"""Token lookup helpers for the competition: token address or DexScreener link -> token, market cap, symbol.
(The old "Moji pravi tradeovi" page was removed on 2026-11-01; its rows stay in league.db table real_trades.)
"""
import re

ADDR = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")


def _best(pairs):
    """token -> (market cap, symbol, url) from the deepest pair."""
    out = {}
    for p in pairs:
        t, liq = p["baseToken"]["address"], (p.get("liquidity") or {}).get("usd") or 0
        if liq >= out.get(t, (0, 0, 0, -1))[3]:
            out[t] = (p.get("marketCap") or p.get("fdv"), p["baseToken"].get("symbol"), p.get("url"), liq)
    return {t: v[:3] for t, v in out.items()}


def live(mints):
    if not mints:
        return {}
    try:
        from dexscreener import client
        return _best(client.tokens("solana", list(mints)))
    except Exception:
        return {}


def resolve(text):
    """Token address or DexScreener link (token or pair) -> (token, market cap, symbol)."""
    m = ADDR.search(text or "")
    if not m:
        raise ValueError("ne vidim Solana adresu ni DexScreener link")
    addr = m[0]
    got = live({addr})
    if addr in got:
        return addr, got[addr][0], got[addr][1]
    try:
        from dexscreener import client
        p = client.pair("solana", addr)
    except Exception:
        p = None
    if p:
        return p["baseToken"]["address"], p.get("marketCap") or p.get("fdv"), p["baseToken"].get("symbol")
    return addr, None, None

