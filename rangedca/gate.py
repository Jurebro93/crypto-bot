"""The live gate of range_dca (spec 7): real money only after >= MIN_ROUNDS closed paper rounds on the demo account
with EV > 0 (the mean result per round after fees, in % of the round's cost). trade/settings.live_refusal asks it
when the owner moves the flag to live; rangedca/trade.py asks it again before every action on the real account, so
a hand edit of the flag or a proof that turned negative never trades real money. Nothing here sets a flag.
Read-only on league.db; light (no league imports)."""
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


def proof(path=None):
    """{"n", "wins", "pnl_usd", "ev_pct"} of the demo account's closed range rounds (zeros when none)."""
    from trade import settings as ts
    path = path or _db()
    out = {"n": 0, "wins": 0, "pnl_usd": 0.0, "ev_pct": None}
    if not os.path.exists(path):
        return out
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        try:
            n, w, pnl, ev = con.execute(
                "SELECT COUNT(*), COALESCE(SUM(pnl_usd > 0), 0), COALESCE(SUM(pnl_usd), 0), AVG(ret) FROM range_rounds "
                "WHERE user=? AND status='closed'", (ts.PAPER_USER,)).fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return out
    return {"n": int(n), "wins": int(w), "pnl_usd": round(float(pnl), 2), "ev_pct": round(ev * 100, 3) if ev is not None else None}


def refusal(path=None, now=None, cached=False):
    """None when range_dca may trade real money, else the reason in Croatian."""
    now = now or time.time()
    if cached and _CACHE["path"] == path and now - _CACHE["at"] < CACHE_S:
        return _CACHE["val"]
    p = proof(path)
    why = None
    if p["n"] < MIN_ROUNDS:
        why = f"range_dca: tek {p['n']} zatvorenih paper rundi, treba {MIN_ROUNDS}"
    elif p["ev_pct"] is None or p["ev_pct"] <= 0:
        why = f"range_dca: EV paper rundi {p['ev_pct'] or 0:+.2f} % po rundi, mora biti iznad nule"
    _CACHE.update(at=now, path=path, val=why)
    return why
