"""Blog covers: every post has a cover in both languages, on cards, in the post header and as og:image. No network."""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import blog, blogcover, public  # noqa: E402
from ui.landing import STATIC  # noqa: E402


class Covers(unittest.TestCase):
    def setUp(self):
        os.environ["RENDER_EXTERNAL_URL"] = "https://example.com"
        public._cache.clear()

    def tearDown(self):
        os.environ.pop("RENDER_EXTERNAL_URL", None)

    def test_every_post_has_number_and_share_image(self):
        for lang in ("en", "hr"):
            for v in blog.views(lang):
                self.assertIn(v["en"], blogcover.COVER, f"add a COVER entry in ui/blogcover.py for {v['en']}")
                name = f"blog-{v['en']}{'' if lang == 'en' else '-hr'}.jpg"
                self.assertTrue(os.path.isfile(os.path.join(STATIC, name)),
                                f"{name} missing: run python3 scripts/blog_covers.py")

    def test_svg_ids_unique_and_language(self):
        v_en, v_hr = blog.get_en("how-to-spot-a-rug-pull", "en"), blog.get_en("how-to-spot-a-rug-pull", "hr")
        a, b = blogcover.svg(v_en, "en"), blogcover.svg(v_hr, "hr")
        self.assertIn("1.4%", a)
        self.assertIn("1,4%", b)
        self.assertNotEqual(re.findall(r'id="(\w+)"', a), re.findall(r'id="(\w+)"', b))

    def test_new_post_without_number_gets_title(self):
        v = dict(blog.get_en("what-is-pump-fun", "en"), en="brand-new-post", h1="A brand new post")
        self.assertIn("A brand new post", blogcover.svg(v, "en"))

    def test_pages_show_covers(self):
        html = public.route("/blog")[1].decode()
        self.assertEqual(html.count("<svg class=\"cv\""), len(blog.views("en")))
        ids = re.findall(r'<linearGradient id="(\w+)"', html)
        self.assertEqual(len(ids), len(set(ids)))
        for path, img in (("/blog/how-to-spot-a-rug-pull", "blog-how-to-spot-a-rug-pull.jpg"),
                          ("/hr/blog/" + blog.get_en("how-to-spot-a-rug-pull", "hr")["slug"],
                           "blog-how-to-spot-a-rug-pull-hr.jpg")):
            html = public.route(path)[1].decode()
            self.assertIn("<figure class=bcov><svg", html)
            self.assertIn(f'og:image" content="https://example.com/static/landing/{img}"', html)


if __name__ == "__main__":
    unittest.main()
