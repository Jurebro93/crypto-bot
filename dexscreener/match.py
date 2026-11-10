"""Turn raw DexScreener pairs into tokens tied to a calendar event, ranked canonical first.

Heuristics only use what DexScreener gives (age, volume, txns, liquidity, socials, CTO).
Holder counts and wallet quality come from the Helius rug filter, not from here.
"""
import math
import re
import time

# Words that match thousands of unrelated tokens. Never search or match on them alone.
NOISE = {
    "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER",
    "OCTOBER", "NOVEMBER", "DECEMBER", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY",
    "SATURDAY", "SUNDAY", "TODAY", "WEEK", "MONTH", "YEAR", "DAY", "PRICE", "ABOVE", "BELOW",
    "HIT", "TWEETS", "WEST", "EAST", "NORTH", "SOUTH", "NEW", "WORLD", "GAME", "TOKEN", "COIN",
    "SOL", "SOLANA", "USD", "USDC", "USDT", "BTC", "ETH", "WETH", "WBTC",
}
# Wrapped majors and stables: real liquidity but never an event memecoin.
MAX_MCAP = 500e6


def _norm(s):
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def event_terms(event):
    """Specific search terms for an event: its keywords minus noise, plus the subject phrase."""
    terms = [k for k in event.get("keywords", []) if _norm(k) not in NOISE and len(_norm(k)) >= 3]
    words = [w for w in re.findall(r"[A-Za-z0-9]+", event.get("subject", "")) if _norm(w) not in NOISE]
    if len(words) >= 2:
        terms.insert(0, " ".join(dict.fromkeys(words)))
    return list(dict.fromkeys(terms))


def weak_terms(event):
    """Single words of a multi-word subject ("HARRY" of Harry Kane): too generic to tie a token to the event."""
    words = [_norm(w) for w in re.findall(r"[A-Za-z0-9]+", event.get("subject", ""))]
    return set(words) if len(words) >= 2 else set()


def summarize(p, now_ms=None):
    now_ms = now_ms or time.time() * 1000
    created = p.get("pairCreatedAt")
    tx = (p.get("txns") or {}).get("h24") or {}
    info = p.get("info") or {}
    return {
        "chain": p.get("chainId"),
        "dex": p.get("dexId"),
        "token": p["baseToken"]["address"],
        "symbol": p["baseToken"].get("symbol", ""),
        "name": p["baseToken"].get("name", ""),
        "pair": p.get("pairAddress"),
        "url": p.get("url"),
        "price_usd": float(p.get("priceUsd") or 0),
        "mcap": p.get("marketCap") or p.get("fdv") or 0,
        "liquidity": (p.get("liquidity") or {}).get("usd") or 0,
        "vol_24h": (p.get("volume") or {}).get("h24") or 0,
        "vol_1h": (p.get("volume") or {}).get("h1") or 0,
        "chg_1h": (p.get("priceChange") or {}).get("h1"),
        "chg_24h": (p.get("priceChange") or {}).get("h24"),
        "buys_24h": tx.get("buys", 0),
        "sells_24h": tx.get("sells", 0),
        "age_h": round((now_ms - created) / 3.6e6, 1) if created else None,
        "boosts": (p.get("boosts") or {}).get("active", 0),
        "socials": len(info.get("socials") or []),
        "website": bool(info.get("websites")),
    }


def matches(row, terms, weak=()):
    """Which term ties this token to the event, or None. Symbol must equal a term, or name contain it.
    Weak terms never count on their own."""
    sym, name = _norm(row["symbol"]), _norm(row["name"])
    terms = [t for t in terms if _norm(t) not in weak]
    for t in terms:
        if _norm(t) == sym:
            return t
    for t in terms:
        n = _norm(t)
        if len(n) >= 4 and n in name:
            return t
    return None


def best_pairs(pairs, chain="solana", min_liquidity=1000, min_volume=100, now_ms=None):
    """One row per token (its deepest pair), dropping dust, dead pairs and majors."""
    best = {}
    for p in pairs:
        if chain and p.get("chainId") != chain:
            continue
        row = summarize(p, now_ms)
        if row["liquidity"] < min_liquidity or row["mcap"] > MAX_MCAP:
            continue
        if row["vol_24h"] < min_volume:  # dead pair
            continue
        cur = best.get(row["token"])
        if cur is None or row["liquidity"] > cur["liquidity"]:
            best[row["token"]] = row
    return list(best.values())


def organic_score(row, cto=False):
    """0-100: how much this looks like the real, organically traded token for the narrative."""
    age_d = max(0, row["age_h"] or 0) / 24
    age = min(15, 15 * math.log10(1 + age_d) / math.log10(31))          # 30+ days = max
    liq = min(15, 15 * math.log10(1 + row["liquidity"]) / 6)             # $1M = max
    # 9.11. (Jure, RIPTRUMP): $2k/day used to earn 14 of 25 points and 21 tx/day a "healthy buy ratio" 10/10, so a
    # dead old token outscored live ones. Volume counts from $1k/day ($1M = max), transactions from 10/day (10k =
    # max), and the buy/sell balance means nothing under 50 transactions a day.
    vol = 25 * min(1.0, max(0.0, math.log10(max(row["vol_24h"], 1) / 1e3) / 3))
    txs = row["buys_24h"] + row["sells_24h"]
    activity = 15 * min(1.0, max(0.0, math.log10(max(txs, 1) / 10) / 3))
    buy_share = row["buys_24h"] / txs if txs else 0
    balance = (10 if 0.4 <= buy_share <= 0.7 else 4 if 0.3 <= buy_share <= 0.8 else 0) if txs >= 50 else 0
    turnover = row["vol_24h"] / row["liquidity"] if row["liquidity"] else 0
    wash = -15 if turnover > 30 else 0                                   # volume far beyond pool depth
    social = min(10, 4 * row["socials"] + (3 if row["website"] else 0))
    return round(max(0, age + liq + vol + activity + balance + wash + social + (15 if cto else 0)), 1)


def rank_event_tokens(rows, terms, cto_tokens=(), exact_bonus=10, weak=()):
    """Tokens matching the event, best first; the top one is marked canonical, the rest copycats."""
    out = []
    for r in rows:
        term = matches(r, terms, weak)
        if not term:
            continue
        exact = _norm(term) == _norm(r["symbol"])
        cto = r["token"] in cto_tokens
        out.append({**r, "keyword": term, "exact": exact, "cto": cto,
                    "score": round(organic_score(r, cto) + (exact_bonus if exact else 0), 1)})
    out.sort(key=lambda r: -r["score"])
    for i, r in enumerate(out):
        r["role"] = "canonical" if i == 0 else "copycat"
    return out
