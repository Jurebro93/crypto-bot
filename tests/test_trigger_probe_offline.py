"""10.11. (Jure: "da, v1"): Jupiter Trigger step 1, the probe: one createOrder request for an open real position's TP,
its answer's shape recorded; nothing is signed or sent (no /execute, no wallet.sign).

    python3 -m unittest tests.test_trigger_probe_offline
"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trade import executor, settings, trigger, wallet  # noqa: E402

MINT = "Hope" + "x" * 36 + "pump"


class Probe(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = executor.connect(os.path.join(self.tmp.name, "trade.db"))
        self.calls = []
        self._saved = (trigger._call, wallet.sign)
        trigger._call = lambda path, params=None, body=None, timeout=20: (
            self.calls.append((path, body)) or {"requestId": "r1", "transaction": "AAAA", "order": "OrdKey"})
        wallet.sign = lambda *a, **k: self.fail("the probe must never sign")

    def tearDown(self):
        trigger._call, wallet.sign = self._saved
        self.con.close()
        self.tmp.cleanup()

    def test_probe_asks_for_the_tp_order_and_records_its_shape_only(self):
        self.con.execute("INSERT INTO positions (league_id, token, symbol, opened_ts, mode, status, sol_in, qty_raw, qty_left) "
                         "VALUES (7, ?, 'Hope', ?, 'live', 'open', 0.15, 1000000000, 1000000000)", (MINT, int(time.time())))
        self.con.commit()
        res = trigger.probe(self.con, {7: {"mode": "tpsl", "tp_px": 0.0002}}, "Maker111", lambda m: 6, lambda: 200.0)
        self.assertTrue(res["ok"])
        (path, body), = self.calls
        self.assertEqual(path, "/createOrder")                        # never /execute
        self.assertEqual((body["inputMint"], body["outputMint"], body["maker"]), (MINT, trigger.SOL, "Maker111"))
        self.assertEqual(body["params"]["makingAmount"], "1000000000")
        # 1000 tokens (6 decimals) x $0.0002 / $200 per SOL = 0.001 SOL
        self.assertEqual(body["params"]["takingAmount"], str(int(0.001 * 1e9)))
        stored = settings.raw(self.con)["trigger_probe"]
        self.assertEqual(stored["answer"]["keys"], ["order", "requestId", "transaction"])
        self.assertNotIn("AAAA", str(stored))                         # the transaction itself is never kept

    def test_without_a_position_or_wallet_it_says_why(self):
        res = trigger.probe(self.con, {}, "Maker111", lambda m: 6, lambda: 200.0)
        self.assertFalse(res["ok"])
        self.assertIn("nema otvorene", res["why"])
        self.assertEqual(self.calls, [])
        self.assertIn("wallet", trigger.probe(self.con, {}, None, lambda m: 6, lambda: 200.0)["why"])

    def test_an_error_answer_is_a_failed_probe(self):
        trigger._call = lambda *a, **k: {"error": "Insufficient balance", "code": 400, "http_status": 400}
        self.con.execute("INSERT INTO positions (league_id, token, symbol, opened_ts, mode, status, qty_left) "
                         "VALUES (7, ?, 'Hope', ?, 'live', 'open', 5)", (MINT, int(time.time())))
        self.con.commit()
        res = trigger.probe(self.con, {7: {"mode": "tpsl", "tp_px": 1.0}}, "M", lambda m: 0, lambda: 100.0)
        self.assertFalse(res["ok"])
        self.assertEqual(res["answer"]["error"], "Insufficient balance")


if __name__ == "__main__":
    unittest.main()
