"""1.11. "Prijedlozi za bolji algoritam": hard rug gate, $100k A/B, 3-KOL trigger, stake per session, exit
simulation closer to reality.

    python3 -m unittest tests.test_paper_rules_offline
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_paper  # noqa: E402
from exits import fit, learn  # noqa: E402
from learn import weights  # noqa: E402
from paper import rules, sim, store  # noqa: E402

PUMP = "So1aNaMintAddrXXXXXXXXXXXXXXXXXXXXXXXXpump"
MOON = "So1aNaMintAddrXXXXXXXXXXXXXXXXXXXXXXXXmoon"


class Gate(unittest.TestCase):
    def test_reasons(self):
        ok = rules.gate(PUMP, 0.0001, 20_000, 100_000, "prolaz", {}, {})
        self.assertIsNone(ok)
        self.assertIn("likvidnost", rules.gate(PUMP, 0.0001, 5_000, 100_000, "prolaz", {}, {}))
        # 1.11. night: pool bigger than the token (liq $120k, mcap $70k) -> fake pool
        self.assertIn("lažni pool", rules.gate(MOON, 0.08, 120_500, 69_900, "prolaz", {}, {}))
        self.assertIn("tokenizirana", rules.gate(MOON, 412.0, 50_000, 900_000, "prolaz", {}, {}))
        self.assertIn("T0", rules.gate(PUMP, 0.0001, 20_000, 100_000, "nije", {}, {}))
        self.assertIn("izvan pump", rules.gate(MOON, 0.0001, 20_000, 100_000, None, {}, {}))
        self.assertIsNone(rules.gate(PUMP, 0.0001, 20_000, 100_000, None, {}, {}))  # pump.fun: authorities revoked
        self.assertIn("volumen", rules.gate(PUMP, 0.0001, 20_000, 100_000, "prolaz", {"snaga_volumen": 0.1}, {}))
        self.assertIsNone(rules.gate(MOON, 0.0001, 1, 100_000, None, {}, {"rules": {"gate": {"enabled": False}}}))

    def test_high_risk_gets_small_stake(self):
        self.assertEqual(rules.high_risk_size("VISOK RIZIK", 50, 20), 20)
        self.assertEqual(rules.high_risk_size("PROLAZI", 50, 20), 50)

    def test_featured_list_needs_t0_and_volume(self):
        from ui import sansa
        full = [(lab, True, "") for lab in sansa.LAYERS]
        base = {"checks": full, "razina": 1, "hard": False}
        self.assertTrue(sansa.featured_ok(base))
        self.assertFalse(sansa.featured_ok({**base, "tier": {"t0": "nije"}}))
        self.assertFalse(sansa.featured_ok({**base, "features": {"snaga_volumen": 0.15}}))
        self.assertTrue(sansa.featured_ok({**base, "features": {"snaga_volumen": 0.5}, "tier": {"t0": "prolaz"}}))


def _trade(con, mode, ret, ts, sl=-0.15, reason="stop_loss", tp_done=0):
    cur = con.execute("INSERT INTO trades (token, symbol, opened_ts, closed_ts, status, exit_reason, size_usd, ret, "
                      "pnl_usd, state, config) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (f"t{ts}{mode}{ret}", "S", int(ts), int(ts) + 60, "closed", reason, 20, ret, ret * 20,
                       json.dumps({"fills": [], "tp_done": tp_done}), json.dumps({"entry_mode": mode, "sl": sl})))
    return cur.lastrowid


class Learned(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._ld, weights.LEARNED_DIR = weights.LEARNED_DIR, self.tmp
        self.db = os.path.join(self.tmp, "paper.db")
        self.con = store.connect(self.db)

    def tearDown(self):
        self.con.close()
        weights.LEARNED_DIR = self._ld

    def test_session_stake_pauses_at_once_and_comes_back_one_step_a_day(self):
        # 5.11. morning report: Asia (PF 0.27) and US (0.32) were paused, Europe (PF 0.17, 64 trades) still traded at
        # 50-75% because a worse result moved one step a day. Now down is at once, up one step a day.
        now = 1_762_000_000 - (1_762_000_000 % 86400) + 20 * 3600  # 20:00 UTC (us)
        eu = now - 9 * 3600  # 11:00 UTC
        for i in range(40):  # Europe: 40% wins at +20%, losses -20% -> profit factor 0.67 (< pause_below 0.7)
            _trade(self.con, "explore", 0.2 if i % 5 < 2 else -0.2, eu - i * 60)
        self.con.commit()
        st = {"sessions": {"ts": now - 3600, "by": {"eu": {"factor": 0.75}}}}   # old state (v1): re-read now
        s1 = rules.session_sizes(self.con, st, {}, now)
        self.assertEqual(s1["by"]["eu"]["factor"], 0.0)   # straight to pause, as Asia and US
        self.assertEqual(s1["by"]["us"]["factor"], 1.0)   # too few trades: full stake
        self.assertEqual(rules.session_sizes(self.con, st, {}, now + 3600)["by"]["eu"]["factor"], 0.0)  # cached
        size, note = rules.size_for(st, "abc", 20, eu + 86400, {})
        self.assertIn(size, (0, 10.0))
        self.assertIn("pauzi", note)
        self.assertTrue(any("Europa" in h["text"] for h in st["history"]))
        for i in range(60):  # Europe recovers: PF well over 1 -> back up one step a day
            _trade(self.con, "explore", 0.5, eu + 3600 + i * 60)
        self.con.commit()
        s2 = rules.session_sizes(self.con, st, {}, now + 86400 + 1, force=True)
        self.assertEqual(s2["by"]["eu"]["factor"], 0.5)
        s3 = rules.session_sizes(self.con, st, {}, now + 2 * 86400 + 2, force=True)
        self.assertEqual(s3["by"]["eu"]["factor"], 0.75)

    def test_same_threshold_for_every_session(self):
        now = 1_762_000_000 - (1_762_000_000 % 86400) + 23 * 3600
        day0 = now - 23 * 3600
        for s_h in (2, 10, 18):   # asia, eu, us: the same losing record in each
            for i in range(35):
                _trade(self.con, "explore", 0.1 if i % 5 == 0 else -0.2, day0 + s_h * 3600 + i * 60)
        self.con.commit()
        by = rules.session_sizes(self.con, {}, {}, now)["by"]
        self.assertEqual({s: v["factor"] for s, v in by.items()}, {"asia": 0.0, "eu": 0.0, "us": 0.0})

    def test_ab_switches_to_the_better_entry_and_keeps_measuring(self):
        now = 1_762_000_000
        st = {"since": {"ab": now - 10 * 86400}}
        for i in range(40):
            _trade(self.con, "explore", -0.3 if i % 3 else 0.2, now - 9 * 86400 + i * 3600)
            _trade(self.con, "mc100k", 0.4 if i % 2 else -0.1, now - 9 * 86400 + i * 3600 + 1)
        self.con.commit()
        ab = rules.ab_judge(self.con, st, {}, now)
        self.assertEqual(ab["winner"], "B")
        self.assertEqual(ab["A"]["n"], 40)
        self.assertTrue(rules.ab_allow(st, "mc100k", "x", {}))
        kept = sum(rules.ab_allow(st, "explore", f"tok{i}", {}) for i in range(400))
        self.assertTrue(40 < kept < 160)  # ~25 % of the losing side still trades

    def test_rug_share_and_gate_shadow(self):
        start = 1_762_000_000
        _trade(self.con, "explore", -1.0, start - 3600, reason="rug")
        _trade(self.con, "explore", 0.1, start - 1800, reason="trailing")
        _trade(self.con, "explore", 0.1, start + 1800, reason="trailing")
        store.add_candidate(self.con, {"token": "G", "ts": start + 10, "origin": "hype", "price": 1.0,
                                       "decision": "skip_gate"})
        store.tick(self.con, "G", start + 600, 0.1, 0, 0)
        self.con.commit()
        r = {x["label"]: x for x in rules.rug_share(self.con, start)}
        self.assertEqual((r["prije filtra"]["n"], r["prije filtra"]["rugs"]), (2, 1))
        self.assertEqual((r["nakon filtra"]["n"], r["nakon filtra"]["rugs"]), (1, 0))
        self.assertEqual(rules.gate_shadow(self.con, start), {"n": 1, "collapsed": 1, "share": 1.0})

    def test_reality_measured_from_live_stops(self):
        for i in range(25):
            _trade(self.con, "explore", -0.2 if i % 5 else -0.6, 1_762_000_000 + i)
        self.con.commit()
        r = fit.reality(self.db, {"reality_min_n": 20})
        self.assertTrue(r["measured"])
        self.assertAlmostEqual(r["p_caught"], 0.8)
        self.assertAlmostEqual(r["gap"], -0.05, places=3)


class Kol3(unittest.TestCase):
    def test_three_authors_in_fifteen_minutes_bots_excluded(self):
        tmp = tempfile.mkdtemp()
        db = os.path.join(tmp, "kol.db")
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE calls (token TEXT, handle TEXT, ts INTEGER, kind TEXT)")
        con.execute("CREATE TABLE kols (handle TEXT, bot INTEGER)")
        con.execute("INSERT INTO kols VALUES ('blossomscanner', 1)")
        now = 1_762_000_000
        rows = [("T", "a", now - 600), ("T", "b", now - 400), ("T", "c", now - 100),  # 3 authors in 8 min
                ("U", "a", now - 300), ("U", "blossomscanner", now - 200), ("U", "b", now - 100),  # bot: only 2
                ("V", "a", now - 1500), ("V", "b", now - 1400), ("V", "c", now - 1300)]  # too old
        con.executemany("INSERT INTO calls VALUES (?,?,?,'call')", rows)
        con.commit()
        con.close()
        got = rules.kol3(db, now, {})
        self.assertEqual(set(got), {"T"})
        self.assertEqual(got["T"]["n"], 3)


class Triggers(unittest.TestCase):
    """B of the A/B ($100k crossing) and the 3-KOL trigger open their own small demo trades through the gate."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._ld, weights.LEARNED_DIR = weights.LEARNED_DIR, self.tmp
        self.saved = {k: getattr(run_paper, k) for k in ("DB", "HYPE_DB", "HERE", "market", "rug_verdict", "notify",
                                                          "t0_check")}
        run_paper.DB = os.path.join(self.tmp, "paper.db")
        run_paper.HYPE_DB = os.path.join(self.tmp, "hype.db")
        run_paper.HERE = self.tmp
        self.now = time.time()
        from tiers import store as tstore
        h = tstore.connect(run_paper.HYPE_DB)
        tstore.upsert(h, PUMP, self.now, symbol="GOOD", t0="prolaz")
        tstore.upsert(h, MOON, self.now, symbol="FAKE", t0="prolaz")
        tstore.record_event(h, PUMP, "B100000", 101_000, 0.0001, 30, {}, self.now - 120)
        tstore.record_event(h, MOON, "B100000", 101_000, 0.08, 30, {}, self.now - 120)
        h.commit()
        h.close()
        mk = {PUMP: (0.0001, 30_000, 101_000, None), MOON: (0.08, 120_000, 101_000, None)}
        run_paper.market = lambda toks: {t: mk[t] for t in toks if t in mk}
        run_paper.rug_verdict = lambda con, t, cfg, now, paid=True: (None, None, [])
        run_paper.notify = lambda *a, **k: None
        run_paper.t0_check = lambda t, now: "prolaz"

    def tearDown(self):
        weights.LEARNED_DIR = self._ld
        for k, v in self.saved.items():
            setattr(run_paper, k, v)

    def test_mc100k_entry_and_fake_pool_refused(self):
        cfg = {**sim.load_config(), "explore": {"enabled": False}, "konv": {"enabled": False}}
        opened = run_paper.intake(cfg, now=self.now, quiet=True)
        self.assertEqual([c["token"] for c in opened], [PUMP])
        con = store.connect(run_paper.DB)
        conf = json.loads(con.execute("SELECT config FROM trades").fetchone()[0])
        self.assertEqual(conf["entry_mode"], "mc100k")
        self.assertEqual(con.execute("SELECT decision FROM candidates WHERE token=?", (MOON,)).fetchone()[0], "skip_gate")
        self.assertEqual(run_paper._n_open(con), 0)  # own cap, not a core slot
        self.assertEqual(run_paper.intake(cfg, now=self.now + 60, quiet=True), [])  # once per token
        con.close()


class Reentry(unittest.TestCase):
    def test_second_crossing_after_a_dip(self):
        """1.11. pairless: out at +16% at $133k, fell to ~$73k, then crossed $100k again on the way past $1M."""
        tmp = tempfile.mkdtemp()
        con = store.connect(os.path.join(tmp, "paper.db"))
        now = 1_762_000_000
        con.execute("INSERT INTO trades (token, opened_ts, closed_ts, status, config) VALUES "
                    "('P', ?, ?, 'closed', ?)", (now - 7200, now - 6000, json.dumps({"entry_mode": "mc100k"})))
        for i, mc in enumerate([133e3, 90e3, 73e3, 85e3, 98e3]):
            store.tick(con, "P", now - 5000 + i * 600, 1, 1, mc)
        con.commit()
        self.assertEqual(run_paper.reentries(con, 1e5, now), {})  # still below
        store.tick(con, "P", now - 10, 1, 1, 104e3)
        got = run_paper.reentries(con, 1e5, now)
        self.assertEqual(set(got), {"P"})
        self.assertEqual(got["P"]["low"], 73e3)
        con.execute("INSERT INTO trades (token, opened_ts, status, config) VALUES ('P', ?, 'closed', ?)",
                    (now, json.dumps({"entry_mode": "mc100k2"})))
        self.assertEqual(run_paper.reentries(con, 1e5, now), {})  # once per token
        con.close()


class ExitReality(unittest.TestCase):
    CFG = {"fee": 0.01, "slip": 0.0, "sl": -0.15, "tp": [[1.0, 0.5]], "trail_after": 0.5, "trail": 0.3,
           "max_hold_h": 24, "rug_liq": 0.2, "size_usd": 1}

    def test_coarse_stop_fills_near_the_stop(self):
        path = [(600, 1.02, 50_000), (4200, 0.2, 50_000)]  # one hour later -80%: retro data gap
        raw = sim.replay(1.0, 50_000, 0, path, self.CFG)
        c = {**self.CFG, "coarse": {"secs": 300, "p_caught": 0.7, "gap": -0.05}}
        real = sim.replay(1.0, 50_000, 0, path, c)
        self.assertLess(raw["ret"], -0.75)
        self.assertGreater(real["ret"], -0.45)  # 0.7 x -20% + 0.3 x -80% = -38%, plus fees
        fine = [(600, 1.02, 50_000), (660, 0.2, 50_000)]  # a minute later: a real one-candle dump, no help
        self.assertLess(sim.replay(1.0, 50_000, 0, fine, c)["ret"], -0.75)

    def test_slippage_costs(self):
        a = sim.replay(1.0, 50_000, 0, [(60, 1.5, 50_000)], {**self.CFG, "max_hold_h": 0})
        b = sim.replay(1.0, 50_000, 0, [(60, 1.5, 50_000)], {**self.CFG, "max_hold_h": 0, "slip": 0.02})
        self.assertLess(b["ret"], a["ret"] - 0.03)

    def test_live_weight_and_few_big_hits_guard(self):
        ps = [{"src": "seed"}] * 90 + [{"src": "live"}] * 10
        w = learn.live_weights(ps, {"live_share": 0.5, "live_w_max": 10})
        self.assertAlmostEqual(sum(x for x, p in zip(w, ps) if p["src"] == "live") / sum(w), 0.5)
        self.assertIsNone(learn.live_weights([{"src": "seed"}] * 5, {}))
        # without_top drops the paths the rules made most on
        paths = [{"src": "seed", "ts": i, "liq0": 50_000, "pts": [[60, 1 + (25 if i < 3 else 0.01), 50_000]]}
                 for i in range(100)]
        rest = learn.without_top(paths, {**self.CFG, "max_hold_h": 0}, {"robust_top": 0.01, "robust_min": 3})
        self.assertEqual(len(rest), 97)
        self.assertTrue(all(p["ts"] >= 3 for p in rest))


class Report(unittest.TestCase):
    def test_morning_report_section(self):
        from report import ai, collect, render
        tmp = tempfile.mkdtemp()
        old = {k: os.environ.get(k) for k in ("REPORT_DB_DIR", "LEARNED_DIR")}
        os.environ["REPORT_DB_DIR"] = os.environ["LEARNED_DIR"] = tmp
        try:
            d = collect.collect()
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        d["rules"] = {"rug": [{"label": "prije filtra", "n": 10, "rugs": 4, "share": 0.4},
                              {"label": "nakon filtra", "n": 5, "rugs": 0, "share": 0.0}],
                      "gate": {"n": 7, "collapsed": 5, "share": 0.7}, "refused_day": 7,
                      "kol3": {"eu": {"n": 3, "win": 0.33, "mean": 0.1}},
                      "kol3_10": {"10": {"n": 4, "win": 0.5, "mean": 0.1, "median": 0.05}},
                      "ab": {"A": {"n": 3, "mean": -0.1}, "B": {"n": 1, "mean": 0.2}, "winner": None},
                      "sessions": {"eu": {"factor": 0.75}}, "history": [{"text": "Europa: ulog 75%"}]}
        out = render.render(d, ai.fallback(d), "pravila")
        self.assertIn("Nova pravila ulaza", out)
        self.assertIn("Filtar je odbio 7 tokena", out)
        self.assertIn("Europa ulog 75%", out)
        self.assertIn("Grupni poziv 3+ autora: unutar 10 min 4 zatvorenih", out)


if __name__ == "__main__":
    unittest.main()
