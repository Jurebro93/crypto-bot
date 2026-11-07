"""One heavy job at a time on the 512 MB server.

Each bot loop runs its big work in a short child process (it gives its memory back when it ends), but on 2.11. the
server still ran out of memory every ~2 hours: the KOL round (~120 MB), a scheduler job, the wallet scan and a page
build happened to run at the same moment. Every heavy child now takes this lock first, so they run one after
another instead of on top of each other. The lock is a file lock: it is released when its holder ends or dies.

    python3 -m ops.heavy run_wallets.py score ...   # run a command under the lock (used by start.sh)
    with heavy.slot(wait=0) as got: ...              # in Python; wait=None blocks, 0 = skip if busy, N = seconds
"""
import contextlib
import fcntl
import os
import subprocess
import sys
import time

LOCK = os.environ.get("HEAVY_LOCK", "/tmp/memesonar-heavy.lock")
PRIO_MAX_AGE = 4 * 3600   # a priority ticket older than this is stale (its holder died without cleaning up)


def _prio_path():
    return LOCK + ".prio"


def _prio_waiting():
    """True while a priority caller (the KOL backfill) is waiting for the lock: others let it go first."""
    try:
        return time.time() - os.path.getmtime(_prio_path()) < PRIO_MAX_AGE
    except OSError:
        return False


def _who_path():
    return LOCK + ".who"


def holder():
    """'cmd (od HH:MM UTC)' of the job holding the lock, as it wrote itself; '' when unknown."""
    try:
        with open(_who_path()) as f:
            return f.read().strip()
    except OSError:
        return ""


def _label(args):
    """'run_learn.py masovno' for [python, /app/run_learn.py, masovno]: the interpreter dropped, paths shortened."""
    return " ".join(os.path.basename(str(a)) for a in args if str(a) != sys.executable) or "?"


@contextlib.contextmanager
def slot(wait=None, priority=False, label=None):
    """True once this process holds the heavy-job lock (until the block ends); False if `wait` ran out.
    priority=True: others queueing for the lock step aside until this one has it. 6.11.: the backfill queued at
    00:30 and was still waiting at 01:30 because the 30-min scheduler jobs kept taking the lock from each other
    (flock has no queue); it starts the night's work only once, so it goes first."""
    f = open(LOCK, "a")
    got = False
    if priority:
        try:
            with open(_prio_path(), "w") as pf:
                pf.write(str(os.getpid()))
        except OSError:
            priority = False
    try:
        t0, told = time.time(), 0
        while True:
            # 7.11. 10:40: after a deploy the 6-hourly token status waited 40+ min behind the start-up jobs and nobody
            # could tell which one held the lock. Now the holder writes itself down and a waiter says so after 2 min.
            if time.time() - t0 >= told + 120:
                told = time.time() - t0
                print(f"brava: {label or 'posao'} čeka već {told / 60:.0f} min, drži je {holder() or 'nepoznat posao'}",
                      flush=True)
            if not priority and _prio_waiting():
                if wait is not None and time.time() - t0 >= wait:
                    break
                time.sleep(1)
                continue
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                got = True
                break
            except BlockingIOError:
                if wait is not None and time.time() - t0 >= wait:
                    break
                time.sleep(1)
        if got:
            try:
                with open(_who_path(), "w") as wf:
                    wf.write(f"{label or 'posao'} (od {time.strftime('%H:%M', time.gmtime())} UTC, pid {os.getpid()})")
            except OSError:
                pass
        if priority:
            try:
                os.remove(_prio_path())
            except OSError:
                pass
        yield got
    finally:
        if got:
            fcntl.flock(f, fcntl.LOCK_UN)
        f.close()
        if priority:
            try:
                os.remove(_prio_path())
            except OSError:
                pass


def run(args, wait=None, priority=False, **kw):
    """subprocess.run(args, **kw) under the lock; None if the lock was busy for longer than `wait` seconds."""
    with slot(wait, priority=priority, label=_label(args)) as got:
        if not got:
            return None
        return subprocess.run(args, **kw)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    priority = False
    if argv and argv[0] == "--prio":
        priority = True
        argv = argv[1:]
    if not argv:
        sys.exit("upotreba: python3 -m ops.heavy [--prio] SKRIPTA.py [argumenti]")
    if argv[0].endswith(".py") or argv[0] == "-m":
        argv = [sys.executable] + argv
    return run(argv, priority=priority).returncode


if __name__ == "__main__":
    sys.exit(main())
