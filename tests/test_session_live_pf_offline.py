"""11.11.: the KOL session factor is capped by the demo's live profit factor in that session."""
import os
import sys
import sqlite3
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import sessions  # noqa: E402


def con_with(f):
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE sessions (key TEXT, n INT, hits INT, med REAL, factor REAL, ts INT)")
    for k, v in f.items():
        c.execute("INSERT INTO sessions VALUES (?,10,5,0.5,?,0)", (k, v))
    return c


class LivePF(unittest.TestCase):
    def test_losing_session_capped(self):
        st = {"sessions": {"by": {"asia": {"n": 60, "pf": 0.12}, "eu": {"n": 40, "pf": 0.53},
                                  "us": {"n": 10, "pf": 0.2}}}}
        with mock.patch("paper.rules.load", return_value=st):
            f = sessions.factors(con_with({"signal:asia": 1.3, "signal:eu": 0.9, "signal:us": 1.2}))
        self.assertEqual(f["asia"], 0.5)          # 1.0 (capped) x max(0.5, 0.12)
        self.assertAlmostEqual(f["eu"], 0.477)    # 0.9 x 0.53
        self.assertEqual(f["us"], 1.2)            # 10 trades: not measured enough
        self.assertLess(f["asia"], f["eu"] + 0.1)

    def test_no_demo_state(self):
        with mock.patch("paper.rules.load", return_value={}):
            self.assertEqual(sessions.factors(con_with({"signal:asia": 1.3}))["asia"], 1.3)


class ConfStep(unittest.TestCase):
    def test_limit_step(self):
        from learn import confmodel
        old = {"coef": {"smart_money": 1.0, "kol": 0.1}, "hype": 0.5, "bias": -2.0, "base": {"*": 0.2}}
        new = {"coef": {"smart_money": 0.5, "kol": 0.9, "x_buzz": 0.4}, "hype": 0.5, "bias": -3.0, "base": {"*": 0.2}}
        m = confmodel.limit_step(old, new)
        self.assertEqual(m["coef"]["smart_money"], 0.75)    # not halved in one run
        self.assertEqual(m["coef"]["kol"], 0.15)            # floor 0.2 x 0.25
        self.assertEqual(m["coef"]["x_buzz"], 0.05)
        self.assertEqual(m["bias"], -2.5)
        self.assertEqual(confmodel.limit_step(None, new), new)


if __name__ == "__main__":
    unittest.main()
