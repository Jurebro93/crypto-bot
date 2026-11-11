"""11.11. (Jure, flag fast_path G24): the fast path (fast/), offline, the network injected (no request leaves).

Covers: the HODL replay of 10.11. 18:05:45 (a followed wallet with 1 closed trade, no proof): the Helius webhook ->
enqueue -> all five checks -> a decision in under 10 s of wall time with the measured latency, BUY_PAPER with the small
stake, or SKIP naming the failing check and its number; CHECK_FAILED on an API error with three retries within 30 s,
never a SKIP, and the Helius cap as CHECK_FAILED "strop kredita"; BUY_LIVE only with run_trade's proof and only a demo
trade in paper (the real account never touched below live; live refused without the gate); the shrink of P toward the
base rate, EV and the cost by liquidity; dedupe (one check per token and source per 10 min) and the 60-s token cache;
at most 20 checks at once; the exit plan (half at +15 %, trailing 8 %, stop -10 %, 45 min) and the copy exit when the
source wallet sells; outcomes (+1/+5/+15/+60, max, "propušteno") and the daily false-reject report with the cost line;
the skip pop-up and the token pop-up with the checks; MCP get_fast_checks; the card under "Još", owner only; the
flag G24, start.sh and cpuguard.

    python3 -m unittest tests.test_fast_offline -v
"""
import datetime as dt
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import types
import unittest
from collections import Counter
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fast import checks, decide, enqueue, outcomes, paper, report, sources, store, view, worker  # noqa: E402
from league import copy as lcopy, exitplan, store as lstore  # noqa: E402
from trade import executor, settings  # noqa: E402

LU, PU = settings.LEAGUE_USER, settings.PAPER_USER
# 10.11. 18:05:45 Zagreb (CET): HODL bought
REPLAY_TS = int(dt.datetime(2026, 11, 10, 18, 5, 45, tzinfo=ZoneInfo("Europe/Zagreb")).timestamp())
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def addr(seed, head="", tail="", n=44):
    body = "".join(B58[(seed * 7 + i * 13) % len(B58)] for i in range(n - len(head) - len(tail)))
    return head + body + tail


W_HODL = addr(1, "CccS", "y1eU")            # synthetic full-length address of "CccS…y1eU"
TOK = addr(2, "", "pump")
POOL = addr(3)
SOL_USD = 150.0


def pair(tok, price=1.52e-5, liq=60_000, mcap=320_000, b5=40, s5=20, vol5=9_000.0, sym="HODLT"):
    return {"baseToken": {"address": tok, "symbol": sym}, "priceUsd": str(price), "liquidity": {"usd": liq},
            "marketCap": mcap, "pairAddress": POOL, "dexId": "pumpswap",
            "txns": {"m5": {"buys": b5, "sells": s5}, "h1": {"buys": 300, "sells": 200}, "h24": {"buys": 3000, "sells": 2500}},
            "volume": {"m5": vol5, "h1": 80_000, "h24": 900_000}, "priceChange": {"m5": 4, "h1": 12, "h24": 30}}


def rc_report(top=(8, 6, 5, 4, 3, 3, 2, 2, 2, 1), mint_auth=None, lp=100.0):
    """A RugCheck report: the pool's vault is a known account (never a holder), ten real holders."""
    hs = [{"address": POOL + "v", "owner": POOL, "pct": 20.0}]
    hs += [{"address": addr(100 + i), "owner": addr(200 + i), "pct": p, "insider": False} for i, p in enumerate(top)]
    return {"token": {"supply": 1e15, "decimals": 6, "mintAuthority": mint_auth, "freezeAuthority": None},
            "mintAuthority": mint_auth, "freezeAuthority": None, "knownAccounts": {POOL: {"type": "AMM"}},
            "markets": [{"pubkey": POOL, "lp": {"lpLockedPct": lp, "quoteUSD": 30_000, "baseUSD": 30_000},
                         "liquidityAAccount": {"owner": POOL}, "liquidityBAccount": {"owner": POOL}}],
            "topHolders": hs, "creatorBalance": 0, "totalHolders": 900, "risks": [], "rugged": False}


class FakeNet(checks.Net):
    """Every read of a fast_check, in memory; counts calls and the concurrency of market()."""

    def __init__(self, meter=None):
        super().__init__(meter or checks.Meter())
        self.calls = Counter()
        self.mk, self.rc, self.facts, self.trades, self.rug = {}, {}, {}, {}, {}
        self.market_err = None
        self.delay = 0.0
        self.lock = threading.Lock()
        self.active = self.max_active = 0

    def market(self, tokens):
        with self.lock:
            self.calls["market"] += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                time.sleep(self.delay)
            if self.market_err:
                raise self.market_err
            self.meter.add("dexscreener")
            return checks.parse_pairs([self.mk[t] for t in tokens if t in self.mk])
        finally:
            with self.lock:
                self.active -= 1

    def rugcheck(self, token, pool=None):
        from topcheck import safety
        self.calls["rugcheck"] += 1
        r = self.rc.get(token)
        if isinstance(r, Exception) or r is None:
            raise r or RuntimeError("RugCheck HTTP 429")
        self.meter.add("rugcheck")
        return safety.summarize_rc(r, extra_pools=[pool] if pool else ()), checks.rc_holders(r, pool)

    def helius_facts(self, token, rpc):
        self.calls["helius"] += 1
        self.meter.add("helius", 4, 4)
        f = self.facts.get(token)
        if isinstance(f, Exception) or f is None:
            raise f or RuntimeError("Helius HTTP 503")
        return f

    def stored(self, token):
        return {"tc": None, "rug": self.rug.get(token)}

    def live_trades(self, token, since):
        return [t for t in self.trades.get(token, []) if t["ts"] >= since]

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


def good_net(tok=TOK, **kw):
    n = FakeNet(kw.pop("meter", None))
    n.mk[tok] = pair(tok, **kw)
    n.rc[tok] = rc_report()
    return n


class Env(unittest.TestCase):
    """trade.db, league.db, fast.db, hype.db, kol.db in a temp dir; the HODL wallet followed by the Autopilot with
    one closed demo copy; the flag fast_path in paper."""
    MODE = "paper"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.fp, self.hp, self.kp = (os.path.join(d, n) for n in ("fast.db", "hype.db", "kol.db"))
        self._saved = (settings.DB, lstore.DB)
        settings.DB, lstore.DB = os.path.join(d, "trade.db"), os.path.join(d, "league.db")
        self.env = mock.patch.dict(os.environ, {"FAST_DB": self.fp, "HYPE_DB": self.hp, "KOL_DB": self.kp,
                                                "TG_DB": os.path.join(d, "tg.db"), "EARLY_DB": os.path.join(d, "early.db"),
                                                "TRADE_OWNER": "Jure"})
        self.env.start()
        for k in ("TRADE_LIVE", "SOLANA_PRIVATE_KEY", "HELIUS_API_KEY"):
            os.environ.pop(k, None)
        self.patches = [mock.patch.object(enqueue, "WAKE", os.path.join(d, ".fast_wake")),
                        mock.patch.object(lcopy, "WAKE", os.path.join(d, ".copy_wake")),
                        mock.patch.object(lcopy, "_rugged", lambda *a, **k: None)]
        try:
            from wallets import store as wstore
            self.patches.append(mock.patch.object(wstore, "DB", os.path.join(d, "wallets.db")))
        except ImportError:
            pass
        try:
            from events import hooks
            self.patches.append(mock.patch.object(hooks, "chain_ingested", lambda *a, **k: 0))
        except ImportError:
            pass
        for p in self.patches:
            p.start()
        settings._FLAG_CACHE.clear()
        enqueue._RECENT.clear()
        paper._TRIED.clear()
        view.clear()
        self.tc = executor.connect(settings.DB)
        if self.MODE != "off":
            settings.put(self.tc, "flag:fast_path", {"mode": self.MODE, "since": REPLAY_TS - 86400, "who": "Jure"})
        settings._FLAG_CACHE.clear()
        self.lg = lstore.connect(lstore.DB)
        lcopy.ensure(self.lg)
        paper.ensure(self.lg)
        self.fid = lcopy.follow(self.lg, LU, "wallet", W_HODL, "HODL", 25, 10, "mirror")
        # HODL's one closed demo copy (+3 $): no proof (10 closed needed)
        self.lg.execute("INSERT INTO trades (user, token, symbol, opened_ts, closed_ts, status, size_usd, pnl_usd, ret, "
                        "source, follow_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (LU, addr(9), "OLD", REPLAY_TS - 7200, REPLAY_TS - 3600, "closed", 25, 3.0, 0.12,
                         "copy wallet HODL", self.fid))
        self.lg.commit()
        self.fc = store.connect(self.fp)
        sources.refresh(self.fc, REPLAY_TS)
        self.lim = {"size_sol": 0.1, "max_sol_per_day": 1.0, "max_open": 5}

    def tearDown(self):
        for p in self.patches:
            p.stop()
        settings.DB, lstore.DB = self._saved
        settings._FLAG_CACHE.clear()
        enqueue._RECENT.clear()
        view.clear()
        self.env.stop()
        for c in (self.tc, self.lg, self.fc):
            c.close()
        self.tmp.cleanup()

    # ---- helpers ----
    def clock(self, start):
        wall0 = time.time()
        return lambda: start + (time.time() - wall0)

    def payload(self, ts, sol=1.5, tokens=15_000_000, tok=TOK, sig="sig-hodl-1"):
        return [{"feePayer": W_HODL, "signature": sig, "timestamp": ts, "type": "SWAP",
                 "tokenTransfers": [{"mint": enqueue.SOL, "fromUserAccount": W_HODL, "toUserAccount": POOL,
                                     "tokenAmount": sol},
                                    {"mint": tok, "fromUserAccount": POOL, "toUserAccount": W_HODL,
                                     "tokenAmount": tokens}], "nativeTransfers": []}]

    def ingest(self, ts, now, **kw):
        from kol import chainwatch
        with mock.patch.object(enqueue, "time", types.SimpleNamespace(time=lambda: now)):
            return chainwatch.ingest(self.payload(ts, **kw), hype_db=self.hp)

    def run_worker(self, net, now_fn, steps=1, cache=None):
        w = worker.Worker(self.fp, net, log=lambda s: None, now_fn=now_fn, cache=cache or checks.Cache())
        w.lim = self.lim
        w.t["sources"] = now_fn()   # the list was refreshed in setUp
        for _ in range(steps):
            w.step(woke=True)
            w.stop(wait=True)
        return w

    def row(self, sid=None):
        con = store.ro(self.fp)
        try:
            rows = store.read(con, "id=?", (sid,)) if sid else store.read(con, limit=1)
        finally:
            con.close()
        return rows[0] if rows else None

    def market_fn(self, price=1.52e-5, liq=60_000.0, mcap=320_000.0):
        return lambda toks: {t: (price, liq, "u", mcap, "HODLT", {}) for t in toks}


# ---------- 1. the HODL replay -------------------------------------------------------------------------------------

class HodlReplay(Env):
    def test_webhook_to_decision_under_10_s_paper_buy_with_the_small_stake(self):
        arrive = REPLAY_TS + 1.2                       # Helius delivers the swap 1.2 s after the buy
        wall0 = time.time()
        self.assertEqual(self.ingest(REPLAY_TS, arrive), 1)
        r = self.row()
        self.assertEqual((r["status"], r["kind"], r["source_label"], r["via"]), ("queued", "wallet_follow", "HODL", "helius"))
        self.assertAlmostEqual(r["entry_sol_px"], 1e-7)  # 1.5 SOL / 15M tokens: the wallet's own entry
        net = good_net()
        self.run_worker(net, self.clock(arrive + 0.05))
        wall = time.time() - wall0
        r = self.row(r["id"])
        self.assertLess(wall, 10.0)
        self.assertLess(r["latency_s"], 10.0)          # from the wallet's buy to the decision
        self.assertGreater(r["latency_s"], 1.0)
        res = r["checks"]["res"]
        self.assertEqual(list(res), ["rug", "holders", "flow", "price", "source"])   # all five, in order
        self.assertEqual({k: v["status"] for k, v in res.items()}, {k: "ok" for k in res})
        self.assertEqual(r["decision"], "BUY_PAPER")
        self.assertEqual(r["size_sol"], 0.05)
        self.assertIn("zatvorenih 1 od 10", r["reason"])
        self.assertEqual(r["quality"]["closed"], 1)
        self.assertFalse(r["quality"]["proof"])
        self.assertAlmostEqual(res["price"]["values"]["from_entry_pct"], 1.3, places=1)   # 1.52e-5 vs 1e-7 x 150
        self.assertEqual(res["holders"]["values"]["top10_pct"], 36.0)   # the pool's 20 % is not a holder
        self.assertEqual(res["flow"]["values"]["buy_share_5m"], 0.667)
        # the demo account takes it within the auto loop; the real account is never touched
        got = paper.run_once(self.lg, self.market_fn(), now=int(arrive) + 3, path=self.fp, sol=SOL_USD, lim=self.lim)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0][0], PU)
        t = self.lg.execute("SELECT user, size_usd, source FROM trades WHERE token=? AND status='open'", (TOK,)).fetchone()
        self.assertEqual((t[0], round(t[1], 2)), (PU, 7.5))           # 0.05 SOL x 150 $
        self.assertIn("fast path", t[2])
        self.assertIsNone(self.lg.execute("SELECT 1 FROM trades WHERE user=? AND token=?", (LU, TOK)).fetchone())
        self.assertEqual(self.row(r["id"])["traded"]["user"], PU)

    def test_skip_names_the_failing_check_and_its_number(self):
        self.ingest(REPLAY_TS, REPLAY_TS + 1)
        net = good_net()
        net.rc[TOK] = rc_report(top=(20, 12, 8, 6, 5, 4, 3, 2, 1, 1))   # top 10 = 62 %
        self.run_worker(net, self.clock(REPLAY_TS + 1.1))
        r = self.row()
        self.assertEqual(r["decision"], "SKIP")
        self.assertTrue(r["reason"].startswith("holderi: top10 62 % > 45 %"), r["reason"])
        self.assertEqual(r["checks"]["key"], "holders")
        self.assertEqual(len(r["checks"]["res"]), 5)                  # every check ran, also after the fail
        self.assertLess(r["latency_s"], 10)
        self.assertEqual(paper.run_once(self.lg, self.market_fn(), now=REPLAY_TS + 5, path=self.fp, sol=SOL_USD,
                                        lim=self.lim), [])

    def test_shadow_decides_and_logs_but_never_trades(self):
        settings.put(self.tc, "flag:fast_path", {"mode": "shadow", "since": REPLAY_TS, "who": "Jure"})
        settings._FLAG_CACHE.clear()
        self.ingest(REPLAY_TS, REPLAY_TS + 1)
        self.run_worker(good_net(), self.clock(REPLAY_TS + 1.1))
        self.assertEqual(self.row()["decision"], "BUY_PAPER")
        self.assertEqual(paper.run_once(self.lg, self.market_fn(), now=REPLAY_TS + 4, path=self.fp, sol=SOL_USD,
                                        lim=self.lim), [])
        self.assertIsNone(self.lg.execute("SELECT 1 FROM trades WHERE token=?", (TOK,)).fetchone())


class FlagOff(Env):
    MODE = "off"

    def test_off_nothing_is_enqueued_and_the_worker_idles(self):
        self.assertEqual(self.ingest(REPLAY_TS, REPLAY_TS + 1), 1)   # the webhook row itself is written as before
        self.assertIsNone(self.row())
        w = worker.Worker(self.fp, good_net(), log=lambda s: None)
        self.assertEqual(w.step(), "off")
        self.assertIsNone(w.pool)


# ---------- 2. CHECK_FAILED ----------------------------------------------------------------------------------------

class CheckFailed(Env):
    def test_api_error_is_check_failed_retried_three_times_within_30_s_never_a_skip(self):
        self.ingest(REPLAY_TS, REPLAY_TS + 1)
        net = good_net()
        net.rc[TOK] = RuntimeError("RugCheck HTTP 429")     # RugCheck down, Helius down too
        t = [REPLAY_TS + 1.5]
        w = worker.Worker(self.fp, net, log=lambda s: None, now_fn=lambda: t[0], cache=checks.Cache())
        w.lim, w.t["sources"] = self.lim, t[0]
        seen = []
        for _ in range(6):
            w.step(woke=True)
            w.stop(wait=True)
            r = self.row()
            seen.append((r["status"], r["decision"], r["attempts"]))
            t[0] = max(t[0], (r["next_ts"] or t[0])) + 0.01
        self.assertEqual(seen, [("retry", "CHECK_FAILED", 1), ("retry", "CHECK_FAILED", 2), ("retry", "CHECK_FAILED", 3),
                                ("failed", "CHECK_FAILED", 4), ("failed", "CHECK_FAILED", 4),
                                ("failed", "CHECK_FAILED", 4)])
        r = self.row()
        self.assertNotEqual(r["decision"], "SKIP")
        self.assertIn("rug: RugCheck", r["reason"])
        self.assertIn("odustao nakon 4", r["reason"])
        self.assertLessEqual(sum(worker.BACKOFF_S), 30)                # three retries within 30 s
        self.assertEqual(net.calls["rugcheck"], 4)                     # an error is never cached
        self.assertEqual(r["checks"]["res"]["price"]["status"], "ok")  # the other checks still ran

    def test_helius_cap_is_check_failed_strop_kredita(self):
        self.ingest(REPLAY_TS, REPLAY_TS + 1)
        net = good_net(meter=checks.Meter(day_cap=0))
        net.rc[TOK] = RuntimeError("RugCheck timeout")
        self.run_worker(net, self.clock(REPLAY_TS + 1.2))
        r = self.row()
        self.assertEqual(r["decision"], "CHECK_FAILED")
        self.assertIn("strop kredita", r["reason"])
        self.assertEqual(net.calls["helius"], 0)                       # nothing spent past the cap

    def test_helius_fallback_when_rugcheck_fails_within_the_cap(self):
        self.ingest(REPLAY_TS, REPLAY_TS + 1)
        net = good_net()
        net.rc[TOK] = RuntimeError("RugCheck timeout")
        net.facts[TOK] = {"top10_pct": 30.0, "mint_auth": None, "freeze_auth": None}
        self.run_worker(net, self.clock(REPLAY_TS + 1.2))
        r = self.row()
        self.assertEqual(r["decision"], "BUY_PAPER")
        self.assertEqual(r["checks"]["res"]["rug"]["values"]["src"], "Helius (RugCheck nije odgovorio)")
        self.assertEqual(net.meter.helius_used, 4)

    def test_dexscreener_down_is_check_failed(self):
        self.ingest(REPLAY_TS, REPLAY_TS + 1)
        net = good_net()
        net.market_err = TimeoutError("DexScreener timeout")
        self.run_worker(net, self.clock(REPLAY_TS + 1.2))
        r = self.row()
        self.assertEqual((r["decision"], r["status"]), ("CHECK_FAILED", "retry"))
        self.assertIn("tok: DexScreener", r["reason"])


# ---------- 3. BUY_LIVE, proof, the real account ---------------------------------------------------------------------

def checks_ok(liq=60_000):
    c = build_cost_pct(liq)
    return {k: {"status": "ok", "text": k, "values": ({"cost_pct": c} if k == "price" else {})}
            for k in decide.ORDER}


def build_cost_pct(liq):
    from proposals import build
    c = build.cost_for(liq)
    return None if c is None else c * 100


class Decide(unittest.TestCase):
    def test_buy_live_only_with_the_proof(self):
        P = sources.proof_rule()
        import run_trade
        self.assertIs(P, run_trade.PROOF)                              # the constant itself, never a copy
        self.assertEqual(sources.has_proof(12, 6, 50.0), (True, None))
        self.assertFalse(sources.has_proof(9, 9, 50.0)[0])             # n < 10
        self.assertFalse(sources.has_proof(12, 6, -1.0)[0])            # PnL <= 0
        self.assertFalse(sources.has_proof(12, 4, 50.0)[0])            # 33 % < 40 %
        q = {"kind": "wallet_follow", "hits": 9, "n": 12, "closed": 12, "proof": True}
        d = decide.decide(checks_ok(), q)
        self.assertEqual((d["decision"], d["size_sol"]), ("BUY_LIVE", 0.1))
        q = {"kind": "wallet_follow", "hits": 5, "n": 12, "closed": 12, "proof": True}
        self.assertEqual(decide.decide(checks_ok(), q)["decision"], "SKIP")   # proven but EV <= 0
        q = {"kind": "wallet_follow", "hits": 1, "n": 1, "closed": 1, "proof": False}
        d = decide.decide(checks_ok(22_000), q)
        self.assertEqual((d["decision"], d["size_sol"]), ("BUY_PAPER", decide.PAPER_SOL))   # collecting, EV < 0 too
        self.assertLess(d["ev_pct"], 0)
        q = {"kind": "wallet_follow", "hits": 2, "n": 14, "closed": 14, "proof": False, "proof_why": "x"}
        self.assertEqual(decide.decide(checks_ok(), q)["decision"], "SKIP")   # measured, unproven, EV <= 0

    def test_shrink_toward_the_base_rate_and_ev_by_liquidity(self):
        base = decide.PRIOR
        self.assertAlmostEqual(base, 0.52)
        p1 = decide.p_tp(1, 1, base)                                   # 1 winner of 1: barely moves
        self.assertAlmostEqual(p1, (1 + 10 * base) / 11)
        self.assertLess(abs(p1 - base), 0.05)
        p10 = decide.p_tp(10, 10, base)                                # 10 of 10: half the way
        self.assertAlmostEqual(p10, (10 + 10 * base) / 20)
        self.assertGreater(abs(p10 - base), abs(p1 - base))
        self.assertAlmostEqual(decide.ev(0.6, 0.03), 0.6 * 0.15 - 0.4 * 0.10 - 0.03)
        self.assertEqual([build_cost_pct(x) for x in (60_000, 30_000, 22_000, 15_000)], [3.0, 5.0, 8.0, None])
        b = decide.base_for("insider", {"insider": (12, 30)})
        self.assertEqual((b["p"], b["n"]), (0.4, 30))                  # measured base rate once there are enough
        self.assertEqual(decide.base_for("insider", {"insider": (3, 5)})["p"], decide.PRIOR)

    def test_errors_beat_fails_and_fails_name_the_first_check(self):
        c = checks_ok()
        c["flow"] = {"status": "fail", "text": "tok: kupnje 31 % u 5 min < 40 %", "values": {}}
        c["holders"] = {"status": "fail", "text": "holderi: top10 62 % > 45 %", "values": {}}
        d = decide.decide(c, {"kind": "wallet_follow", "n": 0, "closed": 0})
        self.assertEqual((d["decision"], d["key"]), ("SKIP", "holders"))
        self.assertIn("i još: tok", d["reason"])
        c["rug"] = {"status": "error", "text": "rug: RugCheck timeout", "values": {}}
        d = decide.decide(c, {"kind": "wallet_follow", "n": 0, "closed": 0})
        self.assertEqual(d["decision"], "CHECK_FAILED")


class LiveLabel(Env):
    def proven(self, n=12, wins=8, pnl=5.0):
        for i in range(n):
            self.lg.execute("INSERT INTO trades (user, token, symbol, opened_ts, closed_ts, status, size_usd, pnl_usd, "
                            "ret, source, follow_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (LU, addr(300 + i), "X", REPLAY_TS - 9000, REPLAY_TS - 8000, "closed", 25,
                             pnl if i < wins else -2.0, 0.1, "copy wallet HODL", self.fid))
        self.lg.commit()

    def test_buy_live_is_only_a_demo_trade_in_paper(self):
        self.proven()
        self.ingest(REPLAY_TS, REPLAY_TS + 1)
        self.run_worker(good_net(), self.clock(REPLAY_TS + 1.1))
        r = self.row()
        self.assertTrue(r["quality"]["proof"])
        self.assertEqual((r["decision"], r["size_sol"]), ("BUY_LIVE", 0.1))
        got = paper.run_once(self.lg, self.market_fn(), now=REPLAY_TS + 3, path=self.fp, sol=SOL_USD, lim=self.lim)
        self.assertEqual(got[0][0], PU)
        self.assertIn("(demo)", got[0][1])
        self.assertIsNone(self.lg.execute("SELECT 1 FROM trades WHERE user=? AND token=?", (LU, TOK)).fetchone())
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM copy_log WHERE token=?", (TOK,)).fetchone()[0], 0)

    def test_live_is_never_reached_without_the_gate(self):
        self.assertIn("fast_path", settings.LIVE_GATES)
        self.assertIn("tek 0 zatvorenih paper tradeova, treba 30", paper.live_refusal(self.tc))
        settings.put(self.tc, "backtest:fast_path", {"pass": True})
        with self.assertRaises(ValueError) as e:
            settings.set_flag(self.tc, "fast_path", "live", "Jure", paper={"n": 50, "pnl": 9.0},
                              now=REPLAY_TS + 30 * 86400)
        self.assertIn("fast_path ne može u live", str(e.exception))
        self.assertNotEqual(settings.flag("fast_path", con=self.tc), "live")

    def test_live_route_goes_through_the_copy_path_with_the_follow(self):
        """The route's shape only: the module's mode is stubbed to live here, no flag is ever set to live."""
        self.proven()
        self.ingest(REPLAY_TS, REPLAY_TS + 1)
        self.run_worker(good_net(), self.clock(REPLAY_TS + 1.1))
        with mock.patch.object(paper, "mode", lambda: "live"):
            got = paper.run_once(self.lg, self.market_fn(), now=REPLAY_TS + 3, path=self.fp, sol=SOL_USD, lim=self.lim)
        self.assertEqual(settings.flag("fast_path", con=self.tc), "paper")
        self.assertEqual(got[0][0], LU)
        t = self.lg.execute("SELECT source, follow_id FROM trades WHERE user=? AND token=?", (LU, TOK)).fetchone()
        self.assertTrue(t[0].startswith("copy wallet HODL"))           # run_trade: is_copy, _no_proof on the follow
        self.assertEqual(t[1], self.fid)
        self.assertEqual(tuple(self.lg.execute("SELECT ev_ts, action FROM copy_log WHERE follow_id=? AND token=?",
                                               (self.fid, TOK)).fetchone()), (REPLAY_TS, "ulaz"))


# ---------- 5. dedupe, the token cache, 20 at once -----------------------------------------------------------------

class Queue(Env):
    def test_one_check_per_token_and_source_per_10_min(self):
        self.assertEqual(self.ingest(REPLAY_TS, REPLAY_TS + 1, sig="a"), 1)
        enqueue._RECENT.clear()                                        # the database dedupes too, not only memory
        self.ingest(REPLAY_TS + 120, REPLAY_TS + 121, sig="b")
        self.ingest(REPLAY_TS + 599, REPLAY_TS + 600, sig="c")
        n = self.fc.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        self.assertEqual(n, 1)
        self.ingest(REPLAY_TS + 601, REPLAY_TS + 602, sig="d")         # 10 min later: a new check
        self.assertEqual(self.fc.execute("SELECT COUNT(*) FROM signals").fetchone()[0], 2)
        # a signal older than 15 min when it reaches us is not checked
        self.ingest(REPLAY_TS + 2000, REPLAY_TS + 2000 + enqueue.MAX_AGE_S + 5, sig="e")
        self.assertEqual(self.fc.execute("SELECT COUNT(*) FROM signals").fetchone()[0], 2)

    def test_the_copy_loop_hook_and_the_worker_scan_enqueue_and_dedupe(self):
        with mock.patch.object(enqueue, "time", types.SimpleNamespace(time=lambda: REPLAY_TS + 5)):
            n = enqueue.from_copy([(W_HODL, TOK, "buy", REPLAY_TS), (W_HODL, TOK, "sell", REPLAY_TS + 1),
                                   ("nobody", addr(77), "buy", REPLAY_TS)], now=REPLAY_TS + 5)
        self.assertEqual(n, 1)
        self.assertEqual(self.row()["via"], "copy")
        self.ingest(REPLAY_TS, REPLAY_TS + 6)                          # the webhook of the same buy: deduped
        w = worker.Worker(self.fp, good_net(), log=lambda s: None, now_fn=lambda: REPLAY_TS + 7)
        self.assertEqual(w.scan(self.fc, REPLAY_TS + 7, {"hype": self.hp, "kol": self.kp, "tg": ""}), 0)
        self.assertEqual(self.fc.execute("SELECT COUNT(*) FROM signals").fetchone()[0], 1)

    def test_token_cache_60_s_shared_by_every_signal_on_the_token(self):
        net, cache = good_net(), checks.Cache()
        s1 = {"id": 1, "token": TOK, "source_id": W_HODL, "kind": "wallet_follow", "sig_ts": REPLAY_TS}
        s2 = dict(s1, id=2, source_id=addr(55), kind="insider")
        checks.run_all(s1, net, REPLAY_TS + 1, 0.1, cache)
        _r, d, _q = checks.run_all(s2, net, REPLAY_TS + 30, 0.1, cache)
        self.assertTrue(d["cached"])
        self.assertEqual((net.calls["market"], net.calls["rugcheck"]), (1, 1))
        checks.run_all(s2, net, REPLAY_TS + 62, 0.1, cache)            # 60 s later: fetched again
        self.assertEqual((net.calls["market"], net.calls["rugcheck"]), (2, 2))

    def test_at_most_20_checks_at_once(self):
        net = FakeNet()
        net.delay = 0.4
        toks = [addr(400 + i, "", "pump") for i in range(30)]
        now = REPLAY_TS + 2
        for i, t in enumerate(toks):
            net.mk[t] = pair(t)
            net.rc[t] = rc_report()
            enqueue.enqueue(self.fc, {"token": t, "source_id": W_HODL, "sig_ts": REPLAY_TS, "via": "test"},
                            {"kind": "wallet_follow", "label": "HODL", "follow_id": self.fid}, now)
        self.fc.commit()
        w = worker.Worker(self.fp, net, log=lambda s: None, now_fn=lambda: now, cache=checks.Cache())
        w.lim, w.t["sources"] = self.lim, now
        w.step(woke=True)
        st = dict(self.fc.execute("SELECT status, COUNT(*) FROM signals GROUP BY status").fetchall())
        self.assertEqual((st.get("running"), st.get("queued")), (20, 10))   # 20 taken, 10 wait in the queue
        w.step()                                                       # the pool is full: nothing more is taken
        self.assertEqual(dict(self.fc.execute("SELECT status, COUNT(*) FROM signals GROUP BY status").fetchall())
                         .get("queued"), 10)
        w.stop(wait=True)
        self.assertEqual(w.max_parallel, 20)
        self.assertLessEqual(net.max_active, 20)
        self.assertGreater(net.max_active, 1)
        w.step(woke=True)
        w.stop(wait=True)
        n = self.fc.execute("SELECT COUNT(*) FROM signals WHERE decision IS NOT NULL").fetchone()[0]
        self.assertEqual(n, 30)


# ---------- 6. exits ------------------------------------------------------------------------------------------------------

class Exits(Env):
    def enter(self):
        self.ingest(REPLAY_TS, REPLAY_TS + 1)
        self.run_worker(good_net(), self.clock(REPLAY_TS + 1.1))
        return paper.run_once(self.lg, self.market_fn(), now=REPLAY_TS + 3, path=self.fp, sol=SOL_USD, lim=self.lim)

    def test_the_fast_exit_plan_and_the_lots_own_levels(self):
        self.enter()
        p = exitplan.active(self.lg, TOK)
        self.assertEqual(p["plan"]["take_profits"], [{"kind": "pct", "v": 15.0, "sell_share": 0.5}])
        self.assertEqual(p["plan"]["trailing"], {"activate_pct": 15.0, "trail_pct": 8.0})
        self.assertEqual(p["plan"]["stop"], {"kind": "pct", "v": -10.0})
        self.assertEqual(p["plan"]["time_stop"]["after_min"], 45.0)
        self.assertEqual(p["plan"]["accounts"], [PU])
        a = json.loads(self.lg.execute("SELECT auto FROM trades WHERE user=? AND token=?", (PU, TOK)).fetchone()[0])
        self.assertEqual(a["mode"], "tpsl")
        self.assertTrue(a.get("until"))                                # 45 min hold

    def test_copy_exit_when_the_source_wallet_sells(self):
        self.enter()
        con = sqlite3.connect(self.hp)
        con.execute("INSERT INTO chain_trades VALUES (?,?,?,?,?,?)", ("sig-sell", W_HODL, TOK, "sell", REPLAY_TS + 60, 1.7))
        con.commit()
        con.close()
        got = paper.run_once(self.lg, self.market_fn(price=1.6e-5), now=REPLAY_TS + 61, path=self.fp, sol=SOL_USD,
                             lim=self.lim)
        self.assertIn("izvor je prodao", got[0][1])
        t = self.lg.execute("SELECT status, exit_rule FROM trades WHERE user=? AND token=?", (PU, TOK)).fetchone()
        self.assertEqual(tuple(t), ("closed", "wallet_sold"))
        f = self.lg.execute("SELECT status, exit_reason, pnl_usd FROM fast_trades").fetchone()
        self.assertEqual(f[:2], ("closed", "izvor je prodao (copy exit)"))
        self.assertGreater(f[2], 0)


# ---------- 7. outcomes and the report ------------------------------------------------------------------------------

class Outcomes(Env):
    def skip_row(self, key="holders", reason="holderi: top10 62 % > 45 %", t0=REPLAY_TS):
        cur = self.fc.execute("INSERT INTO signals (token, symbol, kind, source_id, source_label, sig_ts, enq_ts, status, "
                              "decided_ts, decision, reason, price0, checks, latency_s, cost_pct) VALUES "
                              "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (TOK, "HODLT", "wallet_follow", W_HODL, "HODL", t0 - 3, t0 - 2, "done", t0, "SKIP", reason,
                               1.0, json.dumps({"key": key, "res": {}}), 3.2, 3.0))
        return cur.lastrowid

    def test_plus_1_5_15_60_max_and_propusteno(self):
        sid = self.skip_row()
        for off, px in ((60, 1.05), (300, 1.25), (900, 1.10), (1800, 0.95), (3600, 0.90)):
            outcomes.put_px(self.fc, TOK, px, None, REPLAY_TS + off)
        outcomes.measure(self.fc, REPLAY_TS + 1000)                    # window open: partial
        self.fc.commit()
        r = self.row(sid)
        self.assertEqual((r["out"]["1m"], r["out"]["5m"], r["out_done"]), (5.0, 25.0, 0))
        n = outcomes.measure(self.fc, REPLAY_TS + 3600 + outcomes.GRACE_S)
        self.fc.commit()
        r = self.row(sid)
        self.assertEqual(n, 1)
        self.assertEqual((r["out"]["15m"], r["out"]["60m"], r["max60"], r["out_done"]), (10.0, -10.0, 25.0, 1))
        self.assertEqual((r["missed"], r["hit"]), (1, 1))              # SKIP and +25 %: propušteno; +15 % first

    def test_sampling_is_capped_and_batched(self):
        self.skip_row()
        calls = []
        n = outcomes.sample(self.fc, REPLAY_TS + 30, fetch=lambda toks: calls.append(list(toks)) or
                            {t: {"price": 1.1, "mcap": 1} for t in toks})
        self.assertEqual((n, calls), (1, [[TOK]]))
        self.assertEqual(outcomes.sample(self.fc, REPLAY_TS + 40, fetch=lambda t: {}), 0)   # sampled 10 s ago

    def test_daily_false_reject_report_and_the_cost_line(self):
        a = self.skip_row()
        b = self.skip_row("flow", "tok: kupnje 31 % u 5 min < 40 %", REPLAY_TS + 5)
        self.fc.execute("UPDATE signals SET out_done=1, max60=30.0, missed=1, hit=1, out=? WHERE id=?",
                        (json.dumps({"max60": 30.0, "min60": -2.0}), a))
        self.fc.execute("UPDATE signals SET out_done=1, max60=3.0, missed=0, hit=0, out=? WHERE id=?",
                        (json.dumps({"max60": 3.0, "min60": -12.0}), b))
        store.add_cost(self.fc, "helius", 2, 8, REPLAY_TS)
        store.add_cost(self.fc, "rugcheck", 5, 0, REPLAY_TS)
        self.fc.commit()
        rep = report.daily(REPLAY_TS + 3600, con=self.fc)
        self.assertEqual(rep["per_check"]["holders"]["false_reject"], 1)
        self.assertEqual(rep["per_check"]["flow"]["saved"], 1)
        self.assertEqual(rep["worst_check"], "holders")
        ln = report.lines(rep)
        self.assertTrue(any(x.startswith("fast_check najčešće krivo odbija: holderi (1 od 1)") for x in ln), ln)
        cost = [x for x in ln if x.startswith("fast_check trošak (dan): 2026-11-10 · ")]
        self.assertEqual(len(cost), 1)
        self.assertIn("Helius 2 poziva, 8 kredita", cost[0])
        self.assertIn("RugCheck 5 poziva (besplatno)", cost[0])
        rows = report.ev_rows(REPLAY_TS + 3600, "paper", path=self.fp, log=lambda s: None)
        self.assertTrue(any(r["part"] == "fast:odbio holderi" for r in rows))


# ---------- 8. the page, the pop-ups, MCP, start.sh, cpuguard --------------------------------------------------------

class Mcp(Env):
    def test_schema_and_dispatch(self):
        from ui import mcpapi
        names = {t["name"]: t for t in mcpapi.TOOLS}
        g = names["get_fast_checks"]
        self.assertTrue(g["annotations"]["readOnlyHint"])
        self.assertEqual(sorted(g["inputSchema"]["properties"]), ["decision", "limit", "since"])
        self.assertEqual(g["inputSchema"]["properties"]["decision"]["enum"], list(store.DECISIONS))
        self.ingest(REPLAY_TS, REPLAY_TS + 1)
        self.run_worker(good_net(), self.clock(REPLAY_TS + 1.1))
        d, err = mcpapi._tool("get_fast_checks", {"since": REPLAY_TS - 60})
        self.assertFalse(err, d)
        s = d["signals"][0]
        self.assertEqual(s["decision"], "BUY_PAPER")
        self.assertEqual(sorted(s["checks"]), sorted(decide.ORDER))
        self.assertEqual(s["checks"]["holders"]["values"]["top10_pct"], 36.0)
        self.assertLess(s["latency_s"], 10)
        self.assertEqual(s["source"]["label"], "HODL")
        self.assertIn("closed", s["source_quality"])
        d, err = mcpapi._tool("get_fast_checks", {"since": REPLAY_TS - 60, "decision": "SKIP"})
        self.assertEqual(d["signals"], [])
        d, err = mcpapi._tool("get_fast_checks", {"decision": "MAYBE"})
        self.assertTrue(err)


class Popups(Env):
    def seed(self, decision="SKIP", reason="holderi: top10 62 % > 45 %", status="done", ts=None):
        ts = ts or int(time.time()) - 120
        res = {k: {"status": "fail" if k == "holders" else "ok", "text": reason if k == "holders" else f"{k} u redu",
                   "values": {}, "ms": 5} for k in decide.ORDER}
        self.fc.execute("INSERT INTO signals (token, symbol, kind, source_id, source_label, sig_ts, enq_ts, status, "
                        "decided_ts, decision, reason, checks, latency_s) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (TOK, "HODLT", "wallet_follow", W_HODL, "HODL", ts, ts + 1, status,
                         ts + 3 if decision else None, decision, reason,
                         json.dumps({"key": "holders", "res": res}) if decision else None, 3.2 if decision else None))
        self.fc.commit()
        return ts

    def test_skip_block_shows_every_check_or_in_progress(self):
        from ui import pravitrade
        ts = self.seed()
        html = view.skip_block(TOK, ts + 30, pravitrade.esc)
        self.assertIn("Fast check:", html)
        self.assertIn("SKIP · 3,2 s od kupnje novčanika · holderi: top10 62 % &gt; 45 %", html)
        for name in ("Rug", "Holderi", "Tok", "Cijena", "Izvor"):
            self.assertIn(f"<td>{name}</td>", html)
        self.assertNotIn("nije rađen", html)
        other = addr(66, "", "pump")
        self.assertIn("fast_check u tijeku", view.skip_block(other, int(time.time()) - 30, pravitrade.esc))
        self.fc.execute("UPDATE signals SET status='retry', decision='CHECK_FAILED', reason='rug: RugCheck HTTP 429'")
        self.fc.commit()
        self.assertIn("CHECK_FAILED", view.skip_block(TOK, ts + 30, pravitrade.esc))

    def test_skip_popup_and_the_skip_box_show_the_fast_check(self):
        from ui import pravitrade
        ts = self.seed()
        t = ts + 20
        self.lg.execute("INSERT INTO copy_log (follow_id, token, side, ev_ts, ts, symbol, action, note, trade_id) "
                        "VALUES (?,?,?,?,?,?,?,?,?)", (self.fid, TOK, "buy", ts, t, "HODLT", "preskočeno",
                                                       "nema svježeg razloga za ulaz", None))
        self.lg.commit()
        with pravitrade._LOCK:
            pravitrade._SK.update(ts=0.0, key=None, html=None, rows=None)
            pravitrade._SKP.update(ts=0.0, key=None, rows=None)
        html = pravitrade.skip_popup("Jure", TOK, str(t), now=t + 30)
        self.assertIn("Fast check:", html)
        self.assertIn("holderi: top10 62 % &gt; 45 %", html)
        self.assertIn("<td>Holderi</td>", html)
        settings.put(self.tc, "invited", ["Ivan"])
        guest = pravitrade.skip_popup("Ivan", TOK, str(t), now=t + 30)
        self.assertIn("<h3 translate=no>HODLT</h3>", guest)            # an invited viewer sees the skip ...
        self.assertNotIn("Fast check:", guest)                         # ... but not the owner's checks
        summ = view.skip_summary([(TOK, t)])
        self.assertTrue(summ[(TOK, t)].startswith("fast_check: SKIP · 3,2 s"))

    def test_token_popup_reason_replaces_nema_svjezeg_razloga(self):
        ts = self.seed(ts=int(time.time()) - 42)
        za, protiv, r = view.token_reason(TOK)
        self.assertTrue(za.startswith("praćeni izvor HODL (praćeni novčanik) kupio prije 4"), za)
        self.assertEqual(protiv, "fast_check: holderi: top10 62 % > 45 %")
        self.assertEqual(r["sig_ts"], ts)


class Card(Env):
    def test_under_jos_owner_only_and_nothing_while_off(self):
        from tests.test_apui_offline import SUMMARY, fake_aplog, fake_equity, history
        from ui import pravitrade
        Popups.seed(self)
        with mock.patch.object(pravitrade, "_equity_mod", lambda: fake_equity(history(), SUMMARY)), \
                mock.patch.object(pravitrade, "_aplog_mod", lambda: fake_aplog()), \
                mock.patch.object(pravitrade, "BG_REFRESH", False):
            settings.put(self.tc, "invited", ["Ivan"])
            _, body = pravitrade.page({}, "Jure")
            self.assertIn("id=fast-path", body)
            self.assertLess(body.index("id=jos"), body.index("id=fast-path"))   # under "Još", the top stays trade-focused
            self.assertIn("holderi: top10 62 % &gt; 45 %", body)
            self.assertIn("3,2 s", body)
            _, guest = pravitrade.page({}, "Ivan")
            self.assertNotIn("id=fast-path", guest)
            settings.put(self.tc, "flag:fast_path", {"mode": "off", "since": 0, "who": "Jure"})
            settings._FLAG_CACHE.clear()
            view.clear()
            _, body = pravitrade.page({}, "Jure")
            self.assertNotIn("id=fast-path", body)


class Wiring(unittest.TestCase):
    def test_flag_g24_start_sh_and_cpuguard(self):
        from ops import cpuguard as g
        self.assertEqual(settings.FLAGS["fast_path"][0], "G24")
        self.assertNotIn("fast_path", settings.DATA_FLAGS)
        self.assertEqual(settings.LIVE_GATES["fast_path"], "fast.paper:live_refusal")
        name, rank, _why = g.classify(["python3", "run_fast.py", "loop"])
        self.assertEqual((name, rank), ("fast", g.LAST))
        with open(os.path.join(ROOT, "start.sh"), encoding="utf-8") as f:
            sh = f.read()
        self.assertIn("low keep fast python3 run_fast.py loop", sh)
        self.assertNotIn("ops.heavy --night run_fast.py", sh)
        with open(os.path.join(ROOT, "trade", "config.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f).get("mode"), "dry")         # never touched

    def test_hooks_are_in_the_ingestion_points(self):
        for path, needle in (("kol/chainwatch.py", "_fast.from_chain(payload, rows)"),
                             ("live/store.py", "_fast.from_live("), ("kol/xhook.py", "_fast.from_calls(calls)"),
                             ("league/copy.py", "_fast.from_copy(evs, now)"),
                             ("league/auto.py", "fpaper.run_once(con)"),
                             ("events/evreport.py", "freport.ev_rows(now, st[\"mode\"], log=log)")):
            with open(os.path.join(ROOT, path), encoding="utf-8") as f:
                self.assertIn(needle, f.read(), path)


if __name__ == "__main__":
    unittest.main()
