"""Site log of the public site: "MemeSonar je live N dana" and what each night's refresh found new.

10.11.2026. (Jure): "na naslovnu dodao log: naša stranica je live 47 dana, evo što smo dodali na blogovima i u
podacima; osvježili smo taj i taj blog s novim podacima, dodali smo nove influencere, nove wallete, nove povijesne
tradeove; interni linkovi na blogove."

- record(): called once a day by the 02:00 job (run_web.py daily, scheduled in run_sched.py). It counts a handful of
  things in our own databases (no network, no paid source), compares them with the previous day's row and stores one
  row in public.db site_log: what was added that day.
- today(), recent(n), live_days(): what pages read. Read-only; a missing file or table simply means "nothing yet", so
  a page never breaks on it. The landing page reads recent() inside its background count (ui/landing.compute), never
  per request.
- marker(), check(), watch(): the scheduler is another process, so the web process cannot be told directly that the
  night's refresh happened. The newest row's (day, ts) is the marker; one background thread of the web process reads
  it every WATCH_S seconds (one row by primary key, never on a request) and, when it moved, calls on_change() once,
  which drops the in-memory copies of public data (ui/landing.refreshed).
"""
import datetime as dt
import json
import os
import sqlite3
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TZ = "Europe/Zagreb"                 # the site's day is the owner's day: the job runs at 02:00 there
WATCH_S = int(os.environ.get("SITE_WATCH_S", "60"))
KEEP_DAYS = 400                      # older rows are dropped (the page shows the last few days)
NEW_POSTS_DAYS = 7                   # a post is "new" for a week after its date, until a row has named it

# The day the public site went live. Where it comes from (10.11.2026.):
#   - share/novosti.json lists under 2026-11-01 "Naslovna stranica" (the new public page for people without an
#     account), "Blog", "Javna ljestvica meme coina", "Javni kripto rječnik" and "Novo ime: MemeSonar";
#   - the launch posts of the blog (ui/blogposts*.py) carry date 2026-11-01 (28 of the 33 posts; the other 5: 9.11.);
#   - the earliest entry of share/novosti.json is 2026-10-31, and it is about the members' app (KOL test, morning
#     report), not the public site, so it is not the public launch.
# Not known from the repository: the day memesonar.app itself started answering (the 1.11. entry says "uskoro").
# The git history of this repository is shallow (it starts on 4.11.), so the commit that added ui/landing.py cannot
# confirm it. Jure's "47 dana" was an example in his message: 47 days before 10.11. is 24.9., a month before the
# tool's first network run (README: 2026-10-30). If the site should count from another day, set SITE_LIVE_SINCE.
# 10.11. (Jure): "24.9." -> the site counts from 24.9.2026.
LIVE_SINCE = "2026-09-24"

DB = None   # None = public.db (ui/coins.DB); tests point it at a temp file

SCHEMA = """
CREATE TABLE IF NOT EXISTS site_log (day TEXT PRIMARY KEY, ts INTEGER, counts TEXT, added TEXT, blogs TEXT,
    posts TEXT);
"""
# what is counted every night, in the order the page shows it
KEYS = ("kols", "calls", "channels", "wallets", "trades", "coins", "tokens")


# ---------- the site's day ------------------------------------------------------------------------------------------

def _local(now=None):
    """`now` (epoch seconds, an aware datetime or None = this moment) as a Zagreb datetime."""
    if isinstance(now, dt.datetime):
        utc = now.astimezone(dt.timezone.utc)
    else:
        utc = dt.datetime.fromtimestamp(time.time() if now is None else now, dt.timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return utc.astimezone(ZoneInfo(TZ))
    except Exception:  # noqa: BLE001 - no tz database on this machine: winter time is close enough for a date
        return utc + dt.timedelta(hours=1)


def local_day(now=None):
    """The Zagreb date as 'YYYY-MM-DD'."""
    return _local(now).date().isoformat()


def start_date():
    """LIVE_SINCE, or SITE_LIVE_SINCE=YYYY-MM-DD when set (an unreadable value falls back to the constant)."""
    for s in ((os.environ.get("SITE_LIVE_SINCE") or "").strip(), LIVE_SINCE):
        try:
            return dt.date.fromisoformat(s)
        except ValueError:
            continue
    return dt.date(2026, 9, 24)


def live_days(now=None):
    """Whole days since the site went live (0 on the launch day; never negative)."""
    return max(0, (_local(now).date() - start_date()).days)


# ---------- counting ------------------------------------------------------------------------------------------------

def _file(env, name):
    return os.environ.get(env) or os.path.join(ROOT, name)


def _one(path, sql, args=()):
    """First column of the first row, or None (missing file or table, locked, anything)."""
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return None
    try:
        r = con.execute(sql, args).fetchone()
        return r[0] if r else None
    except sqlite3.Error:
        return None
    finally:
        con.close()


def counts():
    """{key: number} of what we count every night, from our own databases only (no network). A database or table
    that is missing leaves its key out; a key missing on one of two days is simply not compared.
    Runs once a day in the job's own short process: COUNT over the calls table is a full read, fine there, never
    in a page handler."""
    kol, wal = _file("KOL_DB", "kol.db"), _file("WALLET_DB", "wallets.db")
    v = {}
    try:
        from ui import public
        v["kols"] = len(public.influencers())     # exactly the rows a visitor sees on the public leaderboard
    except Exception as e:  # noqa: BLE001
        print(f"dnevnik weba: ljestvica influencera nije izbrojana: {type(e).__name__}: {e}", flush=True)
    v["calls"] = _one(kol, "SELECT COUNT(*) FROM calls WHERE kind='call' AND max24 IS NOT NULL")   # measured calls
    v["channels"] = _one(_file("TG_DB", "tg.db"), "SELECT COUNT(*) FROM channels WHERE status IN ('active','quiet','slow')")
    v["wallets"] = _one(wal, "SELECT COUNT(*) FROM wallets")
    # MAX(rowid) instead of COUNT over millions of trades. A VACUUM renumbers rowids, so after pruned rows the number
    # can fall once; a fall is not shown (diff), and the next night compares like with like again.
    v["trades"] = _one(wal, "SELECT MAX(rowid) FROM wallet_trades")
    v["coins"] = _one(path(), "SELECT COUNT(*) FROM coins")       # every coin that has a public page
    hype = _file("HYPE_DB", "hype.db")
    tiers, rugs = _one(hype, "SELECT COUNT(*) FROM token_tier"), _one(hype, "SELECT COUNT(*) FROM rug_archive")
    if tiers is not None or rugs is not None:
        v["tokens"] = (tiers or 0) + (rugs or 0)                  # tokens checked, the same sum as on the landing page
    return {k: int(x) for k, x in v.items() if x is not None}


def diff(prev, cur):
    """What was added between two nights: only keys counted on both, only growth. A count that fell (bots thrown out
    of the leaderboard, old rows pruned) is not news and is left out."""
    return {k: cur[k] - prev[k] for k in KEYS if k in cur and k in prev and cur[k] > prev[k]}


def new_posts(day, listed=()):
    """English slugs of blog posts dated in the NEW_POSTS_DAYS up to `day` that no earlier row named, newest first.
    10.11.: "not named before", not "dated after the previous row": a post dated the 11th that reaches the server by a
    deploy after the night's run on the 11th fell between two rows and was never named. The very first row has no
    earlier row, so it names the posts of the last week."""
    lo = (dt.date.fromisoformat(day) - dt.timedelta(days=NEW_POSTS_DAYS)).isoformat()
    try:
        from ui import blog
        ps = [p for p in blog._posts() if lo < p.get("date", "") <= day and p["slug"] not in listed]
    except Exception as e:  # noqa: BLE001
        print(f"dnevnik weba: novi članci nisu pročitani: {type(e).__name__}: {e}", flush=True)
        return []
    return [p["slug"] for p in sorted(ps, key=lambda p: p["date"], reverse=True)]


# ---------- storing -------------------------------------------------------------------------------------------------

def path():
    if DB:
        return DB
    from ui import coins
    return coins.DB


def connect(db=None):
    con = sqlite3.connect(db or path(), timeout=30)   # the web process writes coins here too: wait, do not fail
    con.executescript(SCHEMA)
    return con


def _row(r):
    def js(s, empty):
        try:
            return json.loads(s) if s else empty
        except ValueError:
            return empty
    return {"day": r[0], "ts": r[1] or 0, "counts": js(r[2], {}), "added": js(r[3], {}), "blogs": js(r[4], []),
            "posts": js(r[5], [])}


def record(now=None, blogs=(), counted=None, db=None):
    """Count, compare with the previous day's row and store today's row. Returns the stored entry (plus 'first':
    True when there was no earlier day to compare with).
    blogs: English slugs of posts whose data block changed tonight (ui/bloglive.refresh). Running it again on the
    same day compares with the same previous day and keeps what the first run listed."""
    ts = int(now.timestamp() if isinstance(now, dt.datetime) else (time.time() if now is None else now))
    day = local_day(ts)
    cur = counts() if counted is None else {k: int(v) for k, v in counted.items() if v is not None}
    con = connect(db)
    try:
        prev = con.execute("SELECT day, ts, counts, added, blogs, posts FROM site_log WHERE day < ? "
                           "ORDER BY day DESC LIMIT 1", (day,)).fetchone()
        same = con.execute("SELECT day, ts, counts, added, blogs, posts FROM site_log WHERE day = ?", (day,)).fetchone()
        prev, same = (_row(prev) if prev else None), (_row(same) if same else None)
        added = diff(prev["counts"], cur) if prev else {}
        # posts named by the rows of the last two weeks (one a night; a post stays "new" for NEW_POSTS_DAYS)
        named = set()
        for r in con.execute("SELECT day, ts, counts, added, blogs, posts FROM site_log WHERE day < ? "
                             "ORDER BY day DESC LIMIT ?", (day, 2 * NEW_POSTS_DAYS)):
            p = _row(r)["posts"]
            named.update(s for s in (p if isinstance(p, list) else []) if isinstance(s, str))
        posts = new_posts(day, named)
        fresh = [s for s in dict.fromkeys(list((same or {}).get("blogs", [])) + list(blogs)) if s not in posts]
        con.execute("INSERT INTO site_log (day, ts, counts, added, blogs, posts) VALUES (?,?,?,?,?,?) "
                    "ON CONFLICT(day) DO UPDATE SET ts=excluded.ts, counts=excluded.counts, added=excluded.added, "
                    "blogs=excluded.blogs, posts=excluded.posts",
                    (day, ts, json.dumps(cur), json.dumps(added), json.dumps(fresh), json.dumps(posts)))
        con.execute("DELETE FROM site_log WHERE day < ?",
                    ((_local(ts).date() - dt.timedelta(days=KEEP_DAYS)).isoformat(),))
        con.commit()
    finally:
        con.close()
    return {"day": day, "ts": ts, "counts": cur, "added": added, "blogs": fresh, "posts": posts, "first": prev is None}


# ---------- reading -------------------------------------------------------------------------------------------------

def _read(sql, args=(), db=None):
    p = db or path()
    if not p or not os.path.exists(p) or not os.path.getsize(p):
        return []
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.Error:   # no table yet (the job has never run), locked
        return []
    finally:
        con.close()


def recent(n=5, db=None):
    """The last n days of the log, newest first: [{day, ts, counts, added, blogs, posts}]. [] before the first run."""
    return [_row(r) for r in _read("SELECT day, ts, counts, added, blogs, posts FROM site_log ORDER BY day DESC LIMIT ?",
                                   (int(n),), db)]


def today(now=None, db=None):
    """Today's entry (Zagreb day), or None while today's refresh has not run yet."""
    r = recent(1, db)
    return r[0] if r and r[0]["day"] == local_day(now) else None


def has_news(entry):
    """True when the entry has something to show (a day on which nothing grew is not listed)."""
    return bool(entry and (entry.get("added") or entry.get("blogs") or entry.get("posts")))


# ---------- the marker the web process watches ----------------------------------------------------------------------

def marker(db=None):
    """(day, ts) of the newest row: "the last refresh". None before the first one (or when it cannot be read)."""
    r = _read("SELECT day, ts FROM site_log ORDER BY day DESC LIMIT 1", (), db)
    return (r[0][0], r[0][1]) if r else None


_SEEN = {"init": False, "m": None}
_SEEN_LOCK = threading.Lock()
_WATCHING = []


def check(on_change=None, db=None):
    """True when the marker moved since the last look; on_change() is then called, once per move.
    The first look only remembers where the marker is: a process that has just started holds nothing in memory.
    A marker that cannot be read (database busy) changes nothing; the next look decides."""
    m = marker(db)
    with _SEEN_LOCK:
        if not _SEEN["init"]:
            _SEEN.update(init=True, m=m)
            return False
        if m is None or m == _SEEN["m"]:
            return False
        _SEEN["m"] = m
    if on_change:
        try:
            on_change()
        except Exception as e:  # noqa: BLE001 - the pages keep working on their own cache times
            print(f"dnevnik weba: kopije u memoriji nisu osvježene: {type(e).__name__}: {e}", flush=True)
    print(f"dnevnik weba: noćno osvježavanje {m[0]} je gotovo, javne stranice čitaju nove podatke", flush=True)
    return True


def watch(on_change, every_s=None):
    """One background thread of the web process: looks at the marker every WATCH_S seconds (started by
    ui/landing.start). A second call does nothing."""
    with _SEEN_LOCK:
        if _WATCHING:
            return
        _WATCHING.append(True)

    def loop():
        while True:
            try:
                check(on_change)
            except Exception as e:  # noqa: BLE001
                print(f"dnevnik weba: provjera oznake nije uspjela: {type(e).__name__}: {e}", flush=True)
            time.sleep(every_s or WATCH_S)
    threading.Thread(target=loop, daemon=True, name="site-watch").start()
