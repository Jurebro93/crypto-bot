"""Wallet value history (trade/equity.py): deposits, PnL arithmetic, rates, the snapshot thread, the reconstruction.

No network and no real wallet: balances, prices and rates are handed in, the two network functions of the module
are replaced by ones that fail the test if anything reaches them.

    python3 -m unittest tests.test_equity_offline -v
"""
import argparse
import os
import signal
import sqlite3
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_trade  # noqa: E402
from trade import equity, executor, settings, wallet  # noqa: E402

NOW = 1_800_000_000
L = equity.LAMPORTS
ENV = ("TRADE_LIVE", "SOLANA_PRIVATE_KEY", "SOLANA_PUBLIC_KEY")


def _no_network(*a, **k):
    raise AssertionError("test je posegnuo za mrežom")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "trade.db")
        self._saved = (settings.DB, equity._pairs, equity._usd_eur_fetch, equity._sol_balance, equity._usdc_balance,
                       wallet.token_decimals)
        self._env = {k: os.environ.pop(k, None) for k in ENV}
        settings.DB = self.path
        equity._pairs = equity._usd_eur_fetch = equity._sol_balance = equity._usdc_balance = _no_network
        wallet.token_decimals = _no_network
        self.reset()
        self.con = executor.connect(self.path)

    def tearDown(self):
        equity.stop()
        (settings.DB, equity._pairs, equity._usd_eur_fetch, equity._sol_balance, equity._usdc_balance,
         wallet.token_decimals) = self._saved
        for k, v in self._env.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)
        self.reset()
        self.con.close()
        self.tmp.cleanup()

    @staticmethod
    def reset():
        equity._RATES.update(sol=None, sol_ts=0, sol_next=0, eur=None, eur_ts=0, eur_next=0, stored=None, stored_next=0)
        equity._USDC.update(addr=None, ts=0, val=None)
        equity._DEC.clear()
        equity._CACHE.clear()
        equity._LOGGED.clear()

    def snap(self, now, sol, usdc=0.0, prices=None, sol_usd=150.0, usd_eur=0.9, force=False, **kw):
        inject = {"addr": "ADDR", "balance": lambda a: sol, "usdc": usdc if callable(usdc) else (lambda a: usdc),
                  "market": lambda mints: (prices or {}, sol_usd),
                  "rates": lambda t: {"sol_usd": sol_usd, "usd_eur": usd_eur}, "decimals": lambda m: 6}
        inject.update(kw)
        return equity.snapshot(self.con, now=now, force=force, **inject)

    def order(self, ts, side, status="ok", a_in=0, a_out=0, fee=0, pid=1, mode="live", sig=None):
        self.con.execute("INSERT INTO orders (ts, position_id, token, side, mode, amount_in, amount_out, status, "
                         "fee_lamports, signature) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (ts, pid, "MINT", side, mode, a_in, a_out, status, fee, sig))
        self.con.commit()

    def position(self, token="MINT", mode="live", status="open", sol_in=0.1, qty=1_000_000_000, left=None, ts=NOW,
                 reason=None):
        cur = self.con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, "
                               "qty_left, sol_back, fees_sol) VALUES (?,?,?,?,?,?,?,?,?,0,0)",
                               (token, token, ts, mode, status, reason, sol_in, qty, qty if left is None else left))
        self.con.commit()
        return cur.lastrowid

    def rows(self):
        return self.con.execute("SELECT ts, sol, usdc, tokens_sol, flow_sol, src FROM equity ORDER BY ts").fetchall()


class Flows(Base):
    """Deposit / withdrawal detection: what the orders do not explain, above FLOW_MIN_SOL."""

    def test_first_snapshot_books_everything_as_the_opening_deposit(self):
        r = self.snap(NOW, 1.0, usdc=30.0)                       # 30 USDC at 150 $/SOL = 0.2 SOL
        self.assertAlmostEqual(r["value_sol"], 1.2)
        self.assertAlmostEqual(r["flow_sol"], 1.2)
        s = equity.summary(self.con, now=NOW)
        self.assertAlmostEqual(s["net_in_sol"], 1.2)
        self.assertAlmostEqual(s["pnl_sol"], 0.0)                # PnL starts at 0
        self.assertEqual((s["n"], s["first_ts"], s["last_ts"]), (1, NOW, NOW))

    def test_at_most_one_per_every_s_unless_forced(self):
        self.assertIsNotNone(self.snap(NOW, 1.0))
        self.assertIsNone(self.snap(NOW + equity.EVERY_S - 1, 1.0))
        self.assertIsNotNone(self.snap(NOW + 10, 1.0, force=True))
        self.assertIsNone(self.snap(NOW + 10, 1.0, force=True))   # the same second again: ts is the key
        self.assertIsNotNone(self.snap(NOW + 10 + equity.EVERY_S, 1.0))
        self.assertEqual(len(self.rows()), 3)

    def test_deposit_and_withdrawal(self):
        self.snap(NOW, 1.0)
        r = self.snap(NOW + 300, 1.5)
        self.assertAlmostEqual(r["flow_sol"], 0.5)
        r = self.snap(NOW + 600, 1.2)
        self.assertAlmostEqual(r["flow_sol"], -0.3)
        s = equity.summary(self.con, now=NOW + 600)
        self.assertAlmostEqual(s["net_in_sol"], 1.2)
        self.assertAlmostEqual(s["pnl_sol"], 0.0)                # money in and out is not profit or loss
        self.assertEqual([(d["sol"], d["kind"]) for d in equity.deposits(self.con)],
                         [(1.0, "pocetni"), (0.5, "uplata"), (-0.3, "isplata")])

    def test_trades_are_not_flows(self):
        self.snap(NOW, 1.0)
        pid = self.position(sol_in=0.1, qty=1_000_000_000)
        self.order(NOW + 100, "buy", a_in=int(0.1 * L), a_out=1_000_000_000, fee=2_044_280, pid=pid)
        px = {"MINT": (0.00012, None)}                           # 1000 whole tokens x 0.00012 = 0.12 SOL
        r = self.snap(NOW + 300, 1.0 - 0.1 - 0.00204428, prices=px)
        self.assertEqual(r["flow_sol"], 0.0)
        self.assertAlmostEqual(r["tokens_sol"], 0.12)
        self.assertAlmostEqual(equity.summary(self.con, now=NOW + 300)["pnl_sol"], 0.12 - 0.1 - 0.00204428)
        # sold for 0.15, the fee, and the token account's rent comes back
        self.order(NOW + 400, "sell", a_in=1_000_000_000, a_out=int(0.15 * L), fee=5000, pid=pid)
        self.order(NOW + 401, "rent", a_out=2_039_280, fee=-2_039_280, pid=pid)
        self.con.execute("UPDATE positions SET status='closed', qty_left=0 WHERE id=?", (pid,))
        self.con.commit()
        r = self.snap(NOW + 600, 1.0 - 0.1 - 0.00204428 + 0.15 - 0.000005 + 0.00203928)
        self.assertEqual(r["flow_sol"], 0.0)
        s = equity.summary(self.con, now=NOW + 600)
        self.assertAlmostEqual(s["net_in_sol"], 1.0)
        self.assertAlmostEqual(s["pnl_sol"], 0.05 - 0.00204428 - 0.000005 + 0.00203928, places=7)

    def test_fee_noise_below_the_threshold_is_not_a_flow(self):
        self.snap(NOW, 1.0)
        r = self.snap(NOW + 300, 1.0 - 0.015)                    # e.g. fees a quote under-estimated
        self.assertEqual(r["flow_sol"], 0.0)
        self.assertAlmostEqual(equity.summary(self.con, now=NOW + 300)["pnl_sol"], -0.015)   # stays in the result
        r = self.snap(NOW + 600, 1.0 - 0.015 + equity.FLOW_MIN_SOL + 0.001)
        self.assertAlmostEqual(r["flow_sol"], equity.FLOW_MIN_SOL + 0.001)

    def test_failed_order_costs_its_fee_only_when_it_reached_the_chain(self):
        self.snap(NOW, 1.0)
        self.order(NOW + 50, "buy", status="failed", a_in=int(0.1 * L), fee=30_000_000)              # never sent
        self.order(NOW + 60, "buy", status="failed", a_in=int(0.1 * L), fee=25_000_000, sig="SIG")   # landed, failed
        self.order(NOW + 70, "buy", status="ok", a_in=int(0.1 * L), fee=0, mode="dry")              # a dry-run quote
        self.order(NOW + 80, "buy", status="blocked", a_in=int(0.1 * L), fee=40_000_000)
        r = self.snap(NOW + 300, 1.0 - 0.025)
        self.assertEqual(r["flow_sol"], 0.0)                     # 0.025 explained by the landed failure alone

    def test_order_booked_late_with_an_old_time_is_still_counted_once(self):
        """A swap's row carries the time the swap started; the window between snapshots is by order id."""
        self.snap(NOW, 1.0)
        self.order(NOW - 5, "buy", a_in=int(0.1 * L), fee=0)     # written after the snapshot, stamped before it
        r = self.snap(NOW + 300, 0.9, prices={})
        self.assertEqual(r["flow_sol"], 0.0)
        r = self.snap(NOW + 600, 0.9)
        self.assertEqual(r["flow_sol"], 0.0)                     # and not a second time

    def test_time_window_when_the_mark_is_missing(self):
        self.snap(NOW, 1.0)
        self.con.execute("DELETE FROM settings WHERE k='equity_oid'")
        self.order(NOW + 100, "buy", a_in=int(0.1 * L))
        self.assertEqual(self.snap(NOW + 300, 0.9)["flow_sol"], 0.0)

    def test_buy_reconciled_after_a_crash_is_explained_by_its_position(self):
        self.snap(NOW, 1.0)
        self.position(sol_in=0.1, ts=NOW + 100, reason="usklađeno s lancem nakon restarta (SOL ulog = zapisana namjera)")
        r = self.snap(NOW + 300, 0.9)                            # no orders row exists for that buy
        self.assertEqual(r["flow_sol"], 0.0)
        self.assertAlmostEqual(r["tokens_sol"], 0.1)

    def test_usdc_deposit_is_a_flow_and_a_hand_swap_is_not(self):
        self.snap(NOW, 1.0, usdc=0.0)
        r = self.snap(NOW + 300, 1.0, usdc=75.0)                 # 75 USDC arrived = 0.5 SOL
        self.assertAlmostEqual(r["flow_sol"], 0.5)
        self.assertAlmostEqual(equity.summary(self.con, now=NOW + 300)["pnl_sol"], 0.0)
        r = self.snap(NOW + 600, 1.498, usdc=0.0)                # the owner swapped it for SOL on Jupiter
        self.assertEqual(r["flow_sol"], 0.0)
        self.assertAlmostEqual(equity.summary(self.con, now=NOW + 600)["pnl_sol"], -0.002)   # the swap's cost

    def test_usdc_is_asked_once_an_hour_and_at_once_when_sol_jumps(self):
        calls = []

        def usdc(addr):
            calls.append(addr)
            return 15.0
        equity._usdc_balance = usdc

        def snap(now, sol):
            inject = {"addr": "ADDR", "balance": lambda a: sol, "market": lambda m: ({}, 150.0),
                      "rates": lambda t: {"sol_usd": 150.0, "usd_eur": 0.9}}
            return equity.snapshot(self.con, now=now, **inject)
        self.assertAlmostEqual(snap(NOW, 1.0)["usdc"], 15.0)
        snap(NOW + 300, 1.0)
        snap(NOW + 600, 1.0)
        self.assertEqual(len(calls), 1)                          # the hour's reading stands
        snap(NOW + 900, 1.4)                                     # SOL jumped: is it a deposit or a hand swap?
        self.assertEqual(len(calls), 2)
        snap(NOW + 900 + equity.USDC_EVERY_S, 1.4)
        self.assertEqual(len(calls), 3)


class Guards(Base):
    """No snapshot while the balance and the ledger cannot describe the same moment."""

    def test_swap_in_flight_or_just_landed(self):
        self.snap(NOW, 1.0)
        t = NOW + 300
        pid = self.position(status="pending", ts=t - 2)
        self.assertIsNone(self.snap(t, 0.9))                     # a real buy is being sent
        self.con.execute("UPDATE positions SET status='open' WHERE id=?", (pid,))
        self.order(t - 2, "sell", status="pending", pid=pid)
        self.assertIsNone(self.snap(t, 0.9))                     # a real sale is being sent
        self.con.execute("DELETE FROM orders")
        self.order(t - 10, "sell", a_out=int(0.2 * L), pid=pid)
        self.assertIsNone(self.snap(t, 1.2))                     # landed seconds ago: the node may not show it yet
        self.assertIsNotNone(self.snap(t - 10 + equity.SETTLE_S + 1, 1.2))
        self.assertEqual(self.rows()[-1][4], 0.0)

    def test_dry_run_swaps_do_not_hold_snapshots_back(self):
        self.snap(NOW, 1.0)
        self.position(status="pending", mode="dry", ts=NOW + 299)
        self.order(NOW + 299, "sell", status="pending", mode="dry")
        self.order(NOW + 299, "buy", status="dry", mode="dry", a_in=int(0.1 * L))
        self.assertIsNotNone(self.snap(NOW + 300, 1.0))

    def test_order_booked_while_measuring(self):
        self.snap(NOW, 1.0)

        def balance(addr):
            self.order(NOW + 200, "buy", a_in=int(0.1 * L))      # the trade loop books a swap during our RPC call
            return 0.9
        self.assertIsNone(self.snap(NOW + 300, 0.0, balance=balance))
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.snap(NOW + 320, 0.9)["flow_sol"], 0.0)   # the next tick sees both sides


class Positions(Base):
    """tokens_sol: open REAL positions at the price, the stake when there is no price; dry ones never."""

    def test_price_stake_and_dry(self):
        self.position("AAA", sol_in=0.1, qty=2_000_000_000, left=1_000_000_000)       # half sold, 1000 whole tokens
        self.position("BBB", sol_in=0.2, qty=5_000_000_000)                           # no price anywhere
        self.position("DRY", mode="dry", sol_in=0.3)
        self.position("OLD", status="closed", sol_in=0.4)
        seen = []

        def market(mints):
            seen.extend(mints)
            return {"AAA": (0.0002, None)}, 150.0
        r = self.snap(NOW, 1.0, market=market)
        self.assertEqual(sorted(seen), ["AAA", "BBB"])            # one request, real open positions only
        self.assertAlmostEqual(r["tokens_sol"], 1000 * 0.0002 + 0.2)
        self.assertAlmostEqual(r["value_sol"], 1.0 + 0.2 + 0.2)

    def test_thin_pool_cannot_paint_a_profit(self):
        self.position("AAA", sol_in=0.1, qty=1_000_000_000)
        r = self.snap(NOW, 1.0, prices={"AAA": (0.01, 2.0)})     # "worth" 10 SOL in a pool that holds 2 SOL
        self.assertAlmostEqual(r["tokens_sol"], 10 * 1.0 / (1.0 + 10))
        self.assertLess(r["tokens_sol"], 1.0)

    def test_no_decimals_or_no_prices_falls_back_to_the_stake(self):
        self.position("AAA", sol_in=0.1, qty=1_000_000_000, left=500_000_000)

        def boom(mint):
            raise OSError("RPC")
        r = self.snap(NOW, 1.0, prices={"AAA": (0.5, None)}, decimals=boom)
        self.assertAlmostEqual(r["tokens_sol"], 0.05)

        def no_market(mints):
            raise TimeoutError("DexScreener")
        r = self.snap(NOW + 300, 1.0, market=no_market)
        self.assertAlmostEqual(r["tokens_sol"], 0.05)
        self.assertEqual(r["flow_sol"], 0.0)

    def test_market_reads_one_dexscreener_answer(self):
        asked = []

        def pairs(mints):
            asked.append(list(mints))
            return [
                {"chainId": "solana", "baseToken": {"address": equity.WSOL}, "quoteToken": {"address": equity.USDC},
                 "priceUsd": "160", "liquidity": {"usd": 5e6}},
                {"chainId": "solana", "baseToken": {"address": "AAA"}, "quoteToken": {"address": equity.WSOL},
                 "priceNative": "0.0005", "priceUsd": "0.09", "liquidity": {"usd": 32000}},
                {"chainId": "solana", "baseToken": {"address": "BBB"}, "quoteToken": {"address": equity.USDC},
                 "priceUsd": "0.32", "liquidity": {"usd": 16000}},
                {"chainId": "ethereum", "baseToken": {"address": "CCC"}, "priceUsd": "5"},
            ]
        equity._pairs = pairs
        prices, sol_usd = equity._market(["AAA", "BBB", "CCC", "AAA"])
        self.assertEqual(asked, [["AAA", "BBB", "CCC", equity.WSOL]])   # one request, SOL rides along
        self.assertEqual(sol_usd, 160.0)
        self.assertAlmostEqual(prices["AAA"][0], 0.0005)          # quoted in SOL: the pool's own price
        self.assertAlmostEqual(prices["AAA"][1], 200.0)
        self.assertAlmostEqual(prices["BBB"][0], 0.002)           # quoted in USDC: through the SOL price
        self.assertNotIn("CCC", prices)


class Series(Base):
    def fill(self):
        self.snap(NOW, 1.0, sol_usd=100.0, usd_eur=0.9)                      # opening 1.0
        self.snap(NOW + 300, 1.1, sol_usd=100.0, usd_eur=0.9)                # 0.1 arrived
        self.snap(NOW + 600, 1.6, sol_usd=110.0, usd_eur=0.9)                # deposit 0.5
        self.snap(NOW + 900, 1.59, sol_usd=110.0, usd_eur=0.9)               # -0.01: fees, below a flow
        self.snap(NOW + 1200, 1.59, usdc=22.0, sol_usd=110.0, usd_eur=0.8)   # 22 USDC in = 0.2 SOL

    def test_series_arithmetic(self):
        self.fill()
        s = equity.series(self.con)
        self.assertEqual([p["ts"] for p in s], [NOW, NOW + 300, NOW + 600, NOW + 900, NOW + 1200])
        self.assertEqual([p["flow_sol"] for p in s], [1.0, 0.1, 0.5, 0.0, 0.2])
        self.assertEqual([p["net_in_sol"] for p in s], [1.0, 1.1, 1.6, 1.6, 1.8])
        self.assertEqual([round(p["pnl_sol"], 9) for p in s], [0.0, 0.0, 0.0, -0.01, -0.01])
        for p in s:
            self.assertAlmostEqual(p["pnl_sol"], p["value_sol"] - p["net_in_sol"])
            self.assertAlmostEqual(p["value_usd"], p["value_sol"] * p["sol_usd"], places=3)
            self.assertAlmostEqual(p["value_eur"], p["value_usd"] * p["usd_eur"], places=3)
            self.assertEqual(p["src"], "live")
        self.assertAlmostEqual(s[-1]["value_sol"], 1.59 + 0.2)
        self.assertAlmostEqual(s[-1]["pnl_sol"], -0.01)
        self.assertAlmostEqual(s[-1]["value_usd"], 1.79 * 110, places=3)
        self.assertAlmostEqual(s[-1]["value_eur"], 1.79 * 110 * 0.8, places=3)
        self.assertEqual(set(s[0]), {"ts", "sol", "usdc", "tokens_sol", "value_sol", "value_usd", "value_eur", "sol_usd",
                                     "usd_eur", "flow_sol", "net_in_sol", "pnl_sol", "src"})

    def test_since_keeps_the_money_put_in_before_it(self):
        self.fill()
        s = equity.series(self.con, since=NOW + 600)
        self.assertEqual([p["ts"] for p in s], [NOW + 600, NOW + 900, NOW + 1200])
        self.assertEqual([p["net_in_sol"] for p in s], [1.6, 1.6, 1.8])
        self.assertEqual([p["ts"] for p in equity.series(self.con, since=NOW + 1199)], [NOW + 1200])   # whole minutes
        self.assertEqual(equity.series(self.con, since=NOW + 5000), [])

    def test_thinning_keeps_the_last_point_and_every_deposit(self):
        sol = 1.0
        for i in range(120):
            sol += 0.5 if i in (40, 41, 90) else 0.0
            self.snap(NOW + i * 300, sol)
        full = equity.series(self.con, max_points=1000)
        thin = equity.series(self.con, max_points=10)
        self.assertEqual(len(full), 120)
        self.assertLessEqual(len(thin), 10)
        self.assertEqual(thin[-1]["ts"], full[-1]["ts"])
        self.assertAlmostEqual(sum(p["flow_sol"] for p in thin), sum(p["flow_sol"] for p in full))
        self.assertAlmostEqual(thin[-1]["net_in_sol"], 2.5)
        self.assertAlmostEqual(thin[-1]["value_sol"], 2.5)
        for p in thin:
            self.assertAlmostEqual(p["pnl_sol"], 0.0)             # deposits never show as profit, thinned or not
            self.assertIn(p["ts"], {q["ts"] for q in full})       # a real row, not an average

    def test_series_is_cached_until_a_row_arrives_and_safe_to_change(self):
        self.fill()
        a = equity.series(self.con)
        a[0]["value_sol"] = -1
        seen = []
        self.con.set_trace_callback(seen.append)
        b = equity.series(self.con)
        self.con.set_trace_callback(None)
        self.assertEqual(b[0]["value_sol"], 1.0)                  # the caller got its own copy
        self.assertFalse([q for q in seen if "GROUP BY" in q or "ORDER BY ts" in q])   # only the two-number stamp
        self.snap(NOW + 1500, 1.59, usdc=22.0)
        self.assertEqual(len(equity.series(self.con)), 6)

    def test_summary(self):
        self.assertEqual(equity.summary(self.con), {})
        self.assertEqual(equity.series(self.con), [])
        self.assertEqual(equity.deposits(self.con), [])
        self.fill()
        s = equity.summary(self.con, now=NOW + 1200)
        self.assertEqual(set(s), {"value_sol", "value_usd", "value_eur", "sol", "usdc", "tokens_sol", "net_in_sol",
                                  "pnl_sol", "pnl_pct", "pnl_24h_sol", "first_ts", "last_ts", "sol_usd", "usd_eur", "n"})
        self.assertAlmostEqual(s["value_sol"], 1.79)
        self.assertAlmostEqual(s["net_in_sol"], 1.8)
        self.assertAlmostEqual(s["pnl_sol"], -0.01)
        self.assertAlmostEqual(s["pnl_pct"], round(100 * -0.01 / 1.8, 2))
        self.assertAlmostEqual(s["pnl_24h_sol"], -0.01)           # history shorter than a day: against its start
        self.assertEqual((s["sol"], s["usdc"], s["sol_usd"], s["usd_eur"], s["n"]), (1.59, 22.0, 110.0, 0.8, 5))
        self.assertAlmostEqual(s["value_usd"], 1.79 * 110, places=3)
        self.assertAlmostEqual(s["value_eur"], 1.79 * 110 * 0.8, places=3)

    def test_pnl_24h_is_against_the_snapshot_a_day_ago(self):
        self.position("AAA", sol_in=0.1, qty=1_000_000_000)        # 1000 whole tokens, the result moves with the price
        self.snap(NOW, 1.0, prices={"AAA": (0.0001, None)})
        self.snap(NOW + 3600, 1.0, prices={"AAA": (0.00009, None)})   # -0.01 on the first day
        day = NOW + 3600 + 86400
        self.snap(day, 1.0, prices={"AAA": (0.00013, None)})          # +0.04 since
        s = equity.summary(self.con, now=day)
        self.assertAlmostEqual(s["pnl_sol"], 0.03)
        self.assertAlmostEqual(s["pnl_24h_sol"], 0.04)

    def test_everything_withdrawn_has_no_percent(self):
        self.snap(NOW, 1.0)
        self.snap(NOW + 300, 0.0)
        s = equity.summary(self.con, now=NOW + 300)
        self.assertAlmostEqual(s["net_in_sol"], 0.0)
        self.assertIsNone(s["pnl_pct"])

    def test_readers_never_raise(self):
        dead = sqlite3.connect(":memory:")
        dead.close()
        self.assertEqual(equity.series(dead), [])
        self.assertEqual(equity.summary(dead), {})
        self.assertEqual(equity.deposits(dead), [])
        self.assertEqual(equity.backfill(dead), 0)
        self.assertIsNone(equity.snapshot(dead, now=NOW, addr="ADDR"))


class Rates(Base):
    def net(self, sol=160.0, eur=0.87):
        self.calls = {"sol": 0, "eur": 0}

        def pairs(mints):
            self.calls["sol"] += 1
            if sol is None:
                raise TimeoutError("DexScreener")
            return [{"chainId": "solana", "baseToken": {"address": equity.WSOL}, "quoteToken": {"address": equity.USDC},
                     "priceUsd": str(sol), "liquidity": {"usd": 1e6}}]

        def eur_fetch():
            self.calls["eur"] += 1
            return eur
        equity._pairs, equity._usd_eur_fetch = pairs, eur_fetch

    def test_cache_sol_60s_eur_6h(self):
        self.net()
        self.assertEqual(equity.rates(NOW), {"sol_usd": 160.0, "usd_eur": 0.87, "ts": NOW})
        for dt in (1, 30, 59):
            equity.rates(NOW + dt)
        self.assertEqual(self.calls, {"sol": 1, "eur": 1})
        equity.rates(NOW + 61)
        self.assertEqual(self.calls, {"sol": 2, "eur": 1})
        equity.rates(NOW + equity.EUR_TTL_S + 1)
        self.assertEqual(self.calls["eur"], 2)

    def test_fallback_is_the_last_stored_rate(self):
        self.snap(NOW - 600, 1.0, sol_usd=140.0, usd_eur=0.91)   # what an earlier snapshot wrote
        self.reset()
        self.net(sol=None, eur=None)
        r = equity.rates(NOW)
        self.assertEqual((r["sol_usd"], r["usd_eur"], r["ts"]), (140.0, 0.91, NOW - 600))

    def test_a_dead_source_is_not_asked_every_second(self):
        self.net(sol=None, eur=None)
        for dt in range(30):
            self.assertEqual(equity.rates(NOW + dt), {"sol_usd": None, "usd_eur": None, "ts": 0})
        self.assertEqual(self.calls, {"sol": 1, "eur": 1})
        equity.rates(NOW + equity.EUR_RETRY_S + 1)               # the rate is retried after 10 min, not after 6 h
        self.assertEqual(self.calls["eur"], 2)

    def test_last_good_value_survives_a_failed_refresh(self):
        self.net()
        equity.rates(NOW)
        self.net(sol=None, eur=None)
        r = equity.rates(NOW + 3600 * 7)
        self.assertEqual((r["sol_usd"], r["usd_eur"], r["ts"]), (160.0, 0.87, NOW))   # ts says how old the price is

    def test_never_raises(self):
        def boom(*a):
            raise RuntimeError("x")
        equity._pairs = equity._usd_eur_fetch = boom
        settings.DB = os.path.join(self.tmp.name, "nema", "trade.db")
        self.assertEqual(equity.rates(NOW), {"sol_usd": None, "usd_eur": None, "ts": 0})

    def test_eur_fetch_reads_the_ecb_answer_and_tries_the_second_address(self):
        equity._usd_eur_fetch = self._saved[2]
        asked = []
        saved = equity.http.get_json

        def get_json(url, params=None, ttl=0, timeout=30, headers=None, retries=None):
            asked.append((url, timeout, retries))
            if len(asked) == 1:
                raise TimeoutError("spor")
            return {"amount": 1.0, "base": "USD", "date": "2026-11-09", "rates": {"EUR": 0.8643}}
        equity.http.get_json = get_json
        try:
            self.assertEqual(equity._usd_eur_fetch(), 0.8643)
            self.assertEqual([a[0] for a in asked], list(equity.EUR_URLS))
            self.assertTrue(all(t <= 5 and r == 0 for _, t, r in asked))   # short timeout, no retry loop
            equity.http.get_json = lambda *a, **k: {"rates": {"EUR": 0}}
            self.assertIsNone(equity._usd_eur_fetch())
        finally:
            equity.http.get_json = saved

    def test_snapshot_uses_the_stored_rates_when_the_network_gives_none(self):
        self.snap(NOW, 1.0, sol_usd=150.0, usd_eur=0.9)
        r = equity.snapshot(self.con, now=NOW + 300, addr="ADDR", balance=lambda a: 1.0, usdc=lambda a: 0.0,
                            market=lambda m: ({}, None), rates=lambda t: {"sol_usd": None, "usd_eur": None})
        self.assertEqual((r["sol_usd"], r["usd_eur"]), (150.0, 0.9))


class NeverRaisesNeverBlocks(Base):
    def test_snapshot_swallows_every_failure(self):
        def boom(*a):
            raise RuntimeError("RPC https://rpc.example/?api-key=TAJNA nije odgovorio")
        self.assertIsNone(self.snap(NOW, 1.0, balance=boom))
        self.assertIsNone(self.snap(NOW, 1.0, usdc=boom))         # the opening deposit needs the USDC
        self.assertIsNone(self.snap(NOW, 1.0, rates=boom))
        self.assertEqual(self.rows(), [])
        self.assertIsNone(equity.snapshot(self.con, now=NOW))     # no address anywhere: nothing to measure
        self.assertNotIn("TAJNA", equity._err(RuntimeError("https://rpc.example/?api-key=TAJNA x")))
        self.assertIsNotNone(self.snap(NOW, 1.0))
        self.assertIsNotNone(self.snap(NOW + 300, 1.0, usdc=lambda a: 0.0))

    def test_usdc_failure_later_keeps_the_last_reading(self):
        equity._usdc_balance = lambda a: 30.0
        base = {"addr": "ADDR", "balance": lambda a: 1.0, "market": lambda m: ({}, 150.0),
                "rates": lambda t: {"sol_usd": 150.0, "usd_eur": 0.9}}
        equity.snapshot(self.con, now=NOW, **base)

        def boom(a):
            raise OSError("RPC")
        equity._usdc_balance = boom
        r = equity.snapshot(self.con, now=NOW + equity.USDC_EVERY_S + 1, **base)
        self.assertEqual((r["usdc"], r["flow_sol"]), (30.0, 0.0))

    def test_thread_measures_without_holding_the_caller(self):
        os.environ["SOLANA_PUBLIC_KEY"] = "ADDR"
        started = threading.Event()

        def slow(addr):
            started.set()
            time.sleep(0.4)                                       # an RPC that takes its time
            return 2.0
        equity._sol_balance = slow
        equity._usdc_balance = lambda a: 0.0
        equity._pairs = lambda mints: [{"chainId": "solana", "baseToken": {"address": equity.WSOL},
                                        "quoteToken": {"address": equity.USDC}, "priceUsd": "150",
                                        "liquidity": {"usd": 1e6}}]
        equity._usd_eur_fetch = lambda: 0.9
        t0 = time.time()
        th = equity.start(self.path, tick=0.05)
        self.assertLess(time.time() - t0, 0.2)                    # start() returned, the measuring goes on behind
        self.assertTrue(th.daemon)
        self.assertIs(equity.start(self.path, tick=0.05), th)     # one thread, however often it is asked for
        self.assertTrue(started.wait(3))
        self.con.execute("INSERT INTO settings VALUES ('x','1',0,'test')")   # the caller's connection writes meanwhile
        self.con.commit()
        end = time.time() + 5
        while time.time() < end and not self.rows():
            time.sleep(0.05)
        equity.stop()
        rows = self.rows()
        self.assertEqual(len(rows), 1)                            # and only one per EVERY_S, whatever the tick
        self.assertEqual((rows[0][1], rows[0][4], rows[0][5]), (2.0, 2.0, "live"))
        self.assertTrue(self.con.execute("SELECT 1 FROM settings WHERE k='equity_backfill'").fetchone())

    def test_thread_survives_a_failing_snapshot(self):
        os.environ["SOLANA_PUBLIC_KEY"] = "ADDR"
        n = []

        def boom(addr):
            n.append(1)
            raise OSError("RPC ne radi")
        equity._sol_balance = boom
        equity._usdc_balance = lambda a: 0.0
        equity._pairs = lambda mints: []
        equity._usd_eur_fetch = lambda: None
        th = equity.start(self.path, tick=0.02)
        end = time.time() + 5
        while time.time() < end and len(n) < 3:
            time.sleep(0.02)
        self.assertGreaterEqual(len(n), 3)                        # it keeps trying
        self.assertTrue(th.is_alive())
        equity.stop()
        self.assertEqual(self.rows(), [])

    def test_trade_loop_starts_the_thread_and_never_depends_on_it(self):
        saved = (run_trade.DB, run_trade.follow_league_once, equity.start, signal.getsignal(signal.SIGTERM))
        run_trade.DB = self.path
        calls, passes = [], []

        def one_pass(con, cfg, since, now=None, quiet=False):
            passes.append(1)
            run_trade.STOPPING["flag"] = True

        def start(path=None, tick=None):
            calls.append(path)
            raise RuntimeError("dretva se ne može pokrenuti")
        run_trade.follow_league_once, equity.start = one_pass, start
        try:
            run_trade.cmd_follow(argparse.Namespace(config=None, once=False))
            self.assertEqual((calls, passes), ([self.path], [1]))  # started once; its failure did not stop the loop
            run_trade.STOPPING["flag"] = False
            run_trade.cmd_follow(argparse.Namespace(config=None, once=True))
            self.assertEqual(len(calls), 1)                        # a single pass measures nothing
        finally:
            run_trade.STOPPING["flag"] = False
            run_trade.DB, run_trade.follow_league_once, equity.start = saved[:3]
            signal.signal(signal.SIGTERM, saved[3])


class Backfill(Base):
    def ledger(self):
        """Two real trades before the first measured snapshot: one closed with a profit, one still open."""
        a = self.position("AAA", status="closed", sol_in=0.1, qty=1_000_000, left=0, ts=NOW - 5000)
        b = self.position("BBB", status="open", sol_in=0.2, qty=4_000_000, left=2_000_000, ts=NOW - 3000)
        self.order(NOW - 5000, "buy", a_in=int(0.1 * L), a_out=1_000_000, fee=2_000_000, pid=a)
        self.order(NOW - 4000, "sell", a_in=1_000_000, a_out=int(0.16 * L), fee=1_000_000, pid=a)
        self.order(NOW - 4000, "rent", a_out=2_000_000, fee=-2_000_000, pid=a)          # the same second as the sale
        self.order(NOW - 3500, "buy", status="failed", a_in=int(0.2 * L), fee=0, pid=b)  # moved nothing
        self.order(NOW - 3000, "buy", a_in=int(0.2 * L), a_out=4_000_000, fee=2_000_000, pid=b)
        self.order(NOW - 2000, "sell", a_in=2_000_000, a_out=int(0.07 * L), fee=1_000_000, pid=b)   # half, at a loss
        self.order(NOW - 2500, "buy", status="dry", mode="dry", a_in=int(0.1 * L), a_out=5)        # dry-run: no money

    def test_rebuilds_the_past_from_the_orders(self):
        self.ledger()
        # measured now: 1.0 SOL, the open half of BBB (stake 0.1) worth 0.15 at the market
        first = self.snap(NOW, 1.0, prices={"BBB": (0.075, None)})
        self.assertAlmostEqual(first["flow_sol"], 1.15)           # before the backfill: everything is the opening
        self.assertEqual(equity.backfill(self.con, now=NOW + 1), 5)
        s = equity.series(self.con)
        self.assertEqual([p["src"] for p in s], ["recon"] * 5 + ["live"])
        self.assertEqual([p["ts"] for p in s], [NOW - 5001, NOW - 5000, NOW - 4000, NOW - 3000, NOW - 2000, NOW])
        moved = [-0.102, 0.16 - 0.001 + 0.002, -0.202, 0.07 - 0.001]
        start = 1.0 - sum(moved)
        self.assertAlmostEqual(s[0]["sol"], start)                # walked back from the measured balance
        self.assertAlmostEqual(s[0]["flow_sol"], start)           # the opening deposit moved to the first rebuilt row
        self.assertEqual([p["flow_sol"] for p in s[1:]], [0.0] * 5)
        self.assertEqual([round(p["tokens_sol"], 9) for p in s], [0.0, 0.1, 0.0, 0.2, 0.1, 0.15])   # at cost, then market
        self.assertAlmostEqual(s[0]["pnl_sol"], 0.0)
        self.assertAlmostEqual(s[1]["pnl_sol"], -0.002)           # the buy's network fee
        self.assertAlmostEqual(s[2]["pnl_sol"], -0.002 + 0.06 + 0.001)
        self.assertAlmostEqual(s[4]["pnl_sol"], 0.059 - 0.002 - 0.03 - 0.001)   # realised only
        self.assertAlmostEqual(s[5]["pnl_sol"], s[4]["pnl_sol"] + 0.05)         # the open half at the market
        self.assertAlmostEqual(s[4]["sol"], 1.0)
        self.assertTrue(all(p["sol_usd"] == 150.0 and p["usd_eur"] == 0.9 for p in s))   # the first snapshot's rates
        self.assertEqual([d["kind"] for d in equity.deposits(self.con)], ["pocetni"])

    def test_idempotent(self):
        self.ledger()
        self.snap(NOW, 1.0)
        self.assertEqual(equity.backfill(self.con, now=NOW + 1), 5)
        before = self.rows()
        self.assertEqual(equity.backfill(self.con, now=NOW + 2), 0)
        self.con.execute("DELETE FROM settings WHERE k='equity_backfill'")   # even without its mark
        self.assertEqual(equity.backfill(self.con, now=NOW + 3), 0)
        self.assertEqual(self.rows(), before)
        self.snap(NOW + 300, 1.0)
        self.assertEqual(equity.backfill(self.con, now=NOW + 301), 0)
        self.assertEqual(len(self.rows()), len(before) + 1)

    def test_waits_for_a_measured_snapshot_and_marks_an_empty_past(self):
        self.ledger()
        self.assertEqual(equity.backfill(self.con, now=NOW), 0)   # nothing to anchor on yet
        self.assertFalse(equity._backfilled(self.con))
        self.snap(NOW, 1.0)
        self.assertEqual(equity.backfill(self.con, now=NOW + 1), 5)   # a later call does the work
        self.con.execute("DELETE FROM equity")
        self.con.execute("DELETE FROM settings")
        self.con.execute("DELETE FROM orders")
        self.con.execute("DELETE FROM positions")
        self.con.commit()
        self.snap(NOW, 1.0)
        self.assertEqual(equity.backfill(self.con, now=NOW + 1), 0)   # dry-run history: nothing to rebuild
        self.assertTrue(equity._backfilled(self.con))             # marked, so it is not looked at again
        self.assertEqual(self.rows(), [(NOW, 1.0, 0.0, 0.0, 1.0, "live")])

    def test_orders_alone_cannot_go_below_an_empty_wallet(self):
        """Sales brought 0.5 SOL in, the wallet holds 0.1: something was taken out before the first snapshot."""
        a = self.position("AAA", status="closed", sol_in=0.1, qty=1_000_000, left=0, ts=NOW - 5000)
        self.order(NOW - 5000, "buy", a_in=int(0.1 * L), a_out=1_000_000, pid=a)
        self.order(NOW - 4000, "sell", a_in=1_000_000, a_out=int(0.6 * L), pid=a)
        self.snap(NOW, 0.1)
        self.assertEqual(equity.backfill(self.con, now=NOW + 1), 3)
        s = equity.series(self.con)
        self.assertTrue(all(p["sol"] >= -1e-9 for p in s))
        self.assertAlmostEqual(s[0]["sol"], 0.1)                  # at least the first buy's stake was there
        self.assertAlmostEqual(s[2]["sol"], 0.6)
        self.assertAlmostEqual(s[3]["flow_sol"], -0.5)            # booked as a withdrawal on the measured row
        self.assertAlmostEqual(s[3]["pnl_sol"], 0.5)              # and the trade's profit stays a profit
        self.assertEqual([d["kind"] for d in equity.deposits(self.con)], ["pocetni", "isplata"])

    def test_live_snapshots_after_a_backfill_keep_working(self):
        self.ledger()
        self.snap(NOW, 1.0, prices={"BBB": (0.075, None)})
        equity.backfill(self.con, now=NOW + 1)
        r = self.snap(NOW + 300, 1.4, prices={"BBB": (0.075, None)})
        self.assertAlmostEqual(r["flow_sol"], 0.4)
        s = equity.summary(self.con, now=NOW + 300)
        self.assertAlmostEqual(s["pnl_sol"], equity.series(self.con)[-2]["pnl_sol"])


class Plumbing(Base):
    def test_connect_prepares_the_table_and_never_dies_for_it(self):
        cols = [r[1] for r in self.con.execute("PRAGMA table_info(equity)")]
        self.assertEqual(cols, ["ts", "sol", "usdc", "tokens_sol", "sol_usd", "usd_eur", "flow_sol", "src"])
        saved = equity.ensure

        def full(con):
            raise sqlite3.OperationalError("database or disk is full")
        equity.ensure = full
        try:
            con = executor.connect(os.path.join(self.tmp.name, "drugi.db"))   # the trade loop still gets its connection
            self.assertEqual(con.execute("SELECT COUNT(*) FROM positions").fetchone()[0], 0)
            con.close()
        finally:
            equity.ensure = saved

    def test_ensure_does_not_commit_the_callers_transaction(self):
        self.con.execute("INSERT INTO settings VALUES ('x','1',0,'test')")
        equity.ensure(self.con)
        self.con.rollback()
        self.assertIsNone(self.con.execute("SELECT 1 FROM settings WHERE k='x'").fetchone())

    def test_wallet_address_order_matches_the_page(self):
        """Key (when it can sign), then the address saved on the page, then the env one: ui/pravitrade._addr."""
        self.assertEqual(wallet.addresses(self.con), (None, None, None))
        os.environ["SOLANA_PUBLIC_KEY"] = "ENV"
        self.assertEqual(wallet.addresses(self.con), ("ENV", None, "ENV"))
        self.assertEqual(wallet.addresses(None), ("ENV", None, "ENV"))
        settings.put(self.con, "wallet_pub", "SAVED", "test")
        self.assertEqual(wallet.addresses(self.con), ("SAVED", None, "SAVED"))
        saved = (wallet.can_sign, wallet.address)
        wallet.can_sign, wallet.address = (lambda: True), (lambda: "KEY")
        try:
            self.assertEqual(wallet.addresses(self.con), ("KEY", "KEY", "SAVED"))
            try:
                from ui import pravitrade
            except Exception:  # noqa: BLE001 - the page module is another group's; without it there is nothing to compare
                pravitrade = None
            if pravitrade is not None and hasattr(pravitrade, "_addr"):
                self.assertEqual(pravitrade._addr(self.con), wallet.addresses(self.con))
                wallet.can_sign = lambda: False
                self.assertEqual(pravitrade._addr(self.con), wallet.addresses(self.con))

            def broken():
                raise ValueError("ključ se ne da pročitati")
            wallet.can_sign, wallet.address = (lambda: True), broken
            self.assertEqual(wallet.addresses(self.con), ("SAVED", None, "SAVED"))   # never raises
        finally:
            wallet.can_sign, wallet.address = saved

    def test_snapshot_finds_the_wallet_by_itself(self):
        os.environ["SOLANA_PUBLIC_KEY"] = "ENV"
        seen = []
        r = equity.snapshot(self.con, now=NOW, balance=lambda a: seen.append(a) or 1.0, usdc=lambda a: 0.0,
                            market=lambda m: ({}, 150.0), rates=lambda t: {"sol_usd": 150.0, "usd_eur": 0.9})
        self.assertEqual((seen, r["sol"]), (["ENV"], 1.0))


if __name__ == "__main__":
    unittest.main()
