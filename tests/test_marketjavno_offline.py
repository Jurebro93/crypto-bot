"""15.11.: the public data extension. The whole-Solana total and the SOL daily close in the collector, the influencer
calls page (ui/marketcalls.py), the "what it means" boxes and the members box (ui/marketnotes.py), the Kritičar's
public reads (critic/market.py: what is sent, what may be stored), the home page's data buttons and screenshot
showcase, the blog's links to the data pages. Nothing here reaches the network.

    python3 -m unittest tests.test_marketjavno_offline
"""
import os
import re
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market import collect, sources, store  # noqa: E402
from tests import test_marketpub_offline as base  # noqa: E402
from ui import marketcalls, marketnotes  # noqa: E402
from ui import marketpub as M  # noqa: E402
from ui import public  # noqa: E402

D = 86400
NOW = base.NOW
TODAY = NOW // D * D


class Collector(unittest.TestCase):
    def test_sol_close_is_next_midnight(self):
        pts = [{"timestamp": TODAY - 2 * D, "price": 80.0}, {"timestamp": TODAY - D + 40, "price": 78.0},
               {"timestamp": TODAY, "price": 70.0}, {"timestamp": TODAY + 5 * 3600, "price": 66.0}]
        with mock.patch.object(sources.http, "get_json", return_value={"coins": {"coingecko:solana": {"prices": pts}}}) as g:
            out = dict(sources.sol_prices(3, now=NOW))
        self.assertEqual(out, {TODAY - 3 * D: 80.0, TODAY - 2 * D: 78.0, TODAY - D: 70.0})   # yesterday closes at today 00:00
        self.assertEqual(g.call_args[0][1]["start"], TODAY - 3 * D)                           # asked on midnights

    def test_whole_total_and_snapshot(self):
        ov = {"protocols": [{"slug": "pump.fun", "name": "pump.fun", "category": "Launchpad", "total24h": 5.0, "total7d": 30.0},
                            {"slug": "orca-dex", "name": "Orca", "category": "Dexs", "total24h": 50.0, "total7d": 300.0},
                            {"slug": "cards", "name": "Cards", "category": "Physical TCG", "total24h": 1.0, "total7d": 7.0}],
              "total24h": 56.0, "total7d": 337.0,
              "totalDataChartBreakdown": [[TODAY - i * D, {"pump.fun": 10.0, "Orca": 100.0, "Cards": 2.0}] for i in range(12, -1, -1)]}
        con = store.connect(os.path.join(tempfile.mkdtemp(), "m.db"))
        self.addCleanup(con.close)
        collect.daily(con, ov, now=NOW)
        y = TODAY - D
        get = lambda s: con.execute("SELECT volume FROM daily WHERE day=? AND slug=?", (y, s)).fetchone()   # noqa: E731
        self.assertEqual(get(collect.WHOLE)[0], 112.0)          # every category, as DefiLlama's own Solana total
        self.assertEqual(get("all:dex")[0], 100.0)              # the category series the season index is built on: unchanged
        self.assertIsNone(con.execute("SELECT 1 FROM daily WHERE day=? AND slug=?", (TODAY, collect.WHOLE)).fetchone())
        collect.snapshot(con, ov, now=NOW)
        self.assertEqual(con.execute("SELECT vol24h FROM snap WHERE slug=?", (collect.WHOLE,)).fetchone()[0], 56.0)


class Pages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base.MarketPub.setUpClass()
        cls.addClassCleanup(base.MarketPub.tearDownClass)
        con = store.connect(store.DB)
        hour = NOW // 3600 * 3600
        for ts, k in ((hour, 1.0), (hour - D, 1.25)):
            con.executemany("INSERT OR REPLACE INTO snap VALUES (?,?,?,?)",
                            [(ts, "all:launchpad", 100e6 * k, 0), (ts, "all:dex", 1.5e9 * k, 0), (ts, "all:terminal", 7e7 * k, 0)])
        con.commit()
        con.close()
        M.snapshot(force=True)
        public._cache.clear()

    def test_stats_are_aggregates_and_delayed(self):
        c = M.snapshot()["calls"]
        y = c["x"][c["day"]]
        self.assertGreater(y["calls"], 0)
        self.assertEqual(y["callers"], 1)                       # the bot account is not counted
        self.assertTrue(all(d_ < TODAY for d_ in c["out"]))     # no outcome of a day that is not over
        fresh_day = (NOW - 3600) // D * D
        self.assertNotIn(fresh_day, {d_ for d_ in c["out"] if d_ >= (NOW - D) // D * D + D})
        self.assertIsNotNone(c["hit7"])
        self.assertAlmostEqual(c["rug7"], 1 / 9, delta=0.06)
        self.assertGreater(c["mc7"], 40000)
        self.assertTrue(c["grad"])

    def test_calls_page_both_languages_no_private_data(self):
        for path, lang in zip(M.PAGES["calls"], ("en", "hr")):
            html = public.route(path)[1].decode()
            main = html.split("<main")[1].split("</main>")[0]
            self.assertIn("class=lkd", main)
            self.assertIn("class=osv", main)
            for private in ("good", "scanbot", "tok1", "tokX"):          # no handle, no token
                self.assertIsNone(re.search(rf"\b{private}\b", main), (path, private))
            self.assertIn("/influencers" if lang == "en" else "/hr/influenceri", main)
            self.assertNotIn("DefiLlama", main.split("class=asof")[1].split("</p>")[0])   # its own source line

    def test_boxes_and_live_bar(self):
        d = M.snapshot()
        for key in ("market", "calls", "launchpads", "dex", "season"):
            for tone, t_en, t_hr, x_en, x_hr in marketnotes.rules(key, d):
                self.assertTrue(t_en and t_hr and x_en and x_hr, key)
                self.assertIsNone(re.search(r"\bNone\b|\bnan\b", x_en + x_hr), key)
        html = public.route("/solana-market")[1].decode()
        self.assertIn("class=livebar", html)
        self.assertIn("-20%", html)                              # 100M now against 125M a day before
        self.assertIn("What it means", html)
        self.assertIn("Što to znači", public.route("/hr/solana-trziste")[1].decode())

    def test_whole_series_replaces_category_only_when_complete(self):
        d = M.build(NOW)
        self.assertAlmostEqual(d["ser"]["dex"][d["day"]], 1.2e9 * (1 + 0.3 * 0), delta=1.2e9)   # category (no whole stored)
        con = store.connect(store.DB)
        con.executemany("INSERT OR REPLACE INTO daily VALUES (?,?,?)", [(base.DAY - i * D, collect.WHOLE, 5e9) for i in range(120)])
        con.commit()
        con.close()
        try:
            self.assertEqual(M.build(NOW)["ser"]["dex"][base.DAY], 5e9)
        finally:
            con = store.connect(store.DB)
            con.execute("DELETE FROM daily WHERE slug=?", (collect.WHOLE,))
            con.commit()
            con.close()

    def test_critic_box_shown_only_fresh(self):
        d = dict(M.snapshot())
        d["critic"] = {"ts": NOW, "day": d["day"], "notes": [{"tema": "market", "hr": "Volumen je pao 18 %.", "en": "Volume fell 18%."}]}
        self.assertIn("Volume fell 18%.", marketnotes.boxes("market", d, "en"))
        self.assertIn("Kritičar (AI) kaže", marketnotes.boxes("market", d, "hr"))
        self.assertNotIn("Volume fell", marketnotes.boxes("dex", d, "en"))
        d["critic"]["day"] = d["day"] - 3 * D                    # written for older data: not shown
        self.assertNotIn("Volume fell", marketnotes.boxes("market", d, "en"))

    def test_home_buttons_and_showcase(self):
        from ui import landing
        for lang, paths in (("en", ("/solana-market", "/macro-influencers", "/solana-meme-coins", "/best-time-to-trade-crypto")),
                            ("hr", ("/hr/solana-trziste", "/hr/makro-influenceri", "/hr/solana-meme-coini",
                                    "/hr/najbolje-vrijeme-za-trgovanje-kriptom"))):
            html = landing.page_html(lang=lang)
            cta = html.split("class=dcta")[1].split("</div></div>")[0]
            for p in paths:
                self.assertIn(f"href={p}>", cta, p)
            self.assertEqual(cta.count("<a href="), 4)
            self.assertNotIn("influencer-calls", cta)            # 20.11.: no call leaderboard buttons on the home page
            self.assertNotIn("pozivi-kripto", cta)
            self.assertRegex(cta, r"\d+/100")                    # the season index, live
            show = html.split("<div class=show")[1].split("</header>")[0]
            self.assertEqual(show.count("<button"), 4)
            self.assertEqual(show.count(" src="), 1)             # one picture loads with the page, the rest on their turn
            for f in re.findall(r'(?:data-)?src="/static/landing/([^"]+)"', show):
                self.assertTrue(os.path.exists(os.path.join(landing.STATIC, f)), f)
            self.assertIn("class=hbg", html)

    def test_blog_links_to_data_pages(self):
        from ui import blog
        en = public.route("/blog/top-crypto-twitter-accounts-by-call-accuracy")[1].decode()
        self.assertIn("href=/crypto-influencer-calls>", en)
        self.assertIn("Influencer ranking: the big accounts", en)
        hr_slug = blog.get_en("how-to-trade-meme-coins", "hr")["slug"]
        hr = public.route(f"/hr/blog/{hr_slug}")[1].decode()
        self.assertIn("href=/hr/solana-trziste>", hr)
        for slug, keys in blog.DATA_FOR.items():
            self.assertIsNotNone(blog.get_en(slug, "en"), slug)
            self.assertTrue(all(k == "inf" or k in M.PAGES for k in keys), slug)


class Critic(unittest.TestCase):
    def setUp(self):
        base.MarketPub.setUpClass()
        self.addCleanup(base.MarketPub.tearDownClass)
        from critic import store as cstore
        self.tcon = sqlite3.connect(":memory:")
        cstore.ensure(self.tcon)
        self.env = mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-not-a-real-key-000000000000"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def _run(self, notes, **kw):
        from critic import market, trades
        sent = {}

        def call(model, system, text, schema, name, max_out, effort):
            sent.update(model=model, text=text, system=system)
            return {"data": {"osvrti": notes}, "usage": {"in": 1800, "out": 300}, "model": model, "cost_usd": 0.003}
        with mock.patch.object(trades, "enabled", return_value=True):
            res = market.run(now=NOW, log=lambda *a, **k: None, tcon=self.tcon, call=call, snapshot=M.snapshot(), **kw)
        return res, sent

    def test_only_public_aggregates_are_sent_and_reads_are_checked(self):
        from critic import market, openai_api, store as cstore
        good = {"tema": "market", "hr": "Volumen launchpada pao je 18 % u tjedan dana, što znači manje novih coina s kupcima.",
                "en": "Launchpad volume fell 18% in a week, which means fewer new coins find buyers."}
        bad = [{"tema": "calls", "hr": "Kupi odmah, pozivi rastu 40 % i zarada je sigurna.", "en": "Buy now, calls are up 40%."},
               {"tema": "dex", "hr": "Pogledaj $BONK i @nekiracun, volumen je 3 puta veći.", "en": "See $BONK and @someone, volume is 3 times bigger."},
               {"tema": "season", "hr": "Indeks je nizak i tržište je hladno ovih dana.", "en": "The index is low and the market is cold."},
               {"tema": "market", "hr": "Drugi osvrt na istu temu s brojem 12 koji je višak.", "en": "A second read of the same page with the number 12."}]
        res, sent = self._run([good] + bad)
        self.assertEqual(res["osvrta"], 1)
        self.assertEqual(len(res["odbaceno"]), 4)
        self.assertEqual(sent["model"], openai_api.MODEL_CHEAP)
        for private in ("good", "scanbot", "tok1", "sk-test"):
            self.assertIsNone(re.search(rf"\b{private}", sent["text"]), private)
        self.assertIn('"x_poziva_zadnji_dan"', sent["text"])
        v = cstore.kv_get(self.tcon, market.KEY)
        self.assertEqual(v["notes"], [good])
        self.assertEqual(v["day"], M.snapshot()["day"])
        self.assertEqual(self.tcon.execute("SELECT kind, ok, n FROM critic_calls").fetchall(), [("market", 1, 1)])

    def test_twice_a_day_six_hours_apart(self):
        from critic import market
        ok = [{"tema": "dex", "hr": "Volumen DEX-ova pao je 12 % prema tjednu prije.", "en": "DEX volume fell 12% against the week before."}]
        self.assertIn("osvrta", self._run(ok)[0])
        self.assertEqual(self._run(ok)[0], {"skip": "nije vrijeme"})           # 6 h have not passed
        self.assertFalse(market.due(self.tcon, NOW + 3600))
        self.tcon.execute("INSERT INTO critic_calls (ts, kind, model, tokens_in, tokens_out, cost_usd, ok) VALUES (?,?,?,?,?,?,?)",
                          (NOW + 1, "market", "m", 1, 1, 0.0, 1))
        self.tcon.commit()
        from critic import store as cstore
        if cstore.day_start(NOW + 7 * 3600) == cstore.day_start(NOW):
            self.assertFalse(market.due(self.tcon, NOW + 7 * 3600))             # two calls today already
        with mock.patch.dict(os.environ, {"MARKET_OSVRT": "0"}):
            self.assertEqual(self._run(ok, force=True)[0], {"skip": "isključen"})

    def test_scheduled(self):
        import run_sched
        jobs = {n: (fn.__name__, args) for n, fn, args in run_sched.JOBS}
        self.assertEqual(jobs["kriticar_trziste"], ("every", (["run_critic.py", "market"], 60.0, True)))


if __name__ == "__main__":
    unittest.main()
