"""15.11. (vlasnik: "hitno pronađi profitabilnu strategiju kombiniranjem profitabilnih novčanika i influencera ...
pozadinu ostavi za demo"): konsenzus/ (the source consensus strategy) on synthetic data, no network.

  - the rolling source score uses only results known before the moment it is used (no look-ahead)
  - correlated sources (a corr cluster / owner group) count as one; consensus needs two DIFFERENT groups in the window
  - the holdout is untouched: changing the holdout days' results never changes what is chosen
  - costs and stop slippage are always in the result
  - the proof gate keeps real money off without proof; the switch off means never a real buy (konsenzus/live and
    run_trade both); with the switch on and the proof the real buy goes through IZVORI_CAPS
  - a fresh live signal of a selected source opens a DEMO entry with its stop and plan
  - the owner order puts the flag in paper and never turns pravi_novac_izvori on

    python3 -m unittest tests.test_konsenzus_offline
"""
import os
import random
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from izlazi import sim  # noqa: E402
from konsenzus import gate, live, research as R, store as kstore  # noqa: E402
from league import exitplan  # noqa: E402
from tests.test_pravi_novac_sve_offline import LU, PU, SwitchBase, tok  # noqa: E402
from trade import settings  # noqa: E402

NOW = 1794700000


def bars(up, n=120, seed=0, vol=0.004):
    rnd = random.Random(seed)
    out, px = [], 1.0
    for k in range(1, n):
        px *= 1 + up / n + rnd.gauss(0, vol)
        out.append((k * 60, px * 1.01, px * 0.99, px))
    return out


def entry(src, token, sig_ts, up=0.0, kind=None, seed=0, cost=0.03):
    b = sim.fit(bars(up, seed=seed))
    return {"kind": kind or ("wallet" if len(src) >= 32 else "kol"), "src": src, "tok": token, "ts": sig_ts + 60,
            "arrs": sim.pack(b), "cover": b[-1][0], "cost": cost, "sell_s": None, "rug_s": None, "how": "syn",
            "stats": None, "sig_ts": sig_ts, "lag": 60, "mcap": 60_000, "liq": 25_000}


def token(i):
    return f"T{i:05d}" + "x" * 38


def synthetic(days=30, per_day=40, good=("@a", "@b", "tg:c"), seed=3):
    rnd = random.Random(seed)
    srcs = [f"@k{i}" for i in range(20)] + [f"tg:t{i}" for i in range(8)] + ["W" * 40 + str(i) for i in range(8)]
    srcs += list(good)
    out, n = [], 0
    for d in range(days):
        for j in range(per_day):
            s = rnd.choice(srcs)
            t = NOW - (days - d) * 86400 + j * 1800
            out.append(entry(s, token(n), t, up=0.35 if s in good else -0.05, seed=n))
            n += 1
    return out


class Score(unittest.TestCase):
    def evs(self):
        es = [entry("@a", token(i), NOW - 10 * 86400 + i * 3600, up=0.4, seed=i) for i in range(12)]
        return R.make_events(es, R.Groups(), 0.08)

    def test_no_look_ahead(self):
        evs = self.evs()
        cut = evs[6]["ts"]
        before = R.scores_at(evs, cut)
        for ev in evs:   # results of everything not yet known at the cut become absurd: the score must not move
            if ev["known"] > cut or ev["ts"] >= cut:
                ev["r"] = 50.0
        self.assertEqual(before, R.scores_at(evs, cut))
        later = R.scores_at(evs, evs[-1]["ts"] + 86400)
        self.assertGreater(later["a"][0], before["a"][0])

    def test_score_is_shrunk_and_needs_known_results(self):
        es = [entry("@a", token(i), NOW - 10 * 86400 + i * 3600, up=0.4, seed=i) for i in range(12)]
        es += [entry("@z", token(100 + i), NOW - 10 * 86400 + i * 3600, up=-0.2, seed=i) for i in range(12)]
        evs = R.make_events(es, R.Groups(), 0.08)
        self.assertEqual(R.scores_at(evs, evs[0]["ts"]), {})
        sc = R.scores_at(evs, evs[-1]["ts"] + 86400)
        raw = sum(ev["r"] for ev in evs if ev["src"] == "a") / 12
        self.assertLess(sc["a"][0], raw)   # pulled toward the kind's mean (the bad one included)
        self.assertGreater(sc["a"][0], sc["z"][0])
        self.assertEqual(sc["a"][1], 12)


class GroupsAndConsensus(unittest.TestCase):
    def test_cluster_counts_once(self):
        g = R.Groups()
        g.join(["@A", "@b"])   # one corr cluster
        self.assertEqual(g.of("a"), g.of("@B"))
        es = [entry("@a", token(1), NOW), entry("@b", token(1), NOW + 60), entry("@c", token(1), NOW + 120)]
        evs = R.make_events(es, g, 0.08)
        self.assertEqual(len(evs), 2)   # @b's signal is an echo of its group
        sel = lambda ev: None   # noqa: E731 - any group
        picks = R.pick(evs, "S2", {"w": 30}, sel)
        self.assertEqual(len(picks), 1)
        self.assertEqual(picks[0][0]["src"], "c")   # the entry is the second INDEPENDENT group's
        only_cluster = R.make_events(es[:2], g, 0.08)
        self.assertEqual(R.pick(only_cluster, "S2", {"w": 30}, sel), [])

    def test_consensus_window(self):
        es = [entry("@a", token(1), NOW), entry("@c", token(1), NOW + 29 * 60),
              entry("@a", token(2), NOW), entry("@c", token(2), NOW + 31 * 60)]
        evs = R.make_events(es, R.Groups(), 0.08)
        got = R.pick(evs, "S2", {"w": 30}, lambda ev: None)
        self.assertEqual([p[0]["tok"] for p in got], [token(1)])

    def test_cross_type_needs_a_wallet_and_a_caller(self):
        w = "W" * 44
        es = [entry("@a", token(1), NOW), entry("@c", token(1), NOW + 60),
              entry("@a", token(2), NOW), entry(w, token(2), NOW + 60)]
        evs = R.make_events(es, R.Groups(), 0.08)
        got = R.pick(evs, "S3", {"w": 60}, lambda ev: None)
        self.assertEqual([p[0]["tok"] for p in got], [token(2)])

    def test_live_decide_same_rules(self):
        spec = {"family": "S2", "params": {"w": 30}, "selection": {"members": {"a": "g:a", "b": "g:a", "c": "c"},
                                                                  "any": False}}
        sigs = [{"ts": NOW - 100, "token": token(1), "src": "a", "kind": "x"},
                {"ts": NOW - 50, "token": token(1), "src": "b", "kind": "x"}]
        self.assertEqual(live.decide(spec, sigs, NOW), [])   # one group only
        sigs.append({"ts": NOW - 20, "token": token(1), "src": "c", "kind": "tg"})
        got = live.decide(spec, sigs, NOW)
        self.assertEqual([(g[0], g[1]) for g in got], [(token(1), NOW - 20)])
        self.assertEqual(live.decide(spec, sigs, NOW + live.FRESH_S + 60), [])   # stale: no entry
        spec1 = {"family": "S1", "params": {"k": 10}, "selection": {"members": {"a": "g:a"}, "any": False}}
        self.assertEqual([g[0] for g in live.decide(spec1, sigs, NOW)], [token(1)])
        self.assertEqual(live.decide(spec1, [s for s in sigs if s["src"] == "c"], NOW), [])   # not selected


class Earlier(unittest.TestCase):
    def test_repeat_call_is_no_signal(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as d:
            kp, hp, tp = (os.path.join(d, n) for n in ("kol.db", "hype.db", "tg.db"))
            k = sqlite3.connect(kp)
            k.execute("CREATE TABLE calls (token TEXT, ts INTEGER, handle TEXT, kind TEXT)")
            k.execute("INSERT INTO calls VALUES (?,?,?,?)", (token(1), NOW - 3600, "Alice", "call"))
            k.commit()
            k.close()
            h = sqlite3.connect(hp)
            h.execute("CREATE TABLE chain_trades (wallet TEXT, mint TEXT, side TEXT, ts INTEGER)")
            h.execute("INSERT INTO chain_trades VALUES (?,?,?,?)", ("W" * 44, token(2), "buy", NOW - 600))
            h.commit()
            h.close()
            t = sqlite3.connect(tp)
            t.execute("CREATE TABLE posts (channel TEXT, ts INTEGER, cas TEXT, fwd_from TEXT)")
            t.execute("INSERT INTO posts VALUES (?,?,?,?)", ("Chan", NOW - 900, token(3), None))
            t.commit()
            t.close()
            p = {"kol": kp, "hype": hp, "tg": tp}
            self.assertTrue(live.earlier("alice", "x", token(1), NOW, p))
            self.assertFalse(live.earlier("alice", "x", token(4), NOW, p))
            self.assertTrue(live.earlier("W" * 44, "wallet", token(2), NOW, p))
            self.assertTrue(live.earlier("tg:chan", "tg", token(3), NOW, p))
            self.assertFalse(live.earlier("tg:chan", "tg", token(3), NOW - 1000, p))
            sigs = live.read_signals(NOW, 7200, p)
            self.assertEqual({(s["src"], s["kind"]) for s in sigs}, {("alice", "x"), ("W" * 44, "wallet"),
                                                                       ("tg:chan", "tg")})


class Costs(unittest.TestCase):
    def test_flat_path_loses_cost_and_rising_path_pays_it(self):
        e = entry("@a", token(1), NOW, up=0.0, cost=0.04)
        e["arrs"] = sim.pack([(k * 60, 1.0, 1.0, 1.0) for k in range(1, 100)])
        for ex in R.EXITS:
            self.assertAlmostEqual(R.exit_result(e, ex, 0.08), -0.04 - R.SLIP_MKT, places=6)
        e["arrs"] = sim.pack([(60, 1.0, 0.85, 0.86)])   # a gap through the -10 % stop: the slippage on top
        self.assertLess(R.exit_result(e, "E", 0.08), -0.10 - 0.04 - 0.07)

    def test_slippage_never_under_the_floor(self):
        self.assertEqual(R.slip_of({"costs": {"slip_stop_pct": 2.0}}), R.SLIP_STOP_MIN)
        self.assertEqual(R.slip_of({"costs": {"slip_stop_pct": 12.0}}), 0.12)


class Walk(unittest.TestCase):
    def test_holdout_is_untouched_and_planted_edge_found(self):
        es = synthetic()
        evs = R.make_events(es, R.Groups(), 0.08)
        w1 = R.walk(evs, 0.08)
        chosen1 = {f: c["key"] for f, c in w1["chosen"].items()}
        hold = set(w1["days"]["holdout"])
        self.assertTrue(hold and not hold & set(w1["days"]["train"]))
        real = R.exit_result

        def fake(e, ex, slip):   # the holdout days' results turned upside down
            return 9.0 if R.day_of(e["ts"]) in hold else real(e, ex, slip)
        with mock.patch.object(R, "exit_result", fake):
            evs2 = R.make_events(es, R.Groups(), 0.08)
            w2 = R.walk(evs2, 0.08)
        self.assertEqual(chosen1, {f: c["key"] for f, c in w2["chosen"].items()})
        self.assertNotEqual(w1["chosen"]["S1"]["holdout"].get("ev_pct"), w2["chosen"]["S1"]["holdout"].get("ev_pct"))
        h = w1["chosen"]["S1"]["holdout"]
        self.assertGreater(h["n"], 0)
        self.assertGreater(h["ev_pct"], 0)   # the planted good sources are found out of sample
        base = next(c for c in w1["configs"] if c["family"] == R.BASELINE and c["exit"] == "E")
        self.assertLess(base["holdout"]["ev_pct"], h["ev_pct"])

    def test_run_writes_db_md_and_lines(self):
        es = synthetic(days=20, per_day=30)
        with tempfile.TemporaryDirectory() as d:
            lines = []
            with mock.patch.object(R, "write_md", lambda data, path=None: None):
                data = R.run(now=NOW, log=lines.append, path=os.path.join(d, "k.db"), entries=es, meta={},
                             groups=R.Groups(), ginfo={})
            b = kstore.best(os.path.join(d, "k.db"), cached=False)
            self.assertTrue(b and b["selection"]["members"])
            self.assertIn("holdout", data["chosen"][b["family"]])
            self.assertTrue(any(s.startswith("konsenzus: S") and "holdout n=" in s for s in lines))
            self.assertTrue(any("najbolji kandidat" in s for s in lines))
            self.assertIn("# Konsenzus izvora", R.markdown(data))


class Proof(unittest.TestCase):
    def test_holdout_proof(self):
        ok, why = gate.holdout_proof([0.1] * 10, {"n": 10, "ev_pct": 10, "ci_lo_pct": 5})
        self.assertFalse(ok)
        self.assertIn("30", why)
        rets = [0.08 + 0.01 * (i % 3) for i in range(40)]
        self.assertTrue(gate.holdout_proof(rets, {"n": 40, "ev_pct": 9, "ci_lo_pct": 8})[0])
        self.assertFalse(gate.holdout_proof(rets, {"n": 40, "ev_pct": 2.0, "ci_lo_pct": 1})[0])
        self.assertFalse(gate.holdout_proof(rets, {"n": 40, "ev_pct": 9, "ci_lo_pct": -0.5})[0])


SPEC = {"key": "S1:k10:E", "family": "S1", "params": {"k": 10}, "exit": "E", "proof_ok": True, "proof_why": "ok",
        "exit_params": sim.as_dict(R.EXITS["E"]["p"]), "tp_gross": True, "exit_words": R.EXITS["E"]["words"],
        "selection": {"members": {"a": "a"}, "groups": {"a": {}}, "any": False}}


class Live(SwitchBase):
    def setUp(self):
        super().setUp()
        self.flag("konsenzus", "paper")
        live._TRIED.clear()
        live._LAST["ts"] = 0.0

    def sigs(self, t, age=20):
        return [{"ts": int(self.now - age), "token": t, "src": "a", "kind": "x"}]

    def go(self, spec, t, **kw):
        mk = lambda toks: {x: self.quote["row"] for x in toks}   # noqa: E731
        return live.run_once(self.lg, market_fn=mk, now=self.now, spec=spec, sigs=self.sigs(t, **kw), sol=150.0,
                             force=True)

    def users(self, t):
        return sorted(u for (u,) in self.lg.execute("SELECT user FROM konsenzus_trades WHERE token=?", (t,)))

    def test_demo_entry_on_a_live_signal_with_stop_and_plan(self):
        got = self.go(SPEC, tok(1))
        self.assertEqual([u for u, _t in got], [PU])
        tr = self.lg.execute("SELECT auto, source FROM trades WHERE user=? AND token=?", (PU, tok(1))).fetchone()
        self.assertIn('"sl_px"', tr[0])
        self.assertTrue(tr[1].startswith("konsenzus"))
        p = exitplan.active(self.lg, tok(1))
        self.assertIsNotNone(p)
        self.assertTrue(exitplan.quick_live(p, PU))
        self.assertEqual(self.go(SPEC, tok(1)), [])   # the first entry per token only

    def test_flag_off_no_entry(self):
        self.flag("konsenzus", "shadow")
        self.assertEqual(self.go(SPEC, tok(2)), [])

    def test_stale_signal_no_entry(self):
        self.assertEqual(self.go(SPEC, tok(3), age=live.FRESH_S + 30), [])

    def test_switch_off_never_real_even_with_proof(self):
        self.go(SPEC, tok(4))
        self.assertEqual(self.users(tok(4)), [PU])

    def test_switch_on_without_proof_stays_demo(self):
        settings.set_flag(self.con, gate.SWITCH, "live", "Jure")
        settings._FLAG_CACHE.clear()
        self.go(dict(SPEC, proof_ok=False, proof_why="holdout ima 3"), tok(5))
        self.assertEqual(self.users(tok(5)), [PU])

    def test_switch_on_with_proof_real_entry_and_izvori_caps(self):
        settings.set_flag(self.con, gate.SWITCH, "live", "Jure")
        settings._FLAG_CACHE.clear()
        self.go(SPEC, tok(6))
        self.assertEqual(self.users(tok(6)), sorted([LU, PU]))
        with tempfile.TemporaryDirectory() as d:
            kp = os.path.join(d, "k.db")
            con = kstore.connect(kp)
            kstore.save(con, {}, SPEC, NOW)
            con.close()
            kstore._CACHE.clear()
            with mock.patch.dict(os.environ, {"KONSENZUS_DB": kp}):
                self.mirror()
            kstore._CACHE.clear()
        r = self.con.execute("SELECT status, mode, sol_in, reason FROM positions WHERE token=?", (tok(6),)).fetchone()
        self.assertEqual(r[:2], ("open", "live"))
        self.assertAlmostEqual(r[2], 0.1)
        self.assertTrue(self.swaps and self.swaps[-1]["cap"] <= 6.0)

    def test_wallet_heavy_holdout_also_needs_the_demo(self):
        settings.set_flag(self.con, gate.SWITCH, "live", "Jure")
        settings._FLAG_CACHE.clear()
        spec = dict(SPEC, holdout={"n": 40, "ev_pct": 8, "ci_lo_pct": 3, "wallet_share": 0.6})
        self.assertIn("demo", gate.real_refusal(spec) or "")
        self.go(spec, tok(8))
        self.assertEqual(self.users(tok(8)), [PU])
        self.assertIsNone(gate.real_refusal(dict(spec, holdout={"n": 40, "wallet_share": 0.1})))

    def test_run_trade_refuses_konsenzus_without_switch(self):
        tid = self.demo(tok(7), "konsenzus S1:k10:E: a")
        self.assertTrue(tid)
        self.mirror()
        r = self.con.execute("SELECT status, reason FROM positions WHERE token=?", (tok(7),)).fetchone()
        self.assertEqual(r[0], "blocked")
        self.assertIn("pravi_novac_izvori", r[1])
        self.assertEqual(self.swaps, [])

    def test_izvori_caps_day_count(self):
        settings.set_flag(self.con, gate.SWITCH, "live", "Jure")
        settings._FLAG_CACHE.clear()
        self.live_rows(30, reason="konsenzus S1:k10:E: x", status="closed", closed=int(self.now - 10),
                       sol_back=0.1)
        why = self.gate(izvori=True)
        self.assertIn("strop pravi_novac_izvori max_buys_day", why or "")


class Settings(SwitchBase):
    def test_switch_only_by_the_owner_and_flag_never_live(self):
        with self.assertRaises(ValueError):
            settings.set_flag(self.con, gate.SWITCH, "live", "Grok")
        with self.assertRaises(ValueError):
            settings.set_flag(self.con, "konsenzus", "live", "Jure")
        self.assertIn(gate.SWITCH, settings.OWNER_SWITCHES)
        self.assertIn("konsenzus", settings.PROFILE_FLAGS)
        self.assertFalse(settings.pravi_novac_izvori(con=self.con))

    def test_owner_order_paper_last_and_never_the_switch(self):
        from ui import assistnotes
        # 15.11.: the oscillator's order (oscilator -> paper) came after it
        self.assertIn(("konsenzus", "paper"), [o[:2] for o in assistnotes.OWNER_FLAG_ORDERS])
        self.assertNotIn(gate.SWITCH, [n for n, _m, _w in assistnotes.OWNER_FLAG_ORDERS])
        mine = tuple(o for o in assistnotes.OWNER_FLAG_ORDERS if o[0] == "konsenzus")
        with mock.patch.object(assistnotes, "OWNER_FLAG_ORDERS", mine):
            assistnotes.owner_flag_orders(self.con)
        self.assertEqual(settings.flag_state(self.con)["konsenzus"]["mode"], "paper")
        self.assertEqual(settings.flag_state(self.con)[gate.SWITCH]["mode"], "off")

    def test_switch_row_in_prekidaci(self):
        from ui import apterm
        h = apterm.owner_switches_html(self.con, True)
        self.assertIn("pravi_novac_izvori", h)
        self.assertIn("0,3 SOL", h)


class Visibility(unittest.TestCase):
    def test_mcp_tool_and_critic_block(self):
        from critic import deep
        from ui import mcpapi
        self.assertIn("get_source_strategy", {t["name"] for t in mcpapi.TOOLS})
        self.assertIn("konsenzus_izvora", [k for k, _f in deep.CONTEXT_BLOCKS])
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"KONSENZUS_DB": os.path.join(d, "k.db")}):
            kstore._CACHE.clear()
            d0, err = mcpapi._tool("get_source_strategy", {})
            self.assertFalse(err)
            self.assertFalse(d0["available"])
            self.assertIsNone(R and __import__("konsenzus.view", fromlist=["x"]).critic_summary())
        kstore._CACHE.clear()


if __name__ == "__main__":
    unittest.main()
