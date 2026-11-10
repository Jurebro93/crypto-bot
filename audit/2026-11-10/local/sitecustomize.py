"""Lokalno "tržište" za prijedlog dizajna (10.11.2026.): NIJE dio aplikacije i ne ide u produkciju.

Python ovu datoteku sam učita pri svakom startu kad je njezin direktorij u PYTHONPATH (run_local.sh ga postavlja),
pa vrijedi i za dijete koje gradi teške stranice (run_ui.py --render). Radi dvije stvari:
  1. upite na DexScreener (/tokens/v1/solana/<mintovi>) i Jupiter (price/v3) odgovara iz market.json koji napiše
     seed_app.py, da demo pozicije, prijedlozi i Autopilot imaju "živu" cijenu kao na običan dan;
  2. SVAKI drugi odlazni HTTP poziv odmah odbija (URLError), tako da lokalna aplikacija ne zove nijedan vanjski
     servis (ni besplatni ni plaćeni) i stranice ne čekaju na mrežu.
  3. Solana RPC (getBalance, getTokenAccountsByOwner) odgovara stalnim stanjem probnog walleta (1.842 SOL, 25 USDC),
     da kartica Autopilota ima brojeve; ništa se ne potpisuje i ne šalje.
  4. u procesu run_ui.py (ne u djetetu --render) svakih 30 s upiše "heartbeat" u trade.db, kao što to u produkciji
     radi run_trade.py; bez toga Autopilot nakon 3 min piše "Trade proces ne radi".
Poziv na 127.0.0.1 / localhost prolazi normalno.
"""
import io
import json
import os
import urllib.error
import urllib.parse
import urllib.request

_FEED = os.environ.get("UIPROP_MARKET") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "market.json")
_REAL = urllib.request.urlopen
_CACHE = {"mtime": 0, "data": {}}


def _market():
    try:
        m = os.path.getmtime(_FEED)
        if m != _CACHE["mtime"]:
            with open(_FEED, encoding="utf-8") as f:
                _CACHE["data"], _CACHE["mtime"] = json.load(f), m
    except (OSError, ValueError):
        pass
    return _CACHE["data"]


class _Resp(io.BytesIO):
    status = 200
    headers = {}

    def getcode(self):
        return 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _urlopen(req, *a, **kw):
    url = req.full_url if hasattr(req, "full_url") else str(req)
    u = urllib.parse.urlsplit(url)
    host = (u.hostname or "").lower()
    if host in ("127.0.0.1", "localhost", "::1"):
        return _REAL(req, *a, **kw)
    mk = _market()
    if host == "api.dexscreener.com" and u.path.startswith("/tokens/v1/solana/"):
        mints = urllib.parse.unquote(u.path.rsplit("/", 1)[-1]).split(",")
        return _Resp(json.dumps([mk[m] for m in mints if m in mk]).encode())
    if host == "api.dexscreener.com" and u.path.startswith("/token-pairs/v1/solana/"):
        m = urllib.parse.unquote(u.path.rsplit("/", 1)[-1])
        return _Resp(json.dumps([mk[m]] if m in mk else []).encode())
    if host == "lite-api.jup.ag" and u.path.startswith("/price/"):
        ids = dict(urllib.parse.parse_qsl(u.query)).get("ids", "").split(",")
        return _Resp(json.dumps({m: {"usdPrice": float(mk[m]["priceUsd"]), "liquidity": mk[m]["liquidity"]["usd"]}
                                 for m in ids if m in mk}).encode())
    if host in ("api.mainnet-beta.solana.com", "mainnet.helius-rpc.com"):
        body = getattr(req, "data", None) or (a[0] if a else None) or b"{}"
        try:
            method = json.loads(body).get("method")
        except (ValueError, AttributeError):
            method = None
        if method == "getBalance":
            return _Resp(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"context": {"slot": 1}, "value": 1_842_000_000}}).encode())
        if method == "getTokenAccountsByOwner":
            acc = {"pubkey": "UiPropUsdcAccount1111111111111111111111111", "account": {"owner": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                   "data": {"parsed": {"info": {"tokenAmount": {"amount": "25000000", "decimals": 6}}}}}}
            return _Resp(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"context": {"slot": 1}, "value": [acc]}}).encode())
    raise urllib.error.URLError("uiprop: lokalno pokretanje, bez mreže (%s)" % host)


urllib.request.urlopen = _urlopen


def _heartbeat():
    import sqlite3
    import sys
    import threading
    import time
    argv = " ".join(sys.argv)
    if "run_ui.py" not in argv or "--render" in argv:
        return
    db = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "trade.db")

    def loop():
        while True:
            try:
                if os.path.exists(db):
                    con = sqlite3.connect(db, timeout=5)
                    con.execute("INSERT OR REPLACE INTO settings VALUES ('heartbeat', ?, ?, 'uiprop')", (str(int(time.time())), int(time.time())))
                    con.commit()
                    con.close()
            except sqlite3.Error:
                pass
            time.sleep(30)
    threading.Thread(target=loop, daemon=True, name="uiprop-heartbeat").start()


_heartbeat()
