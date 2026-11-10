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
    """The key a client must send: Render env MCP_API_KEY, else the one the owner made on the Autopilot page (trade
    settings "mcp_key", 10.11.: Jure "napravi mcp key, ne znam raditi s pip install")."""
    k = (os.environ.get("MCP_API_KEY") or "").strip()
    if k:
        return k
    try:
        tcon = settings.connect()
        try:
            return str(settings.raw(tcon).get("mcp_key") or "").strip()
        finally:
            tcon.close()
    except Exception:  # noqa: BLE001 - no database: the API is off
        return ""


def new_key(tcon, who):
    """Make (or replace) the owner's MCP key; the old one stops working at once."""
    import secrets
    k = "ms_" + secrets.token_urlsafe(32)
    settings.put(tcon, "mcp_key", k, who)
    return k


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


# ---------- the MCP endpoint itself (POST /mcp), hosted in the app -----------------------------------------------
# 10.11. (Jure: "ne znam raditi s pip install i ostalo"): the same four tools as mcp_server/, served by the app at
# https://app.memesonar.app/mcp, so Grok needs only that address and the key: nothing to install, no ngrok. The
# Streamable HTTP transport of MCP (spec 2025-06-18): JSON-RPC 2.0 in a POST, answered with application/json (no
# event stream: every tool answers at once); a notification gets 202; GET answers 405 (no server-initiated stream).
PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "MemeSonar", "title": "MemeSonar", "version": "1.0"}
INSTRUCTIONS = ("MemeSonar: Solana meme coin signals (X/Telegram calls, followed wallets) with live market data, and "
                "the Autopilot's portfolio. execute_trade only queues a request for the owner's approval on the "
                "MemeSonar Autopilot page; never assume it executed.")
_READ = {"readOnlyHint": True, "openWorldHint": True}
TOOLS = [
    {"name": "get_market_signals", "annotations": _READ,
     "description": ("Meme coins being called right now on Solana by the X and Telegram accounts MemeSonar tracks, and "
                     "buys of the wallets it follows: per token the callers, first/last call time and the live market "
                     "(price, market cap, liquidity, volume, 5m/1h/24h change, buys share of the last hour)."),
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "get_token_details", "annotations": _READ,
     "description": ("One Solana token by its address: live market, who called it in the last hour, MemeSonar's open "
                     "position in it. Tokens under $30k market cap are flagged (MemeSonar does not trade them)."),
     "inputSchema": {"type": "object", "properties": {"token_address": {"type": "string",
                                                                          "description": "Solana token mint address"}},
                     "required": ["token_address"]}},
    {"name": "get_portfolio_status", "annotations": _READ,
     "description": ("The MemeSonar Autopilot: mode (live / trial / off), wallet value in SOL, limits, every open "
                     "position (entries, average entry market cap, market cap now, PnL %, exit rule), open orders."),
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "execute_trade",
     "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
     "description": ("Ask MemeSonar for a trade. NOT executed here: it waits on the Autopilot page until the owner "
                     "approves it (15 minutes). side 'buy': amount in SOL within the owner's per-trade limit; side "
                     "'sell': amount as a share of the open position (0.25 = 25 %, 1 = all). require_approval must "
                     "be true. reason: one line for the owner."),
     "inputSchema": {"type": "object", "properties": {
         "token_address": {"type": "string", "description": "Solana token mint address"},
         "amount": {"type": "number", "description": "SOL for a buy, share 0-1 for a sell"},
         "side": {"type": "string", "enum": ["buy", "sell"]},
         "require_approval": {"type": "boolean", "default": True},
         "reason": {"type": "string"}}, "required": ["token_address", "amount", "side"]}},
]


_PAGE = {"limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
         "offset": {"type": "integer", "minimum": 0, "default": 0}}
_PAGED = " Paginated: limit 1-500 (default 100), offset; the answer has total and next_offset while more rows exist. Times are unix seconds."
TOOLS += [
    {"name": "get_caller_leaderboard", "annotations": _READ,
     "description": ("Every tracked caller (X and Telegram): handle, platform, followers, first/last call ts, total calls, "
                     "hit_rate (24 h high >= +50 %), avg and median price change 1 h / 24 h after the call (fractions), "
                     "x2_share (24 h high >= 2x), rug_count, avg market cap at call, call_power (0-100), and flags "
                     "big_name / rising_star / bragger (definitions in the answer). sort: score | hit_rate | calls | "
                     "avg_r24h | x2_share | followers | last_call_ts | power_rel." + _PAGED),
     "inputSchema": {"type": "object", "properties": {"platform": {"type": "string", "enum": ["x", "telegram"]},
                                                      "min_calls": {"type": "integer", "minimum": 0},
                                                      "sort": {"type": "string"}, **_PAGE}}},
    {"name": "get_caller_history", "annotations": _READ,
     "description": ("Every call of one caller, newest first: token, symbol, call ts, price and market cap at the call, "
                     "max/min within the first hour (minute candles), max within 24 h, price at 1 h / 24 h, rug flag, "
                     "and how many other callers called the same token within 15 min before / after. platform: x or "
                     "telegram (a Telegram channel may also be given as tg:<channel>)." + _PAGED),
     "inputSchema": {"type": "object", "properties": {"handle": {"type": "string"},
                                                      "platform": {"type": "string", "enum": ["x", "telegram"]},
                                                      "since_ts": {"type": "integer"}, **_PAGE},
                     "required": ["handle"]}},
    {"name": "get_token_history", "annotations": _READ,
     "description": ("One token: every call in order (caller, platform, ts, market cap at call), its price / market cap "
                     "series (at most 500 points), rug-check results (rug filter, RugCheck top check, rug archive) and "
                     "every Autopilot trade on it (demo trade it follows and the real position)."),
     "inputSchema": {"type": "object", "properties": {"token_address": {"type": "string"}}, "required": ["token_address"]}},
    {"name": "get_wallet_leaderboard", "annotations": _READ,
     "description": ("Tracked wallets: realized / unrealized PnL (SOL), win rate, median hold time, style, tier, scores and "
                     "the linked influencer handle when known. kind: influencer (a known influencer's wallet) or smart "
                     "(tier S/A/B)." + _PAGED),
     "inputSchema": {"type": "object", "properties": {"kind": {"type": "string", "enum": ["influencer", "smart"]}, **_PAGE}}},
    {"name": "get_wallet_history", "annotations": _READ,
     "description": ("One wallet's buys and sells, newest first: token, ts, side, SOL size, token amount, market cap in "
                     "SOL when the trade was seen live; plus its tier, PnL, win rate and linked handle." + _PAGED),
     "inputSchema": {"type": "object", "properties": {"address": {"type": "string"}, **_PAGE}, "required": ["address"]}},
    {"name": "get_wallet_clusters", "annotations": _READ,
     "description": ("Groups of wallets that buy together (common funder, same rug cluster, same-second buys) with members "
                     "and tokens, and clusters of callers that call the same tokens together; newest analysis snapshot."),
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "get_autopilot_trades", "annotations": _READ,
     "description": ("Every Autopilot trade (real money and trial), newest first; the DCA lots of a token are one trade. "
                     "Per trade: trade_id (its first position_id), lots, entry/exit ts, entry (SOL-weighted) / exit market "
                     "cap, sol_in, sol_back, fees_sol, cost_pct (swap cost of the buys), pnl_sol / pnl_pct, exit_reason "
                     "(TP / SL / time / smart sell / mirror / manual) and exit_note, and the signals at the entry: the "
                     "follow, callers of the last hour with call_power and stats, wallet buys with tier, the rug check "
                     "(verdict, top10 / bundle / sniper %), the minute path of the triggering call and the run-up from the "
                     "first call to the entry. status: open | closed." + _PAGED),
     "inputSchema": {"type": "object", "properties": {"since_ts": {"type": "integer"},
                                                      "status": {"type": "string", "enum": ["open", "closed"]}, **_PAGE}}},
    {"name": "get_unreviewed_trades", "annotations": _READ,
     "description": ("Closed Autopilot trades that have no trade_review yet, newest first (same fields as "
                     "get_autopilot_trades). Review each with submit_trade_review(trade_id)."),
     "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50}}}},
    {"name": "get_assistant_notes", "annotations": _READ,
     "description": ("The notes written through this API and what the owner did with them: kind (trade_review, "
                     "signal_opinion, suggestion, daily_summary), status (novo = waits, prihvaćeno, odbijeno, primijenjeno), "
                     "owner_note (the owner's reason), decided_ts. Use it to learn what was accepted or rejected." + _PAGED),
     "inputSchema": {"type": "object", "properties": {
         "status": {"type": "string", "enum": ["novo", "prihvaćeno", "odbijeno", "primijenjeno"]},
         "kind": {"type": "string", "enum": ["trade_review", "signal_opinion", "suggestion", "daily_summary"]}, **_PAGE}}},
    {"name": "get_scoring_config", "annotations": _READ,
     "description": ("The weights, thresholds, TP/SL defaults and filters the Autopilot uses: caller score weights, caller "
                     "verdict thresholds, the Autopilot's pick rules, copy filters, the real-money proof gate, Autopilot "
                     "limits, rug filter thresholds and hype weights. Read-only."),
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "submit_trade_review", "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
     "description": ("Write a review of one Autopilot trade for the owner: verdict dobar | loš | neutralan, confidence 0-1, "
                     "interpretation (what happened and why), improvement (what to do differently), evidence (JSON of the "
                     "numbers / links used). Shown on the trade's card; changes nothing in trading. Text up to 4000 "
                     "characters; at most 60 notes an hour."),
     "inputSchema": {"type": "object", "properties": {
         "position_id": {"type": "integer", "description": "trade_id from get_autopilot_trades"},
         "verdict": {"type": "string", "enum": ["dobar", "loš", "neutralan"]},
         "confidence": {"type": "number", "minimum": 0, "maximum": 1},
         "interpretation": {"type": "string", "maxLength": 4000}, "improvement": {"type": "string", "maxLength": 4000},
         "evidence": {"type": "object"}}, "required": ["position_id", "verdict", "interpretation"]}},
    {"name": "submit_signal_opinion", "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
     "description": ("Write an opinion on a token the Autopilot holds or is asked to buy (an open position or a request "
                     "waiting for approval): verdict kupi | preskoči | dobar | loš | neutralan, confidence 0-1, "
                     "interpretation, evidence. Shown next to the position or the waiting request; buys nothing."),
     "inputSchema": {"type": "object", "properties": {
         "token": {"type": "string"}, "verdict": {"type": "string", "enum": ["kupi", "preskoči", "dobar", "loš", "neutralan"]},
         "confidence": {"type": "number", "minimum": 0, "maximum": 1}, "interpretation": {"type": "string", "maxLength": 4000},
         "evidence": {"type": "object"}}, "required": ["token", "verdict", "interpretation"]}},
    {"name": "submit_suggestion", "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
     "description": ("Suggest an improvement for the owner: title, interpretation, improvement, evidence, and optionally "
                     "proposed_change. The owner can Prihvati / Odbij / Primijeni on the Autopilot page; only these keys are "
                     "applied by his click: {\"key\": tp_default | sl_default | size_sol | max_open | auto_skip | "
                     "copy.max_delay_min | copy.min_liq | copy.max_mcap | copy.min_mcap | copy.min_liq_mcap | "
                     "copy.crew_window_min | copy.max_per_day, \"from\": current, \"to\": new} or {\"caller\": handle, "
                     "\"platform\": x|telegram, \"weight\": 0-2}. Anything else is accepted for a manual change."),
     "inputSchema": {"type": "object", "properties": {
         "title": {"type": "string", "maxLength": 200}, "interpretation": {"type": "string", "maxLength": 4000},
         "improvement": {"type": "string", "maxLength": 4000}, "evidence": {"type": "object"},
         "proposed_change": {"type": "object"}}, "required": ["title", "interpretation"]}},
    {"name": "submit_daily_summary", "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
     "description": ("Write the day's summary for the owner (title, interpretation, evidence); the newest one is shown at "
                     "the top of the Autopilot page."),
     "inputSchema": {"type": "object", "properties": {
         "title": {"type": "string", "maxLength": 200}, "interpretation": {"type": "string", "maxLength": 4000},
         "evidence": {"type": "object"}}, "required": ["title", "interpretation"]}},
    {"name": "submit_caller_weights",
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
     "description": ("Suggest per-caller weights (0-2, 1 = neutral) with a reason: one suggestion note each (kind "
                     "suggestion, proposed_change {caller, platform, weight}) for the owner's Prihvati / Odbij / Primijeni "
                     "on the Autopilot page; live scoring does NOT change until he applies it. Does not trade. At most 50 "
                     "per call, 60 notes an hour."),
     "inputSchema": {"type": "object", "properties": {"weights": {"type": "array", "maxItems": 200, "items": {
         "type": "object", "properties": {"handle": {"type": "string"}, "platform": {"type": "string", "enum": ["x", "telegram"]},
                                          "weight": {"type": "number", "minimum": 0, "maximum": 2}, "reason": {"type": "string"}},
         "required": ["handle", "weight"]}, "maxItems": 50}}, "required": ["weights"]}},
]


def _note_tool(name, a, kid):
    """The four note tools: insert into trade.db assistant_notes only (ui/assistnotes.py)."""
    from ui import assistnotes
    tcon = settings.connect()
    try:
        if name == "submit_trade_review":
            return assistnotes.submit_trade_review(tcon, kid, a.get("position_id") or a.get("trade_id"), a.get("verdict"),
                                                   a.get("confidence"), a.get("interpretation"), a.get("improvement"),
                                                   a.get("evidence"))
        if name == "submit_signal_opinion":
            return assistnotes.submit_signal_opinion(tcon, kid, a.get("token"), a.get("verdict"), a.get("confidence"),
                                                     a.get("interpretation"), a.get("evidence"))
        if name == "submit_suggestion":
            return assistnotes.submit_suggestion(tcon, kid, a.get("title"), a.get("interpretation"), a.get("improvement"),
                                                 a.get("evidence"), a.get("proposed_change"))
        return assistnotes.submit_daily_summary(tcon, kid, a.get("title"), a.get("interpretation"), a.get("evidence"))
    except ValueError as e:
        return {"error": str(e)}
    finally:
        tcon.close()


NOTE_TOOLS = ("submit_trade_review", "submit_signal_opinion", "submit_suggestion", "submit_daily_summary")


def _tool(name, args, kid="local"):
    """(result dict, is_error) of one tool call."""
    args = args if isinstance(args, dict) else {}
    if name in NOTE_TOOLS:
        d = _note_tool(name, args, kid)
        return d, "error" in d
    from ui import mcpdata
    data_tools = {
        "get_caller_leaderboard": lambda a: mcpdata.caller_leaderboard(a.get("platform"), a.get("min_calls"), a.get("sort"),
                                                                       a.get("limit"), a.get("offset")),
        "get_caller_history": lambda a: mcpdata.caller_history(a.get("handle"), a.get("platform"), a.get("since_ts"),
                                                               a.get("limit"), a.get("offset")),
        "get_token_history": lambda a: mcpdata.token_history(a.get("token_address")),
        "get_wallet_leaderboard": lambda a: mcpdata.wallet_leaderboard(a.get("kind"), a.get("limit"), a.get("offset")),
        "get_wallet_history": lambda a: mcpdata.wallet_history(a.get("address"), a.get("limit"), a.get("offset")),
        "get_wallet_clusters": lambda a: mcpdata.wallet_clusters(),
        "get_autopilot_trades": lambda a: mcpdata.autopilot_trades(a.get("since_ts"), a.get("limit"), a.get("offset"),
                                                                   a.get("status")),
        "get_unreviewed_trades": lambda a: mcpdata.unreviewed_trades(a.get("limit") or 50),
        "get_assistant_notes": lambda a: mcpdata.assistant_notes(a.get("status"), a.get("kind"), a.get("limit"),
                                                                 a.get("offset")),
        "get_scoring_config": lambda a: mcpdata.scoring_config(),
        "submit_caller_weights": lambda a: mcpdata.submit_caller_weights(a.get("weights"), kid=kid),
    }
    if name in data_tools:
        d = data_tools[name](args)
        return d, isinstance(d, dict) and "error" in d
    if name == "get_market_signals":
        return signals(), False
    if name == "get_token_details":
        d = token(args.get("token_address") or args.get("address"))
        return d, "error" in d
    if name == "get_portfolio_status":
        return portfolio(), False
    if name == "execute_trade":
        code, d = trade_request({"token": args.get("token_address") or args.get("token"), "amount": args.get("amount"),
                                 "side": args.get("side"), "require_approval": args.get("require_approval", True),
                                 "reason": args.get("reason") or ""})
        return d, code >= 400
    return {"error": f"unknown tool {name}"}, True


def _one(msg, kid="local"):
    """The JSON-RPC answer to one message, or None for a notification."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        return {"jsonrpc": "2.0", "id": (msg or {}).get("id") if isinstance(msg, dict) else None,
                "error": {"code": -32600, "message": "Invalid Request"}}
    mid, method, params = msg.get("id"), msg["method"], msg.get("params") or {}
    if "id" not in msg:   # a notification (notifications/initialized, cancelled ...): nothing to answer
        return None
    try:
        if method == "initialize":
            asked = str(params.get("protocolVersion") or "")
            result = {"protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                      "capabilities": {"tools": {"listChanged": False}}, "serverInfo": SERVER_INFO,
                      "instructions": INSTRUCTIONS}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            data, err = _tool(params.get("name"), params.get("arguments"), kid)
            result = {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
                      "structuredContent": data, "isError": bool(err)}
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}
    except Exception as e:  # noqa: BLE001 - a broken part answers the client, never a traceback page
        print(f"mcp: {method}: {type(e).__name__}: {e}", flush=True)
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": f"Internal error: {type(e).__name__}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def rpc(raw_body, key=None):
    """(HTTP status, JSON text or '') of a POST /mcp body. key: the client's bearer key (only its fingerprint is
    kept, for the notes' hourly limit)."""
    from ui import assistnotes
    kid = assistnotes.key_id(key)
    try:
        msg = json.loads(raw_body or b"null")
    except ValueError:
        return 400, json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
    if isinstance(msg, list):   # a batch (spec 2025-03-26)
        out = [a for a in (_one(m, kid) for m in msg[:50]) if a is not None]
        return (200, json.dumps(out, ensure_ascii=False)) if out else (202, "")
    a = _one(msg, kid)
    return (202, "") if a is None else (200, json.dumps(a, ensure_ascii=False))
