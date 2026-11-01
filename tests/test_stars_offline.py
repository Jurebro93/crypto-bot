"""Stars (famous influencers): their own X query with ticker matching, and the Stars / Rising stars tabs."""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import collect, store  # noqa: E402
from ui import coins, public  # noqa: E402


def tweet(tid, handle, text, followers=900_000):
    return {"id": tid, "createdAt": time.strftime("%a %b %d %H:%M:%S +0000 %Y", time.gmtime(time.time() - 600)),
            "fullText": text, "author": {"userName": handle, "followers": followers, "name": handle}}


class Stars(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        coins.DB = os.path.join(d, "public.db")
        con = coins.connect()
        con.execute("INSERT INTO coins (mint, slug, symbol, name, rank, mcap) VALUES "
                    "('WifMint1111111111111111111111111111111111111', 'wif', '$WIF', 'dogwifhat', 1, 1e9)")
        con.execute("INSERT INTO coins (mint, slug, symbol, name, rank, mcap) VALUES "
                    "('BonkMint111111111111111111111111111111111111', 'bonk', 'Bonk', 'Bonk', 2, 1e9)")
        con.commit()
        con.close()
        self.con = store.connect(os.path.join(d, "kol.db"))

    def test_stars_query_and_tickers(self):
        seen = {}

        def run(source, actor, inp, **kw):
            seen["q"] = inp["searchTerms"][0]
            return [tweet("1", "MustStopMurad", "$WIF is the one. Not selling."),
                    tweet("2", "blknoiz06", "bags: $WIF $BONK $POPCAT"),            # list of tickers: commentary
                    tweet("3", "frankdegods", "gm")]
        cfg = {"stars": {"handles": ["MustStopMurad", "blknoiz06", "frankdegods"]}}
        n = collect.stars(self.con, cfg, run=run)
        self.assertIn("from:MustStopMurad OR from:blknoiz06", seen["q"])
        self.assertEqual(n, 1)
        row = self.con.execute("SELECT handle, token, match FROM calls").fetchone()
        self.assertEqual(tuple(row), ("MustStopMurad", "WifMint1111111111111111111111111111111111111", "ticker"))
        self.assertEqual(collect.stars(self.con, cfg, run=run), 0)                  # not due again for 3 h

    def test_tabs(self):
        p = os.path.join(tempfile.mkdtemp(), "kol.db")
        con = sqlite3.connect(p)
        con.executescript("""CREATE TABLE kols (handle TEXT PRIMARY KEY, name TEXT, followers INTEGER, score REAL,
            stats TEXT, bot INTEGER);
            CREATE TABLE calls (tweet_id TEXT, token TEXT, handle TEXT, ts INTEGER, url TEXT, symbol TEXT, kind TEXT,
            mcap0 REAL, r1h REAL, r24h REAL, max24 REAL, vol_lift REAL, views INTEGER, first_by_kol INTEGER, p0 REAL,
            bad TEXT);""")
        con.execute("INSERT INTO kols VALUES ('MustStopMurad','M',800000,40,?,0)", (json.dumps({"measured": 1}),))
        con.execute("INSERT INTO kols VALUES ('smallgem','S',4000,60,?,0)", (json.dumps({"measured": 5}),))
        old = int(time.time()) - 3 * 86400
        con.execute("INSERT INTO calls VALUES ('1','T','MustStopMurad',?,'u','X','call',1e6,-.1,-.2,.1,1,1,1,1,NULL)", (old,))
        con.execute("INSERT INTO calls VALUES ('2','T','smallgem',?,'u','X','call',1e5,.3,.2,1.5,1,1,1,1,NULL)", (old,))
        con.commit()
        con.close()
        os.environ["KOL_DB"] = p
        public._cache.clear()
        html = public.route("/influencers")[1].decode()
        for s in ("Rising stars (1)", "Stars (1)", "@smallgem", "@MustStopMurad", "/glossary/priority-fee",
                  "Why the biggest names are harder to profit from", "@blknoiz06"):
            self.assertIn(s, html)
        self.assertIn("Zvijezde (1)", public.route("/hr/influenceri")[1].decode())
        self.assertEqual(public.route("/influencer/MustStopMurad")[0], 200)        # star with one measured call


if __name__ == "__main__":
    unittest.main()
