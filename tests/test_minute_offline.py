"""Minutna provjera (kol/minute.py, 9.11., Jure): entry in the minute of the call, +5..+30 % before the -20 % stop
within 60 min, crews measured from their first call, the hot list read every 1-2 s, and the /ekipe page."""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import minute, store  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = json.load(open(os.path.join(ROOT, "kol", "config.json")))
NOW = int(time.time()) // 60 * 60
T0 = NOW - 3 * 3600          # a call at T0 + 20 s, i.e. 20 s into its minute
PAIR = "PAIR1"


def candles(start, mins, price=1.0, moves=None):
    """1-min candles from `start`: flat at `price` unless moves[k] = (open, high, low, close) for minute k."""
    out = []
    for k in range(mins):
        o, h, l, c = (moves or {}).get(k, (price, price, price, price))
        out.append((start + k * 60, o, h, l, c, 100.0))
    return out


class Path(unittest.TestCase):
    def test_entry_is_the_close_of_the_call_minute_and_lag_is_measured(self):
        ts = T0 + 20
        cs = candles(T0 - 600, 70, 1.0, {10: (1.0, 1.02, 0.99, 1.01)})   # minute 10 = the call's minute
        o = minute.path(cs, ts)
        self.assertEqual((o["entry"], o["lag_s"]), (1.01, 40))           # close of 10:32 is 40 s after 10:32:20
        self.assertEqual(o["t5"], None)
        self.assertAlmostEqual(o["r60"], 1.0 / 1.01 - 1, places=6)

    def test_targets_before_the_stop_count_and_after_it_do_not(self):
        ts = T0 + 20
        m = {10: (1.0, 1.0, 1.0, 1.0), 12: (1.0, 1.06, 1.0, 1.05), 15: (1.05, 1.12, 1.04, 1.1),
             20: (1.1, 1.1, 0.75, 0.8), 40: (0.8, 1.4, 0.8, 1.3)}
        o = minute.path(candles(T0 - 600, 75, 1.0, m), ts)
        self.assertEqual((o["t5"], o["t10"], o["sl_min"], o["t30"]), (2, 5, 10, 30))
        self.assertTrue(minute.clean_hit(o, 5) and minute.clean_hit(o, 10))
        self.assertFalse(minute.clean_hit(o, 15))    # +15 % only after the stop at minute 10
        self.assertFalse(minute.clean_hit(o, 30))
        self.assertAlmostEqual(o["hi15"], 0.12)
        self.assertAlmostEqual(o["lo60"], -0.25)

    def test_wick_is_capped_and_no_candle_means_no_outcome(self):
        ts = T0 + 20
        m = {10: (1.0, 1.0, 1.0, 1.0), 11: (1.0, 9.0, 1.0, 1.0)}        # one dust print: high 9× the body
        o = minute.path(candles(T0 - 600, 70, 1.0, m), ts)
        self.assertEqual(o["t30"], 1)                                     # the capped wick (3× body) still clears +30 %
        self.assertAlmostEqual(o["hi15"], 2.0)                            # 3× the body of 1.0 -> +200 %, not +800 %
        self.assertIsNone(minute.path(candles(T0 - 600, 5), ts))         # no candle within 5 min of the call
        # the first candle after the call (within 5 min) opens the trade when the call minute had no trade
        cs = [c for c in candles(T0 - 600, 70, 2.0) if c[0] != T0]
        o = minute.path(cs, ts)
        self.assertEqual((o["entry"], o["lag_s"]), (2.0, 40))


class Run(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.con = store.connect(os.path.join(self.d, "kol.db"))
        c = self.con
        c.execute("INSERT INTO tokens (token, pair, supply) VALUES ('TOK', ?, 1e6)", (PAIR,))
        c.execute("INSERT INTO tokens (token, pair, supply) VALUES ('SMALL', 'PAIR2', 1e4)")
        c.execute("INSERT INTO tokens (token, pair, supply) VALUES ('SOLO', 'PAIR3', 1e6)")
        c.execute("INSERT INTO kols (handle, bot) VALUES ('botty', 1)")
        rows = [("1", "TOK", "ansem", T0 + 20), ("2", "TOK", "tg:alpha", T0 + 300), ("3", "TOK", "botty", T0 + 30),
                ("4", "SOLO", "murad", T0 + 1000), ("5", "SMALL", "ansem", T0 + 2000), ("w1", "TOK", "w:abc", T0),
                ("6", "TOK", "ansem", NOW - 600)]   # younger than min_age_min: not due yet
        c.executemany("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES (?,?,?,?,'call')", rows)
        c.execute("INSERT INTO groups (token, start_ts, end_ts, n_authors, handles, first_handle) VALUES "
                  "('TOK', ?, ?, 2, ?, 'ansem')", (T0 + 20, T0 + 300, json.dumps(["ansem", "tg:alpha"])))
        c.commit()
        self.cfg = minute.config(CFG)

    def test_due_crews_first_without_bots_wallets_or_young_calls(self):
        todo = minute.due(self.con, self.cfg, NOW)
        self.assertEqual(list(todo), ["TOK", "SMALL", "SOLO"])            # 2 callers first, then newest
        self.assertEqual(sorted(h for _, h, _ in todo["TOK"]), ["ansem", "tg:alpha"])

    def test_run_stores_paths_and_stats_and_hot_list(self):
        m = {10: (1.0, 1.0, 1.0, 1.0), 12: (1.0, 1.12, 1.0, 1.1), 15: (1.1, 1.25, 1.0, 1.2), 30: (1.2, 1.2, 0.7, 0.8)}
        data = {PAIR: candles(T0 - 600, 90, 1.0, m), "PAIR2": candles(T0 + 1400, 90, 1.0, m),
                "PAIR3": candles(T0 + 400, 90, 1.0, {})}
        got = []

        def fetch(pool, start, end):
            got.append((pool, start, end))
            return data[pool]
        t, n = minute.run(self.con, CFG, NOW, fetch=fetch)
        self.assertEqual((t, n), (3, 4))
        self.assertEqual(got[0][0], PAIR)
        self.assertLessEqual(got[0][1], T0 + 20 - 600)
        rows = {r[0]: r for r in self.con.execute("SELECT tweet_id, entry, t10, t20, sl_min, first_caller, bad, mcap_e FROM call_path")}
        self.assertEqual(set(rows), {"1", "2", "4", "5"})
        self.assertEqual(rows["1"][1:6], (1.0, 2, 5, 20, 1))              # ansem first: +10 % at min 2, +20 % at 5
        self.assertEqual(rows["2"][5], 0)                                   # tg:alpha echoed 5 min later
        self.assertEqual(rows["5"][6], "mcap")                              # $10k token: kept, not counted
        self.assertIsNone(rows["4"][2])                                     # flat token: no target
        st = dict(minute.handle_stats(self.con, 14, NOW))
        self.assertEqual(st["ansem"]["n"], 1)                               # the small-cap call is not counted
        self.assertEqual((st["ansem"]["hit10"], st["ansem"]["hit30"], st["ansem"]["sl"]), (1.0, 0.0, 0.0))
        self.assertEqual(st["ansem"]["med_t10"], 2)
        self.assertEqual((st["murad"]["hit5"], st["murad"]["sl"]), (0.0, 0.0))
        cs = minute.crew_stats(self.con, 14, NOW, min_n=1)
        self.assertEqual(cs["crews"][0][0], ("ansem", "tg:alpha"))
        self.assertEqual(cs["crews"][0][1]["hit20"], 1.0)                  # measured from ansem's first call
        self.assertEqual(cs["pairs"][0][0], ("ansem", "tg:alpha"))
        cov = minute.coverage(self.con, self.cfg, NOW)
        self.assertEqual((cov["measured"], cov["small"], cov["waiting"]), (3, 1, 0))
        # hot list: ansem has 1 call only -> below hot_min_n; with the threshold lowered he is in
        hot = minute.hot(self.con, dict(CFG, minute=dict(CFG["minute"], hot_min_n=1)), NOW, wallet_db=os.path.join(self.d, "nema.db"))
        self.assertEqual((hot["x"], hot["tg"]), (["ansem"], []))
        self.assertEqual(minute.hot_list(os.path.join(self.d, "kol.db"))["x"], ["ansem"])
        hot = minute.hot(self.con, CFG, NOW, wallet_db=os.path.join(self.d, "nema.db"))
        self.assertEqual(hot["x"], [])
        # a second run has nothing left to fetch
        self.assertEqual(minute.run(self.con, CFG, NOW, fetch=fetch), (0, 0))

    def test_hot_list_feeds_telegram_polling_and_the_x_hook(self):
        self.con.execute("INSERT OR REPLACE INTO kv VALUES ('hot_list', ?)",
                         (json.dumps({"ts": NOW, "x": ["ansem"], "tg": ["alpha"], "wallets": []}),))
        self.con.commit()
        saved = store.DB
        store.DB = os.path.join(self.d, "kol.db")
        try:
            from tg import poll
            self.assertIn("alpha", poll.followed_channels())
        finally:
            store.DB = saved
        from kol import xhook
        self.assertEqual(xhook.handles(self.con, CFG)[0], "ansem")

    def test_ekipe_page_renders(self):
        saved = store.DB
        store.DB = os.path.join(self.d, "kol.db")
        try:
            m = {10: (1.0, 1.0, 1.0, 1.0), 12: (1.0, 1.12, 1.0, 1.1)}
            minute.run(self.con, CFG, NOW, fetch=lambda pool, s, e: candles(s, 90, 1.0, m))
            from ui import ekipe
            title, body = ekipe.page({"dani": "14", "min": "1"}, NOW)
            self.assertIn("minutna provjera", title)
            self.assertIn("ansem", body)
            self.assertIn("Ekipe koje zovu zajedno", body)
            self.assertIn("Vruća lista", body)
            self.assertIn("poziva izmjereno po minutama", body)
        finally:
            store.DB = saved

    def test_prune_keeps_30_days(self):
        from ops import prune
        self.con.execute("INSERT INTO call_path (tweet_id, token, handle, ts, measured_ts) VALUES ('old', 'TOK', 'x', ?, ?)",
                         (NOW - 40 * 86400, NOW))
        self.con.execute("INSERT INTO call_path (tweet_id, token, handle, ts, measured_ts) VALUES ('new', 'TOK', 'x', ?, ?)",
                         (NOW - 2 * 86400, NOW))
        self.con.commit()
        self.con.close()
        os.environ["DATA_PRUNE"] = "on"
        try:
            out = prune.kol(os.path.join(self.d, "kol.db"), NOW)
        finally:
            os.environ.pop("DATA_PRUNE", None)
        self.assertEqual(out.get("minutne"), 1)
        con = sqlite3.connect(os.path.join(self.d, "kol.db"))
        self.assertEqual([r[0] for r in con.execute("SELECT tweet_id FROM call_path")], ["new"])
        con.close()


class Zones(unittest.TestCase):
    def test_telegram_time_without_offset_is_utc(self):
        from tg import reader
        self.assertEqual(reader.iso_ts("2026-11-09T10:32:01+00:00"), 1794220321)
        self.assertEqual(reader.iso_ts("2026-11-09T10:32:01"), 1794220321)          # never the server's local clock
        self.assertEqual(reader.iso_ts("2026-11-09T11:32:01+01:00"), 1794220321)
        from kol import collect
        self.assertEqual(collect.tweet_ts("Mon Nov 09 10:32:01 +0000 2026"), 1794220321)
        self.assertEqual(collect.tweet_ts("2026-11-09T10:32:01.000Z"), 1794220321)


if __name__ == "__main__":
    unittest.main()
