"""One verdict for an influencer (10.11., Jure, prijedlog 4.0): kolsummary.verdict from the 1-h and 24-h shares, and
verdict_stats / kol_verdict reading kol.db (calls.r24h) and minute.db (handle_stats hit10) once per window, cached."""
import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import minute, store  # noqa: E402
from ui import kolsummary as ks  # noqa: E402


class Verdict(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(ks.verdict(0.5, 0.4, 5)[0], "drzi_se")           # both thresholds inclusive
        self.assertEqual(ks.verdict(0.7, 0.07, 30)[:2], ("samo_brzo", "samo brzo"))
        self.assertEqual(ks.verdict(0.49, 0.9, 30)[:2], ("ne_isplati_se", "ne isplati se"))
        self.assertEqual(ks.verdict(0.9, 0.9, 4)[:2], ("premalo", "premalo poziva"))
        self.assertEqual(ks.verdict(None, 0.9, 20)[0], "premalo")         # 1 h not measured yet
        self.assertEqual(ks.verdict(0.8, None, 20)[0], "samo_brzo")       # 24 h unknown: only the fast exit is backed

    def test_sentence_has_both_numbers(self):
        _, _, s = ks.verdict(0.7, 0.07, 30)
        self.assertIn("70 %", s)
        self.assertIn("7 %", s)
        self.assertIn("+10 % prije stopa −20 %", s)
        self.assertIn("barem 5", ks.verdict(0.9, 0.9, 2)[2])
        for k in ("drzi_se", "samo_brzo", "ne_isplati_se", "premalo"):
            self.assertIn(k, ks.VERDICT_WORD)
            self.assertIn(k, ks.VERDICT_DOT)
            self.assertIn(k, ks.VERDICT_TITLE)


class Stats(unittest.TestCase):
    def setUp(self):
        ks._VCACHE.clear()
        self.d = tempfile.mkdtemp()
        self.kdb = os.path.join(self.d, "kol.db")
        self.mdb = os.path.join(self.d, "minute.db")
        self.now = int(time.time())
        con = store.connect(self.kdb)
        mcon = minute.connect(self.mdb)
        day = 86400
        # @fast: 10 calls 2-10 days ago; 8 hit +10 % before the stop in the first hour, 1 of 10 up a day later
        for i in range(10):
            ts = self.now - (2 + i % 8) * day - i * 60
            self._call(con, f"f{i}", f"T{i}", "fast", ts, r24=0.3 if i == 0 else -0.5, mcap=80000)
            mcon.execute("INSERT INTO call_path (tweet_id, token, handle, ts, entry, t10, sl_min) VALUES (?,?,?,?,?,?,?)",
                         (f"f{i}", f"T{i}", "fast", ts, 1.0, 3 if i < 8 else None, None if i < 8 else 5))
        # a second post of the same token by @fast counts once (first per account and token)
        self._call(con, "f0b", "T0", "fast", self.now - 1 * day, r24=0.9, mcap=90000)
        # a call under 30k $ does not count; a buy is not a post
        self._call(con, "f_low", "LOW", "fast", self.now - 3 * day, r24=5.0, mcap=12000)
        self._call(con, "f_buy", "BUY", "fast", self.now - 3 * day, r24=5.0, mcap=99000, kind="buy")
        # @rare: 2 calls only; @old: calls older than 14 days
        for i in range(2):
            self._call(con, f"r{i}", f"R{i}", "Rare", self.now - 3 * day, r24=0.5, mcap=50000)
        for i in range(6):
            self._call(con, f"o{i}", f"O{i}", "old", self.now - 20 * day, r24=0.5, mcap=50000)
        con.commit()
        mcon.commit()
        con.close()
        mcon.close()

    def _call(self, con, tid, tok, handle, ts, r24, mcap, kind="call"):
        con.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, r24h, mcap0) VALUES (?,?,?,?,?,?,?)",
                    (tid, tok, handle, ts, kind, r24, mcap))

    def test_shares_counts_and_verdict(self):
        st = ks.verdict_stats(14, kol_db=self.kdb, minute_db=self.mdb)
        f = st["fast"]
        self.assertEqual((f["n"], f["n1"], f["n24"], f["plus24"]), (10, 10, 10, 1))
        self.assertAlmostEqual(f["h1"], 0.8)
        self.assertAlmostEqual(f["d24"], 0.1)
        self.assertEqual((f["key"], f["word"], f["dot"]), ("samo_brzo", "samo brzo", "warn"))
        self.assertEqual(st["Rare"]["key"], "premalo")
        self.assertNotIn("old", st)                                      # outside the 14-day window
        self.assertIn("old", ks.verdict_stats(30, kol_db=self.kdb, minute_db=self.mdb))
        self.assertEqual(ks.kol_verdict("@FAST", 14, kol_db=self.kdb, minute_db=self.mdb)["key"], "samo_brzo")
        none = ks.kol_verdict("nobody", 14, kol_db=self.kdb, minute_db=self.mdb)
        self.assertEqual((none["key"], none["n"]), ("premalo", 0))

    def test_one_build_per_window_and_ttl(self):
        calls = []
        real = ks._day24

        def spy(*a):
            calls.append(a)
            return real(*a)
        ks._day24 = spy
        try:
            for _ in range(50):                                           # a page asking for every row
                ks.kol_verdict("fast", 14, kol_db=self.kdb, minute_db=self.mdb)
            self.assertEqual(len(calls), 1)
            ks.verdict_stats(7, kol_db=self.kdb, minute_db=self.mdb)
            self.assertEqual(len(calls), 2)                               # one per window
        finally:
            ks._day24 = real

    def test_without_minute_db_everyone_waits_for_the_measure(self):
        st = ks.verdict_stats(14, kol_db=self.kdb, minute_db=os.path.join(self.d, "nema.db"))
        self.assertEqual(st["fast"]["key"], "premalo")
        self.assertEqual(st["fast"]["n"], 10)

    def test_reads_are_indexed(self):
        con = sqlite3.connect(self.kdb)
        plan = " ".join(str(r) for r in con.execute(
            "EXPLAIN QUERY PLAN SELECT handle, token, ts, r24h, mcap0 FROM calls WHERE ts >= ? AND ts <= ? "
            "AND kind NOT IN ('buy', 'sell') AND bad IS NULL ORDER BY ts", (0, 1)))
        con.close()
        self.assertIn("calls_ts", plan)


if __name__ == "__main__":
    unittest.main()
