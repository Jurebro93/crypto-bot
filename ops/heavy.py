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


@contextlib.contextmanager
def slot(wait=None, priority=False):
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
        t0 = time.time()
        while True:
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
    with slot(wait, priority=priority) as got:
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
