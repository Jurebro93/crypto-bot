"""Public blog (English, indexable): /blog and /blog/<slug>.

Posts live in ui/blogposts.py (title, description, target keyword, body HTML with charts from ui/blogviz.py).
Pages are rendered through ui.public._shell (nav, footer, canonical, Open Graph) and cached by ui.public.route.
Every post ends with the "Request access" call to action and links to related posts and public tool pages.
"""
import json
import os

from ui.html import esc

CSS = """
.art{max-width:740px}.art .ph1 h1{font-size:clamp(30px,5vw,46px);line-height:1.12}
.art .meta{color:var(--mut);font-size:14px;margin:-4px 0 26px}
.art h2{font-size:26px;letter-spacing:-.01em;margin:40px 0 10px}.art h3{font-size:19px;margin:28px 0 6px}
.art p,.art li{font-size:17.5px;line-height:1.7}.art ul,.art ol{padding-left:22px}.art li{margin:6px 0}
.art a{color:var(--acc)}.art .tldr{background:var(--soft);border:1px solid var(--line);border-radius:18px;
padding:16px 20px;margin:0 0 8px}.art .tldr p{margin:0}.art .tldr b{display:block;font-size:13px;color:var(--mut);
text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px}
.art .note{color:var(--mut);font-size:15px}.art blockquote{margin:20px 0;padding:4px 18px;border-left:3px solid var(--acc);
color:var(--fg)}
.bl{display:grid;grid-template-columns:repeat(2,1fr);gap:16px;margin:8px 0 30px}@media(max-width:720px){.bl{grid-template-columns:1fr}}
.bl a{display:block;border:1px solid var(--line);border-radius:18px;padding:20px;background:#fff;color:var(--fg)}
.bl a:hover{border-color:#cfd5e1;box-shadow:0 10px 30px -18px rgba(11,18,32,.35)}
.bl b{display:block;font-size:19px;line-height:1.3;margin:6px 0 8px}.bl span{color:var(--mut);font-size:15px}
.bl em{font-style:normal;color:var(--acc);font-weight:650;font-size:13px}
"""


# Bold terms in post bodies that get a link to their public glossary entry (first occurrence per post).
GLOSS = {"wallet tracker": "smart-money", "smart money": "smart-money", "sniper": "sniper-bot", "rug pull": "rug-pull",
         "mint authority": "mint-authority", "graduates": "graduation", "call": "crypto-call", "bundle": "bundler",
         "slippage": "slippage", "market cap": "market-cap", "liquidity": "liquidity", "kol": "kol", "fdv": "fdv",
         "hit rate": "hit-rate", "late calls": "late-call", "dollar-cost averaging": "dca", "serial creator": "dev-wallet"}
# Glossary chips under each post.
TERMS = {
    "what-is-wallet-tracking": ("smart-money", "crypto-wallet", "sniper-bot", "insider-wallet", "copy-trading"),
    "what-is-copy-trading": ("copy-trading", "smart-money", "take-profit", "stop-loss", "roi"),
    "what-is-a-kol-in-crypto": ("kol", "crypto-call", "call-power", "hit-rate", "late-call", "bot-account"),
    "influencer-clustering": ("kol", "crypto-call", "wallet-cluster", "call-power"),
    "how-to-spot-a-rug-pull": ("rug-pull", "dev-wallet", "mint-authority", "liquidity", "holders", "bundler"),
    "what-is-pump-fun": ("pump-fun", "graduation", "memecoin", "market-cap"),
    "bundles-and-snipers": ("bundler", "sniper-bot", "insider-wallet", "rug-pull"),
    "how-to-trade-meme-coins": ("memecoin", "market-cap", "take-profit", "x-multiplier", "pnl"),
    "what-is-dca-in-crypto": ("dca", "stop-loss", "liquidity"),
    "market-cap-liquidity-slippage": ("market-cap", "fdv", "liquidity", "slippage", "trading-volume"),
}


def _link_terms(body):
    import re
    done = set()

    def sub(m):
        k = m.group(1).lower()
        g = GLOSS.get(k)
        if not g or g in done:
            return m.group(0)
        done.add(g)
        return f"<a href=/glossary/{g}>{m.group(0)}</a>"
    return re.sub(r"<b>([^<]{2,40})</b>", sub, body)


def _chips(slug):
    ts = TERMS.get(slug, ())
    if not ts:
        return ""
    return ("<h2 class=s>Terms in this post</h2><div class=chips>"
            + "".join(f"<a href=/glossary/{t}>{t.replace('-', ' ')}</a>" for t in ts)
            + "<a href=/glossary>All terms →</a></div>")


def _posts():
    from ui.blogposts import POSTS
    return POSTS


def get(slug):
    return next((p for p in _posts() if p["slug"] == slug), None)


def urls():
    """[(path, priority)] for the sitemap."""
    return [("/blog", "0.8")] + [(f"/blog/{p['slug']}", "0.7") for p in _posts()]


def _og(p):
    name = f"blog-{p['slug']}.png"
    from ui.landing import STATIC
    return f"/static/landing/{name}" if os.path.isfile(os.path.join(STATIC, name)) else "/static/landing/kol.jpg"


def index():
    from ui.public import _shell
    cards = "".join(f"<a href=/blog/{p['slug']}><em>{esc(p['tag'])}</em><b>{esc(p['h1'])}</b>"
                    f"<span>{esc(p['desc'])}</span></a>" for p in _posts())
    body = ("<div class=art style='max-width:none'><section class=ph1><div class=eyebrow>KriptoRadar blog</div>"
            "<h1>Solana meme coin research, in plain words</h1><p class=lead>How wallet tracking, copy trading, "
            "influencer calls and rug pulls really work, measured on thousands of tokens we track every day.</p>"
            f"</section><div class=bl>{cards}</div>"
            "<div class=lock><p>Members see these signals live: new tokens, influencer calls and wallets worth "
            "copying, with a rug shield on every buy.</p><a class='btn sm' href=/#pristup>Request access</a></div></div>")
    jsonld = _ld({"@context": "https://schema.org", "@type": "Blog", "name": "KriptoRadar blog",
                  "url": _base() + "/blog",
                  "blogPost": [{"@type": "BlogPosting", "headline": p["h1"], "url": f"{_base()}/blog/{p['slug']}",
                                "datePublished": p["date"]} for p in _posts()]})
    return _shell("en", "KriptoRadar blog: Solana meme coins, wallet tracking, copy trading and rug pulls",
                  "Data-backed guides to Solana meme coin trading: wallet tracking, copy trading, crypto influencers "
                  "(KOLs), pump.fun and how to spot a rug pull.", "/blog", None, body, jsonld=jsonld,
                  og_image="/static/landing/kol.jpg")


def _base():
    return os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")


def _ld(obj):
    return '<script type="application/ld+json">' + json.dumps(obj).replace("</", "<\\/") + "</script>"


def page(slug):
    """HTML of one post, or None."""
    from ui.public import _shell
    p = get(slug)
    if not p:
        return None
    posts = _posts()
    i = posts.index(p)
    rel = [get(s) for s in p.get("related", ()) if get(s)] or [posts[(i + k) % len(posts)] for k in (1, 2, 3)]
    rel_html = "".join(f"<a href=/blog/{r['slug']}><em>{esc(r['tag'])}</em><b>{esc(r['h1'])}</b>"
                       f"<span>{esc(r['desc'])}</span></a>" for r in rel[:3])
    url = f"{_base()}/blog/{slug}"
    jsonld = _ld({"@context": "https://schema.org", "@graph": [
        {"@type": "BlogPosting", "headline": p["h1"], "description": p["desc"], "datePublished": p["date"],
         "dateModified": p.get("updated", p["date"]), "mainEntityOfPage": url, "image": _base() + _og(p),
         "keywords": ", ".join(p["kw"]), "author": {"@type": "Organization", "name": "KriptoRadar"},
         "publisher": {"@type": "Organization", "name": "KriptoRadar"}},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Blog", "item": _base() + "/blog"},
            {"@type": "ListItem", "position": 2, "name": p["h1"], "item": url}]}]})
    body = (f"<article class=art><section class=ph1><div class=crumb><a href=/blog>← Blog</a> · {esc(p['tag'])}</div>"
            f"<h1>{esc(p['h1'])}</h1><div class=meta>{_date(p['date'])} · {p['mins']} min read · KriptoRadar research"
            f"</div><div class=tldr><b>Short answer</b><p>{p['tldr']}</p></div></section>{_link_terms(p['body'])}"
            "<div class=lock><p>KriptoRadar does this for you in real time: every new Solana token, every influencer "
            "call and every tracked wallet, scored and filtered for rugs.</p>"
            "<a class='btn sm' href=/#pristup>Request access</a></div>"
            "<p class=note>Not financial advice. Numbers are measurements of past tokens and calls; meme coins are "
            "extremely risky and most go to zero.</p></article>"
            f"{_chips(slug)}<h2 class=s>Read next</h2><div class=bl>{rel_html}</div>")
    return _shell("en", p["title"], p["desc"], f"/blog/{slug}", None, body, jsonld=jsonld, og_image=_og(p),
                  og_type="article")


def _date(d):
    y, m, dd = d.split("-")
    return f"{int(dd)} {['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'][int(m) - 1]} {y}"
