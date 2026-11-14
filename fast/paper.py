"""The fast path's trades (flag fast_path G24). Runs inside league/auto.loop (run_ui.py, league.db's only writer),
right after the copy loop; a BUY decision wakes that loop (league/copy.wake), so the entry follows within a second.

  off / shadow   no entry (shadow = every check and decision in fast.db, nothing traded). Trades already open keep
                 their exits and the copy exit below: a stop is never dropped.
  paper          BUY_PAPER and BUY_LIVE both enter on the DEMO account PAPER_USER (autopilot-paper; run_trade.py never
                 mirrors it): BUY_PAPER with the small stake (decide.PAPER_SOL, 0.05 SOL), BUY_LIVE with the trade
                 settings' size_sol, BUY_LIVE only labelled. The real account LEAGUE_USER is never touched.
  live           never set by code (trade/settings.LIVE_GATES: live_refusal below, >= MIN_CLOSED closed fast-path paper
                 trades with EV > 0). BUY_LIVE of a source with an Autopilot follow enters on LEAGUE_USER as that
                 follow's copy ("copy wallet <label>", follow_id, a copy_log 'ulaz' row with the signal's time), so
                 run_trade.py applies its own proof (PROOF on the follow), the live switch and TRADE_LIVE exactly as
                 for every copy; never doubled when the copy loop already entered. BUY_LIVE without a follow and
                 BUY_PAPER go to the demo account.

Entry: only decisions of the last FRESH_S (120 s), a live quote (league/copy.market) with the copy loop's pool and rug
guards (momentum/trade.guards without its momentum MC cap), the price not more than CHASE_MAX (10 %) above the price
the check saw, the account not already holding the token, at most lim max_open open fast trades per account and
lim max_sol_per_day of fast entries per Zagreb day (the demo account's existing limits, rangedca/trade.limits).
Exit (Jure, point 5): the lot's own TP/SL (+15 % / -10 % / 45 min hold, league/auto "tpsl") and the plan through
league/exitplan.set_plan: half at +15 %, trailing 8 % from the peak after +15 %, stop -10 %, everything out after 45 min
(when no other plan is active on the token; the plan replaces the lot's TP/SL where exit_plans applies to the account,
elsewhere the lot's own levels hold). Copy exit: when the source wallet sells the token (hype.db chain_trades, a sale
at or after the buy we copied), every open lot of the fast trade is sold at once (exit_rule wallet_sold).
league.db fast_trades: one row per (account, signal), closed with the sum of its lots (a plan's partial sale is its
own closed trade row of the same entry).
"""
import json
import os
import sqlite3
import time

from . import sources, store

FLAG = "fast_path"
SRC = "fast path"
FRESH_S = 120
CHASE_MAX = 0.10
MIN_CLOSED = 30
EXIT_TP, EXIT_SL, EXIT_TRAIL, EXIT_MIN = 15, 10, 8, 45
PLAN = {"take_profits": [{"at_pct": EXIT_TP, "sell_share": 0.5}],
        "trailing": {"activate_pct": EXIT_TP, "trail_pct": EXIT_TRAIL},
        "stop": {"at_pct": -EXIT_SL}, "time_stop": {"after_min": EXIT_MIN, "if_pnl_below_pct": 1000},
        "reason": "fast path: pola van na +15 %, ostatak trailing 8 %, stop -10 %, van nakon 45 min"}
SCHEMA = """CREATE TABLE IF NOT EXISTS fast_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, signal_id INTEGER, token TEXT, symbol TEXT, source_id TEXT,
    kind TEXT, decision TEXT, trade_id INTEGER, plan_id INTEGER, sig_ts INTEGER, opened_ts INTEGER, size_usd REAL,
    entry_px REAL, status TEXT, closed_ts INTEGER, pnl_usd REAL, ret REAL, exit_reason TEXT, UNIQUE (user, signal_id));
CREATE INDEX IF NOT EXISTS fast_trades_status ON fast_trades (status, user);
CREATE INDEX IF NOT EXISTS fast_trades_source ON fast_trades (source_id, status);"""
_TRIED = {}   # signal id -> ts of a decision that could not be traded (logged once)


def ensure(con):
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fast_trades'").fetchone() is None:
        con.executescript(SCHEMA)


def mode():
    try:
        from league import flags
        return flags.mode(FLAG)
    except Exception:  # noqa: BLE001
        return "off"


# ---------- the live gate --------------------------------------------------------------------------------------------

def proof(lcon=None, with_rets=False):
    """{"n", "wins", "pnl_usd", "ev_pct", "ci90_lo_pct"} (+ "rets") of the demo account's closed fast-path trades
    (zeros when none); the results net of the calibrated cost (trade/cost.demo_adjust)."""
    from league import store as lstore
    from trade import cost, edge, settings
    own = lcon is None
    try:
        if own:
            lcon = sqlite3.connect(f"file:{lstore.DB}?mode=ro", uri=True, timeout=5)
        rows = lcon.execute("SELECT pnl_usd, ret FROM fast_trades WHERE user=? AND status='closed'",
                            (settings.PAPER_USER,)).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        if own and lcon is not None:
            lcon.close()
    adj = cost.demo_adjust()
    rets = [r + adj for _p, r in rows if r is not None]
    s = edge.ev_stats(rets)
    return {"n": len(rows), "wins": sum(1 for p, _r in rows if (p or 0) > 0),
            "pnl_usd": round(float(sum(p or 0 for p, _r in rows)), 2),
            "ev_pct": round(s["ev"] * 100, 2) if s["ev"] is not None else None,
            "ci90_lo_pct": round(s["lo90"] * 100, 2) if s["lo90"] is not None else None,
            **({"rets": rets} if with_rets else {})}


def live_refusal(con=None, now=None):
    """trade/settings.LIVE_GATES: None when fast_path may go live (on top of the backtest and the 7 paper days in the
    plus), else why not: >= MIN_CLOSED closed fast-path paper trades on the demo account passing trade/edge.live_proof
    (11.11. owner's rule D: EV >= +3 %, the 90 % interval's lower bound > 0; MIN_CLOSED 30 >= its n 10)."""
    from trade import edge
    p = proof(with_rets=True)
    if p["n"] < MIN_CLOSED:
        return f"fast_path: tek {p['n']} zatvorenih paper tradeova, treba {MIN_CLOSED}"
    ok, why, _s = edge.live_proof(p["rets"])
    if not ok:
        return f"fast_path: dokaz paper tradeova nije prošao: {why}"
    return None


# ---------- entries ------------------------------------------------------------------------------------------------------

def fresh(now, path=None):
    """BUY decisions of the last FRESH_S (fast.db, read-only). 12.11.: never an x_call (Grok's submit_watch_token:
    only checked and measured by x_call_scalp, no account trades it)."""
    con = store.ro(path)
    if con is None:
        return []
    try:
        return store.read(con, "status='done' AND decision IN ('BUY_PAPER', 'BUY_LIVE') AND decided_ts >= ? AND "
                               "COALESCE(kind, '') != 'x_call'", (now - FRESH_S,), order="decided_ts", limit=100)
    finally:
        con.close()


def note_traded(sid, what, path=None):
    """fast.db signals.traded (best effort: the card and get_fast_checks show it; league.db fast_trades is the
    record)."""
    p = path or store.db_path()
    if not os.path.exists(p):
        return
    try:
        con = sqlite3.connect(p, timeout=2)
        try:
            con.execute("UPDATE signals SET traded=? WHERE id=?", (json.dumps(what, ensure_ascii=False), int(sid)))
            con.commit()
        finally:
            con.close()
    except sqlite3.Error:
        pass


def _route(s, m, switch=False):
    """(account, live?) of a BUY decision in mode m; None when this mode does not trade. live = the copy path (a copy
    of the source's Autopilot follow). switch (14.11., the owner's pravi_novac_sve): every BUY decision, BUY_PAPER
    too, enters on the REAL account (the copy path when the source has a follow), without the follow's proof."""
    from trade import settings
    if switch and m in ("paper", "live"):
        return settings.LEAGUE_USER, bool(s.get("follow_id") and s.get("kind") in ("wallet_follow", "influencer"))
    if m == "paper":
        return settings.PAPER_USER, False
    if m == "live":
        if s["decision"] == "BUY_LIVE" and s.get("follow_id") and s.get("kind") in ("wallet_follow", "influencer"):
            return settings.LEAGUE_USER, True
        return settings.PAPER_USER, False
    return None


def _spent_today(con, user, now, sol):
    from league import copy as lcopy
    usd = con.execute("SELECT COALESCE(SUM(size_usd), 0) FROM fast_trades WHERE user=? AND opened_ts>=?",
                      (user, lcopy._day_start(int(now)))).fetchone()[0] or 0
    return usd / sol if sol else 0.0


def _guards(tok, mq, price0):
    from league import copy as lcopy
    price, liq, _url, mcap = mq[:4]
    if lcopy._bonding_curve(mq) or lcopy._dex_pair_empty(mq):
        return "token je još na pump.fun krivulji ili bez DexScreener para (uzimaju se bondani)"
    if (mcap or 0) < lcopy.CFG["min_mcap"]:
        return "MC ispod 30k (ispod 30k se ne kupuje)"
    if (liq or 0) < 20_000:
        return f"likvidnost ${liq or 0:,.0f}, treba $20,000"
    if mcap and liq and liq > mcap:
        return "lažni pool (likvidnost veća od MC-a)"
    if mcap and liq and liq < lcopy.CFG["min_liq_mcap"] * mcap:
        return f"likvidnost samo {liq / mcap:.1%} MC-a"
    if price0 and price > price0 * (1 + CHASE_MAX):
        return f"cijena je od odluke već {price / price0 - 1:+.1%} (najviše {CHASE_MAX:+.0%})"
    col = lcopy._rugged(tok, mcap, liq)
    if col:
        return f"rug ({col['text']})"
    return None


def _sl_default():
    try:
        from trade import executor, settings
        tc = settings.connect()
        try:
            return float(settings.merged(executor.load_config(), tc).get("sl_default") or 60)
        finally:
            tc.close()
    except Exception:  # noqa: BLE001
        return 60.0


def enter(con, s, user, live, mq, lim, sol, now, path=None, switch=False):
    """One entry; (text or None, why not or None). switch (14.11., pravi_novac_sve): the entry is on the real account
    by the owner's switch: its plan executes there (league/exitplan.SWITCH_SRC) and, when the token already has
    another plan, the lot's own TP/SL is its stop (a protective stop is added when no plan is active)."""
    from league import auto, copy as lcopy, exitplan
    from league import store as lstore
    tok = s["token"]
    if con.execute("SELECT 1 FROM fast_trades WHERE user=? AND signal_id=?", (user, s["id"])).fetchone():
        return None, None
    if con.execute("SELECT 1 FROM trades WHERE user=? AND token=? AND status='open'", (user, tok)).fetchone():
        return None, "račun već drži token (npr. kopija istog signala): ne udvostručuje se"
    if not mq or not mq[0]:
        return None, "nema žive cijene"
    why = _guards(tok, mq, s.get("price0"))
    if why:
        return None, why
    n_open = con.execute("SELECT COUNT(*) FROM fast_trades WHERE user=? AND status='open'", (user,)).fetchone()[0]
    if n_open >= int(lim.get("max_open") or 5):
        return None, f"već {n_open} otvorenih fast tradeova (strop {lim.get('max_open')})"
    size = float(s.get("size_sol") or 0)
    if size < 0.005:
        return None, "ulog premalen"
    if _spent_today(con, user, now, sol) + size > float(lim.get("max_sol_per_day") or 1.0) + 1e-9:
        return None, f"dnevni strop fast ulaza ({lim.get('max_sol_per_day')} SOL) potrošen"
    price, liq, _url, mcap = mq[:4]
    sym = (mq[4] if len(mq) > 4 else None) or s.get("symbol")
    label = s.get("source_label") or (s.get("source_id") or "")[:8]
    if live:
        src = f"copy {'wallet' if s.get('kind') == 'wallet_follow' else 'KOL'} {label} (fast)"
    else:   # 14.11.: on the real account by pravi_novac_sve too (run_trade reads "fast path" as the strategy)
        src = f"{SRC} {s['decision'].lower()}: {label}"
    try:
        tid = lstore.buy(con, user, tok, sym, size * sol, price, liq, src, None, mcap)
    except ValueError as e:
        return None, f"ulaz nije prošao ({e})"
    if live:   # the copy path: run_trade's proof is on this follow; the call time is the signal's
        con.execute("UPDATE trades SET follow_id=? WHERE id=?", (s["follow_id"], tid))
        con.execute("INSERT OR IGNORE INTO copy_log VALUES (?,?,?,?,?,?,?,?,?)",
                    (s["follow_id"], tok, "buy", s.get("sig_ts"), int(now), sym, "ulaz",
                     f"fast path: {s.get('reason') or ''}"[:300], tid))
    try:   # the lot's own levels: they hold wherever the plan is not in force
        auto.set_auto(con, user, tid, "tpsl", f"{EXIT_TP}%", f"-{EXIT_SL}%", hold_s=EXIT_MIN * 60)
    except ValueError as e:
        try:
            auto.set_auto(con, user, tid, "tpsl", "", f"-{EXIT_SL}%", hold_s=EXIT_MIN * 60)
        except ValueError:
            auto.set_auto(con, user, tid, "smart")
        print(f"fast {tok[:6]}: TP lota nije postavljen ({e})", flush=True)
    plan_id = None
    if exitplan.active(con, tok) is None:
        try:
            client = f"fast #{s['id']}"
            got = exitplan.set_plan(con, tok, dict(PLAN, accounts=[user]), _sl_default(),
                                    client=exitplan.switch_client(client, user, switch) if switch else client,
                                    now=int(now))
            plan_id = got["plan_id"]
        except ValueError as e:
            print(f"fast {tok[:6]}: plan izlaza nije postavljen ({e})", flush=True)
    if switch and plan_id is None:   # 14.11.: no plan of its own: the protective stop (only when none is active)
        plan_id = exitplan.switch_stop(con, tok, user, now=int(now))
    row = con.execute("SELECT opened_ts, size_usd, entry_px FROM trades WHERE id=?", (tid,)).fetchone()
    con.execute("INSERT OR IGNORE INTO fast_trades (user, signal_id, token, symbol, source_id, kind, decision, trade_id, "
                "plan_id, sig_ts, opened_ts, size_usd, entry_px, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (user, s["id"], tok, sym, s.get("source_id"), s.get("kind"), s["decision"], tid, plan_id, s.get("sig_ts"),
                 row[0], row[1], row[2], "open"))
    con.commit()
    lcopy.wake()
    note_traded(s["id"], {"user": user, "trade_id": tid, "plan_id": plan_id, "size_sol": size, "mcap": mcap,
                          "live": bool(live), "ts": int(now)}, path)
    return (f"fast {s['decision']} {sym or tok[:6]} ({label}): {size:g} SOL na MC ${mcap or 0:,.0f}, izlaz pola +15 % / "
            f"trailing 8 % / stop -10 % / 45 min" + (" (pravi račun, pravi_novac_sve)" if switch else
                                                     " (pravi put kopije, run_trade dokaz)" if live else " (demo)")), None


def run_once(con, market_fn=None, now=None, path=None, sol=None, lim=None):
    """One pass: the copy exits and the closed rows of the open fast trades, then the entries. [(user, text)]."""
    now = int(now or time.time())
    done = []
    ensure(con)
    if con.execute("SELECT 1 FROM fast_trades WHERE status='open' LIMIT 1").fetchone():
        done += copy_exits(con, market_fn, now)
        sync_closed(con, path)
    m = mode()
    if m not in ("paper", "live"):
        return done
    sigs = [s for s in fresh(now, path) if s["id"] not in _TRIED]
    if not sigs:
        return done
    from league import copy as lcopy
    if lim is None:
        from rangedca import trade as rtrade
        lim = rtrade.limits(now)
    if sol is None:
        from rangedca import trade as rtrade
        sol = rtrade.sol_usd()
    if not sol:
        return done
    from trade import settings
    sw = settings.pravi_novac_sve()   # 14.11.: the owner's switch: every decision on the real account, no proof
    mk = (market_fn or lcopy.market)(sorted({s["token"] for s in sigs})) or {}
    for s in sigs:
        r = _route(s, m, sw)
        if r is None:
            continue
        user, live = r
        if live and s.get("follow_id") and con.execute(
                "SELECT 1 FROM copy_log WHERE follow_id=? AND token=? AND side='buy' AND action='ulaz'",
                (s["follow_id"], s["token"])).fetchone():
            _TRIED[s["id"]] = now
            note_traded(s["id"], {"user": user, "skip": "kopija istog praćenja je već ušla (copy loop)"}, path)
            continue
        if live and not sw:   # run_trade's own proof decides the real money; without the follow's proof: demo account
            try:
                proven = lcopy.proven(con, s["follow_id"], user)
            except Exception:  # noqa: BLE001 - unreadable proof: demo only
                proven = False
            if not proven:
                user, live = settings.PAPER_USER, False
        text, why = enter(con, s, user, live, mk.get(s["token"]), lim, sol, now, path,
                          switch=sw and user == settings.LEAGUE_USER)
        if text:
            done.append((user, text))
        elif why:
            _TRIED[s["id"]] = now
            note_traded(s["id"], {"user": user, "skip": why}, path)
            print(f"fast {s['token'][:6]}: {s['decision']} nije kupljen ({why})", flush=True)
    for k in [k for k, ts in _TRIED.items() if now - ts > 3600]:
        _TRIED.pop(k, None)
    return done


# ---------- exits ----------------------------------------------------------------------------------------------------------

def copy_exits(con, market_fn=None, now=None):
    """Sell every open lot of a fast trade whose source wallet sold the token at or after the buy we copied."""
    from league import copy as lcopy, store as lstore
    now = int(now or time.time())
    rows = con.execute("SELECT id, user, token, source_id, kind, sig_ts, trade_id, symbol FROM fast_trades WHERE "
                       "status='open'").fetchall()
    rows = [r for r in rows if r[4] in sources.WALLET_KINDS]
    if not rows:
        return []
    hc = lcopy._ro(lcopy._paths()["hype"])
    sold = {}
    try:
        for fid, _u, tok, w, _k, sig_ts, _tid, _sym in rows:
            r = lcopy._q(hc, "SELECT MIN(ts) FROM chain_trades WHERE wallet=? AND mint=? AND side='sell' AND ts >= ?",
                         (w, tok, int(sig_ts or 0)))
            if r and r[0][0]:
                sold[fid] = int(r[0][0])
    finally:
        if hc is not None:
            hc.close()
    if not sold:
        return []
    mk = (market_fn or lcopy.market)(sorted({r[2] for r in rows if r[0] in sold})) or {}
    done = []
    for fid, user, tok, w, _k, _sig_ts, tid, sym in rows:
        if fid not in sold:
            continue
        mq = mk.get(tok)
        if not mq or not mq[0]:
            continue   # no price this pass: the next one (every 20 s, sooner on a wake-up)
        price, liq, _url, mcap = mq[:4]
        t0 = con.execute("SELECT opened_ts, source FROM trades WHERE id=?", (tid,)).fetchone()
        lots = con.execute("SELECT id FROM trades WHERE user=? AND token=? AND status='open' AND opened_ts=? AND source=?",
                           (user, tok, t0[0], t0[1])).fetchall() if t0 else []
        pnl = 0.0
        for (lid,) in lots:
            pnl += lstore.sell(con, user, lid, price, liq, f"fast: izvor {w[:4]}… je prodao", mcap=mcap,
                               exit_rule="wallet_sold")
        con.execute("UPDATE fast_trades SET exit_reason=? WHERE id=?", ("izvor je prodao (copy exit)", fid))
        con.commit()
        if lots:
            done.append((user, f"fast copy exit {sym or tok[:6]}: izvor je prodao, i mi: {pnl:+.2f} $"))
    return done


def sync_closed(con, path=None):
    """Close the fast_trades rows whose lots are all sold: PnL = the sum of every closed row of that entry."""
    for fid, user, tok, tid, size, sid, why in con.execute(
            "SELECT id, user, token, trade_id, size_usd, signal_id, exit_reason FROM fast_trades WHERE status='open'"
    ).fetchall():
        t = con.execute("SELECT status, opened_ts, source, closed_ts, exit_rule FROM trades WHERE id=?", (tid,)).fetchone()
        if not t or t[0] != "closed":
            continue
        pnl = con.execute("SELECT COALESCE(SUM(pnl_usd), 0) FROM trades WHERE user=? AND token=? AND opened_ts=? AND "
                          "source=? AND status='closed'", (user, tok, t[1], t[2])).fetchone()[0] or 0.0
        ret = pnl / size if size else None
        con.execute("UPDATE fast_trades SET status='closed', closed_ts=?, pnl_usd=?, ret=?, exit_reason=? WHERE id=?",
                    (t[3], pnl, ret, why or t[4], fid))
        con.commit()
        note_traded(sid, {"user": user, "trade_id": tid, "closed": True, "pnl_usd": round(pnl, 2),
                          "ret_pct": round(ret * 100, 1) if ret is not None else None, "exit": why or t[4]}, path)
