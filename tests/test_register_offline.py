"""Self-registration through an invite link: link rules, password hashing, login, the competition board. No network."""
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import members, store  # noqa: E402


class Register(unittest.TestCase):
    def setUp(self):
        store.DB = os.path.join(tempfile.mkdtemp(), "league.db")
        os.environ.pop("UI_ADMINS", None)

    def test_links_and_rules(self):
        con = members.connect()
        tok = members.standing(con, "Jure")
        self.assertEqual(members.standing(con), tok)                     # same link until renewed
        self.assertEqual(members.register(con, tok, "Marko", "tajna12", "tajna12", ["Ivan"]), "Marko")
        self.assertEqual(members.register(con, tok, "Ana", "tajna12", "tajna12"), "Ana")   # reusable
        for args, why in [(("Ivan", "tajna12", "tajna12"), "zauzeto"), (("marko", "tajna12", "tajna12"), "zauzeto"),
                          (("bot", "tajna12", "tajna12"), "zauzeto"), (("a b", "tajna12", "tajna12"), "slova"),
                          (("Luka", "123", "123"), "6 znakova"), (("Luka", "tajna12", "tajna13"), "podudaraju")]:
            with self.assertRaisesRegex(ValueError, why):
                members.register(con, tok, *args, taken=["Ivan"])
        new = members.renew(con)
        with self.assertRaisesRegex(ValueError, "ne vrijedi"):
            members.register(con, tok, "Luka", "tajna12", "tajna12")     # old link stopped
        one = members.single(con)
        members.register(con, one, "Luka", "tajna12", "tajna12")
        with self.assertRaisesRegex(ValueError, "ne vrijedi"):
            members.register(con, one, "Pero", "tajna12", "tajna12")     # single-use
        self.assertTrue(members.valid(con, new))
        self.assertEqual(members.verify("marko", "tajna12"), "Marko")
        self.assertIsNone(members.verify("Marko", "kriva"))
        row = con.execute("SELECT hash FROM members WHERE name='Marko'").fetchone()[0]
        self.assertNotIn("tajna12", row)                                 # only the hash is kept
        self.assertEqual(store.users()[-3:], ["Marko", "Ana", "Luka"])  # on the board, after the server's list
        self.assertAlmostEqual(store.account(con, "Ana")["cash"], store.START_USD)
        con.close()

    def test_viewer_is_no_player(self):
        old = {k: os.environ.get(k) for k in ("UI_USERS", "UI_PASS_IVAN", "UI_PASS_CLAUDE")}
        os.environ.update(UI_USERS="Ivan,Claude,Mario", UI_PASS_IVAN="x")
        os.environ.pop("UI_PASS_CLAUDE", None)
        try:
            self.assertEqual(store.env_users(), ["Ivan", "Mario"])
            self.assertEqual(store.missing_passwords(), ["Mario"])     # the view-only account is not listed
            os.environ["UI_PASS_CLAUDE"] = "y"                        # with its own password it plays
            self.assertIn("Claude", store.env_users())
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def test_http_flow(self):
        os.environ.update(UI_PASSWORD="shared", UI_PASS_IVAN="ivanpw")
        import importlib
        import run_ui
        importlib.reload(run_ui)
        con = members.connect()
        tok = members.standing(con)
        con.close()
        srv = run_ui.ThreadingHTTPServer(("127.0.0.1", 0), run_ui.Handler)
        srv.verbose = False
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a):
                return None
        op = urllib.request.build_opener(NoRedirect)

        def call(path, data=None):
            try:
                r = op.open(urllib.request.Request(base + path, data=urllib.parse.urlencode(data).encode()
                                                   if data else None))
            except urllib.error.HTTPError as e:
                r = e
            return r.code if hasattr(r, "code") else r.status, r.headers, r.read().decode()

        code, _, body = call(f"/registracija?k={tok}")                   # open without logging in
        self.assertEqual(code, 200)
        self.assertIn("name=pw2", body)
        self.assertIn("ne vrijedi", call("/registracija?k=krivo")[2])
        self.assertIn("name=email", body)
        code, _, body = call("/registracija", {"k": tok, "name": "Marko", "pw": "tajna12", "pw2": "tajna12"})
        self.assertEqual(code, 400)                                       # 3.11.: e-mail is required
        self.assertIn("e-mail", body)
        code, _, body = call("/registracija", {"k": tok, "name": "Ivan", "pw": "tajna12", "pw2": "tajna12",
                                               "email": "ivan@mail.hr"})
        self.assertEqual(code, 400)                                       # a server player's name is taken
        self.assertIn("zauzeto", body)
        code, hdr, _ = call("/registracija", {"k": tok, "name": "Marko", "pw": "tajna12", "pw2": "tajna12",
                                              "email": "marko@mail.hr"})
        self.assertEqual(code, 303)
        from league import profiles
        self.assertEqual(profiles.get("Marko")["email"], "marko@mail.hr")   # saved to the profile
        self.assertTrue(hdr["Location"].startswith("/natjecanje?ok="))
        cookie = hdr["Set-Cookie"].split(";")[0]
        self.assertEqual(run_ui.cookie_user(cookie.split("=", 1)[1]), (True, "Marko"))
        self.assertEqual(run_ui.check_password("marko", "tajna12"), (True, "Marko"))
        self.assertEqual(run_ui.check_password("Marko", "x"), (False, None))
        code, hdr, _ = call("/prijava", {"name": "Marko", "pw": "tajna12", "next": "/natjecanje"})
        self.assertEqual((code, hdr["Location"]), (303, "/natjecanje"))
        srv.shutdown()

    def test_invite_box_and_admins(self):
        from ui import register
        from league import roles
        roles.reset_cache()
        self.assertEqual(register.invite_box("Ivan"), "")                 # invites: admins only (league/roles)
        self.assertIn("/registracija?k=", register.invite_box("Jure"))   # TRADE_OWNER default = admin
        self.assertEqual(register.invite_box(None), "")                  # view-only: no box
        os.environ["UI_ADMINS"] = "Jure"
        self.assertEqual(register.invite_box("Ivan"), "")
        self.assertIn("err=", register.post_invite("/natjecanje/pozivnica/novi", {}, "Ivan"))
        self.assertIn("ok=", register.post_invite("/natjecanje/pozivnica/jednokratni", {}, "Jure"))
        self.assertIn("1 jednokratnih čeka", register.invite_box("Jure"))
        self.assertIn("/zahtjevi#pozivnice", register.invite_box("Jure"))
        os.environ.pop("UI_ADMINS")


if __name__ == "__main__":
    unittest.main()
