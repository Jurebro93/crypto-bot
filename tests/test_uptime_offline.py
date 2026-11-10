"""Availability check (ops/uptime.py, 10.11.): what counts as an answer, a deploy or a failure, when the dashboard
process is ended and when not (failure span, grace after a start, cooldown, the UI process only), and that /healthz
stays cheap. No network: the HTTP tests talk to small servers on 127.0.0.1 inside this process."""
import http.server
import os
import signal
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ops import cpuguard, uptime  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def fake_proc(root, procs, uptime_s=5000.0):
    """A /proc tree: {pid: {"argv": [...], "start": ticks since boot, "comm": "python3", "cwd": here}}."""
    write(os.path.join(root, "uptime"), f"{uptime_s:.2f} 1.00\n")
    for pid, p in procs.items():
        d = os.path.join(root, str(pid))
        write(os.path.join(d, "stat"), f"{pid} ({p.get('comm', 'python3')}) S 1 1 1 0 -1 0 0 0 0 0 5 5 0 0 20 0 1 0 "
                                       f"{p.get('start', 0)} 0 0\n")
        with open(os.path.join(d, "cmdline"), "wb") as f:
            f.write(b"\0".join(a.encode() for a in p["argv"]) + b"\0")
        os.symlink(p.get("cwd", os.getcwd()), os.path.join(d, "cwd"))
    return root


class Clock:
    def __init__(self, t=10_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class Script:
    """Stands in for uptime.check: answers from a list, each answer taking `took` seconds of the fake clock."""

    def __init__(self, clock, answers):
        self.clock, self.answers = clock, list(answers)

    def __call__(self, port):
        status, took = self.answers.pop(0) if self.answers else ("ok", 0.01)
        self.clock.sleep(took)
        return status, took, {"ok": "u redu", "deploy": "deploy u tijeku", "fail": "isteklo vrijeme"}[status]


def watch(answers, procs=((4242, 9999.0),), restart=True, started_ago=10_000.0):
    """A Watch on a fake clock; the check, the process list and os.kill are recordings. Its start lies `started_ago`
    seconds back (default: long out of the grace period)."""
    clock = Clock()
    kills, logs = [], []
    w = uptime.Watch(10000, check=Script(clock, answers), ui_procs=lambda: list(procs),
                     kill=lambda pid, sig: kills.append((clock(), pid, sig)), clock=clock, sleep=clock.sleep,
                     log=logs.append, restart=restart)
    w.started -= started_ago
    return w, kills, logs, clock


def run(w, n):
    w.run(steps=n)


class Failures(unittest.TestCase):
    def test_one_failure_is_a_log_line_not_a_restart(self):
        w, kills, logs, clock = watch([("fail", 5.0), ("ok", 0.1)])
        run(w, 2)
        self.assertEqual(kills, [])
        self.assertTrue(any("ne odgovara (isteklo vrijeme, 5.0 s), 1. put zaredom" in ln for ln in logs), logs)
        self.assertTrue(any("opet odgovara" in ln for ln in logs), logs)
        self.assertEqual((w.fails, w.fail_since), (0, None))

    def test_restart_only_after_failures_spanning_150_s(self):
        # every 30 s, 5 s timeouts: sent at 0, 30, 60, 90, 120 (span 125 s) -> wait; at 150 (span 155 s) -> restart
        w, kills, logs, clock = watch([("fail", 5.0)] * 5)
        run(w, 5)
        self.assertEqual(kills, [])
        self.assertEqual(w.fails, 5)
        w.check.answers = [("fail", 5.0)]
        run(w, 1)
        self.assertEqual([(pid, sig) for _, pid, sig in kills], [(4242, signal.SIGTERM)])
        self.assertGreaterEqual(clock() - (w.fail_since or 0), uptime.FAIL_SPAN_S)

    def test_refused_at_once_counts_the_same_way(self):
        w, kills, logs, clock = watch([("fail", 0.0)] * 6)
        run(w, 6)                                                      # sent at 0 ... 150: span exactly 150 s
        self.assertEqual(len(kills), 1)

    def test_a_good_answer_in_between_starts_the_count_again(self):
        w, kills, logs, clock = watch([("fail", 5.0)] * 4 + [("ok", 0.2)] + [("fail", 5.0)] * 4)
        run(w, 9)
        self.assertEqual(kills, [])
        self.assertEqual(w.fails, 4)

    def test_a_deploy_is_not_an_outage(self):
        """deploy_wait.py holds the port while run_ui.py loads: its 503 marked X-MemeSonar-Deploy is no failure."""
        w, kills, logs, clock = watch([("fail", 5.0)] * 4 + [("deploy", 0.01)] * 10 + [("fail", 5.0)] * 2)
        run(w, 16)
        self.assertEqual(kills, [])
        self.assertEqual(sum("deploy u tijeku" in ln for ln in logs), 1)   # one line per deploy, not every 30 s
        self.assertEqual(w.n_fail, 6)

    def test_the_clear_line_comes_before_the_signal(self):
        order = []
        w, kills, logs, clock = watch([("fail", 5.0)] * 6)
        w.log = lambda s: order.append(("log", s))
        w.kill = lambda pid, sig: order.append(("kill", pid))
        run(w, 6)
        i = order.index(("kill", 4242))
        self.assertIn("gasim samo proces sučelja (pid 4242)", order[i - 1][1])
        self.assertIn("ostale petlje i trade se ne diraju", order[i - 1][1])

    def test_a_kill_that_fails_is_logged_and_the_loop_goes_on(self):
        w, kills, logs, clock = watch([("fail", 5.0)] * 7)

        def gone(pid, sig):
            raise ProcessLookupError(pid)
        w.kill = gone
        run(w, 7)
        self.assertTrue(any("nije ugašen" in ln for ln in logs), logs)
        self.assertEqual(w.fails, 7)

    def test_an_error_inside_a_check_does_not_end_the_loop(self):
        w, kills, logs, clock = watch([])
        w.check = mock.Mock(side_effect=[RuntimeError("pokvareno"), ("ok", 0.1, "u redu")])
        run(w, 2)
        self.assertTrue(any("greška u provjeri, nastavljam (RuntimeError: pokvareno)" in ln for ln in logs))
        self.assertEqual(w.check.call_count, 2)

    def test_slow_answers_are_logged_with_the_time(self):
        w, kills, logs, clock = watch([("ok", 2.5), ("ok", 0.3)])
        run(w, 2)
        slow = [ln for ln in logs if "spor" in ln]
        self.assertEqual(len(slow), 1)
        self.assertRegex(slow[0], r"odgovor nakon 2\.5 s, \d\d:\d\d:\d\d UTC$")
        self.assertEqual(w.n_slow, 1)

    def test_checks_come_every_30_s(self):
        w, kills, logs, clock = watch([("ok", 0.5)] * 4)
        t0 = clock()
        run(w, 4)
        self.assertAlmostEqual(clock() - t0, 4 * uptime.EVERY_S)

    def test_hourly_summary(self):
        w, kills, logs, clock = watch([("ok", 0.1)] * 119 + [("fail", 5.0)] + [("ok", 0.1)] * 5)
        run(w, 125)
        summaries = [ln for ln in logs if "zadnjih" in ln]
        self.assertEqual(len(summaries), 1, logs)
        self.assertIn("zadnjih 60 min, provjera: 121, bez odgovora: 1, sporih: 0", summaries[0])   # at 0, 30 ... 3600 s


class WhenNotToRestart(unittest.TestCase):
    def test_not_in_the_first_5_minutes_after_the_check_started(self):
        w, kills, logs, clock = watch([("fail", 5.0)] * 6, started_ago=0)
        run(w, 6)                                                       # 155 s after the start: still the grace period
        self.assertEqual(kills, [])
        self.assertTrue(any("prvih 5 min nakon starta" in ln for ln in logs), logs)
        w.check.answers = [("fail", 5.0)] * 5
        run(w, 5)                                                       # past 300 s: now it may
        self.assertEqual(len(kills), 1)

    def test_not_a_dashboard_process_that_is_itself_still_starting(self):
        w, kills, logs, clock = watch([("fail", 5.0)] * 6, procs=[(77, 120.0)])
        run(w, 6)
        self.assertEqual(kills, [])
        self.assertTrue(any("radi tek 120 s" in ln for ln in logs), logs)

    def test_at_most_once_in_15_minutes(self):
        w, kills, logs, clock = watch([("fail", 5.0)] * 60)
        run(w, 60)                                                      # 30 min of failures
        times = [t for t, _, _ in kills]
        self.assertEqual(len(times), 2, times)                          # at ~155 s and 15 min later, not every check
        self.assertGreaterEqual(times[1] - times[0], uptime.COOLDOWN_S)
        self.assertTrue(any("sljedeći put najranije za" in ln for ln in logs))

    def test_switched_off_only_logs(self):
        w, kills, logs, clock = watch([("fail", 5.0)] * 20, restart=False)
        run(w, 20)
        self.assertEqual(kills, [])
        self.assertTrue(any("UPTIME_RESTART=0" in ln for ln in logs))
        self.assertIn("samo bilježim", logs[0])

    def test_env_switch(self):
        import importlib
        try:
            with mock.patch.dict(os.environ, {"UPTIME_RESTART": "0"}):
                self.assertFalse(importlib.reload(uptime).RESTART)
            with mock.patch.dict(os.environ, {"UPTIME_RESTART": "1"}):
                self.assertTrue(importlib.reload(uptime).RESTART)
        finally:
            importlib.reload(uptime)

    def test_no_dashboard_process_no_signal(self):
        w, kills, logs, clock = watch([("fail", 5.0)] * 6, procs=[])
        run(w, 6)
        self.assertEqual(kills, [])
        self.assertTrue(any("procesa sučelja nema" in ln for ln in logs))

    def test_unreadable_process_list_no_signal(self):
        w, kills, logs, clock = watch([("fail", 5.0)] * 6)
        w.ui_procs = mock.Mock(side_effect=PermissionError("proc"))
        run(w, 6)
        self.assertEqual(kills, [])
        self.assertTrue(any("popis procesa se ne da pročitati" in ln for ln in logs))


class OnlyTheDashboard(unittest.TestCase):
    """Only run_ui.py itself, from our folder: never a page-build child, the trade loop or another folder's app."""

    def test_ui_procs_picks_the_dashboard_only(self):
        tck = cpuguard.CLK_TCK
        proc = fake_proc(tempfile.mkdtemp(), {
            101: {"argv": ["python3", "run_ui.py", "--host", "0.0.0.0", "--port", "10000"], "start": 1000 * tck},
            102: {"argv": ["python3", "/app/run_ui.py", "--render", "/pregled"], "start": 4900 * tck},
            103: {"argv": ["python3", "run_trade.py", "follow"], "start": 1000 * tck},
            104: {"argv": ["python3", "deploy_wait.py", "--port", "10000"]},
            105: {"argv": ["python3", "run_ui.py", "--port", "1"], "cwd": tempfile.mkdtemp()},   # not ours
            106: {"argv": ["bash", "start.sh"], "comm": "bash"},
            107: {"argv": ["python3", "-m", "ops.uptime"]},
        }, uptime_s=5000.0)
        got = uptime.ui_procs(proc)
        self.assertEqual([pid for pid, _ in got], [101])
        self.assertAlmostEqual(got[0][1], 4000.0, delta=1)              # 5000 s up, started at 1000 s

    def test_the_real_watch_signals_only_that_pid(self):
        tck = cpuguard.CLK_TCK
        proc = fake_proc(tempfile.mkdtemp(), {
            201: {"argv": ["python3", "run_ui.py", "--port", "10000"], "start": 100 * tck},
            202: {"argv": ["python3", "run_ui.py", "--render", "/tokeni"], "start": 100 * tck},
            203: {"argv": ["python3", "run_trade.py", "follow"], "start": 100 * tck},
        })
        w, kills, logs, clock = watch([("fail", 5.0)] * 6)
        w.ui_procs = lambda: uptime.ui_procs(proc)
        run(w, 6)
        self.assertEqual([(pid, sig) for _, pid, sig in kills], [(201, signal.SIGTERM)])


class Quiet(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve(handler):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    return srv


class RealAnswers(unittest.TestCase):
    """uptime.check against small servers on 127.0.0.1."""

    def answer(self, code, headers=(), delay=0.0):
        class H(Quiet):
            def do_GET(self):
                time.sleep(delay)
                self.send_response(code)
                for k, v in headers:
                    self.send_header(k, v)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")
        srv = serve(H)
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return srv.server_address[1]

    def test_ok(self):
        status, took, what = uptime.check(self.answer(200))
        self.assertEqual((status, what), ("ok", "u redu"))
        self.assertLess(took, 2)

    def test_error_code_is_a_failure(self):
        self.assertEqual(uptime.check(self.answer(500))[::2], ("fail", "odgovor 500"))
        self.assertEqual(uptime.check(self.answer(503))[::2], ("fail", "odgovor 503"))   # 503 without the deploy mark

    def test_nobody_on_the_port(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        self.assertEqual(uptime.check(port)[::2], ("fail", "na portu nitko ne sluša"))

    def test_no_answer_in_time(self):
        status, took, what = uptime.check(self.answer(200, delay=1.0), timeout=0.2)
        self.assertEqual((status, what), ("fail", "isteklo vrijeme"))
        self.assertLess(took, 0.9)

    def test_deploy_stand_in_is_a_deploy(self):
        """The real deploy_wait.py handler: /healthz is 503 with X-MemeSonar-Deploy, read as "deploy"."""
        import deploy_wait
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), deploy_wait.Wait)
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        self.assertEqual(uptime.check(srv.server_address[1])[::2], ("deploy", "deploy u tijeku"))

    def test_healthz_of_the_dashboard_is_cheap(self):
        """run_ui.py answers /healthz before any page logic: no database, no login, no cache. A health check that
        waited behind a locked database would end a healthy server."""
        import sqlite3
        import run_ui
        opened = []

        def no_db(*a, **kw):
            opened.append(a)
            raise sqlite3.OperationalError("database is locked")
        for auth in (True, False):
            with mock.patch.object(run_ui, "AUTH", auth), mock.patch("sqlite3.connect", no_db), \
                    mock.patch.object(run_ui.pagecache, "_load_snap", side_effect=AssertionError("cache")):
                srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), run_ui.Handler)
                srv.daemon_threads, srv.verbose = True, False   # as run_ui.main sets them
                threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
                try:
                    status, took, what = uptime.check(srv.server_address[1])
                finally:
                    srv.shutdown()
                    srv.server_close()
            self.assertEqual((status, what), ("ok", "u redu"), auth)
        self.assertEqual(opened, [])

    def test_once_from_the_shell(self):
        port = self.answer(200)
        with mock.patch("builtins.print") as out:
            self.assertEqual(uptime.main(["--once", "--port", str(port)]), 0)
        self.assertIn("dostupnost: ok", out.call_args[0][0])


class StartSh(unittest.TestCase):
    def test_web_service_only_and_supervised(self):
        with open(os.path.join(ROOT, "start.sh"), encoding="utf-8") as f:
            sh = f.read()
        self.assertIn('if [ -n "${PORT:-}" ]; then keep uptime python3 -m ops.uptime; fi', sh)
        self.assertLess(sh.index("keep ui python3 run_ui.py"), sh.index("keep uptime python3 -m ops.uptime"))
        # the ui supervisor brings the process back after the SIGTERM: keep restarts whatever ends, after 30 s
        self.assertIn('echo "nadzor: $name završio (izlaz $code), ponovno za 30 s"', sh)


if __name__ == "__main__":
    unittest.main()
