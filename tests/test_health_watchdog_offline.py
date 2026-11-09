"""Memory watchdog (ops/health.py, 9.11.): one runaway process is stopped before Render kills the whole service."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ops import health  # noqa: E402


class Watchdog(unittest.TestCase):
    def test_only_the_runaway_process_is_stopped(self):
        procs = [(11, "ui", 1644.0), (12, "kol", 84.0), (13, "trade", 900.0), (14, "ui-dijete", 810.0), (15, "trade", 1300.0)]
        killed, logs = [], []
        hit = health.watchdog(800, procs=procs, kill=killed.append, log=lambda *a, **k: logs.append(a[0]))
        self.assertEqual([p for p, _, _ in hit], [11, 14, 15])     # trade gets 1.5× room: 900 stays, 1300 goes
        self.assertEqual(killed, [11, 14, 15])
        self.assertIn("keep ga vraća", logs[0])
        self.assertEqual(health.watchdog(800, procs=[(1, "ui", 120.0)], kill=killed.append), [])
        self.assertEqual(len(killed), 3)

    def test_kill_failure_is_logged_not_raised(self):
        def boom(pid):
            raise OSError("gone")
        logs = []
        health.watchdog(800, procs=[(9, "paper", 2000.0)], kill=boom, log=lambda *a, **k: logs.append(a[0]))
        self.assertTrue(any("nije ugašen" in l for l in logs))

    def test_process_list_runs_here(self):
        procs = health.process_list()
        self.assertTrue(all(isinstance(p, int) and mb >= 0 for p, _n, mb in procs))
        self.assertEqual(health.processes(), sorted(health.processes(), key=lambda x: -x[1]))


if __name__ == "__main__":
    unittest.main()
