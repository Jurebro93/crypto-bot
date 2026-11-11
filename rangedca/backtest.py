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
  - costs as on the demo account: 1 % fee each way and the AMM impact of a LOT_USD lot on the pool (liquidity from
    the snapshots, else BT_LIQ).
Variants: range_score threshold 0.6 / 0.7 / 0.8, with and without lot 2. Report: rounds, win rate, average result
per round (USD and % of its cost), max drawdown of the summed rounds in exit order, the worst round, every round.
Output: output/range-backtest-YYYYMMDD.json and .md, and the summary in the log ("range backtest | ...").
The transfer-holders rule is not simulated (no history of who received what).
"""
import bisect
import json
import os
import statistics
import time

from . import data, detect, rules, tier

LOT_USD = 15.0       # ~0.1 SOL, the Autopilot's size_sol
BT_LIQ = 40_000.0    # pool depth for the impact when the history has no liquidity reading
STEP_S = 300
THRESHOLDS = (0.6, 0.7, 0.8)
PROXY_OFF = "0.7_bez_proxyja"   # sensitivity: threshold 0.7 without the volume proxy of the buys share (see simulate)
FEE = 0.01


def _impact(usd, liq):
    side = (liq or BT_LIQ) / 2
    return usd / (side + usd)


def timeline(candles, supply, liq=None, step_s=STEP_S):
    """[(ts, range dict, exclusion state)] every step_s from 6 h after the first candle (variant-independent)."""
    out = []
    if not candles:
        return out
    ts = [c[0] for c in candles]
    cfg = {"supply": supply, "unknown_liq_ok": liq is None}
    snap = {"liq": liq} if liq else None
    st = {}
    t = candles[0][0] + int(detect.CFG["min_hist_h"] * 3600)
    end = candles[-1][0]
    while t <= end:
        lo = bisect.bisect_left(ts, t - int(detect.CFG["window_h"] * 3600))
        hi = bisect.bisect_right(ts, t)
        res = detect.analyze_reset(candles[lo:hi], t, snap, cfg)
        if liq:
            res["metrics"]["liq"] = liq
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


def simulate(candles, supply, tl, score_min=0.7, lot2=True, liq=None, lot_usd=LOT_USD, proxy_buys=True):
    """The rounds of one token: [{opened, closed, lots, entry_mc, lot2_mc, exits, cost, pnl, ret, reason}].
    proxy_buys False: where the candles have no transaction counts, the buys-share gate is left out (a sensitivity
    check of the proxy, reported apart; live the gate reads DexScreener's real counts)."""
    ts = [c[0] for c in candles]
    tl_ts = [x[0] for x in tl]
    rounds, pos, cool_until = [], None, 0
    for i, c in enumerate(candles):
        t = c[0]
        k = bisect.bisect_right(tl_ts, t) - 1
        if k < 0:
            continue
        _t, rng, st = tl[k]
        if pos:
            pos["lo"], pos["hi"] = min(pos["lo"], c[3]), max(pos["hi"], c[2])
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
                    be = cost_left / q / ((1 - FEE) * (1 - _impact(cost_left, liq))) if q > 0 and cost_left > 0 else None
                    hit = rules.exit_step(lv, pos["state"], px, t, pos["opened"], be)
                if not hit:
                    continue
                reason, frac = hit
                fill = lv["rhl"] if reason == "tp1" else px
                for x in pos["lots"]:
                    q = x["qty"] * frac
                    gross = q * fill
                    x["qty"] -= q
                    got = gross * (1 - FEE) * (1 - _impact(gross, liq))
                    pos["realized"] += got
                pos["exits"].append({"ts": t, "reason": reason.split(":")[0], "frac": frac,
                                     "mc": round(fill * supply) if supply else None})
                if frac >= 0.999:
                    cost = sum(x["usd"] for x in pos["lots"])
                    pnl = pos["realized"] - cost
                    rounds.append({"opened": pos["opened"], "closed": t, "lots": len(pos["lots"]),
                                   "entry_mc": pos["entry_mc"], "lot2_mc": pos.get("lot2_mc"), "exits": pos["exits"],
                                   "cost": round(cost, 4), "pnl": round(pnl, 4), "ret": round(pnl / cost, 5),
                                   "reason": reason.split(":")[0], "score": pos["score"],
                                   "low_mc": round(pos["lo"] * supply) if supply else None,
                                   "high_mc": round(pos["hi"] * supply) if supply else None,
                                   "ctx": _close_ctx(rng, st, t)})
                    pos = None
                    cool_until = t + rules.RULES["cooldown_s"]
            if pos and lot2 and len(pos["lots"]) == 1 and not pos["state"].get("tp1"):
                px = c[4]
                drop = 1 - px / pos["lot1_px"]
                if rules.RULES["lot2_lo"] - 1e-9 <= drop <= rules.RULES["lot2_hi"] + 1e-9:
                    m = _metrics_at(candles, ts, i, t, supply, proxy_buys)
                    if rules.lot2_check(pos["lot1_px"], px, lv, m) is None:
                        eff = px * (1 + FEE) / (1 - _impact(lot_usd, liq))
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
            eff = px * (1 + FEE) / (1 - _impact(lot_usd, liq))
            pos = {"opened": t, "lot1_px": px, "lots": [{"px": px, "usd": lot_usd, "qty": lot_usd / eff}], "realized": 0.0,
                   "lo": px, "hi": px,
                   "levels": lv, "state": {}, "exits": [], "entry_mc": round(px * supply), "score": rng.get("score")}
    if pos:   # still open at the end of the data: valued at the last close, marked open
        px = candles[-1][4]
        cost = sum(x["usd"] for x in pos["lots"])
        val = pos["realized"] + sum(x["qty"] * px * (1 - FEE) for x in pos["lots"])
        rounds.append({"opened": pos["opened"], "closed": None, "lots": len(pos["lots"]), "entry_mc": pos["entry_mc"],
                       "lot2_mc": pos.get("lot2_mc"), "exits": pos["exits"], "cost": round(cost, 4),
                       "pnl": round(val - cost, 4), "ret": round((val - cost) / cost, 5), "reason": "otvoreno",
                       "score": pos["score"]})
    return rounds


def _close_ctx(rng, st, t):
    """The token_tier context at a round's close from the timeline (rug history is not known: clean unless excluded)."""
    return {"score": rng.get("score"), "broken_down": bool((rng.get("signals") or {}).get("broken_down")),
            "rug_clean": (st.get("excluded_until") or 0) <= t,
            "activity": (rng.get("metrics") or {}).get("activity")}


SOL_USD_BT = 150.0   # SOL price for the 1.5 %-of-liquidity cap in history (the lot of $15 = ~0.1 SOL above)


def tier_compare(rounds, liq_of=None, fixed=None, sol_usd=SOL_USD_BT):
    """token_tier spec 8: the same closed rounds with a fixed stake (T0, 0.15 SOL) and with the tier system
    (rangedca/tier.step after every round, the stake of the next round from its tier, capped by liquidity / impact).
    A round's result in SOL = its return x the stake (the return was simulated with a ~0.1 SOL lot; a bigger lot's
    extra impact is in the cap, not in the return: slightly optimistic for the tier side). Per variant: PnL SOL,
    max drawdown SOL (all tokens summed in exit order), the biggest single loss SOL, rounds per tier."""
    szs = tier.sizes()
    fixed = fixed if fixed is not None else szs[0]
    closed = sorted((r for r in rounds if r.get("closed")), key=lambda r: r["closed"])
    states, res = {}, {"fixed": [], "tier": []}
    by_tier = {f"T{i}": 0 for i in range(4)}
    steps = []
    for r in closed:
        tok = r.get("token")
        liq = (liq_of or {}).get(tok)
        st = states.get(tok) or tier.blank()
        size, _ = tier.size(st["tier"], liq, sol_usd, szs, _impact)
        by_tier[f"T{st['tier']}"] += 1
        p_fix, p_tier = r["ret"] * fixed, r["ret"] * size
        res["fixed"].append((r["closed"], p_fix))
        res["tier"].append((r["closed"], p_tier))
        new = tier.step(st, {"pnl_sol": p_tier, "reason": r["reason"], "low_mc": r.get("low_mc"),
                             "high_mc": r.get("high_mc")}, r.get("ctx") or {})
        steps.append({"token": tok, "symbol": r.get("symbol"), "closed": r["closed"], "tier_before": st["tier"],
                      "size_sol": size, "ret": r["ret"], "pnl_sol": round(p_tier, 5), "tier_after": new["tier"],
                      "why": new["reason"]})
        states[tok] = new
    out = {}
    for k, xs in res.items():
        eq = peak = dd = 0.0
        for _t, p in xs:
            eq += p
            peak = max(peak, eq)
            dd = max(dd, peak - eq)
        out[k] = {"rounds": len(xs), "pnl_sol": round(sum(p for _t, p in xs), 4), "max_drawdown_sol": round(dd, 4),
                  "worst_round_sol": round(min((p for _t, p in xs), default=0.0), 4)}
    out["fixed"]["stake_sol"] = fixed
    out["tier"]["rounds_by_tier"] = by_tier
    out["tier"]["sizes"] = list(szs)
    out["steps"] = steps
    return out


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


def run_tokens(series, log=print):
    """series: {token: (candles, supply, liq, symbol)}. Returns the report dict."""
    var = {f"{th:.1f}{'' if l2 else '_bez_lota2'}": [] for th in THRESHOLDS for l2 in (True, False)}
    var[PROXY_OFF] = []
    per = {}
    t0 = time.time()
    for tok, (candles, supply, liq, sym) in series.items():
        if not candles or not supply or candles[-1][0] - candles[0][0] < detect.CFG["min_hist_h"] * 3600:
            continue
        tl = timeline(candles, supply, liq)
        act = [x for x in tl if x[1].get("active")]
        per[tok] = {"symbol": sym, "hours": round((candles[-1][0] - candles[0][0]) / 3600, 1), "detections": len(tl),
                    "active_detections": len(act), "best_score": max((x[1].get("score") or 0 for x in act), default=None),
                    "tx_counts": any(c[6] is not None for c in candles), "liq": liq}
        runs = [(f"{th:.1f}{'' if l2 else '_bez_lota2'}", th, l2, True) for th in THRESHOLDS for l2 in (True, False)]
        for key, th, l2, pb in runs + [(PROXY_OFF, 0.7, True, False)]:
            rs = simulate(candles, supply, tl, th, l2, liq, proxy_buys=pb)
            for r in rs:
                r["token"], r["symbol"] = tok, sym
            var[key] += rs
        per[tok]["rounds_0.7"] = [r for r in var["0.7"] if r["token"] == tok]
        per[tok]["rounds_0.7_bez_proxyja"] = [r for r in var[PROXY_OFF] if r["token"] == tok]
    rep_tier = tier_compare(var["0.7"], {t: p.get("liq") for t, p in per.items()})
    rep = {"generated_ts": int(time.time()), "tokens_with_data": len(series), "tokens_simulated": len(per),
           "tier_compare": rep_tier,
           "tokens_with_range": sum(1 for p in per.values() if p["active_detections"]),
           "cpu_s": round(time.time() - t0, 1), "lot_usd": LOT_USD,
           "variants": {k: summary(v) for k, v in var.items()}, "tokens": per}
    return rep


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
    tc = rep.get("tier_compare")
    if tc:
        lines += ["", "## Fiksni ulog vs token_tier (prag 0,7, s lotom 2)", "",
                  "| varijanta | runde | PnL SOL | max drawdown SOL | najveći gubitak runde SOL |", "|---|---|---|---|---|",
                  f"| fiksno {tc['fixed']['stake_sol']:g} SOL | {tc['fixed']['rounds']} | {tc['fixed']['pnl_sol']} | "
                  f"{tc['fixed']['max_drawdown_sol']} | {tc['fixed']['worst_round_sol']} |",
                  f"| tier {'/'.join(f'{x:g}' for x in tc['tier']['sizes'])} | {tc['tier']['rounds']} | {tc['tier']['pnl_sol']} | "
                  f"{tc['tier']['max_drawdown_sol']} | {tc['tier']['worst_round_sol']} |", "",
                  "Runde po tieru: " + ", ".join(f"{k} {v}" for k, v in tc["tier"]["rounds_by_tier"].items())]
    for key, title_ in (("rounds_0.7", "prag 0,7, s lotom 2"), ("rounds_0.7_bez_proxyja", "prag 0,7, bez proxy filtra kupnji")):
        lines += ["", f"## Runde ({title_})", ""]
        for tok, p in rep["tokens"].items():
            for r in p.get(key) or []:
                ex = ", ".join(f"{e['reason']} {e['frac']:.0%} @ {e['mc'] or 0:,.0f}" for e in r["exits"])
                lines.append(f"- {p['symbol'] or tok[:6]} {time.strftime('%d.%m. %H:%M', time.gmtime(r['opened']))} UTC: "
                             f"ulaz MC {r['entry_mc']:,.0f}" + (f", lot 2 {r['lot2_mc']:,.0f}" if r.get("lot2_mc") else "")
                             + f"; izlazi: {ex or '-'}; {r['ret'] * 100:+.1f} % ({r['reason']})")
    return "\n".join(lines) + "\n"


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
    finally:
        rcon.close()
    rep["days"] = days
    path = write(rep, log)
    log(f"range backtest: {rep['tokens_simulated']} tokena, {rep['cpu_s']} s, izvještaj {path}")
    return rep
