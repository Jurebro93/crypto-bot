"""DexScreener matching and scan against canned responses (no network).

    python3 -m unittest discover -s tests
"""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_dex  # noqa: E402
from dexscreener import client, match  # noqa: E402

NOW_MS = 1_800_000_000_000


def _pair(chain, token, symbol, name, liq, vol, created_h_ago=10):
    return {"chainId": chain, "dexId": "pumpswap", "url": f"https://dexscreener.com/{chain}/{token}",
            "pairAddress": f"pair-{token}-{liq}", "baseToken": {"address": token, "symbol": symbol, "name": name},
            "priceUsd": "0.001", "marketCap": 100000, "liquidity": {"usd": liq}, "volume": {"h24": vol, "h1": 1},
            "priceChange": {"h1": 5}, "txns": {"h24": {"buys": 10, "sells": 4}},
            "pairCreatedAt": NOW_MS - created_h_ago * 3.6e6}


PAIRS = [
    _pair("solana", "KIRK1", "KIRK", "Charlie Kirk", 50000, 90000, 2),
    _pair("solana", "KIRK1", "KIRK", "Charlie Kirk", 8000, 1000),        # same token, worse pair
    _pair("solana", "KIRK2", "CK", "Kirk Forever", 20000, 300000),       # name match only
    _pair("solana", "KIRK3", "KIRK", "Kirk dust", 200, 50),              # below min liquidity
    _pair("ethereum", "0xKIRK", "KIRK", "Kirk on eth", 90000, 900000),   # other chain
    _pair("solana", "DOGE1", "DOGE", "Dogecoin", 90000, 900000),         # unrelated
]


EVENT = {"title": "Charlie Kirk birthday", "date": "2026-10-14", "hype": 60,
         "subject": "Charlie Kirk October", "keywords": ["KIRK", "CHARLIEKIRK", "OCTOBER"]}


def _fake(q):
    return PAIRS


class DexOffline(unittest.TestCase):
    def setUp(self):
        self._search, self._cto = client.search, client.community_takeovers
        client.community_takeovers = lambda: [{"tokenAddress": "KIRK2"}]

    def tearDown(self):
        client.search, client.community_takeovers = self._search, self._cto

    def test_event_terms_drop_noise(self):
        self.assertEqual(match.event_terms(EVENT), ["Charlie Kirk", "KIRK", "CHARLIEKIRK"])

    def test_best_pairs(self):
        rows = match.best_pairs(PAIRS, "solana", 1000, now_ms=NOW_MS)
        by_token = {r["token"]: r for r in rows}
        self.assertEqual(set(by_token), {"KIRK1", "KIRK2", "DOGE1"})  # dust and eth dropped
        self.assertEqual(by_token["KIRK1"]["liquidity"], 50000)       # deepest pair kept
        self.assertEqual(by_token["KIRK1"]["age_h"], 2.0)

    def test_rank_canonical_vs_copycat(self):
        rows = match.best_pairs(PAIRS, "solana", 1000, now_ms=NOW_MS)
        ranked = match.rank_event_tokens(rows, match.event_terms(EVENT), cto_tokens={"KIRK2"})
        self.assertEqual([r["token"] for r in ranked], ["KIRK2", "KIRK1"])  # DOGE not tied to event
        self.assertEqual([r["role"] for r in ranked], ["canonical", "copycat"])
        self.assertTrue(ranked[0]["cto"])
        self.assertFalse(ranked[0]["exact"])
        self.assertTrue(ranked[1]["exact"])

    def test_first_name_only_matches_symbol(self):
        harry = match.summarize(_pair("solana", "HP", "BITCOIN", "HarryPotterObamaSonic10Inu", 9e4, 9e4), NOW_MS)
        kane = match.summarize(_pair("solana", "K", "KANE", "Kane", 9e4, 9e4), NOW_MS)
        ev = {"subject": "Harry Kane", "keywords": ["HARRY", "HARRYKANE", "KANE"]}
        ranked = match.rank_event_tokens([harry, kane], match.event_terms(ev), weak=match.weak_terms(ev))
        self.assertEqual(ranked, [])  # neither "HARRY" in a name nor bare "KANE" is enough
        named = match.summarize(_pair("solana", "HK", "HKANE", "Harry Kane Coin", 9e4, 9e4), NOW_MS)
        ranked = match.rank_event_tokens([harry, kane, named], match.event_terms(ev), weak=match.weak_terms(ev))
        self.assertEqual([r["token"] for r in ranked], ["HK"])

    def test_wash_volume_penalised(self):
        base = match.summarize(PAIRS[0], NOW_MS)
        washed = {**base, "vol_24h": base["liquidity"] * 100}
        self.assertLess(match.organic_score(washed), match.organic_score({**base, "vol_24h": base["liquidity"] * 2}))

    def test_scan_groups_by_event(self):
        calls = []
        client.search = lambda q: calls.append(q) or PAIRS
        events = [EVENT, {"title": "Kirk memorial", "date": "2026-11-01", "hype": 40, "keywords": ["KIRK"]}]
        results, errors = run_dex.scan(events, "solana", 1000)
        self.assertEqual(errors, {})
        self.assertEqual(calls, ["Charlie Kirk", "CHARLIEKIRK", "KIRK"])  # bare KIRK only for 2nd event  # each term searched once
        self.assertEqual([e["event"] for e in results], ["Charlie Kirk birthday", "Kirk memorial"])
        self.assertEqual(results[0]["tokens"][0]["role"], "canonical")
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "t.db")
            run_dex.save_db(results, db)
            n = sqlite3.connect(db).execute("SELECT COUNT(*) FROM event_tokens").fetchone()[0]
        self.assertEqual(n, sum(len(e["tokens"]) for e in results))
        self.assertIn("Charlie Kirk birthday", run_dex.report(results, errors, "t"))

    def test_scan_survives_failed_search(self):
        client.search = lambda q: (_ for _ in ()).throw(TimeoutError("slow"))
        results, errors = run_dex.scan([{"title": "x", "date": "2026-01-01", "keywords": ["XYZW"]}])
        self.assertEqual(results[0]["tokens"], [])
        self.assertIn("XYZW", errors)


if __name__ == "__main__":
    unittest.main()
