"""Skener tržišta (scan/, flag market_scan): offline, every network call replaced by a stand-in.

Covers: flag off does nothing; one row per token from several discovery sources and one get_market_signals row per
token (dedupe with the callers); the per-token cache; the Helius credit cap stops the checks cleanly; stage / fees /
rug filters; beta matching and the meta-state measure; X momentum (and Grok's rows first); lead_time_min; the shadow
trade path; the paper gate (>= 30 outcomes and EV > 0) and set_flag refusing paper without it.
"""
import calendar
import contextlib
import json
import math
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from scan import filters, market, meta, shadow, store, xmom
from trade import settings

WSOL = "So11111111111111111111111111111111111111112"
ALPH = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
NOW = calendar.timegm((2026, 11, 10, 23, 30, 0))   # 23:30 UTC: the hourly slice of every day cap is the whole cap
SYSTEM = "11111111111111111111111111111111"


def b58(b):
    n, s = int.from_bytes(b, "big"), ""
    while n:
        n, r = divmod(n, 58)
        s = ALPH[r] + s
    return s


def mint(i):
    m = b58(bytes([i + 3]) * 30 + b"\x09\x05")
    assert any(ch.isdigit() for ch in m) and 32 <= len(m) <= 44, m
    return m


A, B, C, P = mint(1), mint(2), mint(3), mint(4)


def dpair(tok, sym="ABC", name=None, dex="pumpswap", liq=40_000, mcap=300_000, vol_h1=60_000, buys=250, sells=150,
          price=0.0003, ch_h1=10.0, ch_h24=50.0):
    return {"chainId": "solana", "dexId": dex, "url": f"https://dexscreener.com/solana/{tok}",
            "baseToken": {"address": tok, "symbol": sym, "name": name or sym.title()},
            "quoteToken": {"address": WSOL, "symbol": "SOL"}, "priceUsd": str(price), "priceNative": str(price / 150),
            "liquidity": {"usd": liq}, "marketCap": mcap, "fdv": mcap,
            "volume": {"m5": vol_h1 / 12, "h1": vol_h1, "h24": vol_h1 * 10},
            "txns": {"m5": {"buys": 20, "sells": 10}, "h1": {"buys": buys, "sells": sells}},
            "priceChange": {"m5": 1.0, "h1": ch_h1, "h24": ch_h24}}


def gt_pool(tok, sym="ABC", dex="pumpswap", mcap=300_000):
    return {"attributes": {"name": f"{sym} / SOL", "base_token_price_usd": "0.0003", "market_cap_usd": str(mcap),
                           "reserve_in_usd": "40000", "volume_usd": {"m5": "5000", "h1": "60000", "h24": "600000"},
                           "transactions": {"h1": {"buys": 250, "sells": 150, "buyers": 180, "sellers": 90},
                                            "m5": {"buys": 20, "sells": 10}},
                           "price_change_percentage": {"m5": "1", "h1": "10", "h24": "50"}},
            "relationships": {"base_token": {"data": {"id": f"solana_{tok}"}}, "dex": {"data": {"id": dex}}}}


class FakeNet:
    """DexScreener, GeckoTerminal, Helius and X stand-ins that count their calls."""

    def __init__(self):
        self.pairs, self.gt_data, self.tweets = {}, {}, []
        self.calls = {"dex": 0, "gt": 0, "helius": 0, "x": 0, "lists": 0}
        self.mint_auth = None
        self.x_get = None

    def dex_pairs(self, tokens):
        self.calls["dex"] += 1
        return [p for t in tokens for p in self.pairs.get(t, [])]

    def dex_lists(self):
        self.calls["lists"] += 1
        return []

    def gt(self, path, params):
        self.calls["gt"] += 1
        return self.gt_data.get(path) or {"data": []}

    def helius_ready(self):
        return True

    def helius(self, method, params):
        self.calls["helius"] += 1
        if method == "getAccountInfo":
            return {"value": {"data": {"parsed": {"info": {"decimals": 6, "supply": "1000000000000000",
                                                          "mintAuthority": self.mint_auth, "freezeAuthority": None}}}}}
        if method == "getTokenLargestAccounts":
            return {"value": [{"address": "POOLACC", "uiAmount": 3e8}]
                    + [{"address": f"ACC{i}", "uiAmount": 2e7} for i in range(12)]}
        if method == "getMultipleAccounts":
            addrs, opts = params
            if opts["encoding"] == "jsonParsed":
                return {"value": [{"data": {"parsed": {"info": {"owner": "POOLOWNER" if a == "POOLACC" else "W" + a}}}}
                                  for a in addrs]}
            return {"value": [{"owner": "pAMMprogram"} if o == "POOLOWNER" else {"owner": SYSTEM} for o in addrs]}
        if method == "getTokenAccounts":
            return {"token_accounts": [{"owner": f"H{i}"} for i in range(300)]}
        raise AssertionError(method)

    def x(self, query, cursor):
        self.calls["x"] += 1
        return {"tweets": self.tweets, "has_next_page": False}


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        j = lambda n: os.path.join(self.d, n)  # noqa: E731
        self.p = {"hype": j("hype.db"), "kol": j("kol.db"), "tg": j("tg.db"), "league": j("league.db"),
                  "wallets": j("wallets.db")}
        self.trade = j("trade.db")
        self.env = mock.patch.dict(os.environ, {"SCAN_DB": j("scan.db"), "XFEAT_DB": j("xfeat.db")})
        self.env.start()
        self.patches = [mock.patch("usage.meter.record"),
                        mock.patch("league.copy._rugged", return_value=None),
                        mock.patch("league.copy._concentration", return_value=(None, "nepoznato")),
                        mock.patch("ops.heavy.slot", lambda **kw: contextlib.nullcontext(True)),
                        mock.patch("scan.market.followed_wallets", return_value=set())]
        for p in self.patches:
            p.start()
        from kol import store as kstore
        from live import store as lstore
        kstore.connect(self.p["kol"]).close()
        hc = lstore.connect(self.p["hype"])
        hc.execute("CREATE TABLE IF NOT EXISTS hype_signals (ts INTEGER, token TEXT, symbol TEXT, name TEXT, mcap REAL)")
        hc.execute("CREATE TABLE IF NOT EXISTS chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER, "
                   "sol REAL, PRIMARY KEY (sig, mint))")
        hc.close()
        self.net = FakeNet()
        self.cfg = store.config()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.env.stop()
        settings._FLAG_CACHE.clear()

    def flag(self, mode="shadow"):
        tcon = settings.connect(self.trade)
        try:
            settings.put(tcon, "flag:market_scan", {"mode": mode, "since": NOW, "who": "test"}, "test")
        finally:
            tcon.close()
        settings._FLAG_CACHE.clear()

    def run_pass(self, now=NOW, cfg=None):
        return market.pass_once(now, self.net, cfg or self.cfg, self.p, settings_path=self.trade)

    def migrated(self, tok, ts=NOW - 600, sym="ABC"):
        from live import store as lstore
        hc = lstore.connect(self.p["hype"])
        lstore.add_launches(hc, [(tok, ts, "", "", sym, 0.0, "sig" + tok[:5], "migration")])
        hc.close()

    def scan(self):
        return sqlite3.connect(os.environ["SCAN_DB"])


class FlagOff(Base):
    def test_flag_off_touches_nothing(self):
        self.migrated(A)
        self.net.pairs[A] = [dpair(A)]
        self.assertEqual(self.run_pass(), {"off": True})
        self.assertEqual(sum(self.net.calls.values()), 0)                       # no network
        self.assertFalse(os.path.exists(os.environ["SCAN_DB"]))                 # no database
        with mock.patch("ui.pravitrade.gather_callers", return_value=[]):
            from ui import mcpapi
            with mock.patch("scan.store.on", return_value=False):
                self.assertEqual(mcpapi.signals(NOW, source="scan")["signals"], [])
                self.assertEqual(mcpapi.signals(NOW)["signals"], [])

    def test_flag_is_last_and_g11(self):
        self.assertEqual(list(settings.FLAGS)[-1], "market_scan")
        self.assertEqual(settings.FLAGS["market_scan"][0], "G11")
        self.assertNotIn("market_scan", settings.DATA_FLAGS)
        tcon = settings.connect(self.trade)
        try:
            self.assertEqual(settings.flag("market_scan", con=tcon), "off")    # default off
        finally:
            tcon.close()


class Pass(Base):
    def setUp(self):
        super().setUp()
        self.flag()
        self.migrated(A)
        kc = sqlite3.connect(self.p["kol"])
        kc.execute("INSERT INTO kv VALUES ('x', '1')")
        kc.execute("CREATE TABLE IF NOT EXISTS graduates (token TEXT PRIMARY KEY, pool TEXT, symbol TEXT, created_ts "
                   "INTEGER, fdv REAL, vol24 REAL, first_seen INTEGER, source TEXT, seen INTEGER DEFAULT 1)")
        kc.execute("INSERT INTO graduates VALUES (?,?,?,?,?,?,?,?,1)", (A, "pool", "ABC", NOW - 900, 300000, 1, NOW - 900, "g"))
        kc.commit()
        kc.close()
        self.net.pairs[A] = [dpair(A), dpair(A, dex="pumpfun", liq=0, vol_h1=100)]
        self.net.gt_data["/dexes/pumpswap/pools"] = {"data": [gt_pool(A)]}

    def test_one_row_per_token_from_three_sources_and_the_cache(self):
        out = self.run_pass()
        self.assertEqual(out["passed"].get("scan"), 1, out)
        con = self.scan()
        rows = con.execute("SELECT token, via, stage, tradeable, passed, holders, top10_pct, fees_paid_sol FROM cand").fetchall()
        self.assertEqual(len(rows), 1)
        tok, via, stage, tradeable, passed, holders, top10, fees = rows[0]
        self.assertEqual((tok, via, stage, tradeable, passed), (A, "gecko,graduates,pumpportal", "migrated", 1, 1))
        self.assertEqual((holders, top10), (300, 20.0))                        # the curve / pool account is no holder
        self.assertAlmostEqual(fees, 60_000 / 150 * 0.003, places=2)            # estimated from the 1 h volume
        self.assertEqual(con.execute("SELECT COUNT(*) FROM shadow WHERE token=? AND source='scan'", (A,)).fetchone()[0], 1)
        self.assertEqual(out["credits"], 14)                                    # 4 RPC + one holder page
        self.assertEqual(store.spent(con, "helius", NOW), 14)
        self.assertEqual(store.spent(con, "gt", NOW), 3)                        # two pool pages + trending (meta)
        con.close()
        h0 = self.net.calls["helius"]
        out2 = self.run_pass(NOW + 300)                                         # inside the 10-minute cache
        self.assertEqual(out2["checked"], 0)
        self.assertEqual(self.net.calls["helius"], h0)                          # no new paid call
        con = self.scan()
        self.assertEqual(con.execute("SELECT COUNT(*) FROM cand").fetchone()[0], 1)
        self.assertEqual(con.execute("SELECT n_obs FROM shadow WHERE token=?", (A,)).fetchone()[0], 3)   # tracked
        con.close()

    def test_signals_one_row_per_token_with_lead_time_and_source_filter(self):
        self.run_pass()
        live = {"price": 0.0003, "mcap": 300000, "liq": 40000, "txns_h1": 400, "buys_h1": 250}
        rows = [(A, [("kolx", "x", NOW + 600)], NOW + 600, NOW + 600, "ABC", live),
                (B, [("w:abcdef", "chain", NOW + 60)], NOW + 60, NOW + 60, "BBB", live)]
        from ui import mcpapi
        with mock.patch("ui.pravitrade.gather_callers", return_value=rows), \
                mock.patch("scan.store.on", return_value=True):
            sig = mcpapi.signals(NOW + 700)["signals"]
            self.assertEqual([s["token"] for s in sig], [A, B])                 # A once, not again as a scan row
            a = sig[0]
            self.assertEqual((a["source"], a["sources"]), ("caller", ["caller", "scan"]))
            self.assertEqual(a["lead_time_min"], 10.0)                          # the scanner had it 10 min earlier
            self.assertEqual(a["stage"], "migrated")
            self.assertTrue(a["pass_reasons"])
            self.assertIsNone(sig[1]["lead_time_min"])
            self.assertEqual(sig[1]["source"], "wallet")
            for k in ("beta_score", "x_momentum_score", "x_early", "lead_time_min"):
                self.assertIn(k, sig[1])
            self.assertEqual([s["token"] for s in mcpapi.signals(NOW + 700, source="wallet")["signals"]], [B])
            self.assertEqual([s["token"] for s in mcpapi.signals(NOW + 700, source="caller")["signals"]], [A])
            only = mcpapi.signals(NOW + 700, source="scan")["signals"]
            self.assertEqual([(s["token"], s["source"], s["n_callers"]) for s in only], [(A, "scan", 0)])
            self.assertEqual(mcpapi.signals(NOW + 700, source="beta")["signals"], [])
            self.assertIn("error", mcpapi.signals(NOW, source="nesto"))
            code, out = mcpapi.answer("/api/mcp/signals", {"source": "scan"})
            self.assertEqual(code, 200)

    def test_lead_time_from_the_first_call(self):
        self.run_pass()
        kc = sqlite3.connect(self.p["kol"])
        kc.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES ('1', ?, 'kolx', ?, 'call')", (A, NOW + 900))
        kc.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES ('2', ?, 'botty', ?, 'call')", (A, NOW + 60))
        kc.execute("INSERT INTO kols (handle, bot) VALUES ('botty', 1)")
        kc.commit()
        kc.close()
        con = self.scan()
        self.assertEqual(market.update_lead_times(con, NOW + 1000, self.p), 1)
        self.assertEqual(con.execute("SELECT lead_time_min, first_signal_by FROM cand WHERE token=?", (A,)).fetchone(),
                         (15.0, "kolx"))                                       # the bot account does not count
        con.close()

    def test_credit_cap_stops_the_checks_cleanly(self):
        con = store.connect()
        store.add_spent(con, "helius", 5000, NOW)
        con.commit()
        con.close()
        with mock.patch("scan.market.log") as lg:
            out = self.run_pass()
        self.assertEqual(self.net.calls["helius"], 0)
        self.assertEqual(out["passed"].get("scan", 0), 0)
        con = self.scan()
        why = con.execute("SELECT why FROM cand WHERE token=?", (A,)).fetchone()[0]
        self.assertIn("dnevni strop Helius", why)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM shadow").fetchone()[0], 0)
        con.close()
        self.assertTrue(any("dnevni strop Helius" in str(c) for c in lg.call_args_list))

    def test_cap_reached_in_the_middle_of_a_pass(self):
        self.migrated(C, sym="CCC")
        self.net.pairs[C] = [dpair(C, sym="CCC")]
        cfg = dict(self.cfg, helius_credits_day=30)   # a check reserves 24 (two holder pages), spends 14: one fits
        self.run_pass(cfg=cfg)
        con = self.scan()
        whys = dict(con.execute("SELECT token, why FROM cand"))
        con.close()
        self.assertEqual(sorted(w is None for w in whys.values()), [False, True])
        self.assertEqual(self.net.calls["helius"], 5)                           # the second token made no call
        self.assertIn("dnevni strop", [w for w in whys.values() if w][0])

    def test_caller_signal_is_measured_under_its_own_rule(self):
        """A called token under the scanner's volume line: not a scan passer, but a caller shadow entry."""
        self.net.pairs[B] = [dpair(B, sym="BBB", vol_h1=28_000, liq=30_000)]
        kc = sqlite3.connect(self.p["kol"])
        kc.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES ('9', ?, 'kolx', ?, 'call')", (B, NOW - 60))
        kc.commit()
        kc.close()
        out = self.run_pass()
        self.assertEqual(out["passed"].get("caller"), 1, out)
        con = self.scan()
        self.assertEqual(con.execute("SELECT source FROM shadow WHERE token=?", (B,)).fetchall(), [("caller",)])
        self.assertIn("volumen 1 h", con.execute("SELECT why FROM cand WHERE token=?", (B,)).fetchone()[0])
        con.close()


class Filters(unittest.TestCase):
    cfg = store.config()

    def test_stage_rules(self):
        st = lambda **m: filters.stage_filter(m, self.cfg)  # noqa: E731
        self.assertEqual(st(curve=True, mcap=8_000)[0], "curve")
        self.assertIsNotNone(st(curve=True, mcap=8_000)[3])
        self.assertEqual(st(curve=True, mcap=15_000, vol_h1=1), ("final_stretch", False, None, None))   # measured only
        self.assertEqual(st(curve=False, mcap=50_000, vol_h1=20_000), ("migrated", True, filters.VOLUME_RULE, None))
        self.assertEqual(st(curve=False, mcap=25_000, vol_h1=40_000), ("migrated", False, None, None))  # under 30k
        self.assertEqual(st(curve=False, mcap=50_000, vol_h1=40_000), ("migrated", True, None, None))

    def test_trade_floor_never_under_30k_and_analysis_floor_10k(self):
        self.assertEqual(store.DEFAULT["final_stretch_min_mcap"], 10_000)
        path = os.path.join(tempfile.mkdtemp(), "c.json")
        with open(path, "w") as f:
            json.dump({"trade_min_mcap": 5000, "_": "x"}, f)
        self.assertEqual(store.config(path)["trade_min_mcap"], 30_000)

    def test_entry_gates_are_the_copy_loops(self):
        m = {"token": A, "price": 1.0, "liq": 40_000, "mcap": 300_000, "symbol": "ABC", "src": "gecko"}
        with mock.patch("league.copy._rugged", return_value=None):
            self.assertIsNone(filters.entry_gates(m, "migrated"))
            self.assertIn("lažni pool", filters.entry_gates(dict(m, liq=400_000), "migrated"))
            self.assertIn("MC-a", filters.entry_gates(dict(m, liq=6_000), "migrated"))       # liquidity 2 % of MC
            self.assertIn("premala", filters.entry_gates(dict(m, liq=1_000), "migrated"))
            self.assertIsNone(filters.entry_gates(dict(m, liq=0), "final_stretch"))           # a curve has no pool
            self.assertIn("arhivi", filters.entry_gates(m, "migrated", archived={A}))
            self.assertIn("status", filters.entry_gates(m, "migrated", dead={A}))
            self.assertIsNone(filters.entry_gates(dict(m, src="dexscreener"), "migrated", dead={A}))
            self.assertIn("major", filters.entry_gates(dict(m, token=WSOL), "migrated"))
        with mock.patch("league.copy._rugged", return_value={"text": "srušio se 80% od vrha"}):
            self.assertIn("rugan", filters.entry_gates(m, "migrated"))

    def test_fees_from_trades_and_from_volume(self):
        m = {"token": A, "curve": False, "dex": "pumpswap", "vol_h1": 60_000, "txns_h1": 400, "buys_h1": 250, "liq": 40_000}
        f = filters.fees_filter(m, [], self.cfg, 150)
        self.assertIsNone(f["why"])
        self.assertEqual((f["src"], f["buy_share"]), ("dexscreener", 0.625))
        # wash: 25 wallets each buying and selling the same size like a clock (every 500 s)
        wash = [{"side": "buy" if (i // 25) % 2 == 0 else "sell", "wallet": f"w{i % 25}", "amount": 5.0,
                 "ts": NOW - 3000 + 20 * i} for i in range(125)]
        f = filters.fees_filter(m, wash, self.cfg, 150)
        self.assertEqual((f["src"], f["unique_traders"]), ("pumpportal", 25))
        self.assertIn("lažni volumen", f["why"])
        # 10.11.: the busiest pump.fun curve pools had 400+ buys from 3 buyers (GeckoTerminal's buyers count)
        self.assertIn("različitih kupaca", filters.fees_filter(dict(m, buyers_h1=3), [], self.cfg, 150)["why"])
        self.assertIn("premalo", filters.fees_filter(dict(m, vol_h1=5_000), [], self.cfg, 150)["why"])
        self.assertIn("promet", filters.fees_filter(dict(m, liq=1_000), [], self.cfg, 150)["why"])

    def test_rug_check_reasons(self):
        with mock.patch("league.copy._concentration", return_value=(None, "nepoznato")):
            ok = {"top10_pct": 20, "holders": 300, "holders_capped": 0, "mint_auth": None, "freeze_auth": None}
            self.assertIsNone(filters.rug_check(A, ok, self.cfg)[0])
            self.assertIn("mint ovlast", filters.rug_check(A, dict(ok, mint_auth="DEV"), self.cfg)[0])
            self.assertIn("top 10", filters.rug_check(A, dict(ok, top10_pct=75), self.cfg)[0])
            self.assertIn("holdera", filters.rug_check(A, dict(ok, holders=10), self.cfg)[0])
            self.assertIsNone(filters.rug_check(A, dict(ok, holders=1000, holders_capped=1), self.cfg)[0])
            self.assertIn("strop", filters.rug_check(A, None, self.cfg, "čeka (strop)")[0])


class Beta(unittest.TestCase):
    cfg = store.config()

    def test_keywords_and_score(self):
        self.assertEqual(meta.words("BabyTrump on SOL 2026"), ["baby", "trump"])
        wif = {"token": P, "symbol": "WIF", "name": "dogwifhat", "keywords": meta.keywords("dogwifhat", "WIF")}
        s, matched = meta.beta_score({"token": A, "symbol": "BABYWIF", "name": "Baby Wif"}, wif)
        self.assertGreaterEqual(s, 0.6)
        self.assertIn("wif", matched)
        self.assertLess(meta.beta_score({"token": B, "symbol": "MOON", "name": "To the moon"}, wif)[0], 0.6)
        self.assertEqual(meta.beta_score({"token": P, "symbol": "WIF", "name": "dogwifhat"}, wif)[0], 0.0)   # itself
        trump = {"token": P, "symbol": "TRUMPCAT", "name": "Trump Cat", "keywords": meta.keywords("Trump Cat", "TRUMPCAT")}
        s, _ = meta.beta_score({"token": A, "symbol": "TCAT", "name": "Cat of Trump", "description": ""}, trump)
        self.assertGreaterEqual(s, 0.4)                                         # the whole name, not the ticker
        self.assertLess(s, 0.6)

    def test_runners_half_by_day_half_by_hour(self):
        rows = [{"token": f"t{i}", "mcap": 500_000, "price": 1, "ch_h24": 100 - i, "ch_h1": i} for i in range(30)]
        rows.append({"token": "small", "mcap": 1_000, "price": 1, "ch_h24": 999, "ch_h1": 999})
        got = [r["token"] for r in meta.runners(rows, dict(self.cfg, runners=4))]
        self.assertEqual(got, ["t0", "t1", "t29", "t28"])

    def test_match_record_and_meta_state(self):
        with mock.patch.dict(os.environ, {"SCAN_DB": os.path.join(tempfile.mkdtemp(), "scan.db")}):
            con = store.connect()
            meta.store_metas(con, NOW, [{"token": P, "symbol": "WIF", "name": "dogwifhat", "price": 1.0, "mcap": 9e6}])
            con.execute("INSERT INTO cand (token, symbol, checked_ts) VALUES (?, 'BABYWIF', ?)", (A, NOW))
            res = {"why": None, "why_sig": None, "stage": "migrated", "tradeable": True}
            d = {"via": {"gecko"}, "signals": {}}
            n = market.match_betas(con, self.cfg, NOW, [(A, d, {"symbol": "BABYWIF", "name": "Baby Wif", "price": 0.01,
                                                              "mcap": 80_000}, res)])
            self.assertEqual(n, 1)
            self.assertEqual(con.execute("SELECT beta_parent FROM cand WHERE token=?", (A,)).fetchone()[0], P)
            self.assertEqual(con.execute("SELECT source FROM shadow WHERE token=?", (A,)).fetchone()[0], "beta")
            self.assertEqual(market.match_betas(con, self.cfg, NOW, [(A, d, {"symbol": "BABYWIF", "price": 0.01}, res)]), 0)
            self.assertEqual(meta.pending_tokens(con), {A, P})
            meta.track(con, {A: 0.015, P: 1.2}, NOW + 3700)                     # 1 h: beta +50 %, parent +20 % (rising)
            meta.track(con, {A: 0.005, P: 0.9}, NOW + 4 * 3600 + 10)            # 4 h: beta -50 %, parent -10 % (fading)
            rows = {(r["window"], r["state"]): r for r in meta.report_rows(con, NOW - 10)}
            self.assertEqual(rows[("1h", "raste")]["mean"], 0.5)
            self.assertEqual(rows[("4h", "pada")]["mean"], -0.5)
            meta.track(con, {A: 0.02, P: 1.0}, NOW + 24 * 3600 + 10)
            self.assertEqual(con.execute("SELECT done, r24h FROM beta").fetchone(), (1, 1.0))
            con.close()


class XMomentum(Base):
    def posts(self):
        def p(h, mins_ago, fol=500, age_d=400):
            return {"handle": h, "ts": NOW - mins_ago * 60, "followers": fol, "created_ts": NOW - age_d * 86400}
        prev = [p(f"old{i}", 30 + i) for i in range(4)]
        last = [p(f"new{i}", 5) for i in range(6)] + [p("bot1", 3, fol=10), p("bot2", 4, age_d=5)]
        return prev + last

    def test_score_and_early(self):
        m = xmom.momentum(self.posts(), NOW)
        self.assertEqual((m["organic15"], m["organic_prev60"], m["authors15"]), (6, 4, 8))
        self.assertAlmostEqual(m["x_momentum_score"], round(math.log2(7 / 2), 3))
        self.assertEqual(m["bot_share"], round(2 / 12, 3))
        self.assertTrue(m["x_early"])
        called = xmom.momentum(self.posts(), NOW, known={"new3"})
        self.assertTrue(called["caller_called"])
        self.assertFalse(called["x_early"])                                     # a known caller already posted it
        fading = xmom.momentum([dict(p, ts=NOW - 40 * 60) for p in self.posts()], NOW)
        self.assertLess(fading["x_momentum_score"], 0)
        no_meta = xmom.momentum([{"handle": "a", "ts": NOW - 60, "followers": None, "created_ts": None}], NOW)
        self.assertIsNone(no_meta["bot_share"])                                 # no author data: no bot share

    def tweets(self):
        out = []
        for i, p in enumerate(self.posts()):
            out.append({"id": str(i), "createdAt": p["ts"], "text": A,
                        "author": {"userName": p["handle"], "followers": p["followers"], "createdAt": p["created_ts"]}})
        return out

    def test_measure_counts_spend_and_respects_the_cap(self):
        self.net.tweets = self.tweets()
        scon, kcon = store.connect(), sqlite3.connect(self.p["kol"])
        try:
            r = xmom.measure(A, "ABC", NOW, scon, kcon, self.cfg, get=self.net.x)
            self.assertTrue(r["measured"])
            self.assertTrue(r["x_early"])
            self.assertAlmostEqual(store.spent(scon, "xusd", NOW), 12 * 0.00015, places=6)
            from kol import twapi
            self.assertAlmostEqual(twapi.spent(kcon, NOW), 12 * 0.00015, places=6)    # twapi's own day counter too
            store.add_spent(scon, "xusd", 1.0, NOW)                             # the scanner's X budget is spent
            self.assertIsNone(xmom.measure(B, "BBB", NOW, scon, kcon, self.cfg, get=self.net.x))
            self.assertEqual(self.net.calls["x"], 1)
        finally:
            scon.close()
            kcon.close()
        got = xmom.latest([A], now=NOW)
        self.assertEqual(got[A]["source"], "scan")

    def test_grok_rows_take_precedence_and_cost_nothing(self):
        from ui import xfeat
        xc = xfeat.connect()
        xc.execute("INSERT INTO x_features (subject_kind, subject, ts_observed, ts_asof, features, source, backfill, "
                   "created) VALUES ('token', ?, ?, ?, ?, 'mcp:abc', 0, ?)",
                   (A, NOW, NOW - 300, json.dumps({"x_momentum_score": 2.5, "x_early": False}), NOW))
        xc.commit()
        xc.close()
        scon, kcon = store.connect(), sqlite3.connect(self.p["kol"])
        try:
            r = xmom.measure(A, "ABC", NOW, scon, kcon, self.cfg, get=self.net.x)
        finally:
            scon.close()
            kcon.close()
        self.assertEqual((r["source"], r["x_momentum_score"], r["measured"]), ("grok", 2.5, False))
        self.assertEqual(self.net.calls["x"], 0)
        self.assertEqual(xmom.latest([A], now=NOW)[A]["source"], "grok")


class Shadow(unittest.TestCase):
    cfg = store.config()

    def row(self, **kw):
        r = {"token": A, "source": "scan", "stage": "migrated", "found_ts": NOW, "tradeable": 1, "entry": 1.0, "hi": 1.0,
             "lo": 1.0, "last": 1.0, "last_ts": NOW, "n_obs": 1, "max_gap_s": 0, "t_tp": None, "t_sl": None,
             "hi1h": 1.0, "hi4h": 1.0, "r4h": None, "result": None, "exit_why": None, "bad": None, "done": 0}
        r.update(kw)
        return r

    def walk(self, path, step=150):
        r = self.row()
        for i, px in enumerate(path, 1):
            r = shadow.observe(r, px, NOW + i * step, self.cfg)
        return r

    def test_target_first_stop_first_and_time(self):
        n4h = 4 * 3600 // 150
        tp = self.walk([1.1, 1.25, 0.6] + [1.0] * n4h)
        self.assertEqual((tp["exit_why"], tp["result"], tp["done"]), ("tp", 0.18, 1))
        self.assertEqual(shadow.outcome(tp, self.cfg), (True, True, False))
        sl = self.walk([0.9, 0.65, 1.3] + [1.0] * n4h)
        self.assertEqual((sl["exit_why"], sl["result"]), ("sl", -0.32))
        self.assertEqual(shadow.outcome(sl, self.cfg), (True, True, True))      # +20 % later still counts as a hit
        flat = self.walk([1.05] * (n4h + 1))
        self.assertEqual((flat["exit_why"], flat["result"]), ("vrijeme", 0.03))
        late = self.walk([1.0] * 30 + [1.3] + [1.0] * n4h)                      # +30 % after 77 min: 4 h hit, not 1 h
        self.assertEqual(shadow.outcome(late, self.cfg)[:2], (False, True))

    def test_gap_and_lost_pair(self):
        r = shadow.observe(self.row(), 1.0, NOW + 4 * 3600 + 5, self.cfg)        # one point after a 4 h hole
        self.assertEqual((r["done"], r["bad"]), (1, "rupa"))
        r = shadow.observe(self.row(), None, NOW + 4 * 3600 + 1900, self.cfg)    # the pair is gone
        self.assertEqual((r["done"], r["exit_why"], r["result"]), (1, "nestao", -0.32))


class PaperGate(Base):
    def fill(self, n, result, source="scan", tradeable=1):
        con = store.connect()
        for i in range(n):
            self.k = getattr(self, "k", 0) + 1
            con.execute("INSERT INTO shadow (token, source, stage, found_ts, tradeable, entry, result, done) "
                        "VALUES (?,?,?,?,?,1,?,1)", (f"t{self.k}", source, "migrated", NOW - 3600 * (i + 5),
                                                     tradeable, result))
        con.commit()
        con.close()

    def test_needs_30_outcomes_and_positive_ev(self):
        self.fill(29, 0.18)
        self.fill(40, 0.18, tradeable=0)                                        # measured-only rows never count
        why = shadow.paper_refusal("scan", now=NOW)
        self.assertIn("29 od 30", why)
        self.fill(1, -0.32)
        self.assertIsNone(shadow.paper_refusal("scan", now=NOW))                # 30 outcomes, EV > 0
        self.fill(30, -0.32, source="beta")
        self.assertIn("EV", shadow.paper_refusal("beta", now=NOW))
        self.assertEqual(shadow.paper_sources(now=NOW), ["scan"])
        self.assertIsNone(shadow.flag_paper_refusal(now=NOW))

    def test_set_flag_refuses_paper_without_proof(self):
        tcon = settings.connect(self.trade)
        try:
            settings.set_flag(tcon, "market_scan", "shadow", "Jure", now=NOW)
            with self.assertRaises(ValueError) as e:
                settings.set_flag(tcon, "market_scan", "paper", "Jure", now=NOW)
            self.assertIn("ne može u paper", str(e.exception))
            self.assertEqual(settings.flag("market_scan", con=tcon), "shadow")
            self.fill(30, 0.18)
            settings.set_flag(tcon, "market_scan", "paper", "Jure", now=NOW)     # the owner's own tap, with the proof
            self.assertEqual(settings.flag("market_scan", con=tcon), "paper")
            settings.set_flag(tcon, "market_scan", "off", "Jure", now=NOW)       # going down is always allowed
            settings.set_flag(tcon, "require_signal", "paper", "Jure", now=NOW)  # other flags: no such gate
        finally:
            tcon.close()

    def test_report_and_mcp_tool(self):
        self.fill(30, 0.18)
        d = shadow.report_data(NOW)
        g = {r["source"]: r for r in d["gate_window"]}
        self.assertEqual((g["scan"]["n"], g["scan"]["ev"]), (30, 0.18))
        self.assertEqual(d["paper_gate"]["scan"], "prolazi")
        from report import render
        html = render.skener_body(d)
        self.assertIn("Skener (bez callera)", html)
        self.assertIn("Trošak danas", html)
        from ui import mcpapi
        names = {t["name"]: t for t in mcpapi.TOOLS}
        self.assertTrue(names["get_source_stats"]["annotations"]["readOnlyHint"])
        self.assertEqual(names["get_market_signals"]["inputSchema"]["properties"]["source"]["enum"],
                         ["caller", "wallet", "scan", "beta"])
        res = json.loads(mcpapi.rpc(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                "params": {"name": "get_source_stats", "arguments": {}}}).encode())[1])
        self.assertFalse(res["result"]["isError"])
        self.assertIn("paper_gate", res["result"]["structuredContent"])


if __name__ == "__main__":
    unittest.main()
