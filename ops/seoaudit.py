"""SEO check of the public site (memesonar.app): every page type in English and Croatian.

  python3 -m ops.seoaudit --live                  2-3 pages of every type from the live sitemap, one table
  python3 -m ops.seoaudit --live --per-type 5     more pages per type
  python3 -m ops.seoaudit --live --sitemap-all    also every sitemap URL: status 200, no redirect, indexable
  python3 -m ops.seoaudit --offline               the same checks on pages rendered here (no network, no data)

13.11. (Jure: "provjeri još jednom SEO metatitlove URL-ove vidjeli je Google sav content, je li u HTML-u, i što se može
još poboljšati iz SEO perspektive"; "Za svaku stranicu koja je objavljena mora postati hrvatska i engleska verzija").
Per page: status, <html lang>, title and description (length, language), canonical (absolute, self), hreflang
en/hr/x-default (reciprocal, pointing to 200 pages), one <h1>, text in the server HTML, Croatian words on English
pages and English words on Croatian pages, og:locale/title/description/image, JSON-LD, the language switch link,
page weight and render-blocking scripts. Duplicate titles/descriptions across the sample are listed at the end.
Only the standard library; the live mode sends a browser user agent (a Googlebot one is refused by some proxies).
"""
import argparse
import gzip
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from html.parser import HTMLParser

BASE = "https://memesonar.app"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 MemeSonarSEOAudit"
TITLE_MIN, TITLE_MAX = 25, 70       # Google cuts at ~600 px (~60-70 chars); a short brand-only title wastes the slot
DESC_MIN, DESC_MAX = 50, 160
MIN_WORDS = 120                     # visible words in the server HTML below this = thin (or built by JS)

# Croatian words that never appear in English text (function words, the site's own vocabulary)
HR_WORDS = set("""je su nije nisu i ili za na od u iz se da ne što koji koja koje kojeg kao sve svi još bez prije nakon
dana dan sati sat tjedan tjedna mjesec godine danas jučer sada više manje vrh pad rast izvor podaci ažurirano vidi
kupnja kupi prodaja prodaj provjera ocjena pouzdanost sigurnost cijena tržište tržišta novčanik novčanika novčanici
poziv pozivi poziva pogodak pogodaka ukupno prosjek prosječno zadnji zadnja zadnjih prvi prva najbolji najveći
kako zašto kada gdje koliko tko ovaj ova ovo ovdje također samo ali jer pa te uz kod po prema između oko
token tokena tokeni tokene coina coini influencera influenceri kanal kanala kanali stranica stranice pojam pojmovi
rječnik vodič vodiči alati alat besplatno prijava odjava zatraži pristup""".split()) - {"token"}
# English function words that a Croatian sentence never needs (trader terms like wallet, rug, KOL are fine in HR)
EN_WORDS = set("""the and with for of is are was were this that these those from your you our we they it its
be been has have had not no yes all more less read see new today yesterday updated how what why when where which who
by in at about into than then there here every each per most best free learn guide guides price prices buy sell
home back next previous page pages list day days hours hour week month year hit rate""".split())
# words both languages share or that are names; never counted
SHARED = set("""kol kols x sol usd usdc solana pump fun dex dexscreener jupiter raydium phantom telegram memesonar rug
rugs wallet wallets copy trading bot bots api apis dca stop loss take profit market cap mcap fdv ath atl holders
holderi meme memecoin coin coins crypto kripto blog ok a o top call calls""".split())
# terms both languages write in English: removed before counting
PHRASES = re.compile(r"pump (?:and|&) dump|profit and loss|take profit|stop loss|smart money|market cap|"
                     r"how to buy|price prediction|rug pull|copy trading|wallet tracker|trading bot|"
                     r"dollar[- ]cost averaging|fear (?:and|&) greed|all[- ]time high", re.I)
_WORD = re.compile(r"[A-Za-zČčĆćŠšŽžĐđ][A-Za-zČčĆćŠšŽžĐđ'\-]*")
_DIACRITIC = re.compile(r"[ČčĆćŠšŽžĐđ]")


class Page(HTMLParser):
    """The facts of one HTML page the checks need."""
    SKIP = {"script", "style", "noscript", "svg", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lang = None
        self.title = ""
        self.meta = {}           # name/property -> content
        self.canonical = []
        self.hreflang = {}       # lang -> href
        self.h1 = []
        self.links = []          # (href, hreflang attr, text)
        self.jsonld = []
        self.blocking = 0        # <script src> in <head> without async/defer
        self.stylesheets = 0
        self.text = []           # visible text pieces
        self._stack = []
        self._skip = 0
        self._in = None          # "title", "h1", "jsonld", "a"
        self._buf = []
        self._a = None
        self._head = False
        self._notr = 0           # inside translate=no / a code element: names, not language

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "html":
            self.lang = a.get("lang")
        elif tag == "head":
            self._head = True
        elif tag == "body":
            self._head = False
        elif tag == "meta":
            k = a.get("name") or a.get("property")
            if k:
                self.meta.setdefault(k.lower(), a.get("content", ""))
        elif tag == "link":
            rel = a.get("rel", "").lower()
            if rel == "canonical":
                self.canonical.append(a.get("href", ""))
            elif rel == "alternate" and a.get("hreflang"):
                self.hreflang[a["hreflang"].lower()] = a.get("href", "")
            elif rel == "stylesheet":
                self.stylesheets += 1
        elif tag == "script":
            if a.get("type") == "application/ld+json":
                self._in, self._buf = "jsonld", []
            elif self._head and a.get("src") and "async" not in a and "defer" not in a and a.get("type") != "module":
                self.blocking += 1
        elif tag == "title" and not self.title:
            self._in, self._buf = "title", []
        elif tag == "h1":
            self._in, self._buf = "h1", []
        elif tag == "a":
            self._a = [a.get("href", ""), a.get("hreflang", ""), []]
        if tag in self.SKIP:
            self._skip += 1
        if a.get("translate") == "no" or tag in ("code", "kbd"):
            self._notr += 1
            self._stack.append((tag, True))
        elif tag not in ("meta", "link", "br", "img", "input", "hr", "source", "wbr"):
            self._stack.append((tag, False))

    def handle_endtag(self, tag):
        if tag == "script" and self._in == "jsonld":
            self.jsonld.append("".join(self._buf))
            self._in = None
        elif tag == "title" and self._in == "title":
            self.title = " ".join("".join(self._buf).split())
            self._in = None
        elif tag == "h1" and self._in == "h1":
            self.h1.append(" ".join("".join(self._buf).split()))
            self._in = None
        elif tag == "a" and self._a is not None:
            self._a[2] = " ".join("".join(self._a[2]).split())
            self.links.append(tuple(self._a))
            self._a = None
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                for _, notr in self._stack[i:]:
                    if notr:
                        self._notr -= 1
                del self._stack[i:]
                break

    def handle_data(self, data):
        if self._in in ("title", "h1", "jsonld"):
            self._buf.append(data)
        if self._a is not None:
            self._a[2].append(data)
        if not self._skip and self._in != "title":
            self.text.append((data, self._notr > 0))


def parse(html):
    p = Page()
    try:
        p.feed(html)
        p.close()
    except Exception:  # noqa: BLE001 - a broken page is reported by its checks, never a crash of the audit
        pass
    return p


def visible_words(p, names=True):
    """Words of the visible text; names=False leaves out text marked translate=no (token names, handles)."""
    return [w for t, notr in p.text if names or not notr for w in _WORD.findall(t)]


def foreign_words(text_pieces, lang):
    """Words of the other language in `text_pieces` [(text, is_name)]: [(word, context)]."""
    out = []
    for t, notr in text_pieces:
        if notr:
            continue
        t = PHRASES.sub(" ", t)
        for m in _WORD.finditer(t):
            w = m.group(0)
            lw = w.lower().strip("'-")
            if lw in SHARED or len(lw) < 1:
                continue
            bad = (lw in HR_WORDS or (_DIACRITIC.search(w) and w[0].islower())) if lang == "en" else \
                (lw in EN_WORDS and lw not in HR_WORDS)
            if bad:
                ctx = " ".join(t[max(0, m.start() - 40):m.end() + 40].split())
                out.append((w, ctx))
    return out


def lang_of(text):
    """'hr', 'en' or '' for a short text (title, description) by its function words."""
    words = [w.lower() for w in _WORD.findall(PHRASES.sub(" ", text)) if w.lower() not in SHARED]
    hr = sum(1 for w in words if w in HR_WORDS or _DIACRITIC.search(w))
    en = sum(1 for w in words if w in EN_WORDS and w not in HR_WORDS)
    if hr > en:
        return "hr"
    if en > hr:
        return "en"
    return ""


def expected_lang(path):
    return "hr" if path == "/hr" or path.startswith("/hr/") or path == "/autopilot" else "en"


def page_type(path):
    """A short name for the kind of page (the table groups by it)."""
    p = path.rstrip("/") or "/"
    if p in ("/", "/hr"):
        return "home"
    hr = p.startswith("/hr/")
    rest = p[3:] if hr else p
    if rest in ("/autopilot", "/en/autopilot") or p in ("/autopilot", "/en/autopilot"):
        return "autopilot"
    parts = [x for x in rest.split("/") if x]
    head = parts[0] if parts else ""
    if len(parts) == 1:
        return head
    if head in ("blog", "best-crypto-tools", "najbolji-kripto-alati") and len(parts) >= 2:
        return f"{head}/{'category' if parts[1] in ('category', 'kategorija') else '*'}"
    return f"{head}/*"


def check(url, status, html, size=None, location=None, base=BASE):
    """(facts, [issues]) of one fetched page."""
    path = url[len(base):] or "/"
    want = expected_lang(path.split("?")[0])
    issues = []
    if status != 200:
        issues.append(f"status {status}" + (f" -> {location}" if location else ""))
        return {"url": url, "status": status, "lang": want}, issues
    p = parse(html)
    f = {"url": url, "status": status, "lang": want, "html_lang": p.lang, "title": p.title,
         "desc": p.meta.get("description", ""), "canonical": p.canonical, "hreflang": dict(p.hreflang),
         "h1": p.h1, "words": len(visible_words(p)), "bytes": size or len(html.encode("utf-8")),
         "blocking": p.blocking}
    if p.lang != want:
        issues.append(f"html lang={p.lang}, expected {want}")
    t = p.title
    if not t:
        issues.append("no <title>")
    elif not TITLE_MIN <= len(t) <= TITLE_MAX:
        issues.append(f"title {len(t)} chars")
    if t and lang_of(t) not in ("", want):
        issues.append(f"title language {lang_of(t)}")
    d = f["desc"]
    if not d:
        issues.append("no meta description")
    elif not DESC_MIN <= len(d) <= DESC_MAX:
        issues.append(f"description {len(d)} chars")
    if d and lang_of(d) not in ("", want):
        issues.append(f"description language {lang_of(d)}")
    if len(p.canonical) != 1:
        issues.append(f"{len(p.canonical)} canonical tags")
    elif p.canonical[0] != url.split("?")[0]:
        issues.append(f"canonical -> {p.canonical[0]}")
    if "robots" in p.meta and "noindex" in p.meta["robots"]:
        issues.append("noindex")
    hl = p.hreflang
    if not hl:
        issues.append("no hreflang")
    else:
        for k in ("en", "hr", "x-default"):
            if k not in hl:
                issues.append(f"hreflang {k} missing")
        if hl.get(want) and hl[want] != url.split("?")[0]:
            issues.append(f"hreflang {want} -> {hl[want]} (not self)")
    if len(p.h1) != 1:
        issues.append(f"{len(p.h1)} <h1>")
    if f["words"] < MIN_WORDS:
        issues.append(f"thin: {f['words']} words in HTML")
    other = hl.get("hr" if want == "en" else "en")
    if other:
        rel = other[len(base):] if other.startswith(base) else other
        if not any(h.split("#")[0] in (other, rel) for h, _, _ in p.links):
            issues.append("no link to the other language")
    fw = foreign_words(p.text, want)
    if fw:
        c = Counter(w.lower() for w, _ in fw)
        f["foreign"] = fw[:8]
        if len(fw) >= 3:
            issues.append(f"mixed language: {len(fw)} {'HR' if want == 'en' else 'EN'} words "
                          f"({', '.join(w for w, _ in c.most_common(6))})")
    loc = p.meta.get("og:locale", "")
    if loc != ("hr_HR" if want == "hr" else "en_US"):
        issues.append(f"og:locale {loc or 'missing'}")
    for k in ("og:title", "og:description", "og:image"):
        if not p.meta.get(k):
            issues.append(f"{k} missing")
    for raw in p.jsonld:
        try:
            data = json.loads(raw)
        except ValueError:
            issues.append("JSON-LD does not parse")
            continue
        for item in (data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []):
            il = item.get("inLanguage") if isinstance(item, dict) else None
            if isinstance(il, str) and il[:2] != want:
                issues.append(f"JSON-LD inLanguage {il}")
    f["jsonld_types"] = sorted({str(i.get("@type")) for raw in p.jsonld for i in _ld_items(raw)})
    if p.blocking:
        issues.append(f"{p.blocking} render-blocking scripts")
    if f["bytes"] > 600_000:
        issues.append(f"heavy: {f['bytes'] // 1000} kB")
    return f, issues


def _ld_items(raw):
    try:
        d = json.loads(raw)
    except ValueError:
        return []
    if isinstance(d, list):
        return [x for x in d if isinstance(x, dict)]
    if isinstance(d, dict):
        return [x for x in d.get("@graph", [d]) if isinstance(x, dict)]
    return []


# --- live --------------------------------------------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def fetch(url, tries=3):
    """(status, html, bytes on the wire, Location) without following redirects."""
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
            with _opener.open(req, timeout=60) as r:
                body = r.read()
                wire = len(body)
                if r.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return r.status, body.decode("utf-8", "replace"), wire, None
        except urllib.error.HTTPError as e:
            body = e.read() or b""
            if e.headers.get("Content-Encoding") == "gzip":
                try:
                    body = gzip.decompress(body)
                except OSError:
                    pass
            return e.code, body.decode("utf-8", "replace"), len(body), e.headers.get("Location")
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            if i == tries - 1:
                return 0, str(e), 0, None
            time.sleep(2 + 3 * i)
    return 0, "", 0, None


def sitemap_urls(base=BASE):
    st, xml, _, _ = fetch(base + "/sitemap.xml")
    if st != 200:
        raise SystemExit(f"sitemap.xml: {st}")
    locs = re.findall(r"<loc>([^<]+)</loc>", xml)
    alts = {}
    for block in re.findall(r"<url>(.*?)</url>", xml, re.S):
        loc = re.search(r"<loc>([^<]+)</loc>", block).group(1)
        alts[loc] = dict(re.findall(r'hreflang="([^"]+)" href="([^"]+)"', block))
    return locs, alts, xml


def robots_allows(robots, path):
    """Google's rule: the longest matching Allow/Disallow wins ($ anchors the end)."""
    best, allow = -1, True
    for line in robots.splitlines():
        k, _, v = line.partition(":")
        k, v = k.strip().lower(), v.strip()
        if k not in ("allow", "disallow") or not v:
            continue
        rx = "^" + re.escape(v).replace(r"\*", ".*").replace(r"\$", "$")
        if re.match(rx, path) and len(v) > best:
            best, allow = len(v), k == "allow"
    return allow


def sample(locs, per_type, seed_paths=()):
    by = defaultdict(list)
    for u in locs:
        by[page_type(u[len(BASE):] or "/") + (" HR" if expected_lang(u[len(BASE):] or "/") == "hr" else " EN")].append(u)
    out = list(seed_paths)
    for k in sorted(by):
        us = by[k]
        step = max(1, len(us) // per_type)
        out += [u for u in us[::step][:per_type] if u not in out]
    return out, by


def run_live(per_type=2, sitemap_all=False, pause=0.4, out=sys.stdout):
    st, robots, _, _ = fetch(BASE + "/robots.txt")
    locs, alts, xml = sitemap_urls()
    print(f"robots.txt {st}; sitemap: {len(locs)} URLs", file=out)
    issues_all = {}
    blocked = [u for u in locs if not robots_allows(robots, u[len(BASE):] or "/")]
    if blocked:
        issues_all["robots.txt"] = [f"{len(blocked)} sitemap URLs disallowed, e.g. {blocked[:3]}"]
    for res in ("/static/landing/og-home.jpg", "/favicon.ico", "/site.webmanifest"):
        if not robots_allows(robots, res):
            issues_all.setdefault("robots.txt", []).append(f"{res} disallowed")
    nolast = xml.count("<url>") - xml.count("<lastmod>")
    if nolast:
        issues_all.setdefault("sitemap", []).append(f"{nolast} URLs without lastmod")
    urls, by = sample(locs, per_type)
    print("types: " + ", ".join(f"{k} {len(v)}" for k, v in sorted(by.items())), file=out)
    facts, rows = {}, []
    for u in urls:
        st, html, wire, loc = fetch(u)
        f, iss = check(u, st, html, location=loc)
        f["wire"] = wire
        # the alternates: 200 and pointing back
        for lg, href in (f.get("hreflang") or {}).items():
            if href == u or lg == "x-default":
                continue
            if href not in facts:
                st2, html2, _, loc2 = fetch(href)
                facts[href] = (st2, parse(html2) if st2 == 200 else None)
                time.sleep(pause)
            st2, p2 = facts[href]
            if st2 != 200:
                iss.append(f"hreflang {lg} -> {st2}")
            elif p2 and p2.hreflang.get(f["lang"]) != u:
                iss.append(f"hreflang {lg} not reciprocal")
        sm = alts.get(u, {})
        for lg in ("en", "hr"):
            if sm.get(lg) and (f.get("hreflang") or {}).get(lg) and sm[lg] != f["hreflang"][lg]:
                iss.append(f"sitemap {lg} alternate differs from the page")
        rows.append((page_type(u[len(BASE):] or "/"), f, iss))
        time.sleep(pause)
    dup_t = Counter(f.get("title") for _, f, _ in rows if f.get("title"))
    dup_d = Counter(f.get("desc") for _, f, _ in rows if f.get("desc"))
    for _, f, iss in rows:
        if f.get("title") and dup_t[f["title"]] > 1:
            iss.append("duplicate title")
        if f.get("desc") and dup_d[f["desc"]] > 1:
            iss.append("duplicate description")
    report(rows, issues_all, out)
    if sitemap_all:
        bad = sitemap_status(locs, pause)
        print(f"\nsitemap: {len(locs)} URLs checked, {len(bad)} not 200/indexable", file=out)
        for u, why in bad[:60]:
            print(f"  {u}  {why}", file=out)
    return rows, issues_all


def sitemap_status(locs, pause=0.3):
    bad = []
    for u in locs:
        st, html, _, loc = fetch(u)
        if st != 200:
            bad.append((u, f"{st} {loc or ''}".strip()))
        elif re.search(r"<meta name=\"?robots\"? content=\"?[^>]*noindex", html):
            bad.append((u, "noindex"))
        else:
            c = re.search(r"<link rel=\"?canonical\"? href=\"?([^\" >]+)", html)
            if c and c.group(1) != u:
                bad.append((u, f"canonical -> {c.group(1)}"))
        time.sleep(pause)
    return bad


def report(rows, site_issues, out=sys.stdout):
    print(f"\n{'type':<28} {'lang':<4} {'st':<4} {'title':<6} {'desc':<5} {'h1':<3} {'words':<6} {'kB':<5} issues", file=out)
    for typ, f, iss in rows:
        print(f"{typ:<28} {f.get('lang', ''):<4} {f.get('status', ''):<4} {len(f.get('title', '')):<6} "
              f"{len(f.get('desc', '')):<5} {len(f.get('h1', [])):<3} {f.get('words', 0):<6} "
              f"{f.get('bytes', 0) // 1000:<5} {'; '.join(iss) or 'ok'}", file=out)
        print(f"    {f['url']}", file=out)
        if f.get("title") and any(i.startswith(("title", "description", "duplicate")) for i in iss):
            print(f"      T: {f['title']}", file=out)
            print(f"      D: {f['desc']}", file=out)
        for w, ctx in (f.get("foreign") or [])[:3] if any("mixed" in i for i in iss) else []:
            print(f"      [{w}] …{ctx}…", file=out)
    for k, v in site_issues.items():
        for i in v:
            print(f"{k}: {i}", file=out)
    n = sum(1 for _, _, iss in rows if iss)
    print(f"\n{len(rows)} pages, {n} with issues", file=out)


# --- offline -----------------------------------------------------------------------------------------------------

def offline_pages():
    """[(url, status, html)] of the public pages rendered in this process (no network; whatever data is on disk)."""
    import os
    os.environ.setdefault("RENDER_EXTERNAL_URL", BASE)
    from ui import landing, public
    out = []
    for lang, path in (("en", "/"), ("hr", "/hr")):
        out.append((BASE + path, 200, landing.page_html({}, lang=lang)))
    for path in offline_paths():
        r = public.route(path)
        if r and r[2] == "text/html":
            out.append((BASE + path, r[0], r[1].decode("utf-8")))
    return out


def offline_paths():
    from ui import glossary_public as GP
    paths = ["/influencers", "/hr/influenceri", "/glossary", "/hr/rjecnik", "/blog", "/hr/blog",
             "/best-crypto-tools", "/hr/najbolji-kripto-alati", "/telegram-channels", "/hr/telegram-kanali",
             "/solana-meme-coins", "/hr/solana-meme-coini"]
    e = GP.ENTRIES[0]
    paths += [f"/glossary/{e['en']}", f"/hr/rjecnik/{e['hr']}"]
    from ui import blog, coinseo, marketpub, tools
    for en, hr, _pr in blog.urls() + tools.urls() + coinseo.urls() + marketpub.urls():
        paths += [en] + ([hr] if hr else [])
    for c in blog.CATS if hasattr(blog, "CATS") else []:
        paths += [blog.cat_path(c, "en"), blog.cat_path(c, "hr")]
    return list(dict.fromkeys(paths))


def run_offline(out=sys.stdout):
    rows = []
    for url, st, html in offline_pages():
        f, iss = check(url, st, html)
        rows.append((page_type(url[len(BASE):] or "/"), f, iss))
    report(rows, {}, out)
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--per-type", type=int, default=2)
    ap.add_argument("--sitemap-all", action="store_true")
    ap.add_argument("--pause", type=float, default=0.4)
    a = ap.parse_args(argv)
    if a.live:
        run_live(a.per_type, a.sitemap_all, a.pause)
    else:
        run_offline()


if __name__ == "__main__":
    main()
