"""7.11.: token status (DexScreener pair gone? exact pair page, fresh mcap, GeckoTerminal fallback). No network."""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hype import tokenstatus  # noqa: E402
from ui.html import tlink  # noqa: E402

A, B = "2oXfEtMrQ5QAGgJHjTgfgt3N3hWrYEHNtdSw3MTbuU8L", "GhBPHgnNF99EThYxt4bxUfPX1hCPyAS72RCBgLjLpump"


class Status(unittest.TestCase):
    def test_refresh_read_and_cells(self):
        path = os.path.join(tempfile.mkdtemp(), "hype.db")
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE hype_signals (ts INTEGER, token TEXT)")
        dex = lambda toks: {B: {"pair_url": "https://dexscreener.com/solana/pairB", "dex_id": "raydium", "price": 8e-5,
                                "mcap": 73929, "liq": 34826}}
        gt = lambda t: {"gt_price": 7.3e-6, "gt_fdv": 7297.0, "gt_vol24": 0.0}
        n, with_pair, n_gt = tokenstatus.refresh(con, now=1_800_000_000, tokens=[A, B], dex=dex, gt=gt, log=lambda s: None)
        self.assertEqual((n, with_pair, n_gt), (2, 1, 1))
        con.close()
        st = tokenstatus.read(path)
        self.assertEqual(st[B]["has_pair"], 1)
        self.assertEqual(st[A]["has_pair"], 0)
        self.assertEqual(st[A]["gt_fdv"], 7297.0)
        # the dead token's icon says so and goes to the search; the live one goes to its pair page
        dead = tlink(A, "SpaceX", st[A])
        self.assertIn("više nema par", dead)
        self.assertIn("dexscreener.com/search?q=", dead)
        live = tlink(B, "ARIA", st[B])
        self.assertIn("dexscreener.com/solana/pairB", live)
        # market cap column: fresh DexScreener number, GeckoTerminal fallback, or "nema para"
        self.assertEqual(tokenstatus.market_cell(st[B], 50000)[1], 73929)
        self.assertIn("GT", tokenstatus.market_cell(st[A], 69500)[0])
        self.assertIn("nema para", tokenstatus.market_cell({"has_pair": 0, "checked_ts": 1_800_000_000}, 69500)[0])
        self.assertEqual(tokenstatus.market_cell(None, 69500)[1], 69500)

    def test_job_registered(self):
        root = os.path.join(os.path.dirname(__file__), "..")
        self.assertIn('"tokenstatus"', open(os.path.join(root, "run_sched.py")).read())
        self.assertIn('"status": cmd_status', open(os.path.join(root, "run_hype.py")).read())


if __name__ == "__main__":
    unittest.main()
