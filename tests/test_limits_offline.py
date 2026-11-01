"""01.11.2026: Apify pace brake and the shared GeckoTerminal gate (429s on the Dugoročni page)."""
import io
import os
import sys
import tempfile
import time
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from event_calendar import http  # noqa: E402
from hype import apify  # noqa: E402

D = 86400


class ApifyBrake(unittest.TestCase):
    def test_pace_factor(self):
        cfg = {"monthly_reserve_usd": 3, "daily_usd": {"a": 2.0, "b": 2.0}}
        now = 1_000_000
        # $35 of $100 used, 10 days left: $6.2/day allowed > $4 planned -> no brake
        self.assertEqual(apify.pace_factor(cfg, 35, 100, now + 10 * D, now), 1.0)
        # $85 used, 10 days left: $1.2/day allowed of $4 planned -> 30%
        self.assertAlmostEqual(apify.pace_factor(cfg, 85, 100, now + 10 * D, now), 0.3)
        self.assertEqual(apify.pace_factor(cfg, 99, 100, now + 10 * D, now), 0.0)
        self.assertEqual(apify.pace_factor(cfg, 50, 0, 0, now), 1.0)       # no account data: no brake

    def test_brake_spares_kol_sources(self):
        cfg = apify.config()
        self.assertIn("kol_monitor", cfg["bez_kocnice"])
        self.assertIn("kol_timeline", cfg["bez_kocnice"])
        with mock.patch.object(apify, "monthly", return_value=(90.0, 100.0)), \
                mock.patch.object(apify, "spent", return_value=0.2), \
                mock.patch.dict(apify._month, {"end": time.time() + 9 * D}):
            with self.assertRaises(apify.BudgetExceeded):
                apify.check("x_buzz")          # $0.2 today is over its braked share
            apify.check("kol_monitor")         # KOL tracking (and the KOL test) keeps going


class GeckoGate(unittest.TestCase):
    def setUp(self):
        self.orig = http.GATE_DIR
        http.GATE_DIR = tempfile.mkdtemp()
        self.addCleanup(setattr, http, "GATE_DIR", self.orig)

    def test_calls_queue_and_429_pauses_everyone(self):
        url = "https://api.geckoterminal.com/api/v2/networks/solana/pools/x"
        self.assertEqual(http.cooling(url), 0)
        self.assertEqual(http.cooling("https://api.dexscreener.com/x"), 0)
        http.limited(url, 0)
        self.assertGreater(http.cooling(url), 50)

    def test_dugo_gives_way_quietly(self):
        from dugo import sources
        url = sources.GECKO + "/pools/p/ohlcv/day"
        http.limited(url, 0)
        with mock.patch.object(http, "_fetch") as f:
            with self.assertRaises(sources.GeckoBusy):
                sources.candles("p", 0)
            f.assert_not_called()             # paused: no call at all, so no new 429

    def test_429_marks_the_gate(self):
        from dugo import sources
        err = urllib.error.HTTPError(sources.GECKO, 429, "Too Many Requests", {}, io.BytesIO(b""))
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(sources.GeckoBusy):
                sources.candles("p", 0)
        self.assertGreater(http.cooling(sources.GECKO), 0)


if __name__ == "__main__":
    unittest.main()
