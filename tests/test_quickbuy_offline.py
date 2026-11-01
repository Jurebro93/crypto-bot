"""Natjecanje quick buying: suggested strong tokens with one-click buy, copy-address buttons, token-page buy box."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dugo import store as dstore  # noqa: E402
from league import store  # noqa: E402
from ui import league, quickbuy  # noqa: E402

FART = "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump"
JAKI = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"


class QuickBuy(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        store.DB = os.path.join(tmp, "league.db")
        dstore.DB = os.path.join(tmp, "dugo.db")
        con = dstore.connect()
        con.execute("INSERT INTO tokens (mint, symbol) VALUES (?,?)", (JAKI, "JUP"))
        con.execute("INSERT INTO tokens (mint, symbol) VALUES (?,?)", (FART, "FARTCOIN"))
        for m, kind, rank in ((FART, "dugorocni", 1), (JAKI, "jaki", 1)):
            con.execute("INSERT INTO snap (day, mint, kind, rank, mcap, features, why) VALUES (?,?,?,?,?,?,?)",
                        (20000, m, kind, rank, 9e8, json.dumps({"povrat_30d": 0.12}), "stalan volumen"))
        con.commit()
        con.close()
        league.market = lambda mints: {m: (2.0, 1e6, None, 2e6) for m in mints}
        league._suggestions = lambda qs: []

    def test_strong_list(self):
        got = quickbuy.strong()
        self.assertEqual(got[0]["mint"], FART)         # the role model first, once
        self.assertEqual([t["mint"] for t in got].count(FART), 1)
        self.assertIn(JAKI, [t["mint"] for t in got])

    def test_natjecanje_cards_and_token_box(self):
        body = league.page({}, "Jure")[1]
        self.assertIn("Predloženi tokeni", body)
        self.assertIn(f'name=token value="{JAKI}"', body)
        self.assertIn(f'data-m="{FART}"', body)          # copy-address button
        guest = league.page({}, None)[1]
        self.assertIn("Prijavi se za kupnju", guest)
        box = quickbuy.token_box(JAKI, "JUP")
        self.assertIn("Kupi kao moj trade", box)
        self.assertIn(f'name=back value="/token/{JAKI}"', box)
        self.assertIn("zaključana", quickbuy.token_box(JAKI, "JUP", "token je rugan"))
        self.assertEqual(quickbuy.token_box("../x", "X"), "")

    def test_buy_from_token_page_returns_there(self):
        loc = league.post("/natjecanje/buy", {"token": JAKI, "size": "50", "back": f"/token/{JAKI}"}, "Ivan")
        self.assertTrue(loc.startswith(f"/token/{JAKI}?ok="), loc)
        loc = league.post("/natjecanje/buy", {"token": FART, "size": "50", "back": "https://evil.example"}, "Ivan")
        self.assertTrue(loc.startswith("/natjecanje?ok="), loc)
        self.assertIn("err=", league.post("/natjecanje/buy", {"token": JAKI, "size": "50", "back": f"/token/{JAKI}"}, None))


if __name__ == "__main__":
    unittest.main()
