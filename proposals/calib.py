"""The probability behind every proposal (p_tp = the take profit comes BEFORE the stop) and Grok's calibration.

A strategy's p_tp from its measured record (hits of n), never the raw hit rate:

    p_tp = (hits + K_PRIOR * p0) / (n + K_PRIOR)            p0 = (SL + cost) / (TP + SL)

p0 is the break-even probability of THIS proposal (its TP, SL and liquidity cost): the prior says "no edge", so a
strategy with no record has EV exactly 0 (never shown) and a strategy with 5 lucky hits of 5 moves only 5/25 of the
way from no edge to its hit rate: a tiny n cannot produce a big EV. K_PRIOR = 20 pseudo-trades (the same weight
ui/kandidati.SHRINK_N gives a source's EV). Shown next to it: n and the Wilson 90 % interval of the raw hit rate.

Grok's p_tp is CALIBRATED before it is used (11.11., Jure: Grok said 20 % where 56 % happened): from what Grok's
measured predictions did, never from a fixed factor. The pairs (Grok's p, did TP come first): momentum.db calib
(execute_trade p_tp, momentum/evgate: hit = TP before SL within the horizon) and events.db grok_predictions
(submit_grok_prediction p_tp, tp_first). Per bucket of p (0-0.2 ... 0.8-1): mean p m_b, hit rate r_b, n_b;

    calibrated_b = m_b + w_b * (r_b - m_b)        w_b = n_b / (n_b + K_CAL)

so a bucket with few samples stays at Grok's own number (identity) and a well-measured one moves to what happened;
then the buckets are made monotone (pool adjacent violators, weighted by n_b) and a p between bucket means gets the
linearly interpolated correction (the nearest bucket's outside them).
"""
import json
import math
import sqlite3
import time

Z90 = 1.6449
K_PRIOR = 20
K_CAL = 20
BUCKETS = ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0))
CAL_DAYS = 60
P_MIN, P_MAX = 0.01, 0.99


def wilson(k, n, z=Z90):
    """(low, high) of the Wilson score interval of k hits in n (90 % by default); (0, 1) without data."""
    if not n:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def break_even(tp, sl, cost):
    """The p at which p x TP - (1 - p) x SL - cost = 0 (fractions)."""
    return (sl + cost) / (tp + sl) if tp + sl > 0 else 1.0


def ev(p, tp, sl, cost):
    """EV per trade (fraction of the stake): p x TP - (1 - p) x SL - cost. A trade that hits neither level is
    counted as a stop: the cautious reading of a hit rate."""
    return p * tp - (1 - p) * sl - cost


def estimate(hits, n, tp, sl, cost, k=K_PRIOR):
    """{"p", "p_raw", "hits", "n", "ci90", "prior", "k"} of a record of hits in n, shrunk toward no edge."""
    hits, n = max(0, int(hits or 0)), max(0, int(n or 0))
    hits = min(hits, n)
    p0 = min(P_MAX, max(P_MIN, break_even(tp, sl, cost)))
    p = (hits + k * p0) / (n + k)
    lo, hi = wilson(hits, n)
    return {"p": round(p, 4), "p_raw": round(hits / n, 4) if n else None, "hits": hits, "n": n,
            "ci90": [round(lo, 3), round(hi, 3)], "prior": round(p0, 4), "k": k}


# ---------- Grok's calibration -----------------------------------------------------------------------------------------

def _pav(vals, weights):
    """Pool adjacent violators: the closest non-decreasing sequence (weighted least squares)."""
    blocks = [[v, w, 1] for v, w in zip(vals, weights)]
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][0] > blocks[i + 1][0] + 1e-12:
            a, b = blocks[i], blocks[i + 1]
            w = a[1] + b[1]
            blocks[i] = [(a[0] * a[1] + b[0] * b[1]) / w if w else (a[0] + b[0]) / 2, w, a[2] + b[2]]
            del blocks[i + 1]
            i = max(0, i - 1)
        else:
            i += 1
    out = []
    for v, _w, c in blocks:
        out += [v] * c
    return out


def fit(pairs, k=K_CAL):
    """pairs [(p, hit 0/1)] -> {"n", "buckets": [{"from", "to", "n", "mean_p", "hit_rate", "weight", "calibrated"}]}."""
    rows = [(float(p), int(bool(y))) for p, y in pairs if p is not None and y is not None and 0 <= float(p) <= 1]
    bks = []
    for lo, hi in BUCKETS:
        xs = [(p, y) for p, y in rows if lo <= p < hi or (hi == 1.0 and p == 1.0)]
        if not xs:
            continue
        n = len(xs)
        m = sum(p for p, _ in xs) / n
        r = sum(y for _, y in xs) / n
        w = n / (n + k)
        bks.append({"from": lo, "to": hi, "n": n, "mean_p": round(m, 4), "hit_rate": round(r, 4),
                    "weight": round(w, 4), "calibrated": m + w * (r - m)})
    if bks:
        mono = _pav([b["calibrated"] for b in bks], [b["n"] for b in bks])
        for b, v in zip(bks, mono):
            b["calibrated"] = round(min(P_MAX, max(P_MIN, v)), 4)
    return {"n": len(rows), "buckets": bks, "k": k}


def apply(model, p):
    """Grok's p -> the calibrated p (identity without a model or a bucket)."""
    if p is None:
        return None
    p = float(p)
    bks = (model or {}).get("buckets") or []
    if not bks:
        return round(p, 4)
    pts = sorted((b["mean_p"], b["calibrated"] - b["mean_p"]) for b in bks)
    if p <= pts[0][0]:
        d = pts[0][1]
    elif p >= pts[-1][0]:
        d = pts[-1][1]
    else:
        d = pts[0][1]
        for (x0, d0), (x1, d1) in zip(pts, pts[1:]):
            if x0 <= p <= x1:
                d = d0 + (d1 - d0) * ((p - x0) / (x1 - x0) if x1 > x0 else 0.0)
                break
    return round(min(P_MAX, max(P_MIN, p + d)), 4)


def bucket_n(model, p):
    """How many measured predictions stand behind the calibration at p (the nearest bucket's n)."""
    bks = (model or {}).get("buckets") or []
    if not bks or p is None:
        return 0
    return min(bks, key=lambda b: abs(b["mean_p"] - float(p)))["n"]


def pairs(now=None, days=CAL_DAYS, momentum_path=None, events_path=None):
    """[(p, hit)] of Grok's resolved predictions: momentum.db calib (execute_trade p_tp) and events.db
    grok_predictions (submit_grok_prediction p_tp, tp_first). Read-only; a missing database adds nothing."""
    now = int(now or time.time())
    since = now - days * 86400
    out = []
    try:
        from momentum import data as mdata
        con = mdata.ro(momentum_path)
        if con is not None:
            try:
                out += [(p, h) for p, h in con.execute("SELECT p_tp, hit FROM calib WHERE ts >= ? AND status='done' AND "
                                                       "hit IS NOT NULL AND p_tp IS NOT NULL", (since,))]
            except sqlite3.Error:
                pass
            finally:
                con.close()
    except Exception:  # noqa: BLE001
        pass
    try:
        from events import store as estore
        con = estore.ro(events_path)
        if con is not None:
            try:
                out += [(p, y) for p, y in con.execute("SELECT p_tp, tp_first FROM grok_predictions WHERE ts >= ? AND "
                                                       "tp_first IS NOT NULL AND p_tp IS NOT NULL", (since,))]
            except sqlite3.Error:
                pass
            finally:
                con.close()
    except Exception:  # noqa: BLE001
        pass
    return out


def summary(model):
    """The calibration as get_proposals shows it."""
    bks = (model or {}).get("buckets") or []
    return {"n": (model or {}).get("n") or 0, "k": (model or {}).get("k", K_CAL),
            "buckets": [{k: b[k] for k in ("from", "to", "n", "mean_p", "hit_rate", "calibrated")} for b in bks],
            "rule": ("calibrated = mean p + n / (n + 20) x (hit rate - mean p) per bucket of Grok's p, made monotone; "
                     "few samples = Grok's own p (identity)")}


def dumps(model):
    return json.dumps(model)
