"""23.11.2026. (vlasnik: "Ne želimo izlistavati podatke koji nisu dobro profiltrirani, kao Telegram kanali ... smanjiš
sitemapu, staviš samo relevantne stranice, provjeriš robots.txt"; i "kako impresije i klikovi budu rasli, da se dodaju
nove stranice ... postepeno s vremenom"): the one indexing policy (ui/seoindex.py), offline.

  - the core per section on a fixture (hubs, editorial, at most 30 coins with our own data, 30 influencers by clean
    calls), everything else public is 200 + noindex,follow (meta and X-Robots-Tag), template pages too
  - the sitemap: only the core, every URL rendered through the real handler (200, no redirect, no noindex,
    self canonical, hreflang twins in the sitemap), under 500, lastmod never in the future and not "today" everywhere
  - stability (30 days), refill, the weekly growth step (no data, healthy growth with the cap and the spread, pause,
    template pages only after the coin page is indexed, nothing removed inside 30 days), idempotent
  - Telegram: the hub lists only the filtered channels, a listed channel's page is 200 + noindex, every other one 410
  - robots.txt on the site (every Allow line opens a real page, nothing of the core disallowed) and on the app host
  - the daily log line
No network.

    python3 -m unittest tests.test_seo_indeks_offline
"""
import datetime as dt
import json
import os
import re
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
from tests import autopilot_staro  # noqa: E402
os.environ.setdefault("I18N_OFF", "1")

from kol import store as kstore  # noqa: E402
from tg import store as tstore  # noqa: E402
from tokenstranice import store as TS  # noqa: E402
from ui import coins, javniteret, public, seoindex, telegrampub  # noqa: E402

D = 86400
NOW = int(time.time())
BASE = "https://memesonar.app"
N_COINS, N_INFL = 60, 45


def mint(i):
    return f"Mint{i:03d}" + "a" * 36


def page_data(i, rich):
    days = 30 if rich else 8
    px = [((NOW // D - days + k) * D, 0.01 + k * 0.0001) for k in range(days)]
    return {"mint": mint(i), "symbol": f"C{i}", "ts": NOW, "enough": 1, "days": days,
            "now": {"price": 0.01, "mcap": 1e9 - i * 1e6, "liq": 5e5, "vol24": 1e6, "chg24": 2.0},
            "hist": {"px": px, "vol": [], "mc": [], "liq": []},
            "calls": {"stats": {"n": 5 if rich else 0}, "list": []},
            "holders": {"n_top": 50, "hist": [(px[k][0], 1000 + k) for k in range(days)]} if rich else {},
            "m": {"cat": "A"} if rich else {}, "range": {"n": days, "med": 0.1, "p25": 0.05, "p75": 0.2} if rich else {}}


def build(d):
    """The fixture databases: 60 top coins (every 3rd one thin), 45 influencers (k+5 clean calls), 6 Telegram channels
    (3 tracked call channels with 12 clean calls on the follower list, one with 4, one tracked but not listed, one
    without calls), makroinf off."""
    pub = coins.connect(os.path.join(d, "public.db"))
    for i in range(1, N_COINS + 1):
        pub.execute("INSERT INTO coins (mint, slug, symbol, name, rank, mcap, price, liq, holders, vol24, chg24h, "
                    "traders24, created, audit, updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (mint(i), f"c{i}", f"C{i}", f"Coin {i}", i, 1e9 - i * 1e6, 0.01, 5e5, 1000, 1e6, 1.5, 100 + i,
                     "2025-01-01T00:00:00Z", "{}", NOW - 3600))
    pub.commit()
    pub.close()
    ts = TS.connect(os.path.join(d, "tokenstranice.db"))
    for i in range(1, N_COINS + 1):
        ts.execute("INSERT INTO pages (mint, slug, symbol, name, src, first_ts, last_ts, active, enough, mcap, vol24, "
                   "data, updated) VALUES (?,?,?,?,?,?,?,1,1,?,?,?,?)",
                   (mint(i), f"c{i}", f"C{i}", f"Coin {i}", "top", NOW - 40 * D, NOW, 1e9 - i * 1e6, 1e6,
                    json.dumps(page_data(i, i % 3 != 0)), NOW))
    ts.commit()
    ts.close()
    k = kstore.connect(os.path.join(d, "kol.db"))
    st = json.dumps({"measured": 12, "hit_rate": .5, "med_max24": .3, "rug_rate": .1, "prepump_rate": 0})
    for i in range(N_INFL):
        h = f"kol{i:02d}"
        k.execute("INSERT INTO kols (handle, name, followers, score, stats) VALUES (?,?,?,?,?)",
                  (h, h, 5000, 50 + i, st))
        for j in range(i + 5):
            k.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, r1h, r24h, max24, mcap0) "
                      "VALUES (?,?,?,?, 'call', 0.1, 0.2, 0.5, 100000)", (f"{h}-{j}", mint(1 + j % 40), h,
                                                                           NOW - (3 + j) * D))
    tg_calls = {"alpha_calls": 12, "beta_calls": 12, "gamma_calls": 15, "thin_calls": 4, "gone_calls": 12}
    for ch, n in tg_calls.items():
        for j in range(n):
            k.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, r1h, r24h, max24, mcap0) "
                      "VALUES (?,?,?,?, 'call', 0.1, 0.2, 0.5, 100000)", (f"tg:{ch}/{j}", mint(2), f"tg:{ch}",
                                                                           NOW - (5 + j) * D))
    k.commit()
    k.close()
    t = tstore.connect(os.path.join(d, "tg.db"))
    for name, subs, status in (("alpha_calls", 9000, "active"), ("Beta_Calls", 20000, "active"),
                               ("gamma_calls", 500, "quiet"), ("thin_calls", 70000, "active"),
                               ("gone_calls", 1000, "dead"), ("cooking_tips", 900000, "active")):
        t.execute("INSERT INTO channels (name, title, subs, status, checked_ts) VALUES (?,?,?,?,?)",
                  (name, name.title(), subs, status, NOW - D))
    t.commit()
    t.close()


ENV = {}


def setUpModule():
    autopilot_staro.setUpModule()   # 27.11.: tests the removed Autopilot (AUTOPILOT_OFF=0)
    ENV["tmp"] = tempfile.TemporaryDirectory()
    d = ENV["tmp"].name
    build(d)
    ENV["dir"] = d
    ENV["patches"] = [mock.patch.dict(os.environ, {
        "DATA_DIR": d, "KOL_DB": os.path.join(d, "kol.db"), "TG_DB": os.path.join(d, "tg.db"),
        "TOKENSTRANICE_DB": os.path.join(d, "tokenstranice.db"), "DUGO_DB": os.path.join(d, "dugo.db"),
        "MAKROINF_DB": os.path.join(d, "makroinf.db"), "SEO_DB": os.path.join(d, "public.db"),
        "ANALYTICS_DB": os.path.join(d, "analytics.db"), "RENDER_EXTERNAL_URL": BASE, "I18N_OFF": "1"}),
        mock.patch.object(coins, "DB", os.path.join(d, "public.db"))]
    for p in ENV["patches"]:
        p.start()
    fresh()


def tearDownModule():
    for p in reversed(ENV["patches"]):
        p.stop()
    seoindex.reset()
    public._cache.clear()
    javniteret.forget()
    ENV["tmp"].cleanup()
    autopilot_staro.tearDownModule()


def fresh():
    seoindex.reset()
    public._cache.clear()
    javniteret.forget()
    with mock.patch("builtins.print"):
        seoindex.ensure()


def html(path):
    code, body, _ = public.route(path)
    return code, body.decode("utf-8", "replace")


def head(h):
    return h.split("</head>", 1)[0]


class Server:
    def __init__(self):
        import run_ui
        # as in production: passwords on, the visitor (Googlebot) not logged in
        self.auth = mock.patch.object(run_ui, "AUTH", True)
        self.auth.start()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), run_ui.Handler)
        self.srv.verbose = False
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def get(self, path, host="memesonar.app"):
        req = urllib.request.Request(self.base + path, headers={"Host": host, "User-Agent": "Googlebot"})

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
        self.auth.stop()


# ---------- the policy --------------------------------------------------------------------------------------------------

class Core(unittest.TestCase):
    def test_counts_per_section(self):
        from ui import blog, glossary_public as GP, tools
        rows = seoindex.state()["rows"].values()
        by = {}
        for r in rows:
            by[r["section"]] = by.get(r["section"], 0) + 1
        posts = [u for u in blog.urls() if seoindex._is_post(u[0])]
        self.assertEqual(by.get("blog"), len(posts))
        self.assertEqual(by.get("glossary"), len(GP.ENTRIES))
        self.assertEqual(by.get("tools"), len(tools.urls()) - 1)
        self.assertEqual(by.get("coin"), 30)            # the 30 biggest of the 40 rich coins (the thin ones never)
        self.assertEqual(by.get("influencer"), 30)      # 40 with 10+ clean calls, the 30 with the most
        self.assertNotIn("macro", by)                   # the owner switch is off: no macro pages at all
        for s in ("buy", "rug", "pp"):
            self.assertNotIn(s, by)                     # template pages only grow in later (indexed coin first)
        coins_in = {r["en"] for r in rows if r["section"] == "coin"}
        self.assertTrue(all(int(p.rsplit("c", 1)[1]) % 3 for p in coins_in))   # only coins with our own data
        self.assertIn("/coin/c1", coins_in)
        infl = {r["en"] for r in rows if r["section"] == "influencer"}
        self.assertEqual(infl, {f"/influencer/kol{i:02d}" for i in range(15, 45)})   # the most clean calls
        hubs = {r["en"] for r in rows if r["section"] == "hub"}
        for p in ("/", "/influencers", "/solana-meme-coins", "/solana-meme-coins/trending", "/glossary", "/blog",
                  "/best-crypto-tools", "/how-to-buy", "/rug-check", "/autopilot", "/solana-market",
                  "/telegram-channels"):
            self.assertIn(p, hubs, p)
        print(f"\n  jezgra na fixtureu: {dict(sorted(by.items()))}, sitemap {len(public.sitemap().split('<url>')) - 1}")

    def test_noindex_outside_the_core(self):
        for path in ("/how-to-buy/c1", "/hr/kako-kupiti/c1", "/rug-check/c2", "/hr/provjera/c2",
                     "/coin/c1/price-prediction", "/hr/coin/c1/prognoza", "/coin/c3", "/hr/coin/c3", "/coin/c58",
                     "/influencer/kol05", "/hr/influencer/kol05", "/telegram/alpha_calls"):
            code, h = html(path)
            self.assertEqual(code, 200, path)
            self.assertIn('<meta name=robots content="noindex,follow">', head(h), path)
            self.assertFalse(seoindex.indexable(path), path)
        for path in ("/coin/c1", "/hr/coin/c1", "/influencer/kol44", "/hr/influencer/kol44", "/blog", "/hr/rjecnik"):
            code, h = html(path)
            self.assertEqual(code, 200, path)
            self.assertNotIn("noindex", head(h), path)
            self.assertTrue(seoindex.indexable(path), path)

    def test_hubs_link_the_core(self):
        _, coins_html = html("/solana-meme-coins")
        _, infl_html = html("/influencers")
        for p in seoindex.section_paths("coin"):
            self.assertIn(f'href="{p}"', coins_html, p)
        for p in seoindex.section_paths("influencer"):
            self.assertIn(f'href="{p}"', infl_html, p)
        _, hr_coins = html("/hr/solana-meme-coini")
        self.assertIn('href="/hr/coin/c1"', hr_coins)

    def test_hreflang_twins_have_the_same_state(self):
        for r in seoindex.state()["rows"].values():
            if r["hr"]:
                self.assertTrue(seoindex.indexable(r["en"]) and seoindex.indexable(r["hr"]), r)
        for en, hr in (("/coin/c3", "/hr/coin/c3"), ("/how-to-buy/c1", "/hr/kako-kupiti/c1"),
                       ("/influencer/kol01", "/hr/influencer/kol01"), ("/telegram/alpha_calls", "/hr/telegram/alpha_calls")):
            self.assertEqual(seoindex.indexable(en), seoindex.indexable(hr), en)

    def test_idempotent(self):
        before = {k: dict(v) for k, v in seoindex.state()["rows"].items()}
        with mock.patch("builtins.print"):
            seoindex.ensure()
            seoindex.ensure()
        seoindex.reset()
        self.assertEqual({k: dict(v) for k, v in seoindex.state()["rows"].items()}, before)

    def test_other_files_never_reuse_the_state(self):
        """A core computed from other databases (another path) is never served: recomputed at once, and back."""
        try:
            empty = os.path.join(ENV["dir"], "prazan-kol.db")
            kstore.connect(empty).close()
            with mock.patch.dict(os.environ, {"KOL_DB": empty}), mock.patch("builtins.print"):
                self.assertFalse(seoindex.indexable("/influencer/kol44"))
                self.assertFalse(seoindex.indexable("/influencers"))          # readable and empty: no data hub
                self.assertEqual(seoindex.tg_channels(), ({}, False))
            with mock.patch("builtins.print"):
                self.assertTrue(seoindex.indexable("/influencer/kol44"))
                self.assertEqual(len(seoindex.tg_channels()[0]), 3)
        finally:
            fresh()

    def test_a_hub_stays_while_its_source_cannot_be_read(self):
        """kol.db missing for a moment (a start, a lock): the ranking and the profiles keep their place."""
        try:
            with mock.patch.object(public, "_con", lambda: None), mock.patch("builtins.print"):
                seoindex.ensure()
                self.assertTrue(seoindex.indexable("/influencers"))
                self.assertTrue(seoindex.indexable("/influencer/kol44"))
                self.assertEqual(len(seoindex.tg_channels()[0]), 3)            # the stored filtered list stays
        finally:
            fresh()

    def test_a_changed_store_is_read_again(self):
        """The in-memory copy follows the stored core when its file changes (read again after RELOAD_S)."""
        try:
            self.assertTrue(seoindex.indexable("/coin/c1"))
            con = sqlite3.connect(os.environ["SEO_DB"])
            con.execute("DELETE FROM seo_core WHERE en = '/coin/c1'")
            con.commit()
            con.close()
            t = time.monotonic()
            with mock.patch.object(seoindex.time, "monotonic", lambda: t + seoindex.RELOAD_S + 1):
                self.assertFalse(seoindex.indexable("/coin/c1"))
        finally:
            fresh()

    def test_daily_line(self):
        c = seoindex._counts(seoindex.state(), NOW)
        line = seoindex.daily_line(c)
        self.assertRegex(line, r"^seo: sitemap \d+ adresa \(naslovnica i hubovi \d+, blog \d+, rječnik \d+, alati \d+, "
                               r"tokeni 60, influenceri 60, makro 0\); izvan indeksa: tokeni 60, influenceri 30, makro 0, "
                               r"kako-kupiti 120, provjera 120, prognoze 120, telegram kanali 6$")
        self.assertIn(f"sitemap {len(public.sitemap().split('<url>')) - 1} adresa", line)


# ---------- the sitemap ---------------------------------------------------------------------------------------------------

class Sitemap(unittest.TestCase):
    def test_only_the_core_rendered_through_the_handler(self):
        xml = public.sitemap()
        locs = re.findall(r"<loc>([^<]+)</loc>", xml)
        self.assertLess(len(locs), 500)
        self.assertEqual(len(locs), len(set(locs)))
        paths = [u[len(BASE):] or "/" for u in locs]
        self.assertTrue(all(seoindex.indexable(p) for p in paths))
        today = time.strftime("%Y-%m-%d", time.gmtime())
        mods = re.findall(r"<lastmod>([^<]+)</lastmod>", xml)
        self.assertTrue(mods and all(m <= today for m in mods))
        self.assertLess(sum(m == today for m in mods), len(mods) / 2)   # not "today" for everything
        self.assertNotIn("/telegram/", xml)
        self.assertNotIn("/how-to-buy/", xml)
        self.assertNotIn("price-prediction", xml)
        public._cache.clear()
        srv = Server()
        bad = []
        try:
            for p in paths:
                code, hd, body = srv.get(p)
                h = body.decode("utf-8", "replace")
                if code != 200 or hd.get("Location") or "noindex" in hd.get("X-Robots-Tag", "") \
                        or re.search(r"<meta name=robots[^>]*noindex", head(h)):
                    bad.append((p, code, hd.get("Location"), hd.get("X-Robots-Tag")))
                    continue
                if p in ("/", "/hr"):
                    continue
                canon = re.search(r'<link rel=canonical href="([^"]+)"', h)
                if not canon or canon.group(1) != BASE + p:
                    bad.append((p, "canonical", canon and canon.group(1)))
                for alt in re.findall(r'<link rel=alternate hreflang=(?:en|hr) href="([^"]+)"', h):
                    if alt not in locs:
                        bad.append((p, "hreflang", alt))
        finally:
            srv.close()
        self.assertEqual(bad, [])

    def test_trending_list_is_a_200_in_the_sitemap(self):
        self.assertIn(f"<loc>{BASE}/solana-meme-coins/trending</loc>", public.sitemap())
        srv = Server()
        try:
            for host in ("memesonar.app", "localhost"):
                code, hd, _ = srv.get("/solana-meme-coins/trending", host)
                self.assertEqual((code, hd.get("Location")), (200, None))
        finally:
            srv.close()

    def test_noindex_pages_carry_the_header(self):
        public._cache.clear()
        srv = Server()
        try:
            code, hd, _ = srv.get("/how-to-buy/c1")
            self.assertEqual((code, hd.get("X-Robots-Tag")), (200, "noindex, follow"))
            code, hd, _ = srv.get("/coin/c1")
            self.assertEqual(code, 200)
            self.assertNotIn("X-Robots-Tag", hd)
        finally:
            srv.close()


# ---------- stability and growth -------------------------------------------------------------------------------------------

def u(sec, i):
    return (f"/{sec}/x{i:03d}", f"/hr/{sec}/x{i:03d}", "0.5", "2026-11-01")


class Growth(unittest.TestCase):
    """The data sections with fake candidates, a database of their own and a fake Search Console."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = os.path.join(self.tmp.name, "seo.db")
        self.an = os.path.join(self.tmp.name, "analytics.db")
        self.cands = {"coin": [u("coin", i) for i in range(60)], "influencer": [u("influencer", i) for i in range(60)],
                      "macro": [u("macro-influencer", i) for i in range(40)]}
        self.base = {k: {x[0] for x in v} for k, v in self.cands.items()}
        fake = {"_coins": "coin", "_influencers": "influencer", "_macro": "macro"}
        for name, sec in fake.items():
            p = mock.patch.object(seoindex, name, lambda now, sec=sec: (list(self.cands[sec]), set(self.base[sec])))
            p.start()
            self.addCleanup(p.stop)
        for p in (mock.patch.object(seoindex, "_hubs", lambda now: [("/", "/hr", "1.0", None)]),
                  mock.patch.object(seoindex, "_editorial", lambda: {"blog": [], "glossary": [], "tools": []}),
                  mock.patch.object(seoindex, "tg_filtered", lambda now=None: {}),
                  mock.patch.object(seoindex, "_templates", lambda rows, ix: self.tpl(rows, ix)),
                  mock.patch.object(seoindex, "_drop_public_copies", lambda: None),
                  mock.patch.dict(os.environ, {"SEO_DB": self.db, "ANALYTICS_DB": self.an}),
                  mock.patch("builtins.print", lambda *a, **k: self.lines.append(" ".join(map(str, a))))):
            p.start()
            self.addCleanup(p.stop)
        self.lines = []
        self.t0 = 1_800_000_000
        seoindex.reset()
        self.addCleanup(seoindex.reset)

    def tpl(self, rows, indexed):
        coins_in = [r for r in rows.values() if r["section"] == "coin"]
        ok = [r["en"].rsplit("/", 1)[1] for r in sorted(coins_in, key=lambda r: r["rank"]) if r["en"] in indexed]
        return {"buy": ([(f"/how-to-buy/{s}", f"/hr/kako-kupiti/{s}", "0.5", None) for s in ok],
                        {f"/how-to-buy/x{i:03d}" for i in range(60)})}

    def run_day(self, day):
        return seoindex.ensure(now=self.t0 + day * D, db=self.db)

    def rows(self, sec=None):
        con = sqlite3.connect(self.db)
        try:
            return {r[0]: r[1] for r in con.execute("SELECT en, section FROM seo_core") if sec in (None, r[1])}
        finally:
            con.close()

    def gsc(self, day, imp_weeks, indexed=None, inspected=None, pages=()):
        """analytics.db as analytics/gsc writes it: daily rows (newest = day - 3), inspections, page impressions."""
        from analytics import gsc
        con = gsc.connect(self.an)
        con.execute("DELETE FROM gsc_daily")
        con.execute("DELETE FROM gsc_inspect")
        con.execute("DELETE FROM gsc_pages")
        today = dt.datetime.fromtimestamp(self.t0 + day * D, dt.timezone.utc).date()
        end = today - dt.timedelta(days=3)
        for w, total in enumerate(imp_weeks):
            for k in range(7):
                dd = end - dt.timedelta(days=w * 7 + k)
                con.execute("INSERT INTO gsc_daily VALUES (?,?,?,0,0)", (dd.isoformat(), total / 70, total / 7))
        for url in inspected or ():
            st = "Submitted and indexed" if url in (indexed or ()) else "Crawled - currently not indexed"
            con.execute("INSERT INTO gsc_inspect (url, ts, coverage_state) VALUES (?,?,?)", (BASE + url, 0, st))
        for page, imp, clicks in pages:
            con.execute("INSERT INTO gsc_pages VALUES (?,?,0,?,0)", (BASE + page, imp, clicks))
        con.commit()
        con.close()

    def test_seed_fills_each_section_to_its_cap(self):
        self.run_day(0)
        self.assertEqual(len(self.rows("coin")), 30)
        self.assertEqual(len(self.rows("influencer")), 30)
        self.assertEqual(len(self.rows("macro")), 20)
        self.assertIn("seo rast: stoji — nema podataka Search Consolea", self.lines)
        with mock.patch.dict(os.environ, {"SEO_COINS": "10"}):
            seoindex.reset()
            self.run_day(1)
        self.assertEqual(len(self.rows("coin")), 30)   # a lower cap removes nothing inside 30 days

    def test_stable_for_30_days_then_the_best(self):
        self.run_day(0)
        first = set(self.rows("coin"))
        self.cands["coin"].reverse()               # the ranking turns over
        for day in (1, 10, 29):
            self.run_day(day)
            self.assertEqual(set(self.rows("coin")), first, day)
        self.run_day(30)
        self.assertEqual(set(self.rows("coin")), {x[0] for x in self.cands["coin"][:30]})

    def test_a_page_that_is_gone_leaves_and_its_slot_is_refilled(self):
        self.run_day(0)
        gone = "/coin/x000"
        self.base["coin"].discard(gone)
        self.cands["coin"] = [x for x in self.cands["coin"] if x[0] != gone]
        self.run_day(3)
        now = set(self.rows("coin"))
        self.assertNotIn(gone, now)
        self.assertEqual(len(now), 30)
        self.assertIn("/coin/x030", now)

    def test_no_growth_without_fresh_data(self):
        self.run_day(0)
        self.gsc(7, (900, 500, 400), indexed=set(self.rows()), inspected=set(self.rows()))
        self.run_day(17)   # the newest Search Console day is 13 days old
        self.assertTrue(any(line.startswith("seo rast: stoji — podaci Search Consolea stari") for line in self.lines))
        self.assertEqual(len(self.rows()), 81)

    def test_healthy_growth_with_the_cap_and_the_spread(self):
        self.run_day(0)
        core = set(self.rows())
        coin_pages = [p for p, s in self.rows().items() if s == "coin"]
        self.gsc(7, (900, 600, 400), indexed=core, inspected=core,
                 pages=[(coin_pages[0], 300, 3), ("/influencer/x000", 100, 0)])   # coins earn the most, macro nothing
        self.run_day(7)
        line = [x for x in self.lines if x.startswith("seo rast:")][-1]
        self.assertIn("jezgra 81 (indeksirano 81 od 81 pregledanih, 100 %); impresije 7 d 900 (prije 600)", line)
        # 10 % of 81 -> 9 pages: coins (300 + 30) and influencers (100) by what they earn, macro nothing
        self.assertIn("dodano 9 (tokeni 7, influenceri 2, makro 0", line)
        self.assertEqual(len(self.rows()), 90)
        self.assertEqual(len(self.rows("coin")), 37)
        self.assertIn("/coin/x030", self.rows())                 # the next best candidates
        # the templates: only for coins whose own page is indexed
        buy = self.rows("buy")
        self.assertTrue(set(buy) <= {f"/how-to-buy/{p.rsplit('/', 1)[1]}" for p in core})
        # a week later: the weekly cap (SEO_GROW_MAX_WEEK) counts what the last 7 days added
        with mock.patch.dict(os.environ, {"SEO_GROW_MAX_WEEK": "12"}):
            seoindex.reset()
            self.gsc(14, (1200, 900, 600), indexed=set(self.rows()), inspected=set(self.rows()),
                     pages=[(coin_pages[0], 300, 3)])
            self.run_day(14)
        line = [x for x in self.lines if x.startswith("seo rast:")][-1]
        self.assertIn("dodano 9", line)                          # max(5, 10 % of 90) = 9 <= 12
        with mock.patch.dict(os.environ, {"SEO_GROW_MAX_WEEK": "4"}):
            seoindex.reset()
            self.gsc(21, (1500, 1200, 900), indexed=set(self.rows()), inspected=set(self.rows()))
            self.run_day(21)
        line = [x for x in self.lines if x.startswith("seo rast:")][-1]
        self.assertIn("dodano 4", line)
        with mock.patch.dict(os.environ, {"SEO_GROW_MAX_WEEK": "0"}):
            seoindex.reset()
            self.run_day(28)
        self.assertIn("seo rast: stoji — vlasnik je zaustavio rast (SEO_GROW_MAX_WEEK=0)", self.lines)

    def test_once_a_week(self):
        self.run_day(0)
        n = sum(x.startswith("seo rast:") for x in self.lines)
        for day in (1, 2, 6):
            self.run_day(day)
        self.assertEqual(sum(x.startswith("seo rast:") for x in self.lines), n)
        self.run_day(7)
        self.assertEqual(sum(x.startswith("seo rast:") for x in self.lines), n + 1)

    def test_pause_and_standstill(self):
        self.run_day(0)
        core = sorted(self.rows())
        self.gsc(7, (900, 600, 400), indexed=set(core[:30]), inspected=set(core))   # 37 %
        self.run_day(7)
        self.assertTrue(any("pauza: indeksirano ispod 40 %" in x for x in self.lines))
        self.gsc(14, (300, 600, 900), indexed=set(core), inspected=set(core))
        self.run_day(14)
        self.assertTrue(any("pauza: impresije padaju dva tjedna zaredom" in x for x in self.lines))
        self.gsc(21, (500, 600, 400), indexed=set(core[:45]), inspected=set(core))   # 56 %: no pause, no growth
        self.run_day(21)
        self.assertTrue(any("indeksirano ispod 60 %" in x for x in self.lines))
        self.gsc(28, (500, 600, 400), indexed=set(core), inspected=set(core))
        self.run_day(28)
        self.assertTrue(any("impresije nisu rasle" in x for x in self.lines))
        self.assertEqual(len(self.rows()), 81)                   # nothing added, nothing removed

    def test_templates_only_after_the_coin_page_is_indexed(self):
        self.run_day(0)
        core = set(self.rows())
        some = {"/coin/x001", "/coin/x002"}
        self.gsc(7, (900, 600, 400), indexed=(core - {p for p in core if p.startswith("/coin/")}) | some,
                 inspected=core, pages=[("/how-to-buy/x001", 0, 0)])
        with mock.patch.dict(os.environ, {"SEO_GROW_MAX_WEEK": "25"}):
            self.run_day(7)
        buy = set(self.rows("buy"))
        self.assertTrue(buy <= {"/how-to-buy/x001", "/how-to-buy/x002"}, buy)

    def test_nothing_grown_leaves_inside_30_days(self):
        self.run_day(0)
        core = set(self.rows())
        self.gsc(7, (900, 600, 400), indexed=core, inspected=core)
        self.run_day(7)
        grown = set(self.rows()) - core
        self.assertTrue(grown)
        self.cands["coin"].reverse()
        self.cands["influencer"].reverse()
        self.cands["macro"].reverse()
        for day in (8, 20, 36):
            self.run_day(day)
            self.assertTrue(grown <= set(self.rows()), day)


# ---------- Telegram -------------------------------------------------------------------------------------------------------

class Telegram(unittest.TestCase):
    def setUp(self):
        public._cache.clear()
        javniteret.forget()

    def test_filtered_list(self):
        got, known = seoindex.tg_channels()
        self.assertTrue(known)
        self.assertEqual(got, {"alpha_calls": 12, "Beta_Calls": 12, "gamma_calls": 15})
        code, en = html("/telegram-channels")
        self.assertEqual(code, 200)
        self.assertNotIn("noindex", head(en))
        self.assertEqual(re.findall(r'href="/telegram/([^"]+)"', en), ["Beta_Calls", "alpha_calls", "gamma_calls"])
        self.assertNotIn("cooking_tips", en)
        self.assertNotIn("thin_calls", en)
        self.assertIn("at least 10 clean measured calls per channel", en)
        self.assertIn("The 3 channels with the most followers, of 3 on the list.", en)
        _, hr = html("/hr/telegram-kanali")
        self.assertIn("najmanje 10 čistih izmjerenih poziva po kanalu", hr)
        with mock.patch.object(telegrampub, "HUB_MAX", 2):
            javniteret.forget()
            public._cache.clear()
            _, en2 = html("/telegram-channels")
        self.assertEqual(en2.count('href="/telegram/'), 2)
        self.assertEqual(telegrampub.HUB_MAX, int(os.environ.get("TG_HUB_MAX") or 200))

    def test_channel_pages_and_410(self):
        code, h = html("/telegram/alpha_calls")
        self.assertEqual(code, 200)
        self.assertIn('content="noindex,follow"', h)
        self.assertEqual(html("/hr/telegram/beta_calls")[0], 200)   # any case, as before
        sql = []
        real = sqlite3.connect

        def traced(*a, **k):
            con = real(*a, **k)
            sql.append(a)
            return con
        with mock.patch.object(sqlite3, "connect", traced):
            for path in ("/telegram/cooking_tips", "/hr/telegram/thin_calls", "/telegram/gone_calls", "/telegram/x1"):
                code, body, ctype = public.route(path)
                self.assertEqual((code, body, ctype), (410, public.GONE, "text/plain"), path)
        self.assertEqual(sql, [])                              # the answer comes from memory
        srv = Server()
        try:
            code, hd, body = srv.get("/telegram/cooking_tips")
            self.assertEqual(code, 410)
            self.assertEqual(hd.get("Cache-Control"), "public, max-age=86400")
            self.assertEqual(hd.get("X-Robots-Tag"), "noindex")
            self.assertLess(len(body), 50)
        finally:
            srv.close()

    def test_no_filtered_list(self):
        try:
            with mock.patch.object(seoindex, "tg_filtered", lambda now=None: {}), mock.patch("builtins.print"):
                con = sqlite3.connect(os.environ["SEO_DB"])
                con.execute("DELETE FROM seo_tg")
                con.commit()
                con.close()
                seoindex.reset()
                seoindex.ensure()
                public._cache.clear()
                javniteret.forget()
                code, h = html("/telegram-channels")
                self.assertEqual(code, 200)
                self.assertIn("noindex", head(h))
                self.assertIn("cannot be read right now", h)
                self.assertNotIn('href="/telegram/', h)
                self.assertNotIn("/telegram-channels<", public.sitemap())
                self.assertEqual(html("/telegram/alpha_calls")[0], 410)
                self.assertFalse(seoindex.indexable("/telegram-channels"))
        finally:
            fresh()


# ---------- robots.txt ------------------------------------------------------------------------------------------------------

def allowed(robots, path):
    """Google's rule: the longest matching Allow / Disallow wins ($ = end of the address)."""
    best, ok = -1, True
    for line in robots.splitlines():
        k, _, v = line.partition(":")
        v = v.strip()
        if k not in ("Allow", "Disallow") or not v:
            continue
        rx = re.escape(v.rstrip("$")).replace(r"\*", ".*") + ("$" if v.endswith("$") else "")
        if re.match(rx, path) and len(v) > best:
            best, ok = len(v), k == "Allow"
    return ok


class Robots(unittest.TestCase):
    def test_every_allow_line_opens_a_real_page_and_the_core_is_allowed(self):
        txt = public.robots()
        self.assertTrue(txt.rstrip().endswith(f"Sitemap: {BASE}/sitemap.xml"))
        examples = {"/static/landing/": "/static/landing/" + sorted(os.listdir(os.path.join(ROOT, "ui/static/landing")))[0],
                    "/influencer/": "/influencer/kol44", "/hr/influencer/": "/hr/influencer/kol44", "/coin/": "/coin/c1",
                    "/hr/coin/": "/hr/coin/c1", "/telegram/": "/telegram/alpha_calls",
                    "/hr/telegram/": "/hr/telegram/alpha_calls"}
        lines = [ln.split(": ", 1)[1] for ln in txt.splitlines() if ln.startswith("Allow: ")]
        srv = Server()
        bad = []
        try:
            for ln in lines:
                ex = examples.get(ln, dict(public.ROBOTS_ALLOW).get(ln) or ln.rstrip("$"))
                if ln in ("/img/t/", "/embed/", "/hr/embed/"):
                    continue   # token icons and the market embeds need network data (ui/tokenicons, ui/marketpub)
                code = srv.get(ex)[0]
                if code != 200:
                    bad.append((ln, ex, code))
        finally:
            srv.close()
        self.assertEqual(bad, [])
        for en, hr, _p, _m in seoindex.core_urls():
            for p in (en, hr):
                if p:
                    self.assertTrue(allowed(txt, p), p)
        for p in ("/pregled", "/kol", "/prijava", "/admin/export/x"):
            self.assertFalse(allowed(txt, p), p)
        for p in ("/how-to-buy/c1", "/telegram/cooking_tips", "/coin/c3"):   # noindex / 410: crawlable on purpose
            self.assertTrue(allowed(txt, p), p)

    def test_the_app_host_has_its_own(self):
        import run_ui
        srv = Server()
        try:
            with mock.patch.object(run_ui, "SITE_URL", BASE), mock.patch.object(run_ui, "APP_URL", "https://app.memesonar.app"):
                code, hd, body = srv.get("/robots.txt", "app.memesonar.app")
                self.assertEqual((code, body), (200, b"User-agent: *\nDisallow: /\n"))
                self.assertNotIn("Location", hd)
                code, hd, body = srv.get("/robots.txt", "memesonar.app")
                self.assertEqual(code, 200)
                self.assertIn(b"Sitemap: ", body)
                code, hd, _ = srv.get("/influencers", "app.memesonar.app")
                self.assertEqual((code, hd.get("Location")), (301, BASE + "/influencers"))
        finally:
            srv.close()


if __name__ == "__main__":
    unittest.main()
