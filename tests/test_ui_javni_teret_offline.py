"""23.11.2026. (hitno; production 20.-23.11.: the UI process was stopped by the memory watchdog 11 times in 2.5 days,
every time with 8+ public per-entity pages in flight, /telegram/<kanal> 100-330 s each), offline:

  - the admission gate (ui/javniteret.slot): UI_PUBLIC_BUILDS slots, a short wait, then 503 + Retry-After: 120 and a
    tiny body; refused above UI_MEM_SHED_MB; cached copies, logged-in visitors, /healthz and POST /hook/* never
    refused; one log line a minute "ui: odbijeno N javnih zahtjeva (...)"
  - the shared single-flight copy (javniteret.shared): one build for many callers at once
  - the channel page reads one channel (bounded queries, never the posts table, never the whole list) and shows the
    name, the follower count, the date of the last count and the link to the list; noindex as before
  - a burst on a fixture: 12 concurrent /telegram/<kanal> through the real handler, peak RSS growth < 150 MB
    (before the fix: 16.6 s for the 12 on the same fixture; set TG_FIXTURE_FULL=1 for the ~480 MB tg.db)
  - dugo: a DexScreener network error in one batch keeps the other batches (Task B, 22.11. 00:33 Traceback)
  - kol/chainwatch.drain: one drain at a time per process (30 webhook posts at once read the spool once)

    python3 -m unittest tests.test_ui_javni_teret_offline
"""
import os
import random
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ops import mem  # noqa: E402
from ui import javniteret, public, telegrampub  # noqa: E402

D = 86400


def make_tg(path, n_channels=3000, n_posts=130_000, text_len=300, seed=1):
    """tg.db in the production shape: channels of every status, five weekly follower rows each, posts (old and new)."""
    from tg import store
    con = store.connect(path)
    rnd, now = random.Random(seed), int(time.time())
    con.executemany("INSERT INTO channels(name,title,subs,status,checked_ts,n_posts) VALUES (?,?,?,?,?,?)",
                    [(f"chan_{i:05d}", f"Channel {i}", rnd.randint(100, 500_000),
                      ("active", "quiet", "slow", "dead", "candidate")[i % 5], now - D, 40) for i in range(n_channels)])
    txt = "x" * text_len
    rows = []
    for j in range(n_posts):
        ts = now - rnd.randint(0, 60 * D)
        rows.append((f"chan_{rnd.randrange(n_channels):05d}", j, ts, ts, txt, "[]", "[]", 10, None, "web"))
        if len(rows) >= 20_000:
            con.executemany("INSERT OR IGNORE INTO posts VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            rows = []
    con.executemany("INSERT OR IGNORE INTO posts VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    con.executemany("INSERT INTO tg_pratitelji VALUES (?,?,?)",
                    [(f"chan_{i:05d}", now - w * 7 * D, 1000 + i + w) for i in range(n_channels) for w in range(5)])
    con.commit()
    con.close()


def make_tg_calls(path, n_channels=3000, n_calls=10):
    """kol.db with n_calls clean measured calls of every channel 'tg:chan_<i>': since 23.11. (SEO, ui/seoindex) only
    the channels tracked as crypto call channels are on the public list."""
    from kol import store
    con = store.connect(path)
    now = int(time.time())
    con.executemany("INSERT INTO calls (tweet_id, token, handle, ts, kind, r1h, r24h, max24, mcap0) VALUES "
                    "(?,?,?,?, 'call', 0.1, 0.2, 0.5, 100000)",
                    [(f"tg:chan_{i:05d}/{j}", "T", f"tg:chan_{i:05d}", now - (3 + j) * D)
                     for i in range(n_channels) for j in range(n_calls)])
    con.commit()
    con.close()
    return path


class Gate(unittest.TestCase):
    def setUp(self):
        javniteret._refused.update(t=0.0, busy=0, mem=0, mb=None)

    def test_slots_wait_and_refusal(self):
        sem = threading.BoundedSemaphore(2)
        lines = []
        with mock.patch.object(javniteret, "_sem", sem), mock.patch.object(javniteret, "_rss", lambda: 300):
            a, b = javniteret.slot(log=lines.append), javniteret.slot(log=lines.append)
            a.__enter__()
            b.__enter__()
            t = time.time()
            with self.assertRaises(javniteret.Refused):
                with javniteret.slot(wait_s=0.2, log=lines.append):
                    pass
            self.assertGreaterEqual(time.time() - t, 0.19)   # it waited before refusing
            threading.Timer(0.1, lambda: b.__exit__(None, None, None)).start()
            with javniteret.slot(wait_s=2, log=lines.append):   # a slot freed within the wait: built
                pass
            a.__exit__(None, None, None)
            with javniteret.slot(wait_s=0, log=lines.append):
                pass
        self.assertEqual(lines, ["ui: odbijeno 1 javnih zahtjeva (zauzeto)"])

    def test_memory_shed_and_one_line_a_minute(self):
        lines = []
        with mock.patch.object(javniteret, "_rss", lambda: 700), mock.patch.object(javniteret, "SHED_MB", 600):
            for _ in range(3):
                with self.assertRaises(javniteret.Refused):
                    with javniteret.slot(log=lines.append):
                        self.fail("built above the memory limit")
        self.assertEqual(lines, ["ui: odbijeno 1 javnih zahtjeva (memorija 700 MB)"])
        self.assertEqual(javniteret._refused["mem"], 2)   # counted, said with the next line
        self.assertEqual(javniteret._note("busy", None, lines.append, now=time.time() + 61),
                         "ui: odbijeno 3 javnih zahtjeva (zauzeto / memorija 700 MB)")

    def test_defaults(self):
        self.assertEqual((javniteret.SLOTS, javniteret.WAIT_S, javniteret.SHED_MB, javniteret.RETRY_AFTER),
                         (int(os.environ.get("UI_PUBLIC_BUILDS") or 2), float(os.environ.get("UI_PUBLIC_WAIT_S") or 3),
                          float(os.environ.get("UI_MEM_SHED_MB") or 600), 120))
        self.assertLess(len(javniteret.BODY), 64)

    def test_route_503_and_the_exemptions(self):
        public._cache.clear()
        with mock.patch.object(javniteret, "_rss", lambda: 900), mock.patch.object(public, "_makroinf_sync", lambda: None), \
                mock.patch.object(public, "glossary_index", lambda lang: "<p>rječnik</p>"):
            self.assertEqual(public.route("/glossary", gate=True), (503, javniteret.BODY, "text/plain"))
            self.assertEqual(public._cache, {})                       # nothing kept for a refusal
            code, body, _ = public.route("/glossary", gate=False)      # a logged-in visitor / an internal warm
            self.assertEqual((code, body), (200, "<p>rječnik</p>".encode()))
            self.assertEqual(public.route("/glossary", gate=True)[0], 200)   # cached: served even now
        public._cache.clear()

    def test_same_path_built_once(self):
        public._cache.clear()
        n, started = [0], threading.Event()

        def slow(lang):
            n[0] += 1
            started.set()
            time.sleep(0.3)
            return "<p>x</p>"
        out = []
        with mock.patch.object(public, "_makroinf_sync", lambda: None), mock.patch.object(public, "glossary_index", slow):
            ts = [threading.Thread(target=lambda: out.append(public.route("/glossary", gate=True)[0])) for _ in range(6)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
        self.assertEqual((n[0], out), (1, [200] * 6))
        public._cache.clear()

    def test_the_cache_is_gzipped_and_bounded(self):
        public._cache.clear()
        with mock.patch.object(public, "CACHE_MAX_MB", 0.01):
            for i in range(30):
                public._keep(f"/p{i}", time.time(), 200, os.urandom(1000))
        self.assertLessEqual(sum(len(v[2]) for v in public._cache.values()), 10_000)
        self.assertIn("/p29", public._cache)
        self.assertNotIn("/p0", public._cache)
        self.assertEqual(public._ttl("/telegram/abc"), public.TG_CACHE_S)
        self.assertEqual(public._ttl("/hr/telegram-kanali"), public.TG_CACHE_S)
        self.assertEqual(public._ttl("/influencer/abc"), public.CACHE_S)
        public._cache.clear()


class Shared(unittest.TestCase):
    def test_one_build_for_many_and_the_version(self):
        javniteret.forget()
        n = [0]

        def build():
            n[0] += 1
            time.sleep(0.2)
            return [n[0]]
        out = []
        ts = [threading.Thread(target=lambda: out.append(javniteret.shared(("t",), 60, build, version=1)))
              for _ in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual((n[0], out), (1, [[1]] * 8))
        self.assertEqual(javniteret.shared(("t",), 60, build, version=2), [2])   # a new version: rebuilt
        t_now = time.monotonic()
        with mock.patch.object(javniteret.time, "monotonic", lambda: t_now + 61):
            self.assertEqual(javniteret.shared(("t",), 60, build, version=2), [3])   # past ttl: rebuilt
        javniteret.forget()


class Server:
    def __init__(self):
        import run_ui
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), run_ui.Handler)
        self.srv.verbose = False
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def get(self, path, method="GET", data=None):
        req = urllib.request.Request(self.base + path, method=method, data=data)

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        try:
            with urllib.request.build_opener(NoRedirect).open(req, timeout=120) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


class Telegram(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.TemporaryDirectory()
        cls.db = os.path.join(cls.d.name, "tg.db")
        full = os.environ.get("TG_FIXTURE_FULL") == "1"
        make_tg(cls.db, n_posts=130_000, text_len=3500 if full else 300)
        kol = make_tg_calls(os.path.join(cls.d.name, "kol.db"))
        cls.env = mock.patch.dict(os.environ, {"TG_DB": cls.db, "KOL_DB": kol})
        cls.env.start()

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.d.cleanup()

    def setUp(self):
        public._cache.clear()
        javniteret.forget()

    def test_the_channel_page_reads_one_channel(self):
        from tg import store
        sql = []
        real = store.ro

        def traced(path=None):
            con = real(path)
            con.set_trace_callback(sql.append)
            return con
        with mock.patch.object(store, "ro", traced), \
                mock.patch.object(telegrampub, "rows", lambda now=None: self.fail("the whole list was read")):
            en = telegrampub.profile("chan_00000", "en")
            hr = telegrampub.profile("CHAN_00005", "hr")   # the name in any case, as before
            self.assertIsNone(telegrampub.profile("chan_00003", "en"))   # status 'dead': not on the list, as before
            self.assertIsNone(telegrampub.profile("nope_x", "en"))
        self.assertTrue(sql)
        self.assertFalse([q for q in sql if "posts" in q.replace("tg_pratitelji", "")])
        self.assertTrue(all("WHERE" in q for q in sql if q.lstrip().upper().startswith("SELECT")))
        self.assertIn("chan_00000", en)
        self.assertIn("Followers: 1,000.", en)                     # the newest weekly row (1000 + i + 0)
        day = time.strftime("%Y-%m-%d", time.gmtime())
        self.assertIn(f"Last count: {day}.", en)
        self.assertIn("href=/telegram-channels>The list of crypto call channels", en)
        self.assertIn('content="noindex,follow"', en)               # unchanged: channel pages are noindex
        self.assertIn("chan_00005", hr)
        self.assertIn("Zadnje brojanje:", hr)
        self.assertIn("href=/hr/telegram-kanali>Popis kripto call kanala", hr)

    def test_the_hub_is_built_once_without_the_whole_list(self):
        from tg import pratitelji
        n = [0]
        real = telegrampub._top

        def counted(lim, names):
            n[0] += 1
            return real(lim, names)
        with mock.patch.object(telegrampub, "_top", counted), \
                mock.patch.object(pratitelji, "pregled", lambda *a, **k: self.fail("the whole list was read")):
            a = telegrampub.hub("en")
            b = telegrampub.hub("hr")
        self.assertEqual(n[0], 1)
        self.assertEqual(len(telegrampub.rows()), 1800)   # active, quiet, slow of 3000 (the full list still works)
        self.assertNotIn("noindex", a)
        self.assertIn("chan_", b)

    def test_MEMORY_a_burst_of_12_channel_pages(self):
        srv = Server()
        try:
            srv.get("/telegram/chan_00001")   # imports and the first page out of the measurement
            public._cache.clear()
            paths = [("/hr" if i % 2 else "") + f"/telegram/chan_{5 * (i + 2):05d}" for i in range(12)]
            peak, base, stop = [mem.rss_mb()], mem.rss_mb(), []

            def sample():
                while not stop:
                    peak[0] = max(peak[0], mem.rss_mb())
                    time.sleep(0.05)
            th = threading.Thread(target=sample, daemon=True)
            th.start()
            res = []
            t0 = time.time()
            with mock.patch.object(javniteret, "SLOTS", 12), mock.patch.object(javniteret, "_sem",
                                                                              threading.BoundedSemaphore(12)):
                ts = [threading.Thread(target=lambda p=p: res.append(srv.get(p)[0])) for p in paths]
                for t in ts:
                    t.start()
                for t in ts:
                    t.join()
            dt = time.time() - t0
            stop.append(1)
            th.join()
        finally:
            srv.close()
        self.assertEqual(sorted(res), [200] * 12)
        self.assertLess(peak[0] - base, 150, f"peak {peak[0]} MB from {base} MB")
        self.assertLess(dt, 10.0)   # before: 16.6 s for the 12 on this fixture's full size (100-330 s in production)

    def test_503_with_retry_after_and_the_exempt_paths(self):
        srv = Server()
        try:
            with mock.patch.object(javniteret, "_rss", lambda: 950):
                code, headers, body = srv.get("/telegram/chan_00010")
                self.assertEqual((code, headers.get("Retry-After"), body), (503, "120", javniteret.BODY))
                self.assertNotIn("X-Robots-Tag", headers)                 # "come back later", not "never index"
                self.assertNotIn(b"prijava", body.lower())
                for path in ("/robots.txt", "/sitemap.xml", "/favicon.ico"):   # never refused
                    self.assertEqual(srv.get(path)[0], 200, path)
                self.assertEqual(srv.get("/healthz")[0], 200)
                self.assertEqual(srv.get("/hook/chain", "POST", b"[]")[0], 401)   # the webhook is answered, never 503
            self.assertEqual(srv.get("/telegram/chan_00010")[0], 200)
            with mock.patch.object(javniteret, "_rss", lambda: 950):
                self.assertEqual(srv.get("/telegram/chan_00010")[0], 200)   # now cached: served above the limit too
        finally:
            srv.close()

    def test_a_logged_in_visitor_is_never_gated(self):
        import run_ui
        seen = []
        h = run_ui.Handler.__new__(run_ui.Handler)
        h.path, h.headers = "/telegram/chan_00010", {"Host": "x", "Cookie": ""}
        h._send = lambda *a, **k: None
        with mock.patch.object(run_ui, "AUTH", True), mock.patch.object(run_ui.Handler, "_authorized", lambda self: True), \
                mock.patch.object(public, "route", lambda p, gate=False: seen.append(gate) or (200, b"x", "text/html")), \
                mock.patch.object(run_ui, "moved_to_site", lambda *a: None):
            h._do_get()
        with mock.patch.object(run_ui, "AUTH", True), mock.patch.object(run_ui.Handler, "_authorized", lambda self: False), \
                mock.patch.object(public, "route", lambda p, gate=False: seen.append(gate) or (200, b"x", "text/html")), \
                mock.patch.object(run_ui, "moved_to_site", lambda *a: None):
            h._do_get()
        self.assertEqual(seen, [False, True])


class Seo(unittest.TestCase):
    """23.11. (SEO check of production as Googlebot: impressions fell to zero)."""

    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.TemporaryDirectory()
        cls.db = os.path.join(cls.d.name, "tg.db")
        make_tg(cls.db, n_posts=100)
        kol = make_tg_calls(os.path.join(cls.d.name, "kol.db"))
        cls.env = mock.patch.dict(os.environ, {"TG_DB": cls.db, "KOL_DB": kol})
        cls.env.start()

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.d.cleanup()

    def setUp(self):
        public._cache.clear()
        javniteret.forget()

    def test_the_hub_lists_the_top_channels_only(self):
        from tg import pratitelji
        with mock.patch.object(telegrampub, "HUB_MAX", 100):
            en, hr = telegrampub.hub("en"), telegrampub.hub("hr")
            rows, total = telegrampub.top()
        want = [r for r in pratitelji.pregled(self.db) if telegrampub.CH.fullmatch(r["kanal"])][:100]
        self.assertEqual((rows, total), (want, 1800))                     # the same rows and order as the full list
        self.assertEqual(en.count('href="/telegram/'), 100)
        self.assertEqual(hr.count('href="/hr/telegram/'), 100)
        self.assertIn("The 100 channels with the most followers, of 1,800 on the list.", en)
        self.assertIn("100 kanala s najviše pratitelja, od 1.800 na popisu.", hr)
        self.assertLess(len(en.encode()), 1_000_000)
        self.assertNotIn("noindex", en)                                    # the hub stays indexable
        last = want[-1]["kanal"]
        outside = next(r["kanal"] for r in pratitelji.pregled(self.db)[150:])
        self.assertIn(last, en)
        self.assertNotIn(f"/telegram/{outside}\"", en)                    # not linked from the hub ...
        page = telegrampub.profile(outside, "en")                          # ... but its light page lives on
        self.assertIn('content="noindex,follow"', page)
        self.assertEqual(telegrampub.HUB_MAX, int(os.environ.get("TG_HUB_MAX") or 200))

    def test_trailing_slash_is_a_301_to_the_path_without_it(self):
        import run_ui
        for path, want in (("/influencers/", "/influencers"), ("/hr/", "/hr"), ("/coin/abc/", "/coin/abc"),
                           ("/hr/influenceri/", "/hr/influenceri"), ("/telegram-channels/", "/telegram-channels"),
                           ("/telegram/chan_00001/", "/telegram/chan_00001"), ("/blog/", "/blog"), ("/en/", "/en"),
                           ("/autopilot/", "/autopilot"), ("/", None), ("/pregled/", None), ("/novcanici-admin/", None),
                           ("/influencers", None)):
            self.assertEqual(run_ui.slash_redirect(path), want, path)
        srv = Server()
        try:
            code, headers, _ = srv.get("/influencers/?sort=a")
            self.assertEqual((code, headers.get("Location")), (301, "/influencers?sort=a"))
            code, headers, _ = srv.get("/telegram/chan_00000/")
            self.assertEqual((code, headers.get("Location")), (301, "/telegram/chan_00000"))
        finally:
            srv.close()

    def test_robots_and_sitemap_are_cacheable_and_kept(self):
        n = [0]
        real = public.sitemap

        def counted():
            n[0] += 1
            return real()
        srv = Server()
        try:
            with mock.patch.object(public, "sitemap", counted):
                for path in ("/robots.txt", "/sitemap.xml"):
                    code, headers, _ = srv.get(path)
                    self.assertEqual((code, headers.get("Cache-Control")), (200, "public, max-age=3600"), path)
                srv.get("/sitemap.xml")
                self.assertEqual(n[0], 1)                                  # built once, then the copy
                with public._lock:                                         # an hour later: the old copy at once ...
                    t, c, gz = public._cache["/sitemap.xml"]
                    public._cache["/sitemap.xml"] = (t - public.KEEP_S - 1, c, gz)
                code, _, body = srv.get("/sitemap.xml")
                self.assertEqual(code, 200)
                self.assertIn(b"<urlset", body)
                for _ in range(40):                                        # ... and one rebuild in the background
                    if n[0] == 2:
                        break
                    time.sleep(0.05)
                self.assertEqual(n[0], 2)
            with mock.patch.object(public, "CACHE_MAX_MB", 0.0001):        # the byte cap never drops the sitemap
                public._keep("/x", time.time(), 200, b"y" * 5000)
            self.assertIn("/sitemap.xml", public._cache)
            self.assertEqual(srv.get("/influencers")[1].get("Cache-Control"), "no-store")   # other pages as before
        finally:
            srv.close()


class Baseline(unittest.TestCase):
    def test_streamed_baseline_equals_the_old_one(self):
        import statistics
        from kol import store
        from ui import kolstats
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "kol.db")
            con = store.connect(p)
            rnd = random.Random(3)
            now = 1_795_400_000
            con.executemany("INSERT INTO kols(handle, bot) VALUES (?, ?)", [(f"k{i}", int(i == 3)) for i in range(40)])
            con.executemany("INSERT INTO calls(tweet_id, token, handle, ts, kind, r1h, r24h, max24) VALUES (?,?,?,?,?,?,?,?)",
                            [(f"t{j}", f"M{j}", f"k{rnd.randrange(40)}", now - rnd.randint(2, 40) * D, "call",
                              rnd.uniform(-1, 1), None if j % 7 == 0 else rnd.uniform(-1, 1), rnd.uniform(0, 2))
                             for j in range(3000)])
            con.commit()
            got = kolstats.baseline(con, now=now, cache={})
            # the old computation, written out
            bots = kolstats._bots(con)
            by = {}
            for h, r1, r24, mx in con.execute("SELECT handle, r1h, r24h, max24 FROM calls WHERE kind='call' AND "
                                              "max24 IS NOT NULL AND ts < ?", (now - kolstats.PUBLIC_DELAY_S,)):
                if h not in bots:
                    by.setdefault(h, []).append((r1, r24, mx))
            ok = [v for v in by.values() if len(v) >= kolstats.MIN_CLEAN]
            want = {"accounts": len(ok),
                    "up1h": statistics.median([kolstats._share([x[0] for x in v], lambda x: x > 0) for v in ok]),
                    "hit15": statistics.median([kolstats._share([x[2] for x in v], lambda x: x >= kolstats.HIT) for v in ok]),
                    "med24": statistics.median([statistics.median([x[1] for x in v if x[1] is not None]) for v in ok])}
            con.close()
        self.assertEqual(got, want)


class Dugo(unittest.TestCase):
    def test_a_network_error_keeps_the_other_batches(self):
        from dugo import sources
        mints = [f"M{i:03d}" for i in range(70)]
        calls = []

        def tokens(chain, addrs, ttl=None):
            calls.append(list(addrs))
            if len(calls) == 2:
                raise urllib.error.URLError(TimeoutError("timed out"))
            return [{"baseToken": {"address": a}, "liquidity": {"usd": 1e5}, "priceUsd": "1", "quoteToken":
                     {"symbol": "SOL"}} for a in addrs]
        err = []
        with mock.patch.object(sources.dex, "tokens", tokens), \
                mock.patch.object(sources.dex, "pick_pool", lambda ps: (ps[0], None)), \
                mock.patch("sys.stderr") as se:
            se.write = err.append
            best = sources.dex_best(set(mints))
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(best), 70 - len(calls[1]))
        self.assertFalse(set(best) & set(calls[1]))
        line = "".join(err)
        self.assertIn("dugo: DexScreener nije odgovorio (URLError", line)
        self.assertIn("1 od 3 upita), nastavljam s onim što imam", line)

    def test_collect_survives_a_dead_dexscreener(self):
        from dugo import sources
        with mock.patch.object(sources.dex, "tokens", mock.Mock(side_effect=TimeoutError("timed out"))), \
                mock.patch("sys.stderr"):
            self.assertEqual(sources.dex_best({"A", "B"}), {})


class ChainDrain(unittest.TestCase):
    def test_one_drain_at_a_time(self):
        from kol import chainwatch
        with tempfile.TemporaryDirectory() as d:
            hype = os.path.join(d, "hype.db")
            sp = chainwatch.spool_dir(hype)
            os.makedirs(sp)
            for i in range(5):
                with open(os.path.join(sp, f"{i}.json"), "w") as f:
                    f.write("[]")
            gate, reads = threading.Event(), []
            real = chainwatch.ingest

            def slow(payload, hype_db=None, _spool=True, timeout=None):
                reads.append(1)
                gate.wait(2)
                return real(payload, hype_db, _spool, timeout)
            with mock.patch.object(chainwatch, "ingest", slow):
                t = threading.Thread(target=lambda: chainwatch.drain(hype, log=lambda *a, **k: None))
                t.start()
                time.sleep(0.1)
                self.assertEqual(chainwatch.drain(hype, log=lambda *a, **k: None), 0)   # skipped, not a second read
                gate.set()
                t.join()
            self.assertEqual(len(reads), 5)
            self.assertEqual(os.listdir(sp), [])


if __name__ == "__main__":
    unittest.main()
