"""Živi prijedlozi na Autopilotu (ui/zivo.py, 9.11., Jure): candidates through every slow filter, then live numbers
every 2 s; a token stays only while it trades now; order = what moved last; expectation for +15 %."""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import zivo  # noqa: E402

NOW = int(time.time())
A, B, C, D = ("4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi", "8qbHbw2BbbTHBW1sbeqakYXVKRQM8Ne7pLK7m6CVfeR",
              "CktRuQ2mttgRGkXJtyksdKHjUdc2C4TgDzyB98oEzy8", "GgBaCs3NCBuZN12kCJgAW63ydqohFkHEdfdEXBPzLHq")


def live(mcap=120_000, ch_m5=2.0, ch_h1=5.0, vol_h1=8_000.0, txns_h1=60, liq=50_000.0):
    return {"price": 0.001, "liq": liq, "mcap": float(mcap), "vol_h1": vol_h1, "vol_h24": 50_000.0, "txns_h1": txns_h1,
            "buys_h1": 30, "txns_h24": 500, "vol_m5": 900.0, "txns_m5": 7, "ch_m5": ch_m5, "ch_h1": ch_h1, "ch_h24": 20.0}


class Candidates(unittest.TestCase):
    def test_slow_filters(self):
        src = [{"token": A, "symbol": "AAA", "src": "alat", "ts0": NOW - 600, "mcap0": 100_000, "why": ["#1 alata"]},
               {"token": A, "symbol": "AAA", "src": "zovu", "ts0": NOW - 100, "mcap0": 100_000, "why": ["dup"]},   # once
               {"token": "x47c8f3a2b1c9d4e5f6a7b8c9d0e1f2a3b4c5d6a396", "symbol": "EVM", "src": "zovu", "ts0": NOW, "mcap0": 1e6, "why": []},
               {"token": B, "symbol": "COINx", "src": "zovu", "ts0": NOW, "mcap0": 5e6, "why": []},               # xStock
               {"token": C, "symbol": "SMALL", "src": "prijedlog", "ts0": NOW - 60, "mcap0": 12_000, "why": []},   # under 30k
               {"token": D, "symbol": "OLD", "src": "prijedlog", "ts0": NOW - 8 * 3600, "mcap0": 90_000, "why": []}]  # stale
        out = zivo.candidates(NOW, sources=src)
        self.assertEqual([c["token"] for c in out], [A])
        self.assertEqual(out[0]["src"], "alat")


class Rows(unittest.TestCase):
    def test_live_gate_order_and_expectation(self):
        cands = [{"token": A, "symbol": "AAA", "src": "alat", "ts0": NOW - 3600, "mcap0": 100_000, "why": ["#1 alata"]},
                 {"token": B, "symbol": "BBB", "src": "zovu", "ts0": NOW - 300, "mcap0": 150_000, "why": ["zovu: ansem"]},
                 {"token": C, "symbol": "CCC", "src": "prijedlog", "ts0": NOW - 900, "mcap0": 80_000, "why": ["prijedlog"]},
                 {"token": D, "symbol": "DDD", "src": "konvergencija", "ts0": NOW - 100, "mcap0": 60_000, "why": ["konv"]}]
        lv = {A: live(), B: live(mcap=150_000, ch_m5=12.0), C: live(txns_h1=3), D: live(ch_h1=-35.0)}   # C dead now, D falling
        callers = {B: ["ansem", "tg:alpha"]}
        smart = {A: 1}
        mstats = {"ansem": {"n": 6, "hit15": 0.5, "hit10": 0.6, "sl": 0.2}}
        chances = {"100–300k": (0.42, 300), "30–100k": (0.3, 100)}
        rs = zivo.rows(NOW, cands=cands, live=lv, callers=callers, smart=smart, mstats=mstats, chances=chances)
        self.assertEqual([r["token"] for r in rs], [B, A])                 # dead and falling tokens are gone
        self.assertEqual(rs[0]["reasons"], ["novi pozivatelji u 10 min: @ansem, alpha"])   # $900 in 5 min is below the move bar
        self.assertEqual(rs[1]["reasons"], ["1 pametnih novčanika kupilo u 10 min"])
        # a token with nothing fresh (no caller, no smart buy, no 5-min move) is not a suggestion, however good its tier
        stale = zivo.rows(NOW, cands=[cands[0]], live={A: live()}, callers={}, smart={}, mstats={}, chances=chances)
        self.assertEqual(stale, [])
        moving = zivo.rows(NOW, cands=[cands[0]], live={A: {**live(ch_m5=9.0), "vol_m5": 2500.0, "txns_m5": 12}}, callers={}, smart={},
                           mstats={}, chances=chances)
        self.assertEqual(moving[0]["reasons"], ["+9 % u 5 min na $2,500 (12 tx)"])
        self.assertEqual(rs[0]["callers10"], ["ansem", "tg:alpha"])
        self.assertIn("pozivatelji: +15 % prije stopa u 50%", rs[0]["expect"])   # from the minute check
        self.assertEqual(rs[1]["smart10"], 1)
        self.assertIn("42% sličnih tokena", rs[1]["expect"])              # band chance when callers have no minute data
        self.assertGreater(rs[0]["heat"], rs[1]["heat"])
        self.assertEqual(zivo.rows(NOW, cands=cands, live=None), [])      # DexScreener down: nothing

    def test_expectation_text(self):
        self.assertEqual(zivo.expectation([], {}, None), ("još bez mjerenja", None))
        self.assertEqual(zivo.expectation(["x"], {"x": {"n": 4, "hit15": 0.25}}, None)[1], 0.25)


if __name__ == "__main__":
    unittest.main()
