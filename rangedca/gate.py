"""The live gate of range_dca (spec 7): real money only after >= MIN_ROUNDS closed paper rounds on the demo account
whose results pass the owner's live proof (trade/edge.live_proof, 11.11. rule D: the mean result per round net of
cost, the demo's booking moved to the calibrated fee by trade/cost.demo_adjust, >= +3 % AND the lower bound of its
90 % interval > 0; MIN_ROUNDS 20 is stricter than the rule's n >= 10). trade/settings.live_refusal asks it
when the owner moves the flag to live; rangedca/trade.py asks it again before every action on the real account, so
a hand edit of the flag or a proof that turned negative never trades real money. Nothing here sets a flag.
11.11. (the owner's decision 1): the demo account's reclaim rounds (levels "reclaim": true) are counted apart: they are
not in proof() (the real account trades the ATR stop without reclaim), only in reclaim_proof() and the real account's
reclaim gate reclaim_refusal() (>= 7 nights of the nightly stop comparison, >= 20 closed reclaim rounds, EV > 0 after
cost). The owner's learning labels (rangedca/owner.py) are never read here.
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


def is_reclaim(levels):
    """11.11. (decision 1): a reclaim round (range_rounds.levels "reclaim": true)."""
    try:
        return bool((json.loads(levels or "{}") or {}).get("reclaim"))
    except (ValueError, AttributeError):
        return False


def proof(path=None, with_rets=False, source=None, reclaim=False):
    """{"n", "wins", "pnl_usd", "ev_pct", "ci90_lo_pct"} (+ "rets" with_rets) of the demo account's closed range
    rounds (zeros when none); ev_pct / ci90_lo_pct net of the calibrated cost (trade/cost.demo_adjust). source
    (11.11.): "missed" = only the rounds opened from source missed, "other" = all the others; None = every round.
    reclaim (11.11., decision 1): False = the ordinary rounds (the ATR stop, what the real account trades: range_dca's
    and range_missed's proof, the proposals' range record); True = only the reclaim rounds (reclaim_refusal)."""
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
    rows = [r for r in rows if is_reclaim(r[2]) == bool(reclaim)]
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


# ---------- reclaim on the real account (11.11., the owner's decision 1) ---------------------------------------------
# The demo account trades the ATR stop + reclaim (rangedca/trade.py); the real account trades the ATR stop alone and a
# reclaim only past this gate, asked again before every reclaim (trade.may_reclaim): >= RECLAIM_MIN_NIGHTS nights of the
# nightly stop comparison (rangedca/backtest.run_server keeps their dates in range.db kv stop_backtest_nights) AND >=
# RECLAIM_MIN_ROUNDS closed demo reclaim rounds (range_rounds.levels "reclaim": true) whose mean result per round net of
# the calibrated cost (trade/cost.demo_adjust, as proof()) is above zero (the owner's words: "EV > 0 nakon troškova";
# reclaim_proof_ok has trade/edge.live_proof's shape). Nothing here sets a flag; no flag exists for it.
RECLAIM_MIN_NIGHTS = 7
RECLAIM_MIN_ROUNDS = 20
RECLAIM_MIN_EV = 0.03      # 11.11. (Jure): "min. 20 reclaim rundi s EV >= +3 % nakon troška"
_RCACHE = {"at": 0.0, "key": None, "val": None}


def stop_nights(path=None):
    """The dates (YYYY-MM-DD, UTC) of the nights the stop comparison ran (range.db kv stop_backtest_nights); []."""
    from . import data
    con = data.ro(path)
    if con is None:
        return []
    try:
        v = data.kv_get(con, "stop_backtest_nights") or []
        return [d for d in v if isinstance(d, str)] if isinstance(v, list) else []
    except sqlite3.Error:
        return []
    finally:
        con.close()


def reclaim_proof(path=None, with_rets=False):
    """proof() of the demo account's closed reclaim rounds only."""
    return proof(path, with_rets=with_rets, reclaim=True)


def reclaim_proof_ok(rets, n_min=RECLAIM_MIN_ROUNDS):
    """(ok, why not or None, trade/edge.ev_stats) of the reclaim rounds' results (fractions, net of cost): n >= n_min
    and EV (their mean) >= RECLAIM_MIN_EV (+3 % per round, the owner's rule of 11.11.)."""
    from trade import edge
    s = edge.ev_stats(rets)
    if s["n"] < n_min:
        return False, f"zatvorenih reclaim rundi {s['n']} od potrebnih {n_min}", s
    if s["ev"] is None or s["ev"] < RECLAIM_MIN_EV - 1e-12:
        return False, (f"EV reclaim rundi {(s['ev'] or 0) * 100:+.2f} % po rundi nakon troška, treba barem "
                       f"{RECLAIM_MIN_EV * 100:+.0f} %"), s
    return True, None, s


def reclaim_refusal(path=None, rpath=None, now=None, cached=False):
    """None when the real account may buy a reclaim, else the reason in Croatian (see above)."""
    now = now or time.time()
    key = (path, rpath)
    if cached and _RCACHE["key"] == key and now - _RCACHE["at"] < CACHE_S:
        return _RCACHE["val"]
    nights = len(set(stop_nights(rpath)))
    why = None
    if nights < RECLAIM_MIN_NIGHTS:
        why = f"reclaim: tek {nights} noći usporedbe stopova, treba {RECLAIM_MIN_NIGHTS}"
    else:
        p = reclaim_proof(path, with_rets=True)
        ok, w, _s = reclaim_proof_ok(p["rets"])
        if not ok:
            why = f"reclaim: {w}"
    _RCACHE.update(at=now, key=key, val=why)
    return why


def reclaim_live_refusal(con=None, now=None):
    """trade/settings.LIVE_GATES' shape: (con, now=) -> None or the reason."""
    return reclaim_refusal(now=now)


def reclaim_line(path=None, rpath=None):
    """One log line of the demo reclaim rounds and the real account's reclaim gate (the nightly comparison)."""
    p = reclaim_proof(path)
    why = reclaim_refusal(path, rpath)
    ev = f"EV {p['ev_pct']:+.2f} %" if p["ev_pct"] is not None else "EV -"
    return (f"range reclaim (demo, ATR + reclaim): {p['n']} zatvorenih rundi, {ev} nakon troška, PnL "
            f"{p['pnl_usd']:+.2f} $; noći usporedbe {len(set(stop_nights(rpath)))}/{RECLAIM_MIN_NIGHTS}; pravi račun: "
            + (why or "reclaim dozvoljen"))
