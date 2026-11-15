"""twitterapi.io for makroinf: the same endpoints and prices as kol/twapi.py (advanced search $0.15 per 1000 posts
returned, at least $0.00015 a request; user info $0.00018), but booked in makroinf.db (store.book, phase caps) and in
usage.db as twitterapi / makroinf, never in kol.db's day counter of the KOL scanner.

Every call first checks that its most possible cost fits what is left of the phase's cap (a search page: page_posts
posts; a lookup by id: the ids asked); None = the cap is reached (the caller stops cleanly). `get(url, params)` is the
test seam (tests pass a fake; nothing then reaches the network). The key is read from the environment by kol/twapi and
never logged."""
import time

from kol import twapi
from makroinf import store

USER_SEARCH_URL = "https://api.twitterapi.io/twitter/user/search"
PER_USER = twapi.PER_USER     # Pretpostavka for user search: billed like the profile, per user returned


class CapReached(Exception):
    """The phase's cap does not allow the next call."""


def has_key(get=None):
    return get is not None or bool(twapi.key())


def _get(get):
    return get or twapi._get_url


def _need(con, kind_usd, ph, c, now):
    left = store.left(con, "twapi", ph, now, c)
    if left + 1e-12 < kind_usd:
        raise CapReached(f"strop twitterapi ({ph}) dosegnut: ostalo {left:.4f} $")


def search_page(con, query, cursor, ph, c, now=None, get=None, what="pretraga"):
    """One page of advanced search (Latest): (tweets, next_cursor or None)."""
    now = now or time.time()
    _need(con, twapi.cost(int(c["page_posts"])), ph, c, now)
    d = _get(get)(twapi.URL, {"query": query, "queryType": "Latest", "cursor": cursor or ""}) or {}
    if d.get("status") == "error" or (d.get("error") and not d.get("tweets")):   # not billed, the unit stays to do
        raise RuntimeError(f"twitterapi: {str(d.get('msg') or d.get('message') or d.get('error'))[:120]}")
    tw = [t for t in (d.get("tweets") or []) if isinstance(t, dict)]
    store.book(con, "twitterapi", twapi.cost(len(tw)), ph, what, now)
    nxt = d.get("next_cursor") if d.get("has_next_page") else None
    return tw, (nxt or None)


def user(con, handle, ph, c, now=None, get=None):
    """Profile dict of one account, {"unavailable": True, ...} when X says so, or None (unknown / API error)."""
    now = now or time.time()
    _need(con, PER_USER, ph, c, now)
    d = _get(get)(twapi.USER_URL, {"userName": handle}) or {}
    store.book(con, "twitterapi", PER_USER, ph, "profil", now)
    if d.get("status") != "success":
        msg = str(d.get("msg") or d.get("message") or "")
        if "suspend" in msg.lower() or "not found" in msg.lower() or "not exist" in msg.lower():
            return {"unavailable": True, "unavailableReason": msg[:120]}
        return None
    return d.get("data") or None


def user_search(con, query, ph, c, now=None, get=None, limit=20):
    """Accounts matching `query` (twitterapi.io user search): [dict]."""
    now = now or time.time()
    _need(con, PER_USER * limit, ph, c, now)
    d = _get(get)(USER_SEARCH_URL, {"query": query}) or {}
    users = [u for u in (d.get("users") or d.get("data") or []) if isinstance(u, dict)][:limit]
    store.book(con, "twitterapi", max(PER_USER, PER_USER * len(users)), ph, "pretraga računa", now)
    return users


def by_ids(con, ids, ph, c, now=None, get=None):
    """Posts by id (missing ones are not returned): [tweet]."""
    now = now or time.time()
    if not ids:
        return []
    _need(con, twapi.cost(len(ids)), ph, c, now)
    d = _get(get)(twapi.TWEETS_URL, {"tweet_ids": ",".join(str(i) for i in ids)}) or {}
    out = [t for t in (d.get("tweets") or []) if isinstance(t, dict)]
    store.book(con, "twitterapi", twapi.cost(len(out)), ph, "provjera brisanja", now)
    return out


def followings(con, handle, ph, c, now=None, get=None, page=200):
    now = now or time.time()
    _need(con, 0.0006 + page * 0.00001, ph, c, now)
    d = _get(get)(twapi.FOLLOWINGS_URL, {"userName": handle, "cursor": "", "pageSize": page}) or {}
    out = [u for u in (d.get("followings") or []) if isinstance(u, dict)]
    store.book(con, "twitterapi", max(0.0006, len(out) * 0.00001), ph, "praćeni", now)
    return out


def followings_page(con, handle, ph, c, now=None, get=None, cursor="", page=200, what="praćeni"):
    """One page of the accounts `handle` follows: ([user], next_cursor or None). 200 a page = $0.01 per 1,000
    (kol/twapi.followings), at least $0.0006 a call."""
    now = now or time.time()
    _need(con, max(0.0006, page * 0.00001), ph, c, now)
    d = _get(get)(twapi.FOLLOWINGS_URL, {"userName": handle, "cursor": cursor or "", "pageSize": page}) or {}
    if d.get("status") == "error":
        raise RuntimeError(f"twitterapi: {str(d.get('msg') or d.get('message'))[:120]}")
    out = [u for u in (d.get("followings") or []) if isinstance(u, dict)]
    store.book(con, "twitterapi", max(0.0006, len(out) * 0.00001), ph, what, now)
    nxt = d.get("next_cursor") if d.get("has_next_page") else None
    return out, (nxt or None)
