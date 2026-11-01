"""Hype features for one token, each scaled 0..1, and a weighted score 0..100.

Weights live in hype/weights.json; `run_hype.py eval --fit` writes hype/weights.suggested.json.
"""
import json
import math
import os
import re

WEIGHTS_PATH = os.path.join(os.path.dirname(__file__), "weights.json")


def load_weights(path=None):
    with open(path or WEIGHTS_PATH) as f:
        return json.load(f)


def _norm(s):
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _clip(x):
    return max(0.0, min(1.0, x))


def market_features(p, now_ms):
    """Features from one DexScreener pair."""
    liq = (p.get("liquidity") or {}).get("usd") or 0
    vol = p.get("volume") or {}
    tx = (p.get("txns") or {}).get("h1") or {}
    buys, sells = tx.get("buys", 0), tx.get("sells", 0)
    created = p.get("pairCreatedAt")
    age_h = (now_ms - created) / 3.6e6 if created else 999
    chg = (p.get("priceChange") or {}).get("h1") or 0
    info = p.get("info") or {}
    return {
        "fresh": _clip(1 - (age_h - 1) / 71) if age_h > 1 else 1.0,          # 1 under 1 h, 0 at 72 h
        "turnover": _clip((vol.get("h1") or 0) / liq / 3) if liq else 0.0,  # 1h volume vs liquidity
        "buy_pressure": _clip((buys / (buys + sells) - 0.5) * 2.5) if buys + sells >= 10 else 0.0,
        "momentum": _clip(chg / 200),
        "activity": _clip(math.log10(1 + buys + sells) / math.log10(2000)),
        "paid": 1.0 if (p.get("boosts") or {}).get("active") or info.get("imageUrl") else 0.0,
        "socials": _clip(len(info.get("socials") or []) / 3 + 0.34 * bool(info.get("websites"))),
        # an old token waking up: last hour's volume far above its 24 h hourly average
        "revival": _clip(((vol.get("h1") or 0) * 24 / max(vol.get("h24") or 0, 1) - 1) / 5)
        if age_h >= 72 and (vol.get("h1") or 0) >= 2000 else 0.0,
    }


def copycats(pairs, symbol, name, token, now_ms, window_h=72):
    """Other Solana tokens launched recently with the same theme. Many clones = a live narrative."""
    keys = {k for k in (_norm(symbol), _norm(name)) if len(k) >= 3}
    seen = set()
    for p in pairs:
        b = p["baseToken"]
        if p.get("chainId") != "solana" or b["address"] == token or b["address"] in seen:
            continue
        created = p.get("pairCreatedAt") or 0
        if (now_ms - created) / 3.6e6 > window_h:
            continue
        s, n = _norm(b.get("symbol")), _norm(b.get("name"))
        if any(k == s or k in n or (s and len(s) >= 3 and s in k) for k in keys):
            seen.add(b["address"])
    return len(seen)


def score(features, weights):
    """Weighted mean over the features that were measured for this token. A paid or deep check that did not run
    (X buzz, smart money, Google Trends...) is left out of `features`, so it neither helps nor hurts."""
    # Negative weights (a signal the learning loop found to hurt) subtract; the scale stays the positive weights of the
    # measured features, so with only non-negative weights the score is exactly the weighted mean it always was.
    total = sum(max(0.0, weights.get(k, 0)) for k in features) or 1
    return round(max(0.0, min(100.0, 100 * sum(weights.get(k, 0) * v for k, v in features.items()) / total)), 1)
