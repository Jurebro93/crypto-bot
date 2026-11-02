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
        self.assertIn("Dokupljeno", league.post("/natjecanje/buy", {"token": link, "size": "50"}, "Jure"))  # adds to it
        self.assertIn("ok=", league.post("/natjecanje/buy", {"token": link, "size": "50"}, "Ivan"))
        self.assertIn("err=", league.post("/natjecanje/buy", {"token": MINT, "size": "50"}, None))
        import sqlite3
        self.assertIn("disk servera je trenutno pun", league.db_error(sqlite3.OperationalError("database or disk is full")))
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


class PartialSell(unittest.TestCase):
    """Nicholas 1.11.: positions on top of Natjecanje as cards; sell 25% / 50% / Sve / a $ amount, the rest stays open."""
    def setUp(self):
        store.DB = os.path.join(tempfile.mkdtemp(), "league.db")
        league.market = lambda mints: {m: (2.0, 1e6, None, 2e6) for m in mints}

    def test_partial_then_rest(self):
        self.assertIn("ok=", league.post("/natjecanje/buy", {"token": MINT, "size": "100", "symbol": "SOL"}, "Jure"))
        con = store.connect()
        tid = store.trades(con, "Jure", "open")[0]["id"]
        loc = league.post("/natjecanje/sell", {"id": str(tid), "frac": "0.25"}, "Jure")
        self.assertIn("25%25", loc)
        t = store.trades(con, "Jure", "open")[0]
        self.assertAlmostEqual(t["size_usd"], 75)
        part = store.trades(con, "Jure", "closed")[0]
        self.assertAlmostEqual(part["size_usd"], 25)
        self.assertIn("djelomična", part["note"])
        acc = store.account(con, "Jure")
        self.assertAlmostEqual(acc["cash"], 1000 - 75 + part["pnl_usd"])   # money of the sold part is back at once
        con.commit()
        self.assertIn("ok=", league.post("/natjecanje/sell", {"id": str(tid), "usd": "20"}, "Jure"))
        self.assertEqual(len(store.trades(con, "Jure", "open")), 1)
        self.assertIn("err=", league.post("/natjecanje/sell", {"id": str(tid), "frac": "2"}, "Jure"))
        self.assertIn("ok=", league.post("/natjecanje/sell", {"id": str(tid), "usd": "99999"}, "Jure"))  # more = all
        self.assertEqual(store.trades(con, "Jure", "open"), [])
        self.assertEqual(store.account(con, "Jure")["in_use"], 0)

    def test_page_order(self):
        league.post("/natjecanje/buy", {"token": MINT, "size": "50", "symbol": "SOL"}, "Jure")
        body = league.page({}, "Jure")[1]
        self.assertIn("pos-all", body)
        self.assertIn("posView", body)                                   # list / tiles choice remembered
        con = store.connect()
        t = store.trades(con, "Jure", "open")[0]
        con.close()
        self.assertIn("ok=", league.post("/natjecanje/add", {"id": str(t["id"]), "size": "25"}, "Jure"))
        con = store.connect()
        self.assertAlmostEqual(store.trades(con, "Jure", "open")[0]["size_usd"], 75)
        con.close()
        self.assertIn("err=", league.post("/natjecanje/add", {"id": str(t["id"]), "size": "99999"}, "Jure"))
        loc = league.post("/natjecanje/buy", {"token": MINT, "size": "100"}, "Jure")   # buy again = add to it
        self.assertIn("Dokupljeno", loc)
        con = store.connect()
        self.assertEqual(len(store.trades(con, "Jure", "open")), 1)
        self.assertAlmostEqual(store.trades(con, "Jure", "open")[0]["size_usd"], 175)
        con.close()
        self.assertIn("confirm(", body)
        order = [body.index(k) for k in ("id=pozicije", "id=autosell", "id=dca", "id=moj", "id=zatvoreni", "id=kupi")]
        self.assertEqual(order, sorted(order))


class GlobalTpSl(unittest.TestCase):
    """One TP/SL rule for all open positions and (checkbox) for every new buy."""
    def setUp(self):
        store.DB = os.path.join(tempfile.mkdtemp(), "league.db")
        league.market = lambda mints: {m: (2.0, 1e6, None, 2e6) for m in mints}

    def test_rule_on_all_open_and_new_buys(self):
        import json
        from league import auto, dca
        con = store.connect()
        a = store.buy(con, "Ivan", "MintA", "AAA", 100, 1.0, 1e6, mcap=1e5)
        b = store.buy(con, "Ivan", "MintB", "BBB", 100, 2.0, 1e6, mcap=2e6)
        p = store.buy(con, "Panda", "MintA", "AAA", 100, 1.0, 1e6, mcap=1e5)
        loc = league.post("/natjecanje/auto", {"all": "1", "new": "1", "mode": "tpsl", "tp": "100%", "sl": "$1.5M"},
                          "Ivan")
        self.assertIn("ok=", loc)
        from urllib.parse import unquote
        self.assertIn("Preskočeno: AAA", unquote(loc))   # SL $1.5M is above AAA's $100k entry: would sell at once, skipped
        con = store.connect()
        self.assertIsNone(con.execute("SELECT auto FROM trades WHERE id=?", (a,)).fetchone()[0])
        league.post("/natjecanje/auto", {"all": "1", "new": "1", "mode": "tpsl", "tp": "100%", "sl": "-30%"}, "Ivan")
        ta = json.loads(con.execute("SELECT auto FROM trades WHERE id=?", (a,)).fetchone()[0])
        self.assertAlmostEqual(ta["sl_px"], 0.7)
        league.post("/natjecanje/auto", {"all": "1", "new": "1", "mode": "tpsl", "tp": "100%", "sl": "$1.5M"}, "Ivan")
        ta = json.loads(con.execute("SELECT auto FROM trades WHERE id=?", (a,)).fetchone()[0])
        tb = json.loads(con.execute("SELECT auto FROM trades WHERE id=?", (b,)).fetchone()[0])
        self.assertAlmostEqual(ta["tp_px"], 2.0)          # percent from each position's own entry
        self.assertAlmostEqual(tb["tp_px"], 4.0)
        self.assertAlmostEqual(tb["sl_px"], 1.5)          # $1.5M on a $2M entry = price 1.5
        self.assertIsNone(con.execute("SELECT auto FROM trades WHERE id=?", (p,)).fetchone()[0])  # not Panda's
        # new buy gets the rule, copy trading entries don't
        c = store.buy(con, "Ivan", "MintC", "CCC", 50, 1.0, 1e6, mcap=1e6)
        self.assertIn('"tp": "+100%"', con.execute("SELECT auto FROM trades WHERE id=?", (c,)).fetchone()[0])
        d = store.buy(con, "Ivan", "MintD", "DDD", 50, 1.0, 1e6, "copy KOL x", mcap=1e6)
        self.assertIsNone(con.execute("SELECT auto FROM trades WHERE id=?", (d,)).fetchone()[0])
        # DCA moves the average entry: a percent TP follows it
        dca.add_to(con, c, 50, 3.0, 1e6)
        tc = json.loads(con.execute("SELECT auto FROM trades WHERE id=?", (c,)).fetchone()[0])
        self.assertAlmostEqual(tc["tp_px"], 3.0, places=2)   # avg entry 1.5 -> +100% = 3.0
        body = league.page({}, "Ivan")[1]
        self.assertIn("sve otvorene pozicije", body)
        self.assertIn("Pravilo za nove kupnje je uključeno", body)
        # switch the rule off for new buys: positions keep theirs
        self.assertIn("ok=", league.post("/natjecanje/auto", {"all": "1", "mode": "off", "keep": "1"}, "Ivan"))
        self.assertIsNone(auto.get_rule(con, "Ivan"))
        self.assertIsNotNone(con.execute("SELECT auto FROM trades WHERE id=?", (a,)).fetchone()[0])
        e = store.buy(con, "Ivan", "MintE", "EEE", 50, 1.0, 1e6, mcap=1e6)
        self.assertIsNone(con.execute("SELECT auto FROM trades WHERE id=?", (e,)).fetchone()[0])
        # off for all open positions
        league.post("/natjecanje/auto", {"all": "1", "mode": "off"}, "Ivan")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM trades WHERE user='Ivan' AND auto IS NOT NULL").fetchone()[0], 0)
        # a typo is refused before anything changes
        self.assertIn("err=", league.post("/natjecanje/auto", {"all": "1", "mode": "tpsl", "tp": "abc"}, "Ivan"))

    def test_rule_without_positions(self):
        from league import auto
        body = league.page({}, "Filip")[1]
        self.assertIn("sve nove kupnje", body)
        self.assertIn("ok=", league.post("/natjecanje/auto", {"all": "1", "new": "1", "mode": "smart"}, "Filip"))
        con = store.connect()
        self.assertEqual(auto.get_rule(con, "Filip")["mode"], "smart")
        t = store.buy(con, "Filip", "MintA", "AAA", 50, 1.0, 1e6, mcap=1e6)
        self.assertIn("smart", con.execute("SELECT auto FROM trades WHERE id=?", (t,)).fetchone()[0])


class Dashboard(unittest.TestCase):
    """Podium, leaderboard extras, account history, chart data and the live refresh JSON."""
    def setUp(self):
        store.DB = os.path.join(tempfile.mkdtemp(), "league.db")
        os.environ["UI_USERS"] = "Ivan,Panda,Jure,Filip"

    def tearDown(self):
        os.environ.pop("UI_USERS", None)

    def test_history_streak_and_api(self):
        import json
        from league import history
        from ui import leaguedash
        con = store.connect()
        mk = lambda mints: {m: (2.0, 1e6, None, 2e6) for m in mints}  # noqa: E731
        a = store.buy(con, "Ivan", MINT, "SOL", 100, 1.0, 1e6, mcap=1e6)
        store.sell(con, "Ivan", a, 2.0, 1e6)                     # win
        b = store.buy(con, "Ivan", MINT, "SOL", 100, 1.0, 1e6, mcap=1e6)
        store.sell(con, "Ivan", b, 1.5, 1e6)                     # win
        store.buy(con, "Panda", MINT, "SOL", 50, 1.0, 1e6, mcap=1e6)
        self.assertEqual(leaguedash._streak(store.trades(con, "Ivan", "closed")), ("W", 2))
        self.assertEqual(history.snapshot(con, mk), 4)
        self.assertEqual(history.maybe_snapshot(con, mk), 0)     # not again within 15 min
        self.assertEqual(history.snapshot(con, lambda m: {}), 0)  # open positions, no price at all: skipped
        ser = history.series(con)
        self.assertGreater(ser["Ivan"][-1][1], 1100)
        self.assertEqual(history.value_at([(10, 1.0), (20, 2.0)], 15), 1.0)
        self.assertIsNone(history.value_at([(10, 1.0)], 5))
        d = leaguedash.compute(con, mk({MINT}))
        self.assertEqual(d["players"][0]["user"], "Ivan")
        self.assertEqual(d["players"][0]["rank"], 1)
        p = d["players"]
        p[0]["prev"], p[1]["prev"], p[2]["prev"], p[3]["prev"] = None, 1000, 1000, None
        self.assertEqual(leaguedash._tie_rank([1000, 1000], 1000), 1)
        j = json.loads(leaguedash.api(con, mk({MINT})))
        self.assertIn("eq:Ivan", j["v"])
        tid = store.trades(con, "Panda", "open")[0]["id"]
        self.assertIn(f"tp:{tid}", j["v"])                        # live PnL of Panda's open position
        self.assertEqual(len(j["chart"]["series"][0]["pts"]) >= 2, True)
        html = leaguedash.dashboard(con, mk({MINT}), "Ivan")
        for part in ("Ljestvica", "id=eqc", 'data-live="eq:Ivan"', "pl-Panda", "Svi tradeovi", "🔥 2 dobitna zaredom"):
            self.assertIn(part, html)


class RealTradesRemoved(unittest.TestCase):
    def test_not_in_menu(self):
        from ui import html
        hrefs = [p["href"] for _, pages in html.SECTIONS for p in pages]
        self.assertNotIn("/moji-tradeovi", hrefs)
        self.assertNotIn("Moji pravi tradeovi", html.page("x", "", "/"))


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
