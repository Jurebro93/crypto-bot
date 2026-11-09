"""hype.db tables of the live feed (run_live.py). Trades are kept 48 h, launches 7 days, alerts 24 h."""
import os
import sqlite3
import time

HYPE_DB = os.environ.get("HYPE_DB") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hype.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS live_trades (
    sig TEXT, mint TEXT, wallet TEXT, side TEXT, sol REAL, tokens REAL, price_sol REAL, mcap_sol REAL, pool TEXT,
    ts INTEGER, balance_after REAL, PRIMARY KEY (sig, mint));
CREATE INDEX IF NOT EXISTS live_trades_mint_ts ON live_trades (mint, ts);
CREATE TABLE IF NOT EXISTS live_launches (
    mint TEXT PRIMARY KEY, ts INTEGER, creator TEXT, name TEXT, symbol TEXT, initial_sol REAL, sig TEXT, pool TEXT);
CREATE TABLE IF NOT EXISTS live_alerts (
    token TEXT, ts INTEGER, kind TEXT, detail TEXT, PRIMARY KEY (token, ts, kind));
CREATE TABLE IF NOT EXISTS live_state (key TEXT PRIMARY KEY, value TEXT);
"""
KEEP_TRADES_S, KEEP_LAUNCH_S, KEEP_ALERT_S = 48 * 3600, 7 * 86400, 86400


def connect(path=None):
    con = sqlite3.connect(path or HYPE_DB, timeout=60, isolation_level=None)   # explicit BEGIN IMMEDIATE in Feed.flush
    con.execute("PRAGMA busy_timeout = 60000")
    con.executescript(SCHEMA)
    if "balance_after" not in {r[1] for r in con.execute("PRAGMA table_info(live_trades)")}:
        con.execute("ALTER TABLE live_trades ADD COLUMN balance_after REAL")   # 5.11.: proportional selling
    return con


def ro(path=None):
    path = path or HYPE_DB
    if not os.path.exists(path):
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        con.execute("SELECT 1 FROM live_trades LIMIT 1")
        return con
    except sqlite3.Error:
        return None


def add_trades(con, rows):
    con.executemany("INSERT OR IGNORE INTO live_trades VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)


def add_launches(con, rows):
    con.executemany("INSERT OR IGNORE INTO live_launches VALUES (?,?,?,?,?,?,?,?)", rows)


def mirror_chain(con, rows, followed):
    """Trades of followed wallets also go to chain_trades (the Helius webhook table), so insiders, strategies and the
    Natjecanje follows see a pump.fun buy even when the webhook is late or over its 100 addresses."""
    con.execute("""CREATE TABLE IF NOT EXISTS chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER,
                   sol REAL, PRIMARY KEY (sig, mint))""")
    mine = [(r[0], r[2], r[1], r[3], r[9], r[4] if r[3] == "buy" else None) for r in rows if r[2] in followed]
    con.executemany("INSERT OR IGNORE INTO chain_trades VALUES (?,?,?,?,?,?)", mine)
    if mine:
        try:
            from league import copy as _copy   # 9.11.: a followed wallet traded: the copy loop runs within a second
            _copy.wake()
        except Exception:  # noqa: BLE001
            pass


def prune(con, now=None):
    now = now or int(time.time())
    con.execute("DELETE FROM live_trades WHERE ts < ?", (now - KEEP_TRADES_S,))
    con.execute("DELETE FROM live_launches WHERE ts < ?", (now - KEEP_LAUNCH_S,))
    con.execute("DELETE FROM live_alerts WHERE ts < ?", (now - KEEP_ALERT_S,))


def set_state(con, key, value):
    con.execute("INSERT OR REPLACE INTO live_state VALUES (?, ?)", (key, str(value)))


def state(con, key, default=None):
    r = con.execute("SELECT value FROM live_state WHERE key=?", (key,)).fetchone()
    return r[0] if r else default
