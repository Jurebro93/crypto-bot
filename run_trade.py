#!/usr/bin/env python3
"""Real (or dry-run) buys and sells that follow the paper trader's decisions.

    python3 run_trade.py check                     # mode, wallet address, SOL balance, does Jupiter answer
    python3 run_trade.py follow                    # loop: every new paper entry -> buy, every paper exit -> sell
    python3 run_trade.py buy <mint> [--sol 0.05]   # one manual buy through the same risk gate
    python3 run_trade.py sell <mint> [--frac 0.5]  # sell part of an open position (default all)
    python3 run_trade.py status                    # positions and PnL in SOL

Two sources of decisions, both proven in demo first:
- the competition account "pravi-trade" (trade/settings.LEAGUE_USER): the owner picks KOLs and wallets to follow on
  /pravi-trade, league/copy.py enters and exits that demo account, and every entry/exit here becomes a real swap;
- the paper trader (run_paper.py), only when the owner ticks "prati i demo strategiju" on the page.
Limits: trade/config.json defaults, overridden on the page (trade/settings.py). Dry-run is the default; see
trade/executor.py for what turns on live trading. No Telegram (Nicholas's rule): everything shows on /pravi-trade.
"""
import argparse
import datetime as dt
import json
import os
import re
import signal
import sqlite3
import sys
import time

from trade import executor, jupiter, settings, wake, wallet

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "trade.db")  # own file, see run_hype.DB
PAPER_DB = os.path.join(HERE, "paper.db")
LEAGUE_DB = os.path.join(HERE, "league.db")
SELL_ALL_RETRY_S = 30
_sell_all_try = {"ts": 0}


def notify(text):
    """Only the server log: every buy and sell is also in trade.db and on /pravi-trade (no Telegram)."""
    print(f"trade: {text}", flush=True)


def load(path=None, con=None):
    cfg = executor.load_config(path)
    own = con is None
    con = con or settings.connect(DB)
    try:
        return settings.merged(cfg, con)
    finally:
        if own:
            con.close()


def _say(text, quiet=False):
    if not quiet:
        print(text)
    notify(text)


def _paper():
    if not os.path.exists(PAPER_DB):
        return None
    return sqlite3.connect(f"file:{PAPER_DB}?mode=ro", uri=True, timeout=10)


def follow_once(con, cfg, since, now=None, quiet=False):
    """One pass: buy paper entries opened after `since`, sell what paper sold since our last pass."""
    now = now or time.time()
    p = _paper()
    if p is None:
        return
    try:
        trades = p.execute("SELECT id, token, symbol, opened_ts, state, config FROM trades WHERE opened_ts>=?",
                           (since,)).fetchall()
        followed = {pid: (i, st, fd) for i, pid, st, fd in
                    con.execute("SELECT id, paper_id, status, fills_done FROM positions WHERE paper_id IS NOT NULL")}
        for pid, token, sym, opened, state, pcfg in trades:
            if pid in followed:
                continue
            tag = "LIVE" if executor.is_live(cfg) else "DRY"
            # demo-only learning trades (exploration, convergence until it proves itself): never real money
            if json.loads(pcfg or "{}").get("entry_mode") in ("explore", "konv"):
                con.execute("INSERT INTO positions (paper_id, token, symbol, opened_ts, mode, status, reason) "
                            "VALUES (?,?,?,?,?,?,?)", (pid, token, sym, int(now), tag.lower(), "blocked",
                                                       "istraživački / konvergencijski demo trade, ne kopira se"))
                con.commit()
                continue
            if now - opened > cfg["max_signal_age_s"]:
                con.execute("INSERT INTO positions (paper_id, token, symbol, opened_ts, mode, status, reason) "
                            "VALUES (?,?,?,?,?,?,?)", (pid, token, sym, int(now), tag.lower(), "blocked",
                                                       f"signal star {now - opened:.0f} s"))
                con.commit()
                continue
            r = executor.buy(con, cfg, token, sym, paper_id=pid, now=now, reason=f"paper #{pid}")
            if r["status"] == "open":
                _say(f"🟢 {tag} KUPNJA {sym}  {r['amount_in'] / executor.LAMPORTS:.3f} SOL, trošak {r['cost_pct']}%"
                     + (f"  https://solscan.io/tx/{r['signature']}" if r.get("signature") else ""), quiet)
            else:
                _say(f"⛔ {tag} kupnja {sym} nije prošla: {r.get('error')}", quiet)
        open_ids = ",".join(str(k) for k, v in followed.items() if v[1] == "open") or "NULL"
        for pid, token, sym, opened, state in p.execute(
                f"SELECT id, token, symbol, opened_ts, state FROM trades WHERE id IN ({open_ids})"):
            pos_id, _, done = followed[pid]
            st = json.loads(state)
            fills = st["fills"]
            for n, f in enumerate(fills[done:], start=done):
                last = not st["open"] and n == len(fills) - 1
                r = executor.sell(con, cfg, pos_id, f["frac"], close=last, now=now, reason=f["reason"])
                if r["status"] == "wait":
                    break   # an earlier try failed; backing off (executor._sell_wait)
                if r["status"] in ("ok", "dry", "noop"):
                    con.execute("UPDATE positions SET fills_done=? WHERE id=?", (n + 1, pos_id))
                    con.commit()
                    if r["status"] != "noop":
                        _say(f"🔴 {r.get('status').upper()} PRODAJA {sym} {f['frac']:.0%} ({f['reason']}) -> "
                             f"{r['amount_out'] / executor.LAMPORTS:.4f} SOL", quiet)
                else:
                    _say(f"⚠️ prodaja {sym} nije prošla ({f['reason']}): {r.get('error')}; pokušavam opet", quiet)
                    break  # retry this fill next pass, keep the order
    finally:
        p.close()


def _trigger_probe_once(con):
    """10.11. (Jure: "da, v1"): Jupiter Trigger step 1 when the page's button asked for it (settings
    "trigger_probe_req" newer than the last "trigger_probe"): one createOrder request for an open real position's TP,
    its answer recorded. Signs and sends nothing (trade/trigger.py)."""
    raw = settings.raw(con)
    req, done = raw.get("trigger_probe_req") or 0, (raw.get("trigger_probe") or {}).get("ts") or 0
    if not req or req <= done:
        return None
    from trade import equity, trigger
    autos = {}
    lg = _league()
    if lg is not None:
        try:
            for lid, a in lg.execute("SELECT id, auto FROM trades WHERE user=? AND status='open' AND auto IS NOT NULL",
                                     (settings.LEAGUE_USER,)):
                try:
                    autos[lid] = json.loads(a)
                except ValueError:
                    pass
        except sqlite3.Error:
            pass
        finally:
            lg.close()
    return trigger.probe(con, autos, wallet.address(), wallet.token_decimals,
                         lambda: (equity.rates() or {}).get("sol_usd"))


def _league():
    if not os.path.exists(LEAGUE_DB):
        return None
    return sqlite3.connect(f"file:{LEAGUE_DB}?mode=ro", uri=True, timeout=10)


MIN_MCAP_USD = 30_000   # CLAUDE.md: tokens under $30k are never bought; last line of defence behind league/copy.py
# 9.11. (audit P39): a follow needs this much demo proof before real money. 11.11. (owner's rule D, trade/edge): n >= 10
# closed demo trades, their mean result net of cost >= +3 % and the 90 % interval's lower bound > 0 (the old "PnL > 0
# and >= 40 % winners" is gone: 40 % is under break-even for TP +15 / SL -10)
PROOF = {"closed": 10, "ev_min": 0.03, "ci_lo_min": 0.0}
COPY_BOOK_WAIT_S = 5   # 9.11. (review novac): league/copy.py commits the demo trade a few ms before its follow_id and
                       # copy_log row; a copy read in that gap looks like a manual buy with a fresh signal
# 11.11.: the sources of the buys the page books itself (ui/pravitrade._post_buy: the owner's "ručno ...", Grok's
# "Grok auto (MCP)"): it commits the demo trade a few ms before manual_size / manual_override in trade.db, so such a
# trade read without its stake waits up to COPY_BOOK_WAIT_S instead of being mirrored as an automatic buy
PAGE_SOURCES = tuple(p.rstrip("%") for p in executor.OWN_REASONS)


def _grok_source(src):
    """True for a Grok buy (autotrade, or a Grok request the owner approved): its limits stay hard (no override)."""
    try:
        from league import exitplan
        from ui import grokauto
        return (src or "") in (grokauto.SRC, exitplan.APPROVED_SRC)
    except Exception:  # noqa: BLE001 - the two literal sources, should an import fail
        return (src or "") in ("Grok auto (MCP)", "ručno: Grok odobreno (MCP)")


REASON_MIN = 10   # = ui/pravitrade.REASON_MIN: the owner's typed reason of a buy under $30k MC, at least this long


def _override(cfg, t):
    """11.11. (owner: "ako se složim, ručno uvijek nadjačava sve ostalo"): (text, keys) of what the owner confirmed he
    overrides for this manual buy on the page (settings manual_override, written by ui/pravitrade._post_buy before
    manual_size): the text for executor.buy(override=...), the rule keys for the checks here (MIN_MCAP: "mc30k" with
    his reason). (None, set()) for a copy or a Grok buy, whatever the settings say."""
    src = t["source"] or ""
    if src.startswith("copy ") or _grok_source(src):
        return None, set()
    o = (cfg.get("manual_override") or {}).get(str(t["id"]))
    if not o:
        return None, set()
    o = o if isinstance(o, dict) else {}
    why = o.get("why") or []
    keys = {str(k) for k in (o.get("keys") or [])}
    if "mc30k" in keys and len(str(o.get("reason") or "").strip()) < REASON_MIN:
        keys.discard("mc30k")   # under $30k only with the owner's reason (the page never writes one without)
    return ("; ".join(str(w) for w in why)[:500] if why else "nadjačano"), keys


def _league_fresh(lg, since):
    """New open demo trades of the real-trade account, with the columns copy trading adds when they exist."""
    try:
        return lg.execute("SELECT id, token, symbol, opened_ts, source, entry_mcap, follow_id, auto FROM trades "
                          "WHERE user=? AND status='open' AND opened_ts>=?", (settings.LEAGUE_USER, since)).fetchall()
    except sqlite3.OperationalError:
        rows = lg.execute("SELECT id, token, symbol, opened_ts, source, NULL entry_mcap, NULL follow_id, NULL auto "
                          "FROM trades WHERE user=? AND status='open' AND opened_ts>=?",
                          (settings.LEAGUE_USER, since)).fetchall()
        return rows


def _call_ts(lg, trade_id):
    """9.11. (audit P30/P31/P32): when the call itself was posted (copy_log.ev_ts of the entry), or None."""
    try:
        r = lg.execute("SELECT ev_ts FROM copy_log WHERE trade_id=? AND side='buy' AND action='ulaz'", (trade_id,)).fetchone()
    except sqlite3.OperationalError:
        return None
    return r[0] if r and r[0] else None


def _tp_pct(auto_json, default):
    """The exit target of the demo trade in percent ("+100%" of a TP/SL rule); the page default for anything else."""
    try:
        a = json.loads(auto_json or "null") or {}
    except ValueError:
        return default
    m = re.fullmatch(r"\+?([0-9.]+)%", (a.get("tp") or "").strip()) if a.get("mode") == "tpsl" else None
    return float(m.group(1)) if m else default


def _no_proof(lg, follow_id):
    """9.11. (audit P39, CLAUDE.md "dry dok strategija ne dokaže edge u demu"): the reason this follow has not earned
    real money yet, or None. Only consulted when live (dry mirrors collect real quotes for exactly this proof)."""
    if follow_id is None:   # 9.11. (review novac): a copy whose follow was never booked has no proof to look up
        return "kopija bez zapisa praćenja (follow_id); bez dokaza u demu ne ide u pravi novac"
    from trade import edge
    try:
        from league import copy as lcopy
        r = lcopy.follow_results(lg).get(follow_id)
    except Exception:  # noqa: BLE001 - no copy tables: no proof
        r = None
    rets = list((r or {}).get("rets") or [])
    ok, why, s = edge.live_proof(rets, n_min=PROOF["closed"], ev_min=PROOF["ev_min"])
    if not ok:
        return (f"praćenje bez dokaza u demu ({edge.proof_text(s)}: {why}; treba {PROOF['closed']}+ zatvorenih, "
                f"EV >= {PROOF['ev_min']:+.0%} i donja granica 90 % intervala > 0)")
    return None


RUNUP_LIMIT = 0.10   # 10.11. (Grok MCP audit 3) = league/copy.RUNUP_DEFAULT: the real buy pays at most the call + 10 %


def _call_limit(lg, t):
    """10.11. (Grok MCP audit 3, flag runup_default, live only): (why, limit) of a KOL / crew copy's real buy.
    The demo entry already skipped a token more than 10 % above its first call (league/copy._runup_gate); the real
    swap is quoted a moment later and may pay more, so the order itself is held to the same line: limit
    {"max_px", "call_px"} in USD per token for trade/executor (the call's price = the demo entry / (1 + its run-up)).
    A run-up the demo trade does not know is a skip. (None, None) when the flag does not apply: the old behaviour.
    In shadow / paper nothing is logged here: the demo gate logs the same decision (and run_trade never writes
    league.db, whose only writer is the dashboard process)."""
    src = t["source"] or ""
    if not (src.startswith("copy KOL ") or src.startswith("copy ekipa ")):
        return None, None
    try:
        from league import flags
        m = flags.mode("runup_default")
        if m == "off" or not flags.applies("runup_default", settings.LEAGUE_USER, m):
            return None, None
    except Exception:  # noqa: BLE001 - an unreadable flag is off
        return None, None
    try:
        r = lg.execute("SELECT entry_px, runup FROM trades WHERE id=?", (t["id"],)).fetchone()
    except sqlite3.OperationalError:   # league.db without the 10.11. columns
        r = None
    if not r or r[1] is None or not r[0] or r[1] <= -1:
        return "limit cijene poziva: run-up od prvog poziva nepoznat, bez njega se ne kupuje", None
    call_px = r[0] / (1 + r[1])
    return None, {"max_px": call_px * (1 + RUNUP_LIMIT), "call_px": call_px}


def _range_lot(con, lg, t, cfg):
    """10.11. (Jure, flag range_dca): (why, size_sol, add) of a range lot's real buy. The stake is the demo lot's (its
    USD at today's SOL price, never above size_sol: lot 2 may be smaller under the dca cap); lot 2 is one more lot of
    lot 1's real position (add) and only while that one is open, else it is skipped (a lot 2 must never land on a
    position the strategy does not own, e.g. the owner's own lots). Every other limit holds (manual stays False)."""
    try:
        size_usd = lg.execute("SELECT size_usd FROM trades WHERE id=?", (t["id"],)).fetchone()[0]
        from trade import equity
        sol_usd = (equity.rates() or {}).get("sol_usd")
        sol = min(float(cfg["size_sol"]), size_usd / sol_usd) if size_usd and sol_usd else None
    except Exception:  # noqa: BLE001 - unknown: the default stake
        sol = None
    if not (t["source"] or "").startswith("range lot 2"):
        return None, sol, False
    try:
        r = lg.execute("SELECT lot1_id FROM range_rounds WHERE lot2_id=?", (t["id"],)).fetchone()
    except sqlite3.OperationalError:
        r = None
    lot1 = con.execute("SELECT 1 FROM positions WHERE league_id=? AND status IN ('open','pending')",
                       (r[0],)).fetchone() if r else None
    if not lot1:
        return "range lot 2 bez pravog lota 1 (nije kupljen ili je već prodan)", None, False
    return None, sol, True


def _momentum_gate():
    """11.11. (flag momentum_scalp): the live gate again before a momentum trade becomes a real swap (momentum/gate.py:
    >= 50 closed paper trades, EV > 0, hit rate >= 45 %). An unreadable proof refuses."""
    try:
        from momentum import gate
        return gate.refusal(cached=True)
    except Exception as e:  # noqa: BLE001 - no proof, no real money
        return f"momentum_scalp: dokaz se ne može pročitati ({type(e).__name__})"


# 14.11. (owner: "Ja sada ne govorim o demu ... idemo s pravim novcem"; trade/settings "pravi_novac_sve"): while his
# switch is on, every automatic demo trade of the real account is a real buy without the demo proof (PROOF, the
# momentum gate), within trade/executor.SWITCH_CAPS. The hard rules are asked once more right here, on the real buy
# itself (they hold switch or not in the strategies; here they hold whatever a strategy did): the rug archive, a known
# MC of $30k+, a live DexScreener pair (bonded only, never the pump.fun curve) with liquidity $15k+ and no rug, and a
# server-side stop behind the position (an exit plan that executes on the real account, the lot's own SL, or the
# strategy's own exit engine: momentum, range). The kill switch, the wallet balance and reserve, the swap cost cap and
# one real position per token are trade/executor's (buy_checks, swap), as for every buy.
SWITCH_STOP_WAIT_S = 10    # a stop the strategy writes right after its demo buy (momentum, range): wait for it this long
SWITCH_QUOTE_WAIT_S = 20   # DexScreener did not answer: try again on the next passes for this long, then refuse
SWITCH_SUMMARY_S = 600     # the switch's day summary in the log this often while it is on
_switch_log = {"ts": 0.0, "day": None}


def _switch_market(tokens):
    """The live quote of the hard re-check (league/copy.market: DexScreener's 3-s live cache, Jupiter for the curve)."""
    from league import copy as lcopy
    return lcopy.market(tokens)


def _no_stop(lg, t):
    """None when the demo lot behind this real buy has a server-side stop, else why not (Croatian)."""
    try:
        a = json.loads(t["auto"] or "null") or {}
    except (ValueError, TypeError):
        a = {}
    if a.get("mode") == "smart" or (a.get("mode") == "tpsl" and a.get("sl_px")):
        return None   # league/auto runs the lot's own stop every second
    try:
        from league import exitplan
        p = exitplan.active(lg, t["token"], ro=True)
        if p and settings.LEAGUE_USER in exitplan._scope(p["plan"]) \
                and (p["state"].get("stop_px") or {}).get(settings.LEAGUE_USER):
            lots = [dict(r) for r in lg.execute("SELECT * FROM trades WHERE user=? AND token=? AND status='open'",
                                                (settings.LEAGUE_USER, t["token"]))]
            if exitplan.execution(settings.LEAGUE_USER, lots, plan=p)["executes"]:
                return None
    except Exception:  # noqa: BLE001 - an unreadable plan is no plan
        pass
    src = t["source"] or ""
    try:
        if src.startswith("momentum") and lg.execute("SELECT 1 FROM momentum_trades WHERE trade_id=? AND status='open'",
                                                     (t["id"],)).fetchone():
            return None   # momentum/trade.exits_once: stop -10 % every second
        if src.startswith("range lot") and lg.execute("SELECT 1 FROM range_rounds WHERE status='open' AND (lot1_id=? OR "
                                                      "lot2_id=?)", (t["id"], t["id"])).fetchone():
            return None   # rangedca/trade.exits_once: the round's hard stop every second
    except sqlite3.Error:
        pass
    return "bez server-side stopa (plan izlaza na pravom računu, vlastiti SL ili izlaz strategije): bez stopa nema pravog novca"


def _switch_hard(lg, t, now, market_fn=None):
    """(why or None, wait) of the hard rules on an automatic real buy under pravi_novac_sve (see above). wait: not yet
    decided (a stop or a quote that is still coming), the next pass asks again."""
    tok, src = t["token"], t["source"] or ""
    if _grok_source(src) or src.startswith("Grok auto"):
        return "Grokova kupnja ide samo njegovim putem (vlastiti prekidač i limiti), nikad kroz pravi_novac_sve", False
    try:
        from rugfilter import archive
        if tok in archive.blocked():
            return "token je u arhivi rugova: ne trguje se i ne naoružava", False
    except Exception:  # noqa: BLE001 - unreadable archive: the rug check below and the strategies' guards decide
        pass
    if t["entry_mcap"] is None:
        return "MC nepoznat: automatska kupnja pravim novcem samo uz poznat MC od 30k naviše", False
    m = ((market_fn or _switch_market)([tok]) or {}).get(tok)
    if not m or not m[0]:
        return "nema žive cijene (DexScreener): ne kupujem naslijepo", now - t["opened_ts"] < SWITCH_QUOTE_WAIT_S
    from league import copy as lcopy
    from trade import cost
    if lcopy._bonding_curve(m) or lcopy._dex_pair_empty(m):
        return "token je na pump.fun krivulji ili bez DexScreener para: kupuju se samo bondani", False
    if (m[3] or 0) < MIN_MCAP_USD:
        return f"MC ${m[3] or 0:,.0f} ispod 30k (pravilo: ispod 30k se ne kupuje)", False
    why = cost.liq_block(m[1])
    if why:
        return why, False
    col = lcopy._rugged(tok, m[3], m[1])
    if col:
        return f"token je rugan ({col['text']})", False
    why = _no_stop(lg, t)
    if why:
        return why, now - t["opened_ts"] < SWITCH_STOP_WAIT_S
    return None, False


def _switch_summary(con, cfg, now=None, force=False):
    """14.11.: the switch's day summary line (executor.switch_line) every SWITCH_SUMMARY_S while it is on, and the last
    one of a Zagreb day when the next starts. Never raises."""
    now = now or time.time()
    try:
        day = executor._day_start(now, cfg.get("day_tz"))
        if _switch_log["day"] is not None and day != _switch_log["day"]:
            print(f"pravi trade: kraj dana, {executor.switch_line(executor.switch_status(con, day - 1, cfg))}", flush=True)
        _switch_log["day"] = day
        if force or now - _switch_log["ts"] >= SWITCH_SUMMARY_S:
            _switch_log["ts"] = now
            print(f"pravi trade: {executor.switch_line(executor.switch_status(con, now, cfg))}", flush=True)
    except Exception as e:  # noqa: BLE001 - a log line never stops the loop
        print(f"pravi trade: sažetak pravi_novac_sve nije ispisan: {type(e).__name__}: {e}", flush=True)


def _mirrored(con, league_id):
    """10.11. (Jure: "sekundni poslovi ne smiju čitati cijelu bazu svake sekunde"): has this demo trade its
    positions row already? One lookup through the index on league_id (trade/aplog.INDEXES) per fresh demo trade; the
    loop used to read every league_id in the table on every 1-second pass to answer the same question."""
    return con.execute("SELECT 1 FROM positions WHERE league_id=? LIMIT 1", (league_id,)).fetchone() is not None


def _exit_recon_once(con, now=None):
    """Plan 1.5: the real exit next to the demo's for positions closed in the last 15 min (executor.exit_reconcile).
    One getTokenSupply per newly closed token and the SOL price trade/equity already keeps; never raises."""
    lg = None
    try:
        lg = _league()
        if lg is None:
            return 0
        from trade import equity
        return executor.exit_reconcile(con, lg, equity._decimals, lambda: (equity.rates() or {}).get("sol_usd"),
                                       now=now)
    except Exception as e:  # noqa: BLE001 - a statistic never stops the trade loop
        print(f"trade: usporedba izlaza: {type(e).__name__}: {e}", flush=True)
        return 0
    finally:
        if lg is not None:
            lg.close()


EXIT_EVENT_MAX_AGE_S = 300   # 13.11.: an exit plan's trigger this recent is the reason of a demo sale run_trade mirrors


def _exit_trigger(con, lg, pos_id, token, now):
    """13.11. (owner's order point 2): the exit plan's trigger behind a demo sale of the real account (league.db
    exit_events: newest executed sale of the token on LEAGUE_USER within EXIT_EVENT_MAX_AGE_S, written by
    league/exitplan.run_once) that this position has not measured yet (exit_fills), as a dict; None otherwise (a
    manual sale, the lot's own TP/SL, an older database without the table)."""
    try:
        r = lg.execute("SELECT * FROM exit_events WHERE token=? AND user=? AND mode='izvršeno' AND share > 0 "
                       "AND ts >= ? ORDER BY id DESC LIMIT 1",
                       (token, settings.LEAGUE_USER, int(now) - EXIT_EVENT_MAX_AGE_S)).fetchone()
    except sqlite3.Error:
        return None
    if r is None:
        return None
    ev = dict(r) if hasattr(r, "keys") else None
    if not ev:
        return None
    try:
        if con.execute("SELECT 1 FROM exit_fills WHERE event_id=? AND position_id=?", (ev["id"], pos_id)).fetchone():
            return None
    except sqlite3.Error:
        return None
    return ev


def _first_try(con, pos_id, ev):
    """True while no sell of this position was tried since the trigger: only the first try gets the protective
    slippage (a retry after a failure goes straight with Jupiter's own slippage)."""
    t0 = int(ev.get("trig_ts") or ev.get("ts") or 0) - 1
    return con.execute("SELECT 1 FROM orders WHERE position_id=? AND side='sell' AND ts>=? LIMIT 1",
                       (pos_id, t0)).fetchone() is None


def _exit_px_inputs(token, live):
    """(SOL/USD, the token's decimals) for the fill price of an exit, without waiting on the network for the SOL
    price (trade/equity.sol_usd_cached). Decimals: pump.fun mints have 6, otherwise the process' cache, and on a live
    sale one RPC (after the swap, so it delays no sale). Unknown parts are None (the fill is then not priced)."""
    from trade import equity
    sol = equity.sol_usd_cached()
    dec = 6 if token.endswith("pump") else equity._DEC.get(token)
    if dec is None and live:
        try:
            dec = equity._decimals(token)
        except Exception:  # noqa: BLE001 - RPC down: the fill stays unpriced, the sale itself is done
            dec = None
    return sol, dec


def _mc(px, ratio):
    if px is None:
        return "?"
    return f"MC ${px * ratio:,.0f}" if ratio else f"${px:.6g}"


def _exit_fill(con, pos_id, sym, token, ev, r, live, quiet=False):
    """13.11. (owner's order point 2: "Provjeri zašto nastaje toliki zaostatak"): one exit_fills row and one log line
    per real sale behind an exit plan's trigger: the trigger's level and the price the executor saw (and from which
    feed, how old), how long after the trigger the order went out and its answer came, the fill in USD per token
    (SOL out x SOL/USD over the tokens sold) and the slip against the level and against the price seen, and the
    protective slippage try. Never raises (a measurement never stops the trade loop)."""
    try:
        sol, dec = _exit_px_inputs(token, live)
        fill = None
        if sol and dec is not None and r.get("amount_in") and r.get("amount_out"):
            fill = (r["amount_out"] / executor.LAMPORTS) * sol / (r["amount_in"] / 10 ** int(dec))
        level, seen = ev.get("level_px"), ev.get("price")
        ratio = ev["mcap"] / ev["price"] if ev.get("mcap") and ev.get("price") else None
        t0 = ev.get("trig_ts") or ev.get("ts")
        sent = r["t_sent"] - t0 if r.get("t_sent") and t0 else None
        lat = r["t_done"] - t0 if r.get("t_done") and t0 else None
        sl_lvl = (fill / level - 1) * 100 if fill and level else None
        sl_seen = (fill / seen - 1) * 100 if fill and seen else None
        cap = r.get("slip_cap") or {}
        con.execute("INSERT INTO exit_fills (ts, position_id, event_id, plan_id, token, symbol, trigger, level_px, "
                    "seen_px, mc_ratio, px_src, px_age_s, trigger_ts, sent_ts, done_ts, fill_px, slip_level_pct, "
                    "slip_seen_pct, sent_after_s, latency_s, cap_pct, cap_result, status, signature, mode) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (int(time.time()), pos_id, ev.get("id"), ev.get("plan_id"), token, sym, ev.get("trigger"), level,
                     seen, ratio, ev.get("px_src"), ev.get("px_age_s"), t0, r.get("t_sent"), r.get("t_done"), fill,
                     sl_lvl, sl_seen, sent, lat, cap.get("cap_pct"), cap.get("result"), r.get("status"),
                     r.get("signature"), "live" if live else "dry"))
        con.commit()

        def pct(v):
            return f"{v:+.1f} %" if v is not None else "?"

        def sec(v):
            return f"+{v:.2f} s" if v is not None else "?"
        src = ev.get("px_src") or "?"
        age = f", {ev['px_age_s']:.0f} s" if ev.get("px_age_s") is not None else ""
        text = (f"izlaz {sym or token[:6]} {ev.get('trigger')} (plan #{ev.get('plan_id')}): "
                f"razina {_mc(level, ratio)}, viđeno {_mc(seen, ratio)} ({src}{age}), nalog {sec(sent)} nakon "
                f"okidača, ispunjeno {_mc(fill, ratio)} ({pct(sl_lvl)} od razine, {pct(sl_seen)} od viđenog), gotovo "
                f"{sec(lat)}"
                + (f"; zaštitni slippage {cap['cap_pct']:g} %: {cap.get('result')}" if cap.get("cap_pct") else ""))
        _say(text, quiet)
    except Exception as e:  # noqa: BLE001
        print(f"trade: mjerenje izlaza {sym or token[:6]}: {type(e).__name__}: {e}", flush=True)


def _league_sells(con, cfg, lg, now, quiet=False):
    """The real positions that mirror the real-trade account's demo trades: a closed demo trade -> sell everything,
    a demo trade sold in part -> sell the same share (the share still held, qty / bought qty, is the share kept).
    13.11. (owner's order point 2): run FIRST in every pass, so a stop never waits behind a buy; a sale behind an exit
    plan's trigger is sent with the protective slippage on its first try (executor.exit_cap_pct, live positions only;
    a failed try falls back to the normal swap at once) and measured (_exit_fill). Returns how many sells were tried."""
    tried = 0
    for pos_id, lid, qty_raw, qty_left, sym, token, mode in con.execute(
            "SELECT id, league_id, qty_raw, qty_left, symbol, token, mode FROM positions WHERE status='open' "
            "AND league_id IS NOT NULL").fetchall():
        d = lg.execute("SELECT status, size_usd, entry_eff, qty, note FROM trades WHERE id=?", (lid,)).fetchone()
        if d is None:
            continue
        if d["status"] == "closed":
            frac, close, why = 1.0, True, d["note"] or "demo izlaz"
        else:
            bought = d["size_usd"] / d["entry_eff"] if d["entry_eff"] else 0
            keep = min(1.0, d["qty"] / bought) if bought else 1.0
            have_frac = qty_left / qty_raw if qty_raw else 0
            if have_frac - keep < 0.05:
                continue
            frac, close, why = have_frac - keep, False, "djelomična prodaja (demo)"
        live = mode == "live"
        ev = _exit_trigger(con, lg, pos_id, token, now)
        cap = executor.exit_cap_pct(cfg) if ev and live and _first_try(con, pos_id, ev) else None
        kw = {"slip_cap_pct": cap} if cap else {}
        r = executor.sell(con, cfg, pos_id, frac, close=close, now=now, reason=why, **kw)
        tried += 1
        if r["status"] in ("ok", "dry"):
            _say(f"{r['status'].upper()} PRODAJA {sym} -> {r['amount_out'] / executor.LAMPORTS:.4f} SOL", quiet)
            if ev:
                _exit_fill(con, pos_id, sym, token, ev, r, live, quiet)
        elif r["status"] not in ("noop", "wait"):
            _say(f"prodaja {sym} nije prošla: {r.get('error')}; pokušavam opet", quiet)
    return tried


def follow_league_once(con, cfg, since, now=None, quiet=False):
    """Mirror the competition account "pravi-trade": its new open trades -> buys, its (partial) exits -> sells.
    The share still held in the demo trade (qty / bought qty) is the share kept of the real position.
    13.11. (owner's order point 2): the sells go FIRST (_league_sells), and once more after the buys when a buy was
    tried (a swap can take seconds; an exit that fired meanwhile does not wait for the next pass)."""
    now = now or time.time()
    lg = _league()
    if lg is None:
        return
    try:
        lg.row_factory = sqlite3.Row
        try:
            fresh = _league_fresh(lg, since)
        except sqlite3.OperationalError:
            return   # no competition tables yet
        _league_sells(con, cfg, lg, now, quiet)
        bought = 0
        live = executor.is_live(cfg)
        tag = "LIVE" if live else "DRY"
        sw = live and settings.pravi_novac_sve(con=con)   # 14.11.: the owner's switch, read once per pass
        for t in fresh:
            if _mirrored(con, t["id"]):
                continue
            size = (cfg.get("manual_size") or {}).get(str(t["id"]))   # "Kupi ručno" on the page sets its own stake
            is_copy = (t["source"] or "").startswith("copy ")   # league/copy.py: "copy KOL x" / "copy wallet x" / "copy ekipa x"
            call_ts = _call_ts(lg, t["id"])
            if is_copy and (t["follow_id"] is None or call_ts is None) and now - t["opened_ts"] < COPY_BOOK_WAIT_S:
                continue   # 9.11. (review novac): the copy loop is still booking follow_id / copy_log: next tick (`since` is fixed)
            if not size and not is_copy and (t["source"] or "").startswith(PAGE_SOURCES) \
                    and now - t["opened_ts"] < COPY_BOOK_WAIT_S:
                continue   # 11.11.: the page is still writing its stake (and an override): next tick
            # 11.11. (owner: "ručno uvijek nadjačava sve ostalo"): the owner's own buy he confirmed over his limits
            ov, ov_keys = _override(cfg, t) if size and not is_copy else (None, set())
            # 9.11. (audit P30/P31/P32): "fresh" is measured from the CALL (copy_log.ev_ts) when the copy loop wrote
            # it, not from the demo entry; the demo may legally enter up to max_delay_min after the post
            t0 = min(t["opened_ts"], call_ts or t["opened_ts"])
            why = None
            if now - t0 > cfg["max_signal_age_s"]:
                why = f"signal star {now - t0:.0f} s"
            elif t["entry_mcap"] is not None and t["entry_mcap"] < MIN_MCAP_USD \
                    and not (ov and "mc30k" in ov_keys and "mc30k" not in executor.HARD_RULES):
                # known bad only (P1/P7). 11.11. (owner: "Mogu se kupovati tokeni ispod 30.000 market capa uz dovoljno
                # dobar razlog"): only his own manual buy he confirmed with a reason passes; copies, Grok, automatics never
                why = f"MC ${t['entry_mcap']:,.0f} ispod 30k (pravilo: ispod 30k se ne kupuje)"
            elif live and not size and (t["follow_id"] is not None or is_copy) and not sw:   # a copy never passes as
                why = _no_proof(lg, t["follow_id"])   # "manual"; 14.11.: pravi_novac_sve buys without the demo proof
            limit = None
            if not why and is_copy:   # 10.11. (Grok MCP audit 3): flag runup_default, live: limit at the call + 10 %
                why, limit = _call_limit(lg, t)
            rng_sol, rng_add = None, False
            if not why and (t["source"] or "").startswith("range lot "):   # 10.11. (Jure, flag range_dca)
                why, rng_sol, rng_add = _range_lot(con, lg, t, cfg)
            if not why and (t["source"] or "").startswith("momentum") and not sw:   # 11.11. (flag momentum_scalp)
                why = _momentum_gate()
            auto_sw = sw and not size   # 14.11.: an automatic real buy under pravi_novac_sve (the owner's own: as before)
            strat = executor.strategy_of(t["source"])
            if not why and auto_sw:
                why, wait = _switch_hard(lg, t, now)
                if why and wait:
                    continue   # its stop / quote is still being written: the next pass asks again (`since` is fixed)
                if why:
                    _say(f"PRAVI NOVAC: {strat} {t['symbol'] or t['token'][:6]} odbijeno (tvrdo pravilo): {why}", quiet)
            if why:
                con.execute("INSERT INTO positions (league_id, token, symbol, opened_ts, mode, status, reason) "
                            "VALUES (?,?,?,?,?,?,?)", (t["id"], t["token"], t["symbol"], int(now), tag.lower(), "blocked", why))
                con.commit()
                # 9.11. (Jure: "samo jedan trade izvršen, zašto?"): the reason used to be only in the positions table
                _say(f"{tag} PRESKOČENO {t['symbol'] or t['token'][:6]} ({t['source'] or 'copy'}): {why}", quiet)
                continue
            # 10.11. (Jure: "ako unesem adresu tokena koji je već u poziciji, pozicija se podeblja"): the owner's manual
            # buy (its own stake, never a copy) may add one more lot to a token already held; a copy never doubles one
            kw = {"limit": limit} if limit is not None else {}
            bought += 1
            r = executor.buy(con, cfg, t["token"], t["symbol"], now=now, reason=t["source"] or "copy",
                             league_id=t["id"], size_sol=float(size) if size else rng_sol,
                             tp_pct=_tp_pct(t["auto"], cfg.get("tp_default") or 15),   # 15: the page default (ui/pravitrade)
                             add=(bool(size) and not is_copy) or rng_add,
                             manual=bool(size) and not is_copy,   # 10.11. (Jure: "makni limit"): no day spend limit
                             override=ov, **kw)   # 11.11.: only the SOFT limits; kill switch and balance still hold
            if r["status"] == "open":
                over = "; ".join(r.get("overridden") or []) or ov
                _say(f"{tag} KUPNJA {t['symbol']} {r['amount_in'] / executor.LAMPORTS:.3f} SOL ({t['source']})"
                     + (f" uz potvrđeno nadjačavanje: {over}" if ov else ""), quiet)
                if auto_sw and r.get("mode") == "live":   # 14.11.: one line per automatic real buy, then the day so far
                    c = r.get("cost_pct")
                    c_txt = f"{c:.1f}" if isinstance(c, (int, float)) else "?"
                    _say(f"PRAVI NOVAC: {strat} kupuje {t['symbol'] or t['token'][:6]} "
                         f"{r['amount_in'] / executor.LAMPORTS:.3f} SOL (procjena troška {c_txt} %)", quiet)
                    _switch_summary(con, cfg, now, force=True)
            else:
                _say(f"{tag} kupnja {t['symbol']} nije prošla: {r.get('error')}", quiet)
                if auto_sw:   # a cap's refusal names the cap (executor.buy_checks: "strop pravi_novac_sve <cap>")
                    _say(f"PRAVI NOVAC: {strat} {t['symbol'] or t['token'][:6]} odbijeno: {r.get('error')}", quiet)
        if bought:   # 13.11.: an exit that fired while the buys were in flight
            _league_sells(con, cfg, lg, max(now, time.time()), quiet)
    finally:
        lg.close()


def sell_requests_once(con, cfg, now=None, quiet=False):
    """The page's "Prodaj 50%" / "Prodaj sve" buttons on one position: {position id: share}; done ones are removed."""
    now = now or time.time()
    req = dict(cfg.get("sell_req") or {})
    if not req:
        return
    for pid, frac in list(req.items()):
        row = con.execute("SELECT status FROM positions WHERE id=?", (int(pid),)).fetchone()
        if not row or row[0] != "open":
            req.pop(pid)
            continue
        frac = float(frac)
        r = executor.sell(con, cfg, int(pid), frac, close=frac >= 0.999, now=now, reason="ručna prodaja (gumb)")
        if r["status"] in ("ok", "dry", "noop"):
            req.pop(pid)
            _say(f"ručna prodaja #{pid} {frac:.0%}: {r['status']}", quiet)
        elif r["status"] != "wait":
            _say(f"ručna prodaja #{pid} nije prošla: {r.get('error')}; pokušavam opet", quiet)
    done = set(cfg.get("sell_req") or {}) - set(req)
    if done:   # re-read so a button pressed during this pass is not lost
        cur = dict(settings.raw(con).get("sell_req") or {})
        settings.put(con, "sell_req", {k: v for k, v in cur.items() if k not in done}, "bot")


def sell_all_once(con, cfg, now=None, quiet=False):
    """The page's "Prodaj sve" button: every open position (real and probe) is sold; retried every 30 s until none
    is left, then the request is cleared."""
    now = now or time.time()
    if not cfg.get("sell_all") or now - _sell_all_try["ts"] < SELL_ALL_RETRY_S:
        return
    _sell_all_try["ts"] = now
    for (pid,) in con.execute("SELECT id FROM positions WHERE status='open'").fetchall():
        r = executor.sell(con, cfg, pid, close=True, now=now, reason="prodaj sve (gumb)")
        if r["status"] not in ("ok", "dry", "noop", "wait"):
            _say(f"prodaj sve: pozicija #{pid} nije prodana: {r.get('error')}", quiet)
    if not con.execute("SELECT 1 FROM positions WHERE status='open'").fetchone():
        settings.put(con, "sell_all", 0, "bot")


STOPPING = {"flag": False}


def _on_term(signum, frame):
    """9.11. (audit P11): a deploy or the watchdog sends SIGTERM; the loop finishes the pass it is in (a swap and
    its bookkeeping) and exits at the top of the next one instead of dying mid-swap."""
    STOPPING["flag"] = True
    print("pravi trade: SIGTERM, završavam tekući prolaz pa izlazim", flush=True)


def _start_equity():
    """10.11. (Jure: graf vrijednosti walleta kroz vrijeme): the wallet is measured every 5 min by trade/equity.py in
    its own daemon thread with its own connection, so this loop never waits for the RPC, a price or the exchange
    rate. Whatever goes wrong there is one log line; the trading goes on without the chart."""
    try:
        from trade import equity
        equity.start(DB)
    except Exception as e:  # noqa: BLE001
        print(f"equity: snimanje vrijednosti walleta nije pokrenuto ({type(e).__name__}: {e})", flush=True)


def _stop_equity():
    """10.11. (review novac): on the way out (SIGTERM from a deploy) the snapshot thread is told to stop and given
    2 s to finish a write; Render's grace period is for the swap this loop may be finishing, not for the chart."""
    try:
        from trade import equity
        equity.stop(timeout=2)
    except Exception:  # noqa: BLE001 - exiting anyway
        pass


def cmd_follow(a):
    cfg = load(a.config)
    since = time.time() - cfg["max_signal_age_s"]
    print(f"Pratim račun {settings.LEAGUE_USER} (i paper.db ako je uključeno), mod "
          f"{'LIVE' if executor.is_live(cfg) else 'DRY-RUN'}, wallet {wallet.address()}")
    try:
        signal.signal(signal.SIGTERM, _on_term)
    except (ValueError, OSError):   # not the main thread (tests): no handler, the loop still works
        pass
    if not a.once:   # one pass (cron, a check by hand) measures nothing: the snapshots belong to the loop that stays
        _start_equity()
    beat = {"ts": 0, "live": None}
    while not STOPPING["flag"]:
        rung = wake.stamp()   # 13.11.: an exit rung during this pass starts the next one at once (wake.nap below)
        try:
            con = executor.connect(DB)
            cfg = load(a.config, con)
            live_now = executor.is_live(cfg)
            if live_now != beat["live"]:   # 9.11.: the mode is visible in the log every time it changes, not only at start
                # 9.11. (audit P37): config.json "mode" is informative only; what decides is the switch + env + key
                print(f"pravi trade: mod {'LIVE' if live_now else 'DRY-RUN'} (prekidač {'uključen' if cfg.get('on') else 'isključen'}, "
                      f"TRADE_LIVE={os.environ.get('TRADE_LIVE', '')!r}, ključ {'da' if wallet.can_sign() else 'ne'}, "
                      f"config mode={cfg.get('mode', '?')!r} samo kao napomena)", flush=True)
                try:   # 11.11. (Jure: "pokaži iz loga da su Grokovi limiti nepromijenjeni"): the limits in force
                    print(f"pravi trade: {limits_line(con, cfg)}", flush=True)
                except Exception as e:  # noqa: BLE001 - a log line never stops the loop
                    print(f"pravi trade: limiti nisu ispisani: {type(e).__name__}: {e}", flush=True)
                beat["live"] = live_now
            sw_now = settings.pravi_novac_sve(con=con)   # 14.11.: the owner's switch, in the log when it changes
            if sw_now != beat.get("sw"):
                if sw_now or beat.get("sw") is not None:
                    print(f"pravi trade: prekidač pravi_novac_sve {'UKLJUČEN' if sw_now else 'isključen'}"
                          + (f" ({'radi: mod LIVE' if live_now else 'čeka mod LIVE: Autopilot, TRADE_LIVE i ključ'}); "
                             f"{switch_caps_text(cfg)}" if sw_now else "; pravi novac opet samo s dokazom u demu"),
                          flush=True)
                beat["sw"] = sw_now
                if sw_now:
                    _switch_summary(con, cfg, force=True)
            elif sw_now:
                _switch_summary(con, cfg)
            if time.time() - beat["ts"] >= 60:   # the page shows "trade proces ne radi" when this gets old
                settings.put(con, "heartbeat", int(time.time()), "bot")
                beat["ts"] = time.time()
            # 13.11. (owner's order point 2): the Autopilot's mirror FIRST, and in it its exits first: a stop or a
            # trailing that just sold the demo lot goes out before anything else this pass does
            follow_league_once(con, cfg, since)
            _trigger_probe_once(con)          # 10.11.: Jupiter Trigger step 1, only when the owner asked (no money)
            executor.reconcile_pending(con)   # buys a crash left half-booked, matched with the wallet
            sell_all_once(con, cfg)
            sell_requests_once(con, cfg)
            if cfg.get("follow_paper"):
                follow_once(con, cfg, since)
            _exit_recon_once(con)             # 10.11. (plan 1.5): demo vs real exit price of positions just closed
            con.close()
        except Exception as e:
            print(f"greška: {type(e).__name__}: {e}", file=sys.stderr)
            try:   # 10.11. (Jure): the same error with its stack, in Sentry (the log line has only the text)
                from ops import sentry
                sentry.capture(e, where="run_trade.cmd_follow")
            except Exception:  # noqa: BLE001 - the reporter must never stop the trade loop
                pass
        if a.once or STOPPING["flag"]:
            break
        # 13.11. (owner's order point 2): poll_s at most; an exit of the real account (league/exitplan, league/auto
        # fast loop: trade/wake.ring) ends the nap within wake.STEP_S
        wake.nap(cfg["poll_s"], since=rung)
    if not a.once:
        _stop_equity()


def cmd_check(a):
    cfg = load(a.config)
    addr = wallet.address()
    print(f"prekidač: {'UKLJUČEN' if cfg['on'] else 'isključen'}, TRADE_LIVE={os.environ.get('TRADE_LIVE', '')!r}, "
          f"ključ: {'da' if wallet.can_sign() else 'ne'} -> {'LIVE' if executor.is_live(cfg) else 'DRY-RUN'}")
    print(f"wallet: {addr or 'nije postavljen'}; kill switch: {'UKLJUČEN' if os.path.exists(executor.STOP_FILE) else 'ne'}")
    if addr:
        try:
            print(f"stanje: {wallet.sol_balance(addr):.4f} SOL")
        except Exception as e:
            print(f"stanje: {e}")
    for route in ("v2", "ultra"):
        try:
            o = jupiter.order(jupiter.SOL, "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", int(cfg["size_sol"] * 1e9),
                              taker=addr, route=route)
            print(f"{executor.ROUTE_HR[route]}: {cfg['size_sol']} SOL -> {int(o.get('outAmount') or 0) / 1e5:,.0f} BONK, "
                  f"trošak {jupiter.cost_pct(o)}%, mrežne naknade {jupiter.fee_lamports(o) / 1e9:.6f} SOL"
                  + (f", napomena: {o.get('errorMessage')}" if o.get("errorMessage") else ""))
        except Exception as e:
            print(f"{executor.ROUTE_HR[route]}: ne odgovara ({type(e).__name__}: {e})")


def cmd_buy(a):
    cfg = load(a.config)
    r = executor.buy(executor.connect(DB), cfg, a.mint, size_sol=a.sol, reason="ručno")
    print(json.dumps(r, indent=1))


def cmd_sell(a):
    con = executor.connect(DB)
    row = con.execute("SELECT id FROM positions WHERE token=? AND status='open' ORDER BY id DESC", (a.mint,)).fetchone()
    if not row:
        sys.exit("Nema otvorene pozicije za taj token.")
    r = executor.sell(con, load(a.config), row[0], a.frac, close=a.frac >= 1, reason="ručno")
    print(json.dumps(r, indent=1))


def cmd_status(a):
    con = executor.connect(DB)
    for mode in ("live", "dry"):
        rows = con.execute("SELECT id, symbol, token, opened_ts, status, sol_in, sol_back, qty_raw, qty_left, reason "
                           "FROM positions WHERE mode=? ORDER BY id DESC LIMIT ?", (mode, a.limit)).fetchall()
        if not rows:
            continue
        closed = [r for r in rows if r[4] == "closed"]
        pnl = sum(r[6] - r[5] for r in closed)
        print(f"\n## {mode.upper()}: zatvorenih {len(closed)}, PnL {pnl:+.4f} SOL")
        for i, sym, tok, ts, st, sin, sback, q, ql, why in rows:
            extra = f"uloženo {sin:.3f}, vraćeno {sback:.4f}, ostalo {ql / q:.0%}" if q else (why or "")
            print(f"  #{i:<4} {dt.datetime.fromtimestamp(ts):%m-%d %H:%M} {sym or tok[:8]:<12} {st:<8} {extra}")


def limits_line(con, cfg):
    """One log line of the limits in force (settings as stored, not defaults): Grok autotrade's own, the caps every
    automatic live buy gets (executor.LIVE_CAPS), the owner's per-token cap (his manual buys, DCA, MC orders, the Grok
    requests he approves) and the Autopilot's per-token cap (copies; Grok autotrade too)."""
    from ui import grokauto
    g = grokauto.limits(con)
    raw = settings.raw(con)
    own = raw.get("owner_token_cap", raw.get("dca_token_cap", settings.DCA_TOKEN_CAP))
    auto_cap = raw.get("dca_token_cap", settings.DCA_TOKEN_CAP)
    lc = executor.LIVE_CAPS
    return (f"limiti: Grok autotrade {g['grok_max_sol_per_trade']:g} SOL po tradeu, {g['grok_max_sol_per_day']:g} SOL "
            f"na dan, {g['grok_max_open']} otvorene, dnevni gubitak {g['grok_max_loss_day']:g} SOL, {auto_cap:g} SOL po "
            f"tokenu, {g.get('max_round_trips_per_token_day', 3)} kruga po tokenu na dan (stop nakon "
            f"{grokauto.MAX_STOP_OUTS_DAY} izlaza stopom) | automatske live kupnje (LIVE_CAPS) {lc['max_sol_per_trade']:g}/{lc['max_sol_per_day']:g} SOL, "
            f"{lc['max_open']} otvorene, gubitak {lc['max_loss_day']:g} | tvoje ručne kupnje: {own:g} SOL po tokenu, "
            f"{cfg.get('max_sol_per_trade')} SOL po tradeu"
            + (f" | pravi_novac_sve UKLJUČEN: {switch_caps_text(cfg)}" if settings.pravi_novac_sve(con=con) else ""))


def switch_caps_text(cfg):
    """14.11.: the caps of the automatic real buys under pravi_novac_sve (executor.switch_caps), in words."""
    c = executor.switch_caps(cfg)
    return (f"stropovi {c['max_sol_per_trade']:g} SOL po tradeu, najviše {c['max_open']} otvorenih, "
            f"{c['max_buys_day']} kupnji dnevno, {c['max_sol_per_day']:g} SOL dnevno, dnevni gubitak "
            f"-{c['max_loss_day']:g} SOL (Zagreb dan)")


def main(argv=None):
    try:   # 10.11. (Jure): errors go to Sentry (ops/sentry.py); a no-op without SENTRY_DSN, never stops the start
        from ops import sentry
        sentry.init("trade")
    except Exception as e:  # noqa: BLE001
        print(f"sentry: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
    p = argparse.ArgumentParser()
    p.add_argument("--config", help="default trade/config.json")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("follow")
    f.add_argument("--once", action="store_true")
    sub.add_parser("check")
    b = sub.add_parser("buy")
    b.add_argument("mint")
    b.add_argument("--sol", type=float)
    s = sub.add_parser("sell")
    s.add_argument("mint")
    s.add_argument("--frac", type=float, default=1.0)
    st = sub.add_parser("status")
    st.add_argument("--limit", type=int, default=30)
    a = p.parse_args(argv)
    {"follow": cmd_follow, "check": cmd_check, "buy": cmd_buy, "sell": cmd_sell, "status": cmd_status}[a.cmd](a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
