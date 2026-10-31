"""Live SOL prices for open wallet positions (DexScreener pairs, faked here) and unrealized PnL."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wallets import pnl, prices  # noqa: E402

W = prices.WSOL


def pair(base, quote, native, usd, liq):
    return {"chainId": "solana", "baseToken": {"address": base}, "quoteToken": {"address": quote},
            "priceNative": str(native), "priceUsd": str(usd), "liquidity": {"usd": liq}}


class Prices(unittest.TestCase):
    def test_sol_prices(self):
        pairs = [pair("A", W, 0.001, 0.2, 5000), pair("A", W, 0.0009, 0.18, 100),  # most liquid wins
                 pair("B", "USDC", 0.5, 0.5, 9000), pair(W, "USDC", 200, 200, 1e6)]
        got = prices.sol_prices(["A", "B", "C"], fetch=lambda ms: pairs)
        self.assertEqual(got["A"], 0.001)
        self.assertAlmostEqual(got["B"], 0.5 / 200)
        self.assertNotIn("C", got)

    def test_unrealized(self):
        rows = [{"mint": "A", "ts": 1, "kind": "buy", "tokens": 1000.0, "sol": -1.0},
                {"mint": "A", "ts": 2, "kind": "sell", "tokens": -400.0, "sol": 0.8}]
        p = pnl.positions(rows, {"A": 0.002})["A"]
        self.assertEqual(p["status"], "open")
        self.assertAlmostEqual(p["value"], 1.2)
        self.assertAlmostEqual(p["unrealized"], 1.2 - 0.6)
        self.assertAlmostEqual(p["roi"], 1.0)


if __name__ == "__main__":
    unittest.main()
