"""7.11.: a spike that lasts 2-3 snapshots (Jure 1.11.: $900 -> $8.1k -> $8.1k -> $900, pairless at 80x) is a bad
price reading too: marked bad, every snapshot of it left out of the chart line."""
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import history  # noqa: E402
from ui import leaguedash  # noqa: E402


class JumpBack(unittest.TestCase):
    def _con(self, eq):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE equity (ts INTEGER, user TEXT, equity REAL, open INTEGER, detail TEXT)")
        con.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, user TEXT, peak_px REAL)")
        con.executemany("INSERT INTO equity VALUES (?,?,?,12,NULL)", [(900 * i, "Jure", e) for i, e in enumerate(eq)])
        return con

    def test_three_snapshot_spike_is_bad(self):
        con = self._con([913.0, 8108.0, 8123.0, 896.0, 882.0, 8048.0, 8048.0, 8041.0, 868.0, 858.0])
        js = history.jumps(con, {"Jure"})
        self.assertEqual([(j["ts"], j["bad"]) for j in js], [(900, True), (4500, True)])
        self.assertEqual(js[0]["bad_ts"], [900, 1800])
        self.assertEqual(js[1]["bad_ts"], [4500, 5400, 6300])
        self.assertIn("pogrešna cijena", js[0]["text"])
        d = {"users": ["Jure"], "now": 9000, "bot": None, "rekts": [], "jumps": js,
             "players": [{"user": "Jure", "pts": [(ts, e) for ts, e in con.execute("SELECT ts, equity FROM equity")]}]}
        pts = leaguedash.chart_data(d)["series"][0]["pts"]
        self.assertTrue(all(v < 1000 for _, v in pts), pts)
        self.assertEqual(len(pts), 5)

    def test_real_gain_kept(self):
        con = self._con([900.0, 1600.0, 1550.0, 1580.0, 1600.0, 1620.0, 1500.0])
        js = history.jumps(con, {"Jure"})
        self.assertEqual(len(js), 1)
        self.assertFalse(js[0]["bad"])
        self.assertEqual(js[0]["bad_ts"], [])


if __name__ == "__main__":
    unittest.main()
