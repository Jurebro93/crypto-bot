"""Pure functions that turn Helius / RugCheck / DexScreener data into rug signals.

No network here, so every rule is testable on fixtures (tests/test_rug_offline.py).
Amounts are token units unless the name says SOL or USD.
"""
import statistics
from collections import Counter, defaultdict

WSOL = "So11111111111111111111111111111111111111112"
QUOTES = {WSOL, "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}

BUNDLE_SLOTS = 0       # buys in the creation slot itself
SNIPER_SLOTS = 20      # ~8 s after creation
FRESH_DAYS = 3         # wallet first seen this close to its first buy = fresh
MIN_FUNDING_SOL = 0.005


# --- trades ----------------------------------------------------------------------------------

def find_creation(txs, mint):
    """The CREATE transaction of this mint from oldest-first history (else the first one touching it)."""
    for t in txs:
        if t.get("type") == "CREATE":
            return t
    for t in txs:
        if any(tt.get("mint") == mint for tt in t.get("tokenTransfers", [])):
            return t
    return txs[0] if txs else None


def curve_accounts(create_tx, mint):
    """Accounts that hand out the new mint in the CREATE transaction: the bonding curve."""
    if not create_tx:
        return set()
    return {tt["fromUserAccount"] for tt in create_tx.get("tokenTransfers", [])
            if tt.get("mint") == mint and tt.get("fromUserAccount") and tt["fromUserAccount"] != create_tx.get("feePayer")}


def _net_flows(tx, mint):
    net = defaultdict(float)
    for tt in tx.get("tokenTransfers", []):
        if tt.get("mint") != mint:
            continue
        amt = float(tt.get("tokenAmount") or 0)
        if tt.get("fromUserAccount"):
            net[tt["fromUserAccount"]] -= amt
        if tt.get("toUserAccount"):
            net[tt["toUserAccount"]] += amt
    return {a: v for a, v in net.items() if abs(v) > 1e-9}


def detect_pools(txs, mint, known=(), min_share=0.3, min_txs=10):
    """Pool / bonding-curve accounts: the known ones plus any account on the other side of most trades."""
    pools = set(a for a in known if a)
    seen = Counter()
    n = 0
    for t in txs:
        flows = _net_flows(t, mint)
        if len(flows) >= 2:
            n += 1
            seen.update(flows.keys())
    if n >= min_txs:
        pools |= {a for a, c in seen.items() if c / n >= min_share}
    return pools


def trades(txs, mint, pools):
    """One row per wallet per transaction: buy (got tokens from a pool), sell (sent to a pool) or transfer."""
    out = []
    for t in txs:
        if t.get("transactionError"):
            continue
        flows = _net_flows(t, mint)
        via_pool = any(a in pools for a in flows)
        for wallet, v in flows.items():
            if wallet in pools:
                continue
            side = ("buy" if v > 0 else "sell") if via_pool else ("in" if v > 0 else "out")
            out.append({"sig": t.get("signature"), "slot": t.get("slot", 0), "ts": t.get("timestamp", 0),
                        "wallet": wallet, "signer": t.get("feePayer"), "side": side, "amount": abs(v),
                        "sol": _sol_moved(t, wallet)})
    return out


def _sol_moved(tx, wallet):
    sol = sum(n["amount"] for n in tx.get("nativeTransfers", [])
              if wallet in (n.get("fromUserAccount"), n.get("toUserAccount"))) / 1e9
    sol += sum(float(tt.get("tokenAmount") or 0) for tt in tx.get("tokenTransfers", [])
               if tt.get("mint") == WSOL and wallet in (tt.get("fromUserAccount"), tt.get("toUserAccount")))
    return round(sol, 6)


def created_mints(create_txs, dev):
    """Mints a dev wallet created (from its CREATE transactions)."""
    mints = []
    for t in create_txs:
        cands = [tt["mint"] for tt in t.get("tokenTransfers", []) if tt.get("mint") not in QUOTES]
        cands += [a.get("mint") for a in _balance_changes(t) if a.get("mint") not in QUOTES]
        cands = [c for c in cands if c]
        if cands:
            pump = [c for c in cands if c.endswith("pump")]
            mints.append((pump or cands)[0])
    return list(dict.fromkeys(mints))


def _balance_changes(tx):
    for acc in tx.get("accountData", []):
        yield from acc.get("tokenBalanceChanges", [])


# --- launch: dev, bundle, snipers -------------------------------------------------------------

def launch(early_txs, mint, supply, pools):
    """Creator, bundle (same slot as creation) and snipers (first ~8 s) with their share of supply."""
    create = find_creation(early_txs, mint)
    if not create:
        return {}
    dev, slot0, ts0 = create.get("feePayer"), create.get("slot", 0), create.get("timestamp", 0)
    rows = [r for r in trades(early_txs, mint, pools) if r["side"] == "buy"]
    dev_buy = sum(r["amount"] for r in rows if r["wallet"] == dev and r["slot"] - slot0 <= SNIPER_SLOTS)
    bundle, snipers = defaultdict(float), defaultdict(float)
    for r in rows:
        if r["wallet"] == dev:
            continue
        if r["slot"] - slot0 <= BUNDLE_SLOTS:
            bundle[r["wallet"]] += r["amount"]
        elif r["slot"] - slot0 <= SNIPER_SLOTS:
            snipers[r["wallet"]] += r["amount"]
    pct = lambda x: round(100 * x / supply, 2) if supply else 0.0
    first_buyers = list(dict.fromkeys(r["wallet"] for r in sorted(rows, key=lambda r: (r["slot"], r["ts"]))
                                      if r["wallet"] != dev))
    return {
        "dev": dev, "created_slot": slot0, "created_ts": ts0, "platform": create.get("source"),
        "dev_initial_pct": pct(dev_buy),
        "bundle_wallets": len(bundle), "bundle_pct": pct(sum(bundle.values())),
        "sniper_wallets": len(snipers), "sniper_pct": pct(sum(snipers.values())),
        "bundle": {w: pct(a) for w, a in bundle.items()}, "snipers": {w: pct(a) for w, a in snipers.items()},
        "first_buyers": first_buyers,
    }


def dev_sold(tx_samples, mint, dev, pools):
    """Tokens the dev sent away (sold or moved) in the samples we have."""
    rows = [r for txs in tx_samples for r in trades(txs, mint, pools) if r["wallet"] == dev]
    sigs = set()
    sold = moved = 0.0
    for r in rows:
        if r["sig"] in sigs:
            continue
        sigs.add(r["sig"])
        if r["side"] == "sell":
            sold += r["amount"]
        elif r["side"] == "out":
            moved += r["amount"]
    return sold, moved


# --- wallets: age, funder, clusters -----------------------------------------------------------

def wallet_profile(wallet, first_txs):
    """First-seen time and the wallet that sent it its first SOL."""
    if not first_txs:
        return {"wallet": wallet, "first_ts": None, "funder": None, "funding_sol": 0}
    funder, amount = None, 0.0
    for t in first_txs:
        for n in t.get("nativeTransfers", []):
            if n.get("toUserAccount") == wallet and n.get("fromUserAccount") not in (None, wallet) \
                    and n.get("amount", 0) / 1e9 >= MIN_FUNDING_SOL:
                funder, amount = n["fromUserAccount"], n["amount"] / 1e9
                break
        if funder:
            break
    return {"wallet": wallet, "first_ts": first_txs[0].get("timestamp"), "funder": funder,
            "funding_sol": round(amount, 4)}


def is_fresh(profile, at_ts):
    return bool(profile.get("first_ts") and at_ts and at_ts - profile["first_ts"] < FRESH_DAYS * 86400)


def clusters(profiles, dev=None, hubs=()):
    """Group wallets that share a funder, were funded by each other, or by the dev. Hubs (exchanges) don't link."""
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    wallets = {p["wallet"] for p in profiles}
    for p in profiles:
        find(p["wallet"])
        f = p.get("funder")
        if not f or f in hubs:
            continue
        union(p["wallet"], f if f in wallets or f == dev else f"funder:{f}")
    groups = defaultdict(set)
    for w in wallets | ({dev} if dev in parent else set()):
        groups[find(w)].add(w)
    return [sorted(g) for g in groups.values() if len(g) > 1]


def cluster_share(groups, holding_pct, early_pct):
    """Largest cluster by current holding and by early-buy share of supply."""
    best = {"wallets": [], "holding_pct": 0.0, "early_pct": 0.0}
    for g in groups:
        h = round(sum(holding_pct.get(w, 0) for w in g), 2)
        e = round(sum(early_pct.get(w, 0) for w in g), 2)
        if max(h, e) > max(best["holding_pct"], best["early_pct"]):
            best = {"wallets": g, "holding_pct": h, "early_pct": e}
    return best


# --- organic volume vs wash trading -----------------------------------------------------------

def volume_quality(rows):
    """Wash / bot signals over a window of recent trades (buy/sell rows from trades())."""
    rows = [r for r in rows if r["side"] in ("buy", "sell")]
    if not rows:
        return {"trades": 0}
    by_wallet = defaultdict(list)
    for r in rows:
        by_wallet[r["wallet"]].append(r)
    total = sum(r["amount"] for r in rows) or 1
    vol = {w: sum(r["amount"] for r in rs) for w, rs in by_wallet.items()}
    top5 = sum(sorted(vol.values(), reverse=True)[:5]) / total
    both = {w for w, rs in by_wallet.items() if {"buy", "sell"} <= {r["side"] for r in rs}}
    round_trip = sum(vol[w] for w in both) / total
    sizes = Counter(f"{r['side']}:{r['amount']:.3g}" for r in rows)
    repeated = sum(c for c in sizes.values() if c >= 3) / len(rows)
    bot_vol = 0.0
    bots = []
    for w, rs in by_wallet.items():
        ts = sorted(r["ts"] for r in rs)
        gaps = [b - a for a, b in zip(ts, ts[1:]) if b > a]
        if len(gaps) >= 4 and statistics.mean(gaps) > 0 and statistics.pstdev(gaps) / statistics.mean(gaps) < 0.3:
            bot_vol += vol[w]
            bots.append(w)
    span = max(r["ts"] for r in rows) - min(r["ts"] for r in rows)
    buys = sum(1 for r in rows if r["side"] == "buy")
    return {
        "trades": len(rows), "wallets": len(by_wallet), "span_min": round(span / 60, 1),
        "trades_per_wallet": round(len(rows) / len(by_wallet), 2),
        "top5_volume_pct": round(100 * top5, 1), "round_trip_volume_pct": round(100 * round_trip, 1),
        "repeated_size_pct": round(100 * repeated, 1), "bot_timing_volume_pct": round(100 * bot_vol / total, 1),
        "bot_wallets": bots[:10], "buy_ratio": round(buys / len(rows), 2),
    }


def wash_score(vq):
    """0 = organic, 100 = almost certainly fake volume."""
    if not vq.get("trades"):
        return None
    s = 0.0
    s += min(30, max(0, vq["round_trip_volume_pct"] - 30) * 0.6)
    s += min(25, max(0, vq["top5_volume_pct"] - 35) * 0.5)
    s += min(20, max(0, vq["repeated_size_pct"] - 10) * 0.5)
    s += min(15, vq["bot_timing_volume_pct"] * 0.3)
    s += min(10, max(0, vq["trades_per_wallet"] - 3) * 2)
    return round(min(100, s), 1)
