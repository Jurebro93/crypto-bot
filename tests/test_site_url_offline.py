"""Own domain: public pages on onrender.com move to SITE_URL with a 301; the app stays where it is."""
import importlib
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class SiteUrl(unittest.TestCase):
    def test_moved(self):
        old = dict(os.environ)
        os.environ["SITE_URL"] = "https://kriptoradar.app/"
        os.environ["RENDER_EXTERNAL_URL"] = "https://crypto-bot-ylvn.onrender.com"
        try:
            import run_ui
            importlib.reload(run_ui)
            m = run_ui.moved_to_site
            self.assertEqual(os.environ["RENDER_EXTERNAL_URL"], "https://kriptoradar.app")
            on = "crypto-bot-ylvn.onrender.com"
            self.assertEqual(m(on, "/coin/pengu", False), "https://kriptoradar.app/coin/pengu")
            self.assertEqual(m(on, "/", False), "https://kriptoradar.app/")
            self.assertEqual(m(on, "/hr/rjecnik", True), "https://kriptoradar.app/hr/rjecnik")
            self.assertIsNone(m(on, "/", True))                 # logged-in dashboard stays
            self.assertIsNone(m(on, "/natjecanje", False))      # app pages stay
            self.assertIsNone(m(on, "/prijava", False))
            self.assertIsNone(m("kriptoradar.app", "/coin/pengu", False))
            self.assertEqual(m("www.kriptoradar.app", "/natjecanje", True), "https://kriptoradar.app/natjecanje")
            self.assertIsNone(m("localhost:8050", "/blog", False))
        finally:
            os.environ.clear()
            os.environ.update(old)
            import run_ui
            importlib.reload(run_ui)


if __name__ == "__main__":
    unittest.main()
