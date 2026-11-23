"""Editorial pages (blog posts, public glossary, tool pages), 23.11.2026: outside links are https and listed in
docs/seo/izvori_2311.md (each was fetched and read before it was added), every post has a Sources block with 2-5
links in both languages, one H1, unique <title> and meta description per language, and Article structured data with
datePublished / dateModified plus a BreadcrumbList. No network."""
import html as H
import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ui import blog, blogsources as BS, public, tools  # noqa: E402
from ui import glossary_public as GP  # noqa: E402

MD = os.path.join(ROOT, "docs", "seo", "izvori_2311.md")
BASE = "https://example.com"


def _get(path):
    public._cache.clear()
    code, raw, _ = public.route(path)
    return code, raw.decode()


def _main(page):
    m = re.search(r"<main.*?</main>", page, re.S)
    return m.group(0) if m else page


def _external(page):
    return [H.unescape(u) for u in re.findall(r'href="?(https?://[^"\s>]+)', _main(page)) if not u.startswith(BASE)]


def _ld(page):
    out = []
    for raw in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
        d = json.loads(raw.replace("<\\/", "</"))
        for x in d if isinstance(d, list) else [d]:
            out += x.get("@graph", [x])
    return out


def _blog_paths():
    return [(lang, v, f"{blog.L[lang]['base']}/{v['slug']}") for lang in ("en", "hr") for v in blog.views(lang)]


def _gloss_paths():
    return [(f"/glossary/{e['en']}", e) for e in GP.ENTRIES] + [(f"/hr/rjecnik/{e['hr']}", e) for e in GP.ENTRIES]


class Izvori(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["RENDER_EXTERNAL_URL"] = BASE
        with open(MD, encoding="utf-8") as f:
            cls.md = f.read()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("RENDER_EXTERNAL_URL", None)

    def test_md_lists_every_source(self):
        for k, s in BS.S.items():
            self.assertTrue(s[0].startswith("https://"), k)
            self.assertIn(f"| {s[0]} |", self.md, f"{k}: run python3 scripts/izvori_md.py")
        self.assertEqual(len({s[0] for s in BS.S.values()}), len(BS.S))           # no duplicate URLs
        for keys in list(BS.POSTS.values()) + list(BS.GLOSS.values()):
            for k in keys:
                self.assertIn(k, BS.S)

    def test_blog_outbound_links_https_and_listed(self):
        n = 0
        for lang, v, path in _blog_paths():
            code, page = _get(path)
            self.assertEqual(code, 200, path)
            for u in _external(page):
                n += 1
                self.assertTrue(u.startswith("https://"), (path, u))
                self.assertIn(f"| {u} |", self.md, f"{path} links to {u}, which is not in docs/seo/izvori_2311.md")
        self.assertGreater(n, 150)

    def test_glossary_outbound_links_https_and_listed(self):
        for path, e in _gloss_paths():
            code, page = _get(path)
            self.assertEqual(code, 200, path)
            ext = _external(page)
            for u in ext:
                self.assertTrue(u.startswith("https://"), (path, u))
                self.assertIn(f"| {u} |", self.md, (path, u))
            self.assertEqual(len(ext), len(BS.GLOSS.get(e["en"], ())), path)
            if e["en"] in BS.GLOSS:
                self.assertIn("class=src", page, path)

    def test_tool_pages_outbound_links_https(self):
        for en, hr, _p in tools.urls():
            for path in (en, hr):
                if not path:
                    continue
                code, page = _get(path)
                self.assertEqual(code, 200, path)
                for u in _external(page):
                    self.assertTrue(u.startswith("https://"), (path, u))

    def test_every_post_has_sources_both_languages(self):
        en_slugs = {p["slug"] for p in blog._posts()}
        self.assertEqual(set(BS.POSTS), en_slugs)
        for lang, v, path in _blog_paths():
            page = _get(path)[1]
            keys = BS.POSTS[v["en"]]
            self.assertTrue(2 <= len(keys) <= 5, v["en"])
            self.assertIn("<h2 class=s>" + ("Sources" if lang == "en" else "Izvori") + "</h2>", page, path)
            block = re.search(r"<section class=src.*?</section>", page, re.S).group(0)
            listed = set(re.findall(r'href="(https://[^"]+)"', block))
            self.assertEqual(listed, {BS.url(k) for k in keys}, path)
            for u in set(re.findall(r'href="(https://[^"]+)"', v["body"])):    # inline links are in the list too
                self.assertIn(u, listed, (path, u))
            self.assertIn('rel="nofollow noopener" target=_blank', block)

    def test_one_h1_unique_title_and_description(self):
        for lang in ("en", "hr"):
            titles, descs = {}, {}
            for _l, v, path in [x for x in _blog_paths() if x[0] == lang]:
                page = _get(path)[1]
                self.assertEqual(page.count("<h1"), 1, path)
                t = H.unescape(re.search(r"<title>(.*?)</title>", page, re.S).group(1))
                d = H.unescape(re.search(r'name=description content="(.*?)"', page, re.S).group(1))
                self.assertLessEqual(len(t), 70, path)
                self.assertTrue(100 <= len(d) <= 160, (path, len(d)))
                self.assertNotIn(t, titles, (path, titles.get(t)))
                self.assertNotIn(d, descs, (path, descs.get(d)))
                titles[t], descs[d] = path, path
            for path, _e in [g for g in _gloss_paths() if g[0].startswith("/glossary/" if lang == "en" else "/hr/")]:
                self.assertEqual(_get(path)[1].count("<h1"), 1, path)

    def test_structured_data(self):
        for lang, v, path in _blog_paths():
            items = _ld(_get(path)[1])
            art = [x for x in items if x.get("@type") in ("BlogPosting", "Article")]
            self.assertEqual(len(art), 1, path)
            self.assertRegex(art[0]["datePublished"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertGreaterEqual(art[0]["dateModified"], art[0]["datePublished"], path)
            self.assertEqual(art[0]["inLanguage"], lang)
            self.assertEqual(art[0]["citation"], [BS.url(k) for k in BS.POSTS[v["en"]]], path)
            bc = [x for x in items if x.get("@type") == "BreadcrumbList"]
            self.assertEqual(len(bc), 1, path)
            self.assertTrue(bc[0]["itemListElement"][-1]["item"].endswith(path), path)
        for path, _e in _gloss_paths():
            types = {x.get("@type") for x in _ld(_get(path)[1])}
            self.assertTrue({"DefinedTerm", "BreadcrumbList"} <= types, path)

    def test_related_posts_and_no_orphans(self):
        inbound = {p["slug"]: 0 for p in blog._posts()}
        for p in blog._posts():
            self.assertEqual(len(p["related"]), 3, p["slug"])
            for r in p["related"]:
                self.assertNotEqual(r, p["slug"])
                inbound[r] += 1
        for lang, v, path in _blog_paths():
            page = _get(path)[1]
            for r in v["related"]:
                rv = blog.get_en(r, lang)
                self.assertIn(f"href={blog.L[lang]['base']}/{rv['slug']}>", page, (path, r))
        self.assertEqual([s for s, n in inbound.items() if n == 0], [], "posts no other post recommends")

    def test_updated_date_shown_only_when_changed(self):
        for lang, v, path in _blog_paths():
            page = _get(path)[1]
            if v.get("updated"):
                self.assertIn(f"<time datetime={v['updated']}>", page, path)
            else:
                self.assertNotIn("<time datetime=", page.split("<div class=meta>")[1].split("</div>")[0], path)


if __name__ == "__main__":
    unittest.main()
