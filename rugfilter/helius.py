"""Helius client (free tier is enough). Needs HELIUS_API_KEY in the environment.

Docs: https://www.helius.dev/docs (Enhanced Transactions API, RPC).
The Enhanced Transactions API costs more credits than plain RPC, so callers keep page counts small
and wallet lookups are cached for a week (a wallet's first transactions never change).
"""
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from event_calendar import http

API = "https://api-mainnet.helius-rpc.com/v0"
RPC = "https://mainnet.helius-rpc.com/"
WEEK = 7 * 24 * 3600


class _Throttle:
    def __init__(self, per_second):
        self.gap, self.last, self.lock = 1.0 / per_second, 0.0, threading.Lock()

    def wait(self):
        with self.lock:
            delay = self.last + self.gap - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self.last = time.monotonic()


# approximate Helius credit prices: Enhanced API 100 per call, getTransactionsForAddress ~10, other RPC 1
_credits = [0]


def credits_used():
    return _credits[0]


_ENHANCED = _Throttle(float(os.environ.get("HELIUS_ENHANCED_RPS", "2")))
_RPC = _Throttle(float(os.environ.get("HELIUS_RPC_RPS", "8")))


def _key():
    key = os.environ.get("HELIUS_API_KEY")
    if not key:
        raise RuntimeError("HELIUS_API_KEY nije postavljen")
    return key


def address_txs(address, limit=100, order="desc", before=None, tx_type=None, ttl=300):
    """Parsed (enhanced) transactions touching an address. order="asc" starts from the very first one."""
    params = {"api-key": _key(), "limit": limit}
    if order == "asc":
        params["sort-order"] = "asc"
    if before:
        params["before"] = before
    if tx_type:
        params["type"] = tx_type
    return _enhanced(address, params, ttl)


def _enhanced(address, params, ttl):
    url = f"{API}/addresses/{address}/transactions"
    if http.cache_get(url + "?" + urllib.parse.urlencode(params), ttl) is None:
        _ENHANCED.wait()
        _credits[0] += 100
    data = http.get_json(url, params, ttl=ttl)
    return data if isinstance(data, list) else []


def address_txs_pages(address, pages=1, order="desc", tx_type=None, ttl=300):
    """Up to pages*100 transactions. For order="asc" only the first page is reliable to paginate by time."""
    out, before = [], None
    for _ in range(pages):
        if order == "asc" and out:
            # asc pagination: continue after the last seen signature
            batch = _asc_after(address, out[-1]["signature"], ttl)
        else:
            batch = address_txs(address, 100, order, before, tx_type, ttl)
        if not batch:
            break
        out += batch
        before = batch[-1]["signature"]
        if len(batch) < 100:
            break
    return out


def _asc_after(address, after_sig, ttl):
    params = {"api-key": _key(), "limit": 100, "sort-order": "asc", "after-signature": after_sig}
    return _enhanced(address, params, ttl)


def dev_creations(wallet, limit=100):
    """The wallet's last token creations. Helius answers 404 when it finds none of that type."""
    try:
        return address_txs(wallet, limit, tx_type="CREATE", ttl=86400)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise


def wallet_first_txs(wallet, limit=10):
    """Oldest transactions of a wallet (age and who funded it), in the Enhanced shape the analysis uses.

    Uses JSON-RPC getTransactionsForAddress, which is ~10x cheaper in credits than the Enhanced API,
    and caches for a week because a wallet's first transactions never change."""
    cache_key = f"helius-first:{wallet}:{limit}"
    hit = http.cache_get(cache_key, WEEK)
    if hit is not None:
        return hit
    res = rpc("getTransactionsForAddress", [wallet, {"transactionDetails": "full", "encoding": "jsonParsed",
                                                     "sortOrder": "asc", "limit": limit,
                                                     "maxSupportedTransactionVersion": 1}])
    out = [_as_enhanced(t) for t in res.get("data", [])]
    http.cache_put(cache_key, out, ttl=WEEK)
    return out


def _as_enhanced(t):
    """Raw jsonParsed transaction -> {signature, slot, timestamp, feePayer, nativeTransfers}."""
    msg = t["transaction"]["message"]
    ixs = list(msg.get("instructions", []))
    for inner in (t.get("meta") or {}).get("innerInstructions") or []:
        ixs += inner.get("instructions", [])
    native = []
    for ix in ixs:
        p = ix.get("parsed")
        if ix.get("program") == "system" and isinstance(p, dict) and p.get("type") in ("transfer", "transferWithSeed"):
            i = p["info"]
            native.append({"fromUserAccount": i.get("source"), "toUserAccount": i.get("destination"),
                           "amount": int(i.get("lamports", 0))})
    keys = msg.get("accountKeys", [])
    payer = keys[0]["pubkey"] if keys and isinstance(keys[0], dict) else (keys[0] if keys else None)
    return {"signature": t["transaction"]["signatures"][0], "slot": t.get("slot"), "timestamp": t.get("blockTime"),
            "feePayer": payer, "nativeTransfers": native, "tokenTransfers": []}


def rpc(method, params, timeout=30):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(f"{RPC}?api-key={_key()}", data=body,
                                 headers={"Content-Type": "application/json", "User-Agent": http.USER_AGENT})
    _RPC.wait()
    _credits[0] += 10 if method in ("getTransactionsForAddress", "getTokenAccounts") else 1
    data = http._fetch(req, timeout)
    if "error" in data:
        raise RuntimeError(f"Helius RPC {method}: {data['error']}")
    return data["result"]


def sol_balance(address):
    return rpc("getBalance", [address])["value"] / 1e9


def token_balance(owner, mint):
    res = rpc("getTokenAccountsByOwner", [owner, {"mint": mint}, {"encoding": "jsonParsed"}])
    return sum(float(a["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"] or 0) for a in res["value"])


def token_supply(mint):
    v = rpc("getTokenSupply", [mint])["value"]
    return float(v["uiAmount"] or 0), v["decimals"]


def mint_info(mint):
    """Mint and freeze authority straight from the chain."""
    info = rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])["value"]["data"]["parsed"]["info"]
    return {"mintAuthority": info.get("mintAuthority"), "freezeAuthority": info.get("freezeAuthority"),
            "supply": float(info["supply"]) / 10 ** info["decimals"], "decimals": info["decimals"]}
