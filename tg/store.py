"""tg.db: the list of Telegram channels and (until 19.11.2026) their posts that named a token.

19.11. (vlasnik: "Makni Telegram KOL-ove iz izračuna. Ali zadrži popis kanala, osvježen jednom tjedno, samo za broj
pratitelja"): nothing reads channels any more; the only writer is the weekly follower count (tg/pratitelji.py: table
tg_pratitelji and channels.subs / title / checked_ts). The stored posts stay (ops/retencija may blank old texts, by
the owner's switch); they are in the cleanup inventory, nothing deletes them here.
"""
import json
import os
import sqlite3

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("TG_DB", os.path.join(HERE, "tg.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    name TEXT PRIMARY KEY, title TEXT, subs INTEGER, status TEXT DEFAULT 'candidate', found_via TEXT,
    found_ts INTEGER, checked_ts INTEGER, fails INTEGER DEFAULT 0, last_post INTEGER DEFAULT 0, last_post_ts INTEGER,
    last_ca_ts INTEGER, last_poll INTEGER DEFAULT 0, n_posts INTEGER DEFAULT 0, n_ca INTEGER DEFAULT 0,
    lag_s REAL, joined INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS channels_status ON channels (status, last_poll);
CREATE TABLE IF NOT EXISTS posts (
    channel TEXT, post INTEGER, ts INTEGER, seen_ts INTEGER, text TEXT, cas TEXT, tickers TEXT, views INTEGER,
    fwd_from TEXT, source TEXT, PRIMARY KEY (channel, post));
CREATE INDEX IF NOT EXISTS posts_seen ON posts (seen_ts);
CREATE INDEX IF NOT EXISTS posts_ts ON posts (ts);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS tg_pratitelji (kanal TEXT, ts INTEGER, pratitelji INTEGER, PRIMARY KEY (kanal, ts));
CREATE INDEX IF NOT EXISTS tg_pratitelji_ts ON tg_pratitelji (ts);
"""


def connect(path=None):
    con = sqlite3.connect(path or DB, timeout=60)
    con.executescript(SCHEMA)
    return con


def ro(path=None):
    path = path or DB
    if not os.path.exists(path) or not os.path.getsize(path):
        return None
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)


def kv_get(con, key, default=None):
    r = con.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return json.loads(r[0]) if r else default


def kv_set(con, key, value):
    con.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, json.dumps(value)))
