"""Render every blog post's cover (ui/blogcover.py) into the share PNGs used as og:image:
ui/static/landing/blog-<slug>.jpg (English) and blog-<slug>-hr.jpg (Croatian), 1200x630.

Run from the repo root after adding a post: python3 scripts/blog_covers.py  (needs Node + Playwright + Chromium).
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ui import blog, blogcover  # noqa: E402

OUT = os.path.join(ROOT, "ui", "static", "landing")


def main():
    tmp = tempfile.mkdtemp(prefix="covers-")
    jobs = []
    for lang in ("en", "hr"):
        for v in blog.views(lang):
            name = f"blog-{v['en']}{'' if lang == 'en' else '-hr'}.jpg"
            page = os.path.join(tmp, name + ".html")
            with open(page, "w", encoding="utf-8") as f:
                f.write("<!doctype html><meta charset=utf-8><style>body{margin:0}svg{display:block;width:1200px;"
                        f"height:630px}}</style>{blogcover.svg(v, lang)}")
            jobs.append([page, os.path.join(OUT, name)])
    js = ("const {chromium}=require('playwright');(async()=>{const b=await chromium.launch();"
          "const p=await b.newPage({viewport:{width:1200,height:630}});"
          f"for(const [h,o] of {json.dumps(jobs)}){{await p.goto('file://'+h);await p.screenshot({{path:o,type:'jpeg',quality:88}});}}"
          "await b.close()})();")
    subprocess.run(["node", "-e", js], check=True)
    print("ok", len(jobs))


if __name__ == "__main__":
    main()
