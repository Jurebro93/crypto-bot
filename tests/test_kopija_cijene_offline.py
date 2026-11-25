"""25.11. (vlasnik, jutarnji izvještaj, slika: „Kopiranje dokazanih novčanika: koliko bismo zaradili mi" — „Prvih 20 po
ocjeni: n=1825, prosjek +48693144406.11 %, interval +4766.5 do +144102436974.0 %, zbroj +88864988541.15 SOL"),
offline, synthetic wallets and prices only:

  - the cause reproduced: one swap print whose price is not a price (a dust amount of tokens next to a real SOL amount,
    wallets/rpc.parse) lands exactly where the copier exits; counted the way it was before (kopija.portfolio legacy)
    the row is +10^9 % a trade, as in the report; now that trade is dropped and counted, the row is the honest one
  - the rules judge the price, not the result: an isolated print (both sides disagree), a market cap no token ever had
    (another unit / pool), our entry 50x away from his fill, a price <= 0; a real gradual +800 % is kept
  - the pool caps the exit (never more than its whole SOL side), marked
  - the median next to the average; the log's diagnostic line (symbol, prices, sources, liquidity, never a wallet)
  - the demo exit the demo copies read stays the pre-check pick; the clean pick is reported next to it
  - the report and /strategije never print an impossible row (also for a result stored before this fix): „sumnjivi
    podaci, red izostavljen (n tradeova)"; the verdict never rests on such a row

    python3 -m unittest tests.test_kopija_cijene_offline
"""
import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from report import razumno, render  # noqa: E402
from tests.test_wallets_kopija_offline import MM, NOW, Base  # noqa: E402
from wallets import kopija  # noqa: E402

D = 86400


def ser(pts, src=kopija.S_TRADE):
    return kopija.Series([(t, p, src) for t, p in pts])


def tok(pts, liq=(), supply=None, kind="sol"):
    s = ser(pts)
    return {"sol": s if kind == "sol" else kopija.Series(), "usd": s if kind == "usd" else kopija.Series(),
            "liq": sorted(liq), "supply": supply}


class Rules(unittest.TestCase):
    EP = {"mint": "M", "t0": 1000, "px0": 1e-6, "sell_ts": 5000, "sell_px": 2e-6, "ret": 1.0}

    def trade(self, pts, ep=None, **k):
        return kopija.copy_trade("W", ep or self.EP, 60, "on", tok(pts, **k), 150.0, fee=0.01, hi=10 ** 6)

    def test_an_isolated_print_at_the_exit_is_dropped_not_clipped(self):
        pts = [(1060, 1.1e-6), (2000, 1.2e-6), (3000, 1.3e-6), (4000, 1.4e-6), (5060, 500.0),   # a dust swap's "price"
               (5075, 1.5e-6), (5090, 1.5e-6), (5105, 1.4e-6)]
        t = self.trade(pts)
        self.assertIn("izlaz: ispis", t["sumnja"])
        self.assertIsNone(t["ret"])                                       # in no number
        self.assertGreater(t["ret0"], 1e8)                                # what the copier counted before 25.11.
        trs, why = kopija.portfolio([(self.EP, t)])
        self.assertEqual((trs, why["sumnjiva_cijena"], why["kopirano"]), ([], 1, 0))

    def test_a_real_gradual_pump_of_800_percent_is_kept(self):
        pts = [(1060, 1e-6)] + [(1060 + 300 * k, 1e-6 * (1 + 0.6 * k)) for k in range(1, 14)] + [(5060, 9e-6)]
        t = self.trade(pts, liq=[(1000, 500_000.0)])
        self.assertIsNone(t["sumnja"])
        self.assertAlmostEqual(t["gross"], 8.0, places=6)                 # +800 %: big is not a reason
        self.assertFalse(t["cap"])

    def test_a_jump_that_one_side_confirms_is_a_real_move(self):
        pts = [(1060, 1e-6), (1100, 1e-6), (1200, 1e-6), (3000, 2e-5), (4000, 2.1e-5), (5060, 2.2e-5)]
        t = self.trade(pts, liq=[(1000, 5_000_000.0)])
        self.assertIsNone(t["sumnja"])                                    # 20x, then it stays there
        self.assertAlmostEqual(t["gross"], 21.0, places=6)

    def test_a_market_cap_no_token_ever_had_is_another_unit(self):
        # USD series: the snapshots price the token (~1e-5 $), the exit lands on a GeckoTerminal candle of a pool whose
        # base token is SOL (~150 $): 150 $ x 1e9 tokens = 150 bn $
        mixed = [(1060, 1e-5), (2000, 1.1e-5), (5060, 150.0), (5900, 151.0), (6800, 149.0)]
        self.assertTrue(self.trade(mixed, supply=1e9, kind="usd")["sumnja"])   # dropped whichever print is blamed
        # a token whose whole series is such candles: every print agrees with its neighbours, the unit does not
        only = [(1060, 150.0), (2000, 151.0), (5060, 149.0)]
        t = self.trade(only, ep=dict(self.EP, px0=None), supply=1e9, kind="usd")
        self.assertIn("tržišna vrijednost", t["sumnja"])

    def test_our_entry_fifty_times_from_his_fill_and_a_price_at_zero(self):
        t = self.trade([(1060, 1e-3), (5060, 1.2e-3)])                    # his fill 1e-6, ours 60 s later 1e-3
        self.assertIn("od njegove cijene", t["sumnja"])
        self.assertIn("≤ 0", kopija.isolated([0.0, 1.0], 0))

    def test_the_pool_caps_the_exit_and_says_so(self):
        pts = [(1060, 1e-6)] + [(1060 + 300 * k, 1e-6 * 1.5 ** k) for k in range(1, 14)]
        pts.append((5060, pts[-1][1]))
        t = self.trade(pts, liq=[(1000, 2_000.0), (5060, 2_000.0)])
        top = 2_000.0 / 2 / (0.1 * 150.0) - 1                             # never more than the pool's SOL side
        self.assertTrue(t["cap"])
        self.assertAlmostEqual(t["gross"], top)
        self.assertAlmostEqual(t["ret"], top - t["cost"])
        self.assertGreater(t["ret0"], t["ret"])

    def test_the_median_is_next_to_the_average(self):
        trs = [{"ret": r, "token": f"T{i}", "ts": i * D, "out_ts": i * D + 60, "wallet": "W", "open": False,
                "stale": False, "why": "prodao"} for i, r in enumerate([0.1] * 20 + [-0.1] * 9 + [5.0])]
        b = kopija.brief(trs)
        self.assertAlmostEqual(b["med_pct"], 10.0)
        self.assertGreater(b["ev_pct"], b["med_pct"])


class Reproduced(Base):
    """The report's +48693144406 % on the synthetic market: the measured part's exits get a dust swap print."""

    def inject(self, k=6):
        split = NOW - 12 * D
        rows = self.w.con.execute(f"SELECT ts, mint FROM wallet_trades WHERE kind='sell' AND wallet IN "
                                  f"({','.join('?' * len(self.good))}) AND ts >= ? ORDER BY ts LIMIT ?",
                                  (*self.good, split, k)).fetchall()
        # 0.001 tokens for 0.5 SOL (a fee / rent leg booked as a "sale" of a dust amount): 500 SOL a token
        self.w.con.executemany("INSERT INTO wallet_trades VALUES (?,?,?,?,?,?,?)",
                               [(MM, f"dust{i}", ts + 60, m, -1e-3, 0.5, "sell") for i, (ts, m) in enumerate(rows)])
        self.w.con.commit()
        return len(rows)

    def test_before_the_fix_10_to_the_9_percent_after_it_the_honest_row(self):
        clean = self.run_()
        n = self.inject()
        self.lines = []
        res = self.run_()
        old = {x["exit"]: x for x in res["prije_provjere"]}
        self.assertGreater(old["on"]["ev_pct"], 1e8)                     # +10^8..10^9 % a trade, as in the report
        self.assertIsNotNone(razumno.sumnja({"n": old["on"]["n"], "ev_pct": old["on"]["ev_pct"]}))
        r, r0 = kopija.row_of(res, "app", 60, "on"), kopija.row_of(clean, "app", 60, "on")
        self.assertEqual(r["razlozi"]["sumnjiva_cijena"], n)              # dropped and COUNTED
        self.assertEqual(r["n"], r0["n"] - n)
        self.assertLess(abs(r["ev_pct"] - r0["ev_pct"]), 5)              # the clean trades' average, as without them
        self.assertIsNone(razumno.sumnja(r))
        self.assertIn("med_pct", r)
        self.assertIn(f"izbačeno {n} tradeova zbog sumnjive cijene", res["verdict"])
        # the log: the diagnosis before the headline, the dropped trades with their prices and sources, no wallet
        diag = next(x for x in self.lines if x.startswith("novčanici kopija dijagnostika: "))
        self.assertIn(f"[app/60/on: izbačeno {n} zbog sumnjive cijene", diag)
        self.assertIn("IZBAČEN", diag)
        self.assertIn("(trgovina)", diag)
        self.assertNotIn(MM, diag)
        for w in self.good + [self.fade, self.late]:
            self.assertNotIn(w, diag)
            self.assertNotIn(w[:8], diag)
        self.assertIn("izbačeno", self.lines[-1])
        # the table: no impossible row; the dropped count and the median shown
        s = kopija.summary(res, NOW)
        self.assertFalse([x for x in s["redovi"] if x.get("sumnja")])
        ex = next(x for x in s["redovi"] if x["naziv"] == "Isto, izlaz: njegov izlaz")
        self.assertEqual(ex["izbaceno"], n)
        self.assertIsNotNone(ex["medijan_pct"])

    def test_the_demo_exit_is_picked_on_clean_rows(self):
        """Vlasnik 25.11. ("Demo izlaz čisti"): the demo copies read the pick made after the price check."""
        self.inject()
        res = self.run_()
        self.assertGreater(max(x["ev_pct"] for x in res["prije_provjere"]), 1e8)   # the old pick saw broken numbers
        self.assertEqual(res["demo_exit"], kopija.demo_exit(res["grid"]))          # what kopija_demo reads: clean
        self.assertEqual(res["demo_exit_cisti"], res["demo_exit"])
        self.assertEqual(res["demo_exit_staro"], kopija.demo_exit(res["prije_provjere"]))
        # when the old pick differs, the report says which exit the demo uses and what it would have been
        res["demo_exit"], res["demo_exit_staro"] = "on_stop_24h", "on"
        s = kopija.summary(res, NOW)
        self.assertTrue(any("očišćenim" in x and "njegov izlaz, stop" in x for x in s["napomene"]))


def stored_broken():
    """A result as stored before 25.11. with the report's numbers in the „Prvih 20 po ocjeni" row."""
    t = Base("run_")
    t.setUp()
    try:
        res = t.run_()
    finally:
        t.doCleanups()
    res = copy.deepcopy(res)
    for x in res["grid"]:
        x.pop("ograniceno", None)
        (x.get("razlozi") or {}).pop("sumnjiva_cijena", None)
        if (x["rule"], x["delay"], x["exit"]) == ("top", 60, "on_stop"):
            x.update(n=1825, ev_pct=48693144406.11, ci90=[4766.5, 144102436974.0], hit=0.37, sum_sol=88864988541.15,
                     med_pct=None)
    return res


class Display(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = stored_broken()

    def test_report_table_omits_the_impossible_row_and_the_verdict_ignores_it(self):
        s = kopija.summary(self.res, NOW)
        top = next(x for x in s["redovi"] if x["naziv"] == kopija.RULE_HR["top"])
        self.assertIn("prosjek", top["sumnja"])
        html = render.kopija_block(dict(s, demo=None))
        self.assertIn("sumnjivi podaci, red izostavljen (1825 tradeova)", html)
        self.assertNotIn("48693144406", html)
        self.assertNotIn("88864988541", html)
        self.assertNotIn("144102436974", html)
        self.assertIn("medijan", html)
        good = kopija.verdict(self.res)
        self.assertNotIn("48693144406", s["presuda"])
        self.assertEqual(s["presuda"], good)
        self.assertTrue(any("nemoguće brojke" in x for x in s["napomene"]))

    def test_the_primary_row_broken_means_no_verdict(self):
        res = copy.deepcopy(self.res)
        kopija.row_of(res, *kopija.PRIMARY).update(ev_pct=1e6, ci90=[5.0, 1e7], sum_sol=1e5)
        v = kopija.verdict(res)
        self.assertIn("sumnjive podatke", v)
        self.assertNotIn("u plusu", v)

    def test_strategije_page_omits_it_too(self):
        from ui import strategije
        s = kopija.summary(self.res, NOW)
        from unittest import mock
        with mock.patch("report.midcap.kopija", return_value=dict(s, demo=None)):
            html = strategije.kopija_html(NOW)
        self.assertIn("sumnjivi podaci, red izostavljen (1825 tradeova)", html)
        self.assertNotIn("48693144406", html)
        self.assertIn("medijan", html)
        rows = strategije.midcap_rows_html([{"naziv": "X", "vrsta": "backtest", "n": 40, "ev_pct": 5e9, "ci": [1.0, 2e9],
                                             "ci_label": "90 %", "pogodak": 0.4}])
        self.assertIn("sumnjivi podaci", rows[0][2][0])

    def test_any_number_beyond_the_bounds_carries_the_mark(self):
        self.assertEqual(render.pp(12.345, 2), "+12.35 %")
        self.assertIn(razumno.MARK, render.pp(48693144406.11, 2))
        self.assertIn(razumno.MARK, render.sol(88864988541.15, 2))
        self.assertIn(razumno.MARK, render.ci_txt([4766.5, 144102436974.0]))
        self.assertEqual(render.sol(-0.14, 2), "-0.14 SOL")
        # the historical replay table (veliki/replay) goes through the same row guard
        html = render.replay_block({"presuda": "x", "redovi": [{"naziv": "Svi dani", "n": 50, "ev_pct": 3e4, "ci": [1, 2],
                                                               "pogodak": 0.5, "zbroj_sol": 1.0}], "ulog_sol": 0.1})
        self.assertIn("sumnjivi podaci, red izostavljen (50 tradeova)", html)

    def test_a_real_800_percent_row_is_not_hidden(self):
        self.assertIsNone(razumno.sumnja({"n": 40, "ev_pct": 800.0, "ci": [100.0, 950.0], "zbroj_sol": 32.0}))
        self.assertIsNotNone(razumno.sumnja({"n": 40, "ev_pct": 50.0, "zbroj_sol": 500.0}))   # 40 x 0.1 SOL cannot


if __name__ == "__main__":
    unittest.main()
