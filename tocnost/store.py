"""tocnost.db: shown scores and the night's accuracy table. Its own file, so a page writing "this score was shown"
never waits on a source database's lock and the night batch stays read-only on every source database.

  prikaz   (score, subject, day) -> ts, bucket, value, ref, src: the FIRST time that day a score was shown for that
           subject, as it was then (INSERT OR IGNORE: a later view never overwrites it). ref = the market cap at that
           moment where the outcome needs a start. src: 'stranica' (a page) or 'noc' (the night snapshot of a score
           that has no history of its own: the influencer verdict, the copy rank).
  tocnost  (as_of, score, bucket) -> the counts of stat.aggregate; the pages read the newest as_of.
"""
import os
import sqlite3
import threading
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("TOCNOST_DB", os.path.join(HERE, "tocnost.db"))
SCHEMA = """
CREATE TABLE IF NOT EXISTS prikaz (
    score TEXT, subject TEXT, day TEXT, ts INTEGER, bucket TEXT, value REAL, ref REAL, src TEXT,
    PRIMARY KEY (score, subject, day));
CREATE INDEX IF NOT EXISTS prikaz_ts ON prikaz (score, ts);
CREATE TABLE IF NOT EXISTS tocnost (
    as_of INTEGER, score TEXT, bucket TEXT, dir INTEGER, n INTEGER, k INTEGER, rate REAL, lo REAL, hi REAL,
    correct INTEGER, acc REAL, acc_lo REAL, acc_hi REAL, base_n INTEGER, base_k INTEGER, base REAL, enough INTEGER,
    since INTEGER, note TEXT, PRIMARY KEY (as_of, score, bucket));
"""
KEEP_D = 60          # prikaz rows older than this are dropped by the night batch (the window is 30 days + horizon)
KEEP_RUNS_D = 90


def _day(ts):
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def connect(path=None):
    con = sqlite3.connect(path or DB, timeout=5)
    con.executescript(SCHEMA)
    return con


def ro(path=None):
    p = path or DB
    if not os.path.exists(p) or not os.path.getsize(p):
        return None
    try:
        return sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None


def log_shown(score, items, now=None, path=None, src="stranica"):
    """items: [(subject, bucket, value, ref)]. One row per score, subject and UTC day; silent on any error (a page
    must never fail over this). Returns rows written."""
    items = [i for i in (items or []) if i and i[0] and i[1] is not None]
    if not items:
        return 0
    now = int(now or time.time())
    try:
        con = connect(path)
    except sqlite3.Error:
        return 0
    try:
        n = 0
        for subject, bucket, value, ref in items:
            n += con.execute("INSERT OR IGNORE INTO prikaz VALUES (?,?,?,?,?,?,?,?)",
                             (score, str(subject), _day(now), now, str(bucket), value, ref, src)).rowcount
        con.commit()
        return n
    except sqlite3.Error:
        return 0
    finally:
        con.close()


def shown(con, score, since, until):
    """[{subject, ts, bucket, value, ref}] of prikaz rows of a score with since <= ts <= until."""
    try:
        rows = con.execute("SELECT subject, ts, bucket, value, ref FROM prikaz WHERE score=? AND ts>=? AND ts<=? "
                           "ORDER BY ts", (score, int(since), int(until))).fetchall()
    except sqlite3.Error:
        return []
    return [{"subject": s, "ts": t, "bucket": b, "value": v, "ref": r} for s, t, b, v, r in rows]


def save(con, as_of, score, aggs, note=""):
    for a in aggs:
        con.execute("INSERT OR REPLACE INTO tocnost VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (int(as_of), score, a["bucket"], a["dir"], a["n"], a["k"], a["rate"], a["lo"], a["hi"],
                     a["correct"], a["acc"], a["acc_lo"], a["acc_hi"], a["base_n"], a["base_k"], a["base"],
                     int(a["enough"]), int(a["since"]), note))


def prune(con, now):
    a = con.execute("DELETE FROM prikaz WHERE ts < ?", (int(now - KEEP_D * 86400),)).rowcount
    b = con.execute("DELETE FROM tocnost WHERE as_of < ?", (int(now - KEEP_RUNS_D * 86400),)).rowcount
    return a, b


_CACHE = {"ts": 0.0, "path": None, "rows": {}}
_LOCK = threading.Lock()
TTL_S = 600


def latest(path=None, ttl=TTL_S):
    """{(score, bucket): row dict} of the newest night; {} without the table. Cached `ttl` s per process."""
    p = path or DB
    with _LOCK:
        if _CACHE["path"] == p and time.time() - _CACHE["ts"] < ttl:
            return _CACHE["rows"]
        out = {}
        con = ro(p)
        if con is not None:
            try:
                con.row_factory = sqlite3.Row
                last = con.execute("SELECT MAX(as_of) FROM tocnost").fetchone()[0]
                if last:
                    for r in con.execute("SELECT * FROM tocnost WHERE as_of=?", (last,)):
                        out[(r["score"], r["bucket"])] = dict(r)
            except sqlite3.Error:
                out = {}
            finally:
                con.close()
        _CACHE.update(ts=time.time(), path=p, rows=out)
        return out


def clear_cache():
    _CACHE.update(ts=0.0, path=None, rows={})
