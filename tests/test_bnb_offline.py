"""bnb/ (BNB Smart Chain: pumps, who bought before and sold into them, the class, the measurement), offline: recorded
real responses (tests/fixtures/bnb/, 19.11.) and a fake JSON-RPC."""
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bnb import chain, izvor, klasa, pogled, prati, pumpe, run, store, swaps  # noqa: E402
from bnb import rpc as brpc  # noqa: E402
from bnb.keccak import topic  # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures", "bnb")
USDT = "0x55d398326f99059ff775485246999027b3197955"
H = 3600


def fx(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


def w32(v):
    return format(v % (1 << 256), "064x")


def t32(a):
    return "0x" + "0" * 24 + a[2:]


def hx(n):
    return hex(n)


class Db(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "bnb.db")
        self.env = mock.patch.dict(os.environ, {"BNB_DB": self.path, "BNB_OUT_DIR": self.tmp.name})
        self.env.start()
        self.con = store.connect(self.path)
        self.c = store.config({})

    def tearDown(self):
        self.con.close()
        self.env.stop()
        self.tmp.cleanup()


# ---------- keccak, decoding, attribution ----------------------------------------------------------------------------

class Topics(unittest.TestCase):
    def test_known_topics(self):
        self.assertEqual(swaps.TRANSFER, "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef")
        self.assertEqual(swaps.V2, "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822")
        self.assertEqual(swaps.V3, "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67")
        self.assertEqual(topic("Swap(bytes32,address,int128,int128,uint160,uint128,int24,uint24)"),
                         "0x40e9cecb9f5f1f1c5b9c97dec2917b7ee92e57ba5563708daca94dd84ad7112f")   # Uniswap v4
        self.assertEqual(swaps.SEL_DECIMALS, "0x313ce567")


class Decode(unittest.TestCase):
    TOK = "0x9000000000000000000000000000000000000001"   # > USDT: token1

    def v2(self, a0i, a1i, a0o, a1o, li=1, tx="0xaa", to="0x" + "11" * 20):
        return {"address": "0xpool", "topics": [swaps.V2, t32("0x" + "22" * 20), t32(to)],
                "data": "0x" + w32(a0i) + w32(a1i) + w32(a0o) + w32(a1o), "blockNumber": hx(100),
                "blockTimestamp": hx(1_700_000_000), "transactionHash": tx, "logIndex": hx(li)}

    def test_v2_buy_and_sell_with_decimals(self):
        # token1 (9 decimals) out, USDT (token0, 18) in: a buy of 5 tokens for 2 USDT
        d = swaps.decode(self.v2(2 * 10 ** 18, 0, 0, 5 * 10 ** 9), self.TOK, USDT, tdec=9)
        self.assertEqual((d["side"], d["amt"], d["qamt"], d["kind"]), ("buy", 5.0, 2.0, "v2"))
        self.assertEqual(d["ts"], 1_700_000_000)
        d = swaps.decode(self.v2(0, 3 * 10 ** 9, 1 * 10 ** 18, 0), self.TOK, USDT, tdec=9)
        self.assertEqual((d["side"], d["amt"], d["qamt"]), ("sell", 3.0, 1.0))

    def test_v3_signs_pool_side(self):
        lg = {"address": "0xp", "topics": [swaps.V3_PCS, t32("0x" + "22" * 20), t32("0x" + "33" * 20)],
              "data": "0x" + w32(50 * 10 ** 18) + w32(-(17 * 10 ** 18)) + "0" * 64 * 5, "blockNumber": hx(1),
              "transactionHash": "0xbb", "logIndex": hx(0)}
        d = swaps.decode(lg, self.TOK, USDT)   # USDT into the pool, token out: a buy
        self.assertEqual((d["side"], d["amt"], d["qamt"], d["recip"]), ("buy", 17.0, 50.0, "0x" + "33" * 20))

    def test_infinity_signs_swapper_side(self):
        tok = "0x0e63b9c287e32a05e6b9ab8ee8df88a2760225a9"   # PIEVERSE < USDT: currency0
        lg = fx("swaps_live.json")["IRYS-inf"]["swap"][0]
        d = swaps.decode(lg, "0x91152b4ef635403efbae860edd0f8c321d7c035d", USDT)
        self.assertIn(d["side"], ("buy", "sell"))
        self.assertIsNone(d["recip"])
        lg2 = dict(lg, data="0x" + w32(48 * 10 ** 18) + w32(-(140 * 10 ** 18)) + "0" * 64 * 5)
        d2 = swaps.decode(lg2, tok, USDT)   # the live PIEVERSE swap's signs: +token to the swapper, -USDT
        self.assertEqual((d2["side"], d2["amt"], d2["qamt"]), ("buy", 48.0, 140.0))

    def test_recorded_v2_v3_pools_decode(self):
        f = fx("swaps_live.json")
        cases = {"EVAA": ("0xaa036928c9c0df07d525b55ea8ee690bb5a628c1", USDT),
                 "JAGENT": ("0x8e6442663a4f8c50b6132c68d42a30e7dfe4ae15", USDT),
                 "BANANA": ("0x3d4f0513e8a29669b960f9dbca61861548a9a760", swaps.WBNB),
                 "TART": ("0x7ab8d02cbb51ff7223fde700eaaa2a91bf750314", swaps.WBNB)}
        for name, (tok, q) in cases.items():
            pool = f[name]["swap"][0]["address"].lower()
            tr = swaps.parse(f[name]["swap"], f[name]["transfer"], tok, q, {pool})
            self.assertEqual(len(tr), len(f[name]["swap"]), name)
            trs = swaps.transfers_by_tx(f[name]["transfer"])
            for t in tr:
                self.assertGreater(t["amt"], 0)
                self.assertEqual(t["how"], "transfer", name)
                # direction agrees with the token's own transfers: a buy = the pool sent the token in that tx
                moved = trs[t["tx"]]
                if t["side"] == "buy":
                    self.assertTrue(any(fr == pool for _li, fr, _to, _v in moved), name)
                else:
                    self.assertTrue(any(to == pool for _li, _fr, to, _v in moved), name)
                self.assertNotEqual(t["trader"], pool)


class Attribution(unittest.TestCase):
    POOL, ROUTER, USER = "0x" + "aa" * 20, "0x" + "bb" * 20, "0x" + "cc" * 20

    def tr(self, li, fr, to, v, tx="0x01"):
        return {"topics": [swaps.TRANSFER, t32(fr), t32(to)], "data": "0x" + w32(v), "transactionHash": tx,
                "logIndex": hx(li)}

    def test_buy_followed_through_router(self):
        trs = swaps.transfers_by_tx([self.tr(1, self.POOL, self.ROUTER, 1000), self.tr(2, self.ROUTER, self.USER, 990)])
        sw = {"side": "buy", "li": 3, "recip": self.ROUTER, "sender": self.ROUTER}
        self.assertEqual(swaps.attribute(sw, trs["0x01"], {self.POOL}), (self.USER, "transfer"))

    def test_sell_followed_back_and_fallbacks(self):
        trs = swaps.transfers_by_tx([self.tr(1, self.USER, self.ROUTER, 500), self.tr(2, self.ROUTER, self.POOL, 500)])
        sw = {"side": "sell", "li": 3, "recip": self.ROUTER, "sender": self.ROUTER}
        self.assertEqual(swaps.attribute(sw, trs["0x01"], {self.POOL}), (self.USER, "transfer"))
        self.assertEqual(swaps.attribute(sw, [], {self.POOL}), (self.ROUTER, "recipient"))
        self.assertEqual(swaps.attribute(dict(sw, recip=None), None, {self.POOL}), (self.ROUTER, "sender"))

    def test_tax_split_keeps_the_main_hop(self):
        tax = "0x" + "dd" * 20
        trs = swaps.transfers_by_tx([self.tr(1, self.POOL, self.ROUTER, 1000), self.tr(2, self.ROUTER, tax, 50),
                                     self.tr(3, self.ROUTER, self.USER, 950)])
        sw = {"side": "buy", "li": 4, "recip": self.ROUTER, "sender": self.ROUTER}
        self.assertEqual(swaps.attribute(sw, trs["0x01"], {self.POOL})[0], self.USER)

    def test_dedup_by_tx_and_log_index(self):
        f = fx("swaps_live.json")["TART"]
        tok = "0x7ab8d02cbb51ff7223fde700eaaa2a91bf750314"
        pool = f["swap"][0]["address"].lower()
        once = swaps.parse(f["swap"], f["transfer"], tok, swaps.WBNB, {pool})
        twice = swaps.parse(f["swap"] + f["swap"], f["transfer"], tok, swaps.WBNB, {pool})
        self.assertEqual(len(once), len(twice))


# ---------- sources --------------------------------------------------------------------------------------------------

class Sources(unittest.TestCase):
    def test_gt_rows_and_curve_out(self):
        rows = [izvor.pool_row(x) for x in fx("gt_trending.json")["data"]]
        rows = [r for r in rows if r]
        self.assertTrue(rows)
        for r in rows:
            self.assertIn(r["quote"], swaps.QUOTES)
            self.assertNotIn(r["token"], swaps.QUOTES)
        self.assertIsNone(izvor.ds_pair_row({"chainId": "bsc", "dexId": "fourmeme", "baseToken": {"address": "0x1"},
                                             "quoteToken": {"address": swaps.WBNB}}))
        for p in fx("ds_search.json")["pairs"]:
            r = izvor.ds_pair_row(p)
            if r:
                self.assertNotIn("four", r["dex"])

    def test_meme_filter(self):
        self.assertFalse(pumpe.meme("USDT")[0])
        self.assertFalse(pumpe.meme("slisBNB")[0])
        self.assertFalse(pumpe.meme("XRP", "Binance-Peg XRP Token")[0])
        self.assertFalse(pumpe.meme("FOO", "Binance-Peg Foo")[0])
        self.assertTrue(pumpe.meme("JAGENT", "Jagent")[0])

    def test_kind_of(self):
        self.assertEqual(swaps.kind_of("pancakeswap_v2", "0x" + "1" * 40), "v2")
        self.assertEqual(swaps.kind_of("pancakeswap-v3-bsc", "0x" + "1" * 40), "v3")
        self.assertEqual(swaps.kind_of("pancakeswap-infinity-clmm", "0x" + "1" * 64), "inf")
        self.assertIsNone(swaps.kind_of("four-meme", "0x" + "1" * 40))


# ---------- events -----------------------------------------------------------------------------------------------------

class Events(Db):
    TOK = "0x" + "77" * 20

    def put(self, res, rows):
        pumpe.save_candles(self.con, self.TOK, res, rows)

    def test_1h_and_1d_rules_tiers_and_dedup(self):
        now = 1_800_000_000 - 1_800_000_000 % 86400
        hours = [(now - 40 * H + i * H, 1, 1, 1, 1.0, 0) for i in range(30)]
        hours += [(now - 10 * H, 1, 1, 1, 1.2, 0), (now - 9 * H, 1, 1, 1, 1.6, 0), (now - 8 * H, 1, 1, 1, 1.7, 0),
                  (now - 2 * H, 1, 1, 1, 1.0, 0)]
        self.put("1h", hours)
        days = [(now - (60 - i) * 86400, 1, 1, 1, 1.0, 0) for i in range(50)]
        days += [(now - 10 * 86400, 1, 1, 1, 1.6, 0), (now - 9 * 86400, 1, 1, 1, 1.0, 0),
                 (now - 2 * 86400, 1, 1, 1, 1.0, 0), (now - 86400, 1, 1, 1, 1.7, 0),
                 (now, 1, 1, 1, 1.0, 0)]   # the second daily pump holds the 1h pump's t0: dropped
        self.put("1d", days)
        # today's MC 10 M at the last close 1.0: the 1h peak 1.7 -> 17 M ("pumpa15"), the daily 1.6 -> 16 M
        evs = pumpe.token_events(self.con, self.c, self.TOK, "X", "0xpool", 10e6, now)
        kinds = sorted((e["src"], e["tier"]) for e in evs)
        self.assertIn(("c1h 6h", "pumpa15"), kinds)
        self.assertIn(("c1d 1d", "pumpa15"), kinds)
        self.assertEqual(sum(1 for e in evs if e["src"].startswith("c1d")), 1)
        e = next(e for e in evs if e["src"] == "c1h 6h")
        self.assertEqual(e["win_end"], e["peak_ts"] + 3600)
        self.assertAlmostEqual(e["peak_mc"], 17e6)
        # a 3 M token: the same jump is "pumpa2"; a 1 M one has no tier
        self.assertEqual({e["tier"] for e in pumpe.token_events(self.con, self.c, self.TOK, "X", "p", 1.5e6, now)},
                         {"pumpa2"})

    def test_hour_gate(self):
        now = 1_800_000_000
        quiet = [(now - i * 86400, 1, 1.1, 0.95, 1, 0) for i in range(60, 0, -1)]
        self.assertFalse(pumpe.hour_gate(quiet, self.c, now))
        jump = quiet[:-3] + [(now - 2 * 86400, 1, 1.6, 0.98, 1.5, 0)] + quiet[-2:]
        self.assertTrue(pumpe.hour_gate(jump, self.c, now))


# ---------- the chain read (fake RPC) ----------------------------------------------------------------------------------

class FakeChain:
    """A JSON-RPC endpoint over in-memory logs: eth_getLogs (address + topic0 / topic1 filter, block range, max 1000
    blocks a call), eth_blockNumber, eth_getBlockByNumber (0.45 s blocks), eth_call (decimals 18), eth_getCode."""

    def __init__(self, logs, head=10_000, head_ts=1_800_000_000, max_range=1000, fail=(), code=None):
        self.logs, self.head, self.head_ts, self.max_range = logs, head, head_ts, max_range
        self.fail, self.code, self.n = set(fail), code or {}, 0

    def ts(self, b):
        return int(self.head_ts - (self.head - b) * 0.45)

    def answer(self, m, p):
        if m == "eth_blockNumber":
            return {"result": hx(self.head)}
        if m == "eth_getBlockByNumber":
            return {"result": {"timestamp": hx(self.ts(int(p[0], 16)))}}
        if m == "eth_call":
            return {"result": "0x" + w32(18)}
        if m == "eth_getCode":
            return {"result": self.code.get(p[0], "0x")}
        if m == "eth_getLogs":
            f = p[0]
            a, b = int(f["fromBlock"], 16), int(f["toBlock"], 16)
            if b - a + 1 > self.max_range:
                return {"error": {"code": -32701, "message": f"exceed maximum block range: {self.max_range}"}}
            if a in self.fail:
                return {"error": {"code": -32000, "message": "upstream error"}}
            t0 = f["topics"][0]
            t0 = t0 if isinstance(t0, list) else [t0]
            out = [lg for lg in self.logs if lg["address"] == f.get("address") and lg["topics"][0] in t0
                   and a <= int(lg["blockNumber"], 16) <= b
                   and (len(f["topics"]) < 2 or f["topics"][1] is None or lg["topics"][1] == f["topics"][1])]
            return {"result": out}
        return {"result": None}

    def post(self, url, body):
        self.n += 1
        if isinstance(body, list):
            return [dict(self.answer(x["method"], x["params"]), id=x["id"]) for x in body]
        return dict(self.answer(body["method"], body["params"]), id=1)


def swap_log(pool, block, li, buy, usd, tok_amt, trader, chain_):
    """A v2 swap of TOK (token1) vs USDT (token0) and its Transfer (pool <-> trader)."""
    tx = "0x" + format(block * 1000 + li, "064x")
    a0i, a1i, a0o, a1o = (usd * 10 ** 18, 0, 0, tok_amt * 10 ** 18) if buy else (0, tok_amt * 10 ** 18, usd * 10 ** 18, 0)
    ts = hx(chain_.ts(block))
    sw = {"address": pool, "topics": [swaps.V2, t32(Chain.ROUTER), t32(trader if buy else Chain.ROUTER)],
          "data": "0x" + w32(a0i) + w32(a1i) + w32(a0o) + w32(a1o), "blockNumber": hx(block), "blockTimestamp": ts,
          "transactionHash": tx, "logIndex": hx(li + 1)}
    fr, to = (pool, trader) if buy else (trader, pool)
    tr = {"address": Chain.TOK, "topics": [swaps.TRANSFER, t32(fr), t32(to)], "data": "0x" + w32(tok_amt * 10 ** 18),
          "blockNumber": hx(block), "blockTimestamp": ts, "transactionHash": tx, "logIndex": hx(li)}
    return [sw, tr]


class Chain(Db):
    TOK = "0x9" + "0" * 39
    POOL = "0x" + "ab" * 20
    ROUTER = "0x10ed43c718714eb63d5aa57b78b54704e256024e"
    W = "0x" + "c1" * 20

    def setUp(self):
        super().setUp()
        self.c = store.config({"max_range": 1000, "archive_s": 86400 * 3, "pump_pre_h": 1})
        self.fc = FakeChain([], head=20_000)
        self.now = self.fc.head_ts
        self.con.execute("INSERT INTO bnb_tokens (chain, token, symbol, pool, dex, quote, meme, pool_created) VALUES "
                         "('bsc', ?, 'TOK', ?, 'pancakeswap_v2', ?, 1, 0)", (self.TOK, self.POOL, USDT))
        self.con.executemany("INSERT INTO bnb_px VALUES (?,?,?)", [("sol", self.now - 86400 * 5, 100.0)])

    def rpc(self):
        return brpc.Rpc(["https://fake"], post=self.fc.post, sleep=lambda s: None)

    def event(self, t0, end, tier="pumpa15", eid=None, src="c1h 6h"):
        return {"eid": eid or f"j:{self.TOK}:{t0}", "kind": "jump", "token": self.TOK, "symbol": "TOK", "pool": self.POOL,
                "t0": t0, "win_end": end, "peak_ts": end - 3600, "src": src, "tier": tier, "fetched": 0, "peak_x": 1.0,
                "peak_mc": 20e6, "mcap0": 1e7, "prio": 1}

    def test_fetch_coverage_attribution_dedup_and_resume(self):
        t0 = self.fc.ts(18_000)
        logs = []
        logs += swap_log(self.POOL, 17_500, 1, True, 20, 1000, self.W, self.fc)    # before: 20 $ = 0.2 SOL
        logs += swap_log(self.POOL, 18_500, 5, False, 60, 1000, self.W, self.fc)   # into the jump
        self.fc.logs = logs
        e = self.event(t0, self.fc.ts(19_500))
        pumpe.save_events(self.con, [e], self.now)
        rpc = self.rpc()
        blocks = chain.Blocks(rpc, 0.45)
        r = chain.fetch_event(self.con, self.c, e, rpc, blocks, chain.Px(self.con), self.now)
        self.assertTrue(r["complete"])
        self.assertEqual(r["swaps"], 2)
        rows = store.q(self.con, "SELECT trader, side, usd, round(sol_eq, 3), how FROM bnb_trades ORDER BY ts")
        self.assertEqual(rows, [(self.W, "buy", 20.0, 0.2, None), (self.W, "sell", 60.0, 0.6, None)])
        cov = store.q(self.con, "SELECT depth, pre_cov, jump_cov FROM bnb_cover")[0]
        self.assertEqual(cov[0], store.FETCH_DEPTH)
        self.assertGreater(cov[1], 0.99)
        self.assertGreater(cov[2], 0.99)
        # resume: every slice is stored, a second read makes no getLogs call and adds no row
        n = self.fc.n
        r2 = chain.fetch_event(self.con, self.c, e, rpc, blocks, chain.Px(self.con), self.now)
        self.assertTrue(r2["complete"])
        self.assertEqual(self.fc.n - n, 0)
        self.assertEqual(store.q(self.con, "SELECT COUNT(*) FROM bnb_trades")[0][0], 2)

    def test_a_failed_slice_leaves_the_event_due(self):
        t0 = self.fc.ts(18_000)
        e = self.event(t0, self.fc.ts(19_500))
        pumpe.save_events(self.con, [e], self.now)
        rpc = self.rpc()
        rpc.retries = 0
        blocks = chain.Blocks(rpc, 0.45)
        first = blocks.at(t0)
        self.fc.fail = {first}
        r = chain.fetch_event(self.con, self.c, e, rpc, blocks, chain.Px(self.con), self.now, log=lambda *_: None)
        self.assertFalse(r["complete"])
        self.assertEqual(store.q(self.con, "SELECT COUNT(*) FROM bnb_cover")[0][0], 0)
        self.assertEqual(len(chain.due(self.con, pumpe.load(self.con), self.now, self.c)), 1)

    def test_an_empty_read_is_never_counted(self):
        t0 = self.fc.ts(18_000)
        e = self.event(t0, self.fc.ts(19_500))
        pumpe.save_events(self.con, [e], self.now)
        rpc = self.rpc()
        r = chain.fetch_event(self.con, self.c, e, rpc, chain.Blocks(rpc, 0.45), chain.Px(self.con), self.now,
                              log=lambda *_: None)
        self.assertEqual((r["complete"], r["reach"]), (False, "prazno"))
        self.assertEqual(chain.due(self.con, pumpe.load(self.con), self.now, self.c), [])
        self.assertEqual(klasa.funnel(self.con, self.c, pumpe.load(self.con), [], {}, self.now)["prazno"], 1)

    def test_out_of_reach(self):
        old = self.now - 10 * 86400
        e = self.event(old, old + 7200)
        pumpe.save_events(self.con, [e], self.now)
        self.assertEqual(chain.due(self.con, pumpe.load(self.con), self.now, self.c), [])
        self.assertEqual(pumpe.load(self.con)[0]["reach"], "izvan dosega")

    def test_logs_split_on_result_cap(self):
        calls = []

        def post(url, body):
            a, b = int(body["params"][0]["fromBlock"], 16), int(body["params"][0]["toBlock"], 16)
            calls.append((a, b))
            if b - a > 100:
                return {"id": 1, "error": {"code": -32602, "message": f"query exceeds max results 20000, retry with "
                                                                      f"the range {a}-{a + 50}"}}
            return {"id": 1, "result": [{"n": a}]}
        r = brpc.Rpc(["https://fake"], post=post, sleep=lambda s: None)
        out = r.logs({"address": "0x1"}, 0, 300, max_range=1000)
        self.assertEqual(sorted(x["n"] for x in out), sorted({a for a, b in calls if b - a <= 100}))
        self.assertEqual(min(a for a, b in calls if b - a <= 100), 0)
        self.assertEqual(max(b for a, b in calls if b - a <= 100), 300)


# ---------- the class and the funnel ----------------------------------------------------------------------------------

class Timeouts(unittest.TestCase):
    def test_a_timed_out_range_is_halved(self):
        import socket
        calls = []

        def post(url, body):
            a, b = int(body["params"][0]["fromBlock"], 16), int(body["params"][0]["toBlock"], 16)
            calls.append((a, b))
            if b - a > 1000:
                raise socket.timeout("timed out")
            return {"id": 1, "result": [{"n": a}]}
        r = brpc.Rpc(["https://fake"], post=post, sleep=lambda s: None, retries=4)
        out = r.logs({"address": "0x1"}, 0, 4999, max_range=5000)
        self.assertEqual(min(x["n"] for x in out), 0)
        self.assertEqual(r.retries, 4)
        from collections import Counter
        self.assertLessEqual(max(Counter(calls).values()), 2)   # one retry a range, then halved
        self.assertEqual(sorted({x["n"] for x in out})[-1] + 624, 4999)


class Klasa(Db):
    def ev(self, i, tok, tier="pumpa15", t0=None):
        t0 = t0 or 1_790_000_000 + i * 86400 * 3
        e = {"eid": f"j:{tok}:{t0}", "kind": "jump", "token": tok, "symbol": tok[-4:], "pool": "0xp", "t0": t0,
             "win_end": t0 + 3 * H, "peak_ts": t0 + 2 * H, "peak_x": 1.0, "src": "c1h 6h", "tier": tier,
             "peak_mc": 20e6, "mcap0": 10e6, "prio": 1}
        return e

    def trade(self, tok, w, ts, side, usd, block=None, li=[0]):
        li[0] += 1
        self.con.execute("INSERT INTO bnb_trades VALUES ('bsc',?,?,?,?,?,?,?,?,1,?,?,?,?,'transfer',NULL)",
                         (tok, "0xp", f"0x{li[0]:064x}", 1, block or ts, ts, w, side, USDT, usd, usd, usd / 100))

    def build(self, n_tok=6):
        evs = []
        for i in range(n_tok):
            tok = "0x" + f"{i + 1:040x}"
            e = self.ev(i, tok)
            evs.append(e)
            # the insider: bought 1 h before, sold into it (6 pumps: confirmed on the newer third)
            self.trade(tok, "0xin", e["t0"] - H, "buy", 50)
            self.trade(tok, "0xin", e["t0"] + H, "sell", 150)
            # a sandwich bot: buy and sell in the same block, before and into every pump
            self.trade(tok, "0xbot", e["t0"] - 2 * H, "buy", 50, block=7)
            self.trade(tok, "0xbot", e["t0"] - 2 * H + 1, "sell", 50, block=7)
            self.trade(tok, "0xbot", e["t0"] + H, "sell", 80)
            # a contract with the insider's pattern
            self.trade(tok, "0xctr", e["t0"] - H, "buy", 50)
            self.trade(tok, "0xctr", e["t0"] + H, "sell", 90)
            # a router (known address)
            self.trade(tok, klasa.KNOWN and next(iter(klasa.KNOWN)), e["t0"] - H, "buy", 50)
            self.trade(tok, next(iter(klasa.KNOWN)), e["t0"] + H, "sell", 90)
            # dust: 3 $ = 0.03 SOL: never "paid"
            self.trade(tok, "0xdust", e["t0"] - H, "buy", 3)
            self.trade(tok, "0xdust", e["t0"] + H, "sell", 3)
            # a near-threshold wallet: two pumps only
            if i < 2:
                self.trade(tok, "0xnear", e["t0"] - H, "buy", 40)
                self.trade(tok, "0xnear", e["t0"] + H, "sell", 60)
        pumpe.save_events(self.con, evs, 1_800_000_000)
        for e in evs:
            self.con.execute("UPDATE bnb_events SET fetched = 1 WHERE eid = ?", (e["eid"],))
            self.con.execute("INSERT INTO bnb_cover VALUES (?,?,?,?,?,?,?,?,?)",
                             (e["eid"], store.FETCH_DEPTH, 86400, 1.0, 10800, 0.9, 10, 5, 0))
        self.con.commit()
        return pumpe.load(self.con)

    def test_class_exclusions_funnel(self):
        evs = self.build()
        chain.build_parts(self.con, self.c, evs)
        evs = pumpe.load(self.con)
        fake = FakeChain([], code={"0xctr": "0x6080", "0xin": "0xef0100" + "ab" * 20})
        rpc = brpc.Rpc(["https://fake"], post=fake.post, sleep=lambda s: None)
        st, f = klasa.run(self.con, self.c, evs, 1_800_000_000, rpc)
        self.assertEqual(st["0xin"]["cls"], "prije_pumpe")   # a 7702 account is a person's wallet
        self.assertTrue(st["0xin"]["confirmed"])
        self.assertEqual(st["0xbot"]["cls"], "bot")
        self.assertEqual(st["0xctr"]["cls"], "ugovor")
        self.assertEqual(st[next(iter(klasa.KNOWN))]["cls"], "router")
        self.assertNotIn("0xdust", st)
        self.assertEqual(st["0xnear"]["cls"], "kandidat")
        self.assertEqual((f["pumpe15_1h"], f["duboko"], f["grupe"], f["potvrdjeno"], f["blizu_praga"]), (6, 6, 1, 1, 1))
        self.assertEqual(f["pokrivenost_pre_med"], 100.0)
        self.assertEqual(f["pokrivenost_skok_med"], 90.0)
        g = pogled.groups()
        self.assertEqual(len(g), 1)
        self.assertEqual(g[0]["address"], "0xin")
        self.assertEqual(g[0]["pnl_usd"], 600.0)
        self.assertEqual(len(g[0]["pumps"]), 6)
        self.assertEqual(set(g[0]["pumps"][0]), {"symbol", "token", "t0", "tier", "lead_min", "usd_in", "usd_out"})
        self.assertEqual(g[0]["pumps"][0]["lead_min"], 60.0)
        self.assertIn("klase", f)
        self.assertIn("prije pumpe", klasa.funnel_line(f) + "prije pumpe")

    def test_market_maker(self):
        tok = "0x" + "e1" * 20
        evs = [self.ev(i, tok, t0=1_790_000_000 + i * 86400) for i in range(2)]
        for e in evs:
            for k in range(3):
                self.trade(tok, "0xmm", e["t0"] - H + k, "buy", 50)
                self.trade(tok, "0xmm", e["t0"] + H + k, "sell", 50)
        self.assertEqual(klasa.market_makers(self.con, evs, self.c), {"0xmm"})


# ---------- the measurement ------------------------------------------------------------------------------------------

class Mjera(Db):
    def row(self, now, tok="0xt", gid="g"):
        return prati.record(self.con, "bnb_prije_pumpe", gid, {"wallet": "0xw", "token": tok, "tx": "0x1",
                                                               "ts": now - 30, "tax": 0.02, "usd": 100}, ["0xw"], now)

    def test_lifecycle(self):
        now = 1_800_000_000
        rid = self.row(now)
        self.assertIsNone(self.row(now + 10))    # dedup within 24 h
        q = {"0xt": (1.0, 100_000, 5e6, "T", "pancakeswap_v2")}
        self.assertEqual(prati.step(self.con, self.c, now + 60, set(), q)["entered"], 1)
        self.assertEqual(prati.step(self.con, self.c, now + 120, set(), {"0xt": (1.1, *q["0xt"][1:])})["closed"], 0)
        r = prati.step(self.con, self.c, now + 180, {("g", "0xt")}, {"0xt": (1.2, *q["0xt"][1:])})
        self.assertEqual(r["closed"], 1)
        st, reason, g, n50, n250, c50 = store.q(self.con, "SELECT status, exit_reason, ret_gross, ret_net_50, ret_net_250, "
                                                          "cost_50 FROM bnb_mjera WHERE id = ?", (rid,))[0]
        self.assertEqual((st, reason), ("closed", "prodali su"))
        self.assertAlmostEqual(g, 0.2)
        # 2 x 0.25 % fee + 2 x impact(50 $, 100k) + gas + 2 x 2 % tax, never under 3 %
        self.assertAlmostEqual(c50, prati.cost_rt(50, 100_000, 0.0025, 0.02, self.c))
        self.assertGreater(c50, 0.045)
        self.assertLess(n250, n50)

    def test_stop_time_and_misses(self):
        now = 1_800_000_000
        for tok in ("0xa", "0xb", "0xc", "0xd", "0xe"):
            self.row(now, tok)
        q = {t: (1.0, 100_000, 5e6, "T", "v2") for t in ("0xa", "0xb")}
        q["0xc"] = (1.0, 5_000, 5e6, "T", "v2")      # liquidity under 15k: a miss
        q["0xd"] = (1.0, 100_000, 20_000, "T", "v2")  # MC under 30k: a miss
        prati.step(self.con, self.c, now + 60, set(), q)
        prati.step(self.con, self.c, now + 120, set(), {"0xa": (0.7, 100_000, 5e6, "T", "v2")})
        prati.step(self.con, self.c, now + 25 * H, set(), {"0xb": (1.05, 100_000, 5e6, "T", "v2")})
        prati.step(self.con, self.c, now + 26 * H, set(), {})
        got = dict(store.q(self.con, "SELECT token, status || ':' || COALESCE(exit_reason, '') FROM bnb_mjera"))
        self.assertEqual(got, {"0xa": "closed:stop", "0xb": "closed:vrijeme", "0xc": "miss:likvidnost",
                               "0xd": "miss:MC ispod 30k", "0xe": "miss:bez cijene"})
        m = pogled.measurement()
        self.assertEqual(m["by_source"]["bnb_prije_pumpe"]["measured"], 2)
        self.assertEqual(m["by_source"]["bnb_prije_pumpe"]["misses"], 3)
        self.assertEqual(set(m["rows"][0]), set(pogled.MKEYS))

    def test_cost_floor(self):
        self.assertEqual(prati.cost_rt(50, 50_000_000, 0.0001, 0, self.c), 0.03)

    def test_buys_need_a_swap(self):
        w = "0x" + "ee" * 20
        tok = "0x" + "12" * 20
        pool = "0x" + "34" * 20
        lg = {"address": tok, "topics": [swaps.TRANSFER, t32(pool), t32(w)], "data": "0x" + w32(90),
              "transactionHash": "0xa1", "blockNumber": hx(5), "blockTimestamp": hx(100), "logIndex": hx(2)}
        air = dict(lg, transactionHash="0xa2")
        rec = {"0xa1": {"logs": [lg, {"address": pool, "topics": [swaps.V2], "data": "0x", "logIndex": hx(3)},
                                 {"address": USDT, "topics": [swaps.TRANSFER, t32(w), t32(pool)],
                                  "data": "0x" + w32(25 * 10 ** 18), "logIndex": hx(1)},
                                 dict(lg, data="0x" + w32(100), topics=[swaps.TRANSFER, t32(pool), t32(w)])]},
               "0xa2": {"logs": [air]}}

        class R:
            def batch(self, calls, size=50):
                return [rec[p[0]] for _m, p in calls]
        b = prati.buys_of(R(), [lg, air], {w})
        self.assertEqual(len(b), 1)
        self.assertEqual(b[0]["paid"], {USDT: 25.0})
        self.assertAlmostEqual(b[0]["tax"], 0.0)


# ---------- the runner: caps, wall clock, switch ----------------------------------------------------------------------

class Runner(Db):
    def test_wall_clock_and_call_cap(self):
        t = [0.0]
        clock = store.Clock(100, fn=lambda: t[0])
        self.assertFalse(clock.over())
        t[0] = 100.0
        self.assertTrue(clock.over())
        self.assertFalse(store.Clock(None).over())
        run.add_calls(self.con, 1_800_000_000, 41_000)
        ev = {"eid": "j:0x1:1", "kind": "jump", "token": "0x1", "symbol": "A", "pool": "0xp", "t0": 1_799_990_000,
              "win_end": 1_799_995_000, "peak_ts": 1, "peak_x": 1, "src": "c1h 6h", "tier": "pumpa15", "peak_mc": 2e7,
              "mcap0": 1e7, "prio": 1}
        pumpe.save_events(self.con, [ev], 1_800_000_000)

        class R:
            n = 0

            def head(self):
                return 1

            def block_ts(self, n):
                return 1_800_000_000

        with mock.patch.object(chain, "fill_prices", return_value=0), \
                mock.patch.object(pumpe, "build", return_value={"tokens": 0, "candled": 0, "gt_calls": 0,
                                                                "events_new": 0, "events": 0, "left": 0}), \
                mock.patch.object(run, "_rpc", return_value=R()), \
                mock.patch.object(chain, "fetch_event") as fe:
            store.kv(self.con, "discover_ts", 1_800_000_000)
            out = run.fill(self.con, self.c, 1_800_000_000, store.Clock(None), log=lambda *_: None, kind="pass",
                           gt_budget=1)
            self.assertEqual(out["cut"], "dnevni strop poziva")
            fe.assert_not_called()
            tick = iter(range(0, 10_000, 5))
            out = run.fill(self.con, self.c, 1_800_000_000, store.Clock(1, fn=lambda: next(tick)), log=lambda *_: None,
                           kind="backfill")
            self.assertEqual(out["cut"], "vrijeme")
            fe.assert_not_called()

    def test_dormant_unless_bnb_on_is_1(self):
        import run_bnb
        path = os.path.join(self.tmp.name, "dormant.db")
        for val in (None, "0", ""):
            env = {k: v for k, v in os.environ.items() if k != "BNB_ON"}
            env["BNB_DB"] = path
            if val is not None:
                env["BNB_ON"] = val
            buf = io.StringIO()
            with mock.patch.dict(os.environ, env, clear=True), redirect_stdout(buf), \
                    mock.patch("urllib.request.urlopen", side_effect=AssertionError("network")):
                self.assertEqual(run_bnb.main(["pass"]), 0)
                self.assertEqual(run_bnb.main(["track"]), 0)
            self.assertIn("isključeno", buf.getvalue())
            self.assertFalse(os.path.exists(path))
        with mock.patch.dict(os.environ, {"BNB_ON": "1"}):
            self.assertTrue(store.on())

    def test_pogled_shapes_empty_and_report(self):
        s = pogled.summary()
        self.assertEqual(set(s), {"chain", "updated", "tokens", "pumps", "read", "groups", "confirmed", "trades",
                                  "db_mb", "last_pass", "calls"})
        self.assertEqual(pogled.funnel(os.path.join(self.tmp.name, "nema.db")), {})
        self.assertEqual(pogled.measurement(path=os.path.join(self.tmp.name, "nema.db")), {"by_source": {}, "rows": []})
        from bnb import report
        text = report.write(self.con, self.c)
        self.assertIn("Statistika, ne optužba", text)
        self.assertTrue(os.path.exists(os.path.join(report.OUT_DIR, report.OUT_NAME)))

    def test_nothing_here_trades(self):
        for name in os.listdir(os.path.join(ROOT, "bnb")):
            if name.endswith(".py"):
                with open(os.path.join(ROOT, "bnb", name), encoding="utf-8") as f:
                    src = f.read()
                for bad in ("trade.executor", "from trade import executor", "SOLANA_PRIVATE_KEY", "eth_sendRawTransaction",
                            "sendTransaction"):
                    self.assertNotIn(bad, src, name)

    def test_schema_has_chain_columns(self):
        con = sqlite3.connect(self.path)
        for t in ("bnb_tokens", "bnb_candles", "bnb_events", "bnb_trades", "bnb_part", "bnb_pp", "bnb_mjera"):
            cols = {r[1] for r in con.execute(f"PRAGMA table_info({t})")}
            self.assertIn("chain", cols, t)
        con.close()


if __name__ == "__main__":
    unittest.main()
