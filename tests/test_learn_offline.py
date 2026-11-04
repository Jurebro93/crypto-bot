"""Learning loop against a synthetic hype.db (no network): outcomes per class, pump thresholds, guarded fit."""
import json
import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hype import store as hstore  # noqa: E402
from learn import correlations, fit, outcomes, store, weights  # noqa: E402
from tiers import store as tstore  # noqa: E402

NOW = 1_800_000_000
FEATS = ["fresh", "turnover", "smart_money", "x_buzz", "put_skokovitost"]


def synthetic(path, n=300, seed=1):
    """n tokens: smart_money strongly predicts a 3x, the rest is noise; half moonshot, half rizican."""
    rnd = random.Random(seed)
    con = hstore.connect(path)
    con.row_factory = __import__("sqlite3").Row
    tstore.connect(path).close()          # one writer at a time: two open write transactions on one file deadlock
    store.connect(path).close()
    tcon = con
    for i in range(n):
        t, ts = f"T{i:04d}", NOW - 3 * 86400 + i * 600
        f = {k: rnd.random() for k in FEATS}
        pump = f["smart_money"] > 0.5 and rnd.random() < 0.8 or rnd.random() < 0.1
        klasa = "moonshot" if i % 2 else "rizican"
        price, mcap = 1.0, 50_000 if klasa == "moonshot" else 500_000
        con.execute("INSERT INTO hype_signals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (ts, t, t, t, "p", "u", 50, price, mcap, 20_000, json.dumps(f), "profile", "{}"))
        for h in range(1, 25):
            p = price * (1 + (3.0 if pump else 0.2) * h / 24) if pump or rnd.random() < 0.5 else price * 0.8
            con.execute("INSERT OR REPLACE INTO hype_snapshots VALUES (?,?,?,?,?)", (t, ts + h * 3600, p, mcap, 20_000))
        tstore.upsert(tcon, t, ts, symbol=t, klasa=klasa, t0="prolaz", mcap=mcap, razina=1 if i % 3 else 0)
    # one token outside the scan that pumped anyway
    tstore.upsert(tcon, "MISSED", NOW - 86400, symbol="MISS", klasa="moonshot", t0="nije", t0_razlog="likvidnost $500 < $5.0k", mcap=20_000)
    for h in range(0, 12):
        con.execute("INSERT OR REPLACE INTO hype_snapshots VALUES (?,?,?,?,?)", ("MISSED", NOW - 86400 + h * 3600, 1 + h, 20_000, 500))
    con.commit()
    return con


class Learn(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "hype.db")
        self.con = synthetic(self.db)
        weights.LEARNED_DIR = os.path.join(self.tmp, "learned")

    def test_outcomes_thresholds_and_missed(self):
        rows, thr = outcomes.rows(self.con, now=NOW)
        self.assertGreaterEqual(len(rows), 250)
        self.assertEqual(set(thr), {"moonshot", "rizican", "event", "stabilni"})
        self.assertEqual(thr["event"], 0.5)                      # no event rows: initial value stays
        self.assertGreater(thr["moonshot"], 0.5)                 # learned from the data
        self.assertTrue(any(r["hit"] for r in rows) and not all(r["hit"] for r in rows))
        ms = outcomes.missed(self.con, thr, now=NOW)
        self.assertEqual([m["token"] for m in ms][:1], ["MISSED"])
        self.assertIn("likvidnost", ms[0]["reason"])

    def test_step_is_bounded(self):
        cfg = outcomes.config()
        new = fit.step({"a": 10, "b": 10, "c": 0}, {"a": 50, "b": 0, "c": 40}, cfg)
        self.assertEqual(new, {"a": 12.0, "b": 8.0, "c": 1.0})

    def test_run_applies_only_when_better(self):
        base = {k: 10.0 for k in FEATS}
        rep = fit.run(self.con, now=NOW, apply=True, base=base)
        by = {r["klasa"]: r for r in rep}
        self.assertIn("nedovoljno podataka", by["event"]["note"])   # cilj zarada, no shadow book: no peak fallback
        self.assertEqual(by["event"]["cilj"], "nedovoljno")
        rep = fit.run(self.con, cfg={**outcomes.config(), "cilj": "vrh"}, now=NOW, apply=True, base=base)
        by = {r["klasa"]: r for r in rep}
        self.assertIn("premalo", by["event"]["note"])
        for k in ("moonshot", "rizican"):
            r = by[k]
            self.assertLess(r["n"], 200)                          # 150 each: below min_rows, so no change
            self.assertFalse(r["applied"])
        # with a lower bar the fit runs and moves smart_money up
        cfg = outcomes.config()
        cfg["min_rows"] = 100
        cfg["cilj"] = "vrh"          # the old peak target, still available when chosen by name
        cfg["purge_h"] = 0           # synthetic rows sit within a few hours: no label window to purge
        rep = fit.run(self.con, cfg=cfg, now=NOW, apply=True, base=base)
        r = {x["klasa"]: x for x in rep}["moonshot"]
        self.assertIsNotNone(r["new"])
        self.assertGreater(r["new"]["smart_money"], base["smart_money"])
        if r["applied"]:
            self.assertEqual(weights.load("moonshot", base), r["new"])
            self.assertTrue(os.path.exists(weights.path("moonshot")))
        runs = store.runs(self.con, "moonshot")
        self.assertEqual(runs[0]["n"], r["n"])

    def test_correlations(self):
        rows, _ = outcomes.rows(self.con, now=NOW)
        rows = correlations.with_details(self.con, rows)
        lf = {x["feature"]: x for x in correlations.lift(rows)}
        self.assertGreater(lf["smart_money"]["lift"], 1.3)
        cv = {c["label"]: c for c in correlations.curves(rows)}
        self.assertIn("Mcap ($)", cv)
        self.assertTrue(all(0 <= b["hit_rate"] <= 1 for b in cv["Mcap ($)"]["bins"]))
        self.assertIsInstance(correlations.pairs(rows), list)

    def test_rollback_restores_previous(self):
        weights.save("rizican", {"a": 1}, NOW)
        weights.save("rizican", {"a": 2}, NOW)
        self.assertEqual(weights.load("rizican"), {"a": 2})
        self.assertTrue(weights.rollback("rizican"))
        self.assertEqual(weights.load("rizican"), {"a": 1})


if __name__ == "__main__":
    unittest.main()
