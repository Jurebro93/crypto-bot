"""Settings of the MemeSonar MCP server, all from the environment (never written in code or in a repository).

    MCP_SERVER_KEY     the key Grok (or any MCP client) sends: "Authorization: Bearer <MCP_SERVER_KEY>". Required.
    MEMESONAR_URL      the MemeSonar app, default https://app.memesonar.app
    MEMESONAR_API_KEY  the key of the app's /api/mcp/* (Render env MCP_API_KEY). Required.
    MCP_HOST, MCP_PORT where the server listens, default 0.0.0.0:3001
"""
import os

SERVER_KEY = (os.environ.get("MCP_SERVER_KEY") or "").strip()
MEMESONAR_URL = (os.environ.get("MEMESONAR_URL") or "https://app.memesonar.app").rstrip("/")
MEMESONAR_API_KEY = (os.environ.get("MEMESONAR_API_KEY") or "").strip()
HOST = os.environ.get("MCP_HOST") or "0.0.0.0"
PORT = int(os.environ.get("MCP_PORT") or 3001)
TIMEOUT_S = float(os.environ.get("MEMESONAR_TIMEOUT_S") or 15)


def check():
    """The settings that are missing, as one sentence; '' when the server can start."""
    missing = [n for n, v in (("MCP_SERVER_KEY", SERVER_KEY), ("MEMESONAR_API_KEY", MEMESONAR_API_KEY)) if not v]
    return f"Nedostaje: {', '.join(missing)} (vidi README.md)." if missing else ""
