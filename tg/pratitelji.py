"""Telegram kanali: samo broj pratitelja, jednom tjedno (19.11.2026., vlasnik: "Makni Telegram KOL-ove iz izračuna. Ali
zadrži popis kanala, osvježen jednom tjedno, samo za broj pratitelja. Neka to bude samo informativni popis.").

What it does: for every channel on the existing list (tg.db channels with status active / quiet / slow: LIST_STATUS;
no discovery, no new channel is ever added here) it reads the subscriber count from the channel's public web preview
(https://t.me/s/<channel>, free, the page the reader always used; tg/reader.parse) and stores ONE row per channel per
week in tg.db tg_pratitelji (kanal, ts, pratitelji). Nothing else of the page is read or stored: no post, no text, no
call, no history; TGStat, Telethon and every paid source are gone with the old reader (19.11.).

Cadence: TG_FOLLOWERS_EVERY_D (7) days per channel. A channel is due when its newest row is older than that, so the
job may be started daily (start.sh) and a pass cut short goes on the next day, but no channel is ever read twice in a
week. Pace: GAP_S between pages, at most MAX_PER_PASS pages a pass, low priority (start.sh "low").

    python3 run_tg.py pratitelji           one pass now (only the due channels)
    python3 run_tg.py status               the list, counts and the last pass

Readers: ui/tgkanali.py (/telegram-kanali in the app), ui/telegrampub.py (the public /telegram-channels pages).
"""
import os
import time

from tg import reader, store

EVERY_D = float(os.environ.get("TG_FOLLOWERS_EVERY_D") or 7)
LIST_STATUS = ("active", "quiet", "slow")
LIST_SQL = "status IN ('active', 'quiet', 'slow')"   # = LIST_STATUS (stanja/registar.py reads the literals here)
GAP_S = 1.5
MAX_PER_PASS = 400

SCHEMA = """
CREATE TABLE IF NOT EXISTS tg_pratitelji (kanal TEXT, ts INTEGER, pratitelji INTEGER, PRIMARY KEY (kanal, ts));
CREATE INDEX IF NOT EXISTS tg_pratitelji_ts ON tg_pratitelji (ts);
"""


def ensure(con):
    con.executescript(SCHEMA)


def kanali(con):
    """[name] of the existing list (no discovery: the list is what it was on 19.11.)."""
    return [n for (n,) in con.execute(f"SELECT name FROM channels WHERE {LIST_SQL} ORDER BY name")]


def due(con, now=None, every_d=None):
    """[name] whose newest follower row is older than every_d days (or that have none)."""
    now = int(now or time.time())
    cut = now - int(float(every_d if every_d is not None else EVERY_D) * 86400)
    ensure(con)
    last = dict(con.execute("SELECT kanal, MAX(ts) FROM tg_pratitelji GROUP BY kanal"))
    return [n for n in kanali(con) if (last.get(n) or 0) <= cut]


def subs_of(page):
    """(subscribers, title) from a t.me/s page: only the channel header is used, never the posts."""
    info = reader.parse_header(page)
    return info["subs"], info["title"]


def run(con=None, now=None, fetch=None, sleep=time.sleep, log=print, every_d=None, limit=MAX_PER_PASS):
    """One pass over the due channels. -> {"due", "read", "rows", "fails"}."""
    own = con is None
    con = con or store.connect()
    fetch = fetch or reader.fetch
    try:
        ensure(con)
        now = int(now or time.time())
        todo = due(con, now, every_d)
        out = {"due": len(todo), "read": 0, "rows": 0, "fails": 0}
        for i, name in enumerate(todo[:limit]):
            if i:
                sleep(GAP_S)
            try:
                subs, title = subs_of(fetch(name))
            except Exception as e:  # noqa: BLE001 - one channel never stops the pass
                out["fails"] += 1
                log(f"tg pratitelji: {name} nije pročitan ({type(e).__name__})")
                continue
            out["read"] += 1
            if not subs:
                out["fails"] += 1
                continue
            con.execute("INSERT OR IGNORE INTO tg_pratitelji VALUES (?,?,?)", (name, now, int(subs)))
            con.execute("UPDATE channels SET subs = ?, title = COALESCE(?, title), checked_ts = ? WHERE name = ?",
                        (int(subs), title, now, name))
            con.commit()
            out["rows"] += 1
        store.kv_set(con, "pratitelji_zadnji", {"ts": now, **out})
        con.commit()
        log(f"tg pratitelji: {out['rows']} kanala osvježeno (na redu {out['due']}, nije uspjelo {out['fails']}); "
            f"sljedeće za {EVERY_D:g} dana")
        return out
    finally:
        if own:
            con.close()


def _at(series, ts):
    """The value of the newest row at or before ts in [(ts, n)] (oldest first), else None."""
    v = None
    for t, n in series:
        if t <= ts:
            v = n
        else:
            break
    return v


def pregled(path=None, now=None):
    """[{kanal, naslov, pratitelji, d7, d30, ts}] of the list, most followers first; [] without tg.db.
    d7 / d30: the change against the newest row at least 7 / 30 days before the newest one (None until there is one).
    A channel without any weekly row yet shows the count tg.db already had (channels.subs, ts = checked_ts)."""
    con = store.ro(path)
    if con is None:
        return []
    try:
        try:
            chans = con.execute(f"SELECT name, title, subs, checked_ts FROM channels WHERE {LIST_SQL}").fetchall()
        except Exception:  # noqa: BLE001 - an old or empty file
            return []
        rows = {}
        try:
            for k, ts, n in con.execute("SELECT kanal, ts, pratitelji FROM tg_pratitelji ORDER BY kanal, ts"):
                rows.setdefault(k, []).append((int(ts), int(n)))
        except Exception:  # noqa: BLE001 - the table comes with the first weekly pass
            rows = {}
    finally:
        con.close()
    out = []
    for name, title, subs, checked in chans:
        s = rows.get(name) or []
        if s:
            ts, n = s[-1]
            p7, p30 = _at(s, ts - 7 * 86400 + 3600), _at(s, ts - 30 * 86400 + 3600)
            d7 = n - p7 if p7 is not None else None
            d30 = n - p30 if p30 is not None else None
        else:
            ts, n, d7, d30 = checked, subs, None, None
        out.append({"kanal": name, "naslov": title, "pratitelji": n, "d7": d7, "d30": d30, "ts": ts})
    out.sort(key=lambda r: (-(r["pratitelji"] or 0), r["kanal"]))
    return out


def zadnji(path=None):
    """The last pass's kv record, or None."""
    con = store.ro(path)
    if con is None:
        return None
    try:
        return store.kv_get(con, "pratitelji_zadnji")
    except Exception:  # noqa: BLE001
        return None
    finally:
        con.close()
