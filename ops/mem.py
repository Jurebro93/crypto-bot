"""Hand freed heap back to the OS after a big piece of work.

CPython keeps memory it once needed (e.g. a scan or a page that held tens of thousands of rows) for itself, so a
long-running loop otherwise stays at its highest point for good and the 512 MB server slowly fills up.
"""
import gc


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
        return self

    def __exit__(self, *_a):
        _DEPTH.n -= 1
        if self.r0 is not None:
            r1 = rss_mb()
            if r1 is not None and r1 - self.r0 > self.limit:
                try:
                    self.log(f"ui: {self.path} je podigao memoriju za {r1 - self.r0} MB")
                except Exception:  # noqa: BLE001 - the guard never breaks a page
                    pass
        return False
