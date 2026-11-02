"""twitterapi.io: cheap reads of KOL timelines when TWITTERAPI_IO_KEY is set (else kol/collect.timeline uses Apify).

Advanced search GET https://api.twitterapi.io/twitter/tweet/advanced_search?query=...&queryType=Latest&cursor=...
(header X-API-Key). Up to ~20 posts per page; we page until posts are older than the last round. Price (1.11.2026):
$0.15 per 1,000 posts returned, at least $0.00015 per request. Unlike the Apify actor there is no 50-post minimum
per query, so reading 400 accounts every 30 min costs about what their new posts cost.

Spend is estimated per request and kept per UTC day in kol.db kv 'twapi:<day>'; at timeline_twapi.daily_usd the
round stops (the rest waits for the next day). Every request is also metered in usage.db (service 'twitterapi')."""
import json
import os
import time
import urllib.parse
import urllib.request

URL = "https://api.twitterapi.io/twitter/tweet/advanced_search"
PER_TWEET = 0.00015
MIN_REQ = 0.00015


def key():
    return os.environ.get("TWITTERAPI_IO_KEY") or None


def _get(query, cursor, timeout=30):
    q = urllib.parse.urlencode({"query": query, "queryType": "Latest", "cursor": cursor or ""})
    req = urllib.request.Request(f"{URL}?{q}", headers={"X-API-Key": key(), "User-Agent": "memesonar/1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def cost(n_tweets):
    return max(MIN_REQ, n_tweets * PER_TWEET)


def _day(now):
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def spent(con, now=None):
    row = con.execute("SELECT value FROM kv WHERE key = ?", (f"twapi:{_day(now or time.time())}",)).fetchone()
    return float(row[0]) if row else 0.0


def _add(con, usd, now):
    k = f"twapi:{_day(now)}"
    con.execute("INSERT INTO kv VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = CAST(value AS REAL) + ?",
                (k, str(usd), usd))
    try:
        from usage import meter
        meter.record("twitterapi", "kol_timeline", usd)
    except ImportError:
        pass


def search(con, query, since_ts, budget, get=None, max_pages=5, now=None, until_ts=None):
    """Posts matching query newer than since_ts (and older than until_ts), newest first, as dicts calls_from_tweet
    understands. Stops at budget (USD spent today), at a post older than since_ts, or after max_pages."""
    get = get or _get
    now = now or time.time()
    q = f"{query} since_time:{int(since_ts)}" + (f" until_time:{int(until_ts)}" if until_ts else "")
    out, cursor = [], ""
    for _ in range(max_pages):
        if spent(con, now) >= budget:
            break
        d = get(q, cursor)
        tweets = d.get("tweets") or []
        _add(con, cost(len(tweets)), now)
        from kol.collect import tweet_ts
        old = False
        for t in tweets:
            if (tweet_ts(t.get("createdAt")) or now) < since_ts:
                old = True
            else:
                out.append(t)
        cursor = d.get("next_cursor")
        if old or not d.get("has_next_page") or not cursor:
            break
    return out


USER_URL = "https://api.twitterapi.io/twitter/user/info"
TWEETS_URL = "https://api.twitterapi.io/twitter/tweets"
PER_USER = 0.00018


def _get_url(url, params, timeout=30):
    req = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}",
                                 headers={"X-API-Key": key(), "User-Agent": "memesonar/1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def user_info(con, handle, get=None, now=None):
    """Profile of one X account (bio, createdAt, followers, pinnedTweetIds, unavailable...) or None."""
    get = get or _get_url
    d = get(USER_URL, {"userName": handle})
    _add(con, PER_USER, now or time.time())
    return d.get("data") if d.get("status") == "success" else None


def tweets(con, ids, get=None, now=None):
    """Posts by id (the pinned post), as twitterapi.io returns them."""
    if not ids:
        return []
    get = get or _get_url
    d = get(TWEETS_URL, {"tweet_ids": ",".join(str(i) for i in ids)})
    out = d.get("tweets") or []
    _add(con, cost(len(out)), now or time.time())
    return out
