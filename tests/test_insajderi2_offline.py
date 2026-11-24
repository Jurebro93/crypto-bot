"""Insajderi 2.0 (15.11., vlasnik: "koji su novčanici najviše PRODAVALI kad je cijena skočila nakon poziva i jesu li
isti KUPILI prije poziva, danima prije ... kako ih pratiti") on a synthetic chain, no network:

  - a wallet that buys 2 days before the call and sells into the pump on several tokens is an insider; with wallet
    rotation (two wallets, one funder) it is ONE owner group, confirmed out of sample by time
  - a sniper (buys seconds after launch) is excluded, a relayer (pays fees for 5+ owners) is excluded and never merges
    the wallets it paid for
  - the walk-forward never looks ahead: the classification at a day is the same with or without later events, and
    the copy trade of a NEW token after confirmation is priced from entry + delay, exit when they sell, net of cost
  - the Helius day cap holds: a pass never spends more than the cap
  - market jumps of any token are found from candles; catalysts are classified

    python3 -m unittest tests.test_insajderi2_offline
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from insajderi import chain, copy, events as ev, run, score, store  # noqa: E402

BASE = (1794000000 // 86400) * 86400
WSOL = "So11111111111111111111111111111111111111112"


def addr(name):
    return (name + "1" * 44)[:44]


W1, W2, F, S, P = addr("Wone"), addr("Wtwo"), addr("Funder"), addr("Sniper"), addr("Relayer")
RS = [addr(f"Relayed{i}") for i in range(5)]
NOISE = [addr(f"Noise{i}") for i in range(3)]
TOK = [addr(f"Token{k}") for k in range(1, 7)]
NEW = addr("Newtoken")


def t0_of(k):
    return BASE + k * 86400 + 12 * 3600


class Chain:
    """Raw getTransactionsForAddress txs by address (mint and token accounts) + a fake fetch that charges 10 a page."""

    def __init__(self):
        self.by = {}
        self.n = 0
        self.calls = []

    def tx(self, mint, signer, side, sol, tokens, ts, payer=None):
        self.n += 1
        sig = f"sig{self.n}"
        acct = addr("Acct" + signer[:6] + mint[:7])
        payer = payer or signer
        keys = [{"pubkey": payer, "signer": True}]
        if signer != payer:
            keys.append({"pubkey": signer, "signer": True})
        keys += [{"pubkey": acct, "signer": False}, {"pubkey": addr("Pool"), "signer": False}]
        i_sig = 0 if signer == payer else 1
        pre_l = [10_000_000_000] * len(keys)
        post_l = list(pre_l)
        post_l[i_sig] += int((-sol if side == "buy" else sol) * 1e9)
        held = 5_000_000.0
        pre_t = held if side == "sell" else 0.0
        post_t = pre_t + (tokens if side == "buy" else -tokens)
        ai = [k["pubkey"] for k in keys].index(acct)
        bal = (lambda amt: [{"accountIndex": ai, "mint": mint, "owner": signer,
                             "uiTokenAmount": {"amount": str(int(amt * 1e6)), "decimals": 6}}])
        t = {"blockTime": int(ts), "slot": int(ts) * 2, "transaction": {"signatures": [sig], "message": {"accountKeys": keys}},
             "meta": {"err": None, "preBalances": pre_l, "postBalances": post_l, "preTokenBalances": bal(pre_t),
                      "postTokenBalances": bal(post_t)}}
        self.by.setdefault(mint, []).append(t)
        self.by.setdefault(acct, []).append(t)
        return t

    def fetch(self, address, since_ts=None, until_ts=None, max_pages=3, oldest_first=False, on_credits=None):
        self.calls.append(address)
        xs = [t for t in self.by.get(address, []) if (since_ts is None or t["blockTime"] > since_ts)
              and (until_ts is None or t["blockTime"] <= until_ts)]
        xs.sort(key=lambda t: t["blockTime"], reverse=not oldest_first)
        out = xs[:100 * max_pages]
        pages = max(1, -(-len(out) // 100))
        if on_credits:
            for _ in range(pages):
                on_credits(10)
        return out, len(xs) <= 100 * max_pages


def build_world(d, n_tokens=6):
    """kol.db calls + tokens, minute.db candles, wallets.db funder sightings, and the chain."""
    from kol import store as kstore
    from kol import minute
    from wallets import store as wstore
    p = {k: os.path.join(d, f"{k}.db") for k in ("kol_db", "hype_db", "early_db", "wallet_db", "minute_db", "midcap_db",
                                                   "xfeat_db", "trade_db", "usage_db", "corr_db", "listing_db", "rug_db",
                                                   "insajderi_db", "league_db", "tg_db")}
    kc = kstore.connect(p["kol_db"])
    mc = sqlite3.connect(p["minute_db"])
    mc.executescript(minute.SCHEMA)
    wc = sqlite3.connect(p["wallet_db"])
    wc.executescript(wstore.SCHEMA)
    ch = Chain()
    for w in (W1, W2):
        wc.execute("INSERT INTO wallet_sightings VALUES (?,?,?,?,?,?,?)", (w, TOK[0], "rug", "holder", BASE, 1.0,
                                                                           json.dumps({"funder": F})))
    for k in range(1, n_tokens + 1):
        tok, t0 = TOK[k - 1], t0_of(k)
        created = t0 - 3 * 86400
        kc.execute("INSERT INTO tokens (token, symbol, supply, created_ts) VALUES (?,?,?,?)", (tok, f"T{k}", 1e9, created))
        for h, dt in (("alpha", 0), ("beta", 600)):
            kc.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, mcap0, symbol) VALUES (?,?,?,?,?,?,?)",
                       (f"tw{k}{h}", tok, h, t0 + dt, "call", 120_000, f"T{k}"))
        candles = [[t0 + m * 60, 1.0, 1.0, 1.0, 1.0 + (0.6 if 25 <= m <= 35 else 0.4 if m > 35 else m / 50.0), 1]
                   for m in range(0, 240)]
        mc.execute("INSERT INTO call_candles VALUES (?,?,?,?,?,?,?)",
                   (tok, t0, t0 + 14400, len(candles), zlib.compress(json.dumps(candles).encode()), 1, t0))
        ins = W1 if k <= 3 else W2
        ch.tx(tok, ins, "buy", 2.0, 1_000_000, t0 - 2 * 86400)          # two days before the call
        ch.tx(tok, ins, "sell", 1.5, 400_000, t0 + 1200)                # sells into the pump, twice
        ch.tx(tok, ins, "sell", 1.6, 400_000, t0 + 2400)
        ch.tx(tok, S, "buy", 0.5, 800_000, created + 5)                  # the sniper: 5 s after launch
        ch.tx(tok, S, "sell", 0.9, 800_000, t0 + 1500)
        ch.tx(tok, P, "buy", 1.0, 500_000, t0 - 86400)                   # the relayer trades too
        ch.tx(tok, P, "sell", 1.4, 500_000, t0 + 1800)
        for i, r in enumerate(RS):                                       # relayed traders, paid by P
            ch.tx(tok, r, "sell", 0.3, 100_000, t0 + 900 + i, payer=P)
        ch.tx(tok, NOISE[k % 3], "buy", 0.4, 200_000, t0 - 3 * 3600)    # an early buyer that never sells
    kc.commit()
    mc.commit()
    wc.commit()
    for x in (kc, mc, wc):
        x.close()
    return p, ch


def cfg(**k):
    c = {"days": 40, "warmup_days": 1, "sol_usd_hist": False, "lookups_per_event": 10, "mkt_days": 40}
    c.update(k)
    return c


class Insiders2(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p, self.ch = build_world(self.tmp.name)
        self.now = t0_of(6) + 2 * 86400

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, **k):
        return run.run("once", now=self.now, cfg=cfg(**k), credits=100_000, fetch=self.ch.fetch, log=lambda m: None,
                       **self.p)

    def test_insider_owner_group_sniper_relayer(self):
        s = self._run()
        self.assertEqual(s["call_events"], 6)
        con = store.connect(self.p["insajderi_db"])
        own = dict(con.execute("SELECT wallet, owner FROM i2_part"))
        self.assertEqual(own[W1], own[W2])                         # rotation: one funder = one owner
        self.assertNotEqual(own[RS[0]], own[RS[1]])                # the relayer never merges whom it paid for
        g = {o: (cls, n, conf) for o, cls, n, conf in con.execute("SELECT owner, cls, n_hits, confirmed_ts FROM i2_groups")}
        cls, n_hits, conf = g[own[W1]]
        self.assertEqual((cls, n_hits), ("insajder", 6))
        self.assertIsNotNone(conf)
        self.assertEqual(g[own[S]][0], "bot_snajper")
        self.assertEqual(g["relayer:" + P][0], "relayer")
        bb = con.execute("SELECT bought_before, sold_into, n_sells, lead_s FROM i2_part WHERE wallet = ? AND eid LIKE ?",
                         (W1, f"c:{TOK[0]}:%")).fetchone()
        self.assertEqual(bb[:3], (1, 1, 2))
        self.assertEqual(bb[3], 2 * 86400)                         # lead = days before the call
        self.assertEqual(s["confirmed"], 1)
        con.close()

    def test_walk_forward_no_look_ahead_and_copy(self):
        self._run()
        con = store.connect(self.p["insajderi_db"])
        evs = ev.load(con)
        parts = score.load_parts(con)
        c = store.config(cfg())
        as_of = t0_of(4)   # events 1-3 ended before it
        early = [e for e in evs if e["t0"] < as_of]
        a = score.classify(parts, evs, as_of, c)
        b = score.classify([r for r in parts if r[0] in {e["eid"] for e in early}], early, as_of, c)
        strip = (lambda d: {o: (x["cls"], x["n_hits"], x["confirmed"]) for o, x in d.items()})
        self.assertEqual(strip(a), strip(b))                       # later events change nothing at as_of
        self.assertFalse(score.confirmed(score.classify(parts, evs, t0_of(2), c)))
        # the insider buys a NEW token after confirmation; others trade it; it sells 2 h later at ~2x
        tb = t0_of(6) + 86400 + 3 * 3600
        rows = [(NEW, W2, "s1", tb, 1, "buy", 1.0, 1_000_000.0, W2, None),
                (NEW, NOISE[0], "s2", tb + 120, 2, "buy", 1.1, 1_000_000.0, NOISE[0], None),
                (NEW, W2, "s3", tb + 7200, 3, "sell", 2.0, 1_000_000.0, W2, None),
                (NEW, NOISE[1], "s4", tb + 7260, 4, "buy", 1.9, 1_000_000.0, NOISE[1], None)]
        con.executemany("INSERT INTO i2_trades VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        con.commit()
        out, conf = copy.walk(con, self.p, c, evs, parts, tb + 86400)
        mine = [r for r in out if r["token"] == NEW]
        self.assertEqual(len(mine), 1)
        r = mine[0]
        self.assertEqual(r["exit"], "prodali su")
        self.assertAlmostEqual(r["ret"], 1.9 / 1.1 - 1 - copy.cost_rt(c), places=3)
        self.assertEqual(r["bucket"], "<1M")                     # 1.1e-6 SOL x 1e9 x $150 = $165k
        self.assertTrue(r["bonded"])
        sm = copy.summarize(out)
        self.assertEqual(sm["nasa_pravila"]["n"], 0)               # nothing at MC >= 5M
        self.assertFalse(copy.verdict(sm)[0])
        con.close()

    def test_budget_cap(self):
        self._run(helius_day=50, deploy_share=1.0)
        con = store.connect(self.p["insajderi_db"])
        spent = store.helius_spent(con, self.now)
        self.assertLessEqual(spent, 50)
        self.assertGreater(spent, 0)
        total = con.execute("SELECT SUM(credits) FROM i2_fetch").fetchone()[0]
        self.assertLessEqual(total, 50)
        con.close()
        cap, how = store.helius_cap(store.config({}), self.now, None)
        self.assertEqual(cap, store.DEFAULT["helius_fallback"])

    def test_budget_from_old_jobs(self):
        from usage import meter
        uc = meter.connect(self.p["usage_db"])
        h = (self.now // 3600) * 3600 - 5 * 86400
        uc.execute("INSERT INTO usage VALUES (?,?,?,?,?,?,?)", (h, "helius", "precall.py", "getTransactionsForAddress",
                                                                  100, 0, 20_000))
        uc.commit()
        uc.close()
        cap, _how = store.helius_cap(store.config({}), self.now, self.p["usage_db"])
        self.assertEqual(cap, int(20_000 * 0.16))

    def test_market_jumps(self):
        closes = [(i * 3600, 1.0) for i in range(5)] + [(5 * 3600, 1.2), (6 * 3600, 1.7), (7 * 3600, 1.9), (8 * 3600, 1.5)]
        j = ev.find_jumps(closes, 0.5, 1.0)
        self.assertEqual(len(j), 1)
        t0, base, pk_ts, pk, kind = j[0]
        self.assertEqual((t0, base, pk, kind), (4 * 3600, 1.0, 1.9, "6h"))
        self.assertEqual(ev.find_jumps([(i * 3600, 1.0 + 0.01 * i) for i in range(30)], 0.5, 1.0), [])

    def test_catalyst_call(self):
        self._run()
        con = store.connect(self.p["insajderi_db"])
        cats = [r[0] for r in con.execute("SELECT catalyst FROM i2_events")]
        self.assertTrue(cats and all(x == "poziv_x" for x in cats))
        con.close()


if __name__ == "__main__":
    unittest.main()


# ---------- the extension and the wiring ------------------------------------------------------------------------------
from insajderi import live as ilive, report, smart, trending  # noqa: E402
from tests.test_pravi_novac_sve_offline import LU, SwitchBase, tok  # noqa: E402
from trade import settings  # noqa: E402
from unittest import mock  # noqa: E402


class SmartMoney(unittest.TestCase):
    C = store.config({"cluster_gap_s": 300, "cluster_min_tokens": 2, "signal_min_clusters": 2, "signal_window_s": 3600})

    def test_clusters_cobuy_and_signal_needs_two_independent(self):
        a, b, x = addr("Aa"), addr("Bb"), addr("Xx")
        m1, m2, m3 = addr("M1"), addr("M2"), addr("M3")
        tr = [(a, m1, 100, "buy", 1, 1), (b, m1, 160, "buy", 1, 1), (a, m2, 1000, "buy", 1, 1), (b, m2, 1100, "buy", 1, 1),
              (a, m3, 5000, "buy", 1, 1), (b, m3, 5050, "buy", 1, 1), (x, m3, 6000, "buy", 1, 1)]
        owners = {"oa": [a], "ob": [b], "ox": [x]}
        cl = smart.clusters(owners, tr, self.C)
        self.assertEqual(cl["oa"], cl["ob"])                     # co-buy within 5 min on 2+ tokens: one cluster
        self.assertNotEqual(cl["oa"], cl["ox"])
        sig = smart.signals(owners, cl, tr, self.C, 0, 10_000)
        self.assertEqual([(t, ts) for t, ts, _k in sig], [(m3, 6000)])   # a and b are one: only x makes it two

    def test_roles_skip_bots_and_need_two_jumps(self):
        evs = [{"eid": f"e{i}", "win_end": 10, "kind": "jump", "t0": 1} for i in range(3)]
        parts = [(f"e{i}", "w1", "o1", 0, 1, 1, 2, 5, 1, 1, 60) for i in range(3)] + \
                [("e0", "w2", "o2", 0, 1, 0, None, None, 1, 0, 60)] + \
                [(f"e{i}", "w3", "o3", 0, 1, 1, 2, 5, 1, 1, 60) for i in range(3)]
        st = {"o3": {"cls": "bot_snajper"}}
        r = smart.roles(st, evs, parts, 100, store.config({}))
        self.assertIn("o1", r)
        self.assertNotIn("o2", r)                                # one jump only
        self.assertNotIn("o3", r)                                # a bot never


class Trending(unittest.TestCase):
    def test_fit_ranks_the_precursor(self):
        tr = [(i * 3600, {"vacc": 5.0 if i % 10 == 0 else 1.0, "b1h": 10, "bacc": 1, "bshare": 0.5, "c1h": 0, "liq_mc": 0.1},
               int(i % 10 == 0)) for i in range(200)]
        w = trending.fit(tr)
        self.assertGreater(w["vacc"][2], 0)
        hi = {"vacc": 6.0, "b1h": 10, "bacc": 1, "bshare": 0.5, "c1h": 0, "liq_mc": 0.1}
        lo = dict(hi, vacc=0.5)
        self.assertGreater(trending.score(hi, w), trending.score(lo, w))

    def test_samples_stop_at_the_entry(self):
        series = {"m": [(h * 3600, {}) for h in range(10)]}
        sm = trending.samples(series, {"m": 5 * 3600}, 2)
        self.assertEqual([(ts // 3600, y) for ts, _f, y in sm], [(0, 0), (1, 0), (2, 0), (3, 1), (4, 1)])


class Demo(SwitchBase):
    def setUp(self):
        super().setUp()
        d = self.tmp.name
        self.idb = os.path.join(d, "insajderi.db")
        self.hdb = os.path.join(d, "hype.db")
        con = store.connect(self.idb)
        self.wa, self.wb = addr("Wa"), addr("Wb")
        con.execute("INSERT INTO i2_groups (owner, members, cls, confirmed_ts, score) VALUES (?,?,?,?,?)",
                    ("O1", json.dumps([self.wa, self.wb]), "insajder", 1, 9))
        con.commit()
        con.close()
        hc = sqlite3.connect(self.hdb)
        hc.execute("CREATE TABLE chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER, sol REAL, "
                   "PRIMARY KEY (sig, mint))")
        hc.commit()
        hc.close()
        p = mock.patch.dict(os.environ, {"INSAJDERI_DB": self.idb, "HYPE_DB": self.hdb})
        p.start()
        self.addCleanup(p.stop)
        ilive._WATCH.update(ts=0.0, v=[])
        ilive._TRIED.clear()
        ilive._LAST["ts"] = 0.0
        self.flag("insajderi2", "paper")

    def chain(self, sig, w, t, side, ts):
        hc = sqlite3.connect(self.hdb)
        hc.execute("INSERT INTO chain_trades VALUES (?,?,?,?,?,?)", (sig, w, t, side, int(ts), 1.0))
        hc.commit()
        hc.close()

    def go(self, now=None):
        mk = lambda toks: {x: self.quote["row"] for x in toks}   # noqa: E731
        ilive._WATCH.update(ts=0.0, v=[])
        return ilive.run_once(self.lg, market_fn=mk, now=now or self.now, sol=150.0, force=True)

    def test_entry_on_their_buy_and_exit_when_the_group_sells(self):
        self.chain("s1", self.wa, tok(1), "buy", self.now - 20)
        got = self.go()
        self.assertEqual([u for u, _t in got], ["autopilot-novcanici"])   # 19.11.: the wallet demo account, never real
        row = self.lg.execute("SELECT user, owner, status FROM insajderi2_trades WHERE token=?", (tok(1),)).fetchone()
        self.assertEqual(tuple(row), ("autopilot-novcanici", "O1", "open"))
        self.assertTrue(self.lg.execute("SELECT source FROM trades WHERE token=?", (tok(1),)).fetchone()[0]
                        .startswith("insajderi2"))
        self.chain("s2", self.wb, tok(1), "sell", self.now + 60)  # the OTHER wallet of the group sells (rotation)
        self.go(self.now + 90)
        st = self.lg.execute("SELECT status, exit_reason FROM insajderi2_trades WHERE token=?", (tok(1),)).fetchone()
        self.assertEqual(tuple(st), ("closed", "wallet_sold"))
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM trades WHERE user=?", (LU,)).fetchone()[0], 0)

    def test_capgate_and_flag_off(self):
        settings.put(self.con, f"flag:{settings.MIKROKAP}", {"mode": "live", "since": 1, "who": "Jure"})
        settings._FLAG_CACHE.clear()
        self.chain("s3", self.wa, tok(2), "buy", self.now - 20)
        self.assertEqual(self.go(), [])                          # MC $100k < 5M: refused
        self.flag("insajderi2", "off")
        self.chain("s4", self.wa, tok(3), "buy", self.now - 10)
        self.assertEqual(self.go(), [])
        self.assertEqual(ilive.webhook_wallets(), [])             # webhook only in paper / live
        self.flag("insajderi2", "paper")
        ilive._WATCH.update(ts=0.0, v=[])
        self.assertEqual(sorted(ilive.webhook_wallets()), sorted([self.wa, self.wb]))


class Wiring(unittest.TestCase):
    def test_flag_never_live_order_and_fokus_exception(self):
        from ops import fokus
        from ui import assistnotes
        self.assertIn("insajderi2", settings.FLAGS)
        self.assertIn("insajderi2", settings.NEVER_LIVE)
        self.assertIn("insajderi2", settings.PROFILE_FLAGS)
        self.assertNotIn("insajderi2", settings.OWNER_SWITCHES)
        self.assertIn(("insajderi2", "paper"), [(n, m) for n, m, _w in assistnotes.OWNER_FLAG_ORDERS])
        self.assertNotIn(("insajderi2", "live"), [(n, m) for n, m, _w in assistnotes.OWNER_FLAG_ORDERS])
        with mock.patch.dict(os.environ, {"FOKUS_MIDCAP_FORCE": "1"}):
            self.assertIsNone(fokus.skip_cmd(["python3", "run_insajderi.py", "once"]))
            self.assertEqual(fokus.skip_cmd(["python3", "-m", "kol.precall", "night"]), "insajderi")

    def test_mcp_card_critic_and_catalyst_task(self):
        from critic import deep
        from ui import mcpapi
        self.assertIn("get_insiders2", [t["name"] for t in mcpapi.TOOLS])
        self.assertIn("insajderi2", [k for k, _f in deep.CONTEXT_BLOCKS])
        with tempfile.TemporaryDirectory() as d:
            p, ch = build_world(d, 4)
            now = t0_of(4) + 86400
            with mock.patch.dict(os.environ, {"INSAJDERI_DB": p["insajderi_db"]}):
                self.assertFalse(report.mcp({})["available"])
                self.assertIsNone(report.critic_summary())
                run.run("once", now=now, cfg=cfg(), credits=10_000, fetch=ch.fetch, log=lambda m: None, **p)
                m = report.mcp({"limit": 5})
                self.assertTrue(m["available"])
                self.assertIn("nasa_pravila", m["copyability"])
                self.assertTrue(m["groups"])
                d2, err = mcpapi._tool("get_insiders2", {"limit": 3})
                self.assertFalse(err)
                self.assertTrue(d2["available"])
                html = report.card_html(lambda t, meta, inner, sid=None: f"<{sid}>{t}|{meta}|{inner}", None,
                                        lambda x: str(x), True)
                self.assertIn("Insajderi 2.0", html)
                self.assertEqual(report.card_html(None, None, None, False), "")
                self.assertIn("kopiranje_walk_forward", report.critic_summary())
                from ui import assistnotes
                tc = sqlite3.connect(p["trade_db"])
                tc.executescript(assistnotes.SCHEMA)
                tc.commit()
                tasks = report.catalyst_tasks(5, now + 3600, trade_db=p["trade_db"])
                self.assertTrue(tasks)
                tok0 = tasks[0]["token"]
                tc.execute("INSERT INTO assistant_notes (ts, kind, token, verdict, interpretation, evidence) VALUES "
                           "(?,?,?,?,?,?)", (now, "signal_opinion", tok0, "neutralan", "listing na burzi",
                                             json.dumps({"source": "catalyst_check"})))
                tc.commit()
                tc.close()
                left = report.catalyst_tasks(5, now + 3600, trade_db=p["trade_db"])
                self.assertNotIn(tok0, [e["token"] for e in left])
                self.assertIn("insajderi2: događaja", report.lines(run.summary())[0])
