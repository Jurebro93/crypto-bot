"""Insajderski novčanici influencera (16.11., vlasnik: "Kako naći njihove sekundarne wallete ... Mora postojati stavka
'insider wallet' i algoritam koji ih traži"; insajderi/kolwallets.py) on a synthetic chain, no network:

  - a group that buys before an influencer's calls again and again and sells into them is found, with wallet rotation
    merged into ONE owner; the numbers (calls front-run, share sold into, lift, exclusivity, lead) are right
  - "potvrđen" needs 3+ calls, the newer third and a lift above chance; a wallet with 2 calls is a "kandidat"
  - the split (the public wallet moves tokens to a side wallet that sells) and a first funding from the public wallet
    are direct links; a link to a wallet the person denied never counts; a transfer INTO a public wallet is weak
  - bots, snipers and wallets that buy everything are out; an unresolved handle is "handle nije potvrđen"
  - the pass is bounded (credits, time), never raises, and spends nothing when there are no calls
  - the owner's page renders at 390 px without horizontal overflow, others never get it; the MCP tools

    python3 -m unittest tests.test_kolwallets_offline
"""
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from insajderi import chain, kolwallets as kw, run, store  # noqa: E402

BASE = (1794000000 // 86400) * 86400
NOW = BASE + 20 * 86400
D = 86400


def addr(name):
    return (name + "1" * 44)[:44]


PUB, PUBB, DISP = addr("Pubwa"), addr("Pubbeta"), addr("Disputed")
I1, I2, F = addr("Insone"), addr("Instwo"), addr("Funder")
BUSY, RND, SNIP = addr("Busy"), addr("Random"), addr("Sniper")
SIDE, SIDE1, DSIDE, BSIDE = addr("Side"), addr("Sideone"), addr("Dside"), addr("Bside")
K2, FAN, EXCH = addr("Kandtwo"), addr("Fan"), addr("Exchange")
T = [addr(f"Token{k}") for k in range(1, 7)]
AB = "ABCDEFGHJKMN"   # twelve base58 letters: addr("x1") and addr("x11") would be the same address
N = [addr(f"Noise{x}") for x in AB]
D1 = addr("Deltatoken")


def t0_of(k):
    """The call time of alfa's k-th token (1..6): one a day."""
    return BASE + k * D + 12 * 3600


def n0_of(k):
    return BASE + k * D + 3 * 3600


class Chain:
    """Raw transactions by address (mint, token account, wallet) and a fake Helius fetch that charges 10 a page."""

    def __init__(self):
        self.by, self.n, self.calls = {}, 0, []

    def _put(self, t, *addresses):
        for a in addresses:
            self.by.setdefault(a, []).append(t)
        return t

    def swap(self, mint, signer, side, sol, tokens, ts):
        self.n += 1
        acct = addr("Acct" + signer[:6] + mint[:7])
        keys = [{"pubkey": signer, "signer": True}, {"pubkey": acct, "signer": False},
                {"pubkey": addr("Poo"), "signer": False}]
        pre_l = [10_000_000_000] * 3
        post_l = list(pre_l)
        post_l[0] += int((-sol if side == "buy" else sol) * 1e9)
        pre_t = 5_000_000.0 if side == "sell" else 0.0
        post_t = pre_t + (tokens if side == "buy" else -tokens)

        def bal(amt):
            return [{"accountIndex": 1, "mint": mint, "owner": signer,
                     "uiTokenAmount": {"amount": str(int(amt * 1e6)), "decimals": 6}}]
        return self._put({"blockTime": int(ts), "slot": int(ts) * 2,
                          "transaction": {"signatures": [f"sig{self.n}"], "message": {"accountKeys": keys}},
                          "meta": {"err": None, "preBalances": pre_l, "postBalances": post_l,
                                   "preTokenBalances": bal(pre_t), "postTokenBalances": bal(post_t)}}, mint, acct)

    def token_move(self, mint, src, dst, tokens, ts):
        """src (the signer) moves tokens to dst: no SOL leg but the fee."""
        self.n += 1
        keys = [{"pubkey": src, "signer": True}, {"pubkey": addr("Ta" + src[:5]), "signer": False},
                {"pubkey": addr("Tb" + dst[:5]), "signer": False}]

        def bal(i, owner, amt):
            return {"accountIndex": i, "mint": mint, "owner": owner,
                    "uiTokenAmount": {"amount": str(int(amt * 1e6)), "decimals": 6}}
        return self._put({"blockTime": int(ts), "slot": int(ts) * 2,
                          "transaction": {"signatures": [f"mv{self.n}"], "message": {"accountKeys": keys}},
                          "meta": {"err": None, "preBalances": [10_000_000_000, 2_000_000, 0],
                                   "postBalances": [9_999_995_000, 2_000_000, 2_000_000 * 0],
                                   "preTokenBalances": [bal(1, src, 9_000_000.0)],
                                   "postTokenBalances": [bal(1, src, 9_000_000.0 - tokens), bal(2, dst, tokens)]}},
                         mint, src, dst)

    def sol_move(self, src, dst, sol, ts):
        self.n += 1
        keys = [{"pubkey": src, "signer": True}, {"pubkey": dst, "signer": False}]
        return self._put({"blockTime": int(ts), "slot": int(ts) * 2,
                          "transaction": {"signatures": [f"so{self.n}"], "message": {"accountKeys": keys}},
                          "meta": {"err": None, "preBalances": [50_000_000_000, 0],
                                   "postBalances": [50_000_000_000 - int(sol * 1e9) - 5000, int(sol * 1e9)],
                                   "preTokenBalances": [], "postTokenBalances": []}}, src, dst)

    def fetch(self, address, since_ts=None, until_ts=None, max_pages=3, oldest_first=False, on_credits=None):
        self.calls.append(address)
        xs = [t for t in self.by.get(address, []) if (since_ts is None or t["blockTime"] > since_ts)
              and (until_ts is None or t["blockTime"] <= until_ts)]
        xs.sort(key=lambda t: t["blockTime"], reverse=not oldest_first)
        out = xs[:100 * max_pages]
        if on_credits:
            for _ in range(max(1, -(-len(out) // 100))):
                on_credits(10)
        return out, len(xs) <= 100 * max_pages


def seed_file(d):
    path = os.path.join(d, "kol_seed.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"influenceri": [
            {"id": "alfa", "name": "Alfa", "handles": ["alfa_x"],
             "wallets": [{"address": PUB, "status": "javna_oznaka", "source": "https://example.org/alfa"}]},
            {"id": "beta", "name": "Beta", "handles": ["@beta_x"],
             "wallets": [{"address": PUBB, "status": "javna_oznaka", "source": "https://example.org/beta"}]},
            {"id": "gama", "name": "Gama", "handles": [], "wallets": [], "note": "handle nije poznat"},
            {"id": "delta", "name": "Delta", "handles": ["delta_x"],
             "wallets": [{"address": DISP, "status": "osporeno", "source": "https://example.org/delta"},
                         {"address": "nije adresa", "status": "javna_oznaka"}]},
        ]}, f)
    return path


def build_world(d):
    """kol.db calls and tokens, wallets.db funder sightings, and the chain."""
    from kol import store as kstore
    from wallets import store as wstore
    p = {k: os.path.join(d, f"{k}.db") for k in ("kol_db", "hype_db", "early_db", "wallet_db", "minute_db", "midcap_db",
                                                   "xfeat_db", "trade_db", "usage_db", "corr_db", "listing_db", "rug_db",
                                                   "insajderi_db", "league_db", "tg_db", "makroinf_db")}
    kc = kstore.connect(p["kol_db"])
    wc = sqlite3.connect(p["wallet_db"])
    wc.executescript(wstore.SCHEMA)
    for w in (I1, I2):   # the rotation: two wallets, one funder
        wc.execute("INSERT INTO wallet_sightings VALUES (?,?,?,?,?,?,?)", (w, T[0], "rug", "holder", BASE, 1.0,
                                                                           json.dumps({"funder": F})))
    ch = Chain()

    def call(tok, handle, ts, sym, k):
        kc.execute("INSERT INTO tokens (token, symbol, supply, created_ts) VALUES (?,?,?,?)", (tok, sym, 1e9, ts - 3 * D))
        kc.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, mcap0, symbol, url, r1h, r24h) VALUES "
                   "(?,?,?,?,?,?,?,?,?,?)", (f"tw{handle}{k}", tok, handle, ts, "call", 120_000, sym,
                                             f"https://x.com/{handle}/status/{k}", 0.4, -0.2))

    for k in range(1, 7):   # alfa's six calls
        tok, t0 = T[k - 1], t0_of(k)
        call(tok, "alfa_x", t0, f"T{k}", k)
        if k <= 5:   # the insider group: 30 min before, out 10 min after (wallet rotation after the third)
            ins = I1 if k <= 3 else I2
            ch.swap(tok, ins, "buy", 2.0, 1_000_000, t0 - 1800)
            ch.swap(tok, ins, "sell", 3.0, 1_000_000, t0 + 600)
        ch.swap(tok, BUSY, "buy", 1.0, 500_000, t0 - 2 * 3600)          # buys before everything
        if k <= 2:
            ch.swap(tok, RND, "buy", 0.5, 200_000, t0 - 2 * D)          # two of alfa's by chance
            ch.swap(tok, K2, "buy", 0.8, 300_000, t0 - 900)             # two calls + (later) funded by the public wallet
            ch.swap(tok, K2, "sell", 1.2, 300_000, t0 + 1200)
        if k <= 3:
            ch.swap(tok, SNIP, "buy", 0.3, 900_000, t0 - 3 * D + 5)     # 5 s after the launch
            ch.swap(tok, SNIP, "sell", 0.6, 900_000, t0 + 300)
        ch.swap(tok, addr(f"Crowd{k}"), "buy", 0.4, 100_000, t0 + 60)   # the crowd he brought
    for tok in (T[4], T[5]):   # the split: the public wallet moves tokens to a side wallet that sells into the call
        t0 = t0_of(T.index(tok) + 1)
        ch.token_move(tok, PUB, SIDE, 400_000, t0 - 600)
        ch.swap(tok, SIDE, "sell", 1.5, 400_000, t0 + 300)
    ch.token_move(T[5], PUB, SIDE1, 100_000, t0_of(6) - 500)   # a second side wallet of the same public wallet
    ch.swap(T[5], SIDE1, "sell", 0.4, 100_000, t0_of(6) + 400)
    ch.token_move(T[0], FAN, PUB, 50_000, t0_of(1) - 3600)     # a gift INTO the public wallet: weak
    ch.swap(T[0], FAN, "buy", 0.5, 150_000, t0_of(1) - 2 * 3600)
    ch.sol_move(PUB, K2, 1.5, BASE - 30 * D)                   # the public wallet funded K2 (its first inflow)
    ch.sol_move(EXCH, K2, 3.0, BASE - 20 * D)
    for k in range(1, 13):   # beta's twelve calls: the universe the lift is measured on
        tok, t0 = N[k - 1], n0_of(k)
        call(tok, "beta_x", t0, f"N{k}", k)
        ch.swap(tok, BUSY, "buy", 1.0, 500_000, t0 - 3600)
        ch.swap(tok, addr(f"Other{AB[k - 1]}"), "buy", 0.7, 300_000, t0 - 7200)
        if k <= 4:
            ch.swap(tok, RND, "buy", 0.5, 200_000, t0 - D)
    ch.token_move(N[0], PUBB, BSIDE, 100_000, n0_of(1) - 500)   # beta: one call only, a link alone
    ch.swap(N[0], BSIDE, "sell", 0.4, 100_000, n0_of(1) + 400)
    call(D1, "delta_x", BASE + 9 * D, "DLT", 1)
    ch.token_move(D1, DISP, DSIDE, 200_000, BASE + 9 * D - 300)   # a link to a wallet the person denied
    ch.swap(D1, DSIDE, "sell", 0.9, 200_000, BASE + 9 * D + 200)
    kc.commit()
    wc.commit()
    kc.close()
    wc.close()
    return p, ch


def cfg(**k):
    c = {"days": 40, "warmup_days": 1, "sol_usd_hist": False, "mkt_days": 40, "helius_day": 100_000}
    c.update(k)
    return store.config(c)


def load_chain(con, ch, c):
    """What a Helius read of every mint would have stored: the trades (i2_trades) and the transfers."""
    kw.ensure(con)
    for a, txs in ch.by.items():
        if a in T + N + [D1]:
            con.executemany("INSERT OR IGNORE INTO i2_trades VALUES (?,?,?,?,?,?,?,?,?,?)", chain._rows_of(txs, a))
            kw.save_transfers(con, txs, c, mint=a)
    con.commit()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p, self.ch = build_world(self.tmp.name)
        self.seed = seed_file(self.tmp.name)
        self.c = cfg()
        self.con = store.connect(self.p["insajderi_db"])
        self.addCleanup(self.con.close)
        self.logs = []
        # no network, ever: a test that reaches past this machine fails loudly (the page tests talk to 127.0.0.1)
        real = socket.create_connection

        def local_only(address, *a, **k):
            if address[0] not in ("127.0.0.1", "localhost"):
                raise AssertionError(f"mreža u offline testu: {address}")
            return real(address, *a, **k)
        net = mock.patch.object(socket, "create_connection", side_effect=local_only)
        net.start()
        self.addCleanup(net.stop)
        ex = mock.patch.object(kw, "_exchanges", return_value={EXCH})
        ex.start()
        self.addCleanup(ex.stop)

    def run_pass(self, credits=0, fetch=None, **k):
        return kw.run_pass(self.con, self.p, k.pop("c", self.c), NOW, kind=k.pop("kind", "night"), fetch=fetch,
                           credits=credits, log=self.logs.append, seed=self.seed)

    def groups(self, inf):
        rows = [d for d in kw.view(self.p["insajderi_db"]) if d["id"] == inf]
        return {tuple(g["members"]): g for g in rows[0]["wallets"]} if rows else {}

    def group_of(self, inf, wallet):
        return next((g for ms, g in self.groups(inf).items() if wallet in ms), None)


class Pure(unittest.TestCase):
    """The pure parts: the trades around a call, the transfers of a raw transaction, the numbers and the classes."""

    def setUp(self):
        self.c = cfg()

    def test_around_buckets_and_front_needs_a_position_at_the_call(self):
        t0 = BASE + 10 * D
        tr = [("A", t0 - 300, "buy", 1.0, None, "x"), ("A", t0 + 600, "sell", 2.0, None, "x"),
              ("A", t0 + 600, "sell", 2.0, None, "y"),                                   # the same trade, twice
              ("B", t0 - 5 * D, "buy", 1.0, None, "x"), ("B", t0 - 4 * D, "sell", 1.2, None, "x"),   # out before the call
              ("B", t0 + 60, "sell", 0.5, None, "x"),
              ("C", t0 - 2 * 3600, "buy", 1.0, None, "x"), ("C", t0 + 5 * 3600, "sell", 1.0, None, "x"),
              ("E", t0 - 6 * D, "buy", 0.01, None, "x"),                                 # dust
              ("G", t0 - 8 * D, "buy", 5.0, None, "x"), ("G", t0 + 2 * D, "sell", 9.0, None, "x")]   # outside both
        r = kw.around(tr, t0, self.c)
        self.assertEqual((r["A"]["front"], r["A"]["sold"], r["A"]["sold60"], r["A"]["n_sells"]), (1, 1, 1, 1))
        self.assertEqual(kw.bucket(r["A"]["lead_s"]), "<10 min")
        self.assertEqual((r["B"]["front"], r["B"]["sold"]), (0, 1))                     # sold again before the call
        self.assertEqual((r["C"]["front"], r["C"]["sold"], r["C"]["sold60"]), (1, 1, 0))   # sold, but not in the hour
        self.assertEqual(kw.bucket(r["C"]["lead_s"]), "<24 h")
        self.assertNotIn("E", r)
        self.assertNotIn("G", r)
        self.assertEqual(kw.bucket(3 * D), "<7 d")

    def test_transfers_of_raw_transactions(self):
        ch = Chain()
        mv = ch.token_move(T[0], PUB, SIDE, 1000, 500)
        self.assertEqual([(s, d, amt, m) for _sig, _ts, s, d, amt, m in kw.token_moves(mv, T[0])],
                         [(PUB, SIDE, 1000.0, T[0])])
        self.assertEqual(len(kw.token_moves(mv)), 1)                                   # every mint of the transaction
        self.assertEqual(kw.token_moves(ch.swap(T[0], I1, "sell", 2.0, 1000, 600), T[0]), [])   # a swap is no transfer
        self.assertEqual(kw.sol_moves(mv), [])                                         # touches tokens: no SOL transfer
        so = ch.sol_move(PUB, K2, 1.5, 700)
        self.assertEqual([(s, d, sol) for _sig, _ts, s, d, sol in kw.sol_moves(so)], [(PUB, K2, 1.5)])
        self.assertEqual(kw.sol_moves(ch.sol_move(PUB, K2, 0.01, 800)), [])            # under the smallest transfer

    def _by(self, n, sold=None, t=lambda k: BASE + k * D):
        return {f"t{k}": {"t0": t(k), "front": True, "first_buy": t(k) - 600, "last_buy": t(k) - 600,
                          "sold": k in (sold or range(1, n + 1)), "sold60": True, "first_sell": t(k) + 60,
                          "sol_in": 1.0, "sol_out": 1.5, "wallets": {}} for k in range(1, n + 1)}

    def test_lift_exclusivity_and_share_sold(self):
        order = [(BASE + k * D, f"t{k}") for k in range(1, 7)]
        st = kw.stats_of(self._by(5, sold={1, 2, 3, 4}), order, n_w=5, u=18, c=self.c)
        self.assertEqual((st["n_front"], st["n_sold"], st["share_sold"]), (5, 4, 0.8))
        self.assertEqual(st["lift"], 3.0)                # 5 of his 6 against 5 x 6 / 18 expected by chance
        self.assertEqual(st["exclusivity"], 1.0)         # every event it front-ran is his
        self.assertEqual((st["med_lead_min"], st["sol_in"], st["sol_out"]), (10.0, 5.0, 6.0))
        busy = kw.stats_of(self._by(5), order, n_w=15, u=18, c=self.c)
        self.assertEqual((busy["lift"], busy["exclusivity"]), (1.0, 0.333))   # trades everything: no information

    def test_classes_and_the_out_of_sample_rule(self):
        order = [(BASE + k * D, f"t{k}") for k in range(1, 7)]
        ok = kw.stats_of(self._by(5), order, 5, 18, self.c)                 # 4 in the older two thirds, 1 in the newer
        self.assertTrue(ok["oos"])
        self.assertEqual(kw.klass(ok, False, self.c)[0], "potvrđen")
        old_only = kw.stats_of(self._by(4), order, 4, 18, self.c)           # all four before the cut: nothing newer
        self.assertFalse(old_only["oos"])
        cls, why = kw.klass(old_only, False, self.c)
        self.assertEqual(cls, "kandidat")
        self.assertIn("nije potvrđeno na novijim pozivima", why)
        chance = kw.stats_of(self._by(5), order, 15, 18, self.c)            # confirmed in time, but not above chance
        cls, why = kw.klass(chance, False, self.c)
        self.assertEqual(cls, "kandidat")
        self.assertIn("iznad slučajnosti", why)
        small = kw.stats_of(self._by(5), order, 5, 6, self.c)               # too few events to compare with chance
        self.assertEqual(kw.klass(small, False, self.c)[0], "kandidat")
        two = kw.stats_of(self._by(2), order, 2, 18, self.c)
        self.assertEqual(kw.klass(two, False, self.c)[0], "kandidat")
        self.assertEqual(kw.klass(two, True, self.c)[0], "potvrđen")        # a direct link and two calls
        one = kw.stats_of(self._by(1), order, 1, 18, self.c)
        self.assertEqual(kw.klass(one, False, self.c), (None, None))        # one call: not listed
        self.assertEqual(kw.klass(one, True, self.c)[0], "kandidat")        # a link alone
        buys = self._by(5)                                                  # four of the five are buys of his public
        for k in (2, 3, 4, 5):                                              # wallet, one is a post: never confirmed
            buys[f"t{k}"]["kind"] = "javna_kupnja"
        st = kw.stats_of(buys, order, 5, 18, self.c)
        self.assertEqual((st["n_front"], st["n_posts"], st["oos"]), (5, 1, True))
        cls, why = kw.klass(st, False, self.c)
        self.assertEqual(cls, "kandidat")
        self.assertIn("kupnje javnog novčanika", why)

    def test_links_split_funding_two_hops_and_never_through_a_hub(self):
        pub = {PUB: "javna_oznaka", DISP: "osporeno"}
        tr = [{"sig": "a", "ts": 100, "kind": "token", "src": PUB, "dst": SIDE, "amount": 5.0, "mint": T[0], "first_in": 0},
              {"sig": "b", "ts": 50, "kind": "sol", "src": F, "dst": PUB, "amount": 2.0, "mint": "", "first_in": 1},
              {"sig": "c", "ts": 60, "kind": "sol", "src": F, "dst": I1, "amount": 2.0, "mint": "", "first_in": 1},
              {"sig": "d", "ts": 70, "kind": "sol", "src": EXCH, "dst": PUB, "amount": 9.0, "mint": "", "first_in": 0},
              {"sig": "e", "ts": 80, "kind": "sol", "src": EXCH, "dst": RND, "amount": 9.0, "mint": "", "first_in": 1},
              {"sig": "f", "ts": 90, "kind": "token", "src": FAN, "dst": PUB, "amount": 1.0, "mint": T[0], "first_in": 0},
              {"sig": "g", "ts": 95, "kind": "token", "src": DISP, "dst": DSIDE, "amount": 1.0, "mint": T[0], "first_in": 0}]
        strong, weak = kw.ties(tr, pub, {EXCH}, {(SIDE, T[0]): [400]}, self.c)
        lk = {x["wallet"]: x for x in kw.find_links({SIDE, I1, RND, FAN, DSIDE}, pub, strong, weak)}
        self.assertEqual((lk[SIDE]["kind"], lk[SIDE]["hops"], lk[SIDE]["strong"]), ("podjela_tokena", 1, True))
        self.assertEqual((lk[I1]["kind"], lk[I1]["hops"], lk[I1]["via"], lk[I1]["strong"]),
                         ("zajednicki_izvor", 2, F, True))
        self.assertNotIn(RND, lk)                                           # the exchange paid both: not a link
        self.assertEqual((lk[FAN]["kind"], lk[FAN]["strong"]), ("uplata_na_javni", False))   # a gift is weak
        self.assertEqual((lk[DSIDE]["disputed"], lk[DSIDE]["strong"]), (True, False))        # the denied wallet
        self.assertIn("osporen", kw.link_text(lk[DSIDE]))
        late, _w = kw.ties(tr[:1], pub, set(), {(SIDE, T[0]): [100 + 7 * 3600]}, self.c)     # sold 7 h later: no split
        self.assertEqual(late[PUB][SIDE]["kind"], "prijenos_tokena")
        # a funder we have not looked at could still be an exchange: the shared source is shown, not counted
        strong, weak = kw.ties(tr, pub, {EXCH}, {}, self.c, actors={SIDE, I1, RND, FAN, DSIDE, PUB, DISP}, checked=set())
        lk = {x["wallet"]: x for x in kw.find_links({SIDE, I1}, pub, strong, weak)}
        self.assertEqual((lk[I1]["kind"], lk[I1]["unchecked"], lk[I1]["strong"]), ("zajednicki_izvor", True, False))
        self.assertIn("nije provjeren", kw.link_text(lk[I1]))
        self.assertTrue(lk[SIDE]["strong"])                                  # what left the public wallet needs no check
        strong, weak = kw.ties(tr, pub, {EXCH}, {}, self.c, actors={SIDE, I1, PUB}, checked={F})
        self.assertTrue(kw.find_links({I1}, pub, strong, weak)[0]["strong"])   # the funder's own page is read
        pool, _w = kw.ties([dict(tr[0], dst=addr("Poo"))], pub, set(), {}, self.c, actors={SIDE, PUB})
        self.assertEqual(dict(pool), {})                                     # tokens "moved" to a pool tie nothing
        fan_in = [{"sig": f"x{i}", "ts": 1, "kind": "token", "src": addr(f"S{AB[i % 12]}{i // 12}"), "dst": EXCH,
                   "amount": 1.0, "mint": T[0], "first_in": 0} for i in range(25)]
        self.assertIn(EXCH, kw.hub_set(fan_in, set(), 20))                   # many senders into one address: a hub


class Pass(Base):
    def test_seed_unresolved_handle_and_bad_address(self):
        infs = {e["id"]: e for e in kw.load_seed(self.seed, self.con, self.p["kol_db"])}
        self.assertEqual(infs["gama"]["handles"], [])
        self.assertEqual(infs["beta"]["handles"], ["beta_x"])                # the @ is dropped
        self.assertEqual([w["address"] for w in infs["delta"]["wallets"]], [DISP])   # "nije adresa" is not invented
        self.assertFalse(infs["delta"]["public_buys"])
        real = kw.load_seed()                                                # the repository's own list
        self.assertEqual(len(real), 13)
        self.assertEqual([e["id"] for e in real if not e["handles"]], ["aurelius"])
        for e in real:
            for w in e["wallets"]:
                self.assertRegex(w["address"], r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
                self.assertTrue(w["source"].startswith("https://"), e["id"])
        self.assertEqual([w["status"] for e in real if e["id"] == "ansem" for w in e["wallets"]], ["osporeno"])

    def test_repeating_group_is_found_merged_and_confirmed(self):
        load_chain(self.con, self.ch, self.c)
        s = self.run_pass()
        self.assertEqual((s["influencers"], s["with_handle"], s["with_calls"], s["calls"]), (4, 3, 3, 19))
        self.assertEqual(s["helius"], 0)
        self.assertEqual(self.ch.calls, [])                                  # credits 0: no read at all
        g = self.group_of("alfa", I1)
        self.assertEqual(sorted(g["members"]), sorted([I1, I2]))             # the rotation is ONE group
        self.assertEqual((g["cls"], g["n_front"], g["n_sold"], g["n_sold60"], g["share_sold"]), ("potvrđen", 5, 5, 5, 1.0))
        self.assertEqual((g["lift"], g["exclusivity"], g["med_lead_min"]), (3.17, 1.0, 30.0))   # 5 of 6 on 19 events
        self.assertEqual((g["sol_in"], g["sol_out"]), (10.0, 15.0))
        ev = g["evidence"]
        self.assertEqual(ev["buckets"], {"<10 min": 0, "<24 h": 5, "<7 d": 0})
        self.assertEqual(len(ev["calls"]), 5)
        first = min(ev["calls"], key=lambda x: x["t0"])
        self.assertEqual((first["token"], first["t0"], first["url"]), (T[0], t0_of(1), "https://x.com/alfa_x/status/1"))
        w = first["wallets"][0]
        self.assertEqual((w["wallet"], w["last_buy"], w["first_sell"], w["bucket"]), (I1, t0_of(1) - 1800, t0_of(1) + 600,
                                                                                    "<24 h"))
        self.assertEqual([x["side"] for x in w["tx"]], ["buy", "sell"])      # the transactions a person can check
        rnd = self.group_of("alfa", RND)
        self.assertEqual((rnd["cls"], rnd["n_front"], rnd["n_sold"]), ("kandidat", 2, 0))
        self.assertLess(rnd["lift"], 2.0)
        self.assertIsNone(self.group_of("beta", RND) and None)               # four of beta's: a candidate there too
        self.assertEqual(self.group_of("beta", RND)["cls"], "kandidat")
        self.assertIn("insajderi kol: influencera s pozivima u podacima 3 od 4", self.logs[-1])
        self.assertIn("potvrđenih", self.logs[-1])

    def test_bots_snipers_and_buy_everything_are_out(self):
        load_chain(self.con, self.ch, self.c)
        s = self.run_pass()
        for w in (BUSY, SNIP):                                               # buys everything; buys at the launch
            self.assertIsNone(self.group_of("alfa", w), w)
        self.assertIsNone(self.group_of("beta", BUSY))
        self.assertGreaterEqual(s["excluded"], 3)
        self.assertIsNone(self.group_of("alfa", PUB))                        # the public wallet is not its own insider
        with mock.patch.object(kw.score, "bots", return_value={I2}):         # one wallet of the group is a bot
            self.run_pass()
        self.assertIsNone(self.group_of("alfa", I1))

    def test_split_link_confirms_and_a_link_alone_is_a_candidate(self):
        load_chain(self.con, self.ch, self.c)
        self.run_pass()
        side = self.group_of("alfa", SIDE)                                   # two calls + the split
        self.assertEqual(sorted(side["members"]), sorted([SIDE, SIDE1]))     # both got his tokens: one group
        self.assertEqual((side["cls"], side["n_front"], side["n_any"], side["link"]), ("potvrđen", 0, 2, 1))
        self.assertEqual({x["kind"] for x in side["links"]}, {"podjela_tokena"})
        self.assertEqual({x["wallet"] for x in side["links"]}, {SIDE, SIDE1})
        self.assertIn("malo prije prodaje", side["links"][0]["text"])
        self.assertTrue(side["links"][0]["sigs"][0].startswith("mv"))
        self.assertIn("izravna veza", side["why"])
        one = self.group_of("beta", BSIDE)                                   # one call: the link alone
        self.assertEqual((one["cls"], one["n_any"], one["link"]), ("kandidat", 1, 1))
        self.assertIsNone(self.group_of("alfa", FAN))                        # a gift into the public wallet: nothing
        self.assertIsNone(self.group_of("delta", DSIDE))                     # the denied wallet anchors nothing
        st = {d["id"]: d for d in kw.view(self.p["insajderi_db"])}
        self.assertEqual([st[i]["status_hr"] for i in ("alfa", "gama", "delta")],
                         ["pratimo", "handle nije potvrđen", "pratimo"])

    def test_funding_lookup_turns_a_candidate_into_confirmed_inside_the_budget(self):
        load_chain(self.con, self.ch, self.c)
        self.con.execute("UPDATE ik_calls SET fetched = 1")                  # (no rows yet: the pass inserts them)
        self.run_pass()
        self.assertEqual(self.group_of("alfa", K2)["cls"], "kandidat")       # two calls, no link known yet
        self.con.execute("UPDATE ik_calls SET fetched = 1")                  # every call window is already read
        self.con.commit()
        s = self.run_pass(credits=60, fetch=self.ch.fetch)
        self.assertLessEqual(s["helius"], 60)
        self.assertEqual(s["helius"], 60)                                    # six oldest pages, 10 each
        self.assertEqual(store.helius_spent(self.con, NOW), 60)              # counted in the tool's day cap
        k2 = self.group_of("alfa", K2)
        self.assertEqual((k2["cls"], k2["link"]), ("potvrđen", 1))
        self.assertEqual(k2["links"][0]["kind"], "prijenos_sol")
        self.assertIn("izravna veza", k2["why"])
        n = len(self.ch.calls)
        self.run_pass(credits=1000, fetch=self.ch.fetch)                     # read once: the same wallets cost nothing
        self.assertFalse(set(self.ch.calls[n:]) & set(self.ch.calls[:n]))

    def test_helius_reads_the_call_windows_within_its_share_and_time(self):
        s = self.run_pass(credits=90, fetch=self.ch.fetch)                   # nothing stored: Helius, capped
        self.assertLessEqual(s["helius"], 90)
        self.assertGreater(s["helius"], 0)
        self.assertEqual(store.helius_spent(self.con, NOW), s["helius"])
        c = cfg(helius_day=1000, kol_helius_share=0.05)                      # the day share: 50 credits
        self.assertEqual(kw.budget(self.con, self.p, c, NOW), max(0, 50 - s["helius"]))
        self.assertEqual(kw.budget(self.con, self.p, cfg(helius_day=s["helius"]), NOW), 0)   # the tool's cap is spent
        n = len(self.ch.calls)
        s2 = self.run_pass(credits=5000, fetch=self.ch.fetch, c=cfg(kol_max_s=0, helius_day=100_000))
        self.assertTrue(s2["truncated"])                                     # the time bound: nothing read, no raise
        self.assertEqual(len(self.ch.calls), n)
        self.assertIn("prekinuta na vremenskoj granici", self.logs[-1])

    def test_pass_never_raises_and_no_calls_cost_nothing(self):
        with mock.patch.object(kw, "analyze", side_effect=RuntimeError("pokvareno")):
            self.assertEqual(self.run_pass(), {})
        self.assertIn("prolaz nije uspio (RuntimeError", self.logs[-1])
        kc = sqlite3.connect(self.p["kol_db"])
        kc.execute("DELETE FROM calls")
        kc.commit()
        kc.close()
        s = self.run_pass(credits=5000, fetch=self.ch.fetch)
        self.assertEqual((s["with_calls"], s["listed"], s["helius"]), (0, 0, 0))
        self.assertEqual(self.ch.calls, [])                                  # not even the public wallets are read
        st = {d["id"]: d["status_hr"] for d in kw.view(self.p["insajderi_db"])}
        self.assertEqual(st, {"alfa": "nema poziva u podacima", "beta": "nema poziva u podacima",
                              "gama": "handle nije potvrđen", "delta": "nema poziva u podacima"})

    def test_x_read_is_optional_capped_and_says_nema_kredita(self):
        s = self.run_pass()                                                  # off by default: no request, no cost
        self.assertEqual(s["x"], {"state": "isključeno", "posts": 0, "usd": 0.0})
        self.assertIn("X dohvat: isključeno", self.logs[-1])
        infs = kw.load_seed(self.seed, self.con, self.p["kol_db"])
        seen = []

        def refused(q, cursor):
            seen.append(q)
            import urllib.error
            raise urllib.error.HTTPError("https://api.example.test", 402, "Payment Required", {}, None)
        c = cfg(kol_x_usd_day=0.05)
        with mock.patch("usage.meter.record") as rec:
            x = kw.fetch_posts(self.con, c, NOW, infs, get=refused, log=self.logs.append)
            self.assertEqual((x["state"], x["posts"], x["usd"]), ("nema kredita", 0, 0.0))
            self.assertEqual(len(seen), 1)                                   # the first refusal stops the round
            x = kw.fetch_posts(self.con, c, NOW + 60, infs, get=refused, log=self.logs.append)
            self.assertEqual((x["state"], len(seen)), ("nema kredita", 1))   # and pauses: no request at all
            rec.assert_not_called()                                          # a refusal costs nothing
            new = "7ppk9w8NHnH6ehajvJyU31VcMafwZ3ybRtJWumSyD2wd"   # a made-up address that decodes to 32 bytes, as a real mint does

            def ok(q, cursor):
                seen.append(q)
                h = q.split()[0][len("from:"):]
                return {"tweets": [{"id": f"9{len(seen)}", "author": {"userName": h}, "text": f"aping {new}",
                                    "createdAt": "Wed Nov 25 12:00:00 +0000 2026"}] if h == "alfa_x" else []}
            later = NOW + 7 * 3600
            x = kw.fetch_posts(self.con, c, later, infs, get=ok, log=self.logs.append)
            self.assertEqual((x["state"], x["posts"]), ("ok", 1))
            self.assertEqual(len(seen), 4)                                   # one request a handle (alfa, beta, delta)
            self.assertEqual(rec.call_count, 3)                              # metered
            self.assertEqual(rec.call_args[0][:2], ("twitterapi", "kol_insajderi"))
            n = len(seen)
            kw.fetch_posts(self.con, c, later + 600, infs, get=ok, log=self.logs.append)
            self.assertEqual(len(seen), n)                                   # each handle at most every 6 h
            x = kw.fetch_posts(self.con, cfg(kol_x_usd_day=0.0001), later + 7 * 3600, infs, get=ok)
            self.assertEqual((x["state"], len(seen)), ("strop", n))          # the day cap is spent: nothing asked
        ts = self.con.execute("SELECT ts FROM ik_posts WHERE token = ?", (new,)).fetchone()[0]
        calls = kw.find_calls(self.p, self.c, ts + 60, infs)                 # his post is a call like any other
        self.assertEqual((calls["alfa"][new]["t0"], calls["alfa"][new]["kind"]), (ts, "objava"))
        with mock.patch.object(kw, "fetch_posts", side_effect=RuntimeError("x")):
            s = self.run_pass()                                              # the optional read never costs the pass
        self.assertEqual(s["with_calls"], 3)
        self.assertIn("greška", s["x"]["state"])

    def test_runs_inside_the_insajderi_pass(self):
        with mock.patch.object(kw, "SEED", self.seed):
            run.run("incr", now=NOW, cfg={"helius_day": 100_000}, credits=0, log=self.logs.append, **self.p)
        self.assertTrue(any(x.startswith("insajderi kol: influencera s pozivima") for x in self.logs), self.logs)
        from insajderi import report
        with mock.patch.object(store, "db_path", return_value=self.p["insajderi_db"]):
            md = report.markdown(run.summary(self.p["insajderi_db"]))
            self.assertIn("## Insajderski novčanici influencera (vjerojatno povezani)", md)
            self.assertIn("| Gama | handle nije potvrđen |", md)
            self.assertIn("nije dokazana činjenica", md)
            self.assertTrue(report.kol_line().startswith("insajderi kol: "))

    def test_predpoziv_is_recorded_and_settled_only_while_the_flag_is_on(self):
        load_chain(self.con, self.ch, self.c)
        self.run_pass()
        new, t_buy = addr("Newtoken"), NOW - 2 * 3600
        self.con.execute("INSERT INTO i2_trades VALUES (?,?,?,?,?,?,?,?,?,?)", (new, I2, "nb1", t_buy, 1, "buy", 2.0, 1e6,
                                                                               None, None))
        self.con.execute("INSERT INTO i2_trades VALUES (?,?,?,?,?,?,?,?,?,?)", (T[0], I1, "old", NOW - 3600, 1, "buy", 1.0,
                                                                               1e6, None, None))
        self.con.commit()
        infs = kw.load_seed(self.seed, self.con, self.p["kol_db"])
        with mock.patch.object(kw, "mode", return_value="off"):
            self.assertIsNone(kw.predpoziv(self.con, self.p, self.c, NOW, infs))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM ik_predpoziv").fetchone()[0], 0)
        with mock.patch.object(kw, "mode", return_value="shadow"):
            st = kw.predpoziv(self.con, self.p, self.c, NOW, infs)
            self.assertEqual((st["n"], st["settled"]), (1, 0))               # T1 was already called: not an event
            row = self.con.execute("SELECT inf, token, wallet, buy_ts, called FROM ik_predpoziv").fetchone()
            self.assertEqual(row, ("alfa", new, I2, t_buy, None))
            kc = sqlite3.connect(self.p["kol_db"])                           # 40 min later he posts it
            kc.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, mcap0, symbol, r1h, r24h) VALUES "
                       "('twn', ?, 'alfa_x', ?, 'call', 150000, 'NEW', 0.35, -0.5)", (new, t_buy + 2400))
            kc.commit()
            kc.close()
            self.con.execute("INSERT INTO i2_trades VALUES (?,?,?,?,?,?,?,?,?,?)", (new, I2, "ns1", t_buy + 3000, 1, "sell",
                                                                                   3.0, 1e6, None, None))
            self.con.commit()
            st = kw.predpoziv(self.con, self.p, self.c, NOW + 3600, infs)
        self.assertEqual((st["n"], st["called"], st["hit_pct"], st["med_lead_min"], st["sold_after"], st["r1h_med_pct"]),
                         (1, 1, 100.0, 40.0, 1, 35.0))
        row = self.con.execute("SELECT called, call_ts, sold_ts, symbol FROM ik_predpoziv").fetchone()
        self.assertEqual(row, (1, t_buy + 2400, t_buy + 3000, "NEW"))
        from trade import settings
        self.assertEqual(settings.FLAG_DEFAULTS[kw.FLAG], "shadow")          # measures from the deploy, never trades
        self.assertIn(kw.FLAG, settings.NEVER_LIVE)
        self.assertIn(kw.FLAG, settings.PROFILE_FLAGS)                       # paper never makes the demo follow anybody


class ViewsBase(Base):
    """A pass over the synthetic chain (with the funding lookups) and the owner's page of it."""

    def setUp(self):
        super().setUp()
        load_chain(self.con, self.ch, self.c)
        self.run_pass()
        self.con.execute("UPDATE ik_calls SET fetched = 1")
        self.con.commit()
        self.run_pass(credits=100, fetch=self.ch.fetch)                      # the funding link of K2
        env = mock.patch.dict(os.environ, {"INSAJDERI_DB": self.p["insajderi_db"]})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("TRADE_OWNER", None)                                  # the owner is the default, Jure

    def page(self, user="Jure"):
        from ui import kolinsajderi
        return kolinsajderi.page({}, user, now=NOW)


class Views(ViewsBase):
    """The owner's page, the item on Influenceri, the route, the MCP tools."""

    def test_owner_page_content_and_wording(self):
        title, html = self.page()
        self.assertEqual(title, "Insajderski novčanici")
        for txt in ("Vjerojatno povezani novčanici influencera", "VJEROJATNO povezani", "nije dokazana činjenica",
                    "Alfa", "@alfa_x", "pratimo", "Gama", "handle nije potvrđen", "potvrđen", "kandidat",
                    "malo prije prodaje", "prijenos SOL-a s javnog novčanika", "češće nego što bi se očekivalo",
                    "osporeno (osoba kaže da nije njezin)", "https://x.com/alfa_x/status/1",
                    f"https://solscan.io/account/{I1}", "https://solscan.io/tx/", "Stranica nije javna"):
            self.assertIn(txt, html, txt)
        text = html.split("</style>", 1)[1]
        for bad in ("lift", "front-run", "Helius", "i2_", "ik_", "owner", "insajderi.db", "wallet group", "None",
                    "javna_oznaka", "bez_handlea", "podjela_tokena"):          # no English, no internal names
            self.assertNotIn(bad, text, bad)
        self.assertNotIn(I1, text.replace(f"account/{I1}", "").replace(f'title="{I1}"', ""))   # addresses are shortened
        for accusation in ("prevar", "scam", "prijevar", "manipul", "kriv"):  # an inference, never an accusation
            self.assertNotIn(accusation, text.lower(), accusation)

    def test_only_the_owner_gets_data(self):
        for user in (None, "Ivan", "gost"):
            _t, html = self.page(user)
            self.assertIn("vidi samo vlasnik", html)
            for secret in ("Alfa", I1[:4] + "…", "solscan"):
                self.assertNotIn(secret, html, (user, secret))

    def test_influenceri_page_row_is_stripped_for_non_admins_and_nothing_is_public(self):
        from ui import admstrip, kol
        self.assertIn('href="/kol-insajderi"', kol.INSIDER_ROW)
        self.assertIn("Insajderski novčanici", kol.INSIDER_ROW)
        self.assertNotIn("kol-insajderi", admstrip.strip("<main>" + kol.INSIDER_ROW + "</main>"))
        from league import roles
        self.assertEqual(roles.deny_get("/kol-insajderi", "osnovni"), "admin")
        self.assertEqual(roles.deny_get("/kol-insajderi", "prijatelj"), "admin")
        from ui import public
        self.assertIsNone(public.route("/kol-insajderi"))                    # not a public page
        for name in ("ui/public.py", "ui/coinseo.py", "ui/landing.py", "share/novosti.json", "ui/html.py"):
            path = os.path.join(ROOT, name)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    self.assertNotIn("kol-insajderi", f.read(), name)        # no sitemap, menu, landing or share entry

    def test_http_route_is_the_owners_only(self):
        import importlib
        import threading
        import urllib.error
        import urllib.parse
        import urllib.request
        from league import profiles, roles, store as lstore
        d = self.tmp.name
        keys = ("UI_PASSWORD", "UI_PASS_IVAN", "UI_PASS_JURE", "UI_USERS", "UI_ADMINS", "UI_TEST_PASSWORD", "DATA_DIR")
        old, old_db = {k: os.environ.get(k) for k in keys}, lstore.DB

        def restore():
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
            lstore.DB = old_db
            roles.reset_cache()
        self.addCleanup(restore)
        lstore.DB = os.path.join(d, "league.db")
        os.environ.update(DATA_DIR=d, UI_USERS="Ivan,Jure,Ana", UI_PASS_IVAN="ivanpw", UI_PASS_JURE="jurepw",
                          UI_PASS_ANA="anapw", UI_PASSWORD="shared", UI_ADMINS="Ivan,Jure")
        self.addCleanup(os.environ.pop, "UI_PASS_ANA", None)
        profiles.reset_cache()
        roles.reset_cache()
        import run_ui
        importlib.reload(run_ui)
        srv = run_ui.ThreadingHTTPServer(("127.0.0.1", 0), run_ui.Handler)
        srv.verbose = False
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        base = f"http://127.0.0.1:{srv.server_address[1]}"

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a):
                return None
        op = urllib.request.build_opener(NoRedirect)

        def call(path, data=None, cookie=""):
            headers = {"Cookie": cookie} if cookie else {}
            if data is not None:
                headers["Origin"] = base
            req = urllib.request.Request(base + path, data=urllib.parse.urlencode(data).encode() if data else None,
                                         headers=headers)
            try:
                r = op.open(req)
            except urllib.error.HTTPError as e:
                r = e
            with r:
                return r.code, r.read().decode("utf-8", "replace")

        def login(name, pw):
            req = urllib.request.Request(base + "/prijava", headers={"Origin": base}, data=urllib.parse.urlencode(
                {"name": name, "pw": pw, "next": "/kol"}).encode())
            try:
                r = op.open(req)
            except urllib.error.HTTPError as e:
                r = e
            with r:
                self.assertEqual(r.code, 303, name)
                return r.headers["Set-Cookie"].split(";")[0]
        jure, ivan, ana = login("Jure", "jurepw"), login("Ivan", "ivanpw"), login("Ana", "anapw")
        self.assertEqual(call("/kol-insajderi")[0], 401)                     # no login: the login form, no data
        for cookie, who in ((ana, "osnovni"), (ivan, "admin, not the owner")):
            code, body = call("/kol-insajderi", cookie=cookie)
            self.assertEqual(code, 403, who)
            self.assertNotIn("Alfa", body, who)
            self.assertNotIn("solscan", body, who)
        code, body = call("/kol-insajderi", cookie=jure)
        self.assertEqual(code, 200)
        for txt in ("Insajderski novčanici", "Alfa", "VJEROJATNO povezani", "potvrđen"):
            self.assertIn(txt, body, txt)

    def test_mcp_read_and_submit(self):
        from ui import mcpapi
        tools = {t["name"]: t for t in mcpapi.TOOLS}
        self.assertTrue(tools["get_kol_insider_wallets"]["annotations"]["readOnlyHint"])
        self.assertFalse(tools["submit_kol_wallet"]["annotations"]["readOnlyHint"])
        self.assertFalse(tools["submit_kol_wallet"]["annotations"]["destructiveHint"])
        d, err = mcpapi._tool("get_kol_insider_wallets", {})
        self.assertFalse(err)
        self.assertNotIn("evidence", d["influencers"][0]["wallets"][0])      # the whole list: the numbers only
        d, err = mcpapi._tool("get_kol_insider_wallets", {"evidence": True})
        self.assertTrue(d["available"])
        self.assertIn("VJEROJATNO", d["caveat"])
        self.assertEqual([x["id"] for x in d["influencers"]], ["alfa", "beta", "gama", "delta"])
        alfa = d["influencers"][0]
        self.assertEqual((alfa["status"], alfa["handles"], alfa["public"][0]["address"]), ("pratimo", ["alfa_x"], PUB))
        top = alfa["wallets"][0]
        self.assertEqual(top["cls"], "potvrđen")
        self.assertIn("calls", top["evidence"])
        self.assertEqual(d["influencers"][2]["status_hr"], "handle nije potvrđen")
        one, _ = mcpapi._tool("get_kol_insider_wallets", {"influencer": "@ALFA_X", "limit": 1})
        self.assertEqual([x["id"] for x in one["influencers"]], ["alfa"])
        self.assertEqual(len(one["influencers"][0]["wallets"]), 1)
        self.assertIn("calls", one["influencers"][0]["wallets"][0]["evidence"])   # one influencer: with the evidence
        one, _ = mcpapi._tool("get_kol_insider_wallets", {"influencer": "alfa", "evidence": False})
        self.assertNotIn("evidence", one["influencers"][0]["wallets"][0])
        for bad in ({"influencer": "gama", "handle": "nije valjan handle!", "source": "https://x.com/x"},
                    {"influencer": "gama", "address": "kratko", "source": "https://x.com/x"},
                    {"influencer": "gama", "handle": "gama_x"},                    # no source: never a guess
                    {"handle": "gama_x", "source": "https://x.com/gama_x"}):
            d, err = mcpapi._tool("submit_kol_wallet", bad)
            self.assertTrue(err, bad)
        d, err = mcpapi._tool("submit_kol_wallet", {"influencer": "gama", "handle": "@gama_x", "address": addr("Gamapub"),
                                                    "source": "https://x.com/gama_x"})
        self.assertFalse(err, d)
        self.assertEqual(d["status"], "nepotvrđeno")
        infs = {e["id"]: e for e in kw.load_seed(self.seed, self.con, self.p["kol_db"])}
        self.assertEqual(infs["gama"]["handles"], [])                        # a proposal is shown, never used
        self.assertEqual(infs["gama"]["wallets"], [])
        self.assertEqual(infs["gama"]["proposals"][0]["handle"], "gama_x")
        self.assertEqual(kw.proposals(self.p["insajderi_db"])[0]["status"], "nepotvrđeno")
        self.assertIn("Prijedlozi koji čekaju tvoju potvrdu", self.page()[1])
        with mock.patch.object(kw.time, "time", return_value=NOW):
            for _ in range(30):
                kw.submit({"influencer": "gama", "handle": "gama_x", "source": "https://x.com/gama_x"}, who="t")
            self.assertIn("30", kw.submit({"influencer": "gama", "handle": "gama_x", "source": "https://x.com/g"},
                                          who="t")["error"])


def _have_playwright():
    if not shutil.which("node"):
        return False
    try:
        r = subprocess.run(["node", "-e", "const {chromium}=require('playwright');"
                            "process.exit(require('fs').existsSync(chromium.executablePath())?0:1)"],
                           capture_output=True, timeout=60)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@unittest.skipUnless(_have_playwright(), "node + playwright + chromium")
class Browser(ViewsBase):
    """The real page in a browser at 390 px: nothing wider than the screen, closed and with every row opened.
    Screenshots go to KOLW_SHOTS (default: a temporary folder)."""

    def test_no_horizontal_overflow_at_390_px(self):
        import http.server
        import socketserver
        import threading
        from ui.html import page as layout
        html = layout(*self.page(), "/kol-insajderi").encode("utf-8")

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                ok = self.path.split("?")[0] == "/kol-insajderi"
                self.send_response(200 if ok else 404)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html) if ok else 0))
                self.end_headers()
                if ok:
                    self.wfile.write(html)
        srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H)
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        out = os.environ.get("KOLW_SHOTS") or self.tmp.name
        os.makedirs(out, exist_ok=True)
        js = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kolwallets_playwright.js")
        r = subprocess.run(["node", js, f"http://127.0.0.1:{srv.server_address[1]}/kol-insajderi", out],
                           capture_output=True, text=True, timeout=240)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:] + r.stdout[-2000:])
        rep = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(rep["errors"], [])
        for state in ("closed", "open"):
            m = rep[state]
            self.assertEqual(m["vw"], 390, state)
            self.assertLessEqual(m["scroll"], 390, (state, m))               # no sideways scroll
            self.assertEqual(m["wide"], [], (state, m))                      # no element past either edge
        self.assertGreaterEqual(rep["open"]["rows"], 8)                      # 4 influencers + their groups
        self.assertGreater(rep["open"]["text"], rep["closed"]["text"])


if __name__ == "__main__":
    unittest.main()
