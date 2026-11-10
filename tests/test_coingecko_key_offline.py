"""10.11. (Jure kupio CoinGecko plaćeni API): with COINGECKO_API_KEY set, every GeckoTerminal URL goes to CoinGecko's
paid on-chain API (same paths and JSON) with the key in a header, paced at CG_GAP and never reserved by one job;
without the key nothing changes.

    python3 -m unittest tests.test_coingecko_key_offline
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from event_calendar import http  # noqa: E402

GT = "https://api.geckoterminal.com/api/v2/networks/solana/pools/P1/ohlcv/minute?limit=60"


class Route(unittest.TestCase):
    def setUp(self):
        self._env = {k: os.environ.get(k) for k in ("COINGECKO_API_KEY", "COINGECKO_DEMO", "CG_GAP", "CG_DAILY_CALLS",
                                                    "DATA_DIR")}
        for k in self._env:
            os.environ.pop(k, None)
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self._gate = http.GATE_DIR
        http.GATE_DIR = self._tmp.name

    def tearDown(self):
        http.GATE_DIR = self._gate
        self._tmp.cleanup()
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_the_day_count_survives_a_deploy_on_the_persistent_disk(self):
        """10.11. (Jure: "postavljen je, što se ne koristi?"): the count lived in /tmp, which a deploy empties."""
        import tempfile
        disk = tempfile.mkdtemp()
        os.environ["DATA_DIR"] = disk
        os.environ["COINGECKO_API_KEY"] = "CG-test"
        os.environ["CG_DAILY_CALLS"] = "5"
        for _ in range(3):
            self.assertTrue(http._cg_take())
        http.GATE_DIR = tempfile.mkdtemp()            # a new container: /tmp is empty
        self.assertEqual(http.cg_used()[0], 3)        # the disk still knows today's 3
        self.assertTrue(http._cg_take())
        self.assertTrue(http._cg_take())
        self.assertFalse(http._cg_take())             # the cap holds across the "deploy"
        self.assertTrue(os.path.exists(os.path.join(disk, "coingecko.day")))

    def test_without_key_nothing_changes(self):
        self.assertEqual(http._cg_route(GT, None), (GT, None))
        self.assertEqual(http._shared(GT)[0], "geckoterminal.com")

    def test_paid_key_goes_to_pro_api_with_the_header(self):
        os.environ["COINGECKO_API_KEY"] = "CG-test"
        url, h = http._cg_route(GT, {"Accept": "application/json"})
        self.assertEqual(url, "https://pro-api.coingecko.com/api/v3/onchain/networks/solana/pools/P1/ohlcv/minute?limit=60")
        self.assertEqual(h["x-cg-pro-api-key"], "CG-test")
        self.assertEqual(h["Accept"], "application/json")
        self.assertEqual(http._shared(GT), ("coingecko.com", 0.25))      # 240 a minute, both host names one gate
        self.assertEqual(http._shared(url)[0], "coingecko.com")
        self.assertEqual(http.reserved_by_other(GT), 0.0)
        self.assertEqual(http._cg_route("https://api.dexscreener.com/x", None), ("https://api.dexscreener.com/x", None))

    def test_daily_budget_then_the_free_api_until_midnight(self):
        os.environ.update(COINGECKO_API_KEY="CG-test", CG_DAILY_CALLS="2")
        self.assertTrue(http._cg_route(GT, None)[0].startswith("https://pro-api.coingecko.com"))
        self.assertTrue(http._cg_route(GT, None)[0].startswith("https://pro-api.coingecko.com"))
        self.assertEqual(http.cg_used()[0], 2)
        self.assertEqual(http._cg_route(GT, None), (GT, None))                 # budget spent: free GeckoTerminal
        self.assertEqual(http._shared(GT)[0], "geckoterminal.com")             # ... at the free pace
        self.assertEqual(http.cg_used(today="2099-01-01")[0], 0)               # a new day starts at 0

    def test_demo_key(self):
        os.environ.update(COINGECKO_API_KEY="CG-demo", COINGECKO_DEMO="1")
        url, h = http._cg_route(GT, None)
        self.assertTrue(url.startswith("https://api.coingecko.com/api/v3/onchain/networks/solana/"))
        self.assertEqual(h, {"x-cg-demo-api-key": "CG-demo"})


if __name__ == "__main__":
    unittest.main()
