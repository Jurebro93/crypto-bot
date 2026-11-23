"""23.11.2026. (production 01:56 UTC: "nadzor memorije: insajderi drži 911 MB" -> "dio prolaza c (ostalo i kol) nije
uspio (signal 15)", ten minutes after the last memory line), offline:

  - insajderi/store.step_mem: a line every STEP_MEM_EVERY_S while a long step runs, only at MEM_LOG_MB or more,
    naming the step and its running sub-step (store.substep); only the innermost step writes; silent after the step
  - run.py wires it into every stage and step (događaji, lanac, popis steps, copy walks, trending, pametni novac, kol)
  - insajderi/trending.hourly: the rows are streamed and the features are a slotted object: the same numbers, keys
    and order as the old dict version, and trending.run gives the same summary

    python3 -m unittest tests.test_insajderi_korak_offline
"""
import os
import random
import sqlite3
import sys
import tempfile
import time
import unittest
from collections import defaultdict
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from insajderi import store, trending  # noqa: E402


class StepMem(unittest.TestCase):
    def test_lines_while_the_step_runs(self):
        lines = []
        with mock.patch.object(store, "rss_mb", lambda: 640):
            with store.step_mem("pametni novac", lines.append, every_s=0.05):
                with store.substep("hod po danima"):
                    time.sleep(0.18)
            n = len(lines)
            time.sleep(0.15)
        self.assertGreaterEqual(n, 2)
        self.assertEqual(len(lines), n)                                       # nothing after the step
        self.assertRegex(lines[0], r"^insajderi2: memorija 640 MB u koraku pametni novac > hod po danima \(\d+ s\)$")
        self.assertEqual((store._STEPS, store._MEMS), ([], []))

    def test_only_the_innermost_and_only_above_the_limit(self):
        lines = []
        with mock.patch.object(store, "rss_mb", lambda: 450):
            with store.step_mem("popis", lines.append, every_s=0.05):
                with store.step_mem("popis: prije_pumpe", lines.append, every_s=0.05):
                    time.sleep(0.16)
        self.assertTrue(lines)
        self.assertTrue(all(" u koraku popis > popis: prije_pumpe (" in x for x in lines), lines)
        lines.clear()
        with mock.patch.object(store, "rss_mb", lambda: 299):
            with store.step_mem("trending", lines.append, every_s=0.03):
                time.sleep(0.12)
        self.assertEqual(lines, [])
        with mock.patch.object(store, "rss_mb", lambda: 500):   # a broken log never breaks the pass
            with store.step_mem("kol", lambda m: 1 / 0, every_s=0.03):
                time.sleep(0.08)
        self.assertEqual(store.STEP_MEM_EVERY_S, 30)

    def test_wired_in_every_long_step(self):
        with open(os.path.join(ROOT, "insajderi", "run.py"), encoding="utf-8") as f:
            src = f.read()
        for name in ('"dogadaji"', '"lanac"', '"kol"', '"birdeye"', 'f"popis: {name}"', '"trending"', '"pametni novac"'):
            self.assertIn(f"store.step_mem({name}, log)", src, name)
        self.assertIn("'kopija insajderi'}.get(name, name)} \"\n", src)
        with open(os.path.join(ROOT, "insajderi", "smart.py"), encoding="utf-8") as f:
            sm = f.read()
        for name in ("uloge", "trgovine", "klasteri", "hod po danima"):
            self.assertIn(f'store.substep("{name}")', sm)


def _old_hourly(p, since):
    """insajderi/trending.hourly before 23.11. (fetchall + a dict per token-hour), the reference."""
    mc = store.ro(p.get("midcap_db"))
    if mc is None:
        return {}
    ids = dict(store.q(mc, "SELECT id, mint FROM tokens"))
    rows = store.q(mc, """SELECT id, ts / 3600, MAX(ts), mc, liq, v1h, v24, b1h, s1h, b24, c1h FROM snap WHERE ts >= ?
        GROUP BY id, ts / 3600""", (int(since),))
    mc.close()
    out = defaultdict(list)
    for i, h, _ts, mcap, liq, v1h, v24, b1h, s1h, b24, c1h in rows:
        m = ids.get(i)
        if not m:
            continue
        f = {"vacc": (v1h or 0) / ((v24 or 0) / 24) if v24 else 0.0, "b1h": float(b1h or 0),
             "bacc": (b1h or 0) / ((b24 or 0) / 24) if b24 else 0.0,
             "bshare": (b1h or 0) / ((b1h or 0) + (s1h or 0)) if (b1h or s1h) else 0.5,
             "c1h": float(c1h or 0), "liq_mc": (liq or 0) / mcap if mcap else 0.0}
        out[m].append((int(h) * 3600, f))
    for m in out:
        out[m].sort(key=lambda x: x[0])
    return out


class Trending(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from veliki import midcap
        cls.tmp = tempfile.TemporaryDirectory()
        cls.p = {"midcap_db": os.path.join(cls.tmp.name, "midcap.db")}
        con = sqlite3.connect(cls.p["midcap_db"])
        con.executescript(midcap.SCHEMA)
        rnd = random.Random(7)
        cls.now = 1_795_300_000
        con.executemany("INSERT INTO tokens (mint, id, symbol, trend, first_ts, src) VALUES (?,?,?,?,?,?)",
                        [(f"M{i:03d}", i, f"S{i}", (i % 9) or None, cls.now - 86400 * (i % 5), "gt") for i in range(60)])
        rows = []
        for i in range(62):   # ids 60 and 61 have no token row: skipped as before
            for ts in range(cls.now - 6 * 86400, cls.now, 900):
                z = rnd.random()
                rows.append((i, ts + rnd.randrange(60), 1e-3, None if z < 0.02 else rnd.randint(1, 9) * 10 ** 6,
                             rnd.randint(1, 9) * 10 ** 5, 1, rnd.randint(0, 9) * 1000, 1, None if z < 0.05 else
                             rnd.randint(0, 9) * 9000, 1, 1, rnd.randint(0, 50), rnd.randint(0, 50), rnd.randint(0, 900),
                             1, 0.1, rnd.uniform(-5, 5), 0.0, 0.0))
        con.executemany("INSERT OR IGNORE INTO snap VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        con.commit()
        con.close()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_same_series(self):
        since = self.now - 5 * 86400
        new, old = trending.hourly(self.p, since), _old_hourly(self.p, since)
        self.assertEqual(list(new), list(old))
        for m in old:
            self.assertEqual([(ts, tuple(f[k] for k in trending.FEATURES)) for ts, f in new[m]],
                             [(ts, tuple(f[k] for k in trending.FEATURES)) for ts, f in old[m]])
        with self.assertRaises(KeyError):
            next(iter(new.values()))[0][1]["nope"]
        self.assertEqual(trending.hourly({"midcap_db": os.path.join(self.tmp.name, "none.db")}, since), {})

    def test_run_gives_the_same_summary(self):
        c = dict(store.config({"sol_usd_hist": False}), mkt_days=5)
        out = []
        for k, fn in (("a", trending.hourly), ("b", _old_hourly)):
            con = store.connect(os.path.join(self.tmp.name, f"ins_{k}.db"))
            con.executemany("INSERT OR REPLACE INTO i2_trend VALUES (?,?,?,?,?,?)",
                            [(f"M{i:03d}", f"S{i}", self.now - (1 + i % 4) * 86400 + 3600 * (i % 7),
                              self.now - 3600, 5, "gt") for i in range(0, 60, 3)])
            con.commit()
            try:
                with mock.patch.object(trending, "hourly", fn):
                    out.append(trending.run(con, self.p, c, self.now))
            finally:
                con.close()
        self.assertEqual(out[0], out[1])
        self.assertGreater(out[0]["pos_train"], 0)
        self.assertTrue(out[0]["weights"])


if __name__ == "__main__":
    unittest.main()
