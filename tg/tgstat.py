"""TGStat Search API (paid, token in TGSTAT_TOKEN): every indexed Telegram channel that posted a given CA.

This is what the free web preview cannot do: find channels we do not know yet, and see who posted a token first.
Used on the strongest tokens of the moment (KOL group calls and convergences); capped per day in tg/config.json.
Endpoint: https://api.tgstat.ru/posts/search (q = the CA). Fields are read defensively.
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

from tg import reader, store

URL = "https://api.tgstat.ru/posts/search"
_LINK = re.compile(r"t\.me/([A-Za-z][A-Za-z0-9_]{4,31})/(\d+)")


def enabled():
    return bool(os.environ.get("TGSTAT_TOKEN"))


def search(ca, limit=50, timeout=30):
    q = urllib.parse.urlencode({"token": os.environ["TGSTAT_TOKEN"], "q": ca, "limit": limit, "extended": 1})
    with urllib.request.urlopen(f"{URL}?{q}", timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def parse(resp, ca):
    """[(channel, post, ts, text, views)] and {channel: subs} from a search response."""
    body = (resp or {}).get("response") or {}
    chans = {}
    for c in body.get("channels") or []:
        name = reader.channel_name((c.get("username") or c.get("link") or "").replace("t.me/", "").lstrip("@"))
        if name:
            chans[c.get("id")] = (name, int(c.get("participants_count") or 0))
    posts = []
    for it in body.get("items") or []:
        m = _LINK.search(it.get("link") or "")
        name = reader.channel_name(m.group(1)) if m else (chans.get(it.get("channel_id")) or (None,))[0]
        if not name:
            continue
        post = int(m.group(2)) if m else int(it.get("id") or 0)
        posts.append((name, post, int(it.get("date") or 0), (it.get("text") or "")[:600], int(it.get("views") or 0)))
    return posts, {n: s for n, s in chans.values()}


def run(con, tokens, cfg, now=None, search_fn=None, hype_db=None):
    """Search the given CAs (strongest first) within the daily cap. Returns (requests, new candidates, posts)."""
    if not enabled() and search_fn is None:
        return 0, 0, 0
    now = now or int(time.time())
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    used = store.kv_get(con, "tgstat_used", {})
    done = store.kv_get(con, "tgstat_done", {})
    reqs = cand = n_posts = 0
    for ca in tokens:
        if used.get(day, 0) >= cfg["daily_requests"] or reqs >= cfg["tokens_per_run"]:
            break
        if ca in done:
            continue
        try:
            resp = (search_fn or search)(ca)
        except Exception as e:
            print(f"tgstat {ca}: {type(e).__name__}: {e}")
            break
        reqs += 1
        used[day] = used.get(day, 0) + 1
        done[ca] = now
        posts, subs = parse(resp, ca)
        cand += store.add_candidates(con, {p[0] for p in posts}, "tgstat", now)
        for name, post, ts, text, views in posts:
            con.execute("INSERT OR IGNORE INTO posts VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (name, post, ts, now, text, ca, "", views, None, "tgstat"))
            store.mention(name, [{"post": post, "ts": ts, "cas": [ca], "tickers": []}], hype_db)
            n_posts += 1
        for name, s in subs.items():
            con.execute("UPDATE channels SET subs=COALESCE(subs, ?) WHERE name=?", (s or None, name))
    store.kv_set(con, "tgstat_used", {d: n for d, n in used.items() if d >= time.strftime("%Y-%m-%d", time.gmtime(now - 40 * 86400))})
    store.kv_set(con, "tgstat_done", {k: v for k, v in done.items() if v >= now - 7 * 86400})
    con.commit()
    return reqs, cand, n_posts
