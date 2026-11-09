"""Minutna provjera (kol/minute.py, 9.11., Jure): entry in the minute of the call, +5..+30 % before the -20 % stop
within 60 min, own minute.db filled by its own loop (crews first), crews measured from their first call with members,
followers, who calls first, every shared token and its rug flag, the hot list read every 1-2 s, and the /ekipe page."""
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
        cs = [c for c in candles(T0 - 600, 70, 2.0) if c[0] != T0]
        o = minute.path(cs, ts)
        self.assertEqual((o["entry"], o["lag_s"]), (2.0, 40))


class Run(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kp, self.mp = os.path.join(self.d, "kol.db"), os.path.join(self.d, "minute.db")
        self.kc = store.connect(self.kp)
        c = self.kc
        c.execute("INSERT INTO tokens (token, pair, supply) VALUES ('TOK', ?, 1e6)", (PAIR,))
        c.execute("INSERT INTO tokens (token, pair, supply) VALUES ('SMALL', 'PAIR2', 1e4)")
        c.execute("INSERT INTO tokens (token, pair, supply) VALUES ('SOLO', 'PAIR3', 1e6)")
        c.execute("INSERT INTO kols (handle, bot, followers) VALUES ('botty', 1, 5)")
        c.execute("INSERT INTO kols (handle, bot, followers) VALUES ('ansem', 0, 120000)")
        rows = [("1", "TOK", "ansem", T0 + 20), ("2", "TOK", "tg:alpha", T0 + 300), ("3", "TOK", "botty", T0 + 30),
                ("4", "SOLO", "murad", T0 + 1000), ("5", "SMALL", "ansem", T0 + 2000), ("w1", "TOK", "w:abc", T0),
                ("6", "TOK", "ansem", NOW - 600)]   # younger than min_age_min: not due yet
        c.executemany("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES (?,?,?,?,'call')", rows)
        c.execute("INSERT INTO groups (token, start_ts, end_ts, n_authors, handles, first_handle) VALUES "
                  "('TOK', ?, ?, 2, ?, 'ansem')", (T0 + 20, T0 + 300, json.dumps(["ansem", "tg:alpha"])))
        c.commit()
        self.mc = minute.connect(self.mp)
        self.cfg = minute.config(CFG)
        os.environ["MINUTE_DB"] = self.mp

    def tearDown(self):
        self.kc.close()
        self.mc.close()
        os.environ.pop("MINUTE_DB", None)

    def test_due_crews_first_without_bots_wallets_or_young_calls(self):
        todo = minute.due(self.kc, self.mc, self.cfg, NOW)
        self.assertEqual(list(todo), ["TOK", "SMALL", "SOLO"])            # 2 callers first, then newest
        self.assertEqual(sorted(h for _, h, _ in todo["TOK"]), ["ansem", "tg:alpha"])
        self.assertEqual(minute.waiting(self.kc, self.mc, self.cfg, NOW), 4)

    def _data(self):
        m = {10: (1.0, 1.0, 1.0, 1.0), 12: (1.0, 1.12, 1.0, 1.1), 15: (1.1, 1.25, 1.0, 1.2), 30: (1.2, 1.2, 0.7, 0.8)}
        return {PAIR: candles(T0 - 600, 90, 1.0, m), "PAIR2": candles(T0 + 1400, 90, 1.0, m),
                "PAIR3": candles(T0 + 400, 90, 1.0, {})}

    def test_run_stores_paths_stats_crew_detail_and_hot_list(self):
        data = self._data()
        got = []

        def fetch(pool, start, end):
            got.append((pool, start, end))
            return data[pool]
        t, n, left = minute.run(self.kc, self.mc, CFG, NOW, fetch=fetch)
        self.assertEqual((t, n, left), (3, 4, 0))
        self.assertEqual(got[0][0], PAIR)
        rows = {r[0]: r for r in self.mc.execute("SELECT tweet_id, entry, t10, t20, sl_min, first_caller, bad, mcap_e FROM call_path")}
        self.assertEqual(set(rows), {"1", "2", "4", "5"})
        self.assertEqual(rows["1"][1:6], (1.0, 2, 5, 20, 1))              # ansem first: +10 % at min 2, +20 % at 5
        self.assertEqual(rows["2"][5], 0)                                   # tg:alpha echoed 5 min later
        self.assertEqual(rows["5"][6], "mcap")                              # $10k token: kept, not counted
        self.assertIsNone(rows["4"][2])                                     # flat token: no target
        self.assertEqual(self.kc.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='call_path'").fetchone()[0], 0)   # kol.db untouched
        st = dict(minute.handle_stats(self.mc, 14, NOW))
        self.assertEqual(st["ansem"]["n"], 1)
        self.assertEqual((st["ansem"]["hit10"], st["ansem"]["hit30"], st["ansem"]["sl"], st["ansem"]["rug"]), (1.0, 0.0, 0.0, 0.0))
        self.assertEqual(st["ansem"]["med_t10"], 2)
        cs = minute.crew_stats(self.mc, self.kc, 14, NOW, min_n=1)
        hs, s, nt, pot = cs["crews"][0]
        self.assertEqual((hs, nt), (("ansem", "tg:alpha"), 1))
        self.assertEqual(s["hit20"], 1.0)                                    # measured from ansem's first call
        self.assertEqual(pot, minute.potential(s, 1))
        self.assertEqual(cs["pairs"][0][0], ("ansem", "tg:alpha"))
        d = minute.crew_detail(self.mc, self.kc, ["tg:alpha", "ansem"], 30, NOW, tg_db=os.path.join(self.d, "nema.db"))
        self.assertEqual(d["handles"], ("ansem", "tg:alpha"))
        self.assertEqual(d["followers"], {"ansem": 120000, "tg:alpha": None})
        self.assertEqual(d["first"], {"ansem": 1})
        self.assertEqual(len(d["tokens"]), 1)
        self.assertEqual(d["tokens"][0]["first"], "ansem")
        self.assertFalse(d["tokens"][0]["rug"])
        self.assertEqual(d["stats"]["n"], 1)
        cov = minute.coverage(self.mc, self.kc, self.cfg, NOW)
        self.assertEqual((cov["measured"], cov["small"], cov["waiting"]), (3, 1, 0))
        hot = minute.hot(self.mc, self.kc, dict(CFG, minute=dict(CFG["minute"], hot_min_n=1)), NOW, wallet_db=os.path.join(self.d, "nema.db"))
        self.assertEqual((hot["x"], hot["tg"]), (["ansem"], []))
        self.assertEqual(minute.hot_list(self.mp)["x"], ["ansem"])
        hot = minute.hot(self.mc, self.kc, CFG, NOW, wallet_db=os.path.join(self.d, "nema.db"))
        self.assertEqual(hot["x"], [])
        self.assertEqual(minute.run(self.kc, self.mc, CFG, NOW, fetch=fetch), (0, 0, 0))   # nothing left

    def test_rug_flag_from_the_hour_low(self):
        m = {10: (1.0, 1.0, 1.0, 1.0), 20: (1.0, 1.0, 0.1, 0.15)}
        data = {PAIR: candles(T0 - 600, 90, 1.0, m), "PAIR2": candles(T0 + 1400, 90), "PAIR3": candles(T0 + 400, 90)}
        minute.run(self.kc, self.mc, CFG, NOW, fetch=lambda pool, s, e: data[pool])
        d = minute.crew_detail(self.mc, self.kc, ["ansem", "tg:alpha"], 30, NOW, tg_db=os.path.join(self.d, "nema.db"))
        self.assertTrue(d["tokens"][0]["rug"])
        self.assertEqual(d["rugs"], 1)
        self.assertEqual(minute.crew_stats(self.mc, self.kc, 14, NOW, min_n=1)["crews"][0][1]["rug"], 1.0)

    def test_loop_once_logs_and_respects_the_budget(self):
        saved = store.DB
        store.DB = self.kp
        logs = []
        try:
            minute.loop(CFG, log=lambda *a, **k: logs.append(a[0]), once=True, fetch=lambda pool, s, e: self._data()[pool])
        finally:
            store.DB = saved
        self.assertTrue(logs and logs[0].startswith("minute: 3 tokena, 4 poziva"))
        self.assertIn("još 0 tokena čeka", logs[0])

    def test_hot_list_feeds_telegram_polling_and_the_x_hook(self):
        self.mc.execute("INSERT OR REPLACE INTO kv VALUES ('hot_list', ?)",
                        (json.dumps({"ts": NOW, "x": ["ansem"], "tg": ["alpha"], "wallets": []}),))
        self.mc.commit()
        from tg import poll
        self.assertIn("alpha", poll.followed_channels())
        from kol import xhook
        self.assertEqual(xhook.handles(self.kc, CFG)[0], "ansem")

    def test_ekipe_page_renders_with_crew_cards(self):
        saved = store.DB
        store.DB = self.kp
        try:
            minute.run(self.kc, self.mc, CFG, NOW, fetch=lambda pool, s, e: self._data()[pool])
            from ui import ekipe
            title, body = ekipe.page({"dani": "14", "min": "1"}, NOW)
            self.assertIn("minutna provjera", title)
            self.assertIn("Ekipe s najvećim potencijalom", body)
            self.assertIn("#1 @ansem + alpha", body)
            self.assertIn("Prvi zove", body)
            self.assertIn("120k", body)                      # ansem's followers
            self.assertIn("Zaprati ekipu pravim novcem", body)
            self.assertIn("poziva izmjereno po minutama", body)
            self.assertIn("ek-bars", body)
        finally:
            store.DB = saved

    def test_page_without_data_explains(self):
        saved = store.DB
        store.DB = self.kp
        os.environ["MINUTE_DB"] = os.path.join(self.d, "nema.db")
        try:
            from ui import ekipe
            _, body = ekipe.page({}, NOW)
            self.assertIn("još nije napravila prvi krug", body)
        finally:
            store.DB = saved


class Zones(unittest.TestCase):
    def test_telegram_time_without_offset_is_utc(self):
        from tg import reader
        self.assertEqual(reader.iso_ts("2026-11-09T10:32:01+00:00"), 1794220321)
        self.assertEqual(reader.iso_ts("2026-11-09T10:32:01"), 1794220321)          # never the server's local clock
        self.assertEqual(reader.iso_ts("2026-11-09T11:32:01+01:00"), 1794220321)
        from kol import collect
        self.assertEqual(collect.tweet_ts("Mon Nov 09 10:32:01 +0000 2026"), 1794220321)
        self.assertEqual(collect.tweet_ts("2026-11-09T10:32:01.000Z"), 1794220321)


class RoundOrder(unittest.TestCase):
    def test_minute_is_its_own_process_and_backfill_has_a_budget(self):
        import run_kol
        src = open(run_kol.__file__).read()
        self.assertNotIn("cmd_traces, cmd_minute", src)
        self.assertIn('"minute-loop": cmd_minute_loop', src)
        self.assertIn("keep minute python3 run_kol.py minute-loop", open(os.path.join(ROOT, "start.sh")).read())
        from kol import sessions
        d = tempfile.mkdtemp()
        con = store.connect(os.path.join(d, "kol.db"))
        for i in range(5):
            con.execute("INSERT INTO tokens (token, pair) VALUES (?, ?)", (f"T{i}", f"P{i}"))
            con.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, p0) VALUES (?,?,?,?,'call',1.0)", (f"c{i}", f"T{i}", "h", NOW - 3600))
        con.commit()

        def slow(pair, lo, hi):
            time.sleep(0.05)
            return [(NOW - 3600, 1, 1, 1, 1, 10.0)]
        self.assertEqual(sessions.backfill(con, {"sessions": {"hours_backfill": 15}}, slow, NOW, budget_s=0.01), 1)
        self.assertEqual(sessions.backfill(con, {"sessions": {"hours_backfill": 15}}, slow, NOW, budget_s=60), 4)
        con.close()


if __name__ == "__main__":
    unittest.main()
