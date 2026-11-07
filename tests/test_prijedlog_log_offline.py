"""Audit 7.11.: the box's picks are written down and labelled 24 h later from the price path, stop-first aware."""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import together  # noqa: E402
from ui import prijedlog_log as pl  # noqa: E402

NOW = 1_800_000_000


class PrijedlogLog(unittest.TestCase):
    def test_log_label_summary(self):
        db = os.path.join(tempfile.mkdtemp(), "hype.db")
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE hype_snapshots (token TEXT, ts INTEGER, price REAL, mcap REAL, liquidity REAL, PRIMARY KEY (token, ts))")
        t0 = NOW - 30 * 3600
        paths = {"A": [100, 110, 120, 118], "B": [100, 70, 130, 90], "C": [100, 95, 90, 80]}   # k$ mcap
        for tok, ms in paths.items():
            for j, m in enumerate(ms):
                con.execute("INSERT INTO hype_snapshots VALUES (?,?,?,?,0)", (tok, t0 + j * 1200, m / 1000, m * 1000))
        con.commit()
        picks = [{"token": "A", "mcap0": 100_000, "razina": "visoka", "conf": 70},
                 {"token": "B", "mcap0": 100_000, "razina": "visoka", "conf": 60},
                 {"token": "C", "mcap0": 100_000, "razina": "srednja", "conf": 40},
                 {"token": "D", "mcap0": 100_000, "razina": "niska", "conf": 20}]
        self.assertEqual(pl.log(db, picks, "tokeni", t0), 4)
        self.assertEqual(pl.log(db, picks, "pregled", t0 + 600), 0)    # same day: not twice
        self.assertEqual(pl.label(con, NOW), 4)
        rows = {r[0]: r[1:] for r in con.execute("SELECT token, max24, r24, hit, stop_first, n_snap FROM prijedlog_log")}
        self.assertEqual(rows["A"][2:], (1, 0, 4))
        self.assertAlmostEqual(rows["A"][0], 0.2)
        self.assertEqual(rows["B"][2:], (0, 1, 4))                     # +30 % came after the −30 % stop
        self.assertEqual(rows["C"][2:], (0, 0, 4))                     # −20 % never reached the stop
        self.assertEqual(rows["D"], (None, None, None, None, 0))       # no snapshots: left unlabelled but marked
        s = pl.summary(db, now=NOW)
        self.assertEqual((s["visoka"]["n"], s["visoka"]["labelled"], s["visoka"]["hit"], s["visoka"]["stop_first"]), (2, 2, 1, 1))
        self.assertEqual(pl.sentence(s, min_n=2), "Moji prijedlozi zadnjih 7 dana, provjereni 24 h kasnije: visoka 1 od 2 dalo +15 % prije stopa (stop prvi 1, medijan vrha +25%).")
        self.assertEqual(pl.sentence(s), "")
        con.close()

    def test_outcome_rules(self):
        self.assertIsNone(pl.outcome([(1, 100)], 100))
        self.assertEqual(pl.outcome([(1, 100), (2, 116), (3, 50)], 100)[2:], (1, 0))
        self.assertEqual(pl.outcome([(1, 100), (2, 74), (3, 200)], 100)[2:], (0, 1))

    def test_confirm_stats_from_third_caller(self):
        groups = [("T", 1000, 1300, ["a", "b", "c"], "a"), ("U", 2000, 2100, ["a", "b"], "a")]
        calls = [("T", 1000, 1.0, 1.0), ("T", 1100, 1.5, 0.3), ("T", 1300, 1.8, 0.1), ("U", 2000, 1.0, 2.0)]
        cf = together.confirm_stats(groups, calls)
        self.assertEqual(cf["n"], 1)
        self.assertEqual(cf["lag_med"], 5.0)
        self.assertEqual(cf["moved"], 1.0)
        self.assertAlmostEqual(cf["rem_med"], 2.0 / 1.8 - 1)
        self.assertEqual((cf["hit15"], cf["hit50"], cf["under"]), (0.0, 0.0, 0.0))
        self.assertEqual(together.confirm_stats([], [])["n"], 0)


if __name__ == "__main__":
    unittest.main()
