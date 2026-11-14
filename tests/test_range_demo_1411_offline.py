"""14.11. (Jure: "U svakom momentu na kripto tržištu ima stotine tokena koji se kreću u range-u ... Ako je neki token
izdržao ovaj bloodbath ... i ako se vratio u range, pronađi ga i želim da danas otvoriš barem 5 tradeova ... otvaraj
pozicije ... u donjem dijelu range-a. Testiraj sa stop loss, nemoj stavljati preblizu stop loss ... da se uzima barem
10-15% profita"). The wider market universe (30k floor, 5k volume, promote, the PumpSwap pages, DexScreener takeovers
and profile updates, the hype scan, KOL calls of 7 days, former ranges), the crash-survivor check, the demo profile
rules.DEMO (flag range_demo G32: entry thresholds, TP +10 / +15 % net, the stop held at -12..-25 % from the entry,
break-even after TP1), the daily counter "range demo danas: N tradeova (cilj 5)" with its top 3 block reasons, the
real-money gates that never count a demo round, and the backtest of the profile on the range fixtures. No network.

    python3 -m unittest tests.test_range_demo_1411_offline
"""
import gzip
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from league import store  # noqa: E402
from rangedca import backtest, data, gate, market, rules, survivor, trade, view  # noqa: E402
from trade import cost as tcost, settings  # noqa: E402
from tests.test_range_dca_offline import LU, MINT, PU, S, T0, TradeBase, tri  # noqa: E402
from tests.test_range_market_offline import Net, RDB, pair  # noqa: E402

D = 86400
FX = os.path.join(ROOT, "tests", "fixtures")
SURV = {"ok": True, "crashed": False, "age_h": 72.0, "loss_24h": -0.2, "in_range": True,
        "why": "preživio pad: star 3,0 d, MC −20 % od prije 24 h, opet u rasponu"}


def fx_series(names):
    out = {}
    for n in names:
        with gzip.open(os.path.join(FX, n), "rt") as f:
            fx = json.load(f)
        out[fx["token"]] = (data.merge([tuple(r) for r in fx["candles"]], []), fx["supply"], None, fx.get("symbol"))
    return out


# ---------------------------------------------------------------------------------------------------------------
class Universe(RDB):
    """Point 1: why the market list held ~6 tokens and the sources that widen it (all stubbed, no network)."""

    def test_the_owners_30k_floor_and_the_calmer_volume(self):
        now = 1_794_400_000
        s = {"price": 1e-4, "bonded": True, "mcap": 35_000, "liq": 16_000, "vol_h1": 5_500}
        self.assertEqual(market.MIN_MCAP, 30_000)                           # was 50k
        self.assertEqual(market.MIN_VOL_H1, 5_000)                          # was 10k
        self.assertTrue(market.check(s, now - 7 * 3600, "market", now)[0])   # a 35k token after the crash: admitted
        self.assertFalse(market.check(dict(s, mcap=29_000), now - 7 * 3600, "market", now)[0])   # never under 30k
        self.assertFalse(market.check(dict(s, liq=14_000), now - 7 * 3600, "market", now)[0])    # liquidity 15k stays
        kept = market.check(dict(s, vol_h1=3_500), now - 7 * 3600, "market", now, keep=True)
        self.assertTrue(kept[0])                                            # a watched one stays down to $3k

    def test_promote_makes_a_deferred_token_due_now(self):
        now = 1_794_400_000
        tok = "P" * 43 + "pump"
        market.add(self.con, tok, "migracija", now - 3600, due=now - 3600)
        self.con.execute("UPDATE mkt SET next_ts=?, why=? WHERE token=?", (now + D, "MC ispod 30k (ne analizira se)", tok))
        market.add(self.con, tok, "gt", now, nums={"mcap": 90_000})          # seen, numbers unknown: waits
        self.assertEqual(self.con.execute("SELECT next_ts FROM mkt WHERE token=?", (tok,)).fetchone()[0], now + D)
        market.add(self.con, tok, "gt", now, nums={"mcap": 90_000}, promote=True)   # its numbers pass now: due
        self.assertEqual(self.con.execute("SELECT next_ts, via FROM mkt WHERE token=?", (tok,)).fetchone(),
                         (now, "gt,migracija"))
        self.con.execute("UPDATE mkt SET next_ts=?, checked_ts=? WHERE token=?", (now + D, now - 600, tok))
        market.add(self.con, tok, "skener", now, promote=True)               # checked 10 min ago: not before 30 min
        self.assertEqual(self.con.execute("SELECT next_ts FROM mkt WHERE token=?", (tok,)).fetchone()[0], now + D)
        self.con.execute("UPDATE mkt SET watched=1, next_ts=?, checked_ts=NULL WHERE token=?", (now + 99, tok))
        market.add(self.con, tok, "gt", now, promote=True)                   # a watched token is not touched
        self.assertEqual(self.con.execute("SELECT next_ts FROM mkt WHERE token=?", (tok,)).fetchone()[0], now + 99)

    def test_a_gt_pool_that_passes_is_admitted_although_it_was_put_aside(self):
        now = 1_794_355_200 + 12 * 3600
        tok = "G" * 43 + "pump"
        market.add(self.con, tok, "migracija", now - 2 * D, due=now - 2 * D)
        self.con.execute("UPDATE mkt SET next_ts=?, checked_ts=? WHERE token=?", (now + 20 * 3600, now - 4 * 3600, tok))
        pool = {"attributes": {"base_token_price_usd": "0.0001", "fdv_usd": "100000", "reserve_in_usd": "40000",
                               "volume_usd": {"h1": "9000"}, "pool_created_at": "2026-11-10T00:00:00Z",
                               "name": "GGG / SOL"},
                "relationships": {"base_token": {"data": {"id": f"solana_{tok}"}}, "dex": {"data": {"id": "pumpswap"}}}}

        class N(Net):
            def gt_pools(self, n_req=None):
                return [pool]
        net = N({tok: pair(tok, px=1e-4, mc=100_000, liq=40_000, vol_h1=9_000, created=now - 4 * D)})
        logs = []
        out = market.pass_once(self.con, now, net, logs.append, pulse=set(), event_on=False)
        self.assertIn(tok, out["tokens"])                                    # 11.11.: it waited 20 h more
        self.assertEqual(out["stats"]["admitted"], 1)
        self.assertTrue(any("prolazi filter 1" in x for x in logs), logs)

    def test_the_gt_round_asks_the_pumpswap_pages_inside_the_day_cap(self):
        from event_calendar import http
        asked = []
        with mock.patch.object(http, "reserved_by_other", lambda url: 0), \
                mock.patch.object(http, "get_json", lambda url, params=None, **k: asked.append((url, params)) or
                                  {"data": []}):
            market.Net().gt_pools()
        dex = [p for u, p in asked if u.endswith(f"/dexes/{market.GT_DEX}/pools")]
        self.assertEqual(market.GT_DEX, "pumpswap")
        self.assertEqual([p["page"] for p in dex], list(range(1, market.GT_DEX_PAGES + 1)))
        self.assertTrue(all(p["sort"] == "h24_volume_usd_desc" for p in dex))
        self.assertEqual(len(asked), market.gt_requests())                  # 4 trending + 6 top + 5 PumpSwap = 15
        self.assertEqual(market.gt_requests(), 15)
        self.assertLessEqual(market.gt_requests() * 86400 // market.GT_EVERY_S, market.GT_DAY)   # 180 <= 200

    def test_the_dexscreener_lists_add_takeovers_and_profile_updates(self):
        from dexscreener import client
        calls = []

        def fn(name):
            return lambda: calls.append(name) or [{"chainId": "solana", "tokenAddress": f"{name}{'x' * 30}"}]
        with mock.patch.multiple(client, latest_token_profiles=fn("p"), latest_boosts=fn("b"), top_boosts=fn("t"),
                                 community_takeovers=fn("cto"), recent_profile_updates=fn("upd")):
            got = market.Net().lists()
        self.assertEqual(calls, ["p", "b", "t", "cto", "upd"])
        self.assertEqual(len(got), market.N_LISTS)
        now = 1_794_400_000
        market.discover_lists(self.con, now, type("L", (), {"lists": lambda s: got, "gt_pools": lambda s, n=None: []})(),
                              print)
        self.assertEqual(data.day_used(self.con, "mkt_lists_day", now), 5)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM mkt WHERE via='dex_liste'").fetchone()[0], 5)

    def test_the_free_sources_hype_scan_calls_and_former_ranges(self):
        now = 1_794_400_000
        hp = os.environ["RANGE_HYPE_DB"]
        hc = sqlite3.connect(hp)
        hc.execute("CREATE TABLE token_pulse (token TEXT, ts INTEGER, price REAL, mcap REAL, liquidity REAL, vol_m5 REAL, "
                   "vol_h1 REAL, buys_m5 INTEGER, sells_m5 INTEGER, buys_h1 INTEGER, sells_h1 INTEGER)")
        for tok, mc, liq, v1 in (("H1" + "x" * 40, 120_000, 30_000, 8_000), ("H2" + "x" * 40, 25_000, 30_000, 9_000),
                                 ("H3" + "x" * 40, 120_000, 9_000, 9_000)):
            hc.execute("INSERT INTO token_pulse VALUES (?,?,?,?,?,?,?,?,?,?,?)", (tok, now - 600, 1e-4, mc, liq, 1, v1,
                                                                               1, 1, 1, 1))
        hc.commit()
        hc.close()
        kp = os.path.join(self.tmp.name, "kol.db")
        kc = sqlite3.connect(kp)
        kc.execute("CREATE TABLE calls (token TEXT, symbol TEXT, ts INTEGER, mcap0 REAL)")
        kc.executemany("INSERT INTO calls VALUES (?,?,?,?)", [("C1" + "x" * 40, "C1", now - 3 * D, 80_000),
                                                             ("C1" + "x" * 40, "C1", now - 2 * D, 90_000),
                                                             ("C2" + "x" * 40, "C2", now - 8 * D, 80_000),
                                                             ("C3" + "x" * 40, "C3", now - D, 12_000)])
        kc.commit()
        kc.close()
        data.event(self.con, "R1" + "x" * 40, "aktivan", "raspon 50,000-90,000, ocjena 0.80", now - 2 * D)
        data.event(self.con, "R2" + "x" * 40, "isključen", "dva niža dna", now - D)
        from kol import store as kstore
        with mock.patch.object(kstore, "DB", kp):
            self.assertEqual(market.from_pulse(self.con, now, hp), 1)            # only H1 passes 30k / 15k / 5k
            self.assertEqual(market.from_calls(self.con, now), 1)                # C1 (7 days, MC 30k+); not C2, C3
            self.assertEqual(market.from_calls(self.con, now + 60), 0)           # the watermark: once
            self.assertEqual(market.from_ranged(self.con, now), 1)               # R1 had an active range
        vias = dict(self.con.execute("SELECT token, via FROM mkt"))
        self.assertEqual(vias, {"H1" + "x" * 40: "hype", "C1" + "x" * 40: "pozivi", "R1" + "x" * 40: "raspon"})
        self.assertEqual(self.con.execute("SELECT next_ts FROM mkt WHERE token=?", ("R1" + "x" * 40,)).fetchone()[0], now)

    def test_the_free_sources_are_read_every_10_minutes(self):
        n = []
        with mock.patch.object(market, "from_pulse", lambda con, now, hype_db=None: n.append(1) or 0), \
                mock.patch.object(market, "from_calls", lambda con, now: 0), \
                mock.patch.object(market, "from_ranged", lambda con, now: 0):
            for dt in (0, 60, 599, 600):
                market.pass_once(self.con, 1_794_400_000 + dt, Net(), lambda *_: None, pulse=set(), event_on=False)
        self.assertEqual(len(n), 2)


# ---------------------------------------------------------------------------------------------------------------
class Survivor(unittest.TestCase):
    """Point 2: survived the crash (>= 24 h old, MC at most -45 % from 24 h ago) and back in an active range."""

    def setUp(self):
        self.cs = tri(T0, hours=30)
        self.now = self.cs[-1][0]
        self.res = {"active": True, "status": "aktivan", "metrics": {"price": self.cs[-1][4]}, "flip": {"state": "normal"}}

    def test_a_survivor(self):
        s = survivor.check(self.cs, self.now, self.res, age_h=72.0, ch_h24=-20.0)
        self.assertTrue(s["ok"], s)
        self.assertFalse(s["crashed"])
        self.assertEqual((s["loss_24h"], s["ref_from"]), (-0.2, "dexscreener 24 h"))
        self.assertTrue(s["why"].startswith("preživio pad: star 3,0 d, MC −20 % od prije 24 h"), s["why"])

    def test_too_young_crashed_and_not_in_range(self):
        young = survivor.check(self.cs, self.now, self.res, age_h=10.0, ch_h24=-5.0)
        self.assertFalse(young["ok"])
        self.assertIn("premlad za pad: star 10 h", young["why"])
        crash = survivor.check(self.cs, self.now, self.res, age_h=72.0, ch_h24=-60.0)
        self.assertFalse(crash["ok"])
        self.assertTrue(crash["crashed"])
        self.assertIn("nije preživio pad: MC −60 % od prije 24 h (granica −45 %)", crash["why"])
        broken = survivor.check(self.cs, self.now, {**self.res, "active": False, "status": "probijen dolje",
                                                    "why": "cijena ispod range_low_low × 0,92"}, age_h=72.0, ch_h24=-10.0)
        self.assertFalse(broken["ok"])
        self.assertIn("nije u rasponu (cijena ispod range_low_low", broken["why"])
        paused = survivor.check(self.cs, self.now, {**self.res, "flip": {"state": "paused"}}, age_h=72.0, ch_h24=-10.0)
        self.assertIn("u pauzi nakon proboja dolje", paused["why"])

    def test_the_series_gives_the_level_and_the_age_when_dexscreener_does_not(self):
        s = survivor.check(self.cs, self.now, self.res)                  # 30 h of candles, age unknown
        self.assertTrue(s["ok"], s)
        self.assertEqual(s["ref_from"], "serija 24 h")
        ref = [c for c in self.cs if c[0] <= self.now - 24 * 3600][-1][4]
        self.assertAlmostEqual(s["loss_24h"], round(self.cs[-1][4] / ref - 1, 4))
        short = survivor.check(self.cs[-600:], self.now, self.res)         # 10 h of data, age unknown
        self.assertFalse(short["ok"])
        self.assertIn("starost nepoznata, podaci tek 10 h", short["why"])

    def test_run_range_keeps_it_on_the_range_with_dexscreeners_24_h_change(self):
        import run_range
        d = tempfile.mkdtemp()
        con = data.connect(os.path.join(d, "range.db"))
        market.ensure(con)
        tok = "S" * 43 + "pump"
        s = data.snap_of(dict(pair(tok, created=self.now - 5 * D), priceChange={"m5": 1.0, "h24": -30.0}), self.now)
        self.assertEqual((s["ch_h24"], s["created_ts"]), (-30.0, self.now - 5 * D))
        data.save_snap(con, tok, s)
        self.assertEqual(data.snap_ext(con, tok), {"ts": self.now, "ch_h24": -30.0, "created_ts": self.now - 5 * D})
        sv = run_range._survivor_of(con, tok, self.cs, self.now, self.res)
        self.assertTrue(sv["ok"], sv)
        self.assertEqual((sv["age_h"], sv["loss_24h"]), (120.0, -0.3))
        con.close()


class SurvivorJob(TradeBase):
    """run_range.once keeps the survivor on every computed range and counts them in its pass line."""

    def test_the_pass_line_and_the_range_json(self):
        import run_range
        from tests.test_range_market_offline import snaps
        now = self.now - self.now % 60
        tok = "V" * 43 + "pump"
        con = data.connect()
        market.ensure(con)
        for s in snaps(now, hours=30):
            data.save_snap(con, tok, dict(s, pool="Pool" + tok[:8], dex="pumpswap", symbol="VVV"))
        con.execute("INSERT INTO mkt (token, via, src, first_seen, next_ts, watched, last_snap, vol_h1, created_ts) "
                    "VALUES (?,?,?,?,?,1,?,?,?)", (tok, "gt_dex", "market", now - 2 * D, now, now, 60_000.0, now - 3 * D))
        con.commit()
        con.close()
        self.mode("shadow", "range_market")
        last = snaps(now, hours=30)[-1]
        p = pair(tok, px=last["price"], mc=last["mcap"], liq=50_000, created=now - 3 * D)
        with mock.patch.object(market, "_meter", lambda *a, **k: None):
            out = run_range.once(now=now, log=lambda *_: None, fetch=lambda toks: [], gt_fetch=lambda *a: None,
                                 post=lambda *a: {}, net=Net({tok: p}))
        self.assertIn("preživjeli pad u rasponu 1", out)
        con = data.connect()
        r = data.load_range(con, tok)[0]
        con.close()
        self.assertEqual(r["status"], "aktivan", r.get("why"))
        self.assertTrue(r["survivor"]["ok"], r["survivor"])
        self.assertEqual(r["survivor"]["age_h"], 72.0)                       # the market list's pool creation


# ---------------------------------------------------------------------------------------------------------------
class Entry(unittest.TestCase):
    """Point 3: the demo profile's entry thresholds vs today's RULES."""

    def rng(self, score=0.8, pos=2.0, sv=SURV, **m):
        z = {"range_low_low": 51.0, "range_low_top": 53.0, "range_high_low": 95.0, "range_high_top": 100.0}
        mm = {"ch_5m": 0.01, "buy_share_5m": 0.6, "vol_ratio": 0.8}
        mm.update(m)
        return {"active": True, "status": "aktivan", "score": score, "pos_pct": pos, "zones": z, "metrics": mm,
                "survivor": sv}

    def test_the_numbers(self):
        self.assertEqual({k: rules.DEMO[k] for k in ("score_min", "entry_bottom", "ch5_min", "vol_ratio_min",
                                                      "buy_share_min")},
                         {"score_min": 0.6, "entry_bottom": 0.25, "ch5_min": -0.05, "vol_ratio_min": 0.35,
                          "buy_share_min": 0.45})
        self.assertEqual(rules.RULES["score_min"], 0.7)                     # the real account's rules unchanged
        self.assertEqual(rules.RULES["entry_bottom"], 0.15)

    def test_what_the_demo_takes_and_today_does_not(self):
        px_22 = 51.0 + 0.22 * 49.0                                          # 22 % up the range, above the bottom zone
        for r, px in ((self.rng(score=0.65), 52.0), (self.rng(), px_22), (self.rng(ch_5m=-0.04), 52.0),
                      (self.rng(vol_ratio=0.4), 52.0)):
            self.assertIsNone(rules.entry_check(r, px, rules.DEMO), r)
            self.assertIsNotNone(rules.entry_check(r, px), r)
        self.assertIn("ocjena raspona 0.55 ispod 0.60", rules.entry_check(self.rng(score=0.55), 52.0, rules.DEMO))
        self.assertIn("raspona", rules.entry_check(self.rng(), 51.0 + 0.30 * 49.0, rules.DEMO))   # 30 %: too high
        self.assertIn("kupnje 44%", rules.entry_check(self.rng(buy_share_5m=0.44), 52.0, rules.DEMO))   # 45 % stays
        self.assertIn("pada -6.0%", rules.entry_check(self.rng(ch_5m=-0.06), 52.0, rules.DEMO))
        self.assertIn("volumen 15 min je 30%", rules.entry_check(self.rng(vol_ratio=0.3), 52.0, rules.DEMO))

    def test_a_crashed_token_is_never_entered_a_young_one_may_be(self):
        crashed = {"ok": False, "crashed": True, "why": "nije preživio pad: MC −60 % od prije 24 h (granica −45 %)"}
        self.assertEqual(rules.entry_check(self.rng(sv=crashed), 52.0, rules.DEMO), crashed["why"])
        young = {"ok": False, "crashed": False, "why": "premlad za pad: star 10 h (treba 24 h)"}
        self.assertIsNone(rules.entry_check(self.rng(sv=young), 52.0, rules.DEMO))   # tried after the survivors
        self.assertIn("nepoznato", rules.entry_check(self.rng(sv=None), 52.0, rules.DEMO))
        self.assertIsNone(rules.entry_check(self.rng(sv=crashed), 52.0))     # RULES do not read it
        hard = {**rules.DEMO, "survivor": True}                              # the backtest's "required" variant
        self.assertIn("premlad", rules.entry_check(self.rng(sv=young), 52.0, hard))


# ---------------------------------------------------------------------------------------------------------------
class Exits(unittest.TestCase):
    """Point 4: TP1 half at +10 % net, the rest at +15 % net or the top zone, the stop held at -12..-25 %."""

    LV = {"rll": 51.0, "rlt": 53.0, "rhl": 95.0, "rht": 100.0, "stop_px": 43.35, "floor_px": 46.92}

    def test_the_levels_and_the_stop_clamp(self):
        rt = tcost.round_trip(10.0, 25_000.0)
        lv = rules.demo_levels(self.LV, 52.0, rt)
        self.assertAlmostEqual(lv["tp1_px"], 52.0 * 1.10 / (1 - rt))
        self.assertAlmostEqual(lv["tp2_px"], 52.0 * 1.15 / (1 - rt))
        self.assertEqual((lv["profile"], lv["be_after_tp1"], lv["tp2_range"]), ("demo", True, True))
        self.assertEqual(lv["stop_px"], 43.35)                              # -16.6 %: inside -12..-25 %
        wide = rules.demo_levels(dict(self.LV, stop_px=30.0, stop_kind="atr"), 52.0, rt)
        self.assertAlmostEqual(wide["stop_px"], 52.0 * 0.75)                 # never wider than -25 %
        self.assertEqual(wide["stop_kind"], "atr_clamp")
        near = rules.demo_levels(dict(self.LV, stop_px=50.0, stop_kind="atr"), 52.0, rt)
        self.assertAlmostEqual(near["stop_px"], 52.0 * 0.88)                 # never closer than -12 %
        self.assertAlmostEqual(near["floor_px"], max(46.92, 52.0 * 0.88))
        # the stop tightens with a newer range, but never past -12 % from the entry; the TP prices stay the entry's
        fresh = dict(self.LV, stop_px=49.0, rhl=90.0)
        f = rules.levels_in_force(near, fresh)
        self.assertAlmostEqual(f["stop_px"], 52.0 * 0.88)
        self.assertEqual((f["tp1_px"], f["tp2_px"], f["rhl"]), (near["tp1_px"], near["tp2_px"], 90.0))
        self.assertIsNone(rules.profile_cfg(self.LV))
        self.assertIs(rules.profile_cfg(near), rules.DEMO)

    def test_exit_steps(self):
        lv = rules.demo_levels(dict(self.LV, rhl=58.0), 52.0, 0.02)          # a narrow range: the top zone under +15 %
        st = {}
        be = 53.1
        self.assertIsNone(rules.exit_step(lv, st, 57.0, 1000, 0, be, cfg=rules.DEMO))
        self.assertEqual(rules.exit_step(lv, st, lv["tp1_px"], 1001, 0, be, cfg=rules.DEMO), ("tp1", 0.5))
        self.assertEqual(rules.tp2_of(lv), lv["tp2_px"])                     # +15 % net is higher than 58
        self.assertIsNone(rules.exit_step(lv, st, 59.0, 1002, 0, be, cfg=rules.DEMO))
        self.assertEqual(rules.exit_step(lv, st, lv["tp2_px"], 1003, 0, be, cfg=rules.DEMO), ("tp2", 1.0))
        st = {}
        rules.exit_step(lv, st, lv["tp1_px"], 1001, 0, be, cfg=rules.DEMO)
        self.assertEqual(rules.exit_step(lv, st, 53.0, 1002, 0, be, cfg=rules.DEMO), ("breakeven", 1.0))
        wide = rules.demo_levels(self.LV, 52.0, 0.02)                        # top zone 95: the rest waits for it
        self.assertEqual(rules.tp2_of(wide), 95.0)
        st = {}
        rules.exit_step(wide, st, wide["tp1_px"], 1001, 0, be, cfg=rules.DEMO)
        self.assertIsNone(rules.exit_step(wide, st, 80.0, 1002, 0, be, cfg=rules.DEMO))
        self.assertEqual(rules.exit_step(wide, st, 80.0 * 0.85, 1003, 0, be, cfg=rules.DEMO), ("trailing", 1.0))
        self.assertEqual(rules.exit_step(wide, {}, 43.0, 1004, 0, be, cfg=rules.DEMO), ("stop", 1.0))
        # 6 h without TP1: out at break-even or better (RULES' time stop)
        self.assertEqual(rules.exit_step(wide, {}, 53.2, 6 * 3600 + 5, 0, be, cfg=rules.DEMO), ("time", 1.0))


# ---------------------------------------------------------------------------------------------------------------
class DemoAccount(TradeBase):
    """Points 3-5 on the Autopilot's demo account: the profile, the exits and the daily counter."""

    def setUp(self):
        super().setUp()
        self.mode("paper")
        self.mode("paper", "range_demo")
        trade._BLOCKS_SEEN.clear()
        trade._CACHE.pop("demo_log", None)

    def drng(self, score=0.8, **m):
        r = self.rng(score, **m)
        r["survivor"] = dict(SURV)
        return r

    def test_the_flag(self):
        self.assertEqual(settings.FLAGS["range_demo"][0], "G32")
        self.assertEqual(settings.FLAG_DEFAULTS["range_demo"], "paper")
        self.assertIn("range_demo", settings.NEVER_LIVE)
        self.assertEqual(settings.live_refusal(self.con, "range_demo"), settings.NEVER_LIVE["range_demo"])
        self.assertIs(trade.profile(PU), rules.DEMO)
        self.assertIsNone(trade.profile(LU))                                 # the real account: RULES always
        self.mode("off", "range_demo")
        self.assertIsNone(trade.profile(PU))
        settings.put(self.con, "flag:range_demo", {"mode": "paper", "since": self.now})
        for name in settings.FLAGS:   # the profile flag alone never makes the paper account follow anybody
            if name != "range_demo":
                settings.put(self.con, f"flag:{name}", {"mode": "off", "since": self.now})
        settings._FLAG_CACHE.clear()
        self.assertFalse(settings.any_paper(self.con))
        self.assertFalse(settings.any_paper())

    def test_the_demo_enters_what_todays_rules_do_not_and_the_real_account_never(self):
        done = self.enter(rng=self.drng(score=0.65))
        self.assertEqual([u for u, _ in done], [PU])
        self.assertIn("demo 14.11.: TP1 MC $", done[0][1])
        self.assertIn("preživio pad", done[0][1])
        r = trade.rounds(self.lg)[0]
        lv = r["levels"]
        self.assertEqual((lv["profile"], lv["be_after_tp1"]), ("demo", True))
        rt = tcost.round_trip(10.0, 25_000.0)
        self.assertAlmostEqual(lv["tp1_px"], 52 * S * 1.10 / (1 - rt))
        self.assertAlmostEqual(lv["stop_px"], 51 * S * 0.85)                 # -16.6 % from 52: inside the clamp
        self.assertEqual(self.lots(LU), [])
        pos = view.positions()["open"][0]                                    # get_range_candidates' positions
        self.assertEqual(pos["profile"], "demo")
        self.assertEqual(pos["exit_levels_market_cap_usd"]["take_half_at (+10 % net)"], round(lv["tp1_px"] * 1e9))
        self.assertEqual(pos["exit_levels_market_cap_usd"]["rest_at (+15 % net or the top zone)"], 95_000)
        # range_demo off: the same range is no entry for the demo account (score 0.65 < 0.7)
        self.lg.execute("DELETE FROM range_rounds")
        self.lg.execute("DELETE FROM trades")
        self.lg.commit()
        self.mode("off", "range_demo")
        self.assertEqual(self.enter(rng=self.drng(score=0.65)), [])

    def test_no_lot_2_and_the_exits_on_the_demo_round(self):
        self.enter(px=52.0, rng=self.drng())
        self.lim["dca_token_cap"] = 0.3
        self.assertEqual(self.enter(px=46.0, rng=self.drng()), [])           # -11.5 %: no lot 2 on the demo profile
        self.assertEqual(len(self.lots(PU)), 1)
        lv = trade.rounds(self.lg)[0]["levels"]
        tp1 = lv["tp1_px"] / S
        self.assertEqual(self.exits(tp1 - 0.2), [])
        out = self.exits(tp1 + 0.1)
        self.assertIn("pola na +10 % neto (demo 14.11.)", out[0])
        self.assertEqual(len(self.lots(PU, "closed")), 1)
        out = self.exits(52.9)                                               # back to the rest's break-even
        self.assertIn("break-even stop ostatka nakon TP1", out[0])
        self.assertIn("runda gotova", out[0])
        r = trade.rounds(self.lg, "closed")[0]
        self.assertEqual(r["exit_reason"], "breakeven")
        self.assertGreater(r["pnl_usd"], 0.3)                                # half sold at +10 % net, the rest ~0
        rule = {t["note"]: t["exit_rule"] for t in self.lots(PU, "closed")}
        self.assertEqual(rule, {"range: pola na +10 % neto (demo 14.11.) (50%)": "tp",
                                "range: break-even stop ostatka nakon TP1": "sl"})

    def test_the_stop_never_closer_than_12_percent(self):
        r = self.drng()
        r["atr"] = 0.2 * S                                                   # ATR stop 50.7: -2.5 % from 52
        self.enter(px=52.0, rng=r)
        lv = trade.rounds(self.lg)[0]["levels"]
        self.assertAlmostEqual(lv["stop_px"] / S, 52 * 0.88)
        self.assertEqual(self.exits(46.0, rng=r), [])                        # -11.5 %: held
        out = self.exits(45.7, rng=r)
        self.assertIn("tvrdi stop demo (ATR, -12 do -25 % od ulaza)", out[0])

    def test_the_daily_counter_and_its_top_three(self):
        B, C, E, F = ("B" * 43 + "pump", "C" * 43 + "pump", "E" * 43 + "pump", "F" * 43 + "pump")
        rngs = {MINT: self.drng(), B: self.drng(buy_share_5m=0.40), E: self.drng(buy_share_5m=0.41),
                C: self.drng(score=0.5), F: dict(self.drng(), pos_pct=60.0)}
        for r in rngs.values():
            r["ts"] = r["mts"] = self.now
        printed = []
        with mock.patch("builtins.print", lambda *a, **k: printed.append(" ".join(map(str, a)))):
            done = trade.run_once(self.lg, self.mk(52.0), self.now, rngs, self.lim, 100.0)
            self.assertEqual([u for u, _ in done], [PU])
            d = trade.demo_today(self.lg, self.now)
            self.assertEqual((d["trades"], d["goal"], d["open"]), (1, 5, 1))
            self.assertEqual(d["top_blocks"][0], {"reason": "premalo kupnji u 5 min", "tokens": 2})
            self.assertEqual({b["reason"] for b in d["top_blocks"][1:]},
                             {"ocjena raspona ispod praga", "cijena nije u donjem dijelu raspona"})
            self.assertTrue(d["text"].startswith("range demo danas: 1 tradeova (cilj 5)"), d["text"])
            self.assertIn("najviše blokira (tokena): premalo kupnji u 5 min 2", d["text"])
            self.assertEqual([x for x in printed if x.startswith("range demo danas")], [d["text"]])
            trade.run_once(self.lg, self.mk(52.0), self.now + 20, rngs, self.lim, 100.0)
            self.assertEqual(len([x for x in printed if x.startswith("range demo danas")]), 1)   # unchanged: not again
        n = self.lg.execute("SELECT COUNT(*) FROM range_blocks").fetchone()[0]
        self.assertEqual(n, 4)                                               # one row per token, reason and day
        with mock.patch.object(data, "_league_ro", lambda: sqlite3.connect(store.DB)):
            v = view.demo_today(self.now)
        self.assertEqual(v["trades"], 1)

    def test_max_open_is_a_reason_too(self):
        self.lim["max_open"] = 1
        B = "B" * 43 + "pump"
        rngs = {MINT: self.drng(), B: self.drng(score=0.9)}
        for r in rngs.values():
            r["ts"] = r["mts"] = self.now
        trade.run_once(self.lg, self.mk(52.0), self.now, rngs, self.lim, 100.0)
        d = trade.demo_today(self.lg, self.now)
        self.assertEqual(d["trades"], 1)
        self.assertEqual(d["top_blocks"], [{"reason": "najviše otvorenih range rundi", "tokens": 1}])

    def test_block_keys(self):
        for why, key in (("ocjena raspona 0.55 ispod 0.60", "ocjena raspona ispod praga"),
                         ("cijena na 30% raspona (ulaz u donjih 25% ili u donjoj zoni) · 5-minutni podaci nisu svježi",
                          "cijena nije u donjem dijelu raspona"),
                         ("nije preživio pad: MC −60 % od prije 24 h (granica −45 %)", "nije preživio pad (> 45 %)"),
                         ("kupnje 40% transakcija u 5 min (treba 45%)", "premalo kupnji u 5 min"),
                         ("rug (pad 80 % od vrha)", "rug"), ("dnevni limit SOL-a za range ulaze", "dnevni limit SOL-a"),
                         ("nešto 12 novo (x)", "nešto novo")):
            self.assertEqual(trade.block_key(why), key)

    def test_the_real_money_gates_never_count_a_demo_round(self):
        trade.ensure(self.lg)
        for i in range(25):
            self.lg.execute("INSERT INTO range_rounds (user, token, opened_ts, closed_ts, status, cost_usd, pnl_usd, ret, "
                            "levels) VALUES (?,?,?,?, 'closed', 10, 1.0, 0.10, ?)",
                            (PU, f"T{i}", self.now - 3600, self.now - 60, json.dumps({"profile": "demo"})))
        self.lg.commit()
        self.assertEqual(gate.proof(profile="demo")["n"], 25)
        self.assertEqual(gate.proof(profile="rules")["n"], 0)
        self.assertEqual(gate.proof()["n"], 25)                              # the EV views still show every round
        gate._CACHE.update(at=0.0, path=None, val=None)
        self.assertIn("tek 0 zatvorenih paper rundi", gate.refusal())
        self.assertIn("tek 0 zatvorenih paper rundi izvora missed", gate.missed_refusal())
        from events import evreport   # the 23:30 EV report gets its own row once there are demo rounds
        rows = {r["part"]: r for r in evreport.range_source_rows(self.now, "paper", self.lg)}
        self.assertEqual((rows["range:demo"]["n"], rows["range:demo"]["ev_pct"], rows["range:demo"]["flag"]),
                         (25, 10.0, "range_demo"))
        self.assertIn("PnL +25.00 $; nikad pravi novac", rows["range:demo"]["note"])

    def test_get_range_candidates_shows_the_survivor_and_the_demo_decision(self):
        r = self.drng(score=0.65)
        r["ts"] = r["mts"] = self.now
        with mock.patch.object(data, "read_ranges", lambda *a, **k: {MINT: r}), \
                mock.patch.object(view, "demo_today", lambda now=None: {"trades": 0, "goal": 5, "text": "x"}):
            d = view.candidates(now=self.now)
        self.assertEqual(d["min_score"], 0.6)                                # the demo profile's threshold by default
        row = d["candidates"][0]
        self.assertEqual(row["survivor"]["why"], SURV["why"])
        self.assertTrue(row["entry_ready_demo"], row["entry_demo"])
        self.assertFalse(row["entry_ready"])                                 # today's rules: 0.65 < 0.7
        self.assertEqual((d["demo"]["flag_mode"], d["demo"]["entry_ready_demo"], d["demo"]["survivors_in_range"]),
                         ("paper", 1, 1))
        self.assertIn("survived the crash", d["demo"]["survivor_rule"])
        self.assertEqual(d["demo"]["today"]["goal"], 5)


# ---------------------------------------------------------------------------------------------------------------
class Backtest(unittest.TestCase):
    """Point 3 / 4: the demo profile vs today's rules on the six range fixtures (12.47 token-days; ticks wick, the
    ATR stop, the owner's round-trip cost). The other backtest numbers (tests/test_range_flip_offline,
    test_range_haobibi_offline) are unchanged: today's variants never read the profile."""

    @classmethod
    def setUpClass(cls):
        from tests.test_range_flip_offline import FIXTURES
        cls.rep = backtest.run_tokens(fx_series(FIXTURES))

    def test_old_vs_demo(self):
        v = self.rep["demo"]["variants"]
        got = {k: (x["rounds"], x["hit_rate"], x["ev_pct"], round(x["pnl_usd"], 2), round(x["max_dd_usd"], 2))
               for k, x in v.items()}
        self.assertEqual(got["old"], (12, 0.75, 14.1, 26.2, 3.03))
        self.assertEqual(got["demo"], (21, 0.714, 5.31, 16.71, 4.07))         # more rounds, EV still > 0
        self.assertGreater(got["demo"][0], got["old"][0])
        self.assertGreater(got["demo"][2], 0)
        self.assertEqual(got["demo_no_survivor"], got["demo"])                # no crashed token in the fixtures
        self.assertEqual(self.rep["variants"]["0.7"]["rounds"], 12)          # today's backtest untouched
        self.assertEqual(self.rep["demo"]["data"], {"tokens": 6, "days_total": 12.47})
        line = backtest.demo_line(self.rep["demo"])
        self.assertTrue(line.startswith("range demo backtest: 6 tokena, 12.47 dana; staro: runde 12, pogodak 75 %"),
                        line)
        self.assertIn("## Demo profil 14.11.", backtest.md(self.rep))
        reasons = v["demo"]["exit_reasons"]
        self.assertNotIn("top", reasons)                                     # the demo rounds sell by TP1 / TP2
        self.assertIn("tp2", reasons)


if __name__ == "__main__":
    unittest.main()
