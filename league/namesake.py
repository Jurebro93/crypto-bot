"""Namesake tokens: the same ticker on a CEX or on a much bigger Solana token than the one being bought.

5.11.: Filip bought a pump.fun "ARIA" (MC $74k, $61 of volume a day) while watching AriaAI on Binance (MC $27M,
+17 % that day), then asked why his position "never moves". DexScreener's search by symbol finds the real one; if a
token with the same ticker has a market cap at least RATIO times bigger, the buyer is told before and after the buy.
"""
import time

RATIO = 20          # the namesake must be this many times bigger to count
MIN_BIG = 1_000_000  # and at least this big (two $50k memes with the same name are not a mix-up)
TTL = 6 * 3600
_CACHE = {}          # token -> (ts, result or None)


def _pairs(symbol):
    from dexscreener import client
    return client.search(symbol)


def check(token, symbol, mcap, pairs=None):
    """None, or {"token","name","mcap","url"} of the biggest Solana token with the same ticker that dwarfs this one."""
    if not symbol or not mcap or mcap <= 0:
        return None
    now = time.time()
    hit = _CACHE.get(token)
    if hit and now - hit[0] < TTL and pairs is None:
        return hit[1]
    try:
        pairs = pairs if pairs is not None else _pairs(symbol)
    except Exception:  # noqa: BLE001
        return None
    best = None
    for p in pairs or []:
        bt = p.get("baseToken") or {}
        if p.get("chainId") != "solana" or bt.get("address") == token:
            continue
        if (bt.get("symbol") or "").strip().upper() != symbol.strip().upper():
            continue
        mc = p.get("marketCap") or p.get("fdv") or 0
        if mc >= MIN_BIG and mc >= RATIO * mcap and (best is None or mc > best["mcap"]):
            best = {"token": bt["address"], "name": bt.get("name") or symbol, "mcap": mc, "url": p.get("url") or ""}
    _CACHE[token] = (now, best)
    return best


def text(hit, symbol, mcap):
    """One Croatian sentence for the buy confirmation and the position card."""
    from ui.html import esc
    from ui.paper import _mc
    return (f'⚠️ <b>Istoimeni token:</b> postoji {esc(hit["name"])} ({esc(symbol)}) s MC {_mc(hit["mcap"])} na adresi '
            f'<code>{esc(hit["token"][:4])}…{esc(hit["token"][-4:])}</code>. Ovaj koji držiš ima MC {_mc(mcap)}: '
            'ako si htio onaj veliki (npr. s Binancea), kupio si kopiju. Provjeri adresu.')
