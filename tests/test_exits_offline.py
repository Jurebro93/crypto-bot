"""Exit learning, moonbag/KOL rules and competition auto sell, offline.

    python3 -m unittest tests.test_exits_offline
"""
import json
import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paper import sim  # noqa: E402

CFG = sim.load_config()
T0 = 1_800_000_000


def _path(rets, liq=50_000, dt=60):
    return [(T0 + dt * (i + 1), 1.0 + r, liq) for i, r in enumerate(rets)]


class Rules(unittest.TestCase):
    def test_cost_take_profit_returns_the_stake(self):
        cfg = {**CFG, "tp": [[1.0, "cost"]], "trail_tiers": [[5.0, 0.5]], "sl_after_tp": -0.9, "stale_min": None}
        pos = sim.open_position(1.0, 1e9, T0, 50, cfg)
        sim.step(pos, 2.0, 1e9, T0 + 60, cfg)
        self.assertAlmostEqual(pos["realized"], 50, delta=0.5)
        self.assertTrue(0.4 < pos["left"] < 0.6)

    def test_moonbag_rides_after_profit(self):
        cfg = {**CFG, "tp": [[0.5, 0.5]], "trail_tiers": [[0.5, 0.2]], "moonbag": 0.2, "moon_trail": 0.6,
               "sl_after_tp": 0.0, "stale_min": None, "max_hold_h": 1, "moon_hold_h": 72}
        r = sim.replay(1.0, 1e9, T0, _path([0.6, 0.9, 0.5, 0.3, 2.0, 9.0, 5.0], liq=1e9), cfg)
        self.assertEqual(r["exit_reason"], "open")  # the bag survived the normal trailing (+90% -> +50%)
        pos = sim.open_position(1.0, 1e9, T0, 50, cfg)
        for ts, p, liq in _path([0.6, 0.9, 0.5], liq=1e9):
            sim.step(pos, p, liq, ts, cfg)
        self.assertTrue(pos["bag"])
        self.assertAlmostEqual(pos["left"], 0.2)

    def test_stale_exit_and_kol_hold(self):
        cfg = {**CFG, "stale_min": 30, "stale_ret": 0.1, "kol_hold_min": 60}
        flat = _path([0.02] * 40)
        self.assertEqual(sim.replay(1.0, 50_000, T0, flat, cfg)["exit_reason"], "stale")
        r = sim.replay(1.0, 50_000, T0, flat, cfg, calls=[T0 + 600])
        self.assertEqual(r["exit_reason"], "open")  # an influencer called it 10 min in: keep waiting


def _fake_paths(n, seed=1):
    """Spike-then-dump paths: a quick take profit beats holding."""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        top = rng.choice([0.3, 0.6, 1.2, 3.0])
        pts = [(60 * k, 1 + top * k / 5, 50_000) for k in range(1, 6)]
        pts += [(300 + 600 * k, (1 + top) * (0.7 ** k), 50_000) for k in range(1, 10)]
        out.append({"src": "seed", "klasa": "moonshot", "ts": T0 + i * 3600, "liq0": 50_000, "mcap0": 50_000,
                    "pts": pts, "entry": "test"})
    return out


class Learning(unittest.TestCase):
    def setUp(self):
        from learn import weights
        self.tmp = tempfile.mkdtemp()
        self._old = weights.LEARNED_DIR
        weights.LEARNED_DIR = self.tmp

    def tearDown(self):
        from learn import weights
        weights.LEARNED_DIR = self._old

    def test_compress_keeps_extremes(self):
        from exits import paths
        pts = [(i, 1 + (i % 7) * 0.001, 1) for i in range(500)] + [(500, 5.0, 1), (501, 0.5, 1)]
        c = paths.compress(pts, 0.03, 40)
        self.assertLessEqual(len(c), 40)
        self.assertIn(5.0, [m for _, m, _ in c])

    def test_fit_applies_only_with_enough_paths_and_both_halves(self):
        from exits import fit, learn, profiles
        few = fit.run(os.path.join(self.tmp, "none.db"), seed=_fake_paths(50))
        self.assertFalse(any(r["applied"] for r in few))
        rep = fit.run(os.path.join(self.tmp, "none.db"), seed=_fake_paths(400))
        ok = [r for r in rep if r["applied"]]
        self.assertTrue(ok)
        for r in ok:
            self.assertGreater(r["new"]["score"], r["now"]["score"])
            self.assertTrue(all(b >= a for a, b in r["halves"]))
        state = profiles.load()
        cfg = profiles.for_trade(CFG, "moonshot", state=state)
        self.assertEqual(cfg["exit_profile"], "moonshot@1")
        base_idx = learn.load_config()["grid"]["sl"].index(CFG["sl"])
        new_idx = learn.load_config()["grid"]["sl"].index(cfg["sl"])
        self.assertLessEqual(abs(new_idx - base_idx), learn.load_config()["max_steps"])

    def test_rollback_restores_previous(self):
        from exits import profiles
        state = {"profiles": {}}
        profiles.put(state, "moonshot", {"sl": -0.2}, {})
        profiles.put(state, "moonshot", {"sl": -0.6}, {})
        profiles.rollback(state, "moonshot", "test")
        self.assertEqual(state["profiles"]["moonshot"]["params"], {"sl": -0.2})


class MedianRollback(unittest.TestCase):
    """5.11. morning report: moonshot/SAD v4 had a -33% median after 50 live trades and was not rolled back,
    because a few big wins kept its score up. A clearly worse median now rolls it back too."""

    def _run(self, live_rets, replay_ret):
        from unittest import mock
        from exits import fit, learn, profiles
        state = {"profiles": {}}
        profiles.put(state, "moonshot/us", {"sl": -0.2}, {})
        profiles.put(state, "moonshot/us", {"sl": -0.6}, {})
        trades = [{"ret": r, "entry_px": 1.0, "entry_liq": 1e5, "opened": T0, "path": []} for r in live_rets]
        ecfg = {**learn.load_config(), "rollback_margin": 9.0}   # score test off: only the median decides here
        with mock.patch.object(fit, "live_trades", return_value=trades), \
                mock.patch.object(fit.sim, "replay", return_value={"ret": replay_ret}):
            notes = fit.check_rollback(state, "x.db", CFG, ecfg, T0)
        return state, notes

    def test_worse_median_rolls_back(self):
        rets = [-0.33] * 40 + [5.0] * 10   # 50 trades, a few big wins, median -33%
        state, notes = self._run(rets, -0.1)
        self.assertEqual(len(notes), 1)
        self.assertIn("medijan", notes[0]["note"])
        self.assertEqual(state["profiles"]["moonshot/us"]["params"], {"sl": -0.2})
        from exits import fit
        self.assertTrue(fit.recently_rolled(state, "moonshot/us", T0 + 86400, 3))
        self.assertFalse(fit.recently_rolled(state, "moonshot/us", T0 + 4 * 86400, 3))

    def test_similar_median_stays(self):
        state, notes = self._run([-0.12] * 40 + [5.0] * 10, -0.1)
        self.assertEqual(notes, [])
        self.assertEqual(state["profiles"]["moonshot/us"]["params"], {"sl": -0.6})

    def test_too_few_trades_wait(self):
        state, notes = self._run([-0.33] * 25, -0.1)
        self.assertEqual(notes, [])


class AutoSell(unittest.TestCase):
    def setUp(self):
        from league import store
        self.store = store
        self.db = os.path.join(tempfile.mkdtemp(), "league.db")
        self.con = store.connect(self.db)

    def _buy(self):
        return self.store.buy(self.con, "Ivan", "Mint1", "AAA", 100, 1.0, 1e9, mcap=100_000)

    def test_parse_percent_and_mcap(self):
        from league import auto
        self.assertAlmostEqual(auto.parse_level("100%", 1.0, 1e5, "tp")[0], 2.0)
        self.assertAlmostEqual(auto.parse_level("30", 1.0, 1e5, "sl")[0], 0.7)
        self.assertAlmostEqual(auto.parse_level("$500k", 1.0, 1e5, "tp")[0], 5.0)
        self.assertAlmostEqual(auto.parse_level("1.2M", 1.0, 1e5, "tp")[0], 12.0)
        with self.assertRaises(ValueError):
            auto.parse_level("abc", 1.0, 1e5, "tp")

    def test_tp_sl_sells_whole_position(self):
        from league import auto
        tid = self._buy()
        auto.set_auto(self.con, "Ivan", tid, "tpsl", "$300k", "-30%")
        mk = lambda ts: {"Mint1": (2.0, 1e9, "", 2e5)}  # noqa: E731
        self.assertEqual(auto.run_once(self.con, mk), [])
        mk = lambda ts: {"Mint1": (3.1, 1e9, "", 3.1e5)}  # noqa: E731
        done = auto.run_once(self.con, mk)
        self.assertIn("TP", done[0][2])
        t = self.store.trades(self.con, "Ivan")[0]
        self.assertEqual(t["status"], "closed")
        self.assertGreater(t["pnl_usd"], 200)

    def test_smart_partial_then_close_counts_everything(self):
        from league import auto
        tid = self._buy()
        auto.set_auto(self.con, "Ivan", tid, "smart")
        for p in (1.05, 1.3, 2.2, 3.5, 1.2, 0.5, 0.2):
            auto.run_once(self.con, lambda ts, p=p: {"Mint1": (p, 1e9, "", p * 1e5)})
        t = self.store.trades(self.con, "Ivan")[0]
        self.assertEqual(t["status"], "closed")
        self.assertGreater(t["pnl_usd"], 0)  # took profit on the way up, did not ride it back to -80%


if __name__ == "__main__":
    unittest.main()


class Sessions(unittest.TestCase):
    def test_session_split_and_profile_choice(self):
        from exits import paths, profiles
        self.assertEqual(paths.session_of(1_800_000_000 - 1_800_000_000 % 86400 + 3 * 3600), "asia")
        self.assertEqual(paths.session_of(1_800_000_000 - 1_800_000_000 % 86400 + 10 * 3600), "eu")
        self.assertEqual(paths.session_of(1_800_000_000 - 1_800_000_000 % 86400 + 20 * 3600), "us")
        state = {"profiles": {}}
        profiles.put(state, "moonshot", {"sl": -0.2}, {})
        profiles.put(state, "moonshot/us", {"sl": -0.3}, {})
        self.assertEqual(profiles.current(state, "moonshot", CFG, "us")[1], "moonshot/us@1")
        self.assertEqual(profiles.current(state, "moonshot", CFG, "eu")[1], "moonshot@1")
