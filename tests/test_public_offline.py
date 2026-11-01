"""Public indexable pages: influencer leaderboard/profile (EN + HR), robots, sitemap, delay of fresh calls. No network."""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import landing, public  # noqa: E402


def _db():
    p = os.path.join(tempfile.mkdtemp(), "kol.db")
    con = sqlite3.connect(p)
    con.executescript("""CREATE TABLE kols (handle TEXT PRIMARY KEY, name TEXT, followers INTEGER, score REAL, stats TEXT,
        bot INTEGER);
        CREATE TABLE calls (tweet_id TEXT, token TEXT, handle TEXT, ts INTEGER, url TEXT, symbol TEXT, kind TEXT,
        mcap0 REAL, r1h REAL, r24h REAL, max24 REAL, vol_lift REAL, views INTEGER, first_by_kol INTEGER, p0 REAL, bad TEXT);""")
    st = json.dumps({"measured": 6, "hit_rate": .67, "med_max24": 3.24, "rug_rate": .17, "prepump_rate": 0})
    con.execute("INSERT INTO kols VALUES ('ddddddd8a','Dd',4008,58,?,0)", (st,))
    con.execute("INSERT INTO kols VALUES ('spambot','S',10,70,?,1)", (st,))
    con.execute("INSERT INTO kols VALUES ('few','F',10,40,?,0)", (json.dumps({"measured": 1}),))
    now = int(time.time())
    con.execute("INSERT INTO calls VALUES ('1','T1','ddddddd8a',?,'https://x.com/a/1','OLDCOIN','call',50000,.3,.1,1.5,4,900,1,1,NULL)",
                (now - 3 * 86400,))
    con.execute("INSERT INTO calls VALUES ('2','T2','ddddddd8a',?,'https://x.com/a/2','FRESHCOIN','call',50000,.3,.1,1.5,4,900,1,1,NULL)",
                (now - 600,))
    con.commit()
    con.close()
    return p


class Public(unittest.TestCase):
    def setUp(self):
        os.environ["KOL_DB"] = _db()
        os.environ["RENDER_EXTERNAL_URL"] = "https://example.com"
        public._cache.clear()

    def tearDown(self):
        os.environ.pop("KOL_DB", None)
        os.environ.pop("RENDER_EXTERNAL_URL", None)

    def test_leaderboard_and_profile(self):
        code, raw, ctype = public.route("/influencers")
        html = raw.decode()
        self.assertEqual(code, 200)
        self.assertIn("@ddddddd8a", html)
        self.assertNotIn("spambot", html)            # bots out
        self.assertNotIn("/influencer/few", html)    # too few measured calls
        self.assertIn('hreflang=hr href="https://example.com/hr/influenceri"', html)
        code, raw, _ = public.route("/influencer/ddddddd8a")
        html = raw.decode()
        self.assertEqual(code, 200)
        self.assertIn("OLDCOIN", html)
        self.assertNotIn("FRESHCOIN", html)          # fresh calls are members-only
        self.assertIn("1 new calls in the last 24 hours", html)
        self.assertIn("ProfilePage", html)
        hr = public.route("/hr/influencer/ddddddd8a")[1].decode()
        self.assertIn("lang=hr", hr)
        self.assertIn("Zadnji pozivi", hr)
        self.assertEqual(public.route("/influencer/spambot")[0], 404)
        self.assertEqual(public.route("/influencer/<script>")[0], 404)
        self.assertIsNone(public.route("/kol"))

    def test_robots_sitemap(self):
        r = public.route("/robots.txt")[1].decode()
        self.assertIn("Disallow: /", r)
        self.assertIn("Sitemap: https://example.com/sitemap.xml", r)
        sm = public.route("/sitemap.xml")[1].decode()
        self.assertIn("https://example.com/influencer/ddddddd8a", sm)
        self.assertIn("https://example.com/hr", sm)

    def test_landing_english_main(self):
        en = landing.page_html({}, lang="en")
        self.assertIn("Request access", en)
        self.assertIn("lang=en", en)
        self.assertIn('hreflang=x-default href="https://example.com/"', en)
        self.assertIn("Zatraži pristup", landing.page_html({}, lang="hr"))


if __name__ == "__main__":
    unittest.main()
