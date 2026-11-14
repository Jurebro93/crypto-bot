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
from . import survivor as _survivor

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


RECLAIM_S = 30 * 60      # 11.11. stop variant (e): a reclaim within 30 minutes of the stop ...
RECLAIM_BUYS = 0.6       # ... with buys >= 60 % of the last 5 minutes (the proxy where the candles have no counts)
BAR_S = 300              # stop variants (c) / (d): the stop reads 5-minute closes (epoch-aligned, as detect.bars)


def tick_path(c, ticks="body"):
    """The prices one minute is walked through: "body" (today's backtest) open, close; "wick" (11.11., the stop
    variants: the live loop sees every second, wicks included) open, low, high, close for a rising minute and open,
    high, low, close for a falling one (the usual OHLC order)."""
    if ticks != "wick":
        return (c[1], c[4])
    return (c[1], c[3], c[2], c[4]) if c[4] >= c[1] else (c[1], c[2], c[3], c[4])


def bar_closes(candles, i, bar_s=BAR_S):
    """True when candle i is the last one of its 5-minute bar (the next candle starts a new bar); the last candle of
    the data is not known to close its bar."""
    return i + 1 < len(candles) and candles[i + 1][0] // bar_s != candles[i][0] // bar_s


def breakdown_give_up(gu):
    """A give-up of the "range broken downward" exclusion (rules.exclusions): the floor gave way, a stop in effect."""
    return bool(gu) and "probijen dolje" in (gu.get("why") or "")


def _rt(cfg, lot_usds, liq):
    """14.11. popodne: the round trip of a position of these lots as a fraction: the owner's model
    (trade/cost.round_trip of the whole size, as priced()), or with cfg real_fee_side the real account's
    rules.real_cost (the pool's fee + the route's, each buy's impact, the network fee tx_usd of every swap)."""
    c = cfg or {}
    if c.get("real_fee_side") is not None:
        return rules.real_cost(lot_usds, liq or BT_LIQ, c["real_fee_side"], c.get("tx_usd") or 0.0,
                               sells=rules.n_sells(c))
    return _cost.round_trip(sum(lot_usds), liq or BT_LIQ)


def simulate(candles, supply, tl, score_min=0.7, lot2=True, liq=None, lot_usd=LOT_USD, proxy_buys=True, new=None,
             ticks="body", stop_on="tick", reclaim=False, cfg=None, guard=None):
    """The rounds of one token: [{opened, closed, lots, entry_mc, lot2_mc, exits, cost, pnl, ret, reason}].
    proxy_buys False: where the candles have no transaction counts, the buys-share gate is left out (a sensitivity
    check of the proxy, reported apart; live the gate reads DexScreener's real counts).
    new (11.11., range_flip): None = today's rules; else the parts of the new rules (rules.new_range: "flip", "atr")
    over a timeline(flip=True): the range in force, no lot 1 / lot 2 while blocked, the volatility stop.
    11.11. stop variants (rangedca/stops.py; the defaults are today's backtest exactly):
      ticks    "body" (open, close) | "wick" (tick_path: the minute's low and high too; a stop, trailing or top exit
               that a tick passes through fills at its level, one that gapped past it at the tick)
      stop_on  "tick" | "close5": the hard stop AND the "range broken downward" give-up sell only on a 5-minute close
               under their level (stop_px, floor_px = range_low_low x 0.92), at that close; other give-ups unchanged
      reclaim  after a round that ended at the hard stop or on that give-up, a new lot 1 (a round of the same rules
               with the stopped round's TP and stop levels) when within RECLAIM_S the minute closes above range_low
               (the bottom zone's average) and above the stop with buys >= RECLAIM_BUYS of 5 minutes; one reclaim per
               stopped round, never after a reclaim round, the cooldown and the exclusion do not apply to it.
    A round also carries "mae" (the worst mark-to-market of its lots, a fraction of their cost, before cost) with
    ticks "wick", and "reclaim" True for a reclaim round.
    cfg (14.11., the demo profile rules.DEMO): the entry thresholds of cfg (score_min unless score_min is given, the
    bottom share, 5-minute change, volume ratio, buys), the crash-survivor filter (rangedca/survivor, its age the
    span of the data: a lower bound) when cfg["survivor"], the round's levels from rules.demo_levels (TP +10 % / +15 %
    net of cost(), the stop held at -12..-25 % from the entry, break-even on the rest after TP1: the rest's own cost,
    as the live exit loop's _be_px after a partial sale), no lot 2 when cfg["lot2"] is False, no reclaim.
    14.11. popodne (the scalp profile rules.DEMO / SCALP): lot 1 = lot_usd x lot1_share (60 %), lot 2 (DCA) = the rest
    (40 %) by rules.demo_lot2_check (with the crash-survivor check of that minute), the TP on the average entry of both
    lots (rules.demo_retarget) net of the position's round trip (_rt: the owner's cost model, or the real account's
    real_cost when cfg carries real_fee_side / tx_usd), rules.fee_guard before lot 1 and lot 2, the cooldown
    cooldown_tp_s after a profitable exit (rules.TP_EXITS) and cooldown_s after a stop, at most rounds_token_day rounds
    a (Zagreb) day. Every round also carries "lot_usd" (each lot's USD), "dca_ts" and "guard" counts land in
    simulate.guard (a dict passed in, optional)."""
    c_ = rules._r(cfg)
    demo = (cfg or {}).get("profile") in rules.PROFILES
    if demo:
        reclaim = False
        lot2 = lot2 and c_.get("lot2", True) is not False
    split = demo and lot2 and c_.get("lot1_share")
    l1_usd = lot_usd * c_["lot1_share"] if split else lot_usd
    l2_usd = lot_usd - l1_usd if split else lot_usd
    day_n = {}
    ts = [c[0] for c in candles]
    tl_ts = [x[0] for x in tl]
    rounds, pos, cool_until, rec = [], None, 0, None
    wick, close5 = ticks == "wick", stop_on == "close5"
    prev_close = None

    def sell(reason, frac, fill, t, lv):
        nonlocal pos, cool_until, rec
        for x in pos["lots"]:
            q = x["qty"] * frac
            gross = q * fill
            x["qty"] -= q
            got = gross * (1 - _fee()) * (1 - _impact(gross, liq))
            pos["realized"] += got
        pos["exits"].append({"ts": t, "reason": reason.split(":")[0], "frac": frac,
                             "mc": round(fill * supply) if supply else None, "px": fill, "n_lots": len(pos["lots"]),
                             **({"why": reason.split(":", 1)[1].strip()} if ":" in reason else {})})
        if frac < 0.999:
            return
        cost = sum(x["usd"] for x in pos["lots"])
        pnl = pos["realized"] - cost
        r = {"opened": pos["opened"], "closed": t, "lots": len(pos["lots"]), "entry_mc": pos["entry_mc"],
             "lot2_mc": pos.get("lot2_mc"), "exits": pos["exits"], "cost": round(cost, 4), "pnl": round(pnl, 4),
             "ret": round(pnl / cost, 5), "reason": reason.split(":")[0], "score": pos["score"],
             "lot_px": [x["px"] for x in pos["lots"]], "stop_px": lv["stop_px"],
             "lot_usd": [x["usd"] for x in pos["lots"]]}
        if wick:
            r["mae"] = round(pos["mae"], 5)
        if pos.get("reclaim"):
            r["reclaim"] = True
        rounds.append(r)
        stopped = reason == "stop" or (reason.startswith("odustajanje") and "probijen dolje" in reason)
        if reclaim and stopped and not pos.get("reclaim"):
            rec = {"until": t + RECLAIM_S, "levels": dict(pos["levels"], stop_px=lv["stop_px"]),
                   "rl": pos.get("rl") or lv["rll"], "score": pos["score"]}
        pos = None
        short = c_.get("cooldown_tp_s") is not None and reason.split(":")[0] in rules.TP_EXITS
        cool_until = t + (c_["cooldown_tp_s"] if short else c_["cooldown_s"])

    def fill_of(reason, px, last, lv, st, be=None):
        if reason == "tp1":
            return lv.get("tp1_px") or lv["rhl"]
        if reason == "tp2":   # 14.11. (DEMO): the rest at its +15 % net price, sold at the first tick at or over it
            return rules.tp2_of(lv)
        if not wick or reason not in ("stop", "trailing", "top", "breakeven"):
            return px
        level = {"stop": lv["stop_px"], "trailing": (st.get("peak") or 0) * (1 - c_["trail"]),
                 "top": lv["rht"], "breakeven": be or px}[reason]
        return level if last is not None and last >= level >= px else px

    def mark(px):
        if pos and wick:
            cost = sum(x["usd"] for x in pos["lots"])
            val = pos["realized"] + sum(x["qty"] * px for x in pos["lots"])
            pos["mae"] = min(pos["mae"], val / cost - 1)

    def open_pos(t, px, lv, score, rl, is_reclaim=False):
        eff = px * (1 + _fee()) / (1 - _impact(l1_usd, liq))
        if demo:   # 14.11.: the demo round's own TP prices and stop clamp, from the entry
            lv = rules.demo_levels(lv, px, _rt(cfg, [l1_usd], liq), cfg, cost_usd=l1_usd)
        return {"opened": t, "lot1_px": px, "lots": [{"px": px, "usd": l1_usd, "qty": l1_usd / eff,
                                                       "q0": l1_usd / eff}], "realized": 0.0,
                "levels": lv, "state": {}, "exits": [], "entry_mc": round(px * supply), "score": score, "rl": rl,
                "mae": 0.0, **({"reclaim": True} if is_reclaim else {})}

    for i, c in enumerate(candles):
        t = c[0]
        k = bisect.bisect_right(tl_ts, t) - 1
        if k < 0:
            prev_close = c[4]
            continue
        _t, rng, st = tl[k]
        if new:
            rng = rules.new_range(rng, new)
        was_open = pos is not None
        if pos:
            lv = rules.levels_in_force(pos["levels"], rules.levels_of(rng) if rng.get("active") and rng.get("zones")
                                       else None)
            pos["levels"]["stop_px"] = lv["stop_px"]
            gu = st.get("give_up")
            gu = gu if gu and gu["ts"] >= pos["opened"] and rules.gives_up(gu, cfg) else None
            gu_bar = close5 and breakdown_give_up(gu)   # (c) / (d): that give-up waits for a 5-minute close
            lv_t = dict(lv, stop_px=0.0) if close5 else lv
            last = prev_close
            for px in tick_path(c, ticks):
                if not pos:
                    break
                mark(px)
                be = None
                if gu and not gu_bar:
                    hit = (f"odustajanje: {gu['why']}", 1.0)
                else:
                    q = sum(x["qty"] for x in pos["lots"])
                    cost_left = sum(x["usd"] for x in pos["lots"]) - pos["realized"]
                    be = cost_left / q / ((1 - _fee()) * (1 - _impact(cost_left, liq))) if q > 0 and cost_left > 0 else None
                    if demo:   # 14.11.: the rest's own break-even (the live _be_px after a partial sale), not the round's
                        usd, q0 = sum(x["usd"] for x in pos["lots"]), sum(x["q0"] for x in pos["lots"])
                        be = usd / q0 / ((1 - _fee()) * (1 - _impact(usd * q / q0, liq))) if q0 > 0 and q > 0 else None
                    hit = rules.exit_step(lv_t, pos["state"], px, t, pos["opened"], be, cfg=cfg)
                if hit:
                    sell(hit[0], hit[1], fill_of(hit[0], px, last, lv, pos["state"], be), t, lv)
                last = px
            if pos and close5 and bar_closes(candles, i):
                px = c[4]
                if gu_bar and px < lv["floor_px"]:
                    sell(f"odustajanje: {gu['why']}", 1.0, px, t, lv)
                elif px <= lv["stop_px"]:
                    sell("stop", 1.0, px, t, lv)
            if pos and lot2 and len(pos["lots"]) == 1 and not pos["state"].get("tp1") and not rng.get("flip_block") \
                    and not pos.get("lot2_no"):
                px = c[4]
                drop = 1 - px / pos["lot1_px"]
                if c_["lot2_lo"] - 1e-9 <= drop <= c_["lot2_hi"] + 1e-9:
                    m = _metrics_at(candles, ts, i, t, supply, proxy_buys)
                    if demo:   # 14.11. popodne: the scalp profile's DCA (range active, not crashed, above the stop)
                        r2 = dict(rng, metrics=m)
                        if c_.get("survivor"):
                            lo25 = bisect.bisect_left(ts, t - 25 * 3600)
                            r2["survivor"] = _survivor.check(candles[lo25:i + 1], t, rng, price=px)
                        why2 = rules.demo_lot2_check(pos["lot1_px"], px, dict(lv, stop_px=pos["levels"]["stop_px"]),
                                                     r2, m, cfg)
                    else:
                        why2 = rules.lot2_check(pos["lot1_px"], px, lv, m, cfg)
                    if why2 is None:
                        eff = px * (1 + _fee()) / (1 - _impact(l2_usd, liq))
                        new_lot = {"px": px, "usd": l2_usd, "qty": l2_usd / eff, "q0": l2_usd / eff}
                        nlv = None
                        if demo:   # the TP prices follow the average entry of both lots, net of both buys
                            lots_ = pos["lots"] + [new_lot]
                            usd = sum(x["usd"] for x in lots_)
                            avg = usd / sum(x["usd"] / x["px"] for x in lots_)
                            nlv = rules.demo_retarget(dict(pos["levels"], rht=lv["rht"]), avg,
                                                      _rt(cfg, [x["usd"] for x in lots_], liq), usd, cfg)
                            g = rules.fee_guard(nlv, cfg, lot=2)
                            if g:
                                pos["lot2_no"] = g
                                if guard is not None:
                                    guard["lot2"] = guard.get("lot2", 0) + 1
                                new_lot = None
                        if new_lot:
                            pos["lots"].append(new_lot)
                            pos["lot2_mc"] = round(px * supply) if supply else None
                            pos["dca_ts"] = t
                            if nlv:
                                pos["levels"].update({k: nlv[k] for k in ("tp1_px", "tp2_px", "entry_px", "rt_cost",
                                                                          "tp_net", "cost_usd", "dca")})
            if pos or rec is None:
                prev_close = c[4]
                continue
        if rec is not None:   # (e): the minute's close back above range_low within RECLAIM_S, buys >= 60 %
            if t > rec["until"]:
                rec = None
            elif c[4] > rec["rl"] and c[4] > (rec["levels"].get("stop_px") or 0) and supply:
                m = _metrics_at(candles, ts, i, t, supply, proxy_buys)
                if (m.get("buy_share_5m") or 0) >= RECLAIM_BUYS - 1e-9:
                    pos = open_pos(t, c[4], dict(rec["levels"]), rec["score"], rec["rl"], True)
                    rec = None
                    prev_close = c[4]
                    continue
            if was_open:
                prev_close = c[4]
                continue
        prev_close = c[4]
        if t < cool_until or not rng.get("active") or (rng.get("score") or 0) < score_min - 1e-9:
            continue
        day = (t + 3600) // 86400   # the Zagreb day (CET in November), as the live counter
        if c_.get("rounds_token_day") and day_n.get(day, 0) >= c_["rounds_token_day"]:
            continue
        px = c[4]
        lv = rules.levels_of(rng)
        if not rules.in_entry_zone(lv, px, c_):
            continue
        m = _metrics_at(candles, ts, i, t, supply, proxy_buys)
        r2 = dict(rng, metrics=m)
        if (m.get("vol_h1") or 0) < detect.CFG["min_vol_h1"] or not supply or px * supply < detect.CFG["min_mcap"]:
            continue
        if c_.get("survivor"):   # 14.11.: the crash survivor of now (rangedca/survivor), age = the data's span
            lo25 = bisect.bisect_left(ts, t - 25 * 3600)
            r2["survivor"] = _survivor.check(candles[lo25:i + 1], t, rng, price=px)
        if rules.entry_check(r2, px, cfg, min_score=score_min) is None:
            if demo:   # 14.11. popodne: the fee guard (cost cap, TP inside the range) before lot 1
                g = rules.fee_guard(rules.demo_levels(lv, px, _rt(cfg, [l1_usd], liq), cfg, cost_usd=l1_usd), cfg)
                if g:
                    if guard is not None:
                        guard["lot1"] = guard.get("lot1", 0) + 1
                    continue
            pos = open_pos(t, px, lv, rng.get("score"), (rng.get("zones") or {}).get("range_low") or lv["rll"])
            day_n[day] = day_n.get(day, 0) + 1
    if pos:   # still open at the end of the data: valued at the last close, marked open
        px = candles[-1][4]
        cost = sum(x["usd"] for x in pos["lots"])
        val = pos["realized"] + sum(x["qty"] * px * (1 - _fee()) for x in pos["lots"])
        r = {"opened": pos["opened"], "closed": None, "lots": len(pos["lots"]), "entry_mc": pos["entry_mc"],
             "lot2_mc": pos.get("lot2_mc"), "exits": pos["exits"], "cost": round(cost, 4),
             "pnl": round(val - cost, 4), "ret": round((val - cost) / cost, 5), "reason": "otvoreno",
             "score": pos["score"], "lot_px": [x["px"] for x in pos["lots"]], "last_px": px,
             "lot_usd": [x["usd"] for x in pos["lots"]]}
        if wick:
            r["mae"] = round(pos["mae"], 5)
        if pos.get("reclaim"):
            r["reclaim"] = True
        rounds.append(r)
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


def run_tokens(series, log=print, flip=True, stops=True, gate_exclude=(), demo=True):
    """series: {token: (candles, supply, liq, symbol)}. Returns the report dict. flip (11.11.): the timeline also
    carries the range_flip state (today's variants do not read it) and rep["flip"] compares today's rules with the
    new ones (flip_compare). stops (11.11., rangedca/stops.py; needs flip): rep["stops"] compares the stop variants
    (a-e, be), measured only. gate_exclude (11.11.): rep["flip_gate"] = rep["flip"] without these tokens (what the
    range_flip live gate reads; the report keeps them). demo (14.11., needs flip): rep["demo"] compares today's rules
    with the demo profile rules.DEMO (DemoCompare)."""
    var = {f"{th:.1f}{'' if l2 else '_bez_lota2'}": [] for th in THRESHOLDS for l2 in (True, False)}
    var[PROXY_OFF] = []
    per = {}
    fc = FlipCompare() if flip else None
    from . import stops as _stops
    sc = _stops.StopCompare() if stops and flip else None
    dc = DemoCompare() if demo and flip else None
    t0 = time.time()
    for tok, (candles, supply, liq, sym) in series.items():
        if not candles or not supply or candles[-1][0] - candles[0][0] < detect.CFG["min_hist_h"] * 3600:
            continue
        tl = timeline(candles, supply, liq, flip=flip)
        if fc:
            fc.add(tok, sym, candles, supply, liq, tl)
        if sc:
            sc.add(tok, sym, candles, supply, liq, tl)
        if dc:
            dc.add(tok, sym, candles, supply, liq, tl)
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
        if gate_exclude:
            rep["flip_gate"] = fc.report(gate_exclude)
    if sc:
        rep["stops"] = sc.report()
    if dc:
        rep["demo"] = dc.report(gate_exclude)
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


def priced(r, liq=None, cfg=None):
    """(pnl_usd, size_usd) of a simulated round at cost(): the lots' units at their prices, the exits' fills; an open
    round valued at its last close. 14.11. popodne: each lot at its own USD (r "lot_usd": lot 1 60 % / lot 2 40 %),
    and with cfg real_fee_side the real account's cost (_rt)."""
    pxs = r.get("lot_px") or []
    size = r["cost"]
    usds = r.get("lot_usd") or ([size / len(pxs)] * len(pxs) if pxs else [])
    units = [u / px for u, px in zip(usds, pxs)]
    proceeds = 0.0
    for e in r.get("exits") or []:
        for i in range(min(len(units), e.get("n_lots") or len(units))):
            q = units[i] * e["frac"]
            proceeds += q * e["px"]
            units[i] -= q
    if not r.get("closed") and r.get("last_px"):
        proceeds += sum(q * r["last_px"] for q in units)
    rt = _rt(cfg, usds, liq) if (cfg or {}).get("real_fee_side") is not None else cost(size, liq)
    return proceeds - size - size * rt, size


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

    def report(self, exclude=()):
        """exclude (11.11.): tokens left out of the totals (the owner's labelled / pinned tokens that only a fixture
        brought into the nightly set: a label must never steer the live gate's numbers)."""
        ex = set(exclude or ())
        toks = {t: p for t, p in self.tokens.items() if t not in ex}
        hours = sorted(p["hours"] for p in toks.values())
        out = {"variants": {k: flip_summary([r for r in v if r.get("token") not in ex]) for k, v in self.rounds.items()},
               "tokens": toks,
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


# ---------- 14.11. the demo profile (rules.DEMO, flag range_demo G32) vs today's rules -----------------------------------
# The same timeline and simulate() with ticks "wick" (the live exit loop sees every second) and the ATR stop (decision
# 1, rules.new_range "atr") for both, no reclaim, every round priced at the owner's round-trip cost (priced()):
#   old         RULES (score 0.7, bottom 15 %, lot 2, half at the top zone, the rest at the top / trailing)
#   demo_1411   the morning's demo profile rules.DEMO_1411 (bottom 25 %, one lot, TP +10 / +15 % net, stop -12..-25 %)
#   dca         14.11. popodne, the owner's first order: bottom 30 % / rlt x 1.10, lot 1 60 % + DCA 40 % at -10 %, the
#               stop -20..-25 % from lot 1, half at +10 % net of the average entry, the rest +15 % / the top zone
#   demo        rules.DEMO, the scalp profile (the owner's second order, what the demo account trades): the same entry,
#               DCA and stop, the whole position at +$0.60 net, 3 min cooldown after a profit, 10 rounds a token a day
#   demo_real   the same rules at the real account's costs for a 0.1 SOL stake (rules.SCALP, real_cost: PumpSwap
#               0.3 % + route 0.1 % a side, each buy's impact, rules.TX_FEE_SOL a swap at BT_SOL_USD): what
#               pravi_novac_sve would trade
DEMO_VARIANTS = {"old": None, "demo_1411": "1411", "dca": {"tp_usd": None, "tp1_share": 0.5, "cooldown_tp_s": None,
                                                           "rounds_token_day": None},
                 "demo": {}, "demo_real": "real"}


def real_cfg(base=None, sol_usd=None, tx_sol=None):
    """The scalp profile at the real account's costs (backtest): the pool's fee (PumpSwap) + the route's a side and
    the network fee of every swap (tx_sol, default rules.TX_FEE_SOL, at sol_usd, default BT_SOL_USD)."""
    return {**(base or rules.SCALP), "real_fee_side": rules.POOL_FEE["pumpswap"] + rules.ROUTE_FEE,
            "tx_usd": (rules.TX_FEE_SOL if tx_sol is None else tx_sol) * (sol_usd or BT_SOL_USD)}


def demo_cfg(key):
    """The rule set of a DEMO_VARIANTS key (None = RULES)."""
    v = DEMO_VARIANTS[key]
    if v is None:
        return None
    if v == "1411":
        return dict(rules.DEMO_1411)
    if v == "real":
        return real_cfg()
    return {**rules.DEMO, **v}


def demo_summary(rounds, days=None):
    """flip_summary plus hit_rate (wins / closed rounds), ev_pct (the mean result per closed round, % of its cost,
    after the owner's round-trip cost), ev_usd (USD a closed round), avg_win_usd / avg_loss_usd, be_hit_rate (the hit
    rate at which the wins pay the losses: avg loss / (avg win + avg loss)), lot2 (rounds whose DCA filled, their wins
    and PnL) and, with days (token-days of data), rounds_per_token_day."""
    out = flip_summary(rounds)
    closed = [r for r in rounds if r.get("closed")]
    out["hit_rate"] = round(out["wins"] / len(closed), 3) if closed else None
    out["ev_pct"] = round(statistics.mean(r["pnl_c"] / r["cost"] for r in closed) * 100, 2) if closed else None
    out["ev_usd"] = round(statistics.mean(r["pnl_c"] for r in closed), 3) if closed else None
    w = [r["pnl_c"] for r in closed if r["pnl_c"] > 0]
    lo = [-r["pnl_c"] for r in closed if r["pnl_c"] <= 0]
    out["avg_win_usd"] = round(statistics.mean(w), 3) if w else None
    out["avg_loss_usd"] = round(statistics.mean(lo), 3) if lo else None
    out["be_hit_rate"] = (round(out["avg_loss_usd"] / (out["avg_loss_usd"] + out["avg_win_usd"]), 3)
                          if w and lo else None)
    l2 = [r for r in closed if r.get("lots") == 2]
    out["lot2"] = {"n": len(l2), "wins": sum(1 for r in l2 if r["pnl_c"] > 0),
                   "pnl_usd": round(sum(r["pnl_c"] for r in l2), 3),
                   "stops": sum(1 for r in l2 if r["reason"] == "stop")}
    if days:
        out["rounds_per_token_day"] = round(len(closed) / days, 2)
    return out


class DemoCompare:
    """Collects every DEMO_VARIANTS key per token (run_tokens), report() sums them."""

    def __init__(self):
        self.tokens, self.rounds = {}, {k: [] for k in DEMO_VARIANTS}
        self.guard = {k: {} for k in DEMO_VARIANTS}

    def add(self, tok, sym, candles, supply, liq, tl):
        per = {"symbol": sym, **data_span(candles)}
        for k in DEMO_VARIANTS:
            cfg = demo_cfg(k)
            rs = simulate(candles, supply, tl, rules._r(cfg)["score_min"], True, liq, new=("atr",), ticks="wick",
                          cfg=cfg, guard=self.guard[k])
            for r in rs:
                r["token"], r["symbol"] = tok, sym
                r["pnl_c"] = priced(r, liq, cfg)[0]
            self.rounds[k] += rs
            per[k] = demo_summary(rs, per["days"])
        self.tokens[tok] = per

    def report(self, exclude=()):
        ex = set(exclude or ())
        toks = {t: p for t, p in self.tokens.items() if t not in ex}
        hours = [p["hours"] for p in toks.values()]
        days = round(sum(hours) / 24, 2)
        return {"variants": {k: demo_summary([r for r in v if r.get("token") not in ex], days)
                             for k, v in self.rounds.items()},
                "guard": self.guard,
                "tokens": toks, "data": {"tokens": len(hours), "days_total": days},
                "rules": {"old": "RULES (0.7, donjih 15 %, lot 2, izlaz u gornjoj zoni)",
                          "demo_1411": "DEMO_1411 (0.6, donjih 25 %, TP +10/+15 % neto, stop -12..-25 %, bez lota 2)",
                          "dca": "donjih 30 % / donja zona +10 %, lot 1 60 % + DCA 40 % na -10 %, stop -20..-25 % od "
                                 "lota 1, pola na +10 % neto od prosjeka, ostatak +15 % / gornja zona",
                          "demo": "scalp: isti ulaz / DCA / stop, cijela pozicija na +$0,60 neto, cooldown 3 min nakon "
                                  "dobiti, 10 rundi po tokenu dnevno",
                          "demo_real": "scalp s troškom pravog računa (0,1 SOL: PumpSwap 0,3 % + ruta 0,1 % po strani, "
                                       f"mreža {rules.TX_FEE_SOL:g} SOL po swapu)"},
                "lot_usd": LOT_USD, "sol_usd": BT_SOL_USD,
                "ticks": "wick", "stop": "ATR (odluka 1)", "cost": "2 x fee_side + 2 x size / (liq / 2 + size)"}


def demo_line(dr):
    """The log line "range demo backtest: ..." of rep["demo"]."""
    v, d = dr["variants"], dr["data"]

    def s(x):
        if not x:
            return "-"
        return (f"runde {x['rounds']} ({x.get('rounds_per_token_day') or 0:.2f}/token-dan), pogodak "
                f"{x['hit_rate'] * 100 if x['hit_rate'] is not None else 0:.0f} % (break-even "
                f"{x['be_hit_rate'] * 100 if x.get('be_hit_rate') is not None else 0:.0f} %), EV "
                f"{x['ev_pct'] if x['ev_pct'] is not None else 0:+.2f} %/rundi "
                f"({x['ev_usd'] if x.get('ev_usd') is not None else 0:+.2f} $), PnL {x['pnl_usd']:+.2f} $, DD "
                f"{x['max_dd_usd']:.2f} $, DCA {x.get('lot2', {}).get('n', 0)}")
    return (f"range demo backtest: {d['tokens']} tokena, {d['days_total']} dana; staro: {s(v.get('old'))}; demo jutro "
            f"14.11.: {s(v.get('demo_1411'))}; DCA +10/+15 %: {s(v.get('dca'))}; scalp $0,60 (demo): "
            f"{s(v.get('demo'))}; scalp pravi trošak 0,1 SOL: {s(v.get('demo_real'))}")


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
    out = "\n".join(lines) + "\n" + (flip_md(rep["flip"]) if rep.get("flip") else "")
    if rep.get("stops"):   # 11.11. (rangedca/stops.py): the stop variants, measured; the live rule does not change
        from . import stops as _stops
        out += _stops.md(rep["stops"])
        if rep.get("stop_replay"):
            out += "\n" + _stops.replay_line(rep["stop_replay"]) + "\n"
    if rep.get("demo"):   # 14.11.: the demo profile vs today's rules
        out += "\n## Demo profil 14.11. (range_demo, scalp) vs današnja pravila\n\n" + demo_line(rep["demo"]) + "\n"
    return out


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
    memory at once would be hundreds of MB on Render). extra: {token: series} already loaded (fixture_series)."""

    def __init__(self, rcon, toks, now, days, extra=None):
        self.rcon, self.toks, self.now, self.days, self.extra = rcon, toks, now, days, extra or {}

    def __len__(self):
        return len(self.toks) + len(self.extra)

    def items(self):
        for t in self.toks:
            yield t, load(self.rcon, t, self.now, self.days)
        yield from self.extra.items()


FIXTURES_DIR = os.path.join(data.ROOT, "tests", "fixtures")


def fixture_series(tokens, path=None):
    """{token: (candles, supply, None, symbol)} from the stored GeckoTerminal candles (tests/fixtures/range_*.json.gz,
    the newest file of a token) of these tokens. 11.11.: the owner's labelled tokens (rangedca/owner.py) stay in the
    nightly backtest after range.db has pruned their minutes (HAOBIBI)."""
    import glob
    import gzip
    want, out = set(tokens or ()), {}
    if not want:
        return out
    for f in sorted(glob.glob(os.path.join(path or FIXTURES_DIR, "range_*.json.gz"))):
        try:
            with gzip.open(f, "rt") as fh:
                fx = json.load(fh)
        except (OSError, ValueError):
            continue
        if fx.get("token") in want and fx.get("candles"):
            out[fx["token"]] = (data.merge([tuple(r) for r in fx["candles"]], []), fx.get("supply"), None, fx.get("symbol"))
    return out


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
    from . import stops as _stops
    try:   # 11.11. (rangedca/owner.py): the owner's labelled and pinned tokens are always in the nightly set
        from . import owner
        keep = {lb["token"] for lb in owner.labels()} | set(owner.pin_tokens())
    except Exception:  # noqa: BLE001
        keep = set()
    rcon = data.connect()
    try:
        top_up(rcon, now, gt, days, fetch, log)
        toks = tokens_with_data(rcon, now, days)
        extra = fixture_series(sorted(keep - set(toks)))
        # 11.11. (decision 1: a label is never in a win rate / EV): the tokens only a label / pin fixture brought are
        # in the report and the stop comparison per token, never in the totals the range_flip live gate reads
        rep = run_tokens(_Lazy(rcon, toks, now, days, extra), log, gate_exclude=sorted(extra))
        fx = fixture_series([_stops.HAOBIBI])   # the live HAOBIBI round of 11.11. replayed per stop variant
        if fx:
            cs, sup, _l, _s = fx[_stops.HAOBIBI]
            rep["stop_replay"] = _stops.replay_table(cs, sup)
        fr = rep.pop("flip_gate", None) or rep.get("flip")
        if fr:   # 11.11. (range_flip G26): the old vs new numbers the live gate reads (rangedca/gate.flip_refusal)
            data.kv_put(rcon, "flip_backtest", {"ts": now, "days": days, "tokens": fr["data"]["tokens"],
                                                "data": fr["data"], "dd_ok": fr["dd_ok"], "enough": fr.get("enough", True),
                                                **fr["variants"]})
        sr = rep.get("stops")
        if sr:   # 11.11.: the stop variants, for the owner's decision (nothing reads them to trade)
            nights = [d for d in (data.kv_get(rcon, "stop_backtest_nights") or []) if isinstance(d, str)]
            day = time.strftime("%Y-%m-%d", time.gmtime(now))
            nights = (nights + ([day] if day not in nights else []))[-60:]   # the reclaim gate counts these nights
            data.kv_put(rcon, "stop_backtest_nights", nights)
            try:   # 11.11. (decision 1): the demo account's reclaim rounds next to the comparison
                from . import gate as _gate
                rec = _gate.reclaim_proof()
            except Exception:  # noqa: BLE001
                rec = None
            data.kv_put(rcon, "stop_backtest", {"ts": now, "days": days, "data": sr["data"], "vs_a": sr["vs_a"],
                                                "nights": len(nights), "paper_reclaim": rec, **sr["variants"]})
        if rep.get("demo"):   # 14.11.: the demo profile's numbers of the night (get_range_candidates / the owner)
            data.kv_put(rcon, "demo_backtest", {"ts": now, "days": days, "data": rep["demo"]["data"],
                                                **rep["demo"]["variants"]})
        rcon.commit()
    finally:
        rcon.close()
    rep["days"] = days
    path = write(rep, log)
    log(f"range backtest: {rep['tokens_simulated']} tokena, {rep['cpu_s']} s, izvještaj {path}")
    if rep.get("flip"):
        log(flip_line(rep["flip"]))
    if rep.get("stops"):
        log(_stops.line(rep["stops"], focus=sorted(keep)))
        try:   # 11.11. (decision 1): the demo reclaim rounds and the real account's reclaim gate
            from . import gate as _gate
            log(_gate.reclaim_line())
        except Exception as e:  # noqa: BLE001
            log(f"range reclaim: dokaz nije čitljiv ({type(e).__name__})")
    if rep.get("stop_replay"):
        log(_stops.replay_line(rep["stop_replay"]))
    if rep.get("demo"):
        log(demo_line(rep["demo"]))
    return rep
