"""7.11. (Jure): the first thing on Tokeni, Influenceri and Novčanici is what the tool concluded and where to put
money today, with the market cap at analysis time and a live check. No network."""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import prijedlog  # noqa: E402

T = "GhBPHgnNF99EThYxt4bxUfPX1hCPyAS72RCBgLjLpump"


class Prijedlog(unittest.TestCase):
    def _row(self, conf=70, mcap=150_000, age=600, hard=False):
        now = time.time()
        return {"token": T, "symbol": "ARIA", "conf": conf, "mcap": mcap, "last_seen": now - age, "hard": hard,
                "collapse": False, "rug": None, "sansa": 50, "hype": 10, "features": {}, "det": {},
                "conf_parts": [(5, "KOL pozvao"), (3, "volumen raste"), (-2, "mali TG")], "checks": [], "events": []}

    def test_token_picks_filter_and_fields(self):
        ch = {"100–300k": (0.46, 5000)}
        picks = prijedlog.token_picks(rows=[self._row()], status={T: {"has_pair": 1, "mcap": 160_000}}, ch=ch)
        self.assertEqual(len(picks), 1)
        p = picks[0]
        self.assertEqual(p["mcap0"], 160_000)              # the fresh DexScreener number wins
        self.assertEqual(p["why"], ["KOL pozvao", "volumen raste"])
        self.assertEqual(p["chance"], (0.46, 5000))
        self.assertEqual(p["razina"], "visoka")
        # dead pair, rugged and very old rows are never picks; older or weaker ones come graded lower (Jure 7.11.)
        self.assertEqual(prijedlog.token_picks(rows=[self._row()], status={T: {"has_pair": 0}}, ch=ch), [])
        self.assertEqual(prijedlog.token_picks(rows=[self._row(hard=True)], status={}, ch=ch), [])
        self.assertEqual(prijedlog.token_picks(rows=[self._row(age=30 * 3600)], status={}, ch=ch), [])
        self.assertEqual(prijedlog.token_picks(rows=[self._row(age=8 * 3600)], status={}, ch=ch)[0]["razina"], "srednja")
        self.assertEqual(prijedlog.token_picks(rows=[self._row(conf=25)], status={}, ch=ch)[0]["razina"], "niska")
        self.assertEqual(prijedlog.token_picks(rows=[self._row(conf=10)], status={}, ch=ch), [])

    def test_box_and_live_rule(self):
        html = prijedlog.box("tokeni", rows=[self._row()])
        self.assertIn("Prijedlog za danas", html)
        self.assertIn("Analizirao sam", html)
        self.assertIn('data-m0="150000"', html)            # market cap at analysis time travels to the browser
        self.assertIn("/api/prijedlog", html)
        self.assertIn("pričekaj povlačenje", html)
        self.assertIn(str(prijedlog.PULL_X), html)
        for kind in ("influenceri", "novcanici"):
            self.assertIn("Prijedlog za danas", prijedlog.box(kind, rows=[]))

    def test_api_without_tokens(self):
        self.assertEqual(prijedlog.api({}), "{}")


if __name__ == "__main__":
    unittest.main()


class Pregled(unittest.TestCase):
    def test_dashboard_text_and_wallet_views(self):
        html = prijedlog.box("pregled", rows=[])
        self.assertIn("U ovom trenutku", html)
        self.assertIn("Očekivanje i izlaz", html)
        self.assertIn("+15 %", html)
        from ui import pages
        import run_ui  # noqa: F401
        title, body = pages.wallets({})
        self.assertLess(body.find("Za kopiranje"), body.find("Aktivnost"))   # copy list first, activity last
        self.assertIn("Prijedlog za danas", body)
