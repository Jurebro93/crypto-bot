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
         "hit rate": "hit-rate", "late calls": "late-call", "dollar-cost averaging": "dca", "serial creator": "dev-wallet",
         # Croatian versions
         "poziv": "crypto-call", "serijski kreator": "dev-wallet", "diplomira": "graduation", "snajper": "sniper-bot",
         "likvidnost": "liquidity", "pogodak": "hit-rate", "kasni pozivi": "late-call"}
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


L = {
    "en": dict(base="/blog", home="/", crumb="← Blog", read="min read", by="KriptoRadar research", short="Short answer",
               terms="Terms in this post", all_terms="All terms →", next="Read next", cta="Request access",
               lock="KriptoRadar does this for you in real time: every new Solana token, every influencer call and every "
                    "tracked wallet, scored and filtered for rugs.",
               note="Not financial advice. Numbers are measurements of past tokens and calls; meme coins are extremely "
                    "risky and most go to zero.",
               i_h1="Solana meme coin research, in plain words",
               i_lead="How wallet tracking, copy trading, influencer calls and rug pulls really work, measured on "
                      "thousands of tokens we track every day.",
               i_lock="Members see these signals live: new tokens, influencer calls and wallets worth copying, with a rug "
                      "shield on every buy.",
               i_title="KriptoRadar blog: Solana meme coins, wallet tracking, copy trading and rug pulls",
               i_desc="Data-backed guides to Solana meme coin trading: wallet tracking, copy trading, crypto influencers "
                      "(KOLs), pump.fun and how to spot a rug pull.",
               months=("January", "February", "March", "April", "May", "June", "July", "August", "September",
                       "October", "November", "December")),
    "hr": dict(base="/hr/blog", home="/hr", crumb="← Blog", read="min čitanja", by="KriptoRadar istraživanje",
               short="Kratki odgovor", terms="Pojmovi u ovom tekstu", all_terms="Svi pojmovi →", next="Pročitaj još",
               cta="Zatraži pristup",
               lock="KriptoRadar to radi za tebe u stvarnom vremenu: svaki novi Solana token, svaki poziv influencera i "
                    "svaki praćeni novčanik, ocijenjen i provjeren na rug.",
               note="Nije financijski savjet. Brojke su mjerenja prošlih tokena i poziva; meme coini su izuzetno "
                    "rizični i većina završi na nuli.",
               i_h1="Istraživanje Solana meme coina, jednostavnim riječima",
               i_lead="Kako stvarno rade praćenje novčanika, copy trading, pozivi influencera i rug pullovi, izmjereno "
                      "na tisućama tokena koje pratimo svaki dan.",
               i_lock="Članovi vide ove signale uživo: nove tokene, pozive influencera i novčanike koje vrijedi "
                      "kopirati, uz zaštitu od ruga na svakoj kupnji.",
               i_title="KriptoRadar blog: Solana meme coini, praćenje novčanika, copy trading i rug pullovi",
               i_desc="Vodiči za trgovanje Solana meme coinima uz stvarne podatke: praćenje novčanika, copy trading, "
                      "kripto influenceri (KOL), pump.fun i kako prepoznati rug pull.",
               months=("siječnja", "veljače", "ožujka", "travnja", "svibnja", "lipnja", "srpnja", "kolovoza", "rujna",
                       "listopada", "studenoga", "prosinca")),
}


def _gl_href(en_slug, lang):
    if lang == "en":
        return f"/glossary/{en_slug}"
    from ui import glossary_public as GP
    e = GP.BY_EN.get(en_slug)
    return f"/hr/rjecnik/{e['hr']}" if e else None


def _gl_name(en_slug, lang):
    from ui import glossary_public as GP
    e = GP.BY_EN.get(en_slug)
    if not e:
        return en_slug.replace("-", " ")
    return e["name"] if lang == "en" else GP.hr_term(e)["name"]


def _link_terms(body, lang="en"):
    import re
    done = set()

    def sub(m):
        g = GLOSS.get(m.group(1).lower())
        href = g and _gl_href(g, lang)
        if not href or g in done:
            return m.group(0)
        done.add(g)
        return f"<a href={href}>{m.group(0)}</a>"
    return re.sub(r"<b>([^<]{2,40})</b>", sub, body)


def _chips(en_slug, lang="en"):
    t = L[lang]
    links = [(h, _gl_name(g, lang)) for g in TERMS.get(en_slug, ()) for h in [_gl_href(g, lang)] if h]
    if not links:
        return ""
    return (f"<h2 class=s>{t['terms']}</h2><div class=chips>"
            + "".join(f"<a href={h}>{esc(n)}</a>" for h, n in links)
            + f"<a href={'/glossary' if lang == 'en' else '/hr/rjecnik'}>{t['all_terms']}</a></div>")


def _posts():
    from ui.blogposts import POSTS
    return POSTS


def _hr():
    from ui.blogposts_hr import HR
    return HR


def view(p, lang):
    """The post in one language: EN post dict, or its Croatian texts on top (keeps en slug in 'en')."""
    if lang == "en":
        return dict(p, en=p["slug"])
    h = _hr().get(p["slug"])
    return dict(p, **h, en=p["slug"], kw=p["kw"]) if h else None


def get(slug, lang="en"):
    """Post by its slug in that language (view), or None."""
    for p in _posts():
        v = view(p, lang)
        if v and v["slug"] == slug:
            return v
    return None


def views(lang):
    return [v for v in (view(p, lang) for p in _posts()) if v]


def urls():
    """[(path_en, path_hr or None, priority)] for the sitemap."""
    out = [("/blog", "/hr/blog", "0.8")]
    for p in _posts():
        h = _hr().get(p["slug"])
        out.append((f"/blog/{p['slug']}", f"/hr/blog/{h['slug']}" if h else None, "0.7"))
    return out


def _og(p):
    name = f"blog-{p['en']}.png"
    from ui.landing import STATIC
    return f"/static/landing/{name}" if os.path.isfile(os.path.join(STATIC, name)) else "/static/landing/kol.jpg"


def _card(v, lang):
    return (f"<a href={L[lang]['base']}/{v['slug']}><em>{esc(v['tag'])}</em><b>{esc(v['h1'])}</b>"
            f"<span>{esc(v['desc'])}</span></a>")


def index(lang="en"):
    from ui.public import _shell
    t = L[lang]
    vs = views(lang)
    body = (f"<div class=art style='max-width:none'><section class=ph1><div class=eyebrow>KriptoRadar blog</div>"
            f"<h1>{t['i_h1']}</h1><p class=lead>{t['i_lead']}</p></section>"
            f"<div class=bl>{''.join(_card(v, lang) for v in vs)}</div>"
            f"<div class=lock><p>{t['i_lock']}</p><a class='btn sm' href={t['home']}#pristup>{t['cta']}</a></div></div>")
    jsonld = _ld({"@context": "https://schema.org", "@type": "Blog", "name": "KriptoRadar blog", "inLanguage": lang,
                  "url": _base() + t["base"],
                  "blogPost": [{"@type": "BlogPosting", "headline": v["h1"], "url": f"{_base()}{t['base']}/{v['slug']}",
                                "datePublished": v["date"]} for v in vs]})
    return _shell(lang, t["i_title"], t["i_desc"], "/blog", "/hr/blog", body, jsonld=jsonld,
                  og_image="/static/landing/kol.jpg")


def _base():
    return os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")


def _ld(obj):
    return '<script type="application/ld+json">' + json.dumps(obj).replace("</", "<\\/") + "</script>"


def page(slug, lang="en"):
    """HTML of one post in that language, or None."""
    from ui.public import _shell
    t = L[lang]
    p = get(slug, lang)
    if not p:
        return None
    vs = views(lang)
    i = next(k for k, v in enumerate(vs) if v["en"] == p["en"])
    rel = [v for r in p.get("related", ()) for v in vs if v["en"] == r] or [vs[(i + k) % len(vs)] for k in (1, 2, 3)]
    url = f"{_base()}{t['base']}/{slug}"
    jsonld = _ld({"@context": "https://schema.org", "@graph": [
        {"@type": "BlogPosting", "headline": p["h1"], "description": p["desc"], "datePublished": p["date"],
         "dateModified": p.get("updated", p["date"]), "mainEntityOfPage": url, "image": _base() + _og(p),
         "inLanguage": lang, "keywords": ", ".join(p["kw"]), "author": {"@type": "Organization", "name": "KriptoRadar"},
         "publisher": {"@type": "Organization", "name": "KriptoRadar"}},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Blog", "item": _base() + t["base"]},
            {"@type": "ListItem", "position": 2, "name": p["h1"], "item": url}]}]})
    body = (f"<article class=art><section class=ph1><div class=crumb><a href={t['base']}>{t['crumb']}</a> · "
            f"{esc(p['tag'])}</div><h1>{esc(p['h1'])}</h1><div class=meta>{_date(p['date'], lang)} · {p['mins']} "
            f"{t['read']} · {t['by']}</div><div class=tldr><b>{t['short']}</b><p>{p['tldr']}</p></div></section>"
            f"{_link_terms(p['body'], lang)}<div class=lock><p>{t['lock']}</p>"
            f"<a class='btn sm' href={t['home']}#pristup>{t['cta']}</a></div><p class=note>{t['note']}</p></article>"
            f"{_chips(p['en'], lang)}<h2 class=s>{t['next']}</h2><div class=bl>{''.join(_card(r, lang) for r in rel[:3])}</div>")
    en = f"/blog/{p['en']}"
    hr_v = view(next(x for x in _posts() if x["slug"] == p["en"]), "hr")
    hr = f"/hr/blog/{hr_v['slug']}" if hr_v else None
    return _shell(lang, p["title"], p["desc"], en, hr, body, jsonld=jsonld, og_image=_og(p), og_type="article")


def _date(d, lang="en"):
    y, m, dd = d.split("-")
    mon = L[lang]["months"][int(m) - 1]
    return f"{int(dd)} {mon} {y}" if lang == "en" else f"{int(dd)}. {mon} {y}."
