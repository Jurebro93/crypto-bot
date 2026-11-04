"""Public front page + access requests: page renders, form rules, organiser invites. No network."""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import members, store  # noqa: E402
from ui import landing  # noqa: E402


class Landing(unittest.TestCase):
    def setUp(self):
        store.DB = os.path.join(tempfile.mkdtemp(), "league.db")
        os.environ.pop("UI_ADMINS", None)
        landing._IPS.clear()

    def test_page_renders_with_and_without_numbers(self):
        landing._STATS.update(ts=0, v={}, busy=True)        # nothing counted yet: fallback cards, no crash
        html = landing.page_html({})
        for s in ("Za sada besplatno", "pristup na zahtjev", "Zatraži pristup", "/prijava", "Prijedlozi tokena", "Praćenje novčanika", "Event tokeni", "action=/zatrazi-pristup", "og:image",
                  "/static/landing/tokeni.jpg", "/static/landing/mob-kol-profil.jpg", "name=web"):
            self.assertIn(s, html)
        import time
        landing._STATS.update(ts=time.time(), v={"tokens": 25458, "kols": 358, "calls": 5360, "wallets": 1_234_567,
                                                 "group_rate": .57, "solo_rate": .33, "measured": 3645,
                                                 "call_2x": .28, "call_50": .47}, busy=False)
        html = landing.page_html({})
        self.assertIn("25.458", html)
        self.assertIn("1,2 mil.", html)
        self.assertIn("57%", html)
        self.assertIn("1.7×", html)
        self.assertIn("Otvori aplikaciju", landing.page_html({}, logged_in=True))
        en = landing.page_html({}, lang="en")
        for s in ("Free for now", "access on request", "/static/landing/en-mob-tokeni.jpg", "/static/landing/en-tokeni.jpg"):
            self.assertIn(s, en)
        import re
        for f in set(re.findall(r"/static/landing/([\w.-]+\.jpg)", html + en)):   # every image the page uses exists
            self.assertTrue(os.path.isfile(os.path.join(landing.STATIC, f)), f)
        for f in landing.SHOTS:   # every screenshot the page links to is in the repo
            self.assertTrue(os.path.isfile(os.path.join(landing.STATIC, f)), f)

    def test_compute_tolerates_missing_databases(self):
        self.assertIsInstance(landing.compute(), dict)

    def test_submit_rules(self):
        ok, err = landing.submit({"name": "M", "contact": "0911234567"}, "1.1.1.1")
        self.assertFalse(ok)
        self.assertIn("ime", err)
        ok, err = landing.submit({"name": "Marko", "contact": "0911234567"}, "1.1.1.1")
        self.assertFalse(ok)                                       # 3.11.: an e-mail is required
        self.assertIn("e-mail", err)
        self.assertEqual(landing.submit({"name": "Marko", "contact": "marko@mail.hr", "experience": "aktivno"}, "1.1.1.1"),
                         (True, None))
        self.assertEqual(landing.submit({"name": "Marko", "contact": "marko@mail.hr"}, "1.1.1.1"), (True, None))  # duplicate
        self.assertEqual(landing.submit({"name": "Bot", "contact": "x@y.zz", "web": "spam"}, "2.2.2.2"), (True, None))
        self.assertEqual(landing.pending_count(), 1)              # duplicate and honeypot not stored
        for i in range(3):
            landing.submit({"name": f"Ana{i}", "contact": f"ana{i}@mail.hr"}, "1.1.1.1")
        ok, err = landing.submit({"name": "Ana9", "contact": "ana9@mail.hr"}, "1.1.1.1")
        self.assertFalse(ok)
        self.assertIn("Previše", err)
        self.assertNotIn('value="<script>"', landing.page_html({}, err="x", form={"name": "<script>"}))

    def test_admin_invite_flow(self):
        landing.submit({"name": "Marko", "contact": "marko@mail.hr"}, "1.1.1.1")
        landing.submit({"name": "Ana", "contact": "ana@mail.hr"}, "1.1.1.2")
        _, body = landing.admin_page({}, None)
        self.assertIn("samo organizator", body)                   # view-only account sees no contacts
        _, body = landing.admin_page({}, "Jure")
        self.assertIn("Marko", body)
        self.assertIn("/zahtjevi/1/pozovi", body)
        self.assertIn("/zahtjevi?ok=", landing.admin_post("/zahtjevi/1/pozovi", "Jure"))
        landing.admin_post("/zahtjevi/2/odbij", "Jure")
        self.assertEqual(landing.pending_count(), 0)
        con = landing._con()
        tok = con.execute("SELECT invite FROM access_requests WHERE id=1").fetchone()[0]
        con.close()
        con = members.connect()
        self.assertTrue(members.valid(con, tok))
        members.register(con, tok, "Marko", "tajna12", "tajna12")
        con.close()
        _, body = landing.admin_page({}, "Jure")
        self.assertIn("wa.me/385911234567", landing._share({"name": "M", "contact": "091 123 4567"}, "u"))
        self.assertIn("mailto:ana@mail.hr", landing._share({"name": "A", "contact": "ana@mail.hr"}, "u"))
        self.assertIn("registriran", body)
        self.assertEqual(landing.admin_post("/zahtjevi/1/pozovi", None), "/zahtjevi")   # not allowed
        self.assertIn("nitko ne čeka", body)                              # nothing pending: says so
        self.assertIn("ušao u aplikaciju kao <b>Marko</b>", body)
        loc = landing.admin_post("/zahtjevi/nova", "Jure", {"name": "Pero", "contact": "092 555 1234"})
        self.assertIn("#pozivnice", loc)                                   # invite without a request
        _, body = landing.admin_page({}, "Jure")
        self.assertIn("Za Pero", body)
        self.assertIn("wa.me/385925551234", body)
        self.assertIn("iskoristio <b>Marko</b>", body)                    # used invite listed under the old ones
        # 3.11.: delete an invite: the link stops working and the request says so
        con = landing._con()
        tok = con.execute("SELECT invite FROM access_requests WHERE name='Pero'").fetchone()[0]
        con.close()
        self.assertIn("ok=", landing.admin_post("/zahtjevi/pozivnica/obrisi", "Jure", {"k": tok}))
        con = members.connect()
        self.assertIsNone(members.valid(con, tok))
        con.close()
        _, body = landing.admin_page({}, "Jure")
        self.assertNotIn("Za Pero", body)
        self.assertIn("pozivnica obrisana", body)
        self.assertIn("ok=", landing.admin_post("/zahtjevi/pozivnica/jednokratni", "Jure", {}))
        self.assertIn("Jednokratni link", landing.admin_page({}, "Jure")[1])
        self.assertEqual(landing.admin_post("/zahtjevi/pozivnica/obrisi", "Ivan", {"k": "x"}), "/zahtjevi")
        self.assertEqual(landing.admin_post("/zahtjevi/nova", None, {"name": "X"}), "/zahtjevi")
        os.environ["UI_ADMINS"] = "Jure"
        try:
            self.assertIn("samo organizator", landing.admin_page({}, "Ivan")[1])
        finally:
            os.environ.pop("UI_ADMINS", None)


if __name__ == "__main__":
    unittest.main()
