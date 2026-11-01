"""Decision model (learn/gbm.py) and champion/challenger with holdout (learn/champion.py), synthetic data only."""
import json
import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learn import champion, gbm, shadow, weights  # noqa: E402

DAY = 86400
NOW = 1_800_000_000


def xor_rows(n=1500, seed=2):
    """Win only when a AND b are high, or when neither is: an interaction a linear score cannot express."""
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        a, b = rnd.random(), rnd.random()
        p = 0.8 if (a > 0.5) == (b > 0.5) else 0.1
        out.append({"x": {"a": a, "b": b, "noise": rnd.random()}, "y": rnd.random() < p, "ts": i})
    return out


def fill_shadow(path, start, days, per_day=120, seed=5, signal="smart"):
    """Labelled shadow points: the model's feature `smart` predicts the return; the live score is noise."""
    rnd = random.Random(seed)
    con = shadow.connect(path)
    for d in range(days):
        for i in range(per_day):
            ts = int(start + d * DAY + i * (DAY // per_day))
            sm = rnd.random()
            ret = (0.4 if sm > 0.7 else -0.15) + rnd.uniform(-0.1, 0.1)
            point = "mc100k" if i % 2 else "kandidat"
            con.execute("INSERT INTO points (id, token, symbol, point, ts, klasa, sess, price, liq, mcap, score, decision, "
                        "kupljeno, features, status, ret, max2_ret, min_ret, hit, rug) VALUES "
                        "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,'gotovo',?,?,?,?,0)",
                        (f"{point}:{d}:{i}", f"T{d}_{i}", "S", point, ts, "moonshot", "us", 1.0, 3e4, 1e5,
                         rnd.uniform(0, 100), None, 0, json.dumps({signal: sm, "x": rnd.random()}), ret, ret, -0.1,
                         int(ret >= 0.1)))
    con.commit()
    con.close()


class Gbm(unittest.TestCase):
    def test_learns_interaction_and_calibrates(self):
        rows = xor_rows()
        m = gbm.train(rows[:1200], {"min_rows": 100})
        self.assertIsNotNone(m)
        test = rows[1200:]
        hits = sum((gbm.predict(m, r["x"]) > 0.45) == r["y"] for r in test)
        self.assertGreater(hits / len(test), 0.7)  # a linear model is at ~50% here
        self.assertIn(gbm.importance(m)[0][0], ("a", "b"))
        p = [gbm.predict(m, r["x"]) for r in test]
        self.assertTrue(all(0 <= x <= 1 for x in p))

    def test_missing_feature_and_too_little_data(self):
        self.assertIsNone(gbm.train(xor_rows(50), {"min_rows": 100}))
        m = gbm.train(xor_rows(), {"min_rows": 100})
        self.assertTrue(0 <= gbm.predict(m, {}) <= 1)  # nothing measured: still a probability
        self.assertIn("log_mcap", gbm.context({"features": {"a": 1}, "mcap": 1e5, "point": "mc100k"}))


class Champion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        weights.LEARNED_DIR = os.path.join(self.tmp, "learned")
        champion._LIVE.update(ts=0, model=None)
        self.db = os.path.join(self.tmp, "shadow.db")
        self.cfg = {**champion.DEFAULT, "holdout": {"from": "2027-01-01", "to": "2027-01-07"}}

    def test_trial_then_promotion_then_live(self):
        fill_shadow(self.db, NOW - 20 * DAY, 20)
        t1 = NOW - 8 * DAY
        rep = champion.run(now=t1, cfg=self.cfg, shadow_path=self.db)
        self.assertEqual(rep["champion"], "tezine")
        st = champion.load()
        self.assertIsNotNone(st["challenger"])
        self.assertIsNone(champion.live(t1))  # a model in its trial never trades
        rep = champion.run(now=NOW, cfg=self.cfg, shadow_path=self.db)
        self.assertEqual(rep["champion"], "gbm", rep)
        self.assertTrue(any("prošao" in e for e in rep["events"]))
        champion._LIVE.update(ts=0)
        self.assertIsNotNone(champion.live(NOW))
        p_good = champion.candidate_p(champion.live(NOW), {"features": {"smart": 0.95, "x": 0.5}, "mcap": 1e5,
                                                             "liquidity": 3e4, "score": 50}, NOW)
        p_bad = champion.candidate_p(champion.live(NOW), {"features": {"smart": 0.1, "x": 0.5}, "mcap": 1e5,
                                                            "liquidity": 3e4, "score": 50}, NOW)
        self.assertGreater(p_good, p_bad)

    def test_no_promotion_when_model_learns_noise(self):
        fill_shadow(self.db, NOW - 20 * DAY, 20, signal="smart")
        # the model only sees noise columns: replace features after the fact
        con = shadow.connect(self.db)
        rnd = random.Random(1)
        for (pid,) in con.execute("SELECT id FROM points").fetchall():
            con.execute("UPDATE points SET features=? WHERE id=?", (json.dumps({"x": rnd.random()}), pid))
        con.commit()
        con.close()
        champion.run(now=NOW - 8 * DAY, cfg=self.cfg, shadow_path=self.db)
        rep = champion.run(now=NOW, cfg=self.cfg, shadow_path=self.db)
        self.assertEqual(rep["champion"], "tezine")

    def test_holdout_is_never_trained_on(self):
        cfg = {**self.cfg, "holdout": {"from": "2027-01-15", "to": "2027-01-21"}}
        lo, hi = champion.holdout_range(cfg)
        fill_shadow(self.db, lo - 3 * DAY, 13)
        rs = champion.train_rows(hi + 3 * DAY, cfg, self.db)
        self.assertTrue(rs)
        self.assertFalse(any(lo <= r["ts"] < hi for r in rs))
        rep = champion.run(now=hi + 2 * DAY, cfg=cfg, shadow_path=self.db)
        self.assertTrue(any("zaključani" in e for e in rep["events"]))
        self.assertIn("holdout_report", champion.load())


class PaperHook(unittest.TestCase):
    def test_model_need_without_champion(self):
        import sqlite3
        import run_paper
        tmp = tempfile.mkdtemp()
        weights.LEARNED_DIR = os.path.join(tmp, "learned")
        champion._LIVE.update(ts=0, model=None)
        con = sqlite3.connect(":memory:")
        cfg = {"explore": {"enabled": True, "top_pct": 30}}
        self.assertEqual(run_paper.model_need(con, cfg, NOW), (None, None))


if __name__ == "__main__":
    unittest.main()
