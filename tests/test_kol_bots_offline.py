"""1.11. fixes: scanner bots are not KOLs, EVM addresses are not Solana tokens, dust-cap calls do not count,
the daily learning does not re-run on every deploy and empty runs do not pile up."""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kol import bots, collect, converge, measure, score, store  # noqa: E402

CFG = json.load(open(os.path.join(ROOT, "kol", "config.json")))
T0 = 1793390000
MINTS = [f"{i}Gx" + "A" * 36 + "pump" for i in range(1, 10)]


def call(con, tid, handle, token, ts, text, kind=None):
    collect.save(con, [{"tweet_id": tid, "token": token, "handle": handle, "ts": ts, "url": "", "text": text,
                        "followers": 1000, "likes": 0, "retweets": 0, "views": 0, "kind": kind or collect.kind_of(text),
                        "match": "ca", "source": "x_buzz", "symbol": None}])


class Detect(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.con = store.connect(os.path.join(self.d, "kol.db"))

    def test_scanner_pair_no_longer_a_group(self):
        # two scanners post every fresh token minutes apart; one human calls 2 of them
        for i, m in enumerate(MINTS):
            call(self.con, f"b{i}", "bitecong", m, T0 + i * 600, f"🤖 AI Signal (SOL) $T{i}\n\nCA: {m}\n\nfresh pumpfun")
            call(self.con, f"s{i}", "blossomscanner", m, T0 + i * 600 + 60, f"New token {m} mc 5k")
        call(self.con, "h1", "realguy", MINTS[0], T0 + 120, f"aping this one {MINTS[0]}")
        call(self.con, "h2", "realguy", MINTS[1], T0 + 700, f"this looks good {MINTS[1]}")
        score.run(self.con, CFG, now=T0 + 7200)
        flagged = {h for (h,) in self.con.execute("SELECT handle FROM kols WHERE bot = 1")}
        self.assertEqual(flagged, {"bitecong", "blossomscanner"})
        kinds = dict(self.con.execute("SELECT handle, MIN(kind) FROM calls GROUP BY handle"))
        self.assertEqual(kinds, {"bitecong": "bot", "blossomscanner": "bot", "realguy": "call"})
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM groups").fetchone()[0], 0)
        self.assertEqual(store.bot_handles(os.path.join(self.d, "kol.db")), {"bitecong", "blossomscanner"})
        # a new post of a known bot is stored as 'bot' right away
        call(self.con, "b99", "bitecong", MINTS[2], T0 + 9000, f"🤖 AI Signal $X CA: {MINTS[2]}")
        self.assertEqual(self.con.execute("SELECT kind FROM calls WHERE tweet_id='b99'").fetchone()[0], "bot")
        # convergence ignores them
        ev, _, _ = converge.events(T0 + 9100, 86400, kol_db=os.path.join(self.d, "kol.db"),
                                   tg_db=os.path.join(self.d, "none.db"), hype_db=os.path.join(self.d, "none.db"))
        self.assertEqual({e[3] for e in ev}, {"realguy"})

    def test_classify_rules(self):
        posts = [(T0 + i * 60, MINTS[i % 9], f"$A{i} {MINTS[i % 9]} looks good to me fam") for i in range(9)]
        self.assertEqual(bots.classify("human", posts, CFG)[0], False)
        spam = [(T0 + i * 60, f"{i}Q" + "B" * 38 + "pump", f"txt {i}") for i in range(45)]
        self.assertEqual(bots.classify("spammer", spam, CFG)[0], True)
        self.assertEqual(bots.classify("x", [(T0, MINTS[0], "a")], dict(CFG, bots=dict(CFG["bots"], force=["X"])))[0],
                         True)


class Parse(unittest.TestCase):
    def test_evm_address_is_not_a_solana_token(self):
        self.assertEqual(collect.cas_in("CA: 0xefd8469bbe9b7431668acda71d8dfa49f7634444"), [])
        self.assertEqual(collect.cas_in(f"CA: {MINTS[0]}"), [MINTS[0]])

    def test_scam_warning_is_not_a_call(self):
        self.assertEqual(collect.kind_of("🔴 SCAM ALERT - $ARNOLD | Stay away, it'll rug"), "warn")
        self.assertEqual(collect.kind_of("new gem, aping"), "call")


class Validate(unittest.TestCase):
    def test_dust_cap_and_wick(self):
        self.assertEqual(measure.why_bad(143, 64, CFG), "mcap")
        self.assertIsNone(measure.why_bad(50000, 3.0, CFG))
        self.assertEqual(measure.why_bad(None, 500, CFG), "skok")
        # one dust wick: high 100 on a candle that opened and closed at 1 counts as 3 at most
        c = [(T0 - 600, 1, 1, 1, 1, 10), (T0, 1, 1, 1, 1, 10), (T0 + 300, 1, 100, 1, 1, 10)]
        o = measure.outcome(c, T0 + 10, T0 + 30 * 3600, CFG)
        self.assertAlmostEqual(o["max24"], 2.0)

    def test_revalidate_old_rows(self):
        d = tempfile.mkdtemp()
        con = store.connect(os.path.join(d, "kol.db"))
        call(con, "1", "a", MINTS[0], T0, f"buy {MINTS[0]}")
        call(con, "2", "a", MINTS[1], T0, f"buy {MINTS[1]}")
        con.execute("UPDATE calls SET mcap0 = 143, max24 = 64, complete = 1 WHERE tweet_id = '1'")
        con.execute("UPDATE calls SET mcap0 = 90000, max24 = 30, complete = 1, measured_ts = 1 WHERE tweet_id = '2'")
        measure.revalidate(con, CFG)
        r1 = con.execute("SELECT bad, max24 FROM calls WHERE tweet_id='1'").fetchone()
        r2 = con.execute("SELECT bad, complete, measured_ts FROM calls WHERE tweet_id='2'").fetchone()
        self.assertEqual(r1, ("mcap", None))
        self.assertEqual(r2, (None, 0, None))   # measured again once with the wick cap

    def test_fake_evm_token_rows_removed(self):
        d = tempfile.mkdtemp()
        con = store.connect(os.path.join(d, "kol.db"))
        call(con, "1", "a", "xefd8469bbe9b7431668acda71d8dfa49f7634444", T0, "x", kind="call")
        call(con, "2", "a", MINTS[0], T0, "y", kind="call")
        self.assertEqual(score.drop_fake_tokens(con), 1)
        self.assertEqual([t for (t,) in con.execute("SELECT token FROM calls")], [MINTS[0]])


class Learning(unittest.TestCase):
    def test_empty_runs_pruned(self):
        from learn import store as lstore
        con = lstore.connect(os.path.join(tempfile.mkdtemp(), "hype.db"))
        day = 1793404800
        for i in range(5):
            lstore.log_run(con, day + i * 600, "moonshot", 0, 2.0, False, None, None, {}, {}, "premalo")
        lstore.log_run(con, day + 4000, "rizican", 300, 1.0, True, 0.2, 0.3, {}, {}, "ok")
        lstore.log_run(con, day + 86400, "moonshot", 3, 2.0, False, None, None, {}, {}, "premalo")
        lstore.prune_empty(con)
        rows = con.execute("SELECT klasa, ts FROM learn_runs ORDER BY ts").fetchall()
        self.assertEqual([tuple(r) for r in rows],
                         [("moonshot", day + 2400), ("rizican", day + 4000), ("moonshot", day + 86400)])

    def test_schedule_survives_restart(self):
        import run_sched
        old = run_sched.STATE
        run_sched.STATE = os.path.join(tempfile.mkdtemp(), "s.json")
        try:
            self.assertIsNone(run_sched._last_day("learn"))
            run_sched._set_last_day("learn", "2026-11-01")
            self.assertEqual(run_sched._last_day("learn"), "2026-11-01")
        finally:
            run_sched.STATE = old


if __name__ == "__main__":
    unittest.main()
