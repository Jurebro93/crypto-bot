"""simianx.db: token -> SimianX instrument mapping, opinions (one per quick read), the demo book of long signals and
signals handed to the real-trade account. Only run_simianx.py writes opinions/book; league/simianx_feed.py writes
only the `used` column of a signal (the dashboard process), through its own short connection."""
import os
import sqlite3

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("SIMIANX_DB", os.path.join(HERE, "simianx.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS instruments (mint TEXT PRIMARY KEY, symbol TEXT, sx_symbol TEXT, ok INTEGER, note TEXT,
    ts INTEGER);
CREATE TABLE IF NOT EXISTS opinions (id INTEGER PRIMARY KEY AUTOINCREMENT, mint TEXT, symbol TEXT, ts INTEGER,
    timeframe TEXT, view TEXT, action TEXT, entry REAL, stop REAL, target REAL, confidence REAL, reason TEXT,
    says TEXT, points REAL, run_id TEXT, dex_price REAL);
CREATE INDEX IF NOT EXISTS opinions_mint ON opinions (mint, ts);
CREATE TABLE IF NOT EXISTS book (id INTEGER PRIMARY KEY AUTOINCREMENT, opinion_id INTEGER, mint TEXT, symbol TEXT,
    entry_ts INTEGER, entry_price REAL, usd REAL, stop_px REAL, target_px REAL, stop_pct REAL, target_pct REAL,
    exit_ts INTEGER, exit_price REAL, reason TEXT, sol_entry REAL, sol_exit REAL);
CREATE TABLE IF NOT EXISTS signals (id INTEGER PRIMARY KEY AUTOINCREMENT, opinion_id INTEGER, mint TEXT, symbol TEXT,
    ts INTEGER, stop_pct REAL, target_pct REAL, used INTEGER DEFAULT 0, used_ts INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""


def connect(path=None):
    con = sqlite3.connect(path or DB, timeout=60)
    con.executescript(SCHEMA)
    con.row_factory = sqlite3.Row
    return con


def ro(path=None):
    p = path or DB
    if not os.path.exists(p):
        return None
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def spent_today(con, day_start):
    return con.execute("SELECT COALESCE(SUM(points),0) FROM opinions WHERE ts>=?", (day_start,)).fetchone()[0] + \
        float((con.execute("SELECT v FROM kv WHERE k=?", (f"map_points:{day_start}",)).fetchone() or [0])[0])


def add_map_points(con, day_start, pts):
    con.execute("INSERT INTO kv VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=CAST(v AS REAL)+?",
                (f"map_points:{day_start}", pts, pts))


def latest(con):
    """{mint: newest opinion row}."""
    return {r["mint"]: r for r in con.execute(
        "SELECT * FROM opinions WHERE id IN (SELECT MAX(id) FROM opinions GROUP BY mint)")}
