"""10.11. (audit sekundni S1, S2, S8): the per-second paths of the Autopilot page and the copy loop stop re-reading
whole tables and stop waiting minutes on a slow price source."""
import os
import sqlite3
import tempfile
import time
import unittest
from unittest import mock

from dexscreener import client
from ui import data, prijedlog


class ChancesCache(unittest.TestCase):
    def setUp(self):
        prijedlog._CHANCES.clear()

    def tearDown(self):
        prijedlog._CHANCES.clear()

    def test_second_call_within_ttl_does_not_read_kol_db(self):
        rows = [{"mcap0": 2e5, "max24": 0.5 if i % 2 else 0.1} for i in range(40)]
        calls = []
        with mock.patch("ui.data.q", lambda path, s, args=(): calls.append(s) or rows), \
                mock.patch.object(prijedlog, "_kol_db", lambda: "/x/kol.db"):
            a = prijedlog.chances()
            b = prijedlog.chances()
        self.assertEqual(len(calls), 1)
        self.assertEqual(a, b)
        self.assertAlmostEqual(a["100–300k"][0], 0.5)

    def test_cache_expires_and_empty_answers_are_not_kept(self):
        calls = []
        with mock.patch("ui.data.q", lambda path, s, args=(): calls.append(s) or []), \
                mock.patch.object(prijedlog, "_kol_db", lambda: "/x/kol.db"):
            prijedlog.chances()
            prijedlog.chances()
        self.assertEqual(len(calls), 2)   # nothing to keep: asked again
        rows = [{"mcap0": 2e5, "max24": 0.5}] * 30
        with mock.patch("ui.data.q", lambda path, s, args=(): calls.append(s) or rows), \
                mock.patch.object(prijedlog, "_kol_db", lambda: "/x/kol.db"):
            prijedlog.chances()
            key = (14, "/x/kol.db")
            prijedlog._CHANCES[key] = (time.time() - prijedlog.CHANCES_TTL_S - 1, prijedlog._CHANCES[key][1])
            prijedlog.chances()
        self.assertEqual(len(calls), 4)

    def test_caller_cannot_change_the_cached_answer(self):
        rows = [{"mcap0": 2e5, "max24": 0.5}] * 30
        with mock.patch("ui.data.q", lambda path, s, args=(): rows), mock.patch.object(prijedlog, "_kol_db", lambda: "/k"):
            prijedlog.chances()["100–300k"] = "pokvareno"
            self.assertEqual(prijedlog.chances()["100–300k"], (1.0, 30))


class TierByKey(unittest.TestCase):
    def test_one_row_by_primary_key(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "hype.db")
            con = sqlite3.connect(p)
            con.execute("CREATE TABLE token_tier (token TEXT PRIMARY KEY, klasa TEXT, razina INTEGER)")
            con.executemany("INSERT INTO token_tier VALUES (?,?,?)", [(f"T{i}", "mali", i % 3) for i in range(500)])
            con.commit()
            con.close()
            sql = []
            real_q = data.q
            with mock.patch.dict(data.GROUPS, {"hype": [p]}), \
                    mock.patch.object(data, "q", lambda path, s, args=(): sql.append(s) or real_q(path, s, args)):
                row = data.token_tier("T7")
                none = data.token_tier("nema")
            self.assertEqual(row["klasa"], "mali")
            self.assertEqual(row["razina"], 1)
            self.assertIsNone(none)
            self.assertTrue(all("WHERE token=?" in s for s in sql))

    def test_missing_table_is_none(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "hype.db")
            sqlite3.connect(p).close()
            with mock.patch.dict(data.GROUPS, {"hype": [p]}):
                self.assertIsNone(data.token_tier("T1"))


class LivePricesShortLeash(unittest.TestCase):
    def test_live_prices_use_a_short_timeout_and_no_retry(self):
        seen = []

        def get_json(url, params=None, ttl=None, timeout=30, headers=None, retries=None):
            seen.append((ttl, timeout, retries))
            return []
        with mock.patch.object(client.http, "get_json", get_json), mock.patch.object(client._FAST, "wait", lambda: None):
            client.tokens_live("solana", ["A"] * 31)   # two batches of at most 30
            client.tokens("solana", ["A"])
        self.assertEqual(seen[0], (client.LIVE_TTL, client.LIVE_TIMEOUT_S, 0))
        self.assertEqual(seen[1], (client.LIVE_TTL, client.LIVE_TIMEOUT_S, 0))
        self.assertEqual(seen[2], (client.CACHE_TTL, 30, None))   # the scanners keep their patient path
        self.assertLessEqual(client.LIVE_TIMEOUT_S, 5)

    def test_a_failed_live_call_is_no_price_for_the_callers(self):
        from ui import paper

        def boom(*a, **k):
            raise OSError("timed out")
        with mock.patch.object(client.http, "get_json", boom), mock.patch.object(client._FAST, "wait", lambda: None):
            self.assertEqual(paper.market({"A"}), {})


class FollowedWalletsCount(unittest.TestCase):
    """10.11. (audit sekundni S10): the wallets the real-money account follows count as "zovu" signals."""

    def test_followed_wallets_are_read_from_league_db(self):
        from league import copy, store
        from trade import settings
        from ui import pravitrade
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "league.db")
            con = store.connect(p)
            copy.ensure(con)
            for i, w in enumerate(("W1", "W2", "W3")):
                con.execute("INSERT INTO follows (user, kind, target, active) VALUES (?,?,?,?)",
                            (settings.LEAGUE_USER, "wallet", w, 0 if i == 2 else 1))
            con.execute("INSERT INTO follows (user, kind, target, active) VALUES (?,?,?,1)", (settings.LEAGUE_USER, "kol", "x"))
            con.execute("INSERT INTO follows (user, kind, target, active) VALUES (?,?,?,1)", ("netko", "wallet", "W9"))
            con.commit()
            con.close()
            with mock.patch.object(store, "DB", p), mock.patch("wallets.dokazani.current", lambda: ["D1"]):
                got = pravitrade.followed_wallets()
        self.assertEqual(got, {"W1", "W2", "D1"})


if __name__ == "__main__":
    unittest.main()
