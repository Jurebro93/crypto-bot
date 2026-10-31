"""Offline tests for paper/auto.py: the daily review applies safe entry-rule changes itself, with guardrails."""
import os
import shutil
import tempfile
import unittest
from unittest import mock

from learn import weights
from paper import auto, review, sim

DAY = 86400
T0 = 1_800_000_000


def rep(*sugg):
    return {"suggestions": list(sugg)}


class Auto(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old = weights.LEARNED_DIR
        weights.LEARNED_DIR = self.tmp
        self.cfg = sim.load_config(learned=False)

    def tearDown(self):
        weights.LEARNED_DIR = self._old
        shutil.rmtree(self.tmp)

    def test_applies_with_enough_tokens_and_overlays_config(self):
        out = auto.apply(rep({"change": {"min_score": 55}, "n": 40, "text": "Najmanja ocjena za ulaz 50 → 55."}),
                         self.cfg, [], now=T0)
        self.assertEqual(out[0]["kind"], "primijenjeno")
        self.assertIn("Bot je promijenio", out[0]["text"])
        self.assertNotIn(".json", out[0]["text"])
        self.assertEqual(sim.load_config()["min_score"], 55)
        self.assertEqual(sim.load_config(learned=False)["min_score"], self.cfg["min_score"])

    def test_waits_with_few_tokens(self):
        out = auto.apply(rep({"change": {"min_score": 55}, "n": 12, "text": "x"}), self.cfg, [], now=T0)
        self.assertEqual(out[0]["kind"], "čeka")
        self.assertEqual(sim.load_config()["min_score"], self.cfg["min_score"])

    def test_step_is_capped_and_one_change_per_day(self):
        out = auto.apply(rep({"change": {"min_score": self.cfg["min_score"] + 30}, "n": 50, "text": "x"},
                             {"change": {"min_liq": 5000}, "n": 50, "text": "y"}), self.cfg, [], now=T0)
        self.assertEqual(sim.load_config()["min_score"], self.cfg["min_score"] + auto.MAX_SCORE_STEP)
        self.assertEqual([o["kind"] for o in out], ["primijenjeno", "čeka"])

    def test_exit_changes_left_to_exit_learning(self):
        out = auto.apply(rep({"change": {"sl": -0.2}, "n": 50, "text": "x"}), self.cfg, [], now=T0)
        self.assertEqual(out[0]["kind"], "info")
        self.assertEqual(sim.load_config()["sl"], self.cfg["sl"])

    def test_rollback_when_new_rules_lose_on_new_tokens(self):
        auto.apply(rep({"change": {"min_score": 60}, "n": 40, "text": "x"}), self.cfg, [], now=T0)
        cfg = sim.load_config()
        rows = [{"ts": T0 + 3600 + i, "origin": "hype", "score": 55, "liquidity": 1e6, "mcap": 1e5, "verdict": None}
                for i in range(auto.ROLLBACK_MIN_N)]

        def fake_pnl(rs, c):
            return {"n": len(rs), "pnl": 10.0 * len(rs), "win": 0, "avg": 0}  # old rules (min 50) take them all
        with mock.patch.object(review, "pnl", fake_pnl):
            out = auto.apply(rep(), cfg, rows, now=T0 + DAY)
        self.assertEqual(out[0]["kind"], "vraćeno")
        self.assertEqual(sim.load_config()["min_score"], self.cfg["min_score"])
        self.assertTrue(os.path.exists(auto.path()))


if __name__ == "__main__":
    unittest.main()
