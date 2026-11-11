"""Stop variants of range_dca, measured, never traded (11.11., Jure: "HAOBIBI je bio jako dobar ulaz ... trade je samo
trebalo malo držati"; the owner decides from these numbers, the live / paper stop rule does not change here).

The variants (backtest.simulate over the same detection timeline, OHLC ticks: the live exit loop sees every second, so
a wick is a tick; a stop / trailing exit a tick passes through fills at its level, one that gapped past it at the tick):
    a   today: hard stop range_low_low x 0.85 on any tick
    b   range_flip's volatility stop (rules.new_range "atr": range_low_low - 1.5 x ATR(14 x 15 min), 5-20 % under it)
        on any tick
    c   the x 0.85 level, but only a 5-minute CLOSE under it sells (a wick does not); the "range broken downward" give-up
        (rules.exclusions: under range_low_low x 0.92 twice in 24 h) the same way, on a 5-minute close under the floor
    d   (b)'s level on a 5-minute close, as (c)
    e   (a) + reclaim: after the hard stop (or that give-up), when within 30 min a minute closes above range_low (the
        bottom zone's average) and above the stop with buys >= 60 % of 5 minutes, a new lot 1 with the stopped round's
        TP and stop (one reclaim per stopped round)
    be  (b) + reclaim
At the live threshold (score 0.7, lot 2, the volume proxy of the buys share where the candles have no counts), every
round priced again at the owner's round-trip cost (backtest.priced). A FALSE ENTRY is a closed round that ended at the
hard stop without the first take profit (backtest.false_entry). Max drawdown: the deepest fall of the summed PnL in exit
order; mae: the worst mark-to-market of one round's lots before cost.

replay_live() replays one LIVE round with its own fills (lots at the logged market caps, levels as they were live) on
GeckoTerminal minute candles: the HAOBIBI round of 11.11. (HAOBIBI_LIVE). GeckoTerminal's own low in the stop minute
was 88,865, the live feed printed 88,120 (the stop): that print is added to the minute as its low ("inject"), so every
variant sees the tick that stopped the live round.
"""
import time

from . import backtest, detect, rules

VARIANTS = {
    "a": {"new": None, "stop_on": "tick", "reclaim": False, "hr": "danas: range_low_low × 0,85 na svaki tick"},
    "b": {"new": ("atr",), "stop_on": "tick", "reclaim": False, "hr": "ATR stop (range_low_low − 1,5 × ATR, 5–20 %) na tick"},
    "c": {"new": None, "stop_on": "close5", "reclaim": False, "hr": "× 0,85 tek na 5-min zatvaranju ispod"},
    "d": {"new": ("atr",), "stop_on": "close5", "reclaim": False, "hr": "ATR stop tek na 5-min zatvaranju ispod"},
    "e": {"new": None, "stop_on": "tick", "reclaim": True, "hr": "(a) + reclaim (30 min, iznad range_low, kupnje ≥ 60 %)"},
    "be": {"new": ("atr",), "stop_on": "tick", "reclaim": True, "hr": "(b) + reclaim"},
}


def run(candles, supply, tl, key, liq=None, score_min=0.7):
    """The rounds of one variant (backtest.simulate, ticks "wick"), each with "pnl_c" (backtest.priced)."""
    v = VARIANTS[key]
    rs = backtest.simulate(candles, supply, tl, score_min, True, liq, new=v["new"], ticks="wick",
                           stop_on=v["stop_on"], reclaim=v["reclaim"])
    for r in rs:
        r["pnl_c"] = backtest.priced(r, liq)[0]
    return rs


def summary(rounds):
    """backtest.flip_summary plus reclaim rounds (n, PnL), give-ups and the worst mae (%)."""
    out = backtest.flip_summary(rounds)
    closed = [r for r in rounds if r.get("closed")]
    rec = [r for r in closed if r.get("reclaim")]
    out["reclaims"] = len(rec)
    out["reclaim_pnl_usd"] = round(sum(r["pnl_c"] for r in rec), 3)
    out["give_ups"] = sum(1 for r in closed if r["reason"] == "odustajanje")
    maes = [r["mae"] for r in rounds if r.get("mae") is not None]
    out["worst_mae_pct"] = round(min(maes) * 100, 1) if maes else None
    return out


class StopCompare:
    """Collects every variant per token (backtest.run_tokens), report() sums them."""

    def __init__(self, score_min=0.7):
        self.score_min, self.tokens, self.rounds = score_min, {}, {k: [] for k in VARIANTS}

    def add(self, tok, sym, candles, supply, liq, tl):
        per = {"symbol": sym, **backtest.data_span(candles)}
        for k in VARIANTS:
            rs = run(candles, supply, tl, k, liq, self.score_min)
            for r in rs:
                r["token"], r["symbol"] = tok, sym
            self.rounds[k] += rs
            per[k] = summary(rs)
            per[f"rounds_{k}"] = [{"opened": r["opened"], "closed": r["closed"], "reason": r["reason"],
                                   "entry_mc": r["entry_mc"], "lot2_mc": r.get("lot2_mc"), "lots": r["lots"],
                                   "pnl_usd": round(r["pnl_c"], 3), "mae_pct": round((r.get("mae") or 0) * 100, 1),
                                   "reclaim": bool(r.get("reclaim")), "false_entry": backtest.false_entry(r),
                                   "stop_mc": round(r["stop_px"] * supply) if r.get("stop_px") and supply else None}
                                  for r in rs]
        self.tokens[tok] = per

    def report(self):
        hours = sorted(p["hours"] for p in self.tokens.values())
        v = {k: summary(rs) for k, rs in self.rounds.items()}
        a = v["a"]
        return {"variants": v, "tokens": self.tokens, "score_min": self.score_min, "lot_usd": backtest.LOT_USD,
                "rules": {k: x["hr"] for k, x in VARIANTS.items()}, "ticks": "OHLC (open, low/high, close)",
                "data": {"tokens": len(hours), "days_total": round(sum(hours) / 24, 2)},
                "vs_a": {k: {"pnl_usd": round(x["pnl_usd"] - a["pnl_usd"], 3),
                             "dd_usd": round(x["max_dd_usd"] - a["max_dd_usd"], 3),
                             "false_entries": x["false_entries"] - a["false_entries"]} for k, x in v.items()}}


def _s(x):
    return (f"runde {x['rounds']}, PnL {x['pnl_usd']:+.2f} $ ({x['pnl_sol']:+.3f} SOL), DD {x['max_dd_usd']:.2f} $, "
            f"lažni ulazi {x['false_entries']}" + (f", reclaim {x['reclaims']} ({x['reclaim_pnl_usd']:+.2f} $)"
                                                    if x.get("reclaims") else ""))


def line(sr, focus=()):
    """The log line "range stop varijante: ..." (focus: tokens named apart, e.g. the owner's labelled wins)."""
    v = sr["variants"]
    out = (f"range stop varijante: {sr['data']['tokens']} tokena, {sr['data']['days_total']} dana; "
           + "; ".join(f"{k} ({VARIANTS[k]['hr']}): {_s(v[k])}" for k in VARIANTS))
    for tok in focus:
        p = sr["tokens"].get(tok)
        if p:
            out += (f"; {p['symbol'] or tok[:6]}: " + ", ".join(f"{k} {p[k]['pnl_usd']:+.2f} $" for k in VARIANTS))
    return out + "; pravilo uživo se ne mijenja (odluka vlasnika)"


def md(sr):
    """The markdown section (per token and in total)."""
    lines = ["", "## Stop varijante (mjereno, pravilo uživo se ne mijenja)", "",
             f"Prag ocjene {sr['score_min']}, lot 2, lot ${sr['lot_usd']:.0f}, tickovi {sr['ticks']}, trošak kao gore. "
             "Lažni ulaz = runda završena tvrdim stopom bez prvog TP-a; MAE = najgori trenutni gubitak runde.", ""]
    lines += [f"- {k}: {VARIANTS[k]['hr']}" for k in VARIANTS]
    lines += ["", "| token | varijanta | runde | PnL $ | PnL SOL | max DD $ | lažni ulazi | stopovi | odustajanja | "
              "reclaim | najgori MAE % |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    rows = [(p["symbol"] or t[:6], p) for t, p in sr["tokens"].items()] + [("UKUPNO", sr["variants"])]
    for name, p in rows:
        for k in VARIANTS:
            x = p[k]
            lines.append(f"| {name} | {k} | {x['rounds']} | {x['pnl_usd']:+.2f} | {x['pnl_sol']:+.4f} | "
                         f"{x['max_dd_usd']:.2f} | {x['false_entries']} | {x['stops']} | {x['give_ups']} | "
                         f"{x['reclaims']} | {x['worst_mae_pct'] if x['worst_mae_pct'] is not None else '-'} |")
    return "\n".join(lines) + "\n"


# ---------- one live round, replayed with its own fills -------------------------------------------------------------
HAOBIBI = "8tbfkL8LZYUN3ygzWMKfffqVd7tLRpWkuh2fowsepump"
_T = 1794390600   # 2026-11-11 09:50 UTC (10:50 CET), lot 1
HAOBIBI_LIVE = {
    "token": HAOBIBI, "symbol": "HAOBIBI", "account": "autopilot-paper",
    # the Render log (CET): lot 1 0.15 SOL at MC 112,828 10:50, lot 2 at 96,210 11:39, hard stop 88,120 11:44
    "lots": [{"ts": _T, "mc": 112_828, "sol": 0.15}, {"ts": _T + 49 * 60, "mc": 96_210, "sol": 0.15}],
    "stop_mc": 88_120, "stop_ts": _T + 54 * 60,
    # the stop is range_low_low x 0.85 of the range in force (it had tightened from 102,894 x 0.85)
    "rll_mc": round(88_120 / 0.85, 1), "rhl_mc": 172_300, "rht_mc": 183_000,   # rhl = the proposal's TP (#2)
    "booked_usd": -4.26, "sol_usd": 83.83, "liq": 32_000.0,
    "inject": [(_T + 54 * 60, 88_120)],   # the live feed's print in the stop minute (GeckoTerminal's low: 88,865)
}


def _mc_candles(candles, supply, inject=()):
    out = [[c[0], c[1] * supply, c[2] * supply, c[3] * supply, c[4] * supply, c[5]] + list(c[6:8]) for c in candles]
    for ts, mc in inject:
        m = ts - ts % 60
        for c in out:
            if c[0] == m:
                c[3] = min(c[3], mc)
    return out


def _range_low_at(candles, supply, t):
    """range_low (the bottom zone's average, MC) of the range detected on the candles at t (None without one)."""
    r = detect.analyze([c for c in candles if c[0] <= t], t, None, {"supply": supply, "unknown_liq_ok": True})
    z = r.get("zones") or {}
    return round(z["range_low"] * supply) if z.get("range_low") else None


def replay_live(candles, supply, live, key, until=None):
    """One live round (live: HAOBIBI_LIVE's shape) replayed under variant `key` on minute candles (price units,
    detect's candle tuples). Lots at their logged market caps (the variants change nothing before the stop), the
    take-profit levels as live (half at rhl, the rest at rht or a 10 % trailing), the stop per the variant: a / c / e
    the live stop (rll x 0.85), b / d / be the volatility stop on the live rll with ATR at lot 1 (detect.atr); c / d
    on 5-minute closes. Reclaim (e / be) as backtest.simulate. Returns {variant, stop_mc, atr_mc, stop_hit, stop_ts,
    exits [(ts, reason, frac, mc)], reclaim {ts, mc, pnl_usd} or None, pnl_usd (the round + a reclaim, at the owner's
    round-trip cost on live["liq"]), round_pnl_usd, mae_pct, open_at_end}."""
    v = VARIANTS[key]
    cs = _mc_candles(candles, supply, live.get("inject") or ())
    t1 = live["lots"][0]["ts"]
    rll = live["rll_mc"]
    stop = live["stop_mc"]
    atr_mc = None
    if v["new"]:
        a = detect.atr(candles, t1)
        atr_mc = a * supply if a else None
        stop = detect.vol_stop(rll, atr_mc)[0]
    lv = {"stop_px": stop, "rhl": live["rhl_mc"], "rht": live["rht_mc"], "rll": rll, "floor_px": rll * 0.92}
    rl = _range_low_at(candles, supply, live["lots"][-1]["ts"]) or rll
    lot_usd = [x["sol"] * live["sol_usd"] for x in live["lots"]]
    end = until or cs[-1][0]
    out = {"variant": key, "rule": v["hr"], "stop_mc": round(stop), "atr_mc": round(atr_mc) if atr_mc else None,
           "range_low_mc": round(rl), "stop_hit": False, "stop_ts": None, "stop_fill_mc": None, "exits": [],
           "reclaim": None}

    def walk(lots, t_from, lv, st, opened, arm):
        """Walk the minutes after t_from: (exits, units left per lot, mae, closed_ts, reason, cost)."""
        units = [u for _px, u in lots]
        cost = sum(px * u for px, u in lots)
        exits, mae, last = [], 0.0, None
        pending = [x for x in live["lots"][1:] if x["ts"] > t_from] if arm else []
        lv_t = dict(lv, stop_px=0.0) if v["stop_on"] == "close5" else lv
        for i, c in enumerate(cs):
            if c[0] <= t_from or c[0] > end:
                last = c[4] if c[0] <= t_from else last
                continue
            for px in backtest.tick_path(c, "wick"):
                if not any(u > 1e-12 for u in units):
                    break
                val = sum(u for u in units) * px + sum(e[4] for e in exits)
                mae = min(mae, val / cost - 1)
                hit = rules.exit_step(lv_t, st, px, c[0], opened, None)
                if hit:
                    reason, frac = hit
                    if reason == "tp1":
                        fill = lv["rhl"]
                    elif reason in ("stop", "trailing", "top"):
                        level = {"stop": lv["stop_px"], "trailing": (st.get("peak") or 0) * (1 - rules.RULES["trail"]),
                                 "top": lv["rht"]}[reason]
                        fill = level if last is not None and last >= level >= px else px
                    else:
                        fill = px
                    q = sum(units) * frac
                    units = [u * (1 - frac) for u in units]
                    exits.append((c[0], reason, frac, fill, q * fill))
                    if frac >= 0.999:
                        return exits, units, mae, c[0], reason, cost
                last = px
            if v["stop_on"] == "close5" and backtest.bar_closes(cs, i) and c[4] <= lv["stop_px"]:
                q = sum(units)
                exits.append((c[0], "stop", 1.0, c[4], q * c[4]))
                return exits, [0.0 for _ in units], mae, c[0], "stop", cost
            for x in pending:   # lot 2 at its logged market cap, in its minute
                if c[0] == x["ts"] - x["ts"] % 60:
                    u = x["sol"] * live["sol_usd"] / x["mc"]
                    units.append(u)
                    cost += x["mc"] * u
                    pending = [y for y in pending if y is not x]
        return exits, units, mae, None, None, cost

    def value(exits, units, cost, last_px):
        proceeds = sum(e[4] for e in exits) + sum(units) * last_px
        return proceeds - cost - cost * backtest.cost(cost, live.get("liq"))

    lots = [(live["lots"][0]["mc"], lot_usd[0] / live["lots"][0]["mc"])]
    ex, units, mae, closed, reason, cost = walk(lots, t1, lv, {}, t1, True)
    last_px = cs[-1][4]
    out["exits"] = [(e[0], e[1], e[2], round(e[3])) for e in ex]
    out["round_pnl_usd"] = round(value(ex, units, cost, last_px), 3)
    out["mae_pct"] = round(mae * 100, 1)
    out["lots"] = len(units)
    out["open_at_end"] = closed is None
    if reason == "stop":
        out.update(stop_hit=True, stop_ts=closed, stop_fill_mc=round(ex[-1][3]))
    total = out["round_pnl_usd"]
    if v["reclaim"] and reason == "stop":
        for i, c in enumerate(cs):
            if c[0] < closed - closed % 60 or c[0] > closed + backtest.RECLAIM_S:
                continue
            if c[4] <= rl or c[4] <= lv["stop_px"]:
                continue
            j = next(k for k, x in enumerate(candles) if x[0] == c[0])
            m = backtest._metrics_at(candles, [x[0] for x in candles], j, c[0], supply, True)
            if (m.get("buy_share_5m") or 0) < backtest.RECLAIM_BUYS - 1e-9:
                continue
            rlots = [(c[4], lot_usd[0] / c[4])]
            ex2, u2, mae2, closed2, reason2, cost2 = walk(rlots, c[0], dict(lv), {}, c[0], False)
            pnl2 = round(value(ex2, u2, cost2, last_px), 3)
            out["reclaim"] = {"ts": c[0], "mc": round(c[4]), "buy_share_5m": round(m["buy_share_5m"], 3),
                              "exits": [(e[0], e[1], e[2], round(e[3])) for e in ex2], "pnl_usd": pnl2,
                              "mae_pct": round(mae2 * 100, 1), "open_at_end": closed2 is None}
            total += pnl2
            break
    out["pnl_usd"] = round(total, 3)
    return out


def replay_table(candles, supply, live=None):
    """{variant: replay_live(...)} of the live round (HAOBIBI by default) and the booked fact."""
    live = live or HAOBIBI_LIVE
    return {"token": live["token"], "symbol": live["symbol"], "booked_usd": live["booked_usd"],
            "levels_mc": {"range_low_low": live["rll_mc"], "range_high_low (TP)": live["rhl_mc"],
                          "range_high_top": live["rht_mc"], "stop": live["stop_mc"]},
            "variants": {k: replay_live(candles, supply, live, k) for k in VARIANTS}}


def replay_line(tab):
    """One log / report line of replay_table()."""
    def hm(ts):
        return time.strftime("%H:%M", time.gmtime(ts)) if ts else "-"
    parts = []
    for k, r in tab["variants"].items():
        s = (f"{k}: stop {r['stop_mc']:,} " + (f"POGOĐEN {hm(r['stop_ts'])} UTC" if r["stop_hit"] else "nije pogođen")
             + f", runda {r['round_pnl_usd']:+.2f} $, MAE {r['mae_pct']:+.1f} %")
        if r.get("reclaim"):
            s += f", reclaim {hm(r['reclaim']['ts'])} na {r['reclaim']['mc']:,} {r['reclaim']['pnl_usd']:+.2f} $"
        parts.append(s + f", ukupno {r['pnl_usd']:+.2f} $")
    return (f"range stop replay {tab['symbol']} (živa runda, knjiženo {tab['booked_usd']:+.2f} $ ostaje): "
            + "; ".join(parts))
