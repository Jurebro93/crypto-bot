"""Search Console diagnosis (analytics/gsc.py days_lines / pages_lines / inspect_lines, ui/analitika.py
"Indeksiranost") without the network: fake searchAnalytics and URL Inspection answers, exact log line formats, the
daily cap and order, errors that must not break collect(), and no key / token / e-mail in any log line."""
import datetime as dt
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analytics import gsc  # noqa: E402

KEY = {"type": "service_account", "client_email": "memesonar-gsc@proj.iam.gserviceaccount.com",
       "private_key": "-----BEGIN PRIVATE KEY-----\nSECRETKEYBODY\n-----END PRIVATE KEY-----\n",
       "token_uri": gsc.TOKEN_URI}
TOKEN = "ya29.SECRET-TOKEN"
TODAY = dt.date(2026, 11, 20)
B = "https://memesonar.app"
ENV = {"GSC_SERVICE_ACCOUNT_JSON": json.dumps(KEY), "SITE_URL": B, "GSC_SITE": "", "GSC_INSPECT_DAY": "300"}
CUR = {B + "/": (500, 20), B + "/coin/bonk": (50, 2), B + "/hr/coin/bonk": (30, 1), B + "/telegram/abc": (10, 0)}
PREV = {B + "/": (600, 25), B + "/coin/bonk": (80, 3), B + "/coin/wif": (300, 9), B + "/hr/rjecnik/rug": (40, 1),
        B + "/telegram/abc": (20, 0), B + "/telegram/dead": (70, 0), B + "/x/other": (5, 0)}


def fake_query(start, end, dims=(), limit=1000, site_url=None):
    if dims == ("date",):
        out, d = [], start
        while d <= end:
            if d != TODAY - dt.timedelta(days=5):      # a day with no impressions has no row at all
                out.append({"keys": [str(d)], "clicks": 1, "impressions": 100, "ctr": 0.01, "position": 9.0})
            d += dt.timedelta(days=1)
        return out
    if dims == ("page",) and (end - start).days == 6:      # the week-over-week page comparison
        assert limit == 1000
        src = CUR if end == TODAY - dt.timedelta(days=gsc.LAG_DAYS + 1) else PREV
        return [{"keys": [k], "impressions": i, "clicks": c, "ctr": 0, "position": 5} for k, (i, c) in src.items()]
    return [{"keys": ["x"], "clicks": 1, "impressions": 2, "ctr": 0.5, "position": 3.0}]


STATES = {"/coin/wif": ("NEUTRAL", "Excluded by 'noindex' tag", "SUCCESSFUL"),
          "/telegram/dead": ("FAIL", "Server error (5xx)", "SERVER_ERROR"),
          "/hr/rjecnik/rug": ("NEUTRAL", "Crawled - currently not indexed", "SUCCESSFUL"),
          "/x/other": ("FAIL", "Blocked due to unauthorized request (401)", "ACCESS_DENIED")}


def fake_inspect(url):
    path = url[len(B):] or "/"
    v, st, f = STATES.get(path, ("PASS", "Submitted and indexed", "SUCCESSFUL"))
    return {"verdict": v, "coverageState": st, "pageFetchState": f, "robotsTxtState": "ALLOWED",
            "indexingState": "INDEXING_ALLOWED", "lastCrawlTime": "2026-11-18T10:00:00Z", "googleCanonical": url}


def http_error(code, body):
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(body.encode()))


class Base(unittest.TestCase):
    def setUp(self):
        self.db = os.path.join(tempfile.mkdtemp(), "analytics.db")
        self.env = mock.patch.dict(os.environ, ENV)
        self.env.start()
        self.hubs = mock.patch.object(gsc, "hub_urls", lambda: [B + "/", B + "/hr", B + "/influencers"])
        self.hubs.start()
        gsc.collect(self.db, TODAY, fake_query)

    def tearDown(self):
        self.hubs.stop()
        self.env.stop()

    def assertNoSecret(self, lines):
        for line in lines:
            for s in (KEY["client_email"], "SECRETKEYBODY", "PRIVATE KEY", TOKEN, "iam.gserviceaccount"):
                self.assertNotIn(s, line)


class DaysTest(Base):
    def test_format_and_throttle(self):
        lines = gsc.days_lines(self.db, TODAY)
        self.assertEqual(len(lines), 2)
        parts = lines[0].removeprefix("gsc dani: ").split("; ")
        self.assertTrue(lines[0].startswith("gsc dani: 2026-10-30 i=100 k=1; 2026-10-31 i=100 k=1; "))
        self.assertEqual(len(parts), 21)
        self.assertIn("2026-11-15 i=0 k=0", parts)        # missing day shown as zero
        self.assertEqual(parts[-1], "2026-11-19 i=100 k=1")
        self.assertEqual(lines[1], "gsc: zadnja 3 dana su nepotpuna (kašnjenje Googlea)")
        self.assertEqual(gsc.days_lines(self.db, TODAY), [])                         # unchanged
        self.assertEqual(gsc.days_lines(self.db, TODAY + dt.timedelta(days=1)), [])  # changed, but < 6 h
        with mock.patch.object(gsc.time, "time", return_value=gsc.time.time() + 7 * 3600):
            self.assertEqual(len(gsc.days_lines(self.db, TODAY + dt.timedelta(days=1))), 2)


class PagesTest(Base):
    def test_line_and_table(self):
        [line] = gsc.pages_lines(self.db, TODAY, fake_query)
        self.assertEqual(line, "gsc stranice: s impresijama zadnjih 7 d 4 (prije 7); izgubilo sve impresije 4; "
                               "po sekciji: /telegram/* 2→1 (i 90→10), /coin/* 2→2 (i 380→80), "
                               "/influencer/* 0→0 (i 0→0), /macro-influencer/* 0→0 (i 0→0), "
                               "/glossary/* 1→0 (i 40→0), /blog/* 0→0 (i 0→0), /how-to-buy/* 0→0 (i 0→0), "
                               "/rug-check/* 0→0 (i 0→0), naslovnica 1→1 (i 600→500), ostalo 1→0 (i 5→0)")
        con = gsc.connect(self.db)
        self.assertEqual(con.execute("SELECT imp_cur, imp_prev, clicks_cur, clicks_prev FROM gsc_pages WHERE page=?",
                                     (B + "/coin/bonk",)).fetchone(), (50, 80, 2, 3))
        self.assertEqual(con.execute("SELECT COUNT(*) FROM gsc_pages").fetchone()[0], 8)
        con.close()

    def test_sections(self):
        for u, s in (("/hr/telegram-kanali", "/telegram/*"), ("/hr/makro-influencer/a", "/macro-influencer/*"),
                     ("/hr/kako-kupiti/bonk", "/how-to-buy/*"), ("/hr/provjera/bonk", "/rug-check/*"),
                     ("/hr", "naslovnica"), ("/", "naslovnica"), ("/influencers", "/influencer/*"),
                     ("/best-crypto-tools", "ostalo")):
            self.assertEqual(gsc.section(B + u), s, u)

    def test_week_lag(self):
        cs, ce, ps, pe = gsc.week_periods(TODAY)
        self.assertEqual(ce, TODAY - dt.timedelta(days=gsc.LAG_DAYS + 1))
        self.assertEqual(((ce - cs).days, (pe - ps).days, (cs - pe).days), (6, 6, 1))


class InspectTest(Base):
    def setUp(self):
        super().setUp()
        gsc.pages_lines(self.db, TODAY, fake_query)
        self.sm = [B + "/sm/%d" % i for i in range(500)] + [B + "/coin/bonk"]
        self.calls, self.sleeps = [], []

    def call(self, url):
        self.calls.append(url)
        return fake_inspect(url)

    def run_(self, call=None):
        return gsc.inspect_lines(self.db, TODAY, call or self.call, self.sleeps.append, self.sm)

    def test_order_cap_lines(self):
        with mock.patch.dict(os.environ, {"GSC_INSPECT_DAY": "12"}):
            lines = self.run_()
        self.assertEqual(self.calls[:3], [B + "/", B + "/hr", B + "/influencers"])
        self.assertEqual(self.calls[3:7], [B + "/coin/wif", B + "/telegram/dead", B + "/hr/rjecnik/rug", B + "/x/other"])
        self.assertEqual(self.calls[7:], [B + "/sm/%d" % i for i in range(5)])
        self.assertEqual(len(self.calls), 12)
        self.assertEqual(self.sleeps, [1.0] * 11)       # ~1 per second
        c = " (crawl 2026-11-18)"
        self.assertEqual(lines, [
            "gsc indeks: pregledano 12; Submitted and indexed 8, Blocked due to unauthorized request (401) 1, "
            "Crawled - currently not indexed 1, Excluded by 'noindex' tag 1, Server error (5xx) 1; "
            "ukupno u bazi 12, sitemap još nepregledano 496",
            "gsc indeks primjeri Submitted and indexed: " + ", ".join(
                p + c for p in ["/", "/hr", "/influencers"] + ["/sm/%d" % i for i in range(5)]),
            "gsc indeks primjeri Blocked due to unauthorized request (401): /x/other" + c,
            "gsc indeks primjeri Crawled - currently not indexed: /hr/rjecnik/rug" + c,
            "gsc indeks primjeri Excluded by 'noindex' tag: /coin/wif" + c,
            "gsc indeks primjeri Server error (5xx): /telegram/dead" + c,
            "gsc crawl: od 12 pregledanih zadnji crawl zadnjih 3 d 12, 4-7 d 0, 8-14 d 0, starije 0, nikad 0; "
            "najnoviji crawl 2026-11-18",
            "gsc indeks po sekciji: /telegram/* 0/0/0, /coin/* 0/0/0, /influencer/* 1/0/0, /macro-influencer/* 0/0/0, "
            "/glossary/* 0/1/0, /blog/* 0/0/0, /how-to-buy/* 0/0/0, /rug-check/* 0/0/0, naslovnica 2/0/0, ostalo 5/0/0"])
        # cap reached for today: nothing more
        self.calls.clear()
        with mock.patch.dict(os.environ, {"GSC_INSPECT_DAY": "12"}):
            self.assertEqual(self.run_(), [])
        self.assertEqual(self.calls, [])
        # next day: rotation continues with sitemap URLs never inspected (inspected ones are < 20 h old)
        with mock.patch.dict(os.environ, {"GSC_INSPECT_DAY": "3"}):
            gsc.inspect_lines(self.db, TODAY + dt.timedelta(days=1), self.call, self.sleeps.append, self.sm)
        self.assertEqual(self.calls, [B + "/sm/5", B + "/sm/6", B + "/sm/7"])
        con = gsc.connect(self.db)
        row = con.execute("SELECT verdict, coverage_state, page_fetch_state, last_crawl FROM gsc_inspect WHERE url=?",
                          (B + "/telegram/dead",)).fetchone()
        self.assertEqual(row, ("FAIL", "Server error (5xx)", "SERVER_ERROR", "2026-11-18T10:00:00Z"))
        con.close()

    def test_examples_capped_at_20(self):
        sm = [B + "/blog/p%d" % i for i in range(30)]
        lines = gsc.inspect_lines(self.db, TODAY, lambda u: {"verdict": "NEUTRAL", "coverageState": "Page with redirect",
                                                             "pageFetchState": "SUCCESSFUL"}, lambda s: None, sm)
        ex = [x for x in lines if x.startswith("gsc indeks primjeri Page with redirect: ")][0]
        self.assertEqual(len(ex.split(": ", 1)[1].split(", ")), 20)
        self.assertTrue(ex.endswith("/blog/p12 (crawl –)"))

    def test_crawl_buckets_and_sections(self):
        con = gsc.connect(self.db)
        rows = [("/blog/a", "PASS", "Submitted and indexed", "2026-11-19T01:00:00Z"),
                ("/blog/b", "NEUTRAL", gsc.CRAWLED_NOT, "2026-11-14T01:00:00Z"),
                ("/hr/blog/c", "NEUTRAL", gsc.CRAWLED_NOT, "2026-11-10T01:00:00Z"),
                ("/coin/x", "NEUTRAL", gsc.CRAWLED_NOT, "2026-10-01T01:00:00Z"),
                ("/coin/y", "NEUTRAL", gsc.UNKNOWN, ""),
                ("/hr/coin/z", "NEUTRAL", gsc.UNKNOWN, None)]
        con.executemany("INSERT INTO gsc_inspect (url, ts, verdict, coverage_state, last_crawl) VALUES (?,1,?,?,?)",
                        [(B + u, v, st, lc) for u, v, st, lc in rows])
        con.commit()
        self.assertEqual(gsc.stats_lines(con, TODAY), [
            "gsc crawl: od 6 pregledanih zadnji crawl zadnjih 3 d 1, 4-7 d 1, 8-14 d 1, starije 1, nikad 2; "
            "najnoviji crawl 2026-11-19",
            "gsc indeks po sekciji: /telegram/* 0/0/0, /coin/* 0/1/2, /influencer/* 0/0/0, /macro-influencer/* 0/0/0, "
            "/glossary/* 0/0/0, /blog/* 1/2/0, /how-to-buy/* 0/0/0, /rug-check/* 0/0/0, naslovnica 0/0/0, ostalo 0/0/0"])
        con.close()

    def test_sitemap_lines(self):
        api = {"sitemap": [{"path": B + "/sitemap.xml", "lastDownloaded": "2026-11-11T05:06:07.000Z",
                            "isPending": False, "errors": "0", "warnings": "2",
                            "contents": [{"type": "web", "submitted": "242", "indexed": "0"}]},
                           {"path": B + "/sitemap-blog.xml", "isPending": True}]}
        seen = {}

        def http(url, body=None):
            seen["url"] = url
            return api
        with mock.patch.object(gsc, "_http", http):
            lines = gsc.sitemap_lines(self.db, TODAY)
        self.assertEqual(seen["url"], gsc.API + "/sites/sc-domain%3Amemesonar.app/sitemaps")
        self.assertEqual(lines, [
            "gsc sitemap: https://memesonar.app/sitemap.xml zadnje preuzimanje 2026-11-11, obrada ok, greške 0, "
            "upozorenja 2, poslano 242",
            "gsc sitemap: https://memesonar.app/sitemap-blog.xml zadnje preuzimanje –, obrada isPending, greške 0, "
            "upozorenja 0, poslano 0"])
        self.assertEqual(gsc.sitemap_lines(self.db, TODAY, lambda: []), [])          # once a day
        self.assertEqual(gsc.sitemap_lines(self.db, TODAY + dt.timedelta(days=1), lambda: []),
                         ["gsc sitemap: nijedan sitemap nije poslan u Search Console"])

        def boom():
            raise gsc.GscError("Google kaže da previše pitamo (limit); idući pokušaj za nekoliko sati.")
        lines = gsc.sitemap_lines(self.db, TODAY + dt.timedelta(days=2), boom)
        self.assertEqual(lines, ["gsc sitemap: Google kaže da previše pitamo (limit); idući pokušaj za nekoliko sati."])
        self.assertNoSecret(lines)

    def test_default_cap_300(self):
        with mock.patch.dict(os.environ, {"GSC_INSPECT_DAY": ""}):
            os.environ.pop("GSC_INSPECT_DAY")
            self.run_()
        self.assertEqual(len(self.calls), 300)

    def test_errors_one_line_no_crash(self):
        cases = [(http_error(403, '{"error": {"status": "PERMISSION_DENIED", "message": "SERVICE_DISABLED for '
                                  'memesonar-gsc@proj.iam.gserviceaccount.com"}}'), "nije uključen"),
                 (http_error(403, '{"error": "User memesonar-gsc@proj.iam.gserviceaccount.com no permission"}'),
                  "nema dozvolu"),
                 (http_error(429, "quota"), "previše pitamo"),
                 (urllib.error.URLError("timed out"), "ne javlja")]
        for exc, want in cases:
            def boom(*a, **k):
                raise exc
            with mock.patch.object(gsc, "_http", boom), mock.patch.object(gsc, "token", lambda *a: TOKEN):
                lines = gsc.diagnose(self.db, TODAY + dt.timedelta(days=len(want)), fake_query,
                                     sleep=lambda s: None, sitemap=self.sm)
                self.assertTrue(any(want in x for x in lines), (want, lines))
                ln = [x for x in lines if x.startswith("gsc indeks:")]
                self.assertEqual(len(ln), 1, lines)
                self.assertNoSecret(lines)
                con = gsc.connect(self.db)
                self.assertIn(want, gsc.meta(con)["inspect_error"])
                con.close()
            # collect() keeps working afterwards
            self.assertGreater(gsc.collect(self.db, TODAY, fake_query), 10)

    def test_inspect_url_body_and_token_failure(self):
        seen = {}

        def http(url, body=None):
            seen.update(url=url, body=body)
            return {"inspectionResult": {"indexStatusResult": {"verdict": "PASS", "coverageState": "Submitted and indexed"}}}
        with mock.patch.object(gsc, "_http", http):
            self.assertEqual(gsc.inspect_url(B + "/")["verdict"], "PASS")
        self.assertEqual(seen["url"], "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect")
        self.assertEqual(seen["body"], {"inspectionUrl": B + "/", "siteUrl": "sc-domain:memesonar.app"})

        def tok(*a):
            raise gsc.GscError("Google prijava nije uspjela (HTTP 400).")
        with mock.patch.object(gsc, "token", tok):
            with self.assertRaises(gsc.InspectStop):
                gsc.inspect_url(B + "/")

    def test_unexpected_exception_contained(self):
        def bad(url):
            raise RuntimeError("secret " + TOKEN)
        lines = gsc.diagnose(self.db, TODAY, fake_query, bad, lambda s: None, self.sm, lambda: [])
        self.assertIn("gsc indeks: neočekivana greška RuntimeError", lines)
        self.assertNoSecret(lines)

    def test_full_diagnose_no_secret_and_collect_403_message(self):
        lines = gsc.diagnose(self.db, TODAY, fake_query, fake_inspect, lambda s: None, self.sm, lambda: [])
        for p in ("gsc dani: ", "gsc stranice: ", "gsc indeks: pregledano ", "gsc indeks primjeri ", "gsc crawl: od ",
                  "gsc indeks po sekciji: ", "gsc sitemap: "):
            self.assertTrue(any(x.startswith(p) for x in lines), p)
        self.assertNoSecret(lines)

        def http(url, body=None):
            raise http_error(403, "User memesonar-gsc@proj.iam.gserviceaccount.com lacks permission")
        with mock.patch.object(gsc, "_http", http), self.assertRaises(gsc.GscError) as cm:
            gsc.query(TODAY, TODAY)
        self.assertNoSecret([str(cm.exception)])

    def test_page_section(self):
        from ui import analitika
        gsc.inspect_lines(self.db, TODAY, fake_inspect, lambda s: None, self.sm[:5])
        gsc.sitemap_lines(self.db, TODAY, lambda: [])
        con = gsc.connect(self.db)
        gsc._set(con, sm_urls=json.dumps(self.sm[:5]))
        con.commit()
        con.close()
        with mock.patch.object(gsc, "DB", self.db), mock.patch.object(gsc.dt, "date", wraps=dt.date) as d:
            d.today.return_value = TODAY
            _, body = analitika.page({})
        sec = body.split("<h3>Indeksiranost</h3>")[1].split("<h3>Zemlje</h3>")[0]
        for s in ("Submitted and indexed", "Server error (5xx)", "Izgubile sve prikaze", "/telegram/dead", "/coin/wif",
                  "Nisu u indeksu", "SERVER_ERROR", "2026-11-18", "pregledano 12",
                  "Zadnji crawl: zadnjih 3 d <b>12</b>", "Crawled, nije u indeksu", "još nepregledano 0 od 5",
                  "Sitemap u Search Consoleu", "Nijedan sitemap nije poslan"):
            self.assertIn(s, sec, s)
        self.assertLess(sec.index("/coin/wif"), sec.index("/telegram/dead"))   # lost: most impressions first


if __name__ == "__main__":
    unittest.main()
