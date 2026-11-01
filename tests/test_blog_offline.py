"""Public blog: index, every post, 404, sitemap/robots entries, English-only head (no hreflang hr). No network."""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import blog, public  # noqa: E402
from ui.blogposts import POSTS  # noqa: E402


class Blog(unittest.TestCase):
    def setUp(self):
        os.environ["RENDER_EXTERNAL_URL"] = "https://example.com"
        public._cache.clear()

    def tearDown(self):
        os.environ.pop("RENDER_EXTERNAL_URL", None)

    def test_unique_posts(self):
        self.assertEqual(len(POSTS), 14)
        self.assertEqual(len({p["slug"] for p in POSTS}), 14)
        for p in POSTS:
            self.assertRegex(p["slug"], r"^[a-z0-9-]+$")
            self.assertLessEqual(len(p["desc"]), 200, p["slug"])
            for r in p["related"]:
                self.assertIsNotNone(blog.get(r), r)

    def test_index(self):
        code, raw, ctype = public.route("/blog")
        html = raw.decode()
        self.assertEqual((code, ctype), (200, "text/html"))
        for p in POSTS:
            self.assertIn(f"/blog/{p['slug']}", html)
        self.assertIn('rel=canonical href="https://example.com/blog"', html)

    def test_posts(self):
        for p in POSTS:
            code, raw, _ = public.route(f"/blog/{p['slug']}")
            html = raw.decode()
            self.assertEqual(code, 200, p["slug"])
            self.assertIn("BlogPosting", html)
            self.assertIn('og:type" content="article"', html)
            self.assertIn("#pristup", html)
            self.assertIn("class=bv", html)                        # at least one chart
            for href in re.findall(r"href=/blog/([a-z0-9-]+)", html):   # internal links resolve
                self.assertIsNotNone(blog.get(href), href)

    def test_glossary_links_resolve(self):
        for p in POSTS:
            html = public.route(f"/blog/{p['slug']}")[1].decode()
            gl = set(re.findall(r"href=/glossary/([a-z0-9-]+)", html))
            self.assertTrue(gl, p["slug"])
            for g in gl:
                self.assertEqual(public.route(f"/glossary/{g}")[0], 200, g)

    def test_croatian(self):
        from ui.blogposts_hr import HR
        self.assertEqual(set(HR), {p["slug"] for p in POSTS})
        code, raw, _ = public.route("/hr/blog")
        html = raw.decode()
        self.assertEqual(code, 200)
        self.assertIn("<html lang=hr>", html)
        for en, h in HR.items():
            self.assertIn(f"/hr/blog/{h['slug']}", html)
            code, raw, _ = public.route(f"/hr/blog/{h['slug']}")
            page = raw.decode()
            self.assertEqual(code, 200, h["slug"])
            self.assertIn(f'hreflang=en href="https://example.com/blog/{en}"', page)
            self.assertIn("Zatraži pristup", page)
            self.assertNotIn("Show as table", page)
            for href in re.findall(r"href=/hr/blog/([a-z0-9-]+)", page):
                self.assertIsNotNone(blog.get(href, "hr"), href)
            for g in set(re.findall(r"href=(/hr/rjecnik/[a-z0-9_-]+)", page)):
                self.assertEqual(public.route(g)[0], 200, g)
        en_page = public.route("/blog/what-is-pump-fun")[1].decode()
        self.assertIn('hreflang=hr href="https://example.com/hr/blog/sto-je-pump-fun"', en_page)
        self.assertIn("/hr/blog/sto-je-pump-fun", public.route("/sitemap.xml")[1].decode())

    def test_tools_links_resolve(self):
        for lang, base in (("en", "/blog/"), ("hr", "/hr/blog/")):
            for p in POSTS:
                v = blog.view(p, lang)
                html = public.route(base + v["slug"])[1].decode()
                links = re.findall(r"href=(/best-crypto-tools/[a-z-]+|/hr/najbolji-kripto-alati/[a-z-]+)", html)
                self.assertTrue(links, v["slug"])
                for h in set(links):
                    self.assertEqual(public.route(h)[0], 200, h)

    def test_404(self):
        self.assertEqual(public.route("/blog/nope")[0], 404)

    def test_sitemap_robots(self):
        sm = public.route("/sitemap.xml")[1].decode()
        self.assertIn("https://example.com/blog</loc>", sm)
        self.assertIn("https://example.com/blog/how-to-spot-a-rug-pull</loc>", sm)
        self.assertIn("Allow: /blog", public.route("/robots.txt")[1].decode())


if __name__ == "__main__":
    unittest.main()
