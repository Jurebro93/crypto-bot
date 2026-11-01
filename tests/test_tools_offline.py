"""Public "best crypto tools" cluster: pillar + 7 categories in EN and HR, links resolve, sitemap/robots/nav. No network."""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import public, tools, toolsdata as D  # noqa: E402

KEYS = ("best", "free", "paid", "what", "feats", "watch")


class Tools(unittest.TestCase):
    def setUp(self):
        os.environ["RENDER_EXTERNAL_URL"] = "https://example.com"
        public._cache.clear()

    def tearDown(self):
        os.environ.pop("RENDER_EXTERNAL_URL", None)

    def _paths(self):
        out = [tools.BASE["en"], tools.BASE["hr"]]
        for c in D.CATS:
            out += [tools.path(c, "en"), tools.path(c, "hr")]
        return out

    def test_data(self):
        self.assertEqual(len(D.CATS), 7)
        self.assertEqual(set(D.PICKS), {c["key"] for c in D.CATS})
        for k in ("en_slug", "hr_slug"):
            self.assertEqual(len({c[k] for c in D.CATS}), 7)
        for c in D.CATS:
            for lang in ("en", "hr"):
                x = c[lang]
                self.assertLessEqual(len(x["desc"]), 200, (c["key"], lang))
                self.assertEqual(len(x["faq"]), len(c["en"]["faq"]), c["key"])
                self.assertEqual(len(x["choose"]), len(c["en"]["choose"]), c["key"])
            self.assertGreaterEqual(len(c["tools"]), 5, c["key"])
            for t in c["tools"]:
                for lang in ("en", "hr"):
                    for k in KEYS:
                        self.assertTrue(t[lang].get(k), (t["name"], lang, k))
                self.assertEqual(len(t["en"]["feats"]), len(t["hr"]["feats"]), t["name"])
                self.assertTrue(t["url"].startswith(("https://", "/")), t["name"])
            for n, u in c["sources"]:
                self.assertTrue(u.startswith("https://"), u)

    def test_pages(self):
        for p in self._paths():
            code, raw, ctype = public.route(p)
            html = raw.decode()
            self.assertEqual((code, ctype), (200, "text/html"), p)
            self.assertIn("hreflang=hr href", html, p)           # EN/HR pair
            self.assertIn("FAQPage", html, p)
            self.assertIn("class=bv", html, p)                    # chart
            self.assertIn("class=ttab", html, p)                  # comparison table
            self.assertIn("#pristup", html, p)
            self.assertIn('rel=canonical href="https://example.com' + p + '"', html, p)
            self.assertNotIn("<b>Short answer</b><p>None", html)

    def test_internal_links_resolve(self):
        for p in self._paths():
            html = public.route(p)[1].decode()
            for href in set(re.findall(r"href=(/(?:best-crypto-tools|hr/najbolji-kripto-alati|blog|hr/blog|glossary|"
                                       r"hr/rjecnik)[^\s>\"#]*)", html)):
                self.assertEqual(public.route(href)[0], 200, (p, href))

    def test_glossary_live_links(self):
        for slug in ("hardware-wallet", "multisig", "trading-bot", "rug-checker", "crypto-api", "profit-share"):
            self.assertEqual(public.route(f"/glossary/{slug}")[0], 200, slug)
        hr = public.route("/hr/rjecnik/trading-bot")[1].decode()
        self.assertIn("/hr/najbolji-kripto-alati/trading-botovi", hr)

    def test_nav_sitemap_robots_404(self):
        html = public.route("/blog")[1].decode()
        self.assertIn("/best-crypto-tools", html)
        sm = public.route("/sitemap.xml")[1].decode()
        self.assertIn("https://example.com/best-crypto-tools/rug-checkers</loc>", sm)
        self.assertIn("https://example.com/hr/najbolji-kripto-alati/provjera-ruga</loc>", sm)
        rb = public.route("/robots.txt")[1].decode()
        self.assertIn("Allow: /best-crypto-tools", rb)
        self.assertIn("Allow: /hr/najbolji-kripto-alati", rb)
        self.assertEqual(public.route("/best-crypto-tools/nope")[0], 404)
        self.assertEqual(public.route("/hr/najbolji-kripto-alati/wallet-trackers")[0], 404)   # EN slug under HR


if __name__ == "__main__":
    unittest.main()
