"""Local web dashboard: wallets, tokens, events and the selection criteria, read-only from calendar.db, hype.db, wallets.db, rug.db, paper.db.

    python3 run_ui.py                         # http://127.0.0.1:8050 (only this computer)
    python3 run_ui.py --port 9000
    UI_PASSWORD=tajna python3 run_ui.py --host 0.0.0.0   # on a VPS: password required (user: any)

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

from ui import criteria, evidence, jobs, overview, pages, paper, radar  # noqa: E402
from ui.html import esc, page  # noqa: E402

PASSWORD = os.environ.get("UI_PASSWORD", "")


def route(path, qs):
    if path == "/":
        return overview.page(qs)
    if path == "/radar":
        return radar.page(qs)
    if path == "/wallets":
        return pages.wallets(qs)
    if path.startswith("/wallet/"):
        return pages.wallet(path[len("/wallet/"):], qs)
    if path == "/tokens":
        return pages.tokens(qs)
    if path.startswith("/token/"):
        return pages.token(path[len("/token/"):], qs)
    if path == "/events":
        return pages.events(qs)
    if path == "/paper":
        return paper.page(qs)
    if path == "/criteria":
        return criteria.page(qs)
    if path == "/outputs":
        return pages.outputs(qs)
    if path.startswith("/outputs/"):
        return pages.output(path[len("/outputs/"):], qs)
    return None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if PASSWORD and not self._authorized():
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="crypto-bot"')
            self.end_headers()
            return
        u = urlsplit(self.path)
        path, qs = unquote(u.path), dict(parse_qsl(u.query))
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
                code, html = 200, page(res[0], res[1], path)
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
        if PASSWORD and not self._authorized():
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="crypto-bot"')
            self.end_headers()
            return
        path = unquote(urlsplit(self.path).path)
        origin = self.headers.get("Origin") or self.headers.get("Referer") or ""
        same_site = not origin or urlsplit(origin).netloc == self.headers.get("Host")
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
        key = os.environ.get("KOL_HOOK_KEY", "")
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

    def _authorized(self):
        h = self.headers.get("Authorization", "")
        if not h.startswith("Basic "):
            return False
        try:
            _, _, pw = base64.b64decode(h[6:]).decode().partition(":")
        except Exception:
            return False
        return hmac.compare_digest(pw, PASSWORD)

    def log_message(self, fmt, *args):
        if self.server.verbose:
            super().log_message(fmt, *args)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8050)
    p.add_argument("--verbose", action="store_true")
    a = p.parse_args(argv)
    if a.host not in ("127.0.0.1", "localhost", "::1") and not PASSWORD:
        sys.exit("Slušaš na javnoj adresi bez lozinke. Postavi UI_PASSWORD=... ili koristi SSH tunel (vidi --help).")
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    srv.verbose = a.verbose
    print(f"crypto-bot UI: http://{'127.0.0.1' if a.host == '0.0.0.0' else a.host}:{a.port}  (Ctrl+C za kraj)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
