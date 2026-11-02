"""2.11.: Jure's pairless sale at the fake DexScreener price is re-priced at the real one, once."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import fixes, store  # noqa: E402


class Pairless(unittest.TestCase):
    def test_bogus_sale_repriced_once(self):
        path = os.path.join(tempfile.mkdtemp(), "league.db")
        con = store.connect(path)
        ts = 1793551740  # 16:09
        con.execute("INSERT INTO trades (user, token, symbol, opened_ts, closed_ts, status, size_usd, entry_px, entry_eff,"
                    " qty, exit_px, proceeds, pnl_usd, ret, entry_mcap, realized) VALUES "
                    "('Jure','T','pairless',?,?,'closed',100,7.5e-05,7.7e-05,1298.7,0.0011,767.66,667.66,6.68,72800,20)",
                    (ts, ts + 4 * 3600))
        con.execute("INSERT INTO trades (user, token, symbol, opened_ts, closed_ts, status, size_usd, entry_px, entry_eff,"
                    " qty, exit_px, proceeds, pnl_usd, ret) VALUES "
                    "('Ivan','T','pairless',?,?,'closed',15,1.2e-4,1.22e-4,100,1.4e-4,17,2,0.13)", (ts, ts + 60))
        con.commit()
        self.assertEqual(fixes.pairless(con), 1)
        j = con.execute("SELECT * FROM trades WHERE user='Jure'").fetchone()
        self.assertLess(j["pnl_usd"], -75)
        self.assertAlmostEqual(j["exit_px"], 1.36e-05)
        self.assertIn("ispravljeno", j["note"])
        self.assertEqual(con.execute("SELECT pnl_usd FROM trades WHERE user='Ivan'").fetchone()[0], 2)
        self.assertEqual(fixes.pairless(con), 0)
        self.assertLess(store.account(con, "Jure")["cash"], 1000)


if __name__ == "__main__":
    unittest.main()
