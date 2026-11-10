"""10.11. (završni pregled): the 24-h decision line says what it really counts, and the rent of a sold token's
account is read at the same fresh level as the balances."""
import sqlite3
import unittest
from unittest import mock

from trade import aplog, wallet


class DayLineCap(unittest.TestCase):
    def setUp(self):
        aplog._DAY.clear()

    def tearDown(self):
        aplog._DAY.clear()

    def test_capped_when_the_day_has_more_decisions_than_are_read(self):
        rows = [{"ts": 1000 + i, "kind": "preskocio", "why_short": "bez dokaza u demu"} for i in range(aplog.DAY_LIMIT)]
        with mock.patch.object(aplog, "entries", lambda *a, **k: rows):
            val = aplog.summary_24h(sqlite3.connect(':memory:'), None, now=10_000)
        self.assertEqual(val.get("capped"), aplog.DAY_LIMIT)

    def test_not_capped_on_a_normal_day(self):
        rows = [{"ts": 1000, "kind": "kupio"}]
        with mock.patch.object(aplog, "entries", lambda *a, **k: rows):
            val = aplog.summary_24h(sqlite3.connect(':memory:'), None, now=10_000)
        self.assertNotIn("capped", val)

    def test_both_pages_say_what_they_count(self):
        from ui import apjavno, pravitrade
        self.assertTrue(pravitrade.dnevnik_summary({"signali": 5, "kupio": 1, "capped": 1000}).startswith("Zadnjih 1000 odluka:"))
        self.assertTrue(pravitrade.dnevnik_summary({"signali": 5, "kupio": 1}).startswith("Zadnja 24 h:"))
        self.assertEqual(apjavno._day({"signali": 5, "capped": 1000})["capped"], 1000)


class RentRead(unittest.TestCase):
    def test_token_accounts_read_confirmed(self):
        seen = []

        def rpc(method, params):
            seen.append((method, params))
            return {"value": []}
        with mock.patch.object(wallet, "rpc", rpc):
            wallet.token_accounts("OWNER", "MINT")
            wallet.token_raw_balance("OWNER", "MINT")
        for method, params in seen:
            self.assertEqual(params[-1].get("commitment"), wallet.READ_COMMITMENT, method)
        self.assertEqual(wallet.READ_COMMITMENT, "confirmed")


if __name__ == "__main__":
    unittest.main()
