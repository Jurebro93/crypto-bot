"""Autopilot: a tap on a token loads the chart (13.11., Jure: "Kako da odaberem token da bi se prikazao graf kad gdje
god kliknem otvori mi novi pop-up i onda ako kliknem na token odvede me na DexScreener"). The behaviour itself was
checked in Chromium (row name -> chart, Kupi in the row -> Kupi, "provjera" -> pop-up, /token/ link -> chart).

    python3 -m unittest tests.test_graf_odabir_offline
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class GrafOdabir(unittest.TestCase):
    def test_ap_js_catches_token_taps_before_the_pop_up(self):
        js = open(os.path.join(HERE, "ui", "static", "ap", "ap.js"), encoding="utf-8").read()
        self.assertIn("""'[data-pop^="/pravi-trade/token?"], a[href^="/token/"], [data-sel]'""", js)
        self.assertIn("}, true);", js)                      # capture phase: the pop-up handler never sees it
        self.assertIn("[data-popkeep]", js)
        self.assertIn("el.contains(inner)", js)             # Kupi / Uredi inside a row keep their own job

    def test_provjera_keeps_the_pop_up_and_the_pop_up_offers_the_chart(self):
        src = open(os.path.join(HERE, "ui", "apterm.py"), encoding="utf-8").read()
        self.assertIn('tabindex=0 data-popkeep{pt._pop(z["token"])}>provjera', src)
        pt = open(os.path.join(HERE, "ui", "pravitrade.py"), encoding="utf-8").read()
        self.assertIn('data-sel="{esc(mint)}">Prikaži na grafu</a>', pt)


if __name__ == "__main__":
    unittest.main()
