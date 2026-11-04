""""Aktivni" (active older tokens): a demo entry source that is NOT the newest DexScreener listings.

Nicholas 4.11.: tokens that were just listed at ~$5k market cap are very likely rug pulls. Better: every day take
the tokens with the most buys and sells that are already older than 3-4 days, i.e. tokens that survived the first
days and for some reason started trading again.

Source: GeckoTerminal's free API, Solana pools sorted by 24 h transaction count (network-wide plus the main memecoin
DEXes), refreshed every `refresh_h` hours in run_paper's own thread. Filters: pool at least `min_age_d` days old,
market cap inside [min_mcap, max_mcap], real liquidity, enough distinct buyers (bot volume has thousands of trades
from a handful of wallets), no SOL/stablecoins/wrapped majors. The list goes to LEARNED_DIR/aktivni.json; the demo
(run_paper.trigger_entries) enters a listed token once a day as entry mode "aktivni", with the same rug gate,
session stake and learned exits as every other entry, and measures it as its own strategy.
"""
import datetime as dt
import json
import os
import time

from learn import weights as _w

DEFAULT = {"enabled": True, "refresh_h": 6, "min_age_d": 3, "min_mcap": 50000, "max_mcap": 20000000,
           "min_liq": 15000, "min_buyers": 300, "min_tx": 2000, "keep": 30, "size_usd": 20, "max_open": 15,
           "max_per_day": None, "max_h1_up": 0.4, "min_h1_down": -0.15, "min_pace": 0.6,
           "dexes": ["pumpswap", "raydium", "meteora"], "pages_all": 3, "pages_dex": 3, "gap_s": 2.5}
# never memecoins: SOL, USDC, USDT, wrapped BTC/ETH and the big liquid-staking tokens
SKIP = {"So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh",
        "cbbtcf3aa214zXHbiAZQwf4122FBYbraNdFqgw4iMij", "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs",
        "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So", "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",
        "jupSoLaHXQiZZTSfEWMTRRgpnyFm8f6sZdosWBjx93v", "USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB",
        "2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo", "USDSwr9ApdHk5bvJKMjzff41FfuX8bSxdKcR81vTwcA"}


def config(cfg):
    return {**DEFAULT, **((cfg or {}).get("aktivni") or {})}


def path():
    return os.path.join(_w.LEARNED_DIR, "aktivni.json")


def load():
    try:
        with open(path()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(st):
    os.makedirs(os.path.dirname(path()), exist_ok=True)
    tmp = path() + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, ensure_ascii=False)
    os.replace(tmp, path())


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _age_d(created, now):
    try:
        return (now - dt.datetime.fromisoformat((created or "").replace("Z", "+00:00")).timestamp()) / 86400
    except ValueError:
        return None


def parse(pools, now):
    """GeckoTerminal pool records -> one row per base token (its busiest pool), unfiltered."""
    out = {}
    for p in pools or []:
        a = p.get("attributes") or {}
        try:
            mint = p["relationships"]["base_token"]["data"]["id"].split("_", 1)[1]
        except (KeyError, TypeError, IndexError, AttributeError):
            continue
        tx = (a.get("transactions") or {})
        d, h1, h6 = tx.get("h24") or {}, tx.get("h1") or {}, tx.get("h6") or {}
        n24 = (d.get("buys") or 0) + (d.get("sells") or 0)
        row = {"mint": mint, "symbol": (a.get("name") or "").split(" / ")[0][:20], "pool": a.get("address"),
               "age_d": _age_d(a.get("pool_created_at"), now), "tx24": n24,
               "buys24": d.get("buys") or 0, "sells24": d.get("sells") or 0, "buyers24": d.get("buyers") or 0,
               "tx1": (h1.get("buys") or 0) + (h1.get("sells") or 0), "tx6": (h6.get("buys") or 0) + (h6.get("sells") or 0),
               "mcap": _f(a.get("market_cap_usd")) or _f(a.get("fdv_usd")), "liq": _f(a.get("reserve_in_usd")),
               "price": _f(a.get("base_token_price_usd")),
               "ch1": _f((a.get("price_change_percentage") or {}).get("h1")) / 100,
               "ch24": _f((a.get("price_change_percentage") or {}).get("h24")) / 100}
        old = out.get(mint)
        if old:  # the token's oldest pool tells its age, the busiest one its activity
            if row["age_d"] is not None and (old["age_d"] is None or row["age_d"] > old["age_d"]):
                old["age_d"] = row["age_d"]
            if n24 <= old["tx24"]:
                continue
            row["age_d"] = old["age_d"]
        out[mint] = row
    return list(out.values())


def why_not(r, c):
    """Reason (plain Croatian) a busy token is not taken into the list, or None."""
    if r["mint"] in SKIP:
        return "SOL / stablecoin / wrapped"
    if r["age_d"] is None or r["age_d"] < c["min_age_d"]:
        return f"mlađi od {c['min_age_d']} dana"
    if r["mcap"] < c["min_mcap"]:
        return "market cap premali"
    if r["mcap"] > c["max_mcap"]:
        return "market cap prevelik"
    if r["liq"] < c["min_liq"]:
        return "likvidnost premala"
    if r["buyers24"] < c["min_buyers"]:
        return "premalo različitih kupaca (botovski volumen)"
    if r["tx24"] < c["min_tx"]:
        return "premalo kupnji i prodaja"
    if r["price"] >= 1 and not r["mint"].endswith("pump"):
        return "cijena iznad 1 $ (tokenizirana dionica ili wrapped)"
    return None


def pick(rows, c):
    """Rows that pass, busiest first, at most c['keep']."""
    ok = [r for r in rows if not why_not(r, c)]
    return sorted(ok, key=lambda r: -r["tx24"])[:c["keep"]]


class _Never(Exception):
    pass


def fetch(c, get=None):
    """All pool pages; stops early (keeps what it has) when GeckoTerminal says the free minute is used up."""
    if get is None:
        from dugo import sources
        get, busy = (lambda p: sources._gecko(p, c["gap_s"])), sources.GeckoBusy
    else:
        busy = _Never
    paths = [f"/pools?page={i}&sort=h24_tx_count_desc" for i in range(1, c["pages_all"] + 1)]
    for d in c["dexes"]:
        paths += [f"/dexes/{d}/pools?page={i}&sort=h24_tx_count_desc" for i in range(1, c["pages_dex"] + 1)]
    pools, ok, busy_n = [], 0, 0
    for p in paths:
        try:
            pools += (get(p) or {}).get("data") or []
            ok += 1
        except busy:
            busy_n += 1
            if busy_n >= 4:
                break
            time.sleep(30)
        except Exception:  # noqa: BLE001 - a missing dex or a bad page must not lose the rest
            pass
    return pools, ok / len(paths)


def refresh(cfg=None, now=None, get=None, force=False):
    """New list if the stored one is older than refresh_h; returns the state dict."""
    c = config(cfg)
    now = now or time.time()
    st = load()
    if not c["enabled"] or (not force and now - st.get("ts", 0) < c["refresh_h"] * 3600):
        return st
    pools, share = fetch(c, get)
    rows = parse(pools, now)
    # GeckoTerminal down or its free minute used up (the KOL module shares it): keep the old list while it is still
    # usable and try again in an hour; a half-fetched list is used only when there is nothing better
    if not rows or (share < 0.5 and st.get("tokens") and now - st.get("ts", 0) < 2 * c["refresh_h"] * 3600):
        st["tried"] = int(now)
        _save(st)
        return st
    picked = pick(rows, c)
    st = {"ts": int(now), "n_seen": len(rows), "tokens": picked,
          "skipped": {k: sum(1 for r in rows if why_not(r, c) == k) for k in {why_not(r, c) for r in rows} if k}}
    _save(st)
    return st


def due(st, c, now):
    """Is the stored list too old (or never fetched / last failure more than an hour ago)?"""
    if now - st.get("ts", 0) < c["refresh_h"] * 3600:
        return False
    return now - st.get("tried", 0) >= 3600


def wanted(cfg, now=None, st=None):
    """{mint: info} of listed tokens, while the list is fresh (at most 2 x refresh_h old)."""
    c = config(cfg)
    if not c["enabled"]:
        return {}
    now = now or time.time()
    st = st if st is not None else load()
    if now - st.get("ts", 0) > 2 * c["refresh_h"] * 3600:
        return {}
    return {r["mint"]: {"score": None, "symbol": r.get("symbol"), "age_d": r.get("age_d"), "tx24": r["tx24"],
                        "buyers24": r.get("buyers24")} for r in st.get("tokens") or []}


def live_check(pair, c):
    """Reason (plain Croatian) not to enter now, from the token's live DexScreener pair, or None. It must still trade
    at a decent pace (last hour >= min_pace x its 24 h hourly average) and its last hour must be neither a pump we
    would buy the top of (the "kasni ulaz" loss) nor a dump."""
    if not pair:
        return "nema živih podataka"
    tx = pair.get("txns") or {}
    h1 = (tx.get("h1") or {}).get("buys", 0) + (tx.get("h1") or {}).get("sells", 0)
    h24 = (tx.get("h24") or {}).get("buys", 0) + (tx.get("h24") or {}).get("sells", 0)
    pace = h1 / (h24 / 24) if h24 else 0
    ch1 = _f((pair.get("priceChange") or {}).get("h1")) / 100
    if pace < c["min_pace"]:
        return f"aktivnost pala: zadnji sat {pace:.0%} prosjeka dana"
    if ch1 > c["max_h1_up"]:
        return f"već skočio {ch1:+.0%} u zadnjem satu (kasni ulaz)"
    if ch1 < c["min_h1_down"]:
        return f"pada {ch1:+.0%} u zadnjem satu"
    return None


def live_pairs(mints):
    """mint -> its deepest DexScreener pair (txns, priceChange), {} on error. Cached 60 s by the client."""
    try:
        from dexscreener import client
        pairs = client.tokens("solana", list(mints))
    except Exception:  # noqa: BLE001
        return {}
    best = {}
    for p in pairs:
        t, liq = p["baseToken"]["address"], (p.get("liquidity") or {}).get("usd") or 0
        if liq >= ((best.get(t) or {}).get("liquidity") or {}).get("usd", -1):
            best[t] = p
    return best
