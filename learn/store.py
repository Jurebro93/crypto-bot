"""learn_runs in hype.db: every fit, applied or not, with the numbers behind the decision."""
import json
import os
import sqlite3
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(HERE, "hype.db")
SCHEMA = """
CREATE TABLE IF NOT EXISTS learn_runs (
    ts INTEGER, klasa TEXT, n INTEGER, skok REAL, applied INTEGER, metric_old REAL, metric_new REAL,
    old TEXT, new TEXT, note TEXT, PRIMARY KEY (ts, klasa));
"""


def connect(path=None):
    con = sqlite3.connect(path or DB, timeout=60)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def log_run(con, ts, klasa, n, skok, applied, metric_old, metric_new, old, new, note):
    con.execute("INSERT OR REPLACE INTO learn_runs VALUES (?,?,?,?,?,?,?,?,?,?)",
                (int(ts), klasa, n, skok, int(bool(applied)), metric_old, metric_new,
                 json.dumps(old), json.dumps(new), note))


def prune_empty(con):
    """Runs that only said "too few outcomes" (nothing fitted, nothing applied): keep the newest per class and UTC
    day. Every deploy used to re-run the daily fit, which filled the history with ~50 such rows a day."""
    return con.execute("""DELETE FROM learn_runs WHERE applied = 0 AND metric_new IS NULL AND ts < (
        SELECT MAX(r2.ts) FROM learn_runs r2 WHERE r2.klasa = learn_runs.klasa AND r2.applied = 0
        AND r2.metric_new IS NULL AND r2.ts / 86400 = learn_runs.ts / 86400)""").rowcount


def runs(con, klasa=None, limit=50):
    sql = "SELECT * FROM learn_runs" + (" WHERE klasa=?" if klasa else "") + " ORDER BY ts DESC LIMIT ?"
    rows = con.execute(sql, ((klasa, limit) if klasa else (limit,))).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["old"], d["new"] = json.loads(d["old"] or "{}"), json.loads(d["new"] or "{}")
        out.append(d)
    return out
