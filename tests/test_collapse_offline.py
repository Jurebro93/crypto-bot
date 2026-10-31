import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rugfilter import collapse  # noqa: E402


class CollapseTest(unittest.TestCase):
    def test_judge(self):
        self.assertIsNone(collapse.judge(45000, 30000, 17000, 12000))       # -33%: a dip, not a rug
        r = collapse.judge(45500, 6600, 17400, 6400)                        # the MAX case: -85%
        self.assertTrue(r and r["drop"] > 0.8 and "srušio" in r["text"])
        self.assertTrue(collapse.judge(40000, 18000, 20000, 5000))          # -55% with liquidity pulled
        self.assertIsNone(collapse.judge(40000, 18000, 20000, 15000))       # -55%, liquidity fine
        self.assertIsNone(collapse.judge(3000, 100))                        # too small to judge
        self.assertIsNone(collapse.judge(40000, 25000, 20000, 1000))        # recovered above half the peak

    def test_peaks_and_live(self):
        d = tempfile.mkdtemp()
        db = os.path.join(d, "hype.db")
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE hype_signals (ts INTEGER, token TEXT, mcap REAL, liquidity REAL)")
        now = int(time.time())
        con.executemany("INSERT INTO hype_signals VALUES (?,?,?,?)",
                        [(now - 600, "A", 79000, 25800), (now - 60, "A", 30000, 15000), (now - 99999, "B", 90000, 30000),
                         (now - 60, "B", 8000, 5000)])
        con.commit()
        con.close()
        pk = collapse.peaks(db, ["A", "B", "C"])
        self.assertIsNone(collapse.check(pk.get("A")))                    # -62% on last scan, liquidity ok
        self.assertTrue(collapse.check(pk.get("A"), 6600, 6400))          # live price shows the dump
        self.assertIsNone(collapse.check(pk.get("B")))                    # its peak is older than 24 h
        self.assertIsNone(collapse.check(pk.get("C"), 100, 100))          # never seen: nothing to compare

    def test_sim_labels_dump_as_rug(self):
        from paper import sim
        cfg = sim.load_config(learned=False)
        t0 = int(time.time())
        pos = sim.open_position(1.0, 20000, t0, 50, cfg)
        sim.step(pos, 0.2, 15000, t0 + 60, cfg)   # -80% in a minute, liquidity still there
        self.assertFalse(pos["open"])
        self.assertEqual(pos["exit_reason"], "rug")
        pos = sim.open_position(1.0, 20000, t0, 50, cfg)
        sim.step(pos, 0.6, 15000, t0 + 60, cfg)   # -40%: an ordinary stop loss
        self.assertEqual(pos["exit_reason"], "stop_loss")

if __name__ == "__main__":
    unittest.main()


class LeagueRugTest(unittest.TestCase):
    def test_buy_refused_and_page_renders(self):
        from league import store
        from ui import data, league
        d = tempfile.mkdtemp()
        store.DB = os.path.join(d, "league.db")
        db = os.path.join(d, "hype.db")
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE hype_signals (ts INTEGER, token TEXT, mcap REAL, liquidity REAL)")
        mint = "So11111111111111111111111111111111111111112"
        con.execute("INSERT INTO hype_signals VALUES (?,?,?,?)", (int(time.time()) - 600, mint, 45500, 17400))
        con.commit()
        con.close()
        old = data.HYPE_DB
        data.HYPE_DB = db
        try:
            league.market = lambda mints: {m: (1e-6, 6400, None, 6600) for m in mints}
            loc = league.post("/natjecanje/buy", {"token": mint, "size": "50", "symbol": "MAX"}, "Jure")
            self.assertIn("err=", loc)
            league.market = lambda mints: {m: (1e-5, 17000, None, 44000) for m in mints}
            self.assertIn("ok=", league.post("/natjecanje/buy", {"token": mint, "size": "50", "symbol": "MAX"}, "Jure"))
            league.market = lambda mints: {m: (1e-6, 6400, None, 6600) for m in mints}
            _, html = league.page({}, "Jure")
            self.assertIn("rugan", html)                            # warning on the open position
        finally:
            data.HYPE_DB = old


class RadarLabelTest(unittest.TestCase):
    def test_label_follows_confidence(self):
        import json
        from hype import store as hstore
        from ui import data, radar
        d = tempfile.mkdtemp()
        db = os.path.join(d, "hype.db")
        con = sqlite3.connect(db)
        con.executescript(hstore.SCHEMA if hasattr(hstore, "SCHEMA") else "")
        cols = [r[1] for r in con.execute("PRAGMA table_info(hype_signals)")]
        if not cols:
            self.skipTest("no hype schema")
        now = int(time.time())
        for tok, sc, liq, mc in (("LOWLIQ", 52, 5500, 6000), ("GOOD", 52, 40000, 90000)):
            con.execute("INSERT INTO hype_signals (ts, token, symbol, score, mcap, liquidity, features) VALUES (?,?,?,?,?,?,?)",
                        (now - 30, tok, tok, sc, mc, liq, json.dumps({})))
        con.commit()
        con.close()
        old = (data.HYPE_DB, dict(data.GROUPS))
        data.HYPE_DB = db
        data.GROUPS["hype"] = [db]
        try:
            _, html = radar.page({})
        finally:
            data.HYPE_DB = old[0]
            data.GROUPS.update(old[1])
        self.assertNotIn("jak kandidat</span>", html.split("Kandidati sada")[1].split("</table>")[0])
        self.assertIn("Confidence", html)
