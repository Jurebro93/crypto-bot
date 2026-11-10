"""API calls go where a winner can be (9.11., Jure): snapshots only for tokens with a real call, Helius wallet
histories only for wallets seen in a role worth copying."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kol import snap, store as kstore  # noqa: E402
from wallets import store as wstore  # noqa: E402

NOW = 1_800_000_000


class Snapshots(unittest.TestCase):
    def test_only_tokens_with_a_real_call(self):
        con = kstore.connect(os.path.join(tempfile.mkdtemp(), "kol.db"))
        con.executemany("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES (?,?,?,?,?)", [
            ("1", "CALLED", "ansem", NOW - 3600, "call"), ("2", "BOTONLY", "scanner", NOW - 3600, "bot"),
            ("3", "SWAPONLY", "w:abc123", NOW - 3600, "buy"), ("4", "KOLBUY", "ansem", NOW - 3600, "buy"),
            ("5", "BOTCALL", "scannerbot", NOW - 3600, "call"), ("6", "OLD", "ansem", NOW - 30 * 3600, "call")])
        con.execute("INSERT INTO kols (handle, bot) VALUES ('scannerbot', 1)")
        con.commit()
        self.assertEqual(sorted(snap.tokens_to_watch(con, NOW)), ["CALLED", "KOLBUY"])


class WalletQueue(unittest.TestCase):
    def test_first_look_needs_a_strong_sighting_and_rechecks_need_a_tier(self):
        con = wstore.connect(os.path.join(tempfile.mkdtemp(), "w.db"))
        wstore.observe(con, "HOLDER", "T", "rug", "holder", NOW - 100)          # seen only as a holder: no credits
        wstore.observe(con, "EARLY", "T", "harvest", "early_buyer", NOW - 100)  # first look
        wstore.observe(con, "BIG", "T", "dugo", "big_holder", NOW - 100)
        for w, tier in (("TIER_C", "C"), ("TIER_A", "A")):
            wstore.observe(con, w, "T", "harvest", "early_buyer", NOW - 10 * 86400)
            con.execute("UPDATE wallets SET scored_at=?, tier=?, next_check=? WHERE wallet=?", (NOW - 8 * 86400, tier, NOW - 10, w))
        wstore.observe(con, "TIER_C2", "T", "harvest", "early_buyer", NOW - 10 * 86400)
        con.execute("UPDATE wallets SET scored_at=?, tier='C', next_check=? WHERE wallet='TIER_C2'", (NOW - 8 * 86400, NOW - 10))
        wstore.observe(con, "TIER_C2", "T2", "harvest", "smart", NOW - 100)     # new strong sighting after the score
        con.commit()
        got = {w for w, _ in wstore.queue(con, 50, NOW)}
        self.assertEqual(got, {"EARLY", "TIER_A", "TIER_C2"})


class GeckoReservation(unittest.TestCase):
    def test_other_processes_get_none_while_reserved(self):
        from unittest import mock
        from event_calendar import http
        d = tempfile.mkdtemp()
        url = "https://api.geckoterminal.com/api/v2/networks/solana/pools/x/ohlcv/minute"
        with mock.patch.object(http, "GATE_DIR", d), mock.patch.object(http, "CACHE_DIR", os.path.join(d, "c")):
            self.assertEqual(http.reserved_by_other(url), 0.0)
            http.reserve(url, 60)
            self.assertEqual(http.reserved_by_other(url), 0.0)           # ours: we may call
            # another process holds it
            with open(os.path.join(d, "geckoterminal.com.reserved"), "w") as f:
                f.write(f"{__import__('time').time() + 60} {os.getpid() + 1}")
            self.assertGreater(http.reserved_by_other(url), 50)
            self.assertGreater(http.cooling(url), 50)
            with mock.patch.object(http, "_fetch", side_effect=AssertionError("no network call while reserved")):
                self.assertIsNone(http.get_json(url, {"a": 1}, ttl=0))
            http.release(url)                                            # not ours: stays
            self.assertGreater(http.reserved_by_other(url), 50)
            with open(os.path.join(d, "geckoterminal.com.reserved"), "w") as f:
                f.write(f"{__import__('time').time() + 60} {os.getpid()}")
            http.release(url)
            self.assertEqual(http.reserved_by_other(url), 0.0)


class TimelineFocus(unittest.TestCase):
    def test_accounts_without_data_are_read_weekly(self):
        import json
        from kol import collect
        con = kstore.connect(os.path.join(tempfile.mkdtemp(), "kol.db"))
        DAY = 86400
        for h, measured in (("rich", 25), ("poor", 3), ("fresh", 0)):
            con.execute("INSERT INTO kols (handle, score, followers, stats) VALUES (?,?,?,?)", (h, 50, 10000, json.dumps({"measured": measured})))
            con.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES (?,?,?,?,?)", (h + "1", "T" + h, h, NOW - 5 * DAY, "call"))
        collect._searched(con, "tl:rich", "timeline_kol", NOW - 2 * DAY)   # both read two days ago
        collect._searched(con, "tl:poor", "timeline_kol", NOW - 2 * DAY)
        con.commit()
        cfg = {"timeline": {"every_h": 0.5, "kols": 10, "max_items": 60, "min_calls": 1, "min_followers": 5000,
                            "refresh_d": 1, "core": 0, "per_query": 25, "min_measured": 10, "low_refresh_d": 7}}
        got = collect.timeline_handles(con, cfg, NOW)
        self.assertIn("rich", got)        # has data, refresh every day
        self.assertIn("fresh", got)       # never read: one first look
        self.assertNotIn("poor", got)     # 3 measured calls, read 2 days ago: waits a week
        self.assertIn("poor", collect.timeline_handles(con, cfg, NOW + 6 * DAY))


class FrozenStrategies(unittest.TestCase):
    def test_four_strategies_take_no_new_entries(self):
        import json
        cfg = json.load(open(os.path.join(ROOT, "strat", "config.json")))
        frozen = {s["key"] for s in cfg["strategies"] if s.get("frozen")}
        # 9.11. (Jure, "isključi strategije koje troše API, a nisu profitabilne"): insajderi (−45,7 %, ispod kontrole)
        # i ekipa (0 ulaza u 4 dana uz plaćeno čitanje reakcija) pridružene zamrznutima
        self.assertEqual(frozen, {"sumnjivi_socijali", "alat_mali", "ozbiljan_projekt", "top_novcanici", "insajderi", "ekipa"})
        from strat import run
        w = run.wanted({"novcanici": [("T", NOW, "W", 0)], "sumnjivi": [("T", NOW, "x", 0)], "alat": [("T", NOW, "a", 0)]},
                       cfg, NOW, 0)
        for k in frozen:
            self.assertEqual(w.get(k, []), [])


if __name__ == "__main__":
    unittest.main()


class CopyWake(unittest.TestCase):
    def test_wake_file_and_nap(self):
        import time
        from unittest import mock
        from league import auto, copy
        d = tempfile.mkdtemp()
        with mock.patch.object(copy, "WAKE", os.path.join(d, ".copy_wake")):
            t0 = time.time()
            self.assertFalse(copy.woke_since(t0))
            copy.wake()
            self.assertTrue(copy.woke_since(t0 - 1))
            t1 = time.time()
            t = time.time()
            auto._nap(2)                       # nothing new since t: sleeps the full 2 s
            self.assertGreaterEqual(time.time() - t, 1.9)
            import threading
            threading.Timer(0.3, copy.wake).start()
            t = time.time()
            auto._nap(10)                      # woken by the file within ~1 s
            self.assertLess(time.time() - t, 3)

    def test_live_feed_mirror_wakes_the_copy(self):
        import sqlite3
        from unittest import mock
        from live import store as lstore
        from league import copy
        con = sqlite3.connect(":memory:")
        rows = [("s1", "MINT", "W1", "buy", 1.0, 100.0, 0.01, 50, "pump", 1000, 100.0)]
        with mock.patch.object(copy, "wake") as w:
            lstore.mirror_chain(con, rows, {"W1"})
            w.assert_called_once()
        with mock.patch.object(copy, "wake") as w:
            lstore.mirror_chain(con, rows, {"OTHER"})
            w.assert_not_called()


class RealTradePage(unittest.TestCase):
    def test_sections_get_the_tap_toggle_script(self):
        from ui import pravitrade
        self.assertIn("details.ap-sec,details.ap-it", pravitrade.TOGGLE_JS)
        # 10.11. (Jure: "nek su sve zatvorene kartice za početak"): open rows are kept only while the page is open
        self.assertNotIn("sessionStorage", pravitrade.TOGGLE_JS)
        self.assertTrue(pravitrade._with_toggle("<p>x</p>").endswith("</script>"))
