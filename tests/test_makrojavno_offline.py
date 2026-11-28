"""15.11. (vlasnik: "Možeš ti odmah objaviti te stranice javno i staviti ih za sve korisnike aplikacije pod
influencere, makroinfluencer i tab. Dodati da sve bude lijepo, uredno, pregledno. I onda kako budeš punio podatke o
makroinfluencerima na dnevnoj bazi, osvježavati i stranice koje vide korisnici i Google."), offline:

  - the owner order turns the switch makroinf_javno live once, in his name; he can turn it off and it stays off
  - public pages: 404 while off; on: the hub and every profile 200, the hub indexable with hreflang, canonical and
    JSON-LD; since 15.11. navečer ("Neka Google sve indeksira") profiles under 10 episodes are indexable too (with the
    label "still collecting evidence") and the sitemap lists every profile, lastmod = the newest score's day; robots
    and the public menu carry the hub only while on
  - the stance (and the newest calls) fresh in the app, 7 days late on the public pages
  - after a scoring the cached public pages, the sitemap and the app tab are dropped (makroinf/web.sync); kv "javno"
    after every scoring; the night run logs "makroinf: javne stranice osvježene (N računa, M u sitemapu)"
  - the "Makro" tab on Influenceri (/kol) and /kol-makro/... for a normal logged-in user (role osnovni)
  - no keys, env names, internal services, costs, wallet / token addresses in any of these views

    python3 -m unittest tests.test_makrojavno_offline
"""
import importlib
import os
import re
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from makroinf import prices, run, store, web  # noqa: E402
from makroinf import public as mpub  # noqa: E402
from trade import settings  # noqa: E402
from ui import assistnotes  # noqa: E402
from tests.seo_kandidati import setUpModule, tearDownModule  # noqa: E402,F401   # 28.11.: the candidates, as before the core

D = 86400
NOW = int(time.time())
FORBIDDEN = ("twitterapi", "openai", "gpt-", "api key", "api_key", "_KEY", "MAKROINF_DB", "DATA_DIR", "makroinf.db",
             "render", "coingecko", "trošak", "cost", " $", "usd", "wallet", "novčanik", "SECRET-TEXT", "skriva")
ADDRESS = re.compile(r"(?<![\w/])[1-9A-HJ-NP-Za-km-z]{32,44}(?![\w])")


def rising(n=330, start=30_000.0, step=0.01, end=NOW):
    out, p = [], start
    for k in range(n, -1, -1):
        p *= 1 + step + (0.004 if k % 2 else -0.004)
        out.append((end // D * D - k * D, p))
    return out


def main_of(html):
    return html.split("<main", 1)[1].split("</main>", 1)[0]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = os.path.join(self.tmp.name, "makroinf.db")
        self.tdb = os.path.join(self.tmp.name, "trade.db")
        for p in (mock.patch.dict(os.environ, {"MAKROINF_DB": self.db, "RENDER_EXTERNAL_URL": "https://example.com",
                                                "KOL_DB": os.path.join(self.tmp.name, "kol.db")}),
                  mock.patch("usage.meter.record"), mock.patch.object(settings, "DB", self.tdb),
                  mock.patch.dict(prices.FETCH, {}, clear=True), mock.patch.object(web, "STAMP_S", 0)):
            p.start()
            self.addCleanup(p.stop)
        self.tcon = settings.connect(self.tdb)
        self.addCleanup(self.tcon.close)
        settings._FLAG_CACHE.clear()
        self.addCleanup(settings._FLAG_CACHE.clear)
        from ui import public
        self.public = public
        public._cache.clear()
        self.addCleanup(public._cache.clear)
        web._FRAG.clear()
        web._SEEN["v"] = None
        self.addCleanup(web._FRAG.clear)
        self.con = store.connect(self.db)
        self.addCleanup(self.con.close)
        self.fixtures()

    def fixtures(self):
        c = self.con
        c.executemany("INSERT INTO px VALUES (?,?,?,?)", [("bitcoin", "d", t, p) for t, p in rising()])
        c.execute("INSERT INTO accounts (handle, name, category, status) VALUES ('MacroMan', 'Macro Man', 'makro', "
                  "'aktivan')")
        c.execute("INSERT INTO accounts (handle, name, category, status) VALUES ('SmallFry', 'Small Fry', 'ta', 'aktivan')")
        for k in range(14):   # 15 days apart: each call its own episode, all measured
            self.call(100 + k, "MacroMan", NOW - (260 - 15 * k) * D, "up" if k % 4 else "down")
        for k in range(3):
            self.call(200 + k, "SmallFry", NOW - (200 - 20 * k) * D, "up")
        # the stance: down 10 days ago (in force 7 days ago), up 2 days ago (in force now)
        self.call(300, "MacroMan", NOW - 10 * D, "down", horizon=7)
        self.call(301, "MacroMan", NOW - 2 * D, "up", horizon=7)
        c.execute("INSERT INTO deletions (id, handle, base_ts, stage, state) VALUES ('100', 'MacroMan', 1, 1, "
                  "'confirmed_deleted')")
        for k in range(1, 15):   # the index of the most accurate, one row a day (the krug writes it)
            c.execute("INSERT OR REPLACE INTO index_d VALUES (?,?,?,?,?,?,?)",
                      ((NOW - k * D) // D * D, "BTC", "prospektivno", "top", -0.6, 4, None))
        c.commit()
        run.score_all(c, NOW, log=lambda *_: None)

    def call(self, i, h, ts, direction, horizon=None, avail=None):
        self.con.execute("INSERT INTO tweets (id, handle, ts, text, fetched_ts, kw, macro) VALUES (?,?,?,?,?,1,1)",
                         (str(i), h, ts, "SECRET-TEXT btc", ts + 1800))
        self.con.execute("INSERT INTO calls (id, asset, handle, ts, avail_ts, direction, conditional, confidence, promo, "
                         "unclear, withdraws, horizon_days) VALUES (?, 'BTC', ?, ?, ?, ?, 0, 'medium', 0, 0, 0, ?)",
                         (str(i), h, ts, avail or ts + 1800, direction, horizon))

    def live(self):
        with mock.patch.object(assistnotes, "OWNER_FLAG_ORDERS",
                               tuple(o for o in assistnotes.OWNER_FLAG_ORDERS if o[0] == settings.MAKROINF_JAVNO)):
            done = assistnotes.owner_flag_orders(self.tcon)
        settings._FLAG_CACHE.clear()
        return done

    def get(self, path):
        code, raw, _ct = self.public.route(path)
        return code, raw.decode()

    def clean(self, html, what):
        for bad in FORBIDDEN:
            self.assertNotIn(bad.lower(), html.lower(), f"{what}: {bad}")
        self.assertIsNone(ADDRESS.search(html), what)


class OwnerOrder(Base):
    def test_the_order_publishes_once_in_his_name(self):
        self.assertIn((settings.MAKROINF_JAVNO, "live"), [o[:2] for o in assistnotes.OWNER_FLAG_ORDERS])
        self.assertIn("Možeš ti odmah objaviti", dict((n, w) for n, _m, w in assistnotes.OWNER_FLAG_ORDERS)
                      [settings.MAKROINF_JAVNO])
        self.assertFalse(web.on())
        self.assertEqual(self.live(), ["zastavica makroinf_javno: off → live"])
        st = settings.flag_state(self.tcon)[settings.MAKROINF_JAVNO]
        self.assertEqual((st["mode"], st["who"]), ("live", settings.owner()))
        self.assertTrue(web.on())
        self.assertEqual(self.live(), [])                                            # once
        settings.set_flag(self.tcon, settings.MAKROINF_JAVNO, "off", "Jure")           # he turns it off ...
        self.assertEqual(self.live(), [])                                            # ... and it stays off
        self.assertFalse(web.on())
        with self.assertRaises(ValueError):                                           # nobody else publishes
            settings.set_flag(self.tcon, settings.MAKROINF_JAVNO, "live", "neko_drugi")


class Public(Base):
    PATHS = ("/macro-influencers", "/hr/makro-influenceri", "/macro-influencer/MacroMan", "/hr/makro-influencer/MacroMan",
             "/macro-influencer/SmallFry", "/hr/makro-influencer/SmallFry")

    def test_off_404_on_200(self):
        for p in self.PATHS:
            self.assertEqual(self.get(p)[0], 404, p)
        self.assertNotIn("macro-influencer", self.get("/sitemap.xml")[1])
        self.assertNotIn("macro-influencer", self.public.robots())
        self.assertNotIn("/macro-influencers", self.public.nav_links("en") + self.public._foot_links("en"))
        self.live()
        for p in self.PATHS:
            self.assertEqual(self.get(p)[0], 200, p)
        self.assertEqual(self.get("/macro-influencer/Nobody")[0], 404)
        self.assertIn("Allow: /macro-influencer", self.public.robots())
        # the menu: the hub right after the influencer ranking, in both languages and in the footer
        nav = self.public.nav_links("en")
        self.assertIn("/macro-influencers", nav)
        self.assertLess(nav.index("href=/influencers>"), nav.index("href=/macro-influencers>"))
        self.assertIn("/hr/makro-influenceri", self.public.nav_links("hr") + self.public._foot_links("hr"))

    def test_hub_and_profiles_seo(self):
        self.live()
        hub = self.get("/macro-influencers")[1]
        self.assertNotIn("noindex", hub)
        self.assertIn('<link rel=canonical href="https://example.com/macro-influencers">', hub)
        self.assertIn('hreflang=hr href="https://example.com/hr/makro-influenceri"', hub)
        self.assertIn('"@type": "CollectionPage"', hub)
        self.assertIn("/macro-influencer/MacroMan", hub)
        self.assertIn("/macro-influencer/SmallFry", main_of(hub))   # the small account is listed, without a rank
        self.assertIn("Still collecting evidence", hub)
        self.assertIn("id=how-we-measure", hub)
        rich = self.get("/macro-influencer/MacroMan")[1]
        self.assertNotIn("noindex", rich)
        self.assertIn('"@type": "ProfilePage"', rich)
        self.assertIn("later unavailable", rich)                    # the deleted post: no link, neutral words
        self.assertNotIn("/status/100\"", rich)
        self.assertIn("https://x.com/MacroMan/status/113", rich)    # the others link to the original
        small = self.get("/macro-influencer/SmallFry")[1]
        # 23.11. (SEO, ui/seoindex): under 10 episodes the page is published with the honest label, but noindex,follow
        self.assertIn('content="noindex,follow"', small.split("</head>")[0])
        self.assertIn("still collecting evidence", small)
        hr = self.get("/hr/makro-influencer/MacroMan")[1]
        self.assertIn("naknadno nedostupno", hr)
        for p in self.PATHS:
            self.clean(main_of(self.get(p)[1]), p)
        sm = self.get("/sitemap.xml")[1]
        day = time.strftime("%Y-%m-%d", time.gmtime(NOW))
        self.assertIn("/macro-influencer/MacroMan</loc>", sm)
        self.assertIn("/hr/makro-influencer/MacroMan</loc>", sm)
        self.assertNotIn("/macro-influencer/SmallFry</loc>", sm)     # 23.11.: under 10 episodes: not in the core
        self.assertRegex(sm, r"/macro-influencers</loc><lastmod>" + day)
        self.assertEqual([u[0] for u in mpub.urls()], ["/macro-influencers", "/macro-influencer/MacroMan",
                                                       "/macro-influencer/SmallFry"])
        self.assertTrue(all(u[3] == day for u in mpub.urls()))

    def test_stance_fresh_in_the_app_delayed_on_public_pages(self):
        self.live()
        fresh = {r["handle"]: r["stav"]["dir"] for r in web.view(True)["ranked"]}
        late = {r["handle"]: r["stav"]["dir"] for r in web.view(False)["ranked"]}
        self.assertEqual((fresh["MacroMan"], late["MacroMan"]), ("up", "down"))
        tab = web.tab_html()
        self.assertIn("↑ gore", tab)
        self.assertNotIn("↓ dolje", tab.split("MacroMan", 1)[1].split("mi-r", 1)[0])
        self.assertIn("od " + time.strftime("%d.%m.", time.gmtime(NOW - 2 * D)), tab)
        hub_hr = self.get("/hr/makro-influenceri")[1]
        rank = main_of(hub_hr).split("<table class=mr>", 1)[1]
        row = rank.split("/hr/makro-influencer/MacroMan", 1)[1].split("</tr>", 1)[0]
        self.assertIn("↓ dolje", row)
        self.assertNotIn("↑ gore", row)
        # the newest call: in the app profile, not on the public page (older than 7 days only)
        _t, app = web.profile_page("MacroMan")
        self.assertIn("/status/301", app)
        self.assertNotIn("/status/301", self.get("/macro-influencer/MacroMan")[1])
        self.assertIn("/status/113", self.get("/macro-influencer/MacroMan")[1])
        # the consensus: the newest row in the app, the one at least 7 days old on the public page
        self.assertEqual(web.index_btc(True)["day"], (NOW // D) * D)
        self.assertLessEqual(web.index_btc(False)["day"], (NOW - 7 * D) // D * D)
        self.clean(tab, "tab")
        self.clean(app, "app profile")

    def test_cache_dropped_after_a_scoring(self):
        self.live()
        self.assertNotIn("/macro-influencer/SmallFry</loc>", self.get("/sitemap.xml")[1])   # still collecting evidence
        hub = self.get("/hr/makro-influenceri")[1]
        self.assertIn("Rangirani računi · 1", hub)
        tab = web.tab_html()
        self.assertIn("Najtočniji · 1", tab)
        from ui import pagecache
        with pagecache._lock:
            pagecache._store[("/kol-makro/MacroMan", "", None)] = (time.time(), 200, None, b"")
            pagecache._store[("/pregled", "", None)] = (time.time(), 200, None, b"")
        self.addCleanup(pagecache.clear)
        # new posts are classified and the light scoring runs (krug, every 30 min): SmallFry reaches 10 episodes
        for j in range(9):   # 15 days apart, the first 20 days after the last one: 12 episodes
            self.call(210 + j, "SmallFry", NOW - (140 - 15 * j) * D, "up")
        self.con.commit()
        self.assertEqual(self.get("/hr/makro-influenceri")[1], hub)    # same scoring: the cached copy
        s = run.score_all(self.con, NOW + 60, log=lambda *_: None)
        self.assertEqual(s["enough"], 2)
        self.assertEqual(store.kv_json(self.con, "javno")["sitemap"], 2)
        self.assertIn("Rangirani računi · 2", self.get("/hr/makro-influenceri")[1])
        self.assertRegex(self.get("/sitemap.xml")[1], r"/macro-influencer/SmallFry</loc><lastmod>[\d-]+</lastmod>"
                                                      r"<priority>0\.6<")   # ranked now: in the core at once (cap 20)
        self.assertIn("Najtočniji · 2", web.tab_html())
        with pagecache._lock:
            keys = set(pagecache._store)
        self.assertNotIn(("/kol-makro/MacroMan", "", None), keys)       # the in-app pages go too ...
        self.assertIn(("/pregled", "", None), keys)                     # ... nothing else of the app
        # the owner turns the switch off: the pages are gone at once (not after the 15-min page cache)
        settings.set_flag(self.tcon, settings.MAKROINF_JAVNO, "off", "Jure")
        settings._FLAG_CACHE.clear()
        self.assertEqual(self.get("/hr/makro-influenceri")[0], 404)
        self.assertNotIn("macro-influencer", self.get("/sitemap.xml")[1])

    def test_night_run_logs_the_refresh(self):
        self.live()
        self.con.close()
        logs = []
        with mock.patch("makroinf.report.write"):
            s = run.noc(NOW + 120, log=logs.append, path=self.db, gap_h=0)
        self.assertIsNotNone(s)
        self.assertIn("makroinf: javne stranice osvježene (2 računa, 2 u sitemapu)", logs)
        self.con = store.connect(self.db)
        self.assertEqual(store.kv_json(self.con, "javno")["ts"], NOW + 120)


class App(Base):
    def test_the_tab_on_influenceri(self):
        from kol import store as kstore
        from ui import kol
        kp = os.path.join(self.tmp.name, "kol.db")
        kstore.connect(kp).close()
        with mock.patch.object(kstore, "DB", kp), mock.patch("ui.kolsummary.verdict_stats", lambda *a, **k: {}), \
                mock.patch.object(kol, "rang_pane", lambda now=None: ""):
            title, html = kol.page({})
        self.assertEqual(title, "Influenceri")
        self.assertIn('<a href="#makro" class="on" aria-current="page">Makro</a>', html)   # 19.11.: first and open
        self.assertIn('id=makro', html)
        for long_, short in (("Za kopiranje", "Kopiranje"), ("Upravo zvali", "Pozivi")):
            self.assertIn(f"<span class=tl>{long_}</span><span class=ts>{short}</span>", html)
        self.assertIn("hs==='makro'", html)
        tab = web.tab_html()
        self.assertIn("Konsenzus najtočnijih o BTC-u", tab)
        self.assertIn("Kako mjerimo", tab)
        self.assertIn("nedovoljno dokaza", tab)
        self.assertIn('href=\'/kol-makro/MacroMan\'', tab)
        self.assertNotIn("/hr/makro-influenceri", tab)                  # the switch is off: no public link
        self.live()
        web.sync()
        self.assertIn("/hr/makro-influenceri#kako-mjerimo", web.tab_html())

    def test_routes_for_a_normal_user(self):
        env = {"DATA_DIR": self.tmp.name, "UI_USERS": "Ivan,Jure", "UI_PASS_IVAN": "ivanpw", "UI_PASS_JURE": "jurepw",
               "UI_PASSWORD": "", "TRADE_OWNER": "Jure"}
        old = {k: os.environ.get(k) for k in list(env) + ["SITE_URL", "APP_URL", "UI_ADMINS"]}
        os.environ.update(env)
        for k in ("SITE_URL", "APP_URL", "UI_ADMINS"):
            os.environ.pop(k, None)

        def restore():
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            import run_ui as ru
            importlib.reload(ru)   # the module reads the env at import: back to the suite's own
        self.addCleanup(restore)
        from league import profiles, roles, store as lstore
        p = mock.patch.object(lstore, "DB", os.path.join(self.tmp.name, "league.db"))
        p.start()
        self.addCleanup(p.stop)
        profiles.reset_cache()
        roles.reset_cache()
        self.addCleanup(roles.reset_cache)
        self.addCleanup(profiles.reset_cache)
        import run_ui
        importlib.reload(run_ui)
        srv = run_ui.ThreadingHTTPServer(("127.0.0.1", 0), run_ui.Handler)
        srv.verbose = False
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        base = f"http://127.0.0.1:{srv.server_address[1]}"

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a):
                return None
        op = urllib.request.build_opener(NoRedirect)

        def call(path, data=None, cookie=""):
            req = urllib.request.Request(base + path, headers={"Cookie": cookie} if cookie else {},
                                         data=urllib.parse.urlencode(data).encode() if data else None)
            try:
                r = op.open(req)
            except urllib.error.HTTPError as e:
                r = e
            return r.code, r.headers, r.read().decode("utf-8", "replace")
        code, hdr, _ = call("/prijava", {"name": "Ivan", "pw": "ivanpw", "next": "/kol"})
        self.assertEqual(code, 303)
        ivan = hdr["Set-Cookie"].split(";")[0]
        self.assertEqual(roles.role("Ivan"), "osnovni")
        self.assertEqual(call("/kol-makro/lista")[0], 401)                          # guests: the login
        code, _h, frag = call("/kol-makro/lista", cookie=ivan)
        self.assertEqual(code, 200)
        self.assertIn("@MacroMan", frag)
        self.assertFalse(frag.lstrip().lower().startswith("<!doctype"))              # a fragment for the tab
        code, _h, page = call("/kol-makro/MacroMan", cookie=ivan)
        self.assertEqual(code, 200)
        self.assertIn("Prediktivna kvaliteta", page)
        self.assertIn("/status/301", page)                                           # fresh for members
        self.assertEqual(call("/kol-makro/Nobody", cookie=ivan)[0], 404)
        self.assertEqual(call("/kol-makro", cookie=ivan)[0], 200)
        self.assertEqual(call("/macro-influencers")[0], 404)                         # switch off
        self.live()
        code, hdr, hub = call("/macro-influencers")
        self.assertEqual(code, 200)
        self.assertNotIn("noindex", hdr.get("X-Robots-Tag") or "")
        code, hdr, _ = call("/macro-influencer/SmallFry")
        self.assertEqual(code, 200)


if __name__ == "__main__":
    unittest.main()
