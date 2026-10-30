"""SQLite tables for the hype module (in hype.db): signals, price snapshots, smart wallets, TG mentions."""
import json
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS hype_signals (
    ts INTEGER, token TEXT, symbol TEXT, name TEXT, pair TEXT, url TEXT, score REAL,
    price REAL, mcap REAL, liquidity REAL, features TEXT, sources TEXT, weights TEXT,
    PRIMARY KEY (token, ts));
CREATE TABLE IF NOT EXISTS hype_snapshots (
    token TEXT, ts INTEGER, price REAL, mcap REAL, liquidity REAL, PRIMARY KEY (token, ts));
CREATE TABLE IF NOT EXISTS smart_wallets (
    wallet TEXT PRIMARY KEY, score REAL, stats TEXT, found_via TEXT, updated INTEGER);
CREATE TABLE IF NOT EXISTS hype_details (
    token TEXT, ts INTEGER, extra TEXT, PRIMARY KEY (token, ts));
CREATE TABLE IF NOT EXISTS tg_mentions (
    channel TEXT, post TEXT, time TEXT, ca TEXT, tickers TEXT, PRIMARY KEY (post, ca));
"""


def connect(path):
    con = sqlite3.connect(path, timeout=60)  # other loops (paper, watch) write the same file
    con.executescript(SCHEMA)
    return con


def log_signal(con, row, weights):
    con.execute("INSERT OR REPLACE INTO hype_signals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (int(time.time()), row["token"], row["symbol"], row["name"], row["pair"], row["url"], row["score"],
                 row["price"], row["mcap"], row["liquidity"], json.dumps(row["features"]),
                 ",".join(sorted(row["sources"])), json.dumps(weights)))


def log_details(con, row):
    """What the score does not hold: X buzz authors, smart buyers, copycats, trend, pump.fun risk data."""
    extra = dict(row.get("extra") or {})
    for k in ("copycats", "smart_buyers", "x"):
        if row.get(k) is not None:
            extra[k] = row[k]
    con.execute("INSERT OR REPLACE INTO hype_details VALUES (?,?,?)",
                (row["token"], int(time.time()), json.dumps(extra, default=str)))


def snapshot(con, token, price, mcap, liq, ts=None):
    con.execute("INSERT OR REPLACE INTO hype_snapshots VALUES (?,?,?,?,?)",
                (token, int(ts or time.time()), price, mcap, liq))


def smart_set(con, min_score=50):
    return {w for (w,) in con.execute("SELECT wallet FROM smart_wallets WHERE score >= ?", (min_score,))}


def save_wallet(con, wallet, stats, found_via):
    con.execute("INSERT OR REPLACE INTO smart_wallets VALUES (?,?,?,?,?)",
                (wallet, stats["score"], json.dumps(stats), found_via, int(time.time())))


def tg_counts(con, since_iso):
    """CA -> number of distinct channels that posted it since `since_iso`."""
    return dict(con.execute("SELECT ca, COUNT(DISTINCT channel) FROM tg_mentions WHERE time >= ? GROUP BY ca",
                            (since_iso,)))
