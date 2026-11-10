"""The data side of the MemeSonar MCP server (mcp_server/, Grok's tools), 10.11. (Jure: "MCP server MemeSonar:
get_market_signals, get_token_details, get_portfolio_status, execute_trade s require_approval").

    GET  /api/mcp/signals             what is being called right now (X, Telegram, followed wallets) + live market,
                                      and the market scanner's finds (scan, beta) while market_scan is on; ?source=
    GET  /api/mcp/token?address=...   one token: live market, who called it in the last hour, our position in it
    GET  /api/mcp/portfolio           the Autopilot: mode, wallet value, open positions with PnL, open orders
    POST /api/mcp/trade               a trade REQUEST: it waits on the Autopilot page until the owner taps
                                      "Odobri" (then it goes through the owner's manual buy / sell); executed here
                                      only with require_approval=false while the owner has grok_autotrade on
                                      (10.11., ui/grokauto.py: Grok's own limits, kill switch, day-loss pause)

Every call needs "Authorization: Bearer <MCP_API_KEY>" (Render env); without that variable the API answers 404, as
if it did not exist. Read-only on the databases except the request queue (trade settings "mcp_requests"), the
assistant's notes (ui/assistnotes.py) and the insert-only X features (xfeat.db, ui/xfeat.py; 10.11. Grok MCP audit 10).
Why trades wait for the owner: the client is an LLM that reads public posts; a crafted post has already made Grok
order a transfer (May 2026). Real money moves only on the owner's tap (CLAUDE.md: pitaj prije), or, since 10.11. at
the owner's request, through grok_autotrade: off by default, switched on only by the owner on the Autopilot page,
bounded by Grok's own limits (no MCP tool can switch it on or change them), swaps only (no transfer exists).
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


SIGNAL_SOURCES = ("caller", "wallet", "scan", "beta", "hidden_group")
_SCAN_NULL = {"beta_score": None, "beta_parent": None, "x_momentum_score": None, "x_early": None, "lead_time_min": None}


def _scan_fields(r, xm, first_call_ts=None):
    """The market scanner's fields of one token (scan/market.recent row r, X momentum xm) for a signal row."""
    from scan import market as smarket
    x = xm or {}
    return {"beta_score": r.get("beta_score"), "beta_parent": r.get("beta_parent"),
            "x_momentum_score": x.get("x_momentum_score"), "x_early": x.get("x_early"),
            "x_source": x.get("source"), "lead_time_min": smarket.lead_for(r, first_call_ts),
            "stage": r.get("stage"), "tradeable": bool(r.get("tradeable")),
            "pass_reasons": r.get("reasons") or [], "fees_paid_sol": r.get("fees_paid_sol"),
            "buy_share": r.get("buy_share"), "holders": r.get("holders"), "top10_pct": r.get("top10_pct"),
            "scan_found_ts": r.get("first_pass_ts") or r.get("checked_ts"), "scan_via": r.get("via")}


def signals(now=None, source=None):
    """Tokens called in the last hour by the accounts the tool tracks (and buys of followed wallets), most callers
    first, each with its live market; while the flag market_scan is on, also the market scanner's passers of the last
    hour (source scan, with their pass reasons) and the betas of the active metas (source beta). A token the scanner
    found that a caller also called is ONE row (source caller or wallet, plus the scanner's fields and lead_time_min:
    how many minutes earlier the scanner had it). source: caller | wallet | scan | beta filters; None = everything
    (the rows before 10.11. keep their fields; the new ones are added)."""
    src = (source or "").strip().lower() or None
    if src and src not in SIGNAL_SOURCES:
        return {"error": f"source must be one of {', '.join(SIGNAL_SOURCES)}"}
    now = now or time.time()
    scan_rows, xm = {}, {}
    try:
        from scan import market as smarket, store as sstore, xmom
        if sstore.on():
            scan_rows = smarket.recent(now)
            xm = xmom.latest(list(scan_rows), since=now - 6 * 3600, now=now) if scan_rows else {}
    except Exception as e:  # noqa: BLE001 - the scanner's part never breaks the callers' answer
        print(f"mcp: skener: {type(e).__name__}: {e}", flush=True)
        scan_rows, xm = {}, {}
    out, seen = [], set()
    if src in (None, "caller", "wallet"):
        from ui import pravitrade
        for tok, callers, first_ts, last_ts, sym, live in pravitrade.gather_callers(now):
            plats = {p for _w, p, _ts in callers}
            kinds = (["caller"] if plats & {"x", "tg"} else []) + (["wallet"] if "chain" in plats else [])
            if src and src not in kinds:
                continue
            row = {"token": tok, "symbol": sym, "callers": [{"who": w, "platform": p, "ts": int(ts)} for w, p, ts in callers],
                   "n_callers": len(callers), "first_call_ts": int(first_ts), "last_call_ts": int(last_ts),
                   "market": _market_row(live), "under_30k": bool(live and (live.get("mcap") or 0) < 30_000),
                   "source": kinds[0] if kinds else "caller", "sources": kinds, **_SCAN_NULL}
            if tok in scan_rows:
                row.update(_scan_fields(scan_rows[tok], xm.get(tok), first_ts))
                row["sources"] = kinds + [s for s in scan_rows[tok]["sources"] if s in ("scan", "beta")]
            out.append(row)
            seen.add(tok)
    if src in (None, "scan", "beta"):
        for tok, r in scan_rows.items():
            if tok in seen:
                continue   # one row per token: the caller's row above already carries the scanner's fields
            kinds = [s for s in ("scan", "beta") if s in r["sources"]] or (["scan"] if r.get("passed") else [])
            if src and src not in kinds:
                continue
            if src == "beta" and (r.get("beta_score") or 0) < 0.6:
                continue
            if not kinds:
                continue
            m = {"price": r.get("price"), "mcap": r.get("mcap"), "liq": r.get("liq"), "vol_h1": r.get("vol_h1"),
                 "ch_h1": r.get("ch_h1"), "ch_h24": r.get("ch_h24")}
            row = {"token": tok, "symbol": r.get("symbol"), "callers": [], "n_callers": 0, "first_call_ts": None,
                   "last_call_ts": None, "market": _market_row(m), "market_ts": r.get("checked_ts"),
                   "under_30k": (r.get("mcap") or 0) < 30_000, "source": kinds[0], "sources": kinds, **_SCAN_NULL}
            row.update(_scan_fields(r, xm.get(tok)))
            out.append(row)
    if src in (None, "hidden_group"):
        out += _group_signals(now)   # 10.11. source hidden_group (kol/groupdisc.py); nothing while group_discovery is off
    return {"ts": int(now), "source": "MemeSonar (X, Telegram, followed wallets; DexScreener live; market scanner "
                                      "in shadow while the flag market_scan is on)",
            "filter": src, "signals": out}


def _group_signals(now):
    """Hidden wallet-list signals of group_discovery; a broken extra source never hides the calls above."""
    try:
        from kol import groupdisc
        return groupdisc.mcp_signals(now)
    except Exception as e:  # noqa: BLE001
        print(f"mcp: hidden_group: {type(e).__name__}: {e}", flush=True)
        return []


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
            "our_open_lots": pos, "dexscreener": f"https://dexscreener.com/solana/{address}",
            "range": _range_of(address, now)}


def _range_of(address, now):
    """10.11. (flag range_dca): zones, touches, recoveries, every range_score component (rangedca/view.py); None when
    the token is not watched or range.db does not exist."""
    try:
        from rangedca import view
        return view.token(address, now)
    except Exception as e:  # noqa: BLE001 - the token details answer without it
        return {"error": type(e).__name__}


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
        plans = _plans_for(sorted(by), now_mc)
        for tok, g in by.items():
            w = [(l["entry_market_cap_usd"], l["sol_in"] or 0) for l in g["lots"]]
            wsum = sum(s for m, s in w if m and s)
            avg = wsum / sum(s / m for m, s in w if m and s) if wsum else None
            mc = now_mc.get(tok)
            g.update(sol_in=_num(sum(l["sol_in"] or 0 for l in g["lots"]), 4), avg_entry_market_cap_usd=_num(avg, 0),
                     market_cap_now_usd=_num(mc, 0), pnl_pct=_num((mc / avg - 1) * 100, 2) if mc and avg else None)
            g["exit_plan"] = plans.get(tok)   # 10.11.: the plan in force, peak MC since entry, distance to each trigger
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
                "grok_autotrade": _grok_part(tcon, now),
                "open_orders": {"dca": raw.get("dca_orders") or [],
                                "waiting_for_owner": [r for r in raw.get("mcp_requests") or [] if r.get("status") == "pending"]}}
    finally:
        tcon.close()


def set_exit_plan(token, plan, kid="mcp"):
    """10.11. (league/exitplan): validate and store the plan, log it in applied_suggestions (ts, old, new, client)."""
    from league import exitplan, store as lstore
    from trade import executor
    tok = str(token or "").strip()
    if not MINT.fullmatch(tok):
        return {"error": "token_address must be a Solana token address"}
    tcon = settings.connect()
    lcon = lstore.connect()
    try:
        sl_default = float(settings.merged(executor.load_config(), tcon).get("sl_default") or 30)
        try:
            out = exitplan.set_plan(lcon, tok, plan, sl_default, client=f"mcp:{kid}")
        except ValueError as e:
            return {"error": str(e)}
        from ui import assistnotes
        old = out["replaced"]
        assistnotes.record_applied(tcon, 0, f"exit_plan:{tok}", old if isinstance(old, str) else old.get("plan"),
                                   out["plan"], "set_exit_plan", client=f"mcp:{kid}")
        print(f"mcp: plan izlaza #{out['plan_id']} za {tok[:6]}: {out['plan'].get('reason') or ''}", flush=True)
        out["flag_mode"] = settings.flag("exit_plans", con=tcon)
        out["paused_by_owner"] = bool(settings.raw(tcon).get("exit_plans_paused"))
        return out
    finally:
        lcon.close()
        tcon.close()


def exit_events(since_ts=None, limit=None):
    from league import exitplan, store as lstore
    lcon = lstore.connect()
    try:
        try:
            lim = max(1, min(500, int(limit or 200)))
        except (TypeError, ValueError):
            lim = 200
        return {"events": exitplan.events(lcon, since_ts or 0, lim)}
    finally:
        lcon.close()


def _plans_for(tokens, now_mc):
    """{token: exit plan view of the real Autopilot account} for get_portfolio_status."""
    try:
        from league import exitplan, store as lstore
        lcon = lstore.connect()
        try:
            exitplan.ensure(lcon)
            return {t: exitplan.view(lcon, t, settings.LEAGUE_USER, mcap=now_mc.get(t)) for t in tokens}
        finally:
            lcon.close()
    except Exception:  # noqa: BLE001
        return {}


def _grok_part(tcon, now):
    try:
        from ui import grokauto
        return grokauto.portfolio_part(tcon, now)
    except Exception as e:  # noqa: BLE001 - the portfolio answers without it
        return {"error": type(e).__name__}


def trade_request(body, now=None):
    """Queue a trade for the owner's approval. body: {token, side: buy|sell, amount, require_approval, reason}.
    buy: amount in SOL; sell: amount as a share of the position (0.25 = 25 %, 1 = all). require_approval=false:
    executed at once by ui/grokauto ONLY while the owner has grok_autotrade on, else rejected (403)."""
    now = int(now or time.time())
    body = body if isinstance(body, dict) else {}
    auto = body.get("require_approval") is False
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
    if side == "sell" and not 0 < amount <= 1:
        return 400, {"error": "sell amount is a share of the position: 0 < amount <= 1"}
    if auto:   # 10.11. (Jure): executed at once only while the owner has switched grok_autotrade on (ui/grokauto)
        from ui import grokauto
        return grokauto.execute({"token": tok, "side": side, "amount": amount, "reason": body.get("reason")}, now)
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
        data = signals(source=qs.get("source"))
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
                "the Autopilot's portfolio. execute_trade queues a request for the owner's approval on the MemeSonar "
                "Autopilot page, unless the owner has switched grok_autotrade on and require_approval=false is sent: "
                "then it executes within Grok's limits and answers executed or rejected. Never assume a trade "
                "executed unless the answer says status executed.")
_READ = {"readOnlyHint": True, "openWorldHint": True}
TOOLS = [
    {"name": "get_market_signals", "annotations": _READ,
     "description": ("Meme coins being called right now on Solana by the X and Telegram accounts MemeSonar tracks, and "
                     "buys of the wallets it follows: per token the callers, first/last call time and the live market "
                     "(price, market cap, liquidity, volume, 5m/1h/24h change, buys share of the last hour). While the "
                     "market scanner runs (shadow, it never buys) also tokens found WITHOUT a caller: source scan "
                     "(passed the scanner's filters in the last hour: stage final_stretch = still on the bonding "
                     "curve, tradeable=false, or migrated; pass_reasons, fees_paid_sol (estimated from volume), "
                     "buy_share, holders, top10_pct) and source beta (copies the narrative of a top runner: "
                     "beta_score >= 0.6, beta_parent = the runner's mint). Every row: source, sources, beta_score, "
                     "x_momentum_score (growth of unique organic X authors in the last 15 min vs the hour before, "
                     "log2; > 0 = growing), x_early (growing and no known caller posted it yet), lead_time_min (how "
                     "many minutes before the first caller the scanner had it; negative = the caller was first); "
                     "null when unknown. One row per token. source filters: caller | wallet | scan | beta; none = all."),
     "inputSchema": {"type": "object", "properties": {
         "source": {"type": "string", "enum": ["caller", "wallet", "scan", "beta", "hidden_group"],
                    "description": "only rows of this source (default: all)"}}}},
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
     "description": ("Ask MemeSonar for a trade. require_approval=true (default): queued; it waits on the Autopilot "
                     "page until the owner approves it (15 minutes) -> status pending_approval. require_approval=false: "
                     "executed at once ONLY while the owner has switched grok_autotrade on (get_portfolio_status shows "
                     "it and the limits left today); buys within Grok's own limits (grok_max_sol_per_trade, "
                     "grok_max_sol_per_day, grok_max_open; after grok_max_loss_day it pauses until midnight Zagreb) "
                     "and after a fresh rug and liquidity check; sells of any open position, any share. Answer: "
                     "status executed (with tx_signature when the swap landed in the wait, else tx_status submitted) "
                     "or rejected with the reason. side 'buy': amount in SOL; side 'sell': amount as a share of the "
                     "open position (0.25 = 25 %, 1 = all). reason: one line for the owner."),
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
    # 10.11. (Grok MCP audit 5): ranked by the cautious 1 h EV after cost by default; hit_rate is the 24 h wick
    {"name": "get_caller_leaderboard", "annotations": _READ,
     "description": ("Every tracked caller (X and Telegram) with at least min_measured measured calls (default 10, 0 = "
                     "all), ranked by ev_lower: per call (one per token) the 1 h result after a 2 % round-trip cost "
                     "(minute entry close-to-close r60 when measured, else r1h), its mean, median "
                     "(median_r1h_after_cost) and mean minus 2 standard errors (ev_lower, the cautious expected result "
                     "per copied call); hit10_clean / hit10_wilson_low (minute check: +10 % before the -20 % stop "
                     "within 60 min, and its Wilson lower bound) and stop_first_share. Also: followers, first/last call "
                     "ts, calls, measured_calls, hit_rate = the 24 h WICK (the high at any moment within a day reached "
                     "+50 %): NOT tradable, never rank by it alone; avg / median change 1 h / 24 h (fractions), "
                     "x2_share (24 h wick >= 2x), rug_count, avg market cap at call, call_power (0-100), flags "
                     "big_name / rising_star / bragger (definitions in the answer). sort: ev_lower (default) | "
                     "median_r1h_after_cost | mean_r1h_after_cost | hit10_wilson_low | ev_n | score | hit_rate | calls | "
                     "measured_calls | avg_r24h | x2_share | followers | last_call_ts | power_rel." + _PAGED),
     "inputSchema": {"type": "object", "properties": {"platform": {"type": "string", "enum": ["x", "telegram"]},
                                                      "min_calls": {"type": "integer", "minimum": 0},
                                                      "min_measured": {"type": "integer", "minimum": 0, "default": 10},
                                                      "sort": {"type": "string"}, **_PAGE}}},
    {"name": "get_caller_history", "annotations": _READ,
     "description": ("Every call of one caller, newest first: token, symbol, call ts, price and market cap at the call, "
                     "max/min within the first hour (minute candles), max within 24 h, price at 1 h / 24 h, rug flag, "
                     "and how many other callers called the same token within 15 min before / after. *_source says "
                     "where a value came from; minute_status and measure_status say why one is null (under_30k, "
                     "older_than_30d, no_pair, pending, never_measured ...). platform: x or telegram (a Telegram "
                     "channel may also be given as tg:<channel>)." + _PAGED),
     "inputSchema": {"type": "object", "properties": {"handle": {"type": "string"},
                                                      "platform": {"type": "string", "enum": ["x", "telegram"]},
                                                      "since_ts": {"type": "integer"}, **_PAGE},
                     "required": ["handle"]}},
    {"name": "get_token_history", "annotations": _READ,
     "description": ("One token: every call in order (caller, platform, ts, market cap at call, followers), its price / "
                     "market cap series (at most 500 points), rug-check results (rug filter, RugCheck top check, rug "
                     "archive) and every Autopilot trade on it (demo trade it follows with its exit_reason, and the real "
                     "position with block_reason when it was blocked or failed)."),
     "inputSchema": {"type": "object", "properties": {"token_address": {"type": "string"}}, "required": ["token_address"]}},
    {"name": "get_wallet_leaderboard", "annotations": _READ,
     "description": ("Tracked wallets: realized / unrealized PnL (SOL), win rate, median hold time, style, tier, scores and "
                     "the linked influencer handle when known (an influencer wallet not scored yet carries its linked "
                     "caller's call_power, score_source linked_kol_call_power). kind: influencer (a known influencer's "
                     "wallet) or smart (tier S/A/B)." + _PAGED),
     "inputSchema": {"type": "object", "properties": {"kind": {"type": "string", "enum": ["influencer", "smart"]}, **_PAGE}}},
    {"name": "get_wallet_history", "annotations": _READ,
     "description": ("One wallet's buys and sells, newest first: token, ts, side, SOL size, token amount, market cap in "
                     "SOL when the trade was seen live; plus its kind, tier, score (score_source), PnL, win rate and "
                     "linked handle." + _PAGED),
     "inputSchema": {"type": "object", "properties": {"address": {"type": "string"}, **_PAGE}, "required": ["address"]}},
    {"name": "get_wallet_clusters", "annotations": _READ,
     "description": ("Groups of wallets that buy together (common funder, same rug cluster, same-second buys) with members "
                     "and tokens, and clusters of callers that call the same tokens together; newest analysis snapshot."),
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "get_autopilot_trades", "annotations": _READ,
     "description": ("Every Autopilot trade (mode live = real money, dry = trial with real quotes), newest first; the DCA "
                     "lots of a token are one trade. Per trade: trade_id (its first position_id), kind (position | "
                     "refused: a real copy that was blocked or failed, with block_reason and the demo_trade it mirrors | "
                     "demo_only with include_demo_only), lots, entry/exit ts, entry (SOL-weighted) / exit market cap "
                     "(*_source), sol_in, sol_back, fees_sol, cost_pct (swap cost of the buys), pnl_sol / pnl_pct, "
                     "exit_reason = the rule that fired: tp | sl | time | smart_tp | smart_sl | smart_trail | "
                     "smart_other | wallet_sold | manual | rug (exit_rule_source, exit_detail, exit_note), exit_policy "
                     "(the follow's exit mode smart / tpsl / podaci / mirror and the stop that applied: a smart "
                     "profile's own stop is not the account's sl_default), and the signals at the entry: the follow, "
                     "score_at_entry (score_source), the followed caller's record before the entry, callers of the last "
                     "hour with call_power and stats, wallet buys with tier / score / linked handle, the rug check, the "
                     "minute path of the triggering call and the run-up from the first call to the entry. status: open "
                     "| closed | blocked | failed (default all)." + _PAGED),
     "inputSchema": {"type": "object", "properties": {"since_ts": {"type": "integer"},
                                                      "status": {"type": "string",
                                                                 "enum": ["open", "closed", "blocked", "failed"]},
                                                      "include_demo_only": {"type": "boolean", "default": False},
                                                      **_PAGE}}},
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
                     "proposed_change. The owner taps 'Označi prihvaćenim (bez promjene)' (agrees, NOTHING changes), Odbij, "
                     "or 'Primijeni na bota' (applies it); only these keys are applied by that tap: {\"key\": tp_default | "
                     "sl_default | size_sol | max_open | auto_skip | copy.max_delay_min | copy.min_liq | copy.max_mcap | "
                     "copy.min_mcap | copy.min_liq_mcap | copy.crew_window_min | copy.max_per_day | dca_token_cap (SOL per "
                     "token, 0.01-5) | require_signal (true/false) | runup_max (fraction 0.02-2), \"from\": current, "
                     "\"to\": new} or {\"caller\": handle, \"platform\": x|telegram, \"weight\": 0-2}. dca_token_cap, "
                     "require_signal, runup_max and caller weights sit behind flags (dca_cap, require_signal, runup_default, "
                     "caller_weights): applying moves an off flag to shadow only; live is the owner's call after a backtest. "
                     "Check the result with get_scoring_config (applied_suggestions, effective_values). Anything else is "
                     "accepted for a manual change, e.g. a name for a group from get_trader_groups: {\"group_label\": "
                     "{\"group_id\": ..., \"label\": ..., \"note\": ...}} (an accepted one shows as the group's label). "
                     "A verdict on a wallet from get_insider_candidates: {\"insider_label\": {\"wallet\": <address>, "
                     "\"label\": insider | team | bot | sniper | legit, \"note\": <why>}}; the owner's 'Primijeni na "
                     "bota' stores it (bot and sniper keep the wallet out of the insider copy; nothing else changes)."),
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
    # 10.11. (Grok MCP audit 10, plan 3.6): X features Grok counts (e.g. posts with a token's CA per hour), kept
    # point in time in xfeat.db (ui/xfeat.py); insert only, accepted while the owner's flag x_features_ingest is on
    {"name": "submit_x_features",
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
     "description": ("Store what you measured on X about one subject, point in time (insert only; nothing is "
                     "overwritten). subject: a token mint (subject_kind token, default), an X handle (handle) or a "
                     "wallet (wallet). features: a JSON object up to 20 kB; for the count of posts containing a token's "
                     "CA use {\"ca_posts_1h\": <posts in the hour>, \"ca_posts_hour_ts\": <unix start of that hour>}. "
                     "ts_asof: unix seconds of the moment the features describe (the end of the counted hour); the "
                     "server stamps ts_observed itself. A ts_asof older than 3 h needs backfill=true (counted after the "
                     "fact, kept apart from live rows). Refused while the owner has the X feature intake switched off; "
                     "at most 120 rows an hour. MemeSonar's scoring does not read these yet."),
     "inputSchema": {"type": "object", "properties": {
         "subject": {"type": "string"},
         "subject_kind": {"type": "string", "enum": ["token", "handle", "wallet"], "default": "token"},
         "features": {"type": "object"},
         "ts_asof": {"type": "integer", "description": "unix seconds the features describe"},
         "backfill": {"type": "boolean", "default": False}}, "required": ["subject", "features", "ts_asof"]}},
    {"name": "get_x_features", "annotations": _READ,
     "description": ("The X feature rows stored for one subject (submit_x_features), newest ts_asof first: id, "
                     "ts_observed (when MemeSonar received it), ts_asof, features, source, backfill. since: only rows "
                     "with ts_asof >= since. limit 1-500 (default 100)."),
     "inputSchema": {"type": "object", "properties": {
         "subject": {"type": "string"},
         "subject_kind": {"type": "string", "enum": ["token", "handle", "wallet"], "default": "token"},
         "since": {"type": "integer"}, "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100}},
         "required": ["subject"]}},
    {"name": "set_exit_plan",
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
     "description": ("Set the exit plan of one OPEN Autopilot position (all its lots); it replaces the position's "
                     "default TP/SL and is executed by the MemeSonar server every second, no owner tap (it only sells). "
                     "plan: take_profits [{at_pct (from the average entry) OR at_mc_usd, sell_share 0-1}] (shares add "
                     "up to at most 1, each fires once), trailing {activate_pct, trail_pct} (from +activate_pct, sell "
                     "all at -trail_pct from the peak after the activation), stop {at_pct OR at_mc_usd} (hard stop: may "
                     "only be TIGHTENED, never looser than the current stop nor than sl_default), time_stop "
                     "{after_min, if_pnl_below_pct} (counted from the last entry), reason (one line). Runs under the "
                     "flag exit_plans: paper = executed only on the demo account autopilot-paper, logged for the real "
                     "one; live = both. A price older than 60 s fires only the hard stop. accounts (optional): the "
                     "Autopilot accounts the plan applies to, e.g. [\"autopilot-paper\"] for a range position "
                     "(get_range_candidates names its account), so it never touches the other account's position in "
                     "the same token; a range position's own exits keep running next to the plan (a plan only "
                     "tightens). Answer: plan_id, the plan in force, the stop price per account and what it replaced."),
     "inputSchema": {"type": "object", "properties": {
         "token_address": {"type": "string"},
         "plan": {"type": "object", "properties": {
             "accounts": {"type": "array", "items": {"type": "string", "enum": ["pravi-trade", "autopilot-paper"]}},
             "take_profits": {"type": "array", "items": {"type": "object", "properties": {
                 "at_pct": {"type": "number"}, "at_mc_usd": {"type": "number"}, "sell_share": {"type": "number"}}}},
             "trailing": {"type": "object", "properties": {"activate_pct": {"type": "number"},
                                                           "trail_pct": {"type": "number"}}},
             "stop": {"type": "object", "properties": {"at_pct": {"type": "number"}, "at_mc_usd": {"type": "number"}}},
             "time_stop": {"type": "object", "properties": {"after_min": {"type": "number"},
                                                            "if_pnl_below_pct": {"type": "number"}}},
             "reason": {"type": "string"}}}},
         "required": ["token_address", "plan"]}},
    {"name": "get_exit_events", "annotations": _READ,
     "description": ("Executed exit-plan triggers since since_ts (unix s), newest first: plan_id, account, token, "
                     "trigger (tp1, tp2, trailing, stop, time_stop), price, market cap, share sold, PnL in USD of the "
                     "demo side, mode (izvršeno = executed, sjena = logged only), stale (the price was older than 60 s), "
                     "and the real sell's cost/slippage %, tx signature and status when it landed."),
     "inputSchema": {"type": "object", "properties": {"since_ts": {"type": "integer"},
                                                      "limit": {"type": "integer", "minimum": 1, "maximum": 500}}}},
    {"name": "get_research", "annotations": _READ,
     "description": ("One-off research reports MemeSonar computed from the chain and its own databases (read only). "
                     "No name: the list of reports. name (e.g. hope-20261110: every buyer of the Hope token on the "
                     "pump.fun curve and the PumpSwap pool with first buy time, market cap at that buy, SOL in/out, "
                     "first and last sell, phase, wallets.db tier, linked X/Telegram account; the calls of the token "
                     "from kol.db and the callers' known wallets). part: summary (default), wallets, calls, "
                     "calls_before_marko, holders_top20, caller_trades, bundles or all. Lists are paged: limit 1-500 "
                     "(default 100), offset; wallets can be sorted by first_buy_ts (default), sol_in, pnl_sol, net_tok."),
     "inputSchema": {"type": "object", "properties": {
         "name": {"type": "string"},
         "part": {"type": "string", "enum": ["summary", "wallets", "calls", "calls_before_marko", "holders_top20",
                                             "caller_trades", "bundles", "all"], "default": "summary"},
         "sort": {"type": "string", "enum": ["first_buy_ts", "sol_in", "pnl_sol", "net_tok"]},
         "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
         "offset": {"type": "integer", "minimum": 0, "default": 0}}}},
    # 10.11. (market scanner, flag market_scan): how each signal source does in shadow, and whether it may go to paper
    {"name": "get_source_stats", "annotations": _READ,
     "description": ("Shadow results per signal source (caller, wallet, scan, beta) of the market scanner: every "
                     "candidate that passed all filters gets a shadow entry at the moment it was found, then its "
                     "DexScreener price path is followed. Per source for the last 24 h and the gate window: found, n "
                     "(finished outcomes, tradeable tokens only), hit1h / hit4h (+20 % reached within 1 h / 4 h), "
                     "sl_first (-30 % touched before +20 %), ev (mean result of the shadow trade: TP +20 % / SL -30 %, "
                     "first touched wins, else out at 4 h, minus 2 % round-trip cost), median; paper_gate per source "
                     "('prolazi' or the reason: >= 30 outcomes and EV > 0 are needed, never applied automatically); "
                     "measured_only_day (curve / under-30k tokens); lead_time over callers; beta results by the "
                     "parent meta's state (raste / pada); today's spend per paid source and the caps. Read-only."),
     "inputSchema": {"type": "object", "properties": {}}},
]
# 10.11. (flag group_discovery, kol/groupdisc.py): caller crews and hidden wallet lists, read-only; empty while off
TOOLS += [
    {"name": "get_trader_groups", "annotations": _READ,
     "description": ("Groups MemeSonar found (shadow mode: they change no trading). kind caller: X/Telegram accounts whose "
                     "first calls of the same tokens come within 120 s / 10 min of each other far more often than chance "
                     "(pairs with 3+ shared tokens and lift >= 5, connected). kind wallet: wallets that bought the same "
                     "3+ tokens within 5 slots in the tokens' first 30 min under $100k (bots, relayer-paid trades, "
                     "dev-funded and one-owner bundles removed), 4+ members. Per group: members (callers in their "
                     "usual order), metrics (events/tokens, who is first, market cap at the first call or entry, result "
                     "1 h / 4 h / 24 h after the first call, rug share, delay of the public calls behind the group, "
                     "PnL per wallet, entry minutes before the first public call, the pairs with their lift), grade "
                     "quality | exit_liquidity (the public calls fall after the group) | bad | insufficient_data and "
                     "its weight in the shadow scoring (one group within 10 min = one signal; exit_liquidity counts "
                     "-1). min_quality: only grades at or above it in the order exit_liquidity < bad < "
                     "insufficient_data < quality. label: the owner-accepted name. To propose a name use "
                     "submit_suggestion with proposed_change {\"group_label\": {\"group_id\": \"<group_id>\", "
                     "\"label\": \"<short name>\", \"note\": \"<why>\"}}; the owner accepts or rejects it." + _PAGED),
     "inputSchema": {"type": "object", "properties": {
         "kind": {"type": "string", "enum": ["caller", "wallet"], "default": "caller"},
         "min_quality": {"type": "string", "enum": ["exit_liquidity", "bad", "insufficient_data", "quality"]},
         **_PAGE}}},
    {"name": "get_group_activity", "annotations": _READ,
     "description": ("Fresh calls (caller groups) and buys (wallet groups) of group members since since_ts (unix s, "
                     "default 24 h), newest first: group_id, group kind, grade, token, who, market cap, under_30k, "
                     "whether a public call exists; plus the group signals of that time: hidden_group (3+ wallets of "
                     "one quality wallet group bought within 10 min with no public call; also listed in "
                     "get_market_signals as source hidden_group) and caller_group_first (a quality caller group "
                     "called first), with their measured result (+20 % before -30 % within 1 h / 4 h, EV after "
                     "cost) and how many minutes later the public callers came. Shadow only: nothing is bought, "
                     "and tokens under $30k are never bought." + _PAGED),
     "inputSchema": {"type": "object", "properties": {"since_ts": {"type": "integer"}, **_PAGE}}},
]
# 10.11. (flag insider_copy, kol/precall.py): pre-call insiders for Grok to clean, read-only; empty while off
TOOLS += [
    {"name": "get_insider_candidates", "annotations": _READ,
     "description": ("Wallets that bought tokens BEFORE tracked callers called them (X and Telegram, first call of each "
                     "caller, market cap at the call >= $10k), found by MemeSonar from its own trade data and Helius "
                     "windows (the trade is the signing owner's, never a relayer's). Per wallet: status confirmed "
                     "(selected on the older 2/3 of 30 days, confirmed on the newer 1/3) or candidate, tokens bought "
                     "before the first call, median minutes before the next call, share of those tokens that rose "
                     "+30 % within 1 h after the call, share it sold into the call (within 60 min), PnL in SOL, "
                     "callers_front_run (caller, tokens, lift against chance), examples (token, buy time, first and "
                     "next call with times, rose30, sold into the call, under_30k). Snipers, bots, relayers, dev-funded "
                     "and same-owner bundles are already out. Your verdict: submit_suggestion with proposed_change "
                     "{\"insider_label\": {\"wallet\": \"<address>\", \"label\": \"insider|team|bot|sniper|legit\", "
                     "\"note\": \"<why>\"}}; it counts only after the owner's 'Primijeni na bota'. bot / sniper keep a "
                     "wallet out of the copy. Copy is shadow / demo only until the owner's proof; tokens under $30k "
                     "and on the bonding curve are never bought."),
     "inputSchema": {"type": "object", "properties": {
         "min_tokens": {"type": "integer", "minimum": 1, "default": 3},
         "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50}}}},
]


def source_stats(now=None):
    """get_source_stats: scan/shadow.report_data, or a note before the scanner ever ran."""
    from scan import shadow, store as sstore
    d = shadow.report_data(now)
    if d is None:
        return {"ts": int(now or time.time()), "mode": sstore.mode(), "note": "the market scanner has not run yet "
                "(flag market_scan off, or no pass so far): no shadow outcomes"}
    return d


# 10.11. (Jure, flag range_dca): the range + DCA strategy's candidates (rangedca/view.py)
TOOLS.append(
    {"name": "get_range_candidates", "annotations": _READ,
     "description": ("Bonded Solana tokens MemeSonar sees trading in a range (from minute candles of the last 6-24 h, "
                     "recomputed every 5 min): per token the zones (range_low_low/top = bottom zone, range_high_low/top "
                     "= top zone, in price and market cap), every touch, the recoveries from the bottom, range_score "
                     "0-1 and its six components (recoveries, recovery_speed, higher_lows, volume_hold, "
                     "buy_share_at_low, sell_pressure_on_drop, each with value, score and weight), the position in the "
                     "range (0 % = range_low_low, 100 % = range_high_top), the 5-minute numbers, exclusions, and whether "
                     "an entry would pass now. Also the open range positions (account, lots, exit levels) and the paper "
                     "proof (closed rounds, EV per round, the live gate: >= 20 rounds with EV > 0). Tokens under $30k "
                     "market cap and tokens still on the pump.fun curve are never in it. To tighten a range position's "
                     "exits use set_exit_plan with plan.accounts set to its account."),
     "inputSchema": {"type": "object", "properties": {
         "min_score": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.7}}}})


def _xfeat_tool(name, a, kid):
    """10.11. (Grok MCP audit 10): the two X feature tools (ui/xfeat.py)."""
    from ui import xfeat
    try:
        if name == "submit_x_features":
            return xfeat.submit(a.get("subject") or a.get("token"), a.get("subject_kind") or "token", a.get("features"),
                                a.get("ts_asof"), a.get("backfill", False), kid=kid)
        return xfeat.read(a.get("subject") or a.get("token"), a.get("subject_kind") or "token", a.get("since"),
                          a.get("limit"))
    except ValueError as e:
        return {"error": str(e)}


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
    if name in ("submit_x_features", "get_x_features"):
        d = _xfeat_tool(name, args, kid)
        return d, "error" in d
    if name in ("get_trader_groups", "get_group_activity"):   # 10.11. group_discovery (kol/groupdisc.py)
        from kol import groupdisc
        d = groupdisc.mcp_tool(name, args)
        return d, "error" in d
    if name == "get_insider_candidates":   # 10.11. insider_copy (kol/precall.py)
        from kol import precall
        d = precall.mcp_tool(name, args)
        return d, "error" in d
    from ui import mcpdata
    data_tools = {
        "get_caller_leaderboard": lambda a: mcpdata.caller_leaderboard(a.get("platform"), a.get("min_calls"), a.get("sort"),
                                                                       a.get("limit"), a.get("offset"),
                                                                       a.get("min_measured")),
        "get_caller_history": lambda a: mcpdata.caller_history(a.get("handle"), a.get("platform"), a.get("since_ts"),
                                                               a.get("limit"), a.get("offset")),
        "get_token_history": lambda a: mcpdata.token_history(a.get("token_address")),
        "get_wallet_leaderboard": lambda a: mcpdata.wallet_leaderboard(a.get("kind"), a.get("limit"), a.get("offset")),
        "get_wallet_history": lambda a: mcpdata.wallet_history(a.get("address"), a.get("limit"), a.get("offset")),
        "get_wallet_clusters": lambda a: mcpdata.wallet_clusters(),
        "get_autopilot_trades": lambda a: mcpdata.autopilot_trades(a.get("since_ts"), a.get("limit"), a.get("offset"),
                                                                   a.get("status"), a.get("include_demo_only") is True),
        "get_unreviewed_trades": lambda a: mcpdata.unreviewed_trades(a.get("limit") or 50),
        "get_assistant_notes": lambda a: mcpdata.assistant_notes(a.get("status"), a.get("kind"), a.get("limit"),
                                                                 a.get("offset")),
        "get_scoring_config": lambda a: mcpdata.scoring_config(),
        "submit_caller_weights": lambda a: mcpdata.submit_caller_weights(a.get("weights"), kid=kid),
        "set_exit_plan": lambda a: set_exit_plan(a.get("token_address") or a.get("token"), a.get("plan"), kid),
        "get_exit_events": lambda a: exit_events(a.get("since_ts"), a.get("limit")),
        "get_research": lambda a: __import__("research.store", fromlist=["read"]).read(
            a.get("name"), a.get("part"), a.get("limit"), a.get("offset"), a.get("sort")),
        "get_source_stats": lambda a: source_stats(),
        "get_range_candidates": lambda a: __import__("rangedca.view", fromlist=["candidates"]).candidates(
            a.get("min_score")),
    }
    if name in data_tools:
        d = data_tools[name](args)
        return d, isinstance(d, dict) and "error" in d
    if name == "get_market_signals":
        d = signals(source=args.get("source"))
        return d, "error" in d
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
