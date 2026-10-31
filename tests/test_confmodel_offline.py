"""Learned confidence against a synthetic hype.db (no network)."""
import json
import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learn import confmodel, store, weights  # noqa: E402
from tiers import store as tstore  # noqa: E402
from ui import confidence  # noqa: E402

NOW = 1_800_000_000
CFG = {"horizon_h": 24, "min_rows": 200, "max_step": 0.2, "min_weight_floor": 5, "skok_pct": 85, "skok_window_d": 30,
       "min_class_rows": 20, "skok_init": {"moonshot": 2.0, "rizican": 1.0, "event": 0.5, "stabilni": 0.3}, "rollback_runs": 2}


def seed(con, n=400, rnd=None):
    """n tokens over 20 days; smart money makes a skok 6x likelier, low liquidity cuts it to 0.3x, hype is noise."""
    rnd = rnd or random.Random(7)
    for i in range(n):
        t = f"T{i:04d}"
        ts = NOW - 20 * 86400 + i * (20 * 86400 // n)
        smart = rnd.random() < 0.3
        low_liq = rnd.random() < 0.4
        p_hit = 0.05 * (6 if smart else 1) * (0.3 if low_liq else 1)
        hit = rnd.random() < p_hit
        feats = {"fresh": rnd.random(), "turnover": rnd.random(), "smart_money": 0.5 if smart else 0.0}
        hype = 20 + 40 * rnd.random()
        liq = 5_000 if low_liq else 50_000
        con.execute("INSERT OR REPLACE INTO hype_signals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (ts, t, t, t, "pair", "url", hype, 1.0, 300_000, liq, json.dumps(feats), "boost", "{}"))
        con.execute("INSERT OR REPLACE INTO hype_details VALUES (?,?,?)",
                    (t, ts, json.dumps({"smart_buyers": ["w1", "w2"] if smart else []})))
        peak = 3.0 if hit else 1.0 + 0.2 * rnd.random()
        for h in range(1, 25):
            price = 1.0 + (peak - 1.0) * min(1.0, h / 6) if hit else 1.0 + (peak - 1.0) * rnd.random()
            con.execute("INSERT OR REPLACE INTO hype_snapshots VALUES (?,?,?,?,?)", (t, ts + h * 3600, price, 300_000 * price, liq))
        tstore.upsert(con, t, ts, klasa="rizican", razina=1, t0="prolaz", score=hype)
    con.commit()


class ConfModel(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.dir.name, "hype.db")
        tstore.connect(self.db).close()
        self.con = store.connect(self.db)
        self.con.executescript(__import__("hype.store", fromlist=["SCHEMA"]).SCHEMA)
        self.learned = os.path.join(self.dir.name, "learned")
        self._old = weights.LEARNED_DIR
        weights.LEARNED_DIR = self.learned
        confidence._MODEL.update(ts=0, m=None)

    def tearDown(self):
        weights.LEARNED_DIR = self._old
        confidence._MODEL.update(ts=0, m=None)
        self.con.close()
        self.dir.cleanup()

    def test_keyed_parts_and_hand_total_match_old_behaviour(self):
        parts = confidence.parts_keyed(40, {"smart_money": 0.5}, {"pumpfun": {"top10HoldersPercent": 60}}, "PROLAZI", None, 20_000, 50_000)
        keys = {k for k, _, _ in parts}
        self.assertEqual(keys, {"hype", "smart_money", "rug_ok", "holders_conc"})
        self.assertEqual(confidence.hand_total(parts), 44)          # 24 + 10 + 10 + 0: concentration no longer costs 10
        self.assertEqual(confidence.score(None, {}, {}, "ODBAČEN")[0], 0)

    def test_dataset_fit_apply(self):
        seed(self.con)
        rows, thr = confmodel.dataset(self.con, CFG, NOW)
        self.assertGreaterEqual(len(rows), 350)
        self.assertTrue(any("smart_money" in r["keys"] for r in rows))
        self.assertTrue(any("liq_low" in r["keys"] for r in rows))
        model = confmodel.fit(rows)
        self.assertGreater(model["coef"]["smart_money"], 0.5)
        self.assertLess(model["coef"]["liq_low"], -0.2)
        with_smart = confmodel.apply(model, [("hype", 24, ""), ("smart_money", 10, "")], 40, "rizican")
        without = confmodel.apply(model, [("hype", 24, "")], 40, "rizican")
        self.assertGreater(with_smart[0], without[0])
        self.assertGreater(with_smart[1]["smart_money"], 0)      # the points say what the fact adds
        # an average token of its class sits around 50
        avg = sum(confmodel.conf_of(model, r) for r in rows) / len(rows)
        self.assertTrue(35 < avg < 65, avg)

    def test_run_guard_and_apply(self):
        seed(self.con, n=120)
        rec = confmodel.run(self.con, CFG, NOW)
        self.assertFalse(rec["applied"])
        self.assertIn("premalo", rec["note"])
        self.assertIsNone(confmodel.load())
        seed(self.con, n=400)
        rec = confmodel.run(self.con, CFG, NOW + 60)  # learn_runs keys on (ts, klasa)
        self.assertTrue(rec["applied"], rec["note"])
        self.assertGreater(rec["metric_new"], rec["metric_old"])
        m = confmodel.load()
        self.assertEqual(m["n"], rec["n"])
        runs = store.runs(self.con, "confidence")
        self.assertEqual(len(runs), 2)
        # ui.confidence now uses the model and reports class-relative numbers
        c_smart, parts = confidence.score(40, {"smart_money": 0.5}, {"smart_buyers": ["w"]}, None, None, 50_000, 300_000, klasa="rizican")
        c_plain, _ = confidence.score(40, {}, {}, None, None, 5_000, 300_000, klasa="rizican")
        self.assertGreater(c_smart, c_plain)
        self.assertTrue(any(p > 0 and "smart" in t for p, t in parts))
        cal = confmodel.calibration(confmodel.dataset(self.con, CFG, NOW + 60)[0], lambda r: confmodel.conf_of(m, r))
        self.assertTrue(cal)
        rates = [h for _, n, h in cal if n >= 20]
        self.assertGreaterEqual(rates[-1], rates[0])


if __name__ == "__main__":
    unittest.main()
