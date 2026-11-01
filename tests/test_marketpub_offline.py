"""Public market pages (ui/marketpub.py): built from a synthetic market.db + kol.db, both languages, routing, sitemap,
robots, one menu row, embeds, no private data."""
import math
import re
import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market import regime, store  # noqa: E402
from ui import marketpub as M  # noqa: E402
from ui import public, sitenav  # noqa: E402

D = 86400
NOW = int(time.time())
DAY = NOW // D * D - D


def _market(path):
    con = store.connect(path)
    plats = [("pump.fun", "pump.fun", "Launchpad", "launchpad"), ("launchlab", "LaunchLab", "Launchpad", "launchpad"),
             ("meteora-dynamic-bonding-curve", "Meteora Dynamic Bonding Curve", "Launchpad", "launchpad"),
             ("tiny", "Tiny", "Launchpad", "launchpad"), ("raydium-amm", "Raydium AMM", "Dexs", "dex"),
             ("pumpswap", "PumpSwap", "Dexs", "dex"), ("axiom", "Axiom", "Trading App", "terminal")]
    con.executemany("INSERT INTO platforms VALUES (?,?,?,?)", plats)
    rows = []
    for i in range(200):
        d = DAY - i * D
        w = 1 + 0.3 * math.sin(i / 9)
        vols = {"pump.fun": 120e6 * w, "launchlab": 8e6 * w, "meteora-dynamic-bonding-curve": 9e6, "tiny": 100.0,
                "raydium-amm": 900e6 * w, "pumpswap": 300e6 * w, "axiom": 40e6}
        rows += [(d, s, v) for s, v in vols.items()]
        rows += [(d, "all:launchpad", vols["pump.fun"] + vols["launchlab"] + vols["meteora-dynamic-bonding-curve"] + 100),
                 (d, "all:dex", vols["raydium-amm"] + vols["pumpswap"]), (d, "all:terminal", vols["axiom"])]
        con.execute("INSERT INTO price VALUES (?,?)", (d, 150 + 10 * math.sin(i / 7)))
    con.executemany("INSERT INTO daily VALUES (?,?,?)", rows)
    regime.compute_all(con)
    con.commit()
    con.close()


def _kol(path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE token_hours (token TEXT, hour INTEGER, volume REAL, updated INTEGER)")
    con.execute("CREATE TABLE kols (handle TEXT PRIMARY KEY, bot INTEGER)")
    con.execute("CREATE TABLE calls (tweet_id TEXT, token TEXT, handle TEXT, ts INTEGER, kind TEXT, first_by_kol INTEGER, "
                "max24 REAL)")
    for t in range(40):
        con.executemany("INSERT INTO token_hours VALUES (?,?,?,?)",
                        [(f"tok{t}", h, 900.0 if h >= 14 else 100.0, NOW) for h in range(24)])
    con.executemany("INSERT INTO kols VALUES (?,?)", [("good", 0), ("scanbot", 1)])
    rows = []
    for i in range(600):
        ts = NOW - 2 * D - i * 1800
        hr = (ts // 3600) % 24
        rows.append((f"t{i}", f"tok{i}", "good", ts, "call", 1, 1.0 if hr >= 14 and i % 2 else 0.1))
        rows.append((f"b{i}", f"tok{i}", "scanbot", ts, "call", 1, 5.0))     # bot: must not count
    rows.append(("fresh", "tokX", "good", NOW - 3600, "call", 1, 9.0))           # younger than 24 h: must not count
    con.executemany("INSERT INTO calls VALUES (?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


class MarketPub(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.mdb, cls.kdb = os.path.join(cls.tmp, "market.db"), os.path.join(cls.tmp, "kol.db")
        _market(cls.mdb)
        _kol(cls.kdb)
        cls.old = store.DB, os.environ.get("KOL_DB")
        store.DB = cls.mdb
        os.environ["KOL_DB"] = cls.kdb
        M.snapshot(force=True)
        public._cache.clear()

    @classmethod
    def tearDownClass(cls):
        store.DB = cls.old[0]
        if cls.old[1] is None:
            os.environ.pop("KOL_DB", None)
        else:
            os.environ["KOL_DB"] = cls.old[1]
        M._cache.update(t=0, d=None)
        public._cache.clear()

    def test_snapshot(self):
        d = M.snapshot()
        self.assertEqual(d["day"], DAY)
        self.assertTrue(d["regime"])
        self.assertEqual(d["top_lp"][0], "pump.fun")
        self.assertNotIn("tiny", [p["slug"] for p in d["plats"]["launchpad"]])   # dust hidden
        h = d["hours"]
        self.assertEqual(h["ntok"], 40)
        self.assertAlmostEqual(sum(h["vol"]), 1.0, places=6)
        self.assertGreater(h["vol"][15], h["vol"][3])
        self.assertEqual(h["n"], 600)                       # no bot, no call younger than 24 h
        self.assertEqual(max(h["sess"], key=lambda s: h["sess"][s]["rate"]), "us")

    def test_pages_both_languages(self):
        for key, (en, hr) in M.PAGES.items():
            for path, lang in ((en, "en"), (hr, "hr")):
                code, body, ctype = public.route(path)
                html = body.decode()
                self.assertEqual(code, 200, path)
                self.assertIn(f"<html lang={lang}>", html)
                self.assertIn(f'hreflang=en href="{os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")}{en}"', html)
                self.assertIn('"@type": "FAQPage"', html)
                self.assertIn('"@type": "Dataset"', html)
                self.assertIn("class=fcols", html)
                self.assertIn("#pristup", html)
                for other in M.PAGES.values():           # every market page links every other one
                    self.assertIn(f"href={other[lang != 'en']}", html, (path, other))
                self.assertNotIn("Traceback", html)
                main = html.split("<main")[1].split("</main>")[0].split("<style>")[0]
                self.assertIsNone(re.search(r"\bNone\b(?! of)", main), path)
                self.assertIsNone(re.search(r"\bnan\b|\binf\b", main), path)

    def test_besttime_and_charts(self):
        html = public.route("/best-time-to-trade-crypto")[1].decode()
        self.assertIn("id=tz", html)
        self.assertIn("United States", html)
        self.assertIn("data-h=23", html)
        html = public.route("/solana-market")[1].decode()
        self.assertIn("class=mc data-c=", html)
        self.assertIn("class=gauge", html)
        html = public.route("/hr/solana-launchpadi")[1].decode()
        self.assertIn("LaunchLab (bonk.fun)", html)
        self.assertIn("Meteora DBC", html)

    def test_embeds(self):
        for p in ("/embed/meme-season", "/embed/launchpads", "/hr/embed/meme-season"):
            code, body, _ = public.route(p)
            self.assertEqual(code, 200, p)
            self.assertIn("noindex", body.decode())
            self.assertIn("MemeSonar", body.decode())
        self.assertIsNone(public.route("/embed/nope"))

    def test_sitemap_robots_menu(self):
        sm = public.sitemap()
        rb = public.robots()
        for en, hr in M.PAGES.values():
            self.assertIn(en + "</loc>", sm)
            self.assertIn(hr + "</loc>", sm)
            self.assertIn(f"Allow: {en}", rb)
        self.assertIn("Allow: /embed/", rb)
        for lang in ("en", "hr"):
            groups = sitenav.menu(lang)
            self.assertEqual([g[0] for g in groups], ["coins", "kols", "tools", "learn"])   # no new top-level group
            hrefs = [h for g in groups for h, _n, _d in g[4]]
            self.assertEqual(sum(1 for h in hrefs if h in {p for ps in M.PAGES.values() for p in ps}), 1)
            self.assertIn(M.PAGES["market"][lang != "en"], hrefs)

    def test_empty_db(self):
        d, t = M._cache["d"], M._cache["t"]
        try:
            store.DB = os.path.join(self.tmp, "missing.db")
            M.snapshot(force=True)
            public._cache.clear()
            code, body, _ = public.route("/solana-market")
            self.assertEqual(code, 200)
            self.assertIn("not available yet", body.decode())
        finally:
            store.DB = self.mdb
            M._cache.update(d=d, t=t)
            public._cache.clear()


if __name__ == "__main__":
    unittest.main()
