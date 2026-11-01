"""Google Search Console (analytics/gsc.py + ui/analitika.py) without the network: key parsing, error messages,
collect() into a temp analytics.db with a fake API, the page in its three states, menu + glossary."""
import base64
import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analytics import gsc  # noqa: E402

KEY = {"type": "service_account", "client_email": "memesonar-gsc@proj.iam.gserviceaccount.com",
       "private_key": "-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----\n", "token_uri": gsc.TOKEN_URI}
TODAY = dt.date(2026, 11, 20)


def fake_query(start, end, dims=(), limit=1000, site_url=None):
    if dims == ("date",):
        out, d = [], start
        while d <= end:
            n = (d - start).days
            out.append({"keys": [str(d)], "clicks": n % 7, "impressions": 100 + n, "ctr": 0.03, "position": 12.0})
            d += dt.timedelta(days=1)
        return out
    k = dims[0]
    recent = start > TODAY - dt.timedelta(days=40)
    rows = {"query": [("solana meme coins", 30, 900, 12.4), ("memesonar", 20, 40, 1.1), ("bonk price", 0, 300, 8.0)],
            "page": [("https://memesonar.app/solana-meme-coins", 40, 1000, 9.0)],
            "country": [("hrv", 10, 50, 3.0)], "device": [("MOBILE", 30, 800, 10.0)]}[k]
    if not recent:
        rows = rows[:1]
    return [{"keys": [a], "clicks": c, "impressions": i, "ctr": c / i, "position": p} for a, c, i, p in rows]


class KeyTest(unittest.TestCase):
    def test_missing_raw_and_base64(self):
        with mock.patch.dict(os.environ, {"GSC_SERVICE_ACCOUNT_JSON": ""}):
            self.assertIsNone(gsc.key_info())
            self.assertFalse(gsc.configured())
        with mock.patch.dict(os.environ, {"GSC_SERVICE_ACCOUNT_JSON": json.dumps(KEY)}):
            self.assertEqual(gsc.account_email(), KEY["client_email"])
        b64 = base64.b64encode(json.dumps(KEY).encode()).decode()
        with mock.patch.dict(os.environ, {"GSC_SERVICE_ACCOUNT_JSON": b64}):
            self.assertEqual(gsc.key_info()["client_email"], KEY["client_email"])

    def test_bad_key_plain_croatian(self):
        for raw in ("{not json", json.dumps({"type": "authorized_user"}), "%%%"):
            with mock.patch.dict(os.environ, {"GSC_SERVICE_ACCOUNT_JSON": raw}):
                with self.assertRaises(gsc.GscError):
                    gsc.key_info()

    def test_site_from_site_url(self):
        with mock.patch.dict(os.environ, {"SITE_URL": "https://www.memesonar.app", "GSC_SITE": ""}):
            self.assertEqual(gsc.site(), "sc-domain:memesonar.app")
        with mock.patch.dict(os.environ, {"GSC_SITE": "https://memesonar.app/"}):
            self.assertEqual(gsc.site(), "https://memesonar.app/")

    def test_real_jwt_signing(self):
        """The google-auth signer accepts a real PKCS#8 key and the token exchange gets a signed JWT."""
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        pk = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = pk.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                               serialization.NoEncryption()).decode()
        seen = {}

        def post(url, data):
            seen.update(data)
            return {"access_token": "tok", "expires_in": 3600}
        gsc._tok.update(value=None, exp=0)
        with mock.patch.dict(os.environ, {"GSC_SERVICE_ACCOUNT_JSON": json.dumps(dict(KEY, private_key=pem))}), \
                mock.patch.object(gsc, "_post_form", post):
            self.assertEqual(gsc.token(), "tok")
        self.assertEqual(seen["assertion"].count("."), 2)
        claims = json.loads(base64.urlsafe_b64decode(seen["assertion"].split(".")[1] + "=="))
        self.assertEqual(claims["scope"], gsc.SCOPE)
        self.assertEqual(claims["iss"], KEY["client_email"])
        gsc._tok.update(value=None, exp=0)


class CollectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "analytics.db")

    def test_collect_and_error_keeps_data(self):
        n = gsc.collect(self.db, TODAY, fake_query)
        self.assertGreater(n, 400)    # first run takes the whole 16 months
        con = gsc.connect(self.db)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM gsc_top WHERE kind='query' AND period='cur'").fetchone()[0], 3)
        m = gsc.meta(con)
        self.assertTrue(m["last_ok"])
        con.close()

        def boom(*a, **k):
            raise gsc.GscError("Račun nema pristup")
        with self.assertRaises(gsc.GscError):
            gsc.collect(self.db, TODAY, boom)
        con = gsc.connect(self.db)
        self.assertEqual(gsc.meta(con)["last_error"], "Račun nema pristup")
        self.assertGreater(con.execute("SELECT COUNT(*) FROM gsc_daily").fetchone()[0], 400)
        con.close()

    def test_periods_skip_lag(self):
        cs, ce, ps, pe = gsc.periods(TODAY)
        self.assertEqual(ce, TODAY - dt.timedelta(days=3))
        self.assertEqual((ce - cs).days, 27)
        self.assertEqual(pe, cs - dt.timedelta(days=1))

    def test_page_states(self):
        from ui import analitika
        with mock.patch.object(gsc, "DB", self.db), mock.patch.dict(os.environ, {"GSC_SERVICE_ACCOUNT_JSON": ""}):
            _, body = analitika.page({})
            self.assertIn("Kako spojiti Google Search Console", body)
            self.assertIn("GSC_SERVICE_ACCOUNT_JSON", body)
        with mock.patch.object(gsc, "DB", self.db), \
                mock.patch.dict(os.environ, {"GSC_SERVICE_ACCOUNT_JSON": json.dumps(KEY)}):
            _, body = analitika.page({})
            self.assertIn("Ključ je postavljen", body)
            gsc.collect(self.db, TODAY, fake_query)
            with mock.patch.object(gsc.dt, "date", wraps=dt.date) as d:
                d.today.return_value = TODAY
                _, body = analitika.page({})
        for s in ("Klikovi", "Prikazi", "Prosječna pozicija", "solana meme coins", "Blizu vrha", "/solana-meme-coins",
                  "📱 Mobitel", "HRV", "novo"):
            self.assertIn(s, body)
        near = body.split("Blizu vrha")[1].split("<h2>")[0]
        self.assertIn("bonk price", near)
        self.assertNotIn(">memesonar<", near)   # position 1.1 is already on top


class WiringTest(unittest.TestCase):
    def test_route_menu_glossary(self):
        import run_ui
        from ui import glossary, html
        self.assertEqual(run_ui.route("/analitika", {})[0], "Analitika")
        self.assertIn("/analitika", html._pages_json())
        for k in ("google-search-console", "klikovi", "prikazi", "ctr", "prosjecna-pozicija", "upit"):
            self.assertTrue(glossary.get(k), k)
        self.assertEqual(glossary.lookup("Prosj. pozicija"), "prosjecna-pozicija")
        self.assertEqual(glossary.lookup("Pozicija"), "pozicija")   # trading term untouched


if __name__ == "__main__":
    unittest.main()
