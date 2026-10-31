"""Rendered-page cache for the dashboard, so a phone never waits for a page to be built.

Building the overview or the token list reads every hype signal (tens of thousands of rows, JSON per row) and on
Render's 0.5 CPU, shared with all the bot loops, that takes many seconds. Pages are kept here already rendered and
gzipped: a request inside FRESH_S gets the stored copy, an older copy (up to STALE_S) is served at once while one
background thread renders the new one (stale-while-revalidate), and only a page nobody opened for STALE_S is built
while the visitor waits. warm() renders the heaviest pages right after start, so the first visit after a deploy is
fast too. A POST (run button, trade) clears the cache so the next view shows the change.
"""
import gzip
import os
import threading
import time

FRESH_S = int(os.environ.get("UI_CACHE_FRESH_S", "45"))
STALE_S = int(os.environ.get("UI_CACHE_STALE_S", "900"))
MAX_ENTRIES = 60
MAX_MB = float(os.environ.get("UI_CACHE_MAX_MB", "25"))   # gzipped bytes kept in all entries together
BUILDS = int(os.environ.get("UI_BUILDS", "2"))            # pages built at the same time (each holds its rows in RAM)
SLOW_S = 2.0

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
    except Exception:
        pass
    finally:
        with _lock:
            _busy.discard(key)


def get(key, build):
    """(code, raw, gz) for `key`; build() -> (code, raw bytes) renders the page. Only 200 answers are stored."""
    now = time.time()
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
    return _render(key, build)[1:]


def clear():
    with _lock:
        _store.clear()


def warm(paths, build_for, every_s=None):
    """Render `paths` in the background now (and every `every_s` seconds if given), one after another."""
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
