"""11.11. (owner: "Plan izlaza uz kupnju: DA. Kad ručna ili autotrade kupnja ima TP/SL/trailing/time stop u panelu,
server uz kupnju odmah postavi exit plan i taj plan se STVARNO izvršava na pravom računu (exit_plans live za te
pozicije). Stop nikad ne smije biti širi od sl_default. U kartici pozicije jasno prikaži 'plan aktivan (live)' ili
'samo paper'."):

  * a buy with exit fields (TP / SL / trailing % / time stop) sets the position's PANEL plan in the same request
    (ui/pravitrade._buy_plan, league/exitplan.panel_plan); under exit_plan_live it executes on the real account
    (league/exitplan.panel_live) and run_trade mirrors every sale into the real position;
  * a buy without any exit field: the old behaviour (the owner's default stop on the lot, no plan);
  * a stop looser than sl_default (the owner's sl_default: exitplan.sl_floor) refuses the buy,
    the Uredi SL-TP save and a Grok autotrade buy before anything is written;
  * DCA: the same fields keep the plan (its state, the stop from the new average); new fields replace it;
  * the kill switch stops a panel plan; the page and get_portfolio_status say live / paper / shadow and why.
No network.

    python3 -m unittest tests.test_plan_uz_kupnju_offline
"""
import io
import json
import os
import sys
import time
import unittest
from unittest import mock
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_trade  # noqa: E402
from league import auto, exitplan, store  # noqa: E402
from trade import executor, settings  # noqa: E402
from ui import apterm, grokauto, mcpapi, pravitrade  # noqa: E402
from tests.test_pozicije_izlaz_offline import Base, LIVE_ROW, MINT  # noqa: E402
from tests.test_grok_autotrade_offline import Grok as GrokBase  # noqa: E402

LU = settings.LEAGUE_USER


class PlanBase(Base):
    def setUp(self):
        super().setUp()
        from tests.test_trade_offline import FakeJup
        from trade import jupiter
        exitplan._LAST.clear()
        exitplan.ensure(self.lg)
        # 11.11.: the floor is the owner's sl_default alone (no other cap); these tests run with his default at 30
        settings.put(self.con, "sl_default", 30)
        self.mode("exit_plan_live", "live")
        self.live = True   # the Autopilot is live (switch + key); the gate's RPC is not asked here
        for p in (mock.patch.object(executor, "is_live", lambda cfg: self.live),
                  mock.patch.object(pravitrade, "_gate_now", lambda tcon, sol, token, now=None: None),
                  # 11.11.: the owner's buy reads every gate reason at once (_gate_all); no RPC here either
                  mock.patch.object(pravitrade, "_gate_all", lambda tcon, sol, token, now=None, balance=True: [])):
            p.start()
            self.addCleanup(p.stop)
        self.fake = FakeJup()
        self._jup = (jupiter.order, jupiter.execute)
        jupiter.order, jupiter.execute = self.fake.order, self.fake.execute

    def tearDown(self):
        from trade import jupiter
        jupiter.order, jupiter.execute = self._jup
        settings._FLAG_CACHE.clear()
        super().tearDown()

    def mode(self, name, m):
        settings.put(self.con, f"flag:{name}", {"mode": m, "since": int(time.time())})
        settings._FLAG_CACHE.clear()

    def buy(self, **kw):
        form = {"token": MINT, "sol": "0,05", "exit": "tpsl", "tp": "", "sl": ""}
        form.update(kw)
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            loc = unquote(self.post("/pravi-trade/buy", form))
        self.log = out.getvalue()
        return loc

    def price(self, px):
        """The market at px x the first entry (entry 1.0 at MC $82k)."""
        from ui import league as uleague, prijedlog
        uleague.market = lambda toks: {t: (px, 1e6, None, 82_000.0 * px) for t in toks}
        prijedlog.live_market = lambda toks, fetch=None: {t: {**LIVE_ROW, "price": px, "mcap": 82_000.0 * px} for t in toks}

    def tick(self, px, now=None):
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            done = exitplan.run_once(self.lg, lambda toks: {t: (px, 1e6, None, 82_000.0 * px) for t in toks},
                                     now or time.time())
        self.log = out.getvalue()
        return done

    def mirror(self, now=None):
        """run_trade's mirror of the demo trades, as a dry run (no key here: never a real swap or an RPC call); the
        shares it buys and sells are the live mirror's (run_trade.follow_league_once is the same for both modes)."""
        from tests.test_trade_offline import CFG
        cfg = settings.merged(dict(CFG, sell_check=False), self.con)
        live, self.live = self.live, False
        try:
            run_trade.follow_league_once(self.con, cfg, since=0, now=now or time.time(), quiet=True)
        finally:
            self.live = live

    def lots(self):
        return store.trades(self.lg, LU, "open")

    def real(self):
        return self.con.execute("SELECT status, qty_raw, qty_left FROM positions WHERE token=? ORDER BY id",
                                (MINT,)).fetchall()


class BuyWithExit(PlanBase):
    def test_tp_sl_trailing_time_set_a_live_plan_and_the_executor_sells_the_real_lot(self):
        loc = self.buy(tp="15%", sl="-10%", trail="8", time="45")
        self.assertIn("ok=", loc)
        self.assertIn("Plan izlaza #1: TP1 +15 % pola · trailing 8 % · SL −10 % · time stop 45 min (live).", loc)
        self.assertIn("plan izlaza #1 HOPE (panel, live): TP1 +15 % pola · trailing 8 % · SL −10 % · time stop 45 min",
                      self.log)
        p = exitplan.active(self.lg, MINT)
        self.assertEqual(p["client"], "panel: ručna kupnja")
        self.assertTrue(p["client"].startswith(exitplan.PANEL_SRC))
        pl = p["plan"]
        self.assertEqual(pl["take_profits"], [{"kind": "pct", "v": 15.0, "sell_share": 0.5}])
        self.assertEqual(pl["trailing"], {"activate_pct": 15.0, "trail_pct": 8.0})
        self.assertEqual(pl["stop"], {"kind": "pct", "v": -10.0})
        self.assertEqual(pl["time_stop"], {"after_min": 45.0, "if_pnl_below_pct": 1000})
        self.assertEqual(pl["accounts"], [LU])
        (t,) = self.lots()
        self.assertEqual((json.loads(t["auto"])["tp_in"], json.loads(t["auto"])["sl_in"]), ("15%", "-10%"))
        # the plan replaces the lot's own TP/SL in the 1-s and the 20-s loops and executes on the real account
        self.assertEqual(exitplan.in_force_tokens(self.lg, LU), {MINT})
        self.assertEqual(exitplan.execution(LU, exitplan._lots(self.lg, LU, MINT), plan=p)["mode"], "live")
        self.mirror()
        (st, q, ql), = self.real()
        self.assertEqual((st, ql), ("open", q))
        self.assertEqual(self.tick(1.10), [])
        self.assertEqual(auto.fast_once(self.lg, lambda toks: {t: (1.16, 1e6, None, 95_000.0) for t in toks}, LU), [])
        done = self.tick(1.16)                                                     # TP1 +15 %: half
        self.assertEqual([(d[0], d[2]) for d in done], [(LU, "tp1")])
        self.assertIn("(pravi-trade, pravi račun, live): tp1, prodano 50% pozicije", done[0][3])
        self.assertNotIn("sjena", done[0][3] + self.log)
        (t,) = self.lots()
        self.mirror(time.time() + 1)
        (st, q, ql), = self.real()                                                 # the real lot: exactly half sold
        self.assertEqual(st, "open")
        self.assertAlmostEqual(ql / q, 0.5, places=3)
        self.assertEqual(self.tick(1.30), [])                                      # the peak after the activation
        done = self.tick(1.19)                                                     # -8 % from 1.30: trailing
        self.assertEqual([d[2] for d in done], ["trailing"])
        self.assertEqual(self.lots(), [])
        self.mirror(time.time() + 2)
        self.assertEqual(self.real()[0][0], "closed")                              # the real lot is sold too
        ev = exitplan.events(self.lg)
        self.assertEqual([(e["trigger"], e["mode"], e["note"]) for e in reversed(ev)],
                         [("tp1", "izvršeno", "exit_plan_live"), ("trailing", "izvršeno", "exit_plan_live")])

    def test_stop_and_time_stop_execute_on_the_real_account(self):
        self.assertIn("ok=", self.buy(tp="50%", sl="-10%"))
        self.assertEqual(exitplan.active(self.lg, MINT)["plan"]["take_profits"][0]["sell_share"], 1.0)   # no trailing: all
        done = self.tick(0.89)
        self.assertEqual([(d[0], d[2]) for d in done], [(LU, "stop")])
        self.assertEqual(self.lots(), [])
        exitplan._LAST.clear()
        self.assertIn("ok=", self.buy(tp="50%", time="45"))                       # SL empty: the plan's default
        p = exitplan.active(self.lg, MINT)
        self.assertEqual(p["plan"]["stop"], {"kind": "pct", "v": -30.0})
        self.assertEqual(self.tick(1.0, time.time() + 44 * 60), [])
        done = self.tick(1.0, time.time() + 46 * 60)
        self.assertEqual([d[2] for d in done], ["time_stop"])

    def test_a_buy_without_any_exit_field_keeps_the_old_behaviour(self):
        loc = self.buy()
        self.assertIn("ok=", loc)
        self.assertNotIn("Plan izlaza", loc)
        self.assertIsNone(exitplan.active(self.lg, MINT))
        (t,) = self.lots()
        self.assertEqual(json.loads(t["auto"])["sl"], "-30%")                     # the owner's default stop (30 here)
        self.assertEqual(exitplan.in_force_tokens(self.lg, LU), set())
        loc = self.buy(exit="smart")                                              # Smart sell: no plan either
        self.assertIsNone(exitplan.active(self.lg, MINT))
        self.assertIn("err=", self.buy(exit="smart", trail="8"))                  # trailing only with "moj TP/SL"

    def test_a_proposals_kupi_and_an_approved_grok_request_are_live_too(self):
        from ui import mcpapi as mapi
        code, out = mapi.trade_request({"token": MINT, "side": "buy", "amount": 0.05})
        self.assertEqual(code, 202)
        settings.put(self.con, "last_exit", {"tp": "20%", "sl": "-15%"})
        with mock.patch("sys.stdout", io.StringIO()):
            loc = unquote(self.post("/pravi-trade/mcpok", {"id": out["id"]}))
        self.assertIn("ok=", loc)
        p = exitplan.active(self.lg, MINT)
        self.assertEqual(p["client"], "panel: Grok odobreno")
        self.assertEqual(exitplan.status(self.lg, MINT)["plan_mode"], "live")


class StopNeverLooser(PlanBase):
    def test_the_floor_is_the_owners_sl_default_alone(self):
        settings.put(self.con, "sl_default", 60)                    # his Pravila default: -40 % is within it
        self.assertEqual(exitplan.sl_floor(settings.merged(executor.load_config(), self.con)), 60.0)
        settings.put(self.con, "sl_default", 25)
        self.assertEqual(exitplan.sl_floor(settings.merged(executor.load_config(), self.con)), 25.0)
        self.assertEqual(exitplan.DEFAULT_PLAN_SL, 30.0)            # Grok's default plans keep the -30 % they ran with

    def written(self):
        return (self.lots(), self.lg.execute("SELECT COUNT(*) FROM exit_plans").fetchone()[0],
                settings.raw(self.con).get("manual_size") or {})

    def test_the_floor_follows_the_owners_default(self):
        cfg = settings.merged(executor.load_config(), self.con)
        self.assertEqual((cfg["sl_default"], exitplan.sl_floor(cfg)), (30, 30.0))
        self.assertEqual(exitplan.sl_floor({"sl_default": 20}), 20.0)
        self.assertEqual(exitplan.sl_floor({"sl_default": 70}), 70.0)          # 11.11.: no other cap
        self.assertEqual(exitplan.sl_floor(), 30.0)                               # read from trade.db
        settings.put(self.con, "sl_default", 20)
        self.assertEqual(exitplan.sl_floor(), 20.0)

    def test_the_owners_typed_sl_overrides_the_default_an_empty_one_takes_it(self):
        # 11.11. (owner: "Ako ja ručno prilikom kupovine postavim drugačiji stop loss nego što je zadan, onda znači da to
        # želim napraviti samo za tu kupovinu. I tada ručno uvijek nadjačava ono što je zapisano programski")
        loc = self.buy(tp="30%", sl="-70%")
        self.assertIn("ok=", loc)
        self.assertEqual(exitplan.active(self.lg, MINT)["plan"]["stop"], {"kind": "pct", "v": -70.0})
        loc = self.buy(tp="40%", sl="")                                           # empty: the default (-30 %)
        self.assertIn("ok=", loc)
        self.assertEqual(exitplan.active(self.lg, MINT)["plan"]["stop"], {"kind": "pct", "v": -30.0})

    def test_a_buy_order_at_a_market_cap_keeps_the_owners_stop(self):
        loc = unquote(self.post("/pravi-trade/buy", {"token": MINT, "sol": "0,05", "at": "$50k", "exit": "tpsl",
                                                     "tp": "30%", "sl": "-40%", "trail": "8"}))
        self.assertIn("ok=", loc)                                                  # 11.11.: the owner's own stop
        settings.put(self.con, "buy_orders", [])
        loc = unquote(self.post("/pravi-trade/buy", {"token": MINT, "sol": "0,05", "at": "$50k", "exit": "tpsl",
                                                     "tp": "30%", "sl": "-20%", "trail": "8", "time": "60"}))
        self.assertIn("ok=", loc)
        (o,) = settings.raw(self.con)["buy_orders"]
        self.assertEqual((o["trail"], o["time"]), (8.0, 60.0))                    # they go with the order's buy
        bought = []
        pravitrade.limit_once(self.con, live_fn=lambda toks: {MINT: {"mcap": 49_000.0}},
                              buy_fn=lambda con, tcon, form, user: bought.append(form))
        self.assertEqual((bought[0]["trail"], bought[0]["time"]), (8.0, 60.0))

    def test_uredi_sltp_with_a_looser_stop_is_refused_and_a_good_one_sets_the_panel_plan(self):
        self.assertIn("ok=", self.buy(tp="30%", sl="-10%", trail="8"))
        self.mirror()
        pid = self.con.execute("SELECT id FROM positions WHERE token=?", (MINT,)).fetchone()[0]
        before = (exitplan.active(self.lg, MINT)["id"], self.lots()[0]["auto"])
        with mock.patch("sys.stdout", io.StringIO()):
            loc = unquote(self.post("/pravi-trade/exit", {"id": str(pid), "tp": "40%", "sl": "-45%"}))
        self.assertIn("ok=", loc)                                                 # 11.11.: the owner's typed stop holds
        self.assertEqual(exitplan.active(self.lg, MINT)["plan"]["stop"], {"kind": "pct", "v": -45.0})
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            loc = unquote(self.post("/pravi-trade/exit", {"id": str(pid), "tp": "40%", "sl": "-20%"}))
        self.assertIn("ok=", loc)
        p = exitplan.active(self.lg, MINT)
        self.assertEqual(p["client"], "panel: Uredi SL-TP")
        self.assertEqual(p["plan"]["stop"], {"kind": "pct", "v": -20.0})
        self.assertEqual(p["plan"]["trailing"], {"activate_pct": 40.0, "trail_pct": 8.0})   # its trailing stays
        self.assertEqual(p["plan"]["take_profits"][0]["sell_share"], 0.5)
        self.assertIn("HOPE (panel, live): TP1 +40 % pola · trailing 8 % · SL −20 %", out.getvalue())
        self.assertEqual(json.loads(self.lots()[0]["auto"])["sl_in"], "-20%")


class Dca(PlanBase):
    def test_the_same_fields_keep_the_plan_new_ones_replace_it(self):
        self.assertIn("ok=", self.buy(tp="15%", sl="-10%", trail="8"))
        p1 = exitplan.active(self.lg, MINT)
        self.assertEqual([d[2] for d in self.tick(1.16)], ["tp1"])               # half out
        # the same fields (the panel shows the position's exit for a dokup): the plan covers the new lot
        self.price(1.12)
        loc = self.buy(tp="15%", sl="-10%", trail="8")
        self.assertIn("Dokupnja HOPE", loc)
        self.assertIn(f"Plan izlaza #{p1['id']} pokriva i novi ulaz", loc)
        p = exitplan.active(self.lg, MINT)
        self.assertEqual(p["id"], p1["id"])
        self.assertEqual(p["state"]["fired"], {LU: [0]})                          # TP1 stays fired
        lots = exitplan._lots(self.lg, LU, MINT)
        self.assertEqual(len(lots), 2)
        avg = exitplan._avg(lots)
        self.assertAlmostEqual(p["state"]["stop_px"][LU], avg * 0.9)              # -10 % from the NEW average
        # new fields: a new plan for the whole position, from the new average; the lots get them too
        loc = self.buy(tp="40%", sl="-20%")
        self.assertIn("novi izlaz vrijedi za cijelu poziciju", loc)
        p2 = exitplan.active(self.lg, MINT)
        self.assertNotEqual(p2["id"], p1["id"])
        self.assertEqual(p2["plan"]["stop"], {"kind": "pct", "v": -20.0})
        lots = exitplan._lots(self.lg, LU, MINT)
        self.assertEqual(len(lots), 3)
        self.assertAlmostEqual(p2["state"]["stop_px"][LU], exitplan._avg(lots) * 0.8)
        self.assertEqual({json.loads(t["auto"])["tp_in"] for t in lots}, {"40%"})
        # 11.11.: a dokup with the owner's own looser stop: his, a new plan for the whole position
        loc = self.buy(tp="40%", sl="-35%")
        self.assertIn("ok=", loc)
        self.assertEqual(len(exitplan._lots(self.lg, LU, MINT)), 4)
        self.assertEqual(exitplan.active(self.lg, MINT)["plan"]["stop"], {"kind": "pct", "v": -35.0})
        p3 = exitplan.active(self.lg, MINT)
        # a DCA order (no fields): the plan covers the lot (the owner's -35 % stop kept, not refused)
        self.assertIn("pokriva i novi ulaz", self.buy())
        self.assertEqual(exitplan.active(self.lg, MINT)["id"], p3["id"])

    def test_the_owners_dokup_keeps_a_live_grok_plan_live(self):
        # a Grok autotrade position with Grok's own plan (live through grok_live while autotrade is on)
        grokauto.set_on(self.con, True, "Jure")
        tid = store.buy(self.lg, LU, MINT, "HOPE", 25, 1.0, 1e6, grokauto.SRC, None, 82_000.0)
        auto.set_auto(self.lg, LU, tid, "tpsl", "+20%", "-15%")
        exitplan.set_plan(self.lg, MINT, {"take_profits": [{"at_pct": 20, "sell_share": 1}], "stop": {"at_pct": -15},
                                          "accounts": [LU]}, 30, client="mcp:grok")
        self.assertEqual(exitplan.status(self.lg, MINT)["plan_mode"], "live")
        loc = self.buy(tp="20%", sl="-15%")                                       # the owner adds, same exit
        self.assertIn("pokriva i novi ulaz", loc)
        p = exitplan.active(self.lg, MINT)
        self.assertTrue(p["client"].startswith("panel: dokup (bio mcp:grok)"))    # still live: now the owner's
        self.assertEqual(exitplan.status(self.lg, MINT)["plan_mode"], "live")
        self.assertEqual(exitplan.in_force_tokens(self.lg, LU), {MINT})


class KillSwitchAndLabels(PlanBase):
    def test_the_kill_switch_stops_a_panel_plan_and_the_lots_tp_sl_holds(self):
        self.assertIn("ok=", self.buy(tp="15%", sl="-10%", trail="8"))
        self.post("/pravi-trade/exitpause", {})
        self.assertTrue(exitplan.paused())
        self.assertEqual(exitplan.in_force_tokens(self.lg, LU), set())
        self.assertEqual(self.tick(1.16), [])                                     # the plan does nothing
        st = exitplan.status(self.lg, MINT)
        self.assertEqual((st["plan_mode"], st["reason"]),
                         ("paper", "planovi izlaza su pauzirani (kill switch): vrijedi TP/SL pozicije"))
        done = auto.fast_once(self.lg, lambda toks: {t: (1.16, 1e6, None, 95_000.0) for t in toks}, LU)
        self.assertEqual(len(done), 1)                                            # the lot's own TP +15 % (all of it)
        self.post("/pravi-trade/exitresume", {})

    def view(self, mode="live"):
        self.con.execute("UPDATE positions SET mode=?", (mode,))
        self.con.commit()
        cfg = pravitrade._cfg(self.con)
        (p,) = apterm.positions_data(self.con, cfg, live={MINT: {"mcap": 82_000.0}})
        return p, apterm.plan_html(p["plan"])

    def test_live_and_paper_labels_with_the_reason(self):
        self.assertIn("ok=", self.buy(tp="15%", sl="-10%", trail="8", time="45"))
        self.mirror()
        p, html = self.view()
        self.assertEqual(p["plan"]["plan_mode"], "live")
        self.assertIn('class="apx-plan live up" data-plan=live><b>plan aktivan (live)</b> · TP1 +15 % pola · trailing 8 % '
                      '· SL −10 % · time stop 45 min', html)
        self.assertEqual(p["fields"], {"tp": "15%", "sl": "-10%", "trail": 8.0, "time": 45.0})
        _p, html = self.view("dry")
        self.assertIn("<b>samo paper</b> · pozicija je demo (paper): bez pravog novca", html)
        self.live = False
        _p, html = self.view()
        self.assertIn("<b>samo paper</b> · Autopilot nije live", html)
        self.live = True
        self.mode("exit_plan_live", "off")
        _p, html = self.view()
        self.assertIn("<b>samo paper</b> · exit_plan_live nije live", html)
        self.mode("exit_plan_live", "live")
        # a plan that is not from the panel (Grok's MCP plan on the owner's position): in the shadow
        exitplan.set_plan(self.lg, MINT, {"stop": {"at_pct": -10}, "accounts": [LU]}, 30, client="mcp:grok")
        p, html = self.view()
        self.assertEqual(p["plan"]["plan_mode"], "shadow")
        self.assertIn("<b>samo paper</b> · plan u sjeni: pozicija je bez plana iz panela", html)
        self.assertEqual(exitplan.in_force_tokens(self.lg, LU), set())            # the lot's own TP/SL holds
        # the row and the panel's "Tvoja pozicija" carry it
        _, body = pravitrade.page({"m": MINT}, "Jure")
        card = body.split("id=apx-mypos", 1)[1].split("<div class=apx-wal>", 1)[0]
        self.assertIn("data-plan=shadow><b>samo paper</b>", card)
        self.assertIn("data-plan=shadow><b>samo paper</b>", body.split("id=poz-", 1)[1])

    def test_get_portfolio_status_says_plan_mode_and_why(self):
        self.assertIn("ok=", self.buy(tp="15%", sl="-10%"))
        self.mirror()
        self.con.execute("UPDATE positions SET mode='live'")
        self.con.commit()
        modes = mcpapi._plan_modes([MINT], {MINT}, True)
        self.assertEqual(modes[MINT]["plan_mode"], "live")
        self.assertEqual(modes[MINT]["summary"], "TP1 +15 % sve · SL −10 %")
        modes = mcpapi._plan_modes([MINT], set(), True)
        self.assertEqual((modes[MINT]["plan_mode"], modes[MINT]["reason"]), ("paper", "pozicija je demo (paper): bez pravog novca"))
        with mock.patch.object(pravitrade, "equity_data", lambda tcon, now=None: {"summary": {}}):
            d = mcpapi.portfolio()
        (g,) = d["open_positions"]
        self.assertEqual((g["plan_mode"], g["plan_summary"]), ("live", "TP1 +15 % sve · SL −10 %"))
        self.assertIn("exit_plan_live", g["plan_reason"])
        self.assertEqual(d["exit_plans"]["live_stop_limit_pct"], -30.0)
        desc = next(t for t in mcpapi.TOOLS if t["name"] == "get_portfolio_status")["description"]
        self.assertIn("plan_mode live | paper | shadow", desc)

    def test_the_panel_has_trailing_and_time_stop_fields_and_shows_a_positions_exit(self):
        _, body = pravitrade.page({}, "Jure")
        buy = body.split("id=apx-buy", 1)[1].split("</form>", 1)[0]
        self.assertIn('<input name=trail value="" placeholder="—"', buy)
        self.assertIn('<input name=time value="" placeholder="—"', buy)
        self.assertNotIn("ručna kupnja ga nema", body)
        self.assertNotIn("disabled", buy)
        self.assertIn('placeholder="zadano -30%"', buy)                         # the plan's default stop
        self.assertIn("ok=", self.buy(tp="15%", sl="-10%", trail="8", time="45"))
        self.mirror()
        apterm.reset()
        _, body = pravitrade.page({"m": MINT}, "Jure")
        buy = body.split("id=apx-buy", 1)[1].split("</form>", 1)[0]
        for k in ('<input name=tp value="15%"', '<input name=sl value="-10%"', '<input name=trail value="8"',
                  '<input name=time value="45"', "Dokup u HOPE: polja pokazuju izlaz pozicije"):
            self.assertIn(k, buy)
        js = apterm.static_asset("ap.js")[0].decode("utf-8")
        self.assertIn("const tr = $('[data-trail]', f), tt = $('[data-time]', f);", js)
        self.assertNotIn("ova kupnja ga ne postavlja", js)


class EnsureLivePlans(PlanBase):
    def test_the_default_plan_reads_the_owners_stop_never_looser_than_before(self):
        # until 11.11. ts.merged(tcon) failed (no config) and every default plan got -30 % whatever the owner set
        tid = store.buy(self.lg, LU, MINT, "HOPE", 25, 1.0, 1e6, exitplan.APPROVED_SRC, None, 82_000.0)
        auto.set_auto(self.lg, LU, tid, "tpsl", "+20%", "-60%")
        settings.put(self.con, "sl_default", 20)
        with mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(exitplan.ensure_live_plans(self.lg, log=lambda s: None), [MINT])
        self.assertEqual(exitplan.active(self.lg, MINT)["plan"]["stop"], {"kind": "pct", "v": -20.0})
        self.lg.execute("UPDATE exit_plans SET status='replaced'")
        self.lg.commit()
        settings.put(self.con, "sl_default", 60)
        exitplan.ensure_live_plans(self.lg, log=lambda s: None)
        self.assertEqual(exitplan.active(self.lg, MINT)["plan"]["stop"], {"kind": "pct", "v": -30.0})   # the cap


class GrokAutotrade(GrokBase):
    def setUp(self):
        super().setUp()
        exitplan._LAST.clear()
        exitplan.ensure(self.lg)
        settings.put(self.con, "flag:exit_plan_live", {"mode": "live", "since": int(time.time())})
        settings.put(self.con, "sl_default", 30)   # 11.11.: the floor is the owner's sl_default alone
        settings._FLAG_CACHE.clear()
        p = mock.patch.object(executor, "is_live", lambda cfg: True)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        settings._FLAG_CACHE.clear()
        super().tearDown()

    def test_its_tp_sl_become_a_live_plan_and_its_limits_stay(self):
        limits0 = dict(grokauto.LIMITS)
        self.assertIn("ok=", self.post("/pravi-trade/grokon", {}))
        with mock.patch("sys.stdout", io.StringIO()):
            code, out = self.ask(MINT, 0.1)
        self.assertEqual((code, out["status"]), (200, "executed"))
        p = exitplan.active(self.lg, MINT)
        self.assertEqual(p["client"], "panel: Grok autotrade")
        self.assertEqual(p["plan"]["take_profits"], [{"kind": "pct", "v": 15.0, "sell_share": 1.0}])   # tp_default
        self.assertEqual(p["plan"]["stop"], {"kind": "pct", "v": -30.0})          # the plan's default stop
        self.assertEqual(exitplan.status(self.lg, MINT)["plan_mode"], "live")
        grokauto.set_on(self.con, False, "Jure")                                  # its own switch off: the plan
        self.assertEqual(exitplan.in_force_tokens(self.lg, LU), {MINT})           # still protects the position
        # Grok's limits are untouched: 0,1 / 0,3 / 3 / 0,15
        self.assertEqual(grokauto.LIMITS, limits0)
        self.assertEqual(grokauto.limits(self.con), {"grok_max_sol_per_trade": 0.1, "grok_max_sol_per_day": 0.3,
                                                     "grok_max_open": 3, "grok_max_loss_day": 0.15})

    def test_a_looser_stop_from_the_owners_last_exit_gives_grok_the_default(self):
        # 11.11.: Grok's buy takes the owner's last exit; a stop looser than the default is the program's, so Grok's
        # stop is the default (-30 %), never looser, and the buy is not refused for it
        self.post("/pravi-trade/grokon", {})
        settings.put(self.con, "last_exit", {"tp": "30%", "sl": "-60%"})
        with mock.patch("sys.stdout", io.StringIO()):
            code, out = self.ask(MINT, 0.1)
        self.assertEqual(out["status"], "executed")
        self.assertEqual(exitplan.active(self.lg, MINT)["plan"]["stop"], {"kind": "pct", "v": -30.0})


if __name__ == "__main__":
    unittest.main()
