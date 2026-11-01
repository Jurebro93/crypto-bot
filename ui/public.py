"""Public, indexable pages (no login): influencer leaderboard and one page per influencer, English (main) + Croatian.

- /influencers, /influencer/<handle>            English (x-default)
- /hr/influenceri, /hr/influencer/<handle>      Croatian
- /robots.txt, /sitemap.xml
Public = history and scores: calls older than PUBLIC_DELAY_S with their outcome. Fresh calls, live signals, wallets,
copy trading and everything else stay behind the login (and are sent with X-Robots-Tag: noindex by run_ui).
Pages are cached for CACHE_S, so search-engine crawlers cost almost nothing.
"""
import json
import math
import os
import re
import sqlite3
import threading
import time
from urllib.parse import quote

from ui.html import esc, logo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC_DELAY_S = 86400          # calls younger than this are members-only
CACHE_S = int(os.environ.get("PUBLIC_CACHE_S", "900"))
MIN_MEASURED = 3                # page exists
SITEMAP_MEASURED = 5            # page is offered to search engines
HANDLE = re.compile(r"[A-Za-z0-9_]{1,30}")
BAD = re.compile(r"nigg|fag|hitler|retard|nazi|rape|porn|fuck|cunt|dick|cock|pussy|dojk", re.I)

_cache, _lock = {}, threading.Lock()

L = {
    "en": dict(
        lb_title="Crypto influencer leaderboard: who really moves Solana tokens",
        lb_desc="Scores for {n} crypto influencers on X, measured on every Solana token call: hit rate, 24h peak, rugs "
                "and late calls. Updated daily.",
        lb_h1="Crypto influencer leaderboard",
        lb_lead="We measure what the price did after every Solana token call an influencer posts on X: 1 hour, 24 hours, "
                "the peak, and whether it rugged. The score shows who actually moves the market.",
        cols=("#", "Influencer", "Score", "Hit rate", "Median 24h peak", "Rugs", "Late calls", "Followers", "Calls"),
        how_h="How the score works",
        how=("Hit rate: share of calls that gained at least 50% within 24 hours.",
             "Median 24h peak: the typical highest point within 24 hours after the call.",
             "Rugs: share of called tokens that dropped 90% or more.",
             "Late calls: calls made after the price had already doubled in the 2 hours before.",
             "Bots that post every new token are excluded. Few measured calls means a less certain score."),
        p_title="@{h} crypto: calls, track record and score {sc} ({hit} hit rate) | KriptoRadar",
        p_desc="How did @{h}'s Solana token calls play out? {m} calls measured: {hit} gained 50%+ within 24h, median "
               "peak {mx}, {rug} rugged. Updated daily.",
        summary="@{h} has posted {m} measured Solana token calls. {hit} of them gained at least 50% within 24 hours, "
                "the typical peak was {mx} and {rug} of the tokens rugged (fell 90%+). {late} of the calls came after "
                "the price had already doubled.",
        cards=("Score", "Hit rate", "Median 24h peak", "Rugs", "Followers", "Calls measured"),
        inf_h="Does the market listen?", inf=("Volume at least doubled in the hour after the post",
                                              "Price higher 1 hour after the post", "Typical views per post"),
        calls_h="Recent calls", calls_note="Calls older than 24 hours, with their outcome. Fresh calls are for members.",
        ccols=("Date", "Token", "Market cap", "1 h", "24 h", "24h peak", "Post"),
        locked="{n} new calls in the last 24 hours. Members see them live and can copy them automatically.",
        lb_lock="Members see every new call live and can copy the best influencers automatically.",
        cta="Request access", back="← All influencers", similar="Similar influencers", none="No measured calls yet.",
        post="post", foot="Not financial advice. Scores are measurements of past calls, not accusations or "
        "endorsements.", home="/", lb="/influencers", prof="/influencer/", login="Log in"),
    "hr": dict(
        lb_title="Ljestvica crypto influencera: tko stvarno pomiče Solana tokene",
        lb_desc="Ocjene {n} crypto influencera na X-u, izmjerene na svakom pozivu Solana tokena: pogodak, vrh u 24 h, "
                "rugovi i kasni pozivi. Osvježava se svaki dan.",
        lb_h1="Ljestvica crypto influencera",
        lb_lead="Za svaki poziv Solana tokena koji influencer objavi na X-u mjerimo što je cijena napravila: nakon sat "
                "vremena, nakon 24 sata, najviši vrh i je li završio kao rug. Ocjena pokazuje tko stvarno pomiče tržište.",
        cols=("#", "Influencer", "Ocjena", "Pogodak", "Medijan vrha 24 h", "Rugovi", "Kasni pozivi", "Pratitelji",
              "Pozivi"),
        how_h="Kako se računa ocjena",
        how=("Pogodak: udio poziva koji su narasli barem 50% u 24 sata.",
             "Medijan vrha 24 h: tipičan najviši rast u 24 sata nakon poziva.",
             "Rugovi: udio pozvanih tokena koji su pali 90% ili više.",
             "Kasni pozivi: pozivi nakon što se cijena već udvostručila u 2 sata prije.",
             "Botovi koji objavljuju svaki novi token su izbačeni. Malo izmjerenih poziva znači manje sigurnu ocjenu."),
        p_title="@{h} kripto: pozivi, rezultati i ocjena {sc} (pogodak {hit}) | KriptoRadar",
        p_desc="Kako su prošli pozivi Solana tokena od @{h}? Izmjereno {m} poziva: {hit} je naraslo 50%+ u 24 h, medijan "
               "vrha {mx}, {rug} rugova. Osvježava se svaki dan.",
        summary="@{h} je objavio {m} izmjerenih poziva Solana tokena. {hit} ih je naraslo barem 50% u 24 sata, tipičan "
                "vrh bio je {mx}, a {rug} tokena završilo je kao rug (pad 90%+). {late} poziva došlo je nakon što se "
                "cijena već udvostručila.",
        cards=("Ocjena", "Pogodak", "Medijan vrha 24 h", "Rugovi", "Pratitelji", "Izmjerenih poziva"),
        inf_h="Sluša li ga tržište?", inf=("Volumen se barem udvostručio u satu nakon objave",
                                           "Cijena viša sat nakon objave", "Tipičan broj pregleda objave"),
        calls_h="Zadnji pozivi", calls_note="Pozivi stariji od 24 sata, s ishodom. Svježi pozivi su za članove.",
        ccols=("Datum", "Token", "Tržišna vrijednost", "1 h", "24 h", "Vrh 24 h", "Objava"),
        locked="{n} novih poziva u zadnja 24 sata. Članovi ih vide uživo i mogu ih automatski kopirati.",
        lb_lock="Članovi vide svaki novi poziv uživo i mogu automatski kopirati najbolje influencere.",
        cta="Zatraži pristup", back="← Svi influenceri", similar="Slični influenceri", none="Još nema izmjerenih poziva.",
        post="objava", foot="Nije financijski savjet. Ocjene su mjerenja prošlih poziva, a ne optužbe ili preporuke.",
        home="/hr", lb="/hr/influenceri", prof="/hr/influencer/", login="Prijava"),
}

EXTRA_CSS = """
.ph1{padding:56px 0 8px}.ph1 h1{font-size:clamp(32px,5.5vw,52px);margin:10px 0 14px;text-align:left;max-width:none}
.ph1 .lead{margin-bottom:24px}.crumb{color:var(--mut);font-size:14px}.crumb a{color:var(--acc)}
.tw{overflow-x:auto;border:1px solid var(--line);border-radius:18px;background:#fff;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%;font-size:15px}th,td{padding:12px 14px;text-align:left;white-space:nowrap;
border-bottom:1px solid var(--line)}th{font-size:13px;color:var(--mut);font-weight:600;background:var(--soft)}
tr:last-child td{border-bottom:0}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}td a{color:var(--acc);font-weight:600}
.pos{color:#16a34a}.neg{color:#dc2626}.mut{color:var(--mut)}
.cards{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin:8px 0 28px}
@media(max-width:900px){.cards{grid-template-columns:repeat(3,1fr)}}@media(max-width:520px){.cards{grid-template-columns:1fr 1fr}}
.card{border:1px solid var(--line);border-radius:18px;padding:16px;background:#fff}.card b{display:block;font-size:26px;
letter-spacing:-.02em;font-weight:760}.card span{color:var(--mut);font-size:13px}
.lock{display:flex;gap:16px;align-items:center;justify-content:space-between;flex-wrap:wrap;background:var(--fg);color:#fff;
border-radius:18px;padding:20px 22px;margin:18px 0}.lock p{margin:0;color:#cbd2df}.lock .btn{background:#fff;color:var(--fg)}
h2.s{font-size:24px;margin:40px 0 12px}ul.how{color:var(--mut);padding-left:20px}ul.how li{margin:6px 0}
.charts{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:0 0 18px}@media(max-width:760px){.charts{grid-template-columns:1fr}}
ul.lk{list-style:none;padding:0;margin:12px 0 16px;display:grid;gap:8px;color:#cbd2df}
.cards .card{min-width:0}.cards .card b{overflow-wrap:anywhere}@media(max-width:600px){.cards .card b{font-size:19px}}
.m{display:none;font-size:12px}@media(max-width:600px){table.coins .x{display:none}table.coins .m{display:block}table.coins td,table.coins th{white-space:normal;padding:10px 8px}table.coins td.n{white-space:nowrap}table.coins{font-size:14px}table.coins td{overflow-wrap:anywhere}}
.gl{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}@media(max-width:900px){.gl{grid-template-columns:1fr 1fr}}@media(max-width:560px){.gl{grid-template-columns:1fr}}
.gi{border:1px solid var(--line);border-radius:16px;padding:16px;background:#fff;display:block}.gi:hover{border-color:#cfd5e1}.gi b{display:block;color:var(--acc)}.gi span{color:var(--mut);font-size:14px;line-height:1.45;display:block;margin-top:4px}
.fl{margin:0 0 10px}.fl a{color:var(--fg);font-weight:500}
.gbody{max-width:720px;font-size:17.5px}.gbody p{margin:0 0 14px}
.rng{display:flex;justify-content:space-between;font-size:13px;color:var(--mut);margin-top:4px}
.chips{display:flex;flex-wrap:wrap;gap:8px}.chips a{border:1px solid var(--line);border-radius:999px;padding:6px 14px;
font-size:14px;background:#fff}
"""


def _kol_db():
    return os.environ.get("KOL_DB") or os.path.join(ROOT, "kol.db")


def _con():
    p = _kol_db()
    if not os.path.exists(p) or not os.path.getsize(p):
        return None
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def _pct(x, signed=False):
    if x is None:
        return "–"
    return f"{x * 100:+.0f}%" if signed else f"{x * 100:.0f}%"


def _int(x, lang):
    if x is None:
        return "–"
    s = f"{x:,.0f}"
    return s.replace(",", ".") if lang == "hr" else s


def _usd(x):
    if not x:
        return "–"
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if x >= div:
            return f"${x / div:.1f}{suf}"
    return f"${x:.0f}"


def _cls(x):
    return "" if x is None else ("pos" if x > 0 else "neg" if x < 0 else "")


def _sym(sym, token):
    s = (sym or "").strip() or (token or "")[:4] + "…"
    return s[0] + "***" if BAD.search(s) else s[:18]


def influencers():
    """Public rows: measured X influencers, no bots, best score first."""
    con = _con()
    if con is None:
        return []
    try:
        try:
            rows = con.execute("SELECT handle, name, followers, score, stats, COALESCE(bot, 0) bot FROM kols "
                               "WHERE score IS NOT NULL ORDER BY score DESC").fetchall()
        except sqlite3.OperationalError:
            rows = con.execute("SELECT handle, name, followers, score, stats, 0 bot FROM kols "
                               "WHERE score IS NOT NULL ORDER BY score DESC").fetchall()
    finally:
        con.close()
    out = []
    for r in rows:
        h = r["handle"]
        if r["bot"] or not HANDLE.fullmatch(h or "") or BAD.search(h):
            continue
        s = json.loads(r["stats"] or "{}")
        if s.get("measured", 0) < MIN_MEASURED:
            continue
        out.append({"handle": h, "name": r["name"], "followers": r["followers"], "score": r["score"], "s": s})
    return out


def _shell(lang, title, desc, path_en, path_hr, body, canonical_lang=None, jsonld="", og_image="/static/landing/kol.jpg",
           og_type="website"):
    """Page frame. path_hr=None: English-only page (no Croatian alternate; the language switch goes to /hr)."""
    base = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    t = L[lang]
    from ui.landing import CSS
    svg, name = logo(30)
    from ui import blog, blogviz, calcs, tools
    canon = base + (path_en if lang == "en" or not path_hr else path_hr)
    switch = (f"<a class=lnk href={path_hr or '/hr'} hreflang=hr>HR</a>" if lang == "en" else
              f"<a class=lnk href={path_en} hreflang=en>EN</a>")
    alt = (f'<link rel=alternate hreflang=en href="{base}{path_en}"><link rel=alternate hreflang=hr href="{base}{path_hr}">'
           f'\n<link rel=alternate hreflang=x-default href="{base}{path_en}">') if path_hr else ""
    return f"""<!doctype html><html lang={lang}><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover"><title>{esc(title)}</title>
<meta name=description content="{esc(desc)}"><link rel=canonical href="{canon}">
{alt}
<meta property="og:type" content="{og_type}"><meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}"><meta property="og:url" content="{canon}">
<meta property="og:image" content="{base}{og_image}"><meta name="twitter:card" content="summary_large_image">
<meta name=theme-color content="#ffffff"><link rel=icon href="data:image/svg+xml,{quote(logo(32)[0])}">{jsonld}
<style>{CSS}{EXTRA_CSS}{_nav_css()}{blog.CSS}{blogviz.CSS}{tools.CSS}{calcs.CSS}</style></head><body>
<nav class=s><div class=w><a class=brand href={t['home']}>{svg}<span>{esc(name)}</span></a><span class=sp></span>
{nav_links(lang)}{switch}
<a class=lnk href=/prijava>{t['login']}</a><a class='btn p sm' href={t['home']}#pristup>{t['cta']}</a>{mobile_menu(lang)}</div></nav>
<main class=w>{body}</main>
<footer style='margin-top:64px'><div class=w>{_foot_links(lang)}© {time.gmtime().tm_year} {esc(name)} · {t['foot']}</div></footer>
</body></html>"""


def leaderboard(lang):
    t = L[lang]
    rows = influencers()[:100]
    trs = []
    for i, r in enumerate(rows, 1):
        s = r["s"]
        trs.append(f"<tr><td class=mut>{i}</td><td><a href=\"{t['prof']}{r['handle']}\">@{esc(r['handle'])}</a></td>"
                   f"<td class=n><b>{r['score']:.0f}</b></td><td class=n>{_pct(s.get('hit_rate'))}</td>"
                   f"<td class='n {_cls(s.get('med_max24'))}'>{_pct(s.get('med_max24'), True)}</td>"
                   f"<td class=n>{_pct(s.get('rug_rate'))}</td><td class=n>{_pct(s.get('prepump_rate'))}</td>"
                   f"<td class=n>{_int(r['followers'], lang)}</td><td class=n>{s.get('measured', 0)}</td></tr>")
    c = t["cols"]
    head = "".join(f"<th{' class=n' if j > 1 else ''}>{x}</th>" for j, x in enumerate(c))
    table = (f"<div class=tw><table class=coins><thead><tr>{head}</tr></thead><tbody>{''.join(trs)}</tbody></table></div>"
             if trs else f"<p class=mut>{t['none']}</p>")
    how = "".join(f"<li>{x}</li>" for x in t["how"])
    body = (f"<section class=ph1><div class=eyebrow>KriptoRadar</div><h1>{t['lb_h1']}</h1><p class=lead>{t['lb_lead']}</p>"
            f"</section>{table}<h2 class=s>{t['how_h']}</h2><ul class=how>{how}</ul>"
            f"<div class=lock><p>{t['lb_lock']}</p><a class='btn sm' href={t['home']}#pristup>{t['cta']}</a></div>")
    return _shell(lang, t["lb_title"], t["lb_desc"].format(n=len(rows)), "/influencers", "/hr/influenceri", body)


def profile(handle, lang):
    """HTML of one influencer page, or None (unknown, bot, too few calls)."""
    if not HANDLE.fullmatch(handle or ""):
        return None
    t = L[lang]
    rows = influencers()
    me = next((r for r in rows if r["handle"].lower() == handle.lower()), None)
    if not me:
        return None
    h, s = me["handle"], me["s"]
    con = _con()
    if con is None:
        return None
    cut = int(time.time()) - PUBLIC_DELAY_S
    try:
        calls = con.execute("SELECT ts, token, symbol, url, mcap0, r1h, r24h, max24 FROM calls WHERE handle=? AND "
                            "kind='call' AND ts < ? ORDER BY ts DESC LIMIT 25", (h, cut)).fetchall()
        fresh = con.execute("SELECT COUNT(DISTINCT token) FROM calls WHERE handle=? AND kind='call' AND ts >= ?",
                            (h, cut)).fetchone()[0]
        infl = con.execute("SELECT vol_lift, r1h, views FROM calls WHERE handle=? AND kind='call' AND first_by_kol=1 "
                           "AND p0 IS NOT NULL AND bad IS NULL AND ts < ?", (h, cut)).fetchall()
    except sqlite3.OperationalError:
        calls, fresh, infl = [], 0, []
    finally:
        con.close()
    hit, mx, rug, late = (_pct(s.get("hit_rate")), _pct(s.get("med_max24"), True), _pct(s.get("rug_rate")),
                          _pct(s.get("prepump_rate")))
    m = s.get("measured", 0)
    sc = f"{me['score']:.0f}"
    cards = "".join(f"<div class=card><b>{v}</b><span>{lab}</span></div>" for v, lab in zip(
        (sc, hit, mx, rug, _int(me["followers"], lang), m), t["cards"]))
    summary = t["summary"].format(h=esc(h), m=m, hit=hit, mx=mx, rug=rug, late=late)
    lifts = [r["vol_lift"] for r in infl if r["vol_lift"] is not None]
    r1 = [r["r1h"] for r in infl if r["r1h"] is not None]
    views = sorted(r["views"] for r in infl if r["views"])
    inf_rows = [(t["inf"][0], _pct(sum(1 for x in lifts if x >= 2) / len(lifts)) if lifts else "–"),
                (t["inf"][1], _pct(sum(1 for x in r1 if x > 0) / len(r1)) if r1 else "–"),
                (t["inf"][2], _int(views[len(views) // 2], lang) if views else "–")]
    inf_html = ("<div class=tw><table><tbody>" + "".join(f"<tr><td>{a}</td><td class=n><b>{b}</b></td></tr>"
                                                      for a, b in inf_rows) + "</tbody></table></div>")
    crow = []
    for c in calls:
        d = time.strftime("%Y-%m-%d", time.gmtime(c["ts"]))
        post = (f"<a href=\"{esc(c['url'])}\" target=_blank rel=\"nofollow noopener\">{t['post']} ↗</a>"
                if c["url"] and str(c["url"]).startswith("https://") else "–")
        crow.append(f"<tr><td class=mut>{d}</td><td><b>{esc(_sym(c['symbol'], c['token']))}</b></td>"
                    f"<td class=n>{_usd(c['mcap0'])}</td>"
                    + "".join(f"<td class='n {_cls(c[k])}'>{_pct(c[k], True)}</td>" for k in ("r1h", "r24h", "max24"))
                    + f"<td>{post}</td></tr>")
    ch = "".join(f"<th{' class=n' if 1 < j < 6 else ''}>{x}</th>" for j, x in enumerate(t["ccols"]))
    calls_html = (f"<div class=tw><table><thead><tr>{ch}</tr></thead><tbody>{''.join(crow)}</tbody></table></div>"
                  if crow else f"<p class=mut>{t['none']}</p>")
    lock = (f"<div class=lock><p>{t['locked'].format(n=fresh)}</p><a class='btn sm' href={t['home']}#pristup>"
            f"{t['cta']}</a></div>")
    idx = rows.index(me)
    near = [r for r in rows[max(0, idx - 4):idx + 5] if r is not me][:8]
    sim = "".join(f"<a href=\"{t['prof']}{r['handle']}\">@{esc(r['handle'])} · {r['score']:.0f}</a>" for r in near)
    base = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    jsonld = ('<script type="application/ld+json">' + json.dumps({
        "@context": "https://schema.org", "@type": "ProfilePage",
        "mainEntity": {"@type": "Person", "name": me["name"] or h, "alternateName": "@" + h,
                       "sameAs": [f"https://x.com/{h}"]},
        "url": f"{base}{t['prof']}{h}"}) + "</script>")
    body = (f"<section class=ph1><div class=crumb><a href={t['lb']}>{t['back']}</a></div>"
            f"<h1>@{esc(h)}{(' <span class=mut style=font-weight:500>' + esc(me['name']) + '</span>') if me['name'] and not BAD.search(me['name']) else ''}</h1>"
            f"<p class=lead>{summary}</p></section><div class=cards>{cards}</div>{lock}"
            f"<h2 class=s>{t['inf_h']}</h2>{inf_html}<h2 class=s>{t['calls_h']}</h2><p class=mut>{t['calls_note']}</p>"
            f"{calls_html}" + (f"<h2 class=s>{t['similar']}</h2><div class=chips>{sim}</div>" if sim else ""))
    title = t["p_title"].format(h=h, sc=sc, hit=hit)
    desc = t["p_desc"].format(h=h, m=m, hit=hit, mx=mx, rug=rug)
    return _shell(lang, title, desc, f"/influencer/{h}", f"/hr/influencer/{h}", body, jsonld=jsonld)


# One list of public sections, used by the nav, the mobile menu, the footer and the landing page "Explore" block.
# (path, short nav label, footer label, one-line description). New public clusters: add one row per language here.
SECTIONS = {
    "en": [("/solana-meme-coins", "Meme coins", "Solana meme coins", "Top 100 Solana meme coins with charts and safety checks"),
           ("/influencers", "Influencers", "Crypto influencers", "Every influencer call measured: hit rate, rugs, late calls"),
           ("/glossary", "Glossary", "Crypto glossary", "Crypto and meme coin terms explained in plain words"),
           ("/blog", "Blog", "Blog", "Guides on wallet tracking, copy trading and rug pulls, with our data"),
           ("/best-crypto-tools", "Tools", "Best crypto tools", "Wallet trackers, trading bots, wallets, rug checkers and APIs compared, with prices")],
    "hr": [("/hr/solana-meme-coini", "Meme coini", "Solana meme coini", "Top 100 Solana meme coina s grafovima i sigurnosnom provjerom"),
           ("/hr/influenceri", "Influenceri", "Kripto influenceri", "Svaki poziv influencera izmjeren: pogodak, rugovi, kasni pozivi"),
           ("/hr/rjecnik", "Rječnik", "Kripto rječnik", "Kripto i meme coin pojmovi objašnjeni jednostavno"),
           ("/hr/blog", "Blog", "Blog", "Vodiči o praćenju novčanika, copy tradingu i rug pullovima, s našim podacima"),
           ("/hr/najbolji-kripto-alati", "Alati", "Najbolji kripto alati", "Usporedba alata za praćenje novčanika, botova, novčanika, provjere ruga i API-ja, s cijenama")],
}


def nav_links(lang):
    from ui import sitenav
    return sitenav.nav(lang)


def mobile_menu(lang):
    from ui import sitenav
    return sitenav.mobile(lang)


def explore(lang):
    from ui import sitenav
    return sitenav.explore(lang)


def _nav_css():
    from ui import sitenav
    return sitenav.CSS


NAV_CSS = ""   # kept for imports; the CSS lives in ui/sitenav.py


def _foot_links(lang):
    from ui import sitenav
    return sitenav.footer(lang)


def _seo_extra(fn):
    """Internal links from ui/coinseo.py ('' if that module fails, so the coin pages never break)."""
    try:
        from ui import coinseo
        return fn(coinseo)
    except Exception as e:  # noqa: BLE001
        print(f"coinseo: {e}", flush=True)
        return ""


def _seo_robots():
    try:
        from ui import coinseo
        return coinseo.ROBOTS
    except Exception:  # noqa: BLE001
        return ()


def robots():
    base = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    return ("User-agent: *\nAllow: /$\nAllow: /hr$\nAllow: /influencers\nAllow: /influencer/\nAllow: /hr/influenceri\n"
            "Allow: /hr/influencer/\nAllow: /solana-meme-coins\nAllow: /hr/solana-meme-coini\nAllow: /coin/\n"
            "Allow: /hr/coin/\nAllow: /glossary\nAllow: /hr/rjecnik\nAllow: /blog\nAllow: /hr/blog\nAllow: /best-crypto-tools\nAllow: /hr/najbolji-kripto-alati\n"
            + "".join(f"Allow: {p}\n" for p in _seo_robots()) + "Allow: /static/landing/\nDisallow: /\n\n"
            f"Sitemap: {base}/sitemap.xml\n")


def sitemap():
    base = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    day = time.strftime("%Y-%m-%d", time.gmtime())
    urls = [("/", "/hr", "1.0"), ("/influencers", "/hr/influenceri", "0.9")]
    urls.append(("/solana-meme-coins", "/hr/solana-meme-coini", "0.9"))
    try:
        from ui import coins as K
        urls += [(f"/coin/{c['slug']}", f"/hr/coin/{c['slug']}", "0.8") for c in K.top()]
    except Exception:  # noqa: BLE001
        pass
    from ui import glossary_public as GP
    urls.append(("/glossary", "/hr/rjecnik", "0.8"))
    urls += [(f"/glossary/{e['en']}", f"/hr/rjecnik/{e['hr']}", "0.6") for e in GP.ENTRIES]
    try:
        from ui import coinseo
        urls += coinseo.urls()
    except Exception as e:  # noqa: BLE001
        print(f"sitemap: coinseo nedostupan: {e}", flush=True)
    try:
        from ui import tools
        urls += tools.urls()
    except Exception as e:  # noqa: BLE001
        print(f"sitemap: alati nedostupni: {e}", flush=True)
    try:
        urls += [(f"/influencer/{r['handle']}", f"/hr/influencer/{r['handle']}", "0.7") for r in influencers()
                 if r["s"].get("measured", 0) >= SITEMAP_MEASURED]
    except Exception as e:  # noqa: BLE001  (one broken source must not empty the whole sitemap)
        print(f"sitemap: influenceri nedostupni: {e}", flush=True)
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">']
    for en, hr, pr in urls:
        for loc in (en, hr):
            out.append(f"<url><loc>{base}{loc}</loc><lastmod>{day}</lastmod><priority>{pr}</priority>"
                       f'<xhtml:link rel="alternate" hreflang="en" href="{base}{en}"/>'
                       f'<xhtml:link rel="alternate" hreflang="hr" href="{base}{hr}"/></url>')
    from ui import blog
    for en, hr, pr in blog.urls():   # posts without a Croatian version get no alternates
        for loc in (en, hr) if hr else (en,):
            alt = (f'<xhtml:link rel="alternate" hreflang="en" href="{base}{en}"/>'
                   f'<xhtml:link rel="alternate" hreflang="hr" href="{base}{hr}"/>') if hr else ""
            out.append(f"<url><loc>{base}{loc}</loc><lastmod>{day}</lastmod><priority>{pr}</priority>{alt}</url>")
    out.append("</urlset>")
    return "\n".join(out)


def _seo_page(path):
    """Coin SEO pages (price prediction, how to buy, rug check, daily lists) from ui/coinseo.py, or None."""
    try:
        from ui import coinseo
        return coinseo.match(path)
    except Exception as e:  # noqa: BLE001
        print(f"coinseo: {e}", flush=True)
        return None


def route(path):
    """(code, body bytes, content type) for a public path, or None when the path is not public."""
    if path in ("/robots.txt", "/sitemap.xml"):
        fn, ctype = (robots, "text/plain") if path == "/robots.txt" else (sitemap, "application/xml")
    elif path in ("/solana-meme-coins", "/hr/solana-meme-coini"):
        lang = "en" if path == "/solana-meme-coins" else "hr"
        fn, ctype = (lambda: coin_list(lang)), "text/html"
    elif _seo_page(path):
        fn, ctype = _seo_page(path), "text/html"
    elif re.fullmatch(r"(/hr)?/coin/[^/]+", path):
        lang, slug = ("hr" if path.startswith("/hr") else "en"), path.rsplit("/", 1)[1]
        fn, ctype = (lambda: coin_page(slug, lang)), "text/html"
    elif path in ("/influencers", "/hr/influenceri"):
        lang = "en" if path == "/influencers" else "hr"
        fn, ctype = (lambda: leaderboard(lang)), "text/html"
    elif path in ("/glossary", "/hr/rjecnik"):
        lang = "en" if path == "/glossary" else "hr"
        fn, ctype = (lambda: glossary_index(lang)), "text/html"
    elif re.fullmatch(r"/glossary/[^/]+|/hr/rjecnik/[^/]+", path):
        lang, slug = ("hr" if path.startswith("/hr") else "en"), path.rsplit("/", 1)[1]
        fn, ctype = (lambda: glossary_term(slug, lang)), "text/html"
    elif re.fullmatch(r"(/best-crypto-tools|/hr/najbolji-kripto-alati)(/[^/]+)?/?", path):
        from ui import tools
        m = re.fullmatch(r"(/best-crypto-tools|/hr/najbolji-kripto-alati)(?:/([^/]+))?/?", path)
        lang, slug = ("hr" if m.group(1).startswith("/hr") else "en"), m.group(2)
        fn, ctype = ((lambda: tools.page(slug, lang)) if slug else (lambda: tools.index(lang))), "text/html"
    elif re.fullmatch(r"/blog/category/[a-z0-9-]+/?|/hr/blog/kategorija/[a-z0-9-]+/?", path):
        from ui import blog
        lang, slug = ("hr" if path.startswith("/hr") else "en"), path.rstrip("/").rsplit("/", 1)[1]
        fn, ctype = (lambda: blog.category(slug, lang)), "text/html"
    elif re.fullmatch(r"(/hr)?/blog(/[^/]+)?/?", path):
        from ui import blog
        m = re.fullmatch(r"(/hr)?/blog(?:/([^/]+))?/?", path)
        lang, slug = ("hr" if m.group(1) else "en"), m.group(2)
        fn, ctype = ((lambda: blog.page(slug, lang)) if slug else (lambda: blog.index(lang))), "text/html"
    else:
        m = re.fullmatch(r"(/hr)?/influencer/([^/]+)", path)
        if not m:
            return None
        lang, h = ("hr" if m.group(1) else "en"), m.group(2)
        fn, ctype = (lambda: profile(h, lang)), "text/html"
    now = time.time()
    with _lock:
        hit = _cache.get(path)
    if hit and now - hit[0] < CACHE_S:
        return hit[1], hit[2], ctype
    try:
        body = fn()
    except Exception as e:  # noqa: BLE001
        print(f"javna stranica {path} nije uspjela: {e}", flush=True)
        body = None
    code = 200 if body else 404
    if not body:
        lang = "hr" if path.startswith("/hr") else "en"
        body = _shell(lang, "404", "", "/influencers", "/hr/influenceri",
                      f"<section class=ph1><h1>404</h1><p class=lead><a href={L[lang]['lb']}>{L[lang]['back']}</a></p>"
                      "</section>")
    raw = body.encode("utf-8")
    with _lock:
        if len(_cache) > 2000:
            _cache.clear()
        _cache[path] = (now, code, raw)
    return code, raw, ctype


# ---------- top Solana meme coins ----------------------------------------------------------------------------------

C = {
    "en": dict(
        lb_title="Top 100 Solana meme coins by market cap (live) | KriptoRadar",
        lb_desc="The biggest Solana meme coins ranked by market cap: price, 24h change, holders, liquidity and volume, "
                "with an analysis page for every coin. Updated every few hours.",
        lb_h1="Top Solana meme coins by market cap",
        lb_lead="The {n} largest Solana meme coins with real liquidity and holders, ranked by market cap. Click a coin "
                "for its chart, safety check and which influencers called it.",
        cols=("#", "Coin", "Price", "24h", "Market cap", "Liquidity", "Holders", "24h volume"),
        updated="Updated", p_title="{sym} price, market cap & holder analysis: is {name} safe? | KriptoRadar",
        p_desc="{name} ({sym}) is the #{rank} Solana meme coin with a ${mcap} market cap and {holders} holders. Price "
               "chart, safety check, liquidity and the influencers who called it.",
        p_h1="{name} ({sym})", p_sub="price, holders and influencer calls",
        summary="{name} is the #{rank} Solana meme coin by market cap ({mcap}). It has {holders} holders, {liq} of "
                "liquidity and {vol} traded in the last 24 hours. The price moved {chg} in 24 hours.",
        cards=("Price", "Market cap", "24h change", "Holders", "Liquidity", "24h volume"),
        chart_p="Price", chart_h="Holders", chart_src_d="daily, last {n} days", chart_src_h="since we started tracking", chart_src_24="last 24 hours",
        safe_h="Safety check", safe=("Mint authority", "Freeze authority", "Top holders own", "Dev wallet holds",
                                     "Organic trading score", "Top 10 wallets (our data)", "Listed on exchanges"),
        yes_off="revoked ✓", no_on="active ⚠", calls_h="Influencer calls",
        calls_note="Calls older than 24 hours and what the price did after them.",
        ccols=("Date", "Influencer", "Market cap at call", "1 h", "24 h", "24h peak"), no_calls="No influencer calls "
        "measured for this coin yet.", lock_h="What members see on top",
        lock=("KriptoRadar score and odds of a jump, updated every 2 minutes", "Smart-money wallets buying or selling now",
              "{n} influencer calls from the last 24 hours, live",
              "Live influencer calls from the last 24 hours", "Copy trading and alerts on the next move"),
        similar="Similar coins", addr="Contract address", copy="Copy", faq_h="Questions about {sym}",
        faq=[("What is the {sym} contract address?", "The Solana contract address of {name} is {mint}."),
             ("How many holders does {sym} have?", "{name} has {holders} holders right now."),
             ("Is {sym} safe?", "{safe} This is not financial advice; meme coins are very risky.")],
        safe_ok="Mint and freeze authority are revoked, so no one can print new tokens or freeze wallets.",
        safe_bad="Mint or freeze authority is still active, which is a risk.", back="← Top Solana meme coins",
        lb_path="/solana-meme-coins", prof="/coin/"),
    "hr": dict(
        lb_title="Top 100 Solana meme coina po tržišnoj vrijednosti (uživo) | KriptoRadar",
        lb_desc="Najveći Solana meme coini po tržišnoj vrijednosti: cijena, promjena u 24 h, holderi, likvidnost i "
                "volumen, uz stranicu s analizom za svaki coin. Osvježava se svakih par sati.",
        lb_h1="Najveći Solana meme coini po tržišnoj vrijednosti",
        lb_lead="{n} najvećih Solana meme coina s pravom likvidnošću i holderima, poredano po tržišnoj vrijednosti. "
                "Klikni coin za graf, sigurnosnu provjeru i koji su ga influenceri zvali.",
        cols=("#", "Coin", "Cijena", "24 h", "Tržišna vrij.", "Likvidnost", "Holderi", "Volumen 24 h"),
        updated="Osvježeno", p_title="{sym} cijena, market cap i analiza holdera: je li {name} siguran? | KriptoRadar",
        p_desc="{name} ({sym}) je #{rank} Solana meme coin s tržišnom vrijednošću ${mcap} i {holders} holdera. Graf "
               "cijene, sigurnosna provjera, likvidnost i influenceri koji su ga zvali.",
        p_h1="{name} ({sym})", p_sub="cijena, holderi i pozivi influencera",
        summary="{name} je #{rank} Solana meme coin po tržišnoj vrijednosti ({mcap}). Ima {holders} holdera, {liq} "
                "likvidnosti i {vol} trgovanja u zadnja 24 sata. Cijena se u 24 sata promijenila {chg}.",
        cards=("Cijena", "Tržišna vrijednost", "Promjena 24 h", "Holderi", "Likvidnost", "Volumen 24 h"),
        chart_p="Cijena", chart_h="Holderi", chart_src_d="dnevno, zadnjih {n} dana", chart_src_h="otkad ga pratimo", chart_src_24="zadnja 24 sata",
        safe_h="Sigurnosna provjera", safe=("Mint ovlast", "Freeze ovlast", "Najveći holderi drže", "Dev novčanik drži",
                                            "Organsko trgovanje", "Top 10 novčanika (naši podaci)", "Na burzama"),
        yes_off="ukinuta ✓", no_on="aktivna ⚠", calls_h="Pozivi influencera",
        calls_note="Pozivi stariji od 24 sata i što je cijena napravila nakon njih.",
        ccols=("Datum", "Influencer", "Vrijednost kod poziva", "1 h", "24 h", "Vrh 24 h"), no_calls="Još nema "
        "izmjerenih poziva influencera za ovaj coin.", lock_h="Što članovi vide uz to",
        lock=("KriptoRadar ocjena i šansa za skok, osvježava se svake 2 minute", "Pametni novčanici koji upravo kupuju ili prodaju",
              "{n} poziva influencera iz zadnja 24 sata, uživo",
              "Pozivi influencera iz zadnja 24 sata, uživo", "Copy trading i obavijest o sljedećem pomaku"),
        similar="Slični coini", addr="Adresa ugovora", copy="Kopiraj", faq_h="Pitanja o {sym}",
        faq=[("Koja je adresa ugovora za {sym}?", "Solana adresa ugovora za {name} je {mint}."),
             ("Koliko holdera ima {sym}?", "{name} trenutno ima {holders} holdera."),
             ("Je li {sym} siguran?", "{safe} Ovo nije financijski savjet; meme coini su vrlo rizični.")],
        safe_ok="Mint i freeze ovlast su ukinute, pa nitko ne može tiskati nove tokene ni zamrznuti novčanike.",
        safe_bad="Mint ili freeze ovlast je još aktivna, što je rizik.", back="← Najveći Solana meme coini",
        lb_path="/hr/solana-meme-coini", prof="/hr/coin/"),
}


def _hist_or_day(hist, key, day, t):
    """Our own snapshots once they cover 2+ days, else the last 24 h rebuilt from the window changes."""
    pts = [(h["ts"], h[key]) for h in hist if h[key] is not None]
    if len(pts) >= 6 and pts[-1][0] - pts[0][0] >= 2 * 86400:
        return pts, t["chart_src_h"]
    return (day, t["chart_src_24"]) if day else (pts, t["chart_src_h"])


def _price(p):
    if not p:
        return "–"
    if p >= 1:
        return f"${p:,.2f}"
    if p >= 0.01:
        return f"${p:.4f}"
    dec = min(14, 3 - math.floor(math.log10(p)))      # 4 significant digits: $0.007281, $0.00001234
    return f"${p:.{dec}f}"


def _chg(x):
    """Jupiter gives percent (e.g. -0.45 = -0.45%)."""
    if x is None:
        return "–"
    return f"<span class={'pos' if x > 0 else 'neg' if x < 0 else 'mut'}>{x:+.1f}%</span>"


def _icon(u, sym):
    if u and str(u).startswith("https://"):
        return (f"<img src=\"{esc(u)}\" alt=\"\" width=24 height=24 loading=lazy referrerpolicy=no-referrer "
                "onerror=\"this.style.visibility='hidden'\" "
                "style='border-radius:50%;display:inline-block;vertical-align:middle;margin-right:8px;background:#eef'>")
    return ""


def coin_list(lang):
    from ui import coins as K
    t, base_t = C[lang], L[lang]
    rows = K.top()
    trs = []
    for r in rows:
        trs.append(f"<tr><td class=mut>{r['rank']}</td><td><a href=\"{t['prof']}{r['slug']}\">{_icon(r['icon'], r['symbol'])}"
                   f"{esc(r['name'] or r['symbol'])}</a> <span class=mut>{esc(r['symbol'])}</span>"
                   f"<div class='m mut'>{t['cols'][4]} {_usd(r['mcap'])}</div></td>"
                   f"<td class=n>{_price(r['price'])}</td><td class=n>{_chg(r['chg24h'])}</td>"
                   f"<td class='n x'>{_usd(r['mcap'])}</td><td class='n x'>{_usd(r['liq'])}</td>"
                   f"<td class='n x'>{_int(r['holders'], lang)}</td><td class='n x'>{_usd(r['vol24'])}</td></tr>")
    head = "".join(f"<th class='{'n' if j > 1 else ''}{' x' if j > 3 else ''}'>{x}</th>" for j, x in enumerate(t["cols"]))
    upd = max((r["updated"] or 0 for r in rows), default=0)
    when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(upd)) if upd else ""
    table = (f"<div class=tw><table class=coins><thead><tr>{head}</tr></thead><tbody>{''.join(trs)}</tbody></table></div>"
             f"<p class=mut style='font-size:13px'>{t['updated']} {when} · Jupiter, KriptoRadar</p>"
             if trs else f"<p class=mut>{base_t['none']}</p>")
    body = (f"<section class=ph1><div class=eyebrow>KriptoRadar</div><h1>{t['lb_h1']}</h1>"
            f"<p class=lead>{t['lb_lead'].format(n=len(rows) or 100)}</p></section>{table}"
            f"<div class=lock><p>{base_t['lb_lock']}</p><a class='btn sm' href={base_t['home']}#pristup>{base_t['cta']}</a></div>"
            + _seo_extra(lambda S: S.list_links(lang)))
    jsonld = ('<script type="application/ld+json">' + json.dumps({
        "@context": "https://schema.org", "@type": "ItemList", "name": t["lb_h1"],
        "itemListElement": [{"@type": "ListItem", "position": r["rank"], "name": f"{r['name']} ({r['symbol']})",
                             "url": f"{os.environ.get('RENDER_EXTERNAL_URL', '').rstrip('/')}{t['prof']}{r['slug']}"}
                            for r in rows[:100]]}) + "</script>")
    return _shell(lang, t["lb_title"], t["lb_desc"], "/solana-meme-coins", "/hr/solana-meme-coini", body, jsonld=jsonld)


def coin_page(slug, lang):
    from ui import coins as K
    if not re.fullmatch(r"[a-z0-9\-]{1,40}", slug or ""):
        return None
    r, hist = K.coin(slug)
    if not r:
        return None
    t, base_t = C[lang], L[lang]
    o = K.ours(r["mint"], PUBLIC_DELAY_S)
    name, sym = esc(r["name"] or r["symbol"]), esc(r["symbol"])
    same = name.lower().lstrip("$") == sym.lower().lstrip("$")
    a = json.loads(r["audit"] or "{}")
    hold = _int(r["holders"], lang)
    summary = t["summary"].format(name=name, rank=r["rank"] or "–", mcap=_usd(r["mcap"]), holders=hold,
                                  liq=_usd(r["liq"]), vol=_usd(r["vol24"]),
                                  chg=(f"{r['chg24h']:+.1f}%" if r["chg24h"] is not None else "–"))
    c24 = r["chg24h"]
    chg_card = (f"<b class={'pos' if c24 > 0 else 'neg'}>{c24:+.1f}%</b>" if c24 is not None else "<b>–</b>")
    cards = "".join(f"<div class=card>{v if v.startswith('<b') else f'<b>{v}</b>'}<span>{lab}</span></div>"
                    for v, lab in zip((_price(r["price"]), _usd(r["mcap"]), chg_card, hold, _usd(r["liq"]),
                                       _usd(r["vol24"])), t["cards"]))
    # price chart: our daily candles when we have them, else our own snapshots
    if len(o["candles"]) >= 7:
        pp, psrc = [(c["day"], c["c"]) for c in o["candles"]], t["chart_src_d"].format(n=len(o["candles"]))
    else:
        pp, psrc = _hist_or_day(hist, "price", K.day_series(r, 0, r["price"]), t)
    if len(o["holders"]) >= 7:
        hp, hsrc = [(h["day"], h["n"]) for h in o["holders"]], t["chart_src_d"].format(n=len(o["holders"]))
    else:
        hp, hsrc = _hist_or_day(hist, "holders", K.day_series(r, 1, r["holders"]), t)
    up = len(pp) >= 2 and pp[-1][1] >= pp[0][1]
    charts = ""
    for title, pts, src, col, fmt in ((t["chart_p"], pp, psrc, "#16a34a" if up else "#dc2626", _price),
                                      (t["chart_h"], hp, hsrc, "#4f46e5", lambda v: _int(round(v), lang))):
        svg = K.svg_line(pts, color=col, label=f"{sym} {title}")
        if svg:
            charts += (f"<div class=card style='padding:18px'><div style='display:flex;justify-content:space-between'>"
                       f"<b style='font-size:16px'>{title}</b><span class=mut style='font-size:13px'>{src}</span></div>"
                       f"{svg}<div class=rng><span>{fmt(pts[0][1])}</span><span>{fmt(pts[-1][1])}</span></div></div>")
    charts = f"<div class=charts>{charts}</div>" if charts else ""
    ok_auth = a.get("mintAuthorityDisabled") and a.get("freezeAuthorityDisabled")
    sv = [t["yes_off"] if a.get("mintAuthorityDisabled") else t["no_on"],
          t["yes_off"] if a.get("freezeAuthorityDisabled") else t["no_on"],
          f"{a['topHoldersPercentage']:.0f}%" if a.get("topHoldersPercentage") is not None else "–",
          f"{a['devBalancePercentage']:.1f}%" if a.get("devBalancePercentage") is not None else "–",
          f"{r['organic']:.0f}/100" if r["organic"] is not None else "–",
          f"{o['top10'] * 100:.0f}%" if o["top10"] is not None and o["top10"] <= 1 else
          (f"{o['top10']:.0f}%" if o["top10"] is not None else "–"),
          (f"{o['cex'][0]}" + _seo_extra(lambda S: S.cex_short(o["cex"][1]))) if o["cex"] and o["cex"][0] else "–"]
    safe = ("<div class=tw><table><tbody>" + "".join(f"<tr><td>{k}</td><td class=n><b>{v}</b></td></tr>"
                                                    for k, v in zip(t["safe"], sv) if v != "–") + "</tbody></table></div>")
    crow = []
    for c in o["calls"]:
        h = c["handle"] or ""
        who = (f"<a href=\"{base_t['prof']}{esc(h)}\">@{esc(h)}</a>" if HANDLE.fullmatch(h) else esc(h))
        crow.append(f"<tr><td class=mut>{time.strftime('%Y-%m-%d', time.gmtime(c['ts']))}</td><td>{who}</td>"
                    f"<td class=n>{_usd(c['mcap0'])}</td>"
                    + "".join(f"<td class='n {_cls(c[k])}'>{_pct(c[k], True)}</td>" for k in ("r1h", "r24h", "max24"))
                    + "</tr>")
    ch = "".join(f"<th{' class=n' if j > 1 else ''}>{x}</th>" for j, x in enumerate(t["ccols"]))
    calls = (f"<div class=tw><table><thead><tr>{ch}</tr></thead><tbody>{''.join(crow)}</tbody></table></div>"
             if crow else f"<p class=mut>{t['no_calls']}</p>")
    lock = ("<div class=lock style='display:block'><b style='font-size:18px'>" + t["lock_h"] + "</b><ul class=lk>"
            + "".join(f"<li>🔒 {x.format(n=o['fresh'])}</li>" for j, x in enumerate(t["lock"])
                      if j != (3 if o["fresh"] else 2))
            + f"</ul><a class='btn sm' href={base_t['home']}#pristup>{base_t['cta']}</a></div>")
    rows = K.top()
    idx = next((i for i, x in enumerate(rows) if x["mint"] == r["mint"]), None)
    near = [x for x in rows[max(0, (idx or 0) - 4):(idx or 0) + 5] if x["mint"] != r["mint"]][:8] if idx is not None else []
    sim = "".join(f"<a href=\"{t['prof']}{x['slug']}\">{esc(x['symbol'])} · {_usd(x['mcap'])}</a>" for x in near)
    mint = esc(r["mint"])
    links = (f"<a href=\"https://dexscreener.com/solana/{mint}\" target=_blank rel=\"nofollow noopener\">DexScreener ↗</a> · "
             f"<a href=\"https://solscan.io/token/{mint}\" target=_blank rel=\"nofollow noopener\">Solscan ↗</a>")
    addr = (f"<div class=card style='margin:18px 0'><span class=mut style='font-size:13px'>{t['addr']}</span>"
            f"<div style='display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:6px'><code style='font-size:13px;"
            f"word-break:break-all'>{mint}</code><button class='btn g sm' type=button onclick=\"navigator.clipboard&&"
            f"navigator.clipboard.writeText('{mint}');this.textContent='✓'\">{t['copy']}</button></div>"
            f"<div style='margin-top:8px;font-size:14px'>{links}</div></div>")
    safe_txt = t["safe_ok"] if ok_auth else t["safe_bad"]
    faq = [(q.format(sym=sym, name=name), ans.format(sym=sym, name=name, mint=mint, holders=hold, safe=safe_txt))
           for q, ans in t["faq"]]
    faq_html = "".join(f"<details><summary>{q}</summary><p>{x}</p></details>" for q, x in faq)
    base = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    jsonld = ('<script type="application/ld+json">' + json.dumps({
        "@context": "https://schema.org", "@type": "FAQPage",
        "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": x}}
                       for q, x in faq]}) + "</script>")
    body = (f"<section class=ph1><div class=crumb><a href={t['lb_path']}>{t['back']}</a></div>"
            f"<h1>{_icon(r['icon'], sym).replace('24', '44', 2)}{t['p_h1'].format(name=name, sym=sym)} "
            f"<span class=mut style='font-weight:500;font-size:.5em'>{t['p_sub']}</span></h1>"
            f"<p class=lead>{summary}</p></section><div class=cards>{cards}</div>{charts}{lock}"
            f"<h2 class=s>{t['safe_h']}</h2>{safe}<h2 class=s>{t['calls_h']}</h2><p class=mut>{t['calls_note']}</p>{calls}"
            f"{addr}<h2 class=s>{t['faq_h'].format(sym=sym)}</h2><div class=faq style='margin:0'>{faq_html}</div>"
            f"{_seo_extra(lambda S: S.more(r, lang, 'coin'))}"
            + (f"<h2 class=s>{t['similar']}</h2><div class=chips>{sim}</div>" if sim else ""))
    title = t["p_title"].format(name=r["name"] or r["symbol"], sym=r["symbol"])
    desc = t["p_desc"].format(name=r["name"] or r["symbol"], sym=r["symbol"], rank=r["rank"] or "–",
                              mcap=_usd(r["mcap"]).lstrip("$"), holders=hold)
    return _shell(lang, title, desc, f"/coin/{slug}", f"/hr/coin/{slug}", body, jsonld=jsonld)


# ---------- public glossary ----------------------------------------------------------------------------------------

G_T = {
    "en": dict(title="Crypto & Solana meme coin glossary: {n} terms explained | KriptoRadar",
               desc="Plain-English explanations of crypto, Solana meme coin, trading and influencer terms: market cap, "
                    "liquidity, rug pull, KOL, copy trading, DCA, slippage and more.",
               h1="Crypto glossary", lead="{n} terms from Solana meme coin trading, explained in plain words, with "
               "examples and how KriptoRadar measures them.", ex="Example", rel="Related terms", all="← All terms",
               live="See it live", path="/glossary/", idx="/glossary", t_title="{q} {name} explained | KriptoRadar",
               faq="Frequently asked"),
    "hr": dict(title="Kripto rječnik: {n} pojmova o Solana meme coinima objašnjeno | KriptoRadar",
               desc="Jednostavna objašnjenja kripto pojmova: tržišna vrijednost, likvidnost, rug pull, KOL, copy "
                    "trading, DCA, slippage i drugo.",
               h1="Kripto rječnik", lead="{n} pojmova iz trgovanja Solana meme coinima, objašnjeno jednostavno, s "
               "primjerima i načinom na koji ih KriptoRadar mjeri.", ex="Primjer", rel="Povezani pojmovi",
               all="← Svi pojmovi", live="Pogledaj uživo", path="/hr/rjecnik/", idx="/hr/rjecnik",
               t_title="{q} {name} objašnjeno | KriptoRadar", faq="Česta pitanja"),
}
_HR_LIVE = {"/solana-meme-coins": "/hr/solana-meme-coini", "/influencers": "/hr/influenceri",
            "/best-crypto-tools/crypto-wallets": "/hr/najbolji-kripto-alati/kripto-novcanici",
            "/best-crypto-tools/trading-bots": "/hr/najbolji-kripto-alati/trading-botovi",
            "/best-crypto-tools/rug-checkers": "/hr/najbolji-kripto-alati/provjera-ruga",
            "/best-crypto-tools/crypto-apis": "/hr/najbolji-kripto-alati/kripto-api",
            "/best-crypto-tools/copy-trading-platforms": "/hr/najbolji-kripto-alati/copy-trading-platforme"}
_HR_LABEL = {"/hr/solana-meme-coini": "najveći Solana meme coini", "/hr/influenceri": "ljestvica influencera",
             "/hr/najbolji-kripto-alati/kripto-novcanici": "usporedba kripto novčanika",
             "/hr/najbolji-kripto-alati/trading-botovi": "usporedba trading botova i naknada",
             "/hr/najbolji-kripto-alati/provjera-ruga": "usporedba alata za provjeru ruga",
             "/hr/najbolji-kripto-alati/kripto-api": "usporedba kripto API-ja",
             "/hr/najbolji-kripto-alati/copy-trading-platforme": "usporedba copy trading platformi"}


def _gterm(e, lang):
    """(slug, name, question, short, long, example) of one public glossary entry in a language."""
    if lang == "en":
        return e["en"], e["name"], e["q"], e["short"], e["long"], e["ex"]
    from ui import glossary_public as GP
    t = GP.hr_term(e)
    return e["hr"], t["name"], f"Što je {t['name']}?", t["short"], t["long"], t["primjer"]


def glossary_index(lang):
    from ui import glossary_public as GP
    g = G_T[lang]
    items = sorted((_gterm(e, lang) for e in GP.ENTRIES), key=lambda x: x[1].lower())
    lis = "".join(f"<a class=gi href=\"{g['path']}{s_}\"><b>{esc(n)}</b><span>{esc(sh)}</span></a>"
                  for s_, n, _q, sh, _l, _e in items)
    body = (f"<section class=ph1><div class=eyebrow>KriptoRadar</div><h1>{g['h1']}</h1>"
            f"<p class=lead>{g['lead'].format(n=len(items))}</p></section><div class=gl>{lis}</div>"
            f"<div class=lock><p>{L[lang]['lb_lock']}</p><a class='btn sm' href={L[lang]['home']}#pristup>"
            f"{L[lang]['cta']}</a></div>")
    base = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    jsonld = ('<script type="application/ld+json">' + json.dumps({
        "@context": "https://schema.org", "@type": "DefinedTermSet", "name": g["h1"], "url": base + g["idx"],
        "hasDefinedTerm": [{"@type": "DefinedTerm", "name": n, "description": sh, "url": f"{base}{g['path']}{s_}"}
                           for s_, n, _q, sh, _l, _e in items]}, ensure_ascii=False) + "</script>")
    return _shell(lang, g["title"].format(n=len(items)), g["desc"], "/glossary", "/hr/rjecnik", body, jsonld=jsonld)


def glossary_term(slug, lang):
    from ui import glossary_public as GP
    e = (GP.BY_EN if lang == "en" else GP.BY_HR).get(slug)
    if not e:
        return None
    g = G_T[lang]
    s_, name, q, short, long, ex = _gterm(e, lang)
    live = ""
    if e["live"]:
        href, label = e["live"]
        href = href if lang == "en" else _HR_LIVE.get(href, href)
        label = label if lang == "en" else _HR_LABEL.get(href, label)
        live = f"<p><a class='btn g sm' href={href}>{g['live']}: {esc(label)} →</a></p>"
    rel = "".join(f"<a href=\"{g['path']}{_gterm(r, lang)[0]}\">{esc(_gterm(r, lang)[1])}</a>" for r in GP.related(e, lang))
    body = (f"<section class=ph1><div class=crumb><a href={g['idx']}>{g['all']}</a></div><h1>{esc(q)}</h1>"
            f"<p class=lead><b style='color:var(--fg)'>{esc(name)}:</b> {esc(short)}</p></section>"
            f"<div class=gbody>" + (f"<p>{esc(long)}</p>" if long else "")
            + (f"<div class=card style='margin:18px 0'><span class=mut style='font-size:13px'>{g['ex']}</span>"
               f"<p style='margin:6px 0 0'>{esc(ex)}</p></div>" if ex else "") + live + "</div>"
            + (f"<h2 class=s>{g['rel']}</h2><div class=chips>{rel}</div>" if rel else "")
            + f"<div class=lock><p>{L[lang]['lb_lock']}</p><a class='btn sm' href={L[lang]['home']}#pristup>"
              f"{L[lang]['cta']}</a></div>")
    base = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    answer = short + (" " + long if long else "")
    jsonld = ('<script type="application/ld+json">' + json.dumps([
        {"@context": "https://schema.org", "@type": "DefinedTerm", "name": name, "description": short,
         "url": f"{base}{g['path']}{s_}",
         "inDefinedTermSet": {"@type": "DefinedTermSet", "name": g["h1"], "url": base + g["idx"]}},
        {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": answer}}]}],
        ensure_ascii=False) + "</script>")
    title = g["t_title"].format(q=q, name=name)
    desc = (short + " " + long)[:155].rsplit(" ", 1)[0] + "…" if len(short + " " + long) > 155 else short
    return _shell(lang, title, desc, f"/glossary/{e['en']}", f"/hr/rjecnik/{e['hr']}", body, jsonld=jsonld)
