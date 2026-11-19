"""Visits of logged-in people (19.11., owner: "Izbaci sve korisnike koji nisu posjetili aplikaciju zadnjih 5 dana").

Before this nothing recorded who opened the app, so from this deploy on every authorized page request of a logged-in
person (cookie or Basic auth) notes "last visit" for that login name (run_ui._note_visit); a successful login and a
registration count too. Static files, icons, token images, avatars, the live JS polls (/api/, SSE), the MCP endpoints
and webhooks do not (counts()).

Cheap: the visit is kept in memory per name and written to league.db at most once per name per WRITE_EVERY s (only
the dashboard process writes league.db: its single-writer rule). Never raises: an error is swallowed with one log line
at most per hour.

league.db tables:
  posjeti        name, first_ts, last_ts, n_days (distinct Zagreb days with a written visit), last_day
  posjeti_start  one row: when the recording first started (kept across restarts and deploys; never moved)
"""
import datetime as _dt
import sqlite3
import threading
import time
import zoneinfo

from league import store

SCHEMA = """
CREATE TABLE IF NOT EXISTS posjeti (name TEXT PRIMARY KEY COLLATE NOCASE, first_ts INTEGER, last_ts INTEGER,
                                    n_days INTEGER, last_day TEXT);
CREATE TABLE IF NOT EXISTS posjeti_start (id INTEGER PRIMARY KEY CHECK (id = 1), ts INTEGER);
"""
WRITE_EVERY = 600
TZ = zoneinfo.ZoneInfo("Europe/Zagreb")
# not a visit: files, icons, images, the page's own live polls and streams, machine endpoints
SKIP_EXACT = {"/mcp", "/healthz", "/sw.js", "/robots.txt", "/sitemap.xml", "/jezik", "/odjava", "/autopilot/zivo"}
SKIP_PREFIX = ("/static/", "/img/", "/avatar/", "/api/", "/hook/", "/share/", "/admin/export/", "/pravi-trade/static/",
               "/pravi-trade/l/", "/favicon", "/apple-touch-icon", "/cekamo-deploy")
SKIP_PART = ("/api/", "/static/", "/stream")
SKIP_EXT = (".ico", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".css", ".js", ".json", ".webmanifest", ".xml",
            ".txt", ".woff", ".woff2", ".map")

_lock = threading.Lock()
_seen = {}       # (db path, lower name) -> {"name", "last", "written", "day"}
_started = {}    # db path -> start ts
_said = [0.0]


def counts(path):
    """True when a request for `path` is a person opening the app (a page or a form), not a file or a poll."""
    p = (path or "").split("?", 1)[0]
    if not p.startswith("/") or p in SKIP_EXACT or p.startswith(SKIP_PREFIX):
        return False
    low = p.lower()
    return not low.endswith(SKIP_EXT) and not any(x in low for x in SKIP_PART)


def _say(e):
    if time.time() - _said[0] >= 3600:
        _said[0] = time.time()
        print(f"posjeti: nije zapisano ({type(e).__name__}: {e})", flush=True)


def _day(ts):
    return _dt.datetime.fromtimestamp(ts, TZ).strftime("%Y-%m-%d")


def ensure(con):
    try:
        con.executescript(SCHEMA)
    except sqlite3.OperationalError:
        pass


def _start(con, now):
    con.execute("INSERT OR IGNORE INTO posjeti_start (id, ts) VALUES (1, ?)", (int(now),))
    r = con.execute("SELECT ts FROM posjeti_start WHERE id=1").fetchone()
    return int(r[0]) if r else None


def start(now=None):
    """The moment the recording started: stored at the first call, never moved by a later one (restart, deploy)."""
    db = store.DB
    if db in _started:
        return _started[db]
    try:
        con = store.connect()
        try:
            ensure(con)
            ts = _start(con, now or time.time())
            con.commit()
        finally:
            con.close()
    except sqlite3.Error as e:
        _say(e)
        return None
    if ts:
        _started[db] = ts
    return ts


def started_at(con=None):
    """When the recording started; None before it ever did. Read-only."""
    own = con is None
    try:
        con = con or store.connect()
        ensure(con)
        r = con.execute("SELECT ts FROM posjeti_start WHERE id=1").fetchone()
        return int(r[0]) if r else None
    except sqlite3.Error:
        return None
    finally:
        if own and con is not None:
            con.close()


def note(name, now=None):
    """`name` opened the app now. True when this call wrote league.db. Never raises."""
    try:
        if not name:
            return False
        now = int(now or time.time())
        key = (store.DB, name.strip().lower())
        with _lock:
            s = _seen.get(key)
            if s and now - s["written"] < WRITE_EVERY:
                s["last"] = max(s["last"], now)
                return False
            day = _day(now)
            con = store.connect()
            try:
                ensure(con)
                if store.DB not in _started:
                    _started[store.DB] = _start(con, now)
                r = con.execute("SELECT last_day FROM posjeti WHERE name=?", (name.strip(),)).fetchone()
                if r is None:
                    con.execute("INSERT INTO posjeti (name, first_ts, last_ts, n_days, last_day) VALUES (?,?,?,1,?)",
                                (name.strip(), now, now, day))
                else:
                    con.execute("UPDATE posjeti SET last_ts=MAX(COALESCE(last_ts, 0), ?), "
                                "n_days=COALESCE(n_days, 0) + (COALESCE(last_day, '') != ?), last_day=? WHERE name=?",
                                (now, day, day, name.strip()))
                con.commit()
            finally:
                con.close()
            _seen[key] = {"name": name.strip(), "last": now, "written": now, "day": day}
            return True
    except Exception as e:  # noqa: BLE001 - a visit note never fails a request
        _say(e)
        return False


def visits(con=None):
    """{lower name: {"name", "first_ts", "last_ts", "n_days"}}: league.db plus the newer visits still only in memory."""
    out = {}
    own = con is None
    try:
        con = con or store.connect()
        ensure(con)
        for r in con.execute("SELECT name, first_ts, last_ts, n_days FROM posjeti"):
            out[r[0].lower()] = {"name": r[0], "first_ts": r[1], "last_ts": r[2], "n_days": r[3] or 0}
    except sqlite3.Error as e:
        _say(e)
    finally:
        if own and con is not None:
            con.close()
    with _lock:
        for (db, low), s in _seen.items():
            if db != store.DB:
                continue
            d = out.setdefault(low, {"name": s["name"], "first_ts": s["last"], "last_ts": s["last"], "n_days": 1})
            d["last_ts"] = max(d["last_ts"] or 0, s["last"])
    return out


def last_visit(name, con=None):
    v = visits(con).get((name or "").strip().lower())
    return v["last_ts"] if v else None


def reset_cache():
    with _lock:
        _seen.clear()
        _started.clear()
