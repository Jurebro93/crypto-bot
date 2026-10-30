"""Paper trading + daily review against canned prices (no network).

    python3 -m unittest discover -s tests
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paper import review, sim, store  # noqa: E402

CFG = sim.load_config()
T0 = 1_800_000_000


def _path(rets, liq=50_000, dt=600):
    return [(T0 + dt * (i + 1), 1.0 + r, liq if r > -0.95 else 0) for i, r in enumerate(rets)]


class PaperSim(unittest.TestCase):
    def test_fill_costs_fee_and_impact(self):
        pos = sim.open_position(1.0, 50_000, T0, 50, CFG)
        self.assertGreater(pos["entry_eff"], 1.01)
        self.assertLess(pos["entry_eff"], 1.02)

    def test_stop_loss(self):
        r = sim.replay(1.0, 50_000, T0, _path([0.05, -0.1, -0.4, 0.5]), CFG)
        self.assertEqual(r["exit_reason"], "stop_loss")
        self.assertLess(r["ret"], -0.38)

    def test_take_profit_then_trailing(self):
        r = sim.replay(1.0, 50_000, T0, _path([0.5, 1.1, 1.6, 0.7]), CFG)
        self.assertEqual(r["exit_reason"], "trailing")
        self.assertGreater(r["ret"], 0.3)

    def test_rug_exit(self):
        r = sim.replay(1.0, 50_000, T0, _path([0.2, -0.99]), CFG)
        self.assertEqual(r["exit_reason"], "rug")
        self.assertLess(r["ret"], -0.7)

    def test_breakeven_after_tp(self):
        r = sim.replay(1.0, 50_000, T0, _path([1.05, 0.2, -0.05]), {**CFG, "trail_after": 5})
        self.assertEqual(r["exit_reason"], "breakeven")
        self.assertGreater(r["ret"], 0.3)  # half sold at 2x pays for the rest

    def test_time_exit(self):
        r = sim.replay(1.0, 50_000, T0, _path([0.02] * 30, dt=3600), CFG)
        self.assertEqual(r["exit_reason"], "time")


class PaperReview(unittest.TestCase):
    def test_review_finds_mistakes_missed_and_threshold(self):
        con = store.connect(os.path.join(tempfile.mkdtemp(), "p.db"))
        cfg = {**CFG, "min_score": 50}
        now = T0 + 30 * 3600
        for i in range(24):
            score = 30 + i * 2.5  # 30..87
            win = score < 50  # low scores win, high scores lose: the review must suggest a lower threshold
            rets = [0.3, 1.2, 3.5, 5.0, 2.0] if win else [0.05, -0.2, -0.45, -0.5, -0.5]
            tok = f"T{i}"
            taken = score >= cfg["min_score"]
            c = {"token": tok, "symbol": tok, "ts": T0 + i * 60, "origin": "hype", "sources": ["profile"],
                 "score": score, "features": {"momentum": 0.8 if not win else 0.1, "fresh": 1.0 if win else 0.2},
                 "price": 1.0, "liquidity": 50_000, "mcap": 1e5, "decision": "taken" if taken else "skip_score",
                 "reason": f"score {score:.0f}"}
            if taken:
                pos = sim.open_position(1.0, 50_000, c["ts"], 50, cfg)
                c["trade_id"] = store.open_trade(con, tok, tok, pos, cfg)
                for ts, p, l in _path(rets):
                    sim.step(pos, p, l, ts + i * 60, cfg)
                store.save_trade(con, c["trade_id"], pos, sim.result(pos, 0.5, 50_000, cfg))
            store.add_candidate(con, c)
            for ts, p, l in _path(rets):
                store.tick(con, tok, ts + i * 60, p, l, 1e5)
        con.commit()
        rep = review.run(con, cfg, hours=48, now=now)
        self.assertTrue(rep["summary"]["closed"] > 0)
        self.assertTrue(any(m["kind"] == "late_entry" for m in rep["mistakes"]))
        self.assertTrue(rep["missed"])
        th = [s for s in rep["suggestions"] if "min_score" in s.get("change", {})]
        self.assertTrue(th and th[0]["change"]["min_score"] < 50, rep["suggestions"])
        md = review.to_md(rep, cfg)
        self.assertIn("Prijedlozi", md)
        json.dumps(rep, default=str)


if __name__ == "__main__":
    unittest.main()
