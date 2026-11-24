"""What happened after a proposal (every status: novo, kupljeno, isteklo, odbijeno), 1 h and 4 h after it was made,
measured from its price at that moment (price0): max gain, max drawdown, which of its own TP / SL came first, and the
result of a trade on its exit (TP -> +TP, SL -> -SL, neither -> the close) after its cost. For isteklo and odbijeno
this is the missed (or avoided) opportunity; for every strategy together it is the hit rate of the proposals.

The path: the minute data we already keep, merged per minute by events/predictions.series (events.db price ticks,
minute.db call candles, range.db snapshots and seed candles, hype.db token_pulse), plus momentum.db snapshots and
proposals.db px (the pass's own market reads and its capped DexScreener batch). No paid call. A horizon with no
point at all is "nema podataka" (UNAVAILABLE_S after it ended); TP and SL in the same minute count as SL.

12.11. (Jure, točka 4): a horizon measured on fewer than rangedca/missed.MIN_POINTS (3) minutes is marked "reliable":
false, "quality": "nepouzdano": for an expired or rejected proposal (the missed opportunity) it is no missed rise
(rangedca/missed), and the list shows the word instead of its numbers (proposals/view). Every stored horizon carries
n_points, so the ones measured before 12.11. are read alike.
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
    from rangedca import missed
    out = {"status": "ok", "max_gain_pct": round((hi / px0 - 1) * 100, 2), "max_dd_pct": round((lo / px0 - 1) * 100, 2),
           "first": first, "ret_pct": round((ret - cost) * 100, 2), "n_points": len(seg),
           "coverage": round(min(1.0, len(seg) / (secs / 60)), 3), "reliable": len(seg) >= missed.MIN_POINTS}
    if not out["reliable"]:   # 12.11. (Jure, točka 4)
        out["quality"] = missed.UNRELIABLE
    return out


def exit_sim(cs, entry_px, t0, plan, supply=None, t_end=None):
    """A paper lot bought at entry_px in minute t0 on the proposal's exit plan (league/exitplan format: take_profits
    at_mc_usd / at_pct with sell_share, stop, trailing {activate_pct, trail_pct}, time_stop {after_min,
    if_pnl_below_pct}) over the minute path cs after t0 (up to t_end): (first, gross return fraction, exit minute).
    first: "tp" (a take profit or the trailing came first), "sl" (the stop came first), "time" (the time stop sold
    everything first), "open" (nothing by the end of the data: the rest marked at the last close). The stop is checked
    before the take profits in the same minute (cautious); MC levels need the supply (MC / price)."""
    def px(lv):
        if not lv:
            return None
        if lv.get("at_mc_usd") and supply:
            return float(lv["at_mc_usd"]) / supply
        if lv.get("at_pct") is not None:
            return entry_px * (1 + float(lv["at_pct"]) / 100)
        return None
    tps = sorted([(px(t), float(t.get("sell_share") or 1.0)) for t in plan.get("take_profits") or [] if px(t)])
    sl = px(plan.get("stop"))
    tr = plan.get("trailing") or {}
    act = entry_px * (1 + float(tr.get("activate_pct") or 0) / 100) if tr.get("trail_pct") else None
    trail = float(tr.get("trail_pct") or 0) / 100
    ts_ = plan.get("time_stop") or {}
    left, got, first, peak, hit, last_c, last_m = 1.0, 0.0, None, entry_px, set(), entry_px, t0
    for m, _o, h, lo, c in cs:
        if m <= t0:
            continue
        if t_end is not None and m > t_end:
            break
        last_c, last_m = c, m
        if sl and lo <= sl:
            return first or "sl", got + left * sl / entry_px - 1, m
        if act and peak >= act and lo <= peak * (1 - trail):
            return first or "tp", got + left * peak * (1 - trail) / entry_px - 1, m
        for i, (tp_px, share) in enumerate(tps):
            if i not in hit and h >= tp_px and left > 1e-9:
                q = min(left, share)
                got, left = got + q * tp_px / entry_px, left - q
                hit.add(i)
                first = first or "tp"
        if left <= 1e-9:
            return first or "tp", got - 1, m
        peak = max(peak, h)
        if ts_.get("after_min") and m - t0 >= float(ts_["after_min"]) * 60 \
                and (c / entry_px - 1) * 100 < float(ts_.get("if_pnl_below_pct") or 0):
            return first or "time", got + left * c / entry_px - 1, m
    return first or "open", got + left * last_c / entry_px - 1, last_m


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
