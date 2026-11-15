"""konsenzus.db: the research runs and the current best candidate (konsenzus/research writes it; the live entries,
the page, the MCP tool and the critic only read it).

    runs  one row per run: ts, data (JSON: every candidate's train / holdout numbers, coverage, assumptions); the last
          RUNS_KEEP
    kv    best (JSON: the chosen candidate, its parameters, holdout numbers, proof, and the CURRENT source selection the
          live entries use), last_day (the Zagreb day the nightly run is done for), last_ts

On the persistent disk (KONSENZUS_DB, else DATA_DIR/konsenzus.db, else next to the code). Small: a few hundred kB.
"""
import json
import os
import sqlite3
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS_KEEP = 20
CACHE_S = 60
SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (ts INTEGER PRIMARY KEY, data TEXT);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""
_CACHE = {}


def db_path():
    if os.environ.get("KONSENZUS_DB"):
        return os.environ["KONSENZUS_DB"]
    data = os.environ.get("DATA_DIR")
    if data and os.path.isdir(data):
        return os.path.join(data, "konsenzus.db")
    return os.path.join(ROOT, "konsenzus.db")


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
    con.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)", (k, json.dumps(v, ensure_ascii=False, default=str)))


def save(con, data, best, now=None):
    now = int(now or time.time())
    con.execute("INSERT OR REPLACE INTO runs VALUES (?, ?)", (now, json.dumps(data, ensure_ascii=False, default=str)))
    con.execute("DELETE FROM runs WHERE ts NOT IN (SELECT ts FROM runs ORDER BY ts DESC LIMIT ?)", (RUNS_KEEP,))
    if best is not None:
        kv_put(con, "best", best)
    kv_put(con, "last_ts", now)
    con.commit()
    _CACHE.clear()


def latest(path=None):
    """(ts, data) of the newest run; (None, None) before the first."""
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


def best(path=None, cached=True):
    """The current best candidate with its live selection (kv best), or None. Cached CACHE_S per process (the live
    entries ask every pass)."""
    path = path or db_path()
    hit = _CACHE.get(path)
    if cached and hit and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    con = ro(path)
    val = None
    if con is not None:
        try:
            val = kv_get(con, "best")
        except sqlite3.Error:
            val = None
        finally:
            con.close()
    _CACHE[path] = (time.monotonic(), val)
    return val
