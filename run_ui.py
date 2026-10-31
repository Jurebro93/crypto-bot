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
import sys
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, unquote, urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui import criteria, evidence, jobs, kol, market, overview, pages, paper, radar, tokens, usage, watch  # noqa: E402
from ui.html import SHOW_ALL, esc, page  # noqa: E402
from ui import pagecache  # noqa: E402
from ui import league, real  # noqa: E402
from league import store as league_store  # noqa: E402

PASSWORD = os.environ.get("UI_PASSWORD", "")
PLAYERS = {u.lower(): (u, os.environ.get(f"UI_PASS_{u.upper()}", "")) for u in league_store.users()}
# view-only test account for Claude's checks of the live dashboard (no player, no trading, not in Natjecanje)
VIEWER, VIEWER_PASS = os.environ.get("UI_TEST_USER", "Claude"), os.environ.get("UI_TEST_PASSWORD", "")
AUTH = bool(PASSWORD or VIEWER_PASS or any(pw for _, pw in PLAYERS.values()))
# login cookie: signed with a key derived from every password, so changing a password logs everybody out
_SECRET = hashlib.sha256(("crypto-bot-session|" + PASSWORD + "|" + VIEWER_PASS + "|" + "|".join(pw for _, pw in PLAYERS.values()))
                         .encode()).digest()
COOKIE, COOKIE_DAYS = "cb_s", 60


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
    player, ppw = PLAYERS.get(name.lower(), (None, ""))
    return (True, player) if player and ppw else (False, None)


def check_password(name, pw):
    """(ok, player or None): a player's own name + password, or the shared UI_PASSWORD with any name."""
    player, ppw = PLAYERS.get((name or "").strip().lower(), (None, ""))
    if player and ppw and hmac.compare_digest(pw.encode(), ppw.encode()):
        return True, player
    if VIEWER_PASS and (name or "").strip().lower() == VIEWER.lower():
        return hmac.compare_digest(pw.encode(), VIEWER_PASS.encode()), None
    return bool(PASSWORD) and hmac.compare_digest(pw.encode(), PASSWORD.encode()), None


def _safe_next(n):
    return n if n.startswith("/") and not n.startswith("//") and "\\" not in n else "/"


def login_page(qs, err=""):
    from ui.html import esc as e
    users = ", ".join(league_store.users())
    nxt = e(_safe_next(qs.get("next", "/")))
    who = e(qs.get("kao", ""))
    body = ("<h1>Prijava</h1><form method=post action=/prijava class=card style='max-width:360px'>"
            f"<input type=hidden name=next value=\"{nxt}\">"
            f"<p><label>Ime<br><input name=name autocomplete=username value=\"{who}\" style='width:100%' "
            "autocapitalize=none></label></p>"
            "<p><label>Lozinka<br><input name=pw type=password autocomplete=current-password required "
            "style='width:100%'></label></p>"
            + (f"<p class=neg>{e(err)}</p>" if err else "")
            + "<p><button type=submit>Prijavi se</button></p></form>"
            f"<p class=mut>Igrači ({e(users)}) upisuju svoje ime i svoju lozinku. Samo za gledanje: bilo koje ime i "
            "zajednička lozinka. Prijava se pamti 60 dana na ovom uređaju.</p>")
    miss = league_store.missing_passwords()
    if miss:
        body += (f"<p class=neg>Lozinke još nisu postavljene za: {e(', '.join(miss))}. Postavljaju se u postavkama "
                 "servera na Renderu.</p>")
    return page("Prijava", body, "/prijava")


def route(path, qs):
    if path == "/":
        return overview.page(qs)
    if path == "/radar":
        return radar.page(qs)
    if path == "/kol":
        return kol.page(qs)
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
    if path == "/outputs":
        return pages.outputs(qs)
    if path.startswith("/outputs/"):
        return pages.output(path[len("/outputs/"):], qs)
    return None


def build(path, qs):
    """(code, html bytes) of a route() page with the banner; used through ui/pagecache."""
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
    return code, html.encode("utf-8")


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

    def do_GET(self):
        ok = not AUTH or self._authorized()
        u = urlsplit(self.path)
        path, qs = unquote(u.path), dict(parse_qsl(u.query))
        if path == "/prijava":
            return self._login(qs)
        if path == "/odjava":
            return self._redirect("/prijava", cookie=f"{COOKIE}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax")
        if not ok:
            # a login form instead of the browser's own password box: phones and in-app browsers often never show
            # that box, the page then just stays blank. 401 without WWW-Authenticate, so no box pops up.
            nxt = path + (f"?{u.query}" if u.query else "")
            return self._send(401, login_page({"next": nxt}).encode("utf-8"))
        if path in ("/natjecanje", "/prijedlozi", "/moji-tradeovi"):
            SHOW_ALL.set(qs.get("sve") == "1")
            fn = {"/natjecanje": league.page, "/prijedlozi": league.ideas_page, "/moji-tradeovi": real.page}[path]
            try:
                html = page(*fn(qs, self.user), path)
            except Exception:
                html = page("Greška", f"<h1>Greška</h1><pre>{esc(traceback.format_exc())}</pre>", path)
            return self._send(200, html.encode("utf-8"))
        if path.startswith("/izvjestaj/raw/"):
            from ui import reportpage
            body = reportpage.raw(path[len("/izvjestaj/raw/"):])
            return self._send(200 if body else 404, body or b"nema izvjestaja")
        if path == "/api/paper":
            return self._send(200, paper.api(qs).encode("utf-8"), "application/json")
        if path.startswith("/api/evidence/"):
            try:
                frag = evidence.fragment(path[len("/api/evidence/"):])
            except Exception:
                frag = f"<pre>{esc(traceback.format_exc())}</pre>"
            return self._send(200, frag.encode("utf-8"))
        key = (path, u.query, None)    # route() pages are the same for every user
        code, raw, gz = pagecache.get(key, lambda: build(path, qs))
        self._send(code, raw, gz=gz)

    def _send(self, code, body, ctype="text/html", gz=None):
        """gzip when the browser takes it: tables shrink ~10x, which is most of a phone's wait."""
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
        if zipped:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        self.wfile.write(out)

    def do_POST(self):
        """/run/<job>: start an on-demand run (button on the page), then back to the page.
        /hook/kol?key=$KOL_HOOK_KEY: webhook for the KOL tracker on X (hype/sources.kol_monitor), its own key."""
        u = urlsplit(self.path)
        if u.path == "/hook/kol":
            self._kol_hook(u)
            return
        if u.path == "/hook/chain":
            self._chain_hook(u)
            return
        if u.path == "/prijava":
            return self._login_post()
        if AUTH and not self._authorized():
            return self._send(401, login_page({}).encode("utf-8"))
        pagecache.clear()   # a run or a trade changes what the pages show
        path = unquote(urlsplit(self.path).path)
        origin = self.headers.get("Origin") or self.headers.get("Referer") or ""
        same_site = not origin or urlsplit(origin).netloc == self.headers.get("Host")
        if same_site and path.startswith(("/natjecanje/", "/prijedlozi/", "/moji-tradeovi/")):
            n = int(self.headers.get("Content-Length") or 0)
            form = dict(parse_qsl(self.rfile.read(min(n, 100_000)).decode("utf-8", "replace")))
            self.send_response(303)
            handler = real.post if path.startswith("/moji-tradeovi/") else league.post
            self.send_header("Location", handler(path, form, self.user))
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
            chainwatch.ingest(json.loads(self.rfile.read(min(n, 5_000_000)) or b"[]"),
                              os.path.join(os.path.dirname(os.path.abspath(__file__)), "hype.db"))
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
        return self._redirect(_safe_next(form.get("next", "/")), cookie=cookie)

    def _redirect(self, location, cookie=None):
        self.send_response(303)
        self.send_header("Location", location)
        if cookie:
            self.send_header("Set-Cookie", cookie)
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


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8050)
    p.add_argument("--verbose", action="store_true")
    a = p.parse_args(argv)
    if a.host not in ("127.0.0.1", "localhost", "::1") and not AUTH:
        sys.exit("Slušaš na javnoj adresi bez lozinke. Postavi UI_PASSWORD=... ili koristi SSH tunel (vidi --help).")
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    srv.verbose = a.verbose
    if os.environ.get("LEAGUE_AUTO_SELL", "1") == "1":  # competition auto sell; this process is league.db's only writer
        import threading
        from league import auto
        from ui.paper import market
        threading.Thread(target=auto.loop, args=(market,), daemon=True, name="auto-sell").start()
    # heaviest pages rendered in the background right away and every 5 min, so a visit never waits for them
    pagecache.warm(["/", "/tokens"], lambda p: build(p, {}), every_s=int(os.environ.get("UI_WARM_EVERY_S", "300")))
    print(f"crypto-bot UI sluša na {a.host}:{a.port}" + ("  (sve adrese, lozinka uključena)" if a.host == "0.0.0.0" else "")
          + "  (Ctrl+C za kraj)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
