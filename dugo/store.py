"""dugo.db: candidate tokens, daily candles, scored snapshots, the demo long-term book and learning runs.

Only run_dugo.py writes here (single writer); the dashboard reads it read-only. Size stays small: ~300 tokens x
<= 400 daily candles (~5 MB), one snapshot row per token per day (older than 400 days deleted).
"""
import json
import os
import sqlite3

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("DUGO_DB", os.path.join(HERE, "dugo.db"))
KEEP_DAYS = 400

SCHEMA = """
CREATE TABLE IF NOT EXISTS tokens (mint TEXT PRIMARY KEY, symbol TEXT, name TEXT, pair TEXT, source TEXT,
    created_ts INTEGER, first_seen INTEGER, last_dex INTEGER, liquidity REAL, mcap REAL, vol24 REAL,
    buys24 INTEGER, sells24 INTEGER, ch24 REAL, url TEXT, candles_ts INTEGER, status TEXT);
CREATE TABLE IF NOT EXISTS candles (mint TEXT, day INTEGER, o REAL, h REAL, l REAL, c REAL, v REAL,
    PRIMARY KEY (mint, day));
CREATE TABLE IF NOT EXISTS ref (name TEXT, day INTEGER, c REAL, PRIMARY KEY (name, day));
CREATE TABLE IF NOT EXISTS snap (day INTEGER, mint TEXT, kind TEXT, score REAL, rank INTEGER, price REAL,
    liquidity REAL, mcap REAL, features TEXT, why TEXT, PRIMARY KEY (day, mint, kind));
CREATE TABLE IF NOT EXISTS book (id INTEGER PRIMARY KEY AUTOINCREMENT, mint TEXT, symbol TEXT, kind TEXT,
    entry_ts INTEGER, entry_price REAL, usd REAL, exit_ts INTEGER, exit_price REAL, reason TEXT,
    sol_entry REAL, sol_exit REAL);
CREATE TABLE IF NOT EXISTS holders (mint TEXT, day INTEGER, n INTEGER, PRIMARY KEY (mint, day));
CREATE TABLE IF NOT EXISTS learn_runs (ts INTEGER, kind TEXT, applied INTEGER, n INTEGER, before REAL, after REAL,
    note TEXT, weights TEXT);
"""


def connect(path=None):
    con = sqlite3.connect(path or DB, timeout=60)
    con.executescript(SCHEMA)
    return con


def ro(path=None):
    p = path or DB
    if not os.path.exists(p):
        return None
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def candles(con, mint, until=None):
    q = "SELECT day, o, h, l, c, v FROM candles WHERE mint=?" + (" AND day<=?" if until else "") + " ORDER BY day"
    return con.execute(q, (mint, until) if until else (mint,)).fetchall()


def ref(con, name):
    return dict(con.execute("SELECT day, c FROM ref WHERE name=?", (name,)).fetchall())


def put_candles(con, mint, rows):
    con.executemany("INSERT OR REPLACE INTO candles VALUES (?,?,?,?,?,?,?)", [(mint, *r) for r in rows])


def prune(con, now):
    con.execute("DELETE FROM candles WHERE day < ?", (now - KEEP_DAYS * 86400,))
    con.execute("DELETE FROM snap WHERE day < ?", (now - KEEP_DAYS * 86400,))


def dumps(o):
    return json.dumps(o, separators=(",", ":"), ensure_ascii=False)
