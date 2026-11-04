"""KOL module on synthetic data: tweet -> calls, price path after a call, groups, call power, flows, signals, page."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import collect, flows, measure, score, store  # noqa: E402

CFG = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kol", "config.json")))
CA = "HgxEGTZ1Epb64RrYqcuHkqb1gGWWnF5WcPTCDWzApump"
CA2 = "8uBobWMhu6hRUn4jaA4kjcgWCjTxgHwHJtPgBePXpump"
T0 = 1793390000 // 300 * 300
H = 3600


def tweet(tid, handle, text, ts, followers=5000, **kw):
    import datetime as dt
    created = dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%a %b %d %H:%M:%S +0000 %Y")
    return dict({"id": tid, "url": f"https://x.com/{handle}/status/{tid}", "text": text, "createdAt": created,
                 "likeCount": "3", "viewCount": 100, "author": {"userName": handle, "followers": followers}}, **kw)


def candles(path):
    """path: [(minutes_from_T0, price, volume)] -> 5-min candles with that close and high."""
    return [(T0 + m * 60, p, p, p, p, v) for m, p, v in path]


class Tweets(unittest.TestCase):
    def test_ca_ticker_retweet_brag(self):
        c = collect.calls_from_tweet(tweet("1", "a", f"new gem {CA} go", T0), CA, "ICOIN")
        self.assertEqual([(x["token"], x["match"], x["kind"]) for x in c], [(CA, "ca", "call")])
        c = collect.calls_from_tweet(tweet("2", "b", "$ICOIN sending", T0), CA, "ICOIN")
        self.assertEqual(c[0]["match"], "ticker")
        self.assertEqual(collect.calls_from_tweet(tweet("3", "c", "$ICOIN", T0, isRetweet=True), CA, "ICOIN"), [])
        self.assertEqual(collect.calls_from_tweet(tweet("4", "d", "$OTHER only", T0), CA, "ICOIN"), [])
        # a tweet that names another CA is a call on that one, not a ticker hit on the searched token
        c = collect.calls_from_tweet(tweet("5", "e", f"$ICOIN {CA2}", T0), CA, "ICOIN")
        self.assertEqual([x["token"] for x in c], [CA2])
        self.assertEqual(collect.kind_of("15X on $ICOIN"), "brag")
        self.assertEqual(collect.kind_of("115x $ICOIN\nCA"), "brag")
        self.assertEqual(collect.kind_of("this is the next 100x"), "call")
        self.assertEqual(collect.tweet_ts("Fri Oct 30 21:58:58 +0000 2026"), 1793397538)

    def test_cache_target(self):
        key = 'x_buzz:apidojo/tweet-scraper:{"maxItems": 40, "searchTerms": ["%s", "$TUSK"], "sort": "Latest"}' % CA
        self.assertEqual(collect._target(key), (CA, "TUSK"))
        self.assertEqual(collect._target('kol_timeline:x:{"searchTerms": ["from:a OR from:b"]}'), (None, None))


class Measure(unittest.TestCase):
    def test_outcome(self):
        # flat at 1.0 for 2 h, call at T0+120 min, doubles by +60 min, peaks 3.0, ends at 0.05 (rug)
        path = [(m, 1.0, 100) for m in range(0, 125, 5)] + [(150, 2.0, 5000), (240, 3.0, 500), (1560, 0.05, 10)]
        ts = T0 + 120 * 60 + 30
        o = measure.outcome(candles(path), ts, ts + 30 * H, CFG)
        self.assertAlmostEqual(o["p0"], 1.0)
        self.assertAlmostEqual(o["pre2h"], 0.0)
        self.assertAlmostEqual(o["r1h"], 1.0)
        self.assertAlmostEqual(o["max24"], 2.0)
        self.assertAlmostEqual(o["r24h"], -0.95)
        self.assertEqual(o["rug"], 1)
        self.assertEqual(o["complete"], 1)
        self.assertGreater(o["vol_lift"], 4)
        # not yet an hour after the call: no 1 h number, not complete
        o = measure.outcome(candles(path), ts, ts + 600, CFG)
        self.assertIsNone(o["r1h"])
        self.assertEqual(o["complete"], 0)


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "kol.db")
        self.con = store.connect(self.path)
        ts = T0 + 120 * 60
        tw = [tweet("10", "alpha", f"aping {CA}", ts, 20000), tweet("11", "beta", f"{CA} 🚀", ts + 600, 3000),
              tweet("12", "gamma", f"20x on {CA}", ts + 900, 800),  # brag: not part of the group
              tweet("13", "alpha", f"early {CA2}", ts + 5 * H, 20000)]
        for t in tw:
            collect.save(self.con, collect.calls_from_tweet(t))
        self.con.executemany("INSERT INTO tokens (token, symbol, pair, supply, tries, updated) VALUES (?,?,?,?,0,0)",
                             [(CA, "ICOIN", "POOL1", 1e9, ), (CA2, "TUSK", "POOL2", 1e9)])
        self.con.commit()
        self.now = ts + 30 * H

        def fake(pool, start, end):
            if pool == "POOL1":
                return candles([(m, 0.0001, 50) for m in range(0, 120, 5)] + [(150, 0.0003, 5000), (300, 0.0004, 800)])
            return candles([(m, 0.0002, 50) for m in range(0, 420, 5)] + [(480, 0.00001, 10)])
        self.fake = fake

    def test_end_to_end(self):
        con, cfg = self.con, dict(CFG, good_score=30)
        t, n = measure.run(con, cfg, now=self.now, fetch=self.fake)
        self.assertEqual(t, 2)
        mc = con.execute("SELECT mcap0, max24 FROM calls WHERE tweet_id='10'").fetchone()
        self.assertAlmostEqual(mc[0], 1e5)
        self.assertAlmostEqual(mc[1], 3.0)
        score.run(con, cfg, now=self.now)
        g = con.execute("SELECT n_authors, handles, first_handle FROM groups").fetchall()
        self.assertEqual(len(g), 1)
        self.assertEqual(json.loads(g[0][1]), ["alpha", "beta"])
        firsts = dict(con.execute("SELECT tweet_id, first_overall FROM calls"))
        self.assertEqual((firsts["10"], firsts["11"], firsts["12"]), (1, 0, 0))
        k = dict(con.execute("SELECT handle, stats FROM kols"))
        alpha = json.loads(k["alpha"])
        self.assertEqual(alpha["measured"], 2)
        self.assertEqual(alpha["rug_rate"], 0.5)
        self.assertEqual(json.loads(k["gamma"])["brags"], 1)
        sc = dict(con.execute("SELECT handle, score FROM kols"))
        self.assertGreater(sc["beta"], sc["gamma"] or 0)
        # one measured call is pulled towards prior_score
        self.assertLess(abs(sc["beta"] - cfg["prior_score"]), abs(json.loads(k["beta"])["raw"] - cfg["prior_score"]))

        # flows: alpha's call; insider bought 2 SOL before, sold 3 after; a rotation dev sold too
        con.execute("INSERT INTO kol_wallets VALUES ('ROT','rotation_dev',3,1,1,'[]',0,0)")
        due = flows.due(con, cfg, self.now)
        self.assertEqual(due[0][0], "10")

        def fetch(mint, since_ts=None, until_ts=None, max_pages=2, oldest_first=False, on_credits=None):
            on_credits(10)
            if oldest_first:
                return [("INS", since_ts + 60, "sell", 3.0), ("ROT", since_ts + 90, "sell", 1.0)], True
            return [("INS", since_ts + 60, "buy", 2.0), ("SMALL", since_ts + 70, "buy", 0.01)], True
        orig = flows._swaps
        flows._swaps = lambda txs, mint: txs
        try:
            n, cr = flows.run(con, cfg, now=self.now, fetch=fetch)
        finally:
            flows._swaps = orig
        self.assertGreaterEqual(n, 1)
        f = con.execute("SELECT insiders, insider_sol, rotation_selling FROM flows WHERE tweet_id='10'").fetchone()
        self.assertEqual(f, (1, 3.0, 1))
        self.assertEqual({w for w, in con.execute("SELECT wallet FROM insiders")}, {"INS"})

        score.run(con, cfg, now=T0 + 120 * 60 + 2 * H)
        self.assertEqual(con.execute("SELECT dev_selling FROM groups").fetchone()[0], 1)
        con.commit()
        sig = store.signals(path=self.path, max_age_h=10 ** 6)
        self.assertEqual(sig[CA]["feature"], 0.0)  # devs sold into the call: no signal

    def test_page_renders(self):
        measure.run(self.con, CFG, now=self.now, fetch=self.fake)
        score.run(self.con, CFG, now=self.now)
        self.con.commit()
        from ui import kol as ukol
        old = store.DB
        store.DB = self.path
        try:
            title, body = ukol.page({})
            self.assertIn("@alpha", body)
            self.assertIn("https://x.com/alpha/status/10", body)
            self.assertIn("Svi grupni pozivi", body)
            self.assertIn("ICOIN", ukol.token_section(CA))
            self.assertIn("Kako je dobio ocjenu", ukol.kol_page("alpha", {})[1])
            body = ukol.kol_page("alpha", {})[1]
            self.assertIn("Kako su mu prolazili pozivi", body)  # 2 measured calls: bar + running-result chart
            self.assertIn("Da si uložio $10", body)
        finally:
            store.DB = old

    def test_wallet_trades_not_posts(self):
        """Wallet buys/sells (Helius) get their own table with a Solscan transaction link, never a 'post' link."""
        self.con.execute("INSERT INTO kol_ids (wallet, name, twitter, source) VALUES ('F6GTuHabcdef', NULL, NULL, 'kolscan')")
        self.con.execute("""INSERT INTO calls (tweet_id, token, handle, ts, url, text, followers, likes, retweets, views,
            kind, match, source) VALUES ('sig:XYZ', ?, 'w:F6GTuH', ?, 'https://solscan.io/tx/XYZ', 'buy 0.05 SOL',
            0, 0, 0, 0, 'buy', 'wallet', 'chain')""", (CA, self.now - 60))
        self.con.commit()
        from ui import kol as ukol
        old = store.DB
        store.DB = self.path
        try:
            sec = ukol.token_section(CA)
            self.assertIn("transakcija ↗", sec)
            self.assertIn("https://solscan.io/tx/XYZ", sec)
            self.assertIn("https://solscan.io/account/F6GTuHabcdef", sec)
            self.assertNotIn('solscan.io/tx/XYZ" target=_blank rel=noopener>post', sec)
            head, _, rest = sec.partition("KOL novčanici")
            self.assertNotIn("solscan.io/tx", head)  # posts table has no wallet rows
            self.assertIn("0.05", rest)
            self.assertIn("Kupnje i prodaje", ukol._wallet_page(self.con, "w:F6GTuH")[1])
            self.assertIn("<details class=uc-sec id=kupnje><summary>Kupnje i prodaje</summary>", ukol.page({})[1])
        finally:
            store.DB = old

    def test_missing_db(self):
        self.assertEqual(store.signals(path=os.path.join(tempfile.mkdtemp(), "none.db")), {})


class Seed(unittest.TestCase):
    def test_import_once(self):
        import gzip
        import shutil
        d = tempfile.mkdtemp()
        src = store.connect(os.path.join(d, "src.db"))
        collect.save(src, collect.calls_from_tweet(tweet("1", "a", f"gem {CA}", T0)))
        src.commit()
        src.close()
        with open(os.path.join(d, "src.db"), "rb") as f, gzip.open(os.path.join(d, "seed.db.gz"), "wb") as g:
            shutil.copyfileobj(f, g)
        con = store.connect(os.path.join(d, "dst.db"))
        self.assertEqual(store.import_seed(con, os.path.join(d, "seed.db.gz")), 1)
        self.assertEqual(store.import_seed(con, os.path.join(d, "seed.db.gz")), 0)
        self.assertEqual(store.import_seed(con, os.path.join(d, "none.gz")), 0)
        from kol import backfill
        self.assertEqual(backfill.token_query(CA, T0, T0 + 3600).split()[1:], ["since:2026-10-30", "until:2026-11-01"])


class Live(unittest.TestCase):
    def setUp(self):
        self.con = store.connect(os.path.join(tempfile.mkdtemp(), "kol.db"))
        good = {"measured": 8, "hit_rate": 0.75, "prepump_rate": 0.1, "med_max24": 1.2}
        for h, sc, st in [("early", 70, good), ("late", 80, dict(good, prepump_rate=0.6)),
                          ("few", 75, dict(good, measured=2)), ("weak", 40, good), ("ok", 60, dict(good, hit_rate=0.5))]:
            self.con.execute("INSERT INTO kols (handle, score, stats) VALUES (?,?,?)", (h, sc, json.dumps(st)))

    def test_watch_and_sync(self):
        cfg = dict(CFG, watch=dict(CFG["watch"], size=4))
        self.assertEqual(score.build_watch(self.con, cfg, now=1000), ["early", "ok"])
        self.assertIn("pogodak 75%", self.con.execute("SELECT reason FROM watch WHERE handle='early'").fetchone()[0])
        self.assertEqual(score.build_watch(self.con, cfg, now=5000), ["early", "ok"])
        self.assertEqual(self.con.execute("SELECT since FROM watch WHERE handle='early'").fetchone()[0], 1000)

        from kol import live
        calls = []
        import tempfile
        env = {"RENDER_EXTERNAL_URL": "https://bot.example", "UI_PASSWORD": "pw", "DATA_DIR": tempfile.mkdtemp()}
        old = {k: os.environ.get(k) for k in [*env, "KOL_HOOK_KEY", "APIFY_TOKEN"]}
        os.environ.update(env, APIFY_TOKEN="x")
        os.environ.pop("KOL_HOOK_KEY", None)
        try:
            self.assertEqual(store.hook_key(), store.hook_key())
            self.assertEqual(len(store.hook_key()), 32)
            self.assertTrue(live.hook_url().startswith("https://bot.example/hook/kol?key="))
            fake = lambda handles, url, stop=False, hours=None: calls.append((sorted(handles), stop, hours))
            H6 = 6 * 3600
            self.assertTrue(live.sync(self.con, cfg, fake, now=H6, log=lambda *_: None))  # start
            self.assertFalse(live.sync(self.con, cfg, fake, now=H6 + 60))  # nothing changed, not due
            self.assertTrue(live.sync(self.con, cfg, fake, now=2 * H6))  # periodic resync bills 6 h x 2 accounts
            self.con.execute("DELETE FROM watch")
            self.assertTrue(live.sync(self.con, cfg, fake, now=2 * H6 + 3600, log=lambda *_: None))  # stop
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.assertEqual(calls, [(["early", "ok"], False, 0), (["early", "ok"], False, 6.0),
                                 (["early", "ok"], True, 1.0)])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM monitor").fetchone()[0], 0)
        self.assertEqual(live.plan([], [], 0, 10 ** 9, 6), (False, False))


class Sessions(unittest.TestCase):
    def test_session_zone_hours(self):
        from kol import sessions
        day = 1793318400  # 2026-10-30 00:00 UTC
        self.assertEqual([sessions.session_of(day + h * H) for h in (0, 7, 8, 13, 14, 23)],
                         ["asia", "asia", "eu", "eu", "us", "us"])
        # posts every hour except 07-12 UTC (night centred on 09:00 UTC = 04:00 in New York, UTC-5)
        ts = [day + d * 86400 + h * H for d in range(3) for h in range(24) if not 6 <= h < 12]
        self.assertEqual(sessions.zone(ts), (-5, "us", len(ts)))
        self.assertEqual(sessions.zone(ts[:5])[0], None)
        flat = [day + h * H for h in range(24)] * 2  # no night: bot
        self.assertIsNone(sessions.zone(flat)[0])
        sh = sessions.shares(sessions.hours_from_candles([(day + 3 * H, 0, 0, 0, 0, 30.0), (day + 15 * H, 0, 0, 0, 0, 70.0)]))
        self.assertEqual(sh, {"asia": 0.3, "eu": 0.0, "us": 0.7})
        self.assertEqual(sessions.dominant(sh), "us")

    def test_learn_factor(self):
        from kol import sessions
        con = store.connect(os.path.join(tempfile.mkdtemp(), "kol.db"))
        day = 1793318400
        rows = [(f"a{i}", day + 2 * H, 1.0) for i in range(40)] + [(f"e{i}", day + 10 * H, 0.0) for i in range(40)]
        for tid, t, mx in rows:
            con.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, first_by_kol, max24) "
                        "VALUES (?,?,?,?,'call',1,?)", (tid, tid, "k", t, mx))
        cfg = dict(CFG, sessions=dict(CFG["sessions"]))
        sessions.learn(con, cfg, now=day)
        f = sessions.factors(con)
        self.assertEqual(f["asia"], cfg["sessions"]["factor_max"])  # always hit: capped
        self.assertEqual(f["eu"], cfg["sessions"]["factor_min"])
        self.assertEqual(f["us"], 1.0)  # no data
        info = sessions.now_info(con, now=day + 3 * H)
        self.assertEqual((info["session"], info["factor"]), ("asia", 1.3))


class Helpers(unittest.TestCase):
    def test_groups(self):
        calls = [("A", 0, "x"), ("A", 600, "y"), ("A", 1700, "x"), ("A", 5000, "z"), ("B", 0, "x")]
        self.assertEqual(list(score.find_groups(calls, 1800)), [("A", 0, 1700, ["x", "y"])])

    def test_spearman(self):
        self.assertEqual(score.spearman([1, 2, 3, 4, 5], [2, 4, 6, 8, 10]), 1.0)
        self.assertEqual(score.spearman([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]), -1.0)
        self.assertIsNone(score.spearman([1, 2], [1, 2]))


if __name__ == "__main__":
    unittest.main()
