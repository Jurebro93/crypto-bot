"""koltest.db: the KOL test book. Own file; only the run_paper process writes it (koltest.run.step), the dashboard
and the morning report read it read-only. Nothing in the main demo book or the learning reads it.

Tables:
  positions  one row per (caller, token): a $50 demo entry on a fresh call (status open/done) or a call that was
             not entered (status skip, close_reason = why). Path stats: peak, trough, when each level was first
             reached and the lowest point before it, returns at 5 min .. 24 h, and the ladder book's result.
  kv         test start/end.
"""
import os
import sqlite3

DB = os.environ.get("KOLTEST_DB", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                               "koltest.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT, symbol TEXT, source TEXT, caller TEXT, score REAL,
    call_ts INTEGER, seen_ts INTEGER, entry_ts INTEGER, entry_px REAL, entry_mcap REAL, entry_liq REAL,
    status TEXT, last_ts INTEGER, last_px REAL, last_liq REAL, last_mcap REAL, peak REAL, peak_ts INTEGER,
    trough REAL, trough_ts INTEGER, hits TEXT, rets TEXT, book TEXT, pnl_usd REAL, book_closed_ts INTEGER,
    book_reason TEXT, done_ts INTEGER, close_reason TEXT, missing_since INTEGER, url TEXT,
    UNIQUE (caller, token));
CREATE INDEX IF NOT EXISTS positions_status ON positions (status, entry_ts);
CREATE INDEX IF NOT EXISTS positions_seen ON positions (seen_ts);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
"""


def connect(path=None):
    con = sqlite3.connect(path or DB, timeout=60)
    con.executescript(SCHEMA)
    return con


def ro(path=None):
    path = path or DB
    if not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.OperationalError:
        return None


def kv_get(con, key, default=None):
    r = con.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return r[0] if r else default


def kv_set(con, key, value):
    con.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)", (key, str(value)))


def window(con, cfg, now):
    """(start_ts, end_ts) of the test; started on first call, lasts cfg days."""
    start = kv_get(con, "start_ts")
    if start is None:
        start = int(now)
        kv_set(con, "start_ts", start)
    start = int(float(start))
    return start, start + int(cfg.get("days", 7) * 86400)


def rows(con, where="status IN ('open', 'done')", args=()):
    cur = con.execute(f"SELECT * FROM positions WHERE {where}", args)
    cols = [d[0] for d in cur.description]
    import json
    out = []
    for r in cur:
        d = dict(zip(cols, r))
        for k in ("hits", "rets", "book"):
            d[k] = json.loads(d[k] or "{}")
        out.append(d)
    return out
