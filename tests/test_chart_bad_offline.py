"""6.11.: a bad price reading (Filip's ZEC spike to $2.3M) must not be drawn in the account chart line."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import leaguedash  # noqa: E402


class ChartBad(unittest.TestCase):
    def test_spike_left_out_marker_on_real_value(self):
        d = {"users": ["Filip"], "now": 1000, "bot": None, "rekts": [],
             "players": [{"user": "Filip", "pts": [(100, 1019.0), (200, 2317343.0), (300, 1020.0)]}],
             "jumps": [{"ts": 200, "user": "Filip", "before": 1019.0, "after": 2317343.0, "text": "ZEC", "bad": True}]}
        c = leaguedash.chart_data(d)
        self.assertEqual([p[1] for p in c["series"][0]["pts"]], [1019.0, 1020.0])
        self.assertEqual(c["ev"][0]["v"], 1019.0)
        self.assertTrue(c["ev"][0]["bad"])
        self.assertIn("touchstart", leaguedash.JS)


if __name__ == "__main__":
    unittest.main()
