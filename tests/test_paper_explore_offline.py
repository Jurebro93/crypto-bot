"""Exploration entries: more, smaller demo trades below the main score bar, never copied to real trading.

    python3 -m unittest tests.test_paper_explore_offline
"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_paper  # noqa: E402
from paper import sim, store  # noqa: E402


class Explore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._db = run_paper.DB
        run_paper.DB = os.path.join(self.tmp, "paper.db")
        self.now = time.time()
        con = store.connect(run_paper.DB)
        for i in range(40):  # yesterday's candidates: scores 0..39
            store.add_candidate(con, {"token": f"old{i}", "ts": self.now - 3600, "origin": "hype", "score": i,
                                      "decision": "ignored"})
        con.commit()
        con.close()
        self.sigs = [{"token": "A", "symbol": "A", "ts": self.now, "score": 60, "features": {}, "sources": set(),
                      "url": None, "origin": "hype"},
                     {"token": "B", "symbol": "B", "ts": self.now, "score": 35, "features": {}, "sources": set(),
                      "url": None, "origin": "hype"},
                     {"token": "C", "symbol": "C", "ts": self.now, "score": 12, "features": {}, "sources": set(),
                      "url": None, "origin": "hype"}]
        self.patch = {"hype_signals": lambda now=None: [dict(s) for s in self.sigs], "event_tokens": lambda c, n=None: [],
                      "market": lambda toks: {t: (1.0, 50_000, 100_000, None) for t in toks},
                      "rug_verdict": lambda con, t, cfg, now, paid=True: (None, None, []), "klasa_of": lambda toks: {},
                      "notify": lambda *a, **k: None}
        self.saved = {k: getattr(run_paper, k) for k in self.patch}
        for k, v in self.patch.items():
            setattr(run_paper, k, v)

    def tearDown(self):
        run_paper.DB = self._db
        for k, v in self.saved.items():
            setattr(run_paper, k, v)

    def test_core_and_explore_entries(self):
        cfg = sim.load_config()
        opened = run_paper.intake(cfg, now=self.now, quiet=True)
        self.assertEqual({c["token"] for c in opened}, {"A", "B"})  # C is below the explore floor
        con = store.connect(run_paper.DB)
        modes = {t: (json.loads(c)["entry_mode"], s) for t, c, s in con.execute("SELECT token, config, size_usd FROM trades")}
        self.assertEqual(modes["A"], ("core", cfg["size_usd"]))
        self.assertEqual(modes["B"], ("explore", cfg["explore"]["size_usd"]))
        self.assertEqual(run_paper._n_open(con), 1)  # exploration trades have their own cap

    def test_explore_off(self):
        cfg = {**sim.load_config(), "explore": {"enabled": False}}
        opened = run_paper.intake(cfg, now=self.now, quiet=True)
        self.assertEqual({c["token"] for c in opened}, {"A"})


if __name__ == "__main__":
    unittest.main()
