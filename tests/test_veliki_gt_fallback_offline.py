"""15.11. navečer (coordinator, production 11:45 UTC: every veliki backtest variant n=0, the 1h candles never arrived -
GeckoTerminal 429): offline, no network.

  - a refused GeckoTerminal call (429, another job's reservation) waits on the limiter and tries again instead of
    giving the pass up; it stops at GT_TRIES or at the pass deadline
  - veliki has the CoinGecko key's priority (CG_PRIORITY); the midcap collector does not
  - our own 15m bars (veliki/live's DexScreener polls) become c15 / c1h candles where GeckoTerminal has none; a
    GeckoTerminal candle is never overwritten by ours and replaces ours when it arrives
  - the candle top-up asks for the top tokens' 1h first
  - without a backtest-picked rule veliki/live uses the documented default rule and says so once an hour
  - "once --ako-nema-pravila" does nothing while a rule exists

    python3 -m unittest tests.test_veliki_gt_fallback_offline
"""
import os
import sqlite3
import sys
import tempfile
import time
import unittest
import urllib.error
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from event_calendar import http  # noqa: E402
from kol import measure  # noqa: E402
from veliki import live, store, walk  # noqa: E402

NOW = 1_790_000_000 // 3600 * 3600


class GtPatience(unittest.TestCase):
    def setUp(self):
        store.GT_STATS.update(ok=0, refused=0, waited_s=0.0)
        store.DEADLINE[0] = 0.0

    def _run(self, answers, tries=4):
        calls = []

        def get_json(url, params=None, **kw):
            calls.append(url)
            a = answers.pop(0)
            if isinstance(a, Exception):
                raise a
            return a
        ok = {"data": {"attributes": {"ohlcv_list": [[NOW, 1, 2, 0.5, 1.5, 10]]}}}
        answers = [ok if a == "ok" else a for a in answers]
        with mock.patch.object(http, "get_json", get_json), mock.patch.object(http, "cooling", lambda u: 3.0), \
                mock.patch.object(store.time, "sleep") as sl, mock.patch.object(store, "GT_TRIES", tries), \
                mock.patch.dict(store.FETCH, {}, clear=True), mock.patch.object(measure._GT, "wait", lambda: None):
            out = store.gt_ohlcv("POOL", "hour", 1, NOW + 3600, 10)
        return out, calls, sl

    def test_429_then_answer(self):
        e429 = urllib.error.HTTPError("u", 429, "Too Many", {}, None)
        out, calls, sl = self._run([e429, None, "ok"])
        self.assertEqual(out, [(NOW, 1.0, 2.0, 0.5, 1.5, 10.0)])
        self.assertEqual(len(calls), 3)
        self.assertEqual(sl.call_count, 2)
        self.assertEqual(store.GT_STATS["refused"], 2)

    def test_gives_up_after_tries(self):
        out, calls, _sl = self._run([None, None, None, None], tries=4)
        self.assertIsNone(out)
        self.assertEqual(len(calls), 4)

    def test_deadline_stops_waiting(self):
        store.DEADLINE[0] = time.monotonic() + 1.0   # the next wait (>= 5 s) would pass the deadline
        out, calls, sl = self._run([None, "ok"])
        self.assertIsNone(out)
        self.assertEqual(len(calls), 1)
        sl.assert_not_called()

    def test_priority(self):
        self.assertIn("veliki", http.CG_PRIORITY)
        self.assertNotIn("midcap", http.CG_PRIORITY)   # the collector leaves the end of every hour's slice to veliki
        ok, _why = http.cg_allow({"n": 2990 * 0 + int(3000 * 0.99 / 24), "jobs": {}}, "veliki", 3600 * 0 + 10, cap=3000)
        self.assertTrue(ok)   # inside the hour's slice a priority job may spend it all


class OwnBars(unittest.TestCase):
    def test_merge_keeps_gt_and_fills_gaps(self):
        with tempfile.TemporaryDirectory() as d:
            con = store.connect(os.path.join(d, "v.db"))
            h0 = NOW - 3 * 3600
            store.put_candles(con, "c1h", "T", [(h0, 1.0, 1.1, 0.9, 1.05, 500.0)])   # GeckoTerminal's hour
            own = {"T": [(h0 + i * 900, 1.0 + i / 100, 1.02 + i / 100, 0.99 + i / 100, 1.01 + i / 100)
                         for i in range(12)]}   # three hours of 15m bars
            n15, n1h = store.merge_own_bars(con, own, NOW)
            self.assertEqual(n15, 12)
            self.assertEqual(n1h, 2)   # the GT hour stays GT's
            rows = store.candles(con, "c1h", "T")
            self.assertEqual(rows[0], (h0, 1.0, 1.1, 0.9, 1.05, 500.0))
            self.assertAlmostEqual(rows[1][1], 1.04)   # the first 15m open of the second hour
            self.assertAlmostEqual(rows[1][4], 1.08)   # its last close
            store.put_candles(con, "c1h", "T", [(h0 + 3600, 2.0, 2.0, 2.0, 2.0, 9.0)])   # GT arrives later
            self.assertEqual(store.candles(con, "c1h", "T")[1], (h0 + 3600, 2.0, 2.0, 2.0, 2.0, 9.0))
            con.close()

    def test_incomplete_hour_not_written(self):
        with tempfile.TemporaryDirectory() as d:
            con = store.connect(os.path.join(d, "v.db"))
            own = {"T": [(NOW + i * 900, 1, 1, 1, 1) for i in range(2)]}   # the current hour, in progress
            n15, n1h = store.merge_own_bars(con, own, NOW + 1900)
            self.assertEqual((n15, n1h), (2, 0))
            con.close()

    def test_top_up_order_1h_first(self):
        seen = []
        rows = [{"mint": f"M{i}", "pool": f"P{i}"} for i in range(3)]
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(store, "fill", lambda con, m, p, now, b, tables: seen.append((m, tables[0])) or 1), \
                mock.patch.object(store, "own_bars", lambda toks, since: {}):
            con = store.connect(os.path.join(d, "v.db"))
            used = walk.top_up(con, rows, [], NOW, budget=4, log=lambda s: None)
            con.close()
        self.assertEqual(used, 4)
        self.assertEqual(seen, [("M0", "c1h"), ("M1", "c1h"), ("M2", "c1h"), ("M0", "c1d")])


class DefaultRule(unittest.TestCase):
    def test_default_without_backtest(self):
        with mock.patch.object(store, "live_rule", lambda path=None: None):
            c = live.cfg_now()
        self.assertTrue(c["default"])
        self.assertEqual((c["tp"], c["trail"], c["time_h"], c["look_d"], c["stop_pct"]), (8.0, 0.05, 72, 7, 0.20))

    def test_picked_rule_wins(self):
        with mock.patch.object(store, "live_rule", lambda path=None: {"tp": 15.0, "trail": 0.0, "time_h": 168,
                                                                         "look_d": 14}):
            c = live.cfg_now()
        self.assertFalse(c["default"])
        self.assertEqual((c["tp"], c["time_h"], c["look_d"]), (15.0, 168, 14))

    def test_once_retry_flag(self):
        import run_veliki
        with mock.patch.object(store, "live_rule", lambda path=None: {"tp": 8.0}), \
                mock.patch.object(store, "last", lambda path=None: (None, None)), \
                mock.patch.object(walk, "run") as run:
            self.assertEqual(run_veliki.main(["once", "--ako-nema-pravila"]), 0)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
