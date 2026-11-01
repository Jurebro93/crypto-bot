"""Public glossary: every entry maps to a Croatian term, pages render in both languages, sitemap/robots list them."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import glossary, glossary_public as GP, public  # noqa: E402


class GlossaryPublic(unittest.TestCase):
    def setUp(self):
        os.environ["RENDER_EXTERNAL_URL"] = "https://example.com"
        public._cache.clear()

    def test_entries(self):
        self.assertEqual(len(GP.ENTRIES), len(GP._E))               # no entry silently dropped
        self.assertEqual(len(GP.BY_EN), len(GP.ENTRIES))            # unique English slugs
        for slug in ("copy-trading", "dca", "kol", "slippage", "liquidity", "memecoin", "fdv", "market-cap",
                     "rug-pull", "smart-money", "pump-fun"):          # slugs promised to the blog
            self.assertIn(slug, GP.BY_EN)
        internal = {"stranice", "stupci", "sustav", "nastoken"}
        self.assertFalse([e for e in GP.ENTRIES if glossary.TERMS[e["hr"]]["cat"] in internal])

    def test_pages(self):
        code, body, _ = public.route("/glossary")
        html = body.decode()
        self.assertEqual(code, 200)
        for s in ("Crypto glossary", "/glossary/rug-pull", "DefinedTermSet", "hreflang=hr"):
            self.assertIn(s, html)
        code, body, _ = public.route("/glossary/rug-pull")
        html = body.decode()
        self.assertEqual(code, 200)
        for s in ("What is a rug pull?", "FAQPage", "DefinedTerm", "/hr/rjecnik/rug", "Related terms"):
            self.assertIn(s, html)
        hr = public.route("/hr/rjecnik/rug")[1].decode()
        self.assertIn("Što je Rug?", hr)
        self.assertIn("/glossary/rug-pull", hr)
        self.assertEqual(public.route("/glossary/nope")[0], 404)
        self.assertEqual(public.route("/hr/rjecnik/demo-racun")[0], 404)     # internal terms stay private
        sm = public.route("/sitemap.xml")[1].decode()
        self.assertIn("https://example.com/glossary/copy-trading", sm)
        self.assertIn("https://example.com/hr/rjecnik/copy-trading", sm)
        self.assertIn("Allow: /glossary", public.route("/robots.txt")[1].decode())


if __name__ == "__main__":
    unittest.main()
