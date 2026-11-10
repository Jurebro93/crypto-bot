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

from trade import executor, jupiter, settings, wallet

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


def _league():
    if not os.path.exists(LEAGUE_DB):
        return None
    return sqlite3.connect(f"file:{LEAGUE_DB}?mode=ro", uri=True, timeout=10)


MIN_MCAP_USD = 30_000   # CLAUDE.md: tokens under $30k are never bought; last line of defence behind league/copy.py
PROOF = {"closed": 10, "win_rate": 0.4}   # 9.11. (audit P39): a follow needs this much demo proof before real money
COPY_BOOK_WAIT_S = 5   # 9.11. (review novac): league/copy.py commits the demo trade a few ms before its follow_id and
                       # copy_log row; a copy read in that gap looks like a manual buy with a fresh signal


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
    try:
        from league import copy as lcopy
        r = lcopy.follow_results(lg).get(follow_id)
    except Exception:  # noqa: BLE001 - no copy tables: no proof
        r = None
    closed, wins, pnl = (r["closed"], r["wins"], r["pnl"]) if r else (0, 0, 0.0)
    if closed < PROOF["closed"] or pnl <= 0 or wins / closed < PROOF["win_rate"]:
        return (f"praćenje bez dokaza u demu (zatvorenih {closed}, dobitnih {wins}, PnL {pnl:+.0f} $; "
                f"treba {PROOF['closed']}+ zatvorenih, PnL > 0 i {PROOF['win_rate']:.0%}+ dobitnih)")
    return None


def _mirrored(con, league_id):
    """10.11. (Jure: "sekundni poslovi ne smiju čitati cijelu bazu svake sekunde"): has this demo trade its
    positions row already? One lookup through the index on league_id (trade/aplog.INDEXES) per fresh demo trade; the
    loop used to read every league_id in the table on every 1-second pass to answer the same question."""
    return con.execute("SELECT 1 FROM positions WHERE league_id=? LIMIT 1", (league_id,)).fetchone() is not None


def follow_league_once(con, cfg, since, now=None, quiet=False):
    """Mirror the competition account "pravi-trade": its new open trades -> buys, its (partial) exits -> sells.
    The share still held in the demo trade (qty / bought qty) is the share kept of the real position."""
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
        live = executor.is_live(cfg)
        tag = "LIVE" if live else "DRY"
        for t in fresh:
            if _mirrored(con, t["id"]):
                continue
            size = (cfg.get("manual_size") or {}).get(str(t["id"]))   # "Kupi ručno" on the page sets its own stake
            is_copy = (t["source"] or "").startswith("copy ")   # league/copy.py: "copy KOL x" / "copy wallet x" / "copy ekipa x"
            call_ts = _call_ts(lg, t["id"])
            if is_copy and (t["follow_id"] is None or call_ts is None) and now - t["opened_ts"] < COPY_BOOK_WAIT_S:
                continue   # 9.11. (review novac): the copy loop is still booking follow_id / copy_log: next tick (`since` is fixed)
            # 9.11. (audit P30/P31/P32): "fresh" is measured from the CALL (copy_log.ev_ts) when the copy loop wrote
            # it, not from the demo entry; the demo may legally enter up to max_delay_min after the post
            t0 = min(t["opened_ts"], call_ts or t["opened_ts"])
            why = None
            if now - t0 > cfg["max_signal_age_s"]:
                why = f"signal star {now - t0:.0f} s"
            elif t["entry_mcap"] is not None and t["entry_mcap"] < MIN_MCAP_USD:   # known bad only (P1/P7)
                why = f"MC ${t['entry_mcap']:,.0f} ispod 30k (pravilo: ispod 30k se ne kupuje)"
            elif live and not size and (t["follow_id"] is not None or is_copy):   # a copy never passes as "manual"
                why = _no_proof(lg, t["follow_id"])
            if why:
                con.execute("INSERT INTO positions (league_id, token, symbol, opened_ts, mode, status, reason) "
                            "VALUES (?,?,?,?,?,?,?)", (t["id"], t["token"], t["symbol"], int(now), tag.lower(), "blocked", why))
                con.commit()
                # 9.11. (Jure: "samo jedan trade izvršen, zašto?"): the reason used to be only in the positions table
                _say(f"{tag} PRESKOČENO {t['symbol'] or t['token'][:6]} ({t['source'] or 'copy'}): {why}", quiet)
                continue
            # 10.11. (Jure: "ako unesem adresu tokena koji je već u poziciji, pozicija se podeblja"): the owner's manual
            # buy (its own stake, never a copy) may add one more lot to a token already held; a copy never doubles one
            r = executor.buy(con, cfg, t["token"], t["symbol"], now=now, reason=t["source"] or "copy",
                             league_id=t["id"], size_sol=float(size) if size else None,
                             tp_pct=_tp_pct(t["auto"], cfg.get("tp_default") or 15),   # 15: the page default (ui/pravitrade)
                             add=bool(size) and not is_copy)
            if r["status"] == "open":
                _say(f"{tag} KUPNJA {t['symbol']} {r['amount_in'] / executor.LAMPORTS:.3f} SOL ({t['source']})", quiet)
            else:
                _say(f"{tag} kupnja {t['symbol']} nije prošla: {r.get('error')}", quiet)
        for pos_id, lid, qty_raw, qty_left, sym in con.execute(
                "SELECT id, league_id, qty_raw, qty_left, symbol FROM positions WHERE status='open' "
                "AND league_id IS NOT NULL").fetchall():
            d = lg.execute("SELECT status, size_usd, entry_eff, qty, note FROM trades WHERE id=?", (lid,)).fetchone()
            if d is None:
                continue
            if d["status"] == "closed":
                r = executor.sell(con, cfg, pos_id, close=True, now=now, reason=d["note"] or "demo izlaz")
            else:
                bought = d["size_usd"] / d["entry_eff"] if d["entry_eff"] else 0
                keep = min(1.0, d["qty"] / bought) if bought else 1.0
                have_frac = qty_left / qty_raw if qty_raw else 0
                if have_frac - keep < 0.05:
                    continue
                r = executor.sell(con, cfg, pos_id, have_frac - keep, now=now, reason="djelomična prodaja (demo)")
            if r["status"] in ("ok", "dry"):
                _say(f"{r['status'].upper()} PRODAJA {sym} -> {r['amount_out'] / executor.LAMPORTS:.4f} SOL", quiet)
            elif r["status"] not in ("noop", "wait"):
                _say(f"prodaja {sym} nije prošla: {r.get('error')}; pokušavam opet", quiet)
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
        try:
            con = executor.connect(DB)
            cfg = load(a.config, con)
            live_now = executor.is_live(cfg)
            if live_now != beat["live"]:   # 9.11.: the mode is visible in the log every time it changes, not only at start
                # 9.11. (audit P37): config.json "mode" is informative only; what decides is the switch + env + key
                print(f"pravi trade: mod {'LIVE' if live_now else 'DRY-RUN'} (prekidač {'uključen' if cfg.get('on') else 'isključen'}, "
                      f"TRADE_LIVE={os.environ.get('TRADE_LIVE', '')!r}, ključ {'da' if wallet.can_sign() else 'ne'}, "
                      f"config mode={cfg.get('mode', '?')!r} samo kao napomena)", flush=True)
                beat["live"] = live_now
            if time.time() - beat["ts"] >= 60:   # the page shows "trade proces ne radi" when this gets old
                settings.put(con, "heartbeat", int(time.time()), "bot")
                beat["ts"] = time.time()
            executor.reconcile_pending(con)   # buys a crash left half-booked, matched with the wallet
            sell_all_once(con, cfg)
            sell_requests_once(con, cfg)
            if cfg.get("follow_paper"):
                follow_once(con, cfg, since)
            follow_league_once(con, cfg, since)
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
        time.sleep(cfg["poll_s"])
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
