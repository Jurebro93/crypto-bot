"""Shadow book (learn/shadow.py) and the 2.11. learning-target changes, against synthetic DBs (no network)."""
import json
import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hype import evaluate, score  # noqa: E402
from hype import store as hstore  # noqa: E402
from learn import fit, outcomes, shadow, weights  # noqa: E402
from paper import store as pstore  # noqa: E402
from tiers import store as tstore  # noqa: E402

NOW = 1_800_000_000
FEATS = ["fresh", "turnover", "smart_money", "x_buzz"]


def build(tmp, n=240, seed=3):
    """hype.db: n tokens, first signal + $100k event; smart_money -> steady +60% rise, else a slide to -50%.
    paper.db: every 4th token is a candidate with minute ticks (every 8th bought)."""
    rnd = random.Random(seed)
    hdb, pdb = os.path.join(tmp, "hype.db"), os.path.join(tmp, "paper.db")
    con = hstore.connect(hdb)
    tstore.connect(hdb).close()
    for i in range(n):
        t, ts = f"T{i:04d}", NOW - 2 * 86400 + i * 120
        f = {k: rnd.random() for k in FEATS}
        good = f["smart_money"] > 0.5
        con.execute("INSERT INTO hype_signals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (ts, t, t, t, "p", "u", 50, 1.0, 50_000, 40_000, json.dumps(f), "profile", "{}"))
        tstore.record_event(con, t, "B100000", 1e5, 1.0, 50.0, f, now=ts)
        for m in range(1, 25 * 3):  # 20-min snapshots
            x = m / 72
            p = 1 + 0.6 * x if good else 1 - 0.5 * x
            con.execute("INSERT OR REPLACE INTO hype_snapshots VALUES (?,?,?,?,?)", (t, ts + m * 1200, p, 1e5, 40_000))
        tstore.upsert(con, t, ts, symbol=t, klasa="moonshot", t0="prolaz", mcap=50_000)
    con.commit()
    con.close()
    p = pstore.connect(pdb)
    for i in range(0, n, 4):
        t, ts = f"T{i:04d}", NOW - 2 * 86400 + i * 120
        p.execute("INSERT INTO candidates (token, symbol, first_ts, origin, sources, score, features, price, liquidity, mcap, "
                  "decision, trade_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (t, t, ts, "hype", "[]", 40, "{}", 1.0, 40_000, 50_000, "bought" if i % 8 == 0 else "skip_score",
                   i if i % 8 == 0 else None))
        for m in range(1, 60):
            p.execute("INSERT OR REPLACE INTO ticks VALUES (?,?,?,?,?)", (t, ts + m * 60, 1.0 + 0.01 * m, 40_000, 5e4))
    p.commit()
    p.close()
    return hdb, pdb


class Shadow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        weights.LEARNED_DIR = os.path.join(self.tmp, "learned")
        os.environ["DATA_DIR"] = self.tmp
        self.hdb, self.pdb = build(self.tmp)
        self.sdb = os.path.join(self.tmp, "shadow.db")

    def tearDown(self):
        os.environ.pop("DATA_DIR", None)

    def _run(self):
        con = shadow.connect(self.sdb)
        cfg = {**shadow.config(), "lookback_h": 24 * 30}
        new = shadow.collect(con, self.hdb, self.pdb, NOW, cfg)
        n = shadow.label(con, self.hdb, self.pdb, NOW, cfg)
        con.close()
        return new, n

    def test_collect_is_idempotent_and_labels(self):
        new, n = self._run()
        self.assertEqual(new["prvi_signal"], 240)
        self.assertEqual(new["mc100k"], 240)
        self.assertEqual(new["kandidat"], 60)
        self.assertEqual(n, 540)
        again, n2 = self._run()
        self.assertEqual(again, {})
        self.assertEqual(n2, 0)
        rs = shadow.rows(self.sdb)
        good = [r for r in rs if r["point"] == "prvi_signal" and r["features"]["smart_money"] > 0.5]
        bad = [r for r in rs if r["point"] == "prvi_signal" and r["features"]["smart_money"] <= 0.5
               and int(r["token"][1:]) % 4]  # candidates have their own (rising) minute ticks
        self.assertTrue(all(r["src"] == ("tick" if int(r["token"][1:]) % 4 == 0 else "snap") for r in good + bad))
        self.assertGreater(sum(r["hit"] for r in good) / len(good), 0.9)  # +60% rise is a taken profit
        self.assertEqual(sum(r["hit"] for r in bad), 0)
        self.assertTrue(all(r["ret"] < 0 for r in bad))
        k = [r for r in rs if r["point"] == "kandidat"]
        self.assertTrue(all(r["src"] == "tick" for r in k))
        self.assertEqual(sum(r["kupljeno"] for r in k), 30)
        # daily snapshot file for later models
        files = os.listdir(shadow.export_dir())
        self.assertEqual(len(files), 1)

    def test_clean_drops_single_bogus_print(self):
        path = [(1, 1.0, 1), (2, 1.1, 1), (3, 70.0, 1), (4, 1.2, 1), (5, 3.5, 1), (6, 3.6, 1)]
        out = shadow.clean(path)
        self.assertNotIn(70.0, [p for _, p, _ in out])
        self.assertIn(3.5, [p for _, p, _ in out])  # a real jump keeps its neighbour

    def test_stats_caps_and_trims(self):
        rs = [{"ret": 50.0, "hit": 1, "rug": 0}] + [{"ret": -0.1, "hit": 0, "rug": 0}] * 99
        st = shadow.stats(rs)
        self.assertAlmostEqual(st["mean"], (3.0 - 9.9) / 100, places=3)  # 50x counted as +300%
        self.assertLess(st["mean_trim"], 0)
        self.assertEqual(st["n"], 100)

    def test_fit_learns_from_shadow_book(self):
        self._run()
        cfg = {**outcomes.config(), "min_rows": 100, "purge_h": 0}   # synthetic points: no window to purge
        base = {k: 10.0 for k in FEATS}
        from learn import store
        con = store.connect(self.hdb)
        rep = fit.run(con, cfg=cfg, now=NOW, apply=True, base=base, shadow_path=self.sdb)
        con.close()
        r = {x["klasa"]: x for x in rep}["moonshot"]
        self.assertEqual(r["cilj"], "zarada")
        self.assertGreaterEqual(r["n_shadow"], 480)
        self.assertGreater(r["new"]["smart_money"], base["smart_money"])

    def test_summary(self):
        self._run()
        sm = shadow.summary(self.sdb, days=30, now=NOW)
        self.assertEqual(sm["by_point"]["mc100k"]["n"], 240)
        self.assertEqual(sm["kandidat"]["kupljeno"]["n"], 30)
        self.assertEqual(sm["status"]["gotovo"], 540)


class NegativeWeights(unittest.TestCase):
    def test_score_subtracts_and_clamps(self):
        w = {"a": 50, "b": 50, "c": -40}
        self.assertEqual(score.score({"a": 1, "b": 1}, w), 100.0)
        self.assertEqual(score.score({"a": 1, "b": 1, "c": 1}, w), 60.0)
        self.assertEqual(score.score({"c": 1}, w), 0.0)
        self.assertEqual(score.score({"a": 1, "b": 0}, {"a": 50, "b": 50}), 50.0)  # unchanged without negatives

    def test_fit_keeps_negative_coefficients(self):
        rnd = random.Random(1)
        rows = []
        for _ in range(400):
            f = {"good": rnd.random(), "bad": rnd.random()}
            p = 0.15 + 0.6 * f["good"] - 0.5 * f["bad"]
            rows.append({"features": f, "hit": rnd.random() < max(0.02, p)})
        out = evaluate.fit_weights(rows)
        self.assertGreater(out["weights"]["good"], 0)
        self.assertLess(out["weights"]["bad"], 0)


if __name__ == "__main__":
    unittest.main()
