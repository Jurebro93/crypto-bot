"""9.11.: stabilni and default learn the weights on "+30% within 72 h" (shadow.label_dug, outcomes.shadow_rows)."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learn import outcomes, shadow  # noqa: E402

T0 = 1793390000
H = 3600
TG = {"stabilni": {"ret": 0.3, "h": 72}, "default": {"ret": 0.3, "h": 72}}


class Dug(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.db, self.hype = os.path.join(d, "shadow.db"), os.path.join(d, "hype.db")
        h = sqlite3.connect(self.hype)
        h.execute("CREATE TABLE hype_snapshots (token TEXT, ts INTEGER, price REAL, liquidity REAL)")
        for i in range(1, 73):
            h.execute("INSERT INTO hype_snapshots VALUES ('UP', ?, ?, 1e5)", (T0 + i * H, 1.0 + 0.5 * i / 72))
            h.execute("INSERT INTO hype_snapshots VALUES ('FLAT', ?, 1.05, 1e5)", (T0 + i * H,))
            if i < 20:
                h.execute("INSERT INTO hype_snapshots VALUES ('SHORT', ?, 2.0, 1e5)", (T0 + i * H,))
        h.commit()
        h.close()
        con = shadow.connect(self.db)
        for pid, tok, kl in (("a", "UP", "stabilni"), ("b", "FLAT", "stabilni"), ("c", "SHORT", None),
                             ("d", "UP", "moonshot")):
            con.execute("INSERT INTO points (id, token, point, ts, klasa, price, liq, features, status, hit, ret, "
                        "max2_ret) VALUES (?,?,?,?,?,1.0,1e5,?, 'gotovo', 0, 0.0, 0.05)",
                        (pid, tok, "mc100k", T0, kl, json.dumps({"x": 1})))
        con.commit()
        self.con = con

    def tearDown(self):
        self.con.close()

    def test_label_and_rows(self):
        n = shadow.label_dug(self.con, self.hype, None, T0 + 80 * H, shadow.DEFAULT, TG)
        self.assertEqual(n, 2)
        got = {r[0]: (r[1], r[2]) for r in self.con.execute("SELECT id, hit_dug, max_dug FROM points")}
        self.assertEqual(got["a"][0], 1)
        self.assertEqual(got["b"][0], 0)
        self.assertEqual(got["c"][0], -1)        # prices cover less than half the window
        self.assertIsNone(got["d"][0])           # moonshot keeps the 24 h target
        cfg = {**outcomes.config(), "cilj_klasa": TG}
        rs = {r["id"]: r for r in outcomes.shadow_rows(cfg, T0 + 80 * H, self.db)}
        self.assertTrue(rs["a"]["hit"])
        self.assertFalse(rs["b"]["hit"])
        self.assertNotIn("c", rs)
        self.assertFalse(rs["d"]["hit"])
        self.assertNotIn("cilj_dug", rs["d"])

    def test_not_due_before_window(self):
        self.assertEqual(shadow.label_dug(self.con, self.hype, None, T0 + 50 * H, shadow.DEFAULT, TG), 0)


if __name__ == "__main__":
    unittest.main()
