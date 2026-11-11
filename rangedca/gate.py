"""The live gate of range_dca (spec 7): real money only after >= MIN_ROUNDS closed paper rounds on the demo account
whose results pass the owner's live proof (trade/edge.live_proof, 11.11. rule D: the mean result per round net of
cost, the demo's booking moved to the calibrated fee by trade/cost.demo_adjust, >= +3 % AND the lower bound of its
90 % interval > 0; MIN_ROUNDS 20 is stricter than the rule's n >= 10). trade/settings.live_refusal asks it
when the owner moves the flag to live; rangedca/trade.py asks it again before every action on the real account, so
a hand edit of the flag or a proof that turned negative never trades real money. Nothing here sets a flag.
Read-only on league.db; light (trade/cost and trade/edge only)."""
import json
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


def round_source(levels):
    """The watchlist source a round was opened from (range_rounds.levels "src", 11.11.); "signal" before that."""
    try:
        return (json.loads(levels or "{}") or {}).get("src") or "signal"
    except (ValueError, AttributeError):
        return "signal"


def proof(path=None, with_rets=False, source=None):
    """{"n", "wins", "pnl_usd", "ev_pct", "ci90_lo_pct"} (+ "rets" with_rets) of the demo account's closed range
    rounds (zeros when none); ev_pct / ci90_lo_pct net of the calibrated cost (trade/cost.demo_adjust). source
    (11.11.): "missed" = only the rounds opened from source missed, "other" = all the others; None = every round."""
    from trade import cost, edge, settings as ts
    path = path or _db()
    out = {"n": 0, "wins": 0, "pnl_usd": 0.0, "ev_pct": None, "ci90_lo_pct": None, **({"rets": []} if with_rets else {})}
    if not os.path.exists(path):
        return out
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        try:
            rows = con.execute("SELECT pnl_usd, ret, levels FROM range_rounds WHERE user=? AND status='closed'",
                               (ts.PAPER_USER,)).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return out
    if source:
        rows = [r for r in rows if (round_source(r[2]) == "missed") == (source == "missed")]
    rows = [(p, r) for p, r, *_ in rows]
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


# ---------- range_missed (11.11., flag range_missed G27, rangedca/missed.py) ----------------------------------------
# The missed tokens (skipped, then >= +20 % within 60 min) reach the real account only past their OWN proof: >=
# MIN_ROUNDS (20) closed demo rounds opened from source missed (range_rounds.levels "src") passing trade/edge.live_proof
# (EV >= +3 % net of the calibrated cost and the lower bound of its 90 % interval > 0), the same live gate as range_dca.
_MCACHE = {"at": 0.0, "path": None, "val": None}


def missed_refusal(path=None, now=None, cached=False):
    """None when a missed-sourced token may be bought with real money (range_missed live), else the reason."""
    now = now or time.time()
    if cached and _MCACHE["path"] == path and now - _MCACHE["at"] < CACHE_S:
        return _MCACHE["val"]
    from trade import edge
    p = proof(path, with_rets=True, source="missed")
    why = None
    if p["n"] < MIN_ROUNDS:
        why = f"range_missed: tek {p['n']} zatvorenih paper rundi izvora missed, treba {MIN_ROUNDS}"
    else:
        ok, w, _s = edge.live_proof(p["rets"])
        if not ok:
            why = f"range_missed: dokaz paper rundi izvora missed nije prošao: {w}"
    _MCACHE.update(at=now, path=path, val=why)
    return why


def missed_live_refusal(con=None, now=None):
    """trade/settings.LIVE_GATES' shape: (con, now=) -> None or the reason."""
    return missed_refusal(now=now)


def by_source(path=None):
    """{"missed": proof, "other": proof} of the demo account's closed range rounds (the EV report, get_range_candidates)."""
    return {"missed": proof(path, source="missed"), "other": proof(path, source="other")}


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
