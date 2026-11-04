"""User roles (league/roles.py): defaults, admin page, and that the SERVER refuses pages and actions per role."""
import importlib
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import members, profiles, roles, store  # noqa: E402

ENV = ("UI_PASSWORD", "UI_PASS_IVAN", "UI_PASS_JURE", "UI_USERS", "UI_ADMINS", "UI_TEST_PASSWORD", "TRADE_OWNER")


class Roles(unittest.TestCase):
    def setUp(self):
        self.old = {k: os.environ.get(k) for k in ENV}
        d = tempfile.mkdtemp()
        store.DB = os.path.join(d, "league.db")
        os.environ.update(DATA_DIR=d, UI_USERS="Ivan,Jure", UI_PASS_IVAN="ivanpw", UI_PASS_JURE="jurepw",
                          UI_PASSWORD="shared", UI_TEST_PASSWORD="gledam")
        os.environ.pop("UI_ADMINS", None)
        os.environ.pop("TRADE_OWNER", None)
        profiles.reset_cache()
        roles.reset_cache()

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        roles.reset_cache()

    def test_defaults_and_changes(self):
        self.assertEqual(roles.role("Jure"), "admin")          # owner by default
        self.assertEqual(roles.role("ivan"), "osnovni")        # UI_USERS player too (Nicholas 3.11.)
        self.assertEqual(roles.role("Novi"), "osnovni")        # registered via invite
        self.assertEqual(roles.role(None), "osnovni")          # shared password
        with self.assertRaises(ValueError):
            roles.set_role("Novi", "admin", "Ivan")            # only admins change roles
        with self.assertRaises(ValueError):
            roles.set_role("Jure", "osnovni", "Jure")          # the server's admin can't be locked out
        roles.set_role("Novi", "prijatelj", "Jure")
        self.assertEqual(roles.role("novi"), "prijatelj")
        os.environ["UI_ADMINS"] = "Ivan"
        self.assertEqual(roles.role("Ivan"), "admin")
        self.assertEqual(roles.role("Jure"), "osnovni")
        self.assertEqual(roles.deny_get("/usage", "prijatelj"), "admin")
        self.assertIsNone(roles.deny_get("/tokens", "osnovni"))
        self.assertEqual(roles.deny_get("/izvjestaj/raw/x", "osnovni"), "prijatelj")
        self.assertEqual(roles.deny_post("/run/wallets", "prijatelj"), "admin")
        self.assertIsNone(roles.deny_post("/natjecanje/buy", "osnovni"))

    def test_http(self):
        import run_ui
        importlib.reload(run_ui)
        con = members.connect()
        try:
            tok = members.renew(con, "Jure")
            members.register(con, tok, "Novi", "novipw1novipw1", "novipw1novipw1", ["Ivan", "Jure", "Claude"])
        finally:
            con.close()
        srv = run_ui.ThreadingHTTPServer(("127.0.0.1", 0), run_ui.Handler)
        srv.verbose = False
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a):
                return None
        op = urllib.request.build_opener(NoRedirect)

        def call(path, data=None, cookie=""):
            headers = {"Cookie": cookie} if cookie else {}
            if data is not None:   # like a browser: same-site Origin and the page JS's form token (4.11.)
                headers["Origin"] = base
                sess = cookie.split("=", 1)[1] if cookie.startswith(run_ui.COOKIE + "=") else ""
                data = {**data, "_csrf": run_ui.csrf_token(sess)}
            req = urllib.request.Request(base + path, data=urllib.parse.urlencode(data).encode() if data else None,
                                         headers=headers)
            try:
                r = op.open(req)
            except urllib.error.HTTPError as e:
                r = e
            return r.code, r.headers, r.read().decode("utf-8", "replace")

        def login(name, pw):
            code, hdr, _ = call("/prijava", {"name": name, "pw": pw, "next": "/postavke"})
            self.assertEqual(code, 303, name)
            return hdr["Set-Cookie"].split(";")[0]
        try:
            roles.set_role("Ivan", "prijatelj", "Jure")
            novi, ivan, jure, viewer = (login("Novi", "novipw1novipw1"), login("Ivan", "ivanpw"), login("Jure", "jurepw"),
                                        login("Claude", "gledam"))
            # basic user: core pages yes, spend/admin/AI-cost pages and paid actions no
            for p in ("/korisnici", "/usage", "/analitika", "/zahtjevi", "/outputs", "/learn", "/criteria",
                      "/izvjestaj", "/nas-token", "/whatsapp"):
                code, _, body = call(p, cookie=novi)
                self.assertEqual(code, 403, p)
                self.assertIn("Ovo nije za tvoj račun", body)
            for p in ("/run/wallets", "/korisnici/uloga", "/natjecanje/pozivnica/nova", "/paper/izlaz",
                      "/nas-token/rpc", "/prijedlozi/status"):
                self.assertEqual(call(p, {"x": "1"}, novi)[0], 403, p)
            code, hdr, body = call("/postavke", cookie=novi)
            self.assertEqual(code, 200)
            self.assertIn("cb_r=osnovni", " ".join(hdr.get_all("Set-Cookie")))
            self.assertIn("cb_nm=1", " ".join(hdr.get_all("Set-Cookie")))   # no e-mail yet: box on every page
            profiles._set("Novi", email="novi@mail.hr")
            code, hdr, _ = call("/tokens", cookie=novi + "; cb_nm=1")
            self.assertIn("cb_nm=;", " ".join(hdr.get_all("Set-Cookie") or []))
            self.assertIn("r-adm", body)                                   # admin menu items marked for hiding
            self.assertEqual(call("/usage", cookie=viewer)[0], 403)         # view-only account is basic too
            self.assertEqual(call("/usage", cookie="x")[0], 401)
            # friend: friend pages yes, admin no
            self.assertEqual(call("/korisnici", cookie=ivan)[0], 403)
            self.assertEqual(call("/run/wallets", {"x": "1"}, ivan)[0], 403)
            self.assertNotEqual(call("/whatsapp", cookie=ivan)[0], 403)
            # admin sees the page and changes a role, which the server applies at once
            code, _, body = call("/korisnici", cookie=jure)
            self.assertEqual(code, 200)
            self.assertIn("Novi", body)
            self.assertIn("stalno, postavljeno na serveru", body)
            code, hdr, _ = call("/korisnici/uloga", {"name": "Novi", "role": "prijatelj"}, jure)
            self.assertIn("ok=", hdr["Location"])
            self.assertNotEqual(call("/whatsapp", cookie=novi)[0], 403)
            code, hdr, _ = call("/korisnici/uloga", {"name": "Jure", "role": "osnovni"}, jure)
            self.assertIn("err=", hdr["Location"])
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
