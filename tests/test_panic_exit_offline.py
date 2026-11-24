"""6.11. emergency exit (paper/sim.panic, "hitni_izlaz"), target vs real stop (exits/fit.target_vs_real) and the
learned panic_liq key (exits/learn)."""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from exits import fit, learn  # noqa: E402
from paper import sim  # noqa: E402

T0 = 1793390000
CFG = {"fee": 0.01, "slip": 0.0, "sl": -0.2, "tp": [[1.0, 0.5]], "breakeven_after_tp": True, "trail_after": 0.5,
       "trail": 0.3, "max_hold_h": 24, "rug_liq": 0.2, "panic": {"liq_drop": 0.3, "gap_s": 120}}


def pos_at(cfg=CFG):
    p = sim.open_position(1.0, 50000, T0, 50, cfg)
    sim.step(p, 1.0, 50000, T0 + 60, cfg)
    return p


class Panic(unittest.TestCase):
    def test_liquidity_drop_sells_before_stop(self):
        p = pos_at()
        sim.step(p, 0.95, 30000, T0 + 120, CFG)   # -5% price, but liquidity -40% in one tick
        self.assertFalse(p["open"])
        self.assertEqual(p["exit_reason"], "hitni_izlaz")

    def test_small_liq_change_keeps_position(self):
        p = pos_at()
        sim.step(p, 0.97, 42000, T0 + 120, CFG)   # -16% liquidity
        self.assertTrue(p["open"])

    def test_price_gap_only_with_late_tick(self):
        p = pos_at({**CFG, "sl_delay_min": 30})  # stop not armed yet: the normal stop would not fire
        c = {**CFG, "sl_delay_min": 30}
        sim.step(p, 0.75, 48000, T0 + 120, c)      # -25% in a 60 s tick: no panic (tick was on time)
        self.assertTrue(p["open"])
        q = pos_at(c)
        sim.step(q, 0.75, 48000, T0 + 60 + 300, c)   # same drop after a 5 min gap: panic
        self.assertEqual(q["exit_reason"], "hitni_izlaz")

    def test_off(self):
        c = {**CFG, "panic": None}
        p = pos_at(c)
        sim.step(p, 0.95, 30000, T0 + 120, c)
        self.assertTrue(p["open"])

    def test_target_vs_real(self):
        t = fit.target_vs_real([(-0.2, -0.22), (-0.2, -0.55), (-0.2, -0.52), (-0.2, -0.21), (-0.2, -0.2)])
        self.assertEqual(t["n"], 5)
        self.assertEqual(t["over2x"], 2)
        self.assertEqual(t["sl_med"], -0.2)
        self.assertEqual(t["real_med"], -0.22)
        self.assertEqual(t["worst10"], -0.55)
        self.assertEqual(fit.target_vs_real([]), {"n": 0})

    def test_learned_key(self):
        base = copy.deepcopy(CFG)
        self.assertEqual(learn.params_of(base)["panic_liq"], 0.3)
        self.assertIsNone(learn.to_sim(base, {"panic_liq": None})["panic"])
        self.assertEqual(learn.to_sim(base, {"panic_liq": 0.5})["panic"], {"liq_drop": 0.5, "gap_s": 120})
        self.assertEqual(learn.to_sim(base, {"sl": -0.3})["panic"], base["panic"])   # old profile: config value
        self.assertIn(None, learn.load_config()["grid"]["panic_liq"])
        self.assertIn("hitni izlaz", learn.describe({**learn.params_of(base)}))


if __name__ == "__main__":
    unittest.main()
