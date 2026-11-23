"""23.11. (vlasnik: "Demo tradanje ne troši nikakve prave novce. Demo tradanje nikad ne treba prestati. Bez obzira
koliko je volumen pao, to treba vrijediti samo za pravi novac. Za demo uvijek ide tradanje."), offline:

  - in the macro regime risk_off the rule's demo (dnevni raspon and raspon 7 d), the explorer and the shadow book open
    entries, each tagged with the gate (veliki_trades.gate "makro risk-off"), while the REAL account is refused
    exactly as before (no row, no league trade, no real order); BTC's free fall the same ("BTC slobodan pad")
  - live.enter refuses the real account whoever calls it while a market gate holds (the učenik's real twin too)
  - a demo position opened in risk_off is not closed by the macro reasoned exit and follows the normal DCA rule; a
    position opened outside risk_off keeps today's exits (makro_zastita)
  - the proof numbers (live.demo_stats -> gate.demo_proof, ucenik.stats, istrazivac.stats, nauceno.learn,
    report/midcap.strategies) leave the gated entries out and report them apart
  - makroinf's bearish index tags the demo entry (gate_info) instead of skipping it; real money never reads it, so
    the entry stays in the proof
  - the wallet-following demo has no market gate at all
  - the hourly lines: "veliki makro risk-off: pravi novac bez novih ulaza; demo ulazi s oznakom (danas N ...)"

    python3 -m unittest tests.test_demo_uvijek_offline
"""
import os
import sqlite3
import sys
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.test_pravi_novac_sve_offline import LU, PU, SwitchBase, tok  # noqa: E402
from tests.test_veliki_dca_offline import good_ctx  # noqa: E402
from veliki import gate, intra, istrazivac, live, makro, midcap, nauceno, rule, sjena, ucenik  # noqa: E402
from veliki import store as vstore  # noqa: E402

H, D = 3600, 86400


def risk_off(now=None, **k):
    return {"regime": "risk_off", "why": "volumen meme platformi -32 % prema prosjeku 7 d", "ts": now or time.time()}


def free_fall_state(now=None):
    return {"known": True, "crash": True, "crash_obj": rule.NO_CRASH, "state": "slobodan_pad",
            "why": "novo dno BTC-a prije 1 h", "last_end": None}


class Intra(SwitchBase):
    """The intraday rule's tick (as tests/test_veliki_intra_offline.Live) under the market gates."""

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
        sjena._ST.update(ready=False, open={}, day=None, n_day=0)
        con = vstore.connect(self.vdb)
        vstore.save_list(con, [{"mint": tok(31), "symbol": "BIG", "pool": "P", "dex": "raydium", "mcap": 5e7,
                                "liq": 2e6, "liq_total": 3e6, "vol24": 1e6, "age_d": 100}], self.now)
        con.executemany("INSERT INTO btc_h VALUES (?,?)", [(int(self.now) // H * H - i * H, 80_000.0) for i in range(48)])
        con.commit()
        con.close()
        mc = midcap.connect(self.mdb)
        mc.executemany("INSERT INTO tokens VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       [(tok(100 + i), 100 + i, f"M{i}", f"P{i}", "raydium", 2e7, 300_000.0, 500_000.0 + i, None, 0, 0,
                         None, "dex", None, 1, None) for i in range(3)])
        mc.commit()
        mc.close()
        self.z = {"ok": True, "lo": 0.9e-4, "hi": 1.2e-4, "width": 0.33, "s_lo": 0.9e-4, "s_hi": 0.975e-4,
                  "r_lo": 1.2e-4, "r_hi": 1.2e-4, "mid": 1.05e-4}
        self.sig = lambda px, z, b15, cfg=None, btc_state=None: (
            "BTC slobodan pad: bez novih ulaza" if btc_state == "slobodan_pad" else None)
        prio = {t: {"mint": t, "symbol": t[-3:], "score": 1.0, "parts": {}, "facts": {}}
                for t in (tok(31), tok(100), tok(101), tok(102))}
        from veliki import prioritet
        for obj, name, val in ((live, "_sol", lambda: 150.0),
                               (live, "series", lambda t, now: ([(0, 1, 1, 1, 1, 0)] * 30, [])),
                               (live, "bars_intra", lambda t, now: ([], [])),
                               (intra, "zone", lambda h1, t, cfg=None: dict(self.z)),
                               (intra, "signal", lambda *a, **k: self.sig(*a, **k)),
                               (rule, "signal", lambda *a, **k: "nije na podršci"),
                               (prioritet, "cached", lambda *a, **k: prio),
                               (gate, "real_refusal", lambda *a, **k: None)):   # real money otherwise allowed
            p = mock.patch.object(obj, name, val)
            p.start()
            self.addCleanup(p.stop)
        self.flag("veliki_range", "paper")

    def mk(self, toks, px=1.0e-4):
        return {t: (px, 2_000_000.0, "https://dexscreener.com/solana/raydium", 5e7, "BIG" if t == tok(31) else "MID",
                    {"m5": 0.0}) for t in toks}

    def rows(self):
        return [tuple(r) for r in self.lg.execute("SELECT user, token, gate, makro FROM veliki_trades ORDER BY id")]

    def test_control_without_a_gate_real_enters(self):
        live.tick(self.lg, lambda ts: self.mk(ts), now=self.now, force=True)
        rows = self.rows()
        self.assertIn((LU, tok(31)), [(u, t) for u, t, _g, _m in rows])
        self.assertTrue(all(g is None for _u, _t, g, _m in rows))
        self.assertIsNone(live.real_gate())

    def test_risk_off_real_refused_demo_explorer_shadow_enter_tagged(self):
        with mock.patch.object(makro, "current", risk_off):
            out = live.tick(self.lg, lambda ts: self.mk(ts), now=self.now, force=True)
        rows = self.rows()
        self.assertFalse([r for r in rows if r[0] == LU], rows)                       # real money: refused as before
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM trades WHERE user=?", (LU,)).fetchone()[0], 0)
        self.assertEqual(self.swaps, [])                                              # no order of any kind
        demo = [r for r in rows if r[0] == PU]
        self.assertGreaterEqual(len(demo), 4, rows)                                  # every demo candidate entered
        self.assertTrue(all(r[2] == live.GATE_MAKRO for r in demo), demo)
        self.assertTrue(all((r[3] or "").startswith("risk_off") for r in demo), demo)
        self.assertTrue(any("veliki demo ulaz" in x and "makro risk-off: pravi novac bi stajao" in x for x in out), out)
        self.assertEqual(live.real_gate(), live.GATE_MAKRO)
        n_sh = self.lg.execute("SELECT COUNT(*) FROM veliki_sjena WHERE makro LIKE 'risk_off%'").fetchone()[0]
        self.assertGreater(n_sh, 0)                                                   # the shadow book too
        self.assertEqual(sjena.gated_today(self.lg, self.now), n_sh)
        # the hour's line: real money held, the demo entering (never the old "makro risk-off: bez novih ulaza N")
        gl = live.gate_line(self.lg, self.now)
        self.assertTrue(gl.startswith("veliki makro risk-off: pravi novac bez novih ulaza; demo ulazi s oznakom "
                                      f"(danas {len(demo)} demo ulaza, sjena {n_sh})"), gl)
        self.assertNotIn("makro risk-off", live.refusal_line())

    def test_risk_off_explorer_enters_tagged(self):
        self.sig = lambda *a, **k: "nije u donjih 25 % zone"
        with mock.patch.object(makro, "current", risk_off), \
                mock.patch.object(istrazivac, "variant", lambda *a, **k: "sire"):
            live.tick(self.lg, lambda ts: self.mk(ts), now=self.now, force=True)
        ex = [tuple(r) for r in self.lg.execute("SELECT gate, varijanta FROM veliki_trades WHERE user=?",
                                                (istrazivac.USER,))]
        self.assertTrue(ex)
        self.assertTrue(all(r == (live.GATE_MAKRO, "sire") for r in ex), ex)
        self.assertFalse(self.lg.execute("SELECT 1 FROM veliki_trades WHERE user=?", (LU,)).fetchone())

    def test_btc_free_fall_real_refused_demo_tagged(self):
        seen = []
        orig = istrazivac.variant

        def var(px, z, b15, cfg, btc_state=None, grok=None, now=None):
            seen.append(btc_state)
            return orig(px, z, b15, cfg, btc_state, grok, now)
        with mock.patch.object(live, "btc_state", free_fall_state), mock.patch.object(istrazivac, "variant", var):
            live.tick(self.lg, lambda ts: self.mk(ts), now=self.now, force=True)
        rows = self.rows()
        self.assertFalse([r for r in rows if r[0] == LU], rows)
        demo = [r for r in rows if r[0] == PU]
        self.assertTrue(demo)
        self.assertTrue(all(r[2] == live.GATE_BTC for r in demo), demo)
        self.assertNotIn("slobodan_pad", seen)       # the explorer is not asked about the free fall either

    def test_enter_refuses_real_whoever_calls_while_gated(self):
        live.ensure(self.lg)
        live._ST["real_gate"] = live.GATE_MAKRO
        q = self.mk([tok(31)])[tok(31)]
        text, why, vid = live.enter(self.lg, LU, tok(31), q, self.now, 150.0, self.z, intra.cfg_of(), kind="intra",
                                    meta=(1.0, None))
        self.assertEqual((text, vid), (None, None))
        self.assertIn("pravi novac bez novih ulaza", why)
        text, why, vid = live.enter(self.lg, PU, tok(31), q, self.now, 150.0, self.z, intra.cfg_of(), kind="intra",
                                    meta=(1.0, None))
        self.assertTrue(vid, why)
        self.assertEqual(self.lg.execute("SELECT gate FROM veliki_trades WHERE id=?", (vid,)).fetchone()[0],
                         live.GATE_MAKRO)

    def test_ucenik_real_twin_refused_while_gated(self):
        live.ensure(self.lg)
        live._ST["real_gate"] = live.GATE_MAKRO
        out = []
        e = {"k": {"symbol": "BIG", "px": 1e-4, "rt": 0.03}, "prof": "skalp", "pred": 0.02, "tp_px": 1.1e-4,
             "stop_px": 0.96e-4, "demo_id": 1, "model_ts": int(self.now), "facts": {}}
        with mock.patch.object(ucenik, "_real_ready", lambda: None):
            rid = ucenik._enter_real(self.lg, out, set(), tok(31), self.mk([tok(31)])[tok(31)], self.now, 150.0, self.z,
                                     intra.cfg_of(), {"state": "normalno"}, {}, {tok(31)}, None, e)
        self.assertIsNone(rid)
        self.assertTrue(any("makro risk-off: pravi novac bez novih ulaza" in x for x in out), out)
        self.assertFalse(self.lg.execute("SELECT 1 FROM veliki_trades WHERE user=?", (LU,)).fetchone())


class Range(SwitchBase):
    """The 7-day rule's tick (as tests/test_veliki_dca_offline.Live): the exits and the DCA of a gated position."""

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
                               (live, "full_tp", lambda now: (True, "test")),
                               (rule.Zones, "at", lambda self_, t, look: dict(zone)),
                               (rule, "signal", lambda *a, **k: None)):
            p = mock.patch.object(obj, name, val)
            p.start()
            self.addCleanup(p.stop)
        self.flag("veliki_range", "paper")

    def mk(self, px):
        return lambda toks: {t: (px, 2_000_000.0, "https://dexscreener.com/solana/raydium", 5e7, "USELESS",
                                 {"m5": 0.0}) for t in toks}

    def open_one(self, gated):
        if gated:
            with mock.patch.object(makro, "current", risk_off):
                live.tick(self.lg, self.mk(1.0e-4), now=self.now, force=True)
        else:
            live.tick(self.lg, self.mk(1.0e-4), now=self.now, force=True)
        r = self.lg.execute("SELECT id, gate FROM veliki_trades WHERE user=? AND token=?", (PU, tok(41))).fetchone()
        self.assertTrue(r)
        self.assertEqual(r[1], live.GATE_MAKRO if gated else None)
        return r[0]

    def state(self, rid):
        return tuple(self.lg.execute("SELECT status, reason, lots FROM veliki_trades WHERE id=?", (rid,)).fetchone())

    def test_gated_position_not_closed_by_the_macro_exit(self):
        rid = self.open_one(True)
        self.ctx = good_ctx(macro="risk_off")
        live.tick(self.lg, self.mk(1.06e-4), now=self.now + 60, force=True)    # +6 %: makro_zastita for an ungated one
        self.assertEqual(self.state(rid)[0], "open")
        stop = self.lg.execute("SELECT stop_px, first_px FROM veliki_trades WHERE id=?", (rid,)).fetchone()
        self.assertLess(stop[0], stop[1] * 0.9 * 0.999)                          # nor tightened to -10 % by it
        self.ctx = good_ctx(macro="risk_off", bad="prijenos na burzu (depozit za prodaju)")
        live.tick(self.lg, self.mk(1.06e-4), now=self.now + 120, force=True)   # a token-quality exit still applies
        self.assertEqual(self.state(rid)[:2], ("closed", "los"))

    def test_ungated_position_keeps_todays_macro_exit(self):
        rid = self.open_one(False)
        self.ctx = good_ctx(macro="risk_off")
        live.tick(self.lg, self.mk(1.06e-4), now=self.now + 60, force=True)
        self.assertEqual(self.state(rid)[:2], ("closed", "makro_zastita"))

    def test_gated_position_follows_the_normal_dca(self):
        rid = self.open_one(True)
        self.ctx = good_ctx(macro="risk_off")
        out = live.tick(self.lg, self.mk(0.89e-4), now=self.now + 60, force=True)
        self.assertEqual(self.state(rid), ("open", None, 2), out)                  # the DCA lot, no makro_rez

    def test_real_rows_keep_every_gate(self):
        ctx = good_ctx(macro="risk_off", btc_state="slobodan_pad")
        self.assertEqual(live._gate_ctx({"user": LU, "gate": live.GATE_MAKRO}, ctx), ctx)
        self.assertEqual(live._gate_ctx({"user": PU, "gate": None}, ctx), ctx)
        g = live._gate_ctx({"user": PU, "gate": "makro risk-off; BTC slobodan pad"}, ctx)
        self.assertEqual((g["macro"], g["btc_state"]), (None, None))


def _row(con, user, ret, gate=None, kind="intra", var=None, now=None, gate_info=None, tok_i=1):
    now = int(now or time.time())
    con.execute("INSERT INTO veliki_trades (user, token, opened_ts, closed_ts, status, ret, pnl_usd, ret_demo, kind, "
                "gate, varijanta, gate_info) VALUES (?,?,?,?,'closed',?,?,?,?,?,?,?)",
                (user, tok(tok_i), now - 7200, now - 3600, ret, ret * 15, ret, kind, gate, var, gate_info))


class Proof(unittest.TestCase):
    def setUp(self):
        self.tmp = __import__("tempfile").TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "league.db")
        self.con = sqlite3.connect(self.path)
        live.ensure(self.con)
        self.addCleanup(self.con.close)
        self.now = time.time()

    def test_demo_stats_and_demo_proof_exclude_gated(self):
        for i in range(40):
            _row(self.con, PU, 0.02, tok_i=i)
        for i in range(10):
            _row(self.con, PU, -0.30, gate=live.GATE_MAKRO, tok_i=100 + i)
        _row(self.con, PU, 0.01, gate_info=live.GATE_MAKROINF, tok_i=200)   # real money never reads the index
        self.con.commit()
        d = live.demo_stats(self.con)
        self.assertEqual(d["n"], 41)
        self.assertAlmostEqual(d["ev_pct"], (40 * 2 + 1) / 41, places=3)
        self.assertEqual(d["u_filtru"]["n"], 10)
        self.assertAlmostEqual(d["u_filtru"]["ev_pct"], -30.0)
        self.assertTrue(gate.demo_proof(d)[0])                     # the -30 % gated trades do not decide real money
        s = live.gated_stats(self.con, PU)
        self.assertEqual(s["n"], 10)
        self.assertIn("n=10, prosjek -30.0%", live.gated_text(s))

    def test_ucenik_verdict_excludes_gated(self):
        for i in range(5):
            _row(self.con, ucenik.USER, 0.05, var="nauceno:skalp", tok_i=i)
        for i in range(3):
            _row(self.con, ucenik.USER, -0.10, gate=live.GATE_MAKRO, var="nauceno:skalp", tok_i=50 + i)
        self.con.commit()
        s = ucenik.stats(self.con, self.now)
        self.assertEqual(s["closed"]["n"], 5)
        self.assertAlmostEqual(s["closed"]["ev"], 0.05)
        self.assertEqual(s["u_filtru"]["n"], 3)
        with mock.patch.object(nauceno, "load_model", lambda **k: None), mock.patch.object(nauceno, "model_ts",
                                                                                         lambda **k: None):
            self.assertIn("u filtru tržišta (pravi novac bi stajao, izvan presude): n=3",
                          ucenik.line(self.con, self.now))

    def test_istrazivac_stats_exclude_gated(self):
        _row(self.con, istrazivac.USER, 0.04, var="sire", tok_i=1)
        _row(self.con, istrazivac.USER, -0.2, var="sire", gate=live.GATE_BTC, tok_i=2)
        _row(self.con, PU, 0.03, tok_i=3)
        _row(self.con, PU, -0.5, gate=live.GATE_MAKRO, tok_i=4)
        self.con.commit()
        s = istrazivac.stats(self.con, self.now)
        self.assertEqual(s["by"]["sire"]["n"], 1)
        self.assertEqual(s["rule"]["n"], 1)
        self.assertEqual(s["u_filtru"]["n"], 1)
        self.assertIn("u filtru tržišta", istrazivac.line(self.con, self.now))

    def test_report_midcap_strategies_exclude_gated(self):
        from report import midcap as rmid
        for i in range(3):
            _row(self.con, PU, 0.05, tok_i=i)
        _row(self.con, PU, -0.4, gate=live.GATE_MAKRO, tok_i=9)
        self.con.commit()
        p = {k: os.path.join(self.tmp.name, f"{k}.db") for k in ("trade", "veliki", "midcap", "holderi", "insajderi",
                                                                   "usage", "wallets")}
        p["league"] = self.path
        rows = rmid.strategies(self.now, p, rinfo={}, hd={}, rp={}, kp={})
        main = next(r for r in rows if r["naziv"] == "Midcap dnevni raspon" and r["vrsta"] == "demo")
        self.assertEqual(main["n"], 3)
        self.assertAlmostEqual(main["ev_pct"], 5.0)
        apart = next(r for r in rows if r["naziv"] == "Midcap dnevni raspon u filtru tržišta")
        self.assertEqual(apart["n"], 1)
        t = rmid.trading(self.now, p)
        demo = next(x for x in t["rows"] if x["racun"] == "demo" and x["pravilo"] == "intra")
        self.assertEqual(demo["7d"]["zatvoreno"], 3)
        self.assertEqual(demo["u_filtru"]["7d"]["zatvoreno"], 1)

    def test_nauceno_proof_excludes_gated_days(self):
        rows = []
        t0 = int(self.now) // D * D - 6 * D
        for d in range(6):
            for k, (mk, ret) in enumerate((("neutral", 0.02), ("risk_off/x", -0.2))):
                ts = t0 + d * D + 3600 + k
                rows.append({"token": tok(k), "opened_ts": ts, "closed_ts": ts + 600, "profil": "skalp", "ret": ret,
                             "band": "dno", "calm": 1, "zone_ok": 1, "btc": "normalno", "makro": mk})
        res = nauceno.learn(rows, min_train_days=1, thr=-1.0)
        self.assertEqual(res["picked"]["n"], 5)                    # 5 scored days x the ungated candidate
        self.assertAlmostEqual(res["picked"]["ev"], 0.02)
        self.assertEqual(res["u_filtru"]["picked"]["n"], 5)
        self.assertEqual(res["all"]["n"], 5)
        self.assertTrue(nauceno.gated({"makro": "risk_off"}))
        self.assertTrue(nauceno.gated({"btc": "slobodan_pad"}))
        self.assertFalse(nauceno.gated({"makro": "neutral", "btc": "normalno"}))
        res["ts"] = int(self.now)
        self.assertIn("u filtru tržišta (risk-off / BTC slobodan pad", nauceno.line(res))


class Makroinf(unittest.TestCase):
    def test_bearish_index_tags_instead_of_skipping(self):
        with mock.patch.object(makro, "demo_index", lambda now=None: (True, "indeks -0,8", "paper")):
            out = []
            self.assertEqual(live._makroinf_blocks(time.time(), out), live.GATE_MAKROINF)
        with mock.patch.object(makro, "demo_index", lambda now=None: (True, "indeks -0,8", "shadow")):
            self.assertIsNone(live._makroinf_blocks(time.time(), []))
        with open(os.path.join(ROOT, "veliki", "live.py"), encoding="utf-8") as f:
            src = f.read()
        i = src.index("mi = _makroinf_blocks(now, out)")
        self.assertNotIn("continue", src[i:i + 300].split("_try_enter")[0])   # never skips the entry any more


class RealUnchanged(unittest.TestCase):
    """Nothing added here can place a real order; the real-money switches, the pause and the gate are untouched."""

    def test_no_order_path_and_untouched_controls(self):
        with open(os.path.join(ROOT, "veliki", "live.py"), encoding="utf-8") as f:
            src = f.read()
        for bad in ("executor.buy", "executor.swap", "pravi_novac_pauza", "pauza_set", "set_flag", "STOP_FILE"):
            self.assertNotIn(bad, src)
        for rel in (("veliki", "istrazivac.py"), ("veliki", "sjena.py"),
                    ("veliki", "nauceno.py")):
            with open(os.path.join(ROOT, *rel), encoding="utf-8") as f:
                other = f.read()
            for bad in ("executor.buy", "executor.swap", "pauza_set", "set_flag"):
                self.assertNotIn(bad, other, rel)
        from trade import settings
        self.assertEqual(settings.PAUZA_KEY, "pravi_novac_pauza")
        self.assertIn("insajderi2", settings.NEVER_LIVE)            # the wallet demo stays demo-only
        self.assertEqual(gate.REAL, {"size_sol": 0.1, "max_open": 5, "max_buys_day": 20, "max_loss_day_sol": 0.3})
        self.assertEqual(live.market_gates("risk_off", "slobodan_pad"), [live.GATE_MAKRO, live.GATE_BTC])
        self.assertEqual(live.market_gates("neutral", "normalno"), [])

    def test_btc_refusal_still_holds_the_real_gate(self):
        with mock.patch.object(live, "btc_state", free_fall_state), \
                mock.patch.object(gate, "switch_on", lambda con=None: True), \
                mock.patch.object(gate, "proof_mode", lambda cfg=None, con=None: "nalog_vlasnika"):
            self.assertIn("BTC slobodan pad", gate.real_refusal())


class WalletDemo(unittest.TestCase):
    """The wallet-following demo (insajderi/pp_live "autopilot-novcanici", insajderi/live, wallets/kopija_demo) has no
    market gate: nothing in its entry path reads the macro regime, BTC's state or the real-money gate."""

    def test_no_market_gate_in_the_wallet_demos(self):
        for rel in (("insajderi", "pp_live.py"), ("insajderi", "live.py"), ("wallets", "kopija_demo.py")):
            with open(os.path.join(ROOT, *rel), encoding="utf-8") as f:
                src = f.read()
            for word in ("makro", "risk_off", "btc_state", "slobodan_pad", "real_gate", "regime"):
                self.assertNotIn(word, src, rel)


if __name__ == "__main__":
    unittest.main()
