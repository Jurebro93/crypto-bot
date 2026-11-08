"""Only numbers are features (8.11.2026): masovno stored the wallet address and None kol_scores in shadow points and
the 6-hourly weight fit crashed on them; the KOL round runs its cheap, important steps first."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hype import evaluate  # noqa: E402
from learn import shadow  # noqa: E402


class ShadowFeatures(unittest.TestCase):
    def test_text_and_none_are_dropped(self):
        path = os.path.join(tempfile.mkdtemp(), "shadow.db")
        con = shadow.connect(path)
        con.execute("INSERT INTO points (id, token, point, ts, features, status, hit, max2_ret) VALUES "
                    "('p1', 'T', 'novcanik_kupio', 1000, ?, 'gotovo', 1, 0.2)",
                    (json.dumps({"novcanik": "9pQQc1xy", "kol_score": None, "liq": 0.4, "ok": True, "n": 3}),))
        con.commit(); con.close()
        rows = shadow.rows(path)
        self.assertEqual(rows[0]["features"], {"liq": 0.4, "n": 3})


class FitWeights(unittest.TestCase):
    def test_fit_survives_text_features(self):
        rows = []
        for i in range(60):
            hit = i % 3 == 0
            rows.append({"features": {"a": 1.0 if hit else 0.2, "b": 0.5, "novcanik": "abc", "kol_score": None},
                         "hit": hit, "ts": i})
        fit = evaluate.fit_weights(rows, epochs=20)
        self.assertIsNotNone(fit)
        self.assertNotIn("novcanik", fit["weights"])
        self.assertNotIn("kol_score", fit["weights"])
        self.assertGreater(fit["weights"]["a"], 0)


class KolCycleOrder(unittest.TestCase):
    def test_webhook_before_scoring(self):
        import run_kol
        src = open(os.path.join(ROOT, "run_kol.py")).read()
        steps = src.split("for step in (")[1].split("):")[0]
        names = [s.strip() for s in steps.replace("\n", "").split(",") if s.strip()]
        self.assertLess(names.index("cmd_chain"), names.index("cmd_search"))
        self.assertLess(names.index("cmd_chain"), names.index("cmd_score"))
        self.assertLess(names.index("cmd_converge"), names.index("cmd_score"))
        self.assertTrue(hasattr(run_kol, "cmd_chain"))


class ValidateThrottle(unittest.TestCase):
    def test_validation_runs_every_six_hours_not_every_round(self):
        from kol import score, store as kstore
        con = kstore.connect(os.path.join(tempfile.mkdtemp(), "kol.db"))
        t0 = 1_800_000_000
        self.assertTrue(score.validate_due(con, {}, t0))               # never validated: due
        con.execute("INSERT INTO kv VALUES ('validate_ts', ?)", (str(t0),))
        self.assertFalse(score.validate_due(con, {}, t0 + 5 * 3600))
        self.assertTrue(score.validate_due(con, {}, t0 + 6 * 3600))
        self.assertTrue(score.validate_due(con, {"validate_every_h": 1}, t0 + 3600))


    def test_slow_parts_every_six_hours(self):
        from kol import score, store as kstore
        con = kstore.connect(os.path.join(tempfile.mkdtemp(), "kol.db"))
        t0 = 1_800_000_000
        self.assertTrue(score.slow_due(con, {}, t0))
        score._mark(con, "slow_ts", t0)
        self.assertFalse(score.slow_due(con, {}, t0 + 3 * 3600))
        self.assertTrue(score.slow_due(con, {}, t0 + 6 * 3600))


if __name__ == "__main__":
    unittest.main()
