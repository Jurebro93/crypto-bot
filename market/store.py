"""market.db: daily volume per platform and group, SOL price, hourly 24 h snapshots and the daily regime.

Only run_market.py writes here (single writer); the dashboard and the scoring read it.
Days are UTC midnights (unix seconds). Group totals are stored as slug 'all:<group>'.
"""
import os
import sqlite3

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("MARKET_DB", os.path.join(HERE, "market.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS platforms (slug TEXT PRIMARY KEY, name TEXT, category TEXT, grp TEXT);
CREATE TABLE IF NOT EXISTS daily (day INTEGER, slug TEXT, volume REAL, PRIMARY KEY (day, slug));
CREATE TABLE IF NOT EXISTS price (day INTEGER PRIMARY KEY, usd REAL);
CREATE TABLE IF NOT EXISTS btc (day INTEGER PRIMARY KEY, usd REAL);
CREATE TABLE IF NOT EXISTS fng (day INTEGER PRIMARY KEY, value INTEGER, label TEXT, published INTEGER, seen INTEGER);
CREATE TABLE IF NOT EXISTS snap (ts INTEGER, slug TEXT, vol24h REAL, vol7d REAL, PRIMARY KEY (ts, slug));
CREATE TABLE IF NOT EXISTS regime (day INTEGER PRIMARY KEY, score REAL, label TEXT, features TEXT, created INTEGER);
"""


def connect(path=None):
    con = sqlite3.connect(path or DB, timeout=30)
    con.executescript(SCHEMA)
    return con


def ro(path=None):
    """Read-only connection for the dashboard, None when the file does not exist yet."""
    p = path or DB
    if not os.path.exists(p):
        return None
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)


def series(con, slug, since=0):
    """[(day, volume)] oldest first."""
    return con.execute("SELECT day, volume FROM daily WHERE slug=? AND day>=? ORDER BY day", (slug, since)).fetchall()
