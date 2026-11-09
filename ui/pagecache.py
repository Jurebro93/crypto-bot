"""Rendered-page cache for the dashboard, so a phone never waits for a page to be built.

Building the overview or the token list reads every hype signal (tens of thousands of rows, JSON per row) and on
Render's 0.5 CPU, shared with all the bot loops, that takes many seconds. Pages are kept here already rendered and
gzipped: a request inside FRESH_S gets the stored copy, an older copy (up to STALE_S) is served at once while one
background thread renders the new one (stale-while-revalidate), and only a page nobody opened for STALE_S is built
while the visitor waits. warm() renders the heaviest pages right after start, so the first visit after a deploy is
fast too. A POST (run button, trade) clears the cache so the next view shows the change.

The warmed pages are also saved to the server disk (snapshot). Memory is empty after every deploy and the first build
can take ~45 s while all bot loops start (4.11., /pregled), so a visitor then gets the last saved copy at once while
the new one is built in the background.
"""
import gzip
import os
import threading
import time

FRESH_S = int(os.environ.get("UI_CACHE_FRESH_S", "45"))
STALE_S = int(os.environ.get("UI_CACHE_STALE_S", "900"))
MAX_ENTRIES = 60
MAX_MB = float(os.environ.get("UI_CACHE_MAX_MB", "25"))   # gzipped bytes kept in all entries together
BUILDS = int(os.environ.get("UI_BUILDS", "1"))            # pages built at the same time (each holds its rows in RAM);
                                                          # 9.11.: one at a time, two children + corr + ui came near 2 GiB
SLOW_S = 2.0
_data = os.environ.get("DATA_DIR")
SNAP_DIR = os.environ.get("UI_SNAP_DIR") or (os.path.join(_data, "pagecache") if _data else "")
SNAP_MAX_S = int(os.environ.get("UI_SNAP_MAX_S", str(24 * 3600)))   # older snapshots are not served
_cleared_at = 0.0   # clear() time: a snapshot saved before it is out of date
_snap_paths = set()  # paths registered by warm(): only their plain view (no query, Croatian) is saved

_lock = threading.Lock()
_store = {}          # key -> (ts, code, None, gzipped bytes): only the gzipped copy is kept, run_ui unzips when needed
_build_slots = threading.BoundedSemaphore(BUILDS)
_busy = set()        # keys being rendered in the background
_inflight = {}       # key -> Event while some thread renders it: a second visitor waits for that one


def _pack(code, raw):
    return time.time(), code, None, gzip.compress(raw, 5)


def trim():
    from ops import mem   # the dashboard keeps a page build's memory otherwise
    mem.trim()


def _render(key, build):
    """Render once even when several threads ask at the same moment (0.5 CPU can't afford doing it twice)."""
    with _lock:
        ev = _inflight.get(key)
        mine = ev is None
        if mine:
            ev = _inflight[key] = threading.Event()
    if not mine:
        ev.wait(120)
        with _lock:
            hit = _store.get(key)
        if hit:
            return hit
    try:
        return _build(key, build)
    finally:
        if mine:
            with _lock:
                _inflight.pop(key, None)
            ev.set()


def _snap_file(key):
    if not SNAP_DIR or len(key) != 3 or key[1] or key[2] is not None or key[0] not in _snap_paths:
        return None
    return os.path.join(SNAP_DIR, (key[0].strip("/").replace("/", "_") or "index") + ".html.gz")


def _save_snap(key, gz):
    f = _snap_file(key)
    if not f:
        return
    try:
        os.makedirs(SNAP_DIR, exist_ok=True)
        tmp = f + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(gz)
        os.replace(tmp, f)
    except OSError:
        pass


def _load_snap(key):
    """(ts, 200, None, gz) from disk, dated so it counts as stale (a refresh starts), or None."""
    f = _snap_file(key)
    try:
        mt = os.path.getmtime(f) if f else 0
        if not f or time.time() - mt > SNAP_MAX_S or mt < _cleared_at:   # a POST changed data since
            return None
        with open(f, "rb") as fh:
            gz = fh.read()
    except OSError:
        return None
    return (time.time() - FRESH_S - 1, 200, None, gz) if gz else None


def _build(key, build):
    with _build_slots:
        t0 = time.time()
        code, raw = build()
        dt = time.time() - t0
    entry = _pack(code, raw)
    del raw
    trim()
    if dt > SLOW_S:
        print(f"ui: {key[0]} se gradio {dt:.1f} s", flush=True)
    if code == 200:
        _save_snap(key, entry[3])
        with _lock:
            _store[key] = entry
            old = sorted(_store.items(), key=lambda kv: kv[1][0])
            total = sum(len(v[3]) for _, v in old)
            while old and (len(_store) > MAX_ENTRIES or total > MAX_MB * 1e6) and old[0][0] != key:
                k, v = old.pop(0)
                _store.pop(k, None)
                total -= len(v[3])
    return entry


def _refresh(key, build):
    try:
        _render(key, build)
    except Exception as e:  # noqa: BLE001 - 5.11.: used to be silent, so a page could stay stale for days
        print(f"pagecache: osvježavanje {key[0]} palo: {type(e).__name__}: {str(e)[:120]}", flush=True)
    finally:
        with _lock:
            _busy.discard(key)


def get(key, build):
    """(code, raw, gz) for `key`; build() -> (code, raw bytes) renders the page. Only 200 answers are stored."""
    now = time.time()
    with _lock:
        hit = _store.get(key)
    if hit is None:   # right after a deploy: the copy saved on disk, refreshed in the background below
        snap = _load_snap(key)
        if snap:
            with _lock:
                hit = _store.setdefault(key, snap)
    with _lock:
        hit = _store.get(key)
        age = now - hit[0] if hit else None
        start_bg = hit is not None and FRESH_S <= age < STALE_S and key not in _busy
        if start_bg:
            _busy.add(key)
    if hit and age < FRESH_S:
        return hit[1:]
    if start_bg:
        threading.Thread(target=_refresh, args=(key, build), daemon=True, name="page-refresh").start()
        return hit[1:]
    if hit and age < STALE_S:      # someone else is already refreshing it
        return hit[1:]
    return _render(key, build)[1:]   # older than STALE_S: rebuilt now, so a broken build shows its error, not old data


def clear():
    global _cleared_at
    _cleared_at = time.time()
    with _lock:
        _store.clear()


def warm(paths, build_for, every_s=None):
    """Render `paths` in the background now (and every `every_s` seconds if given), one after another.
    Their plain views are also kept on disk (see SNAP_DIR)."""
    _snap_paths.update(paths)
    def run():
        while True:
            for p in paths:
                try:
                    _render((p, "", None), lambda p=p: build_for(p))
                except Exception:
                    pass
            if not every_s:
                return
            time.sleep(every_s)
    threading.Thread(target=run, daemon=True, name="page-warm").start()
