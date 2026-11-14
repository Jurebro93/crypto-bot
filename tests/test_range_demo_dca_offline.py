"""14.11. popodne (Jure: "Probaj podignuti range za 5% ... uđe sa 60% pozicije uz DCA order. Ako padne još minus 10%,
ostatak 40% pozicije ... Paziti na iznos fija za svaki trade ... 50 do 100 dnevno"; "na istom tokenu može dnevno
napraviti 10 raidova ... 50 centi ili 1 euro u profitu"; "sve s pravim novcem"). The range SCALP profile (rules.DEMO on
the demo account, rules.SCALP on the real account under the owner's switch pravi_novac_sve): the entry at 30 % / up to
the bottom zone's top x 1.10, lot 1 60 % + one DCA lot 2 40 % at -10 %, the stop under the DCA (-17..-25 % from lot 1),
the TP on the average entry net of both buys, the fee guard, the demo account's raised caps (focus 10, 10 rounds a token
a day, 5 / 20 min cooldown, max_open 10), the daily counter's goal 100 with the day's net, the real account untouched
while the switch is off, and with it on: the executor's caps with Croatian reasons, the real-fee math, the exit plan,
lot 2 through run_trade's executor path (mocked). No network.

    python3 -m unittest tests.test_range_demo_dca_offline
"""
import gzip
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from league import exitplan, store  # noqa: E402
from rangedca import backtest, data, gate, rules, trade, view  # noqa: E402
from trade import cost as tcost, executor, settings  # noqa: E402
from tests.test_range_dca_offline import LU, MINT, PU, S, TradeBase  # noqa: E402

D = 86400
FX = os.path.join(ROOT, "tests", "fixtures")
SURV = {"ok": True, "crashed": False, "age_h": 72.0, "loss_24h": -0.2, "in_range": True,
        "why": "preživio pad: star 3,0 d, MC −20 % od prije 24 h, opet u rasponu"}
LIQ = 25_000.0
DEMO_REAL = (31, 0.968, 5.3, 14.77, 3.48)   # the scalp at the real costs, 0.1 SOL, all at the target


def fx_series(names):
    out = {}
    for n in names:
        with gzip.open(os.path.join(FX, n), "rt") as f:
            fx = json.load(f)
        out[fx["token"]] = (data.merge([tuple(r) for r in fx["candles"]], []), fx["supply"], None, fx.get("symbol"))
    return out


# ---------------------------------------------------------------------------------------------------------------
class Rules(unittest.TestCase):
    """The pure rules: entry, levels, the DCA, the fee guard, the real cost."""

    LV = {"rll": 51.0, "rlt": 53.0, "rhl": 95.0, "rht": 100.0, "stop_px": 43.35, "floor_px": 46.92}

    def rng(self, score=0.8, sv=SURV, z=None, **m):
        zz = {"range_low_low": 51.0, "range_low_top": 53.0, "range_high_low": 95.0, "range_high_top": 100.0}
        zz.update(z or {})
        mm = {"ch_5m": 0.01, "buy_share_5m": 0.6, "vol_ratio": 0.8}
        mm.update(m)
        return {"active": True, "status": "aktivan", "score": score, "pos_pct": 2.0, "zones": zz, "metrics": mm,
                "survivor": sv}

    def test_the_numbers_and_the_real_rules_unchanged(self):
        d = rules.DEMO
        self.assertEqual((d["entry_bottom"], d["entry_rlt_x"], d["lot1_share"], d["lot2"], d["lot2_lo"], d["lot2_hi"]),
                         (0.30, 1.10, 0.6, True, 0.10, 0.15))
        self.assertEqual((d["stop_min_pct"], d["stop_max_pct"], d["tp_usd"], d["tp1_share"], d["time_stop_s"]),
                         (0.17, 0.25, 0.60, 0.5, 6 * 3600))
        self.assertEqual((d["cooldown_tp_s"], d["cooldown_s"], d["rounds_token_day"], d["focus_n"], d["max_open"],
                          d["max_rt_cost"], d["give_up_volume"]), (300, 1200, 10, 10, 10, 0.05, False))
        self.assertEqual(rules.DEMO_GOAL, 100)
        self.assertEqual((rules.SCALP["profile"], rules.SCALP["tp1_share"]), ("scalp", 1.0))   # one sale (fees)
        same = [k for k in d if k not in ("profile", "tp1_share")]
        self.assertEqual({k: rules.SCALP[k] for k in same}, {k: d[k] for k in same})
        # the real account's RULES exactly as before
        r = rules.RULES
        self.assertEqual((r["score_min"], r["entry_bottom"], r["lot2_lo"], r["lot2_hi"], r["cooldown_s"], r["stop_x"]),
                         (0.7, 0.15, 0.10, 0.15, 1200, 0.85))
        for k in ("lot1_share", "tp_usd", "entry_rlt_x", "cooldown_tp_s", "focus_n", "max_rt_cost"):
            self.assertNotIn(k, r)
        self.assertEqual(rules.DEMO_1411["entry_bottom"], 0.25)            # the morning's profile kept as it was

    def test_entry_at_30_percent_or_up_to_the_bottom_zone_top_x_1_10(self):
        D_ = rules.DEMO
        px30 = 51.0 + 0.30 * 49.0
        self.assertIsNone(rules.entry_check(self.rng(), px30, D_))
        self.assertIsNone(rules.entry_check(self.rng(), 51.0 + 0.29 * 49.0, D_))
        self.assertIn("ulaz u donjih 30% ili do 10% iznad donje zone", rules.entry_check(self.rng(), px30 + 0.6, D_))
        self.assertIn("raspona", rules.entry_check(self.rng(), px30, rules.DEMO_1411))   # 25 % before
        self.assertIn("raspona", rules.entry_check(self.rng(score=0.8), px30))          # RULES: 15 %
        wide = self.rng(z={"range_low_top": 70.0})                           # a wide bottom zone: rlt x 1.10 = 77
        self.assertIsNone(rules.entry_check(wide, 76.9, D_))                 # 52 % of the range, inside 77
        self.assertIsNotNone(rules.entry_check(wide, 77.2, D_))
        self.assertIsNotNone(rules.entry_check(wide, 76.9, rules.DEMO_1411))
        self.assertIn("ispod range_low_low", rules.entry_check(self.rng(), 46.0, D_))    # the floor holds
        crashed = {"ok": False, "crashed": True, "why": "nije preživio pad: MC −60 % od prije 24 h (granica −45 %)"}
        self.assertEqual(rules.entry_check(self.rng(sv=crashed), 52.0, D_), crashed["why"])

    def test_the_stop_sits_under_the_dca_level(self):
        rt = tcost.round_trip(9.0, LIQ)
        near = rules.demo_levels(dict(self.LV, stop_px=50.0, stop_kind="atr"), 52.0, rt, rules.DEMO, cost_usd=9.0)
        self.assertAlmostEqual(near["stop_px"], 52.0 * 0.83)                 # never closer than -17 % from lot 1
        dca = 52.0 * (1 - rules.DEMO["lot2_lo"])
        self.assertLess(near["stop_px"], dca * (1 - 0.075))                  # 7.8 % under the DCA price
        wide = rules.demo_levels(dict(self.LV, stop_px=30.0, stop_kind="atr"), 52.0, rt, rules.DEMO, cost_usd=9.0)
        self.assertAlmostEqual(wide["stop_px"], 52.0 * 0.75)                 # never wider than -25 %
        self.assertEqual((near["lot1_px"], near["profile"], near["tp_usd"], near["cost_usd"]), (52.0, "demo", 0.6, 9.0))
        self.assertAlmostEqual(near["tp1_px"], 52.0 * (1 + 0.6 / 9.0) / (1 - rt))   # +$0.60 net on lot 1's $9
        self.assertIs(rules.profile_cfg(near), rules.DEMO)
        self.assertIs(rules.profile_cfg(dict(near, profile="scalp")), rules.SCALP)

    def test_the_tp_on_the_average_entry_net_of_both_buys(self):
        rt1 = tcost.round_trip(9.0, LIQ)
        lv1 = rules.demo_levels(self.LV, 52.0, rt1, rules.DEMO, cost_usd=9.0)
        p2 = 52.0 * 0.9
        avg = 15.0 / (9.0 / 52.0 + 6.0 / p2)
        rt2 = tcost.round_trip(15.0, LIQ)
        lv2 = rules.demo_retarget(lv1, avg, rt2, 15.0, rules.DEMO)
        self.assertAlmostEqual(lv2["tp1_px"], avg * (1 + 0.6 / 15.0) / (1 - rt2))
        self.assertLess(lv2["tp1_px"], lv1["tp1_px"])                          # the DCA brings the target closer
        self.assertEqual((lv2["stop_px"], lv2["stop_clamp"], lv2["dca"]), (lv1["stop_px"], lv1["stop_clamp"], True))
        # sold whole at TP1 by league/store's own fill model (1 % a side + the AMM impact of each lot): >= +$0.60 net
        fee = store.FEE
        q = sum(u / (px * (1 + fee) / (1 - store.impact(u, LIQ))) for u, px in ((9.0, 52.0), (6.0, p2)))
        gross = q * lv2["tp1_px"]
        net = gross * (1 - fee) * (1 - store.impact(gross, LIQ)) - 15.0
        self.assertGreaterEqual(net, 0.595)
        self.assertLess(net, 0.65)

    def test_the_fee_guard(self):
        rt = tcost.round_trip(9.0, LIQ)
        narrow = rules.demo_levels(dict(self.LV, rht=54.0), 52.0, rt, rules.DEMO, cost_usd=9.0)
        why = rules.fee_guard(narrow, rules.DEMO)
        self.assertIn("nedostižan unutar raspona", why)
        self.assertIn("+$0.60 neto", why)
        self.assertIsNone(rules.fee_guard(rules.demo_levels(self.LV, 52.0, rt, rules.DEMO, cost_usd=9.0), rules.DEMO))
        dear = dict(rules.demo_levels(self.LV, 52.0, 0.06, rules.DEMO, cost_usd=9.0))
        self.assertIn("trošak runde 6.0%", rules.fee_guard(dear, rules.DEMO))
        self.assertIn("lot 2 ne bi bio profitabilan", rules.fee_guard(dear, rules.DEMO, lot=2))
        self.assertIsNone(rules.fee_guard(dear, rules.DEMO_1411))              # the rule sets without a guard
        self.assertIsNone(rules.fee_guard(dear, rules.RULES))

    def test_the_dca_check(self):
        lv = dict(self.LV, stop_px=52.0 * 0.80, floor_px=52.0 * 0.80)
        m = {"vol_ratio": 0.8, "buy_share_5m": 0.6}
        p = 52.0 * 0.9
        self.assertIsNone(rules.demo_lot2_check(52.0, p, lv, self.rng(), m, rules.DEMO))
        self.assertIn("tek 9.0%", rules.demo_lot2_check(52.0, 52.0 * 0.91, lv, self.rng(), m, rules.DEMO))
        self.assertIn("dublje od -15%", rules.demo_lot2_check(52.0, 52.0 * 0.84, lv, self.rng(), m, rules.DEMO))
        self.assertIn("nije aktivan", rules.demo_lot2_check(52.0, p, lv, dict(self.rng(), active=False), m, rules.DEMO))
        crashed = {"crashed": True, "why": "nije preživio pad: MC −60 %"}
        self.assertEqual(rules.demo_lot2_check(52.0, p, lv, self.rng(sv=crashed), m, rules.DEMO), crashed["why"])
        close = dict(lv, stop_px=52.0 * 0.87, floor_px=52.0 * 0.87)           # the DCA only 3.4 % above the stop
        self.assertIn("iznad stopa", rules.demo_lot2_check(52.0, p, close, self.rng(), m, rules.DEMO))
        self.assertIn("kupnje ispod 45%", rules.demo_lot2_check(52.0, p, lv, self.rng(), dict(m, buy_share_5m=0.44),
                                                                 rules.DEMO))
        self.assertIsNone(rules.demo_lot2_check(52.0, p, lv, self.rng(), dict(m, vol_ratio=0.4), rules.DEMO))

    def test_the_real_cost_and_the_give_ups(self):
        rt = rules.real_cost([9.0, 6.0], LIQ, 0.004, tx_usd=0.05, sells=2)
        imp = tcost.impact
        self.assertAlmostEqual(rt, 2 * 0.004 + (9 * imp(9, LIQ) + 6 * imp(6, LIQ)) / 15 + imp(15, LIQ) + 4 * 0.05 / 15)
        self.assertEqual(rules.pool_fee(url="https://dexscreener.com/solana/pumpswap-abc"), 0.003)
        self.assertEqual(rules.pool_fee(url="https://dexscreener.com/solana/raydium-abc"), 0.0025)
        self.assertEqual((rules.n_sells(rules.DEMO), rules.n_sells(rules.SCALP)), (2, 1))
        quiet = {"why": "volumen zadnjeg sata pao ispod pola prosjeka 6 h", "ts": 1}
        broke = {"why": "raspon probijen dolje 2 puta u 24 h", "ts": 1}
        self.assertFalse(rules.gives_up(quiet, rules.DEMO))                  # the scalp waits through a quiet hour
        self.assertTrue(rules.gives_up(broke, rules.DEMO))
        self.assertTrue(rules.gives_up(quiet, None))                          # RULES unchanged
        self.assertTrue(rules.gives_up(quiet, rules.DEMO_1411))


# ---------------------------------------------------------------------------------------------------------------
class DemoScalp(TradeBase):
    """The demo account on the scalp profile (range_demo paper)."""

    def setUp(self):
        super().setUp()
        self.mode("paper")
        self.mode("paper", "range_demo")
        trade._BLOCKS_SEEN.clear()
        trade._CACHE.pop("demo_log", None)
        trade._CACHE.pop("tx_fee", None)
        trade._LOT2_SAID.clear()

    def drng(self, score=0.8, **m):
        r = self.rng(score, **m)
        r["survivor"] = dict(SURV)
        return r

    def round_(self, user=PU):
        return trade.rounds(self.lg, "open", user)[0]

    def test_lot_1_is_60_percent_and_the_dca_the_other_40_at_minus_10(self):
        # lot 1 at 55 (8 % up the range): its DCA at -10 % (49.5) stays above range_low_low x 0.92 (46.9); from 52
        # the DCA would be under that floor ("raspon probijen dolje"), never bought
        done = self.enter(px=55.0, rng=self.drng())
        self.assertEqual([u for u, _ in done], [PU])
        self.assertIn("scalp: lot 1 60 % uloga, pola na MC $", done[0][1])
        self.assertIn("DCA 40 % na MC $49,500", done[0][1])
        lots = self.lots(PU)
        self.assertEqual(len(lots), 1)
        self.assertAlmostEqual(lots[0]["size_usd"], 6.0)                     # 0.06 SOL at $100: 60 % of 0.1 SOL
        lv = self.round_()["levels"]
        rt1 = tcost.round_trip(6.0, LIQ)
        self.assertAlmostEqual(lv["tp1_px"], 55 * S * (1 + 0.6 / 6.0) / (1 - rt1))
        self.assertEqual((lv["profile"], lv["tp_usd"], lv["lot1_px"], lv["stake_sol"]), ("demo", 0.6, 55 * S, 0.1))
        self.assertEqual(self.enter(px=50.2, rng=self.drng()), [])           # -8.7 %: not yet
        done = self.enter(px=49.5, rng=self.drng())                          # -10 %: the DCA
        self.assertEqual(len(done), 1)
        self.assertIn("range lot 2", done[0][1])
        self.assertIn("TP1 sada MC $", done[0][1])
        lots = self.lots(PU)
        self.assertEqual([round(t["size_usd"], 6) for t in lots], [6.0, 4.0])
        self.assertEqual(lots[1]["source"], trade.SRC2)
        r = self.round_()
        avg = 10.0 / (6.0 / (55 * S) + 4.0 / (49.5 * S))
        self.assertAlmostEqual(r["levels"]["tp1_px"], avg * (1 + 0.6 / 10.0) / (1 - tcost.round_trip(10.0, LIQ)))
        self.assertAlmostEqual(r["levels"]["stop_px"], lv["stop_px"])        # lot 2 never moves the stop
        self.assertEqual(self.enter(px=48.5, rng=self.drng()), [])           # one DCA only

    def test_the_stop_is_under_the_dca_and_holds_a_dca_fill(self):
        r = self.drng()
        r["atr"] = 0.2 * S                                                   # ATR stop -9 %: clamped to -17 %
        self.enter(px=55.0, rng=r)
        lv = self.round_()["levels"]
        self.assertAlmostEqual(lv["stop_px"] / S, 55 * 0.83)
        self.enter(px=49.5, rng=r)                                           # DCA 8.4 % above the stop
        self.assertEqual(len(self.lots(PU)), 2)
        self.assertEqual(self.exits(49.5, rng=r), [])                        # held
        self.assertEqual(self.exits(46.0, rng=r), [])
        out = self.exits(45.6, rng=r)
        self.assertIn("tvrdi stop scalp (ATR, -17 do -25 % od lota 1)", out[0])

    def test_half_at_the_net_target_on_the_average_entry_after_the_dca(self):
        self.enter(px=55.0, rng=self.drng())
        self.enter(px=49.5, rng=self.drng())
        self.assertEqual(len(self.lots(PU)), 2)
        tp1 = self.round_()["levels"]["tp1_px"] / S
        self.assertEqual(self.exits(tp1 - 0.05), [])
        out = self.exits(tp1 + 0.01)
        self.assertIn("pola na cilju +$0.60 neto (scalp)", out[0])
        sold = sum(t["pnl_usd"] for t in self.lots(PU, "closed"))
        self.assertAlmostEqual(sold, 0.30, delta=0.02)                      # half of +$0.60 net, both buys' fees in
        out = self.exits(tp1 * 0.999)
        self.assertEqual(out, [])
        r = self.round_()
        self.assertTrue(r["state"].get("tp1"))

    def test_the_fee_guard_is_a_reason_in_the_counter(self):
        r = self.drng()
        r["zones"] = dict(r["zones"], range_high_low=54.0 * S, range_high_top=55.0 * S)   # TP1 ~+12 % > the top
        self.assertEqual(self.enter(px=52.0, rng=r), [])
        d = trade.demo_today(self.lg, self.now)
        self.assertEqual(d["top_blocks"], [{"reason": "cilj iznad vrha raspona (trošak)", "tokens": 1}])

    def test_the_cooldowns_and_ten_rounds_a_token_a_day(self):
        trade.ensure(self.lg)

        def closed(reason, ago, opened=None):
            self.lg.execute("INSERT INTO range_rounds (user, token, opened_ts, closed_ts, status, exit_reason, levels) "
                            "VALUES (?,?,?,?, 'closed', ?, '{}')", (PU, MINT, opened or self.now - ago - 600,
                                                                   self.now - ago, reason))
            self.lg.commit()
        closed("tp2", 4 * 60)
        self.assertTrue(trade._cooldown(self.lg, PU, MINT, self.now, rules.DEMO))   # 4 min after a profit
        self.assertTrue(trade._cooldown(self.lg, PU, MINT, self.now))        # RULES: 20 min whatever the exit
        self.assertFalse(trade._cooldown(self.lg, PU, MINT, self.now + 120, rules.DEMO))   # 6 min: free again
        self.lg.execute("DELETE FROM range_rounds")
        closed("stop", 6 * 60)
        self.assertTrue(trade._cooldown(self.lg, PU, MINT, self.now, rules.DEMO))   # after a stop: 20 min
        self.assertFalse(trade._cooldown(self.lg, PU, MINT, self.now + 15 * 60, rules.DEMO))
        self.lg.execute("DELETE FROM range_rounds")
        start = trade._day_start(self.now)
        for i in range(10):
            closed("tp2", 3600, opened=max(start, self.now - 7200) + i)
        self.assertEqual(self.enter(px=52.0, rng=self.drng()), [])
        d = trade.demo_today(self.lg, self.now)
        self.assertIn({"reason": "10 rundi u tokenu danas", "tokens": 1}, d["top_blocks"])
        self.lg.execute("DELETE FROM range_rounds WHERE id IN (SELECT id FROM range_rounds LIMIT 1)")
        self.lg.commit()
        self.assertEqual(len(self.enter(px=52.0, rng=self.drng())), 1)       # the 10th round of the day

    def test_the_focus_list_and_the_demo_accounts_own_caps(self):
        toks = [f"T{i:02d}" + "x" * 40 for i in range(12)]
        rngs = {}
        for i, t in enumerate(toks):
            r = self.drng(vol_h1=10_000 + 1_000 * i)
            r["ts"] = r["mts"] = self.now
            rngs[t] = r
        self.assertEqual(self.lim["max_open"], 5)                           # the trade settings' 5 ...
        done = trade.run_once(self.lg, self.mk(52.0), self.now, rngs, self.lim, 100.0)
        self.assertEqual(len(done), 10)                                      # ... the demo profile's 10
        held = {r["token"] for r in trade.rounds(self.lg, "open", PU)}
        self.assertEqual(held, set(toks[2:]))                                # the 10 with the most volume
        d = trade.demo_today(self.lg, self.now)
        self.assertIn({"reason": "izvan fokusa (top 10 po volumenu)", "tokens": 2}, d["top_blocks"])
        lim = trade.user_limits(PU, rules.DEMO, self.lim)
        self.assertEqual((lim["max_open"], lim["max_sol_per_day"]), (10, 15.0))
        self.assertIs(trade.user_limits(LU, rules.SCALP, self.lim), self.lim)   # the real account: trade settings

    def test_the_counter_goal_100_with_the_days_net(self):
        trade.ensure(self.lg)
        for pnl in (0.5, -0.2):
            self.lg.execute("INSERT INTO range_rounds (user, token, opened_ts, closed_ts, status, pnl_usd, levels) "
                            "VALUES (?,?,?,?, 'closed', ?, '{}')", (PU, MINT, self.now - 60, self.now - 30, pnl))
        self.lg.commit()
        d = trade.demo_today(self.lg, self.now)
        self.assertEqual((d["goal"], d["closed"], d["pnl_usd"], d["avg_usd"]), (100, 2, 0.3, 0.15))
        self.assertTrue(d["text"].startswith("range demo danas: 2 tradeova (cilj 100)"), d["text"])
        self.assertIn("neto danas +0.30 $, prosjek po zatvorenoj rundi +0.15 $", d["text"])

    def test_a_quiet_hour_no_longer_sells_a_scalp_round(self):
        self.enter(px=52.0, rng=self.drng())
        quiet = self.drng()
        quiet["state"] = {"give_up": {"why": "volumen zadnjeg sata pao ispod pola prosjeka 6 h", "ts": self.now}}
        self.assertEqual(self.exits(53.0, rng=quiet), [])
        broke = self.drng()
        broke["state"] = {"give_up": {"why": "raspon probijen dolje 2 puta u 24 h", "ts": self.now}}
        out = self.exits(53.0, rng=broke)
        self.assertIn("odustajanje", out[0])

    def test_get_range_candidates_shows_the_scalp_levels(self):
        self.enter(px=52.0, rng=self.drng())
        pos = view.positions()["open"][0]
        lv = pos["exit_levels_market_cap_usd"]
        self.assertEqual(lv["dca_lot2_at (-10 % from lot 1)"], round(52 * S * 0.9 * 1e9))
        self.assertIn("take_half_at (+$0.60 net on the position)", lv)
        self.assertGreater(pos["round_cost_pct"], 2.0)
        self.assertIn("pravi_novac_sve", view.DEMO_RULES)


# ---------------------------------------------------------------------------------------------------------------
class RealAccount(TradeBase):
    """The owner's switch pravi_novac_sve (G33): off = the real account untouched; on = the scalp on the real account
    inside the executor's caps, real fees, the exit plan, lot 2 through run_trade's executor path."""

    def setUp(self):
        super().setUp()
        self.mode("paper")
        self.mode("paper", "range_demo")
        trade._BLOCKS_SEEN.clear()
        trade._CACHE.pop("demo_log", None)
        trade._CACHE.pop("tx_fee", None)
        trade._CACHE.pop("cfg", None)
        trade._LOT2_SAID.clear()

    def switch(self, on=True):
        self.mode("live" if on else "off", trade.PRAVI_FLAG)

    def drng(self, score=0.8, **m):
        r = self.rng(score, **m)
        r["survivor"] = dict(SURV)
        return r

    def test_the_switch_is_an_owner_switch_and_off_by_default(self):
        self.assertEqual(settings.FLAGS["pravi_novac_sve"][0], "P14")   # one switch for all strategies (noc/live)
        self.assertIn("range trguje scalp", settings.FLAGS["pravi_novac_sve"][1])
        self.assertIn("pravi_novac_sve", settings.OWNER_SWITCHES)
        self.assertIn("pravim novcem", settings.OWNER_SWITCH_NOTES["pravi_novac_sve"])
        self.assertEqual(settings.flag("pravi_novac_sve", self.con), "off")
        self.assertIsNone(settings.live_refusal(self.con, "pravi_novac_sve"))   # only the owner's tap moves it
        self.assertIn("range_demo", settings.NEVER_LIVE)                     # the demo profile itself never live
        from ui import assistnotes
        self.assertNotIn("pravi_novac_sve", [n for n, _m, _w in assistnotes.OWNER_FLAG_ORDERS])
        cfg = settings.merged({"size_sol": 0.1}, self.con)
        self.assertEqual((cfg["range_scalp_trades_day"], cfg["range_scalp_target_usd"]), (100, 0.6))
        self.assertIn("range_scalp_trades_day", settings.LIMITS)

    def test_switch_on_the_real_account_also_trades_market_and_event_tokens(self):
        """14.11. popodne (owner: "Sve strategije"): under the switch a token only the market list / an event brought
        is traded by the real account too (NEVER_LIVE overridden by the switch); off: never."""
        self.mode("paper", "range_market")
        rng = dict(self.drng(), sources=["market"], source="market")
        self.assertFalse(trade.allowed(rng, LU, self.now))
        self.assertTrue(trade.allowed(rng, PU, self.now))
        self.switch()
        self.assertTrue(trade.allowed(rng, LU, self.now))
        self.mode("off", "range_market")
        self.assertFalse(trade.allowed(rng, LU, self.now))                  # the source's own flag off: never

    def test_switch_off_the_real_account_is_untouched(self):
        self.assertIsNone(trade.profile(LU))
        self.assertEqual(trade.roles("paper", self.now), ([PU], [LU]))
        self.enter(px=52.0, rng=self.drng())
        self.assertEqual(self.lots(LU), [])
        self.assertEqual(len(self.lots(PU)), 1)
        self.assertFalse(exitplan.execution(LU, [], plan={"client": "range scalp: #1"})["executes"])

    def test_switch_on_the_real_account_trades_the_scalp_without_the_paper_gate(self):
        self.switch()
        self.assertEqual(trade.profile(LU)["profile"], "scalp")
        with mock.patch.object(gate, "refusal", side_effect=AssertionError("the paper-proof gate is not asked")):
            act, sh = trade.roles("paper", self.now)
            self.assertEqual((sorted(act), sh), (sorted([LU, PU]), []))
            done = self.enter(px=52.0, rng=self.drng())
        texts = dict(done)
        self.assertIn("range scalp PRAVI lot 1", texts[LU])
        self.assertIn("trošak procjena: bazen+ruta 0.35% po strani, mreža 2 swapa x 0.00050 SOL", texts[LU])
        self.assertIn("scalp: lot 1 60 % uloga, sve na MC $", texts[LU])   # the real account: one sale
        self.assertIn("plan izlaza #", texts[LU])
        lots = self.lots(LU)
        self.assertEqual(len(lots), 1)
        self.assertAlmostEqual(lots[0]["size_usd"], 6.0)                     # 60 % of the 0.1 SOL stake
        r = trade.rounds(self.lg, "open", LU)[0]
        lv = r["levels"]
        self.assertEqual((lv["profile"], lv["fee_side"], lv["tx_sol"]), ("scalp", 0.0035, rules.TX_FEE_SOL))
        rt = rules.real_cost([6.0], LIQ, 0.0035, rules.TX_FEE_SOL * 100.0, sells=1)
        self.assertAlmostEqual(lv["rt_cost"], round(rt, 5))
        self.assertAlmostEqual(lv["tp1_px"] / (52 * S * (1 + 0.6 / 6.0) / (1 - rt)), 1.0, places=9)
        # the exit plan of the round (league/exitplan): executes on the real account under the switch
        p = exitplan.active(self.lg, MINT)
        self.assertEqual(p["id"], lv["plan_id"])
        self.assertTrue(p["client"].startswith("range scalp: #"))
        self.assertEqual(p["plan"]["accounts"], [LU])
        tps = p["plan"]["take_profits"]
        self.assertEqual([t["sell_share"] for t in tps], [1.0])               # everything at the net target
        self.assertAlmostEqual(tps[0]["v"], round(lv["tp1_px"] * 1e9, 2))
        self.assertAlmostEqual(p["state"]["stop_px"][LU], lv["stop_px"])
        self.assertIsNone(p["plan"].get("trailing"))
        self.assertTrue(exitplan.execution(LU, exitplan._lots(self.lg, LU, MINT), plan=p)["executes"])
        self.assertTrue(trade.plan_runs(self.lg, r))
        self.assertIn(MINT, exitplan.in_force_tokens(self.lg, LU))

    def test_the_real_fee_math_reads_the_measured_network_fee(self):
        for i in range(6):
            self.con.execute("INSERT INTO orders (ts, mode, side, status, prio_lamports, fee_lamports) VALUES "
                             "(?,?,?,?,?,?)", (self.now - i, "dry", "buy", "dry", 95_000, 2_100_000))
        self.con.commit()
        sol, src = trade.tx_fee_sol(now=self.now)
        self.assertAlmostEqual(sol, 0.0001)                                  # 95,000 + 5,000 lamports a swap
        self.assertIn("medijan zadnjih 6 naloga", src)
        mq = (52 * S, LIQ, "https://dexscreener.com/solana/pumpswap-pool", 52_000.0)
        rt, parts = trade.round_cost(LU, [6.0, 4.0], LIQ, 100.0, mq, rules.SCALP)
        self.assertEqual((parts["fee_side"], parts["n_tx"]), (0.004, 3))     # PumpSwap 0.3 % + route 0.1 %; 2 + 1
        self.assertAlmostEqual(rt, rules.real_cost([6.0, 4.0], LIQ, 0.004, 0.01, sells=1))
        self.assertAlmostEqual(parts["net_usd"], 0.03)
        rt_d, parts_d = trade.round_cost(PU, [6.0, 4.0], LIQ, 100.0, mq, rules.DEMO)
        self.assertEqual(parts_d["model"], "demo")
        self.assertAlmostEqual(rt_d, tcost.round_trip(10.0, LIQ))
        self.assertIn("ukupno", trade.cost_words(parts, 10.0))

    def test_the_fee_guard_refuses_when_the_network_fee_eats_the_target(self):
        self.switch()
        trade._CACHE["tx_fee"] = (self.now + 10_000, 0.003, "test")           # 0.003 SOL a swap: 10 % of $6
        done = self.enter(px=52.0, rng=self.drng())
        self.assertEqual([u for u, _ in done], [PU])
        d = trade.demo_today(self.lg, self.now, LU)
        self.assertEqual(d["top_blocks"], [{"reason": "trošak runde iznad 5 %", "tokens": 1}])
        self.assertTrue(d["text"].startswith("range scalp PRAVI račun danas: 0 tradeova"), d["text"])

    def test_the_executors_caps_refuse_with_croatian_reasons(self):
        self.switch()
        with tempfile.TemporaryDirectory() as td:
            stop = os.path.join(td, "STOP")
            open(stop, "w").close()
            with mock.patch.object(executor, "STOP_FILE", stop):
                self.enter(px=52.0, rng=self.drng())
        self.assertEqual(self.lots(LU), [])
        d = trade.demo_today(self.lg, self.now, LU)
        self.assertEqual(d["top_blocks"], [{"reason": "pravi račun: kill switch", "tokens": 1}])
        why = trade.precheck(self.lg, LU, MINT, 0.06, self.now, lim=self.lim)
        self.assertIsNone(why)
        for i in range(5):   # the trade settings' max_open 5 (config.json) of real (dry) positions
            self.con.execute("INSERT INTO positions (token, opened_ts, mode, status, sol_in) VALUES (?,?,?,?,?)",
                             (f"P{i}" + "x" * 40, self.now, "dry", "open", 0.0))
        self.con.commit()
        why = trade.precheck(self.lg, LU, MINT, 0.06, self.now, lim=self.lim)
        self.assertIn("pravi račun (dry): najviše otvorenih pravih pozicija: 5 otvorenih pozicija", why)
        self.con.execute("DELETE FROM positions")
        self.con.commit()
        settings.put(self.con, "range_scalp_trades_day", 1)
        trade._CACHE.update(lim=None, lim_at=0.0, cfg=None)
        self.assertEqual(len(self.lots(LU)), 0)
        trade._BLOCKS_SEEN.clear()
        self.lg.execute("DELETE FROM range_blocks")
        self.lg.commit()
        self.enter(px=52.0, rng=self.drng())
        self.assertEqual(len(self.lots(LU)), 1)
        why = trade.precheck(self.lg, LU, "Q" * 44, 0.06, self.now, lim=self.lim)
        self.assertEqual(why, "pravi račun: već 1 range scalp rundi danas (limit range_scalp_trades_day 1)")
        self.assertEqual(trade.block_key(why), "pravi račun: dnevni broj rundi")
        self.assertIsNone(trade.precheck(self.lg, PU, "Q" * 44, 0.06, self.now, lim=self.lim))   # demo: no caps here

    def test_the_plan_sells_the_real_lots_and_the_round_ends_by_it(self):
        self.switch()
        self.enter(px=52.0, rng=self.drng())
        r = trade.rounds(self.lg, "open", LU)[0]
        tp1 = r["levels"]["tp1_px"] / S
        mk = (lambda px: (lambda toks: {t: (px * S, LIQ, None, px * S * 1e9) for t in toks}))
        out = self.exits(tp1 + 0.05)
        self.assertFalse([t for t in out if f"range {LU}" in t], out)        # the range module leaves LU to the plan
        lot = self.lots(LU)[0]
        self.assertAlmostEqual(lot["qty"] / (lot["size_usd"] / lot["entry_eff"]), 1.0)
        done = exitplan.run_once(self.lg, mk(tp1 + 0.05), self.now)
        self.assertEqual([(u, trig) for u, _t, trig, _x in done], [(LU, "tp1")])
        self.assertIn("pravi račun, live", done[0][3])
        self.assertEqual(self.lots(LU), [])                                  # everything sold at the net target
        out = self.exits(tp1 + 0.05)
        self.assertTrue(any("runda zatvorena (tp1" in t for t in out), out)
        r1 = trade.rounds(self.lg, "closed", LU)[0]
        self.assertEqual(r1["exit_reason"], "tp1")
        self.assertAlmostEqual(r1["pnl_usd"], 0.6 + 0.6 * 0.05 / 6, delta=0.06)   # the league ledger's 1 % fee
        # the next round in the same token: its stop through the plan, the round's end by it
        r2 = self.drng()
        r2["ts"] = r2["mts"] = self.now + 400
        self.enter(px=52.0, rng=r2, now=self.now + 400)                      # 5 min cooldown after a profit
        r = trade.rounds(self.lg, "open", LU)[0]
        stop = r["levels"]["stop_px"] / S
        done = exitplan.run_once(self.lg, mk(stop * 0.99), self.now + 405)
        self.assertIn((LU, "stop"), [(u, trig) for u, _t, trig, _x in done])
        self.assertEqual(self.lots(LU), [])
        out = self.exits(stop * 0.99, now=self.now + 406)
        self.assertTrue(any("runda zatvorena (stop" in t for t in out), out)
        self.assertEqual(trade.rounds(self.lg, "closed", LU)[-1]["exit_reason"], "stop")

    def test_switched_off_with_a_round_open_the_range_rules_keep_the_exits(self):
        self.switch()
        self.enter(px=52.0, rng=self.drng())
        self.switch(False)
        r = trade.rounds(self.lg, "open", LU)[0]
        self.assertFalse(trade.plan_runs(self.lg, r))
        tp1 = r["levels"]["tp1_px"] / S
        self.mode("paper", "exit_plans")                                     # the real account would only shadow
        self.assertEqual(exitplan.run_once(self.lg, lambda toks: {t: (tp1 * S * 1.01, LIQ, None, tp1 * 1e3)
                                                                   for t in toks}, self.now), [])
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM exit_events").fetchone()[0], 0)   # no shadow state
        out = self.exits(tp1 + 0.05)
        self.assertTrue(any(f"range {LU}" in t and "na cilju +$0.60" in t for t in out), out)   # never left alone

    def test_the_dca_is_a_real_buy_through_run_trades_executor_path(self):
        import run_trade
        from trade import equity
        self.switch()
        self.enter(px=55.0, rng=self.drng())
        plan1 = trade.rounds(self.lg, "open", LU)[0]["levels"]["plan_id"]
        done = self.enter(px=49.5, rng=self.drng())
        self.assertTrue(any(u == LU and "range lot 2" in t for u, t in done), done)
        r = trade.rounds(self.lg, "open", LU)[0]
        self.assertNotEqual(r["levels"]["plan_id"], plan1)                  # the plan follows the average entry
        p = exitplan.active(self.lg, MINT)
        self.assertAlmostEqual(p["plan"]["take_profits"][0]["v"], round(r["levels"]["tp1_px"] * 1e9, 2))
        calls = []

        def buy(con, cfg, token, symbol=None, now=None, reason="", league_id=None, size_sol=None, add=False, **kw):
            calls.append({"reason": reason, "size_sol": size_sol, "add": add, "league_id": league_id})
            con.execute("INSERT INTO positions (league_id, token, opened_ts, mode, status, sol_in, qty_raw, qty_left) "
                        "VALUES (?,?,?,?,?,?,?,?)", (league_id, token, int(now), "dry", "open", size_sol, 1000, 1000))
            con.commit()
            return {"status": "open", "amount_in": int(size_sol * 1e9)}
        cfg = run_trade.load(con=self.con)
        with mock.patch.object(executor, "buy", buy), \
                mock.patch.object(equity, "rates", lambda *a, **k: {"sol_usd": 100.0}):
            run_trade.follow_league_once(self.con, cfg, self.now - 60, now=self.now, quiet=True)
        self.assertEqual([(c["reason"], c["add"]) for c in calls], [(trade.SRC1, False), (trade.SRC2, True)])
        self.assertAlmostEqual(calls[0]["size_sol"], 0.06)
        self.assertAlmostEqual(calls[1]["size_sol"], 0.04)


# ---------------------------------------------------------------------------------------------------------------
class Backtest(unittest.TestCase):
    """The variants on the six range fixtures (12.47 token-days, ticks wick, the ATR stop, the owner's round-trip cost):
    old RULES and the morning's profile unchanged, the DCA order (+10 / +15 %), the scalp (what the demo account
    trades) and the scalp at the real account's costs for 0.1 SOL."""

    @classmethod
    def setUpClass(cls):
        from tests.test_range_flip_offline import FIXTURES
        cls.rep = backtest.run_tokens(fx_series(FIXTURES), stops=False)

    def test_the_variants(self):
        v = self.rep["demo"]["variants"]
        got = {k: (x["rounds"], x["hit_rate"], x["ev_pct"], round(x["pnl_usd"], 2), round(x["max_dd_usd"], 2))
               for k, x in v.items()}
        self.assertEqual(got["old"], (12, 0.75, 14.1, 26.2, 3.03))
        self.assertEqual(got["demo_1411"], (21, 0.714, 5.31, 16.71, 4.07))
        self.assertEqual(got["dca"], (25, 0.92, 8.29, 21.34, 2.44))
        self.assertEqual(got["demo"], (30, 0.967, 7.18, 19.76, 3.44))
        self.assertEqual(got["demo_real"], DEMO_REAL)
        self.assertEqual(v["demo"]["lot2"]["n"], 5)                          # the DCA filled in 5 rounds
        self.assertEqual(v["demo"]["rounds_per_token_day"], 2.41)
        self.assertLess(v["demo"]["be_hit_rate"], v["demo"]["hit_rate"])
        self.assertNotIn("odustajanje", v["demo"]["exit_reasons"])          # no quiet-hour give-up any more
        line = backtest.demo_line(self.rep["demo"])
        self.assertIn("scalp $0,60 (demo): runde 30 (2.41/token-dan), pogodak 97 % (break-even 81 %)", line)
        self.assertIn(f"scalp pravi trošak 0,1 SOL: runde {DEMO_REAL[0]}", line)
        self.assertEqual(self.rep["variants"]["0.7"]["rounds"], 12)          # today's backtest untouched


if __name__ == "__main__":
    unittest.main()
