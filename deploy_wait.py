"""Stand-in web server for the first seconds after a deploy: answers on $PORT with the funny "deploy in progress"
page (ui/deploypage.py, status 503 + Retry-After) while start.sh prepares the databases and run_ui.py loads.

Render routes traffic as soon as something listens on the port, so visitors see our page instead of Render's black
502. run_ui.py touches DEPLOY_WAIT_FLAG right before it binds the port; this server then lets go of the port within
~0.1 s and exits (run_ui retries the bind for a few seconds). It also exits by itself after DEPLOY_WAIT_MAX_S
(default 240 s), so a run_ui that never starts shows Render's own error instead of a promise that never comes true.
10.11. (Grok MCP audit 11): the MCP endpoint (/mcp, /api/mcp/*) gets a JSON 503 with Retry-After 30 instead of the page.

    python3 deploy_wait.py --port 10000
"""
import argparse
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FLAG = os.environ.get("DEPLOY_WAIT_FLAG", "/tmp/memesonar-ui-starting")


class Wait(BaseHTTPRequestHandler):
    body = b""
    sw = b""
    timeout = 10   # a client that announces a body and never sends it does not hold a thread for ever

    def _out(self, code, body, ctype, retry="15"):
        self.send_response(code)
        # application/json has no charset parameter (RFC 8259: always UTF-8); the page types keep theirs
        self.send_header("Content-Type", ctype if ctype == "application/json" else f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.send_header("X-MemeSonar-Deploy", "1")
        if code == 503:
            self.send_header("Retry-After", retry)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _read_body(self, cap):
        """Up to `cap` bytes of the request body. Read even when unused: closing a socket with unread data resets the
        connection, and the client may then lose this answer."""
        try:
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(min(n, cap)) if n > 0 else b""
        except (ValueError, OSError):
            return b""

    def _api(self, body=b""):
        """10.11. (Grok MCP audit 11): the MCP endpoint (/mcp, /api/mcp/*) gets a JSON 503 with Retry-After 30
        (ui/deploypage.api_answer), never the HTML page. False for every other address."""
        from ui import deploypage
        got = deploypage.api_answer(self.path, body)
        if got is None:
            return False
        code, headers, out = got
        self._out(code, out, headers["Content-Type"], retry=headers["Retry-After"])
        return True

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/sw.js":   # a browser updating its worker mid-deploy gets the same one back
            return self._out(200, self.sw, "text/javascript")
        if path == "/healthz":
            return self._out(503, b"starting", "text/plain")
        if self._api():
            return None
        return self._out(503, self.body, "text/html")

    do_HEAD = do_GET

    def do_POST(self):   # a form sent mid-deploy: same page, the browser can resend after reload
        from ui import deploypage
        body = self._read_body(deploypage.API_BODY_MAX)
        if self._api(body):   # 10.11. (Grok MCP audit 11): JSON-RPC error with the request's id
            return None
        return self._out(503, self.body, "text/html")

    def log_message(self, *a):
        pass


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT") or 8050))
    a = p.parse_args(argv)
    try:
        os.remove(FLAG)
    except OSError:
        pass
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from ui import deploypage
    Wait.body = deploypage.html().encode("utf-8")
    Wait.sw = deploypage.sw_js().encode("utf-8")
    ThreadingHTTPServer.allow_reuse_address = True
    try:
        srv = ThreadingHTTPServer((a.host, a.port), Wait)
    except OSError as e:
        print(f"deploy stranica: port {a.port} zauzet ({e}), preskačem", flush=True)
        return
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    print(f"deploy stranica: čeka na portu {a.port} dok se aplikacija ne upali", flush=True)
    t0, limit = time.time(), float(os.environ.get("DEPLOY_WAIT_MAX_S", "240"))
    while not os.path.exists(FLAG) and time.time() - t0 < limit:
        time.sleep(0.05)
    srv.shutdown()
    srv.server_close()
    print(f"deploy stranica: predajem port aplikaciji nakon {time.time() - t0:.0f} s", flush=True)


if __name__ == "__main__":
    main()
