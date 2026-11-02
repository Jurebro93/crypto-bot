"""topcheck.db: the fresh check of every recommended token. One writer (run_top.py); the dashboard reads it."""
import json
import os
import sqlite3
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("TOPCHECK_DB", os.path.join(HERE, "topcheck.db"))
SCHEMA = """
CREATE TABLE IF NOT EXISTS top_check (
    token TEXT PRIMARY KEY, symbol TEXT, rank INTEGER, ts INTEGER,
    price REAL, mcap REAL, liq REAL, state TEXT, state_json TEXT,
    verdict TEXT, safety_json TEXT, rc_json TEXT, rc_ts INTEGER, sell_json TEXT, sell_ts INTEGER, full_ts INTEGER);
CREATE TABLE IF NOT EXISTS full_budget (day TEXT PRIMARY KEY, n INTEGER);
"""
KEEP_DAYS = 3


def connect(path=None):
    con = sqlite3.connect(path or DB, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    for col in ("rc_fail INTEGER", "rc_fail_ts INTEGER"):   # added after the first release
        try:
            con.execute(f"ALTER TABLE top_check ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass
    return con


def get(con, token):
    r = con.execute("SELECT * FROM top_check WHERE token=?", (token,)).fetchone()
    return dict(r) if r else None


def put(con, row):
    cols = ["token", "symbol", "rank", "ts", "price", "mcap", "liq", "state", "state_json", "verdict", "safety_json",
            "rc_json", "rc_ts", "sell_json", "sell_ts", "full_ts", "rc_fail", "rc_fail_ts"]
    con.execute(f"INSERT OR REPLACE INTO top_check ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                [row.get(c) for c in cols])


def unrank(con, keep):
    """Tokens that left the top list keep their last check (the page may still show them) but lose the rank."""
    q = ",".join("?" * len(keep)) or "''"
    con.execute(f"UPDATE top_check SET rank=NULL WHERE token NOT IN ({q})", list(keep))
    con.execute("DELETE FROM top_check WHERE ts < ?", (int(time.time() - KEEP_DAYS * 86400),))


def budget_take(con, day, cap):
    n = (con.execute("SELECT n FROM full_budget WHERE day=?", (day,)).fetchone() or [0])[0]
    if n >= cap:
        return False
    con.execute("INSERT OR REPLACE INTO full_budget VALUES (?, ?)", (day, n + 1))
    con.execute("DELETE FROM full_budget WHERE day < ?", (time.strftime("%Y-%m-%d", time.gmtime(time.time() - 7 * 86400)),))
    return True


def read_all(path=None, max_age_h=24):
    """mint -> row with parsed JSON (read-only, for the dashboard and token_rows). {} without the file."""
    path = path or DB
    if not os.path.exists(path):
        return {}
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM top_check WHERE ts >= ?", (int(time.time() - max_age_h * 3600),)).fetchall()
        con.close()
    except sqlite3.Error:
        return {}
    out = {}
    for r in rows:
        d = dict(r)
        for k in ("state_json", "safety_json", "rc_json", "sell_json"):
            try:
                d[k[:-5]] = json.loads(d.pop(k) or "null")
            except ValueError:
                d[k[:-5]] = None
        out[d["token"]] = d
    return out
