"""Rugged tokens archived and purged (rugfilter/archive.py), rug profile (learn/rugprofile.py), "jaki" list (dugo)."""
import json
import os
import random
import sqlite3
import tempfile
import time
import unittest

from hype import store as hstore
from tiers import store as tstore

H = 3600


def make_db(d, now):
    db = os.path.join(d, "hype.db")
    con = hstore.connect(db)
    tstore.connect(db).close()
    con.executescript("CREATE TABLE IF NOT EXISTS token_pulse (token TEXT, ts INTEGER, price REAL, mcap REAL, liquidity REAL, "
                      "vol_m5 REAL, vol_h1 REAL, buys_m5 INT, sells_m5 INT, buys_h1 INT, sells_h1 INT, holders INT, "
                      "holders_src TEXT, PRIMARY KEY (token, ts))")

    def token(t, first, path, t0="prolaz", why=None):
        con.execute("INSERT INTO token_tier (token, symbol, first_ts, last_ts, t0, t0_razlog, klasa) VALUES (?,?,?,?,?,?,?)",
                    (t, t.upper(), first, first + len(path) * 120, t0, why, "moonshot"))
        for i, (mc, liq) in enumerate(path):
            ts = first + i * 120
            con.execute("INSERT INTO hype_signals (ts, token, symbol, score, price, mcap, liquidity, features) "
                        "VALUES (?,?,?,?,?,?,?,?)", (ts, t, t.upper(), 50, mc / 1e9, mc, liq, json.dumps({"vol": 0.5})))
            con.execute("INSERT INTO hype_snapshots VALUES (?,?,?,?,?)", (t, ts, mc / 1e9, mc, liq))
            con.execute("INSERT INTO hype_details VALUES (?,?,?)", (t, ts, json.dumps({"pumpfun": {"holders": 100}})))
            con.execute("INSERT INTO token_pulse (token, ts, price, mcap, liquidity) VALUES (?,?,?,?,?)",
                        (t, ts, mc / 1e9, mc, liq))

    old = now - 30 * H
    token("rugged", old, [(50000, 20000)] * 30 + [(200000, 60000)] * 30 + [(20000, 5000)] * 60)
    token("healthy", old, [(50000, 20000)] * 60 + [(120000, 40000)] * 60)
    token("young", now - 3 * H, [(200000, 60000)] * 30 + [(10000, 3000)] * 30)
    token("mech", old, [(30000, 10000)] * 5, t0="pad", why="aktivan mint authority")
    token("lookalike", old, [(30000, 10000)] * 5, t0="pad", why="sliči rugovima (91%)")
    con.commit()
    con.close()
    return db


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        from rugfilter import archive
        self.archive = archive
        self.d = tempfile.mkdtemp()
        self.now = time.time()
        self.db = make_db(self.d, self.now)
        self._root = archive.ROOT
        archive.ROOT = self.d          # no paper/league/koltest/dugo files: nothing protected
        archive.forget_cache()

    def tearDown(self):
        self.archive.ROOT = self._root
        self.archive.forget_cache()

    def test_archive_and_purge(self):
        a = self.archive
        n, rows = a.run(self.db, now=self.now, log=None)
        self.assertEqual(n, 1)                       # mech (rug mechanics) at once; the crash goes on watch first
        self.assertEqual(a.blocked(self.db, ttl=0), {"mech"})
        n, rows = a.run(self.db, now=self.now + a.CONFIRM_H * H + 60, log=None)   # 9.11.: still collapsed 6 h later
        self.assertEqual(n, 1)
        self.assertGreater(rows, 0)
        gone = a.blocked(self.db, ttl=0)
        self.assertEqual(gone, {"rugged", "mech"})   # not healthy, not too young, not the profile's own stop
        con = sqlite3.connect(self.db)
        r = dict(zip(("kind", "reason", "entry"), con.execute(
            "SELECT kind, reason, entry FROM rug_archive WHERE token='rugged'").fetchone()))
        self.assertEqual(r["kind"], "srusen")
        e = json.loads(r["entry"])
        self.assertEqual(e["mcap"], 50000)            # the entry as first seen
        self.assertEqual(e["features"], {"vol": 0.5})
        self.assertEqual(e["pumpfun"]["holders"], 100)
        # learning record kept: first signal only, thinned snapshots incl. the peak, no pulse
        self.assertEqual(con.execute("SELECT COUNT(*) FROM hype_signals WHERE token='rugged'").fetchone()[0], 1)
        snaps = con.execute("SELECT mcap FROM hype_snapshots WHERE token='rugged'").fetchall()
        self.assertLessEqual(len(snaps), 2 * 6)
        self.assertIn(200000, [s[0] for s in snaps])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM token_pulse WHERE token='rugged'").fetchone()[0], 0)
        self.assertLessEqual(con.execute("SELECT COUNT(*) FROM hype_details WHERE token='rugged'").fetchone()[0], 2)
        # untouched
        self.assertEqual(con.execute("SELECT COUNT(*) FROM hype_signals WHERE token='healthy'").fetchone()[0], 120)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM token_tier WHERE token='rugged'").fetchone()[0], 1)
        con.close()
        # third run: nothing new
        self.assertEqual(a.run(self.db, now=self.now + a.CONFIRM_H * H + 120, log=None)[0], 0)
        sm = a.summary(self.db, now=self.now)
        self.assertEqual(sm["n"], 2)
        self.assertEqual(sm["by_kind"], {"srusen": 1, "mehanika": 1})

    def test_bounce_before_confirmation_is_not_archived(self):
        a = self.archive
        a.run(self.db, now=self.now, log=None)                      # 'rugged' goes on watch
        con = sqlite3.connect(self.db)
        self.assertEqual(con.execute("SELECT token FROM rug_watch").fetchall(), [("rugged",)])
        ts = self.now + 2 * H
        con.execute("INSERT INTO hype_snapshots VALUES ('rugged', ?, ?, ?, ?)", (ts, 150000 / 1e9, 150000, 50000))  # back to 75% of peak
        con.commit(); con.close()
        a.run(self.db, now=self.now + a.CONFIRM_H * H + 60, log=None)
        self.assertNotIn("rugged", a.blocked(self.db, ttl=0))
        con = sqlite3.connect(self.db)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM rug_watch WHERE token='rugged'").fetchone()[0], 0)  # off the watch
        con.close()

    def test_recovered_token_comes_back(self):
        a = self.archive
        t2 = self.now + a.CONFIRM_H * H + 60
        a.run(self.db, now=self.now, log=None)
        a.run(self.db, now=t2, log=None)
        self.assertIn("rugged", a.blocked(self.db, ttl=0))
        con = sqlite3.connect(self.db)
        from hype import tokenstatus
        tokenstatus.ensure(con)
        con.execute("INSERT OR REPLACE INTO token_status (token, has_pair, mcap, checked_ts) VALUES ('rugged', 1, 90000, ?)",
                    (t2 + 3 * H,))                                   # 45% of the 200k peak, above the 40% line
        con.commit(); con.close()
        logs = []
        a.run(self.db, now=t2 + 4 * H, log=logs.append)
        self.assertNotIn("rugged", a.blocked(self.db, ttl=0))
        rec = a.recovered("rugged", self.db)
        self.assertEqual((rec["kind"], round(rec["mcap"] / rec["peak_mcap"], 2)), ("srusen", 0.45))
        self.assertIsNone(a.get("rugged", self.db))                 # out of the rug profile's data
        self.assertTrue(any("vraćeno u praćenje" in l for l in logs), logs)

    def test_open_position_protected(self):
        a = self.archive
        p = sqlite3.connect(os.path.join(self.d, "paper.db"))
        p.execute("CREATE TABLE trades (token TEXT, status TEXT)")
        p.execute("INSERT INTO trades VALUES ('rugged', 'open')")
        p.commit()
        p.close()
        a.run(self.db, now=self.now, log=None)
        self.assertNotIn("rugged", a.blocked(self.db, ttl=0))

    def test_judge(self):
        j = self.archive.judge
        self.assertEqual(j(100000, 20000, 30000, 8000)[0], "srusen")
        self.assertEqual(j(100000, 0, 30000, 0)[0], "likvidnost")
        self.assertIsNone(j(100000, 80000, 30000, 25000))
        self.assertIsNone(j(None, None, None, None, "pad", "sliči rugovima (90%)"))
        self.assertEqual(j(None, None, None, None, None, None, "ODBAČEN")[0], "mehanika")

    def test_ui_hides_archived(self):
        from ui import data, overview
        self.archive.run(self.db, now=self.now, log=None)
        self.archive.run(self.db, now=self.now + self.archive.CONFIRM_H * H + 60, log=None)   # confirmed 6 h later
        old = (data.HYPE_DB, dict(data.GROUPS))
        data.HYPE_DB = self.db
        data.GROUPS["hype"] = [self.db]
        try:
            toks = {r["token"] for r in overview.token_rows()}
        finally:
            data.HYPE_DB = old[0]
            data.GROUPS.update(old[1])
        self.assertNotIn("rugged", toks)
        self.assertIn("healthy", toks)


class RelevantTest(unittest.TestCase):
    def test_relevant(self):
        from ui import overview
        good = {"hard": False, "collapse": None, "rug": None, "conf": 50}
        self.assertTrue(overview.relevant(good))
        self.assertFalse(overview.relevant({**good, "conf": 20}))
        self.assertFalse(overview.relevant({**good, "hard": True}))
        self.assertFalse(overview.relevant({**good, "rug": {"verdict": "VISOK RIZIK"}}))


class RugProfileTest(unittest.TestCase):
    def test_learns_and_guards(self):
        from learn import rugprofile as rp
        rnd = random.Random(1)
        rows = []
        for i in range(600):
            y = 1 if rnd.random() < 0.3 else 0
            # rugs: thin liquidity for their size and a high "bundle" feature
            bundle = min(1, max(0, rnd.gauss(0.8 if y else 0.2, 0.15)))
            liq, mcap = (3000, 60000) if y else (20000, 60000)
            rows.append({"token": f"t{i}", "ts": i, "y": y, "hit": (not y) and rnd.random() < 0.1,
                         "x": rp.inputs({"bundle": bundle}, mcap, liq)})
        keys = rp._keys(rows)
        m = rp.fit(rows[:300], keys)
        p = [rp.prob(m, r["x"]) for r in rows[300:]]
        self.assertGreater(rp.auc(p, [r["y"] for r in rows[300:]]), 0.9)
        thr = rp.threshold(rows[300:], p)
        self.assertIsNotNone(thr)
        self.assertGreaterEqual(thr["precision"], rp.MIN_PRECISION)
        # a profile that never passed its checks only measures, it does not stop anything
        saved = {"active": False, "thr": None, "model": m}
        sim, stop = rp.judge({"bundle": 0.9}, 60000, 3000, saved)
        self.assertGreater(sim, 0.5)
        self.assertFalse(stop)
        sim, stop = rp.judge({"bundle": 0.9}, 60000, 3000, {**saved, "active": True, "thr": thr["thr"]})
        self.assertTrue(stop)

    def test_too_little_data(self):
        from learn import rugprofile as rp
        d = tempfile.mkdtemp()
        db = make_db(d, time.time())
        from learn import store
        con = store.connect(db)
        os.environ["LEARNED_DIR"] = d
        try:
            r = rp.run(con, apply_model=False)
        finally:
            os.environ.pop("LEARNED_DIR", None)
        self.assertFalse(r["applied"])
        self.assertIn("premalo", r["note"])


class StrongListTest(unittest.TestCase):
    def test_strong_shape(self):
        from dugo import run, score as sc
        cfg = run.config()
        g = cfg["jaki"]
        f = {"starost_d": 40, "volumen_dan": 300000, "stalnost_volumena": 0.7, "pad_od_vrha": -0.3, "holderi_30d": 0.1}
        self.assertTrue(sc.eligible("jaki", f, 300000, 2e7, cfg))
        self.assertFalse(sc.eligible("jaki", f, 300000, 1e6, cfg))                          # too small
        self.assertFalse(sc.eligible("jaki", {**f, "stalnost_volumena": 0.1}, 3e5, 2e7, cfg))  # spiky volume
        self.assertFalse(sc.eligible("jaki", {**f, "holderi_30d": -0.2}, 3e5, 2e7, cfg))       # holders leaving
        self.assertTrue(sc.eligible("jaki", {**f, "holderi_30d": None}, 3e5, 2e7, cfg))        # unknown: no block
        self.assertFalse(sc.eligible("jaki", {**f, "starost_d": g["min_starost_d"] - 1}, 3e5, 2e7, cfg))
        self.assertIn("jaki", cfg["tezine"])

    def test_volume_steadiness_feature(self):
        from dugo import features
        D = 86400
        steady = [(i * D, 1, 1.1, 0.9, 1 + i * 0.01, 100000) for i in range(30)]
        spiky = [(i * D, 1, 1.1, 0.9, 1, 1000000 if i % 7 == 0 else 1000) for i in range(30)]
        self.assertGreater(features.compute(steady)["stalnost_volumena"], 0.9)
        self.assertLess(features.compute(spiky)["stalnost_volumena"], 0.2)


if __name__ == "__main__":
    unittest.main()
