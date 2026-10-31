"""Calls from X: every tweet the bot already paid for (hype.db apify_cache), webhook mentions, and two small
searches of our own (follow-up on tokens that KOLs are calling, latest tweets of the best KOLs).

A call is one (tweet, token) pair. The token is any Solana CA in the tweet text; a token search also counts a
tweet that only writes the $TICKER, as match "ticker", when the tweet names no other CA.
"""
import datetime as dt
import json
import os
import re
import sqlite3
import time

from hype.telegram import _CA, _TICKER

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HYPE_DB = os.environ.get("HYPE_DB", os.path.join(ROOT, "hype.db"))
X_ACTOR = "apidojo/tweet-scraper"
CACHE_PREFIXES = ("x_buzz:", "kol_search:", "kol_timeline:")

# "15X on $ICOIN", "78.6x on my tg", "did a 20x", "115x $ICOIN" (post opens with the multiple): bragging about a
# past pump, not a call. "next 100x" inside a sentence stays a call.
_BRAG = re.compile(r"\b\d+(?:[.,]\d+)?\s?x\s+(?:on|from|up|in|with|done|already|secured|profit|gain|since)\b"
                   r"|\b(?:did|hit|printed|secured|called|up|done|made)\s+(?:a\s+|an\s+)?\d+(?:[.,]\d+)?\s?x\b"
                   r"|^\W*\d+(?:[.,]\d+)?\s?x\b", re.I)


def _int(x):
    try:
        return int(float(str(x).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def tweet_ts(s):
    """'Fri Oct 30 21:58:58 +0000 2026' or ISO -> unix seconds; None if unknown."""
    if not s:
        return None
    if isinstance(s, (int, float)):
        return int(s / 1000 if s > 1e12 else s)
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return int(dt.datetime.strptime(s.replace("Z", "+0000"), fmt).timestamp())
        except ValueError:
            pass
    return None


def cas_in(text):
    return sorted({c for c in _CA.findall(text or "") if any(ch.isdigit() for ch in c)})


def kind_of(text):
    return "brag" if _BRAG.search(text or "") else "call"


def calls_from_tweet(t, target=None, symbol=None, source="x_buzz"):
    """List of call dicts for one scraped tweet. Retweets are skipped (the original author made the call)."""
    if not isinstance(t, dict) or t.get("noResults") or t.get("isRetweet"):
        return []
    a = t.get("author") or t.get("user") or {}
    handle = a.get("userName") or a.get("screen_name") or a.get("username")
    ts = tweet_ts(t.get("createdAt"))
    tid = str(t.get("id") or "")
    if not handle or not ts or not tid:
        return []
    text = t.get("fullText") or t.get("text") or ""
    found = cas_in(text)
    pairs = [(c, "ca") for c in found]
    if target and target not in found and not found and symbol:
        tickers = {x.upper() for x in _TICKER.findall(text)}
        if symbol.upper() in tickers:
            pairs.append((target, "ticker"))
    base = {"tweet_id": tid, "handle": handle, "ts": ts,
            "url": t.get("url") or f"https://x.com/{handle}/status/{tid}", "text": text[:600],
            "followers": _int(a.get("followers") or a.get("followersCount") or a.get("followers_count")),
            "likes": _int(t.get("likeCount")), "retweets": _int(t.get("retweetCount")), "views": _int(t.get("viewCount")),
            "kind": kind_of(text), "source": source, "symbol": symbol if target else None,
            "author": {"name": a.get("name"), "verified": bool(a.get("isBlueVerified") or a.get("isVerified"))}}
    return [dict(base, token=c, match=m, symbol=(symbol if c == target else None)) for c, m in pairs]


def save(con, calls):
    n = 0
    for c in calls:
        n += con.execute("""INSERT OR IGNORE INTO calls (tweet_id, token, handle, ts, url, text, followers, likes, retweets,
            views, kind, match, source, symbol) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (c["tweet_id"], c["token"], c["handle"], c["ts"], c["url"], c["text"], c["followers"],
                          c["likes"], c["retweets"], c["views"], c["kind"], c["match"], c["source"],
                          c["symbol"])).rowcount
        au = c.get("author") or {}
        con.execute("""INSERT INTO kols (handle, name, followers, verified, first_seen, last_seen) VALUES (?,?,?,?,?,?)
            ON CONFLICT (handle) DO UPDATE SET
              name=COALESCE(excluded.name, name),
              followers=CASE WHEN excluded.last_seen >= last_seen OR followers IS NULL OR followers = 0
                             THEN COALESCE(NULLIF(excluded.followers, 0), followers) ELSE followers END,
              verified=MAX(COALESCE(verified, 0), excluded.verified),
              first_seen=MIN(first_seen, excluded.first_seen), last_seen=MAX(last_seen, excluded.last_seen)""",
                    (c["handle"], au.get("name"), c["followers"] or None, int(au.get("verified") or 0), c["ts"], c["ts"]))
    return n


def _target(key):
    """(ca, symbol) a cached token search was for, or (None, None) for a timeline search."""
    try:
        inp = json.loads(key.split(":", 2)[2])
    except (IndexError, ValueError):
        return None, None
    terms = inp.get("searchTerms") or []
    ca = next((s for s in terms if _CA.fullmatch(s or "")), None)
    sym = next((s[1:] for s in terms if (s or "").startswith("$")), None)
    return ca, sym


def from_hype_cache(con, hype_db=None):
    """Copy calls out of every X search the bot cached in hype.db. The cache row is replaced on the next identical
    search, so this has to run often; seen_cache remembers (key, ts) already copied."""
    path = hype_db or HYPE_DB
    if not os.path.exists(path):
        return 0
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    try:
        where = " OR ".join("key LIKE ?" for _ in CACHE_PREFIXES)
        rows = src.execute(f"SELECT key, ts, items FROM apify_cache WHERE {where}",
                           [p + "%" for p in CACHE_PREFIXES]).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        src.close()
    seen = dict(con.execute("SELECT key, ts FROM seen_cache"))
    n = 0
    for key, ts, items in rows:
        if seen.get(key) == ts:
            continue
        ca, sym = _target(key)
        source = key.split(":", 1)[0]
        try:
            tweets = json.loads(items)
        except ValueError:
            tweets = []
        for t in tweets:
            n += save(con, calls_from_tweet(t, ca, sym, source))
        con.execute("INSERT OR REPLACE INTO seen_cache VALUES (?,?)", (key, ts))
    return n


def from_webhook(con, hype_db=None):
    """kol_mentions rows written by the xquik monitor webhook (no link, no followers in that payload)."""
    path = hype_db or HYPE_DB
    if not os.path.exists(path):
        return 0
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    try:
        rows = src.execute("SELECT ts, handle, ca, text FROM kol_mentions WHERE ca != '' AND handle != ''").fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        src.close()
    n = 0
    for ts, handle, ca, text in rows:
        tid = f"hook-{handle}-{ts}"
        n += save(con, [{"tweet_id": tid, "token": ca, "handle": handle, "ts": ts, "url": f"https://x.com/{handle}",
                         "text": (text or "")[:600], "followers": 0, "likes": 0, "retweets": 0, "views": 0,
                         "kind": kind_of(text), "match": "ca", "source": "webhook", "symbol": None}])
    return n


# ---------------- paid searches (Apify, budgeted per source in hype/apify.json) ----------------

def _searched(con, target, kind, now):
    con.execute("INSERT INTO searches VALUES (?,?,?,1) ON CONFLICT (target) DO UPDATE SET last_ts=excluded.last_ts, "
                "n=n+1", (target, kind, now))


def followup_targets(con, cfg, now=None):
    """Tokens a KOL called 1-24 h ago that we have not searched for a while: catches who joined the call later."""
    now = now or int(time.time())
    f = cfg["followup"]
    rows = con.execute("""
        SELECT c.token, MAX(c.symbol), COUNT(DISTINCT c.handle) AS n, MAX(COALESCE(k.score, 0)) AS best
        FROM calls c LEFT JOIN kols k ON k.handle = c.handle
        WHERE c.kind = 'call' AND c.ts BETWEEN ? AND ?
        GROUP BY c.token ORDER BY n DESC, best DESC""",
                       (now - f["max_age_h"] * 3600, now - f["after_h"] * 3600)).fetchall()
    last = dict(con.execute("SELECT target, last_ts FROM searches WHERE kind = 'followup'"))
    return [(t, s) for t, s, n, best in rows if now - (last.get(t) or 0) >= f["again_h"] * 3600]


def followup(con, cfg, run=None):
    """Search the CA (and $TICKER) of the top follow-up targets. Returns new calls."""
    from hype import apify
    run = run or apify.run
    f = cfg["followup"]
    n, now = 0, int(time.time())
    for token, sym in followup_targets(con, cfg)[:f["per_run"]]:
        terms = [token] + ([f"${sym}"] if sym and len(sym) >= 3 else [])
        items = run("kol_search", X_ACTOR, {"searchTerms": terms, "maxItems": f["max_items"], "sort": "Latest"})
        _searched(con, token, "followup", now)
        n += save(con, [c for t in items for c in calls_from_tweet(t, token, sym, "kol_search")])
    return n


def timeline_handles(con, cfg):
    t = cfg["timeline"]
    rows = con.execute("""
        SELECT k.handle FROM kols k JOIN calls c ON c.handle = k.handle AND c.kind = 'call'
        GROUP BY k.handle HAVING COUNT(DISTINCT c.token) >= ?
        ORDER BY COALESCE(k.score, 0) DESC, COALESCE(k.followers, 0) DESC LIMIT ?""",
                       (t["min_calls"], t["kols"])).fetchall()
    return [r[0] for r in rows]


def timeline(con, cfg, run=None, now=None):
    """Latest tweets of the best KOLs in one query (every timeline.every_h hours): their new calls on any token,
    also tokens our scanner has not seen yet."""
    from hype import apify
    run = run or apify.run
    now = now or int(time.time())
    t = cfg["timeline"]
    last = con.execute("SELECT last_ts FROM searches WHERE target = 'timeline'").fetchone()
    if last and now - last[0] < t["every_h"] * 3600:
        return 0
    handles = timeline_handles(con, cfg)
    if not handles:
        return 0
    query = " OR ".join(f"from:{h}" for h in handles)
    items = run("kol_timeline", X_ACTOR, {"searchTerms": [query], "maxItems": t["max_items"], "sort": "Latest"})
    _searched(con, "timeline", "timeline", now)
    return save(con, [c for it in items for c in calls_from_tweet(it, source="kol_timeline")])
