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


# ---------- price sanity ----------
# 1.11. "pairless": DexScreener reported price 0.0011 / MC $1.07M / liquidity $407k / +6654% in 1 h on the pump.swap
# pool with $5k volume that hour, while the pool's real trades (GeckoTerminal candles) were at 0.000014. The
# competition chart jumped to $8k and a sale went through at the fake price. A real 3x+ move in an hour moves money:
# the hour's volume is a good share of the pool. A jump without that volume is a bad reading and is not used.
JUMP = 3.0          # a reading this many times the last good one ...
MIN_TURNOVER = 0.5  # ... needs at least this share of the pool's liquidity traded in the last hour
_LAST = {}          # pairAddress -> (ts, price, liquidity) of the last reading accepted, per process
_LOCK = threading.Lock()


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def sane(p, now=None):
    """Check one pair dict in place. A suspicious price is replaced by the last good one (or, the first time, by the
    price an hour ago from priceChange.h1) and the pair gets p["sumnjivo"] = reason. Returns p."""
    now = now or time.time()
    key = p.get("pairAddress") or (p.get("baseToken") or {}).get("address")
    price = _f(p.get("priceUsd"))
    if not key or price <= 0:
        return p
    vol = p.get("volume") or {}
    vol_h1 = _f(vol.get("h1"))
    liq = _f((p.get("liquidity") or {}).get("usd"))
    chg = _f((p.get("priceChange") or {}).get("h1"))
    with _LOCK:
        last = _LAST.get(key)
    good = None
    if last and price >= JUMP * last[1]:
        age = now - last[0]
        traded = vol_h1 if age <= 3600 else _f(vol.get("h6")) if age <= 6 * 3600 else _f(vol.get("h24"))
        if traded < MIN_TURNOVER * max(last[2], 1):
            good, why = last[1], f"cijena {price / last[1]:.0f}x uz samo ${traded:,.0f} prometa"
    if good is None and chg >= (JUMP - 1) * 100 and vol_h1 < MIN_TURNOVER * 0.1 * max(liq, 1):
        good = last[1] if last else price / (1 + chg / 100)
        why = f"+{chg:.0f}% u 1 h uz samo ${vol_h1:,.0f} prometa"
    if good is None:
        with _LOCK:
            _LAST[key] = (now, price, liq)
            if len(_LAST) > 20000:
                _LAST.clear()
        return p
    k = good / price
    p["priceUsd"] = f"{good:.12g}"
    for f in ("marketCap", "fdv"):
        if p.get(f):
            p[f] = _f(p[f]) * k
    if last:  # the pool's own liquidity reading jumps with the bad price
        p["liquidity"] = {**(p.get("liquidity") or {}), "usd": last[2]}
    p["sumnjivo"] = why
    return p


def tokens(chain, addresses):
    """Pairs for up to 30 token addresses per request (batched here); prices pass the sanity check (sane())."""
    out = []
    for i in range(0, len(addresses), 30):
        out += _get(f"/tokens/v1/{_q(chain)}/{','.join(addresses[i:i + 30])}", fast=True) or []
    return [sane(p) for p in out]
