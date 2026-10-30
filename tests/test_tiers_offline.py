"""Tiered analysis against canned data (no network)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tiers import classify, sieve, store  # noqa: E402


class Classify(unittest.TestCase):
    def test_klasa(self):
        self.assertEqual(classify.klasa(50_000, 10), "moonshot")
        self.assertEqual(classify.klasa(50_000, 100), "rizican")      # small but old: not a fresh moonshot
        self.assertEqual(classify.klasa(500_000, 10), "rizican")
        self.assertEqual(classify.klasa(5_000_000, 200), "stabilni")
        self.assertEqual(classify.klasa(5_000_000, 20), "rizican")    # big but days old: not stable yet
        self.assertEqual(classify.klasa(5, 1, "canonical"), "event")

    def test_put_shape(self):
        self.assertIsNone(classify.put([(0, 1), (60, 2)])["put_skokovitost"])
        steady = classify.put([(0, 10_000), (3600, 20_000), (7200, 30_000), (10800, 40_000)])
        self.assertAlmostEqual(steady["put_skokovitost"], 1 / 3, places=2)
        self.assertEqual(steady["put_zadrzavanje"], 1.0)
        jump = classify.put([(0, 10_000), (3600, 10_100), (7200, 100_000), (10800, 40_000)])
        self.assertGreater(jump["put_skokovitost"], 0.9)
        self.assertAlmostEqual(jump["put_zadrzavanje"], 0.4)
        f = classify.put_features(jump)
        self.assertTrue(all(0 <= v <= 1 for v in f.values()))
        self.assertEqual(classify.put_features(classify.put([])), {})


class Sieve(unittest.TestCase):
    def test_pumpfun_passes_without_network(self):
        self.assertEqual(sieve.check("Mint1111111111111111111111111111111111pump")[0], "prolaz")

    def test_report_verdicts(self):
        self.assertEqual(sieve.verdict_from_report({"mintAuthority": "Abc"})[0], "pad")
        self.assertEqual(sieve.verdict_from_report({"freezeAuthority": "Abc"})[0], "pad")
        self.assertEqual(sieve.verdict_from_report({"rugged": True})[0], "pad")
        self.assertEqual(sieve.verdict_from_report({"markets": [{"lp": {"lpLockedPct": 5}}]})[0], "pad")
        self.assertEqual(sieve.verdict_from_report({"markets": [{"lp": {"lpLockedPct": 5}}],
                                                    "launchpad": {"name": "Pump.fun"}})[0], "prolaz")
        self.assertEqual(sieve.verdict_from_report({"markets": [{"lp": {"lpLockedPct": 100}}]})[0], "prolaz")
        # low liquidity / concentrated holders are never a T0 fail
        self.assertEqual(sieve.verdict_from_report({"totalHolders": 3, "score_normalised": 90})[0], "prolaz")
        self.assertEqual(sieve.verdict_from_report({})[0], "prolaz")

    def test_needs_check(self):
        self.assertTrue(sieve.needs_check(None))
        self.assertTrue(sieve.needs_check({"t0": "nije"}))
        self.assertFalse(sieve.needs_check({"t0": "prolaz", "t0_ts": 1000}, now=1000 + 3600))
        self.assertTrue(sieve.needs_check({"t0": "prolaz", "t0_ts": 1000}, now=1000 + 30 * 3600))


class Store(unittest.TestCase):
    def test_upsert_keeps_max_tier_and_sums_credits(self):
        path = os.path.join(tempfile.mkdtemp(), "hype.db")
        con = store.connect(path)
        store.upsert(con, "T1", 100, symbol="A", klasa="moonshot", t0="prolaz", razina=0)
        store.reach(con, "T1", 2, 525, "rug filter", 200)
        store.upsert(con, "T1", 300, razina=1, credits=10)   # a later cheaper check must not lower the tier
        store.upsert(con, "T2", 300, t0="nije", t0_razlog="likvidnost")
        r = store.get(con, "T1")
        self.assertEqual((r["razina"], r["credits"], r["first_ts"], r["last_ts"]), (2, 535, 100, 300))
        self.assertEqual(sorted(store.recent_tokens(con, 1, now=3000)), ["T1", "T2"])
        self.assertEqual(store.recent_tokens(con, 1, now=300 + 7200), [])
        sm = store.summary(con, 1, now=3000)
        self.assertEqual(sm["t0"], {"prolaz": 1, "nije": 1})
        self.assertEqual(sm["razina"], {2: 1, 0: 1})


if __name__ == "__main__":
    unittest.main()
