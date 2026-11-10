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


def addresses(con=None):
    """10.11. (Jure: graf vrijednosti walleta): (address to show and measure, address of the key or None, address the
    owner saved on /pravi-trade or the env one, or None). The key comes first when it can sign, then what the owner
    saved on the page (settings wallet_pub), then SOLANA_PUBLIC_KEY: the same order ui/pravitrade._addr has, kept
    here so the trade process (trade/equity.py) can find the wallet without importing the whole ui package.
    con: a trade.db connection (None = only the key and the env are looked at). Never raises."""
    key = None
    if can_sign():
        try:
            key = address()
        except Exception:  # noqa: BLE001 - a key that cannot be parsed signs nothing: fall back to the saved address
            key = None
    saved = None
    if con is not None:
        try:
            row = con.execute("SELECT v FROM settings WHERE k='wallet_pub'").fetchone()
            saved = (json.loads(row[0]) if row and row[0] else None) or None
        except Exception:  # noqa: BLE001 - no settings table yet
            saved = None
    env = os.environ.get("SOLANA_PUBLIC_KEY") or None
    return key or saved or env, key, saved or env


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


def token_decimals(mint):
    """Decimals of a mint (getTokenSupply, one standard RPC call); trade/equity.py asks once per mint per process to
    turn a raw quantity into whole tokens for the price."""
    return int(rpc("getTokenSupply", [mint])["value"]["decimals"])


TOKEN_PROGRAMS = {"TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PQnx5ujeXu69C1"}


def token_accounts(owner, mint):
    """[(account address, raw amount, decimals, token program)] of this wallet for one mint."""
    res = rpc("getTokenAccountsByOwner", [owner, {"mint": mint}, {"encoding": "jsonParsed"}])
    out = []
    for a in res["value"]:
        ta = a["account"]["data"]["parsed"]["info"]["tokenAmount"]
        out.append((a["pubkey"], int(ta["amount"]), int(ta.get("decimals") or 0), a["account"].get("owner")))
    return out


def send(signed_tx_b64):
    """Send a signed transaction through our RPC; returns the signature."""
    return rpc("sendTransaction", [signed_tx_b64, {"encoding": "base64", "maxRetries": 3}])


def confirmed(signature, wait_s=45, sleep=2.0):
    """True when the transaction landed without error, False when it landed with an error, None when unknown."""
    import time as _t
    end = _t.time() + wait_s
    while _t.time() < end:
        st = rpc("getSignatureStatuses", [[signature], {"searchTransactionHistory": True}])["value"][0]
        if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
            return st.get("err") is None
        _t.sleep(sleep)
    return None


def sign_raw(tx_bytes, keypair=None):
    """Sign an unsigned VersionedTransaction given as raw bytes (PumpPortal); returns base64."""
    return sign(base64.b64encode(tx_bytes).decode(), keypair)


def close_empty(owner_kp, mint):
    """Close this wallet's empty token accounts for `mint`, giving the ~0.002 SOL rent of each back.
    Returns lamports reclaimed (0 when nothing was empty or the RPC failed)."""
    from solders.hash import Hash
    from solders.instruction import AccountMeta, Instruction
    from solders.message import MessageV0
    from solders.pubkey import Pubkey
    from solders.transaction import VersionedTransaction
    owner = owner_kp.pubkey()
    empty = [(acc, prog) for acc, amount, _, prog in token_accounts(str(owner), mint) if amount == 0
             and prog in TOKEN_PROGRAMS]
    if not empty:
        return 0
    lamports = sum(rpc("getBalance", [acc])["value"] for acc, _ in empty)
    ixs = [Instruction(Pubkey.from_string(prog), bytes([9]),   # SPL Token CloseAccount
                       [AccountMeta(Pubkey.from_string(acc), False, True), AccountMeta(owner, False, True),
                        AccountMeta(owner, True, False)]) for acc, prog in empty]
    bh = Hash.from_string(rpc("getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"])
    tx = VersionedTransaction(MessageV0.try_compile(owner, ixs, [], bh), [owner_kp])
    sig = send(base64.b64encode(bytes(tx)).decode())
    return lamports if confirmed(sig, wait_s=30) else 0
