"""TP/SL iz podataka (kol/tpsl.py, 9.11.2026, Jure: "TP 20 / SL -40? koliko pogodaka treba? neka alat dinamički
odluči kad može biti profitabilno"): the break-even arithmetic, the first-touch minutes kol/minute.py stores for every
level, the outcome of one call under any pair (cautious on rows measured before the levels existed), the choice of a
pair per source (pulled toward no edge, proven on the older AND the newer calls), the copy follow that uses it
(exit "podaci": skip when nothing pays, TP/SL from the data, closed after the measured hour), and the page.

    python3 -m unittest tests.test_tpsl_offline
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import minute, store as kstore, tpsl  # noqa: E402
from league import auto, copy, store  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = json.load(open(os.path.join(ROOT, "kol", "config.json")))
NOW = int(time.time()) // 60 * 60
T0 = NOW - 3 * 3600
A = "A" * 43

WIN = {"u": {"10": 2, "15": 3, "20": 5, "30": 8}, "d": {}}                      # +30 % at minute 8, never down 10 %
LOSS = {"u": {}, "d": {"10": 1, "15": 1, "20": 2, "25": 2, "30": 2, "40": 3}}    # straight down


def row(i, lv=None, handle="kol", token=None, ts=None, r60=0.0, **legacy):
    """One measured call as kol/tpsl.rows returns it (lv None = a row from before the levels were stored)."""
    d = {"tweet_id": str(i), "token": token or f"T{i}", "handle": handle, "ts": ts if ts is not None else T0 + i * 60,
         "hi60": None, "lo60": None, "r60": r60, "t5": None, "t10": None, "t15": None, "t20": None, "t30": None,
         "sl_min": None, "lv": json.dumps(lv) if lv is not None else None}
    d.update(legacy)
    return d


def candles(start, mins, price=1.0, moves=None):
    out = []
    for k in range(mins):
        o, h, l, c = (moves or {}).get(k, (price, price, price, price))
        out.append((start + k * 60, o, h, l, c, 100.0))
    return out


def put(mc, i, handle, lv, token=None, ts=None, r60=0.0, **legacy):
    """Insert one measured call into minute.db (call_path by name; call_lv only when lv is given)."""
    r = row(i, lv, handle, token, ts, r60, **legacy)
    mc.execute("INSERT INTO call_path (tweet_id, token, handle, ts, entry, lag_s, hi60, lo60, r60, t5, t10, t15, t20, t30, "
               "sl_min, first_caller, measured_ts) VALUES (?,?,?,?,1.0,10,?,?,?,?,?,?,?,?,?,1,?)",
               (r["tweet_id"], r["token"], handle, r["ts"], r["hi60"], r["lo60"], r["r60"], r["t5"], r["t10"], r["t15"],
                r["t20"], r["t30"], r["sl_min"], NOW))
    if lv is not None:
        mc.execute("INSERT INTO call_lv VALUES (?,?,?,?)", (r["tweet_id"], r["token"], r["ts"], json.dumps(lv)))


class Arithmetic(unittest.TestCase):
    def test_a_wider_stop_needs_more_hits_not_fewer(self):
        self.assertAlmostEqual(tpsl.breakeven(15, 20, 0), 20 / 35)          # 57 %
        self.assertAlmostEqual(tpsl.breakeven(20, 40, 0), 2 / 3)            # 67 %: Jure's pair needs MORE than 15/20
        self.assertAlmostEqual(tpsl.breakeven(15, 20), 22 / 35)             # 63 % with the demo's 2 % round trip
        self.assertAlmostEqual(tpsl.breakeven(20, 40), 0.70)
        self.assertAlmostEqual(tpsl.breakeven(30, 15), 17 / 45)             # a target above the stop needs under 40 %
        self.assertGreater(tpsl.breakeven(20, 40), tpsl.breakeven(20, 20))
        from league import store as lstore
        self.assertEqual(tpsl.COST, lstore.FEE * 2 * 100)                   # the cost is the demo's fee, both sides


class Levels(unittest.TestCase):
    def test_path_stores_the_first_minute_of_every_level(self):
        m = {13: (1.0, 1.12, 1.0, 1.05), 15: (1.0, 1.0, 0.88, 0.95), 19: (0.95, 0.95, 0.55, 0.6)}
        o = minute.path(candles(T0 - 600, 75, 1.0, m), T0 + 20)
        self.assertEqual(o["lv"]["u"], {"5": 3, "10": 3})                    # +12 % high in minute 3
        self.assertEqual(o["lv"]["d"], {"10": 5, "15": 9, "20": 9, "25": 9, "30": 9, "40": 9})   # -45 % low in minute 9
        self.assertEqual((o["t10"], o["sl_min"]), (3, 9))                    # the old columns say the same
        self.assertNotIn("50", o["lv"]["d"])

    def test_outcome_with_levels_is_exact(self):
        r = row(1, {"u": {"10": 3, "20": 12}, "d": {"10": 5, "20": 9}}, r60=0.02)
        self.assertEqual(tpsl.outcome(r, 10, 10), ("tp", 10.0))             # +10 % in minute 3, -10 % in minute 5
        self.assertEqual(tpsl.outcome(r, 20, 10), ("sl", -10.0))            # +20 % only in minute 12
        self.assertEqual(tpsl.outcome(r, 20, 30), ("tp", 20.0))             # -30 % never came
        self.assertEqual(tpsl.outcome(r, 30, 40), ("time", 2.0))            # neither: out at the close of minute 60
        tie = row(2, {"u": {"10": 4}, "d": {"10": 4}})
        self.assertEqual(tpsl.outcome(tie, 10, 10), ("sl", -10.0))          # the same minute: the stop (order unknown)

    def test_old_rows_are_exact_for_minus_20_and_cautious_elsewhere(self):
        r = row(1, None, t5=2, t10=3, t15=8, t20=12, sl_min=9, lo60=-0.45, hi60=0.25, r60=-0.30)
        self.assertEqual(tpsl.outcome(r, 10, 20), ("tp", 10.0))             # exact: +10 % minute 3, -20 % minute 9
        self.assertEqual(tpsl.outcome(r, 20, 20), ("sl", -20.0))
        self.assertEqual(tpsl.outcome(r, 10, 40), ("tp", 10.0))             # -40 % cannot come before -20 % (minute 9)
        self.assertEqual(tpsl.outcome(r, 20, 40), ("sl", -40.0))            # +20 % after minute 9: not provable, a loss
        self.assertEqual(tpsl.outcome(r, 10, 10), ("sl", -10.0))            # -10 % touched at an unknown minute: a loss
        self.assertEqual(tpsl.outcome(r, 50, 20), ("sl", -20.0))            # +50 % has no minute in an old row: no win
        calm = row(2, None, t10=4, lo60=-0.05, hi60=0.6, r60=0.4)
        self.assertEqual(tpsl.outcome(calm, 10, 10), ("tp", 10.0))          # the low never reached -10 %: exact
        self.assertEqual(tpsl.outcome(calm, 50, 10), ("time", 40.0))        # +50 % unknown minute: only the close counts
        failed = row(3, None, t10=4, lo60=-0.05)
        failed["lv"] = minute.LV_FAILED                                      # second measurement failed: still an old row
        self.assertEqual(tpsl.outcome(failed, 10, 10), ("tp", 10.0))

    def test_grid_is_the_mean_after_cost(self):
        rows = [row(1, WIN), row(2, WIN), row(3, LOSS), row(4, {"u": {}, "d": {}}, r60=0.05)]
        g = tpsl.grid(rows)[(20, 20)]
        self.assertEqual((g["n"], g["tp"], g["sl"], g["time"]), (4, 0.5, 0.25, 0.25))
        self.assertAlmostEqual(g["ev"], (20 + 20 - 20 + 5) / 4 - tpsl.COST)


class Decide(unittest.TestCase):
    def _rows(self, pattern):
        return [row(i, WIN if ch == "W" else LOSS, r60=0.25 if ch == "W" else -0.5) for i, ch in enumerate(pattern)]

    def test_too_few_calls_is_no_decision(self):
        d = tpsl.decide(self._rows("WWWWW"))
        self.assertIsNone(d["ok"])
        self.assertIn("premalo izmjerenih poziva (5 od 10)", d["why"])

    def test_a_real_edge_is_taken_with_its_pair(self):
        d = tpsl.decide(self._rows("WWWLWWWWLWWWWLW"))                       # 12 of 15 reach +30 %, losers go straight down
        self.assertTrue(d["ok"])
        self.assertEqual((d["tp"], d["sl"], d["n"], d["n_new"]), (30, 10, 15, 5))   # the tight stop loses least on the losers
        self.assertAlmostEqual(d["win"], 0.8)
        self.assertAlmostEqual(d["need"], 0.30)
        self.assertAlmostEqual(d["ev_raw"], (12 * 30 - 3 * 10) / 15 - 2)    # +20 % a trade before the caution
        self.assertAlmostEqual(d["ev"], (20 * 15 + (-2) * 10) / 25)         # pulled toward "no edge" by 10 pseudo-calls
        self.assertIn("izlaz po podacima TP +30 % / SL −10 %", d["why"])
        self.assertIn("cilj prije stopa 80% (treba 30%)", d["why"])

    def test_an_edge_only_in_the_past_is_not_taken(self):
        d = tpsl.decide(self._rows("WWWWWWWWWWLLLLL"))                       # the newer third is all losers
        self.assertFalse(d["ok"])
        self.assertLess(d["ev_new"], 0)
        self.assertGreater(d["ev"], tpsl.MIN_EV)                             # the whole sample still looks fine: not enough
        self.assertIn("na novijih 5 poziva gubi", d["why"])

    def test_a_plus_that_could_be_luck_is_not_taken(self):
        # 7 of 12 calls reach +50 %, 5 go straight down: the mean is well in the plus on the older AND the newer
        # calls, but with a spread like this 12 calls cannot tell an edge from luck (the low end is under zero)
        big = {"u": {"10": 2, "15": 3, "20": 5, "30": 8, "50": 20}, "d": {}}
        rows = [row(i, big if ch == "W" else LOSS, r60=0.5 if ch == "W" else -0.5) for i, ch in enumerate("WLWLWWLWLWLW")]
        d = tpsl.decide(rows, z=3.5)
        self.assertFalse(d["ok"])
        self.assertGreater(d["ev"], tpsl.MIN_EV)
        self.assertGreater(d["ev_new"], 0)
        self.assertLessEqual(d["lo"], 0)
        self.assertTrue(d["why"].startswith("po podacima još nije dokazano"))
        self.assertIn("donja granica", d["why"])
        self.assertTrue(tpsl.decide(rows, z=0.5)["ok"])                      # the same calls pass a loose bound

    def test_ten_lucky_calls_do_not_pass(self):
        win10 = {"u": {"10": 2}, "d": {}}
        rows = [row(i, win10 if ch == "W" else LOSS) for i, ch in enumerate("WLWWLWLWWL")]   # 6 x +10 %, 4 x -10 %
        d = tpsl.decide(rows)
        self.assertFalse(d["ok"])
        self.assertEqual((d["tp"], d["sl"]), (10, 10))
        self.assertAlmostEqual(d["ev_raw"], 0.0)                             # +2 % gross, 2 % cost
        self.assertAlmostEqual(d["ev"], -1.0)                                # and pulled toward -2 %
        self.assertTrue(d["why"].startswith("po podacima se ne isplati"))

    def test_everybodys_result_lowers_the_start_but_never_lifts_it(self):
        rows = self._rows("WWWLWWWWLWWWWLW")
        everybody = lambda ev: {f"{tp}/{sl}": {"n": 5000, "ev": ev} for tp in tpsl.TPS for sl in tpsl.SLS}   # noqa: E731
        low = tpsl.decide(rows, pool=everybody(-8.0))
        self.assertEqual((low["tp"], low["sl"]), (30, 10))
        self.assertAlmostEqual(low["ev"], (20 * 15 + (-8) * 10) / 25)       # the crowd loses 8 % a trade: a lower start
        high = tpsl.decide(rows, pool=everybody(6.0))
        self.assertAlmostEqual(high["ev"], (20 * 15 + 0 * 10) / 25)         # the crowd's plus counts as zero at most
        none = tpsl.decide(rows, pool={"30/10": {"n": 0, "ev": -50.0}})     # an empty pool entry says nothing
        self.assertAlmostEqual(none["ev"], (20 * 15 + (-2) * 10) / 25)


class Reading(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.mp = os.path.join(self.d, "minute.db")
        self.mc = minute.connect(self.mp)

    def tearDown(self):
        self.mc.close()

    def test_rows_are_one_per_account_and_token_any_case_and_work_without_the_levels_table(self):
        put(self.mc, 1, "GoodKol", WIN, token="T1", ts=T0)
        put(self.mc, 2, "GoodKol", LOSS, token="T1", ts=T0 + 600)            # the same token again: not a second call
        put(self.mc, 3, "GoodKol", None, token="T2", ts=T0 + 60, t10=4, lo60=-0.05)
        put(self.mc, 4, "other", WIN, token="T3", ts=T0)
        self.mc.execute("INSERT INTO call_path (tweet_id, token, handle, ts, bad) VALUES ('5', 'T9', 'GoodKol', ?, 'svijeca')", (T0,))
        self.mc.commit()
        got = tpsl.rows(self.mc, ["goodkol"], now=NOW)
        self.assertEqual([(r["tweet_id"], r["lv"] is not None) for r in got], [("1", True), ("3", False)])
        self.assertEqual(len(tpsl.rows(self.mc, None, now=NOW)), 3)
        self.assertEqual(tpsl.rows(self.mc, [], now=NOW), [])
        self.mc.execute("DROP TABLE call_lv")                                # a minute.db its writer has not migrated yet
        got = tpsl.rows(self.mc, ["goodkol"], now=NOW)
        self.assertEqual([r["lv"] for r in got], [None, None])

    def test_crew_is_judged_on_the_call_it_enters_on(self):
        rws = [row(1, WIN, "a", "T1", 100), row(2, LOSS, "b", "T1", 200), row(3, WIN, "a", "T2", 100),
               row(4, WIN, "b", "T2", 5000), row(5, WIN, "a", "T3", 300), row(6, WIN, "a", "T1", 150)]
        self.assertEqual([r["tweet_id"] for r in tpsl.crew_rows(rws, 1)], ["1", "3", "5"])    # the first caller of each
        self.assertEqual([r["tweet_id"] for r in tpsl.crew_rows(rws, 2)], ["2"])              # the 2nd member, in the window

    def test_pool_is_saved_for_the_pages_and_for_handles_reads_it(self):
        for i, ch in enumerate("WWWLWWWWLWWWWLW"):
            put(self.mc, i, "goodkol", WIN if ch == "W" else LOSS, r60=0.25 if ch == "W" else -0.5)
        self.mc.commit()
        p = tpsl.save_pool(self.mc, now=NOW)
        self.assertEqual(p["n"], 15)
        self.assertAlmostEqual(p["pairs"]["20/40"]["need"], 0.70)
        self.assertEqual(tpsl.load_pool(self.mc)["pairs"]["30/10"]["n"], 15)
        d = tpsl.for_handles(["GOODKOL"], now=NOW, path=self.mp)
        self.assertTrue(d["ok"])
        self.assertEqual((d["tp"], d["sl"]), (30, 10))
        self.assertIsNone(tpsl.for_handles(["goodkol"], now=NOW, path=os.path.join(self.d, "nema.db")))
        self.assertIsNone(tpsl.for_handles([], now=NOW, path=self.mp))


class MinuteLoopStoresLevels(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kp, self.mp = os.path.join(self.d, "kol.db"), os.path.join(self.d, "minute.db")
        self.kc = kstore.connect(self.kp)
        self.kc.execute("INSERT INTO tokens (token, pair, supply) VALUES ('TOK', 'PAIR1', 1e6)")
        self.kc.execute("INSERT INTO tokens (token, pair, supply) VALUES ('OLD', 'PAIR2', 1e6)")
        self.kc.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES ('1', 'TOK', 'ansem', ?, 'call')", (T0 + 20,))
        self.kc.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES ('9', 'OLD', 'ansem', ?, 'call')", (T0 - 3600 + 20,))
        self.kc.commit()
        self.mc = minute.connect(self.mp)
        # 'OLD' was measured before the levels existed: a path row, no call_lv row
        put(self.mc, 9, "ansem", None, token="OLD", ts=T0 - 3600 + 20, t10=2, sl_min=30, lo60=-0.3, hi60=0.25, r60=-0.2)
        self.mc.commit()
        m = {12: (1.0, 1.12, 1.0, 1.1), 15: (1.1, 1.25, 1.0, 1.2), 30: (1.2, 1.2, 0.7, 0.8)}
        self.data = {"PAIR1": candles(T0 - 600, 90, 1.0, m), "PAIR2": candles(T0 - 3600 - 600, 90, 1.0, m)}

    def tearDown(self):
        self.kc.close()
        self.mc.close()

    def test_new_calls_get_levels_and_old_rows_are_measured_again_when_the_queue_is_short(self):
        got = []

        def fetch(pool, start, end):
            got.append(pool)
            return self.data[pool]
        t, n, left = minute.run(self.kc, self.mc, CFG, NOW, fetch=fetch)
        self.assertEqual(got, ["PAIR1", "PAIR2"])                             # the new call first, the old row after it
        self.assertEqual((t, n, left), (2, 2, 0))
        lv = {r[0]: json.loads(r[1]) for r in self.mc.execute("SELECT tweet_id, lv FROM call_lv")}
        self.assertEqual(lv["1"]["u"], {"5": 2, "10": 2, "15": 5, "20": 5})
        self.assertEqual(lv["1"]["d"], {"10": 20, "15": 20, "20": 20, "25": 20, "30": 20})
        self.assertEqual(lv["9"]["d"]["30"], 20)                              # the old row now has every stop's minute
        r = tpsl.rows(self.mc, ["ansem"], now=NOW)
        self.assertEqual([x["lv"] is not None for x in r], [True, True])
        self.assertEqual(tpsl.outcome(r[0], 10, 30), ("tp", 10.0))
        got.clear()
        self.assertEqual(minute.run(self.kc, self.mc, CFG, NOW, fetch=fetch), (0, 0, 0))   # nothing left to do
        self.assertEqual(got, [])

    def test_a_busy_queue_leaves_the_old_rows_for_later(self):
        cfg = dict(CFG, minute=dict(CFG.get("minute") or {}, relevel_per_run=1))
        got = []

        def fetch(pool, start, end):
            got.append(pool)
            return self.data[pool]
        minute.run(self.kc, self.mc, cfg, NOW, fetch=fetch)                   # one new token = the queue is "full"
        self.assertEqual(got, ["PAIR1"])
        self.assertEqual(self.mc.execute("SELECT COUNT(*) FROM call_lv WHERE tweet_id = '9'").fetchone()[0], 0)

    def test_an_old_row_whose_candles_are_gone_keeps_its_path(self):
        self.data["PAIR2"] = []                                               # GeckoTerminal has no candle there any more
        minute.run(self.kc, self.mc, CFG, NOW, fetch=lambda pool, s, e: self.data[pool])
        self.assertEqual(self.mc.execute("SELECT lv FROM call_lv WHERE tweet_id = '9'").fetchone()[0], minute.LV_FAILED)
        self.assertEqual(self.mc.execute("SELECT t10, bad FROM call_path WHERE tweet_id = '9'").fetchone(), (2, None))
        got = []
        minute.run(self.kc, self.mc, CFG, NOW, fetch=lambda pool, s, e: got.append(pool) or self.data[pool])
        self.assertEqual(got, [])                                             # not asked again


class TimeLimit(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self._db = store.DB
        store.DB = os.path.join(d, "league.db")
        self.con = store.connect()
        self.tid = store.buy(self.con, "Ivan", A, "AAA", 25, 1.0, 50000, "copy KOL x", None, 1e6)

    def tearDown(self):
        self.con.close()
        store.DB = self._db

    def test_a_data_exit_is_closed_at_the_end_of_the_measured_hour(self):
        opened = self.con.execute("SELECT opened_ts FROM trades WHERE id=?", (self.tid,)).fetchone()[0]
        a = auto.set_auto(self.con, "Ivan", self.tid, "tpsl", "20%", "-15%", from_eff=True, hold_s=3600)
        self.assertEqual(a["until"], opened + 3600)
        self.assertIn("najdulje do ", auto.describe(json.dumps(a)))
        flat = lambda toks: {A: (1.0, 50000, None, 1e6)}                      # noqa: E731 - neither level touched
        self.assertEqual(auto.run_once(self.con, flat, opened + 3599), [])
        done = auto.run_once(self.con, flat, opened + 3600)
        self.assertEqual(len(done), 1)
        self.assertIn("vrijeme", done[0][2])
        t = self.con.execute("SELECT status, note FROM trades WHERE id=?", (self.tid,)).fetchone()
        self.assertEqual(t[0], "closed")
        self.assertIn("auto vrijeme", t[1])

    def test_levels_still_come_first_and_plain_tpsl_has_no_limit(self):
        a = auto.set_auto(self.con, "Ivan", self.tid, "tpsl", "20%", "-15%", from_eff=True)
        self.assertNotIn("until", a)
        self.assertNotIn("najdulje", auto.describe(json.dumps(a)))
        self.assertEqual(auto.run_once(self.con, lambda toks: {A: (1.0, 50000, None, 1e6)}, time.time() + 10 * 86400), [])
        auto.set_auto(self.con, "Ivan", self.tid, "tpsl", "20%", "-15%", from_eff=True, hold_s=3600)
        done = auto.run_once(self.con, lambda toks: {A: (1.5, 50000, None, 1.5e6)}, time.time() + 10 * 86400)
        self.assertIn("TP +20%", done[0][2])                                  # the target is said, not "vrijeme"


class CopyWithDataExit(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self._saved = (store.DB, {k: os.environ.get(k) for k in ("KOL_DB", "HYPE_DB", "TG_DB", "MINUTE_DB")})
        store.DB = os.path.join(d, "league.db")
        self.paths = {"kol": os.path.join(d, "kol.db"), "hype": os.path.join(d, "hype.db"), "tg": os.path.join(d, "tg.db")}
        self.mp = os.path.join(d, "minute.db")
        os.environ.update(KOL_DB=self.paths["kol"], HYPE_DB=self.paths["hype"], TG_DB=self.paths["tg"], MINUTE_DB=self.mp)
        k = sqlite3.connect(self.paths["kol"])
        k.executescript("""CREATE TABLE calls (token TEXT, handle TEXT, ts INTEGER, kind TEXT);
            CREATE TABLE kols (handle TEXT, followers INTEGER, score REAL, stats TEXT, bot INTEGER DEFAULT 0);
            CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT);""")
        k.commit()
        self.k = k
        h = sqlite3.connect(self.paths["hype"])
        h.executescript("""CREATE TABLE chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER, sol REAL);
            CREATE TABLE kol_mentions (handle TEXT, ca TEXT, ts INTEGER);""")
        h.commit()
        self.h = h
        self.mc = minute.connect(self.mp)
        self.con = store.connect()
        self.now = int(time.time())

    def tearDown(self):
        for c in (self.k, self.h, self.mc, self.con):
            c.close()
        store.DB = self._saved[0]
        for k, v in self._saved[1].items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def market(self, toks):
        return {t: (1.0, 50000, None, 1e6, "AAA") for t in toks}

    def _history(self, pattern, handle="goodkol"):
        for i, ch in enumerate(pattern):
            put(self.mc, i, handle, WIN if ch == "W" else LOSS, ts=self.now - 86400 + i * 600,
                r60=0.25 if ch == "W" else -0.5)
        self.mc.commit()

    def _call(self):
        fid = copy.follow(self.con, "Ivan", "kol", "goodkol", "@goodkol", 25, 10, "podaci")
        self.con.execute("UPDATE follows SET created=?", (self.now - 3600,))
        self.con.commit()
        self.k.execute("INSERT INTO calls VALUES (?, 'goodkol', ?, 'call')", (A, self.now - 20))
        self.k.commit()
        return fid

    def test_a_proven_account_is_entered_with_the_pair_from_its_calls(self):
        self._history("WWWLWWWWLWWWWLW")
        self._call()
        done = copy.run_once(self.con, self.market, self.now, self.paths)
        self.assertEqual(len(done), 1)
        t = store.trades(self.con, "Ivan", "open")[0]
        a = json.loads(t["auto"])
        self.assertEqual((a["mode"], a["tp"], a["sl"], a["from_eff"]), ("tpsl", "+30%", "-10%", True))
        self.assertEqual(a["until"], t["opened_ts"] + tpsl.HOLD_MIN * 60)
        note = copy.log(self.con)[0]["note"]
        self.assertIn("izlaz po podacima TP +30 % / SL −10 %", note)

    def test_an_account_whose_calls_do_not_pay_is_not_entered(self):
        self._history("WLLWLLLWLLLL")
        self._call()
        self.assertEqual(copy.run_once(self.con, self.market, self.now, self.paths), [])
        self.assertEqual(store.trades(self.con, "Ivan", "open"), [])
        r = copy.log(self.con)[0]
        self.assertEqual(r["action"], "preskočeno")
        self.assertTrue(r["note"].startswith("po podacima se ne isplati"))
        s = copy.follow_log_summary(self.con, self.now - 86400)
        self.assertEqual(sum(v["preskočeno"] for v in s.values()), 1)         # shows up in "Zadnjih 24 h"

    def test_too_few_measured_calls_keeps_the_default_pair(self):
        self._history("WWW")
        self._call()
        self.assertEqual(len(copy.run_once(self.con, self.market, self.now, self.paths)), 1)
        a = json.loads(store.trades(self.con, "Ivan", "open")[0]["auto"])
        self.assertEqual((a["tp"], a["sl"]), ("+15%", "-20%"))
        self.assertNotIn("until", a)
        self.assertIn("premalo izmjerenih poziva (3 od 10)", copy.log(self.con)[0]["note"])

    def test_a_crew_is_judged_on_its_members_calls_and_wallets_cannot_use_it(self):
        for i, ch in enumerate("WWWLWWWWLWWWWLW"):
            put(self.mc, i, "tg:alpha" if i % 2 else "goodkol", WIN if ch == "W" else LOSS,
                ts=self.now - 86400 + i * 600, r60=0.25 if ch == "W" else -0.5)
        self.mc.commit()
        fid = copy.follow(self.con, "Ivan", "ekipa", "goodkol, tg:alpha", "", 25, 10, "podaci")
        f = next(x for x in copy.follows(self.con, "Ivan") if x["id"] == fid)
        d = copy.data_exit(f, self.now)
        self.assertTrue(d["ok"])
        self.assertEqual(d["n"], 15)
        self.assertIn("po podacima", copy.describe_exit(f["exit"]))
        with self.assertRaises(ValueError) as e:
            copy.follow(self.con, "Ivan", "wallet", "W" * 44, "", 25, 10, "podaci")
        self.assertIn("izlaz po podacima postoji za influencere i ekipe", str(e.exception))


class Page(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self._saved = (store.DB, os.environ.get("MINUTE_DB"))
        store.DB = os.path.join(d, "league.db")
        self.mp = os.path.join(d, "minute.db")
        os.environ["MINUTE_DB"] = self.mp
        self.mc = minute.connect(self.mp)
        self.con = store.connect()
        from ui import pravitrade
        self.pt = pravitrade
        self.pt._DATA_EXIT.clear()

    def tearDown(self):
        self.mc.close()
        self.con.close()
        store.DB = self._saved[0]
        if self._saved[1] is None:
            os.environ.pop("MINUTE_DB", None)
        else:
            os.environ["MINUTE_DB"] = self._saved[1]
        self.pt._DATA_EXIT.clear()

    def _follow(self, mode, target="goodkol"):
        fid = copy.follow(self.con, "Ivan", "kol", target, "", 25, 10, mode, "15%" if mode == "tpsl" else "", "")
        return next(x for x in copy.follows(self.con, "Ivan") if x["id"] == fid)

    def test_the_follow_line_says_what_the_data_says(self):
        for i, ch in enumerate("WWWLWWWWLWWWWLW"):
            put(self.mc, i, "goodkol", WIN if ch == "W" else LOSS, r60=0.25 if ch == "W" else -0.5)
        for i, ch in enumerate("WLLWLLLWLLLL"):
            put(self.mc, 100 + i, "badkol", WIN if ch == "W" else LOSS, r60=0.25 if ch == "W" else -0.5)
        put(self.mc, 200, "newkol", WIN)
        self.mc.commit()
        good = self.pt._data_exit_line(self._follow("podaci"), NOW)
        self.assertIn("Po podacima alat bi uzeo TP +30 % / SL −10 %", good)
        self.assertIn("na novijih 5 poziva", good)
        bad = self.pt._data_exit_line(self._follow("podaci", "badkol"), NOW)
        self.assertIn("Po podacima se ne isplati", bad)
        self.assertIn("Bot zato sada NE ulazi", bad)
        own = self.pt._data_exit_line(self._follow("tpsl", "badkol2"), NOW)      # no calls measured at all
        self.assertIn("premalo izmjerenih poziva (0 od 10)", own)
        new = self.pt._data_exit_line(self._follow("podaci", "newkol"), NOW)
        self.assertIn("Do tada vrijedi zadani izlaz TP +15 % / SL -20 %", new)
        wallet = {"id": 99, "kind": "wallet", "target": "W" * 44, "exit": {"mode": "mirror"}}
        self.assertEqual(self.pt._data_exit_line(wallet, NOW), "")

    def test_the_pool_table_answers_which_pair_pays(self):
        self.assertEqual(self.pt._pool_line(), "")                               # nothing measured yet: no box
        for i, ch in enumerate("WWWLWWWWLWWWWLW"):
            put(self.mc, i, "goodkol", WIN if ch == "W" else LOSS, r60=0.25 if ch == "W" else -0.5)
        self.mc.commit()
        tpsl.save_pool(self.mc, now=NOW)
        html = self.pt._pool_line()
        self.assertIn("Koji TP/SL se isplati", html)
        self.assertIn("TP +20 % / SL −40 %", html)                               # the pair Jure asked about
        self.assertIn("<td class=n>70%</td>", html)                              # ... needs 70 % for zero
        self.assertIn("(najbolji)", html)
        self.assertIn("Širi stop traži VIŠE pogodaka", html)

    def test_the_form_offers_the_data_exit(self):
        import inspect
        src = inspect.getsource(self.pt._follows)
        self.assertIn("<option value=podaci>po podacima (alat bira TP/SL)</option>", src)


if __name__ == "__main__":
    unittest.main()
