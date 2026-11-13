"""The shared GeckoTerminal gap learns the real limit (event_calendar/http, 9.11.): a 429 widens it, successes
narrow it back, every process reads the same value from the gate file."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from event_calendar import http  # noqa: E402

URL = "https://api.geckoterminal.com/api/v2/networks/solana/pools/x/ohlcv/minute"


class Gap(unittest.TestCase):
    def test_grows_on_429_and_eases_on_success(self):
        d = tempfile.mkdtemp()
        with mock.patch.object(http, "GATE_DIR", d):
            base = http.current_gap(URL)
            self.assertEqual(base, http.SHARED_GAP["geckoterminal.com"])
            http.limited(URL, 0)
            self.assertAlmostEqual(http.current_gap(URL), base * 1.5, places=3)
            http.limited(URL, 0)
            self.assertAlmostEqual(http.current_gap(URL), base * 2.25, places=3)
            for _ in range(200):
                http.limited(URL, 0)
            self.assertEqual(http.current_gap(URL), http.GAP_MAX)
            for _ in range(400):
                http.eased(URL)
            self.assertEqual(http.current_gap(URL), base)          # never below the default
            self.assertEqual(http.current_gap("https://api.dexscreener.com/x"), 0.0)

    def test_pacing_uses_the_learned_gap(self):
        d = tempfile.mkdtemp()
        with mock.patch.object(http, "GATE_DIR", d):
            http.limited(URL, 0)
            http._gate("geckoterminal.com", lambda s: [0.0, 0.0, s[2]])   # clear the pause, keep the learned gap
            slept = []
            with mock.patch.object(http.time, "sleep", slept.append):
                http._pace_shared(URL)
                http._pace_shared(URL)
            self.assertTrue(slept and abs(slept[-1] - http.current_gap(URL)) < 0.5)


if __name__ == "__main__":
    unittest.main()
