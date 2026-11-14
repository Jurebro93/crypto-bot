"""11.11. (Jure: "rangedca flip / pauza / stop", flag range_flip G26): the flip / pause state of a range
(rangedca/detect.flip_step), the volatility stop, the new rules (rules.new_range) on the demo account only, the shadow
rows, the live gate on the nightly backtest (new max drawdown <= today's), the job, the MCP view and the backtest of
today's rules vs the new ones on the stored GeckoTerminal candles (HOPE + WEALTH, PIRATE, timmy, Leonida; 11.11.
HAOBIBI added on the owner's order). No network.

    python3 -m unittest tests.test_range_flip_offline
"""
import gzip
import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from league import flags  # noqa: E402
from rangedca import backtest, data, detect, gate, rules, trade, view  # noqa: E402
from trade import settings  # noqa: E402
from tests.test_pozicije_izlaz_offline import MINT  # noqa: E402
from tests.test_range_dca_offline import S, T0, TradeBase, path, tri  # noqa: E402

LU, PU = settings.LEAGUE_USER, settings.PAPER_USER
FX = os.path.join(ROOT, "tests", "fixtures")
FIXTURES = ("range_hope_20261111.json.gz", "range_wealth_20261111.json.gz", "range_pirate_20261111.json.gz",
            "range_timmy_20261111.json.gz", "range_leonida_20261111.json.gz",
            "range_haobibi_20261111.json.gz")   # 11.11. (owner: HAOBIBI into the range_flip backtest set)
HV = {m: 5000.0 for m in range(0, 40)}   # 5 x the range's volume per minute in the first 40 minutes of a move


def after(cs, pts, vol=1000.0, vols=None):
    """cs and then minute candles through (minute, price / S) waypoints from the next minute on."""
    return cs + path(cs[-1][0] + 60, [(m, p * S) for m, p in pts], vol=vol, vols=vols)


BASE = tri(T0, hours=12)   # 52-98 (MC 51.5k-99k), 12 h, ends near the bottom
END = BASE[-1][4] / S
UP_RETEST = [(0, END), (30, 98), (40, 125), (60, 135), (100, 98), (140, 135), (180, 98), (220, 125), (260, 120)]
UP_FAIL = [(0, END), (30, 98), (40, 125), (60, 135), (100, 85), (140, 80)]
DOWN_BELOW = [(0, END), (20, 34), (30, 30), (60, 45), (90, 30), (120, 45), (150, 30), (180, 45), (210, 31), (240, 44)]
DOWN_ABOVE = [(0, END), (20, 34), (30, 30), (60, 62), (90, 30), (120, 62), (150, 30), (180, 62), (210, 31), (240, 60)]
DOWN_RECLAIM = [(0, END), (20, 34), (30, 30), (60, 45), (75, 75), (200, 74)]
UP_NO_RETEST = [(0, END), (30, 98), (40, 125), (60, 135), (480, 140)]


def states(cs, liq=50_000.0):
    """[(ts, state, range)] of every 5-minute step (backtest.timeline with the flip state, as run_range live)."""
    return [(t, r["flip"]["state"], r) for t, r, _st in backtest.timeline(cs, 1e9, liq, flip=True)]


def first(sts, state):
    return next(((t, r) for t, s, r in sts if s == state), (None, None))


def load(name):
    with gzip.open(os.path.join(FX, name), "rt") as f:
        fx = json.load(f)
    return fx["token"], (data.merge([tuple(r) for r in fx["candles"]], []), fx["supply"], None, fx.get("symbol"))


# ---------------------------------------------------------------------------------------------------------------
class Breaks(unittest.TestCase):
    ZONES = {"range_low_low": 50.0, "range_low_top": 52.0, "range_high_low": 95.0, "range_high_top": 100.0}

    def bars(self, closes_vols, t0=T0):
        """One candle per 5-minute bar (o = h = l = c)."""
        return [(t0 + i * 300, c, c, c, c, v, None, None) for i, (c, v) in enumerate(closes_vols)]

    def test_a_break_up_is_confirmed_only_with_volume(self):
        inside = [(70.0 + (i % 5), 1000.0) for i in range(30)]
        for vol, confirmed in ((1400.0, False), (1600.0, True)):
            cs = self.bars(inside + [(103.0, vol)])
            now = cs[-1][0] + 300
            b = detect.breakout(self.ZONES, cs, now - 300, now, atr_px=None)
            self.assertEqual((b["dir"], b["confirmed"]), ("up", confirmed), vol)
            self.assertAlmostEqual(b["level"], 102.0)                        # range_high_top + 2 %
            self.assertAlmostEqual(b["vol_x"], vol / 1000.0)
        cs = self.bars(inside + [(101.5, 9000.0)])                            # over the top, under the 2 % margin
        self.assertIsNone(detect.breakout(self.ZONES, cs, cs[-1][0], cs[-1][0] + 300))
        cs = self.bars(inside + [(103.0, 9000.0)])                            # the margin is max(2 %, 1 x ATR)
        b = detect.breakout(self.ZONES, cs, cs[-1][0], cs[-1][0] + 300, atr_px=5.0)
        self.assertIsNone(b)
        # a slow grind: the excursion began 4 bars ago, the volume came later: not a confirmed break
        cs = self.bars(inside + [(103.0, 1000.0)] * 4 + [(104.0, 5000.0)])
        b = detect.breakout(self.ZONES, cs, cs[-1][0], cs[-1][0] + 300)
        self.assertFalse(b["confirmed"])
        cs = self.bars(inside + [(47.0, 4000.0)])                             # down: under range_low_low - 2 %
        b = detect.breakout(self.ZONES, cs, cs[-1][0], cs[-1][0] + 300)
        self.assertEqual((b["dir"], b["confirmed"]), ("down", True))

    def test_flip_candidate_then_the_old_top_is_the_new_bottom_after_two_retests(self):
        sts = states(after(BASE, UP_RETEST, vols=HV))
        t1, r1 = first(sts, "flip_candidate")
        self.assertIsNotNone(t1)
        fl = r1["flip"]
        self.assertEqual((fl["brk"]["dir"], fl["zone"]["mc_low"], fl["zone"]["mc_top"]), ("up", 97020, 98980))
        self.assertGreaterEqual(fl["brk"]["vol_x"], 1.5)
        nr = rules.new_range(r1)                                               # no range entries until the retests
        self.assertEqual((nr["active"], nr["status"]), (False, "flip_candidate"))
        self.assertIn("retest", rules.entry_check(nr, 98 * S))
        self.assertIsNone(rules.new_range(r1, ("atr",)).get("flip_block"))   # the stop-only part does not block
        t2, r2 = first(sts, "flipped")
        self.assertGreater(t2, t1)
        fl = r2["flip"]
        self.assertGreaterEqual(len(fl["touches"]), 2)
        self.assertEqual(fl["alt"]["status"], "aktivan")
        az = fl["alt"]["zones"]["mc"]
        self.assertEqual((az["range_low_low"], az["range_low_top"]), (97020, 98980))   # the old top zone
        self.assertGreater(az["range_high_low"], 130_000)
        nr = rules.new_range(r2)
        self.assertTrue(nr["active"])
        self.assertEqual(nr["zones"]["mc"]["range_low_low"], 97020)
        self.assertEqual(nr["stop_kind"], "atr")
        lv = rules.levels_of(nr)
        self.assertTrue(97.02 * S * 0.80 - 1e-12 <= lv["stop_px"] <= 97.02 * S * 0.95 + 1e-12)
        self.assertEqual(lv["floor_px"], max(97.02 * S * 0.92, lv["stop_px"]))
        # today's range never changes for it: no "flip" in the zones the old rules read, its own levels
        self.assertEqual(rules.levels_of(r2)["stop_px"], r2["zones"]["range_low_low"] * 0.85)

    def test_unconfirmed_break_up_changes_nothing_and_a_close_under_the_zone_fails_the_flip(self):
        sts = states(after(BASE, UP_RETEST))                                   # the same move without volume
        self.assertEqual({s for _t, s, _r in sts}, {"normal"})
        sts = states(after(BASE, UP_FAIL, vols=HV))
        t1, _r = first(sts, "flip_candidate")
        t2, r2 = next(((t, r) for t, s, r in sts if t > (t1 or 0) and s == "normal"), (None, None))
        self.assertIsNotNone(t2)
        self.assertIn("flip nije uspio", r2["flip"]["why"])

    def test_pause_after_a_break_down_no_entries_and_resume_under_the_resistance(self):
        sts = states(after(BASE, DOWN_BELOW, vols={m: 5000.0 for m in range(30)}))
        t1, r1 = first(sts, "paused")
        fl = r1["flip"]
        self.assertEqual((fl["brk"]["dir"], fl["zone"]["mc_low"], fl["zone"]["mc_top"]), ("down", 51480, 52520))
        self.assertIn("pauza", fl["block"])
        nr = rules.new_range(r1)
        self.assertEqual((nr["active"], nr["zones"]), (False, None))
        self.assertIn("pauza", rules.entry_check(nr, 52 * S))
        self.assertTrue(rules.flip_block(r1))
        t2, r2 = first(sts, "resumed")
        self.assertGreater(t2, t1)
        alt = r2["flip"]["alt"]
        self.assertEqual(alt["status"], "aktivan")
        self.assertLessEqual(alt["zones"]["range_high_top"], 52.52 * S * 1.03)   # its top <= the resistance
        self.assertGreaterEqual(alt["bottom_touches"], 2)
        self.assertEqual(rules.new_range(r2)["zones"]["range_high_top"], alt["zones"]["range_high_top"])
        # a new range ABOVE the resistance: still paused
        sts = states(after(BASE, DOWN_ABOVE, vols={m: 5000.0 for m in range(30)}))
        self.assertIsNotNone(first(sts, "paused")[0])
        self.assertIsNone(first(sts, "resumed")[0])

    def test_a_pause_ends_when_the_price_closes_back_above_the_resistance_with_volume(self):
        """11.11. (Jure: "nastavak iz pauze kad se cijena vrati iznad otpora uz volumen")."""
        brk = {m: 5000.0 for m in range(30)}
        sts = states(after(BASE, DOWN_RECLAIM, vols={**brk, **{m: 5000.0 for m in range(60, 80)}}))
        t1, _r = first(sts, "paused")
        t2, r2 = next(((t, r) for t, s, r in sts if t > (t1 or 0) and s == "normal"), (None, None))
        self.assertIsNotNone(t2)
        self.assertIn("nastavak: povratak iznad otpora", r2["flip"]["why"])
        self.assertIsNone(r2["flip"]["block"])
        sts = states(after(BASE, DOWN_RECLAIM, vols=brk))                    # the same return without volume
        t1, _r = first(sts, "paused")
        self.assertFalse(any(s == "normal" for t, s, _r in sts if t > t1))
        z = {"low": 50.0, "top": 52.0}
        cs = Breaks().bars([(51.0, 1000.0)] * 30 + [(40.0, 1000.0)] * 5 + [(53.5, 1200.0), (53.5, 900.0)])
        now = cs[-1][0] + 300
        self.assertIsNone(detect.reclaim(z, cs, cs[30][0], now))             # above 52 x 1.02, volume only 1.2x
        cs = Breaks().bars([(51.0, 1000.0)] * 30 + [(40.0, 1000.0)] * 5 + [(52.5, 9000.0), (53.5, 1600.0)])
        r = detect.reclaim(z, cs, cs[30][0], now)
        self.assertEqual((r["close"], r["vol_x"]), (53.5, 1.6))               # 52.5 is under the 2 % margin

    def test_a_flip_without_its_retests_in_5_h_is_no_flip(self):
        """11.11. (Jure: "retest nakon flipa skratiti s 24 h na 4-6 h")."""
        self.assertEqual(detect.FLIP["retest_s"], 5 * 3600)
        sts = states(after(BASE, UP_NO_RETEST, vols=HV))
        t1, r1 = first(sts, "flip_candidate")
        t2, r2 = next(((t, r) for t, s, r in sts if t > (t1 or 0) and s == "normal"), (None, None))
        self.assertIsNotNone(t2)
        self.assertIn("flip nije potvrđen u 5 h", r2["flip"]["why"])
        self.assertGreater(t2 - r1["flip"]["brk"]["end"], 5 * 3600)
        self.assertLessEqual(t2 - r1["flip"]["brk"]["end"], 5 * 3600 + 300)

    def test_a_state_ends_24_h_after_its_break_and_a_stale_reference_reads_no_break(self):
        sts = states(after(BASE, DOWN_BELOW, vols={m: 5000.0 for m in range(30)}))
        _t, r = first(sts, "paused")
        st = dict(r["flip"], ref=None)
        later = BASE[-1][0] + 25 * 3600
        st2 = detect.flip_step(st, None, [], later)
        self.assertEqual(st2["state"], "normal")
        self.assertIn("24 h", st2["why"])
        ref = dict(Breaks.ZONES)
        prev = {"v": detect.FLIP["v"], "state": "normal", "ts": T0, "since": T0, "ver": 0, "ref": ref}
        cs = Breaks().bars([(70.0, 1000.0)] * 30 + [(110.0, 9000.0)])
        self.assertEqual(detect.flip_step(prev, None, cs, cs[-1][0] + 300)["state"], "normal")   # 2.5 h gap
        prev["ts"] = cs[-1][0]
        self.assertEqual(detect.flip_step(prev, None, cs, cs[-1][0] + 300)["state"], "flip_candidate")
        self.assertIsNone(detect.flip_step({**prev, "v": 0}, None, cs, cs[-1][0] + 300).get("brk"))   # old version


class VolatilityStop(unittest.TestCase):
    def test_atr_of_15_minute_bodies(self):
        b0 = T0 - T0 % 900
        cs = [(b0 + i * 900, *((100.0, 110.0, 100.0, 110.0) if i % 2 == 0 else (110.0, 110.0, 100.0, 100.0)), 1.0, None, None)
              for i in range(20)]
        self.assertAlmostEqual(detect.atr(cs, b0 + 20 * 900), 10.0)
        wick = [(c[0], c[1], c[2] * 3, c[3] / 3, c[4], c[5], None, None) for c in cs]   # wicks do not count
        self.assertAlmostEqual(detect.atr(wick, b0 + 20 * 900), 10.0)
        self.assertIsNone(detect.atr(cs[:4], b0 + 4 * 900))                 # 3 true ranges: unknown

    def test_stop_is_range_low_low_minus_1_5_atr_between_5_and_20_percent(self):
        self.assertEqual(detect.vol_stop(100.0, None), (85.0, "fixed"))     # unknown ATR: today's x 0.85
        self.assertEqual(detect.vol_stop(100.0, 1.0), (95.0, "atr"))        # 98.5: at least 5 % under it
        self.assertEqual(detect.vol_stop(100.0, 6.0), (91.0, "atr"))
        self.assertEqual(detect.vol_stop(100.0, 30.0), (80.0, "atr"))       # 55 -> at most 20 % under it
        r = {"zones": {"range_low_low": 100.0, "range_low_top": 104.0, "range_high_low": 140.0, "range_high_top": 150.0},
             "active": True, "flip": {"state": "normal", "atr": 6.0}}
        self.assertEqual(rules.levels_of(r)["stop_px"], 85.0)              # today's rules: x 0.85
        nr = rules.new_range(r)
        self.assertEqual((rules.levels_of(nr)["stop_px"], rules.levels_of(nr)["stop_kind"]), (91.0, "atr"))
        self.assertEqual(rules.levels_of(rules.new_range(r, ("flip",)))["stop_px"], 85.0)   # flip only: x 0.85
        plain = {"zones": r["zones"], "active": True}
        self.assertIs(rules.new_range(plain), plain)                         # no flip block: today's range itself


# ---------------------------------------------------------------------------------------------------------------
class Modes(TradeBase):
    def frng(self, state="normal", atr=4.0, **kw):
        r = self.rng(**kw)
        r["flip"] = {"v": 1, "state": state, "atr": atr * S, "block": "pauza nakon proboja dolje" if state == "paused"
                     else "proboj gore: čeka se retest" if state == "flip_candidate" else None,
                     "zone": {"low": 51.0 * S, "top": 53.0 * S} if state != "normal" else None}
        return r

    def enter_r(self, r, px=52.0, now=None):
        now = now or self.now
        r["ts"] = r["mts"] = now
        return trade.run_once(self.lg, self.mk(px), now, {MINT: r}, self.lim, 100.0)

    def test_off_is_todays_rules_exactly(self):
        self.mode("paper")
        self.assertEqual(len(self.enter_r(self.frng("paused"))), 1)         # the flip block is not read
        lv = trade.rounds(self.lg)[0]["levels"]
        self.assertAlmostEqual(lv["stop_px"], 51.0 * S * 0.85)
        self.assertNotIn("rules", lv)
        self.assertNotIn("flip_stop_px", lv)
        self.assertEqual(flags.shadow_rows(self.lg, "range_flip"), [])

    def test_shadow_trades_todays_rules_and_logs_what_would_differ(self):
        self.mode("paper")
        self.mode("shadow", "range_flip")
        self.assertEqual(len(self.enter_r(self.frng("paused"))), 1)         # entered: today's rules decide
        lv = trade.rounds(self.lg)[0]["levels"]
        self.assertAlmostEqual(lv["stop_px"], 51.0 * S * 0.85)
        self.assertAlmostEqual(lv["flip_stop_px"], 51.0 * S - 1.5 * 4.0 * S)   # 45: the would-be stop, kept
        rows = flags.shadow_rows(self.lg, "range_flip")
        acts = sorted(r[5] for r in rows)
        self.assertTrue(any(a.startswith("blokirano (pauza") for a in acts), acts)
        self.assertTrue(any("ATR" in a for a in acts), acts)
        self.assertEqual(self.lots(LU), [])                                  # the real account: nothing
        # the would-be stop sells where today's does not: one row, the round keeps running
        n = len(flags.shadow_rows(self.lg, "range_flip"))
        self.assertEqual(self.exits(44.9, rng=self.frng("paused")), [])
        self.assertEqual(len(flags.shadow_rows(self.lg, "range_flip")), n + 1)
        self.assertIn("ATR stop", flags.shadow_rows(self.lg, "range_flip")[0][5])
        self.assertEqual(len(self.lots(PU)), 1)

    def test_paper_the_demo_account_trades_the_new_rules_the_real_one_never(self):
        self.mode("live")                                                    # range_dca live, its proof passed
        self.mode("paper", "range_flip")
        trade.ensure(self.lg)
        for i in range(20):
            self.lg.execute("INSERT INTO range_rounds (user, token, opened_ts, closed_ts, status, cost_usd, pnl_usd, ret) "
                            "VALUES (?,?,?,?,?,?,?,?)", (PU, f"T{i}", 1, 2, "closed", 10.0, 1.0, 0.1))
        self.lg.commit()
        gate._CACHE.update(at=0.0)
        m, new, sh = trade.flip_roles([LU, PU], self.now)
        self.assertEqual((m, new, sh), ("paper", {PU}, {LU}))
        done = self.enter_r(self.frng("paused"))
        self.assertEqual([u for u, _t in done], [LU])
        self.assertEqual(self.lots(PU), [])                                  # paused: the demo account does not enter
        self.assertEqual([t["source"] for t in self.lots(LU)], [trade.SRC1])  # the real account: today's rules
        self.assertNotIn("rules", trade.rounds(self.lg, user=LU)[0]["levels"])

    def test_paper_entry_with_the_volatility_stop_no_lot_2_while_paused_and_its_stop(self):
        self.mode("paper")
        self.mode("paper", "range_flip")
        self.lim["dca_token_cap"] = 0.2
        self.assertEqual(self.enter_r(self.frng("flip_candidate")), [])     # a flip candidate: no entry
        self.assertEqual(len(self.enter_r(self.frng("normal"), px=57.0)), 1)
        r = trade.rounds(self.lg)[0]
        lv = r["levels"]
        self.assertEqual((lv["rules"], lv["stop_kind"]), ("flip", "atr"))
        self.assertAlmostEqual(lv["stop_px"], 45.0 * S)                      # 51 - 1.5 x 4
        self.assertAlmostEqual(lv["old_stop_px"], 51.0 * S * 0.85)
        self.assertEqual(self.enter_r(self.frng("paused"), px=50.0), [])    # lot 2 (-12 %) refused while paused
        self.assertEqual(len(self.lots(PU)), 1)
        self.assertEqual(len(self.enter_r(self.frng("normal"), px=50.0)), 1)   # normal again: lot 2
        out = self.exits(44.5, rng=self.frng("normal"))                     # 44.5 <= 45: the volatility stop
        self.assertIn("1,5 × ATR", out[0])
        self.assertEqual(trade.rounds(self.lg, "closed")[0]["exit_reason"], "stop")
        self.assertIn("ATR", self.lots(PU, "closed")[-1]["note"])

    def test_paper_entry_on_the_range_after_a_break_that_todays_rules_do_not_see(self):
        self.mode("paper")
        self.mode("paper", "range_flip")
        r = self.frng("flipped")
        r.update(active=False, status="probijen gore", score=0.8)           # today's range: no entry
        r["flip"]["alt"] = {"status": "aktivan", "active": True, "score": 0.8, "ratio": 1.4, "why": "",
                            "zones": {"range_low_low": 51.0 * S, "range_low_top": 53.0 * S,
                                      "range_high_low": 95.0 * S, "range_high_top": 100.0 * S}}
        done = self.enter_r(r)
        self.assertEqual(len(done), 1)
        self.assertEqual(trade.rounds(self.lg)[0]["levels"]["flip_state"], "flipped")

    def test_live_needs_the_flip_gate_for_the_real_account(self):
        self.mode("live", "range_flip")
        gate._FCACHE.update(at=0.0)
        m, new, sh = trade.flip_roles([LU, PU], self.now)
        self.assertEqual((new, sh), ({PU}, {LU}))                            # no nightly result: the real one stays
        con = data.connect()
        data.kv_put(con, "flip_backtest", {"ts": self.now, "tokens": 5, "old": {"rounds": 30, "max_dd_sol": 0.03},
                                           "new": {"rounds": 30, "max_dd_sol": 0.02}})
        con.commit()
        con.close()
        gate._FCACHE.update(at=0.0)
        self.assertEqual(trade.flip_roles([LU, PU], self.now)[1], {LU, PU})


class LiveGate(TradeBase):
    def put(self, **kw):
        con = data.connect()
        data.kv_put(con, "flip_backtest", kw)
        con.commit()
        con.close()
        gate._FCACHE.update(at=0.0)

    def test_settings_flag_g26_off_by_default_live_gate(self):
        self.assertEqual(settings.FLAGS["range_flip"][0], "G26")
        names = list(settings.FLAGS)   # 11.11.: range_missed (G27) comes after it; 12.11.: x_call_scalp (G31)
        # 14.11.: range_demo (G32, the demo account's profile) after them; 14.11. popodne: the owner switch
        # pravi_novac_sve (G33)
        self.assertEqual(names[names.index("range_flip") + 1:], ["range_missed", "x_call_scalp", "range_demo",
                                                                  "pravi_novac_sve"])
        self.assertEqual(settings.flag("range_flip", con=self.con), "off")
        self.assertNotIn("range_flip", settings.DATA_FLAGS)
        self.assertNotIn("range_flip", settings.NEVER_LIVE)
        self.assertEqual(settings.LIVE_GATES["range_flip"], "rangedca.gate:flip_live_refusal")

    def test_live_refused_without_a_backtest_with_a_worse_dd_or_too_few_rounds(self):
        settings.put(self.con, "backtest:range_flip", {"pass": True})
        self.mode("paper", "range_flip", since=self.now - 8 * 86400)
        paper = {"n": 30, "pnl": 5.0}
        with self.assertRaisesRegex(ValueError, "nema noćnog backtesta"):
            settings.set_flag(self.con, "range_flip", "live", "Jure", paper=paper, now=self.now)
        old = {"rounds": 30, "pnl_sol": 0.1, "pnl_pct": 8.0, "max_dd_sol": 0.02, "false_entries": 2}
        self.put(ts=self.now, tokens=5, old=old, new=dict(old, max_dd_sol=0.03, false_entries=1))
        with self.assertRaisesRegex(ValueError, "novi DD veći od starog.*lažnih ulaza 2.*lažnih ulaza 1"):
            settings.set_flag(self.con, "range_flip", "live", "Jure", paper=paper, now=self.now)
        self.put(ts=self.now, tokens=5, old=dict(old, rounds=29), new=dict(old, max_dd_sol=0.01))
        with self.assertRaisesRegex(ValueError, "premalo podataka"):
            settings.set_flag(self.con, "range_flip", "live", "Jure", paper=paper, now=self.now)
        # 11.11. (Jure): 30 rounds of BOTH rule sets (12 token-days prove nothing)
        self.put(ts=self.now, tokens=5, old=old, new=dict(old, rounds=12, max_dd_sol=0.01))
        with self.assertRaisesRegex(ValueError, "premalo podataka.*novo 12.*treba 30 za oba"):
            settings.set_flag(self.con, "range_flip", "live", "Jure", paper=paper, now=self.now)
        self.put(ts=self.now - 4 * 86400, tokens=5, old=old, new=dict(old, max_dd_sol=0.01))
        with self.assertRaisesRegex(ValueError, "star"):
            settings.set_flag(self.con, "range_flip", "live", "Jure", paper=paper, now=self.now)
        self.put(ts=self.now, tokens=5, old=old, new=dict(old, max_dd_sol=0.02))   # equal DD passes
        self.assertIsNone(gate.flip_refusal(now=self.now))
        self.assertEqual(settings.set_flag(self.con, "range_flip", "live", "Jure", paper=paper, now=self.now)["mode"],
                         "live")


# ---------------------------------------------------------------------------------------------------------------
class JobAndView(TradeBase):
    def run_job(self, flip_mode):
        import run_range
        self.mode("paper")
        self.mode(flip_mode, "range_flip")
        cs = tri(self.now - 12 * 3600 + 60 - self.now % 60, hours=12)
        pair = {"baseToken": {"address": MINT, "symbol": "RNG"}, "priceUsd": str(cs[-1][4]), "marketCap": cs[-1][4] * 1e9,
                "dexId": "pumpswap", "pairAddress": "Pool" + MINT[:8], "liquidity": {"usd": 25_000},
                "volume": {"m5": 5000, "h1": 60_000, "h6": 360_000}, "priceChange": {"m5": 1.0},
                "txns": {"m5": {"buys": 6, "sells": 4}, "h1": {"buys": 60, "sells": 40}}}
        logs = []
        run_range.once(now=self.now, log=logs.append, fetch=lambda toks: [pair],
                       gt_fetch=lambda pool, s, e: [c[:6] for c in cs], post=lambda *a: {}, extra=[MINT])
        return logs

    def test_off_computes_and_stores_nothing(self):
        self.run_job("off")
        con = data.connect()
        r, _st = data.load_range(con, MINT)
        self.assertNotIn("flip", r)
        self.assertNotIn("stop", r["zones"]["mc"])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM range_flip").fetchone()[0], 0)
        con.close()
        self.assertIsNone(view.candidates(min_score=0.0)["range_flip"])

    def test_shadow_keeps_the_state_versioned_in_range_db_and_the_mcp_shows_it(self):
        logs = self.run_job("shadow")
        self.assertIn("range_flip (shadow): normal 1", " ".join(logs))
        con = data.connect()
        r, _st = data.load_range(con, MINT)
        self.assertEqual(r["flip"]["state"], "normal")
        self.assertEqual(r["zones"]["flip_state"], "normal")
        self.assertAlmostEqual(r["zones"]["mc"]["stop"], r["zones"]["range_low_low"] * 0.85 * 1e9, delta=2)
        self.assertIn("stop_flip", r["zones"]["mc"])
        v, ver, state = con.execute("SELECT v, ver, state FROM range_flip WHERE token=?", (MINT,)).fetchone()
        self.assertEqual((v, ver, state), (detect.FLIP["v"], 0, "normal"))
        self.assertEqual(data.flip_load(con, MINT)["state"], "normal")
        st = data.flip_load(con, MINT)
        data.flip_save(con, MINT, dict(st, state="paused", zone={"low": 51.0 * S, "top": 53.0 * S}, ver=1, since=self.now,
                                       block="pauza nakon proboja dolje", brk={"dir": "down", "ts": self.now - 600,
                                                                                "end": self.now - 300, "close": 45 * S,
                                                                                "vol_x": 3.0}))
        con.execute("UPDATE range_flip SET v=99 WHERE token='nobody'")
        con.commit()
        self.assertIsNone(data.flip_load(con, "nobody"))
        con.close()
        d = view.candidates(min_score=0.0)
        c = d["candidates"][0]
        self.assertEqual((c["flip_status"], c["range_flip"]["status"]), ("normal", "normal"))
        self.assertIn(c["range_flip"]["stop_kind"], ("atr", "fixed"))
        self.assertEqual(c["range_flip"]["stop_today"]["rule"], "range_low_low x 0.85")
        self.assertIn("entry_ready_new_rules", c)
        fl = d["range_flip"]
        self.assertEqual(fl["flag_mode"], "shadow")
        self.assertEqual([(x["token"], x["status"]) for x in fl["tokens"]], [(MINT, "paused")])
        self.assertEqual(fl["tokens"][0]["resistance_market_cap_usd"], {"low": 51_000, "top": 53_000})
        self.assertIn("1.5 x ATR", fl["rules"])


# ---------------------------------------------------------------------------------------------------------------
class BacktestOldVsNew(unittest.TestCase):
    """The comparison on the stored candles (GeckoTerminal, 1 request per 1000 minutes): HOPE 10.-11.11. and four
    other bonded range tokens (WEALTH, PIRATE, timmy, Leonida, 7.-11.11.) and HAOBIBI 11.11. (the owner's labelled win,
    rangedca/owner.py). These are the numbers in the report. Without HAOBIBI (the 5 tokens before): old 10 rounds
    +0.118 SOL, new 8 rounds +0.047 SOL, both DD 0.025 SOL, 1 false entry each."""

    @classmethod
    def setUpClass(cls):
        cls.series = dict(load(n) for n in FIXTURES)
        cls.rep = backtest.run_tokens(cls.series)

    def test_the_fixtures(self):
        self.assertEqual(len(self.series), 6)
        self.assertIn("GxRPJsRK9TE9EgBhLxrFGcRYLGqPJe4fxtiPmdXCpump", self.series)   # HOPE
        fr = self.rep["flip"]
        self.assertEqual(fr["data"]["tokens"], 6)
        self.assertAlmostEqual(fr["data"]["days_total"], 12.47, delta=0.02)
        self.assertEqual(fr["data"]["tokens_24h_plus"], 4)

    def test_old_vs_new_numbers(self):
        v = self.rep["flip"]["variants"]
        got = {k: (v[k]["rounds"], round(v[k]["pnl_sol"], 3), round(v[k]["max_dd_sol"], 3), v[k]["false_entries"])
               for k in v}
        self.assertEqual(got["old"], (12, 0.112, 0.026, 1))   # 13.11.: entry buy share 0.45 (11.11. rules B: (10, 0.118, 0.025, 1))
        # 11.11. (Jure): pause ends on a close back above the resistance with volume, retest window 5 h (was 8,
        # +0.047): 12 token-days and < 30 rounds, no conclusion either way (14.11.: with buy share 0.45)
        self.assertEqual(got["new"], (8, 0.026, 0.026, 1))
        self.assertFalse(self.rep["flip"]["enough"])
        self.assertEqual(got["atr_only"], got["old"])                       # the volatility stop changed no round here
        self.assertEqual(got["flip_only"], got["new"])
        self.assertTrue(self.rep["flip"]["dd_ok"])
        # today's variants are the same with the flip state in the timeline (today's rules never read it)
        self.assertEqual(self.rep["variants"]["0.7"]["rounds"], 12)
        t = self.rep["flip"]["tokens"]
        timmy = next(p for p in t.values() if p["symbol"] == "timmy")
        self.assertEqual((timmy["old"]["rounds"], timmy["new"]["rounds"]), (3, 0))
        self.assertGreater(timmy["states"].get("paused", 0), 0)
        hope = t["GxRPJsRK9TE9EgBhLxrFGcRYLGqPJe4fxtiPmdXCpump"]
        self.assertEqual((hope["old"]["rounds"], hope["new"]["rounds"], hope["breaks_up"]), (0, 0, 1))
        hao = t["8tbfkL8LZYUN3ygzWMKfffqVd7tLRpWkuh2fowsepump"]   # 11.11.: a win, then the give-up on the second break down
        self.assertEqual([r["reason"] for r in hao["rounds_old"]], ["trailing", "odustajanje"])
        self.assertEqual(hao["new"]["rounds"], 2)

    def test_report_text_and_log_line(self):
        text = backtest.md(self.rep)
        self.assertIn("## range_flip: stara pravila vs nova", text)
        self.assertIn("| UKUPNO |", text)
        line = backtest.flip_line(self.rep["flip"])
        self.assertTrue(line.startswith("range flip backtest: 6 tokena, 12.47"))
        self.assertIn("premalo rundi za zaključak (staro 12, novo 8, treba 30 za oba): usporedba čeka", line)
        self.assertNotIn("DD novo <= staro", line)
        self.assertIn("Bez zaključka: premalo rundi (staro 12, novo 8, treba 30 za oba).", text)
        self.assertIn("DD novo <= staro: da", backtest.flip_line(dict(self.rep["flip"], enough=True)))

    def test_cost_is_the_owners_round_trip(self):
        self.assertAlmostEqual(backtest.cost(15.0, 40_000.0), 0.02 + 2 * 15 / 20_015)
        r = {"cost": 30.0, "lot_px": [1.0, 0.9], "closed": 1, "exits": [{"frac": 0.5, "px": 1.2, "n_lots": 2},
                                                                         {"frac": 1.0, "px": 1.1, "n_lots": 2}]}
        units = 15 / 1.0 + 15 / 0.9
        want = units * 0.5 * 1.2 + units * 0.5 * 1.1 - 30 - 30 * backtest.cost(30.0, None)
        self.assertAlmostEqual(backtest.priced(r)[0], want)

    def test_nightly_run_logs_the_line_and_keeps_the_result_for_the_gate(self):
        import tempfile
        d = tempfile.mkdtemp()
        tok, (cs, sup, _liq, sym) = load("range_timmy_20261111.json.gz")
        with mock.patch.dict(os.environ, {"RANGE_DB": os.path.join(d, "range.db"), "RANGE_HYPE_DB": os.path.join(d, "h.db")}), \
                mock.patch.object(data, "ROOT", d), mock.patch.object(backtest, "tokens_with_data", lambda *a, **k: [tok]), \
                mock.patch.object(backtest, "load", lambda rcon, t, now, days=14: (cs, sup, None, sym)):
            logs = []
            backtest.run_server(now=cs[-1][0] + 60, log=logs.append)
            self.assertTrue(any(x.startswith("range flip backtest: 1 tokena") for x in logs), logs[-3:])
            r = gate.flip_result()
            self.assertEqual((r["old"]["rounds"], r["new"]["rounds"], r["tokens"], r["enough"]), (3, 0, 1, False))
            self.assertIn("premalo podataka", gate.flip_refusal(now=cs[-1][0] + 120))


if __name__ == "__main__":
    unittest.main()
