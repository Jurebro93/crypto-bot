"""10.11. (Jure, flag insider_copy G14, kol/precall.py): every new pump.fun token captured, launches measured from 10k,
pre-call insiders found, cleaned and copied only in the demo.

Launch capture on by default (only LIVE_NEW_TOKENS=0 / --no-new switch it off) and a bond no longer hidden by the
create row; the +10/+30/+90 min DexScreener checks within their caps; a launch at 10k promoted to the market scanner
as final_stretch (never tradeable); the pre-call window; trades attributed to the signing owner, never to a relayer
(also kol/flows.py); snipers, bots, dev and one-owner bundles out; the caller <-> wallet lift; out-of-sample
promotion; the wallets tier untouched in shadow; follows only in paper and only on the demo account; the webhook only
in paper / live; Grok's label only on the owner's tap; the live proof; flag off does nothing. No network."""
import argparse
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import run_live  # noqa: E402
from kol import chainwatch, flows, precall as pc, store as kstore  # noqa: E402
from league import store as lstore  # noqa: E402
from live import store as livestore  # noqa: E402
from trade import executor, settings  # noqa: E402
from wallets import store as wstore  # noqa: E402

NOW = 1_800_000_000
H, D = 3600, 86400
POOL = "PooL" + "1" * 40


def W(name):
    return (name + "x" * 44)[:44]


INS, SNP, BOTW, DEV, R, NOISE = (W(n) for n in ("Qnsider", "Snyper", "Bxtwal", "Devv", "Reyayer", "Nxise"))
B1, B2, FUND = W("Bundxa"), W("Bundxb"), W("Funder")
US = [W(f"Usr{i}") for i in range(6)]


def M(k):
    return ("Mnt" + str(k) + "z" * 44)[:44]


def tx(sig, ts, mint, trades, signers=None, payer=None, slot=None):
    """A getTransactionsForAddress-style tx: trades [(owner, token delta, SOL delta)]; the pool never signs."""
    signers = list(signers or [o for o, *_ in trades])
    payer = payer or signers[0]
    keys = [payer] + [s for s in signers if s != payer]
    keys += [o for o, *_ in trades if o not in keys] + [POOL]
    pre_b = [10_000_000_000] * len(keys)
    post_b = list(pre_b)
    pre_t, post_t = [], []
    for o, d, sol in trades:
        post_b[keys.index(o)] += int(sol * 1e9)
        pre_t.append({"owner": o, "mint": mint, "uiTokenAmount": {"amount": str(0 if d > 0 else int(-d * 1e6)), "decimals": 6}})
        post_t.append({"owner": o, "mint": mint, "uiTokenAmount": {"amount": str(int(d * 1e6) if d > 0 else 0), "decimals": 6}})
    return {"slot": slot or ts, "blockTime": ts,
            "meta": {"err": None, "preBalances": pre_b, "postBalances": post_b, "preTokenBalances": pre_t,
                     "postTokenBalances": post_t},
            "transaction": {"signatures": [sig], "message": {
                "accountKeys": [{"pubkey": k, "signer": k in signers or k == payer} for k in keys]}}}


BUY, SELL = (1_000_000, -0.5), (-1_000_000, 0.9)


class FakeHelius:
    """wallets/rpc.fetch stand-in: the token's txs inside (since, until], 10 credits a page."""

    def __init__(self, by_mint):
        self.by_mint, self.asked = by_mint, []

    def __call__(self, mint, since_ts=None, until_ts=None, max_pages=3, oldest_first=False, on_credits=None, **_kw):
        self.asked.append(mint)
        for _ in range(max_pages):
            on_credits(10)
        out = [t for t in self.by_mint.get(mint, []) if (since_ts is None or t["blockTime"] > since_ts)
               and (until_ts is None or t["blockTime"] <= until_ts)]
        return sorted(out, key=lambda t: t["blockTime"], reverse=not oldest_first), True


class FakeDex:
    def __init__(self, rows):
        self.rows, self.asked = rows, []

    def __call__(self, tokens):
        self.asked.append(list(tokens))
        return [{"chainId": "solana", "dexId": r.get("dex", "pumpfun"), "baseToken": {"address": m, "symbol": "S"},
                 "marketCap": r["mcap"], "volume": {"h1": r.get("vol", 0)}} for m, r in self.rows.items() if m in tokens]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.p = {k: os.path.join(d, f"{k[:-3]}.db") for k in ("kol_db", "hype_db", "tg_db", "wallet_db", "rug_db",
                                                              "early_db", "minute_db", "league_db")}
        self._env = os.environ.get("EARLY_DB")
        os.environ["EARLY_DB"] = self.p["early_db"]
        self._db, self._ldb = settings.DB, lstore.DB
        settings.DB = os.path.join(d, "trade.db")
        lstore.DB = self.p["league_db"]
        settings._FLAG_CACHE.clear()
        self.tc = executor.connect(settings.DB)
        self.kc = kstore.connect(self.p["kol_db"])
        lstore.connect(self.p["league_db"]).close()
        from league import copy as lcopy
        lc = sqlite3.connect(self.p["league_db"])
        lcopy.ensure(lc)
        lc.close()
        self.hc = livestore.connect(self.p["hype_db"])
        self.hc.execute("CREATE TABLE IF NOT EXISTS chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER, "
                        "sol REAL, PRIMARY KEY (sig, mint))")
        self.wc = wstore.connect(self.p["wallet_db"])

    def tearDown(self):
        settings.DB, lstore.DB = self._db, self._ldb
        settings._FLAG_CACHE.clear()
        if self._env is None:
            os.environ.pop("EARLY_DB", None)
        else:
            os.environ["EARLY_DB"] = self._env
        for c in (self.tc, self.kc, self.hc, self.wc):
            c.close()
        self.tmp.cleanup()

    def flag(self, m, since=NOW - 8 * D):
        settings.set_flag(self.tc, pc.FLAG, m, "Jure", now=since)
        settings._FLAG_CACHE.clear()

    def call(self, tid, tok, h, ts, **kw):
        cols = {"tweet_id": tid, "token": tok, "handle": h, "ts": ts, "kind": "call", **kw}
        self.kc.execute(f"INSERT INTO calls ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", list(cols.values()))

    def kw(self):
        return {k: v for k, v in self.p.items()}


# ===================================================================================================================
# Part 1: capture and measurement from 10k
# ===================================================================================================================
class LaunchCapture(Base):
    def ns(self, **kw):
        return argparse.Namespace(new=kw.get("new", False), no_new=kw.get("no_new", False))

    def test_on_by_default_off_only_on_purpose(self):
        self.assertTrue(run_live.new_tokens_on(self.ns(), env={})[0])                       # LIVE_ARGS without --new
        self.assertTrue(run_live.new_tokens_on(self.ns(), env={"LIVE_NEW_TOKENS": "1"})[0])
        self.assertTrue(run_live.new_tokens_on(self.ns(new=True), env={"LIVE_NEW_TOKENS": "0"})[0])
        self.assertFalse(run_live.new_tokens_on(self.ns(), env={"LIVE_NEW_TOKENS": "0"})[0])
        self.assertFalse(run_live.new_tokens_on(self.ns(no_new=True), env={})[0])
        with open(os.path.join(ROOT, "start.sh"), encoding="utf-8") as f:
            sh = f.read()
        self.assertIn("python3 run_live.py loop ${LIVE_ARGS:-}", sh)

    def test_a_bond_turns_the_create_row_into_the_migration_and_new_launches_go_after_a_day(self):
        m = M(1)
        livestore.add_launches(self.hc, [(m, NOW - 3000, DEV, "Name", "SYM", 1.0, "s1", "pump")])
        livestore.add_launches(self.hc, [(m, NOW - 100, None, "", "", 0.0, "s2", "migration")])
        livestore.add_launches(self.hc, [(m, NOW - 50, None, "", "", 0.0, "s3", "migration")])   # a repeat: ignored
        self.assertEqual(self.hc.execute("SELECT ts, pool, name, symbol, creator FROM live_launches").fetchall(),
                         [(NOW - 100, "migration", "Name", "SYM", DEV)])
        livestore.add_launches(self.hc, [(M(2), NOW - 2 * D, DEV, "", "", 1.0, "s4", "pump"),
                                         (M(3), NOW - 2 * D, DEV, "", "", 1.0, "s5", "migration")])
        livestore.prune(self.hc, NOW)
        self.assertEqual({r[0] for r in self.hc.execute("SELECT mint FROM live_launches")}, {m, M(3)})


class LaunchMeasure(Base):
    def launches(self, rows):
        livestore.add_launches(self.hc, [(m, ts, DEV, "", "S", 1.0, "s" + m[:6], pool) for m, ts, pool in rows])
        self.hc.commit()

    def test_checks_at_10_30_90_caps_dead_and_promotion_to_the_scanner(self):
        self.flag("shadow")
        L = [M(10 + i) for i in range(5)]
        self.launches([(L[0], NOW - 12 * 60, "pump"), (L[1], NOW - 12 * 60, "pump"), (L[2], NOW - 12 * 60, "pump"),
                       (L[3], NOW - 35 * 60, "pump"), (L[4], NOW - 100 * 60, "pump"), (M(99), NOW - 600, "migration")])
        dex = FakeDex({L[0]: {"mcap": 12_000, "vol": 900}, L[1]: {"mcap": 4_000}, L[3]: {"mcap": 8_000, "vol": 500},
                       L[4]: {"mcap": 15_000, "vol": 2000}})
        d = pc.incremental(now=NOW, dex=dex, log=lambda *_: None, **self.kw())
        self.assertEqual(d["launches"]["new"], 5)                       # the bond is the scanner's own source
        self.assertEqual(d["launches"]["checked"], 5)
        self.assertEqual(d["launches"]["reached"], 2)
        self.assertEqual(d["launches"]["dead"], 1)
        self.assertEqual(d["launches"]["dex_calls"], 1)                  # 5 tokens in one batch of 30
        ec = sqlite3.connect(self.p["early_db"])
        st = {m: (k, r, dd) for m, k, r, dd in ec.execute("SELECT mint, checks, reached_ts, dead FROM precall_launch")}
        self.assertEqual(st[L[4]][0], 3)                                 # +10 and +30 merged into the +90 look
        self.assertEqual(st[L[3]][0], 2)
        self.assertEqual(st[L[1]][2], 1)                                 # dead: under 5k with no volume
        # 20 min later: only L[2] (no pair yet, now 32 min old) is due; L[3] already had its +30, L[1] is dead
        d2 = pc.incremental(now=NOW + 20 * 60, dex=dex, log=lambda *_: None, **self.kw())
        self.assertEqual(dex.asked[-1], [L[2]])
        self.assertEqual(d2["launches"]["checked"], 1)
        self.assertEqual({m for m, _s in pc.reached(NOW + 20 * 60)}, {L[0], L[4]})
        # the scanner takes them as candidates; on the curve they are final_stretch and never tradeable
        from scan import filters, market, store as sstore
        c = {}
        market.from_launches(NOW + 20 * 60, c)
        self.assertEqual(set(c), {L[0], L[4]})
        self.assertEqual(c[L[0]]["via"], {"launch10k"})
        self.assertEqual(filters.stage_filter({"curve": True, "mcap": 12_000}, sstore.config())[:2], ("final_stretch", False))
        ec.close()

    def test_dexscreener_caps_per_pass_and_per_day(self):
        self.flag("shadow")
        self.launches([(M(100 + i), NOW - 12 * 60, "pump") for i in range(40)])
        dex = FakeDex({})
        cfg = {"insider_copy": {"dex_calls_pass": 1, "dex_calls_day": 2}}
        d = pc.incremental(cfg=cfg, now=NOW, dex=dex, log=lambda *_: None, **self.kw())
        self.assertEqual(d["launches"]["checked"], 30)
        self.assertEqual(d["launches"]["dex_calls"], 1)
        pc.incremental(cfg=cfg, now=NOW + 60, dex=dex, log=lambda *_: None, **self.kw())
        d3 = pc.incremental(cfg=cfg, now=NOW + 120, dex=dex, log=lambda *_: None, **self.kw())
        self.assertEqual(d3["launches"]["dex_calls"], 0)                 # the day's 2 calls are spent
        self.assertEqual(sum(-(-len(a) // 30) for a in dex.asked), 2)


# ===================================================================================================================
# Part 2: the pre-call window, attribution, cleaning, lift, out of sample
# ===================================================================================================================
C = pc.config({})


class Window(unittest.TestCase):
    def test_buys_between_the_first_trade_or_six_hours_before_and_the_call(self):
        t0, ws = NOW, NOW - 2 * H
        trades = [("a", ws - 10, "buy", 1.0, None, "x"),          # before the window
                  ("b", ws + 5, "buy", 1.0, None, "x"),           # in it
                  ("b", t0 + 300, "sell", 2.0, None, "x"),        # sold into the call
                  ("c", t0 - 60, "buy", 0.01, None, "x"),         # dust
                  ("d", t0 + 10, "buy", 1.0, None, "x"),          # after the call
                  ("e", t0 - 600, "buy", None, None, "y")]        # amount unknown: kept
        agg = pc.aggregate(trades, ws, t0, C)
        self.assertEqual(set(agg), {"b", "e"})
        self.assertEqual(agg["b"][:4], [ws + 5, 1.0, t0 + 300, 2.0])
        self.assertIsNone(agg["e"][1])

    def test_the_window_starts_at_the_first_trade_or_six_hours_before_the_call(self):
        rows = [(NOW - 3 * H, NOW), (NOW - 9 * H, NOW)]
        out = [max(ft, t0 - C["pre_window_s"]) for ft, t0 in rows]
        self.assertEqual(out, [NOW - 3 * H, NOW - 6 * H])


class Attribution(unittest.TestCase):
    def test_a_relayed_swap_belongs_to_the_owner_never_to_the_fee_payer(self):
        t = tx("r1", NOW, M(1), [(US[0], *BUY)], signers=[R, US[0]], payer=R)
        self.assertEqual([(w, k) for w, _ts, k, _s in flows._swaps([t], M(1))], [(US[0], "buy")])
        rows = [(R, US[i]) for i in range(5)]
        from kol import groupdisc as gd
        self.assertEqual(gd.relayers(rows, C["relayer_min"]), {R})


class Lift(unittest.TestCase):
    def test_lift_against_chance(self):
        self.assertEqual(pc.lift(4, 4, 5, 20)[0], 4.0)     # 4 of its 4 tokens are the caller's 5 of 20
        self.assertEqual(pc.lift(1, 4, 5, 20)[0], 1.0)
        self.assertEqual(pc.lift(1, 0, 5, 20)[0], None)

    def obs(self, t0, front_min=20, rose=1, first_trade=None, callers=None):
        callers = callers or {"big": (t0, rose)}
        return {"token": f"t{t0}", "t0": t0, "buy_ts": t0 - front_min * 60, "callers": callers, "sold_ts": t0 + 300,
                "sol_in": 1.0, "sol_out": 2.0, "first_trade": first_trade}

    def totals(self):
        from collections import Counter
        return {"all": (20, Counter({"big": 6})), "sel": (12, Counter({"big": 4})), "conf": (8, Counter({"big": 2}))}

    def test_select_on_the_older_two_thirds_confirm_on_the_newer_third(self):
        cut = NOW - 10 * D
        sel = [self.obs(NOW - (20 - i) * D) for i in range(3)]
        conf = [self.obs(NOW - (5 - i) * D) for i in range(2)]
        s = pc.wallet_stats(sel + conf, cut, C, self.totals())
        self.assertEqual(s["status"], "confirmed")
        self.assertEqual((s["first_sel"], s["first_conf"]), (3, 2))
        self.assertEqual(s["sold_into"], 1.0)
        self.assertEqual(s["med_min"], 20.0)
        self.assertGreater(s["links"]["big"]["lift"], 1)
        self.assertEqual(pc.wallet_stats(sel, cut, C, self.totals())["status"], "candidate")      # nothing new yet
        self.assertEqual(pc.wallet_stats(sel[:2] + conf, cut, C, self.totals())["status"], "watch")
        flop = [self.obs(NOW - (20 - i) * D, rose=0) for i in range(3)]
        self.assertEqual(pc.wallet_stats(flop + conf, cut, C, self.totals())["status"], "watch")   # no +30 %

    def test_a_sniper_buys_in_the_first_seconds_of_every_launch(self):
        cut = NOW - 10 * D
        obs = [self.obs(NOW - (20 - i) * D, front_min=180, first_trade=NOW - (20 - i) * D - 180 * 60 + 4)
               for i in range(3)] + [self.obs(NOW - (5 - i) * D, front_min=180,
                                              first_trade=NOW - (5 - i) * D - 180 * 60 + 2) for i in range(2)]
        s = pc.wallet_stats(obs, cut, C, self.totals())
        self.assertEqual(s["status"], "excluded")
        self.assertIn("sniper", s["why"])

    def test_front_running_one_caller_after_the_first_call_counts_through_the_lift(self):
        cut = NOW - 10 * D

        def o(t0):   # a small channel calls first, the wallet buys 5 min later and 20 min before the influencer
            x = self.obs(t0, callers={"small": (t0 - 25 * 60, 0), "big": (t0 + 30 * 60, 1)})
            x["buy_ts"] = t0 - 20 * 60
            x["t0"] = t0 - 25 * 60
            return x
        s = pc.wallet_stats([o(NOW - (20 - i) * D) for i in range(3)] + [o(NOW - (5 - i) * D) for i in range(2)],
                            cut, C, self.totals())
        self.assertEqual(s["n_first"], 0)
        self.assertEqual(s["best_caller_sel"], "big")
        self.assertEqual(s["status"], "confirmed")


class Scenario(Base):
    """Calls of two callers on 18 tokens over 25 days; Helius is a fake that serves each token's trades."""

    def setUp(self):
        super().setUp()
        self.helius = FakeHelius({})
        self.ins_tokens = []
        k = 0
        # 4 older + 3 newer tokens of "big" (the insider front-runs 4 + 2 of them), 4 more "big" tokens without him,
        # 7 tokens of "other" only
        plan = [(25 - i * 3, "big", i < 4) for i in range(4)] + [(6 - i * 2, "big", i < 2) for i in range(3)]
        plan += [(23 - i * 4, "big", False) for i in range(4)] + [(24 - i * 3, "other", False) for i in range(7)]
        for days, caller, ins in plan:
            k += 1
            mint, t0 = M(k), NOW - days * D
            L = t0 - 3 * H
            self.kc.execute("INSERT INTO tokens (token, created_ts) VALUES (?, ?)", (mint, L))
            self.call(f"c{k}", mint, caller, t0, mcap0=50_000, r1h=0.5)
            self.hc.execute("INSERT INTO live_launches VALUES (?,?,?,?,?,?,?,?)", (mint, L, DEV, "", "", 1.0, f"l{k}", "pump"))
            txs = [tx(f"d{k}", L + 60, mint, [(DEV, *BUY)]), tx(f"s{k}", L + 3, mint, [(SNP, *BUY)]),
                   tx(f"n{k}", t0 - 15 * 60, mint, [(W(f"Nxise{k}"), *BUY)])]
            if ins:
                self.ins_tokens.append(mint)
                txs += [tx(f"i{k}", t0 - 20 * 60, mint, [(INS, *BUY)]), tx(f"j{k}", t0 + 600, mint, [(INS, *SELL)]),
                        tx(f"b{k}", t0 - 25 * 60, mint, [(BOTW, *BUY)]),
                        tx(f"x{k}", t0 - 30 * 60, mint, [(B1, *BUY)]), tx(f"y{k}", t0 - 29 * 60, mint, [(B2, *BUY)])]
            if k <= 5:   # five traders through one relayer (gasless swaps)
                txs.append(tx(f"r{k}", t0 - 40 * 60, mint, [(US[k - 1], *BUY)], signers=[R, US[k - 1]], payer=R))
                self.kc.execute("INSERT INTO insiders VALUES (?,?,?,?,?,?,?)", (R, mint, t0, t0 - 40 * 60, t0 + 60, 1.0, 1.2))
            self.helius.by_mint[mint] = txs
        self.call("low", M(90), "big", NOW - 3 * D, mcap0=5_000)       # under 10k: never analysed
        self.kc.commit()
        self.hc.commit()
        self.wc.execute("INSERT INTO wallets (wallet, first_seen, last_seen, labels) VALUES (?,?,?,?)",
                        (BOTW, NOW, NOW, json.dumps(["bot"])))
        for w in (INS, SNP):   # scored by run_wallets: a tier the trading code reads
            self.wc.execute("INSERT INTO wallets (wallet, first_seen, last_seen, tier, copy_score, score, labels) "
                            "VALUES (?,?,?,?,?,?,?)", (w, NOW - D, NOW - D, "A", 50.0, 60.0, "[]"))
        for w in (B1, B2):
            self.wc.execute("INSERT INTO wallet_sightings VALUES (?,?,?,?,?,?,?)",
                            (w, "", "test", "seen", NOW, None, json.dumps({"funder": FUND})))
        self.wc.commit()

    def night(self, **kw):
        return pc.night(now=NOW, force=True, fetch=self.helius, log=lambda *_: None, **{**self.kw(), **kw})

    def status(self):
        ec = sqlite3.connect(self.p["early_db"])
        try:
            return {w: (s, why) for w, s, why in ec.execute("SELECT wallet, status, why FROM precall_wallets")}
        finally:
            ec.close()

    def test_night_finds_the_insider_and_cleans_the_rest(self):
        self.flag("shadow")
        d = self.night(credits=3000)
        self.assertEqual(d["mints_read"], 18)                            # the 5k call is not read
        self.assertEqual(d["credits"], 18 * 30)
        st = self.status()
        self.assertEqual(st[INS][0], "confirmed")
        self.assertEqual(st[SNP][0], "excluded")
        self.assertIn("sniper", st[SNP][1])
        self.assertEqual(st[BOTW][0], "excluded")
        self.assertIn("bot", st[BOTW][1])
        self.assertEqual(st[DEV][0], "excluded")
        self.assertIn("dev", st[DEV][1])
        self.assertNotIn(R, st)                                          # a relayer is never a trader
        self.assertTrue(all(w not in st or st[w][0] not in ("candidate", "confirmed") for w in (B1, B2)))
        ec = sqlite3.connect(self.p["early_db"])
        self.assertEqual(ec.execute("SELECT COUNT(*) FROM precall_trades WHERE wallet = ?", (R,)).fetchone()[0], 0)
        self.assertEqual(ec.execute("SELECT COUNT(*) FROM precall_trades WHERE wallet IN (?,?,?,?,?)", US[:5]).fetchone()[0], 5)
        n, lf = ec.execute("SELECT n, lift FROM precall_links WHERE wallet = ? AND handle = 'big'", (INS,)).fetchone()
        self.assertEqual(n, 6)
        self.assertGreater(lf, 1.5)
        self.assertIsNone(ec.execute("SELECT 1 FROM precall_tokens WHERE token = ?", (M(90),)).fetchone())
        ec.close()
        # the mirrors: kol.db caller <-> wallet, wallets.db its own table
        self.assertEqual(self.kc.execute("SELECT handle, n FROM precall_links WHERE wallet = ?", (INS,)).fetchall(), [("big", 6)])
        self.assertEqual(self.wc.execute("SELECT label, status FROM precall_insiders WHERE wallet = ?", (INS,)).fetchone(),
                         ("precall_insider", "confirmed"))
        # a mint is never fetched twice
        asked = len(self.helius.asked)
        self.night(credits=3000)
        self.assertEqual(len(self.helius.asked), asked)

    def test_the_credit_cap_of_a_pass(self):
        self.flag("shadow")
        d = self.night(credits=100)
        self.assertEqual(d["mints_read"], 3)
        self.assertLessEqual(d["credits"], 100)

    def test_the_tier_the_trading_code_reads_is_untouched_in_shadow(self):
        before = self.wc.execute("SELECT * FROM wallets ORDER BY wallet").fetchall()
        self.flag("shadow")
        self.night(credits=3000)
        pc.incremental(now=NOW + 60, dex=FakeDex({}), log=lambda *_: None, **self.kw())
        self.assertEqual(self.wc.execute("SELECT * FROM wallets ORDER BY wallet").fetchall(), before)
        from league import copy as lcopy
        with mock.patch.dict(os.environ, {"WALLET_DB": self.p["wallet_db"]}):
            self.assertEqual(lcopy._wallet_tiers([INS, SNP]), {INS: "A", SNP: "A"})

    def follows(self, user=None):
        lc = sqlite3.connect(self.p["league_db"])
        try:
            q = "SELECT user, target, active, exit FROM follows WHERE kind = 'wallet'" + (" AND user = ?" if user else "")
            return lc.execute(q, (user,) if user else ()).fetchall()
        finally:
            lc.close()

    def shadow_lines(self):
        lc = sqlite3.connect(self.p["league_db"])
        try:
            return lc.execute("SELECT token, old_action, new_action FROM shadow_decisions WHERE flag = ?", (pc.FLAG,)).fetchall()
        finally:
            lc.close()

    def test_copy_follows_only_in_paper_and_only_on_the_demo_account(self):
        self.flag("shadow")
        self.night(credits=3000)
        new_tok = M(200)
        self.hc.execute("INSERT INTO chain_trades VALUES (?,?,?,?,?,?)", ("z1", INS, new_tok, "buy", NOW + 30, 1.0))
        self.hc.commit()
        cp = pc.incremental(now=NOW + 60, dex=FakeDex({}), log=lambda *_: None, **self.kw())["copy"]
        self.assertEqual(self.follows(), [])                                    # shadow: nobody follows
        self.assertEqual((cp["set"], cp["seen"]), (1, 1))
        lines = self.shadow_lines()
        self.assertIn((new_tok, "nema", "kopiraj kupnju insajdera"), lines)
        self.assertIn((INS, "ne prati", "prati insajdera (mirror)"), lines)
        self.flag("paper", since=NOW + 100)
        pc.incremental(now=NOW + 1000, dex=FakeDex({}), log=lambda *_: None, **self.kw())
        f = self.follows()
        self.assertEqual([(u, t, a) for u, t, a, _e in f], [(settings.PAPER_USER, INS, 1)])
        self.assertEqual(json.loads(f[0][3])["mode"], "mirror")                  # sells when he sells
        self.assertEqual(self.follows(settings.LEAGUE_USER), [])                 # the real Autopilot only logs
        pc.incremental(now=NOW + 2000, dex=FakeDex({}), log=lambda *_: None, **self.kw())
        self.assertEqual(len(self.follows()), 1)                                 # not twice
        self.flag("shadow", since=NOW + 2100)
        pc.incremental(now=NOW + 3000, dex=FakeDex({}), log=lambda *_: None, **self.kw())
        self.assertEqual([a for _u, _t, a, _e in self.follows()], [0])           # back to shadow: stopped

    def test_an_owner_follow_of_the_same_wallet_is_never_taken_over(self):
        from league import copy as lcopy
        self.flag("shadow")
        self.night(credits=3000)
        lc = sqlite3.connect(self.p["league_db"])
        lc.row_factory = sqlite3.Row
        fid = lcopy.follow(lc, settings.PAPER_USER, "wallet", INS, "moj", 40, 7, "tpsl", "50%", "-20%")
        lc.close()
        self.flag("paper", since=NOW + 100)
        pc.incremental(now=NOW + 1000, dex=FakeDex({}), log=lambda *_: None, **self.kw())
        lc = sqlite3.connect(self.p["league_db"])
        self.assertEqual(lc.execute("SELECT id, label, size_usd, per_day FROM follows WHERE kind = 'wallet'").fetchall(),
                         [(fid, "moj", 40.0, 7)])
        lc.close()

    def test_the_webhook_takes_them_only_in_paper_or_live(self):
        self.flag("shadow")
        self.night(credits=3000)
        cfg = {"max_wallets": 100, "share": {"ids": 0.4, "copy": 0.3, "signal": 0.1, "insajderi": 0.2}}
        empty = os.path.join(self.tmp.name, "empty_wallets.db")
        self.assertEqual(pc.webhook_wallets(), [])
        self.assertNotIn(INS, chainwatch.wanted(self.kc, cfg, wallet_db=empty))
        self.flag("paper", since=NOW + 100)
        self.assertEqual(pc.webhook_wallets(), [INS])
        self.assertIn(INS, chainwatch.wanted(self.kc, cfg, wallet_db=empty))

    def test_grok_label_counts_only_after_the_owners_tap(self):
        from ui import assistnotes
        self.flag("shadow")
        self.night(credits=3000)
        ec = sqlite3.connect(self.p["early_db"])
        self.assertEqual([w for w, _s in pc.copy_set(ec)], [INS])
        r = assistnotes.submit_suggestion(self.tc, "grok", "INS je bot", "kupuje svaki token",
                                          proposed_change={"insider_label": {"wallet": INS, "label": "bot", "note": "x"}})
        nid = r["id"]
        self.assertEqual(pc.owner_labels(), {})
        self.assertEqual([w for w, _s in pc.copy_set(ec)], [INS])               # proposed only: still copied
        cands = pc.candidates()
        self.assertEqual(cands["wallets"][0]["proposed_labels"][0]["label"], "bot")
        self.assertEqual(cands["wallets"][0]["callers_front_run"][0]["caller"], "big")
        self.assertTrue(cands["wallets"][0]["examples"][0]["sold_into_call"])
        assistnotes.decide(self.tc, nid, "prihvaćeno")
        self.assertEqual(pc.owner_labels(), {})                                  # "agree" changes nothing
        status, _words = assistnotes.apply(self.tc, nid)
        self.assertEqual(status, "primijenjeno")
        self.assertEqual(pc.owner_labels()[INS]["label"], "bot")
        self.assertEqual(pc.copy_set(ec), [])                                    # bot: never copied
        ec.close()
        with self.assertRaises(ValueError):
            pc.parse_label({"wallet": "nije-adresa", "label": "bot"})
        with self.assertRaises(ValueError):
            pc.parse_label({"wallet": INS, "label": "kit"})
        from ui import mcpapi
        names = {t["name"]: t for t in mcpapi.TOOLS}
        self.assertTrue(names["get_insider_candidates"]["annotations"]["readOnlyHint"])
        self.assertIn("insider_label", names["submit_suggestion"]["description"])
        out, err = mcpapi._tool("get_insider_candidates", {"min_tokens": 3, "limit": 5})
        self.assertFalse(err)
        self.assertEqual(out["wallets"][0]["wallet"], INS)

    def test_live_needs_twenty_closed_paper_copies_with_ev_above_zero(self):
        self.flag("shadow")
        self.night(credits=3000)
        self.flag("paper", since=NOW - 8 * D)
        pc.incremental(now=NOW - 8 * D + 60, dex=FakeDex({}), log=lambda *_: None, **self.kw())
        settings.put(self.tc, f"backtest:{pc.FLAG}", {"pass": True, "ts": NOW})
        ec = sqlite3.connect(self.p["early_db"])
        fid = ec.execute("SELECT follow_id FROM precall_follows").fetchone()[0]
        ec.close()
        lc = sqlite3.connect(self.p["league_db"])

        def trades(n, ret):
            for i in range(n):
                cur = lc.execute("INSERT INTO trades (user, token, opened_ts, closed_ts, status, size_usd, pnl_usd, ret) "
                                 "VALUES (?,?,?,?,?,?,?,?)", (settings.PAPER_USER, M(300 + i), NOW - 5 * D, NOW - 4 * D,
                                                               "closed", 25.0, 25 * ret, ret))
                lc.execute("UPDATE trades SET follow_id = ? WHERE id = ?", (fid, cur.lastrowid))
            lc.commit()
        trades(19, 0.2)
        paper = {"n": 30, "pnl": 100.0}
        with self.assertRaisesRegex(ValueError, "19 od 20"):
            settings.set_flag(self.tc, pc.FLAG, "live", "Jure", paper=paper, now=NOW)
        trades(1, -2.0)                     # 11.11. (trade/edge): EV +9 % but the 90 % interval reaches below 0
        with self.assertRaisesRegex(ValueError, "nije prošao.*donja granica"):
            settings.set_flag(self.tc, pc.FLAG, "live", "Jure", paper=paper, now=NOW)
        trades(10, 0.3)
        self.assertEqual(settings.flag(pc.FLAG, con=self.tc), "paper")           # never automatic
        settings.set_flag(self.tc, pc.FLAG, "live", "Jure", paper=paper, now=NOW)
        self.assertEqual(settings.flag(pc.FLAG, con=self.tc), "live")
        lc.close()

    def test_report_section(self):
        self.flag("shadow")
        self.night(credits=3000)
        d = pc.report_data(NOW + 60)
        self.assertEqual(d["status"]["confirmed"], 1)
        self.assertEqual(d["cost_24h"]["night"]["helius_credits"], 18 * 30)
        from report import render
        html = render.insajderi_body(d)
        self.assertIn("potvrđenih", html)


class FlagOff(Base):
    def test_flag_off_does_nothing(self):
        self.assertEqual(settings.flag(pc.FLAG, con=self.tc), "off")
        self.assertEqual(settings.FLAGS[pc.FLAG][0], "G14")
        self.assertNotIn(pc.FLAG, settings.DATA_FLAGS)
        livestore.add_launches(self.hc, [(M(1), NOW - 700, DEV, "", "", 1.0, "s", "pump")])
        self.hc.commit()
        self.call("c1", M(1), "big", NOW - D, mcap0=50_000)
        self.kc.commit()
        dex, helius = FakeDex({M(1): {"mcap": 50_000}}), FakeHelius({})
        self.assertIsNone(pc.incremental(now=NOW, dex=dex, fetch=helius, log=lambda *_: None, **self.kw()))
        self.assertIsNone(pc.night(now=NOW, force=True, fetch=helius, log=lambda *_: None, **self.kw()))
        self.assertEqual((dex.asked, helius.asked), ([], []))                     # no network
        self.assertFalse(os.path.exists(self.p["early_db"]))                      # no database
        self.assertEqual(pc.reached(NOW), [])
        self.assertEqual(pc.webhook_wallets(), [])
        self.assertEqual(pc.candidates()["wallets"], [])
        self.assertIsNone(pc.report_data(NOW))

    def test_cpuguard_and_start_sh_know_the_passes(self):
        from ops import cpuguard as g
        self.assertEqual(g.classify(["python3", "-m", "kol.precall", "incr"])[:2], ("insajderi", g.JOBS))
        with open(os.path.join(ROOT, "start.sh"), encoding="utf-8") as f:
            sh = f.read()
        self.assertIn("python3 -m ops.heavy --night -m kol.precall night", sh)
        self.assertIn("low python3 -m kol.precall incr", sh)


if __name__ == "__main__":
    unittest.main()
