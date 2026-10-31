"""Helius getTransactionsForAddress paging + pump.fun transaction parsing for the retrospective study.

Cost: 10 credits per 100 full transactions. Every call goes through event_calendar.http so usage/meter counts it.
"""
import base64
import json
import os
import threading
import time
import urllib.request

from event_calendar import http

URL = "https://mainnet.helius-rpc.com/"
WSOL = "So11111111111111111111111111111111111111112"
PUMP_MINT_AUTHORITY = "TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM"  # signs every pump.fun create
PUMP_MIGRATION = "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg"  # signs every bonding-curve -> PumpSwap migration
SUPPLY = 1e9  # every pump.fun token has 1B supply, so market cap in SOL = price * 1e9
# pump.fun's own trading account ("mayhem" mode): gets its own 1B tokens at creation and then buys and sells
# against the curve. Its rows are kept as trades (protocol-made volume is a feature) but it is never a holder.
PROTOCOL = {"BwWK17cbHxwWBKZkUYvzxLcNQ1YVyaFezduWbtm2de6s"}

_credits = [0]
_lock = threading.Lock()


class _Throttle:
    def __init__(self, per_second):
        self.gap, self.last, self.lock = 1.0 / per_second, 0.0, threading.Lock()

    def wait(self):
        with self.lock:
            delay = self.last + self.gap - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self.last = time.monotonic()


# the live bot shares this key (plan limit 50 rps), so the study stays well below it
_RPS = _Throttle(float(os.environ.get("RETRO_RPS", "8")))


def credits_used():
    return _credits[0]


def rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(f"{URL}?api-key={os.environ['HELIUS_API_KEY']}", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": http.USER_AGENT})
    for attempt in range(5):
        _RPS.wait()
        data = http._fetch(req, 60)
        if "error" not in data:
            break
        if attempt == 4 or data["error"].get("code") not in (-32429, -32603, 429):
            raise RuntimeError(f"Helius {method}: {data['error']}")
        time.sleep(2 ** attempt)
    res = data["result"]
    if method == "getTransactionsForAddress":
        with _lock:
            _credits[0] += max(10, -(-len(res.get("data") or []) // 100) * 10)
    return res


def page(address, since=None, until=None, asc=True, limit=100, token=None):
    flt = {"status": "succeeded"}
    bt = {}
    if since is not None:
        bt["gte"] = int(since)
    if until is not None:
        bt["lt"] = int(until)
    if bt:
        flt["blockTime"] = bt
    opts = {"transactionDetails": "full", "encoding": "jsonParsed", "maxSupportedTransactionVersion": 1,
            "limit": limit, "sortOrder": "asc" if asc else "desc", "filters": flt}
    if token:
        opts["paginationToken"] = token
    res = rpc("getTransactionsForAddress", [address, opts])
    return res.get("data") or [], res.get("paginationToken")


def keys(tx):
    return [k["pubkey"] if isinstance(k, dict) else k for k in tx["transaction"]["message"]["accountKeys"]]


def logs(tx):
    return (tx.get("meta") or {}).get("logMessages") or []


def has_ix(tx, name):
    return any(l == f"Program log: Instruction: {name}" for l in logs(tx))


# ---------- pump.fun CreateEvent (anchor event in "Program data:" log) ----------

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58(raw):
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    return "1" * (len(raw) - len(raw.lstrip(b"\0"))) + out


def create_event(tx):
    """{name, symbol, uri, mint, curve, user, creator} from a pump.fun create tx, or None."""
    for l in logs(tx):
        if not l.startswith("Program data: "):
            continue
        try:
            raw = base64.b64decode(l[14:])
            pos, out = 8, {}
            for f in ("name", "symbol", "uri"):
                n = int.from_bytes(raw[pos:pos + 4], "little")
                if n > 400:
                    raise ValueError
                out[f] = raw[pos + 4:pos + 4 + n].decode("utf-8", "replace")
                pos += 4 + n
            for f in ("mint", "curve", "user"):
                out[f] = b58(raw[pos:pos + 32])
                pos += 32
            # CreateV2 events carry creator after user; older Create events end earlier
            out["creator"] = b58(raw[pos:pos + 32]) if len(raw) >= pos + 32 else out["user"]
            # other anchor events (trades) in the same log also decode; trust only one naming the created mint,
            # and take the curve from balances: the account left holding most of the supply
            info = create_info(tx)
            if info and out["mint"] == info["mint"]:
                out["curve"] = info["curve"]
                return out
        except (ValueError, IndexError):
            continue
    return None


def create_info(tx):
    """Fallback without the event: mint = non-WSOL mint, curve = biggest holder after the tx."""
    meta = tx.get("meta") or {}
    bal = [b for b in meta.get("postTokenBalances") or [] if b["mint"] != WSOL and b.get("owner") not in PROTOCOL]
    if not bal:
        return None
    big = max(bal, key=lambda b: float(b["uiTokenAmount"]["uiAmount"] or 0))
    return {"mint": big["mint"], "curve": big.get("owner"), "user": keys(tx)[0], "creator": keys(tx)[0],
            "name": "", "symbol": "", "uri": ""}


# ---------- trades on the bonding curve ----------

def trades(tx, mint, curve):
    """Rows (wallet, side, tokens, sol) for every non-curve owner whose `mint` balance moved, plus the
    curve's SOL and token change (exact price = curve_sol / -curve_tok, before fees)."""
    meta = tx.get("meta") or {}
    ks = keys(tx)
    lam = {k: (meta["postBalances"][i] - meta["preBalances"][i]) / 1e9 for i, k in enumerate(ks)}
    tok, wsol = {}, {}
    for sign, side in ((-1, "preTokenBalances"), (1, "postTokenBalances")):
        for b in meta.get(side) or []:
            amt = int(b["uiTokenAmount"]["amount"]) / 10 ** int(b["uiTokenAmount"]["decimals"])
            owner = b.get("owner")
            if b["mint"] == mint:
                tok[owner] = tok.get(owner, 0.0) + sign * amt
            elif b["mint"] == WSOL:
                wsol[owner] = wsol.get(owner, 0.0) + sign * amt
    curve_tok = tok.pop(curve, 0.0)
    curve_sol = lam.get(curve, 0.0)
    rows = []
    for owner, d in tok.items():
        if abs(d) < 1e-6:
            continue
        sol = lam.get(owner, 0.0) + wsol.get(owner, 0.0)
        if d > 0 and sol < 0:
            side = "buy"
        elif d < 0 and sol > 0:
            side = "sell"
        else:
            side = "in" if d > 0 else "out"  # transfer / airdrop / bundle helper paid by someone else
        rows.append((owner, side, d, sol))
    return rows, curve_sol, curve_tok
