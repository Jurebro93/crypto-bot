"""Rug by the pool's liquidity (11.11. evening, Jure: "mjeri pad likvidnosti na SOL (quote) strani poola, ne u USD"):
the constant-product math, the dev-selling branch, the non-CP fallback, the SOL columns of the pulse, and the
retroactive relabel of the last 7 days (counts, X, the log block, nothing deleted)."""
import json
import math
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rugfilter import archive, collapse, relabel  # noqa: E402

NOW = 1794400000
H = 3600
X = "CccS" + "7hJ2kQwPz9mNvB4rT6yXa3LdF8sGcE1u" + "y1eU"
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

    def pair(self, dex="pumpswap", labels=None, addr="POOL1", quote="SOL"):
        q = {"address": collapse.SOL_MINT, "symbol": "SOL"} if quote == "SOL" else {"address": "USDC", "symbol": "USDC"}
        return {"dexId": dex, "labels": labels or [], "pairAddress": addr, "quoteToken": q,
                "priceNative": str(self.price()) if quote == "SOL" else str(self.price() * self.S),
                "priceUsd": str(self.price() * self.S), "marketCap": self.mcap(),
                "liquidity": {"usd": self.liq_usd(), "base": self.x, "quote": self.y if quote == "SOL" else self.y * self.S}}


def fold(acc, tok, ts, pool, **kw):
    pp = collapse.pair_pool(pool.pair(**kw))
    return collapse.add(acc, tok, ts, pool.mcap(), pool.liq_usd(), pp["liq_sol"], pp["price_native"], pp["pool"], pp["dex"])


class CpMath(unittest.TestCase):
    def test_numbers_behind_the_rule(self):
        p = Pool()
        y0, L0, p0 = p.y, p.L(), p.price()
        p.trade_to(0.15)                                                     # an organic -85 % dump
        self.assertAlmostEqual(p.y / y0, math.sqrt(0.15), places=6)          # SOL side 0.387 of its peak: -61 %
        self.assertAlmostEqual(p.L() / L0, 1.0, places=9)                    # L unchanged
        self.assertAlmostEqual((p.y / math.sqrt(p.price())) / (y0 / math.sqrt(p0)), 1.0, places=9)   # y / sqrt(p) = L
        q = Pool().pull(0.6)                                                 # LP pull of 60 %
        self.assertAlmostEqual(q.L() / L0, 0.4, places=9)
        self.assertAlmostEqual(q.price() / p0, 1.0, places=9)

    def test_dump_85_is_a_dump_lp_pull_60_is_a_rug(self):
        acc, p = {}, Pool()
        fold(acc, "D", NOW - 3600, p)
        fold(acc, "D", NOW, p.trade_to(0.15))
        j = collapse.assess_pool(acc["D"])
        self.assertEqual(j["kind"], "dump")
        self.assertEqual(j["basis"], "sol")                                  # the stored SOL side, same pool
        self.assertAlmostEqual(j["l_drop"], 0.0, places=3)
        self.assertAlmostEqual(j["sol_drop"], 1 - math.sqrt(0.15), places=3)  # -61 %
        self.assertEqual(j["sol_rule"], "rug")                               # the literal "SOL side -50 %" would say rug
        self.assertIn("pool drži", j["text"])
        self.assertEqual(collapse.check(acc["D"])["strict"], "old")           # 11.11. hotfix: the stricter label blocks
        acc, p = {}, Pool()
        fold(acc, "R", NOW - 3600, p)
        fold(acc, "R", NOW, p.pull(0.6))
        j = collapse.assess_pool(acc["R"])
        self.assertEqual(j["kind"], "rug")                                   # L -60 %, the price did not move
        self.assertAlmostEqual(j["l_drop"], 0.6, places=3)
        self.assertEqual(j["drop"], 0.0)
        self.assertIn("izvučena likvidnost: pool (L) 60% manji", j["text"])
        self.assertTrue(collapse.check(acc["R"]))

    def test_same_rule_from_usd_numbers_and_from_peaks_only(self):
        p = Pool()
        m0, l0 = p.mcap(), p.liq_usd()
        p.trade_to(0.15)
        self.assertEqual(collapse.judge(m0, p.mcap(), l0, p.liq_usd())["kind"], "dump")   # judge without a series
        acc = {}
        collapse.add(acc, "U", NOW - 3600, m0, l0)                           # hype_signals: USD only
        collapse.add(acc, "U", NOW, p.mcap(), p.liq_usd())
        j = collapse.assess_pool(acc["U"])
        self.assertEqual((j["kind"], j["basis"]), ("dump", "usd"))
        self.assertAlmostEqual(j["l_drop"], 0.0, places=6)
        q = Pool()
        m0, l0 = q.mcap(), q.liq_usd()
        q.pull(0.6).trade_to(0.5)                                             # pulled, then sold into the thin pool
        self.assertEqual(collapse.judge(m0, q.mcap(), l0, q.liq_usd())["kind"], "rug")
        acc = {}
        collapse.add(acc, "U", NOW - 3600, m0, l0)
        self.assertEqual(collapse.assess_pool(acc["U"], q.mcap(), q.liq_usd())["kind"], "rug")   # live numbers folded in

    def test_dev_selling_and_a_75_crash_is_a_rug(self):
        acc, p = {}, Pool()
        fold(acc, "E", NOW - 3600, p)
        fold(acc, "E", NOW, p.trade_to(0.25))
        self.assertEqual(collapse.assess_pool(acc["E"])["kind"], "dump")
        j = collapse.assess_pool(acc["E"], evidence=DEV)
        self.assertEqual(j["kind"], "rug")
        self.assertIn("dev prodaje", j["text"])
        with mock.patch.object(collapse, "rug_evidence", lambda t: DEV if t == "E" else None):
            self.assertEqual(collapse.check(acc["E"], token="E")["kind"], "rug")
            self.assertIsNone(collapse.check(acc["E"], token="other"))

    def test_a_pool_switch_is_not_a_pull(self):
        acc, big, small = {}, Pool(sol=400, tokens=2e9), Pool(sol=40, tokens=2e8)   # same price, a tenth of the pool
        fold(acc, "S", NOW - 3600, big, addr="BIG")
        fold(acc, "S", NOW, small, addr="SMALL")                              # DexScreener now shows another pool
        self.assertIsNone(collapse.assess_pool(acc["S"]))                          # only the newest pool is compared
        self.assertEqual(collapse.judge(big.mcap(), small.mcap(), big.liq_usd(), small.liq_usd())["kind"], "rug")
        # (the peak / now numbers alone cannot tell a switch from a pull: why the pool address is stored)


class NonCp(unittest.TestCase):
    def test_is_cp(self):
        for dex, want in (("pumpswap", True), ("raydium", True), ("raydium/CPMM", True), ("meteora/DYN", True),
                          ("raydium/CLMM", False), ("meteora/DLMM", False), ("orca/wp", False), ("meteora/DYN2", False),
                          ("pumpfun", False), (None, None), ("somedex", None)):
            self.assertEqual(collapse.is_cp(dex), want, dex)

    def test_clmm_falls_back_to_the_sol_side(self):
        def row(sol0, sol1, ratio):
            acc = {}
            for ts, sol, px in ((NOW - 3600, sol0, 1e-6), (NOW, sol1, 1e-6 * ratio)):
                collapse.add(acc, "C", ts, px * 150 * 1e9, sol * 2 * 150, sol, px, "CL1", "raydium/CLMM")
            return acc["C"]
        j = collapse.assess_pool(row(100, 40, 0.4))                               # SOL side -60 %, price -60 %
        self.assertEqual((j["kind"], j["cp"]), ("rug", False))
        self.assertIn("ne-CP pool raydium/CLMM", j["text"])
        j = collapse.assess_pool(row(100, 55, 0.25))                              # SOL side -45 %, price -75 %
        self.assertEqual(j["kind"], "dump")
        self.assertIn("ne-CP pool", j["text"])
        self.assertIsNone(collapse.assess_pool(row(100, 40, 0.8)))                # SOL side -60 % on a -20 % dip: nothing

    def test_pair_pool(self):
        p = Pool()
        pp = collapse.pair_pool(p.pair(labels=["CPMM"], dex="raydium"))
        self.assertAlmostEqual(pp["liq_sol"], p.y)
        self.assertAlmostEqual(pp["price_native"], p.price())
        self.assertEqual((pp["pool"], pp["dex"]), ("POOL1", "raydium/CPMM"))
        usdc = p.pair(quote="USDC")
        self.assertIsNone(collapse.pair_pool(usdc)["liq_sol"])                # no SOL price: unknown
        pp = collapse.pair_pool(usdc, sol_usd=150.0)
        self.assertAlmostEqual(pp["liq_sol"], p.liq_usd() / 2 / 150)
        self.assertAlmostEqual(pp["price_native"], p.price())

    def test_sol_usd_by_day(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = tmp.name
        db = os.path.join(d, "market.db")
        c = sqlite3.connect(db)
        c.execute("CREATE TABLE price (day INTEGER PRIMARY KEY, usd REAL)")
        day = NOW // 86400 * 86400
        c.executemany("INSERT INTO price VALUES (?,?)", [(day - 86400, 160.0), (day, 150.0)])
        c.commit()
        c.close()
        with mock.patch.object(collapse, "MARKET_DB", db):
            collapse._SOL_DAYS["ts"] = 0.0
            self.assertEqual(collapse.sol_usd_at(NOW), 150.0)
            self.assertEqual(collapse.sol_usd_at(NOW - 86400), 160.0)
            self.assertEqual(collapse.sol_usd_at(NOW + 5 * 86400), 150.0)     # nearest known day
        collapse._SOL_DAYS["ts"] = 0.0


class PulseColumns(unittest.TestCase):
    def test_old_table_gets_the_columns_and_rows_carry_the_sol_side(self):
        from hype import pulse
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = tmp.name
        db = os.path.join(d, "hype.db")
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE token_pulse (token TEXT, ts INTEGER, price REAL, mcap REAL, liquidity REAL, vol_m5 REAL, "
                    "vol_h1 REAL, buys_m5 INTEGER, sells_m5 INTEGER, buys_h1 INTEGER, sells_h1 INTEGER, holders INTEGER, "
                    "holders_src TEXT, PRIMARY KEY (token, ts))")
        con.execute("INSERT INTO token_pulse (token, ts, mcap, liquidity) VALUES ('OLD', 1, 5, 5)")
        con.execute("CREATE TABLE hype_signals (ts INTEGER, token TEXT, mcap REAL, liquidity REAL)")
        pulse.ensure(con)
        cols = [r[1] for r in con.execute("PRAGMA table_info(token_pulse)")]
        self.assertEqual(cols[-4:], ["liq_sol", "price_native", "pool", "dex"])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM token_pulse").fetchone()[0], 1)
        p = Pool()
        pulse.record(con, "T", p.pair(), NOW - 3600)
        pulse.record(con, "T", p.trade_to(0.15).pair(), NOW)
        con.commit()
        r = con.execute("SELECT liq_sol, price_native, pool, dex FROM token_pulse WHERE token='T' ORDER BY ts").fetchall()
        self.assertAlmostEqual(r[0][0], 85.0)
        self.assertEqual(r[1][2:], ("POOL1", "pumpswap"))
        con.close()
        j = collapse.assess_pool(collapse.peaks(db, ["T"], now=NOW)["T"])
        self.assertEqual((j["kind"], j["basis"]), ("dump", "sol"))
        self.assertAlmostEqual(j["sol_drop"], 0.613, places=3)

    def test_sol_price_of_the_scan(self):
        from hype import pulse
        rows = [{"raw": Pool(sol_usd=s).pair()} for s in (140.0, 150.0, 160.0)] + [{"raw": Pool().pair(quote="USDC")}]
        self.assertAlmostEqual(pulse.sol_price(rows), 150.0)
        self.assertIsNone(pulse.sol_price([]))


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
                        (tok, sym or tok[:4], start, start + step * len(path)))
            for i, (m, liq) in enumerate(path):
                con.execute("INSERT INTO hype_signals (ts, token, symbol, score, price, mcap, liquidity, features) "
                            "VALUES (?,?,?,?,?,?,?,?)", (start + i * step, tok, sym, 50, m / 1e9, m, liq, "{}"))

        t0 = NOW - 72 * H
        up = [100_000 + 50_000 * i for i in range(11)]                       # 100k -> 600k in 10 h
        series("DUMP", cp_path(80_000, up + [600_000] * 15 + [90_000] * 20), t0)               # -85 %, L held
        series("PULL", [(200_000, 40_000)] * 20 + [(200_000, 12_000)] * 2 + [(100_000, 8_485)] * 10, t0)  # LP -70 %
        series("DEV", cp_path(60_000, [300_000] * 10 + [60_000] * 10), t0)                      # -80 %, dev sells
        series("DIP", cp_path(60_000, [100_000] * 10 + [70_000] * 10), t0)                       # -30 %: nothing
        series(X, cp_path(80_000, [151_800] * 4 + [600_000] * 8 + [90_000] * 8 + [387_000] * 6), t0, sym="X")
        # the archive: A1 a CP dump archived 2 days ago (kept snapshots), A2 rug mechanics, A3 outside the window
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
        con.commit()
        con.close()
        self.paper = os.path.join(d, "paper.db")
        from paper import store as pstore
        pc = pstore.connect(self.paper) if hasattr(pstore, "connect") else sqlite3.connect(self.paper)
        pc.executescript(pstore.SCHEMA) if hasattr(pstore, "SCHEMA") else None
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

    def test_retro_counts_x_and_the_log_block(self):
        before = self.counts()
        logs = []
        s = relabel.retro_once(self.db, NOW, log=logs.append, paper_db=self.paper, evidence_fn=self.ev)
        self.assertEqual(self.counts(), before)                                  # no row deleted or added elsewhere
        self.assertEqual(s["n"], 5)                                              # DUMP, PULL, DEV, X, ARCH1
        self.assertEqual((s["rug_dump"], s["dump_rug"], s["rug_rug"]), (3, 0, 2))
        self.assertEqual((s["sol_rug"], s["sol_rug_pool_dump"]), (5, 3))          # the literal rule: all five rugs
        self.assertEqual((s["src_archive"], s["src_collapse"], s["mehanika"]), (1, 4, 1))
        self.assertEqual((s["paper"], s["paper_now_dump"]), (1, 1))
        self.assertEqual({i["token"] for i in s["list_rug_dump"]}, {"DUMP", X, "ARCH1"})
        self.assertEqual((s["x"]["old"], s["x"]["new"], s["x"]["sol"]), ("rug", "dump", "rug"))
        self.assertTrue(logs[0].startswith("rug pravilo (pool invariant) 7 dana: 5 tokena, rug→dump 3, dump→rug 0, "
                                           "ostaje rug 2"))
        self.assertIn("po SOL strani bi bilo: rug 5", logs[0])
        txt = "\n".join(logs)
        self.assertIn("X CccS…y1eU: staro rug → novo dump (po SOL strani rug)", txt)
        self.assertIn("rug→dump (3 od 3)", txt)
        self.assertIn("Ništa nije obrisano", txt)
        self.assertTrue(all(ln.startswith("rug pravilo") for ln in logs))
        c = sqlite3.connect(self.db)
        rows = dict(c.execute("SELECT token, old_kind || '>' || new_kind FROM rug_relabel"))
        c.close()
        self.assertEqual(rows["DUMP"], "rug>dump")
        self.assertEqual(rows["PULL"], "rug>rug")
        self.assertEqual(rows["DEV"], "rug>rug")
        self.assertEqual(rows["ARCH1"], "rug>dump")
        self.assertNotIn("DIP", rows)
        self.assertNotIn("ARCH3", rows)                                          # archived 10 days ago
        k = archive.kinds(self.db, ttl=0, log=lambda m: None)                    # 11.11. hotfix: the stricter label
        self.assertEqual((k["ARCH1"], k["ARCH2"], k["ARCH3"]), ("rug", "rug", "rug"))   # nothing is unblocked
        logs2 = []
        self.assertIsNone(relabel.retro_once(self.db, NOW + 60, log=logs2.append, paper_db=self.paper))   # once
        self.assertEqual(logs2, [])

    def test_x_missing_is_said(self):
        s = relabel.retro(self.db, NOW, paper_db=self.paper, evidence_fn=self.ev)
        s["x"] = None
        self.assertIn("nije pronađen", "\n".join(relabel.lines(s)))

    def test_budget_marks_it_partial(self):
        s = relabel.retro(self.db, NOW, paper_db=self.paper, evidence_fn=self.ev, budget_s=0)
        self.assertTrue(s["partial"])
        self.assertIn("DJELOMIČNO", relabel.lines(s)[0])


class ArchiveRun(unittest.TestCase):
    def test_new_archives_get_the_pool_label_before_the_purge(self):
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
            rows = dict(c.execute("SELECT token, old_kind || '>' || new_kind FROM rug_relabel WHERE src='archive'"))
            c.close()
            self.assertEqual(rows, {"CPDUMP": "rug>dump", "PULLED": "rug>rug"})
            archive.forget_cache()
            k = archive.kinds(db, ttl=0, log=lambda m: None)
            self.assertEqual((k["CPDUMP"], k["PULLED"]), ("rug", "rug"))      # 11.11. hotfix: the stricter label blocks
            self.assertEqual(archive.kind_one("CPDUMP", db), "rug")
        finally:
            archive.ROOT = root
            archive.forget_cache()

    def test_kind_of_without_a_relabel(self):
        self.assertEqual(archive.kind_new("srusen", 50_000, 50_000 * math.sqrt(0.12), 500_000, 60_000), "dump")
        self.assertEqual(archive.kind_of("srusen", 50_000, 5_000, 500_000, 60_000), "rug")     # L -71 %
        self.assertEqual(archive.kind_of("srusen", 60_000, 10_000), "rug")                       # no market caps
        self.assertEqual(archive.kind_new("srusen", 50_000, 5_000, 500_000, 60_000, "dump"), "dump")   # relabel wins
        self.assertEqual(archive.kind_of("srusen", 50_000, 5_000, 500_000, 60_000, "dump"), "rug")    # hotfix: stricter
        self.assertEqual(archive.kind_of("mehanika", None, None, None, None, "dump"), "rug")
        self.assertEqual(archive.kind_usd("srusen", 50_000, 50_000 * math.sqrt(0.12)), "rug")   # the noon rule


if __name__ == "__main__":
    unittest.main()
