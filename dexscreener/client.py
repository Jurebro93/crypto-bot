"""DexScreener public API (no key). Docs: https://docs.dexscreener.com/api/reference

Rate limits: 60 req/min for profiles/boosts/orders/metas, 300 req/min for pairs/search/tokens.
Responses are cached briefly (DEX_CACHE_TTL, default 60 s) so reruns don't burn the limit.
"""
import os
import threading
import time
import urllib.parse

from event_calendar import http

BASE = "https://api.dexscreener.com"
CACHE_TTL = int(os.environ.get("DEX_CACHE_TTL", "60"))


class _Throttle:
    """Spaces calls so we stay under a per-minute limit."""

    def __init__(self, per_minute):
        self.gap = 60.0 / per_minute
        self.last = 0.0
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            delay = self.last + self.gap - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self.last = time.monotonic()


_SLOW = _Throttle(55)
_FAST = _Throttle(280)


def _get(path, params=None, fast=False):
    (_FAST if fast else _SLOW).wait()
    return http.get_json(f"{BASE}{path}", params, ttl=CACHE_TTL)


def _q(s):
    return urllib.parse.quote(str(s), safe="")


# 60 req/min
def latest_token_profiles():
    return _get("/token-profiles/latest/v1")


def recent_profile_updates():
    return _get("/token-profiles/recent-updates/v1")


def latest_boosts():
    return _get("/token-boosts/latest/v1")


def top_boosts():
    return _get("/token-boosts/top/v1")


def community_takeovers():
    return _get("/community-takeovers/latest/v1")


def latest_ads():
    return _get("/ads/latest/v1")


def orders(chain, token):
    """Paid orders (profile, ads, boosts) for a token: who paid DexScreener to promote it."""
    return _get(f"/orders/v1/{_q(chain)}/{_q(token)}").get("orders", [])


def trending_metas():
    return _get("/metas/trending/v1")


def meta(slug):
    return _get(f"/metas/meta/v1/{_q(slug)}")


# 300 req/min
def search(query):
    return _get("/latest/dex/search", {"q": query}, fast=True).get("pairs") or []


def pair(chain, pair_address):
    data = _get(f"/latest/dex/pairs/{_q(chain)}/{_q(pair_address)}", fast=True)
    return (data.get("pairs") or [None])[0]


def token_pairs(chain, token):
    return _get(f"/token-pairs/v1/{_q(chain)}/{_q(token)}", fast=True) or []


def tokens(chain, addresses):
    """Pairs for up to 30 token addresses per request (batched here)."""
    out = []
    for i in range(0, len(addresses), 30):
        out += _get(f"/tokens/v1/{_q(chain)}/{','.join(addresses[i:i + 30])}", fast=True) or []
    return out
