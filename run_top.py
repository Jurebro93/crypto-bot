#!/usr/bin/env python3
"""Svježa provjera preporučenih tokena (topcheck/): every few minutes for the top recommended tokens only.

    python3 run_top.py once            # one pass
    python3 run_top.py loop --every 180

Per pass, for the top TOP_N Natjecanje suggestions plus what Pregled features (ui.overview.watch_tokens):
  * DexScreener pairs (one free batch call)          -> market state: pumpa / pad uz oporavak / pada / stabilno
  * RugCheck report (free, every RC_EVERY_MIN)       -> mint/freeze authority, LP, top holders, dev, Token-2022 traps
  * Jupiter sell quote (free, every SELL_EVERY_MIN)  -> honeypot test: can it be sold, how much comes back
  * full rug filter (Helius, already paid) at most every FULL_EVERY_H per token, FULL_PER_DAY a day (~525 credits
    each, default cap 30/day ~ 16k credits of the plan's ~330k/day), saved to rug.db like every other rug check
The fresh hype score itself comes from the scan: these tokens are in hype.pulse.retained, re-scored every 2 min.
Writes topcheck.db only (plus rug.db through run_rug.save). Never trades.
"""
import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.parse

from topcheck import safety, state, store

HERE = os.path.dirname(os.path.abspath(__file__))
RUG_DB = os.environ.get("RUG_DB", os.path.join(HERE, "rug.db"))
WSOL = "So11111111111111111111111111111111111111112"
RC_EVERY_MIN = float(os.environ.get("TOP_RC_EVERY_MIN", "30"))
SELL_EVERY_MIN = float(os.environ.get("TOP_SELL_EVERY_MIN", "10"))
FULL_EVERY_H = float(os.environ.get("TOP_FULL_EVERY_H", "12"))
FULL_PER_DAY = int(os.environ.get("TOP_FULL_PER_DAY", "30"))
SELL_USD = 25.0


def log(msg):
    print(f"topcheck: {msg}", file=sys.stderr, flush=True)


def best_pairs(mints):
    from dexscreener import client as dex
    best = {}
    for p in dex.tokens("solana", list(mints)):
        t = (p.get("baseToken") or {}).get("address")
        if t not in mints:
            continue
        liq = (p.get("liquidity") or {}).get("usd") or 0
        if t not in best or liq > ((best[t].get("liquidity") or {}).get("usd") or 0):
            best[t] = p
    return best


def rugcheck(mint):
    from rugfilter import rugcheck as rc
    try:
        return safety.summarize_rc(rc.report(mint, ttl=int(RC_EVERY_MIN * 60) - 30))
    except Exception as e:
        log(f"RugCheck {mint[:6]}: {type(e).__name__}: {e}")
        return None


def sell_quote(mint, price, decimals, sol_usd):
    """Jupiter quote for selling SELL_USD worth of the token into SOL; the USD that comes back as `_usd_out`."""
    if not price or decimals is None or not sol_usd:
        return None
    amount = int(SELL_USD / price * 10 ** decimals)
    if amount <= 0:
        return None
    from event_calendar import http
    url = "https://lite-api.jup.ag/swap/v1/quote?" + urllib.parse.urlencode(
        {"inputMint": mint, "outputMint": WSOL, "amount": amount, "slippageBps": 2000})
    try:
        q = http.get_json(url, ttl=0, timeout=15, retries=1)
    except Exception as e:
        msg = str(e)
        if "400" in msg or "COULD_NOT_FIND" in msg or "NOT_TRADABLE" in msg:
            return {"error": msg[:80]}
        log(f"Jupiter {mint[:6]}: {type(e).__name__}: {e}")
        return None
    if isinstance(q, dict) and q.get("outAmount"):
        q["_usd_out"] = int(q["outAmount"]) / 1e9 * sol_usd
        q.pop("routePlan", None)
    return q


def latest_full(mint):
    if not os.path.exists(RUG_DB):
        return None
    try:
        con = sqlite3.connect(f"file:{RUG_DB}?mode=ro", uri=True, timeout=10)
        r = con.execute("SELECT checked_at, verdict, data FROM rug_reports WHERE mint=? ORDER BY checked_at DESC LIMIT 1",
                        (mint,)).fetchone()
        con.close()
    except sqlite3.Error:
        return None
    if not r:
        return None
    try:
        d = json.loads(r[2] or "{}")
    except ValueError:
        d = {}
    return {"checked_at": r[0], "verdict": r[1], "data": {"hard_fails": d.get("hard_fails") or []}}


def full_check(con, mint, now):
    """Fresh full rug filter (Helius) when the newest one is older than FULL_EVERY_H and the daily cap allows."""
    have = latest_full(mint)
    if have and now - (have["checked_at"] or 0) < FULL_EVERY_H * 3600:
        return have
    if not os.environ.get("HELIUS_API_KEY"):
        return have
    if not store.budget_take(con, time.strftime("%Y-%m-%d", time.gmtime(now)), FULL_PER_DAY):
        return have
    con.commit()
    from ops import heavy
    with heavy.slot(wait=0) as got:   # the full check pulls many transactions: never on top of another heavy job
        if not got:
            return have
        try:
            from rugfilter.check import check
            import run_rug
            r = check(mint)
            run_rug.save(r)
            return {"checked_at": r["checked_at"], "verdict": r["verdict"], "data": {"hard_fails": r.get("hard_fails") or []}}
        except Exception as e:
            log(f"rug filter {mint[:6]}: {type(e).__name__}: {e}")
            return have


def pass_once(n=None):
    from ui import overview
    now = time.time()
    mints = overview.watch_tokens(n=n or overview.TOP_N)
    if not mints:
        log("nema preporučenih tokena")
        return 0
    try:
        pairs = best_pairs(set(mints))
    except Exception as e:
        log(f"DexScreener: {type(e).__name__}: {e}")
        pairs = {}
    try:
        from ui.paper import jup_prices
        sol_usd = (jup_prices([WSOL]).get(WSOL) or (None,))[0]
    except Exception:
        sol_usd = None
    con = store.connect()
    try:
        for rank, mint in enumerate(mints, 1):
            old = store.get(con, mint) or {}
            p = pairs.get(mint)
            st = state.classify(p)
            price = float(p.get("priceUsd") or 0) if p else None
            row = {"token": mint, "symbol": (p or {}).get("baseToken", {}).get("symbol") or old.get("symbol"),
                   "rank": rank, "ts": int(now), "price": price or old.get("price"),
                   "mcap": (p.get("marketCap") or p.get("fdv")) if p else old.get("mcap"),
                   "liq": ((p.get("liquidity") or {}).get("usd")) if p else old.get("liq"),
                   "state": st["state"] if st else None, "state_json": json.dumps(st, ensure_ascii=False) if st else None}
            rc = json.loads(old.get("rc_json") or "null")
            row["rc_ts"] = old.get("rc_ts")
            if rc is None or now - (old.get("rc_ts") or 0) > RC_EVERY_MIN * 60:
                fresh = rugcheck(mint)
                if fresh is not None:
                    rc, row["rc_ts"] = fresh, int(now)
            row["rc_json"] = json.dumps(rc) if rc is not None else None
            sell = json.loads(old.get("sell_json") or "null")
            row["sell_ts"] = old.get("sell_ts")
            if sell is None or now - (old.get("sell_ts") or 0) > SELL_EVERY_MIN * 60:
                q = sell_quote(mint, price, (rc or {}).get("decimals"), sol_usd)
                if q is not None:
                    sell, row["sell_ts"] = safety.sell_test(q, SELL_USD), int(now)
            row["sell_json"] = json.dumps(sell) if sell is not None else None
            full = full_check(con, mint, now) if rank <= (n or overview.TOP_N) else latest_full(mint)
            row["full_ts"] = (full or {}).get("checked_at")
            sf = safety.judge(mint, rc, sell, full)
            row["verdict"], row["safety_json"] = sf["verdict"], json.dumps(sf, ensure_ascii=False)
            store.put(con, row)
            con.commit()
            if sf["verdict"] == "pao" and old.get("verdict") != "pao":
                log(f"{row['symbol'] or mint[:6]} pao na rug checku: {'; '.join(sf['fails'][:2])}")
        store.unrank(con, mints)
        con.commit()
    finally:
        con.close()
    log(f"provjereno {len(mints)} preporučenih tokena")
    return len(mints)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["once", "loop"])
    ap.add_argument("--every", type=int, default=int(os.environ.get("TOP_EVERY_S", "180")))
    ap.add_argument("--n", type=int, default=None)
    a = ap.parse_args()
    if a.cmd == "once":
        pass_once(a.n)
        return
    while True:
        t0 = time.time()
        try:
            pass_once(a.n)
        except Exception as e:  # one bad pass must not end the loop
            log(f"prolaz nije uspio: {type(e).__name__}: {e}")
        time.sleep(max(30, a.every - (time.time() - t0)))


if __name__ == "__main__":
    main()
