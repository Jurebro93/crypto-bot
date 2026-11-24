"""11.11. (Jure: "HAOBIBI je bio jako dobar ulaz, zapiši ga kao dobitak ... zadrži ovaj token: neka bude preporuka ako
padne u raspon i volumen se drži"): the owner's learning label (league.db owner_labels, once, the booked round never
changes), the pin (trade settings range_pins: always watched, a proposal only in the lower zone while the volume
holds, never an automatic real buy), the stop variants measured on HAOBIBI's GeckoTerminal candles (the live round
replayed with its own fills, and the variants over every range fixture), the similarity to the labelled wins (shadow
P bonus only). No network.

    python3 -m unittest tests.test_range_haobibi_offline
"""
import glob
import gzip
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from proposals import build, strategies  # noqa: E402
from rangedca import backtest, data, detect, owner, stops, trade, view  # noqa: E402
from trade import settings  # noqa: E402
from tests.test_pozicije_izlaz_offline import MINT  # noqa: E402
from tests.test_range_dca_offline import S, TradeBase, tri  # noqa: E402

LU, PU = settings.LEAGUE_USER, settings.PAPER_USER
FX = os.path.join(ROOT, "tests", "fixtures")
H = owner.HAOBIBI
T1 = owner.HAOBIBI_TS            # 09:50 UTC, lot 1
T_STOP = T1 + 54 * 60            # 10:44 UTC


def load(name):
    with gzip.open(os.path.join(FX, name), "rt") as f:
        fx = json.load(f)
    return fx, data.merge([tuple(r) for r in fx["candles"]], [])


def hm(ts):
    return time.strftime("%H:%M", time.gmtime(ts))


# ---------------------------------------------------------------------------------------------------------------
class Labels(TradeBase):
    def booked_round(self):
        trade.ensure(self.lg)
        self.lg.execute("INSERT INTO range_rounds (user, token, symbol, opened_ts, closed_ts, status, lot1_sol, "
                        "lot2_sol, entry_mc, lot2_mc, cost_usd, pnl_usd, ret, exit_reason) VALUES "
                        "(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (PU, H, "HAOBIBI", T1, T_STOP, "closed", 0.15, 0.15, 112_828,
                                                          96_210, 25.15, -4.26, -0.1694, "stop"))
        self.lg.commit()
        return self.lg.execute("SELECT id FROM range_rounds WHERE token=?", (H,)).fetchone()[0]

    def test_the_owner_order_stores_the_label_once_and_the_booked_round_stays_as_booked(self):
        rid = self.booked_round()
        before = [tuple(r) for r in self.lg.execute("SELECT * FROM range_rounds ORDER BY id")]
        done = owner.owner_once(self.con, self.lg, now=self.now)
        self.assertTrue(any("oznaka HAOBIBI" in t for t in done), done)
        self.assertEqual(owner.owner_once(self.con, self.lg, now=self.now + 60), [])      # once: its marker
        self.assertIsNone(owner.add_label(self.lg, H, T1, "win", "missed_win_stop_too_early"))   # and one row anyway
        lbs = owner.labels()
        self.assertEqual(len(lbs), 1)
        lb = lbs[0]
        self.assertEqual((lb["token"], lb["symbol"], lb["label"], lb["kind"], lb["strategy"]),
                         (H, "HAOBIBI", "win", "missed_win_stop_too_early", "range"))
        self.assertEqual((lb["round_id"], lb["booked_pnl_usd"]), (rid, -4.26))
        d = lb["data"]
        self.assertEqual((d["entry_mc"], d["lot2_mc"], d["stop_mc"], d["tp_mc"]), (112_828, 96_210, 88_120, 172_300))
        self.assertTrue(d["tp_reached"])
        self.assertIn("ostaje −4,26 $", lb["note"])
        # the booked result never changes: the round row is exactly as before
        self.assertEqual([tuple(r) for r in self.lg.execute("SELECT * FROM range_rounds ORDER BY id")], before)
        raw = settings.raw(self.con)
        self.assertTrue(raw.get(owner.ONCE_LABEL_KEY) and raw.get(owner.ONCE_PIN_KEY))
        self.assertIn("knjiženo -4,26 $ ostaje", owner.label_text(lb))

    def test_the_label_in_get_range_candidates_get_proposals_the_brief_and_the_2330_report(self):
        owner.owner_once(self.con, self.lg, now=self.now)
        self.mode("paper")
        from ui import mcpapi
        d, err = mcpapi._tool("get_range_candidates", {})
        self.assertFalse(err, d)
        lv = d["owner_labels"]
        self.assertEqual([(x["token"], x["label"], x["kind"]) for x in lv], [(H, "win", "missed_win_stop_too_early")])
        self.assertEqual((lv[0]["entry_mc"], lv[0]["stop_mc"], lv[0]["booked_pnl_usd"]), (112_828, 88_120, -4.26))
        self.assertIn("knjiženi rezultat runde se ne mijenja", lv[0]["booked_note"])
        self.mode("paper", "proposals")
        from proposals import view as pview
        p = pview.mcp(now=self.now, path=os.path.join(self.tmp.name, "nema.db"))
        self.assertEqual([x["token"] for x in p["owner_labels"]], [H])
        from events import brief, evreport
        b = brief.range_part()
        self.assertEqual([x["token"] for x in b["owner_labels"]], [H])
        self.assertEqual([x["token"] for x in b["pins"]], [H])
        logs = []
        rows = evreport.owner_rows(self.now, "paper", log=logs.append)
        self.assertEqual([r["part"] for r in rows], ["range_oznake"])
        self.assertIn("HAOBIBI: oznaka vlasnika win (dobitak propušten preranim stopom)", rows[0]["note"])
        self.assertIn("knjiženo -4,26 $ ostaje", rows[0]["note"])
        self.assertTrue(logs[0].startswith("range oznake vlasnika: HAOBIBI"), logs)
        # the similarity line (the label's ts is the fixture's, fixed on 11.11.: against the real clock it is a
        # reference now; the 24 h rule itself is checked against fixed clocks below)
        self.assertTrue(logs[1].startswith("range slični"), logs)
        ws_lb = owner.labels()
        self.assertEqual(owner.wins(lbs=ws_lb, now=T1 + 3600), [])                   # 1 h old: not a reference yet
        self.assertEqual([w["token"] for w in owner.wins(lbs=ws_lb, now=T1 + 25 * 3600)], [H])   # 25 h: it is


# ---------------------------------------------------------------------------------------------------------------
class Pins(TradeBase):
    def pinned_rng(self, px=52.0, score=0.5, vol=None, **m):
        r = self.rng(score=score, price=px * S, mcap=px * 1000, **m)
        r["pos_pct"] = round((px - 51) / (100 - 51) * 100, 1)
        r["pin_vol"] = vol or {"vol_h1": 30_000, "vol_h1_med6": 40_000, "holds": True, "why": None}
        return r

    def test_the_owner_order_pins_haobibi_once_and_only_the_owner_removes_the_pin(self):
        owner.owner_once(self.con, self.lg, now=self.now)
        p = owner.pins(fresh=True)[H]
        self.assertEqual(p["zones_mc"]["range_low_low"], 102_894)
        from ui import pravitrade
        self.assertIn("err=", pravitrade.post("/pravi-trade/rangepin", {"token": H, "action": "remove"}, "netko"))
        self.assertIn(H, owner.pins(fresh=True))
        self.assertIn("ok=", self.post("/pravi-trade/rangepin", {"token": H, "action": "remove"}))
        self.assertNotIn(H, owner.pins(fresh=True))
        self.assertEqual(owner.owner_once(self.con, self.lg, now=self.now + 60), [])     # removed stays removed
        self.assertNotIn(H, owner.pins(fresh=True))
        self.assertIn("ok=", self.post("/pravi-trade/rangepin", {"token": MINT, "symbol": "RNG"}))
        self.assertEqual(list(owner.pins(fresh=True)), [MINT])
        self.assertIn("err=", self.post("/pravi-trade/rangepin", {"token": "nije-adresa"}))

    def test_a_pinned_token_is_always_in_the_signal_pass_never_capped_out(self):
        con = data.connect()
        for i in range(45):   # 45 better ranges seen in the last 2 h: the 40-token cap is full without the pin
            data.save_range(con, f"Tok{i:02d}" + "x" * 37, {"ts": self.now - 60, "status": "aktivan", "active": True,
                                                              "score": 0.9, "metrics": {}, "pos_pct": 10.0}, {})
        con.commit()
        self.assertNotIn(MINT, data.candidates(con, self.now))
        owner.pin(self.con, MINT, "Jure", "RNG")
        import run_range
        self.assertEqual(run_range._pins(), (MINT,))
        got = data.candidates(con, self.now, run_range._pins())
        self.assertEqual((got[0], len(got)), (MINT, data.MAX_TOKENS))
        con.close()

    def test_run_range_watches_the_pin_and_keeps_its_volume_rule(self):
        self.mode("paper")
        owner.pin(self.con, MINT, "Jure", "RNG")
        import run_range
        asked = []

        def fetch(toks):
            asked.append(list(toks))
            last = tri(self.now - 12 * 3600 + 60 - self.now % 60, hours=12)[-1]
            return [{"baseToken": {"address": MINT, "symbol": "RNG"}, "priceUsd": str(last[4]), "marketCap": last[4] * 1e9,
                     "dexId": "pumpswap", "pairAddress": "Pool" + MINT[:8], "liquidity": {"usd": 25_000},
                     "volume": {"m5": 5000, "h1": 60_000, "h6": 360_000},
                     "txns": {"m5": {"buys": 6, "sells": 4}, "h1": {"buys": 60, "sells": 40}}, "priceChange": {"m5": 1.0}}]
        run_range.once(now=self.now, log=lambda *a: None, fetch=fetch,
                       gt_fetch=lambda pool, s, e: [c[:6] for c in tri(e - 12 * 3600 + 60, hours=12)], post=lambda *a: {})
        self.assertEqual(asked[0][0], MINT)                                   # nobody named it: the pin did
        con = data.connect()
        r, _st = data.load_range(con, MINT)
        con.close()
        self.assertTrue(r["pinned"])
        self.assertEqual(r["pin_vol"]["vol_h1"], 60_000)                      # the fresh snapshot's hour
        self.assertTrue(r["pin_vol"]["holds"])
        from ui import mcpapi
        d, _err = mcpapi._tool("get_range_candidates", {"min_score": 0.99})   # above its score: listed anyway
        row = next(x for x in d["candidates"] + d["breakouts"] if x["token"] == MINT)
        self.assertTrue(row["pinned"])
        self.assertEqual([x["token"] for x in d["pins"]], [MINT])

    def test_volume_holds_only_at_half_the_6_h_median_and_10k(self):
        now = T1

        def cs(hourly):   # one candle per hour bucket with that hour's volume
            return [(now - 3600 * k - 600, 1.0, 1.0, 1.0, 1.0, v, None, None) for k, v in enumerate(hourly)]
        self.assertTrue(owner.vol_hold(cs([20_000] + [30_000] * 5), now)["holds"])
        v = owner.vol_hold(cs([12_000] + [30_000] * 5), now)                  # 12k < 50 % of 30k
        self.assertEqual((v["holds"], v["vol_h1_med6"]), (False, 30_000))
        self.assertIn("50 % medijana", v["why"])
        v = owner.vol_hold(cs([8_000] + [9_000] * 5), now)                    # >= half of the median, under $10k
        self.assertFalse(v["holds"])
        self.assertIn("ispod $10k", v["why"])
        snap = {"ts": now - 30, "vol_h1": 25_000}
        self.assertTrue(owner.vol_hold(cs([1_000] + [30_000] * 5), now, snap)["holds"])   # the fresh snapshot's hour

    def test_a_proposal_only_in_the_lower_zone_and_while_the_volume_holds(self):
        pin = {"symbol": "RNG", "ts": self.now, "zones_mc": None}
        r = self.pinned_rng()                                     # score 0.5: the normal range rules never take it
        row = view.one(MINT, r, self.now, pin, [])
        self.assertEqual((row["pinned"], row["entry_ready"], row["pin_ready"]), (True, False, True))
        self.assertIsNone(strategies.range_ready(row))
        self.assertIn("ocjena raspona 0.5 ispod 0.7", row["pin"]["notes"])
        self.assertIsNotNone(strategies.range_ready(view.one(MINT, r, self.now, None, [])))   # not pinned: no
        up = view.one(MINT, self.pinned_rng(px=70.0), self.now, pin, [])         # 39 % of the range: waits
        self.assertFalse(up["pin_ready"])
        self.assertIn("donjoj zoni", strategies.range_ready(up))
        low = view.one(MINT, self.pinned_rng(px=46.0), self.now, pin, [])        # under range_low_low x 0.92
        self.assertFalse(low["pin_ready"])
        weak = view.one(MINT, self.pinned_rng(vol={"vol_h1": 12_000, "vol_h1_med6": 30_000, "holds": False,
                                                   "why": "volumen 1 h $12,000 ispod 50 % medijana 6 h ($30,000)"}),
                        self.now, pin, [])
        self.assertFalse(weak["pin_ready"])
        self.assertIn("medijana 6 h", strategies.range_ready(weak))
        stale = self.pinned_rng()
        stale["mts"] = self.now - 600
        self.assertFalse(view.one(MINT, stale, self.now, pin, [])["pin_ready"])
        # a range without a pair of zones now: the zones the owner pinned it with
        nz = self.pinned_rng()
        nz.update(status="nema raspona", active=False, zones=None)
        pz = {"symbol": "RNG", "ts": self.now, "zones_mc": {"range_low_low": 51_000, "range_low_top": 53_000,
                                                            "range_high_low": 95_000, "range_high_top": 100_000}}
        row2 = view.one(MINT, nz, self.now, pz, [])
        self.assertTrue(row2["pin_ready"])
        self.assertEqual((row2["zones"]["from"], row2["zones"]["market_cap_usd"]["range_high_low"]), ("pin", 95_000))

    def test_the_proposal_goes_through_the_normal_range_strategy_with_the_hard_blocks(self):
        from tests.test_kandidati_offline import NOW, live
        from tests.test_prijedlozi_offline import PSources
        pin = {"symbol": "RNG", "ts": NOW, "zones_mc": None}
        r = self.pinned_rng()
        r["ts"] = r["mts"] = NOW
        Sx = PSources()
        Sx.rc = [view.one(MINT, r, NOW, pin, [])]
        Sx.rrec = {"n": 40, "wins": 34}
        Sx.mk[MINT] = live(mcap=52_000, liq=40_000)
        rows, near, _m = build.build(NOW, Sx)
        got = {x["token"]: x for x in rows}
        self.assertIn(MINT, got, near)
        p = got[MINT]
        self.assertEqual((p["strategy"], p["pinned"], p["pin_only"]), ("range", True, True))
        self.assertEqual(p["exits_mcap"]["sl"], round(51_000 * 0.85))
        self.assertIn("Vlasnikov pin", p["why"])
        self.assertTrue(any("nikad automatska kupnja pravim novcem" in x for x in p["risks"]))
        Sx.mk[MINT] = live(mcap=52_000, liq=14_000)                           # rule B: under $15k liquidity blocks
        rows, near, _m = build.build(NOW, Sx)
        self.assertNotIn(MINT, {x["token"] for x in rows})
        self.assertIn("liq", [b["key"] for n in near if n["token"] == MINT for b in n["blocks"]])
        Sx.mk[MINT] = live(mcap=70_000, liq=40_000)
        Sx.rc = [view.one(MINT, self.pinned_rng(px=70.0), NOW, pin, [])]      # out of the lower zone: no proposal
        Sx.rc[0]["computed_ts"] = NOW
        self.assertNotIn(MINT, {x["token"] for x in build.build(NOW, Sx)[0]})

    def test_the_pin_itself_buys_nothing(self):
        self.mode("paper")
        owner.pin(self.con, MINT, "Jure", "RNG")
        r = self.pinned_rng()
        r["ts"] = r["mts"] = self.now
        self.assertEqual(trade.run_once(self.lg, self.mk(52.0), self.now, {MINT: r}, self.lim, 100.0), [])
        self.assertEqual(self.lots(PU) + self.lots(LU), [])


# ---------------------------------------------------------------------------------------------------------------
class StopVariants(unittest.TestCase):
    """HAOBIBI 11.11. on GeckoTerminal's minute candles (tests/fixtures/range_haobibi_20261111.json.gz)."""

    @classmethod
    def setUpClass(cls):
        cls.fx, cls.cs = load("range_haobibi_20261111.json.gz")
        cls.tab = stops.replay_table(cls.cs, 1e9)

    def test_the_fixture_and_why_the_stop_hit(self):
        self.assertEqual((self.fx["token"], self.fx["symbol"], len(self.cs)), (H, "HAOBIBI", 501))
        self.assertEqual((hm(self.cs[0][0]), hm(self.cs[-1][0])), ("02:41", "11:01"))   # the pool exists since 02:41
        c = next(x for x in self.cs if x[0] == T_STOP)
        # the stop minute: GeckoTerminal's low 88,865 (the live feed printed the stop, 88,120), it closed at 124,563
        self.assertEqual((round(c[3] * 1e9), round(c[4] * 1e9)), (88_865, 124_563))
        b5 = {b[0]: b for b in detect.bars(self.cs, 300, self.cs[-1][0])}
        self.assertEqual(round(b5[T_STOP - 4 * 60 - 300][4] * 1e9), 96_449)   # 5-minute closes around the stop
        self.assertEqual(round(b5[T_STOP - 4 * 60][4] * 1e9), 124_563)
        g5 = {r[0]: r for r in self.fx["candles_5m"]}                          # GeckoTerminal's own 5-minute candles agree
        self.assertEqual(round(g5[T_STOP - 4 * 60][4] * 1e9), 124_563)
        hi = max(x[2] for x in self.cs if x[0] > T_STOP)
        self.assertEqual(round(hi * 1e9), owner.HAOBIBI_LABEL["data"]["peak_mc"])
        tp = next(x[0] for x in self.cs if x[0] > T_STOP and x[2] * 1e9 >= 172_300)
        self.assertEqual(tp, owner.HAOBIBI_LABEL["data"]["tp_reached_ts"])

    def test_the_live_round_replayed_per_variant(self):
        v = self.tab["variants"]
        got = {k: (r["stop_mc"], r["stop_hit"], r["round_pnl_usd"], r["pnl_usd"], r["mae_pct"]) for k, r in v.items()}
        self.assertEqual(got["a"], (88_120, True, -4.393, -4.393, -15.7))     # booked -4.26 $ (league fees)
        self.assertEqual((v["a"]["stop_ts"], v["a"]["stop_fill_mc"]), (T_STOP, 88_120))
        self.assertEqual(got["b"], (82_936, False, 14.645, 14.645, -15.7))    # ATR 29k: clamped at 20 % under rll
        self.assertEqual(v["b"]["atr_mc"], 29_012)
        self.assertEqual(got["c"], (88_120, False, 14.645, 14.645, -15.7))    # no 5-minute close under 88,120
        self.assertEqual(got["d"], got["b"])
        self.assertEqual(got["e"], (88_120, True, -4.393, -2.423, -15.7))
        rc = v["e"]["reclaim"]
        self.assertEqual((rc["ts"], rc["mc"], rc["pnl_usd"]), (T_STOP + 120, 141_515, 1.97))   # 10:46, buys 71 %
        self.assertGreaterEqual(rc["buy_share_5m"], 0.6)
        self.assertEqual(got["be"], got["b"])
        self.assertIsNone(v["be"]["reclaim"])                                  # no stop, no reclaim
        self.assertEqual([(hm(t), why, m) for t, why, _f, m in v["c"]["exits"]],
                         [("10:55", "tp1", 172_300), ("10:57", "trailing", 161_182)])
        line = stops.replay_line(self.tab)
        self.assertTrue(line.startswith("range stop replay HAOBIBI (živa runda, knjiženo -4.26 $ ostaje): a: stop 88,120 "
                                        "POGOĐEN 10:44 UTC"), line)

    def test_every_variant_over_every_range_fixture(self):
        series = {}
        for f in sorted(glob.glob(os.path.join(FX, "range_*_20261111.json.gz"))):
            fx, cs = load(os.path.basename(f))
            series[fx["token"]] = (cs, fx["supply"], None, fx.get("symbol"))
        self.assertEqual(len(series), 6)
        rep = backtest.run_tokens(series)
        sr = rep["stops"]
        got = {k: (x["rounds"], round(x["pnl_usd"], 2), round(x["max_dd_usd"], 2), x["false_entries"], x["reclaims"])
               for k, x in sr["variants"].items()}
        self.assertEqual(got, {"a": (13, 24.0, 4.77, 2, 0), "b": (12, 26.2, 3.03, 2, 0), "c": (12, 24.77, 3.9, 2, 0),   # 13.11.: entry buy share 0.45
                               "d": (12, 24.77, 3.9, 2, 0), "e": (14, 26.48, 4.77, 2, 1), "be": (13, 28.68, 3.03, 2, 1)})
        h = sr["tokens"][H]
        self.assertEqual({k: round(h[k]["pnl_usd"], 2) for k in stops.VARIANTS},
                         {"a": 0.77, "b": 2.95, "c": 2.39, "d": 2.39, "e": 3.25, "be": 5.43})
        self.assertEqual([r["reason"] for r in h["rounds_a"]], ["top", "stop", "odustajanje"])
        self.assertTrue(h["rounds_e"][-1]["reclaim"])
        line = stops.line(sr, focus=[H])
        self.assertTrue(line.startswith("range stop varijante: 6 tokena, 12.47 dana; a (danas"), line)
        self.assertIn("HAOBIBI: a +0.77 $", line)
        self.assertIn("## Stop varijante", backtest.md(rep))
        # today's backtest (body path) is untouched by the variants: the flip comparison's old rules
        self.assertEqual(rep["variants"]["0.7"]["rounds"], 12)

    def test_the_nightly_run_keeps_the_labelled_token_from_its_fixture(self):
        d = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"RANGE_DB": os.path.join(d, "range.db"), "RANGE_HYPE_DB": os.path.join(d, "h.db")}), \
                mock.patch.object(data, "ROOT", d), mock.patch.object(backtest, "tokens_with_data", lambda *a, **k: []), \
                mock.patch.object(owner, "labels", lambda *a, **k: [{"token": H}]), \
                mock.patch.object(owner, "pin_tokens", lambda *a, **k: []):
            logs = []
            rep = backtest.run_server(now=self.cs[-1][0] + 60, log=logs.append)
            self.assertEqual(rep["tokens_simulated"], 1)
            self.assertTrue(any(x.startswith("range stop varijante: 1 tokena") for x in logs), logs[-4:])
            self.assertTrue(any(x.startswith("range stop replay HAOBIBI") for x in logs), logs[-4:])
            con = data.connect()
            kv = data.kv_get(con, "stop_backtest")
            con.close()
            self.assertEqual(kv["a"]["rounds"], 3)


# ---------------------------------------------------------------------------------------------------------------
class Similar(unittest.TestCase):
    def test_the_measure(self):
        f = owner.HAOBIBI_LABEL["data"]["features"]
        self.assertEqual(owner.similarity(f, f), 1.0)
        g = dict(f, pos_pct=f["pos_pct"] + 15.0)                     # one feature one typical spread off
        self.assertAlmostEqual(owner.similarity(f, g), round(2.718281828 ** (-1 / 9 / 2), 4), places=3)
        self.assertIsNone(owner.similarity({"ratio": 1.5, "range_score": 0.8}, f))   # fewer than 5 features known

    def test_the_label_features_come_from_the_fixture(self):
        _fx, cs = load("range_haobibi_20261111.json.gz")
        t = T1 + 26 * 60   # 10:16 UTC: the same bottom zone as the live lot 1
        r = detect.analyze([c for c in cs if c[0] <= t], t, None, {"supply": 1e9, "unknown_liq_ok": True})
        f = owner.features(r)
        lf = owner.HAOBIBI_LABEL["data"]["features"]
        self.assertAlmostEqual(f["ratio"], lf["ratio"], places=3)
        self.assertEqual(f["bottom_touches"], lf["bottom_touches"])
        self.assertAlmostEqual(f["buy_share_5m"], lf["buy_share_5m"], places=2)
        self.assertAlmostEqual(f["pos_pct"], lf["pos_pct"], delta=0.5)
        self.assertGreaterEqual(owner.similarity(f, lf), 0.8)          # its own setup scores high

    def test_ranking_of_the_range_fixtures_against_haobibi(self):
        ws = [{"token": H, "symbol": "HAOBIBI", "features": owner.HAOBIBI_LABEL["data"]["features"]}]
        rows = []
        for f in sorted(glob.glob(os.path.join(FX, "range_*_20261111.json.gz"))):
            fx, cs = load(os.path.basename(f))
            if fx["token"] == H:
                continue
            best = None   # the most similar moment of each token: an active range with the price in its lower 40 %
            for _t, r, _st in backtest.timeline(cs, fx["supply"], None):
                if r.get("active") and r.get("pos_pct") is not None and r["pos_pct"] <= 40:
                    s = owner.similarity(owner.features(r), ws[0]["features"])
                    if s is not None and (best is None or s > best[0]):
                        best = (s, owner.features(r))
            rows.append({"token": fx["token"], "symbol": fx["symbol"], "features": best[1]})
        rank = owner.ranking(rows, ws)
        self.assertEqual([(x["symbol"], round(x["score"], 2)) for x in rank],
                         [("timmy", 0.88), ("HOPE", 0.68), ("PIRATE", 0.66), ("Leonida", 0.52), ("WEALTH", 0.42)])
        self.assertEqual(owner.similar_line(rank, ws).split(";")[0],
                         "range slični (HAOBIBI): timmy 0,88, HOPE 0,68, PIRATE 0,66, Leonida 0,52, WEALTH 0,42")
        self.assertIsNone(owner.similar_to(H, ws[0]["features"], ws))    # never the label's own token

    def test_shadow_p_bonus_changes_nothing(self):
        st = {"valid": True, "p_tp": 0.40, "tp_pct": 60.0, "sl_pct": 20.0, "ev_pct": -1.0}
        rc = {"similar_to": {"token": H, "symbol": "HAOBIBI", "score": 0.86}}
        sh = build.similar_shadow(st, rc, 0.03)
        self.assertEqual((sh["similar_to"], sh["p_tp_would_be"], sh["shown_now"]), ("HAOBIBI", 0.45, False))
        self.assertAlmostEqual(sh["ev_pct_would_be"], (0.45 * 0.6 - 0.55 * 0.2 - 0.03) * 100, places=2)
        self.assertTrue(sh["would_be_shown"])
        self.assertEqual((st["p_tp"], st["ev_pct"]), (0.40, -1.0))      # P and EV as they were
        self.assertIsNone(build.similar_shadow(dict(st), {"similar_to": dict(rc["similar_to"], score=0.79)}, 0.03))


if __name__ == "__main__":
    unittest.main()
