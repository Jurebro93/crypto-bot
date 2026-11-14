"""What the MCP API shows of range_dca (ui/mcpapi: get_range_candidates and the "range" part of get_token_details).
Read-only on range.db and league.db.

11.11. (market watchlist, rangedca/market.py): every row says which watchlist brought the token, source = signal |
event | market (several: the first of signal > event > market, all of them in `sources`), and paper_only (a market /
event token is traded only on the demo account); watched_by_source and the watchlist's filter and cost today.
11.11. (flag range_flip G26, detect.flip_step): while the flag is not off every row carries range_flip (status normal |
flip_candidate | flipped | paused | resumed, the break, the flip zone or the resistance, the retests, ATR, stop_kind,
the stop of today's rules and of the new ones, the range after the break, why the new rules take no entry) and
entry_ready_new_rules; the answer lists every token not in state normal under range_flip (a paused token is often not
active under today's rules, so it would not be in the candidates at all).
11.11. (Jure: HAOBIBI, rangedca/owner.py): owner_labels (the owner's learning labels, counterfactual: the booked round
never changes), the owner's pins (pinned true on the row, always listed whatever the score, pin_ready / pin_entry: the
pin's rule, lower zone + volume holds), similar_to per row (the most similar labelled win, 0-1) and meta similar (top
10).
11.11. (flag range_missed G27): source "missed" (signal > event > missed > market), and the answer's "missed" part
(missed_meta): the list, its filter, the rounds of source missed vs the others and the missed live gate.
14.11. (Jure: "pronađi tokene koji su izdržali bloodbath i vratili se u range ... barem 5 tradeova danas"; flag
range_demo G32): every row carries survivor (rangedca/survivor: ok, why, age, MC change 24 h, deepest fall, in range)
and, while range_demo is on, entry_ready_demo / entry_demo (the demo account's decision by rules.DEMO); the answer
has demo_today (the daily counter "range demo danas: N tradeova (cilj 5)" with the 3 reasons that held off the most
tokens), demo_rules, survivor_rule, and min_score defaults to DEMO's 0.6 while range_demo is on."""
import sqlite3
import time

from . import data, detect, gate, market, owner, rules, trade

ZONE_KEYS = ("range_low_low", "range_low_top", "range_high_low", "range_high_top")
SOURCES = market.SRC_ORDER   # priority order of the watchlist source: signal > event > missed (11.11.) > market


def source_of(srcs):
    """(source, sources): the first of signal > event > missed > market, and all of them in that order."""
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


def _pin_part(r, p, now):
    """The owner's pin on a row (rangedca/owner.pin_check): pinned, pin {...}, pin_ready, pin_entry."""
    if p is None:
        return {"pinned": False}
    ready, why, det = owner.pin_check(r, p, now)
    return {"pinned": True, "pin_ready": ready,
            "pin_entry": why or "preporuka po pinu bi prošla (uz tvrde blokade pravila B)",
            "pin": {"since": p.get("ts"), "who": p.get("who"), "note": p.get("note"), "ready": ready, "why_not": why,
                    "zones_from": det.get("zones_from"), "zones_market_cap_usd": det.get("zones_mc"),
                    "position_in_range_pct": det.get("position_in_range_pct"), "volume": det.get("volume"),
                    "notes": det.get("notes") or [], "rule": owner.PIN_RULE}}


def _fresh_part(r, now):
    """12.11. popodne (owner, točka 1): how old the row's numbers are against both limits (rangedca/trade): numbers_age_s,
    range_age_s, ready_limit_s (entry_ready), trade_limit_s (every automatic buy), trade_gate_fresh (the automatic
    buy's freshness passes now) and note (None while the numbers are at most METRICS_NOTE_S old)."""
    age = trade.numbers_age(r, now)
    hard = trade.stale_why(r, now)
    note = None
    if age > trade.METRICS_READY_S or now - (r.get("ts") or 0) > trade.RANGE_FRESH_S:
        note = trade.stale_why(r, now, trade.METRICS_READY_S)
    elif hard:
        note = (f"5-minutni podaci stari {age / 60:.1f} min: spremnost se procjenjuje po njima, automatski ulaz čeka "
                f"svježe (granica {trade.METRICS_FRESH_S / 60:g} min)")
    elif age > trade.METRICS_NOTE_S:
        note = f"5-minutni podaci kasne {age / 60:.1f} min (osvježavaju se svakog prolaza, ~1 min)"
    return {"numbers_age_s": age, "range_age_s": int(now - (r.get("ts") or 0)),
            "ready_limit_s": trade.METRICS_READY_S, "trade_limit_s": trade.METRICS_FRESH_S,
            "trade_gate_fresh": hard is None, "note": note}


def one(tok, r, now=None, pin=None, ws=None):
    """One range as the MCP API shows it. entry_ready: an entry would pass now (no breakout, entry_now passes, numbers
    within trade.METRICS_READY_S, not in the rug archive); status "breakout" when the price is above 100 % of the
    range. 12.11.: entry_now keeps the real reason and adds the staleness note (freshness: both limits, the ages).
    pin: the owner's pin of the token (pinned, pin, pin_ready, pin_entry); ws: the labelled wins (similar_to; the
    row's features under "_features" for the ranking, the caller pops them)."""
    now = now or time.time()
    m = r.get("metrics") or {}
    st = r.get("state") or {}
    brk = is_breakout(r)
    # 12.11. popodne (owner, točka 1): entry_ready under the readiness limit (trade.METRICS_READY_S, 9 min), so one
    # late cycle keeps the real rules deciding; the real reason first, the staleness added (never only "nisu svježi")
    why = None if brk else trade.entry_view(r, m.get("price"), now, trade.METRICS_READY_S)
    fresh = _fresh_part(r, now)
    arch = trade.archived_why(tok)   # 12.11. (owner, točka 4): a rug-archive token is never an entry, nor armed
    src, srcs = source_of(r.get("sources") or [r.get("source") or "signal"])
    pp = _pin_part(r, pin, now)
    if arch and pp.get("pinned"):
        pp = {**pp, "pin_ready": False, "pin_entry": arch}
    entry_now = (f"probijen gore: cijena na {r.get('pos_pct'):.0f} % raspona, nije ulaz u raspon" if brk else
                 why or "ulaz bi prošao (uz provjeru ruga i limite)")
    if fresh["note"] and fresh["note"] not in entry_now:
        entry_now += f" · {fresh['note']}"
    if arch:
        entry_now = f"{arch} · {entry_now}"
    zones = _zones(r)
    demo = {}
    if demo_on():   # 14.11. (range_demo): the demo account's own decision on this range (rules.DEMO)
        dwhy = None if brk else trade.entry_view(r, m.get("price"), now, trade.METRICS_READY_S, cfg=rules.DEMO)
        if arch:
            dwhy = arch
        demo = {"entry_ready_demo": not brk and dwhy is None,
                "entry_demo": ("probijen gore: nije ulaz u raspon" if brk else dwhy or
                               "demo ulaz bi prošao (uz provjeru ruga i limite)")}
    if pp.get("pinned") and pp["pin"]["zones_from"] == "pin":   # no pair of zones now: the pinned ones (in MC)
        zones = {"price": None, "market_cap_usd": pp["pin"]["zones_market_cap_usd"], "from": "pin"}
    sim = {}
    if ws is not None:
        f = owner.features(r)
        s = owner.similar_to(tok, f, ws)
        sim = {"similar_to": {"token": s["token"], "symbol": s["symbol"], "score": s["score"]} if s else None,
               "_features": f}
    return {"token": tok, "symbol": r.get("symbol"), "source": src, "sources": srcs, **pp, **sim,
            "status": BREAKOUT if brk else r.get("status"),
            "range_status": r.get("status"), "entry_ready": not brk and why is None and not arch,
            "active": bool(r.get("active")),
            "why": r.get("why") or None, "computed_ts": r.get("ts"), "numbers_ts": r.get("mts"),
            "freshness": fresh, "rug_archive": arch,
            "range_score": r.get("score"), "range_high_to_low": r.get("ratio"),
            "position_in_range_pct": r.get("pos_pct"), "zones": zones, "touches": _touches(r, m.get("supply")),
            "recoveries": r.get("recoveries"),
            "components": {k: {kk: _round(vv) for kk, vv in v.items()} for k, v in (r.get("components") or {}).items()},
            "now": {"price_usd": m.get("price"), "market_cap_usd": m.get("mcap"), "liquidity_usd": m.get("liq"),
                    "volume_1h_usd": m.get("vol_h1"), "volume_15m_usd": m.get("vol_15m"),
                    "volume_ratio_15m_vs_1h_avg": _round(m.get("vol_ratio")), "change_5m": _round(m.get("ch_5m")),
                    "buy_share_5m": _round(m.get("buy_share_5m")), "buy_share_source": m.get("buy_share_how")},
            "signals": r.get("signals"),
            "excluded_until": st.get("excluded_until") if (st.get("excluded_until") or 0) > now else None,
            "excluded_why": st.get("excluded_why") if (st.get("excluded_until") or 0) > now else None,
            "entry_now": entry_now,
            "paper_only": src != "signal" and not (src == "missed" and trade.missed_live(now)),
            "survivor": r.get("survivor"), **demo,
            "stop": stop_view(r), **_flip_part(r, m, now)}


def demo_on():
    """14.11.: the flag range_demo (G32) is paper (or live, which is paper for it)."""
    try:
        from league import flags
        return flags.mode(trade.DEMO_FLAG) in ("paper", "live")
    except Exception:  # noqa: BLE001
        return False


def demo_today(now=None):
    """14.11.: the daily counter of the demo account's range trades (rangedca/trade.demo_today), read-only."""
    con = data._league_ro()
    if con is None:
        return None
    try:
        return trade.demo_today(con, now)
    except sqlite3.Error:
        return None
    finally:
        con.close()


DEMO_RULES = ("14.11. (flag range_demo G32, demo account only, never real money): lot 1 when range_score >= 0.6, the "
              "price in the bottom 25 % of the range or inside the bottom zone, 5m change > -5 %, buys >= 45 % of 5m, "
              "15m volume x4 >= 35 % of the 1h average, never a token whose MC fell more than 45 % in 24 h "
              "(survivor.crashed); crash survivors (survivor.ok) are tried first; half out at +10 % net of the "
              "round-trip cost, the rest at +15 % net or the top zone when higher, a 15 % trailing or break-even once "
              "TP1 sold; stop: the ATR stop held between -12 % and -25 % from the entry; no lot 2; 6 h without TP1: "
              "out at break-even; 20 min cooldown")
SURVIVOR_RULE = ("survived the crash = >= 24 h old (pool creation; else 22 h+ of its own series), MC now at most 45 % "
                 "under the level 24 h ago (DexScreener's 24 h change, else the series' close 24 h ago), and back in an "
                 "active range (status aktivan, not paused / a flip candidate under range_flip)")


def stop_view(r):
    """11.11. (the owner's decision 1): the hard stop every account trades on this range (the ATR stop; x 0.85 while
    ATR is unknown), its ATR and today's old x 0.85, in market cap; None without zones or supply."""
    sp = rules.stop_parts(r)
    sup = ((r or {}).get("metrics") or {}).get("supply")
    if not sp or not sup:
        return None

    def mc(px):
        return round(px * sup) if px else None
    return {"market_cap_usd": mc(sp["stop_px"]), "kind": sp["kind"], "atr_market_cap_usd": mc(sp["atr_px"]),
            "old_x085_market_cap_usd": mc(sp["old_px"]),
            "rule": ("range_low_low - 1.5 x ATR (14 x 15 min), 5-20 % under it; every account; the demo account also "
                     "reclaims (30 min, back above range_low, buys >= 60 %)") if sp["kind"] == "atr" else
                    "range_low_low x 0.85 while ATR is unknown"}


def flip_view(fl, rng=None):
    """The range_flip block of a range (detect.flip_public) as the MCP API shows it, None without one."""
    if not fl:
        return None
    m = (rng or {}).get("metrics") or {}
    sup = m.get("supply")
    z = (rng or {}).get("zones") or {}
    old_stop = z["range_low_low"] * rules.RULES["stop_x"] if z.get("range_low_low") else None
    s = fl.get("state")
    zone = fl.get("zone") or {}
    zmc = {"low": zone.get("mc_low"), "top": zone.get("mc_top")} if zone else None
    brk = fl.get("brk") or {}
    alt = fl.get("alt") or {}
    return {"status": s, "since": fl.get("since"), "version": fl.get("v"), "changes": fl.get("ver"),
            "why": fl.get("why") or None, "entry_block": fl.get("block"),
            "break": ({"direction": brk.get("dir"), "ts": brk.get("ts"), "close_price": brk.get("close"),
                       "close_market_cap_usd": round(brk["close"] * sup) if sup and brk.get("close") else None,
                       "volume_x_median": brk.get("vol_x")} if brk else None),
            "flip_zone_market_cap_usd": zmc if s in ("flip_candidate", "flipped") else None,
            "resistance_market_cap_usd": zmc if s in ("paused", "resumed") else None,
            "retests": len(fl.get("touches") or []),
            "atr": {"price": fl.get("atr"), "pct_of_price": fl.get("atr_pct"), "market_cap_usd": fl.get("atr_mc"),
                    "bars": "14 x 15 min"} if fl.get("atr") else None,
            "stop_kind": fl.get("stop_kind"),
            "stop_new_rules": {"price": fl.get("stop_px"), "market_cap_usd": fl.get("stop_mc")} if fl.get("stop_px") else None,
            "stop_today": {"price": old_stop, "market_cap_usd": round(old_stop * sup) if sup and old_stop else None,
                           "rule": "range_low_low x 0.85"} if old_stop else None,
            "range_after_break": ({"status": alt.get("status"), "active": alt.get("active"), "score": alt.get("score"),
                                   "zones_market_cap_usd": (alt.get("zones") or {}).get("mc")} if alt else None),
            "last_unconfirmed_break": ({"direction": fl["seen"].get("dir"), "ts": fl["seen"].get("ts"),
                                        "volume_x_median": fl["seen"].get("vol_x")} if fl.get("seen") else None)}


FLIP_RULES = ("range_flip (G26): a 5-minute close beyond the range by max(2 %, 1 x ATR) with volume >= 1.5 x the "
              "median 5-minute volume is a confirmed break. Up: the old top zone is the candidate for the new bottom, "
              "no entries until 2 retests (swing lows within it +-3 %) without a close under it x 0.97 (then the range "
              "after the break trades); without them within 5 h of the break it is no flip (back to normal). Down: "
              "paused, no lot 1 / lot 2, the old bottom zone is the resistance; resumed when a range formed after the "
              "break has its top <= the resistance x 1.03, or back to normal when a 5-minute close is above the "
              "resistance by the break margin with volume >= 1.5 x the median. A state ends 24 h after its break. "
              "Stop: range_low_low - 1.5 x ATR(14 x 15 min), 5-20 % under range_low_low (11.11., the owner's "
              "decision 1: every account's stop now, range_flip or not; x 0.85 only while ATR is unknown).")


def _flip_tokens(since, limit=50):
    """Every token whose range_flip state is not normal (range.db range_flip), newest change first."""
    fr = data.flip_rows(since=since, states=[s for s in detect.FLIP_STATES if s != "normal"])
    if not fr:
        return []
    rr = data.read_ranges(since=since, tokens=sorted(fr))
    out = []
    for t, s in sorted(fr.items(), key=lambda kv: -(kv[1].get("since") or 0))[:limit]:
        r = rr.get(t) or {}
        sup = (r.get("metrics") or {}).get("supply")
        out.append({"token": t, "symbol": r.get("symbol"), **flip_view(detect.flip_public(s, sup), r)})
    return out


def _flip_part(r, m, now):
    """range_flip in a row (only while the flag is not off and the range carries the state)."""
    from league import flags
    fl = r.get("flip")
    if not fl or flags.mode(trade.FLIP_FLAG) == "off":
        return {}
    nr = rules.new_range(r)
    why = trade.entry_view(nr, m.get("price"), now, trade.METRICS_READY_S)   # 12.11.: the readiness limit, as one()
    return {"range_flip": flip_view(fl, r), "flip_status": fl.get("state"),
            "entry_ready_new_rules": why is None and not is_breakout(nr), "entry_new_rules": why or "ulaz bi prošao"}


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
        # 11.11. (range_flip; decision 1: every round): the round's hard stop is in that field whatever its kind
        # (stop_kind: atr = range_low_low - 1.5 x ATR, reclaim = under the new low by the ATR rule)
        r["exit_levels_market_cap_usd"]["hard_stop"] = r["exit_levels_market_cap_usd"]["hard_stop (range_low_low x 0.85)"]
        if lv.get("profile") == "demo" and sup:   # 14.11. (range_demo): the demo round's own take-profit prices
            r["exit_levels_market_cap_usd"].update({
                "take_half_at (+10 % net)": round(lv["tp1_px"] * sup) if lv.get("tp1_px") else None,
                "rest_at (+15 % net or the top zone)": round(rules.tp2_of(lv) * sup) if lv.get("tp2_px") else None,
                "stop_clamp (-25 % .. -12 % from the entry)": [round(x * sup) for x in lv.get("stop_clamp") or []]})
        r["profile"] = lv.get("profile") or "rules"
        r["rules"] = "range_flip" if lv.get("rules") == "flip" else "today"
        r["stop_kind"] = lv.get("stop_kind") or "range_low_low x 0.85"
        r["reclaim"] = bool(lv.get("reclaim"))
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
    don = demo_on()
    try:   # 14.11.: while range_demo is on, the default threshold is the demo profile's (0.6)
        ms = float(min_score) if min_score is not None else (rules.DEMO if don else rules.RULES)["score_min"]
    except (TypeError, ValueError):
        return {"error": "min_score must be a number 0-1"}
    src = (str(source).strip().lower() or None) if source else None
    if src and src not in SOURCES:
        return {"error": f"source must be one of {', '.join(SOURCES)}"}
    since = now - trade.RANGE_FRESH_S
    rs = data.read_ranges(since=since, active_only=True)
    pins = owner.pins()
    labels = owner.labels()
    ws = owner.wins(lbs=labels)
    rows = [one(t, r, now, pins.get(t), ws) for t, r in rs.items()
            if r.get("active") and (r.get("score") or 0) >= ms - 1e-9]
    if src:
        rows = [x for x in rows if src in x["sources"]]
    # 11.11. (owner's pins): a pinned token is always listed, whatever its score or status (it is a signal-pass token)
    have = {x["token"] for x in rows}
    rest = [t for t in pins if t not in have] if src in (None, "signal") else []
    if rest:
        pr = data.read_ranges(since=now - 3 * 3600, tokens=rest)
        for t in rest:
            r = pr.get(t)
            rows.append(one(t, r, now, pins[t], ws) if r else _pin_only(t, pins[t], now))
    rows.sort(key=lambda x: (not (x["entry_ready"] or x.get("pin_ready") or x.get("entry_ready_demo")),
                             not x.get("pinned"), not (x.get("survivor") or {}).get("ok"), -(x.get("range_score") or 0)))
    brk = [x for x in rows if x["status"] == BREAKOUT]   # 11.11.: above the range: shown apart, never a range entry
    rows = [x for x in rows if x["status"] != BREAKOUT]
    feats = [{"token": x["token"], "symbol": x.get("symbol"), "features": x.pop("_features")}
             for x in rows + brk if "_features" in x]
    total, by = _watched(since)
    mcounts, cost = market.info(now=now)
    from league import flags
    mflip = flags.mode(trade.FLIP_FLAG)
    flip = {"flag_mode": mflip, "tokens": _flip_tokens(since, limit), "rules": FLIP_RULES} if mflip != "off" else None
    return {"ts": int(now), "flag_mode": flags.mode(trade.FLAG), "min_score": ms, "source": src,
            "candidates": rows[:limit], "entry_ready": sum(1 for x in rows if x["entry_ready"]),
            "breakouts": brk[:limit], "range_flip": flip,
            "demo": {"flag_mode": flags.mode(trade.DEMO_FLAG), "today": demo_today(now) if don else None,
                     "entry_ready_demo": sum(1 for x in rows if x.get("entry_ready_demo")),
                     "survivors_in_range": sum(1 for x in rows if (x.get("survivor") or {}).get("ok")),
                     "rules": DEMO_RULES, "survivor_rule": SURVIVOR_RULE},
            "owner_labels": [owner.label_view(lb) for lb in labels],
            "pins": [{"token": t, "symbol": p.get("symbol"), "since": p.get("ts"), "who": p.get("who"),
                      "note": p.get("note"), "zones_market_cap_usd": p.get("zones_mc"),
                      "pin_ready": bool(next((x.get("pin_ready") for x in rows + brk if x["token"] == t), False))}
                     for t, p in pins.items()],
            "pin_rule": owner.PIN_RULE,
            "pin_remove": "only the owner: POST /pravi-trade/rangepin with token=<mint> and action=remove (or add)",
            "similar": owner.ranking(feats, ws),
            "similar_rule": ("features at entry time (ratio, range_score, position in range, volume 1 h / liquidity, "
                             "liquidity, market cap, age up to 24 h, bottom touches, buys share 5 min, holders / top 10 "
                             "when known), each scaled by a fixed typical spread (log10 for sizes and touches); similarity = "
                             "exp(-mean(z^2) / 2), 0-1, against the owner's labelled wins (never the token itself); "
                             f">= {owner.SIM_BONUS_MIN}: a P bonus of +{owner.SIM_P_BONUS} for range proposals ONLY IN "
                             "SHADOW (recorded as similar_shadow, P and EV unchanged)"),
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
            "missed": missed_meta(now),
            "rules": ("lot 1 in the bottom 15 % of the range or inside the bottom zone, 5m change > -3 %, buys >= 45 % "
                      "of 5m transactions, 15m volume x4 >= 50 % of the 1h average, range_score >= 0.7; lot 2 at -10 to "
                      "-15 % from lot 1 above range_low_low x 0.92; half out at range_high_low, the rest at "
                      "range_high_top or a 10 % trailing stop above it; hard stop (11.11., the owner's decision 1, "
                      "every account) range_low_low - 1.5 x ATR(14 x 15 min), 5-20 % under it (x 0.85 while ATR is "
                      "unknown; row stop); the demo account also reclaims: within 30 min of a stop-out, back above "
                      "range_low with buys >= 60 % of 5 min, a new lot 1 with its stop under the new low by the ATR "
                      "rule (the real account only past >= 7 nights of the stop comparison and >= 20 reclaim rounds "
                      "with EV > 0); after 6 h without the top zone out at break-even; 20 min cooldown")}


def _pin_only(tok, p, now):
    """The row of a pinned token without a computed range (not polled yet, cold or stale)."""
    pp = _pin_part(None, p, now)
    return {"token": tok, "symbol": p.get("symbol"), "source": "signal", "sources": ["signal"],
            "status": "nema svježeg raspona", "range_status": None, "entry_ready": False, "active": False,
            "why": "run_range ga prati od sljedećeg prolaza (ili je ispod 30k / još na krivulji)", "range_score": None,
            "position_in_range_pct": None, "zones": {"price": None, "market_cap_usd": p.get("zones_mc"), "from": "pin"},
            "now": {}, "entry_now": pp.get("pin_entry"), "paper_only": False, **pp}


def missed_meta(now=None):
    """11.11. (flag range_missed G27, rangedca/missed.py): the missed list (tokens skipped, then >= +20 % within
    60 min) and the paper rounds of source missed vs the other sources, with the missed live gate."""
    from . import missed
    now = now or time.time()
    from league import flags
    con = data.ro()
    try:
        lst = missed.info(con, now) if con is not None else {}
    except sqlite3.Error:
        lst = {}
    finally:
        if con is not None:
            con.close()
    try:
        rounds, live = gate.by_source(), gate.missed_refusal() or \
            f"prolazi (>= {gate.MIN_ROUNDS} rundi izvora missed, EV > 0)"
    except Exception as e:  # noqa: BLE001 - the proof unreadable: said so, the answer still comes
        rounds, live = None, f"dokaz nije čitljiv ({type(e).__name__}): pravi račun ne kupuje propuštene"
    return {"flag_mode": flags.mode(missed.FLAG), "list": lst, "ttl_h": missed.TTL_S // 3600,
            "label": f"preskočen, pa >= +{missed.MIN_PCT:g} % u 60 min (preskoceni, brzi put, prijedlozi)",
            # 12.11. (Jure, točka 4): the rule; list.unreliable says how many it left out
            "unreliable_rule": f"{missed.UNRELIABLE} = {missed.WHY} u 60 min nakon preskoka: nije propušteno, nije na "
                               "listi, ni u rundama izvora missed, ni u live vratima",
            "filter": {"min_mcap_usd": market.MIN_ANALYSED, "min_liquidity_usd": market.MISSED_MIN_LIQ,
                       "min_volume_1h_usd": market.MISSED_MIN_VOL_H1,
                       "hard_blocks": "rug (11.11. pravilo), rug arhiva, honeypot / freeze / mint, visok rug rizik, "
                                      "dev / top holderi prodaju"},
            "entry": "samo raspon iz rangedca/detect (computed_ts), nikad cijena preskoka",
            "rounds_by_source": rounds, "live_gate": live}


def token(address, now=None):
    """The "range" part of get_token_details (None when the token is not watched)."""
    rs = data.read_ranges(tokens=[address])
    r = rs.get(address)
    if not r:
        return None
    out = one(address, r, now, owner.pins().get(address), owner.wins())
    out.pop("_features", None)
    out["positions"] = positions([address])
    out["owner_labels"] = [owner.label_view(lb) for lb in owner.labels(token=address)]
    return out

