"""Pump pick among several tokens of one event (no network)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eventpick import score  # noqa: E402


def tok(token, symbol, organic, liq, mcap, role="copy", keyword="MIDTERMS"):
    return {"token": token, "symbol": symbol, "score": organic, "liquidity": liq, "mcap": mcap,
            "role": role, "keyword": keyword}


class EventPick(unittest.TestCase):
    def test_ranks_healthy_token_over_big_and_rugged(self):
        toks = [tok("big", "MAGA", 80, 2_000_000, 300_000_000, keyword="MAGA"),
                tok("mid", "MIDTERMS", 55, 60_000, 400_000, role="canonical"),
                tok("rug", "MIDTERM", 70, 50_000, 300_000),
                tok("dust", "MAGA", 40, 900, 5_000, keyword="MAGA")]
        rugs = {"rug": {"verdict": "ODBAČEN"}, "mid": {"verdict": "PROLAZI", "bundle_pct": 3}}
        watches = {"mid": {"n": 20, "corr_volume": 0.7, "smart_total": 2, "bad_total": 0,
                           "verdict": "volumen i smart money rastu prema eventu"}}
        ranked = score.rank(toks, rugs, watches, {"mid": 2})
        self.assertEqual(ranked[0]["token"], "mid")
        self.assertEqual({t["token"] for t in ranked if t["pump"] is None}, {"rug", "dust"})
        self.assertEqual([t["token"] for t in ranked[-2:]].count("rug"), 1)  # excluded go last
        self.assertTrue(any("KOL" in r for _, r in ranked[0]["reasons"]))

    def test_bad_wallets_and_thin_pool_lower_the_score(self):
        base = tok("a", "X", 50, 50_000, 500_000)
        clean = score.score_token(base)["pump"]
        bad = score.score_token(base, watch={"n": 10, "corr_volume": 0, "smart_total": 0, "bad_total": 4,
                                             "verdict": "ulaze loši walleti"})["pump"]
        thin = score.score_token({**base, "liquidity": 5_000})["pump"]
        self.assertLess(bad, clean)
        self.assertLess(thin, clean)

    def test_no_data_still_scores(self):
        r = score.score_token(tok("a", "X", 30, 20_000, 100_000))
        self.assertIsNotNone(r["pump"])
        self.assertTrue(any("nije napravljena" in t for _, t in r["reasons"]))


if __name__ == "__main__":
    unittest.main()
