"""Positions, realized/unrealized PnL and the two wallet scores, from parsed trade rows (see rpc.parse).

score       0-100: how profitable and how consistently (sample size, win rate, profit factor, concentration)
style       bot / sniper / scalper / swing; profitable bots and snipers get tier S (signal, not copy)
copy_score  0-100: score x how copyable it is (hold time, activity, recency, size, insider signs)
"""
import math
import statistics
import time

DEAD_LIQ_USD = 1000  # an open position in a pool below this is treated as worth 0


def _clamp(x):
    return max(0.0, min(1.0, x))


CLOSED_FRAC = 0.98   # sold this share of what was bought = closed (was 0.9: a 10% bag still open was "closed")


def positions(rows, prices=None):
    """rows -> {mint: position}. prices: {mint: price in SOL per token}; missing or None = unknown, 0 = confirmed
    dead (pool below DEAD_LIQ_USD).

    Cost basis is kept event by event (moving average cost, audit 4.11. C01): a sale books its profit against the
    cost of the tokens held AT THAT MOMENT, so a later buy never changes an already booked sale. Tokens received for
    free (transfer_in) have no known cost: sales beyond the bought quantity are left out of realized PnL.
    Fields: bought/cost/sold/proceeds (totals), realized, remaining, cost_left (open cost basis), value,
    unrealized, price_status (known / unknown / dead), status (open / closed / no_cost / moved), roi, hold_min."""
    prices = prices or {}
    pos = {}
    for r in sorted(rows, key=lambda r: r["ts"]):
        p = pos.setdefault(r["mint"], {"mint": r["mint"], "bought": 0.0, "cost": 0.0, "sold": 0.0, "proceeds": 0.0,
                                       "free_in": 0.0, "moved": 0.0, "buys": 0, "sells": 0, "first_buy": None,
                                       "last_sell": None, "last_ts": None, "held": 0.0, "held_cost": 0.0,
                                       "realized": 0.0, "matched_proceeds": 0.0, "matched_cost": 0.0})
        p["last_ts"] = r["ts"]
        if r["kind"] == "buy":
            p["bought"] += r["tokens"]
            p["cost"] += -r["sol"]
            p["held"] += r["tokens"]
            p["held_cost"] += -r["sol"]
            p["buys"] += 1
            p["first_buy"] = p["first_buy"] or r["ts"]
        elif r["kind"] == "sell":
            q, got = -r["tokens"], r["sol"]
            p["sold"] += q
            p["proceeds"] += got
            p["sells"] += 1
            p["last_sell"] = r["ts"]
            if q > 0 and p["held"] > 0:
                m = min(q, p["held"])                     # tokens with a known cost
                c = p["held_cost"] * m / p["held"]
                g = got * m / q
                p["realized"] += g - c
                p["matched_proceeds"] += g
                p["matched_cost"] += c
                p["held"] -= m
                p["held_cost"] -= c
        elif r["kind"] == "transfer_in":
            p["free_in"] += r["tokens"]
        elif r["kind"] == "transfer_out":
            q = -r["tokens"]
            p["moved"] += q
            if q > 0 and p["held"] > 0:                 # the cost leaves with the tokens, no profit booked
                m = min(q, p["held"])
                p["held_cost"] -= p["held_cost"] * m / p["held"]
                p["held"] -= m
    for p in pos.values():
        held, held_cost = p.pop("held"), p.pop("held_cost")
        if p["bought"] <= 0:
            p["status"] = "no_cost"  # only transfers, or bought before our history window
            continue
        if p["moved"] > 0.5 * p["bought"]:
            p["status"] = "moved"  # sent to another wallet (often to sell from there): PnL unknown here
            continue
        p["remaining"] = max(0.0, held)
        p["cost_left"] = max(0.0, held_cost)
        price = prices.get(p["mint"])
        p["price_status"] = "unknown" if price is None else "dead" if price == 0 else "known"
        p["value"] = None if price is None else p["remaining"] * price
        p["unrealized"] = None if price is None else p["value"] - p["cost_left"]
        sold_frac = 1 - p["remaining"] / p["bought"] if p["bought"] else 1.0
        p["status"] = "closed" if sold_frac >= CLOSED_FRAC or price == 0 else "open"
        p["roi"] = (p["realized"] + (p["unrealized"] or 0.0)) / p["cost"] if p["cost"] > 0 else 0.0
        p["hold_min"] = (p["last_sell"] - p["first_buy"]) / 60 if p["last_sell"] and p["first_buy"] else None
    return pos


def score(pos, rows, now=None, labels=(), min_sol=0.02):
    now = now or time.time()
    real = [p for p in pos.values() if p["status"] in ("open", "closed") and p["cost"] >= min_sol]
    closed = [p for p in real if p["status"] == "closed"]
    rois = [p["roi"] for p in closed]
    pnls = [p["realized"] + (p["unrealized"] or 0) for p in closed]
    gains, losses = sum(x for x in pnls if x > 0), -sum(x for x in pnls if x < 0)
    wins = sum(1 for r in rois if r > 0)
    n = len(closed)
    realized = sum(p["realized"] for p in real)
    unrealized = sum(p["unrealized"] or 0 for p in real if p["status"] == "open")
    cost = sum(p["cost"] for p in closed)
    holds = [p["hold_min"] for p in closed if p["hold_min"] is not None]
    sizes = [p["cost"] / max(1, p["buys"]) for p in real]
    ts = [r["ts"] for r in rows]
    span_d = max(1.0, (max(ts) - min(ts)) / 86400) if ts else 1.0
    trades_per_day = sum(1 for r in rows if r["kind"] in ("buy", "sell")) / span_d
    free_ratio = (sum(1 for p in pos.values() if p["free_in"] > 0) / len(pos)) if pos else 0
    total_pnl = sum(pnls)
    s = {
        "positions": len(real), "closed": n, "open": len(real) - n,
        "win_rate": round(wins / n, 2) if n else 0.0,
        "realized_sol": round(realized, 3), "unrealized_sol": round(unrealized, 3),
        "closed_pnl_sol": round(total_pnl, 3), "roi_on_cost": round(total_pnl / cost, 2) if cost else 0.0,
        "profit_factor": round(gains / losses, 2) if losses else (99.0 if gains else 0.0),
        "big_wins": sum(1 for r in rois if r >= 1.0), "rugged_in": sum(1 for p in closed if p["roi"] <= -0.9),
        "median_roi": round(statistics.median(rois), 2) if rois else 0.0,
        "top_trade_share": round(max(pnls) / gains, 2) if gains and pnls else 1.0,
        "median_hold_min": round(statistics.median(holds), 1) if holds else None,
        "median_buy_sol": round(statistics.median(sizes), 3) if sizes else 0.0,
        "trades_per_day": round(trades_per_day, 1), "free_token_ratio": round(free_ratio, 2),
        "last_trade_days": round((now - max(ts)) / 86400, 1) if ts else None,
        "history_days": round(span_d, 1),
    }
    wr = (wins + 1) / (n + 2)  # shrunk toward 50% so 2/2 doesn't look like a genius
    pf = min(s["profit_factor"], 5)
    sc = (25 * _clamp(math.log10(1 + max(0, total_pnl)) / 2)       # 100 SOL closed profit = full marks
          + 20 * _clamp(s["roi_on_cost"])                             # +100% on capital = full marks
          + 20 * _clamp((wr - 0.25) / 0.45)
          + 15 * _clamp((pf - 1) / 2)
          + 10 * _clamp(s["big_wins"] / 5)
          + 10 * (1 - _clamp(s["top_trade_share"])) * (total_pnl > 0))
    sc *= min(1.0, n / 10)  # fewer than 10 closed trades = not enough evidence
    s["score"] = round(sc)

    bot = trades_per_day > 300 or (s["median_hold_min"] is not None and s["median_hold_min"] < 0.5)
    s["bot"] = bool(bot)
    h = s["median_hold_min"]
    if bot:
        s["style"] = "bot"
    elif "sniper" in labels:
        s["style"] = "sniper"
    elif h is not None and h < 10:
        s["style"] = "scalper"
    else:
        s["style"] = "swing"
    why, mult = [], 1.0
    bad = set(labels) & {"bot", "rugger", "bundler", "insider", "dev", "cex", "mev", "sniper", "funder_of_rugger"}
    if bot or bad:
        mult, why = 0.0, ["bot"] if bot else sorted(bad)
    else:
        h = s["median_hold_min"]
        if h is not None and h < 2:
            mult *= 0.2; why.append("drži < 2 min")
        elif h is not None and h < 10:
            mult *= 0.6; why.append("drži < 10 min")
        if trades_per_day > 60:
            mult *= 0.4; why.append("previše trejdova")
        elif trades_per_day < 0.3:
            mult *= 0.7; why.append("rijetko trejda")
        d = s["last_trade_days"]
        if d is not None and d > 14:
            mult *= 0.2; why.append("neaktivan 14+ dana")
        elif d is not None and d > 5:
            mult *= 0.6; why.append("neaktivan 5+ dana")
        if s["median_buy_sol"] < 0.05:
            mult *= 0.5; why.append("sitne kupnje")
        if free_ratio > 0.3:
            mult *= 0.3; why.append("puno besplatnih tokena (insider?)")
        if s["closed_pnl_sol"] <= 0:
            mult = 0.0; why.append("u minusu")
    s["copy_score"] = round(s["score"] * mult)
    s["copy_notes"] = why
    return s


def tier(s):
    """Tier and seconds until the next recheck. Better wallets are rechecked more often (cheap: only new txs)."""
    if s["score"] >= 40 and s["style"] in ("bot", "sniper"):
        return "S", 24 * 3600  # profitable but not copyable: tracked as a signal source
    if s["copy_score"] >= 60:
        return "A", 6 * 3600
    if s["score"] >= 40 or s["copy_score"] >= 35:
        return "B", 24 * 3600
    if s["bot"] or s["copy_score"] == 0 and s["closed"] >= 10:
        return "D", None  # only rechecked if another analysis sees it again
    return "C", 7 * 24 * 3600


def prices_sol(mints, client):
    """({mint: SOL price per token}, SOL/USD) from DexScreener (free). A mint the feed did not answer for is left
    OUT (unknown, audit 4.11. C02: an empty answer used to become price 0 = "dead token" and closed the position);
    0 only for a pool that answered with liquidity below DEAD_LIQ_USD. SOL/USD None when unknown."""
    out = {}
    best = {}
    sol_usd = None
    for p in client.tokens("solana", list(mints) + ["So11111111111111111111111111111111111111112"]):
        base = p["baseToken"]["address"]
        liq = (p.get("liquidity") or {}).get("usd") or 0
        if base == "So11111111111111111111111111111111111111112":
            if p.get("priceUsd") and liq > (best.get(base, (0,))[0]):
                best[base] = (liq, float(p["priceUsd"]))
                sol_usd = float(p["priceUsd"])
            continue
        if base in mints and p.get("priceUsd") and liq >= best.get(base, (-1,))[0]:
            best[base] = (liq, float(p.get("priceUsd") or 0))
    for m, (liq, usd) in best.items():
        if m in mints and sol_usd:
            out[m] = usd / sol_usd if liq >= DEAD_LIQ_USD else 0.0
    return out, sol_usd
