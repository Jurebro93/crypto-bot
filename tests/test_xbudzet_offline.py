"""27.11.2026. (vlasnik): the X budget (usage/xbudzet.py) and the end of the 5-day social window (ops/drustveni).

  - caps: 5 $ a UTC day and 100 $ a calendar month, both hard; the month cap wins; env may only lower them
  - priority split 50 / 30 / 20 (pozivi, otkrivanje, ostatak) and the same-day rollover downwards
  - kol/twapi stops before a request that does not fit (search pages, tweets / user_info raise Cap) and books after
  - hype/apify X sources blocked at the cap (kol_monitor only booked: its stop must work)
  - the daily line: spend per category, calls captured, new influencers found
  - the 5-day window no longer blocks any gate (skip_cmd, gate, gate_main, the start line, the notice)
  - kol/novcanici_x: calls on the tokens our watched wallets buy, candidates who called right after the buy
"""
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from usage import xbudzet as xb  # noqa: E402

D = 86400
MA, MB = "So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
T0 = 1_795_737_600 + 12 * 3600   # 27.11.2026. 12:00 UTC (midday: half of the day elapsed)


class Ledger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = os.path.join(self.tmp.name, "usage.db")
        env = mock.patch.dict(os.environ, {"XBUDZET_DB": self.db})
        env.start()
        self.addCleanup(env.stop)
        for k in ("X_DAY_USD", "X_MONTH_USD"):
            os.environ.pop(k, None)


class Arithmetic(unittest.TestCase):
    def test_split_at_the_start_of_the_day(self):
        a = xb.allowance({}, 5.0, 0.0)
        self.assertAlmostEqual(a["pozivi"]["left"], 2.5)
        self.assertAlmostEqual(a["otkrivanje"]["left"], 1.5)
        self.assertAlmostEqual(a["ostatak"]["left"], 1.0)
        self.assertAlmostEqual(sum(v["left"] for v in a.values()), 5.0)

    def test_rollover_grows_with_the_day_and_only_downwards(self):
        # priority 1 spent nothing: at noon half of its share rolls to priority 2, and on from there
        a = xb.allowance({}, 5.0, 0.5)
        self.assertAlmostEqual(a["pozivi"]["left"], 2.5)                      # nothing rolls up
        self.assertAlmostEqual(a["otkrivanje"]["carry"], 1.25)
        self.assertAlmostEqual(a["otkrivanje"]["left"], 1.5 + 1.25)
        self.assertAlmostEqual(a["ostatak"]["carry"], 0.75 + 1.25)            # 2's own half + what 1 passed on
        # at the end of the day all of it has rolled; the total never exceeds L
        e = xb.allowance({}, 5.0, 1.0)
        self.assertAlmostEqual(e["ostatak"]["left"], 5.0)
        e = xb.allowance({"ostatak": 4.0}, 5.0, 1.0)
        self.assertAlmostEqual(e["pozivi"]["left"], 1.0)                      # total cap: L - all spent

    def test_a_busy_priority_passes_nothing_on(self):
        a = xb.allowance({"pozivi": 2.5}, 5.0, 0.9)
        self.assertEqual(a["pozivi"]["left"], 0.0)
        self.assertEqual(a["otkrivanje"]["carry"], 0.0)

    def test_month_cap_wins(self):
        self.assertEqual(xb.limit_of(0.0, 5.0, 100.0), 5.0)
        self.assertAlmostEqual(xb.limit_of(97.5, 5.0, 100.0), 2.5)
        self.assertEqual(xb.limit_of(100.0, 5.0, 100.0), 0.0)
        self.assertEqual(xb.limit_of(120.0, 5.0, 100.0), 0.0)

    def test_env_only_lowers(self):
        with mock.patch.dict(os.environ, {"X_DAY_USD": "9", "X_MONTH_USD": "500"}):
            self.assertEqual((xb.day_cap(), xb.month_cap()), (5.0, 100.0))
        with mock.patch.dict(os.environ, {"X_DAY_USD": "2", "X_MONTH_USD": "x"}):
            self.assertEqual((xb.day_cap(), xb.month_cap()), (2.0, 100.0))


class Caps(Ledger):
    def test_day_cap(self):
        t = T0 - 12 * 3600 + 60   # 00:01: no rollover yet
        self.assertTrue(xb.room("pozivi", 2.5, t))
        xb.book("pozivi", 2.5, t, "moc")
        self.assertFalse(xb.room("pozivi", 0.01, t))                          # its share is used
        self.assertTrue(xb.room("otkrivanje", 1.5, t))
        xb.book("otkrivanje", 1.5, t, "timeline")
        xb.book("ostatak", 1.0, t, "makroinf")
        for k in xb.KEYS:
            self.assertFalse(xb.room(k, 0.0001, T0 + 11 * 3600))             # 5 $ spent: nothing more today
        self.assertTrue(xb.room("pozivi", 2.5, T0 + D))                       # the next UTC day starts afresh
        with self.assertRaises(xb.Cap):
            xb.need("pozivi", 0.01, T0)

    def test_month_cap(self):
        # 20 days of 5 $ = 100 $ in November: the 27th has nothing left, though its own day is empty
        for i in range(20):
            xb.book("pozivi", 5.0, T0 - (i + 1) * D, "moc")
        st = xb.state(T0)
        self.assertEqual(st["L"], 0.0)
        self.assertEqual(st["month"], 100.0)
        for k in xb.KEYS:
            self.assertFalse(xb.room(k, 0.0001, T0))
        self.assertIn("mjesečni strop dosegnut", xb.line(T0))
        self.assertTrue(xb.room("pozivi", 2.5, T0 + 4 * D + 1))               # 1.12.: a new month

    def test_month_cap_partial_day(self):
        for i in range(19):
            xb.book("ostatak", 5.0, T0 - (i + 1) * D, "x")
        xb.book("ostatak", 3.0, T0 - 20 * D, "x")                            # 98 $ before today
        st = xb.state(T0)
        self.assertAlmostEqual(st["L"], 2.0)
        self.assertAlmostEqual(st["cats"]["pozivi"]["avail"], 1.0)

    def test_rollover_in_the_ledger(self):
        late = T0 + 11 * 3600 + 59 * 60                                     # 23:59: nearly all unused has rolled
        self.assertFalse(xb.room("ostatak", 1.5, T0 - 12 * 3600 + 60))        # morning: only its own 1 $
        self.assertTrue(xb.room("ostatak", 4.9, late))
        xb.book("ostatak", 4.9, late, "skener")
        self.assertFalse(xb.room("pozivi", 0.2, late))                        # the total cap holds

    def test_no_ledger_is_open(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(xb.path())
            self.assertTrue(xb.room("pozivi", 1e9))
            xb.book("pozivi", 1.0)                                            # nothing written, no error
            self.assertIn("nema trajnog stanja", xb.line())

    def test_line(self):
        xb.book("pozivi", 0.4, T0, "moc")
        xb.book("pozivi", 0.1, T0, "obrisane")
        xb.book("otkrivanje", 0.3, T0, "timeline")
        xb.note("pozivi", 37, T0)
        xb.note("novi_influenceri", 4, T0)
        s = xb.line(T0)
        self.assertIn("X budžet 2026-11-27", s)
        self.assertIn("pozivi 0,50/2,50 $ (moc 0,40, obrisane 0,10)", s)
        self.assertIn("dan 0,80/5,00 $", s)
        self.assertIn("mjesec 0,80/100,00 $", s)
        self.assertIn("uhvaćeno poziva 37, novih influencera 4", s)


class Twapi(Ledger):
    def test_search_stops_before_a_page_that_does_not_fit(self):
        from kol import twapi
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT)")
        pages = []

        def get(q, cursor):
            pages.append(q)
            return {"tweets": [{"id": str(len(pages)), "createdAt": None}] * 20, "has_next_page": True,
                    "next_cursor": "c"}
        xb.book("ostatak", 1.0 - twapi.MAX_PAGE * 1.5, T0 - 12 * 3600 + 60, "x")
        twapi.search(con, "q", T0 - 3600, 100.0, get=get, max_pages=5, now=T0 - 12 * 3600 + 60, cat="ostatak",
                     job="skener")
        self.assertEqual(len(pages), 1)                                       # the second page would not fit
        st = xb.state(T0 - 12 * 3600 + 60)
        self.assertAlmostEqual(st["jobs"]["ostatak"]["skener"], twapi.cost(20))
        self.assertAlmostEqual(twapi.spent(con, T0 - 12 * 3600 + 60), twapi.cost(20))   # old counter still kept

    def test_tweets_raise_at_the_cap(self):
        from kol import twapi
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT)")
        xb.book("pozivi", 5.0, T0, "moc")
        called = []
        with self.assertRaises(xb.Cap):
            twapi.tweets(con, ["1", "2"], get=lambda u, p: called.append(1) or {"tweets": []}, now=T0,
                         cat="pozivi")
        self.assertEqual(called, [])                                          # no request was made

    def test_apify_x_sources(self):
        from hype import apify
        xb.book("ostatak", 5.0, time.time(), "x")
        cfg = {"daily_usd": {"x_trends": 1.0, "kol_monitor": 1.0}, "ugaseno": {}}
        with mock.patch.object(apify, "config", lambda: cfg), mock.patch.object(apify, "spent", lambda *a: 0.0), \
                mock.patch.object(apify, "monthly", lambda: (0.0, 0.0)):
            with self.assertRaises(apify.BudgetExceeded):
                apify.check("x_trends")
            apify.check("kol_monitor")                                        # only booked, its stop must work


class WindowAbolished(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"SOCIAL_STATE": os.path.join(self.tmp.name, "drustveni.json")})
        env.start()
        self.addCleanup(env.stop)
        for k in ("SOCIAL_WINDOW", "SOCIAL_ALWAYS", "SOCIAL_EVERY_D", "SOCIAL_WINDOW_H"):
            os.environ.pop(k, None)

    def test_no_gate_blocks(self):
        from ops import drustveni
        # with the old window the first start opened it, and 6 h later every gate was closed for 5 days
        drustveni._update(drustveni.path(), lambda st: (st.update(prvi=T0 - 2 * D) or None, True))
        for t in (T0, T0 + D, T0 + 3 * D):
            self.assertTrue(drustveni.social_open(t))
            for job in ("kol_krug", "xmom", "detektiv", "brzo_obrisane", "kol_minute"):
                self.assertTrue(drustveni.gate(job, t))
            for argv in (["python3", "run_makroinf.py", "krug"], ["python3", "run_veliki.py", "moc"],
                         ["python3", "run_kol.py", "search-round"], ["python3", "run_konsenzus.py"]):
                self.assertIsNone(drustveni.skip_cmd(argv, t))
        drustveni.gate_main(["python3", "run_makroinf.py", "krug"])           # does not exit
        self.assertIn("svaki dan", drustveni.line(T0))
        self.assertNotIn("zatvoren", drustveni.line(T0))
        self.assertEqual(drustveni.notice_html("hr"), "")
        self.assertEqual(drustveni.public_notice("en"), "")
        self.assertEqual(drustveni.notice_dates(T0), (None, None))

    def test_the_daily_cost_line(self):
        from usage import daily
        from ops import drustveni
        self.assertIn("ukinut", daily.drustveni_part(daily.drustveni(T0)))
        self.assertNotIn("prozor zatvoren", daily.drustveni_part(daily.drustveni(T0)))
        with mock.patch.dict(os.environ, {"SOCIAL_WINDOW": "1"}):               # the old window, on request only
            drustveni._update(drustveni.path(), lambda st: (st.update(prvi=T0 - 2 * D) or None, True))
            self.assertFalse(drustveni.social_open(T0))

    def test_makroinf_approved(self):
        from makroinf import store
        self.assertFalse(store.DEFAULT["twapi_stop"])


class WalletTokens(Ledger):
    def test_calls_and_candidates(self):
        from kol import novcanici_x, store as kstore, twapi
        kdb, wdb = os.path.join(self.tmp.name, "kol.db"), os.path.join(self.tmp.name, "wallets.db")
        from wallets import store as wstore
        wcon = wstore.connect(wdb)
        buy = T0 - 3600
        wcon.execute("INSERT INTO wallet_trades VALUES (?,?,?,?,?,?,?)", ("W1", "s1", buy, MA, 1.0, 0.5, "buy"))
        wcon.execute("INSERT INTO wallet_trades VALUES (?,?,?,?,?,?,?)", ("W2", "s2", buy, MB, 1.0, 0.5, "buy"))
        wcon.commit()
        wcon.close()
        con = kstore.connect(kdb)
        iso = lambda t: time.strftime("%a %b %d %H:%M:%S +0000 %Y", time.gmtime(t))  # noqa: E731
        queries = []

        def get(q, cursor):
            queries.append(q)
            return {"tweets": [
                {"id": "t1", "text": MA + " going up", "createdAt": iso(buy + 600),
                 "author": {"userName": "fresh_caller", "followers": 5000}},
                {"id": "t2", "text": MA, "createdAt": iso(buy - 1800),
                 "author": {"userName": "early_one", "followers": 100}}], "has_next_page": False}
        with mock.patch.object(twapi, "key", lambda: "k"):
            n = novcanici_x.search(con, {}, get=get, now=T0, wallets={"W1"}, wpath=wdb, log=lambda *a: None)
        self.assertEqual(len(queries), 1)                                     # W2 is not watched
        self.assertTrue(queries[0].startswith(MA))
        rows = con.execute("SELECT handle, wallet, delay_s, known FROM nx_kandidati").fetchall()
        self.assertEqual(rows, [("fresh_caller", "W1", 600, 0)])             # the early one called BEFORE the buy
        self.assertGreaterEqual(n, 0)
        st = xb.state(T0)
        self.assertIn("novcanici", st["jobs"].get("pozivi", {}))
        # searched once: the next round does not buy it again
        with mock.patch.object(twapi, "key", lambda: "k"):
            novcanici_x.search(con, {}, get=get, now=T0 + 60, wallets={"W1"}, wpath=wdb, log=lambda *a: None)
        self.assertEqual(len(queries), 1)
        con.close()

    def test_candidates_pure(self):
        from kol import novcanici_x
        calls = [{"handle": "a", "ts": 1100}, {"handle": "a", "ts": 1050}, {"handle": "b", "ts": 900},
                 {"handle": "c", "ts": 1000 + 7 * 3600}]
        self.assertEqual(novcanici_x.candidates(calls, [(1000, "W")], 6 * 3600), [("a", "W", 1000, 1050, 50)])


if __name__ == "__main__":
    unittest.main()
