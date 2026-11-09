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
        snap = (time.time() - 100, 200, None, gzip.compress(b"<html>stara kopija</html>"))
        with mock.patch.object(heavy, "slot", return_value=contextlib.nullcontext(False)), \
                mock.patch.object(self.pagecache, "_load_snap", return_value=snap) as ls, \
                mock.patch("subprocess.run") as sr, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(self.run_ui.build_in_child("/pregled"), (200, b"<html>stara kopija</html>"))
        sr.assert_not_called()                                   # no child next to the running heavy job
        ls.assert_called_once_with(("/pregled", "", None), stale_ok=True)   # also a copy from before a POST's clear()
        self.assertIn("brava zauzeta", out.getvalue())

    def test_busy_lock_without_copy_is_503(self):
        with mock.patch.object(heavy, "slot", return_value=contextlib.nullcontext(False)), \
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
        for name in ("shadow", "corr", "postai"):       # still under the lock: they read big tables
            self.assertEqual(len(jobs[name][2]), 2, name)
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
