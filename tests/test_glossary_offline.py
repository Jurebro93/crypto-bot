"""Pojmovnik: every term, column and page is explained; ⓘ pop-ups and charts render."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_ui  # noqa: E402
from ui import charts, glossary as G, glossarypage, html as H  # noqa: E402
from ui.help import HELP  # noqa: E402


class Glossary(unittest.TestCase):
    def test_every_column_and_page_has_an_entry(self):
        for label in HELP:
            self.assertIsNotNone(G.lookup(label), label)
        for _, items in H.SECTIONS:
            for p in items:
                self.assertIsNotNone(G.page_key(p["href"]), p["href"])
        self.assertGreater(len([t for t in G.all_terms() if t["long"]]), 60)

    def test_links_and_categories_are_valid(self):
        cats = {k for k, _, _ in G.CATS}
        for t in G.all_terms():
            self.assertIn(t["cat"], cats, t["k"])
            for v in t["vidi"]:
                self.assertIsNotNone(G.get(v), (t["k"], v))

    def test_lookup_ignores_case_emoji_and_punctuation(self):
        self.assertEqual(G.lookup("Slavnost (Wikidata)"), "slavnost-wikidata")
        self.assertEqual(G.lookup("  moć poziva: "), "moc-poziva")
        self.assertEqual(G.lookup("Likv."), "likvidnost")
        self.assertEqual(G.lookup("💀 RUGAN"), "rug")
        self.assertIsNone(G.lookup("nešto posve nepoznato"))

    def test_fragment_and_page(self):
        f = glossarypage.fragment("sansa-za-token", "Šansa za token", "Procjena 0-1")
        self.assertIn("Šansa za token", f)
        self.assertIn("/pojmovnik#sansa-za-token", f)
        self.assertIn("nepoznato", glossarypage.fragment("", "nepoznato", "<b>x</b>"))
        self.assertNotIn("<b>x</b>", glossarypage.fragment("", "nepoznato", "<b>x</b>"))
        title, body = run_ui.route("/pojmovnik", {})
        self.assertEqual(title, "Pojmovnik")
        self.assertIn('id="slavnost-wikidata"', body)
        self.assertIn('id="k-stupci"', body)

    def test_page_annotates_headings_tiles_and_title(self):
        out = H.page("x", "<h1>KOL-ovi</h1><h2>Koliko ga tržište sluša</h2><div class=l>pogodak</div>"
                          "<h2>Neki naslov bez pojma</h2>", "/kol")
        self.assertIn('data-gk="str-kol"', out)              # whole-page explanation next to the title
        self.assertIn('data-gk="koliko-ga-trziste-slusa"', out)
        self.assertIn('data-gk="pogodak"', out)
        self.assertIn("<h2>Neki naslov bez pojma</h2>", out)
        self.assertIn("id='gl'", H.GL_JS.replace('"', "'"))

    def test_column_header_carries_key(self):
        self.assertIn('data-gk="sansa-za-token"', H.th("Šansa za token"))
        self.assertIn('data-gk="slavnost-wikidata"', H.breakdown([("Slavnost (Wikidata)", 3.0, 25, "x")]))


class Charts(unittest.TestCase):
    def test_line(self):
        out = charts.line([{"name": "A", "pts": [(1_700_000_000, 1.0), (1_700_090_000, 3.0)]},
                           {"name": "B", "pts": [(1_700_000_000, 2.0), (1_700_050_000, 2.5)]}], "Naslov", fmt="num", base=0)
        self.assertIn("polyline", out)
        self.assertIn("Prikaži kao tablicu", out)
        self.assertIn("chlg", out)                           # two series -> legend
        self.assertEqual(charts.line([{"name": "A", "pts": [(1, 1.0)]}], "x"), "")

    def test_bars_cap_outlier(self):
        items = [(1_700_000_000 + i * 3600, f"T{i}", v) for i, v in enumerate([0.1, -0.5, 0.2, 0.3, -0.2, 0.1, 0.4,
                                                                               -0.1, 0.2, 50.0])]
        out = charts.bars(items, "Pozivi")
        self.assertEqual(out.count("<rect"), 10)
        self.assertIn("vrh grafa odrezan", out)
        self.assertIn("u minusu <b>3</b>", out)
        self.assertEqual(charts.bars(items[:1], "x"), "")


if __name__ == "__main__":
    unittest.main()
