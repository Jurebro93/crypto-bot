"""28.11. (vlasnik, poslovni plan): the data-product homepage, prices, the free influencer check, the methodology page,
the sign-up forms and the consent-gated GA4 / GTM tag. No network.

    python3 -m unittest tests.test_naslovnica_offline
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from league import roles, store  # noqa: E402
from ui import cijene, landing, metodologija, naslovnica as N, provjeri, public  # noqa: E402
from tests.test_skrivanje_offline import INTERNAL, RECIPE  # noqa: E402

NOW = int(time.time())
BANNED = ("Helius", "Birdeye", "PumpPortal", "Apify", "twitterapi", "CoinGecko", "GeckoTerminal", "DexScreener",
          "OpenAI", "Anthropic", "Claude", "Grok", "Render", "SOLANA_", "_KEY", "insajder", "kol.db", "league.db",
          "rani_pristup", "b2b_upiti", "provjere_dan", "kopirljivost.db", "tocnost.db")
# claims of a bot that makes money, or of features a visitor cannot get (alerts / copying that run for them)
CLAIMS = re.compile(r"(?i)autopilot|copy them automatically|automatski kopir|kopira(ti|mo)? automatski|zarađuj|"
                    r"earn (money|while)|guaranteed|zajamčen|real[- ]money|pravim? novc|demo račun|"
                    r"demo account|trading is live|tradanje pravim")
NEGATED = re.compile(r"(?i)(ne tvrdimo[^.]*|we do not claim[^.]*|promises no profit|ne obećava zaradu|ne obećanje "
                     r"zarade|not a promise of profit)")


def visible(html):
    return re.sub(r"\s+", " ", re.sub(r"(?s)<style>.*?</style>|<script.*?</script>|<[^>]+>", " ", html))


def main_text(html):
    """The page's own content: the shell's menu (which lists other sections of the site, e.g. a tools comparison of copy
    trading platforms) and footer are not this page's claims."""
    if "<main" in html:
        html = html.split("<main", 1)[1].split("</main>", 1)[0]
    else:
        html = re.sub(r"(?s)<nav class=top.*?</nav>", "", html)
        html = re.sub(r"(?s)<footer>.*?</footer>", "", html)
    return visible(html)


def kol_fixture(path, n=120, now=NOW):
    con = sqlite3.connect(path)
    con.executescript("""CREATE TABLE kols (handle TEXT PRIMARY KEY, name TEXT, followers INTEGER, score REAL, stats TEXT,
        bot INTEGER);
        CREATE TABLE calls (tweet_id TEXT, token TEXT, handle TEXT, ts INTEGER, url TEXT, symbol TEXT, kind TEXT,
        mcap0 REAL, r1h REAL, r24h REAL, max24 REAL, vol_lift REAL, views INTEGER, first_by_kol INTEGER, p0 REAL, bad TEXT,
        pre2h REAL, source TEXT);""")
    con.execute("INSERT INTO kols VALUES ('caller1','C',5000,60,'{}',0)")
    con.execute("INSERT INTO kols VALUES ('spambot','S',10,70,'{}',1)")
    for i in range(n):   # every 4th call +20 % after 24 h, the rest -10 %; one in 10 rugged
        r24 = 0.2 if i % 4 == 0 else (-0.95 if i % 10 == 1 else -0.1)
        con.execute("INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (str(i), f"T{i}", "caller1", now - 2 * 86400 - i * 600, "https://x.com/c/1", f"S{i}", "call", 1e6,
                     0.05 if i % 2 else -0.05, r24, 0.3, 1, 100, 1, 1, None, 0, "x"))
    for i in range(30):   # a bot's calls, a late call, a winner search: never counted
        con.execute("INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (f"b{i}", f"B{i}", "spambot", now - 2 * 86400, "u", "B", "call", 1e6, 1, 1, 1, 1, 1, 1, 1, None, 0, "x"))
    con.execute("INSERT INTO calls VALUES ('l','L','caller1',?,'u','L','call',1e6,1,1,1,1,1,1,1,NULL,2.0,'x')", (now - 2 * 86400,))
    con.execute("INSERT INTO calls VALUES ('w','W','caller1',?,'u','W','call',1e6,1,1,1,1,1,1,1,NULL,0,'kol_win')", (now - 2 * 86400,))
    con.commit()
    con.close()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.old_db = store.DB
        store.DB = os.path.join(self.tmp, "league.db")
        self.addCleanup(setattr, store, "DB", self.old_db)
        cijene._IPS.clear()
        quiet = mock.patch.dict(cijene.NOTIFY, {"fn": lambda _t: None})   # never a real Telegram message from a test
        quiet.start()
        self.addCleanup(quiet.stop)
        self.saved = dict(landing._STATS)
        landing._STATS.update(ts=time.time(), v={}, busy=True)
        self.addCleanup(self._restore)
        self.env = mock.patch.dict(os.environ, {"RENDER_EXTERNAL_URL": "https://memesonar.app",
                                                "KOL_DB": os.path.join(self.tmp, "kol.db"),
                                                "GA4_ID": "", "GA4_MEASUREMENT_ID": "", "GTM_ID": ""})
        self.env.start()
        self.addCleanup(self.env.stop)
        public._cache.clear()

    def _restore(self):
        landing._STATS.clear()
        landing._STATS.update(self.saved)

    def pages(self):
        """[(lang, path, html)] of the four new pages in both languages."""
        out = []
        for lang in ("hr", "en"):
            out += [(lang, N.href("home", lang), landing.page_html({}, lang=lang)),
                    (lang, N.href("pricing", lang), cijene.page(lang)),
                    (lang, N.href("check", lang), provjeri.page(lang)),
                    (lang, N.href("method", lang), metodologija.page(lang))]
        return out


class Pages(Base):
    def test_render_both_languages_and_pass_the_seo_audit(self):
        from ops import seoaudit as A
        for lang, path, html in self.pages():
            self.assertIn(f"<html lang={lang}>", html, path)
            self.assertEqual(html.count("<h1"), 1, path)
            f, issues = A.check(A.BASE + path, 200, html)
            self.assertEqual(issues, [], (path, issues))
        hr = landing.page_html({}, lang="hr")
        self.assertIn("<h1>Izmjereni podaci o Solana memecoinima</h1>", hr)
        self.assertIn("nakon troška", hr)
        self.assertIn("Podaci, ne financijski savjet", hr)
        en = landing.page_html({}, lang="en")
        self.assertIn("<h1>Measured data on Solana memecoins</h1>", en)
        self.assertIn("Data, not financial advice", en)
        for html in (hr, en):
            self.assertIn("id=pristup", html)        # every "#pristup" link of the site lands on the sign-up
            self.assertLess(html.index("id=dokaz"), html.index("id=proizvodi"))
            self.assertLess(html.index("id=kako"), html.index("id=cijena"))
            for anchor in ("/hr/metodologija", "/metodologija") if html is hr else ("/methodology",):
                self.assertIn(anchor, html)

    def test_no_bot_claims_no_autopilot_no_locked_promises(self):
        for lang, path, html in self.pages():
            text = NEGATED.sub("", main_text(html))
            self.assertIsNone(CLAIMS.search(text), (path, CLAIMS.search(text) and text[CLAIMS.search(text).start() - 60:][:140]))
            self.assertNotIn("profitab", text.lower(), path)
            self.assertNotIn("class=lock", html, path)
            self.assertNotIn("/autopilot", html, path)
        for lang in ("hr", "en"):   # the old homepage blocks are gone
            html = landing.page_html({}, lang=lang)
            for old in ("id=autopilot", "class=show", "class=dcta", "id=novcanici", "Zatraži pristup.",
                        "Request access.", "Wallets that buy", "Novčanici koji kupuju", "Za sada besplatno", "Free for now"):
                self.assertNotIn(old, html, old)

    def test_no_internal_words(self):
        for lang, path, html in self.pages():
            text = visible(html)
            m = INTERNAL.search(text)
            self.assertIsNone(m, (path, m and text[max(0, m.start() - 60):m.end() + 40]))
            self.assertIsNone(RECIPE.search(text), path)
            for b in BANNED:
                self.assertNotIn(b, text, (path, b))

    def test_methodology_concepts_and_honest_sources(self):
        for lang in ("hr", "en"):
            t = main_text(metodologija.page(lang))
            for w in (("izvan uzorka", "3 %", "5 sekundi", "promašen", "javni lanac", "licencirani tržišni podaci")
                      if lang == "hr" else ("out of sample", "3%", "5 seconds", "missed", "public chain",
                                            "licensed market data")):
                self.assertIn(w.lower(), t.lower(), w)

    def test_pricing_packages(self):
        hr = main_text(cijene.page("hr"))
        for s in ("0 €", "29 €", "290 €", "79 €", "5.000 zahtjeva", "−40 %", "prvih 50", "199 $/mj", "499 $/mj",
                  "Licenca podataka", "KOL izvještaji za agencije", "Naplata se uskoro otvara", "Alarmi na Telegramu"):
            self.assertIn(s, hr, s)
        en = main_text(cijene.page("en"))
        for s in ("€0", "€29", "€290", "€79", "5,000 requests", "40% off", "$199/mo", "$499/mo", "Billing opens soon"):
            self.assertIn(s, en, s)
        html = cijene.page("hr")
        self.assertIn("action=/cekanje", html)
        self.assertIn("action=/b2b-upit", html)
        self.assertEqual(html.count("name=consent value=1 required"), 2)
        self.assertEqual(html.count("name=web tabindex=-1"), 2)            # the honeypots
        self.assertIn("<option value=proplus selected>", cijene.page("hr", {"plan": "proplus"}))


class Proof(Base):
    def test_no_data_says_still_measuring_never_a_number(self):
        for lang, wait in (("hr", "Mjerenje je u tijeku"), ("en", "Still measuring")):
            strip = landing.page_html({}, lang=lang).split("id=dokaz")[1].split("</section>")[0]
            self.assertEqual(strip.count(wait), 3)
            self.assertEqual(strip.count("<b class=w>—</b>"), 3)
            self.assertIsNone(re.search(r"<b>\d", strip))

    def test_numbers_from_the_data_with_sample_and_date(self):
        kol_fixture(os.environ["KOL_DB"])
        k = N.kol_number(NOW)
        self.assertEqual(k["n"], 120)                 # bots, the late call and the winner search left out
        self.assertAlmostEqual(k["share"], 30 / 120)  # +20 % less 3 % is up; -10 % is not
        toc = os.path.join(self.tmp, "tocnost.db")
        from tocnost import store as ts
        con = ts.connect(toc)
        ts.save(con, NOW - 3600, "rug", [
            {"bucket": "VISOK RIZIK", "dir": 1, "n": 40, "k": 30, "rate": .75, "lo": .6, "hi": .85, "correct": 30,
             "acc": .75, "acc_lo": .6, "acc_hi": .85, "base_n": 400, "base_k": 40, "base": .1, "enough": 1, "since": 0},
            {"bucket": "PROLAZI", "dir": -1, "n": 60, "k": 6, "rate": .1, "lo": .05, "hi": .2, "correct": 54,
             "acc": .9, "acc_lo": .8, "acc_hi": .95, "base_n": 400, "base_k": 40, "base": .1, "enough": 1, "since": 0}])
        con.commit()
        con.close()
        ts.clear_cache()
        self.addCleanup(ts.clear_cache)
        a = N.toc_number(toc)
        self.assertEqual((a["score"], a["n"]), ("rug", 100))
        self.assertAlmostEqual(a["acc"], 0.84)
        kp = os.path.join(self.tmp, "kopirljivost.db")
        from wallets import kopirljivost as K
        c = K.connect(kp)
        for i in range(12):
            c.execute("INSERT INTO kopirljivost (kind, source, delay, n, verdict, updated) VALUES (?,?,?,?,?,?)",
                      ("novcanik", f"w{i}", 30, 25, "kopirljivo" if i < 3 else "nije", NOW - 7200))
        c.execute("INSERT INTO kopirljivost (kind, source, delay, n, verdict, updated) VALUES ('novcanik','x',30,2,'malo',?)",
                  (NOW,))
        c.commit()
        c.close()
        b = N.kop_number(kp)
        self.assertEqual((b["good"], b["rated"], b["n"]), (3, 12, 300))
        html = N.proof_html("hr", {"kol": k, "toc": a, "kop": b})
        for s in ("25 %", "n = 120 poziva", "84 %", "provjere ruga", "n = 100 provjerenih", "3 od 12", "n = 300 kopiranja"):
            self.assertIn(s, html, s)
        self.assertIn(N.day_text(k["day"], "hr"), html)
        en = N.proof_html("en", {"kol": k, "toc": a, "kop": b})
        self.assertIn("25%", en)
        self.assertIn("3 of 12", en)

    def test_too_small_samples_are_withheld(self):
        kol_fixture(os.environ["KOL_DB"], n=20)
        self.assertIsNone(N.kol_number(NOW))
        self.assertIsNone(N.toc_number(os.path.join(self.tmp, "nema.db")))
        self.assertIsNone(N.kop_number(os.path.join(self.tmp, "nema.db")))

    def test_counted_in_the_background_with_the_other_numbers(self):
        with mock.patch.object(N, "proof", return_value={"kol": None}) as p:
            v = landing.compute()
        p.assert_called_once()
        self.assertEqual(v["dokaz"], {"kol": None})


class Forms(Base):
    def test_waitlist_rows_dupes_honeypot_consent(self):
        ok = {"plan": "pro", "email": "Ana@Mail.hr", "consent": "1", "name": "Ana", "lang": "hr"}
        self.assertEqual(cijene.submit(ok, "1.1.1.1"), (True, None))
        self.assertEqual(cijene.submit(dict(ok), "1.1.1.1"), (True, None))                  # the same again: one row
        self.assertEqual(cijene.submit({**ok, "plan": "tjedni"}, "1.1.1.1"), (True, None))
        self.assertEqual(cijene.submit({**ok, "email": "bot@x.io", "web": "http://spam"}, "2.2.2.2"), (True, None))
        self.assertEqual(cijene.submit({**ok, "consent": ""}, "3.3.3.3"), (False, "consent"))
        self.assertEqual(cijene.submit({**ok, "email": "nope"}, "3.3.3.3"), (False, "email"))
        self.assertEqual(cijene.submit({**ok, "plan": "gold"}, "3.3.3.3"), (False, "plan"))
        rows = cijene.rows("rani_pristup")
        self.assertEqual(sorted(r["plan"] for r in rows), ["pro", "tjedni"])
        self.assertEqual(rows[0]["email"], "ana@mail.hr")
        self.assertTrue(all(r["consent_ts"] and r["ip_hash"] and "1.1.1.1" not in r["ip_hash"] for r in rows))

    def test_rate_limit_holds_across_processes(self):
        for i in range(cijene.PER_IP_HOUR):
            self.assertEqual(cijene.submit({"plan": "pro", "email": f"a{i}@b.hr", "consent": "1"}, "9.9.9.9"), (True, None))
        self.assertEqual(cijene.submit({"plan": "pro", "email": "x@b.hr", "consent": "1"}, "9.9.9.9"), (False, "rate"))
        cijene._IPS.clear()   # a restart: the database count still says no
        self.assertEqual(cijene.submit({"plan": "pro", "email": "y@b.hr", "consent": "1"}, "9.9.9.9"), (False, "rate"))
        ok, code = cijene.submit_b2b({"company": "Acme", "email": "a@acme.io", "need": "API please", "consent": "1"},
                                     "9.9.9.9")
        self.assertEqual((ok, code), (False, "rate"))
        self.assertEqual(cijene.submit({"plan": "pro", "email": "y@b.hr", "consent": "1"}, "8.8.8.8"), (True, None))
        self.assertIn("sat", cijene.err_text("rate", "hr"))
        self.assertIn("hour", cijene.err_text("rate", "en"))

    def test_b2b_stored_and_owner_told_once(self):
        told = []
        with mock.patch.dict(cijene.NOTIFY, {"fn": told.append}):
            f = {"company": "Acme Labs", "email": "ops@acme.io", "need": "Token risk API in our app", "interest": "api_business",
                 "consent": "1", "lang": "en"}
            self.assertEqual(cijene.submit_b2b(f, "4.4.4.4"), (True, None))
            self.assertEqual(cijene.submit_b2b({**f, "web": "x"}, "5.5.5.5"), (True, None))    # honeypot: nothing
            self.assertEqual(cijene.submit_b2b({**f, "consent": ""}, "5.5.5.5"), (False, "consent"))
            self.assertEqual(cijene.submit_b2b({**f, "company": ""}, "5.5.5.5"), (False, "company"))
            self.assertEqual(cijene.submit_b2b({**f, "need": ""}, "5.5.5.5"), (False, "need"))
        self.assertEqual(len(told), 1)
        self.assertIn("Acme Labs", told[0])
        self.assertNotIn("ops@acme.io", told[0])                  # the e-mail stays on our side
        rows = cijene.rows("b2b_upiti")
        self.assertEqual([(r["company"], r["interest"]) for r in rows], [("Acme Labs", "api_business")])

    def test_owner_page_csv_and_role(self):
        cijene.submit({"plan": "proplus", "email": "z@z.hr", "consent": "1"}, "1.2.3.4")
        cijene.submit_b2b({"company": "=HYPERLINK(1)", "email": "a@b.io", "need": "=cmd stuff", "consent": "1"}, "1.2.3.5")
        title, body = cijene.owner_page({})
        self.assertIn("z@z.hr", body)
        self.assertIn("Pro+: <b>1</b>", body)
        name, text = cijene.csv_export("b2b")
        self.assertTrue(name.endswith(".csv"))
        self.assertIn("'=HYPERLINK(1)", text)                     # never a live formula in the owner's sheet
        self.assertIn("z@z.hr", cijene.csv_export("cekanje")[1])
        for r in ("osnovni", "prijatelj"):
            self.assertEqual(roles.deny_get("/prijave", r), "admin")
            self.assertEqual(roles.deny_get("/prijave.csv", r), "admin")
        self.assertIsNone(roles.deny_get("/prijave", "admin"))


class FreeCheck(Base):
    def test_three_a_day_per_visitor_and_per_address(self):
        for _ in range(provjeri.DAILY):
            self.assertTrue(provjeri.take("a" * 32, "7.7.7.7"))
        self.assertFalse(provjeri.take("a" * 32, "7.7.7.7"))
        self.assertEqual(provjeri.used("a" * 32, "7.7.7.7"), provjeri.DAILY)
        self.assertTrue(provjeri.take("a" * 32, "7.7.7.7", now=NOW + 86400))       # a new UTC day
        n = sum(provjeri.take(f"{i:032x}", "6.6.6.6") for i in range(provjeri.IP_DAILY + 3))   # cookies cleared
        self.assertEqual(n, provjeri.IP_DAILY)

    def test_result_unknown_bad_and_limit(self):
        kol_fixture(os.environ["KOL_DB"])
        html = provjeri.check("hr", {"h": "@caller1"}, "b" * 32, "5.5.5.5")
        res = main_text(html)
        self.assertIn("@caller1: 120 izmjerenih poziva", res)
        self.assertIn("nakon troška", res)
        self.assertIn("25 %", res)                                   # in plus a day later after a 3 % cost
        self.assertIn("/hr/influencer/caller1", html)
        self.assertIn("ostalo provjera: 2 od 3", res)
        self.assertIn("još ne pratimo", main_text(provjeri.check("hr", {"h": "spambot"}, "b" * 32, "5.5.5.5")))
        self.assertIn("Enter an X handle", main_text(provjeri.check("en", {"h": "<script>"}, "b" * 32, "5.5.5.5")))
        self.assertIn("do not track @nobody_here", main_text(provjeri.check("en", {"h": "nobody_here"}, "b" * 32, "5.5.5.5")))
        en = main_text(provjeri.check("en", {"h": "caller1"}, "b" * 32, "5.5.5.5"))
        self.assertIn("used all three free checks", en)
        self.assertEqual(provjeri.used("b" * 32, "5.5.5.5"), 3)     # the bad handle was not counted
        for w in ("težin", "weight", "threshold", "prag", "formula"):
            self.assertNotIn(w, res.lower())


class Consent(Base):
    def test_nothing_without_ids(self):
        from analytics import ga4
        self.assertEqual(ga4.tag("hr"), "")
        for _lang, path, html in self.pages():
            self.assertNotIn("googletagmanager", html, path)
            self.assertNotIn("id=cc ", html, path)

    def test_defaults_denied_and_no_script_before_accept(self):
        from analytics import ga4
        with mock.patch.dict(os.environ, {"GA4_ID": "G-ABC123", "GTM_ID": "GTM-XY12"}):
            t = ga4.tag("hr")
            html = landing.page_html({}, lang="hr")
            self.assertIn("data-cc-open", main_text(html) and html)       # the footer reopens the banner
        self.assertIn("analytics_storage:'denied'", t)
        self.assertIn("ad_user_data:'denied'", t)
        self.assertIn("ad_personalization:'denied'", t)
        self.assertIsNone(re.search(r"<script[^>]+src=", t))           # no tag script in the HTML itself
        self.assertIn("ms_consent", t)
        self.assertIn(t, html)
        with mock.patch.dict(os.environ, {"GA4_ID": "G-<x>", "GTM_ID": "GTM-'"}):
            self.assertEqual(ga4.tag("en"), "")

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_script_runs_only_after_accept(self):
        """The banner's script in node with a tiny fake document: no script element before Accept, gtag + gtm after,
        none after Decline, and a stored "y" loads at once."""
        from analytics import ga4
        with mock.patch.dict(os.environ, {"GA4_ID": "G-ABC123", "GTM_ID": "GTM-XY12"}):
            js = re.search(r"<script>(.*)</script>", ga4.tag("en"), re.S).group(1)
        harness = """
const added=[];let cookie=process.argv[2]||'';const handlers=[];const docHandlers=[];
const banner={hidden:true,addEventListener:(t,f)=>handlers.push(f)};
global.window=global;global.location={protocol:'https:'};
global.document={get cookie(){return cookie},set cookie(v){cookie=v.split(';')[0]},
 getElementById:()=>banner,createElement:()=>({}),head:{appendChild:s=>added.push(s.src)},
 addEventListener:(t,f)=>docHandlers.push(f)};
%s
const out={before:added.length,shown:!banner.hidden,consent:dataLayer[0][1]+':'+dataLayer[0][2].analytics_storage};
const click=process.argv[3];if(click)handlers.forEach(f=>f({target:{dataset:{cc:click}}}));
out.after=added;out.cookie=cookie;out.update=dataLayer.some(a=>a[0]==='consent'&&a[1]==='update');
console.log(JSON.stringify(out));""" % js
        f = os.path.join(self.tmp, "h.js")
        with open(f, "w") as fh:
            fh.write(harness)
        run = (lambda *a: json.loads(subprocess.run(["node", f, *a], capture_output=True, text=True, timeout=30).stdout))
        o = run("", "")
        self.assertEqual((o["before"], o["shown"], o["consent"], o["update"]), (0, True, "default:denied", False))
        o = run("", "n")
        self.assertEqual((o["after"], o["cookie"], o["update"]), ([], "ms_consent=n", False))
        o = run("", "y")
        self.assertEqual(o["cookie"], "ms_consent=y")
        self.assertEqual(len(o["after"]), 2)
        self.assertTrue(o["update"])
        self.assertIn("gtag/js?id=G-ABC123", o["after"][0])
        self.assertIn("gtm.js?id=GTM-XY12", o["after"][1])
        o = run("ms_consent=y", "")
        self.assertEqual((len(o["after"]), o["shown"]), (2, False))


class Indexing(Base):
    def test_core_robots_paths_and_aliases(self):
        import run_ui
        from ui import seoindex
        hubs = {(en, hr) for en, hr, _p, _m in seoindex._hubs(NOW)}
        self.assertNotIn(N.PATHS["method"], hubs)   # 28.11. (vlasnik): public, noindex for now
        for p in N.PATHS["method"]:
            self.assertFalse(seoindex.indexable(p), p)
            self.assertIn('content="noindex,follow"', public.policy(p, metodologija.page("en" if p[1:3] != "hr" else "hr")))
        for key in ("pricing", "check", "method"):
            if key != "method":
                self.assertIn(N.PATHS[key], hubs)
            for p in N.PATHS[key]:
                self.assertTrue(run_ui.is_public(p), p)
                self.assertIn(p, run_ui.NEW_PUBLIC)
        robots = public.robots()
        for p in ("/pricing$", "/hr/cijene$", "/check-influencer$", "/hr/provjeri-influencera$", "/methodology$",
                  "/hr/metodologija$"):
            self.assertIn(f"Allow: {p}\n", robots)
        for old, new in N.ALIASES.items():
            self.assertIn(old, run_ui.NEW_ALIASES)
            self.assertTrue(run_ui.is_public(old), old)
            self.assertIn(new, run_ui.NEW_PUBLIC)
        html = cijene.page("hr")
        self.assertIn('<link rel=canonical href="https://memesonar.app/hr/cijene">', html)
        self.assertIn('hreflang=en href="https://memesonar.app/pricing"', html)
        self.assertIn('hreflang=x-default href="https://memesonar.app/pricing"', html)


if __name__ == "__main__":
    unittest.main()
