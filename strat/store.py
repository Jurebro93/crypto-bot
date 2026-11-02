"""strat.db: five demo accounts of $1000 that each buy from a different source, side by side. Own file; only the
run_paper process writes it (strat.run.step), the dashboard, the morning report and the learning read it read-only.

Tables:
  positions  one row per (strategy, token): status pending (signal seen, waiting for a price), open, closed or skip
             (close_reason = why it was not bought). state = the paper.sim position (fills, peak, stop state), so the
             exits behave exactly like the main demo's.
  equity     account value per strategy every equity_every_min minutes (the chart).
  kv         start time, last random pick.
"""
import json
import os
import sqlite3

DB = os.environ.get("STRAT_DB", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "strat.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, strat TEXT, token TEXT, symbol TEXT, url TEXT, why TEXT,
    signal_ts INTEGER, seen_ts INTEGER, entry_ts INTEGER, entry_mcap REAL, size_usd REAL, status TEXT,
    state TEXT, last_ts INTEGER, last_px REAL, last_liq REAL, pnl_usd REAL, ret REAL, closed_ts INTEGER,
    exit_reason TEXT, close_reason TEXT, missing_since INTEGER,
    UNIQUE (strat, token));
CREATE INDEX IF NOT EXISTS positions_status ON positions (status, strat);
CREATE INDEX IF NOT EXISTS positions_seen ON positions (seen_ts);
CREATE TABLE IF NOT EXISTS equity (ts INTEGER, strat TEXT, value REAL, PRIMARY KEY (ts, strat));
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
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        con.execute("SELECT 1 FROM positions LIMIT 1")
        return con
    except sqlite3.OperationalError:
        return None


def kv_get(con, key, default=None):
    r = con.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return r[0] if r else default


def kv_set(con, key, value):
    con.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)", (key, str(value)))


def start_ts(con, now):
    s = kv_get(con, "start_ts")
    if s is None:
        kv_set(con, "start_ts", int(now))
        return int(now)
    return int(float(s))


def rows(con, where="status IN ('open', 'closed')", args=()):
    cur = con.execute(f"SELECT * FROM positions WHERE {where} ORDER BY COALESCE(entry_ts, seen_ts)", args)
    cols = [d[0] for d in cur.description]
    out = []
    for r in cur:
        d = dict(zip(cols, r))
        d["state"] = json.loads(d["state"] or "{}")
        out.append(d)
    return out
