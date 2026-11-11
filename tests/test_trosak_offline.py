"""11.11. (Jure, "Može sve": preporuke 1, 3, 4 i 8 iz analize troška):
  1. the CoinGecko key spent by the UTC hour, the live jobs first, the night book "masovno" capped at night and paused
     by day after a GeckoTerminal 429 (event_calendar/http, learn/masovno);
  3. Apify x_buzz switched off by config, the xquik monitor kept (its precondition is not met) (hype/apify, kol/live);
  4. the scanner's X cap 6 -> 3 $ a day; X accounts without a call in 14 days skipped in the timeline (kol/collect);
  8. one cost line per source a day + the same numbers as JSON for the weekly report (usage/daily, run_sched).

    python3 -m unittest tests.test_trosak_offline
"""
import calendar
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from event_calendar import http  # noqa: E402

DAY0 = calendar.timegm((2026, 11, 12, 0, 0, 0))   # a winter day: Zagreb = UTC + 1
H = 3600
GT = "https://api.geckoterminal.com/api/v2/networks/solana/pools/P1/ohlcv/minute?limit=60"


class _CG(unittest.TestCase):
    """A private day file, the key set, the clock pinned."""
    def setUp(self):
        self._env = {k: os.environ.get(k) for k in ("COINGECKO_API_KEY", "COINGECKO_DEMO", "CG_DAILY_CALLS", "DATA_DIR",
                                                    "CG_MASOVNO_NIGHT", "CG_RESERVE", "CG_JOB")}
        for k in self._env:
            os.environ.pop(k, None)
        os.environ["COINGECKO_API_KEY"] = "CG-test"
        self._tmp = tempfile.TemporaryDirectory()
        self._gate = http.GATE_DIR
        http.GATE_DIR = self._tmp.name
        self.now = DAY0 + 5 * H + 1800
        self._p = mock.patch.object(http, "_now", side_effect=lambda: self.now)
        self._p.start()

    def tearDown(self):
        self._p.stop()
        http.set_cg_job(None)
        http.GATE_DIR = self._gate
        self._tmp.cleanup()
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def take_until_refused(self, job, limit=10_000):
        n = 0
        while n < limit and http._cg_take(job=job):
            n += 1
        return n


class HourlyBudget(_CG):
    def test_allowance_is_cumulative_by_the_utc_hour_and_the_live_jobs_keep_the_last_part(self):
        st = http._cg_blank("2026-11-12")
        now = DAY0 + 5 * H + 1800                         # hour 5: 6 of 24 hours begun -> 2400 x 6 / 24 = 600
        st["n"] = 599
        self.assertTrue(http.cg_allow(st, "minute", now, 2400)[0])
        st["n"] = 600
        self.assertEqual(http.cg_allow(st, "minute", now, 2400), (False, "satni dio potrošen"))
        st["n"] = 549                                     # every other job stops half an hour's share (50) earlier
        self.assertTrue(http.cg_allow(st, "kol", now, 2400)[0])
        st["n"] = 550
        self.assertFalse(http.cg_allow(st, "kol", now, 2400)[0])
        st["n"] = 2400
        self.assertEqual(http.cg_allow(st, "minute", DAY0 + 23 * H, 2400), (False, "dnevni strop"))

    def test_minute_loop_range_momentum_and_scanner_get_the_rest_of_the_slice(self):
        os.environ["CG_DAILY_CALLS"] = "2400"
        self.assertEqual(self.take_until_refused("kol"), 550)      # a non-live job stops at 550 of the 600
        for job in ("minute", "range", "momentum", "scan"):
            self.assertTrue(http._cg_take(job=job), job)
        self.assertEqual(self.take_until_refused("minute"), 46)    # the live jobs take it up to 600
        st = http.cg_status()
        self.assertEqual((st["n"], st["allowed"]), (600, 600))
        self.assertEqual(st["jobs"], {"kol": 550, "minute": 47, "range": 1, "momentum": 1, "scan": 1})
        self.now += H                                               # a new hour: the next 100
        self.assertEqual(self.take_until_refused("minute"), 100)

    def test_unused_hours_roll_over(self):
        os.environ["CG_DAILY_CALLS"] = "2400"
        self.now = DAY0 + 20 * H                                     # nothing spent all day: 2100 open by 20:59
        self.assertEqual(self.take_until_refused("minute"), 2100)

    def test_masovno_only_at_night_and_at_most_its_night_cap_on_the_key(self):
        os.environ.update(CG_DAILY_CALLS="2400", CG_MASOVNO_NIGHT="30")
        self.now = DAY0 + 12 * H                                     # 13:00 CET: by day masovno goes free
        ok, why = http.cg_allow(http._cg_blank("2026-11-12"), "masovno", self.now)
        self.assertFalse(ok)
        self.assertIn("danju", why)
        self.now = DAY0 + 2 * H + 1800                               # 03:30 CET: the night window
        self.assertEqual(self.take_until_refused("masovno"), 30)    # its own night cap
        self.assertTrue(http._cg_take(job="minute"))                 # the others go on

    def test_a_refused_job_goes_free_and_is_counted_and_paced_as_free(self):
        os.environ["CG_DAILY_CALLS"] = "24"                          # 1 an hour: the hour's one call is the minute loop's
        self.now = DAY0 + 1800
        http.set_cg_job("minute")
        url, h = http._cg_route(GT, None)
        self.assertTrue(url.startswith("https://pro-api.coingecko.com"))
        http.set_cg_job("kol")
        self.assertEqual(http._cg_route(GT, None), (GT, None))
        self.assertEqual(http._shared(GT)[0], "geckoterminal.com")  # the free API, at the free pace
        self.assertEqual(http._shared(url)[0], "coingecko.com")     # the paid host stays on the paid gate
        st = http.cg_status()
        self.assertEqual((st["jobs"], st["free"]), ({"minute": 1}, {"kol": 1}))

    def test_429_counted_by_the_hour_and_the_legacy_file_is_read(self):
        http.note_429("https://api.geckoterminal.com/api/v2/x")
        http.note_429("https://pro-api.coingecko.com/api/v3/onchain/x")
        http.note_429("https://api.dexscreener.com/x")               # not ours to count
        st = http.cg_status()
        self.assertEqual(st["e429"], {"05": 2})
        self.assertEqual(http.gt_last_429(), int(self.now))
        with open(http._cg_day_file(), "w") as f:                    # before 11.11. the file was "YYYY-MM-DD n"
            f.write("2026-11-12 1500")
        self.assertEqual(http.cg_used()[0], 1500)
        self.assertIn("ključem 1.500 / dopušteno 750", http.cg_hour_line(queue=59))

    def test_job_names_from_the_command_line(self):
        j = http._job_from_argv
        self.assertEqual(j(["/x/run_kol.py", "minute-loop"]), "minute")
        self.assertEqual(j(["run_learn.py", "masovno"]), "masovno")
        self.assertEqual(j(["run_range.py", "once"]), "range")
        self.assertEqual(j(["run_momentum.py", "once"]), "momentum")
        self.assertEqual(j(["run_scan.py", "once"]), "scan")
        self.assertEqual(j(["run_kol.py", "loop"]), "kol")
        self.assertEqual(j(["/srv/kol/groupdisc.py", "night"]), "groupdisc")


def _masovno_dbs(tmp, now):
    hype = os.path.join(tmp, "hype.db")
    h = sqlite3.connect(hype)
    h.executescript("""CREATE TABLE live_launches (mint TEXT PRIMARY KEY, ts INTEGER, creator TEXT, name TEXT, symbol TEXT, initial_sol REAL, sig TEXT, pool TEXT);
                       CREATE TABLE chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER, sol REAL, PRIMARY KEY (sig, mint));
                       CREATE TABLE hype_signals (ts INTEGER, token TEXT, symbol TEXT, score REAL, price REAL, mcap REAL, liquidity REAL, features TEXT);""")
    for i in range(4):
        h.execute("INSERT INTO hype_signals VALUES (?, ?, ?, 50, 1.0, 60000, 20000, '{}')", (now - 28 * H, f"SCAN{i}", f"S{i}"))
    h.commit()
    h.close()
    from kol import store as kstore
    kol = os.path.join(tmp, "kol.db")
    kstore.connect(kol).close()
    return hype, kol


class MasovnoDayPause(unittest.TestCase):
    def test_backoff_after_a_429_by_day(self):
        from learn import masovno
        now = DAY0 + 12 * H
        cfg = masovno.config()
        self.assertEqual(masovno.day_pause_left(now, cfg, last_429=0), 0.0)
        self.assertGreater(masovno.day_pause_left(now, cfg, last_429=now - 100), 600)      # 12 min backoff
        self.assertEqual(masovno.day_pause_left(now, cfg, last_429=now - 13 * 60), 0.0)

    def test_a_day_pass_stops_at_the_first_429(self):
        from learn import masovno
        now = DAY0 + 12 * H
        tmp = tempfile.mkdtemp()
        hype, kol = _masovno_dbs(tmp, now)
        con = masovno.connect(os.path.join(tmp, "shadow.db"))
        with mock.patch.object(masovno, "_followed", return_value=[]):
            masovno.collect(con, now, hype_db=hype, kol_db=kol)

        def fetch(pool, start, end):
            return [(int(start) + i, 1.0, 1.01, 0.99, 1.0, 1000.0) for i in range(0, int(end - start), 300)]
        pool_for = lambda tok: ("POOL" + tok, 20000.0)   # noqa: E731
        # the first token is fetched, then GeckoTerminal answers 429: the pass ends there
        with mock.patch.object(masovno, "_last_429", side_effect=[0] + [2 ** 31] * 10):
            self.assertEqual(masovno.label(con, now, budget=100, fetch=fetch, pool_for=pool_for, stop_on_429=True), (1, 2))
        with mock.patch.object(masovno, "_last_429", return_value=0):
            self.assertEqual(masovno.label(con, now, budget=100, fetch=fetch, pool_for=pool_for, stop_on_429=True)[0], 3)
        con.close()


class ApifyOff(unittest.TestCase):
    def test_x_buzz_off_by_config_and_xquik_kept_with_its_reason(self):
        from hype import apify
        cfg = apify.config()
        self.assertTrue(apify.off("x_buzz", cfg))
        self.assertIsNone(apify.off("kol_monitor", cfg))             # precondition of the audit not met: stays on
        self.assertIn("kol_mentions", cfg["zadrzano"]["kol_monitor"])
        line = apify.status_line(cfg)
        self.assertTrue(line.startswith("apify: ugašeno x_buzz"))
        self.assertIn("ostaje kol_monitor", line)
        with self.assertRaises(apify.BudgetExceeded):
            apify.check("x_buzz")                                    # no run, whoever asks

    def test_xhook_does_not_cover_what_the_hype_scan_reads(self):
        """The audit's precondition for switching xquik off: /hook/x must write hype.db kol_mentions. It writes
        kol.db calls only, so the xquik monitor stays on (hype/apify.json zadrzano)."""
        import inspect
        from kol import xhook
        self.assertNotIn("kol_mentions", inspect.getsource(xhook))

    def test_switching_kol_monitor_off_stops_the_running_monitor_once(self):
        from hype import apify
        from kol import live, store as kstore
        con = kstore.connect(os.path.join(tempfile.mkdtemp(), "kol.db"))
        con.execute("INSERT INTO watch VALUES ('a', 1, 0, '')")
        con.execute("INSERT INTO monitor VALUES ('a', 0, ?)", (DAY0,))
        con.commit()
        calls = []
        mon = lambda hs, url, stop=False, hours=None: calls.append((hs, stop))   # noqa: E731
        with mock.patch.object(live, "hook_url", return_value="https://x/hook/kol?key=k"), \
                mock.patch.object(apify, "enabled", return_value=True), \
                mock.patch.object(apify, "off", side_effect=lambda s, cfg=None: "test" if s == "kol_monitor" else None):
            self.assertTrue(live.sync(con, {"watch": {"resync_h": 6}}, monitor=mon, now=DAY0 + H, log=lambda *a: None))
            self.assertEqual(calls, [(["a"], True)])
            self.assertFalse(live.sync(con, {"watch": {"resync_h": 6}}, monitor=mon, now=DAY0 + 2 * H, log=lambda *a: None))
        self.assertEqual(len(calls), 1)


class XTimeline(unittest.TestCase):
    def test_scanner_x_cap_is_3_dollars(self):
        with open(os.path.join(ROOT, "scan", "config.json")) as f:
            cfg = json.load(f)
        self.assertEqual(cfg["x_usd_day"], 3.0)

    def setUp(self):
        from kol import store as kstore
        self.con = kstore.connect(os.path.join(tempfile.mkdtemp(), "kol.db"))
        self.now = DAY0 + 12 * H
        D = 86400
        for h, first, call_age in (("ziv", 60, 2), ("mrtav", 60, 40), ("citani", 60, 40), ("nov", 3, 20),
                                   ("vlasnik", 60, 40)):
            self.con.execute("INSERT INTO kols (handle, score, followers, first_seen, stats) VALUES (?, 50, 10000, ?, '{}')",
                             (h, self.now - first * D))
            self.con.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES (?, ?, ?, ?, 'call')",
                             (h + "1", "T" + h, h, self.now - call_age * D))
        from kol import collect
        collect._searched(self.con, "tl:mrtav", "timeline_kol", self.now - H)        # read an hour ago
        collect._searched(self.con, "tl:citani", "timeline_kol", self.now - 7 * H)   # read 7 h ago: due again
        self.con.commit()
        self.cfg = {"timeline": {"every_h": 0.5, "kols": 20, "max_items": 60, "min_calls": 1, "min_followers": 5000,
                                 "refresh_d": 1, "core": 20, "per_query": 25, "stars_slots": 0,
                                 "mrtvi": {"dani": 14, "svakih_h": 6}}}

    def test_accounts_without_a_call_in_14_days_are_read_every_6_hours(self):
        from kol import collect
        st = {}
        with mock.patch.object(collect, "_owner_handles", return_value={"vlasnik"}):
            got = collect.timeline_handles(self.con, self.cfg, self.now, stats=st)
            later = collect.timeline_handles(self.con, self.cfg, self.now + 5 * H + 1)
        for h in ("ziv", "nov", "vlasnik", "citani"):
            self.assertIn(h, got)
        self.assertNotIn("mrtav", got)                       # skipped in the round, not deleted
        self.assertEqual({k: st[k] for k in ("aktivni", "novi", "vlasnikovi", "mrtvi_citani", "mrtvi_preskoceni")},
                         {"aktivni": 1, "novi": 1, "vlasnikovi": 1, "mrtvi_citani": 1, "mrtvi_preskoceni": 1})
        self.assertIn("mrtav", later)                         # 6 h after its last read it gets one look
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM kols").fetchone()[0], 5)

    def test_off_without_the_setting(self):
        from kol import collect
        cfg = {"timeline": dict(self.cfg["timeline"])}
        cfg["timeline"].pop("mrtvi")
        self.assertIn("mrtav", collect.timeline_handles(self.con, cfg, self.now))

    def test_the_real_config_skips_after_14_days_and_reads_every_6_hours(self):
        with open(os.path.join(ROOT, "kol", "config.json")) as f:
            cfg = json.load(f)
        self.assertEqual((cfg["timeline_twapi"]["mrtvi"]["dani"], cfg["timeline_twapi"]["mrtvi"]["svakih_h"]), (14, 6))


class DailyCostLine(_CG):
    def setUp(self):
        super().setUp()
        self.now = DAY0 + 23 * H + 59 * 60
        d = tempfile.mkdtemp()
        self.paths = {k: os.path.join(d, k + ".db") for k in ("kol", "scan", "hype", "usage", "ai")}
        from kol import store as kstore
        from scan import store as sstore
        from usage import meter
        k = kstore.connect(self.paths["kol"])
        day = "2026-11-12"
        for key, v in ((f"twapi:{day}", "6.10"), (f"twtl:{day}", "2.70"), (f"twdisc:{day}", "0.30"),
                       (f"twtrend:{day}", "0.10"), ("flash_day", json.dumps({"day": day, "n": 1000}))):
            k.execute("INSERT INTO kv VALUES (?, ?)", (key, v))
        k.commit()
        k.close()
        s = sstore.connect(self.paths["scan"])
        s.execute("INSERT INTO kv VALUES (?, '2.85')", (f"xusd:{day}",))
        s.commit()
        s.close()
        h = sqlite3.connect(self.paths["hype"])
        h.executescript("""CREATE TABLE apify_runs (ts INTEGER, source TEXT, actor TEXT, run_id TEXT, items INTEGER, cost_usd REAL, status TEXT);
                           CREATE TABLE live_state (key TEXT PRIMARY KEY, value TEXT);""")
        h.execute("INSERT INTO apify_runs VALUES (?, 'kol_search', 'a', 'r', 1, 0.12, 'SUCCEEDED')", (DAY0 + H,))
        h.execute("INSERT INTO apify_runs VALUES (?, 'x_buzz', 'a', 'r', 1, 0.30, 'SUCCEEDED')", (DAY0 - H,))   # yesterday
        h.execute("INSERT INTO live_state VALUES ('trades_day', ?)", (json.dumps({"day": day, "base": 20000, "seen": 5}),))
        h.commit()
        h.close()
        u = meter.connect(self.paths["usage"])
        u.executemany("INSERT INTO usage VALUES (?,?,?,?,?,?,?)",
                      [(DAY0 + 3 * H, "helius", "run_scan.py", "getTokenAccounts", 500, 0, 5000.0),
                       (DAY0 + 4 * H, "helius", "groupdisc.py", "getTransactionsForAddress", 299, 0, 2990.0),
                       (DAY0 - 2 * H, "helius", "run_scan.py", "getTokenAccounts", 500, 0, 9999.0),        # yesterday
                       (DAY0 + 2 * H, "anthropic", "run_learn.py", "postai", 2000, 0, 0.11)])
        u.executemany("INSERT INTO account VALUES (?,?,?,?,?,?,?)",
                      [(self.now - 86400, "helius", 6.30e6, 1e7, 0, 0, "{}"), (self.now - 60, "helius", 6.50e6, 1e7, 0, 0, "{}"),
                       (self.now - 86400, "apify", 1.0, 100, 0, 0, "{}"), (self.now - 60, "apify", 4.5, 100, 0, 0, "{}")])
        u.commit()
        u.close()
        a = sqlite3.connect(self.paths["ai"])
        a.execute("CREATE TABLE batches (id TEXT PRIMARY KEY, created INTEGER, n INTEGER, status TEXT, ids TEXT, kind TEXT, done_ts INTEGER, cost_usd REAL)")
        a.execute("INSERT INTO batches VALUES ('b', ?, 2000, 'gotovo', '[]', 'x', 0, 0.11)", (DAY0 + H,))
        a.commit()
        a.close()
        os.environ["CG_DAILY_CALLS"] = "3000"
        for job, n in (("minute", 5), ("masovno", 3)):
            for _ in range(n):
                http._cg_take(job=job, now=DAY0 + 2 * H)
        http._cg_free("kol")
        http.note_429(GT, now=DAY0 + 4 * H)

    def test_one_line_per_source_and_the_week(self):
        from usage import daily
        d = daily.collect(self.now, self.paths)
        self.assertEqual(d["coingecko"]["po_poslu"], {"minute": 5, "masovno": 3})
        self.assertEqual(d["coingecko"]["e429"], {"04": 1})
        self.assertEqual(d["twitterapi"]["dijelovi"], {"timeline": 2.7, "skener": 2.85, "discover": 0.3, "trending": 0.1,
                                                       "obrisane": 0.15, "ostalo": 0.0})
        self.assertEqual(d["apify"]["usd_bot"], 0.12)
        self.assertEqual(d["apify"]["racun"]["dan"], 3.5)
        self.assertEqual(d["pumpportal"], {"tradeova": 20000, "sol": 0.02})
        self.assertEqual(d["helius"]["krediti_bot"], 7990)
        self.assertEqual(d["helius"]["racun"]["dan"], 200000.0)
        self.assertEqual((d["ai"]["objava"], d["ai"]["usd"]), (2000, 0.11))
        line = daily.line(d)
        self.assertTrue(line.startswith("trošak po izvoru 2026-11-12 (UTC dan): CoinGecko ključem 8/3.000 (minute 5, masovno 3)"))
        for part in ("besplatno 1 (kol 1)", "429 ukupno 1 (po satu UTC: 04h 1)", "X twitterapi $6,10 (timeline 2,70, skener 2,85",
                     "Apify $0,12 po botu (kol_search 0,12), račun +$3,50 u 24 h", "PumpPortal 20.000 tradeova ≈ 0.020 SOL",
                     "Helius bot 7.990 kr. (run_scan.py 5.000, groupdisc.py 2.990), stanje računa 6.50M/10M (+200k u 24 h",
                     "AI oznake 2.000 objava, $0,11 (postai 0,11)"):
            self.assertIn(part, line)
        out = []
        daily.run(self.now, log=lambda *a, **k: out.append(a[0]), paths=self.paths, path=self.paths["usage"])
        self.assertEqual(out, [line])
        w = daily.week(self.now, path=self.paths["usage"])
        self.assertEqual((w["dana"], w["coingecko_kljuc"], w["x_usd"], w["pumpportal_tradeova"], w["helius_bot"]),
                         (1, 8, 6.1, 20000, 7990))
        md = "\n".join(daily.week_md(w))
        self.assertIn("## Trošak po izvoru (7 dana)", md)
        self.assertIn("X (twitterapi.io): $6,10", md)

    def test_without_an_account_reading_the_line_says_to_look_by_hand(self):
        from usage import daily
        u = sqlite3.connect(self.paths["usage"])
        u.execute("DELETE FROM account WHERE service = 'helius'")
        u.commit()
        u.close()
        self.assertIn("stanje računa: /usage ručno", daily.line(daily.collect(self.now, self.paths)))

    def test_scheduled_in_the_last_minute_of_the_utc_day(self):
        import datetime as dt
        import run_sched
        jobs = {name: (fn.__name__, args) for name, fn, args in run_sched.JOBS}
        self.assertEqual(jobs["trosak"], ("daily_utc", (["run_usage.py", "dnevno"], 23, 59)))
        t = lambda hh, mm: dt.datetime(2026, 11, 12, hh, mm, tzinfo=dt.timezone.utc)   # noqa: E731
        self.assertIsNone(run_sched.utc_due(23, 59, None, t(23, 58)))
        self.assertEqual(run_sched.utc_due(23, 59, None, t(23, 59)), "2026-11-12")
        self.assertIsNone(run_sched.utc_due(23, 59, "2026-11-12", t(23, 59)))


if __name__ == "__main__":
    unittest.main()
