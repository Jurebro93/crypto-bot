"""15.11. popodne: a real midcap buy (league source "veliki: ...", switch pravi_novac_veliki) is held to
veliki/gate.real_caps (0.1 SOL, 5 open, 20 buys a day, day loss 0.3 SOL, cost cap 6 %) INSTEAD of LIVE_CAPS: the
first real midcap buy (12:48) was refused by LIVE_CAPS' 0.3 SOL of automatic buys a day that other strategies had used.

    python3 -m unittest tests.test_veliki_executor_caps_offline
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.test_pravi_novac_sve_offline import SwitchBase  # noqa: E402
from trade import executor, settings  # noqa: E402


class VelikiCaps(SwitchBase):
    def on(self):
        settings.set_flag(self.con, "pravi_novac_veliki", "live", settings.owner())
        settings._FLAG_CACHE.clear()

    def test_caps_are_the_gates(self):
        c = executor.veliki_caps({})
        self.assertEqual((c["size_sol"], c["max_open"], c["max_buys_day"], c["max_loss_day"]), (0.2, 5, 20, 0.3))
        self.assertAlmostEqual(c["max_sol_per_day"], 4.1)   # 20 buys x 0.2 SOL + 0.1
        self.assertTrue(executor.is_veliki("veliki: dnevni raspon"))
        self.assertFalse(executor.is_veliki("konsenzus S1"))

    def test_other_strategies_spend_does_not_block_a_midcap_buy(self):
        self.on()
        self.live_rows(7, reason="copy KOL x", status="closed", closed=int(self.now - 10), sol_back=0.1)
        self.assertIn("dnevni limit automatskih kupnji", self.gate() or "")   # LIVE_CAPS: 0.7 of 0.3 used
        self.assertIsNone(self.gate(veliki=True))

    def test_midcap_day_count_and_spend(self):
        self.on()
        self.live_rows(20, reason="veliki: dnevni raspon", status="closed", closed=int(self.now - 10), sol_back=0.1)
        self.assertIn("strop pravi_novac_veliki max_buys_day", self.gate(veliki=True) or "")

    def test_day_loss_of_every_live_position_stops_it(self):
        self.on()
        self.live_rows(4, reason="copy KOL x", status="closed", closed=int(self.now - 10), sol_back=0.0)
        self.assertIn("max_loss_day", self.gate(veliki=True) or "")

    def test_max_open_counts_every_strategy(self):
        self.on()
        self.live_rows(5, reason="copy KOL x", status="open")
        self.assertIn("max_open", self.gate(veliki=True) or "")

    def test_switch_off_blocks_the_buy_itself(self):
        r = executor.buy(self.con, dict(self.cfg, mode="live"), "Tok1111", "T", now=self.now,
                         reason="veliki: dnevni raspon", size_sol=0.1)
        self.assertEqual(r["status"], "blocked")
        self.assertIn("pravi_novac_veliki", r["error"])
        self.assertEqual(self.swaps, [])


if __name__ == "__main__":
    unittest.main()


class EquityFloor(SwitchBase):
    """15.11. navečer (vlasnik: "ako padne ispod jedne solane, onda ćemo ugasiti"): automatic real buys stop under
    1 SOL of wallet value; his manual buys are not held."""
    def snap(self, sol, tokens=0.0, age=60):
        self.con.execute("CREATE TABLE IF NOT EXISTS equity (ts INTEGER, sol REAL, usdc REAL, tokens_sol REAL, "
                         "sol_usd REAL, usd_eur REAL, flow_sol REAL, src TEXT)")
        self.con.execute("INSERT INTO equity VALUES (?,?,?,?,?,?,?,?)", (int(self.now - age), sol, 0.0, tokens, 150.0,
                                                                        0.9, 0.0, "live"))
        self.con.commit()

    def test_under_one_sol_stops_automatic_buys(self):
        self.snap(0.7, tokens=0.2)
        self.assertIn("ispod poda 1 SOL", self.gate(balance=5.0) or "")

    def test_above_the_floor_passes_the_floor(self):
        self.snap(0.9, tokens=0.2)
        self.assertNotIn("ispod poda", self.gate(balance=5.0) or "")

    def test_manual_buy_is_not_held(self):
        self.snap(0.5)
        self.assertNotIn("ispod poda", self.gate(balance=5.0, manual=True) or "")

    def test_stale_snapshot_uses_balance_and_open_stakes(self):
        self.snap(5.0, age=7200)
        self.assertIn("stanje SOL-a", self.gate(balance=0.5) or "")
