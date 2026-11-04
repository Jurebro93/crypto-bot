"""Free, keyless sources for Solana trading volume: DefiLlama DEX overview (every protocol, daily history) and
DefiLlama coin prices (SOL). Nothing here costs Helius credits or Apify dollars, so nothing is counted in usage.db."""
from event_calendar import http

OVERVIEW = "https://api.llama.fi/overview/dexs/solana"
PRICES = "https://coins.llama.fi/chart/coingecko:solana"

# DefiLlama category -> our group. Launchpads are the trenches (bonding curves), terminals are the apps
# trench traders click in (Axiom, GMGN, Photon, BullX, Trojan...), dex is everything that swaps on Solana.
GROUPS = {"Launchpad": "launchpad", "Trading App": "terminal", "Telegram Bot": "terminal", "Dexs": "dex"}
GROUP_NAMES = {"launchpad": "Launchpadi (trenchevi)", "terminal": "Trading terminali i botovi", "dex": "Solana DEX ukupno"}
# what the DefiLlama name means for a trench trader
ALIAS = {
    "launchlab": "LaunchLab (bonk.fun / letsbonk)",
    "meteora-dynamic-bonding-curve": "Meteora DBC (Bags, Believe, Jupiter Studio…)",
    "pump.fun": "pump.fun (bonding curve)",
    "pumpswap": "PumpSwap (pump.fun nakon graduacije)",
    "moonshot.money": "Moonshot",
}


def overview(history=True):
    """Every Solana protocol with its 24 h / 7 d volume; with history also the daily volume per protocol
    (totalDataChartBreakdown, keyed by display name, ~1 MB)."""
    params = {"excludeTotalDataChart": "true", "excludeTotalDataChartBreakdown": "false" if history else "true"}
    return http.get_json(OVERVIEW, params, ttl=1800 if history else 300, timeout=60)


def protocol_daily(slug):
    """[(day, solana_volume)] for one protocol. Used for the ones the overview leaves out of its daily breakdown
    (DefiLlama marks trading apps as double counted, and some launchpads are missing there)."""
    data = http.get_json(f"https://api.llama.fi/summary/dexs/{slug}", {"dataType": "dailyVolume"}, ttl=1800, timeout=60)
    out = []
    for day, chains in data.get("totalDataChartBreakdown") or []:
        sol = (chains or {}).get("Solana")
        if isinstance(sol, dict):
            out.append((int(day), float(sum(v for v in sol.values() if isinstance(v, (int, float))))))
    return out


def sol_prices(days=120):
    """[(unix_ts, usd)] one per day, oldest first."""
    data = http.get_json(PRICES, {"span": days, "period": "1d"}, ttl=1800)
    pts = (data.get("coins") or {}).get("coingecko:solana", {}).get("prices") or []
    return [(int(p["timestamp"]), float(p["price"])) for p in pts]


BTC_PRICES = "https://coins.llama.fi/chart/coingecko:bitcoin"
FNG = "https://api.alternative.me/fng/"   # free, keyless; attribution "Fear & Greed: alternative.me" required


def btc_prices(days=120):
    """[(unix_ts, usd)] one per day, oldest first (same free DefiLlama call as SOL). Audit 4.11. §15."""
    data = http.get_json(BTC_PRICES, {"span": days, "period": "1d"}, ttl=1800)
    pts = (data.get("coins") or {}).get("coingecko:bitcoin", {}).get("prices") or []
    return [(int(p["timestamp"]), float(p["price"])) for p in pts]


def fear_greed(limit=0):
    """[(unix_ts, value 0-100, label)] daily Crypto Fear & Greed (BTC-centred), oldest first. limit=0 = since 2018."""
    data = http.get_json(FNG, {"limit": limit, "format": "json"}, ttl=3600)
    out = [(int(x["timestamp"]), int(x["value"]), x.get("value_classification") or "") for x in data.get("data") or []]
    return sorted(out)


def protocols(ov):
    """slug -> (name, category, group) for the protocols we keep (the groups above)."""
    out = {}
    for p in ov.get("protocols") or []:
        g = GROUPS.get(p.get("category"))
        if g and p.get("slug"):
            out[p["slug"]] = (p.get("displayName") or p.get("name"), p.get("category"), g)
    return out


def label(slug, name=None):
    return ALIAS.get(slug) or name or slug
