"""15.11. (owner, translated: "learn from history: if we follow a wallet, look at its average stop losses and set ours
accordingly; learn everything from data, the best stop loss and take profit per source individually ... maybe a wider
stop loss and wait longer: if right after our entry it goes down, wait longer for a recovery"): izlazi/ (sim, data,
learn, store, apply, report) and its use in league/exitplan.

  - the grace keeps a winner that dips -30 % and recovers (the simulator and the live executor)
  - the catastrophic stop and the rug flags ignore the grace
  - walk-forward by time without look-ahead; shrinkage of a small source toward its kind
  - real money keeps the default unless the learned rule is proven out of sample; the demo uses what is learned
  - costs are always taken (never a zero fee); an open plan keeps the numbers it was opened with
No network, synthetic paths and temporary databases.

    python3 -m unittest tests.test_izlazi_offline
"""
import json
import math
import os
import random
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from izlazi import apply, data as idata, learn, report, sim, store as istore  # noqa: E402
from league import auto, copy, exitplan, store  # noqa: E402
from trade import cost as tcost, executor, settings  # noqa: E402

LU, PU = settings.LEAGUE_USER, settings.PAPER_USER
P = 1e-4
W = "W" * 44
TOK = "So1111111111111111111111111111111111111111"


def tok(i):
    return TOK[:-3] + f"{i:03d}"


def bars_of(points, step=60):
    """[(minute, mult)] -> bars [(dt, hi, lo, close)] with the price walking linearly minute by minute."""
    out, prev = [], 1.0
    pts = sorted(points)
    for (m0, v0), (m1, v1) in zip([(0, 1.0)] + pts[:-1], pts):
        for k in range(m0 + 1, m1 + 1):
            v = v0 + (v1 - v0) * (k - m0) / (m1 - m0)
            out.append((k * step, max(prev, v), min(prev, v), v))
            prev = v
    return out


DIP_WIN = [(5, 0.70), (20, 0.72), (40, 1.0), (60, 1.30), (90, 1.60), (240, 1.55)]   # -30 % then +60 %
STRAIGHT_DOWN = [(10, 0.85), (30, 0.70), (60, 0.55), (240, 0.45)]
CRASH = [(3, 0.40), (240, 1.40)]                                                     # -60 % at once (then back)


def entry(bars, ts, src="A", kind="wallet", cost=0.03, sell_s=None, rug_s=None):
    f = sim.fit(bars)
    return {"kind": kind, "src": src, "tok": f"t{ts}", "ts": ts, "arrs": sim.pack(f), "cover": bars[-1][0],
            "cost": cost, "sell_s": sell_s, "rug_s": rug_s, "how": "svijeće", "stats": sim.path_stats(f)}


# ---------- the simulator ---------------------------------------------------------------------------------------------

class Simulator(unittest.TestCase):
    def test_grace_keeps_a_winner_that_dips_30_and_recovers(self):
        b = bars_of(DIP_WIN)
        pr = sim.Prep(b, 0.03)
        no_grace = sim.Params(20, 0, 30, 1.0, 0, 1440, 0)
        grace = no_grace._replace(sl=25, grace=60)
        r0, why0, _ = pr.run(no_grace)
        r1, why1, _ = pr.run(grace)
        self.assertEqual(why0, "sl")
        self.assertLess(r0, -0.20)                        # stopped at -20 % (+ slip + cost)
        self.assertEqual(why1, "tp")                      # waited, then +30 % net
        self.assertAlmostEqual(r1, (1.30 + 0.03) * (1 - sim.SLIP_MKT) - 1 - 0.03, places=6)
        self.assertAlmostEqual(r1, sim.evaluate(b, grace, 0.03), places=9)

    def test_after_the_grace_the_stop_sells_at_the_price_there(self):
        b = bars_of(STRAIGHT_DOWN)
        r, why, i = sim.Prep(b, 0.03).run(sim.Params(20, 30, 30, 1.0, 0, 1440, 0))
        self.assertEqual(why, "sl")
        self.assertGreaterEqual(b[i - 1][0], 30 * 60)       # not before the grace ended
        self.assertLess(r, -0.30)                           # the price was already ~-30 %: sold there, not at -20 %

    def test_the_catastrophic_stop_and_the_rug_flag_ignore_the_grace(self):
        b = bars_of(CRASH)
        r, why, i = sim.Prep(b, 0.03).run(sim.Params(20, 60, 30, 1.0, 0, 1440, 0))
        self.assertEqual(why, "cat")
        self.assertLess(b[i][0], 60 * 60)
        r2, why2, i2 = sim.Prep(bars_of(DIP_WIN), 0.03, rug_s=120).run(sim.Params(20, 60, 30, 1.0, 0, 1440, 0))
        self.assertEqual((why2, i2), ("rug", 1))

    def test_fees_are_always_taken(self):
        flat = [(k * 60, 1.0, 1.0, 1.0) for k in range(1, 61)]
        r, why, _ = sim.Prep(flat, 0.04).run(sim.Params(20, 0, 30, 1.0, 0, 45, 0))
        self.assertEqual(why, "time")
        self.assertAlmostEqual(r, (1 - sim.SLIP_MKT) - 1 - 0.04)   # a flat path loses the round trip and the slip
        self.assertGreaterEqual(idata.MIN_COST, 0.02)
        c = idata.Costs({"trade": None})
        self.assertGreaterEqual(c.round_trip(10_000_000, "x", 150.0), 0.02)   # a deep pool still pays 2 %+
        up = bars_of([(10, 1.13)])                                   # +13 % gross: under TP1 +12 % NET with 3 % cost
        self.assertNotEqual(sim.Prep(up, 0.03).run(sim.Params(20, 0, 12, 1.0, 0, 1440, 0))[1], "tp")

    def test_the_fast_prep_and_the_plain_simulation_agree(self):
        rnd = random.Random(3)
        import itertools
        for _ in range(40):
            b, p = [], 1.0
            for k in range(1, rnd.randint(10, 300)):
                o = p
                p *= math.exp(rnd.gauss(0, 0.05))
                b.append((60 * k, max(o, p) * 1.01, min(o, p) * 0.99, p))
            b = sim.unpack(sim.pack(b))
            sell, rug = rnd.choice([None, rnd.randint(0, 9000)]), rnd.choice([None, None, rnd.randint(0, 9000)])
            pr = sim.Prep(sim.pack(b), 0.03, sell, rug)
            for q in itertools.islice(itertools.product(*(sim.VALUES[d] for d in sim.DIMS)), 0, None, 97):
                q = sim.canon(q)
                self.assertAlmostEqual(pr.net(q), sim.evaluate(b, q, 0.03, sell, rug), places=6)

    def test_thinning_keeps_the_exits(self):
        b = bars_of(DIP_WIN)
        f = sim.fit(b)
        self.assertLessEqual(len(f), sim.MAX_BARS)
        for q in (sim.DEFAULT, sim.Params(25, 60, 30, 1.0, 0, 1440, 0), sim.Params(10, 0, 8, 0.5, 15, 120, 0)):
            self.assertAlmostEqual(sim.Prep(b, 0.03).net(q), sim.Prep(f, 0.03).net(q), delta=0.02)

    def test_path_stats_measure_how_deep_a_winner_dips(self):
        st = sim.path_stats(bars_of(DIP_WIN))
        self.assertTrue(st["winner"])
        self.assertAlmostEqual(st["mae_before_peak"], -0.30, places=6)
        self.assertGreater(st["recover_min"], 20)


# ---------- the data ------------------------------------------------------------------------------------------------

class Data(unittest.TestCase):
    def test_assemble_extends_the_path_and_rescales_at_the_join(self):
        t = 1_800_000_000
        m0 = t - t % 60
        cs = [(m0 + 60 * k, 1.0, 1.0, 1.0, 1.0, 1) for k in range(0, 60)]          # 1 h of USD candles at $1
        sol = [(m0 + 60 * k, 0.01, 0.01, 0.01, 0.01 if k < 120 else 0.012, 0)
               for k in range(55, 300)]                                     # SOL prints, +20 % later
        bars, t0, cover, how = idata.assemble({"svijeće": cs, "printovi": sol}, t)
        self.assertEqual(how, "svijeće+printovi")
        self.assertGreater(cover, 4 * 3600 - 600)
        self.assertAlmostEqual(bars[-1][3], 1.2, places=6)                    # rescaled: SOL x the join's ratio
        self.assertIsNone(idata.assemble({"tikovi": cs}, t))                  # a 20-min tick store is no entry

    def test_build_reads_kol_calls_and_their_candles(self):
        from kol import minute
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        mp, kp = os.path.join(tmp.name, "minute.db"), os.path.join(tmp.name, "kol.db")
        now = int(time.time())
        mcon = minute.connect(mp)
        rows = []
        for i in range(6):
            ts = now - 86400 * (6 - i)
            m0 = ts - ts % 60
            mint = f"Mint{i:040d}"
            path = [(m0 + 60 * k, 1.0, 1.02, 0.99, 1.0 + 0.002 * k, 100.0) for k in range(0, 240)]
            minute.keep_candles(mcon, mint, path, [("tw%d" % i, "caller", ts)], m0 + 240 * 60, now)
            mcon.execute("INSERT INTO call_path (tweet_id, token, handle, ts, entry, lag_s, mcap_e) VALUES "
                         "(?,?,?,?,?,?,?)", (f"tw{i}", mint, "caller", ts, 1.0, 30, 100_000.0))
            rows.append(mint)
        mcon.commit()
        mcon.close()
        kc = sqlite3.connect(kp)
        kc.executescript("CREATE TABLE kols (handle TEXT, bot INTEGER);")
        kc.close()
        over = {k: None for k in ("hype", "wallets", "events", "league", "fast", "market", "range", "momentum",
                                  "proposals")}
        over.update(minute=mp, kol=kp, trade=os.path.join(tmp.name, "trade.db"))
        es, cov, meta = idata.build(over, now=now, log=lambda s: None)
        self.assertEqual(len(es), 6)
        self.assertEqual({e["src"] for e in es}, {"caller"})
        self.assertEqual(cov["kol"]["s_putom"], 6)
        self.assertTrue(all(e["cost"] >= 0.02 for e in es))
        self.assertEqual(meta["lag"]["kol"]["s"], 60)


    def test_build_reads_a_followed_wallet_its_sales_its_own_stop_and_our_copies(self):
        from kol import minute
        from wallets import store as wstore
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = tmp.name
        now = int(time.time())
        mp, wp, lp = (os.path.join(d, x) for x in ("minute.db", "wallets.db", "league.db"))
        mcon, wcon, lg = minute.connect(mp), wstore.connect(wp), store.connect(lp)
        copy.ensure(lg)
        fid = copy.follow(lg, PU, "wallet", W, "kit", 25, 5, "mirror")
        for i in range(8):
            ts = now - 86400 * (8 - i)
            m0 = ts - ts % 60
            mint = f"Mint{i:040d}"
            minute.keep_candles(mcon, mint, [(m0 + 60 * k, 1.0, 1.02, 0.99, 1.0 + 0.002 * k, 1.0) for k in range(240)],
                                [("tw%d" % i, "x", ts)], m0 + 240 * 60, now)
            wcon.execute("INSERT INTO wallet_trades VALUES (?,?,?,?,?,?,?)", (W, f"b{i}", ts, mint, 1000.0, -0.5, "buy"))
            wcon.execute("INSERT INTO wallet_trades VALUES (?,?,?,?,?,?,?)",
                         (W, f"s{i}", ts + 3600, mint, -1000.0, 0.4 if i % 2 else 0.7, "sell"))
            tid = store.buy(lg, PU, mint, "S", 25, 1.0, 50_000, "copy wallet kit", None, 100_000.0)
            lg.execute("UPDATE trades SET opened_ts=?, follow_id=? WHERE id=?", (ts + 40, fid, tid))
            lg.execute("INSERT OR IGNORE INTO copy_log VALUES (?,?,?,?,?,?,?,?,?)",
                       (fid, mint, "sell", ts + 3600, ts + 3630, "S", "izlaz", "x", tid))
        for c in (mcon, wcon, lg):
            c.commit()
            c.close()
        over = {k: None for k in ("hype", "events", "fast", "market", "range", "momentum", "proposals", "kol")}
        over.update(minute=mp, wallets=wp, league=lp, trade=os.path.join(d, "trade.db"))
        es, cov, meta = idata.build(over, now=now, log=lambda s: None)
        kinds = sorted({(e["kind"], e["src"]) for e in es})
        self.assertEqual(kinds, [("strategy", "copy"), ("wallet", W)])
        w = [e for e in es if e["kind"] == "wallet"]
        self.assertEqual(len(w), 8)
        self.assertTrue(all(3500 < e["sell_s"] < 3700 for e in w))           # its sale + our lag: the mirror sale
        own = meta["wallet_own"][W]
        self.assertEqual((own["closed"], own["own_stop_p50"], own["win_rate"]), (8, 20.0, 0.5))   # sells losers at -20 %
        self.assertEqual(cov["wallet"]["kandidati"]["praćen"], 1)


# ---------- learning ------------------------------------------------------------------------------------------------

def regime(n, t0, pts, src="A", kind="wallet", step=3600, **kw):
    return [entry(bars_of(pts), t0 + i * step, src, kind, **kw) for i in range(n)]


class Learning(unittest.TestCase):
    def test_walk_forward_is_split_by_time_without_look_ahead(self):
        es = regime(40, 1_800_000_000, DIP_WIN) + regime(20, 1_800_000_000 + 41 * 3600, STRAIGHT_DOWN)
        ins, outs, cut = learn.split(es)
        self.assertTrue(ins and outs)
        self.assertTrue(all(e["ts"] + e["cover"] <= cut for e in ins))       # every in-sample outcome known at the cut
        self.assertTrue(all(e["ts"] >= cut for e in outs))
        self.assertFalse({id(e) for e in ins} & {id(e) for e in outs})
        rows, _ = learn.learn(es, log=lambda s: None)
        r = [x for x in rows if x["source_id"] == "A"][0]
        p = sim.from_dict(r["params"])
        # chosen on the older regime (dip -30 % then +60 %): a stop wider than the dip or a grace over it, although
        # the newer entries (only out of sample) fall straight down, where a tight stop would have been best
        self.assertTrue(p.sl > 30 or p.grace >= 30, p)
        self.assertLess(r["ev_out"], r["ev_in"])
        self.assertEqual(r["n_out"], len([e for e in es if e["ts"] >= r["stats"]["cut_ts"]]))

    def test_a_small_source_is_shrunk_toward_its_kind(self):
        kind_rows = []
        for s in range(8):   # the kind: winners that dip -30 % first (wide stop + grace wins)
            kind_rows += regime(12, 1_800_000_000 + s * 50, DIP_WIN, src=f"K{s}", step=7200)
        small = regime(6, 1_800_000_000 + 99, STRAIGHT_DOWN, src="small", step=7200)
        rows, _ = learn.learn(kind_rows + small, log=lambda s: None)
        by = {(r["source_kind"], r["source_id"]): r for r in rows}
        r = by[("wallet", "small")]
        self.assertTrue(r["stats"]["shrunk"])
        self.assertLess(r["n"], learn.MIN_N)
        alone, _memo = learn.fit(learn.Scorer([e for e in small if e["ts"] + e["cover"] <= r["stats"]["cut_ts"]]))
        self.assertLessEqual(alone.sl, 20)                                    # on its own: a tight stop
        self.assertNotEqual(sim.from_dict(r["params"]), alone)               # shrunk: not its own extreme
        self.assertIn(("wallet", "*"), by)
        self.assertIn(("*", "*"), by)
        self.assertEqual(learn.eb_k([(10, 0.01, 0.04)] * 5), learn.K_MAX)   # no difference between sources: strong

    def test_the_simplest_rule_within_one_standard_error(self):
        es = regime(30, 1_800_000_000, [(30, 1.0), (240, 1.0)])               # nothing happens: every rule is equal
        chosen, memo = learn.fit(learn.Scorer(es))
        self.assertEqual(sim.complexity(chosen, max(learn.Scorer(es).allowed()["tmax"])), 0)

    def test_rows_are_stored_and_read_back_small(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "izlazi.db")
        es = regime(30, 1_800_000_000, DIP_WIN)
        info = learn.run(path=path, entries=es, cov={"wallet": {"ulazi": 30}}, meta={}, log=lambda s: None)
        rows = istore.load(path, fresh=True)
        self.assertIn(("wallet", "A"), rows)
        self.assertEqual(info["summary"]["entries"], 30)
        self.assertLess(os.path.getsize(path), 200_000)
        cs = report.critic_summary(path=path)
        self.assertTrue(cs["available"])
        self.assertTrue(any(s["source"] == "wallet:A" for s in cs["sources"]))
        self.assertIn("ev_out_pct", cs["sources"][0])
        self.assertIn("Naučeni izlazi", report.markdown(path))
        json.dumps(cs)


# ---------- real money vs demo --------------------------------------------------------------------------------------

def row(kind, sid, params, n=40, n_out=12, ev_out=4.0, default_ev_out=0.5, ci=(1.0, 7.0), ts=None):
    return {"source_kind": kind, "source_id": sid, "params": sim.as_dict(params), "n": n, "n_out": n_out,
            "ev_in": 3.0, "ev_out": ev_out, "ci_lo": ci[0], "ci_hi": ci[1], "default_ev_out": default_ev_out,
            "stats": {"mirror_judged": True, "diff_ci": [0.5, 6.5]}, "ts": ts or int(time.time())}


WIDE = sim.Params(40, 15, 20, 0.5, 15, 1440, 0)


class Proof(unittest.TestCase):
    def test_real_money_needs_out_of_sample_proof(self):
        good = row("wallet", W, WIDE)
        self.assertTrue(istore.proven(good)[0])
        for bad, why in ((dict(good, n_out=5), "premalo"), (dict(good, ev_out=1.2), "nije barem"),
                         (dict(good, ci_hi=0.4), "ispod zadanog"),
                         (dict(good, stats={"diff_ci": [-2.5, 9.0]}), "nesigurna"),
                         (dict(good, stats={}), "intervala razlike"),
                         (row("wallet", W, sim.DEFAULT), "zadano")):
            ok, w = istore.proven(bad)
            self.assertFalse(ok)
            self.assertIn(why, w)
        keys = [("wallet", W), ("strategy", "copy"), ("wallet", "*"), ("*", "*")]
        weak = {("wallet", W): dict(good, n_out=3), ("strategy", "copy"): dict(good, ev_out=0.6)}
        self.assertEqual(apply.choose(weak, keys, real=True)[0], None)          # nothing proven: the default
        self.assertIs(apply.choose(weak, keys, real=False)[0], weak[("wallet", W)])   # the demo learns anyway
        own_no = {("wallet", W): dict(good, ev_out=0.6), ("*", "*"): good}
        self.assertIsNone(apply.choose(own_no, keys, real=True)[0])   # its own evidence (n_out >= 8) says no
        kol = {("kol", "SomeCaller"): good}
        self.assertIs(apply.choose(kol, [("kol", "@somecaller")], real=True)[0], good)   # '@' and case
        stale = {("wallet", W): dict(good, ts=int(time.time()) - 10 * 86400)}
        self.assertIsNone(apply.choose(stale, keys, real=False)[0])   # the nightly run stopped: not used


class Env(unittest.TestCase):
    """league.db / trade.db / izlazi.db in a temporary folder; no rug unless a test says so."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self._saved = (settings.DB, store.DB)
        settings.DB = os.path.join(d, "trade.db")
        store.DB = os.path.join(d, "league.db")
        self.con = executor.connect(settings.DB)
        self.lg = store.connect(store.DB)
        copy.ensure(self.lg)
        self.izl = os.path.join(d, "izlazi.db")
        for p in (mock.patch.dict(os.environ, {"IZLAZI_DB": self.izl}),
                  mock.patch.object(auto, "_collapsed", lambda *a, **k: None),
                  mock.patch.object(exitplan, "fresh_prices", lambda toks, now: {})):
            p.start()
            self.addCleanup(p.stop)
        settings._FLAG_CACHE.clear()
        istore._CACHE.clear()
        exitplan._LAST.clear()
        exitplan._SWEEP["ts"] = exitplan._QSWEEP["ts"] = 0.0
        self.now = int(time.time())
        self.fid = copy.follow(self.lg, PU, "wallet", W, "kit", 25, 5, "mirror")
        self.lines = []

    def tearDown(self):
        settings.DB, store.DB = self._saved
        settings._FLAG_CACHE.clear()
        istore._CACHE.clear()
        self.con.close()
        self.lg.close()
        self.tmp.cleanup()

    def learned(self, rows):
        con = istore.connect(self.izl)
        istore.save(con, rows, {"summary": {}}, self.now)
        con.close()
        istore._CACHE.clear()

    def switch(self, on=True):
        settings.set_flag(self.con, settings.SWITCH_ALL, "live" if on else "off", "Jure")
        settings._FLAG_CACHE.clear()

    def buy(self, user, token, age=0, fid=None):
        tid = store.buy(self.lg, user, token, "SYM", 25, P, 50_000, "copy wallet kit", None, 100_000.0)
        self.lg.execute("UPDATE trades SET opened_ts=?, follow_id=? WHERE id=?", (self.now - age, fid or self.fid, tid))
        self.lg.commit()
        auto.set_auto(self.lg, user, tid, "tpsl", "15%", "-15%")   # the lot's own tight stop
        return tid

    def cover(self, user, token):
        return exitplan.quick_cover(self.lg, token, user, now=self.now, liq=50_000, client="copy kit",
                                    log=self.lines.append)

    def step(self, mult, dt=5, liq=50_000.0):
        self.now += dt
        mk = lambda toks: {x: (P * mult, liq, None, 100_000.0 * mult) for x in toks}   # noqa: E731
        return exitplan.run_once(self.lg, mk, now=self.now)

    def held(self, user, token):
        return bool(exitplan._lots(self.lg, user, token))


class DemoAndReal(Env):
    def test_demo_uses_the_learned_exit_and_it_replaces_the_lots_own_stop(self):
        self.learned([row("wallet", W, WIDE, n=6, n_out=0, ev_out=None, default_ev_out=None, ci=(None, None))])
        self.buy(PU, tok(1))
        pid = self.cover(PU, tok(1))
        p = exitplan.active(self.lg, tok(1))
        self.assertEqual(p["id"], pid)
        self.assertIn(exitplan.LEARNED_TAG, p["client"])
        self.assertTrue(p["client"].startswith(exitplan.QUICK_SRC))
        self.assertEqual(p["plan"]["stop"]["v"], -40.0)                       # wider than the lot's own -15 %
        self.assertEqual(p["plan"]["grace"]["min"], 15.0)
        rt = tcost.round_trip(25.0, 50_000.0) * 100
        self.assertAlmostEqual(p["plan"]["take_profits"][0]["v"], round(20 + rt, 2))   # TP1 net of the cost
        self.assertIn(tok(1), exitplan.in_force_tokens(self.lg, PU))         # the lot's own TP/SL steps aside
        self.assertTrue(any("izlaz naučen: wallet" in x for x in self.lines))

    def test_grace_holds_a_dip_of_30_and_takes_the_recovery(self):
        self.learned([row("wallet", W, WIDE)])
        self.buy(PU, tok(2))
        self.cover(PU, tok(2))
        self.assertEqual(self.step(0.70), [])                                 # -30 % inside the grace: held
        self.assertEqual(auto.fast_once(self.lg, lambda toks: {x: (P * 0.70, 50_000.0, None, 70_000.0)
                                                               for x in toks}, PU, now=self.now), [])   # lot's -15 %
        self.assertTrue(self.held(PU, tok(2)))
        self.assertEqual(self.step(0.95, dt=600), [])
        got = self.step(1.0 + (20 + tcost.round_trip(25.0, 50_000.0) * 100) / 100 + 0.002)
        self.assertEqual([tr for _u, _t, tr, _x in got], ["tp1"])

    def test_after_the_grace_the_stop_fires(self):
        self.learned([row("wallet", W, WIDE)])
        self.buy(PU, tok(3))
        self.cover(PU, tok(3))
        self.assertEqual(self.step(0.58), [])                                 # -42 %: under the stop, in the grace
        got = self.step(0.58, dt=16 * 60)                                     # the grace is over: out
        self.assertEqual([tr for _u, _t, tr, _x in got], ["stop"])

    def test_the_catastrophic_stop_and_the_rug_ignore_the_grace(self):
        self.learned([row("wallet", W, WIDE)])
        self.buy(PU, tok(4))
        self.cover(PU, tok(4))
        got = self.step(0.45)                                                 # -55 % inside the grace
        self.assertEqual([tr for _u, _t, tr, _x in got], ["katastrofa"])
        self.buy(PU, tok(5))
        self.cover(PU, tok(5))
        got = self.step(0.98, liq=20_000.0)                                   # the pool under half of the entry's
        self.assertEqual([tr for _u, _t, tr, _x in got], ["rug"])
        ev = self.lg.execute("SELECT note FROM exit_events WHERE token=? AND trigger='rug'", (tok(5),)).fetchone()
        self.assertIn("likvidnost", ev[0])
        self.buy(PU, tok(6))
        self.cover(PU, tok(6))
        with mock.patch.object(auto, "_collapsed", lambda *a, **k: {"text": "dev prodaje"}):
            got = self.step(0.99)                                             # rugfilter's collapse: dev selling
        self.assertEqual([tr for _u, _t, tr, _x in got], ["rug"])

    def test_real_money_keeps_the_default_without_proof(self):
        self.switch(True)
        self.learned([row("wallet", W, WIDE, n_out=4)])                       # learned, but not proven out of sample
        self.buy(LU, tok(7))
        self.cover(LU, tok(7))
        p = exitplan.active(self.lg, tok(7))
        self.assertNotIn(exitplan.LEARNED_TAG, p["client"])
        self.assertTrue(p["client"].startswith(f"{exitplan.SWITCH_SRC} {exitplan.QUICK_TAG}"))
        self.assertEqual(p["plan"]["stop"]["v"], -15.0)                       # quick plan: the lot's tighter stop
        self.assertNotIn(tok(7), exitplan.in_force_tokens(self.lg, LU))

    def test_real_money_takes_a_proven_rule_and_never_without_the_switch(self):
        self.learned([row("wallet", W, WIDE)])
        self.buy(LU, tok(8))
        self.assertIsNone(exitplan._learned(self.lg, LU, exitplan._lots(self.lg, LU, tok(8)))[0])   # switch off
        self.switch(True)
        self.cover(LU, tok(8))
        p = exitplan.active(self.lg, tok(8))
        self.assertTrue(p["client"].startswith(exitplan.SWITCH_SRC))
        self.assertIn(exitplan.LEARNED_TAG, p["client"])
        self.assertTrue(p["plan"]["learned"]["proof"])
        self.assertIn(tok(8), exitplan.in_force_tokens(self.lg, LU))
        self.assertTrue(any("EV van uzorka +4,00 % vs default +0,50 %" in x for x in self.lines))

    def test_the_stop_is_never_wider_than_sl_default(self):
        settings.put(self.con, "sl_default", 30, "Jure")
        self.learned([row("wallet", W, sim.Params(50, 15, 20, 0.5, 15, 1440, 0))])
        self.buy(PU, tok(9))
        self.cover(PU, tok(9))
        p = exitplan.active(self.lg, tok(9))
        self.assertEqual(p["plan"]["stop"]["v"], -30.0)
        self.assertLessEqual(p["plan"]["grace"]["cat_pct"], 30.0)

    def test_two_accounts_one_token_each_its_own_numbers(self):
        self.switch(True)
        self.learned([row("wallet", W, WIDE, n_out=3)])                      # demo yes, real money no
        self.buy(PU, tok(10))
        self.cover(PU, tok(10))
        self.buy(LU, tok(10))
        self.cover(LU, tok(10))
        p = exitplan.active(self.lg, tok(10))
        self.assertEqual(sorted(p["plan"]["accounts"]), sorted([LU, PU]))
        mine = exitplan.user_plan(p["plan"], LU)
        self.assertIsNone(mine.get("learned"))
        self.assertIsNone(mine.get("grace"))
        self.assertIsNotNone(exitplan.user_plan(p["plan"], PU).get("grace"))
        self.assertIn(tok(10), exitplan.in_force_tokens(self.lg, PU))
        self.assertNotIn(tok(10), exitplan.in_force_tokens(self.lg, LU))
        got = self.step(0.70)                                                 # -30 %: the real account's -15 % fires
        self.assertEqual([(u, tr) for u, _t, tr, _x in got], [(LU, "stop")])
        self.assertTrue(self.held(PU, tok(10)))                               # the demo waits out its grace

    def test_an_open_plan_keeps_its_numbers_when_the_learning_changes(self):
        self.learned([row("wallet", W, WIDE)])
        self.buy(PU, tok(11))
        pid = self.cover(PU, tok(11))
        before = exitplan.active(self.lg, tok(11))["plan"]
        self.learned([row("wallet", W, sim.Params(10, 0, 8, 1.0, 0, 45, 1))])
        self.now += 60
        exitplan.ensure_quick_plans(self.lg, now=self.now, every=0)
        p = exitplan.active(self.lg, tok(11))
        self.assertEqual(p["id"], pid)
        self.assertEqual(p["plan"], before)

    def test_a_learned_exit_without_mirror_skips_the_sources_sale(self):
        self.learned([row("wallet", W, WIDE)])                                # mirror 0
        self.buy(PU, tok(12))
        self.cover(PU, tok(12))
        self.assertTrue(exitplan.mirror_off(self.lg, tok(12), PU))
        f = [x for x in copy.follows(self.lg, PU) if x["id"] == self.fid][0]
        copy._enter(self.lg, auto, {tok(12): (P * 1.05, 50_000.0, None, 105_000.0, "SYM")},
                    [(f, tok(12), "sell", self.now)], self.now)
        self.assertTrue(self.held(PU, tok(12)))
        self.learned([row("wallet", W, WIDE._replace(mirror=1))])
        self.buy(PU, tok(13))
        self.cover(PU, tok(13))
        self.assertFalse(exitplan.mirror_off(self.lg, tok(13), PU))

    def test_no_learning_no_change(self):
        self.buy(PU, tok(14))
        self.cover(PU, tok(14))
        p = exitplan.active(self.lg, tok(14))
        self.assertNotIn(exitplan.LEARNED_TAG, p["client"])
        self.assertIsNone(p["plan"].get("grace"))
        self.assertNotIn(tok(14), exitplan.in_force_tokens(self.lg, PU))

    def test_mcp_tool_reads_the_rows(self):
        from ui import mcpapi
        self.learned([row("wallet", W, WIDE)])
        d, err = mcpapi._tool("get_learned_exits", {"source_kind": "wallet", "top": 5})
        self.assertFalse(err)
        self.assertEqual(d["sources"][0]["source"], f"wallet:{W}")
        self.assertTrue(d["sources"][0]["real_money"])
        self.assertIn("get_learned_exits", {t["name"] for t in mcpapi.TOOLS})
        d, err = mcpapi._tool("get_learned_exits", {"source_kind": "x"})
        self.assertTrue(err)


if __name__ == "__main__":
    unittest.main()
