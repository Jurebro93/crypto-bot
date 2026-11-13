"""10.11. ~21:45 (Jure): set_exit_plan (MCP) + the server's exit executor (league/exitplan.py) behind exit_plans.
Every trigger type, partial sales, no loosening of the stop, the stale feed (only the hard stop), the kill switch,
paper vs live, the default TP/SL skipped only while a plan is in force, MCP answers and events.

    python3 -m unittest tests.test_exit_plans_offline
"""
import json
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import auto, exitplan, flags, store  # noqa: E402
from trade import settings  # noqa: E402
from ui import mcpapi  # noqa: E402
from tests.test_pozicije_izlaz_offline import Base, MINT  # noqa: E402

LU, PU = settings.LEAGUE_USER, settings.PAPER_USER


class Plans(Base):
    def setUp(self):
        super().setUp()
        exitplan._LAST.clear()
        exitplan.ensure(self.lg)
        self.mode("live")
        settings.put(self.con, "sl_default", 30)
        p = mock.patch.object(exitplan, "paused", lambda: bool(settings.raw(self.con).get("exit_plans_paused")))
        p.start()
        self.addCleanup(p.stop)

    def mode(self, m):
        settings.put(self.con, "flag:exit_plans", {"mode": m, "since": int(time.time())})
        settings._FLAG_CACHE.clear()

    def lot(self, user=LU, px=1.0, mcap=50_000.0, sl="-30%", opened=None):
        tid = store.buy(self.lg, user, MINT, "HOPE", 30, px, 100_000, "copy KOL x", None, mcap, allow_open=True)
        auto.set_auto(self.lg, user, tid, "tpsl", "+100%", sl)
        if opened:
            self.lg.execute("UPDATE trades SET opened_ts=? WHERE id=?", (opened, tid))
            self.lg.commit()
        return tid

    def mk(self, px):
        return lambda toks: {t: (px, 100_000.0, None, 50_000.0 * px) for t in toks}

    def tick(self, px, now=None):
        return exitplan.run_once(self.lg, self.mk(px), now or time.time())

    def open_qty(self, user=LU):
        return sum(r[0] for r in self.lg.execute("SELECT qty FROM trades WHERE user=? AND token=? AND status='open'",
                                                 (user, MINT)))

    # ---------- validation ----------
    def test_validation_shares_stop_floor_tighten_only_and_open_position(self):
        with self.assertRaisesRegex(ValueError, "no open Autopilot position"):
            exitplan.set_plan(self.lg, MINT, {"stop": {"at_pct": -20}}, 30)
        self.lot()
        with self.assertRaisesRegex(ValueError, "at most 1"):
            exitplan.set_plan(self.lg, MINT, {"take_profits": [{"at_pct": 20, "sell_share": 0.6},
                                                               {"at_pct": 50, "sell_share": 0.5}]}, 30)
        with self.assertRaisesRegex(ValueError, "looser than sl_default"):
            exitplan.set_plan(self.lg, MINT, {"stop": {"at_pct": -40}}, 30)
        out = exitplan.set_plan(self.lg, MINT, {"stop": {"at_pct": -20}, "reason": "stegni"}, 30)
        self.assertEqual(out["replaced"], "the position's default TP/SL")
        with self.assertRaisesRegex(ValueError, "only be tightened"):
            exitplan.set_plan(self.lg, MINT, {"stop": {"at_pct": -25}}, 30)
        out2 = exitplan.set_plan(self.lg, MINT, {"stop": {"at_mc_usd": 45_000}}, 30)   # -10 %: tighter
        self.assertEqual(out2["replaced"]["plan_id"], out["plan_id"])
        self.assertAlmostEqual(out2["stop_price"][LU], 0.9)
        with self.assertRaisesRegex(ValueError, "empty plan"):
            exitplan.set_plan(self.lg, MINT, {"reason": "x"}, 30)

    def test_mcp_tool_logs_in_applied_suggestions_with_the_client(self):
        self.lot()
        d, err = mcpapi._tool("set_exit_plan", {"token_address": MINT, "plan": {
            "take_profits": [{"at_mc_usd": 75_000, "sell_share": 0.5}], "reason": "pola na 75k"}}, kid="grok")
        self.assertFalse(err, d)
        self.assertEqual(d["flag_mode"], "live")
        log = settings.raw(self.con)["applied_log"][0]
        self.assertEqual((log["key"], log["client"], log["old"]), (f"exit_plan:{MINT}", "mcp:grok", "the position's default TP/SL"))
        d, err = mcpapi._tool("set_exit_plan", {"token_address": MINT, "plan": {"stop": {"at_pct": -50}}})
        self.assertTrue(err)
        self.assertIn("sl_default", d["error"])

    # ---------- triggers ----------
    def test_take_profit_sells_its_share_once(self):
        self.lot()
        exitplan.set_plan(self.lg, MINT, {"take_profits": [{"at_mc_usd": 75_000, "sell_share": 0.5},
                                                           {"at_pct": 100, "sell_share": 0.25}]}, 30)
        q0 = self.open_qty()
        self.assertEqual(self.tick(1.4), [])
        done = self.tick(1.5)                                                    # 75k
        self.assertEqual([d[2] for d in done], ["tp1"])
        self.assertAlmostEqual(self.open_qty(), q0 * 0.5)
        self.assertEqual(self.tick(1.6), [])                                     # tp1 never twice
        self.assertEqual([d[2] for d in self.tick(2.0)], ["tp2"])                # 0.25 of the original
        self.assertAlmostEqual(self.open_qty(), q0 * 0.25)
        ev = exitplan.events(self.lg)
        self.assertEqual([(e["trigger"], e["share"], e["mode"]) for e in ev], [("tp2", 0.25, "izvršeno"), ("tp1", 0.5, "izvršeno")])

    def test_trailing_from_the_peak_after_activation(self):
        self.lot()
        exitplan.set_plan(self.lg, MINT, {"trailing": {"activate_pct": 20, "trail_pct": 15}}, 30)
        self.assertEqual(self.tick(1.1), [])
        self.assertEqual(self.tick(1.25), [])                                    # active, peak 1.25
        self.assertEqual(self.tick(1.4), [])                                     # peak 1.4 -> sell under 1.19
        self.assertEqual(self.tick(1.2), [])
        self.assertEqual([d[2] for d in self.tick(1.18)], ["trailing"])
        self.assertEqual(self.open_qty(), 0)

    def test_hard_stop_and_time_stop(self):
        self.lot()
        exitplan.set_plan(self.lg, MINT, {"stop": {"at_pct": -20}}, 30)
        self.assertEqual([d[2] for d in self.tick(0.79)], ["stop"])
        self.lot(opened=int(time.time()) - 100 * 60)
        exitplan.set_plan(self.lg, MINT, {"time_stop": {"after_min": 90, "if_pnl_below_pct": 5}}, 30)
        self.assertEqual(self.tick(1.10), [])                                    # +10 %: kept
        self.assertEqual([d[2] for d in self.tick(1.02)], ["time_stop"])

    def test_time_stop_counts_from_the_last_entry(self):
        self.lot(opened=int(time.time()) - 100 * 60)
        self.lot()                                                               # a DCA lot just now
        exitplan.set_plan(self.lg, MINT, {"time_stop": {"after_min": 90, "if_pnl_below_pct": 5}}, 30)
        self.assertEqual(self.tick(1.0), [])

    # ---------- safety ----------
    def test_stale_feed_fires_only_the_hard_stop(self):
        self.lot()
        exitplan.set_plan(self.lg, MINT, {"take_profits": [{"at_pct": 50, "sell_share": 0.5}], "stop": {"at_pct": -20}}, 30)
        now = time.time()
        exitplan._LAST[MINT] = (1.6, 80_000.0, 1e5, now - 120)                  # the last quote is 2 min old
        self.assertEqual(exitplan.run_once(self.lg, lambda toks: {}, now), [])  # no TP on a stale price
        exitplan._LAST[MINT] = (0.7, 35_000.0, 1e5, now - 120)
        with mock.patch("ui.paper.jup_prices", lambda toks: {}):
            done = exitplan.run_once(self.lg, lambda toks: {}, now)
        self.assertEqual([d[2] for d in done], ["stop"])
        self.assertEqual(exitplan.events(self.lg)[0]["stale"], 1)

    def test_kill_switch_pauses_plans_and_the_default_tp_sl_is_back(self):
        self.lot()
        exitplan.set_plan(self.lg, MINT, {"take_profits": [{"at_pct": 50, "sell_share": 1}]}, 30)
        self.assertEqual(exitplan.in_force_tokens(self.lg, LU), {MINT})
        from ui import pravitrade
        _, body = pravitrade.page({}, "Jure")
        self.assertIn("Pauziraj exit planove", body)
        self.assertLess(body.index("id=pozicije"), body.index("id=exit-planovi"))
        self.assertEqual(auto.fast_once(self.lg, self.mk(2.5), LU), [])          # the plan owns the exit
        settings.put(self.con, "exit_plans_paused", True)
        self.assertEqual(self.tick(1.6), [])
        self.assertEqual(exitplan.in_force_tokens(self.lg, LU), set())
        self.assertEqual(len(auto.fast_once(self.lg, self.mk(2.5), LU)), 1)      # default TP +100 % sells
        # the page switch
        self.assertIn("ok=", self.post("/pravi-trade/exitresume", {}))
        self.assertFalse(settings.raw(self.con)["exit_plans_paused"])

    def test_paper_executes_on_the_demo_account_only(self):
        self.mode("paper")
        self.lot(LU)
        self.lot(PU)
        exitplan.set_plan(self.lg, MINT, {"stop": {"at_pct": -20}}, 30)
        done = self.tick(0.75)
        self.assertEqual(sorted((d[0], d[2]) for d in done), sorted([(LU, "stop"), (PU, "stop")]))
        self.assertGreater(self.open_qty(LU), 0)                                 # real account: logged only
        self.assertEqual(self.open_qty(PU), 0)
        self.assertEqual({e["user"]: e["mode"] for e in exitplan.events(self.lg)}, {LU: "sjena", PU: "izvršeno"})
        self.assertEqual(len(flags.shadow_rows(self.lg, "exit_plans")), 1)
        self.mode("off")
        self.assertEqual(exitplan.in_force_tokens(self.lg, PU), set())

    # ---------- reading ----------
    def test_portfolio_view_and_exit_events_tool(self):
        self.lot()
        exitplan.set_plan(self.lg, MINT, {"take_profits": [{"at_mc_usd": 75_000, "sell_share": 0.5}],
                                          "stop": {"at_pct": -20}, "trailing": {"activate_pct": 20, "trail_pct": 15}}, 30)
        self.tick(1.3)
        v = exitplan.view(self.lg, MINT, LU, mcap=60_000)
        self.assertEqual(v["peak_mc_since_entry"], 65_000)
        trig = {t["trigger"]: t for t in v["triggers"]}
        self.assertAlmostEqual(trig["tp1"]["distance_pct"], 25.0)
        self.assertAlmostEqual(trig["stop"]["distance_pct"], round((0.8 / 1.2 - 1) * 100, 2))
        self.assertIn("trailing", trig)
        self.tick(1.5)
        d, err = mcpapi._tool("get_exit_events", {"since_ts": 0})
        self.assertFalse(err)
        self.assertEqual(d["events"][0]["trigger"], "tp1")
        names = [t["name"] for t in mcpapi.TOOLS]
        self.assertIn("set_exit_plan", names)
        self.assertIn("get_exit_events", names)


if __name__ == "__main__":
    unittest.main()
