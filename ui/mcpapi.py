"""The data side of the MemeSonar MCP server (mcp_server/, Grok's tools), 10.11. (Jure: "MCP server MemeSonar:
get_market_signals, get_token_details, get_portfolio_status, execute_trade s require_approval").

    GET  /api/mcp/signals             what is being called right now (X, Telegram, followed wallets) + live market,
                                      and the market scanner's finds (scan, beta) while market_scan is on; ?source=
                                      (11.11.: rug risk / hard and 4x+ run-up rows only with ?include_hidden=true)
    GET  /api/mcp/token?address=...   one token: live market, who called it in the last hour, our position in it
    GET  /api/mcp/portfolio           the Autopilot: mode, wallet value, open positions with PnL, open orders
    POST /api/mcp/trade               a trade REQUEST: it waits on the Autopilot page until the owner taps
                                      "Odobri" (then it goes through the owner's manual buy / sell); executed here
                                      only with require_approval=false while the owner has grok_autotrade on
                                      (10.11., ui/grokauto.py: Grok's own limits, kill switch, day-loss pause)

Every call needs "Authorization: Bearer <MCP_API_KEY>" (Render env); without that variable the API answers 404, as
if it did not exist. Read-only on the databases except the request queue (trade settings "mcp_requests"), the
assistant's notes (ui/assistnotes.py) and the insert-only X features (xfeat.db, ui/xfeat.py; 10.11. Grok MCP audit 10);
11.11.: also the caller weights (applied on arrival, trade settings caller_weights, behind the flag caller_weights)
and Grok's predictions (events.db grok_predictions, insert only, events/predictions.py).
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
            "scan_found_ts": r.get("first_pass_ts") or r.get("checked_ts"), "scan_via": r.get("via"),
            # 10.11. (BOXCAT): what the NEWEST check says, so a shadow row of an earlier pass is not read as "passes"
            "scan_passed_now": bool(r.get("passed")), "scan_why_now": r.get("why")}


def signals(now=None, source=None, include_hidden=False):
    """Tokens called in the last hour by the accounts the tool tracks (and buys of followed wallets), most callers
    first, each with its live market; while the flag market_scan is on, also the market scanner's passers of the last
    hour (source scan, with their pass reasons) and the betas of the active metas (source beta). A token the scanner
    found that a caller also called is ONE row (source caller or wallet, plus the scanner's fields and lead_time_min:
    how many minutes earlier the scanner had it). source: caller | wallet | scan | beta filters; None = everything
    (the rows before 10.11. keep their fields; the new ones are added).
    11.11. (Grok #54 / #96 / #105): every row carries rug_verdict and runup_x (_hygiene); a row rated rug risk / hard
    or at RUNUP_HIDE_X+ leaves "signals" for "hidden" (only with include_hidden; "hidden_count" always)."""
    src = (source or "").strip().lower() or None
    if src and src not in SIGNAL_SOURCES:
        return {"error": f"source must be one of {', '.join(SIGNAL_SOURCES)}"}
    explicit_now = now   # a caller's own time (tests, reports): the rug tables are read fresh, not from the cache
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
    out, hidden = _hygiene(out, now, scan_rows, cached=explicit_now is None)
    res = {"ts": int(now), "source": "MemeSonar (X, Telegram, followed wallets; DexScreener live; market scanner "
                                     "in shadow while the flag market_scan is on)",
           "filter": src, "signals": out, "hidden_count": len(hidden), "hidden_rule": HIDDEN_RULE}
    if include_hidden:
        res["hidden"] = hidden
    return res


# ---------- 11.11. (Grok's notes #54 / #96 / #105): signal feed hygiene ---------------------------------------------
# get_market_signals listed tokens that fail the rug check (Dacity, DOPE, HWAN, GTA) and late pumps (offered after
# 6-39x, then -95 %). Every row now carries the verdict ui/kandidati uses (rug_view: ok | unknown | oprez | risk | hard)
# and the run-up from the token's first signal of the last 24 h; risk / hard and 4x+ rows are left out by default.
RUNUP_HIDE_X = 4.0          # = ui/kandidati.RUNUP_MAX_X
HIDE_RUG = ("risk", "hard")
HIDDEN_RULE = ("left out of signals (listed under hidden with include_hidden=true): rug_verdict risk or hard (the rug "
               "filter's ODBAČEN / VISOK RIZIK, supply concentration, a collapse, mint / freeze authority, the rug "
               "archive) or runup_x >= 4 (market cap now over the first signal's in 24 h: kol.db first measured call "
               "or the scanner's first sighting as bonded; else 1 + the 1 h change)")
_RUG_TTL_S = 120
_RUG = {"ts": 0.0, "tables": None, "archived": frozenset()}


class _RugSrc:
    """ui/kandidati.rug_view's two reads, with one batched collapse read (hype.db) for all rows."""

    def __init__(self, peaks):
        self.peaks = peaks or {}

    def collapse(self, token, mcap, liq):
        from rugfilter import collapse
        return collapse.check(self.peaks.get(token), mcap, liq)

    def concentration(self, token):
        from league import copy as lcopy
        return lcopy._concentration(token)


def _rug_inputs(cached=True):
    """((topcheck rows, rug.db newest reports), archived mints): cached _RUG_TTL_S (the rug.db read is the slow part)."""
    t = time.time()
    if not cached or _RUG["tables"] is None or t - _RUG["ts"] >= _RUG_TTL_S:
        from scan import filters
        try:
            tables = filters.rug_tables()
        except Exception:  # noqa: BLE001
            tables = ({}, {})
        try:
            from rugfilter import archive
            archived = archive.blocked()
        except Exception:  # noqa: BLE001
            archived = frozenset()
        if not cached:
            return tables, archived
        _RUG.update(ts=t, tables=tables, archived=archived)
    return _RUG["tables"], _RUG["archived"]


def _first_signal(tokens, now, scan_rows):
    """{token: first signal market cap}: the earlier of the first measured call in 24 h (kol.db, ui/zivo.first_calls,
    cached a minute) and the scanner's first sighting as bonded (scan.db cand.mcap_first, within 24 h)."""
    from ui import zivo
    cands = {t: [v] for t, v in zivo.first_calls(now, tokens).items()}
    for t in tokens:
        r = scan_rows.get(t) or {}
        if r.get("mcap_first") and r.get("mcap_first_ts") and now - r["mcap_first_ts"] <= 86400:
            cands.setdefault(t, []).append((int(r["mcap_first_ts"]), float(r["mcap_first"])))
    return {t: min(v)[1] for t, v in cands.items() if v}


def _hygiene(rows, now, scan_rows, cached=True):
    """(visible rows, hidden rows): rug_verdict, rug_reasons, runup_x, runup_from, first_signal_mcap_usd on every
    row; a broken read never hides a row (the fields stay None then)."""
    for r in rows:
        r.update(rug_verdict=None, rug_reasons=[], runup_x=None, runup_from=None, first_signal_mcap_usd=None)
    if not rows:
        return rows, []
    from league import copy as lcopy
    mine = None
    try:
        from ui import data, kandidati
        from rugfilter import collapse
        toks = sorted({r["token"] for r in rows})
        tables, archived = _rug_inputs(cached)
        first = _first_signal(toks, now, scan_rows or {})
        rs = _RugSrc(collapse.peaks(data.HYPE_DB, toks))
        if lcopy._CONC_CACHE is None:   # _concentration reads the same two tables once for all rows
            mine = lcopy._CONC_CACHE = {"tc": tables[0], "rug": tables[1]}
        for r in rows:
            mk = r.get("market") or {}
            m = {"mcap": mk.get("market_cap_usd"), "ch_h1": mk.get("change_1h_pct"), "ch_h24": mk.get("change_24h_pct")}
            rv = kandidati.rug_view(r["token"], m["mcap"] or None, mk.get("liquidity_usd"), rs, tables, archived,
                                    (scan_rows or {}).get(r["token"]))
            ru = kandidati.runup(m, first.get(r["token"]))
            r.update(rug_verdict=rv["level"], rug_reasons=(rv["hard"] + rv["risk"] + rv["warn"])[:3],
                     runup_x=ru["x"], runup_from=ru["from"], first_signal_mcap_usd=ru["mcap_at_first_signal"])
    except Exception as e:  # noqa: BLE001 - the hygiene is extra; the feed answers without it
        print(f"mcp: higijena signala: {type(e).__name__}: {e}", flush=True)
        return rows, []
    finally:
        if mine is not None and lcopy._CONC_CACHE is mine:
            lcopy._CONC_CACHE = None
    vis, hid = [], []
    for r in rows:
        why = []
        if r["rug_verdict"] in HIDE_RUG:
            why.append(f"rug ocjena {r['rug_verdict']}" + (f": {r['rug_reasons'][0]}" if r["rug_reasons"] else ""))
        if r["runup_x"] is not None and r["runup_x"] >= RUNUP_HIDE_X:
            why.append(f"kasno: već {r['runup_x']:.1f}× ({r['runup_from']}; granica {RUNUP_HIDE_X:g}×)")
        if why:
            hid.append(dict(r, hidden_reasons=why))
        else:
            vis.append(r)
    return vis, hid


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
                # 11.11.: whether set_exit_plan sells on the real account (each plan's exit_plan.execution says it too)
                "exit_plans": {"exit_plans": settings.flag("exit_plans", con=tcon),
                               "exit_plan_live": settings.flag("exit_plan_live", con=tcon),
                               "paused_by_owner": bool(raw.get("exit_plans_paused")),
                               "rule": ("a plan sells on the real account (execution.mode live) when exit_plans is "
                                        "live, or when exit_plan_live is live and every lot of the position is a Grok "
                                        "autotrade buy while Grok autotrade is on; otherwise paper: the real account "
                                        "only logs it and keeps its default TP/SL")},
                "grok_autotrade": _grok_part(tcon, now),
                "momentum_candidates": _momentum_part(now),
                "open_orders": {"dca": raw.get("dca_orders") or [],
                                # 11.11.: only what can still be approved (not expired, not a sell of a closed position)
                                "waiting_for_owner": pending(tcon, now)}}
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
        # 11.11.: per account whether the plan sells live (the real account) or paper, and why (league/exitplan)
        out["execution"] = {u: exitplan.execution(u, exitplan._lots(lcon, u, tok)) for u in out.get("stop_price") or {}}
        out["exit_plan_live"] = settings.flag("exit_plan_live", con=tcon)
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


def _momentum_part(now):
    """11.11. (flag momentum_scalp): the newest momentum candidates for Grok to rate (momentum/view.py, read-only)."""
    try:
        from momentum import view
        return view.candidates(now, minutes=60, limit=10)
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
    # 11.11. (flag grok_ev_gate, momentum/evgate.py): optional p_tp (0-1) and strategy; old requests stay valid
    from momentum import evgate
    p_tp, strategy, perr = evgate.parse(body)
    if perr:
        return 400, {"error": perr}
    if auto:   # 10.11. (Jure): executed at once only while the owner has switched grok_autotrade on (ui/grokauto)
        from ui import grokauto
        return grokauto.execute({"token": tok, "side": side, "amount": amount, "reason": body.get("reason"),
                                 "p_tp": p_tp, "strategy": strategy}, now)
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
        req = {"id": rid, "ts": now, "token": tok, "side": side, "amount": amount, "status": "pending",
               "reason": str(body.get("reason") or "")[:300], "client": "mcp"}
        if p_tp is not None:
            req.update(p_tp=p_tp, strategy=strategy)
        reqs.append(req)
        settings.put(tcon, "mcp_requests", reqs[-100:], "mcp")
    finally:
        tcon.close()
    print(f"mcp: zahtjev {rid} {side} {tok[:6]} {amount:g} čeka odobrenje", flush=True)
    out = {"status": "pending_approval", "id": rid,
           "message": "Waiting for the owner's approval on the MemeSonar Autopilot page; expires in 15 minutes."}
    if side == "buy" and p_tp is not None:
        out["ev_gate"] = _calib_queued(tok, amount, p_tp, strategy, now)
    return 202, out


def _calib_queued(tok, amount, p_tp, strategy, now):
    """11.11.: a queued buy with p_tp is recorded for calibration (never refused here: the owner decides) and the
    answer says what the EV gate makes of it."""
    try:
        from momentum import evgate
        g = evgate.check(tok, amount, p_tp, strategy, None, now, gate_mode="off")
        g["mode"] = evgate.mode()
        evgate.record(g, tok, amount, "pending_approval", now)
        return {"ev_pct": round(g["ev"] * 100, 2) if g.get("ev") is not None else None,
                "break_even_p_tp": round(g["break_even_p"], 3) if g.get("break_even_p") is not None else None,
                "would_pass": g.get("would_reject") is None, "why": g.get("would_reject")}
    except Exception as e:  # noqa: BLE001 - bookkeeping never fails a request
        return {"error": type(e).__name__}


def _open_tokens(tcon):
    """{token: [opened_ts of each open position]} (a dict: `token in` works as with the set it used to be)."""
    out = {}
    try:
        for t, ts in tcon.execute("SELECT token, opened_ts FROM positions WHERE status='open'"):
            out.setdefault(t, []).append(int(ts or 0))
    except Exception:  # noqa: BLE001 - no positions table yet: nothing is open
        return {}
    return out


def sell_positions_open(r, open_tokens):
    """11.11. (VC sell g1794342901001, its position closed 10.11. 21:55): a sell request is about the positions of
    its token that were open when it was made (opened at or before its ts); a position opened later is another
    position. True while at least one of those is still open (open_tokens: _open_tokens() or a plain set)."""
    tok = r.get("token")
    if tok not in open_tokens:
        return False
    opened = open_tokens.get(tok) if isinstance(open_tokens, dict) else None
    return opened is None or any(ts <= (r.get("ts") or 0) for ts in opened)


def request_status(r, now, open_tokens):
    """11.11. (Jure: request g1794340688000 for Hope still "pending" after the position was closed): the status a
    request really has now. A pending sell whose position is no longer open is "obsolete" (sell_positions_open: a
    NEW position in the same token does not revive an old sell); a pending request older than REQUEST_TTL_S is
    "expired" (it can no longer be approved: the market moved); everything else as stored."""
    st = r.get("status")
    if st != "pending":
        return st
    if r.get("side") == "sell" and not sell_positions_open(r, open_tokens):
        return "obsolete"
    if now - (r.get("ts") or 0) >= REQUEST_TTL_S:
        return "expired"
    return "pending"


def pending(tcon, now=None):
    """The requests that still wait for the owner (younger than REQUEST_TTL_S, and a sell only while its position is
    open), oldest first."""
    now = now or time.time()
    reqs = settings.raw(tcon).get("mcp_requests") or []
    if not any(r.get("status") == "pending" for r in reqs):
        return []
    op = _open_tokens(tcon)
    return [r for r in reqs if request_status(r, now, op) == "pending"]


def requests_view(tcon, now=None, limit=20, include_closed=True):
    """The last `limit` requests, newest first, each with its real status (pending | expired | obsolete | approved |
    rejected | failed ...) and its age in minutes (get_hourly_brief). include_closed=False: only those still pending
    (11.11.: the brief listed the closed ones too, so a sell of a position closed the day before still showed)."""
    now = now or time.time()
    reqs = list(settings.raw(tcon).get("mcp_requests") or [])[-int(limit):]
    op = _open_tokens(tcon)
    out = []
    for r in reversed(reqs):
        d = {k: r.get(k) for k in ("id", "ts", "token", "side", "amount", "reason", "decided", "note")}
        d["status"] = request_status(r, now, op)
        if not include_closed and d["status"] != "pending":
            continue
        d["age_min"] = round((now - (r.get("ts") or now)) / 60, 1)
        out.append(d)
    return out


def tidy_requests(tcon=None, now=None):
    """Store the real status of stale pending requests (obsolete / expired, with the time and the reason), so every
    reader of trade settings sees it. Run by the 5-min events tick (run_events.py tick). Returns requests changed."""
    now = int(now or time.time())
    own = tcon is None
    tcon = tcon or settings.connect()
    try:
        reqs = list(settings.raw(tcon).get("mcp_requests") or [])
        if not any(r.get("status") == "pending" for r in reqs):
            return 0
        op = _open_tokens(tcon)
        n = 0
        for r in reqs:
            st = request_status(r, now, op)
            if st != r.get("status"):
                r["status"], r["decided"] = st, now
                r["note"] = "pozicija je već zatvorena" if st == "obsolete" else "isteklo bez odgovora (15 min)"
                n += 1
        if n:
            settings.put(tcon, "mcp_requests", reqs, "events")
        return n
    finally:
        if own:
            tcon.close()


REQUESTS_ONCE_KEY = "owner_once_1111_requests"


def cleanup_requests_once(tcon, now=None):
    """11.11. (Jure): the stale requests stored before the 5-min tidy existed, tidied once at the first start after the
    deploy (ui/assistnotes.owner_once_1111). Returns the requests changed (0 when it ran before)."""
    if settings.raw(tcon).get(REQUESTS_ONCE_KEY):
        return 0
    n = tidy_requests(tcon, now)
    settings.put(tcon, REQUESTS_ONCE_KEY, int(now or time.time()), "Jure")
    return n


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


def _truthy(x):
    """A boolean argument from JSON (true) or a query string ("true", "1", "yes", "da")."""
    return x is True or str(x or "").strip().lower() in ("1", "true", "yes", "da")


def answer(path, qs):
    """(status, JSON text) of a GET."""
    if path == "/api/mcp/signals":
        data = signals(source=qs.get("source"), include_hidden=_truthy(qs.get("include_hidden")))
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
                     "null when unknown. One row per token. source filters: caller | wallet | scan | beta; none = all. "
                     "Every row also: rug_verdict (ok | unknown | oprez | risk | hard, the same rating as "
                     "get_trade_candidates' rug.level) with rug_reasons, and runup_x (market cap now over the first "
                     "signal's in the last 24 h) with runup_from. Rows rated risk / hard or with runup_x >= 4 are left "
                     "out (hidden_count); include_hidden=true lists them under hidden with hidden_reasons."),
     "inputSchema": {"type": "object", "properties": {
         "source": {"type": "string", "enum": ["caller", "wallet", "scan", "beta", "hidden_group"],
                    "description": "only rows of this source (default: all)"},
         "include_hidden": {"type": "boolean", "default": False,
                            "description": "also list the rows left out (rug risk / hard, run-up 4x+) under hidden"}}}},
    {"name": "get_token_details", "annotations": _READ,
     "description": ("One Solana token by its address: live market, who called it in the last hour, MemeSonar's open "
                     "position in it. Tokens under $30k market cap are flagged (MemeSonar does not trade them)."),
     "inputSchema": {"type": "object", "properties": {"token_address": {"type": "string",
                                                                          "description": "Solana token mint address"}},
                     "required": ["token_address"]}},
    {"name": "get_portfolio_status", "annotations": _READ,
     "description": ("The MemeSonar Autopilot: mode (live / trial / off), wallet value in SOL, limits, every open "
                     "position (entries, average entry market cap, market cap now, PnL %, exit rule, exit_plan with "
                     "execution.mode live = it sells on the real account | paper = only logged there, and why), "
                     "exit_plans (the flags deciding that), open orders, and "
                     "momentum_candidates: the newest momentum_scalp signals (bonded jumps that met every entry rule, "
                     "with their numbers and outcome), near misses, the base rate and the paper proof, to rate with "
                     "execute_trade strategy momentum_scalp and p_tp."),
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
                     "open position (0.25 = 25 %, 1 = all). reason: one line for the owner. "
                     "Buy gate (11.11., replaces P(+20 % in 4 h) >= 0.6): send p_tp = your probability (0-1) that the "
                     "strategy's take profit comes BEFORE its stop, and strategy: momentum_scalp (TP +15 % / SL -10 %, "
                     "45 min), range_dca (TP range_high_low / SL range_low_low x 0.85 of the token's range, 24 h) or "
                     "other (default: the exit your buys get, the owner's TP, default +15 %, and the default stop, "
                     "-60 % unless changed, 4 h). EV = p_tp x TP - (1 - p_tp) x SL - cost (~2-3 % round trip: 1 % fee "
                     "each side + pool impact). While the owner has grok_ev_gate in paper or live, an autotrade buy "
                     "with EV <= 0 or without p_tp is rejected with the numbers, and a momentum_scalp / range_dca buy "
                     "gets that strategy's TP / SL as its exit; in shadow it is only logged. Break-even p_tp: ~0.5 for "
                     "momentum_scalp, ~0.83 for other with a -60 % stop. Every buy with p_tp is scored later (TP "
                     "before SL within the horizon) for your calibration: get_hourly_brief grok_calibration (Brier "
                     "score, hit rate per p bucket). Both fields are optional; old calls work as before."),
     "inputSchema": {"type": "object", "properties": {
         "token_address": {"type": "string", "description": "Solana token mint address"},
         "amount": {"type": "number", "description": "SOL for a buy, share 0-1 for a sell"},
         "side": {"type": "string", "enum": ["buy", "sell"]},
         "require_approval": {"type": "boolean", "default": True},
         "reason": {"type": "string"},
         "p_tp": {"type": "number", "minimum": 0, "maximum": 1,
                  "description": "your probability that the strategy's TP comes before its SL (buy only)"},
         "strategy": {"type": "string", "enum": ["momentum_scalp", "range_dca", "other"], "default": "other",
                      "description": "whose TP / SL the EV gate prices (buy only)"}},
         "required": ["token_address", "amount", "side"]}},
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
                     "caller's call_power, score_source linked_kol_call_power). copy_score: the copy ranking 0-100 "
                     "(30 days, closed positions: Wilson win rate, median return, profit factor, copyability, recency; "
                     "no absolute SOL PnL), copy_proven = 10+ closed tokens, copy_copyable = median entry liquidity "
                     "15k+. kind: influencer (a known influencer's wallet) or smart (tier S/A/B)." + _PAGED),
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
                     "waiting for approval), or a get_trade_candidates / get_grok_tasks token: verdict kupi | "
                     "preskoči | dobar | loš | neutralan, confidence 0-1, interpretation, evidence. Shown next to the "
                     "position or the waiting request; buys nothing. A kupi / dobar of the last 30 min can lift a rug "
                     "risk rating (grok_override, half size); a newer preskoči / loš takes it back. Optional (11.11., "
                     "proposals G21): a trade PROPOSAL with verdict kupi + p_tp (your probability 0-1 that the take "
                     "profit comes before the stop), strategy (range | momentum | influencer | group | insider | event | "
                     "catalyst | grok), entry_zone {mcap_low, mcap_high}, exit_zone {tp_mcap, sl_mcap, trailing_pct} "
                     "and valid_min (5-1440, default 60): shown on the Autopilot's Prijedlozi and in get_proposals "
                     "only when your p_tp CALIBRATED on your measured predictions gives EV > 0 after cost and no block "
                     "applies; without these fields nothing changes."),
     "inputSchema": {"type": "object", "properties": {
         "token": {"type": "string"}, "verdict": {"type": "string", "enum": ["kupi", "preskoči", "dobar", "loš", "neutralan"]},
         "confidence": {"type": "number", "minimum": 0, "maximum": 1}, "interpretation": {"type": "string", "maxLength": 4000},
         "evidence": {"type": "object"},
         "strategy": {"type": "string", "enum": ["range", "momentum", "influencer", "group", "insider", "event",
                                                 "catalyst", "grok"]},
         "p_tp": {"type": "number", "minimum": 0, "maximum": 1},
         "entry_zone": {"type": "object", "properties": {"mcap_low": {"type": "number", "exclusiveMinimum": 0},
                                                         "mcap_high": {"type": "number", "exclusiveMinimum": 0}}},
         "exit_zone": {"type": "object", "properties": {"tp_mcap": {"type": "number", "exclusiveMinimum": 0},
                                                        "sl_mcap": {"type": "number", "exclusiveMinimum": 0},
                                                        "trailing_pct": {"type": "number", "minimum": 1, "maximum": 90}}},
         "valid_min": {"type": "integer", "minimum": 5, "maximum": 1440}},
         "required": ["token", "verdict", "interpretation"]}},
    {"name": "submit_suggestion", "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
     "description": ("Suggest an improvement for the owner: title, interpretation, improvement, evidence, and optionally "
                     "proposed_change. The owner taps 'Označi prihvaćenim (bez promjene)' (agrees, NOTHING changes), Odbij, "
                     "or 'Primijeni na bota' (applies it); only these keys are applied by that tap: {\"key\": tp_default | "
                     "sl_default | size_sol | max_open | auto_skip | copy.max_delay_min | copy.min_liq | copy.max_mcap | "
                     "copy.min_mcap | copy.min_liq_mcap | copy.crew_window_min | copy.max_per_day | dca_token_cap (SOL per "
                     "token, 0.01-5) | require_signal (true/false) | runup_max (fraction 0.02-2), \"from\": current, "
                     "\"to\": new} or {\"caller\": handle, \"platform\": x|telegram, \"weight\": 0-2} (a caller weight is "
                     "applied on arrival, no tap: the owner's standing order of 11.11.). dca_token_cap, "
                     "require_signal, runup_max and caller weights sit behind flags (dca_cap, require_signal, runup_default, "
                     "caller_weights): the owner's 'Primijeni' moves an off flag to shadow only, the automatic weight "
                     "never moves a flag; live is the owner's call after a backtest. "
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
     "description": ("Set per-caller weights (0-2, 1 = neutral) with a reason: one suggestion note each (kind "
                     "suggestion, proposed_change {caller, platform, weight}), APPLIED AT ONCE to the trade settings "
                     "caller_weights (the owner's standing order of 11.11.; logged in applied_suggestions with old -> "
                     "new and the note marked primijenjeno). The weights act only through the flag caller_weights "
                     "(its mode is in the answer; this tool never changes it). Does not trade. At most 50 per call, 60 "
                     "notes an hour."),
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
                     "at most 120 rows an hour. get_trade_candidates and the market scanner read your token rows "
                     "of the last 2 h first (they replace MemeSonar's paid X lookup); a fresh row (30 min) naming "
                     "known callers / large accounts or growing organic authors can lift a rug risk rating "
                     "(get_grok_tasks x_check lists the keys: posts_15m, posts_60m, unique_authors_15m, "
                     "unique_authors_60m, known_callers, large_accounts, bot_share, note)."),
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
                     "one; live = both. The owner's switch exit_plan_live (live = on) executes a plan on the REAL "
                     "account for a Grok autotrade position (every lot bought by your execute_trade "
                     "require_approval=false, while grok_autotrade is on) whatever exit_plans says. The answer's "
                     "execution says per account live or paper. A price older than 60 s fires only the hard stop. accounts (optional): the "
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
                     "parent meta's state (raste / pada); today's spend per paid source and the caps. Also the "
                     "combined sources: kandidati (a top tradeable row of get_trade_candidates, entered when it first "
                     "ranks in the top 5) and grok_override (a row your fresh evidence lifted over a rug risk "
                     "rating), and combined = both next to the best single source: does confluence pay, does "
                     "overriding the rug rating pay. Read-only."),
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
                     "quality (8+ events measured at 1 h / 4 h / 24 h, median 4 h > 0, median 24 h > -30 %, EV > 0 at "
                     "1 h and 4 h) | exit_liquidity (the public calls fall after the group) | bad | insufficient_data, "
                     "n_measured and grade_text next to it, link density, shill_network / shill_parts (flag pre_shill) and "
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
# 11.11. (flag pre_shill, kol/preshill.py): wallets that buy before the paid shill network, read-only; empty while off
TOOLS += [
    {"name": "get_pre_shill_wallets", "annotations": _READ,
     "description": ("The paid shill network(s) (\"plaćena shill mreža\": a caller group graded bad with 20+ accounts, "
                     "after a chain check: a component joined only through chains of pairs is split by link density, "
                     "4-truss and a higher lift, and a chained part is never a network; chain_checks shows the "
                     "measurement of every big group) and the wallets that bought the network's tokens in the 6 h "
                     "BEFORE its first call (T0). Per wallet: status confirmed (selected on the older 2/3 of 14 days, "
                     "confirmed on the newer 1/3) or candidate (>= 3 tokens, on average 5-120 min before T0, PnL > 0), "
                     "cluster (same funder or same slot: likely the network's owners), tokens bought before T0, median "
                     "/ average minutes before T0, entry market cap, PnL in SOL, hit rate, median hold, share sold into "
                     "the wave of shill calls, shared funders, a Croatian sentence, and per token the timeline: buy, "
                     "first shill call, peak, sell. Dev-funded wallets, bundlers (3+ wallets in one slot), bots (> 200 "
                     "trades a day), relayers, LP and CEX are out; the trade is the signing owner's, never a fee "
                     "payer's. Shadow only: a shill-network call is exit liquidity, nothing is bought. status: "
                     "candidate | confirmed | watch | excluded | all (default candidate + confirmed)." + _PAGED),
     "inputSchema": {"type": "object", "properties": {
         "status": {"type": "string", "enum": ["candidate", "confirmed", "watch", "excluded", "all"]}, **_PAGE}}},
    {"name": "get_pre_shill_signals", "annotations": _READ,
     "description": ("Shadow signals since since_ts (unix s, default 7 days): 2+ pre-shill wallets (or one wallet of "
                     "a cluster) bought a token before any public call. Per signal: detection time (up to 30 min after "
                     "the buy), wallets, clusters, market cap (under_30k), the measured result from the detection "
                     "(+20 % before -30 % within 1 h / 4 h, EV after cost), minutes until the shill network started "
                     "calling and until the first public call, and the result of selling into the network's first "
                     "call (the exit rule). Summary: EV and the sell-into-calls result. Nothing is bought."),
     "inputSchema": {"type": "object", "properties": {"since_ts": {"type": "integer"},
                                                      "limit": {"type": "integer", "minimum": 1, "maximum": 500}}}},
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
                     "range (0 % = range_low_low, 100 % = range_high_top), the 5-minute numbers, exclusions, whether "
                     "an entry would pass now (entry_now, and entry_ready true | false; entry-ready rows first). A "
                     "price above 100 % of the range is status breakout: never a range entry candidate, listed apart "
                     "under breakouts. Also the open range positions (account, lots, exit levels) and the paper "
                     "proof (closed rounds, EV per round, the live gate: >= 20 rounds with EV > 0). Tokens under $30k "
                     "market cap and tokens still on the pump.fun curve are never in it. To tighten a range position's "
                     "exits use set_exit_plan with plan.accounts set to its account. 11.11.: per row source (signal = "
                     "our own signals, event = an event topic's token, market = the whole-market watchlist; several: "
                     "signal > event > market, all in sources), entry_ready (not a breakout and the entry rules pass "
                     "now; those rows first) and paper_only (market / event tokens are traded only on the demo account, "
                     "never with real money); breakouts (ranges broken upward), watched_by_source and the watchlist's "
                     "filter, refresh and cost today per source. Source missed (flag range_missed): a token skipped "
                     "and then >= +20 % within 60 min, watched 72 h (signal > event > missed > market); the answer's "
                     "missed part has its filter, the closed rounds of source missed vs the others (rounds, wins, EV, "
                     "PnL) and its own live gate (>= 20 rounds of source missed with EV > 0; paper only before that). "
                     "While the flag range_flip is not off: per row "
                     "range_flip (status normal | flip_candidate | flipped | paused | resumed, the confirmed break, the "
                     "flip zone or the resistance in market cap, retests, ATR, stop_kind, the stop of today's rules and "
                     "of the new ones, the range after the break), flip_status and entry_ready_new_rules, and the "
                     "range_flip list of every token not in state normal (a paused token may not be a candidate). "
                     "11.11.: owner_labels (the owner's learning labels, e.g. HAOBIBI win / missed_win_stop_too_early: "
                     "entry, lot 2, stop, peak, TP in market cap; counterfactual, the booked round never changes), "
                     "pins (the owner's pinned tokens: always listed, row pinned true, pin_ready / pin_entry = price in "
                     "the range's lower zone AND volume 1 h >= 50 % of its 6 h median and >= $10k; a recommendation, "
                     "never buy one with real money on your own), per row similar_to (the most similar labelled win, "
                     "score 0-1) and similar (top 10, similar_rule says how it is computed)."),
     "inputSchema": {"type": "object", "properties": {
         "min_score": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.7},
         "source": {"type": "string", "enum": ["signal", "market", "event", "missed"],
                    "description": "only rows whose sources include this one"}}}})


# 11.11. (Jure: "event tokeni s Grokom", flag event_tokens G19, topics/): Grok's event topics and their tokens
TOOLS += [
    {"name": "submit_event_topic",
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
     "description": ("Send an event topic you see driving meme tokens on X (e.g. GTA6's release), or update one: upsert "
                     "by name (case and spaces do not matter). keywords: 1-20 strings incl. tickers, each at least 2 "
                     "letters or digits, e.g. [\"GTA6\", \"GTA 6\", \"Grand Theft Auto\", \"$GTA6\"]; matching is "
                     "token-aware (\"GTA 6\" == \"GTA6\" == \"gta-6\" == \"$GTA6\", but GTA6 never matches GTA, GTA5 or "
                     "GTAV; list those too if they should count). event_ts: unix seconds or ISO 8601 when known. "
                     "buzz_score 0-100 from X (send it again as it changes: the history is the trend). status "
                     "upcoming -> live -> done (only forward). New topics need keywords; an update may send any field. "
                     "At most 8 active (upcoming / live) topics, 60 writes an hour; refused while the owner has the "
                     "flag event_tokens off. MemeSonar then matches new pump.fun tokens in real time and searches "
                     "DexScreener every 10 min per active topic. Nothing is bought with real money."),
     "inputSchema": {"type": "object", "properties": {
         "name": {"type": "string", "minLength": 2, "maxLength": 60},
         "keywords": {"type": "array", "items": {"type": "string", "minLength": 2, "maxLength": 60}, "minItems": 1,
                      "maxItems": 20},
         "event_ts": {"type": ["integer", "string"], "description": "unix seconds or ISO 8601"},
         "buzz_score": {"type": "number", "minimum": 0, "maximum": 100},
         "status": {"type": "string", "enum": ["upcoming", "live", "done"]},
         "source": {"type": "string", "maxLength": 40, "description": "where you saw it, default x"},
         "note": {"type": "string", "maxLength": 500}}, "required": ["name"]}},
    {"name": "get_event_topics", "annotations": _READ,
     "description": ("The event topics with their ids: name, keywords, event_ts, status, buzz_score, buzz_trend (↑ ↓ →) "
                     "and buzz_spark from the buzz history, created_by, how many tokens match and the main token. "
                     "status: upcoming | live | done | active (upcoming + live); default all, newest first."),
     "inputSchema": {"type": "object", "properties": {
         "status": {"type": "string", "enum": ["upcoming", "live", "done", "active"]},
         "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50}}}},
    {"name": "get_event_tokens", "annotations": _READ,
     "description": ("All Solana tokens whose ticker, name or description matches one topic's keywords (new pump.fun "
                     "tokens in real time, DexScreener / Birdeye search, the scanner's tokens), main first: per token "
                     "role (main = the most liquid with organic X; clone = under 30 min old with snipers / bundlers "
                     "holding over 30 %; rug = the rug check says hard or risk; other) and why, the match (field, "
                     "keyword, via), age_min, market (price, market cap, liquidity, 1 h / 24 h volume, bonded, its "
                     "source and time), holders, snipers_pct, the rug check, X numbers you or the scanner stored "
                     "(organic yes / no), the range (status, score, position, entry_ready) and the price 24 h before / "
                     "at / 24 h after event_ts with the changes. measure_summary: the median run-up into the event "
                     "and the median move after it (buy the rumour, exit before the event). Read-only."),
     "inputSchema": {"type": "object", "properties": {"topic_id": {"type": "integer"}}, "required": ["topic_id"]}},
]
INSTRUCTIONS += (" Event topics: when X shows a real-world event driving meme tokens, send it with submit_event_topic "
                 "(keywords incl. tickers, event_ts, buzz_score) and update the buzz as it changes; get_event_topics "
                 "gives the ids, get_event_tokens(topic_id) the matching tokens with main / clone / rug.")


# 10.11. (Jure: "najvažnije je naći tokene kojima treba trgovati"; ui/kandidati.py): one ranked row per token over
# every source, and the work queue where Grok's free X / web judgement adds most. Read-only.
TOOLS += [
    {"name": "get_trade_candidates", "annotations": _READ,
     "description": ("ONE row per token over every source MemeSonar has right now (callers with each account's measured "
                     "record and verdict, followed and tier S/A wallets, the market scanner and betas, hidden wallet "
                     "lists, caller crews, range candidates, the tool's own top list, pre-call insiders), ranked: "
                     "tradeable first, then ev_pct, then confluence, then score (the formula is in the answer's "
                     "ranking): confluence never outranks a negative EV. ev_pct = the expected result per trade in % "
                     "after the one cost model (2 x fee + 2 x the pool impact of suggested_size_sol) and the P "
                     "modifiers (the measured records the row's sources rest on, n-weighted, shrunk toward 0); "
                     "n_samples = how many measured outcomes it rests on; ev_confidence low under 10. tradeable=true "
                     "ONLY with ev_pct > 0 and no block (rug high, liquidity under $15k, 1 h volume under $3k, the "
                     "market gates); else why_not names it (\"negativan EV\", the block, or a row without a measured "
                     "record: its fast_check's verdict). Each row's \"fast\": the token's fast_check (decision KUPI "
                     "(paper) / KUPI (live-eligible) / PRESKOČI, EV with its 90 % interval, P with n and its origin "
                     "source | prior: <strategy> (\"procjena, n izvora < 10\"), the lag from the source's entry); a row "
                     "whose sources have no record takes the fast_check's EV. "
                     "tags / modifiers (never blocks): run-up 4x+ (p x 0.7, size x 0.5 unless X bursts and buys >= 60 "
                     "%), shill-driven (p x 0.5), a pool under 3 % of MC. Per row: evidence per "
                     "source with that source's measured shadow record (n, hit1h / hit4h = +20 % within 1 h / 4 h, "
                     "sl_first = -30 % first, ev after cost), confluence (independent signals; a caller crew within "
                     "10 min counts once), the market now, runup (market cap now / at the first signal; 4x or more is "
                     "a tag), rug (hard = a collapse, mint / freeze, honeypot: never tradeable; risk = a "
                     "rating), x (your fresh X row first), tradeable and why_not, grok_override (your fresh evidence "
                     "lifted a rug RISK rating: warning shown, half suggested_size_sol, tight exit_plan), "
                     "suggested_size_sol and exit_plan in set_exit_plan's format. Buys nothing. min_sources: at "
                     "least this confluence (default 1); limit 1-100 (default 30)."),
     "inputSchema": {"type": "object", "properties": {
         "min_sources": {"type": "integer", "minimum": 1, "maximum": 10, "default": 1},
         "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 30}}}},
    {"name": "get_grok_tasks", "annotations": _READ,
     "description": ("Your work queue, most useful first, with how_to_work: x_check (search X for a top candidate's CA "
                     "and ticker; answer with submit_x_features: it can lift a rug risk rating and saves MemeSonar's "
                     "paid X lookup), resolve_conflict (sources disagree, e.g. good callers but falling X momentum; "
                     "answer with submit_signal_opinion), label_group / label_insiders (name a hidden wallet list, a "
                     "caller crew or pre-call insiders; answer with submit_suggestion group_label / insider_label). "
                     "Each task carries the exact tool and arguments; a task disappears once your answer is stored. "
                     "limit 1-100 (default 20). Read-only; never trade outside grok_autotrade limits."),
     "inputSchema": {"type": "object", "properties": {
         "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}}}},
]
INSTRUCTIONS += (" Start with get_grok_tasks and get_trade_candidates: the candidates are ranked over every source, "
                 "and your fresh X rows (submit_x_features) feed the ranking and the scanner.")

# 11.11. (Jure, proposals/ flag proposals G21): the Autopilot's "Prijedlozi" for Grok, read-only
TOOLS.append(
    {"name": "get_proposals", "annotations": _READ,
     "description": ("The Autopilot's trade proposals from every strategy (range, momentum, influencer, group, insider, "
                     "event, catalyst, grok), ONE row per token, the same list the owner sees. Per proposal: status "
                     "(novo | kupljeno | isteklo | odbijeno), strategy (the best) and sources (every strategy proposing "
                     "it), n_independent, ev_pct = p_tp x TP - (1 - p_tp) x SL - cost (cost = 2 x fee + 2 x the stake's "
                     "pool impact, one model), ev_lo_pct (the EV at the low end of p_tp's 90 % interval), ev_per_min "
                     "(the ranking: EV per expected minute, then ev_lo_pct, then liquidity), p_tp with n and ci90 "
                     "(Wilson 90 %), modifiers (run-up 4x+ p x 0.7 / size x 0.5, wash or shill p x 0.5: never blocks), "
                     "paper_only (event / market watchlist rows: never real money), per strategy its p_tp, n, EV, entry "
                     "zone and exits in market cap, your raw and calibrated p_tp (grok, grok_calibration), exit_plan in "
                     "set_exit_plan's format, size_sol (<= 0.15 SOL, the owner's caps and the stake with <= 2 % "
                     "slippage), risks, why, expires_ts, and for decided / expired ones what happened after (after: max gain, max drawdown, TP before SL at 1 h and 4 h). report: "
                     "the newest daily report per strategy with the day's missed risers. since: unix time (default "
                     "24 h ago); min_ev: at least this ev_pct (default 0); status: only this status; include_blocked: "
                     "also the last pass's near misses with their blocks; limit 1-200 (default 50). Read-only: buy a "
                     "proposal only through execute_trade within your grok_autotrade limits; add one with "
                     "submit_signal_opinion (kupi + p_tp). 11.11.: owner_labels (the owner's learning labels, "
                     "counterfactual), per row pinned / pin_only (the owner's pin: a recommendation, never buy it with "
                     "real money on your own) and similar_shadow (a P bonus for tokens similar to his labelled wins, "
                     "recorded only: p_tp and ev_pct are unchanged)."),
     "inputSchema": {"type": "object", "properties": {
         "since": {"type": "integer", "minimum": 0}, "min_ev": {"type": "number", "default": 0},
         "status": {"type": "string", "enum": ["novo", "kupljeno", "isteklo", "odbijeno"]},
         "include_blocked": {"type": "boolean", "default": False},
         "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50}}}})
# 11.11. (Jure, fast/ flag fast_path G24): every fast_check decision for Grok's opinion, read-only
TOOLS.append(
    {"name": "get_fast_checks", "annotations": _READ,
     "description": ("The fast path's decisions: every buy of a followed wallet (wallet_follow, insider, pre_shill, "
                     "group) and every call of a followed influencer gets five checks at once and a decision. Per "
                     "signal: source (kind, id, label, via), signal_ts (the wallet's buy / the call), decided_ts, "
                     "latency_s (seconds from the signal to the decision), decision (BUY_PAPER | BUY_LIVE | SKIP | "
                     "CHECK_FAILED) with reason and decided_by (the check or rule), ev_pct = p_tp x 15 % - (1 - p_tp) x "
                     "10 % - cost (2 x fee + 2 x the stake's pool impact), p_tp (the source's record shrunk toward "
                     "base_rate, x the run-up / wash modifiers), "
                     "size_sol, checks {rug, holders, flow, price, source}: status ok | fail | error, text, values "
                     "(numbers), threshold, ms; wallet_entry and price_at_decision; source_quality (closed, winners, "
                     "PnL, tier, proof = run_trade's real-money proof); outcome (+1/+5/+15/+60 min, max and min within "
                     "60 min, hit = +15 % before -10 % within 45 min) and missed (SKIP that did >= +20 %); traded (the "
                     "demo trade). report: the newest daily report (false rejects per check, latency, cost per source). "
                     "since: unix time (default 24 h ago); decision: only that one; limit 1-200 (default 50). Read-only: "
                     "give your opinion with submit_signal_opinion."),
     "inputSchema": {"type": "object", "properties": {
         "since": {"type": "integer", "minimum": 0},
         "decision": {"type": "string", "enum": ["BUY_PAPER", "BUY_LIVE", "SKIP", "CHECK_FAILED"]},
         "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50}}}})
# 11.11. (Jure, part D, momentum/evgate.py): the buy gate is an EV with the strategy's TP / SL
INSTRUCTIONS += (" Buy gate: send execute_trade with p_tp (your probability 0-1 that the take profit comes before the "
                 "stop) and strategy (momentum_scalp: +15 % / -10 % in 45 min; range_dca: the range's zones; other: "
                 "the owner's exit, default +15 % / -60 %). Buy only when EV = p_tp x TP - (1 - p_tp) x SL - cost "
                 "(~2-3 %) > 0; with grok_ev_gate on, the server rejects the rest. get_portfolio_status and "
                 "get_hourly_brief list momentum_candidates (fresh jumps that met every momentum_scalp entry rule) to "
                 "rate, and grok_calibration shows how well your p_tp matched what happened.")


# 11.11. (Jure, events.db): one read-only call with what an hourly look needs (events/brief.py)
TOOLS.append(
    {"name": "get_hourly_brief", "annotations": _READ,
     "description": ("Everything for an hourly look in one read-only call. portfolio: get_portfolio_status's answer "
                     "(open positions with entry and current market cap, PnL %, exit plan with its execution live | "
                     "paper, account live | trial; wallet SOL; grok_autotrade state and what is left today) plus "
                     "paper_positions (the paper account's open demo trades, account paper). trade_requests: the "
                     "execute_trade requests still pending (younger than 15 min, a sell only while the positions it "
                     "was about are open); with include_closed=true also the rest of the last 20 with their real status "
                     "(expired = older than 15 min; obsolete = a sell whose position is already closed; approved, "
                     "rejected, failed); trade_requests_closed_hidden counts the ones left out. signals: tokens with "
                     "calls, followed wallets' "
                     "buys or signals (scan, groups, autopilot, grok) since `since`, most sources first, with "
                     "precomputed features: rug verdict and snipers %, fees_paid_sol and volume_1h_usd, "
                     "run_up_since_first_seen_pct, phase (final_stretch = on the curve, migrated), X numbers "
                     "(posts_per_h, unique authors, template_share, brag_ratio), every caller's and wallet's score "
                     "(n, n_measured, hit_rate = +20 % within 4 h, median max 4 h, EV) and wallets' early-buyer "
                     "record. groups: group activity and hidden_group signals. range_candidates: range_score >= 0.7, "
                     "only tokens inside their range (entry_ready = an entry would pass now; a price above 100 % of "
                     "the range is a breakout, never a range entry; breakouts lists them apart). "
                     "momentum_candidates: the newest momentum_scalp signals and near misses to rate (strategy "
                     "momentum_scalp, p_tp = +15 % before -10 % in 45 min). grok_calibration: your execute_trade p_tp "
                     "against the outcomes (Brier score, hit rate per p bucket). grok_predictions: "
                     "your submit_grok_prediction rows scored since `since` (per horizon 1h / 4h / 24h: max gain, max "
                     "loss, which of TP / SL came first, up10/20/50), pending, and the calibration per p_tp bucket "
                     "(predicted vs actual %) for you and for MemeSonar's own EV-implied probability, with Brier "
                     "scores. zonewatch: armed (zones in force, by source), alerts_24h (by event and status), "
                     "last_post_ok, last_error, configured (whether the Grok Bot webhook is set), the flag, "
                     "without_range (watched tokens with no active range, so no zones, and why), positions (the real "
                     "account's positions and levels watched), position_alerts_24h (by level) and range_off_24h. "
                     "health: feed gap alerts (no events of an active type for > 60 min, 08-24 Zagreb), "
                     "last_night (started_ts, finished_ts, duration_s, calls_processed, helius_credits, errors, "
                     "status) and an alert when the night batch has not finished by 04:30 Zagreb. timing_ms per part."),
     "inputSchema": {"type": "object", "properties": {
         "since": {"type": ["string", "integer"],
                   "description": "ISO 8601 or unix seconds / milliseconds; default the last 60 minutes"},
         "limit_signals": {"type": "integer", "minimum": 1, "maximum": 100, "default": 30},
         "include_closed": {"type": "boolean", "default": False,
                            "description": "also the trade requests that no longer wait (expired, obsolete, approved, "
                                           "rejected, failed)"}}}})
# 11.11. (Jure): Grok's predictions, stored immutable and scored after 1 h / 4 h / 24 h (events/predictions.py)
_P01 = {"type": "number", "minimum": 0, "maximum": 1}
TOOLS.append(
    {"name": "submit_grok_prediction",
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
     "description": ("Store one prediction for a token, made NOW (ts at most 15 min old; immutable once stored; buys "
                     "nothing). strategy momentum | range | call; mcap = market cap at ts (under $30k refused); p_tp = "
                     "probability that +tp_pct comes before -sl_pct (sl_pct = the stop in % below the entry); "
                     "p_up10_1h ... p_up50_24h = probability that the high within 1 h / 4 h / 24 h reaches +10 / +20 "
                     "/ +50 % (up10 >= up20 >= up50, and never lower for a longer horizon); p_drop30_first = "
                     "probability that -30 % comes before +20 %; verdict runner | avoid | neutral; reasons. MemeSonar "
                     "stores its own probability for the same trade next to it (the EV-implied p of the token's "
                     "get_trade_candidates row) and scores both after 1 h, 4 h and 24 h from the minute data it keeps: "
                     "max gain, max loss, TP before SL (both in one minute = SL). get_hourly_brief.grok_predictions "
                     "shows the results and the calibration. Refused while the owner has the intake switched off "
                     "(flag grok_predictions); at most 120 an hour."),
     "inputSchema": {"type": "object", "properties": {
         "token": {"type": "string", "description": "Solana token mint address"},
         "ts": {"type": "integer", "description": "unix seconds of the prediction (default now)"},
         "mcap": {"type": "number", "description": "market cap in USD at ts"},
         "strategy": {"type": "string", "enum": ["momentum", "range", "call"]},
         "p_tp": _P01, "tp_pct": {"type": "number", "exclusiveMinimum": 0},
         "sl_pct": {"type": "number", "exclusiveMinimum": 0},
         **{f"p_up{lv}_{hz}": _P01 for hz in ("1h", "4h", "24h") for lv in (10, 20, 50)},
         "p_drop30_first": _P01,
         "verdict": {"type": "string", "enum": ["runner", "avoid", "neutral"]},
         "reasons": {"type": "string", "maxLength": 2000}},
         "required": ["token", "mcap", "strategy", "p_tp", "tp_pct", "sl_pct", "verdict"]}})


# 11.11. (Jure: "real-time zone alarm na Grok Bot", data flag zonewatch G21, zonewatch/): Grok arms zones; MemeSonar
# POSTs an alarm to the Grok Bot webhook when the market cap enters one
_MC = {"type": "number", "exclusiveMinimum": 0, "description": "market cap in USD"}
TOOLS += [
    {"name": "arm_zone",
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
     "description": ("Arm (or update, or disarm) one SHORT-LIVED price zone of a Solana token by hand, in MARKET CAP "
                     "USD: MemeSonar watches it and POSTs an alarm to the Grok Bot webhook the moment the market cap "
                     "crosses it (zone_enter / zone_exit for bottom, dca and custom; top_hit at >= lo of a top zone; "
                     "stop_hit at <= a stop). Upsert on (mint, zone_type, source). zone_type bottom | dca | top | stop "
                     "| custom; lo <= hi, both at least $30k; a stop may be given as lo only. ttl_h: hours it stays "
                     "armed (default 2, max 2); ttl_h=0 DISARMS the zone (lo / hi not needed). source manual (default) "
                     "| event (a zone tied to an event topic). Range zones (source range) are not armed here: they "
                     "come only from MemeSonar's range engine (recomputed about every 5 min) for tokens with an open "
                     "range round, an entry-ready range or an open position on the real account, while the engine has "
                     "an active range for them. At most 100 active armed zones and 60 arm_zone calls an hour per key. "
                     "The alarm JSON: id, event, mint, symbol, zone_type, zone_lo, zone_hi, mcap, price, liq, vol_5m, "
                     "vol_1h, buys_5m, sells_5m, buy_share_5m, buy_share_1h, uniq_traders_1h, rug_risk, source, ts, "
                     "and for a range zone what it is based on: zone_version (+1 per range computation), computed_ts "
                     "(when the range was computed), window_h (hours of data it spanned); null for a hand-armed zone. "
                     "Buys nothing."),
     "inputSchema": {"type": "object", "properties": {
         "mint": {"type": "string", "description": "Solana token mint address"},
         "zone_type": {"type": "string", "enum": ["bottom", "dca", "top", "stop", "custom"]},
         "lo": _MC, "hi": _MC,
         "note": {"type": "string", "maxLength": 300},
         "ttl_h": {"type": "number", "minimum": 0, "maximum": 2, "default": 2,
                   "description": "hours armed, at most 2; 0 disarms"},
         "source": {"type": "string", "enum": ["manual", "event"], "default": "manual"}},
         "required": ["mint", "zone_type"]}},
    {"name": "get_armed_zones", "annotations": _READ,
     "description": ("The zones MemeSonar watches now (hand-armed first, then the range engine's: bottom, dca, top, "
                     "stop in market cap USD), each with lo, hi, source (manual | event | range), note, armed_by, "
                     "expires_at, zone_version / computed_ts / window_h of a range zone's range (null for a hand-armed "
                     "one), state (inside | outside | unknown), mcap_now with its age, distance_pct to the zone (0 "
                     "inside) and zone_is (below / above the price), and the last alarm (event, ts, status). Also the "
                     "flag, whether the Grok Bot webhook is configured, the counts by source and the limits (ttl_h at "
                     "most 2). positions (without a source filter): the REAL account's open positions (manual, Grok "
                     "auto, approved; never the demo account) with lots, qty, avg_entry_price / avg_entry_mcap, "
                     "pnl_pct / pnl_usd / pnl_sol, sources and their OWN levels watched with or without a range (stop "
                     "/ trailing / take profit of the lots, Smart sell or an exit plan in force, DCA and buy orders): "
                     "level_price, level_mcap, distance_pct (negative = below the price), state and the last alarm; "
                     "these alarm as event position_level (sl_near within 3 % above a stop, sl_hit, tp_hit, dca_hit) "
                     "and a held token whose range rangedca switches off as range_off (reason_key break_up | "
                     "break_down | weak_volume | other). mint / source filter; limit 1-300 (default 100)."),
     "inputSchema": {"type": "object", "properties": {
         "mint": {"type": "string"}, "source": {"type": "string", "enum": ["manual", "event", "range"]},
         "limit": {"type": "integer", "minimum": 1, "maximum": 300, "default": 100}}}},
]
INSTRUCTIONS += (" Zone alarms: MemeSonar watches its range engine's zones (bottom, dca, top, stop; zone_version, "
                 "computed_ts and window_h in every alarm) and POSTs to your Grok Bot webhook when the price crosses "
                 "one; arm_zone(mint, zone_type, lo, hi, note, ttl_h) adds a market-cap zone by hand for at most 2 h "
                 "(ttl_h=0 disarms); get_armed_zones lists them with their state. The real account's open positions "
                 "alarm on their own SL / TP / trailing / DCA levels (event position_level) and when the range of a "
                 "held token is switched off (event range_off); advise from these, never trade on them alone.")
ZONE_TOOLS = ("arm_zone", "get_armed_zones")


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
            prop = {k: a.get(k) for k in assistnotes.PROPOSAL_KEYS if a.get(k) not in (None, "")}   # 11.11.: optional
            return assistnotes.submit_signal_opinion(tcon, kid, a.get("token"), a.get("verdict"), a.get("confidence"),
                                                     a.get("interpretation"), a.get("evidence"), proposal=prop or None)
        if name == "submit_suggestion":
            return assistnotes.submit_suggestion(tcon, kid, a.get("title"), a.get("interpretation"), a.get("improvement"),
                                                 a.get("evidence"), a.get("proposed_change"))
        return assistnotes.submit_daily_summary(tcon, kid, a.get("title"), a.get("interpretation"), a.get("evidence"))
    except ValueError as e:
        return {"error": str(e)}
    finally:
        tcon.close()


NOTE_TOOLS = ("submit_trade_review", "submit_signal_opinion", "submit_suggestion", "submit_daily_summary")
EVENT_TOOLS = ("submit_event_topic", "get_event_topics", "get_event_tokens")


def _event_tool(name, a, kid):
    """11.11. (flag event_tokens): the three event-topic tools (topics/view.py); the key's fingerprint is the
    client attribution of a submitted topic (event_topics.kid, topic_log)."""
    from topics import view
    try:
        if name == "submit_event_topic":
            return view.submit(a.get("name"), a.get("keywords"), a.get("event_ts"), a.get("buzz_score"), a.get("status"),
                               a.get("source"), a.get("note"), kid=f"mcp:{kid}")
        if name == "get_event_topics":
            return view.list_topics(a.get("status"), a.get("limit"))
        return view.tokens(a.get("topic_id"))
    except ValueError as e:
        return {"error": str(e)}


def _tool(name, args, kid="local"):
    """(result dict, is_error) of one tool call."""
    args = args if isinstance(args, dict) else {}
    if name in NOTE_TOOLS:
        d = _note_tool(name, args, kid)
        return d, "error" in d
    if name in ("submit_x_features", "get_x_features"):
        d = _xfeat_tool(name, args, kid)
        return d, "error" in d
    if name in ("get_trade_candidates", "get_grok_tasks"):   # 10.11. ui/kandidati.py, read-only
        from ui import kandidati
        d = (kandidati.candidates(args.get("min_sources"), args.get("limit")) if name == "get_trade_candidates"
             else kandidati.tasks(args.get("limit")))
        return d, "error" in d
    if name == "get_proposals":   # 11.11. proposals/ (flag proposals G21), read-only, cached
        from proposals import view as pview
        d = pview.mcp(args.get("since"), args.get("min_ev"), _truthy(args.get("include_blocked")), args.get("status"),
                      args.get("limit"))
        return d, "error" in d
    if name == "get_fast_checks":   # 11.11. fast/ (flag fast_path G24), read-only
        from fast import view as fview
        d = fview.mcp(args.get("since"), args.get("decision"), args.get("limit"))
        return d, "error" in d
    if name in ("get_trader_groups", "get_group_activity"):   # 10.11. group_discovery (kol/groupdisc.py)
        from kol import groupdisc
        d = groupdisc.mcp_tool(name, args)
        return d, "error" in d
    if name == "get_insider_candidates":   # 10.11. insider_copy (kol/precall.py)
        from kol import precall
        d = precall.mcp_tool(name, args)
        return d, "error" in d
    if name in ("get_pre_shill_wallets", "get_pre_shill_signals"):   # 11.11. pre_shill (kol/preshill.py)
        from kol import preshill
        d = preshill.mcp_tool(name, args)
        return d, "error" in d
    if name == "get_hourly_brief":   # 11.11. events/brief.py
        from events import brief
        d = brief.build(args.get("since"), args.get("limit_signals"), include_closed=args.get("include_closed") is True)
        return d, "error" in d
    if name == "submit_grok_prediction":   # 11.11. events/predictions.py
        from events import predictions
        try:
            d = predictions.submit(args, kid)
        except ValueError as e:
            d = {"error": str(e)}
        return d, "error" in d
    if name in EVENT_TOOLS:   # 11.11. topics/view.py (flag event_tokens)
        d = _event_tool(name, args, kid)
        return d, "error" in d
    if name in ZONE_TOOLS:   # 11.11. zonewatch/view.py (flag zonewatch); the key's fingerprint attributes the write
        from zonewatch import view as zview
        d = zview.mcp_tool(name, args, kid=f"mcp:{kid}")
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
            a.get("min_score"), source=a.get("source")),
    }
    if name in data_tools:
        d = data_tools[name](args)
        return d, isinstance(d, dict) and "error" in d
    if name == "get_market_signals":
        d = signals(source=args.get("source"), include_hidden=_truthy(args.get("include_hidden")))
        return d, "error" in d
    if name == "get_token_details":
        d = token(args.get("token_address") or args.get("address"))
        return d, "error" in d
    if name == "get_portfolio_status":
        return portfolio(), False
    if name == "execute_trade":
        code, d = trade_request({"token": args.get("token_address") or args.get("token"), "amount": args.get("amount"),
                                 "side": args.get("side"), "require_approval": args.get("require_approval", True),
                                 "reason": args.get("reason") or "", "p_tp": args.get("p_tp"),
                                 "strategy": args.get("strategy")})
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
