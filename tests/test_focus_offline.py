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


if __name__ == "__main__":
    unittest.main()
