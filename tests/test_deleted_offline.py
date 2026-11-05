"""5.11.: deleted X posts (kol/deleted.py): re-check by tweet id, mark, keep counting, punish deleting losers.

    python3 -m unittest tests.test_deleted_offline
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import deleted, score, store as kstore  # noqa: E402

CFG = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kol", "config.json")))
DAY = 86400
NOW = 1_800_000_000


def _call(con, tid, h, tok, ts, max24, rug=0, complete=1):
    con.execute("INSERT INTO calls (tweet_id, handle, token, ts, kind, first_by_kol, max24, r1h, vol_lift, rug, pre2h, "
                "followers, complete) VALUES (?,?,?,?,'call',1,?,?,2.0,?,0.0,1000,?)",
                (tid, h, tok, ts, max24, max24 / 3, rug, complete))
    con.execute("INSERT OR IGNORE INTO kols (handle, followers) VALUES (?, 1000)", (h,))


class Due(unittest.TestCase):
    def test_only_old_measured_x_calls_never_or_long_ago_checked(self):
        con = kstore.connect(os.path.join(tempfile.mkdtemp(), "kol.db"))
        _call(con, "100", "a", "T1", NOW - 3 * DAY, 1.0)                 # due
        _call(con, "101", "a", "T2", NOW - 3600, 1.0)                    # too fresh
        _call(con, "102", "a", "T3", NOW - 3 * DAY, 1.0, complete=0)     # not measured yet
        _call(con, "hook-1", "a", "T4", NOW - 3 * DAY, 1.0)              # not an X id
        _call(con, "103", "tg:chan", "T5", NOW - 3 * DAY, 1.0)           # Telegram
        _call(con, "104", "a", "T6", NOW - 3 * DAY, 1.0)
        con.execute("UPDATE calls SET checked_ts = ? WHERE tweet_id = '104'", (NOW - DAY,))   # checked yesterday
        _call(con, "105", "a", "T7", NOW - 30 * DAY, 1.0)
        con.execute("UPDATE calls SET checked_ts = ? WHERE tweet_id = '105'", (NOW - 20 * DAY,))   # due again
        con.commit()
        self.assertEqual(deleted.due(con, CFG, NOW), ["100", "105"])


class CheckAndScore(unittest.TestCase):
    def setUp(self):
        self.con = kstore.connect(os.path.join(tempfile.mkdtemp(), "kol.db"))
        t0 = NOW - 20 * DAY
        # "clean" and "hider" have the same 8 calls: 4 winners, 4 losers; hider deleted 3 of the losers
        for h, base in (("clean", 100), ("hider", 200)):   # numeric ids like real X posts
            for i in range(8):
                _call(self.con, str(base + i), h, f"tok-{h}{i}", t0 + i * DAY, 1.5 if i < 4 else -0.6, rug=int(i == 7))
        self.con.commit()

    def test_check_marks_missing_ids_and_skips_empty_batches(self):
        log = []
        calls = []
        def fetch(batch):
            calls.append(list(batch))
            return [i for i in batch if i not in ("205", "206", "207")]
        checked, gone = deleted.check(self.con, CFG, NOW, fetch=fetch, log=log.append)
        self.assertEqual((checked, gone), (16, 3))
        self.assertEqual(sorted(t for t, in self.con.execute("SELECT tweet_id FROM calls WHERE deleted_ts IS NOT NULL")),
                         ["205", "206", "207"])
        self.assertEqual(deleted.due(self.con, CFG, NOW), [])                      # everything checked now
        self.assertEqual(deleted.summary(self.con, "hider"), {"deleted": 3, "deleted_losers": 3, "deleted_winners": 0})
        # an empty answer for a whole batch is an API hiccup: nothing is marked deleted
        self.con.execute("UPDATE calls SET checked_ts = NULL, deleted_ts = NULL")
        self.con.commit()
        checked, gone = deleted.check(self.con, CFG, NOW, fetch=lambda b: [], log=log.append)
        self.assertEqual((checked, gone), (0, 0))
        self.assertTrue(any("prazan odgovor" in m for m in log))

    def test_deleted_calls_still_count_and_hiding_losers_costs_points(self):
        deleted.check(self.con, CFG, NOW, fetch=lambda b: [i for i in b if i not in ("205", "206", "207")])
        score.run(self.con, CFG, NOW)
        st = {h: json.loads(s) for h, s in self.con.execute("SELECT handle, stats FROM kols")}
        sc = dict(self.con.execute("SELECT handle, score FROM kols"))
        self.assertEqual(st["hider"]["measured"], 8)                   # deleted posts are not forgotten
        self.assertAlmostEqual(st["hider"]["hit_rate"], st["clean"]["hit_rate"])
        self.assertEqual((st["hider"]["deleted"], st["hider"]["deleted_losers"]), (3, 3))
        self.assertEqual(st["clean"]["deleted"], 0)
        self.assertLess(sc["hider"], sc["clean"])
        self.assertAlmostEqual(st["hider"]["parts"]["deletes"], -15 * 1.0 * 3 / 5, places=1)


if __name__ == "__main__":
    unittest.main()
