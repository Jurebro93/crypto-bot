"""23.11. (vlasnik: "Ok, kreni da najviše dvije pozicije mogu biti otvorene, ali ako se zatvore, otvori dvije nove ...
sa uključenim 4% fijem kojeg plaćamo za tradeove. Tako da pazite kad se zatvara da bi profit postojao."), offline:
the owner switch pravi_novac_risk_off (trade/settings.RISKOFF_SWITCH, veliki/riskoff.py).

  - off (default): in risk_off the real account is refused exactly as before; the exception's code is never asked
  - on and every condition true: one real daily-range entry of 0.1 SOL, tagged, cost >= 4 %, through run_trade's real
    path (fake swap); each failing condition refuses with its reason; at most 2 open, a new one after one closes
  - exits: voluntary profit exits under +1 % net (4 % cost) hold, stops act, the macro risk_off exit does not close it
  - only the owner's confirmed tap turns it on (plus his one-time order of 23.11., inert unless called); the council
    cannot apply it; the demo is unchanged

    python3 -m unittest tests.test_riskoff_iznimka_offline
"""
import os
import re
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests import test_demo_uvijek_offline as du  # noqa: E402
from tests.test_pravi_novac_sve_offline import LU, PU, tok  # noqa: E402
from league import store as lstore  # noqa: E402
from trade import executor, settings  # noqa: E402
from veliki import gate, live, makro, riskoff, rule  # noqa: E402

H = 3600
RS = settings.RISKOFF_SWITCH


def snap(now, chg=6.3, age=60, regime="risk_off"):
    return {"regime": regime, "why": "volumen meme platformi -38 %", "ts": now - age,
            "sector": {"mcap": 1e10, "mcap_chg24": chg}}


class Base(du.Intra):
    def setUp(self):
        super().setUp()
        riskoff._S.update(on=None, why=None, ref={}, held={})
        live.ensure(self.lg)
        self.snap = snap(self.now)
        p = mock.patch.object(makro, "current", lambda now=None, **k: self.snap)
        p.start()
        self.addCleanup(p.stop)

    def tap(self):
        settings.set_flag(self.con, RS, "live", "Jure", tap=True)
        settings._FLAG_CACHE.clear()

    def tick(self, now=None, mk=None):
        live._ST["tick"] = 0.0
        live._ST.pop("univ_q", None)
        return live.tick(self.lg, mk or (lambda ts: self.mk(ts)), now=now or self.now, force=True)

    def real(self):
        return [dict(zip(("token", "size_sol", "rt", "gate", "gate_info", "be_px", "entry_px", "tp_px", "status"), r))
                for r in self.lg.execute("SELECT token, size_sol, rt, gate, gate_info, be_px, entry_px, tp_px, status "
                                         "FROM veliki_trades WHERE user=? ORDER BY id", (LU,))]

    def open_real(self, i):
        self.lg.execute("INSERT INTO veliki_trades (user, token, symbol, opened_ts, size_sol, size_usd, entry_px, tp_px, "
                        "stop_px, rt, drt, status, kind, first_px, be_px, trail, half_frac) VALUES "
                        "(?,?,?,?,?,?,?,?,?,?,?,'open','intra',?,?,0,0)",
                        (LU, tok(i), f"X{i}", int(self.now - 600), 0.1, 15.0, 1e-4, 9e-4, 1e-5, 0.04, 0.03, 1e-4, 1.1e-4))
        self.lg.commit()


for _n in [n for n in dir(du.Intra) if n.startswith("test_")]:
    setattr(Base, _n, None)   # the parent's own tests run in their module


class Off(Base):
    def test_switch_off_is_todays_behaviour(self):
        with mock.patch.object(riskoff, "mode_refusal", side_effect=AssertionError("asked")):
            out = self.tick()
        self.assertEqual(self.real(), [])
        self.assertEqual(self.swaps, [])
        self.assertFalse(riskoff.active())
        self.assertFalse([x for x in out if "risk-off iznimka" in x], out)
        self.assertEqual(settings.flag(RS, con=self.con), "off")
        demo = self.lg.execute("SELECT gate FROM veliki_trades WHERE user=?", (PU,)).fetchall()
        self.assertTrue(demo and all(g[0] == live.GATE_MAKRO for g in demo))
        with mock.patch.object(riskoff, "active", lambda: False):
            self.assertIn("pravi novac bez novih ulaza", live.enter(self.lg, LU, tok(31), self.mk([tok(31)])[tok(31)],
                                                                    self.now, 150.0, self.z, {}, kind="intra")[1])


class On(Base):
    def test_all_true_one_tagged_real_entry_through_the_real_path(self):
        self.tap()
        out = self.tick()
        rows = self.real()
        self.assertEqual(len(rows), 1, out)
        r = rows[0]
        self.assertEqual((r["token"], r["size_sol"], r["gate"], r["gate_info"]), (tok(31), 0.1, None, riskoff.TAG))
        self.assertGreaterEqual(r["rt"], 0.04)
        self.assertAlmostEqual(r["be_px"], r["entry_px"] * 1.01 / (1 - r["rt"]))
        self.assertGreaterEqual(r["tp_px"] / r["entry_px"] * (1 - r["rt"]) - 1, 0.03)
        self.assertTrue(any("[risk-off iznimka" in x for x in out), out)
        self.assertTrue(riskoff.active())
        src = self.lg.execute("SELECT source FROM trades WHERE user=?", (LU,)).fetchone()[0]
        self.assertIn("[risk-off iznimka]", src)
        self.assertEqual(executor.strategy_label(src), "veliki risk-off iznimka")
        # the demo is unchanged: every demo candidate entered, tagged with the gate
        demo = self.lg.execute("SELECT gate FROM veliki_trades WHERE user=?", (PU,)).fetchall()
        self.assertGreaterEqual(len(demo), 4)
        self.assertTrue(all(g[0] == live.GATE_MAKRO for g in demo))
        # run_trade's real path (fake swap): 0.1 SOL, the source carries the tag
        self.mirror()
        p = self.pos(tok(31))
        self.assertIsNotNone(p)
        self.assertEqual(p[0], "open", p)
        self.assertIn("risk-off iznimka", p[2])
        self.assertAlmostEqual(p[3], 0.1)
        self.assertEqual(len(self.swaps), 1)
        self.assertEqual(self.swaps[0]["lamports"], int(0.1 * 1e9))
        line = riskoff.line(self.lg, self.now, self.con)
        self.assertTrue(line.startswith("veliki risk-off iznimka: UKLJUČENA (vlasnik "), line)
        self.assertIn("pravi novac smije do 2 pozicije po 0,1 SOL; BTC normalno, meme sektor +6.3 % 24 h; otvoreno 1 "
                      "od 2", line.replace("0.1 SOL", "0,1 SOL"))
        rep = live.report_line(self.lg, self.now)
        self.assertIn("pravi risk-off iznimka: ukupno n=0", rep)

    def refused(self, why):
        out = self.tick()
        self.assertEqual(self.real(), [], out)
        got = (riskoff._S.get("why") or "") + " | " + " ".join(riskoff._S["ref"])
        self.assertIn(why, got)

    def test_btc_falling(self):
        self.tap()
        st = live.btc_state(self.now)
        fake = mock.Mock(wraps=st["crash_obj"])
        fake.chg = lambda t, hours=4: -0.012
        with mock.patch.object(live, "btc_state", lambda now=None: dict(st, crash_obj=fake)):
            self.refused("BTC pada")

    def test_btc_free_fall_is_never_the_exception(self):
        self.assertEqual(riskoff.mode_refusal([live.GATE_MAKRO, live.GATE_BTC], {}, {}, self.now),
                         f"prekidač {RS} isključen")
        self.tap()
        self.assertEqual(riskoff.mode_refusal([live.GATE_MAKRO, live.GATE_BTC], {}, {}, self.now), "BTC slobodan pad")
        self.assertEqual(riskoff.btc_refusal({"known": False}, self.now), "BTC cijena nepoznata")
        self.assertEqual(riskoff.btc_refusal({"known": True, "crash": True, "state": "slobodan_pad"}, self.now),
                         "BTC slobodan pad")

    def test_sector_down_unknown_stale(self):
        self.tap()
        for s, why in ((snap(self.now, chg=-0.4), "Solana meme sektor -0.4 %"),
                       (snap(self.now, chg=None), "Solana meme sektor nepoznat"),
                       (snap(self.now, age=4 * H), "makro snimka stara")):
            with self.subTest(why=why):
                self.snap = s
                riskoff._S.update(ref={})
                live._ST.pop("ro_why", None)
                self.refused(why)

    def test_token_under_15m(self):
        self.tap()
        mk = lambda ts: {t: (1.0e-4, 2_000_000.0, "https://dexscreener.com/solana/raydium",
                             1e7 if t == tok(31) else 5e7, "X", {"m5": 0.0}) for t in ts}
        out = self.tick(mk=mk)
        self.assertEqual(self.real(), [], out)
        self.assertTrue(any(k.startswith("MC") and "izvan" in k for k in riskoff._S["ref"]), riskoff._S["ref"])
        self.assertTrue(riskoff.active())

    def test_two_open_then_one_closes(self):
        self.tap()
        self.open_real(40)
        self.open_real(41)
        self.tick()
        self.assertEqual([r["token"] for r in self.real()], [tok(40), tok(41)])
        self.assertTrue(any("već N otvorene prave midcap pozicije" in k for k in riskoff._S["ref"]), riskoff._S["ref"])
        self.lg.execute("UPDATE veliki_trades SET status='closed', closed_ts=?, ret=0.02, pnl_usd=0.3 WHERE token=?",
                        (int(self.now), tok(40)))
        self.lg.commit()
        self.tick(now=self.now + 900)
        self.assertEqual([r["token"] for r in self.real() if r["status"] == "open"], [tok(41), tok(31)])
        live._ST.pop("bar15", None)
        self.assertIn("najviše 2", live.enter(self.lg, LU, tok(32), self.mk([tok(32)])[tok(32)], self.now + 1000,
                                              150.0, self.z, {"tp": 10.0}, kind="intra",
                                              meta=("p", "d"))[1])

    def test_wallet_kill_day_loss_pause(self):
        self.tap()
        self.con.execute("CREATE TABLE IF NOT EXISTS equity (ts INTEGER, sol REAL, usdc REAL, tokens_sol REAL, "
                         "sol_usd REAL, usd_eur REAL, flow_sol REAL, src TEXT)")
        self.con.execute("INSERT INTO equity VALUES (?,?,?,?,?,?,?,?)", (int(self.now - 60), 0.6, 0.0, 0.2, 150.0, 0.9,
                                                                        0.0, "live"))
        self.con.commit()
        self.refused("vrijednost novčanika")
        self.con.execute("DELETE FROM equity")
        self.con.commit()
        open(executor.STOP_FILE, "w").close()
        live._ST.pop("ro_why", None)
        self.refused("kill switch")
        os.remove(executor.STOP_FILE)
        self.live_rows(6, reason="veliki: x", status="closed", closed=int(self.now - 10), sol_back=0.0)
        live._ST.pop("ro_why", None)
        self.refused("dnevni gubitak")
        self.con.execute("DELETE FROM positions")
        self.con.commit()
        settings.pauza_set(self.con, True, "Jure", "test")
        live._ST.pop("ro_why", None)
        self.refused("pauza od 19.11.")

    def test_target_and_cost_floor(self):
        self.assertEqual(riskoff.rt_of(0.02), 0.04)
        self.assertEqual(riskoff.rt_of(0.05), 0.05)
        self.assertIsNone(riskoff.target_refusal(1.0, 1.08, 0.04))           # +3.7 % net
        self.assertIn("treba barem +3%", riskoff.target_refusal(1.0, 1.06, 0.04))
        self.assertEqual(riskoff.cfg({"pravi_novac_risk_off": {"trosak": 0.01, "min_neto": 0.05}})["trosak"], 0.04)
        self.assertEqual(riskoff.cfg({"pravi_novac_risk_off": {"min_neto": 0.05}})["min_neto"], 0.05)


class Exits(Base):
    def row(self, user=LU, tag=riskoff.TAG, peak=None, stop=0.8, be=None, t=50):
        tid = lstore.buy(self.lg, user, tok(t), "EX", 15.0, 1.0, 2e6, "veliki: test", None, 5e7)
        be = be or (riskoff.lock_px(1.0, 0.04) if tag else rule.be_price(1.0, 0.04, {"exit_slip": 0.0}))
        cur = self.lg.execute(
            "INSERT INTO veliki_trades (user, token, symbol, opened_ts, trade_id, size_sol, size_usd, entry_px, tp_px, "
            "stop_px, rt, drt, liq, status, kind, first_px, be_px, trail, half_frac, peak, gate_info, lots) VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,'open','intra',?,?,?,?,?,?,1)",
            (user, tok(t), "EX", int(self.now - 600), tid, 0.1, 15.0, 1.0, 1.10, stop, 0.04, 0.03, 2e6, 1.0, be, 0.05,
             0.0, peak, tag))
        self.lg.commit()
        return live.open_rows(self.lg)[[r["id"] for r in live.open_rows(self.lg)].index(cur.lastrowid)]

    def manage(self, r, px, ctx=None):
        c = ctx or {"btc_state": "normalno", "macro": None}
        with mock.patch.object(live, "context", lambda t, now: dict(c)), \
                mock.patch.object(live, "full_tp", lambda now: (True, "x")):
            return live.manage(self.lg, r, (px, 2e6, "u", 5e7), 1, self.now, live.cfg_now())

    def status(self, r):
        return self.lg.execute("SELECT status, reason, ret FROM veliki_trades WHERE id=?", (r["id"],)).fetchone()

    def test_trailing_under_one_percent_holds_above_closes(self):
        r = self.row(peak=1.12)
        self.manage(r, 1.05)                                   # trailing level 1.064; +0.8 % net at 4 %: held
        self.assertEqual(self.status(r)[0], "open")
        out = self.manage(r, 1.06)                             # +1.8 % net: closes
        st = self.status(r)
        self.assertEqual(st[:2], ("closed", "trail"))
        self.assertAlmostEqual(st[2], 1.06 * 0.96 - 1, places=6)
        self.assertIn(f"({1.06 * 0.96 - 1:+.1%}", out[-1])     # the logged "pravim troškom" uses the 4 % cost

    def test_demo_row_trailing_closes_as_before(self):
        r = self.row(user=PU, tag=None, peak=1.12)
        self.manage(r, 1.05)
        self.assertEqual(self.status(r)[:2], ("closed", "trail"))

    def test_stops_always_act(self):
        r = self.row()
        self.manage(r, 0.79)
        self.assertEqual(self.status(r)[:2], ("closed", "stop"))

    def test_macro_risk_off_does_not_close_it_but_a_normal_real_row(self):
        ctx = {"btc_state": "normalno", "macro": "risk_off"}
        r = self.row()
        self.manage(r, 1.03, ctx)                              # +(-1.1 %) net: no makro_zastita for the exception
        self.assertEqual(self.status(r)[0], "open")
        self.lg.execute("UPDATE veliki_trades SET status='closed' WHERE id=?", (r["id"],))
        r2 = self.row(tag=None, t=51)
        self.lg.execute("UPDATE veliki_trades SET rt=0.01 WHERE id=?", (r2["id"],))
        r2["rt"] = 0.01
        self.manage(r2, 1.03, ctx)
        self.assertEqual(self.status(r2)[:2], ("closed", "makro_zastita"))

    def test_btc_profit_protection_needs_one_percent(self):
        r = self.row()
        pos = live.pos_of(r)
        self.assertFalse(riskoff.exit_ok(r, pos, 1.045, "btc_zastita", self.now))
        self.assertTrue(riskoff.exit_ok(r, pos, 1.06, "btc_zastita", self.now))
        for reason in ("stop", "be", "btc_rez", "rug", "likvidnost", "los", "volumen", "tp"):
            self.assertTrue(riskoff.exit_ok(r, pos, 0.9, reason, self.now), reason)
        self.assertTrue(riskoff.exit_ok(dict(r, gate_info=None), pos, 1.0, "trail", self.now))

    def test_break_even_is_a_one_percent_lock_armed_at_five_percent_net(self):
        r = self.row()
        self.assertAlmostEqual(r["be_px"] * (1 + live.row_cfg(r)["be_at"]), 1.05 / 0.96)
        self.assertAlmostEqual(r["be_px"] * 0.96 - 1, 0.01)


class Switch(Base):
    def test_only_the_owners_confirmed_tap(self):
        for who, tap in (("Jure", False), ("grok", True), ("asistent (Primijeni)", True)):
            with self.assertRaises(ValueError):
                settings.set_flag(self.con, RS, "live", who, tap=tap)
        settings.pauza_set(self.con, True, "Jure", "19.11.")
        self.assertEqual(settings.flag(settings.VEL_SWITCH, con=self.con), "off")
        settings.set_flag(self.con, RS, "live", "Jure", tap=True)
        self.assertEqual(settings.flag(RS, con=self.con), "live")
        self.assertEqual(settings.flag(settings.VEL_SWITCH, con=self.con), "live")   # the same tap
        self.assertIsNone(settings.pauza(self.con))                                    # ends the pause
        self.assertIn(RS, settings.REAL_SWITCHES)
        self.assertIn("Uključuje i 'midcap raspon' pravim novcem i skida pauzu od 19.11.", settings.RISKOFF_CONFIRM)
        settings.set_flag(self.con, RS, "off", "Jure")                                 # off: nothing else moves
        self.assertEqual(settings.flag(settings.VEL_SWITCH, con=self.con), "live")

    def test_the_page_needs_the_confirmation_field(self):
        from ui import pravitrade
        loc = pravitrade.post("/pravi-trade/flag", {"name": RS, "mode": "live"}, "Jure")
        self.assertIn("err=", loc)
        self.assertEqual(settings.flag(RS, con=self.con), "off")
        loc = pravitrade.post("/pravi-trade/flag", {"name": RS, "mode": "live", "potvrda": "1"}, "Jure")
        self.assertIn("ok=", loc)
        self.assertEqual(settings.flag(RS, con=self.con), "live")
        self.assertIn("err=", pravitrade.post("/pravi-trade/flag", {"name": RS, "mode": "off"}, "Ivan"))

    def test_ui_row(self):
        from ui import apjed
        h = apjed._riskoff_row(self.con, True)
        self.assertIn("Uključuje i &#x27;midcap raspon&#x27; pravim novcem i skida pauzu od 19.11.", h)
        self.assertIn("name=potvrda value=0", h)
        self.assertIn("4 %", h)
        v = apjed._riskoff_row(self.con, False)
        self.assertNotIn("<form", v)

    def test_no_code_path_sets_it_on(self):
        """Grep: the flag row is written only by set_flag and by the owner's one-time order of 23.11.; tap=True is
        passed nowhere but the page's handler (from his confirmation field)."""
        hits, taps = [], []
        for d, _ds, fs in os.walk(ROOT):
            if any(x in d for x in (os.sep + ".git", os.sep + "tests", "__pycache__")):
                continue
            for f in fs:
                if not f.endswith(".py"):
                    continue
                p = os.path.join(d, f)
                with open(p, encoding="utf-8", errors="replace") as fh:
                    src = fh.read()
                rel = os.path.relpath(p, ROOT)
                for m in re.finditer(r"set_flag\([^)]*(RISKOFF_SWITCH|pravi_novac_risk_off)", src):
                    hits.append(rel)
                if re.search(r"set_flag\([^)]*tap\s*=\s*True", src):
                    taps.append(rel)
                if re.search(r"flag:\{?RISKOFF_SWITCH|flag:pravi_novac_risk_off", src):
                    hits.append(rel + ":put")
        self.assertEqual(sorted(set(hits)), ["trade/settings.py:put"])
        self.assertEqual(taps, [])
        # the one-time order is not wired into any start yet (only the owner can decide that)
        for f in ("run_trade.py", "ui/pravitrade.py", "ui/assistnotes.py"):
            with open(os.path.join(ROOT, f), encoding="utf-8") as fh:
                self.assertNotIn("riskoff_order_2311", fh.read())

    def test_owner_chat_orders_cannot(self):
        from ui import assistnotes
        with mock.patch.object(assistnotes, "OWNER_FLAG_ORDERS", ((RS, "live", "test"),)):
            try:
                assistnotes.owner_flag_orders(self.con)
            except Exception:  # noqa: BLE001
                pass
        self.assertEqual(settings.flag(RS, con=self.con), "off")

    def test_the_council_cannot_apply_it(self):
        from vijece import odluka
        for pc in ({"flag": RS, "mode": "live"}, {"key": f"flag:{RS}", "to": "live"}, {"name": RS}):
            self.assertEqual(odluka.klasa(pc), "pravi_novac")

    def test_stanja_registry(self):
        from stanja import ploca, registar
        self.assertEqual(tuple(n for n, _w in ploca.REAL_SWITCHES), settings.REAL_SWITCHES)
        self.assertIn("risk_off", registar.BY_KEY["real_money_switch"].store)


class Order2311(Base):
    """The owner's one-time order of 23.11. (trade/settings.riskoff_order_2311)."""

    def stop(self):
        return os.path.join(self.tmp.name, "STOP")

    def vel(self, who="Jure"):
        settings.put(self.con, f"flag:{settings.VEL_SWITCH}", {"mode": "live", "since": int(self.now), "who": who})
        settings._FLAG_CACHE.clear()

    def snapshot(self):
        return {k: v for k, v in settings.raw(self.con).items() if k not in (f"flag:{RS}", settings.RISKOFF_ONCE)}

    def test_applies_once_when_vel_is_live(self):
        self.vel()
        before = self.snapshot()
        line = settings.riskoff_order_2311(self.con, now=self.now, stop_file=self.stop())
        self.assertEqual(line, settings.RISKOFF_ORDER_LINE)
        self.assertEqual(settings.flag(RS, con=self.con), "live")
        self.assertEqual(self.snapshot(), before)                     # nothing else changed
        settings.set_flag(self.con, RS, "off", "Jure")                # he turns it off: it stays off
        self.assertIsNone(settings.riskoff_order_2311(self.con, now=self.now + 60, stop_file=self.stop()))
        self.assertEqual(settings.flag(RS, con=self.con), "off")

    def test_does_nothing_unless_every_condition(self):
        self.assertIsNone(settings.riskoff_order_2311(self.con, now=self.now, stop_file=self.stop()))   # VEL off
        self.vel(who="asistent")
        self.assertIsNone(settings.riskoff_order_2311(self.con, now=self.now, stop_file=self.stop()))   # not his
        self.vel()
        settings.pauza_set(self.con, True, "Jure", "x")
        self.assertIsNone(settings.riskoff_order_2311(self.con, now=self.now, stop_file=self.stop()))   # paused
        settings.pauza_set(self.con, False, "Jure", "x")
        open(self.stop(), "w").close()
        self.assertIsNone(settings.riskoff_order_2311(self.con, now=self.now, stop_file=self.stop()))   # kill switch
        os.remove(self.stop())
        self.assertIsNone(settings.riskoff_order_2311(self.con, now=settings.RISKOFF_ORDER_UNTIL,
                                                      stop_file=self.stop()))                          # expired
        self.assertEqual(settings.flag(RS, con=self.con), "off")
        self.assertFalse(settings.raw(self.con).get(settings.RISKOFF_ONCE))                            # not spent
        self.assertEqual(settings.riskoff_order_2311(self.con, now=self.now, stop_file=self.stop()),
                         settings.RISKOFF_ORDER_LINE)                                                  # still can

    def test_his_own_earlier_setting_spends_it(self):
        self.vel()
        settings.put(self.con, f"flag:{RS}", {"mode": "off", "since": int(self.now), "who": "Jure"})
        self.assertIsNone(settings.riskoff_order_2311(self.con, now=self.now, stop_file=self.stop()))
        self.assertEqual(settings.flag(RS, con=self.con), "off")
        self.assertTrue(settings.raw(self.con).get(settings.RISKOFF_ONCE))


if __name__ == "__main__":
    unittest.main()
