"""Live token prices in SOL from DexScreener (free, no key, 300 req/min, 30 tokens per request, cached 60 s).

Used by the wallet page for the unrealized PnL of open positions. No Helius credits.
"""
WSOL = "So11111111111111111111111111111111111111112"


def _best(pairs):
    """mint -> most liquid Solana pair."""
    best = {}
    for p in pairs or []:
        if p.get("chainId") not in (None, "solana"):
            continue
        m = (p.get("baseToken") or {}).get("address")
        liq = (p.get("liquidity") or {}).get("usd") or 0
        if m and liq >= ((best.get(m, {}).get("liquidity") or {}).get("usd") or 0):
            best[m] = p
    return best


def sol_prices(mints, fetch=None, limit=90):
    """{mint: price in SOL per token} for up to limit mints; a mint without any pair is left out (unknown)."""
    from dexscreener import client
    fetch = fetch or (lambda ms: client.tokens("solana", ms))
    mints = list(dict.fromkeys(mints))[:limit]
    if not mints:
        return {}
    best = _best(fetch(mints + ([WSOL] if WSOL not in mints else [])))
    sol_usd = float((best.get(WSOL) or {}).get("priceUsd") or 0)
    out = {}
    for m in mints:
        p = best.get(m)
        if not p:
            continue
        q = (p.get("quoteToken") or {}).get("address")
        if q == WSOL and p.get("priceNative"):
            out[m] = float(p["priceNative"])
        elif p.get("priceUsd") and sol_usd:
            out[m] = float(p["priceUsd"]) / sol_usd
    return out
