"""SEO plan 7.11. (implemented 9.11.2026): honest influencer statistics (ui/kolstats.py), profile pages with FAQ and
noindex below 10 clean calls, the Telegram channel hub and profiles, the sitemap threshold and the five new posts.
No network: a synthetic kol.db in a temp dir."""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kol import store as kstore  # noqa: E402
from ui import kolstats as KS, public, telegrampub  # noqa: E402

NOW = int(time.time())
D = 86400


def _call(con, tid, tok, h, ts, kind="call", src="kol_timeline", r1=0.1, r24=-0.2, mx=0.3, pre=0.0, bad=None):
    con.execute("INSERT INTO calls (tweet_id, token, symbol, handle, ts, kind, source, r1h, r24h, max24, pre2h, bad, mcap0, url)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (tid, tok, tok[:4], h, ts, kind, src, r1, r24, mx, pre, bad, 120000, "https://x.com/x/status/1"))


def make_db(d):
    path = os.path.join(d, "kol.db")
    con = kstore.connect(path)
    for i in range(14):
        _call(con, f"a{i}", f"TOK{i}", "goodguy", NOW - (3 + i) * D, r1=0.2 if i % 2 else -0.1,
              r24=0.5 if i % 3 == 0 else -0.6, mx=0.4 if i % 2 else 0.05)
    _call(con, "late", "LATE", "goodguy", NOW - 5 * D, pre=1.5)            # late call: excluded
    _call(con, "win", "WIN", "goodguy", NOW - 5 * D, src="kol_win")        # outcome-selected source: excluded
    _call(con, "bad", "BAD", "goodguy", NOW - 5 * D, bad="mcap")           # dust pool: excluded
    _call(con, "fresh", "FRESH", "goodguy", NOW - 3600)                    # younger than 24 h: members only
    _call(con, "brag", "BRAG", "goodguy", NOW - 5 * D, kind="brag")        # not a call
    for i in range(4):
        _call(con, f"t{i}", f"TK{i}", "thinguy", NOW - (3 + i) * D)
    for i in range(12):
        _call(con, f"b{i}", f"B{i}", "scannerbot", NOW - (3 + i) * D)
    for i in range(12):
        _call(con, f"g{i}", f"G{i}", "tg:alphacalls", NOW - (3 + i) * D, src="tg", r1=0.05, r24=0.1, mx=0.2)
    for i in range(3):
        _call(con, f"s{i}", f"S{i}", "tg:smallchan", NOW - (3 + i) * D, src="tg")
    con.executemany("INSERT INTO kols (handle, name, followers, score, stats, bot) VALUES (?,?,?,?,?,?)", [
        ("goodguy", "Good Guy", 12000, 55, json.dumps({"measured": 14, "hit_rate": 0.4, "med_max24": 0.3, "rug_rate": 0.1,
                                                        "prepump_rate": 0.1}), 0),
        ("thinguy", None, 3000, 40, json.dumps({"measured": 4}), 0),
        ("scannerbot", None, 500, 30, json.dumps({"measured": 12}), 1),
        ("tg:alphacalls", "Alpha Calls", 4000, 50, json.dumps({"measured": 12, "calls": 40}), 0),
        ("tg:smallchan", None, 100, 20, json.dumps({"measured": 3}), 0)])
    con.commit()
    con.close()
    return path


class Honest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        cls.path = make_db(cls.d)
        os.environ["KOL_DB"] = cls.path
        os.environ["RENDER_EXTERNAL_URL"] = "https://example.com"
        public._cache.clear()
        KS._BASE.clear()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("KOL_DB", None)
        os.environ.pop("RENDER_EXTERNAL_URL", None)
        public._cache.clear()
        KS._BASE.clear()

    def test_clean_calls_drop_late_biased_bad_fresh_and_bots(self):
        con = public._con()
        try:
            calls = KS.clean_calls(con, "goodguy")
            self.assertEqual(len(calls), 14)
            self.assertEqual({c["token"][:3] for c in calls}, {"TOK"})
            counts = KS.clean_counts(con, prefix="")
            self.assertEqual(counts, {"goodguy": 14, "thinguy": 4})      # the bot is out
            self.assertEqual(KS.clean_counts(con, prefix="tg:"), {"tg:alphacalls": 12, "tg:smallchan": 3})
            s = KS.stats(calls)
            self.assertTrue(s["enough"])
            self.assertEqual(s["n"], 14)
            self.assertAlmostEqual(s["up1h"], 7 / 14)
            self.assertAlmostEqual(s["hit15"], 7 / 14)
            self.assertEqual(s["best"]["r24h"], 0.5)
            self.assertEqual(s["worst"]["r24h"], -0.6)
            self.assertTrue(s["months"])
            base = KS.baseline(con, cache={})
            self.assertEqual(base["accounts"], 2)                       # goodguy and the Telegram channel
            self.assertFalse(KS.stats(KS.clean_calls(con, "thinguy"))["enough"])
        finally:
            con.close()

    def test_verdict_never_claims_without_data(self):
        few = KS.stats([])
        self.assertIn("Premalo podataka", KS.verdict(few, {"accounts": 0}, "hr"))
        self.assertIn("Too little data", KS.verdict(few, {"accounts": 0}, "en"))
        con = public._con()
        try:
            s = KS.stats(KS.clean_calls(con, "goodguy"))
        finally:
            con.close()
        v = KS.verdict(s, {"accounts": 2, "up1h": 0.5, "hit15": 0.5, "med24": -0.2}, "en")
        self.assertIn("On 14 clean measured calls", v)
        self.assertIn("Past calls, not a prediction", v)

    def test_profile_with_data_has_faq_and_is_indexable(self):
        code, raw, _ = public.route("/influencer/goodguy")
        html = raw.decode()
        self.assertEqual(code, 200)
        self.assertIn("x.com/goodguy", html)
        self.assertIn("FAQPage", html)
        self.assertIn("Month by month", html)
        self.assertIn("Best and worst call", html)
        self.assertIn("(X / Twitter): crypto calls track record", html)
        self.assertNotIn("noindex", html)
        self.assertNotIn("FRESH", html)                                  # members only
        hr = public.route("/hr/influencer/goodguy")[1].decode()
        self.assertIn("Mjesec po mjesec", hr)
        self.assertIn("Prošli pozivi, ne predviđanje", hr)

    def test_thin_profile_is_noindex_and_says_so(self):
        html = public.route("/influencer/thinguy")[1].decode()
        self.assertIn('<meta name=robots content="noindex,follow">', html)
        self.assertIn("Too little data", html)
        self.assertNotIn("FAQPage", html)
        self.assertIn("Premalo podataka", public.route("/hr/influencer/thinguy")[1].decode())

    def test_telegram_hub_and_profiles(self):
        code, raw, _ = public.route("/telegram-channels")
        html = raw.decode()
        self.assertEqual(code, 200)
        self.assertIn("/telegram/alphacalls", html)
        self.assertNotIn("/telegram/smallchan", html)                     # too few calls for the hub
        self.assertIn("ItemList", html)
        self.assertIn('hreflang=hr href="https://example.com/hr/telegram-kanali"', html)
        p = public.route("/telegram/alphacalls")[1].decode()
        self.assertIn("t.me/alphacalls", p)
        self.assertIn("FAQPage", p)
        self.assertNotIn("noindex", p)
        self.assertIn("Alpha Calls", p)
        thin = public.route("/telegram/smallchan")[1].decode()
        self.assertIn("noindex", thin)
        self.assertEqual(public.route("/telegram/nope")[0], 404)
        self.assertEqual(public.route("/telegram/<script>")[0], 404)
        self.assertIn("Zadnji pozivi", public.route("/hr/telegram/alphacalls")[1].decode())

    def test_sitemap_and_robots_follow_the_threshold(self):
        sm = public.route("/sitemap.xml")[1].decode()
        self.assertIn("https://example.com/influencer/goodguy", sm)
        self.assertNotIn("https://example.com/influencer/thinguy", sm)
        self.assertIn("https://example.com/telegram-channels", sm)
        self.assertIn("https://example.com/telegram/alphacalls", sm)
        self.assertNotIn("https://example.com/telegram/smallchan", sm)
        self.assertIn("https://example.com/hr/telegram/alphacalls", sm)
        r = public.route("/robots.txt")[1].decode()
        self.assertIn("Allow: /telegram/", r)
        self.assertIn("Allow: /hr/telegram-kanali", r)
        self.assertEqual(telegrampub.urls()[0], ("/telegram-channels", "/hr/telegram-kanali", "0.8"))


class Posts(unittest.TestCase):
    SLUGS = ("best-crypto-telegram-channels", "top-crypto-twitter-accounts-by-call-accuracy",
             "memecoin-telegram-groups-explained", "how-to-spot-a-pump-fun-runner", "how-to-check-a-kol-track-record")

    def setUp(self):
        os.environ["RENDER_EXTERNAL_URL"] = "https://example.com"
        public._cache.clear()

    def tearDown(self):
        os.environ.pop("RENDER_EXTERNAL_URL", None)

    def test_five_posts_in_both_languages_link_the_clusters(self):
        from ui import blog
        for slug in self.SLUGS:
            en = blog.get(slug, "en")
            hr = blog.get(blog.view(blog.get(slug), "hr")["slug"], "hr")
            self.assertIsNotNone(en, slug)
            self.assertIsNotNone(hr, slug)
            page = public.route(f"/blog/{slug}")[1].decode()
            self.assertEqual(public.route(f"/blog/{slug}")[0], 200)
            self.assertIn("class=bv", page)
            self.assertTrue("/influencers" in page or "/telegram-channels" in page or "/solana-meme-coins" in page, slug)
            # never a named winner: the posts say no account passed the tests
            self.assertNotIn("@ratwizardx", page)
            self.assertNotIn("api-key", page.lower())


if __name__ == "__main__":
    unittest.main()
