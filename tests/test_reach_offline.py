"""5.11.: reach (kol/reach.py): followers + followed by proven KOLs as the starting score and as the
'Veliki račun zove' strategy filter."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import reach, score, store as kstore  # noqa: E402

CFG = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kol", "config.json")))
NOW = 1_800_000_000
DAY = 86400


class Prior(unittest.TestCase):
    def test_prior_grows_with_reach_and_caps(self):
        self.assertEqual(reach.prior(35, 300, 0), 35.0)
        mid = reach.prior(35, 40000, 0)
        big = reach.prior(35, 40000, 3)
        huge = reach.prior(35, 2_000_000, 9)
        self.assertTrue(35 < mid < big < huge == 65)   # +15 followers +15 followed-by at most
        self.assertTrue(reach.is_big(36800, 2))
        self.assertFalse(reach.is_big(36800, 1))
        self.assertFalse(reach.is_big(5000, 5))

    def test_score_uses_reach_prior_and_strategy_sees_big_accounts(self):
        con = kstore.connect(os.path.join(tempfile.mkdtemp(), "kol.db"))
        from kol import discover
        con.execute(discover.FOLLOW_SCHEMA)
        for src in ("moby", "unipcs"):
            con.execute("INSERT INTO follows VALUES (?, 'wirelyss', ?, 36800, 'trader')", (src, NOW))
        for h, foll in (("wirelyss", 36800), ("nobody", 300)):
            con.execute("INSERT INTO kols (handle, followers) VALUES (?, ?)", (h, foll))
            for i in range(2):   # two measured calls each, identical outcomes
                con.execute("INSERT INTO calls (tweet_id, handle, token, ts, kind, first_by_kol, max24, r1h, vol_lift, rug, pre2h, followers, complete) "
                            "VALUES (?,?,?,?,'call',1,0.5,0.2,2.0,0,0.0,?,1)", (f"{h}{i}", h, f"tok-{h}{i}", NOW - (3 - i) * DAY, foll))
        con.commit()
        score.score_kols(con, CFG, NOW)
        st = {h: (sc, json.loads(s)) for h, sc, s in con.execute("SELECT handle, score, stats FROM kols")}
        self.assertEqual(st["wirelyss"][1]["doseg"]["followed_by"], 2)
        self.assertGreater(st["wirelyss"][1]["prior"], st["nobody"][1]["prior"])
        self.assertGreater(st["wirelyss"][0], st["nobody"][0])               # same calls, bigger reach, higher score
        from strat import signals
        src = signals.Sources(kol_db=os.path.join(os.path.dirname(con.execute("PRAGMA database_list").fetchone()[2]), "kol.db"),
                              tg_db="/nonexistent/tg.db", hype_db="/nonexistent/hype.db", paper_db="/nonexistent/paper.db")
        con.close()
        out = src.read(NOW, 5 * DAY)
        self.assertEqual({e[0] for e in out["veliki"]}, {"tok-wirelyss0", "tok-wirelyss1"})
        self.assertTrue(all("wirelyss (36k, prate ga 2)" in e[2] for e in out["veliki"]))


if __name__ == "__main__":
    unittest.main()
