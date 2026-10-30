"""Natjecanje: demo accounts, buy/sell accounting, leaderboard, ideas, and the login rules. No network."""
import base64
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import store  # noqa: E402
from ui import league  # noqa: E402

MINT = "So11111111111111111111111111111111111111112"


class League(unittest.TestCase):
    def setUp(self):
        self.db = os.path.join(tempfile.mkdtemp(), "league.db")
        store.DB = self.db
        league._live = lambda mints: {m: (2.0, 1e6, None) for m in mints}

    def test_buy_sell_and_leaderboard(self):
        con = store.connect()
        tid = store.buy(con, "Ivan", MINT, "SOL", 100, 1.0, 1e6)
        self.assertAlmostEqual(store.account(con, "Ivan")["cash"], 900)
        with self.assertRaises(ValueError):
            store.buy(con, "Ivan", MINT, "SOL", 50, 1.0, 1e6)     # already open
        with self.assertRaises(ValueError):
            store.buy(con, "Panda", MINT, "SOL", 5000, 1.0, 1e6)  # more than the account has
        board = store.leaderboard(con, {MINT: (2.0, 1e6, None)})
        self.assertEqual(board[0]["user"], "Ivan")
        self.assertGreater(board[0]["unrealized"], 90)
        pnl = store.sell(con, "Ivan", tid, 2.0, 1e6)
        self.assertTrue(90 < pnl < 100)                            # doubled, minus fees and impact
        self.assertEqual(store.account(con, "Ivan")["in_use"], 0)
        with self.assertRaises(ValueError):
            store.sell(con, "Panda", tid, 2.0, 1e6)

    def test_forms_and_pages(self):
        loc = league.post("/natjecanje/buy", {"token": MINT, "size": "50", "symbol": "SOL"}, "Jure")
        self.assertIn("ok=", loc)
        self.assertIn("err=", league.post("/natjecanje/buy", {"token": "../x", "size": "50"}, "Jure"))
        self.assertIn("err=", league.post("/natjecanje/buy", {"token": MINT, "size": "50"}, None))
        league.post("/prijedlozi/add", {"text": "alarm za pad <30%>"}, "Panda")
        for user in ("Jure", None):
            self.assertIn("Ljestvica", league.page({}, user)[1])
            body = league.ideas_page({}, user)[1]
            self.assertIn("&lt;30%&gt;", body)
        con = store.connect()
        tid = store.trades(con, "Jure", "open")[0]["id"]
        self.assertIn("ok=", league.post("/natjecanje/sell", {"id": str(tid)}, "Jure"))


class Login(unittest.TestCase):
    def test_player_and_shared_password(self):
        os.environ.update(UI_PASSWORD="shared", UI_PASS_IVAN="ivanpw")
        import importlib
        import run_ui
        importlib.reload(run_ui)

        def who(name, pw):
            h = run_ui.Handler.__new__(run_ui.Handler)
            h.headers = {"Authorization": "Basic " + base64.b64encode(f"{name}:{pw}".encode()).decode()}
            return h._authorized(), h.user

        self.assertEqual(who("ivan", "ivanpw"), (True, "Ivan"))
        self.assertEqual(who("Ivan", "shared"), (True, None))
        self.assertEqual(who("Panda", "ivanpw"), (False, None))
        self.assertEqual(who("Jure", ""), (False, None))
        for k in ("UI_PASSWORD", "UI_PASS_IVAN"):
            os.environ.pop(k)
        importlib.reload(run_ui)


if __name__ == "__main__":
    unittest.main()
