"""13.11. (owner's order, points 2 and 4):
2. "Slippage na stop i trailing izlazima (~5 % preko triggera) ... smanji ga (brži polling za otvorene pozicije ili
   brže slanje / zaštitni slippage prag pri triggeru) bez gašenja sigurnosnih provjera": the stop and the trailing
   also fire on the newest PumpPortal trade (hype.db live_trades, local), the level / price / feed / age are in
   exit_events, an exit of the real account rings run_trade (trade/wake), run_trade sells first in its pass with a
   protective slippage that falls back to the normal swap at once, and measures every such sale (trade.db exit_fills).
4. "Nativni break-even stop nakon TP1 u exit_plan / set_exit_plan": breakeven_after_tp1 (+ breakeven_buffer_pct).

    python3 -m unittest tests.test_izlazi_1311_offline
"""
import os
import re
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_trade  # noqa: E402
from league import auto, exitplan, store  # noqa: E402
from live import store as live_store  # noqa: E402
from trade import cost, executor, jupiter, settings, wake, wallet  # noqa: E402
from ui import mcpapi  # noqa: E402
from tests.test_pozicije_izlaz_offline import Base, MINT  # noqa: E402

LU, PU = settings.LEAGUE_USER, settings.PAPER_USER
SOL_USD = 100.0
RAW = 30_000_000   # the real position: 30 tokens of 6 decimals


class FakeJup:
    """Jupiter that fills a sell at `fill` USD per token (SOL at SOL_USD); `capped` says what happens to an order sent
    with slippageBps: None = fills, "6001" = lands and fails on slippage, "silent" = never answers after sending."""

    def __init__(self, fill=0.86, capped=None):
        self.fill, self.capped, self.calls, self.sent = fill, capped, [], {}

    def order(self, inp, out, amount, taker=None, route="v2", slippage_bps=None):
        rid = f"r{len(self.calls) + 1}"
        self.calls.append({"route": route, "slip": slippage_bps, "amount": amount})
        lam = int(amount / 1e6 * self.fill / SOL_USD * 1e9) if out == jupiter.SOL else int(amount * 1000)
        self.sent[rid] = (slippage_bps, amount, lam)
        return {"inAmount": str(amount), "outAmount": str(lam), "requestId": rid, "inUsdValue": 100,
                "outUsdValue": 99, "transaction": "dHg=", "taker": taker}

    def execute(self, signed, rid, route="v2"):
        slip, amount, lam = self.sent[rid]
        if slip and self.capped == "6001":
            return {"status": "Failed", "code": 6001, "signature": "SIGF", "error": "slippage"}
        if slip and self.capped == "silent":
            return None
        return {"status": "Success", "signature": "SIG" + rid, "totalInputAmount": str(amount),
                "totalOutputAmount": str(lam)}


class Exits(Base):
    def setUp(self):
        super().setUp()
        exitplan._LAST.clear()
        exitplan.ensure(self.lg)
        self.mode("live")
        settings.put(self.con, "sl_default", 30)
        self.paused = False
        self.hype = os.path.join(self.tmp.name, "hype.db")
        self.jup = FakeJup()
        self.qty = RAW
        for p in (mock.patch.object(exitplan, "paused", lambda: self.paused),
                  mock.patch.object(exitplan, "_sol_usd", lambda: SOL_USD),
                  mock.patch.object(live_store, "HYPE_DB", self.hype),
                  mock.patch.object(executor, "STOP_FILE", os.path.join(self.tmp.name, "STOP")),
                  mock.patch.object(executor, "armed", lambda: True),
                  mock.patch.object(jupiter, "order", lambda *a, **k: self.jup.order(*a, **k)),
                  mock.patch.object(jupiter, "execute", lambda *a, **k: self.jup.execute(*a, **k)),
                  mock.patch.object(wallet, "address", lambda: "WALLET"),
                  mock.patch.object(wallet, "sign", lambda tx, kp=None: "SIGNED"),
                  mock.patch.object(wallet, "token_raw_balance", lambda owner, mint: self.qty),
                  mock.patch.object(wallet, "close_empty", lambda kp, mint: 0),
                  mock.patch.object(wallet, "_keypair", lambda: None),
                  mock.patch.object(run_trade, "_exit_px_inputs", lambda token, live: (SOL_USD, 6)),
                  mock.patch.object(run_trade, "notify", lambda text: self.said.append(text))):
            p.start()
            self.addCleanup(p.stop)
        self.said = []
        executor._CAP_UNSUPPORTED.clear()

    def tearDown(self):
        settings._FLAG_CACHE.clear()
        super().tearDown()

    def mode(self, m):
        settings.put(self.con, "flag:exit_plans", {"mode": m, "since": int(time.time())})
        settings._FLAG_CACHE.clear()

    def lot(self, user=LU, px=1.0, mcap=50_000.0):
        tid = store.buy(self.lg, user, MINT, "HOPE", 30, px, 100_000, "copy KOL x", None, mcap, allow_open=True)
        auto.set_auto(self.lg, user, tid, "tpsl", "+100%", "-30%")
        return tid

    def real(self, lid):
        """The real position that mirrors demo lot `lid` (bought earlier: RAW tokens for 0.3 SOL)."""
        self.con.execute("INSERT INTO positions (league_id, token, symbol, opened_ts, mode, status, reason, sol_in, "
                         "qty_raw, qty_left, sol_back, fees_sol) VALUES (?,?,?,?,?,?,?,?,?,?,0,0)",
                         (lid, MINT, "HOPE", int(time.time()) - 600, "live", "open", "copy KOL x", 0.3, RAW, RAW))
        self.con.commit()

    def market(self, px):
        return lambda toks: {t: (px, 100_000.0, None, 50_000.0 * px) for t in toks}

    def tick(self, px, now=None):
        return exitplan.run_once(self.lg, self.market(px), now or time.time())

    def pp_trade(self, usd, age=1.0, now=None):
        """One PumpPortal trade in hype.db (run_live.py's table) at `usd` per token, `age` seconds ago."""
        now = now or time.time()
        con = live_store.connect(self.hype)
        n = con.execute("SELECT COUNT(*) FROM live_trades").fetchone()[0]
        live_store.add_trades(con, [(f"sig{n}", MINT, "w", "sell", 0.1, 0.1 / (usd / SOL_USD), usd / SOL_USD, None,
                                     "pump-amm", int(now - age), None)])
        con.close()

    def mirror(self, since=None):
        from tests.test_trade_offline import CFG
        cfg = settings.merged(dict(CFG, sell_check=False), self.con)
        run_trade.follow_league_once(self.con, cfg, since=since if since is not None else time.time() + 60,
                                     now=time.time(), quiet=True)

    def open_lots(self, user=LU):
        return self.lg.execute("SELECT COUNT(*) FROM trades WHERE user=? AND token=? AND status='open'",
                               (user, MINT)).fetchone()[0]

    def fills(self):
        self.con.row_factory = None
        cur = self.con.execute("SELECT * FROM exit_fills ORDER BY id")
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


class FreshPrice(Exits):
    """Point 2, the trigger side: the gap opened between the level and the first price the executor saw."""

    def test_the_stop_fires_on_the_fresh_pumpportal_trade_before_the_market_quote_crosses(self):
        self.lot()
        exitplan.set_plan(self.lg, MINT, {"stop": {"at_pct": -12}}, 30)
        self.assertEqual(self.tick(0.95), [])                                    # quote and no fresh trade: above
        self.pp_trade(0.86)                                                      # a sale on chain, 1 s ago
        done = self.tick(0.95)                                                   # the quote still shows 0.95
        self.assertEqual([(d[0], d[2]) for d in done], [(LU, "stop")])
        self.assertRegex(done[0][3], r"razina MC \$44,000 \(cijena -2\.3 % od razine, pumpportal, [12] s\)")
        ev = exitplan.events(self.lg)[0]
        self.assertEqual((ev["trigger"], ev["px_src"]), ("stop", "pumpportal"))
        self.assertAlmostEqual(ev["level_px"], 0.88)
        self.assertAlmostEqual(ev["price"], 0.86)
        self.assertAlmostEqual(ev["mcap"], 43_000.0)
        self.assertGreater(ev["trig_ts"], time.time() - 5)
        self.assertAlmostEqual(self.lg.execute("SELECT exit_px FROM trades WHERE token=?", (MINT,)).fetchone()[0], 0.86)

    def test_a_stale_trade_or_a_bad_print_is_not_used_and_never_fires_a_take_profit(self):
        self.lot()
        exitplan.set_plan(self.lg, MINT, {"take_profits": [{"at_pct": 10, "sell_share": 0.5}],
                                          "stop": {"at_pct": -12}}, 30)
        self.pp_trade(0.80, age=exitplan.FRESH_S + 3)                            # too old
        self.assertEqual(self.tick(0.95), [])
        self.pp_trade(0.30)                                                      # -68 % vs a fresh quote: a bad print
        self.assertEqual(self.tick(0.95), [])
        self.pp_trade(1.30)                                                      # higher: only the quote counts
        self.assertEqual(self.tick(1.05), [])                                    # no TP on the trade's price
        self.assertEqual([d[2] for d in self.tick(1.10)], ["tp1"])               # the quote reaches +10 %
        self.assertEqual(exitplan.events(self.lg)[0]["px_src"], "tržište")

    def test_the_trailing_fires_on_the_fresh_trade_too(self):
        self.lot()
        exitplan.set_plan(self.lg, MINT, {"trailing": {"activate_pct": 10, "trail_pct": 6}}, 30)
        self.assertEqual(self.tick(1.15), [])                                    # active, peak 1.15: level 1.081
        self.pp_trade(1.07)
        done = self.tick(1.12)
        self.assertEqual([d[2] for d in done], ["trailing"])
        ev = exitplan.events(self.lg)[0]
        self.assertAlmostEqual(ev["level_px"], 1.15 * 0.94)
        self.assertAlmostEqual(ev["price"], 1.07)

    def test_the_feed_subscribes_the_real_accounts_lots_and_planned_tokens(self):
        from live import pumpportal
        self.lot()
        other = MINT[:-4] + "wxyz"
        store.buy(self.lg, PU, other, "PAP", 30, 1.0, 100_000, "range lot 1", None, 50_000.0, allow_open=True)
        exitplan.set_plan(self.lg, other, {"stop": {"at_pct": -10}, "accounts": [PU]}, 30)
        miss = os.path.join(self.tmp.name, "nema.db")
        tokens, _w, open_tokens = pumpportal.wanted(paper_db=miss, strat_db=miss, hype_db=miss, kol_db=miss,
                                                    league_db=store.DB)
        self.assertEqual(set(tokens[:2]), {MINT, other})
        self.assertEqual(open_tokens, {MINT, other})                             # kept past the budget, never "hot"


class Wake(Exits):
    """Point 2, the sending side: run_trade hears the exit at once."""

    def test_a_real_account_exit_rings_and_the_nap_ends_at_once_a_paper_exit_does_not(self):
        self.lot(PU)
        exitplan.set_plan(self.lg, MINT, {"stop": {"at_pct": -12}, "accounts": [PU]}, 30)
        s0 = wake.stamp()
        self.assertEqual([d[0] for d in self.tick(0.80)], [PU])
        self.assertEqual(wake.stamp(), s0)                                       # the demo account: no real sale
        self.lot(LU)
        exitplan.set_plan(self.lg, MINT, {"stop": {"at_pct": -12}, "accounts": [LU]}, 30)
        t0 = time.monotonic()
        self.assertEqual([d[0] for d in self.tick(0.80)], [LU])
        self.assertNotEqual(wake.stamp(), s0)
        self.assertTrue(wake.nap(5, since=s0))                                   # rung during the pass: no nap at all
        self.assertLess(time.monotonic() - t0, 1.0)

    def test_the_nap_ends_within_a_step_of_the_ring(self):
        s0 = wake.stamp()
        threading.Timer(0.3, wake.ring, args=("test",)).start()
        t0 = time.monotonic()
        self.assertTrue(wake.nap(5, since=s0))
        self.assertLess(time.monotonic() - t0, 0.3 + wake.STEP_S + 0.25)        # was poll_s (1 s) + the pass
        self.assertFalse(wake.nap(0.2))                                          # nothing rung: the full poll

    def test_the_owners_plan_kill_switch_stops_the_exit_and_the_ring(self):
        self.lot()
        exitplan.set_plan(self.lg, MINT, {"stop": {"at_pct": -12}}, 30)
        self.paused = True
        s0 = wake.stamp()
        self.assertEqual(self.tick(0.80), [])
        self.assertEqual((self.open_lots(), wake.stamp()), (1, s0))


class RealSell(Exits):
    """Point 2: the real sale behind a trigger, its protective slippage and its measurement."""

    def stop_fired(self):
        lid = self.lot()
        self.real(lid)
        exitplan.set_plan(self.lg, MINT, {"stop": {"at_pct": -12}}, 30)
        self.pp_trade(0.87)
        self.assertEqual([d[2] for d in self.tick(0.95)], ["stop"])
        return lid

    def test_the_stop_is_sold_first_with_the_protective_slippage_and_measured(self):
        self.stop_fired()
        self.mirror()
        st, left = self.con.execute("SELECT status, qty_left FROM positions").fetchone()
        self.assertEqual((st, left), ("closed", 0))
        self.assertEqual([c["slip"] for c in self.jup.calls], [int(executor.EXIT_SLIP_CAP_PCT * 100)])
        (f,) = self.fills()
        self.assertEqual((f["trigger"], f["px_src"], f["cap_pct"], f["cap_result"], f["status"], f["mode"]),
                         ("stop", "pumpportal", executor.EXIT_SLIP_CAP_PCT, "ok", "ok", "live"))
        self.assertAlmostEqual(f["level_px"], 0.88)
        self.assertAlmostEqual(f["seen_px"], 0.87)
        self.assertAlmostEqual(f["fill_px"], 0.86, places=4)
        self.assertAlmostEqual(f["slip_level_pct"], (0.86 / 0.88 - 1) * 100, places=2)
        self.assertAlmostEqual(f["slip_seen_pct"], (0.86 / 0.87 - 1) * 100, places=2)
        self.assertGreaterEqual(f["sent_after_s"], 0)
        self.assertLess(f["sent_after_s"], 1.0)                                  # the order went out at once
        self.assertGreaterEqual(f["latency_s"], f["sent_after_s"])
        self.assertTrue(any(re.match(r"izlaz HOPE stop \(plan #1\): razina MC \$44,000, viđeno MC \$43,500 "
                                     r"\(pumpportal, [12] s\), nalog \+0\.\d\d s nakon okidača, ispunjeno MC \$43,000 "
                                     r"\(-2\.3 % od razine, -1\.1 % od viđenog\), gotovo \+\d+\.\d\d s; "
                                     r"zaštitni slippage 3 %: ok$", t) for t in self.said), self.said)
        ev = exitplan.events(self.lg)[0]
        (rf,) = ev["real_sell"]["fills"]
        self.assertEqual(rf["fill_mc"], 43_000)
        self.assertAlmostEqual(rf["slip_vs_level_pct"], f["slip_level_pct"])
        self.mirror()
        self.assertEqual(len(self.fills()), 1)                                   # measured once

    def test_a_capped_try_that_fails_on_slippage_falls_back_to_the_normal_swap_at_once(self):
        self.jup.capped = "6001"
        self.stop_fired()
        self.mirror()
        self.assertEqual(self.con.execute("SELECT status FROM positions").fetchone()[0], "closed")
        self.assertEqual([(c["route"], c["slip"]) for c in self.jup.calls][-1], ("v2", None))
        self.assertIn(300, [c["slip"] for c in self.jup.calls])
        rows = self.con.execute("SELECT status, code FROM orders WHERE side='sell' ORDER BY id").fetchall()
        self.assertEqual(rows[-1], ("ok", 0))
        self.assertIn(("failed", 6001), rows)                                    # the capped try stays in the ledger
        (f,) = self.fills()
        self.assertTrue(f["cap_result"].startswith("pao (") and f["cap_result"].endswith("odmah normalni slippage: ok"),
                        f["cap_result"])

    def test_an_unknown_outcome_is_never_sent_twice(self):
        self.jup.capped = "silent"
        self.stop_fired()
        self.mirror()
        self.assertEqual(self.con.execute("SELECT status FROM positions").fetchone()[0], "open")
        self.assertEqual([c["slip"] for c in self.jup.calls], [300])            # one order, no blind second swap
        self.assertEqual(self.fills(), [])
        self.assertTrue(any("nije prošla" in t for t in self.said), self.said)

    def test_one_capped_try_only_and_a_route_that_does_not_answer_is_not_asked_again(self):
        real_order = self.jup.order

        def order(inp, out, amount, taker=None, route="v2", slippage_bps=None):
            if route == "v2":
                self.jup.calls.append({"route": route, "slip": slippage_bps, "amount": amount})
                raise TimeoutError("v2 down")
            return real_order(inp, out, amount, taker, route, slippage_bps)
        self.jup.order = order
        self.stop_fired()
        self.mirror()
        self.assertEqual(self.con.execute("SELECT status FROM positions").fetchone()[0], "closed")
        self.assertEqual([(c["route"], c["slip"]) for c in self.jup.calls], [("v2", 300), ("ultra", None)])

    def test_a_refused_slippage_parameter_is_not_sent_again(self):
        real_order = self.jup.order

        def order(inp, out, amount, taker=None, route="v2", slippage_bps=None):
            if slippage_bps:
                self.jup.calls.append({"route": route, "slip": slippage_bps, "amount": amount})
                return {"error": "unknown parameter slippageBps", "http_status": 400}
            return real_order(inp, out, amount, taker, route, slippage_bps)
        self.jup.order = order
        self.stop_fired()
        self.mirror()
        self.assertEqual(self.con.execute("SELECT status FROM positions").fetchone()[0], "closed")
        self.assertEqual([(c["route"], c["slip"]) for c in self.jup.calls], [("v2", 300), ("v2", None)])
        self.assertTrue(executor._CAP_UNSUPPORTED.get("v2"))
        (f,) = self.fills()
        self.assertIn("odmah normalni slippage: ok", f["cap_result"])

    def test_safety_checks_hold_kill_switch_blocks_the_buy_not_the_stop_and_no_key_no_swap(self):
        self.stop_fired()
        open(executor.STOP_FILE, "w").close()                                    # the owner's kill switch
        tid = store.buy(self.lg, LU, MINT[:-4] + "abcd", "NEW", 30, 1.0, 100_000, "ručno (pravi trade)", None,
                        60_000.0, allow_open=True)
        settings.put(self.con, "manual_size", {str(tid): 0.05}, "Jure")
        with mock.patch.object(executor, "is_live", lambda cfg: True):
            self.mirror(since=0)
        rows = dict(self.con.execute("SELECT symbol, status FROM positions"))
        self.assertEqual(rows["HOPE"], "closed")                                 # the stop still sells
        self.assertEqual(rows["NEW"], "blocked")
        self.assertIn("kill switch", self.con.execute("SELECT reason FROM positions WHERE symbol='NEW'").fetchone()[0])
        # a real position without the key / TRADE_LIVE: no swap at all, protective slippage or not
        lid = self.lot()
        self.real(lid)
        self.jup.calls.clear()
        exitplan.set_plan(self.lg, MINT, {"stop": {"at_pct": -12}}, 30)
        self.assertEqual([d[2] for d in self.tick(0.80)], ["stop"])
        with mock.patch.object(executor, "armed", lambda: False):
            self.mirror()
        self.assertEqual(self.jup.calls, [])
        self.assertEqual(self.con.execute("SELECT status FROM positions WHERE league_id=?", (lid,)).fetchone()[0], "open")


class BreakEven(Exits):
    """Point 4: after TP1 the rest's stop moves to break-even (entry + cost), never before, never lower."""

    def plan(self, user=LU, **kw):
        p = {"take_profits": [{"at_pct": 10, "sell_share": 0.5}], "stop": {"at_pct": -12},
             "breakeven_after_tp1": True, "accounts": [user]}
        p.update(kw)
        return exitplan.set_plan(self.lg, MINT, p, 30)

    def stop_px(self, user=LU):
        return exitplan.active(self.lg, MINT)["state"]["stop_px"][user]

    def test_validation_and_the_words(self):
        self.lot()
        with self.assertRaisesRegex(ValueError, "needs take_profits"):
            exitplan.set_plan(self.lg, MINT, {"stop": {"at_pct": -12}, "breakeven_after_tp1": True}, 30)
        with self.assertRaisesRegex(ValueError, "nothing is left"):
            exitplan.set_plan(self.lg, MINT, {"take_profits": [{"at_pct": 10, "sell_share": 1}],
                                              "breakeven_after_tp1": True}, 30)
        with self.assertRaisesRegex(ValueError, "goes with breakeven_after_tp1"):
            exitplan.set_plan(self.lg, MINT, {"stop": {"at_pct": -12}, "breakeven_buffer_pct": 2}, 30)
        with self.assertRaisesRegex(ValueError, "not above the break-even"):
            self.plan(breakeven_buffer_pct=10)
        out = self.plan(breakeven_buffer_pct=2)
        self.assertEqual((out["plan"]["breakeven_after_tp1"], out["plan"]["breakeven_buffer_pct"]), (True, 2.0))
        self.assertIn("nakon TP1 stop na break-even (ulaz +2 %)", exitplan.describe(out["plan"]))
        self.assertIn("nakon TP1 stop na break-even (ulaz + trošak)", exitplan.describe(self.plan()["plan"]))
        self.assertEqual(exitplan.denorm(exitplan.active(self.lg, MINT)["plan"])["breakeven_after_tp1"], True)
        d, err = mcpapi._tool("set_exit_plan", {"token_address": MINT, "plan": {
            "take_profits": [{"at_pct": 15, "sell_share": 0.5}], "breakeven_after_tp1": True,
            "breakeven_buffer_pct": 1.5, "reason": "BE nakon TP1"}}, kid="grok")
        self.assertFalse(err, d)
        self.assertIn("break-even", d["summary"])
        tool = next(t for t in mcpapi.TOOLS if t["name"] == "set_exit_plan")
        self.assertIn("breakeven_after_tp1", tool["inputSchema"]["properties"]["plan"]["properties"])
        self.assertIn("breakeven_after_tp1", tool["description"])

    def run_be(self, user):
        self.lot(user)
        self.plan(user, breakeven_buffer_pct=2)
        self.assertAlmostEqual(self.stop_px(user), 0.88)
        self.assertEqual(self.tick(1.05), [])
        self.assertAlmostEqual(self.stop_px(user), 0.88)                         # not before TP1
        done = self.tick(1.10)
        self.assertEqual([d[2] for d in done], ["tp1"])
        self.assertIn("stop na break-even: prosječni ulaz + 2.00 % troška = MC $51,000", done[0][3])
        self.assertAlmostEqual(self.stop_px(user), 1.02)
        ev = exitplan.events(self.lg)
        self.assertEqual([(e["trigger"], e["share"]) for e in ev[:2]], [("breakeven", 0.0), ("tp1", 0.5)])
        self.assertIsNone(ev[0]["real_sell"])
        v = exitplan.view(self.lg, MINT, user, price=1.05)
        self.assertEqual((v["breakeven"]["active"], v["breakeven"]["stop_mc"]), (True, 51_000))
        self.assertTrue(next(t for t in v["triggers"] if t["trigger"] == "stop")["breakeven"])
        self.assertEqual(self.tick(1.03), [])
        done = self.tick(1.015)                                                  # under entry + cost: the rest out
        self.assertEqual([d[2] for d in done], ["stop"])
        self.assertIn("stop (break-even)", done[0][3])
        self.assertEqual(self.open_lots(user), 0)
        self.assertIn("break-even", exitplan.events(self.lg)[0]["note"])

    def test_paper_account(self):
        self.run_be(PU)

    def test_live_account_rings_run_trade_and_the_real_rest_follows(self):
        lid = self.lot()
        self.real(lid)
        self.plan(LU, breakeven_buffer_pct=2)
        self.assertEqual([d[2] for d in self.tick(1.10)], ["tp1"])
        self.mirror()
        st, left = self.con.execute("SELECT status, qty_left FROM positions").fetchone()
        self.assertEqual(st, "open")
        self.assertAlmostEqual(left / RAW, 0.5, places=3)                        # TP1: half of the real position
        self.qty = left
        self.assertAlmostEqual(self.stop_px(), 1.02)
        s0 = wake.stamp()
        self.assertEqual([d[2] for d in self.tick(1.01)], ["stop"])
        self.assertNotEqual(wake.stamp(), s0)
        self.mirror()
        self.assertEqual(self.con.execute("SELECT status FROM positions").fetchone()[0], "closed")
        self.assertEqual([f["trigger"] for f in self.fills()], ["tp1", "stop"])

    def test_default_buffer_is_the_round_trip_cost_and_a_tighter_stop_is_never_lowered(self):
        self.lot()
        self.plan()
        self.tick(1.10)
        exp = 1.0 * (1 + cost.round_trip(30 * 0.5, 100_000.0))
        self.assertAlmostEqual(self.stop_px(), exp)
        self.assertGreater(exp, 1.0)
        be = exitplan.active(self.lg, MINT)["state"]["be"][LU]
        self.assertAlmostEqual(be["buf_pct"], round((exp - 1) * 100, 3))
        # a stop already above break-even stays
        store.sell(self.lg, LU, self.lg.execute("SELECT id FROM trades WHERE status='open'").fetchone()[0], 1.1, 1e5)
        self.lot()
        self.plan(stop={"at_pct": 4})
        self.tick(1.10)
        self.assertAlmostEqual(self.stop_px(), 1.04)
        self.assertIn("već bio viši", exitplan.events(self.lg)[0]["note"])

    def test_tp1_under_the_cost_puts_the_stop_just_under_the_tp1_price(self):
        self.lot()
        self.plan(take_profits=[{"at_pct": 0.2, "sell_share": 0.5}])
        self.assertEqual([d[2] for d in self.tick(1.002)], ["tp1"])
        self.assertAlmostEqual(self.stop_px(), 1.002 * (1 - exitplan.BE_MIN_GAP))
        self.assertIn("TP1 je ispod troška", exitplan.events(self.lg)[0]["note"])
        self.assertEqual(self.tick(1.0), [])                                     # not sold the next second

    def test_a_dca_after_tp1_keeps_break_even_from_the_new_average(self):
        self.lot()
        self.plan(breakeven_buffer_pct=2)
        self.tick(1.10)
        self.lot(px=0.9)
        p = exitplan.extend(self.lg, MINT, 30)
        avg = exitplan._avg(exitplan._lots(self.lg, LU, MINT))
        self.assertAlmostEqual(p["state"]["stop_px"][LU], avg * 1.02)
        self.assertAlmostEqual(p["state"]["be"][LU]["px"], avg * 1.02)


if __name__ == "__main__":
    unittest.main()
