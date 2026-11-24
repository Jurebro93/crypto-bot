"""15.11. (owner, verbatim: "... zašto demo nije trgao tijekom noći. Želim ... da demo trguje cijelo vrijeme bez obzira
je li autopilot uključen nije I autopilot mora bolje uzimati profit. Ulaziti u više pozicija ali brže uzimati profit."
and earlier "Zašto je portfolio u minusu ako je dosta pozicija moglo biti izvučeno u profitu").

1. The demo account PAPER_USER trades 24/7: with the Autopilot switch off, the kill switch on, under pravi_novac_sve
   (which used to send every fast-path / proposal entry to the real account only) and while BTC falls (the macro gate
   no longer stops a demo entry; the state is recorded on the trade).
2. More demo entries: the range demo's looser entry (score 0.5, 5-min change > -8 %, volume ratio 20 %) and the fast
   path's soft skips (EV on thin evidence, the flow check alone), the demo account only; the real account keeps today's
   gates exactly (rules.SCALP, the BUY decisions, its caps).
3. The quick-profit exit (league/exitplan "brzi profit"): half at +12 % net, break-even, trailing 10 %, stop -20 % (a
   tighter own stop stays) on every automatic real-account position under pravi_novac_sve and on the demo account; the
   mirror sale stays an exit; momentum's TP1 half on the real account is mirrored for real.
No network.

    python3 -m unittest tests.test_demo15_offline
"""
import json
import os
import sys
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fast import paper as fpaper, sources as fsources, store as fstore  # noqa: E402
from league import auto, copy, exitplan, store  # noqa: E402
from market import makro  # noqa: E402
from momentum import trade as mtrade  # noqa: E402
from paper import rules as prules  # noqa: E402
from rangedca import rules as rrules, trade as rtrade  # noqa: E402
from trade import cost as tcost, executor, settings  # noqa: E402
from tests.test_pravi_novac_sve_offline import LU, PU, P, SwitchBase, tok  # noqa: E402
from tests.test_range_dca_offline import MINT, S, TradeBase  # noqa: E402

FALLING = {"btc": "pada", "eth": "neutralno", "score": 0.2, "ts": 0, "falling": True}
CALM = {"btc": "neutralno", "eth": "neutralno", "score": 0.5, "ts": 0, "falling": False}
W = "W" * 44


def checks(key="ev", fails=(), errors=(), label="procjena, n izvora < 10", n=3, flow_text=None, tx5=12):
    res = {"flow": {"status": "fail" if "flow" in fails else "ok", "text": flow_text or "tok u redu",
                    "values": {"tx_5m": tx5} if tx5 is not None else {}}}
    return {"key": key, "fails": list(fails), "errors": list(errors), "res": res,
            "est": {"label": label, "n": n, "p": 0.4}}


class Env(SwitchBase):
    """SwitchBase (trade.db / league.db in a temp dir, the swap and the market faked) + fast.db; the Autopilot switch
    OFF, the kill switch file present, flag fast_path paper, BTC calm unless a test says otherwise."""

    def setUp(self):
        super().setUp()
        self.fp = os.path.join(self.tmp.name, "fast.db")
        p = mock.patch.dict(os.environ, {"FAST_DB": self.fp})
        p.start()
        self.addCleanup(p.stop)
        self.fc = fstore.connect(self.fp)
        self.addCleanup(self.fc.close)
        fpaper.ensure(self.lg)
        fpaper._TRIED.clear()
        fpaper._TRIED_DEMO.clear()
        exitplan._SWEEP["ts"] = 0.0
        exitplan._QSWEEP["ts"] = 0.0
        exitplan._LAST.clear()
        store._MAKRO.update(at=0.0, v=None)
        self.addCleanup(store._MAKRO.update, at=0.0, v=None)
        settings.put(self.con, "on", False, "Jure")                       # the Autopilot switch OFF
        with open(executor.STOP_FILE, "w") as f:                          # the kill switch ON (real money only)
            f.write("stop")
        self.flag("fast_path", "paper")
        self.snap = dict(CALM)
        pm = mock.patch.object(makro, "snapshot", lambda now=None: dict(self.snap))
        pm.start()
        self.addCleanup(pm.stop)
        ed = mock.patch.object(copy, "entry_data", lambda *a, **k: {"score": None, "runup": None, "call_mcap": None})
        ed.start()
        self.addCleanup(ed.stop)
        self.lim = {"size_sol": 0.1, "max_sol_per_day": 1.0, "max_open": 5, "dca_token_cap": 0.3}

    def sig(self, token, decision="BUY_PAPER", ev=2.0, ch=None, size=0.05, kind="insider", t=None):
        t = int(t or self.now)
        cur = self.fc.execute(
            "INSERT INTO signals (token, symbol, kind, source_id, source_label, sig_ts, enq_ts, status, decided_ts, "
            "decision, reason, ev_pct, size_sol, checks, price0) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (token, "SIG", kind, W, "X", t - 5, t - 4, "done", t - 1, decision, "r", ev, size,
             json.dumps(ch if ch is not None else checks()), P))
        self.fc.commit()
        return cur.lastrowid

    def mk(self, mcap=100_000.0, liq=50_000.0, px=P):
        return lambda toks: {x: (px, liq, None, mcap, "SIG", {"m5": 1.0}) for x in toks}

    def run_fast(self, mk=None):
        return fpaper.run_once(self.lg, mk or self.mk(), now=int(self.now), path=self.fp, sol=100.0, lim=self.lim)

    def held(self, user, token):
        return self.lg.execute("SELECT 1 FROM trades WHERE user=? AND token=? AND status='open'", (user, token)
                               ).fetchone() is not None


# ---------- 1. the demo trades 24/7 -------------------------------------------------------------------------------------

class Demo247(Env):
    def test_autopilot_off_and_kill_switch_the_demo_still_enters(self):
        self.assertFalse(settings.merged(executor.load_config(), self.con)["on"])   # the Autopilot switch off
        self.assertTrue(os.path.exists(executor.STOP_FILE))                        # the kill switch on
        self.sig(tok(1))
        done = self.run_fast()
        self.assertEqual([u for u, _ in done], [PU])                     # switch off: the demo account, as before
        self.assertTrue(self.held(PU, tok(1)))

    def test_under_pravi_novac_sve_the_demo_enters_next_to_the_real_account(self):
        """14.11. evening - 15.11. 06:00: under the switch every BUY decision went to the real account only; now the
        demo account takes it too (paper stake), whatever the Autopilot switch says."""
        self.switch(True)
        self.sig(tok(2))
        done = self.run_fast()
        self.assertEqual(sorted(u for u, _ in done), sorted([LU, PU]))
        self.assertTrue(self.held(LU, tok(2)) and self.held(PU, tok(2)))
        src = self.lg.execute("SELECT source, size_usd FROM trades WHERE user=? AND token=?", (PU, tok(2))).fetchone()
        self.assertIn("usporedno s pravim računom", src[0])
        self.assertAlmostEqual(src[1], 5.0)                              # 0.05 SOL paper at $100
        self.assertEqual(self.run_fast(), [])                            # once per signal and account
        # one plan for the token, both accounts in it (the real one's executes there, the demo's on the demo)
        p = exitplan.active(self.lg, tok(2))
        self.assertEqual(p["plan"]["accounts"], sorted([LU, PU]))
        self.assertTrue(exitplan.execution(PU, exitplan._lots(self.lg, PU, tok(2)), plan=p)["executes"])
        # the source's record counts the signal once (the parallel demo entry is no second outcome)
        for u in (LU, PU):
            self.lg.execute("UPDATE fast_trades SET status='closed', pnl_usd=1.0 WHERE user=? AND token=?", (u, tok(2)))
        self.lg.commit()
        self.assertEqual(fsources.record(W, "insider", league_db=store.DB)["fast_closed"], 1)

    def test_proposals_under_the_switch_the_demo_takes_them_too(self):
        # (tests/test_pravi_novac_sve_offline.Paths.test_proposals_off_the_demo_account_on_the_real_one asserts it)
        from proposals import paper as ppaper
        with open(ppaper.__file__) as f:
            self.assertIn("users = [settings.LEAGUE_USER, settings.PAPER_USER] if real", f.read())

    def test_btc_falling_never_stops_a_demo_entry_and_the_state_is_on_the_trade(self):
        """06:44 UTC log "makro: ... novi demo ulazi zaustavljeni dok BTC pada": the demo bot's gate (paper/rules)
        refused every entry while BTC fell. Now: no refusal, the stake x 0.5, the state recorded."""
        self.snap = dict(FALLING)
        self.assertIsNone(prules.gate("T" * 44, 0.001, 50_000, 200_000, "prolaz", None, None))
        self.assertEqual(prules.makro_size(20.0, None)[:2], (10.0, "BTC pada (makro): ulog ×0,5"))
        self.assertEqual(prules.makro_size(20.0, None)[2]["btc"], "pada")
        self.snap = dict(CALM)
        self.assertEqual(prules.makro_size(20.0, None)[:2], (20.0, None))
        self.snap = dict(FALLING)
        store._MAKRO.update(at=0.0, v=None)
        self.sig(tok(3))
        done = self.run_fast()
        self.assertEqual([u for u, _ in done], [PU])                     # the Autopilot's demo: never stopped
        mk = json.loads(self.lg.execute("SELECT makro FROM trades WHERE user=? AND token=?", (PU, tok(3))).fetchone()[0])
        self.assertEqual((mk["btc"], mk["falling"]), ("pada", True))
        row = {"ts": int(self.now), "score": 0.2, "btc": "pada", "eth": "neutralno", "detail": {}}
        with mock.patch.object(makro, "at", lambda ts, con=None: row):
            self.assertIn("demo ulazi s pola uloga dok BTC pada (demo trguje uvijek)", makro.line(self.now))
            self.assertNotIn("zaustavljeni", makro.line(self.now))


class RunPaperMacro(unittest.TestCase):
    """The demo bot (run_paper.py): both entry paths take rules.makro_size (never a refusal while BTC falls)."""

    def test_both_entry_paths_use_the_macro_stake_and_record_it(self):
        with open(os.path.join(ROOT, "run_paper.py")) as f:
            src = f.read()
        self.assertEqual(src.count("rules.makro_size(size, cfg, now)"), 2)
        self.assertEqual(src.count('cfg_t["makro"] = mk_snap'), 2)
        with open(prules.__file__) as f:
            gate_src = f.read().split("def gate(")[1].split("\ndef ")[0]
        self.assertNotIn("makro.falling", gate_src)


# ---------- 2. more demo entries, the real account untouched ------------------------------------------------------------

class SoftSkips(Env):
    def test_what_is_soft_and_what_never_is(self):
        def s(**k):
            base = {"decision": "SKIP", "kind": "insider", "ev_pct": -2.0, "checks": checks()}
            base.update(k)
            return fpaper.soft_skip(base)
        self.assertIn("EV -2,0 % na tankom dokazu (n izvora 3)", s())
        self.assertIn("tok: kupnje 30 % u 5 min < 40 %",
                      s(checks=checks("flow", ["flow"], flow_text="tok: kupnje 30 % u 5 min < 40 %")))
        self.assertIsNone(s(checks=checks(label=None, n=25)))            # a measured source with EV <= 0: a real no
        self.assertIsNone(s(ev_pct=-7.0))                                # under SOFT_EV_MIN
        self.assertIsNone(s(ev_pct=None))
        for key in ("rug", "holders", "price", "source"):                # the hard checks never
            self.assertIsNone(s(checks=checks(key, [key])))
        self.assertIsNone(s(checks=checks("flow", ["flow", "holders"])))  # the flow alone only
        self.assertIsNone(s(checks=checks("flow", ["flow"], tx5=None)))  # no pair: nothing measured
        self.assertIsNone(s(checks=checks(errors=["rug"])))
        self.assertIsNone(s(kind="x_call"))
        self.assertIsNone(s(decision="BUY_PAPER"))

    def test_a_soft_skip_is_a_demo_entry_only_and_never_a_real_one(self):
        self.switch(True)                                                # even with the real-money switch on
        self.sig(tok(10), "SKIP", ev=-2.5)
        self.sig(tok(11), "SKIP", ev=1.0, ch=checks("flow", ["flow"], flow_text="tok: 3 transakcija u 5 min < 5"))
        self.sig(tok(12), "SKIP", ev=1.0, ch=checks("rug", ["rug"]))
        done = self.run_fast()
        self.assertEqual(sorted((u, d.split(" ")[2]) for u, d in done), [(PU, "SIG"), (PU, "SIG")])
        for t in (tok(10), tok(11), tok(12)):
            self.assertFalse(self.held(LU, t))
        self.assertTrue(self.held(PU, tok(10)) and self.held(PU, tok(11)))
        self.assertFalse(self.held(PU, tok(12)))
        rows = self.lg.execute("SELECT decision, user FROM fast_trades ORDER BY id").fetchall()
        self.assertEqual([tuple(r) for r in rows], [(fpaper.SOFT_DECISION, PU)] * 2)
        src = self.lg.execute("SELECT source FROM trades WHERE user=? AND token=?", (PU, tok(10))).fetchone()[0]
        self.assertIn("mekani preskok: EV -2,5 % na tankom dokazu", src)
        traded = self.fc.execute("SELECT traded FROM signals WHERE token=?", (tok(10),)).fetchone()[0]
        self.assertIn("mekani preskok", traded)
        # the live gate (proof) and the source's record never count them
        self.lg.execute("UPDATE fast_trades SET status='closed', pnl_usd=-1.0, ret=-0.2")
        self.lg.commit()
        self.assertEqual(fpaper.proof(self.lg)["n"], 0)
        self.assertEqual(fsources.record(W, "insider", league_db=store.DB)["fast_closed"], 0)

    def test_the_hard_rules_hold_on_the_live_quote(self):
        self.sig(tok(20), "SKIP", ev=-1.0)
        self.assertEqual(self.run_fast(self.mk(mcap=25_000.0)), [])      # under 30k
        fpaper._TRIED_DEMO.clear()
        self.assertEqual(self.run_fast(self.mk(liq=12_000.0)), [])       # liquidity under $15k (the fast path: $20k)
        fpaper._TRIED_DEMO.clear()
        curve = lambda toks: {x: (P, 50_000.0, None, 100_000.0, "SIG", {"curve": True}) for x in toks}   # noqa: E731
        with mock.patch.object(copy, "_bonding_curve", lambda m: True):
            self.assertEqual(self.run_fast(curve), [])                   # still on the pump.fun curve
        fpaper._TRIED_DEMO.clear()
        with mock.patch.object(rtrade, "archived_why", lambda t: "token je u arhivi rugova (rug)"):
            self.assertEqual(self.run_fast(), [])                         # the rug archive
        fpaper._TRIED_DEMO.clear()
        self.assertEqual([u for u, _ in self.run_fast()], [PU])          # all clear: the demo learns


class RangeDemo(TradeBase):
    """The range demo profile's looser entry (rules.DEMO) vs the real account's rules.SCALP (14.11. exactly)."""

    def setUp(self):
        super().setUp()
        self.mode("paper")
        self.mode("paper", "range_demo")
        rtrade._BLOCKS_SEEN.clear()
        rtrade._CACHE.pop("demo_log", None)
        rtrade._CACHE.pop("tx_fee", None)
        rtrade._CACHE.pop("cfg", None)
        store._MAKRO.update(at=0.0, v=None)
        self.addCleanup(store._MAKRO.update, at=0.0, v=None)

    def drng(self, score=0.8, **m):
        r = self.rng(score, **m)
        r["survivor"] = {"ok": True, "crashed": False, "age_h": 72.0, "loss_24h": -0.2, "in_range": True, "why": "ok"}
        return r

    def test_the_night_blockers_no_longer_hold_the_demo_but_hold_the_real_account(self):
        # score 0.55, the 5-min change -6 %, the 15-min volume at 25 % of the hour: all three held the demo at night
        r = self.drng(score=0.55, ch_5m=-0.06, vol_ratio=0.25)
        self.assertIsNone(rrules.entry_check(r, 52.0 * S, rrules.DEMO))
        self.assertIn("ocjena raspona 0.55 ispod 0.60", rrules.entry_check(r, 52.0 * S, rrules.SCALP))
        self.assertIn("pada -6.0% u 5 min", rrules.entry_check(dict(r, score=0.8), 52.0 * S, rrules.SCALP))
        self.assertIn("volumen 15 min je 25%", rrules.entry_check(self.drng(vol_ratio=0.25), 52.0 * S, rrules.SCALP))
        self.mode("live", rtrade.PRAVI_FLAG)                             # the real account trades its scalp too
        self.assertEqual(rtrade.profile(LU)["score_min"], 0.6)
        self.assertEqual(rtrade.profile(PU)["score_min"], 0.5)
        with mock.patch.object(makro, "snapshot", lambda now=None: dict(FALLING)):   # and BTC falls
            settings.put(self.con, "on", False, "Jure")                  # and the Autopilot switch is off
            done = self.enter(px=52.0, rng=r)
        self.assertEqual([u for u, _ in done], [PU])                     # the demo only
        self.assertEqual(self.lots(LU), [])
        mk = json.loads(self.lots(PU)[0]["makro"])
        self.assertTrue(mk["falling"])
        blocks = {k for (k,) in self.lg.execute("SELECT reason FROM range_blocks WHERE user=?", (LU,))}
        self.assertEqual(blocks & {"pad u zadnjih 5 min", "slab volumen 15 min"}, set())   # its own reasons only

    def test_a_real_entry_is_still_the_14_11_profile(self):
        self.mode("live", rtrade.PRAVI_FLAG)
        same = {k: rrules.SCALP[k] for k in ("score_min", "ch5_min", "vol_ratio_min", "entry_bottom", "tp_usd",
                                              "stop_min_pct", "stop_max_pct", "focus_n", "max_open")}
        self.assertEqual(same, {"score_min": 0.6, "ch5_min": -0.05, "vol_ratio_min": 0.35, "entry_bottom": 0.5,
                                "tp_usd": 0.6, "stop_min_pct": 0.17, "stop_max_pct": 0.25, "focus_n": 10, "max_open": 10})
        self.assertIs(rrules.profile_cfg({"profile": "scalp"}), rrules.SCALP)


# ---------- 3. the quick-profit exit ------------------------------------------------------------------------------------

class QuickExit(Env):
    def market(self, mult, mcap=100_000.0):
        return lambda toks: {x: (P * mult, 50_000.0, None, mcap * mult) for x in toks}

    def step(self, mult, dt=5):
        self.now += dt
        with mock.patch.object(exitplan, "fresh_prices", lambda toks, now: {}):
            return exitplan.run_once(self.lg, self.market(mult), now=self.now)

    def copy_in(self, user, token, kind="wallet", mode="mirror", tp="", sl=""):
        fid = copy.follow(self.lg, user, kind, W, "kit", 25, 5, mode, tp, sl)
        f = [x for x in copy.follows(self.lg, user) if x["id"] == fid][0]
        mk = {token: (P, 50_000.0, None, 100_000.0, "CPY", {"m5": 1.0})}
        copy._enter(self.lg, auto, mk, [(f, token, "buy", int(self.now) - 5)], int(self.now))
        return f

    def test_a_mirror_copy_half_at_12_net_break_even_trailing_and_the_mirror_sale(self):
        self.switch(True)
        f = self.copy_in(LU, tok(90))
        p = exitplan.active(self.lg, tok(90))
        rt = tcost.round_trip(25.0, 50_000.0) * 100
        self.assertTrue(p["client"].startswith(f"{exitplan.SWITCH_SRC} {exitplan.QUICK_TAG}"))
        self.assertAlmostEqual(p["plan"]["take_profits"][0]["v"], round(12 + rt, 2))
        self.assertEqual(p["plan"]["take_profits"][0]["sell_share"], 0.5)
        self.assertEqual(p["plan"]["trailing"], {"activate_pct": round(12 + rt, 2), "trail_pct": 10.0})
        self.assertTrue(p["plan"]["breakeven_after_tp1"])
        self.assertEqual(p["plan"]["stop"]["v"], -20.0)                  # was the -30 % protective stop
        self.assertNotIn(tok(90), exitplan.in_force_tokens(self.lg, LU))   # only adds: the lot's own exits stay
        note = self.lg.execute("SELECT note FROM copy_log WHERE token=? AND action='ulaz'", (tok(90),)).fetchone()[0]
        self.assertIn("brzi profit: pola na +", note)
        self.assertEqual(self.step(1.10), [])                            # +10 %: nothing
        got = self.step(1 + (12 + rt) / 100 + 0.001)
        self.assertEqual([(u, tr) for u, _t, tr, _x in got], [(LU, "tp1")])
        t = exitplan._lots(self.lg, LU, tok(90))[0]
        self.assertAlmostEqual(t["qty"] / (t["size_usd"] / t["entry_eff"]), 0.5, places=6)   # run_trade sells 50 %
        st = exitplan.active(self.lg, tok(90))["state"]
        self.assertGreater(st["stop_px"][LU], P)                         # the rest's stop at break-even (entry + cost)
        self.assertLess(st["stop_px"][LU], P * 1.05)
        self.assertEqual(self.step(1.35), [])                            # GTA$ 14.11.: +35 % ...
        # ... the source sells: the mirror sale is still an exit (it sells the rest)
        copy._enter(self.lg, auto, {tok(90): (P * 1.30, 50_000.0, None, 130_000.0, "CPY")},
                    [(f, tok(90), "sell", int(self.now))], int(self.now))
        self.assertEqual(exitplan._lots(self.lg, LU, tok(90)), [])
        rule = self.lg.execute("SELECT exit_rule FROM trades WHERE user=? AND token=? ORDER BY id DESC", (LU, tok(90))
                               ).fetchone()[0]
        self.assertEqual(rule, "wallet_sold")

    def test_the_trailing_10_from_the_peak_and_the_hard_stop_minus_20(self):
        self.switch(True)
        self.copy_in(LU, tok(91))
        self.step(1.20)                                                  # TP1
        self.step(1.40)                                                  # the peak
        self.assertEqual(self.step(1.27), [])                            # -9.3 % from the peak
        got = self.step(1.25)                                            # -10.7 %: the trailing
        self.assertEqual([tr for _u, _t, tr, _x in got], ["trailing"])
        self.assertEqual(exitplan._lots(self.lg, LU, tok(91)), [])
        self.copy_in(LU, tok(92))
        self.assertEqual(self.step(0.81), [])
        got = [x for x in self.step(0.79) if x[1] == tok(92)]            # -21 %: the hard stop
        self.assertEqual([tr for _u, _t, tr, _x in got], ["stop"])

    def test_the_demo_copy_runs_it_too_without_any_switch(self):
        self.flag("exit_plans", "off")                                   # whatever exit_plans says
        self.copy_in(PU, tok(93))
        p = exitplan.active(self.lg, tok(93))
        self.assertTrue(p["client"].startswith(exitplan.QUICK_SRC))
        self.assertEqual(p["plan"]["accounts"], [PU])
        self.assertTrue(exitplan.execution(PU, exitplan._lots(self.lg, PU, tok(93)), plan=p)["executes"])
        got = self.step(1.20)
        self.assertEqual([(u, tr) for u, _t, tr, _x in got], [(PU, "tp1")])
        part = self.lg.execute("SELECT COUNT(*) FROM trades WHERE user=? AND token=? AND status='closed'",
                               (PU, tok(93))).fetchone()[0]
        self.assertEqual(part, 1)                                        # the sold half is its own closed row

    def test_one_plan_two_accounts_each_its_own_stop(self):
        self.switch(True)
        self.copy_in(PU, tok(94), sl="-15%", mode="tpsl", tp="50%")      # the demo first, with a tighter own SL
        self.copy_in(LU, tok(94))
        p = exitplan.active(self.lg, tok(94))
        self.assertEqual(p["plan"]["accounts"], sorted([LU, PU]))
        self.assertTrue(p["client"].startswith(exitplan.SWITCH_SRC))     # the real part executes on the real account
        lots = {u: exitplan._lots(self.lg, u, tok(94))[0] for u in (LU, PU)}
        self.assertAlmostEqual(p["state"]["stop_px"][LU] / lots[LU]["entry_px"], 0.80, places=4)
        self.assertGreater(p["state"]["stop_px"][PU] / lots[PU]["entry_px"], 0.84)   # its own -15 % (from eff)
        got = self.step(1.20)
        self.assertEqual(sorted(u for u, _t, tr, _x in got if tr == "tp1"), sorted([LU, PU]))

    def test_a_joined_account_whose_state_was_written_over_joins_again(self):
        """The 20-s loop joins an account while the 1-s executor holds the plan's older state: its save drops the
        joined account's stop; the 5-s sweep puts it back (the run_trade stop check reads it)."""
        self.switch(True)
        self.copy_in(LU, tok(102))
        self.copy_in(PU, tok(102))
        p = exitplan.active(self.lg, tok(102))
        st = dict(p["state"], stop_px={LU: p["state"]["stop_px"][LU]})
        self.lg.execute("UPDATE exit_plans SET state=? WHERE id=?", (json.dumps(st), p["id"]))
        self.lg.commit()
        self.assertEqual(exitplan.ensure_quick_plans(self.lg, every=0), [tok(102)])
        p = exitplan.active(self.lg, tok(102))
        self.assertAlmostEqual(p["state"]["stop_px"][PU] / P, 0.80, places=3)
        self.assertEqual(exitplan.ensure_quick_plans(self.lg, every=0), [])

    def test_other_strategies_keep_their_tighter_numbers(self):
        self.switch(True)
        # a copy with its own -15 % SL: -15 % stays
        self.demo(tok(95), "copy KOL a", sl="-15%")
        # momentum: its own exits (half at +15 %, trailing 8 %, stop -10 %): only the protective stop, -20 % (was -30)
        self.demo(tok(96), mtrade.SRC, sl=None)
        # a range lot: its round's own plan / stop, exactly as before; the owner's own: nothing
        self.demo(tok(97), "range lot 1", sl=None)
        self.demo(tok(98), "ručno (pravi trade)", sl=None)
        exitplan.ensure_switch_stops(self.lg, every=0)
        p95, p96, p97 = (exitplan.active(self.lg, tok(i)) for i in (95, 96, 97))
        self.assertTrue(exitplan.is_quick(p95))
        self.assertGreater(p95["plan"]["stop"]["v"], -16.0)
        self.assertEqual((p96["plan"]["stop"]["v"], p96["plan"]["take_profits"]), (-20.0, []))
        self.assertEqual((p97["plan"]["stop"]["v"], p97["plan"]["take_profits"]), (-30.0, []))
        self.assertIsNone(exitplan.active(self.lg, tok(98)))
        # the fast path under the switch: its own -10 % stop, 8 % trailing, TP1 never above its +15 %; 45 min by the
        # lot's own hold (a shared plan's time stop would hold for the other account too)
        s = {"id": 77, "token": tok(99), "decision": "BUY_PAPER", "size_sol": 0.05, "price0": P, "kind": "insider",
             "source_label": "X", "source_id": W, "sig_ts": int(self.now)}
        text, why = fpaper.enter(self.lg, s, LU, False, (P, 50_000.0, None, 100_000.0, "FST"), self.lim, 100.0,
                                 int(self.now), path=self.fp, switch=True)
        self.assertIsNone(why)
        p = exitplan.active(self.lg, tok(99))
        self.assertEqual((p["plan"]["stop"]["v"], p["plan"]["trailing"]["trail_pct"]), (-10.0, 8.0))
        self.assertLessEqual(p["plan"]["take_profits"][0]["v"], 15.0)
        self.assertIsNone(p["plan"]["time_stop"])
        a = json.loads(self.lg.execute("SELECT auto FROM trades WHERE user=? AND token=?", (LU, tok(99))).fetchone()[0])
        self.assertEqual(a["until"] - self.lg.execute("SELECT opened_ts FROM trades WHERE user=? AND token=?",
                                                      (LU, tok(99))).fetchone()[0], 45 * 60)

    def test_an_old_protective_stop_becomes_the_quick_plan(self):
        self.switch(True)
        self.demo(tok(100), "copy KOL a", sl=None)
        exitplan.set_plan(self.lg, tok(100), {"accounts": [LU], "stop": {"at_pct": -30.0}}, 60,
                          client=exitplan.PROTECT_CLIENT)
        self.assertEqual(exitplan.ensure_switch_stops(self.lg, every=0), [tok(100)])
        p = exitplan.active(self.lg, tok(100))
        self.assertTrue(exitplan.is_quick(p))
        self.assertEqual(p["plan"]["stop"]["v"], -20.0)                  # tightened, never loosened

    def test_without_the_switch_the_real_account_is_untouched(self):
        self.copy_in(LU, tok(101))
        self.assertIsNone(exitplan.active(self.lg, tok(101)))            # no quick plan on the real account
        self.assertEqual(exitplan.ensure_switch_stops(self.lg, every=0), [])
        self.assertEqual(exitplan.ensure_quick_plans(self.lg, every=0), [])   # the sweep is for the demo only


class MomentumReal(Env):
    def test_tp1_half_on_the_real_account_is_sold_for_real(self):
        """momentum's TP1 half used store.sell_partial, which run_trade cannot see on the real account (the share held
        stayed 1.0): now store.sell_part, the trade's PnL counted once."""
        mtrade.ensure(self.lg)
        tid = self.demo(tok(110), mtrade.SRC, sl=None)
        self.lg.execute("INSERT INTO momentum_trades (user, token, symbol, opened_ts, status, trade_id, entry_px, "
                        "size_usd, state) VALUES (?,?,?,?,?,?,?,?,?)",
                        (LU, tok(110), "MOM", int(self.now), "open", tid, P, 25.0, json.dumps({"pnl": 0.0})))
        self.lg.commit()
        mkt = lambda m: (lambda toks: {x: (P * m, 50_000.0, None, 100_000.0 * m) for x in toks})   # noqa: E731
        out = mtrade.exits_once(self.lg, mkt(1.16), self.now + 5)
        self.assertIn("pola van na +15 %", out[0])
        t = dict(self.lg.execute("SELECT * FROM trades WHERE id=?", (tid,)).fetchone())
        self.assertEqual(t["status"], "open")
        self.assertAlmostEqual(t["qty"] / (t["size_usd"] / t["entry_eff"]), 0.5, places=6)
        mtrade.exits_once(self.lg, mkt(1.30), self.now + 10)              # the peak
        out = mtrade.exits_once(self.lg, mkt(1.19), self.now + 15)        # -8.5 %: the trailing
        self.assertIn("trade gotov", out[0])
        pnl_lot = self.lg.execute("SELECT pnl_usd FROM trades WHERE id=?", (tid,)).fetchone()[0]
        pnl_mt = self.lg.execute("SELECT pnl_usd FROM momentum_trades WHERE trade_id=?", (tid,)).fetchone()[0]
        self.assertAlmostEqual(pnl_mt, pnl_lot, places=6)                 # counted once


if __name__ == "__main__":
    unittest.main()
