"""19.11. navečer (2): the incremental copy walk-forwards (insajderi/walkcache.py), offline:

  - the fast selection equals classifying every owner every day (rows, null draws and the walk's state)
  - walked over several passes with data arriving in between (new events, a re-read old event) == one walk from
    scratch on the final data (rows and summary)
  - a walk cut by the deadline resumes in the next pass, the line says "kopija: izračunato do ..." until it reaches
    today, and the numbers appear only then
  - PERFORMANCE (bounded, generous): the whole walk on the generator at 1/10 scale

    python3 -m unittest tests.test_kopija_hod_offline
"""
import os
import shutil
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from insajderi import chain, copy, events as ev, score, store, walkcache  # noqa: E402
from tests import scale_insajderi as S  # noqa: E402

D = 86400


class Prices(copy.Prices):
    """A price for every token: 1.0 an hour after a buy-day start, 1.3 three hours later (SOL series)."""

    def __init__(self):
        super().__init__(None, {}, store.config({}))

    def _load_meta(self, tok):
        self.supply[tok] = 1e9

    def _sol_series(self, tok):
        d = int(tok.split("_")[-1])
        return [(d + 3600 + 30, 1e-4), (d + 3 * 3600, 1.3e-4), (d + 30 * 3600, 1.2e-4)]

    def series(self, tok, ts):
        return "sol", self._sol_series(tok)

    def sol_usd(self, ts):
        return 150.0

    def liq_at(self, tok, ts):
        return None

    def bonded(self, tok, mcap, ts):
        return True


def trades_fn(days):
    def fn(members):
        out = []
        for w in sorted(members):
            for d in days:
                if hash((w, d)) % 3 == 0:
                    tok = f"K{w[:8]}_{d}"
                    out.append((w, tok, d + 3600, "buy", 1.0, 1e4))
                    out.append((w, tok, d + 4 * 3600, "sell", 1.2, 1e4))
        return out
    return fn


class Walk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.p, cls.now = S.build(cls.tmp.name, 0.03, seed=11)
        cls.c = store.config({"days": 45, "sol_usd_hist": False, "warmup_days": 1})
        con = store.connect(cls.p["insajderi_db"])
        cls.evs = ev.load_horizon(con, cls.c, cls.now)
        chain.assign_owners(con, cls.p, cls.c)
        cls.parts = score.load_parts(con)
        con.close()
        cls.days = walkcache.days_of(cls.evs, cls.c, cls.now)
        cls.bad = {r[1] for r in cls.parts[::400]}          # a few bots
        cls.base = os.path.join(cls.tmp.name, "base.db")
        shutil.copy(cls.p["insajderi_db"], cls.base)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def db(self, name):
        path = os.path.join(self.tmp.name, name)
        shutil.copy(self.base, path)
        return store.connect(path)

    def walk(self, con, evs=None, parts=None, now=None, fast=True, stop=None):
        evs = self.evs if evs is None else evs
        parts = self.parts if parts is None else parts
        return walkcache.run(con, self.p, self.c, evs, parts, now or self.now, self.bad, {}, set(), stop=stop,
                             prices=Prices(), trades_fn=trades_fn(self.days), fast=fast)

    def dump(self, con):
        return (sorted(con.execute("SELECT * FROM i2_pp_copy")), sorted(con.execute("SELECT * FROM i2_copy")),
                sorted(con.execute("SELECT walk, through FROM i2_walk")))

    def test_fast_selection_equals_everyone_every_day(self):
        a, b = self.db("fast.db"), self.db("slow.db")
        ra = self.walk(a, fast=True)
        rb = self.walk(b, fast=False)
        self.assertEqual(self.dump(a), self.dump(b))
        self.assertEqual(ra["pp"]["summary"], rb["pp"]["summary"])
        self.assertTrue(ra["pp"]["done"] and ra["ins"]["done"])
        self.assertTrue(self.dump(a)[0], "the fixture must produce copy rows")
        self.assertTrue(any(r[0] == "null" for r in self.dump(a)[0]))
        a.close()
        b.close()

    def test_incremental_passes_equal_one_walk_from_scratch(self):
        con = self.db("inc.db")
        t1 = sorted(e["t0"] for e in self.evs)[len(self.evs) // 2]
        evs1 = [e for e in self.evs if e["t0"] < t1]
        ids1 = {e["eid"] for e in evs1}
        r1 = self.walk(con, evs1, [r for r in self.parts if r[0] in ids1], now=self.now - 3 * D)
        self.assertTrue(r1["pp"]["done"])
        # a later pass: new events, and an OLD event re-read (one participant less)
        old = evs1[len(evs1) // 3]["eid"]
        parts2 = [r for r in self.parts if r[0] != old] + [r for r in self.parts if r[0] == old][1:]
        r2 = self.walk(con, self.evs, parts2, now=self.now - D)
        self.assertGreater(r2["pp"]["from"], self.days[0])                   # not from scratch
        r3 = self.walk(con, self.evs, self.parts, now=self.now)
        fresh = self.db("fresh.db")
        r4 = self.walk(fresh)
        self.assertEqual(self.dump(con), self.dump(fresh))
        self.assertEqual(r3["pp"]["summary"], r4["pp"]["summary"])
        self.assertEqual(r3["ins"]["summary"], r4["ins"]["summary"])
        r5 = self.walk(con)                                                 # nothing changed: only the tail
        self.assertEqual(r5["pp"]["from"], self.days[-2])
        con.close()
        fresh.close()

    def test_resume_after_a_cut_and_the_progress_line(self):
        con = self.db("cut.db")
        n = [0]

        def stop():
            n[0] += 1
            return n[0] > 10                                                # about ten days a pass
        r1 = self.walk(con, stop=stop)
        self.assertFalse(r1["pp"]["done"])
        self.assertIsNone(r1["pp"]["summary"])
        line = walkcache.progress(r1["pp"])
        th = store.day(r1["pp"]["through"])
        self.assertEqual(line, f"kopija: izračunato do {th[8:10]}.{th[5:7]}. ({r1['pp']['n']} od {len(self.days)} dana)")
        passes = 1
        while True:
            n[0] = 0
            r = self.walk(con, stop=stop)
            passes += 1
            if r["pp"]["done"] and r["ins"]["done"]:
                break
            self.assertLess(passes, 60)
        fresh = self.db("cutfresh.db")
        r_full = self.walk(fresh)
        self.assertEqual(self.dump(con), self.dump(fresh))
        self.assertEqual(r["pp"]["summary"], r_full["pp"]["summary"])
        con.close()
        fresh.close()

    def test_whole_walk_at_a_tenth_of_production_PERFORMANCE(self):
        with tempfile.TemporaryDirectory() as d:
            p, now = S.build(d, 0.1)
            c = store.config({"days": 45, "sol_usd_hist": False})
            con = store.connect(p["insajderi_db"])
            evs = ev.load_horizon(con, c, now)
            chain.assign_owners(con, p, c)
            parts = score.load_parts(con)
            t = time.perf_counter()
            r = walkcache.run(con, p, c, evs, parts, now, set(), {}, set(), trades_fn=lambda ms: [])
            first = time.perf_counter() - t
            t = time.perf_counter()
            walkcache.run(con, p, c, evs, parts, now + 600, set(), {}, set(), trades_fn=lambda ms: [])
            again = time.perf_counter() - t
            con.close()
        self.assertTrue(r["pp"]["done"] and r["ins"]["done"])
        self.assertLess(first, 120.0)                      # generous: a few seconds on the development box
        self.assertLess(again, first + 5.0)
        print(f"\nhod kopije 1/10: prvi {first:.1f} s, ponovno {again:.1f} s", file=sys.stderr)


class PassLine(unittest.TestCase):
    def test_the_pass_line_splits_the_copy_stage_and_the_progress_line(self):
        from unittest import mock
        from insajderi import prijepumpe, report, run
        from tests.test_insajderi2_offline import build_world, cfg, t0_of
        with tempfile.TemporaryDirectory() as d:
            p, ch = build_world(d)
            lines = []
            with mock.patch.object(report, "OUT_DIR", d), mock.patch.dict(os.environ, {"INSAJDERI_DB": p["insajderi_db"]}):
                run.run("once", now=t0_of(6) + 2 * D, cfg=cfg(), credits=100_000, fetch=ch.fetch, log=lines.append, **p)
        tl = [x for x in lines if x.startswith("insajderi2: prolaz once: trajanje:")][0]
        self.assertIn("kopija prije pumpe ", tl)
        self.assertIn("kopija insajderi ", tl)
        pp = {"covered15": 1, "covered2": 2, "pumps15": 1, "pumps2": 2, "groups": 3, "confirmed": 1, "bundles": 0,
              "copy_progress": "kopija: izračunato do 03.10. (40 od 162 dana)"}
        self.assertIn("; kopija: izračunato do 03.10. (40 od 162 dana), brojke kad dođe do danas; Helius danas 5/9",
                      prijepumpe.line(pp, 5, 9))


if __name__ == "__main__":
    unittest.main()
