"""What happened after a proposal (every status: novo, kupljeno, isteklo, odbijeno), 1 h and 4 h after it was made,
measured from its price at that moment (price0): max gain, max drawdown, which of its own TP / SL came first, and the
result of a trade on its exit (TP -> +TP, SL -> -SL, neither -> the close) after its cost. For isteklo and odbijeno
this is the missed (or avoided) opportunity; for every strategy together it is the hit rate of the proposals.

The path: the minute data we already keep, merged per minute by events/predictions.series (events.db price ticks,
minute.db call candles, range.db snapshots and seed candles, hype.db token_pulse), plus momentum.db snapshots and
proposals.db px (the pass's own market reads and its capped DexScreener batch). No paid call. A horizon with no
point at all is "nema podataka" (UNAVAILABLE_S after it ended); TP and SL in the same minute count as SL.
"""
import json
import sqlite3
import time

HORIZONS = (("1h", 3600), ("4h", 4 * 3600))
GRACE_S = 600
UNAVAILABLE_S = 6 * 3600
ENTRY_S = 300


def _extra(token, t0, t1, pcon, mom_path=None):
    """[(ts, o, h, l, c)] from proposals.db px and momentum.db snaps."""
    out = []
    if pcon is not None:
        try:
            out += [(ts, p, p, p, p) for ts, p in pcon.execute("SELECT ts, price FROM px WHERE token=? AND ts>=? AND ts<=? "
                                                                "AND price > 0", (token, int(t0), int(t1)))]
        except sqlite3.Error:
            pass
    try:
        from momentum import data as mdata
        mc = mdata.ro(mom_path)
    except Exception:  # noqa: BLE001
        mc = None
    if mc is not None:
        try:
            out += [(ts, p, p, p, p) for ts, p in mc.execute("SELECT ts, price FROM snaps WHERE token=? AND ts>=? AND "
                                                             "ts<=? AND price > 0", (token, int(t0), int(t1)))]
        except sqlite3.Error:
            pass
        finally:
            mc.close()
    return out


def path(token, t0, t1, econ=None, pcon=None, mom_path=None):
    """[(minute, o, h, l, c)] of the token in [t0, t1], oldest first."""
    from events import predictions
    own = econ is None
    if econ is None:
        try:
            from events import store as estore
            econ = estore.ro()
        except Exception:  # noqa: BLE001
            econ = None
    if econ is None:
        econ, own = sqlite3.connect(":memory:"), True
    try:
        return predictions.series(token, t0, t1, econ, extra=_extra(token, t0, t1, pcon, mom_path))
    finally:
        if own:
            econ.close()


def score(cs, px0, t0, secs, tp, sl, cost):
    """One horizon (tp, sl, cost: fractions) -> {"status", "max_gain_pct", "max_dd_pct", "first", "ret_pct",
    "n_points"}."""
    from events import predictions
    seg = [c for c in cs if t0 <= c[0] + 59 and c[0] <= t0 + secs]
    if not seg or not px0:
        return {"status": "nema podataka", "n_points": len(seg)}
    hi, lo = max(c[2] for c in seg), min(c[3] for c in seg)
    first = predictions.first_touch(seg, px0, tp * 100, sl * 100)
    ret = tp if first == "tp" else -sl if first == "sl" else seg[-1][4] / px0 - 1
    return {"status": "ok", "max_gain_pct": round((hi / px0 - 1) * 100, 2), "max_dd_pct": round((lo / px0 - 1) * 100, 2),
            "first": first, "ret_pct": round((ret - cost) * 100, 2), "n_points": len(seg),
            "coverage": round(min(1.0, len(seg) / (secs / 60)), 3)}


def measure_one(p, now, econ=None, pcon=None, mom_path=None):
    """(after dict, done) of one proposal; None when nothing new is due."""
    t0 = int(p["created_ts"])
    after = dict(p.get("after") or {})
    due = [(k, s) for k, s in HORIZONS if k not in after and now >= t0 + s + GRACE_S]
    if not due:
        return None
    r = p.get("row") or {}
    tp, sl = (p.get("tp_pct") or 0) / 100, (p.get("sl_pct") or 0) / 100
    cost = (r.get("cost_pct") or 0) / 100
    cs = path(p["token"], t0 - ENTRY_S, t0 + HORIZONS[-1][1], econ, pcon, mom_path)
    px0 = p.get("price0")
    if not px0:
        before = [c for c in cs if t0 - ENTRY_S <= c[0] <= t0]
        px0 = before[-1][4] if before else None
    changed = False
    for k, s in due:
        sc = score(cs, px0, t0, s, tp, sl, cost)
        if sc["status"] == "ok" or now >= t0 + s + UNAVAILABLE_S:
            after[k] = sc
            changed = True
    if not changed:
        return None
    after["entry_px"] = px0
    return after, all(k in after for k, _s in HORIZONS)


def measure_due(con, now, econ=None, log=print, limit=200, mom_path=None):
    """Every proposal whose 1 h or 4 h is due; returns how many got a new horizon."""
    now = int(now or time.time())
    from . import store
    rows = store.read(con, "after_done = 0 AND created_ts <= ?", (now - HORIZONS[0][1] - GRACE_S,), order="id",
                      limit=limit)
    n = 0
    for p in rows:
        try:
            got = measure_one(p, now, econ, con, mom_path)
        except Exception as e:  # noqa: BLE001 - one token's data never stops the others
            log(f"prijedlozi: ishod #{p['id']} nije izmjeren ({type(e).__name__})")
            continue
        if got is None:
            continue
        after, done = got
        con.execute("UPDATE proposals SET after=?, after_done=? WHERE id=?", (json.dumps(after), int(done), p["id"]))
        n += 1
    if n:
        con.commit()
    return n
