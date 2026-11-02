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


@contextlib.contextmanager
def slot(wait=None):
    """True once this process holds the heavy-job lock (until the block ends); False if `wait` ran out."""
    f = open(LOCK, "a")
    got = False
    try:
        t0 = time.time()
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                got = True
                break
            except BlockingIOError:
                if wait is not None and time.time() - t0 >= wait:
                    break
                time.sleep(1)
        yield got
    finally:
        if got:
            fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def run(args, wait=None, **kw):
    """subprocess.run(args, **kw) under the lock; None if the lock was busy for longer than `wait` seconds."""
    with slot(wait) as got:
        if not got:
            return None
        return subprocess.run(args, **kw)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        sys.exit("upotreba: python3 -m ops.heavy SKRIPTA.py [argumenti]")
    if argv[0].endswith(".py") or argv[0] == "-m":
        argv = [sys.executable] + argv
    return run(argv).returncode


if __name__ == "__main__":
    sys.exit(main())
