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
        """28.11. (vlasnik, poslovni plan): the data product's homepage (ui/naslovnica.py); the proof strip says "still
        measuring" until the background count has numbers, never a made-up one."""
        landing._STATS.update(ts=0, v={}, busy=True)        # nothing counted yet: no crash, honest dashes
        html = landing.page_html({})
        for s in ("Izmjereni podaci o Solana memecoinima", "Podaci, ne financijski savjet", "/prijava", "og:image",
                  "action=/cekanje", "name=web", "id=pristup", "/hr/cijene", "/hr/provjeri-influencera",
                  "/hr/metodologija", "Mjerenje je u tijeku"):
            self.assertIn(s, html)
        self.assertEqual(html.split("id=dokaz")[1].split("</section>")[0].count("<b class=w>—</b>"), 3)
        import time
        proof = {"kol": {"share": .312, "n": 4210, "day": "2026-11-26"}, "toc": None,
                 "kop": {"good": 7, "rated": 140, "n": 5120, "day": "2026-11-27"}}
        landing._STATS.update(ts=time.time(), v={"dokaz": proof}, busy=False)
        strip = landing.page_html({}).split("id=dokaz")[1].split("</section>")[0]
        for s in ("<b>31 %</b>", "n = 4.210 poziva", "26. 11. 2026.", "<b>7 od 140</b>", "n = 5.120 kopiranja"):
            self.assertIn(s, strip)
        self.assertEqual(strip.count("Mjerenje je u tijeku"), 1)
        self.assertIn("Otvori aplikaciju", landing.page_html({}, logged_in=True))
        en = landing.page_html({}, lang="en")
        for s in ("Measured data on Solana memecoins", "<b>31%</b>", "n = 4,210 calls", "26 Nov 2026", "<b>7 of 140</b>"):
            self.assertIn(s, en)
        import re
        for f in set(re.findall(r"/static/landing/([\w.-]+\.jpg)", html + en)):   # every image the page uses exists
            self.assertTrue(os.path.isfile(os.path.join(landing.STATIC, f)), f)

    def test_share_cards(self):
        from ui import loginpage, public as P
        for lang in ("en", "hr"):
            for path in ("/", "/influencers", "/coin/bonk", "/best-crypto-tools", "/glossary/kol", "/blog"):
                img, alt = P.og_card(path, lang)
                self.assertTrue(os.path.isfile(os.path.join(landing.STATIC, img.rsplit("/", 1)[1])), img)
                self.assertTrue(alt)
        self.assertIn("og-kols-hr.jpg", P.og_card("/influencer/x", "hr")[0])
        html = landing.page_html({}, lang="en")
        for s in ('og:image:width" content="1200"', "og-home.jpg", "twitter:image"):
            self.assertIn(s, html)
        self.assertIn("https://memesonar.app/static/landing/og-home-hr.jpg", loginpage.html(site_url="https://memesonar.app", lang="hr"))

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
        self.assertNotIn('value="<script>"', landing.page_html({}, err="x", form={"email": "<script>"}))

    def test_admin_invite_flow(self):
        landing.submit({"name": "Marko", "contact": "marko@mail.hr"}, "1.1.1.1")
        landing.submit({"name": "Ana", "contact": "ana@mail.hr"}, "1.1.1.2")
        _, body = landing.admin_page({}, None)
        self.assertIn("samo administrator", body)                   # view-only account sees no contacts
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
        members.register(con, tok, "Marko", "tajna12tajna", "tajna12tajna")
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
            self.assertIn("samo administrator", landing.admin_page({}, "Ivan")[1])
        finally:
            os.environ.pop("UI_ADMINS", None)


if __name__ == "__main__":
    unittest.main()
