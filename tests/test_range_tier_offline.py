"""11.11. (Jure: "range_dca: adaptivni ulog po tokenu (token_tier)", rangedca/tier.py). Step up only with every
condition, down to T0 with a cooldown, no house money, the liquidity / slippage cap, paper only (the demo account),
the round's low / high and the tier at the close, zone_reset after a new higher range, the backtest comparison
(fixed vs tier) and the replay on Hope's stored candles of 10.11. No network.

    python3 -m unittest tests.test_range_tier_offline
"""
import gzip
import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from league import store  # noqa: E402
from rangedca import backtest, data, detect, tier, trade, view  # noqa: E402
from tests.test_pozicije_izlaz_offline import MINT  # noqa: E402
from tests.test_range_dca_offline import LU, PU, S, T0, TradeBase, path, tri  # noqa: E402

GOOD = {"score": 0.8, "rug_clean": True, "broken_down": False,
        "activity": {"vol_h1_med6": 20_000.0, "tx_h1": 300, "tx_h1_avg24": 320.0}}


def win(st, low, high=None, pnl=0.05, ctx=GOOD, reason="top"):
    return tier.step(st, {"pnl_sol": pnl, "reason": reason, "low_mc": low, "high_mc": high}, ctx)


class Rules(unittest.TestCase):
    def test_up_only_after_three_wins_with_higher_lows_and_one_tier_at_a_time(self):
        st = win(None, 50_000)
        self.assertEqual(st["tier"], 0)                                   # 1 win, no previous low
        st = win(st, 55_000)
        self.assertEqual(st["tier"], 0)                                   # 2 wins: needs 3
        self.assertIn("profitabilne runde", st["reason"])
        st = win(st, 60_000)
        self.assertEqual((st["tier"], st["moved"]), (1, 1))
        self.assertEqual(st["reason"], "3 runde +, higher lows 55k→60k")
        for low in (65_000, 70_000, 75_000, 80_000):
            st = win(st, low)
        self.assertEqual(st["tier"], 3)                                   # max T3
        self.assertEqual(tier.label(st, 0.3), "Tier T3 · ulog 0.3 · razlog: " + st["reason"])

    def test_every_condition_blocks_the_step_up(self):
        base = {"tier": 1, "wins": 5, "last_bottom": 60_000}
        bad = [({"low": 59_000}, "higher lows"),
               ({"ctx": dict(GOOD, activity=dict(GOOD["activity"], vol_h1_med6=9_000))}, "volumen 1 h"),
               ({"ctx": dict(GOOD, activity=dict(GOOD["activity"], tx_h1=200))}, "transakcije"),   # -37.5 %
               ({"ctx": dict(GOOD, activity=dict(GOOD["activity"], tx_h1=None))}, "transakcije"),
               ({"ctx": dict(GOOD, score=0.65)}, "range_score"),
               ({"ctx": dict(GOOD, rug_clean=False)}, "rug")]
        for b, word in bad:
            st = win(base, b.get("low", 65_000), ctx=b.get("ctx", GOOD))
            self.assertEqual(st["tier"], 1, word)
            self.assertIn(word, st["reason"])
        self.assertEqual(win(base, 65_000)["tier"], 2)
        self.assertEqual(win(dict(base, tier=1, wins=1), 65_000)["tier"], 1)   # 2 wins in total

    def test_down_to_t0_at_once_with_a_one_round_cooldown(self):
        t2 = {"tier": 2, "wins": 6, "wins_streak": 4, "last_bottom": 90_000}
        for rnd, ctx, why in (({"pnl_sol": -0.01, "reason": "trailing"}, GOOD, "gubitak"),
                              ({"pnl_sol": 0.01, "reason": "stop"}, GOOD, "tvrdi stop"),
                              ({"pnl_sol": 0.01, "reason": "odustajanje: dva niža dna"}, GOOD, "probijeno dno"),
                              ({"pnl_sol": 0.01, "reason": "top"}, dict(GOOD, broken_down=True), "probijeno dno")):
            st = tier.step(t2, dict(rnd, low_mc=95_000), ctx)
            self.assertEqual((st["tier"], st["cooldown"]), (0, 1), why)
            self.assertIn(why, st["reason"])
        st = tier.step(t2, {"pnl_sol": -0.01, "reason": "stop", "low_mc": 95_000}, GOOD)
        st = win(st, 100_000)                                               # the cooldown round: no step up
        self.assertEqual((st["tier"], st["cooldown"]), (0, 0))
        self.assertIn("pauza", st["reason"])
        self.assertEqual(win(st, 105_000)["tier"], 1)                       # then it may climb again

    def test_lower_highs_twice_in_a_row(self):
        st = {"tier": 2, "wins": 6, "last_bottom": 50_000, "last_top": 120_000}
        st = win(st, 55_000, high=110_000)
        self.assertEqual(st["tier"], 3)                                     # one lower high: still up
        st = win(st, 58_000, high=100_000)
        self.assertEqual((st["tier"], st["cooldown"]), (0, 1))
        self.assertIn("lower highs", st["reason"])

    def test_a_round_at_zero_moves_nothing(self):
        st = tier.step({"tier": 2, "wins": 5}, {"pnl_sol": 0.0, "reason": "time", "low_mc": 70_000}, GOOD)
        self.assertEqual((st["tier"], st["moved"]), (2, 0))

    def test_no_house_money_and_the_liquidity_and_slippage_cap(self):
        rich = tier.step({"tier": 0, "realized_pnl_sol": 50.0, "wins": 1}, {"pnl_sol": 2.0, "reason": "top"}, GOOD)
        self.assertEqual(rich["tier"], 0)                                   # big realized PnL, no higher lows
        self.assertEqual(tier.size(rich["tier"], 1e6, 100.0, impact=store.impact)[0], 0.15)
        self.assertEqual(tier.size(3, 1e6, 100.0, impact=store.impact), (0.3, None))
        lot, why = tier.size(3, 1_000.0, 100.0)                             # 1.5 % of $1k = $15 = 0.15 SOL
        self.assertEqual((lot, "likvidnosti" in why), (0.15, True))
        lot, why = tier.size(3, 1e6, 100.0, impact=lambda usd, liq: 0.03 if usd > 20 else 0.01)
        self.assertLessEqual(lot * 100.0, 20.0)
        self.assertIn("slippage", why)
        self.assertEqual(tier.ladder(0.1), (0.1, 0.2, 0.25, 0.3))
        self.assertEqual(tier.ladder(0.22), (0.22, 0.22, 0.25, 0.3))       # no tier under the base stake
        with mock.patch.dict(os.environ, {"RANGE_TIER_SIZES": "0.1,0.12,0.14,0.16"}):
            self.assertEqual(tier.sizes(), (0.1, 0.12, 0.14, 0.16))
        with mock.patch.dict(os.environ, {"RANGE_TIER_SIZES": "0.3,0.2"}):
            self.assertEqual(tier.sizes(), tier.SIZES_DEFAULT)

    def test_activity_from_the_candles(self):
        now = T0 + 24 * 3600 - 1
        cs = [(T0 + k * 60, 1, 1, 1, 1, 100.0 if k >= 18 * 60 else 10.0, 3, 2) for k in range(24 * 60)]
        a = tier.activity(cs, now)
        self.assertAlmostEqual(a["vol_h1_med6"], 6000.0)                   # 60 minutes x $100 per hour
        self.assertEqual(a["tx_h1"], 300)
        self.assertAlmostEqual(a["tx_h1_avg24"], 300.0, places=1)
        self.assertIsNone(tier.activity([c[:6] + (None, None) for c in cs], now)["tx_h1"])


class Trader(TradeBase):
    def setUp(self):
        super().setUp()
        self.mode("paper")

    def test_the_demo_account_trades_its_tier_the_real_account_keeps_size_sol(self):
        tier.save(self.lg, PU, MINT, dict(tier.blank(), tier=2, reason="4 runde +, higher lows 95k→103k"))
        tier.save(self.lg, LU, MINT, dict(tier.blank(), tier=3))
        self.lg.commit()
        done = self.enter()
        self.assertEqual([u for u, _ in done], [PU])
        self.assertIn("Tier T2 · ulog 0.25 · razlog: 4 runde +, higher lows 95k→103k", done[0][1])
        self.assertAlmostEqual(self.lots(PU)[0]["size_usd"], 25.0)          # 0.25 SOL x $100
        self.assertEqual(trade.rounds(self.lg)[0]["levels"]["lot_sol"], 0.25)
        self.assertEqual(trade.stake(self.lg, LU, MINT, self.lim, 25_000.0, 100.0)[0], 0.1)
        with mock.patch.dict(os.environ, {"RANGE_TIER": "off"}):
            self.assertEqual(trade.stake(self.lg, PU, MINT, self.lim, 25_000.0, 100.0)[0], 0.1)
        lot, cap, note = trade.stake(self.lg, PU, MINT, self.lim, 10_000.0, 100.0)   # 1.5 % of $10k = 1.5 SOL: T2
        self.assertEqual((lot, round(cap, 3)), (0.25, 0.75))                       # the cap scales: 0.3 x 2.5
        lot, cap, note = trade.stake(self.lg, PU, MINT, self.lim, 1_000.0, 100.0)    # thin pool: impact > 2 %
        self.assertLess(lot, 0.15)
        self.assertLessEqual(store.impact(lot * 100.0, 1_000.0), 0.02)
        self.assertIn("slippage", note)

    def test_lot_2_uses_the_rounds_stake_under_the_scaled_cap(self):
        tier.save(self.lg, PU, MINT, dict(tier.blank(), tier=3))
        self.lg.commit()
        self.assertEqual(len(self.enter(px=57.0)), 1)
        self.assertEqual(len(self.enter(px=50.0)), 1)                       # -12.3 %
        self.assertEqual([round(t["size_usd"], 6) for t in self.lots(PU)], [30.0, 30.0])   # cap 0.3 x 3 = 0.9

    def test_the_close_counts_the_round_with_its_low_and_high(self):
        tier.save(self.lg, PU, MINT, dict(tier.blank(), tier=0, wins=2, last_bottom=40_000))
        self.lg.commit()
        self.enter(px=52.0)
        rng = self.rng()
        rng["metrics"]["activity"] = GOOD["activity"]
        with mock.patch.object(trade, "sol_usd", lambda: 100.0):
            self.exits(51.5, rng)                                           # the round's low
            self.exits(95.5, rng)
            self.exits(101.0, rng)
            out = self.exits(99.0, rng)
        self.assertIn("tier T1", out[-1])
        st = tier.get(self.lg, PU, MINT)
        self.assertEqual((st["tier"], st["wins"], st["rounds"], st["prev_bottom"]), (1, 3, 1, 40_000))
        self.assertAlmostEqual(st["last_bottom"], 51_500, delta=1)
        self.assertGreater(st["realized_pnl_sol"], 0.05)
        self.assertGreater(st["last_top"], 98_000)

    def test_a_stopped_round_drops_the_tier(self):
        tier.save(self.lg, PU, MINT, dict(tier.blank(), tier=2, wins=5))
        self.lg.commit()
        self.enter(px=52.0)
        with mock.patch.object(trade, "sol_usd", lambda: 100.0):
            out = self.exits(40.0)
        self.assertIn("tier T0", out[-1])
        st = tier.get(self.lg, PU, MINT)
        self.assertEqual((st["tier"], st["cooldown"]), (0, 1))

    def test_the_mcp_row_shows_the_tier_and_grok_stays_under_its_limit(self):
        tier.save(self.lg, PU, MINT, dict(tier.blank(), tier=3, reason="5 runde +, higher lows 95k→103k"))
        self.lg.commit()
        rows = tier.all_for(self.lg)
        with mock.patch.object(trade, "limits", lambda now=None: self.lim):
            ti = view.tier_info(MINT, 1e6, rows, 100.0, 0.1)
        self.assertEqual((ti["tier"], ti["size_sol"], ti["grok_size_sol"]), (3, 0.3, 0.1))
        self.assertTrue(ti["label"].startswith("Tier T3 · ulog 0.3 · razlog: 5 runde +"))
        r = self.rng()
        with mock.patch.object(view, "tiers", lambda toks: rows), mock.patch.object(view, "_grok_max", lambda: 0.1), \
                mock.patch.object(trade, "limits", lambda now=None: self.lim):
            row = view.one(MINT, r, self.now, rows, 100.0, 0.1)
        self.assertEqual((row["tier"]["tier"], row["tier"]["grok_size_sol"]), (3, 0.1))


class ZoneReset(unittest.TestCase):
    def test_a_new_higher_range_resets_the_zones_from_the_last_hours(self):
        old = tri(T0, hours=18, lo=52.0, hi=98.0, period=120)
        new = tri(old[-1][0] + 60, hours=6, lo=130.0, hi=220.0, period=90)
        cs = (old + new)[:-20]
        now = cs[-1][0]
        snap = {"ts": now, "price": cs[-1][4], "mcap": cs[-1][4] * 1e9, "liq": 80_000.0, "vol_h1": 60_000.0, "supply": 1e9}
        plain = detect.analyze(cs, now, snap)
        self.assertLess(plain["zones"]["range_low"], 60 * S)      # 24 h: the old bottom stretched up to the new tops
        res = detect.analyze_reset(cs, now, snap)
        self.assertTrue(res["active"], res.get("why"))
        self.assertGreater(res["zones"]["range_low"], 120 * S)
        zr = res["zone_reset"]
        self.assertIn(zr["window_h"], (12, 6))
        self.assertGreater(zr["to_low_mc"], zr["from_low_mc"])

    def test_no_reset_inside_the_range(self):
        cs = tri(T0, hours=12)
        now = cs[-1][0]
        snap = {"ts": now, "price": cs[-1][4], "mcap": cs[-1][4] * 1e9, "liq": 50_000.0, "vol_h1": 60_000.0, "supply": 1e9}
        self.assertNotIn("zone_reset", detect.analyze_reset(cs, now, snap))


class Backtest(unittest.TestCase):
    def test_fixed_vs_tier_on_rounds(self):
        rs = []
        for k, (ret, low, reason) in enumerate([(0.3, 50_000, "top"), (0.3, 55_000, "top"), (0.3, 60_000, "top"),
                                                (0.3, 65_000, "top"), (-0.2, 62_000, "stop"), (0.3, 70_000, "top")]):
            rs.append({"token": MINT, "closed": T0 + k * 3600, "ret": ret, "reason": reason, "low_mc": low,
                       "high_mc": None, "ctx": GOOD})
        out = backtest.tier_compare(rs, {MINT: 1e6})
        self.assertEqual(out["fixed"]["stake_sol"], 0.15)
        self.assertAlmostEqual(out["fixed"]["pnl_sol"], 0.15 * (0.3 * 5 - 0.2), places=4)
        self.assertEqual([s["tier_before"] for s in out["steps"]], [0, 0, 0, 1, 2, 0])
        self.assertAlmostEqual(out["tier"]["worst_round_sol"], -0.2 * 0.25, places=4)   # the loss at T2
        self.assertAlmostEqual(out["fixed"]["worst_round_sol"], -0.03, places=4)
        self.assertEqual(out["tier"]["rounds_by_tier"], {"T0": 4, "T1": 1, "T2": 1, "T3": 0})
        rep = {"tokens_with_data": 1, "tokens_simulated": 1, "tokens_with_range": 1, "lot_usd": 15.0,
               "variants": {}, "tokens": {}, "tier_compare": out}
        self.assertIn("Fiksni ulog vs token_tier", backtest.md(rep))

    def test_the_run_has_the_comparison(self):
        cs = tri(T0, hours=24, period=180)
        rep = backtest.run_tokens({MINT: (cs, 1e9, 50_000.0, "RNG")})
        tc = rep["tier_compare"]
        self.assertEqual(tc["fixed"]["rounds"], rep["variants"]["0.7"]["rounds"])
        self.assertTrue(all(r.get("low_mc") for r in rep["tokens"][MINT]["rounds_0.7"]))

    def test_hope_10_11_replay(self):
        with gzip.open(os.path.join(ROOT, "tests", "fixtures", "range_hope_20261110.json.gz"), "rt") as f:
            fx = json.load(f)
        cs = data.merge([tuple(r) for r in fx["candles"]], [])
        tl = backtest.timeline(cs, 1e9, None)
        rounds = backtest.simulate(cs, 1e9, tl, 0.7, True, None)
        for r in rounds:
            r["token"], r["symbol"] = fx["token"], "Hope"
        out = backtest.tier_compare(rounds, {fx["token"]: None})
        closed = [r for r in rounds if r["closed"]]
        self.assertEqual(out["fixed"]["rounds"], len(closed))
        self.assertEqual(len(out["steps"]), len(closed))
        for s in out["steps"]:
            self.assertIn(s["size_sol"], tier.sizes())
            self.assertTrue(0 <= s["tier_after"] <= 3)


class Replay(TradeBase):
    def test_tier_replay_command_reads_the_stored_series(self):
        import run_range
        rcon = data.connect()
        try:
            cs = tri(T0, hours=24, period=180, vol=2000.0)
            for c in cs[::5]:
                data.save_snap(rcon, MINT, {"ts": c[0], "price": c[4], "mcap": c[4] * 1e9, "liq": 50_000.0,
                                            "vol_m5": 10_000.0, "vol_h1": 60_000.0, "vol_h6": None, "buys_m5": 30,
                                            "sells_m5": 20, "buys_h1": 300, "sells_h1": 200, "ch_m5": 0.5})
            rcon.execute("INSERT INTO pools VALUES (?,?,?,?,?)", (MINT, "pool", "raydium", "RNG", T0))
            rcon.commit()
            lines = []
            import time as _t
            day = _t.strftime("%Y-%m-%dT%H:%M:%S", _t.gmtime(T0))
            end = _t.strftime("%Y-%m-%dT%H:%M:%S", _t.gmtime(T0 + 25 * 3600))
            out = run_range.tier_replay("rng", day, end, log=lines.append, rcon=rcon)
        finally:
            rcon.close()
        self.assertIsNotNone(out, lines)
        self.assertTrue(lines[0].startswith("tier-replay RNG"), lines)
        self.assertTrue(any(ln.strip().startswith("fixed:") for ln in lines))


if __name__ == "__main__":
    unittest.main()
