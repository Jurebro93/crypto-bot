"""15.11. ~12:35 UTC (vlasnik: "lista od barem 100 tokena ... do 100 tradeova dnevno s ~10 %, više tradeova po tokenu";
veliki/intra.py, veliki/live.py), offline:

  - the intraday zone (48 h of 1h candles, q10 / q90, >= 10 % wide, no trend) and the entry: the bottom 25 %, the bars
    stopped falling, never in a BTC free fall; the stop under the zone's low, at most -12 %
  - the exit fix (the critic: "TP +8 % then trailing 5 %" could leave everything at ~+2.6 %): half at the target, the
    rest's stop to break-even, the trailing from the rest's peak; the blended return
  - the demo universe: the veliki list + the midcap collector's members (MC 2M-200M, liquidity / volume >= $50k, a
    memecoin), >= 100 tokens; the line "veliki demo lista: N tokena"
  - live: an intraday demo entry at 0.1 SOL, the real account only on the veliki list's tokens, the half sale on the
    league trade, the trailing exit of the rest, max 3 rounds a token a day, the hour's report line

    python3 -m unittest tests.test_veliki_intra_offline
"""
import math
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.test_pravi_novac_sve_offline import LU, PU, SwitchBase, tok  # noqa: E402
from veliki import intra, live, midcap, rule, store as vstore  # noqa: E402

H, M15 = 3600, 900
T0 = 1_790_000_000 // 86400 * 86400


def range_h1(t_end, hours=48, base=1.0, amp=0.08, period=16):
    """1h candles ending at t_end: a sine +-amp (a ~16 % range)."""
    out, prev = [], base
    for k in range(hours):
        t = t_end - (hours - k) * H
        c = base * (1 + amp * math.sin(2 * math.pi * k / period))
        out.append((t, prev, max(prev, c) * 1.003, min(prev, c) * 0.997, c, 1000.0))
        prev = c
    return out


def calm15(t_end, px):
    """Three completed 15m bars ending at t_end that stopped falling (higher lows, last close up)."""
    return [(t_end - 3 * M15, px * 1.01, px * 1.012, px * 0.99, px * 0.995, 0.0),
            (t_end - 2 * M15, px * 0.995, px * 1.0, px * 0.991, px * 0.998, 0.0),
            (t_end - M15, px * 0.998, px * 1.004, px * 0.993, px * 1.0, 0.0)]


class Rule(unittest.TestCase):
    def test_zone_and_entry(self):
        t = T0 + 10 * 86400
        z = intra.zone(range_h1(t), t)
        self.assertTrue(z["ok"], z)
        self.assertGreaterEqual(z["width"], 0.10)
        low = z["lo"] * 1.01
        self.assertIsNone(intra.signal(low, z, calm15(t, low)))
        self.assertIn("donjih", intra.signal(z["hi"] * 0.99, z, calm15(t, z["hi"] * 0.99)))
        self.assertIn("slobodan pad", intra.signal(low, z, calm15(t, low), btc_state="slobodan_pad"))
        falling = calm15(t, low)
        falling[-1] = (falling[-1][0], low, low, low * 0.97, low * 0.975, 0.0)
        self.assertIn("pada", intra.signal(low, z, falling))
        self.assertIn("ispod dna", intra.signal(z["lo"] * 0.95, z, calm15(t, z["lo"] * 0.95)))
        trend = [(c[0], c[1], c[2], c[3], 1.0 * 1.01 ** k, c[5]) for k, c in enumerate(range_h1(t))]
        self.assertFalse(intra.zone(trend, t)["ok"])
        self.assertIn("premalo", intra.zone(range_h1(t, hours=6), t)["why"])

    def test_stop_under_zone_capped(self):
        z = {"lo": 0.95, "hi": 1.2}
        self.assertAlmostEqual(intra.stop_px(1.0, z), 0.95 * 0.98)
        self.assertAlmostEqual(intra.stop_px(1.0, {"lo": 0.5, "hi": 1.2}), 0.88)          # -12 % cap
        self.assertAlmostEqual(intra.stop_px(1.0, {"lo": 0.98, "hi": 1.2}), 0.98 * 0.98)  # under the low
        self.assertAlmostEqual(intra.stop_px(1.0, {"lo": 1.03, "hi": 1.2}), 0.97)         # >= 3 % under the entry

    def test_half_then_break_even_and_trailing(self):
        c = intra.cfg_of()
        pos = intra.position(1.0, T0, {"lo": 0.95, "hi": 1.2}, 0.035, c)
        self.assertGreater(pos["tp_px"], 1.13)            # +10 % NET at a 3.5 % round trip
        self.assertGreater(pos["be_px"], 1.035)
        t = T0
        self.assertIsNone(rule.exit_on_bar(pos, (t, 1.0, pos["tp_px"] * 1.02, 1.0, pos["tp_px"] * 1.01, 0), c))
        self.assertTrue(pos.get("half_px"))
        self.assertAlmostEqual(pos["stop_px"], pos["be_px"])
        hit = rule.exit_on_bar(pos, (t + M15, pos["tp_px"], pos["tp_px"], pos["tp_px"] * 0.9, pos["tp_px"] * 0.92, 0), c)
        self.assertEqual(hit[0], "trail")
        r = rule.blend_ret(pos, hit[1], 0.035, c)
        self.assertGreater(r, 0.07)                       # half at +10 %, the rest ~+4.5 %: never the old +2.6 %
        # a gap under the break-even after the half: the rest closes at the break-even stop, the half stays locked
        pos2 = intra.position(1.0, T0, {"lo": 0.95, "hi": 1.2}, 0.035, c)
        rule.exit_on_bar(pos2, (t, 1.0, pos2["tp_px"], 1.0, pos2["tp_px"], 0), c)
        hit2 = rule.exit_on_bar(pos2, (t + M15, 1.0, 1.0, 0.9, 0.95, 0), c)
        self.assertEqual(hit2[0], "be")
        self.assertGreater(rule.blend_ret(pos2, hit2[1], 0.035, c), 0.03)
        # the time stop 24 h
        pos3 = intra.position(1.0, T0, {"lo": 0.95, "hi": 1.2}, 0.035, c)
        self.assertEqual(rule.exit_on_bar(pos3, (T0 + 24 * H - M15, 1.0, 1.01, 0.99, 1.0, 0), c)[0], "time")

    def test_whole_position_trailing_kept_as_variant(self):
        pos = {"entry": 1.0, "ts": T0, "tp_px": 1.10, "stop_px": 0.8, "be_px": 1.04}
        cfg = {"trail": 0.05, "half": 0.0, "time_h": 1000}
        rule.exit_on_bar(pos, (T0 + H, 1.0, 1.15, 1.0, 1.14, 0), cfg)
        self.assertFalse(pos.get("half_px"))
        self.assertEqual(rule.exit_on_bar(pos, (T0 + 2 * H, 1.12, 1.13, 1.05, 1.06, 0), cfg)[0], "trail")

    def test_replay_trades_many_rounds(self):
        b15 = []
        prev = 1.0
        for k in range(4 * 24 * 6):
            c = 1.0 + 0.09 * math.sin(2 * math.pi * k / 64)
            b15.append((T0 + k * M15, prev, max(prev, c) * 1.002, min(prev, c) * 0.998, c, 10.0))
            prev = c
        trs = intra.simulate(b15, None, 0.035, 15.0)
        self.assertGreater(len(trs), 3)
        days = {}
        for x in trs:
            days[x["ts"] // 86400] = days.get(x["ts"] // 86400, 0) + 1
        self.assertLessEqual(max(days.values()), intra.MAX_ROUNDS)
        self.assertTrue(any(x["half"] for x in trs))


class Live(SwitchBase):
    def setUp(self):
        super().setUp()
        self.vdb = os.path.join(self.tmp.name, "veliki.db")
        self.mdb = os.path.join(self.tmp.name, "midcap.db")
        p = mock.patch.dict(os.environ, {"VELIKI_DB": self.vdb, "MIDCAP_DB": self.mdb})
        p.start()
        self.addCleanup(p.stop)
        vstore.reset_cache()
        midcap._MEM.update(ts=0.0, rows=[])
        live._ST.clear()
        live._ST.update(tick=0.0, bar={}, said={}, gt={}, gt_ts=0.0, btc=None, btc_ts=0.0, q={})
        live._LIVE.clear()
        con = vstore.connect(self.vdb)
        vstore.save_list(con, [{"mint": tok(31), "symbol": "BIG", "pool": "P", "dex": "raydium", "mcap": 5e7,
                                "liq": 2e6, "liq_total": 3e6, "vol24": 1e6, "age_d": 100}], self.now)
        con.executemany("INSERT INTO btc_h VALUES (?,?)", [(int(self.now) // H * H - i * H, 80_000.0) for i in range(48)])
        con.commit()
        con.close()
        mc = midcap.connect(self.mdb)
        rows = [(tok(100 + i), 100 + i, f"M{i}", f"P{i}", "raydium", 2e7, 300_000.0, 500_000.0 + i, None, 0, 0, None,
                 "dex", (i if i < 20 else None), 1, None) for i in range(110)]
        rows += [(tok(300), 300, "THIN", "PX", "raydium", 2e7, 40_000.0, 900_000.0, None, 0, 0, None, "dex", None, 1, None),
                 (tok(301), 301, "USDC", "PY", "raydium", 2e7, 900_000.0, 900_000.0, None, 0, 0, None, "dex", None, 1,
                  None)]
        mc.executemany("INSERT INTO tokens VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        mc.commit()
        mc.close()
        self.z = {"ok": True, "lo": 0.9e-4, "hi": 1.2e-4, "width": 0.33, "s_lo": 0.9e-4, "s_hi": 0.975e-4,
                  "r_lo": 1.2e-4, "r_hi": 1.2e-4, "mid": 1.05e-4}
        for obj, name, val in ((live, "_sol", lambda: 150.0),
                               (live, "series", lambda t, now: ([(0, 1, 1, 1, 1, 0)] * 30, [])),
                               (live, "bars_intra", lambda t, now: ([], [])),
                               (intra, "zone", lambda h1, t, cfg=None: dict(self.z)),
                               (rule, "signal", lambda *a, **k: "nije na podršci")):
            p = mock.patch.object(obj, name, val)
            p.start()
            self.addCleanup(p.stop)
        self.sig = mock.patch.object(intra, "signal", lambda *a, **k: None)
        self.sig.start()
        self.addCleanup(self.sig.stop)

    def mk(self, toks, px=1.0e-4):
        return {t: (px, 2_000_000.0, "https://dexscreener.com/solana/raydium", 5e7, "BIG" if t == tok(31) else "MID",
                    {"m5": 0.0}) for t in toks}

    def test_demo_universe_union(self):
        toks, src = live.demo_tokens(self.now)
        self.assertGreaterEqual(len(toks), 100)
        self.assertEqual(toks[0], tok(31))                 # the veliki list first
        self.assertNotIn(tok(300), toks)                   # liquidity < $50k
        self.assertNotIn(tok(301), toks)                   # not a memecoin
        self.assertTrue(all(t in toks[1:21] for t in [tok(100 + i) for i in range(20)]))   # trending first
        self.assertEqual(src["veliki lista"], 1)
        self.assertEqual(src["od toga trending"], 20)
        self.flag("veliki_range", "paper")
        out = live.tick(self.lg, lambda ts: {}, now=self.now, force=True)
        self.assertTrue(any(x.startswith("veliki demo lista: 111 tokena") for x in out), out)

    def test_intra_demo_entry_half_trailing_and_rounds(self):
        # 15.11. navečer: the half at the target only when the whole market rises (live.full_tp False)
        _p = mock.patch.object(live, "full_tp", lambda now: (False, "test: tržište raste"))
        _p.start()
        self.addCleanup(_p.stop)
        self.flag("veliki_range", "paper")
        out = live.tick(self.lg, lambda ts: self.mk([t for t in ts if t in (tok(31), tok(100))]), now=self.now,
                        force=True)
        rows = self.lg.execute("SELECT id, user, token, kind, size_sol, tp_px, stop_px, half_frac FROM veliki_trades "
                               "ORDER BY id").fetchall()
        self.assertEqual({(r[1], r[2], r[3]) for r in rows}, {(PU, tok(31), "intra"), (PU, tok(100), "intra")}, out)
        self.assertTrue(all(r[4] == live.INTRA_DEMO_SOL for r in rows))
        self.assertTrue(any("veliki demo ulaz MID (dnevni raspon)" in x for x in out), out)
        rid, tp, stop = rows[0][0], rows[0][5], rows[0][6]
        self.assertAlmostEqual(stop / 1.0e-4, 0.9 * 0.98, places=3)
        self.assertGreater(tp / 1.0e-4 - 1, 0.10)
        # the price reaches the target: half sold on the league trade, the rest's stop to break-even
        t1 = self.now + 60
        out = live.tick(self.lg, lambda ts: self.mk(ts, tp * 1.01), now=t1, force=True)
        self.assertTrue(any("50% prodano na cilju" in x for x in out), out)
        r = self.lg.execute("SELECT half_px, stop_px, be_px, trade_id FROM veliki_trades WHERE id=?", (rid,)).fetchone()
        self.assertTrue(r[0])
        self.assertAlmostEqual(r[1], r[2])
        qty, size, entry_eff = self.lg.execute("SELECT qty, size_usd, entry_eff FROM trades WHERE id=?",
                                               (r[3],)).fetchone()
        self.assertAlmostEqual(qty / (size / entry_eff), 0.5, places=3)
        # the rest trails 5 % from its peak
        t2 = t1 + 60
        out = live.tick(self.lg, lambda ts: self.mk(ts, tp * 1.01 * 0.94), now=t2, force=True)
        st, reason, ret = self.lg.execute("SELECT status, reason, ret FROM veliki_trades WHERE id=?", (rid,)).fetchone()
        self.assertEqual((st, reason), ("closed", "trail"), out)
        self.assertGreater(ret, 0.06)
        # re-entry after the cooldown, at most MAX_ROUNDS a token a day
        t = t2
        for k in range(6):
            t += intra.COOLDOWN_S + 60
            self.lg.execute("UPDATE veliki_trades SET status='closed', closed_ts=? WHERE status='open'", (int(t - 1900),))
            self.lg.execute("UPDATE trades SET status='closed' WHERE status='open'")
            self.lg.commit()
            live._ST["bar15"] = {}
            live.tick(self.lg, lambda ts: self.mk([x for x in ts if x == tok(100)]), now=t, force=True)
        n = self.lg.execute("SELECT COUNT(*) FROM veliki_trades WHERE token=? AND user=?", (tok(100), PU)).fetchone()[0]
        self.assertEqual(n, intra.MAX_ROUNDS)

    def _prio(self, risk=None):
        rows = {t: {"mint": t, "symbol": t[-3:], "score": 1.0, "parts": {}, "facts": {}} for t in (tok(31), tok(100))}
        if risk:
            for r in rows.values():
                r["risk"] = risk
        from veliki import prioritet
        return mock.patch.object(prioritet, "cached", lambda *a, **k: rows)

    def test_real_only_on_the_veliki_list(self):
        self.flag("veliki_range", "paper")
        from veliki import gate
        with mock.patch.object(gate, "real_refusal", lambda *a, **k: None), self._prio():
            live.tick(self.lg, lambda ts: self.mk([t for t in ts if t in (tok(31), tok(100))]), now=self.now,
                      force=True)
        rows = {(r[0], r[1]) for r in self.lg.execute("SELECT user, token FROM veliki_trades")}
        self.assertIn((LU, tok(31)), rows)
        self.assertIn((PU, tok(100)), rows)
        self.assertNotIn((LU, tok(100)), rows)      # a midcap without the age / list check: demo only
        size = self.lg.execute("SELECT size_sol FROM veliki_trades WHERE user=?", (LU,)).fetchone()[0]
        self.assertEqual(size, 0.1)

    def test_real_needs_the_priority_row(self):
        # 15.11. popodne: without the priority row (holder / safety facts) no real buy; the demo still enters
        self.flag("veliki_range", "paper")
        from veliki import gate
        with mock.patch.object(gate, "real_refusal", lambda *a, **k: None):
            live.tick(self.lg, lambda ts: self.mk([t for t in ts if t in (tok(31), tok(100))]), now=self.now,
                      force=True)
        rows = {(r[0], r[1]) for r in self.lg.execute("SELECT user, token FROM veliki_trades")}
        self.assertNotIn((LU, tok(31)), rows)
        self.assertIn((PU, tok(100)), rows)

    def test_static_risk_known_before_the_buy_refuses_demo_and_real(self):
        self.flag("veliki_range", "paper")
        from veliki import gate
        with mock.patch.object(gate, "real_refusal", lambda *a, **k: None), self._prio("top 10 holdera 60 %"):
            live.tick(self.lg, lambda ts: self.mk([t for t in ts if t in (tok(31), tok(100))]), now=self.now,
                      force=True)
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM veliki_trades").fetchone()[0], 0)

    def test_round_trip_is_the_higher_of_model_and_measured(self):
        self.flag("veliki_range", "paper")
        from veliki import rule
        with mock.patch.object(rule, "demo_rt", lambda *a, **k: 0.045):
            live.tick(self.lg, lambda ts: self.mk([t for t in ts if t == tok(100)]), now=self.now, force=True)
        rt, drt = self.lg.execute("SELECT rt, drt FROM veliki_trades WHERE user=?", (PU,)).fetchone()
        self.assertAlmostEqual(rt, 0.045)
        self.assertAlmostEqual(drt, 0.045)

    def test_owner_once_extends_the_open_trade_once(self):
        from veliki import live as vlive
        vlive.ensure(self.lg)
        self.lg.execute("INSERT INTO veliki_trades (user, token, opened_ts, status, time_h) VALUES (?,?,?,?,?)",
                        (LU, "74SBV4zzzz", int(self.now), "open", 24.0))
        self.lg.commit()
        with mock.patch.object(vlive, "OWNER_ONCE", (("t1", "74SBV4", 72.0),)):
            self.assertTrue(vlive.owner_once(self.lg, self.now))
            self.assertEqual(vlive.owner_once(self.lg, self.now), [])
        self.assertEqual(self.lg.execute("SELECT time_h FROM veliki_trades WHERE token='74SBV4zzzz'").fetchone()[0], 72.0)

    def test_owner_exit_break_even_at_five_percent_and_no_time_stop(self):
        # 15.11. navečer (vlasnik): +5 % net -> the stop to break-even; no time stop; the target still sells half
        pos = {"entry": 1.0, "first": 1.0, "ts": 0, "tp_px": 1.15, "stop_px": 0.95, "be_px": 1.03, "peak": None}
        cfg = {"trail": 0.05, "half": 0.5, "exit_slip": 0.0, "stop_slip": 0.0, "stop_fill": "level",
               "be_at": rule.OWNER_EXIT["be_at"]}
        self.assertIsNone(rule.on_price(pos, 1.05, "t", 1.05, cfg))
        self.assertEqual(pos["stop_px"], 0.95)                      # +1.9 % net: not yet
        self.assertIsNone(rule.on_price(pos, 1.0816, "t", 1.0816, cfg))
        self.assertEqual(pos["stop_px"], 1.03)                      # +5 % net over break-even: stop to break-even
        self.assertEqual(rule.on_price(pos, 1.02, "t", 1.02, cfg)[0], "be")
        self.assertIsNone(rule.OWNER_EXIT["time_h"])
        bar = (10 * 86400, 1.0, 1.01, 0.99, 1.0, 0)
        self.assertIsNone(rule.exit_on_bar({"entry": 1.0, "ts": 0, "tp_px": 1.5, "stop_px": 0.5, "be_px": 1.03},
                                           bar, {"time_h": None, "bar_s": 3600}))

    def test_dynamic_bad_ignores_facts_known_at_entry(self):
        from veliki import prioritet
        self.assertIsNone(prioritet.dynamic_bad({"facts": {"liq_ratio": 0.95, "sells_buys": 1.0, "c24": -3},
                                                 "risk": "top 10 holdera 59 %"}))
        self.assertIn("likvidnost", prioritet.dynamic_bad({"facts": {"liq_ratio": 0.5}}))
        self.assertIn("holderi", prioritet.dynamic_bad({"facts": {}, "block": "holderi: tim prodaje"}))

    def test_full_profit_unless_the_whole_market_rises(self):
        # 15.11. navečer (vlasnik): the whole profit at the target; half + trailing only when BTC jumped, the meme
        # sector is green and the regime risk_on
        from veliki import makro
        base = {"entry": 1.0, "first": 1.0, "ts": 0, "tp_px": 1.15, "stop_px": 0.95, "be_px": 1.03, "peak": None}
        cfg = {"trail": 0.05, "half": 0.5, "exit_slip": 0.0, "stop_slip": 0.0, "stop_fill": "level"}
        self.assertEqual(rule.on_price(dict(base), 1.16, "t", 1.16, {**cfg, "full_tp": True})[0], "tp")
        pos = dict(base)
        self.assertIsNone(rule.on_price(pos, 1.16, "t", 1.16, {**cfg, "full_tp": False}))
        self.assertTrue(pos.get("half_px"))
        up = {"ts": self.now, "btc24": 0.04, "sector": {"mcap_chg24": 2.0}, "regime": "risk_on"}
        self.assertTrue(makro.bull(self.now, up)[0])
        self.assertFalse(makro.bull(self.now, {**up, "btc24": 0.01})[0])
        self.assertFalse(makro.bull(self.now, {**up, "sector": {"mcap_chg24": -1.0}})[0])
        self.assertFalse(makro.bull(self.now, {**up, "regime": "neutral"})[0])
        self.assertFalse(makro.bull(self.now, {})[0])

    def test_chain_line_counts_bought_and_refused(self):
        import sqlite3
        import tempfile
        from veliki import live as vlive
        vlive.ensure(self.lg)
        d0 = int(self.now - 3600)
        for i, tid in enumerate((101, 102)):
            self.lg.execute("INSERT INTO veliki_trades (user, token, opened_ts, trade_id, status) VALUES (?,?,?,?,?)",
                            (LU, tok(200 + i), int(self.now - 60), tid, "open"))
        self.lg.commit()
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.db")
            c = sqlite3.connect(p)
            c.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, league_id INTEGER, mode TEXT, status TEXT)")
            c.executemany("INSERT INTO positions (league_id, mode, status) VALUES (?,?,?)",
                          [(101, "live", "open"), (102, "live", "blocked")])
            c.commit()
            c.close()
            self.assertEqual(vlive.chain_line(self.lg, LU, d0, path=p), "; na lancu danas: kupljeno 1, odbijeno 1")

    def test_hour_report_line(self):
        self.flag("veliki_range", "paper")
        live.tick(self.lg, lambda ts: self.mk([t for t in ts if t == tok(100)]), now=self.now, force=True)
        live._ST["rep_h"] = 0
        out = live.tick(self.lg, lambda ts: self.mk([t for t in ts if t == tok(100)]), now=self.now + 30, force=True)
        line = next(x for x in out if x.startswith("veliki demo: otvoreno"))
        self.assertIn("pravi: otvoreno", line)
        self.assertIn("dobit", line)
        self.assertIn("gubitak", line)
        self.assertTrue(any(x.startswith("veliki odbijeni kandidati zadnji sat") for x in out))


if __name__ == "__main__":
    unittest.main()
