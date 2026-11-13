import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import html, search  # noqa: E402


class NavTest(unittest.TestCase):
    def test_every_page_in_menu_once_and_natjecanje_visible(self):
        hrefs = [p["href"] for _, items in html.SECTIONS for p in items]
        self.assertEqual(len(hrefs), len(set(hrefs)))
        out = html.page("x", "<h1>x</h1>", "/token/abc")
        # 10.11. (Jure, prijedlog 3.5): the side menu keeps only the core items + Više; Natjecanje is one tap away on
        # the "Više" page (and in the search), not in every page's menu any more
        self.assertIn('href="/vise"', out)
        self.assertIn('href="/natjecanje"', html.vise_page({})[1])
        self.assertIn('<a href="/tokens" class="on">Tokeni</a>', out)
        self.assertIn('id=q name=q', out)

    def test_map_page_lists_all(self):
        _, body = html.map_page({})
        for _, items in html.SECTIONS:
            for p in items:
                self.assertIn(f'href="{p["href"]}"', body)

    def test_logos(self):
        for k in html.LOGOS:
            svg, name = html.logo(20, k)
            self.assertTrue(svg.startswith("<svg") and name)


class SearchTest(unittest.TestCase):
    def setUp(self):
        search._CACHE.clear()
        self.d = tempfile.mkdtemp()
        self.old = search.data.HYPE_DB
        search.data.HYPE_DB = os.path.join(self.d, "hype.db")
        con = sqlite3.connect(search.data.HYPE_DB)
        con.execute("CREATE TABLE hype_signals (ts INTEGER, token TEXT, symbol TEXT, name TEXT, pair TEXT, url TEXT, score REAL)")
        con.executemany("INSERT INTO hype_signals VALUES (?,?,?,?,?,?,?)",
                        [(1, "9xFart1111111111111111111111111111pump", "FARTCOIN", "Fartcoin", "", "", 1),
                         (2, "9xFart1111111111111111111111111111pump", "FARTCOIN", "Fartcoin", "", "", 1),
                         (3, "7yOther111111111111111111111111111pump", "FARTDOG", "Fart Dog", "", "", 1)])
        con.commit()
        con.close()

    def tearDown(self):
        search.data.HYPE_DB = self.old

    def test_pages_without_diacritics(self):
        self.assertEqual(search.pages("potrosnja")[0]["href"], "/usage")
        self.assertEqual(search.pages("natjecanje")[0]["href"], "/natjecanje")

    def test_tokens_by_name_exact_first(self):
        r = search.search("fartcoin")
        self.assertEqual(r["tokens"][0]["sym"], "FARTCOIN")
        self.assertEqual(len({t["mint"] for t in r["tokens"]}), len(r["tokens"]))
        json.loads(search.api("fart"))

    def test_address(self):
        r = search.search("9xFart1111111111111111111111111111pump")
        self.assertTrue(r["addr"])
        self.assertEqual(r["tokens"][0]["sym"], "FARTCOIN")
        _, body = search.page({"q": "1111111111111111111111111111111A"})
        self.assertIn("/wallet/", body)


if __name__ == "__main__":
    unittest.main()
