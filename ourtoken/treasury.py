"""The shared vault ("trezor"): a PUBLIC Solana address, read on chain. The dashboard never holds its key.

NAS_TOKEN_TREZOR (Render env) overrides DEFAULT. Recommended later: a Squads multisig vault, so no single person
can move the money. Reading costs little: Helius
getBalance (1 credit) + getTransactionsForAddress (10 credits per 100 txs), cached 10 min, only when the page opens.
Donations are SOL or USDC sent to the address; the sender is matched to a player by the wallet they registered.
"""
import os
import time

USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
LAMPORTS = 1e9
_CACHE = {}
CACHE_S = 600


# Nicholas's new Phantom wallet, 1.11.2026 (public address only). Later a Squads multisig vault: set NAS_TOKEN_TREZOR.
DEFAULT = "84AWq5MbyGf2QrMMcaCnRbG3wAnjn7vy5N5WAnBZMdTs"


def address():
    a = os.environ.get("NAS_TOKEN_TREZOR", DEFAULT).strip()
    from ourtoken.store import ADDR
    return a if ADDR.fullmatch(a) else ""


def _rpc(method, params):
    from wallets import rpc
    res, cached = rpc._rpc(method, params, ttl=CACHE_S)
    if not cached:
        try:
            from usage import meter
            meter.record("helius", f"trezor:{method}", 10 if method == "getTransactionsForAddress" else 1)
        except Exception:  # noqa: BLE001
            pass
    return res


def _keys(tx):
    return [k["pubkey"] if isinstance(k, dict) else k for k in tx["transaction"]["message"]["accountKeys"]]


def incoming(txs, addr):
    """Plain list of what came into `addr`: {ts, sig, sender, sol, usdc}. Outgoing / zero moves are skipped."""
    out = []
    for tx in txs or []:
        try:
            keys, meta = _keys(tx), tx.get("meta") or {}
            sol = 0.0
            if addr in keys:
                i = keys.index(addr)
                sol = (meta["postBalances"][i] - meta["preBalances"][i]) / LAMPORTS
            usdc = 0.0
            for side, sign in (("postTokenBalances", 1), ("preTokenBalances", -1)):
                for b in meta.get(side) or []:
                    if b.get("owner") == addr and b.get("mint") == USDC:
                        usdc += sign * float((b.get("uiTokenAmount") or {}).get("uiAmount") or 0)
            if sol <= 0.000001 and usdc <= 0.000001:
                continue
            out.append({"ts": tx.get("blockTime"), "sig": (tx["transaction"].get("signatures") or [""])[0],
                        "sender": keys[0], "sol": max(sol, 0.0), "usdc": max(usdc, 0.0)})
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    return out


def read(addr=None, now=None):
    """{address, sol, usdc, gifts: [...], error} for the vault; {} when no address is set."""
    addr = addr or address()
    if not addr:
        return {}
    hit = _CACHE.get(addr)
    now = now or time.time()
    if hit and now - hit[0] < CACHE_S:
        return hit[1]
    out = {"address": addr, "sol": None, "usdc": None, "gifts": [], "error": None}
    try:
        out["sol"] = (_rpc("getBalance", [addr]) or {}).get("value", 0) / LAMPORTS
        acc = _rpc("getTokenAccountsByOwner", [addr, {"mint": USDC}, {"encoding": "jsonParsed"}]) or {}
        out["usdc"] = sum(float(a["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"] or 0)
                          for a in acc.get("value") or [])
        res = _rpc("getTransactionsForAddress", [addr, {
            "transactionDetails": "full", "encoding": "jsonParsed", "maxSupportedTransactionVersion": 1,
            "limit": 100, "sortOrder": "desc", "filters": {"status": "succeeded", "tokenAccounts": "balanceChanged"}}]) or {}
        out["gifts"] = incoming(res.get("data") or [], addr)
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:200]
    _CACHE[addr] = (now, out)
    return out


def by_player(gifts, donors, sol_usd):
    """player -> {sol, usdc, usd, n}; gifts from wallets nobody registered go under '?'."""
    who = {a: u for u, a in donors.items()}
    out = {}
    for g in gifts:
        r = out.setdefault(who.get(g["sender"], "?"), {"sol": 0.0, "usdc": 0.0, "usd": 0.0, "n": 0})
        r["sol"] += g["sol"]
        r["usdc"] += g["usdc"]
        r["usd"] += g["sol"] * (sol_usd or 0) + g["usdc"]
        r["n"] += 1
    return out
