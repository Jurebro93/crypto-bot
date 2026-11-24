"""topics.db: event topics (Grok's or the owner's), the Solana tokens that match them, and the price around the event.
Writers: run_topics.py (the job), the MCP tool submit_event_topic (ui/mcpapi -> topics/view.submit) and the PumpPortal
feed's hook (topics/hook.py, a queued writer thread). Everyone else reads it read-only.

Tables
  event_topics   one row per topic: name (upsert key: its normal form), keywords (JSON list incl. tickers), event_ts
                 (nullable), buzz_score, buzz_hist (JSON [[ts, score], ...], the newest BUZZ_KEEP points, for the trend),
                 source (where the client saw it, e.g. "x"), created_by grok | owner, kid (the MCP key fingerprint),
                 status upcoming | live | done, created_ts, updated_ts, the job's search state
  topic_tokens   one row per (topic, token): first_seen, match_field (symbol | name | description), match_kw, via
                 (pumpportal_create | pumpportal_migration | dexscreener_search | birdeye_search | profile), role
                 main | clone | rug | other (+ role_why), metrics (JSON snapshot: mcap, liquidity, volume, age, pool...)
  topic_measure  per (topic, token): the price 24 h before event_ts, at event_ts and 24 h after (from snapshots we
                 already store, GeckoTerminal only within TOPICS_GT_DAY), each with its time and source
  topic_log      every MCP / owner write (ts, topic_id, kid, what): the audit trail and the hourly rate limit
  kv             watermarks (the PumpPortal launch scan, scan.db profiles) and day counters per paid source
"""
import json
import os
import sqlite3
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLAG = "event_tokens"
STATUSES = ("upcoming", "live", "done")
ACTIVE = ("upcoming", "live")
BUZZ_KEEP = 48

SCHEMA = """
CREATE TABLE IF NOT EXISTS event_topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE, keywords TEXT NOT NULL,
    event_ts INTEGER, buzz_score REAL, buzz_hist TEXT, source TEXT, created_by TEXT, kid TEXT, status TEXT NOT NULL,
    created_ts INTEGER, updated_ts INTEGER, note TEXT, last_search_ts INTEGER, search_i INTEGER DEFAULT 0,
    last_bird_ts INTEGER, backfill_ts INTEGER);
CREATE TABLE IF NOT EXISTS topic_tokens (
    topic_id INTEGER NOT NULL, token TEXT NOT NULL, first_seen INTEGER, match_field TEXT, match_kw TEXT, via TEXT,
    symbol TEXT, name TEXT, created_ts INTEGER, role TEXT, role_why TEXT, metrics TEXT, metrics_ts INTEGER,
    PRIMARY KEY (topic_id, token));
CREATE INDEX IF NOT EXISTS topic_tokens_token ON topic_tokens (token);
CREATE TABLE IF NOT EXISTS topic_measure (
    topic_id INTEGER NOT NULL, token TEXT NOT NULL, event_ts INTEGER, before_ts INTEGER, before_px REAL, before_mc REAL,
    before_src TEXT, at_ts INTEGER, at_px REAL, at_mc REAL, at_src TEXT, after_ts INTEGER, after_px REAL,
    after_mc REAL, after_src TEXT, note TEXT, updated_ts INTEGER, PRIMARY KEY (topic_id, token));
CREATE TABLE IF NOT EXISTS topic_log (ts INTEGER, topic_id INTEGER, kid TEXT, what TEXT);
CREATE INDEX IF NOT EXISTS topic_log_kid ON topic_log (kid, ts);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""


def db_path():
    """topics.db on the persistent disk: TOPICS_DB, else DATA_DIR (Render /var/data), else the repository root."""
    if os.environ.get("TOPICS_DB"):
        return os.environ["TOPICS_DB"]
    data = os.environ.get("DATA_DIR")
    if data and os.path.isdir(data):
        return os.path.join(data, "topics.db")
    return os.path.join(ROOT, "topics.db")


def connect(path=None, timeout=30):
    p = path or db_path()
    new = not os.path.exists(p) or not os.path.getsize(p)
    con = sqlite3.connect(p, timeout=timeout)
    if new:
        con.execute("PRAGMA auto_vacuum=INCREMENTAL")
    con.executescript(SCHEMA)
    return con


def ro(path=None):
    """Read-only connection, None while topics.db does not exist (no topic ever submitted)."""
    p = path or db_path()
    if not os.path.exists(p) or not os.path.getsize(p):
        return None
    try:
        return sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return None


def mode(trade_db=None):
    """The flag event_tokens (trade settings G19): off | shadow | paper | live ("off" when unreadable)."""
    try:
        from trade import settings
        return settings.flag(FLAG, path=trade_db) if trade_db else settings.flag(FLAG)
    except Exception:  # noqa: BLE001
        return "off"


def kv_get(con, k, default=None):
    r = con.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    if not r:
        return default
    try:
        return json.loads(r[0])
    except ValueError:
        return default


def kv_put(con, k, v):
    con.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (k, json.dumps(v)))


def _day(now):
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def day_used(con, key, now):
    d = kv_get(con, f"day:{key}") or {}
    return int(d.get(_day(now), 0))


def day_add(con, key, n, now):
    d = kv_get(con, f"day:{key}") or {}
    day = _day(now)
    keep = {k: v for k, v in d.items() if k >= _day(now - 8 * 86400)}   # a week of history for the weekly report
    keep[day] = int(keep.get(day, 0)) + int(n)
    kv_put(con, f"day:{key}", keep)
    return keep[day]


def topic_row(r, cols):
    d = dict(zip(cols, r))
    for k in ("keywords", "buzz_hist"):
        try:
            d[k] = json.loads(d.get(k) or "[]")
        except ValueError:
            d[k] = []
    return d


def topics(con, status=None):
    """[topic dict] (all, or only these statuses), newest first."""
    sql, args = "SELECT * FROM event_topics", []
    if status:
        st = [status] if isinstance(status, str) else list(status)
        sql += f" WHERE status IN ({','.join('?' * len(st))})"
        args = st
    cur = con.execute(sql + " ORDER BY id DESC", args)
    cols = [c[0] for c in cur.description]
    return [topic_row(r, cols) for r in cur.fetchall()]


def topic(con, tid):
    cur = con.execute("SELECT * FROM event_topics WHERE id=?", (int(tid),))
    cols = [c[0] for c in cur.description]
    r = cur.fetchone()
    return topic_row(r, cols) if r else None


def add_match(con, tid, token, now, field, kw, via, symbol=None, name=None, created_ts=None, metrics=None):
    """One matched token (first sighting wins; a later sighting fills what the first did not know). True when new."""
    m = json.dumps(metrics, separators=(",", ":")) if metrics else None
    cur = con.execute("INSERT OR IGNORE INTO topic_tokens (topic_id, token, first_seen, match_field, match_kw, via, symbol, "
                      "name, created_ts, role, metrics, metrics_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (int(tid), token, int(now), field, kw, via, (symbol or "")[:30] or None, (name or "")[:80] or None,
                       int(created_ts) if created_ts else None, "other", m, int(now) if m else None))
    if cur.rowcount:
        return True
    con.execute("UPDATE topic_tokens SET symbol=COALESCE(symbol, ?), name=COALESCE(name, ?), "
                "created_ts=COALESCE(created_ts, ?) WHERE topic_id=? AND token=?",
                ((symbol or "")[:30] or None, (name or "")[:80] or None, int(created_ts) if created_ts else None,
                 int(tid), token))
    if m:
        con.execute("UPDATE topic_tokens SET metrics=?, metrics_ts=? WHERE topic_id=? AND token=?",
                    (m, int(now), int(tid), token))
    return False


def tokens_of(con, tid):
    cur = con.execute("SELECT * FROM topic_tokens WHERE topic_id=? ORDER BY first_seen", (int(tid),))
    cols = [c[0] for c in cur.description]
    out = []
    for r in cur.fetchall():
        d = dict(zip(cols, r))
        try:
            d["metrics"] = json.loads(d.get("metrics") or "{}")
        except ValueError:
            d["metrics"] = {}
        out.append(d)
    return out


def active_tokens(con, roles=("main", "other")):
    """{token: (topic_id, role)} of the tokens of active topics in these roles (the range watchlist's event source)."""
    q = ",".join("?" * len(ACTIVE))
    r = ",".join("?" * len(roles))
    out = {}
    for tok, tid, role in con.execute(
            f"SELECT tt.token, tt.topic_id, tt.role FROM topic_tokens tt JOIN event_topics t ON t.id = tt.topic_id "
            f"WHERE t.status IN ({q}) AND COALESCE(tt.role, 'other') IN ({r}) ORDER BY tt.first_seen",
            (*ACTIVE, *roles)):
        out.setdefault(tok, (tid, role))
    return out


def log(con, tid, kid, what, now=None):
    con.execute("INSERT INTO topic_log VALUES (?,?,?,?)", (int(now or time.time()), tid, kid, str(what)[:300]))
