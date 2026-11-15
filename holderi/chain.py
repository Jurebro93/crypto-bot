"""Chain reads for holderi/, every one through the daily Helius credit cap (Budget) and metered by usage/meter (the
requests go through event_calendar/http._fetch). RugCheck (free) is the first source of the top holders; Helius only
when RugCheck has nothing, to trace a large move, to check a destination and for the exchange wallets' balances.

Helius credits (https://www.helius.dev/docs/billing/credits): getTokenLargestAccounts / getMultipleAccounts /
getTokenSupply / getBalance / getSignaturesForAddress / getTokenAccountsByOwner 1 each; getTransactionsForAddress 10
per page of 100 (wallets/rpc.fetch, cached 10 min); a wallet's first transactions (funder) 10, cached a week.
Tests: FETCH[name] replaces each read ("rugcheck", "largest", "txs", "busy", "funder", "token_accounts", "supply").
"""
import time

FETCH = {}
TOKEN_PROGRAMS = ("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
SYSTEM = "11111111111111111111111111111111"


class Budget:
    """Helius credits a day (cap), sliced by the UTC hour like the other jobs (at most cap x (hour + 1) / 24 by now);
    spent credits go to holderi.db kv cnt:<day>.helius. take(n) False = over the cap: the caller stops."""

    def __init__(self, con, cap, now=None, sliced=True):
        from holderi import store
        self.con, self.cap, self.now = con, int(cap), int(now or time.time())
        self.used = float((store.kv_get(con, f"cnt:{store.day(self.now)}", {}) or {}).get("helius") or 0)
        hour = time.gmtime(self.now).tm_hour
        self.allow = self.cap * (hour + 1) / 24 if sliced else self.cap
        self.spent = 0.0
        self.refused = 0

    def left(self):
        return max(0.0, min(self.cap, self.allow) - self.used - self.spent)

    def take(self, n):
        if self.left() < n:
            self.refused += 1
            return False
        self.spent += n
        return True

    def close(self):
        from holderi import store
        if self.spent:
            store.count(self.con, self.now, helius=self.spent)
        return self.spent


def rugcheck(mint):
    """The RugCheck report (free; ttl 1 h = the midcap collector's own cache file, so a token it checked within the hour
    costs nothing)."""
    if "rugcheck" in FETCH:
        return FETCH["rugcheck"](mint)
    from rugfilter import rugcheck as rc
    return rc.report(mint, ttl=3600)


def _rpc(method, params):
    from rugfilter import helius
    return helius.rpc(method, params)


def largest(mint, budget):
    """[{owner, acct, amount, program_owner}] of the 20 largest token accounts (Helius, 3 credits), None over the cap."""
    if not budget.take(3):
        return None
    if "largest" in FETCH:
        return FETCH["largest"](mint)
    res = _rpc("getTokenLargestAccounts", [mint])
    accts = [(a["address"], float(a.get("uiAmount") or 0)) for a in (res.get("value") or [])][:20]
    if not accts:
        return []
    info = _rpc("getMultipleAccounts", [[a for a, _ in accts], {"encoding": "jsonParsed"}]).get("value") or []
    rows = []
    for (addr, amt), acc in zip(accts, info):
        try:
            rows.append({"acct": addr, "owner": acc["data"]["parsed"]["info"]["owner"], "amount": amt})
        except (TypeError, KeyError):
            continue
    kinds = _rpc("getMultipleAccounts", [[r["owner"] for r in rows],
                                         {"encoding": "base64", "dataSlice": {"offset": 0, "length": 0}}]).get("value") or []
    for r, acc in zip(rows, kinds):
        r["program_owner"] = bool(acc) and acc.get("owner") != SYSTEM
    return rows


def supply(mint, budget):
    if not budget.take(1):
        return None
    if "supply" in FETCH:
        return FETCH["supply"](mint)
    v = _rpc("getTokenSupply", [mint])["value"]
    return float(v.get("uiAmount") or 0) or None


def txs(address, since_ts, budget, pages=1):
    """Raw parsed transactions of an address that changed a token balance since since_ts (newest first), None over the
    cap. 10 credits a page."""
    if not budget.take(10 * pages):
        return None
    if "txs" in FETCH:
        return FETCH["txs"](address, since_ts)
    from wallets import rpc
    out, _ = rpc.fetch(address, since_ts=since_ts, max_pages=pages)
    return out


def history(address, budget):
    """The OLDEST page (100) of an address's token-balance transactions (a token account: only that token's history;
    10 credits), None over the cap."""
    if not budget.take(10):
        return None
    if "history" in FETCH:
        return FETCH["history"](address)
    from wallets import rpc
    out, _ = rpc.fetch(address, max_pages=1, oldest_first=True)
    return out


def busy(address, budget):
    """(SOL balance, signatures among the last 1000, hours they span) of a wallet (2 credits), None over the cap."""
    if not budget.take(2):
        return None
    if "busy" in FETCH:
        return FETCH["busy"](address)
    sol = _rpc("getBalance", [address])["value"] / 1e9
    sigs = _rpc("getSignaturesForAddress", [address, {"limit": 1000}]) or []
    span = (sigs[0]["blockTime"] - sigs[-1]["blockTime"]) / 3600 if len(sigs) > 1 and sigs[-1].get("blockTime") else None
    return sol, len(sigs), span


def funder(wallet, budget):
    """The address that first sent SOL to the wallet (its oldest transactions; 10 credits, cached a week), or None."""
    if "funder" in FETCH:
        return FETCH["funder"](wallet) if budget.take(10) else None
    from event_calendar import http
    if http.cache_get(f"helius-first:{wallet}:10", 7 * 86400) is None and not budget.take(10):
        return None
    from rugfilter import helius
    for t in helius.wallet_first_txs(wallet, 10):
        for n in t.get("nativeTransfers") or []:
            if n.get("toUserAccount") == wallet and n.get("fromUserAccount") and n.get("amount", 0) > 0:
                return n["fromUserAccount"]
    return None


def token_accounts(owner, mints, budget):
    """{mint: ui amount} of the owner's balances of `mints` (both token programs, 2 credits), None over the cap."""
    if not budget.take(2):
        return None
    if "token_accounts" in FETCH:
        return FETCH["token_accounts"](owner, mints)
    want = set(mints)
    out = {}
    for prog in TOKEN_PROGRAMS:
        res = _rpc("getTokenAccountsByOwner", [owner, {"programId": prog}, {"encoding": "jsonParsed"}])
        for a in res.get("value") or []:
            try:
                info = a["account"]["data"]["parsed"]["info"]
            except (TypeError, KeyError):
                continue
            m = info.get("mint")
            if m in want:
                out[m] = out.get(m, 0.0) + float((info.get("tokenAmount") or {}).get("uiAmount") or 0)
    return out


def _keys(tx):
    return [k["pubkey"] if isinstance(k, dict) else k for k in tx["transaction"]["message"]["accountKeys"]]


def outflows(tx, wallet, mint):
    """[(dest owner, ui amount, kind)] of `mint` leaving `wallet` in one raw tx: kind "sell" when the wallet got SOL /
    a stablecoin for it (a swap), else "transfer"."""
    meta = tx.get("meta") or {}
    if meta.get("err"):
        return []
    bal = {}
    for sign, side in ((-1, "preTokenBalances"), (1, "postTokenBalances")):
        for b in meta.get(side) or []:
            if b.get("mint") != mint:
                continue
            try:
                amt = int(b["uiTokenAmount"]["amount"]) / 10 ** int(b["uiTokenAmount"]["decimals"])
            except (KeyError, TypeError, ValueError):
                continue
            o = b.get("owner")
            bal[o] = bal.get(o, 0.0) + sign * amt
    d = bal.get(wallet, 0.0)
    if d >= -1e-9:
        return []
    from wallets import rpc
    kind = "sell" if any(r["kind"] == "sell" and r["mint"] == mint for r in rpc.parse(tx, wallet, 150.0)) else "transfer"
    dests = sorted(((o, v) for o, v in bal.items() if o != wallet and v > 1e-9), key=lambda x: -x[1])
    if not dests:
        return [(None, -d, kind)]
    return [(o, v, kind) for o, v in dests[:3]]


def tx_ts(tx):
    return int(tx.get("blockTime") or 0)


def tx_sig(tx):
    try:
        return tx["transaction"]["signatures"][0]
    except (KeyError, IndexError, TypeError):
        return None
