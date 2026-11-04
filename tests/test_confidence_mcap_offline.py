"""4.11.: a tiny token cannot show 'visoka' confidence just because it has signals (90% of <$20k tokens rug).

    python3 -m unittest tests.test_confidence_mcap_offline
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import confidence  # noqa: E402


class SmallMcap(unittest.TestCase):
    def test_same_signals_three_sizes(self):
        f = {"telegram": 0.7}
        kw = dict(hype=80, features=f, rug_verdict="PROLAZI", liquidity=15000)
        big, _ = confidence.score(mcap=250_000, **kw)
        mid, _ = confidence.score(mcap=40_000, **kw)
        tiny, parts = confidence.score(mcap=7_600, **kw)
        self.assertGreaterEqual(big, 55)                      # visoka, as before
        self.assertEqual((mid, tiny), (big - 15, big - 30))
        self.assertLess(tiny, 35)                             # niska
        self.assertTrue(any("Premali" in t for _, t in parts))

    def test_learned_model_cannot_undo_the_guard(self):
        old = confidence._MODEL.copy()
        confidence._MODEL.update({"ts": 9e12, "m": {"bias": 1.0, "hype": 1.0, "coef": {}, "base": {"*": 0.3}}})
        try:
            hi, _ = confidence.score(hype=60, features={}, mcap=250_000)
            lo, _ = confidence.score(hype=60, features={}, mcap=7_600)
        finally:
            confidence._MODEL.update(old)
        self.assertEqual(lo, max(0, hi - 30))


if __name__ == "__main__":
    unittest.main()
