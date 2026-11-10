"""Proven-twice copyable wallets (wallets/dokazani.py, 9.11.): the list, its place in the webhook, and the demo copy
strategy with the wallet's own sell as an exit and the delay/fill record for slippage."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from wallets import dokazani, store as wstore  # noqa: E402

NOW = 1_800_000_000
D = 86400


def _trades(con, wallet, rounds):
    """rounds: [(ts, cost_sol, proceeds_sol)] closed round trips (buy then full sell 5 min later)."""
    rows = []
    for i, (ts, cost, got) in enumerate(rounds):
        mint = f"{wallet}-M{i}"
        rows.append((wallet, f"{wallet}-b{i}", ts, mint, 1000.0, -cost, "buy"))
        rows.append((wallet, f"{wallet}-s{i}", ts + 300, mint, -1000.0, got, "sell"))
    con.executemany("INSERT INTO wallet_trades VALUES (?,?,?,?,?,?,?)", rows)


def _wallet(con, wallet, labels=(), hold=30, tpd=5):
    con.execute("INSERT INTO wallets (wallet, first_seen, last_seen, scored_at, stats, labels) VALUES (?,?,?,?,?,?)",
                (wallet, NOW - 40 * D, NOW, NOW, json.dumps({"median_hold_min": hold, "trades_per_day": tpd}), json.dumps(list(labels))))


def make_db(tmp):
    path = os.path.join(tmp, "wallets.db")
    con = wstore.connect(path)
    cut = NOW - 5 * D
    _wallet(con, "PROVEN")
    _trades(con, "PROVEN", [(cut - 10 * D + i * 3600, 1.0, 1.4 if i != 2 else 0.6) for i in range(6)]   # 5 of 6 wins
             + [(cut + D + i * 3600, 1.0, 1.3 if i else 0.8) for i in range(3)])                         # 2 of 3, positive
    _wallet(con, "ONCE")
    _trades(con, "ONCE", [(cut - 10 * D + i * 3600, 1.0, 1.4) for i in range(6)] + [(cut + D, 1.0, 0.5), (cut + 2 * D, 1.0, 0.6)])
    _wallet(con, "BOT", labels=["bot"], hold=1, tpd=900)
    _trades(con, "BOT", [(cut - 10 * D + i * 3600, 1.0, 1.4) for i in range(6)] + [(cut + D, 1.0, 1.3), (cut + 2 * D, 1.0, 1.3)])
    con.commit()
    return path, con


class Rule(unittest.TestCase):
    def test_proven_twice_only(self):
        tmp = tempfile.mkdtemp()
        path, con = make_db(tmp)
        rows = {r["wallet"]: r for r in dokazani.evaluate(con, NOW)}
        self.assertEqual(set(rows), {"PROVEN", "ONCE"})          # the bot is not copyable at all
        self.assertEqual((rows["PROVEN"]["passed"], rows["PROVEN"]["closed_before"], rows["PROVEN"]["win_before"]), (1, 6, 0.83))
        self.assertEqual(rows["ONCE"]["passed"], 0)              # good before the cut, lost after it
        n, tot = dokazani.run(con, NOW, log=None)
        self.assertEqual((n, tot), (1, 2))
        con.close()
        self.assertEqual(dokazani.current(path), {"PROVEN"})
        self.assertEqual(dokazani.current(os.path.join(tmp, "none.db")), set())

    def test_webhook_takes_proven_first(self):
        from kol import chainwatch, idents, store as kstore
        tmp = tempfile.mkdtemp()
        path, con = make_db(tmp)
        dokazani.run(con, NOW, log=None)
        con.close()
        kcon = kstore.connect(os.path.join(tmp, "kol.db"))
        idents.save(kcon, [{"wallet": f"ID{i}", "name": f"k{i}", "twitter": None, "telegram": None, "pnl": 1, "wins": 1,
                            "losses": 0, "rank": i} for i in range(10)], "kolscan")
        got = chainwatch.wanted(kcon, {"max_wallets": 6}, wallet_db=path)
        self.assertEqual(got[0], "PROVEN")
        self.assertEqual(len(got), 6)


class Strategy(unittest.TestCase):
    def test_copy_enters_records_delay_and_sells_when_the_wallet_sells(self):
        from strat import run, store
        tmp = tempfile.mkdtemp()
        hype = os.path.join(tmp, "hype.db")
        hc = sqlite3.connect(hype)
        hc.executescript("""CREATE TABLE chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER, sol REAL, PRIMARY KEY (sig, mint));
                            CREATE TABLE live_trades (sig TEXT, mint TEXT, wallet TEXT, side TEXT, sol REAL, tokens REAL, price_sol REAL,
                            mcap_sol REAL, pool TEXT, ts INTEGER, balance_after REAL, PRIMARY KEY (sig, mint));""")
        hc.execute("INSERT INTO chain_trades VALUES ('b1', 'PROVENWALLETxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', 'TOK', 'buy', ?, 1.0)", (NOW - 60,))
        hc.execute("INSERT INTO live_trades VALUES ('b1', 'TOK', 'PROVENWALLETxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', 'buy', 1.0, 1000, 0.001, 500, 'pump', ?, 1000)", (NOW - 60,))
        hc.commit(); hc.close()
        cfg = run.load_config()
        cfg = {**cfg, "strategies": [s for s in cfg["strategies"] if s["key"] in ("dokazani", "kontrola")]}
        self.assertEqual(run.exits_for(cfg, {"sl": -0.35, "tp": [[1.0, 0.5]], "stale_min": 10}, 100_000, "dokazani")["tp"], [[0.1, 0.5], [0.15, 0.5]])
        self.assertIsNone(run.exits_for(cfg, {"sl": -0.35, "stale_min": 10}, 100_000, "dokazani")["stale_min"])

        class Src:
            kol_db, hype_db = None, hype

            def read(self, now, window_s):
                return {"novcanici": [], "kol": [], "alat": [], "scored": [],
                        "dokazani": [("TOK", NOW - 60, "dokazani novčanik PROVENWALLETxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", 0)]}
        mk = lambda toks: {t: (1.0, 20000.0, 100000.0, t, "u") for t in toks}
        path = os.path.join(tmp, "strat.db")
        con = store.connect(path)
        store.kv_set(con, "start_ts", NOW - 3600)
        con.commit(); con.close()
        r = run.step(now=NOW, cfg=cfg, path=path, market_fn=mk, sources=Src(), quiet=True)
        self.assertGreaterEqual(r["entered"], 1)
        con = store.connect(path)
        p = store.rows(con, "strat='dokazani'")[0]
        self.assertEqual((p["token"], p["status"]), ("TOK", "open"))
        k = p["state"]["kopija"]
        self.assertEqual((k["wallet"], k["delay_s"], k["entry_mcap"]), ("PROVENWALLETxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", 60, 100000.0))
        self.assertEqual(k["wallet_fill"]["mcap_sol"], 500)
        con.close()
        hc = sqlite3.connect(hype)
        hc.execute("INSERT INTO chain_trades VALUES ('s1', 'PROVENWALLETxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', 'TOK', 'sell', ?, NULL)", (NOW + 400,))
        hc.commit(); hc.close()
        run.step(now=NOW + 600, cfg=cfg, path=path, market_fn=mk, sources=Src(), quiet=True)
        con = store.connect(path)
        p = store.rows(con, "strat='dokazani'")[0]
        self.assertEqual(p["status"], "closed")
        self.assertEqual(p["state"]["fills"][-1]["reason"], "dokazani prodao")
        con.close()

    def test_stale_signal_is_not_copied(self):
        from strat import run
        cfg = run.load_config()
        w = run.wanted({"dokazani": [("A", NOW - 30, "dokazani novčanik W", 0), ("B", NOW - 600, "dokazani novčanik W", 0)]}, cfg, NOW, 0)
        self.assertEqual([e[0] for e in w["dokazani"]], ["A"])


if __name__ == "__main__":
    unittest.main()


class Page(unittest.TestCase):
    def test_latest_rows_and_the_page_items(self):
        tmp = tempfile.mkdtemp()
        path, con = make_db(tmp)
        dokazani.run(con, NOW, log=None)
        con.close()
        rows = dokazani.latest(path)
        self.assertEqual([r["wallet"] for r in rows], ["PROVEN"])
        self.assertEqual((rows[0]["hold_min"], rows[0]["tpd"], rows[0]["passed"]), (30, 5, 1))
        self.assertEqual(dokazani.latest(os.path.join(tmp, "none.db")), [])
        from ui import pravitrade
        html = pravitrade._dokazani_items(rows, set(), True, {"PROVEN": "@proven"})
        self.assertIn("Prije reza", html)
        self.assertIn("@proven", html)
        self.assertIn("Poslije reza", html)
        card = pravitrade._buy_now_card({"size_sol": 0.1}, True)
        self.assertIn("Kupi ručno", card)   # 10.11. (maketa autopilot.html): the row's name under "Kako trguje"
        self.assertIn('name=sol value="0.1"', card)
        self.assertEqual(pravitrade._buy_now_card({"size_sol": 0.1}, False), "")
        src = open(os.path.join(ROOT, "ui", "pravitrade.py")).read()
        # 10.11. (Jure: "čista stranica", audit/2026-11-10/dizajn.md): the manual buy in the main column, the tool's
        # picks (influencers, wallets, tokens) in one closed section at the bottom, filled by /pravi-trade/preporuke
        page_src = src[src.index("def page(qs, user):"):]
        self.assertLess(page_src.index("_buy_now_card, cfg, owner"), page_src.index("_recs_section()"))
        self.assertIn("_kol_section, con, owner", src[src.index("def recs_fragment(user):"):])


class RealTradePageRework(unittest.TestCase):
    def test_sell_buttons_headers_refresh_and_follow_anyone(self):
        from ui import pravitrade
        btns = pravitrade._sell_btns(7, None)
        for fr in ("0.2", "0.5", "1"):
            self.assertIn(f"name=frac value={fr}", btns)
        self.assertIn("user-select:none", pravitrade.CSS)
        self.assertEqual(pravitrade.LOG_EVERY_S, 1)   # 9.11. 15:50 (Jure): every second
        self.assertEqual(pravitrade._detect_kind("@ansem"), ("kol", "ansem"))
        self.assertEqual(pravitrade._detect_kind("tg:henrygems"), ("kol", "tg:henrygems"))
        self.assertEqual(pravitrade._detect_kind("9pQQc1xyZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ"), ("wallet", "9pQQc1xyZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ"))
        src = open(os.path.join(ROOT, "ui", "pravitrade.py")).read()
        body = src[src.index("def page(qs, user):"):]
        # 10.11.: every part of the page is built behind _safe(name, fn, *args), the order is the same
        self.assertLess(body.index("_positions, tcon, not owner"), body.index("_follows, con, owner"))
        self.assertIn("/pravi-trade/pozicije", open(os.path.join(ROOT, "run_ui.py")).read())
        import sqlite3 as _s
        from trade import executor
        tcon = executor.connect(":memory:")
        inner, meta, has_open = pravitrade.positions_inner(tcon, False, True, {})
        self.assertIn("Još nema pozicija", inner)
        self.assertEqual((meta, has_open), ("0 otvoreno", False))
