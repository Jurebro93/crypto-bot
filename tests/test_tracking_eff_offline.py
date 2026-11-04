"""5.11.: tracking efficiency. (1) kol/chainwatch.wanted follows our own scored wallets next to the public
leaderboards; (2) wallets/pnl.score sees the open book (half the unrealized result, bags = old open losers);
(3) kol/score rescores only the KOLs whose calls changed since the last round, with the same numbers as a full run.

    python3 -m unittest tests.test_tracking_eff_offline
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import chainwatch, idents, score, store as kstore  # noqa: E402
from wallets import pnl, store as wstore  # noqa: E402

CFG = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kol", "config.json")))
DAY = 86400
NOW = 1793500000


def _wallet_db(path, rows):
    """rows: (wallet, score, copy_score, tier, labels)"""
    con = wstore.connect(path)
    for w, sc, cs, tier, lab in rows:
        con.execute("INSERT INTO wallets (wallet, score, copy_score, tier, labels, stats) VALUES (?,?,?,?,?,?)",
                    (w, sc, cs, tier, json.dumps(lab), "{}"))
    con.commit()
    con.close()


class Wanted(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.con = kstore.connect(os.path.join(self.tmp, "kol.db"))
        idents.save(self.con, [{"wallet": f"ID{i}", "name": f"k{i}", "twitter": None, "telegram": None, "pnl": 10 - i,
                                "wins": 1, "losses": 0, "rank": i} for i in range(8)], "kolscan")
        self.wdb = os.path.join(self.tmp, "wallets.db")
        _wallet_db(self.wdb, [("C1", 70, 80, "A", []), ("C2", 60, 61, "A", []), ("BAD", 90, 95, "A", ["rugger"]),
                              ("C3", 50, 40, "B", []), ("LOW", 50, 20, "C", []), ("S1", 55, 0, "S", ["bot"]),
                              ("S2", 30, 0, "S", []), ("ID1", 99, 99, "A", [])])

    def test_union_by_share_and_leftovers(self):
        cfg = {"max_wallets": 10, "share": {"ids": 0.5, "copy": 0.4, "signal": 0.1}, "min_copy": 35}
        got = chainwatch.wanted(self.con, cfg, wallet_db=self.wdb)
        self.assertEqual(got[:5], ["ID0", "ID1", "ID2", "ID3", "ID4"])        # 50%: leaderboard by rank
        self.assertEqual(got[5:8], ["C1", "C2", "C3"])                        # 40%: best copy scores, no rugger
        self.assertEqual(got[8], "S1")                                        # 10%: tier S, score >= 40
        self.assertEqual(got[9], "ID5")                                       # leftover slot -> next leaderboard wallet
        self.assertNotIn("BAD", got)
        self.assertNotIn("LOW", got)
        self.assertEqual(len(got), len(set(got)))                             # ID1 is in both lists, once

    def test_no_registry_keeps_old_behaviour(self):
        cfg = {"max_wallets": 3}
        got = chainwatch.wanted(self.con, cfg, wallet_db=os.path.join(self.tmp, "none.db"))
        self.assertEqual(got, ["ID0", "ID1", "ID2"])

    def test_sync_sends_the_union(self):
        calls = []
        api = lambda m, p="", b=None: calls.append((m, p, b)) or ([] if m == "GET" else {"webhookID": "H1"})
        os.environ["RENDER_EXTERNAL_URL"], os.environ["KOL_HOOK_KEY"] = "https://x.example", "k"
        old = wstore.DB
        wstore.DB = self.wdb
        try:
            self.assertTrue(chainwatch.sync(self.con, {"max_wallets": 4, "resync_h": 24}, 1000, api, log=lambda *a: None))
        finally:
            wstore.DB = old
            del os.environ["RENDER_EXTERNAL_URL"], os.environ["KOL_HOOK_KEY"]
        self.assertEqual(calls[1][2]["accountAddresses"], ["ID0", "ID1", "C1", "C2"])


def _rows(n_win=8, n_lose=4):
    rows = []
    for i in range(n_win + n_lose):
        m, t = f"M{i}", 10_000 + i * 3600
        out = 3.0 if i < n_win else 0.5
        rows += [{"sig": f"b{i}", "ts": t, "mint": m, "tokens": 100, "sol": -1.0, "kind": "buy"},
                 {"sig": f"s{i}", "ts": t + 1800, "mint": m, "tokens": -100, "sol": out, "kind": "sell"}]
    return rows


class OpenBook(unittest.TestCase):
    def test_bag_holder_scores_lower_than_clean_wallet(self):
        now = 10_000 + 30 * DAY
        clean = _rows()
        s_clean = pnl.score(pnl.positions(clean), clean, now=now)
        # same closed trades plus 6 old open positions down 90% (bags), bought 20 days ago
        bags = clean + [{"sig": f"ob{i}", "ts": now - 20 * DAY, "mint": f"B{i}", "tokens": 100, "sol": -1.0, "kind": "buy"}
                        for i in range(6)]
        prices = {f"B{i}": 0.001 for i in range(6)}
        s_bags = pnl.score(pnl.positions(bags, prices), bags, now=now)
        self.assertEqual(s_clean["closed_pnl_sol"], s_bags["closed_pnl_sol"])   # closed book identical
        self.assertEqual(s_bags["bags"], 6)
        self.assertAlmostEqual(s_bags["bag_share"], 6 / 18, places=2)
        self.assertAlmostEqual(s_bags["unrealized_sol"], -5.4)
        self.assertAlmostEqual(s_bags["scored_pnl_sol"], s_bags["closed_pnl_sol"] - 2.7)   # half the open loss
        self.assertLess(s_bags["score"], s_clean["score"] * 0.9)
        self.assertLess(s_bags["copy_score"], s_clean["copy_score"] * 0.6)
        self.assertTrue(any("gubitnike" in w for w in s_bags["copy_notes"]))

    def test_open_losses_bigger_than_closed_profit_means_minus(self):
        now = 10_000 + 30 * DAY
        rows = _rows(n_win=10, n_lose=2) + [{"sig": "big", "ts": now - 3 * DAY, "mint": "BIG", "tokens": 100, "sol": -50.0,
                                            "kind": "buy"}]
        s = pnl.score(pnl.positions(rows, {"BIG": 0.02}), rows, now=now)   # 50 SOL in, worth 2: -48 open, half of it beats +19 closed
        self.assertGreater(s["closed_pnl_sol"], 0)
        self.assertLess(s["scored_pnl_sol"], 0)
        self.assertEqual(s["copy_score"], 0)
        self.assertEqual(s["bags"], 0)   # 3 days old: not a bag yet, but it still counts
        self.assertIn("u minusu s otvorenim pozicijama", s["copy_notes"])

    def test_recent_open_winner_counts_half(self):
        now = 10_000 + 30 * DAY
        rows = _rows() + [{"sig": "o", "ts": now - DAY, "mint": "O", "tokens": 100, "sol": -1.0, "kind": "buy"}]
        s = pnl.score(pnl.positions(rows, {"O": 0.03}), rows, now=now)
        self.assertAlmostEqual(s["unrealized_sol"], 2.0)
        self.assertAlmostEqual(s["scored_pnl_sol"], s["closed_pnl_sol"] + 1.0)
        self.assertAlmostEqual(s["pnl_sol"], s["closed_pnl_sol"] + 2.0)


def _call(con, h, tok, ts, max24, measured_ts=None):
    con.execute("INSERT INTO calls (tweet_id, handle, token, ts, kind, max24, r1h, vol_lift, rug, pre2h, followers, "
                "measured_ts, complete) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)",
                (f"{h}-{tok}", h, tok, ts, "call", max24, max24 / 3, 2.0, 0, 0.0, 1000, measured_ts or ts + DAY))
    con.execute("INSERT OR IGNORE INTO kols (handle, followers) VALUES (?, 1000)", (h,))


def _scores(con):
    return {h: (sc, json.loads(st or "{}").get("measured")) for h, sc, st in con.execute("SELECT handle, score, stats FROM kols")}


class Incremental(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.con = kstore.connect(os.path.join(self.tmp, "kol.db"))
        t0 = NOW - 10 * DAY
        for h, xs in (("a", [2.0, 1.0, 0.2, 3.0, 0.5]), ("b", [0.1, 0.0, 0.3, 0.2, -0.5]), ("c", [1.0, 1.5, 0.8, 0.4, 0.2])):
            for i, x in enumerate(xs):
                _call(self.con, h, f"tok-{h}{i}", t0 + i * DAY, x)   # not hex-like: drop_fake_tokens
        self.con.commit()

    def test_partial_run_matches_full_run(self):
        score.run(self.con, CFG, NOW - 3600)
        full = _scores(self.con)
        mark = json.loads(self.con.execute("SELECT value FROM kv WHERE key = 'score_mark'").fetchone()[0])
        self.assertIsNone(mark["partial"])
        # a new call by b on a token a already called: b and a change, c must not be touched
        _call(self.con, "b", "tok-a1", NOW - 3600, 4.0, measured_ts=NOW - 100)
        self.con.execute("UPDATE kols SET stats = json_set(stats, '$.marker', 1) WHERE handle = 'c'")
        self.con.commit()
        touched = score.touched_handles(self.con, mark, NOW)
        self.assertEqual(touched, {"a", "b"})
        score.run(self.con, CFG, NOW)
        part = _scores(self.con)
        mark2 = json.loads(self.con.execute("SELECT value FROM kv WHERE key = 'score_mark'").fetchone()[0])
        self.assertEqual(mark2["partial"], 2)
        self.assertEqual(part["c"], full["c"])
        self.assertIn("marker", self.con.execute("SELECT stats FROM kols WHERE handle = 'c'").fetchone()[0])
        self.assertEqual(part["b"][1], 6)
        # the same database scored from scratch gives the same numbers
        self.con.execute("DELETE FROM kv WHERE key = 'score_mark'")
        self.con.execute("UPDATE kols SET score = NULL, stats = NULL")
        self.con.commit()
        score.run(self.con, CFG, NOW)
        again = _scores(self.con)
        for h in "abc":
            self.assertEqual(again[h], part[h], h)

    def test_full_run_after_four_hours_or_reclassify(self):
        score.run(self.con, CFG, NOW - 5 * 3600)
        mark = json.loads(self.con.execute("SELECT value FROM kv WHERE key = 'score_mark'").fetchone()[0])
        self.assertIsNone(score.touched_handles(self.con, mark, NOW))        # 5 h later: everyone again
        self.assertEqual(score.touched_handles(self.con, mark, NOW - 4 * 3600 - 1), set())   # nothing new: nobody
        self.assertEqual(score.reclassify(self.con), 0)

    def test_narrow_columns_only(self):
        for col in ("text", "url", "symbol", "source"):
            self.assertNotIn(col, score.CALL_COLS.split(", "))


if __name__ == "__main__":
    unittest.main()
