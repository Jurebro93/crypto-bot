"""Jupiter Trigger API v1 (limit orders on chain): the Autopilot's take profit as an order Jupiter fills by itself when
the price reaches it, even for a wick of a second (10.11., Jure: "dodaj Jupiter trigger: take profit na određen market
cap, Jupiter proda kad ga dosegne"; "da, v1").

Step 1 (this module, now): probe(). It asks Jupiter for the order of one open real position (createOrder: its
tokens for the SOL its TP is worth) and records what came back: whether Jupiter accepts the request, which fields it
answers with, the error if any. Nothing is signed and nothing is sent: an order exists only after /execute with a
signed transaction. The page's button "Provjeri Jupiter Trigger (bez novca)" asks run_trade.py for it (settings
"trigger_probe_req"), the answer is in settings "trigger_probe".

Step 2 (after a probe that passed, with the owner watching): place, cancel before any sale of ours, and book the fill.

API (developers.jup.ag/docs/trigger/v1, the research of 10.11.): POST {base}/createOrder {inputMint, outputMint,
maker, payer, params: {makingAmount, takingAmount, expiredAt?}, computeUnitPrice: "auto"} -> {requestId,
transaction (base64, unsigned), order?}; POST {base}/execute {signedTransaction, requestId}; POST
{base}/cancelOrder {maker, order, computeUnitPrice}; GET {base}/getTriggerOrders?user=&orderStatus=active|history.
Amounts are strings in raw units (making: the token's raw units, taking: lamports). base: api.jup.ag/trigger/v1 with
JUP_API_KEY (x-api-key), lite-api.jup.ag/trigger/v1 without.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from event_calendar import http
from trade import jupiter

SOL = jupiter.SOL
LAMPORTS = 1_000_000_000


def base():
    return os.environ.get("JUP_TRIGGER_URL") or (
        "https://api.jup.ag/trigger/v1" if jupiter.KEY else "https://lite-api.jup.ag/trigger/v1")


def _call(path, params=None, body=None, timeout=20):
    url = f"{base()}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
    headers = {"User-Agent": http.USER_AGENT, "Accept": "application/json"}
    if jupiter.KEY:
        headers["x-api-key"] = jupiter.KEY
    data = None
    if body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data, headers), timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:   # Jupiter answers its errors with a JSON body
        try:
            return json.loads(e.read() or b"{}") | {"http_status": e.code}
        except ValueError:
            return {"http_status": e.code, "error": str(e)}


def create_order(maker, input_mint, making_raw, taking_lamports, expired_at=None, output_mint=SOL):
    """The unsigned transaction of a limit sell (input tokens -> at least taking_lamports of SOL). Signs nothing."""
    params = {"makingAmount": str(int(making_raw)), "takingAmount": str(int(taking_lamports))}
    if expired_at:
        params["expiredAt"] = str(int(expired_at))
    return _call("/createOrder", body={"inputMint": input_mint, "outputMint": output_mint, "maker": maker,
                                        "payer": maker, "params": params, "computeUnitPrice": "auto"})


def orders(user, status="active", page=1):
    return _call("/getTriggerOrders", params={"user": user, "orderStatus": status, "page": page})


def taking_for(qty_raw, decimals, tp_price_usd, sol_usd):
    """Lamports the position's tokens are worth at the TP price (USD per whole token) at this SOL price."""
    if not (qty_raw and tp_price_usd and sol_usd and decimals is not None):
        return None
    return int(qty_raw / 10 ** decimals * tp_price_usd / sol_usd * LAMPORTS)


def _shape(resp):
    """What a probe keeps of an answer: its keys and the error; never the transaction itself."""
    if not isinstance(resp, dict):
        return {"type": type(resp).__name__}
    out = {"keys": sorted(resp.keys())}
    for k in ("error", "code", "http_status", "cause", "message"):
        if k in resp:
            out[k] = str(resp[k])[:300]
    if "transaction" in resp:
        out["transaction_len"] = len(str(resp.get("transaction") or ""))
    return out


def probe(con, league_auto, maker, decimals_fn, sol_usd_fn, now=None):
    """Step 1: ask Jupiter for the TP order of the newest open real position with a TP and record the answer's shape
    (settings "trigger_probe"). league_auto: {league_id: auto rule dict}. Signs and sends nothing."""
    from trade import settings
    now = int(now or time.time())
    res = {"ts": now, "base": base(), "key": bool(jupiter.KEY)}
    row = None
    for pid, token, sym, lid, qty in con.execute(
            "SELECT id, token, symbol, league_id, qty_left FROM positions WHERE status='open' AND mode='live' "
            "AND league_id IS NOT NULL ORDER BY id DESC"):
        rule = league_auto.get(lid) or {}
        if rule.get("mode") == "tpsl" and rule.get("tp_px") and qty:
            row = (pid, token, sym, qty, rule["tp_px"])
            break
    if not maker:
        res.update(ok=False, why="wallet nije postavljen")
    elif row is None:
        res.update(ok=False, why="nema otvorene prave pozicije s TP-om za probu")
    else:
        pid, token, sym, qty, tp_px = row
        try:
            dec, sol_usd = decimals_fn(token), sol_usd_fn()
            taking = taking_for(qty, dec, tp_px, sol_usd)
            if not taking:
                res.update(ok=False, why=f"ne znam vrijednost TP-a u SOL-u (decimale {dec}, SOL ${sol_usd})")
            else:
                resp = create_order(maker, token, qty, taking, expired_at=now + 7 * 86400)
                shape = _shape(resp)
                ok = "transaction" in (resp or {}) and not shape.get("error") and not shape.get("http_status")
                res.update(ok=ok, position=pid, symbol=sym, making=str(qty), taking_sol=round(taking / LAMPORTS, 6),
                           answer=shape)
        except Exception as e:  # noqa: BLE001 - the probe reports, it never breaks the trade loop
            res.update(ok=False, why=f"{type(e).__name__}: {e}"[:300])
    settings.put(con, "trigger_probe", res, "bot")
    print(f"jupiter trigger proba: {'PROŠLA' if res.get('ok') else 'NIJE PROŠLA'} {json.dumps(res, ensure_ascii=False)[:600]}",
          flush=True)
    return res
