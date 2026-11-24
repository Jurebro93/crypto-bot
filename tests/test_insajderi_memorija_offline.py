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

D = 86400
from tests import scale_insajderi_deep as S  # noqa: E402

SCALE, DEPTH, SPAN = 0.05, 0.3, 40
CALL_TRADES, CALL_POOL = 200, 2500   # 20.11. (2): the call events with recurring early buyers (production)


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
        cls.p, now = S.build(cls.tmp.name, SCALE, depth=DEPTH, span=SPAN, call_trades=CALL_TRADES, call_pool=CALL_POOL)
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
        # many rows: one jump window, no early buy; many: the call events' recurring early buyers
        self.assertGreater(len(self.full) - len(self.rel), len(self.full) / 4)
        self.assertGreater(len(self.rel), len(self.full) / 4)
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
        """full: the way before 20.11. (every row in memory, the full stats of every owner kept to the end, smart money's
        walk-forward classifying and re-reading everyone every day): the reference for the results and the memory."""
        real, real_cls = score.load_parts, score.classify
        patches = [mock.patch.object(score, "load_parts", lambda c_, relevant=False: real(c_)),
                   mock.patch.object(score, "classify", lambda *a, slim=None, **k: real_cls(*a, **k)),
                   mock.patch.object(score, "light", lambda st: st),
                   mock.patch.object(smart, "_DayRoles", lambda *a, **k: None)] if full else []
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

    def test_MEMORY_no_read_returns_every_participant_and_smart_money_holds_less(self):
        # the one wide read left: the distinct wallets for the owner map (chain.assign_owners), a set of strings
        self.assertEqual([s for s, _n in self.big if "SELECT DISTINCT wallet FROM i2_part" not in s], [], self.big)
        self.assertLessEqual(self.new_peak, self.old_peak, (self.new_peak >> 20, self.old_peak >> 20))
        # smart money's walk-forward (the heaviest step, 20.11. (2)): the old way (every owner classified and every
        # row re-read each day) against now, on the same rows and classes
        evs = self.evs
        st = score.classify(self.rel, evs, self.now + 1, self.c, set(), {})
        peaks = {}
        for mode in ("old", "new"):
            con = self.db(f"smart_{mode}.db")
            real = score.classify
            pats = [mock.patch.object(score, "classify", lambda *a, slim=None, **k: real(*a, **k)),
                    mock.patch.object(smart, "_DayRoles", lambda *a, **k: None)] if mode == "old" else []
            for x in pats:
                x.start()
            tracemalloc.start()
            try:
                out = smart.run(con, self.p, self.c, self.now, st, evs, self.rel)
                peaks[mode] = (tracemalloc.get_traced_memory()[1], out, sorted(con.execute("SELECT * FROM i2_signals")))
            finally:
                tracemalloc.stop()
                for x in pats:
                    x.stop()
                con.close()
        self.assertEqual(peaks["old"][1], peaks["new"][1])
        self.assertEqual(peaks["old"][2], peaks["new"][2])
        self.assertTrue(peaks["new"][2], "the fixture must produce signals")
        self.assertLess(peaks["new"][0], 0.75 * peaks["old"][0], (peaks["new"][0] >> 20, peaks["old"][0] >> 20))

    def test_the_memory_line(self):
        with mock.patch.object(store, "rss_mb", lambda: 512):
            self.assertEqual(store.mem_line("prije_pumpe"), "insajderi2: memorija 512 MB nakon koraka prije_pumpe")
        with mock.patch.object(store, "rss_mb", lambda: 300):   # 20.11. (2): from 300 MB
            self.assertEqual(store.mem_line("x"), "insajderi2: memorija 300 MB nakon koraka x")
        for v in (None, 120, 299):
            with mock.patch.object(store, "rss_mb", lambda v=v: v):
                self.assertIsNone(store.mem_line("x"))
        r = store.rss_mb()
        self.assertTrue(r is None or (isinstance(r, int) and r > 0))
        mem = [x for x in self.lines if "memorija" in x]
        for step in ("vlasnici", "dijelovi", "prvi", "botovi", "klase", "spremanje", "katalizatori", "prije_pumpe",
                     "birdeye", "kopija prije pumpe (odabir)", "kopija insajderi (odabir)",
                     "kopija prije pumpe (redovi)", "kopija insajderi (redovi)", "trending", "pametni novac"):
            self.assertIn(f"insajderi2: memorija 650 MB nakon koraka {step}", mem)


def old_wallet_trades(con, p, wallets):
    """copy.wallet_trades before 20.11. (2) (every row read, then deduplicated), the reference."""
    ws = sorted(set(wallets))
    out = []
    for ch in copy._chunks(ws):
        out += store.q(con, f"SELECT wallet, mint, ts, side, sol, tokens FROM i2_trades WHERE wallet IN "
                            f"({copy._in(ch)})", ch)
    ec, wc, hc = store.ro(p.get("early_db")), store.ro(p.get("wallet_db")), store.ro(p.get("hype_db"))
    for ch in copy._chunks(ws):
        out += store.q(ec, f"SELECT wallet, mint, ts, side, sol, tokens FROM group_buys WHERE wallet IN "
                           f"({copy._in(ch)})", ch)
        out += [(w, m, ts, k, abs(s_) if s_ is not None else None, abs(tk) if tk is not None else None)
                for w, m, ts, k, s_, tk in store.q(wc, f"SELECT wallet, mint, ts, kind, sol, tokens FROM wallet_trades "
                                                       f"WHERE kind IN ('buy', 'sell') AND wallet IN ({copy._in(ch)})",
                                                   ch)]
    want = set(ws)
    for c_, sql in ((ec, "SELECT wallet, mint, ts, side, sol, tokens FROM precall_trades"),
                    (hc, "SELECT wallet, mint, ts, side, sol, tokens FROM live_trades"),
                    (hc, "SELECT wallet, mint, ts, side, sol, NULL FROM chain_trades")):
        if c_ is not None:
            out += [r for r in c_.execute(sql) if r[0] in want]
    for x in (ec, wc, hc):
        if x is not None:
            x.close()
    seen, res = set(), []
    for r in out:
        if not r[0] or not r[1] or r[2] is None or r[3] not in ("buy", "sell"):
            continue
        k = (r[0], r[1], int(r[2]), r[3])
        if k not in seen:
            seen.add(k)
            res.append((r[0], r[1], int(r[2]), r[3], r[4], r[5]))
    return sorted(res, key=lambda r: r[2])


class Lean(unittest.TestCase):
    """20.11. (2): the pieces made lighter give the same answers (call events with recurring early buyers)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.p, now = S.build(cls.tmp.name, SCALE, depth=DEPTH, span=SPAN, call_trades=CALL_TRADES, call_pool=CALL_POOL)
        cls.now = now + 3600
        cls.c = store.config(S.cfg())
        cls.con = store.connect(cls.p["insajderi_db"])
        chain.assign_owners(cls.con, cls.p, cls.c)
        cls.evs = ev.load_horizon(cls.con, cls.c, cls.now)
        cls.parts = score.load_parts(cls.con, relevant=True)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        cls.tmp.cleanup()

    def test_wallet_trades_equal_the_old_read(self):
        ws = {r[1] for r in self.parts[::3]}
        self.assertEqual(copy.wallet_trades(self.con, self.p, ws), old_wallet_trades(self.con, self.p, ws))
        self.assertGreater(len(old_wallet_trades(self.con, self.p, ws)), 1000)

    def test_slim_classes_equal_the_full_ones(self):
        bad = set(sorted({r[1] for r in self.parts if r[8] and r[9]})[::9])
        full = score.classify(self.parts, self.evs, self.now + 1, self.c, bad, {})
        light = score.classify(self.parts, self.evs, self.now + 1, self.c, bad, {}, slim="light")
        stored = score.classify(self.parts, self.evs, self.now + 1, self.c, bad, {}, slim="store")
        self.assertEqual(list(full), list(light))
        self.assertEqual(list(full), list(stored))
        for o, s in full.items():
            for k in ("cls", "confirmed", "n_early", "n_hits"):
                self.assertEqual(s[k], light[o][k], (o, k))
            if not (s["cls"] == "promatra" and s["n_early"] + s["n_hits"] < 2):
                self.assertEqual(s, stored[o])
        self.assertEqual(score.confirmed(full), score.confirmed(light))
        self.assertEqual(score.confirmed(full), score.confirmed(score.light(full)))
        self.assertTrue({s["cls"] for s in full.values()} >= {"promatra", "kandidat", "bot_snajper"})
        a, b = self.db_pair()
        self.assertEqual(score.save(a, full, self.now), score.save(b, stored, self.now))
        q = "SELECT * FROM i2_groups ORDER BY owner"
        self.assertEqual(a.execute(q).fetchall(), b.execute(q).fetchall())
        a.close()
        b.close()

    def db_pair(self):
        out = []
        for n in ("x.db", "y.db"):
            path = os.path.join(self.tmp.name, n)
            shutil.copy(self.p["insajderi_db"], path)
            out.append(store.connect(path))
        return out

    def test_day_roles_equal_roles_every_day(self):
        days = smart._DayRoles(self.evs, self.parts, self.c)
        t0 = min(e["t0"] for e in self.evs)
        n = 0
        for d in range(t0 - t0 % D + D, self.now + D, D):
            st = score.classify(self.parts, self.evs, d, self.c)
            want = {o: x["members"] for o, x in smart.roles(st, self.evs, self.parts, d, self.c).items()}
            got = days.at(d)
            self.assertEqual(list(want.items()), list(got.items()), store.day(d))
            n += len(got)
        self.assertGreater(n, 100)

    def test_the_aggregate_cache_keeps_the_big_lists(self):
        score._AGG.clear()
        big = list(self.parts)
        a = score.aggregate(big)
        sub = big[: len(big) // 2]
        score.aggregate_subset(sub, big)
        for k in range(5):   # a day's few owners each: never pushes the big ones out
            score.aggregate(big[k:k + 3])
        self.assertIs(score.aggregate(big), a)
        self.assertEqual(len(score._AGG), score.AGG_KEEP)


class Stages(unittest.TestCase):
    """20.11. (2): the pass as three processes (run_insajderi.py --stage a|b|c) gives the same as one."""

    def test_three_stages_equal_one_pass(self):
        from insajderi import report
        from tests.test_insajderi2_offline import build_world, cfg, t0_of
        with tempfile.TemporaryDirectory() as d:
            p, ch = build_world(d)
            now = t0_of(6) + 2 * D
            out = {}
            for mode in ("one", "three"):
                for f in (p["insajderi_db"], p["insajderi_db"] + "-wal", p["insajderi_db"] + "-shm"):
                    if os.path.exists(f):
                        os.remove(f)
                lines = []
                with mock.patch.object(report, "OUT_DIR", d), mock.patch.dict(os.environ, {"INSAJDERI_DB": p["insajderi_db"]}), \
                        mock.patch.object(store, "rss_mb", lambda: 650):
                    if mode == "one":
                        s = run.run("once", now=now, cfg=cfg(), credits=100_000, fetch=ch.fetch, log=lines.append, **p)
                    else:
                        r = [run.run("once", now=now, cfg=cfg(), credits=100_000, fetch=ch.fetch, log=lines.append,
                                     stage=st, **p) for st in ("a", "b", "c")]
                        self.assertEqual((r[0], r[1]), ({"stage": "a", "next": "b"}, {"stage": "b", "next": "c"}))
                        s = r[2]
                        again = run.run("once", now=now, cfg=cfg(), credits=100_000, fetch=ch.fetch,
                                        log=lines.append, stage="c", **p)
                        self.assertEqual(again, {"stage": "c", "next": None})   # a stray stage never repeats
                con = store.connect(p["insajderi_db"])
                out[mode] = (json.loads(json.dumps({k: v for k, v in s.items() if k not in ("ts", "trajanje")},
                                                   default=str)),
                             sorted(s["trajanje"]), dump(con),
                             [x for x in lines if "trajanje" not in x and "memorija" not in x], lines)
                con.close()
        self.assertEqual(out["one"][:4], out["three"][:4])
        self.assertTrue(out["one"][0]["prije_pumpe"])
        mem = [x for x in out["three"][4] if "memorija" in x]
        for step in ("dogadaji", "lanac", "klase", "prije_pumpe", "trending", "pametni novac", "kol"):
            self.assertIn(f"insajderi2: memorija 650 MB nakon koraka {step}", mem)

    def test_the_parent_runs_the_stages_and_fails_with_them(self):
        import run_insajderi as ri
        calls, lines = [], []

        def fake(rcs):
            it = iter(rcs)

            def sub(args, **_k):
                calls.append(args[2:])
                return mock.Mock(returncode=next(it))
            return sub
        with mock.patch("subprocess.run", fake([0, 0, 0])), mock.patch("builtins.print", lambda *a, **k: lines.append(a)):
            self.assertEqual(ri.stages("night", ["night", "--credits", "500"]), 0)
        self.assertEqual(calls, [["night", "--credits", "500", "--stage", s] for s in "abc"])
        calls.clear()
        with mock.patch("subprocess.run", fake([0, 3])):
            self.assertEqual(ri.stages("incr", ["incr"]), 0)              # incr / a cut ends in b
        self.assertEqual(len(calls), 2)
        calls.clear()
        with mock.patch("subprocess.run", fake([3])):
            self.assertEqual(ri.stages("once", []), 0)                    # skipped (the once gap): a only
        self.assertEqual(calls, [["once", "--stage", "a"]])
        with mock.patch("subprocess.run", fake([0, -15])), mock.patch("builtins.print", lambda *a, **k: lines.append(a)):
            self.assertEqual(ri.stages("once", ["once"]), 143)            # stopped by the memory watchdog
        self.assertIn(("insajderi2: dio prolaza b (popis i kopija) nije uspio (signal 15)",), lines)
        with mock.patch("subprocess.run", fake([0, 0, 1])), mock.patch("builtins.print", lambda *a, **k: lines.append(a)):
            self.assertEqual(ri.stages("once", ["once"]), 1)
        self.assertIn(("insajderi2: dio prolaza c (ostalo i kol) nije uspio (kod 1)",), lines)


if __name__ == "__main__":
    unittest.main()
