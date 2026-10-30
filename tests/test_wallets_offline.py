"""Wallet module against canned RPC data (no network).

    python3 -m unittest discover -s tests
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wallets import pnl, rpc, store  # noqa: E402

W = "Wallet111111111111111111111111111111111111"
WSOL = rpc.WSOL


def _tx(ts, sig, sol_lamports, toks, wallet=W, slot=None):
    """Raw getTransactionsForAddress row: wallet's native change + token balances (mint -> (pre, post))."""
    pre, post = [], []
    for i, (mint, (a, b)) in enumerate(toks.items()):
        for side, amt in ((pre, a), (post, b)):
            if amt is not None:
                side.append({"accountIndex": i + 1, "mint": mint, "owner": wallet,
                             "uiTokenAmount": {"amount": str(int(amt * 1e6)), "decimals": 6}})
    return {"blockTime": ts, "slot": slot or ts,
            "transaction": {"signatures": [sig], "message": {"accountKeys": [{"pubkey": wallet}]}},
            "meta": {"err": None, "preBalances": [10_000_000_000], "postBalances": [10_000_000_000 + sol_lamports],
                     "preTokenBalances": pre, "postTokenBalances": post}}


class WalletsOffline(unittest.TestCase):
    def test_parse_buy_sell_transfer_and_wsol(self):
        buy = rpc.parse(_tx(1, "a", -1_000_000_000, {"M": (None, 500)}), W)
        self.assertEqual((buy[0]["kind"], buy[0]["tokens"], buy[0]["sol"]), ("buy", 500, -1.0))
        # sell paid out in WSOL that stays wrapped: still counts as SOL
        sell = rpc.parse(_tx(2, "b", -5000, {"M": (500, 0), WSOL: (0, 3)}), W)
        self.assertEqual(sell[0]["kind"], "sell")
        self.assertAlmostEqual(sell[0]["sol"], 3 - 5e-6, places=6)
        airdrop = rpc.parse(_tx(3, "c", -5000, {"X": (None, 100)}), W)
        self.assertEqual(airdrop[0]["kind"], "transfer_in")
        self.assertEqual(rpc.credits_for(0), 10)
        self.assertEqual(rpc.credits_for(250), 30)

    def test_positions_realized_unrealized_and_score(self):
        rows = []
        for i in range(12):  # 8 winners at 3x, 4 losers at -50%, one open bag at 2x
            m, t = f"M{i}", 10_000 + i * 3600
            out = 3.0 if i < 8 else 0.5
            rows += [{"sig": f"b{i}", "ts": t, "mint": m, "tokens": 100, "sol": -1.0, "kind": "buy"},
                     {"sig": f"s{i}", "ts": t + 1800, "mint": m, "tokens": -100, "sol": out, "kind": "sell"}]
        rows.append({"sig": "open", "ts": 60_000, "mint": "OPEN", "tokens": 100, "sol": -1.0, "kind": "buy"})
        pos = pnl.positions(rows, {"OPEN": 0.02})
        self.assertEqual(pos["OPEN"]["status"], "open")
        self.assertAlmostEqual(pos["OPEN"]["unrealized"], 1.0)
        s = pnl.score(pos, rows, now=70_000)
        self.assertEqual((s["closed"], s["win_rate"], s["big_wins"]), (12, 0.67, 8))
        self.assertAlmostEqual(s["realized_sol"], 14.0)
        self.assertGreater(s["score"], 60)
        self.assertGreater(s["copy_score"], 40)
        self.assertEqual(pnl.score(pos, rows, now=70_000, labels={"rugger"})["copy_score"], 0)
        sn = pnl.score(pos, rows, now=70_000, labels={"sniper"})  # profitable sniper: not copied, but tracked
        self.assertEqual((sn["style"], sn["copy_score"], pnl.tier(sn)[0]), ("sniper", 0, "S"))

    def test_partial_sell_and_dead_token(self):
        rows = [{"sig": "b", "ts": 1, "mint": "M", "tokens": 100, "sol": -2.0, "kind": "buy"},
                {"sig": "s", "ts": 2, "mint": "M", "tokens": -50, "sol": 3.0, "kind": "sell"}]
        p = pnl.positions(rows, {"M": 0.0})["M"]
        self.assertAlmostEqual(p["realized"], 2.0)       # 3 out - half of 2 in
        self.assertAlmostEqual(p["unrealized"], -1.0)    # other half rugged to 0
        self.assertEqual(p["status"], "closed")

    def test_registry_observe_label_queue(self):
        with tempfile.TemporaryDirectory() as d:
            con = store.connect(os.path.join(d, "t.db"))
            store.observe(con, "A", "T1", "harvest", "early_buyer", 100)
            store.observe(con, "A", "T1", "harvest", "early_buyer", 100)  # duplicate ignored
            store.observe(con, "A", "T2", "rug", "early_buyer", 200)
            store.observe(con, "B", "T1", "harvest", "dev", 100)
            store.label(con, "C", "rugger")
            store.observe(con, "C", "T3", "harvest", "early_buyer", 100)
            row = con.execute("SELECT sightings, priority FROM wallets WHERE wallet='A'").fetchone()
            self.assertEqual(row, (2, 4.0))
            self.assertIn("dev", store.labels(con, "B"))
            self.assertEqual([w for w, _ in store.queue(con, 10)], ["A"])  # B negative priority, C rugger


if __name__ == "__main__":
    unittest.main()
