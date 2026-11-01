"""Automatic DCA in the competition (league/dca.py, Natjecanje block): plans, scheduled buys into one averaged
position, stops on done / no cash / rug / low liquidity, page and form. No network."""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import dca, store  # noqa: E402
from ui import league  # noqa: E402

A = "A" * 43
B = "B" * 43


class Dca(unittest.TestCase):
    def setUp(self):
        store.DB = os.path.join(tempfile.mkdtemp(), "league.db")
        self.mk = {A: (1.0, 1e6, None, 1e6, "AAA"), B: (1.0, 2000, None, 1e6, "BBB")}
        dca._rugged = lambda *a: None

    def market(self, toks):
        return {t: self.mk[t] for t in toks if t in self.mk}

    def test_buys_on_schedule_into_one_averaged_position(self):
        con = store.connect()
        now = int(time.time())
        pid = dca.start(con, "Ivan", A, "AAA", 20, 60, 3, now=now)
        self.assertEqual(len(dca.run_once(con, self.market, now)), 1)          # first buy right away
        self.assertEqual(dca.run_once(con, self.market, now + 60), [])          # not due yet
        self.mk[A] = (0.5, 1e6, None, 5e5, "AAA")                               # price halves
        dca.run_once(con, self.market, now + 3600)
        t = store.trades(con, "Ivan", "open")
        self.assertEqual(len(t), 1)
        t = t[0]
        self.assertAlmostEqual(t["size_usd"], 40)
        self.assertAlmostEqual(t["entry_px"], 40 / (20 / 1.0 + 20 / 0.5))     # dollar-weighted average = 0.667
        self.assertAlmostEqual(t["entry_mcap"], 1e6 * t["entry_px"])
        self.assertEqual(t["source"], "DCA kupnja 2/3")
        self.assertAlmostEqual(store.account(con, "Ivan")["cash"], 960)
        dca.run_once(con, self.market, now + 7200)
        p = dca.plans(con, "Ivan", active=None)[0]
        self.assertEqual((p["n_done"], p["active"], p["spent"]), (3, 0, 60))
        self.assertTrue(p["why"].startswith("gotovo"))
        self.assertEqual(dca.run_once(con, self.market, now + 99999), [])
        self.assertEqual([r["action"] for r in dca.log(con, pid)], ["kupnja"] * 3)

    def test_adds_to_manual_position_and_reopens_after_sell(self):
        con = store.connect()
        now = int(time.time())
        tid = store.buy(con, "Ivan", A, "AAA", 100, 1.0, 1e6, "ručno", mcap=1e6)
        dca.start(con, "Ivan", A, "AAA", 10, 15, 5, now=now)
        dca.run_once(con, self.market, now)
        t = store.trades(con, "Ivan", "open")[0]
        self.assertEqual((t["id"], t["size_usd"], t["source"]), (tid, 110, "ručno"))
        store.sell(con, "Ivan", tid, 1.0, 1e6)
        dca.run_once(con, self.market, now + 900)
        t = store.trades(con, "Ivan", "open")[0]
        self.assertNotEqual(t["id"], tid)
        self.assertEqual(t["size_usd"], 10)

    def test_stops_on_no_cash_low_liquidity_and_rug(self):
        con = store.connect()
        now = int(time.time())
        dca.start(con, "Ivan", A, "AAA", 500, 15, 3, now=now)
        dca.run_once(con, self.market, now)
        dca.run_once(con, self.market, now + 900)
        dca.run_once(con, self.market, now + 1800)    # third $500 does not fit into $1,000
        p = dca.plans(con, "Ivan", active=None)[0]
        self.assertEqual((p["n_done"], p["active"]), (2, 0))
        self.assertIn("novca", p["why"])
        dca.start(con, "Panda", B, "BBB", 20, 15, 3, now=now)
        dca.run_once(con, self.market, now)
        self.assertIn("likvidnost", dca.plans(con, "Panda", active=None)[0]["why"])
        dca._rugged = lambda *a: {"text": "70% ispod vrha"}
        dca.start(con, "Jure", A, "AAA", 20, 15, 3, now=now)
        dca.run_once(con, self.market, now)
        self.assertIn("srušio", dca.plans(con, "Jure", active=None)[0]["why"])
        self.assertEqual(store.trades(con, "Jure"), [])

    def test_validation_stop_and_missing_price(self):
        con = store.connect()
        now = int(time.time())
        for args in ((2, 60, 5), (20, 7, 5), (20, 60, 1), (20, 60, 500)):
            with self.assertRaises(ValueError):
                dca.start(con, "Ivan", A, "AAA", *args)
        pid = dca.start(con, "Ivan", A, "AAA", 20, 60, 5, now=now)
        with self.assertRaises(ValueError):
            dca.start(con, "Ivan", A, "AAA", 20, 60, 5)          # one active plan per token
        self.assertEqual(dca.run_once(con, lambda t: {}, now + 60), [])   # no price: waits
        self.assertEqual(dca.plans(con, "Ivan")[0]["n_done"], 0)
        dca.run_once(con, lambda t: {}, now + 3600)                     # still none after 30 min: skipped
        self.assertEqual(dca.plans(con, "Ivan")[0]["next_ts"], now + 3600)
        with self.assertRaises(ValueError):
            dca.stop(con, "Panda", pid)                                  # not hers
        dca.stop(con, "Ivan", pid)
        self.assertEqual(dca.plans(con, "Ivan"), [])

    def test_page_and_form(self):
        league.market = lambda mints: {m: (2.0, 1e6, None, 2e6) for m in mints}
        league._symbol = lambda token: "AAA"
        league._suggestions = lambda qs: []
        loc = league.post("/natjecanje/dca/start", {"token": A, "amount": "25", "every": "60", "n": "4"}, "Ivan")
        self.assertIn("ok=", loc)
        loc = league.post("/natjecanje/dca/start", {"token": A, "amount": "25", "every": "60", "n": "4"}, "Ivan")
        self.assertIn("err=", loc)
        self.assertIn("err=", league.post("/natjecanje/dca/start", {"token": A}, None))
        con = store.connect()
        dca.run_once(con, lambda t: {A: (2.0, 1e6, None, 2e6, "AAA")})
        con.close()
        title, html = league.page({}, "Ivan")
        self.assertIn("Automatski DCA", html)
        self.assertIn("obavljeno 1 od 4", html)
        self.assertIn("Zaustavi", html)
        con = store.connect()
        pid = dca.plans(con, "Ivan")[0]["id"]
        con.close()
        self.assertIn("ok=", league.post("/natjecanje/dca/stop", {"id": str(pid)}, "Ivan"))


if __name__ == "__main__":
    unittest.main()
