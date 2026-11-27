"""27.11. (vlasnik: model vjerojatnosti bondanja): bondmodel/, offline, sintetički podaci.

  - učenje nikad ne vidi retke testnog razdoblja ni ishod koji se u trenutku testa još nije znao
  - povijest deva koristi samo ishode upisane prije lansiranja
  - model nauči umjetni signal izvan uzorka; na šumu presuda kaže da ne pobjeđuje osnovnu stopu
  - mjere (AUC, preciznost u gornjih q, kalibracija)
  - spremanje i odjeljak stranice (bez adresa, bez formula); arhiva mjerenja prije brisanja
  - nijedan modul koji trguje ne uvozi bondmodel

    python3 -m unittest tests.test_bondmodel_offline
"""
import gzip
import json
import os
import random
import re
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bondmodel import model as bm  # noqa: E402
from live import pumpmjerenje as pm  # noqa: E402

T0 = 1_790_000_000


def synth(n=4000, hours=48, signal=True, seed=1):
    """(launches, ishod, imena): lansiranja ravnomjerno kroz `hours`; s signalom bondanje ovisi o devovoj kupnji."""
    rnd = random.Random(seed)
    launches, ishod, imena = {}, [], {}
    for i in range(n):
        ts = T0 + int(i * hours * 3600 / n)
        sol = rnd.choice([0.0, 0.0, 0.1, 0.5, 1.0, 3.0])
        mint = f"m{i}"
        launches[mint] = {"mint": mint, "ts": ts, "creator": f"d{rnd.randrange(n // 3)}", "initial_sol": sol,
                          "mayhem": rnd.random() < 0.1, "pool": "pump", "u": rnd.random(), "in_sample": True}
        p = (0.02 + 0.25 * (sol >= 1)) if signal else 0.08
        mig = rnd.random() < p
        peak = 40_000 if mig else rnd.choice([3_000, 6_000, 12_000])
        ishod.append({"mint": mint, "k": 1, "ts": ts + 3600, "found": 1, "mcap_usd": peak, "max_mcap_usd": peak,
                      "migrated": int(mig)})
        ishod.append({"mint": mint, "k": 12, "ts": ts + 12 * 3600, "found": 1, "mcap_usd": peak,
                      "max_mcap_usd": peak, "migrated": int(mig)})
        imena[mint] = {"mint": mint, "name": "x", "symbol": "X", "tema": ""}
    return launches, ishod, imena


class Metrics(unittest.TestCase):
    def test_auc(self):
        self.assertEqual(bm.auc([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1]), 1.0)
        self.assertEqual(bm.auc([0.9, 0.8, 0.2, 0.1], [0, 0, 1, 1]), 0.0)
        self.assertEqual(bm.auc([0.5] * 4, [0, 1, 0, 1]), 0.5)
        self.assertIsNone(bm.auc([0.1, 0.2], [0, 0]))

    def test_precision_and_calibration(self):
        s = [i / 100 for i in range(100)]
        y = [1 if i >= 95 else 0 for i in range(100)]
        self.assertEqual(bm.precision_at(s, y, 0.05), (1.0, 5, 5))
        self.assertEqual(bm.precision_at(s, y, 0.01), (1.0, 1, 1))
        cal = bm.calibration(s, y)
        self.assertEqual(len(cal), 10)
        self.assertEqual(cal[-1][3], 0.5)
        self.assertEqual(sum(c[1] for c in cal), 100)


class NoLookahead(unittest.TestCase):
    def test_training_never_sees_test_period(self):
        rows = bm.build_rows(*synth(2000))
        seen = []

        def chk(start, train, test):
            test_m = {r["mint"] for r in test}
            for r in train:
                self.assertLess(r["ts"], start)
                self.assertLess(r["label_ts"], start)   # ishod je bio poznat prije testa
                self.assertNotIn(r["mint"], test_m)
            self.assertTrue(all(r["ts"] >= start for r in test))
            seen.append(start)
        preds, blocks = bm.walk_forward(rows, "bond", min_train=100, on_block=chk)
        self.assertGreaterEqual(len(seen), 3)
        self.assertTrue(preds)
        # embargo: prvi blok s učenjem počinje tek kad su ishodi +12 h poznati
        self.assertGreaterEqual(seen[0], T0 + 12 * 3600)

    def test_fit_input_is_only_train(self):
        rows = bm.build_rows(*synth(1500))
        fitted = []
        real = bm.fit

        def spy(rs, target, **kw):
            fitted.append(max(r["label_ts"] for r in rs))
            return real(rs, target, **kw)
        starts = []
        with mock.patch.object(bm, "fit", spy):
            bm.walk_forward(rows, "bond", min_train=100, on_block=lambda s, tr, te: starts.append(s))
        self.assertEqual(len(fitted), len(starts))
        self.assertTrue(all(f < s for f, s in zip(fitted, starts)))

    def test_dev_history_only_from_seen_outcomes(self):
        launches = {
            "a": {"mint": "a", "ts": T0, "creator": "D", "initial_sol": 0, "pool": "pump", "u": 0, "in_sample": True},
            "b": {"mint": "b", "ts": T0 + 600, "creator": "D", "initial_sol": 0, "pool": "pump", "u": 0,
                  "in_sample": True},
            "c": {"mint": "c", "ts": T0 + 2 * 3600, "creator": "D", "initial_sol": 0, "pool": "pump", "u": 0,
                  "in_sample": True}}
        ishod = []
        for m, l in launches.items():
            ishod.append({"mint": m, "k": 1, "ts": l["ts"] + 3600, "found": 1, "mcap_usd": 50_000,
                          "max_mcap_usd": 50_000, "migrated": int(m == "a")})
            ishod.append({"mint": m, "k": 12, "ts": l["ts"] + 12 * 3600, "found": 1, "mcap_usd": 5000,
                          "max_mcap_usd": 5000, "migrated": int(m == "a")})
        rows = {r["mint"]: r for r in bm.build_rows(launches, ishod, {})}
        self.assertEqual(rows["b"]["x"]["dev_ranije_bondao"], 0.0)   # ishod od a viđen tek u T0+1h
        self.assertEqual(rows["b"]["x"]["dev_24h_log"], bm.math.log1p(1))
        self.assertEqual(rows["c"]["x"]["dev_ranije_bondao"], 1.0)   # sada je viđen
        self.assertEqual(rows["a"]["x"]["dev_24h_log"], 0.0)
        self.assertEqual(rows["a"]["y"]["bond"], 1)

    def test_missing_12h_outcome_excluded(self):
        la, ish, im = synth(50)
        ish = [r for r in ish if not (r["mint"] == "m0" and r["k"] == 12)]
        ish.append({"mint": "m1", "k": 12, "ts": T0, "found": -1})
        rows = bm.build_rows(la, [r for r in ish if not (r["mint"] == "m1" and r["k"] == 12 and r["found"] >= 0)],
                             im)
        mints = {r["mint"] for r in rows}
        self.assertNotIn("m0", mints)
        self.assertNotIn("m1", mints)


class Learning(unittest.TestCase):
    def test_learns_signal_out_of_sample(self):
        rows = bm.build_rows(*synth(4000, signal=True))
        preds, _ = bm.walk_forward(rows, "bond")
        m = bm.evaluate(preds)
        self.assertGreater(m["auc"], 0.75)
        self.assertGreater(m["lift5"], 2)
        self.assertTrue(m["verdict"].startswith("jasno bolji"))
        f = bm.factors(bm.fit(rows, "bond"))
        self.assertIn(f[0][0], (bm.FEATURE_WORDS["kupnja_log"], bm.FEATURE_WORDS["kupnja_velika"]))

    def test_noise_does_not_beat_base(self):
        rows = bm.build_rows(*synth(4000, signal=False, seed=7))
        m = bm.evaluate(bm.walk_forward(rows, "bond")[0])
        self.assertLess(abs(m["auc"] - 0.5), 0.06)
        self.assertFalse(m["verdict"].startswith("jasno bolji"))


class StoreAndPage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _mjerenje_db(self, n=3000):
        p = os.path.join(self.tmp.name, "pump_mjerenje.db")
        con = pm.connect(p)
        la, ish, im = synth(n)
        con.executemany("INSERT INTO launches VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        [(r["mint"], r["ts"], r["creator"], r["initial_sol"], 0, 30, r["pool"], int(r["mayhem"]),
                          1, 0, r["u"]) for r in la.values()])
        con.executemany("INSERT INTO ishod VALUES (?,?,?,?,?,?,?,?,?,?)",
                        [(r["mint"], r["k"], r["ts"], r["found"], 1, 1, r["mcap_usd"], r["max_mcap_usd"],
                          r["migrated"], 200) for r in ish])
        con.executemany("INSERT INTO imena VALUES (?,?,?,?)", [(m, "x", "X", "") for m in im])
        pm.put(con, "start", T0)
        pm.put(con, "rok", T0 + 48 * 3600)
        pm.put(con, "udio", 1)
        return con, p

    def test_run_save_and_section(self):
        con, p = self._mjerenje_db()
        con.close()
        out = os.path.join(self.tmp.name, "bond_model.db")
        res = bm.run([p], path=out, now=T0 + 60 * 3600, log=lambda s: None)
        self.assertEqual(set(res), set(bm.TARGETS))
        c = sqlite3.connect(out)
        self.assertEqual(c.execute("SELECT COUNT(DISTINCT cilj) FROM runs").fetchone()[0], 3)
        self.assertGreater(c.execute("SELECT COUNT(*) FROM predictions").fetchone()[0], 100)
        c.close()
        from ui import bondmodel as ub
        html = ub.section_html(out)
        self.assertIn("Procjena bondanja", html)
        text = re.sub(r"<[^>]+>", " ", html)
        self.assertNotRegex(text, r"\bm\d+\b")   # bez mintova
        self.assertNotRegex(text, r"log|sigm|AUC|=")   # bez formula

    def test_section_without_data(self):
        from ui import bondmodel as ub
        self.assertIn("Još nema izračuna", ub.section_html(os.path.join(self.tmp.name, "nema.db")))

    def test_archive_before_delete_and_load_equal(self):
        con, p = self._mjerenje_db(600)
        con.close()
        dl = T0 + 48 * 3600
        logs = []
        pm.tick(dl + 10, fetch=lambda m: [], log=logs.append, env={}, path=p)
        con = sqlite3.connect(p)
        a = pm.get(con, "arhiva")
        con.close()
        self.assertTrue(a and os.path.exists(a))
        self.assertEqual(os.path.dirname(a), self.tmp.name)
        with gzip.open(a, "rt") as f:
            d = json.load(f)
        self.assertEqual(len(d["launches"]["rows"]), 600)
        self.assertIn("creator", d["launches"]["cols"])
        rows_db = bm.build_rows(*bm.load([p])[:3])
        rows_gz = bm.build_rows(*bm.load([a])[:3])
        self.assertEqual(rows_db, rows_gz)
        # brisanje kao dosad (7 dana), arhiva ostaje
        pm.tick(dl + pm.KEEP_AFTER_S + 1, fetch=lambda m: [], log=logs.append, env={}, path=p)
        self.assertFalse(os.path.exists(p))
        self.assertTrue(os.path.exists(a))
        self.assertEqual(len(bm.build_rows(*bm.load([a])[:3])), len(rows_db))

    def test_no_delete_without_archive(self):
        con, p = self._mjerenje_db(50)
        con.close()
        dl = T0 + 48 * 3600
        with mock.patch.object(pm.gzip, "open", side_effect=OSError("disk")):
            pm.tick(dl + pm.KEEP_AFTER_S + 1, fetch=lambda m: [], log=lambda s: None, env={}, path=p)
        self.assertTrue(os.path.exists(p))
        pm.tick(dl + pm.KEEP_AFTER_S + 700, fetch=lambda m: [], log=lambda s: None, env={}, path=p)
        self.assertFalse(os.path.exists(p))
        self.assertTrue(any(f.startswith("pump_mjerenje_arhiva_") for f in os.listdir(self.tmp.name)))


class Isolation(unittest.TestCase):
    def test_nothing_that_trades_imports_bondmodel(self):
        allowed = {os.path.join("ui", "bondmodel.py"), os.path.join("ui", "pumptokeni.py")}
        bad = []
        for d, _sub, files in os.walk(ROOT):
            rel = os.path.relpath(d, ROOT)
            if rel.startswith((".git", "tests", ".cache", "bondmodel")):
                continue
            for f in files:
                if not f.endswith(".py"):
                    continue
                p = os.path.normpath(os.path.join(rel, f))
                if p in allowed:
                    continue
                try:
                    with open(os.path.join(d, f), encoding="utf-8") as fh:
                        txt = fh.read()
                except (OSError, UnicodeDecodeError):
                    continue
                if re.search(r"(from|import)\s+bondmodel|from ui import .*bondmodel", txt):
                    bad.append(p)
        self.assertEqual(bad, [])

    def test_model_has_no_network_or_trading_imports(self):
        for f in ("model.py", "posao.py"):
            with open(os.path.join(ROOT, "bondmodel", f), encoding="utf-8") as fh:
                txt = fh.read()
            self.assertNotRegex(txt, r"import (urllib|requests|http)|from (trade|veliki|live|paper|league)\b")


if __name__ == "__main__":
    unittest.main()
