"""Pulse of retained tokens and the strength features, against a synthetic hype.db (no network)."""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hype import pulse, score  # noqa: E402
from tiers import store as tstore  # noqa: E402

NOW = 1_800_000_000
CFG = {**pulse.DEFAULTS, "holderi_kredita_dan": 0}  # never calls Helius in tests


def pair(vol_h1=10_000, buys=50, sells=40, buys5=5, sells5=4, mcap=80_000):
    return {"priceUsd": "0.0001", "marketCap": mcap, "liquidity": {"usd": 20_000},
            "volume": {"m5": 800, "h1": vol_h1}, "txns": {"m5": {"buys": buys5, "sells": sells5}, "h1": {"buys": buys, "sells": sells}}}


class Pulse(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.dir.name, "hype.db")
        self.con = tstore.connect(self.db)
        pulse.ensure(self.con)

    def tearDown(self):
        self.con.close()
        self.dir.cleanup()

    def test_retained_only_reached_and_not_failed(self):
        tstore.upsert(self.con, "A", NOW - 3600, razina=1, score=70, t0="prolaz")
        tstore.upsert(self.con, "B", NOW - 3600, razina=2, score=90, t0="pad")       # rug mechanics: out
        tstore.upsert(self.con, "C", NOW - 3600, razina=0, score=95, t0="prolaz")    # never reached T1: out
        tstore.upsert(self.con, "D", NOW - 30 * 3600, razina=1, score=99, t0="prolaz")  # too old: out
        tstore.upsert(self.con, "E", NOW - 600, razina=1, score=80, t0="prolaz")
        self.assertEqual(pulse.retained(self.con, CFG, NOW), ["E", "A"])
        self.assertEqual(pulse.retained(self.con, {**CFG, "max": 1}, NOW), ["E"])

    def test_strength_needs_an_hour(self):
        rows = [{"ts": NOW - 600, "vol_h1": 1, "buys_h1": 1, "sells_h1": 1, "buys_m5": 0, "sells_m5": 0, "holders": None},
                {"ts": NOW - 300, "vol_h1": 1, "buys_h1": 1, "sells_h1": 1, "buys_m5": 0, "sells_m5": 0, "holders": None},
                {"ts": NOW, "vol_h1": 1, "buys_h1": 1, "sells_h1": 1, "buys_m5": 0, "sells_m5": 0, "holders": None}]
        self.assertEqual(pulse.strength(rows, NOW), {})

    def test_steady_token_scores_high_fading_token_low(self):
        for i in range(6):  # one reading every 50 min for 5 h, steady volume, holders growing 5 %/h, few txns per holder
            pulse.record(self.con, "S", pair(vol_h1=10_000, buys5=3, sells5=2), NOW - (5 - i) * 3000,
                         holders=int(1000 * (1 + 0.05 * i * 3000 / 3600)), holders_src="helius")
            pulse.record(self.con, "F", pair(vol_h1=max(100, 10_000 - i * 2_500), buys=max(2, 50 - i * 12), sells=40,
                                             buys5=30, sells5=30), NOW - (5 - i) * 3000,
                         holders=1000 + 2 * i, holders_src="helius")
        s = pulse.strength(pulse.series(self.con, "S", 6, NOW), NOW)
        f = pulse.strength(pulse.series(self.con, "F", 6, NOW), NOW)
        self.assertEqual(s["snaga_volumen"], 1.0)
        self.assertEqual(s["snaga_txn"], 1.0)
        self.assertAlmostEqual(s["rast_holdera"], 0.5, places=1)      # 5 %/h of the 10 %/h scale
        self.assertGreater(s["organski"], 0.9)                         # 208 new holders on ~450 txns
        self.assertLess(f["snaga_volumen"], 0.05)
        self.assertLess(f["snaga_txn"], 0.6)
        self.assertLess(f["rast_holdera"], 0.05)
        self.assertLess(f["organski"], 0.15)                           # 10 holders on ~330 txns: churn
        self.assertTrue(all(0 <= v <= 1 for v in list(s.values()) + list(f.values())))
        self.assertIn("volumen drži 100%", pulse.describe(s))
        self.assertEqual(pulse.describe({}), "")

    def test_apply_records_and_sets_features(self):
        for i in range(3):
            pulse.record(self.con, "A", pair(), NOW - (3 - i) * 3000)
        rows = [{"token": "A", "symbol": "A", "features": {"fresh": 1.0}, "raw": pair(), "extra": {}},
                {"token": "Z", "symbol": "Z", "features": {"fresh": 1.0}, "raw": pair(), "extra": {}}]
        n = pulse.apply(self.con, rows, {"A"}, NOW, CFG)
        self.assertEqual(n, 0)  # budget 0: no Helius
        self.assertEqual(rows[0]["features"]["snaga_volumen"], 1.0)
        self.assertEqual(rows[0]["extra"]["puls"]["n"], 4)
        self.assertNotIn("snaga_volumen", rows[1]["features"])  # not retained, not recorded
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM token_pulse WHERE token='Z'").fetchone()[0], 0)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM token_pulse WHERE token='A'").fetchone()[0], 4)
        # pump.fun board holders are a free reading
        rows[0]["extra"]["pumpfun"] = {"holders": 321}
        pulse.apply(self.con, rows, {"A"}, NOW + 120, CFG)
        self.assertEqual(pulse.holders_last(self.con, "A"), (NOW + 120, 321))

    def test_weights_and_score(self):
        w = score.load_weights()
        for k in pulse.FEATURES:
            self.assertGreater(w[k], 0, k)
        base = score.score({"fresh": 0.5, "turnover": 0.5}, w)
        strong = score.score({"fresh": 0.5, "turnover": 0.5, "snaga_volumen": 1, "rast_holdera": 1}, w)
        self.assertGreater(strong, base)

    def test_prune(self):
        pulse.record(self.con, "O", pair(), NOW - 10 * 86400)
        pulse.record(self.con, "N", pair(), NOW)
        self.con.execute("DELETE FROM token_pulse WHERE ts < ?", (NOW - 7 * 86400,))  # prune() uses wall-clock time
        self.assertEqual([r[0] for r in self.con.execute("SELECT token FROM token_pulse")], ["N"])


if __name__ == "__main__":
    unittest.main()
