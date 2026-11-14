"""momentum_scalp on the Autopilot's demo accounts (flag momentum_scalp; league.db's only writer, run_ui.py, runs this):

  run_once    every pass of league/auto.loop (20 s): one entry per FRESH signal (momentum.db, at most SIGNAL_FRESH_S old)
  exits_once  every second in league/auto.fast_loop: TP1 half at +15 %, the rest on an 8 % trailing stop from the
              peak, stop -10 %, time stop 45 min (momentum/rules.exit_step)

Modes (league/flags): off nothing new (trades already open keep their exits: a stop is never dropped; looked for
once a minute); shadow: the real account LEAGUE_USER only logs what it would buy (league.db shadow_decisions);
paper: the demo account PAPER_USER trades (run_trade.py never mirrors it), LEAGUE_USER logs; live: both trade, and
LEAGUE_USER only while momentum/gate.refusal() is None (>= 50 closed paper trades, EV > 0, hit rate >= 45 %),
checked again every minute. LEAGUE_USER's positions are never touched in paper: every query is by user.

A trade = one demo lot (source "momentum scalp", no auto TP/SL of its own) and its row in momentum_trades (league.db):
the signal it came from, entry, state (tp1 done, peak), and at the end the PnL of every part sold (TP1's half is its
own closed row, league/store.sell_partial), hit (TP1 came before the stop) and the exit reason.

Before the buy, again on the live quote: bonded, MC 30k-3M, liquidity >= $15k, the copy loop's pool and rug guards
(league/copy), and the price not more than chase_max (5 %) above the signal's. Limits: trade settings size_sol at the
SOL price, max_open open momentum trades per account, max_sol_per_day of momentum entries per Zagreb day.
"""
import json
import sqlite3
import time

from league import store
from . import data, gate, rules

FLAG = "momentum_scalp"
SRC = "momentum scalp"
SIGNAL_FRESH_S = 120        # a signal older than this is not bought (the jump goes on without us)
STALE_S = 60                # an older price fires only the stop
OFF_CHECK_S = 60
EXIT_RULE = {"tp1": "tp", "trailing": "tp", "stop": "sl", "time": "time"}
REASON_HR = {"tp1": "pola van na +15 %", "trailing": "trailing 8 % od vrha", "stop": "stop -10 %",
             "time": "45 min, izlaz po vremenu"}

SCHEMA = """CREATE TABLE IF NOT EXISTS momentum_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, token TEXT, symbol TEXT, signal_id INTEGER, opened_ts INTEGER,
    closed_ts INTEGER, status TEXT, trade_id INTEGER, entry_px REAL, entry_mc REAL, size_usd REAL, state TEXT,
    pnl_usd REAL, ret REAL, hit INTEGER, exit_reason TEXT);
CREATE INDEX IF NOT EXISTS momentum_trades_status ON momentum_trades (status, user, token);"""

_CACHE = {"off_at": 0.0, "off_open": False, "gate_log": 0.0}
_SHADOWED = {}


def ensure(con):
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='momentum_trades'").fetchone() is None:
        con.executescript(SCHEMA)


def _flags():
    from league import flags
    return flags


def mode():
    return _flags().mode(FLAG)


def roles(m, now=None):
    """(accounts that trade, accounts that only log) in mode m. LEAGUE_USER trades only past the live gate."""
    from trade import settings as ts
    fl = _flags()
    act = [u for u in fl.autopilot_users() if fl.applies(FLAG, u, m)]
    sh = [u for u in fl.autopilot_users() if fl.shadowing(FLAG, u, m)]
    if m in ("paper", "live") and ts.pravi_novac_sve():
        # 14.11. (owner: "nema više demo"): the real account trades too, without the paper proof (gate.refusal); the demo
        # account keeps trading as in paper / live; the caps are trade/executor's SWITCH_CAPS on the real swap
        act = [ts.LEAGUE_USER] + [u for u in act if u != ts.LEAGUE_USER]
        return act, [u for u in sh if u != ts.LEAGUE_USER]
    if ts.LEAGUE_USER in act:
        why = gate.refusal(now=now, cached=True)
        if why:
            act.remove(ts.LEAGUE_USER)
            sh.append(ts.LEAGUE_USER)
            t = now or time.time()
            if t - _CACHE["gate_log"] > 3600:
                _CACHE["gate_log"] = t
                print(f"momentum_scalp live: pravi račun ne trguje ({why}); samo zapis u sjeni", flush=True)
    return act, sh


def trades(con, status="open", user=None):
    ensure(con)
    sql, args = "SELECT * FROM momentum_trades WHERE status=?", [status]
    if user:
        sql += " AND user=?"
        args.append(user)
    cur = con.execute(sql + " ORDER BY id", args)
    cols = [c[0] for c in cur.description]
    out = []
    for row in cur.fetchall():
        d = dict(zip(cols, row))
        d["state"] = json.loads(d["state"] or "{}")
        out.append(d)
    return out


def guards(tok, mq, signal_px=None, cfg=None):
    """The entry guards on the live quote (league/copy's pool and rug guards included): None or the reason."""
    from league import copy
    c = rules._r(cfg)
    price, liq, _url, mcap = mq[:4]
    if copy._bonding_curve(mq) or copy._dex_pair_empty(mq):
        return "token je još na pump.fun krivulji ili bez DexScreener para (uzimaju se bondani)"
    if (mcap or 0) < max(c["mcap_min"], copy.CFG["min_mcap"]):
        return "MC ispod 30k (ispod 30k se ne kupuje)"
    if (mcap or 0) > c["mcap_max"]:
        return f"MC ${mcap:,.0f} iznad ${c['mcap_max']:,.0f}"
    if (liq or 0) < c["liq_min"]:
        return f"likvidnost ${liq or 0:,.0f}, treba ${c['liq_min']:,.0f}"
    if mcap and liq and liq > mcap:
        return "lažni pool (likvidnost veća od MC-a)"
    if mcap and liq and liq < copy.CFG["min_liq_mcap"] * mcap:
        return f"likvidnost samo {liq / mcap:.1%} MC-a"
    if signal_px and price > signal_px * (1 + c["chase_max"]):
        return f"cijena je već {price / signal_px - 1:+.1%} od signala (najviše {c['chase_max']:+.0%})"
    col = copy._rugged(tok, mcap, liq)
    if col:
        return f"rug ({col['text']})"
    why, _shown = copy._concentration(tok)
    return why


def _spent_today(con, user, now, sol):
    from rangedca import trade as rtrade
    usd = con.execute("SELECT COALESCE(SUM(size_usd), 0) FROM momentum_trades WHERE user=? AND opened_ts>=?",
                      (user, rtrade._day_start(now))).fetchone()[0] or 0
    return usd / sol if sol else 0.0


def fresh_signals(now, path=None):
    """{token: signal} of the signals of the last SIGNAL_FRESH_S, newest per token (momentum.db, read-only)."""
    out = {}
    for s in data.read_signals(now - SIGNAL_FRESH_S, path):
        out.setdefault(s["token"], s)
    return out


def run_once(con, market_fn=None, now=None, signals=None, lim=None, sol=None):
    """One entry pass: [(user, text)]. Off: nothing at all (one cached flag read)."""
    m = mode()
    if m == "off":
        return []
    now = int(now or time.time())
    act, sh = roles(m, now)
    if not act and not sh:
        return []
    sigs = signals if signals is not None else fresh_signals(now)
    sigs = {t: s for t, s in sigs.items() if now - s["ts"] <= SIGNAL_FRESH_S}
    if not sigs:
        return []
    ensure(con)
    from league import copy
    from rangedca import trade as rtrade
    mk = (market_fn or copy.market)(sorted(sigs)) or {}
    lim = lim or rtrade.limits(now)
    sol = sol or rtrade.sol_usd()
    done = []
    if not sol:
        return done
    for user in act:
        n_open = len(trades(con, "open", user))
        for tok in sorted(sigs, key=lambda t: -sigs[t]["ts"]):
            if n_open >= lim["max_open"]:
                break
            got = _enter(con, user, tok, sigs[tok], mk.get(tok), lim, sol, now)
            if got:
                n_open += 1
                done += got
    for user in sh:
        for tok, s in sigs.items():
            mq = mk.get(tok)
            if not mq or not mq[0] or (user, s["id"]) in _SHADOWED:
                continue
            if guards(tok, mq, s["price"]) is None:
                _SHADOWED[(user, s["id"])] = now
                _flags().shadow(con, FLAG, None, tok, "ništa", "momentum ulaz",
                                {"user": user, "signal_id": s["id"], "mc": mq[3], "ch_m5": (s.get("features") or {}).get("ch_m5")},
                                now)
                con.commit()
    for k in [k for k, ts in _SHADOWED.items() if now - ts > 3600]:
        _SHADOWED.pop(k, None)
    return done


def _enter(con, user, tok, s, mq, lim, sol, now):
    if not mq or not mq[0]:
        return []
    if con.execute("SELECT 1 FROM trades WHERE user=? AND token=? AND status='open'", (user, tok)).fetchone():
        return []   # already held (by a copy, a range round or an earlier momentum trade): never doubled
    if con.execute("SELECT 1 FROM momentum_trades WHERE user=? AND signal_id=?", (user, s["id"])).fetchone():
        return []
    price, liq, _url, mcap = mq[:4]
    if guards(tok, mq, s["price"]):
        return []
    lot = float(lim["size_sol"])
    if _spent_today(con, user, now, sol) + lot > float(lim["max_sol_per_day"]) + 1e-9:
        return []
    sym = (mq[4] if len(mq) > 4 else None) or s.get("symbol")
    try:
        tid = store.buy(con, user, tok, sym, lot * sol, price, liq, SRC, None, mcap)
    except ValueError as e:
        print(f"momentum {user} {tok[:6]}: ulaz nije prošao ({e})", flush=True)
        return []
    con.execute("UPDATE trades SET auto=NULL, auto_state=NULL WHERE id=?", (tid,))   # our exit loop sells it
    con.execute("INSERT INTO momentum_trades (user, token, symbol, signal_id, opened_ts, status, trade_id, entry_px, "
                "entry_mc, size_usd, state) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (user, tok, sym, s["id"], now, "open", tid, price, mcap, lot * sol, json.dumps({"pnl": 0.0})))
    con.commit()
    _switch_stop(con, user, tok, now)
    return [(user, f"momentum ulaz {sym or tok[:6]}: {lot:g} SOL na MC ${mcap or 0:,.0f} "
                   f"(signal #{s['id']}, {((s.get('features') or {}).get('ch_m5') or 0):+.1f} % u 5 min)")]


def _switch_stop(con, user, tok, now):
    """14.11. (pravi_novac_sve): a real-account entry gets its server-side protective stop at once (league/exitplan);
    this module's own exit (stop -10 %) keeps running first. Never fails the entry."""
    try:
        from trade import settings as ts
        if user == ts.LEAGUE_USER and ts.pravi_novac_sve():
            from league import exitplan
            exitplan.switch_stop(con, tok, user, now=int(now))
    except Exception as e:  # noqa: BLE001 - the sweep (exitplan.ensure_switch_stops) tries again
        print(f"momentum {tok[:6]}: zaštitni stop nije postavljen ({type(e).__name__}: {e})", flush=True)


# ---------- exits (every second) ------------------------------------------------------------------------------------
def _lots(con, r):
    cur = con.execute("SELECT * FROM trades WHERE id=? AND user=? AND status='open'", (r["trade_id"], r["user"]))
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _finish(con, r, reason, now):
    st = r["state"]
    pnl = float(st.get("pnl") or 0)
    ret = pnl / r["size_usd"] if r["size_usd"] else None
    con.execute("UPDATE momentum_trades SET status='closed', closed_ts=?, pnl_usd=?, ret=?, hit=?, exit_reason=?, state=? "
                "WHERE id=? AND status='open'", (int(now), pnl, ret, int(bool(st.get("tp1"))), reason, json.dumps(st),
                                                 r["id"]))
    con.commit()
    return pnl


def exits_once(con, market_fn, now=None):
    """The exits of every open momentum trade: [text]. Flag off: the open trades still get their exits (looked for
    once a minute); none open: nothing."""
    now = now or time.time()
    m = mode()
    if m == "off":
        if now - _CACHE["off_at"] < OFF_CHECK_S and not _CACHE["off_open"]:
            return []
        _CACHE["off_at"] = now
        try:
            _CACHE["off_open"] = con.execute("SELECT 1 FROM sqlite_master WHERE name='momentum_trades'").fetchone() is not None \
                and con.execute("SELECT 1 FROM momentum_trades WHERE status='open' LIMIT 1").fetchone() is not None
        except sqlite3.Error:
            _CACHE["off_open"] = False
        if not _CACHE["off_open"]:
            return []
    elif con.execute("SELECT 1 FROM sqlite_master WHERE name='momentum_trades'").fetchone() is None:
        return []
    open_t = trades(con)
    if not open_t:
        return []
    from league import exitplan
    q = exitplan.quote(market_fn, {r["token"] for r in open_t}, now)
    out = []
    for r in open_t:
        lots = _lots(con, r)
        if not lots:   # sold by an exit plan (Grok) or by hand: the trade ends with what was booked
            con.execute("UPDATE momentum_trades SET state=? WHERE id=?", (json.dumps(r["state"]), r["id"]))
            pnl = _finish(con, r, r["state"].get("last") or "prodano izvan strategije", now)
            out.append(f"momentum {r['user']} {r['symbol'] or r['token'][:6]}: zatvoreno izvan strategije ({pnl:+.2f} $)")
            continue
        if r["token"] not in q:
            continue
        price, mcap, liq, age = q[r["token"]]
        st = r["state"]
        before = json.dumps(st, sort_keys=True)
        hit = rules.exit_step(st, r["entry_px"], price, now, r["opened_ts"], stale=age > STALE_S)
        if not hit:
            if json.dumps(st, sort_keys=True) != before:
                con.execute("UPDATE momentum_trades SET state=? WHERE id=?", (json.dumps(st), r["id"]))
                con.commit()
            continue
        reason, frac = hit
        t = lots[0]
        rule = EXIT_RULE[reason]
        note = f"momentum: {REASON_HR[reason]}"
        try:
            if frac >= 0.999:
                pnl = store.sell(con, r["user"], t["id"], price, liq, note, mcap=mcap, exit_rule=rule)
                left = False
            else:
                pnl, sold_all = store.sell_partial(con, r["user"], t["id"], frac, price, liq, mcap=mcap)
                part = t["id"] if sold_all else con.execute(
                    "SELECT MAX(id) FROM trades WHERE user=? AND token=? AND status='closed'", (r["user"], r["token"])).fetchone()[0]
                store.set_data(con, part, exit_rule=rule)
                con.execute("UPDATE trades SET note=? WHERE id=?", (f"{note} ({frac:.0%})", part))
                left = not sold_all
        except ValueError as e:   # closed in the same second by another path: next pass
            print(f"momentum {r['token'][:6]}: {e}", flush=True)
            continue
        st["pnl"] = round(float(st.get("pnl") or 0) + pnl, 6)
        st["last"] = reason
        con.execute("UPDATE momentum_trades SET state=? WHERE id=?", (json.dumps(st), r["id"]))
        con.commit()
        text = (f"momentum {r['user']} {r['symbol'] or r['token'][:6]}: {REASON_HR[reason]}, prodano {frac:.0%} na MC "
                f"${mcap or 0:,.0f}, {pnl:+.2f} $")
        if not left:
            tot = _finish(con, r, reason, now)
            text += f"; trade gotov {tot:+.2f} $"
        out.append(text)
    return out


def view_trades(con, user=None, limit=30):
    """Open trades and the last closed ones, for the MCP API."""
    ensure(con)
    out = {"open": trades(con, "open", user)}
    sql = "SELECT * FROM momentum_trades WHERE status='closed'" + (" AND user=?" if user else "") + " ORDER BY id DESC LIMIT ?"
    cur = con.execute(sql, ((user,) if user else ()) + (int(limit),))
    cols = [c[0] for c in cur.description]
    out["closed"] = [dict(zip(cols, row)) for row in cur.fetchall()]
    for d in out["closed"]:
        d.pop("state", None)
    return out
