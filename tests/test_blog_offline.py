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

    def test_ten_unique_posts(self):
        self.assertEqual(len(POSTS), 10)
        self.assertEqual(len({p["slug"] for p in POSTS}), 10)
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
            self.assertNotIn("hreflang=hr href", html)            # English only
            self.assertIn("class=bv", html)                        # at least one chart
            for href in re.findall(r"href=/blog/([a-z0-9-]+)", html):   # internal links resolve
                self.assertIsNotNone(blog.get(href), href)

    def test_404(self):
        self.assertEqual(public.route("/blog/nope")[0], 404)

    def test_sitemap_robots(self):
        sm = public.route("/sitemap.xml")[1].decode()
        self.assertIn("https://example.com/blog</loc>", sm)
        self.assertIn("https://example.com/blog/how-to-spot-a-rug-pull</loc>", sm)
        self.assertIn("Allow: /blog", public.route("/robots.txt")[1].decode())


if __name__ == "__main__":
    unittest.main()
