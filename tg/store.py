"""tg.db: Telegram call channels (candidates, status, poll schedule) and their posts that name a token.

run_tg.py is the writer (the optional Telethon listener writes posts through save_posts too, short transactions).
kol/collect.from_telegram copies posts with a CA into kol.db calls (source 'tg'), and every CA post also goes to
hype.db tg_mentions, which the hype scan (feature 'telegram') and the Korelacije page read.
"""
import json
import os
import sqlite3
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("TG_DB", os.path.join(HERE, "tg.db"))
HYPE_DB = os.environ.get("HYPE_DB", os.path.join(HERE, "hype.db"))

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


def add_candidates(con, names, via, now=None):
    """New channel names (already normalised); known ones are left alone. Returns how many were new."""
    now = now or int(time.time())
    n = 0
    for name in names:
        if name:
            n += con.execute("INSERT OR IGNORE INTO channels (name, found_via, found_ts) VALUES (?,?,?)",
                             (name, via, now)).rowcount
    return n


def save_posts(con, channel, posts, source="web", now=None, hype_db=None):
    """Store posts newer than the channel's last one; only posts naming a CA or $TICKER keep their text.
    Returns the list of new posts with a CA (also written to hype.db tg_mentions)."""
    now = now or int(time.time())
    last = (con.execute("SELECT last_post FROM channels WHERE name=?", (channel,)).fetchone() or (0,))[0] or 0
    new = [p for p in posts if p["post"] > last]
    with_ca = []
    for p in new:
        keep = bool(p["cas"] or p["tickers"])
        con.execute("INSERT OR IGNORE INTO posts VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (channel, p["post"], p["ts"], now, p["text"] if keep else None, ",".join(p["cas"]),
                     ",".join(p["tickers"]), p.get("views") or 0, p.get("fwd_from"), source))
        if p["cas"]:
            with_ca.append(p)
    if new:
        top = max(new, key=lambda p: p["post"])
        ca_ts = max((p["ts"] or 0 for p in with_ca), default=None)
        con.execute("""UPDATE channels SET last_post=MAX(COALESCE(last_post,0), ?), last_post_ts=?,
                       last_ca_ts=MAX(COALESCE(last_ca_ts,0), COALESCE(?,0)), n_posts=n_posts+?, n_ca=n_ca+? WHERE name=?""",
                    (top["post"], top["ts"], ca_ts, len(new), len(with_ca), channel))
    if with_ca:
        mention(channel, with_ca, hype_db)
        try:   # 9.11. (audit P25): a CA from a followed channel (2-second set) wakes the copy loop at once
            from tg import poll as _poll
            if channel in _poll.followed_channels():
                from league import copy as _copy
                _copy.wake()
        except Exception:  # noqa: BLE001
            pass
    return with_ca


def mention(channel, posts, hype_db=None):
    """hype.db tg_mentions rows (channel, 'channel/post', ISO time, ca, tickers), the shape run_hype wrote before."""
    import datetime as dt
    path = hype_db or HYPE_DB
    try:
        h = sqlite3.connect(path, timeout=60)
        h.execute("CREATE TABLE IF NOT EXISTS tg_mentions (channel TEXT, post TEXT, time TEXT, ca TEXT, tickers TEXT, "
                  "PRIMARY KEY (post, ca))")
        for p in posts:
            when = dt.datetime.fromtimestamp(p["ts"] or time.time(), dt.timezone.utc).isoformat()
            for ca in p["cas"]:
                h.execute("INSERT OR IGNORE INTO tg_mentions VALUES (?,?,?,?,?)",
                          (channel, f"{channel}/{p['post']}", when, ca, ",".join(p["tickers"])))
        h.commit()
        h.close()
    except sqlite3.Error as e:
        print(f"tg_mentions: {e}")


def prune(con, days, now=None):
    """Posts older than `days`: drop the text (the call itself lives on in kol.db), then rows without a CA."""
    cut = (now or int(time.time())) - days * 86400
    a = con.execute("DELETE FROM posts WHERE seen_ts < ? AND (cas IS NULL OR cas = '')", (cut,)).rowcount
    con.execute("UPDATE posts SET text=NULL WHERE seen_ts < ?", (cut,))
    return a


def summary(path=None):
    """For the dashboard: counts per status, the best channels, recent CA posts. None without tg.db."""
    con = ro(path)
    if con is None:
        return None
    try:
        st = dict(con.execute("SELECT status, COUNT(*) FROM channels GROUP BY status"))
        chans = con.execute("""SELECT name, title, subs, status, found_via, n_posts, n_ca, last_ca_ts, lag_s, joined
                               FROM channels WHERE status IN ('active','quiet','slow') ORDER BY last_ca_ts DESC
                               LIMIT 300""").fetchall()
        recent = con.execute("""SELECT channel, post, ts, seen_ts, cas, text, views, fwd_from, source FROM posts
                                WHERE cas != '' ORDER BY seen_ts DESC LIMIT 60""").fetchall()
        meta = dict(con.execute("SELECT key, value FROM kv"))
        return {"status": st, "channels": chans, "recent": recent, "kv": {k: json.loads(v) for k, v in meta.items()}}
    except sqlite3.OperationalError:
        return None
    finally:
        con.close()
