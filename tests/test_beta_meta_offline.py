"""16.11. (jutarnji izvještaj: "Beta dok meta raste: prosjek 608,985,465 %"): scan/meta.report_rows (the report's
"beta_by_meta_state", scan/shadow.report_data) - one beta with a start price of ~0 carried the mean. Now: rows without a
usable start price are dropped, each result is capped at +1000 % for the mean (winsorized), the median is next to it.

    python3 -m unittest tests.test_beta_meta_offline
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scan import meta, shadow, store  # noqa: E402

NOW = 1_763_280_000


class BetaByMetaState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"SCAN_DB": os.path.join(self.tmp.name, "scan.db")})
        self.env.start()
        self.con = store.connect()

    def tearDown(self):
        self.con.close()
        self.env.stop()
        self.tmp.cleanup()

    def beta(self, i, r4, pr4, p0=0.01, pp0=1.0):
        self.con.execute("INSERT INTO beta (token, parent, score, found_ts, p0, parent_p0, r4h, parent_r4h, done) "
                         "VALUES (?,?,?,?,?,?,?,?,1)", (f"B{i}", "P", 0.8, NOW, p0, pp0, r4, pr4))
        self.con.commit()

    def test_outlier_capped_median_and_zero_base_dropped(self):
        for i, r in enumerate((0.10, -0.20, 0.30, -0.05)):
            self.beta(i, r, 0.05)
        self.beta(10, 6_089_854.65, 0.05, p0=1e-12)   # a start price of ~0: +608,985,465 %
        self.beta(11, 3.0, 0.05, p0=0.0)              # no start price: not a measurement
        self.beta(12, 2.0, 0.05, p0=None)
        self.beta(13, 1.0, 0.05, pp0=0.0)             # the parent's start price missing: no meta state
        rows = {(r["window"], r["state"]): r for r in meta.report_rows(self.con, NOW - 10)}
        r = rows[("4h", "raste")]
        self.assertEqual((r["n"], r["capped"], r["dropped"]), (5, 1, 3))
        self.assertAlmostEqual(r["mean"], round((0.10 - 0.20 + 0.30 - 0.05 + meta.BETA_CAP) / 5, 4))
        self.assertLessEqual(r["mean"], meta.BETA_CAP)
        self.assertEqual(r["median"], 0.1)
        self.assertEqual(r["hit"], 0.6)

    def test_even_count_median_and_falling_parent(self):
        for i, r in enumerate((0.2, -0.4, -0.1, 0.0)):
            self.beta(i, r, -0.02)
        r = {(x["window"], x["state"]): x for x in meta.report_rows(self.con, NOW - 10)}[("4h", "pada")]
        self.assertEqual((r["n"], r["median"], r["mean"], r["capped"], r["dropped"]), (4, -0.05, -0.075, 0, 0))

    def test_track_never_divides_by_a_zero_start(self):
        self.con.execute("INSERT INTO beta (token, parent, score, found_ts, p0, parent_p0, done) VALUES "
                         "('Z', 'P', 0.8, ?, 0.0, 1.0, 0)", (NOW,))
        meta.track(self.con, {"Z": 5.0, "P": 1.1}, NOW + 3700)
        self.assertEqual(self.con.execute("SELECT r1h, parent_r1h FROM beta WHERE token='Z'").fetchone(), (None, 0.1))

    def test_report_data_carries_the_robust_rows(self):
        self.beta(0, 6_089_854.65, 0.05, p0=1e-12)
        self.beta(1, 0.2, 0.05)
        d = shadow.report_data(NOW + 60, con=self.con)
        b = [x for x in d["beta_by_meta_state"] if x["window"] == "4h"][0]
        self.assertEqual((b["n"], b["capped"], b["median"]), (2, 1, round((0.2 + 6_089_854.65) / 2, 4)))
        self.assertLessEqual(b["mean"], meta.BETA_CAP)


if __name__ == "__main__":
    unittest.main()
