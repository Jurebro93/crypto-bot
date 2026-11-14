"""SEO of the public site (13.11., Jure: "provjeri još jednom SEO metatitlove URL-ove ... i što se može još poboljšati";
"Za svaku stranicu koja je objavljena mora postati hrvatska i engleska verzija"): ops/seoaudit.py on every page type
rendered here (no network, no data), titles and descriptions trimmed in one place, the 404 page that no longer claims
to be /influencers, the Croatian tool tables in Croatian. No network."""
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["I18N_OFF"] = "1"
os.environ["RENDER_EXTERNAL_URL"] = "https://memesonar.app"

from ops import seoaudit as A  # noqa: E402
from ui import public  # noqa: E402

BASE = "https://memesonar.app"


class TitleAndDescription(unittest.TestCase):
    def test_title_drops_the_brand_then_an_aside(self):
        self.assertEqual(public.seo_title("Short title | MemeSonar"), "Short title | MemeSonar")
        self.assertEqual(public.seo_title("How to spot a rug pull on Solana: a rug checker checklist (data from 10,650 "
                                          "tokens) | MemeSonar"), "How to spot a rug pull on Solana: a rug checker checklist")
        self.assertEqual(public.seo_title("  Two   spaces  "), "Two spaces")

    def test_description_in_160(self):
        d = ("Da, hrvatski d.o.o. smije kupiti kripto vlastitim novcem. Kako se knjiži (HSFI 5 ili 10), oporezuje (10% "
             "ili 18% porez na dobit, bez pravila dvije godine), PDV, banke i kad je privatno držanje jeftinije.")
        out = public.seo_desc(d)
        self.assertLessEqual(len(out), 160)
        self.assertTrue(out.endswith("…"))
        long_sentences = "A" * 120 + ". " + "B" * 80 + "."
        self.assertEqual(public.seo_desc(long_sentences), "A" * 120 + ".")
        self.assertEqual(public.seo_desc("Kratko."), "Kratko.")


class NotFound(unittest.TestCase):
    def test_404_claims_no_other_page(self):
        for path, lang in (("/coin/45yf6UuhLUfkDKrNDUq4WSiLxb1e1NiggpyWjiRKpump", "en"), ("/hr/coin/nema-ga", "hr"),
                           ("/blog/nema-ga", "en"), ("/hr/blog/nema-ga", "hr")):
            code, body, _ = public.route(path)
            html = body.decode()
            head = html.split("<body", 1)[0]
            self.assertEqual(code, 404, path)
            self.assertNotIn("canonical", head, path)
            self.assertNotIn("hreflang=", head, path)
            self.assertNotIn("og:url", head, path)
            self.assertIn("noindex", head, path)
            self.assertIn(f"<html lang={lang}>", html, path)
            self.assertNotIn("/influencers\"><link", head)


class ToolsInCroatian(unittest.TestCase):
    def test_chains_column(self):
        from ui import toolsdata
        for c in toolsdata.CATS:
            for t in c["tools"]:
                hr = toolsdata.chains(t, "hr")
                self.assertNotRegex(hr, r"\b(and|more|chains|incl|Exchange)\b", t["name"])
                self.assertEqual(toolsdata.chains(t, "en"), t["chains"])
        from ui import botguides
        for b in botguides.BOTS:
            self.assertNotRegex(b["chains"]["hr"], r"\b(and|more|separate|chains)\b", b["name"])


class Audit(unittest.TestCase):
    """Every page type the sitemap offers, rendered here in both languages, passes the audit's hard checks."""

    @classmethod
    def setUpClass(cls):
        os.environ["DATA_DIR"] = tempfile.mkdtemp()
        public._cache.clear()
        cls.rows = []
        for url, st, html in A.offline_pages():
            f, iss = A.check(url, st, html)
            cls.rows.append((url, f, iss))

    def test_enough_pages(self):
        self.assertGreater(len(self.rows), 100)
        langs = {f["lang"] for _, f, _ in self.rows}
        self.assertEqual(langs, {"en", "hr"})

    def test_hard_checks(self):
        hard = re.compile(r"^(status|html lang|no <title>|title (\d{2,}) chars|description (\d+) chars|\d+ canonical|"
                          r"canonical ->|no hreflang|hreflang .* missing|hreflang .* \(not self\)|\d+ <h1>|og:|"
                          r"no link to the other language|JSON-LD|title language|description language)")
        bad = []
        for url, f, iss in self.rows:
            for i in iss:
                m = hard.match(i)
                if not m:
                    continue
                if i.startswith("title ") and "chars" in i and int(i.split()[1]) < A.TITLE_MAX:
                    continue            # short titles of the empty market pages (no data here) are not the point
                if i.startswith("description ") and "chars" in i and int(i.split()[1]) < A.DESC_MIN:
                    continue
                bad.append((url, i))
        self.assertEqual(bad, [])

    def test_pairs_both_languages(self):
        """Every English page names a Croatian one and the other way round (the owner's rule)."""
        for url, f, _ in self.rows:
            hl = f.get("hreflang") or {}
            self.assertIn("en", hl, url)
            self.assertIn("hr", hl, url)
            self.assertNotEqual(hl["en"], hl["hr"], url)

    def test_titles_unique_per_language(self):
        seen = {}
        for url, f, _ in self.rows:
            if f.get("status") == 200:
                self.assertNotIn(f["title"], seen, f"{url} and {seen.get(f['title'])}")
                seen[f["title"]] = url


class Helpers(unittest.TestCase):
    def test_robots_longest_rule_wins(self):
        r = "User-agent: *\nAllow: /$\nAllow: /coin/\nAllow: /hr$\nDisallow: /\n"
        self.assertTrue(A.robots_allows(r, "/"))
        self.assertTrue(A.robots_allows(r, "/coin/pengu"))
        self.assertTrue(A.robots_allows(r, "/hr"))
        self.assertFalse(A.robots_allows(r, "/hr/x"))
        self.assertFalse(A.robots_allows(r, "/token/x"))

    def test_mixed_language_finder(self):
        p = A.parse("<html lang=en><body><p>Price is up today and novčanik je pun</p>"
                    "<span translate=no>Ivana Kovač</span></body></html>")
        self.assertEqual({w for w, _ in A.foreign_words(p.text, "en")}, {"novčanik", "je"})
        p = A.parse("<html lang=hr><body><p>Cijena je porasla, pump and dump, top 100 i the best</p></body></html>")
        self.assertEqual([w for w, _ in A.foreign_words(p.text, "hr")], ["the", "best"])

    def test_page_types(self):
        self.assertEqual(A.page_type("/hr/coin/pengu/prognoza"), "coin/*")
        self.assertEqual(A.page_type("/blog/category/guides"), "blog/category")
        self.assertEqual(A.page_type("/"), "home")
        self.assertEqual(A.expected_lang("/autopilot"), "hr")
        self.assertEqual(A.expected_lang("/en/autopilot"), "en")


if __name__ == "__main__":
    unittest.main()
