"""Helius wallet forensics: who bought a token early, and how good those wallets are.

Uses the Enhanced Transactions API (GET /v0/addresses/{addr}/transactions), ~100 credits per call
on the free plan, so results are cached on disk (HELIUS_CACHE_TTL, default 10 min; asc pages longer).
"""
import os
import statistics

from event_calendar import http

BASE = "https://api-mainnet.helius-rpc.com/v0"
SOL = "So11111111111111111111111111111111111111112"
STABLES = {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}
CACHE_TTL = int(os.environ.get("HELIUS_CACHE_TTL", "600"))


def _key():
    k = os.environ.get("HELIUS_API_KEY")
    if not k:
        raise RuntimeError("HELIUS_API_KEY nije postavljen")
    return k


def transactions(address, limit=100, before=None, oldest_first=False, tx_type="SWAP", ttl=None):
    params = {"api-key": _key(), "limit": limit}
    if tx_type:
        params["type"] = tx_type
    if before:
        params["before"] = before
    if oldest_first:
        params["sort-order"] = "asc"
    data = http.get_json(f"{BASE}/addresses/{address}/transactions", params,
                         ttl=CACHE_TTL * 100 if oldest_first else (CACHE_TTL if ttl is None else ttl))
    return data if isinstance(data, list) else []


def _amount(change):
    raw = change["rawTokenAmount"]
    return int(raw["tokenAmount"]) / 10 ** int(raw["decimals"])


def swap_deltas(tx, wallet, sol_usd=150.0):
    """(sol_delta, {mint: token_delta}) for one wallet in one parsed tx. Stablecoins are converted to SOL."""
    sol, toks = 0.0, {}
    for acc in tx.get("accountData") or []:
        if acc.get("account") == wallet:
            sol += (acc.get("nativeBalanceChange") or 0) / 1e9
        for c in acc.get("tokenBalanceChanges") or []:
            if c.get("userAccount") != wallet:
                continue
            amt = _amount(c)
            if c["mint"] == SOL:
                sol += amt
            elif c["mint"] in STABLES:
                sol += amt / sol_usd
            else:
                toks[c["mint"]] = toks.get(c["mint"], 0) + amt
    return sol, toks


def early_buyers(mint, n=50, pages=2):
    """First n distinct wallets that bought `mint`, oldest first, with time and SOL spent."""
    out, seen, before, first_ts = [], set(), None, None
    for _ in range(pages):
        txs = transactions(mint, oldest_first=True, before=before)
        if not txs:
            break
        for tx in txs:
            first_ts = first_ts or tx.get("timestamp")
            payer = tx.get("feePayer")
            sol, toks = swap_deltas(tx, payer)
            if toks.get(mint, 0) <= 0 or payer in seen:
                continue
            seen.add(payer)
            out.append({"wallet": payer, "ts": tx["timestamp"], "slot": tx.get("slot"),
                        "secs_after_first": tx["timestamp"] - first_ts, "sol_in": round(-sol, 4),
                        "source": tx.get("source")})
            if len(out) >= n:
                return out
        before = txs[-1]["signature"]
    return out


def wallet_trades(wallet, pages=3, sol_usd=150.0):
    """Per-mint aggregate of a wallet's recent swaps (newest pages first)."""
    per, before, n_tx, ts = {}, None, 0, []
    for _ in range(pages):
        txs = transactions(wallet, before=before)
        if not txs:
            break
        for tx in txs:
            if tx.get("transactionError"):
                continue
            sol, toks = swap_deltas(tx, wallet, sol_usd)
            n_tx += 1
            ts.append(tx["timestamp"])
            for mint, amt in toks.items():
                m = per.setdefault(mint, {"mint": mint, "sol_in": 0.0, "sol_out": 0.0, "tokens": 0.0,
                                          "first_buy": None, "last_sell": None, "buys": 0, "sells": 0})
                m["tokens"] += amt
                if amt > 0:
                    m["sol_in"] += max(0.0, -sol)
                    m["buys"] += 1
                    m["first_buy"] = min(m["first_buy"] or tx["timestamp"], tx["timestamp"])
                else:
                    m["sol_out"] += max(0.0, sol)
                    m["sells"] += 1
                    m["last_sell"] = max(m["last_sell"] or 0, tx["timestamp"])
        if len(txs) < 100:
            break
        before = txs[-1]["signature"]
    span_h = (max(ts) - min(ts)) / 3600 if len(ts) > 1 else 0
    return list(per.values()), {"n_tx": n_tx, "span_h": round(span_h, 1)}


def score_wallet(trades, meta, min_sol=0.05):
    """Smart-money stats from closed positions (bought and sold). Score 0-100, bots flagged."""
    closed = [t for t in trades if t["sol_in"] >= min_sol and t["sells"] > 0]
    pnl = [t["sol_out"] - t["sol_in"] for t in closed]
    rois = [(t["sol_out"] / t["sol_in"]) - 1 for t in closed]
    holds = [(t["last_sell"] - t["first_buy"]) / 60 for t in closed if t["first_buy"] and t["last_sell"]]
    wins = sum(1 for r in rois if r > 0)
    tx_per_h = meta["n_tx"] / meta["span_h"] if meta["span_h"] else meta["n_tx"]
    s = {
        "tokens_traded": len(trades), "closed": len(closed),
        "win_rate": round(wins / len(closed), 2) if closed else 0,
        "pnl_sol": round(sum(pnl), 2), "median_roi": round(statistics.median(rois), 2) if rois else 0,
        "big_wins": sum(1 for r in rois if r >= 1.0),  # 2x or better
        "median_hold_min": round(statistics.median(holds), 1) if holds else None,
        "tx_per_hour": round(tx_per_h, 1),
        "bot": tx_per_h > 30 or (holds and statistics.median(holds) < 0.5),
    }
    score = 0.0
    if len(closed) >= 5:
        score += 35 * s["win_rate"]
        score += min(30, max(0, s["pnl_sol"]) * 1.5)
        score += min(20, s["big_wins"] * 4)
        score += min(15, len(closed))
    s["score"] = 0 if s["bot"] else round(min(100, score))
    return s
