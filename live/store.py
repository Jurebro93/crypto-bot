"""hype.db tables of the live feed (run_live.py). Trades are kept 48 h, bonded tokens (pool 'migration') 7 days, new
launches 24 h (10.11.: every new pump.fun token is captured, 20-40k a day; kol/precall.py measures them within 2 h and
keeps the ones that reached 10k itself), alerts 24 h."""
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
CREATE INDEX IF NOT EXISTS live_launches_ts ON live_launches (ts);
CREATE TABLE IF NOT EXISTS live_alerts (
    token TEXT, ts INTEGER, kind TEXT, detail TEXT, PRIMARY KEY (token, ts, kind));
CREATE TABLE IF NOT EXISTS live_state (key TEXT PRIMARY KEY, value TEXT);
"""
KEEP_TRADES_S, KEEP_LAUNCH_S, KEEP_ALERT_S = 48 * 3600, 7 * 86400, 86400
KEEP_NEW_S = 86400   # 10.11.: a launch that has not bonded is kept a day (the 24 h count on the status line)


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
    """New tokens are inserted once. 10.11.: with every new token captured, a token that bonds already has its create
    row, which INSERT OR IGNORE kept and so hid the bond from every reader of pool 'migration' (the scanner, the
    live subscriptions, kol/graduates, learn/masovno): a migration now turns that row into the bond (pool and ts
    become the migration's; name, symbol and creator stay), once."""
    news = [r for r in rows if r[7] != "migration"]
    migs = [r for r in rows if r[7] == "migration"]
    con.executemany("INSERT OR IGNORE INTO live_launches VALUES (?,?,?,?,?,?,?,?)", news)
    con.executemany("""INSERT INTO live_launches VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(mint) DO UPDATE SET
        ts = excluded.ts, sig = excluded.sig, pool = 'migration', name = COALESCE(NULLIF(live_launches.name, ''),
        excluded.name), symbol = COALESCE(NULLIF(live_launches.symbol, ''), excluded.symbol),
        creator = COALESCE(live_launches.creator, excluded.creator) WHERE live_launches.pool != 'migration'""", migs)


def mirror_chain(con, rows, followed):
    """Trades of followed wallets also go to chain_trades (the Helius webhook table), so insiders, strategies and the
    Natjecanje follows see a pump.fun buy even when the webhook is late or over its 100 addresses."""
    con.execute("""CREATE TABLE IF NOT EXISTS chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER,
                   sol REAL, PRIMARY KEY (sig, mint))""")
    mine = [(r[0], r[2], r[1], r[3], r[9], r[4] if r[3] == "buy" else None) for r in rows if r[2] in followed]
    con.executemany("INSERT OR IGNORE INTO chain_trades VALUES (?,?,?,?,?,?)", mine)
    if mine:
        try:   # 11.11. dual write into events.db (events/hooks.py): queued, never waits on the database
            from events import hooks as _ev
            _ev.wallet_rows(mine, "pumpportal")
        except Exception:  # noqa: BLE001
            pass
        try:
            from league import copy as _copy   # 9.11.: a followed wallet traded: the copy loop runs within a second
            _copy.wake()
        except Exception:  # noqa: BLE001
            pass


def prune(con, now=None):
    now = now or int(time.time())
    con.execute("DELETE FROM live_trades WHERE ts < ?", (now - KEEP_TRADES_S,))
    con.execute("DELETE FROM live_launches WHERE ts < ?", (now - KEEP_LAUNCH_S,))
    con.execute("DELETE FROM live_launches WHERE pool != 'migration' AND ts < ?", (now - KEEP_NEW_S,))
    con.execute("DELETE FROM live_alerts WHERE ts < ?", (now - KEEP_ALERT_S,))


def set_state(con, key, value):
    con.execute("INSERT OR REPLACE INTO live_state VALUES (?, ?)", (key, str(value)))


def state(con, key, default=None):
    r = con.execute("SELECT value FROM live_state WHERE key=?", (key,)).fetchone()
    return r[0] if r else default
