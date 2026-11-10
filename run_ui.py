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
import json
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
                         r"telegram-channels|telegram/.*|"   # 10.11. (pregled): linked from the landing log and blogs
                         r"embed/.*|static/landing/.*|share/novosti\.png)$")


APP_URL = os.environ.get("APP_URL", "").strip().rstrip("/") if SITE_URL else ""
if APP_URL:
    os.environ["APP_URL"] = APP_URL
# 10.11. (Jure): the public Autopilot page is SHARED, not PUBLIC: a visitor reads it on the site and a logged-in
# player reads it (and writes in its chat) on the app host, where the login cookie is; a PUBLIC path would send the
# player from the app host to the site, where nobody is logged in.
SHARED_PATH = re.compile(r"^/(static/landing/.*|hook/.*|nas-token/\d+/meta\.json|jezik|sw\.js|cekamo-deploy|healthz|"
                         r"favicon\.ico|favicon\.svg|apple-touch-icon\.png|icon-(192|512)\.png|site\.webmanifest|"
                         r"(en/)?autopilot|autopilot/chat)$")   # served on every host


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
from ui import favicon  # noqa: E402
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


def _cookie_name(value):
    """Login name inside a cookie already checked by cookie_user (the view-only account has no player)."""
    try:
        name = base64.urlsafe_b64decode(value.split(".")[0].encode()).decode()
    except Exception:
        return None
    return VIEWER if VIEWER_PASS and name.lower() == VIEWER.lower() else None


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


def is_admin(user):
    """Role admin (league/roles.py): UI_ADMINS, or TRADE_OWNER/Jure when UI_ADMINS is empty, plus whoever an admin
    made admin on /korisnici."""
    if not AUTH:
        return True
    from league import roles
    return bool(user) and roles.role(user) == "admin"


def role_of(who):
    """Role of the login name `who` (player, registered friend or the view-only account; None = shared password)."""
    if not AUTH:
        return "admin"   # local run without passwords
    from league import roles
    return roles.role(who)


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
    if path == "/pregled":
        from ui import pocetna
        return pocetna.page(qs)
    if path == "/":
        return overview.page(qs)
    if path == "/radar":
        return radar.page(qs)
    if path == "/kol":
        return kol.page(qs)
    if path == "/kol-test":
        from ui import koltest
        return koltest.page(qs)
    if path == "/strategije":
        from ui import strategije
        return strategije.page(qs)
    if path == "/izvori":
        from ui import izvori
        return izvori.page(qs)
    if path == "/ekipe":   # 9.11.: crews and the minute check (kol/minute.py)
        from ui import ekipe
        return ekipe.page(qs)
    if path == "/kol/analize":   # 10.11. (Jure, prijedlog 3.3): the analyses that were folded under /kol, one tap away
        return kol.analize_page(qs)
    if path.startswith("/kol/"):
        return kol.kol_page(path[len("/kol/"):], qs)
    if path == "/wallets":
        return pages.wallets(qs)
    if path.startswith("/wallet/"):
        return pages.wallet(path[len("/wallet/"):], qs)
    if path == "/tokens":
        return tokens.page(qs)
    if path == "/tokens/jaki":
        return tokens.page(qs, view="jaki")
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
    if path == "/novo":
        from ui import novo
        return novo.page(qs)
    if path == "/pojmovnik":
        from ui import glossarypage
        return glossarypage.page(qs)
    if path == "/mapa":
        from ui.html import map_page
        return map_page(qs)
    if path in ("/vise", "/vise/sustav"):   # 10.11. (Jure, prijedlog 3.5): "Više" is a page now, not the ☰ drawer
        from ui.html import vise_page
        return vise_page(qs, "sustav" if path == "/vise/sustav" else None)
    if path == "/trazi":
        from ui import search
        return search.page(qs)
    if path == "/outputs":
        return pages.outputs(qs)
    if path.startswith("/outputs/"):
        return pages.output(path[len("/outputs/"):], qs)
    return None


def _no_admin(code, raw, gz):
    """(code, html bytes) of a cached page without its adm-only elements."""
    from ui import admstrip
    body = raw if raw is not None else gzip.decompress(gz)
    return code, admstrip.strip(body.decode("utf-8")).encode("utf-8")


def _error_html():
    """Generic error text for the page; the traceback goes to the server log only (audit 4.11. §4.3)."""
    ref = hashlib.sha256(f"{time.time()}{os.getpid()}".encode()).hexdigest()[:8]
    print(f"ui-greska {ref}:\n{traceback.format_exc()}", file=sys.stderr, flush=True)
    try:   # 10.11. (Jure): the same error in Sentry, under the mark the page and the log show
        from ops import sentry
        sentry.capture(where=f"ui-greska {ref}")
    except Exception:  # noqa: BLE001 - the error page must still be shown
        pass
    return (f"<h1>Greška</h1><p>Stranica se nije mogla složiti. Pokušaj ponovno za minutu. "
            f"<span class=mut>Oznaka za log: {ref}</span></p>")


def _secure_flag(headers):
    """'; Secure' behind https and always on Render (audit 4.11.: not only when the proxy sends the header)."""
    return "; Secure" if headers.get("X-Forwarded-Proto") == "https" or os.environ.get("RENDER") else ""


def csrf_token(session_value):
    """Form token tied to the login cookie (double submit: cookie cb_csrf + hidden field _csrf added by page JS)."""
    return hmac.new(_SECRET, f"csrf|{session_value}".encode(), hashlib.sha256).hexdigest()[:32] if session_value else ""


# POSTs that change money, roles or settings: need a non-empty same-site Origin/Referer AND the form token
CSRF_STRICT = ("/pravi-trade/", "/korisnici/", "/postavke/", "/zahtjevi/", "/run/")


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
        html = page("Greška", _error_html(), path)
    return code, i18n.translate(html).encode("utf-8")


# pages that read every hype signal (or, /ekipe and /kol, every minute candle / every call): built by build_in_child,
# never in this process. 9.11. 19:32: /ekipe (180 s) and /kol (30 s) built here took the UI process to 818 MB, the
# memory watchdog stopped it and every visitor saw Cloudflare's 502 and then the deploy page for a minute.
HEAVY = ("/tokens", "/tokens/jaki", "/pregled", "/ekipe", "/kol", "/kol/analize")
WARM = ("/pregled", "/tokens")   # pre-rendered every few minutes; the others are built on the first visit
SNAPSHOT_ONLY = ("/ekipe", "/kol", "/kol/analize")   # not warmed (180 s / 30 s of CPU), their last good build is kept on disk
# 10.11.: /kol/analize holds what /kol built before (pairs, correlations, together): same child build and snapshot
BUILDING_REFRESH_S = int(os.environ.get("UI_BUILDING_REFRESH_S", "20"))
WARM_SKIP_FRESH_S = int(os.environ.get("UI_WARM_SKIP_FRESH_S", "240"))   # the warmer leaves a page younger than this alone
CHILD_NICE = int(os.environ.get("UI_CHILD_NICE", "5"))   # page builds below the request threads, above the heavy jobs
# 9.11. 22:00: the stdlib server keeps only 5 connections waiting to be accepted; with the CPU at 100 % (KOL search
# round) the 1-2 s fragment polls of a few open Autopilot tabs overflowed it, the kernel refused the rest and Render
# showed 502 (59 of them at 21:15 UTC) although the UI process was alive. A deeper backlog queues them instead.
ThreadingHTTPServer.request_queue_size = int(os.environ.get("UI_BACKLOG", "128"))


def _nice_child():
    """Page builds run at nice CHILD_NICE: below the request threads (nice 0) and above the heavy jobs (ops/heavy
    NICE). 9.11. 20:10: 1 CPU at 100 % (run_dugo + KOL round + a 45-s /pregled build) and every visitor's request,
    every 1-s Autopilot fragment, waited for CPU behind the page build."""
    try:
        os.nice(CHILD_NICE)
    except (OSError, AttributeError):
        pass


def warm_build(path):
    """build_in_child for the warmer: when the page was built less than WARM_SKIP_FRESH_S ago (a visitor's refresh or
    the previous pass) the cached copy is kept, instead of another 22-45 s child build next to the heavy jobs every
    UI_WARM_EVERY_S whether anyone looked or not (9.11. 20:10, 1 CPU at 100 %). 9.11. (audit): pagecache.warm now
    skips such a page before calling this (skip_fresh_s), so the stored copy is not re-packed with a new time; this
    check stays as the guard for a visitor's build that landed in between."""
    with pagecache._lock:
        hit = pagecache._store.get((path, "", None))
    if hit and time.time() - hit[0] < WARM_SKIP_FRESH_S:
        return 200, gzip.decompress(hit[3])
    return build_in_child(path)


def _building_html(path):
    """The 503 "being built" page: refreshes itself (meta refresh + Retry-After in _send) and offers the pages that
    never wait (Autopilot, Natjecanje), so it is a short wait, not a dead end (9.11. 18:08-18:17: Pregled was this
    page for 10 min and the only way on was to keep clicking)."""
    body = (f"<h1>Stranica se trenutno slaže</h1><p>Poslužitelj je zauzet drugim poslom; stranica se gradi u pozadini "
            f"i ova se sama osvježava za {BUILDING_REFRESH_S} s. Pokušaj ponovno za minutu ako se ne pojavi.</p>"
            f"<p><a href=/pravi-trade>Autopilot</a> · <a href=/natjecanje>Natjecanje</a> · <a href=/>Na pregled</a></p>")
    html = page("Stranica nije dostupna", body, path)
    meta = f'<meta http-equiv="refresh" content="{BUILDING_REFRESH_S}">'
    html = html.replace("<head>", "<head>" + meta, 1) if "<head>" in html else meta + html
    return 503, i18n.translate(html).encode("utf-8")


def _last_copy(path, why):
    """(code, html bytes) when the child could not render `path`: the last snapshot pagecache saved on disk (served as
    a 200 so the visitor sees data; its age shows in the page), or the self-refreshing 503 (_building_html). 9.11.
    (audit P33): never build(path) here instead; the HEAVY pages hold ~200 MB of rows and this process also runs the
    copy/auto-sell loop and the webhooks, so an OOM or a watchdog SIGTERM here stops real-money copies for 30 s+."""
    snap = pagecache._load_snap((path, "", None), stale_ok=True)
    if snap:
        print(f"ui: {why}, služim zadnju spremljenu kopiju {path}", flush=True)
        return 200, gzip.decompress(snap[3])
    print(f"ui: {why}, nema spremljene kopije {path}", flush=True)
    return _building_html(path)


def build_in_child(path):
    """(code, html bytes) of `path` rendered by a short child process (`run_ui.py --render PATH`).

    The overview and the token list read every hype signal; built inside this long-lived server that memory stayed
    with it (~200 MB) and the 512 MB server ran out of memory every few minutes (1.11.). A child gives it all back
    when it ends. 9.11. (audit P33): when the heavy lock stays busy for 60 s, or the child fails or times out, the
    last saved copy (or a 503) is served instead of building here (_last_copy); this process never builds HEAVY pages."""
    import subprocess
    from ops import health, heavy
    try:
        # 9.11. 19:05: used to wait up to 60 s for the lock; with run_dugo (29 min) and wallets score holding it one
        # after another, every visit to Pregled after a click waited the full minute and the browser showed the deploy
        # page. Now: lock free -> build under it; busy but RAM for a child (UI_BUILD_FREE_MB) -> build next to the
        # heavy job (the lock guards memory, 2.11. was a 512 MB server); busy and tight -> last copy at once.
        with heavy.slot(wait=0, label="gradnja stranice") as got:
            if not got:
                free = health.container_free_mb()
                if free is not None and free < float(os.environ.get("UI_BUILD_FREE_MB", "600")):
                    return _last_copy(path, f"brava zauzeta ({heavy.holder() or 'nepoznat posao'}), slobodno {free:.0f} MB, "
                                            f"dijete za {path} ne krećem")
                print(f"ui: brava zauzeta ({heavy.holder() or 'nepoznat posao'}), slobodno "
                      f"{free if free is None else round(free)} MB: gradim {path} bez brave", flush=True)
            r = subprocess.run([sys.executable, os.path.abspath(__file__), "--render", path], capture_output=True,
                               timeout=int(os.environ.get("UI_CHILD_TIMEOUT_S", "300")), preexec_fn=_nice_child)
        for ln in r.stderr.decode(errors="replace").splitlines():
            if ln.startswith("ui-tijek:"):   # where a slow build spent its time
                print(ln, flush=True)
        if r.returncode == 0 and r.stdout:
            return 200, r.stdout
        why = f"dijete za {path} nije uspjelo ({r.returncode}): {r.stderr.decode(errors='replace')[-300:]}"
    except subprocess.TimeoutExpired:
        why = f"dijete za {path} predugo"
    return _last_copy(path, why)


def english(raw, gz, lang):
    """(200, html bytes) in `lang` from a Croatian page as pagecache keeps it."""
    html = (raw if raw is not None else gzip.decompress(gz)).decode("utf-8")
    i18n.LANG.set(lang)
    return 200, i18n.translate(html).encode("utf-8")


def _banner(path):
    """Nothing on top of pages any more (2.11.): spend warnings are on /usage (Sustav → Potrošnja) and the urgent
    ones go into the morning report."""
    return ""


class Handler(BaseHTTPRequestHandler):
    user = os.environ.get("UI_LOCAL_USER") if not AUTH else None   # local run without passwords: play as this name
    who = user
    role = "admin" if not AUTH else "osnovni"   # league/roles.py; set again by _authorized on every request

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
        if path in favicon.PATHS:   # icons on every host, no login
            body, ctype = favicon.get(path)
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=604800")
            self.end_headers()
            return self.wfile.write(body)
        if path.startswith("/admin/export/"):   # 7.11.: read-only database copy for offline analysis (EXPORT_KEY)
            return self._export(path[len("/admin/export/"):], qs)
        if path.startswith("/api/mcp/"):   # 10.11.: the MemeSonar MCP server's data (Bearer MCP_API_KEY), no login
            return self._mcp_get(path, qs)
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
        if path == "/share/novosti.png":   # 5.11.: the day's "what is new" card for the evening X post (public)
            from ui import sharecard
            day = (qs.get("d") or "").strip() if isinstance(qs, dict) else ""
            lang = "hr" if isinstance(qs, dict) and qs.get("lang") == "hr" else "en"
            body = sharecard.png(day if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) else None, lang=lang)
            if not body:
                return self._send(404, b"")
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=600")
            self.end_headers()
            return self.wfile.write(body)
        if path in ("/autopilot", "/en/autopilot", "/autopilot/chat"):   # 10.11. (Jure): public Autopilot page and its chat
            return self._autopilot(path, qs, ok)
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
        from league import roles
        need = roles.deny_get(path, self.role)
        if need:   # checked on the server for every page, not only hidden in the menu
            return self._forbidden(path, need)
        if path == "/korisnici":
            from ui import userroles
            try:
                html = page(*userroles.page(qs, self.who, PLAYERS_NAMES(), VIEWER if VIEWER_PASS else None), path)
            except Exception:
                html = page("Greška", _error_html(), path)
            return self._send(200, html.encode("utf-8"))
        if path == "/postavke":
            from ui import settings
            try:
                html = page(*settings.page(qs, self.user, user_kind(self.user), self.lang), path)
            except Exception:
                html = page("Greška", _error_html(), path)
            return self._send(200, html.encode("utf-8"))
        if path == "/zahtjevi":
            from ui import landing
            try:
                html = page(*landing.admin_page(qs, self.user), path)
            except Exception:
                html = page("Greška", _error_html(), path)
            return self._send(200, html.encode("utf-8"))
        if path == "/pravi-trade/log":   # live order log on the Autopilot page, re-fetched every few seconds
            from ui import pravitrade
            frag = pravitrade.log_fragment(self.user)
            return self._send(200 if frag is not None else 403, (frag or "").encode("utf-8"))
        if path in ("/pravi-trade/token", "/pravi-trade/ekipa"):   # 9.11.: pop-ups, re-fetched every second while open
            from ui import pravitrade
            frag = (pravitrade.token_popup(self.user, qs.get("m", "")) if path == "/pravi-trade/token"
                    else pravitrade.crew_popup(self.user, qs.get("h", "")))
            return self._send(200 if frag is not None else 403, (frag or "").encode("utf-8"))
        if path == "/pravi-trade/preskok":
            # 10.11. (Jure): the pop-up of one skipped buy (market cap at the call, +5/+10/+15 min, now), same access
            # as the page; a failure is a 500 with no text and the pop-up says "nema svježih podataka" (POP_JS)
            from ui import pravitrade
            try:
                frag = pravitrade.skip_popup(self.user, qs.get("m", ""), qs.get("t", ""))
            except Exception:  # noqa: BLE001
                _error_html()
                return self._send(500, b"")
            return self._send(200 if frag is not None else 403, (frag or "").encode("utf-8"))
        if path in ("/pravi-trade/pozicije", "/pravi-trade/zovu", "/pravi-trade/ideje"):   # 9.11.: live fragments
            from ui import pravitrade
            fn = {"/pravi-trade/pozicije": pravitrade.positions_fragment, "/pravi-trade/zovu": pravitrade.callers_fragment,
                  "/pravi-trade/ideje": pravitrade.ideas_fragment}[path]
            frag = fn(self.user)
            return self._send(200 if frag is not None else 403, (frag or "").encode("utf-8"))
        if path in ("/pravi-trade/graf", "/pravi-trade/dnevnik", "/pravi-trade/preporuke"):
            # 10.11. (Jure: graf na vrhu, dnevnik na klik, čista stranica): the header with the chart (every 45 s), the
            # open decision log (every second) and the recommendations (once, when opened); same access as the page.
            # A failure is a 500 with no text: the page greys the box and tries again, the trade loop never notices.
            from ui import pravitrade
            fn = {"/pravi-trade/graf": pravitrade.head_fragment, "/pravi-trade/dnevnik": pravitrade.dnevnik_fragment,
                  "/pravi-trade/preporuke": pravitrade.recs_fragment}[path]
            try:
                frag = fn(self.user)
            except Exception:  # noqa: BLE001
                _error_html()   # the traceback to the log under a reference; the box only greys out
                return self._send(500, b"")
            return self._send(200 if frag is not None else 403, (frag or "").encode("utf-8"))
        if path == "/pravi-trade":
            from ui import pravitrade
            try:
                html = page(*pravitrade.page(qs, self.user), path)
            except Exception:
                html = page("Greška", _error_html(), path)
            return self._send(200, html.encode("utf-8"))
        if path in ("/natjecanje", "/prijedlozi", "/copy-trading"):
            SHOW_ALL.set(qs.get("sve") == "1")
            from ui import copytrade
            fn = {"/natjecanje": league.page, "/prijedlozi": league.ideas_page,
                  "/copy-trading": copytrade.page}[path]
            try:
                html = page(*fn(qs, self.user), path)
            except Exception:
                html = page("Greška", _error_html(), path)
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
                html = page("Greška", _error_html(), path)
            return self._send(200 if res else 404, html.encode("utf-8"))
        if path == "/whatsapp":
            from ui import whatsapp
            try:
                html = page(*whatsapp.page(qs, self.user), path)
            except Exception:
                html = page("Greška", _error_html(), path)
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
        if path == "/api/prijedlog":   # 7.11.: live market cap for the picks, or the whole box rebuilt (?box=)
            from ui import prijedlog
            out = prijedlog.api(qs)
            return self._send(200, out.encode("utf-8"), "text/html" if qs.get("box") else "application/json")
        if path == "/api/paper":
            return self._send(200, paper.api(qs).encode("utf-8"), "application/json")
        if path.startswith("/api/evidence/"):
            try:
                frag = evidence.fragment(path[len("/api/evidence/"):])
            except Exception:
                frag = _error_html()
            return self._send(200, frag.encode("utf-8"))
        if path == "/watch":   # Prije eventa is a section of Eventi since 4.11.
            return self._redirect("/events#prije", code=301)
        if path == "/":   # the app opens on Pregled (4.11.: one page with the most important things, then Tokeni)
            return self._redirect("/pregled" + (f"?{u.query}" if u.query else ""), code=302)
        key = (path, u.query, None)    # route() pages are the same for every user
        # the heaviest pages always in a child process, also when a visitor comes before the warm-up finished
        # (right after a deploy: built here they pushed this process to ~200 MB, 1.11.)
        heavy_page = path in HEAVY and not u.query
        mk = (lambda: build_in_child(path)) if heavy_page else (lambda: build(path, qs))
        # 9.11. 19:32: a heavy page that is in neither memory nor on disk is built in the background and the visitor
        # gets the self-refreshing "being built" page at once, instead of a request that hangs 60-180 s (Cloudflare
        # gives up at 100 s) while the child renders
        fetch = (lambda k, b: pagecache.get_bg(k, b, lambda: _building_html(path))) if heavy_page else pagecache.get
        if self.lang == "hr":
            code, raw, gz = fetch(key, mk)
        else:   # English = the (pre-rendered) Croatian page translated, so it is as fast as the Croatian one
            code, raw, gz = fetch(key, mk)   # cached Croatian page, then translated
            if code == 200:
                code, raw, gz = pagecache.get(key + (self.lang,), lambda r=raw, g=gz: english(r, g, self.lang))
        if AUTH and self.role != "admin":   # non-admins get a copy without the adm-only parts (audit 4.11. §4.2)
            code, raw, gz = pagecache.get(key + (self.lang, "noadm"), lambda c=code, r=raw, g=gz: _no_admin(c, r, g))
        self._send(code, raw, gz=gz, translated=True)

    EXPORTABLE = ("kol.db", "strat.db", "shadow.db", "paper.db", "hype.db", "league.db", "wallets.db", "tg.db", "market.db",
                  "koltest.db", "watch.db", "dugo.db")

    def _export(self, name, qs):
        """A consistent read-only copy of one database (sqlite backup API), gzipped. Needs EXPORT_KEY (env) in ?key=;
        without the env the route does not exist. 7.11.: the retro analysis (what separates +15 % from losers) runs
        offline on these copies instead of on the 2 GB server."""
        import gzip
        import sqlite3 as _sq
        import tempfile
        key = os.environ.get("EXPORT_KEY") or ""
        if not key or not hmac.compare_digest(qs.get("key", ""), key) or name not in self.EXPORTABLE:
            return self._send(404, b"nema", "text/plain")
        src = os.path.join(os.environ.get("DATA_DIR") or os.path.dirname(os.path.abspath(__file__)), name)
        if not os.path.exists(src):
            return self._send(404, b"nema baze", "text/plain")
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            a, b = _sq.connect(f"file:{src}?mode=ro", uri=True), _sq.connect(tmp.name)
            with b:
                a.backup(b, pages=4096)
            a.close()
            b.close()
            # 7.11.: streamed in 4 MB pieces; a 1.1 GB hype.db read whole into memory would take the 2 GB server down
            import zlib
            self.send_response(200)
            self.send_header("Content-Type", "application/gzip")
            self.send_header("Content-Disposition", f'attachment; filename="{name}.gz"')
            self.send_header("Cache-Control", "no-store")
            # 7.11. 10:20: this server speaks HTTP/1.0, where "Transfer-Encoding: chunked" means nothing, so Cloudflare
            # passed the chunk sizes through as part of the file (league.db.gz was "not in gzip format"). HTTP/1.0 has
            # its own way: no length, write the body, close the connection.
            self.send_header("Connection", "close")
            self.end_headers()
            comp = zlib.compressobj(3, wbits=31)
            with open(tmp.name, "rb") as f:
                while True:
                    piece = f.read(4 << 20)
                    if not piece:
                        break
                    self.wfile.write(comp.compress(piece))
            self.wfile.write(comp.flush())
            self.close_connection = True
        finally:
            try:
                os.remove(tmp.name)
            except OSError:
                pass

    def _mcp_auth(self):
        """True, or the (code, json) to answer: 404 while MCP_API_KEY is not set (the API does not exist), 401 on a
        wrong key."""
        from ui import mcpapi
        ok = mcpapi.authorized(self.headers.get("Authorization"))
        if ok is None:
            return 404, '{"error": "not found"}'
        if not ok:
            return 401, '{"error": "wrong or missing Authorization: Bearer <key>"}'
        return True

    def _mcp_get(self, path, qs):
        from ui import mcpapi
        a = self._mcp_auth()
        if a is not True:
            return self._send(a[0], a[1].encode("utf-8"), "application/json")
        try:
            code, out = mcpapi.answer(path, qs)
        except Exception as e:  # noqa: BLE001 - a broken part answers JSON, never a traceback page
            print(f"mcp: {path}: {type(e).__name__}: {e}", flush=True)
            code, out = 500, json.dumps({"error": f"{type(e).__name__}"})
        return self._send(code, out.encode("utf-8"), "application/json")

    def _mcp_post(self):
        from ui import mcpapi
        a = self._mcp_auth()
        if a is not True:
            return self._send(a[0], a[1].encode("utf-8"), "application/json")
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(min(n, 100_000)) or b"{}")
        except ValueError:
            return self._send(400, b'{"error": "body must be JSON"}', "application/json")
        code, data = mcpapi.trade_request(body)
        return self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json")

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
        if code == 503:   # 9.11. (audit P33, review): _last_copy's "try again in a minute" says so to the browser too
            self.send_header("Retry-After", "60")
        self.send_header("Vary", "Accept-Encoding")
        if not getattr(self, "_index", False):
            self.send_header("X-Robots-Tag", "noindex, nofollow")
        if zipped:
            self.send_header("Content-Encoding", "gzip")
        if ctype == "text/html" and not getattr(self, "_public", False):
            self._admin_cookie()
            self._trade_cookie()
        self.end_headers()
        try:
            self.wfile.write(out)
        except (BrokenPipeError, ConnectionResetError):   # 9.11.: the 1-s pollers abort old requests; not an error
            return

    def _admin_cookie(self):
        """cb_adm=1 for admins, so cached pages show the adm-only bits (Sustav menu, spend warnings) only to them."""
        cookies = self.headers.get("Cookie") or ""
        has = "cb_adm=1" in cookies
        r = getattr(self, "role", "osnovni")
        adm = r == "admin"
        if adm and not has:
            self.send_header("Set-Cookie", f"cb_adm=1; Path=/; Max-Age={COOKIE_DAYS * 86400}; SameSite=Lax")
        elif has and not adm:
            self.send_header("Set-Cookie", "cb_adm=; Path=/; Max-Age=0; SameSite=Lax")
        # cb_nm=1: this player has no e-mail yet, every page then shows the "upiši e-mail" box (ui/html.ADMIN_JS)
        user = getattr(self, "user", None)
        nm = False
        if user:
            try:
                from league import profiles
                nm = not (profiles.get(user).get("email") or "").strip()
            except Exception:  # noqa: BLE001
                nm = False
        if nm and "cb_nm=1" not in cookies:
            self.send_header("Set-Cookie", f"cb_nm=1; Path=/; Max-Age={COOKIE_DAYS * 86400}; SameSite=Lax")
        elif not nm and "cb_nm=1" in cookies:
            self.send_header("Set-Cookie", "cb_nm=; Path=/; Max-Age=0; SameSite=Lax")
        # cb_csrf: form token for money/roles/settings POSTs; page JS copies it into a hidden _csrf field
        tok = csrf_token(self._session_value())
        if tok and f"cb_csrf={tok}" not in cookies:
            self.send_header("Set-Cookie", f"cb_csrf={tok}; Path=/; Max-Age={COOKIE_DAYS * 86400}; SameSite=Strict"
                             + _secure_flag(self.headers))
        # cb_r: the role, so cached pages hide the menu items this role cannot open (the server refuses them anyway)
        if f"cb_r={r}" not in cookies:
            self.send_header("Set-Cookie", f"cb_r={r}; Path=/; Max-Age={COOKIE_DAYS * 86400}; SameSite=Lax")

    def _forbidden(self, path, need):
        from league import roles
        body = (f"<h1>🔒 Ovo nije za tvoj račun</h1><div class=card><p>Ova stranica ili radnja traži ulogu "
                f"<b>{esc(roles.LABEL[need])}</b>. Tvoja uloga je <b>{esc(roles.LABEL.get(self.role, self.role))}</b>"
                f"<span class=mut>: {esc(roles.WHAT.get(self.role, ''))}</span></p>"
                "<p>Ako trebaš veći pristup, javi se administratoru.</p>"
                "<p><a href=/tokens>← Na tokene</a></p></div>")
        return self._send(403, page("Nemaš pristup", body, path).encode("utf-8"))

    def _trade_cookie(self):
        """cb_pt=1 for the owner and invited players: the cached menu then shows "Pravi trade" only to them
        (the page itself checks access again)."""
        has = "cb_pt=1" in (self.headers.get("Cookie") or "")
        try:
            from ui import pravitrade
            ok = pravitrade.can_view_cached(getattr(self, "user", None))
        except Exception:  # noqa: BLE001
            return
        if ok and not has:
            self.send_header("Set-Cookie", f"cb_pt=1; Path=/; Max-Age={COOKIE_DAYS * 86400}; SameSite=Lax")
        elif has and not ok:
            self.send_header("Set-Cookie", "cb_pt=; Path=/; Max-Age=0; SameSite=Lax")

    def do_POST(self):
        """/run/<job>: start an on-demand run (button on the page), then back to the page.
        /hook/kol?key=$KOL_HOOK_KEY: webhook for the KOL tracker on X (hype/sources.kol_monitor), its own key."""
        u = urlsplit(self.path)
        self._public = False
        self._set_lang()
        if u.path == "/hook/kol":
            self._kol_hook(u)
            return
        if u.path == "/hook/x":   # 5.11.: twitterapi.io filter-rule webhook (kol/xhook.py), ?key=<KOL_HOOK_KEY>
            self._x_hook(u)
            return
        if u.path == "/hook/chain":
            self._chain_hook(u)
            return
        if u.path == "/api/mcp/trade":   # 10.11.: a trade REQUEST from the MCP server; waits for the owner's tap
            return self._mcp_post()
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
        path = unquote(urlsplit(self.path).path)
        from league import roles
        need = roles.deny_post(path, self.role)
        if need:   # e.g. a basic user posting /run/wallets by hand: refused before anything starts
            print(f"uloge: odbijeno {self.who or '-'} ({self.role}) POST {path}", flush=True)
            return self._forbidden(path, need)
        if path.startswith("/autopilot/"):   # 10.11.: chat of the public Autopilot page (no cached page changes)
            return self._autopilot_post(path)
        pagecache.clear()   # a run or a trade changes what the pages show
        origin = self.headers.get("Origin") or self.headers.get("Referer") or ""
        same_site = not origin or urlsplit(origin).netloc == self.headers.get("Host")
        if path.startswith(CSRF_STRICT) and AUTH:
            # audit 4.11. §4.2/§14.4: an empty Origin is no longer "our site", and the form must carry the token
            same_site = bool(origin) and urlsplit(origin).netloc == self.headers.get("Host")
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(min(n, 600_000))
            self._body = raw
            sent = dict(parse_qsl(raw.decode("utf-8", "replace"))).get("_csrf", "")
            want = csrf_token(self._session_value())
            if not same_site or not want or not hmac.compare_digest(sent, want):
                print(f"csrf: odbijeno {self.who or '-'} POST {path} (origin={'da' if origin else 'prazan'})", flush=True)
                self.send_response(403)
                self.end_headers()
                return
        if same_site and path.startswith("/korisnici/"):
            from ui import userroles
            form = dict(parse_qsl(self._read_body(10_000).decode("utf-8", "replace")))
            return self._redirect(userroles.post(path, form, self.who))
        if same_site and path.startswith("/pravi-trade/"):
            from urllib.parse import parse_qs
            from ui import pravitrade
            multi = parse_qs(self._read_body(100_000).decode("utf-8", "replace"))
            form = {k: v[-1] for k, v in multi.items()}
            form["u_list"] = multi.get("u", [])
            to = pravitrade.post(path, form, self.user)
            if path in ("/pravi-trade/switch", "/pravi-trade/sellall"):
                # 10.11. (pregled): pagecache was cleared above BEFORE the switch was saved, and the public page keeps
                # "live" 30 s: forget both after it, so no page keeps saying "tradamo pravim novcem" once it is off
                try:
                    from ui import apjavno
                    apjavno.reset_cache()
                except Exception:  # noqa: BLE001
                    pass
                pagecache.clear()
            return self._redirect(to)
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
            form = dict(parse_qsl(self._read_body(10_000).decode("utf-8", "replace")))
            return self._redirect(landing.admin_post(path, self.user, form))
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

    def _read_body(self, limit):
        """POST body, once: the CSRF check may already have read it."""
        if getattr(self, "_body", None) is not None:
            return self._body[:limit]
        n = int(self.headers.get("Content-Length") or 0)
        self._body = self.rfile.read(min(n, limit))
        return self._body

    def _session_value(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return v
        return ""

    def _kol_hook(self, u):
        from kol import store as kstore
        key = kstore.hook_key()
        got = self.headers.get("X-Hook-Key") or dict(parse_qsl(u.query)).get("key", "")  # xquik cannot set headers
        if not key or not hmac.compare_digest(got, key):
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

    def _x_hook(self, u):
        from kol import store as kstore, xhook
        key = kstore.hook_key()
        got = self.headers.get("X-Hook-Key") or dict(parse_qsl(u.query)).get("key", "")
        if not key or not hmac.compare_digest(got, key):
            self.send_response(404)
            self.end_headers()
            return
        n = int(self.headers.get("Content-Length") or 0)
        try:
            import json
            xhook.ingest(json.loads(self.rfile.read(min(n, 2_000_000)) or b"{}"))
            self.send_response(200)
        except Exception as e:  # noqa: BLE001
            print(f"xhook: {type(e).__name__}: {e}", flush=True)
            self.send_response(400)
        self.end_headers()

    def _chain_hook(self, u):
        """/hook/chain (Authorization: <chain key>): Helius enhanced webhook with swaps of the KOL wallets (kol/chainwatch.py)."""
        from kol import chainwatch, store as kstore
        key = kstore.chain_key()
        got = self.headers.get("Authorization") or ""     # Helius authHeader; ?key= in the URL is ignored (4.11.)
        if not key or not hmac.compare_digest(got, key):
            self.send_response(401)
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
        secure = _secure_flag(self.headers)
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
        secure = _secure_flag(self.headers)
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
        form = dict(parse_qsl(self._read_body(600_000).decode("utf-8", "replace")))
        kind = user_kind(self.user)
        loc, extra = settings.post(path, form, self.user, kind, lambda u, pw: check_password(u, pw)[1] == u)
        msg = loc.split("err=", 1)[1].split("#")[0] if "err=" in loc else "ok"
        print(f"postavke: {self.user} {path[len('/postavke/'):]} -> {unquote(msg)[:120]}", flush=True)
        pagecache.clear()
        secure = _secure_flag(self.headers)
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
            return self._send(400, register.page_html({"k": form.get("k", ""), "name": form.get("name", ""),
                                                          "email": form.get("email", "")}, err)
                              .encode("utf-8"))
        pagecache.clear()
        secure = _secure_flag(self.headers)
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

    def _autopilot(self, path, qs, ok):
        """10.11. (Jure): /autopilot is readable without a login on every host. A visitor gets it in a light public
        frame (Croatian, /en/autopilot through ui/i18n); a logged-in player gets it inside the app, where the chat
        form and +1 work. /autopilot/chat is the message list alone, re-fetched by the page every 15 s."""
        from ui import apjavno
        if ok and path == apjavno.PATH_EN:   # inside the app the language is the player's own setting
            return self._redirect(apjavno.PATH)
        if not ok and qs.get("prijava") == "1":   # "Prijavi se" on the public copy: only a visitor needs the form
            return self._redirect("/prijava?next=" + apjavno.PATH)
        user = self.user if ok else None
        lang = self.lang if ok else ("en" if path == apjavno.PATH_EN or qs.get("l") == "en" else "hr")
        self._public = not ok   # a visitor gets no app cookies; a player's copy carries the form token cookie
        # 10.11. (Jure: "da", u Google): the visitor's copy of the page is indexable; the chat fragment and the in-app copy are not
        self._index = not ok and path in (apjavno.PATH, apjavno.PATH_EN)
        try:
            if path == apjavno.CHAT_PATH:
                html = apjavno.chat_fragment(user, qs)
            elif ok:
                html = page(*apjavno.page(qs, user, lang, logged_in=True), path)
            else:
                html = apjavno.guest_html(qs, lang)
        except Exception:
            err = _error_html()   # the traceback goes to the server log, never to the page
            html = page("Greška", err, path) if ok else f"<!doctype html><meta charset=utf-8><title>Greška</title>{err}"
            return self._send(500, html.encode("utf-8"))
        i18n.LANG.set(lang)
        return self._send(200, i18n.translate(html).encode("utf-8"), translated=True)

    def _autopilot_post(self, path):
        """Chat of /autopilot (message, +1, hide a message): logged-in players only, with a same-site Origin and the
        form token, as strict as the money forms (CSRF_STRICT). It sits before pagecache.clear() because a chat line
        changes no cached page. ajax=1 (the page script): the answer is the refreshed message list, not a redirect."""
        from ui import apjavno
        form = dict(parse_qsl(self._read_body(20_000).decode("utf-8", "replace")))
        origin = self.headers.get("Origin") or self.headers.get("Referer") or ""
        same_site = urlsplit(origin).netloc == self.headers.get("Host") if origin else not AUTH
        want = csrf_token(self._session_value())
        token_ok = not AUTH or bool(want) and hmac.compare_digest(form.get("_csrf", "").encode(), want.encode())
        if not same_site or not token_ok:
            print(f"csrf: odbijeno {self.who or '-'} POST {path} (origin={'da' if origin else 'prazan'})", flush=True)
            self.send_response(403)
            self.end_headers()
            return
        if form.get("ajax") != "1":
            return self._redirect(apjavno.post(path, form, self.user))
        ok, code = apjavno.act(path, form, self.user)
        frag = apjavno.chat_fragment(self.user, {}, err="" if ok else code)
        return self._send(200, i18n.translate(frag).encode("utf-8"), translated=True)

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
        self.user = self.who = None
        self.role = "osnovni"
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                ok, player = cookie_user(v)
                if ok:
                    self.user = player
                    self.who = player or _cookie_name(v)
                    self.role = role_of(self.who)
                    return True
        h = self.headers.get("Authorization", "")   # old browser password box still works
        if not h.startswith("Basic "):
            return False
        try:
            name, _, pw = base64.b64decode(h[6:]).decode().partition(":")
        except Exception:
            return False
        ok, self.user = check_password(name, pw)
        if ok:
            self.who = self.user or (VIEWER if VIEWER_PASS and name.strip().lower() == VIEWER.lower() else None)
            self.role = role_of(self.who)
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
    try:   # 10.11. (Jure): errors go to Sentry (ops/sentry.py); a no-op without SENTRY_DSN, never stops the start
        from ops import sentry
        sentry.init("ui")
    except Exception as e:  # noqa: BLE001
        print(f"sentry: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8050)
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--render", metavar="PATH", help="ispiši jednu stranicu na stdout i izađi (za build_in_child)")
    a = p.parse_args(argv)
    if a.render:
        code, raw = build(a.render, {})
        if code != 200:
            sys.exit(1)
        sys.stdout.buffer.write(raw)
        sys.stdout.flush()
        return
    if a.host not in ("127.0.0.1", "localhost", "::1") and not AUTH:
        sys.exit("Slušaš na javnoj adresi bez lozinke. Postavi UI_PASSWORD=... ili koristi SSH tunel (vidi --help).")
    srv = _bind(a.host, a.port)
    srv.verbose = a.verbose
    if os.environ.get("LEAGUE_AUTO_SELL", "1") == "1":  # competition auto sell; this process is league.db's only writer
        import threading
        from league import auto
        from ui.paper import market
        threading.Thread(target=auto.loop, args=(market,), daemon=True, name="auto-sell").start()
        # 10.11. (Jure: TP +40 % dotaknut, a prodaja se nije dogodila): the Autopilot's TP/SL every second, apart
        # from the 20-s pass over every player's positions
        threading.Thread(target=auto.fast_loop, args=(market,), daemon=True, name="autopilot-izlazi").start()
        # 10.11. (Jure: MC u trenutku poziva i pomak u 5/10/15 min bez čekanja na svijeće): live samples of the skips
        from ui import pravitrade as _pt
        threading.Thread(target=_pt.skip_sampler_loop, daemon=True, name="preskoceni-uzivo").start()
        # 10.11. (Jure: "DCA ide ručno, granice postavljam ručno"): the owner's dokup orders, watched every second
        threading.Thread(target=_pt.dca_loop, daemon=True, name="dca-nalozi").start()
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
    pagecache.warm(list(WARM), warm_build, every_s=int(os.environ.get("UI_WARM_EVERY_S", "300")),
                   skip_fresh_s=WARM_SKIP_FRESH_S)   # 9.11. (audit): the skip lives in warm(), so a kept page keeps its age
    pagecache.snapshot(SNAPSHOT_ONLY)   # 9.11.: /ekipe and /kol keep their last good build on disk (served while rebuilt)
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
