"""19.11. navečer (2) (coordinator: "make the deep read several times faster without breaking the rate limit or the
box"), offline:

  - wallets/helpool.Pool: the credits never go above the cap, also when workers race; no SQLite off the main thread
  - wallets/rpc: the limiter keeps the rate across threads; a 429 backs off (Retry-After, jitter) and is counted; the
    pool shrinks to one worker after repeated 429s and says so
  - chain.fetch_event_deep on the pool: identical trades and coverage to the sequential read; the deadline stops the
    dispatch (in flight finishes and is saved), the next call resumes with only what is left; a failed slice is
    retried once, then left due
  - the measured speed-up on a fixture (I/O sleep + a parse cost) for the deep read and for wallets/povijest
  - the pass line's "dohvat: ..." part

    python3 -m unittest tests.test_brzi_dohvat_offline
"""
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from insajderi import chain, store  # noqa: E402
from wallets import helpool, rpc  # noqa: E402

D = 86400
NOW = 1_795_200_000
C = store.config({"warmup_days": 1, "sol_usd_hist": False})
MAIN = threading.main_thread()


def addr(name):
    return (name + "1" * 44)[:44]


class MainOnly:
    """A sqlite connection that fails the test when used off the main thread."""

    def __init__(self, con):
        self._con = con

    def __getattr__(self, name):
        attr = getattr(self._con, name)
        if callable(attr):
            def guarded(*a, **k):
                assert threading.current_thread() is MAIN, f"SQLite {name} off the main thread"
                return attr(*a, **k)
            return guarded
        return attr


class PoolCredits(unittest.TestCase):
    def test_never_over_the_cap_when_workers_race(self):
        import random
        rnd = random.Random(3)
        for trial in range(20):
            pool = helpool.Pool(8, log=lambda m: None, stats={"calls": 0, "e429": 0})
            tasks = [{"cost": rnd.choice((20, 30, 70)), "i": i} for i in range(40)]
            spent = [0]
            out = []

            def call(t):
                time.sleep(rnd.random() * 0.002)
                return t["i"], rnd.randint(0, t["cost"])          # never more than its reservation
            cap = rnd.randint(100, 900)
            pool.run(tasks, call, cap, spent, None, lambda t, r, e: out.append(r))
            pool.close()
            self.assertLessEqual(spent[0], cap, trial)
            self.assertTrue(out)


class Limits(unittest.TestCase):
    def test_limiter_keeps_the_rate_across_threads(self):
        lim = rpc.Limiter(50.0)
        stamps, lock = [], threading.Lock()

        def go():
            for _ in range(5):
                lim.wait()
                with lock:
                    stamps.append(time.monotonic())
        th = [threading.Thread(target=go) for _ in range(6)]
        t0 = time.monotonic()
        for t in th:
            t.start()
        for t in th:
            t.join()
        self.assertEqual(len(stamps), 30)
        self.assertGreaterEqual(max(stamps) - t0, 29 / 50 - 0.02)   # 30 calls at 50/s: at least 0.58 s
        self.assertLessEqual(len([s for s in stamps if s - t0 <= 0.2]), 11)

    def test_429_backs_off_honours_retry_after_and_counts(self):
        sleeps = []
        lim = rpc.Limiter(1000.0, sleep=sleeps.append)
        calls = []

        class H:
            def get(self, k):
                return "3" if k == "Retry-After" else None

        def fake(req, timeout, retries=None):
            calls.append(retries)
            if len(calls) <= 2:
                raise urllib.error.HTTPError("u", 429, "busy", H(), None)
            return {"result": {"data": []}}
        e0 = rpc.STATS["e429"]
        with mock.patch.object(rpc, "LIMIT", lim), mock.patch.object(rpc.http, "_fetch", fake):
            got = rpc._send(object())
        self.assertEqual(got, {"result": {"data": []}})
        self.assertEqual(calls, [0, 0, 0])                                 # http's own retries are off
        self.assertEqual(rpc.STATS["e429"] - e0, 2)
        self.assertTrue(sleeps and max(sleeps) >= 3.0)                     # every thread waits out the Retry-After
        self.assertTrue(max(sleeps) <= 3.0 * 1.3 + 1e-6)                   # with at most 30 % jitter

    def test_pool_shrinks_to_one_after_429s(self):
        stats = {"calls": 0, "e429": 0}
        lines = []
        pool = helpool.Pool(6, log=lines.append, stats=stats, prefix="x: ")
        widths = []

        def call(t):
            stats["e429"] += 1
            return None, 0

        def done(t, r, e):
            widths.append(pool.width())
        pool.run([{"cost": 10} for _ in range(12)], call, 10_000, [0], None, done)
        pool.close()
        self.assertEqual(widths[-1], 1)
        self.assertEqual(len([x for x in lines if "dohvat na 1 radnika do kraja prolaza" in x]), 1)
        self.assertIn("radnika 1, 429: 12", pool.line())


class DeepPool(unittest.TestCase):
    def setUp(self):
        from tests.test_insajderi2_offline import Chain
        self.tmp = tempfile.TemporaryDirectory()
        self.p = {k: os.path.join(self.tmp.name, f"{k}.db") for k in ("hype_db", "kol_db", "early_db", "wallet_db")}
        self.tok = addr("Pump")
        self.t0 = NOW - 3 * D
        self.e = {"eid": "j:P:1", "kind": "jump", "token": self.tok, "t0": self.t0, "win_end": self.t0 + 8 * 3600,
                  "tier": "pumpa15", "src": "midcap 6h", "fetched": 0, "prio": 1.0, "callers": {}}
        ch = Chain()
        for i in range(60):   # buyers spread over the 24 h before, sellers in the jump
            w = addr(f"B{i}")
            ch.tx(self.tok, w, "buy", 0.5 + i / 100, 1000 + i, self.t0 - 24 * 3600 + 1200 * i + 7)
            if i % 2:
                ch.tx(self.tok, w, "sell", 0.9, 500 + i, self.t0 + 400 * i + 3)
        self.ch = ch

    def tearDown(self):
        self.tmp.cleanup()

    def con(self, name):
        c = store.connect(os.path.join(self.tmp.name, name))
        c.execute("INSERT INTO i2_events (eid, kind, token, t0, tier, win_end, src) VALUES (?,?,?,?,?,?,?)",
                  (self.e["eid"], "jump", self.tok, self.t0, "pumpa15", self.e["win_end"], "midcap 6h"))
        c.commit()
        return c

    def fetch(self, delay=0.0, parse=0.0, fail=None):
        lock = threading.Lock()
        calls = []

        def f(address, since_ts=None, until_ts=None, max_pages=3, oldest_first=False, on_credits=None):
            with lock:
                calls.append((address, since_ts, until_ts))
                n = len(calls)
            if fail and fail(n, address, since_ts):
                raise RuntimeError("Helius 503")
            time.sleep(delay)                                   # the network
            t_end = time.perf_counter() + parse                 # the page's parse (CPU, holds the GIL)
            while time.perf_counter() < t_end:
                pass
            return self.ch.fetch(address, since_ts, until_ts, max_pages, oldest_first, on_credits)
        f.calls = calls
        return f

    def read(self, name, workers, fetch, stop=None, c=None):
        con = self.con(name)
        guarded = MainOnly(con)
        pool = helpool.Pool(workers, log=lambda m: None, stats={"calls": 0, "e429": 0})
        got = chain.fetch_event_deep(guarded, self.p, c or C, self.e, NOW, 10_000, fetch=fetch, log=lambda m: None,
                                     pool=pool, stop=stop)
        pool.close()
        trades = set(con.execute("SELECT sig, wallet, mint, side FROM i2_trades"))
        cover = con.execute("SELECT depth, pre_s, pre_cov, jump_s, jump_cov, n_tx FROM i2_cover").fetchone()
        return con, got, trades, cover

    def test_identical_to_sequential_and_no_sqlite_off_main(self):
        c1, g1, tr1, cov1 = self.read("a.db", 1, self.fetch())
        c6, g6, tr6, cov6 = self.read("b.db", 6, self.fetch())
        self.assertTrue(tr1)
        self.assertEqual(tr1, tr6)
        self.assertEqual(cov1, cov6)
        self.assertEqual(g1, g6)
        self.assertEqual(cov1[0], store.FETCH_DEPTH)
        c1.close()
        c6.close()

    def test_deadline_stops_dispatch_and_the_next_call_resumes(self):
        f = self.fetch(delay=0.01)
        stop = (lambda: len(f.calls) >= 4)
        con, _g, tr, cov = self.read("c.db", 3, f, stop=stop)
        self.assertIsNone(cov)                                       # cut: not marked, still due
        n1 = len(f.calls)
        self.assertLessEqual(n1, 6)                                  # the ones in flight, nothing after the deadline
        saved = con.execute("SELECT COUNT(*) FROM i2_fetch WHERE key LIKE 'deep%' AND key NOT LIKE '%:cov'").fetchone()[0]
        self.assertEqual(saved, n1)                                  # every call that ran was saved
        con.close()
        f2 = self.fetch()
        con = MainOnly(store.connect(os.path.join(self.tmp.name, "c.db")))
        chain.fetch_event_deep(con, self.p, C, self.e, NOW, 10_000, fetch=f2, log=lambda m: None,
                               pool=helpool.Pool(3, log=lambda m: None, stats={"calls": 0, "e429": 0}))
        deep2 = [x for x in f2.calls if x[0] == self.tok]
        self.assertEqual(len(deep2), 20 - n1)                        # only the slices left
        _c, _g, tr_full, cov_full = self.read("d.db", 1, self.fetch())
        got = set(con.execute("SELECT sig, wallet, mint, side FROM i2_trades"))
        self.assertEqual(got, tr_full)
        self.assertEqual(con.execute("SELECT depth, pre_s, pre_cov, jump_s, jump_cov, n_tx FROM i2_cover").fetchone(),
                         cov_full)

    def test_a_failed_slice_is_retried_once_then_left_due(self):
        once = self.fetch(fail=lambda n, a, s: n == 1)               # the first call fails, its retry works
        con, _g, _tr, cov = self.read("e.db", 4, once)
        self.assertEqual(cov[0], store.FETCH_DEPTH)
        con.close()
        twice = self.fetch(fail=lambda n, a, s: a == self.tok and s == self.t0 - 24 * 3600)   # that slice always fails
        con, _g, _tr, cov = self.read("f.db", 4, twice)
        self.assertIsNone(cov)
        self.assertEqual(len([x for x in twice.calls if x[1] == self.t0 - 24 * 3600]), 2)
        con.close()

    def test_measured_speed_up(self):
        res = {}
        for w in (1, 6):
            f = self.fetch(delay=0.03, parse=0.003)
            t = time.perf_counter()
            self.read(f"s{w}.db", w, f)
            res[w] = time.perf_counter() - t
        speed = res[1] / res[6]
        print(f"\nduboko čitanje: 1 radnik {res[1]:.2f} s, 6 radnika {res[6]:.2f} s, ubrzanje {speed:.1f}x",
              file=sys.stderr)
        self.assertGreater(speed, 2.5)


class Povijest(unittest.TestCase):
    def test_pool_credits_and_speed_up(self):
        import json
        from wallets import pnl, povijest, store as wstore
        res = {}
        for w in (1, 6):
            with tempfile.TemporaryDirectory() as d:
                con = wstore.connect(os.path.join(d, "w.db"))
                for i in range(30):
                    wstore.observe(con, addr(f"W{i}"), "t", "harvest", "early_buyer", NOW - D)
                con.commit()

                def swaps(wallet, since_ts=None, max_pages=3, oldest_first=False, on_credits=None, sol_usd=None):
                    time.sleep(0.03)
                    on_credits(10)
                    on_credits(10)
                    return [], True, None, None
                c = dict(povijest.config(), workers=w, kredita_dan=470, dan_udio=1.0)
                lines = []
                t = time.perf_counter()
                with mock.patch.object(pnl, "prices_sol", lambda m, cl: ({}, None)):
                    r = povijest.run("night", now=NOW, con=con, cfg=c, swaps=swaps, log=lines.append,
                                     insajderi_db=os.path.join(d, "none.db"), holderi_db=os.path.join(d, "none2.db"))
                res[w] = (time.perf_counter() - t, r)
                spent = con.execute("SELECT SUM(credits) FROM helius_credits WHERE method='povijest'").fetchone()[0]
                self.assertLessEqual(spent, 470)                     # 70 a wallet reserved: 6 wallets, 120 credits
                self.assertEqual(r["credits"], spent)
                self.assertIn("dohvat: ", lines[-1])
                self.assertEqual(json.loads(con.execute("SELECT stats FROM wallets WHERE scored_at IS NOT NULL")
                                            .fetchone()[0]).get("closed"), 0)
                con.close()
        self.assertEqual(res[1][1]["n"], res[6][1]["n"])
        print(f"\npovijest: 1 radnik {res[1][0]:.2f} s, 6 radnika {res[6][0]:.2f} s za {res[1][1]['n']} novčanika",
              file=sys.stderr)


class Line(unittest.TestCase):
    def test_pass_line_carries_the_fetch_stats(self):
        from insajderi import run
        clk = store.Clock("once", C)
        clk.stages["lanac"] = 12.0
        chain.LAST_POOL["line"] = "dohvat: 120 poziva, 7.9/s prosjek, radnika 6, 429: 0"
        try:
            ln = run.time_line("once", clk)
        finally:
            chain.LAST_POOL["line"] = None
        self.assertEqual(ln, "insajderi2: prolaz once: trajanje: lanac 12 s; dohvat: 120 poziva, 7.9/s prosjek, "
                             "radnika 6, 429: 0")


if __name__ == "__main__":
    unittest.main()
