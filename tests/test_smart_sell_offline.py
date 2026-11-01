"""1.11. pairless follow-up: bad DexScreener prices, Smart sell explosion rule, "?" marks on the competition chart,
the big-wins box.

    python3 -m unittest tests.test_smart_sell_offline
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dexscreener import client  # noqa: E402
from paper import sim  # noqa: E402


class Sanity(unittest.TestCase):
    def setUp(self):
        client._LAST.clear()

    def test_pairless_reading_is_rejected(self):
        p = {"pairAddress": "P1", "priceUsd": "0.001108", "marketCap": 1075101, "liquidity": {"usd": 407687},
             "volume": {"h1": 5379, "h6": 968653, "h24": 968653}, "priceChange": {"h1": 6654}}
        q = client.sane(dict(p))
        self.assertIn("prometa", q["sumnjivo"])
        self.assertLess(float(q["priceUsd"]), 0.00002)  # real trades were at 0.000014
        self.assertLess(q["marketCap"], 20_000)

    def test_jump_without_volume_keeps_last_good_price(self):
        base = {"pairAddress": "P2", "liquidity": {"usd": 20_000}, "volume": {"h1": 3_000}, "priceChange": {"h1": 5}}
        client.sane({**base, "priceUsd": "0.00001", "marketCap": 10_000}, now=1000)
        q = client.sane({**base, "priceUsd": "0.0005", "marketCap": 500_000}, now=1900)
        self.assertEqual(float(q["priceUsd"]), 0.00001)
        self.assertTrue(q.get("sumnjivo"))

    def test_real_pump_passes(self):
        base = {"pairAddress": "P3", "liquidity": {"usd": 20_000}, "priceChange": {"h1": 400}}
        client.sane({**base, "priceUsd": "0.00001", "volume": {"h1": 3_000}}, now=1000)
        q = client.sane({**base, "priceUsd": "0.00005", "volume": {"h1": 250_000}}, now=1900)
        self.assertEqual(float(q["priceUsd"]), 0.00005)
        self.assertNotIn("sumnjivo", q)


class Boom(unittest.TestCase):
    CFG = {"fee": 0.01, "sl": -0.3, "tp": [[1.0, 0.3]], "trail_after": 5, "trail": 0.5, "max_hold_h": 24,
           "rug_liq": 0.2, "size_usd": 10, "boom": [3.0, 15, 0.5]}

    def test_explosion_sells_half_on_the_spot(self):
        pos = sim.open_position(1.0, 1e9, 0, 10, self.CFG)
        sim.step(pos, 1.1, 1e9, 60, self.CFG)
        sim.step(pos, 4.0, 1e9, 120, self.CFG)  # x3.6 within two minutes
        reasons = [f["reason"] for f in pos["fills"]]
        self.assertEqual(reasons[0], "smart_sell_eksplozija")
        self.assertAlmostEqual(pos["fills"][0]["frac"], 0.5)
        self.assertIn("take_profit_1x", reasons)  # the ladder still runs on the rest
        sim.step(pos, 4.2, 1e9, 180, self.CFG)
        self.assertEqual(sum(r == "smart_sell_eksplozija" for r in [f["reason"] for f in pos["fills"]]), 1)

    def test_slow_climb_is_not_an_explosion(self):
        pos = sim.open_position(1.0, 1e9, 0, 10, self.CFG)
        for i, px in enumerate([1.3, 1.7, 2.2, 2.9, 3.6]):
            sim.step(pos, px, 1e9, (i + 1) * 1200, self.CFG)  # 20 min apart
        self.assertNotIn("smart_sell_eksplozija", [f["reason"] for f in pos["fills"]])


class Jumps(unittest.TestCase):
    def test_spike_that_reverts_is_called_a_bad_price(self):
        from league import history
        tmp = tempfile.mkdtemp()
        con = sqlite3.connect(os.path.join(tmp, "league.db"))
        con.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, user TEXT, status TEXT)")
        history._ensure(con)
        rows = [(0, 1600, {"pairless": 50}), (900, 8000, {"pairless": 6450}), (1800, 1650, {"pairless": 95}),
                (2700, 1660, {"pairless": 100})]
        for ts, e, d in rows:
            con.execute("INSERT INTO equity (ts, user, equity, open, detail) VALUES (?,?,?,?,?)",
                        (ts, "Jure", e, 1, json.dumps(d)))
        js = history.jumps(con)
        self.assertEqual(len(js), 1)  # the drop back is explained by the same mark
        self.assertTrue(js[0]["bad"])
        self.assertIn("pairless", js[0]["text"])
        self.assertIn("DexScreenera", js[0]["text"])


class Wins(unittest.TestCase):
    def test_collect_with_peak(self):
        from ui import wins
        tmp = tempfile.mkdtemp()
        p = sqlite3.connect(os.path.join(tmp, "paper.db"))
        p.execute("CREATE TABLE trades (symbol, token, ret, pnl_usd, max_ret, closed_ts, state, status)")
        p.execute("INSERT INTO trades VALUES ('ANSEM', 'A', 2.1, 42, 5.6, 2000000000, '{}', 'closed')")
        p.execute("INSERT INTO trades VALUES ('SMALL', 'S', 0.1, 2, 0.2, 2000000000, '{}', 'closed')")
        p.commit()
        lg = sqlite3.connect(os.path.join(tmp, "league.db"))
        lg.execute("CREATE TABLE trades (user, symbol, token, ret, pnl_usd, closed_ts, entry_px, exit_px, peak_px, status)")
        lg.execute("INSERT INTO trades VALUES ('Ivan', 'XX', 'X1', 1.0, 50, 2000000000, 1.0, 2.0, 3.0, 'closed')")
        lg.commit()
        ws = wins.collect(7, 5, os.path.join(tmp, "paper.db"), os.path.join(tmp, "league.db"), now=2000000100)
        self.assertEqual([w["symbol"] for w in ws], ["XX", "ANSEM"])
        self.assertAlmostEqual(ws[0]["peak"], 2.0)
        self.assertAlmostEqual(ws[1]["peak"], 5.6)


if __name__ == "__main__":
    unittest.main()
