"""Public site menu: every group has links in both languages, plugins can add items, landing shows menu + board."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import public, sitenav  # noqa: E402


class SiteNav(unittest.TestCase):
    def test_menu_both_languages(self):
        for lang in ("en", "hr"):
            m = sitenav.menu(lang)
            self.assertEqual([g[0] for g in m], ["coins", "kols", "tools", "learn"])
            for _k, _label, hub, _d, rows in m:
                self.assertTrue(rows, hub)
                self.assertTrue(all(h.startswith("/hr/") == (lang == "hr") for h, _n, _x in rows if h != "/blog"))
        self.assertIn("/solana-meme-coins/gainers", sitenav.nav("en"))
        self.assertIn("/hr/provjera", sitenav.mobile("hr"))
        self.assertIn("/best-crypto-tools/", sitenav.footer("en"))

    def test_plugin_items(self):
        import types
        mod = types.ModuleType("fakeplug")
        mod.nav_items = lambda lang: [("learn", "/blog/category/guides", "Guides", "How-tos")]
        sys.modules["fakeplug"] = mod
        old = sitenav.PLUGINS
        sitenav.PLUGINS = old + ("fakeplug", "does.not.exist")
        try:
            self.assertIn("/blog/category/guides", sitenav.footer("en"))
        finally:
            sitenav.PLUGINS = old

    def test_public_pages_use_menu(self):
        public._cache.clear()
        html = public.route("/glossary")[1].decode()
        self.assertIn("class=fcols", html)
        self.assertIn("class=ddm", html)


if __name__ == "__main__":
    unittest.main()
