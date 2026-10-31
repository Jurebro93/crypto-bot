"""Features at a decision point and the outcome after it, from retro.db rows of one token."""
import json
import statistics

SUPPLY = 1e9
SMALL_BUY = 0.05  # SOL; spam/bot sized buys
DAY = 86400


PROTOCOL = {"BwWK17cbHxwWBKZkUYvzxLcNQ1YVyaFezduWbtm2de6s"}


def holdings(trs, exclude=()):
    h = {}
    for r in trs:
        if r["wallet"] in exclude or r["wallet"] in PROTOCOL:
            continue
        h[r["wallet"]] = h.get(r["wallet"], 0.0) + r["tokens"]
    return h


def at(trs, tok, cut, creator_row=None, meta=None, smart=None):
    """Feature dict from trades with ts <= cut. trs are dicts sorted by n."""
    allsub = [r for r in trs if r["ts"] <= cut]
    proto = [r for r in allsub if r["wallet"] in PROTOCOL]
    sub = [r for r in allsub if r["wallet"] not in PROTOCOL]
    t0, slot0 = tok["t_create"], tok["slot_create"]
    creator = tok["creator"]
    buys = [r for r in sub if r["side"] == "buy"]
    sells = [r for r in sub if r["side"] == "sell"]
    buyers = {r["wallet"] for r in buys}
    sellers = {r["wallet"] for r in sells}
    h = holdings(sub)
    pos = sorted((v for w, v in h.items() if v > 1), reverse=True)
    holders_x_dev = sorted((v for w, v in h.items() if v > 1 and w != creator), reverse=True)
    dev_in = sum(r["tokens"] for r in sub if r["wallet"] == creator and r["tokens"] > 0)
    dev_out = -sum(r["tokens"] for r in sub if r["wallet"] == creator and r["tokens"] < 0)
    slot_rows = [r for r in sub if r["slot"] == slot0 and r["tokens"] > 0]
    early_rows = [r for r in sub if r["slot"] is not None and slot0 is not None and r["slot"] - slot0 <= 3 and r["tokens"] > 0]
    buy_sol = [-r["sol"] for r in buys]
    per_wallet = {}
    for r in sub:
        per_wallet[r["wallet"]] = per_wallet.get(r["wallet"], 0) + 1
    last5 = [r for r in buys if r["ts"] > cut - 300]
    prices = [r["price"] for r in sub if r["price"]]
    f = {
        "age_min": (cut - t0) / 60,
        "n_trades": len(sub),
        "n_buys": len(buys),
        "n_sells": len(sells),
        "uniq_buyers": len(buyers),
        "uniq_sellers": len(sellers),
        "sell_buy_ratio": len(sells) / max(1, len(buys)),
        "buy_sol": sum(buy_sol),
        "sell_sol": sum(r["sol"] for r in sells),
        "net_sol": sum(buy_sol) - sum(r["sol"] for r in sells),
        "mcap_sol": (statistics.median(prices[-3:]) * SUPPLY) if prices else None,
        "median_buy_sol": statistics.median(buy_sol) if buy_sol else 0,
        "small_buy_frac": sum(1 for x in buy_sol if x < SMALL_BUY) / max(1, len(buy_sol)),
        "big_buy_frac": sum(1 for x in buy_sol if x >= 2) / max(1, len(buy_sol)),
        "holders": len(pos),
        "top1_pct": 100 * (holders_x_dev[0] if holders_x_dev else 0) / SUPPLY,
        "top10_pct": 100 * sum(pos[:10]) / SUPPLY,
        "dev_buy_pct": 100 * dev_in / SUPPLY,
        "dev_hold_pct": 100 * max(0.0, h.get(creator, 0.0)) / SUPPLY,
        "dev_sold_frac": dev_out / dev_in if dev_in else 0.0,
        "dev_sold_any": 1.0 if dev_out > 1 else 0.0,
        "bundle_wallets": len({r["wallet"] for r in slot_rows}),
        "bundle_pct": 100 * sum(r["tokens"] for r in slot_rows) / SUPPLY,
        "snipe3_wallets": len({r["wallet"] for r in early_rows}),
        "snipe3_pct": 100 * sum(r["tokens"] for r in early_rows) / SUPPLY,
        "churn_frac": len(buyers & sellers) / max(1, len(buyers)),
        "heavy_wallet_frac": sum(1 for v in per_wallet.values() if v >= 5) / max(1, len(per_wallet)),
        "last5_buy_share": len(last5) / max(1, len(buys)),
        # pump.fun's own "mayhem" account trading the token: share of SOL volume that is protocol-made
        "mayhem": 1.0 if proto else 0.0,
        "proto_vol_frac": (sum(abs(r["sol"]) for r in proto) /
                           max(1e-9, sum(abs(r["sol"]) for r in allsub if r["side"] in ("buy", "sell")))),
    }
    if creator_row:
        f["dev_prior_creates"] = creator_row["prior_creates"]
        f["dev_fresh"] = 1.0 if (creator_row["prior_txs"] or 0) < 10 else 0.0
    if meta is not None:
        f["has_twitter"] = 1.0 if meta.get("twitter") else 0.0
        f["has_website"] = 1.0 if meta.get("website") else 0.0
        f["has_telegram"] = 1.0 if meta.get("telegram") else 0.0
        f["n_socials"] = f["has_twitter"] + f["has_website"] + f["has_telegram"]
        f["tw_is_status"] = 1.0 if "/status/" in (meta.get("twitter") or "") else 0.0
        f["desc_len"] = len(meta.get("description") or "")
    if smart is not None:
        early = {r["wallet"] for r in buys}
        f["smart_wallets"] = len(early & smart)
    return f


def price_at(trs, cut, k=3):
    """Price at `cut`: median of the last k priced trades, so one odd tx (routed buy, dust) cannot set it."""
    import statistics
    last = []
    for r in trs:
        if r["ts"] > cut:
            break
        if r["price"]:
            last.append(r["price"])
    return statistics.median(last[-k:]) if last else None


def peak_after(trs, series, cut, end, use="close"):
    """Peak price (SOL per token) after `cut` until `end`, from curve trades and candles. Uses the 2nd highest
    point (a real pump has many trades near its top), so a single mispriced tx cannot make a 'winner'."""
    pts = [r["price"] for r in trs if cut < r["ts"] <= end and r["price"]
           and abs(r.get("sol") or 1) >= 0.01 and abs(r.get("tokens") or 1e9) >= 1e4]  # not dust or rent refunds
    for c in series or []:
        ts, high, close = c[0], c[1], c[2]
        if cut <= ts <= end:
            pts.append(close if use == "close" else high)
    if not pts:
        return 0.0
    pts.sort(reverse=True)
    return pts[1] if len(pts) >= 2 else pts[0]


def first_cross(series, level, after):
    """(ts, price) of the first 15 min candle closing at or above `level` (price) after `after`."""
    for c in sorted(series or []):
        if c[0] >= after and c[2] >= level:
            return c[0], c[2]
    return None, None


def path_shape(points, cut, start):
    """How the price got to where it is at `cut`: steady climb, sudden spike or chop.

    points: (ts, price) sorted. Returns spike_share (share of the log-rise made in the last 10% of the time),
    up_steps (share of 1/20-time buckets that closed higher than the previous one), max_dd_pct (deepest fall
    from a running high before cut) and vol (std of bucket log returns)."""
    pts = [(t, p) for t, p in points if start <= t <= cut and p and p > 0]
    if len(pts) < 3 or cut <= start:
        return {"spike_share": None, "up_steps": None, "max_dd_pct": None, "vol": None}
    import math
    span = cut - start
    buckets = []
    j = 0
    last = pts[0][1]
    for k in range(1, 21):
        edge = start + span * k / 20
        while j < len(pts) and pts[j][0] <= edge:
            last = pts[j][1]
            j += 1
        buckets.append(last)
    p0, pend = pts[0][1], pts[-1][1]
    p_late = None
    for t, p in pts:
        if t <= cut - span * 0.1:
            p_late = p
    total = math.log(pend / p0) if pend > 0 and p0 > 0 else 0
    late = math.log(pend / p_late) if p_late else total
    hi, dd = 0, 0
    for _, p in pts:
        hi = max(hi, p)
        dd = max(dd, 1 - p / hi)
    rets = [math.log(b / a) for a, b in zip(buckets[:-1], buckets[1:]) if a > 0 and b > 0]
    mean = sum(rets) / len(rets) if rets else 0
    return {"spike_share": (late / total) if total > 0.05 else None,
            "up_steps": sum(1 for r in rets if r > 0) / max(1, len(rets)),
            "max_dd_pct": 100 * dd,
            "vol": (sum((r - mean) ** 2 for r in rets) / max(1, len(rets))) ** 0.5}


def buy_concentration(trs, cut):
    """Share of SOL bought before cut that came from the 3 biggest buyers (few wallets = likely painted pump)."""
    per = {}
    for r in trs:
        if r["ts"] <= cut and r["side"] == "buy":
            per[r["wallet"]] = per.get(r["wallet"], 0.0) - r["sol"]
    tot = sum(per.values())
    return sum(sorted(per.values(), reverse=True)[:3]) / tot if tot > 0 else None
