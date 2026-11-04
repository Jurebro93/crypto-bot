"""Where candidates come from and how their data is fetched. All free; Birdeye only with BIRDEYE_API_KEY.

Universe: every token our KOL/Telegram tracking ever saw (kol.db calls, hype.db tg_mentions), tokens the hype
scanner saw at least a week ago with real liquidity (hype.db hype_signals), the established Solana tokens in
config.json "uzori"/"temelj", and GeckoTerminal's busiest Solana pools (catches older tokens nobody called).
"""
import json
import os
import sqlite3
import time
import urllib.error
import urllib.request

from dexscreener import client as dex
from event_calendar import http

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GECKO = "https://api.geckoterminal.com/api/v2/networks/solana"
D = 86400
QUOTES = {"So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qZxEHFTGFfqx6pVbmF1rDWdBYv",
          "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}
_last = [0.0]


class GeckoBusy(Exception):
    """GeckoTerminal's free per-minute limit is used up (by us or the KOL module): not an error, try next pass."""


def _gecko(path, gap):
    """GeckoTerminal GET without the disk cache (candles are stored in dugo.db anyway). The free API allows ~30
    calls a minute per IP and the KOL module uses the same IP: calls are spaced `gap` seconds here and queue with
    the other processes through http's shared gate. The Dugoročni lists refresh slowly anyway, so on a 429 (or
    while the gate is paused after someone else's 429) we give way to the KOL measurements instead of waiting."""
    url = GECKO + path
    if http.cooling(url) > 0:
        raise GeckoBusy()
    wait = _last[0] + gap - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": http.USER_AGENT, "Accept": "application/json"})
    try:
        return http._fetch(req, 30, retries=0)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise GeckoBusy() from None
        raise


def _ro(name):
    p = os.path.join(HERE, name)
    if not os.path.exists(p):
        return None
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)


def _q(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


def universe(cfg, now=None):
    """{mint: source} of every token worth checking."""
    now = now or time.time()
    out = {}
    for m in cfg.get("uzori", {}).values():
        out[m] = "uzor"
    for m in cfg.get("temelj", {}).values():
        out.setdefault(m, "temelj")
    kol = _ro("kol.db")
    for (m,) in _q(kol, "SELECT DISTINCT token FROM calls WHERE kind IS NULL OR kind NOT IN ('brag','bot','warn')"):
        out.setdefault(m, "kol")
    hype = _ro("hype.db")
    for (m,) in _q(hype, "SELECT DISTINCT ca FROM tg_mentions"):
        out.setdefault(m, "telegram")
    for (m,) in _q(hype, "SELECT token FROM hype_signals GROUP BY token HAVING MIN(ts) < ? AND MAX(liquidity) >= ?",
                   (now - 7 * D, cfg["hype_min_liq"])):
        out.setdefault(m, "skener")
    for c in (kol, hype):
        if c:
            c.close()
    return {m: s for m, s in out.items() if m and m not in QUOTES}


def gecko_top(pages, gap):
    """Mints of the busiest Solana pools (base token), a few pages of 20."""
    out = []
    for p in range(1, pages + 1):
        try:
            d = _gecko(f"/pools?page={p}&sort=h24_volume_usd_desc", gap)
        except Exception:
            break
        for pool in d.get("data", []):
            bt = (pool.get("relationships", {}).get("base_token", {}).get("data", {}).get("id") or "")
            m = bt.split("_", 1)[-1]
            if m and m not in QUOTES:
                out.append(m)
    return out


def dex_best(mints):
    """{mint: DexScreener pair to believe} for many mints (30 per call, free). Not simply the biggest reported
    liquidity any more (audit 4.11. F04/PYTH): dexscreener.client.pick_pool takes the most liquid SOL/USDC/USDT
    pool that agrees with the median price; a conflict is put on the pair as p["sumnjivo"] (shown, not ranked)."""
    by = {}
    for p in dex.tokens("solana", list(mints)):
        m = (p.get("baseToken") or {}).get("address")
        if m in mints:
            by.setdefault(m, []).append(p)
    best = {}
    for m, ps in by.items():
        p, why = dex.pick_pool(ps)
        if p is None:
            continue
        if why:
            p = {**p, "sumnjivo": why}
        best[m] = p
    return best


def candles(pair, gap, limit=400):
    """[(day, o, h, l, c, v)] oldest first from GeckoTerminal daily candles of the pair."""
    d = _gecko(f"/pools/{pair}/ohlcv/day?limit={limit}&currency=usd&token=base", gap)
    rows = (d.get("data") or {}).get("attributes", {}).get("ohlcv_list") or []
    return sorted((int(r[0]) // D * D, *map(float, r[1:6])) for r in rows)


def btc_closes(days=365):
    """{day: close} BTC from CoinGecko's free endpoint (one call a day)."""
    d = http.get_json("https://api.coingecko.com/api/v3/coins/bitcoin/market_chart",
                      {"vs_currency": "usd", "days": days, "interval": "daily"}, ttl=6 * 3600)
    # a CoinGecko point at 00:00 UTC is the close of the PREVIOUS day; GeckoTerminal candles are keyed by their open day
    return {int(t / 1000) // D * D - D: p for t, p in d.get("prices", []) if int(t / 1000) % D < 3600}


def holders_birdeye(mint):
    """Holder count from Birdeye (paid, only with BIRDEYE_API_KEY). None without the key or on error."""
    key = os.environ.get("BIRDEYE_API_KEY")
    if not key:
        return None
    req = urllib.request.Request(f"https://public-api.birdeye.so/defi/token_overview?address={mint}",
                                 headers={"X-API-KEY": key, "x-chain": "solana", "Accept": "application/json",
                                          "User-Agent": http.USER_AGENT})
    try:
        d = http._fetch(req, 20, retries=1)
        return (d.get("data") or {}).get("holder")
    except Exception:
        return None


def social(mints, now=None):
    """{mint: {kol_autora, kol_tjedana_60d, kol_7d, tg_30d, tg_7d}} from our own KOL and Telegram tracking."""
    now = now or time.time()
    out = {m: {"kol_autora": 0, "kol_tjedana_60d": 0, "kol_7d": 0, "tg_30d": 0, "tg_7d": 0} for m in mints}
    kol = _ro("kol.db")
    for m, a, w, n7 in _q(kol, """SELECT token, COUNT(DISTINCT handle),
            COUNT(DISTINCT CASE WHEN ts > ? THEN ts / 604800 END), SUM(ts > ?) FROM calls
            WHERE kind IS NULL OR kind NOT IN ('brag', 'bot', 'warn') GROUP BY token""", (now - 60 * D, now - 7 * D)):
        if m in out:
            out[m].update(kol_autora=a or 0, kol_tjedana_60d=w or 0, kol_7d=n7 or 0)
    hype = _ro("hype.db")
    t30 = time.strftime("%Y-%m-%dT%H:%M", time.gmtime(now - 30 * D))
    t7 = time.strftime("%Y-%m-%dT%H:%M", time.gmtime(now - 7 * D))
    for m, n30, n7 in _q(hype, "SELECT ca, COUNT(*), SUM(time > ?) FROM tg_mentions WHERE time > ? GROUP BY ca", (t7, t30)):
        if m in out:
            out[m].update(tg_30d=n30 or 0, tg_7d=n7 or 0)
    for c in (kol, hype):
        if c:
            c.close()
    return out


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default
