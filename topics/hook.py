"""The PumpPortal feed's hook (live/pumpportal.Feed.flush, run_live.py): every new pump.fun token and every migration
is string-matched against the keywords of the active event topics the moment it arrives. Matching only (no network,
no paid call); a match is queued and written into topics.db by a daemon thread, so the feed never waits on a
database (it is on the money path: followed wallets' buys). run_topics.py catches up from hype.db live_launches every
pass anyway (INSERT OR IGNORE), so a match lost in a restart is found within minutes.

The keywords are re-read from topics.db (read-only, a few rows) at most every REFRESH_S; with the flag event_tokens
off or no active topic the hook returns at once.
"""
import collections
import sys
import threading
import time

REFRESH_S = 60
FLUSH_S = 2.0
_STATE = {"at": -1e9, "matcher": None, "thread": None, "err_at": 0.0}
_Q = collections.deque(maxlen=5000)
_LOCK = threading.Lock()


def _quiet(e):
    now = time.time()
    if now - _STATE["err_at"] > 300:
        _STATE["err_at"] = now
        print(f"eventi: kuka PumpPortala nije uspjela ({type(e).__name__}: {e})", file=sys.stderr, flush=True)


def matcher(now=None, path=None):
    """The compiled keywords of the active topics, refreshed at most every REFRESH_S; None while off or empty."""
    now = now or time.monotonic()
    if now - _STATE["at"] < REFRESH_S:
        return _STATE["matcher"]
    _STATE["at"] = now
    from topics import match, store
    m = None
    if store.mode() != "off":
        con = store.ro(path)
        if con is not None:
            try:
                kws = {t["id"]: t["keywords"] for t in store.topics(con, store.ACTIVE)}
            finally:
                con.close()
            m = match.Matcher(kws) or None
    _STATE["matcher"] = m
    return m


def launches(rows, now=None, path=None):
    """rows: live_launches tuples (mint, ts, creator, name, symbol, initial_sol, sig, pool). Returns the matches
    queued. Never raises."""
    try:
        m = matcher(path=path)
        if not m or not rows:
            return 0
        n = 0
        for r in rows:
            mint, ts, name, sym, pool = r[0], r[1], r[3], r[4], r[7]
            for tid, (field, kw) in m.match(sym, name).items():
                mig = pool == "migration"
                _Q.append((tid, mint, int(ts or now or time.time()), field, kw,
                           "pumpportal_migration" if mig else "pumpportal_create", sym, name, None if mig else ts))
                n += 1
        if n:
            _start(path)
        return n
    except Exception as e:  # noqa: BLE001 - the feed must never notice
        _quiet(e)
        return 0


def flush(path=None):
    """Write what is queued (the thread calls it; the tests call it directly). Returns rows written."""
    with _LOCK:
        if not _Q:
            return 0
        batch = [_Q.popleft() for _ in range(len(_Q))]
        try:
            from topics import store
            con = store.connect(path)
            try:
                for tid, mint, ts, field, kw, via, sym, name, created in batch:
                    if store.add_match(con, tid, mint, ts, field, kw, via, sym, name, created):
                        print(f"eventi: {sym or mint[:6]} ({kw}, {via}) odgovara temi #{tid}", flush=True)
                con.commit()
            finally:
                con.close()
            return len(batch)
        except Exception as e:  # noqa: BLE001
            _Q.extendleft(reversed(batch))
            _quiet(e)
            return 0


def _loop(path):
    while True:
        time.sleep(FLUSH_S)
        try:
            flush(path)
        except Exception as e:  # noqa: BLE001
            _quiet(e)


def _start(path=None):
    t = _STATE["thread"]
    if t is None or not t.is_alive():
        t = threading.Thread(target=_loop, args=(path,), name="eventi-kuka", daemon=True)
        _STATE["thread"] = t
        t.start()
