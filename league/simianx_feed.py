"""SimianX long signals -> the real-trade competition account, only with the owner's approval.

While trade.settings.simianx_on() is True (the owner's checkbox on /pravi-trade, off by default), every fresh, unused
long signal from simianx.db (simianx/run.py) becomes a $real_usd buy on trade.settings.LEAGUE_USER with SimianX's stop
and target as auto TP/SL. run_trade.py mirrors that account into real swaps within the page's limits (stake, daily
spend and loss, open positions). Called from league/auto.loop, the only writer of league.db; which signals were used
is kept in league.db (simianx_used), so simianx.db keeps one writer too. Switch off -> nothing is read."""
import sqlite3
import time

from . import store

SCHEMA = "CREATE TABLE IF NOT EXISTS simianx_used (signal_id INTEGER PRIMARY KEY, trade_id INTEGER, ts INTEGER, note TEXT)"


def _require_signal(con, user, mint, now):
    """10.11. (Jure: "bez ulaza bez signala", flag require_signal): a SimianX signal with no caller's call and no buy by
    a wallet with a tier on the token is not bought while the flag applies (ValueError, logged as skipped); in shadow
    it is bought as before and the skip it would make goes to shadow_decisions."""
    from . import copy as lcopy, flags
    m = flags.mode("require_signal")
    if m == "off":
        return
    on, sh = flags.applies("require_signal", user, m), flags.shadowing("require_signal", user, m)
    if not on and not sh:
        return
    ok, why = lcopy.signal_for(mint, now)
    if ok:
        return
    if on:
        raise ValueError(f"bez signala: {why}")
    flags.shadow(con, "require_signal", None, mint, "ulaz", "preskočeno", {"gate": "signal", "src": "simianx",
                                                                            "why": why})


def run_once(con, market, now=None, on=None, sx_con=None, cfg=None):
    """-> [(user, what happened)]."""
    from trade import settings
    if not (settings.simianx_on() if on is None else on):
        return []
    from simianx import run as sxrun, store as sxstore
    cfg = cfg or sxrun.config()
    now = now or time.time()
    own = sx_con is None
    sx = sx_con or sxstore.ro()
    if sx is None:
        return []
    out = []
    try:
        con.execute(SCHEMA)
        used = {i for (i,) in con.execute("SELECT signal_id FROM simianx_used")}
        try:
            rows = sx.execute("SELECT * FROM signals WHERE ts>? ORDER BY id", (now - cfg["signal_max_age_s"],)).fetchall()
        except sqlite3.OperationalError:
            return []   # simianx.db still empty (first pass not run yet)
        sigs = [s for s in rows if s["id"] not in used]
        if not sigs:
            return []
        mk = market({s["mint"] for s in sigs}) or {}
        user = settings.LEAGUE_USER
        for s in sigs:
            if s["mint"] not in mk:
                continue   # no price this pass: try again in 20 s while the signal is fresh
            price, liq, _, mcap = mk[s["mint"]]
            try:
                _require_signal(con, user, s["mint"], now)   # 10.11. (Jure, flag require_signal)
                tid = store.buy(con, user, s["mint"], s["symbol"], cfg["real_usd"], price, liq, "simianx", None, mcap)
                from . import auto
                auto.set_auto(con, user, tid, "tpsl", f"{100 * s['target_pct']:+.1f}%", f"{100 * s['stop_pct']:+.1f}%")
                note = f"kupljeno, TP {s['target_pct']:+.0%} SL {s['stop_pct']:+.0%}"
            except ValueError as e:
                tid, note = None, f"preskočeno: {e}"
            con.execute("INSERT OR REPLACE INTO simianx_used VALUES (?,?,?,?)", (s["id"], tid, int(now), note))
            con.commit()
            out.append((user, f"SimianX {s['symbol']}: {note}"))
        return out
    finally:
        if own:
            sx.close()
