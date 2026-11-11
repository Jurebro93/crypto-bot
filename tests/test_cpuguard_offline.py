"""CPU guard (ops/cpuguard.py, 10.11.): the container's CPU from fake cgroup files, who may be paused and who never,
the bounds of a pause, and that nothing is ever left stopped. No network; the signals are a recording fake, except
one test that ends a real guard twin with SIGKILL."""
import collections
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ops import cpuguard as g  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def fake_proc(root, procs, uptime=5000.0):
    """A /proc tree: {pid: {"argv": [...], "state": "S", "ticks": 0, "start": 0, "comm": "python3", "cwd": here}}."""
    write(os.path.join(root, "uptime"), f"{uptime:.2f} 1.00\n")
    for pid, p in procs.items():
        d = os.path.join(root, str(pid))
        ticks = p.get("ticks", 0)
        # pid (name) state ppid pgrp session tty tpgid flags minflt cminflt majflt cmajflt utime stime cutime cstime
        # priority nice threads itrealvalue starttime ...
        write(os.path.join(d, "stat"), f"{pid} ({p.get('comm', 'python3')}) {p.get('state', 'S')} 1 1 1 0 -1 0 0 0 0 0 "
                                       f"{ticks - ticks // 3} {ticks // 3} 0 0 20 0 1 0 {p.get('start', 0)} 0 0\n")
        with open(os.path.join(d, "cmdline"), "wb") as f:
            f.write(b"\0".join(a.encode() for a in p["argv"]) + b"\0")
        link = os.path.join(d, "cwd")
        if os.path.islink(link):
            os.remove(link)
        os.symlink(p.get("cwd", os.getcwd()), link)
    return root


class Clock:
    """A clock that only moves when somebody sleeps."""

    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class Kills:
    """Stands in for os.kill: writes down (clock, pid, signal)."""

    def __init__(self, clock, fail=()):
        self.clock, self.fail, self.log = clock, set(fail), []

    def __call__(self, pid, sig):
        if pid in self.fail:
            raise ProcessLookupError(pid)
        self.log.append((self.clock(), pid, sig))

    def of(self, sig):
        return [pid for _, pid, s in self.log if s == sig]


class FakeMeter:
    source, cpus, throttled = "proba", 1.0, 0

    def __init__(self, readings):
        self.readings = list(readings)

    def read(self):
        return self.readings.pop(0) if self.readings else None


class FakeProcs:
    def __init__(self, procs, proc=None, moved=()):
        self.procs, self.proc, self.moved = procs, proc or tempfile.mkdtemp(), set(moved)

    def scan(self):
        return list(self.procs)

    def same(self, p):
        return p.pid not in self.moved

    def ours(self, p):
        return True


def P(pid, name, rank, pct, state="S"):
    return g.P(pid, 1, name, rank, "", pct, 0.0, state)


UI, TRADE, KOL = P(11, "ui", g.PROTECTED, 97.0), P(12, "trade", g.PROTECTED, 30.0), P(13, "kol", g.PROTECTED, 40.0)
DUGO, WALLETS, PAGE = P(21, "dugo", g.JOBS, 60.0), P(22, "wallets", g.JOBS, 35.0), P(23, "ui-dijete", g.PAGES, 80.0)


def guard(readings, procs, on=True, fail=(), moved=(), **kw):
    clock = Clock()
    kills = Kills(clock, fail)
    logs = []
    gd = g.Guard(meter=FakeMeter(readings), procs=FakeProcs(procs, moved=moved), kill=kills, sleep=clock.sleep, clock=clock,
                 log=logs.append, on=on, high=90, low=80, window=3, **kw)
    return gd, kills, logs, clock


class ContainerCpu(unittest.TestCase):
    """The percentage is of what the CONTAINER may use: its quota, not the host's cores."""

    def setUp(self):
        self.root, self.proc, self.clock = tempfile.mkdtemp(), tempfile.mkdtemp(), Clock()

    def meter(self, **kw):
        return g.Meter(root=self.root, proc=self.proc, clock=self.clock, **kw)

    def v2(self, usec, quota="100000 100000", throttled=None):
        write(os.path.join(self.root, "cpu.stat"), f"usage_usec {usec}\nuser_usec 1\nsystem_usec 1\n"
              + (f"nr_periods 9\nnr_throttled {throttled}\nthrottled_usec 5\n" if throttled is not None else ""))
        if quota is not None:
            write(os.path.join(self.root, "cpu.max"), quota + "\n")

    def v1(self, nsec, quota=100000, period=100000, d="cpuacct"):
        write(os.path.join(self.root, d, "cpuacct.usage"), f"{nsec}\n")
        write(os.path.join(self.root, "cpu", "cpu.cfs_quota_us"), f"{quota}\n")
        write(os.path.join(self.root, "cpu", "cpu.cfs_period_us"), f"{period}\n")
        write(os.path.join(self.root, "cpu", "cpu.stat"), "nr_periods 3\nnr_throttled 2\nthrottled_time 9\n")

    def procstat(self, busy, idle, cpus=2):
        t = f"cpu  {busy} 0 0 {idle} 0 0 0 0 0 0\n" + "".join(f"cpu{i} 1 0 0 1 0 0 0 0 0 0\n" for i in range(cpus))
        write(os.path.join(self.proc, "stat"), t + "intr 1 2 3\nctxt 5\n")

    def test_v2_one_cpu_quota(self):
        self.v2(10_000_000)
        m = self.meter()
        self.assertIsNone(m.read())                      # the first reading has nothing to compare with
        self.clock.sleep(1)
        self.v2(10_900_000)                              # 0.9 s of CPU in 1 s on a 1-CPU quota
        self.assertAlmostEqual(m.read(), 90.0)
        self.assertEqual((m.source, m.cpus, m.cpus_from), ("cgroup v2", 1.0, "kvota"))
        self.clock.sleep(2)
        self.v2(11_900_000)                              # 1.0 s of CPU in 2 s
        self.assertAlmostEqual(m.read(), 50.0)

    def test_v2_half_and_two_cpus(self):
        self.v2(0, "50000 100000")
        m = self.meter()
        m.read()
        self.clock.sleep(1)
        self.v2(450_000, "50000 100000")                 # 0.45 s on half a CPU is 90 %, not 45
        self.assertAlmostEqual(m.read(), 90.0)
        self.assertEqual(m.cpus, 0.5)
        self.clock.sleep(1)
        self.v2(1_450_000, "200000 100000")              # the plan grew to 2 CPUs: 1 s of CPU is half of it
        self.assertAlmostEqual(m.read(), 50.0)

    def test_v2_quota_max_uses_the_cpus_we_may_run_on(self):
        self.v2(0, "max 100000")
        with mock.patch.object(g, "own_cpus", return_value=4):
            m = self.meter()
            m.read()
            self.clock.sleep(1)
            self.v2(1_000_000, "max 100000")             # one busy core of four
            self.assertAlmostEqual(m.read(), 25.0)
            self.assertEqual((m.cpus, m.cpus_from), (4, "jezgre koje vidim, kvote nema"))   # said in the start line
        self.v2(1_000_000, quota=None)                   # no cpu.max at all reads the same way
        os.remove(os.path.join(self.root, "cpu.max"))
        self.assertEqual(g.read_v2(self.root)[1], None)

    def test_cores_override_wins(self):
        self.v2(0, "max 100000")
        m = self.meter(cores=2)
        m.read()
        self.clock.sleep(1)
        self.v2(1_000_000, "max 100000")
        self.assertAlmostEqual(m.read(), 50.0)
        self.assertEqual(m.cpus_from, "zadano ručno")

    def test_v1_cpuacct(self):
        self.v1(5_000_000_000)
        m = self.meter()
        m.read()
        self.clock.sleep(1)
        self.v1(5_800_000_000)                           # nanoseconds: 0.8 s of CPU
        self.assertAlmostEqual(m.read(), 80.0)
        self.assertEqual((m.source, m.cpus), ("cgroup v1", 1.0))
        self.assertEqual(g.read_v1(self.root)[2], 2)     # nr_throttled

    def test_v1_without_a_quota(self):
        self.v1(0, quota=-1)
        with mock.patch.object(g, "own_cpus", return_value=2):
            m = self.meter()
            m.read()
            self.clock.sleep(1)
            self.v1(1_000_000_000, quota=-1)
            self.assertAlmostEqual(m.read(), 50.0)

    def test_proc_stat_is_the_last_resort(self):
        tck = g.CLK_TCK
        self.procstat(busy=1000, idle=5000)
        m = self.meter()
        m.read()
        self.clock.sleep(1)
        self.procstat(busy=1000 + tck, idle=5000 + tck)  # one of the two CPUs busy for the second
        self.assertAlmostEqual(m.read(), 50.0)
        self.assertIn("/proc/stat", m.source)
        self.assertEqual((m.cpus, m.cpus_from), (2, "jezgre cijelog stroja"))

    def test_order_v2_then_v1_then_proc(self):
        self.procstat(1, 1)
        self.assertIn("/proc/stat", (lambda m: (m.read(), m.source))(self.meter())[1])
        self.v1(1)
        self.assertEqual((lambda m: (m.read(), m.source))(self.meter())[1], "cgroup v1")
        self.v2(1)
        self.assertEqual((lambda m: (m.read(), m.source))(self.meter())[1], "cgroup v2")

    def test_iowait_is_not_busy(self):
        write(os.path.join(self.proc, "stat"), "cpu  100 20 30 1000 400 5 5 0 0 0\ncpu0 1 1 1 1 1 1 1 1 1 1\n")
        used, cpus, thr = g.read_procstat(self.proc)
        self.assertAlmostEqual(used, 160 / g.CLK_TCK)    # user+nice+system+irq+softirq, without idle and iowait
        self.assertEqual((cpus, thr), (1, None))

    def test_throttle_periods_are_counted(self):
        self.v2(0, throttled=4)
        m = self.meter()
        m.read()
        self.clock.sleep(1)
        self.v2(100, throttled=11)
        m.read()
        self.assertEqual(m.throttled, 7)

    def test_two_readings_a_moment_apart_are_not_a_percentage(self):
        self.v2(0)
        m = self.meter()
        m.read()
        self.clock.sleep(0.01)
        self.v2(10_000)                                  # one 10 ms tick in 10 ms would read as 100 %
        self.assertIsNone(m.read())
        self.clock.sleep(0.99)
        self.v2(500_000)
        self.assertAlmostEqual(m.read(), 50.0)           # measured from the first reading, which was kept

    def test_nothing_readable_is_none_not_an_error(self):
        m = self.meter()
        self.assertIsNone(m.read())
        self.assertIsNone(m.read())
        self.assertIsNone(m.source)
        write(os.path.join(self.root, "cpu.stat"), "nešto drugo\n")
        self.assertIsNone(self.meter().read())

    def test_percent(self):
        self.assertAlmostEqual(g.percent((0, 0.0), (2, 1.9), 1), 95.0)
        self.assertIsNone(g.percent((5, 0.0), (5, 1.0), 1))
        self.assertEqual(g.percent((0, 5.0), (1, 4.0), 1), 0.0)   # a counter that went back is not negative CPU


class WhoIsWho(unittest.TestCase):
    """The protected list comes from start.sh: every python command there is classified on purpose."""

    def kind(self, cmd, cpu_s=0.0):
        return g.classify(["python3"] + cmd.split(), cpu_s)[:2]

    def test_money_path_is_protected(self):
        # audit sekundni.md §4 "Nikad ne pauzirati": run_trade, run_ui, run_live, run_tg; plus the supervisors, the
        # deploy stand-in, the two checks and the memory watchdog (when in doubt, protected)
        for cmd, name in (("run_ui.py --host 0.0.0.0 --port 10000", "ui"), ("run_trade.py follow", "trade"),
                          ("run_kol.py loop --every 20", "kol"), ("run_tg.py loop", "tg"), ("run_tg.py telethon", "tg"),
                          ("run_live.py loop", "live"),
                          ("deploy_wait.py --port 10000", "deploy"), ("-m ops.cpuguard", "cpuguard"),
                          ("-m ops.uptime", "uptime"), ("-m ops.health --hourly", "health"), ("-m ops.health", "health"),
                          ("-m ops.health --quiet", "health"), ("run_sched.py", "sched"),
                          ("/app/run_trade.py follow", "trade"), ("-u /srv/app/run_ui.py --port 1", "ui")):
            self.assertEqual(self.kind(cmd), (name, g.PROTECTED), cmd)

    def test_demo_loop_waits_only_while_it_does_not_feed_the_real_trade(self):
        """Audit §4: run_paper may wait "dok je follow_paper zaključan"; the day the lock goes, it is protected."""
        from trade import settings
        self.assertIn("follow_paper", settings.LOCKED)                       # today: locked
        self.assertEqual(self.kind("run_paper.py run --scan --hype-args --deep 20"), ("paper", g.SCANS))
        with mock.patch.dict(settings.LOCKED, clear=True):
            self.assertEqual(g._paper_rank(), g.PROTECTED)
        import builtins
        real = builtins.__import__

        def broken(name, *a, **kw):
            if name.split(".")[0] == "trade":
                raise ImportError(name)
            return real(name, *a, **kw)
        with mock.patch("builtins.__import__", broken):                     # unreadable: the safe side
            self.assertEqual(g._paper_rank(), g.PROTECTED)

    def test_the_wrapper_is_not_the_job_it_wraps(self):
        self.assertEqual(self.kind("-m ops.heavy --night run_dugo.py once"), ("heavy", g.PROTECTED))
        self.assertEqual(self.kind("run_dugo.py once"), ("dugo", g.JOBS))
        self.assertEqual(self.kind("-m ops.heavy -m ops.health --hourly"), ("heavy", g.PROTECTED))
        self.assertEqual(self.kind("-m rugfilter.archive"), ("rug-arhiva", g.JOBS))

    def test_background_ranks_follow_the_audit(self):
        """Audit §4 "Smije čekati, ovim redom": page builds, hype scan and demo, KOL jobs, the scheduler's jobs and
        the rest, run_top last."""
        for cmd, name, rank in (("run_ui.py --render /pregled", "ui-dijete", g.PAGES),
                                ("run_hype.py scan --top 3", "hype", g.SCANS), ("run_hype.py learn --auto 5", "hype", g.SCANS),
                                ("run_kol.py minute-loop", "minute", g.ROUNDS),
                                ("run_kol.py backfill --budget 28", "backfill", g.ROUNDS),
                                ("run_hype.py status", "hype-status", g.JOBS),
                                ("run_learn.py masovno", "learn", g.JOBS), ("run_exits.py rollback", "exits", g.JOBS),
                                ("run_wallets.py score --credits 6000", "wallets", g.JOBS),
                                ("run_report.py loop", "report", g.JOBS), ("run_simianx.py once", "simianx", g.JOBS),
                                ("run_watch.py run", "watch", g.JOBS), ("-m rugfilter.archive", "rug-arhiva", g.JOBS),
                                ("run_top.py once", "top", g.LAST),
                                ("run_nesto.py x", "nesto", g.JOBS), ("-c import time", "-c", g.JOBS)):
            self.assertEqual(self.kind(cmd), (name, rank), cmd)
        self.assertEqual(g.classify(["python3", "run_nesto.py", "x"])[2], g.OTHER_WHY)
        self.assertLess(g.PAGES, g.SCANS)
        self.assertLess(g.SCANS, g.ROUNDS)
        self.assertLess(g.ROUNDS, g.JOBS)
        self.assertLess(g.JOBS, g.LAST)

    def test_kol_round_is_protected_until_it_computes(self):
        for cmd in ("run_kol.py once", "run_kol.py --verbose search-round", "-X faulthandler run_kol.py once"):
            self.assertEqual(self.kind(cmd), ("kol-krug", g.PROTECTED), cmd)
            self.assertEqual(self.kind(cmd, g.ROUND_CPU_S), ("kol-krug", g.PROTECTED), cmd)
            self.assertEqual(self.kind(cmd, g.ROUND_CPU_S + 1), ("kol-krug", g.ROUNDS), cmd)   # scoring, or a runaway query
        self.assertEqual(self.kind("run_kol.py loop", 10 ** 6), ("kol", g.PROTECTED))           # the supervisor: always

    def test_not_python_is_not_ours(self):
        for argv in (["bash", "start.sh"], ["sleep", "3600"], ["nice", "-n", "10", "python3", "x.py"], []):
            self.assertIsNone(g.classify(argv))
        self.assertEqual(g.parse(["/usr/local/bin/python3.13", "run_x.py", "a"]), ("run_x.py", ["a"]))

    def test_every_python_command_in_start_sh_is_on_the_list(self):
        """Whoever adds a loop to start.sh decides here whether it may be paused; nothing falls through by accident."""
        with open(os.path.join(ROOT, "start.sh"), encoding="utf-8") as f:
            sh = f.read()
        code = "\n".join(ln.split(" #")[0] for ln in sh.splitlines() if not ln.strip().startswith("#"))
        script = r"((?:-m [\w.]+)|(?:\w+\.py))"
        # 10.11.: also what runs behind "python3 -m ops.heavy [--night] [--prio]" (calendar, dex, wallets, dugo ...)
        cmds = set(re.findall(r"python3 " + script, code)) | set(re.findall(r"ops\.heavy(?: --\w+)* " + script, code))
        self.assertGreaterEqual(len(cmds), 20)
        for c in ("run_calendar.py", "run_wallets.py", "run_dugo.py", "-m rugfilter.archive", "run_hype.py"):
            self.assertIn(c, cmds)
        self.check_listed(cmds)

    def check_listed(self, cmds):
        listed = {script for _, script, _, _, _ in g.PROCESSES}
        self.assertEqual(sorted(c for c in cmds if c not in listed), [])
        for c in cmds:
            self.assertNotEqual(g.classify(["python3"] + c.split())[2], g.OTHER_WHY, c)

    def test_every_job_of_the_scheduler_and_the_loops_children_is_on_the_list(self):
        """The processes start.sh does not start itself: run_sched's jobs, the KOL round, the hype scan, page builds."""
        found = set()
        for path in ("run_sched.py", "run_corr.py", "ui/jobs.py"):
            with open(os.path.join(ROOT, path), encoding="utf-8") as f:
                found |= set(re.findall(r'"(run_\w+\.py)"', f.read()))
        self.assertGreaterEqual(len(found), 6)
        self.check_listed(found)
        for argv, name in ((["run_kol.py", "once"], "kol-krug"), (["run_kol.py", "search-round"], "kol-krug"),
                           (["run_hype.py", "scan"], "hype"), (["run_ui.py", "--render", "/tokeni"], "ui-dijete")):
            self.assertEqual(g.classify(["python3"] + argv)[0], name)

    def test_every_reason_is_written_down(self):
        for name, script, words, rank, why in g.PROCESSES:
            self.assertIn(rank, (g.PROTECTED, g.ROUND, g.PAGES, g.SCANS, g.ROUNDS, g.JOBS, g.LAST), name)
            self.assertGreater(len(why), 15, name)
            self.assertNotIn("\u2014", why)
        text = g.popis()
        for name in ("ui", "trade", "kol", "tg", "live", "deploy", "health", "cpuguard"):
            self.assertRegex(text, rf"\n  {name} +\S.* +zaštićen ", name)
        self.assertRegex(text, r"\n  ui-dijete +run_ui.py --render +1\. u redu ")
        self.assertRegex(text, r"\n  top +run_top.py +5\. u redu ")
        self.assertRegex(text, r"\n  kol-krug +run_kol.py +krug ")


class Processes(unittest.TestCase):
    def setUp(self):
        self.proc, self.clock = tempfile.mkdtemp(), Clock()
        self.me = os.getpid()

    def tree(self, **over):
        procs = {
            101: {"argv": ["python3", "run_ui.py", "--port", "1"], "ticks": 1000},
            102: {"argv": ["python3", "/app/run_dugo.py", "once"], "ticks": 500, "start": 77},
            103: {"argv": ["bash", "start.sh"], "comm": "bash", "ticks": 900},
            104: {"argv": ["sleep", "60"], "comm": "sleep"},
            self.me: {"argv": ["python3", "-m", "ops.cpuguard"], "ticks": 5},
        }
        for pid, ch in over.items():
            procs[int(pid[1:])].update(ch)
        return fake_proc(self.proc, procs)

    def test_stat_line_with_brackets_and_spaces_in_the_name(self):
        write(os.path.join(self.proc, "7", "stat"), "7 (py thon) x) T 1 1 1 0 -1 0 0 0 0 0 40 2 0 0 20 0 1 0 314 0 0\n")
        self.assertEqual(g.proc_stat(7, self.proc), ("py thon) x", "T", 42, 314))

    def test_scan_measures_each_python_process(self):
        self.tree()
        pr = g.Procs(proc=self.proc, clock=self.clock, window=3)
        first = {p.pid: p for p in pr.scan()}
        self.assertEqual(sorted(first), [101, 102])                    # not bash, not sleep, not this process
        self.assertEqual((first[101].name, first[101].rank), ("ui", g.PROTECTED))
        self.assertEqual((first[102].name, first[102].rank, first[102].start), ("dugo", g.JOBS, 77))
        self.assertEqual(first[102].pct, 0.0)                          # one sample is not a rate yet
        self.clock.sleep(1)
        self.tree(p102={"ticks": 500 + g.CLK_TCK // 2})                # half a second of CPU in one second
        second = {p.pid: p for p in pr.scan()}
        self.assertAlmostEqual(second[102].pct, 50.0, delta=1.5)
        self.assertEqual(second[101].pct, 0.0)
        self.assertAlmostEqual(second[102].cpu_s, (500 + g.CLK_TCK // 2) / g.CLK_TCK)

    def test_rate_is_over_the_window_and_the_dead_are_forgotten(self):
        self.tree()
        pr = g.Procs(proc=self.proc, clock=self.clock, window=2)
        pr.scan()
        for add in (g.CLK_TCK, g.CLK_TCK, 0, 0):                       # busy, busy, idle, idle
            self.clock.sleep(1)
            self.tree(p102={"ticks": self.ticks(102) + add})
            pct = {p.pid: p.pct for p in pr.scan()}[102]
        self.assertEqual(pct, 0.0)                                     # the two idle seconds are the whole window now
        import shutil
        shutil.rmtree(os.path.join(self.proc, "102"))
        self.assertEqual([p.pid for p in pr.scan()], [101])
        self.assertEqual([k[0] for k in pr.hist], [101])

    def ticks(self, pid):
        return g.proc_stat(pid, self.proc)[2]

    def test_same_tells_a_reused_pid(self):
        self.tree()
        pr = g.Procs(proc=self.proc, clock=self.clock)
        p = {p.pid: p for p in pr.scan()}[102]
        self.assertTrue(pr.same(p))
        self.tree(p102={"start": 99999})                               # the pid now belongs to a newer process
        self.assertFalse(pr.same(p))
        self.assertFalse(pr.same(p._replace(pid=555)))                  # gone

    def test_ours_is_what_runs_from_this_folder(self):
        self.tree(p102={"cwd": tempfile.mkdtemp()})
        self.assertTrue(g.ours(101, self.proc))
        self.assertFalse(g.ours(102, self.proc))                       # somebody else's python on the same machine
        self.assertFalse(g.ours(999, self.proc))

    def test_sweep_continues_only_stopped_python_of_ours(self):
        self.tree(p101={"state": "T"}, p102={"state": "T", "cwd": tempfile.mkdtemp()}, p103={"state": "T"})
        got = []
        self.assertEqual(g.sweep(kill=lambda pid, sig: got.append((pid, sig)), proc=self.proc), [101])
        self.assertEqual(got, [(101, signal.SIGCONT)])
        self.tree(p101={"state": "S"})
        self.assertEqual(g.sweep(kill=lambda *a: self.fail("nothing stands"), proc=self.proc), [])

    def test_sweep_survives_a_process_that_ended(self):
        self.tree(p101={"state": "T"})

        def gone(pid, sig):
            raise ProcessLookupError(pid)
        self.assertEqual(g.sweep(kill=gone, proc=self.proc), [])


class Victims(unittest.TestCase):
    def test_protected_is_never_chosen(self):
        c = g.candidates([UI, TRADE, KOL, DUGO])
        self.assertEqual([p.name for p in c], ["dugo"])                 # the UI at 97 % stays where it is
        self.assertEqual(g.candidates([UI, TRADE, KOL]), [])
        for level in (0.1, 0.5, 5.0):
            self.assertEqual(g.plan(level, g.candidates([UI, TRADE, KOL])), [])

    def test_audit_order_first_then_the_biggest_consumer(self):
        """Audit sekundni.md §4: page builds first, run_top last; inside one rank the biggest consumer first."""
        top = P(24, "top", g.LAST, 95.0)
        hype = P(25, "hype", g.SCANS, 20.0)
        minute = P(26, "minute", g.ROUNDS, 50.0)
        c = g.candidates([top, PAGE, minute, UI, WALLETS, hype, DUGO])
        self.assertEqual([p.name for p in c], ["ui-dijete", "hype", "minute", "dugo", "wallets", "top"])
        pl = g.plan(g.ceiling(len(c)), c)
        self.assertEqual([p.name for p, _ in pl], [p.name for p in c])
        self.assertEqual([s for _, s in pl], sorted((s for _, s in pl), reverse=True))   # the first stands longest

    def test_idle_stopped_and_foreign_processes_are_left_alone(self):
        idle = P(31, "report", g.JOBS, g.MIN_CPU - 0.1)
        standing = P(32, "hype", g.SCANS, 50.0, state="T")
        zombie = P(33, "hype", g.SCANS, 50.0, state="Z")
        self.assertEqual(g.candidates([idle, standing, zombie]), [])
        self.assertEqual(g.candidates([DUGO, WALLETS], ours=lambda p: p.pid != 21), [WALLETS])

    def test_brake_goes_up_above_high_down_below_low_and_holds_between(self):
        self.assertAlmostEqual(g.next_level(0.2, 95, 2, 90, 80), 0.2 + g.STEP_UP)
        self.assertAlmostEqual(g.next_level(0.2, 85, 2, 90, 80), 0.2)
        self.assertAlmostEqual(g.next_level(0.2, 90, 2, 90, 80), 0.2)             # exactly the threshold is not above it
        self.assertAlmostEqual(g.next_level(0.2, 70, 2, 90, 80), 0.2 - g.STEP_DOWN)
        self.assertEqual(g.next_level(0.01, 10, 2, 90, 80), 0.0)
        self.assertEqual(g.next_level(0.3, 99, 0, 90, 80), 0.0)                   # nobody to pause: no brake wound up
        self.assertAlmostEqual(g.next_level(9.0, 99, 3, 90, 80), g.ceiling(3))
        self.assertAlmostEqual(g.ceiling(3), g.MAX_DUTY + 2 * g.JOIN)

    def test_plan_biggest_stands_longest_the_next_joins_later(self):
        c = g.candidates([DUGO, WALLETS, PAGE])
        self.assertEqual(g.plan(0.0, c), [])
        one = g.plan(0.1, c)
        self.assertEqual([(p.name, round(s, 3)) for p, s in one], [("ui-dijete", 0.05)])   # page builds first (audit)
        three = g.plan(0.35, c)
        self.assertEqual([p.name for p, _ in three], ["ui-dijete", "dugo", "wallets"])
        self.assertEqual([round(s, 3) for _, s in three], [0.175, 0.125, 0.075])

    def test_duty_cycle_bounds(self):
        """Whatever the brake says: a pause is never over half a second (nor over MAX_DUTY of a slot), and the rest
        of the slot, in which the process runs, is never shorter than RUN_MIN_S."""
        many = [P(100 + i, f"job{i}", g.JOBS, 90.0 - i) for i in range(12)]
        for n in (1, 2, 5, 12):
            for level in (0.01, 0.05, 0.1, 0.33, 0.5, 0.9, 2.0, 50.0):
                pl = g.plan(level, many[:n])
                self.assertLessEqual(len(pl), n)
                for _, s in pl:
                    self.assertGreaterEqual(s, g.MIN_PAUSE_S)
                    self.assertLessEqual(s, g.MAX_DUTY * g.SLOT_S + 1e-9)
                    self.assertLessEqual(s, 0.5)
                    self.assertGreaterEqual(g.SLOT_S - s, g.RUN_MIN_S - 1e-9)
        self.assertLessEqual(g.SLOT_S, 0.5)
        self.assertLessEqual(g.MAX_DUTY, 1 - g.RUN_MIN_S / g.SLOT_S)
        self.assertEqual(g.TICK_S / g.SLOT_S, int(g.TICK_S / g.SLOT_S))

    def test_env_numbers_stay_inside_their_bounds(self):
        with mock.patch.dict(os.environ, {"X_HI": "500", "X_LO": "-3", "X_BAD": "devedeset", "X_EMPTY": ""}):
            self.assertEqual(g._env("X_HI", 90, 20, 100), 100)
            self.assertEqual(g._env("X_LO", 90, 20, 100), 20)
            self.assertEqual(g._env("X_BAD", 90, 20, 100), 90)
            self.assertEqual(g._env("X_EMPTY", 90, 20, 100), 90)
        self.assertLessEqual(g.CPU_LOW, g.CPU_HIGH)


class Settles(unittest.TestCase):
    """The brake on a model of the container: CPU-bound background jobs (each can fill the 1-CPU quota alone) next
    to a protected load. Pauses are nested at the start of a slot, the kernel caps every moment at 100 %."""

    def second(self, demands, duty, protected):
        cuts = sorted({0.0, 1.0} | {duty.get(i, 0.0) for i in demands})
        read, use = 0.0, dict.fromkeys(demands, 0.0)
        for a, b in zip(cuts, cuts[1:]):
            run = {i: d for i, d in demands.items() if duty.get(i, 0.0) <= a}
            total = protected + sum(run.values())
            scale = min(1.0, 100.0 / total) if total else 1.0
            read += (b - a) * min(100.0, total)
            for i, d in run.items():
                use[i] += (b - a) * d * scale
        return read, use

    def run_model(self, demands, protected=8.0, secs=60, ranks=None):
        demands = dict(enumerate(demands))
        ranks = ranks or [g.JOBS] * len(demands)
        window, level, duty, trace, worst = collections.deque(maxlen=3), 0.0, {}, [], 0.0
        for _ in range(secs):
            read, use = self.second(demands, duty, protected)
            window.append(read)
            c = g.candidates([P(i, f"job{i}", ranks[i], pct) for i, pct in use.items()])
            if len(window) == 3:
                level = g.next_level(level, sum(window) / 3, len(c), 90, 80)
            duty = {p.pid: s / g.SLOT_S for p, s in g.plan(level, c)}
            worst = max([worst] + list(duty.values()))
            trace.append(read)
        return trace, worst

    def test_one_to_five_cpu_bound_jobs_end_under_90(self):
        for demands in ([100], [100, 100], [100, 100, 100], [100] * 5, [40, 30, 20], [100, 30], [60, 50]):
            trace, worst = self.run_model(demands)
            self.assertEqual(trace[0], min(100.0, 8.0 + sum(demands)), demands)   # the first second, before the brake
            self.assertLessEqual(max(trace[12:]), 90.0, demands)            # within 12 s, and it stays there
            self.assertGreaterEqual(min(trace[12:]), 70.0, demands)         # without starving the jobs either
            self.assertLessEqual(worst, g.MAX_DUTY + 1e-9, demands)

    def test_a_small_first_in_line_does_not_keep_a_big_one_running(self):
        """The audit's order puts a page build first even when it uses little; the brake still reaches the big
        CPU-bound job behind it (it joins JOIN later) and the container ends under 90 %."""
        for demands, ranks in (([10, 100], [g.PAGES, g.JOBS]), ([6, 100, 100], [g.PAGES, g.SCANS, g.LAST]),
                               ([100, 30], [g.LAST, g.PAGES])):
            trace, worst = self.run_model(demands, ranks=ranks)
            self.assertLessEqual(max(trace[15:]), 90.0, demands)
            self.assertGreaterEqual(min(trace[15:]), 70.0, demands)
            self.assertLessEqual(worst, g.MAX_DUTY + 1e-9, demands)

    def test_light_jobs_are_never_paused(self):
        trace, worst = self.run_model([4, 4, 4], protected=8.0)
        self.assertEqual(worst, 0.0)
        trace, worst = self.run_model([], protected=97.0)                   # only the UI is busy: nothing to pause
        self.assertEqual((worst, trace[-1]), (0.0, 97.0))


class Pauses(unittest.TestCase):
    def stops_and_conts(self, kills):
        out = collections.defaultdict(list)
        for t, pid, sig in kills.log:
            out[pid].append((t, sig))
        return out

    def test_above_high_pauses_background_only_and_always_continues(self):
        gd, kills, logs, clock = guard([99] * 30, [UI, TRADE, KOL, DUGO, WALLETS])
        for _ in range(30):
            gd.tick()
        self.assertEqual(gd.stopped, set())
        self.assertTrue(kills.of(signal.SIGSTOP))
        self.assertEqual(set(kills.of(signal.SIGSTOP)), {21, 22})          # dugo and wallets, never ui / trade / kol
        self.assertFalse({11, 12, 13} & {pid for _, pid, _ in kills.log})
        for pid, events in self.stops_and_conts(kills).items():
            sigs = [s for _, s in events]
            self.assertEqual(sigs[0::2], [signal.SIGSTOP] * (len(sigs) // 2), pid)   # strictly STOP, CONT, STOP, CONT
            self.assertEqual(sigs[1::2], [signal.SIGCONT] * (len(sigs) // 2), pid)
            self.assertEqual(len(sigs) % 2, 0, pid)
            for (t_stop, _), (t_cont, _) in zip(events[0::2], events[1::2]):
                self.assertLessEqual(t_cont - t_stop, 0.5 + 1e-9)                     # a pause: at most half a second
                self.assertLessEqual(t_cont - t_stop, g.MAX_DUTY * g.SLOT_S + 1e-9)
            for (t_cont, _), (t_stop, _) in zip(events[1::2], events[2::2]):
                self.assertGreaterEqual(t_stop - t_cont, g.RUN_MIN_S - 1e-9)          # and a run before the next one

    def test_biggest_consumer_is_paused_first_and_longest(self):
        gd, kills, logs, clock = guard([99] * 5, [UI, DUGO, WALLETS])
        for _ in range(3):
            gd.tick()
        self.assertEqual(set(kills.of(signal.SIGSTOP)), {21})               # the first step of the brake: dugo alone
        gd.tick()                                                            # the second: wallets joins, JOIN shorter
        self.assertEqual(set(kills.of(signal.SIGSTOP)), {21, 22})
        gd.tick()
        self.assertGreater(gd.pauses["dugo"][1], gd.pauses["wallets"][1])

    def test_a_single_spike_is_not_a_reason(self):
        gd, kills, logs, clock = guard([20, 20, 100, 20, 20, 20], [UI, DUGO])
        for _ in range(6):
            gd.tick()
        self.assertEqual(kills.log, [])

    def test_needs_a_full_window_before_it_acts(self):
        gd, kills, logs, clock = guard([100, 100], [UI, DUGO])
        gd.tick(), gd.tick()
        self.assertEqual(kills.log, [])                                      # two seconds are not yet "a few"
        gd, kills, logs, clock = guard([100, 100, 100], [UI, DUGO])
        gd.tick(), gd.tick(), gd.tick()
        self.assertEqual(kills.of(signal.SIGSTOP), [21, 21])                 # two slots in the third second

    def test_eases_off_below_low_and_stops(self):
        gd, kills, logs, clock = guard([99] * 6 + [85] * 5 + [50] * 20, [UI, DUGO])
        for _ in range(7):                                                    # the 7th window (99, 99, 85) is still above
            gd.tick()
        top = gd.level
        self.assertGreater(top, 0.3)
        for _ in range(4):
            gd.tick()
        self.assertEqual(gd.level, top)                                       # between low and high: held
        n = len(kills.log)
        for _ in range(20):
            gd.tick()
        self.assertEqual(gd.level, 0.0)
        tail = len(kills.log)
        gd.meter.readings = [50] * 5
        for _ in range(5):
            gd.tick()
        self.assertGreater(tail, n)                                           # eased off step by step ...
        self.assertEqual(len(kills.log), tail)                                # ... down to no pauses at all

    def test_a_second_lasts_a_second(self):
        gd, kills, logs, clock = guard([99] * 8, [UI, DUGO, WALLETS])
        t0 = clock()
        for _ in range(8):
            gd.tick()
        self.assertAlmostEqual(clock() - t0, 8.0)

    def test_off_switch_measures_and_logs_but_sends_no_signal(self):
        gd, kills, logs, clock = guard([99] * 10, [UI, DUGO], on=False)
        for _ in range(10):
            gd.tick()
        self.assertEqual(kills.log, [])
        line = gd.line()
        self.assertIn("pauziranje isključeno", line)
        self.assertIn("pauzirao bih: dugo", line)
        self.assertIn("isključeno", gd.start_line())

    def test_no_reading_no_action(self):
        gd, kills, logs, clock = guard([None] * 5, [UI, DUGO])
        for _ in range(5):
            self.assertIsNone(gd.tick())
        self.assertEqual(kills.log, [])
        self.assertIn("nema mjerenja", gd.line())

    def test_a_pid_that_went_to_another_process_is_not_stopped(self):
        gd, kills, logs, clock = guard([99] * 6, [UI, DUGO, WALLETS], moved={21})
        for _ in range(6):
            gd.tick()
        self.assertEqual(set(kills.of(signal.SIGSTOP)), {22})

    def test_a_process_that_ended_is_skipped(self):
        gd, kills, logs, clock = guard([99] * 6, [UI, DUGO, WALLETS], fail={21})
        for _ in range(6):
            gd.tick()
        self.assertEqual(set(kills.of(signal.SIGSTOP)), {22})
        self.assertEqual(gd.stopped, set())

    def test_never_twice_in_a_row_without_a_run(self):
        gd, kills, logs, clock = guard([], [DUGO])
        self.assertTrue(gd._stop(DUGO))
        gd._cont(21)
        self.assertFalse(gd._stop(DUGO))                                      # just continued: it runs first
        clock.sleep(g.RUN_MIN_S / 2)
        self.assertFalse(gd._stop(DUGO))
        clock.sleep(g.RUN_MIN_S / 2)
        self.assertTrue(gd._stop(DUGO))
        gd.resume_all()
        self.assertEqual(kills.of(signal.SIGSTOP), [21, 21])
        self.assertEqual(kills.of(signal.SIGCONT), [21, 21])


class NothingStaysStopped(unittest.TestCase):
    """A stopped process left behind is the worst this guard could do."""

    def standing_when(self, kills):
        """Pids that got a SIGSTOP and no SIGCONT after it."""
        state = {}
        for _, pid, sig in kills.log:
            state[pid] = sig
        return {pid for pid, sig in state.items() if sig == signal.SIGSTOP}

    def break_sleep_after(self, clock, n, exc):
        """clock.sleep that raises `exc` on its n-th call: in the middle of a pause, with processes standing."""
        calls = {"n": 0}

        def sleep(s):
            calls["n"] += 1
            if calls["n"] == n:
                raise exc
            clock.sleep(s)
        return sleep

    def test_on_exit_everything_is_continued(self):
        # SIGTERM arrives as SystemExit out of the sleep in the middle of a pause (cpuguard._on_signal)
        gd, kills, logs, clock = guard([99] * 40, [UI, DUGO, WALLETS])
        for _ in range(8):
            gd.tick()
        seen = len(kills.log)
        gd.sleep = self.break_sleep_after(clock, 1, SystemExit(0))
        with self.assertRaises(SystemExit):
            gd.run()
        self.assertGreater(len(kills.of(signal.SIGSTOP)), 0)
        self.assertEqual(kills.log[seen][2], signal.SIGSTOP)                  # it was standing when the signal came
        self.assertEqual(self.standing_when(kills), set())
        self.assertEqual(gd.stopped, set())

    def test_on_keyboard_interrupt_too(self):
        gd, kills, logs, clock = guard([99] * 40, [UI, DUGO])
        for _ in range(6):
            gd.tick()
        gd.sleep = self.break_sleep_after(clock, 1, KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            gd.run()
        self.assertEqual(self.standing_when(kills), set())

    def test_on_any_exception_everything_is_continued_and_the_guard_goes_on(self):
        gd, kills, logs, clock = guard([99] * 40, [UI, DUGO, WALLETS])
        for _ in range(8):
            gd.tick()
        gd.sleep = self.break_sleep_after(clock, 1, RuntimeError("pokvareno"))
        gd.run(ticks=5)
        self.assertEqual(self.standing_when(kills), set())
        self.assertEqual(gd.stopped, set())
        self.assertEqual(sum("greška, nastavljam (RuntimeError: pokvareno)" in ln for ln in logs), 1)
        self.assertGreater(len(kills.of(signal.SIGSTOP)), 3)                  # it went on pausing after the error

    def test_a_failing_reader_is_one_line_a_minute_not_a_crash(self):
        gd, kills, logs, clock = guard([], [UI, DUGO])
        gd.meter.read = mock.Mock(side_effect=[None] + [OSError("cgroup nestao")] * 200)
        gd.run(ticks=130)
        errors = [ln for ln in logs if "greška" in ln]
        self.assertEqual(len(errors), 3)                                       # at 0, 60 and 120 s
        self.assertEqual(kills.log, [])

    def test_continue_fails_for_one_the_others_are_still_continued(self):
        clock = Clock()
        sent = []

        def kill(pid, sig):
            sent.append((pid, sig))
            if sig == signal.SIGCONT and pid == 21:
                raise ProcessLookupError(pid)                                  # it ended while it stood
        gd = g.Guard(meter=FakeMeter([]), procs=FakeProcs([]), kill=kill, sleep=clock.sleep, clock=clock, log=lambda s: None)
        gd._stop(DUGO), gd._stop(WALLETS)
        gd.resume_all()
        self.assertIn((22, signal.SIGCONT), sent)
        self.assertEqual(gd.stopped, set())

    def test_start_sweep_continues_what_an_earlier_guard_left(self):
        proc = fake_proc(tempfile.mkdtemp(), {
            301: {"argv": ["python3", "run_dugo.py", "once"], "state": "T"},
            302: {"argv": ["python3", "run_ui.py"], "state": "S"},
        })
        clock = Clock()
        kills, logs = Kills(clock), []
        gd = g.Guard(meter=FakeMeter([10] * 3), procs=FakeProcs([UI], proc=proc), kill=kills, sleep=clock.sleep, clock=clock,
                     log=logs.append)
        gd.run(ticks=2)
        self.assertEqual(kills.log[0][1:], (301, signal.SIGCONT))             # before anything else
        self.assertIn("pri startu", logs[0])
        self.assertIn("301", logs[0])
        self.assertEqual(kills.of(signal.SIGCONT).count(301), 2)              # and once more on the way out

    def test_signal_handler_leaves_through_the_cleanup(self):
        with mock.patch("signal.signal") as sig:
            with self.assertRaises(SystemExit):
                g._on_signal(signal.SIGTERM, None)
        ignored = {c.args[0] for c in sig.call_args_list if c.args[1] == signal.SIG_IGN}
        self.assertEqual(ignored, {signal.SIGTERM, signal.SIGINT, signal.SIGHUP})   # a second TERM cannot cut it short

    @unittest.skipUnless(os.path.isdir("/proc/self") and hasattr(os, "fork"), "treba Linux /proc")
    def test_a_killed_guard_leaves_nothing_stopped(self):
        """Real processes: a guard with its twin stops a job and is ended with SIGKILL, which no handler sees."""
        d = tempfile.mkdtemp()   # both run from their own folder, so only they are "ours" to the twin
        env = dict(os.environ, PYTHONPATH=ROOT)
        job = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], cwd=d, env=env)
        code = ("import os, signal, sys, time\nfrom ops import cpuguard\nkeep = cpuguard.deadman()\n"
                f"os.kill({job.pid}, signal.SIGSTOP)\nprint('stoji', flush=True)\ntime.sleep(60)\n")
        gd = subprocess.Popen([sys.executable, "-c", code], cwd=d, env=env, stdout=subprocess.PIPE)
        try:
            self.assertEqual(gd.stdout.readline().strip(), b"stoji")
            self.assertEqual(self.wait_state(job.pid, "T"), "T")
            gd.kill()
            gd.wait(5)
            self.assertNotEqual(self.wait_state(job.pid, "S"), "T")
        finally:
            for p in (gd, job):
                try:
                    os.kill(p.pid, signal.SIGCONT)
                    p.kill()
                except OSError:
                    pass
                p.wait(5)
            gd.stdout.close()

    def wait_state(self, pid, want, seconds=5.0):
        end = time.time() + seconds
        while True:
            state = g.proc_stat(pid)[1]
            if (state == "T") == (want == "T") or time.time() > end:
                return state
            time.sleep(0.01)


class LogLine(unittest.TestCase):
    def test_one_line_with_average_peak_pauses_and_whom(self):
        gd, kills, logs, clock = guard([40, 60, 99, 99, 99, 99, 99, 99], [UI, DUGO, WALLETS])
        for _ in range(8):
            gd.tick()
        line = gd.line()
        self.assertNotIn("\n", line)
        self.assertTrue(line.startswith("čuvar CPU-a: prosjek 87 %, vrh 99 %, iznad 90 % 6 s od 8, pauza "), line)
        m = re.search(r"pauza (\d+) \(dugo (\d+) puta ([\d.]+) s, wallets (\d+) puta ([\d.]+) s\)", line)
        self.assertTrue(m, line)
        self.assertEqual(int(m.group(1)), int(m.group(2)) + int(m.group(4)))
        self.assertEqual(int(m.group(1)), len(kills.of(signal.SIGSTOP)))
        self.assertGreater(float(m.group(3)), float(m.group(5)))             # the biggest consumer stood longest
        self.assertNotIn("—", line)

    def test_quiet_minute(self):
        gd, kills, logs, clock = guard([12, 30, 18], [UI, DUGO])
        for _ in range(3):
            gd.tick()
        self.assertEqual(gd.line(), "čuvar CPU-a: prosjek 20 %, vrh 30 %, iznad 90 % 0 s od 3, pauza 0")

    def test_names_the_protected_consumer_it_may_not_touch(self):
        gd, kills, logs, clock = guard([99] * 6, [UI, TRADE])
        for _ in range(6):
            gd.tick()
        self.assertEqual(kills.log, [])
        self.assertIn("pauza 0; najviše troši ui 97 % (zaštićen, ne diram ga)", gd.line())

    def test_kernel_throttling_is_in_the_line(self):
        gd, kills, logs, clock = guard([50, 50], [UI])
        gd.tick()
        gd.meter.throttled = 7
        gd.tick()
        self.assertIn("jezgra nas je kočila 7 puta", gd.line())

    def test_one_line_a_minute(self):
        gd, kills, logs, clock = guard([30] * 400, [UI, DUGO])
        gd.run(ticks=185)
        lines = [ln for ln in logs if "prosjek" in ln and "vrh" in ln]
        self.assertEqual(len(lines), 3)                                        # 185 s: three minutes' lines
        self.assertIn("od 60", lines[0])
        self.assertIn("izvor proba, 1.00 CPU, pauze iznad 90 %", logs[0])      # the start line: source, CPUs, thresholds
        self.assertIn("nikad ne diram: ui, trade", logs[0])


class Priorities(unittest.TestCase):
    """start.sh: background loops below the UI and the trade loop, the protected listeners at normal priority."""

    def setUp(self):
        with open(os.path.join(ROOT, "start.sh"), encoding="utf-8") as f:
            self.sh = f.read()
        self.code = [ln for ln in self.sh.splitlines() if not ln.strip().startswith("#")]

    def test_background_loops_are_low_listeners_are_not(self):
        for cmd in ("keep minute python3 run_kol.py minute-loop", "keep sched python3 run_sched.py",
                    "keep report python3 run_report.py loop", "python3 run_top.py once", "python3 run_watch.py run",
                    "python3 run_simianx.py once"):
            self.assertIn("low " + cmd, self.sh, cmd)
        for cmd in ("keep ui python3 run_ui.py", "keep trade python3 run_trade.py follow", "keep kol python3 run_kol.py loop",
                    "keep tg python3 run_tg.py loop", "python3 run_tg.py telethon", "keep paper python3 run_paper.py run",
                    "keep live python3 run_live.py loop", "keep cpuguard python3 -m ops.cpuguard",
                    "keep uptime python3 -m ops.uptime"):
            self.assertIn(cmd, self.sh, cmd)
            self.assertNotIn("low " + cmd, self.sh, cmd)

    def test_low_matches_the_guards_list(self):
        """What start.sh starts at low priority is never something the guard protects as part of the money path."""
        for ln in self.code:
            m = re.search(r"low (?:keep \w+ )?python3 (\S+)(.*)", ln)
            if m:
                name, kind, _ = g.classify(["python3", m.group(1)] + m.group(2).split())
                self.assertIn(name, ("minute", "sched", "report", "top", "watch", "simianx", "skener", "grupe", "range", "insajderi",
                                     "momentum", "shill-mreza", "eventi", "prijedlozi", "zonewatch", "fast"), ln)   # 11.11.:
                # momentum/, kol/preshill.py, topics/, proposals/, zonewatch/, fast/ (run_fast.py, flag fast_path G24)
                self.assertNotIn(name, ("ui", "trade", "kol", "tg", "live", "paper"), ln)

    def test_guard_starts_right_after_ui_and_trade_before_the_background(self):
        i = self.sh.index("keep cpuguard python3 -m ops.cpuguard")
        self.assertLess(self.sh.index("keep ui python3 run_ui.py"), i)
        self.assertLess(self.sh.index("keep trade python3 run_trade.py follow"), i)
        for later in ("rugfilter.archive", "run_top.py once", "run_calendar.py", "keep kol python3", "keep paper python3"):
            self.assertLess(i, self.sh.index(later), later)
        self.assertIn('if [ -n "${PORT:-}" ]; then keep uptime python3 -m ops.uptime; fi', self.sh)   # web service only
        subprocess.run(["bash", "-n", os.path.join(ROOT, "start.sh")], check=True)

    def test_low_and_keep_really_lower_the_priority(self):
        """The two helpers as bash runs them: `low keep` and `low` give nice +BG_NICE, plain `keep` leaves it."""
        defs = "\n".join(ln for ln in self.code if re.match(r"(BG_NICE=|low\(\) \{|keep\(\) \{)", ln))
        self.assertEqual(defs.count("\n"), 2, defs)
        out = os.path.join(tempfile.mkdtemp(), "out")
        show = f"import os; open('{out}', 'a').write('%s %d\\n' % (os.environ['WHO'], os.nice(0)))"
        script = (f"set -u\n{defs}\n"
                  f"WHO=nisko low keep a {sys.executable} -c \"{show}\"\n"
                  f"WHO=obicno keep b {sys.executable} -c \"{show}\"\n"
                  f"( WHO=petlja low {sys.executable} -c \"{show}\" ) &\n"
                  f"for i in $(seq 1 100); do [ \"$(wc -l < '{out}' 2>/dev/null || echo 0)\" -ge 3 ] && break; sleep 0.05; done\n"
                  "kill $(jobs -p) 2>/dev/null\n")
        subprocess.run(["bash", "-c", script], check=False, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with open(out) as f:
            got = dict(ln.split() for ln in f.read().splitlines())
        base = int(got["obicno"])
        want = min(19, base + 10)
        self.assertEqual((int(got["nisko"]), int(got["petlja"])), (want, want), got)

    def test_heavy_child_goes_to_its_nice_not_below_it(self):
        from ops import heavy
        for now, add in ((0, [heavy.NICE]), (4, [heavy.NICE - 4]), (heavy.NICE, []), (15, [])):
            calls = []

            def nice(n, now=now, calls=calls):
                if n:
                    calls.append(n)
                return now + n
            with mock.patch("os.nice", side_effect=nice):
                heavy._nicer()
            self.assertEqual(calls, add, now)          # a job under `low keep sched` (already at 10) is not pushed to 20


if __name__ == "__main__":
    unittest.main()
