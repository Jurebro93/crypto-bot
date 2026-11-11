"""5.11.: does a KOL delete the posts of his losing calls? A call stays in kol.db once read (nothing removes it on a
re-read), but a backfill or a later timeline read only sees what survived, and an account that deletes every rug
looks better than it is. So measured calls are re-checked by tweet id (twitterapi.io, $0.15 per 1000) a couple of
days after the call: gone = deleted_ts. Deleted calls keep counting in every stat; on top, kol/score punishes a KOL
whose deleted posts are mostly losers (weight "deletes").
11.11. (Jure: "Marko ima naviku objaviti X post pa ga za sekundu izbrisati ... to ne treba ući u statistiku Marka jer je
post stajao samo jako kratko na X-u"): a fresh X call is checked again ~1 and ~5 minutes after it was posted
(flash_check, every 30 s in a side thread of the minute loop); gone by then = kind 'flash': no stat, score, weight, signal or
first-call rule counts it any more (they all read kind 'call'), the row stays for the record. A post deleted later is
the old case above (it keeps counting, and deleting losers is punished).
"""
import json
import os
import time

DEFAULT = {"per_round": 200, "min_age_d": 2, "recheck_d": 14, "batch": 100}
DAY = 86400
# first check >= first_s after the post, second >= second_s; a call older than max_s is no longer checked quickly
# (a post deleted later keeps counting, as before).
# twitterapi.io bills returned posts only ($0.15 / 1000): ~2 lookups per live call, day_cap lookups a day at most.
FLASH = {"first_s": 45, "second_s": 300, "max_s": 420, "batch": 100, "day_cap": 3000, "every_s": 30}
FLASH_KIND = "flash"
# 11.11. (Jure, in the chat): @0xMarko77's post of 10.11. 22:35:20 CET (29JjbX5p...pump) was up for about a second
OWNER_FLASH = (("2120269096952770895", "vlasnik 11.11.: Markov post stajao je na X-u samo sekundu"),)


def config(cfg):
    return {**DEFAULT, **((cfg or {}).get("deleted") or {})}


def due(con, cfg, now=None):
    """[tweet_id] of measured X calls old enough to have been deleted, never checked or checked long ago."""
    c = config(cfg)
    now = now or int(time.time())
    rows = con.execute("""SELECT DISTINCT tweet_id FROM calls
                          WHERE kind = 'call' AND deleted_ts IS NULL AND complete = 1 AND ts <= ?
                            AND tweet_id GLOB '[0-9]*' AND handle NOT LIKE 'tg:%' AND handle NOT LIKE 'w:%'
                            AND (checked_ts IS NULL OR checked_ts < ?)
                          ORDER BY (checked_ts IS NOT NULL), ts DESC LIMIT ?""",
                       (now - c["min_age_d"] * DAY, now - c["recheck_d"] * DAY, c["per_round"])).fetchall()
    return [r[0] for r in rows]


def mark(con, ids, present, now=None):
    """present: ids the API returned. The rest of `ids` are gone -> deleted_ts. Returns the number deleted."""
    now = now or int(time.time())
    present = set(str(i) for i in present)
    gone = [i for i in ids if str(i) not in present]
    con.executemany("UPDATE calls SET checked_ts = ? WHERE tweet_id = ?", [(now, i) for i in ids])
    con.executemany("UPDATE calls SET deleted_ts = ? WHERE tweet_id = ? AND deleted_ts IS NULL", [(now, i) for i in gone])
    return len(gone)


def check(con, cfg, now=None, fetch=None, log=print):
    """One round: re-read due calls in batches. A batch whose answer is empty is treated as an API hiccup, not as
    'everything deleted'. Returns (checked, deleted)."""
    from kol import twapi
    if not twapi.key() and fetch is None:
        return 0, 0
    now = now or int(time.time())
    c = config(cfg)
    ids = due(con, cfg, now)
    fetch = fetch or (lambda batch: [str(t.get("id")) for t in twapi.tweets(con, batch, now=now)])
    checked = deleted = 0
    for i in range(0, len(ids), c["batch"]):
        batch = ids[i:i + c["batch"]]
        try:
            present = fetch(batch)
        except Exception as e:  # noqa: BLE001
            log(f"obrisane objave: {type(e).__name__}: {str(e)[:120]}")
            break
        if not present and len(batch) >= 5:
            log(f"obrisane objave: prazan odgovor za {len(batch)} objava, preskačem")
            continue
        deleted += mark(con, batch, present, now)
        checked += len(batch)
    con.commit()
    if checked:
        log(f"obrisane objave: provjereno {checked}, obrisano {deleted}")
    return checked, deleted


def summary(con, handle):
    """{deleted, deleted_losers, deleted_winners} for one KOL, for the page."""
    rows = con.execute("SELECT max24, rug FROM calls WHERE handle = ? AND deleted_ts IS NOT NULL AND kind = 'call'",
                       (handle,)).fetchall()
    losers = sum(1 for m, r in rows if r or (m is not None and m < 0))
    return {"deleted": len(rows), "deleted_losers": losers, "deleted_winners": len(rows) - losers}


def flash_config(cfg):
    return {**FLASH, **((cfg or {}).get("flash") or {})}


def flash_due(con, cfg, now):
    """[tweet_id] of fresh X calls due for a quick check (first after first_s, second after second_s)."""
    c = flash_config(cfg)
    rows = con.execute("""SELECT DISTINCT tweet_id FROM calls
                          WHERE kind = 'call' AND ts >= ? AND tweet_id GLOB '[0-9]*'
                            AND handle NOT LIKE 'tg:%' AND handle NOT LIKE 'w:%'
                            AND ((COALESCE(flash_n, 0) = 0 AND ts <= ?) OR (flash_n = 1 AND ts <= ?))
                          ORDER BY ts LIMIT ?""",
                       (now - c["max_s"], now - c["first_s"], now - c["second_s"], c["batch"] * 3)).fetchall()
    return [r[0] for r in rows]


def _day_used(con, now):
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    r = con.execute("SELECT value FROM kv WHERE key = 'flash_day'").fetchone()
    d = json.loads(r[0]) if r else {}
    return day, (d.get("n", 0) if d.get("day") == day else 0)


def mark_flash(con, tweet_id, now, why=""):
    """The post of `tweet_id` was up only briefly: kind 'flash' (out of every stat). Returns the rows changed."""
    n = con.execute("UPDATE calls SET kind = ?, deleted_ts = COALESCE(deleted_ts, ?), checked_ts = ? "
                    "WHERE tweet_id = ? AND kind = 'call'", (FLASH_KIND, now, now, str(tweet_id))).rowcount
    return n


def flash_check(con, cfg, now=None, fetch=None, log=print):
    """One quick pass over fresh X calls. Returns (checked, flashed)."""
    from kol import twapi
    if not twapi.key() and fetch is None:
        return 0, 0
    now = int(now or time.time())
    c = flash_config(cfg)
    ids = flash_due(con, cfg, now)
    day, used = _day_used(con, now)
    ids = ids[:max(0, c["day_cap"] - used)]
    if not ids:
        return 0, 0
    fetch = fetch or (lambda batch: [str(t.get("id")) for t in twapi.tweets(con, batch, now=now)])
    checked = flashed = 0
    for i in range(0, len(ids), c["batch"]):
        batch = ids[i:i + c["batch"]]
        try:
            present = {str(x) for x in fetch(batch)}
        except Exception as e:  # noqa: BLE001
            log(f"brzo obrisane: {type(e).__name__}: {str(e)[:120]}")
            break
        checked += len(batch)
        if not present and len(batch) >= 5:   # an empty answer for many posts is an API hiccup, not mass deletion
            log(f"brzo obrisane: prazan odgovor za {len(batch)} objava, preskačem")
            continue
        for tid in batch:
            if str(tid) in present:
                con.execute("UPDATE calls SET flash_n = COALESCE(flash_n, 0) + 1 WHERE tweet_id = ?", (tid,))
                continue
            rows = con.execute("SELECT handle, symbol, token, ts FROM calls WHERE tweet_id = ? AND kind = 'call'",
                               (tid,)).fetchall()
            if mark_flash(con, tid, now):
                flashed += 1
                h, sym, tok, ts = rows[0]
                log(f"brzo obrisane: @{h} {sym or tok[:6]} objava {tid} nestala unutar {now - ts} s, ne ulazi u "
                    f"statistiku")
    con.execute("INSERT OR REPLACE INTO kv VALUES ('flash_day', ?)", (json.dumps({"day": day, "n": used + checked}),))
    con.commit()
    return checked, flashed


def owner_flash(con, now=None, log=print):
    """The owner's own list (OWNER_FLASH), each once (kv flash_owner:<id>): logs what the bot had stored for the post,
    then takes it out of the stats. [text]."""
    now = int(now or time.time())
    out = []
    for tid, why in OWNER_FLASH:
        key = f"flash_owner:{tid}"
        if con.execute("SELECT 1 FROM kv WHERE key = ?", (key,)).fetchone():
            continue
        rows = con.execute("SELECT handle, token, symbol, ts, kind, source, mcap0, r1h, max24, first_by_kol, "
                           "first_overall FROM calls WHERE tweet_id = ?", (tid,)).fetchall()
        if not rows:
            out.append(f"objava {tid}: nije u bazi (bot je nije spremio kao poziv)")
        for h, tok, sym, ts, kind, src, mc0, r1h, mx, fbk, fo in rows:
            out.append(f"objava {tid}: @{h} {sym or ''} {tok} {time.strftime('%d.%m. %H:%M:%S', time.gmtime(ts + 3600))} CET, "
                       f"vrsta {kind}, izvor {src}, MC poziva {mc0 or 0:,.0f}, 1 h {r1h}, max 24 h {mx}, prvi njegov "
                       f"{fbk}, prvi uopće {fo}")
        n = mark_flash(con, tid, ts + 1 if rows else now, why) if rows else 0
        if n:
            out.append(f"objava {tid}: {n} redaka više ne ulazi u statistiku ({why})")
        con.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)", (key, json.dumps({"ts": now, "rows": n})))
    con.commit()
    for t in out:
        log(f"brzo obrisane: {t}")
    return out


def flash_round(cfg, log=print, now=None, fetch=None, path=None):
    """From the minute loop: a short write connection to kol.db (5 s busy wait; locked = skip this pass), the owner's
    list once, then one quick pass."""
    import sqlite3
    from kol import store
    p = path or store.DB
    if not os.path.exists(p):
        return 0, 0
    con = sqlite3.connect(p, timeout=5)
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(calls)")}
        if not cols:
            return 0, 0
        if "flash_n" not in cols:
            con.execute("ALTER TABLE calls ADD COLUMN flash_n INTEGER")
        con.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)")
        owner_flash(con, now, log)
        return flash_check(con, cfg, now, fetch, log)
    except sqlite3.OperationalError as e:
        if "locked" in str(e) or "busy" in str(e):
            return 0, 0
        raise
    finally:
        con.close()


_THREAD = {"t": None}


def start_flash_thread(cfg, log=print, sleep=time.sleep):
    """Run flash_round every FLASH every_s in a daemon thread (once per process)."""
    import threading
    if _THREAD["t"] is not None and _THREAD["t"].is_alive():
        return _THREAD["t"]
    every = flash_config(cfg)["every_s"]

    def run():
        while True:
            try:
                flash_round(cfg, log=lambda m, **k: log(m, flush=True) if log is print else log(m))
            except Exception as e:  # noqa: BLE001 - the thread never dies on one pass
                log(f"brzo obrisane: {type(e).__name__}: {str(e)[:160]}")
            sleep(every)
    t = threading.Thread(target=run, name="brzo-obrisane", daemon=True)
    t.start()
    _THREAD["t"] = t
    return t
