"""5.11.: KOL backfill on the server without a retrospective file (token list from kol.db) and the once-per-budget
guard (kv backfill_done) that keeps a redeploy from paying twice.

    python3 -m unittest tests.test_backfill_server_offline
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import backfill, store  # noqa: E402

DAY = 86400
NOW = 1793500000


class TokensFromDb(unittest.TestCase):
    def setUp(self):
        self.con = store.connect(os.path.join(tempfile.mkdtemp(), "kol.db"))
        c = self.con
        # WIN: created 10 days ago, two calls, best +250%; snapshots peak a day after the first call
        c.execute("INSERT INTO tokens (token, symbol, created_ts) VALUES ('WIN', 'W', ?)", (NOW - 10 * DAY,))
        c.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, max24) VALUES ('1','WIN','a',?, 'call', 2.5)", (NOW - 9 * DAY,))
        c.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, max24) VALUES ('2','WIN','b',?, 'call', 0.3)", (NOW - 8 * DAY,))
        for i, px in enumerate([1.0, 3.0, 2.0]):
            c.execute("INSERT INTO snaps (token, ts, price) VALUES ('WIN', ?, ?)", (NOW - 9 * DAY + i * 12 * 3600, px))
        # LOSE: no tokens row, no snapshots, best +20%
        c.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, max24) VALUES ('3','LOSE','a',?, 'call', 0.2)", (NOW - 5 * DAY,))
        # OLD: outside max_age_d; BAD: invalid measure; NONE: not measured yet
        c.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, max24) VALUES ('4','OLD','a',?, 'call', 5.0)", (NOW - 200 * DAY,))
        c.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, max24, bad) VALUES ('5','BAD','a',?, 'call', 50.0, 'skok')", (NOW - DAY,))
        c.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES ('6','NONE','a',?, 'call')", (NOW - DAY,))
        c.commit()

    def test_list(self):
        toks = {t["mint"]: t for t in backfill.tokens_from_db(self.con, now=NOW)}
        self.assertEqual(set(toks), {"WIN", "LOSE"})
        w = toks["WIN"]
        self.assertTrue(w["winner"])
        self.assertAlmostEqual(w["peak_mult"], 3.5)
        self.assertEqual(w["launch_ts"], NOW - 10 * DAY)
        self.assertEqual(w["peak_ts"], NOW - 9 * DAY + 12 * 3600)       # highest snapshot
        self.assertEqual(w["symbol"], "W")
        lo = toks["LOSE"]
        self.assertFalse(lo["winner"])
        self.assertEqual(lo["launch_ts"], NOW - 6 * DAY)                 # a day before the first call
        self.assertEqual(lo["peak_ts"], NOW - 4 * DAY)                   # a day after it
        picked = backfill.pick(list(toks.values()), 300, 300)
        self.assertEqual([t["mint"] for t in picked], ["WIN", "LOSE"])
        self.assertIn("since:", backfill.token_query(w["mint"], w["launch_ts"], w["peak_ts"]))


class OncePerBudget(unittest.TestCase):
    def test_second_run_with_same_budget_is_skipped(self):
        import run_kol
        from hype import apify
        tmp = tempfile.mkdtemp()
        old_db, store.DB = store.DB, os.path.join(tmp, "kol.db")   # cmd_backfill opens store.connect() itself
        runs = []
        old_run, old_spent = apify.run, apify.spent
        apify.run = lambda *a, **k: runs.append(a) or []
        apify.spent = lambda *a, **k: 0.0
        try:
            con = store.connect()
            con.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, max24) VALUES ('1','T1','a',?, 'call', 1.5)",
                        (NOW - DAY,))
            con.commit()
            con.close()
            steps = []
            for name in ("cmd_collect", "cmd_measure", "cmd_score"):
                setattr(run_kol, name, lambda a, con=None, cfg=None, _n=name: steps.append(_n))
            a = run_kol.main.__globals__["argparse"].Namespace(tokens=None, winners=5, losers=5, per_token=3, kols=2,
                                                               per_kol=3, budget=28.0, force=False, verbose=False)
            run_kol.cmd_backfill(a)
            self.assertEqual(len(runs), 1)               # one token search (no KOL with 1000 followers for timelines)
            self.assertEqual(steps, ["cmd_collect", "cmd_measure", "cmd_score"])
            con = store.connect()
            self.assertEqual(con.execute("SELECT value FROM kv WHERE key = 'backfill_done'").fetchone()[0], "28.0")
            con.close()
            run_kol.cmd_backfill(a)                      # same budget again (a redeploy): nothing
            self.assertEqual(len(runs), 1)
            self.assertEqual(len(steps), 3)
            a.force = True
            run_kol.cmd_backfill(a)                      # --force: searches done before are skipped by the searches table
            self.assertEqual(len(runs), 1)
            self.assertEqual(len(steps), 6)
        finally:
            apify.run, apify.spent = old_run, old_spent
            store.DB = old_db


if __name__ == "__main__":
    unittest.main()
