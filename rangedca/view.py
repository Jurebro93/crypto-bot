"""What the MCP API shows of range_dca (ui/mcpapi: get_range_candidates and the "range" part of get_token_details).
Read-only on range.db and league.db.

11.11. (market watchlist, rangedca/market.py): every row says which watchlist brought the token, source = signal |
event | market (several: the first of signal > event > market, all of them in `sources`), and paper_only (a market /
event token is traded only on the demo account); watched_by_source and the watchlist's filter and cost today."""
import sqlite3
import time

from . import data, gate, market, rules, trade

ZONE_KEYS = ("range_low_low", "range_low_top", "range_high_low", "range_high_top")
SOURCES = ("signal", "event", "market")   # priority order of the watchlist source


def source_of(srcs):
    """(source, sources): the first of signal > event > market, and all of them in that order."""
    s = [x for x in SOURCES if x in set(srcs or ())] or ["signal"]
    return s[0], s


def _round(x, nd=4):
    return round(x, nd) if isinstance(x, float) else x


def _zones(r):
    z = r.get("zones") or {}
    if not z:
        return None
    return {"price": {k: z.get(k) for k in ZONE_KEYS}, "market_cap_usd": z.get("mc"),
            "range_high": z.get("range_high"), "range_low": z.get("range_low")}


def _touches(r, supply):
    t = r.get("touches") or {}

    def rows(xs):
        return [{"ts": p["ts"], "price": p["px"], "market_cap_usd": round(p["px"] * supply) if supply else None} for p in xs or []]
    return {"top": rows(t.get("top")), "bottom": rows(t.get("bottom"))} if t else None


BREAKOUT = "breakout"


def is_breakout(r):
    """11.11. (Jure: X at 138 % of its range was still offered as a range entry): the price sits above the range's top
    (position in range > 100 %). detect.py calls a range broken only past range_high_top x 1.15, so such a range can
    still be "aktivan"; it is no range entry either way."""
    p = (r or {}).get("pos_pct")
    return p is not None and p > 100


def one(tok, r, now=None):
    """One range as the MCP API shows it. entry_ready: an entry would pass now (no breakout, entry_now passes);
    status "breakout" when the price is above 100 % of the range."""
    now = now or time.time()
    m = r.get("metrics") or {}
    st = r.get("state") or {}
    brk = is_breakout(r)
    why = None if brk else trade.entry_view(r, m.get("price"), now)
    src, srcs = source_of(r.get("sources") or [r.get("source") or "signal"])
    return {"token": tok, "symbol": r.get("symbol"), "source": src, "sources": srcs,
            "status": BREAKOUT if brk else r.get("status"),
            "range_status": r.get("status"), "entry_ready": not brk and why is None, "active": bool(r.get("active")),
            "why": r.get("why") or None, "computed_ts": r.get("ts"), "numbers_ts": r.get("mts"),
            "range_score": r.get("score"), "range_high_to_low": r.get("ratio"),
            "position_in_range_pct": r.get("pos_pct"), "zones": _zones(r), "touches": _touches(r, m.get("supply")),
            "recoveries": r.get("recoveries"),
            "components": {k: {kk: _round(vv) for kk, vv in v.items()} for k, v in (r.get("components") or {}).items()},
            "now": {"price_usd": m.get("price"), "market_cap_usd": m.get("mcap"), "liquidity_usd": m.get("liq"),
                    "volume_1h_usd": m.get("vol_h1"), "volume_15m_usd": m.get("vol_15m"),
                    "volume_ratio_15m_vs_1h_avg": _round(m.get("vol_ratio")), "change_5m": _round(m.get("ch_5m")),
                    "buy_share_5m": _round(m.get("buy_share_5m")), "buy_share_source": m.get("buy_share_how")},
            "signals": r.get("signals"),
            "excluded_until": st.get("excluded_until") if (st.get("excluded_until") or 0) > now else None,
            "excluded_why": st.get("excluded_why") if (st.get("excluded_until") or 0) > now else None,
            "entry_now": (f"probijen gore: cijena na {r.get('pos_pct'):.0f} % raspona, nije ulaz u raspon" if brk else
                          why or "ulaz bi prošao (uz provjeru ruga i limite)"),
            "paper_only": src != "signal"}


def positions(tokens=None):
    """Open range rounds (and the last closed ones) from league.db, read-only: [{account, token, lots, levels...}]."""
    con = data._league_ro()
    if con is None:
        return {"open": [], "closed": []}
    try:
        out = trade.view_rounds(con) if con.execute(
            "SELECT 1 FROM sqlite_master WHERE name='range_rounds'").fetchone() else {"open": [], "closed": []}
    except sqlite3.Error:
        out = {"open": [], "closed": []}
    finally:
        con.close()
    for r in out["open"]:
        lv = r.pop("levels", {}) or {}
        sup = lv.get("supply")
        r["exit_levels_market_cap_usd"] = {
            "take_half_at (range_high_low)": round(lv["rhl"] * sup) if sup and lv.get("rhl") else None,
            "rest_at (range_high_top)": round(lv["rht"] * sup) if sup and lv.get("rht") else None,
            "hard_stop (range_low_low x 0.85)": round(lv["stop_px"] * sup) if sup and lv.get("stop_px") else None}
        r["tighten_with"] = {"tool": "set_exit_plan", "plan.accounts": [r["user"]],
                             "note": "a plan only tightens: the range's own exits keep running next to it"}
    if tokens:
        out["open"] = [r for r in out["open"] if r["token"] in tokens]
        out["closed"] = [r for r in out["closed"] if r["token"] in tokens]
    return out


def _watched(since):
    """(total, {signal, market, event}) of the ranges computed since `since` (one COUNT, no JSON parsed)."""
    con = data.ro()
    if con is None:
        return 0, {}
    try:
        if data.has_src(con):
            by = {s or "signal": n for s, n in con.execute("SELECT src, COUNT(*) FROM ranges WHERE ts >= ? GROUP BY src",
                                                            (int(since),))}
        else:
            by = {"signal": con.execute("SELECT COUNT(*) FROM ranges WHERE ts >= ?", (int(since),)).fetchone()[0]}
        out = {}
        for s, n in by.items():
            out[s] = out.get(s, 0) + n
        return sum(out.values()), out
    except sqlite3.Error:
        return 0, {}
    finally:
        con.close()


def candidates(min_score=None, now=None, limit=50, source=None):
    """get_range_candidates: tokens with an active range (score >= min_score, default 0.7), entry-ready first, then
    the best score. source: signal | market | event keeps only the rows whose sources include it."""
    now = now or time.time()
    try:
        ms = float(min_score) if min_score is not None else rules.RULES["score_min"]
    except (TypeError, ValueError):
        return {"error": "min_score must be a number 0-1"}
    src = (str(source).strip().lower() or None) if source else None
    if src and src not in SOURCES:
        return {"error": f"source must be one of {', '.join(SOURCES)}"}
    since = now - trade.RANGE_FRESH_S
    rs = data.read_ranges(since=since, active_only=True)
    rows = [one(t, r, now) for t, r in rs.items() if r.get("active") and (r.get("score") or 0) >= ms - 1e-9]
    if src:
        rows = [x for x in rows if src in x["sources"]]
    rows.sort(key=lambda x: (not x["entry_ready"], -(x["range_score"] or 0)))
    brk = [x for x in rows if x["status"] == BREAKOUT]   # 11.11.: above the range: shown apart, never a range entry
    rows = [x for x in rows if x["status"] != BREAKOUT]
    total, by = _watched(since)
    mcounts, cost = market.info(now=now)
    from league import flags
    return {"ts": int(now), "flag_mode": flags.mode(trade.FLAG), "min_score": ms, "source": src,
            "candidates": rows[:limit], "entry_ready": sum(1 for x in rows if x["entry_ready"]),
            "breakouts": brk[:limit],
            "watched": total, "watched_by_source": {s: by.get(s, 0) for s in SOURCES},
            "watchlist": {"range_market_flag": flags.mode("range_market"), "event_tokens_flag": flags.mode("event_tokens"),
                          "market_max": market.MARKET_MAX, "signal_max": data.MAX_TOKENS,
                          "listed_now": {"market": mcounts.get("market", 0), "event": mcounts.get("event", 0)},
                          "market_filter": {"min_mcap_usd": market.MIN_MCAP, "max_mcap_usd": market.MAX_MCAP,
                                            "min_liquidity_usd": market.MIN_LIQ, "min_volume_1h_usd": market.MIN_VOL_H1,
                                            "min_age_h": market.MIN_AGE_H},
                          "refresh": f"top {market.HOT_N} every {market.HOT_EVERY_S // 60} min, the rest every "
                                     f"{market.COLD_EVERY_S // 60} min (DexScreener snapshots, free)",
                          "cost_today": cost,
                          "money": "market and event tokens: paper only (demo account, range_dca) while their flag is "
                                   "paper; never real money"},
            "positions": positions(),
            "paper_proof": {**gate.proof(), "live_gate": gate.refusal() or "prolazi (>= 20 rundi, EV > 0)"},
            "rules": ("lot 1 in the bottom 15 % of the range or inside the bottom zone, 5m change > -3 %, buys >= 50 % "
                      "of 5m transactions, 15m volume x4 >= 50 % of the 1h average, range_score >= 0.7; lot 2 at -10 to "
                      "-15 % from lot 1 above range_low_low x 0.92; half out at range_high_low, the rest at "
                      "range_high_top or a 10 % trailing stop above it; hard stop range_low_low x 0.85; after 6 h "
                      "without the top zone out at break-even; 20 min cooldown")}


def token(address, now=None):
    """The "range" part of get_token_details (None when the token is not watched)."""
    rs = data.read_ranges(tokens=[address])
    r = rs.get(address)
    if not r:
        return None
    out = one(address, r, now)
    out["positions"] = positions([address])
    return out

