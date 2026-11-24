"""The midcap range backtest and walk-forward (run_veliki.py once / night; read-only on everything but veliki.db).

Data: veliki.db c1h (GeckoTerminal 1h, the top 40 of the list + 20 tokens that fell out of it: survivorship) and c1d
(daily, every token: the categories, metrics.py), BTC hourly / daily (DefiLlama). The rule trades 1h bars.

Universe point in time (the critic): a token enters only while ITS MC at that hour was 5-150M (today's MC x the price
then / now) and it was older than 15 days; the tokens that later died stay in (store.hist).
Three BTC variants (the owner 15.11. popodne: "krivo je stati s ulazima nakon pada BTC-a ... kad nađe dno i volumen
raste, to je signal za POČETI kupovati"):
  dno          THE live rule: no entry in a BTC free fall (rule.Crash.regime "slobodan_pad"), the range rule when
               normal, and while the bottom forms also a bounce with token inflow (LIVE_VARIANT)
  zabrana      no NEW entry while a crash lasts (4 h <= -3 % or 24 h <= -5 %); open positions keep their losses
  bez_filtra   no BTC rule
Grid (rule.GRID, small): target net +8 / 15 / 25 % with / without a 5 % trailing after it x time stop 3 / 7 days x zone
window 7 / 14 days, the owner's stop -20 %; at 0.5 SOL also -10 / -15 % and the ATR stop (below the support by 2 ATR,
at most -20 %), and the holdout's picks with DCA at -10 % (off by default), the stop at the bar's low, and the entry only
after BTC turned up. Sizes 0.1 / 0.5 / 1.0 SOL.
Walk-forward (no look-ahead): anchored, TRAIN_D (10) days train only, then blocks of FOLD_D (5) days; before each block
the config with the best EV on the trades CLOSED before it (n >= MIN_TRAIN_N) is picked, only its trades inside the
block count. Numbers (the critic): n, per day, hit, EV % / $, CI90 by token-day, CI90 / CI95 blocked by DAY, EV at
doubled costs, leave-one-token-out, profit factor, max drawdown, worst 5 %, MAE / MFE, hold time, per token, per BTC
regime, per age bucket (16-30 / 31-90 / > 90 d), trades on tokens that later fell out.
The live rule = the best configuration of "dno" on ALL days at the demo size (kv rule); the proof (kv proof) = the
holdout per size of "dno" (gate.py reads the real size).
15.11. (vlasnik: DCA, razlozi za izlaz, makro, više tradeova): VARIANTS on the holdout's own picks at the demo and the
real size: the plain pick (half at the target when it trails), the old whole-position trailing, DCA without / with the
smart conditions (-10 %, the zone's low, 3 x ATR), the reasoned exits, the macro filter (makro.daily_regimes from
market.db, day d from the days before it), all together, the wider entry (adopted live only when the holdout allows:
more trades, EV > 0 and within 0.5 pp of the plain pick's); n, EV, CI95 by day, max drawdown, worst, the DCA lots and
the exit reasons. The intraday rule (intra.py) replayed on the 15m candles at 0.1 SOL (intra_replay).
"""
import json
import os
import random
import time

from veliki import rule, store

PREFIX = "veliki: "
BUDGET_S = int(os.environ.get("VEL_BUDGET_S", "900"))
TRAIN_D = 10
FOLD_D = 5
MIN_TRAIN_N = 15
MIN_ALL_N = 30
B = 1000
DEMO_SIZE = float(os.environ.get("VEL_DEMO_SOL", "0.5"))
LIVE_VARIANT = "dno"   # the owner's correction 15.11. popodne: buy when BTC's bottom forms, never in a free fall
D = 86400


def sol_now():
    try:
        from trade import equity
        v = equity.sol_usd_cached()
        if v and v > 0:
            return float(v)
    except Exception:  # noqa: BLE001
        pass
    return rule.SOL_USD


# ---------- regime labels --------------------------------------------------------------------------------------------

class Regime:
    """market/makro's BTC state known at ts (its own _state on the daily closes up to that day + the 4 h change)."""

    def __init__(self, btc_d, btc_h):
        self.d = sorted(btc_d)
        self.h = sorted(btc_h)
        self._c = {}

    def at(self, ts):
        import bisect
        from market import makro
        key = int(ts) // 3600
        if key in self._c:
            return self._c[key]
        day = int(ts) // D * D
        i = bisect.bisect_right([x[0] for x in self.d], day)
        closes = self.d[:i]
        hts = [x[0] for x in self.h]
        j1 = bisect.bisect_right(hts, int(ts)) - 1
        j0 = bisect.bisect_left(hts, int(ts) - 4 * 3600)
        drop = self.h[j1][1] / self.h[j0][1] - 1 if 0 <= j0 < j1 else None
        s, _f = makro._state(closes, makro.DEFAULT, drop) if len(closes) >= 31 else (None, {})
        self._c[key] = s or "nepoznato"
        return self._c[key]


# ---------- stats ----------------------------------------------------------------------------------------------------

def boot_ci(trades, b=B, seed=7, by="token_day", q=0.05):
    """The (q, 1 - q) interval of EV % a trade (sum ret / sum n). by "token_day": resample (token, day) groups;
    by "day": resample calendar days with ALL their trades (the critic: simultaneous trades of memecoins that move
    together are not independent, so the day is the block)."""
    g = {}
    for x in trades:
        k = (x["token"], x["ts"] // D) if by == "token_day" else x["ts"] // D
        s = g.setdefault(k, [0.0, 0])
        s[0] += x["ret"]
        s[1] += 1
    groups = list(g.values())
    if len(groups) < 3:
        return None
    rnd = random.Random(seed)
    out = []
    for _ in range(b):
        sr = sn = 0
        for _k in range(len(groups)):
            s = groups[rnd.randrange(len(groups))]
            sr += s[0]
            sn += s[1]
        out.append(sr / sn * 100 if sn else 0.0)
    out.sort()
    return [round(out[int(q * b)], 3), round(out[int((1 - q) * b) - 1], 3)]


def max_dd(trades):
    eq = peak = dd = 0.0
    for x in sorted(trades, key=lambda x: x["out_ts"]):
        eq += x["pnl"]
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    return round(dd, 2)


def _med(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else None


def stats(trades, days, size_usd, names=None):
    """The holdout's numbers (the critic's list): n, per_day, hit, EV % / $, CI90 by token-day, CI90 / CI95 by day
    (the pass criterion), EV at DOUBLED modeled costs, leave-one-token-out (the worst EV without one token), profit
    factor, max drawdown, the worst 5 % of trades, MAE / MFE, hold time."""
    s = rule.summary(trades)
    n = s["n"]
    s.update({"days": days, "per_day": round(n / days, 2) if days else None,
              "usd_day": round(s["pnl_usd"] / days, 3) if days else None, "max_dd_usd": max_dd(trades) if n else 0.0,
              "ci90_ev_pct": boot_ci(trades) if n else None, "size_usd": round(size_usd, 2),
              "ci90_day_pct": boot_ci(trades, by="day") if n else None,
              "ci95_day_pct": boot_ci(trades, by="day", q=0.025) if n else None,
              "token_days": len({(x["token"], x["ts"] // D) for x in trades})})
    if n:
        r2 = [x["fx"] * (1 - 2 * x["rt"]) - 1 for x in trades]
        s["ev_2x_cost_pct"] = round(sum(r2) / n * 100, 3)
        gains = sum(x["pnl"] for x in trades if x["pnl"] > 0)
        loss = -sum(x["pnl"] for x in trades if x["pnl"] < 0)
        s["profit_factor"] = round(gains / loss, 3) if loss > 0 else None
        rets = sorted(x["ret"] for x in trades)
        k = max(1, int(round(0.05 * n)))
        s["worst5_pct"] = round(sum(rets[:k]) / k * 100, 2)
        s["mae_med_pct"] = round(_med([x["mae"] for x in trades]) * 100, 2)
        s["mfe_med_pct"] = round(_med([x["mfe"] for x in trades]) * 100, 2)
        s["hold_med_h"] = _med([x["hours"] for x in trades])
        toks = {x["token"] for x in trades}
        loto = {}
        for t in toks:
            rest = [x["ret"] for x in trades if x["token"] != t]
            if rest:
                loto[(names or {}).get(t, t[:6])] = round(sum(rest) / len(rest) * 100, 3)
        s["loto_min_pct"] = min(loto.values()) if loto else None
        s["loto_min_without"] = min(loto, key=loto.get) if loto else None
    return s


def by_key(trades, key):
    out = {}
    for x in trades:
        out.setdefault(key(x), []).append(x)
    return {k: {"n": len(v), "hit": round(sum(1 for x in v if x["ret"] > 0) / len(v), 3),
                "ev_pct": round(sum(x["ret"] for x in v) / len(v) * 100, 3), "pnl_usd": round(sum(x["pnl"] for x in v), 2)}
            for k, v in sorted(out.items(), key=lambda kv: -len(kv[1]))}


# ---------- the computation ------------------------------------------------------------------------------------------

def pit_of(row, bars):
    """The point-in-time universe of a token (the critic): at time t with close c its MC was mcap_now x c / c_last
    (the same supply) and its age t - created; it qualifies while MC is MIN..MAX and age > MIN_AGE_D."""
    from veliki import universe
    c_last = bars[-1][4] if bars else None
    mc = row.get("mcap") or 0
    born = row.get("created_ts") or (bars[0][0] if bars else 0)
    if not c_last or not mc:
        return None

    def ok(t, c):
        m = mc * c / c_last
        return universe.MIN_MCAP <= m <= universe.MAX_MCAP and (t - born) / D > universe.MIN_AGE_D
    return ok


def load(con, with_history=True):
    """{mint: {"bars" (1h), "h1", "daily", "liq", "dex", "symbol", "row", "dead"}} of the list (and the history-only
    tokens that fell out: survivorship), BTC hourly / daily."""
    series = {}
    rows = store.tokens(con) + (store.history_rows(con) if with_history else [])
    for r in rows:
        bars = store.candles(con, "c1h", r["mint"])
        daily = store.candles(con, "c1d", r["mint"])
        series[r["mint"]] = {"bars": bars, "h1": bars, "daily": daily, "liq": r.get("liq"),
                             "dex": r.get("dex") or r.get("url"), "symbol": r.get("symbol"), "row": r,
                             "dead": bool(r.get("dead")), "b15": store.candles(con, "c15", r["mint"])}
    return series, store.btc_hourly(con), store.btc_daily(con)


def categories(series, btc_h, btc_d, now, crash=None):
    """{mint: metrics.compute(...)} of every token with daily candles."""
    from veliki import metrics
    out = {}
    for m, s in series.items():
        if not s.get("daily"):
            continue
        try:
            out[m] = metrics.compute(s["daily"], s["h1"], btc_d, btc_h, (s["row"] or {}).get("created_ts"), now, crash)
        except Exception as e:  # noqa: BLE001 - one token's bad data never stops the table
            out[m] = {"error": type(e).__name__, "cat": "C", "score": -9}
        out[m].update(symbol=s["symbol"], mcap=(s["row"] or {}).get("mcap"), dead=s.get("dead"))
    return out


def compute(series, btc_h, btc_d, now=None, log=print, budget_s=BUDGET_S, sol_usd=None, sizes=rule.SIZES_SOL,
            grid=None, stops=tuple(rule.STOPS), cats=None, macro_days=None, index_days=None):
    now = int(now or time.time())
    t_end = time.time() + budget_s
    sol = sol_usd or sol_now()
    crash = rule.crash_of(btc_h)
    if macro_days is None:
        try:
            from veliki import makro
            macro_days = makro.daily_regimes(series, crash)
        except Exception:  # noqa: BLE001 - no market.db: the variants without the macro regime
            macro_days = {}
    if index_days is None:   # 15.11. (makroinf/): the macro influencers' index over the macro regime, if there is one
        try:
            from makroinf import index as mindex
            ov = mindex.veliki_overlay()
            index_days = mindex.overlay_days(ov[1], ov[0], macro_days) if ov else {}
        except Exception:  # noqa: BLE001 - no makroinf.db: no "makro_indeks" variant
            index_days = {}
    reg = Regime(btc_d, btc_h)
    names = {m: s["symbol"] for m, s in series.items()}
    tradable = {m: s for m, s in series.items() if len(s["bars"]) >= 200}
    looks = sorted(set((grid or {}).get("look_d") or rule.GRID["look_d"]))
    tx = rule.tx_sol()[0]
    days_all = sorted({b[0] // D for s in tradable.values() for b in s["bars"]})
    variants = {LIVE_VARIANT: crash, "zabrana": crash, "bez_filtra": None}
    vmode = {"dno": "dno", "zabrana": "zabrana", "bez_filtra": "bez"}
    cands = {}
    for v, cr in variants.items():
        for m, s in tradable.items():
            zs = rule.Zones(s["h1"], cr)
            pit = pit_of(s["row"] or {}, s["bars"])
            for lk in looks:
                cands[(v, m, lk)] = rule.candidates(s["bars"], zs, lk, cr, {"crash_filter": cr is not None,
                                                                             "btc_mode": vmode[v]}, pit)
    out = {"ts": now, "sol_usd": round(sol, 2), "tx_sol": tx, "days": len(days_all), "tokens": len(tradable),
           "dead_included": sum(1 for s in tradable.values() if s.get("dead")),
           "crash_periods": [[a, b] for a, b in crash.periods if a >= (days_all[0] * D if days_all else 0)],
           "variants": {}, "costs": {}, "grid_n": len(rule.configs(grid)), "stops": {}}
    for size in sizes:
        out["costs"][f"{size:g}"] = {s["symbol"]: round(rule.cost_at(size, s["liq"], sol, rule.fee_side_of(s["dex"]),
                                                                      tx)["rt"] * 100, 3) for s in tradable.values()}
    if len(days_all) < TRAIN_D + 2:
        out["note"] = f"premalo dana ({len(days_all)}): walk-forward treba barem {TRAIN_D + 2}"
    folds = []
    k = TRAIN_D
    while k < len(days_all):
        folds.append((days_all[k], days_all[min(k + FOLD_D, len(days_all)) - 1] + 1))
        k += FOLD_D
    test_days = sum(b - a for a, b in folds)
    out["test_days"] = test_days

    def walk_one(v, cr, size, stop):
        usd = size * sol
        per_cfg = {}
        for c in rule.configs(grid, stop):
            cc = {**c, "crash_filter": cr is not None, "btc_mode": vmode[v]}
            trs = []
            for m, s in tradable.items():
                cost = rule.cost_at(size, s["liq"], sol, rule.fee_side_of(s["dex"]), tx)["rt"]
                drt = rule.demo_rt(usd, s["liq"])
                for x in rule.simulate(s["bars"], cands[(v, m, c["look_d"])], usd, cost, cc, drt, crash=crash):
                    x["token"] = m
                    x["day"] = x["ts"] // D
                    trs.append(x)
            per_cfg[rule.cfg_key(c)] = (c, trs)
        picks, hold = [], []
        for a, b in folds:
            best = None
            for key, (c, trs) in per_cfg.items():
                tr = [x for x in trs if x["day"] < a and x["out_ts"] <= a * D]   # only trades CLOSED before the block
                if len(tr) < MIN_TRAIN_N:
                    continue
                ev = sum(x["ret"] for x in tr) / len(tr)
                if best is None or ev > best[0]:
                    best = (ev, key, len(tr))
            if best is None:
                picks.append({"from": a * D, "to": b * D, "pick": None})
                continue
            te = [x for x in per_cfg[best[1]][1] if a <= x["day"] < b]
            hold += te
            picks.append({"from": a * D, "to": b * D, "pick": best[1], "train_n": best[2],
                          "train_ev_pct": round(best[0] * 100, 3), "test_n": len(te)})
        st = stats(hold, test_days, usd, names)
        st["folds"] = picks
        st["worst_trade"] = ({"token": names[min(hold, key=lambda x: x["ret"])["token"]],
                              "ret_pct": round(min(x["ret"] for x in hold) * 100, 2)} if hold else None)
        st["per_token"] = {names[m]: d for m, d in by_key(hold, lambda x: x["token"]).items()}
        st["by_regime"] = by_key(hold, lambda x: reg.at(x["ts"]))
        st["crash_overlap_n"] = sum(1 for x in hold if x.get("crash_overlap"))
        best_all = None
        for key, (c, trs) in per_cfg.items():
            if len(trs) >= MIN_ALL_N:
                ev = sum(x["ret"] for x in trs) / len(trs)
                if best_all is None or ev > best_all[0]:
                    best_all = (ev, key, len(trs), c)
        st["best_all"] = ({"cfg": best_all[3], "key": best_all[1], "n": best_all[2],
                           "ev_pct": round(best_all[0] * 100, 3)} if best_all else None)
        st["grid_top"] = sorted(({"key": k2, "n": len(t2), "ev_pct": round(sum(x["ret"] for x in t2) / len(t2) * 100, 3)}
                                 for k2, (_c2, t2) in per_cfg.items() if len(t2) >= MIN_TRAIN_N),
                                key=lambda r: -r["ev_pct"])[:8]
        return st, picks, per_cfg, hold

    for v, cr in variants.items():
        vo = out["variants"].setdefault(v, {})
        for size in sizes:
            if time.time() > t_end:
                vo[f"{size:g}"] = {"error": "vremenski budžet potrošen"}
                continue
            st, picks, per_cfg, hold = walk_one(v, cr, size, "pct20")
            if v == LIVE_VARIANT and abs(size - DEMO_SIZE) < 1e-9 and hold:
                st["variants_holdout"] = _variants(tradable, cands, picks, per_cfg, folds, size * sol, sol, tx, crash,
                                                   test_days, names, cats, macro_days, index_days)
            if v == LIVE_VARIANT and abs(size - min(sizes)) < 1e-9 and hold and size != DEMO_SIZE:
                st["variants_holdout"] = _variants(tradable, cands, picks, per_cfg, folds, size * sol, sol, tx, crash,
                                                   test_days, names, cats, macro_days, index_days)
                st["by_age"] = by_key(hold, lambda x: _age_k(series[x["token"]], x["ts"]))
                st["dead_n"] = sum(1 for x in hold if series[x["token"]].get("dead"))
            vo[f"{size:g}"] = st
            log(PREFIX + line_size(v, size, st))
    # the owner's -20 % against -10 / -15 % and the ATR stop, the live variant at the demo size
    for stop in stops:
        if stop == "pct20" or time.time() > t_end:
            continue
        st, _p, _pc, _h = walk_one(LIVE_VARIANT, crash, DEMO_SIZE, stop)
        out["stops"][stop] = {f: st.get(f) for f in ("n", "hit", "ev_pct", "ci95_day_pct", "usd_day", "max_dd_usd",
                                                     "profit_factor", "worst5_pct")}
    if out["stops"]:
        log(PREFIX + "stopovi (0,5 SOL, pravilo dna BTC-a): " + "; ".join(
            f"{k} n={x['n']} EV {_pct(x['ev_pct'])}" for k, x in out["stops"].items()))
    bp = out["variants"].get(LIVE_VARIANT) or {}
    demo = (bp.get(f"{DEMO_SIZE:g}") or {}).get("best_all")
    out["live_rule"] = ({**demo["cfg"], "key": demo["key"], "n_all": demo["n"], "ev_all_pct": demo["ev_pct"],
                         "size_sol": DEMO_SIZE} if demo else None)
    # 15.11. (vlasnik: "cilj je VIŠE tradeova"): the wider entry goes live only where the holdout allows it: more
    # trades AND an EV still > 0 and not more than 0.5 pp under the plain pick's
    vh = ((bp.get(f"{DEMO_SIZE:g}") or {}).get("variants_holdout") or {})
    w, o = vh.get("siri_ulaz") or {}, vh.get("osnovno") or {}
    if out["live_rule"] and w.get("n") and o.get("n") and w["n"] > o["n"] and (w.get("ev_pct") or -1) > 0 \
            and (w.get("ev_pct") or -1) >= (o.get("ev_pct") or 0) - 0.5:
        out["live_rule"].update(near=0.04, touch_bars=6, wide=True)
    out["macro_days"] = {"n": len(macro_days), "by": {k: sum(1 for x in macro_days.values() if x == k)
                                                       for k in ("risk_on", "neutral", "risk_off")}}
    if time.time() < t_end:
        out["intra"] = intra_replay(series, crash, sol, tx)
        if out["intra"].get("n"):
            log(PREFIX + "dnevni raspon (replay 15m, 0,1 SOL): " + intra_text(out["intra"]))
    out["proof"] = {"ts": now, "days": len(days_all), "test_days": test_days,
                    "sizes": {s: {f: x.get(f) for f in ("n", "ev_pct", "ev_usd", "ci90_ev_pct", "ci95_day_pct",
                                                        "ev_2x_cost_pct", "loto_min_pct", "usd_day", "hit",
                                                        "max_dd_usd", "per_day", "token_days", "profit_factor")}
                              for s, x in bp.items() if isinstance(x, dict) and "n" in x}}
    return out


def _age_k(s, ts):
    from veliki import metrics
    born = (s.get("row") or {}).get("created_ts") or (s["bars"][0][0] if s["bars"] else ts)
    return metrics.age_bucket_critic((ts - born) / D)


VARIANTS = (
    # 15.11. (vlasnik: "uključi DCA ... zatvaraju se tradeovi gdje postoji dobar razlog ... makro"; the critic's exit):
    # each on the holdout's own picks (no new choice), against the plain pick ("osnovno": half at the target when the
    # pick trails)
    ("osnovno", {}, False),
    ("cijeli_trailing", {"half": 0.0}, False),           # the old exit: the whole position trails from the target
    ("dca_10_bez_uvjeta", {"dca": 0.10}, False),         # the old DCA: every -10 % dip
    ("dca_10", {"dca": 0.10}, True),                     # the smart DCA (rule.dca_refusal: BTC, macro, A/B, bounces)
    ("dca_zona", {"dca_mode": "zona"}, True),
    ("dca_atr", {"dca_mode": "atr"}, True),
    ("razlozi", {"reasoned": True}, True),               # the reasoned exits (BTC free fall, macro, volume)
    ("makro_filter", {"macro_filter": True}, True),      # no entry while the macro regime is risk_off
    ("sve", {"dca": 0.10, "reasoned": True, "macro_filter": True}, True),
    ("siri_ulaz", {"near": 0.04, "touch_bars": 6}, False),   # more trades: a wider touch of the support
    ("stop_na_dnu_svijece", {"stop_fill": "low"}, False),
    ("btc_okrenut_gore", {"btc_up": True}, False),
)


def _variants(series, cands, picks, per_cfg, folds, usd, sol, tx, crash, test_days, names=None, cats=None,
              macro_days=None, index_days=None):
    """The holdout's picks re-run with each VARIANTS change (DCA on / off and its trigger, the reasoned exits, the
    macro filter, the old whole-position trailing, the stop at the bar's low, the entry only after BTC turned up):
    n, EV, CI95 by day, $ a day, max drawdown, worst trade, the worst 5 %, the DCA lots bought and the exit reasons.
    15.11. (makroinf/): with index_days ({day: regime}: the macro regime, risk_off also on the days the macro
    influencers' top index was bearish, known at the day's start) one more variant "makro_indeks" = "makro_filter" with
    that regime: the incremental EV of the index on the same locked strategy (makroinf/index.incremental_ev)."""
    res = {}
    mfn = (lambda t: (macro_days or {}).get(int(t) // D)) if macro_days else None
    vols = {m: rule.vol_ratios(s["bars"]) for m, s in series.items()}
    wide = {}
    vlist = [(n_, e_, s_, mfn) for n_, e_, s_ in VARIANTS]
    if index_days:
        vlist.append(("makro_indeks", {"macro_filter": True}, True, lambda t: index_days.get(int(t) // D)))
    for name, extra, smart, mf in vlist:
        hold = []
        for p, (a, b) in zip(picks, folds):
            if not p.get("pick"):
                continue
            c = per_cfg[p["pick"]][0]
            cc = {**c, "crash_filter": True, "btc_mode": "dno", "tx_frac": tx * sol / usd, **extra}
            for m, s in series.items():
                cs = cands[(LIVE_VARIANT, m, c["look_d"])]
                if "near" in extra or "touch_bars" in extra:   # the entry itself changes: its own candidates
                    k2 = (m, c["look_d"])
                    if k2 not in wide:
                        wide[k2] = rule.candidates(s["bars"], rule.Zones(s["h1"], crash), c["look_d"], crash,
                                                   {"crash_filter": True, "btc_mode": "dno", **extra},
                                                   pit_of(s["row"] or {}, s["bars"]))
                    cs = wide[k2]
                cost = rule.cost_at(usd / sol, s["liq"], sol, rule.fee_side_of(s["dex"]), tx)["rt"]
                cost2 = rule.cost_at(usd / sol, s["liq"], sol, rule.fee_side_of(s["dex"]), tx, lots=2)["rt"]
                k = (cats or {}).get(m) or {}
                ctx = {"macro": mf, "cat": k.get("cat"), "metrics": k, "vol": vols.get(m)} if smart else None
                for x in rule.simulate(s["bars"], cs, usd, cost, cc, crash=crash, t0=a * D, t1=b * D, rt2=cost2,
                                       ctx=ctx):
                    x["token"] = m
                    hold.append(x)
        st = stats(hold, test_days, usd, names)
        res[name] = {f: st.get(f) for f in ("n", "hit", "ev_pct", "ci95_day_pct", "usd_day", "max_dd_usd",
                                            "profit_factor", "worst5_pct", "worst_pct", "reasons")}
        res[name]["dca_n"] = sum(1 for x in hold if x.get("dca"))
        res[name]["half_n"] = sum(1 for x in hold if x.get("half"))
    return res


def intra_replay(series, crash, sol, tx, size=0.1):
    """The intraday rule (veliki/intra.py) replayed on every token's 15m GeckoTerminal bars at 0.1 SOL and its real
    cost: n, a day, hit, EV, $ a day, max drawdown, worst, the exit reasons, the +10 % trades."""
    from veliki import intra
    trs, days = [], set()
    for m, s in series.items():
        b15 = s.get("b15") or []
        if len(b15) < 4 * 24:
            continue
        rt = rule.cost_at(size, s["liq"], sol, rule.fee_side_of(s["dex"]), tx)["rt"]
        for x in intra.simulate(b15, s.get("h1"), rt, size * sol, {"tx_frac": tx / size}, crash):
            x["token"] = m
            trs.append(x)
        days |= {b[0] // D for b in b15}
    st = stats(trs, len(days), size * sol) if trs else {"n": 0}
    st["ten_n"] = sum(1 for x in trs if x["ret"] >= 0.10)
    st["half_n"] = sum(1 for x in trs if x.get("half"))
    return {f: st.get(f) for f in ("n", "days", "per_day", "hit", "ev_pct", "usd_day", "max_dd_usd", "worst_pct",
                                   "ci95_day_pct", "reasons", "ten_n", "half_n")}


def intra_text(x):
    return (f"n={x.get('n')} ({x.get('per_day')}/dan), pogodak {x.get('hit')}, EV {_pct(x.get('ev_pct'))}, $/dan "
            f"{x.get('usd_day')}, max pad {x.get('max_dd_usd')} $, najgori {x.get('worst_pct')} %, ≥ +10 %: "
            f"{x.get('ten_n')}, pola na cilju {x.get('half_n')}, izlazi {x.get('reasons')}")


def variants_line(vh):
    return "varijante (holdout): " + "; ".join(
        f"{k} n={x.get('n')} EV {_pct(x.get('ev_pct'))} max pad {x.get('max_dd_usd')} $ najgori {x.get('worst_pct')} %"
        + (f" DCA {x['dca_n']}" if x.get("dca_n") else "") for k, x in vh.items())


def _pct(x):
    return "—" if x is None else f"{x:+.2f} %"


VNAME = {"dno": "kupnja na dnu BTC-a (bez ulaza u slobodnom padu)", "zabrana": "s zabranom ulaza tijekom pada BTC-a",
         "bez_filtra": "bez BTC pravila"}


def line_size(v, size, st):
    if "n" not in st:
        return f"backtest {size:g} SOL ({VNAME.get(v, v)}): {st.get('error')}"
    ci = st.get("ci95_day_pct")
    return (f"backtest {size:g} SOL ({VNAME.get(v, v)}): n={st['n']} ({st.get('per_day')}/dan), EV "
            f"{_pct(st.get('ev_pct'))} ({st.get('ev_usd')} $), CI95 po danu [{ci[0] if ci else '—'}; "
            f"{ci[1] if ci else '—'}], uz 2x trošak {_pct(st.get('ev_2x_cost_pct'))}, bez jednog tokena najmanje "
            f"{_pct(st.get('loto_min_pct'))}, $/dan {st.get('usd_day')}, pogodak {st.get('hit')}, PF "
            f"{st.get('profit_factor')}, max pad {st.get('max_dd_usd')} $, najgorih 5 % {st.get('worst5_pct')} %, MAE/MFE "
            f"{st.get('mae_med_pct')}/{st.get('mfe_med_pct')} %, drži {st.get('hold_med_h')} h")


def regime_line(st):
    br = st.get("by_regime") or {}
    return "po režimu BTC: " + ("; ".join(f"{k} n={v['n']} EV {_pct(v['ev_pct'])}" for k, v in br.items()) or "—")


# ---------- report ---------------------------------------------------------------------------------------------------

def markdown(data):
    if not data:
        return "# Veliki tokeni — range\n\nJoš nema izračuna (run_veliki.py once).\n"
    L = ["# Veliki tokeni — range", "",
         f"Izračun {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(data.get('ts') or 0))}: {data.get('tokens')} tokena, "
         f"{data.get('days')} dana 1h svijeća (uz {data.get('dead_included', 0)} ispalih tokena), SOL ${data.get('sol_usd')}, mreža {data.get('tx_sol')} SOL po swapu, "
         f"mreža konfiguracija {data.get('grid_n')}.", ""]
    if data.get("note"):
        L += [f"**{data['note']}**", ""]
    bn = data.get("btc_now") or {}
    if bn:
        L += [f"**BTC sada:** {bn.get('state')} — {bn.get('why')}", ""]
    tab = data.get("table") or []
    if tab:
        from veliki import metrics
        L += ["## Tablica (kategorije)", "", "A = " + metrics.CAT_TEXT["A"][3:] + "; B = " + metrics.CAT_TEXT["B"][3:]
              + "; C = " + metrics.CAT_TEXT["C"][3:] + ". Stalnost = udio dana s volumenom ≥ $50k; odbijanja = dani na "
              "dnu 30-dnevnog raspona (ne na dan pada BTC-a) nakon kojih je vrh u 7 dana bio ≥ +15 %.", "",
              "| # | token | kat. | MC | starost | stalnost 30 / 90 d | CV vol. 30 d | beta / korel. BTC dnevno | 4 h | "
              "od ATH | nakon BTC +3 % (24 / 72 h) | odbijanja n / +15 % / med. gore / med. dolje |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for i, x in enumerate(tab, 1):
            L.append(f"| {i} | {x.get('symbol')} | {x.get('cat')} | ${(x.get('mcap') or 0) / 1e6:,.1f}M | "
                     f"{x.get('age_d')} d ({x.get('age_bucket')}) | {x.get('pers30')} / {x.get('pers90')} | {x.get('cv30')} | "
                     f"{x.get('beta_d')} / {x.get('corr_d')} | {x.get('beta_4h')} / {x.get('corr_4h')} | "
                     f"{_pct((x.get('dd_ath') or 0) * 100) if x.get('dd_ath') is not None else '—'} | "
                     f"{x.get('btc_up_24h')} / {x.get('btc_up_72h')} % (n {x.get('btc_up_n')}) | {x.get('bounce_n')} / "
                     f"{x.get('hit15')} / {x.get('med_up7')} % / {x.get('med_dn7')} % |")
        L.append("")
    oor = data.get("out_of_range") or []
    if oor:
        L += ["**Izvan raspona MC (5-200M) ili bez pravog poola:** " + "; ".join(oor), ""]
    lst = data.get("list") or []
    if lst:
        L += ["## Lista", "", "| token | MC | likvidnost (sve / najdublji) | volumen 24 h | starost | 1d / 1h dana | kako |",
              "|---|---|---|---|---|---|---|"]
        cov = data.get("coverage") or {}
        for r in lst:
            c = cov.get(r["mint"]) or {}
            L.append(f"| {r['symbol']} | ${(r.get('mcap') or 0) / 1e6:,.0f}M | ${(r.get('liq_total') or 0) / 1e6:,.1f}M / "
                     f"${(r.get('liq') or 0) / 1e6:,.2f}M | ${(r.get('vol24') or 0) / 1e6:,.1f}M | {r.get('age_d')} d | "
                     f"{c.get('d1d', 0)} / {c.get('d1h', 0)} | {r.get('how') or ''} |")
        L.append("")
    cp = data.get("crash_periods") or []
    L += ["## Padovi BTC-a (4 h ≤ −3 % ili 24 h ≤ −5 %)", "",
          ("; ".join(f"{time.strftime('%d.%m. %H h', time.gmtime(a))} – "
                     f"{time.strftime('%d.%m. %H h', time.gmtime(b)) if b else 'traje'}" for a, b in cp) or "nijedan"), ""]
    L += ["## Trošak runde (pravi: pool + Jupiter + mreža, % uloga)", "", "| veličina | " + " | ".join(
        next(iter((data.get("costs") or {}).values()), {}).keys()) + " |",
          "|---|" + "---|" * len(next(iter((data.get("costs") or {}).values()), {}))]
    for s, row in (data.get("costs") or {}).items():
        L.append(f"| {s} SOL | " + " | ".join(f"{v:.2f}" for v in row.values()) + " |")
    L.append("")
    for v, sizes in (data.get("variants") or {}).items():
        L += [f"## Walk-forward: {VNAME.get(v, v)}", ""]
        for s, st in sizes.items():
            L.append("- " + line_size(v, float(s), st))
        ref = sizes.get(f"{DEMO_SIZE:g}") or {}
        if ref.get("by_regime"):
            L.append(f"- {DEMO_SIZE:g} SOL " + regime_line(ref))
        if ref.get("folds"):
            L.append("- odabir po bloku: " + "; ".join(f"{time.strftime('%d.%m.', time.gmtime(p['from']))} {p.get('pick')} "
                                                       f"(trening n {p.get('train_n')}, EV {p.get('train_ev_pct')} %, test n "
                                                       f"{p.get('test_n')})" for p in ref["folds"]))
        if ref.get("variants_holdout"):
            for k, x in ref["variants_holdout"].items():
                L.append(f"- varijanta {k}: n {x.get('n')}, EV {_pct(x.get('ev_pct'))}, CI95 po danu "
                         f"{x.get('ci95_day_pct')}, $/dan {x.get('usd_day')}, max pad {x.get('max_dd_usd')} $, najgori "
                         f"{x.get('worst_pct')} %, DCA lotova {x.get('dca_n')}, pola na cilju {x.get('half_n')}, izlazi "
                         f"{x.get('reasons')}")
        if ref.get("by_age"):
            L.append("- po starosti tokena: " + "; ".join(f"{k} n={x['n']} EV {_pct(x['ev_pct'])}"
                                                         for k, x in ref["by_age"].items()))
        if ref.get("dead_n") is not None:
            L.append(f"- tradeova na tokenima koji su kasnije ispali s liste: {ref['dead_n']}")
        if ref.get("per_token"):
            L += ["", f"| token ({DEMO_SIZE:g} SOL) | n | pogodak | EV % | PnL $ |", "|---|---|---|---|---|"]
            L += [f"| {k} | {x['n']} | {x['hit']} | {x['ev_pct']:+.2f} | {x['pnl_usd']:+.2f} |"
                  for k, x in ref["per_token"].items()]
        if ref.get("grid_top"):
            L += ["", "Najbolje konfiguracije na svim danima (u uzorku, samo za usporedbu): " + "; ".join(
                f"{g['key']} n {g['n']} EV {g['ev_pct']:+.2f} %" for g in ref["grid_top"][:5])]
        L.append("")
    if data.get("stops"):
        L += ["## Stop (0,5 SOL, pravilo dna BTC-a)", "", "- pct20 (vlasnikov, zadan): vidi gore"]
        for k, x in data["stops"].items():
            L.append(f"- {k}: n {x.get('n')}, EV {_pct(x.get('ev_pct'))}, CI95 po danu {x.get('ci95_day_pct')}, $/dan "
                     f"{x.get('usd_day')}, PF {x.get('profit_factor')}, najgorih 5 % {x.get('worst5_pct')} %")
        L.append("")
    if (data.get("intra") or {}).get("n"):
        L += ["## Dnevni raspon (replay na 15m svijećama, 0,1 SOL, pravi trošak)", "", "- " + intra_text(data["intra"]), ""]
    md = data.get("macro_days") or {}
    if md.get("n"):
        L += [f"Makro režim po danima (market.db): {md['by']}", ""]
    lr = data.get("live_rule")
    L += ["## Pravilo za demo", "", (f"{lr['key']} (svi dani: n {lr['n_all']}, EV {lr['ev_all_pct']:+.2f} %), "
                                     f"{lr['size_sol']} SOL" if lr else "još nema (premalo tradeova)"), ""]
    g = data.get("gate") or {}
    L += ["## Pravi novac", "", g.get("why") or "dopušten", ""]
    return "\n".join(L) + "\n"


# ---------- the run --------------------------------------------------------------------------------------------------

GT_PASS_S = float(os.environ.get("VEL_GT_PASS_S", "900"))   # 15.11. navečer: the longest a pass waits on GeckoTerminal


def top_up(con, rows, hrows, now, budget, log=print, pass_s=None):
    """The list's candles, most needed first (15.11. navečer, coordinator: the backtest and the zones need the 1h; the
    3-hourly pass used its budget on the daily candles of 60 tokens and the 429s stopped it before any 1h): the own
    bars from veliki/live's DexScreener polls merged in (free), then 1h for the top TOP_1H of the list (by rank, so
    the top tokens first), then the daily candles of the list, then the fallen tokens' daily and 1h (survivorship).
    GeckoTerminal requests at most `budget`, waiting on the shared limiter within pass_s (GT_PASS_S). Requests used."""
    try:
        own = store.own_bars([r["mint"] for r in rows], now - 9 * 86400)
        n15, n1h = store.merge_own_bars(con, own, now)
        if n15 or n1h:
            log(PREFIX + f"vlastite svijeće iz DexScreener cijena: +{n15} × 15m, +{n1h} × 1h (GeckoTerminal ih zamijeni "
                         "kad stigne)")
    except Exception as e:  # noqa: BLE001 - the fallback is a help; GeckoTerminal below
        log(PREFIX + f"vlastite svijeće: {type(e).__name__}: {e}")
    store.DEADLINE[0] = time.monotonic() + (GT_PASS_S if pass_s is None else pass_s)
    used = 0
    try:
        plan = [(r, "c1h") for r in rows[:store.TOP_1H]] + [(r, "c1d") for r in rows] + \
               [(r, "c1d") for r in hrows] + [(r, "c1h") for r in hrows[:store.HIST_1H]]
        for r, t in plan:
            if used >= budget or time.monotonic() >= store.DEADLINE[0]:
                break
            if r.get("pool"):
                used += store.fill(con, r["mint"], r["pool"], now, budget - used, tables=(t,))
    finally:
        store.DEADLINE[0] = 0.0
    return used


def candles_pass(now=None, log=print, path=None, budget=None, pass_s=None):
    """run_veliki.py candles (start.sh every VEL_CANDLES_EVERY_S, 15 min): only the candles of the current list topped
    up (no list rebuild): the own bars, then GeckoTerminal by need (top_up). Returns requests used."""
    now = int(now or time.time())
    con = store.connect(path)
    try:
        rows = store.tokens(con)
        if not rows:
            return 0
        used = top_up(con, rows, store.history_rows(con), now, store.GT_PASS if budget is None else budget, log,
                      pass_s if pass_s is not None else float(os.environ.get("VEL_CANDLES_PASS_S", "480")))
        cov = store.coverage(con, [r["mint"] for r in rows])
        store.kv_put(con, "coverage", cov)
        con.commit()
        n1h = sum(1 for m in cov.values() if (m.get("d1h") or 0) >= 3)
        log(PREFIX + f"svijeće (dopuna): {used} zahtjeva GeckoTerminalu (odbijeno {store.GT_STATS['refused']}, čekano "
                     f"{store.GT_STATS['waited_s']:.0f} s), {n1h} od {len(rows)} tokena ima 3+ dana 1h svijeća")
        store.reset_cache()
        return used
    finally:
        con.close()


def refresh(now=None, log=print, path=None, gt_budget=None):
    """The list + candles + BTC (run_veliki.py list): the list from scratch, the candles topped up. Returns rows."""
    from veliki import universe
    now = int(now or time.time())
    con = store.connect(path)
    try:
        rows, meta = universe.build(now, log)
        hist = meta.pop("history", [])
        if rows:
            store.save_list(con, rows, now, meta)
            store.save_history(con, hist, now)
        else:
            rows = store.tokens(con)
            log(PREFIX + "lista prazna (izvori nisu odgovorili): ostaje zadnja")
        log(universe.line(rows))
        if meta.get("out_of_range"):
            log(PREFIX + "izvan raspona MC / bez pravog poola: " + "; ".join(meta["out_of_range"]))
        nh, nd = store.fill_btc(con, now)
        used, budget = 0, store.GT_PASS if gt_budget is None else gt_budget
        hrows = store.history_rows(con)
        used = top_up(con, rows, hrows, now, budget)
        store.prune(con, now)
        ng = store.archive_grok(con, [r["mint"] for r in rows], now)
        cov = store.coverage(con, [r["mint"] for r in rows])
        store.kv_put(con, "coverage", cov)
        store.kv_put(con, "refresh_ts", now)
        con.commit()
        log(PREFIX + f"svijeće: {used} zahtjeva GeckoTerminalu, BTC {nh} sati / {nd} dana, {len(hrows)} ispalih "
            f"tokena za povijest, {ng} Grokovih signala arhivirano; pokrivenost (dani 1d / 1h): " + ", ".join(
                f"{r['symbol']} {cov[r['mint']]['d1d']:.0f}/{cov[r['mint']]['d1h']:.0f}" for r in rows))
        store.reset_cache()
        return rows
    finally:
        con.close()


def run(now=None, log=print, mode="once", path=None, budget_s=BUDGET_S):
    now = int(now or time.time())
    con = store.connect(path)
    try:
        if not store.tokens(con) or now - ((store.kv_get(con, "list") or {}).get("ts") or 0) > 6 * 3600:
            con.close()
            refresh(now, log, path)
            con = store.connect(path)
        series, btc_h, btc_d = load(con)
        lst = store.tokens(con)
        cov = store.kv_get(con, "coverage") or {}
        meta = store.kv_get(con, "list") or {}
    finally:
        con.close()
    t0 = time.time()
    crash = rule.crash_of(btc_h)
    cats = categories(series, btc_h, btc_d, now, crash)
    table = sorted(({"mint": m, **x} for m, x in cats.items() if not x.get("dead")),
                   key=lambda x: (x.get("cat") or "C", -(x.get("score") or 0)))
    data = compute(series, btc_h, btc_d, now, log, budget_s, cats=cats)
    try:
        store.save_cats(cats, path)
    except Exception:  # noqa: BLE001 - the live DCA then refuses (no category)
        pass
    for size_k, ref in ((data.get("variants") or {}).get(LIVE_VARIANT) or {}).items():
        if isinstance(ref, dict) and ref.get("variants_holdout"):
            log(PREFIX + f"{size_k} SOL " + variants_line(ref["variants_holdout"]))
    data.update(mode=mode, list=lst, coverage=cov, secs=round(time.time() - t0, 1), table=table,
                out_of_range=meta.get("out_of_range") or [], seeds=meta.get("seeds") or {},
                btc_now=dict(zip(("state", "why"), crash.regime(now))))
    for v in (LIVE_VARIANT, "zabrana", "bez_filtra"):
        ref = ((data["variants"].get(v) or {}).get(f"{DEMO_SIZE:g}") or {})
        if ref.get("by_regime"):
            log(PREFIX + f"{VNAME.get(v, v)}: " + regime_line(ref))
    tab = data.get("table") or []
    if tab:
        cats = {}
        for x in tab:
            cats[x.get("cat")] = cats.get(x.get("cat"), 0) + 1
        log(PREFIX + "tablica: " + ", ".join(f"{k} {v}" for k, v in sorted(cats.items())) + "; prvih 10: " + ", ".join(
            f"{x['symbol']} ({x.get('cat')}, MC ${(x.get('mcap') or 0) / 1e6:,.0f}M, {x.get('age_bucket')}, stalnost 90 d "
            f"{x.get('pers90')}, korelacija BTC {x.get('corr_d')}, odbijanja +15 % {x.get('hit15')})" for x in tab[:10]))
    store.save_run(data, now, path)
    try:
        from veliki import gate
        why = gate.real_refusal()
    except Exception as e:  # noqa: BLE001
        why = f"vrata nečitljiva ({type(e).__name__})"
    data["gate"] = {"why": why}
    lr = data.get("live_rule")
    log(PREFIX + f"pravilo za demo: {lr['key'] if lr else 'još nema'}; pravi novac: {why or 'dopušten'} "
        f"({data['secs']} s)")
    try:
        os.makedirs(os.path.join(store.ROOT, "output"), exist_ok=True)
        with open(os.path.join(store.ROOT, "output", "veliki.md"), "w") as f:
            f.write(markdown(data))
    except OSError:
        pass
    return data


def dumps(d):
    return json.dumps(d, ensure_ascii=False, default=str)
