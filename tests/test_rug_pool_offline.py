"""Rug by the SOL that left the pool beyond what the price explains (11.11. evening, the owner's rule: "očekivani SOL
omjer = sqrt(cijena_kraj / cijena_početak), stvarni = SOL_kraj / SOL_početak, rug ako stvarni / očekivani <= 0,5, ILI
pad cijene >= 90 % i SOL strana >= 90 %, ILI >= 70 % uz dev/top-holder prodaju ili visok rug_risk"): the owner's four
cases, the start after an LP add / a migration, the stricter label that blocks until his switch rug_labels_v2_ok,
statistics on the old labels, a rug voiding a counterfactual win, the SOL columns of the pulse and the relabel of the
last 7 days (counts, X, 5 random rug→dump, once per marker, nothing deleted)."""
import json
import math
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rugfilter import archive, collapse, labels, relabel  # noqa: E402

NOW = 1794400000
H = 3600
X = "CccS" + "7hJ2kQwPz9mNvB4rT6yXa3LdF8sGcE1u" + "y1eU"
HAOBIBI = "8tbfkL8LZYUN3ygzWMKfffqVd7tLRpWkuh2fowsepump"
DEV = "dev prodaje (dev je prodao 70% (kupio 9% na startu))"


class Pool:
    """A constant-product pool: x tokens, y SOL, k = x * y; L = sqrt(k); price p = y / x in SOL."""

    def __init__(self, sol=85.0, tokens=200e6, sol_usd=150.0, supply=1e9):
        self.x, self.y, self.S, self.N = tokens, sol, sol_usd, supply

    def price(self):
        return self.y / self.x

    def L(self):
        return math.sqrt(self.x * self.y)

    def mcap(self):
        return self.price() * self.S * self.N

    def liq_usd(self):
        return 2 * self.y * self.S

    def trade_to(self, ratio):
        """Swaps until the price is ratio x what it is (no LP change: L stays)."""
        k, p = self.x * self.y, self.price() * ratio
        self.x = math.sqrt(k / p)
        self.y = k / self.x
        return self

    def pull(self, share):
        """LP removed: both reserves down by `share`, the price unchanged."""
        self.x *= 1 - share
        self.y *= 1 - share
        return self

    def add_lp(self, share):
        self.x *= 1 + share
        self.y *= 1 + share
        return self

    def pair(self, dex="pumpswap", labels_=None, addr="POOL1", quote="SOL"):
        q = {"address": collapse.SOL_MINT, "symbol": "SOL"} if quote == "SOL" else {"address": "USDC", "symbol": "USDC"}
        return {"dexId": dex, "labels": labels_ or [], "pairAddress": addr, "quoteToken": q,
                "priceNative": str(self.price()) if quote == "SOL" else str(self.price() * self.S),
                "priceUsd": str(self.price() * self.S), "marketCap": self.mcap(),
                "liquidity": {"usd": self.liq_usd(), "base": self.x, "quote": self.y if quote == "SOL" else self.y * self.S}}


def fold(acc, tok, ts, pool, **kw):
    pp = collapse.pair_pool(pool.pair(**kw))
    return collapse.add(acc, tok, ts, pool.mcap(), pool.liq_usd(), pp["liq_sol"], pp["price_native"], pp["pool"], pp["dex"])


def snaps(*moves):
    """A measured series: [(ts, sol, price)] fed to a peaks() row through add()."""
    acc = {}
    for i, (sol, px) in enumerate(moves):
        collapse.add(acc, "T", NOW - (len(moves) - i) * 600, px * 150 * 1e9, sol * 2 * 150, sol, px, "P1", "pumpswap")
    return acc["T"]


def new(row, **kw):
    return collapse.assess(row, strict=False, **kw)


class OwnerCases(unittest.TestCase):
    """The owner's tests (a) - (d) and the coordinator's "SOL -97 % with L -40 %"."""

    def test_a_price_75_sol_50_is_a_dump(self):
        j = new(snaps((100.0, 1e-6), (50.0, 0.25e-6)))
        self.assertEqual(j["kind"], "dump")
        self.assertAlmostEqual(j["expected"], 0.5, places=3)
        self.assertAlmostEqual(j["actual"], 0.5, places=3)
        self.assertAlmostEqual(j["ratio"], 1.0, places=3)
        self.assertIn("stvarni / očekivani 1,00", j["text"])

    def test_b_price_40_sol_70_is_a_rug(self):
        j = new(snaps((100.0, 1e-6), (30.0, 0.6e-6)))
        self.assertEqual((j["kind"], j["why"]), ("rug", "višak"))
        self.assertAlmostEqual(j["ratio"], 0.3 / math.sqrt(0.6), places=3)          # 0.39 <= 0.5

    def test_c_price_100_sol_97_is_a_rug(self):
        j = new(snaps((100.0, 1e-6), (3.0, 1e-12)))
        self.assertEqual((j["kind"], j["why"]), ("rug", "90/90"))

    def test_d_haobibi(self):
        """HAOBIBI (8tbf…pump, rugged 11.11. 12:51 CET): liquidity 25.7k → 1.9k $, buy share 5m 0.11. Pretpostavka: its
        price at the rug is not stored; (1) a pure CP move would need the price at (1.9 / 25.7)^2 = 0.55 % (-99.5 %):
        the 90 / 90 branch; (2) a pull with the price only -80 %: actual 0.074 / expected 0.45 = 0.17, the excess."""
        pm = 100_000
        j = collapse.judge(pm, pm * (1.9 / 25.7) ** 2, 25_700, 1_900, strict=False)
        self.assertEqual((j["kind"], j["why"]), ("rug", "90/90"))
        j = collapse.judge(pm, pm * 0.2, 25_700, 1_900, strict=False)
        self.assertEqual((j["kind"], j["why"]), ("rug", "višak"))
        self.assertLess(j["ratio"], 0.2)

    def test_sol_97_with_l_40_is_a_rug(self):
        p0 = 1e-6
        sol1 = 3.0                                     # SOL -97 %
        p1 = p0 * (sol1 / 100 / 0.6) ** 2               # L -40 %: SOL = L * sqrt(p)
        j = new(snaps((100.0, p0), (sol1, p1)))
        self.assertAlmostEqual(j["ratio"], 0.6, places=3)
        self.assertEqual((j["kind"], j["why"]), ("rug", "90/90"))   # the ratio says 0.6; the total collapse decides

    def test_cp_dump_85_and_lp_pull_60(self):
        acc, p = {}, Pool()
        fold(acc, "D", NOW - 3600, p)
        fold(acc, "D", NOW, p.trade_to(0.15))
        j = new(acc["D"])
        self.assertEqual((j["kind"], j["basis"], j["sol_measured"]), ("dump", "sol", True))
        self.assertAlmostEqual(j["sol_drop"], 1 - math.sqrt(0.15), places=3)          # SOL -61 % ...
        self.assertAlmostEqual(j["ratio"], 1.0, places=3)                              # ... all of it the price
        acc, p = {}, Pool()
        fold(acc, "R", NOW - 3600, p)
        fold(acc, "R", NOW, p.pull(0.6))
        j = new(acc["R"])
        self.assertEqual((j["kind"], j["drop"]), ("rug", 0.0))                         # LP pulled, price unchanged
        self.assertAlmostEqual(j["ratio"], 0.4, places=3)
        self.assertIn("izvučena likvidnost", j["text"])

    def test_dev_selling_with_a_75_crash(self):
        acc, p = {}, Pool()
        fold(acc, "E", NOW - 3600, p)
        fold(acc, "E", NOW, p.trade_to(0.25))
        self.assertEqual(new(acc["E"])["kind"], "dump")
        j = new(acc["E"], evidence=DEV)
        self.assertEqual((j["kind"], j["why"]), ("rug", "dokaz"))
        self.assertIn("dev prodaje", j["text"])


class StartSnapshot(unittest.TestCase):
    def test_lp_add_moves_the_start(self):
        acc, p = {}, Pool()
        fold(acc, "A", NOW - 3 * 600, p)
        fold(acc, "A", NOW - 2 * 600, p.add_lp(1.0))       # liquidity doubled (L +100 %): the start moves here
        fold(acc, "A", NOW - 600, p.pull(0.6))              # back under the first snapshot's L: 0.8 of it, 0.4 of the start
        j = new(acc["A"])
        self.assertTrue(j["reset"])
        self.assertAlmostEqual(j["ratio"], 0.4, places=3)
        self.assertEqual(j["kind"], "rug")
        self.assertIn("nakon dodavanja likvidnosti", j["text"])
        tr = collapse.Track()
        for ts, sol, px in ((1, 100.0, 1.0), (2, 110.0, 1.0)):   # +10 % L: noise, not an add
            tr.push(ts, sol, px)
        self.assertFalse(tr.state()["reset"])
        tr = collapse.Track()
        for ts, sol, px in ((1, 100.0, 1.0), (2, 3.0, 1e-6)):    # a crash raises L, but no SOL came in: no reset
            tr.push(ts, sol, px)
        self.assertFalse(tr.state()["reset"])

    def test_a_migration_is_another_pool(self):
        acc, curve, swap = {}, Pool(sol=30, tokens=6e8), Pool(sol=85, tokens=2e8)
        fold(acc, "M", NOW - 1200, curve, dex="pumpfun", addr="CURVE")
        fold(acc, "M", NOW - 600, swap, addr="SWAP")
        fold(acc, "M", NOW, swap.trade_to(0.2), addr="SWAP")
        j = new(acc["M"])
        self.assertEqual(j["sol_first"], 85)                 # only the PumpSwap pool, from its first snapshot
        self.assertAlmostEqual(j["ratio"], 1.0, places=3)
        self.assertEqual(j["kind"], "dump")


class NonCp(unittest.TestCase):
    def test_same_rule_and_said(self):
        acc = {}
        for ts, sol, px in ((NOW - 3600, 100.0, 1e-6), (NOW, 25.0, 0.6e-6)):
            collapse.add(acc, "C", ts, px * 150 * 1e9, sol * 2 * 150, sol, px, "CL1", "raydium/CLMM")
        j = new(acc["C"])
        self.assertEqual((j["kind"], j["cp"]), ("rug", False))
        self.assertIn("ne-CP pool raydium/CLMM", j["text"])

    def test_is_cp_and_pair_pool(self):
        for dex, want in (("pumpswap", True), ("raydium/CLMM", False), ("meteora/DLMM", False), ("orca/wp", False),
                          ("pumpfun", False), (None, None)):
            self.assertEqual(collapse.is_cp(dex), want, dex)
        p = Pool()
        pp = collapse.pair_pool(p.pair(labels_=["CPMM"], dex="raydium"))
        self.assertAlmostEqual(pp["liq_sol"], p.y)
        self.assertEqual(pp["dex"], "raydium/CPMM")
        self.assertAlmostEqual(collapse.pair_pool(p.pair(quote="USDC"), sol_usd=150.0)["liq_sol"], p.liq_usd() / 300)

    def test_estimate_from_usd_is_marked(self):
        acc, p = {}, Pool()
        m0, l0 = p.mcap(), p.liq_usd()
        collapse.add(acc, "U", NOW - 3600, m0, l0)
        p.trade_to(0.25)
        collapse.add(acc, "U", NOW, p.mcap(), p.liq_usd())
        j = new(acc["U"])
        self.assertEqual((j["kind"], j["basis"], j["sol_measured"]), ("dump", "usd", False))
        self.assertIn("procjena iz USD", j["text"])


class Strict(unittest.TestCase):
    """Until the owner's switch: a token blocks when the old OR the new label says rug; statistics take the old one."""

    def test_old_rug_new_dump_is_blocked(self):
        p = Pool()
        m0, l0 = p.mcap(), p.liq_usd()
        p.trade_to(0.15)                                             # USD liquidity -61 %: the noon rule says rug
        acc = {}
        collapse.add(acc, "D", NOW - 3600, m0, l0)
        collapse.add(acc, "D", NOW, p.mcap(), p.liq_usd())
        self.assertEqual(collapse.assess_pool(acc["D"])["kind"], "dump")
        with mock.patch.object(labels, "v2_ok", lambda: False):
            j = collapse.check(acc["D"])
            self.assertEqual((j["kind"], j["strict"], j["kinds"]["usd"], j["kinds"]["sol_v2"]), ("rug", "old", "rug", "dump"))
            self.assertIn("stroža oznaka", j["text"])
        with mock.patch.object(labels, "v2_ok", lambda: True):        # after the owner's confirmation: the new label
            self.assertIsNone(collapse.check(acc["D"]))
            self.assertEqual(collapse.assess(acc["D"])["kind"], "dump")

    def test_archive_reads_the_stricter_label(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "hype.db")
            archive.connect(db).close()
            c = sqlite3.connect(db)
            c.execute("INSERT INTO rug_archive (token, kind, peak_mcap, last_mcap, peak_liq, last_liq) VALUES (?,?,?,?,?,?)",
                      ("CPD", "srusen", 500_000, 60_000, 50_000, 50_000 * math.sqrt(0.12)))
            c.commit()
            c.close()
            for ok, want in ((False, "rug"), (True, "dump")):
                archive.forget_cache()
                with mock.patch.object(labels, "v2_ok", lambda ok=ok: ok):
                    self.assertEqual(archive.kinds(db, ttl=0, log=lambda m: None)["CPD"], want)
                    self.assertEqual(archive.kind_one("CPD", db), want)
            self.assertEqual(archive.kinds_detail(db)["CPD"], {"usd": "rug", "pool_v1": "dump", "sol_v2": "dump"})
            self.assertEqual(archive.kind_new("srusen", 50_000, 50_000 * math.sqrt(0.12), 500_000, 60_000), "dump")
        archive.forget_cache()

    def test_statistics_use_the_old_labels_without_the_switch(self):
        ks = {"usd": "rug", "pool_v1": "dump", "sol_v2": "dump"}
        with mock.patch.object(labels, "v2_ok", lambda: False):
            self.assertEqual(labels.for_stats(ks), "rug")
            self.assertEqual(labels.effective(ks), "rug")
        with mock.patch.object(labels, "v2_ok", lambda: True):
            self.assertEqual(labels.for_stats(ks), "dump")
            self.assertEqual(labels.effective(ks), "dump")
        from trade import settings
        self.assertIn(labels.FLAG, settings.FLAGS)
        self.assertIn(labels.FLAG, settings.OWNER_SWITCHES)


class VoidWins(unittest.TestCase):
    """A rug by any label voids a counterfactual win in the statistics (callers, sources, proposals, owner labels)."""

    def setUp(self):
        labels.forget()
        self.addCleanup(labels.forget)

    def test_hits_and_wins(self):
        rugged = frozenset({"RUG"})
        from kol import score
        cfg = json.load(open(os.path.join(os.path.dirname(score.__file__), "config.json")))
        calls = [{"kind": "call", "first_by_kol": 1, "token": t, "ts": NOW + i, "max24": 3.0, "r1h": 0, "vol_lift": 1,
                  "rug": 0, "pre2h": 0, "first_overall": 0, "views": 0, "likes": 0, "retweets": 0, "followers": 0}
                 for i, t in enumerate(("OK", "RUG"))]
        with mock.patch.object(labels, "void_set", lambda **k: rugged):
            s, _ = score.kol_stats(calls, cfg)
            self.assertAlmostEqual(s["hit_rate"], 0.5)                    # the rugged token's +200 % is no hit
            from proposals import report
            ps = [{"token": t, "status": "novo", "after": {"4h": {"status": "ok", "first": "tp", "ret_pct": 50.0}}}
                  for t in ("OK", "RUG")]
            self.assertEqual(report._summ(ps)["hit_rate"], 0.5)
            from fast import outcomes
            con = sqlite3.connect(":memory:")
            con.execute("CREATE TABLE signals (source_id TEXT, kind TEXT, token TEXT, hit INTEGER, out_done INTEGER, "
                        "decided_ts INTEGER)")
            con.executemany("INSERT INTO signals VALUES ('w1','wallet',?,1,1,?)", [("OK", NOW), ("RUG", NOW)])
            self.assertEqual(outcomes.source_rates(con, NOW)["w1"], (1, 2))
            self.assertEqual(outcomes.base_rates(con, NOW)["wallet"], (1, 2))
            from rangedca import owner
            lbs = [{"token": t, "symbol": t, "label": "win", "ts": NOW - 2 * 86400, "data": {"features": {"a": 1}}}
                   for t in ("OK", "RUG")]
            self.assertEqual([w["token"] for w in owner.wins(lbs=lbs, now=NOW)], ["OK"])

    def test_void_set_uses_the_label_statistics_may_use(self):
        # 11.11. (owner): "Statistike ... računaj sa starim oznakama. Nove oznake nemoj koristiti dok ne prođe korak 3":
        # switch off = the OLD label voids a win (R2's only rug is the new sol_v2 label: not voided yet)
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "hype.db")
            archive.connect(db).close()
            c = sqlite3.connect(db)
            c.execute("INSERT INTO rug_archive (token, kind, peak_mcap, last_mcap, peak_liq, last_liq) VALUES (?,?,?,?,?,?)",
                      ("CPD", "srusen", 500_000, 60_000, 50_000, 50_000 * math.sqrt(0.12)))   # old rug, new dump
            c.execute("INSERT INTO rug_relabel (token, src, old_kind, new_kind) VALUES ('R1', 'collapse', 'rug', 'dump')")
            c.execute("INSERT INTO rug_relabel_sol (token, src, old_kind, l_kind, new_kind) "
                      "VALUES ('R2', 'collapse', 'dump', 'dump', 'rug')")
            c.execute("INSERT INTO rug_relabel_sol (token, src, old_kind, l_kind, new_kind) "
                      "VALUES ('OK', 'collapse', 'dump', 'dump', 'dump')")
            c.commit()
            c.close()
            archive.forget_cache()
            nowhere = os.path.join(d, "league.db")
            self.assertEqual(labels.void_set(db, ttl=0, v2=False, league_db=nowhere), {"CPD", "R1"})
            archive.forget_cache()
            self.assertEqual(labels.void_set(db, ttl=0, v2=True, league_db=nowhere), {"R2"})
        archive.forget_cache()


class PulseColumns(unittest.TestCase):
    def test_old_table_gets_the_columns_and_rows_carry_the_sol_side(self):
        from hype import pulse
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = os.path.join(tmp.name, "hype.db")
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE token_pulse (token TEXT, ts INTEGER, price REAL, mcap REAL, liquidity REAL, vol_m5 REAL, "
                    "vol_h1 REAL, buys_m5 INTEGER, sells_m5 INTEGER, buys_h1 INTEGER, sells_h1 INTEGER, holders INTEGER, "
                    "holders_src TEXT, PRIMARY KEY (token, ts))")
        con.execute("INSERT INTO token_pulse (token, ts, mcap, liquidity) VALUES ('OLD', 1, 5, 5)")
        con.execute("CREATE TABLE hype_signals (ts INTEGER, token TEXT, mcap REAL, liquidity REAL)")
        pulse.ensure(con)
        self.assertEqual([r[1] for r in con.execute("PRAGMA table_info(token_pulse)")][-4:],
                         ["liq_sol", "price_native", "pool", "dex"])
        p = Pool()
        pulse.record(con, "T", p.pair(), NOW - 3600)
        pulse.record(con, "T", p.trade_to(0.15).pair(), NOW)
        con.commit()
        con.close()
        j = new(collapse.peaks(db, ["T"], now=NOW)["T"])
        self.assertEqual((j["kind"], j["basis"]), ("dump", "sol"))
        self.assertAlmostEqual(j["ratio"], 1.0, places=3)


# ---------------------------------------------------------------------------------------------------------------
def cp_path(L_usd, mcaps):
    """[(mcap, liq)] of a CP pool with USD liquidity L_usd * sqrt(mcap / 1e6) (L constant)."""
    return [(m, L_usd * math.sqrt(m / 1e6)) for m in mcaps]


class Relabel(unittest.TestCase):
    def setUp(self):
        from hype import pulse
        from hype import store as hstore
        from tiers import store as tstore
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.db = os.path.join(d, "hype.db")
        con = hstore.connect(self.db)
        tstore.connect(self.db).close()
        pulse.ensure(con)
        archive.connect(self.db).close()

        def series(tok, path, start, step=H, sym=None):
            con.execute("INSERT OR REPLACE INTO token_tier (token, symbol, first_ts, last_ts) VALUES (?,?,?,?)",
                        (tok, sym or tok[:5], start, start + step * len(path)))
            for i, (m, liq) in enumerate(path):
                con.execute("INSERT INTO hype_signals (ts, token, symbol, score, price, mcap, liquidity, features) "
                            "VALUES (?,?,?,?,?,?,?,?)", (start + i * step, tok, sym, 50, m / 1e9, m, liq, "{}"))

        t0 = NOW - 72 * H
        up = [100_000 + 50_000 * i for i in range(11)]                        # 100k -> 600k in 10 h
        for k, tok in enumerate(("DUMP", "DUMP2", "DUMP3", "DUMP4")):        # -85 %, the SOL side as the price explains
            series(tok, cp_path(80_000 + k, up + [600_000] * 15 + [90_000] * 20), t0)
        series("PULL", [(200_000, 40_000)] * 20 + [(200_000, 12_000)] * 2 + [(100_000, 8_485)] * 10, t0)   # LP -70 %
        series("DEV", cp_path(60_000, [300_000] * 10 + [60_000] * 10), t0)                    # -80 %, dev sells
        series("CRASH", cp_path(60_000, [500_000] * 10 + [4_000] * 10), t0)                  # -99 %, SOL -91 %: 90 / 90
        series("DIP", cp_path(60_000, [100_000] * 10 + [70_000] * 10), t0)                    # -30 %: nothing
        series(X, cp_path(80_000, [151_800] * 4 + [600_000] * 8 + [90_000] * 8 + [387_000] * 6), t0, sym="X")
        cols = "(token, symbol, first_ts, last_ts, archived_ts, kind, reason, peak_mcap, last_mcap, peak_liq, last_liq, pad)"
        a1 = cp_path(70_000, [100_000, 500_000, 500_000, 60_000, 60_000])
        con.execute(f"INSERT INTO rug_archive {cols} VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("ARCH1", "AONE", t0, NOW - 50 * H, NOW - 48 * H, "srusen", "srušio se 88% od vrha", 500_000, 60_000,
                     a1[1][1], a1[-1][1], 0.88))
        for i, (m, liq) in enumerate(a1):
            con.execute("INSERT INTO hype_snapshots VALUES (?,?,?,?,?)", ("ARCH1", t0 + i * 1800, m / 1e9, m, liq))
        con.execute(f"INSERT INTO rug_archive {cols} VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("ARCH2", "ATWO", t0, t0, NOW - 24 * H, "mehanika", "aktivan mint authority", None, None, None, None, None))
        con.execute(f"INSERT INTO rug_archive {cols} VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("ARCH3", "ATRI", t0, t0, NOW - 10 * 86400, "srusen", "x", 500_000, 60_000, 50_000, 10_000, 0.88))
        con.execute("INSERT INTO rug_relabel_runs VALUES ('pool_v1', ?, '{}')", (NOW - 3600,))   # PR #140 already ran
        con.commit()
        con.close()
        self.paper = os.path.join(d, "paper.db")
        from paper import store as pstore
        pc = pstore.connect(self.paper)
        pc.execute("INSERT OR REPLACE INTO candidates (token, symbol, first_ts, decision, reason) VALUES (?,?,?,?,?)",
                   ("DUMP", "DUMP", t0, "skip_rug", "rugan: srušio se 85% od vrha ($600.0k → $90.0k), likvidnost 61% manja"))
        pc.commit()
        pc.close()
        self.ev = lambda t: DEV if t == "DEV" else None
        archive.forget_cache()

    def tearDown(self):
        archive.forget_cache()
        self.tmp.cleanup()

    def counts(self):
        c = sqlite3.connect(self.db)
        out = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for (t,) in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'rug_relabel%'").fetchall()}
        c.close()
        return out

    def test_retro_counts_sample_x_and_once(self):
        before = self.counts()
        logs = []
        s = relabel.retro_once(self.db, NOW, log=logs.append, paper_db=self.paper, evidence_fn=self.ev)
        self.assertEqual(self.counts(), before)                                   # no row deleted or added elsewhere
        self.assertEqual(s["n"], 9)                                               # DUMP 1-4, PULL, DEV, CRASH, X, ARCH1
        self.assertEqual((s["rug_dump"], s["dump_rug"], s["rug_rug"]), (6, 0, 3))
        self.assertEqual({i["token"] for i in s["list_rug_dump"]}, {"DUMP", "DUMP2", "DUMP3", "DUMP4", X, "ARCH1"})
        self.assertEqual(len(s["sample"]), 5)
        self.assertTrue({i["token"] for i in s["sample"]} <= {i["token"] for i in s["list_rug_dump"]})
        self.assertEqual((s["src_archive"], s["mehanika"], s["paper"], s["paper_now_dump"]), (1, 1, 1, 1))
        self.assertEqual((s["x"]["usd"], s["x"]["sol_v2"]), ("rug", "dump"))
        self.assertEqual(s["strict_rug"], s["n"])                                  # every one blocks until the switch
        txt = "\n".join(logs)
        self.assertTrue(logs[0].startswith("rug pravilo (višak SOL-a, sol_v2) 7 dana: "))
        self.assertIn("rug→dump 6, dump→rug 0, ostaje rug 3", logs[0])
        self.assertIn("5 nasumičnih od 6 koji ostaju rug→dump:", txt)
        sample = [ln for ln in logs if ln.startswith("rug pravilo |   ")]
        self.assertEqual(len(sample), 5)
        for ln in sample:
            for part in ("cijena od vrha -", "od prve snimke", "SOL strana", " → ", "stvarni / očekivani",
                         "procjena iz USD likvidnosti",
                         "dump jer: stvarni / očekivani SOL omjer"):
                self.assertIn(part, ln)
        self.assertIn("X CccS…y1eU: staro (usd) rug", txt)
        self.assertIn("Ništa nije obrisano", txt)
        self.assertTrue(all(ln.startswith("rug pravilo") for ln in logs))
        c = sqlite3.connect(self.db)
        rows = {t: (o, l1, n, why) for t, o, l1, n, why in
                c.execute("SELECT token, old_kind, l_kind, new_kind, why FROM rug_relabel_sol")}
        c.close()
        self.assertEqual(rows["DUMP"][:3], ("rug", "dump", "dump"))
        self.assertEqual(rows["PULL"][2:], ("rug", "višak"))
        self.assertEqual(rows["DEV"][2:], ("rug", "dokaz"))
        self.assertEqual(rows["CRASH"][2:], ("rug", "90/90"))
        self.assertNotIn("DIP", rows)
        self.assertNotIn("ARCH3", rows)
        with mock.patch.object(labels, "v2_ok", lambda: True):
            archive.forget_cache()
            self.assertEqual(archive.kinds(self.db, ttl=0, log=lambda m: None)["ARCH1"], "dump")
        with mock.patch.object(labels, "v2_ok", lambda: False):
            archive.forget_cache()
            self.assertEqual(archive.kinds(self.db, ttl=0, log=lambda m: None)["ARCH1"], "rug")   # stricter until then
        logs2 = []
        self.assertIsNone(relabel.retro_once(self.db, NOW + 60, log=logs2.append, paper_db=self.paper))   # once
        self.assertEqual(logs2, [])

    def test_budget_marks_it_partial(self):
        s = relabel.retro(self.db, NOW, paper_db=self.paper, evidence_fn=self.ev, budget_s=0)
        self.assertTrue(s["partial"])
        self.assertIn("DJELOMIČNO", relabel.lines(s)[0])


class ArchiveRun(unittest.TestCase):
    def test_new_archives_get_the_versions_before_the_purge(self):
        from hype import store as hstore
        from tiers import store as tstore
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = tmp.name
        db = os.path.join(d, "hype.db")
        con = hstore.connect(db)
        tstore.connect(db).close()
        old = NOW - 30 * H
        for tok, path in (("CPDUMP", cp_path(80_000, [200_000] * 30 + [600_000] * 30 + [60_000] * 60)),
                          ("PULLED", [(200_000, 60_000)] * 60 + [(50_000, 5_000)] * 60)):
            con.execute("INSERT INTO token_tier (token, symbol, first_ts, last_ts, t0, klasa) VALUES (?,?,?,?,?,?)",
                        (tok, tok, old, old + len(path) * 120, "prolaz", "moonshot"))
            for i, (m, liq) in enumerate(path):
                ts = old + i * 120
                con.execute("INSERT INTO hype_signals (ts, token, symbol, score, price, mcap, liquidity, features) "
                            "VALUES (?,?,?,?,?,?,?,?)", (ts, tok, tok, 50, m / 1e9, m, liq, json.dumps({})))
                con.execute("INSERT INTO hype_snapshots VALUES (?,?,?,?,?)", (tok, ts, m / 1e9, m, liq))
        con.commit()
        con.close()
        root = archive.ROOT
        archive.ROOT = d
        try:
            with mock.patch.object(collapse, "rug_evidence", lambda t: None):
                archive.run(db, now=NOW, log=None)
                archive.run(db, now=NOW + archive.CONFIRM_H * H + 60, log=None)
            c = sqlite3.connect(db)
            rows = {t: (o, n) for t, o, n in c.execute("SELECT token, old_kind, new_kind FROM rug_relabel_sol "
                                                       "WHERE src='archive'")}
            c.close()
            self.assertEqual(rows, {"CPDUMP": ("rug", "dump"), "PULLED": ("rug", "rug")})
            with mock.patch.object(labels, "v2_ok", lambda: True):
                archive.forget_cache()
                k = archive.kinds(db, ttl=0, log=lambda m: None)
                self.assertEqual((k["CPDUMP"], k["PULLED"]), ("dump", "rug"))
        finally:
            archive.ROOT = root
            archive.forget_cache()


if __name__ == "__main__":
    unittest.main()
