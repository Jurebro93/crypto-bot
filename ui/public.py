"""Public, indexable pages (no login): influencer leaderboard and one page per influencer, English (main) + Croatian.

- /influencers, /influencer/<handle>            English (x-default)
- /hr/influenceri, /hr/influencer/<handle>      Croatian
- /robots.txt, /sitemap.xml
Public = history and scores: calls older than PUBLIC_DELAY_S with their outcome. Fresh calls, live signals, wallets,
copy trading and everything else stay behind the login (and are sent with X-Robots-Tag: noindex by run_ui).
Pages are cached for CACHE_S, so search-engine crawlers cost almost nothing.
"""
import json
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
        p_title="@{h} crypto calls: score {sc}, {hit} hit rate | KriptoRadar",
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
        p_title="@{h} crypto pozivi: ocjena {sc}, pogodak {hit} | KriptoRadar",
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


def _shell(lang, title, desc, path_en, path_hr, body, canonical_lang=None, jsonld=""):
    base = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    t = L[lang]
    from ui.landing import CSS
    svg, name = logo(30)
    canon = base + (path_en if lang == "en" else path_hr)
    switch = (f"<a class=lnk href={path_hr} hreflang=hr>HR</a>" if lang == "en" else
              f"<a class=lnk href={path_en} hreflang=en>EN</a>")
    return f"""<!doctype html><html lang={lang}><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover"><title>{esc(title)}</title>
<meta name=description content="{esc(desc)}"><link rel=canonical href="{canon}">
<link rel=alternate hreflang=en href="{base}{path_en}"><link rel=alternate hreflang=hr href="{base}{path_hr}">
<link rel=alternate hreflang=x-default href="{base}{path_en}">
<meta property="og:type" content="website"><meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}"><meta property="og:url" content="{canon}">
<meta property="og:image" content="{base}/static/landing/kol.jpg"><meta name="twitter:card" content="summary_large_image">
<meta name=theme-color content="#ffffff"><link rel=icon href="data:image/svg+xml,{quote(logo(32)[0])}">{jsonld}
<style>{CSS}{EXTRA_CSS}</style></head><body>
<nav class=s><div class=w><a class=brand href={t['home']}>{svg}<span>{esc(name)}</span></a><span class=sp></span>
<a class='lnk hm' href={t['lb']}>{'Influencers' if lang == 'en' else 'Influenceri'}</a>{switch}
<a class=lnk href=/prijava>{t['login']}</a><a class='btn p sm' href={t['home']}#pristup>{t['cta']}</a></div></nav>
<main class=w>{body}</main>
<footer style='margin-top:64px'><div class=w>© {time.gmtime().tm_year} {esc(name)} · {t['foot']}</div></footer>
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
    table = (f"<div class=tw><table><thead><tr>{head}</tr></thead><tbody>{''.join(trs)}</tbody></table></div>"
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


def robots():
    base = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    return ("User-agent: *\nAllow: /$\nAllow: /hr$\nAllow: /influencers\nAllow: /influencer/\nAllow: /hr/influenceri\n"
            "Allow: /hr/influencer/\nAllow: /static/landing/\nDisallow: /\n\n"
            f"Sitemap: {base}/sitemap.xml\n")


def sitemap():
    base = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    day = time.strftime("%Y-%m-%d", time.gmtime())
    urls = [("/", "/hr", "1.0"), ("/influencers", "/hr/influenceri", "0.9")]
    urls += [(f"/influencer/{r['handle']}", f"/hr/influencer/{r['handle']}", "0.7") for r in influencers()
             if r["s"].get("measured", 0) >= SITEMAP_MEASURED]
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">']
    for en, hr, pr in urls:
        for loc in (en, hr):
            out.append(f"<url><loc>{base}{loc}</loc><lastmod>{day}</lastmod><priority>{pr}</priority>"
                       f'<xhtml:link rel="alternate" hreflang="en" href="{base}{en}"/>'
                       f'<xhtml:link rel="alternate" hreflang="hr" href="{base}{hr}"/></url>')
    out.append("</urlset>")
    return "\n".join(out)


def route(path):
    """(code, body bytes, content type) for a public path, or None when the path is not public."""
    if path in ("/robots.txt", "/sitemap.xml"):
        fn, ctype = (robots, "text/plain") if path == "/robots.txt" else (sitemap, "application/xml")
    elif path in ("/influencers", "/hr/influenceri"):
        lang = "en" if path == "/influencers" else "hr"
        fn, ctype = (lambda: leaderboard(lang)), "text/html"
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
