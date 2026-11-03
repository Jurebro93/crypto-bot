"""Jupiter swap APIs: one order call (quote + unsigned transaction), one execute call. Two independent endpoints:

- "v2": Swap API v2, https://api.jup.ag/swap/v2 (docs: developers.jup.ag/docs/swap/order-and-execute). Metis, JupiterZ
  (RFQ), Dflow and OKX compete on every order; Jupiter lands the transaction. Keyless works (0.5 order requests/s,
  /execute 20/s); with JUP_API_KEY (free key from portal.jup.ag) the limits are higher.
- "ultra": the older Ultra API on lite-api.jup.ag (deprecated by Jupiter but still answering, 3.11.2026), used when
  v2 does not answer or fails.

Both route every Solana DEX including the pump.fun bonding curve, pick slippage and priority fee themselves and land
the transaction through Jupiter's own sender, so no RPC or Jito setup is needed for a swap.
"""
import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from event_calendar import http

SOL = "So11111111111111111111111111111111111111112"
KEY = os.environ.get("JUP_API_KEY")
BASES = {
    "v2": os.environ.get("JUP_SWAP_URL") or "https://api.jup.ag/swap/v2",
    "ultra": os.environ.get("JUP_ULTRA_URL") or ("https://api.jup.ag/ultra/v1" if KEY else "https://lite-api.jup.ag/ultra/v1"),
}
BASE = BASES["ultra"]   # kept for older callers
# execute may be repeated with the same signed transaction + requestId for up to 2 minutes: it never executes twice,
# it only answers the status (Jupiter docs, "Transaction Status Polling")
EXECUTE_TRIES = 3
EXECUTE_WAIT_S = 5

# /execute codes worth trying again on another route (the transaction did not land, nothing was spent)
NOT_LANDED = {-1, -1000, -1001, -1002, -1004, -1005, -1006, -2000, -2001, -2003, -2005}
ERRORS_HR = {
    -1: "nalog je istekao prije slanja", -2: "transakcija krivo potpisana", -3: "transakcija promijenjena",
    -1000: "transakcija nije stigla u blok", -1001: "nepoznata greška kod Jupitera", -1002: "neispravna transakcija",
    -1003: "transakcija nije potpuno potpisana", -1004: "neispravna visina bloka", -1005: "transakcija je istekla",
    -1006: "isteklo vrijeme čekanja", -2000: "RFQ transakcija nije stigla u blok", -2003: "RFQ ponuda istekla",
    -2004: "market maker je odbio swap", 6001: "cijena se pomaknula više od dopuštenog klizanja (slippage)",
}


def _call(path, params=None, body=None, timeout=20, route="ultra"):
    url = f"{BASES[route]}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
    headers = {"User-Agent": http.USER_AGENT, "Accept": "application/json"}
    if KEY:
        headers["x-api-key"] = KEY
    data = None
    if body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data, headers), timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:   # 400 "Failed to get quotes" etc. come with a JSON body
        try:
            return json.loads(e.read() or b"{}") | {"http_status": e.code}
        except ValueError:
            raise e


def order(input_mint, output_mint, amount_raw, taker=None, route="v2"):
    """Quote, plus an unsigned transaction (base64) when taker is given and can pay.
    Without funds the quote still comes back, with errorCode 1 'Insufficient funds' and an empty transaction."""
    params = {"inputMint": input_mint, "outputMint": output_mint, "amount": int(amount_raw)}
    if taker:
        params["taker"] = taker
    return _call("/order", params, route=route)


def execute(signed_tx_b64, request_id, route="v2"):
    """Send the signed transaction; a dropped connection is retried with the same payload (safe, see above).
    Returns status ('Success'/'Failed'), code, signature, totalInputAmount/totalOutputAmount; None if Jupiter
    never answered (the caller must then check the wallet before trying anything else)."""
    for i in range(EXECUTE_TRIES):
        try:
            return _call("/execute", body={"signedTransaction": signed_tx_b64, "requestId": request_id},
                         timeout=60, route=route)
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, ValueError):
            if i < EXECUTE_TRIES - 1:
                time.sleep(EXECUTE_WAIT_S)
    return None


def cost_pct(o):
    """Round-trip cost of a quote in percent: USD in vs USD out (price impact + Jupiter fee)."""
    i, out = float(o.get("inUsdValue") or 0), float(o.get("outUsdValue") or 0)
    return round(100 * (1 - out / i), 2) if i > 0 else None


def fee_lamports(o):
    """Network costs the wallet pays on top of the swap: signature + priority fee + rent for a new token account
    (0 when Jupiter or a market maker pays them: gasless)."""
    total = 0
    for k in ("signatureFeeLamports", "prioritizationFeeLamports", "rentFeeLamports"):
        payer = o.get(k.replace("Lamports", "Payer"))
        if payer and payer != o.get("taker"):
            continue
        total += int(o.get(k) or 0)
    return total


def explain(code, error=None):
    return ERRORS_HR.get(code) or error or (f"greška {code}" if code is not None else "nepoznata greška")
