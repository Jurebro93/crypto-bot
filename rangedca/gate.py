"""The live gate of range_dca (spec 7): real money only after >= MIN_ROUNDS closed paper rounds on the demo account
whose results pass the owner's live proof (trade/edge.live_proof, 11.11. rule D: the mean result per round net of
cost, the demo's booking moved to the calibrated fee by trade/cost.demo_adjust, >= +3 % AND the lower bound of its
90 % interval > 0; MIN_ROUNDS 20 is stricter than the rule's n >= 10). trade/settings.live_refusal asks it
when the owner moves the flag to live; rangedca/trade.py asks it again before every action on the real account, so
a hand edit of the flag or a proof that turned negative never trades real money. Nothing here sets a flag.
Read-only on league.db; light (trade/cost and trade/edge only)."""
import os
import sqlite3
import time

MIN_ROUNDS = 20
_CACHE = {"at": 0.0, "path": None, "val": None}
CACHE_S = 60


def _db():
    try:
        from league import store
        return store.DB
    except Exception:  # noqa: BLE001
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "league.db")


def proof(path=None, with_rets=False):
    """{"n", "wins", "pnl_usd", "ev_pct", "ci90_lo_pct"} (+ "rets" with_rets) of the demo account's closed range
    rounds (zeros when none); ev_pct / ci90_lo_pct net of the calibrated cost (trade/cost.demo_adjust)."""
    from trade import cost, edge, settings as ts
    path = path or _db()
    out = {"n": 0, "wins": 0, "pnl_usd": 0.0, "ev_pct": None, "ci90_lo_pct": None, **({"rets": []} if with_rets else {})}
    if not os.path.exists(path):
        return out
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        try:
            rows = con.execute("SELECT pnl_usd, ret FROM range_rounds WHERE user=? AND status='closed'",
                               (ts.PAPER_USER,)).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return out
    adj = cost.demo_adjust()
    rets = [r + adj for _p, r in rows if r is not None]
    s = edge.ev_stats(rets)
    return {"n": len(rows), "wins": sum(1 for p, _r in rows if (p or 0) > 0),
            "pnl_usd": round(float(sum(p or 0 for p, _r in rows)), 2),
            "ev_pct": round(s["ev"] * 100, 3) if s["ev"] is not None else None,
            "ci90_lo_pct": round(s["lo90"] * 100, 3) if s["lo90"] is not None else None,
            **({"rets": rets} if with_rets else {})}


def refusal(path=None, now=None, cached=False):
    """None when range_dca may trade real money, else the reason in Croatian."""
    now = now or time.time()
    if cached and _CACHE["path"] == path and now - _CACHE["at"] < CACHE_S:
        return _CACHE["val"]
    from trade import edge
    p = proof(path, with_rets=True)
    why = None
    if p["n"] < MIN_ROUNDS:
        why = f"range_dca: tek {p['n']} zatvorenih paper rundi, treba {MIN_ROUNDS}"
    else:
        ok, w, _s = edge.live_proof(p["rets"])
        if not ok:
            why = f"range_dca: dokaz paper rundi nije prošao: {w}"
    _CACHE.update(at=now, path=path, val=why)
    return why
