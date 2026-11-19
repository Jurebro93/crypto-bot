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
        """20.11. (vlasnik 19.11.: "promijeniti fokus"): the wallets that buy before a jump first; the live numbers
        from the stored summaries ("—" and "being computed" without them)."""
        landing._STATS.update(ts=0, v={}, busy=True)        # nothing counted yet: no crash, honest dashes
        html = landing.page_html({})
        for s in ("Za sada besplatno", "pristup na zahtjev", "Zatraži pristup", "/prijava", "Novčanici koji kupuju",
                  "Kako radi", "action=/zatrazi-pristup", "og:image", "/static/landing/token-midcap.jpg", "name=web",
                  "Prvi rezultati se upravo računaju.", "Prvi nalazi stižu nakon noćne obrade."):
            self.assertIn(s, html)
        self.assertEqual(html.split("id=brojke")[1].split("</section>")[0].count("<b>—</b>"), 4)
        import time
        nv = {"rises": 41, "found": 20, "confirmed": 8, "meas": {"n": 19, "mean": .047, "lo": -.02, "hi": .1, "td": 19,
                                                                 "verdict": "premalo podataka: n=19 od potrebnih 100"},
              "examples": [{"k": 70, "n": 7, "b": 6}, {"k": 1, "n": 3, "b": 3}], "tokens": []}
        landing._STATS.update(ts=time.time(), v={"nov": nv}, busy=False)
        html = landing.page_html({})
        live = html.split("id=brojke")[1].split("</section>")[0]
        for s in ("<b>41</b>", "<b>20</b>", "<b>8</b>", "<b>prerano za reći</b>", "izmjereno 19 kupnji"):
            self.assertIn(s, live)
        self.assertIn("Skupina od 70 povezanih novčanika kupila je prije rasta 7 tokena i prodala dok su rasli (6 od "
                      "njih vrijedilo je 15 milijuna dolara ili više); potvrđeno na novijim podacima.", html)
        self.assertIn("To je statistika iz javnih podataka s lanca, a ne financijski savjet.", html)
        nv["meas"] = {"n": 140, "mean": .052, "lo": .011, "hi": .094, "td": 120, "verdict": "u plusu"}
        landing._STATS.update(ts=time.time(), v={"nov": nv}, busy=False)
        live = landing.page_html({}).split("id=brojke")[1].split("</section>")[0]
        self.assertIn("<b>+5,2 %</b><span>po kupnji nakon troška (+1,1 % … +9,4 %)</span>", live)
        self.assertIn("Otvori aplikaciju", landing.page_html({}, logged_in=True))
        en = landing.page_html({}, lang="en")
        for s in ("Free for now", "access on request", "/static/landing/en-novcanici.jpg", "Wallets that buy",
                  "<b>+5.2 %</b><span>per buy after costs (+1.1 % … +9.4 %)</span>"):
            self.assertIn(s, en)
        import re
        for f in set(re.findall(r"/static/landing/([\w.-]+\.jpg)", html + en)):   # every image the page uses exists
            self.assertTrue(os.path.isfile(os.path.join(landing.STATIC, f)), f)
        for f in landing.SHOTS:   # every screenshot the page links to is in the repo
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
        for s in ('og:image:width" content="1200"', "og-home.jpg", "twitter:image", "class=pulse"):
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
        self.assertNotIn('value="<script>"', landing.page_html({}, err="x", form={"name": "<script>"}))

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
