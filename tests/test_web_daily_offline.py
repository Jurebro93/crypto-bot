"""The daily 02:00 refresh of the public web: when the scheduler runs it (Zagreb time, across both clock changes),
what the job does (run_web.py daily), how the web process drops its in-memory copies once, and the dates the sitemap
gives blog posts. No network, temp databases only."""
import datetime as dt
import json
import os
import re
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_sched  # noqa: E402
import run_web  # noqa: E402
from ui import bloglive, coins, landing, public, sitelog  # noqa: E402

UTC = dt.timezone.utc
ENV = ("KOL_DB", "WALLET_DB", "TG_DB", "HYPE_DB", "WEB_DAILY_NO_NET", "RENDER_EXTERNAL_URL", "SITE_LIVE_SINCE")


def utc(y, m, d, hh=0, mm=0):
    return dt.datetime(y, m, d, hh, mm, tzinfo=UTC)


def simulate(start, hours, step_min=5, last=None):
    """The scheduler's 5-minute checks over `hours`: [(local day the job ran for, UTC moment)].
    last: the day the job last ran for before the first check (None = never, so the first check catches up)."""
    runs, t = [], start
    while t < start + dt.timedelta(hours=hours):
        day = run_sched.local_due(2, last, t)
        if day:
            runs.append((day, t))
            last = day
        t += dt.timedelta(minutes=step_min)
    return runs


class DueAtTwo(unittest.TestCase):
    def test_two_at_night_zagreb_time_winter_and_summer(self):
        self.assertIsNone(run_sched.local_due(2, None, utc(2026, 11, 10, 0, 55)))             # 01:55 CET
        self.assertEqual(run_sched.local_due(2, None, utc(2026, 11, 10, 1, 0)), "2026-11-10")  # 02:00 CET = 01:00 UTC
        self.assertIsNone(run_sched.local_due(2, None, utc(2026, 7, 9, 23, 55)))              # 01:55 CEST
        self.assertEqual(run_sched.local_due(2, None, utc(2026, 7, 10, 0, 0)), "2026-07-10")   # 02:00 CEST = 00:00 UTC
        self.assertIsNone(run_sched.local_due(2, "2026-11-10", utc(2026, 11, 10, 15, 0)))     # done for today
        self.assertEqual(run_sched.local_due(2, "2026-11-09", utc(2026, 11, 10, 9, 0)), "2026-11-10")   # morning catch-up

    def test_once_a_day_when_the_clocks_go_back(self):
        runs = simulate(utc(2026, 10, 24, 12), 72, last="2026-10-24")   # 25.10.2026: 03:00 CEST becomes 02:00 CET
        self.assertEqual([d for d, _ in runs], ["2026-10-25", "2026-10-26", "2026-10-27"])
        self.assertEqual(runs[0][1], utc(2026, 10, 25, 0, 0))     # the first 02:00 (summer time); the second one is skipped
        self.assertEqual(runs[1][1], utc(2026, 10, 26, 1, 0))     # 02:00 winter time

    def test_once_a_day_when_the_clocks_go_forward(self):
        runs = simulate(utc(2027, 3, 27, 12), 72, last="2027-03-27")    # 28.3.2027: 02:00 CET becomes 03:00 CEST
        self.assertEqual([d for d, _ in runs], ["2027-03-28", "2027-03-29", "2027-03-30"])
        self.assertEqual(runs[0][1], utc(2027, 3, 28, 1, 0))      # there is no 02:00 that night: 03:00 it is
        self.assertEqual(runs[1][1], utc(2027, 3, 29, 0, 0))      # 02:00 summer time

    def test_a_whole_year_of_checks_gives_one_run_per_day(self):
        runs = simulate(utc(2026, 1, 1, 0), 24 * 365, step_min=30)
        days = [d for d, _ in runs]
        self.assertEqual(len(days), len(set(days)))
        self.assertEqual(len(days), 365)
        from zoneinfo import ZoneInfo
        hours = {t.astimezone(ZoneInfo("Europe/Zagreb")).hour for _, t in runs}
        self.assertEqual(hours, {2, 3})                           # 03:00 only on the one night without a 02:00


class DailyLocalLoop(unittest.TestCase):
    def setUp(self):
        self._state = run_sched.STATE
        run_sched.STATE = os.path.join(tempfile.mkdtemp(), "sched_state.json")

    def tearDown(self):
        run_sched.STATE = self._state

    def loop(self, codes, due="2026-11-10", checks=6):
        """Run daily_local until `checks` sleeps happened; codes: the job's exit code per run. -> (runs, sleeps)."""
        runs, sleeps = [], []

        def run(name, args, light=False):
            runs.append((name, tuple(args), light))
            return codes[min(len(runs), len(codes)) - 1]

        def sleep(s):
            sleeps.append(s)
            if len(sleeps) >= checks:
                raise KeyboardInterrupt

        def due_now(hour, last, now=None, tz=None):
            return None if last == due else due

        with mock.patch.object(run_sched, "run", side_effect=run), mock.patch("builtins.print"), \
                mock.patch.object(run_sched.time, "sleep", side_effect=sleep), \
                mock.patch.object(run_sched, "local_due", side_effect=due_now):
            with self.assertRaises(KeyboardInterrupt):
                run_sched.daily_local("web", ["run_web.py", "daily"], 2)
        return runs, sleeps

    def test_runs_once_and_remembers_the_day_across_restarts(self):
        runs, sleeps = self.loop([0])
        self.assertEqual(runs, [("web", ("run_web.py", "daily"), True)])        # light: not behind the heavy lock
        self.assertEqual(sleeps[0], run_sched.LIGHT_START_DELAY_S)              # not into start.sh's maintenance
        self.assertEqual(run_sched._last_day("web"), "2026-11-10")
        runs, _ = self.loop([0])                                                # a deploy restarts the scheduler
        self.assertEqual(runs, [])

    def test_a_failed_run_is_tried_again_later_and_given_up_after_three(self):
        runs, sleeps = self.loop([1, 0])
        self.assertEqual(len(runs), 2)
        self.assertIn(run_sched.LOCAL_RETRY_S, sleeps)
        self.assertEqual(run_sched._last_day("web"), "2026-11-10")
        run_sched._set_last_day("web", None)
        runs, sleeps = self.loop([1], checks=8)
        self.assertEqual(len(runs), run_sched.LOCAL_TRIES)                      # then the day is let go, no hammering
        self.assertEqual(sleeps.count(run_sched.LOCAL_RETRY_S), run_sched.LOCAL_TRIES - 1)
        self.assertEqual(run_sched._last_day("web"), "2026-11-10")

    def test_job_is_declared_at_two_and_points_at_the_real_script(self):
        jobs = {name: (fn, args) for name, fn, args in run_sched.JOBS}
        fn, args = jobs["web"]
        self.assertIs(fn, run_sched.daily_local)
        self.assertEqual(args, (["run_web.py", "daily"], 2))
        self.assertTrue(os.path.exists(os.path.join(run_sched.ROOT, args[0][0])))
        self.assertEqual(run_sched.WEB_TZ, "Europe/Zagreb")
        from ops import heavy
        with mock.patch.object(heavy, "NIGHT", "1-6"):
            self.assertTrue(heavy.night_now(utc(2026, 11, 10, 1, 0)))           # 02:00 is inside the night window
            self.assertTrue(heavy.night_now(utc(2026, 7, 10, 0, 0)))


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self._env = {k: os.environ.get(k) for k in ENV}
        for env, name in (("KOL_DB", "kol.db"), ("WALLET_DB", "wallets.db"), ("TG_DB", "tg.db"), ("HYPE_DB", "hype.db")):
            os.environ[env] = os.path.join(self.d, name)
        os.environ["RENDER_EXTERNAL_URL"] = "https://example.com"
        os.environ.pop("WEB_DAILY_NO_NET", None)
        self._coins_db, self._stats = coins.DB, dict(landing._STATS)
        coins.DB = os.path.join(self.d, "public.db")
        sitelog.DB = None
        sitelog._SEEN.update(init=False, m=None)
        public._cache.clear()

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        coins.DB = self._coins_db
        landing._STATS.clear()
        landing._STATS.update(self._stats)
        sitelog._SEEN.update(init=False, m=None)
        public._cache.clear()

    def wallets(self, n):
        from wallets import store as wstore
        con = wstore.connect(os.environ["WALLET_DB"])
        for i in range(n):
            con.execute("INSERT OR IGNORE INTO wallets (wallet, scored_at) VALUES (?, 1)", (f"W{i}",))
            con.execute("INSERT OR IGNORE INTO wallet_trades (wallet, sig, ts, mint) VALUES (?,?,1,'M')", (f"W{i}", f"s{i}"))
        con.commit()
        con.close()


class DailyJob(Base):
    def test_two_nights_give_a_diff_a_refreshed_blog_and_a_marker(self):
        self.wallets(20)
        with mock.patch("builtins.print") as pr:
            first = run_web.daily(now=dt.datetime(2026, 11, 10, 1, 2, tzinfo=UTC).timestamp(), net=False)
            self.assertIn("prvi zapis", pr.call_args.args[0])
        self.assertEqual((first["day"], first["added"]), ("2026-11-10", {}))
        self.assertEqual(set(first["blogs"]), {"what-is-wallet-tracking", "what-is-copy-trading", "tokens-sent-to-kol-wallets"})
        self.wallets(27)
        with mock.patch("builtins.print") as pr:
            second = run_web.daily(now=dt.datetime(2026, 11, 11, 1, 2, tzinfo=UTC).timestamp(), net=False)
            line = pr.call_args.args[0]
        self.assertEqual(second["added"], {"wallets": 7, "trades": 7})
        self.assertIn("novčanici +7, tradeovi novčanika +7; blogovi s novim podacima: 3", line)
        self.assertEqual(sitelog.marker()[0], "2026-11-11")
        self.assertEqual(bloglive.blocks()["wallets"]["data"]["wallets"], 27)
        with mock.patch("builtins.print"):
            third = run_web.daily(now=dt.datetime(2026, 11, 12, 1, 2, tzinfo=UTC).timestamp(), net=False)
        self.assertEqual((third["added"], third["blogs"]), ({}, []))           # nothing grew: nothing is claimed

    def test_a_failed_step_is_one_line_and_the_rest_still_runs(self):
        self.wallets(3)
        with mock.patch.object(bloglive, "refresh", side_effect=RuntimeError("blok")), mock.patch("builtins.print") as pr:
            entry = run_web.daily(now=dt.datetime(2026, 11, 10, 1, 2, tzinfo=UTC).timestamp(), net=False)
        self.assertEqual(entry["counts"]["wallets"], 3)                         # the log row is still written
        self.assertIn("korak 'blog' nije uspio", " ".join(str(c) for c in pr.call_args_list))
        args = type("A", (), {"no_net": True})()
        with mock.patch.object(sitelog, "record", side_effect=RuntimeError("disk")), mock.patch("builtins.print"), \
                mock.patch.object(run_web.os, "nice"):
            self.assertEqual(run_web.cmd_daily(args), 1)                         # no row = the scheduler tries again
        with mock.patch("builtins.print"), mock.patch.object(run_web.os, "nice"):
            self.assertEqual(run_web.cmd_daily(args), 0)

    def test_coin_list_is_read_again_only_when_old_and_never_without_network_permission(self):
        with mock.patch.object(coins, "refresh", return_value=100) as rf, mock.patch("builtins.print"):
            run_web.daily(now=time.time(), net=False)
            self.assertEqual(rf.call_count, 0)                                  # --no-net
            os.environ["WEB_DAILY_NO_NET"] = "1"
            run_web.daily(now=time.time())
            self.assertEqual(rf.call_count, 0)
            os.environ.pop("WEB_DAILY_NO_NET")
            self.assertIsNone(coins.age_s())                                    # never stored: read it
            run_web.daily(now=time.time())
            self.assertEqual(rf.call_count, 1)
            con = coins.connect()
            con.execute("INSERT INTO coins (mint, slug, updated) VALUES ('M','m',?)", (int(time.time()) - 600,))
            con.commit()
            con.close()
            self.assertAlmostEqual(coins.age_s(), 600, delta=5)
            run_web.daily(now=time.time())
            self.assertEqual(rf.call_count, 1)                                  # 10 minutes old: the web process just read it
            con = coins.connect()
            con.execute("UPDATE coins SET updated = ?", (int(time.time()) - 2 * 3600,))
            con.commit()
            con.close()
            run_web.daily(now=time.time())
            self.assertEqual(rf.call_count, 2)
        with mock.patch.object(coins, "refresh", side_effect=OSError("nema mreže")), mock.patch("builtins.print"):
            self.assertIsNotNone(run_web.daily(now=time.time()))                # Jupiter down: the log is still written

    def test_job_calls_nothing_paid_and_needs_no_network_for_our_data(self):
        src = ""
        for mod in (run_web, sitelog, bloglive):
            with open(mod.__file__) as f:
                src += f.read()
        for word in ("helius", "apify", "twitterapi", "anthropic", "urllib", "requests", "birdeye", "tgstat"):
            self.assertNotIn(word, src.lower().replace("no paid source", ""), word)

    def test_log_command_prints_the_days(self):
        sitelog.record(dt.datetime(2026, 11, 10, 1, 5, tzinfo=UTC).timestamp(), counted={"kols": 1})
        sitelog.record(dt.datetime(2026, 11, 11, 1, 5, tzinfo=UTC).timestamp(), counted={"kols": 4})
        with mock.patch("builtins.print") as pr:
            self.assertEqual(run_web.main(["log", "-n", "3"]), 0)
        out = "\n".join(c.args[0] for c in pr.call_args_list)
        self.assertIn("2026-11-11: influenceri na ljestvici +3", out)
        self.assertIn("MemeSonar je live", out)


class DropCopies(Base):
    def test_drop_caches_empties_every_in_memory_copy_of_public_data(self):
        from ourtoken import advisor
        from ui import kolstats, marketpub
        public.route("/robots.txt")
        public.route("/hr/blog")
        self.assertEqual(len(public._cache), 2)
        kolstats._BASE.update(ts=time.time(), v={"accounts": 3})
        advisor._CACHE["x"] = (time.time(), 1)
        with marketpub._lock:
            old = dict(marketpub._cache)
            marketpub._cache.update(t=time.time(), d={"keep": "as fallback"})
        try:
            self.assertEqual(public.drop_caches(), 2)
            self.assertEqual((len(public._cache), kolstats._BASE, advisor._CACHE), (0, {}, {}))
            self.assertEqual(marketpub._cache["t"], 0.0)                         # rebuilt on the next view ...
            self.assertEqual(marketpub._cache["d"], {"keep": "as fallback"})     # ... with the old numbers if that fails
        finally:
            with marketpub._lock:
                marketpub._cache.update(old)

    def test_one_copy_that_cannot_be_dropped_does_not_stop_the_others(self):
        from ui import kolstats
        public.route("/robots.txt")
        kolstats._BASE.update(ts=1, v={"a": 1})
        with mock.patch.object(public, "_drop_market", side_effect=RuntimeError("x")), mock.patch("builtins.print") as pr:
            public.drop_caches()
        self.assertEqual((len(public._cache), kolstats._BASE), (0, {}))
        self.assertEqual(pr.call_count, 1)

    def test_warm_builds_the_main_tables_in_both_languages(self):
        paths = public.hub_paths()
        for p in ("/influencers", "/hr/influenceri", "/solana-meme-coins", "/hr/solana-meme-coini", "/telegram-channels",
                  "/hr/blog", "/sitemap.xml"):
            self.assertIn(p, paths)
        with mock.patch.object(public.time, "sleep") as sl:
            n = public.warm(["/robots.txt", "/hr/blog", "/nije-javno"], pause_s=1.0)
        self.assertEqual(n, 2)
        self.assertEqual(sl.call_count, 3)                                       # a pause between pages: no CPU burst
        self.assertIn("/hr/blog", public._cache)
        with mock.patch.object(public, "route", side_effect=RuntimeError("x")), mock.patch("builtins.print"):
            self.assertEqual(public.warm(["/hr/blog"], pause_s=0), 0)            # never raises into the watch thread

    def test_the_nights_marker_makes_the_web_process_refresh_once(self):
        sitelog.record(dt.datetime(2026, 11, 9, 1, 5, tzinfo=UTC).timestamp(), counted={"kols": 1})
        public.route("/hr/blog")
        landing._STATS.update(ts=time.time(), v={"tokens": 1}, busy=False)
        with mock.patch.object(public, "warm") as warm, mock.patch.object(landing, "HERE", self.d), \
                mock.patch("builtins.print"):
            self.assertFalse(sitelog.check(landing.refreshed))                   # start of the process: nothing to drop
            self.assertEqual(len(public._cache), 1)
            sitelog.record(dt.datetime(2026, 11, 10, 1, 5, tzinfo=UTC).timestamp(), counted={"kols": 5})
            self.assertTrue(sitelog.check(landing.refreshed))                    # the night's job has written its row
            self.assertEqual(len(public._cache), 0)                              # rendered pages dropped
            self.assertEqual(landing._STATS["v"]["log"][0]["added"], {"kols": 4})   # landing numbers and log re-read
            self.assertFalse(landing._STATS["busy"])
            self.assertEqual(warm.call_count, 1)
            public.route("/hr/blog")
            self.assertFalse(sitelog.check(landing.refreshed))                   # and only once
            self.assertEqual((len(public._cache), warm.call_count), (1, 1))

    def test_start_also_starts_the_watch(self):
        with mock.patch.object(landing.threading, "Thread") as th, mock.patch.object(sitelog, "watch") as watch:
            landing.start()
        self.assertEqual(th.call_count, 1)
        watch.assert_called_once_with(landing.refreshed)
        with mock.patch.object(landing.threading, "Thread"), mock.patch.object(sitelog, "watch", side_effect=RuntimeError("x")), \
                mock.patch("builtins.print") as pr:
            landing.start()                                                      # the page lives without the watch
        self.assertEqual(pr.call_count, 1)


class SitemapDates(Base):
    def lastmods(self):
        sm = public.sitemap()
        return dict(re.findall(r"<loc>https://example.com([^<]*)</loc><lastmod>([^<]+)</lastmod>", sm))

    def test_blog_posts_carry_the_day_they_changed_and_data_pages_today(self):
        today = time.strftime("%Y-%m-%d", time.gmtime())
        lm = self.lastmods()
        self.assertEqual(lm["/blog/crypto-tax-croatia"], "2026-11-01")           # its own date, not "today" every day
        self.assertEqual(lm["/hr/blog/porez-na-kriptovalute"], "2026-11-01")
        self.assertEqual(lm["/blog/best-crypto-telegram-channels"], "2026-11-09")
        self.assertEqual(lm["/influencers"], today)                              # rebuilt from the databases all day
        self.assertEqual(lm["/blog"], today)
        now = time.time()
        bloglive.refresh(now, measured={"telegram": {"tg_channels": 9, "tg_measured": 90}})
        lm = self.lastmods()
        self.assertEqual(lm["/blog/best-crypto-telegram-channels"], min(sitelog.local_day(now), today))   # numbers changed tonight
        self.assertEqual(lm["/hr/blog/najbolji-kripto-telegram-kanali"], lm["/blog/best-crypto-telegram-channels"])
        self.assertEqual(lm["/blog/crypto-tax-croatia"], "2026-11-01")
        from ui import blog
        self.assertEqual(len(blog.urls()[0]), 3)                                 # the old shape stays for other callers
        self.assertEqual(json.dumps(blog.urls()), json.dumps([u[:3] for u in blog.urls(with_lastmod=True)]))


if __name__ == "__main__":
    unittest.main()
