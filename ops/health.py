"""One log line with memory per process and the data disk, so Render's log shows the trend.

  python3 -m ops.health            the line (start.sh runs it every 10 min)
  python3 -m ops.health --tables   plus the biggest tables of each database over 20 MB
  python3 -m ops.health --startup  database upkeep before the loops start (ops/dbs.py)
  python3 -m ops.health --hourly   hourly database upkeep + HTTP cache trim
"""
import os
import sys

from ops import dbs, disk


def processes():
    """[(name, MB)] of this service's Python processes, biggest first (name = run_<name>.py, or python)."""
    out = {}
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
            with open(f"/proc/{pid}/status") as f:
                kb = next(int(l.split()[1]) for l in f if l.startswith("VmRSS"))
        except (OSError, StopIteration, ValueError):
            continue
        out[name] = out.get(name, 0) + kb / 1024
    return sorted(out.items(), key=lambda x: -x[1])


def container_mb():
    for p in ("/sys/fs/cgroup/memory.current", "/sys/fs/cgroup/memory/memory.usage_in_bytes"):
        try:
            with open(p) as f:
                return int(f.read()) / 2**20
        except (OSError, ValueError):
            pass
    return None


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
    s = (f"zdravlje: RAM {total:.0f} MB" if total is not None else "zdravlje: RAM ?") \
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
        line(tables="--tables" in argv)


if __name__ == "__main__":
    main(sys.argv[1:])
