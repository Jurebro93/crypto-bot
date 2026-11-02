"""kol/discover.py offline: winners searched backwards, trial ("na probi"), wallet proof, weekly AI profile check."""
import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import bots, discover, score, store  # noqa: E402

CFG = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kol", "config.json")))
DAY = 86400
NOW = 1793500000
CA = "HgxEGTZ1Epb64RrYqcuHkqb1gGWWnF5WcPTCDWzApump"


def tw(tid, h, ts, text):
    created = dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%a %b %d %H:%M:%S +0000 %Y")
    return {"id": tid, "text": text, "createdAt": created, "author": {"userName": h, "followers": 900}}


class Base(unittest.TestCase):
    def setUp(self):
        p = mock.patch("usage.meter.record")
        p.start()
        self.addCleanup(p.stop)
        self.con = store.connect(os.path.join(tempfile.mkdtemp(), "kol.db"))

    def ins(self, tid, h, tok, ts, kind="call", max24=None, pre2h=None, text="x"):
        self.con.execute("INSERT INTO calls (tweet_id, handle, token, ts, kind, max24, pre2h, text) VALUES "
                         "(?,?,?,?,?,?,?,?)", (tid, h, tok, ts, kind, max24, pre2h, text))


class Winners(Base):
    def test_searches_before_the_rise_once(self):
        self.ins("a", "late", CA, NOW - 5 * 3600, max24=0.2, pre2h=1.5)   # posted after it had doubled
        self.ins("b", "early", CA, NOW - 9 * 3600, max24=2.5, pre2h=0.0)
        self.ins("c", "x", "Other1111111111111111111111111111111pump", NOW - 3600, max24=0.1)
        t = discover.winner_targets(self.con, CFG, NOW)
        self.assertEqual([x[0] for x in t], [CA])
        self.assertEqual(t[0][2], NOW - 5 * 3600)  # until = first post after the doubling
        asked = []

        def get(q, cursor):
            asked.append(q)
            return {"tweets": [tw("9", "newguy", NOW - 7 * 3600, f"aping {CA}")], "has_next_page": False}
        n = discover.winners(self.con, CFG, get=get, now=NOW)
        self.assertEqual(n, 1)
        self.assertIn(f"until_time:{NOW - 5 * 3600}", asked[0])
        self.assertTrue(asked[0].startswith(CA))
        self.assertEqual(self.con.execute("SELECT source FROM calls WHERE handle='newguy'").fetchone()[0], "kol_win")
        asked.clear()
        self.assertEqual(discover.winners(self.con, CFG, get=get, now=NOW + 60), 0)  # searched once
        self.assertEqual(asked, [])

    def test_own_budget(self):
        for i in range(6):
            self.ins(f"w{i}", "e", f"Tok{i}" + "1" * 36 + "pump", NOW - 3600, max24=3.0)

        def get(q, cursor):
            return {"tweets": [tw(f"{q[:5]}{k}", "a", NOW - 7200, "gm") for k in range(20)], "has_next_page": False}
        cfg = dict(CFG, discover=dict(CFG["discover"], winners_usd=0.004, win_per_run=6))
        discover.winners(self.con, cfg, get=get, now=NOW)
        done = self.con.execute("SELECT COUNT(*) FROM searches WHERE target LIKE 'win:%'").fetchone()[0]
        self.assertEqual(done, 2)  # $0.003 per page of 20: the third would go over $0.004


    def test_runs_after_timelines_used_their_budget(self):
        self.ins("b", "early", CA, NOW - 9 * 3600, max24=2.5, pre2h=0.0)
        day = __import__("time").strftime("%Y-%m-%d", __import__("time").gmtime(NOW))
        self.con.execute("INSERT INTO kv VALUES (?, ?)", (f"twapi:{day}", "0.70"))  # timeline share all used

        def get(q, cursor):
            return {"tweets": [tw("9", "newguy", NOW - 10 * 3600, f"aping {CA}")], "has_next_page": False}
        self.assertEqual(discover.winners(self.con, CFG, get=get, now=NOW), 1)
        self.assertLess(discover.disc_left(self.con, CFG, NOW), CFG["discover"]["daily_usd"])

class Trial(Base):
    def test_trial_bought_and_watch(self):
        for h, n, first in (("proven", 12, NOW - 30 * DAY), ("newbie", 12, NOW - 3 * DAY), ("few", 3, NOW - 30 * DAY)):
            st = {"measured": n, "hit_rate": 0.9, "prepump_rate": 0.0, "med_max24": 2.0, "med_views": 5000}
            self.con.execute("INSERT INTO kols (handle, score, stats) VALUES (?,?,?)", (h, 80, json.dumps(st)))
            self.ins(f"{h}0", h, f"{h}tok", first)
        self.ins("buy1", "proven", "proventok", NOW - 29 * DAY, kind="buy")
        trial = discover.annotate(self.con, CFG, NOW)
        self.assertEqual(trial, {"newbie", "few"})
        s = json.loads(self.con.execute("SELECT stats FROM kols WHERE handle='proven'").fetchone()[0])
        self.assertEqual((s["trial"], s["bought"]), (False, 1))
        s = json.loads(self.con.execute("SELECT stats FROM kols WHERE handle='newbie'").fetchone()[0])
        self.assertIn("dana", s["trial_why"])
        self.assertEqual(score.build_watch(self.con, CFG, NOW), ["proven"])

    def test_rugger_read_less_often(self):
        st = {"measured": 40, "hit_rate": 0.9, "prepump_rate": 0.0, "med_max24": 2.0, "med_views": 5000,
              "rug_rate": 0.875}
        self.con.execute("INSERT INTO kols (handle, score, stats) VALUES (?,?,?)", ("DegenWar01", 80, json.dumps(st)))
        self.ins("d0", "DegenWar01", "tok", NOW - 40 * DAY)
        discover.annotate(self.con, CFG, NOW)
        s = json.loads(self.con.execute("SELECT stats FROM kols").fetchone()[0])
        self.assertTrue(s["rugger"])
        self.assertIn("88%", s["rug_why"])
        self.assertEqual(discover.ruggers(self.con), {"DegenWar01"})
        self.assertEqual(score.build_watch(self.con, CFG, NOW), ["DegenWar01"])  # still gets a chance
        from kol import collect
        cfg = dict(CFG, timeline=dict(CFG["timeline"], kols=10, core=5, min_calls=1, rug_refresh_d=3))
        self.con.execute("DELETE FROM watch")
        collect._searched(self.con, "tl:DegenWar01", "timeline_kol", NOW - DAY)
        self.assertNotIn("DegenWar01", collect.timeline_handles(self.con, cfg, NOW))  # read a day ago: wait 3
        self.assertIn("DegenWar01", collect.timeline_handles(self.con, cfg, NOW + 3 * DAY))

    def test_few_views(self):
        st = {"measured": 20, "med_views": 15}
        self.con.execute("INSERT INTO kols (handle, score, stats) VALUES (?,?,?)", ("ghost", 80, json.dumps(st)))
        self.ins("g0", "ghost", "t", NOW - 40 * DAY)
        self.assertEqual(discover.annotate(self.con, CFG, NOW), {"ghost"})


class Audit(Base):
    def client(self, verdict):
        def create(**kw):
            self.prompts.append(kw["messages"][0]["content"])
            return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(
                {"verdict": verdict, "why": "profil sportaša, objave su spam"}))],
                usage=SimpleNamespace(input_tokens=500, output_tokens=40))
        return SimpleNamespace(messages=SimpleNamespace(create=create))

    def get(self, url, params):
        if "user/info" in url:
            if params["userName"] == "gone":
                return {"status": "success", "data": {"unavailable": True, "unavailableReason": "Suspended"}}
            return {"status": "success", "data": {"name": "Maison", "description": "QB class of 2026 🏈",
                                                  "createdAt": "2019-01-01", "followers": 900,
                                                  "pinnedTweetIds": ["5"]}}
        return {"tweets": [{"id": "5", "text": "Committed to State University!"}]}

    def test_bad_verdict_flags_account(self):
        self.prompts = []
        for h in ("hacked", "gone"):
            self.con.execute("INSERT INTO kols (handle, score, stats) VALUES (?,?,?)", (h, 90, "{}"))
            self.ins(f"{h}0", h, CA, NOW - DAY, text=f"$X is in the listing window {CA} ab12c Click below to vote")
        n = discover.audit(self.con, CFG, client=self.client("hakiran"), get=self.get, now=NOW)
        self.assertEqual(n, 2)
        self.assertIn("QB class of 2026", self.prompts[0])
        self.assertIn("Committed to State University", self.prompts[0])
        v = dict(self.con.execute("SELECT handle, verdict FROM audits"))
        self.assertEqual(v, {"hacked": "hakiran", "gone": "suspendiran"})
        flagged = bots.detect(self.con, CFG)
        self.assertEqual(flagged, {"hacked", "gone"})
        why = self.con.execute("SELECT bot_why FROM kols WHERE handle='hacked'").fetchone()[0]
        self.assertIn("spam", why)  # the text rule already explains it; the audit would too
        # checked again only after a week
        self.assertEqual(discover.audit_targets(self.con, CFG, NOW + DAY), [])

    def test_good_verdict_stays(self):
        self.prompts = []
        self.con.execute("INSERT INTO kols (handle, score, stats) VALUES (?,?,?)", ("real", 90, "{}"))
        self.ins("r0", "real", CA, NOW - DAY, text="chart looks good")
        discover.audit(self.con, CFG, client=self.client("kol"), get=self.get, now=NOW)
        self.assertEqual(bots.detect(self.con, CFG), set())
        self.assertEqual(discover.bad_audits(self.con, CFG), {})


class Graph(Base):
    def test_followed_by_two_proven_kols_gets_read(self):
        for h in ("pro1", "pro2", "newbie"):
            st = {"measured": 20, "trial": h == "newbie"}
            self.con.execute("INSERT INTO kols (handle, score, stats) VALUES (?,?,?)", (h, 80, json.dumps(st)))
        asked = []

        def get(url, params):
            asked.append(params["userName"])
            return {"followings": [
                {"userName": "hiddengem", "followers_count": 4000, "description": "solana degen, early calls"},
                {"userName": "nbaplayer", "followers_count": 900000, "description": "basketball"},
                {"userName": "tinycaller", "followers_count": 50, "description": "memecoin calls"},
                {"userName": f"only_{params['userName']}", "followers_count": 9000, "description": "crypto"}]}
        self.assertEqual(discover.graph(self.con, CFG, get=get, now=NOW), 2)
        self.assertEqual(sorted(asked), ["pro1", "pro2"])  # trial KOLs are not a source
        self.assertEqual(discover.graph_candidates(self.con, CFG), ["hiddengem"])
        self.assertEqual(discover.graph(self.con, CFG, get=get, now=NOW + 60), 0)  # weekly
        from kol import collect
        cfg = dict(CFG, timeline=dict(CFG["timeline"], kols=10, core=0))
        self.assertIn("hiddengem", collect.timeline_handles(self.con, cfg, NOW))
        collect._searched(self.con, "tl:hiddengem", "timeline_kol", NOW)
        self.assertNotIn("hiddengem", collect.timeline_handles(self.con, cfg, NOW + 30 * DAY))  # asked once


if __name__ == "__main__":
    unittest.main()
