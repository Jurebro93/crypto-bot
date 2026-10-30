"""RugCheck public API (no key): https://api.rugcheck.xyz/swagger/index.html"""
import urllib.parse

from event_calendar import http

BASE = "https://api.rugcheck.xyz/v1"


def report(mint, ttl=300):
    """Full token report: authorities, top holders (with owner wallets), markets/LP, insider networks, risks."""
    return http.get_json(f"{BASE}/tokens/{urllib.parse.quote(mint, safe='')}/report", ttl=ttl)
