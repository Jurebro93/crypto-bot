"""The list "veliki" (15.11., owner: "Useless, Troll i slično ... hvataj range velikih tokena"): established Solana
memecoins, refreshed by run_veliki.py list (after a deploy, then every 3 h; the candidates' numbers from DexScreener,
free).

Candidates (no paid call): Jupiter's token lists (toptraded / toporganicscore / toptrending 24 h, free and keyless as
rangedca/market reads them: MC, liquidity aggregated over every pool, tags), dugo.db tokens (the long-term survivors
layer, its own MC / liquidity), dugo/config.json "uzori" + "temelj", GeckoTerminal's busiest Solana pools (2 pages by
24 h volume, the shared GeckoTerminal budget), and the owner's seeds SEEDS (USELESS, TROLL).
Seeds resolve to the REAL mint (resolve()): DexScreener search by ticker, only Solana pairs whose base symbol is the
ticker exactly, grouped by mint; a group whose pools are fake (liquidity >= half its MC, the copycat that shows $100M
"liquidity" with a $1 day volume) or dead (24 h volume < SEED_MIN_VOL) is refused; among the rest the mint with the
most REAL liquidity wins (ties: the older first pair). dugo/config's mint for the same ticker is checked against it;
the log says which mint, why, and what was refused.
Rules (every candidate, the seeds included): MC >= MIN_MCAP ($20M), liquidity >= MIN_LIQ ($500k: Jupiter's over every
pool, else DexScreener's sum of the real pools; the routed swap uses them all) with the deepest pool >= MIN_DEEP
($100k) and the pools under half the MC, 24 h volume >= MIN_VOL ($500k), the oldest pair >= MIN_AGE_D (14 d), the
deepest pool an AMM (never a bonding curve: rangedca/market.CURVE_DEX), not in the rug archive, a memecoin (Jupiter's
tag "meme" when Jupiter lists the token; else not a stable / LST / wrapped / platform token, NON_MEME). Ranked by 24 h
volume (seeds first), at most MAX_LIST (20). The cost model uses the deepest pool's liquidity (conservative).
"""
import json
import os
import re
import time

# 15.11. popodne (owner: "MC 5-150M, ne iznad (PENGU / PUMP), ne ispod 5M, starije od 15 dana; velika lista"): the
# midcaps. The list (demo, analysis) needs liquidity >= MIN_LIQ ($150k); a REAL buy needs REAL_MIN_LIQ ($500k, live.py)
MIN_MCAP = float(os.environ.get("VEL_MIN_MCAP", "5000000"))
MAX_MCAP = float(os.environ.get("VEL_MAX_MCAP", "150000000"))
MIN_LIQ = float(os.environ.get("VEL_MIN_LIQ", "150000"))
REAL_MIN_LIQ = float(os.environ.get("VEL_REAL_MIN_LIQ", "500000"))
MIN_VOL = float(os.environ.get("VEL_MIN_VOL", "100000"))
MIN_DEEP = float(os.environ.get("VEL_MIN_DEEP", "50000"))
JUP_URL = "https://lite-api.jup.ag/tokens/v2"
JUP_LISTS = ("toptraded/24h", "toporganicscore/24h", "toptrending/24h", "toptraded/6h", "toporganicscore/6h",
             "toptrending/6h")
JUP_NOT_MEME = frozenset(("stocks", "rwa", "lst", "defi", "equities", "xstocks", "stablecoin"))
MIN_AGE_D = float(os.environ.get("VEL_MIN_AGE_D", "15"))
MAX_LIST = int(os.environ.get("VEL_MAX_LIST", "200"))
MAX_HISTORY = int(os.environ.get("VEL_MAX_HISTORY", "40"))
SEEDS = ("ANSEM", "TROLL", "GOODGUY", "CHILLGUY", "FARTCOIN", "USELESS")   # the owner's examples (Good Guy, Chill Guy...)
SEED_MIN_VOL = 50_000
FAKE_LIQ_MCAP = 0.5
GT_PAGES = 4
NON_MEME = frozenset(s.upper() for s in (
    "SOL", "WSOL", "USDC", "USDT", "PYUSD", "USDS", "USDE", "USDG", "FDUSD", "EURC", "USD1", "JUP", "JTO", "RAY", "PYTH",
    "W", "JLP", "ORCA", "DRIFT", "KMNO", "TNSR", "HNT", "RENDER", "MSOL", "JITOSOL", "BSOL", "JUPSOL", "INF", "HSOL",
    "WBTC", "CBBTC", "ZBTC", "ETH", "WETH", "PUMP", "MET", "MPLX", "CLOUD", "ZEUS", "GRASS", "IO", "NOS", "SONIC",
    "BIO", "MEW_LP", "SAROS", "FIDA", "MNDE", "BLZE", "STEP", "SBR", "PRCL", "ZEX", "DBR", "HONEY", "MOBILE", "SHDW",
    "XBTC", "TBTC", "LBTC", "SYRUPUSDC", "SUSD", "XAUT", "PAXG", "BNSOL", "DSOL", "VSOL", "STSOL", "LAYER", "ME",
    "KAITO", "VIRTUAL", "AI16Z", "ACT", "DEEP", "XYO"))
_NON_MEME_RX = re.compile(r"(USD|BTC|ETH|SOL)$")
_STOCK_RX = re.compile(r"^[A-Z]{1,5}x$")   # tokenized shares (xStocks: TSLAx, NVDAx)
_NON_MEME_NAME = re.compile(r"xstock|tokenized|wrapped|staked|bridged|liquid staking", re.I)


def _f(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def non_meme(sym, name=None):
    s = (sym or "").upper().strip()
    if s in NON_MEME:
        return True
    if s not in SEEDS and _NON_MEME_RX.search(s) and len(s) <= 8:
        return True
    if _STOCK_RX.match((sym or "").strip()):
        return True
    return bool(name and _NON_MEME_NAME.search(name))


def group(pairs):
    """{mint: {"symbol", "name", "liq" (sum of the real pools), "deep" (the deepest pool), "mcap", "vol24",
    "created_ts", "dexes"}} of DexScreener pairs (Solana only)."""
    out = {}
    for p in pairs or []:
        if (p.get("chainId") or "solana") != "solana":
            continue
        b = p.get("baseToken") or {}
        m = b.get("address")
        if not m:
            continue
        g = out.setdefault(m, {"mint": m, "symbol": b.get("symbol"), "name": b.get("name"), "liq": 0.0, "deep": None,
                               "mcap": 0.0, "vol24": 0.0, "created_ts": None, "dexes": set(), "pairs": 0})
        lq = _f((p.get("liquidity") or {}).get("usd")) or 0.0
        g["liq"] += lq
        g["vol24"] += _f((p.get("volume") or {}).get("h24")) or 0.0
        if g["deep"] is None or lq > (_f((g["deep"].get("liquidity") or {}).get("usd")) or 0.0):
            g["mcap"] = _f(p.get("marketCap") or p.get("fdv")) or 0.0   # the deepest pool's MC (one pool's can be wrong)
        c = p.get("pairCreatedAt")
        if c:
            c = int(c) // 1000 if int(c) > 10 ** 11 else int(c)
            g["created_ts"] = min(g["created_ts"] or c, c)
        g["dexes"].add(p.get("dexId") or "?")
        g["pairs"] += 1
        if g["deep"] is None or lq > (_f((g["deep"].get("liquidity") or {}).get("usd")) or 0.0):
            g["deep"] = p
    return out


def fake_why(g):
    """Why this mint's pools are not real (a copycat / fake pool / dead), else None."""
    if g["mcap"] and g["liq"] >= FAKE_LIQ_MCAP * g["mcap"]:
        return (f"lažni pool: likvidnost ${g['liq'] / 1e6:,.1f}M ≥ pola MC-a ${g['mcap'] / 1e6:,.1f}M, volumen 24 h "
                f"${g['vol24']:,.0f}")
    if g["vol24"] < SEED_MIN_VOL:
        return f"mrtav: volumen 24 h ${g['vol24']:,.0f}"
    return None


def resolve(ticker, pairs, known=None):
    """(mint or None, how: Croatian text, refused: [(mint, why)]) - the REAL token behind a ticker among DexScreener
    search pairs: exact symbol, Solana, fake / dead pools refused, the most real liquidity (ties: the older)."""
    t = ticker.upper().lstrip("$")
    gs = {m: g for m, g in group(pairs).items() if (g["symbol"] or "").upper().strip() == t}
    refused, ok = [], []
    for m, g in gs.items():
        why = fake_why(g)
        if why:
            refused.append((m, why))
        else:
            ok.append(g)
    if not ok:
        return None, f"{t}: nijedan od {len(gs)} tokena s tim tickerom nema pravi pool", refused
    ok.sort(key=lambda g: (-g["liq"], g["created_ts"] or 10 ** 11))
    best = ok[0]
    how = (f"{t}: {best['mint']} - najveća prava likvidnost ${best['liq'] / 1e6:,.2f}M (MC ${best['mcap'] / 1e6:,.1f}M, "
           f"volumen 24 h ${best['vol24'] / 1e6:,.2f}M, {best['pairs']} poolova: {', '.join(sorted(best['dexes']))}) od "
           f"{len(gs)} tokena istog tickera")
    if refused:
        how += "; odbačeni: " + "; ".join(f"{m[:6]}… ({w})" for m, w in refused[:4])
    if len(ok) > 1:
        how += f"; manji: " + ", ".join(f"{g['mint'][:6]}… ${g['liq'] / 1e3:,.0f}k" for g in ok[1:4])
    if known:
        how += "; isti kao dugo/config" if known == best["mint"] else f"; dugo/config ima {known[:6]}… (zamijenjen)"
    return best["mint"], how, refused


def liq_of(g):
    """(liquidity for the floor: Jupiter's over every pool, else the DexScreener sum; the deepest pool's)."""
    deep = _f(((g.get("deep") or {}).get("liquidity") or {}).get("usd")) or 0.0
    return (_f((g.get("jup") or {}).get("liq")) or g.get("liq") or 0.0), deep


def vol_of(g):
    """24 h volume: the larger of DexScreener's (its top pools) and Jupiter's (every venue)."""
    return max(g.get("vol24") or 0.0, _f((g.get("jup") or {}).get("vol24")) or 0.0)


def judge(g, now, archived=frozenset(), curve_dex=()):
    """Why this candidate is not on the list (Croatian), else None."""
    deep = g.get("deep") or {}
    dex = (deep.get("dexId") or "").lower()
    lq, ld = liq_of(g)
    tags = set((g.get("jup") or {}).get("tags") or ())
    if g["mint"] in archived:
        return "u arhivi rugova"
    if non_meme(g.get("symbol"), g.get("name")) or tags & JUP_NOT_MEME:
        return "nije memecoin (stable / LST / platforma / dionica)"
    if g.get("jup") and "meme" not in tags:
        return "Jupiter ga ne označava kao meme"
    if dex in curve_dex or "pump.fun" in dex or dex == "pumpfun":
        return "najdublji pool je krivulja (uzimaju se bondani)"
    if g["mcap"] < MIN_MCAP:
        return f"MC ${g['mcap'] / 1e6:,.1f}M ispod ${MIN_MCAP / 1e6:,.0f}M"
    if g["mcap"] > MAX_MCAP:
        return f"MC ${g['mcap'] / 1e6:,.0f}M iznad ${MAX_MCAP / 1e6:,.0f}M"
    if lq < MIN_LIQ:
        return f"likvidnost ${lq / 1e3:,.0f}k ispod ${MIN_LIQ / 1e3:,.0f}k"
    if ld < MIN_DEEP:
        return f"najdublji pool ${ld / 1e3:,.0f}k ispod ${MIN_DEEP / 1e3:,.0f}k"
    if g["liq"] >= FAKE_LIQ_MCAP * g["mcap"]:
        return "lažni pool (likvidnost ≥ pola MC-a)"
    if vol_of(g) < MIN_VOL:
        return f"volumen 24 h ${vol_of(g) / 1e3:,.0f}k ispod ${MIN_VOL / 1e3:,.0f}k"
    created = min([x for x in (g.get("created_ts"), (g.get("jup") or {}).get("created_ts")) if x] or [None]) \
        if (g.get("created_ts") or (g.get("jup") or {}).get("created_ts")) else None
    age = (now - created) / 86400 if created else None
    if age is None or age < MIN_AGE_D:
        return f"premlad ({age or 0:.0f} d, treba {MIN_AGE_D:.0f})"
    return None


def row_of(g, now, seed=False, how=None):
    deep = g.get("deep") or {}
    return {"mint": g["mint"], "symbol": (g.get("symbol") or "").strip() or g["mint"][:6], "name": g.get("name"), "pool": deep.get("pairAddress"),
            "dex": deep.get("dexId"), "url": deep.get("url"), "mcap": round(g["mcap"]),
            "liq": round(_f((deep.get("liquidity") or {}).get("usd")) or 0), "liq_total": round(liq_of(g)[0]),
            "vol24": round(vol_of(g)), "age_d": round((now - g["created_ts"]) / 86400, 1) if g.get("created_ts") else None,
            "created_ts": g.get("created_ts"), "seed": 1 if seed else 0, "how": how}


def select(groups, now, seeds=(), archived=frozenset(), curve_dex=(), cap=MAX_LIST):
    """(rows, refused {mint: why}) - the list from {mint: group}; seeds (mints) first, then by 24 h volume."""
    ok, refused = [], {}
    for m, g in groups.items():
        why = judge(g, now, archived, curve_dex)
        if why:
            refused[m] = (g.get("symbol"), why)
        else:
            ok.append(g)
    ok.sort(key=lambda g: (0 if g["mint"] in seeds else 1, -vol_of(g)))
    return ok[:cap], refused


# ---------- the candidates (I/O) -------------------------------------------------------------------------------------

def _dugo_candidates():
    """{mint: symbol} from dugo.db (MC >= MIN_MCAP / 2 by its own last numbers) and dugo/config.json."""
    out = {}
    try:
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, "dugo", "config.json")) as f:
            cfg = json.load(f)
        for k in ("uzori", "temelj"):
            for sym, m in (cfg.get(k) or {}).items():
                out[m] = sym
    except (OSError, ValueError):
        pass
    try:
        from dugo import store as dstore
        con = dstore.ro()
        if con is not None:
            try:
                for r in con.execute("SELECT mint, symbol FROM tokens WHERE COALESCE(mcap, 0) >= ? AND "
                                     "COALESCE(liquidity, 0) >= ?", (MIN_MCAP / 5, 10_000)):
                    out.setdefault(r[0], r[1])
            finally:
                con.close()
    except Exception:  # noqa: BLE001 - no dugo.db yet: the other sources
        pass
    return out


def _gecko_candidates(pages=GT_PAGES):
    """{mint: symbol} of the base tokens of GeckoTerminal's busiest Solana pools (24 h volume)."""
    from veliki import store
    if "gt_pools" in store.FETCH:
        return store.FETCH["gt_pools"](pages)
    out = {}
    from event_calendar import http
    for page in range(1, pages + 1):
        try:
            d = http.get_json(f"{store.GECKO}/pools", {"sort": "h24_volume_usd_desc", "page": page, "include": "base_token"},
                              ttl=3600, headers={"Accept": "application/json"}, retries=0)
        except Exception:  # noqa: BLE001
            d = None
        if not d:
            break
        syms = {x.get("id"): (x.get("attributes") or {}).get("symbol") for x in d.get("included") or []}
        for p in d.get("data") or []:
            bid = (((p.get("relationships") or {}).get("base_token") or {}).get("data") or {}).get("id") or ""
            if bid.startswith("solana_"):
                out[bid[7:]] = syms.get(bid)
    return out


def _iso_ts(s):
    import datetime as dt
    try:
        return int(dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp())
    except (TypeError, ValueError):
        return None


def _jup_candidates():
    """{mint: {"symbol", "tags", "liq", "mcap", "created_ts"}} of Jupiter's 24 h lists with MC >= MIN_MCAP (free)."""
    from veliki import store
    if "jup" in store.FETCH:
        return store.FETCH["jup"]()
    from event_calendar import http
    out = {}
    for name in JUP_LISTS:
        try:
            d = http.get_json(f"{JUP_URL}/{name}", {"limit": 100}, ttl=1800, timeout=10, retries=0)
        except Exception:  # noqa: BLE001
            d = None
        for t in d if isinstance(d, list) else []:
            if not (MIN_MCAP <= (_f(t.get("mcap")) or 0) <= MAX_MCAP * 1.2) or not t.get("id"):
                continue
            st = t.get("stats24h") or {}
            out[t["id"]] = {"symbol": t.get("symbol"), "tags": list(t.get("tags") or []), "liq": _f(t.get("liquidity")),
                            "vol24": (_f(st.get("buyVolume")) or 0.0) + (_f(st.get("sellVolume")) or 0.0),
                            "mcap": _f(t.get("mcap")),
                            "created_ts": _iso_ts((t.get("firstPool") or {}).get("createdAt") or t.get("createdAt"))}
    return out


def _dex_tokens(mints):
    from veliki import store
    if "dex_tokens" in store.FETCH:
        return store.FETCH["dex_tokens"](mints)
    from dexscreener import client
    return client.tokens("solana", list(mints))


def _dex_search(q):
    from veliki import store
    if "dex_search" in store.FETCH:
        return store.FETCH["dex_search"](q)
    from dexscreener import client
    return client.search(q)


def build(now=None, log=print):
    """The list: (rows, meta {"seeds": {ticker: how}, "refused": n, "candidates": n}). Writes nothing."""
    now = int(now or time.time())
    cand = _dugo_candidates()
    known = {s.upper(): m for m, s in cand.items() if s}
    seeds, seed_how = set(), {}
    for t in SEEDS:
        try:
            m, how, _ref = resolve(t, _dex_search(t), known.get(t))
        except Exception as e:  # noqa: BLE001
            m, how = known.get(t), f"{t}: pretraga nije uspjela ({type(e).__name__}), dugo/config {known.get(t)}"
        seed_how[t] = how
        log(f"veliki: sjeme {how}")
        if m:
            seeds.add(m)
            cand[m] = t
            for mm, s in list(cand.items()):   # a dugo/config mint of the same ticker that is not the real one goes
                if mm != m and (s or "").upper() == t:
                    cand.pop(mm, None)
    try:
        g = _gecko_candidates()
        for m, s in g.items():
            cand.setdefault(m, s)
    except Exception as e:  # noqa: BLE001
        log(f"veliki: GeckoTerminal popis poolova nije stigao ({type(e).__name__})")
    try:
        jup = _jup_candidates()
    except Exception as e:  # noqa: BLE001
        jup = {}
        log(f"veliki: Jupiterove liste nisu stigle ({type(e).__name__})")
    for m, j in jup.items():
        if (j.get("symbol") or "").upper() in SEEDS and m not in seeds:
            continue   # a copycat of a seed's ticker
        cand.setdefault(m, j.get("symbol"))
    pairs = _dex_tokens(sorted(cand)) if cand else []
    groups = group(pairs)
    for m, g in groups.items():
        if m in jup:
            g["jup"] = jup[m]
    try:
        from rugfilter import archive
        arch = archive.blocked()
    except Exception:  # noqa: BLE001
        arch = frozenset()
    try:
        from rangedca import market as rmarket
        curve = tuple(rmarket.CURVE_DEX)
    except Exception:  # noqa: BLE001
        curve = ("pumpfun", "pump-fun", "moonshot", "launchlab", "meteora-dbc")
    ok, refused = select(groups, now, seeds, arch, curve)
    rows = [row_of(g, now, g["mint"] in seeds, next((h for t, h in seed_how.items() if g["mint"] in seeds
                                                     and h.startswith(f"{t}: {g['mint']}")), None)
                    or ("sjeme vlasnika" if g["mint"] in seeds else "automatski: MC, likvidnost, volumen, starost"))
            for g in ok]
    oor = []
    for m in seeds:
        if m in refused:
            log(f"veliki: sjeme {refused[m][0]} nije na listi: {refused[m][1]}")
            oor.append(f"{refused[m][0]} ({m[:6]}…): {refused[m][1]}")
    for t, h in seed_how.items():
        if not any(h.startswith(f"{t}: {m}") for m in seeds):
            oor.append(h)
    # survivorship (the critic): the tokens that fell out (MC under the floor, liquidity / volume gone, rugged) are
    # kept for the backtest's point-in-time universe, never traded
    hist = []
    for m, (sym, why) in refused.items():
        g = groups.get(m)
        if not g or not (g.get("deep") or {}).get("pairAddress"):
            continue
        if any(w in why for w in ("ispod", "arhivi", "volumen", "likvidnost", "najdublji")) and "iznad" not in why:
            hist.append(dict(row_of(g, now, False, f"samo povijest: {why}"), dead=1))
    hist.sort(key=lambda r: -(r.get("mcap") or 0))
    return rows, {"seeds": seed_how, "candidates": len(cand), "refused": len(refused), "jupiter": len(jup),
                  "out_of_range": oor, "history": hist[:MAX_HISTORY],
                  "refused_top": sorted(((s, w) for s, w in refused.values() if s), key=lambda x: x[0] or "")[:15]}


def line(rows):
    return (f"veliki: lista: {len(rows)} tokena: " + ", ".join(
        f"{r['symbol']} (MC ${(r['mcap'] or 0) / 1e6:,.0f}M, liq ${(r.get('liq_total') or r['liq'] or 0) / 1e6:,.1f}M)" for r in rows))
