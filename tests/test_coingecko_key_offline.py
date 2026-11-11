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
                                                    "DATA_DIR", "CG_NIGHT_SHARE")}
        for k in self._env:
            os.environ.pop(k, None)
        os.environ["CG_NIGHT_SHARE"] = "1"   # the night cap has its own test; the others must not depend on the clock
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self._gate = http.GATE_DIR
        http.GATE_DIR = self._tmp.name
        from usage import meter   # 11.11.: the key's calls are tallied in usage.db; never the repository's one
        self._usage = meter.DB
        meter.flush()            # what earlier tests tallied goes to the old DB, not into this test's counts
        meter.DB = os.path.join(self._tmp.name, "usage.db")

    def tearDown(self):
        from usage import meter
        meter._tally.clear()
        meter.DB = self._usage
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

    def test_key_calls_are_tallied_per_script_and_kind(self):
        """11.11. (Jure: "javi koliko od 3.000 dnevno trošimo"): the day was gone by 02:38 UTC; usage.db now says who."""
        import io
        import tempfile
        from contextlib import redirect_stdout
        from unittest import mock
        from usage import meter
        os.environ.update(COINGECKO_API_KEY="CG-test", CG_DAILY_CALLS="3")
        self.assertEqual(http._cg_kind(GT), "ohlcv")
        self.assertEqual(http._cg_kind("https://api.geckoterminal.com/api/v2/networks/solana/trending_pools?page=1"),
                         "trending_pools")
        self.assertEqual(http._cg_kind("https://api.geckoterminal.com/api/v2/networks/solana/tokens/M1/info"), "tokens")
        db = os.path.join(tempfile.mkdtemp(), "usage.db")
        out = io.StringIO()
        with mock.patch.object(meter, "DB", db), mock.patch.object(meter, "SCRIPT", "run_dugo.py"), redirect_stdout(out):
            for _ in range(3):
                http._cg_route(GT, None)
            self.assertEqual(http.cg_by_script(), [("run_dugo.py", 3)])
        self.assertIn("coingecko: 3 poziva danas od 3 (po skripti: run_dugo.py 3), ključ potrošen u", out.getvalue())
        con = meter.connect(db)
        self.assertEqual(con.execute("SELECT method, calls FROM usage WHERE service=?", (http.CG_TALLY,)).fetchall(),
                         [("ohlcv", 3)])
        con.close()

    def test_night_jobs_get_at_most_40_percent_of_the_day(self):
        """11.11. (Jure: "3000 poziva potrošeno do 02:38 UTC noćnim poslovima -> noćni batch najviše 40 % dnevnog
        budžeta, ostatak za range listu i dnevne runde")."""
        import calendar
        from unittest import mock
        utc = lambda *a: calendar.timegm((2026, 11, 11, *a, 0, 0, 0))   # noqa: E731
        self.assertTrue(http.cg_night(utc(1, 30)))       # 02:30 Zagreb
        self.assertTrue(http.cg_night(utc(4, 59)))       # 05:59 Zagreb
        self.assertFalse(http.cg_night(utc(5, 0)))       # 06:00 Zagreb: the day
        self.assertFalse(http.cg_night(utc(23, 30)))     # 00:30 Zagreb, still the previous paid day
        os.environ.update(COINGECKO_API_KEY="CG-test", CG_DAILY_CALLS="10", CG_NIGHT_SHARE="0.4")
        self.assertEqual(http.cg_night_cap(), 4)
        with mock.patch.object(http, "cg_night", lambda now=None: True):
            self.assertEqual(http.cg_limit(), 4)
            for _ in range(4):
                self.assertTrue(http._cg_route(GT, None)[0].startswith("https://pro-api.coingecko.com"))
            self.assertEqual(http._cg_route(GT, None), (GT, None))            # the night share is spent: free GT
            self.assertEqual(http.cg_key(), "")
            self.assertEqual(http._shared(GT)[0], "geckoterminal.com")         # ... at the free pace
        with mock.patch.object(http, "cg_night", lambda now=None: False):
            self.assertEqual(http.cg_key(), "CG-test")                         # the day: the other 60 %
            for _ in range(6):
                self.assertTrue(http._cg_route(GT, None)[0].startswith("https://pro-api.coingecko.com"))
            self.assertEqual(http._cg_route(GT, None), (GT, None))
        self.assertEqual(http.cg_used()[0], 10)


if __name__ == "__main__":
    unittest.main()
