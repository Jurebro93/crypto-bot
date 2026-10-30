"""Executor and paper-follow logic against a fake Jupiter (no network, no real wallet).

    python3 -m unittest discover -s tests
"""
import base64
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_trade  # noqa: E402
from paper import store as paper_store  # noqa: E402
from trade import executor, jupiter, wallet  # noqa: E402

CFG = {"mode": "dry", "size_sol": 0.05, "max_sol_per_trade": 0.1, "max_sol_per_day": 0.12, "max_open": 5,
       "min_sol_reserve": 0.05, "max_cost_pct": 6, "max_signal_age_s": 180, "poll_s": 5}
NOW = 1_800_000_000


class FakeJup:
    def __init__(self, cost=1.0):
        self.calls, self.executed, self.cost = [], [], cost

    def order(self, inp, out, amount, taker=None):
        self.calls.append((inp, out, amount))
        rate = 1000 if inp == jupiter.SOL else 1 / 1000
        return {"inAmount": str(amount), "outAmount": str(int(amount * rate)), "requestId": "rq",
                "inUsdValue": 100, "outUsdValue": 100 - self.cost, "transaction": "dHg=", "error": None}

    def execute(self, signed, rid):
        self.executed.append(rid)
        return {"status": "Success", "signature": "SIG", "inputAmountResult": "0", "outputAmountResult": "0"}


class TradeOffline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = FakeJup()
        self._saved = (jupiter.order, jupiter.execute, run_trade.PAPER_DB, run_trade.notify, executor.STOP_FILE)
        jupiter.order, jupiter.execute = self.fake.order, self.fake.execute
        run_trade.PAPER_DB = os.path.join(self.tmp.name, "paper.db")
        run_trade.notify = lambda t: None
        executor.STOP_FILE = os.path.join(self.tmp.name, "STOP")
        self.con = executor.connect(os.path.join(self.tmp.name, "trade.db"))
        for k in ("TRADE_LIVE", "SOLANA_PRIVATE_KEY"):
            os.environ.pop(k, None)

    def tearDown(self):
        jupiter.order, jupiter.execute, run_trade.PAPER_DB, run_trade.notify, executor.STOP_FILE = self._saved
        self.tmp.cleanup()

    def test_dry_buy_never_executes(self):
        r = executor.buy(self.con, {**CFG, "mode": "live"}, "MINT", "X", now=NOW)  # live in config, no env/key
        self.assertEqual((r["status"], r["mode"]), ("open", "dry"))
        self.assertEqual(self.fake.executed, [])
        self.assertEqual(self.fake.calls[0], (jupiter.SOL, "MINT", 50_000_000))

    def test_daily_cap_and_kill_switch(self):
        self.assertEqual(executor.buy(self.con, CFG, "A", now=NOW)["status"], "open")
        self.assertEqual(executor.buy(self.con, CFG, "B", now=NOW)["status"], "open")
        r = executor.buy(self.con, CFG, "C", now=NOW)
        self.assertEqual(r["status"], "blocked")
        self.assertIn("dnevni limit", r["error"])
        open(executor.STOP_FILE, "w").close()
        self.assertIn("kill switch", executor.buy(self.con, {**CFG, "max_sol_per_day": 9}, "D", now=NOW)["error"])
        self.assertEqual(len(self.fake.calls), 2)  # blocked buys never even ask for a quote

    def test_cost_too_high_blocks(self):
        self.fake.cost = 12
        r = executor.buy(self.con, CFG, "MINT", now=NOW)
        self.assertEqual(r["status"], "blocked")
        self.assertIn("trošak", r["error"])

    def test_live_position_not_closed_when_live_off(self):
        self.con.execute("INSERT INTO positions (token, mode, status, qty_raw, qty_left, sol_in, sol_back, opened_ts) "
                         "VALUES ('M','live','open',1000,1000,0.05,0,?)", (NOW,))
        r = executor.sell(self.con, CFG, 1, close=True, now=NOW)
        self.assertEqual(r["status"], "failed")
        self.assertEqual(self.con.execute("SELECT status FROM positions").fetchone()[0], "open")

    def test_follow_mirrors_paper(self):
        p = paper_store.connect(run_trade.PAPER_DB)
        pos = {"opened_ts": NOW - 10, "size_usd": 50, "entry_px": 1, "entry_eff": 1, "open": True, "fills": []}
        tid = paper_store.open_trade(p, "MINT", "MEME", pos, {})
        paper_store.open_trade(p, "OLD", "OLD", {**pos, "opened_ts": NOW - 1000}, {})  # stale signal
        p.commit()
        run_trade.follow_once(self.con, CFG, since=0, now=NOW, quiet=True)
        rows = dict(self.con.execute("SELECT token, status FROM positions"))
        self.assertEqual(rows, {"MINT": "open", "OLD": "blocked"})
        self.assertEqual(self.con.execute("SELECT qty_raw FROM positions WHERE token='MINT'").fetchone()[0], 50_000_000_000)

        pos["fills"] = [{"frac": 0.5, "reason": "take_profit_1x"}]  # paper sells half
        p.execute("UPDATE trades SET state=? WHERE id=?", (json.dumps(pos), tid))
        p.commit()
        run_trade.follow_once(self.con, CFG, since=0, now=NOW + 60, quiet=True)
        left, done, st = self.con.execute("SELECT qty_left, fills_done, status FROM positions WHERE token='MINT'").fetchone()
        self.assertEqual((left, done, st), (25_000_000_000, 1, "open"))

        pos["fills"].append({"frac": 0.5, "reason": "stop_loss"})
        pos["open"] = False
        p.execute("UPDATE trades SET state=? WHERE id=?", (json.dumps(pos), tid))
        p.commit()
        run_trade.follow_once(self.con, CFG, since=0, now=NOW + 120, quiet=True)
        left, st, back = self.con.execute("SELECT qty_left, status, sol_back FROM positions WHERE token='MINT'").fetchone()
        self.assertEqual((left, st), (0, "closed"))
        self.assertAlmostEqual(back, 0.05)
        run_trade.follow_once(self.con, CFG, since=0, now=NOW + 180, quiet=True)  # nothing sold twice
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM orders WHERE side='sell'").fetchone()[0], 2)

    def test_sign_jupiter_style_tx(self):
        try:
            from solders.hash import Hash
            from solders.keypair import Keypair
            from solders.message import MessageV0
            from solders.system_program import TransferParams, transfer
            from solders.transaction import VersionedTransaction
        except ImportError:
            self.skipTest("solders nije instaliran")
        kp = Keypair()
        ix = transfer(TransferParams(from_pubkey=kp.pubkey(), to_pubkey=Keypair().pubkey(), lamports=1))
        msg = MessageV0.try_compile(kp.pubkey(), [ix], [], Hash.default())
        unsigned = VersionedTransaction.populate(msg, [executor_null_sig()])
        signed = VersionedTransaction.from_bytes(base64.b64decode(
            wallet.sign(base64.b64encode(bytes(unsigned)).decode(), kp)))
        self.assertTrue(signed.verify_with_results()[0])
        os.environ["SOLANA_PRIVATE_KEY"] = str(kp)
        try:
            self.assertEqual(wallet.address(), str(kp.pubkey()))
        finally:
            os.environ.pop("SOLANA_PRIVATE_KEY")


def executor_null_sig():
    from solders.signature import Signature
    return Signature.default()


if __name__ == "__main__":
    unittest.main()
