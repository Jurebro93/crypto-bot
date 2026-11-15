"""oscilator.db: the walk-forward runs and today's top list (run_oscilator.py writes it; the demo trades, the page, the
MCP tool, the critic and the real-money gate only read it).

    runs  one row per run: ts, data (JSON: coverage, the walk-forward per size and target, the range scalp next to it,
          the fee table, the top list); the last RUNS_KEEP
    kv    top (today's top K with their day-D metrics), proof (the walk-forward numbers the gate reads), last_ts,
          last_day (the Zagreb day the nightly run is done for)

On the persistent disk (OSCILATOR_DB, else DATA_DIR/oscilator.db, else next to the code). Small: tens of kB a run.
"""
import json
import os
import sqlite3
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS_KEEP = 30
CACHE_S = 60
SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (ts INTEGER PRIMARY KEY, data TEXT);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""
_CACHE = {}


def db_path():
    if os.environ.get("OSCILATOR_DB"):
        return os.environ["OSCILATOR_DB"]
    data = os.environ.get("DATA_DIR")
    if data and os.path.isdir(data):
        return os.path.join(data, "oscilator.db")
    return os.path.join(ROOT, "oscilator.db")


def connect(path=None):
    con = sqlite3.connect(path or db_path(), timeout=30)
    con.executescript(SCHEMA)
    return con


def ro(path=None):
    path = path or db_path()
    if not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        con.execute("SELECT 1 FROM kv LIMIT 1")
        return con
    except sqlite3.Error:
        return None


def kv_get(con, k, default=None):
    r = con.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    if not r:
        return default
    try:
        return json.loads(r[0])
    except (TypeError, ValueError):
        return default


def kv_put(con, k, v):
    con.execute("INSERT OR REPLACE INTO kv (k, v) VALUES (?, ?)", (k, json.dumps(v, ensure_ascii=False)))


def proof_of(data):
    """The numbers the real-money gate reads: per size@target the walk-forward top-K stats (n, ev, CI, $/day)."""
    keep = ("n", "ev_pct", "ev_usd", "ci90_ev_pct", "usd_day", "ci90_usd_day", "hit", "max_dd_usd", "worst_day_usd",
            "per_token_day", "broke_share", "ev_demo_pct", "token_days")
    return {"ts": data.get("ts"), "days": (data.get("walk") or {}).get("days"),
            "sizes": {k: {f: v.get(f) for f in keep} for k, v in ((data.get("walk") or {}).get("top") or {}).items()}}


def save(data, now=None, path=None):
    now = int(now or time.time())
    from . import scan
    con = connect(path)
    try:
        con.execute("INSERT OR REPLACE INTO runs (ts, data) VALUES (?, ?)", (now, json.dumps(data, ensure_ascii=False)))
        con.execute("DELETE FROM runs WHERE ts NOT IN (SELECT ts FROM runs ORDER BY ts DESC LIMIT ?)", (RUNS_KEEP,))
        kv_put(con, "top", {"ts": now, "day": data.get("top_day"), "tokens": data.get("top") or []})
        kv_put(con, "proof", proof_of(data))
        kv_put(con, "last_ts", now)
        if data.get("mode") == "night":
            kv_put(con, "last_day", scan.day_of(now))
        con.commit()
    finally:
        con.close()
    _CACHE.clear()


def _cached(k, path=None):
    hit = _CACHE.get((k, path))
    if hit and time.time() - hit[0] < CACHE_S:
        return hit[1]
    con = ro(path)
    v = None
    if con is not None:
        try:
            v = kv_get(con, k)
        except sqlite3.Error:
            v = None
        finally:
            con.close()
    _CACHE[(k, path)] = (time.time(), v)
    return v


def top(path=None):
    """{"ts", "day", "tokens": [...]} of the newest run, or None."""
    return _cached("top", path)


def proof(path=None):
    return _cached("proof", path)


def latest(path=None):
    """(ts, data) of the newest run, (None, None) without one."""
    con = ro(path)
    if con is None:
        return None, None
    try:
        r = con.execute("SELECT ts, data FROM runs ORDER BY ts DESC LIMIT 1").fetchone()
    except sqlite3.Error:
        r = None
    finally:
        con.close()
    if not r:
        return None, None
    try:
        return r[0], json.loads(r[1])
    except (TypeError, ValueError):
        return r[0], None


def last(path=None):
    con = ro(path)
    if con is None:
        return None, None
    try:
        return kv_get(con, "last_ts"), kv_get(con, "last_day")
    finally:
        con.close()


def reset_cache():
    _CACHE.clear()
