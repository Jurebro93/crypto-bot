"""3.11.: one author posting the same token several times in a short window."""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import store  # noqa: E402


class Burst(unittest.TestCase):
    def test_burst(self):
        path = os.path.join(tempfile.mkdtemp(), "kol.db")
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE calls (tweet_id TEXT, token TEXT, handle TEXT, ts INTEGER, kind TEXT)")
        now = 100_000
        rows = [("1", "A", "Ana", now - 3000), ("2", "A", "ana", now - 2000), ("3", "A", "Ana", now - 100),
                ("4", "B", "Bob", now - 10000), ("5", "B", "Bob", now - 100),    # 2.7 h apart: no burst
                ("6", "C", "Cid", now - 50), ("7", "C", "Dan", now - 40),        # two authors: no burst
                ("8", "D", "bot1", now - 50), ("9", "D", "bot1", now - 40)]
        con.executemany("INSERT INTO calls VALUES (?,?,?,?,'')", rows)
        con.execute("UPDATE calls SET kind='bot' WHERE handle='bot1'")
        con.commit()
        con.close()
        b = store.author_bursts(path=path, now=now)
        self.assertEqual(b, {"A": {"n": 3, "handle": "ana"}})


if __name__ == "__main__":
    unittest.main()
