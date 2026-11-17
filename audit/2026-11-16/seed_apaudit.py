#!/usr/bin/env python3
"""Local copy of the Autopilot page (/pravi-trade) in the state of the owner's report of 16.11. ("Kliknem na otvorenu
poziciju GTA V6 ... otvori graf nekog tokena koji se zove Umbra"). NOT part of the app: it builds small databases in
a scratch folder and serves the REAL run_ui.py over them, with no network and no key.

    python3 audit/2026-11-16/seed_apaudit.py --dir /tmp/.../apaudit-db --serve 8795 [--stari]
    -> http://127.0.0.1:8795/pravi-trade   (Basic auth Jure / demo)

What is seeded (three open REAL positions of the midcap strategy "veliki", as production had them):
  PRVT6T…  stored symbol "PRVT6T" (the mint prefix veliki/live.enter wrote), really UMBRA; wide stop -20 %
  GTA6x…   stored symbol "GTA6" (a proper one); the tight stop of a BTC episode
  Ce2gx9…  stored symbol "Ce2gx9" (prefix), DexScreener gives no symbol, the veliki list knows "TROLL"; stop at entry
  LONG…    a demo (dry) manual position with a long name and its own TP / SL, for the paper rows
  + two closed real trades (one with a prefix symbol), a blocked one, the wallet's equity history
--prazno: no positions at all (the empty states). --stari: leave the stored prefix symbols alone at startup (the page as production showed it: skips the fix-up).
Everything that would reach the network is answered by audit/2026-11-10/local/sitecustomize.py from market.json;
the exit loops are off (LEAGUE_AUTO_SELL=0), so nothing sells and the rows stay as seeded.
"""
import argparse
import json
import math
import os
import random
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OWNER = "Jure"
PUB = "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin"
UMBRA = "PRVT6TkQ8sVn3FrUd2D9xs2zqDBsa3GbMJMwCQsgmeta"
GTA6 = "GTA6xPm4QhV7dT1cYw9uJbR3nK8sLfE2aZoH5iBvpump"
TROLL = "Ce2gx9KsM4vTq7WdR1pYhJ8nB3aLfU6cZoE5iXwVpump"
LONG = "LongNm7QhV2dT9cYw4uJbR8nK1sLfE6aZoH3iBvXpump"
OLD1 = "Dz9mQ9Rk5tWv2YbN7cJ4hG8sLfE1aZoH6iBvXpQdpump"
OLD2 = "7GCihgT3mWq9YbN5cJ2hG6sLfE8aZoH1iBvXpQdRpump"
SOL_USD = 171.0
# symbol on DexScreener (None: the pair carries no symbol), price, MC, liquidity
MARKET = {UMBRA: ("UMBRA", 0.9412, 94_120_000, 2_300_000), GTA6: ("GTA6", 0.01182, 11_820_000, 760_000),
          TROLL: (None, 0.0507, 50_700_000, 1_900_000), LONG: ("SUPERCALIFRAGILISTIC", 0.000212, 212_000, 41_000),
          OLD1: ("DZ", 0.0061, 6_100_000, 520_000), OLD2: ("GIGA", 0.0152, 15_200_000, 900_000)}


def env(d):
    os.makedirs(d, exist_ok=True)
    for k in ("ttl", "snap", "cache", "gate"):
        os.makedirs(os.path.join(d, k), exist_ok=True)
    e = {"TRADE_DB": "trade.db", "LEAGUE_DB": "league.db", "MIDCAP_DB": "midcap.db", "VELIKI_DB": "veliki.db",
         "KOL_DB": "kol.db", "TG_DB": "tg.db", "TOPCHECK_DB": "topcheck.db", "WALLET_DB": "wallets.db", "RUG_DB": "rug.db",
         "MINUTE_DB": "minute.db", "RANGE_DB": "range.db", "USAGE_DB": "usage.db", "PROPOSALS_DB": "proposals.db", "EVENTS_DB": "events.db"}
    for k, v in e.items():
        os.environ[k] = os.path.join(d, v)
    os.environ.update({
        "UIPROP_MARKET": os.path.join(d, "market.json"), "TRADE_OWNER": OWNER, "SOLANA_PUBLIC_KEY": PUB,
        "UI_USERS": "Jure,Ivan", "UI_PASS_JURE": "demo", "UI_PASS_IVAN": "demo", "UI_ADMINS": OWNER,
        "UI_TTL_DIR": os.path.join(d, "ttl"), "UI_SNAP_DIR": os.path.join(d, "snap"),
        "CAL_CACHE_DIR": os.path.join(d, "cache"), "HTTP_GATE_DIR": os.path.join(d, "gate"),
        "DEPLOY_WAIT_FLAG": os.path.join(d, "starting"), "HEAVY_LOCK": os.path.join(d, "heavy.lock"),
        "LEAGUE_AUTO_SELL": "0", "I18N_OFF": "1", "TZ": "Europe/Zagreb", "TRADE_LIVE": "1", "AP_BG_REFRESH": "1",
        "PYTHONDONTWRITEBYTECODE": "1"})
    for k in ("SOLANA_PRIVATE_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY", "SENTRY_DSN", "RENDER",
              "DATA_DIR", "HELIUS_API_KEY", "TELEGRAM_BOT_TOKEN"):
        os.environ.pop(k, None)


def market_json(d):
    out = {}
    for mint, (sym, px, mcap, liq) in MARKET.items():
        base = {"address": mint, "name": (sym or "").title()}
        if sym:
            base["symbol"] = sym
        out[mint] = {"chainId": "solana", "dexId": "raydium", "pairAddress": "Pool" + mint[:40], "baseToken": base,
                     "quoteToken": {"address": "So11111111111111111111111111111111111111112", "symbol": "SOL"},
                     "url": f"https://dexscreener.com/solana/{mint}", "priceUsd": f"{px:.10g}", "marketCap": mcap,
                     # UMBRA: about half of the supply circulates, so DexScreener's page shows an FDV twice our MC
                     "fdv": round(mcap * 1.97) if mint == UMBRA else mcap, "liquidity": {"usd": liq}, "pairCreatedAt": int((time.time() - 40 * 86400) * 1000),
                     "volume": {"m5": 21_000, "h1": 240_000, "h6": 1_100_000, "h24": 4_200_000},
                     "priceChange": {"m5": 0.6, "h1": -1.4, "h6": 3.2, "h24": -6.5},
                     "txns": {"m5": {"buys": 31, "sells": 24}, "h1": {"buys": 340, "sells": 310},
                              "h6": {"buys": 1800, "sells": 1700}, "h24": {"buys": 7000, "sells": 6800}}}
    with open(os.path.join(d, "market.json"), "w", encoding="utf-8") as f:
        json.dump(out, f)


def seed(d, now=None):
    from league import copy, store
    from trade import executor, settings
    from veliki import live as vlive, midcap, store as vstore
    now = int(now or time.time())
    rng = random.Random(1611)
    tcon = executor.connect(os.environ["TRADE_DB"])
    try:
        from trade import equity
        equity.ensure(tcon)
    except Exception:  # noqa: BLE001
        equity = None
    try:
        from trade import aplog
        aplog.ensure(tcon)
    except Exception:  # noqa: BLE001
        pass
    for k, v in (("on", True), ("heartbeat", now - 5), ("wallet_pub", PUB), ("invited", ["Ivan"]), ("size_sol", 0.1),
                 ("flag:exit_plan_live", {"mode": "live", "since": now - 86400, "who": OWNER}),
                 ("flag:veliki_range", {"mode": "paper", "since": now - 86400, "who": OWNER}),
                 ("flag:pravi_novac_veliki", {"mode": "live", "since": now - 86400, "who": OWNER})):
        settings.put(tcon, k, v, OWNER)
    # the wallet's value: 6 days, one deposit, a small drift down (the report's day)
    t0, net, rows = now - 6 * 86400, 0.0, []
    for i, ts in enumerate(range(t0, now - 60, 600)):
        flow = 1.4 if i == 0 else 0.0
        net += flow
        x = (ts - t0) / 86400
        pnl = -0.02 * x + 0.03 * math.sin(x * 2.1) + rng.gauss(0, 0.002)
        tokens = 0.3 if ts > now - 6 * 3600 else 0.1
        rows.append((ts, round(net + pnl - tokens, 6), 0.0, tokens, SOL_USD + 3 * math.sin(x), 0.862, flow, "live"))
    tcon.execute("DELETE FROM equity")
    tcon.executemany("INSERT INTO equity (ts, sol, usdc, tokens_sol, sol_usd, usd_eur, flow_sol, src) VALUES (?,?,?,?,?,?,?,?)",
                     rows)
    lg = store.connect(os.environ["LEAGUE_DB"])
    copy.ensure(lg)
    vlive.ensure(lg)
    for u in (settings.LEAGUE_USER, settings.PAPER_USER):
        lg.execute("INSERT OR IGNORE INTO accounts VALUES (?,?,?)", (u, 1e6, now))
    L = 1_000_000_000

    def veliki(tok, stored, ago, entry, stop, tp, mcap, kind="intra", wide=None, tight_ts=None, be=None, status="open",
               back=None):
        """One real midcap trade as veliki/live.enter + run_trade.py leave it: the league trade (auto NULL: the
        strategy sells it), its veliki_trades row and the real position that mirrors it."""
        why = (f"veliki: dnevna zona {entry * 0.97:.6g}-{entry * 1.14:.6g} (17%), cilj {tp / entry - 1:+.1%}, stop "
               f"{stop / entry - 1:+.0%}, BTC normalno")
        size_usd = 0.1 * SOL_USD
        tid = lg.execute("INSERT INTO trades (user, token, symbol, opened_ts, status, size_usd, entry_px, entry_eff, qty, "
                         "source, entry_mcap) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (settings.LEAGUE_USER, tok, stored, now - ago, status, size_usd, entry, entry * 1.005,
                          size_usd / (entry * 1.005), why, mcap)).lastrowid
        lg.execute("INSERT INTO veliki_trades (user, token, symbol, opened_ts, trade_id, size_sol, size_usd, entry_px, "
                   "tp_px, stop_px, rt, drt, liq, mcap, cfg, zone, status, why, btc_state, kind, be_px, first_px, wide_px, "
                   "tight_ts, lots, time_h, trail, half_frac) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?)",
                   (settings.LEAGUE_USER, tok, stored, now - ago, tid, 0.1, size_usd, entry, tp, stop, 0.012, 0.012,
                    MARKET[tok][3], mcap, "intra", "{}", status, why, "normalno", kind, be or entry * 1.012, entry, wide,
                    tight_ts, 24.0, 0.0, 0.0))
        q = 1_000_000_000
        closed = status != "open"
        pid = tcon.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, qty_left, "
                           "sol_back, closed_ts, league_id, fees_sol) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (tok, stored, now - ago + 4, "live", "closed" if closed else "open", why, 0.1, q,
                            0 if closed else q, back, (now - ago + 5400) if closed else None, tid, 0.0006)).lastrowid
        tcon.execute("INSERT INTO orders (ts, position_id, token, side, mode, amount_in, amount_out, status, reason, "
                     "signature, route, fee_lamports) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (now - ago + 4, pid, tok, "buy", "live", int(0.1 * L), q, "ok", why, "5sig" + tok[:40], "v2", 105_000))
        if closed:
            lg.execute("UPDATE trades SET closed_ts=?, exit_px=?, ret=?, pnl_usd=? WHERE id=?",
                       (now - ago + 5400, entry * back / 0.1, back / 0.1 - 1, (back / 0.1 - 1) * size_usd, tid))
            lg.execute("UPDATE veliki_trades SET closed_ts=?, exit_px=?, reason=?, ret=? WHERE trade_id=?",
                       (now - ago + 5400, entry * back / 0.1, "tp" if back > 0.1 else "stop", back / 0.1 - 1, tid))
            tcon.execute("INSERT INTO orders (ts, position_id, token, side, mode, amount_in, amount_out, status, reason, "
                         "signature, route, fee_lamports) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (now - ago + 5400, pid, tok, "sell", "live", q, int(back * L), "ok",
                          "veliki: cilj" if back > 0.1 else "veliki: stop", "4sig" + tok[:40], "v2", 105_000))
        return pid

    # UMBRA: the newest (the page opens on it), stored under its mint prefix; only the wide stop -20 %
    e = 0.962
    veliki(UMBRA, UMBRA[:6], 35 * 60, e, e * 0.80, e * 1.112, 96_200_000, wide=e * 0.80)
    # GTA6: a proper symbol; BTC fell, the tight stop 4 % under the price of that moment
    e = 0.01204
    veliki(GTA6, "GTA6", 3 * 3600, e, 0.01171 * 0.96, e * 1.112, 12_040_000, wide=e * 0.80, tight_ts=now - 1500)
    # Ce2gx9 (TROLL): prefix; +5 % net was reached, the stop is at the entry (break-even)
    e = 0.0478
    veliki(TROLL, TROLL[:6], 5 * 3600, e, e * 1.012, e * 1.112, 47_800_000, wide=e * 1.012, be=e * 1.012)
    # closed real trades for Povijest: one stored under its prefix (resolved by midcap.db: "DZ"), one proper
    veliki(OLD1, OLD1[:6], 9 * 3600, 0.0064, 0.0064 * 0.8, 0.0064 * 1.11, 6_400_000, status="closed", back=0.0957)
    veliki(OLD2, "GIGA", 20 * 3600, 0.0141, 0.0141 * 0.8, 0.0141 * 1.11, 14_100_000, status="closed", back=0.1094)
    # a demo (dry) manual position with a long symbol and its own TP / SL
    rule = {"mode": "tpsl", "tp": "+40%", "sl": "-25%", "tp_in": "40%", "sl_in": "-25%"}
    sym = MARKET[LONG][0]
    tid = lg.execute("INSERT INTO trades (user, token, symbol, opened_ts, status, size_usd, entry_px, entry_eff, qty, "
                     "source, entry_mcap, auto) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (settings.LEAGUE_USER, LONG, sym, now - 7200, "open", 17.1, 0.000198, 0.000199, 17.1 / 0.000199,
                      "ručno (pravi trade)", 198_000, json.dumps(rule))).lastrowid
    tcon.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, qty_left, "
                 "league_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (LONG, sym, now - 7200, "dry", "open", "ručno (pravi trade)", 0.1, 1000, 1000, tid))
    tcon.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason) VALUES (?,?,?,?,?,?)",
                 (OLD2, "GIGA", now - 1800, "live", "blocked", "veliki: najviše 5 otvorenih pozicija"))
    tcon.commit()
    lg.commit()
    lg.close()
    tcon.close()
    # midcap.db (the collector's members) and the veliki list: where the real symbols live
    mc = midcap.connect(os.environ["MIDCAP_DB"])
    for i, (mint, s) in enumerate(((UMBRA, "UMBRA"), (GTA6, "GTA6"), (TROLL, TROLL[:6]), (OLD1, "DZ"), (OLD2, "GIGA"))):
        mc.execute("INSERT OR REPLACE INTO tokens (mint, id, symbol, mcap, liq, vol24, first_ts, last_ts, member) "
                   "VALUES (?,?,?,?,?,?,?,?,1)", (mint, i + 1, s, MARKET[mint][2], MARKET[mint][3], 4e6, now - 86400, now))
    mc.commit()
    mc.close()
    # two days of our own minute snapshots per token: the chart's candles on every time frame
    from rangedca import data as rdata
    rc = rdata.connect(os.environ["RANGE_DB"])
    for mint, (_s, px, mcap, liq) in MARKET.items():
        p, rows = px * 1.06, []
        for ts in range(now - 2 * 86400, now, 60):
            p = max(px * 0.7, p * (1 + rng.gauss(0, 0.0035)) + (px - p) * 0.002)
            rows.append((mint, ts, p, mcap * p / px, liq, 9000.0, 90_000.0, None, 10, 5, None, 100, 50))
        rc.executemany("INSERT OR REPLACE INTO snaps VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    rc.commit()
    rc.close()
    vc = vstore.connect(os.environ["VELIKI_DB"])
    vstore.save_list(vc, [{"mint": m, "symbol": s, "name": s, "mcap": MARKET[m][2], "liq": MARKET[m][3], "vol24": 4e6,
                           "age_d": 40} for m, s in ((UMBRA, "UMBRA"), (GTA6, "GTA6"), (TROLL, "TROLL"))], now)
    vc.close()


def serve(port, d, old):
    # answers DexScreener / Jupiter / RPC from market.json and refuses every other host (loaded by path: Python may
    # already hold a module named sitecustomize)
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "apaudit_local", os.path.join(ROOT, "audit", "2026-11-10", "local", "sitecustomize.py"))
    spec.loader.exec_module(importlib.util.module_from_spec(spec))
    from trade import executor, settings, wallet
    wallet.can_sign = lambda: True       # "armed" for the page only: nothing signs, run_trade.py is not running
    wallet.address = lambda: PUB
    executor.armed = lambda: True
    if old:
        os.environ["AP_SYMBOL_FIX"] = "0"
    else:   # what veliki/live.tick does at its first pass in production (the exit loops are off here)
        from league import store
        from veliki import symbols
        lg = store.connect(os.environ["LEAGUE_DB"])
        print("popravak naziva:", symbols.fix_once(lg), flush=True)
        lg.close()

    def beat():
        while True:
            try:
                con = executor.connect(os.environ["TRADE_DB"])
                settings.put(con, "heartbeat", int(time.time()), "trade")
                con.close()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(30)
    threading.Thread(target=beat, daemon=True).start()
    import run_ui
    run_ui.main(["--port", str(port)])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True, help="scratch folder for the databases (never the repo, never production)")
    ap.add_argument("--serve", type=int, default=0)
    ap.add_argument("--stari", action="store_true", help="no symbol fix-up at startup (the page as it was)")
    ap.add_argument("--prazno", action="store_true", help="no positions, orders or trades (the page's empty states)")
    a = ap.parse_args()
    if os.environ.get("RENDER") or os.path.exists("/var/data"):
        sys.exit("seed_apaudit: ovo izgleda kao produkcija. Ne pokrećem.")
    d = os.path.abspath(a.dir)
    env(d)
    sys.path.insert(0, ROOT)
    os.chdir(ROOT)
    if not os.path.exists(os.environ["TRADE_DB"]):
        market_json(d)
        seed(d)
        if a.prazno:
            import sqlite3
            for db, tables in ((os.environ["TRADE_DB"], ("positions", "orders")),
                               (os.environ["LEAGUE_DB"], ("trades", "veliki_trades"))):
                con = sqlite3.connect(db)
                for t in tables:
                    con.execute(f"DELETE FROM {t}")
                con.commit()
                con.close()
    print(f"baze: {d}", flush=True)
    if a.serve:
        serve(a.serve, d, a.stari)


if __name__ == "__main__":
    main()
