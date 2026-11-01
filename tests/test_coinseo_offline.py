"""Coin SEO pages (price prediction, how to buy, rug check, hubs, daily lists): routes, links, sitemap. No network."""
import os
import re
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import coins, coinseo, public  # noqa: E402
from tests.test_coins_offline import LIST  # noqa: E402

PAGES = ["/coin/bonk/price-prediction", "/hr/coin/bonk/prognoza", "/how-to-buy/bonk", "/hr/kako-kupiti/bonk",
         "/rug-check/bonk", "/hr/provjera/bonk", "/how-to-buy", "/hr/kako-kupiti", "/rug-check", "/hr/provjera",
         "/solana-meme-coins/gainers", "/hr/solana-meme-coini/rastuci", "/solana-meme-coins/trending",
         "/hr/solana-meme-coini/popularni", "/solana-meme-coins/new", "/hr/solana-meme-coini/novi"]


class CoinSeo(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        coins.DB = os.path.join(d, "public.db")
        os.environ["KOL_DB"] = os.path.join(d, "kol.db")
        os.environ["DUGO_DB"] = os.path.join(d, "dugo.db")
        os.environ["RENDER_EXTERNAL_URL"] = "https://example.com"
        public._cache.clear()
        coins.store(coins.pick(LIST), now=int(time.time()))

    def tearDown(self):
        os.environ.pop("RENDER_EXTERNAL_URL", None)

    def test_pages_render_with_pairs(self):
        for path in PAGES:
            code, raw, ctype = public.route(path)
            html = raw.decode()
            self.assertEqual((code, ctype), (200, "text/html"), path)
            self.assertRegex(html, r'hreflang="?hr', path)
            self.assertIn("<h1>", html, path)

    def test_unknown_coin_404(self):
        for path in ("/how-to-buy/nope", "/rug-check/nope", "/coin/nope/price-prediction", "/hr/provjera/../x"):
            r = public.route(path)
            self.assertTrue(r is None or r[0] == 404, path)

    def test_buy_page_links_exchange_article(self):
        en = public.route("/how-to-buy/bonk")[1].decode()
        hr = public.route("/hr/kako-kupiti/bonk")[1].decode()
        self.assertIn(coinseo.EXCH_EN, en)
        self.assertIn(coinseo.EXCH_HR, hr)
        self.assertIn("BonkMint111", en)                                   # real contract address
        self.assertEqual(public.route(coinseo.EXCH_EN)[0], 200)
        self.assertEqual(public.route(coinseo.EXCH_HR)[0], 200)

    def test_rug_check_counts(self):
        html = public.route("/rug-check/bonk")[1].decode()
        self.assertRegex(html, r"\d of \d checks passed")

    def test_coin_page_and_list_link_cluster(self):
        self.assertIn("/coin/bonk/price-prediction", public.route("/coin/bonk")[1].decode())
        self.assertIn("/solana-meme-coins/gainers", public.route("/solana-meme-coins")[1].decode())

    def test_internal_links_resolve(self):
        html = public.route("/how-to-buy/bonk")[1].decode()
        for href in set(re.findall(r"href=(/(?:coin|how-to-buy|rug-check)/[a-z0-9\-/]+)", html)):
            self.assertEqual(public.route(href)[0], 200, href)

    def test_sitemap_and_robots(self):
        sm = public.route("/sitemap.xml")[1].decode()
        for p in ("/coin/bonk/price-prediction", "/hr/kako-kupiti/bonk", "/rug-check/pengu", "/solana-meme-coins/new"):
            self.assertIn(f"https://example.com{p}<", sm, p)
        rb = public.route("/robots.txt")[1].decode()
        self.assertIn("Allow: /how-to-buy\n", rb)
        self.assertIn("Allow: /hr/provjera\n", rb)

    def test_cex_names_only_well_known(self):
        import json
        names = json.dumps(["aivora-exchange", "bitbaby-exchange", "binance", "gdax", "okex", "bybit-eu"])
        txt = coinseo.cex_text({"cex": (40, names)}, "hr", "TRUMP")
        self.assertIn("Coinbase (EU licenca)", txt)
        self.assertIn("Binance", txt)
        self.assertNotIn("aivora", txt.lower())
        self.assertNotIn("[", txt)
        small = coinseo.cex_text({"cex": (3, json.dumps(["aivora-exchange"]))}, "en", "X")
        self.assertNotIn("aivora", small.lower())
        self.assertEqual(coinseo.cex_short(names), " · Binance, Coinbase, OKX, Bybit EU")


if __name__ == "__main__":
    unittest.main()
