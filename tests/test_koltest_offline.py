"""KOL test book on synthetic calls and prices: entry on a fresh call, late/capped calls skipped, level hits with the
drop before them, the ladder book, the 24 h end, the exit grid, the dashboard page and the e-mail section."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from koltest import book, run, store  # noqa: E402

A = "HgxEGTZ1Epb64RrYqcuHkqb1gGWWnF5WcPTCDWzApump"
B = "8uBobWMhu6hRUn4jaA4kjcgWCjTxgHwHJtPgBePXpump"
T0 = 1793390000


class Book(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.db = os.path.join(self.d, "koltest.db")
        self.cfg = run.load_config()
        self.px = {A: 1.0, B: 1.0}
        self.events = []

    def mk(self, toks):
        return {t: (self.px[t], 50000, self.px[t] * 1e6, "SYM", "https://dexscreener.com/x") for t in toks
                if t in self.px}

    def step(self, now):
        return run.step(now=now, cfg=self.cfg, path=self.db, market_fn=self.mk,
                        events_fn=lambda now, cfg: [e for e in self.events if e[1] <= now], quiet=True)

    def rows(self):
        con = store.connect(self.db)
        try:
            return store.rows(con)
        finally:
            con.close()

    def test_path_levels_ladder_and_end(self):
        self.step(T0)   # starts the test
        self.events = [(A, T0 + 50, "x", "kolA", 60)]
        self.assertEqual(self.step(T0 + 60)["entered"], 1)
        # dips to -10%, then +25%, +45%, +60%
        for i, p in enumerate([0.9, 1.25, 1.45, 1.6]):
            self.px[A] = p
            self.step(T0 + 120 + 60 * i)
        p = self.rows()[0]
        self.assertEqual(p["status"], "open")
        self.assertAlmostEqual(p["trough"], -0.1, places=3)
        self.assertEqual(p["hits"]["0.2"][1], -0.1)        # dropped 10% before reaching +20%
        self.assertEqual(p["hits"]["0.2"][0], 120)         # two minutes after entry
        self.assertIn("0.5", p["hits"])
        self.assertNotIn("1", p["hits"])
        self.assertFalse(p["book"]["open"])                 # all four ladder steps sold
        self.assertEqual([f["reason"] for f in p["book"]["fills"]], ["+20%", "+30%", "+40%", "+50%"])
        self.assertGreater(p["pnl_usd"], 10)
        # 24 h later the measuring ends
        self.px[A] = 1.1
        self.step(T0 + 60 + 86400 + 60)
        p = self.rows()[0]
        self.assertEqual(p["status"], "done")
        self.assertIn("24h", p["rets"])

    def test_stop_and_rug(self):
        self.step(T0)
        self.events = [(A, T0 + 10, "tg", "tg:chan", 0), (B, T0 + 10, "chain", "w:abc", 0)]
        self.step(T0 + 30)
        self.px[A] = 0.6          # -40%: stop
        self.px[B] = 0.0          # rug
        self.step(T0 + 90)
        ps = {p["token"]: p for p in self.rows()}
        self.assertTrue(ps[A]["book_reason"].startswith("stop"))
        self.assertLess(ps[A]["pnl_usd"], -15)
        self.assertEqual(ps[B]["book_reason"], "rug")
        self.assertAlmostEqual(ps[B]["pnl_usd"], -50, places=3)
        self.assertEqual(ps[B]["trough"], -1.0)

    def test_late_duplicate_and_caps(self):
        self.step(T0)
        self.cfg = dict(self.cfg, per_hour={"x": 1, "tg": 5, "chain": 5})
        self.events = [(A, T0 + 10, "x", "kolA", 60), (A, T0 + 20, "x", "kolA", 60),   # same caller twice
                       (B, T0 + 15, "x", "kolB", 10)]                                    # over the x cap
        self.step(T0 + 60)
        self.events.append((B, T0 + 30, "tg", "tg:late", 0))
        self.step(T0 + 30 + 20 * 60)          # seen 20 min after the call: too late
        ps = self.rows()
        self.assertEqual([(p["caller"], p["token"]) for p in ps], [("kolA", A)])
        con = store.connect(self.db)
        sk = run.skips(con)
        con.close()
        self.assertEqual(sk[("x", "limit po satu")], 1)
        self.assertEqual(sk[("tg", "kasno")], 1)

    def test_calls_before_start_and_low_liq(self):
        self.step(T0)
        self.events = [(A, T0 - 100, "x", "kolA", 60), (B, T0 + 5, "x", "kolB", 60)]
        self.mk = lambda toks: {B: (1.0, 200, 1e5, "LOW", None)}
        self.step(T0 + 60)
        con = store.connect(self.db)
        rows = con.execute("SELECT token, status, close_reason FROM positions").fetchall()
        con.close()
        self.assertEqual(rows, [(B, "skip", "premala likvidnost")])

    def test_big_caps_skipped(self):
        self.step(T0)
        self.events = [(A, T0 + 5, "chain", "w:abc", 0)]
        self.mk = lambda toks: {A: (60000.0, 5e7, 3e8, "WBTC", None)}
        self.step(T0 + 60)
        con = store.connect(self.db)
        rows = con.execute("SELECT status, close_reason FROM positions").fetchall()
        con.close()
        self.assertEqual(rows, [("skip", "velik token")])

    def test_pending_rows_not_in_stats(self):
        """A call waiting for its first price (status pending) must not reach the page's statistics."""
        self.step(T0)
        self.events = [(A, T0 + 50, "x", "kolA", 60)]
        self.mk = lambda toks: {}
        self.step(T0 + 60)
        con = store.connect(self.db)
        self.assertEqual(con.execute("SELECT status FROM positions").fetchall(), [("pending",)])
        self.assertEqual(store.rows(con), [])
        con.close()

    def test_grid_and_levels(self):
        cfg = self.cfg
        base = {"status": "done", "entry_liq": 1e9, "rets": {"24h": 0.05}, "last_px": 1.05, "entry_px": 1.0}
        ps = [dict(base, hits={"0.2": [60, -0.05], "0.5": [600, -0.05]}, trough=-0.05, peak=0.6),
              dict(base, hits={"0.2": [60, -0.4]}, trough=-0.4, peak=0.25),
              dict(base, hits={}, trough=-0.1, peak=0.1)]
        g = {(x["tp"], x["sl"]): x for x in book.grid(ps, cfg)}
        # +20% without stop: 2 of 3 reach it, third ends at +5%
        self.assertEqual(g[(0.2, None)]["wins"], 3)
        # +20% with -35% stop: the second dropped to -40% first
        self.assertEqual(g[(0.2, -0.35)]["wins"], 2)
        lv = {r["level"]: r for r in book.levels_table(ps, cfg)}
        self.assertEqual(lv[0.2]["hit"], 2)
        self.assertEqual(lv[0.5]["hit"], 1)
        self.assertEqual(lv[0.2]["stopped_first"], 1)

    def test_page_and_report(self):
        self.step(T0)
        self.events = [(A, T0 + 50, "x", "kolA", 60), (B, T0 + 50, "chain", "w:abc", 0)]
        self.step(T0 + 60)
        self.px[A] = 1.3
        self.step(T0 + 120)
        os.environ["KOLTEST_DB"] = self.db
        store.DB = self.db
        from ui import koltest as page
        title, html = page.page({})
        self.assertIn("KOL test", html)
        self.assertIn("Što bi koji izlaz zaradio", html)
        self.assertIn("kolA", html)
        self.assertNotIn("None", html)
        from kol import store as kstore
        orig = kstore.bot_handles
        kstore.bot_handles = lambda path=None: {"kolA"}
        try:
            _, html2 = page.page({})
            self.assertIn("Izuzeto iz statistike: 1 ulaza", html2)
            self.assertEqual(page.report_data(T0 + 200)["all"]["n"], 1)
        finally:
            kstore.bot_handles = orig
        data = page.report_data(T0 + 200)
        self.assertEqual(data["all"]["n"], 2)
        from report import render
        out = []
        kt = data
        self.assertTrue(kt["all"]["hit20"] >= 1)
        html = render.render({"ts": T0 + 200, "paper": {"pnl": 0, "closed": 0, "open_now": 0, "wins": 0,
                                                         "median_ret": None, "best": [], "worst": [], "week": []},
                              "kols": {"calls_24h": 0, "new_kols": 0, "top": [], "watch": [], "best_calls": []},
                              "sessions": {}, "today": {"now": "eu", "tokens": []}, "pulse": [], "weights": {"runs": []},
                              "exits": {"changed": []}, "market": None, "koltest": kt}, {}, "pravila")
        self.assertIn("KOL test", html)
        del out


if __name__ == "__main__":
    unittest.main()
