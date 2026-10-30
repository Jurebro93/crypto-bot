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
        league.market = lambda mints: {m: (2.0, 1e6, None, 2e6) for m in mints}

    def test_buy_sell_and_leaderboard(self):
        con = store.connect()
        tid = store.buy(con, "Ivan", MINT, "SOL", 100, 1.0, 1e6, mcap=1e6)
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
        t = store.trades(con, "Ivan", "closed")[0]
        self.assertEqual((t["entry_mcap"], t["exit_mcap"]), (1e6, 2e6))  # exit mcap follows price when not given
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
        t = store.trades(con, "Jure", "closed")[0]
        self.assertEqual((t["entry_mcap"], t["exit_mcap"]), (2e6, 2e6))
        self.assertIn("MC izlaz", league.page({}, "Jure")[1])


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
        self.assertIn("PANDA", league.login_help())          # tells which passwords are still missing

        import threading
        import urllib.error
        import urllib.request
        srv = run_ui.ThreadingHTTPServer(("127.0.0.1", 0), run_ui.Handler)
        srv.verbose = False
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a):
                return None

        def get(path, name, pw):
            auth = base64.b64encode(f"{name}:{pw}".encode()).decode()
            req = urllib.request.Request(base + path, headers={"Authorization": "Basic " + auth})
            try:
                return urllib.request.build_opener(NoRedirect).open(req).status
            except urllib.error.HTTPError as e:
                return e.code

        self.assertEqual(get("/prijava", "x", "shared"), 401)          # shared password: ask for a player login
        self.assertEqual(get("/prijava", "Ivan", "ivanpw"), 303)       # player: on to the league
        self.assertEqual(get("/prijava?kao=Ivan", "Ivan", "ivanpw"), 401)  # switching user asks again
        self.assertEqual(get("/natjecanje", "x", "wrong"), 401)
        srv.shutdown()
        for k in ("UI_PASSWORD", "UI_PASS_IVAN"):
            os.environ.pop(k)
        importlib.reload(run_ui)


if __name__ == "__main__":
    unittest.main()
