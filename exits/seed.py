"""Build exits/seed_paths.json.gz from the retrospective study (offline, no network, no credits).

    python3 run_exits.py seed --retro retro.db retro2.db --series series.jsonl.gz --kol kol.db

Entry points (each one is a trade the bot could have opened):
- krivulja_<X>k: random-sample tokens (unbiased: 99% of launches die) at the first trade where the bonding-curve
  market cap crosses $X; every curve trade after it is known (dense path), then the post-graduation points.
- graduacija: graduated tokens (not instant bundle launches) at the graduation price.
- 100k: graduated tokens at the first post-graduation point at or above $100k market cap.

Post-graduation prices come from the study's PumpSwap samples (src helius): ~100 txs at the end of each slice
(0-6 h hourly, then 6-12 h steps to 7 days), so inside the first hours a path has gaps of up to ~1 h. Stops and
take profits on those gaps fill at the next seen price, as a 1-minute live bot would after an outage. Dense
live paths from paper.db replace this seed as they accumulate (see learn.fit_profile).

Liquidity: curve virtual reserves (vSol = sqrt(k x price), k = 30 SOL x 1.073e9 tokens); after graduation the
pool starts with ~80 real SOL and constant product gives pool SOL ~ 80 x sqrt(price / graduation price).

Influencer calls: timestamps from the KOL history (kol/seed.db.gz, 5,360 X calls on retrospective tokens) are
attached to each path as `kol` (seconds after entry), so the KOL hold rule is learned too.
"""
import gzip
import json
import math
import sqlite3

from . import paths as P

K_CURVE = 30 * 1.073e9
POOL_SOL0 = 80.0
SUPPLY = 1e9
LEVELS_K = (10, 20, 40)


def _curve_liq(price, usd):
    return 2 * math.sqrt(K_CURVE * price) * usd


def _series(path):
    out = {}
    with gzip.open(path, "rt") as f:
        for line in f:
            r = json.loads(line)
            if r.get("candles"):
                out[r["mint"]] = r
    return out


def _post(series_row, t_grad, p_grad):
    """[(ts, price, pool SOL)] after graduation, sorted, dust/rent outliers dropped (a point more than 20x away
    from both neighbours is a mispriced tx, not a move)."""
    c = sorted((x[0], x[2]) for x in series_row["candles"] if x[2] and x[2] > 0 and x[0] >= t_grad)
    keep = []
    for i, (t, p) in enumerate(c):
        a = c[i - 1][1] if i else p_grad
        b = c[i + 1][1] if i + 1 < len(c) else p
        if (p > 20 * a and p > 20 * b) or (p < a / 20 and p < b / 20):
            continue
        keep.append((t, p, POOL_SOL0 * math.sqrt(p / p_grad)))
    return keep


def _calls(kol_db):
    """mint -> sorted timestamps of influencer calls (not post-pump bragging) from the KOL history."""
    if not kol_db:
        return {}
    con = sqlite3.connect(f"file:{kol_db}?mode=ro", uri=True)
    out = {}
    for token, ts in con.execute("SELECT token, ts FROM calls WHERE kind='call' ORDER BY ts"):
        out.setdefault(token, []).append(ts)
    con.close()
    return out


def _attach(path, mint, calls):
    path["mint"] = mint
    t0 = path["ts"]
    rel = [c - t0 for c in calls.get(mint, ()) if -3600 <= c - t0 <= 7 * 86400]
    if rel:
        path["kol"] = rel
    return path


def build(retro_dbs, series_path, usd=96.0, tol=0.03, max_points=160, kol_db=None):
    series = _series(series_path)
    calls = _calls(kol_db)
    out, counts = [], {}
    for db in retro_dbs:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        toks = con.execute("""SELECT mint, stratum, t_create, t_grad, complete FROM tokens
                              WHERE fetched_at IS NOT NULL AND err IS NULL AND t_create IS NOT NULL""").fetchall()
        for mint, stratum, t_create, t_grad, complete in toks:
            if t_grad is not None and t_grad - t_create < 60:
                continue  # instant bundle launch: no tradable curve, no honest graduation entry
            trs = [(ts, p) for ts, p, sol in con.execute(
                "SELECT ts, price, sol FROM trades WHERE mint=? AND price>0 ORDER BY n", (mint,))
                   if abs(sol or 0) >= 0.01]
            if len(trs) < 5 or sorted(p for _, p in trs)[len(trs) // 2] * SUPPLY < 14:
                continue  # quoted in another token, not SOL
            srow = series.get(mint)
            p_grad = None
            if t_grad:
                before = [p for ts, p in trs if ts <= t_grad][-3:]
                p_grad = sorted(before)[len(before) // 2] if before else None
            post = _post(srow, t_grad, p_grad) if (srow and t_grad and p_grad) else []
            if t_grad and not post:
                continue  # graduated but no price after: outcome unknown, a path would look like a dead token
            if not t_grad and not complete:
                continue  # curve history cut: unknown outcome
            age = lambda ts: (ts - t_create) / 3600  # noqa: E731
            # curve entries, random sample only (the grad stratum would over-represent winners)
            if stratum == "rand":
                for lvl in LEVELS_K:
                    target = lvl * 1000 / usd / SUPPLY
                    i = next((j for j, (_, p) in enumerate(trs) if p >= target and (not t_grad or trs[j][0] < t_grad)), None)
                    if i is None:
                        continue
                    ts0, p0 = trs[i]
                    pts = [(ts - ts0, p / p0, _curve_liq(p, usd)) for ts, p in trs[i + 1:] if not t_grad or ts <= t_grad]
                    pts += [(ts - ts0, p / p0, 2 * sol * usd) for ts, p, sol in post]
                    if not pts:
                        continue
                    name = f"krivulja_{lvl}k"
                    out.append(_attach(P.make("seed", P.classify(p0 * SUPPLY * usd, age(ts0)), ts0, _curve_liq(p0, usd),
                                      p0 * SUPPLY * usd, pts, tol, max_points, entry=name), mint, calls))
                    counts[name] = counts.get(name, 0) + 1
            if stratum == "grad" and post and p_grad:
                pts = [(ts - t_grad, p / p_grad, 2 * sol * usd) for ts, p, sol in post]
                out.append(_attach(P.make("seed", P.classify(p_grad * SUPPLY * usd, age(t_grad)), t_grad,
                                  2 * POOL_SOL0 * usd, p_grad * SUPPLY * usd, pts, tol, max_points, entry="graduacija"), mint, calls))
                counts["graduacija"] = counts.get("graduacija", 0) + 1
                lvl = 1e5 / usd / SUPPLY
                j = next((k for k, (_, p, _) in enumerate(post) if p >= lvl), None)
                if j is not None:
                    ts0, p0, sol0 = post[j]
                    pts = [(ts - ts0, p / p0, 2 * sol * usd) for ts, p, sol in post[j + 1:]]
                    if pts:
                        out.append(_attach(P.make("seed", P.classify(1e5, age(ts0)), ts0, 2 * sol0 * usd, 1e5, pts, tol,
                                          max_points, entry="100k"), mint, calls))
                        counts["100k"] = counts.get("100k", 0) + 1
        con.close()
    return out, {"counts": counts, "usd_per_sol": usd, "tolerance": tol, "max_points": max_points,
                 "with_kol_calls": sum(1 for p in out if p.get("kol"))}
