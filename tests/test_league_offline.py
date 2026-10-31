"""Natjecanje: demo accounts, buy/sell accounting, leaderboard, ideas, and the login rules. No network."""
import base64
import os
import sys
import tempfile
import time
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
        from ui import real
        real.live = lambda mints: {m: (2e6, "SOL", None) for m in mints}
        link = f"https://dexscreener.com/solana/{MINT}"
        self.assertIn("err=", league.post("/natjecanje/buy", {"token": link, "size": "50"}, "Jure"))  # already open
        self.assertIn("ok=", league.post("/natjecanje/buy", {"token": link, "size": "50"}, "Ivan"))
        self.assertIn("err=", league.post("/natjecanje/buy", {"token": MINT, "size": "50"}, None))
        league.post("/prijedlozi/add", {"text": "alarm za pad <30%>"}, "Panda")
        for user in ("Jure", None):
            self.assertIn("Ljestvica", league.page({}, user)[1])
            self.assertIn("<b>Jure</b>", league.page({}, user)[1])   # everyone sees Jure's position
            body = league.ideas_page({}, user)[1]
            self.assertIn("&lt;30%&gt;", body)
        con = store.connect()
        tid = store.trades(con, "Jure", "open")[0]["id"]
        self.assertIn("ok=", league.post("/natjecanje/sell", {"id": str(tid)}, "Jure"))
        t = store.trades(con, "Jure", "closed")[0]
        self.assertEqual((t["entry_mcap"], t["exit_mcap"]), (2e6, 2e6))
        self.assertIn("MC izlaz", league.page({}, "Jure")[1])


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


class DiskFull(unittest.TestCase):
    def test_cache_prune(self):
        from event_calendar import http
        saved = http.CACHE_DIR
        http.CACHE_DIR = tempfile.mkdtemp()
        try:
            for i in range(5):
                p = os.path.join(http.CACHE_DIR, f"{i}.json")
                with open(p, "w") as f:
                    f.write("x" * 400_000)
                os.utime(p, (1000 + i, 1000 + i))   # 0 is the oldest
            fresh = os.path.join(http.CACHE_DIR, "new.json")
            with open(fresh, "w") as f:
                f.write("x" * 400_000)
            self.assertEqual(http.prune(max_mb=1.3, max_age=10**12)[0], 3)   # oldest first until under 1.3 MB
            self.assertEqual(sorted(os.listdir(http.CACHE_DIR)), ["3.json", "4.json", "new.json"])
            self.assertTrue(os.path.exists(fresh))
            self.assertEqual(http.prune(max_mb=100, max_age=3600)[0], 2)   # older than an hour
            self.assertEqual(os.listdir(http.CACHE_DIR), ["new.json"])
            rpc = os.path.join(http.CACHE_DIR, "rpc-abc.json")
            with open(rpc, "w") as f:
                f.write("{}")
            os.utime(rpc, (time.time() - 7200,) * 2)               # Helius RPC cache is dead after its 10 min TTL
            self.assertEqual(http.prune()[0], 1)
            self.assertEqual(os.listdir(http.CACHE_DIR), ["new.json"])
        finally:
            http.CACHE_DIR = saved

    def test_usage_page_shows_disk(self):
        from ui import usage
        self.assertIn("Disk", usage.page({})[1])


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
        self.assertIn("Panda", league.login_help())          # tells which passwords are still missing

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

        self.assertEqual(get("/prijava", "x", "shared"), 200)          # shared password: login form for a player
        self.assertEqual(get("/prijava", "Ivan", "ivanpw"), 303)       # player: on to the league
        self.assertEqual(get("/prijava?kao=Ivan", "Ivan", "ivanpw"), 200)  # switching user shows the form
        self.assertEqual(get("/natjecanje", "x", "wrong"), 401)

        # login form + cookie (phones / in-app browsers that never show the browser's password box)
        import urllib.parse
        opener = urllib.request.build_opener(NoRedirect)

        def post_login(name, pw, nxt="/tokens"):
            data = urllib.parse.urlencode({"name": name, "pw": pw, "next": nxt}).encode()
            try:
                r = opener.open(urllib.request.Request(base + "/prijava", data=data))
            except urllib.error.HTTPError as e:
                r = e
            return r.status if hasattr(r, "status") else r.code, r.headers

        try:
            opener.open(base + "/tokens")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 401)
            self.assertIsNone(e.headers.get("WWW-Authenticate"))     # no browser box, the page has a form
            self.assertIn(b"name=pw", e.read())
        code, hdr = post_login("Ivan", "ivanpw")
        self.assertEqual((code, hdr["Location"]), (303, "/tokens"))
        cookie = hdr["Set-Cookie"].split(";")[0]
        r = opener.open(urllib.request.Request(base + "/natjecanje", headers={"Cookie": cookie}))
        self.assertEqual(r.status, 200)
        self.assertEqual(run_ui.cookie_user(cookie.split("=", 1)[1]), (True, "Ivan"))
        self.assertEqual(post_login("Ivan", "nope")[0], 401)
        self.assertEqual(post_login("x", "shared", "//evil.com")[1]["Location"], "/")   # no open redirect
        self.assertEqual(run_ui.cookie_user("eA==.9999999999.bad"), (False, None))
        srv.shutdown()
        for k in ("UI_PASSWORD", "UI_PASS_IVAN"):
            os.environ.pop(k)
        importlib.reload(run_ui)


if __name__ == "__main__":
    unittest.main()
