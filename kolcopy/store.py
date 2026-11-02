"""kolcopy.db: the KOL copy replay. Own file with one writer (run_kolcopy.py run, from run_sched); the dashboard
reads it read-only. Nothing in the demo book, real trading or the learning reads it.

Tables:
  events  one row per (KOL wallet, token): the wallet's first buy seen by the Helius webhook (t0, SOL spent), its
          first sell within mirror_max_h (sell_ts), and the measured prices at every point (points, JSON
          {name: [price_sol, trade_ts]}; name kol = t0, e<d> = t0 + d s, h<H> = t0 + H h, s<d> = sell_ts + d s).
          status open / done / skip (skip_reason says why).
  px      swap prices of a token from its own transactions (SOL per token), shared by every event on that token.
  cover   time ranges [a, b] of a token whose swaps are all in px, so a price inside them costs no credits.
  kv      credits spent per day, last run.
"""
import os
import sqlite3
from pathlib import Path

DB = os.environ.get("KOLCOPY_DB", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                               "kolcopy.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, wallet TEXT, mint TEXT, t0 INTEGER, kol_sol REAL, sell_ts INTEGER,
    points TEXT DEFAULT '{}', status TEXT DEFAULT 'open', skip_reason TEXT, created INTEGER, updated INTEGER,
    UNIQUE (wallet, mint));
CREATE INDEX IF NOT EXISTS events_status ON events (status, t0);
CREATE TABLE IF NOT EXISTS px (mint TEXT, sig TEXT, ts INTEGER, price REAL, PRIMARY KEY (mint, sig));
CREATE INDEX IF NOT EXISTS px_ts ON px (mint, ts);
CREATE TABLE IF NOT EXISTS cover (mint TEXT, a INTEGER, b INTEGER);
CREATE INDEX IF NOT EXISTS cover_mint ON cover (mint, a);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
"""


def connect(path=None):
    con = sqlite3.connect(path or DB, timeout=60)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def ro(path=None):
    path = path or DB
    if not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
        con.row_factory = sqlite3.Row
        return con
    except sqlite3.OperationalError:
        return None


def kv_get(con, key, default=None):
    r = con.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return r[0] if r else default


def kv_set(con, key, value):
    con.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)", (key, str(value)))
