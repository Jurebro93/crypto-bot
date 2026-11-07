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


class Slim(unittest.TestCase):
    """hype_signals slimming keeps what every reader uses: weights of the newest row, features of the first and
    newest row, all numbers; compaction then gives the space back."""

    def test_slim_and_compact(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(disk, "DATA_DIR", d):
            p = os.path.join(d, "hype.db")
            c = sqlite3.connect(p)
            from hype import store
            c.executescript(store.SCHEMA)
            now = int(time.time())
            w = json.dumps({f"k{i}": i for i in range(60)})
            rows = []
            for t in ("A", "B"):
                for i in range(400):
                    ts = now - 3 * 86400 + i * 600
                    rows.append((ts, t, t, t, "p", "u", float(i % 90), 1.0, 1000.0 + i, 500.0,
                                 json.dumps({"i": i, "pad": "x" * 9000}), "dex", w * 20))
            c.executemany("INSERT INTO hype_signals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            c.commit()
            before = c.execute("SELECT token, ts, score, price, mcap, liquidity, sources FROM hype_signals ORDER BY token, ts").fetchall()
            c.close()
            size0 = os.path.getsize(p)
            nw, nf = dbs.slim_signals(p, now=now, batch=150)
            self.assertEqual(nw, 2 * 399)
            c = sqlite3.connect(p)
            self.assertEqual(c.execute("SELECT token, ts, score, price, mcap, liquidity, sources FROM hype_signals ORDER BY token, ts").fetchall(), before)
            for t in ("A", "B"):
                first, last = c.execute("SELECT MIN(ts), MAX(ts) FROM hype_signals WHERE token=?", (t,)).fetchone()
                got = dict(c.execute("SELECT ts, features FROM hype_signals WHERE token=? AND features IS NOT NULL", (t,)).fetchall())
                self.assertIn(first, got)
                self.assertIn(last, got)
                self.assertTrue(all(ts >= now - dbs.SLIM_FEATURES_H * 3600 for ts in got if ts not in (first, last)))
                self.assertEqual([r[0] for r in c.execute("SELECT ts FROM hype_signals WHERE token=? AND weights IS NOT NULL", (t,))], [last])
            c.close()
            with mock.patch.object(disk, "free_mb", return_value=5.0):     # data disk too full for an in-place VACUUM
                self.assertIsNone(dbs.compact(p))                             # online: skipped
            free = lambda path=None: 10000.0 if path else 30.0  # noqa: E731  tmp has room, data disk only for the packed copy
            with mock.patch.object(disk, "free_mb", side_effect=free):
                out = dbs.compact(p, offline=True)
            self.assertIn("privremenog", out)
            self.assertLess(os.path.getsize(p), size0 / 2)
            c = sqlite3.connect(p)
            self.assertEqual(c.execute("SELECT token, ts, score, price, mcap, liquidity, sources FROM hype_signals ORDER BY token, ts").fetchall(), before)
            self.assertEqual(c.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(c.execute("PRAGMA quick_check").fetchone()[0], "ok")
            c.close()
            with mock.patch.object(disk, "free_mb", return_value=10000.0):
                self.assertIsNone(dbs.compact(p))                             # packed now: nothing left to win


class TtlCache(unittest.TestCase):
    def test_cached_value_is_a_copy(self):
        from ui import data
        calls = []
        f = lambda: calls.append(1) or {"a": [1, 2]}  # noqa: E731
        data._TTL.pop("t", None)
        import tempfile
        saved, data.TTL_DIR = data.TTL_DIR, tempfile.mkdtemp()   # no file left by an earlier run
        self.addCleanup(setattr, data, "TTL_DIR", saved)
        self.assertEqual(data.ttl_cache("t", 60, f), {"a": [1, 2]})
        v = data.ttl_cache("t", 60, f)
        v["a"].append(3)                       # a page changing its copy does not change the cache
        self.assertEqual(data.ttl_cache("t", 60, f), {"a": [1, 2]})
        self.assertEqual(len(calls), 1)

    def test_json_not_pickle_and_types_round_trip(self):
        """Audit 4.11. §4.3: no pickle.loads from the shared cache dir; tuples, sets and int keys survive."""
        from ui import data
        import inspect
        self.assertNotIn("pickle.loads", inspect.getsource(data))
        v = {"a": (1, 2), "s": {3}, 5: [b"x", float("inf")], "__x": 1}
        self.assertEqual(data._loads(data._dumps(v)), v)


class MallocArenaTest(unittest.TestCase):
    def test_start_sh_limits_malloc_arenas_before_any_python(self):
        """Two glibc arenas per process (1.11.: the threaded UI grew to ~200 MB and the 512 MB server ran out)."""
        sh = open(os.path.join(os.path.dirname(__file__), "..", "start.sh")).read()
        i = sh.index('export MALLOC_ARENA_MAX="${MALLOC_ARENA_MAX:-2}"')
        self.assertLess(i, sh.index("python3 "))


class ShortProcessRoundsTest(unittest.TestCase):
    """1.11.: long loops hand a round's memory back by running it in a child process."""

    def test_kol_loop_runs_each_round_as_a_child(self):
        import argparse
        import run_kol
        calls = []

        class Stop(Exception):
            pass

        def fake_sleep(s):
            raise Stop

        with mock.patch("subprocess.run", side_effect=lambda args, **kw: calls.append(args)), \
                mock.patch.object(run_kol.store, "connect", side_effect=RuntimeError("no db")), \
                mock.patch.object(run_kol.time, "sleep", side_effect=fake_sleep):
            with self.assertRaises(Stop):
                run_kol.cmd_loop(argparse.Namespace(every=20, verbose=False))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][-1], "once")
        self.assertTrue(calls[0][1].endswith("run_kol.py"))

    def test_paper_scan_runs_as_a_child(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "run_paper.py")).read()
        self.assertNotIn("run_hype.main(hype_args)", src)
        self.assertIn('"run_hype.py")]', src)


class UiChildRenderTest(unittest.TestCase):
    def test_warm_pages_are_built_in_a_child(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "run_ui.py")).read()
        self.assertIn('pagecache.warm(list(WARM), build_in_child', src)
        import run_ui
        self.assertEqual(run_ui.HEAVY, ("/tokens", "/tokens/jaki", "/pregled"))
        self.assertTrue(set(run_ui.WARM) <= set(run_ui.HEAVY))
        self.assertIn("build_in_child(path)) if path in HEAVY", src)

    def test_child_failure_falls_back_to_building_here(self):
        import run_ui

        class R:
            returncode, stdout, stderr = 1, b"", b"boom"
        with mock.patch("subprocess.run", return_value=R()), \
                mock.patch.object(run_ui, "build", return_value=(200, b"here")) as b:
            self.assertEqual(run_ui.build_in_child("/"), (200, b"here"))
        b.assert_called_once_with("/", {})


class HeavyLockTest(unittest.TestCase):
    """2.11.: heavy children run one after another (ops/heavy.py)."""

    def setUp(self):
        from ops import heavy
        self.heavy = heavy
        self.tmp = tempfile.mkdtemp()
        self.p = mock.patch.object(heavy, "LOCK", os.path.join(self.tmp, "heavy.lock"))
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_second_holder_is_skipped_or_waits(self):
        import subprocess
        script = ("import sys,time;sys.path.insert(0,%r);from ops import heavy;heavy.LOCK=%r\n"
                  "with heavy.slot() as g:\n print('in',flush=True);time.sleep(3)") % (
            os.path.join(os.path.dirname(__file__), ".."), self.heavy.LOCK)
        child = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE)
        self.assertEqual(child.stdout.readline().strip(), b"in")
        self.assertIsNone(self.heavy.run([sys.executable, "-c", "pass"], wait=0))
        t0 = time.time()
        r = self.heavy.run([sys.executable, "-c", "pass"])     # blocks until the other one ends
        self.assertEqual(r.returncode, 0)
        self.assertGreater(time.time() - t0, 0.5)
        child.wait()

    def test_cli_runs_scripts_and_modules(self):
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)) as run:
            self.heavy.main(["run_x.py", "a"])
            self.heavy.main(["-m", "ops.health", "--hourly"])
        self.assertEqual(run.call_args_list[0][0][0], [sys.executable, "run_x.py", "a"])
        self.assertEqual(run.call_args_list[1][0][0], [sys.executable, "-m", "ops.health", "--hourly"])

    def test_wired_in(self):
        root = os.path.join(os.path.dirname(__file__), "..")
        sh = open(os.path.join(root, "start.sh")).read()
        for cmd in ("run_wallets.py score", "run_calendar.py", "run_dex.py scan", "run_dugo.py once", "rugfilter.archive"):
            self.assertIn("python3 -m ops.heavy " + ("-m " if "." in cmd.split()[0] and not cmd.endswith(".py") and "run_" not in cmd else "") + cmd, sh)
        self.assertIn("heavy.run(", open(os.path.join(root, "run_sched.py")).read())
        self.assertIn("heavy.run(", open(os.path.join(root, "run_kol.py")).read())
        self.assertIn("heavy.run(cmd, wait=0", open(os.path.join(root, "run_paper.py")).read())
        self.assertIn("heavy.slot(wait=60, label=", open(os.path.join(root, "run_ui.py")).read())


class HeavyPriorityTest(unittest.TestCase):
    """6.11.: a priority waiter (the KOL backfill) goes before other waiters; its ticket never outlives it."""

    def setUp(self):
        from ops import heavy
        self.heavy = heavy
        self.tmp = tempfile.mkdtemp()
        self.p = mock.patch.object(heavy, "LOCK", os.path.join(self.tmp, "heavy.lock"))
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_others_step_aside_while_a_priority_ticket_waits(self):
        open(self.heavy._prio_path(), "w").write("1")          # someone with priority is queueing
        self.assertIsNone(self.heavy.run([sys.executable, "-c", "pass"], wait=0))   # a normal caller skips
        r = self.heavy.run([sys.executable, "-c", "pass"], priority=True)           # the priority caller goes
        self.assertEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(self.heavy._prio_path()))                     # ticket cleaned up
        self.assertEqual(self.heavy.run([sys.executable, "-c", "pass"], wait=0).returncode, 0)

    def test_stale_ticket_is_ignored(self):
        open(self.heavy._prio_path(), "w").write("1")
        old = time.time() - self.heavy.PRIO_MAX_AGE - 10
        os.utime(self.heavy._prio_path(), (old, old))
        self.assertEqual(self.heavy.run([sys.executable, "-c", "pass"], wait=0).returncode, 0)

    def test_start_sh_gives_the_backfill_priority(self):
        root = os.path.join(os.path.dirname(__file__), "..")
        self.assertIn("python3 -m ops.heavy --prio run_kol.py backfill", open(os.path.join(root, "start.sh")).read())


class SchedLightTest(unittest.TestCase):
    """7.11.: masovno (17 min of GeckoTerminal waiting per pass) runs outside the heavy lock; the others inside."""

    def test_masovno_light_others_locked(self):
        import run_sched
        jobs = {j[0]: j for j in run_sched.JOBS}
        self.assertTrue(jobs["masovno"][2][-1])
        self.assertTrue(jobs["tokenstatus"][2][-1])
        self.assertEqual(len(jobs["shadow"][2]), 2)
        with mock.patch("subprocess.run") as sr, mock.patch("ops.heavy.run") as hr:
            sr.return_value.returncode = 0
            hr.return_value.returncode = 0
            run_sched.run("masovno", ["run_learn.py", "masovno"], light=True)
            self.assertEqual((sr.call_count, hr.call_count), (1, 0))
            run_sched.run("tokenstatus", ["run_hype.py", "status"])
            self.assertEqual((sr.call_count, hr.call_count), (1, 1))
