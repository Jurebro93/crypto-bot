"""Public Telegram trading bot overview + 4 setup guides (EN/HR): data, pages, links, nav, sitemap. No network."""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import botguides as B, public, sitenav, tools  # noqa: E402


class BotGuides(unittest.TestCase):
    def setUp(self):
        os.environ["RENDER_EXTERNAL_URL"] = "https://example.com"
        public._cache.clear()

    def tearDown(self):
        os.environ.pop("RENDER_EXTERNAL_URL", None)

    def _paths(self):
        out = [B.opath("en"), B.opath("hr")]
        for k in B.ORDER:
            out += [B.gpath(k, "en"), B.gpath(k, "hr")]
        return out

    def test_data(self):
        self.assertEqual(set(B.ORDER), set(B.GUIDES))
        for k in B.ORDER:
            g = B.GUIDES[k]
            for lang in ("en", "hr"):
                self.assertLessEqual(len(g["desc"][lang]), 200, (k, lang))
                self.assertTrue(g["tldr"][lang] and g["watch"][lang], (k, lang))
            for st in g["steps"]:
                self.assertEqual(len(st), 4, k)
            for b in B.BOTS:
                for _, u in b["links"]:
                    self.assertTrue(u.startswith("https://t.me/") or u.startswith("https://"), u)
        for lang in ("en", "hr"):
            self.assertLessEqual(len(B.TX[lang]["desc"]), 200, lang)
        self.assertEqual(len(B.TX["en"]["faq"]), len(B.TX["hr"]["faq"]))
        # no slug collides with a tools category
        cats = {c["en_slug"] for c in tools._data().CATS} | {c["hr_slug"] for c in tools._data().CATS}
        for p in self._paths():
            self.assertNotIn(p.rsplit("/", 1)[1], cats)

    def test_pages(self):
        for p in self._paths():
            code, raw, ctype = public.route(p)
            html = raw.decode()
            self.assertEqual((code, ctype), (200, "text/html"), p)
            self.assertIn('rel=canonical href="https://example.com' + p + '"', html, p)
            self.assertIn("hreflang=hr href", html, p)
            self.assertIn("class=tgm", html, p)          # settings panel illustration
            self.assertIn("class=ttab", html, p)         # settings table
            self.assertIn("#pristup", html, p)
            self.assertNotIn("None</", html, p)
        ov = public.route(B.opath("en"))[1].decode()
        self.assertIn("FAQPage", ov)
        self.assertIn("class=bv", ov)                    # charts
        self.assertIn("0.005 SOL", ov)                   # sol fmt
        self.assertIn("0,005 SOL", public.route(B.opath("hr"))[1].decode())
        for k in B.ORDER:
            self.assertIn("HowTo", public.route(B.gpath(k, "hr"))[1].decode(), k)

    def test_internal_links_resolve(self):
        for p in self._paths() + [tools.BASE["en"] + "/trading-bots", tools.BASE["hr"] + "/trading-botovi"]:
            html = public.route(p)[1].decode()
            for href in set(re.findall(r"href=(/(?:best-crypto-tools|hr/najbolji-kripto-alati|blog|hr/blog|glossary|"
                                       r"hr/rjecnik)[^\s>\"#]*)", html)):
                self.assertEqual(public.route(href)[0], 200, (p, href))

    def test_linked_from_trading_category_nav_sitemap_glossary(self):
        self.assertIn(B.opath("en"), public.route("/best-crypto-tools/trading-bots")[1].decode())
        self.assertIn(B.gpath("trojan", "hr"), public.route("/hr/najbolji-kripto-alati/trading-botovi")[1].decode())
        self.assertIn(B.opath("en"), sitenav.menu("en") if isinstance(sitenav.menu("en"), str) else str(sitenav.menu("en")))
        sm = public.route("/sitemap.xml")[1].decode()
        self.assertIn("https://example.com" + B.gpath("maestro", "en") + "</loc>", sm)
        self.assertIn("https://example.com" + B.opath("hr") + "</loc>", sm)
        for slug in ("mev-protection", "priority-fee"):
            html = public.route(f"/glossary/{slug}")[1].decode()
            self.assertIn(B.opath("en"), html, slug)
        self.assertEqual(public.route(B.opath("en") + "x")[0], 404)
        self.assertEqual(public.route("/hr/najbolji-kripto-alati/" + B.OVERVIEW["en"])[0], 404)


if __name__ == "__main__":
    unittest.main()
