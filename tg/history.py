"""Older posts of a channel: t.me/s/<channel>?before=<post id> pages back in time (free, ~20 posts a page).

tg/poll.visit only ever stores posts newer than the channel's last one, so a channel added today starts with its
20 latest posts. backfill() walks back once per channel (kv 'hist:<channel>' remembers how far it got), stores
older CA posts with seen_ts = now so kol/collect.from_telegram copies them into kol.db as calls, and
kol/measure.py prices them from GeckoTerminal history like any other call.
"""
import time
import urllib.request

from event_calendar.http import USER_AGENT
from tg import reader, store


def fetch_before(channel, before, timeout=20):
    req = urllib.request.Request(f"https://t.me/s/{channel}?before={int(before)}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def save_old(con, channel, posts, now=None, hype_db=None):
    """Store posts regardless of the channel's last post (INSERT OR IGNORE). Returns the new CA posts."""
    now = now or int(time.time())
    new = []
    for p in posts:
        keep = bool(p["cas"] or p["tickers"])
        n = con.execute("INSERT OR IGNORE INTO posts VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (channel, p["post"], p["ts"], now, p["text"] if keep else None, ",".join(p["cas"]),
                         ",".join(p["tickers"]), p.get("views") or 0, p.get("fwd_from"), "history")).rowcount
        if n and p["cas"]:
            new.append(p)
    if new:
        con.execute("UPDATE channels SET n_ca = n_ca + ? WHERE name = ?", (len(new), channel))
        store.mention(channel, new, hype_db)
    return new


def backfill(con, channel, max_pages=25, since_ts=0, fetch=fetch_before, sleep=time.sleep, gap_s=1.5, now=None,
             hype_db=None):
    """Walk back from the oldest post we know. Stops at post 1, an empty page, posts older than since_ts or
    max_pages. Returns (pages read, new CA posts, done)."""
    st = store.kv_get(con, f"hist:{channel}", {}) or {}
    if st.get("done"):
        return 0, 0, True
    before = st.get("before") or (con.execute("SELECT MIN(post) FROM posts WHERE channel = ?", (channel,))
                                  .fetchone() or (None,))[0]
    if not before:
        return 0, 0, False   # channel never read yet: poll.visit fills the newest page first
    pages = n_new = 0
    done = False
    while pages < max_pages:
        if before <= 1:
            done = True
            break
        if pages:
            sleep(gap_s)
        info = reader.parse(fetch(channel, before), channel)
        pages += 1
        posts = [p for p in info["posts"] if p["post"] < before]
        if not posts:
            # deleted posts leave gaps in the ids and t.me then shows an empty page: jump further back a few times
            # before deciding the channel has no older posts
            gaps = st.get("gaps", 0) + 1
            st["gaps"] = gaps
            if gaps > 6 or before <= 200:
                done = True
                break
            before = max(1, before - 50 * 4 ** (gaps - 1))
            continue
        st["gaps"] = 0
        n_new += len(save_old(con, channel, posts, now, hype_db))
        before = min(p["post"] for p in posts)
        if min((p["ts"] or 0) for p in posts) < since_ts:
            done = True
            break
    store.kv_set(con, f"hist:{channel}", {"before": before, "done": done, "pages": (st.get("pages") or 0) + pages,
                                          "gaps": st.get("gaps", 0)})
    con.commit()
    return pages, n_new, done
