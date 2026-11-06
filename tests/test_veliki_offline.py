"""6.11. (Jure): tokens over $1M are scored and compared; strategies judged by '≥ +15 % in X of Y'. No network."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strat import run as srun  # noqa: E402


class Veliki(unittest.TestCase):
    def test_srednji_and_veliki_take_fresh_scored_tokens(self):
        cfg = srun.load_config()
        now = 1_800_000_000
        ms = srun._paper_min_score()
        src = {"alat": [("A", now - 60, "demo bot kupio", 1)],
               "scored": [("B", now - 60, "ocjena 80", ms + 30), ("C", now - 60, "ocjena 10", 10),
                          ("D", now - 7200, "ocjena 90", ms + 40)]}
        w = srun.wanted(src, cfg, now, 0)
        self.assertEqual([e[0] for e in w["alat_veliki"]], ["B"])      # scored, fresh, above the threshold
        self.assertEqual([e[0] for e in w["alat_srednji"]], ["B"])
        self.assertEqual([e[0] for e in w["alat_mali"]], ["A"])        # the small band still copies the demo bot

    def test_exits_for_big_tokens(self):
        cfg = srun.load_config()
        ex = {"sl": -0.35, "stale_min": 45, "tp": [[1.0, 0.5]], "max_hold_h": 24}
        self.assertEqual(srun.exits_for(cfg, ex, 120_000), ex)
        big = srun.exits_for(cfg, ex, 2_500_000)
        self.assertIsNone(big["stale_min"])
        self.assertEqual(big["sl"], -0.2)
        self.assertEqual(big["tp"][0][0], 0.15)

    def test_scan_default_ceiling_and_masovno_source(self):
        import run_hype
        from learn import masovno
        src = open(run_hype.__file__).read()
        self.assertIn('default=500e6', src)
        self.assertIn("_majors", src)
        self.assertIn("veliki", masovno.SOURCES)


if __name__ == "__main__":
    unittest.main()
