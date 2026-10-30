"""Full rug check of one Solana token: RugCheck + Helius + DexScreener -> report dict.

Helius credit cost per token with defaults: ~5 Enhanced calls (500 credits) + ~25 cheap RPC calls.
"""
import json
import os
import time

from dexscreener import client as dex
from dexscreener.match import summarize

from . import analysis as A
from . import helius, rugcheck
from .score import max_entry_usd, score

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SMART_FILE = os.path.join(HERE, "smart_wallets.json")  # optional: ["wallet", ...] or {"wallet": "label"}
HUB_SOL = 5000
MAX_NETWORK = 50  # RugCheck "networks" bigger than this are routers/aggregators, not one operator
BURN = {"11111111111111111111111111111111", "1nc1nerator11111111111111111111111111111111"}  # a funder holding this much SOL is an exchange/hot wallet: shared funding means nothing


def _try(errors, name, fn, default=None):
    try:
        return fn()
    except Exception as e:  # one dead source must not kill the report
        errors[name] = f"{type(e).__name__}: {e}"
        return default


def _smart_wallets():
    try:
        with open(SMART_FILE) as f:
            data = json.load(f)
        return set(data if isinstance(data, list) else data.keys())
    except (OSError, ValueError):
        return set()


def _registry(wallets):
    """{wallet: (labels, tier)} from the shared wallet registry (wallets/store.py), if it is there."""
    try:
        from wallets import store as wstore
        con = wstore.connect()
    except Exception:
        return {}
    out = {}
    for w in set(wallets):
        row = con.execute("SELECT labels, tier FROM wallets WHERE wallet=?", (w,)).fetchone()
        if row:
            out[w] = (set(json.loads(row[0] or "[]")), row[1])
    con.close()
    return out


def check(mint, wallets=20, early_pages=2, recent_pages=3, now=None):
    now = now or time.time()
    errors = {}
    credits0 = helius.credits_used()
    r = {"mint": mint, "checked_at": int(now)}

    # RugCheck: authorities, holders with owners, markets, insider networks
    rc = _try(errors, "rugcheck", lambda: rugcheck.report(mint), {}) or {}
    tok = rc.get("token") or {}
    decimals = tok.get("decimals")
    supply = (tok.get("supply") or 0) / 10 ** decimals if decimals is not None else 0
    mi = _try(errors, "helius_mint", lambda: helius.mint_info(mint), {}) or {}
    supply = mi.get("supply") or supply
    decimals = mi.get("decimals", decimals) or 0
    r["authorities"] = {"mintAuthority": mi.get("mintAuthority", rc.get("mintAuthority")),
                        "freezeAuthority": mi.get("freezeAuthority", rc.get("freezeAuthority"))}
    r["supply"] = supply
    meta = rc.get("tokenMeta") or {}
    r["symbol"], r["name"] = meta.get("symbol", ""), meta.get("name", "")
    networks = rc.get("insiderNetworks") or []
    raw_supply = supply * 10 ** decimals if supply else 0
    insider_pct = max([100 * (n.get("currentHolding") or n.get("tokenAmount") or 0) / raw_supply
                       for n in networks if (n.get("size") or 0) <= MAX_NETWORK] or [0]) if raw_supply else 0
    r["rugcheck"] = {"score_normalised": rc.get("score_normalised"), "rugged": rc.get("rugged"),
                     "total_holders": rc.get("totalHolders"), "creator": rc.get("creator"),
                     "insider_pct": round(insider_pct, 2), "insiders_detected": rc.get("graphInsidersDetected"),
                     "launchpad": (rc.get("launchpad") or {}).get("name"),
                     "risks": [f"{x.get('name')} ({x.get('level')})" for x in rc.get("risks") or []]}

    # DexScreener: market data and pool addresses
    pairs = _try(errors, "dexscreener", lambda: dex.token_pairs("solana", mint), []) or []
    if pairs:
        best = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd", 0))
        r["market"] = summarize(best, now * 1000)
        r["market"]["max_entry_usd_5pct"] = max_entry_usd(r["market"]["liquidity"])
        r["symbol"] = r["symbol"] or r["market"]["symbol"]

    known_pools = {m.get("pubkey") for m in rc.get("markets") or []} | {p.get("pairAddress") for p in pairs}

    # Helius: launch (oldest txs) and recent trading
    early = _try(errors, "helius_early", lambda: helius.address_txs_pages(mint, early_pages, "asc"), []) or []
    recent = _try(errors, "helius_recent", lambda: helius.address_txs_pages(mint, recent_pages, "desc"), []) or []
    known_pools |= A.curve_accounts(A.find_creation(early, mint), mint)
    pools = A.detect_pools(early + recent, mint, known_pools)
    r["pools"] = sorted(pools)
    L = A.launch(early, mint, supply, pools) if early else {}
    r["launch"] = {k: v for k, v in L.items() if k not in ("bundle", "snipers", "first_buyers")}
    dev = L.get("dev") or rc.get("creator")

    # holders (RugCheck top 20, pools excluded)
    holders = [h for h in rc.get("topHolders") or []
               if h.get("owner") not in pools | BURN and h.get("address") not in pools]
    holding = {h["owner"]: round(h.get("pct", 0), 2) for h in holders if h.get("owner")}
    r["holders"] = {"top10_pct": round(sum(h.get("pct", 0) for h in holders[:10]), 2),
                    "top": [{"wallet": h["owner"], "pct": round(h.get("pct", 0), 2), "insider": h.get("insider")}
                            for h in holders[:10]]}

    # dev wallet
    if dev:
        d = {"wallet": dev}
        creates = _try(errors, "helius_dev_history", lambda: helius.dev_creations(dev), []) or []
        others = [m for m in A.created_mints(creates, dev) if m != mint]
        d["tokens_created"] = len(others) + 1
        alive = _try(errors, "dex_dev_tokens", lambda: dex.tokens("solana", others[:90]), []) if others else []
        alive_set = {p["baseToken"]["address"] for p in alive or [] if (p.get("liquidity") or {}).get("usd", 0) >= 5000}
        d["tokens_alive"] = len(alive_set) + ((r.get("market") or {}).get("liquidity", 0) >= 5000)
        d["history_capped"] = len(creates) >= 100  # only the last 100 creations were read
        d["other_tokens"] = others[:20]
        sold, moved = A.dev_sold([early, recent], mint, dev, pools)
        pct = lambda x: round(100 * x / supply, 2) if supply else 0
        d["sold_pct"], d["moved_pct"] = pct(sold), pct(moved)
        bal = _try(errors, "helius_dev_balance", lambda: helius.token_balance(dev, mint), None)
        d["hold_pct"] = pct(bal) if bal is not None else holding.get(dev, 0)
        r["dev"] = d

    # wallet profiles: dev, first buyers, top holders
    half = max(1, wallets // 2)
    targets = list(dict.fromkeys(([dev] if dev else []) + L.get("first_buyers", [])[:half] + list(holding)[:half]))
    profiles = []
    for w in targets:
        txs = _try(errors, f"wallet {w[:6]}", lambda w=w: helius.wallet_first_txs(w), None)
        if txs is not None:
            profiles.append(A.wallet_profile(w, txs))
    funders = {p["funder"] for p in profiles if p.get("funder")}
    shared = [f for f in funders if sum(p.get("funder") == f for p in profiles) > 1]
    hubs = set()
    for f in shared[:15]:
        bal = _try(errors, f"funder {f[:6]}", lambda f=f: helius.sol_balance(f), 0)
        if bal and bal >= HUB_SOL:
            hubs.add(f)
    groups = A.clusters(profiles, dev, hubs)
    early_pct = {**L.get("bundle", {}), **L.get("snipers", {})}
    if dev:
        early_pct[dev] = L.get("dev_initial_pct", 0)
    cl = A.cluster_share(groups, holding, early_pct)
    dev_group = next((g for g in groups if dev in g), [])
    cl["dev_linked_early"] = len([w for w in dev_group if w != dev and w in L.get("first_buyers", [])])
    cl["clusters"] = len(groups)
    r["cluster"] = cl

    by_w = {p["wallet"]: p for p in profiles}
    t0 = L.get("created_ts") or now
    early_prof = [by_w[w] for w in L.get("first_buyers", [])[:half] if w in by_w]
    hold_prof = [by_w[w] for w in list(holding)[:half] if w in by_w]
    frac = lambda ps: round(100 * sum(A.is_fresh(p, t0) for p in ps) / len(ps), 1) if ps else 0
    r["holders"]["fresh_early_pct"] = frac(early_prof)
    r["holders"]["fresh_holders_pct"] = frac(hold_prof)
    if dev and dev in by_w:
        r["dev"].update({k: by_w[dev][k] for k in ("first_ts", "funder", "funding_sol")})
        r["dev"]["fresh"] = A.is_fresh(by_w[dev], t0)
        f = by_w[dev].get("funder")
        if f and f not in hubs:
            bal = _try(errors, "dev funder", lambda: helius.sol_balance(f), 0)
            if bal and bal >= HUB_SOL:
                hubs.add(f)
        r["dev"]["funder_is_exchange"] = f in hubs
    r["wallets"] = [{**p, "role": _role(p["wallet"], dev, L, holding),
                     "fresh": A.is_fresh(p, t0), "cluster": any(p["wallet"] in g for g in groups)} for p in profiles]

    # what earlier checks and the wallet scorer already know about these wallets
    seen = set(L.get("first_buyers", [])) | set(holding)
    reg = _registry(seen | {dev} | {p["funder"] for p in profiles if p.get("funder")})
    bad = {"rugger", "bundler", "insider"}
    r["known_bad"] = sorted(w for w in seen if reg.get(w, (set(), None))[0] & bad and w != dev)
    if dev:
        dev_funder = (r.get("dev") or {}).get("funder")
        r["dev"]["known_rugger"] = "rugger" in reg.get(dev, (set(), None))[0]
        r["dev"]["funder_known_bad"] = bool(dev_funder and reg.get(dev_funder, (set(), None))[0] & (bad | {"funder_of_rugger"}))
    smart = _smart_wallets() | {w for w, (labels, tier) in reg.items() if tier == "A" and not labels & bad}
    r["smart_wallets"] = sorted(smart & seen)

    # volume quality on the recent window
    rows = A.trades(recent, mint, pools)
    r["volume"] = A.volume_quality(rows)
    r["wash_score"] = A.wash_score(r["volume"])

    r["hubs"] = sorted(hubs)
    r["helius_credits"] = helius.credits_used() - credits0
    r["errors"] = errors
    r.update(score(r))
    return r


def _role(w, dev, L, holding):
    if w == dev:
        return "dev"
    if w in L.get("bundle", {}):
        return "bundler"
    if w in L.get("snipers", {}):
        return "sniper"
    if w in L.get("first_buyers", []):
        return "early_buyer"
    return "holder" if w in holding else "other"
