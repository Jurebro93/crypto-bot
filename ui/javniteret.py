"""Javne stranice pod naletom crawlera (23.11.2026., hitno).

Production 20.-23.11.: the UI process was stopped by the memory watchdog 11 times in 2.5 days, every time with 8+
public per-entity pages in flight at once (/telegram/<kanal>, /influencer/<h>, /macro-influencer/<h>,
/coin/<x>/price-prediction), each 100-330 s. Measured offline (tests/test_ui_javni_teret_offline.py): a page that
reads a few thousand SQLite rows takes 0.01 s alone but 15 s when 12 threads do it at once in one process, because
Python's sqlite3 gives the GIL back and takes it again for every row it steps (a convoy: with more threads than cores
each row waits for the switch interval). The requests then pile up, every new crawler request is one more thread,
and memory climbs with the pile. Two guards here:

  gate  slot(): at most UI_PUBLIC_BUILDS (2) public, uncached page builds at once; a request that does not get a
        slot within UI_PUBLIC_WAIT_S (3 s), or that comes while this process is above UI_MEM_SHED_MB (600), gets
        503 + Retry-After: 120 and a tiny body (crawlers come back later). Cached copies, logged-in visitors, the
        app pages, /healthz, static files and POST /hook/* never come here. One log line a minute at most:
        "ui: odbijeno N javnih zahtjeva (zauzeto / memorija N MB)".
  memo  shared(): one copy per process of data every page of a kind needs (the channel list, the influencer rows,
        the macro view), built by ONE thread while the others wait for it, kept ttl_s (and/or until `version`
        changes), so a burst reads the database once instead of once per request.
"""
import os
import threading
import time

SLOTS = max(1, int(os.environ.get("UI_PUBLIC_BUILDS") or 2))
WAIT_S = float(os.environ.get("UI_PUBLIC_WAIT_S") or 3)
SHED_MB = float(os.environ.get("UI_MEM_SHED_MB") or 600)
RETRY_AFTER = 120
BODY = b"Busy, please retry later.\n"
LOG_EVERY_S = 60

_sem = threading.BoundedSemaphore(SLOTS)
_log_lock = threading.Lock()
_refused = {"t": 0.0, "busy": 0, "mem": 0, "mb": None}


class Refused(Exception):
    """No slot for a public build (busy or memory); the caller answers 503 + Retry-After."""


def _rss():
    from ops import mem
    return mem.rss_mb()


def _note(kind, mb=None, log=None, now=None):
    """Count one refusal; one line per LOG_EVERY_S with what was counted since the last line."""
    now = now or time.time()
    with _log_lock:
        _refused[kind] += 1
        if mb is not None:
            _refused["mb"] = mb
        if now - _refused["t"] < LOG_EVERY_S:
            return None
        n = _refused["busy"] + _refused["mem"]
        parts = (["zauzeto"] if _refused["busy"] else []) + (
            [f"memorija {_refused['mb']} MB"] if _refused["mem"] else [])
        line = f"ui: odbijeno {n} javnih zahtjeva ({' / '.join(parts)})"
        _refused.update(t=now, busy=0, mem=0, mb=None)
    try:
        (log or (lambda m: print(m, flush=True)))(line)
    except Exception:  # noqa: BLE001 - the guard never breaks a page
        pass
    return line


class slot:
    """with slot(): <build one public page>  -> raises Refused instead of entering when it may not build now."""

    def __init__(self, wait_s=None, log=None):
        self.wait_s = WAIT_S if wait_s is None else wait_s
        self.log = log
        self.held = False

    def __enter__(self):
        mb = _rss()
        if mb is not None and mb > SHED_MB:
            _note("mem", mb, self.log)
            raise Refused(f"memorija {mb} MB")
        if not _sem.acquire(timeout=self.wait_s):
            _note("busy", None, self.log)
            raise Refused("zauzeto")
        self.held = True
        return self

    def __exit__(self, *_a):
        if self.held:
            self.held = False
            _sem.release()
        return False


# ---------- shared, single-flight copies --------------------------------------------------------------------------

_mlock = threading.Lock()
_memo = {}        # key -> (monotonic ts, version, value)
_building = {}    # key -> Event while one thread builds it


def shared(key, ttl_s, build, version=None, wait_s=120):
    """build() once per key for ttl_s seconds (and while `version` stays the same); concurrent callers wait for the
    thread that builds it instead of building it themselves. The value is shared: callers must not change it.
    A failing build raises in the building thread; the waiting ones then try once themselves."""
    with _mlock:
        hit = _memo.get(key)
        if hit and time.monotonic() - hit[0] < ttl_s and hit[1] == version:
            return hit[2]
        ev = _building.get(key)
        mine = ev is None
        if mine:
            ev = _building[key] = threading.Event()
    if not mine:
        done = ev.wait(wait_s)
        with _mlock:
            hit = _memo.get(key)
        if done and hit and hit[1] == version:
            return hit[2]
        return build()   # the builder failed or hangs: this caller builds its own copy (not kept)
    try:
        value = build()
        with _mlock:
            _memo[key] = (time.monotonic(), version, value)
        return value
    finally:
        if mine:
            with _mlock:
                _building.pop(key, None)
            ev.set()


def file_version(path):
    """(mtime, size) of a SQLite file and its -wal: a shared copy keyed by it is rebuilt after a write."""
    out = []
    for f in (path, path + "-wal"):
        try:
            st = os.stat(f)
            out += [st.st_mtime_ns, st.st_size]
        except (OSError, TypeError):
            out += [None, None]
    return tuple(out)


def forget(prefix=None):
    """Drop the shared copies (all, or those whose key starts with `prefix` when the key is a tuple)."""
    with _mlock:
        for k in list(_memo):
            if prefix is None or (isinstance(k, tuple) and k[:len(prefix)] == prefix):
                _memo.pop(k, None)
