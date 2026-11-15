"""15.11. (vlasnik: "do insiders hold a large share of supply — if yes, be careful — but the holders of large shares are
often EXCHANGES ... if a large part of the supply is sent to an external wallet previously known as an exchange wallet,
that must be a STRONG signal"; "if the token is NOT yet listed on that exchange, how would anyone sell it there?";
"find wallets that hold large amounts of established, profitable tokens ... what are they buying now?"): holderi/,
offline (synthetic holders / transfers, no network).

  - an exchange holder is never counted as an insider (insider share excludes exchanges and LP)
  - 2 % of supply from the team to a known exchange that does NOT list the token -> PRE-LISTING signal, the loud line,
    the owner's notification, the priority bonus; the same to an exchange that lists it -> deposit to sell + caution
  - an unconfirmed address lowers the score; a symbol-only listing match is "nesigurno"
  - a per-user deposit address that sweeps into a known hot wallet counts; a new balance at an exchange is evidence
  - the insider caution lowers the priority / blocks, and is the "zašto je pao" reason; the real account's order leaves
    the listing bonus out (holderi/config.json listing_real off)
  - the Helius budget cap stops the reads; the exchange list counts
  - profitable diamond holders: cost basis, buys, clusters, the digest and the follow measurement

    python3 -m unittest tests.test_holderi_offline
"""
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from holderi import burze, chain, klasa, profit, run, signal, store, view  # noqa: E402
from trade import settings  # noqa: E402

NOW = (int(time.time()) // 86400 - 2) * 86400 + 12 * 3600   # two days ago, noon UTC
MINT = "MiNTAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"[:44]
POOL = "PooLAuthAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"[:44]
TEAM = "TeamAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"[:44]
W1 = "WhaAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"[:44]
EXA = "ExchAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"[:44]
EXB = "ExchBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"[:44]
DEP = "DepoAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"[:44]
SUPPLY = 1e9


def rc(holders, creator=TEAM):
    """A RugCheck report of `holders` [(owner, pct, insider?)] (+ the pool)."""
    th = [{"address": "acct" + o[:8], "owner": o, "pct": p, "uiAmount": p / 100 * SUPPLY, "insider": bool(ins)}
          for o, p, *rest in holders for ins in [rest[0] if rest else False]]
    th.insert(0, {"address": "poolacct", "owner": POOL, "pct": 20.0, "uiAmount": 0.2 * SUPPLY})
    return {"token": {"supply": SUPPLY * 1e6, "decimals": 6}, "creator": creator, "topHolders": th,
            "knownAccounts": {POOL: {"name": "Raydium Authority", "type": "AMM"}},
            "markets": [{"pubkey": "mkt", "liquidityAAccount": {"owner": POOL}}]}


def tx(sig, ts, sol=None, toks=(), payer=None):
    """A raw jsonParsed tx: sol {wallet: SOL delta}, toks [(owner, mint, pre, post)] in UI units (6 decimals)."""
    keys = list(dict.fromkeys(([payer] if payer else []) + list(sol or {}) + [o for o, *_ in toks]))
    pre = [10 ** 12] * len(keys)
    post = [pre[i] + int((sol or {}).get(k, 0) * 1e9) for i, k in enumerate(keys)]

    def tb(i, o, m, a):
        return {"accountIndex": i, "mint": m, "owner": o, "uiTokenAmount": {"amount": str(int(a * 1e6)), "decimals": 6}}
    return {"blockTime": ts, "slot": 1, "transaction": {"signatures": [sig], "message": {
        "accountKeys": [{"pubkey": k} for k in keys]}},
        "meta": {"err": None, "preBalances": pre, "postBalances": post,
                 "preTokenBalances": [tb(i, o, m, a) for i, (o, m, a, b) in enumerate(toks)],
                 "postTokenBalances": [tb(i, o, m, b) for i, (o, m, a, b) in enumerate(toks)]}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = os.path.join(self.tmp.name, "holderi.db")
        seed = os.path.join(self.tmp.name, "burze.json")
        owner = os.path.join(self.tmp.name, "burze_vlasnik.json")
        with open(seed, "w") as f:
            json.dump({"adrese": [{"address": EXB, "exchange": "bybit", "kind": "hot", "confidence": 0.7,
                                   "source": "test seed"}]}, f)
        with open(owner, "w") as f:
            json.dump({"adrese": [{"address": EXA, "exchange": "mexc", "kind": "hot", "source": "vlasnik"},
                                  {"address": EXB, "exchange": "bybit"}][:1]}, f)
        self.owner_file = owner
        tdb = os.path.join(self.tmp.name, "trade.db")
        settings.connect(tdb).close()
        for p in (mock.patch.dict(os.environ, {"HOLDERI_DB": self.db, "WALLET_DB": os.path.join(self.tmp.name, "w.db"),
                                               "MIDCAP_DB": os.path.join(self.tmp.name, "midcap.db")}),
                  mock.patch.object(burze, "SEED", seed), mock.patch.object(burze, "OWNER", owner),
                  mock.patch.object(settings, "DB", tdb),
                  mock.patch.object(run, "px_now", lambda mints, path=None: {m: (1.0, 25e6) for m in mints}),
                  mock.patch.object(view, "write_md", lambda *a, **k: None)):
            p.start()
            self.addCleanup(p.stop)
        burze._C.update(ts=0.0, v=None)
        view._C.update(ts=0.0, v=None)
        self.sent = []
        run.NOTIFY["fn"] = self.sent.append
        self.addCleanup(run.NOTIFY.update, fn=None)
        self.lists = {"mexc": {"symbols": ["BTC", "ETH"], "contracts": []}, "bybit": {"symbols": ["BTC"], "contracts": []}}
        self.cg = []
        burze.FETCH.update(lists=lambda ex: self.lists.get(ex, {"symbols": ["BTC"], "contracts": []}),
                           cg=lambda m: self.cg)
        self.rc = {}
        self.txs = {}
        self.bal = {}
        chain.FETCH.update(rugcheck=lambda m: self.rc[m], txs=lambda a, since: self.txs.get(a, []),
                           busy=lambda a: (1.0, 10, 500.0), funder=lambda w: None,
                           token_accounts=lambda o, ms: self.bal.get(o, {}), supply=lambda m: SUPPLY)
        profit.FETCH.update(table=lambda: [])
        for d in (burze.FETCH, chain.FETCH, profit.FETCH):
            self.addCleanup(d.clear)
        self.tok = {"mint": MINT, "symbol": "MEME", "mcap": 25e6, "liq": 8e5, "vol24": 2e6, "pool": None}
        self.logs = []

    def pass_(self, now):
        return run.run_pass(now=now, log=self.logs.append, force=True, toks=[self.tok])

    def con(self):
        c = store.connect(self.db)
        self.addCleanup(c.close)
        return c


class Classes(Base):
    def test_exchange_holder_is_not_an_insider(self):
        reg = burze.registry(fresh=True)
        hs, pools, creator, known, sup = klasa.from_rugcheck(rc([(EXA, 12.0, True), (TEAM, 6.0), (W1, 2.0, True)]))
        rows = klasa.classify(hs, pools=pools, creator=creator, reg=reg, known=known)
        cls = {r["owner"]: r["cls"] for r in rows}
        self.assertEqual(cls, {POOL: "lp", EXA: "exchange", TEAM: "team", W1: "insider"})
        m = klasa.metrics(rows)
        self.assertEqual(m["insider_ex"], 8.0)              # team 6 + insider 2; the exchange's 12 % never counted
        self.assertEqual(m["shares"]["exchange"], 12.0)
        self.assertEqual(m["exchanges"], {"mexc": 12.0})
        self.assertEqual(m["top10_ex"], 8.0)
        self.assertEqual(m["hhi"], 12 ** 2 + 6 ** 2 + 2 ** 2)
        self.assertEqual(sup, SUPPLY)

    def test_registry_confidence_and_owner_confirmation(self):
        reg = burze.registry(fresh=True)
        self.assertEqual(reg[EXA]["status"], "potvrđeno")
        self.assertEqual(reg[EXA]["confidence"], 1.0)
        self.assertEqual(reg[EXB]["status"], "nepotvrđeno")
        self.assertLess(reg[EXB]["confidence"], 1.0)
        con = self.con()
        burze.add(con, DEP, "Binance", "deposit", 0.9, "Grok: label", "grok")
        con.commit()
        reg = burze.registry(fresh=True)
        self.assertEqual((reg[DEP]["exchange"], reg[DEP]["status"]), ("binance", "nepotvrđeno"))
        self.assertLessEqual(reg[DEP]["confidence"], 0.6)  # Grok never makes an address certain
        with self.assertRaises(ValueError):
            burze.add(con, "not an address!", "x")

    def test_the_shipped_seed_has_only_unconfirmed_addresses_with_a_source(self):
        with open(os.path.join(ROOT, "holderi", "burze.json"), encoding="utf-8") as f:
            seed = json.load(f)
        self.assertGreaterEqual(len(seed["adrese"]), 5)
        for e in seed["adrese"]:
            self.assertEqual(e["status"], "nepotvrđeno")
            self.assertTrue(e["source"])
            self.assertLess(e["confidence"], 1.0)
        with open(os.path.join(ROOT, "holderi", "burze_vlasnik.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["adrese"], [])


class Score(Base):
    def test_unverified_address_lowers_the_score(self):
        mv = [{"pct": 2.0, "sender_cls": "team", "kind": "to_exchange"}]
        sure = signal.score_group([dict(mv[0], conf=1.0)], "mexc", "ne")
        seed = signal.score_group([dict(mv[0], conf=0.7)], "mexc", "ne")
        heur = signal.score_group([dict(mv[0], conf=0.45)], "mexc", "ne")
        self.assertEqual(sure["score"], 70.0)              # size 40 + team 20 + tier-2 10
        self.assertGreater(sure["score"], seed["score"])
        self.assertGreater(seed["score"], heur["score"])
        self.assertLess(heur["score"], 60)                 # a heuristic address alone stays under the loud threshold
        self.assertIn("nepotvrđeno", " ".join(seed["reasons"]))

    def test_listing_status_changes_the_kind(self):
        mv = [{"pct": 2.0, "sender_cls": "team", "kind": "to_exchange", "conf": 1.0}]
        self.assertEqual(signal.score_group(mv, "mexc", "da")["kind"], "deposit_sell")
        unsure = signal.score_group(mv, "mexc", "nesigurno")
        self.assertEqual(unsure["kind"], "pre_listing")
        self.assertEqual(unsure["score"], 42.0)            # x 0.6: the same symbol may be another token
        con = self.con()
        burze.refresh_lists(con, NOW, log=self.logs.append)
        self.assertEqual(burze.listed(con, MINT, "eth", "mexc", NOW)[0], "nesigurno")
        self.assertEqual(burze.listed(con, MINT, "MEME", "mexc", NOW)[0], "ne")
        self.lists["mexc"]["contracts"] = [MINT]
        store.kv_put(con, "lst:mexc", {"ts": 0})
        burze.refresh_lists(con, NOW, log=self.logs.append)
        self.assertEqual(burze.listed(con, MINT, "MEME", "mexc", NOW)[0], "da")
        self.cg = ["kucoin"]
        store.kv_put(con, f"cg:{MINT}", {"ts": 0})
        self.assertEqual(burze.listed(con, MINT, "MEME", "kucoin", NOW)[0], "da")   # CoinGecko by contract

    def test_caution_on_insider_share(self):
        self.assertEqual(signal.caution({"insider_ex": 20.0})["pts"], 0.0)
        c = signal.caution({"insider_ex": 42.0})
        self.assertEqual((c["pts"], c["block"]), (-12.0, None))
        self.assertIn("insajderi", signal.caution({"insider_ex": 55.0})["block"])
        sold = signal.caution({"insider_ex": 10.0}, [{"pct": 1.5, "sender_cls": "team", "kind": "sell"}])
        self.assertTrue(sold["block"])
        self.assertEqual(sold["pts"], -20.0)

    def test_priority_components_and_the_reason(self):
        from veliki import prioritet
        base = {"vol24": 5e6, "v1h": 2e5, "trend": 10}
        s0, _ = prioritet.score(base)
        s1, p1 = prioritet.score(dict(base, holders={"listing": 35.0}))
        s2, p2 = prioritet.score(dict(base, holders={"oprez": -12.0}))
        self.assertEqual((round(s1 - s0, 1), p1["listing"]), (35.0, 35.0))
        self.assertEqual(round(s2 - s0, 1), -12.0)
        kind, why = prioritet.classify({"c24": -9, "holders": {"block": "insajderi drže 55 % ponude"}})
        self.assertEqual(kind, "los")
        self.assertIn("insajderi drže 55 %", why)            # "zašto je pao"
        prio = {"L": {"score": 60.0, "parts": {"listing": 35.0}}, "N": {"score": 40.0, "parts": {}}}
        self.assertEqual(prioritet.order(["N", "L"], prio), ["L", "N"])              # the demo: the bonus counts
        self.assertEqual(prioritet.order(["N", "L"], prio, real=True), ["N", "L"])   # real: 25 without it


class Pass(Base):
    def test_two_percent_from_the_team_to_a_known_exchange_is_a_loud_signal(self):
        self.rc[MINT] = rc([(TEAM, 5.0), (W1, 3.0)])
        self.pass_(NOW)
        self.rc[MINT] = rc([(TEAM, 3.0), (W1, 3.0), (EXA, 2.0)])
        self.txs[TEAM] = [tx("s1", NOW + 3600, toks=[(TEAM, MINT, 5e7, 3e7), (EXA, MINT, 0, 2e7)], payer=TEAM)]
        out = self.pass_(NOW + 7 * 3600)
        self.assertEqual(out["signals"], 1)
        con = self.con()
        mv = con.execute("SELECT sender_cls, dest_cls, exchange, pct, kind, conf FROM moves WHERE kind='to_exchange'"
                         ).fetchall()
        self.assertEqual(mv, [("team", "exchange", "mexc", 2.0, "to_exchange", 1.0)])
        kind, ex, score, listed, notified = con.execute(
            "SELECT kind, exchange, score, listed, notified FROM signals").fetchone()
        self.assertEqual((kind, ex, score, listed, notified), ("pre_listing", "mexc", 70.0, "ne", 1))
        loud = [x for x in self.logs if x.startswith("LISTING SIGNAL: MEME (MC $25.0M)")]
        self.assertEqual(len(loud), 1)
        self.assertIn("mogući listing na MEXC", loud[0])
        self.assertEqual(len(self.sent), 1)                 # the owner's notification
        pri = view.prio_facts(self.db, 10 ** 9)[MINT]
        self.assertEqual((pri["listing"], pri["listing_ex"]), (35.0, "mexc"))
        self.assertEqual(self.pass_(NOW + 7 * 3600 + 600)["signals"], 0)   # stored once, not every pass
        self.assertEqual(len(self.sent), 1)
        ls = view.listing_signals({"days": 30})
        self.assertTrue(ls["available"])
        self.assertEqual(ls["signals"][0]["exchange_name"], "MEXC")

    def test_deposit_to_an_exchange_that_lists_it_is_caution_not_a_buy(self):
        self.lists["mexc"]["contracts"] = [MINT]
        self.rc[MINT] = rc([(TEAM, 5.0), (W1, 3.0)])
        self.pass_(NOW)
        self.rc[MINT] = rc([(TEAM, 3.0), (W1, 3.0), (EXA, 2.0)])
        self.txs[TEAM] = [tx("s1", NOW + 3600, toks=[(TEAM, MINT, 5e7, 3e7), (EXA, MINT, 0, 2e7)], payer=TEAM)]
        self.pass_(NOW + 7 * 3600)
        con = self.con()
        self.assertEqual(con.execute("SELECT kind FROM signals").fetchone()[0], "deposit_sell")
        self.assertEqual(self.sent, [])
        pri = view.prio_facts(self.db, 10 ** 9)[MINT]
        self.assertFalse(pri["listing"])
        self.assertIn("izbacuju", pri["block"])
        self.assertTrue(any("VEĆ listan" in x for x in self.logs))

    def test_a_deposit_address_that_sweeps_into_a_hot_wallet_counts(self):
        self.rc[MINT] = rc([(W1, 4.0)])
        self.pass_(NOW)
        self.rc[MINT] = rc([(W1, 2.5)])
        self.txs[W1] = [tx("a", NOW + 3600, toks=[(W1, MINT, 4e7, 2.5e7), (DEP, MINT, 0, 1.5e7)], payer=W1)]
        self.txs[DEP] = [tx("b", NOW + 3700, toks=[(DEP, MINT, 1.5e7, 0), (EXB, MINT, 0, 1.5e7)], payer=DEP)]
        self.pass_(NOW + 7 * 3600)
        con = self.con()
        mv = con.execute("SELECT dest, exchange, kind, conf FROM moves WHERE sender=?", (W1,)).fetchone()
        self.assertEqual(mv, (DEP, "bybit", "deposit_sweep", 0.63))   # the seed's 0.7 x 0.9
        kind, score = con.execute("SELECT kind, score FROM signals").fetchone()
        self.assertEqual(kind, "pre_listing")
        self.assertAlmostEqual(score, round((30 + 8 + 15) * burze.weight(0.63), 1))

    def test_a_new_balance_at_an_exchange_is_evidence(self):
        self.rc[MINT] = rc([(W1, 3.0)])
        self.pass_(NOW)                                      # the first look at the exchange wallets: the baseline
        self.bal[EXA] = {MINT: 0.015 * SUPPLY}
        self.pass_(NOW + 7 * 3600)
        con = self.con()
        self.assertEqual(con.execute("SELECT kind, exchange, pct FROM moves WHERE dest=?", (EXA,)).fetchone(),
                         ("new_balance", "mexc", 1.5))
        kind, score = con.execute("SELECT kind, score FROM signals").fetchone()
        self.assertEqual((kind, score), ("pre_listing", 45.0))   # 30 + untraced 5 + tier 10 (one reading: no growth)
        self.assertEqual(self.sent, [])                      # under the loud threshold
        self.assertEqual(view.prio_facts(self.db, 10 ** 9)[MINT]["listing"], 22.5)

    def test_outcomes_against_the_control(self):
        con = self.con()
        con.execute("INSERT INTO signals (mint, symbol, ts, kind, exchange, score, reasons, px) VALUES "
                    "(?,?,?,?,?,?,?,?)", (MINT, "MEME", NOW, "pre_listing", "mexc", 70, "[]", 1.0))
        con.commit()
        with mock.patch.object(run, "px_now", lambda mints, path=None: {MINT: (1.3, 30e6)}):
            self.assertEqual(run.outcomes(con, NOW + 3600 + 60), 1)
        r = view.listing_signals({"days": 30})["signals"][0]
        self.assertEqual(r["ret_1h_pct"], 30.0)
        self.assertIsNone(r["ret_24h_pct"])

    def test_budget_cap_stops_the_reads(self):
        con = self.con()
        b = chain.Budget(con, 240, NOW - NOW % 86400)       # hour 0: 1/24 of the day = 10 credits
        self.assertTrue(b.take(10))
        self.assertIsNone(chain.txs(W1, 0, b))               # 10 more: refused, no read
        self.assertIsNone(chain.busy(W1, b))
        self.assertEqual(b.refused, 2)
        self.assertEqual(b.close(), 10)
        self.assertEqual(store.kv_get(con, f"cnt:{store.day(NOW)}")["helius"], 10)
        b2 = chain.Budget(con, 240, NOW - NOW % 86400)
        self.assertEqual(b2.left(), 0)                       # the spent credits count for the rest of the day

    def test_switch_off_does_nothing(self):
        with mock.patch("ops.fokus.on", return_value=False):
            self.assertEqual(run.run_pass(now=NOW, log=self.logs.append, toks=[self.tok]), {})
        self.assertFalse(os.path.exists(self.db))


class Profitable(Base):
    BIG = "BigAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"[:44]
    NEW = "NewTokAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"[:44]
    H1 = "HoLdAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"[:44]
    H2 = "HoLdBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"[:44]
    H3 = "HoLdCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"[:44]

    def test_diamonds_their_buys_clusters_and_the_digest(self):
        B, N = self.BIG, self.NEW
        self.rc[B] = rc([(self.H1, 2.0), (self.H2, 1.5), (self.H3, 1.0), (EXA, 5.0)], creator=None)
        profit.FETCH.update(table=lambda: [{"mint": B, "symbol": "BIG", "cat": "A"}], sol_usd=lambda ts: 150.0,
                            px_day=lambda m, ts: None,
                            dex=lambda ms: {m: v for m, v in {B: (1.0, 1e9, 5e6, "BIG"),
                                                              N: (0.002, 3e6, 2e5, "NEW")}.items() if m in ms})
        old = NOW - 90 * 86400
        hist = {"acct" + self.H1[:8]: [tx("h1", old, sol={self.H1: -100}, toks=[(self.H1, B, 0, 2e7)])],
                "acct" + self.H2[:8]: [tx("h2", old, sol={self.H2: -50}, toks=[(self.H2, B, 0, 1.5e7)])],
                "acct" + self.H3[:8]: [tx("h3", old, toks=[(self.H3, B, 0, 1e7)], payer="Someone11111111111111111111111111")]}
        chain.FETCH["history"] = lambda a: hist.get(a, [])
        self.txs[self.H1] = [tx("b1", NOW - 2 * 86400, sol={self.H1: -1}, toks=[(self.H1, N, 0, 1000)])]
        self.txs[self.H2] = [tx("b2", NOW - 86400, sol={self.H2: -2}, toks=[(self.H2, N, 0, 1500)])]
        fund = {self.H1: "FunderOne1111111111111111111111111", self.H2: "FunderTwo1111111111111111111111111"}
        chain.FETCH["funder"] = lambda w: fund.get(w)
        run.run_pass(now=NOW, log=self.logs.append, force=True, toks=[{"mint": B, "symbol": "BIG", "mcap": 1e9}])
        con = self.con()
        pos = {w: (d, m) for w, d, m in con.execute("SELECT wallet, diamond, mult FROM holder_pos")}
        self.assertNotIn(EXA, pos)                           # exchanges are not "holders in profit"
        self.assertEqual(pos[self.H1][0], 1)
        self.assertGreater(pos[self.H1][1], 100)             # $20M worth on $15k
        self.assertEqual(pos[self.H3][0], 0)                 # transfer in, cost unknown: never a diamond
        buys = con.execute("SELECT wallet, cluster, token, sol, usd, mc_at_buy, src_mint FROM holder_buys ORDER BY ts"
                           ).fetchall()
        self.assertEqual([(w, t, s, u, src) for w, _k, t, s, u, _mc, src in buys],
                         [(self.H1, N, 1.0, 150.0, B), (self.H2, N, 2.0, 300.0, B)])
        self.assertEqual(len({k for _w, k, *_r in buys}), 2)  # different funders, a day apart: two clusters
        self.assertEqual(buys[0][5], round(3e6 * (150 / 1000) / 0.002))
        d = profit.summary(con)
        self.assertEqual([(r["token"], r["clusters"], r["holders"]) for r in d["digest"]], [(N, 2, 2)])
        self.assertEqual(con.execute("SELECT clusters, px FROM follow WHERE token=?", (N,)).fetchone(), (2, 0.002))
        profit.FETCH["dex"] = lambda ms: {N: (0.003, 4.5e6, 2e5, "NEW")}
        self.assertEqual(profit.follow_outcomes(con, NOW + 3700), 1)
        m = profit.measure(con)
        self.assertEqual(m["1h"]["n"], 1)
        self.assertGreater(m["1h"]["ev_pct"], 40)            # +50 % less the round-trip cost
        self.assertTrue(view.profitable_holders({})["available"])

    def test_same_funder_is_one_cluster(self):
        con = self.con()
        for w in (self.H1, self.H2):
            con.execute("INSERT INTO holder_pos (wallet, mint, ts, diamond) VALUES (?,?,?,1)", (w, self.BIG, NOW))
            con.execute("INSERT INTO funders VALUES (?,?,?)", (w, "SameFunder111111111111111111111111", NOW))
        cl = profit.clusters(con, run.config(), NOW, chain.Budget(con, 1000, NOW))
        self.assertEqual(cl[self.H1], cl[self.H2])


class Wiring(Base):
    def test_tools_card_critic_and_task(self):
        from critic import deep
        from ui import mcpapi
        names = {t["name"]: t for t in mcpapi.TOOLS}
        for n in ("get_holder_profile", "get_listing_signals", "get_profitable_holders"):
            self.assertTrue(names[n]["annotations"]["readOnlyHint"], n)
        self.assertFalse(names["submit_exchange_wallet"]["annotations"]["destructiveHint"])
        self.assertIn("holderi_listing", [k for k, _f in deep.CONTEXT_BLOCKS])
        self.rc[MINT] = rc([(TEAM, 5.0), (W1, 3.0)])
        self.pass_(NOW)
        d, err = mcpapi._tool("get_holder_profile", {"token": MINT})
        self.assertFalse(err)
        self.assertEqual(d["shares_pct"]["team"], 5.0)
        d, err = mcpapi._tool("submit_exchange_wallet", {"address": DEP, "exchange": "okx", "evidence": "label"})
        self.assertFalse(err)
        self.assertEqual(burze.registry(fresh=True)[DEP]["status"], "nepotvrđeno")
        html = view.card_html(lambda t, m, i, sid=None: f"<sec>{t}|{m}|{i}</sec>", None, lambda x: x)
        self.assertIn("Listing signali i holderi", html)
        self.assertEqual(view.card_html(None, None, None, owner=False), "")
        self.assertIsNotNone(view.critic_summary())


if __name__ == "__main__":
    unittest.main()
