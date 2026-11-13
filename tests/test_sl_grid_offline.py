"""Stop loss grid (Nicholas 2.11.): stop delay in the sim, shadow-book paths for exit learning, SL x delay table."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from exits import learn  # noqa: E402
from learn import shadow  # noqa: E402
from paper import sim  # noqa: E402

T0 = 1_800_000_000


def dip_then_run():
    """-30% at 5 min, back above entry at 40 min, 3x at 3 h: a stop that arms immediately sells the dip."""
    return [(T0 + 60, 0.95, 5e4), (T0 + 300, 0.70, 5e4), (T0 + 1200, 0.85, 5e4), (T0 + 2400, 1.05, 5e4),
            (T0 + 3 * 3600, 3.0, 5e4), (T0 + 6 * 3600, 2.6, 5e4)]


class Delay(unittest.TestCase):
    def setUp(self):
        self.base = sim.load_config(learned=False)

    def test_stop_waits_for_delay(self):
        # panic off: the -26% tick inside the delay would be an emergency exit (learned separately, grid panic_liq)
        cfg = {**self.base, "sl": -0.2, "sl_delay_min": 0, "panic": None}
        r0 = sim.replay(1.0, 5e4, T0, dip_then_run(), cfg)
        self.assertEqual(r0["exit_reason"], "stop_loss")
        r15 = sim.replay(1.0, 5e4, T0, dip_then_run(), {**cfg, "sl_delay_min": 15})
        self.assertNotEqual(r15["exit_reason"], "stop_loss")
        self.assertGreater(r15["ret"], r0["ret"])

    def test_rug_exits_even_during_delay(self):
        pts = [(T0 + 60, 0.25, 5e4), (T0 + 600, 1.5, 5e4)]
        r = sim.replay(1.0, 5e4, T0, pts, {**self.base, "sl": -0.2, "sl_delay_min": 60})
        self.assertIn(r["exit_reason"], ("rug", "stop_loss"))
        self.assertLess(r["ret"], -0.5)

    def test_params_and_describe(self):
        p = learn.params_of({**self.base, "sl_delay_min": 30})
        self.assertEqual(p["sl_delay_min"], 30)
        self.assertIn("30 min", learn.describe(p))
        self.assertEqual(learn.to_sim(self.base, p)["sl_delay_min"], 30)


class ShadowPaths(unittest.TestCase):
    def test_exit_paths_keep_dips_and_kol_flag(self):
        tmp = tempfile.mkdtemp()
        db = os.path.join(tmp, "shadow.db")
        con = shadow.connect(db)
        raw = [(T0 + i * 60, 1.0 + (0.001 * i if i != 7 else -0.4), 5e4) for i in range(1, 400)]
        comp = shadow._compress(1.0, T0, raw)
        self.assertLessEqual(len(comp), 100)
        self.assertIn(0.6, [round(x[1], 3) for x in comp])  # the -40% dip survives the thinning
        for i, (tok, f) in enumerate((("A", {"kol_x": 1.0}), ("B", {}), ("C", {}))):
            con.execute("INSERT INTO points (id, token, symbol, point, ts, klasa, sess, price, liq, mcap, score, kupljeno, "
                        "features, status, path) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'gotovo',?)",
                        (f"p{i}", tok, "S", "mc100k", T0 + i, "moonshot", "us", 1.0, 5e4, 1e5, 50, 0, json.dumps(f),
                         json.dumps(comp)))
        con.commit()
        con.close()
        ps = shadow.exit_paths(T0 - 10, skip_tokens={"C"}, path=db)
        self.assertEqual(sorted(p["token"] for p in ps), ["A", "B"])
        self.assertEqual({p["token"]: p["kol_sig"] for p in ps}, {"A": True, "B": False})
        self.assertEqual(ps[0]["src"], "shadow")
        self.assertEqual(len(ps[0]["pts"][0]), 3)


class Grid(unittest.TestCase):
    def test_table_and_search_with_old_profile(self):
        base = sim.load_config(learned=False)
        ecfg = learn.load_config()
        rel = [(t - T0, m, l) for t, m, l in dip_then_run()]
        paths = [{"src": "shadow", "klasa": "moonshot", "ts": T0 + i, "liq0": 5e4, "pts": rel} for i in range(30)]
        cur = learn.params_of(base)
        cur.pop("sl_delay_min")  # a profile learned before the delay existed
        g = learn.sl_grid(paths, base, cur, ecfg)
        n_sl, n_d = len([x for x in ecfg["grid"]["sl"] if x > -0.95]), len(ecfg["grid"]["sl_delay_min"])
        self.assertEqual(len(g["rows"]), n_sl * n_d + 1)
        best = max(g["rows"], key=lambda r: r["score"])
        self.assertTrue(best["sl"] is None or best["delay"] > 0 or best["sl"] <= -0.3)
        cand = learn.search(paths, base, cur, ecfg)
        self.assertIn("sl_delay_min", cand)


if __name__ == "__main__":
    unittest.main()
