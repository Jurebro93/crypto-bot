"""Own domain: public pages on onrender.com move to SITE_URL with a 301; the app stays where it is."""
import importlib
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class SiteUrl(unittest.TestCase):
    def test_moved(self):
        old = dict(os.environ)
        os.environ["SITE_URL"] = "https://memesonar.app/"
        os.environ["RENDER_EXTERNAL_URL"] = "https://crypto-bot-ylvn.onrender.com"
        try:
            import run_ui
            importlib.reload(run_ui)
            m = run_ui.moved_to_site
            self.assertEqual(os.environ["RENDER_EXTERNAL_URL"], "https://memesonar.app")
            on = "crypto-bot-ylvn.onrender.com"
            self.assertEqual(m(on, "/coin/pengu", False), "https://memesonar.app/coin/pengu")
            self.assertEqual(m(on, "/", False), "https://memesonar.app/")
            self.assertEqual(m(on, "/hr/rjecnik", True), "https://memesonar.app/hr/rjecnik")
            self.assertIsNone(m(on, "/", True))                 # logged-in dashboard stays
            self.assertIsNone(m(on, "/natjecanje", False))      # app pages stay
            self.assertIsNone(m(on, "/prijava", False))
            self.assertIsNone(m("memesonar.app", "/coin/pengu", False))
            self.assertEqual(m("www.memesonar.app", "/natjecanje", True), "https://memesonar.app/natjecanje")
            self.assertIsNone(m("localhost:8050", "/blog", False))
        finally:
            os.environ.clear()
            os.environ.update(old)
            import run_ui
            importlib.reload(run_ui)

    def test_app_host(self):
        old = dict(os.environ)
        os.environ["SITE_URL"] = "https://memesonar.app"
        os.environ["APP_URL"] = "https://app.memesonar.app/"
        os.environ["RENDER_EXTERNAL_URL"] = "https://crypto-bot-ylvn.onrender.com"
        try:
            import run_ui
            importlib.reload(run_ui)
            m, S, A = run_ui.moved_to_site, "https://memesonar.app", "https://app.memesonar.app"
            site, app, on = "memesonar.app", "app.memesonar.app", "crypto-bot-ylvn.onrender.com"
            # public site: landing at "/" always, public pages stay, app pages go to the app host
            self.assertIsNone(m(site, "/", True))
            self.assertIsNone(m(site, "/blog/what-is-pump-fun", False))
            self.assertIsNone(m(site, "/solana-market", False))
            self.assertIsNone(m(site, "/static/landing/kol.jpg", False))
            self.assertEqual(m(site, "/dobrodosli", False), S + "/hr")
            self.assertEqual(m(site, "/natjecanje", True), A + "/natjecanje")
            self.assertEqual(m(site, "/prijava", False), A + "/prijava")
            self.assertEqual(m(site, "/registracija", False), A + "/registracija")
            self.assertTrue(run_ui.on_site_host("memesonar.app"))
            self.assertFalse(run_ui.on_site_host("app.memesonar.app"))
            # app host: dashboard at "/", public pages go to the site
            self.assertIsNone(m(app, "/", True))
            self.assertIsNone(m(app, "/", False))
            self.assertIsNone(m(app, "/natjecanje", True))
            self.assertIsNone(m(app, "/static/landing/kol.jpg", False))
            self.assertEqual(m(app, "/coin/pengu", False), S + "/coin/pengu")
            self.assertEqual(m(app, "/dobrodosli", True), S + "/hr")
            # old onrender address and www
            self.assertEqual(m(on, "/", True), A + "/")
            self.assertEqual(m(on, "/", False), S + "/")
            self.assertEqual(m(on, "/natjecanje", True), A + "/natjecanje")
            self.assertEqual(m(on, "/blog", False), S + "/blog")
            self.assertEqual(m("www.memesonar.app", "/tokens", False), A + "/tokens")
            from ui import urls, html
            self.assertEqual(urls.app_link("/prijava"), A + "/prijava")
            self.assertEqual(urls.home_link(), S + "/")
        finally:
            os.environ.clear()
            os.environ.update(old)
            import run_ui
            importlib.reload(run_ui)


if __name__ == "__main__":
    unittest.main()
