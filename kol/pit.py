"""Point-in-time caller statistics (10.11. (Grok MCP audit 5), plan 2.1, flag caller_ev_rank).

The Autopilot ranked influencers on statistics that could contain the future: the 24-hour wick (calls.max24) and
minute stats over every measured call in the window, also calls whose outcome hour was still running. A rank used at
time t0 must be built only from what was known at t0:

  - only calls posted before t0 whose measured hour (kol/minute.HORIZON_MIN) had closed before t0: ts + 3600 < t0;
  - one call per (account, token), the first, as kol/minute.handle_stats and kol/tpsl.rows count them;
  - from minute.db call_path / call_lv (the minute measure), never from calls.max24 (the 24-h high).

Per account: n, the EV after cost of the follow's exit pair (kol/tpsl.grid: TP +tp % / SL -sl %, mean and standard
deviation in % of the stake), its lower bound mean - Z * SE, the share of clean +10 % hits (+10 % before -20 %,
kol/minute.clean_hit) with its Wilson lower bound, the stop share and the rug share (low within the hour <= -80 %).
Adding a call after t0, or a call whose hour is still open at t0, cannot change anything returned for t0.

Reads minute.db only (read-only connection from the caller); no API call.
"""
import math
import sqlite3

from kol import minute, tpsl

HORIZON_S = minute.HORIZON_MIN * 60   # the measured hour: a call's outcome is known only after it
D = 86400
WILSON_Z = 1.64                       # = ui/autopilot.WILSON_Z (one-sided 95 %)
Z = tpsl.Z                            # standard errors under the mean for the EV lower bound (kol/tpsl uses the same)

_COLS = tpsl._COLS   # tweet_id, token, handle, ts, hi60, lo60, r60, t5..t30, sl_min, lv


def wilson_low(share, n, z=WILSON_Z):
    """Lower end of the Wilson interval of a share measured on n calls (the same formula as ui/autopilot)."""
    if not n:
        return 0.0
    p = max(0.0, min(1.0, share))
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5
    return max(0.0, (c - r) / d)


def rows_at(mcon, t0, days=30, handles=None):
    """Measured calls known at t0: posted in [t0 - days, t0 - HORIZON_S), entry and no 'bad' mark, one per (account,
    token) - the first. handles: only these accounts (any case). Oldest first, as dicts kol/tpsl.outcome reads."""
    t0 = int(t0)
    cols = ", ".join(f"c.{c}" for c in _COLS[:-1])
    where = "c.entry IS NOT NULL AND c.bad IS NULL AND c.ts >= ? AND c.ts < ?"
    args = [t0 - int(days * D), t0 - HORIZON_S]
    if handles is not None:
        hs = sorted({h.lower() for h in handles if h})
        if not hs:
            return []
        where += f" AND LOWER(c.handle) IN ({','.join('?' * len(hs))})"
        args += hs
    try:
        got = mcon.execute(f"SELECT {cols}, l.lv FROM call_path c LEFT JOIN call_lv l ON l.tweet_id = c.tweet_id "
                           f"AND l.token = c.token WHERE {where}", args).fetchall()
    except sqlite3.OperationalError as e:
        if "no such table: call_lv" not in str(e):
            raise
        got = mcon.execute(f"SELECT {cols}, NULL FROM call_path c WHERE {where}", args).fetchall()
    first = {}
    for r in got:
        d = dict(zip(_COLS, r))
        k = (d["handle"], d["token"])
        if k not in first or d["ts"] < first[k]["ts"]:
            first[k] = d
    return sorted(first.values(), key=lambda d: d["ts"])


def summarize(rows, tp=15, sl=60, cost=tpsl.COST, z=Z):
    """Stats of one account's rows (see the module text); None for no rows."""
    n = len(rows)
    if not n:
        return None
    g = tpsl.grid(rows, cost, (int(tp),), (int(sl),))[(int(tp), int(sl))]
    se = g["sd"] / math.sqrt(n) if n > 1 else None
    hits10 = sum(1 for r in rows if minute.clean_hit(r, 10))
    stops = sum(1 for r in rows if r.get("sl_min") is not None and not minute.clean_hit(r, 10))
    rugs = sum(1 for r in rows if r.get("lo60") is not None and r["lo60"] <= minute.RUG_LO)
    return {"n": n, "tp": int(tp), "sl": int(sl), "ev": g["ev"], "sd": g["sd"],
            "ev_lo": (g["ev"] - z * se) if se is not None else None,
            "win": g["tp"], "stop": g["sl"], "time": g["time"],
            "hits10": hits10, "hit10": hits10 / n, "wilson10": wilson_low(hits10 / n, n),
            "sl_share": stops / n, "rug": rugs / n, "last_ts": rows[-1]["ts"]}


def stats_at(handle, t0, mcon, days=30, tp=15, sl=60):
    """The statistics of one account as known at t0 (None when it has no measured call that old)."""
    return summarize(rows_at(mcon, t0, days, [handle]), tp, sl)


def all_stats(mcon, t0, days=30, tp=15, sl=60, handles=None):
    """{handle: stats} of every account (or only `handles`) as known at t0, from one read of minute.db."""
    by = {}
    for r in rows_at(mcon, t0, days, handles):
        by.setdefault(r["handle"], []).append(r)
    return {h: summarize(rs, tp, sl) for h, rs in by.items()}
