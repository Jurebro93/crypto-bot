"""KOL copy replay on synthetic swaps: pool-side swap price (curve and AMM), cached price lookups, events from
chain_trades, points filled as they come due, mirrored exits and the 'sold before our entry' skip, the big-token
skip, the credit stop, statistics with the out-of-sample test, and the dashboard page."""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kolcopy import prices, replay, stats, store  # noqa: E402
from retro import chain  # noqa: E402

A = "HgxEGTZ1Epb64RrYqcuHkqb1gGWWnF5WcPTCDWzApump"
B = "8uBobWMhu6hRUn4jaA4kjcgWCjTxgHwHJtPgBePXpump"
C = "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"
CURVE, POOL = "Curve1111111111111111111111111111111111111", "Pool11111111111111111111111111111111111111"
T0 = 1793390000
W1, W2, W3, W4 = "Wal1" * 11, "Wal2" * 11, "Wal3" * 11, "Wal4" * 11


def tx(sig, ts, mint, price, buy=True, amm=False, trader="Trader111111111111111111111111111111111111", ok=True):
    """A swap of 1000 tokens at `price` SOL each: curve (SOL as lamports on the curve) or AMM (wSOL in the pool)."""
    tok, sol = 1000.0, 1000.0 * price
    pool = POOL if amm else CURVE
    d_pool_tok = -tok if buy else tok
    d_pool_sol = sol if buy else -sol
    keys = [{"pubkey": trader, "signer": True}, {"pubkey": pool, "signer": False}]
    pre_l, post_l = [10 * 10 ** 9, 50 * 10 ** 9], [10 * 10 ** 9 - int(d_pool_sol * 1e9), 50 * 10 ** 9]
    if not amm:
        post_l[1] = 50 * 10 ** 9 + int(d_pool_sol * 1e9)

    def bal(owner, m, amt):
        return {"owner": owner, "mint": m, "uiTokenAmount": {"amount": str(int(amt * 1e6)), "decimals": 6}}
    pre = [bal(pool, mint, 1e6), bal(trader, mint, 5000)]
    post = [bal(pool, mint, 1e6 + d_pool_tok), bal(trader, mint, 5000 - d_pool_tok)]
    if amm:
        pre.append(bal(pool, chain.WSOL, 100))
        post.append(bal(pool, chain.WSOL, 100 + d_pool_sol))
    return {"blockTime": ts, "slot": ts, "transaction": {"signatures": [sig], "message": {"accountKeys": keys}},
            "meta": {"err": None if ok else {"x": 1}, "preBalances": pre_l, "postBalances": post_l,
                     "preTokenBalances": pre, "postTokenBalances": post}}


def path_a(t):
    """A (x 1e-6 SOL, a ~1000 SOL market cap): 1.0 before the buy, up to 2.0 at +600 s, down to 0.5 at +3600 s."""
    if t <= T0:
        x = 1.0
    elif t <= T0 + 600:
        x = 1.0 + (t - T0) / 600
    elif t <= T0 + 3600:
        x = 2.0 - 1.5 * (t - T0 - 600) / 3000
    else:
        x = 0.5
    return x * 1e-6


class Market:
    def __init__(self):
        self.txs = {A: [], B: [], C: []}
        for t in range(T0 - 100, T0 + 7200, 5):
            self.txs[A].append(tx(f"a{t}", t, A, path_a(t)))
        for t in range(T0 + 7200, T0 + 30 * 3600, 600):
            self.txs[A].append(tx(f"a{t}", t, A, path_a(t), amm=True))
        for t in range(T0 - 60, T0 + 3600, 60):  # B: flat 1.0 for an hour, then nobody trades it
            self.txs[B].append(tx(f"b{t}", t, B, 1e-6, buy=t % 120 == 0))
        for t in range(T0 - 60, T0 + 3600, 60):
            self.txs[C].append(tx(f"c{t}", t, C, 0.001))
        self.calls = 0

    def page(self, address, since=None, until=None, asc=True, limit=100, token=None):
        self.calls += 1
        rows = [x for x in self.txs.get(address, []) if (since is None or x["blockTime"] >= since)
                and (until is None or x["blockTime"] < until)]
        rows.sort(key=lambda x: x["blockTime"], reverse=not asc)
        return rows[:limit], None


def hype_db(path, trades):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER, sol REAL, "
                "PRIMARY KEY (sig, mint))")
    con.executemany("INSERT INTO chain_trades VALUES (?,?,?,?,?,?)", trades)
    con.commit()
    con.close()


class SwapPrice(unittest.TestCase):
    def test_curve_and_amm_both_sides(self):
        self.assertAlmostEqual(prices.swap_price(tx("s", T0, A, 0.002), A), 0.002, places=9)
        self.assertAlmostEqual(prices.swap_price(tx("s", T0, A, 0.002, buy=False), A), 0.002, places=9)
        self.assertAlmostEqual(prices.swap_price(tx("s", T0, A, 0.03, amm=True), A), 0.03, places=9)
        self.assertAlmostEqual(prices.swap_price(tx("s", T0, A, 0.03, buy=False, amm=True), A), 0.03, places=9)

    def test_failed_other_mint_and_plain_transfer(self):
        self.assertIsNone(prices.swap_price(tx("s", T0, A, 1.0, ok=False), A))
        self.assertIsNone(prices.swap_price(tx("s", T0, A, 1.0), B))
        t = tx("s", T0, A, 1.0)
        t["meta"]["postBalances"] = t["meta"]["preBalances"]  # tokens moved, no SOL: a transfer
        self.assertIsNone(prices.swap_price(t, A))


class Lookup(unittest.TestCase):
    def setUp(self):
        self.con = store.connect(os.path.join(tempfile.mkdtemp(), "kc.db"))
        self.cfg = replay.load_config()
        self.m = Market()
        self.p = prices.Prices(self.con, self.cfg, page=self.m.page)

    def test_first_swap_after_and_cache(self):
        px, ts = self.p.price_at(A, T0 + 7)
        self.assertEqual(ts, T0 + 10)
        self.assertAlmostEqual(px, path_a(T0 + 10))
        calls = self.m.calls
        px2, ts2 = self.p.price_at(A, T0 + 31)   # inside the page already read: no new call
        self.assertEqual((ts2, self.m.calls), (T0 + 35, calls))
        self.assertEqual(self.p.credits, 10 * calls)

    def test_quiet_token_uses_last_swap_before(self):
        px, ts = self.p.price_at(B, T0 + 6 * 3600)
        self.assertAlmostEqual(px, 1e-6)
        self.assertLess(ts, T0 + 3600)
        self.assertIsNone(self.p.price_at("Nobody1111111111111111111111111111111111111", T0))


class Replay(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.hype = os.path.join(d, "hype.db")
        hype_db(self.hype, [
            ("b1", W1, A, "buy", T0, 1.0), ("b1x", W1, A, "buy", T0 + 30, 0.5), ("s1", W1, A, "sell", T0 + 600, None),
            ("b2", W2, B, "buy", T0, 2.0),
            ("b3", W3, A, "buy", T0, 0.01),                                   # dust: ignored
            ("b4", W4, A, "buy", T0, 1.0), ("s4", W4, A, "sell", T0 + 20, None),  # flips in 20 s
            ("b5", W2, C, "buy", T0, 1.0),                                    # 1M SOL "mcap": not a memecoin
        ])
        self.con = store.connect(os.path.join(d, "kc.db"))
        self.cfg = replay.load_config()
        self.m = Market()
        self.p = prices.Prices(self.con, self.cfg, page=self.m.page)

    def ev(self, wallet, mint):
        return dict(self.con.execute("SELECT * FROM events WHERE wallet=? AND mint=?", (wallet, mint)).fetchone())

    def test_incremental_then_complete(self):
        r = replay.step(self.con, self.cfg, self.p, now=T0 + 400, hype_path=self.hype, credits=1e6)
        self.assertEqual(r["added"], 4)
        self.assertIsNone(self.con.execute("SELECT 1 FROM events WHERE wallet=?", (W3,)).fetchone())
        e1 = self.ev(W1, A)
        self.assertEqual(e1["status"], "open")
        import json
        pts = json.loads(e1["points"])
        self.assertEqual(set(pts), {"kol", "e5", "e30", "e120"})   # only points at least lag_s old
        self.assertEqual(self.ev(W2, C)["status"], "skip")
        self.assertEqual(self.ev(W2, C)["skip_reason"], "velik token")

        replay.step(self.con, self.cfg, self.p, now=T0 + 31 * 3600, hype_path=self.hype, credits=1e6)
        e1, e2, e4 = self.ev(W1, A), self.ev(W2, B), self.ev(W4, A)
        self.assertEqual([e1["status"], e2["status"], e4["status"]], ["done"] * 3)
        self.assertEqual(e1["sell_ts"], T0 + 600)
        c = replay.cost(self.cfg)
        r1 = replay.returns(e1, self.cfg, T0 + 31 * 3600)
        self.assertAlmostEqual(r1[5]["mirror"], path_a(T0 + 605) / path_a(T0 + 5) - 1 - c, places=4)  # lamport rounding
        self.assertLess(r1[600]["mirror"], 0)               # entered at the top, out 10 min after the KOL
        self.assertAlmostEqual(r1[30]["h24"], path_a(T0 + 86400) / path_a(T0 + 30) - 1 - c, places=4)  # lamport rounding
        r4 = replay.returns(e4, self.cfg, T0 + 31 * 3600)
        self.assertEqual(r4[30]["mirror"], "skip")          # he sold before our 30 s entry
        self.assertIsInstance(r4[5]["mirror"], float)
        r2 = replay.returns(e2, self.cfg, T0 + 31 * 3600)
        self.assertAlmostEqual(r2[30]["mirror"], -c, places=6)   # never sold: out at 24 h, flat price

    def test_credit_stop(self):
        r = replay.step(self.con, self.cfg, self.p, now=T0 + 31 * 3600, hype_path=self.hype, credits=20)
        self.assertTrue(r["stopped"])
        self.assertLessEqual(r["credits"], 30)
        self.assertEqual(r["done"], 0)

    def test_daily_cap(self):
        day = replay._spent_today(self.con, T0 + 400)[0]
        store.kv_set(self.con, f"credits:{day}", self.cfg["credits_per_day"])
        r = replay.step(self.con, self.cfg, self.p, now=T0 + 400, hype_path=self.hype, credits=1e6)
        self.assertEqual(r["credits"], 0)

    def test_no_hype_db(self):
        r = replay.step(self.con, self.cfg, self.p, now=T0, hype_path=os.path.join(tempfile.mkdtemp(), "x.db"))
        self.assertEqual(r["added"], 0)


class Stats(unittest.TestCase):
    def test_summary_and_verdict(self):
        s = stats.summarize([0.1] * 40 + [-0.05] * 10)
        self.assertEqual(s["n"], 50)
        self.assertAlmostEqual(s["mean"], 0.07)
        self.assertEqual(s["win"], 0.8)
        self.assertEqual(stats.verdict(s), "u plusu")
        self.assertEqual(stats.verdict(stats.summarize([-0.2] * 40)), "u minusu")
        self.assertEqual(stats.verdict(stats.summarize([0.1, -0.1] * 5)), "premalo podataka")
        big = stats.summarize([0.01, -0.01] * 200)
        self.assertLess(big["lo"], 0)
        self.assertGreater(big["hi"], 0)
        self.assertEqual(stats.verdict(big), "nejasno")
        self.assertIsNone(stats.summarize(["skip"]))

    def test_out_of_sample(self):
        cfg = replay.load_config()
        rs = []
        for i in range(40):   # good wallet stays good, lucky wallet only in the first half
            rs.append(({"t0": T0 + i, "wallet": "good", "sell_ts": T0 + i + 60}, {30: {"mirror": 0.2}}))
            rs.append(({"t0": T0 + i, "wallet": "lucky", "sell_ts": None},
                       {30: {"mirror": 0.5 if i < 20 else -0.5}}))
            rs.append(({"t0": T0 + i, "wallet": "bad", "sell_ts": None}, {30: {"mirror": -0.3}}))
        o = stats.oos(rs, cfg, 30)
        self.assertEqual(o["picked"], ["lucky", "good"])
        self.assertAlmostEqual(o["picked_second"]["mean"], (0.2 - 0.5) / 2)
        self.assertGreater(o["picked_second"]["mean"], o["all_second"]["mean"])
        pw = stats.per_wallet(rs, cfg, 30)
        self.assertEqual(pw["good"]["hold_min"], 1)


class Page(unittest.TestCase):
    def test_page_with_and_without_db(self):
        from ui import kolcopy as page
        old = store.DB
        try:
            store.DB = os.path.join(tempfile.mkdtemp(), "none.db")
            title, html = page.page({})
            self.assertIn("još nije pokrenut", html)
            d = tempfile.mkdtemp()
            hype = os.path.join(d, "hype.db")
            hype_db(hype, [("b1", W1, A, "buy", T0, 1.0), ("s1", W1, A, "sell", T0 + 600, None)])
            store.DB = os.path.join(d, "kc.db")
            con = store.connect()
            cfg = replay.load_config()
            replay.step(con, cfg, prices.Prices(con, cfg, page=Market().page), now=T0 + 31 * 3600, hype_path=hype,
                        credits=1e6)
            con.close()
            title, html = page.page({"k": "5"})
            self.assertEqual(title, "KOL kopiranje")
            self.assertIn("Rezultat po kašnjenju", html)
            self.assertIn("kad KOL proda", html)
            self.assertIn("Wal1", html)
        finally:
            store.DB = old


if __name__ == "__main__":
    unittest.main()
