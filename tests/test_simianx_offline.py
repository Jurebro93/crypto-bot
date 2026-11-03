"""SimianX second opinion + demo book + real-trade feed (fake API, temp DBs, no network).

    python3 -m unittest tests.test_simianx_offline
"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dugo import store as dstore  # noqa: E402
from league import simianx_feed, store as lstore  # noqa: E402
from simianx import client, run, store  # noqa: E402

NOW = time.time()
FART, MEME_BTC, SOL = "FartMint111", "MemeBtcMint", run.SOL_MINT


def decision_run(side="long", action="open", entry=0.12, stop=0.108, target=0.15, conf=0.7):
    return {"id": "r1", "status": "done", "points": 1.2,
            "results": {"indicator": {"say": "Graf: bikovski"}, "decision": {"say": "Odluka: kupi"}},
            "analyses": [{"agent": "decision", "conclusion": {"decision": {
                "side": side, "action": action, "entry_price": entry, "stop_loss": stop, "take_profit": target,
                "confidence": conf, "reasoning": "test"}}}]}


class FakeApi:
    SEARCH_GAP_S = 0
    Error = client.Error

    def __init__(self, run_=None):
        self.run, self.quick_calls = run_ or decision_run(), []

    def key(self):
        return "k"

    def points_left(self):
        return 20.0

    def search(self, sym):
        return [{"symbol": sym}] if sym in ("FARTCOIN", "BTC") else []

    def last_close(self, sym, tf="1D"):
        return {"FARTCOIN": 0.119, "BTC": 77000.0}[sym]

    def quick(self, sym, tf, tier):
        self.quick_calls.append(sym)
        return self.run

    parse = staticmethod(client.parse)


class SimianX(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.dcon = dstore.connect(os.path.join(d, "dugo.db"))
        day = int(NOW) // 86400 * 86400
        for i, (m, sym, px) in enumerate([(FART, "Fartcoin ", 0.12), (MEME_BTC, "BTC", 0.003), ("X", "NOPE", 1.0)]):
            self.dcon.execute("INSERT INTO tokens (mint, symbol, name) VALUES (?,?,?)", (m, sym, sym))
            self.dcon.execute("INSERT INTO snap (day, mint, kind, score, rank, price) VALUES (?,?,?,?,?,?)",
                              (day, m, "dugorocni", 90 - i, i + 1, px))
        self.dcon.commit()
        self.con = store.connect(os.path.join(d, "simianx.db"))
        self.px = {FART: 0.12, MEME_BTC: 0.003, SOL: 150.0}

    def tearDown(self):
        self.tmp.cleanup()

    def once(self, api, now=NOW):
        return run.once(self.con, run.config(), now, api, self.dcon, lambda mints: dict(self.px))

    def test_parse_real_no_trade(self):
        op = client.parse(decision_run(side="flat", action="no_trade", entry=None, stop=None, target=None, conf=0.78))
        self.assertEqual(op["view"], "wait")
        self.assertEqual(op["confidence"], 0.78)

    def test_ticker_clash_is_skipped_and_long_opens_demo_and_signal(self):
        api = FakeApi()
        r = self.once(api)
        self.assertEqual(api.quick_calls, ["FARTCOIN"])            # meme "BTC" never gets Bitcoin's analysis
        self.assertEqual(r["reads"], 1)
        self.assertEqual(r["opened"], 1)
        bad = self.con.execute("SELECT ok, note FROM instruments WHERE mint=?", (MEME_BTC,)).fetchone()
        self.assertEqual(bad["ok"], 0)
        self.assertIn("drugi token", bad["note"])
        b = self.con.execute("SELECT * FROM book").fetchone()
        self.assertAlmostEqual(b["stop_pct"], -0.10, places=3)
        self.assertAlmostEqual(b["target_pct"], 0.25, places=3)
        self.assertAlmostEqual(b["stop_px"], 0.108, places=6)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM signals").fetchone()[0], 1)
        # fresh opinion: next pass does not spend points on it again
        self.once(api, NOW + 3600)
        self.assertEqual(api.quick_calls, ["FARTCOIN"])

    def test_book_closes_at_stop(self):
        self.once(FakeApi())
        self.px[FART] = 0.10
        run.book_step(self.con, run.config(), NOW + 60, self.px)
        b = self.con.execute("SELECT * FROM book").fetchone()
        self.assertIn("stop", b["reason"])

    def test_daily_budget_stops_reads(self):
        cfg = run.config()
        day = int(NOW) // 86400 * 86400
        self.con.execute("INSERT INTO opinions (mint, ts, points) VALUES ('old', ?, ?)", (day + 1, cfg["daily_points"]))
        self.con.commit()
        api = FakeApi()
        self.once(api)
        self.assertEqual(api.quick_calls, [])

    def test_short_or_wait_opens_nothing(self):
        r = self.once(FakeApi(decision_run(side="short", entry=0.12, stop=0.13, target=0.1)))
        self.assertEqual(r["opened"], 0)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM signals").fetchone()[0], 0)

    def test_free_plan_empty_answer_is_not_an_opinion(self):
        api = FakeApi({"id": "r2", "status": "done", "points": 0.0, "analyses": [],
                       "results": {"decision": {"say": "Decision on FARTCOIN (1D): wait, no position."}}})
        r = self.once(api)
        self.assertEqual(r["reads"], 0)
        self.assertIsNone(self.con.execute("SELECT 1 FROM opinions").fetchone())
        i = self.con.execute("SELECT ok, note FROM instruments WHERE mint=?", (FART,)).fetchone()
        self.assertEqual(i["ok"], 0)
        self.assertIn("Free plan", i["note"])

    def test_no_key_does_nothing(self):
        api = FakeApi()
        api.key = lambda: ""
        self.assertEqual(self.once(api), {"skipped": "no key"})


class Feed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self._db = lstore.DB
        lstore.DB = os.path.join(d, "league.db")
        self.lcon = lstore.connect()
        self.sx = store.connect(os.path.join(d, "simianx.db"))
        self.sx.execute("INSERT INTO signals (opinion_id, mint, symbol, ts, stop_pct, target_pct) VALUES (1,?,?,?,?,?)",
                        (FART, "FARTCOIN", int(NOW) - 60, -0.1, 0.25))
        self.sx.commit()
        self.market = lambda toks: {FART: (0.12, 500000.0, None, 120e6)}

    def tearDown(self):
        lstore.DB = self._db
        self.tmp.cleanup()

    def test_switch_off_buys_nothing(self):
        self.assertEqual(simianx_feed.run_once(self.lcon, self.market, NOW, on=False, sx_con=self.sx), [])
        self.assertIsNone(self.lcon.execute("SELECT 1 FROM trades").fetchone())

    def test_switch_on_buys_once_with_tpsl(self):
        from trade import settings
        out = simianx_feed.run_once(self.lcon, self.market, NOW, on=True, sx_con=self.sx)
        self.assertEqual(len(out), 1)
        t = self.lcon.execute("SELECT * FROM trades").fetchone()
        self.assertEqual(t["user"], settings.LEAGUE_USER)
        self.assertEqual(t["source"], "simianx")
        a = json.loads(t["auto"])
        self.assertEqual(a["mode"], "tpsl")
        self.assertAlmostEqual(a["tp_px"], 0.15, places=6)
        self.assertAlmostEqual(a["sl_px"], 0.108, places=6)
        self.assertEqual(simianx_feed.run_once(self.lcon, self.market, NOW + 20, on=True, sx_con=self.sx), [])
        self.assertEqual(self.lcon.execute("SELECT COUNT(*) FROM trades").fetchone()[0], 1)

    def test_old_signal_is_ignored(self):
        self.assertEqual(simianx_feed.run_once(self.lcon, self.market, NOW + 7200, on=True, sx_con=self.sx), [])


if __name__ == "__main__":
    unittest.main()
