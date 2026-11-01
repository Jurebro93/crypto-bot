"""Does the KOL score actually predict anything? Checks that run on every scoring round, no API calls.

  ranges      every KOL score gets an 80% range (bootstrap over his own measured calls, then the same shrink towards
              prior_score as the score). Few calls = wide range. Pages show "48 (35-61)".
  walk-forward for each of the last few weeks: score every KOL only from calls that were already measured before the
              week started (no peeking), then look at the calls made during that week. The top 20% by score must
              hit more often than the rest and than the top 20% by followers (a dumb rule). Verdict:
              "prolazi" (top 20% better by margin+ and not worse than followers), "pada" (top 20% no better than the
              rest), "nejasno" (better by less than the margin: maybe luck) or "malo" (too few calls to tell).
  calibration when the tool's past numbers said "x% of his calls hit", how many of the next calls really hit.
  pair test   two accounts that keep calling the same tokens within minutes: how many such tokens would chance give,
              given how many tokens each of them calls and how many tokens were being called at all in that period
              (hypergeometric). A pair is "dokazan" only with 3+ shared tokens, 3x+ chance and p < 1%.

The verdict also guards the signal: when the score fails the test (cfg validate.gate), "good KOL" counts drop out of
kol_group until it passes again; group size still counts. Results live in kv 'validate' and table pair_tests.
"""
import json
import math
import random
import statistics
import time
import zlib

from kol import score as kscore

DAY = 86400
WEEK = 7 * DAY

DEFAULTS = {"weeks": 4, "min_hist": 3, "top_share": 0.2, "min_n": 30, "margin": 0.05, "boot": 100,
            "pair_min_tokens": 3, "pair_min_lift": 3.0, "pair_max_p": 0.01, "gate": True}


def vcfg(cfg):
    return dict(DEFAULTS, **(cfg.get("validate") or {}))


# ---------------------------------------------------------------- ranges

def _shrink(raw, n, cfg):
    k = n / (n + cfg["prior_calls"])
    return k * raw + (1 - k) * cfg["prior_score"]


def score_range(calls, cfg, boot=100, seed=0):
    """80% range (lo, hi) of the shrunk score from one KOL's calls (dicts with calls columns), or None."""
    mine = [c for c in calls if c["kind"] in ("call", "bot") and c["first_by_kol"] and c["max24"] is not None]
    n = len(mine)
    if not n:
        return None
    rnd = random.Random(seed)
    vals = []
    for _ in range(boot):
        sample = [rnd.choice(mine) for _ in range(n)]
        _, raw = kscore.kol_stats(sample, cfg)
        if raw is not None:
            vals.append(_shrink(raw, n, cfg))
    if not vals:
        return None
    vals.sort()
    return round(vals[int(0.1 * (len(vals) - 1))], 1), round(vals[int(0.9 * (len(vals) - 1))], 1)


def hit_estimate(hits, n, p0, k0):
    """Hit rate shrunk towards p0 with k0 pseudo-calls (Beta mean)."""
    return (hits + p0 * k0) / (n + k0)


# ---------------------------------------------------------------- walk-forward

def _hit(c, cfg):
    return c["max24"] >= cfg["hit_x"]


def _rate(cs, cfg):
    return (sum(1 for c in cs if _hit(c, cfg)) / len(cs)) if cs else None


def week_test(calls, cfg, start, end, foll, bots=()):
    """calls: first calls (kind 'call', first_by_kol) with max24 measured, as dicts. Scores use only calls made at
    least 24 h before `start` (their 24 h outcome was known by then); the test is the calls in [start, end)."""
    v = vcfg(cfg)
    hist, test = {}, []
    for c in calls:
        if c["handle"] in bots:
            continue
        if c["ts"] < start - DAY:
            hist.setdefault(c["handle"], []).append(c)
        elif start <= c["ts"] < end:
            test.append(c)
    all_hist = [c for cs in hist.values() for c in cs]
    p0 = _rate(all_hist, cfg) or 0.0
    scored = {}
    for h, cs in hist.items():
        if len(cs) < v["min_hist"]:
            continue
        _, raw = kscore.kol_stats(cs, cfg)
        if raw is not None:
            hits = sum(1 for c in cs if _hit(c, cfg))
            scored[h] = (_shrink(raw, len(cs), cfg), hit_estimate(hits, len(cs), p0, cfg["prior_calls"]))
    ranked = sorted(scored, key=lambda h: -scored[h][0])
    k = max(1, round(len(ranked) * v["top_share"])) if ranked else 0
    top = set(ranked[:k])
    by_f = sorted(scored, key=lambda h: -(foll.get(h) or 0))
    top_f = set(by_f[:k])
    t_top = [c for c in test if c["handle"] in top]
    t_rest = [c for c in test if c["handle"] in scored and c["handle"] not in top]
    t_foll = [c for c in test if c["handle"] in top_f]
    calib = [(scored[c["handle"]][1], _hit(c, cfg)) for c in test if c["handle"] in scored]
    return {"start": start, "end": end, "kols": len(scored), "top_kols": len(top),
            "n_top": len(t_top), "hit_top": _rate(t_top, cfg), "med_top": kscore._med(c["max24"] for c in t_top),
            "n_rest": len(t_rest), "hit_rest": _rate(t_rest, cfg), "med_rest": kscore._med(c["max24"] for c in t_rest),
            "n_foll": len(t_foll), "hit_foll": _rate(t_foll, cfg),
            "n_all": len(test), "hit_all": _rate(test, cfg), "calib": calib}


BUCKETS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 1.01)]


def verdict(weeks, cfg):
    """Pool the weeks: 'malo' (too few calls), 'prolazi' or 'pada', plus the pooled numbers and calibration."""
    v = vcfg(cfg)

    def pool(key):
        n = sum(w[f"n_{key}"] for w in weeks)
        hits = sum((w[f"hit_{key}"] or 0) * w[f"n_{key}"] for w in weeks)
        return n, (hits / n if n else None)
    n_top, hit_top = pool("top")
    n_rest, hit_rest = pool("rest")
    n_foll, hit_foll = pool("foll")
    n_all, hit_all = pool("all")
    pairs = [p for w in weeks for p in w["calib"]]
    calib = []
    for lo, hi in BUCKETS:
        xs = [(p, h) for p, h in pairs if lo <= p < hi]
        if xs:
            calib.append({"lo": lo, "hi": min(hi, 1.0), "n": len(xs), "said": statistics.mean(p for p, _ in xs),
                          "real": sum(1 for _, h in xs if h) / len(xs)})
    if n_top < v["min_n"] or n_rest < v["min_n"]:
        state = "malo"
    elif hit_top >= hit_rest + v["margin"] and (hit_foll is None or n_foll < v["min_n"] or hit_top >= hit_foll):
        state = "prolazi"
    elif hit_top <= hit_rest:
        state = "pada"
    else:  # better, but by less than the margin: could be luck, no gate
        state = "nejasno"
    return {"state": state, "n_top": n_top, "hit_top": hit_top, "n_rest": n_rest, "hit_rest": hit_rest,
            "n_foll": n_foll, "hit_foll": hit_foll, "n_all": n_all, "hit_all": hit_all, "calib": calib}


def walk_forward(con, cfg, now=None):
    now = now or int(time.time())
    v = vcfg(cfg)
    calls = kscore._rows(con, "SELECT * FROM calls WHERE kind = 'call' AND first_by_kol = 1 AND max24 IS NOT NULL "
                              "AND ts < ?", (now - DAY,))
    foll = dict(con.execute("SELECT handle, COALESCE(followers, 0) FROM kols"))
    bots = {h for h, in con.execute("SELECT handle FROM kols WHERE bot = 1")}
    end = now - DAY  # the last day's calls have no 24 h outcome yet
    weeks = []
    for i in range(v["weeks"]):
        e = end - i * WEEK
        weeks.append(week_test(calls, cfg, e - WEEK, e, foll, bots))
    out = verdict(weeks, cfg)
    out["weeks"] = [{k: w[k] for k in w if k != "calib"} for w in weeks]
    out["ts"] = now
    return out


# ---------------------------------------------------------------- pair test

def hyper_sf(k, total, good, draws):
    """P(X >= k) for X ~ Hypergeometric(total, good, draws)."""
    if k <= 0:
        return 1.0
    hi = min(good, draws)
    if k > hi:
        return 0.0
    den = math.comb(total, draws)
    return min(1.0, sum(math.comb(good, i) * math.comb(total - good, draws - i) for i in range(k, hi + 1)) / den)


def pair_tests(con, cfg):
    """Chance test for every pair that called 2+ of the same tokens within the group window."""
    v = vcfg(cfg)
    rows = con.execute("SELECT token, ts, handle FROM calls WHERE kind = 'call'").fetchall()
    first = {}
    for token, ts, h in rows:
        key = (h, token)
        if key not in first or ts < first[key]:
            first[key] = ts
    toks = {}
    for (h, token), ts in first.items():
        toks.setdefault(h, {})[token] = ts
    token_ts = {}
    for (h, token), ts in first.items():
        token_ts.setdefault(token, []).append(ts)
    out = []
    for a, b, together, _ in kscore.pairs(con, 2, 2000):
        ta, tb = toks.get(a, {}), toks.get(b, {})
        if not ta or not tb:
            continue
        lo, hi = max(min(ta.values()), min(tb.values())), min(max(ta.values()), max(tb.values()))
        if hi < lo:  # never active at the same time: use the whole span of both
            lo, hi = min(min(ta.values()), min(tb.values())), max(max(ta.values()), max(tb.values()))
        lo, hi = lo - cfg["group_secs"], hi + cfg["group_secs"]
        universe = sum(1 for ts_list in token_ts.values() if any(lo <= t <= hi for t in ts_list))
        na = sum(1 for t in ta.values() if lo <= t <= hi)
        nb = sum(1 for t in tb.values() if lo <= t <= hi)
        if not universe or not na or not nb:
            continue
        exp = na * nb / universe
        p = hyper_sf(together, universe, na, nb)
        lift = together / exp if exp else None
        ok = int(together >= v["pair_min_tokens"] and (lift or 0) >= v["pair_min_lift"] and p <= v["pair_max_p"])
        out.append((a, b, together, round(exp, 3), None if lift is None else round(lift, 1), p, ok))
    con.execute("DELETE FROM pair_tests")
    con.executemany("INSERT INTO pair_tests VALUES (?,?,?,?,?,?,?)", out)
    return out


# ---------------------------------------------------------------- who copies whom

def copies(con, cfg, now=None):
    """Big accounts that call tokens AFTER a small account already did, on several tokens: the big one (or his
    team) probably reads the small one. Big = at least copy.ratio x the small one's followers and copy.min_big
    followers. Only the first call of each account per token; the big one within copy.max_h hours after the small.
    Returns [(small, big, n_tokens, median lag in minutes, n_reverse, [tokens])], most tokens first; n_reverse =
    tokens where the big one called first (if that is about as often, it is not copying, just the same circle)."""
    c = dict({"ratio": 5, "min_big": 20000, "max_h": 48, "min_tokens": 2, "limit": 50}, **(cfg.get("copy") or {}))
    foll = {h: f or 0 for h, f in con.execute("SELECT handle, followers FROM kols WHERE COALESCE(bot, 0) = 0 "
                                              "AND handle NOT LIKE 'tg:%' AND handle NOT LIKE 'w:%'")}
    first = {}
    for token, ts, h in con.execute("SELECT token, ts, handle FROM calls WHERE kind = 'call'"):
        if h in foll and ((token, h) not in first or ts < first[(token, h)]):
            first[(token, h)] = ts
    by_token = {}
    for (token, h), ts in first.items():
        by_token.setdefault(token, []).append((ts, h))
    pairs, reverse = {}, {}
    win = c["max_h"] * 3600
    for token, xs in by_token.items():
        xs.sort()
        for i, (ta, a) in enumerate(xs):
            for tb, b in xs[i + 1:]:
                if tb - ta > win:
                    break
                fa, fb = foll.get(a, 0), foll.get(b, 0)
                if fb >= c["min_big"] and fb >= c["ratio"] * max(fa, 1):  # small a first, big b after
                    pairs.setdefault((a, b), []).append((token, (tb - ta) / 60))
                elif fa >= c["min_big"] and fa >= c["ratio"] * max(fb, 1):  # big first, small after
                    reverse[(b, a)] = reverse.get((b, a), 0) + 1
    out = [(a, b, len(v), statistics.median(m for _, m in v), reverse.get((a, b), 0), [t for t, _ in v])
           for (a, b), v in pairs.items() if len(v) >= c["min_tokens"]]
    out.sort(key=lambda r: (-r[2], r[3]))
    return out[:c["limit"]]


# ---------------------------------------------------------------- glue

def ranges(con, cfg):
    """Adds score_lo / score_hi to every scored KOL's stats JSON."""
    v = vcfg(cfg)
    by = {}
    for c in kscore._rows(con, "SELECT handle, token, kind, first_by_kol, max24, r1h, vol_lift, rug, pre2h, "
                               "first_overall, views, likes, retweets, followers FROM calls"):
        by.setdefault(c["handle"], []).append(c)
    n = 0
    for h, st in con.execute("SELECT handle, stats FROM kols WHERE stats IS NOT NULL").fetchall():
        s = json.loads(st or "{}")
        r = score_range(by.get(h, []), cfg, v["boot"], seed=zlib.crc32(h.encode()))
        if r:
            s["score_lo"], s["score_hi"] = r
            con.execute("UPDATE kols SET stats = ? WHERE handle = ?", (json.dumps(s), h))
            n += 1
    return n


def load(con):
    try:
        row = con.execute("SELECT value FROM kv WHERE key = 'validate'").fetchone()
    except Exception:
        return None
    return json.loads(row[0]) if row else None


def gate_closed(con, cfg):
    """True when the score failed the walk-forward test: 'good KOL' should not count in signals."""
    if not vcfg(cfg)["gate"]:
        return False
    v = load(con)
    return bool(v and v.get("state") == "pada")


def run(con, cfg, now=None):
    ranges(con, cfg)
    res = walk_forward(con, cfg, now)
    con.execute("INSERT OR REPLACE INTO kv VALUES ('validate', ?)", (json.dumps(res),))
    pt = pair_tests(con, cfg)
    return res["state"], sum(1 for p in pt if p[6])
