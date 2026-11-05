"""4.11.: WBTC / SOL / stablecoins never count as a "token most sources call" (kol/converge, Pregled highlight).

    python3 -m unittest tests.test_majors_offline
"""
import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import converge, store as kstore  # noqa: E402

WBTC = "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh"


class Majors(unittest.TestCase):
    def test_wbtc_is_dropped_from_converge_and_highlight(self):
        self.assertIn(WBTC, converge.majors())
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "kol.db")
        con = kstore.connect(path)
        now = int(time.time())
        for tok in (WBTC, "MEME"):      # an old WBTC row from before the filter, and a real memecoin
            con.execute("INSERT INTO converge (token, ts, first_ts, score, n_x, n_tg, n_chain, n_other, platforms, "
                        "handles, kol_selling, updated) VALUES (?,?,?,?,?,?,?,?,'[]','[]',0,?)",
                        (tok, now - 100, now - 200, 90, 0, 0, 149 if tok == WBTC else 3, 0, now))
        con.commit()
        from ui import pocetna
        old, kstore.DB = kstore.DB, path
        try:
            html = pocetna._hl_converge(now)
        finally:
            kstore.DB = old
        self.assertIn("MEME", html)
        self.assertNotIn(WBTC, html)
        converge.save(con, {}, now)
        self.assertEqual([t for t, in con.execute("SELECT token FROM converge")], ["MEME"])
        con.close()

    def test_big_liquid_token_is_not_a_convergence(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "kol.db")
        con = kstore.connect(path)
        con.execute("INSERT INTO tokens (token, liquidity) VALUES ('TRUMP', 9000000)")
        con.execute("INSERT INTO tokens (token, liquidity) VALUES ('MEME', 40000)")
        now = int(time.time())
        for tok in ("TRUMP", "MEME"):
            con.execute("INSERT INTO converge (token, ts, first_ts, score, n_x, n_tg, n_chain, n_other, platforms, "
                        "handles, kol_selling, updated) VALUES (?,?,?,?,?,?,?,?,'[]','[]',0,?)",
                        (tok, now - 100, now - 200, 84, 0, 0, 9, 6, now))
        con.commit()
        self.assertEqual(converge.too_big(con, {"TRUMP", "MEME", "NEW"}), {"TRUMP"})
        import unittest.mock as m
        evs = [("TRUMP", now - 60, "chain", f"w{i}", "buy") for i in range(9)] + [("MEME", now - 60, "chain", f"w{i}", "buy") for i in range(3)]
        with m.patch.object(converge, "events", return_value=(evs, {}, {})):
            out = converge.compute(now=now, cfg={"min_score": 0, "fresh_min": 60, "window_min": 60}, kol_db=path)
        self.assertNotIn("TRUMP", out)
        self.assertIn("MEME", out)
        converge.save(con, {}, now)
        self.assertEqual([t for t, in con.execute("SELECT token FROM converge")], ["MEME"])
        con.close()

    def test_compute_skips_majors(self):
        import unittest.mock as m
        evs = [(WBTC, 1000, "chain", f"w{i}", "buy") for i in range(5)] + [("MEME", 1000, "x", "a", "call"), ("MEME", 1010, "tg", "b", "call")]
        with m.patch.object(converge, "events", return_value=(evs, {"a": 80, "b": 80}, {})):
            out = converge.compute(now=1200, cfg={"min_score": 0, "fresh_min": 60, "window_min": 60})
        self.assertNotIn(WBTC, out)


if __name__ == "__main__":
    unittest.main()
