"""12.11. (Jure, nalog točke 1 i 2): Grok's X calls (MCP submit_watch_token, fast/xcall.py) and the paper strategy
x_call_scalp (fast/xscalp.py, flag x_call_scalp G31), offline: the network injected, every database in a temp dir.

Covers: the validation of submit_watch_token (mint base58, handle, integers and their ranges, the post's time, the
engagement keys, velocity given or computed); the fast_check runs at once and its result comes back (or "in progress"
with the id, then get_fast_checks with that id); an x_call is never traded (fast/paper, proposals); a hard block (liquidity,
MC under 30k, rug hard, curve) keeps the paper entry out; the measurement on a synthetic series (max gain before -8 %,
+15 min, +1 h, the target / the stop, the dev dump and the low after it; our own DexScreener point only without
another); the author classes and get_x_call_stats; the x_call record in live_eligible only with n >= 10 and EV >= +3 %;
the flag (default shadow, never live).

    python3 -m unittest tests.test_xcall_offline -v
"""
import json
import os
import sys
import tempfile
import time
import unittest
from collections import Counter
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from fast import checks, enqueue, live as flive, paper, store, view, xcall, xscalp  # noqa: E402
from league import copy as lcopy, store as lstore  # noqa: E402
from live import store as lvstore  # noqa: E402
from rugfilter import collapse  # noqa: E402
from trade import executor, settings  # noqa: E402
from ui import kandidati, mcpapi  # noqa: E402

import test_kandidati_offline as tk  # noqa: E402

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
SOL_USD = 150.0


def addr(seed, tail="", n=44):
    body = "".join(B58[(seed * 11 + i * 17) % len(B58)] for i in range(n - len(tail)))
    return body + tail


TOK = addr(1, "pump")
POOL = addr(2)
DEV = addr(3)
HOLDER = addr(4)


def pair(tok, price=3.2e-4, liq=60_000, mcap=320_000, b5=40, s5=20, dex="pumpswap"):
    return {"baseToken": {"address": tok, "symbol": "XC"}, "priceUsd": str(price), "liquidity": {"usd": liq},
            "marketCap": mcap, "pairAddress": POOL, "dexId": dex,
            "txns": {"m5": {"buys": b5, "sells": s5}, "h1": {"buys": 300, "sells": 200},
                     "h24": {"buys": 3000, "sells": 2500}},
            "volume": {"m5": 9_000, "h1": 80_000, "h24": 900_000}, "priceChange": {"m5": 4, "h1": 12, "h24": 30}}


def rc_report(mint_auth=None, top=(8, 6, 5, 4, 3, 3, 2, 2, 2, 1)):
    hs = [{"address": POOL + "v", "owner": POOL, "pct": 20.0}]
    hs += [{"address": addr(100 + i), "owner": HOLDER if i == 0 else addr(200 + i), "pct": p, "insider": False}
           for i, p in enumerate(top)]
    return {"token": {"supply": 1e15, "decimals": 6, "mintAuthority": mint_auth, "freezeAuthority": None},
            "mintAuthority": mint_auth, "freezeAuthority": None, "knownAccounts": {POOL: {"type": "AMM"}},
            "markets": [{"pubkey": POOL, "lp": {"lpLockedPct": 100.0, "quoteUSD": 30_000, "baseUSD": 30_000},
                         "liquidityAAccount": {"owner": POOL}, "liquidityBAccount": {"owner": POOL}}],
            "topHolders": hs, "creatorBalance": 0, "totalHolders": 900, "risks": [], "rugged": False}


class FakeNet(checks.Net):
    """Every read of a fast_check in memory (no request leaves); the author's record is given (q)."""

    def __init__(self):
        super().__init__(checks.Meter())
        self.calls = Counter()
        self.mk, self.rc = {}, {}
        self.delay = 0.0
        self.q = {"closed": 0, "wins": 0, "pnl_usd": 0.0, "ev_pct": None, "proof": False,
                  "proof_why": "zatvorenih 0 od potrebnih 10", "hits": 0, "n": 0}

    def market(self, tokens):
        self.calls["market"] += 1
        if self.delay:
            time.sleep(self.delay)
        self.meter.add("dexscreener")
        return checks.parse_pairs([self.mk[t] for t in tokens if t in self.mk])

    def rugcheck(self, token, pool=None):
        from topcheck import safety
        self.calls["rugcheck"] += 1
        r = self.rc.get(token)
        if r is None:
            raise RuntimeError("RugCheck HTTP 429")
        return safety.summarize_rc(r, extra_pools=[pool] if pool else ()), checks.rc_holders(r, pool)

    def helius_facts(self, token, rpc):
        raise RuntimeError("Helius off in the test")

    def stored(self, token):
        return {"tc": None, "rug": None}

    def live_trades(self, token, since):
        return []

    def snipers(self, token):
        return (None, None)

    def collapse(self, token, mcap, liq):
        return None

    def archived(self, token):
        return False

    def first_mcap(self, token, now):
        return None

    def sol_usd(self):
        return SOL_USD

    def wallet_meta(self, owners):
        return {}

    def quality(self, sig, now):
        from fast import sources
        return dict(self.q, kind=sig.get("kind"), kind_hr=sources.KIND_HR.get(sig.get("kind")), id=sig["source_id"],
                    label=sig.get("source_label"))

    def source_sold(self, sig, since):
        return None


def good_net(**kw):
    n = FakeNet()
    n.mk[TOK] = pair(TOK, **kw)
    n.rc[TOK] = rc_report()
    return n


def call(now=None, **kw):
    now = now or time.time()
    a = {"mint": TOK, "source": "x_call", "author": "@Ansem_X", "followers": 25_000, "post_id": "1856000000000000001",
         "post_ts": int(now) - 120, "engagement_baseline": {"likes": 400, "replies": 50, "reposts": 150, "views": 90_000},
         "velocity": 5.0}
    a.update(kw)
    return a


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.fp, self.hp, self.rp, self.mp, self.rugp = (os.path.join(d, n) for n in
                                                         ("fast.db", "hype.db", "range.db", "minute.db", "rug.db"))
        self._saved = (settings.DB, lstore.DB)
        settings.DB, lstore.DB = os.path.join(d, "trade.db"), os.path.join(d, "league.db")
        self.env = mock.patch.dict(os.environ, {"FAST_DB": self.fp, "HYPE_DB": self.hp, "RANGE_DB": self.rp,
                                                "MINUTE_DB": self.mp, "PROPOSALS_DB": os.path.join(d, "proposals.db"),
                                                "TRADE_OWNER": "Jure"})
        self.env.start()
        for k in ("TRADE_LIVE", "SOLANA_PRIVATE_KEY", "HELIUS_API_KEY", "DATA_DIR"):
            os.environ.pop(k, None)
        self.patches = [mock.patch.object(enqueue, "WAKE", os.path.join(d, ".fast_wake")),
                        mock.patch.object(lcopy, "WAKE", os.path.join(d, ".copy_wake")),
                        mock.patch.object(lvstore, "HYPE_DB", self.hp),
                        mock.patch.object(collapse, "RUG_DB", self.rugp)]
        try:
            from wallets import store as wstore
            self.patches.append(mock.patch.object(wstore, "DB", os.path.join(d, "wallets.db")))
        except ImportError:
            pass
        for p in self.patches:
            p.start()
        settings._FLAG_CACHE.clear()
        xcall._CTX.update(ts=0.0, priors=None, rates=None, path=None)
        enqueue._RECENT.clear()
        view.clear()
        self.tc = executor.connect(settings.DB)
        self.lg = lstore.connect(lstore.DB)
        lcopy.ensure(self.lg)
        paper.ensure(self.lg)
        store.connect(self.fp).close()
        self.lim = {"size_sol": 0.1, "max_sol_per_day": 1.0, "max_open": 5}
        self.srcs = {"hype": self.hp, "range": self.rp, "minute": self.mp, "rug": self.rugp}

    def tearDown(self):
        for p in self.patches:
            p.stop()
        settings.DB, lstore.DB = self._saved
        settings._FLAG_CACHE.clear()
        self.env.stop()
        for c in (self.tc, self.lg):
            c.close()
        self.tmp.cleanup()

    def submit(self, net, wait_s=8.0, **kw):
        return xcall.submit(call(**kw), kid="mcp:test", net=net, wait_s=wait_s, cache=checks.Cache(),
                            log=lambda s: None, lim=self.lim)

    def xrow(self, xid):
        con = store.connect(self.fp)
        try:
            return xcall._x(con, xid)
        finally:
            con.close()

    def set_flag(self, name, mode):
        settings.put(self.tc, f"flag:{name}", {"mode": mode, "since": int(time.time()) - 86400, "who": "Jure"})
        settings._FLAG_CACHE.clear()


# ---------- 1. validation ----------------------------------------------------------------------------------------------

class Validation(unittest.TestCase):
    NOW = 1_794_000_000

    def bad(self, msg, **kw):
        with self.assertRaisesRegex(ValueError, msg):
            xcall.validate(call(now=self.NOW, **kw), self.NOW)

    def test_a_good_call_is_normalised(self):
        a = xcall.validate(call(now=self.NOW, post_id="https://x.com/ansem/status/1856000000000000009"), self.NOW)
        self.assertEqual((a["mint"], a["author"], a["followers"], a["post_id"]), (TOK, "ansem_x", 25_000,
                                                                                    "1856000000000000009"))
        self.assertEqual((a["likes"], a["replies"], a["reposts"], a["views"]), (400, 50, 150, 90_000))
        self.assertEqual((a["velocity"], a["velocity_src"]), (5.0, "client"))
        # milliseconds are read as seconds; velocity omitted: interactions per minute since the post, computed
        a = xcall.validate(call(now=self.NOW, post_ts=(self.NOW - 600) * 1000, velocity=None), self.NOW)
        self.assertEqual(a["post_ts"], self.NOW - 600)
        self.assertEqual((a["velocity"], a["velocity_src"]), (60.0, "computed"))   # 600 interactions / 10 min
        a = xcall.validate(call(now=self.NOW, engagement_baseline={"likes": 1, "replies": 0, "reposts": "2"}), self.NOW)
        self.assertIsNone(a["views"])

    def test_mint_must_be_base58(self):
        self.bad("base58", mint="0OIl" + TOK[4:])          # 0, O, I, l are not base58
        self.bad("base58", mint=TOK[:20])                  # too short
        self.bad("base58", mint=TOK + "abc")               # too long (47)
        self.bad("base58", mint=None)
        self.bad("stablecoin", mint=enqueue.SOL)

    def test_numbers_and_lengths(self):
        self.bad("X handle", author="this_handle_is_too_long")
        self.bad("X handle", author="bad handle")
        self.bad("followers", followers=-1)
        self.bad("followers", followers=True)
        self.bad("followers", followers=1.5)
        self.bad("followers", followers=2_000_000_000)
        self.bad("followers", followers="mnogo")
        self.bad("post_id", post_id="abc")
        self.bad("post_id", post_id="1" * 26)
        self.bad("future", post_ts=self.NOW + 3600)
        self.bad("24 h", post_ts=self.NOW - 25 * 3600)
        self.bad("source", source="telegram")
        self.bad("engagement_baseline", engagement_baseline=[1, 2, 3])
        self.bad("likes is required", engagement_baseline={"replies": 1, "reposts": 1})
        self.bad("unknown key", engagement_baseline={"likes": 1, "replies": 1, "reposts": 1, "bookmarks": 3})
        self.bad("replies", engagement_baseline={"likes": 1, "replies": -2, "reposts": 1})
        self.bad("velocity", velocity=-1)
        self.bad("velocity", velocity=float("nan"))
        self.bad("velocity", velocity="brzo")

    def test_the_mcp_tool_answers_the_reason_as_an_error(self):
        d, err = mcpapi._tool("submit_watch_token", call(mint="nije-adresa"))
        self.assertTrue(err)
        self.assertIn("base58", d["error"])


# ---------- 2. the fast_check runs and comes back ----------------------------------------------------------------------

class FastCheck(Env):
    def test_the_check_runs_at_once_and_its_result_comes_back(self):
        net = good_net()
        t0 = time.time()
        out = self.submit(net)
        self.assertLess(time.time() - t0, 10.0)
        fc = out["fast_check"]
        self.assertEqual(fc["state"], "done", fc)
        self.assertIn(fc["decision"], ("BUY_PAPER", "BUY_LIVE", "SKIP"))
        self.assertEqual(list(fc["checks"]), ["rug", "holders", "flow", "price", "source"])
        self.assertEqual(fc["checks"]["price"]["status"], "ok")
        self.assertEqual(fc["market"]["market_cap_usd"], 320_000)
        self.assertEqual(fc["kind"], "x_call")
        self.assertEqual(out["class"], {"followers_band": "10-50k", "velocity_band": "srednja", "class": "10-50k/srednja"})
        self.assertEqual(out["trading"], "none: submit_watch_token never buys")
        # every field stored, with submitted_ts; the paper entry at the detection's market cap (flag default shadow)
        x = self.xrow(out["x_call_id"])
        self.assertEqual((x["author"], x["followers"], x["post_id"], x["likes"], x["replies"], x["reposts"], x["views"],
                          x["velocity"], x["kid"], x["xmode"]),
                         ("ansem_x", 25_000, "1856000000000000001", 400, 50, 150, 90_000, 5.0, "mcp:test", "shadow"))
        self.assertGreater(x["submitted_ts"], 0)
        self.assertEqual(out["x_call_scalp"]["entry"], "entered")
        self.assertEqual((x["mcap0"], x["liq0"]), (320_000, 60_000))
        self.assertAlmostEqual(x["cost"], 0.02 + 2 * 15 / (30_000 + 15), places=4)   # 0.1 SOL x $150 in a $60k pool
        self.assertIn(HOLDER, x["holders"])                                       # the RugCheck top holders kept
        con = store.ro(self.fp)
        try:
            sig = store.one(con, fc["id"])
        finally:
            con.close()
        # its own source id: a followed influencer's "<handle>" signal is never swallowed by enqueue's dedupe
        self.assertEqual((sig["kind"], sig["source_id"], sig["mode"]), ("x_call", "x:ansem_x", "x_call"))
        fc_con = store.connect(self.fp)
        try:
            self.assertIsNotNone(enqueue.enqueue(fc_con, {"token": TOK, "source_id": "ansem_x", "sig_ts": int(time.time()),
                                                          "via": "x_hook"}, {"kind": "influencer", "label": "@ansem_x"}))
            fc_con.rollback()
        finally:
            fc_con.close()
        # a repeat of the same token and author within 10 min: the stored call, no second check
        again = self.submit(net)
        self.assertTrue(again["duplicate"])
        self.assertEqual(again["x_call_id"], out["x_call_id"])
        self.assertEqual(net.calls["market"], 1)
        # get_fast_checks with the id, and the x_call it belongs to
        d, err = mcpapi._tool("get_fast_checks", {"id": fc["id"]})
        self.assertFalse(err)
        self.assertEqual([s["id"] for s in d["signals"]], [fc["id"]])
        self.assertEqual(d["signals"][0]["x_calls"][0]["x_call_id"], out["x_call_id"])
        d, err = mcpapi._tool("get_fast_checks", {"id": "x"})
        self.assertTrue(err)

    def test_a_slow_check_answers_in_progress_with_the_id_then_get_fast_checks_has_it(self):
        net = good_net()
        net.delay = 1.0
        out = self.submit(net, wait_s=0.2)
        fc = out["fast_check"]
        self.assertEqual(fc["state"], "in_progress")
        self.assertIn(f"id={fc['id']}", fc["query"])
        end = time.time() + 8
        got = None
        while time.time() < end:
            d = view.mcp(ids=fc["id"])
            got = d["signals"][0] if d["signals"] else None
            if got and got["status"] == "done":
                break
            time.sleep(0.1)
        self.assertEqual(got["status"], "done")
        self.assertIn(got["decision"], ("BUY_PAPER", "BUY_LIVE", "SKIP"))
        end = time.time() + 3
        while time.time() < end and self.xrow(out["x_call_id"])["entry_status"] == "pending":
            time.sleep(0.05)
        self.assertEqual(self.xrow(out["x_call_id"])["entry_status"], "entered")

    def test_an_x_call_is_never_traded_even_with_a_kupi_and_fast_path_in_paper(self):
        self.set_flag("fast_path", "paper")
        net = good_net()
        net.q.update(bench={"n": 40, "hits": 32})   # the author's bench: P high, EV > 0
        out = self.submit(net)
        self.assertEqual(out["fast_check"]["decision"], "BUY_PAPER", out["fast_check"])
        now = time.time()
        self.assertEqual(paper.fresh(now, self.fp), [])                       # the demo account never sees it
        self.assertEqual(flive.kupi_rows(now, self.fp), {})                   # no proposal either
        self.assertEqual(paper.run_once(self.lg, lambda toks: {t: (3.2e-4, 60_000.0, "u", 320_000.0, "XC", {})
                                                               for t in toks}, now=int(now) + 1, path=self.fp,
                                        sol=SOL_USD, lim=self.lim), [])
        self.assertIsNone(self.lg.execute("SELECT 1 FROM trades WHERE token=?", (TOK,)).fetchone())

    def test_the_source_check_reads_the_authors_caller_record_by_the_handle(self):
        from fast import sources
        seen = []
        with mock.patch.object(sources, "caller_info", lambda h, now: seen.append(h) or {"ev_n": 3}), \
                mock.patch.object(sources, "caller_bench", lambda h: seen.append(h) or {"n": 12, "hits": 7}):
            q = sources.quality({"source_id": "x:ansem_x", "kind": "x_call", "source_label": "@ansem_x"})
        self.assertEqual(seen, ["ansem_x", "ansem_x"])
        self.assertEqual((q["id"], q["kind_hr"], q["n"], q["hits"]), ("x:ansem_x", "X poziv (Grok)", 12, 7))

    def test_rate_limit_per_key(self):
        with mock.patch.object(xcall, "RATE_PER_HOUR", 1):
            self.submit(good_net(), wait_s=5)
            with self.assertRaisesRegex(ValueError, "rate limit"):
                self.submit(good_net(), author="drugi")

    def test_flag_off_stores_and_checks_but_enters_nothing(self):
        self.set_flag("x_call_scalp", "off")
        out = self.submit(good_net())
        self.assertEqual(out["fast_check"]["state"], "done")
        self.assertEqual(out["x_call_scalp"]["entry"], "off")


# ---------- 3. hard blocks -----------------------------------------------------------------------------------------------

class HardBlocks(Env):
    def entry(self, net):
        out = self.submit(net)
        x = self.xrow(out["x_call_id"])
        return x["entry_status"], x["entry_why"] or "", x

    def test_liquidity_under_15k_blocks(self):
        st, why, x = self.entry(good_net(liq=9_000, mcap=300_000))
        self.assertEqual(st, "blocked")
        self.assertIn("liq_low", why)
        self.assertIsNone(x["mcap0"])

    def test_mc_under_30k_blocks(self):
        st, why, _x = self.entry(good_net(liq=16_000, mcap=20_000))
        self.assertEqual(st, "blocked")
        self.assertIn("under_30k", why)

    def test_rug_hard_blocks(self):
        net = good_net()
        net.rc[TOK] = dict(rc_report(), rugged=True)   # RugCheck marks it rugged: a hard rug (never overridden)
        st, why, _x = self.entry(net)
        self.assertEqual(st, "blocked")
        self.assertIn("rug_hard", why)

    def test_curve_blocks(self):
        st, why, _x = self.entry(good_net(dex="pumpfun"))
        self.assertEqual(st, "blocked")
        self.assertIn("curve", why)
        net = good_net()
        net.mk.clear()                               # no DexScreener pair at all
        net.rc[TOK] = rc_report()
        st, why, _x = self.entry(net)
        self.assertEqual(st, "blocked")
        self.assertIn("curve", why)

    def test_a_blocked_call_is_never_measured(self):
        self.entry(good_net(liq=9_000))
        out = xscalp.tick(time.time() + 4000, srcs=self.srcs, fetch=lambda toks: {}, log=lambda s: None)
        self.assertEqual(out["measured"], 0)
        s = xscalp.stats()
        self.assertEqual((s["all"]["n"], s["all"]["blocked"]), (0, 1))
        self.assertEqual(s["all"]["blocked_reasons"], {"liq_low": 1})


# ---------- 4. the measurement ---------------------------------------------------------------------------------------------

def ev_(ts, r, lo=None, close=None, src="t"):
    return (ts, r, r if lo is None else lo, r if close is None else close, src)


class Measure(unittest.TestCase):
    T0 = 1_794_000_000
    C = 0.03

    def test_target_before_the_stop(self):
        t = self.T0
        ev = [ev_(t + 60, 1.05), ev_(t + 300, 1.14), ev_(t + 900, 1.08), ev_(t + 1500, 0.91), ev_(t + 1800, 1.30),
              ev_(t + 3600, 0.97)]
        m = xscalp.measure(ev, t, self.C)
        self.assertEqual(m["hit"], 1)                          # 1.14 >= 1 + 10 % + 3 % cost, before -8 %
        self.assertEqual(m["net"], 0.10)
        self.assertAlmostEqual(m["max_net"], 0.11)             # 1.14 before the stop at t+1500; the later 1.30 not
        self.assertAlmostEqual(m["r15"], 0.05)
        self.assertAlmostEqual(m["r60"], -0.06)
        self.assertEqual(m["n_points"], 6)

    def test_the_stop_first(self):
        t = self.T0
        ev = [ev_(t + 60, 1.06), ev_(t + 180, 0.91), ev_(t + 600, 1.40), ev_(t + 3590, 1.2)]
        m = xscalp.measure(ev, t, self.C)
        self.assertEqual(m["hit"], 0)
        self.assertAlmostEqual(m["net"], -0.08 - self.C)
        self.assertAlmostEqual(m["max_net"], 0.06 - self.C)
        self.assertAlmostEqual(m["r60"], 0.2 - self.C)

    def test_target_and_stop_in_one_candle_is_the_stop(self):
        t = self.T0
        m = xscalp.measure([ev_(t + 60, 1.25, lo=0.90, close=1.0)], t, self.C)
        self.assertEqual(m["hit"], 0)
        self.assertAlmostEqual(m["max_net"], -self.C)          # the stop candle's own high does not count

    def test_neither_is_the_hour_result_and_a_gross_10_is_no_net_10(self):
        t = self.T0
        m = xscalp.measure([ev_(t + 600, 1.11), ev_(t + 3610, 1.04)], t, self.C)
        self.assertEqual(m["hit"], 0)                          # +11 % gross is +8 % net: no hit
        self.assertAlmostEqual(m["net"], 0.04 - self.C)
        self.assertIsNone(m["r15"])                            # no point near +15 min
        self.assertIsNone(xscalp.measure([], t, self.C)["net"])


class Tick(Env):
    T0 = None

    def entered(self, t0, mcap0=100_000.0, price0=1e-4, cost=0.03):
        con = store.connect(self.fp)
        try:
            cur = con.execute("INSERT INTO x_calls (mint, source, author, followers, post_id, post_ts, likes, replies, "
                              "reposts, velocity, fol_band, vel_band, cls, submitted_ts, kid, xmode, entry_status, "
                              "entry_ts, mcap0, price0, liq0, stake_usd, cost, dev, holders) VALUES "
                              "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (TOK, "x_call", "ansem_x", 25_000, "1", int(t0) - 60, 1, 1, 1, 5.0, "10-50k", "srednja",
                               "10-50k/srednja", int(t0), "mcp:test", "shadow", "entered", t0, mcap0, price0, 60_000,
                               15.0, cost, DEV, json.dumps([{"owner": HOLDER, "pct": 8.0}])))
            con.commit()
            return cur.lastrowid
        finally:
            con.close()

    def px(self, rows):
        con = store.connect(self.fp)
        try:
            con.executemany("INSERT INTO x_call_px VALUES (?,?,?,?)", [(TOK, int(ts), None, mc) for ts, mc in rows])
            con.commit()
        finally:
            con.close()

    def test_synthetic_series_max_gain_15_min_1_h_and_the_dev_dump(self):
        t0 = int(time.time()) - 4000
        xid = self.entered(t0)
        self.px([(t0 + 60, 105_000), (t0 + 300, 114_000), (t0 + 900, 108_000), (t0 + 1200, 95_000),
                 (t0 + 1500, 91_000), (t0 + 3600, 97_000)])
        from hype import pulse
        hc = lvstore.connect(self.hp)
        pulse.ensure(hc)
        hc.execute("INSERT INTO token_pulse (token, ts, price, mcap, liquidity) VALUES (?,?,?,?,?)",
                   (TOK, t0 + 2400, 0.99e-4, 99_000, 50_000))
        # the dev sells 2 % of the supply (supply = 100k / 1e-4 = 1e9) at +1000 s; a holder's 0.1 % sale is no dump
        lvstore.add_trades(hc, [("s1", TOK, HOLDER, "sell", 0.1, 1_000_000, 1e-6, 600, "p", t0 + 700, 0),
                                ("s2", TOK, DEV, "sell", 2.0, 20_000_000, 1e-6, 600, "p", t0 + 1000, 0)])
        hc.commit()
        hc.close()
        out = xscalp.tick(t0 + 3600 + 301, srcs=self.srcs, fetch=lambda toks: {}, log=lambda s: None)
        self.assertEqual(out["measured"], 1)
        x = self.xrow(xid)
        self.assertEqual((x["measured"], x["hit"]), (1, 1))
        self.assertAlmostEqual(x["net"], 0.10)
        self.assertAlmostEqual(x["max_net"], 0.11)
        self.assertAlmostEqual(x["r15"], 0.05)
        self.assertAlmostEqual(x["r60"], -0.06)
        self.assertEqual((x["dump_ts"], x["dump_who"]), (t0 + 1000, "dev"))
        self.assertAlmostEqual(x["dump_low"], -0.09)                   # the low after the dump: 91k of 100k
        res = json.loads(x["res"])
        self.assertIn("hype.db token_pulse", res["sources"])
        self.assertIn("x_call_px", res["sources"])

    def test_our_own_dexscreener_point_only_without_another(self):
        t0 = int(time.time()) - 100
        self.entered(t0)
        asked = []

        def fetch(toks):
            asked.append(list(toks))
            return {t: {"price": 1.1e-4, "mcap": 110_000} for t in toks}
        xscalp.tick(t0 + 100, srcs=self.srcs, fetch=fetch, log=lambda s: None)
        self.assertEqual(asked, [[TOK]])
        xscalp.tick(t0 + 110, srcs=self.srcs, fetch=fetch, log=lambda s: None)   # a fresh point exists: no request
        self.assertEqual(len(asked), 1)
        con = store.ro(self.fp)
        try:
            self.assertEqual(store.costs(con, store.day_of(t0 + 100))["dexscreener_xcall"]["calls"], 1)
        finally:
            con.close()


# ---------- 5. classes and get_x_call_stats ------------------------------------------------------------------------------

def put_measured(fp, cls, nets, now, cost=0.03, entry="entered", days_ago=1):
    con = store.connect(fp)
    try:
        for i, n in enumerate(nets):
            fb, vb = cls.split("/")
            con.execute("INSERT INTO x_calls (mint, author, followers, cls, fol_band, vel_band, submitted_ts, entry_status, "
                        "entry_why, cost, measured, net, hit, r15, r60, max_net) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (addr(500 + i), f"a{i}", 1, cls, fb, vb, int(now) - days_ago * 86400 - i, entry,
                         "liq_low: likvidnost" if entry == "blocked" else None, cost,
                         int(n is not None and entry == "entered"),
                         n, int(n is not None and n >= 0.10), n, n, n))
        con.commit()
    finally:
        con.close()


class Classes(Env):
    def test_bands_and_thresholds(self):
        c = xscalp.classify
        self.assertEqual(c(9_999, 1.99)[2], "<10k/niska")
        self.assertEqual(c(10_000, 2.0)[2], "10-50k/srednja")
        self.assertEqual(c(49_999, 19.99)[2], "10-50k/srednja")
        self.assertEqual(c(50_000, 20.0)[2], "50-200k/visoka")
        self.assertEqual(c(199_999, 0)[2], "50-200k/niska")
        self.assertEqual(c(200_000, 500)[2], "200k+/visoka")
        self.assertEqual(len(xscalp.CLASSES), 12)

    def test_stats_per_class_and_days(self):
        now = time.time()
        nets = [0.10] * 7 + [-0.11] * 5                   # 12 measured: 7 hits
        put_measured(self.fp, "10-50k/srednja", nets, now)
        put_measured(self.fp, "10-50k/srednja", [0.10] * 3, now, days_ago=40)     # out of the 30 days
        put_measured(self.fp, "200k+/visoka", [None], now, entry="blocked")
        d, err = mcpapi._tool("get_x_call_stats", {"class": "10-50k/srednja"})
        self.assertFalse(err, d)
        (k,) = d["classes"]
        self.assertEqual((k["n"], k["hit_rate"]), (12, round(7 / 12, 3)))
        self.assertEqual(k["median_net_pct"], 10.0)
        self.assertAlmostEqual(k["ev_net_pct"], round((0.7 - 0.55) / 12 * 100, 2))
        self.assertFalse(k["live_record_ok"])            # EV net +1.25 % < +3 %
        self.assertIn("EV neto", k["live_why"])
        d = xscalp.stats(followers_band="10-50k", days=60)
        self.assertEqual([x["class"] for x in d["classes"]], ["10-50k/niska", "10-50k/srednja", "10-50k/visoka"])
        self.assertEqual(d["classes"][1]["n"], 15)
        d = xscalp.stats(velocity_band="visoka")
        self.assertEqual(d["all"]["blocked"], 1)
        self.assertEqual(d["thresholds"]["velocity"]["visoka"], ">= 20")
        self.assertIn("error", xscalp.stats(cls="1M+/x"))
        self.assertIn("error", xscalp.stats(followers_band="huge"))
        rows = {r["part"]: r for r in xscalp.ev_rows(now, "shadow")}   # events/evreport, the last 7 days
        self.assertEqual(rows["x_call:10-50k/srednja"]["n_outcomes"], 12)
        self.assertIn("DexScreener", rows["x_call:sve"]["note"])
        recs = xscalp.class_records(now)
        self.assertEqual(recs["10-50k/srednja"]["n"], 12)
        # the record's "ev" is net of the fee part only (ui/kandidati's convention): + cost - 2 %
        self.assertAlmostEqual(recs["10-50k/srednja"]["ev"], (0.7 - 0.55) / 12 + 0.03 - 0.02, places=4)


# ---------- 6. live_eligible ----------------------------------------------------------------------------------------------

class XSources(tk.FakeSources):
    def __init__(self):
        super().__init__()
        self.xc, self.xrec = [], {}

    def x_calls(self, now):
        return self.xc

    def x_call_records(self, now):
        return self.xrec


class LiveEligible(unittest.TestCase):
    NOW = tk.NOW

    def setUp(self):
        S = self.S = XSources()
        X = self.X = tk.A
        S.c = [(X, [("pro", "x", self.NOW - 600)], self.NOW - 600, self.NOW - 600, "XC", tk.live())]
        S.crec = {"pro": {"ev_n": 50, "ev_mean": 0.08}}   # a proven caller carries the row's EV
        S.xc = [{"token": X, "ts": self.NOW - 300, "author": "ansem_x", "followers": 25_000, "class": "10-50k/srednja",
                 "velocity": 5.0, "post_id": "1", "mcap": 300_000, "x_call_id": 1, "entry": "entered"}]

    def row(self):
        rows, _m = kandidati.build(self.NOW, self.S)
        return {r["token"]: r for r in rows}[self.X]

    def rec(self, n, ev_net):
        return {"10-50k/srednja": {"n": n, "ev": ev_net + 0.01, "ev_net": ev_net, "hit": 0.6}}

    def test_an_x_call_record_needs_n_10_and_ev_3(self):
        self.S.xrec = self.rec(9, 0.20)
        r = self.row()
        self.assertTrue(r["tradeable"], r["why_not"])
        self.assertIn("x_call", r["source_kinds"])
        self.assertFalse(r["live_eligible"])
        self.assertEqual(r["live_state"], "paper")
        self.assertIn("n = 9", r["live_why"])
        self.assertIn("x_call:10-50k/srednja", [d["from"] for d in r["ev_detail"]])
        self.S.xrec = self.rec(12, 0.02)                  # n enough, EV net +2 % < +3 %
        r = self.row()
        self.assertFalse(r["live_eligible"])
        self.assertIn("EV neto", r["live_why"])
        self.S.xrec = self.rec(12, 0.035)                 # n >= 10 and EV net >= +3 %: live
        r = self.row()
        self.assertTrue(r["live_eligible"], r["live_why"])
        self.assertTrue(r["x_call_gate"]["ok"])
        self.assertEqual(r["x_call_gate"]["class"], "10-50k/srednja")

    def test_without_a_record_the_other_sources_decide_and_x_call_alone_is_paper(self):
        self.S.xrec = {}
        r = self.row()                                     # the x_call adds nothing to the EV: no gate
        self.assertIsNone(r["x_call_gate"])
        self.assertTrue(r["live_eligible"], r["live_why"])
        self.S.c = []                                      # x_call is the only source; its fast_check carries the EV
        self.S.mk = {self.X: tk.live()}
        self.S.fastv = {self.X: {"state": "done", "decision": "BUY_PAPER", "ev_pct": 6.0, "n": 40, "origin": "source",
                                 "key": "ev"}}
        r = self.row()
        self.assertEqual(r["source_kinds"], ["x_call"])
        self.assertTrue(r["tradeable"], r["why_not"])
        self.assertEqual(r["live_state"], "paper")
        self.assertIn("x_call", r["live_why"])

    def test_live_state_takes_the_gate(self):
        evx = {"ev_pct": 5.0, "n_samples": 40, "top_source": {"from": "caller:pro", "n": 40, "share": 0.9}}
        self.assertEqual(kandidati.live_state(True, evx), ("live", None))
        self.assertEqual(kandidati.live_state(True, evx, xcall={"ok": False, "why": "samo papir: x"})[0], "paper")
        self.assertEqual(kandidati.live_state(True, evx, xcall={"ok": True})[0], "live")


# ---------- 7. the flag and the tools -------------------------------------------------------------------------------------

class FlagAndTools(Env):
    def test_default_shadow_never_live(self):
        self.assertEqual(settings.flag("x_call_scalp"), "shadow")
        self.assertEqual(settings.flag_state(self.tc)["x_call_scalp"]["mode"], "shadow")
        self.assertIn("x_call_scalp", settings.FLAGS)
        settings.put(self.tc, "backtest:x_call_scalp", {"pass": True})
        with self.assertRaisesRegex(ValueError, "nikad"):
            settings.set_flag(self.tc, "x_call_scalp", "live", "Jure")
        settings.set_flag(self.tc, "x_call_scalp", "paper", "Jure")
        self.assertEqual(settings.flag("x_call_scalp", con=self.tc), "paper")
        self.assertFalse(settings.any_paper(path=os.path.join(self.tmp.name, "nema.db")))

    def test_tools_are_listed_with_their_schemas(self):
        t = {x["name"]: x for x in mcpapi.TOOLS}
        sw = t["submit_watch_token"]
        self.assertFalse(sw["annotations"]["readOnlyHint"])
        self.assertEqual(set(sw["inputSchema"]["required"]),
                         {"mint", "author", "followers", "post_id", "post_ts", "engagement_baseline"})
        self.assertEqual(set(sw["inputSchema"]["properties"]),
                         {"mint", "source", "author", "followers", "post_id", "post_ts", "engagement_baseline", "velocity"})
        self.assertIn("never", sw["description"])
        self.assertTrue(t["get_x_call_stats"]["annotations"]["readOnlyHint"])
        self.assertIn("id", t["get_fast_checks"]["inputSchema"]["properties"])
        json.dumps(mcpapi.TOOLS)


if __name__ == "__main__":
    unittest.main()
