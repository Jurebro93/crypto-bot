"""16.11. (vlasnik: "Objasni mi kako ovdje postoji profitabilni wallet, a mi nemamo profitabilnu strategiju"; wallets/
kopija.py, wallets/kopija_demo.py), offline, synthetic wallets and prices only (no network, no real database):

  - the pure parts: the split, a wallet's positions (first buy, first sale, his own return), the copier's trade on a
    price series (entry `delay` later, his exit + delay, the stop at the print that crossed it, 24 h, still open at the
    end), "bez cijene" when no price is near, the cost never under 3 %, the account's cap and one position a token,
    the decomposition that adds up, the n < 30 rule
  - the selection never sees the measured part: trades after the split change nothing in select()
  - the whole pipeline on a synthetic market: the numbers are the ones computed by hand, after delay and cost
  - run(): bounded by its budget, never raises, no network, the result stored and kept; the report section, the
    strategies rows, /strategije; the CLI (--ako-nema, --night), the schedule and the midcap focus
  - the paid refresh is OFF by default and calls nothing
  - the demo copies: the demo account only (NEVER_LIVE), also under 5M MC without asking the real account's gate, the
    caps, his price / ours / the delay stored, the exit when he sells

    python3 -m unittest tests.test_wallets_kopija_offline
"""
import argparse
import io
import json
import os
import socket
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from wallets import dokazani, kopija, kopija_demo, rang, store as wstore  # noqa: E402
from tests.test_pravi_novac_sve_offline import LU, SwitchBase, tok  # noqa: E402
WU = "autopilot-novcanici"   # 19.11.: league/store.WALLET_DEMO_USER
from trade import settings  # noqa: E402

D, H = 86400, 3600
NOW = 1794821400 // H * H     # 16.11.2026 09:00 UTC
PX = 1e-6                     # SOL per token of every synthetic first buy
NOPATHS = {k: None for k in ("hype", "kol", "league", "market", "fast", "minute", "events", "early", "insajderi",
                             "range", "momentum", "midcap")}
MM = "Market" + "m" * 38      # a labelled bot: its swaps are prices, it is never selected


def wal(name):
    return (name + "w" * 44)[:44]


def mint(k):
    return f"Tok{k:05d}" + "x" * 32 + "pump"


class World:
    """A synthetic wallets.db: wallets that buy 1 SOL of a fresh token and sell it 2 h later at `mult` x their price,
    and a market wallet whose swaps print the price path around both: after his buy +0.1 % a second for 10 min, after
    his sale -0.05 % a second for 15 min."""

    def __init__(self, path):
        self.path, self.rows, self.k = path, [], 0
        self.con = wstore.connect(path)
        rang.ensure(self.con)
        dokazani.ensure(self.con)
        self.wallet(MM, labels='["bot"]')

    def wallet(self, w, labels="[]", first_scored=NOW - 35 * D):
        self.con.execute("DELETE FROM wallet_pnl WHERE wallet = ?", (w,))
        self.con.execute("INSERT OR REPLACE INTO wallets (wallet, first_seen, last_seen, scored_at, labels) "
                         "VALUES (?,?,?,?,?)", (w, NOW - 40 * D, NOW, NOW - D, labels))
        self.con.execute("INSERT OR REPLACE INTO wallet_pnl VALUES (?,?,0,0,0,0,0,0)", (w, first_scored))

    def tr(self, w, ts, m, tokens, sol, kind):
        self.rows.append((w, f"sig{len(self.rows)}", int(ts), m, tokens, sol, kind))

    def round(self, w, t0, mult=1.5, hold=2 * H, prints=True, sell=True, m=None):
        self.k += 1
        m = m or mint(self.k)
        self.tr(w, t0, m, 1e6, -1.0, "buy")
        if sell:
            self.tr(w, t0 + hold, m, -1e6, mult, "sell")
        if prints:
            for s in range(15, 615, 15):
                self.tr(MM, t0 + s, m, 1e5, -0.1 * (1 + 0.001 * s), "buy")
            if sell:
                for s in range(15, 915, 15):
                    self.tr(MM, t0 + hold + s, m, -1e5, 0.1 * mult * (1 - 0.0005 * s), "sell")
        return m

    def days(self, w, first, last, mult=1.5, per_day=2, **k):
        """`per_day` rounds on each of the days first..last-1 before NOW (30 = the oldest)."""
        off = (sum(map(ord, w)) % 50) * 60
        for day in range(first, last, -1):
            for j in range(per_day):
                self.round(w, NOW - day * D + off + j * 5 * H, mult, **k)

    def save(self):
        self.con.executemany("INSERT INTO wallet_trades VALUES (?,?,?,?,?,?,?)", self.rows)
        self.rows = []
        self.con.commit()


def expected(delay, mult=1.5, cost=0.03):
    """The copier's net return on one synthetic round: entry `delay` s late, exit `delay` s after his sale."""
    return mult * (1 - 0.0005 * delay) / (1 + 0.001 * delay) - 1 - cost


class Pure(unittest.TestCase):
    def test_split_days_60_40_and_no_split_on_few_days(self):
        tr, ho, split = kopija.split_days(range(100, 110))
        self.assertEqual((len(tr), len(ho), split), (6, 4, 106 * D))
        self.assertEqual(kopija.split_days(range(kopija.MIN_DAYS - 1))[2], None)

    def test_positions_first_buy_first_sale_and_his_own_return(self):
        t = [dict(sig="a", ts=100, mint="M", tokens=1000.0, sol=-1.0, kind="buy"),
             dict(sig="b", ts=200, mint="M", tokens=1000.0, sol=-2.0, kind="buy"),       # he adds: not a new signal
             dict(sig="c", ts=300, mint="M", tokens=-1000.0, sol=3.0, kind="sell"),      # his first sale
             dict(sig="d", ts=400, mint="M", tokens=-1000.0, sol=1.5, kind="sell"),      # closed
             dict(sig="e", ts=500, mint="M", tokens=500.0, sol=-1.0, kind="buy"),        # a new position, never sold
             dict(sig="f", ts=600, mint="N", tokens=-5.0, sol=1.0, kind="sell")]         # a sale of nothing we saw bought
        eps = kopija.episodes(t)
        self.assertEqual(len(eps), 2)
        a, b = eps
        self.assertEqual((a["t0"], a["px0"], a["sell_ts"], a["sell_px"], a["t1"], a["adds"]),
                         (100, 0.001, 300, 0.003, 400, 1))
        self.assertAlmostEqual(a["ret"], 4.5 / 3.0 - 1)                               # realized / cost of the whole position
        self.assertEqual((b["t0"], b["sell_ts"], b["t1"], b["ret"]), (500, None, None, None))

    def series(self, pts):
        return kopija.Series([(t, p, kopija.S_TRADE) for t, p in pts])

    def test_entry_is_the_first_price_after_the_delay_never_his_own(self):
        ep = {"mint": "M", "t0": 1000, "px0": 1.0, "sell_ts": 5000, "sell_px": 2.0}
        s = self.series([(1000, 1.0), (1040, 1.05), (1070, 1.10), (1200, 1.3), (5000, 2.0), (5070, 1.9)])
        t = kopija.simulate(ep, 60, "on", s, 10 ** 6)
        self.assertEqual((t["ts"], t["e_px"], t["out_ts"], t["x_px"], t["why"]), (1060, 1.10, 5060, 1.9, "prodao"))
        self.assertEqual(kopija.simulate(ep, 30, "on", s, 10 ** 6)["e_px"], 1.05)        # a shorter delay, a better price
        # no price within ENTRY_GAP_S of our entry: the buy is dropped, never guessed
        far = self.series([(1000, 1.0), (1060 + kopija.ENTRY_GAP_S + 1, 1.2), (5070, 1.9)])
        self.assertIsNone(kopija.simulate(ep, 60, "on", far, 10 ** 6))
        # an entry price but nothing near his sale: the exit has no price (x_px None), the slot is still taken
        t = kopija.simulate(ep, 60, "on", self.series([(1070, 1.1), (5060 + kopija.EXIT_GAP_S + 1, 3.0)]), 10 ** 6)
        self.assertEqual((t["x_px"], t["out_ts"], t["why"]), (None, 5060, "prodao"))

    def test_prints_of_one_second_are_one_price(self):
        s = self.series([(1000, 1.0), (1000, 3.0), (1001, 5.0), (999, 0.0)])            # a zero price is no price
        self.assertEqual((s.ts, s.px), ([1000, 1001], [2.0, 5.0]))
        self.assertEqual(s.first_from(990, 5), None)                                     # the next point is 10 s away
        self.assertEqual(s.first_from(990, 10), 0)

    def test_stop_time_limit_and_still_open(self):
        ep = {"mint": "M", "t0": 1000, "px0": 1.0, "sell_ts": 9000, "sell_px": 2.0}
        s = self.series([(1070, 1.0), (2000, 0.85), (3000, 0.7), (4000, 1.5), (9070, 2.0)])
        self.assertEqual(kopija.simulate(ep, 60, "on", s, 10 ** 6)["x_px"], 2.0)          # his exit only: no stop
        t = kopija.simulate(ep, 60, "on_stop", s, 10 ** 6)
        self.assertEqual((t["why"], t["out_ts"], t["x_px"]), ("stop", 3000, 0.7))        # filled at the print, not at -20 %
        never = {"mint": "M", "t0": 1000, "px0": 1.0, "sell_ts": None, "sell_px": None}
        day = 1060 + kopija.HOLD_S
        s2 = self.series([(1070, 1.0), (5000, 1.2), (day + 30, 1.4), (day + 5000, 9.0)])
        t = kopija.simulate(never, 60, "on_stop_24h", s2, 10 ** 7)
        self.assertEqual((t["why"], t["out_ts"], t["x_px"], t["stale"]), ("vrijeme", day, 1.4, False))
        t = kopija.simulate(never, 60, "on_stop_24h", self.series([(1070, 1.0), (5000, 1.2)]), 10 ** 7)
        self.assertEqual((t["why"], t["x_px"], t["stale"]), ("vrijeme", 1.2, True))  # nobody traded: the last print, flagged
        t = kopija.simulate(never, 60, "on", s2, day + 100)                           # he never sold: open at the data's end
        self.assertEqual((t["why"], t["open"], t["x_px"], t["out_ts"]), ("otvoreno", True, 1.4, day + 100))

    def tok(self, pts, liq=()):
        return {"sol": self.series(pts), "usd": kopija.Series(), "liq": sorted(liq), "supply": None}

    def test_cost_is_the_model_at_that_liquidity_never_under_three_percent(self):
        ep = {"mint": mint(1), "t0": 1000, "px0": 1.0, "sell_ts": 5000, "sell_px": 2.0, "ret": 1.0}
        pts = [(1060, 1.1), (5060, 1.9)]
        t = kopija.copy_trade("W", ep, 60, "on", self.tok(pts, [(1000, 500_000.0)]), 150.0, fee=0.01, hi=10 ** 6)
        self.assertAlmostEqual(t["cost"], 0.03)                                          # the model says 2.01 %: the floor
        self.assertAlmostEqual(t["ret"], 1.9 / 1.1 - 1 - 0.03)
        thin = kopija.copy_trade("W", ep, 60, "on", self.tok(pts, [(1000, 2_000.0)]), 150.0, fee=0.01, hi=10 ** 6)
        self.assertAlmostEqual(thin["cost"], 2 * 0.01 + 2 * 15.0 / (1000 + 15.0))        # 2 x fee + 2 x impact of 0.1 SOL
        self.assertLess(thin["ret"], t["ret"])
        self.assertAlmostEqual(t["slip"], 0.1)                                           # our entry 10 % above his fill
        self.assertIsNone(kopija.copy_trade("W", ep, 60, "on", self.tok([(5060, 1.9)]), 150.0, fee=0.01, hi=10 ** 6))

    def cand(self, k, ts, out_ts, token=None, liq=50_000.0, ret=0.1):
        t = {"ts": ts, "out_ts": out_ts, "token": token or f"T{k}", "liq": liq, "ret": ret, "wallet": "W"}
        return ({"t0": ts - 60}, t)

    def test_account_cap_one_position_a_token_liquidity_and_no_price(self):
        cands = [self.cand(k, 100 + k, 10_000) for k in range(12)]                       # 12 at once: 10 fit
        cands.append(self.cand(99, 20_000, 30_000, token="T0"))                          # later, T0 is free again
        cands.append(self.cand(98, 20_001, 30_000, token="T0"))                          # ... and now held
        cands.append(self.cand(97, 20_002, 30_000, liq=1_000.0))                         # a pool under the floor
        cands.append(self.cand(96, 20_003, 30_000, ret=None))                            # the exit has no price
        cands.append(({"t0": 50}, None))                                                 # no price at our entry
        small = self.cand(95, 20_004, 30_000)
        small[1]["mc"] = 12_000.0                                                   # under 30k $: never bought automatically
        cands.append(small)
        trs, why = kopija.portfolio(cands)
        self.assertEqual(why, {"kupnji": 18, "kopirano": 11, "bez_cijene_ulaza": 1, "bez_cijene_izlaza": 1,
                               "ispod_30k": 1, "likvidnost": 1, "vec_drzimo": 1, "strop": 2})
        self.assertEqual(len(trs), 11)
        self.assertEqual(sum(v for k, v in why.items() if k != "kupnji"), why["kupnji"])  # every buy has one fate
        _trs, why = kopija.portfolio([self.cand(1, 100, 200, liq=None)], kopija.LIQ_STRICT, True)
        self.assertEqual(why["likvidnost"], 1)                                        # the strict rule: unknown = not copied

    def trades(self, n, ret=0.1):
        return [{"token": f"T{i % 7}", "wallet": f"W{i % 3}", "ts": 1000 + i * D, "out_ts": 2000 + i * D,
                 "ret": ret if i % 2 else -ret / 2, "gross": 0.2, "cost": 0.03, "open": False, "stale": i == 1,
                 "why": "prodao", "kind": "sol", "his": 0.5, "mirror": 0.4, "at_his": 0.3, "slip": 0.05, "mc": 5e5,
                 "liq": 2e4, "src": 0}
                for i in range(n)]

    def test_under_thirty_trades_is_too_little_data(self):
        self.assertEqual(kopija.brief(self.trades(29)), {"n": 29, "malo": True})
        self.assertEqual(kopija.gap(self.trades(29)), {"n": 29, "malo": True})
        b = kopija.brief(self.trades(30))
        for k in ("ev_pct", "ci90", "hit", "hold_med_min", "sum_sol", "max_dd_sol", "bez_tokena_pct", "bez_novcanika_pct"):
            self.assertIn(k, b)
        self.assertLessEqual(b["ci90"][0], b["ev_pct"])
        self.assertGreaterEqual(b["ci90"][1], b["ev_pct"])
        self.assertEqual(b["zadnja_cijena"], 1)
        self.assertLess(b["ev_pes_pct"], b["ev_pct"])                                    # that one counted as a total loss
        self.assertLess(b["max_dd_sol"], 0)

    def test_the_decomposition_adds_up(self):
        trs = self.trades(40)
        for i, t in enumerate(trs):
            t.update(his=0.5 + i / 100, mirror=0.4 + i / 200, at_his=0.3 - i / 300, gross=0.2 + i / 400)
            t["ret"] = t["gross"] - t["cost"]
        g = kopija.gap(trs)
        self.assertAlmostEqual(g["skaliranje_pp"] + g["ulaz_pp"] + g["izlaz_pp"] + g["trosak_pp"], g["razlika_pp"], places=1)
        self.assertAlmostEqual(g["nase_pct"] - g["njegov_pct"], g["razlika_pp"], places=1)
        self.assertAlmostEqual(g["trosak_pp"], -3.0, places=2)
        self.assertEqual(len(kopija.gap_lines(g)), 6)
        usd = [dict(t, kind="usd") for t in trs]                                      # his SOL fills against USD prices: out
        self.assertEqual(kopija.gap(usd), {"n": 0, "malo": True})


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "wallets.db")
        self.w = World(self.path)
        self.good = [wal(f"Good{i}") for i in range(4)]
        self.fade, self.late = wal("Fade"), wal("Late")
        for w in self.good + [self.fade, self.late]:
            self.w.wallet(w)
        for w in self.good:
            self.w.days(w, 30, 0)                       # +50 % every round, before and after the split
        self.w.days(self.fade, 30, 12)                  # proven before the split ...
        self.w.days(self.fade, 12, 0, mult=0.6)         # ... and losing after it
        self.w.days(self.late, 30, 12, mult=0.6)        # losing before the split ...
        self.w.days(self.late, 12, 0, mult=5.0)         # ... brilliant after it: must never be picked
        self.w.save()
        self.addCleanup(self.w.con.close)
        self.lines = []

    def run_(self, **k):
        k.setdefault("p", NOPATHS)
        return kopija.run(now=NOW, path=self.path, fee=0.01, log=self.lines.append, **k)

    def ro(self):
        return sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)


class Selection(Base):
    def test_only_trades_before_the_split_decide(self):
        con = self.ro()
        days, _new = kopija.trade_days(con, NOW)
        _tr, _ho, split = kopija.split_days(days)
        a = kopija.select(con, split, kopija.paths(dict(NOPATHS, wallets=self.path)))
        con.close()
        self.assertEqual(a["rules"]["app"], sorted(self.good + [self.fade]))             # Fade was proven at the split
        self.assertNotIn(self.late, {w for ws in a["rules"].values() for w in ws})        # Late's future is not known
        self.assertEqual(a["rules"]["top"], a["rules"]["app"])                           # in profit before the split only
        self.assertTrue(a["info"][self.late]["proven"])                                  # 10+ closed, but they lost
        self.assertNotIn(MM, a["info"])                                                  # a labelled bot is never picked
        # the measured part rewritten: Late even better, the good ones ruined; the selection is the same
        w2 = World.__new__(World)
        w2.path, w2.rows, w2.k, w2.con = self.path, [], 10_000, sqlite3.connect(self.path)
        w2.days(self.late, 6, 0, mult=20.0)
        for w in self.good:
            w2.days(w, 6, 0, mult=0.1)
        w2.save()
        w2.con.close()
        con = self.ro()
        b = kopija.select(con, split, kopija.paths(dict(NOPATHS, wallets=self.path)))
        con.close()
        self.assertEqual(a["rules"], b["rules"])
        self.assertEqual({w: (x["dvaput"], x["jednom"], x.get("score")) for w, x in a["info"].items()},
                         {w: (x["dvaput"], x["jednom"], x.get("score")) for w, x in b["info"].items()})

    def test_proven_twice_at_the_split_ignores_later_trades(self):
        con = self.ro()
        tr = kopija.trades_of(con, self.late, 0, NOW + 1)                             # ALL of Late's trades, future included
        con.close()
        split = NOW - 12 * D
        self.assertEqual(kopija.dvaput_at(tr, split), {"jednom": False, "dvaput": False})
        self.assertEqual(kopija.dvaput_at(tr, NOW), {"jednom": False, "dvaput": False})  # realized before the cut < 0

    def test_a_wallet_found_after_the_split_is_marked(self):
        self.w.wallet(self.good[0], first_scored=NOW - 2 * D)                            # the tool met it after the split
        self.w.con.commit()
        res = self.run_()
        self.assertEqual(res["odabir"]["app"], 5)
        self.assertEqual(res["strict"]["wallets"], 4)
        self.assertLess(res["strict"]["n"], kopija.row_of(res, *kopija.PRIMARY)["n"])


class Pipeline(Base):
    def test_the_numbers_after_delay_and_cost_out_of_sample(self):
        res = self.run_()
        self.assertEqual((res["days"], res["train_days"], res["hold_days"]), (30, 18, 12))
        self.assertEqual(res["grid_n"], 36)
        self.assertEqual(len(res["grid"]), 36)
        r = kopija.row_of(res, *kopija.PRIMARY)
        # 4 good wallets x 2 x 12 days at +50 %, Fade x 2 x 12 at -40 %: every buy has a price, all are copied
        self.assertEqual((r["kupnji"], r["n"], r["nekopirano"]), (120, 120, 0.0))
        # Fade's losers: the first print at or under our -20 % is his own sale at 0.6 x his price: our stop fills there
        ev = (96 * expected(60) + 24 * (0.6 / 1.06 - 1 - 0.03)) / 120 * 100
        self.assertAlmostEqual(r["ev_pct"], ev, places=1)
        self.assertEqual(r["izlazi"], {"prodao": 96, "stop": 24, "vrijeme": 0, "otvoreno": 0})
        self.assertAlmostEqual(kopija.row_of(res, "app", 60, "on")["ev_pct"],
                               (96 * expected(60) + 24 * expected(60, 0.6)) / 120 * 100, places=1)
        self.assertAlmostEqual(r["sum_sol"], ev / 100 * 120 * 0.1, places=2)
        r30, r180 = kopija.row_of(res, "app", 30, "on_stop"), kopija.row_of(res, "app", 180, "on_stop")
        self.assertGreater(r30["ev_pct"], r["ev_pct"])                                   # the delay costs
        self.assertGreater(r["ev_pct"], r180["ev_pct"])
        g = res["gap"]
        self.assertAlmostEqual(g["njegov_pct"], (96 * 50 + 24 * -40) / 120, places=1)    # their own fills, no delay, no cost
        self.assertAlmostEqual(g["nase_pct"], r["ev_pct"], places=1)
        self.assertAlmostEqual(g["skaliranje_pp"] + g["ulaz_pp"] + g["izlaz_pp"] + g["trosak_pp"], g["razlika_pp"], places=1)
        self.assertAlmostEqual(g["trosak_pp"], -3.0, places=1)
        self.assertLess(g["ulaz_pp"], 0)
        self.assertAlmostEqual(g["ulaz_med_pct"], 6.0, places=1)                         # 60 s x 0.1 % a second
        self.assertEqual(res["own"]["app"]["zatvoreno"], 120)
        self.assertEqual(res["sources"], {kopija.SRC_HR[kopija.S_TRADE]: 120})
        self.assertEqual(res["demo_exit"], "on_stop")                                    # the best of the three at 60 s
        self.assertIn("u plusu", res["verdict"])
        self.assertIn("novčanici kopija: ", self.lines[-1])
        self.assertIn("isprobano 36 kombinacija", self.lines[-1])
        self.assertEqual(len(self.lines), 1)

    def test_a_buy_without_a_stored_price_is_counted_not_guessed(self):
        for j in range(10):                                                              # 10 buys nobody else traded
            self.w.round(self.good[0], NOW - 5 * D + j * 600 + 40_000, prints=False)
        for j in range(5):                                                               # 5 with an entry but no exit price
            m = self.w.round(self.good[1], NOW - 4 * D + j * 600 + 40_000, prints=False)
            self.w.tr(MM, NOW - 4 * D + j * 600 + 40_000 + 70, m, 1e5, -0.106, "buy")
        self.w.save()
        res = self.run_()
        r = kopija.row_of(res, "app", 60, "on")
        self.assertEqual(r["razlozi"]["bez_cijene_ulaza"], 10)
        self.assertEqual(r["razlozi"]["bez_cijene_izlaza"], 5)
        self.assertEqual((r["kupnji"], r["n"]), (135, 120))
        self.assertAlmostEqual(r["nekopirano"], 15 / 135, places=3)
        self.assertAlmostEqual(r["ev_pct"], (96 * expected(60) + 24 * expected(60, 0.6)) / 120 * 100, places=1)
        s = kopija.summary(res, NOW)
        self.assertTrue(any("bez cijene u trenutku našeg ulaza 10" in n for n in s["napomene"]))

    def test_the_stop_cuts_the_losers_only_where_a_price_shows_it(self):
        w = wal("Dump")
        self.w.wallet(w)
        self.w.days(w, 30, 12)
        for day in range(12, 0, -1):                                                     # after the split: -60 % in an hour
            for j in range(2):
                t0 = NOW - day * D + 7 * H + j * 5 * H
                m = self.w.round(w, t0, mult=0.3)
                self.w.tr(MM, t0 + 3600, m, 1e5, -0.04, "buy")                           # a print at 0.4 x his price
        self.w.save()
        res = self.run_()
        on, stop = kopija.row_of(res, "app", 60, "on"), kopija.row_of(res, "app", 60, "on_stop")
        self.assertEqual(stop["izlazi"]["stop"], 48)                                     # Dump's 24 and Fade's 24
        self.assertEqual(on["izlazi"]["stop"], 0)
        self.assertGreater(stop["ev_pct"], on["ev_pct"])                                 # out at 0.4 x, not at 0.3 x

    def test_too_few_copies_is_said_not_scored(self):
        con = sqlite3.connect(self.path)
        con.execute("DELETE FROM wallet_trades WHERE wallet = ? AND ts >= ?", (MM, NOW - 12 * D + 2 * D))
        con.commit()                                                                  # prices only for the first 2 test days
        con.close()
        res = self.run_()
        r = kopija.row_of(res, *kopija.PRIMARY)
        self.assertTrue(r["malo"])
        self.assertLess(r["n"], kopija.MIN_N)
        self.assertNotIn("ev_pct", r)
        self.assertIn("Premalo podataka", res["verdict"])
        s = kopija.summary(res, NOW)
        self.assertTrue(s["redovi"][0]["malo"])
        self.assertEqual(s["razlika"], [])
        from report import render
        self.assertIn("premalo podataka", render.kopija_block(s))


class Run(Base):
    def test_bounded_stored_and_never_raising_without_a_network(self):
        with mock.patch.object(socket, "socket", side_effect=AssertionError("mreža u replayu")), \
                mock.patch.object(socket, "create_connection", side_effect=AssertionError("mreža u replayu")):
            res = self.run_()
            self.assertEqual(kopija.latest(self.path)["grid_n"], 36)
            self.assertEqual(kopija.latest(self.path)["verdict"], res["verdict"])
            t0 = time.time()
            cut = self.run_(budget_s=0.0001)                                             # the budget ends at once
            self.assertLess(time.time() - t0, 5)
            self.assertTrue(cut["partial"])
            self.assertIn("djelomično", self.lines[-1])
        missing = kopija.run(now=NOW, path=os.path.join(self.tmp.name, "nema.db"), log=self.lines.append)
        self.assertEqual(missing, {})
        self.assertIn("nema podataka", self.lines[-1])
        with open(os.path.join(self.tmp.name, "smece.db"), "w") as f:
            f.write("ovo nije baza " * 100)
        self.assertEqual(kopija.run(now=NOW, path=f.name, log=self.lines.append).get("grid"), None)
        with mock.patch.object(kopija, "compute", side_effect=RuntimeError("bum")):
            self.assertEqual(self.run_(), {})
            self.assertIn("nije uspio (RuntimeError: bum)", self.lines[-1])
        with mock.patch.object(kopija, "compute", side_effect=RuntimeError("bum")):
            self.assertEqual(kopija.run(now=NOW, path=self.path, log=mock.Mock(side_effect=OSError)), {})

    def test_a_pass_without_days_keeps_the_last_result(self):
        self.run_()
        res = kopija.run(now=NOW - 400 * D, path=self.path, p=NOPATHS, log=self.lines.append)   # no trade that old
        self.assertIsNone(res.get("grid"))
        self.assertIn("Premalo podataka", res["verdict"])
        self.assertIn("zadnji spremljeni rezultat ostaje", self.lines[-1])
        self.assertEqual(len(kopija.latest(self.path)["grid"]), 36)

    def test_freshness_says_what_is_stale_and_what_refreshing_costs(self):
        con = sqlite3.connect(self.path)
        con.executemany("INSERT INTO helius_credits VALUES (?,?,?,?)",
                        [(NOW - 3 * D + i, "wallet_history", 20, "w") for i in range(100)])
        con.commit()
        with mock.patch.dict(os.environ, {"FOKUS_MIDCAP_FORCE": "1"}):
            f = kopija.freshness(con, NOW)
        con.close()
        self.assertTrue(f["fokus"])
        self.assertEqual(f["ugaseno"], ["wallets_harvest", "wallets_score"])
        self.assertTrue(f["osvjezi"])                                                    # 16.11.: on in the committed config
        self.assertEqual(f["kredita_po_provjeri"], 20.0)
        self.assertEqual(f["kredita_dan_prije"], 2000)
        self.assertLessEqual(f["procjena_kredita_dan"], f["strop_kredita_dan"])
        text = " ".join(kopija.freshness_lines(f, NOW))
        for k in ("fokus midcap", "ne rade skupljanje i ocjenjivanje", "isključeno dok vlasnik ne odobri",
                  "Helius kredita dnevno"):
            self.assertIn(k, text)


class Report(Base):
    def test_summary_the_email_block_the_strategies_rows_and_the_page(self):
        res = self.run_()
        s = kopija.summary(res, NOW)
        self.assertEqual(s["presuda"], res["verdict"])
        self.assertEqual(len(s["redovi"]), 9)                                   # primary, 2 delays, 2 exits, 3 rules, strict
        self.assertTrue(s["redovi"][0]["naziv"].startswith("Glavno pravilo"))
        self.assertEqual(len(s["razlika"]), 6)
        self.assertTrue(any("Isprobano 36 unaprijed zadanih kombinacija" in n for n in s["napomene"]))
        self.assertEqual(len(s["pristranosti"]), len(kopija.BIASES))
        self.assertTrue(any("preživjeli" in b for b in s["pristranosti"]))
        self.assertTrue(any("Tržišna vrijednost: ispod 1M" == g["naziv"] for g in s["skupine"]))
        self.assertEqual(len(s["mreza"]), 36)                                            # every combination tried is shown
        self.assertIsNone(kopija.summary(None))
        from report import midcap as rmid, render
        with mock.patch.dict(os.environ, {"REPORT_DB_DIR": self.tmp.name}):
            k = rmid.kopija(NOW)
            self.assertEqual(k["presuda"], res["verdict"])
            self.assertIsNone(k["demo"])                                                 # no league.db here: no demo row
            html = render.kopija_block(k)
            for text in ("Kopiranje dokazanih novčanika: koliko bismo zaradili mi", "Zašto je novčanik u plusu",
                         "Kako čitati i gdje test griješi", "Glavno pravilo", "90 % interval"):
                self.assertIn(text, html)
            rows = rmid.strategies(NOW)
            row = next(r for r in rows if r["naziv"] == "Kopija dokazanih novčanika: povijesni test")
            self.assertEqual((row["vrsta"], row["n"]), ("backtest", 120))
            self.assertIn("izvan uzorka (zadnjih 12 d)", row["opis"])
            self.assertIn("kopija", rmid.collect(NOW))
            from ui import strategije
            page = strategije.kopija_html(NOW)
            self.assertIn("id=kopija", page)
            self.assertIn("Zašto je novčanik u plusu", page)
            self.assertIn("Svih 36 isprobanih kombinacija", page)
        self.assertEqual(render.kopija_block(None), "")
        self.assertEqual(render.kopija_block({}), "")
        from report import ai
        small = ai.compact({"midcap": {"kopija": dict(s)}})["midcap"]["kopija"]          # the AI prompt stays small
        self.assertEqual(small["presuda"], s["presuda"])
        self.assertEqual(len(small["razlika"]), 6)
        for key in ("mreza", "skupine", "napomene", "pristranosti"):
            self.assertNotIn(key, small)


class Cli(Base):
    def args(self, **k):
        return argparse.Namespace(**{"ako_nema": False, "night": False, "force": False, **k})

    def test_kopija_command_only_when_missing_and_only_at_night(self):
        import run_wallets
        calls = []
        with mock.patch.object(wstore, "DB", self.path), mock.patch.object(kopija, "run", lambda **k: calls.append(k)), \
                mock.patch.object(os, "nice", lambda n: None):
            run_wallets.cmd_kopija(self.args(ako_nema=True))                             # no result yet: runs
            self.assertEqual(len(calls), 1)
            with mock.patch.object(kopija, "latest", lambda *a: {"ts": NOW, "day": "2020-01-01"}):
                run_wallets.cmd_kopija(self.args(ako_nema=True))                         # a result exists: skipped
                self.assertEqual(len(calls), 1)
                with mock.patch.object(run_wallets, "_in_night", lambda now: False):
                    run_wallets.cmd_kopija(self.args(night=True))                        # daytime: skipped
                self.assertEqual(len(calls), 1)
                with mock.patch.object(run_wallets, "_in_night", lambda now: True):
                    run_wallets.cmd_kopija(self.args(night=True))                        # the night window, another day
                self.assertEqual(len(calls), 2)
                run_wallets.cmd_kopija(self.args(force=True))
                self.assertEqual(len(calls), 3)

    def test_the_schedule_and_the_midcap_focus_leave_it_on(self):
        from ops import fokus
        with mock.patch.dict(os.environ, {"FOKUS_MIDCAP_FORCE": "1"}):
            for sub in ("kopija", "osvjezi", "dokazani", "rang"):
                self.assertIsNone(fokus.skip_cmd(["python3", "run_wallets.py", sub]), sub)
            self.assertEqual(fokus.skip_cmd(["python3", "run_wallets.py", "score"]), "wallets_score")
            self.assertEqual(fokus.skip_cmd(["python3", "run_wallets.py", "harvest"]), "wallets_harvest")
        with open(os.path.join(ROOT, "start.sh"), encoding="utf-8") as f:
            sh = f.read()
        self.assertIn('sleep "${KOPIJA_FIRST_S:-1200}"; python3 -m ops.heavy run_wallets.py kopija --ako-nema', sh)
        self.assertIn("python3 -m ops.heavy --night run_wallets.py kopija --night", sh)

    def test_the_paid_refresh_is_off_by_default_and_calls_nothing(self):
        import run_wallets
        # 16.11. (vlasnik: "Imaš Helios ... nadopuni sve te influencere i volete"): the committed config turns the
        # refresh ON (inside its day cap); the code's own default without that line stays OFF and calls nothing
        self.assertEqual(kopija.config()["osvjezi"], True)
        score = mock.Mock(side_effect=AssertionError("plaćeni poziv"))
        out = io.StringIO()
        off = dict(kopija.config(), osvjezi=False)
        with mock.patch.object(wstore, "DB", self.path), redirect_stdout(out), \
                mock.patch.object(kopija, "config", lambda *a, **k: off), \
                mock.patch.object(run_wallets, "score_one", score):
            run_wallets.cmd_osvjezi(argparse.Namespace(stanje=False))
            self.assertEqual(out.getvalue(), "")                                         # silent in the scheduled loop
            run_wallets.cmd_osvjezi(argparse.Namespace(stanje=True))
            self.assertIn("ISKLJUČENO", out.getvalue())
            self.assertIn("ništa nije pozvano", out.getvalue())
        score.assert_not_called()

    def test_the_refresh_when_the_owner_turns_it_on_stays_inside_its_day_cap(self):
        import run_wallets
        self.w.con.executemany("INSERT INTO dokazani VALUES (?,?,5,1,1,2,1,1,1)", [(w, NOW) for w in self.good])
        self.w.con.execute("UPDATE wallets SET scored_at = 0")
        self.w.con.commit()
        seen = []

        def score(con, w, pages):
            seen.append(w)
            return {"credits": 30}, "A", {}
        cfg = dict(kopija.CFG_DEFAULT, osvjezi=True, kredita_dan=70)
        with mock.patch.object(wstore, "DB", self.path), mock.patch.object(kopija, "config", lambda: cfg), \
                redirect_stdout(io.StringIO()) as out:
            run_wallets.cmd_osvjezi(argparse.Namespace(stanje=False), score=score)
        self.assertEqual(seen, self.good[:2])                                            # 2 x 30 credits fit under 70
        self.assertIn("potrošeno 60 Helius kredita", out.getvalue())


class Demo(SwitchBase):
    """The demo copies on league.db (the fixture of tests/test_pravi_novac_sve_offline: quote MC $100k, liquidity $50k)."""

    def setUp(self):
        super().setUp()
        d = self.tmp.name
        self.hdb, self.wdb = os.path.join(d, "hype.db"), os.path.join(d, "wallets.db")
        hc = sqlite3.connect(self.hdb)
        hc.execute("CREATE TABLE chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER, sol REAL, "
                   "PRIMARY KEY (sig, mint))")
        hc.commit()
        hc.close()
        self.wa, self.wb, self.wc = wal("Proven"), wal("NotCopyable"), wal("Unknown")
        wc = wstore.connect(self.wdb)
        rang.ensure(wc)
        dokazani.ensure(wc)
        for w in (self.wa, self.wb):
            wc.execute("INSERT INTO wallets (wallet, labels, scored_at, stats) VALUES (?, '[]', 1, '{}')", (w,))
            wc.execute("INSERT INTO dokazani VALUES (?,?,5,1,1,2,1,1,1)", (w, int(self.now)))
        rang.save(wc, "wallet", [{"target": self.wa, "score": 70.0, "proven": True, "copyable": True, "n": 12},
                                 {"target": self.wb, "score": 60.0, "proven": True, "copyable": False, "n": 12}],
                  int(self.now))
        wc.commit()
        wc.close()
        rang.clear()
        for p in (mock.patch.dict(os.environ, {"HYPE_DB": self.hdb}),):
            p.start()
            self.addCleanup(p.stop)
        kopija_demo._TRIED.clear()
        kopija_demo._FILLS.clear()
        kopija_demo._LAST.update(ts=0.0, fill=0.0)
        self.flag(kopija_demo.FLAG, "paper")
        settings.put(self.con, f"flag:{settings.MIKROKAP}", {"mode": "live", "since": 1, "who": "Jure"})  # the 5M gate is ON
        settings._FLAG_CACHE.clear()

    def chain(self, sig, w, t, side, ts, sol=1.0):
        hc = sqlite3.connect(self.hdb)
        hc.execute("INSERT INTO chain_trades VALUES (?,?,?,?,?,?)", (sig, w, t, side, int(ts), sol))
        hc.commit()
        hc.close()

    def go(self, now=None):
        mk = lambda toks: {x: self.quote["row"] for x in toks}   # noqa: E731
        return kopija_demo.run_once(self.lg, market_fn=mk, now=now or self.now, sol=150.0, force=True, hype_db=self.hdb,
                                    wallet_db=self.wdb)

    def test_flag_is_demo_only_by_construction(self):
        self.assertEqual(settings.FLAGS[kopija_demo.FLAG][0], "P25")
        self.assertIn(kopija_demo.FLAG, settings.NEVER_LIVE)
        self.assertIn(kopija_demo.FLAG, settings.PROFILE_FLAGS)
        self.assertNotIn(kopija_demo.FLAG, settings.OWNER_SWITCHES)
        self.assertEqual(settings.FLAG_DEFAULTS[kopija_demo.FLAG], "paper")
        with self.assertRaises(ValueError):
            settings.set_flag(self.con, kopija_demo.FLAG, "live", "Jure")
        self.assertEqual(kopija_demo.demo_user(), WU)   # 19.11.: the wallet-following demo account
        self.assertEqual((kopija_demo.DEMO_SOL, kopija_demo.MAX_OPEN, kopija_demo.STOP), (0.1, 40, 0.20))   # 19.11.: 10 -> 40

    def test_copies_a_proven_copyable_wallet_under_5m_on_the_demo_account_only(self):
        from trade import capgate
        self.assertEqual(kopija_demo.targets(self.now, self.wdb), frozenset({self.wa}))   # proven AND copyable only
        payload = [{"feePayer": self.wa, "signature": "s1", "timestamp": int(self.now) - 40,
                    "tokenTransfers": [{"mint": tok(1), "toUserAccount": self.wa, "tokenAmount": 2_000_000}]}]
        kopija_demo.note_fills(payload, [("s1", self.wa, tok(1), "buy", int(self.now) - 40, 1.0)])
        self.chain("s1", self.wa, tok(1), "buy", self.now - 40)
        self.chain("s2", self.wb, tok(2), "buy", self.now - 40)                          # proven, not copyable: no copy
        self.chain("s3", self.wc, tok(3), "buy", self.now - 40)                          # not on the list: no copy
        with mock.patch.object(capgate, "check", side_effect=AssertionError("capgate")), \
                mock.patch.object(capgate, "allow_entry", side_effect=AssertionError("capgate")):
            got = self.go()
        self.assertEqual([u for u, _t in got], [WU])                                     # MC $100k < 5M: entered on the demo
        r = self.lg.execute("SELECT user, wallet, buy_sig, buy_ts, his_sol, his_px_sol, delay_s, our_px_usd, our_px_sol, "
                            "exit_plan, status, size_usd, entry_mcap FROM kopija_trades").fetchall()
        self.assertEqual(len(r), 1)
        r = r[0]
        self.assertEqual(tuple(r)[:5], (WU, self.wa, "s1", int(self.now) - 40, 1.0))
        self.assertAlmostEqual(r[5], 1.0 / 2_000_000)                                    # his fill: SOL per token
        self.assertTrue(38 <= r[6] <= 45)                                                # our delay in seconds
        self.assertAlmostEqual(r[8], r[7] / 150.0)                                       # our price in SOL per token
        self.assertEqual((r[9], r[10]), ("on_stop", "open"))                             # no replay result yet: the default
        self.assertAlmostEqual(r[11], 0.1 * 150.0)                                       # the real stake
        self.assertEqual(r[12], 100_000.0)
        t = self.lg.execute("SELECT user, source, auto FROM trades WHERE token=?", (tok(1),)).fetchone()
        self.assertEqual(t[0], WU)
        self.assertTrue(t[1].startswith("kopija dokazanih"))
        self.assertEqual(json.loads(t[2])["sl"], "-20%")
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM trades WHERE user=?", (LU,)).fetchone()[0], 0)
        self.assertEqual(self.swaps, [])                                                 # no order was ever built
        self.assertEqual(self.go(), [])                                                  # the same buy is never copied twice

    def test_exit_when_he_sells_with_his_price_and_our_delay(self):
        self.chain("s1", self.wa, tok(1), "buy", self.now - 40)
        self.go()
        self.chain("s9", self.wa, tok(1), "sell", self.now + 600, sol=1.4)
        kopija_demo.note_fills([{"feePayer": self.wa, "signature": "s9", "tokenTransfers": [
            {"mint": tok(1), "fromUserAccount": self.wa, "tokenAmount": 2_000_000}]}],
            [("s9", self.wa, tok(1), "sell", int(self.now) + 600, 1.4)])
        got = self.go(self.now + 630)
        self.assertEqual(len(got), 1)
        r = self.lg.execute("SELECT status, exit_reason, his_sell_ts, his_sell_px_sol, exit_delay_s, our_exit_px_usd, ret "
                            "FROM kopija_trades").fetchone()
        self.assertEqual(tuple(r)[:3], ("closed", "wallet_sold", int(self.now) + 600))
        self.assertAlmostEqual(r[3], 1.4 / 2_000_000)
        self.assertEqual(r[4], 30)
        self.assertIsNotNone(r[6])
        st = kopija_demo.stats(self.lg, self.now + 700)
        self.assertEqual((st["n"], st["otvoreno"], st["zastavica"]), (1, 0, "paper"))
        self.assertIsNotNone(st["kasnjenje_med_s"])

    def test_caps_stale_buys_hard_rules_and_the_flag(self):
        self.chain("old", self.wa, tok(50), "buy", self.now - kopija_demo.FRESH_S - 5)
        self.assertEqual(self.go(), [])                                                  # too late: somebody else's trade
        for k in range(kopija_demo.MAX_OPEN + 2):
            self.chain(f"b{k}", self.wa, tok(100 + k), "buy", self.now - 20)
        self.assertEqual(len(self.go()), kopija_demo.MAX_OPEN)                           # the cap on open copies
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM kopija_trades WHERE status='open'").fetchone()[0],
                         kopija_demo.MAX_OPEN)
        self.lg.execute("UPDATE kopija_trades SET status='closed'")
        self.lg.execute("UPDATE trades SET status='closed'")
        self.lg.commit()
        kopija_demo._TRIED.clear()
        self.quote["row"] = (self.quote["row"][0], 9_000.0) + tuple(self.quote["row"][2:])   # a pool under 15k
        self.chain("thin", self.wa, tok(60), "buy", self.now - 20)
        self.assertEqual(self.go(), [])                                                  # the hard rules still hold
        self.quote["row"] = (self.quote["row"][0], 50_000.0) + tuple(self.quote["row"][2:])
        kopija_demo._TRIED.clear()
        with mock.patch.object(kopija_demo, "PER_DAY", kopija_demo.MAX_OPEN):
            self.chain("day", self.wa, tok(61), "buy", self.now - 20)
            self.assertEqual(self.go(), [])                                              # the day's cap is spent
        self.flag(kopija_demo.FLAG, "off")
        settings._FLAG_CACHE.clear()
        kopija_demo._TRIED.clear()
        self.chain("off", self.wa, tok(62), "buy", self.now - 20)
        self.assertEqual(self.go(), [])                                                  # the flag off: nothing is entered

    def test_his_price_filled_later_from_the_scorers_trades(self):
        self.chain("s1", self.wa, tok(1), "buy", self.now - 40)
        self.go()
        self.assertIsNone(self.lg.execute("SELECT his_px_sol FROM kopija_trades").fetchone()[0])
        wc = sqlite3.connect(self.wdb)
        wc.execute("INSERT INTO wallet_trades VALUES (?,?,?,?,?,?,?)",
                   (self.wa, "s1", int(self.now) - 40, tok(1), 4e6, -1.0, "buy"))
        wc.commit()
        wc.close()
        self.assertEqual(kopija_demo.fill_his(self.lg, self.wdb), 1)
        self.assertAlmostEqual(self.lg.execute("SELECT his_px_sol FROM kopija_trades").fetchone()[0], 0.25e-6)

    def test_the_report_shows_the_demo_copies(self):
        self.chain("s1", self.wa, tok(1), "buy", self.now - 40)
        self.go()
        from report import render
        st = kopija_demo.stats(self.lg, self.now)
        html = render.kopija_block({"demo": st})
        self.assertIn("Demo kopije (mjerenje unaprijed)", html)
        self.assertIn("zatvoreno 0, otvoreno 1", html)
        self.assertIn("Pravi novac i njegova pravila nisu dirani", html)


if __name__ == "__main__":
    unittest.main()
