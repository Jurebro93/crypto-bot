"""The hot wallet: address from env, signing with solders (pip install solders base58).

SOLANA_PRIVATE_KEY: base58 secret (Phantom "export private key") or the JSON byte array of a keypair file.
SOLANA_PUBLIC_KEY: address only, enough for dry-run quotes that include a transaction.
Never commit or paste the private key anywhere; set it only in the server's environment secrets.
"""
import base64
import json
import os
import urllib.request

from event_calendar import http


def _keypair():
    secret = os.environ.get("SOLANA_PRIVATE_KEY", "").strip()
    if not secret:
        return None
    from solders.keypair import Keypair
    if secret.startswith("["):
        return Keypair.from_bytes(bytes(json.loads(secret)))
    return Keypair.from_base58_string(secret)


def address():
    kp = _keypair()
    return str(kp.pubkey()) if kp else (os.environ.get("SOLANA_PUBLIC_KEY") or None)


def can_sign():
    return bool(os.environ.get("SOLANA_PRIVATE_KEY", "").strip())


def sign(tx_b64, keypair=None):
    """Sign a base64 VersionedTransaction from Jupiter as its fee payer; returns base64."""
    from solders.transaction import VersionedTransaction
    kp = keypair or _keypair()
    if kp is None:
        raise RuntimeError("SOLANA_PRIVATE_KEY nije postavljen")
    tx = VersionedTransaction.from_bytes(base64.b64decode(tx_b64))
    return base64.b64encode(bytes(VersionedTransaction(tx.message, [kp]))).decode()


def _rpc_url():
    if os.environ.get("SOLANA_RPC_URL"):
        return os.environ["SOLANA_RPC_URL"]
    if os.environ.get("HELIUS_API_KEY"):
        return f"https://mainnet.helius-rpc.com/?api-key={os.environ['HELIUS_API_KEY']}"
    return "https://api.mainnet-beta.solana.com"


def rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(_rpc_url(), body, {"Content-Type": "application/json", "User-Agent": http.USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
    try:
        from usage import meter
        meter.helius(req.full_url, body, data)
    except ImportError:
        pass
    if "error" in data:
        raise RuntimeError(f"RPC {method}: {data['error']}")
    return data["result"]


def sol_balance(addr):
    return rpc("getBalance", [addr])["value"] / 1e9


def token_raw_balance(owner, mint):
    res = rpc("getTokenAccountsByOwner", [owner, {"mint": mint}, {"encoding": "jsonParsed"}])
    return sum(int(a["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"]) for a in res["value"])
