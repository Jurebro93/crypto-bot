"""19.11. navečer (production: the forced once pass sat 21 min in the list stage, past its deadline, holding the heavy
lock), offline:

  - PERFORMANCE (bounded, generous): the list stage on the production-scale generator at 1/10 scale finishes well
    under its bound; the owners step no longer scans i2_part once per wallet
  - the owners written by the set-based UPDATE are exactly those of the old per-wallet UPDATE
  - the funnel comes FIRST (cheap SQL) and equals the funnel of the full list on the same data
  - the list stage stops between steps at the pass deadline and at list_max_s, says which step, keeps the last result
  - once / incr rebuild only the young and the never-built events; only the events read in the pass after the fetch

    python3 -m unittest tests.test_popis_brzina_offline
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from insajderi import chain, events as ev, prijepumpe, run, score, store  # noqa: E402
from tests import scale_insajderi as S  # noqa: E402


class Scale(unittest.TestCase):
    def test_list_stage_at_a_tenth_of_production_PERFORMANCE(self):
        with tempfile.TemporaryDirectory() as d:
            p, now = S.build(d, 0.1)
            with mock.patch("builtins.print"):
                t = time.perf_counter()
                out = S.time_steps(p, now)
                total = time.perf_counter() - t
        self.assertLess(out["vlasnici"], 10.0, out)     # was ~18 s at this scale, ~135 min at full scale
        self.assertLess(total, 90.0, out)               # generous: ~1.5 s on the development box

    def test_set_based_owners_equal_the_old_per_wallet_update(self):
        with tempfile.TemporaryDirectory() as d:
            p, now = S.build(d, 0.03)
            old = os.path.join(d, "old.db")
            shutil.copy(p["insajderi_db"], old)
            c = store.config({"sol_usd_hist": False})
            con = store.connect(p["insajderi_db"])
            own, relay = chain.assign_owners(con, p, c)
            new_rows = sorted(con.execute("SELECT eid, wallet, owner FROM i2_part"))
            con.close()
            oc = sqlite3.connect(old)
            wallets = {w for (w,) in oc.execute("SELECT DISTINCT wallet FROM i2_part")}
            oc.executemany("UPDATE i2_part SET owner = ? WHERE wallet = ?",
                           [(own.get(w, w) if w not in relay else "relayer:" + w, w) for w in wallets])
            old_rows = sorted(oc.execute("SELECT eid, wallet, owner FROM i2_part"))
            oc.close()
        self.assertEqual(new_rows, old_rows)
        self.assertTrue(any(o != w for _e, w, o in new_rows))   # some wallets do share an owner

    def test_funnel_first_equals_the_full_funnel(self):
        with tempfile.TemporaryDirectory() as d:
            p, now = S.build(d, 0.03)
            c = store.config({"days": 45, "sol_usd_hist": False})
            con = store.connect(p["insajderi_db"])
            evs = ev.load_horizon(con, c, now)
            first = prijepumpe.funnel_sql(con, c, evs)
            chain.assign_owners(con, p, c)
            parts = score.load_parts(con)
            pp, _mm = prijepumpe.run_list(con, c, now, evs, parts, set(), {}, {})
            con.close()
        full = pp["lijevak"]
        for k in ("pumpe15_1h", "pumpe15_1d", "pumpe2_1h", "pumpe2_1d", "duboko", "rani", "rani_prodali", "blizu_praga",
                  "pokrivenost_pre_med", "pokrivenost_skok_med", "n_pokrivenost"):
            self.assertEqual(first[k], full[k], k)
        self.assertGreater(first["rani_prodali"], 0)
        self.assertGreater(first["blizu_praga"], 0)


class Cut(unittest.TestCase):
    def setUp(self):
        from tests.test_insajderi2_offline import build_world, cfg, t0_of
        self.tmp = tempfile.TemporaryDirectory()
        self.p, self.ch = build_world(self.tmp.name)
        self.now = t0_of(6) + 2 * 86400
        self.cfg = cfg
        from insajderi import report
        for patch in (mock.patch.dict(os.environ, {"INSAJDERI_DB": self.p["insajderi_db"]}),
                      mock.patch.object(report, "OUT_DIR", self.tmp.name)):
            patch.start()
            self.addCleanup(patch.stop)
        run.run("once", now=self.now, cfg=cfg(), credits=100_000, fetch=self.ch.fetch, log=lambda m: None, **self.p)

    def tearDown(self):
        self.tmp.cleanup()

    def analyze(self, slow_step, **cfgk):
        t = [0.0]
        c = store.config(self.cfg(**cfgk))
        clk = store.Clock("once", c, lambda: t[0])
        real = getattr(score, slow_step)

        def slow(*a, **k):
            t[0] += 1000.0
            return real(*a, **k)
        lines = []
        con = store.connect(self.p["insajderi_db"])
        prev = json.loads(store.kv(con, "summary"))
        with mock.patch.object(score, slow_step, slow):
            s = run.analyze(con, self.p, c, self.now + 60, log=lines.append, clk=clk)
        con.close()
        return s, prev, lines, clk

    def test_deadline_stops_at_the_next_step_and_keeps_the_last_result(self):
        s, prev, lines, clk = self.analyze("bots", pass_max_s={"once": 500})
        self.assertTrue(any("popis: prekinuto u koraku klase (vremenska granica prolaza)" in x for x in lines), lines)
        self.assertEqual(s["confirmed"], prev["confirmed"])                 # the stored numbers stay
        self.assertEqual(s["list_skipped"], "prekinuto u koraku klase")
        self.assertIn("lijevak", s["prije_pumpe"])                           # the funnel came first
        self.assertIn("botovi", clk.sub)
        self.assertTrue(any("popis: prekinuto u koraku klase" in x for x in clk.cuts))
        self.assertIn("; popis: vlasnici ", run.time_line("once", clk))

    def test_list_max_s_is_a_hard_guard(self):
        s, _prev, lines, _clk = self.analyze("load_parts", pass_max_s={"once": 100_000}, list_max_s=600)
        self.assertTrue(any("popis: prekinuto u koraku prvi (popis dulji od 600 s)" in x for x in lines), lines)
        self.assertIn("lijevak", s["prije_pumpe"])

    def test_once_rebuilds_only_young_and_unbuilt_events(self):
        built = []
        real = chain.build

        def rec(con, p, c, events, stop=None):
            built.append([e["eid"] for e in events])
            return real(con, p, c, events, stop)
        con = store.connect(self.p["insajderi_db"])
        store.kv(con, "summary", json.dumps({"prije_pumpe": {"x": 1}}))
        store.kv(con, "depth_version", store.FETCH_DEPTH)
        con.commit()
        con.close()
        with mock.patch.object(chain, "build", rec):
            run.run("once", now=self.now + 30 * 86400, cfg=self.cfg(), credits=100_000, fetch=self.ch.fetch,
                    log=lambda m: None, **self.p)
        self.assertEqual(built[0], [])                                       # every event built and old: none
        with mock.patch.object(chain, "build", rec):
            run.run("night", now=self.now + 30 * 86400, cfg=self.cfg(), credits=100_000, fetch=self.ch.fetch,
                    log=lambda m: None, **self.p)
        self.assertTrue(built[-1] if len(built) == 2 else built[1])          # the night rebuilds them all


if __name__ == "__main__":
    unittest.main()
