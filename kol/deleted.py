"""5.11.: does a KOL delete the posts of his losing calls? A call stays in kol.db once read (nothing removes it on a
re-read), but a backfill or a later timeline read only sees what survived, and an account that deletes every rug
looks better than it is. So measured calls are re-checked by tweet id (twitterapi.io, $0.15 per 1000) a couple of
days after the call: gone = deleted_ts. Deleted calls keep counting in every stat; on top, kol/score punishes a KOL
whose deleted posts are mostly losers (weight "deletes").
"""
import time

DEFAULT = {"per_round": 200, "min_age_d": 2, "recheck_d": 14, "batch": 100}
DAY = 86400


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
