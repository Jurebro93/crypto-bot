"""Shadow outcomes per source and the paper gate (10.11., spec item 4). Measures only: nothing here buys.

Entry: every candidate that passed all filters gets one shadow row per (token, source, stage) at the moment it was
found (source caller, wallet, scan or beta), at the DexScreener price of that pass.
Path: every scanner pass (~150 s) the open rows get the current DexScreener price (60 s cache), so the path has one
point every pass. Between two points a wick is not seen (kol/minute.py's one-minute candles cost GeckoTerminal calls
the CoinGecko budget cannot spare for every scanner token); max_gap_s records the longest hole, and a row whose path
has a hole over max_gap_min (30) is kept out of the counts (bad 'rupa'), as is a row without any price point.

The shadow trade (one rule for every source, so they compare):
    take profit +tp (20 %), stop -sl (30 %), whichever the path touches FIRST; neither within horizon_h (4 h): out at
    the first price at or after 4 h. Result after a round-trip cost (2 %, as get_caller_leaderboard): +18 % or -32 %
    or the 4 h change minus 2 %. A token that loses its price (no pair any more) before 4 h counts as the stop, unless
    the target came first (plan 2.6 survivor_fix: a call without a pair is a loss, it does not drop out).
Outcomes per row: hit1h / hit4h (+20 % reached within 1 h / 4 h, whatever came before), sl_first (the stop touched
before the target), result. EV of a source = mean result of its finished, tradeable rows.

Paper gate: a source may move to paper only with >= paper_min_outcomes (30) finished tradeable outcomes in the last
gate_days (30) and EV > 0 (paper_refusal). trade/settings.set_flag asks flag_paper_refusal before the flag
market_scan goes to paper; nothing ever moves it automatically.
"""
import statistics
import time

from scan import store


def enter(con, token, source, stage, tradeable, now, price, mcap=None, symbol=None):
    """A shadow entry (the first one per token, source and stage wins). False when there is no price."""
    if not price or price <= 0:
        return False
    cur = con.execute("INSERT OR IGNORE INTO shadow (token, source, stage, found_ts, tradeable, symbol, entry, mcap0, "
                      "hi, lo, last, last_ts, n_obs, hi1h, hi4h) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)",
                      (token, source, stage, int(now), int(bool(tradeable)), symbol, price, mcap, price, price, price,
                       int(now), price, price))
    return cur.rowcount > 0


COLS = ("token", "source", "stage", "found_ts", "tradeable", "entry", "hi", "lo", "last", "last_ts", "n_obs",
        "max_gap_s", "t_tp", "t_sl", "hi1h", "hi4h", "r4h", "result", "exit_why", "bad", "done")


def observe(row, price, now, cfg):
    """One price point on an open row (a dict with COLS): the path, the first touch of the target and of the stop,
    and the end once horizon_h has passed. Returns the updated dict. Pure."""
    r = dict(row)
    now = int(now)
    if r.get("done"):
        return r
    entry, age = r["entry"], now - r["found_ts"]
    horizon = float(cfg["horizon_h"]) * 3600
    tp, sl, cost = float(cfg["tp"]), float(cfg["sl"]), float(cfg["cost"])
    if price and price > 0:
        gap = now - (r.get("last_ts") or r["found_ts"])
        r["max_gap_s"] = max(int(r.get("max_gap_s") or 0), int(gap))
        r["n_obs"] = int(r.get("n_obs") or 0) + 1
        r["hi"], r["lo"] = max(r.get("hi") or price, price), min(r.get("lo") or price, price)
        if age <= 3600:
            r["hi1h"] = max(r.get("hi1h") or price, price)
        if age <= horizon:
            r["hi4h"] = max(r.get("hi4h") or price, price)
            if r.get("t_tp") is None and price >= entry * (1 + tp):
                r["t_tp"] = now
            if r.get("t_sl") is None and price <= entry * (1 - sl):
                r["t_sl"] = now
        r["last"], r["last_ts"] = price, now
        if age >= horizon:
            r["r4h"] = round(price / entry - 1, 4)
            _close(r, r["r4h"] - cost, "vrijeme", tp, sl, cost)
            if r["max_gap_s"] > float(cfg["max_gap_min"]) * 60:
                r["bad"] = "rupa"
    elif age >= horizon + 1800:   # no price since: the pair is gone; counted as the stop unless the target came first
        _close(r, -sl - cost, "nestao", tp, sl, cost)
    return r


def _close(r, timed, why, tp, sl, cost):
    t_tp, t_sl = r.get("t_tp"), r.get("t_sl")
    if t_tp is not None and (t_sl is None or t_tp <= t_sl):
        r["result"], r["exit_why"] = round(tp - cost, 4), "tp"
    elif t_sl is not None:
        r["result"], r["exit_why"] = round(-sl - cost, 4), "sl"
    else:
        r["result"], r["exit_why"] = round(timed, 4), why
    r["done"] = 1


def open_rows(con):
    return [dict(zip(COLS, row)) for row in con.execute(f"SELECT {', '.join(COLS)} FROM shadow WHERE done=0")]


def open_tokens(con):
    return {t for (t,) in con.execute("SELECT DISTINCT token FROM shadow WHERE done=0")}


def track(con, prices, now, cfg):
    """Apply this pass's prices ({token: price}) to every open row. Returns the number of rows finished."""
    n = 0
    for r in open_rows(con):
        new = observe(r, prices.get(r["token"]), now, cfg)
        if new == r:
            continue
        sets = {k: new.get(k) for k in COLS[5:] if new.get(k) != r.get(k)}
        if not sets:
            continue
        con.execute(f"UPDATE shadow SET {', '.join(f'{k}=?' for k in sets)} WHERE token=? AND source=? AND stage=?",
                    (*sets.values(), r["token"], r["source"], r["stage"]))
        n += int(bool(new.get("done")) and not r.get("done"))
    return n


def outcome(r, cfg):
    """(hit1h, hit4h, sl_first) of a finished row."""
    tp, e = float(cfg["tp"]), r["entry"]
    hit1h = bool(r.get("hi1h") and r["hi1h"] >= e * (1 + tp))
    hit4h = bool(r.get("hi4h") and r["hi4h"] >= e * (1 + tp))
    sl_first = r.get("t_sl") is not None and (r.get("t_tp") is None or r["t_sl"] < r["t_tp"])
    return hit1h, hit4h, sl_first


def stats(con, cfg, since, now=None, source=None, tradeable=True):
    """Per source: {"source", "found" (entries in the window), "n" (finished, counted outcomes), "hit1h", "hit4h",
    "sl_first" (shares), "ev" (mean result), "median"}. tradeable=True counts only rows that could ever be bought
    (bonded, 30k+); False only the measured-only ones (curve, under 30k); None both."""
    out = []
    sql = f"SELECT {', '.join(COLS)} FROM shadow WHERE found_ts >= ?"
    args = [int(since)]
    if source:
        sql += " AND source = ?"
        args.append(source)
    if tradeable is not None:
        sql += " AND tradeable = ?"
        args.append(int(bool(tradeable)))
    by = {}
    for row in con.execute(sql, args):
        r = dict(zip(COLS, row))
        by.setdefault(r["source"], []).append(r)
    for src in [s for s in store.SOURCES if s in by] + sorted(s for s in by if s not in store.SOURCES):
        rows = by[src]
        fin = [r for r in rows if r["done"] and not r["bad"] and r["result"] is not None]
        oc = [outcome(r, cfg) for r in fin]
        res = [r["result"] for r in fin]
        n = len(fin)
        out.append({"source": src, "found": len(rows), "n": n,
                    "hit1h": round(sum(o[0] for o in oc) / n, 3) if n else None,
                    "hit4h": round(sum(o[1] for o in oc) / n, 3) if n else None,
                    "sl_first": round(sum(o[2] for o in oc) / n, 3) if n else None,
                    "ev": round(sum(res) / n, 4) if n else None,
                    "median": round(statistics.median(res), 4) if n else None,
                    "open": sum(1 for r in rows if not r["done"])})
    return out


def paper_refusal(source, con=None, cfg=None, now=None):
    """None when `source` may move to paper, else the reason in Croatian: at least paper_min_outcomes finished
    tradeable shadow outcomes in the last gate_days and EV > 0. Never moves anything itself."""
    cfg = cfg or store.config()
    now = int(now or time.time())
    own = con is None
    if own:
        con = store.ro()
        if con is None:
            return "skener još nema nijedan ishod u sjeni (scan.db ne postoji)"
    try:
        st = stats(con, cfg, now - int(cfg["gate_days"]) * 86400, now, source=source)
    finally:
        if own:
            con.close()
    s = st[0] if st else {"n": 0, "ev": None}
    need = int(cfg["paper_min_outcomes"])
    if s["n"] < need:
        return f"izvor {source}: tek {s['n']} od {need} ishoda u sjeni (zadnjih {cfg['gate_days']} dana)"
    if s["ev"] is None or s["ev"] <= 0:
        return f"izvor {source}: EV sjene {s['ev'] * 100:+.1f} % po tradeu nije iznad nule ({s['n']} ishoda)"
    return None


GATED = ("scan", "beta")   # the sources the flag market_scan would put on paper; caller / wallet are the baseline


def paper_sources(con=None, cfg=None, now=None):
    """The sources of the flag that pass the gate (only these may ever run in paper)."""
    return [s for s in GATED if paper_refusal(s, con, cfg, now) is None]


def flag_paper_refusal(con=None, cfg=None, now=None):
    """None when the flag market_scan may go to paper (at least one of its sources passes the gate), else the
    reasons of both. trade/settings.paper_refusal calls this."""
    why = [paper_refusal(s, con, cfg, now) for s in GATED]
    if any(w is None for w in why):
        return None
    return "; ".join(why)


def report_data(now=None, con=None, cfg=None):
    """What the daily report and the MCP tool get_source_stats show: per source the last 24 h (found, outcomes,
    hit rates, -30 %-first, EV), the gate window, the paper gate per source, the measured-only line, beta by meta
    state, the lead time over callers and today's spend per paid source. None before scan.db exists."""
    from scan import meta
    cfg = cfg or store.config()
    now = int(now or time.time())
    own = con is None
    if own:
        con = store.ro()
        if con is None:
            return None
    try:
        day = stats(con, cfg, now - 86400, now)
        gate = stats(con, cfg, now - int(cfg["gate_days"]) * 86400, now)
        measured = stats(con, cfg, now - 86400, now, tradeable=False)
        gates = {s: paper_refusal(s, con, cfg, now) for s in store.SOURCES}
        leads = [r[0] for r in con.execute("SELECT lead_time_min FROM cand WHERE lead_time_min IS NOT NULL AND "
                                           "first_pass_ts >= ?", (now - 7 * 86400,))]
        passed_day = con.execute("SELECT COUNT(*) FROM cand WHERE first_pass_ts >= ?", (now - 86400,)).fetchone()[0]
        checked_day = con.execute("SELECT COUNT(*) FROM cand WHERE checked_ts >= ?", (now - 86400,)).fetchone()[0]
        beta = meta.report_rows(con, now - 7 * 86400)
        spend = {"helius_credits": store.spent(con, "helius", now), "gt_calls": store.spent(con, "gt", now),
                 "x_usd": round(store.spent(con, "xusd", now), 4)}
    finally:
        if own:
            con.close()
    return {"ts": now, "mode": store.mode(), "rule": {"tp": cfg["tp"], "sl": cfg["sl"], "horizon_h": cfg["horizon_h"],
                                                     "cost": cfg["cost"]},
            "day": day, "gate_window": gate, "gate_days": cfg["gate_days"], "measured_only_day": measured,
            "paper_gate": {s: (w or "prolazi") for s, w in gates.items()},
            "lead_time": {"n": len(leads), "median_min": round(statistics.median(leads), 1) if leads else None,
                          "share_before_callers": round(sum(1 for x in leads if x > 0) / len(leads), 3) if leads else None},
            "checked_24h": checked_day, "passed_24h": passed_day, "beta_by_meta_state": beta, "spend_today": spend,
            "caps": {"helius_credits": cfg["helius_credits_day"], "gt_calls": cfg["gt_calls_day"],
                     "x_usd": cfg["x_usd_day"]}}
