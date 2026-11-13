"""MemeSonar MCP server: Grok (or any MCP client) reads MemeSonar's live signals, token details and the Autopilot's
portfolio, and can ASK for a trade that the owner approves on the Autopilot page.

Transport: Streamable HTTP on MCP_HOST:MCP_PORT (default 0.0.0.0:3001), path /mcp. Every request needs
"Authorization: Bearer <MCP_SERVER_KEY>". Run:  python main.py   (see README.md, also for the ngrok tunnel).
"""
import hmac
import sys

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

import config
import tools

mcp = FastMCP("MemeSonar", instructions=(
    "MemeSonar: Solana meme coin signals (X/Telegram calls, followed wallets) with live market data, and the "
    "Autopilot's portfolio. execute_trade only queues a request for the owner's approval; never assume it executed."),
    host=config.HOST, port=config.PORT)

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
mcp.tool(annotations=READ)(tools.get_market_signals)
mcp.tool(annotations=READ)(tools.get_token_details)
mcp.tool(annotations=READ)(tools.get_portfolio_status)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False,
                                     openWorldHint=True))(tools.execute_trade)


class ApiKey(BaseHTTPMiddleware):
    """Authorization: Bearer <MCP_SERVER_KEY> on every request, compared in constant time."""

    async def dispatch(self, request, call_next):
        got = request.headers.get("authorization", "")
        got = got[7:].strip() if got.lower().startswith("bearer ") else ""
        if not config.SERVER_KEY or not hmac.compare_digest(got.encode(), config.SERVER_KEY.encode()):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


def app():
    a = mcp.streamable_http_app()
    a.add_middleware(ApiKey)
    return a


if __name__ == "__main__":
    problem = config.check()
    if problem:
        sys.exit(problem)
    print(f"MemeSonar MCP: http://{config.HOST}:{config.PORT}/mcp -> {config.MEMESONAR_URL}", flush=True)
    uvicorn.run(app(), host=config.HOST, port=config.PORT, log_level="info")
