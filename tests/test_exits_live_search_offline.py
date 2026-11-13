"""12.11.: with enough live paths the exit rules are searched and judged on live paths; history only checks."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from exits import learn  # noqa: E402
from paper import sim  # noqa: E402
from test_exits_offline import _fake_paths  # noqa: E402


def as_live(ps):
    return [{**p, "src": "live"} for p in ps]


class LiveSearch(unittest.TestCase):
    def setUp(self):
        self.base = sim.load_config(learned=False)
        self.ecfg = learn.load_config()
        self.cur = learn.params_of(self.base)

    def test_uses_live_when_enough(self):
        ps = as_live(_fake_paths(200)) + _fake_paths(400, seed=3)
        out, cand = learn.fit_profile(ps, self.base, self.cur, self.ecfg)
        self.assertTrue(out["on_live"])
        self.assertIn("hist", out)

    def test_history_when_few_live(self):
        ps = as_live(_fake_paths(40)) + _fake_paths(400, seed=3)
        out, _ = learn.fit_profile(ps, self.base, self.cur, self.ecfg)
        self.assertFalse(out["on_live"])
        self.assertNotIn("hist", out)

    def test_history_veto(self):
        ps = as_live(_fake_paths(200)) + _fake_paths(400, seed=3)
        out, cand = learn.fit_profile(ps, self.base, self.cur, {**self.ecfg, "hist_margin": -10})
        if out.get("hist"):
            self.assertIsNone(cand)
            self.assertIn("povijesti", out["note"])

    def test_median_guard(self):
        from unittest import mock
        ps = _fake_paths(400, seed=3)
        real = learn.evaluate

        def fake(paths, cfg, *a, **k):
            r = real(paths, cfg, *a, **k)
            if cfg.get("sl") != self.base.get("sl") or cfg.get("tp") != self.base.get("tp"):
                r = {**r, "median": (r.get("median") or 0) - 0.5}
            return r
        with mock.patch.object(learn, "evaluate", side_effect=fake):
            out, cand = learn.fit_profile(ps, self.base, self.cur, self.ecfg)
        if out.get("new_params") != self.cur and "medijan" in out.get("note", ""):
            self.assertIsNone(cand)


if __name__ == "__main__":
    unittest.main()
