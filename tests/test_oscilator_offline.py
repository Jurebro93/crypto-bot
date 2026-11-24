"""15.11. (vlasnik: "token koji ide gore-dolje tijekom dana ... 50 puta dnevno, 1-2 $ na svakom"): oscilator/ on
synthetic data, no network.

  - the scanner ranks a sine-like oscillating token above a trending and a dumping one
  - costs: swings too small to pay at 0.1 SOL (no entry: the target net of cost does not fit in the range) pay at 1 SOL
    in a deep pool
  - the walk-forward picks day D+1's tokens from day D's data only (changing D+1 never changes the pick)
  - the demo account's entries and exits (take profit, stop, rug crash) through oscilator/live.tick
  - the switch off means never real money (live and run_trade); the owner order puts the flag in paper last and never
    the switch; the rug / breakdown exit costs what the bar's low says

    python3 -m unittest tests.test_oscilator_offline
"""
import math
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from oscilator import gate, live, rule, scan, store as ostore, walk  # noqa: E402
from tests.test_pravi_novac_sve_offline import PU, SwitchBase, tok  # noqa: E402
from trade import settings  # noqa: E402

D0 = 20500   # a Zagreb day number
T0 = scan.day_start(D0)
SUPPLY = 1e9


def series(kind, days=3, amp=0.06, period_min=40, start=2e-4, seed_days=None):
    """Minute bars [(ts, o, h, l, c, v, None, None)] of `days` days: "sine" (+-amp around a flat level), "trend"
    (+60 % a day, tiny noise), "dump" (-40 % a day)."""
    out = []
    px_prev = start
    for i in range(days * 1440):
        t = T0 + i * 60
        d = i / 1440
        if kind == "sine":
            px = start * (1 + amp * math.sin(2 * math.pi * i / period_min))
        elif kind == "trend":
            px = start * (1.6 ** d) * (1 + 0.002 * math.sin(i / 3))
        else:
            px = start * (0.6 ** d) * (1 + 0.002 * math.sin(i / 3))
        hi, lo = max(px, px_prev) * 1.001, min(px, px_prev) * 0.999
        out.append((t, px_prev, hi, lo, px, 500.0, None, None))
        px_prev = px
    return out


class Scanner(unittest.TestCase):
    def test_oscillator_ranks_first(self):
        per = {}
        cst = {"fee_side": 0.004, "tx_sol": 0.0005, "demo_fee_side": 0.01, "sol_usd": 150.0}
        for name in ("sine", "trend", "dump"):
            per[name], _r, _d = walk.token_days(series(name, days=2), SUPPLY, 100_000, cst, sizes=(0.5,),
                                                targets=(1.0,))
        top = walk.pick(per, D0)
        self.assertEqual(top[0][0], "sine")
        m = per["sine"][D0]["m"]
        self.assertTrue(m["eligible"])
        self.assertGreater(m["swings"]["0.5"], 20)
        self.assertLess(m["er"], 0.05)
        self.assertFalse(per["dump"][D0]["m"]["eligible"])   # -40 % in the day: never picked
        self.assertGreater(per["trend"][D0]["m"]["er"], per["sine"][D0]["m"]["er"])

    def test_zigzag_counts_cycles_above_the_threshold_only(self):
        closes = [1.0, 1.05, 1.0, 1.05, 1.0, 1.05, 1.0]
        self.assertEqual(scan.zigzag_legs(closes, 0.04), 3)
        self.assertEqual(scan.zigzag_legs(closes, 0.06), 0)


class Costs(unittest.TestCase):
    def test_small_swings_pay_only_at_size_in_a_deep_pool(self):
        bars = series("sine", days=1, amp=0.025, period_min=30)
        small = rule.cost_at(0.1, 250_000, 150.0)
        big = rule.cost_at(1.0, 250_000, 150.0)
        # 0.1 SOL: ~1.7 % cost + 1 $ / 15 $ = 6.7 % net -> ~9 % move needed; the 5 % peak-to-trough never fits
        self.assertGreater(rule.need_move(rule.target_frac(15, 1.0), small["rt"]), 0.08)
        t_small = rule.simulate(bars, 15.0, 250_000, tp_usd=1.0, rt=small["rt"])
        self.assertEqual(t_small, [])
        t_big = rule.simulate(bars, 150.0, 250_000, tp_usd=1.0, rt=big["rt"])
        self.assertGreater(len(t_big), 10)
        s = rule.summary(t_big)
        self.assertGreater(s["ev_usd"], 0)
        self.assertGreater(s["hit"], 0.8)
        # every trade's net result is after the real round trip (fees, impact, network)
        x = t_big[0]
        self.assertAlmostEqual(x["ret"], x["exit"] / x["entry"] * (1 - big["rt"]) - 1, places=9)

    def test_cost_model_parts(self):
        c = rule.cost_at(0.1, 40_000, 150.0)
        self.assertAlmostEqual(c["parts"]["fee"], 2 * (0.003 + 0.001))   # PumpSwap 0.3 % + route 0.1 % a side
        self.assertAlmostEqual(c["parts"]["net"], 2 * 0.0005 * 150 / 15)
        self.assertGreater(rule.cost_at(1.0, 20_000, 150.0)["rt"], rule.cost_at(1.0, 250_000, 150.0)["rt"])
        self.assertGreater(rule.demo_rt(75, 40_000, 0.029), rule.cost_at(0.5, 40_000, 150.0)["rt"])

    def test_rug_exit_costs_the_bar_low(self):
        bars = series("sine", days=1, amp=0.025, period_min=30)[:300]
        c = rule.cost_at(1.0, 250_000, 150.0)
        tr = rule.simulate(bars, 150.0, 250_000, tp_usd=1.0, rt=c["rt"])
        self.assertTrue(tr)
        k = next(i for i, b in enumerate(bars) if b[0] >= tr[-1]["out_ts"]) + 1
        # a fresh entry signal right before a crash: rebuild a path that dips, turns up, then rugs to -80 %
        crash = list(bars[:k + 60])
        last = crash[-1]
        base = last[4]
        for j, f in enumerate((0.97, 0.975, 0.98)):
            t = last[0] + 60 * (j + 1)
            crash.append((t, base * f, base * f * 1.001, base * f * 0.999, base * f, 1, None, None))
        t = crash[-1][0] + 60
        crash.append((t, base * 0.98, base * 0.98, base * 0.2, base * 0.2, 1, None, None))
        tr2 = rule.simulate(crash, 150.0, 250_000, tp_usd=1.0, rt=c["rt"])
        worst = min(tr2, key=lambda x: x["ret"])
        if worst["reason"] in ("rug", "stop"):
            self.assertLess(worst["ret"], -0.5)


class WalkForward(unittest.TestCase):
    def test_pick_uses_day_d_only(self):
        cst = {"fee_side": 0.004, "tx_sol": 0.0005, "demo_fee_side": 0.01, "sol_usd": 150.0}
        a = series("sine", days=2)
        b = series("trend", days=2)
        per = {"A": walk.token_days(a, SUPPLY, 100_000, cst, (0.5,), (1.0,))[0],
               "B": walk.token_days(b, SUPPLY, 100_000, cst, (0.5,), (1.0,))[0]}
        wf = walk.walk(per, sizes=(0.5,), targets=(1.0,), k=1)
        self.assertEqual(wf["picks"][str(D0 + 1)], ["A"])
        # day D+1 changed completely (A dumps, B oscillates): the pick for D+1 is still A, its loss counts
        a2 = a[:1440] + [(x[0], x[1] * 0.3, x[2] * 0.3, x[3] * 0.3, x[4] * 0.3) + x[5:] for x in a[1440:]]
        b2 = b[:1440] + series("sine", days=2)[1440:]
        per2 = {"A": walk.token_days(a2, SUPPLY, 100_000, cst, (0.5,), (1.0,))[0],
                "B": walk.token_days(b2, SUPPLY, 100_000, cst, (0.5,), (1.0,))[0]}
        wf2 = walk.walk(per2, sizes=(0.5,), targets=(1.0,), k=1)
        self.assertEqual(wf2["picks"][str(D0 + 1)], ["A"])
        self.assertGreater(wf["top"]["0.5@1"]["n"], 0)
        self.assertEqual(wf2["top"]["0.5@1"]["broke_share"], 1.0)

    def test_run_on_fixtures_writes_db_report_and_lines(self):
        lines = []
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "o.db")
            data = walk.run(series=walk.fixture_series(), now=1794400000, log=lines.append, out_dir=d, db_path=db,
                            budget_s=120)
            self.assertTrue(os.path.exists(os.path.join(d, "oscilator.md")))
            ostore.reset_cache()
            self.assertTrue((ostore.top(db) or {}).get("tokens"))
            self.assertIn("0.1@1", (ostore.proof(db) or {}).get("sizes") or {})
            ostore.reset_cache()
        self.assertTrue(any(s.startswith("oscilator: velicina 0.5 SOL") and "EV" in s and "CI90" in s for s in lines))
        self.assertTrue(any(s.startswith("oscilator: top 10 danas:") for s in lines))
        self.assertEqual(set(data["walk"]["top"]), {f"{s:g}@{t:g}" for s in rule.SIZES_SOL for t in rule.TARGETS_USD})


class Live(SwitchBase):
    def setUp(self):
        super().setUp()
        self.flag("oscilator", "paper")
        live._BARS.clear()
        live._ST.update(tick=0.0, minute={}, said={})
        live._ST.pop("q", None)
        self.px = {}
        self.liq = 60_000.0   # under the MC of $100k (a pool above the MC is a fake one)
        p = mock.patch.object(live, "_sol", lambda: 150.0)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(live, "_seed", lambda con, t, now: live._BARS.__setitem__(t, []))
        p.start()
        self.addCleanup(p.stop)

    def mk(self, toks):
        return {t: (self.px[t], self.liq, "https://dexscreener.com/solana/pumpswap", self.px[t] * 1e9, "OSC",
                    {"m5": 0.0}) for t in toks if t in self.px}

    def feed(self, t, prices, start, step=20):
        """Quotes every `step` s; returns the texts."""
        out = []
        now = start
        for p in prices:
            self.px[t] = p
            out += live.tick(self.lg, self.mk, now=now, force=True, top=[t])
            now += step
        return out, now

    def oscillation(self, n_min, base=1e-4, amp=0.03, period=20):
        """Three quotes a minute of a sine around base."""
        out = []
        for i in range(n_min * 3):
            out.append(base * (1 + amp * math.sin(2 * math.pi * (i / 3) / period)))
        return out

    def rows(self, user=None):
        return self.lg.execute("SELECT user, status, reason, ret, pnl_usd, ret_demo, pnl_booked FROM oscilator_trades "
                               + ("WHERE user=?" if user else ""), (user,) if user else ()).fetchall()

    def test_demo_entries_and_take_profits(self):
        t = tok(11)
        texts, _now = self.feed(t, self.oscillation(150), self.now - 150 * 60)
        rs = self.rows()
        self.assertTrue(rs, texts[-5:])
        self.assertEqual({r[0] for r in rs}, {PU})
        closed = [r for r in rs if r[1] == "closed"]
        self.assertTrue(closed)
        self.assertTrue(all(r[2] in ("tp", "time", "stop") for r in closed))
        self.assertIn("tp", {r[2] for r in closed})
        tp = [r for r in closed if r[2] == "tp"][0]
        self.assertGreater(tp[4], 0.9)   # ~ +1 $ net at the real cost (0.5 SOL x $150)
        self.assertLess(tp[5], tp[3])    # the demo fee gives less than the real cost model
        self.assertTrue(any("oscilator demo ulaz" in x for x in texts))
        tr = self.lg.execute("SELECT auto, source FROM trades WHERE user=? AND token=?", (PU, t)).fetchone()
        self.assertIsNone(tr[0])
        self.assertTrue(tr[1].startswith("oscilator"))

    def test_stop_on_a_crash(self):
        t = tok(12)
        now = self.now - 200 * 60
        for p in self.oscillation(190):   # quote by quote until the rule holds a trade
            _x, now = self.feed(t, [p], now)
            if [r for r in self.rows() if r[1] == "open"]:
                break
        self.assertTrue([r for r in self.rows() if r[1] == "open"])
        _x, now = self.feed(t, [0.3e-4] * 3, now)   # a rug: -70 % in one quote
        stops = [r for r in self.rows() if r[2] in ("stop", "rug")]
        self.assertTrue(stops)
        self.assertLess(min(r[3] for r in stops), -0.5)
        self.assertFalse([r for r in self.rows() if r[1] == "open"])

    def test_flag_off_no_entry(self):
        self.flag("oscilator", "off")
        self.feed(tok(13), self.oscillation(120), self.now - 120 * 60)
        self.assertEqual(self.rows(), [])

    def test_switch_off_never_real(self):
        good = {"sizes": {"0.1@1": {"n": 500, "ev_pct": 3.0, "ci90_ev_pct": [1.0, 5.0], "usd_day": 20.0}}}
        self.assertIn("isključen", gate.real_refusal(con=self.con, proof=good, stats={"n": 100, "ev_pct": 2.0}))
        self.feed(tok(14), self.oscillation(150), self.now - 150 * 60)
        self.assertEqual({r[0] for r in self.rows()}, {PU})

    def test_switch_on_needs_both_proofs(self):
        settings.set_flag(self.con, gate.SWITCH, "live", "Jure")
        settings._FLAG_CACHE.clear()
        good = {"sizes": {"0.1@1": {"n": 500, "ev_pct": 3.0, "ci90_ev_pct": [1.0, 5.0], "usd_day": 20.0}}}
        self.assertIn("demo", gate.real_refusal(con=self.con, proof=good, stats={"n": 10, "ev_pct": 2.0}))
        self.assertIn("treba 100", gate.real_refusal(con=self.con, proof={"sizes": {"0.1@1": {"n": 40}}},
                                                     stats={"n": 100, "ev_pct": 2.0}))
        bad_ci = {"sizes": {"0.1@1": {"n": 500, "ev_pct": 1.0, "ci90_ev_pct": [-0.5, 2.0], "usd_day": 5.0}}}
        self.assertIn("90 %", gate.real_refusal(con=self.con, proof=bad_ci, stats={"n": 100, "ev_pct": 2.0}))
        self.assertIsNone(gate.real_refusal(con=self.con, proof=good, stats={"n": 60, "ev_pct": 1.0}))

    def test_run_trade_refuses_oscilator_without_switch(self):
        tid = self.demo(tok(15), "oscilator: dno raspona 60 min, zaokret gore")
        self.assertTrue(tid)
        self.mirror()
        r = self.con.execute("SELECT status, reason FROM positions WHERE token=?", (tok(15),)).fetchone()
        self.assertEqual(r[0], "blocked")
        self.assertIn("pravi_novac_oscilator", r[1])
        self.assertEqual(self.swaps, [])


class Settings(SwitchBase):
    def test_switch_only_by_the_owner_and_flag_never_live(self):
        with self.assertRaises(ValueError):
            settings.set_flag(self.con, gate.SWITCH, "live", "Grok")
        with self.assertRaises(ValueError):
            settings.set_flag(self.con, "oscilator", "live", "Jure")
        self.assertIn(gate.SWITCH, settings.OWNER_SWITCHES)
        self.assertIn("oscilator", settings.PROFILE_FLAGS)
        self.assertIn("oscilator", settings.NEVER_LIVE)
        self.assertEqual(settings.flag(gate.SWITCH, con=self.con), "off")

    def test_owner_order_paper_last_and_never_the_switch(self):
        from ui import assistnotes
        # 15.11.: the big tokens' order (veliki_range -> paper) came after it
        self.assertIn(("oscilator", "paper"), [o[:2] for o in assistnotes.OWNER_FLAG_ORDERS])
        self.assertNotIn(gate.SWITCH, [n for n, _m, _w in assistnotes.OWNER_FLAG_ORDERS])
        mine = tuple(o for o in assistnotes.OWNER_FLAG_ORDERS if o[0] == "oscilator")
        with mock.patch.object(assistnotes, "OWNER_FLAG_ORDERS", mine):
            assistnotes.owner_flag_orders(self.con)
        self.assertEqual(settings.flag_state(self.con)["oscilator"]["mode"], "paper")
        self.assertEqual(settings.flag_state(self.con)[gate.SWITCH]["mode"], "off")

    def test_switch_row_in_prekidaci(self):
        from ui import apterm
        h = apterm.owner_switches_html(self.con, True)
        self.assertIn(gate.SWITCH, h)
        self.assertIn("3 otvorena", h)

    def test_views_render_without_a_run(self):
        from oscilator import view
        settings.put(self.con, "flag:oscilator", {"mode": "paper", "since": 1})
        settings._FLAG_CACHE.clear()
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.dict(os.environ, {"OSCILATOR_DB": os.path.join(d, "none.db")}):
                ostore.reset_cache()
                self.assertFalse(view.summary()["available"])
                self.assertIsNone(view.critic_summary())
                html = view.card_html(lambda t, m, i, sid="": f"<s>{t}|{m}|{i}</s>", lambda *a, **k: "", str)
                self.assertIn("Oscilator", html)
                self.assertIn("real_money", view.mcp({}))
        ostore.reset_cache()


if __name__ == "__main__":
    unittest.main()
