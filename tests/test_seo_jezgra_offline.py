"""28.11. (vlasnik: "jezgra"): ui/seoindex's core of about 40 addresses on top of the candidate sections.

  - always the homepage, prices and the free check; every candidate with Search Console impressions, even past the size
  - then the quotas per section (influencers, coins, market pages, blog posts), round robin, up to SEO_CORE_MAX
  - the last core's members first (stable); the glossary, methodology, Telegram hub never
  - the weekly step raises the size by SEO_CORE_GROW_WEEK only on a healthy week; SEO_CORE_MAX=0 = the old behaviour

    python3 -m unittest tests.test_seo_jezgra_offline
"""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import seoindex as S  # noqa: E402


def row(en, sec, rank=0, hr=True):
    return {"en": en, "hr": ("/hr" + en if en != "/" else "/hr") if hr else None, "section": sec, "prio": "0.5",
            "lastmod": None, "added": "2026-11-01", "seed": 0, "rank": rank}


def pool():
    rows = {}
    for en in ("/", "/pricing", "/check-influencer", "/solana-meme-coins", "/rug-check", "/meme-coin-season-index",
               "/influencers", "/blog", "/best-crypto-tools"):
        rows[en] = row(en, "hub")
    for i in range(30):
        rows[f"/influencer/k{i}"] = row(f"/influencer/k{i}", "influencer", i)
        rows[f"/coin/c{i}"] = row(f"/coin/c{i}", "coin", i)
        rows[f"/blog/p{i}"] = row(f"/blog/p{i}", "blog", i)
        rows[f"/macro-influencer/m{i}"] = row(f"/macro-influencer/m{i}", "macro", i)
    return rows


def size(rows, pick):
    return sum(1 + bool(rows[e]["hr"]) for e in pick)


class Core(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict(os.environ, {"SEO_CORE_MAX": "40"})
        p.start()
        self.addCleanup(p.stop)

    def test_always_then_quotas_up_to_the_size(self):
        rows = pool()
        pick = S._jezgra(rows, {}, set())
        self.assertEqual(size(rows, pick), 40)
        self.assertEqual(pick[:3], ["/", "/pricing", "/check-influencer"])
        by = {}
        for e in pick:
            by[rows[e]["section"]] = by.get(rows[e]["section"], 0) + 1
        self.assertEqual(by, {"hub": 6, "influencer": 7, "coin": 4, "blog": 3})   # 3 always + 3 market pages
        self.assertEqual([e for e in pick if rows[e]["section"] == "influencer"], [f"/influencer/k{i}" for i in range(7)])
        for e in ("/solana-meme-coins", "/rug-check", "/meme-coin-season-index"):
            self.assertIn(e, pick)
        self.assertNotIn("/macro-influencer/m0", pick)

    def test_earners_are_never_dropped_even_past_the_size(self):
        rows = pool()
        earn = {f"/hr/macro-influencer/m{i}" for i in range(20, 30)} | {"/coin/c29"}
        pick = S._jezgra(rows, {}, earn)
        for e in [f"/macro-influencer/m{i}" for i in range(20, 30)] + ["/coin/c29"]:
            self.assertIn(e, pick)
        self.assertEqual(size(rows, pick), 40)        # 3 always + 11 earners = 28 addresses, the quotas fill the rest
        earn = {f"/macro-influencer/m{i}" for i in range(30)}
        pick = S._jezgra(rows, {}, earn)
        self.assertEqual(size(rows, pick), 66)        # 30 earning pairs past the size: kept, nothing else added
        self.assertNotIn("/influencer/k0", pick)

    def test_stable_last_members_first(self):
        rows = pool()
        kv = {"jezgra": json.dumps(["/influencer/k25", "/coin/c20"])}
        pick = S._jezgra(rows, kv, set())
        self.assertIn("/influencer/k25", pick)
        self.assertIn("/coin/c20", pick)
        self.assertNotIn("/influencer/k6", pick)      # the old member kept the slot of the 7th best

    def test_growth_adds_size_only_on_a_healthy_week(self):
        rows = pool()
        core = {e: rows[e] for e in S._jezgra(rows, {}, set())}

        class Con:
            def __init__(self):
                self.sql = []

            def execute(self, *a):
                self.sql.append(a)
        good = {"fresh": True, "a": 30, "b": 40, "share": .75, "imp": [120, 80, 60], "clicks": [3, 1, 0], "weight": {}}
        for h, grows in ((None, False), ({"fresh": False}, False), ({**good, "share": .3}, False),
                         ({**good, "imp": [50, 80, 90]}, False), (good, True)):
            kv, con = {}, Con()
            with mock.patch.object(S, "health", return_value=h):
                line = S.grow_core(core, kv, 1e9, con)
            self.assertEqual(kv.get("jezgra_extra") == "10", grows, (h, line))
            self.assertEqual(bool(con.sql), grows)
        kv = {"jezgra_extra": "10"}
        self.assertEqual(size(rows, S._jezgra(rows, kv, set())), 50)
        with mock.patch.dict(os.environ, {"SEO_CORE_GROW_WEEK": "99"}), mock.patch.object(S, "health", return_value=good):
            kv = {}
            S.grow_core(core, kv, 1e9, Con())
        self.assertEqual(kv["jezgra_extra"], "20")       # never more than 20 a week

    def test_finish_reads_the_core_and_never_the_glossary(self):
        rows = pool()
        rows["/glossary"] = row("/glossary", "hub")
        st = {"rows": rows, "kv": {"jezgra": json.dumps(["/", "/coin/c1", "/gone"])}}
        S._finish(st)
        self.assertEqual(set(st["core"]), {"/", "/coin/c1"})
        self.assertEqual(st["set"], {"/", "/hr", "/coin/c1", "/hr/coin/c1"})
        self.assertTrue(S.OUT_HUB.fullmatch("/glossary"))
        self.assertTrue(S.OUT_HUB.fullmatch("/methodology"))
        self.assertTrue(S.OUT_HUB.fullmatch("/telegram-channels"))
        self.assertIn("glossary", S.OUT_SECTIONS)
        st = {"rows": rows, "kv": {}}                   # no core stored: every candidate (the old behaviour)
        self.assertEqual(len(S._finish(st)["core"]), len(rows))


if __name__ == "__main__":
    unittest.main()
