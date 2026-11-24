"""Apify sources, score normalization and the Radar page's plain-language reasons (no network).

    python3 -m unittest discover -s tests
"""
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hype import score, sources  # noqa: E402
from ui import radar  # noqa: E402

from league import copy as _copy  # noqa: E402

# 9.11. (audit review): ingest_kol_event wakes the copy loop (league/copy.wake); the tests must not touch the repo's .copy_wake
_WAKE = mock.patch.object(_copy, "WAKE", os.path.join(tempfile.mkdtemp(), ".copy_wake"))


def setUpModule():
    _WAKE.start()


def tearDownModule():
    _WAKE.stop()


class SourcesOffline(unittest.TestCase):
    def test_trend_match(self):
        keys = sources.trend_keys([{"trend": "Tusk"}, {"trend": "#GTA6Trailer"}, {"trend": "Happy Friday"},
                                   {"trend": "Sam Altman"}])
        self.assertEqual(sources.trend_match("TUSK", "Tusk", keys), "Tusk")
        self.assertEqual(sources.trend_match("GTA", "GTA6 trailer coin", keys), "#GTA6Trailer")
        self.assertEqual(sources.trend_match("ALTMAN", "x", keys), "Sam Altman")
        self.assertIsNone(sources.trend_match("HAPPY", "Happy cat", keys))  # filler words never match

    def test_gmgn_score(self):
        good = sources.gmgn_score({"winrate_7d": "0.7", "realized_profit_7d": "60000", "pnl_2x_5x_num_7d": 6,
                                   "pnl_gt_5x_num_7d": 1, "txs_7d": 300, "avg_holding_period_7d": 3600})
        bot = sources.gmgn_score({"winrate_7d": "0.9", "realized_profit_7d": "90000", "txs_7d": 9000,
                                  "avg_holding_period_7d": 10, "tags": ["snipe_bot"]})
        self.assertEqual(good["score"], 100)
        self.assertEqual((bot["bot"], bot["score"]), (True, 0))

    def test_kol_webhook(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "h.db")
            n = sources.ingest_kol_event({"event": {"author": {"username": "kol1"}, "text":
                                          "aping $GTA6 4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz"}}, db)
            self.assertEqual(n, 1)
            self.assertEqual(sources.ingest_kol_event({"text": "gm"}, db), 0)
            by_ca, by_tk = sources.kol_counts(sqlite3.connect(db))
        self.assertEqual(by_ca, {"4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz": 1})
        self.assertEqual(by_tk, {"GTA6": 1})

    def test_unmeasured_features_do_not_count(self):
        w = {"turnover": 10, "x_buzz": 10}
        self.assertEqual(score.score({"turnover": 1.0}, w), 100.0)                # X buzz not checked
        self.assertEqual(score.score({"turnover": 1.0, "x_buzz": 0.0}, w), 50.0)  # checked, nobody talks

    def test_radar_reasons_and_risks(self):
        f = {"x_trend": 1.0, "turnover": 1.0, "momentum": 0.5, "paid": 1.0}
        why = radar.reasons(f, {"x_trend": "Tusk"})
        self.assertTrue(why[0].startswith("Ime je upravo trending"))
        self.assertIn("3x ili više", why[1])
        self.assertIn("+100%", why[2])
        risk = radar.risks({"liquidity": 5000, "mcap": 2e6}, {"pumpfun": {"bundlerOwnedPercent": 3000}}, None)
        self.assertEqual(len(risk), 3)  # bundlers 30% (reported x100), thin liquidity, already big


if __name__ == "__main__":
    unittest.main()
