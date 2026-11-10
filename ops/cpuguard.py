"""CPU guard: keeps the container under about 90 % of its CPU, so the pages and the money path never wait.

10.11. (Jure: "CPU treba u svakom momentu biti maksimalno 90-95 %, napravi skriptu koja to provjerava; aplikacija
mora biti dostupna u svakom momentu"). On 9.11. background jobs held the single CPU at 100 % for 30-47 minutes of
every hour and the web app stopped answering. When a container has used up its CPU quota the kernel stops EVERY
process in it until the next 100 ms period, the web server and the trade loop included; "nice" does not help there,
it only orders processes that wait for the same core. So this loop keeps the total under the quota instead:

  every second          the container's CPU (cgroup v2 cpu.stat + cpu.max, else cgroup v1 cpuacct, else /proc/stat)
                        and the CPU of each of our python processes (/proc/<pid>/stat)
  average of the last CPU_WINDOW_S seconds above CPU_HIGH (90)
                        brake harder: the first background job in line (the audit's order: page builds first,
                        run_top's rug check last; the biggest consumer first within one rank) is paused (SIGSTOP ...
                        SIGCONT) for a part of every half second; when one is not enough the next one joins
  between the two       hold
  below CPU_LOW (80)    ease off, step by step down to no pauses (a sudden stop would jump straight back to 100 %)

What a pause may cost, and what is done about it:
- a paused process may be in the middle of a SQLite write and hold the lock: a pause is a part of a half second
  (0.25 s at the default CPU_MAX_DUTY, never more than SLOT_S), and after every pause the process runs for at least
  RUN_MIN_S before the next one, so a writer waiting behind it (busy timeouts here are 10-60 s) waits a little longer
  and nothing more;
- a process left stopped is the worst outcome: everything stopped is continued within the same half second
  (try/finally), on SIGTERM/SIGINT/SIGHUP, on any exception, at start (a sweep over /proc for stopped python
  processes, in case an earlier guard was killed), and by a forked twin that outlives a SIGKILL of the guard (deadman);
- bash's `wait` in start.sh's keep and Python's subprocess.run do not return when their child is merely stopped
  (checked 10.11. with bash 5.2), so no supervisor restarts or doubles a paused job.

    python3 -m ops.cpuguard          the loop (start.sh: keep cpuguard ...)
    python3 -m ops.cpuguard --once   one reading and our processes with their rank, then exit
    python3 -m ops.cpuguard --popis  who is never paused, the order of the others, and why

CPUGUARD=0 turns the pausing off (it still measures and logs). CPU_HIGH, CPU_LOW, CPU_WINDOW_S, CPU_MAX_DUTY and
CPU_CORES (when the cgroup does not say how many CPUs we have) override the defaults.
"""
import collections
import os
import signal
import sys
import time


def _env(name, default, lo, hi):
    """A number from the environment, kept inside [lo, hi]; a typo there must not stop the guard."""
    try:
        return min(hi, max(lo, float(os.environ.get(name) or default)))
    except ValueError:
        return float(default)


ON = os.environ.get("CPUGUARD", "1") != "0"
CPU_HIGH = _env("CPU_HIGH", 90, 20, 100)
CPU_LOW = min(_env("CPU_LOW", 80, 10, 100), CPU_HIGH)
WINDOW_S = int(_env("CPU_WINDOW_S", 3, 1, 30))   # "the average over a few seconds": one spike is not a reason to pause
TICK_S = 1.0
SLOT_S = 0.5        # a second is two slots; in each a paused process stands for a part and runs for the rest
RUN_MIN_S = 0.2     # ... and it always runs at least this long between two pauses
MAX_DUTY = _env("CPU_MAX_DUTY", 0.5, 0.1, 1 - RUN_MIN_S / SLOT_S)   # the largest part of a slot one process may stand
MIN_PAUSE_S = 0.02  # shorter than this is not worth two signals
STEP_UP, STEP_DOWN = 0.1, 0.05   # how fast the brake goes on and comes off: parts of a slot per second
JOIN = 0.1          # the next biggest consumer joins when the one before it already stands this much of a slot
MIN_CPU = 5.0       # a process under 5 % of a core is not what holds the CPU; pausing it gains nothing
LOG_EVERY_S = 60
MIN_INTERVAL_S = 0.2   # the shortest stretch a CPU percentage is computed over
CGROUP, PROC = "/sys/fs/cgroup", "/proc"
CLK_TCK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100

# ---------------------------------------------------------------------------------------------------------------
# Who may be paused, and in which order. Decided from start.sh, process by process, by what each one does, and from
# last night's audit of the per-second jobs (audit/2026-11-10/sekundni.md §4: who is never paused, who may wait and
# in which order); when in doubt, protected.
#
# The money path, never paused: a followed account posts or a followed wallet buys -> a listener writes it down
# (X and Helius webhooks inside run_ui.py, run_tg.py, run_live.py, the KOL round's collect) -> league/copy.py in
# run_ui.py enters the demo account -> run_trade.py mirrors it as a real (or dry-run) swap. Supervisors are left
# alone as well: they use no CPU, and several of them hold the heavy-job lock for their child.
#
# Rank: 0 = never paused; 1..5 = may stand for a part of a second, rank 1 first (the audit's order), and within a
# rank the biggest consumer first. A lower rank stands longer: the brake gives the first candidate the largest part.
# ---------------------------------------------------------------------------------------------------------------
PROTECTED, PAGES, SCANS, ROUNDS, JOBS, LAST = 0, 1, 2, 3, 4, 5
ROUND = -1   # only in the table below: protected until ROUND_CPU_S of its own CPU, ROUNDS after that
ROUND_CPU_S = _env("CPUGUARD_ROUND_CPU_S", 120, 0, 86400)


def _paper_rank():
    """10.11. (audit sekundni.md §4): the demo loop may wait only "dok je follow_paper zaključan", i.e. while run_trade
    does not mirror its entries ("prati i demo strategiju" locked in trade/settings.LOCKED, a code constant: no
    database read). Lock lifted, or the module not readable: protected, the safe side."""
    try:
        from trade import settings
        return SCANS if "follow_paper" in settings.LOCKED else PROTECTED
    except Exception:  # noqa: BLE001 - any doubt protects
        return PROTECTED


# (name in the log, script or "-m module", words one of which must be among its arguments (() = any), rank, why)
# The first match wins, so the special cases of a script stand above its general line.
PROCESSES = (
    # 1: page builds, the biggest consumer of the day (/pregled 60-116 s and /tokeni ~60 s of CPU every ~7 min); while
    # one is built the visitor gets the last saved copy (run_ui._last_copy), so nobody waits for it by the second
    ("ui-dijete", "run_ui.py", ("--render",), PAGES,
     "gradnja teške stranice u djetetu, najveći dnevni potrošač; posjetitelj za to vrijeme dobiva zadnju "
     "spremljenu kopiju"),
    ("ui", "run_ui.py", (), PROTECTED,
     "stranice, webhookovi (X, Helius), demo kopiranje praćenih računa i auto prodaja: tu lanac novca počinje"),
    ("trade", "run_trade.py", (), PROTECTED, "pravi (ili probni) swapovi, petlja od jedne sekunde"),
    ("deploy", "deploy_wait.py", (), PROTECTED, "stranica 'deploy u tijeku' dok se aplikacija diže"),
    ("kol", "run_kol.py", ("loop",), PROTECTED,
     "nadzor KOL krugova: pokreće ih i drži im bravu teških poslova; sam ne troši CPU"),
    ("minute", "run_kol.py", ("minute-loop", "minute"), ROUNDS,
     "minutne svijeće nakon poziva: zaostatak mjerenja, vlastita baza"),
    ("backfill", "run_kol.py", ("backfill",), ROUNDS, "jednokratna povijest poziva (plaćeni dohvat, noću)"),
    # 10.11.: a round (once, search-round) starts with the steps that bring calls of followed accounts into kol.db
    # (webhook spool, X watch, live sync: little CPU, mostly waiting on the network), and at night the same process
    # goes on to the scoring (40+ minutes of CPU). There is no separate process to tell them apart, so the round is
    # protected until it has used ROUND_CPU_S of CPU itself; past that it is computing, not listening, and may wait
    # with the KOL jobs (audit rank 3). The same line catches a search round that runs away (9.11.: one query held it
    # at 100 % for 47 minutes).
    ("kol-krug", "run_kol.py", (), ROUND,
     f"krug donosi pozive praćenih računa u kol.db; zaštićen dok sam ne potroši {ROUND_CPU_S:.0f} s CPU-a "
     "(dalje je to ocjenjivanje, pa smije čekati s ostalim KOL poslovima)"),
    ("tg", "run_tg.py", (), PROTECTED,
     "čita praćene Telegram kanale svake 2-3 s (i živi slušač): pozivi koje kopiranje čita"),
    ("live", "run_live.py", (), PROTECTED,
     "PumpPortal uživo: kupnje i prodaje praćenih walleta u sekundi; zaustavljen puni red i ruši vezu"),
    ("paper", "run_paper.py", (), _paper_rank(),
     "demo ulazi i izlazi i dijete hype skena; smije čekati samo dok je 'prati i demo strategiju' zaključano "
     "(pravi trade ga tada ne zrcali), inače zaštićen"),
    ("cpuguard", "-m ops.cpuguard", (), PROTECTED, "ovaj čuvar i njegov rezervni blizanac"),
    ("uptime", "-m ops.uptime", (), PROTECTED, "provjera dostupnosti aplikacije svakih 30 s"),
    # 10.11.: the audit lets the hourly upkeep wait (its rank 4); kept protected here: it holds the write lock of
    # trade.db and league.db too (retention, WAL cut, the daily rewrite), and every second it stands is a second
    # run_trade and the copy loop wait for that lock. The minute memory watchdog is the same module.
    ("health", "-m ops.health", (), PROTECTED,
     "nadzor memorije svake minute i održavanje baza: drži bravu pisanja i nad trade.db i league.db, "
     "pauza bi produžila čekanje petlje novca"),
    ("heavy", "-m ops.heavy", (), PROTECTED, "omotač teškog posla: čeka dijete i drži bravu; sam ne troši CPU"),
    ("sched", "run_sched.py", (), PROTECTED, "raspored: drži sat i pokreće svoje poslove; sam ne troši CPU"),
    # 2: the hype scan (a child of the demo loop every 2 min) and the nightly smart-wallet learning
    ("hype-status", "run_hype.py", ("status",), JOBS, "status tokena svakih 6 sati (raspored)"),
    ("hype", "run_hype.py", (), SCANS, "hype sken (dijete demo petlje svake 2 min) i noćno učenje pametnih walleta"),
    # 4: the scheduler's jobs and the other batches; nobody waits for these by the second, each comes round again
    ("learn", "run_learn.py", (), JOBS, "učenje, sjena, masovna sjena i AI oznake objava (raspored)"),
    ("exits", "run_exits.py", (), JOBS, "pravila izlaza po klasi: dnevno učenje i povrat (raspored)"),
    ("market", "run_market.py", (), JOBS, "stanje tržišta svaki sat (raspored)"),
    ("usage", "run_usage.py", (), JOBS, "potrošnja plaćenih izvora svakih 15 min (raspored)"),
    ("corr", "run_corr.py", (), JOBS, "korelacije skupina i faktora, noću (raspored)"),
    ("whatsapp", "run_whatsapp.py", (), JOBS, "dnevni sažetak u WhatsApp grupu (raspored)"),
    ("report", "run_report.py", (), JOBS, "jutarnji izvještaj e-poštom"),
    ("simianx", "run_simianx.py", (), JOBS, "drugo mišljenje za dugoročnu listu"),
    ("watch", "run_watch.py", (), JOBS, "praćenje tokena prije događaja, jednom na sat"),
    ("web", "run_web.py", (), JOBS, "dnevno osvježavanje javnih stranica u 02:00, čita samo naše baze"),
    ("wallets", "run_wallets.py", (), JOBS, "registar walleta: skupljanje, ocjenjivanje, popisi"),
    # 10.11. (Grok MCP audit 9): night only, at most 200 getTransaction calls a night; waits on the network, not the CPU
    ("solfill", "-m wallets.solfill", (), JOBS, "noću upisuje iznose prodaja praćenih walleta iz transakcija (Helius)"),
    ("research", "-m research.hope", (), JOBS, "jednokratno istraživanje tokena (samo čitanje, Helius)"),
    ("research-a", "-m research.hope_report", (), JOBS, "jednokratni sažetak istraživanja u log (samo čitanje)"),
    ("rug-arhiva", "-m rugfilter.archive", (), JOBS, "arhiva rugiranih tokena, jednom na sat"),
    ("calendar", "run_calendar.py", (), JOBS, "kalendar događaja svakih 6 sati (noću)"),
    ("dex", "run_dex.py", (), JOBS, "DexScreener tokeni događaja svakih 6 sati (noću)"),
    ("dugo", "run_dugo.py", (), JOBS, "dugoročni sloj svakih 6 sati (noću)"),
    # 5: last of all: its rug check feeds the entry guard (_concentration) of the copy loop
    ("top", "run_top.py", (), LAST,
     "provjera preporučenih tokena svake 3 min; njena provjera ruga hrani zaštitu ulaza, pa staje zadnja"),
)
OTHER_WHY = "nije u start.sh ni u rasporedu (ručno pokrenut posao): čeka s poslovima rasporeda"


def rank_text(rank):
    """'zaštićen' or '3. u redu', for the log and the list."""
    return "zaštićen" if rank == PROTECTED else "krug" if rank == ROUND else f"{rank}. u redu"


def parse(argv):
    """("run_kol.py" or "-m ops.heavy", the arguments after it) of a python command line; None when it is not python.
    The module of "-m" is looked at first: "python3 -m ops.heavy --night run_dugo.py once" is the wrapper, not run_dugo."""
    if not argv or "python" not in os.path.basename(argv[0]):
        return None
    rest = [a for a in argv[1:] if a]
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "-m" and i + 1 < len(rest):
            return "-m " + rest[i + 1], rest[i + 2:]
        if a == "-c":
            return "-c", rest[i + 2:]
        if a.endswith(".py"):
            return os.path.basename(a), rest[i + 1:]
        if not a.startswith("-"):
            break
        i += 2 if a in ("-X", "-W") else 1   # these two interpreter options carry a value of their own
    return "python", rest


def classify(argv, cpu_s=0.0):
    """(name, rank, why) of a python command line, or None for anything else. cpu_s: CPU seconds the process has used
    so far (a KOL round is protected only up to ROUND_CPU_S of them)."""
    got = parse(argv)
    if got is None:
        return None
    what, args = got
    for name, script, words, rank, why in PROCESSES:
        if script == what and (not words or any(w in args for w in words)):
            if rank == ROUND:
                rank = PROTECTED if cpu_s <= ROUND_CPU_S else ROUNDS
            return name, rank, why
    name = what[4:-3] if what.startswith("run_") and what.endswith(".py") else what
    return name, JOBS, OTHER_WHY


# ---------------------------------------------------------------------------------------------------------------
# The container's CPU
# ---------------------------------------------------------------------------------------------------------------
def _read(path):
    with open(path) as f:
        return f.read()


def _kv(text):
    """{"usage_usec": "123", ...} from the "name value" lines of a cgroup stat file."""
    return dict(ln.split()[:2] for ln in text.splitlines() if len(ln.split()) >= 2)


def read_v2(root=CGROUP):
    """cgroup v2: (CPU seconds used so far, CPUs the quota allows or None for "max", times the kernel throttled us)."""
    stat = _kv(_read(os.path.join(root, "cpu.stat")))
    used = int(stat["usage_usec"]) / 1e6
    try:
        quota, period = (_read(os.path.join(root, "cpu.max")).split() + ["100000"])[:2]
        cpus = None if quota == "max" else int(quota) / int(period)
    except OSError:   # no cpu.max: the CPU controller is not switched on for us, so there is no quota either
        cpus = None
    return used, cpus, int(stat["nr_throttled"]) if "nr_throttled" in stat else None


def read_v1(root=CGROUP):
    """cgroup v1: the same three from cpuacct.usage (nanoseconds) and cpu.cfs_quota_us / cpu.cfs_period_us
    (-1 = no quota)."""
    used = None
    for d in ("cpuacct", "cpu,cpuacct", "cpu"):
        try:
            used = int(_read(os.path.join(root, d, "cpuacct.usage"))) / 1e9
            break
        except OSError:
            pass
    if used is None:
        raise OSError("cpuacct.usage")
    cpus = throttled = None
    for d in ("cpu", "cpu,cpuacct"):
        try:
            quota = int(_read(os.path.join(root, d, "cpu.cfs_quota_us")))
            period = int(_read(os.path.join(root, d, "cpu.cfs_period_us")))
            cpus = quota / period if quota > 0 and period > 0 else None
            stat = _kv(_read(os.path.join(root, d, "cpu.stat")))
            throttled = int(stat["nr_throttled"]) if "nr_throttled" in stat else None
            break
        except (OSError, ValueError):
            pass
    return used, cpus, throttled


def read_procstat(proc=PROC):
    """/proc/stat, the last resort: busy seconds of the whole machine and its CPUs. Inside a container this is usually
    the host, so the percentage is then the host's; the start line says which source is in use."""
    lines = _read(os.path.join(proc, "stat")).splitlines()
    f = [int(x) for x in lines[0].split()[1:9]]   # user nice system idle iowait irq softirq steal (guest is in user)
    cpus = sum(1 for ln in lines if ln.startswith("cpu") and ln[3:4].isdigit())
    return (sum(f) - f[3] - (f[4] if len(f) > 4 else 0)) / CLK_TCK, cpus or 1, None


def own_cpus():
    """CPUs this process may run on (the cpuset), for a container without a quota; never the host's whole count
    when the container was given fewer."""
    try:
        return len(os.sched_getaffinity(0)) or 1
    except (AttributeError, OSError):
        return os.cpu_count() or 1


def percent(prev, cur, cpus):
    """CPU in percent of what `cpus` CPUs can give, between two readings (seconds on the clock, CPU seconds used)."""
    dt = cur[0] - prev[0]
    if dt <= 0 or not cpus:
        return None
    return max(0.0, (cur[1] - prev[1]) / (dt * cpus) * 100)


class Meter:
    """The container's CPU in percent of what it may use, from one reading to the next."""

    def __init__(self, root=CGROUP, proc=PROC, cores=None, clock=time.monotonic):
        self.clock = clock
        self.cores = cores if cores is not None else (_env("CPU_CORES", 0, 0, 4096) or None)
        self.sources = (("cgroup v2", lambda: read_v2(root)), ("cgroup v1", lambda: read_v1(root)),
                        ("/proc/stat (cijeli stroj)", lambda: read_procstat(proc)))
        self.source = self.cpus = self.cpus_from = self.prev = None
        self.throttled = 0   # kernel throttle periods since the first reading: the thing this guard exists to prevent

    def _sample(self):
        for name, fn in self.sources if self.source is None else [s for s in self.sources if s[0] == self.source]:
            try:
                used, cpus, thr = fn()
            except (OSError, ValueError, KeyError, IndexError):
                continue
            self.source = name
            return used, cpus, thr
        return None

    def read(self):
        """Percent since the previous call; None on the first call and when no source can be read."""
        got = self._sample()
        if got is None:
            return None
        used, cpus, thr = got
        cur = (self.clock(), used, thr)
        self.cpus = self.cores or cpus or own_cpus()
        # said in the start line: without a quota the percentage is of every core we may run on, and a guard that
        # counts 8 cores where Render gives us one would never act (CPU_CORES fixes that)
        self.cpus_from = ("zadano ručno" if self.cores else "jezgre cijelog stroja" if self.source.startswith("/proc")
                          else "kvota" if cpus else "jezgre koje vidim, kvote nema")
        prev = self.prev
        if prev is not None and cur[0] - prev[0] < MIN_INTERVAL_S:
            return None   # two readings a few ms apart say nothing (one 10 ms tick would read as 1000 %)
        self.prev = cur
        if prev is None:
            return None
        if thr is not None and prev[2] is not None:
            self.throttled += max(0, thr - prev[2])
        return percent(prev, cur, self.cpus)


# ---------------------------------------------------------------------------------------------------------------
# Our processes
# ---------------------------------------------------------------------------------------------------------------
P = collections.namedtuple("P", "pid start name rank why pct cpu_s state")


def proc_stat(pid, proc=PROC):
    """(name, state, CPU ticks used, start time in ticks since boot) from /proc/<pid>/stat. The name stands in
    brackets and may itself hold spaces and brackets, so the fields are counted from the last one."""
    s = _read(os.path.join(proc, str(pid), "stat"))
    i, j = s.index("("), s.rindex(")")
    f = s[j + 2:].split()
    return s[i + 1:j], f[0], int(f[11]) + int(f[12]), int(f[19])


def cmdline(pid, proc=PROC):
    with open(os.path.join(proc, str(pid), "cmdline"), "rb") as f:
        return [a.decode(errors="replace") for a in f.read().split(b"\0") if a]


class Procs:
    """Our python processes and how much CPU each used over the last WINDOW_S seconds."""

    def __init__(self, proc=PROC, clock=time.monotonic, window=WINDOW_S):
        self.proc, self.clock, self.window = proc, clock, window
        self.hist = {}   # (pid, start) -> deque of (clock, ticks), newest last

    def scan(self):
        """[P] of every python process but this one. pct: percent of one core over the window (0 at first sight)."""
        now, out, alive = self.clock(), [], set()
        for pid in os.listdir(self.proc):
            if not pid.isdigit() or int(pid) == os.getpid():
                continue
            try:
                comm, state, ticks, start = proc_stat(pid, self.proc)
                if not comm.startswith("python"):
                    continue
                # read every time, not remembered: between fork and exec a child still shows its parent's command line
                got = classify(cmdline(pid, self.proc), ticks / CLK_TCK)
            except (OSError, ValueError, IndexError):
                continue   # ended while we looked
            if got is None:
                continue
            key = (int(pid), start)
            alive.add(key)
            h = self.hist.setdefault(key, collections.deque(maxlen=self.window + 1))
            h.append((now, ticks))
            dt = h[-1][0] - h[0][0]
            pct = (h[-1][1] - h[0][1]) / CLK_TCK / dt * 100 if dt > 0 else 0.0
            out.append(P(int(pid), start, *got, pct, ticks / CLK_TCK, state))
        for key in set(self.hist) - alive:
            del self.hist[key]
        return out

    def same(self, p):
        """True while pid p.pid is still the process we measured (a pid can be handed to a new process)."""
        try:
            return proc_stat(p.pid, self.proc)[3] == p.start
        except (OSError, ValueError, IndexError):
            return False

    def ours(self, p):
        return ours(p.pid, self.proc)


def ours(pid, proc=PROC):
    """True when the process runs from the same directory as this guard (start.sh starts everything from the app's
    folder): a python process of anything else on the machine is not ours to stop or to continue."""
    try:
        return os.readlink(os.path.join(proc, str(pid), "cwd")) == os.getcwd()
    except OSError:
        return False


def stopped_pids(proc=PROC):
    """Pids of our python processes that stand stopped (state T) right now."""
    out = []
    for pid in os.listdir(proc):
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        try:
            comm, state, _, _ = proc_stat(pid, proc)
        except (OSError, ValueError, IndexError):
            continue
        if state == "T" and comm.startswith("python") and ours(pid, proc):
            out.append(int(pid))
    return out


def sweep(kill=os.kill, proc=PROC):
    """SIGCONT to every stopped python process of ours; the pids continued. Nothing here stops a process on purpose
    for longer than half a second, so one found standing was left behind by a guard that died."""
    done = []
    for pid in stopped_pids(proc):
        try:
            kill(pid, signal.SIGCONT)
            done.append(pid)
        except OSError:
            pass
    return done


# ---------------------------------------------------------------------------------------------------------------
# The brake
# ---------------------------------------------------------------------------------------------------------------
def candidates(procs, ours=lambda p: True):
    """Processes that may be paused now, in the order they would be: by rank (page builds first, the rug check of
    run_top last), the biggest consumer first within a rank. Never a protected one, never one that uses next to
    nothing, never one that already stands."""
    c = [p for p in procs if p.rank > PROTECTED and p.pct >= MIN_CPU and p.state not in ("T", "t", "Z", "X")
         and ours(p)]
    return sorted(c, key=lambda p: (p.rank, -p.pct))


def ceiling(n, max_duty=MAX_DUTY):
    """The level at which all n candidates stand as long as they may; pushing the brake further changes nothing."""
    return max_duty + (n - 1) * JOIN if n else 0.0


def next_level(level, avg, n, high=CPU_HIGH, low=CPU_LOW, max_duty=MAX_DUTY):
    """The brake for the next second: the part of every slot the first candidate in line stands. Up while the
    average is above `high`, down while it is below `low`, unchanged between them; 0 with nobody to pause."""
    if avg > high:
        level += STEP_UP
    elif avg < low:
        level -= STEP_DOWN
    return max(0.0, min(level, ceiling(n, max_duty)))


def plan(level, cands, max_duty=MAX_DUTY, slot=SLOT_S):
    """[(P, seconds to stand in every slot)]: the first in line stands `level` of the slot (at most max_duty), each
    next one JOIN less. All of them stand at the START of the slot, so the shortest pause is a moment when no
    background job runs at all: one CPU-bound job alone can fill the quota, and pausing only its neighbour would
    hand it the freed time and change nothing."""
    out = []
    for i, p in enumerate(cands):
        part = min(max_duty, level - i * JOIN)
        if part * slot < MIN_PAUSE_S:
            break
        out.append((p, part * slot))
    return out


class Guard:
    def __init__(self, meter=None, procs=None, kill=os.kill, sleep=time.sleep, clock=time.monotonic, log=None, on=ON,
                 high=CPU_HIGH, low=CPU_LOW, window=WINDOW_S):
        self.meter = meter or Meter(clock=clock)
        self.procs = procs or Procs(clock=clock, window=window)
        self.kill, self.sleep, self.clock, self.on = kill, sleep, clock, on
        self.log = log or (lambda s: print(s, flush=True))
        self.high, self.low = high, low
        self.window = collections.deque(maxlen=window)
        self.level = 0.0
        self.stopped = set()    # pids standing because of us right now
        self.resumed = {}       # pid -> clock of its last SIGCONT (it must run RUN_MIN_S before the next pause)
        self._errors = {}       # error text -> clock of its last log line
        self._reset_stats()

    # -- signals ------------------------------------------------------------------------------------------------
    def _stop(self, p):
        """SIGSTOP, unless the process has not yet had its run since the last pause or is no longer the one measured."""
        if self.clock() - self.resumed.get(p.pid, -1e9) < RUN_MIN_S or not self.procs.same(p):
            return False
        try:
            self.stopped.add(p.pid)   # written down first: if the signal lands and anything after it fails, it is continued
            self.kill(p.pid, signal.SIGSTOP)
            return True
        except OSError:               # ended in the meantime
            self.stopped.discard(p.pid)
            return False

    def _cont(self, pid):
        try:
            self.kill(pid, signal.SIGCONT)
        except OSError:
            pass
        self.stopped.discard(pid)
        self.resumed[pid] = self.clock()

    def resume_all(self):
        """SIGCONT to everything we stopped; called on every way out of a slot, a tick and the loop."""
        for pid in list(self.stopped):
            self._cont(pid)

    # -- one second -----------------------------------------------------------------------------------------------
    def _slot(self, victims):
        """Half a second: the victims stand for their part of it, then run for the rest."""
        t0 = self.clock()
        try:
            standing = [(p, s) for p, s in victims if self._stop(p)]
            for p, s in sorted(standing, key=lambda v: v[1]):
                self._wait(t0 + s)
                self._cont(p.pid)
                self._count(p.name, self.clock() - t0)
        finally:
            self.resume_all()
        self._wait(t0 + SLOT_S)

    def _wait(self, until):
        left = until - self.clock()
        if left > 0:
            self.sleep(left)

    def tick(self):
        """One second: read, decide, brake. Returns the percentage read (None when there was nothing to read)."""
        t0 = self.clock()
        pct = self.meter.read()
        victims = []
        if pct is not None:
            self.window.append(pct)
            avg = sum(self.window) / len(self.window)
            procs = self.procs.scan()
            cands = candidates(procs, self.procs.ours)
            if len(self.window) == self.window.maxlen:
                self.level = next_level(self.level, avg, len(cands), self.high, self.low)
            victims = plan(self.level, cands)
            self._note(pct, avg, procs, stuck=self.level >= ceiling(len(cands)) - 1e-9)
        if victims and self.on:
            for _ in range(int(TICK_S / SLOT_S)):
                self._slot(victims)
        else:
            for p, s in victims:   # CPUGUARD=0: what it would have done, for the log line
                self._count(p.name, s * TICK_S / SLOT_S)
        self._wait(t0 + TICK_S)
        for pid in [pid for pid, t in self.resumed.items() if self.clock() - t > 60]:
            del self.resumed[pid]
        return pct

    # -- the log line -----------------------------------------------------------------------------------------------
    def _reset_stats(self):
        self.n, self.total, self.peak, self.over = 0, 0.0, 0.0, 0
        self.pauses = {}     # name -> [times, seconds]
        self.blocked = None  # (name, pct): the biggest protected consumer while the CPU was high and the brake at its end
        self.thr0 = self.meter.throttled
        self.t_log = self.clock()

    def _count(self, name, seconds):
        c = self.pauses.setdefault(name, [0, 0.0])
        c[0] += 1
        c[1] += seconds

    def _note(self, pct, avg, procs, stuck=False):
        self.n += 1
        self.total += pct
        self.peak = max(self.peak, pct)
        self.over += pct > self.high
        if avg > self.high and stuck:   # too high and the brake has no more to give: say who holds the CPU
            top = max((p for p in procs if p.rank == PROTECTED), key=lambda p: p.pct, default=None)
            if top and top.pct >= MIN_CPU and (self.blocked is None or top.pct > self.blocked[1]):
                self.blocked = (top.name, top.pct)

    def line(self):
        """The minute's line: average, peak, how many pauses and of whom."""
        if not self.n:
            return "čuvar CPU-a: nema mjerenja (cgroup i /proc/stat se ne daju pročitati)"
        who = ", ".join(f"{n} {c} puta {s:.1f} s" for n, (c, s) in sorted(self.pauses.items(), key=lambda kv: -kv[1][1]))
        count = sum(c for c, _ in self.pauses.values())
        s = (f"čuvar CPU-a: prosjek {self.total / self.n:.0f} %, vrh {self.peak:.0f} %, "
             f"iznad {self.high:.0f} % {self.over} s od {self.n}, ")
        if self.on:
            s += f"pauza {count}" + (f" ({who})" if who else "")
        else:
            s += "pauziranje isključeno" + (f" (pauzirao bih: {who})" if who else "")
        thr = self.meter.throttled - self.thr0
        if thr:
            s += f", jezgra nas je kočila {thr} puta"
        if self.blocked:
            s += f"; najviše troši {self.blocked[0]} {self.blocked[1]:.0f} % (zaštićen, ne diram ga)"
        return s

    def start_line(self):
        m = self.meter
        never = ", ".join(n for n, _, _, k, _ in PROCESSES if k == PROTECTED)
        how = getattr(m, "cpus_from", None)
        return (f"čuvar CPU-a: izvor {m.source or 'nema'}, {m.cpus or 0:.2f} CPU" + (f" ({how})" if how else "")
                + f", pauze iznad {self.high:.0f} % (prosjek {self.window.maxlen} s) dok ne padne ispod {self.low:.0f} %"
                + ("" if self.on else ", pauziranje isključeno (samo mjerim)")
                + f"; nikad ne diram: {never}; KOL krug do {ROUND_CPU_S:.0f} s CPU-a")

    # -- the loop -----------------------------------------------------------------------------------------------------
    def _error(self, e):
        """One line per kind of error per minute; the guard carries on."""
        text = f"{type(e).__name__}: {e}"
        if self.clock() - self._errors.get(text, -1e9) >= LOG_EVERY_S:
            self._errors[text] = self.clock()
            self.log(f"čuvar CPU-a: greška, nastavljam ({text})")

    def run(self, ticks=None):
        """The loop. Whatever ends it (a signal, an exception, the end of `ticks`), nothing stays stopped."""
        try:
            left = sweep(self.kill, self.procs.proc)
            if left:
                self.log(f"čuvar CPU-a: pri startu su nastavljeni zaustavljeni procesi (pid {left})")
            self.meter.read()
            self.log(self.start_line())
            self._reset_stats()
            while ticks is None or ticks > 0:
                try:
                    self.tick()
                except Exception as e:  # noqa: BLE001 - a bad reading must not end the guard, nor leave anything stopped
                    self.resume_all()
                    self._error(e)
                    self.sleep(TICK_S)
                if self.clock() - self.t_log >= LOG_EVERY_S:
                    self.log(self.line())
                    self._reset_stats()
                ticks = None if ticks is None else ticks - 1
        finally:
            self.resume_all()
            sweep(self.kill, self.procs.proc)


def deadman(sweep_fn=sweep, log=None):
    """A forked twin that waits for this process to end and then continues whatever still stands stopped.
    try/finally and the signal handlers cover every end Python gets to see; a SIGKILL they do not, and keep would
    bring the guard (and its start sweep) back only 30 s later, with a background job frozen in the middle of a
    database write until then. Returns the pipe end the guard must keep open for as long as it lives."""
    r, w = os.pipe()
    if os.fork():
        os.close(r)
        return w
    try:   # the twin: no cleanup of the parent's, no way out but os._exit
        os.close(w)
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)   # a deploy's TERM reaches both; the twin must be the one that ends last
        while os.read(r, 1):
            pass
        done = sweep_fn()
        if done:
            (log or (lambda s: print(s, flush=True)))(
                f"čuvar CPU-a: čuvar je nestao; zaustavljeni procesi su nastavljeni (pid {done})")
    finally:
        os._exit(0)


def _on_signal(signum, frame):
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, signal.SIG_IGN)   # the way out (Guard.run's finally) must not be cut short by a second one
    raise SystemExit(0)


def popis():
    """The protected list with the reasons, as text."""
    def where(script, words):
        return script + (" " + "|".join(words) if words else "")
    rows = [f"  {n:<11} {where(s, w):<30} {rank_text(k):<9} {why}" for n, s, w, k, why in PROCESSES]
    return "\n".join(["čuvar CPU-a: tko nikad ne stoji (zaštićen) i kojim redom ostali smiju kratko stati (1. u redu "
                      "staje prvi i najdulje, unutar istog reda prvo onaj koji troši najviše; krug = zaštićen dok ne "
                      "potroši svoje, onda 3. u redu)"] + rows
                     + [f"  {'ostalo':<11} {'':<30} {rank_text(JOBS):<9} {OTHER_WHY}"])


def once(sleep=time.sleep):
    """One reading over a second and the table of our processes, for a look from the shell."""
    m, pr = Meter(), Procs()
    m.read()
    pr.scan()
    sleep(1)
    pct = m.read()
    print(f"izvor {m.source or 'nema'}, {m.cpus or 0:.2f} CPU ({m.cpus_from or '?'}), sada "
          + ("?" if pct is None else f"{pct:.0f} %"))
    for p in sorted(pr.scan(), key=lambda p: -p.pct):
        print(f"  {p.pid:>7} {p.name:<12} {rank_text(p.rank):<9} {p.pct:5.1f} %  {p.state}"
              + ("" if pr.ours(p) else "  (nije naš: drugi direktorij, ne diram ga)"))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--popis" in argv:
        print(popis())
        return 0
    if "--once" in argv:
        once()
        return 0
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, _on_signal)
    guard = Guard()
    try:
        keep_open = deadman()   # noqa: F841 - closed by the kernel when this process ends, which is the signal
    except OSError as e:
        print(f"čuvar CPU-a: rezervni nadzor nije pokrenut ({e}), radim bez njega", flush=True)
    guard.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
