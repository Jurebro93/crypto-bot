"""Hype module against canned data (no network).

    python3 -m unittest discover -s tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hype import evaluate, onchain, score, store, telegram, xbuzz  # noqa: E402

NOW_MS = 1_800_000_000_000
W = "Buyer1111111111111111111111111111111111111"
MINT = "Mint11111111111111111111111111111111111pump"


def _tx(ts, sol_lamports, tok, mint=MINT, wallet=W):
    return {"timestamp": ts, "feePayer": wallet, "signature": f"s{ts}", "source": "PUMP_AMM", "accountData": [
        {"account": wallet, "nativeBalanceChange": sol_lamports, "tokenBalanceChanges": []},
        {"account": "ata", "nativeBalanceChange": 0, "tokenBalanceChanges": [
            {"userAccount": wallet, "mint": mint, "rawTokenAmount": {"tokenAmount": str(int(tok * 1e6)), "decimals": 6}}]}]}


class HypeOffline(unittest.TestCase):
    def test_swap_deltas_and_wallet_score(self):
        sol, toks = onchain.swap_deltas(_tx(1, -2_000_000_000, 1000), W)
        self.assertAlmostEqual(sol, -2.0)
        self.assertEqual(toks, {MINT: 1000})
        txs = []
        for i in range(6):  # 6 round trips, 4 winners at 3x, 2 losers at -50%
            m = f"M{i}"
            out = 3_000_000_000 if i < 4 else 500_000_000
            txs += [_tx(1000 * i + 900, out, -10, m), _tx(1000 * i, -1_000_000_000, 10, m)]
        orig = onchain.transactions
        onchain.transactions = lambda addr, **kw: txs if kw.get("before") is None else []
        try:
            trades, meta = onchain.wallet_trades(W, pages=1)
        finally:
            onchain.transactions = orig
        s = onchain.score_wallet(trades, meta)
        self.assertEqual((s["closed"], s["win_rate"], s["big_wins"], s["pnl_sol"]), (6, 0.67, 4, 7.0))
        self.assertFalse(s["bot"])
        self.assertGreater(s["score"], 50)

    def test_early_buyers_skips_sells_and_repeats(self):
        txs = [_tx(100, -1e9, 50), _tx(101, 5e8, -20), _tx(105, -1e9, 10),
               _tx(110, -3e9, 30, wallet="Other111111111111111111111111111111111111111")]
        orig = onchain.transactions
        onchain.transactions = lambda addr, **kw: txs if kw.get("before") is None else []
        try:
            b = onchain.early_buyers(MINT, n=10, pages=2)
        finally:
            onchain.transactions = orig
        self.assertEqual([x["wallet"][:5] for x in b], ["Buyer", "Other"])
        self.assertEqual(b[1]["secs_after_first"], 10)
        self.assertEqual(b[1]["sol_in"], 3.0)

    def test_telegram_parse(self):
        page = ('<div class="tgme_widget_message" data-post="calls/42"><div class="tgme_widget_message_text js-message_text">'
                'New gem $GTA6 <a href="https://dexscreener.com/solana/4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz">chart</a>'
                '</div><time datetime="2026-10-30T20:00:00+00:00">20:00</time></div>')
        p = telegram.parse(page, "calls")
        self.assertEqual(p[0]["cas"], ["4kjruqGHDsSqkMdFfCjV7Vb62HPFhtXyWc2t6JpQzDnz"])
        self.assertEqual(p[0]["tickers"], ["GTA6"])

    def test_features_copycats_revival(self):
        pair = {"liquidity": {"usd": 10000}, "volume": {"h1": 30000, "h24": 40000}, "priceChange": {"h1": 100},
                "txns": {"h1": {"buys": 300, "sells": 100}}, "pairCreatedAt": NOW_MS - 0.5 * 3.6e6,
                "info": {"imageUrl": "x", "socials": [{}, {}, {}]}}
        f = score.market_features(pair, NOW_MS)
        self.assertEqual((f["fresh"], f["turnover"], f["paid"], f["revival"]), (1.0, 1.0, 1.0, 0.0))
        self.assertAlmostEqual(f["buy_pressure"], 0.625)
        old = dict(pair, pairCreatedAt=NOW_MS - 30 * 24 * 3.6e6, volume={"h1": 6000, "h24": 12000})
        self.assertEqual(score.market_features(old, NOW_MS)["revival"], 1.0)  # 12x the hourly average
        clones = [{"chainId": "solana", "pairCreatedAt": NOW_MS - 3.6e6, "baseToken": {"address": a, "symbol": s, "name": n}}
                  for a, s, n in [("A", "GTA6", "GTA VI"), ("B", "GTAVI", "GTA 6 on sol"), ("C", "DOG", "dog"), ("me", "GTA6", "x")]]
        self.assertEqual(score.copycats(clones, "GTA6", "GTA VI", "me", NOW_MS), 2)
        self.assertEqual(score.score({"a": 1, "b": 0}, {"a": 1, "b": 3}), 25.0)

    def test_x_buzz(self):
        tweets = [{"author": {"userName": f"u{i}", "followers": 50000 if i < 2 else 100}, "likeCount": 10,
                   "retweetCount": 5} for i in range(10)]
        b = xbuzz.buzz(tweets)
        self.assertEqual((b["tweets"], b["authors"], len(b["influencers"]), b["engagement"]), (10, 10, 2, 200))
        self.assertAlmostEqual(b["feature"], 0.2 + 0.4 * 2 / 3 + 0.2 * 0.575, places=2)
        self.assertEqual(xbuzz.buzz([])["feature"], 0.0)

    def test_eval_loop(self):
        con = store.connect(":memory:")
        w = {"turnover": 1, "fresh": 1}
        for i in range(40):  # turnover predicts a 2x, fresh is noise
            good = i % 2 == 0
            row = {"token": f"T{i}", "symbol": f"T{i}", "name": "", "pair": "", "url": "", "price": 1.0, "mcap": 1,
                   "liquidity": 1000, "sources": {"profile"}, "score": 80 if good else 20,
                   "features": {"turnover": 1.0 if good else 0.0, "fresh": float(i % 3 == 0)}}
            store.log_signal(con, row, w)
            con.execute("UPDATE hype_signals SET ts = 0 WHERE token = ?", (row["token"],))
            store.snapshot(con, row["token"], 2.5 if good else 0.7, 1, 1000, ts=3600)
            store.snapshot(con, row["token"], 1.8 if good else 0.6, 1, 50 if i == 1 else 1000, ts=7200)
        rows = evaluate.outcomes(con, horizon_h=24, now=10 ** 6)
        self.assertEqual(len(rows), 40)
        self.assertTrue(rows[1]["rug"])
        buckets = {b["bucket"]: b for b in evaluate.by_bucket(rows)}
        self.assertEqual((buckets["80-100"]["hit_rate"], buckets["20-40"]["hit_rate"]), (1.0, 0.0))
        lift = {f["feature"]: f["lift"] for f in evaluate.feature_lift(rows)}
        self.assertEqual(lift["turnover"], 2.0)
        self.assertEqual(evaluate.paper_trade(rows, min_score=60)["avg_ret"], 1.0)  # every trade hits TP
        fit = evaluate.fit_weights(rows)
        self.assertGreater(fit["weights"]["turnover"], fit["weights"]["fresh"])


if __name__ == "__main__":
    unittest.main()
