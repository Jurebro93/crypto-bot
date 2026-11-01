"""Public top Solana meme coins: picking from the Jupiter list, storing with stable slugs, pages, sitemap. No network."""
import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import coins, public  # noqa: E402


def tok(mint, sym, mcap, liq=500_000, holders=50_000, vol=200_000, tags=("meme", "verified"), **kw):
    t = {"id": mint, "symbol": sym, "name": kw.get("name", sym.title()), "icon": "https://img.example/x.png",
         "mcap": mcap, "fdv": mcap, "usdPrice": kw.get("price", 0.0123), "liquidity": liq, "holderCount": holders,
         "tags": list(tags), "organicScore": 80,
         "audit": {"mintAuthorityDisabled": True, "freezeAuthorityDisabled": True, "topHoldersPercentage": 22.5},
         "stats5m": {"priceChange": 0.1, "holderChange": 0.01}, "stats1h": {"priceChange": 1.0, "holderChange": 0.1},
         "stats6h": {"priceChange": -2.0, "holderChange": 0.3},
         "stats24h": {"priceChange": 5.0, "holderChange": 1.0, "buyVolume": vol / 2, "sellVolume": vol / 2,
                      "numBuys": 100, "numSells": 90, "numTraders": 50}}
    return t


LIST = [tok("PengMint111", "PENGU", 500e6, liq=3e6, name="Pudgy Penguins"), tok("BonkMint111", "Bonk", 250e6),
        tok("FakeMint111", "GOHOME", 760e6, liq=300_000),                       # liquidity 0.04% of mcap: fake mcap
        tok("DeadMint111", "DEAD", 5e6, vol=500),                               # nobody trades it
        tok("Stable11111", "USDX", 900e6, tags=("stable", "verified")),         # not a meme
        tok("abcdefpump", "PUMPY", 3e6, tags=("verified",)),                    # pump.fun launch counts as meme
        tok("BadMint1111", "NIGGACOIN", 9e6), tok("Thin1111111", "THIN", 9e6, holders=20)]


class Coins(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        coins.DB = os.path.join(d, "public.db")
        os.environ["KOL_DB"] = os.path.join(d, "kol.db")
        os.environ["DUGO_DB"] = os.path.join(d, "dugo.db")
        os.environ["RENDER_EXTERNAL_URL"] = "https://example.com"
        public._cache.clear()

    def test_pick_filters_fakes_and_non_memes(self):
        self.assertEqual([t["symbol"] for t in coins.pick(LIST)], ["PENGU", "Bonk", "PUMPY"])

    def test_store_keeps_slugs_and_drops_rank(self):
        coins.store(coins.pick(LIST), now=1000)
        self.assertEqual([r["slug"] for r in coins.top()], ["pengu", "bonk", "pumpy"])
        coins.store([tok("PengMint111", "PENGU2", 400e6), tok("OtherPengu1", "PENGU", 100e6)], now=2000)
        rows = coins.top()
        self.assertEqual([r["slug"] for r in rows], ["pengu", "pengu-othe"])     # slug stays with the mint
        r, hist = coins.coin("bonk")                                            # dropped out: page stays, no rank
        self.assertIsNone(r["rank"])
        self.assertEqual(len(coins.coin("pengu")[1]), 2)

    def test_pages_routes_sitemap(self):
        coins.store(coins.pick(LIST), now=int(time.time()))
        con = sqlite3.connect(os.environ["KOL_DB"])
        con.executescript("""CREATE TABLE kols (handle TEXT PRIMARY KEY, score REAL, bot INTEGER);
            CREATE TABLE calls (tweet_id TEXT, token TEXT, handle TEXT, ts INTEGER, url TEXT, kind TEXT, mcap0 REAL,
            r1h REAL, r24h REAL, max24 REAL);""")
        now = int(time.time())
        con.execute("INSERT INTO calls VALUES ('1','PengMint111','oldcaller',?,'u','call',1e8,.1,.2,.5)", (now - 3 * 86400,))
        con.execute("INSERT INTO calls VALUES ('2','PengMint111','freshcaller',?,'u','call',1e8,.1,.2,.5)", (now - 60,))
        con.commit()
        con.close()
        code, body, _ = public.route("/solana-meme-coins")
        html = body.decode()
        self.assertEqual(code, 200)
        for s in ("Top Solana meme coins", "/coin/pengu", "Pudgy Penguins", "ItemList", 'hreflang=hr'):
            self.assertIn(s, html)
        self.assertNotIn("GOHOME", html)
        code, body, _ = public.route("/coin/pengu")
        html = body.decode()
        self.assertEqual(code, 200)
        for s in ("PENGU price, market cap", "is Pudgy Penguins safe?", "PengMint111", "revoked", "@oldcaller",
                  "FAQPage", "last 24 hours", "<svg", "1 influencer calls from the last 24 hours", "/coin/bonk"):
            self.assertIn(s, html)
        self.assertNotIn("freshcaller", html)                                  # fresh calls stay members-only
        self.assertIn("je li Pudgy Penguins siguran", public.route("/hr/coin/pengu")[1].decode())
        self.assertEqual(public.route("/coin/nope")[0], 404)
        self.assertIn((public.route("/coin/../etc") or [404])[0], (404,))      # never a page
        sm = public.route("/sitemap.xml")[1].decode()
        self.assertIn("https://example.com/coin/pengu", sm)
        self.assertIn("https://example.com/solana-meme-coins", sm)
        self.assertIn("Allow: /coin/", public.route("/robots.txt")[1].decode())

    def test_day_series_and_price_format(self):
        row = {"updated": 10_000, "win": '{"24h": [100, 0], "6h": [0, 0], "1h": [null, 0], "5m": [0, 0]}'}
        pts = coins.day_series(row, 0, 2.0)
        self.assertEqual(pts[0], (10_000 - 86400, 1.0))                        # +100% in 24 h: was half
        self.assertEqual(pts[-1], (10_000, 2.0))
        self.assertEqual(coins.day_series({"win": "{}"}, 0, 1.0), [])
        self.assertEqual(public._price(0.007281087393), "$0.007281")
        self.assertEqual(public._price(0.0000029244), "$0.000002924")
        self.assertEqual(public._price(1.6912), "$1.69")


if __name__ == "__main__":
    unittest.main()
