"""11.11. (Jure, flag proposals G21): "Prijedlozi" from every strategy (proposals/), offline, no network.

Covers: several sources merged into one token row (sources, independent count: callers <= 30 s apart count once,
a known crew within 10 min once), the ONE cost model (trade/cost.round_trip, blocked under $15k; 11.11. owner's rule A),
the EV > 0 filter and the ranking (11.11. rule D: EV per expected minute, then the low end of the EV's interval, then
liquidity), the hard blocks (rug high, liquidity under $15k) and the modifiers that are no longer blocks (wash, 4x+
run-up, shill-driven: P x 0.5 / x 0.7, size x 0.5; rule B), the shrinkage (a strategy with no record is never shown), Grok's p_tp calibration (the owner's 20 % ->
56 % fixture, identity with few samples) and a Grok proposal through it, expiry (time, drop-out, a failed market
read), the after-outcome recording (1 h / 4 h, TP before SL, from our own price points), the Autopilot card right
after Brza kupnja and owner-only (nav link only while the flag is on), the fragment, Odbij with a reason, Kupi ->
Brza kupnja -> the position's own TP/SL + the exit plan + kupljeno, paper entries only on the demo account, live
refused, the MCP schema and dispatch (get_proposals, submit_signal_opinion with and without a proposal), the guarded
event / catalyst sources, the daily report with the missed risers, start.sh / cpuguard registration.
11.11. (after HAOBIBI): the paper entry waits for the entry zone (no entry at $88k under a $104-112k zone and an $88.6k
stop, an entry at $108k; proposals older than 10 min too; the cap per pass), the stop rule (under the stop at creation:
waits; above it, then under: isteklo), a vanished source outside the zone keeps waiting, one position per token next
to range_dca (open round, its cooldown, the pause; a proposal's position blocks a range round), the waiting state on
the card / get_proposals, report.zone_misses and its log block once, live still refused.

    python3 -m unittest tests.test_prijedlozi_offline
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from league import copy as lcopy, exitplan  # noqa: E402
from proposals import build, calib, job, outcomes, paper, report, store, strategies, view  # noqa: E402
from tests.test_kandidati_offline import NOW, FakeSources, live, mint  # noqa: E402
from trade import cost as tcost, edge, executor, settings  # noqa: E402
from ui import kandidati  # noqa: E402
from ui import assistnotes, mcpapi  # noqa: E402

A, B, C, D, E, F = (mint(i) for i in range(11, 17))


class PSources(FakeSources):
    """kandidati's in-memory reads plus the proposals pass's own."""

    def __init__(self):
        super().__init__()
        self.mom, self.ps = [], {}
        self.rc, self.evr, self.cat, self.gp, self.bn, self.zones = [], [], [], {}, {}, {}
        self.mrec, self.rrec = {"n": 0, "hits": 0}, {"n": 0, "wins": 0}
        self.psrec, self.irec, self.crec_cat = {"n": 0, "hits": 0}, {"n": 0, "hits": 0}, None
        self.conf, self.model, self.trades = set(), None, {}
        self.cp = {"max_sol_per_trade": 0.5, "dca_token_cap": 0.3, "held": {}}
        self.path = None

    def momentum(self, now):
        return self.mom

    def pre_shill(self, now):
        return self.ps

    def range_candidates(self, now):
        return self.rc

    def range_record(self, now):
        return self.rrec

    def momentum_record(self, now):
        return self.mrec

    def preshill_record(self, now):
        return self.psrec

    def insider_record(self, now):
        return self.irec

    def confirmed_insiders(self):
        return self.conf

    def event_rows(self, now):
        return self.evr

    def event_record(self, now):
        return None

    def catalyst_rows(self, now):
        return self.cat

    def catalyst_record(self, now):
        return self.crec_cat

    def range_zones(self, tokens):
        return {t: z for t, z in self.zones.items() if t in tokens}

    def grok_proposals(self, now, window_s=86400):
        return self.gp

    def calib_model(self, now):
        return self.model

    def bench(self, handles):
        return self.bn

    def live_trades(self, token, now):
        return self.trades.get(token, [])

    def caps(self):
        return self.cp

    def range_tier(self, token):
        return (getattr(self, "tier", None) or {}).get(token)


def msig(tok, mcap=300_000, ts=NOW - 120):
    return {"token": tok, "symbol": "MOM", "ts": ts, "mcap_usd": mcap, "change_5m_pct": 9.0, "volume_x": 3.5,
            "buy_share_5m": 0.7, "unique_buyers_5m": 40, "signal_id": 7}


GOOD_BENCH = {"n": 30, "hits": 28, "sl_first": 1, "ev_pct": 6.0}


def by(rows):
    return {r["token"]: r for r in rows}


class Merge(unittest.TestCase):
    def setUp(self):
        self.S = PSources()
        self.S.mrec = {"n": 100, "hits": 70}

    def build(self):
        return build.build(NOW, self.S)

    def test_sources_merged_into_one_row_and_coordinated_callers_count_once(self):
        S = self.S
        S.mom = [msig(A)]
        S.c = [(A, [("a1", "x", NOW - 600), ("a2", "x", NOW - 590), ("solo", "x", NOW - 300)], NOW - 600, NOW - 300,
                "AAA", live())]
        S.bn = {h: dict(GOOD_BENCH) for h in ("a1", "a2", "solo")}
        S.firsts = {A: (NOW - 600, 290_000)}
        rows, near, meta = self.build()
        got = by(rows)
        self.assertEqual(list(got), [A], near)                                     # ONE row for the token
        r = got[A]
        self.assertEqual(sorted(r["sources"]), ["influencer", "momentum"])
        # a1 and a2 called 10 s apart: coordinated, one source; solo another; momentum a third
        self.assertEqual(r["n_independent"], 3)
        self.assertEqual(r["strategy"], max(r["sources"], key=lambda k: r["strategies"][k]["ev_per_min"]))
        # 11.11. (rule A): the ONE cost model, 2 x fee + 2 x impact of the stake in the $40k pool
        self.assertEqual(r["cost_pct"], round(tcost.round_trip(r["size_sol"] * kandidati.SOL_USD, 40_000) * 100, 2))
        self.assertGreater(r["ev_pct"], 0)
        self.assertLessEqual(r["size_sol"], 0.15)
        self.assertIn("Potvrđuje i", r["why"])
        self.assertEqual(r["strategies"]["influencer"]["n"], 90)                   # pooled benchmark of three callers
        self.assertTrue(r["exit_plan"]["take_profits"])
        self.assertIn(A, meta["prices"])

    def test_caller_signals_crew_and_30_seconds(self):
        self.assertEqual(len(build.caller_signals([(0, "x"), (25, "y"), (200, "z")])), 2)
        self.assertEqual(len(build.caller_signals([(0, "x"), (31, "y")])), 2)
        self.assertEqual(len(build.caller_signals([(0, "x"), (20, "y"), (40, "z")])), 1)    # a chain 20 s apart
        # a known crew within 10 min is one signal even 5 min apart (kol/groupdisc.dedupe, as ui/kandidati)
        self.assertEqual(len(build.caller_signals([(0, "c1"), (300, "c2")], {"c1": "g", "c2": "g"})), 1)
        self.assertEqual(len(build.caller_signals([(0, "c1"), (300, "c2")])), 2)

    def test_cost_model_and_blocked_under_15k(self):
        # 11.11. (owner's rule A): no more 3 / 5 / 8 % by liquidity; the ONE model, blocked only under $15k
        for liq in (60_000, 50_000, 30_000, 22_000, 15_000):
            self.assertAlmostEqual(build.cost_for(liq, 37.5), 2 * tcost.FEE_DEMO + 2 * 37.5 / (liq / 2 + 37.5))
        self.assertIsNone(build.cost_for(14_999))
        self.assertIsNone(build.cost_for(None))
        S = self.S
        for tok, liq in ((A, 60_000), (B, 30_000), (C, 22_000), (D, 15_000), (E, 14_000)):
            S.mom.append(msig(tok, 600_000))
            S.mk[tok] = live(mcap=600_000, liq=liq)
        S.mrec = {"n": 400, "hits": 300}
        rows, near, _m = self.build()
        got = by(rows)
        self.assertEqual(set(got), {A, B, C, D})                                   # $15k and $22k are no longer blocked
        for t, liq in ((A, 60_000), (B, 30_000), (C, 22_000), (D, 15_000)):
            self.assertEqual(got[t]["cost_pct"], round(tcost.round_trip(got[t]["size_sol"] * kandidati.SOL_USD, liq)
                                                       * 100, 2))
        self.assertGreater(got[A]["ev_pct"], got[B]["ev_pct"])                     # the same p, a cheaper pool
        self.assertGreater(got[B]["ev_pct"], got[C]["ev_pct"])
        self.assertIn("tanak pool", " ".join(got[D]["risks"]))
        nr = by(near)
        self.assertIn("liq", [b["key"] for b in nr[E]["blocks"]])
        self.assertIn("ispod $15k", nr[E]["why"])

    def test_ev_filter_ranking_and_no_record_is_never_shown(self):
        S = self.S
        S.mom = [msig(A), msig(B)]
        S.mk = {A: live(liq=60_000), B: live(liq=30_000)}
        S.mrec = {"n": 200, "hits": 150}
        S.rc = [{"token": C, "symbol": "RNG", "entry_ready": True, "range_score": 0.8, "computed_ts": NOW - 60,
                 "now": {"volume_1h_usd": 20_000, "buy_share_5m": 0.6, "market_cap_usd": 100_000},
                 "zones": {"market_cap_usd": {"range_low_low": 90_000, "range_low_top": 105_000,
                                              "range_high_low": 150_000, "range_high_top": 170_000}}}]
        S.mk[C] = live(mcap=100_000, liq=40_000)
        S.rrec = {"n": 0, "wins": 0}                                                # no closed paper round yet
        rows, near, _m = self.build()
        self.assertEqual([r["token"] for r in rows], [A, B])                       # EV first (A's pool is cheaper)
        nr = by(near)
        self.assertIn(C, nr)                                                       # unmeasured: EV exactly 0
        self.assertAlmostEqual(nr[C]["strategy_detail"]["range"]["ev_pct"], 0.0, places=6)
        # with a record the range proposes it, its exit from the zones
        S.rrec = {"n": 40, "wins": 34}
        rows, _n, _m = self.build()
        r = by(rows)[C]
        self.assertEqual(r["strategy"], "range")
        self.assertEqual(r["exits_mcap"]["sl"], round(90_000 * 0.85))
        self.assertEqual(r["exits_mcap"]["tp"], [150_000, 170_000])
        self.assertEqual(r["entry_zone"], {"mcap_low": 90_000, "mcap_high": 105_000})
        self.assertEqual(r["buy"]["tp"], "$150k")
        self.assertIn("lot 2", r["dca"])
        self.assertIsNone(r["range_tier"])
        # the range's tier (rangedca.tier, the tier work): its line, and its stake, always <= 0.15 SOL and the caps
        S.tier = {C: {"tier": "T2", "size_sol": 0.25, "reason": "4 runde +",
                      "text": "Tier T2 · ulog 0.25 · razlog: 4 runde +, higher lows 95k→103k"}}
        r = by(build.build(NOW, S)[0])[C]
        self.assertEqual((r["size_sol"], r["buy"]["sol"]), (0.15, 0.15))
        self.assertIn("higher lows", r["range_tier"]["text"])
        S.tier = {C: {"tier": "T1", "size_sol": 0.05, "reason": "1 runda +", "text": "Tier T1 · ulog 0.05"}}
        self.assertEqual(by(build.build(NOW, S)[0])[C]["size_sol"], 0.05)
        S.cp = {"max_sol_per_trade": 0.5, "dca_token_cap": 0.3, "held": {C: 0.28}}
        S.tier = {C: {"tier": "T2", "size_sol": 0.25, "text": "Tier T2"}}
        self.assertEqual(by(build.build(NOW, S)[0])[C]["size_sol"], 0.02)       # the owner's per-token cap wins
        S.tier, S.cp = {}, {"max_sol_per_trade": 0.5, "dca_token_cap": 0.3, "held": {}}
        # 11.11. (rule D): EV per expected minute first, then the EV's low end, then liquidity
        x = [{"token": "b", "ev_per_min": 0.05, "ev_lo_pct": 1.0, "liq0": 30_000},
             {"token": "a", "ev_per_min": 0.05, "ev_lo_pct": 2.0, "liq0": 30_000},
             {"token": "d", "ev_per_min": 0.05, "ev_lo_pct": 2.0, "liq0": 90_000},
             {"token": "c", "ev_per_min": 0.10, "ev_lo_pct": -3.0, "liq0": 20_000}]
        self.assertEqual([r["token"] for r in sorted(x, key=build.rank_key)], ["c", "d", "a", "b"])
        # a 6 h range with the bigger EV ranks under a 45 min trade with the better EV per minute
        rng = {"token": "r", "ev_pct": 9.0, "duration_min": 360.0, "ev_per_min": 9.0 / 360, "ev_lo_pct": 5.0}
        mom = {"token": "m", "ev_pct": 3.0, "duration_min": 45.0, "ev_per_min": 3.0 / 45, "ev_lo_pct": 1.0}
        self.assertEqual([r["token"] for r in sorted([rng, mom], key=build.rank_key)], ["m", "r"])

    def test_tiny_n_cannot_make_a_big_ev(self):
        p0 = calib.break_even(0.15, 0.10, 0.03)
        e = calib.estimate(0, 0, 0.15, 0.10, 0.03)
        self.assertAlmostEqual(e["p"], p0, places=3)
        self.assertAlmostEqual(calib.ev(e["p"], 0.15, 0.10, 0.03), 0.0, places=3)
        small = calib.estimate(5, 5, 0.15, 0.10, 0.03)
        self.assertLess(small["p"], 0.7)                                          # 5 of 5 is not 100 %
        self.assertLess(calib.ev(small["p"], 0.15, 0.10, 0.03), 0.03)
        lo, hi = calib.wilson(5, 5)
        self.assertLess(lo, 0.7)
        self.assertEqual(small["ci90"], [round(lo, 3), round(hi, 3)])
        big = calib.estimate(500, 500, 0.15, 0.10, 0.03)
        self.assertGreater(big["p"], 0.95)

    def test_hard_blocks_only_the_rest_are_modifiers(self):
        # 11.11. (owner's rule B): rug high and liquidity under $15k block; wash, a 4x+ run-up, shill-driven and a
        # $20k pool only change P and the size
        S = self.S
        S.mrec = {"n": 400, "hits": 300}
        G = mint(17)
        for t in (A, B, C, D, E, F, G):
            S.mom.append(msig(t))
        S.col = {A: {"text": "cijena 80 % ispod vrha"}}                              # rug high: a collapse
        S.rug = {B: {"verdict": "VISOK RIZIK", "score": 40, "data": {"flags": [], "hard_fails": []}}}   # rating, no Grok
        S.trades = {C: [{"side": "buy" if i % 2 == 0 else "sell", "wallet": f"W{i % 4}", "amount": 1.0,
                         "ts": NOW - 3000 + i * 10} for i in range(150)]}             # 4 wallets churn it: wash
        S.firsts = {D: (NOW - 3000, 50_000)}                                         # 6x from the first call
        S.mk = {t: live() for t in (A, B, C, D, F)}
        S.mk[E] = live(liq=20_000)                                                   # $20k: no longer blocked
        S.mk[G] = live(liq=14_000)                                                   # under $15k: blocked
        S.c = [(F, [("shill1", "x", NOW - 300), ("shill2", "x", NOW - 200)], NOW - 300, NOW - 200, "F", live())]
        S.paid = {"shill1", "shill2"}                                                # only paid shillers call it
        rows, near, _m = self.build()
        got, nr = by(rows), by(near)
        keys = {n["token"]: [b["key"] for b in n["blocks"]] for n in near}
        self.assertIn("rug_hard", keys[A])
        self.assertIn("rug_risk", keys[B])
        self.assertIn("liq", keys[G])
        for t in (C, D, E, F):                                                       # never a block any more
            self.assertEqual(keys.get(t, []), [], t)
        # run-up 6x: P x 0.7 and half the size, still shown (no X burst known: the reduction applies)
        self.assertEqual(got[D]["modifiers"]["p_mult"], 0.7)
        self.assertEqual(got[D]["modifiers"]["size_mult"], 0.5)
        self.assertEqual(got[D]["size_sol"], 0.075)
        self.assertLess(got[D]["p_tp"], got[E]["p_tp"])
        self.assertIn("runup", [t["key"] for t in got[D]["modifiers"]["tags"]])
        self.assertIn(E, got)                                                        # a $20k pool is shown
        # wash and shill-driven: P x 0.5, which turns this record's EV negative (a near miss, not a block)
        for t in (C, F):
            self.assertEqual(nr[t]["blocks"], [])
            self.assertEqual(nr[t]["strategy_detail"]["momentum"]["p_mult"], 0.5)
            self.assertIn("EV", nr[t]["why"])
        # without them the same signal is shown at the full P
        S.col, S.rug, S.trades, S.firsts, S.c, S.paid = {}, {}, {}, {}, [], set()
        S.mk[G] = live()
        rows, _n, _m = self.build()
        self.assertEqual(sorted(r["token"] for r in rows), sorted([A, B, C, D, E, F, G]))
        self.assertTrue(all(r["modifiers"]["p_mult"] == 1.0 for r in rows))

    def test_influencer_rules(self):
        S = self.S
        S.c = [(A, [("good", "x", NOW - 300), ("thin", "x", NOW - 290)], NOW - 300, NOW - 290, "A", live(mcap=140_000)),
               (B, [("good", "x", NOW - 300)], NOW - 300, NOW - 300, "B", live(mcap=200_000))]
        S.bn = {"good": dict(GOOD_BENCH), "thin": {"n": 9, "hits": 9, "sl_first": 0, "ev_pct": 9.0}}
        S.firsts = {A: (NOW - 300, 100_000), B: (NOW - 300, 100_000)}
        rows, near, _m = self.build()
        r = by(rows)[A]
        self.assertEqual(r["sources"], ["influencer"])
        self.assertEqual([c["who"] for c in r["strategies"]["influencer"]["detail"]["callers"]], ["good"])   # n >= 10
        # 11.11. (rule E): the signal exit, half at +15 %, trailing 8 %, stop -10 %, 45 min
        self.assertEqual((r["tp_pct"], r["sl_pct"]), (15.0, 10.0))
        self.assertEqual(r["exits_mcap"]["time_min"], 45)
        self.assertEqual(r["exits_mcap"]["trailing_pct"], 8)
        self.assertEqual(r["exits_mcap"]["tp_share"], [0.5])
        self.assertIn("+15 % prije -10 % u 45 min", r["strategies"]["influencer"]["p_from"])
        S.bn["thin"]["n"] = S.bn["thin"]["hits"] = 10                               # 20 -> 10 (with the shrink)
        rows, _n, _m = self.build()
        self.assertEqual(sorted(c["who"] for c in by(rows)[A]["strategies"]["influencer"]["detail"]["callers"]),
                         ["good", "thin"])
        nb = by(near)[B]                                                             # +100 % since the first call
        self.assertIn("granica +50 %", nb["strategy_detail"]["influencer"]["why_not"])
        # a shill-network member never counts, even with a good record
        S.ps = {"members": {"good": "net1", "thin": "net1"}, "signals": [], "held": {}}
        rows, near, _m = self.build()
        self.assertNotIn(A, by(rows))

    def test_group_insider_event_catalyst_sources(self):
        S = self.S
        S.member = {"c1": "crew1", "c2": "crew1"}
        S.glist = {"crew1": ("caller", "quality", ["c1", "c2"], {"n_measured": 9})}
        S.gsig = [(NOW - 600, "hidden_group", "w1", A, "x1,x2,x3", 280_000)]
        S.glist["w1"] = ("wallet", "quality", ["x1", "x2", "x3"], {"n_closed": 10})
        S.recs["hidden_group"] = {"n": 200, "hit1h": 0.5, "hit4h": 0.75, "sl_first": 0.1, "ev": 0.08}
        S.ins = [{"token": B, "ts": NOW - 300, "wallets": ["I1", "I2"], "mcap_usd": 250_000}]
        S.conf = {"I2"}
        S.irec = {"n": 100, "hits": 80}
        S.evr = [{"token": C, "symbol": "EVT", "topic": "Konferencija", "topic_id": 3, "event_ts": NOW + 3 * 86400,
                  "role": "main", "mcap": 300_000, "liq": 40_000}]
        S.mk = {A: live(), B: live(), C: live(), D: live(mcap=100_000)}
        S.cat = [{"token": D, "symbol": "CAT", "ts": NOW - 600, "kinds": ["dex_profile", "boost"], "pos_pct": 20,
                  "mcap": 100_000, "liq": 40_000, "why": ""}]
        S.zones = {D: {"range_low_low": 90_000, "range_low_top": 100_000, "range_high_low": 160_000,
                       "range_high_top": 180_000}}
        S.crec_cat = {"n": 60, "hits": 50}
        rows, near, _m = self.build()
        got = by(rows)
        self.assertEqual(got[A]["sources"], ["group"])
        self.assertIn("skupina novčanika", got[A]["why"])
        self.assertEqual(got[B]["sources"], ["insider"])
        self.assertEqual(got[D]["sources"], ["catalyst"])
        self.assertEqual(got[D]["exits_mcap"]["sl"], round(90_000 * 0.85))         # range exit from range.db
        self.assertIn("DexScreener profil", got[D]["why"])
        nr = by(near)
        self.assertIn(C, nr)                                                       # an unmeasured event: EV 0
        self.assertIn("event", nr[C]["strategies"])
        # a group grade under n=8 is no source
        S.glist["w1"] = ("wallet", "quality", ["x1"], {"n_closed": 5})
        S.gsig = [(NOW - 600, "hidden_group", "w1", A, "x1,x2,x3", 280_000)]
        rows, near, _m = self.build()
        self.assertNotIn(A, by(rows))

    def test_guarded_imports_of_the_parallel_work(self):
        S = build.Sources()
        with mock.patch.dict(sys.modules, {"topics": None, "catalyst": None}):
            self.assertEqual(S.event_rows(NOW), [])
            self.assertEqual(S.catalyst_rows(NOW), [])
            self.assertIsNone(S.catalyst_record(NOW))
        fake = type(sys)("catalyst")
        fake.view = type(sys)("catalyst.view")
        fake.view.proposal_rows = lambda now, hours=2: (_ for _ in ()).throw(RuntimeError("boom"))
        with mock.patch.dict(sys.modules, {"catalyst": fake, "catalyst.view": fake.view}):
            self.assertEqual(S.catalyst_rows(NOW), [])
        fake.view.proposal_rows = lambda now, hours=2: [{"token": A, "kinds": ["boost"]}, {"bad": 1}]
        fake.view.record = lambda now: {"n": 50, "hit_rate": 0.4}
        with mock.patch.dict(sys.modules, {"catalyst": fake, "catalyst.view": fake.view}):
            self.assertEqual([r["token"] for r in S.catalyst_rows(NOW)], [A])
            self.assertEqual(S.catalyst_record(NOW)["hits"], 20)
        # rangedca.tier (the tier work): missing or failing -> None; there -> its reason line
        import rangedca
        with mock.patch.dict(sys.modules, {"rangedca.tier": None}):
            self.assertIsNone(S.range_tier(A))
        tier = type(sys)("rangedca.tier")
        tier.view = lambda tok: {"tier": "T2", "size_sol": 0.25, "reason": "4 runde +"}
        tier.reason_text = lambda v: f"Tier {v['tier']} · ulog {v['size_sol']} · razlog: {v['reason']}"
        with mock.patch.dict(sys.modules, {"rangedca.tier": tier}), mock.patch.object(rangedca, "tier", tier, create=True):
            self.assertEqual(S.range_tier(A)["text"], "Tier T2 · ulog 0.25 · razlog: 4 runde +")
            tier.view = lambda tok: (_ for _ in ()).throw(RuntimeError("boom"))
            self.assertIsNone(S.range_tier(A))


# ---------- Grok calibration -------------------------------------------------------------------------------------------

class Calibration(unittest.TestCase):
    def test_owner_fixture_20_to_56_percent(self):
        pairs = [(0.2, 1)] * 224 + [(0.2, 0)] * 176                                  # Grok said 20 %, 56 % happened
        m = calib.fit(pairs)
        self.assertAlmostEqual(calib.apply(m, 0.2), 0.56, delta=0.03)
        self.assertGreater(calib.apply(m, 0.2), 0.5)

    def test_few_samples_stay_near_identity(self):
        m = calib.fit([(0.2, 1), (0.2, 1), (0.2, 0)])
        self.assertLess(abs(calib.apply(m, 0.2) - 0.2), 0.07)
        self.assertEqual(calib.apply(None, 0.37), 0.37)
        self.assertEqual(calib.apply(calib.fit([]), 0.37), 0.37)

    def test_monotone_and_bounded(self):
        pairs = [(0.1, 1)] * 80 + [(0.1, 0)] * 20 + [(0.5, 1)] * 30 + [(0.5, 0)] * 70 + [(0.9, 1)] * 60 + [(0.9, 0)] * 40
        m = calib.fit(pairs)
        vals = [b["calibrated"] for b in m["buckets"]]
        self.assertEqual(vals, sorted(vals))
        self.assertTrue(all(0.01 <= calib.apply(m, p) <= 0.99 for p in (0, 0.05, 0.5, 1)))

    def test_pairs_from_momentum_and_events(self):
        tmp = tempfile.mkdtemp()
        mp, ep = os.path.join(tmp, "m.db"), os.path.join(tmp, "e.db")
        con = sqlite3.connect(mp)
        con.execute("CREATE TABLE calib (ts INTEGER, p_tp REAL, hit INTEGER, status TEXT)")
        con.executemany("INSERT INTO calib VALUES (?,?,?,?)", [(NOW, 0.2, 1, "done"), (NOW, 0.3, None, "open")])
        con.commit()
        con.close()
        con = sqlite3.connect(ep)
        con.execute("CREATE TABLE events (id INTEGER)")   # events/store.ro opens only a real events.db
        con.execute("CREATE TABLE grok_predictions (ts INTEGER, p_tp REAL, tp_first INTEGER)")
        con.executemany("INSERT INTO grok_predictions VALUES (?,?,?)", [(NOW, 0.25, 0), (NOW, 0.4, None)])
        con.commit()
        con.close()
        self.assertEqual(sorted(calib.pairs(NOW, momentum_path=mp, events_path=ep)), [(0.2, 1), (0.25, 0)])

    def test_grok_proposal_uses_the_calibrated_p(self):
        S = PSources()
        S.gp = {A: {"id": 5, "ts": NOW - 300, "confidence": 0.6, "interpretation": "Jak X. Još nešto.",
                    "proposal": {"p_tp": 0.2, "strategy": "grok", "exit_zone": {"tp_mcap": 450_000, "sl_mcap": 255_000}}}}
        S.mk = {A: live(liq=60_000)}
        rows, near, _m = build.build(NOW, S)                                        # no calibration: Grok's 20 %
        self.assertEqual(rows, [])
        self.assertIn(A, by(near))
        S.model = calib.fit([(0.2, 1)] * 224 + [(0.2, 0)] * 176)
        rows, _n, _m = build.build(NOW, S)
        r = by(rows)[A]
        self.assertEqual(r["strategy"], "grok")
        self.assertEqual(r["grok"]["p_tp_raw"], 0.2)
        self.assertAlmostEqual(r["grok"]["p_tp_calibrated"], 0.56, delta=0.03)
        self.assertEqual(r["exits_mcap"]["tp"], [450_000])
        self.assertEqual(r["expires_ts"], NOW - 300 + 3600)                          # its own validity: default 1 h
        self.assertIn("Jak X", r["why"])


# ---------- proposals.db: sync, expiry, outcomes -------------------------------------------------------------------------

def prow(tok, ev=3.0, sources=("momentum",), exp=None, price=1.0, tp=15.0, sl=10.0, strat=None):
    st = {k: {"valid": True, "ev_pct": ev, "expires_ts": exp or NOW + 900} for k in sources}
    return {"token": tok, "symbol": "T" + tok[:3], "strategy": strat or sources[0], "sources": list(sources),
            "n_independent": len(sources), "ev_pct": ev, "p_tp": 0.7, "n": 100, "ci90": [0.6, 0.8], "tp_pct": tp,
            "sl_pct": sl, "cost_pct": 3.0, "size_sol": 0.15, "why": "Zato.", "risks": [], "entry_zone": None,
            "exits_mcap": {"tp": [115_000], "tp_share": [1.0], "sl": 90_000}, "strategies": st,
            "exit_plan": {"take_profits": [{"at_pct": tp, "sell_share": 1.0}], "stop": {"at_pct": -sl}},
            "buy": {"tp": f"{tp:g}%", "sl": f"-{sl:g}%", "sol": 0.15, "hold_s": None}, "market": {"market_cap_usd": 100_000},
            "expires_ts": exp or NOW + 900, "price0": price, "mcap0": 100_000, "liq0": 60_000}


class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "proposals.db")
        self.con = store.connect(self.path)

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_new_update_expire_by_time_dropout_and_cooldown(self):
        c = self.con
        out = job.sync(c, [prow(A), prow(B)], [], NOW)
        self.assertEqual(out["new"], 2)
        out = job.sync(c, [prow(A, ev=4.0), prow(B)], [], NOW + 60)
        self.assertEqual((out["new"], out["updated"]), (0, 2))
        self.assertEqual(store.active(c)[A]["ev_pct"], 4.0)
        # B's source is gone, but the market read failed this pass: only the time rule may expire it
        out = job.sync(c, [prow(A, ev=4.0)], [], NOW + 120, market_ok=False)
        self.assertEqual(out["expired"], 0)
        # ... nor when this pass had no market reading of it (DexScreener answered nothing for the token)
        out = job.sync(c, [prow(A, ev=4.0)], [{"token": B, "why": "nema tržišta", "blocks": [{"key": "market"}]}],
                       NOW + 150)
        self.assertEqual(out["expired"], 0)
        out = job.sync(c, [prow(A, ev=4.0)], [{"token": B, "why": "lažni volumen"}], NOW + 180)
        p = store.last_by_token(c, [B])[B]
        self.assertEqual((p["status"], p["status_why"]), ("isteklo", "više ne vrijedi: lažni volumen"))
        # A: momentum, 15 min
        out = job.sync(c, [prow(A, ev=4.0)], [], NOW + 901)
        self.assertEqual(store.last_by_token(c, [A])[A]["status"], "isteklo")
        self.assertEqual(store.last_by_token(c, [A])[A]["status_why"], "vrijeme je isteklo")
        # not proposed again right away for the same source; a new strategy may
        job.sync(c, [prow(A, exp=NOW + 5000)], [], NOW + 1000)
        self.assertNotIn(A, store.active(c))
        job.sync(c, [prow(A, sources=("momentum", "influencer"), exp=NOW + 5000)], [], NOW + 1001)
        self.assertIn(A, store.active(c))

    def test_range_valid_two_hours_from_the_proposal(self):
        r = prow(A, sources=("range",))
        r["strategies"]["range"] = {"valid": True, "ev_pct": 3.0, "expires_ts": None, "expires_after_s": 7200}
        job.sync(self.con, [r], [], NOW)
        job.sync(self.con, [r], [], NOW + 7000)
        self.assertIn(A, store.active(self.con))
        job.sync(self.con, [r], [], NOW + 7201)
        self.assertEqual(store.last_by_token(self.con, [A])[A]["status"], "isteklo")

    def test_reject_and_bought_once(self):
        job.sync(self.con, [prow(A), prow(B)], [], NOW)
        self.con.commit()
        ids = {p["token"]: p["id"] for p in store.active(self.con).values()}
        store.reject(ids[A], "kasno", "već je otišlo", "Jure", NOW + 10, path=self.path)
        p = store.one(self.con, ids[A])
        self.assertEqual((p["status"], p["reject_reason"], p["reject_note"]), ("odbijeno", "kasno", "već je otišlo"))
        with self.assertRaises(ValueError):
            store.reject(ids[A], "drugo", "", "Jure", path=self.path)
        self.assertIsNotNone(store.mark_bought(ids[B], 0.15, "Jure", path=self.path))
        self.assertIsNone(store.mark_bought(ids[B], 0.15, "Jure", path=self.path))

    def test_after_outcome_from_our_price_points(self):
        c = self.con
        job.sync(c, [prow(A, price=1.0, tp=15.0, sl=10.0), prow(B, price=1.0)], [], NOW)
        c.commit()
        ida = store.active(c)[A]["id"]
        store.reject(ida, "kasno", "", "Jure", NOW + 60, path=self.path)
        for dt_, px in ((300, 1.05), (900, 1.18), (1500, 1.1), (5400, 0.88), (12000, 0.95)):
            c.execute("INSERT INTO px VALUES (?,?,?,?)", (A, NOW + dt_, px, px * 100_000))
        for dt_, px in ((300, 0.95), (700, 0.89), (2000, 1.3)):
            c.execute("INSERT INTO px VALUES (?,?,?,?)", (B, NOW + dt_, px, px * 100_000))
        c.commit()
        from events import predictions
        with mock.patch.object(predictions, "_minute_rows", lambda *a, **k: []):
            self.assertEqual(outcomes.measure_due(c, NOW + 3000, econ=sqlite3.connect(":memory:")), 0)   # not due
            n = outcomes.measure_due(c, NOW + 3600 + 700, econ=sqlite3.connect(":memory:"), mom_path="/nema")
            self.assertEqual(n, 2)
            pa = store.one(c, ida)
            h1 = pa["after"]["1h"]
            self.assertEqual((h1["first"], h1["max_gain_pct"]), ("tp", 18.0))     # +15 % came before -10 %
            self.assertEqual(h1["ret_pct"], 12.0)                                  # +15 % - 3 % cost
            self.assertNotIn("4h", pa["after"])
            self.assertEqual(pa["status"], "odbijeno")                             # a missed opportunity
            self.assertEqual(store.one(c, store.last_by_token(c, [B])[B]["id"])["after"]["1h"]["first"], "sl")
            outcomes.measure_due(c, NOW + 4 * 3600 + 700, econ=sqlite3.connect(":memory:"), mom_path="/nema")
            pa = store.one(c, ida)
            self.assertEqual(pa["after"]["4h"]["max_dd_pct"], -12.0)
            self.assertEqual(pa["after_done"], 1)

    def test_seen_near_misses_per_day(self):
        job.record_seen(self.con, [prow(A)], [{"token": B, "symbol": "BB", "strategies": ["momentum"], "why": "lažni volumen",
                                                "blocks": [{"key": "wash"}], "strategy_detail": {"momentum": {"ev_pct": 2}},
                                                "mcap": 50_000}], NOW)
        rows = {(t, k): (p, w) for t, k, p, w in self.con.execute("SELECT token, strategy, proposed, why FROM seen")}
        self.assertEqual(rows[(A, "momentum")][0], 1)
        self.assertEqual(rows[(B, "momentum")], (0, "lažni volumen"))

    def test_dex_batch_is_capped(self):
        calls = []

        def fetch(toks):
            calls.append(list(toks))
            return {t: {"price": 2.0, "mcap": 200_000} for t in toks}
        toks = [mint(i) for i in range(40, 80)]
        self.assertEqual(job.dex_batch(self.con, toks, NOW, fetch), job.DEX_TOKENS)
        self.assertEqual(job.dex_batch(self.con, toks, NOW + 60, fetch), 0)        # every DEX_EVERY_S at most
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0]), job.DEX_TOKENS)


# ---------- the pass, the flag, start.sh -----------------------------------------------------------------------------------

class FlagAndPass(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self._saved = settings.DB
        settings.DB = os.path.join(d, "trade.db")
        self.tc = executor.connect(settings.DB)
        self.env = mock.patch.dict(os.environ, {"PROPOSALS_DB": os.path.join(d, "proposals.db")})
        self.env.start()
        view.clear()

    def tearDown(self):
        self.env.stop()
        settings.DB = self._saved
        settings._FLAG_CACHE.clear()
        self.tc.close()
        self.tmp.cleanup()
        view.clear()

    def test_flag_is_g21_off_by_default_and_never_live(self):
        self.assertEqual(settings.FLAGS["proposals"][0], "G21")
        self.assertEqual(settings.flag("proposals", con=self.tc), "off")
        self.assertIn("proposals", settings.LIVE_GATES)
        self.assertTrue(paper.live_refusal(self.tc))
        settings.set_flag(self.tc, "proposals", "shadow", "Jure")
        with self.assertRaises(ValueError):
            settings.set_flag(self.tc, "proposals", "live", "Jure")
        settings.put(self.tc, "backtest:proposals", {"pass": True})
        settings.set_flag(self.tc, "proposals", "paper", "Jure", now=NOW)
        with self.assertRaises(ValueError) as e:
            settings.set_flag(self.tc, "proposals", "live", "Jure", paper={"n": 50, "pnl": 9.0}, now=NOW + 30 * 86400)
        self.assertIn("nemaju live", str(e.exception))

    def test_off_reads_nothing_and_writes_nothing(self):
        S = PSources()
        S.range_candidates = mock.Mock(side_effect=AssertionError("read while off"))
        self.assertEqual(job.once(NOW, S), {"off": True})
        self.assertFalse(os.path.exists(os.environ["PROPOSALS_DB"]))
        self.assertEqual(view.card(lambda x: x, lambda *a, **k: "", True), "")
        d, err = mcpapi._tool("get_proposals", {})
        self.assertFalse(err)
        self.assertEqual(d["proposals"], [])

    def test_one_pass_writes_proposals_and_the_tool_reads_them(self):
        settings.set_flag(self.tc, "proposals", "shadow", "Jure")
        S = PSources()
        S.mrec = {"n": 300, "hits": 220}
        S.mom = [msig(A)]
        S.mk = {A: live(liq=60_000)}
        S.trades = {}
        S.rc = []
        out = job.once(NOW, S, pairs_fn=lambda now: [], dex_fetch=lambda toks: {})
        self.assertEqual(out["new"], 1)
        view.clear()
        d, err = mcpapi._tool("get_proposals", {"include_blocked": True})
        self.assertFalse(err, d)
        p = d["proposals"][0]
        self.assertEqual((p["token"], p["status"], p["strategy"]), (A, "novo", "momentum"))
        for k in ("p_tp", "strategies", "exit_plan", "exits_mcap", "size_sol", "risks", "why", "expires_ts", "grok"):
            self.assertIn(k, p)
        self.assertIn("ci90", p["p_tp"])
        self.assertIn("blocked", d)
        self.assertIn("buckets", d["grok_calibration"])
        d, err = mcpapi._tool("get_proposals", {"status": "nešto"})
        self.assertTrue(err)
        d, _e = mcpapi._tool("get_proposals", {"min_ev": 99})
        self.assertEqual(d["proposals"], [])

    def test_start_sh_and_cpuguard(self):
        from ops import cpuguard
        with open(os.path.join(ROOT, "start.sh"), encoding="utf-8") as f:
            sh = f.read()
        self.assertIn("low python3 run_proposals.py once", sh)
        self.assertIn("python3 -m ops.heavy --night run_proposals.py night", sh)
        name, rank, _why = cpuguard.classify(["python3", "run_proposals.py", "once"])
        self.assertEqual((name, rank), ("prijedlozi", cpuguard.JOBS))

    def test_night_benchmark_from_minute_rows(self):
        # 11.11. (rule E): the benchmark is the signal exit, +15 % before -10 % within 45 min
        rows = [{"handle": "a", "token": f"t{i}", "ts": NOW - i, "_lv": ({15: 3}, {10: 9} if i % 5 == 0 else {}, True)}
                for i in range(25)]
        rows += [{"handle": "late", "token": f"u{i}", "ts": NOW - i, "r60": 0.05, "_lv": ({15: 50}, {}, True)}
                 for i in range(12)]                                        # +15 % only after 45 min: no hit
        rows += [{"handle": "old", "token": f"v{i}", "ts": NOW - i, "_lv": ({10: 3}, {20: 30}, True)}
                 for i in range(12)]                                        # +10 % was the old target: no hit
        with mock.patch("kol.tpsl.rows", lambda *a, **k: rows), mock.patch("os.path.getsize", lambda p: 1), \
                mock.patch("os.path.exists", lambda p: True), mock.patch("sqlite3.connect"):
            b = job.bench_rows(NOW, "/x/minute.db")
        self.assertEqual((b["a"]["n"], b["a"]["hits"]), (25, 25))
        self.assertTrue(strategies.qualifies(b["a"]))
        self.assertEqual((b["late"]["hits"], b["late"]["sl_first"]), (0, 0))
        self.assertEqual(b["old"]["hits"], 0)
        self.assertEqual((job.BENCH_TP, job.BENCH_SL, job.BENCH_MIN), (edge.TP * 100, edge.SL * 100, edge.TIME_MIN))
        self.assertEqual(strategies.INFLUENCER_MIN_N, 10)


# ---------- the Autopilot card, Kupi, Odbij, paper -------------------------------------------------------------------------

from tests.test_apui_offline import SUMMARY, Base as ApBase, fake_aplog, fake_equity, history  # noqa: E402
from tests.test_pozicije_izlaz_offline import MINT, Base as BuyBase  # noqa: E402


def _seed(path, tok=A, now=None, **kw):
    con = store.connect(path)
    try:
        r = prow(tok, exp=(now or NOW) + 900, **kw)
        pid = store.insert(con, r, now or NOW)
        con.commit()
        return pid
    finally:
        con.close()


class Card(ApBase):
    def setUp(self):
        super().setUp()
        self.ppath = os.path.join(self.tmp.name, "proposals.db")
        self.penv = mock.patch.dict(os.environ, {"PROPOSALS_DB": self.ppath})
        self.penv.start()
        view.clear()
        settings._FLAG_CACHE.clear()

    def tearDown(self):
        self.penv.stop()
        view.clear()
        settings._FLAG_CACHE.clear()
        super().tearDown()

    def test_right_after_brza_kupnja_owner_only_and_nav(self):
        import time as _t
        from ui import pravitrade
        self.mods(fake_equity(history(), SUMMARY), fake_aplog())
        # 11.11. (Jure: "Što kupiti" = jedna lista, ui/apterm): the proposals are rows of "Što kupiti", loaded when the
        # card scrolls into view and every 30 s while on screen; Kupi only fills the order panel (data-pk)
        from ui import apterm
        _, body = pravitrade.page({}, "Jure")
        self.assertIn("data-x-src=/pravi-trade/l/kupiti data-x-every=30", body)
        self.assertNotIn("data-pk=", body)                                          # never in the first HTML
        self.assertNotIn("data-pk=", apterm.lazy("kupiti", "Jure"))                # flag off: no proposal rows
        settings.set_flag(self.con, "proposals", "shadow", "Jure")
        _seed(self.ppath, now=int(_t.time()))
        view.clear()
        body = apterm.lazy("kupiti", "Jure")
        self.assertIn("id=prijedlozi-trade", body)
        self.assertIn("prijedlozi: shadow", body)
        self.assertIn("data-pk=", body)
        self.assertIn("dexscreener.com/solana/" + A, body)
        self.assertIn("solscan.io/token/" + A, body)
        self.assertIn("action=/pravi-trade/prijedlog-odbij", body)
        body = apterm.lazy("kupiti", "Ivan")                                        # invited: never a proposal
        self.assertNotIn("data-pk=", body)
        self.assertNotIn("T" + A[:3], body)
        self.assertIsNone(pravitrade.proposals_fragment("Ivan"))
        frag = pravitrade.proposals_fragment("Jure")
        self.assertIn("T" + A[:3], frag)
        self.assertIn("Šansa TP prije SL", frag)

    def test_range_tier_line_on_the_card(self):
        from ui.html import esc
        r = prow(A, sources=("range",))
        r["range_tier"] = {"tier": "T2", "size_sol": 0.25, "text": "Tier T2 · ulog 0.25 · razlog: 4 runde +"}
        html = view._row_inner({"id": 1, "token": A, "sources": ["range"], "size_sol": 0.15, "row": r}, esc)
        self.assertIn("Tier raspona", html)
        self.assertIn("Tier T2 · ulog 0.25 · razlog: 4 runde +", html)
        r["range_tier"] = None
        self.assertNotIn("Tier raspona", view._row_inner({"id": 1, "token": A, "sources": ["range"], "row": r}, esc))

    def test_top_five_and_the_rest_behind_jos(self):
        import time as _t
        settings.set_flag(self.con, "proposals", "shadow", "Jure")
        now = int(_t.time())
        for i in range(7):
            _seed(self.ppath, tok=mint(60 + i), now=now, ev=1.0 + i)
        view.clear()
        from ui import pravitrade
        frag = pravitrade.proposals_fragment("Jure")
        head, _sep, rest = frag.partition("još 2")
        self.assertTrue(rest)
        self.assertEqual(head.count("data-pk="), 5)

    def test_odbij_stores_the_reason(self):
        import time as _t
        from ui import pravitrade
        settings.set_flag(self.con, "proposals", "shadow", "Jure")
        pid = _seed(self.ppath, now=int(_t.time()))
        loc = pravitrade.post("/pravi-trade/prijedlog-odbij", {"id": str(pid), "reason": "ne vjerujem izvoru",
                                                                "note": "isti dev kao prošli rug"}, "Jure")
        self.assertIn("ok=", loc)
        con = store.ro(self.ppath)
        p = store.one(con, pid)
        con.close()
        self.assertEqual((p["status"], p["reject_reason"], p["reject_note"]),
                         ("odbijeno", "ne vjerujem izvoru", "isti dev kao prošli rug"))
        loc = pravitrade.post("/pravi-trade/prijedlog-odbij", {"id": str(pid), "reason": "kasno"}, "Ivan")
        self.assertIn("err=", loc)


class Kupi(BuyBase):
    def setUp(self):
        super().setUp()
        self.ppath = os.path.join(self.tmp.name, "proposals.db")
        self.penv = mock.patch.dict(os.environ, {"PROPOSALS_DB": self.ppath})
        self.penv.start()
        view.clear()

    def tearDown(self):
        self.penv.stop()
        view.clear()
        super().tearDown()

    def test_kupi_goes_through_brza_kupnja_and_the_exits_become_the_positions_own(self):
        import time as _t
        r = prow(MINT, tp=20.0, sl=12.0)
        r["buy"] = {"tp": "$100k", "sl": "$70k", "sol": 0.1}   # the default max_sol_per_trade is 0.1
        r["exit_plan"] = {"take_profits": [{"at_mc_usd": 100_000, "sell_share": 0.5}], "trailing": {"activate_pct": 20,
                          "trail_pct": 8}, "stop": {"at_mc_usd": 70_000}, "reason": "prijedlog (momentum)"}
        con = store.connect(self.ppath)
        pid = store.insert(con, r, int(_t.time()))
        con.commit()
        con.close()
        loc = unquote_(self.post("/pravi-trade/buy", {"token": MINT, "sol": "0,1", "tp": "$100k", "sl": "$70k",
                                                      "exit": "tpsl", "prijedlog": str(pid)}))
        self.assertIn("ok=", loc)
        self.assertIn("Plan izlaza prijedloga", loc)
        t = self.lg.execute("SELECT * FROM trades WHERE user=? AND token=? AND status='open'",
                            (settings.LEAGUE_USER, MINT)).fetchone()
        auto = json.loads(t["auto"])
        self.assertEqual(auto["mode"], "tpsl")                                     # the position's own TP/SL
        self.assertAlmostEqual(auto["sl_px"], 70_000 / 82_000, places=6)
        self.assertTrue(t["source"].startswith("ručno: prijedlog"))
        plan = exitplan.active(self.lg, MINT)
        self.assertEqual(plan["plan"]["accounts"], [settings.LEAGUE_USER])
        # 11.11. (plan uz kupnju): the proposal's whole plan is the position's panel plan (live under exit_plan_live)
        self.assertEqual(plan["client"], f"{exitplan.PANEL_SRC} prijedlog #{pid}")
        self.assertEqual(plan["plan"]["trailing"], {"activate_pct": 20.0, "trail_pct": 8.0})
        con = store.ro(self.ppath)
        p = store.one(con, pid)
        con.close()
        self.assertEqual((p["status"], p["bought_sol"]), ("kupljeno", 0.1))
        sizes = settings.raw(self.con).get("manual_size")
        self.assertEqual(list(sizes.values()), [0.1])                             # the real swap's own stake
        # the same proposal cannot be bought twice through it
        loc = unquote_(self.post("/pravi-trade/buy", {"token": MINT, "sol": "0,1", "tp": "$100k", "sl": "$70k",
                                                      "exit": "tpsl", "prijedlog": str(pid)}))
        self.assertIn("err=", loc)

    def test_paper_only_on_the_demo_account(self):
        import time as _t
        now = int(_t.time())
        r = prow(MINT, tp=20.0, sl=12.0, exp=now + 900)
        r["buy"] = {"tp": "20%", "sl": "-12%", "sol": 0.15, "hold_s": 2700}
        # 11.11.: the demo account enters only inside the entry zone and above the stop (MC $82k here)
        r.update(entry_zone={"mcap_low": 80_000, "mcap_high": 85_000}, mcap0=82_000,
                 exits_mcap={"tp": [98_400], "tp_share": [1.0], "sl": 72_160})
        con = store.connect(self.ppath)
        pid = store.insert(con, r, now)
        con.commit()
        con.close()
        mk = lambda toks: {t: (1.0, 60_000.0, None, 82_000.0) for t in toks}   # noqa: E731
        with mock.patch.object(lcopy, "_rugged", lambda *a: None):
            self.assertEqual(paper.run_once(self.lg, mk, now, sol=200.0), [])   # flag off
            settings.set_flag(self.con, "proposals", "shadow", "Jure")
            settings._FLAG_CACHE.clear()
            self.assertEqual(paper.run_once(self.lg, mk, now, sol=200.0), [])   # shadow: list and measure only
            settings.put(self.con, "flag:proposals", {"mode": "paper", "since": now})
            settings._FLAG_CACHE.clear()
            done = paper.run_once(self.lg, mk, now, sol=200.0)
            self.assertEqual([u for u, _w in done], [settings.PAPER_USER])
            self.assertEqual(paper.run_once(self.lg, mk, now, sol=200.0), [])   # once per proposal
        users = [u for (u,) in self.lg.execute("SELECT user FROM trades WHERE token=? AND status='open'", (MINT,))]
        self.assertEqual(users, [settings.PAPER_USER])                             # never the real account
        t = self.lg.execute("SELECT * FROM trades WHERE user=? AND token=?", (settings.PAPER_USER, MINT)).fetchone()
        self.assertEqual(json.loads(t["auto"])["mode"], "tpsl")
        self.assertAlmostEqual(t["size_usd"], 0.15 * 200, places=4)
        pt = self.lg.execute("SELECT proposal_id, strategy, status FROM proposal_trades").fetchone()
        self.assertEqual(tuple(pt), (pid, "momentum", "open"))
        self.assertEqual(exitplan.active(self.lg, MINT)["plan"]["accounts"], [settings.PAPER_USER])
        self.lg.execute("UPDATE trades SET status='closed', ret=0.12, closed_ts=? WHERE id=?", (now + 60, t["id"]))
        self.lg.commit()
        paper.sync_closed(self.lg, settings.PAPER_USER)
        self.assertEqual(paper.proof(self.lg)["momentum"], {"n": 1, "hits": 1, "hit_rate": 1.0, "ev_pct": 12.0})


def unquote_(s):
    from urllib.parse import unquote
    return unquote(s)


# ---------- 11.11. waiting for the entry zone (HAOBIBI), the stop rule, range_dca's round -----------------------------------

from league import store as lstore  # noqa: E402
from rangedca import trade as rtrade  # noqa: E402
from tests.test_range_dca_offline import TradeBase as RangeBase, S as RS  # noqa: E402

HAO = "8tbfkL8L" + "H" * 32 + "pump"   # HAOBIBI (only the start of the real mint is known here: symbolic)
HAO_ZONE, HAO_SL = {"mcap_low": 104_000, "mcap_high": 112_000}, 88_600


def hao_row(tok=HAO, mcap0=88_120, ev=20.0, hits=30, n=40, created=NOW):
    """The HAOBIBI range proposal of 11.11.: zone $104-112k, stop $88.6k, TP $172.3k / $190k."""
    r = prow(tok, ev=ev, sources=("range",), exp=created + 7200)
    r.update(symbol="HAOBIBI", entry_zone=dict(HAO_ZONE), mcap0=mcap0, price0=mcap0 / 1e9, liq0=60_000,
             market={"market_cap_usd": mcap0, "price_usd": mcap0 / 1e9, "liquidity_usd": 60_000},
             exits_mcap={"tp": [172_300, 190_000], "tp_share": [0.5, 0.5], "sl": HAO_SL, "trailing_pct": 10,
                         "time_min": 360},
             exit_plan={"take_profits": [{"at_mc_usd": 172_300, "sell_share": 0.5},
                                         {"at_mc_usd": 190_000, "sell_share": 0.5}],
                        "stop": {"at_mc_usd": HAO_SL}, "trailing": {"activate_pct": 70, "trail_pct": 10},
                        "time_stop": {"after_min": 360, "if_pnl_below_pct": 0}},
             buy={"tp": "$172.3k", "sl": "$88.6k", "sol": 0.15, "hold_s": None},
             strategies={"range": {"valid": True, "ev_pct": ev, "p_tp": 0.6, "n": n, "hits": hits, "p_mult": 1.0,
                                   "calibrated": False, "expires_ts": None, "expires_after_s": 7200}})
    return r


def at_mc(mcap, liq=60_000.0, seen=None):
    def mk(toks):
        if seen is not None:
            seen.append(sorted(toks))
        return {t: (mcap / 1e9, liq, None, float(mcap)) for t in toks}
    return mk


class ZoneEntry(BuyBase):
    """paper.run_once enters a waiting proposal only inside its zone, above its stop, never next to a range round."""

    def setUp(self):
        super().setUp()
        self.ppath = os.path.join(self.tmp.name, "proposals.db")
        self.penv = mock.patch.dict(os.environ, {"PROPOSALS_DB": self.ppath})
        self.penv.start()
        self.rug = mock.patch.object(lcopy, "_rugged", lambda *a: None)
        self.rug.start()
        self.now = int(__import__("time").time())
        settings.put(self.con, "flag:proposals", {"mode": "paper", "since": self.now})
        settings._FLAG_CACHE.clear()
        paper._LAST.clear()
        view.clear()

    def tearDown(self):
        self.rug.stop()
        self.penv.stop()
        settings._FLAG_CACHE.clear()
        paper._LAST.clear()
        view.clear()
        super().tearDown()

    def seed(self, r, created):
        con = store.connect(self.ppath)
        try:
            pid = store.insert(con, r, created)
            con.commit()
            return pid
        finally:
            con.close()

    def prop(self, pid):
        con = store.ro(self.ppath)
        try:
            return store.one(con, pid)
        finally:
            con.close()

    def go(self, mk, now):
        return paper.run_once(self.lg, mk, now, sol=200.0)

    def held(self, tok=HAO):
        return [tuple(r) for r in self.lg.execute("SELECT user, source FROM trades WHERE token=? AND status='open'", (tok,))]

    def test_haobibi_replay_under_the_stop_at_creation_waits_then_enters_in_the_zone(self):
        # made 1 h ago (long past the old 10-min window) while the price was already under its $88.6k stop
        pid = self.seed(hao_row(mcap0=88_120, created=self.now - 3600), self.now - 3600)
        p = self.prop(pid)
        self.assertEqual(p["below_sl_at_creation"], 1)
        self.assertEqual(self.go(at_mc(88_120), self.now), [])                      # 11:44:39: no entry at $88k
        p = self.prop(pid)
        self.assertEqual((p["status"], p["last_mcap"], p["paper_ts"]), ("novo", 88_120, None))   # still waiting
        # 11.11. (decision 4): outside the zone and under the stop -> not published, "čeka zonu" with the reason
        self.assertEqual(view.entry_state(p, self.now)["state"], "čeka zonu")
        self.assertIn("ispod SL-a", view.entry_state(p, self.now)["text"])
        self.assertIn("izvan zone ulaza $104k–$112k", p["wait_why"])
        self.assertEqual(self.held(), [])
        self.assertEqual(self.go(at_mc(100_000), self.now + 20), [])               # under the zone: waits
        done = self.go(at_mc(108_000), self.now + 40)                              # in the zone: paper entry
        self.assertEqual(len(done), 1, done)
        self.assertEqual(done[0][0], settings.PAPER_USER)
        self.assertIn("ušao (paper) na MC $108,000", done[0][1])
        self.assertIn("$104k–$112k", done[0][1])
        self.assertEqual(self.held(), [(settings.PAPER_USER, "prijedlog (demo): range")])
        p = self.prop(pid)
        self.assertEqual((p["status"], p["paper_mcap"], p["status_why"]), ("novo", 108_000, "ušao (paper) na MC $108,000"))
        self.assertIsNotNone(p["zone_seen_ts"])
        self.assertEqual(view.entry_state(p, self.now)["state"], "ušao (paper)")
        self.assertEqual(self.go(at_mc(108_000), self.now + 60), [])               # once per proposal
        t = self.lg.execute("SELECT auto FROM trades WHERE user=? AND token=?", (settings.PAPER_USER, HAO)).fetchone()
        self.assertEqual(json.loads(t[0])["mode"], "tpsl")

    def test_above_the_stop_at_creation_then_under_it_expires(self):
        pid = self.seed(hao_row(mcap0=96_210, created=self.now - 600), self.now - 600)   # lot 2's MC: above the stop
        self.assertEqual(self.prop(pid)["below_sl_at_creation"], 0)
        self.assertEqual(self.go(at_mc(88_120), self.now), [])
        p = self.prop(pid)
        self.assertEqual(p["status"], "isteklo")
        self.assertTrue(p["status_why"].startswith("pao ispod SL-a"), p["status_why"])
        self.assertEqual(self.go(at_mc(108_000), self.now + 20), [])               # dead: never entered
        self.assertEqual(self.held(), [])

    def test_entry_only_inside_the_zone_and_with_ev_above_zero(self):
        pid = self.seed(hao_row(mcap0=108_000, created=self.now - 60), self.now - 60)
        for i, mc in enumerate((103_000, 112_500, 150_000)):
            self.assertEqual(self.go(at_mc(mc), self.now + 20 * i), [], mc)
        self.assertEqual(self.prop(pid)["status"], "novo")
        self.assertEqual(self.go(at_mc(108_000, liq=14_000), self.now + 80), [])   # liquidity under $15k
        self.assertEqual(len(self.go(at_mc(104_000, liq=16_000), self.now + 100)), 1)   # $15k floor (not $20k), inclusive
        # EV recomputed at the entry: a record with no hits is not entered even inside the zone
        pid2 = self.seed(hao_row(tok=mint(30), mcap0=108_000, hits=0, created=self.now), self.now)
        self.assertEqual(self.go(at_mc(108_000), self.now + 120), [])
        self.assertEqual(self.prop(pid2)["paper_ts"], None)
        # a proposal without an entry zone waits for its market cap +- 5 %
        r = prow(mint(31), exp=self.now + 900)
        r["entry_zone"] = None
        self.seed(r, self.now)
        self.assertEqual(self.go(at_mc(110_000), self.now + 140), [])
        self.assertEqual(len(self.go(at_mc(104_000), self.now + 160)), 1)

    def test_older_than_ten_minutes_and_the_cap_per_pass(self):
        seen = []
        for i in range(paper.PASS_CAP + 10):
            self.seed(hao_row(tok=mint(100 + i), mcap0=108_000, ev=1.0 + i, created=self.now - 5400), self.now - 5400)
        self.assertEqual(self.go(at_mc(150_000, seen=seen), self.now), [])          # all outside: nothing bought
        self.assertEqual(len(seen[0]), paper.PASS_CAP)                              # at most 50 priced a pass
        self.assertNotIn(mint(100), seen[0])                                        # the lowest EV ones wait
        self.assertIn(mint(100 + paper.PASS_CAP + 9), seen[0])
        self.assertEqual(self.go(at_mc(150_000, seen=seen), self.now + 5), [])      # at most every CHECK_EVERY_S
        self.assertEqual(len(seen), 1)

    def test_range_round_open_cooldown_and_pause_block_the_entry(self):
        pid = self.seed(hao_row(mcap0=108_000, created=self.now - 60), self.now - 60)
        rtrade.ensure(self.lg)
        self.lg.execute("INSERT INTO range_rounds (user, token, opened_ts, status, levels, state) VALUES (?,?,?,?,?,?)",
                        (settings.PAPER_USER, HAO, self.now - 3000, "open", "{}", "{}"))
        self.lg.commit()
        self.assertEqual(self.go(at_mc(108_000), self.now), [])                    # its second buy is range's lot 2
        # HAOBIBI: the round closed on its stop 2 s before
        self.lg.execute("UPDATE range_rounds SET status='closed', closed_ts=? WHERE token=?", (self.now + 18, HAO))
        self.lg.commit()
        self.assertEqual(self.go(at_mc(108_000), self.now + 20), [])
        self.assertIn("cooldown", rtrade.busy(self.lg, settings.PAPER_USER, HAO, self.now + 20))
        self.assertEqual(self.held(), [])
        # the range paused by range_flip
        later = self.now + 18 + 20 * 60 + 1
        with mock.patch.object(paper, "_range_rows", lambda toks: {HAO: {"flip": {"state": "paused"}}}):
            self.assertEqual(self.go(at_mc(108_000), later), [])
        self.assertIsNone(rtrade.busy(self.lg, settings.PAPER_USER, HAO, later))
        self.assertEqual(len(self.go(at_mc(108_000), later + 20)), 1)              # after the cooldown it may
        self.assertEqual(self.prop(pid)["paper_mcap"], 108_000)

    def test_live_is_still_refused_and_only_the_demo_account_enters(self):
        with self.assertRaises(ValueError):
            settings.set_flag(self.con, "proposals", "live", "Jure")
        self.assertTrue(paper.live_refusal(self.con))
        settings.put(self.con, "flag:proposals", {"mode": "live", "since": self.now})   # a hand edit: still paper only
        settings._FLAG_CACHE.clear()
        self.seed(hao_row(mcap0=108_000, created=self.now), self.now)
        done = self.go(at_mc(108_000), self.now)
        self.assertEqual([u for u, _w in done], [settings.PAPER_USER])
        self.assertEqual(self.held(), [(settings.PAPER_USER, "prijedlog (demo): range")])

    def test_the_card_and_get_proposals_show_the_waiting_state(self):
        from ui.html import esc
        pid = self.seed(hao_row(mcap0=96_210, created=self.now), self.now)
        p = self.prop(pid)
        self.assertIn("čeka ulaz · sada $96k, zona $104k–$112k", view._row_inner(p, esc))
        con = store.connect(self.ppath)
        store.mark_seen(con, [(pid, 108_000, True)], self.now)
        con.commit()
        con.close()
        p = self.prop(pid)
        self.assertEqual(view.entry_state(p, self.now)["state"], "u zoni")
        self.assertIn("u zoni", view._row_inner(p, esc))
        es = view._mcp_row(p)["entry_state"]
        self.assertEqual((es["state"], es["zone"], es["sl"], es["below_sl_at_creation"]),
                         ("u zoni", [104_000, 112_000], HAO_SL, 0))


class WaitSync(unittest.TestCase):
    """job.sync: a vanished source with the price outside the zone keeps the proposal waiting; the stop rule."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "proposals.db")
        self.con = store.connect(self.path)

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def p(self, tok=HAO):
        return store.last_by_token(self.con, [tok])[tok]

    def test_vanished_source_outside_the_zone_keeps_waiting(self):
        c = self.con
        job.sync(c, [hao_row(mcap0=108_000)], [], NOW)                              # made in the zone
        self.assertEqual(self.p()["zone_seen_mcap"], 108_000)
        # the range dropped out because the price left the bottom zone ($97k): it waits
        out = job.sync(c, [], [], NOW + 150, prices={HAO: (97e-6, 97_000)})
        self.assertEqual((out["expired"], out["waiting"], self.p()["status"]), (0, 1, "novo"))
        self.assertEqual(self.p()["last_mcap"], 97_000)
        # no price at all this pass: only the time rule decides
        self.assertEqual(job.sync(c, [], [], NOW + 900)["expired"], 0)
        # the pass's own px point (newer than the paper loop's read) outside the zone: still waiting
        c.execute("INSERT INTO px VALUES (?,?,?,?)", (HAO, NOW + 1000, 99e-6, 99_000))
        self.assertEqual(job.sync(c, [], [], NOW + 1050)["expired"], 0)
        # a near miss that is a price reason (EV / an invalid strategy) outside the zone: waiting
        near = [{"token": HAO, "why": "EV -1,0 % nakon troška", "blocks": [], "mcap": 100_000}]
        self.assertEqual(job.sync(c, [], near, NOW + 1100)["expired"], 0)
        # a hard block (rug) still expires it
        near = [{"token": HAO, "why": "rug (kolaps)", "blocks": [{"key": "rug_hard"}], "mcap": 100_000}]
        job.sync(c, [], near, NOW + 1200)
        self.assertEqual((self.p()["status"], self.p()["status_why"]), ("isteklo", "više ne vrijedi: rug (kolaps)"))
        # the source vanished while the price IS in the zone: not a price reason, it expires as before
        job.sync(c, [hao_row(tok=A, mcap0=108_000)], [], NOW)
        job.sync(c, [], [], NOW + 150, prices={A: (108e-6, 108_000)})
        self.assertEqual(self.p(A)["status_why"], "više ne vrijedi: izvor prijedloga je nestao")
        # and the time expiry ends any wait
        job.sync(c, [hao_row(tok=B, mcap0=108_000)], [], NOW)
        job.sync(c, [], [], NOW + 7201, prices={B: (97e-6, 97_000)})
        self.assertEqual(self.p(B)["status_why"], "vrijeme je isteklo")

    def test_the_stop_rule_in_the_pass(self):
        c = self.con
        job.sync(c, [hao_row(mcap0=88_120)], [], NOW)                               # made under its stop
        self.assertEqual(self.p()["below_sl_at_creation"], 1)
        job.sync(c, [hao_row(mcap0=87_000)], [], NOW + 150)                         # still under it: waits
        job.sync(c, [], [], NOW + 300, prices={HAO: (85e-6, 85_000)})
        self.assertEqual(self.p()["status"], "novo")
        job.sync(c, [hao_row(mcap0=106_000)], [], NOW + 450)                        # in the zone: armed
        self.assertIsNotNone(self.p()["zone_seen_ts"])
        job.sync(c, [], [], NOW + 600, prices={HAO: (88e-6, 88_000)})              # then under the stop: dead
        self.assertTrue(self.p()["status_why"].startswith("pao ispod SL-a"))
        # above the stop at creation, then under it while still shown
        job.sync(c, [hao_row(tok=A, mcap0=96_210)], [], NOW)
        job.sync(c, [hao_row(tok=A, mcap0=88_120)], [], NOW + 150)
        self.assertEqual(self.p(A)["status"], "isteklo")

    def test_an_old_database_gets_the_columns_and_old_readers_still_read(self):
        p2 = os.path.join(self.tmp.name, "old.db")
        old = sqlite3.connect(p2)
        old.executescript(store.SCHEMA.replace(",\n    below_sl_at_creation INTEGER, last_mcap REAL, last_mcap_ts "
                                               "INTEGER, zone_seen_ts INTEGER, zone_seen_mcap REAL,\n    paper_ts "
                                               "INTEGER, paper_mcap REAL", ""))
        self.assertNotIn("paper_ts", {r[1] for r in old.execute("PRAGMA table_info(proposals)")})
        old.execute("INSERT INTO proposals (token, created_ts, expires_ts, status, row) VALUES (?,?,?,?,?)",
                    (A, NOW, NOW + 900, "novo", json.dumps(prow(A))))
        old.commit()
        got = store.read(old, "status='novo'")                                      # an unmigrated reader
        self.assertEqual((got[0]["token"], got[0]["paper_ts"]), (A, None))
        old.close()
        con = store.connect(p2)
        self.assertIn("paper_ts", {r[1] for r in con.execute("PRAGMA table_info(proposals)")})
        con.close()


class ZoneMisses(unittest.TestCase):
    """report.zone_misses on a fixture: through the zone without a paper entry, paper, range round, never, no data."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "proposals.db")
        self.con = store.connect(self.path)
        self.lc = sqlite3.connect(":memory:")
        paper.ensure(self.lc)
        rtrade.ensure(self.lc)
        self.lc.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, user TEXT, token TEXT, opened_ts INTEGER, "
                        "closed_ts INTEGER, status TEXT, source TEXT, entry_mcap REAL)")

    def tearDown(self):
        self.con.close()
        self.lc.close()
        self.tmp.cleanup()

    def add(self, r, created, status="novo", why=None, pts=()):
        pid = store.insert(self.con, r, created)
        if status != "novo":
            store.set_status(self.con, pid, status, why, created + 300)
        for dt_, mc in pts:
            self.con.execute("INSERT INTO px VALUES (?,?,?,?)", (r["token"], created + dt_, mc / 1e9, mc))
        return pid

    def test_report_on_a_fixture_and_the_log_block_once(self):
        T = NOW - 30 * 3600
        G, H = mint(40), mint(41)
        # HAOBIBI: its source vanished at +300 s (the old rule), the price came into the zone at +600 s, then TP1 / TP2
        p1 = self.add(hao_row(mcap0=96_000, created=T), T, "isteklo", "više ne vrijedi: izvor prijedloga je nestao",
                      [(60, 97_000), (600, 108_000), (1200, 120_000), (1800, 175_000), (2400, 195_000)])
        # a paper entry by the old rule: bought at $88k, outside its zone and under its stop (#2 of 11.11.)
        p2 = self.add(hao_row(tok=A, mcap0=88_120, created=T), T, pts=[(60, 88_120), (600, 80_000)])
        self.lc.execute("INSERT INTO trades (id, user, token, opened_ts, status, source, entry_mcap) VALUES "
                        "(7,?,?,?,?,?,?)", (settings.PAPER_USER, A, T + 60, "closed", "prijedlog (demo): range", 88_120))
        self.lc.execute("INSERT INTO proposal_trades (user, proposal_id, token, strategy, trade_id, opened_ts, status) "
                        "VALUES (?,?,?,?,?,?,?)", (settings.PAPER_USER, p2, A, "range", 7, T + 60, "open"))
        # in the zone at +300 s, while range_dca's round closed at +250 s (its cooldown runs to +1450 s)
        self.add(hao_row(tok=B, mcap0=96_000, created=T), T, pts=[(300, 106_000), (900, 70_000)])
        self.lc.execute("INSERT INTO range_rounds (user, token, opened_ts, closed_ts, status) VALUES (?,?,?,?,?)",
                        (settings.PAPER_USER, B, T + 100, T + 250, "closed"))
        self.add(hao_row(tok=C, mcap0=96_000, created=T), T, pts=[(60, 97_000), (600, 99_000)])   # never in the zone
        self.add(hao_row(tok=D, mcap0=96_000, created=T), T)                                      # no prices at all
        # a momentum proposal through its zone, then its -10 % stop
        r = prow(G, exp=T + 900)
        r.update(entry_zone={"mcap_low": 100_000, "mcap_high": 105_000}, mcap0=100_000, price0=100_000 / 1e9)
        self.add(r, T, pts=[(60, 101_000), (300, 89_000)])
        # one older than 48 h is not in the window
        self.add(hao_row(tok=H, mcap0=108_000, created=NOW - 50 * 3600), NOW - 50 * 3600, pts=[(60, 108_000)])
        self.con.commit()
        from events import predictions
        econ = sqlite3.connect(":memory:")
        self.addCleanup(econ.close)

        def path_fn(tok, t0, t1):
            return outcomes.path(tok, t0, t1, econ=econ, pcon=self.con, mom_path="/nema")
        with mock.patch.object(predictions, "_minute_rows", lambda *a, **k: []):
            rep = report.zone_misses(NOW, con=self.con, lcon=self.lc, path_fn=path_fn)
        self.assertEqual((rep["n"], rep["missed"], rep["paper"], rep["skipped_range"], rep["not_in_zone"],
                          rep["no_data"]), (6, 2, 1, 1, 1, 1))
        got = {r["id"]: r for r in rep["list"]}
        h = got[p1]
        self.assertEqual((h["first_in_zone_mc"], h["outcome"], h["zone"]), (108_000, "tp", [104_000, 112_000]))
        cost = tcost.round_trip(0.15 * kandidati.SOL_USD, 60_000)
        self.assertAlmostEqual(h["ret_pct"], round(((172_300 + 190_000) / 2 / 108_000 - 1 - cost) * 100, 2), places=2)
        mom = [r for r in rep["list"] if r["token"] == G][0]
        self.assertEqual((mom["outcome"], mom["first_in_zone_mc"]), ("sl", 101_000))
        self.assertAlmostEqual(mom["ret_pct"], round((-0.10 - tcost.round_trip(0.15 * kandidati.SOL_USD, 60_000)) * 100, 2),
                               places=2)
        self.assertEqual(rep["per_strategy"]["range"]["skipped_range"], 1)
        self.assertEqual(rep["per_strategy"]["momentum"]["outcomes"]["sl"], 1)
        self.assertEqual([s["token"] for s in rep["skipped"]], [B])
        self.assertEqual((rep["paper_outside_zone"], rep["paper_outside"][0]["paper_mcap"]), (1, 88_120))
        lines = report.zone_lines(rep)
        self.assertIn("paper ulaz 1 (od toga izvan zone ili ispod SL-a 1)", lines[0])
        self.assertTrue(lines[0].startswith("prijedlozi kroz zonu bez paper ulaza (48 h): 2 od 6, ishod: TP prvi 1, SL prvi 1"))
        self.assertIn("preskočeno: range runda/cooldown 1", lines[0])
        self.assertTrue(any("HAOBIBI (raspon) zona $104k–$112k, prvi u zoni $108k -> TP prvi" in ln for ln in lines))
        # the pass: once in the log, then into get_proposals' report (kv zone_misses)
        logged = []
        with mock.patch.object(report, "zone_misses", lambda now, **k: rep):
            job.zone_report(self.con, NOW, logged.append)
            job.zone_report(self.con, NOW + 4000, logged.append)                     # refreshed, not logged again
        self.assertEqual(len(logged), 1)
        self.assertEqual(logged[0].count("\n"), len(lines) - 1)                     # ONE block
        self.assertEqual(store.kv_get(self.con, "zone_misses")["missed"], 2)
        self.con.commit()
        with mock.patch.object(view, "_mode", lambda: "paper"):
            d = view.mcp(path=self.path, now=NOW)
        self.assertEqual(d["report"]["zone_misses"]["missed"], 2)


class RangeSeesTheProposal(RangeBase):
    def test_a_proposal_position_on_the_demo_account_blocks_a_range_round(self):
        self.mode("paper")
        lstore.buy(self.lg, settings.PAPER_USER, MINT, "RNG", 30, 52 * RS, 25_000, "prijedlog (demo): range", None,
                   52_000)
        self.assertEqual(self.enter(), [])                                          # range's _held: no lot 1
        self.assertEqual(rtrade.rounds(self.lg), [])
        self.assertEqual([t["source"] for t in self.lots(settings.PAPER_USER)], ["prijedlog (demo): range"])
        self.lg.execute("UPDATE trades SET status='closed', closed_ts=? WHERE token=?", (self.now, MINT))
        self.lg.commit()
        self.assertEqual(len(self.enter()), 1)                                      # the token is free again


# ---------- MCP and submit_signal_opinion ----------------------------------------------------------------------------------

class Mcp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._saved = settings.DB
        settings.DB = os.path.join(self.tmp.name, "trade.db")
        self.tc = executor.connect(settings.DB)

    def tearDown(self):
        settings.DB = self._saved
        self.tc.close()
        self.tmp.cleanup()

    def test_schema(self):
        names = {t["name"]: t for t in mcpapi.TOOLS}
        g = names["get_proposals"]
        self.assertTrue(g["annotations"]["readOnlyHint"])
        self.assertEqual(sorted(g["inputSchema"]["properties"]), ["include_blocked", "limit", "min_ev", "since", "status"])
        s = names["submit_signal_opinion"]["inputSchema"]
        self.assertEqual(s["required"], ["token", "verdict", "interpretation"])   # unchanged
        for k in ("strategy", "p_tp", "entry_zone", "exit_zone", "valid_min"):
            self.assertIn(k, s["properties"])
        self.assertEqual(sorted(s["properties"]["exit_zone"]["properties"]), ["sl_mcap", "tp_mcap", "trailing_pct"])
        self.assertEqual(sorted(s["properties"]["entry_zone"]["properties"]), ["mcap_high", "mcap_low"])

    def test_submit_signal_opinion_backward_compatible(self):
        d, err = mcpapi._tool("submit_signal_opinion", {"token": A, "verdict": "kupi", "interpretation": "dobar X"},
                              kid="g")
        self.assertFalse(err, d)
        self.assertNotIn("proposal", d)
        self.assertEqual(self.tc.execute("SELECT verdict, proposal FROM assistant_notes").fetchone(), ("kupi", None))

    def test_submit_signal_opinion_with_a_proposal_and_the_reader(self):
        d, err = mcpapi._tool("submit_signal_opinion", {
            "token": A, "verdict": "kupi", "interpretation": "jak X", "p_tp": 0.35, "strategy": "momentum_scalp",
            "entry_zone": {"mcap_low": 80_000, "mcap_high": 95_000},
            "exit_zone": {"tp_mcap": 140_000, "sl_mcap": 70_000, "trailing_pct": 10}, "valid_min": 30}, kid="g")
        self.assertFalse(err, d)
        self.assertEqual(d["proposal"]["strategy"], "momentum")
        self.assertIn("CALIBRATED", d["proposal_note"])
        got = build.Sources(trade_db=settings.DB).grok_proposals(int(__import__("time").time()))
        self.assertEqual(got[A]["proposal"]["p_tp"], 0.35)
        for bad in ({"p_tp": 1.5}, {"strategy": "moon"}, {"exit_zone": {"tp_mcap": 50, "sl_mcap": 90}},
                    {"entry_zone": {"mcap_low": 9, "mcap_high": 5}}, {"valid_min": 2},
                    {"entry_zone": {"mcap_low": 80_000, "mcap_high": 95_000}, "exit_zone": {"tp_mcap": 70_000}}):
            d, err = mcpapi._tool("submit_signal_opinion", {"token": A, "verdict": "kupi", "interpretation": "x", **bad},
                                  kid="g")
            self.assertTrue(err, bad)
        # a newer opinion without a proposal takes it back
        mcpapi._tool("submit_signal_opinion", {"token": A, "verdict": "preskoči", "interpretation": "pada"}, kid="g")
        self.assertEqual(build.Sources(trade_db=settings.DB).grok_proposals(int(__import__("time").time())), {})

    def test_an_old_table_gets_the_column(self):
        con = sqlite3.connect(":memory:")
        con.execute(assistnotes.SCHEMA.replace(", key_id TEXT", ""))
        con.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, token TEXT, symbol TEXT)")
        assistnotes.submit_signal_opinion(con, "k", A, "kupi", interpretation="x", proposal={"p_tp": 0.4})
        self.assertEqual(json.loads(con.execute("SELECT proposal FROM assistant_notes").fetchone()[0]), {"p_tp": 0.4})


# ---------- the daily report ----------------------------------------------------------------------------------------------

class Report(unittest.TestCase):
    def test_per_strategy_and_missed_risers(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "proposals.db")
        con = store.connect(path)
        _d, start = report.day_bounds(NOW)
        pid = store.insert(con, prow(A, sources=("momentum", "influencer")), start + 3600)
        con.execute("UPDATE proposals SET after=?, after_done=1, status='odbijeno', reject_reason='kasno' WHERE id=?",
                    (json.dumps({"4h": {"status": "ok", "first": "tp", "ret_pct": 12.0}}), pid))
        job.record_seen(con, [], [{"token": B, "symbol": "BB", "strategies": ["momentum"], "why": "lažni volumen",
                                   "blocks": [{"key": "wash"}], "strategy_detail": {}, "mcap": 90_000}], start + 7200)
        con.commit()
        con.close()
        scan = sqlite3.connect(":memory:")
        scan.execute("CREATE TABLE cand (token TEXT, symbol TEXT, mcap REAL, ch_h24 REAL, last_seen INTEGER)")
        scan.executemany("INSERT INTO cand VALUES (?,?,?,?,?)", [(A, "AA", 200_000, 300.0, start + 100),
                                                                 (B, "BB", 90_000, 250.0, start + 100),
                                                                 (C, "CC", 500_000, 400.0, start + 100),
                                                                 (D, "DD", 20_000, 900.0, start + 100)])   # under 30k
        mom = sqlite3.connect(":memory:")
        mom.execute("CREATE TABLE snaps (token TEXT, ts INTEGER, mcap REAL)")
        mom.execute("CREATE TABLE signals (token TEXT, ts INTEGER)")
        lc = sqlite3.connect(":memory:")
        with mock.patch.object(report, "_momentum_seen", lambda toks, st, m=None: (set(), set())):
            rep = report.daily(NOW, path, lcon=lc, scan_con=scan, mom_con=mom)
        self.assertEqual(rep["per_strategy"]["momentum"]["proposals"], 1)
        self.assertEqual(rep["per_strategy"]["momentum"]["hit_rate"], 1.0)
        self.assertEqual(rep["per_strategy"]["influencer"]["ev_pct"], 12.0)
        self.assertEqual(rep["reject_reasons"], {"kasno": 1})
        missed = {m["token"]: m for m in rep["missed_risers"]}
        self.assertNotIn(A, missed)                                                 # we proposed it
        self.assertNotIn(D, missed)                                                 # under 30k
        self.assertEqual(list(missed), [C, B])                                      # biggest first
        self.assertTrue(missed[B]["strategies"]["momentum"].startswith("skoro"))
        self.assertEqual(missed[C]["strategies"]["momentum"], "nikad")
        self.assertTrue(any("Propušten rast" in ln for ln in report.lines(rep)))
        self.assertEqual(report.latest(path)["day"], rep["day"])
        # the 23:30 EV report (events/evreport) takes one row per strategy that proposed something
        logged = []
        with mock.patch.object(report, "daily", lambda now, path=None: rep):
            rows = report.ev_rows(NOW, "shadow", log=logged.append)
        self.assertEqual(sorted(r["part"] for r in rows), ["prijedlozi:influencer", "prijedlozi:momentum"])
        self.assertTrue(all(r["flag"] == "proposals" and r["phase"] == "shadow" for r in rows))
        self.assertTrue(logged and logged[0].startswith("Prijedlozi "))
        import inspect
        from events import evreport
        self.assertIn('name == "proposals"', inspect.getsource(evreport.build))


if __name__ == "__main__":
    unittest.main()
