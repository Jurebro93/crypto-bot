"""Rang za kopiranje (11.11.2026, Jure): one score 0-100 for "whom to copy", wallets and influencers alike. It
replaces the old copy ocjena (wallets/pnl copy_score = profitability WITH absolute SOL PnL x style penalties), which
put a wallet that made 63 % of its PnL on one trade, entering at ~$2.5k market cap, at the top of "Za kopiranje".

Per wallet, over the last WINDOW_D days, CLOSED positions only (wallets/pnl.positions: sold 98 %+; a position is in
the window by the time of its last sale):
  n           closed tokens; MIN_N+ = "dokazan"
  roi         realized PnL / total invested (SOL / SOL)
  median      median return per token (realized / cost), not the mean (one +900 % does not make a trader)
  win_lo      Wilson lower bound (one-sided 90 %, z = Z90) of the share of tokens closed in profit; the score uses
              the lower bound, never the raw share (5 of 5 does not beat 40 of 55)
  pf          profit factor = sum of the wins / sum of the losses
  conc        the largest trade's share of the total PnL (only while the total is positive); pnl_ex_top = PnL
              without that one trade. The penalty (conc_hi) is "more than CONC_MAX of the result hangs on one trade",
              i.e. pnl_ex_top < (1 - CONC_MAX) x PnL: with a total at or under zero and any winning trade that holds
              too (without its best trade the source loses), so a source barely in plus is never punished harder
              than one in minus
  liq         median pool liquidity (USD) at his entries: a stored pool snapshot within SNAP_TOL_S of the entry
              (kol.db snaps, hype.db token_pulse / hype_snapshots); else, for a pump.fun mint, the constant-product
              estimate from his own entry price (pool_liq_usd, PumpSwap after migration, LP burned); else unknown.
              Known for fewer than half of the entries = unknown.
  slip        round-trip cost of OUR stake (STAKE_SOL) at that liquidity, the cost formula of trade/cost.py:
              cost(size_usd, liq) = 2 x fee_side + 2 x size_usd / (liq / 2 + size_usd), fee_side = league/store.FEE
  lag         our entry delay: median fast.db signals.latency_s of this source (fast_check), else the Autopilot's
              copy lag (league.db copy_log ts - ev_ts of its entries), else LAG_DEFAULT_S
  avail       the share of his gain still there after our lag: (max price after entry+lag - price at entry+lag) /
              (max price after entry - entry price), from stored series (hype.db live_trades, kept 48 h; for
              influencers minute.db call_candles, 4 h); median over the entries where it is known
  recency     closed tokens weighted 0.5 ** (age / HALF_LIFE_D) (age from the last sale); n7 = closed in 7 days
  stake       average SOL per token: shown on the details row, never in the score
SCORE (0-100) = 100 x sum(WEIGHTS[k] x component k), every component in [0, 1] (components()); a concentration over
CONC_MAX multiplies the score by CONC_MULT. Absolute SOL PnL is NOT in the score (no SOL amount reaches components()).
Flags: proven = n >= MIN_N ("dokazan"); copyable = median entry liquidity known and >= MIN_LIQ_USD. "Nije kopirljivo"
is shown on the pages but never copied with real money (gate(): ui/autopilot.auto_targets, kol/chainwatch copy group,
league/copy real-money entries); neither is a source with n < MIN_N.

Influencers: the same shape over their calls (kol.db calls kind 'call' only, so PR #119's 'flash' rows and bots'
'bot' rows are out; the FIRST call per account and token): return = the close 4 h after the call (events.db
call_outcomes.change_4h, the night batch) where measured, else the 1-h result (calls.r1h); one equal stake per call,
so roi = the mean return. Liquidity at the call: kol.db snaps near it, else the pump.fun estimate from calls.mcap0.

run() (run_wallets.py rang, after `dokazani`) ranks both, replaces copy_rank in wallets.db and prints one summary line;
once per database (copy_rank_kv), the block "rang za kopiranje: prije ... / poslije ..." with the old and new top 10
and the data coverage, for the Render log. Read-only on every other database; no API call, no cost.
"""
import bisect
import json
import math
import os
import sqlite3
import statistics
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WINDOW_D = 30
MIN_N = 10                   # closed tokens (calls) for "dokazan"
MIN_LIQ_USD = 15_000         # median pool liquidity at his entries; below = "nije kopirljivo"
CONC_MAX, CONC_MULT = 0.50, 0.6
HALF_LIFE_D = 7.0
Z90 = 1.645                  # one-sided 90 % (Wilson lower bound)
STAKE_SOL = (0.10, 0.15)     # our stake; the score uses the larger (worse) one
MIN_SOL = 0.02               # positions smaller than this are dust (wallets/pnl.score's min_sol)
# The score's parts and their weights, in ONE place (sum 1.0, tests/test_rang_offline checks it).
#   win      Wilson lower bound of the win rate, WIN_RANGE -> 0..1
#   median   median return per token, MEDIAN_RANGE -> 0..1
#   pf       profit factor (capped at 5), PF_RANGE -> 0..1
#   copy     copyability: (COST_MAX - cost of our stake) / (COST_MAX - 2 x fee) x the median share of the gain left
#            after our lag over his entries (AVAIL_DEFAULT for an entry no stored series covers); 0 while the entry
#            liquidity is unknown
#   recency  decayed closed tokens / RECENCY_FULL
WEIGHTS = {"win": 0.30, "median": 0.25, "pf": 0.15, "copy": 0.20, "recency": 0.10}
WIN_RANGE = (0.25, 0.65)
MEDIAN_RANGE = (-0.20, 0.40)
PF_RANGE = (1.0, 3.0)
COST_MAX = 0.08
AVAIL_DEFAULT = 0.8          # Pretpostavka: no series = most of the gain still there after a ~30-60 s lag
RECENCY_FULL = 5.0
PF_CAP = 10.0                # no losing token at all: shown as this, the component caps at 5 anyway
LAG_DEFAULT_S = {"wallet": 30, "kol": 60}   # Pretpostavka: Helius webhook + copy pass / X poll + copy pass
SNAP_TOL_S = 30 * 60
SERIES_TOL_S = 300           # a price point this late after entry+lag still stands for it
AVAIL_HORIZON_S = 4 * 3600
SOL_USD_DEFAULT = 150.0      # Pretpostavka when market.db has no SOL price for the day
# pump.fun -> PumpSwap migration: ~79 SOL and ~206.9M of the 1B tokens go into the pool and the LP is burned, so the
# pool stays constant product: SOL reserve x = sqrt(K x mcap_sol) with K = 79 x 206.9e6 / 1e9. On the bonding curve
# the (virtual) reserve is larger, so this estimate is the cautious one for both.
PUMP_SUPPLY = 1e9
PUMP_K = 79.0 * 206.9e6 / PUMP_SUPPLY
BAD = frozenset({"bot", "rugger", "bundler", "insider", "dev", "cex", "mev", "sniper", "funder_of_rugger", "izbačen"})
WATCH = (("8xiS", "aftH"),)  # the owner's example (11.11.): its places before/after go into the one-time block
KV_BEFORE_AFTER = "prije_poslije_1111"

try:
    from league.store import FEE as FEE_SIDE
except Exception:  # noqa: BLE001 - league/ missing (a copy of the module): the same 1 % per side
    FEE_SIDE = 0.01

SCHEMA = """
CREATE TABLE IF NOT EXISTS copy_rank (kind TEXT, target TEXT, as_of INTEGER, score REAL, proven INTEGER,
    copyable INTEGER, n INTEGER, data TEXT, PRIMARY KEY (kind, target));
CREATE TABLE IF NOT EXISTS copy_rank_kv (k TEXT PRIMARY KEY, v TEXT);
"""


# ---------- pure parts --------------------------------------------------------------------------------------------

def _clamp(x):
    return max(0.0, min(1.0, x))


def _scale(x, lo, hi):
    return _clamp((x - lo) / (hi - lo))


def wilson_low(k, n, z=Z90):
    """Lower bound of the Wilson interval of k successes in n (one-sided 90 % with z = 1.645): 5 of 5 -> ~0.65,
    40 of 55 -> ~0.62, 0 of n -> 0."""
    if not n:
        return 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (c - r) / d)


def cost(size_usd, liq):
    """Round-trip cost of a stake of size_usd in a pool of liq USD (both sides): 2 x fee per side + 2 x the price
    impact. trade/cost.round_trip; None for an unknown pool."""
    if not liq or liq <= 0 or size_usd is None:
        return None
    from trade import cost as _cost   # 11.11.: the one cost model (calibrated on our own orders when there are some)
    return _cost.round_trip(size_usd, liq)


def decay(age_s, half_life_d=HALF_LIFE_D):
    return 0.5 ** (max(0.0, age_s) / 86400 / half_life_d)


def is_pump(mint):
    return bool(mint) and str(mint).endswith("pump")


def pool_liq_usd(mcap_sol, sol_usd):
    """Liquidity (USD, both sides) of a pump.fun token's constant-product pool at a market cap of mcap_sol SOL."""
    if not mcap_sol or mcap_sol <= 0 or not sol_usd:
        return None
    return 2 * math.sqrt(PUMP_K * mcap_sol) * sol_usd


def avail_share(points, t0, p0, lag_s, end, tol_s=SERIES_TOL_S):
    """Share of the gain after an entry at t0 (price p0) still there for a copy lag_s later:
    (max after t0+lag - price at t0+lag) / (max after t0 - p0). points: [(ts, high, price)] (a trade: high = price).
    None when the series does not cover t0+lag (within tol_s) or there was no gain after his entry."""
    if not p0 or p0 <= 0:
        return None
    pts = sorted(p for p in points if t0 <= p[0] <= end and p[2] and p[2] > 0)
    tl = t0 + (lag_s or 0)
    after = [p for p in pts if p[0] >= tl]
    if not after or after[0][0] > tl + tol_s:
        return None
    top = max([p0] + [p[1] for p in pts])
    if top <= p0:
        return None
    return _clamp((max(p[1] for p in after) - after[0][2]) / (top - p0))


def candle_points(candles, ts, wick=3.0):
    """minute.db candles [(t, o, h, l, c, v)] -> points for avail_share: the open at the minute's start and the close
    at its end, the high capped like kol/minute (a one-print wick counts up to wick x the body)."""
    out = []
    for c in sorted(candles):
        t, o, h, cl = c[0], c[1], c[2], c[4]
        if t + 60 <= ts:
            continue
        hi = min(h, max(o, cl) * wick) if o and cl else h
        out.append((max(t, ts), hi, o))
        out.append((t + 59, hi, cl))
    return out


def metrics(items, now, lag_s=None, lag_src=None, sol_usd=SOL_USD_DEFAULT):
    """items: [{ret, pnl, cost, t0, t1, liq, liq_src, avail, hold_min}] closed tokens (calls) -> the numbers of the
    ranking. pnl/cost: SOL for a wallet, 1 per call for an influencer."""
    n = len(items)
    pnls = [i["pnl"] for i in items]
    rets = [i["ret"] for i in items]
    inv = sum(i["cost"] for i in items)
    total = sum(pnls)
    gains = sum(p for p in pnls if p > 0)
    losses = -sum(p for p in pnls if p < 0)
    wins = sum(1 for p in pnls if p > 0)
    top = max(pnls) if pnls else 0.0
    liqs = [i["liq"] for i in items if i.get("liq")]
    med_liq = statistics.median(liqs) if liqs and 2 * len(liqs) >= n else None
    src = {}
    for i in items:
        if i.get("liq"):
            src[i.get("liq_src") or "?"] = src.get(i.get("liq_src") or "?", 0) + 1
    av = [i["avail"] for i in items if i.get("avail") is not None]
    # the score takes every entry: its measured share, AVAIL_DEFAULT where no series covers it (one measured entry
    # out of 20 must not decide alone)
    av_eff = [i["avail"] if i.get("avail") is not None else AVAIL_DEFAULT for i in items]
    holds = [i["hold_min"] for i in items if i.get("hold_min") is not None]
    sol_usd = sol_usd or SOL_USD_DEFAULT
    return {"n": n, "wins": wins, "win": wins / n if n else 0.0, "win_lo": wilson_low(wins, n),
            "roi": total / inv if inv else None, "median": statistics.median(rets) if rets else None,
            "pf": gains / losses if losses else (PF_CAP if gains else 0.0),
            "pnl": total, "pnl_ex_top": total - top if pnls else 0.0,
            "conc": top / total if total > 0 and top > 0 else None,
            "conc_hi": bool(pnls) and top > 0 and (total <= 0 or top / total > CONC_MAX),
            "liq": med_liq, "liq_known": len(liqs), "liq_src": src,
            "slip_lo": cost(STAKE_SOL[0] * sol_usd, med_liq), "slip": cost(STAKE_SOL[1] * sol_usd, med_liq),
            "lag_s": lag_s, "lag_src": lag_src, "avail": statistics.median(av) if av else None, "avail_n": len(av),
            "avail_eff": statistics.median(av_eff) if av_eff else AVAIL_DEFAULT,
            "n7": sum(1 for i in items if now - i["t1"] <= 7 * 86400),
            "rec": sum(decay(now - i["t1"]) for i in items),
            "stake": inv / n if n else None, "hold_min": statistics.median(holds) if holds else None,
            "last_ts": max((i["t1"] for i in items), default=None)}


def components(m):
    """{part: 0..1} of the score (WEIGHTS). Takes only shares and ratios: no SOL amount enters here."""
    copy_ = 0.0
    if m.get("liq") is not None and m.get("slip") is not None:
        av = m.get("avail_eff")
        av = (m["avail"] if m.get("avail") is not None else AVAIL_DEFAULT) if av is None else av
        copy_ = _scale(COST_MAX - m["slip"], 0.0, COST_MAX - 2 * FEE_SIDE) * av
    return {"win": _scale(m.get("win_lo") or 0.0, *WIN_RANGE),
            "median": _scale(m["median"], *MEDIAN_RANGE) if m.get("median") is not None else 0.0,
            "pf": _scale(min(m.get("pf") or 0.0, 5.0), *PF_RANGE),
            "copy": copy_, "recency": _clamp((m.get("rec") or 0.0) / RECENCY_FULL)}


def score(m):
    """(score 0-100, components, concentration multiplier)."""
    c = components(m)
    raw = 100 * sum(WEIGHTS[k] * c[k] for k in WEIGHTS)
    hi = m.get("conc_hi")
    if hi is None:   # a row without the flag (older callers): the share alone
        hi = m.get("conc") is not None and m["conc"] > CONC_MAX
    pen = CONC_MULT if hi else 1.0
    return round(raw * pen, 1), c, pen


def copy_flags(m):
    """(proven, copyable, why not copyable in Croatian or "")."""
    proven = (m.get("n") or 0) >= MIN_N
    if m.get("liq") is None:
        return proven, False, "likvidnost na ulazu nepoznata"
    if m["liq"] < MIN_LIQ_USD:
        return proven, False, f"medijan likvidnosti na ulazu ${m['liq'] / 1000:.1f}k, ispod ${MIN_LIQ_USD // 1000}k"
    return proven, True, ""


def evaluate(items, now, lag_s=None, lag_src=None, sol_usd=SOL_USD_DEFAULT):
    """One ranked row (dict) from a source's closed tokens / calls."""
    m = metrics(items, now, lag_s, lag_src, sol_usd)
    sc, comp, pen = score(m)
    proven, copyable, why = copy_flags(m)
    m.update(score=sc, parts={k: round(v, 3) for k, v in comp.items()}, pen=pen, proven=proven, copyable=copyable,
             why=why)
    return m


# ---------- stored data (read-only) -------------------------------------------------------------------------------

def _paths(paths=None):
    p = dict(paths or {})

    def get(k, fn):
        if k not in p:
            try:
                p[k] = fn()
            except Exception:  # noqa: BLE001
                p[k] = None
        return p[k]
    get("hype", lambda: os.environ.get("HYPE_DB") or os.path.join(ROOT, "hype.db"))
    get("kol", lambda: os.environ.get("KOL_DB") or os.path.join(ROOT, "kol.db"))
    get("league", lambda: __import__("league.store", fromlist=["DB"]).DB)
    get("market", lambda: __import__("market.store", fromlist=["DB"]).DB)
    get("fast", lambda: __import__("fast.store", fromlist=["db_path"]).db_path())
    get("minute", lambda: __import__("kol.minute", fromlist=["db_path"]).db_path())
    get("events", lambda: __import__("events.store", fromlist=["db_path"]).db_path())
    return p


def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return None


def _chunks(xs, n=400):
    xs = list(xs)
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def sol_usd_days(path):
    """{UTC day start: SOL/USD} from market.db price (run_market.py); {} without it."""
    con = _ro(path)
    if con is None:
        return {}
    try:
        return {int(d): float(u) for d, u in con.execute("SELECT day, usd FROM price WHERE usd > 0")}
    except sqlite3.Error:
        return {}
    finally:
        con.close()


def sol_at(days, ts):
    """SOL/USD of ts's day (or the nearest earlier known day within a week), else SOL_USD_DEFAULT."""
    if days:
        d = int(ts) // 86400 * 86400
        for k in range(8):
            v = days.get(d - k * 86400)
            if v:
                return v
    return SOL_USD_DEFAULT


SNAP_SOURCES = (("kol", "snaps", "token", "ts", "liq"), ("hype", "token_pulse", "token", "ts", "liquidity"),
                ("hype", "hype_snapshots", "token", "ts", "liquidity"))


def snapshot_liq(entries, paths):
    """{(mint, ts): liq USD} for [(mint, ts)] from the stored pool snapshots nearest each entry within SNAP_TOL_S."""
    out = {}
    if not entries:
        return out
    by_mint = {}
    for m, t in entries:
        by_mint.setdefault(m, set()).add(int(t))
    lo = min(t for _, t in entries) - SNAP_TOL_S
    hi = max(t for _, t in entries) + SNAP_TOL_S
    for db, table, tc, sc, lc in SNAP_SOURCES:
        con = _ro(paths.get(db))
        if con is None:
            continue
        try:
            for part in _chunks([m for m in by_mint if any((m, t) not in out for t in by_mint[m])]):
                q = ",".join("?" * len(part))
                snaps = {}
                for tok, ts, liq in con.execute(f"SELECT {tc}, {sc}, {lc} FROM {table} WHERE {tc} IN ({q}) AND {sc} >= ? "
                                                f"AND {sc} <= ? AND {lc} > 0", (*part, lo, hi)):
                    snaps.setdefault(tok, []).append((int(ts), float(liq)))
                for tok, ss in snaps.items():
                    ss.sort()
                    tss = [s[0] for s in ss]
                    for t in by_mint[tok]:
                        if (tok, t) in out:
                            continue
                        i = bisect.bisect_left(tss, t)
                        best = min((ss[j] for j in (i - 1, i) if 0 <= j < len(ss)), key=lambda s: abs(s[0] - t),
                                   default=None)
                        if best and abs(best[0] - t) <= SNAP_TOL_S:
                            out[(tok, t)] = best[1]
        except sqlite3.Error:
            pass
        finally:
            con.close()
    return out


def lags(kind, targets, paths, now):
    """{target: (lag_s, source)} for the given wallets / handles: fast.db latency (fast_check), else the Autopilot's
    copy lag (league.db copy_log entries), else LAG_DEFAULT_S. Handles compare without case and '@'."""
    norm = (lambda x: x) if kind == "wallet" else (lambda x: str(x or "").lower().lstrip("@"))
    want = {norm(t): t for t in targets}
    got = {}
    con = _ro(paths.get("fast"))
    if con is not None:
        try:
            per = {}
            for sid, lat in con.execute("SELECT source_id, latency_s FROM signals WHERE latency_s IS NOT NULL AND "
                                        "latency_s >= 0 AND decided_ts >= ?", (now - WINDOW_D * 86400,)):
                k = norm(sid)
                if k in want:
                    per.setdefault(k, []).append(float(lat))
            for k, xs in per.items():
                got[want[k]] = (statistics.median(xs), "fast")
        except sqlite3.Error:
            pass
        finally:
            con.close()
    con = _ro(paths.get("league"))
    if con is not None:
        try:
            per = {}
            for tgt, d in con.execute("SELECT f.target, c.ts - c.ev_ts FROM copy_log c JOIN follows f ON f.id = c.follow_id "
                                      "WHERE f.kind = ? AND c.action = 'ulaz' AND c.ts >= ? AND c.ev_ts > 0",
                                      (kind, now - WINDOW_D * 86400)):
                k = norm(tgt)
                if k in want and want[k] not in got and d is not None and d >= 0:
                    per.setdefault(k, []).append(float(d))
            for k, xs in per.items():
                got[want[k]] = (statistics.median(xs), "copy_log")
        except sqlite3.Error:
            pass
        finally:
            con.close()
    return {t: got.get(t, (float(LAG_DEFAULT_S[kind]), "zadano")) for t in targets}


def live_points(mints, since, paths):
    """{mint: [(ts, price_sol, price_sol)]} from hype.db live_trades (the PumpPortal feed, kept 48 h)."""
    out = {}
    con = _ro(paths.get("hype"))
    if con is None or not mints:
        return out
    try:
        for part in _chunks(sorted(mints)):
            q = ",".join("?" * len(part))
            for m, ts, px in con.execute(f"SELECT mint, ts, price_sol FROM live_trades WHERE mint IN ({q}) AND ts >= ? "
                                         f"AND price_sol > 0", (*part, int(since))):
                out.setdefault(m, []).append((int(ts), float(px), float(px)))
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return out


# ---------- wallets -------------------------------------------------------------------------------------------------

def wallet_items(trades, now, days=WINDOW_D):
    """A wallet's stored trades -> closed tokens of the window (by last sale): [{mint, t0, t1, px0, cost, pnl, ret,
    hold_min}]. px0 = SOL per token of the first buy (his own fill)."""
    from wallets import pnl
    first = {}
    for r in sorted(trades, key=lambda r: r["ts"]):
        if r["kind"] == "buy" and r["mint"] not in first and r["tokens"] and r["tokens"] > 0:
            first[r["mint"]] = r
    lo = now - days * 86400
    out = []
    for p in pnl.positions(trades).values():
        if p.get("status") != "closed" or p.get("cost", 0) < MIN_SOL or not p.get("last_sell") or p["last_sell"] < lo:
            continue
        f = first.get(p["mint"])
        px0 = (-f["sol"] / f["tokens"]) if f and f["sol"] and f["sol"] < 0 else None
        out.append({"mint": p["mint"], "t0": p["first_buy"] or p["last_sell"], "t1": p["last_sell"], "px0": px0,
                    "cost": p["cost"], "pnl": p["realized"], "ret": p["realized"] / p["cost"], "hold_min": p.get("hold_min")})
    return out


def rank_wallets(con, now=None, paths=None, days=WINDOW_D):
    """[row] for every scored wallet (no bad label) with a closed token in the window. con: wallets.db."""
    now = int(now or time.time())
    paths = _paths(paths)
    lo = now - days * 86400
    per = {}
    meta = {}
    for w, lab, last in con.execute("SELECT wallet, labels, last_tx_ts FROM wallets WHERE scored_at IS NOT NULL AND "
                                    "COALESCE(last_tx_ts, ?) >= ?", (now, lo)).fetchall():
        try:
            labels = set(json.loads(lab or "[]"))
        except ValueError:
            labels = set()
        if labels & BAD:
            continue
        trades = [dict(zip(("sig", "ts", "mint", "tokens", "sol", "kind"), r)) for r in con.execute(
            "SELECT sig, ts, mint, tokens, sol, kind FROM wallet_trades WHERE wallet=? AND ts>=? ORDER BY ts",
            (w, now - 2 * days * 86400))]
        items = wallet_items(trades, now, days)
        if items:
            per[w] = items
            meta[w] = {"last_tx": max([last or 0] + [t["ts"] for t in trades]) or None}
    sols = sol_usd_days(paths.get("market"))
    entries = {(i["mint"], int(i["t0"])) for items in per.values() for i in items}
    snap = snapshot_liq(entries, paths)
    recent = {i["mint"] for items in per.values() for i in items if i["t0"] >= now - 48 * 3600}
    pts = live_points(recent, now - 48 * 3600, paths)
    lag = lags("wallet", list(per), paths, now)
    rows = []
    for w, items in per.items():
        lag_s, lag_src = lag[w]
        for i in items:
            liq = snap.get((i["mint"], int(i["t0"])))
            i["liq_src"] = "snimka" if liq else None
            if not liq and is_pump(i["mint"]) and i["px0"]:
                liq = pool_liq_usd(i["px0"] * PUMP_SUPPLY, sol_at(sols, i["t0"]))
                i["liq_src"] = "model" if liq else None
            i["liq"] = liq
            i["avail"] = (avail_share(pts.get(i["mint"]) or [], i["t0"], i["px0"], lag_s,
                                      min(max(i["t1"], i["t0"] + lag_s + 60), i["t0"] + AVAIL_HORIZON_S))
                          if i["mint"] in pts else None)
        r = evaluate(items, now, lag_s, lag_src, sol_at(sols, now))
        r["target"] = w
        r["last_ts"] = meta[w]["last_tx"] or r["last_ts"]
        rows.append(r)
    rows.sort(key=lambda r: -r["score"])
    return rows


# ---------- influencers ---------------------------------------------------------------------------------------------

def kol_calls(paths, now, days=WINDOW_D):
    """[(tweet_id, token, handle, ts, mcap0, r1h)] the first call per account and token in the window (kind 'call')."""
    con = _ro(paths.get("kol"))
    if con is None:
        return []
    try:
        rows = con.execute("SELECT tweet_id, token, handle, ts, mcap0, r1h FROM calls WHERE kind = 'call' AND ts >= ? "
                           "AND ts <= ? ORDER BY ts", (now - days * 86400, now - 3600)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    seen, out = set(), []
    for r in rows:
        k = (r[2], r[1])
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def four_hour(paths, since):
    """{(tweet_id, mint): change_4h} measured by the night batch (events.db call_outcomes)."""
    con = _ro(paths.get("events"))
    if con is None:
        return {}
    try:
        return {(t, m): c for t, m, c in con.execute("SELECT tweet_id, mint, change_4h FROM call_outcomes WHERE kind = "
                                                     "'call' AND ts >= ? AND change_4h IS NOT NULL", (since,))}
    except sqlite3.Error:
        return {}
    finally:
        con.close()


def minute_candles(paths, tokens):
    """{token: candles} from minute.db call_candles (1-min, 4 h after each measured call)."""
    out = {}
    try:
        from kol import minute
    except Exception:  # noqa: BLE001
        return out
    con = _ro(paths.get("minute"))
    if con is None:
        return out
    try:
        for part in _chunks(sorted(tokens)):
            q = ",".join("?" * len(part))
            for tok, blob in con.execute(f"SELECT token, data FROM call_candles WHERE token IN ({q})", part):
                try:
                    out[tok] = minute._unpack(blob)
                except Exception:  # noqa: BLE001
                    pass
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return out


def rank_kols(now=None, paths=None, days=WINDOW_D):
    """[row] per influencer with a measured call in the window, best first."""
    now = int(now or time.time())
    paths = _paths(paths)
    calls = kol_calls(paths, now, days)
    if not calls:
        return []
    r4 = four_hour(paths, now - days * 86400 - 86400)
    sols = sol_usd_days(paths.get("market"))
    snap = snapshot_liq({(c[1], int(c[3])) for c in calls}, paths)
    candles = minute_candles(paths, {c[1] for c in calls})
    per, last = {}, {}
    for tid, tok, h, ts, mc0, r1 in calls:
        last[h] = max(last.get(h, 0), ts)
        ret, hor = r4.get((tid, tok)), 240
        if ret is None:
            ret, hor = r1, 60
        if ret is None:
            continue
        liq = snap.get((tok, int(ts)))
        src = "snimka" if liq else None
        if not liq and is_pump(tok) and mc0:
            s = sol_at(sols, ts)
            liq = pool_liq_usd(mc0 / s, s)
            src = "model" if liq else None
        per.setdefault(h, []).append({"mint": tok, "t0": ts, "t1": ts, "ret": float(ret), "pnl": float(ret), "cost": 1.0,
                                      "liq": liq, "liq_src": src, "hold_min": hor, "_c": candles.get(tok)})
    lag = lags("kol", list(per), paths, now)
    rows = []
    for h, items in per.items():
        lag_s, lag_src = lag[h]
        for i in items:
            cs = i.pop("_c")
            av = None
            if cs:
                pts = candle_points(cs, i["t0"])
                p0 = next((p[2] for p in pts if p[0] >= i["t0"]), None)
                av = avail_share(pts, i["t0"], p0, lag_s, i["t0"] + AVAIL_HORIZON_S, tol_s=90)
            i["avail"] = av
        r = evaluate(items, now, lag_s, lag_src, sol_at(sols, now))
        r["target"] = h
        r["last_ts"] = last.get(h) or r["last_ts"]
        rows.append(r)
    rows.sort(key=lambda r: -r["score"])
    return rows


# ---------- storage and readers -------------------------------------------------------------------------------------

KEEP = ("score", "proven", "copyable", "why", "n", "wins", "win", "win_lo", "roi", "median", "pf", "pnl", "pnl_ex_top",
        "conc", "conc_hi", "liq", "liq_known", "liq_src", "slip_lo", "slip", "lag_s", "lag_src", "avail", "avail_n", "avail_eff",
        "n7", "rec", "stake", "hold_min", "last_ts", "parts", "pen")


def _round(v):
    if isinstance(v, float):
        return round(v, 5) if abs(v) < 100 else round(v, 1)
    if isinstance(v, dict):
        return {k: _round(x) for k, x in v.items()}
    return v


def ensure(con):
    con.executescript(SCHEMA)


def save(con, kind, rows, now=None):
    """Replace the kind's rows of copy_rank with this run's."""
    ensure(con)
    now = int(now or time.time())
    con.execute("DELETE FROM copy_rank WHERE kind = ?", (kind,))
    con.executemany("INSERT OR REPLACE INTO copy_rank VALUES (?,?,?,?,?,?,?,?)",
                    [(kind, r["target"], now, r["score"], int(r["proven"]), int(r["copyable"]), r["n"],
                      json.dumps({k: _round(r.get(k)) for k in KEEP}, separators=(",", ":"))) for r in rows])


_CACHE = {}
CACHE_S = 60


def clear():
    _CACHE.clear()


def load(kind="wallet", path=None):
    """{target: row} of the latest run (read-only, cached CACHE_S); {} without the table or before the first run.
    A row: score, proven, copyable, n, as_of and the stored numbers (KEEP)."""
    if path is None:
        from wallets import store as wstore
        path = wstore.DB
    key = (path, kind)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < CACHE_S:
        return hit[1]
    out = {}
    con = _ro(path)
    if con is not None:
        try:
            for t, as_of, sc, pr, cp, n, data in con.execute(
                    "SELECT target, as_of, score, proven, copyable, n, data FROM copy_rank WHERE kind = ?", (kind,)):
                try:
                    d = json.loads(data or "{}")
                except ValueError:
                    d = {}
                d.update(target=t, as_of=as_of, score=sc, proven=bool(pr), copyable=bool(cp), n=n)
                out[t] = d
        except sqlite3.Error:
            out = {}
        finally:
            con.close()
    _CACHE[key] = (time.time(), out)
    return out


def get(kind, target, path=None):
    """One row by target (influencer handles without case and '@'), or None."""
    rows = load(kind, path)
    if not target:
        return None
    if target in rows:
        return rows[target]
    if kind == "kol":
        t = str(target).lower().lstrip("@")
        for k, r in rows.items():
            if k.lower().lstrip("@") == t:
                return r
    return None


def ranked(kind="wallet", path=None, proven=None, copyable=None):
    """Rows of the latest run, best score first, optionally only proven / copyable ones."""
    rows = [r for r in load(kind, path).values() if (proven is None or r["proven"] == proven)
            and (copyable is None or r["copyable"] == copyable)]
    rows.sort(key=lambda r: (-(r.get("score") or 0), r["target"]))
    return rows


def gate(kind, target, path=None):
    """Real money (11.11., Jure): (True, "") when the source may be copied, (False, why) when not ("nije kopirljivo"
    or fewer than MIN_N closed tokens / calls), (None, "") while there is no ranking of this kind yet (fresh deploy,
    table missing): no verdict, nothing blocked. A source the latest run did not rank has no closed token in the
    window, so it is not proven."""
    rows = load(kind, path)
    if not rows:
        return None, ""
    r = get(kind, target, path)
    if r is None:
        return False, f"nije dokazan: nema zatvorenih {'tradeova' if kind == 'wallet' else 'poziva'} u {WINDOW_D} dana"
    if not r["copyable"]:
        return False, "nije kopirljivo: " + (r.get("why") or "likvidnost na ulazu")
    if not r["proven"]:
        return False, (f"nije dokazan: {r['n']} {'zatvorenih tokena' if kind == 'wallet' else 'poziva'} u "
                       f"{WINDOW_D} dana (treba {MIN_N})")
    return True, ""


# ---------- the run and the one-time before/after block -------------------------------------------------------------

def short(w):
    w = str(w or "")
    return f"{w[:4]}…{w[-4:]}" if len(w) > 10 else w


def old_top(con, n=10):
    """The old copy list (explain.shortlist with run_wallets copy's defaults: copy_score 50+, 10+ closed, no bad label)
    by copy_score: [(wallet, copy_score)]."""
    out = []
    try:
        rows = con.execute("SELECT wallet, copy_score, stats, labels FROM wallets WHERE copy_score >= 50 "
                           "ORDER BY copy_score DESC, score DESC").fetchall()
    except sqlite3.Error:
        return out
    for w, cs, st, lab in rows:
        try:
            s, labels = json.loads(st or "{}"), set(json.loads(lab or "[]"))
        except ValueError:
            continue
        if labels & BAD or (s.get("closed") or 0) < 10:
            continue
        out.append((w, cs))
        if len(out) >= n:
            break
    return out


def new_top(rows, n=10):
    return [r for r in rows if r["proven"]][:n]


def coverage(rows):
    """Data coverage of a ranking: entries with a known entry liquidity (snapshot / model), sources not copyable for
    an unknown liquidity, lag sources, entries with a measured gain-after-lag share."""
    ent = sum(r["n"] for r in rows)
    known = sum(r["liq_known"] for r in rows)
    src = {}
    for r in rows:
        for k, v in (r.get("liq_src") or {}).items():
            src[k] = src.get(k, 0) + v
    lag = {}
    for r in rows:
        lag[r.get("lag_src")] = lag.get(r.get("lag_src"), 0) + 1
    return {"sources": len(rows), "entries": ent, "liq_known": known, "liq_src": src,
            "liq_unknown_sources": sum(1 for r in rows if r.get("liq") is None),
            "below_liq": sum(1 for r in rows if r.get("liq") is not None and r["liq"] < MIN_LIQ_USD),
            "lag": lag, "avail_known": sum(r.get("avail_n") or 0 for r in rows),
            "proven": sum(1 for r in rows if r["proven"]), "copyable": sum(1 for r in rows if r["copyable"])}


def _cov_line(name, c):
    src = ", ".join(f"{k} {v}" for k, v in sorted(c["liq_src"].items())) or "nijedna"
    lag = ", ".join(f"{k} {v}" for k, v in sorted(c["lag"].items(), key=lambda x: str(x[0]))) or "–"
    return (f"  {name}: {c['sources']} rangiranih, {c['proven']} dokazanih, {c['copyable']} kopirljivih; likvidnost na "
            f"ulazu poznata za {c['liq_known']} od {c['entries']} ulaza ({src}); nepoznata likvidnost (pa nije "
            f"kopirljivo): {c['liq_unknown_sources']}, ispod ${MIN_LIQ_USD // 1000}k: {c['below_liq']}; lag: {lag}; "
            f"dobitak nakon laga izmjeren na {c['avail_known']} ulaza")


def before_after_text(before, after, kols, cov_w, cov_k, watch=()):
    """The one log block: old top 10 (copy_score) | new top 10 (score), the influencers' new top and the coverage."""
    lines = ["rang za kopiranje: prije (stara copy ocjena) / poslije (nova ocjena 0-100, samo dokazani)"]
    for i in range(max(len(before), len(after), 1)):
        b = f"{short(before[i][0])} copy {before[i][1]:.0f}" if i < len(before) else "–"
        if i < len(after):
            a = after[i]
            liq = "liq ?" if a.get("liq") is None else f"liq {a['liq'] / 1000:.0f}k"
            a = (f"{short(a['target'])} {a['score']:.1f} n {a['n']} {'kopirljiv' if a['copyable'] else 'NIJE kopirljiv'} "
                 f"{liq}" + (f" konc {a['conc']:.0%}" if a.get("conc") is not None else ""))
        else:
            a = "–"
        lines.append(f"  {i + 1:>2}. prije {b:<26} | poslije {a}")
    for w, pb, pa, row in watch:
        lines.append(f"  {short(w)}: prije #{pb or '–'}, poslije #{pa or '–'}"
                     + (f" (ocjena {row['score']:.1f}, {'kopirljiv' if row['copyable'] else 'nije kopirljiv: ' + row['why']}"
                        + (f", konc {row['conc']:.0%}" if row.get("conc") is not None else "") + ")" if row else
                        " (nema zatvorenih u 30 d)"))
    if kols:
        lines.append("  influenceri poslije: " + "; ".join(
            f"{r['target']} {r['score']:.1f} n {r['n']}{'' if r['copyable'] else ' (nije kopirljiv)'}" for r in kols[:10]))
    lines.append(_cov_line("novčanici", cov_w))
    lines.append(_cov_line("influenceri", cov_k))
    return "\n".join(lines)


def watch_places(before, rows_w, con):
    """[(wallet, place before, place after, row)] for the owner's example wallets (WATCH: prefix, suffix)."""
    out = []
    try:
        cands = [w for (w,) in con.execute("SELECT wallet FROM wallets")]
    except sqlite3.Error:
        return out
    after = [r["target"] for r in rows_w if r["proven"]]
    byw = {r["target"]: r for r in rows_w}
    for pre, suf in WATCH:
        for w in cands:
            if w.startswith(pre) and w.endswith(suf):
                pb = next((i + 1 for i, (x, _) in enumerate(before) if x == w), None)
                pa = after.index(w) + 1 if w in after else None
                out.append((w, pb, pa, byw.get(w)))
    return out


def run(con, now=None, paths=None, log=print, once_key=KV_BEFORE_AFTER):
    """Rank wallets and influencers, replace copy_rank, log one line; the first run on this database also logs the
    before/after block (marker once_key in copy_rank_kv). con: wallets.db (the only writer: run_wallets.py)."""
    now = int(now or time.time())
    ensure(con)
    before = old_top(con, 50)
    rows_w = rank_wallets(con, now, paths)
    try:
        rows_k = rank_kols(now, paths)
    except Exception as e:  # noqa: BLE001 - an unreadable kol.db never stops the wallet ranking
        if log:
            log(f"rang: influenceri nisu rangirani ({type(e).__name__}: {e})")
        rows_k = []
    save(con, "wallet", rows_w, now)
    save(con, "kol", rows_k, now)
    cov_w, cov_k = coverage(rows_w), coverage(rows_k)
    done = con.execute("SELECT v FROM copy_rank_kv WHERE k = ?", (once_key,)).fetchone()
    block = None
    if not done:
        block = before_after_text(before[:10], new_top(rows_w), new_top(rows_k), cov_w, cov_k,
                                  watch_places(before, rows_w, con))
        con.execute("INSERT OR REPLACE INTO copy_rank_kv VALUES (?, ?)", (once_key, json.dumps({"ts": now, "text": block})))
    con.commit()
    clear()
    if log:
        log(f"rang za kopiranje: {cov_w['sources']} novčanika ({cov_w['proven']} dokazanih, {cov_w['copyable']} "
            f"kopirljivih), {cov_k['sources']} influencera ({cov_k['proven']} dokazanih, {cov_k['copyable']} kopirljivih)")
        if block:
            log(block)
    return {"wallets": rows_w, "kols": rows_k, "block": block, "coverage": {"wallet": cov_w, "kol": cov_k}}
