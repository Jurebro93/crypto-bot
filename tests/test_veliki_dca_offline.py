"""15.11. (vlasnik: "uključi DCA ... zatvaraju se tradeovi gdje postoji dobar razlog"; veliki/rule.py, veliki/live.py,
run_trade.py), offline:

  - the smart DCA: allowed only when every condition holds (BTC not in a free fall, the macro regime not risk_off, no
    bad dip reason, category A / B with a history of recovering after BTC +3 % days, the volume holding, the caps), one
    lot a position; the average entry moves the target and the break-even, the stop stays the FIRST entry's
  - the reasoned exits: a bad reason, BTC's free fall (protect a profit / cut under -10 %), the macro risk_off (the
    same, else the stop tightens to -10 %), the volume collapsing
  - live: the DCA lot is a second league trade (run_trade adds it to the first lot's real position only while that one
    is open), it counts in the day's buys; a reasoned exit closes with its reason stored

    python3 -m unittest tests.test_veliki_dca_offline
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.test_pravi_novac_sve_offline import LU, PU, SwitchBase, tok  # noqa: E402
from veliki import live, rule, store as vstore  # noqa: E402

H = 3600
T0 = 1_790_000_000 // 86400 * 86400
GOOD_M = {"cat": "A", "btc_up_n": 6, "btc_up_hit": 0.67, "btc_up_72h": 4.1}


def good_ctx(**kw):
    c = {"btc_state": "normalno", "macro": "neutral", "cat": "A", "metrics": dict(GOOD_M), "dip_kind": "trzisni",
         "bad": None, "vol_ratio": 0.9, "lots": 1, "room": None}
    c.update(kw)
    return c


class DcaRule(unittest.TestCase):
    def test_every_condition(self):
        self.assertIsNone(rule.dca_refusal(good_ctx()))
        self.assertIsNone(rule.dca_refusal(good_ctx(macro=None, dip_kind=None, vol_ratio=None)))   # unknown != bad
        for kw, word in (({"lots": 2}, "jedan po poziciji"), ({"half_done": True}, "polovica"),
                         ({"btc_state": "slobodan_pad"}, "slobodnom padu"), ({"macro": "risk_off"}, "risk-off"),
                         ({"bad": "LP povučen"}, "loš razlog"), ({"dip_kind": "los"}, "loš"),
                         ({"cat": "C"}, "kategorija C"), ({"cat": None}, "kategorija ?"),
                         ({"metrics": {"btc_up_n": 1}}, "premalo dana"),
                         ({"metrics": {"btc_up_n": 5, "btc_up_hit": 0.2, "btc_up_72h": -3.0}}, "ne oporavlja"),
                         ({"vol_ratio": 0.2}, "urušio"), ({"room": "dnevni strop kupnji (20)"}, "dnevni strop")):
            self.assertIn(word, rule.dca_refusal(good_ctx(**kw)) or "", kw)
        self.assertIn("kategorija A", rule.dca_why(good_ctx(), {"dca": 0.10}))

    def test_levels(self):
        self.assertAlmostEqual(rule.dca_level(1.0, None, {"dca": 0.10}), 0.9)
        self.assertIsNone(rule.dca_level(1.0, None, {"dca": 0.0}))
        self.assertAlmostEqual(rule.dca_level(1.0, {"s_lo": 0.9}, {"dca_mode": "zona"}), 0.882)
        self.assertAlmostEqual(rule.dca_level(1.0, {"s_lo": 0.99}, {"dca_mode": "zona"}), 0.95)     # >= 5 % under
        self.assertAlmostEqual(rule.dca_level(1.0, {"atr": 0.04}, {"dca_mode": "atr"}), 0.88)

    def bars(self):
        """1h bars: entry at 1.0, a dip to 0.88, the recovery to 1.10 (short of one lot's +8 % net)."""
        px = [1.0] * 3 + [0.97, 0.93, 0.89, 0.88, 0.9, 0.95, 1.0, 1.05, 1.08, 1.1, 1.1]
        return [(T0 + k * H, p, p * 1.004, p * 0.996, p, 1000.0) for k, p in enumerate(px)]

    def run_sim(self, ctx, cfg=None):
        b = self.bars()
        c = {"tp": 8.0, "trail": 0.0, "time_h": 72, "dca": 0.10, "stop": "pct20", **(cfg or {})}
        return rule.simulate(b, [(1, {"ok": True, "s_lo": 0.95})], 15.0, 0.03, c, rt2=0.035, ctx=ctx)

    def test_backtest_dca_on_and_off(self):
        ok = {"macro": lambda t: "neutral", "cat": "A", "metrics": dict(GOOD_M), "vol": None}
        tr = self.run_sim(ok)[0]
        self.assertEqual(tr["lots"], 2)
        self.assertTrue(tr["dca"])
        self.assertAlmostEqual(tr["entry"], 2 / (1 / tr["first"] + 1 / tr["dca"]["px"]))   # the average entry
        self.assertEqual(tr["reason"], "tp")
        self.assertAlmostEqual(tr["pnl"], tr["ret"] * 15.0 * 2)
        no = self.run_sim({**ok, "cat": "C"})[0]
        self.assertEqual(no["lots"], 1)
        self.assertNotEqual(no["reason"], "tp")                     # one lot: the target is not reached
        risk_off = self.run_sim({**ok, "macro": lambda t: "risk_off"})[0]
        self.assertEqual(risk_off["lots"], 1)
        # the stop stays the FIRST entry's (-20 %): it never widens with the average
        b = self.bars()[:7] + [(T0 + 7 * H, 0.82, 0.83, 0.79, 0.8, 1.0)]
        c = {"tp": 8.0, "trail": 0.0, "time_h": 72, "dca": 0.10, "stop": "pct20"}
        x = rule.simulate(b, [(1, {"ok": True, "s_lo": 0.95})], 15.0, 0.03, c, rt2=0.035, ctx=ok)[0]
        self.assertEqual((x["reason"], x["lots"]), ("stop", 2))
        self.assertAlmostEqual(x["exit"], b[2][1] * (1 + rule.RULE["entry_slip"]) * 0.8 * (1 - rule.RULE["stop_slip"]))


class Reasoned(unittest.TestCase):
    def pos(self):
        return {"entry": 1.0, "first": 1.0, "stop_px": 0.8, "tp_px": 1.1}

    def test_reasons(self):
        p = self.pos()
        self.assertEqual(rule.reasoned_exit(p, 1.0, 0.03, {"bad": "dev prodaje"})[0], "los")
        # 15.11. navečer (vlasnik: "ako odmah nakon ulaza krene u mali loss, onda čekaš"): a dip classified "los" on
        # facts known at the entry no longer closes; only new danger (ctx bad: live.context's dynamic reasons) does
        self.assertEqual(rule.reasoned_exit(p, 1.0, 0.03, {"dip_kind": "los"}), (None, None))
        self.assertEqual(rule.reasoned_exit(p, 1.06, 0.03, {"btc_state": "slobodan_pad"})[0], "btc_zastita")
        self.assertEqual(rule.reasoned_exit(p, 0.88, 0.03, {"btc_state": "slobodan_pad"})[0], "btc_rez")
        self.assertEqual(rule.reasoned_exit(p, 0.97, 0.03, {"btc_state": "slobodan_pad"}), (None, None))
        self.assertEqual(rule.reasoned_exit(p, 1.06, 0.03, {"macro": "risk_off"})[0], "makro_zastita")
        self.assertEqual(rule.reasoned_exit(p, 0.89, 0.03, {"macro": "risk_off"})[0], "makro_rez")
        rs, tight = rule.reasoned_exit(p, 0.97, 0.03, {"macro": "risk_off"})
        self.assertIsNone(rs)
        self.assertAlmostEqual(tight, 0.9)
        self.assertEqual(rule.reasoned_exit(p, 1.0, 0.03, {"vol_ratio": 0.2})[0], "volumen")
        self.assertEqual(rule.reasoned_exit(p, 1.0, 0.03, {"vol_ratio": 0.5}), (None, None))

    def test_vol_ratios(self):
        b = [(T0 + k * H, 1, 1, 1, 1, 100.0) for k in range(200)] + [(T0 + (200 + k) * H, 1, 1, 1, 1, 10.0)
                                                                     for k in range(24)]
        vr = rule.vol_ratios(b)
        self.assertIsNone(vr[100])
        self.assertAlmostEqual(vr[199], 1.0)
        self.assertLess(vr[-1], 0.3)
        own = [(T0 + k * H, 1, 1, 1, 1, 0.0) for k in range(200)]           # own bars carry no volume
        self.assertIsNone(rule.vol_ratios(own)[-1])

    def test_backtest_reasoned_exit(self):
        b = [(T0 + k * H, 1.0 + 0.01 * k, 1.0 + 0.01 * k, 1.0 + 0.01 * k, 1.0 + 0.01 * k, 1.0) for k in range(10)]
        crash = mock.Mock()
        crash.regime = lambda t: ("slobodan_pad", "x") if t >= T0 + 5 * H else ("normalno", "")
        c = {"tp": 25.0, "trail": 0.0, "time_h": 72, "reasoned": True, "crash_filter": False}
        x = rule.simulate(b, [(1, {"ok": True, "s_lo": 0.9})], 15.0, 0.01, c, crash=crash,
                          ctx={"macro": None, "cat": "A", "metrics": {}, "vol": None})[0]
        self.assertEqual(x["reason"], "btc_zastita")
        self.assertGreater(x["ret"], 0)


class Walk(unittest.TestCase):
    def test_variants_dca_on_off_reasoned_macro_and_intra_replay(self):
        import math
        from veliki import walk
        from tests.test_veliki_range_offline import flat_btc, series_of
        series = series_of(A="range", B="trend")
        b15 = []
        for k in range(10 * 96):
            c = 1.0 + 0.09 * math.sin(2 * math.pi * k / 64)
            b15.append((T0 + k * 900, c, c * 1.003, c * 0.997, c, 10.0))
        series["A"]["b15"] = b15
        cats = {"A": dict(GOOD_M), "B": {"cat": "C"}}
        days = {d: ("risk_off" if d % 5 == 0 else "neutral") for d in range(T0 // 86400 - 5, T0 // 86400 + 40)}
        with mock.patch.object(rule, "tx_sol", lambda: (0.0005, "test")), mock.patch.object(walk, "MIN_ALL_N", 3), \
                mock.patch.object(walk, "MIN_TRAIN_N", 2):
            d = walk.compute(series, flat_btc(), [], now=T0 + 31 * 86400, log=lambda s: None, sol_usd=150.0,
                             sizes=(0.5,), grid={"tp": (8.0,), "trail": (0.05,), "time_h": (72,), "look_d": (7,)},
                             stops=("pct20",), cats=cats, macro_days=days)
        vh = d["variants"]["dno"]["0.5"]["variants_holdout"]
        for k in ("osnovno", "cijeli_trailing", "dca_10_bez_uvjeta", "dca_10", "razlozi", "makro_filter", "sve",
                  "siri_ulaz"):
            self.assertIn(k, vh)
            for f in ("n", "ev_pct", "max_dd_usd", "worst_pct", "dca_n"):
                self.assertIn(f, vh[k])
        self.assertLessEqual(vh["makro_filter"]["n"], vh["osnovno"]["n"])
        self.assertGreater(vh["osnovno"]["half_n"], 0)
        self.assertEqual(vh["cijeli_trailing"]["half_n"], 0)
        self.assertGreater(d["intra"]["n"], 0)
        self.assertIn("Dnevni raspon (replay", walk.markdown(d))
        self.assertIn("dca_10", walk.variants_line(vh))


class Live(SwitchBase):
    def setUp(self):
        super().setUp()
        self.vdb = os.path.join(self.tmp.name, "veliki.db")
        p = mock.patch.dict(os.environ, {"VELIKI_DB": self.vdb, "MIDCAP_DB": os.path.join(self.tmp.name, "m.db")})
        p.start()
        self.addCleanup(p.stop)
        vstore.reset_cache()
        live._ST.clear()
        live._ST.update(tick=0.0, bar={}, said={}, gt={}, gt_ts=0.0, btc=None, btc_ts=0.0, q={})
        live._LIVE.clear()
        con = vstore.connect(self.vdb)
        vstore.save_list(con, [{"mint": tok(41), "symbol": "USELESS", "pool": "P", "dex": "raydium", "mcap": 5e7,
                                "liq": 2e6, "liq_total": 3e6, "vol24": 1e6, "age_d": 100}], self.now)
        con.executemany("INSERT INTO btc_h VALUES (?,?)", [(int(self.now) // H * H - i * H, 80_000.0) for i in range(48)])
        con.commit()
        con.close()
        self.ctx = good_ctx()
        zone = {"ok": True, "s_lo": 0.95e-4, "s_hi": 1.0e-4, "r_lo": 1.15e-4, "r_hi": 1.2e-4, "mid": 1.07e-4}
        for obj, name, val in ((live, "_sol", lambda: 150.0),
                               (live, "series", lambda t, now: ([(0, 1, 1, 1, 1, 0)] * 30, [])),
                               (live, "bars_intra", lambda t, now: ([], [])),
                               (live, "context", lambda t, now: dict(self.ctx)),
                               (rule.Zones, "at", lambda self_, t, look: dict(zone)),
                               (rule, "signal", lambda *a, **k: None)):
            p = mock.patch.object(obj, name, val)
            p.start()
            self.addCleanup(p.stop)
        self.flag("veliki_range", "paper")

    def mk(self, px):
        return lambda toks: {t: (px, 2_000_000.0, "https://dexscreener.com/solana/raydium", 5e7, "USELESS",
                                 {"m5": 0.0}) for t in toks}

    def open_one(self):
        live.tick(self.lg, self.mk(1.0e-4), now=self.now, force=True)
        r = self.lg.execute("SELECT id, stop_px, size_usd, entry_px FROM veliki_trades WHERE user=? AND token=?",
                            (PU, tok(41))).fetchone()
        self.assertTrue(r)
        return r

    def test_dca_lot_average_and_caps(self):
        # 15.11. navečer: the half at the target only when the whole market rises (live.full_tp False)
        _p = mock.patch.object(live, "full_tp", lambda now: (False, "test: tržište raste"))
        _p.start()
        self.addCleanup(_p.stop)
        rid, stop, size, entry = self.open_one()
        out = live.tick(self.lg, self.mk(0.89e-4), now=self.now + 60, force=True)
        line = next(x for x in out if x.startswith("veliki DCA USELESS"))
        self.assertIn("razlog:", line)
        self.assertIn("kategorija A", line)
        r = self.lg.execute("SELECT lots, entry_px, stop_px, size_usd, dca_trade_id, tp_px FROM veliki_trades WHERE id=?",
                            (rid,)).fetchone()
        self.assertEqual(r[0], 2)
        self.assertAlmostEqual(r[1], 2 / (1 / entry + 1 / 0.89e-4))
        self.assertAlmostEqual(r[2], stop)                                   # the first entry's stop stays
        self.assertAlmostEqual(r[3], size * 2)
        self.assertGreater(r[5], r[1])
        src = self.lg.execute("SELECT source, status FROM trades WHERE id=?", (r[4],)).fetchone()
        self.assertTrue(src[0].startswith("veliki: DCA USELESS"))
        self.assertEqual(live.buys_today(self.lg, PU, self.now + 60), 2)    # the DCA lot counts in the day's buys
        live.tick(self.lg, self.mk(0.88e-4), now=self.now + 120, force=True)
        self.assertEqual(self.lg.execute("SELECT lots FROM veliki_trades WHERE id=?", (rid,)).fetchone()[0], 2)
        # the target sells half of BOTH league trades, the trailing closes both
        out = live.tick(self.lg, self.mk(r[5] * 1.01), now=self.now + 180, force=True)
        self.assertTrue(any("50% prodano na cilju" in x for x in out), out)
        for tid in (self.lg.execute("SELECT trade_id FROM veliki_trades WHERE id=?", (rid,)).fetchone()[0], r[4]):
            q, sz, ee = self.lg.execute("SELECT qty, size_usd, entry_eff FROM trades WHERE id=?", (tid,)).fetchone()
            self.assertAlmostEqual(q / (sz / ee), 0.5, places=3)
        live.tick(self.lg, self.mk(r[5] * 1.01 * 0.94), now=self.now + 240, force=True)
        st = self.lg.execute("SELECT status, reason, ret FROM veliki_trades WHERE id=?", (rid,)).fetchone()
        self.assertEqual(st[:2], ("closed", "trail"))
        self.assertGreater(st[2], 0.04)
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM trades WHERE token=? AND user=? AND status='open'",
                                         (tok(41), PU)).fetchone()[0], 0)

    def test_dca_blocked_category_and_btc_free_fall_cuts(self):
        rid = self.open_one()[0]
        self.ctx = good_ctx(cat="C")
        out = live.tick(self.lg, self.mk(0.89e-4), now=self.now + 60, force=True)
        self.assertTrue(any("veliki DCA USELESS odbijen (kategorija C" in x for x in out), out)
        self.assertEqual(self.lg.execute("SELECT lots FROM veliki_trades WHERE id=?", (rid,)).fetchone()[0], 1)
        self.ctx = good_ctx(btc_state="slobodan_pad")          # -11 % in BTC's free fall: cut, never a DCA
        live.tick(self.lg, self.mk(0.89e-4), now=self.now + 120, force=True)
        self.assertEqual(tuple(self.lg.execute("SELECT status, reason, lots FROM veliki_trades WHERE id=?",
                                               (rid,)).fetchone()), ("closed", "btc_rez", 1))

    def test_real_day_cap_counts_the_dca(self):
        cp = live.caps(LU)
        self.assertEqual((cp["per_day"], cp["max_open"], cp["size_sol"]), (20, 5, 0.1))
        live.ensure(self.lg)
        for i in range(19):
            self.lg.execute("INSERT INTO veliki_trades (user, token, opened_ts, status) VALUES (?,?,?,'closed')",
                            (LU, tok(200 + i), int(self.now)))
        self.assertIsNone(live.room(self.lg, LU, self.now, 150.0, cp, new_position=False))
        self.lg.execute("UPDATE veliki_trades SET dca_ts=? WHERE token=?", (int(self.now), tok(200)))
        self.assertIn("dnevni strop kupnji", live.room(self.lg, LU, self.now, 150.0, cp, new_position=False))
        self.lg.execute("DELETE FROM veliki_trades")
        self.lg.execute("INSERT INTO veliki_trades (user, token, opened_ts, closed_ts, status, pnl_usd) VALUES "
                        "(?,?,?,?,'closed',?)", (LU, tok(250), int(self.now), int(self.now), -46.0))
        self.assertIn("dnevni gubitak", live.room(self.lg, LU, self.now, 150.0, cp, new_position=False))

    def test_reasoned_exit_btc_free_fall_protects_profit(self):
        rid = self.open_one()[0]
        self.ctx = good_ctx(btc_state="slobodan_pad")
        out = live.tick(self.lg, self.mk(1.06e-4), now=self.now + 60, force=True)
        st, reason, why = self.lg.execute("SELECT status, reason, exit_why FROM veliki_trades WHERE id=?",
                                          (rid,)).fetchone()
        self.assertEqual((st, reason), ("closed", "btc_zastita"), out)
        self.assertIn("BTC slobodan_pad", why)
        self.assertTrue(any("zaštita profita" in x for x in out))

    def test_reasoned_exit_bad_reason_and_tighten(self):
        rid = self.open_one()[0]
        self.ctx = good_ctx(macro="risk_off", dip_kind="trzisni")
        live.tick(self.lg, self.mk(0.97e-4), now=self.now + 60, force=True)
        r = self.lg.execute("SELECT status, stop_px, first_px FROM veliki_trades WHERE id=?", (rid,)).fetchone()
        self.assertEqual(r[0], "open")
        self.assertAlmostEqual(r[1], r[2] * 0.9)                             # tightened to -10 % from the first entry
        self.ctx = good_ctx(bad="prijenos na burzu MEXC (depozit za prodaju)")
        live.tick(self.lg, self.mk(0.97e-4), now=self.now + 120, force=True)
        st, reason, why = self.lg.execute("SELECT status, reason, exit_why FROM veliki_trades WHERE id=?",
                                          (rid,)).fetchone()
        self.assertEqual((st, reason), ("closed", "los"))
        self.assertIn("depozit za prodaju", why)

    def test_macro_risk_off_no_new_entries(self):
        from veliki import makro
        with mock.patch.object(makro, "current", lambda now=None, **k: {"regime": "risk_off", "why": "x", "ts": now}):
            out = live.tick(self.lg, self.mk(1.0e-4), now=self.now, force=True)
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM veliki_trades").fetchone()[0], 0)
        self.assertTrue(any("veliki makro režim: risk_off" in x for x in out), out)

    def test_run_trade_adds_the_dca_only_to_an_open_first_lot(self):
        import run_trade
        self.open_one()
        live.tick(self.lg, self.mk(0.89e-4), now=self.now + 60, force=True)
        live.ensure(self.lg)
        first, dca_id = self.lg.execute("SELECT trade_id, dca_trade_id FROM veliki_trades").fetchone()
        import sqlite3
        self.lg.row_factory = sqlite3.Row
        t = self.lg.execute("SELECT * FROM trades WHERE id=?", (dca_id,)).fetchone()
        why, add = run_trade._veliki_dca(self.con, self.lg, t)
        self.assertFalse(add)
        self.assertIn("bez pravog prvog lota", why)
        self.con.execute("INSERT INTO positions (league_id, token, symbol, opened_ts, mode, status) VALUES "
                         "(?,?,?,?,?,?)", (first, tok(41), "USELESS", int(self.now), "dry", "open"))
        self.assertEqual(run_trade._veliki_dca(self.con, self.lg, t), (None, True))
        t1 = self.lg.execute("SELECT * FROM trades WHERE id=?", (first,)).fetchone()
        self.assertEqual(run_trade._veliki_dca(self.con, self.lg, t1), (None, False))
        self.assertIsNone(run_trade._no_stop(self.lg, t))


if __name__ == "__main__":
    unittest.main()
