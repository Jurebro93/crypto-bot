"""X (Twitter) buzz through an Apify actor, only for the best candidates because every tweet costs money.

Needs APIFY_TOKEN. Default actor apidojo/tweet-scraper (~$0.40 per 1000 tweets); override with APIFY_X_ACTOR.
Searching by contract address finds real shills; the $TICKER alone matches unrelated tweets.
"""
import json
import math
import os
import time
import urllib.request

ACTOR = os.environ.get("APIFY_X_ACTOR", "apidojo~tweet-scraper")
CACHE_SECS = int(os.environ.get("XBUZZ_CACHE_SECS", "900"))
_cache = {}


def enabled():
    return bool(os.environ.get("APIFY_TOKEN"))


def search(terms, max_items=40, timeout=120):
    url = (f"https://api.apify.com/v2/acts/{ACTOR}/run-sync-get-dataset-items"
           f"?token={os.environ['APIFY_TOKEN']}&timeout={timeout}")
    body = json.dumps({"searchTerms": terms, "maxItems": max_items, "sort": "Latest"}).encode()
    req = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout + 30) as r:
        return json.load(r)


def _followers(t):
    a = t.get("author") or t.get("user") or {}
    return a.get("followers") or a.get("followersCount") or a.get("followers_count") or 0


def _handle(t):
    a = t.get("author") or t.get("user") or {}
    return a.get("userName") or a.get("screen_name") or a.get("username") or a.get("id")


def buzz(tweets, influencer_followers=10000):
    """Mentions, distinct authors, influencers (>= 10k followers) and engagement from a list of tweets."""
    authors = {_handle(t) for t in tweets}
    infl = sorted({(_handle(t), _followers(t)) for t in tweets if _followers(t) >= influencer_followers},
                  key=lambda x: -x[1])
    eng = sum((t.get("likeCount") or 0) + 2 * (t.get("retweetCount") or 0) + (t.get("replyCount") or 0) for t in tweets)
    return {"tweets": len(tweets), "authors": len(authors), "influencers": infl[:5], "engagement": eng,
            # 0..1: many different accounts, at least one big account, real engagement
            "feature": min(1.0, len(authors) / 20 * 0.4 + min(len(infl), 3) / 3 * 0.4
                       + math.log10(1 + eng) / 4 * 0.2)}


def token_buzz(ca, symbol=None, max_items=40):
    hit = _cache.get(ca)
    if hit and time.time() - hit[0] < CACHE_SECS:
        return hit[1]
    terms = [ca] + ([f"${symbol}"] if symbol and len(symbol) >= 3 else [])
    tweets = [t for t in search(terms, max_items) if not t.get("noResults")]
    res = buzz(tweets)
    _cache[ca] = (time.time(), res)
    return res
