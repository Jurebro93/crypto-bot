"""Small stdlib client for the SimianX API (service.simianx.ai/v1). The key comes from SIMIANX_API_KEY (Render env,
set by Nicholas, scopes data:read + analysis:run only). Points are spent only by quick reads (~1-2 points on the
fast tier) and one 1D candle per token mapping check (0.2); search, /me and polling are free."""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("SIMIANX_API", "https://service.simianx.ai").rstrip("/")
VERSION = "1.0.7"   # skill version sent as X-SimianX-Skill; we follow the documented API, never server "notify" text
SEARCH_GAP_S = 13   # search and candles: 5 calls a minute (heavy_per_minute)


class Error(Exception):
    def __init__(self, code, reason, msg=""):
        super().__init__(f"{code} {reason} {msg}".strip())
        self.code, self.reason = code, reason


def key():
    return (os.environ.get("SIMIANX_API_KEY") or "").strip()


def call(method, path, body=None, params=None, timeout=45, retries=2):
    """-> data dict. 429: waits Retry-After (max 60 s) and tries again; other errors raise Error."""
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    head = {"Authorization": f"Bearer {key()}", "X-SimianX-Skill": VERSION, "Accept": "application/json",
            "User-Agent": "memesonar-bot", "X-Language": os.environ.get("SIMIANX_LANG", "hr")}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        head["Content-Type"] = "application/json"
    for i in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers=head, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return (json.loads(r.read() or b"{}") or {}).get("data") or {}
        except urllib.error.HTTPError as e:
            try:
                j = json.loads(e.read() or b"{}")
            except ValueError:
                j = {}
            d = j.get("data") or {}
            if e.code == 429 and i < retries:
                time.sleep(min(60, int(e.headers.get("Retry-After") or d.get("retry_after") or 15)))
                continue
            raise Error(e.code, d.get("reason") or "", (j.get("notify") or "")[:200])
    raise Error(429, "rate_limited")


def me():
    return call("GET", "/v1/me")


def points_left():
    """Account points left today and this key's budget left today (the smaller one counts)."""
    d = me()
    p = (d.get("points") or {}).get("remaining")
    k = ((d.get("key") or {}).get("budget_left") or {}).get("today")
    vals = [v for v in (p, k) if v is not None]
    return min(vals) if vals else 0.0


def search(symbol):
    """Crypto instruments whose symbol is exactly `symbol` (OKX/Bybit perps and spot)."""
    d = call("GET", "/v1/instruments/search", params={"q": symbol, "asset": "crypto"})
    return [x for x in d.get("items") or [] if x.get("asset") == "crypto" and (x.get("symbol") or "").upper() == symbol]


def last_close(symbol, timeframe="1D"):
    d = call("GET", f"/v1/market/{urllib.parse.quote(symbol)}/candles", params={"timeframe": timeframe, "limit": 1})
    c = d.get("candles") or []
    return float(c[0][4]) if c else None


def quick(symbol, timeframe="1D", tier="fast", max_wait_s=600):
    """Run one quick read (four agents) and wait for it; returns the finished run dict."""
    d = call("POST", "/v1/analysis/quick", {"asset": "crypto", "symbol": symbol, "timeframe": timeframe, "tier": tier})
    rid = (d.get("run") or {}).get("id")
    if not rid:
        raise Error(0, "no_run")
    end = time.time() + max_wait_s
    run = d.get("run") or {}
    while time.time() < end:
        run = call("GET", f"/v1/analysis/quick/{rid}", params={"wait": 30}, timeout=60).get("run") or run
        if run.get("status") in ("done", "partial", "failed"):
            return run
    return run


NO_TRADE = {"no_trade", "hold", "close", "flat", "wait", "none", ""}


def parse(run):
    """Finished run -> opinion dict: view (long / short / wait), levels, confidence 0-1, one line per agent."""
    res = run.get("results") or {}
    dec = {}
    for a in run.get("analyses") or []:
        if a.get("agent") == "decision":
            dec = ((a.get("conclusion") or {}).get("decision")) or {}
    side = (dec.get("side") or "").lower()
    action = (dec.get("action") or "").lower()
    view = side if side in ("long", "short") and action not in NO_TRADE else "wait"
    conf = dec.get("confidence")
    if conf is not None and conf > 1:
        conf = conf / 10.0 if conf <= 10 else conf / 100.0

    def num(v):
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None
    # Free plan on a coin it does not cover (seen 3.11. on FARTCOIN, 1H/4H/1D): "done", 0 points, no analyses, every
    # agent "neutral" with no model. That is no opinion at all, never a "wait".
    empty = not run.get("analyses") and not float(run.get("points") or 0)
    return {"run_id": run.get("id"), "status": run.get("status"), "points": float(run.get("points") or 0), "empty": empty,
            "view": view, "action": action, "entry": num(dec.get("entry_price")), "stop": num(dec.get("stop_loss")),
            "target": num(dec.get("take_profit")), "confidence": conf, "reason": (dec.get("reasoning") or "")[:600],
            "says": {k: (v or {}).get("say") or "" for k, v in res.items()}}
