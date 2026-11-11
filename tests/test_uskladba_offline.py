"""11.11. (the owner's consolidated correction, rules A-E and H): one cost model, hard blocks only, size by slippage, the
EV proof, the signal exit and the event seeds, offline.

    python3 -m unittest tests.test_uskladba_offline
"""
import datetime as dt
import json
import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from trade import cost, edge, executor  # noqa: E402


# ---------- A. one cost model ------------------------------------------------------------------------------------------

class CostModel(unittest.TestCase):
    def setUp(self):
        cost.reset_cache()
        self.addCleanup(cost.reset_cache)

    def test_the_formula_in_fractions(self):
        # cost(size_usd, liq) = 2 x fee_side + 2 x size_usd / (liq / 2 + size_usd); fee_side = league/store.FEE
        from league import store as lstore
        self.assertEqual(cost.FEE_DEMO, lstore.FEE)
        c = cost.round_trip(15.0, 40_000, fee=0.01)
        self.assertAlmostEqual(c, 0.02 + 2 * 15 / (20_000 + 15))
        self.assertAlmostEqual(cost.impact(15.0, 40_000), lstore.impact(15.0, 40_000))
        self.assertAlmostEqual(cost.round_trip(0, 40_000, fee=0.01), 0.02)
        self.assertGreater(cost.round_trip(100, 15_000, fee=0.01), cost.round_trip(100, 60_000, fee=0.01))
        self.assertAlmostEqual(cost.round_trip(15.0, None, fee=0.01), cost.round_trip(15.0, cost.DEFAULT_LIQ, fee=0.01))
        self.assertEqual(cost.FEE_ROUND_TRIP, 0.02)

    def test_every_ev_reads_the_same_model(self):
        from fast import checks as fchecks
        from kol import tpsl
        from momentum import evgate, rules
        from proposals import build
        from scan import store as sstore
        self.assertAlmostEqual(rules.round_trip_cost(15.0, 40_000), cost.round_trip(15.0, 40_000))
        self.assertAlmostEqual(evgate.cost(0.1, 150.0, 40_000), cost.round_trip(15.0, 40_000))
        self.assertAlmostEqual(build.cost_for(40_000, 37.5), cost.round_trip(37.5, 40_000))
        self.assertIsNone(build.cost_for(14_999))
        self.assertEqual(tpsl.COST, cost.FEE_ROUND_TRIP * 100)
        self.assertEqual(sstore.DEFAULT["cost"], cost.FEE_ROUND_TRIP)
        self.assertEqual(fchecks.CFG["liq_min"], cost.LIQ_HARD_MIN)
        self.assertFalse(hasattr(build, "COST_HI"))                         # the 3 / 5 / 8 % is gone

    def test_calibration_on_the_median_of_the_last_30_orders(self):
        self.assertEqual(cost.calibrate([]), (None, 0))
        self.assertEqual(cost.calibrate([(0.5, "buy", None, None, None)] * 4), (None, 4))   # under 5: not yet
        fee, n = cost.calibrate([(0.4, "buy", 100_000_000, 5, 0)] * 3 + [(0.8, "sell", 5, 100_000_000, 0)] * 2)
        self.assertEqual(n, 5)
        self.assertAlmostEqual(fee, 0.004)
        # the network fee of the swap counts too: 0.001 SOL on a 0.1 SOL buy = 1 %
        fee, _n = cost.calibrate([(0.5, "buy", 100_000_000, 5, 1_000_000)] * 5)
        self.assertAlmostEqual(fee, 0.005 + 0.01)
        self.assertEqual(cost.calibrate([(-3.0, "buy", None, None, None)] * 5)[0], 0.0)   # never below 0
        # only the newest 30 count
        rows = [(1.0, "buy", None, None, None)] * 30 + [(9.0, "buy", None, None, None)] * 30
        self.assertAlmostEqual(cost.calibrate(rows)[0], 0.01)

    def test_calibration_from_trade_db_replaces_the_fee_part(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "trade.db")
        self.assertEqual(cost.calibration(p)["fee_side"], cost.FEE_DEMO)          # no trade.db: league/store.FEE
        con = executor.connect(p)
        for i in range(40):
            con.execute("INSERT INTO orders (ts, side, cost_pct, amount_in, amount_out, fee_lamports, status) VALUES "
                        "(?,?,?,?,?,?,?)", (i, "buy", 3.0 if i < 10 else 0.6, 100_000_000, 1, 0, "dry"))
        con.commit()
        con.close()
        cost.reset_cache()
        c = cost.calibration(p)
        self.assertTrue(c["calibrated"])
        self.assertEqual(c["n"], 30)
        self.assertAlmostEqual(c["fee_side"], 0.006)                               # the median of the newest 30
        self.assertAlmostEqual(cost.round_trip(15.0, 40_000, fee=c["fee_side"]),
                               0.012 + 2 * cost.impact(15.0, 40_000))
        self.assertAlmostEqual(cost.calib_delta(0.006), 0.012 - 0.02)
        self.assertAlmostEqual(cost.demo_adjust(0.006), 0.008)                     # demo results look 0.8 pp worse


# ---------- B / C. hard blocks only, modifiers, size by slippage ----------------------------------------------------

class BlocksAndSize(unittest.TestCase):
    def test_only_under_15k_liquidity_blocks(self):
        self.assertIsNone(cost.liq_block(15_000))
        self.assertIsNone(cost.liq_block(20_000))
        self.assertIn("ispod $15k", cost.liq_block(14_999))
        self.assertIsNotNone(cost.liq_block(None))
        from momentum import rules
        from rangedca import detect, market
        self.assertEqual(rules.RULES["liq_min"], 15_000)
        self.assertEqual(detect.CFG["min_liq"], 15_000)
        self.assertEqual(market.MIN_LIQ, 15_000)                                 # the watchlist admission, lowered
        self.assertEqual(market.KEEP_LIQ, 15_000)
        self.assertEqual(detect.CFG["min_vol_h1"], cost.VOL_FLOOR)

    def test_modifiers_never_block(self):
        m = edge.modifiers(runup_x=5.0)                                         # X unknown: the reduction applies
        self.assertEqual((m["p_mult"], m["size_mult"]), (0.7, 0.5))
        m = edge.modifiers(runup_x=5.0, x_score=1.2, buy_share_5m=0.65)        # X bursting and buys >= 60 %
        self.assertEqual((m["p_mult"], m["size_mult"]), (1.0, 1.0))
        m = edge.modifiers(runup_x=5.0, x_score=1.2, buy_share_5m=0.5)         # buys under 60 %: reduced
        self.assertEqual(m["p_mult"], 0.7)
        self.assertEqual(edge.modifiers(runup_x=3.9)["p_mult"], 1.0)
        self.assertEqual(edge.modifiers(wash=True)["p_mult"], 0.5)
        self.assertEqual(edge.modifiers(shill=True)["p_mult"], 0.5)
        self.assertEqual(edge.modifiers(wash=True, shill=True)["p_mult"], 0.5)  # once
        # an EV measured without a P: P x m on the signal exit
        e, c = 0.05, 0.02
        p = (e + c + edge.SL) / (edge.TP + edge.SL)
        self.assertAlmostEqual(edge.ev_p_mult(e, 0.5, c), edge.ev(p * 0.5, edge.TP, edge.SL, c))

    def test_no_fee_volume_rule_in_momentum(self):
        from momentum import rules
        f = {"price": 1.0, "bonded": True, "mcap": 300_000, "liq": 20_000, "ch_m5": 8.0, "buys_m5": 70, "sells_m5": 30,
             "vol_m5": 5_000, "vol_h1": 20_000, "fee_rate": 0.0}
        self.assertIsNone(rules.cheap_check(f))
        self.assertNotIn("fee_vol_min", rules.RULES)

    def test_size_by_2_percent_slippage(self):
        u = cost.max_size_usd(15_000)
        self.assertAlmostEqual(cost.impact(u, 15_000), 0.02)
        self.assertAlmostEqual(u, 0.02 / 0.98 * 7_500)
        self.assertEqual(cost.max_size_usd(None), 0.0)
        self.assertAlmostEqual(cost.size_sol(1.0, 15_000, 250.0), round(u / 250.0, 6))   # the slippage stake wins
        self.assertEqual(cost.size_sol(0.1, 15_000, 250.0), 0.1)                       # the cap wins
        self.assertEqual(cost.size_sol(0.1, 60_000, 250.0, vol_h1=5_000), 0.05)        # volume $5k: x 0.5
        self.assertEqual(cost.size_sol(0.1, 60_000, 250.0, vol_h1=2_000), 0.0)         # under $3k: nothing
        self.assertEqual(cost.size_sol(0.1, 60_000, 250.0, vol_h1=50_000, mult=0.5), 0.05)
        self.assertIsNotNone(cost.vol_block(2_999))
        self.assertIsNone(cost.vol_block(3_000))

    def test_the_15_percent_of_the_pool_formula_is_not_here(self):
        for mod in ("proposals/build.py", "rangedca/trade.py", "ui/kandidati.py", "fast/checks.py"):
            with open(os.path.join(ROOT, mod)) as f:
                self.assertNotIn("0.015 *", f.read(), mod)


# ---------- C. live never above the grok_autotrade limits ---------------------------------------------------------------

class LiveCaps(unittest.TestCase):
    CFG = {"mode": "dry", "size_sol": 0.1, "max_sol_per_trade": 0.5, "max_sol_per_day": 1.0, "max_open": 5,
           "min_sol_reserve": 0.05, "max_cost_pct": 6, "max_signal_age_s": 180, "poll_s": 5, "max_loss_day": 0.4,
           "day_tz": "Europe/Zagreb"}
    NOW = 1_800_000_000

    def setUp(self):
        self.con = executor.connect(os.path.join(tempfile.mkdtemp(), "trade.db"))
        self.addCleanup(self.con.close)

    def test_the_caps_are_grok_autotrades(self):
        from ui import grokauto
        self.assertEqual(executor.LIVE_CAPS, {k.replace("grok_", ""): v[0] for k, v in grokauto.LIMITS.items()})

    def test_automatic_live_buys_are_held_to_them_the_owners_own_and_dry_are_not(self):
        g = lambda size, live, **k: executor.gate_buy(self.con, self.CFG, size, self.NOW, live, balance=10.0, **k)  # noqa
        self.assertIsNone(g(0.3, False))                                       # dry: the settings' own 0.5
        self.assertIn("iznad limita 0.1", g(0.3, True))                        # automatic live: never above 0.1 a buy
        self.assertIsNone(g(0.3, True, manual=True))                           # the owner's own: his settings (0.5)
        self.assertIsNone(g(0.1, True))
        for i in range(3):
            self.con.execute("INSERT INTO positions (token, opened_ts, mode, status, sol_in, reason) VALUES "
                             "(?,?,?,?,?,?)", (f"T{i}", self.NOW - 60, "live", "open", 0.1, "copy KOL x"))
        self.con.commit()
        self.assertIn("dnevni limit automatskih kupnji", g(0.05, True))       # 0.3 a day of automatic buys
        self.assertIsNone(g(0.05, True, manual=True, add=True))              # the owner's own buy is not held by it
        self.con.execute("UPDATE positions SET opened_ts=? ", (self.NOW - 3 * 86400,))
        self.con.commit()
        self.assertIn("3 otvorenih", g(0.05, True))                             # 3 open at most (automatic)
        self.assertIsNone(g(0.05, False))                                      # dry: max_open 5


# ---------- D. EV and proof --------------------------------------------------------------------------------------------

class EvProof(unittest.TestCase):
    def test_live_needs_n_ev_and_the_interval(self):
        self.assertEqual(edge.live_proof([0.05] * 9)[0], False)                # n < 10
        self.assertEqual(edge.live_proof([0.05] * 10), (True, None, edge.ev_stats([0.05] * 10)))
        self.assertFalse(edge.live_proof([0.025] * 20)[0])                     # EV +2.5 % < +3 %
        ok, why, s = edge.live_proof([0.3, -0.2] * 6)                          # EV +5 %, interval reaches under 0
        self.assertFalse(ok)
        self.assertIn("donja granica", why)
        self.assertLess(s["lo90"], 0)
        self.assertGreater(edge.t90(9), edge.Z90)                              # Student t for a small n
        self.assertAlmostEqual(edge.t90(9), 1.833, places=2)

    def test_40_percent_winners_is_gone(self):
        import run_trade
        from league import copy
        self.assertNotIn("win_rate", run_trade.PROOF)
        self.assertEqual(run_trade.PROOF, copy.PROOF)
        self.assertEqual((run_trade.PROOF["closed"], run_trade.PROOF["ev_min"]), (10, 0.03))
        # 12 closed, PnL > 0, 42 % winners: the old rule's "proven"; under break-even for TP 15 / SL 10 -> not proof
        rets = [0.15] * 5 + [-0.10] * 7
        self.assertGreater(sum(rets), 0)
        self.assertFalse(copy.proof_of(rets)[0])
        from fast import sources
        self.assertFalse(sources.has_proof(rets)[0])

    def test_run_trade_proof_per_follow_from_its_returns(self):
        import run_trade
        from league import copy, store as lstore
        lg = lstore.connect(os.path.join(tempfile.mkdtemp(), "league.db"))
        copy.ensure(lg)
        fid = copy.follow(lg, "pravi-trade", "kol", "ansem", "", 25, 5, "tpsl", "15%", "")

        def closed(rs):
            for i, r in enumerate(rs):
                lg.execute("INSERT INTO trades (user, token, status, follow_id, pnl_usd, size_usd, opened_ts) VALUES "
                           "(?,?,?,?,?,?,?)", ("pravi-trade", f"T{len(rs)}{i}", "closed", fid, 25 * r, 25, 1))
            lg.commit()
        self.assertIn("od potrebnih 10", run_trade._no_proof(lg, fid))
        closed([0.15] * 5 + [-0.10] * 7)
        self.assertIn("treba barem +3", run_trade._no_proof(lg, fid))
        closed([0.12] * 20)
        self.assertIsNone(run_trade._no_proof(lg, fid))
        lg.close()

    def test_influencer_n_10_with_the_shrink(self):
        from proposals import calib, strategies
        self.assertEqual(strategies.INFLUENCER_MIN_N, 10)
        self.assertFalse(strategies.qualifies({"n": 9, "ev_pct": 5.0}))
        self.assertTrue(strategies.qualifies({"n": 10, "ev_pct": 5.0}))
        e = calib.estimate(10, 10, edge.TP, edge.SL, 0.02)                      # 10 of 10 is not 100 %
        self.assertLess(e["p"], 0.7)

    def test_proposals_rank_by_ev_per_minute_then_the_low_end_then_liq(self):
        from proposals import build
        rows = [{"token": "range", "ev_per_min": 10.0 / 360, "ev_lo_pct": 6.0, "liq0": 50_000},
                {"token": "mom", "ev_per_min": 3.0 / 45, "ev_lo_pct": 0.5, "liq0": 20_000},
                {"token": "mom2", "ev_per_min": 3.0 / 45, "ev_lo_pct": 1.5, "liq0": 20_000},
                {"token": "mom3", "ev_per_min": 3.0 / 45, "ev_lo_pct": 1.5, "liq0": 90_000}]
        self.assertEqual([r["token"] for r in sorted(rows, key=build.rank_key)], ["mom3", "mom2", "mom", "range"])


# ---------- E. the signal exit -------------------------------------------------------------------------------------------

class SignalExit(unittest.TestCase):
    def test_15_trailing_8_stop_10_45_min(self):
        from fast import outcomes, paper as fpaper
        from momentum import rules
        from proposals import strategies
        want = {"tp": [{"pct": 15.0, "share": 0.5}], "sl": {"pct": -10.0},
                "trail": {"activate_pct": 15.0, "trail_pct": 8.0}, "time": {"after_min": 45, "if_pnl_below_pct": 1000}}
        self.assertEqual(edge.signal_exit_levels(), want)
        now = 1_800_000_000
        cal = {"callers": [{"who": "a", "ts": now - 60}]}
        inf = strategies.influencer_ev(cal, 100_000, {"a": {"n": 12, "hits": 9, "ev_pct": 4.0}}, None, set(), now)
        grp = strategies.group_ev({"pre_shill": {"ts": now - 60, "mcap_usd": 100_000}}, {}, {}, {"n": 10, "hits": 6},
                                  100_000, now)
        ins = strategies.insider_ev({"wallets": ["w"], "ts": now - 60}, {"w"}, {"n": 5, "hits": 3}, 100_000, now)
        for ev in (inf, grp, ins):
            self.assertEqual(ev["levels"], want, ev["strategy"])
            self.assertEqual((ev["tp"], ev["sl"]), (0.15, 0.10))
        mom = strategies.momentum_ev({"ts": now - 60, "mcap_usd": 100_000}, 100_000, {"n": 1, "hits": 1}, now)
        self.assertEqual(mom["levels"], want)
        self.assertEqual((rules.RULES["tp1"], rules.RULES["trail"], rules.RULES["stop"], rules.RULES["time_s"]),
                         (0.15, 0.08, 0.10, 45 * 60))
        self.assertEqual((fpaper.EXIT_TP, fpaper.EXIT_SL, fpaper.EXIT_TRAIL, fpaper.EXIT_MIN), (15, 10, 8, 45))
        self.assertEqual((outcomes.TP_PCT, outcomes.SL_PCT, outcomes.TP_WIN_S), (15.0, 10.0, 45 * 60))

    def test_kandidati_signal_rows_get_the_same_exit(self):
        from ui import kandidati
        r = {"sources": {"caller": {"callers": [{"who": "a"}]}}}
        p = kandidati.exit_plan(r, None, {"sl_default": 60}, None)
        self.assertEqual(p["take_profits"], [{"at_pct": 15.0, "sell_share": 0.5}])
        self.assertEqual((p["stop"], p["trailing"]["trail_pct"], p["time_stop"]["after_min"]), ({"at_pct": -10.0}, 8.0, 45))

    def test_the_influencer_benchmark_is_15_before_10_within_45_min(self):
        from kol import tpsl
        early = {"_lv": ({15: 30}, {10: 40}, True), "r60": 0.0}
        late = {"_lv": ({15: 50}, {10: 55}, True), "r60": 0.02}
        self.assertEqual(tpsl.outcome(early, 15, 10, 45), ("tp", 15.0))
        self.assertEqual(tpsl.outcome(late, 15, 10, 45)[0], "time")              # both after minute 45
        self.assertEqual(tpsl.outcome(late, 15, 10)[0], "tp")                     # the old 60 min window would count it


# ---------- H. event seeds -----------------------------------------------------------------------------------------------

class EventSeeds(unittest.TestCase):
    def setUp(self):
        from event_calendar import sources
        with open(sources.MANUAL_FILE) as f:
            self.items = {it["title"]: it for it in json.load(f)}

    def test_owner_seeds_carry_source_status_and_a_verified_date(self):
        for t in ("GTA 6 release (rolling, New Zealand first)", "PUMP token unlock (date unconfirmed)",
                  "US PPI release (October data)", "FOMC rate decision", "Solana Breakpoint 2026 (London, Olympia)"):
            it = self.items[t]
            self.assertTrue(it.get("sources"), t)
            self.assertIn(it.get("status"), ("confirmed", "unconfirmed"), t)
            self.assertEqual(it.get("verified"), "2026-11-11", t)

    def test_times_are_the_earliest_global_start(self):
        from event_calendar import sources
        utc = dt.timezone.utc
        nzdt, cet = dt.timezone(dt.timedelta(hours=13)), dt.timezone(dt.timedelta(hours=1))
        g = self.items["GTA 6 release (rolling, New Zealand first)"]
        ts = sources._iso_ts(g["event_ts"])
        self.assertEqual(ts, int(dt.datetime(2026, 11, 19, 0, 0, tzinfo=nzdt).timestamp()))   # 19.11. 00:00 NZDT
        self.assertEqual(dt.datetime.fromtimestamp(ts, cet).strftime("%d.%m. %H:%M"), "18.11. 12:00")
        self.assertEqual(g["date"], "2026-11-18")
        ppi = sources._iso_ts(self.items["US PPI release (October data)"]["event_ts"])
        self.assertEqual(dt.datetime.fromtimestamp(ppi, cet).strftime("%d.%m. %H:%M"), "13.11. 14:30")
        fomc = sources._iso_ts(self.items["FOMC rate decision"]["event_ts"])
        self.assertEqual(dt.datetime.fromtimestamp(fomc, cet).strftime("%d.%m. %H:%M"), "09.12. 20:00")
        self.assertEqual(dt.datetime.fromtimestamp(fomc, utc).hour, 19)

    def test_pump_unlock_is_never_seeded_as_certain(self):
        from event_calendar import sources
        p = self.items["PUMP token unlock (date unconfirmed)"]
        self.assertEqual(p["status"], "unconfirmed")
        self.assertIsNone(p["date"])
        self.assertEqual(len(p["candidates"]), 2)
        d = tempfile.mkdtemp()
        f = os.path.join(d, "m.json")
        with open(f, "w") as fh:   # even with a date, an unconfirmed seed is skipped
            json.dump([dict(p, date="2026-11-14")], fh)
        self.assertEqual(sources.manual_events(dt.date(2026, 11, 11), 14, f), [])
        titles = [e["title"] for e in sources.manual_events(dt.date(2026, 11, 11), 14)]
        self.assertNotIn(p["title"], titles)

    def test_breakpoint_ppi_fomc_are_regime_labels_not_event_tokens(self):
        from event_calendar import enrich, sources
        evs = {e["title"]: e for e in sources.manual_events(dt.date(2026, 11, 11), 40)}
        bp = evs["Solana Breakpoint 2026 (London, Olympia)"]
        self.assertEqual((bp["kind"], bp["signals"]["regime"], bp["date"], bp["signals"]["end_date"]),
                         ("regime", "conference", "2026-11-15", "2026-11-17"))
        for t in ("Solana Breakpoint 2026 (London, Olympia)", "US PPI release (October data)", "FOMC rate decision"):
            self.assertEqual(enrich.token_likelihood(evs[t]), 0.0, t)
        self.assertGreater(enrich.token_likelihood(evs["GTA 6 release (rolling, New Zealand first)"]), 0.5)
        with open(os.path.join(ROOT, "run_dex.py")) as f:
            self.assertIn('e.get("kind") != "regime"', f.read())


if __name__ == "__main__":
    unittest.main()
