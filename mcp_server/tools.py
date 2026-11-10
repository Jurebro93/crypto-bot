"""The four tools of the MemeSonar MCP server. Each asks the MemeSonar app (/api/mcp/*) with MEMESONAR_API_KEY, so
the data is always the app's own, live, and the server holds no database and no wallet key.

execute_trade never trades: it puts a REQUEST in the queue on the Autopilot page and the owner taps Odobri / Odbij
(ui/mcpapi.py in the app). The client is an LLM that reads public posts, and a crafted post can make it ask for a
trade; real money moves only on the owner's tap.
"""
import httpx

import config


def _headers():
    return {"Authorization": f"Bearer {config.MEMESONAR_API_KEY}", "Accept": "application/json",
            "User-Agent": "memesonar-mcp/1.0"}


def _get(path, params=None):
    with httpx.Client(timeout=config.TIMEOUT_S) as c:
        r = c.get(f"{config.MEMESONAR_URL}{path}", params=params, headers=_headers())
    return _json(r)


def _post(path, body):
    with httpx.Client(timeout=config.TIMEOUT_S) as c:
        r = c.post(f"{config.MEMESONAR_URL}{path}", json=body, headers=_headers())
    return _json(r)


def _json(r):
    try:
        data = r.json()
    except ValueError:
        data = {"error": f"MemeSonar answered HTTP {r.status_code} without JSON"}
    if r.status_code >= 400 and isinstance(data, dict):
        data.setdefault("http_status", r.status_code)
    return data


def get_market_signals(source: str = "") -> dict:
    """Meme coins being called right now on Solana by the X and Telegram accounts MemeSonar tracks, and buys of the
    wallets it follows: per token the callers, first/last call time, and the live market (price, market cap,
    liquidity, volume, 5m/1h/24h change, buys share of the last hour's transactions as on-chain sentiment). While
    MemeSonar's market scanner runs (shadow, it never buys) also tokens found without a caller (source scan) and
    betas of the top runners (source beta), with beta_score, x_momentum_score, x_early and lead_time_min.
    source: caller | wallet | scan | beta to filter; empty = all."""
    return _get("/api/mcp/signals", {"source": source} if source else None)


def get_token_details(token_address: str) -> dict:
    """One Solana token by its address: live market, who called it in the last hour, and MemeSonar's open
    position in it (if any). Tokens under $30k market cap are flagged (MemeSonar does not trade them)."""
    return _get("/api/mcp/token", {"address": token_address})


def get_portfolio_status() -> dict:
    """The MemeSonar Autopilot: mode (live / trial / off), wallet value in SOL (free, in positions, PnL, 24 h),
    the owner's limits, every open position (entries, average entry market cap, market cap now, PnL %, exit rule)
    and the open orders (DCA, requests waiting for the owner)."""
    return _get("/api/mcp/portfolio")


def execute_trade(token_address: str, amount: float, side: str, require_approval: bool = True, reason: str = "") -> dict:
    """Ask MemeSonar for a trade. It is NOT executed here: it waits on the Autopilot page until the owner approves
    it (15 minutes). side: "buy" (amount in SOL, within the owner's per-trade limit) or "sell" (amount as a share
    of the open position, 0.25 = 25 %, 1 = all). require_approval must stay true. reason: one line for the owner."""
    if require_approval is not True:
        return {"error": "MemeSonar executes no trade without the owner's approval; call again with require_approval=true"}
    return _post("/api/mcp/trade", {"token": token_address, "amount": amount, "side": side,
                                    "require_approval": True, "reason": reason})
