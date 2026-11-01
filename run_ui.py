"""Local web dashboard: wallets, tokens, events and the selection criteria, read-only from calendar.db, hype.db, wallets.db, rug.db, paper.db.

    python3 run_ui.py                         # http://127.0.0.1:8050 (only this computer)
    python3 run_ui.py --port 9000
    UI_PASSWORD=tajna python3 run_ui.py --host 0.0.0.0   # on a VPS: password required (user: any)

Players (Natjecanje): log in with the name from UI_USERS (default Ivan,Panda,Jure) and the password in
UI_PASS_<NAME>, e.g. UI_PASS_IVAN. The shared UI_PASSWORD still works but can only look, not trade.

Only the Python standard library. On a VPS prefer an SSH tunnel over opening the port:
    ssh -L 8050:127.0.0.1:8050 user@vps   then open http://127.0.0.1:8050 locally
"""
import argparse
import base64
import gzip
import hashlib
import hmac
import os
import re
import sys
import time
import traceback

# Own domain: SITE_URL=https://memesonar.app makes every canonical/sitemap/hreflang/og link use it (they read
# RENDER_EXTERNAL_URL), and public pages opened on the old onrender.com address move there with a 301.
SITE_URL = os.environ.get("SITE_URL", "").strip().rstrip("/")
if SITE_URL:
    os.environ.setdefault("RENDER_ORIGINAL_URL", os.environ.get("RENDER_EXTERNAL_URL", ""))
    os.environ["RENDER_EXTERNAL_URL"] = SITE_URL
PUBLIC_PATH = re.compile(r"^/(hr(/.*)?|en|robots\.txt|sitemap\.xml|influencers?(/.*)?|solana-meme-coins(/.*)?|coin/.*|"
                         r"glossary(/.*)?|blog(/.*)?|best-crypto-tools(/.*)?|how-to-buy(/.*)?|rug-check(/.*)?|"
                         r"solana-market|meme-coin-season-index|solana-launchpads|solana-dex-volume|best-time-to-trade-crypto|"
                         r"embed/.*|static/landing/.*)$")


APP_URL = os.environ.get("APP_URL", "").strip().rstrip("/") if SITE_URL else ""
if APP_URL:
    os.environ["APP_URL"] = APP_URL
SHARED_PATH = re.compile(r"^/(static/landing/.*|hook/.*|nas-token/\d+/meta\.json|jezik|sw\.js|cekamo-deploy|healthz)$")   # served on every host


def _host(url_or_host):
    return (url_or_host or "").split("://", 1)[-1].split("/")[0].split(":")[0].lower()


def is_public(path):
    if path in ("/", "/dobrodosli", "/zatrazi-pristup") or PUBLIC_PATH.match(path):
        return True
    try:   # pages other modules add later (coin SEO, market pages) without touching this list
        from ui import public
        return bool(public._seo_page(path))
    except Exception:  # noqa: BLE001
        return False


def moved_to_site(host, path, logged_in):
    """301 target for a page opened on the wrong host, else None.
    SITE_URL alone: public pages on *.onrender.com / www.<site> move to the site; the app stays where it is.
    SITE_URL + APP_URL: the site serves only public pages (landing always at "/"), the app host only the app."""
    if not SITE_URL:
        return None
    site_host, app_host = _host(SITE_URL), _host(APP_URL)
    h = _host(host)
    if not h or h in ("localhost", "127.0.0.1"):
        return None
    shared, pub = bool(SHARED_PATH.match(path)), is_public(path)
    if h == site_host:
        if not APP_URL or shared:
            return None
        if path == "/dobrodosli":
            return SITE_URL + "/hr"
        return None if pub else APP_URL + path
    if APP_URL and h == app_host:
        if path == "/dobrodosli":
            return SITE_URL + "/hr"
        return SITE_URL + path if pub and path != "/" and not shared else None
    if not h.endswith(".onrender.com") and h != "www." + site_host:
        return None
    if APP_URL:
        if path == "/":
            return (APP_URL if logged_in else SITE_URL) + "/"
        return (SITE_URL if pub or shared else APP_URL) + path
    if path == "/" and logged_in and h != "www." + site_host:
        return None      # the dashboard itself stays where the login cookie is
    if path == "/" or PUBLIC_PATH.match(path) or h == "www." + site_host:
        return SITE_URL + path
    return None


def on_site_host(host):
    """True when the app has its own host and this request came to the public site."""
    return bool(APP_URL) and _host(host) == _host(SITE_URL)


from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, unquote, urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui import criteria, evidence, jobs, kol, market, overview, pages, paper, radar, tokens, usage, watch  # noqa: E402
from ui.html import SHOW_ALL, esc, page  # noqa: E402
from ui import pagecache  # noqa: E402
from ui import i18n  # noqa: E402
from ui import league  # noqa: E402
from ui import deploypage  # noqa: E402
from league import store as league_store  # noqa: E402

PASSWORD = os.environ.get("UI_PASSWORD", "")
PLAYERS = {u.lower(): (u, os.environ.get(f"UI_PASS_{u.upper()}", "")) for u in league_store.env_users()}
# view-only test account for Claude's checks of the live dashboard (no player, no trading, not in Natjecanje)
VIEWER, VIEWER_PASS = os.environ.get("UI_TEST_USER", "Claude"), os.environ.get("UI_TEST_PASSWORD", "")
AUTH = bool(PASSWORD or VIEWER_PASS or any(pw for _, pw in PLAYERS.values()))
# login cookie: signed with a key derived from every password, so changing a password logs everybody out
_SECRET = hashlib.sha256(("crypto-bot-session|" + PASSWORD + "|" + VIEWER_PASS + "|" + "|".join(pw for _, pw in PLAYERS.values()))
                         .encode()).digest()
COOKIE, COOKIE_DAYS = "cb_s", 60


def PLAYERS_NAMES():
    return [p for p, _ in PLAYERS.values()]


def _sign(name, exp):
    return hmac.new(_SECRET, f"{name}|{exp}".encode(), hashlib.sha256).hexdigest()


def make_cookie(name):
    exp = int(time.time()) + COOKIE_DAYS * 86400
    return f"{base64.urlsafe_b64encode(name.encode()).decode()}.{exp}.{_sign(name, exp)}"


def cookie_user(value):
    """(ok, player or None) for a cookie value from make_cookie()."""
    try:
        b, exp, sig = value.split(".")
        name, exp = base64.urlsafe_b64decode(b.encode()).decode(), int(exp)
    except Exception:
        return False, None
    if exp < time.time() or not hmac.compare_digest(sig, _sign(name, exp)):
        return False, None
    if not name:
        return bool(PASSWORD), None
    if VIEWER_PASS and name.lower() == VIEWER.lower():
        return True, None
    from league import profiles
    if not profiles.session_ok(name, exp - COOKIE_DAYS * 86400):   # "odjavi me svugdje" or a new password
        return False, None
    player, ppw = PLAYERS.get(name.lower(), (None, ""))
    if player:
        return (True, player) if ppw or profiles.has_password(player) else (False, None)
    from league import members   # registered through an invite link
    member = members.exists(name)
    return (True, member) if member else (False, None)


def check_password(name, pw):
    """(ok, player or None): a player's own name + password, or the shared UI_PASSWORD with any name."""
    player, ppw = PLAYERS.get((name or "").strip().lower(), (None, ""))
    if player:
        from league import profiles
        own = profiles.check_password(player, pw)   # a password the player set in ⚙️ Postavke replaces UI_PASS_<NAME>
        if own:
            return True, player
        if own is None and ppw and hmac.compare_digest(pw.encode(), ppw.encode()):
            return True, player
    if VIEWER_PASS and (name or "").strip().lower() == VIEWER.lower():
        return hmac.compare_digest(pw.encode(), VIEWER_PASS.encode()), None
    if not player:
        from league import members   # registered through an invite link
        member = members.verify(name, pw)
        if member:
            return True, member
    return bool(PASSWORD) and hmac.compare_digest(pw.encode(), PASSWORD.encode()), None


def user_kind(user):
    """'env' (UI_USERS player), 'member' (invite link) or 'viewer' (no player: look only)."""
    if not user:
        return "viewer"
    return "env" if user.lower() in PLAYERS else "member"


def _safe_next(n):
    return n if n.startswith("/") and not n.startswith("//") and "\\" not in n else "/"


def login_page(qs, err=""):
    from ui import loginpage
    return loginpage.html(_safe_next(qs.get("next", "/")), qs.get("kao", ""), err, league_store.missing_passwords(),
                          SITE_URL)


def route(path, qs):
    if path == "/":
        return overview.page(qs)
    if path == "/radar":
        return radar.page(qs)
    if path == "/kol":
        return kol.page(qs)
    if path == "/kol-test":
        from ui import koltest
        return koltest.page(qs)
    if path == "/izvori":
        from ui import izvori
        return izvori.page(qs)
    if path.startswith("/kol/"):
        return kol.kol_page(path[len("/kol/"):], qs)
    if path == "/wallets":
        return pages.wallets(qs)
    if path.startswith("/wallet/"):
        return pages.wallet(path[len("/wallet/"):], qs)
    if path == "/tokens":
        return tokens.page(qs)
    if path.startswith("/token/"):
        return pages.token(path[len("/token/"):], qs)
    if path == "/events":
        return pages.events(qs)
    if path == "/watch":
        return watch.page(qs)
    if path == "/paper":
        return paper.page(qs)
    if path == "/usage":
        return usage.page(qs)
    if path == "/market":
        return market.page(qs)
    if path == "/analitika":
        from ui import analitika
        return analitika.page(qs)
    if path == "/criteria":
        return criteria.page(qs)
    if path == "/izlazi":
        from ui import exitspage
        return exitspage.page(qs)
    if path == "/dugorocno":
        from ui import dugo
        return dugo.page(qs)
    if path == "/korelacije":
        from ui import corrpage
        return corrpage.page(qs)
    if path == "/learn":
        from ui import learnpage
        return learnpage.page(qs)
    if path == "/izvjestaj":
        from ui import reportpage
        return reportpage.page(qs)
    if path == "/pojmovnik":
        from ui import glossarypage
        return glossarypage.page(qs)
    if path == "/mapa":
        from ui.html import map_page
        return map_page(qs)
    if path == "/trazi":
        from ui import search
        return search.page(qs)
    if path == "/outputs":
        return pages.outputs(qs)
    if path.startswith("/outputs/"):
        return pages.output(path[len("/outputs/"):], qs)
    return None


def build(path, qs, lang="hr"):
    """(code, html bytes) of a route() page with the banner, in `lang`; used through ui/pagecache (which may
    run it in a background thread, so the language is set here and not taken from the request)."""
    i18n.LANG.set(lang)
    SHOW_ALL.set(qs.get("sve") == "1")
    try:
        res = route(path, qs)
        if res is None:
            code, html = 404, page("404", "<h1>Nema te stranice</h1><p><a href=/>Na pregled</a></p>", path)
        else:
            code, html = 200, page(res[0], _banner(path) + res[1], path)
    except Exception:
        code = 500
        html = page("Greška", f"<h1>Greška</h1><pre>{esc(traceback.format_exc())}</pre>", path)
    return code, i18n.translate(html).encode("utf-8")


def english(raw, gz, lang):
    """(200, html bytes) in `lang` from a Croatian page as pagecache keeps it."""
    html = (raw if raw is not None else gzip.decompress(gz)).decode("utf-8")
    i18n.LANG.set(lang)
    return 200, i18n.translate(html).encode("utf-8")


def _banner(path):
    """Spend warnings on top of every page (the /usage page lists them itself)."""
    if path == "/usage":
        return ""
    try:
        return usage.banner()
    except Exception:
        return ""


class Handler(BaseHTTPRequestHandler):
    user = os.environ.get("UI_LOCAL_USER") if not AUTH else None   # local run without passwords: play as this name

    def _set_lang(self):
        """cb_lang cookie -> self.lang and the i18n context of this request."""
        self.lang = "hr"
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == i18n.COOKIE and v in ("hr", "en"):
                self.lang = v
        i18n.LANG.set(self.lang)

    def do_GET(self):
        self._index = False   # every page is noindex unless it is one of the public, indexable ones
        self._public = False  # public pages have their own English version and are never run through ui/i18n
        self._set_lang()
        ok = not AUTH or self._authorized()
        u = urlsplit(self.path)
        path, qs = unquote(u.path), dict(parse_qsl(u.query))
        to = moved_to_site(self.headers.get("Host"), path, ok and AUTH)
        if to:
            return self._redirect(to + (f"?{u.query}" if u.query else ""), code=301)
        if path == "/jezik":
            return self._lang_switch(qs)
        if path in ("/sw.js", deploypage.PATH, "/healthz"):   # deploy page + its service worker, every host, no login
            if path == "/sw.js":
                return self._send(200, deploypage.sw_js().encode("utf-8"), "text/javascript")
            if path == "/healthz":
                return self._send(200, b"ok", "text/plain")
            self._public = True
            return self._send(200, deploypage.html().encode("utf-8"))
        if path == "/prijava":
            return self._login(qs)
        if path == "/registracija":
            from ui import register
            return self._send(200, register.page_html(qs).encode("utf-8"))
        site = on_site_host(self.headers.get("Host"))
        if path in ("/dobrodosli", "/hr", "/en") or (path == "/" and (site or not ok and not APP_URL)):
            # public sales page (English main); with an own app host, "/" on the site is always this page
            self._public = True
            from ui import landing
            if path == "/en" and (site or not ok):
                return self._redirect("/", code=301 if site else 303)
            lang = "en" if path in ("/", "/en") else "hr"   # /en: the English page for logged-in users (canonical /)
            self._index = path not in ("/dobrodosli", "/en")
            return self._send(200, landing.page_html(qs, logged_in=ok and AUTH and not site, ok=qs.get("poslano") == "1", lang=lang)
                              .encode("utf-8"))
        from ui import public
        pub = public.route(path)
        if pub:   # indexable pages: influencer leaderboard and profiles, robots.txt, sitemap.xml
            self._public = True
            self._index = pub[0] == 200
            return self._send(pub[0], pub[1], pub[2])
        if path.startswith("/static/landing/"):
            return self._static(path[len("/static/landing/"):])
        m = re.fullmatch(r"/nas-token/(\d+)/meta\.json", path)
        if m:   # public token metadata: wallets, pump.fun and explorers read it without logging in
            from ui import nastoken
            body = nastoken.meta_json(int(m.group(1)))
            return self._send(200 if body else 404, (body or "{}").encode("utf-8"), "application/json")
        if path == "/odjava":
            return self._redirect("/prijava", cookie=f"{COOKIE}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax")
        if path.startswith("/avatar/") and ok:
            return self._avatar(path[len("/avatar/"):])
        if not ok:
            # a login form instead of the browser's own password box: phones and in-app browsers often never show
            # that box, the page then just stays blank. 401 without WWW-Authenticate, so no box pops up.
            nxt = path + (f"?{u.query}" if u.query else "")
            return self._send(401, login_page({"next": nxt}).encode("utf-8"))
        if path == "/postavke":
            from ui import settings
            try:
                html = page(*settings.page(qs, self.user, user_kind(self.user), self.lang), path)
            except Exception:
                html = page("Greška", f"<h1>Greška</h1><pre>{esc(traceback.format_exc())}</pre>", path)
            return self._send(200, html.encode("utf-8"))
        if path == "/zahtjevi":
            from ui import landing
            try:
                html = page(*landing.admin_page(qs, self.user), path)
            except Exception:
                html = page("Greška", f"<h1>Greška</h1><pre>{esc(traceback.format_exc())}</pre>", path)
            return self._send(200, html.encode("utf-8"))
        if path in ("/natjecanje", "/prijedlozi", "/copy-trading"):
            SHOW_ALL.set(qs.get("sve") == "1")
            from ui import copytrade
            fn = {"/natjecanje": league.page, "/prijedlozi": league.ideas_page,
                  "/copy-trading": copytrade.page}[path]
            try:
                html = page(*fn(qs, self.user), path)
            except Exception:
                html = page("Greška", f"<h1>Greška</h1><pre>{esc(traceback.format_exc())}</pre>", path)
            return self._send(200, html.encode("utf-8"))
        if path == "/nas-token/launch.js":
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "nastoken_launch.js"), "rb") as f:
                return self._send(200, f.read(), "text/javascript")
        if path == "/nas-token" or path.startswith("/nas-token/"):
            from ui import nastoken
            rest = path[len("/nas-token/"):]
            try:
                res = nastoken.page(qs, self.user) if path == "/nas-token" or not rest else \
                    nastoken.strategy_page(qs, self.user) if rest == "strategija" else \
                    nastoken.project_page(int(rest), qs, self.user, self.headers.get("Host")) if rest.isdigit() else None
                html = page(*res, path) if res else page("404", "<h1>Nema te stranice</h1>", path)
            except Exception:
                html = page("Greška", f"<h1>Greška</h1><pre>{esc(traceback.format_exc())}</pre>", path)
            return self._send(200 if res else 404, html.encode("utf-8"))
        if path == "/whatsapp":
            from ui import whatsapp
            try:
                html = page(*whatsapp.page(qs, self.user), path)
            except Exception:
                html = page("Greška", f"<h1>Greška</h1><pre>{esc(traceback.format_exc())}</pre>", path)
            return self._send(200, html.encode("utf-8"))
        if path.startswith("/izvjestaj/raw/"):
            from ui import reportpage
            body = reportpage.raw(path[len("/izvjestaj/raw/"):])
            return self._send(200 if body else 404, body or b"nema izvjestaja")
        if path == "/api/trazi":
            from ui import search
            return self._send(200, search.api(qs.get("q", "")).encode("utf-8"), "application/json")
        if path == "/api/pojam":
            from ui import glossarypage
            frag = glossarypage.fragment(qs.get("k", ""), qs.get("l", "")[:80], qs.get("t", "")[:800])
            return self._send(200, frag.encode("utf-8"))
        if path == "/api/natjecanje":
            return self._send(200, league.api().encode("utf-8"), "application/json")
        if path == "/api/paper":
            return self._send(200, paper.api(qs).encode("utf-8"), "application/json")
        if path.startswith("/api/evidence/"):
            try:
                frag = evidence.fragment(path[len("/api/evidence/"):])
            except Exception:
                frag = f"<pre>{esc(traceback.format_exc())}</pre>"
            return self._send(200, frag.encode("utf-8"))
        key = (path, u.query, None)    # route() pages are the same for every user
        if self.lang == "hr":
            code, raw, gz = pagecache.get(key, lambda: build(path, qs))
        else:   # English = the (pre-rendered) Croatian page translated, so it is as fast as the Croatian one
            code, raw, gz = pagecache.get(key, lambda: build(path, qs))   # cached Croatian page, then translated
            if code == 200:
                code, raw, gz = pagecache.get(key + (self.lang,), lambda r=raw, g=gz: english(r, g, self.lang))
        self._send(code, raw, gz=gz, translated=True)

    def _send(self, code, body, ctype="text/html", gz=None, translated=False):
        """gzip when the browser takes it: tables shrink ~10x, which is most of a phone's wait."""
        if (body is not None and not translated and ctype == "text/html" and getattr(self, "lang", "hr") == "en"
                and not getattr(self, "_public", False)):
            body = i18n.translate(body.decode("utf-8")).encode("utf-8")
        accepts = "gzip" in (self.headers.get("Accept-Encoding") or "")
        if body is None:            # cached page: only the gzipped copy is kept
            zipped = accepts
            if not zipped:
                body = gzip.decompress(gz)
        else:
            zipped = accepts and len(body) > 1024
        if zipped and gz is None:
            gz = gzip.compress(body, 5)
        out = gz if zipped else body
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Vary", "Accept-Encoding")
        if not getattr(self, "_index", False):
            self.send_header("X-Robots-Tag", "noindex, nofollow")
        if zipped:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        self.wfile.write(out)

    def do_POST(self):
        """/run/<job>: start an on-demand run (button on the page), then back to the page.
        /hook/kol?key=$KOL_HOOK_KEY: webhook for the KOL tracker on X (hype/sources.kol_monitor), its own key."""
        u = urlsplit(self.path)
        self._public = False
        self._set_lang()
        if u.path == "/hook/kol":
            self._kol_hook(u)
            return
        if u.path == "/hook/chain":
            self._chain_hook(u)
            return
        if u.path == "/prijava":
            return self._login_post()
        if u.path == "/registracija":
            return self._register_post()
        if u.path == "/zatrazi-pristup":
            return self._request_post()
        if on_site_host(self.headers.get("Host")):
            return self._redirect(APP_URL + self.path, code=308)
        if AUTH and not self._authorized():
            return self._send(401, login_page({}).encode("utf-8"))
        pagecache.clear()   # a run or a trade changes what the pages show
        path = unquote(urlsplit(self.path).path)
        origin = self.headers.get("Origin") or self.headers.get("Referer") or ""
        same_site = not origin or urlsplit(origin).netloc == self.headers.get("Host")
        if same_site and path.startswith(("/natjecanje/", "/prijedlozi/")):
            n = int(self.headers.get("Content-Length") or 0)
            form = dict(parse_qsl(self.rfile.read(min(n, 100_000)).decode("utf-8", "replace")))
            self.send_response(303)
            from ui import copytrade
            handler = copytrade.post if path.startswith("/natjecanje/copy/") else league.post
            self.send_header("Location", handler(path, form, self.user))
            self.end_headers()
            return
        if same_site and (path == "/nas-token/rpc" or path.endswith("/pump-tx")) and path.startswith("/nas-token/"):
            import json
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(min(n, 200_000)) or b"{}")
            except ValueError:
                body = {}
            from ui import nastoken
            code, out = nastoken.api_post(path, body if isinstance(body, dict) else {}, self.user, self.headers.get("Host"))
            return self._send(code, json.dumps(out).encode("utf-8"), "application/json")
        if same_site and path.startswith("/nas-token/"):
            n = int(self.headers.get("Content-Length") or 0)
            form = dict(parse_qsl(self.rfile.read(min(n, 20_000)).decode("utf-8", "replace")))
            from ui import nastoken
            return self._redirect(nastoken.post(path, form, self.user))
        if same_site and path.startswith("/postavke/"):
            return self._settings_post(path)
        if same_site and path.startswith("/zahtjevi/"):
            from ui import landing
            return self._redirect(landing.admin_post(path, self.user))
        if same_site and path == "/whatsapp/poslano":   # the update was copied or shared to the group
            from ui import whatsapp
            whatsapp.post_shared()
            self.send_response(204)
            self.end_headers()
            return
        if same_site and path == "/paper/izlaz":  # sell an open demo position by hand
            n = int(self.headers.get("Content-Length") or 0)
            form = dict(parse_qsl(self.rfile.read(min(n, 10_000)).decode("utf-8", "replace")))
            return self._redirect(paper.post(path, form, self.user))
        if not path.startswith("/run/") or not same_site:
            self.send_response(403)
            self.end_headers()
            return
        name = path[len("/run/"):]
        jobs.start(name)
        self.send_response(303)
        self.send_header("Location", f"/{name}#run")
        self.end_headers()

    def _kol_hook(self, u):
        from kol import store as kstore
        key = kstore.hook_key()
        if not key or not hmac.compare_digest(dict(parse_qsl(u.query)).get("key", ""), key):
            self.send_response(404)
            self.end_headers()
            return
        n = int(self.headers.get("Content-Length") or 0)
        try:
            import json
            from hype import sources
            sources.ingest_kol_event(json.loads(self.rfile.read(min(n, 1_000_000)) or b"{}"),
                                     os.path.join(os.path.dirname(os.path.abspath(__file__)), "hype.db"))
            self.send_response(204)
        except Exception:
            self.send_response(400)
        self.end_headers()

    def _chain_hook(self, u):
        """/hook/chain?key=...: Helius enhanced webhook with swaps of the KOL wallets (kol/chainwatch.py)."""
        from kol import chainwatch, store as kstore
        key = kstore.chain_key()
        if not key or not hmac.compare_digest(dict(parse_qsl(u.query)).get("key", ""), key):
            self.send_response(404)
            self.end_headers()
            return
        n = int(self.headers.get("Content-Length") or 0)
        try:
            import json
            payload = json.loads(self.rfile.read(min(n, 5_000_000)) or b"[]")
            try:   # Helius bills every delivered event (1 credit), so the meter must see them too
                from usage import meter
                meter.helius_webhook(len(payload) if isinstance(payload, list) else 1)
            except Exception:
                pass
            chainwatch.ingest(payload, os.path.join(os.path.dirname(os.path.abspath(__file__)), "hype.db"))
            self.send_response(200)
        except Exception:
            self.send_response(400)
        self.end_headers()

    def _login(self, qs):
        """/prijava: login form. A logged-in player goes on to the competition unless switching (?kao=<name>)."""
        if self.user and self.user != qs.get("kao") and not qs.get("next"):
            return self._redirect("/natjecanje")
        return self._send(200, login_page(qs).encode("utf-8"))

    def _login_post(self):
        n = int(self.headers.get("Content-Length") or 0)
        form = dict(parse_qsl(self.rfile.read(min(n, 10_000)).decode("utf-8", "replace")))
        ok, player = check_password(form.get("name", ""), form.get("pw", ""))
        if not ok:
            time.sleep(1)   # slows down guessing
            return self._send(401, login_page({"next": form.get("next", "/"), "kao": form.get("name", "")},
                                              "Pogrešno ime ili lozinka.").encode("utf-8"))
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
        viewer = VIEWER if not player and VIEWER_PASS and form.get("name", "").strip().lower() == VIEWER.lower() else ""
        cookie = (f"{COOKIE}={make_cookie(player or viewer)}; Max-Age={COOKIE_DAYS * 86400}; Path=/; HttpOnly; "
                  f"SameSite=Lax{secure}")
        cookies = [cookie]
        if player:   # the language chosen in ⚙️ Postavke follows the player to a new device
            from league import profiles
            lang = profiles.get(player).get("lang")
            if lang in ("hr", "en"):
                cookies.append(self._lang_cookie(lang))
        return self._redirect(_safe_next(form.get("next", "/")), cookie=cookies)

    def _lang_cookie(self, lang):
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
        return f"{i18n.COOKIE}={lang}; Max-Age={400 * 86400}; Path=/; SameSite=Lax{secure}"

    def _lang_switch(self, qs):
        """/jezik?l=en: switch the app language (cookie + the player's settings), back to the page you were on."""
        lang = qs.get("l") if qs.get("l") in ("hr", "en") else "hr"
        if self.user:
            try:
                from league import profiles
                profiles.set_lang(self.user, lang)
            except Exception:
                pass
        nxt = qs.get("next")
        if not nxt:
            ref = urlsplit(self.headers.get("Referer") or "")
            nxt = (ref.path + (f"?{ref.query}" if ref.query else "")) if ref.netloc == self.headers.get("Host") else "/"
        if lang == "en":
            i18n.seed()   # first English visitor: queue the whole app for translation (no-op once done)
        return self._redirect(_safe_next(nxt or "/"), cookie=self._lang_cookie(lang))

    def _avatar(self, file):
        from league import profiles
        p = profiles.avatar_path(file.split("?")[0])
        if not p:
            return self._send(404, b"", "image/jpeg")
        with open(p, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "private, max-age=604800")
        self.end_headers()
        self.wfile.write(body)

    def _settings_post(self, path):
        """⚙️ Postavke forms. A password change or "log out everywhere" gives this device a fresh login."""
        from ui import settings
        n = int(self.headers.get("Content-Length") or 0)
        form = dict(parse_qsl(self.rfile.read(min(n, 600_000)).decode("utf-8", "replace")))
        kind = user_kind(self.user)
        loc, extra = settings.post(path, form, self.user, kind, lambda u, pw: check_password(u, pw)[1] == u)
        msg = loc.split("err=", 1)[1].split("#")[0] if "err=" in loc else "ok"
        print(f"postavke: {self.user} {path[len('/postavke/'):]} -> {unquote(msg)[:120]}", flush=True)
        pagecache.clear()
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
        if extra == "relogin":
            cookie = (f"{COOKIE}={make_cookie(self.user)}; Max-Age={COOKIE_DAYS * 86400}; Path=/; HttpOnly; "
                      f"SameSite=Lax{secure}")
            return self._redirect(loc, cookie=cookie)
        if extra == "logout":
            return self._redirect(loc, cookie=f"{COOKIE}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax")
        return self._redirect(loc)

    def _register_post(self):
        """Invite link form: makes the player, logs them in and opens the competition."""
        from ui import register
        n = int(self.headers.get("Content-Length") or 0)
        form = dict(parse_qsl(self.rfile.read(min(n, 10_000)).decode("utf-8", "replace")))
        name, err = register.post(form, list(PLAYERS_NAMES()) + [VIEWER])
        if err:
            time.sleep(1)   # slows down guessing invite links
            return self._send(400, register.page_html({"k": form.get("k", ""), "name": form.get("name", "")}, err)
                              .encode("utf-8"))
        pagecache.clear()
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
        cookie = (f"{COOKIE}={make_cookie(name)}; Max-Age={COOKIE_DAYS * 86400}; Path=/; HttpOnly; "
                  f"SameSite=Lax{secure}")
        from urllib.parse import quote
        msg = f"Dobrodošao, {name}! Tvoj demo račun od ${league_store.START_USD:,.0f} je spreman. Kupi prvi token ispod."
        return self._redirect(f"/natjecanje?ok={quote(msg)}#kupi", cookie=cookie)

    def _request_post(self):
        """'Zatraži pristup' on the public page: stored for the organiser (/zahtjevi)."""
        from ui import landing
        n = int(self.headers.get("Content-Length") or 0)
        form = dict(parse_qsl(self.rfile.read(min(n, 10_000)).decode("utf-8", "replace")))
        ip = (self.headers.get("X-Forwarded-For") or self.client_address[0] or "").split(",")[0].strip()
        ok, err = landing.submit(form, ip)
        lang = "en" if form.get("lang") == "en" else "hr"
        if not ok:
            err = landing.ERR_EN.get(err, err) if lang == "en" else err
            return self._send(400, landing.page_html({}, err=err, form=form, lang=lang).encode("utf-8"))
        return self._redirect(("/" if lang == "en" else "/hr") + "?poslano=1#forma")

    def _static(self, name):
        """Screenshots of the public page: only plain file names from ui/static/landing."""
        from ui import landing
        if not re.fullmatch(r"[a-z0-9\-]+\.(jpg|png|webp)", name):
            return self._send(404, b"")
        fp = os.path.join(landing.STATIC, name)
        if not os.path.isfile(fp):
            return self._send(404, b"")
        with open(fp, "rb") as f:
            body = f.read()
        ctype = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}[name.rsplit(".", 1)[1]]
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location, cookie=None, code=303):
        self.send_response(code)
        self.send_header("Location", location)
        for c in ([cookie] if isinstance(cookie, str) else cookie or []):
            self.send_header("Set-Cookie", c)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _authorized(self):
        """A player's own name + password sets self.user; the shared UI_PASSWORD (any name) lets in without one."""
        self.user = None
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                ok, player = cookie_user(v)
                if ok:
                    self.user = player
                    return True
        h = self.headers.get("Authorization", "")   # old browser password box still works
        if not h.startswith("Basic "):
            return False
        try:
            name, _, pw = base64.b64decode(h[6:]).decode().partition(":")
        except Exception:
            return False
        ok, self.user = check_password(name, pw)
        return ok

    def log_message(self, fmt, *args):
        if self.server.verbose:
            super().log_message(fmt, *args)


def _bind(host, port):
    """Take the port over from deploy_wait.py (the funny deploy page that holds it while we load): tell it to let
    go, then retry the bind for a few seconds instead of failing on "address in use"."""
    wait_flag = os.environ.get("DEPLOY_WAIT_FLAG", "/tmp/memesonar-ui-starting")
    try:
        open(wait_flag, "w").close()
    except OSError:
        pass
    ThreadingHTTPServer.allow_reuse_address = True
    for i in range(200):
        try:
            return ThreadingHTTPServer((host, port), Handler)
        except OSError:
            if i == 199:
                raise
            time.sleep(0.05)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8050)
    p.add_argument("--verbose", action="store_true")
    a = p.parse_args(argv)
    if a.host not in ("127.0.0.1", "localhost", "::1") and not AUTH:
        sys.exit("Slušaš na javnoj adresi bez lozinke. Postavi UI_PASSWORD=... ili koristi SSH tunel (vidi --help).")
    srv = _bind(a.host, a.port)
    srv.verbose = a.verbose
    if os.environ.get("LEAGUE_AUTO_SELL", "1") == "1":  # competition auto sell; this process is league.db's only writer
        import threading
        from league import auto
        from ui.paper import market
        threading.Thread(target=auto.loop, args=(market,), daemon=True, name="auto-sell").start()
    # heaviest pages rendered in the background right away and every 5 min, so a visit never waits for them
    from ui import landing
    landing.start()   # live numbers of the public page, counted in the background
    try:
        from ui import marketpub
        marketpub.warm()   # public market pages: numbers ready before the first visitor
    except Exception as e:  # noqa: BLE001
        print(f"marketpub: {e}", flush=True)
    from ui import coins
    coins.start()     # public top-100 Solana meme coins (Jupiter list every 3 h) -> public.db
    try:
        from analytics import gsc
        gsc.start()   # Google Search Console every 6 h -> analytics.db (only with GSC_SERVICE_ACCOUNT_JSON)
        from analytics import ga4
        ga4.start()   # GA4 Data API, same key, only with GA4_PROPERTY_ID
    except Exception as e:  # noqa: BLE001
        print(f"gsc: {e}", flush=True)
    pagecache.warm(["/", "/tokens"], lambda p: build(p, {}), every_s=int(os.environ.get("UI_WARM_EVERY_S", "300")))
    if os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("I18N_OFF"):
        import threading
        # English version: every known text of the app is translated in the background a few minutes after start
        # (after the maintenance run); already translated ones are skipped, so after the first time this is a no-op
        threading.Timer(float(os.environ.get("I18N_SEED_DELAY_S", "240")), i18n.seed).start()
    print(f"crypto-bot UI sluša na {a.host}:{a.port}" + ("  (sve adrese, lozinka uključena)" if a.host == "0.0.0.0" else "")
          + "  (Ctrl+C za kraj)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
