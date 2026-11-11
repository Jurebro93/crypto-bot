"""11.11. (Jure: "razina MC $50 je ispod 30k ... a MC je 149k"): a bare number in "Kupi na MC" means thousands."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import pravitrade  # noqa: E402


class KupiNaMc(unittest.TestCase):
    def test_bare_numbers_are_thousands(self):
        self.assertEqual(pravitrade._dca_level("50", 149_000), 50_000)
        self.assertEqual(pravitrade._dca_level("150", 149_000), 150_000)
        self.assertEqual(pravitrade._dca_level("$50k", 149_000), 50_000)
        self.assertEqual(pravitrade._dca_level("50000", 149_000), 50_000)
        self.assertEqual(pravitrade._dca_level("1.2m", 149_000), 1_200_000)
        self.assertAlmostEqual(pravitrade._dca_level("-40%", 149_000), 89_400)


if __name__ == "__main__":
    unittest.main()
