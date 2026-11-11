"""Backtest of range_dca (spec 7) over the minute candles we hold, with the trader's own rules (rangedca/detect.py and
rules.py), so the numbers are the rule that would trade.

Simulation of one token, minute by minute (body path: open, then close):
  - every 5 minutes the range is computed from the last 24 h (detect.analyze) and the exclusions are updated
    (rules.exclusions); the live job does the same;
  - lot 1 / lot 2 at a minute's close when rules.entry_check / lot2_check pass with the 5-minute numbers of that
    minute; without transaction counts (GeckoTerminal candles) the buys share is the share of volume in rising
    minutes ("proxy"); liquidity unknown in history is not a reason to refuse (live it is checked);
  - exits with rules.exit_step at the open and the close of every minute; the first take profit fills at its level
    (the live executor sells at the first second at or over it), everything else at the price that triggered it
    (a stop that gapped fills lower: the pessimistic side); a give-up at that minute's close;
  - costs: trade/cost, the ONE model (11.11. owner's rule A): the fee each way (league/store.FEE, 1 %, until trade.db
    orders calibrate it) and the AMM impact of a LOT_USD lot on the pool (liquidity from the snapshots, else BT_LIQ).
Variants: range_score threshold 0.6 / 0.7 / 0.8, with and without lot 2. Report: rounds, win rate, average result
per round (USD and % of its cost), max drawdown of the summed rounds in exit order, the worst round, every round.
Output: output/range-backtest-YYYYMMDD.json and .md, and the summary in the log ("range backtest | ...").
The transfer-holders rule is not simulated (no history of who received what).

11.11. (flag range_flip G26, Jure: "backtest staro vs novo, live samo ako ne pogoršava DD"): the timeline also carries
the range_flip state (timeline(flip=True), detect.flip_step as run_range.py live) and rep["flip"] compares today's
rules with the new ones (FlipCompare, see the block before flip_line): PnL (SOL and %) at the owner's round-trip
cost(), max drawdown, false entries, rounds, per token and in total; the markdown gets its table, the log the line
"range flip backtest: ...", and the nightly run_server keeps the totals in range.db kv flip_backtest (the live gate,
rangedca/gate.flip_refusal). The days of data actually used are reported with it (data_span: hours and the share of
minutes that have a candle).
"""
import bisect
import json
import os
import statistics
import time

from trade import cost as _cost

from . import data, detect, gate, rules

LOT_USD = 15.0       # ~0.1 SOL, the Autopilot's size_sol
BT_LIQ = 40_000.0    # pool depth for the impact when the history has no liquidity reading
STEP_S = 300
THRESHOLDS = (0.6, 0.7, 0.8)
PROXY_OFF = "0.7_bez_proxyja"   # sensitivity: threshold 0.7 without the volume proxy of the buys share (see simulate)


def _fee():
    """The fee a side (trade/cost: league/store.FEE or its calibration)."""
    return _cost.fee_side()


def _impact(usd, liq):
    return _cost.impact(usd, liq or BT_LIQ)


def timeline(candles, supply, liq=None, step_s=STEP_S, flip=False):
    """[(ts, range dict, exclusion state)] every step_s from 6 h after the first candle (variant-independent).
    flip (11.11., range_flip): every range also carries its "flip" block (detect.flip_step from the previous step's
    state, as run_range.py does live); today's rules never read it."""
    out = []
    if not candles:
        return out
    ts = [c[0] for c in candles]
    cfg = {"supply": supply, "unknown_liq_ok": liq is None}
    snap = {"liq": liq} if liq else None
    st, fst = {}, None
    t = candles[0][0] + int(detect.CFG["min_hist_h"] * 3600)
    end = candles[-1][0]
    while t <= end:
        lo = bisect.bisect_left(ts, t - int(detect.CFG["window_h"] * 3600))
        hi = bisect.bisect_right(ts, t)
        res = detect.analyze(candles[lo:hi], t, snap, cfg)
        if liq:
            res["metrics"]["liq"] = liq
        if flip:
            fst = detect.flip_step(fst, res, candles[lo:hi], t, snap, cfg)
            res["flip"] = detect.flip_public(fst, supply)
        st = rules.exclusions(st, res, t)
        res = rules.apply_exclusion(res, st, t)
        out.append((t, res, dict(st)))
        t += step_s
    return out


def _metrics_at(candles, ts, i, t, supply, proxy_buys=True):
    lo = bisect.bisect_left(ts, t - 6 * 3600)
    m = detect.metrics(candles[lo:i + 1], t, None, {"supply": supply})
    if not proxy_buys and m.get("buy_share_how") == "proxy":
        m["buy_share_5m"] = 1.0   # the sensitivity variant: the volume proxy of the buys share is not used as a gate
    return m


def simulate(candles, supply, tl, score_min=0.7, lot2=True, liq=None, lot_usd=LOT_USD, proxy_buys=True, new=None):
    """The rounds of one token: [{opened, closed, lots, entry_mc, lot2_mc, exits, cost, pnl, ret, reason}].
    proxy_buys False: where the candles have no transaction counts, the buys-share gate is left out (a sensitivity
    check of the proxy, reported apart; live the gate reads DexScreener's real counts).
    new (11.11., range_flip): None = today's rules; else the parts of the new rules (rules.new_range: "flip", "atr")
    over a timeline(flip=True): the range in force, no lot 1 / lot 2 while blocked, the volatility stop."""
    ts = [c[0] for c in candles]
    tl_ts = [x[0] for x in tl]
    rounds, pos, cool_until = [], None, 0
    for i, c in enumerate(candles):
        t = c[0]
        k = bisect.bisect_right(tl_ts, t) - 1
        if k < 0:
            continue
        _t, rng, st = tl[k]
        if new:
            rng = rules.new_range(rng, new)
        if pos:
            lv = rules.merge_levels(pos["levels"], rules.levels_of(rng) if rng.get("active") and rng.get("zones") else None)
            pos["levels"]["stop_px"] = lv["stop_px"]
            gu = st.get("give_up")
            for px in (c[1], c[4]):
                if not pos:
                    break
                if gu and gu["ts"] >= pos["opened"]:
                    hit = (f"odustajanje: {gu['why']}", 1.0)
                else:
                    q = sum(x["qty"] for x in pos["lots"])
                    cost_left = sum(x["usd"] for x in pos["lots"]) - pos["realized"]
                    be = cost_left / q / ((1 - _fee()) * (1 - _impact(cost_left, liq))) if q > 0 and cost_left > 0 else None
                    hit = rules.exit_step(lv, pos["state"], px, t, pos["opened"], be)
                if not hit:
                    continue
                reason, frac = hit
                fill = lv["rhl"] if reason == "tp1" else px
                for x in pos["lots"]:
                    q = x["qty"] * frac
                    gross = q * fill
                    x["qty"] -= q
                    got = gross * (1 - _fee()) * (1 - _impact(gross, liq))
                    pos["realized"] += got
                pos["exits"].append({"ts": t, "reason": reason.split(":")[0], "frac": frac,
                                     "mc": round(fill * supply) if supply else None, "px": fill,
                                     "n_lots": len(pos["lots"])})
                if frac >= 0.999:
                    cost = sum(x["usd"] for x in pos["lots"])
                    pnl = pos["realized"] - cost
                    rounds.append({"opened": pos["opened"], "closed": t, "lots": len(pos["lots"]),
                                   "entry_mc": pos["entry_mc"], "lot2_mc": pos.get("lot2_mc"), "exits": pos["exits"],
                                   "cost": round(cost, 4), "pnl": round(pnl, 4), "ret": round(pnl / cost, 5),
                                   "reason": reason.split(":")[0], "score": pos["score"],
                                   "lot_px": [x["px"] for x in pos["lots"]], "stop_px": lv["stop_px"]})
                    pos = None
                    cool_until = t + rules.RULES["cooldown_s"]
            if pos and lot2 and len(pos["lots"]) == 1 and not pos["state"].get("tp1") and not rng.get("flip_block"):
                px = c[4]
                drop = 1 - px / pos["lot1_px"]
                if rules.RULES["lot2_lo"] - 1e-9 <= drop <= rules.RULES["lot2_hi"] + 1e-9:
                    m = _metrics_at(candles, ts, i, t, supply, proxy_buys)
                    if rules.lot2_check(pos["lot1_px"], px, lv, m) is None:
                        eff = px * (1 + _fee()) / (1 - _impact(lot_usd, liq))
                        pos["lots"].append({"px": px, "usd": lot_usd, "qty": lot_usd / eff})
                        pos["lot2_mc"] = round(px * supply) if supply else None
            continue
        if t < cool_until or not rng.get("active") or (rng.get("score") or 0) < score_min - 1e-9:
            continue
        px = c[4]
        lv = rules.levels_of(rng)
        span = lv["rht"] - lv["rll"]
        if px < lv["floor_px"] or not ((px - lv["rll"]) / span <= rules.RULES["entry_bottom"] or lv["rll"] <= px <= lv["rlt"]):
            continue
        m = _metrics_at(candles, ts, i, t, supply, proxy_buys)
        r2 = dict(rng, metrics=m)
        if (m.get("vol_h1") or 0) < detect.CFG["min_vol_h1"] or not supply or px * supply < detect.CFG["min_mcap"]:
            continue
        if rules.entry_check(r2, px, min_score=score_min) is None:
            eff = px * (1 + _fee()) / (1 - _impact(lot_usd, liq))
            pos = {"opened": t, "lot1_px": px, "lots": [{"px": px, "usd": lot_usd, "qty": lot_usd / eff}], "realized": 0.0,
                   "levels": lv, "state": {}, "exits": [], "entry_mc": round(px * supply), "score": rng.get("score")}
    if pos:   # still open at the end of the data: valued at the last close, marked open
        px = candles[-1][4]
        cost = sum(x["usd"] for x in pos["lots"])
        val = pos["realized"] + sum(x["qty"] * px * (1 - _fee()) for x in pos["lots"])
        rounds.append({"opened": pos["opened"], "closed": None, "lots": len(pos["lots"]), "entry_mc": pos["entry_mc"],
                       "lot2_mc": pos.get("lot2_mc"), "exits": pos["exits"], "cost": round(cost, 4),
                       "pnl": round(val - cost, 4), "ret": round((val - cost) / cost, 5), "reason": "otvoreno",
                       "score": pos["score"], "lot_px": [x["px"] for x in pos["lots"]], "last_px": px})
    return rounds


def summary(rounds):
    """n (closed), wins, win rate, average USD and % per round, total, max drawdown (USD, summed in exit order)."""
    closed = sorted((r for r in rounds if r["closed"]), key=lambda r: r["closed"])
    n = len(closed)
    out = {"rounds": n, "open_at_end": sum(1 for r in rounds if not r["closed"]), "wins": sum(1 for r in closed if r["pnl"] > 0)}
    out["win_rate"] = round(out["wins"] / n, 3) if n else None
    out["avg_pnl_usd"] = round(sum(r["pnl"] for r in closed) / n, 3) if n else None
    out["avg_ret_pct"] = round(statistics.mean(r["ret"] for r in closed) * 100, 2) if n else None
    out["total_pnl_usd"] = round(sum(r["pnl"] for r in closed), 3)
    eq = peak = dd = 0.0
    for r in closed:
        eq += r["pnl"]
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    out["max_drawdown_usd"] = round(dd, 3)
    out["worst_ret_pct"] = round(min(r["ret"] for r in closed) * 100, 2) if n else None
    out["with_lot2"] = sum(1 for r in closed if r["lots"] == 2)
    out["exit_reasons"] = {k: sum(1 for r in closed if r["reason"] == k) for k in sorted({r["reason"] for r in closed})}
    return out


def run_tokens(series, log=print, flip=True):
    """series: {token: (candles, supply, liq, symbol)}. Returns the report dict. flip (11.11.): the timeline also
    carries the range_flip state (today's variants do not read it) and rep["flip"] compares today's rules with the
    new ones (flip_compare)."""
    var = {f"{th:.1f}{'' if l2 else '_bez_lota2'}": [] for th in THRESHOLDS for l2 in (True, False)}
    var[PROXY_OFF] = []
    per = {}
    fc = FlipCompare() if flip else None
    t0 = time.time()
    for tok, (candles, supply, liq, sym) in series.items():
        if not candles or not supply or candles[-1][0] - candles[0][0] < detect.CFG["min_hist_h"] * 3600:
            continue
        tl = timeline(candles, supply, liq, flip=flip)
        if fc:
            fc.add(tok, sym, candles, supply, liq, tl)
        act = [x for x in tl if x[1].get("active")]
        per[tok] = {"symbol": sym, "hours": round((candles[-1][0] - candles[0][0]) / 3600, 1), "detections": len(tl),
                    "active_detections": len(act), "best_score": max((x[1].get("score") or 0 for x in act), default=None),
                    "tx_counts": any(c[6] is not None for c in candles)}
        runs = [(f"{th:.1f}{'' if l2 else '_bez_lota2'}", th, l2, True) for th in THRESHOLDS for l2 in (True, False)]
        for key, th, l2, pb in runs + [(PROXY_OFF, 0.7, True, False)]:
            rs = simulate(candles, supply, tl, th, l2, liq, proxy_buys=pb)
            for r in rs:
                r["token"], r["symbol"] = tok, sym
            var[key] += rs
        per[tok]["rounds_0.7"] = [r for r in var["0.7"] if r["token"] == tok]
        per[tok]["rounds_0.7_bez_proxyja"] = [r for r in var[PROXY_OFF] if r["token"] == tok]
    rep = {"generated_ts": int(time.time()), "tokens_with_data": len(series), "tokens_simulated": len(per),
           "tokens_with_range": sum(1 for p in per.values() if p["active_detections"]),
           "cpu_s": round(time.time() - t0, 1), "lot_usd": LOT_USD,
           "variants": {k: summary(v) for k, v in var.items()}, "tokens": per}
    if fc:
        rep["flip"] = fc.report()
    return rep


# ---------- range_flip: today's rules vs the new ones (11.11., flag range_flip G26) -----------------------------------
# The same timeline (timeline(flip=True)) and the same simulate() for both; the new rules are rules.new_range over it:
#   old        today's rules (range_low_low x 0.85 stop, no flip / pause)
#   new        flip + pause + the volatility stop (what range_flip paper trades)
#   atr_only   only the volatility stop;  flip_only  only flip + pause (x 0.85 stop): which part does what
# at the live threshold (score 0.7, lot 2, the volume proxy of the buys share as live). PnL of every round is priced
# again with the owner's round-trip cost (cost() below, as trade/cost.py: 2 x fee + 2 x size / (liq / 2 + size)):
# the same lot prices and exit fills, less cost(size, liq) x size. A FALSE ENTRY is a closed round that ended at the
# hard stop without ever taking the first take profit (the entry was wrong, not the exit). Max drawdown: the largest
# fall of the summed PnL in exit order (all tokens together, and per token). SOL at LOT_USD / 0.1 USD (lot = 0.1 SOL).
FLIP_VARIANTS = {"old": None, "new": ("flip", "atr"), "atr_only": ("atr",), "flip_only": ("flip",)}
BT_SOL_USD = LOT_USD / 0.1


def cost(size_usd, liq):
    """The owner's round-trip cost as a share of the size (11.11.): trade/cost.py, liq unknown: BT_LIQ."""
    return _cost.round_trip(size_usd, liq or BT_LIQ)


def priced(r, liq=None):
    """(pnl_usd, size_usd) of a simulated round at cost(): the lots' units at their prices, the exits' fills; an open
    round valued at its last close."""
    pxs = r.get("lot_px") or []
    size = r["cost"]
    usd = size / len(pxs) if pxs else 0.0
    units = [usd / px for px in pxs]
    proceeds = 0.0
    for e in r.get("exits") or []:
        for i in range(min(len(units), e.get("n_lots") or len(units))):
            q = units[i] * e["frac"]
            proceeds += q * e["px"]
            units[i] -= q
    if not r.get("closed") and r.get("last_px"):
        proceeds += sum(q * r["last_px"] for q in units)
    return proceeds - size - size * cost(size, liq), size


def false_entry(r):
    """A closed round that ended at the hard stop without the first take profit."""
    return bool(r.get("closed")) and r.get("reason") == "stop" and not any(e["reason"] == "tp1" for e in r.get("exits") or [])


def flip_summary(rounds):
    """rounds, wins, PnL (USD, SOL, % of the USD put in), max drawdown (USD, SOL), false entries, stops, the exit
    reasons, open at the end; rounds carry "pnl_c" (priced())."""
    closed = sorted((r for r in rounds if r.get("closed")), key=lambda r: r["closed"])
    pnl = sum(r["pnl_c"] for r in closed)
    size = sum(r["cost"] for r in closed)
    eq = peak = dd = 0.0
    for r in closed:
        eq += r["pnl_c"]
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {"rounds": len(closed), "wins": sum(1 for r in closed if r["pnl_c"] > 0),
            "pnl_usd": round(pnl, 3), "pnl_sol": round(pnl / BT_SOL_USD, 4),
            "pnl_pct": round(pnl / size * 100, 2) if size else None,
            "max_dd_usd": round(dd, 3), "max_dd_sol": round(dd / BT_SOL_USD, 4),
            "false_entries": sum(1 for r in closed if false_entry(r)),
            "stops": sum(1 for r in closed if r["reason"] == "stop"),
            "exit_reasons": {k: sum(1 for r in closed if r["reason"] == k) for k in sorted({r["reason"] for r in closed})},
            "open_at_end": sum(1 for r in rounds if not r.get("closed"))}


def data_span(candles):
    """{hours, days, coverage}: the hours from the first to the last candle and the share of its minutes that have a
    candle (GeckoTerminal leaves out the minutes without a trade; snapshots stand for several minutes)."""
    if not candles:
        return {"hours": 0.0, "days": 0.0, "coverage": None}
    span = (candles[-1][0] - candles[0][0]) / 60 + 1
    return {"hours": round(span / 60, 1), "days": round(span / 1440, 2), "coverage": round(len(candles) / span, 3)}


class FlipCompare:
    """Collects old vs new per token (run_tokens), report() sums them."""

    def __init__(self, score_min=0.7):
        self.score_min, self.tokens, self.rounds = score_min, {}, {k: [] for k in FLIP_VARIANTS}

    def add(self, tok, sym, candles, supply, liq, tl):
        per = {"symbol": sym, **data_span(candles), "detections": len(tl),
               "states": {}, "breaks_up": 0, "breaks_down": 0, "unconfirmed": 0}
        last = None
        for _t, rng, _st in tl:
            fl = rng.get("flip") or {}
            s = fl.get("state")
            per["states"][s] = per["states"].get(s, 0) + 1
            b = fl.get("brk")
            if b and (last is None or b.get("ts") != last):
                per["breaks_up" if b["dir"] == "up" else "breaks_down"] += 1
                last = b.get("ts")
            if fl.get("seen") and fl["seen"].get("ts") != per.get("_seen"):
                per["unconfirmed"] += 1
                per["_seen"] = fl["seen"]["ts"]
        per.pop("_seen", None)
        for k, parts in FLIP_VARIANTS.items():
            rs = simulate(candles, supply, tl, self.score_min, True, liq, new=parts)
            for r in rs:
                r["token"], r["symbol"] = tok, sym
                r["pnl_c"] = priced(r, liq)[0]
            self.rounds[k] += rs
            per[k] = flip_summary(rs)
            if k in ("old", "new"):
                per[f"rounds_{k}"] = [{"opened": r["opened"], "closed": r["closed"], "reason": r["reason"],
                                       "entry_mc": r["entry_mc"], "lots": r["lots"], "pnl_usd": round(r["pnl_c"], 3),
                                       "stop_mc": round(r["stop_px"] * supply) if r.get("stop_px") and supply else None,
                                       "false_entry": false_entry(r)} for r in rs]
        self.tokens[tok] = per

    def report(self):
        hours = sorted(p["hours"] for p in self.tokens.values())
        out = {"variants": {k: flip_summary(v) for k, v in self.rounds.items()}, "tokens": self.tokens,
               "score_min": self.score_min, "lot_usd": LOT_USD, "sol_usd": BT_SOL_USD,
               "data": {"tokens": len(hours), "days_total": round(sum(hours) / 24, 2),
                        "max_days": round(hours[-1] / 24, 2) if hours else 0.0,
                        "median_hours": round(statistics.median(hours), 1) if hours else 0.0,
                        "tokens_24h_plus": sum(1 for h in hours if h >= 24)},
               "params": dict(detect.FLIP), "cost": "2 x fee_side + 2 x size / (liq / 2 + size), fee_side 1 %"}
        o, n = out["variants"]["old"], out["variants"]["new"]
        out["dd_ok"] = n["max_dd_sol"] <= o["max_dd_sol"] + 1e-9
        # 11.11. (Jure): no conclusion below gate.FLIP_MIN_ROUNDS (30) closed rounds of BOTH rule sets
        out["enough"] = min(o["rounds"], n["rounds"]) >= gate.FLIP_MIN_ROUNDS
        return out


def flip_line(fr):
    """The log line "range flip backtest: ..." of rep["flip"]."""
    v, d = fr["variants"], fr["data"]

    def s(x):
        return (f"runde {x['rounds']}, PnL {x['pnl_sol']:+.3f} SOL ({x['pnl_pct'] if x['pnl_pct'] is not None else 0:+.1f} %), "
                f"DD {x['max_dd_sol']:.3f} SOL, lažni ulazi {x['false_entries']}")
    head = (f"range flip backtest: {d['tokens']} tokena, {d['days_total']} dana podataka ukupno (najviše "
            f"{d['max_days']} dana po tokenu, medijan {d['median_hours']} h, {d['tokens_24h_plus']} tokena s 24 h+); ")
    if not fr.get("enough", True):   # 11.11. (Jure): below 30 rounds of both, only the count (no comparison)
        return (head + f"premalo rundi za zaključak (staro {v['old']['rounds']}, novo {v['new']['rounds']}, treba "
                f"{gate.FLIP_MIN_ROUNDS} za oba): usporedba čeka")
    return (head + f"staro: {s(v['old'])}; novo: {s(v['new'])}; samo ATR stop: {s(v['atr_only'])}; samo flip/pauza: "
            f"{s(v['flip_only'])}; DD novo <= staro: {'da' if fr['dd_ok'] else 'ne'}")


def flip_md(fr):
    """The markdown section of the comparison (per token and total)."""
    lines = ["", "## range_flip: stara pravila vs nova (flip / pauza / ATR stop)", "",
             f"Prag ocjene {fr['score_min']}, lot 2, lot ${fr['lot_usd']:.0f} (0,1 SOL), trošak {fr['cost']}. Lažni ulaz = "
             "runda završena tvrdim stopom bez prvog TP-a. Podaci: "
             f"{fr['data']['tokens']} tokena, {fr['data']['days_total']} dana ukupno, najviše {fr['data']['max_days']} "
             "dana po tokenu.", "",
             "| token | sati | pravila | runde | PnL SOL | PnL % | max DD SOL | lažni ulazi | stopovi |",
             "|---|---|---|---|---|---|---|---|---|"]
    rows = [(p["symbol"] or t[:6], p["hours"], p) for t, p in fr["tokens"].items()]
    rows.append(("UKUPNO", round(fr["data"]["days_total"] * 24, 1), fr["variants"]))
    for name, h, p in rows:
        for k in FLIP_VARIANTS:
            x = p[k]
            lines.append(f"| {name} | {h} | {k} | {x['rounds']} | {x['pnl_sol']:+.4f} | "
                         f"{x['pnl_pct'] if x['pnl_pct'] is not None else '-'} | {x['max_dd_sol']:.4f} | "
                         f"{x['false_entries']} | {x['stops']} |")
    v = fr["variants"]
    lines += ["", f"DD novo <= staro: {'da' if fr['dd_ok'] else 'ne'}" if fr.get("enough", True) else
              f"Bez zaključka: premalo rundi (staro {v['old']['rounds']}, novo {v['new']['rounds']}, treba "
              f"{gate.FLIP_MIN_ROUNDS} za oba)."]
    return "\n".join(lines) + "\n"


def md(rep, title="Range DCA backtest"):
    v = rep["variants"]
    lines = [f"# {title}", "",
             f"Tokena s podacima: {rep['tokens_with_data']}, simulirano (>= 6 h minutnih podataka): {rep['tokens_simulated']}, "
             f"s otkrivenim rasponom: {rep['tokens_with_range']}. Lot ${rep['lot_usd']:.0f}, naknada 1 % + utjecaj na pool "
             "po strani.", "",
             "| prag ocjene | lot 2 | runde | dobitne | win rate | prosjek $ | prosjek % | ukupno $ | max drawdown $ | najgora % |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for k, s in v.items():
        th, l2 = k.split("_")[0], "ne" if "lota2" in k else "da"
        if k == PROXY_OFF:
            th += " (bez proxy filtra kupnji)"
        lines.append(f"| {th} | {l2} | {s['rounds']} | {s['wins']} | {s['win_rate'] if s['win_rate'] is not None else '-'} | "
                     f"{s['avg_pnl_usd'] if s['avg_pnl_usd'] is not None else '-'} | "
                     f"{s['avg_ret_pct'] if s['avg_ret_pct'] is not None else '-'} | {s['total_pnl_usd']} | "
                     f"{s['max_drawdown_usd']} | {s['worst_ret_pct'] if s['worst_ret_pct'] is not None else '-'} |")
    for key, title_ in (("rounds_0.7", "prag 0,7, s lotom 2"), ("rounds_0.7_bez_proxyja", "prag 0,7, bez proxy filtra kupnji")):
        lines += ["", f"## Runde ({title_})", ""]
        for tok, p in rep["tokens"].items():
            for r in p.get(key) or []:
                ex = ", ".join(f"{e['reason']} {e['frac']:.0%} @ {e['mc'] or 0:,.0f}" for e in r["exits"])
                lines.append(f"- {p['symbol'] or tok[:6]} {time.strftime('%d.%m. %H:%M', time.gmtime(r['opened']))} UTC: "
                             f"ulaz MC {r['entry_mc']:,.0f}" + (f", lot 2 {r['lot2_mc']:,.0f}" if r.get("lot2_mc") else "")
                             + f"; izlazi: {ex or '-'}; {r['ret'] * 100:+.1f} % ({r['reason']})")
    return "\n".join(lines) + "\n" + (flip_md(rep["flip"]) if rep.get("flip") else "")


def write(rep, log=print, name=None):
    out = os.path.join(data.ROOT, "output")
    os.makedirs(out, exist_ok=True)
    name = name or f"range-backtest-{time.strftime('%Y%m%d', time.gmtime())}"
    with open(os.path.join(out, name + ".json"), "w") as f:
        json.dump(rep, f, ensure_ascii=False)
    text = md(rep)
    with open(os.path.join(out, name + ".md"), "w") as f:
        f.write(text)
    for ln in text.splitlines()[:60]:
        if ln.strip():
            log(f"range backtest | {ln}")
    return os.path.join(out, name + ".md")


# ---------- the data we have (server) -------------------------------------------------------------------------------
def _supply(token, snaps):
    s = [x["mcap"] / x["price"] for x in snaps if x.get("mcap") and x.get("price")]
    if s:
        return statistics.median(s)
    try:
        from kol import store as kstore
        con = data._ro_file(kstore.DB)
        if con is not None:
            try:
                r = con.execute("SELECT supply FROM tokens WHERE token=?", (token,)).fetchone()
            finally:
                con.close()
            if r and r[0]:
                return float(r[0])
    except Exception:  # noqa: BLE001
        pass
    return 1e9 if token.endswith("pump") else None   # pump.fun: always 1 billion


def tokens_with_data(rcon, now, days=14):
    toks = set()
    t0 = int(now - days * 86400)
    toks |= {r[0] for r in rcon.execute("SELECT token FROM gt_candles WHERE last_ts >= ?", (t0,))}
    toks |= {r[0] for r in rcon.execute("SELECT DISTINCT token FROM snaps WHERE ts >= ?", (t0,))}
    for path, sql in ((data.minute_path(), "SELECT token FROM call_candles WHERE last_ts >= ? AND n >= 300"),
                      (data.hype_path(), "SELECT token FROM token_pulse WHERE ts >= ? GROUP BY token HAVING COUNT(*) >= 150")):
        con = data._ro_file(path)
        if con is None:
            continue
        try:
            toks |= {r[0] for r in con.execute(sql, (t0,))}
        except Exception:  # noqa: BLE001
            pass
        finally:
            con.close()
    # 11.11. (market watchlist): a token only the market list snapshots is simulated only when it had an active range
    # in the window (range.db events 'aktivan'), so the night pass does not replay ~400 quiet tokens
    try:
        mkt = {r[0] for r in rcon.execute("SELECT token FROM mkt")}
        if mkt:
            had = {r[0] for r in rcon.execute("SELECT DISTINCT token FROM events WHERE kind='aktivan' AND ts >= ?", (t0,))}
            sig = {r[0] for r in rcon.execute("SELECT token FROM gt_candles")}
            toks = {t for t in toks if t not in mkt or t in had or t in sig}
    except Exception:  # noqa: BLE001 - no market table: every token
        pass
    return sorted(toks)


class _Lazy:
    """{token: series} for run_tokens, loaded one token at a time (11.11.: with the market watchlist every series in
    memory at once would be hundreds of MB on Render)."""

    def __init__(self, rcon, toks, now, days):
        self.rcon, self.toks, self.now, self.days = rcon, toks, now, days

    def __len__(self):
        return len(self.toks)

    def items(self):
        for t in self.toks:
            yield t, load(self.rcon, t, self.now, self.days)


def load(rcon, token, now, days=14):
    t0 = int(now - days * 86400)
    snaps = data.own_rows(rcon, token, t0) + data.pulse_rows(token, t0)
    true = data.gt_rows(rcon, token, t0, now) + data.call_candles(token, t0, now)
    candles = data.merge(true, snaps)
    liqs = [s["liq"] for s in snaps if s.get("liq")]
    sym = None
    p = rcon.execute("SELECT symbol FROM pools WHERE token=?", (token,)).fetchone()
    if p:
        sym = p[0]
    return candles, _supply(token, snaps), (statistics.median(liqs) if liqs else None), sym


def top_up(rcon, now, n, days=14, fetch=None, log=print):
    """At most n GeckoTerminal requests (inside the range day cap, data.GT_DAY) for tokens called in the last `days` at
    MC >= 30k whose stored minutes cover < 6 h: 1000 minute candles from 2 h before the first call. Returns the count."""
    if n <= 0:
        return 0
    try:
        from kol import store as kstore
        kcon = data._ro_file(kstore.DB)
    except Exception:  # noqa: BLE001
        kcon = None
    if kcon is None:
        return 0
    try:
        rows = kcon.execute("SELECT c.token, MIN(c.ts), COUNT(*), t.pair FROM calls c JOIN tokens t ON t.token=c.token "
                            "WHERE c.ts >= ? AND COALESCE(c.mcap0, 0) >= 30000 AND t.pair IS NOT NULL GROUP BY c.token "
                            "ORDER BY COUNT(*) DESC LIMIT 200", (int(now - days * 86400),)).fetchall()
    finally:
        kcon.close()
    done = 0
    for tok, first, _n, pool in rows:
        if done >= n or data.gt_left(rcon, now) <= 0:
            break
        if rcon.execute("SELECT 1 FROM gt_candles WHERE token=?", (tok,)).fetchone():
            continue
        start = int(first - 2 * 3600)
        data.day_add(rcon, "gt_day", 1, now)
        rcon.commit()
        try:
            got = (fetch or data.gt_fetch)(pool, start, min(int(now), start + 998 * 60))
        except Exception:  # noqa: BLE001
            got = None
        if got is None:
            break   # GeckoTerminal busy or refused: the rest next night
        data.store_gt(rcon, tok, pool, got, now)
        rcon.commit()
        done += 1
    if done:
        log(f"range backtest: {done} GeckoTerminal zahtjeva za povijest (dnevni strop {data.GT_DAY})")
    return done


def run_server(now=None, days=14, gt=0, log=print, fetch=None):
    now = int(now or time.time())
    rcon = data.connect()
    try:
        top_up(rcon, now, gt, days, fetch, log)
        rep = run_tokens(_Lazy(rcon, tokens_with_data(rcon, now, days), now, days), log)
        fr = rep.get("flip")
        if fr:   # 11.11. (range_flip G26): the old vs new numbers the live gate reads (rangedca/gate.flip_refusal)
            data.kv_put(rcon, "flip_backtest", {"ts": now, "days": days, "tokens": fr["data"]["tokens"],
                                                "data": fr["data"], "dd_ok": fr["dd_ok"], "enough": fr["enough"],
                                                **fr["variants"]})
            rcon.commit()
    finally:
        rcon.close()
    rep["days"] = days
    path = write(rep, log)
    log(f"range backtest: {rep['tokens_simulated']} tokena, {rep['cpu_s']} s, izvještaj {path}")
    if rep.get("flip"):
        log(flip_line(rep["flip"]))
    return rep
