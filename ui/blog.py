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
.bl a.cvr{padding:0;overflow:hidden}.bl a.cvr .cv{display:block;width:100%;height:auto;border-bottom:1px solid var(--line)}
.bl a.cvr .bt{display:block;padding:16px 20px 20px}
.art .bcov{margin:0 0 22px;border:1px solid var(--line);border-radius:18px;overflow:hidden}.art .bcov .cv{display:block;width:100%;height:auto}
.bcat{margin:4px 0 22px;overflow-x:auto;flex-wrap:nowrap;padding-bottom:4px;scrollbar-width:none}.bcat::-webkit-scrollbar{display:none}
.bcat a{white-space:nowrap}.bcat a.on{background:var(--fg);color:#fff;border-color:var(--fg)}
h2.s a{color:inherit}h2.s a:hover{color:var(--acc)}
"""


# Bold terms in post bodies that get a link to their public glossary entry (first occurrence per post).
GLOSS = {"wallet tracker": "smart-money", "smart money": "smart-money", "sniper": "sniper-bot", "rug pull": "rug-pull",
         "mint authority": "mint-authority", "graduates": "graduation", "call": "crypto-call", "bundle": "bundler",
         "slippage": "slippage", "market cap": "market-cap", "liquidity": "liquidity", "kol": "kol", "fdv": "fdv",
         "dex": "dex", "contract address": "contract-address", "bundles": "bundler", "snipers": "sniper-bot",
         "adresa ugovora": "contract-address", "adresu ugovora": "contract-address", "bundlovi": "bundler", "spread": "cex", "priority fee": "priority-fee", "stars": "stars-vs-rising-stars",
         "zvijezde": "stars-vs-rising-stars",
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
    "best-crypto-exchanges-croatia": ("cex", "dex", "crypto-wallet", "hardware-wallet"),
    "how-to-buy-solana-meme-coins": ("crypto-wallet", "contract-address", "dex", "slippage", "rug-pull"),
    "how-to-use-jupiter-swap": ("dex", "slippage", "contract-address", "dca", "liquidity"),
    "what-is-a-pump-and-dump": ("rug-pull", "bundler", "sniper-bot", "kol", "wallet-cluster"),
    "crypto-cards-croatia": ("cex", "crypto-wallet", "pnl"),
    "crypto-tax-croatia": ("pnl", "roi", "cex", "dca"),
    "company-crypto-investment-croatia": ("multisig", "hardware-wallet", "cex", "pnl"),
    "why-big-influencer-calls-are-hard-to-trade": ("kol", "stars-vs-rising-stars", "priority-fee", "front-running",
                                                   "sniper-bot", "hit-rate"),
    "address-poisoning": ("crypto-wallet", "contract-address", "cex", "hardware-wallet"),
    "zero-trust-support-calls": ("hardware-wallet", "crypto-wallet", "cex", "multisig"),
    "polymarket-rules-checklist": ("token", "liquidity", "crypto-wallet"),
    "polymarket-insider-moves": ("smart-money", "insider-wallet", "wallet-cluster", "memecoin"),
    "perps-settings-after-october-10": ("liquidity", "stop-loss", "take-profit", "pnl", "cex"),
    "tokens-sent-to-kol-wallets": ("copy-trading", "kol", "smart-money", "dev-wallet", "dex"),
    "what-to-do-with-an-airdrop": ("token", "fdv", "liquidity", "take-profit"),
    "fake-volume-check": ("trading-volume", "liquidity", "dex", "cex", "wallet-cluster"),
    "after-kaito-yaps": ("kol", "crypto-call", "bot-account"),
    "fair-token-launch-cca": ("launchpad", "sniper-bot", "bundler", "liquidity", "fdv"),
}


# Blog categories: key -> (EN slug, HR slug, EN name, HR name, EN intro, HR intro, posts by EN slug in reading order).
CATS = [
    ("guides", "vodici", "Guides", "Vodiči",
     "Step by step: buying meme coins, swapping on Jupiter, trading plans, DCA and what slippage costs.",
     "Korak po korak: kupnja meme coina, swap na Jupiteru, plan trgovanja, DCA i koliko košta slippage.",
     ("how-to-buy-solana-meme-coins", "how-to-use-jupiter-swap", "how-to-trade-meme-coins", "what-is-pump-fun",
      "market-cap-liquidity-slippage", "what-is-dca-in-crypto", "perps-settings-after-october-10",
      "what-to-do-with-an-airdrop")),
    ("exchanges-and-cards", "mjenjacnice-i-kartice", "Exchanges and cards", "Mjenjačnice i kartice",
     "Where to buy crypto legally in Croatia and the EU, and which cards let you spend it.",
     "Gdje legalno kupiti kripto u Hrvatskoj i EU i kojim karticama ga možeš trošiti.",
     ("best-crypto-exchanges-croatia", "crypto-cards-croatia")),
    ("tax-and-law", "porez-i-zakon", "Tax and law", "Porez i zakon",
     "Crypto tax in Croatia, JOPPD, MiCA and investing through a company.",
     "Porez na kripto u Hrvatskoj, JOPPD, MiCA i ulaganje preko firme.",
     ("crypto-tax-croatia", "company-crypto-investment-croatia")),
    ("rugs-and-scams", "rugovi-i-prevare", "Rugs and scams", "Rugovi i prevare",
     "How rug pulls, pump and dumps, bundles and snipers work, measured on thousands of tokens.",
     "Kako rade rug pullovi, pump and dump, bundleri i snajperi, izmjereno na tisućama tokena.",
     ("how-to-spot-a-rug-pull", "what-is-a-pump-and-dump", "bundles-and-snipers", "fake-volume-check",
      "address-poisoning", "zero-trust-support-calls")),
    ("wallets-and-influencers", "novcanici-i-influenceri", "Wallets and influencers", "Novčanici i influenceri",
     "Wallet tracking, copy trading and crypto influencer (KOL) calls: what the data says works.",
     "Praćenje novčanika, copy trading i pozivi kripto influencera (KOL): što prema podacima radi.",
     ("what-is-a-kol-in-crypto", "why-big-influencer-calls-are-hard-to-trade", "influencer-clustering",
      "what-is-wallet-tracking", "what-is-copy-trading", "tokens-sent-to-kol-wallets")),
    ("prediction-markets", "prediction-marketi", "Prediction markets", "Prediction marketi",
     "How Polymarket markets resolve, how to read the rules and how to spot odds that move before the news.",
     "Kako se rješavaju Polymarket tržišta, kako čitati pravila i kako uočiti kvote koje se pomaknu prije vijesti.",
     ("polymarket-rules-checklist", "polymarket-insider-moves")),
    ("for-crypto-projects", "za-kripto-projekte", "For crypto projects", "Za kripto projekte",
     "For founders: fair token launches without snipers and getting real visibility on X.",
     "Za osnivače: fer lansiranje tokena bez snajpera i stvarna vidljivost na X-u.",
     ("fair-token-launch-cca", "after-kaito-yaps")),
]
CAT_OF = {en: c for c in CATS for en in c[6]}


def cat_path(c, lang):
    return f"/blog/category/{c[0]}" if lang == "en" else f"/hr/blog/kategorija/{c[1]}"


def cat_by_slug(slug, lang):
    return next((c for c in CATS if c[0 if lang == "en" else 1] == slug), None)


def cat_nav(lang, active=None):
    """Category chip row (index, category pages, under each post)."""
    t = L[lang]
    chips = [f"<a href={t['base']}{' class=on' if active is None else ''}>{t['all']}</a>"]
    chips += [f"<a href={cat_path(c, lang)}{' class=on' if active and active[0] == c[0] else ''}>{c[2 if lang == 'en' else 3]}</a>"
              for c in CATS]
    return f"<nav class='chips bcat' aria-label=Blog>{''.join(chips)}</nav>"


L = {
    "en": dict(base="/blog", home="/", crumb="← Blog", all="All posts", c_title="{c}: MemeSonar blog",
               c_more="More on MemeSonar", read="min read", by="MemeSonar research", short="Short answer",
               terms="Terms in this post", all_terms="All terms →", next="Read next", cta="Request access",
               lock="MemeSonar does this for you in real time: every new Solana token, every influencer call and every "
                    "tracked wallet, scored and filtered for rugs.",
               note="Not financial advice. Numbers are measurements of past tokens and calls; meme coins are extremely "
                    "risky and most go to zero.",
               i_h1="Solana meme coin research, in plain words",
               i_lead="How to buy, trade and stay safe with Solana meme coins, where to buy crypto legally in Croatia and "
                      "the EU, and how it is taxed. Measured on thousands of tokens we track every day.",
               i_lock="Members see these signals live: new tokens, influencer calls and wallets worth copying, with a rug "
                      "shield on every buy.",
               i_title="MemeSonar blog: Solana meme coins, exchanges, crypto tax in Croatia and rug pulls",
               i_desc="Data-backed crypto guides: buying Solana meme coins, MiCA-licensed exchanges and cards in Croatia, "
                      "crypto tax, wallet tracking, copy trading and how to spot a rug pull.",
               months=("January", "February", "March", "April", "May", "June", "July", "August", "September",
                       "October", "November", "December")),
    "hr": dict(base="/hr/blog", home="/hr", crumb="← Blog", all="Svi članci", c_title="{c}: MemeSonar blog",
               c_more="Još na MemeSonaru", read="min čitanja", by="MemeSonar istraživanje",
               short="Kratki odgovor", terms="Pojmovi u ovom tekstu", all_terms="Svi pojmovi →", next="Pročitaj još",
               cta="Zatraži pristup",
               lock="MemeSonar to radi za tebe u stvarnom vremenu: svaki novi Solana token, svaki poziv influencera i "
                    "svaki praćeni novčanik, ocijenjen i provjeren na rug.",
               note="Nije financijski savjet. Brojke su mjerenja prošlih tokena i poziva; meme coini su izuzetno "
                    "rizični i većina završi na nuli.",
               i_h1="Istraživanje Solana meme coina, jednostavnim riječima",
               i_lead="Kako kupiti, trgovati i ostati siguran sa Solana meme coinima, gdje legalno kupiti kripto u "
                      "Hrvatskoj i EU i kako se oporezuje. Izmjereno na tisućama tokena koje pratimo svaki dan.",
               i_lock="Članovi vide ove signale uživo: nove tokene, pozive influencera i novčanike koje vrijedi "
                      "kopirati, uz zaštitu od ruga na svakoj kupnji.",
               i_title="MemeSonar blog: Solana meme coini, mjenjačnice, porez na kripto i rug pullovi",
               i_desc="Kripto vodiči uz stvarne podatke: kupnja Solana meme coina, mjenjačnice i kartice s MiCA licencom u "
                      "Hrvatskoj, porez na kriptovalute, praćenje novčanika, copy trading i rug pullovi.",
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


# Matching "best tools" comparison pages (ui/tools.py), EN slug -> HR slug.
TOOLS = {"wallet-trackers": "pracenje-novcanika", "crypto-analysis-tools": "alati-za-analizu",
         "trading-bots": "trading-botovi", "rug-checkers": "provjera-ruga",
         "copy-trading-platforms": "copy-trading-platforme", "crypto-wallets": "kripto-novcanici",
         "telegram-trading-bots": "telegram-trading-botovi"}
TOOLS_FOR = {"what-is-wallet-tracking": ("wallet-trackers",), "what-is-copy-trading": ("copy-trading-platforms",),
             "what-is-a-kol-in-crypto": ("crypto-analysis-tools",), "influencer-clustering": ("crypto-analysis-tools",),
             "how-to-spot-a-rug-pull": ("rug-checkers",), "what-is-pump-fun": ("trading-bots", "rug-checkers"),
             "bundles-and-snipers": ("rug-checkers", "trading-bots"), "how-to-trade-meme-coins": ("trading-bots", "telegram-trading-bots"),
             "what-is-dca-in-crypto": ("trading-bots",), "market-cap-liquidity-slippage": ("crypto-analysis-tools",),
             "best-crypto-exchanges-croatia": ("crypto-wallets",), "how-to-buy-solana-meme-coins": ("crypto-wallets", "rug-checkers", "telegram-trading-bots"),
             "how-to-use-jupiter-swap": ("trading-bots", "crypto-wallets", "telegram-trading-bots"), "what-is-a-pump-and-dump": ("rug-checkers",),
             "crypto-cards-croatia": ("crypto-wallets",), "company-crypto-investment-croatia": ("crypto-wallets",),
             "why-big-influencer-calls-are-hard-to-trade": ("trading-bots", "crypto-analysis-tools", "telegram-trading-bots"),
             "address-poisoning": ("crypto-wallets",), "zero-trust-support-calls": ("crypto-wallets",),
             "tokens-sent-to-kol-wallets": ("wallet-trackers", "copy-trading-platforms"),
             "fake-volume-check": ("crypto-analysis-tools", "rug-checkers"), "what-to-do-with-an-airdrop": ("crypto-wallets",),
             "perps-settings-after-october-10": ("trading-bots",)}
TOOL_NAME = {"en": {"wallet-trackers": "Best wallet trackers", "crypto-analysis-tools": "Best crypto analysis tools",
                    "trading-bots": "Best Solana trading bots", "rug-checkers": "Best rug checkers",
                    "copy-trading-platforms": "Best copy trading platforms", "crypto-wallets": "Best crypto wallets",
                    "telegram-trading-bots": "Telegram trading bots and setup guides"},
             "hr": {"wallet-trackers": "Najbolji alati za praćenje novčanika", "crypto-analysis-tools": "Najbolji alati za analizu",
                    "trading-bots": "Najbolji Solana trading botovi", "rug-checkers": "Najbolji alati za provjeru ruga",
                    "copy-trading-platforms": "Najbolje copy trading platforme", "crypto-wallets": "Najbolji kripto novčanici",
                    "telegram-trading-bots": "Telegram trading botovi i vodiči za postavljanje"}}


def _tools(en_slug, lang="en"):
    ts = TOOLS_FOR.get(en_slug, ())
    if not ts:
        return ""
    base = "/best-crypto-tools/" if lang == "en" else "/hr/najbolji-kripto-alati/"
    links = " · ".join(f"<a href={base}{t if lang == 'en' else TOOLS[t]}>{TOOL_NAME[lang][t]}</a>" for t in ts)
    return f"<p class=note>{'Compare tools' if lang == 'en' else 'Usporedi alate'}: {links}</p>"


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
    out = [("/blog", "/hr/blog", "0.8")] + [(cat_path(c, "en"), cat_path(c, "hr"), "0.7") for c in CATS]
    for p in _posts():
        h = _hr().get(p["slug"])
        out.append((f"/blog/{p['slug']}", f"/hr/blog/{h['slug']}" if h else None, "0.7"))
    return out


def _og(p, lang="en"):
    """Share image: the post's cover JPG in its language (scripts/blog_covers.py), else the EN one, else a screenshot."""
    from ui.landing import STATIC
    for name in ((f"blog-{p['en']}-hr.jpg",) if lang == "hr" else ()) + (f"blog-{p['en']}.jpg",):
        if os.path.isfile(os.path.join(STATIC, name)):
            return f"/static/landing/{name}"
    return "/static/landing/kol.jpg"


def _card(v, lang):
    from ui.blogcover import svg
    return (f"<a class=cvr href={L[lang]['base']}/{v['slug']}>{svg(v, lang, decorative=True)}<div class=bt>"
            f"<em>{esc(v['tag'])}</em><b>{esc(v['h1'])}</b><span>{esc(v['desc'])}</span></div></a>")


def index(lang="en"):
    from ui.public import _shell
    t = L[lang]
    vs = views(lang)
    body = (f"<div class=art style='max-width:none'><section class=ph1><div class=eyebrow>MemeSonar blog</div>"
            f"<h1>{t['i_h1']}</h1><p class=lead>{t['i_lead']}</p></section>{cat_nav(lang)}"
            + "".join(f"<h2 class=s><a href={cat_path(c, lang)}>{c[2 if lang == 'en' else 3]} →</a></h2>"
                      f"<div class=bl>{''.join(_card(v, lang) for en in c[6] for v in [get_en(en, lang)] if v)}</div>" for c in CATS)
            + (f"<div class=bl>{''.join(_card(v, lang) for v in vs if v['en'] not in CAT_OF)}</div>"
               if any(v["en"] not in CAT_OF for v in vs) else "")
            + f"<div class=lock><p>{t['i_lock']}</p><a class='btn sm' href={t['home']}#pristup>{t['cta']}</a></div></div>")
    jsonld = _ld({"@context": "https://schema.org", "@type": "Blog", "name": "MemeSonar blog", "inLanguage": lang,
                  "url": _base() + t["base"],
                  "blogPost": [{"@type": "BlogPosting", "headline": v["h1"], "url": f"{_base()}{t['base']}/{v['slug']}",
                                "datePublished": v["date"]} for v in vs]})
    return _shell(lang, t["i_title"], t["i_desc"], "/blog", "/hr/blog", body, jsonld=jsonld,
                  og_image="/static/landing/kol.jpg")


def category(slug, lang="en"):
    """A category page: intro, chip nav, its posts, related public sections. None if unknown."""
    from ui.public import _shell
    t = L[lang]
    c = cat_by_slug(slug, lang)
    if not c:
        return None
    name, intro = c[2 if lang == "en" else 3], c[4 if lang == "en" else 5]
    vs = [v for en in c[6] for v in [get_en(en, lang)] if v]
    extra = CAT_LINKS.get(c[0], {}).get(lang, ())
    more = (f"<h2 class=s>{t['c_more']}</h2><div class=chips>"
            + "".join(f"<a href={h}>{esc(n)}</a>" for h, n in extra) + "</div>") if extra else ""
    body = (f"<div class=art style='max-width:none'><section class=ph1><div class=crumb><a href={t['base']}>{t['crumb']}</a>"
            f"</div><h1>{esc(name)}</h1><p class=lead>{esc(intro)}</p></section>{cat_nav(lang, c)}"
            f"<div class=bl>{''.join(_card(v, lang) for v in vs)}</div>{more}"
            f"<div class=lock><p>{t['i_lock']}</p><a class='btn sm' href={t['home']}#pristup>{t['cta']}</a></div></div>")
    jsonld = _ld({"@context": "https://schema.org", "@type": "CollectionPage", "name": name, "inLanguage": lang,
                  "url": _base() + cat_path(c, lang), "hasPart": [
                      {"@type": "BlogPosting", "headline": v["h1"], "url": f"{_base()}{t['base']}/{v['slug']}"} for v in vs]})
    return _shell(lang, t["c_title"].format(c=name), intro, cat_path(c, "en"), cat_path(c, "hr"), body, jsonld=jsonld)


def get_en(en_slug, lang):
    p = next((x for x in _posts() if x["slug"] == en_slug), None)
    return view(p, lang) if p else None


# Public sections linked from each category page (internal links beyond the blog).
CAT_LINKS = {
    "guides": {"en": (("/how-to-buy", "How to buy the top 100 meme coins"), ("/solana-meme-coins", "Top 100 Solana meme coins"),
                      ("/best-crypto-tools/crypto-wallets", "Best crypto wallets"), ("/glossary/slippage", "Slippage")),
               "hr": (("/hr/kako-kupiti", "Kako kupiti top 100 meme coina"), ("/hr/solana-meme-coini", "Top 100 Solana meme coina"),
                      ("/hr/najbolji-kripto-alati/kripto-novcanici", "Najbolji kripto novčanici"), ("/hr/rjecnik/slippage", "Slippage"))},
    "exchanges-and-cards": {"en": (("/how-to-buy", "How to buy guides per coin"), ("/glossary/cex", "What is a CEX"),
                                   ("/best-crypto-tools/crypto-wallets", "Best crypto wallets")),
                            "hr": (("/hr/kako-kupiti", "Vodiči za kupnju po coinu"), ("/hr/rjecnik/cex", "Što je CEX"),
                                   ("/hr/najbolji-kripto-alati/kripto-novcanici", "Najbolji kripto novčanici"))},
    "tax-and-law": {"en": (("/blog/best-crypto-exchanges-croatia", "MiCA-licensed exchanges"), ("/glossary/pnl", "PnL"),
                           ("/glossary/multisig", "Multisig wallet")),
                    "hr": (("/hr/blog/najbolje-kripto-mjenjacnice-hrvatska", "Mjenjačnice s MiCA licencom"),
                           ("/hr/rjecnik/pnl", "PnL"), ("/hr/rjecnik/multisig", "Multisig novčanik"))},
    "rugs-and-scams": {"en": (("/rug-check", "Rug check for the top 100 coins"), ("/best-crypto-tools/rug-checkers", "Best rug checkers"),
                              ("/glossary/rug-pull", "Rug pull")),
                       "hr": (("/hr/provjera", "Provjera ruga za top 100 coina"),
                              ("/hr/najbolji-kripto-alati/provjera-ruga", "Najbolji alati za provjeru ruga"),
                              ("/hr/rjecnik/rug-pull", "Rug pull"))},
    "wallets-and-influencers": {"en": (("/influencers", "Crypto influencer leaderboard"),
                                       ("/best-crypto-tools/wallet-trackers", "Best wallet trackers"),
                                       ("/best-crypto-tools/copy-trading-platforms", "Copy trading platforms")),
                                "hr": (("/hr/influenceri", "Ljestvica kripto influencera"),
                                       ("/hr/najbolji-kripto-alati/pracenje-novcanika", "Najbolji alati za praćenje novčanika"),
                                       ("/hr/najbolji-kripto-alati/copy-trading-platforme", "Copy trading platforme"))},
}


def _base():
    return os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")


def _ld(obj):
    return '<script type="application/ld+json">' + json.dumps(obj).replace("</", "<\\/") + "</script>"


def page(slug, lang="en"):
    """HTML of one post in that language, or None."""
    from ui.public import _shell
    from ui.blogcover import svg
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
         "dateModified": p.get("updated", p["date"]), "mainEntityOfPage": url, "image": _base() + _og(p, lang),
         "inLanguage": lang, "keywords": ", ".join(p["kw"]), "author": {"@type": "Organization", "name": "MemeSonar"},
         "publisher": {"@type": "Organization", "name": "MemeSonar"}},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Blog", "item": _base() + t["base"]},
            *([{"@type": "ListItem", "position": 2, "name": CAT_OF[p["en"]][2 if lang == "en" else 3],
                "item": _base() + cat_path(CAT_OF[p["en"]], lang)}] if p["en"] in CAT_OF else []),
            {"@type": "ListItem", "position": 3 if p["en"] in CAT_OF else 2, "name": p["h1"], "item": url}]}]})
    c = CAT_OF.get(p["en"])
    crumb_cat = (f"<a href={cat_path(c, lang)}>{c[2 if lang == 'en' else 3]}</a>" if c else esc(p["tag"]))
    body = (f"<article class=art><section class=ph1><div class=crumb><a href={t['base']}>{t['crumb']}</a> · "
            f"{crumb_cat}</div><h1>{esc(p['h1'])}</h1><div class=meta>{_date(p['date'], lang)} · {p['mins']} "
            f"{t['read']} · {t['by']}</div><figure class=bcov>{svg(p, lang)}</figure><div class=tldr><b>{t['short']}</b><p>{p['tldr']}</p></div></section>"
            f"{_link_terms(p['body'], lang)}{_tools(p['en'], lang)}<div class=lock><p>{t['lock']}</p>"
            f"<a class='btn sm' href={t['home']}#pristup>{t['cta']}</a></div><p class=note>{t['note']}</p></article>"
            f"{_chips(p['en'], lang)}<h2 class=s>{t['next']}</h2><div class=bl>{''.join(_card(r, lang) for r in rel[:3])}</div>")
    en = f"/blog/{p['en']}"
    hr_v = view(next(x for x in _posts() if x["slug"] == p["en"]), "hr")
    hr = f"/hr/blog/{hr_v['slug']}" if hr_v else None
    return _shell(lang, p["title"], p["desc"], en, hr, body, jsonld=jsonld, og_image=_og(p, lang), og_type="article")


def _date(d, lang="en"):
    y, m, dd = d.split("-")
    mon = L[lang]["months"][int(m) - 1]
    return f"{int(dd)} {mon} {y}" if lang == "en" else f"{int(dd)}. {mon} {y}."


# Short menu descriptions per category (ui/sitenav.py picks nav_items up for the menus and footer).
_CAT_SHORT = {"guides": ("Step-by-step how-tos", "Upute korak po korak"),
              "exchanges-and-cards": ("Licensed exchanges and crypto cards", "Licencirane mjenjačnice i kartice"),
              "tax-and-law": ("Crypto tax in Croatia, companies", "Porez na kripto, firme"),
              "rugs-and-scams": ("Rug pulls and pump and dumps", "Rug pullovi i pump and dump"),
              "prediction-markets": ("Polymarket rules and odds", "Pravila i kvote na Polymarketu"),
              "for-crypto-projects": ("Token launches and marketing", "Lansiranje tokena i marketing"),
              "wallets-and-influencers": ("Wallet tracking, copy trading, KOLs", "Praćenje novčanika, copy trading, KOL")}


def nav_items(lang):
    """[(group, href, label, description)] for the site menu: blog categories plus the two key Croatia articles."""
    i = 0 if lang == "en" else 1
    out = [("learn", cat_path(c, lang), c[2 + i], _CAT_SHORT[c[0]][i]) for c in CATS]
    for en, d in (("best-crypto-exchanges-croatia", ("Best exchanges in Croatia", "Najbolje mjenjačnice u Hrvatskoj")),
                  ("crypto-tax-croatia", ("Crypto tax calculator", "Kalkulator poreza na kripto"))):
        v = get_en(en, lang)
        if v:
            out.append(("learn", f"{L[lang]['base']}/{v['slug']}", d[i], v["tag"]))
    return out
