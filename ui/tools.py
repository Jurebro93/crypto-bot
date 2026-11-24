"""Public "Best crypto tools" topic cluster (indexable, English main, Croatian under /hr).

- /best-crypto-tools               pillar page (EN)     /hr/najbolji-kripto-alati               (HR)
- /best-crypto-tools/<en_slug>     category page (EN)   /hr/najbolji-kripto-alati/<hr_slug>     (HR)

Content lives in ui/toolsdata.py. Pages are rendered through ui.public._shell and cached by ui.public.route.
Each category: short answer, comparison table, one chart, a card per tool (features, prices, what to watch out for),
how to choose, FAQ (FAQPage JSON-LD), sources, glossary chips, related blog posts and links to the other categories.
"""
import json
import os

from ui.html import esc

BASE = {"en": "/best-crypto-tools", "hr": "/hr/najbolji-kripto-alati"}

L = {
    "en": dict(crumb="← Best crypto tools", short="Short answer", table_h="Comparison table",
               cols=("Tool", "Best for", "Chains", "Free", "Paid plans / fees"), detail_h="The tools in detail",
               site="Website", free="Free", paid="Paid", watch="Watch out", choose_h="How to choose", faq_h="FAQ",
               src_h="Sources (checked 1 November 2026)", terms="Terms on this page", all_terms="All terms →",
               blog_h="Related guides", other_h="Other tool categories", ours="Our tool", n_tools="tools compared",
               checked="Prices checked 1 November 2026", by="MemeSonar research", chart_h="In numbers",
               cta="Request access", home="/",
               lock="MemeSonar puts wallet tracking, influencer calls and a rug check on every new Solana token in one "
                    "app. Invite only.",
               note="Not financial advice. Prices and fees are taken from each vendor's page on the date above and "
                    "change often; check before you pay or deposit. No affiliate links.",
               glossary="/glossary"),
    "hr": dict(crumb="← Najbolji kripto alati", short="Kratki odgovor", table_h="Usporedna tablica",
               cols=("Alat", "Najbolji za", "Mreže", "Besplatno", "Plaćeni planovi / naknade"), detail_h="Alati detaljno",
               site="Web stranica", free="Besplatno", paid="Plaćeno", watch="Na što paziti", choose_h="Kako odabrati",
               faq_h="Česta pitanja", src_h="Izvori (provjereno 1. studenoga 2026.)", terms="Pojmovi na ovoj stranici",
               all_terms="Svi pojmovi →", blog_h="Povezani vodiči", other_h="Ostale kategorije alata", ours="Naš alat",
               n_tools="alata uspoređeno", checked="Cijene provjerene 1. studenoga 2026.", by="MemeSonar istraživanje",
               chart_h="U brojkama", cta="Zatraži pristup", home="/hr",
               lock="MemeSonar u jednoj aplikaciji spaja praćenje novčanika, pozive influencera i provjeru ruga na "
                    "svakom novom Solana tokenu. Samo uz pozivnicu.",
               note="Nije financijski savjet. Cijene i naknade preuzete su sa stranica proizvođača na navedeni datum i "
                    "često se mijenjaju; provjeri prije plaćanja ili uplate. Bez affiliate linkova.",
               glossary="/hr/rjecnik"),
}

CSS = """
.tc{border:1px solid var(--line);border-radius:18px;padding:18px 20px;margin:16px 0;background:#fff}
.tc h3{margin:0 0 4px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}.tc h3 a{font-size:14px;font-weight:500}
.tc p{margin:6px 0}.tc ul{margin:6px 0 8px}.tc .pr{display:grid;grid-template-columns:110px 1fr;gap:2px 12px;font-size:15.5px;
background:var(--soft);border-radius:12px;padding:10px 14px;margin:10px 0}.tc .pr b{color:var(--mut);font-weight:600}
.tc .wo{color:var(--mut);font-size:15.5px}.badge{font-size:12px;font-weight:650;color:#fff;background:var(--acc);
border-radius:999px;padding:2px 10px}.ttab td{white-space:normal;min-width:120px;font-size:14.5px;vertical-align:top}
.ttab td:first-child{min-width:100px;font-weight:650}.src{font-size:14.5px;color:var(--mut)}.src a{color:var(--mut)}
.faq h3{font-size:18px;margin:22px 0 4px}
.art .tldr p b{display:inline;font-size:inherit;color:inherit;text-transform:none;letter-spacing:0;margin:0}
@media(max-width:560px){.tc .pr{grid-template-columns:1fr}}
"""


def _data():
    from ui import toolsdata
    return toolsdata


def _base():
    return os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")


def _ld(obj):
    return '<script type="application/ld+json">' + json.dumps(obj).replace("</", "<\\/") + "</script>"


def get(slug, lang):
    key = "en_slug" if lang == "en" else "hr_slug"
    return next((c for c in _data().CATS if c[key] == slug), None)


def path(c, lang):
    return f"{BASE[lang]}/{c['en_slug'] if lang == 'en' else c['hr_slug']}"


def urls():
    """[(path_en, path_hr, priority)] for the sitemap."""
    return [(BASE["en"], BASE["hr"], "0.8")] + [(path(c, "en"), path(c, "hr"), "0.7") for c in _data().CATS] + _bot_urls()


def _bot_urls():
    try:
        from ui import botguides
        return botguides.urls()
    except Exception:
        return []


def _chart(ch, lang):
    from ui.blogviz import bars
    i = 0 if lang == "en" else 1
    rows = [(lab[i], v, note[i]) for lab, v, note in ch["rows"]]
    return bars(ch["title"][i], rows, sub=ch["sub"][i], fmt=ch["fmt"], hl=ch.get("hl"), source=ch["source"][i],
                lang=lang)


def _ext(url, label):
    if url.startswith("/"):
        return ""
    return f"<a href=\"{esc(url)}\" rel=\"nofollow noopener\" target=_blank>{esc(label)} ↗</a>"


def _tool_card(t, lang):
    s, x = L[lang], t[lang]
    badge = f"<span class=badge>{s['ours']}</span>" if t["ours"] else ""
    link = _ext(t["url"], s["site"]) or f"<a href={s['home']}#pristup>{s['cta']} →</a>"
    feats = "".join(f"<li>{esc(f)}</li>" for f in x["feats"])
    paid = "" if x["paid"] == "–" else f"<b>{s['paid']}</b><span>{esc(x['paid'])}</span>"
    return (f"<div class=tc id=\"{_anchor(t['name'])}\"><h3>{esc(t['name'])} {badge} {link}</h3>"
            f"<p class=meta style='margin:0'>{esc(x['best'])} · {esc(_data().chains(t, lang))}</p><p>{esc(x['what'])}</p>"
            f"<ul>{feats}</ul><div class=pr><b>{s['free']}</b><span>{esc(x['free'])}</span>{paid}</div>"
            f"<p class=wo><b>{s['watch']}:</b> {esc(x['watch'])}</p></div>")


def _anchor(name):
    import re
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _table(tools, lang):
    s = L[lang]
    head = "".join(f"<th>{c}</th>" for c in s["cols"])
    rows = []
    for t in tools:
        x = t[lang]
        name = f"<a href=#{_anchor(t['name'])}>{esc(t['name'])}</a>" + (f" <span class=badge>{s['ours']}</span>"
                                                                       if t["ours"] else "")
        rows.append(f"<tr><td>{name}</td><td>{esc(x['best'])}</td><td>{esc(_data().chains(t, lang))}</td><td>{esc(x['free'])}</td>"
                    f"<td>{esc(x['paid'])}</td></tr>")
    return f"<div class=tw><table class=ttab><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


def _faq(faq, lang):
    html = "<div class=faq>" + "".join(f"<h3>{esc(q)}</h3><p>{esc(a)}</p>" for q, a in faq) + "</div>"
    ld = {"@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": q,
                                              "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]}
    return html, ld


def _chips(terms, lang):
    from ui import blog
    s = L[lang]
    links = [(h, blog._gl_name(g, lang)) for g in terms for h in [blog._gl_href(g, lang)] if h]
    if not links:
        return ""
    return (f"<h2 class=s>{s['terms']}</h2><div class=chips>" + "".join(f"<a href={h}>{esc(n)}</a>" for h, n in links)
            + f"<a href={s['glossary']}>{s['all_terms']}</a></div>")


def _blog_cards(slugs, lang):
    from ui import blog
    vs = {v["en"]: v for v in blog.views(lang)}
    base = "/blog" if lang == "en" else "/hr/blog"
    out = []
    for sl in slugs:
        v = vs.get(sl)
        if v:
            out.append(f"<a href={base}/{v['slug']}><em>{esc(v['tag'])}</em><b>{esc(v['h1'])}</b>"
                       f"<span>{esc(v['desc'])}</span></a>")
    return "".join(out)


def _cat_card(c, lang):
    x = c[lang]
    return (f"<a href={path(c, lang)}><em>{esc(x['tag'])}</em><b>{esc(x['h1'])}</b>"
            f"<span>{esc(x['desc'])}</span></a>")


def page(slug, lang="en"):
    """HTML of one category page, or None."""
    from ui.public import _shell
    c = get(slug, lang)
    if not c:
        from ui import botguides   # Telegram bot overview + setup guides live under the same base path
        return botguides.page(slug, lang)
    s, x = L[lang], c[lang]
    url = _base() + path(c, lang)
    faq_html, faq_ld = _faq(x["faq"], lang)
    choose = "".join(f"<li>{i}</li>" for i in x["choose"])
    src = "".join(f"<li>{_ext(u, n)}</li>" for n, u in c["sources"])
    blog_html = _blog_cards(c["blog"], lang)
    others = "".join(_cat_card(o, lang) for o in _data().CATS if o is not c)
    tools = c["tools"]
    body = (f"<article class=art><section class=ph1><div class=crumb><a href={BASE[lang]}>{s['crumb']}</a> · "
            f"{esc(x['tag'])}</div><h1>{esc(x['h1'])}</h1><div class=meta>{s['checked']} · {len(tools)} "
            f"{s['n_tools']} · {s['by']}</div><div class=tldr><b>{s['short']}</b><p>{x['tldr']}</p></div></section>"
            f"{x['intro']}{_bot_box(c, lang)}<h2>{s['table_h']}</h2></article>{_table(tools, lang)}<article class=art>"
            f"<h2>{s['chart_h']}</h2>{x['chart_note']}{_chart(c['chart'], lang)}"
            f"<h2>{s['detail_h']}</h2>{''.join(_tool_card(t, lang) for t in tools)}"
            f"<h2>{s['choose_h']}</h2><ol>{choose}</ol><h2>{s['faq_h']}</h2>{faq_html}"
            f"<div class=lock><p>{s['lock']}</p><a class='btn sm' href={s['home']}#pristup>{s['cta']}</a></div>"
            f"<p class=note>{s['note']}</p><h2 style='font-size:19px'>{s['src_h']}</h2><ul class=src>{src}</ul></article>"
            f"{_chips(c['terms'], lang)}"
            + (f"<h2 class=s>{s['blog_h']}</h2><div class=bl>{blog_html}</div>" if blog_html else "")
            + f"<h2 class=s>{s['other_h']}</h2><div class=bl>{others}</div>")
    d = _data().CHECKED
    jsonld = _ld({"@context": "https://schema.org", "@graph": [
        {"@type": "Article", "headline": x["h1"], "description": x["desc"], "datePublished": d, "dateModified": d,
         "mainEntityOfPage": url, "inLanguage": lang, "author": {"@type": "Organization", "name": "MemeSonar"},
         "publisher": {"@type": "Organization", "name": "MemeSonar"}},
        {"@type": "ItemList", "name": x["h1"], "itemListElement": [
            {"@type": "ListItem", "position": i, "name": t["name"],
             **({"url": t["url"]} if not t["url"].startswith("/") else {})} for i, t in enumerate(tools, 1)]},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": s["crumb"].lstrip("← "), "item": _base() + BASE[lang]},
            {"@type": "ListItem", "position": 2, "name": x["short"], "item": url}]},
        faq_ld]})
    return _shell(lang, x["title"], x["desc"], path(c, "en"), path(c, "hr"), body, jsonld=jsonld, og_type="article")


def _bot_box(c, lang):
    """On the trading-bots page: a box linking the Telegram bot overview and setup guides."""
    if c["key"] != "trading":
        return ""
    from ui import botguides
    return botguides.promo(lang)


def index(lang="en"):
    """The pillar page."""
    from ui.public import _shell
    D = _data()
    s, p = L[lang], D.PILLAR[lang]
    i = 0 if lang == "en" else 1
    cats = {c["key"]: c for c in D.CATS}
    rows = []
    for k, picks in D.PICKS.items():
        c = cats[k]
        free, paid, price = picks[i]
        rows.append(f"<tr><td><a href={path(c, lang)}>{esc(c[lang]['short'])}</a></td><td>{esc(free)}</td>"
                    f"<td>{esc(paid)}</td><td>{esc(price)}</td></tr>")
    head = "".join(f"<th>{h}</th>" for h in p["cols"])
    picks_tbl = f"<div class=tw><table class=ttab><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    faq_html, faq_ld = _faq(p["faq"], lang)
    n_tools = len({t["name"] for c in D.CATS for t in c["tools"]})
    body = (f"<article class=art><section class=ph1><div class=eyebrow>MemeSonar</div><h1>{esc(p['h1'])}</h1>"
            f"<p class=lead>{esc(p['lead'])}</p><div class=meta>{s['checked']} · {n_tools} {s['n_tools']}</div>"
            f"<div class=tldr><b>{s['short']}</b><p>{p['tldr']}</p></div></section>"
            f"<h2>{p['picks_h']}</h2></article>{picks_tbl}"
            f"<h2 class=s>{p['cats_h']}</h2><div class=bl>{''.join(_cat_card(c, lang) for c in D.CATS)}</div>"
            f"<article class=art><h2>{p['chart_h']}</h2>{p['chart_note']}{_chart(D.PILLAR_CHART, lang)}"
            f"<h2>{p['stack_h']}</h2><ul>{''.join(f'<li>{x}</li>' for x in p['stack'])}</ul>"
            f"<h2>{p['how_h']}</h2><ul>{''.join(f'<li>{x}</li>' for x in p['how'])}</ul>"
            f"<h2>{s['faq_h']}</h2>{faq_html}"
            f"<div class=lock><p>{s['lock']}</p><a class='btn sm' href={s['home']}#pristup>{s['cta']}</a></div>"
            f"<p class=note>{s['note']}</p></article>")
    url = _base() + BASE[lang]
    jsonld = _ld({"@context": "https://schema.org", "@graph": [
        {"@type": "CollectionPage", "name": p["h1"], "description": p["desc"], "url": url, "inLanguage": lang,
         "hasPart": [{"@type": "Article", "headline": c[lang]["h1"], "url": _base() + path(c, lang)} for c in D.CATS]},
        faq_ld]})
    return _shell(lang, p["title"], p["desc"], BASE["en"], BASE["hr"], body, jsonld=jsonld)
