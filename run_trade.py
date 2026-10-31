#!/usr/bin/env python3
"""Real (or dry-run) buys and sells that follow the paper trader's decisions.

    python3 run_trade.py check                     # mode, wallet address, SOL balance, does Jupiter answer
    python3 run_trade.py follow                    # loop: every new paper entry -> buy, every paper exit -> sell
    python3 run_trade.py buy <mint> [--sol 0.05]   # one manual buy through the same risk gate
    python3 run_trade.py sell <mint> [--frac 0.5]  # sell part of an open position (default all)
    python3 run_trade.py status                    # positions and PnL in SOL

Entry and exit rules stay in one place (run_paper.py + paper/config.json): `follow` mirrors what the paper
trader does, so a strategy is proven in demo and the same decisions then go live. Limits are in
trade/config.json. Dry-run is the default; see trade/executor.py for what turns on live trading.
"""
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import time

from trade import executor, jupiter, wallet

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "trade.db")  # own file, see run_hype.DB
PAPER_DB = os.path.join(HERE, "paper.db")


def notify(text):
    try:
        import run_hype
        run_hype.alert(text)
    except Exception as e:
        print(f"  telegram: {e}", file=sys.stderr)


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


def cmd_follow(a):
    cfg = executor.load_config(a.config)
    since = time.time() - cfg["max_signal_age_s"]
    print(f"Pratim paper.db, mod {'LIVE' if executor.is_live(cfg) else 'DRY-RUN'}, wallet {wallet.address()}")
    while True:
        cfg = executor.load_config(a.config)
        try:
            follow_once(executor.connect(DB), cfg, since)
        except Exception as e:
            print(f"greška: {type(e).__name__}: {e}", file=sys.stderr)
        if a.once:
            return
        time.sleep(cfg["poll_s"])


def cmd_check(a):
    cfg = executor.load_config(a.config)
    addr = wallet.address()
    print(f"config mode: {cfg['mode']}, TRADE_LIVE={os.environ.get('TRADE_LIVE', '')!r}, "
          f"ključ: {'da' if wallet.can_sign() else 'ne'} -> {'LIVE' if executor.is_live(cfg) else 'DRY-RUN'}")
    print(f"wallet: {addr or 'nije postavljen'}; kill switch: {'UKLJUČEN' if os.path.exists(executor.STOP_FILE) else 'ne'}")
    if addr:
        try:
            print(f"stanje: {wallet.sol_balance(addr):.4f} SOL")
        except Exception as e:
            print(f"stanje: {e}")
    o = jupiter.order(jupiter.SOL, "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", int(cfg["size_sol"] * 1e9))
    print(f"Jupiter: {cfg['size_sol']} SOL -> {int(o.get('outAmount') or 0) / 1e5:,.0f} BONK, trošak {jupiter.cost_pct(o)}%")


def cmd_buy(a):
    cfg = executor.load_config(a.config)
    r = executor.buy(executor.connect(DB), cfg, a.mint, size_sol=a.sol, reason="ručno")
    print(json.dumps(r, indent=1))


def cmd_sell(a):
    con = executor.connect(DB)
    row = con.execute("SELECT id FROM positions WHERE token=? AND status='open' ORDER BY id DESC", (a.mint,)).fetchone()
    if not row:
        sys.exit("Nema otvorene pozicije za taj token.")
    r = executor.sell(con, executor.load_config(a.config), row[0], a.frac, close=a.frac >= 1, reason="ručno")
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
