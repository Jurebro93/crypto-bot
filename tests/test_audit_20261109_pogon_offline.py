"""Audit 9.11., group 'pogon' (start.sh, ops/, run_ui.py, run_sched.py):
P9  start-up maintenance no longer slims/compacts on every deploy (seconds, not minutes before UI and trade start);
P33 build_in_child never builds a HEAVY page in the UI process (busy lock, failed or slow child -> last copy / 503);
P63 market and usage are light scheduler jobs; a lock waiter logs every 10 min after the first 2."""
import contextlib
import gzip
import io
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ops import dbs, disk, heavy  # noqa: E402


class P9StartupIsLight(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = mock.patch.object(disk, "DATA_DIR", self.tmp.name)
        self.p.start()
        con = sqlite3.connect(os.path.join(self.tmp.name, "hype.db"))
        con.execute("CREATE TABLE apify_cache (key TEXT PRIMARY KEY, ts INTEGER, items TEXT)")
        con.execute("INSERT INTO apify_cache VALUES ('new', ?, '[]')", (int(time.time()),))
        con.commit()
        con.close()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def test_startup_skips_slim_and_compact_when_disk_has_room(self):
        with mock.patch.object(dbs, "slim_signals") as slim, mock.patch.object(dbs, "compact") as comp, \
                mock.patch.object(disk, "free_mb", return_value=dbs.STARTUP_COMPACT_FREE_MB + 1000), \
                contextlib.redirect_stdout(io.StringIO()):
            dbs.startup()
        slim.assert_not_called()
        comp.assert_not_called()
        con = sqlite3.connect(os.path.join(self.tmp.name, "hype.db"))
        self.assertEqual(con.execute("PRAGMA journal_mode").fetchone()[0], "wal")   # the fast part still happens
        self.assertEqual(con.execute("PRAGMA auto_vacuum").fetchone()[0], 2)
        con.close()

    def test_startup_compacts_offline_only_on_a_tight_disk(self):
        """The full-disk safety path stays: with little room the packed copy is made before the loops open the files."""
        with mock.patch.object(disk, "free_mb", return_value=10000.0), contextlib.redirect_stdout(io.StringIO()):
            dbs.startup()   # first start: auto_vacuum switched on (its own VACUUM replaces the compaction that time)
        with mock.patch.object(dbs, "compact", return_value=None) as comp, \
                mock.patch.object(disk, "free_mb", return_value=dbs.STARTUP_COMPACT_FREE_MB - 1), \
                contextlib.redirect_stdout(io.StringIO()):
            dbs.startup()
        self.assertTrue(comp.called)
        self.assertTrue(all(c.kwargs.get("offline") for c in comp.call_args_list))

    def test_unknown_free_space_is_not_tight(self):
        """Review 9.11.: disk.free_mb() -> None (OSError) must not count as "tight" and start the slow dbstat pass over
        every file; compact() could not finish without a known free space anyway."""
        with mock.patch.object(dbs, "compact") as comp, mock.patch.object(disk, "free_mb", return_value=None), \
                contextlib.redirect_stdout(io.StringIO()):
            dbs.startup()
        comp.assert_not_called()

    def test_hourly_still_slims(self):
        with mock.patch.object(dbs, "slim_signals", return_value=(0, 0)) as slim, contextlib.redirect_stdout(io.StringIO()):
            dbs.hourly()
        slim.assert_called_once()

    def test_start_sh_order_ui_trade_first_hourly_soon(self):
        sh = open(os.path.join(ROOT, "start.sh")).read()
        startup = sh.index("ops.health --startup")
        ui = sh.index("keep ui python3 run_ui.py")
        trade = sh.index("keep trade python3 run_trade.py follow")
        self.assertLess(sh.index("deploy_wait.py"), startup)        # stand-in first, unchanged
        self.assertLess(startup, ui)                                  # databases prepared before anything opens them
        self.assertLess(trade, sh.index("rugfilter.archive"))         # trade right after ui, before the data loops
        self.assertLess(trade, sh.index("run_calendar.py"))
        self.assertEqual(sh.count("keep trade python3 run_trade.py follow"), 1)
        self.assertIn('sleep "${HOURLY_FIRST_S:-600}"; while true; do python3 -m ops.heavy -m ops.health --hourly', sh)
        self.assertNotIn("sleep 3600; python3 -m ops.heavy -m ops.health --hourly", sh)
        subprocess.run(["bash", "-n", os.path.join(ROOT, "start.sh")], check=True)


class P33ChildNeverFallsBackHere(unittest.TestCase):
    def setUp(self):
        import run_ui
        from ui import pagecache
        self.run_ui, self.pagecache = run_ui, pagecache
        self.b = mock.patch.object(run_ui, "build", side_effect=AssertionError("build() ran in the UI process"))
        self.b.start()

    def tearDown(self):
        self.b.stop()

    def test_busy_lock_serves_last_copy(self):
        from ops import health
        snap = (time.time() - 100, 200, None, gzip.compress(b"<html>stara kopija</html>"))
        with mock.patch.object(heavy, "slot", return_value=contextlib.nullcontext(False)), \
                mock.patch.object(health, "container_free_mb", return_value=150.0), \
                mock.patch.object(self.pagecache, "_load_snap", return_value=snap) as ls, \
                mock.patch("subprocess.run") as sr, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(self.run_ui.build_in_child("/pregled"), (200, b"<html>stara kopija</html>"))
        sr.assert_not_called()                                   # no child next to the running heavy job
        ls.assert_called_once_with(("/pregled", "", None), stale_ok=True)   # also a copy from before a POST's clear()
        self.assertIn("brava zauzeta", out.getvalue())

    def test_busy_lock_with_free_memory_builds_beside_the_job(self):
        """9.11. 19:05: the lock guards memory; with 1.2 GB free the page must not wait behind run_dugo (29 min)."""
        from ops import health
        done = mock.Mock(returncode=0, stdout=b"<html>svjeze</html>", stderr=b"")
        with mock.patch.object(heavy, "slot", return_value=contextlib.nullcontext(False)), \
                mock.patch.object(health, "container_free_mb", return_value=1200.0), \
                mock.patch.object(self.pagecache, "_load_snap") as ls, \
                mock.patch("subprocess.run", return_value=done) as sr, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(self.run_ui.build_in_child("/pregled"), (200, b"<html>svjeze</html>"))
        sr.assert_called_once()
        ls.assert_not_called()
        self.assertIn("gradim /pregled bez brave", out.getvalue())

    def test_busy_lock_without_copy_is_503(self):
        from ops import health
        with mock.patch.object(heavy, "slot", return_value=contextlib.nullcontext(False)), \
                mock.patch.object(health, "container_free_mb", return_value=150.0), \
                mock.patch.object(self.pagecache, "_load_snap", return_value=None), \
                mock.patch("subprocess.run") as sr, contextlib.redirect_stdout(io.StringIO()):
            code, html = self.run_ui.build_in_child("/tokens")
        self.assertEqual(code, 503)
        self.assertIn("Pokušaj ponovno za minutu".encode(), html)
        sr.assert_not_called()

    def test_child_timeout_serves_last_copy(self):
        snap = (time.time() - 100, 200, None, gzip.compress(b"<html>x</html>"))
        with mock.patch.object(heavy, "slot", return_value=contextlib.nullcontext(True)), \
                mock.patch.object(self.pagecache, "_load_snap", return_value=snap), \
                mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("x", 300)), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(self.run_ui.build_in_child("/pregled"), (200, b"<html>x</html>"))
        self.assertIn("predugo", out.getvalue())

    def test_good_child_output_is_returned(self):
        class R:
            returncode, stdout, stderr = 0, b"<html>novo</html>", b""
        with mock.patch.object(heavy, "slot", return_value=contextlib.nullcontext(True)), \
                mock.patch("subprocess.run", return_value=R()):
            self.assertEqual(self.run_ui.build_in_child("/pregled"), (200, b"<html>novo</html>"))

    def test_503_carries_retry_after(self):
        """Review 9.11.: the "try again in a minute" answer tells the browser/proxy so too (deploy_wait does the same)."""
        h = self.run_ui.Handler.__new__(self.run_ui.Handler)
        h.headers, h.wfile, h.lang, h._public = {}, io.BytesIO(), "hr", True
        sent = {}
        h.send_response = lambda code: sent.setdefault("code", code)
        h.send_header = lambda k, v: sent.setdefault(k, v)
        h.end_headers = lambda: None
        h._send(503, b"<p>zauzeto</p>", translated=True)
        self.assertEqual((sent["code"], sent.get("Retry-After")), (503, "60"))
        sent.clear()
        h._send(200, b"<p>ok</p>", translated=True)
        self.assertNotIn("Retry-After", sent)

    def test_503_is_not_cached(self):
        """pagecache keeps only 200 answers, so the 503 never shadows a later good build."""
        from ui import pagecache
        key = ("/p33-test", "", None)
        with mock.patch.object(pagecache, "trim"):
            entry = pagecache._build(key, lambda: (503, b"zauzeto"))
        self.assertEqual(entry[1], 503)
        self.assertNotIn(key, pagecache._store)


class P63LightJobsAndQuietWaiters(unittest.TestCase):
    def test_market_and_usage_are_light(self):
        import run_sched
        jobs = {j[0]: j for j in run_sched.JOBS}
        for name in ("market", "usage", "masovno", "tokenstatus"):
            self.assertTrue(jobs[name][2][-1] is True, name)
        for name in ("shadow", "corr"):                 # still under the lock; since 9.11. 21:40 also night-only
            self.assertEqual(tuple(jobs[name][2][2:]), (False, True), name)
        self.assertTrue(jobs["postai"][2][-1] is True)   # 9.11. 21:40: waits on the Haiku API -> light, not behind the lock
        with mock.patch("subprocess.run") as sr, mock.patch("ops.heavy.run") as hr:
            sr.return_value.returncode = 0
            hr.return_value.returncode = 0
            run_sched.run("market", ["run_market.py", "collect"], light=True)
            run_sched.run("usage", ["run_usage.py", "tick"], light=True)
            self.assertEqual((sr.call_count, hr.call_count), (2, 0))

    def test_waiter_logs_after_2_min_then_every_10(self):
        self.assertEqual((heavy.WAIT_LOG_FIRST_S, heavy.WAIT_LOG_S), (120, 600))
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        clock = [1000.0]
        with mock.patch.object(heavy, "LOCK", os.path.join(tmp.name, "heavy.lock")), \
                mock.patch.object(heavy.time, "time", side_effect=lambda: clock[0]), \
                mock.patch.object(heavy.time, "sleep", side_effect=lambda s: clock.__setitem__(0, clock[0] + 30)), \
                mock.patch.object(heavy.fcntl, "flock", side_effect=BlockingIOError), \
                mock.patch.object(heavy, "_prio_waiting", return_value=False), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            with heavy.slot(wait=1500, label="test") as got:   # 25 min of waiting in 30 s steps
                self.assertFalse(got)
        lines = [ln for ln in out.getvalue().splitlines() if "čeka već" in ln]
        self.assertEqual(len(lines), 3, lines)     # at 2, 12 and 22 min; before: 12 lines (every 2 min)
        self.assertIn("2 min", lines[0])
        self.assertIn("12 min", lines[1])


if __name__ == "__main__":
    unittest.main()


class P33HeavyPagesNeverHang(unittest.TestCase):
    """9.11. 19:32: /ekipe (180 s) and /kol (30 s) built in the UI process pushed it to 818 MB -> memory watchdog ->
    Cloudflare 502 + deploy page for a minute; a heavy page without a copy hung the request 60-180 s. Now: HEAVY
    pages are built by a child in the background and the visitor gets the self-refreshing 503 at once."""

    def setUp(self):
        import run_ui
        from ui import pagecache
        self.run_ui, self.pagecache = run_ui, pagecache
        self.saved_store = dict(pagecache._store)
        pagecache._store.clear()

    def tearDown(self):
        self.pagecache._store.clear()
        self.pagecache._store.update(self.saved_store)

    def test_ekipe_and_kol_are_heavy_and_kept_on_disk(self):
        self.assertIn("/ekipe", self.run_ui.HEAVY)
        self.assertIn("/kol", self.run_ui.HEAVY)
        self.assertEqual(set(self.run_ui.SNAPSHOT_ONLY), {"/ekipe", "/kol"})
        with mock.patch.object(self.pagecache, "_snap_paths", set()):
            self.pagecache.snapshot(self.run_ui.SNAPSHOT_ONLY)
            self.assertIn("/ekipe", self.pagecache._snap_paths)

    def test_building_page_refreshes_itself_and_offers_autopilot(self):
        code, html = self.run_ui._building_html("/pregled")
        self.assertEqual(code, 503)
        self.assertIn(b'<head><meta http-equiv="refresh"', html)
        self.assertIn(b"/pravi-trade", html)
        self.assertIn("Pokušaj ponovno za minutu".encode(), html)

    def test_get_bg_returns_placeholder_then_the_page(self):
        key = ("/p33-bg", "", None)
        built = threading.Event()

        def build():
            built.set()
            return 200, b"<html>gotovo</html>"

        with mock.patch.object(self.pagecache, "trim"), \
                mock.patch.object(self.pagecache, "_load_snap", return_value=None):
            code, raw, gz = self.pagecache.get_bg(key, build, lambda: (503, b"<p>slaze se</p>"))
            self.assertEqual((code, raw, gz), (503, b"<p>slaze se</p>", None))
            self.assertTrue(built.wait(5))                       # the build ran, in the background
            for _ in range(200):                                 # ... and its result lands in the cache right after
                if key in self.pagecache._store:
                    break
                time.sleep(0.02)
            code, raw, gz = self.pagecache.get_bg(key, build, lambda: (503, b"nikad"))
        self.assertEqual(code, 200)
        self.assertEqual(gzip.decompress(gz), b"<html>gotovo</html>")

    def test_get_bg_serves_the_disk_copy_at_once(self):
        key = ("/p33-bg2", "", None)
        snap = (time.time() - 100, 200, None, gzip.compress(b"<html>kopija</html>"))
        with mock.patch.object(self.pagecache, "trim"), \
                mock.patch.object(self.pagecache, "_load_snap", return_value=snap), \
                mock.patch.object(self.pagecache, "_refresh") as rf:
            code, raw, gz = self.pagecache.get_bg(key, lambda: (200, b"novo"), lambda: (503, b"nikad"))
            time.sleep(0.05)
        self.assertEqual((code, gzip.decompress(gz)), (200, b"<html>kopija</html>"))
        rf.assert_called_once()                                  # ... and the fresh build was started behind it

    def test_save_snap_keeps_the_age_of_an_unchanged_copy(self):
        pc = self.pagecache
        with tempfile.TemporaryDirectory() as d, mock.patch.object(pc, "SNAP_DIR", d), \
                mock.patch.object(pc, "_snap_paths", {"/p33-snap"}):
            key = ("/p33-snap", "", None)
            pc._save_snap(key, gzip.compress(b"<html>a</html>"))
            f = pc._snap_file(key)
            old = time.time() - 3600
            os.utime(f, (old, old))
            pc._save_snap(key, gzip.compress(b"<html>a</html>"))   # the same page again (the old copy served)
            self.assertAlmostEqual(os.path.getmtime(f), old, delta=2)
            pc._save_snap(key, gzip.compress(b"<html>b</html>"))   # a new build does replace it
            self.assertGreater(os.path.getmtime(f), old + 100)


class WarmerAndChildPriority(unittest.TestCase):
    """9.11. 20:10: 1 CPU at 100 % (run_dugo + KOL round + the warmer's 22-45 s /pregled build every 5 min) and the
    visitor's requests waited. The warmer keeps a page younger than WARM_SKIP_FRESH_S; child builds run niced."""

    def setUp(self):
        import run_ui
        from ui import pagecache
        self.run_ui, self.pagecache = run_ui, pagecache
        self.saved_store = dict(pagecache._store)
        pagecache._store.clear()

    def tearDown(self):
        self.pagecache._store.clear()
        self.pagecache._store.update(self.saved_store)

    def test_warm_build_keeps_a_fresh_page(self):
        key = ("/pregled", "", None)
        self.pagecache._store[key] = (time.time() - 10, 200, None, gzip.compress(b"<html>svjeze</html>"))
        with mock.patch.object(self.run_ui, "build_in_child") as b:
            self.assertEqual(self.run_ui.warm_build("/pregled"), (200, b"<html>svjeze</html>"))
        b.assert_not_called()

    def test_warm_build_rebuilds_an_old_page(self):
        key = ("/pregled", "", None)
        self.pagecache._store[key] = (time.time() - 1000, 200, None, gzip.compress(b"<html>staro</html>"))
        with mock.patch.object(self.run_ui, "build_in_child", return_value=(200, b"<html>novo</html>")) as b:
            self.assertEqual(self.run_ui.warm_build("/pregled"), (200, b"<html>novo</html>"))
        b.assert_called_once_with("/pregled")
        with mock.patch.object(self.run_ui, "build_in_child", return_value=(200, b"<html>prvi</html>")) as b:
            self.pagecache._store.clear()                        # nothing cached yet (right after a deploy)
            self.assertEqual(self.run_ui.warm_build("/tokens"), (200, b"<html>prvi</html>"))
        b.assert_called_once_with("/tokens")

    def test_child_build_runs_niced(self):
        class R:
            returncode, stdout, stderr = 0, b"<html>x</html>", b""
        with mock.patch.object(heavy, "slot", return_value=contextlib.nullcontext(True)), \
                mock.patch("subprocess.run", return_value=R()) as sr:
            self.run_ui.build_in_child("/pregled")
        self.assertIs(sr.call_args.kwargs.get("preexec_fn"), self.run_ui._nice_child)
        with mock.patch("os.nice") as n:
            self.run_ui._nice_child()
        n.assert_called_once_with(self.run_ui.CHILD_NICE)
        self.assertGreater(self.run_ui.CHILD_NICE, 0)
        self.assertLess(self.run_ui.CHILD_NICE, heavy.NICE)      # below requests, above the heavy jobs


class NightWindow(unittest.TestCase):
    """9.11. 21:40 (Jure: "brave zakaži za iza ponoć"): heavy, non-urgent jobs run only in ops/heavy.NIGHT (Zagreb
    01-06); the KOL round does the light steps by day and the full set at night; start.sh waits with --night."""

    def _utc(self, h, m=0):
        import datetime as dt
        return dt.datetime(2026, 11, 9, h, m, tzinfo=dt.timezone.utc)   # CET: Zagreb = UTC + 1 in November

    def test_night_now_follows_the_zagreb_window(self):
        with mock.patch.object(heavy, "NIGHT", "0-6"):
            self.assertEqual(heavy.night_hours(), (0, 6))
            self.assertTrue(heavy.night_now(self._utc(23, 30)))    # 00:30 Zagreb
            self.assertTrue(heavy.night_now(self._utc(4, 59)))     # 05:59 Zagreb
            self.assertFalse(heavy.night_now(self._utc(5, 0)))     # 06:00 Zagreb: the window is to-exclusive
            self.assertFalse(heavy.night_now(self._utc(12, 0)))
        with mock.patch.object(heavy, "NIGHT", "22-6"):            # a window across midnight
            self.assertTrue(heavy.night_now(self._utc(21, 30)))    # 22:30 Zagreb
            self.assertFalse(heavy.night_now(self._utc(9, 0)))
        with mock.patch.object(heavy, "NIGHT", ""):                # no window: as before, any time
            self.assertIsNone(heavy.night_hours())
            self.assertTrue(heavy.night_now(self._utc(12, 0)))

    def test_main_accepts_night_and_waits(self):
        with mock.patch.object(heavy, "wait_for_night") as w, mock.patch.object(heavy, "run") as r:
            r.return_value = mock.Mock(returncode=0)
            heavy.main(["--night", "run_dugo.py", "once"])
        w.assert_called_once()
        self.assertEqual(r.call_args.args[0][1:], ["run_dugo.py", "once"])
        with mock.patch.object(heavy, "wait_for_night") as w, mock.patch.object(heavy, "run") as r:
            r.return_value = mock.Mock(returncode=0)
            heavy.main(["--prio", "--night", "run_kol.py", "backfill"])
        w.assert_called_once()
        self.assertTrue(r.call_args.kwargs.get("priority"))

    def test_sched_marks_the_learning_jobs_night_only(self):
        import run_sched
        with mock.patch.object(heavy, "night_now", return_value=False):
            self.assertTrue(run_sched.night_ok(False))
            self.assertFalse(run_sched.night_ok(True))
        jobs = {name: (fn.__name__, args) for name, fn, args in run_sched.JOBS}
        self.assertTrue(jobs["shadow"][1][-1] is True and jobs["corr"][1][-1] is True)        # night flag of every()
        self.assertTrue(jobs["learn6"][1][-1] is True and jobs["exits_rb"][1][-1] is True)    # night flag of every_hours()
        self.assertEqual(jobs["postai"][1][2], True)                                           # light, not behind the lock
        self.assertEqual(jobs["market"][1][2], True)
        import json
        self.assertEqual(json.load(open(os.path.join(ROOT, "learn/config.json")))["run_at_utc"], "02:30")  # 03:30 Zagreb
        self.assertEqual(json.load(open(os.path.join(ROOT, "exits/config.json")))["run_at_utc"], "03:30")

    def test_kol_round_is_light_by_day_and_full_at_night(self):
        import run_kol
        day, night = run_kol.round_steps(False), run_kol.round_steps(True)
        for s in ("cmd_collect", "cmd_chain", "cmd_xhook", "cmd_live", "cmd_snap", "cmd_converge", "cmd_crew"):
            self.assertIn(s, day)
        for s in ("cmd_score", "cmd_measure", "cmd_flows", "cmd_traces", "cmd_deleted"):
            self.assertNotIn(s, day)
            self.assertIn(s, night)
        for s in day + night:
            self.assertTrue(callable(getattr(run_kol, s)))
        with mock.patch.object(heavy, "night_now", return_value=False), mock.patch.dict(os.environ, {"KOL_FULL_ROUND": "1"}):
            self.assertIs(run_kol.round_steps(), run_kol.NIGHT_STEPS)
        with mock.patch.object(heavy, "night_now", return_value=False), mock.patch.dict(os.environ, {"KOL_FULL_ROUND": ""}):
            self.assertIs(run_kol.round_steps(), run_kol.DAY_STEPS)

    def test_start_sh_waits_for_the_night_on_the_heavy_loops(self):
        src = open(os.path.join(ROOT, "start.sh")).read()
        for job in ("run_calendar.py", "run_dex.py scan", "run_hype.py learn", "run_wallets.py harvest", "run_wallets.py score", "run_dugo.py once"):
            self.assertIn("ops.heavy --night " + job, src, job)
        for job in ("run_wallets.py dokazani", "rugfilter.archive", "ops.health --hourly"):   # fresh/short: stay by day
            self.assertNotIn("--night " + job, src, job)


class AutopilotMenuForAdmins(unittest.TestCase):
    """9.11. (Jure): the Autopilot is highlighted at the top of the menu for administrators and absent from the page
    everybody else receives (class adm-only, stripped server-side by ui/admstrip)."""

    def test_menu_has_the_admin_button_under_the_core_items(self):
        from ui import admstrip, html
        menu = html.side_menu("/pregled")
        self.assertIn('class="sec-ap adm-only"', menu)
        self.assertIn('href="/pravi-trade" class="ap"', menu)
        others = [i for i in (menu.find('<div class="sec"'), menu.find('<div class="sec ')) if i >= 0]
        self.assertLess(menu.index("sec-ap"), min(others))                        # before every other group
        self.assertEqual(menu.count("/pravi-trade"), 1)                           # no second, plain entry below
        self.assertNotIn("<h4>Autopilot</h4>", menu)
        self.assertIn('class="ap on"', html.side_menu("/pravi-trade"))
        stripped = admstrip.strip(menu)
        self.assertNotIn("/pravi-trade", stripped)                                # a non-admin's copy has no trace of it
        self.assertIn('href="/pregled"', stripped)                                # ... and keeps the rest of the menu
        self.assertIn("Autopilot", html.ADMIN)
        self.assertIn(".side .sec-ap a.ap", html.ADMIN_CSS)

    def test_map_page_marks_the_autopilot_group_admin_only(self):
        from ui import admstrip, html
        _, body = html.map_page()
        i = body.index("Autopilot</h2>")
        self.assertIn("adm-only", body[body.rfind("<h2", 0, i):i])
        self.assertNotIn("/pravi-trade", admstrip.strip(body))


class KolSearchRoundIsCheap(unittest.TestCase):
    """9.11. 22:00 (Jure: "nešto guši aplikaciju, ne učitava se"): Render metrics showed the one CPU at 100 % for
    30-47 min of every hour and every faulthandler dump of the KOL search round stood in discover.graph_candidates,
    whose NOT EXISTS ... LOWER() subquery scanned the calls table once per follows row. The same answer must now
    come from one index pass, and the UI must queue a burst of polls instead of refusing them (502)."""

    def test_candidates_skip_handles_that_posted_in_any_case_without_a_correlated_subquery(self):
        import inspect
        import sqlite3
        from kol import discover, store
        con = sqlite3.connect(":memory:")
        con.executescript(store.SCHEMA)
        con.execute(discover.FOLLOW_SCHEMA)
        for src in ("pro1", "pro2"):
            con.executemany("INSERT INTO follows VALUES (?,?,?,?,?)",
                            [(src, "HiddenGem", 1, 4000, "solana degen"), (src, "fresh1", 1, 4000, "memecoin calls"),
                             (src, "hoopsfan", 1, 9000, "basketball")])
        con.execute("INSERT INTO follows VALUES (?,?,?,?,?)", ("pro1", "lonely", 1, 4000, "crypto"))   # one follower
        con.execute("INSERT INTO calls (tweet_id, handle, token, ts, kind) VALUES (?,?,?,?,?)",
                    ("t1", "hiddengem", "CA1", 1, "call"))   # posted already, in another letter case
        cfg = {"discover": {"graph": {"min_followed_by": 2, "min_followers": 1000}}}
        self.assertEqual(discover.graph_candidates(con, cfg), ["fresh1"])
        src = "\n".join(l for l in inspect.getsource(discover.graph_candidates).splitlines() if not l.strip().startswith("#"))
        self.assertNotIn("NOT EXISTS", src)
        self.assertNotIn("LOWER(c.handle)", src)

    def test_ui_accept_backlog_is_deep(self):
        from http.server import ThreadingHTTPServer
        import run_ui  # noqa: F401 - sets the backlog at import
        self.assertGreaterEqual(ThreadingHTTPServer.request_queue_size, 64)


class PopupNeverPilesUp(unittest.TestCase):
    """9.11. 23:10 (Jure, screenshot: the Autopilot pop-up stays at "Učitavam…"): CPU at 100 % (KOL search round), the
    pop-up fired a request every second without waiting for the previous one, and every request read kol.db, tg.db
    (85 MB, no index on ts) and hype.db again. The scripts now keep one request in flight, the last hour of calls is
    read once and shared, and the time reads have an index."""

    def test_time_indexes_are_created_at_startup_and_by_the_owner_modules(self):
        import sqlite3
        import tempfile
        from ops import dbs
        from tg import store as tstore
        with tempfile.TemporaryDirectory() as d:
            hype, tg = os.path.join(d, "hype.db"), os.path.join(d, "tg.db")
            con = sqlite3.connect(hype)
            con.execute("CREATE TABLE kol_mentions (ts INTEGER, handle TEXT, ca TEXT, tickers TEXT, text TEXT)")
            con.execute("CREATE TABLE hype_signals (ts INTEGER, token TEXT, score REAL, mcap REAL, liquidity REAL, symbol TEXT)")
            con.commit()
            con.close()
            con = sqlite3.connect(tg)
            con.execute("CREATE TABLE posts (channel TEXT, post INTEGER, ts INTEGER, seen_ts INTEGER, text TEXT, cas TEXT, "
                        "tickers TEXT, views INTEGER, fwd_from TEXT, source TEXT, PRIMARY KEY (channel, post))")
            con.commit()
            con.close()
            dbs.ensure_indexes(hype, tg)
            con = sqlite3.connect(hype)
            plan = " ".join(r[3] for r in con.execute("EXPLAIN QUERY PLAN SELECT handle, ca, ts FROM kol_mentions "
                                                      "WHERE ts >= ? AND ca != ''", (0,)))
            con.close()
            self.assertIn("kol_mentions_ts", plan)
            con = sqlite3.connect(tg)
            plan = " ".join(r[3] for r in con.execute("EXPLAIN QUERY PLAN SELECT channel, ts, cas, fwd_from FROM posts "
                                                      "WHERE ts >= ? AND cas != ''", (0,)))
            con.close()
            self.assertIn("posts_ts", plan)
            dbs.ensure_indexes(os.path.join(d, "nema.db"), os.path.join(d, "nema2.db"))   # missing files: no error
        self.assertIn("posts_ts ON posts (ts)", tstore.SCHEMA)
        with open(os.path.join(ROOT, "hype", "sources.py"), encoding="utf-8") as f:
            self.assertIn("kol_mentions_ts ON kol_mentions (ts)", f.read())

    def test_events_are_read_once_and_shared_while_the_refresher_runs(self):
        from kol import converge
        from ui import pravitrade
        calls = []
        saved = (converge.events, pravitrade.BG_REFRESH, dict(pravitrade._EVENTS))

        def fake(now, window_s, **kw):
            calls.append(window_s)
            return [("TOK", now, "x", "caller", "call")], {}, {}
        converge.events = fake
        try:
            pravitrade._EVENTS.update(ts=0.0, ev=None)
            pravitrade.BG_REFRESH = True
            a = pravitrade._events_hour(1000)
            b = pravitrade._events_hour(1001)
            self.assertEqual(len(calls), 1)            # the second pop-up poll took the stored copy
            self.assertIs(a, b)
            pravitrade._events_hour(1002, fresh=True)   # the refresher thread always reads
            self.assertEqual(len(calls), 2)
            pravitrade._EVENTS["ts"] -= pravitrade.EVENTS_TTL_S + 1
            pravitrade._events_hour(1003)               # an old copy is not served
            self.assertEqual(len(calls), 3)
            pravitrade.BG_REFRESH = False               # tests / refresher off: every call reads the databases
            pravitrade._events_hour(1004)
            pravitrade._events_hour(1004)
            self.assertEqual(len(calls), 5)
        finally:
            converge.events, pravitrade.BG_REFRESH = saved[0], saved[1]
            pravitrade._EVENTS.clear()
            pravitrade._EVENTS.update(saved[2])

    def test_popups_do_not_read_the_databases_themselves(self):
        import inspect
        from ui import pravitrade
        for fn in (pravitrade.token_popup, pravitrade.crew_popup):
            src = inspect.getsource(fn)
            self.assertIn("_events_hour(now)", src)
            self.assertNotIn("converge.events(", src)

    def test_scripts_keep_one_request_in_flight(self):
        from ui import leaguedash, paper, pravitrade
        js = pravitrade.POP_JS
        self.assertIn("if(!url||cur===url)return", js)          # a tick while the previous request is out does nothing
        self.assertIn("AbortController", js)                    # ... and a request is given up after the timeout
        self.assertIn(str(pravitrade.POP_TIMEOUT_MS), js)
        self.assertIn("if(u!==url)return", js)                  # a late answer for a closed pop-up is dropped
        self.assertIn("server je spor", js)
        import sqlite3
        t = sqlite3.connect(":memory:")
        t.execute("CREATE TABLE orders (ts INTEGER)")
        saved = (pravitrade.log_html, pravitrade._sec)
        pravitrade.log_html, pravitrade._sec = (lambda tcon, cfg: ""), (lambda title, sub, body, sid=None: body)
        try:
            frag = pravitrade._log_section(t, {})
        finally:
            pravitrade.log_html, pravitrade._sec = saved
        # 10.11. (apui): the page's one poller (POLL_JS) moved from the log section to the end of the page, so a
        # log section that fails to build no longer takes every live box down with it
        # (tests/test_apui_offline.py checks the page carries it exactly once)
        self.assertNotIn("window.apTick", frag)
        self.assertIn("if(run||document.visibilityState!=='visible')return", pravitrade.POLL_JS)
        self.assertIn("finally{run=false}", pravitrade.POLL_JS)
        for mod in (paper, leaguedash):
            with open(mod.__file__, encoding="utf-8") as f:
                src = f.read()
            self.assertIn("busy=true", src)
            self.assertIn("finally{busy=false}", src)
