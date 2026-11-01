"""Stand-in web server for the first seconds after a deploy: answers on $PORT with the funny "deploy in progress"
page (ui/deploypage.py, status 503 + Retry-After) while start.sh prepares the databases and run_ui.py loads.

Render routes traffic as soon as something listens on the port, so visitors see our page instead of Render's black
502. run_ui.py touches DEPLOY_WAIT_FLAG right before it binds the port; this server then lets go of the port within
~0.1 s and exits (run_ui retries the bind for a few seconds). It also exits by itself after DEPLOY_WAIT_MAX_S
(default 240 s), so a run_ui that never starts shows Render's own error instead of a promise that never comes true.

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

    def _out(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.send_header("X-MemeSonar-Deploy", "1")
        if code == 503:
            self.send_header("Retry-After", "15")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/sw.js":   # a browser updating its worker mid-deploy gets the same one back
            return self._out(200, self.sw, "text/javascript")
        if path == "/healthz":
            return self._out(503, b"starting", "text/plain")
        return self._out(503, self.body, "text/html")

    do_HEAD = do_GET

    def do_POST(self):   # a form sent mid-deploy: same page, the browser can resend after reload
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
