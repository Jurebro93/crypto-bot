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


class RealTrades(unittest.TestCase):
    def setUp(self):
        store.DB = os.path.join(tempfile.mkdtemp(), "league.db")
        from ui import real
        self.real = real
        real.live = lambda mints: {m: (52_000, "REMARC", None) for m in mints}

    def test_parse_usd(self):
        p = self.real.parse_usd
        self.assertEqual((p("26k"), p("$1.5M"), p("22"), p("26,000"), p(""), p("abc")),
                         (26_000, 1_500_000, 22, 26_000, None, None))

    def test_add_follow_close(self):
        link = f"https://dexscreener.com/solana/{MINT}"
        loc = self.real.post("/moji-tradeovi/add", {"token": link, "size": "22", "mcap": "26k"}, "Jure")
        self.assertIn("ok=", loc)
        self.assertIn("err=", self.real.post("/moji-tradeovi/add", {"token": "nista", "size": "22"}, "Jure"))
        self.assertIn("err=", self.real.post("/moji-tradeovi/add", {"token": MINT, "size": "22"}, None))
        body = self.real.page({}, "Jure")[1]
        self.assertIn("+22.00", body)                         # MC doubled 26k -> 52k on $22
        self.assertIn("Jure", self.real.page({}, "Ivan")[1])  # others see it under Ostali igrači
        con = store.connect()
        tid = store.real_trades(con, "Jure")[0]["id"]
        self.assertIn("err=", self.real.post("/moji-tradeovi/close", {"id": str(tid)}, "Ivan"))  # not his
        self.assertIn("ok=", self.real.post("/moji-tradeovi/close", {"id": str(tid), "mcap": "13k"}, "Jure"))
        self.assertAlmostEqual(store.real_trades(con, "Jure")[0]["pnl_usd"], -11)
        self.real.post("/moji-tradeovi/delete", {"id": str(tid)}, "Jure")
        self.assertEqual(store.real_trades(con), [])


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
