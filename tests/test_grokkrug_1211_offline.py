"""12.11. (owner's order, points 3 and 4).

3. set_exit_plan: time_stop_min + min_profit_pct (out after X min unless at least min_profit_pct NET of the round-trip
   cost, trade/cost.round_trip) and max_stop_pct (a wider stop in the plan is refused; without a stop the plan gets
   -max_stop_pct; sl_default still on top; the owner's typed SL is never limited by it); shown in the UI and MCP.
4. Grok autotrade: more rounds in one token (open, close, open again, DCA lots while the token stays <= dca_token_cap),
   max_round_trips_per_token_day (default 3, the owner's limit on the page), no buy of a token after 2 stop-outs in it
   in a Zagreb day (the next day it passes); refusals in English for MCP, in Croatian on the page and in the log.

    python3 -m unittest tests.test_grokkrug_1211_offline
"""
import io
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import auto, copy, exitplan, store  # noqa: E402
from trade import cost, settings  # noqa: E402
from ui import grokauto, mcpapi, pravitrade  # noqa: E402
from tests.test_pozicije_izlaz_offline import Base, MINT  # noqa: E402

LU = settings.LEAGUE_USER
M2 = MINT[:-1] + "8"
GOOD = (1.0, 30_000.0, None, 82_000.0, "HOPE", {"src": "dex"})


class PlanNew(Base):
    """Point 3: the plan's new fields."""
    def setUp(self):
        super().setUp()
        exitplan._LAST.clear()
        exitplan.ensure(self.lg)
        settings.put(self.con, "flag:exit_plans", {"mode": "live", "since": int(time.time())})
        settings._FLAG_CACHE.clear()
        settings.put(self.con, "sl_default", 30)
        cost.reset_cache()
        p = mock.patch.object(exitplan, "paused", lambda: False)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(settings._FLAG_CACHE.clear)

    def lot(self, px=1.0, mcap=50_000.0, opened=None):
        tid = store.buy(self.lg, LU, MINT, "HOPE", 30, px, 100_000, "copy KOL x", None, mcap, allow_open=True)
        auto.set_auto(self.lg, LU, tid, "tpsl", "+100%", "-30%")
        if opened:
            self.lg.execute("UPDATE trades SET opened_ts=? WHERE id=?", (opened, tid))
            self.lg.commit()
        return tid

    def tick(self, px, now=None):
        with mock.patch("sys.stdout", io.StringIO()):
            return exitplan.run_once(self.lg, lambda toks: {t: (px, 100_000.0, None, 50_000.0 * px) for t in toks},
                                     now or time.time())

    def open_qty(self):
        return sum(r[0] for r in self.lg.execute("SELECT qty FROM trades WHERE user=? AND token=? AND status='open'",
                                                 (LU, MINT)))

    def test_time_stop_min_sells_under_plus_3_net_after_60_min_and_keeps_above(self):
        self.lot(opened=int(time.time()) - 61 * 60)
        out = exitplan.set_plan(self.lg, MINT, {"time_stop_min": 60, "min_profit_pct": 3, "reason": "60 min / +3 %"}, 30)
        self.assertEqual((out["plan"]["time_stop_min"], out["plan"]["min_profit_pct"]), (60.0, 3.0))
        rt = cost.round_trip(30, 100_000)                     # the one cost model: 2 x 1 % fee + 2 x impact
        self.assertAlmostEqual(rt, 0.02 + 2 * 30 / (50_000 + 30))
        self.assertEqual(self.tick(1.10), [])                 # +10 % gross, +7.9 % net: kept
        self.assertEqual(self.tick(1.06), [])                 # +6 % gross, +3.9 % net: kept
        self.assertGreater(self.open_qty(), 0)
        lots = exitplan._lots(self.lg, LU, MINT)
        self.assertAlmostEqual(exitplan.net_pnl_pct(lots, 1.04, 100_000), (0.04 - rt) * 100)
        done = self.tick(1.04)                                # +4 % gross but +1.9 % NET: under +3 % -> out
        self.assertEqual([d[2] for d in done], ["time_stop_min"])
        self.assertEqual(self.open_qty(), 0)
        ev = exitplan.events(self.lg)[0]
        self.assertEqual((ev["trigger"], ev["share"], ev["mode"]), ("time_stop_min", 1.0, "izvršeno"))

    def test_time_stop_min_waits_for_its_minutes_from_the_last_entry(self):
        self.lot(opened=int(time.time()) - 30 * 60)
        exitplan.set_plan(self.lg, MINT, {"time_stop_min": 60, "min_profit_pct": 3}, 30)
        self.assertEqual(self.tick(0.95), [])                 # under +3 %, but only 30 min in
        self.assertEqual([d[2] for d in self.tick(0.95, time.time() + 31 * 60)], ["time_stop_min"])
        with self.assertRaisesRegex(ValueError, "min_profit_pct goes with time_stop_min"):
            self.lot()
            exitplan.set_plan(self.lg, MINT, {"min_profit_pct": 3}, 30)

    def test_max_stop_pct_refuses_a_wider_stop_and_sets_its_own(self):
        self.lot()
        with self.assertRaisesRegex(ValueError, r"-20.0 % from the average entry is wider than max_stop_pct \(-12 %\)"):
            exitplan.set_plan(self.lg, MINT, {"stop": {"at_pct": -20}, "max_stop_pct": 12}, 30)
        with self.assertRaisesRegex(ValueError, "wider than max_stop_pct"):     # an MC stop at -20 %, -12 given
            exitplan.set_plan(self.lg, MINT, {"stop": {"at_mc_usd": 40_000}, "max_stop_pct": -12}, 30)
        with self.assertRaisesRegex(ValueError, "SL −20 % je širi od max_stop_pct −12 % ovog plana"):
            exitplan.validate(self.lg, MINT, {"stop": {"at_pct": -20}, "max_stop_pct": 12}, 30, hr=True)
        with self.assertRaisesRegex(ValueError, "looser than sl_default"):      # sl_default still holds on top
            exitplan.set_plan(self.lg, MINT, {"stop": {"at_pct": -40}, "max_stop_pct": 50}, 30)
        self.assertIsNone(exitplan.active(self.lg, MINT))                         # nothing refused was stored
        out = exitplan.set_plan(self.lg, MINT, {"take_profits": [{"at_pct": 50, "sell_share": 1}],
                                                "max_stop_pct": 12}, 30)
        self.assertAlmostEqual(out["stop_price"][LU], 0.88)                      # no stop given: the plan's own -12 %
        out = exitplan.set_plan(self.lg, MINT, {"stop": {"at_pct": -10}, "max_stop_pct": 12}, 30)
        self.assertAlmostEqual(out["stop_price"][LU], 0.9)
        self.assertEqual([d[2] for d in self.tick(0.89)], ["stop"])

    def test_the_owners_typed_sl_is_never_limited_by_it(self):
        own = exitplan.panel_plan("+30%", "-40%", floor=30, max_stop_pct=12)
        self.assertNotIn("max_stop_pct", own)
        self.assertEqual(own["stop"], {"at_pct": -40.0})
        dflt = exitplan.panel_plan("+30%", "", floor=30, max_stop_pct=12)       # an empty SL: the plan's own stop
        self.assertEqual((dflt["stop"], dflt["max_stop_pct"]), ({"at_pct": -12.0}, 12.0))
        self.assertIn("time_stop", exitplan.panel_plan("+30%", "", time_min=45, floor=30))   # "sve van" unchanged
        net = exitplan.panel_plan("+30%", "", time_min=45, floor=30, min_profit_pct=2)
        self.assertEqual((net["time_stop_min"], net["min_profit_pct"]), (45.0, 2.0))
        self.lot()
        exitplan.set_plan(self.lg, MINT, {"time_stop_min": 60, "min_profit_pct": 3, "max_stop_pct": 12}, 30,
                          client="mcp:grok")
        typed = pravitrade._edit_plan(self.lg, MINT, "+30%", "-40%", exitplan.OWNER_SL_MAX)   # Uredi SL-TP
        self.assertEqual((typed["stop"], typed.get("max_stop_pct")), ({"at_pct": -40.0}, None))
        self.assertEqual((typed["time_stop_min"], typed["min_profit_pct"]), (60, 3.0))     # Grok's time stop stays
        empty = pravitrade._edit_plan(self.lg, MINT, "+30%", "", 30)
        self.assertEqual((empty["stop"], empty["max_stop_pct"]), ({"at_pct": -12.0}, 12.0))

    def test_mcp_schema_takes_the_new_fields_and_ui_and_mcp_show_them(self):
        tool = next(t for t in mcpapi.TOOLS if t["name"] == "set_exit_plan")
        props = tool["inputSchema"]["properties"]["plan"]["properties"]
        self.assertTrue({"time_stop_min", "min_profit_pct", "max_stop_pct"} <= set(props))
        self.assertIn("NET of the round-trip cost", tool["description"])
        self.lot()
        d, err = mcpapi._tool("set_exit_plan", {"token_address": MINT, "plan": {
            "time_stop_min": 60, "min_profit_pct": 3, "max_stop_pct": 12, "reason": "60 min, +3 % neto"}}, kid="grok")
        self.assertFalse(err, d)
        self.assertEqual((d["plan"]["time_stop_min"], d["plan"]["min_profit_pct"], d["plan"]["max_stop_pct"]),
                         (60.0, 3.0, 12.0))
        words = "time stop 60 min ako je ispod +3 % neto · SL najviše −12 %"
        self.assertEqual(d["summary"], words)
        v = exitplan.view(self.lg, MINT, LU, price=1.0)
        self.assertEqual((v["time_stop_min"], v["min_profit_pct"], v["max_stop_pct"]), (60.0, 3.0, 12.0))
        trig = {t["trigger"]: t for t in v["triggers"]}
        self.assertEqual(trig["time_stop_min"]["min_profit_pct_net"], 3.0)
        self.assertLess(trig["time_stop_min"]["net_pnl_pct_now"], 0)            # at the entry: minus the cost
        self.assertAlmostEqual(trig["stop"]["distance_pct"], -12.0)
        self.assertIn(words, exitplan.status(self.lg, MINT)["summary"])         # the Autopilot page's plan line
        d, err = mcpapi._tool("set_exit_plan", {"token_address": MINT, "plan": {"stop": {"at_pct": -20},
                                                                                "max_stop_pct": 12}})
        self.assertTrue(err)
        self.assertIn("wider than max_stop_pct", d["error"])


class Rounds(Base):
    """Point 4: rounds on one token."""
    def setUp(self):
        super().setUp()
        self.mk = {}
        p = [mock.patch.object(copy, "market", lambda toks: {t: self.mk.get(t, GOOD) for t in toks}),
             mock.patch.object(copy, "_rugged", lambda *a: None),
             mock.patch.object(copy, "_concentration", lambda t: (None, "nepoznato")),
             mock.patch.object(grokauto, "TX_WAIT_S", 0.0),
             mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}),
             mock.patch("sys.stdout", io.StringIO())]
        for x in p:
            x.start()
            self.addCleanup(x.stop)
        settings.put(self.con, "max_sol_per_trade", 0.5)
        settings.put(self.con, "size_sol", 0.1)
        self.assertIn("ok=", self.post("/pravi-trade/grokon", {}))

    def ask(self, tok, amount, side="buy"):
        return mcpapi.trade_request({"token": tok, "side": side, "amount": amount, "require_approval": False,
                                     "reason": "Grok: krug"})

    def bought(self, tok=MINT, amount=0.05):
        code, out = self.ask(tok, amount)
        self.assertEqual((code, out["status"]), (200, "executed"), out)
        return out["league_trade_id"]

    def grok_lots(self, tok=MINT):
        return [dict(r) for r in self.lg.execute("SELECT * FROM trades WHERE user=? AND token=? AND status='open' "
                                                 "AND source=?", (LU, tok, grokauto.SRC))]

    def close(self, how, tok=MINT):
        lots = self.grok_lots(tok)
        self.assertTrue(lots)
        if how == "plan_stop":   # the exit plan's own sale (league/exitplan._sell)
            exitplan._sell(self.lg, LU, lots, 1.0, 0.85, 30_000.0, 70_000.0, "plan_stop")
            return
        note, rule, px = {"tp": ("auto TP +15%", "tp", 1.2), "sl": ("auto SL -30%", "sl", 0.7),
                          "time": ("plan izlaza: plan_time_stop_min", "plan_time_stop_min", 0.98)}[how]
        for t in lots:
            store.sell(self.lg, LU, t["id"], px, 30_000.0, note, exit_rule=rule)

    def info(self, tok=MINT, now=None):
        return grokauto.round_info(self.con, self.lg, tok, now)

    def test_third_round_passes_the_fourth_is_refused_and_a_dca_is_no_round(self):
        self.bought()
        self.close("tp")
        self.bought()
        self.bought()                                                             # a DCA lot: the same round
        self.assertEqual((self.info()["rounds_today"], self.info()["open"]), (2, True))
        self.close("time")                                                        # a time stop is no stop-out
        self.bought()                                                             # the third round
        self.close("tp")
        i = self.info()
        self.assertEqual((i["rounds_today"], i["stop_outs_today"], i["open"]), (3, 0, False))
        code, out = self.ask(MINT, 0.05)                                          # the fourth round
        self.assertEqual((code, out["status"]), (409, "rejected"))
        self.assertIn("max_round_trips_per_token_day: 3 rounds in this token today (Zagreb day), at most 3", out["reason"])
        log = grokauto.log_rows(self.con, 1)[0]
        self.assertIn("najviše 3 krugova u istom tokenu u danu", log["why_hr"])
        self.assertIn("odbijeno: najviše 3 krugova", pravitrade._grok_rows([log]))   # the page: Croatian
        self.assertEqual(self.grok_lots(), [])
        # the owner's limit on the page, like Grok's other limits
        self.assertIn("err=", self.post("/pravi-trade/groklimits", {"max_round_trips_per_token_day": "50"}))
        self.assertIn("ok=", self.post("/pravi-trade/groklimits", {"max_round_trips_per_token_day": "4"}))
        self.assertEqual(grokauto.limits(self.con)["max_round_trips_per_token_day"], 4)
        self.assertIn("name=max_round_trips_per_token_day", pravitrade._grok_auto_setup(self.con, True))
        self.bought()
        self.assertIn("max_round_trips_per_token_day", mcpapi.portfolio()["grok_autotrade"]["limits"])

    def test_dca_up_to_the_token_cap_passes_and_over_it_is_refused(self):
        settings.put(self.con, "grok_max_sol_per_day", 1.0)
        ids = [self.bought(amount=0.1) for _ in range(3)]                         # 0.3 SOL in one round
        self.assertEqual(len(self.grok_lots()), 3)
        self.assertEqual((self.info()["rounds_today"], self.info()["open"]), (1, True))
        self.assertAlmostEqual(pravitrade.held_sol_now(self.lg, self.con, MINT), 0.3)   # not mirrored yet: counted
        for amt in (0.1, 0.05):
            code, out = self.ask(MINT, amt)
            self.assertEqual(out["status"], "rejected")
            self.assertIn("dca_token_cap: 0.300 SOL already in this token", out["reason"])
        self.assertIn("najviše 0.3 SOL po tokenu (Grokov limit)", grokauto.log_rows(self.con, 1)[0]["why_hr"])
        with self.assertRaisesRegex(ValueError, "najviše 0.3 SOL po tokenu"):     # an approved request: the same cap
            pravitrade._owner_buy_rules(self.lg, self.con, MINT, 0.1, src=exitplan.APPROVED_SRC)
        for lid in ids:                                                           # run_trade mirrored them: no double count
            self.con.execute("INSERT INTO positions (token, opened_ts, mode, status, reason, sol_in, league_id) "
                             "VALUES (?,?,?,?,?,?,?)", (MINT, int(time.time()), "dry", "open", grokauto.SRC, 0.1, lid))
        self.con.commit()
        self.assertAlmostEqual(pravitrade.held_sol_now(self.lg, self.con, MINT), 0.3)
        self.assertEqual(self.bought(tok=M2, amount=0.1) > 0, True)              # another token is its own cap

    def test_two_stop_outs_block_the_token_today_and_it_passes_tomorrow(self):
        self.bought()
        self.close("sl")                                                          # stop-out 1: the Autopilot's SL
        self.assertEqual(self.info()["stop_outs_today"], 1)
        self.bought()
        self.close("plan_stop")                                                   # stop-out 2: the plan's hard stop
        self.assertEqual(self.info()["stop_outs_today"], 2)
        self.bought(tok=M2)                                                       # per token: another one is fine
        code, out = self.ask(MINT, 0.05)
        self.assertEqual((code, out["status"]), (409, "rejected"))
        self.assertIn("2 stop-outs in this token today (Zagreb day)", out["reason"])
        self.assertIn("izlaza stopom u ovom tokenu danas", pravitrade._grok_rows(grokauto.log_rows(self.con, 1)))
        tomorrow = time.time() + 86400
        self.assertEqual(self.info(now=tomorrow)["stop_outs_today"], 0)
        code, out = grokauto.execute({"token": MINT, "side": "buy", "amount": 0.05, "reason": "sutra"}, now=tomorrow,
                                     wait_s=0)
        self.assertEqual((code, out["status"]), (200, "executed"), out)

    def test_open_close_open_again_after_grok_sold_the_real_position(self):
        lid = self.bought()
        self.con.execute("INSERT INTO positions (token, opened_ts, mode, status, reason, sol_in, league_id) VALUES "
                         "(?,?,?,?,?,?,?)", (MINT, int(time.time()) - 600, "dry", "open", grokauto.SRC, 0.05, lid))
        self.con.commit()
        code, out = self.ask(MINT, 1.0, side="sell")                              # Grok closes it
        self.assertEqual(out["status"], "executed")
        self.con.execute("UPDATE positions SET status='closed', closed_ts=? WHERE league_id=?", (int(time.time()) - 300,
                                                                                              lid))
        self.con.commit()                                                         # run_trade sold it; the demo lot is open
        self.assertEqual(len(self.grok_lots()), 1)
        i = self.info()
        self.assertEqual((i["open"], i["rounds_today"], i["stop_outs_today"]), (False, 1, 0))
        lid2 = self.bought()                                                      # open again: a new round of its own
        self.assertEqual([t["id"] for t in self.grok_lots()], [lid2])
        old = self.lg.execute("SELECT status, exit_rule FROM trades WHERE id=?", (lid,)).fetchone()
        self.assertEqual(tuple(old), ("closed", "manual"))
        i = self.info()
        self.assertEqual((i["open"], i["rounds_today"], i["stop_outs_today"]), (True, 2, 0))


if __name__ == "__main__":
    unittest.main()
