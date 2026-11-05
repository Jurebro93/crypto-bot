"""5.11.: trending tokens (kol/trending.py): GeckoTerminal + DexScreener boosts, daily X search for who posted the
CA, and the list in the KOL backfill.

    python3 -m unittest tests.test_trending_offline
"""
import datetime as dt
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import backfill, store, trending  # noqa: E402

CFG = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kol", "config.json")))
NOW = 1_800_000_000
CA = "DDmGnuvroxVrb7CSyjYcezFU8gnAfhKasg4ZZezmpump"
WBTC = "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh"


def tw(tid, h, ts, text):
    created = dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%a %b %d %H:%M:%S +0000 %Y")
    return {"id": tid, "text": text, "createdAt": created, "author": {"userName": h, "followers": 5000}}


def _pool(tok, name, fdv, vol, created="2026-11-03T10:00:00Z"):
    return {"attributes": {"name": name, "fdv_usd": fdv, "volume_usd": {"h24": vol}, "pool_created_at": created},
            "relationships": {"base_token": {"data": {"id": f"solana_{tok}"}}}}


class Fetch(unittest.TestCase):
    def test_gecko_pages_and_dedup(self):
        pages = {1: {"data": [_pool(CA, "AMD / SOL", 600000, 2e6), _pool(WBTC, "WBTC / SOL", 9e9, 5e6)]},
                 2: {"data": [_pool(CA, "AMD / SOL", 600000, 2e6), _pool("BIG" + "1" * 40, "BIG / SOL", 5e8, 1e6)]}}
        got = trending.fetch_gecko(get=lambda url, p: pages.get(p["page"], {"data": []}), pages=3)
        self.assertEqual([g["token"] for g in got], [CA, WBTC, "BIG" + "1" * 40])
        self.assertEqual(got[0]["symbol"], "AMD")
        self.assertEqual(got[0]["created_ts"], int(dt.datetime(2026, 11, 3, 10, tzinfo=dt.timezone.utc).timestamp()))


class Collect(unittest.TestCase):
    def setUp(self):
        mock.patch("usage.meter.record").start()
        self.addCleanup(mock.patch.stopall)
        self.con = store.connect(os.path.join(tempfile.mkdtemp(), "kol.db"))
        self.gecko = [{"token": CA, "symbol": "AMD", "fdv": 600000, "vol24": 2e6, "created_ts": NOW - 2 * 86400},
                      {"token": WBTC, "symbol": "WBTC", "fdv": 9e9, "vol24": 5e6, "created_ts": None},
                      {"token": "BIG" + "1" * 40, "symbol": "BIG", "fdv": 5e8, "vol24": 1e6, "created_ts": None}]
        self.boosts = [{"token": "BOOST" + "2" * 39, "symbol": "", "fdv": 0, "vol24": 0, "created_ts": None}]

    def test_store_search_and_backfill(self):
        n = trending.collect_today(self.con, CFG, NOW, gecko=self.gecko, boosts=self.boosts)
        self.assertEqual(n, 2)                                            # WBTC (major) and BIG (fdv > 100M) left out
        self.assertEqual(trending.collect_today(self.con, CFG, NOW + 60, gecko=self.gecko, boosts=self.boosts), 0)
        t = trending.targets(self.con, CFG, NOW)
        self.assertEqual([x[0] for x in t], [CA, "BOOST" + "2" * 39])     # gecko before boosts
        self.assertEqual(t[0][1], NOW - 2 * 86400)                        # since = pool creation (inside back_d)
        asked = []

        def get(q, cursor):
            asked.append(q)
            return {"tweets": [tw("77", "caller", NOW - 36 * 3600, f"look at {CA} 🚀")], "has_next_page": False}
        with mock.patch("kol.twapi.key", return_value="k"):
            n = trending.search(self.con, CFG, get=get, now=NOW)
        self.assertEqual(n, 1)
        self.assertEqual(len(asked), 2)
        self.assertTrue(asked[0].startswith(CA))
        self.assertEqual(self.con.execute("SELECT source, kind FROM calls WHERE handle='caller'").fetchone(), ("kol_trend", "call"))
        self.assertEqual(trending.targets(self.con, CFG, NOW), [])         # searched once
        bf = trending.for_backfill(self.con, NOW)
        self.assertEqual({b["mint"] for b in bf}, {CA, "BOOST" + "2" * 39})
        self.assertTrue(all(b["winner"] for b in bf))
        picked = backfill.pick(bf + [{"mint": "L1", "launch_ts": 0, "peak_ts": 0, "winner": False}], 5, 5)
        self.assertEqual(picked[0]["mint"], CA)                           # highest volume first

    def test_daily_cap(self):
        trending.collect_today(self.con, CFG, NOW, gecko=self.gecko, boosts=[])
        self.con.execute("INSERT INTO kv VALUES (?, ?)", (f"twtrend:{time.strftime('%Y-%m-%d', time.gmtime(NOW))}", "0.4"))
        self.con.commit()
        with mock.patch("kol.twapi.key", return_value="k"):
            self.assertEqual(trending.search(self.con, CFG, get=lambda q, c: {"tweets": []}, now=NOW), 0)
        self.assertEqual(len(trending.targets(self.con, CFG, NOW)), 1)    # nothing was searched: cap reached


if __name__ == "__main__":
    unittest.main()
