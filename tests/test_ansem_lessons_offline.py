"""Lessons from the 31.10. demo day (ANSEM +559% while 11 of 12 other winners closed at ~+10%):
the stop after a take profit must not sit above the price, score bands learn like arms, hand sales.

    python3 -m unittest tests.test_ansem_lessons_offline
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_paper  # noqa: E402
from paper import arms, sim, store  # noqa: E402

# the profile the demo traded with on 31.10.: TP +10/+30/+60%, after the first TP the rest's stop at +30%
PROFILE = dict(sl=-0.15, tp=[[0.1, 0.3], [0.3, 0.3], [0.6, 0.2]], sl_after_tp=0.3,
               trail_tiers=[[0.5, 0.35], [2.0, 0.5], [9.0, 0.6]], stale_min=None, max_hold_h=24)


def cfg(**kw):
    return {**sim.load_config(learned=False), **PROFILE, **kw}


class AfterTpStop(unittest.TestCase):
    def test_small_tp_no_longer_sells_everything(self):
        # billy / ROCCO / HOOD on 31.10.: +10% -> 30% sold by TP and the other 70% by a +30% "breakeven" stop on the
        # same tick. Now the 70% stays (protected at breakeven) and rides the climb.
        path = [(60 * i, 1.0 * 1.05 ** i, 50_000) for i in range(1, 40)]
        r = sim.replay(1.0, 50_000, 0, path, cfg(), size_usd=20)
        self.assertGreater(r["ret"], 1.0)
        old = sim.replay(1.0, 50_000, 0, path, cfg(lock_gap=-1), size_usd=20)  # lock always armed = old mechanics
        self.assertEqual(old["exit_reason"], "breakeven")
        self.assertLess(old["ret"], 0.12)

    def test_rest_protected_at_breakeven_until_lock_arms(self):
        c = cfg()
        pos = sim.open_position(1.0, 50_000, 0, 20, c)
        sim.step(pos, 1.12, 50_000, 60, c)  # first TP
        self.assertTrue(pos["open"])
        self.assertEqual(sim.after_tp_stop(pos, c), 0.0)
        sim.step(pos, 1.5, 50_000, 120, c)  # peak +50% >= 1.3 * 1.1 -> the +30% lock arms
        self.assertEqual(sim.after_tp_stop(pos, c), 0.3)
        sim.step(pos, 1.28, 50_000, 180, c)
        self.assertFalse(pos["open"])
        self.assertEqual(pos["exit_reason"], "breakeven")

    def test_gap_over_all_tps_keeps_ansem_behaviour(self):
        c = cfg()
        pos = sim.open_position(1.43e-5, 8_300, 0, 20, c)
        sim.step(pos, 4.49e-5, 24_000, 60, c)  # one candle +214%: all three TPs, 80% sold
        self.assertAlmostEqual(pos["left"], 0.2)
        self.assertEqual(sim.after_tp_stop(pos, c), 0.3)

    def test_negative_lock_and_plain_breakeven(self):
        pos = {"tp_done": 1, "peak": 0.1}
        self.assertEqual(sim.after_tp_stop(pos, {"sl_after_tp": -0.15}), -0.15)
        self.assertEqual(sim.after_tp_stop(pos, {"breakeven_after_tp": True}), 0.0)
        self.assertIsNone(sim.after_tp_stop({"tp_done": 0, "peak": 1}, {"sl_after_tp": 0.3}))


class ScoreBands(unittest.TestCase):
    def test_band_names(self):
        self.assertEqual(arms.band_of(31), "ocjena do 35")
        self.assertEqual(arms.band_of(42), "ocjena 35-45")
        self.assertEqual(arms.band_of(49), "ocjena 45+")

    def test_stats_count_bands_and_skip_hand_sales(self):
        con = store.connect(os.path.join(tempfile.mkdtemp(), "paper.db"))
        rows = [(48, -0.5, False), (47, -0.6, False), (31, 2.7, False), (30, 0.1, True)]
        for i, (score, ret, manual) in enumerate(rows):
            state = {"fills": [{"reason": "rucno" if manual else "stop_loss"}]}
            con.execute("INSERT INTO trades (id, token, status, ret, state, config) VALUES (?,?,?,?,?,?)",
                        (i + 1, f"t{i}", "closed", ret, json.dumps(state),
                         json.dumps({"arm": "dex|us", "entry_mode": "explore"})))
            store.add_candidate(con, {"token": f"t{i}", "ts": 0, "origin": "hype", "score": score,
                                      "decision": "taken", "trade_id": i + 1})
        st = arms.stats(con)
        self.assertEqual(st["ocjena 45+"], [0, 2])
        # the hand-sold trade does not count; since 2.11. a win counts by size (+270% = 3 wins' worth)
        self.assertEqual(st["ocjena do 35"], [3.0, 0])
        self.assertEqual(st["dex|us"], [3.0, 2])


class ManualExit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._db = run_paper.DB
        run_paper.DB = os.path.join(self.tmp, "paper.db")
        self.price = 2.0
        self.patch = {"market": lambda toks: {t: (self.price, 50_000, 100_000, None) for t in toks},
                      "kol_calls": lambda toks, since: {}, "kol_sells": lambda toks, since: {},
                      "notify": lambda *a, **k: None}
        self.saved = {k: getattr(run_paper, k) for k in self.patch}
        for k, v in self.patch.items():
            setattr(run_paper, k, v)
        self.cfg = cfg(tp=[[5.0, 0.5]])
        con = store.connect(run_paper.DB)
        pos = sim.open_position(1.0, 50_000, time.time() - 120, 20, self.cfg)
        self.tid = store.open_trade(con, "T", "T", pos, {"tp": self.cfg["tp"]}, 10_000)
        con.commit()
        con.close()

    def tearDown(self):
        run_paper.DB = self._db
        for k, v in self.saved.items():
            setattr(run_paper, k, v)

    def _state(self):
        con = sqlite3.connect(run_paper.DB)
        st, status = con.execute("SELECT state, status FROM trades WHERE id=?", (self.tid,)).fetchone()
        con.close()
        return json.loads(st), status

    def test_partial_then_all(self):
        con = store.connect(run_paper.DB)
        self.assertTrue(store.request_exit(con, self.tid, 0.5, "Jure"))
        con.commit()
        con.close()
        run_paper.tick(self.cfg, quiet=True)
        st, status = self._state()
        self.assertEqual(status, "open")
        self.assertAlmostEqual(st["left"], 0.5)
        self.assertEqual(st["fills"][-1]["reason"], "rucno")
        con = store.connect(run_paper.DB)
        self.assertEqual(store.pending_exits(con), {})
        store.request_exit(con, self.tid, 1.0, "Jure")
        con.commit()
        con.close()
        run_paper.tick(self.cfg, quiet=True)
        st, status = self._state()
        self.assertEqual(status, "closed")
        self.assertTrue(store.is_manual(st))

    def test_ui_post_validates(self):
        from ui import data, paper as upaper
        saved = data.PAPER_DB
        data.PAPER_DB = run_paper.DB
        try:
            self.assertEqual(upaper.post("/paper/izlaz", {"trade": str(self.tid), "frac": "0.3"}), "/paper#open")
            self.assertEqual(upaper.post("/paper/izlaz", {"trade": str(self.tid), "frac": "1"}), "/paper?izlaz=1#open")
            self.assertEqual(upaper._pending(), {self.tid: 1.0})
        finally:
            data.PAPER_DB = saved

    def test_closed_trade_refuses(self):
        con = store.connect(run_paper.DB)
        con.execute("UPDATE trades SET status='closed' WHERE id=?", (self.tid,))
        self.assertFalse(store.request_exit(con, self.tid, 1.0))
        con.close()


class Refit(unittest.TestCase):
    def test_scheduler_refits_rules_fitted_under_old_mechanics(self):
        import run_sched
        d = tempfile.mkdtemp()
        old = os.environ.get("LEARNED_DIR")
        os.environ["LEARNED_DIR"] = d
        try:
            self.assertFalse(run_sched.exits_refit())  # no learned rules yet
            with open(os.path.join(d, "exits.json"), "w") as f:
                json.dump({"profiles": {"default": {"v": 1, "params": {}}}}, f)
            self.assertTrue(run_sched.exits_refit())
            with open(os.path.join(d, "exits.json"), "w") as f:
                json.dump({"profiles": {"default": {"v": 1, "params": {}}}, "sim_version": sim.SIM_VERSION}, f)
            self.assertFalse(run_sched.exits_refit())
        finally:
            if old is None:
                os.environ.pop("LEARNED_DIR", None)
            else:
                os.environ["LEARNED_DIR"] = old


if __name__ == "__main__":
    unittest.main()
