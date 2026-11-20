"""The free market sources for BSC: GeckoTerminal (network "bsc": pool lists, OHLCV), DexScreener (chain "bsc": token
pairs with market cap, liquidity, pair age; live prices for the measurement) and Binance's public market-data mirror
(data-api.binance.vision: BNBUSDT / SOLUSDT hourly klines, the USD of a WBNB amount and of 0.05 SOL at a time).

GeckoTerminal goes through event_calendar/http.get_json, i.e. the repo's shared per-IP gate (3.5 s between calls of
every process, a shared pause after a 429) and its cache; nothing here paces it on its own. DexScreener through
dexscreener/client (its own 280 / 55 a minute throttles). Calls are counted per source in CALLS (the run line, the
report) and in usage/ (service "bsc-free", amount 0).
"""
import json
import time
import urllib.parse
import urllib.request
from collections import Counter

from bnb import swaps

GT = "https://api.geckoterminal.com/api/v2"
BINANCE = "https://data-api.binance.vision/api/v3/klines"
CALLS = Counter()
UA = "chain-research/0.1 (public data, low rate)"


def _count(src, method):
    CALLS[src] += 1
    try:
        from usage import meter
        meter.record("bsc-free", f"{src}:{method}", 0.0)
    except Exception:  # noqa: BLE001
        pass


def gt(path, params=None, ttl=600):
    """One GeckoTerminal GET through the shared gate (event_calendar/http); None when the gate says another job holds
    the host or the call fails."""
    from event_calendar import http
    _count("geckoterminal", path.split("/")[3] if path.count("/") >= 3 else path)
    try:
        return http.get_json(GT + path, params, ttl=ttl, timeout=30)
    except Exception as e:  # noqa: BLE001
        CALLS["geckoterminal_err"] += 1
        print(f"bnb: GeckoTerminal {path[:60]}: {type(e).__name__} {str(e)[:80]}", flush=True)
        return None


def _f(x):
    try:
        return float(x) if x not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _iso(s):
    try:
        import datetime as dt
        return int(dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp())
    except (TypeError, ValueError):
        return None


def pool_row(x):
    """GeckoTerminal pool JSON -> {"pool", "dex", "token", "quote", "symbol", "quote_sym", "fdv", "mcap", "liq",
    "vol24", "created"} with the memecoin as `token` (the non-quote side), or None (no known quote)."""
    a, r = x.get("attributes") or {}, x.get("relationships") or {}
    base = ((r.get("base_token") or {}).get("data") or {}).get("id", "").split("_")[-1].lower()
    quote = ((r.get("quote_token") or {}).get("data") or {}).get("id", "").split("_")[-1].lower()
    dex = ((r.get("dex") or {}).get("data") or {}).get("id")
    name = a.get("name") or ""
    parts = [p.strip() for p in name.split("/")]
    bsym = parts[0] if parts else None
    qsym = parts[1].split(" ")[0] if len(parts) > 1 else None
    if base in swaps.QUOTES and quote not in swaps.QUOTES:   # the memecoin listed as the quote side
        base, quote, bsym, qsym = quote, base, qsym, bsym
    if quote not in swaps.QUOTES or base in swaps.QUOTES:
        return None
    return {"pool": (a.get("address") or "").lower(), "dex": dex, "token": base, "quote": quote, "symbol": bsym,
            "quote_sym": swaps.QUOTES[quote][0], "fdv": _f(a.get("fdv_usd")), "mcap": _f(a.get("market_cap_usd")),
            "liq": _f(a.get("reserve_in_usd")), "vol24": _f((a.get("volume_usd") or {}).get("h24")),
            "created": _iso(a.get("pool_created_at")), "src": "gt"}


def gt_lists(c, log=print):
    """[pool row] from GeckoTerminal's BSC lists: top pools by 24 h volume (gt_volume_pages), trending (1 h / 6 h /
    24 h, gt_trend_pages each), the top pools of each gt_dexes DEX (gt_dex_pages each). ~31 calls."""
    out = []
    for page in range(1, int(c["gt_volume_pages"]) + 1):
        d = gt("/networks/bsc/pools", {"page": page, "sort": "h24_volume_usd_desc"}, ttl=3600)
        out += [r for r in (pool_row(x) for x in (d or {}).get("data") or []) if r]
    for dex in c.get("gt_dexes") or ():   # per DEX: a deeper list than the network's top 200
        for page in range(1, int(c.get("gt_dex_pages") or 0) + 1):
            d = gt(f"/networks/bsc/dexes/{dex}/pools", {"page": page, "sort": "h24_volume_usd_desc"}, ttl=3600)
            out += [r for r in (pool_row(x) for x in (d or {}).get("data") or []) if r]
    for dur in ("1h", "6h", "24h"):
        for page in range(1, int(c["gt_trend_pages"]) + 1):
            d = gt("/networks/bsc/trending_pools", {"page": page, "duration": dur}, ttl=3600)
            out += [r for r in (pool_row(x) for x in (d or {}).get("data") or []) if r]
    return out


def ds_pair_row(p):
    """DexScreener pair JSON (chain bsc) -> a pool row like pool_row (src "ds"), or None (curve / no quote)."""
    if (p.get("chainId") or "") != "bsc":
        return None
    dex = (p.get("dexId") or "").lower()
    if "four" in dex or "meme" in dex:   # four.meme bonding curve ("fourmeme"): never read (CLAUDE.md)
        return None
    base = ((p.get("baseToken") or {}).get("address") or "").lower()
    quote = ((p.get("quoteToken") or {}).get("address") or "").lower()
    bsym = (p.get("baseToken") or {}).get("symbol")
    name = (p.get("baseToken") or {}).get("name")
    if base in swaps.QUOTES and quote not in swaps.QUOTES:
        base, quote = quote, base
        bsym, name = (p.get("quoteToken") or {}).get("symbol"), (p.get("quoteToken") or {}).get("name")
    if quote not in swaps.QUOTES or base in swaps.QUOTES:
        return None
    labels = [str(x).lower() for x in p.get("labels") or []]
    gdex = {"pancakeswap": "pancakeswap-v3-bsc" if "v3" in labels else
            "pancakeswap-infinity-clmm" if any("cl" in x or "v4" in x or "inf" in x for x in labels) else
            "pancakeswap_v2", "uniswap": "uniswap-v3-bsc" if "v3" in labels else "uniswap-bsc"}.get(dex, dex)
    created = p.get("pairCreatedAt")
    return {"pool": (p.get("pairAddress") or "").lower(), "dex": gdex, "token": base, "quote": quote, "symbol": bsym,
            "name": name, "quote_sym": swaps.QUOTES[quote][0], "fdv": _f(p.get("fdv")),
            "mcap": _f(p.get("marketCap")), "liq": _f((p.get("liquidity") or {}).get("usd")),
            "vol24": _f((p.get("volume") or {}).get("h24")), "created": int(created / 1000) if created else None,
            "src": "ds", "price": _f(p.get("priceUsd"))}


def ds_lists(c):
    """[pool row] from DexScreener searches (c["ds_queries"]) and the top boosts on bsc."""
    from dexscreener import client as ds
    out = []
    for qy in c["ds_queries"]:
        _count("dexscreener", "search")
        try:
            out += [r for r in (ds_pair_row(p) for p in ds.search(qy)) if r]
        except Exception:  # noqa: BLE001
            CALLS["dexscreener_err"] += 1
    try:
        _count("dexscreener", "boosts")
        toks = [b.get("tokenAddress") for b in ds.top_boosts() or [] if b.get("chainId") == "bsc"]
        if toks:
            out += [r for r in (ds_pair_row(p) for p in tokens(toks)) if r]
    except Exception:  # noqa: BLE001
        CALLS["dexscreener_err"] += 1
    return out


def tokens(addrs, ttl=60):
    """DexScreener /tokens/v1/bsc/<up to 30> -> [pair JSON]."""
    from dexscreener import client as ds
    out = []
    addrs = list(dict.fromkeys(a for a in addrs if a))
    for i in range(0, len(addrs), 30):
        _count("dexscreener", "tokens")
        try:
            out += ds.tokens("bsc", addrs[i:i + 30], ttl=ttl) or []
        except Exception:  # noqa: BLE001
            CALLS["dexscreener_err"] += 1
    return out


def best_pairs(addrs, ttl=600):
    """{token: (best pool row by liquidity, token mcap, token fdv)} from DexScreener tokens/v1 (30 a call): the
    market cap and the most liquid supported pool of each token."""
    by = {}
    for p in tokens(addrs, ttl=ttl):
        r = ds_pair_row(p)
        if not r or not swaps.kind_of(r["dex"], r["pool"]):
            continue
        cur = by.get(r["token"])
        if cur is None or (r["liq"] or 0) > (cur["liq"] or 0):
            by[r["token"]] = r
    return by


def ohlcv(pool, token, res, limit=1000, before=None):
    """[(ts, o, h, l, c, v)] USD candles of `token` in `pool` (res "day" | "hour"), oldest first."""
    params = {"limit": limit, "currency": "usd", "token": token}
    if before:
        params["before_timestamp"] = int(before)
    d = gt(f"/networks/bsc/pools/{pool}/ohlcv/{res}", params, ttl=1800)
    rows = (((d or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    out = []
    for r in rows:
        try:
            out.append((int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5] or 0)))
        except (TypeError, ValueError, IndexError):
            continue
    return sorted(out)


def klines(symbol, start_ms, end_ms, interval="1h", fetch=None):
    """[(ts, close)] of Binance's public market-data mirror (no key), 1000 a call."""
    out = []
    t = int(start_ms)
    while t < end_ms:
        q = urllib.parse.urlencode({"symbol": symbol, "interval": interval, "startTime": t, "endTime": int(end_ms),
                                    "limit": 1000})
        _count("binance-data", "klines")
        if fetch:
            rows = fetch(f"{BINANCE}?{q}")
        else:
            req = urllib.request.Request(f"{BINANCE}?{q}", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                rows = json.load(r)
            time.sleep(0.3)
        if not rows:
            break
        out += [(int(x[0]) // 1000, float(x[4])) for x in rows]
        t = int(rows[-1][0]) + 1
        if len(rows) < 1000:
            break
    return out
