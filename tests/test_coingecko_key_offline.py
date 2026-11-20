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
        # 11.11.: the key is spent by the UTC hour (cap x (h + 1) / 24) and the live jobs come first: these tests
        # check the day's budget, so they run as the minute loop at 23:30 UTC, when the whole day's cap is open
        import time as _t
        from unittest import mock
        t = _t.time()
        self._p = mock.patch.object(http, "_now", return_value=t - t % 86400 + 23 * 3600 + 1800)
        self._p.start()
        http.set_cg_job("minute")

    def tearDown(self):
        self._p.stop()
        http.set_cg_job(None)
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


class Plan(unittest.TestCase):
    """20.11.: the day budget from CoinGecko's own GET /key (plan, monthly credit, remaining), read at most every 6 h."""
    NOV1 = 1793534400          # 2026-11-01 12:00 UTC: 30 days left in the month, today included
    NOV20 = 1795176000         # 2026-11-20 12:00 UTC: 11 days left

    def setUp(self):
        import calendar
        import tempfile
        self.assertEqual(calendar.timegm((2026, 11, 1, 12, 0, 0)), self.NOV1)
        self.assertEqual(calendar.timegm((2026, 11, 20, 12, 0, 0)), self.NOV20)
        self._env = {k: os.environ.get(k) for k in ("COINGECKO_API_KEY", "COINGECKO_DEMO", "CG_DAILY_CALLS", "DATA_DIR")}
        for k in self._env:
            os.environ.pop(k, None)
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

    def info(self, credit, remaining, ts, **kw):
        return {"plan": "X", "credit": credit, "remaining": remaining, "used": credit - remaining, "ts": ts,
                "day": http._day(ts), **kw}

    def test_cap_formula(self):
        f = http.cg_cap_from
        self.assertEqual(f(self.info(100_000, 100_000, self.NOV1), self.NOV1), 3000)          # Basic: the floor
        self.assertEqual(f(self.info(500_000, 500_000, self.NOV1), self.NOV1), 14_516)        # Analyst: 0.9 x 500k / 31
        self.assertEqual(f(self.info(500_000, 413_000, self.NOV20), self.NOV20), 14_516)      # on pace: the plan part
        # nearly used up: (40,000 - 5 % of 500k) / 11 days left
        self.assertEqual(f(self.info(500_000, 40_000, self.NOV20), self.NOV20), 1_363)
        self.assertEqual(f(self.info(500_000, 20_000, self.NOV20), self.NOV20), 0)            # inside the reserve
        # the day's calls spent before the reading are in "remaining" already: added back the same day only
        self.assertEqual(f(self.info(500_000, 40_000, self.NOV20, n_at=500), self.NOV20 + 3600), 1_863)
        self.assertEqual(f(self.info(500_000, 40_000, self.NOV20 - 86400, n_at=500), self.NOV20), 1_363)
        self.assertEqual(f(None, self.NOV20), 3000)                                             # no reading
        self.assertEqual(f({"ts": self.NOV20, "plan": "X"}, self.NOV20), 3000)                 # no credit figure
        self.assertEqual(f(self.info(500_000, 500_000, self.NOV20 - 40 * 3600), self.NOV20), 3000)   # too old
        dec1 = self.NOV1 + 30 * 86400                                                          # 1.12.: November's
        self.assertEqual(f(self.info(500_000, 1_000, dec1 - 13 * 3600), dec1), 14_516)          # remaining is not ours

    def test_env_wins_and_no_reading_is_3000(self):
        http._cg_account_save(self.info(500_000, 500_000, self.NOV1))
        self.assertEqual(http.cg_cap(self.NOV1), 14_516)
        os.environ["CG_DAILY_CALLS"] = "2500"
        self.assertEqual(http.cg_cap(self.NOV1), 2500)
        os.environ.pop("CG_DAILY_CALLS")
        os.remove(http._cg_account_file())
        self.assertEqual(http.cg_cap(self.NOV1), 3000)

    def test_read_at_most_every_6h_counted_and_never_raises(self):
        calls = []

        def ok(url, headers):
            calls.append((url, sorted(headers)))
            return {"plan": "Analyst", "rate_limit_request_per_minute": 500, "monthly_call_credit": 500000,
                    "current_total_monthly_calls": 87412, "current_remaining_monthly_calls": 412588}
        self.assertIsNone(http.cg_account(self.NOV20, fetch=ok))                 # no key: no call
        os.environ["COINGECKO_API_KEY"] = "CG-secret"
        os.environ["COINGECKO_DEMO"] = "1"
        self.assertIsNone(http.cg_account(self.NOV20, fetch=ok))                 # a demo key has no /key
        os.environ.pop("COINGECKO_DEMO")
        d = http.cg_account(self.NOV20, fetch=ok)
        self.assertEqual(calls, [("https://pro-api.coingecko.com/api/v3/key", ["x-cg-pro-api-key"])])
        self.assertEqual((d["plan"], d["credit"], d["used"], d["remaining"], d["rate"]),
                         ("Analyst", 500000, 87412, 412588, 500))
        self.assertEqual(http._cg_read(self.NOV20)["jobs"], {"racun": 1})      # the one call is counted
        http.cg_account(self.NOV20 + 5 * 3600, fetch=ok)
        self.assertEqual(len(calls), 1)                                          # not again within 6 h
        self.assertEqual(http.cg_cap(self.NOV20), 14_516)
        line = http.cg_account_line(self.NOV20)
        self.assertIn("coingecko račun: plan Analyst, ovaj mjesec 87.412 od 500.000 poziva, 500/min", line)
        self.assertIn("dnevni strop 14.516 (iz plana)", line)
        self.assertNotIn("CG-secret", line)

        def boom(url, headers):
            raise OSError("down")
        d = http.cg_account(self.NOV20 + 7 * 3600, fetch=boom)                  # fails: the old reading stays
        self.assertEqual(d["plan"], "Analyst")
        self.assertEqual(d["err"], "OSError")
        os.remove(http._cg_account_file())
        self.assertIsNone(http.cg_account(self.NOV20 + 14 * 3600, fetch=boom))
        self.assertIsNone(http.cg_account(self.NOV20 + 21 * 3600, fetch=lambda u, h: ["?"]))   # odd answer
        self.assertEqual(http.cg_cap(self.NOV20 + 21 * 3600), 3000)
        self.assertIn("nije očitan (nepoznat odgovor)", http.cg_account_line(self.NOV20 + 21 * 3600))
        with open(http._cg_account_file(), "w") as f:                           # a broken file
            f.write("{nope")
        self.assertIsNone(http.cg_account(self.NOV20 + 21 * 3600, fetch=boom))
        self.assertEqual(http.cg_cap(self.NOV20 + 21 * 3600), 3000)

    def test_hour_line_appends_the_account_only_when_asked(self):
        os.environ["COINGECKO_API_KEY"] = "CG-secret"
        http._cg_account_save(dict(self.info(500_000, 412_588, self.NOV20), plan="Analyst", rate=500,
                                   tried=self.NOV20))
        self.assertNotIn("račun", http.cg_hour_line(self.NOV20))
        self.assertIn("coingecko račun: plan Analyst", http.cg_hour_line(self.NOV20 + 60, account=True))


if __name__ == "__main__":
    unittest.main()
