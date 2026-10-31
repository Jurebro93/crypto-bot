"""token_tier: one row per token ever seen by the hype scan, in hype.db (same writer as hype_signals)."""
import json
import os
import sqlite3
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(HERE, "hype.db")
SCHEMA = """
CREATE TABLE IF NOT EXISTS token_tier (
    token TEXT PRIMARY KEY, symbol TEXT, first_ts INTEGER, last_ts INTEGER,
    razina INTEGER DEFAULT 0, klasa TEXT, t0 TEXT, t0_razlog TEXT, t0_ts INTEGER,
    mcap REAL, liquidity REAL, age_h REAL, score REAL,
    put_brzina REAL, put_skokovitost REAL, put_zadrzavanje REAL,
    credits INTEGER DEFAULT 0, razlog TEXT);
CREATE TABLE IF NOT EXISTS tier_events (
    token TEXT, point TEXT, ts INTEGER, mcap REAL, price REAL, score REAL, features TEXT,
    PRIMARY KEY (token, point));
"""
# bonding-curve snapshot (tiers/curve.py), added after the first deploy: ALTER TABLE in connect()
CURVE_COLS = {"krivulja": "TEXT", "krivulja_ts": "INTEGER", "krivulja_complete": "INTEGER", "grad_min": "REAL",
              "bundle_launch": "INTEGER", "mayhem": "INTEGER", "quote_sol": "INTEGER"}
COLS = ("symbol", "razina", "klasa", "t0", "t0_razlog", "t0_ts", "mcap", "liquidity", "age_h", "score",
        "put_brzina", "put_skokovitost", "put_zadrzavanje", "razlog") + tuple(CURVE_COLS)
# the first market-cap crossing worth a decision: the study's best entry (2x 24%, 5x 9% over 7 days)
EVENT_BANDS = {"B100000": 1e5, "B1000000": 1e6}


def connect(path=None):
    con = sqlite3.connect(path or DB, timeout=60)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    have = {r[1] for r in con.execute("PRAGMA table_info(token_tier)")}
    for col, typ in CURVE_COLS.items():
        if col not in have:
            con.execute(f"ALTER TABLE token_tier ADD COLUMN {col} {typ}")
    return con


def get(con, token):
    r = con.execute("SELECT * FROM token_tier WHERE token=?", (token,)).fetchone()
    return dict(r) if r else None


def upsert(con, token, now=None, **vals):
    """Insert or update the row; razina never goes down, credits add up."""
    now = int(now or time.time())
    cur = get(con, token)
    if cur is None:
        con.execute("INSERT INTO token_tier (token, first_ts, last_ts) VALUES (?,?,?)", (token, now, now))
        cur = {"razina": 0, "credits": 0}
    sets, args = ["last_ts=?"], [now]
    for k, v in vals.items():
        if k == "credits":
            sets.append("credits=credits+?")
            args.append(int(v or 0))
        elif k == "razina":
            sets.append("razina=MAX(razina,?)")
            args.append(int(v))
        elif k in COLS:
            sets.append(f"{k}=?")
            args.append(v)
    args.append(token)
    con.execute(f"UPDATE token_tier SET {', '.join(sets)} WHERE token=?", args)


def reach(con, token, razina, credits=0, razlog=None, now=None):
    """A paid check ran for this token: record the tier it reached and what it cost."""
    vals = {"razina": razina, "credits": credits}
    if razlog:
        vals["razlog"] = razlog
    upsert(con, token, now, **vals)


def recent_tokens(con, hours=48, now=None):
    since = int((now or time.time()) - hours * 3600)
    return [r["token"] for r in con.execute("SELECT token FROM token_tier WHERE last_ts >= ?", (since,))]


def summary(con, hours=24, now=None):
    """Counts per T0 outcome and per class in the last `hours`, for the dashboard."""
    since = int((now or time.time()) - hours * 3600)
    out = {"t0": {}, "klasa": {}, "razina": {}}
    for r in con.execute("SELECT t0, klasa, razina, COUNT(*) n FROM token_tier WHERE last_ts >= ? "
                         "GROUP BY t0, klasa, razina", (since,)):
        out["t0"][r["t0"] or "nije"] = out["t0"].get(r["t0"] or "nije", 0) + r["n"]
        out["klasa"][r["klasa"] or "?"] = out["klasa"].get(r["klasa"] or "?", 0) + r["n"]
        out["razina"][r["razina"]] = out["razina"].get(r["razina"], 0) + r["n"]
    return out


def crossings(cur, mcap):
    """Bands a token crosses now for the first time: its stored mcap (or none) was below, the new one is at or
    above. A token first seen already far above a band (more than 2x) did not cross it on our watch."""
    out = []
    prev = (cur or {}).get("mcap")
    for point, band in EVENT_BANDS.items():
        if (mcap or 0) < band:
            continue
        if prev is None and mcap <= 2 * band or prev is not None and prev < band:
            out.append(point)
    return out


def record_event(con, token, point, mcap, price, score, features, now=None):
    """Features at a decision point, kept once per (token, point); the learning loop judges from here."""
    con.execute("INSERT OR IGNORE INTO tier_events VALUES (?,?,?,?,?,?,?)",
                (token, point, int(now or time.time()), mcap, price, score, json.dumps(features)))


def events(con, point, since=None):
    sql = "SELECT token, point, ts, mcap, price, score, features FROM tier_events WHERE point=?"
    args = [point]
    if since:
        sql += " AND ts >= ?"
        args.append(int(since))
    return [dict(zip(("token", "point", "ts", "mcap", "price", "score", "features"), r)) | {"features": json.loads(r[6] or "{}")}
            for r in con.execute(sql + " ORDER BY ts", args)]


def dumps(x):
    return json.dumps(x, ensure_ascii=False)
