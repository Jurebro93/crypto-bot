"""League round 2 (paper/liga.py): only kinds of trades that proved themselves count for the bot."""
import json
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paper import liga, store  # noqa: E402

NOW = 1_800_000_000


class Liga(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.executescript(store.SCHEMA)
        liga._CACHE.update(ts=0, data=None)

    def add(self, mode, arm, rets, age_d=1):
        for i, r in enumerate(rets):
            self.con.execute("INSERT INTO trades (token, opened_ts, closed_ts, status, ret, state, config) "
                             "VALUES (?,?,?,?,?,?,?)", (f"T{mode}{arm}{i}", NOW - age_d * 86400 - 3600,
                                                       NOW - age_d * 86400, "closed", r, "{}",
                                                       json.dumps({"entry_mode": mode, "arm": arm})))

    def test_only_proven_groups_count(self):
        self.add("explore", "tg+x|us", [0.4, 0.3, -0.1, 0.5, 0.2] * 4)        # wins, enough trades
        self.add("explore", "dex|asia", [-0.25, -0.3, 0.1, -0.2, -0.5] * 4)   # loses
        self.add("core", "x|eu", [0.5, 0.4])                                  # too few to judge
        self.add("explore", "pump|eu", [2.0] * 20, age_d=10)                  # too old
        g = liga.groups(self.con, NOW)
        self.assertTrue(g["explore:tg+x|us"]["proven"])
        self.assertFalse(g["explore:dex|asia"]["proven"])
        self.assertFalse(g["core:x|eu"]["proven"])
        self.assertNotIn("explore:pump|eu", g)
        c = {"entry_mode": "explore", "arm": "tg+x|us"}
        self.assertTrue(liga.flag(self.con, c, {}, NOW))
        self.assertEqual(c["liga_group"], "explore:tg+x|us")
        d = {"entry_mode": "explore", "arm": "dex|asia"}
        self.assertFalse(liga.flag(self.con, d, {}, NOW))
        self.assertFalse(liga.flag(self.con, {"entry_mode": "x", "arm": "y"}, {"liga": {"enabled": False}}, NOW))

    def test_big_winner_capped(self):
        self.add("konv", "x|us", [50.0] + [-0.3] * 19)  # one lucky 50x must not prove a losing kind
        self.assertFalse(liga.groups(self.con, NOW)["konv:x|us"]["proven"])


if __name__ == "__main__":
    unittest.main()
