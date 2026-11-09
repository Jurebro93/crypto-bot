"""One log line with memory per process and the data disk, so Render's log shows the trend.

  python3 -m ops.health            memory watchdog + the line (start.sh: watchdog every minute, line every 10)
  python3 -m ops.health --quiet    memory watchdog only
  python3 -m ops.health --tables   plus the biggest tables of each database over 20 MB
  python3 -m ops.health --startup  database upkeep before the loops start (ops/dbs.py)
  python3 -m ops.health --hourly   hourly database upkeep + HTTP cache trim
"""
import os
import sys

from ops import dbs, disk


def process_list():
    """[(pid, name, MB)] of this service's Python processes (name = run_<name>.py, 'ui-dijete' for a page-render
    child, or python)."""
    out = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmd = f.read().split(b"\0")
            if not cmd or b"python" not in os.path.basename(cmd[0]):
                continue
            script = next((os.path.basename(c.decode()) for c in cmd[1:] if c.endswith(b".py")), None)
            name = script[4:-3] if script and script.startswith("run_") else (script or "python")
            if name == "ui" and b"--render" in cmd:
                name = "ui-dijete"
            with open(f"/proc/{pid}/status") as f:
                kb = next(int(l.split()[1]) for l in f if l.startswith("VmRSS"))
        except (OSError, StopIteration, ValueError):
            continue
        out.append((int(pid), name, kb / 1024))
    return out


def processes():
    """[(name, MB)] summed per name, biggest first."""
    out = {}
    for _pid, name, mb in process_list():
        out[name] = out.get(name, 0) + mb
    return sorted(out.items(), key=lambda x: -x[1])


MEM_KILL_MB = float(os.environ.get("MEM_KILL_MB", "800"))   # one process this big is a leak on a 2 GB plan
SPARE = {"trade": 1.5}   # the real-money process gets more room before it is restarted


def over_limit(procs, limit_mb=None):
    """[(pid, name, MB)] of processes a watchdog should stop: above limit_mb (SPARE[name] × for the trade process)."""
    limit_mb = limit_mb or MEM_KILL_MB
    return [(pid, name, mb) for pid, name, mb in procs if mb > limit_mb * SPARE.get(name, 1.0)]


def watchdog(limit_mb=None, procs=None, kill=None, log=print):
    """9.11. 12:30 and 12:56: the UI process grew to 1.6 GB and Render killed the WHOLE service (OOM 2 GiB), the trade
    process with it. A single runaway process is stopped here instead (SIGTERM); start.sh's keep brings it back in
    30 s and the rest keeps running. Returns the processes stopped."""
    import signal
    kill = kill or (lambda pid: os.kill(pid, signal.SIGTERM))
    hit = over_limit(process_list() if procs is None else procs, limit_mb)
    for pid, name, mb in hit:
        log(f"nadzor memorije: {name} (pid {pid}) drži {mb:.0f} MB, više od {(limit_mb or MEM_KILL_MB) * SPARE.get(name, 1.0):.0f}: "
            "gasim ga da Render ne ugasi cijeli servis; keep ga vraća za 30 s", flush=True)
        try:
            kill(pid)
        except OSError as e:
            log(f"nadzor memorije: {name} (pid {pid}) nije ugašen: {e}", flush=True)
    return hit


def container_split_mb():
    """(anon, file) MB from the cgroup: anon = what processes really hold, file = page cache the kernel drops under
    pressure. 5.11.: the health line said 'RAM 2005 MB' on a 2 GB plan while Render's own metric showed 1.0 GB; the
    difference was cache, not a leak."""
    for p in ("/sys/fs/cgroup/memory.stat", "/sys/fs/cgroup/memory/memory.stat"):
        try:
            with open(p) as f:
                kv = dict(line.split()[:2] for line in f if line.strip())
            anon = int(kv.get("anon") or kv.get("rss") or 0) / 2**20
            file = int(kv.get("file") or kv.get("cache") or 0) / 2**20
            return anon, file
        except (OSError, ValueError):
            pass
    return None, None


def container_mb():
    for p in ("/sys/fs/cgroup/memory.current", "/sys/fs/cgroup/memory/memory.usage_in_bytes"):
        try:
            with open(p) as f:
                return int(f.read()) / 2**20
        except (OSError, ValueError):
            pass
    return None


def container_limit_mb():
    """The cgroup memory limit in MB (Render plan), or the machine's MemTotal when the cgroup says 'max'; None if unknown."""
    for p in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            with open(p) as f:
                v = f.read().strip()
            if v != "max" and int(v) < 2**50:
                return int(v) / 2**20
        except (OSError, ValueError):
            pass
    try:
        with open("/proc/meminfo") as f:
            for ln in f:
                if ln.startswith("MemTotal:"):
                    return int(ln.split()[1]) / 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def container_free_mb():
    """MB the processes could still take: limit minus what they hold (anon). Page cache is not counted as used, the
    kernel drops it under pressure. None when the cgroup does not say. 9.11. 19:05: the page build waited 60 s on the
    heavy lock behind run_dugo (29 min) and wallets score while 1.2 GB were free; the lock is about memory, so a build
    may go next to a heavy job when there is room."""
    limit = container_limit_mb()
    anon, _ = container_split_mb()
    if limit is None or anon is None:
        return None
    return max(0.0, limit - anon)


def line(tables=False):
    procs = processes()
    total = container_mb()
    files = []
    for p in dbs.files():
        mb = (os.path.getsize(p) + (os.path.getsize(p + "-wal") if os.path.exists(p + "-wal") else 0)) / 1e6
        files.append((os.path.basename(p), mb, p))
    files.sort(key=lambda x: -x[1])
    used = 0.0
    for root, _, names in os.walk(disk.DATA_DIR):
        for n in names:
            try:
                used += os.path.getsize(os.path.join(root, n)) / 1e6
            except OSError:
                pass
    free = disk.free_mb()
    anon, cache = container_split_mb()
    s = (f"zdravlje: RAM {total:.0f} MB" + (f" (procesi {anon:.0f}, cache {cache:.0f})" if anon is not None else "")
         if total is not None else "zdravlje: RAM ?") \
        + f" (python {sum(m for _, m in procs):.0f} MB: " + ", ".join(f"{n} {m:.0f}" for n, m in procs[:8]) + ")" \
        + f" | disk {used:.0f} MB zauzeto, {free:.0f} MB slobodno" \
        + " | " + ", ".join(f"{n} {mb:.0f}" for n, mb, _ in files[:8])
    print(s, flush=True)
    if tables:
        for n, mb, p in files:
            if mb >= 20:
                print(f"zdravlje: {n} najveće tablice: "
                      + ", ".join(f"{t} {m:.0f} MB" for t, m in dbs.table_sizes(p)), flush=True)


def main(argv):
    if "--startup" in argv or "--hourly" in argv:
        from event_calendar import http   # HTTP cache first: it shares the disk the databases need to work
        free = disk.free_mb() or 0
        n, mb = http.prune(max_mb=100 if free < 250 else None)   # tight disk: the cache gives way to the databases
        print(f"cache: obrisano {n} datoteka, {mb:.0f} MB", flush=True)
    if "--startup" in argv:
        dbs.startup()
    elif "--hourly" in argv:
        dbs.hourly()
        line(tables=True)
    else:
        watchdog()
        if "--quiet" not in argv:   # start.sh: the watchdog runs every minute, the log line every 10 minutes
            line(tables="--tables" in argv)


if __name__ == "__main__":
    main(sys.argv[1:])
