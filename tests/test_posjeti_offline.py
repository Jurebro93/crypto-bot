"""19.11. (vlasnik: "Izbaci sve korisnike koji nisu posjetili aplikaciju zadnjih 5 dana bez da me pitaš išta
dodatno"): visits recorded from this deploy (league/posjeti.py), the one-time removal after 5 days of them
(league/izbaceni.py, ui/assistnotes.owner_izbaci_1911), what "removed" means at login, in the lists and on /korisnici,
and that it is reversible and deletes nothing. Offline.

    python3 -m unittest tests.test_posjeti_offline
"""
import importlib
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import izbaceni, members, posjeti, profiles, roles, store  # noqa: E402
from trade import settings  # noqa: E402
from ui import assistnotes, i18n, userroles  # noqa: E402

ENV = ("UI_PASSWORD", "UI_PASS_IVAN", "UI_PASS_JURE", "UI_PASS_PANDA", "UI_PASS_CLAUDE", "UI_USERS", "UI_ADMINS",
       "UI_TEST_PASSWORD", "UI_TEST_USER", "TRADE_OWNER", "DATA_DIR")
DAY = 86400
T0 = 1_800_000_000
PW = "novipw1novipw1"


class Base(unittest.TestCase):
    def setUp(self):
        self.old = {k: os.environ.get(k) for k in ENV}
        self.old_db = store.DB
        self.d = tempfile.mkdtemp()
        store.DB = os.path.join(self.d, "league.db")
        os.environ.update(DATA_DIR=self.d, UI_USERS="Ivan,Jure,Panda,autopilot-paper,Claude", UI_PASS_IVAN="ivanpw",
                          UI_PASS_JURE="jurepw", UI_PASS_PANDA="pandapw", UI_PASS_CLAUDE="gledam",
                          UI_TEST_PASSWORD="gledam")
        for k in ("UI_ADMINS", "TRADE_OWNER", "UI_PASSWORD", "UI_TEST_USER"):
            os.environ.pop(k, None)
        for m in (profiles, roles, posjeti, izbaceni):
            m.reset_cache()
        con = members.connect()
        try:
            tok = members.renew(con, "Jure")
            for n in ("Novi", "Stari"):
                members.register(con, tok, n, PW, PW, ["Ivan", "Jure", "Panda", "Claude"])
        finally:
            con.close()

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        store.DB = self.old_db
        for m in (profiles, roles, posjeti, izbaceni):
            m.reset_cache()
        shutil.rmtree(self.d, ignore_errors=True)


class Recording(Base):
    def test_which_paths_count(self):
        for p in ("/", "/tokens", "/korisnici", "/natjecanje/buy", "/postavke", "/pravi-trade"):
            self.assertTrue(posjeti.counts(p), p)
        for p in ("/favicon.ico", "/apple-touch-icon.png", "/site.webmanifest", "/static/landing/a.css",
                  "/img/t/abc.png", "/avatar/x.jpg", "/api/mcp/tokens", "/mcp", "/hook/kol", "/hook/x",
                  "/pravi-trade/api/stream", "/pravi-trade/api/tick", "/pravi-trade/static/app.js", "/sw.js",
                  "/healthz", "/autopilot/zivo", "/share/novosti.png", "/admin/export/x", "/cekamo-deploy"):
            self.assertFalse(posjeti.counts(p), p)

    def test_throttled_to_one_write_per_ten_minutes_and_days_counted(self):
        self.assertTrue(posjeti.note("Ivan", now=T0))
        self.assertFalse(posjeti.note("ivan", now=T0 + 60))           # memory only
        self.assertEqual(posjeti.visits()["ivan"]["last_ts"], T0 + 60)
        con = store.connect()
        self.assertEqual(con.execute("SELECT last_ts FROM posjeti WHERE name='Ivan'").fetchone()[0], T0)
        con.close()
        self.assertFalse(posjeti.note("Ivan", now=T0 + 599))
        self.assertTrue(posjeti.note("Ivan", now=T0 + 600))
        self.assertTrue(posjeti.note("Ivan", now=T0 + DAY))
        con = store.connect()
        r = con.execute("SELECT first_ts, last_ts, n_days FROM posjeti WHERE name='Ivan'").fetchone()
        con.close()
        self.assertEqual((r[0], r[1], r[2]), (T0, T0 + DAY, 2))

    def test_start_is_stored_once(self):
        self.assertIsNone(posjeti.started_at())
        self.assertEqual(posjeti.start(now=T0), T0)
        posjeti.reset_cache()                                          # a restart / a deploy
        self.assertEqual(posjeti.start(now=T0 + 5 * DAY), T0)
        self.assertEqual(posjeti.started_at(), T0)
        posjeti.note("Ivan", now=T0 + 10)
        self.assertEqual(posjeti.started_at(), T0)

    def test_never_raises(self):
        store.DB = os.path.join(self.d, "nema", "dir", "league.db")
        self.assertFalse(posjeti.note("Ivan"))
        self.assertIsNone(posjeti.start())


class Order(Base):
    def setUp(self):
        super().setUp()
        posjeti.start(now=T0)
        roles.set_role("Panda", "admin", "Jure")                       # another admin: removed too if absent
        con = store.connect()
        for u in ("Ivan", "Panda", "Novi", "Stari"):
            store.account(con, u)
            con.execute("INSERT INTO trades (user, token, symbol, opened_ts, status, size_usd) VALUES (?,?,?,?,?,?)",
                        (u, "tok", "TOK", T0, "open", 10))
        con.commit()
        con.close()
        self.now = T0 + 6 * DAY
        posjeti.note("Ivan", now=self.now - (4 * DAY + 23 * 3600))     # inside the window
        posjeti.note("Novi", now=T0 + 10)                              # older than 5 days

    def counts(self):
        con = store.connect()
        try:
            return [con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("accounts", "trades")]
        finally:
            con.close()

    def test_not_before_five_days(self):
        self.assertEqual(izbaceni.run_order(now=T0 + 5 * DAY - 1), (None, False))
        self.assertEqual(izbaceni.rows(), [])

    def test_removes_exactly_the_inactive_once(self):
        before = self.counts()
        res, fresh = izbaceni.run_order(now=self.now)
        self.assertTrue(fresh)
        self.assertEqual(sorted(res["izbaceni"]), ["Novi", "Panda", "Stari"])
        self.assertEqual(res["ostaje"], 4)                              # Ivan, Jure, autopilot-paper, Claude
        for n in ("Novi", "Panda", "Stari"):
            self.assertTrue(izbaceni.is_out(n))
        for n in ("Ivan", "Jure", "autopilot-paper", "Claude"):
            self.assertFalse(izbaceni.is_out(n))
        self.assertEqual(store.users(), ["Ivan", "Jure", "autopilot-paper", "Claude"])
        self.assertIsNone(members.verify("Novi", PW))
        self.assertTrue(members.exists("Stari", with_deleted=True))    # name stays taken
        self.assertEqual(self.counts(), before)                        # nothing deleted
        # once: later inactivity changes nothing
        res2, fresh2 = izbaceni.run_order(now=T0 + 30 * DAY)
        self.assertFalse(fresh2)
        self.assertEqual(res2, res)
        self.assertFalse(izbaceni.is_out("Ivan"))

    def test_exactly_at_start_plus_five_days(self):
        posjeti.note("Panda", now=T0 + 1)
        res, _ = izbaceni.run_order(now=T0 + 5 * DAY)
        self.assertEqual(sorted(res["izbaceni"]), ["Stari"])           # Novi at T0+10, Panda at T0+1: inside

    def test_owner_wrapper_logs_and_marks(self):
        tcon = settings.connect(os.path.join(self.d, "trade.db"))
        assistnotes.ensure(tcon)
        self.assertFalse(assistnotes.owner_izbaci_1911(tcon, now=T0 + DAY))
        self.assertIsNone(settings.raw(tcon).get(assistnotes.IZBACI_KEY))
        self.assertTrue(assistnotes.owner_izbaci_1911(tcon, now=self.now))
        raw = settings.raw(tcon)
        self.assertEqual(sorted(raw[assistnotes.IZBACI_KEY]["izbaceni"]), ["Novi", "Panda", "Stari"])
        log = [x for x in raw["applied_log"] if x["key"] == "korisnici:izbaci_neaktivne_1911"]
        self.assertEqual(len(log), 1)
        self.assertIn("Novi", log[0]["new"])
        self.assertTrue(assistnotes.owner_izbaci_1911(tcon, now=self.now + DAY))
        self.assertEqual(len([x for x in settings.raw(tcon)["applied_log"]
                              if x["key"] == "korisnici:izbaci_neaktivne_1911"]), 1)
        tcon.close()

    def test_restore_brings_both_back(self):
        con = store.connect()
        con.execute("CREATE TABLE IF NOT EXISTS follows (id INTEGER PRIMARY KEY, user TEXT, active INTEGER DEFAULT 1, "
                    "stopped INTEGER)")
        con.execute("INSERT INTO follows (user, active) VALUES ('Panda', 1)")
        con.execute("INSERT INTO follows (user, active, stopped) VALUES ('Panda', 0, 5)")   # stopped by himself
        con.commit()
        con.close()
        izbaceni.run_order(now=self.now)
        con = izbaceni.connect()
        self.assertEqual([r[0] for r in con.execute("SELECT active FROM follows ORDER BY id")], [0, 0])
        izbaceni.restore(con, "panda", "Jure")
        izbaceni.restore(con, "Novi", "Jure")
        self.assertEqual([r[0] for r in con.execute("SELECT active FROM follows ORDER BY id")], [1, 0])
        with self.assertRaises(ValueError):
            izbaceni.restore(con, "Ivan", "Jure")
        con.close()
        self.assertFalse(izbaceni.is_out("Panda"))
        self.assertEqual(members.verify("Novi", PW), "Novi")
        self.assertIn("Panda", store.users())
        self.assertIn("Novi", store.users())
        self.assertNotIn("Stari", store.users())


class Http(Base):
    def setUp(self):
        super().setUp()
        import run_ui
        self.ru = importlib.reload(run_ui)
        self.srv = run_ui.ThreadingHTTPServer(("127.0.0.1", 0), run_ui.Handler)
        self.srv.verbose = False
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a):
                return None
        self.op = urllib.request.build_opener(NoRedirect)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def call(self, path, data=None, cookie="", method=None):
        headers = {"Cookie": cookie} if cookie else {}
        if data is not None:
            headers["Origin"] = self.base
            sess = cookie.split("=", 1)[1] if cookie.startswith(self.ru.COOKIE + "=") else ""
            data = {**data, "_csrf": self.ru.csrf_token(sess)}
        req = urllib.request.Request(self.base + path, data=urllib.parse.urlencode(data).encode() if data else None,
                                     headers=headers, method=method)
        try:
            r = self.op.open(req)
        except urllib.error.HTTPError as e:
            r = e
        return r.code, r.headers, r.read().decode("utf-8", "replace")

    def login(self, name, pw):
        code, hdr, body = self.call("/prijava", {"name": name, "pw": pw, "next": "/postavke"})
        return hdr["Set-Cookie"].split(";")[0] if code == 303 else None

    def test_visits_over_http(self):
        ivan = self.ru.COOKIE + "=" + self.ru.make_cookie("Ivan")
        for p in ("/favicon.ico", "/img/t/x.png", "/api/mcp/tokens", "/pravi-trade/api/tick"):
            self.call(p, cookie=ivan)
        self.call("/hook/kol", {"x": "1"}, cookie=ivan)
        self.assertNotIn("ivan", posjeti.visits())
        self.call("/postavke", cookie=ivan)
        self.assertIn("ivan", posjeti.visits())
        self.assertIsNotNone(posjeti.started_at())
        self.assertNotIn("panda", posjeti.visits())
        self.assertIsNotNone(self.login("Panda", "pandapw"))       # a login is a visit
        self.assertIn("panda", posjeti.visits())

    def test_removed_cannot_log_in_and_restore(self):
        panda = self.login("Panda", "pandapw")
        novi = self.login("Novi", PW)
        jure = self.login("Jure", "jurepw")
        self.assertEqual(self.call("/postavke", cookie=panda)[0], 200)
        con = izbaceni.connect()
        izbaceni.remove(con, "Panda", izbaceni.WHY, izbaceni.BY)
        izbaceni.remove(con, "Novi", izbaceni.WHY, izbaceni.BY)
        con.close()
        self.assertEqual(self.call("/postavke", cookie=panda)[0], 401)    # the existing cookie stops
        self.assertEqual(self.call("/postavke", cookie=novi)[0], 401)
        code, _, body = self.call("/prijava", {"name": "Panda", "pw": "pandapw"})
        self.assertEqual(code, 401)
        self.assertIn("Pogrešno ime ili lozinka.", body)
        self.assertIsNone(self.login("Novi", PW))
        self.assertEqual(self.ru.check_password("Panda", "pandapw"), (False, None))
        code, _, body = self.call("/korisnici", cookie=jure)
        self.assertIn("Izbačeni (2)", body)
        self.assertIn("/korisnici/vrati", body)
        code, hdr, _ = self.call("/korisnici/vrati", {"name": "Panda"}, jure)
        self.assertEqual(code, 303)
        self.assertIn("ok=", hdr["Location"])
        self.call("/korisnici/vrati", {"name": "Novi"}, jure)
        self.assertIsNotNone(self.login("Panda", "pandapw"))
        self.assertIsNotNone(self.login("Novi", PW))
        # a basic user cannot restore
        con = izbaceni.connect()
        izbaceni.remove(con, "Stari", izbaceni.WHY, izbaceni.BY)
        con.close()
        ivan = self.login("Ivan", "ivanpw")
        self.assertEqual(self.call("/korisnici/vrati", {"name": "Stari"}, ivan)[0], 403)
        self.assertTrue(izbaceni.is_out("Stari"))


class Page(Base):
    def en(self, html):
        tok = i18n.LANG.set("en")
        try:
            with mock.patch.object(i18n, "_start_worker"), mock.patch.object(i18n, "_queue") as q:
                out = i18n.translate(html)
            return out, [c.args[0] for c in q.call_args_list]
        finally:
            i18n.LANG.reset(tok)

    def render(self):
        return userroles.page({}, "Jure", ["Ivan", "Jure", "Panda"], "Claude")[1]

    def test_before_and_after(self):
        posjeti.start(now=T0)
        posjeti.note("Ivan", now=T0 + 100)
        with mock.patch("time.time", return_value=T0 + 3 * 3600):
            html = self.render()
        self.assertIn("Posjeti se bilježe od 15.01.2027. 20.01.2027. alat sam izbacuje sve koji u tih 5 dana nisu "
                      "otvorili aplikaciju (tvoj nalog 19.11.).", html)
        self.assertIn("Zadnji posjet: <b>prije 2 h</b>", html)
        self.assertIn("Zadnji posjet: <b>nema zapisa</b>", html)
        self.assertNotIn("Izbačeni", html)
        izbaceni.run_order(now=T0 + 5 * DAY)
        html = self.render()
        self.assertIn("Izbačeno 3 korisnika 20.01.2027. (bez posjeta 5 dana).", html)   # Panda, Novi, Stari
        self.assertIn("Izbačeni (3)", html)
        self.assertNotIn("Posjeti se bilježe", html)
        users = html.split("Izbačeni (")[0]
        for n in ("Panda", "Novi", "Stari"):
            self.assertNotIn(f">{n}<", users)
        self.assertIn(">Ivan<", users)
        self.assertIn(">Jure<", users)

    def test_english_and_escaping(self):
        posjeti.start(now=T0)
        con = izbaceni.connect()
        izbaceni.remove(con, "<img src=x>", "a<b>c", "Jure")
        izbaceni.remove(con, "Stari", izbaceni.WHY, izbaceni.BY)
        con.close()
        html = self.render()
        self.assertNotIn("<img src=x>", html)
        self.assertIn("&lt;img src=x&gt;", html)
        self.assertNotIn("a<b>c", html)
        with mock.patch("time.time", return_value=T0 + 60):
            html = self.render()
        out, missing = self.en(html)
        mine = [m for m in missing if any(w in m for w in ("posjet", "Izbačen", "Vrati", "bilježe", "zapisa",
                                                           "prije", "obrisano", "nalog"))]
        self.assertEqual(mine, [])
        for w in ("Last visit", "Removed (2)", "Restore", "Visits are recorded since"):
            self.assertIn(w, out)
        izbaceni.run_order(now=T0 + 5 * DAY)
        out, missing = self.en(self.render())
        self.assertIn("users removed on", out)


if __name__ == "__main__":
    unittest.main()
