"""The data side of the MemeSonar MCP server (mcp_server/, Grok's tools), 10.11. (Jure: "MCP server MemeSonar:
get_market_signals, get_token_details, get_portfolio_status, execute_trade s require_approval").

    GET  /api/mcp/signals             what is being called right now (X, Telegram, followed wallets) + live market
    GET  /api/mcp/token?address=...   one token: live market, who called it in the last hour, our position in it
    GET  /api/mcp/portfolio           the Autopilot: mode, wallet value, open positions with PnL, open orders
    POST /api/mcp/trade               a trade REQUEST: it waits on the Autopilot page until the owner taps
                                      "Odobri" (then it goes through the owner's manual buy / sell); never executed here

Every call needs "Authorization: Bearer <MCP_API_KEY>" (Render env); without that variable the API answers 404, as
if it did not exist. Read-only on the databases except the request queue (trade settings "mcp_requests").
Why trades wait for the owner: the client is an LLM that reads public posts; a crafted post has already made Grok
order a transfer (May 2026). Real money moves only on the owner's tap (CLAUDE.md: pitaj prije).
"""
import hmac
import json
import os
import re
import time

from trade import settings

MINT = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")
MAX_PENDING = 10
REQUEST_TTL_S = 15 * 60   # a request the owner did not answer in 15 min is stale: the market moved


def key():
    return (os.environ.get("MCP_API_KEY") or "").strip()


def authorized(header):
    k = key()
    if not k:
        return None   # the API is off
    got = (header or "").strip()
    if got.lower().startswith("bearer "):
        got = got[7:].strip()
    return hmac.compare_digest(got.encode(), k.encode())


def _num(x, nd=6):
    try:
        return round(float(x), nd) if x is not None else None
    except (TypeError, ValueError):
        return None


def _market_row(m):
    if not m:
        return None
    tx = m.get("txns_h1") or 0
    buys = m.get("buys_h1") or 0
    return {"price_usd": _num(m.get("price"), 12), "market_cap_usd": _num(m.get("mcap"), 0),
            "liquidity_usd": _num(m.get("liq"), 0), "volume_1h_usd": _num(m.get("vol_h1"), 0),
            "volume_24h_usd": _num(m.get("vol_h24"), 0), "change_5m_pct": _num(m.get("ch_m5"), 2),
            "change_1h_pct": _num(m.get("ch_h1"), 2), "change_24h_pct": _num(m.get("ch_h24"), 2),
            "txns_1h": tx, "buys_1h": buys,
            # the share of buys in the last hour's transactions: the on-chain "sentiment" we can measure
            "buy_share_1h": round(buys / tx, 3) if tx else None}


def signals(now=None):
    """Tokens called in the last hour by the accounts the tool tracks (and buys of followed wallets), most callers
    first, each with its live market."""
    from ui import pravitrade
    now = now or time.time()
    rows = pravitrade.gather_callers(now)
    out = []
    for tok, callers, first_ts, last_ts, sym, live in rows:
        out.append({"token": tok, "symbol": sym, "callers": [{"who": w, "platform": p, "ts": int(ts)} for w, p, ts in callers],
                    "n_callers": len(callers), "first_call_ts": int(first_ts), "last_call_ts": int(last_ts),
                    "market": _market_row(live), "under_30k": bool(live and (live.get("mcap") or 0) < 30_000)})
    return {"ts": int(now), "source": "MemeSonar (X, Telegram, followed wallets; DexScreener live)", "signals": out}


def token(address, now=None):
    from ui import prijedlog, pravitrade
    now = now or time.time()
    address = (address or "").strip()
    if not MINT.fullmatch(address):
        return {"error": "not a Solana token address"}
    lv = prijedlog.live_market([address]) or {}
    m = lv.get(address)
    called = next(({"callers": [{"who": w, "platform": p, "ts": int(ts)} for w, p, ts in c], "symbol": s}
                   for tok, c, _f, _l, s, _m in pravitrade.gather_callers(now, limit=40) if tok == address), None)
    tcon = settings.connect()
    try:
        pos = [{"id": r[0], "sol_in": _num(r[1], 4), "opened_ts": r[2], "mode": r[3]} for r in tcon.execute(
            "SELECT id, sol_in, opened_ts, mode FROM positions WHERE token=? AND status='open'", (address,))]
    finally:
        tcon.close()
    return {"ts": int(now), "token": address, "market": _market_row(m),
            "under_30k": bool(m and (m.get("mcap") or 0) < 30_000), "called_last_hour": called,
            "our_open_lots": pos, "dexscreener": f"https://dexscreener.com/solana/{address}"}


def portfolio(now=None):
    from trade import executor
    from ui import pravitrade
    now = now or time.time()
    tcon = settings.connect()
    try:
        cfg = settings.merged(executor.load_config(), tcon)
        eq = pravitrade.equity_data(tcon, now).get("summary") or {}
        rows = tcon.execute("SELECT id, token, symbol, opened_ts, sol_in, league_id FROM positions WHERE status='open' "
                            "ORDER BY id").fetchall()
        demo = pravitrade._demo_sides(r[5] for r in rows)
        toks = sorted({r[1] for r in rows})
        now_mc, mc_ts = pravitrade._now_mcap(toks) if toks else ({}, None)
        by = {}
        for pid, tok, sym, ts, sin, lid in rows:
            mc, rule, _o = demo.get(lid, (None, None, False))
            g = by.setdefault(tok, {"token": tok, "symbol": sym, "lots": [], "exit": pravitrade._exit_words(rule)})
            g["lots"].append({"id": pid, "opened_ts": ts, "sol_in": _num(sin, 4), "entry_market_cap_usd": _num(mc, 0)})
        out = []
        for tok, g in by.items():
            w = [(l["entry_market_cap_usd"], l["sol_in"] or 0) for l in g["lots"]]
            wsum = sum(s for m, s in w if m and s)
            avg = wsum / sum(s / m for m, s in w if m and s) if wsum else None
            mc = now_mc.get(tok)
            g.update(sol_in=_num(sum(l["sol_in"] or 0 for l in g["lots"]), 4), avg_entry_market_cap_usd=_num(avg, 0),
                     market_cap_now_usd=_num(mc, 0), pnl_pct=_num((mc / avg - 1) * 100, 2) if mc and avg else None)
            out.append(g)
        raw = settings.raw(tcon)
        return {"ts": int(now), "price_ts": int(mc_ts) if mc_ts else None,
                "mode": "live" if (cfg["on"] and executor.armed()) else ("trial" if cfg["on"] else "off"),
                "wallet": {"value_sol": _num(eq.get("value_sol"), 4), "free_sol": _num(eq.get("sol"), 4),
                           "in_positions_sol": _num(eq.get("tokens_sol"), 4), "pnl_sol": _num(eq.get("pnl_sol"), 4),
                           "pnl_24h_sol": _num(eq.get("pnl_24h_sol"), 4)},
                "limits": {k: cfg.get(k) for k in ("size_sol", "max_sol_per_trade", "max_sol_per_day", "max_open",
                                                     "tp_default", "sl_default")},
                "open_positions": out,
                "open_orders": {"dca": raw.get("dca_orders") or [],
                                "waiting_for_owner": [r for r in raw.get("mcp_requests") or [] if r.get("status") == "pending"]}}
    finally:
        tcon.close()


def trade_request(body, now=None):
    """Queue a trade for the owner's approval. body: {token, side: buy|sell, amount, require_approval, reason}.
    buy: amount in SOL; sell: amount as a share of the position (0.25 = 25 %, 1 = all)."""
    now = int(now or time.time())
    body = body if isinstance(body, dict) else {}
    if body.get("require_approval") is False:
        return 400, {"error": "MemeSonar never executes a trade without the owner's approval; send require_approval=true"}
    tok = str(body.get("token") or "").strip()
    side = str(body.get("side") or "").strip().lower()
    if not MINT.fullmatch(tok):
        return 400, {"error": "token must be a Solana token address"}
    if side not in ("buy", "sell"):
        return 400, {"error": "side must be buy or sell"}
    try:
        amount = float(body.get("amount"))
    except (TypeError, ValueError):
        return 400, {"error": "amount must be a number (SOL for buy, share 0-1 for sell)"}
    tcon = settings.connect()
    try:
        cfg = settings.merged(__import__("trade.executor", fromlist=["load_config"]).load_config(), tcon)
        if side == "buy" and not 0 < amount <= cfg["max_sol_per_trade"]:
            return 400, {"error": f"buy amount must be between 0 and {cfg['max_sol_per_trade']} SOL (the owner's limit)"}
        if side == "sell":
            if not 0 < amount <= 1:
                return 400, {"error": "sell amount is a share of the position: 0 < amount <= 1"}
            if not tcon.execute("SELECT 1 FROM positions WHERE token=? AND status='open'", (tok,)).fetchone():
                return 400, {"error": "no open position in that token"}
        reqs = [r for r in settings.raw(tcon).get("mcp_requests") or [] if now - r.get("ts", 0) < 7 * 86400]
        if sum(1 for r in reqs if r.get("status") == "pending" and now - r["ts"] < REQUEST_TTL_S) >= MAX_PENDING:
            return 429, {"error": f"{MAX_PENDING} requests already wait for the owner"}
        rid = f"g{now}{len(reqs) % 1000:03d}"
        reqs.append({"id": rid, "ts": now, "token": tok, "side": side, "amount": amount, "status": "pending",
                     "reason": str(body.get("reason") or "")[:300], "client": "mcp"})
        settings.put(tcon, "mcp_requests", reqs[-100:], "mcp")
    finally:
        tcon.close()
    print(f"mcp: zahtjev {rid} {side} {tok[:6]} {amount:g} čeka odobrenje", flush=True)
    return 202, {"status": "pending_approval", "id": rid,
                 "message": "Waiting for the owner's approval on the MemeSonar Autopilot page; expires in 15 minutes."}


def pending(tcon, now=None):
    """The requests that still wait for the owner (younger than REQUEST_TTL_S), oldest first."""
    now = now or time.time()
    return [r for r in settings.raw(tcon).get("mcp_requests") or []
            if r.get("status") == "pending" and now - r.get("ts", 0) < REQUEST_TTL_S]


def decide(tcon, rid, status, note=""):
    reqs = list(settings.raw(tcon).get("mcp_requests") or [])
    hit = None
    for r in reqs:
        if r.get("id") == rid:
            r["status"], r["decided"], r["note"] = status, int(time.time()), note[:300]
            hit = r
    if hit is not None:
        settings.put(tcon, "mcp_requests", reqs, settings.owner())
    return hit


def answer(path, qs):
    """(status, JSON text) of a GET."""
    if path == "/api/mcp/signals":
        data = signals()
    elif path == "/api/mcp/token":
        data = token(qs.get("address") or qs.get("token"))
    elif path == "/api/mcp/portfolio":
        data = portfolio()
    else:
        return 404, json.dumps({"error": "unknown endpoint"})
    return (400 if "error" in data else 200), json.dumps(data, ensure_ascii=False)
