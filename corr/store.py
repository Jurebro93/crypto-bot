"""corr.db: the latest correlation snapshot, the AI interpretation of it and the groups we follow.

Own file, one writer (run_corr.py), like every other module (see wallets/store.py). The dashboard and
run_wallets harvest read it read-only.

Tables:
  snapshots  one row per analysis run: JSON with KOL clusters, wallet<->KOL links, wallet owner groups,
             pump factors and what is active now (only the newest KEEP rows are kept, the disk is small)
  ai         Claude's interpretation per data hash (so the same data is never paid for twice)
  follow     groups followed automatically: kind (kol|wallets), members, why, since
"""
import json
import os
import sqlite3
import time

DB = os.environ.get("CORR_DB", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corr.db"))
KEEP = 8

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (ts INTEGER PRIMARY KEY, hash TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS ai (hash TEXT PRIMARY KEY, ts INTEGER, model TEXT, data TEXT, cost REAL);
CREATE TABLE IF NOT EXISTS follow (id TEXT PRIMARY KEY, kind TEXT, name TEXT, members TEXT, reason TEXT,
    score REAL, since INTEGER, updated INTEGER);
"""


def connect(path=None):
    con = sqlite3.connect(path or DB, timeout=60)
    con.executescript(SCHEMA)
    return con


def ro(path=None):
    path = path or DB
    if not os.path.exists(path) or not os.path.getsize(path):
        return None
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)


def save(con, data, digest, now=None):
    now = int(now or time.time())
    con.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?)", (now, digest, json.dumps(data, ensure_ascii=False)))
    con.execute("DELETE FROM snapshots WHERE ts NOT IN (SELECT ts FROM snapshots ORDER BY ts DESC LIMIT ?)", (KEEP,))
    con.execute("DELETE FROM ai WHERE hash NOT IN (SELECT hash FROM ai ORDER BY ts DESC LIMIT ?)", (KEEP,))
    con.commit()


def latest(path=None):
    """(ts, data, ai row or None) of the newest snapshot; (None, None, None) before the first run."""
    con = ro(path)
    if con is None:
        return None, None, None
    try:
        row = con.execute("SELECT ts, hash, data FROM snapshots ORDER BY ts DESC LIMIT 1").fetchone()
        if not row:
            return None, None, None
        ai = con.execute("SELECT ts, model, data, cost FROM ai ORDER BY ts DESC LIMIT 1").fetchone()
        ai = {"ts": ai[0], "model": ai[1], "data": json.loads(ai[2]), "cost": ai[3],
              "fresh": True} if ai else None
        if ai:
            ai["fresh"] = con.execute("SELECT 1 FROM ai WHERE hash=?", (row[1],)).fetchone() is not None
        return row[0], json.loads(row[2]), ai
    except sqlite3.OperationalError:
        return None, None, None
    finally:
        con.close()


def last_ai(con):
    row = con.execute("SELECT ts, hash FROM ai ORDER BY ts DESC LIMIT 1").fetchone()
    return row or (0, None)


def save_ai(con, digest, model, data, cost, now=None):
    con.execute("INSERT OR REPLACE INTO ai VALUES (?,?,?,?,?)",
                (digest, int(now or time.time()), model, json.dumps(data, ensure_ascii=False), cost))
    con.commit()


def set_follow(con, items, now=None):
    """items: [{id, kind, name, members, reason, score}]. Keeps `since` of groups already followed."""
    now = int(now or time.time())
    for it in items:
        con.execute("INSERT INTO follow VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                    "name=excluded.name, members=excluded.members, reason=excluded.reason, score=excluded.score, "
                    "updated=excluded.updated",
                    (it["id"], it["kind"], it["name"], json.dumps(it["members"]), it["reason"], it["score"], now, now))
    con.commit()


def followed(path=None, kind=None):
    """[{id, kind, name, members, reason, score, since}] of the followed groups; [] if corr.db is missing."""
    con = ro(path)
    if con is None:
        return []
    try:
        rows = con.execute("SELECT id, kind, name, members, reason, score, since FROM follow"
                           + (" WHERE kind=?" if kind else "") + " ORDER BY score DESC", (kind,) if kind else ()).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()
    return [{"id": r[0], "kind": r[1], "name": r[2], "members": json.loads(r[3] or "[]"), "reason": r[4],
             "score": r[5], "since": r[6]} for r in rows]
