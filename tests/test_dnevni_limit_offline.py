"""10.11. (Jure: "Dnevni limit potrošnje je dosegnut (2,850 SOL) ... Ovo nema smisla."): max_sol_per_day limits the
Autopilot's AUTOMATIC buys; the owner's own buys ("ručno ...") and Grok's autotrades ("Grok auto ...") are not held
by it and must not use it up; the page says which buys stop.

    python3 -m unittest tests.test_dnevni_limit_offline
"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trade import executor  # noqa: E402

NOW = int(time.time())
CFG = {"max_sol_per_trade": 0.5, "max_sol_per_day": 0.5, "max_open": 20, "max_loss_day": 5, "day_tz": "Europe/Zagreb"}


class Limit(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.con = executor.connect(os.path.join(self.d, "trade.db"))

    def tearDown(self):
        self.con.close()

    def pos(self, sol, reason, tok):
        self.con.execute("INSERT INTO positions (token, opened_ts, mode, status, sol_in, reason) VALUES (?,?,?,?,?,?)",
                         (tok, NOW, "dry", "open", sol, reason))
        self.con.commit()

    def test_own_and_grok_buys_do_not_use_up_the_automatic_limit(self):
        self.pos(2.0, "ručno (pravi trade)", "A")
        self.pos(0.6, "ručno (pravi trade)", "B")
        self.pos(0.25, "Grok auto (MCP)", "C")
        self.assertEqual(executor.auto_spent(self.con, NOW, "dry", CFG["day_tz"]), 0)
        self.assertIsNone(executor.gate_buy(self.con, CFG, 0.1, NOW, False, token="D"))      # a copy still buys
        self.pos(0.45, "copy KOL ansem", "E")
        self.assertAlmostEqual(executor.auto_spent(self.con, NOW, "dry", CFG["day_tz"]), 0.45)
        why = executor.gate_buy(self.con, CFG, 0.1, NOW, False, token="F")
        self.assertIn("dnevni limit automatskih kupnji", why)
        self.assertIsNone(executor.gate_buy(self.con, CFG, 0.1, NOW, False, token="G", manual=True))   # his own: yes


if __name__ == "__main__":
    unittest.main()
