"""20.11. (production: the full insajderi passes "once" / "night" killed by the memory watchdog at 823-930 MB RSS after
the deep pump reads; i2_part ~1M rows, almost all wallets that only traded in one jump window), offline:

  - the list stage reads only the relevant participants (score.load_parts(relevant=True)): every owner that is in it
    classifies exactly as with all rows (score.classify, prijepumpe.classify, smart.roles), every owner left out is
    "promatra" and quiet_owners() counts them; the rows keep their order
  - a whole run.analyze gives the SAME summary and the same tables as with all rows in memory
  - the walks' fingerprints read from the database (walkcache.inputs_db) equal inputs() over all rows
  - prijepumpe.bundles with the owner map in a temp table equals the old dict version
  - chain.build in chunks bounded by our rows gives the same i2_part as one chunk
  - the price series in two arrays reads like the list (copy.Series), the cache is bounded by prices held
  - MEMORY: no read during run.analyze returns the full participant rows (the reads that held ~1M rows at once), and
    the Python heap peak of run.analyze is well under the old one on the same database
  - the log line "insajderi2: memorija N MB nakon koraka X" above store.MEM_LOG_MB (500), silent below

    python3 -m unittest tests.test_insajderi_memorija_offline
"""
import bisect
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import tracemalloc
import unittest
from collections import defaultdict
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from insajderi import chain, copy, events as ev, prijepumpe, run, score, smart, store, walkcache  # noqa: E402
from tests import scale_insajderi_deep as S  # noqa: E402

SCALE, DEPTH, SPAN = 0.05, 0.3, 40


def old_bundles(con, events, c, as_of):
    """prijepumpe.bundles before 20.11. (the owner map and the sellers of every event in dicts), the reference."""
    pumps = [e for e in events if e.get("tier") and e["win_end"] < as_of]
    owner = {w: o for w, o in store.q(con, "SELECT DISTINCT wallet, owner FROM i2_part WHERE owner IS NOT NULL")}
    sold = defaultdict(set)
    for eid, w in store.q(con, "SELECT eid, wallet FROM i2_part WHERE sold_into = 1"):
        sold[eid].add(w)
    min_w, share_min = int(c["bundle_min_wallets"]), float(c["bundle_share"])
    out = {}

    def put(bid, kind, ws, e, share):
        b = out.setdefault(bid, {"kind": kind, "members": set(), "pumps": set(), "pumps15": set(), "shares": {},
                                 "sold": set(), "tokens": set(), "last": 0})
        b["members"] |= set(ws)
        b["pumps"].add(e["token"])
        if e["tier"] == "pumpa15":
            b["pumps15"].add(e["token"])
        if share is not None:
            b["shares"][e["token"]] = max(share, b["shares"].get(e["token"], 0.0))
        if set(ws) & sold[e["eid"]]:
            b["sold"].add(e["token"])
        b["tokens"].add(e["token"])
        b["last"] = max(b["last"], int(e["t0"]))
        if b["kind"] != kind:
            b["kind"] = "isti blok + udio"
    for e in pumps:
        t0, end = int(e["t0"]), int(e["win_end"])
        rows = store.q(con, "SELECT wallet, ts, slot, sol, payer FROM i2_trades WHERE mint = ? AND side = 'buy' AND "
                            "ts BETWEEN ? AND ?", (e["token"], t0 - 6 * 3600, end))
        if not rows:
            continue
        tot = sum(r[3] or 0 for r in rows)
        early_sol, early_w = defaultdict(float), defaultdict(set)
        for w, ts, _slot, sol, _payer in rows:
            if t0 - 3600 <= ts <= t0 + int(c["bundle_early_s"]):
                o = owner.get(w, w)
                early_sol[o] += sol or 0
                early_w[o].add(w)
        shares = {o: (v / tot if tot else None) for o, v in early_sol.items()}
        blocks = defaultdict(list)
        for w, ts, slot, _sol, payer in rows:
            blocks[("s", slot) if slot is not None else ("t", ts)].append((w, payer))
        for blk in blocks.values():
            by = defaultdict(set)
            for w, payer in blk:
                by["o:" + owner.get(w, w)].add(w)
                if payer and payer != w:
                    by["p:" + payer].add(w)
            for key, ws in by.items():
                if len(ws) >= min_w:
                    os_ = {owner.get(w, w) for w in ws}
                    put(key, "isti blok", ws, e, sum(early_sol.get(o, 0.0) for o in os_) / tot if tot else None)
        for o, sh in shares.items():
            if sh is not None and sh >= share_min and len(early_w[o]) >= 2:
                put("o:" + o, "udio ranih kupnji", early_w[o], e, sh)
    return out


def dump(con):
    out = {}
    for t, cols in (("i2_part", "*"), ("i2_groups", "owner, members, cls, why, n_hits, n_early, lift, pnl_sol, tokens, "
                                                   "confirmed_ts, score"),
                    ("i2_pp", "owner, members, cls, why, n_pumps15, n_pumps2, n_tokens, med_lead_min, pnl_sol, "
                              "confirmed_ts, last_seen"),
                    ("i2_pp_copy", "*"), ("i2_copy", "*"), ("i2_bundle", "bid, kind, members, n_pumps, n_pumps15, "
                                                                        "share_med, sold_into, tokens, last_seen"),
                    ("i2_smart", "wallet, owner, cluster, roles, score, n_jumps, n_calls, last_buy_ts, last_token"),
                    ("i2_signals", "*"), ("i2_walk_fp", "*"), ("i2_walk", "walk, through, version, days")):
        out[t] = sorted(con.execute(f"SELECT {cols} FROM {t}"), key=repr)
    return out


class Memory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.p, now = S.build(cls.tmp.name, SCALE, depth=DEPTH, span=SPAN)
        cls.now = now + 3600
        cls.c = store.config(S.cfg())
        con = store.connect(cls.p["insajderi_db"])
        chain.assign_owners(con, cls.p, cls.c)
        con.commit()
        con.close()
        cls.base = os.path.join(cls.tmp.name, "base.db")
        shutil.copy(cls.p["insajderi_db"], cls.base)
        x = sqlite3.connect(cls.base)
        cls.n_part = x.execute("SELECT COUNT(*) FROM i2_part").fetchone()[0]
        x.close()
        # run.analyze twice on copies of the same database: with every row in memory (the old way) and as now; the
        # new one with the reads watched, the RSS read as 650 MB (the log line) and both under tracemalloc
        cls.big, cls.lines = [], []
        real_q = store.q

        def q(con, sql, args=()):
            rows = real_q(con, sql, args)
            if "i2_part" in sql and len(rows) > cls.n_part / 2:
                cls.big.append((sql[:90], len(rows)))
            return rows
        cls.a_con, cls.b_con = cls.db(cls, "a.db"), cls.db(cls, "b.db")
        tracemalloc.start()
        try:
            cls.sa = cls._analyze(cls, cls.a_con, full=True)
            cls.old_peak = tracemalloc.get_traced_memory()[1]
            tracemalloc.reset_peak()
            with mock.patch.object(store, "q", q), mock.patch.object(store, "rss_mb", lambda: 650):
                cls.sb = cls._analyze(cls, cls.b_con, log=cls.lines.append)
            cls.new_peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()

    @classmethod
    def tearDownClass(cls):
        cls.a_con.close()
        cls.b_con.close()
        cls.tmp.cleanup()

    def db(self, name):
        path = os.path.join(self.tmp.name, name)
        shutil.copy(self.base, path)
        return store.connect(path)

    def setUp(self):
        self.con = self.db("work.db")
        self.evs = ev.load_horizon(self.con, self.c, self.now)
        self.full = score.load_parts(self.con)
        self.rel = score.load_parts(self.con, relevant=True)

    def tearDown(self):
        self.con.close()

    def test_the_fixture_has_the_production_shape(self):
        n_owners = len({r[2] or r[1] for r in self.full})
        self.assertLess(len(self.rel), len(self.full) / 3)               # most rows: one jump window, no early buy
        self.assertGreater(n_owners, 1000)
        st = prijepumpe.classify(self.full, self.evs, self.now + 1, self.c)
        self.assertTrue(prijepumpe.confirmed(st))                         # the copy walk has groups to copy
        self.assertTrue(old_bundles(self.con, self.evs, self.c, self.now + 1))

    def test_relevant_parts_classify_the_same_and_the_rest_are_counted(self):
        keys = {r[2] or r[1] for r in self.rel}
        self.assertEqual(self.rel, [r for r in self.full if (r[2] or r[1]) in keys])   # same rows, same order
        bad = {r[1] for r in self.full if r[8] and r[9]}
        bad = set(sorted(bad)[::7])
        a = score.classify(self.full, self.evs, self.now + 1, self.c, bad, {})
        b = score.classify(self.rel, self.evs, self.now + 1, self.c, bad, {})
        self.assertEqual({o: a[o] for o in b}, b)
        rest = {o: s for o, s in a.items() if o not in b}
        self.assertTrue(rest)
        self.assertEqual({s["cls"] for s in rest.values()}, {"promatra"})
        self.assertEqual({s["n_early"] + s["n_hits"] for s in rest.values()}, {0})       # never stored either
        self.assertEqual(score.quiet_owners(self.con, self.evs, self.now + 1, self.rel), len(rest))
        self.assertEqual(score.quiet_owners(self.con, self.evs, self.now + 1, self.full), 0)
        self.assertEqual(prijepumpe.classify(self.full, self.evs, self.now + 1, self.c, bad, {}),
                         prijepumpe.classify(self.rel, self.evs, self.now + 1, self.c, bad, {}))
        self.assertEqual(smart.roles(a, self.evs, self.full, self.now + 1, self.c),
                         smart.roles(b, self.evs, self.rel, self.now + 1, self.c))

    def test_fingerprints_from_the_database_equal_inputs_over_all_rows(self):
        bad = {r[1] for r in self.full[::50]}
        mm = {r[1] for r in self.full[3::70]}
        a = walkcache.inputs(self.evs, self.full, bad, {"x": 1}, mm)
        b = walkcache.inputs_db(self.con, "pp", self.evs, bad, {"x": 1}, mm)
        for k in ("ev", "end", "tok", "own", "ft"):
            self.assertEqual(a[k], b[k], k)
        self.assertEqual({w: a["of"][w] for w in b["of"]}, b["of"])
        self.assertEqual({w for w in set(bad) | set(mm) if w in a["of"]}, set(b["of"]))

    def test_bundles_equal_the_old_dict_version(self):
        a = old_bundles(self.con, self.evs, self.c, self.now + 1)
        b = prijepumpe.bundles(self.con, self.evs, self.c, self.now + 1)
        self.assertEqual(a, b)
        self.assertFalse(store.q(self.con, "SELECT name FROM sqlite_temp_master WHERE name = 'i2_wown'"))

    def test_build_chunks_never_change_the_participants(self):
        pumps = [e for e in self.evs if e.get("tier")]
        con2 = self.db("chunks.db")
        with mock.patch.object(chain, "BUILD_ROWS", 10 ** 9):
            chain.build(self.con, self.p, self.c, pumps)
        with mock.patch.object(chain, "BUILD_ROWS", 500):
            self.assertGreater(len(chain._build_chunks(con2, pumps)), len(pumps) // 100 + 1)
            chain.build(con2, self.p, self.c, pumps)
        q = "SELECT * FROM i2_part ORDER BY eid, wallet"
        self.assertEqual(self.con.execute(q).fetchall(), con2.execute(q).fetchall())
        con2.close()

    def test_series_reads_like_the_list_and_the_cache_is_bounded(self):
        pts = sorted((1000 + 7 * i // 3, 1e-6 * (1 + i % 5)) for i in range(300))
        s = copy.Series(pts)
        self.assertEqual(len(s), len(pts))
        self.assertEqual(list(s), pts)
        for ts in (0, 1000, 1001, 1350, 1699, 5000):
            for key in ((ts, -1.0), (ts, float("inf"))):
                self.assertEqual(bisect.bisect_left(s, key), bisect.bisect_left(pts, key))
                self.assertEqual(bisect.bisect_right(s, key), bisect.bisect_right(pts, key))
            self.assertEqual(copy.Prices.at(s, ts, 900), copy.Prices.at(pts, ts, 900))
            self.assertEqual(copy.Prices.before(s, ts, 900), copy.Prices.before(pts, ts, 900))
        self.assertEqual(list(s[120:]), pts[120:])
        toks = [e["token"] for e in self.evs if e.get("tier")][:6]
        pr = copy.Prices(self.con, self.p, self.c)
        first = [list(pr._sol_series(t)) for t in toks]
        with mock.patch.object(copy, "SOL_CACHE_PTS", 1):
            small = copy.Prices(self.con, self.p, self.c)
            again = [list(small._sol_series(t)) for t in toks]
            self.assertEqual(len(small._sol), 1)                         # only the last one kept
        self.assertEqual(first, again)
        self.assertEqual(pr._n_pts, sum(len(x) for x in first))

    def _analyze(self, con, full=False, log=None):
        real = score.load_parts
        patches = [mock.patch.object(score, "load_parts", lambda c_, relevant=False: real(c_))] if full else []
        for x in patches:
            x.start()
        try:
            return run.analyze(con, self.p, self.c, self.now, log=log or (lambda m: None))
        finally:
            for x in patches:
                x.stop()

    def test_analyze_gives_the_same_summary_and_tables_as_with_every_row(self):
        sa, sb = dict(self.sa), dict(self.sb)
        sa.pop("ts")
        sb.pop("ts")
        self.assertEqual(json.loads(json.dumps(sa, default=str)), json.loads(json.dumps(sb, default=str)))
        self.assertGreater(sb["classes"]["promatra"], 1000)
        self.assertTrue(sb["prije_pumpe"]["confirmed"])
        self.assertTrue(sb["prije_pumpe"]["copy"]["60s"]["svi"]["n_buys"])
        self.assertTrue(sb["smart"]["n_wallets"])
        self.assertEqual(dump(self.a_con), dump(self.b_con))

    def test_MEMORY_no_read_returns_every_participant_and_the_heap_peak_drops(self):
        # the one wide read left: the distinct wallets for the owner map (chain.assign_owners), a set of strings
        self.assertEqual([s for s, _n in self.big if "SELECT DISTINCT wallet FROM i2_part" not in s], [], self.big)
        self.assertLess(self.new_peak, 0.6 * self.old_peak, (self.new_peak >> 20, self.old_peak >> 20))

    def test_the_memory_line(self):
        with mock.patch.object(store, "rss_mb", lambda: 512):
            self.assertEqual(store.mem_line("prije_pumpe"), "insajderi2: memorija 512 MB nakon koraka prije_pumpe")
        for v in (None, 300, 500):
            with mock.patch.object(store, "rss_mb", lambda v=v: v):
                self.assertIsNone(store.mem_line("x"))
        r = store.rss_mb()
        self.assertTrue(r is None or (isinstance(r, int) and r > 0))
        mem = [x for x in self.lines if "memorija" in x]
        for step in ("vlasnici", "dijelovi", "klase", "prije_pumpe", "kopija", "ostalo"):
            self.assertIn(f"insajderi2: memorija 650 MB nakon koraka {step}", mem)


if __name__ == "__main__":
    unittest.main()
