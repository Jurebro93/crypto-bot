"""kol/validate.py on synthetic data: score ranges, walk-forward verdict, chance test for pairs, signal gate."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import score, store, validate  # noqa: E402

CFG = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kol", "config.json")))
DAY = 86400
NOW = 1793500000


def call(h, token, ts, max24, **kw):
    c = {"handle": h, "token": token, "ts": ts, "kind": "call", "first_by_kol": 1, "max24": max24, "r1h": max24 / 3,
         "vol_lift": 2.0, "rug": 0, "pre2h": 0.0, "first_overall": 1, "views": 100, "likes": 1, "retweets": 0,
         "followers": 1000}
    c.update(kw)
    return c


class Ranges(unittest.TestCase):
    def test_few_calls_wide_many_calls_narrow(self):
        few = [call("a", f"t{i}", i, x) for i, x in enumerate([3.0, 0.1, 1.0])]
        many = [call("b", f"t{i}", i, x) for i, x in enumerate([3.0, 0.1, 1.0] * 20)]
        lo1, hi1 = validate.score_range(few, CFG, 200, 1)
        lo2, hi2 = validate.score_range(many, CFG, 200, 1)
        self.assertLess(lo1, hi1)
        self.assertGreater(hi1 - lo1, hi2 - lo2)
        self.assertIsNone(validate.score_range([], CFG))

    def test_hypergeometric(self):
        self.assertAlmostEqual(validate.hyper_sf(0, 10, 3, 3), 1.0)
        self.assertEqual(validate.hyper_sf(4, 10, 3, 3), 0.0)
        # P(X >= 3) drawing 3 of 10 with 3 good = 1 / C(10, 3)
        self.assertAlmostEqual(validate.hyper_sf(3, 10, 3, 3), 1 / 120)


class WalkForward(unittest.TestCase):
    def calls(self, good_wins):
        """KOLs g0..g4 hit every call when good_wins, the other 20 KOLs half; history before the test week."""
        out = []
        start = NOW - DAY - 7 * DAY
        for k in range(25):
            h = f"g{k}" if k < 5 else f"o{k}"
            for i in range(6):  # history: g* always hit, o* never
                out.append(call(h, f"{h}-h{i}", start - 3 * DAY - i * 3600, 1.0 if h[0] == "g" else 0.1))
            for i in range(4):  # test week
                hit = (h[0] == "g") == good_wins or i % 2 == 0
                out.append(call(h, f"{h}-t{i}", start + DAY + i * 3600, 1.0 if hit else 0.1))
        return out

    def test_pass_and_fail(self):
        start = NOW - DAY - 7 * DAY
        w = validate.week_test(self.calls(True), CFG, start, start + 7 * DAY, {})
        self.assertEqual((w["kols"], w["top_kols"], w["n_top"]), (25, 5, 20))
        self.assertEqual(w["hit_top"], 1.0)
        v = validate.verdict([w], dict(CFG, validate={"min_n": 10}))
        self.assertEqual(v["state"], "prolazi")
        w = validate.week_test(self.calls(False), CFG, start, start + 7 * DAY, {})
        self.assertEqual(validate.verdict([w], dict(CFG, validate={"min_n": 10}))["state"], "pada")
        self.assertEqual(validate.verdict([w], CFG)["state"], "malo")  # 20 top calls < 30
        w = dict(w, hit_top=0.52, hit_rest=0.50, hit_foll=0.5)  # better, but within the margin
        self.assertEqual(validate.verdict([w], dict(CFG, validate={"min_n": 10}))["state"], "nejasno")

    def test_no_peeking(self):
        """Calls in the last 24 h before the week (outcome not known yet) and during it never feed the score."""
        start = NOW - 8 * DAY
        cs = [call("x", f"t{i}", start - 12 * 3600 + i, 1.0) for i in range(5)]
        w = validate.week_test(cs, CFG, start, start + 7 * DAY, {})
        self.assertEqual(w["kols"], 0)


class Database(unittest.TestCase):
    def test_run_pairs_and_gate(self):
        path = os.path.join(tempfile.mkdtemp(), "kol.db")
        con = store.connect(path)
        rows = []
        t0 = NOW - 20 * DAY
        for i in range(6):  # a and b call 6 tokens together within minutes; c calls other tokens alone
            rows += [("a", f"s{i}", t0 + i * DAY), ("b", f"s{i}", t0 + i * DAY + 300)]
        for i in range(60):  # many other tokens called at the same time: 6 shared would be ~1 by chance
            rows.append(("c", f"c{i}", t0 + i * 3600 * 2))
        for h, tok, ts in rows:
            con.execute("INSERT INTO calls (tweet_id, handle, token, ts, kind, max24) VALUES (?,?,?,?,?,?)",
                        (f"{h}{tok}", h, tok, ts, "call", 1.0))
        for h in "abc":
            con.execute("INSERT OR IGNORE INTO kols (handle) VALUES (?)", (h,))
        score.mark_first(con)
        score.score_kols(con, CFG, NOW)
        score.build_groups(con, CFG)
        state, proven = validate.run(con, CFG, NOW)
        self.assertEqual(state, "malo")
        self.assertEqual(proven, 1)
        a, b, together, exp, lift, p, ok = con.execute("SELECT * FROM pair_tests").fetchone()
        self.assertEqual((a, b, together, ok), ("a", "b", 6, 1))
        self.assertLess(p, 0.01)
        s = json.loads(con.execute("SELECT stats FROM kols WHERE handle = 'c'").fetchone()[0])
        self.assertLessEqual(s["score_lo"], s["score_hi"])
        self.assertFalse(validate.gate_closed(con, CFG))
        con.execute("UPDATE kv SET value = ? WHERE key = 'validate'", (json.dumps({"state": "pada"}),))
        self.assertTrue(validate.gate_closed(con, CFG))
        self.assertFalse(validate.gate_closed(con, dict(CFG, validate={"gate": False})))


class Copies(unittest.TestCase):
    def test_big_after_small(self):
        con = store.connect(os.path.join(tempfile.mkdtemp(), "kol.db"))
        for h, f in [("small", 2000), ("big", 300000), ("peer", 2500)]:
            con.execute("INSERT INTO kols (handle, followers) VALUES (?,?)", (h, f))
        rows = []
        for i in range(3):  # small first, big 40 min later, three times
            rows += [("small", f"t{i}", NOW + i * DAY), ("big", f"t{i}", NOW + i * DAY + 2400)]
        rows += [("big", "u", NOW), ("small", "u", NOW + 600)]  # once the other way round
        rows += [("small", "p", NOW), ("peer", "p", NOW + 60)]  # peer is not big
        for h, tok, ts in rows:
            con.execute("INSERT INTO calls (tweet_id, handle, token, ts, kind) VALUES (?,?,?,?,?)",
                        (f"{h}{tok}", h, tok, ts, "call"))
        out = validate.copies(con, CFG)
        self.assertEqual(len(out), 1)
        a, b, n, lag, rev, toks = out[0]
        self.assertEqual((a, b, n, rev, round(lag)), ("small", "big", 3, 1, 40))


class Timeline(unittest.TestCase):
    def test_core_by_lower_bound_rotation_and_queries(self):
        from kol import collect
        con = store.connect(os.path.join(tempfile.mkdtemp(), "kol.db"))
        for i in range(12):  # k0..k11, each with 3 tokens; k0 lucky (high score, wide range), k1 proven
            h = f"k{i}"
            lo = {0: 20, 1: 60}.get(i, 40 - i)
            con.execute("INSERT INTO kols (handle, score, stats, bot) VALUES (?,?,?,?)",
                        (h, 70 if i == 0 else 55, json.dumps({"score_lo": lo}), 1 if i == 11 else 0))
            for j in range(3):
                con.execute("INSERT INTO calls (tweet_id, handle, token, ts, kind) VALUES (?,?,?,?,?)",
                            (f"{h}{j}", h, f"{h}t{j}", NOW - DAY, "call"))
        # an unscored account that called a winner early gets the first rotating slot
        con.execute("INSERT INTO kols (handle) VALUES ('winner')")
        for j in range(2):
            con.execute("INSERT INTO calls (tweet_id, handle, token, ts, kind, max24, pre2h) VALUES (?,?,?,?,?,?,?)",
                        (f"w{j}", "winner", f"w{j}", NOW - DAY, "call", 3.0, 0.1))
        cfg = dict(CFG, timeline=dict(CFG["timeline"], kols=6, core=3, per_query=4, refresh_d=1))
        hs = collect.timeline_handles(con, cfg, NOW)
        self.assertEqual(hs[:3], ["k1", "k2", "k3"])  # core by lower bound, the lucky k0 is not in the core
        self.assertEqual(hs[3], "winner")
        self.assertEqual(len(hs), 6)
        self.assertNotIn("k11", hs)  # bot
        seen = []
        n = collect.timeline(con, cfg, run=lambda src, actor, inp: seen.append(inp) or [], now=NOW)
        self.assertEqual(n, 0)
        self.assertEqual(len(seen), 1)
        self.assertEqual(len(seen[0]["searchTerms"]), 2)  # 6 handles, 4 per query
        self.assertIn("since:", seen[0]["searchTerms"][0])
        # next round: the core is read again, the rotating slots go to accounts not read yet
        hs2 = collect.timeline_handles(con, cfg, NOW + 2 * 3600)
        self.assertEqual(len(hs2), 6)
        self.assertEqual(hs2[:3], ["k1", "k2", "k3"])
        self.assertFalse(set(hs2[3:]) & set(hs[3:]))


class TwitterApiIo(unittest.TestCase):
    def setUp(self):  # keep test spend out of the shared usage meter
        from unittest import mock
        p = mock.patch("usage.meter.record")
        p.start()
        self.addCleanup(p.stop)

    def test_round_budget_and_paging(self):
        import datetime as dt
        from kol import collect, twapi
        con = store.connect(os.path.join(tempfile.mkdtemp(), "kol.db"))
        for i in range(30):
            h = f"k{i}"
            con.execute("INSERT INTO kols (handle, score, stats) VALUES (?,?,?)", (h, 50, json.dumps({"score_lo": 40})))
            for j in range(2):
                con.execute("INSERT INTO calls (tweet_id, handle, token, ts, kind) VALUES (?,?,?,?,?)",
                            (f"{h}{j}", h, f"{h}t{j}", NOW - DAY, "call"))
        ca = "HgxEGTZ1Epb64RrYqcuHkqb1gGWWnF5WcPTCDWzApump"

        def tw(tid, h, ts, text):
            created = dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%a %b %d %H:%M:%S +0000 %Y")
            return {"id": tid, "text": text, "createdAt": created, "author": {"userName": h, "followers": 900}}
        asked = []

        def get(q, cursor):
            asked.append((q, cursor))
            if not cursor:  # page 1: two new posts, more pages
                return {"tweets": [tw("1", "k0", NOW - 60, f"buy {ca}"),
                                   tw("2", "k1", NOW - 120, "gm")], "has_next_page": True, "next_cursor": "c2"}
            return {"tweets": [tw("3", "k2", NOW - 9 * 3600, f"old {ca}")], "has_next_page": True, "next_cursor": "c3"}
        cfg = dict(CFG, timeline_twapi={"every_min": 30, "kols": 30, "core": 20, "per_query": 25, "daily_usd": 0.7})
        n = collect.timeline_twapi(con, cfg, get=get, now=NOW)
        self.assertEqual(len([q for q in asked if not q[1]]), 2)  # 30 handles, 25 per query
        self.assertTrue(all("since_time:" in q for q, _ in asked))
        self.assertNotIn("c3", [c for _, c in asked])  # stopped paging at a post older than the last round
        self.assertGreaterEqual(n, 1)
        self.assertGreater(twapi.spent(con, NOW), 0)
        self.assertEqual(collect.timeline_twapi(con, cfg, get=get, now=NOW + 60), 0)  # too soon
        # over budget: nothing asked
        asked.clear()
        cfg2 = dict(cfg, timeline_twapi=dict(cfg["timeline_twapi"], daily_usd=0.0))
        collect.timeline_twapi(con, cfg2, get=get, now=NOW + 3600)
        self.assertEqual(asked, [])

    def test_retweet_skipped(self):
        from kol import collect
        self.assertEqual(collect.calls_from_tweet({"id": "1", "retweeted_tweet": {"id": "0"}, "text": "x",
                                                  "createdAt": "Fri Oct 30 21:58:58 +0000 2026",
                                                  "author": {"userName": "a"}}), [])


if __name__ == "__main__":
    unittest.main()
