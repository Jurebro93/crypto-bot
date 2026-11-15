"""15.11. (vlasnik: "slike se ne učitavaju"): token icons from our own address, images during a deploy, the service
worker, the hero slider's preload and the deploy page's language. No network: every outside fetch is mocked.

Found in Chromium on the live site: ipfs.io and gateway.pinata.cloud block an embedded image (403 + CORP same-origin,
net::ERR_BLOCKED_BY_RESPONSE), so ~40 % of the coin icons were hidden; deploy_wait.py answered images with the 503
page; the slider loaded a screen only when its turn came; the deploy page was Croatian for everybody.
"""
import http.client
import http.server
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import deploy_wait  # noqa: E402
from ui import deploypage, landing, tokenicons  # noqa: E402

MINT = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
MINT2 = "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"


def png(w=300, h=200, color=(200, 30, 30)):
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (w, h), color).save(out, "PNG")
    return out.getvalue()


def serve(handler):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    return srv


def ask(srv, method, path, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
    try:
        c.request(method, path, headers=headers or {})
        r = c.getresponse()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
    finally:
        c.close()


class IconsBase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        p = mock.patch.dict(os.environ, {"ICON_CACHE_DIR": self.dir})
        p.start()
        self.addCleanup(p.stop)
        self.calls = []


class Sources(IconsBase):
    def test_ipfs_links_go_to_working_gateways_first(self):
        c = tokenicons.ipfs_candidates("https://ipfs.io/ipfs/QmWT4jA2ipuevUfBi1a2LW2gfnPJyvHn1JayAe2qz5kRQJ")
        self.assertTrue(c[0].startswith("https://ipfs.filebase.io/ipfs/Qm"))          # not ipfs.io (429 / CORP block)
        self.assertIn("https://ipfs.io/ipfs/QmWT4jA2ipuevUfBi1a2LW2gfnPJyvHn1JayAe2qz5kRQJ", c)   # still tried, later
        self.assertFalse(any("cloudflare-ipfs" in x for x in c))                       # closed gateway, not on the list
        own = "https://desperate-moccasin-minnow.myfilebase.com/ipfs/QmWZ/a.png"
        self.assertEqual(tokenicons.ipfs_candidates(own)[0], own)                      # a dedicated gateway: as it is first
        self.assertEqual(tokenicons.ipfs_candidates(own)[1], "https://ipfs.filebase.io/ipfs/QmWZ/a.png")
        self.assertEqual(tokenicons.ipfs_candidates("ipfs://bafyabc")[0], "https://ipfs.filebase.io/ipfs/bafyabc")
        sub = tokenicons.ipfs_candidates("https://bafybeidyqirtv6uan5sqjc327tnuememrtzmjxc3bwhljivdrrr7sovhx4.ipfs.4everland.io/")
        self.assertIn("https://ipfs.filebase.io/ipfs/bafybeidyqirtv6uan5sqjc327tnuememrtzmjxc3bwhljivdrrr7sovhx4", sub)
        self.assertEqual(tokenicons.ipfs_candidates("https://static.datapi.jup.ag/token-icons/abc"),
                         ["https://static.datapi.jup.ag/token-icons/abc"])

    def test_only_public_https_is_fetched(self):
        with mock.patch.object(tokenicons, "_proxied", return_value=False), \
                mock.patch.object(tokenicons.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]):
            self.assertTrue(tokenicons._safe("https://img.example/x.png"))
            self.assertFalse(tokenicons._safe("http://img.example/x.png"))
            self.assertFalse(tokenicons._safe("https://img.example:8443/x.png"))
            self.assertFalse(tokenicons._safe("https://user:pw@img.example/x.png"))
            self.assertFalse(tokenicons._safe("file:///etc/passwd"))
        for bad in ("https://127.0.0.1/x", "https://10.1.2.3/x", "https://169.254.169.254/latest", "https://[::1]/x",
                    "https://localhost/x", "https://db.internal/x"):
            self.assertFalse(tokenicons._safe(bad), bad)
        with mock.patch.object(tokenicons, "_proxied", return_value=False), \
                mock.patch.object(tokenicons.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.5", 443))]):
            self.assertFalse(tokenicons._safe("https://looks-public.example/x.png"))   # a name that points inside
        with mock.patch.object(tokenicons, "_proxied", return_value=False), \
                mock.patch.object(tokenicons.socket, "getaddrinfo", side_effect=OSError("no such host")):
            self.assertFalse(tokenicons._safe("https://nowhere.example/x.png"))

    def test_shrinks_to_a_small_square_webp(self):
        out = tokenicons.to_webp(png(2000, 1200))
        from PIL import Image
        im = Image.open(io.BytesIO(out))
        self.assertEqual((im.format, im.size), ("WEBP", (tokenicons.PX, tokenicons.PX)))
        self.assertLess(len(out), 20_000)
        self.assertIsNone(tokenicons.to_webp(b"<svg xmlns='http://www.w3.org/2000/svg'/>"))   # not a raster: next source
        self.assertIsNone(tokenicons.to_webp(b"<html>429 Too Many Requests</html>"))


class Endpoint(IconsBase):
    def fake_get(self, ok):
        def get(u, **kw):
            self.calls.append(u)
            if "lite-api.jup.ag" in u:
                return json.dumps([{"id": MINT, "icon": "https://ipfs.io/ipfs/QmJup", "symbol": "BONK"}]).encode()
            if "dexscreener" in u:
                return b"[]"
            return ok(u)
        return get

    def test_falls_back_through_gateways_and_caches_a_week(self):
        def ok(u):   # ipfs.io-style failures everywhere except one gateway; the first gateway sends an HTML page
            if u.startswith("https://ipfs.filebase.io/"):
                return b"<html>blocked</html>"
            return png() if u.startswith("https://dweb.link/") else None
        with mock.patch.object(tokenicons, "known", return_value=("https://ipfs.io/ipfs/QmKnown", "BONK")), \
                mock.patch.object(tokenicons, "_get", side_effect=self.fake_get(ok)):
            code, h, body = tokenicons.get(MINT)
        self.assertEqual((code, h["Content-Type"]), (200, "image/webp"))
        self.assertIn("max-age=604800", h["Cache-Control"])
        self.assertTrue(h["Cache-Control"].startswith("public"))
        self.assertEqual(self.calls[:3], ["https://ipfs.filebase.io/ipfs/QmKnown",
                                          "https://quicknode.quicknode-ipfs.com/ipfs/QmKnown", "https://dweb.link/ipfs/QmKnown"])
        self.assertFalse(any("lite-api" in c for c in self.calls))       # the known link worked: no search needed
        self.assertTrue(os.path.isfile(os.path.join(self.dir, f"{MINT}.webp")))
        with mock.patch.object(tokenicons, "_get", side_effect=AssertionError("must not fetch again")):
            self.assertEqual(tokenicons.get(MINT)[2], body)               # from the disk
            self.assertEqual(tokenicons.cached(MINT)[2], body)

    def test_search_by_mint_when_we_hold_no_link(self):
        with mock.patch.object(tokenicons, "known", return_value=("", "")), \
                mock.patch.object(tokenicons, "_get", side_effect=self.fake_get(lambda u: png() if "QmJup" in u else None)):
            code, h, _ = tokenicons.get(MINT)
        self.assertEqual(h["Content-Type"], "image/webp")
        self.assertTrue(any("lite-api.jup.ag" in c and MINT in c for c in self.calls))

    def test_nothing_works_gives_initials_never_a_hole(self):
        with mock.patch.object(tokenicons, "known", return_value=("https://ipfs.io/ipfs/QmDead", "bonk")), \
                mock.patch.object(tokenicons, "_get", side_effect=self.fake_get(lambda u: None)):
            code, h, body = tokenicons.get(MINT, now=1000)
        self.assertEqual((code, h["Content-Type"]), (200, "image/svg+xml"))
        self.assertEqual(h["Cache-Control"], tokenicons.CACHE_PLACEHOLDER)   # short: the real icon may come later
        svg = body.decode()
        self.assertIn("<circle", svg)
        self.assertIn(">BO</text>", svg)
        self.assertIn(re.search(r'fill="(#[0-9a-f]{6})"', svg).group(1), tokenicons.COLORS)
        self.assertNotIn("<script", svg)
        # the miss is remembered: no fetch for MISS_RETRY_S, then one more try
        with mock.patch.object(tokenicons, "_get", side_effect=AssertionError("must not fetch")):
            self.assertIn(b">BO<", tokenicons.get(MINT, now=1000 + 60)[2])
        n = len(self.calls)
        with mock.patch.object(tokenicons, "known", return_value=("", "")), \
                mock.patch.object(tokenicons, "_get", side_effect=self.fake_get(lambda u: png() if "QmJup" in u else None)):
            self.assertEqual(tokenicons.get(MINT, now=1000 + tokenicons.MISS_RETRY_S + 1)[1]["Content-Type"], "image/webp")
        self.assertGreater(len(self.calls), n)
        self.assertFalse(os.path.exists(os.path.join(self.dir, f"{MINT}.miss")))

    def test_bad_mint_is_404_and_cached_never_fetches(self):
        self.assertEqual(tokenicons.get("../../etc/passwd")[0], 404)
        self.assertEqual(tokenicons.cached("0OIl" * 10)[0], 404)
        with mock.patch.object(tokenicons, "_get", side_effect=AssertionError("deploy_wait must not fetch")):
            code, h, body = tokenicons.cached(MINT2)
        self.assertEqual((code, h["Content-Type"]), (200, "image/svg+xml"))

    def test_cache_has_a_size_cap(self):
        for i in range(10):
            p = os.path.join(self.dir, f"{i}.webp")
            with open(p, "wb") as f:
                f.write(b"x" * 1000)
            os.utime(p, (1000 + i, 1000 + i))
        kept = tokenicons.trim(max_bytes=5000)
        left = sorted(os.listdir(self.dir))
        self.assertLessEqual(kept, 4500)
        self.assertNotIn("0.webp", left)                 # the oldest went first
        self.assertIn("9.webp", left)

    def test_markup_uses_our_address(self):
        self.assertEqual(tokenicons.url(MINT), f"/img/t/{MINT}.webp")
        self.assertEqual(tokenicons.url("nope"), "")
        h = tokenicons.img(MINT, 44)
        self.assertIn(f'src="/img/t/{MINT}.webp"', h)
        self.assertIn("width=44 height=44", h)
        from ui import public
        self.assertIn(f"/img/t/{MINT}.webp", public._icon("https://ipfs.io/ipfs/Qm", "BONK", MINT))
        self.assertIn("width=44", public._icon("https://ipfs.io/ipfs/Qm", "BONK", MINT, 44))
        self.assertIn("https://img.example/x.png", public._icon("https://img.example/x.png", "X"))   # no mint: as before

    def test_home_page_board_uses_our_address(self):
        from ui import coins, sitenav
        rows = [{"mint": (MINT[:-2] + f"{i:02d}").replace("0", "1"), "slug": f"c{i}", "symbol": f"C{i}", "icon": "https://ipfs.io/ipfs/Qm",
                 "mcap": 1e6 * (20 - i), "chg24h": i - 5.0, "liq": 1e5, "traders24": 100 + i, "created": "2026-01-01T00:00:00Z"}
                for i in range(12)]
        with mock.patch.object(coins, "top", return_value=rows):
            html = sitenav.coin_board("en")
        self.assertIn("/img/t/", html)
        self.assertNotIn("ipfs.io", html)


class Routes(IconsBase):
    def test_run_ui_serves_icons_on_every_host_without_login(self):
        import run_ui
        with mock.patch.object(run_ui, "SITE_URL", "https://memesonar.app"), \
                mock.patch.object(run_ui, "APP_URL", "https://app.memesonar.app"):
            for host in ("memesonar.app", "app.memesonar.app"):
                self.assertIsNone(run_ui.moved_to_site(host, f"/img/t/{MINT}.webp", False))
        srv = serve(run_ui.Handler)
        srv.verbose = False
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        with mock.patch.object(tokenicons, "known", return_value=("https://img.example/x.png", "BONK")), \
                mock.patch.object(tokenicons, "_get", side_effect=lambda u, **kw: png()):
            code, h, body = ask(srv, "GET", f"/img/t/{MINT}.webp", {"Host": "memesonar.app"})
        self.assertEqual((code, h["content-type"]), (200, "image/webp"))
        self.assertIn("max-age=604800", h["cache-control"])
        self.assertEqual(int(h["content-length"]), len(body))
        self.assertEqual(ask(srv, "GET", "/img/t/x.webp")[0], 404)


class DeployWindow(IconsBase):
    """deploy_wait.py while the app starts: images as usual, pages get the deploy page in the request's language."""

    def setUp(self):
        super().setUp()
        for k, v in (("body", deploypage.html("en").encode()), ("body_hr", deploypage.html("hr").encode())):
            p = mock.patch.object(deploy_wait.Wait, k, v)
            p.start()
            self.addCleanup(p.stop)
        self.srv = serve(deploy_wait.Wait)
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def test_images_are_served_normally(self):
        name = sorted(f for f in os.listdir(deploypage.STATIC_DIR) if f.endswith(".jpg"))[0]
        code, h, body = ask(self.srv, "GET", f"/static/landing/{name}")
        self.assertEqual((code, h["content-type"]), (200, "image/jpeg"))
        self.assertEqual(h["cache-control"], "public, max-age=86400")
        self.assertNotIn("x-memesonar-deploy", h)
        with open(os.path.join(deploypage.STATIC_DIR, name), "rb") as f:
            self.assertEqual(body, f.read())
        code, h, _ = ask(self.srv, "GET", "/favicon.svg")
        self.assertEqual((code, h["content-type"]), (200, "image/svg+xml"))
        self.assertEqual(ask(self.srv, "GET", "/static/landing/og-home.jpg")[0], 200)     # og image for link previews
        self.assertEqual(ask(self.srv, "GET", "/static/landing/nema-me.jpg")[0], 404)     # missing: 404, not the page
        self.assertEqual(ask(self.srv, "GET", "/static/landing/../../run_ui.py")[0], 503)  # not a file name we serve
        with open(os.path.join(self.dir, f"{MINT}.webp"), "wb") as f:
            f.write(b"RIFFxxxxWEBP")
        code, h, body = ask(self.srv, "GET", f"/img/t/{MINT}.webp")
        self.assertEqual((code, h["content-type"], body), (200, "image/webp", b"RIFFxxxxWEBP"))
        with mock.patch.object(tokenicons, "_get", side_effect=AssertionError("no fetch during a deploy")):
            code, h, body = ask(self.srv, "GET", f"/img/t/{MINT2}.webp")
        self.assertEqual((code, h["content-type"]), (200, "image/svg+xml"))
        self.assertEqual(ask(self.srv, "HEAD", "/favicon.ico")[0], 200)

    def test_pages_get_the_deploy_page_in_english_unless_clearly_croatian(self):
        def page(path, headers=None):
            code, h, body = ask(self.srv, "GET", path, headers)
            self.assertEqual((code, h["x-memesonar-deploy"]), (503, "1"))
            html = body.decode()
            return re.search(r"<html lang=(\w+)", html).group(1), re.search(r"<title>([^<]*)", html).group(1)
        self.assertEqual(page("/"), ("en", "Deploy in progress · MemeSonar"))
        self.assertEqual(page("/en")[0], "en")
        self.assertEqual(page("/coin/bonk")[0], "en")
        self.assertEqual(page("/hrvatska")[0], "en")
        self.assertEqual(page("/hr"), ("hr", "Deploy u tijeku · MemeSonar"))
        self.assertEqual(page("/hr/blog?x=1")[0], "hr")
        self.assertEqual(page("/", {"Cookie": "a=1; cb_lang=hr"})[0], "hr")
        self.assertEqual(page("/", {"Cookie": "cb_lang=en"})[0], "en")
        self.assertEqual(page("/", {"Accept-Language": "hr-HR,hr;q=0.9"})[0], "en")   # the browser language alone: no


class DeployPageLanguage(unittest.TestCase):
    def test_rule(self):
        L = deploypage.lang_for
        self.assertEqual([L("/"), L("/en"), L("/en/autopilot"), L("/hr"), L("/hr/"), L("/hr/coin/x"), L("/hrk")],
                         ["en", "en", "en", "hr", "hr", "hr", "en"])
        self.assertEqual(L("/", "cb_lang=hr"), "hr")
        self.assertEqual(L("/", "cb_lang=hrx"), "en")
        with mock.patch.dict(os.environ, {"DEPLOY_LANG": "hr"}):
            self.assertEqual(L("/"), "hr")

    def test_page_renders_both_languages_and_decides_again_in_the_browser(self):
        en, hr = deploypage.html("en"), deploypage.html("hr")
        self.assertIn("<html lang=en>", en)
        self.assertIn("Shipping a super cool deploy", en)
        self.assertIn(">Try now<", en)
        self.assertIn("<html lang=hr>", hr)
        self.assertIn(">Probaj sad<", hr)
        self.assertIn("location.pathname", en)              # the stored copy of the service worker picks by address
        self.assertIn("cb_lang=hr", en)
        self.assertNotIn("navigator.language", en)          # never the browser language alone
        self.assertIn('"lang": "auto"', en)


class ServiceWorker(unittest.TestCase):
    def test_stores_only_a_real_200_page(self):
        js = deploypage.sw_js()
        self.assertIn("res.status===200", js)
        self.assertIn("!res.headers.get(H)", js)
        self.assertNotIn("c.add(", js)                      # add() would not let us check the answer ourselves
        self.assertIn("r.mode!=='navigate'", js)            # images and API calls are never touched

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_worker_in_node(self):
        """The real sw.js with fake caches/fetch: a 503 or a deploy answer is never stored; images pass by."""
        harness = r"""
const src = require('fs').readFileSync(0, 'utf8');
const L = {}, store = {}, puts = [];
const Resp = (status, h = {}, type = 'basic') => ({ status, type, redirected: false, headers: { get: k => h[k.toLowerCase()] || null } });
global.self = { addEventListener: (n, f) => { L[n] = f }, skipWaiting: () => Promise.resolve(), clients: { claim: () => Promise.resolve() } };
global.caches = { open: n => Promise.resolve({ put: (k, r) => { puts.push([k, r.status]); store[k] = r; return Promise.resolve() },
  match: k => Promise.resolve(store[k]) }), keys: () => Promise.resolve([]), delete: () => Promise.resolve(true) };
global.Request = function (u, o) { this.url = u; Object.assign(this, o) };
let next;
global.fetch = () => Promise.resolve(next);
new Function(src)();
const install = async r => { next = r; let p; L.install({ waitUntil: x => { p = x } }); return p.then(() => 'ok', e => 'rejected') };
const nav = async (mode, r) => { next = r; let got = 'passed by'; L.fetch({ request: { mode, method: 'GET' }, respondWith: p => { got = p } });
  return got === 'passed by' ? got : (await got).status };
(async () => {
  const out = {};
  out.i503 = await install(Resp(503, { 'content-type': 'text/html' }));
  out.iDeploy = await install(Resp(200, { 'content-type': 'text/html', 'x-memesonar-deploy': '1' }));
  out.iJson = await install(Resp(200, { 'content-type': 'application/json' }));
  out.putsBad = puts.length;
  out.iGood = await install(Resp(200, { 'content-type': 'text/html; charset=utf-8' }));
  out.puts = puts.length;
  out.img503 = await nav('no-cors', Resp(503, {}));
  out.nav200 = await nav('navigate', Resp(200, {}));
  out.nav503 = await nav('navigate', Resp(503, {}));
  out.navDeploy = await nav('navigate', Resp(503, { 'x-memesonar-deploy': '1' }));
  console.log(JSON.stringify(out));
})();
"""
        r = subprocess.run(["node", "-e", harness], input=deploypage.sw_js(), capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual((out["i503"], out["iDeploy"], out["iJson"], out["putsBad"]), ("rejected", "rejected", "rejected", 0))
        self.assertEqual((out["iGood"], out["puts"]), ("ok", 1))
        self.assertEqual(out["img503"], "passed by")       # an image request: the worker stays out of it
        self.assertEqual(out["nav200"], 200)
        self.assertEqual(out["nav503"], 200)               # a bare 503 page load: the stored copy (a real 200 page)
        self.assertEqual(out["navDeploy"], 503)            # our own deploy page from deploy_wait: as it is


class Slider(unittest.TestCase):
    def test_first_screen_high_priority_the_rest_preloaded_after_load(self):
        for lang in ("en", "hr"):
            h = landing.showcase(lang)
            imgs = re.findall(r"<img [^>]*>", h)
            self.assertEqual(len(imgs), 6)
            self.assertIn('src="/static/landing/', imgs[0])
            self.assertIn("fetchpriority=high", imgs[0])
            for i in imgs[1:]:
                self.assertIn('data-src="/static/landing/', i)
                self.assertIn("fetchpriority=low", i)
                self.assertNotIn(" src=", i)                 # not with the page: after it (idle)
        js = landing.JS
        self.assertIn("requestIdleCallback", js)
        self.assertIn("addEventListener('load'", js)
        self.assertIn("saveData", js)                       # Save-Data: no preload, a tap still loads
        self.assertIn("pointerdown", js)                    # the tapped screen starts loading before the click
        self.assertIn("classList.toggle('was'", js)         # the old screen stays until the new one is ready
        self.assertIn("addEventListener('error'", js)       # a screen that failed is asked again
        self.assertIn(".show .vp img.was{opacity:1}", landing.CSS)


if __name__ == "__main__":
    unittest.main()
