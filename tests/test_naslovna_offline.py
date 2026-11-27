"""The public homepage after the change of focus (20.11.; vlasnik 19.11.: "Treba homepage osvježiti isto i promijeniti
fokus" and "Autopilot stavi u drugi plan dok rekonstruiramo app"; ui/landing.py):

  - both languages: the headline, the one sentence and the three steps
  - the old claims are gone (collected from the page before the change), no link to the removed app pages
  - the live numbers from the fixture (scripts/seed_novcanici.py) and with no data ("—", "being computed")
  - the examples carry no address; no data provider, env name or internal word on the page
  - Autopilot: not in the hero, one block low on the page, the pause block in both languages
  - SEO: one h1, title / description / canonical / hreflang / og / JSON-LD pass ops/seoaudit

    python3 -m unittest tests.test_naslovna_offline
"""
import os
import re
import sys
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tests.autopilot_staro import setUpModule, tearDownModule  # noqa: E402,F401   # 27.11.: tests the removed Autopilot (AUTOPILOT_OFF=0)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from ui import landing  # noqa: E402

HEAD = {"en": ("Wallets that buy <span class=g>before the jump.</span>",
               "We look for the wallets that buy before a token jumps, and measure whether following them pays."),
        "hr": ("Novčanici koji kupuju <span class=g>prije skoka.</span>",
               "Tražimo novčanike koji kupuju prije nego što token skoči i mjerimo isplati li se pratiti ih.")}
STEPS = {"en": ("We watch tokens worth 2 to 200 million dollars", "We find who bought before the rise",
                "We measure and publish", "bots, market makers and one-off wallets are left out",
                "also when it is negative"),
         "hr": ("Pratimo tokene od 2 do 200 milijuna dolara", "Tražimo tko je kupio prije rasta", "Mjerimo i objavljujemo",
                "botove, market makere i novčanike koji se pojave samo jednom izbacujemo", "i kad je rezultat negativan")}
# the page before 20.11. (collected from it before the change): none of these may come back
OLD = {"en": ("Smarter entries into", "MemeSonar tracks new tokens, influencers and smart wallets", "Token picks",
              "Event tokens", "Demo bot and copy trading", "when 3+ influencers call a token within 15 minutes",
              "Fresh re-check every 3 minutes", "new scan", "$1,000 demo account", "Influencer leaderboard.",
              "/crypto-influencer-calls", "Open the leaderboard", "Who just bought or sold", "Rug shield",
              "Long-term tokens", "Real-money trading is live", "class='w apst'"),
       "hr": ("Pametniji ulaz u", "MemeSonar prati nove tokene, influencere i pametne novčanike", "Prijedlozi tokena",
              "Event tokeni", "Demo bot i copy trading", "kad token zove 3+ influencera u 15 minuta",
              "Svježa provjera svake 3 minute", "novi sken", "demo račun od $1.000", "Ljestvica influencera.",
              "/hr/pozivi-kripto-influencera", "Otvori ljestvicu", "Tko je upravo kupio ili prodao", "Štit od ruga",
              "Dugoročni tokeni", "Tradanje pravim sredstvima je live", "class='w apst'")}
REMOVED_PAGES = ("/events", "/radar", "/whatsapp", "/prijedlozi", "/natjecanje")
BANNED = ("Helius", "Birdeye", "PumpPortal", "Apify", "twitterapi", "CoinGecko", "GeckoTerminal", "DexScreener",
          "OpenAI", "Anthropic", "Claude", "Grok", "Render", "pumpa15", "pumpa2", "i2_", "helius_day", "SOLANA_",
          "_KEY", "BIRDEYE", "insajder", "Insajder", "kandidat", "$ /", "USD/")


def visible(html):
    return re.sub(r"<style>.*?</style>|<script.*?</script>|<[^>]+>", " ", html, flags=re.S)


class Base(unittest.TestCase):
    def setUp(self):
        self.saved = (dict(landing._STATS), landing._STATS.get("ts"))
        landing._STATS.update(ts=0, v={}, busy=True)
        self.addCleanup(self._restore)

    def _restore(self):
        landing._STATS.clear()
        landing._STATS.update(self.saved[0])

    def page(self, lang, nv=None, paused=False):
        from ui import pauza
        landing._STATS.update(ts=time.time() if nv else 0, v={"nov": nv} if nv else {}, busy=bool(not nv))
        with mock.patch.object(pauza, "on", return_value=paused):
            return landing.page_html({}, lang=lang)


class Text(Base):
    def test_headline_steps_and_no_old_claims(self):
        for lang in ("en", "hr"):
            html = self.page(lang)
            h1, sub = HEAD[lang]
            self.assertEqual(html.count("<h1"), 1)
            self.assertIn(f"<h1>{h1}</h1>", html)
            self.assertIn(f"<p class=sub>{sub}</p>", html)
            for s in STEPS[lang]:
                self.assertIn(s, html, s)
            steps = html.split("<ol class=steps>")[1].split("</ol>")[0]
            self.assertEqual(steps.count("<li>"), 3)
            for s in OLD[lang]:
                self.assertNotIn(s, html, s)
            for p in REMOVED_PAGES:
                self.assertIsNone(re.search(rf'href="?{re.escape(p)}[/"> ]', html), p)
            for b in BANNED:
                self.assertNotIn(b, html, b)
            hero = html.split("<header class=hero>")[1].split("</header>")[0]
            self.assertNotIn("autopilot", visible(hero).lower())          # not in the first screen
            self.assertNotIn("/autopilot", hero)
            self.assertLess(html.index("id=kako"), html.index("id=brojke"))
            self.assertLess(html.index("id=novcanici"), html.index("id=autopilot"))   # Autopilot low on the page
            self.assertLess(html.index("id=autopilot"), html.index("id=pristup"))

    def test_the_pause_block_in_both_languages(self):
        from ui import pauza
        for lang in ("en", "hr"):
            html = self.page(lang, paused=True)
            block = html.split("id=autopilot")[1].split("</section>")[0]
            self.assertIn(pauza.TEXT[lang], block)
            self.assertIn(pauza.DEMO[lang], block)
            self.assertNotIn("is live", block)
            off = self.page(lang, paused=False).split("id=autopilot")[1].split("</section>")[0]
            self.assertNotIn(pauza.TEXT[lang], off)
            self.assertIn("/autopilot" if lang == "en" else "/hr/autopilot", off)

    def test_disclaimer_and_access(self):
        for lang, d in (("en", "These are statistics from public on-chain data, not financial advice."),
                        ("hr", "To je statistika iz javnih podataka s lanca, a ne financijski savjet.")):
            html = self.page(lang)
            self.assertIn(d, html)
            wal = html.split("id=novcanici")[1].split("</section>")[0]
            self.assertIn("href=#pristup", wal)
            self.assertIn("/prijava", wal)


class LiveNumbers(Base):
    def test_empty_shows_dashes_and_being_computed(self):
        for lang, wait in (("en", "The first results are being computed."), ("hr", "Prvi rezultati se upravo računaju.")):
            live = self.page(lang).split("id=brojke")[1].split("</section>")[0]
            self.assertEqual(live.count("<b>—</b>"), 4)
            self.assertIn(wait, live)

    def test_from_the_fixture(self):
        import seed_novcanici as SEED
        import tempfile
        from league import store as lstore
        from trade import settings
        from wallets import store as wstore
        from ui import pauza
        d = tempfile.mkdtemp()
        paths = SEED.paths_in(d)
        with mock.patch.dict(os.environ, {"INSAJDERI_DB": paths["insajderi"], "HOLDERI_DB": paths["holderi"],
                                          "TOKENSTRANICE_DB": os.path.join(d, "nema.db")}), \
                mock.patch.object(wstore, "DB", paths["wallets"]), mock.patch.object(lstore, "DB", paths["league"]), \
                mock.patch.object(settings, "DB", paths["trade"]):
            SEED.seed(paths, now=int(time.time()))
            pauza.reset()
            nv = landing.wallet_numbers()
            self.assertEqual((nv["rises"], nv["found"], nv["confirmed"]), (40, 20, 8))
            self.assertEqual(len(nv["examples"]), 3)
            self.assertTrue(nv["meas"]["n"] > 0)
            self.assertEqual(nv["tokens"], [])
            html = self.page("en", nv)
            live = html.split("id=brojke")[1].split("</section>")[0]
            for s in ("<b>40</b>", "<b>20</b>", "<b>8</b>", "too early to say", "buys measured"):
                self.assertIn(s, live)
            wal = visible(html.split("id=novcanici")[1].split("</section>")[0])
            self.assertEqual(wal.count("confirmed on newer data."), 3)
            for m in SEED.seed(paths, now=int(time.time()))["members"]:   # no address of a wallet anywhere
                self.assertNotIn(m[:10], html)
            self.assertIn("The token list is filling up.", html)

    def test_numbers_are_kept_with_the_others(self):
        with mock.patch.object(landing, "wallet_numbers", return_value={"rises": 3}) as wn:
            v = landing.compute()
        wn.assert_called_once()
        self.assertEqual(v["nov"], {"rises": 3})


class Seo(Base):
    def test_audit_passes(self):
        from ops import seoaudit as A
        for lang, path in (("en", "/"), ("hr", "/hr")):
            with mock.patch.dict(os.environ, {"RENDER_EXTERNAL_URL": A.BASE}):
                html = self.page(lang)
            f, issues = A.check(A.BASE + path, 200, html)
            self.assertEqual(issues, [], path)
            self.assertIn('hreflang=x-default', html)
            self.assertIn('"@type":"WebApplication"', html)
            self.assertIn("og-home" + ("-hr" if lang == "hr" else "") + ".jpg", html)


if __name__ == "__main__":
    unittest.main()
