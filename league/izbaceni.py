"""Removed users (19.11., owner: "Izbaci sve korisnike koji nisu posjetili aplikaciju zadnjih 5 dana bez da me pitaš
išta dodatno").

A removed user cannot log in and leaves every list of users, but nothing of theirs is deleted (demo account, trades,
profile, avatar stay in league.db) and an admin brings them back with one tap on /korisnici ("Vrati").

  invite members  the existing soft delete (members.deleted; the name stays taken, nobody re-registers it)
  env players     their password lives in the server's settings, which code cannot remove, so the name goes into the
                  table `izbaceni`; run_ui.cookie_user / check_password, store.users() and /korisnici honour it
  both            listed in `izbaceni` (for "Vrati"), every session ends (profiles.logout_everywhere), their active
                  demo copy follows and DCA plans pause with stopped = the removal time (restore resumes exactly those)

The owner's order runs ONCE (run_order, from ui/assistnotes.owner_izbaci_1911, which the dashboard's dca_loop asks at
most hourly): when 5 days of recorded visits exist (league/posjeti.py; start + WINDOW), every user whose last recorded
visit is older than WINDOW, or who has none, is removed. Never removed: the owner (trade.settings.is_owner, and the
UI_ADMINS / TRADE_OWNER default admins), the tool's own accounts (members.reserved) and the view-only test account.

Only the dashboard process writes league.db; is_out() is cached in memory (CACHE_S in other processes' readers).
"""
import datetime
import json
import os
import sqlite3
import threading
import time

from league import store

SCHEMA = """
CREATE TABLE IF NOT EXISTS izbaceni (name TEXT PRIMARY KEY COLLATE NOCASE, ts INTEGER, why TEXT, by TEXT, kind TEXT);
CREATE TABLE IF NOT EXISTS izbaceni_nalog (key TEXT PRIMARY KEY, ts INTEGER, v TEXT);
"""
ORDER_KEY = "owner_once:izbaci_neaktivne_1911"
WINDOW = 5 * 86400
WHY = "nalog vlasnika 19.11.: bez posjeta aplikaciji 5 dana"
BY = "nalog vlasnika 19.11."
CACHE_S = 60
_lock = threading.Lock()
_cache = {}   # db path -> (loaded ts, {lower name})


def ensure(con):
    try:
        con.executescript(SCHEMA)
    except sqlite3.OperationalError:
        pass


def connect():
    con = store.connect()
    ensure(con)
    return con


def _out():
    db = store.DB
    with _lock:
        c = _cache.get(db)
        if c and time.time() - c[0] < CACHE_S:
            return c[1]
    try:
        con = store.connect()
        try:
            ensure(con)
            names = {r[0].lower() for r in con.execute("SELECT name FROM izbaceni")}
        finally:
            con.close()
    except sqlite3.Error:
        return set()
    with _lock:
        _cache[db] = (time.time(), names)
    return names


def is_out(name):
    """True when `name` was removed (and not brought back). Never raises."""
    return bool(name) and name.strip().lower() in _out()


def reset_cache():
    with _lock:
        _cache.clear()


def rows(con=None):
    """Removed users, newest first: [{name, ts, why, by, kind}]."""
    own = con is None
    try:
        con = con or store.connect()
        ensure(con)
        return [dict(zip(("name", "ts", "why", "by", "kind"), r))
                for r in con.execute("SELECT name, ts, why, by, kind FROM izbaceni ORDER BY ts DESC, name")]
    except sqlite3.Error:
        return []
    finally:
        if own and con is not None:
            con.close()


def _pause_plans(con, name, ts):
    for table in ("follows", "dca_plans"):
        try:
            con.execute(f"UPDATE {table} SET active=0, stopped=? WHERE user=? AND active=1", (ts, name))
        except sqlite3.OperationalError:
            pass


def _resume_plans(con, name, ts):
    for table in ("follows", "dca_plans"):
        try:
            con.execute(f"UPDATE {table} SET active=1, stopped=NULL WHERE user=? AND active=0 AND stopped=?", (name, ts))
        except sqlite3.OperationalError:
            pass


def remove(con, name, why, by, now=None):
    """`name` can no longer log in and leaves every list; nothing of theirs is deleted. Returns the stored name."""
    from league import members, profiles
    name = (name or "").strip()
    if not name:
        raise ValueError("koga izbacuješ?")
    ensure(con)
    try:
        con.executescript(members.SCHEMA)
    except sqlite3.OperationalError:
        pass
    members._migrate(con)
    now = int(now or time.time())
    r = con.execute("SELECT name FROM members WHERE name=? AND deleted IS NULL", (name,)).fetchone()
    kind = "member" if r else "env"
    name = r[0] if r else name
    con.execute("INSERT OR REPLACE INTO izbaceni (name, ts, why, by, kind) VALUES (?,?,?,?,?)",
                (name, now, why, by, kind))
    if kind == "member":
        con.execute("UPDATE members SET deleted=? WHERE name=? AND deleted IS NULL", (now, name))
    _pause_plans(con, name, now)
    con.commit()
    try:
        profiles.logout_everywhere(name)
    except Exception as e:  # noqa: BLE001 - the removal itself already blocks every login
        print(f"korisnici: odjava {name} nije zapisana ({type(e).__name__})", flush=True)
    reset_cache()
    return name


def restore(con, name, by):
    """Brings a removed user back exactly as they were (a member's soft delete of the removal is undone)."""
    ensure(con)
    r = con.execute("SELECT name, ts, kind FROM izbaceni WHERE name=?", ((name or "").strip(),)).fetchone()
    if not r:
        raise ValueError(f"{name} nije na popisu izbačenih")
    name, ts, kind = r[0], r[1], r[2]
    if kind == "member":
        from league import members
        members._migrate(con)
        con.execute("UPDATE members SET deleted=NULL WHERE name=? AND deleted=?", (name, ts))
    _resume_plans(con, name, ts)
    con.execute("DELETE FROM izbaceni WHERE name=?", (name,))
    con.commit()
    reset_cache()
    print(f"korisnici: {by or '-'} je vratio {name}", flush=True)
    return name


# --- the owner's order of 19.11. -----------------------------------------------------------------------------------

def protected(name):
    """Never removed by the order: the owner and the server's default admins, the tool's accounts, the viewer."""
    from league import members, roles
    low = (name or "").strip().lower()
    if not low:
        return True
    try:
        from trade import settings as ts
        if ts.is_owner(name):
            return True
    except Exception:  # noqa: BLE001 - league/ without trade/: the locked admins below still hold the owner
        pass
    if low in roles.locked_admins() or low == (os.environ.get("TRADE_OWNER") or "Jure").strip().lower():
        return True
    if members.reserved(name):
        return True
    return low == (os.environ.get("UI_TEST_USER", "Claude") or "").strip().lower()


def users(con):
    """Every user the order looks at (env players and invite members still in), each once."""
    from league import members
    out, have = [], set()
    for n in store.env_users() + members.names(con):
        if n.lower() not in have and not is_out(n):
            have.add(n.lower())
            out.append(n)
    return out


def done(con=None):
    """The stored result of the order ({ts, izbaceni, ostaje, start}) or None while it has not run."""
    own = con is None
    try:
        con = con or store.connect()
        ensure(con)
        r = con.execute("SELECT v FROM izbaceni_nalog WHERE key=?", (ORDER_KEY,)).fetchone()
        return json.loads(r[0]) if r else None
    except (sqlite3.Error, ValueError):
        return None
    finally:
        if own and con is not None:
            con.close()


def due_at(con=None):
    from league import posjeti
    s = posjeti.started_at(con)
    return s + WINDOW if s else None


def run_order(now=None):
    """(result, fresh): the order's result; fresh = it ran in this call. (None, False) while it is not due yet (no
    5 days of recorded visits). Runs once: after it ran, later calls only return the stored result."""
    from league import posjeti
    now = int(now or time.time())
    con = connect()
    try:
        old = done(con)
        if old:
            return old, False
        start = posjeti.started_at(con)
        if not start or now < start + WINDOW:
            return None, False
        seen = posjeti.visits(con)
        cut = now - WINDOW
        out, stay = [], []
        for n in users(con):
            last = (seen.get(n.lower()) or {}).get("last_ts")
            if protected(n) or (last and last >= cut):
                stay.append(n)
                continue
            remove(con, n, WHY, BY, now)
            out.append(n)
            when = (datetime.datetime.fromtimestamp(last, posjeti.TZ).strftime("%d.%m. %H:%M") if last
                    else "nikad zabilježen")
            print(f"korisnici: izbačen {n} (zadnji posjet: {when}; nalog vlasnika 19.11.)", flush=True)
        res = {"ts": now, "izbaceni": out, "ostaje": len(stay), "start": start}
        con.execute("INSERT OR REPLACE INTO izbaceni_nalog (key, ts, v) VALUES (?,?,?)",
                    (ORDER_KEY, now, json.dumps(res, ensure_ascii=False)))
        con.commit()
        print(f"korisnici: izbačeno {len(out)} neaktivnih (nalog vlasnika 19.11., bez posjeta 5 dana): "
              f"{', '.join(out) or 'nitko'}; ostaje {len(stay)}", flush=True)
        return res, True
    finally:
        con.close()
