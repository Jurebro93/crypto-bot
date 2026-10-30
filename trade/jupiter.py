"""Jupiter Ultra swap API: one quote+transaction call, one execute call. Docs: https://dev.jup.ag/docs/ultra

Ultra routes every Solana DEX including the pump.fun bonding curve, picks slippage and priority fee itself
and lands the transaction through its own sender, so no RPC or Jito setup is needed for a swap.
Free without a key on lite-api.jup.ag; with JUP_API_KEY (portal.jup.ag) it uses api.jup.ag with higher limits.
"""
import json
import os
import urllib.parse
import urllib.request

from event_calendar import http

SOL = "So11111111111111111111111111111111111111112"
KEY = os.environ.get("JUP_API_KEY")
BASE = os.environ.get("JUP_ULTRA_URL") or ("https://api.jup.ag/ultra/v1" if KEY else "https://lite-api.jup.ag/ultra/v1")


def _call(path, params=None, body=None, timeout=20):
    url = f"{BASE}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
    headers = {"User-Agent": http.USER_AGENT, "Accept": "application/json"}
    if KEY:
        headers["x-api-key"] = KEY
    data = None
    if body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    with urllib.request.urlopen(urllib.request.Request(url, data, headers), timeout=timeout) as r:
        return json.load(r)


def order(input_mint, output_mint, amount_raw, taker=None):
    """Quote, plus an unsigned transaction (base64) when taker is given and can pay.
    Without funds the quote still comes back, with error 'Insufficient funds' and an empty transaction."""
    params = {"inputMint": input_mint, "outputMint": output_mint, "amount": int(amount_raw)}
    if taker:
        params["taker"] = taker
    return _call("/order", params)


def execute(signed_tx_b64, request_id):
    """Send the signed transaction. Returns status ('Success'/'Failed'), signature, input/outputAmountResult."""
    return _call("/execute", body={"signedTransaction": signed_tx_b64, "requestId": request_id}, timeout=60)


def cost_pct(o):
    """Round-trip cost of a quote in percent: USD in vs USD out (price impact + Jupiter fee)."""
    i, out = float(o.get("inUsdValue") or 0), float(o.get("outUsdValue") or 0)
    return round(100 * (1 - out / i), 2) if i > 0 else None
