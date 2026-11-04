"""4.11.: the numbers on Pregled > "Koliko podataka alat ima" and the demo bot's "why nothing was bought" line.

    python3 -m unittest tests.test_pregled_counts_offline
"""
import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import store as kstore  # noqa: E402
from ui import pocetna  # noqa: E402

DAY = 86400


class KolCounts(unittest.TestCase):
    def setUp(self):
        self.now = time.time()
        self.path = os.path.join(tempfile.mkdtemp(), "kol.db")
        con = kstore.connect(self.path)
        t = int(self.now) - DAY
        for h in ("alice", "bob", "tg:gemcalls", "w:7xKXtg"):
            con.execute("INSERT INTO kols (handle, first_seen) VALUES (?, ?)", (h, t))
        rows = [("1", "alice", "call"), ("2", "bob", "call"), ("3", "tg:gemcalls", "call"), ("4", "alice", "brag")]
        rows += [(f"b{i}", "w:7xKXtg", "buy") for i in range(20)] + [(f"s{i}", "w:7xKXtg", "sell") for i in range(10)]
        for tid, h, kind in rows:
            con.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES (?, 'T', ?, ?, ?)", (tid, h, t, kind))
        con.commit()
        con.close()

    def test_wallet_swaps_are_not_influencer_calls(self):
        c = pocetna._sql_counts(self.path, "kols", "first_seen", self.now, "handle NOT LIKE 'tg:%' AND handle NOT LIKE 'w:%'")
        self.assertEqual(c, (2, 2, 0))                                   # alice, bob: not the channel, not the wallet
        c = pocetna._sql_counts(self.path, "calls", "ts", self.now, "kind = 'call'")
        self.assertEqual(c, (3, 3, 0))                                   # 3 calls (X and Telegram), not the brag
        c = pocetna._sql_counts(self.path, "calls", "ts", self.now, "kind IN ('buy', 'sell')")
        self.assertEqual(c, (30, 30, 0))
        self.assertEqual(pocetna._sql_counts(self.path, "calls", "ts", self.now)[0], 34)   # what the page showed before

    def test_week_split(self):
        con = sqlite3.connect(self.path)
        con.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES ('old', 'T', 'alice', ?, 'call')",
                    (int(self.now) - 10 * DAY,))
        con.commit()
        con.close()
        self.assertEqual(pocetna._sql_counts(self.path, "calls", "ts", self.now, "kind = 'call'"), (4, 3, 1))


class RowTotals(unittest.TestCase):
    def test_timestamp_keys_are_counted_not_summed(self):
        con = sqlite3.connect(":memory:")
        con.executescript("""CREATE TABLE snapshots (ts INTEGER PRIMARY KEY, data TEXT);
                             CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT, x);
                             CREATE TABLE wallet_trades (wallet TEXT, sig TEXT, PRIMARY KEY (sig, wallet));""")
        con.execute("INSERT INTO snapshots VALUES (1793000000, 'x')")
        con.execute("INSERT INTO trades (x) VALUES (1)")
        con.execute("INSERT INTO wallet_trades VALUES ('w', 's')")
        total = sum(con.execute(f"SELECT {pocetna._count_expr(con, t)} FROM [{t}]").fetchone()[0]
                    for t in ("snapshots", "trades", "wallet_trades"))
        self.assertEqual(total, 3)


class IntakeSummary(unittest.TestCase):
    def test_line(self):
        import run_paper
        cands = {"A": {"decision": "skip_score", "score": 41}, "B": {"decision": "skip_score", "score": 12},
                 "C": {"decision": "skip_liq", "score": 60}, "D": {"score": 70}}
        s = run_paper._intake_summary(cands, {"min_score": 50}, 38.0)
        self.assertEqual(s, "4 kandidata: skip_score 2 (najbolji 41 < 50), skip_liq 1, bez cijene 1; prag 50, istraživanje od 38")
        self.assertIsNone(run_paper._intake_summary({}, {"min_score": 50}, None))
        self.assertIn("istraživanje isključeno", run_paper._intake_summary(cands, {"min_score": 50}, None))


if __name__ == "__main__":
    unittest.main()
