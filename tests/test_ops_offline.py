"""Housekeeping: disk guard, database upkeep (WAL, auto_vacuum, retention), health line, scheduler, and the
Pregled data read in SQL giving the same rows as reading every signal in Python."""
import contextlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ops import dbs, disk, health  # noqa: E402


class Disk(unittest.TestCase):
    def test_low_when_little_free(self):
        disk._last[:] = [0.0, None, 0.0]
        with mock.patch.object(disk, "free_mb", return_value=50.0), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertTrue(disk.low("test"))
        self.assertIn("preskačem", out.getvalue())
        disk._last[:] = [0.0, None, 0.0]
        with mock.patch.object(disk, "free_mb", return_value=5000.0):
            self.assertFalse(disk.low())

    def test_http_cache_skipped_when_low(self):
        from event_calendar import http
        with tempfile.TemporaryDirectory() as d, mock.patch.object(disk, "low", return_value=True):
            p = os.path.join(d, "x.json")
            http._write(p, "{}")
            self.assertFalse(os.path.exists(p))


class Dbs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = mock.patch.object(disk, "DATA_DIR", self.tmp.name)
        self.p.start()
        con = sqlite3.connect(os.path.join(self.tmp.name, "hype.db"))
        con.execute("CREATE TABLE apify_cache (key TEXT PRIMARY KEY, ts INTEGER, items TEXT)")
        now = int(time.time())
        con.execute("INSERT INTO apify_cache VALUES ('old', ?, ?)", (now - 30 * 86400, "[1]" * 1000))
        con.execute("INSERT INTO apify_cache VALUES ('new', ?, '[]')", (now,))
        con.commit()
        con.close()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def test_startup_retention_wal_vacuum(self):
        with contextlib.redirect_stdout(io.StringIO()):
            dbs.startup()
        con = sqlite3.connect(os.path.join(self.tmp.name, "hype.db"))
        self.assertEqual([k for (k,) in con.execute("SELECT key FROM apify_cache")], ["new"])
        self.assertEqual(con.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertEqual(con.execute("PRAGMA auto_vacuum").fetchone()[0], 2)
        con.close()
        with contextlib.redirect_stdout(io.StringIO()) as out:   # second start: nothing to rewrite
            dbs.startup()
            dbs.hourly()
        self.assertIn("sažeto: ništa", out.getvalue())

    def test_health_line(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            health.line(tables=True)
        self.assertIn("zdravlje: RAM", out.getvalue())
        self.assertIn("hype.db", out.getvalue())


class League(unittest.TestCase):
    def test_columns_added_once(self):
        from league import store
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "l.db")
            store.connect(p).close()
            con = store.connect(p)
            cols = {r[1] for r in con.execute("PRAGMA table_info(trades)")}
            self.assertTrue({"entry_mcap", "realized", "auto_state"} <= cols)
            seen = []
            con.set_trace_callback(seen.append)
            store._migrate(con)        # already done in this process: no ALTER, not even a table_info
            con.close()
            self.assertFalse([q for q in seen if "ALTER" in q or "table_info" in q])


class Scheduler(unittest.TestCase):
    def test_daily_runs_once_per_day(self):
        import run_sched
        calls = []
        sleeps = [0]

        def sleep(_):
            sleeps[0] += 1
            if sleeps[0] >= 3:
                raise KeyboardInterrupt

        with mock.patch.object(run_sched, "run", side_effect=lambda n, a: calls.append(n)), \
                mock.patch.object(run_sched.time, "sleep", side_effect=sleep):
            with self.assertRaises(KeyboardInterrupt):
                run_sched.daily("learn", ["run_learn.py", "fit"], "learn/config.json")
        self.assertLessEqual(len(calls), 1)   # three checks in one day, at most one fit

    def test_jobs_point_at_real_commands(self):
        import run_sched
        for name, _, args in run_sched.JOBS:
            self.assertTrue(os.path.exists(os.path.join(ROOT, args[0][0])), name)


class SignalSummary(unittest.TestCase):
    """data.signal_summary + latest_details + rug_latest give token_rows exactly what the old full read gave."""

    def test_same_as_full_read(self):
        from ui import data
        with tempfile.TemporaryDirectory() as d:
            hype, cal, rug = (os.path.join(d, n) for n in ("hype.db", "calendar.db", "rug.db"))
            for p in (hype, cal):
                c = sqlite3.connect(p)
                c.execute("CREATE TABLE hype_signals (ts INTEGER, token TEXT, symbol TEXT, name TEXT, pair TEXT, url TEXT,"
                          " score REAL, price REAL, mcap REAL, liquidity REAL, features TEXT, sources TEXT, weights TEXT,"
                          " PRIMARY KEY (token, ts))")
                c.execute("CREATE TABLE hype_details (token TEXT, ts INTEGER, extra TEXT, PRIMARY KEY (token, ts))")
                c.commit()
                c.close()
            c = sqlite3.connect(hype)
            rows = [(100 + i, f"T{i % 7}", f"S{i % 7}", None, None, None, (i * 13) % 90, 1.0, 1000 + i, 500 + i,
                     json.dumps({"i": i}), "x", "{}") for i in range(60)]
            c.executemany("INSERT INTO hype_signals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            c.executemany("INSERT INTO hype_details VALUES (?,?,?)", [(f"T{i % 7}", i, json.dumps({"n": i})) for i in range(30)])
            c.commit()
            c.close()
            c = sqlite3.connect(cal)   # legacy file: one duplicate key (dropped) and one older token
            c.execute("INSERT INTO hype_signals VALUES (159,'T3','old',NULL,NULL,NULL,99,1,1,1,'{}','x','{}')")
            c.execute("INSERT INTO hype_signals VALUES (50,'Z','Z',NULL,NULL,NULL,10,1,1,1,'{}','x','{}')")
            c.commit()
            c.close()
            c = sqlite3.connect(rug)
            c.execute("CREATE TABLE rug_reports (mint TEXT, checked_at INTEGER, symbol TEXT, verdict TEXT, data TEXT)")
            c.executemany("INSERT INTO rug_reports VALUES (?,?,?,?,?)",
                          [("T1", 5, "a", "OK", '{"v": 1}'), ("T1", 9, "a", "ODBAČEN", '{"v": 2}'), ("T2", 1, "b", "OK", "{}")])
            c.commit()
            c.close()
            with mock.patch.dict(data.GROUPS, {"hype": [hype, cal], "rug": [rug]}), \
                    mock.patch.object(data, "HYPE_DB", hype):
                for limit in (50000, 40):
                    old = {}
                    for s in data.hype_signals(limit=limit):
                        r = old.setdefault(s["token"], {"last": s, "first_ts": s["ts"], "max": 0})
                        r["first_ts"] = min(r["first_ts"], s["ts"])
                        r["max"] = max(r["max"], s["score"] or 0)
                        if s["ts"] > r["last"]["ts"]:
                            r["last"] = s
                    new, recent = data.signal_summary(limit=limit, recent_since=120)
                    self.assertEqual(set(new), set(old))
                    for t in old:
                        o = dict(old[t]["last"])
                        o.pop("weights")
                        self.assertEqual(new[t]["last"], o, t)
                        self.assertEqual((new[t]["first_ts"], new[t]["max"]), (old[t]["first_ts"], old[t]["max"]), t)
                    want = sorted((s["token"], s["ts"], s["mcap"], s["liquidity"])
                                  for s in data.hype_signals(limit=limit) if s["ts"] >= 120)
                    self.assertEqual(sorted(recent), want)
                dets = {}
                for r in data.q(hype, "SELECT token, ts, extra FROM hype_details ORDER BY ts DESC"):
                    dets.setdefault(r["token"], json.loads(r["extra"]))
                self.assertEqual(data.latest_details(), dets)
                old_rug = {}
                for r in data.rug_reports():
                    old_rug.setdefault(r["mint"], r)
                self.assertEqual(data.rug_latest(), old_rug)


if __name__ == "__main__":
    unittest.main()
