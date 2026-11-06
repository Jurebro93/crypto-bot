"""Paper trading + daily review against canned prices (no network).

    python3 -m unittest discover -s tests
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paper import dca, review, sim, store  # noqa: E402

CFG = sim.load_config()
T0 = 1_800_000_000


def _path(rets, liq=50_000, dt=600):
    return [(T0 + dt * (i + 1), 1.0 + r, liq if r > -0.95 else 0) for i, r in enumerate(rets)]


class PaperSim(unittest.TestCase):
    def test_fill_costs_fee_and_impact(self):
        pos = sim.open_position(1.0, 50_000, T0, 50, CFG)
        slip = CFG.get("slip", 0.0)  # execution slippage on top of fee + pool impact (1.11.)
        self.assertGreater(pos["entry_eff"], 1.01 * (1 + slip))
        self.assertLess(pos["entry_eff"], 1.02 * (1 + slip))

    def test_no_liquidity_reading_does_not_crash(self):
        """1.11.: a candidate with liquidity 0 made the daily review crash (ZeroDivisionError in open_position)."""
        pos = sim.open_position(1.0, 0, T0, 50, CFG)
        self.assertGreater(pos["entry_eff"], 1.0)
        self.assertLess(pos["entry_eff"], 1e3)

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
        # panic off: this tests the breakeven mechanics (with it on, the -41% tick after the take profit is an
        # emergency exit at +20%, see test_panic_exit_offline)
        r = sim.replay(1.0, 50_000, T0, _path([1.05, 0.2, -0.05]), {**CFG, "trail_after": 5, "panic": None})
        self.assertEqual(r["exit_reason"], "breakeven")
        self.assertGreater(r["ret"], 0.3)  # half sold at 2x pays for the rest

    def test_time_exit(self):
        r = sim.replay(1.0, 50_000, T0, _path([0.02] * 30, dt=3600), CFG)
        self.assertEqual(r["exit_reason"], "time")


class PaperDca(unittest.TestCase):
    def test_signal_needs_dip_bounce_and_liquidity(self):
        pos = sim.open_position(1.0, 50_000, T0, 50, CFG)
        late = T0 + 3600
        sim.step(pos, 0.72, 45_000, late, CFG)  # -28%, at the low: no bounce yet
        self.assertIsNone(dca.check(pos, 0.72, 45_000, late, CFG))
        self.assertIsNotNone(dca.check(pos, 0.79, 45_000, late, CFG))  # bounced ~10% off the low
        self.assertIsNone(dca.check(pos, 0.79, 20_000, late, CFG))  # liquidity leaving
        self.assertIsNone(dca.check(pos, 0.79, 45_000, T0 + 60, CFG))  # too early
        self.assertIsNone(dca.check(pos, 0.95, 45_000, late, CFG))  # not a dip

    def test_outcome_held_to_trade_exit(self):
        con = store.connect(os.path.join(tempfile.mkdtemp(), "p.db"))
        pos = sim.open_position(1.0, 50_000, T0, 50, CFG)
        tid = store.open_trade(con, "T", "T", pos, CFG, mcap=100_000)
        self.assertTrue(dca.log(con, tid, "T", "T", pos, 0.75, 45_000, 75_000, T0 + 3600, "test", CFG))
        self.assertFalse(dca.log(con, tid, "T", "T", pos, 0.7, 45_000, 70_000, T0 + 4000, "again", CFG))
        for ts, p in [(T0 + 4000, 1.0), (T0 + 8000, 1.5)]:
            store.tick(con, "T", ts, p, 50_000, p * 1e5)
        pos["open"], pos["closed_ts"] = False, T0 + 8000
        store.save_trade(con, tid, pos, sim.result(pos), mcap=150_000)
        row = con.execute("SELECT entry_mcap, exit_mcap FROM trades WHERE id=?", (tid,)).fetchone()
        self.assertEqual(row, (100_000, 150_000))
        out = dca.outcomes(con)
        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(out[0]["ret_to_exit"], 1.5 * 0.99 / (0.75 * 1.01) - 1, places=3)

    def test_old_db_gets_mcap_columns_from_ticks(self):
        import sqlite3
        path = os.path.join(tempfile.mkdtemp(), "old.db")
        con = sqlite3.connect(path)
        con.executescript(store.SCHEMA)
        con.execute("INSERT INTO trades (token, symbol, opened_ts, closed_ts, status) VALUES ('T','T',?,?,'closed')",
                    (T0, T0 + 600))
        con.execute("INSERT INTO ticks VALUES ('T', ?, 1, 1, 111)", (T0,))
        con.execute("INSERT INTO ticks VALUES ('T', ?, 2, 1, 222)", (T0 + 600,))
        con.commit()
        con.close()
        con = store.connect(path)
        self.assertEqual(con.execute("SELECT entry_mcap, exit_mcap FROM trades").fetchone(), (111, 222))


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
        self.assertIn("Moguća promjena: Najmanja ocjena za ulaz", md)
        self.assertNotIn("run_paper.py", md)
        self.assertNotIn(".json", md)
        json.dumps(rep, default=str)


if __name__ == "__main__":
    unittest.main()
