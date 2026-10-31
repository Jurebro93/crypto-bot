"""Free space on the data disk. When it runs low, caches stop writing so the databases keep room to work
(a full disk made every SQLite write fail and crashed the loops on start)."""
import os
import shutil
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("DATA_DIR") or HERE
MIN_FREE_MB = float(os.environ.get("DISK_MIN_FREE_MB", "100"))
_last = [0.0, None, 0.0]   # checked at, free MB, last warning


def free_mb(path=None):
    try:
        return shutil.disk_usage(path or (DATA_DIR if os.path.isdir(DATA_DIR) else HERE)).free / 1e6
    except OSError:
        return None


def low(what="cache"):
    """True when the data disk has less than MIN_FREE_MB free (checked at most every 30 s); warns in the log
    at most every 10 min. Callers skip non-essential writes (caches, raw API answers) when it is True."""
    now = time.time()
    if now - _last[0] > 30:
        _last[0], _last[1] = now, free_mb()
    free = _last[1]
    if free is None or free >= MIN_FREE_MB:
        return False
    if now - _last[2] > 600:
        _last[2] = now
        print(f"disk: slobodno samo {free:.0f} MB (< {MIN_FREE_MB:.0f} MB), preskačem upis: {what}", flush=True)
    return True
