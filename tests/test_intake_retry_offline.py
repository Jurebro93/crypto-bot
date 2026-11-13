"""13.11.: 0 demo trades on a quiet day. The scan reported ~108 tokens, but intake only looked at never-seen ones
(1-2 a minute); an earlier skip came back only with a score >= min_score, and the day's best was 32. Now a skipped
token in the day's exploration band is looked at again, at most every RETRY_MIN minutes.

    python3 -m unittest tests.test_intake_retry_offline
"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_paper  # noqa: E402
from learn import weights  # noqa: E402
from paper import sim, store  # noqa: E402

TOK = "Ab1cdEfGhJkLmNoPqRsTuVwXyZ23456789abcdepump"
CFG = {"min_score": 50}


def sig(score, tok=TOK):
    return {"token": tok, "score": score, "origin": "hype"}


class Reconsider(unittest.TestCase):
    def setUp(self):
        run_paper._LOOKED.clear()

    def test_exploration_band_reopens_old_skips_throttled(self):
        now = 1_794_500_000
        self.assertTrue(run_paper.reconsider("skip_score", sig(30), CFG, 28, "score 30 < 50", now))
        self.assertFalse(run_paper.reconsider("skip_score", sig(30), CFG, 28, "", now + 60))       # 30 min pause
        self.assertTrue(run_paper.reconsider("skip_score", sig(30), CFG, 28, "", now + 31 * 60))
        self.assertTrue(run_paper.reconsider("skip_gate", sig(30, "B" * 44), CFG, 28,
                                             "market cap $22.000 ispod $30.000", now))
        self.assertFalse(run_paper.reconsider("skip_gate", sig(30, "C" * 44), CFG, 28,
                                              "T0: mehanika ruga (mint/freeze)", now))
        self.assertFalse(run_paper.reconsider("skip_score", sig(20, "D" * 44), CFG, 28, "", now))    # under the band
        self.assertFalse(run_paper.reconsider("taken", sig(40, "E" * 44), CFG, 28, "", now))
        self.assertFalse(run_paper.reconsider("skip_rug", sig(40, "F" * 44), CFG, 28, "", now))
        self.assertTrue(run_paper.reconsider("skip_liq", sig(60, "G" * 44), CFG))                   # old rule stays


class Intake(unittest.TestCase):
    def setUp(self):
        run_paper._LOOKED.clear()
        self.tmp = tempfile.mkdtemp()
        self._ld, weights.LEARNED_DIR = weights.LEARNED_DIR, self.tmp
        self.saved = {k: getattr(run_paper, k) for k in ("DB", "HYPE_DB", "HERE", "market", "rug_verdict", "notify",
                                                          "t0_check", "hype_signals", "explore_need", "event_tokens")}
        run_paper.DB = os.path.join(self.tmp, "paper.db")
        run_paper.HYPE_DB = os.path.join(self.tmp, "hype.db")
        run_paper.HERE = self.tmp
        run_paper.market = lambda toks: {t: (0.0001, 40_000, 100_000, None) for t in toks}
        run_paper.rug_verdict = lambda con, t, cfg, now, paid=True: (None, None, [])
        run_paper.notify = lambda *a, **k: None
        run_paper.t0_check = lambda t, now: "prolaz"
        run_paper.event_tokens = lambda cfg, now=None: []
        run_paper.explore_need = lambda con, cfg, now: 28
        self.now = time.time()
        run_paper.hype_signals = lambda fresh_min=30, now=None: [
            {"token": TOK, "symbol": "OLD", "ts": self.now, "score": 32, "features": {}, "sources": {"zadrzan"},
             "url": None, "origin": "hype"}]

    def tearDown(self):
        weights.LEARNED_DIR = self._ld
        for k, v in self.saved.items():
            setattr(run_paper, k, v)

    def test_old_skip_becomes_exploration_entry(self):
        con = store.connect(run_paper.DB)
        store.add_candidate(con, {"token": TOK, "symbol": "OLD", "ts": self.now - 7200, "origin": "hype", "score": 18,
                                  "decision": "skip_score", "reason": "score 18 < 50", "sources": {"profile"},
                                  "features": {}})
        con.commit()
        con.close()
        cfg = {**sim.load_config(), "konv": {"enabled": False},
               "rules": {"ab": {"enabled": False}, "kol3": {"enabled": False}, "aktivni": {"enabled": False},
                         "povratak": {"enabled": False}, "povlacenje": {"enabled": False}}}
        opened = run_paper.intake(cfg, now=self.now, quiet=True)
        self.assertEqual([c["token"] for c in opened], [TOK])
        self.assertIn("istraživanje", opened[0]["reason"])
        con = store.connect(run_paper.DB)
        self.assertEqual(con.execute("SELECT decision FROM candidates WHERE token=?", (TOK,)).fetchone()[0], "taken")
        con.close()


if __name__ == "__main__":
    unittest.main()
