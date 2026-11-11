"""fast.db (DATA_DIR): the fast path's queue and every decision, price points, followed sources, costs, reports, kv.

Writers: run_fast.py (the worker: decisions, outcomes, sources, costs, reports), the ingestion hooks (enqueue: one
INSERT, short busy wait, a failure is caught by the worker's own scan) and run_ui.py's demo trades (signals.traded).
Readers: the Autopilot card, the skip pop-up and the MCP tool get_fast_checks, read-only. WAL, so a reader never
waits for the worker.

signals.status: queued -> running -> done (BUY_PAPER / BUY_LIVE / SKIP) | retry (CHECK_FAILED, next try at next_ts) ->
failed (CHECK_FAILED after the last try). decision is never empty once a check ran: a skip always has its checks.
"""
import datetime as dt
import json
import os
import sqlite3
import time
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TZ = "Europe/Zagreb"
KEEP_DAYS = 30
PX_KEEP_S = 3 * 3600

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT NOT NULL, symbol TEXT, kind TEXT, source_id TEXT,
    source_label TEXT, follow_id INTEGER, via TEXT, sig_ts INTEGER, enq_ts REAL, entry_px REAL, entry_sol_px REAL,
    entry_mcap REAL, priority INTEGER DEFAULT 5, status TEXT DEFAULT 'queued', attempts INTEGER DEFAULT 0,
    next_ts REAL, started_ts REAL, decided_ts REAL, decision TEXT, reason TEXT, ev_pct REAL, p_tp REAL, cost_pct REAL,
    size_sol REAL, latency_s REAL, work_s REAL, checks TEXT, quality TEXT, mode TEXT, price0 REAL, mcap0 REAL,
    traded TEXT, out TEXT, out_done INTEGER DEFAULT 0, max60 REAL, missed INTEGER, hit INTEGER);
CREATE UNIQUE INDEX IF NOT EXISTS signals_key ON signals (token, source_id, sig_ts);
CREATE INDEX IF NOT EXISTS signals_queue ON signals (status, priority, enq_ts);
CREATE INDEX IF NOT EXISTS signals_decided ON signals (decided_ts);
CREATE INDEX IF NOT EXISTS signals_token ON signals (token, sig_ts);
CREATE INDEX IF NOT EXISTS signals_out ON signals (out_done, decided_ts);
CREATE TABLE IF NOT EXISTS px (token TEXT, ts INTEGER, price REAL, mcap REAL, PRIMARY KEY (token, ts));
CREATE TABLE IF NOT EXISTS sources (id TEXT PRIMARY KEY, kind TEXT, label TEXT, follow_id INTEGER, ts INTEGER);
CREATE TABLE IF NOT EXISTS costs (day TEXT, source TEXT, calls INTEGER DEFAULT 0, credits REAL DEFAULT 0,
    PRIMARY KEY (day, source));
CREATE TABLE IF NOT EXISTS reports (day TEXT PRIMARY KEY, ts INTEGER, data TEXT);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""
COLS = ("id", "token", "symbol", "kind", "source_id", "source_label", "follow_id", "via", "sig_ts", "enq_ts",
        "entry_px", "entry_sol_px", "entry_mcap", "priority", "status", "attempts", "next_ts", "started_ts",
        "decided_ts", "decision", "reason", "ev_pct", "p_tp", "cost_pct", "size_sol", "latency_s", "work_s", "checks",
        "quality", "mode", "price0", "mcap0", "traded", "out", "out_done", "max60", "missed", "hit")
JSON_COLS = ("checks", "quality", "traded", "out")
DECISIONS = ("BUY_PAPER", "BUY_LIVE", "SKIP", "CHECK_FAILED")


def db_path():
    """fast.db on the persistent disk (DATA_DIR, Render /var/data), like proposals.db."""
    if os.environ.get("FAST_DB"):
        return os.environ["FAST_DB"]
    data = os.environ.get("DATA_DIR")
    if data and os.path.isdir(data):
        return os.path.join(data, "fast.db")
    return os.path.join(ROOT, "fast.db")


def connect(path=None, timeout=30):
    p = path or db_path()
    new = not os.path.exists(p) or not os.path.getsize(p)
    con = sqlite3.connect(p, timeout=timeout, check_same_thread=False)
    if new:
        con.execute("PRAGMA auto_vacuum=INCREMENTAL")
    try:
        con.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        pass
    con.executescript(SCHEMA)
    return con


def ro(path=None):
    """Read-only connection, None while fast.db does not exist (the flag was never on)."""
    p = path or db_path()
    if not os.path.exists(p) or not os.path.getsize(p):
        return None
    try:
        return sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return None


def day_of(ts):
    return dt.datetime.fromtimestamp(int(ts), ZoneInfo(TZ)).date().isoformat()


def kv_get(con, k, default=None):
    try:
        r = con.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    except sqlite3.Error:
        return default
    if not r:
        return default
    try:
        return json.loads(r[0])
    except ValueError:
        return default


def kv_put(con, k, v):
    con.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (k, json.dumps(v, ensure_ascii=False)))


def _dict(r):
    d = dict(zip(COLS, r))
    for k in JSON_COLS:
        try:
            d[k] = json.loads(d[k]) if d[k] else {}
        except ValueError:
            d[k] = {}
    return d


def read(con, where="1=1", args=(), order="id DESC", limit=200):
    try:
        return [_dict(r) for r in con.execute(f"SELECT {', '.join(COLS)} FROM signals WHERE {where} ORDER BY {order} "
                                              f"LIMIT ?", (*args, int(limit)))]
    except sqlite3.Error:
        return []


def one(con, sid):
    got = read(con, "id=?", (int(sid),), limit=1)
    return got[0] if got else None


def add_cost(con, source, calls=1, credits=0.0, now=None):
    """One line per (Zagreb day, source): calls and credits (Helius credits; 0 for the free sources)."""
    con.execute("INSERT INTO costs (day, source, calls, credits) VALUES (?,?,?,?) ON CONFLICT (day, source) DO UPDATE "
                "SET calls = calls + excluded.calls, credits = credits + excluded.credits",
                (day_of(now or time.time()), source, int(calls), float(credits)))


def costs(con, day):
    """{source: {"calls", "credits"}} of one Zagreb day."""
    try:
        return {s: {"calls": c, "credits": round(cr or 0, 1)}
                for s, c, cr in con.execute("SELECT source, calls, credits FROM costs WHERE day=?", (day,))}
    except sqlite3.Error:
        return {}


def prune(con, now):
    con.execute("DELETE FROM signals WHERE COALESCE(decided_ts, enq_ts) < ?", (now - KEEP_DAYS * 86400,))
    con.execute("DELETE FROM px WHERE ts < ?", (int(now) - PX_KEEP_S,))
    con.execute("DELETE FROM costs WHERE day < ?", (day_of(now - 120 * 86400),))
    con.execute("DELETE FROM reports WHERE ts < ?", (int(now) - 120 * 86400,))
