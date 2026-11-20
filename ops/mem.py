"""Hand freed heap back to the OS after a big piece of work.

CPython keeps memory it once needed (e.g. a scan or a page that held tens of thousands of rows) for itself, so a
long-running loop otherwise stays at its highest point for good and the 512 MB server slowly fills up.
"""
import gc
import os
import sys
import time


def trim():
    gc.collect()
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass


RAISE_LOG_MB = 150   # 20.11. (2): a page build that raises the UI process this much is named in the log


def rss_mb():
    """This process's resident memory in MB (/proc/self/status VmRSS), None where it cannot be read."""
    try:
        with open("/proc/self/status", encoding="ascii") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


_DEPTH = __import__("threading").local()
_ACTIVE = {}          # id(watch) -> (path, started): the outer blocks running now, for the sampler's line
WARN_MB = float(os.environ.get("UI_MEM_WARN_MB", "550"))   # the UI idles near 300 MB; the watchdog stops it at 800


class watch:
    """with watch(path): ... -> one line "ui: <path> je podigao memoriju za N MB" when the block raised this process's
    RSS by more than RAISE_LOG_MB (20.11. (2): the UI process went 311 -> 1561 MB in 3 minutes and the log could not
    say which page). A block inside another watched block (a request that builds its page) is counted once, by the
    outer one. Never raises."""

    def __init__(self, path, log=None, limit_mb=None):
        self.path, self.log = path, log or (lambda m: print(m, flush=True))
        self.limit = RAISE_LOG_MB if limit_mb is None else limit_mb

    def __enter__(self):
        self.outer = not getattr(_DEPTH, "n", 0)
        _DEPTH.n = getattr(_DEPTH, "n", 0) + 1
        self.r0 = rss_mb() if self.outer else None
        if self.outer:
            _ACTIVE[id(self)] = (self.path, time.time())
        return self

    def __exit__(self, *_a):
        _DEPTH.n -= 1
        _ACTIVE.pop(id(self), None)
        if self.r0 is not None:
            r1 = rss_mb()
            if r1 is not None and r1 - self.r0 > self.limit:
                try:
                    self.log(f"ui: {self.path} je podigao memoriju za {r1 - self.r0} MB")
                except Exception:  # noqa: BLE001 - the guard never breaks a page
                    pass
        return False


def active(now=None):
    """"/a (12 s), /b (3 s)": the watched blocks running now, the longest first; "ništa" when none."""
    now = now or time.time()
    rows = sorted(list(_ACTIVE.values()), key=lambda r: r[1])
    return ", ".join(f"{p} ({now - t:.0f} s)" for p, t in rows[:8]) or "ništa"


def sample(state, log=None, now=None, dump=None):
    """One reading of the sampler. Above WARN_MB: one line "ui: memorija N MB, u tijeku: <paths>", again only after
    60 s or another 150 MB, and the stacks of all threads (faulthandler, stderr) at most once in 10 minutes, so the log
    names the code even when it is not a page and even when the watchdog stops the process before the block ends
    (20.11. (2): watch() alone writes its line only after the block). Returns the line or None. Never raises."""
    try:
        now = now or time.time()
        r = rss_mb()
        if r is None or r < WARN_MB:
            return None
        if now - state.get("t", 0) < 60 and r - state.get("r", 0) < RAISE_LOG_MB:
            return None
        state["t"], state["r"] = now, r
        line = f"ui: memorija {r} MB, u tijeku: {active(now)}"
        (log or (lambda m: print(m, flush=True)))(line)
        if now - state.get("dump", 0) >= 600:
            state["dump"] = now
            if dump is None:
                import faulthandler
                faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
            else:
                dump()
        return line
    except Exception:  # noqa: BLE001 - the guard never breaks the UI
        return None


def sampler_loop(every=2.0):
    """The UI's daemon thread: sample() every 2 s (one read of /proc/self/status)."""
    state = {}
    while True:
        time.sleep(every)
        sample(state)
