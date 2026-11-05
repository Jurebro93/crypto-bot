"""4.11.: the numbers on Pregled > "Koliko podataka alat ima" and the demo bot's "why nothing was bought" line.

    python3 -m unittest tests.test_pregled_counts_offline
"""
import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import store as kstore  # noqa: E402
from ui import pocetna  # noqa: E402

DAY = 86400


class KolCounts(unittest.TestCase):
    def setUp(self):
        self.now = time.time()
        self.path = os.path.join(tempfile.mkdtemp(), "kol.db")
        con = kstore.connect(self.path)
        t = int(self.now) - DAY
        for h in ("alice", "bob", "tg:gemcalls", "w:7xKXtg"):
            con.execute("INSERT INTO kols (handle, first_seen) VALUES (?, ?)", (h, t))
        rows = [("1", "alice", "call"), ("2", "bob", "call"), ("3", "tg:gemcalls", "call"), ("4", "alice", "brag")]
        rows += [(f"b{i}", "w:7xKXtg", "buy") for i in range(20)] + [(f"s{i}", "w:7xKXtg", "sell") for i in range(10)]
        for tid, h, kind in rows:
            con.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES (?, 'T', ?, ?, ?)", (tid, h, t, kind))
        con.commit()
        con.close()

    def test_wallet_swaps_are_not_influencer_calls(self):
        c = pocetna._sql_counts(self.path, "kols", "first_seen", self.now, "handle NOT LIKE 'tg:%' AND handle NOT LIKE 'w:%'")
        self.assertEqual(c, (2, 2, 0))                                   # alice, bob: not the channel, not the wallet
        c = pocetna._sql_counts(self.path, "calls", "ts", self.now, "kind = 'call'")
        self.assertEqual(c, (3, 3, 0))                                   # 3 calls (X and Telegram), not the brag
        c = pocetna._sql_counts(self.path, "calls", "ts", self.now, "kind IN ('buy', 'sell')")
        self.assertEqual(c, (30, 30, 0))
        self.assertEqual(pocetna._sql_counts(self.path, "calls", "ts", self.now)[0], 34)   # what the page showed before

    def test_week_split(self):
        con = sqlite3.connect(self.path)
        con.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES ('old', 'T', 'alice', ?, 'call')",
                    (int(self.now) - 10 * DAY,))
        con.commit()
        con.close()
        self.assertEqual(pocetna._sql_counts(self.path, "calls", "ts", self.now, "kind = 'call'"), (4, 3, 1))


class RowTotals(unittest.TestCase):
    def test_timestamp_keys_are_counted_not_summed(self):
        con = sqlite3.connect(":memory:")
        con.executescript("""CREATE TABLE snapshots (ts INTEGER PRIMARY KEY, data TEXT);
                             CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT, x);
                             CREATE TABLE wallet_trades (wallet TEXT, sig TEXT, PRIMARY KEY (sig, wallet));""")
        con.execute("INSERT INTO snapshots VALUES (1793000000, 'x')")
        con.execute("INSERT INTO trades (x) VALUES (1)")
        con.execute("INSERT INTO wallet_trades VALUES ('w', 's')")
        total = sum(con.execute(f"SELECT {pocetna._count_expr(con, t)} FROM [{t}]").fetchone()[0]
                    for t in ("snapshots", "trades", "wallet_trades"))
        self.assertEqual(total, 3)


class IntakeSummary(unittest.TestCase):
    def test_line(self):
        import run_paper
        cands = {"A": {"decision": "skip_score", "score": 41}, "B": {"decision": "skip_score", "score": 12},
                 "C": {"decision": "skip_liq", "score": 60}, "D": {"score": 70}}
        s = run_paper._intake_summary(cands, {"min_score": 50}, 38.0)
        self.assertEqual(s, "4 kandidata: skip_score 2 (najbolji 41 < 50), skip_liq 1, bez cijene 1; prag 50, istraživanje od 38")
        self.assertIsNone(run_paper._intake_summary({}, {"min_score": 50}, None))
        self.assertIn("istraživanje isključeno", run_paper._intake_summary(cands, {"min_score": 50}, None))


class Reconsider(unittest.TestCase):
    def test_better_score_overturns_liq_and_ignored_but_not_rug_or_taken(self):
        import run_paper
        cfg = {"min_score": 50}
        hi, lo = {"origin": "hype", "score": 60}, {"origin": "hype", "score": 40}
        for d in ("skip_score", "skip_liq", "skip_mcap", "ignored"):
            self.assertTrue(run_paper.reconsider(d, hi, cfg), d)
            self.assertFalse(run_paper.reconsider(d, lo, cfg), d)
        for d in ("taken", "skip_rug", "skip_gate", "skip_full", "skip_ab", "skip_sesija"):
            self.assertFalse(run_paper.reconsider(d, hi, cfg), d)
        self.assertFalse(run_paper.reconsider("skip_liq", {"origin": "event", "score": 90}, cfg))


class CocallOutcome(unittest.TestCase):
    def test_cluster_token_is_judged_from_the_call_that_completed_the_cluster(self):
        from ourtoken import advisor
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE calls (token, handle, ts, views, max24, kind)")
        rows = []
        for i in range(6):   # first call +400% (before the cluster), third caller only +20%: the token is NOT a 2x
            rows += [(f"g{i}", "a", 1000, 0, 4.0, "call"), (f"g{i}", "b", 1060, 0, 2.0, "call"), (f"g{i}", "c", 1120, 0, 0.2, "call")]
        rows += [(f"s{i}", "a", 1000, 0, 3.0 if i < 10 else 0.1, "call") for i in range(30)]   # solo: first call counts
        con.executemany("INSERT INTO calls VALUES (?,?,?,?,?,?)", rows)
        lift = advisor.cocall_lift(con)
        self.assertEqual((lift["group_n"], lift["solo_n"]), (6, 30))
        self.assertAlmostEqual(lift["group_rate"], 0.0)      # was 1.0 when the first call's +400% labelled the token
        self.assertAlmostEqual(lift["solo_rate"], 1 / 3)


class TelegramHistoryPage(unittest.TestCase):
    def test_channel_from_exports_gets_a_summary_not_an_empty_page(self):
        from kol import store as kstore
        from ui import kol as ukol
        path = os.path.join(tempfile.mkdtemp(), "kol.db")
        kstore.connect(path).close()                      # empty database: no kols row for the channel
        old, kstore.DB = kstore.DB, path
        try:
            title, body = ukol.kol_page("tg:x666calls", {})   # in kol/tg_history.json (Call Analyser export)
            self.assertNotIn("Nema poziva od ovog računa", body)
            self.assertIn("Poziva u 6 mj.", body)
            self.assertIn("https://t.me/x666calls", body)
            self.assertIn("Barem 2×", body)
            self.assertIn("Bot još nije skupio nijedan poziv", body)
            self.assertEqual(ukol.kol_page("tg:nema-takvog-kanala-123", {})[1].count("Nema poziva"), 1)
        finally:
            kstore.DB = old


class StrategyTradesTable(unittest.TestCase):
    def test_bought_cell_is_text_not_a_tuple(self):
        import inspect
        from ui import strategije
        src = inspect.getsource(strategije)
        self.assertIn('(ago(p["entry_ts"])[0], p["entry_ts"], "n")', src)
        self.assertNotIn('(ago(p["entry_ts"]), p["entry_ts"], "n")', src)


class WalletRecommendation(unittest.TestCase):
    def _w(self, addr, copy, **st):
        base = {"closed": 20, "closed_pnl_sol": 10.0, "win_rate": 0.6, "median_hold_min": 40, "last_trade_days": 0.5,
                "top_trade_share": 0.3}
        base.update(st)
        return {"wallet": addr, "copy_score": copy, "stats": base, "labels": []}

    def test_three_picks_with_confidence_and_demo_copies(self):
        from ui import preporuka
        ws = [self._w("A" * 44, 61, closed=40),                         # visoka
              self._w("B" * 44, 69, closed=13),                         # niska (13 < 15)
              self._w("C" * 44, 55, closed=18),                         # srednja
              self._w("D" * 44, 66, closed=48, closed_pnl_sol=47.9, win_rate=0.48, top_trade_share=0.7),  # big PnL, visoka? no: top share
              self._w("E" * 44, 70, closed=5),                          # fewer than 10 closed: out
              self._w("F" * 44, 70, closed=30, median_hold_min=4 * 1440),   # holds 4 days: out
              self._w("G" * 44, 70, closed=30, closed_pnl_sol=-2.0)]    # in minus: out
        ranked = preporuka.rank_wallets(ws, {"DDDDDD": (4, 0.12, 31.0)})
        self.assertEqual([w["wallet"][0] for w, _ in ranked], ["A", "D", "C", "B"])
        self.assertEqual([r["tier"] for _, r in ranked], ["visoka", "srednja", "srednja", "niska"])
        html = preporuka.wallets_box(ws, {"DDDDDD": (4, 0.12, 31.0)})
        self.assertIn("pouzdanost visoka", html)
        self.assertIn("Što bih ja napravio:", html)
        self.assertIn("Kopirao bih", html)
        self.assertIn("50 $ po tradeu", html)                      # first pick has high confidence
        self.assertIn("Kad je naš demo bot kupio isto što i on (4×", html)
        self.assertNotIn("EEEEEE", html)
        self.assertIn("(4 prolazi uvjete)", html)
        self.assertNotIn("ne obećanje", html)                      # no roi_on_cost in the fixture: no projection
        html2 = preporuka.wallets_box([self._w("A" * 44, 61, closed=40, roi_on_cost=0.35)])
        self.assertIn("+350 $", html2)

    def test_nobody_yet(self):
        from ui import preporuka
        html = preporuka.wallets_box([self._w("A" * 44, 30)])
        self.assertIn("Ne bih kopirao nikoga", html)

    def test_demo_copies_in_minus_overrule_the_history(self):
        from ui import preporuka
        html = preporuka.wallets_box([self._w("A" * 44, 61, closed=40)], {"AAAAAA": (5, -0.08, -20.0)})
        self.assertIn("Ne bih kopirao ni", html)
        self.assertIn("-8% po tradeu", html)


class StopLossGridText(unittest.TestCase):
    def test_count_is_text_and_equal_delay_columns_are_explained(self):
        from ui import exitspage
        rows = [{"sl": -0.1, "delay": 0, "mean": 0.375, "median": 0, "win": 0.5, "score": 1},
                {"sl": -0.1, "delay": 15, "mean": 0.348, "median": 0, "win": 0.5, "score": 0.9},
                {"sl": None, "delay": 0, "mean": 0.348, "median": 0, "win": 0.5, "score": 0.9}]
        html = exitspage.sl_html({"sl_grid": {"ts": time.time(), "sve": {"n": 1409, "rows": rows}}})
        self.assertIn("1,409 prilika", html)
        self.assertNotIn("('1,409'", html)
        self.assertIn("nakon 15 min” jednaki su retku „bez stop lossa”", html)


if __name__ == "__main__":
    unittest.main()
