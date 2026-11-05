"""5.11.: group call of 3+ different authors within 10 minutes (hype feature grupa_10, kol3 trades tagged grupa10)."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import store  # noqa: E402
from paper import rules, store as pstore  # noqa: E402


class Group10(unittest.TestCase):
    def test_group_calls(self):
        path = os.path.join(tempfile.mkdtemp(), "kol.db")
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE calls (tweet_id TEXT, token TEXT, handle TEXT, ts INTEGER, kind TEXT, bad INTEGER)")
        now = 100_000
        rows = [("A", "Ana", now - 900), ("A", "Bob", now - 600), ("A", "Cid", now - 400),   # 3 in 8.3 min
                ("B", "Ana", now - 1500), ("B", "Bob", now - 900), ("B", "Cid", now - 100),  # 3 only in 23 min
                ("C", "Ana", now - 60), ("C", "ana", now - 50), ("C", "Bob", now - 40),      # 2 different authors
                ("D", "Ana", now - 60), ("D", "Bob", now - 50), ("D", "bot1", now - 40),     # third is a bot
                ("E", "Ana", now - 60), ("E", "Bob", now - 50), ("E", "Dan", now - 40)]      # Dan's call is bad
        con.executemany("INSERT INTO calls VALUES (?,?,?,?,'call',0)", [(str(i), *r) for i, r in enumerate(rows)])
        con.execute("UPDATE calls SET kind='bot' WHERE handle='bot1'")
        con.execute("UPDATE calls SET bad=1 WHERE handle='Dan'")
        con.commit()
        con.close()
        g = store.group_calls(path=path, now=now)
        self.assertEqual(set(g), {"A"})
        self.assertEqual(g["A"]["n"], 3)
        self.assertEqual(g["A"]["handles"], ["ana", "bob", "cid"])

    def test_kol3_tight_split(self):
        d = tempfile.mkdtemp()
        con = pstore.connect(os.path.join(d, "paper.db"))
        now = 1_762_000_000
        for i, (g10, ret) in enumerate([(True, 0.3)] * 3 + [(False, -0.2)] * 2 + [(None, 0.9)]):
            c = {"entry_mode": "kol3"}
            if g10 is not None:
                c["grupa10"] = g10
            con.execute("INSERT INTO trades (token, symbol, opened_ts, closed_ts, status, exit_reason, size_usd, ret, "
                        "pnl_usd, state, config) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (f"t{i}", "S", now - 3600 + i, now - 60, "closed", "tp", 20, ret, ret * 20, "{}", json.dumps(c)))
        con.commit()
        kt = rules.kol3_tight(con, 14, now)
        self.assertEqual(kt["10"]["n"], 3)
        self.assertEqual(kt["15"]["n"], 2)   # the trade without the tag (before 5.11.) is left out
        self.assertEqual(kt["10"]["median"], 0.3)


if __name__ == "__main__":
    unittest.main()
