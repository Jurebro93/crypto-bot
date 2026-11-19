"""Cheap wallet history from Helius: getTransactionsForAddress (JSON-RPC, Helius-only method).

Cost: 10 credits per 100 full transactions (min 10), versus 100 credits per call for the Enhanced
/v0/addresses/{addr}/transactions endpoint that hype/onchain.py uses. Filters run server side:
status=succeeded and tokenAccounts=balanceChanged drop failed txs and plain SOL transfers we don't need,
and blockTime lets a recheck fetch only what is new since the last run.
Docs: https://www.helius.dev/docs/rpc/gettransactionsforaddress
"""
import hashlib
import json
import os
import random
import threading
import time
import urllib.error
import urllib.request

from event_calendar import http

URL = "https://mainnet.helius-rpc.com/"
WSOL = "So11111111111111111111111111111111111111112"
STABLES = {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}
PAGE = 100
CACHE_TTL = int(os.environ.get("HELIUS_CACHE_TTL", "600"))
DUST_SOL = 0.001  # smaller SOL legs are fees/rent, not a trade


def credits_for(n_tx):
    return max(10, -(-n_tx // 100) * 10)


# 19.11. navečer (the deep pump read and the history job run several calls at once): ONE limiter for every thread of
# this process. Token bucket at HELIUS_RPS requests a second (default 8: well under the Developer plan's documented
# 50 RPC requests a second; Pretpostavka: the plan, not a measurement, and other processes share the account: holderi,
# kopija osvjezi, the webhook sync), burst 1 (calls are spaced). A 429 pauses EVERY thread of the process until its
# Retry-After (else 2^attempt s) with jitter, then the call is retried, at most RETRY_429 times; STATS counts calls and
# 429s for the pass line (chain.fetch_stats).
class Limiter:
    def __init__(self, rps=8.0, fn=None, sleep=None):
        self.rps = float(rps)
        self.fn = fn or time.monotonic
        self.sleep = sleep or time.sleep
        self.lock = threading.Lock()
        self.next = 0.0
        self.paused = 0.0

    def set_rps(self, rps):
        with self.lock:
            self.rps = max(0.1, float(rps))

    def wait(self):
        """Block until this thread may send one request (slots spaced 1 / rps apart, after any pause)."""
        with self.lock:
            now = self.fn()
            start = max(now, self.next, self.paused)
            self.next = start + 1.0 / self.rps
        if start > now:
            self.sleep(start - now)

    def pause(self, secs):
        """A 429: no thread sends before now + secs."""
        with self.lock:
            self.paused = max(self.paused, self.fn() + float(secs))


LIMIT = Limiter(float(os.environ.get("HELIUS_RPS", "8")))
RETRY_429 = 4
STATS = {"calls": 0, "e429": 0}
_STATS_LOCK = threading.Lock()


def _count(k, n=1):
    with _STATS_LOCK:
        STATS[k] = STATS.get(k, 0) + n


def _send(req):
    """http._fetch without its own retries, under LIMIT, with the 429 / 5xx back-off above."""
    for attempt in range(RETRY_429 + 1):
        LIMIT.wait()
        _count("calls")
        try:
            return http._fetch(req, 60, retries=0)
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500:
                raise
            if e.code == 429:
                _count("e429")
            try:
                after = float(e.headers.get("Retry-After") or 0)
            except (TypeError, ValueError, AttributeError):
                after = 0.0
            if attempt == RETRY_429:
                raise
            delay = min(60.0, max(after, 2.0 ** attempt)) * (1 + random.uniform(0, 0.3))
            LIMIT.pause(delay)


def _rpc(method, params, ttl=CACHE_TTL):
    key = os.environ.get("HELIUS_API_KEY")
    if not key:
        raise RuntimeError("HELIUS_API_KEY nije postavljen")
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    path = os.path.join(http.CACHE_DIR, "rpc-" + hashlib.sha1(body).hexdigest() + ".json")
    if ttl and os.path.exists(path) and time.time() - os.path.getmtime(path) < ttl:
        with open(path) as f:
            return json.load(f), True
    req = urllib.request.Request(f"{URL}?api-key={key}", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": http.USER_AGENT})
    data = _send(req)
    if "error" in data:
        raise RuntimeError(f"Helius {method}: {data['error']}")
    os.makedirs(http.CACHE_DIR, exist_ok=True)
    http._write(path, json.dumps(data["result"]))
    return data["result"], False


def fetch(address, since_ts=None, until_ts=None, max_pages=3, oldest_first=False, on_credits=None):
    """Full parsed txs of `address` that changed a token balance, newest first unless oldest_first.

    Returns (txs, complete): complete=False when max_pages stopped us before the end of the window.
    """
    flt = {"status": "succeeded", "tokenAccounts": "balanceChanged"}
    bt = {}
    if since_ts:
        bt["gt"] = int(since_ts)
    if until_ts:
        bt["lte"] = int(until_ts)
    if bt:
        flt["blockTime"] = bt
    out, token = [], None
    for _ in range(max_pages):
        opts = {"transactionDetails": "full", "encoding": "jsonParsed", "maxSupportedTransactionVersion": 1,
                "limit": PAGE, "sortOrder": "asc" if oldest_first else "desc", "filters": flt}
        if token:
            opts["paginationToken"] = token
        res, cached = _rpc("getTransactionsForAddress", [address, opts])
        data = res.get("data") or []
        if on_credits and not cached:
            on_credits(credits_for(len(data)))
        out += data
        token = res.get("paginationToken")
        if not token or not data:
            return out, True
    return out, False


def _keys(tx):
    return [k["pubkey"] if isinstance(k, dict) else k for k in tx["transaction"]["message"]["accountKeys"]]


def sol_usd_history(days=120):
    """ts -> SOL/USD of that UTC day (DefiLlama daily closes, free, cached 30 min by core http), or None when the
    day is unknown. Used for stablecoin legs instead of a fixed 150 (audit 4.11. C03)."""
    try:
        from market import sources
        pts = sources.sol_prices(days)
    except Exception:  # noqa: BLE001 - offline: every leg stays "approximate"
        pts = []
    by_day = {int(t) // 86400: px for t, px in pts}

    def at(ts):
        d = int(ts or 0) // 86400
        return by_day.get(d) or by_day.get(d - 1)
    return at


def parse(tx, wallet, sol_usd=150.0):
    """One raw tx -> list of trade rows for `wallet`: buy/sell (token vs SOL) or transfer_in/out (no SOL leg).
    sol_usd: a number, or a function ts -> SOL/USD that day (None = unknown). A stablecoin leg converted with a
    fixed or unknown rate marks the rows fx='approx' so the wallet score can show the approximation."""
    meta = tx.get("meta") or {}
    if meta.get("err"):
        return []
    keys = _keys(tx)
    sol = 0.0
    if wallet in keys:
        i = keys.index(wallet)
        sol += (meta["postBalances"][i] - meta["preBalances"][i]) / 1e9
    toks = {}
    for sign, side in ((-1, "preTokenBalances"), (1, "postTokenBalances")):
        for b in meta.get(side) or []:
            if b.get("owner") != wallet:
                continue
            amt = int(b["uiTokenAmount"]["amount"]) / 10 ** int(b["uiTokenAmount"]["decimals"])
            toks[b["mint"]] = toks.get(b["mint"], 0.0) + sign * amt
    sol += toks.pop(WSOL, 0.0)
    fx = None
    for m in list(toks):
        if m in STABLES:
            rate = sol_usd(tx.get("blockTime")) if callable(sol_usd) else None
            fx = "hist" if rate else "approx"
            sol += toks.pop(m) / (rate or (sol_usd if not callable(sol_usd) else 150.0))
    moved = {m: d for m, d in toks.items() if abs(d) > 1e-9}
    if not moved:
        return []
    sig = tx["transaction"]["signatures"][0]
    ts = tx.get("blockTime") or 0
    ins = [m for m, d in moved.items() if d > 0]
    outs = [m for m, d in moved.items() if d < 0]
    rows = []
    for m, d in moved.items():
        if d > 0 and sol < -DUST_SOL and not outs:
            kind, leg = "buy", sol / len(ins)
        elif d < 0 and sol > DUST_SOL and not ins:
            kind, leg = "sell", sol / len(outs)
        else:  # airdrop, transfer between own wallets, token-for-token swap
            kind, leg = ("transfer_in" if d > 0 else "transfer_out"), 0.0
        row = {"sig": sig, "ts": ts, "mint": m, "tokens": d, "sol": round(leg, 9), "kind": kind}
        if fx:
            row["fx"] = fx
        rows.append(row)
    return rows


BOT_PAGE_HOURS = 2  # 100 token txs in under 2 h = bot/MEV; stop paying for more pages unless it makes money


def _round_trip_sol(rows):
    sold = {r["mint"] for r in rows if r["kind"] == "sell"}
    return sum(r["sol"] for r in rows if r["mint"] in sold and r["kind"] in ("buy", "sell"))


def wallet_swaps(wallet, since_ts=None, max_pages=3, oldest_first=False, on_credits=None, sol_usd=None):
    """Parsed trade rows of a wallet since `since_ts`. Returns (rows, complete, newest_ts, oldest_ts).

    Newest-first first looks are sampled: one page (10 credits) first, more pages only if it isn't a bot,
    or if it is a bot whose round trips on that page made money (profitable bots are worth tracking).
    """
    if sol_usd is None:
        sol_usd = sol_usd_history()
    txs, complete = fetch(wallet, since_ts=since_ts, max_pages=1 if not oldest_first else max_pages,
                          oldest_first=oldest_first, on_credits=on_credits)
    if not oldest_first and not complete and max_pages > 1 and txs:
        times = [tx.get("blockTime") or 0 for tx in txs]
        slow = (max(times) - min(times)) / 3600 >= BOT_PAGE_HOURS
        if slow or _round_trip_sol([r for tx in txs for r in parse(tx, wallet, sol_usd)]) > 0:
            more, complete = fetch(wallet, since_ts=since_ts, until_ts=min(times), max_pages=max_pages - 1,
                                   on_credits=on_credits)
            sigs = {tx["transaction"]["signatures"][0] for tx in txs}
            txs += [tx for tx in more if tx["transaction"]["signatures"][0] not in sigs]
    rows = [r for tx in txs for r in parse(tx, wallet, sol_usd)]
    times = [tx.get("blockTime") or 0 for tx in txs]
    return rows, complete, (max(times) if times else None), (min(times) if times else None)


def early_buyers(mint, n=50, max_pages=2, on_credits=None):
    """First n distinct wallets that bought `mint` (oldest first), via the cheap method.

    Each row has secs_after_first, same_slot (bought in the token's first slot: dev bundle or sniper) and
    creator_tx (the buy sits in the very first tx, i.e. the deployer's own buy).
    """
    txs, _ = fetch(mint, max_pages=max_pages, oldest_first=True, on_credits=on_credits)
    out, seen = [], set()
    first_ts = first_slot = None
    for i, tx in enumerate(txs):
        first_ts = first_ts if first_ts is not None else tx.get("blockTime")
        first_slot = first_slot if first_slot is not None else tx.get("slot")
        payer = _keys(tx)[0]
        if payer in seen:
            continue
        buy = [r for r in parse(tx, payer) if r["mint"] == mint and r["kind"] == "buy"]
        if not buy:
            continue
        seen.add(payer)
        out.append({"wallet": payer, "ts": tx.get("blockTime"), "secs_after_first": (tx.get("blockTime") or 0) - (first_ts or 0),
                    "same_slot": tx.get("slot") == first_slot, "creator_tx": i == 0, "sol_in": round(-buy[0]["sol"], 4)})
        if len(out) >= n:
            break
    return out
