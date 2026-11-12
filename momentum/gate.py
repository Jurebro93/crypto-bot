"""The live gate of momentum_scalp: real money only after >= MIN_TRADES closed paper trades on the demo account whose
results pass the owner's live proof (trade/edge.live_proof, 11.11. rule D): the mean result per trade, net of cost
(the demo books league/store.FEE a side; trade/cost.demo_adjust moves it to the calibrated fee), >= +3 % AND the
lower bound of its 90 % interval > 0. trade/settings.live_refusal asks it through LIVE_GATES when the owner moves the
flag to live; momentum/trade.py asks it again before every action on the real account and run_trade.py before
mirroring a momentum trade, so a hand edit of the flag or a proof that turned negative never trades real money.
Nothing here sets a flag. Read-only on league.db.

No hit-rate rule (11.11.: the old ">= 45 % with +15 % before -10 %" is gone; a win rate says nothing the EV and its
interval do not). MIN_TRADES stays the strategy's own 50, stricter than the rule's n >= 10 (trade/edge.N_MIN).
"""
import os
import sqlite3
import time

MIN_TRADES = 50             # >= trade/edge.N_MIN (10): the strategy's own, stricter minimum
_CACHE = {"at": 0.0, "path": None, "val": None}
CACHE_S = 60


def _db():
    try:
        from league import store
        return store.DB
    except Exception:  # noqa: BLE001
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "league.db")


def proof(path=None, with_rets=False):
    """{"n", "hits", "hit_rate", "pnl_usd", "ev_pct", "ci90_lo_pct"} (+ "rets" with_rets) of the demo account's closed
    momentum trades (zeros when none); ev_pct / ci90_lo_pct are net of the calibrated cost (trade/cost.demo_adjust)."""
    from trade import cost, edge, settings as ts
    path = path or _db()
    out = {"n": 0, "hits": 0, "hit_rate": None, "pnl_usd": 0.0, "ev_pct": None, "ci90_lo_pct": None,
           **({"rets": []} if with_rets else {})}
    if not os.path.exists(path):
        return out
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        try:
            rows = con.execute("SELECT hit, pnl_usd, ret FROM momentum_trades WHERE user=? AND status='closed'",
                               (ts.PAPER_USER,)).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return out
    adj = cost.demo_adjust()
    rets = [r + adj for _h, _p, r in rows if r is not None]
    s = edge.ev_stats(rets)
    n, h = len(rows), sum(int(x or 0) for x, _p, _r in rows)
    return {"n": n, "hits": h, "hit_rate": round(h / n, 3) if n else None,
            "pnl_usd": round(float(sum(p or 0 for _h, p, _r in rows)), 2),
            "ev_pct": round(s["ev"] * 100, 3) if s["ev"] is not None else None,
            "ci90_lo_pct": round(s["lo90"] * 100, 3) if s["lo90"] is not None else None,
            **({"rets": rets} if with_rets else {})}


def refusal(path=None, now=None, cached=False):
    """None when momentum_scalp may trade real money, else the reason in Croatian."""
    from trade import edge
    now = now or time.time()
    if cached and _CACHE["path"] == path and now - _CACHE["at"] < CACHE_S:
        return _CACHE["val"]
    p = proof(path, with_rets=True)
    why = None
    if p["n"] < MIN_TRADES:
        why = f"momentum_scalp: tek {p['n']} zatvorenih paper tradeova, treba {MIN_TRADES}"
    else:
        ok, w, _s = edge.live_proof(p["rets"])
        if not ok:
            why = f"momentum_scalp: dokaz paper tradeova nije prošao: {w}"
    _CACHE.update(at=now, path=path, val=why)
    return why


def live_refusal(con=None, now=None):
    """trade/settings.LIVE_GATES' shape: (con, now=) -> None or the reason."""
    return refusal(now=now)
