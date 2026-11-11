"""The live gate of momentum_scalp: real money only after >= MIN_TRADES closed paper trades on the demo account with
EV > 0 (the mean result per trade after fees, in % of its stake) AND a hit rate >= MIN_HIT (the share of trades
whose +15 % take profit came before the -10 % stop). trade/settings.live_refusal asks it through LIVE_GATES when the
owner moves the flag to live; momentum/trade.py asks it again before every action on the real account and
run_trade.py before mirroring a momentum trade, so a hand edit of the flag or a proof that turned negative never
trades real money. Nothing here sets a flag. Read-only on league.db.

Why 45 % and not 50 %: with TP +15 / SL -10 and ~2-3 % round trip the break-even hit rate of a FULL exit at TP is
~50 % (momentum/rules.break_even_p); the strategy sells only half at +15 % and trails the rest, so its hit rate and
its EV are measured apart and BOTH must pass: EV > 0 is the real test, 45 % a floor against a few lucky runners.
"""
import os
import sqlite3
import time

MIN_TRADES = 50
MIN_HIT = 0.45
_CACHE = {"at": 0.0, "path": None, "val": None}
CACHE_S = 60


def _db():
    try:
        from league import store
        return store.DB
    except Exception:  # noqa: BLE001
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "league.db")


def proof(path=None):
    """{"n", "hits", "hit_rate", "pnl_usd", "ev_pct"} of the demo account's closed momentum trades (zeros when none)."""
    from trade import settings as ts
    path = path or _db()
    out = {"n": 0, "hits": 0, "hit_rate": None, "pnl_usd": 0.0, "ev_pct": None}
    if not os.path.exists(path):
        return out
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        try:
            n, h, pnl, ev = con.execute(
                "SELECT COUNT(*), COALESCE(SUM(hit), 0), COALESCE(SUM(pnl_usd), 0), AVG(ret) FROM momentum_trades "
                "WHERE user=? AND status='closed'", (ts.PAPER_USER,)).fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return out
    n = int(n)
    return {"n": n, "hits": int(h), "hit_rate": round(h / n, 3) if n else None, "pnl_usd": round(float(pnl), 2),
            "ev_pct": round(ev * 100, 3) if ev is not None else None}


def refusal(path=None, now=None, cached=False):
    """None when momentum_scalp may trade real money, else the reason in Croatian."""
    now = now or time.time()
    if cached and _CACHE["path"] == path and now - _CACHE["at"] < CACHE_S:
        return _CACHE["val"]
    p = proof(path)
    why = None
    if p["n"] < MIN_TRADES:
        why = f"momentum_scalp: tek {p['n']} zatvorenih paper tradeova, treba {MIN_TRADES}"
    elif p["ev_pct"] is None or p["ev_pct"] <= 0:
        why = f"momentum_scalp: EV paper tradeova {p['ev_pct'] or 0:+.2f} % po tradeu, mora biti iznad nule"
    elif (p["hit_rate"] or 0) < MIN_HIT:
        why = f"momentum_scalp: pogodak {p['hit_rate'] or 0:.0%} (+15 % prije -10 %), treba {MIN_HIT:.0%}"
    _CACHE.update(at=now, path=path, val=why)
    return why


def live_refusal(con=None, now=None):
    """trade/settings.LIVE_GATES' shape: (con, now=) -> None or the reason."""
    return refusal(now=now)
