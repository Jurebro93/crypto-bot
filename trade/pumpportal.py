"""Last-resort route when both Jupiter endpoints fail: PumpPortal's Local Transaction API
(https://pumpportal.fun/local-trading-api/trading-api). It builds a pump.fun / PumpSwap / Raydium / LaunchLab / Bonk
swap transaction; we sign it here and send it through our own RPC (Helius). No API key, nothing to register.
Cost: PumpPortal takes 0.5% of each trade (pumpportal.fun/fees) plus the priority fee below, which is why it is only
the fallback. There is no quote: what was spent and received is read from the wallet balances before and after.
"""
import json
import urllib.request

from event_calendar import http

URL = "https://pumpportal.fun/api/trade-local"
FEE_PCT = 0.5
SLIPPAGE_PCT = 15
PRIORITY_FEE_SOL = 0.0005


def trade_local(public_key, action, mint, amount, denominated_in_sol):
    """Unsigned VersionedTransaction bytes. amount: SOL (buy) or e.g. "100%" / "37.5%" of the wallet's tokens (sell)."""
    body = {"publicKey": public_key, "action": action, "mint": mint, "amount": amount,
            "denominatedInSol": "true" if denominated_in_sol else "false", "slippage": SLIPPAGE_PCT,
            "priorityFee": PRIORITY_FEE_SOL, "pool": "auto"}
    req = urllib.request.Request(URL, json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "User-Agent": http.USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = r.read()
    if r.status != 200 or not data or data[:1] == b"{":
        raise RuntimeError(f"PumpPortal: {data[:200]!r}")
    return data
