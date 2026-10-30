"""watch.db: event-linked tokens tracked over time, from ~14 days before the event until a day after.

Own file (one writer per SQLite file on the shared disk, see wallets/store.py).

Tables:
  watch_tokens       which tokens are being tracked and for which event
  watch_snapshots    one row per token per snapshot: market data from DexScreener, buyers from Helius
  watch_buyers       every wallet seen buying a watched token, with its tier/labels from wallets.db
  watch_correlation  per token: does volume / buying / smart money rise as the event gets closer?
"""
import os
import sqlite3

DB = os.environ.get("WATCH_DB", os.path.join(os.path.dirname(__file__), "..", "watch.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS watch_tokens (
    token TEXT, event TEXT, event_date TEXT, symbol TEXT, name TEXT, role TEXT, url TEXT,
    likelihood REAL, added_ts INTEGER, wallets_ts INTEGER, active INTEGER DEFAULT 1,
    PRIMARY KEY (token, event_date, event));
CREATE TABLE IF NOT EXISTS watch_snapshots (
    token TEXT, event_date TEXT, ts INTEGER, days_to_event REAL, price REAL, mcap REAL, liquidity REAL,
    vol_h1 REAL, vol_h24 REAL, buys_h1 INTEGER, sells_h1 INTEGER, buys_h24 INTEGER, sells_h24 INTEGER,
    new_buyers INTEGER, smart_buyers INTEGER, bad_buyers INTEGER, buyer_sol REAL,
    PRIMARY KEY (token, event_date, ts));
CREATE TABLE IF NOT EXISTS watch_buyers (
    token TEXT, wallet TEXT, first_ts INTEGER, sol_in REAL, buys INTEGER, tier TEXT, labels TEXT,
    days_to_event REAL, PRIMARY KEY (token, wallet));
CREATE TABLE IF NOT EXISTS watch_correlation (
    token TEXT, event TEXT, event_date TEXT, symbol TEXT, n INTEGER, first_ts INTEGER, last_ts INTEGER,
    corr_volume REAL, corr_buys REAL, corr_buyers REAL, corr_smart REAL, corr_price REAL,
    vol_change REAL, buyers_total INTEGER, smart_total INTEGER, bad_total INTEGER, verdict TEXT, updated_ts INTEGER,
    PRIMARY KEY (token, event_date, event));
"""


def connect(path=None):
    con = sqlite3.connect(path or DB, timeout=30)
    con.executescript(SCHEMA)
    con.row_factory = sqlite3.Row
    return con
