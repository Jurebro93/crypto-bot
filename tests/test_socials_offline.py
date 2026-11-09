"""5.11.: a token's own socials (hype/socials.py): X profile vs tweet/search, Telegram preview, paid profile,
'ozbiljan projekt' / 'sumnjivi socijali' features, confidence parts and strategy signals."""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hype import socials  # noqa: E402

NOW = 1_800_000_000
PAGE = ('<div class="tgme_header_counter">1.2K subscribers</div>'
        + "".join(f'<div data-post="c/{i}"><time datetime="2027-01-25T10:0{i}:00+00:00"></time></div>' for i in range(5)))


class Socials(unittest.TestCase):
    def test_classify_and_features(self):
        serious = {"socials": [{"type": "twitter", "url": "https://x.com/VraxCTO"}, {"type": "telegram", "url": "https://t.me/VraxVerify"}],
                   "websites": [{"url": "https://vrax.io"}], "imageUrl": "i", "header": "h"}
        cls = socials.classify(serious)
        self.assertEqual((cls["x"], cls["tg_handle"], cls["paid"], cls["web"]), ("profile", "VraxVerify", True, True))
        now = 1_800_000_000 + 0  # the fixture's posts are in 2027: ages computed against `now` below
        import datetime as dt
        now = dt.datetime(2027, 1, 25, 12, tzinfo=dt.timezone.utc).timestamp()
        tg = socials.telegram_probe("VraxVerify", fetch=lambda url: PAGE, now=now)
        self.assertEqual((tg["kind"], tg["subs"], tg["posts_7d"]), ("channel", 1200, 5))
        self.assertLess(tg["last_post_age_h"], 3)
        f = socials.features(cls, tg)
        self.assertEqual((f["ozbiljan_projekt"], f["sumnjivi_socijali"], f["socijali_x"], f["socijali_placeni"]), (1.0, 0.0, 1.0, 1.0))
        self.assertGreaterEqual(f["socijali_tg"], 0.9)
        self.assertIn("pravi X profil", socials.describe(cls, tg))
        # Aren: a leopard tweet as the X link, no Telegram
        aren = {"socials": [{"type": "twitter", "url": "https://x.com/meggarwicky/status/2118"}]}
        c2 = socials.classify(aren)
        f2 = socials.features(c2, None)
        self.assertEqual((c2["x"], f2["ozbiljan_projekt"], f2["sumnjivi_socijali"], f2["socijali_x"]), ("tweet", 0.0, 1.0, 0.3))
        # Woke 3: a search page
        woke = {"socials": [{"type": "twitter", "url": "https://x.com/search?q=woke%203&src=typed_query&f=top"}], "imageUrl": "i", "header": "h"}
        self.assertEqual(socials.classify(woke)["x"], "search")
        # group join page: members only
        tg2 = socials.telegram_probe("grp", fetch=lambda url: ('<div class="tgme_page_extra">340 members</div>' if "/s/" not in url else ""), now=now)
        self.assertEqual((tg2["kind"], tg2["subs"]), ("group", 340))
        self.assertIsNone(socials.telegram_probe("none", fetch=lambda url: "", now=now))

    def test_cache_confidence_and_strategy_signal(self):
        con = sqlite3.connect(os.path.join(tempfile.mkdtemp(), "hype.db"))
        calls = []
        info = {"socials": [{"type": "telegram", "url": "https://t.me/chan"}, {"type": "twitter", "url": "https://x.com/p"}], "imageUrl": "i", "header": "h"}
        d = socials.probe_and_store(con, "T1", info, NOW, fetch=lambda url: calls.append(url) or PAGE)
        d2 = socials.probe_and_store(con, "T1", info, NOW + 100, fetch=lambda url: calls.append(url) or PAGE)
        self.assertEqual(len(calls), 1)                       # second time from cache
        self.assertEqual(d2["features"], d["features"])
        from ui import confidence
        hi, parts = confidence.score(hype=60, features={"ozbiljan_projekt": 1.0}, mcap=250_000)
        lo, parts2 = confidence.score(hype=60, features={"sumnjivi_socijali": 1.0}, mcap=250_000)
        self.assertEqual(hi - lo, 20)
        self.assertTrue(any("Ozbiljan projekt" in t for _, t in parts))
        self.assertTrue(any("Sumnjivi" in t for _, t in parts2))
        from strat import run
        cfg = run.load_config()
        for s in cfg["strategies"]:   # 9.11.: both frozen by Jure's decision; the signal plumbing is what is tested here
            s.pop("frozen", None)
        self.assertIn("ozbiljan_projekt", run.keys(cfg))
        self.assertIn("sumnjivi_socijali", run.keys(cfg))
        w = run.wanted({"ozbiljni": [("A", NOW, "x", 70)], "sumnjivi": [("B", NOW, "y", 40)]}, cfg, NOW, 0, (), None)
        self.assertEqual([e[0] for e in w["ozbiljan_projekt"]], ["A"])
        self.assertEqual([e[0] for e in w["sumnjivi_socijali"]], ["B"])


if __name__ == "__main__":
    unittest.main()
