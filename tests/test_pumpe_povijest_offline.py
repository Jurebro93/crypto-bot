"""19.11. navečer (vlasnik: "zašto ne možeš provjeriti povijesne podatke, više tokena koji su pumpali, i tko je kupio
prije, a prodao u pumpi?"), offline:

  - pumps from the DAILY candles (midcap.db and veliki.db c1d): +50 % in a day / +100 % in 3 days, tiers, t0 = the low
    day, src "c1d", the 1h event of the same pump wins (dedup)
  - the tiered events keep their own 180-day horizon (the call events keep `days`)
  - the deep, time-spread Helius read of a pump: the requested windows / slices / pages, the coverage, the depth
    marker, a shallow (old) read is read again once, i2_trades never counts a trade twice
  - the backfill cap by date and its once / incr values; the forced once pass runs once
  - the funnel counts and its line

    python3 -m unittest tests.test_pumpe_povijest_offline
"""
import calendar
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from insajderi import chain, events as ev, prijepumpe as pp, run, store  # noqa: E402

D = 86400
NOW = calendar.timegm((2026, 11, 20, 12, 0, 0)) // D * D + 12 * 3600
C = store.config({"warmup_days": 1, "sol_usd_hist": False})


def addr(name):
    return (name + "1" * 44)[:44]


def daily_db(path, rows, table_sql, closes):
    con = sqlite3.connect(path)
    con.executescript(table_sql)
    con.executemany("INSERT INTO c1d (token, ts, c) VALUES (?,?,?)", closes)
    for r in rows:
        con.execute(r[0], r[1])
    con.commit()
    con.close()


class Daily(unittest.TestCase):
    def test_daily_pumps_tiers_dedup_and_both_sources(self):
        from veliki import midcap, store as vstore
        big, small, old = addr("Big"), addr("Small"), addr("Gone")
        day0 = NOW - NOW % D
        closes = []
        for tok, jumps in ((big, {100: 1.6, 40: (1.3, 2.1), 10: 1.8}), (small, {60: 1.7}), (old, {150: 1.9})):
            for k in range(170, 0, -1):
                v = 1.0
                j = jumps.get(k)
                if isinstance(j, tuple):
                    v = j[0]
                elif j:
                    v = j
                if (k + 1) in jumps and isinstance(jumps[k + 1], tuple):
                    v = jumps[k + 1][1]
                closes.append((tok, day0 - k * D, v))
        with tempfile.TemporaryDirectory() as d:
            mpath, vpath = os.path.join(d, "m.db"), os.path.join(d, "v.db")
            mc = midcap.connect(mpath)
            mc.execute("INSERT INTO tokens (mint, id, symbol, mcap) VALUES (?,?,?,?)", (big, 1, "BIG", 30e6))
            mc.execute("INSERT INTO tokens (mint, id, symbol, mcap) VALUES (?,?,?,?)", (small, 2, "SM", 3e6))
            mc.executemany("INSERT INTO c1d (token, ts, c) VALUES (?,?,?)", [r for r in closes if r[0] != old])
            mc.commit()
            mc.close()
            vc = vstore.connect(vpath)
            vc.execute("INSERT INTO hist (mint, symbol, mcap) VALUES (?,?,?)", (old, "OLD", 20e6))
            vc.executemany("INSERT INTO c1d (token, ts, c) VALUES (?,?,?)", [r for r in closes if r[0] == old])
            vc.commit()
            vc.close()
            p = {"midcap_db": mpath, "veliki_db": vpath}
            one_h = {big: [(day0 - 10 * D + 3 * 3600, day0 - 10 * D + 9 * 3600)]}   # the 1h event of day -10
            got = ev.daily_events(p, C, NOW, one_h)
        by = {(e["token"], (day0 - e["t0"]) // D): e for e in got}
        self.assertEqual(set(by), {(big, 101), (big, 41), (small, 61), (old, 151)}, sorted(by))   # day -10: the 1h one
        e = by[(big, 101)]
        self.assertEqual((e["src"], e["eid"][:2], ev.res_of(e), e["tier"]), ("c1d 1d", "d:", "1d", "pumpa15"))
        self.assertAlmostEqual(e["peak_mc"], 48e6)                         # 30M today x 1.6 / 1.0 (an estimate)
        self.assertEqual(e["peak_ts"], day0 - 100 * D + D)                 # the end of the peak day
        self.assertEqual(by[(big, 41)]["src"], "c1d 3d")                   # +110 % within 3 days, never +50 % in one
        self.assertEqual(by[(small, 61)]["tier"], "pumpa2")                # 3M x 1.7 = 5.1M
        self.assertEqual(by[(old, 151)]["tier"], "pumpa15")                # veliki.db hist: 20M x 1.9 = 38M

    def test_tiered_events_keep_their_horizon(self):
        with tempfile.TemporaryDirectory() as d:
            con = store.connect(os.path.join(d, "i.db"))
            rows = [("c:old", "call", None, NOW - 100 * D), ("d:old", "jump", "pumpa15", NOW - 100 * D),
                    ("d:older", "jump", "pumpa2", NOW - 200 * D), ("c:new", "call", None, NOW - 5 * D)]
            for eid, kind, tier, t0 in rows:
                con.execute("INSERT INTO i2_events (eid, kind, token, t0, tier, win_end) VALUES (?,?,?,?,?,?)",
                            (eid, kind, "t", t0, tier, t0 + 3600))
            con.commit()
            got = {e["eid"] for e in ev.load_horizon(con, store.config({"days": 45, "pump_days": 180}), NOW)}
            con.close()
        self.assertEqual(got, {"d:old", "c:new"})


class Fake:
    """getTransactionsForAddress with blockTime filters: records (address, since, until, pages, asc); returns
    transactions covering half of each requested window (not complete)."""

    def __init__(self, n=3):
        self.calls, self.n = [], n

    def __call__(self, address, since_ts=None, until_ts=None, max_pages=3, oldest_first=False, on_credits=None):
        self.calls.append((address, since_ts, until_ts, max_pages, oldest_first))
        if on_credits:
            for _ in range(max_pages):
                on_credits(10)
        mid = (since_ts + until_ts) // 2
        txs = []
        for i in range(self.n):
            ts = since_ts + 1 + (mid - since_ts - 1) * i // max(1, self.n - 1)
            txs.append({"blockTime": ts, "slot": ts, "transaction": {"signatures": [f"s{address[:4]}{ts}"],
                                                                    "message": {"accountKeys": []}},
                        "meta": {"err": None}})
        return txs, False


class Deep(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = store.connect(os.path.join(self.tmp.name, "i.db"))
        self.e = {"eid": "j:T:1", "kind": "jump", "token": addr("Tok"), "t0": NOW - 3 * D, "win_end": NOW - 3 * D + 8 * 3600,
                  "tier": "pumpa15", "src": "midcap 6h", "fetched": 1, "prio": 1.0, "callers": {}}
        self.con.execute("INSERT INTO i2_events (eid, kind, token, t0, tier, win_end, fetched, src) VALUES (?,?,?,?,?,?,?,?)",
                         (self.e["eid"], "jump", self.e["token"], self.e["t0"], "pumpa15", self.e["win_end"], 1,
                          "midcap 6h"))
        self.con.commit()
        self.p = {k: os.path.join(self.tmp.name, f"{k}.db") for k in ("hype_db", "kol_db", "early_db", "wallet_db")}

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_spread_windows_coverage_depth_and_reread_once(self):
        self.assertEqual(chain.due_events(self.con, [self.e], NOW), [self.e])   # fetched shallow before: read again
        f = Fake()
        spent = chain.fetch_event_deep(self.con, self.p, C, self.e, NOW, 10_000, fetch=f, log=lambda m: None)
        mint_calls = [x for x in f.calls if x[0] == self.e["token"]]
        pre = [x for x in mint_calls if x[2] <= self.e["t0"]]
        jump = [x for x in mint_calls if x[1] >= self.e["t0"]]
        self.assertEqual(len(pre), 10)                                      # pump_slices_pre
        self.assertEqual(pre[0][1], self.e["t0"] - 24 * 3600)               # 24 h before t0 for a 1h event
        self.assertEqual(pre[-1][2], self.e["t0"])
        self.assertEqual({x[3] for x in pre}, {2})                          # 20 pages over 10 slices
        self.assertTrue(all(x[4] for x in mint_calls))                      # each slice oldest first
        self.assertEqual(len(jump), 10)
        self.assertLessEqual(spent, C["pump_event_max_credits"])
        d, pc, jc, n = self.con.execute("SELECT depth, pre_cov, jump_cov, n_tx FROM i2_cover").fetchone()
        self.assertEqual(d, store.FETCH_DEPTH)
        self.assertAlmostEqual(pc, 0.5, delta=0.02)                        # half of every slice
        self.assertAlmostEqual(jc, 0.5, delta=0.02)
        self.assertEqual(n, 60)
        self.assertEqual(chain.due_events(self.con, [self.e], NOW), [])    # read once at the new depth
        # a 1d event: 72 h before t0
        e1 = dict(self.e, eid="d:T:1", src="c1d 1d", fetched=0)
        f2 = Fake()
        chain.fetch_event_deep(self.con, self.p, C, e1, NOW, 10_000, fetch=f2, log=lambda m: None)
        self.assertEqual(min(x[1] for x in f2.calls if x[0] == e1["token"]), e1["t0"] - 72 * 3600)

    def test_the_cap_per_event_and_no_double_count(self):
        f = Fake()
        spent = chain.fetch_event_deep(self.con, self.p, dict(C, pump_event_max_credits=100), self.e, NOW, 10_000, fetch=f,
                                       log=lambda m: None)
        self.assertLessEqual(spent, 100)
        self.assertIsNone(self.con.execute("SELECT 1 FROM i2_cover").fetchone())   # not read to its end: no depth
        rows = [(self.e["token"], addr("W"), "sigX", NOW, 1, "buy", 1.0, 1.0, None, None)]
        for _ in range(2):
            self.con.executemany("INSERT OR IGNORE INTO i2_trades VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM i2_trades").fetchone()[0], 1)   # keyed by signature


class Backfill(unittest.TestCase):
    def test_cap_by_date_and_pass_values(self):
        c = store.config()
        d20 = calendar.timegm((2026, 11, 20, 3, 0, 0))
        d26 = calendar.timegm((2026, 11, 26, 3, 0, 0))
        d18 = calendar.timegm((2026, 11, 18, 3, 0, 0))
        d21 = calendar.timegm((2026, 11, 21, 0, 30, 0))
        self.assertEqual(store.helius_cap(c, d20), (250000, "punjenje povijesti do 20.11."))
        self.assertEqual(store.helius_cap(c, d21)[0], 60000)   # 20.11.: the backfill ended a day after it began
        self.assertEqual(store.helius_cap(c, d26)[0], 60000)
        self.assertEqual(store.helius_cap(c, d18)[0], 60000)
        self.assertEqual((store.effective(c, d20)["pass_max_s"]["once"], store.effective(c, d20)["incr_share"]),
                         (1800, 0.2))
        self.assertEqual((store.effective(c, d26)["pass_max_s"]["once"], store.effective(c, d26)["incr_share"]),
                         (900, 0.1))

    def test_forced_once_runs_once(self):
        from tests.test_insajderi2_offline import build_world, cfg, t0_of
        with tempfile.TemporaryDirectory() as d:
            p, ch = build_world(d)
            con = store.connect(p["insajderi_db"])
            store.kv(con, "once_last", t0_of(6) + 2 * D - 600)   # an earlier deploy's pass 10 min ago
            con.commit()
            self.assertTrue(run.force_once(con))
            con.close()
            from insajderi import report
            with mock.patch.object(report, "OUT_DIR", d), mock.patch.dict(os.environ, {"INSAJDERI_DB": p["insajderi_db"]}):
                lines = []
                s = run.run("once", now=t0_of(6) + 2 * D, cfg=cfg(), fetch=ch.fetch, log=lines.append, **p)
                self.assertIn("prije_pumpe", s)
                self.assertTrue(any(x.startswith("novčanici prije pumpe: lijevak: ") for x in lines), lines)
                self.assertTrue(any("pumpe: ≥ 15M" in x for x in lines), lines)
                lines2 = []
                run.run("once", now=t0_of(6) + 2 * D + 600, cfg=cfg(), fetch=ch.fetch, log=lines2.append, **p)
                self.assertTrue(any("prolaz nakon deploya već odrađen" in x for x in lines2), lines2)
            con = store.connect(p["insajderi_db"])
            self.assertFalse(run.force_once(con))
            store.kv(con, "depth_version", store.FETCH_DEPTH - 1)          # a new depth: forced again
            self.assertTrue(run.force_once(con))
            con.close()


class Funnel(unittest.TestCase):
    def test_counts_and_line(self):
        with tempfile.TemporaryDirectory() as d:
            con = store.connect(os.path.join(d, "i.db"))
            evs = [{"eid": "a", "tier": "pumpa15", "src": "midcap 6h", "token": "x"},
                   {"eid": "b", "tier": "pumpa15", "src": "c1d 1d", "token": "y"},
                   {"eid": "c", "tier": "pumpa2", "src": "c1d 3d", "token": "z"},
                   {"eid": "k", "tier": None, "src": "calls", "token": "q"}]
            con.executemany("INSERT INTO i2_cover VALUES (?,?,?,?,?,?,?,?,?)",
                            [("a", store.FETCH_DEPTH, 86400, 0.4, 3600, 0.9, 10, 100, NOW),
                             ("b", store.FETCH_DEPTH, 86400, 0.6, 3600, 0.7, 10, 100, NOW),
                             ("c", 1, 86400, 0.1, 3600, 0.1, 10, 100, NOW)])
            parts = [("a", "w1", "w1", 1, 1, 1, 2, 2, 1, 1, 60), ("b", "w1", "w1", 1, 1, 1, 2, 2, 1, 1, 60),
                     ("a", "w2", "w2", 1, 1, 0, None, None, 1, 0, 60), ("k", "w3", "w3", 1, 1, 1, 2, 2, 1, 1, 60)]
            st = {"w1": {"n_tokens": 2, "cls": "kandidat", "confirmed": False},
                  "g": {"n_tokens": 3, "cls": "prije_pumpe", "confirmed": True, "members": ["g"]}}
            f = pp.funnel(con, C, evs, parts, st, NOW)
            con.close()
        self.assertEqual(f, {"pumpe15_1h": 1, "pumpe15_1d": 1, "pumpe2_1h": 0, "pumpe2_1d": 1, "duboko": 2, "rani": 2,
                             "rani_prodali": 1, "blizu_praga": 1, "grupe": 1, "potvrdjeno": 1,
                             "pokrivenost_pre_med": 50.0, "pokrivenost_skok_med": 80.0, "n_pokrivenost": 2})
        ln = pp.funnel_line({"lijevak": f, "punjenje": "punjenje povijesti do 25.11."})
        self.assertEqual(ln, "novčanici prije pumpe: lijevak: pumpi ≥ 15M 2 (1h 1, 1d 1), 2-15M 1 (1h 0, 1d 1); "
                             "pročitano do pune dubine 2; ranih kupaca 2, od njih prodali u pumpu 1; blizu praga (2 pumpe) "
                             "1; grupa s 3+ pumpe 1; potvrđeno 1; pokrivenost prozora prije skoka: medijan 50 % (skok "
                             "80 %, 2 pumpi); punjenje povijesti do 25.11.")


if __name__ == "__main__":
    unittest.main()
