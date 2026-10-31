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
import hmac
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, unquote, urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui import criteria, evidence, jobs, kol, market, overview, pages, paper, radar, tokens, usage, watch  # noqa: E402
from ui.html import esc, page  # noqa: E402
from ui import league, real  # noqa: E402
from league import store as league_store  # noqa: E402

PASSWORD = os.environ.get("UI_PASSWORD", "")
PLAYERS = {u.lower(): (u, os.environ.get(f"UI_PASS_{u.upper()}", "")) for u in league_store.users()}
AUTH = bool(PASSWORD or any(pw for _, pw in PLAYERS.values()))


def route(path, qs):
    if path == "/":
        return overview.page(qs)
    if path == "/radar":
        return radar.page(qs)
    if path == "/kol":
        return kol.page(qs)
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
    if path == "/learn":
        from ui import learnpage
        return learnpage.page(qs)
    if path == "/outputs":
        return pages.outputs(qs)
    if path.startswith("/outputs/"):
        return pages.output(path[len("/outputs/"):], qs)
    return None


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
        if not ok:
            return self._challenge()
        if path in ("/natjecanje", "/prijedlozi", "/moji-tradeovi"):
            fn = {"/natjecanje": league.page, "/prijedlozi": league.ideas_page, "/moji-tradeovi": real.page}[path]
            try:
                html = page(*fn(qs, self.user), path)
            except Exception:
                html = page("Greška", f"<h1>Greška</h1><pre>{esc(traceback.format_exc())}</pre>", path)
            return self._send(200, html.encode("utf-8"))
        if path == "/api/paper":
            return self._send(200, paper.api(qs).encode("utf-8"), "application/json")
        if path.startswith("/api/evidence/"):
            try:
                frag = evidence.fragment(path[len("/api/evidence/"):])
            except Exception:
                frag = f"<pre>{esc(traceback.format_exc())}</pre>"
            return self._send(200, frag.encode("utf-8"))
        try:
            res = route(path, qs)
            if res is None:
                code, html = 404, page("404", "<h1>Nema te stranice</h1><p><a href=/>Na pregled</a></p>", path)
            else:
                code, html = 200, page(res[0], _banner(path) + res[1], path)
        except Exception:
            code = 500
            html = page("Greška", f"<h1>Greška</h1><pre>{esc(traceback.format_exc())}</pre>", path)
        self._send(code, html.encode("utf-8"))

    def _send(self, code, body, ctype="text/html"):
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        """/run/<job>: start an on-demand run (button on the page), then back to the page.
        /hook/kol?key=$KOL_HOOK_KEY: webhook for the KOL tracker on X (hype/sources.kol_monitor), its own key."""
        u = urlsplit(self.path)
        if u.path == "/hook/kol":
            self._kol_hook(u)
            return
        if AUTH and not self._authorized():
            return self._challenge()
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

    def _challenge(self, body=b""):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="crypto-bot"')
        if body:
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _login(self, qs):
        """/prijava: the browser only shows its name + password box after a 401, and otherwise keeps sending the
        shared password it remembered. Answer 401 until a player logs in (?kao=<name> also switches away from them)."""
        if self.user and self.user != qs.get("kao"):
            self.send_response(303)
            self.send_header("Location", "/natjecanje")
            self.end_headers()
            return
        return self._challenge(page("Prijava", league.login_help(), "/prijava").encode("utf-8"))

    def _authorized(self):
        """A player's own name + password sets self.user; the shared UI_PASSWORD (any name) lets in without one."""
        self.user = None
        h = self.headers.get("Authorization", "")
        if not h.startswith("Basic "):
            return False
        try:
            name, _, pw = base64.b64decode(h[6:]).decode().partition(":")
        except Exception:
            return False
        player, ppw = PLAYERS.get(name.strip().lower(), (None, ""))
        if player and ppw and hmac.compare_digest(pw.encode(), ppw.encode()):
            self.user = player
            return True
        return bool(PASSWORD) and hmac.compare_digest(pw.encode(), PASSWORD.encode())

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
    print(f"crypto-bot UI sluša na {a.host}:{a.port}" + ("  (sve adrese, lozinka uključena)" if a.host == "0.0.0.0" else "")
          + "  (Ctrl+C za kraj)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
