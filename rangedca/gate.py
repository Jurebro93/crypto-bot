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


# ---------- range_flip (11.11., flag range_flip G26) ----------------------------------------------------------------
# Live only past the backtest of today's rules vs the new ones (flip / pause / volatility stop) over the real range
# tokens, run every night by rangedca/backtest.run_server and kept in range.db kv flip_backtest: the new rules' max
# drawdown must not be larger than today's (Jure 11.11.: "ide live samo ako ne pogoršava DD"), with at least
# FLIP_MIN_ROUNDS rounds of today's rules on FLIP_MIN_TOKENS tokens (with fewer the comparison proves nothing) and a
# result not older than FLIP_MAX_AGE_S. The reason always names PnL and false entries of both.
FLIP_MIN_ROUNDS = 10
FLIP_MIN_TOKENS = 3
FLIP_MAX_AGE_S = 3 * 86400
_FCACHE = {"at": 0.0, "path": None, "val": None}


def flip_result(path=None):
    """range.db kv flip_backtest (rangedca/backtest.flip_summary of the last night), None when there is none."""
    from . import data
    con = data.ro(path)
    if con is None:
        return None
    try:
        return data.kv_get(con, "flip_backtest")
    except sqlite3.Error:
        return None
    finally:
        con.close()


def _side(s):
    return (f"PnL {s.get('pnl_sol', 0):+.3f} SOL ({s.get('pnl_pct') or 0:+.1f} %), DD {s.get('max_dd_sol', 0):.3f} SOL, "
            f"lažnih ulaza {s.get('false_entries', 0)}, rundi {s.get('rounds', 0)}")


def flip_refusal(path=None, now=None, cached=False):
    """None when range_flip may decide for the real account, else the reason in Croatian (see above)."""
    now = now or time.time()
    if cached and _FCACHE["path"] == path and now - _FCACHE["at"] < CACHE_S:
        return _FCACHE["val"]
    r = flip_result(path)
    why = None
    if not isinstance(r, dict) or not r.get("old") or not r.get("new"):
        why = "range_flip: nema noćnog backtesta staro vs novo (rangedca/backtest, range.db kv flip_backtest)"
    else:
        old, new = r["old"], r["new"]
        tail = f"; staro: {_side(old)}; novo: {_side(new)}"
        if now - (r.get("ts") or 0) > FLIP_MAX_AGE_S:
            why = f"range_flip: backtest je star {(now - (r.get('ts') or 0)) / 86400:.1f} dana (najviše 3)" + tail
        elif (old.get("rounds") or 0) < FLIP_MIN_ROUNDS or (r.get("tokens") or 0) < FLIP_MIN_TOKENS:
            why = (f"range_flip: premalo podataka ({old.get('rounds') or 0} rundi starih pravila na {r.get('tokens') or 0} "
                   f"tokena, treba {FLIP_MIN_ROUNDS} na {FLIP_MIN_TOKENS})" + tail)
        elif (new.get("max_dd_sol") or 0) > (old.get("max_dd_sol") or 0) + 1e-9:
            why = "range_flip: novi DD veći od starog" + tail
    _FCACHE.update(at=now, path=path, val=why)
    return why


def flip_live_refusal(con=None, now=None):
    """trade/settings.LIVE_GATES' shape: (con, now=) -> None or the reason."""
    return flip_refusal(now=now)
