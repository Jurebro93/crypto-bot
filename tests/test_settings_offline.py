"""⚙️ Postavke (password, sessions, picture, profile, delete) and the English version (ui/i18n). No network."""
import base64
import importlib
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["I18N_OFF"] = "1"

from league import members, profiles, store  # noqa: E402
from ui import i18n  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 500


def data_url(raw=JPEG):
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode()


class Profiles(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        store.DB = os.path.join(d, "league.db")
        os.environ["DATA_DIR"] = d
        profiles.reset_cache()

    def test_password_override_and_sessions(self):
        self.assertIsNone(profiles.check_password("Ivan", "x"))          # nothing set: the Render one counts
        profiles.set_password("Ivan", "novatajna")
        self.assertTrue(profiles.check_password("ivan", "novatajna"))
        self.assertFalse(profiles.check_password("Ivan", "stara"))
        row = sqlite_row("SELECT pw_hash FROM profiles WHERE name='Ivan'")
        self.assertNotIn("novatajna", row[0])
        after = profiles.get("Ivan")["sessions_after"]
        self.assertFalse(profiles.session_ok("Ivan", after - 5))          # older logins stop working
        self.assertTrue(profiles.session_ok("Ivan", after))
        with self.assertRaisesRegex(ValueError, "6 znakova"):
            profiles.validate_new("123", "123")
        with self.assertRaisesRegex(ValueError, "podudaraju"):
            profiles.validate_new("tajna12", "tajna13")

    def test_member_password_and_delete(self):
        con = members.connect()
        tok = members.standing(con)
        members.register(con, tok, "Marko", "tajna12", "tajna12")
        con.close()
        profiles.set_member_password("Marko", "drugatajna")
        self.assertIsNone(members.verify("Marko", "tajna12"))
        self.assertEqual(members.verify("Marko", "drugatajna"), "Marko")
        profiles.save_avatar("Marko", data_url())
        self.assertIn("Marko", store.users())
        profiles.delete_member("Marko")
        self.assertNotIn("Marko", store.users())                         # off the board
        self.assertIsNone(members.verify("Marko", "drugatajna"))         # can't log in
        self.assertIsNone(profiles.avatar_url("Marko"))
        con = members.connect()
        with self.assertRaisesRegex(ValueError, "zauzeto"):              # nobody inherits the old trades
            members.register(con, members.standing(con), "marko", "tajna12", "tajna12")
        con.close()

    def test_profile_and_avatar(self):
        profiles.save_profile("Ivan", {"email": "ivan@primjer.com", "email_report": "1", "bio": "  volim   meme  ",
                                       "s_x": "https://x.com/ivan_sol", "s_telegram": "@ivantg", "s_web": "ivan.hr"})
        self.assertEqual(profiles.social("Ivan"), {"x": "ivan_sol", "telegram": "ivantg", "web": "https://ivan.hr"})
        self.assertEqual(profiles.get("Ivan")["bio"], "volim meme")
        self.assertEqual(profiles.report_emails(), ["ivan@primjer.com"])
        self.assertEqual(profiles.links("Ivan")[0][2], "https://x.com/ivan_sol")
        for bad in ({"email": "nije-mail"}, {"s_x": "ime s razmakom"}, {"s_web": "javascript:alert(1)"}):
            with self.assertRaises(ValueError):
                profiles.save_profile("Ivan", bad)
        profiles.save_avatar("Ivan", data_url())
        url = profiles.avatar_url("Ivan")
        self.assertRegex(url, r"^/avatar/[0-9a-f]{20}\.jpg\?v=\d+$")
        self.assertTrue(profiles.avatar_path(url.split("/")[-1].split("?")[0]))
        self.assertIsNone(profiles.avatar_path("../league.db"))
        with self.assertRaisesRegex(ValueError, "nije slika"):
            profiles.save_avatar("Ivan", data_url(b"<svg>" + b"0" * 50))
        with self.assertRaisesRegex(ValueError, "prevelika"):
            profiles.save_avatar("Ivan", data_url(JPEG + b"0" * 400_000))
        from ui import leaguedash
        self.assertIn("background-image:url(/avatar/", leaguedash._av("Ivan", "#123"))
        self.assertIn(">J<", leaguedash._av("Jure", "#123"))
        self.assertIn("x.com/ivan_sol", leaguedash._about("Ivan"))
        profiles.remove_avatar("Ivan")
        self.assertIsNone(profiles.avatar_url("Ivan"))

    def test_settings_page(self):
        from ui import settings
        _, body = settings.page({}, "Ivan", "env", "hr")
        for part in ("/postavke/lozinka", "/postavke/slika", "/postavke/profil", "odjava-svugdje", "/jezik?l=en"):
            self.assertIn(part, body)
        self.assertNotIn("/postavke/obrisi", body)                       # server players are removed on the server
        self.assertIn("/postavke/obrisi", settings.page({}, "Marko", "member", "hr")[1])
        viewer = settings.page({}, None, "viewer", "hr")[1]
        self.assertIn("/jezik?l=en", viewer)
        self.assertNotIn("/postavke/lozinka", viewer)


def sqlite_row(sql):
    import sqlite3
    con = sqlite3.connect(store.DB)
    try:
        return con.execute(sql).fetchone()
    finally:
        con.close()


class Translate(unittest.TestCase):
    def setUp(self):
        i18n._static = {"Kupi <1/> sada": "Buy <1/> now", "Natjecanje": "Competition", "prije {0} min": "{0} min ago",
                        "Ovo je <1>vrlo važno</1> za sve": "This is <1>very important</1> for everyone",
                        "Objašnjenje": "Explanation", "Kopirano": "Copied", "Pokvareno <1/> ovdje": "Broken here"}
        i18n._auto = {}
        i18n._pending.clear()
        self.tok = i18n.LANG.set("en")

    def tearDown(self):
        i18n.LANG.reset(self.tok)
        i18n._static = i18n._auto = None

    def test_segments(self):
        h = ('<div><p>Kupi <a href="/t/x">BONK</a> sada</p><h2>Natjecanje</h2><td>prije 12 min</td>'
             '<p>Ovo je <b class=x>vrlo važno</b> za sve</p><span class=tip aria-label="Objašnjenje">ⓘ</span>'
             "<script>var a='Kopirano';</script><pre>Natjecanje</pre><textarea>Natjecanje</textarea>"
             '<p>Pokvareno <a href=/x>link</a> ovdje</p><b translate=no>Natjecanje</b></div>')
        out = i18n.translate(h)
        self.assertIn('<p>Buy <a href="/t/x">BONK</a> now</p>', out)
        self.assertIn("<h2>Competition</h2>", out)
        self.assertIn("<td>12 min ago</td>", out)
        self.assertIn("<p>This is <b class=x>very important</b> for everyone</p>", out)
        self.assertIn('aria-label="Explanation"', out)
        self.assertIn("var a='Copied'", out)
        self.assertIn("<pre>Natjecanje</pre><textarea>Natjecanje</textarea>", out)   # left alone
        self.assertIn("<b translate=no>Natjecanje</b>", out)
        self.assertIn("Pokvareno <a href=/x>link</a> ovdje", out)       # translation lost the link: kept Croatian
        self.assertIn("BONK", i18n._pending.keys() | {"BONK"})

    def test_page_language(self):
        self.assertIn("<html lang=en>", i18n.translate("<!doctype html><html lang=hr><body><p>Natjecanje</p></body></html>"))

    def test_queue_rules(self):
        i18n.translate("<p>Nešto novo za prevesti 7 puta</p><p>BONK</p><p>$WIF</p>"
                       "<p>9txCZaqYaQ62nFVcEWhosWx3vTMcJMFP5YYXQ5yhBAGS</p>")
        self.assertEqual(list(i18n._pending), ["Nešto novo za prevesti {0} puta"])   # tickers, addresses: never sent

    def test_croatian_untouched(self):
        i18n.LANG.set("hr")
        h = "<p>Natjecanje</p>"
        self.assertIs(i18n.translate(h), h)

    def test_worker_batch(self):
        d = tempfile.mkdtemp()
        os.environ["DATA_DIR"] = d
        i18n._pending.update({"Kupi <1/> odmah": 0, "Dobit {0} $": 0})
        n = i18n.run_once(lambda keys: ["Buy <1/> now" if "Kupi" in k else "Lost the number" for k in keys])
        self.assertEqual(n, 1)                                            # the one that dropped {0} is refused
        with open(os.path.join(d, "i18n", "en.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"Kupi <1/> odmah": "Buy <1/> now"})

    def test_dictionaries_are_sound(self):
        i18n._static = i18n._auto = None
        st, _ = i18n._load()
        self.assertGreater(len(st), 200)
        for k, v in st.items():
            self.assertEqual(sorted(i18n._PH.findall(k)), sorted(i18n._PH.findall(v)), k)
        with open(os.path.join(i18n.HERE, "i18n_seed.json"), encoding="utf-8") as f:
            self.assertGreater(len(json.load(f)), 1000)


class Http(unittest.TestCase):
    def test_flow(self):
        d = tempfile.mkdtemp()
        store.DB = os.path.join(d, "league.db")
        os.environ.update(DATA_DIR=d, UI_PASSWORD="shared", UI_PASS_IVAN="ivanpw", UI_USERS="Ivan,Jure")
        profiles.reset_cache()
        import run_ui
        importlib.reload(run_ui)
        srv = run_ui.ThreadingHTTPServer(("127.0.0.1", 0), run_ui.Handler)
        srv.verbose = False
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a):
                return None
        op = urllib.request.build_opener(NoRedirect)

        def call(path, data=None, cookie=""):
            req = urllib.request.Request(base + path, data=urllib.parse.urlencode(data).encode() if data else None,
                                         headers={"Cookie": cookie} if cookie else {})
            try:
                r = op.open(req)
            except urllib.error.HTTPError as e:
                r = e
            return r.code if hasattr(r, "code") else r.status, r.headers, r.read().decode("utf-8", "replace")

        def login(pw):
            code, hdr, _ = call("/prijava", {"name": "Ivan", "pw": pw, "next": "/postavke"})
            self.assertEqual(code, 303, pw)
            return hdr["Set-Cookie"].split(";")[0]
        try:
            c1 = login("ivanpw")
            code, _, body = call("/postavke", cookie=c1)
            self.assertEqual(code, 200)
            self.assertIn("⚙️ Postavke", body)
            self.assertIn('href="/postavke"', body)                        # menu item
            self.assertIn("/jezik?l=en", body)                             # switch next to Odjava
            time.sleep(1.1)
            c2 = login("ivanpw")                                           # a second device
            code, hdr, _ = call("/postavke/lozinka", {"old": "krivo", "new": "novatajna", "new2": "novatajna"}, c1)
            self.assertIn("err=", hdr["Location"])
            time.sleep(1.1)
            code, hdr, _ = call("/postavke/lozinka", {"old": "ivanpw", "new": "novatajna", "new2": "novatajna"}, c1)
            self.assertIn("ok=", hdr["Location"])
            c1 = hdr["Set-Cookie"].split(";")[0]                           # this device stays logged in
            self.assertEqual(call("/postavke", cookie=c1)[0], 200)
            self.assertEqual(call("/postavke", cookie=c2)[0], 401)          # the other one is logged out
            self.assertEqual(run_ui.check_password("Ivan", "ivanpw"), (False, None))   # Render password replaced
            self.assertEqual(run_ui.check_password("Ivan", "novatajna"), (True, "Ivan"))
            # picture + profile
            code, hdr, _ = call("/postavke/slika", {"data": data_url()}, c1)
            self.assertIn("ok=", hdr["Location"])
            url = profiles.avatar_url("Ivan")
            code, hdr, body = call(url, cookie=c1)
            self.assertEqual((code, hdr["Content-Type"]), (200, "image/jpeg"))
            self.assertEqual(call(url)[0], 401)                            # pictures only for logged-in users
            # language: cookie + stored, survives a new login
            code, hdr, _ = call("/jezik?l=en&next=/postavke", cookie=c1)
            self.assertEqual(hdr["Location"], "/postavke")
            self.assertIn("cb_lang=en", hdr["Set-Cookie"])
            self.assertEqual(profiles.get("Ivan")["lang"], "en")
            code, _, body = call("/postavke", cookie=c1 + "; cb_lang=en")
            self.assertIn("<html lang=en>", body)
            self.assertIn("Settings", body)
            self.assertIn("Change password", body)
            code, hdr, _ = call("/prijava", {"name": "Ivan", "pw": "novatajna", "next": "/"})
            self.assertIn("cb_lang=en", " ".join(hdr.get_all("Set-Cookie")))
            # public page is never run through the translator
            code, _, body = call("/hr", cookie="cb_lang=en")
            self.assertIn("lang=hr", body)
        finally:
            srv.shutdown()
            for k in ("UI_PASSWORD", "UI_PASS_IVAN", "UI_USERS"):
                os.environ.pop(k, None)


if __name__ == "__main__":
    unittest.main()
