"""The big-token range backtest and walk-forward (run_veliki.py once / night; read-only on everything but veliki.db).

Data: veliki.db c15 / c1h of the list (GeckoTerminal), BTC hourly / daily (DefiLlama). Per token the 1h candles the
zones read are rebuilt from the 15m bars where those exist (rule.h1_from_15m), exactly as live does.

Two rule variants (the owner 15.11.: "NE računajući velike padove Bitcoina"):
  bez_padova   THE rule (live trades it): no entry while a BTC crash is active (rule.crash_hours: 4 h <= -3 % or 24 h
               <= -5 %), zones after a crash only from the candles since its end (>= 24 h: the fresh range). The grid
               is picked on THIS variant.
  s_padovima   the same rule with neither (every period counts), for comparison.
Grid (rule.GRID, small): target net +3 / +5 / +8 % or the range's mid / top x stop -3 / -5 / -7 % x time stop 12 / 24 /
48 h x zone window 3 / 7 days = 90 configurations, at each size 0.1 / 0.5 / 1.0 SOL (the cost differs: the network fee
is 1 % of 0.1 SOL and 0.1 % of 1 SOL).
Walk-forward (no look-ahead: zones and signals read only completed candles; a config is picked only on older days):
anchored, the first TRAIN_D (10) days train only, then test blocks of FOLD_D (5) days; before each block the config
with the best EV on every earlier day (n >= MIN_TRAIN_N) is picked and only its trades INSIDE the block count. The
holdout = all test blocks. Bootstrap 90 % interval by token-day (B 1000), trades / day, hit, EV % and $, $ / day, max
drawdown, worst trade, per token, per BTC regime (market/makro's own _state on the BTC closes known at the entry).
Also on the holdout at 0.5 SOL: the DCA variant (one more lot at half the stop), the stop filled at the bar's low,
and the trades that overlapped a crash left out (the owner's view taken literally).
The live rule = the best configuration of bez_padova on ALL days at the demo size (kv rule); the proof (kv proof) =
the holdout per size of bez_padova (gate.py reads 0.1 SOL).
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

def boot_ci(trades, b=B, seed=7):
    """90 % interval of EV % a trade (sum ret / sum n), resampling token-days."""
    g = {}
    for x in trades:
        k = (x["token"], x["ts"] // D)
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
    return [round(out[int(0.05 * b)], 3), round(out[int(0.95 * b) - 1], 3)]


def max_dd(trades):
    eq = peak = dd = 0.0
    for x in sorted(trades, key=lambda x: x["out_ts"]):
        eq += x["pnl"]
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    return round(dd, 2)


def stats(trades, days, size_usd):
    s = rule.summary(trades)
    n = s["n"]
    s.update({"days": days, "per_day": round(n / days, 2) if days else None,
              "usd_day": round(s["pnl_usd"] / days, 3) if days else None, "max_dd_usd": max_dd(trades) if n else 0.0,
              "ci90_ev_pct": boot_ci(trades) if n else None, "size_usd": round(size_usd, 2),
              "token_days": len({(x["token"], x["ts"] // D) for x in trades})})
    return s


def by_key(trades, key):
    out = {}
    for x in trades:
        out.setdefault(key(x), []).append(x)
    return {k: {"n": len(v), "hit": round(sum(1 for x in v if x["ret"] > 0) / len(v), 3),
                "ev_pct": round(sum(x["ret"] for x in v) / len(v) * 100, 3), "pnl_usd": round(sum(x["pnl"] for x in v), 2)}
            for k, v in sorted(out.items(), key=lambda kv: -len(kv[1]))}


# ---------- the computation ------------------------------------------------------------------------------------------

def load(con):
    """{mint: {"bars", "h1", "liq", "dex", "symbol"}} of the list, BTC hourly / daily."""
    series = {}
    for r in store.tokens(con):
        bars = store.candles(con, "c15", r["mint"])
        if len(bars) < 200:
            continue
        h1 = rule.h1_from_15m(bars, store.candles(con, "c1h", r["mint"]))
        series[r["mint"]] = {"bars": bars, "h1": h1, "liq": r.get("liq"), "dex": r.get("dex") or r.get("url"),
                             "symbol": r.get("symbol")}
    return series, store.btc_hourly(con), store.btc_daily(con)


def compute(series, btc_h, btc_d, now=None, log=print, budget_s=BUDGET_S, sol_usd=None, sizes=rule.SIZES_SOL,
            grid=None):
    now = int(now or time.time())
    t_end = time.time() + budget_s
    sol = sol_usd or sol_now()
    crash = rule.Crash(rule.crash_hours(btc_h))
    reg = Regime(btc_d, btc_h)
    cfgs = rule.configs(grid)
    looks = sorted({c["look_d"] for c in cfgs})
    tx = rule.tx_sol()[0]
    days_all = sorted({b[0] // D for s in series.values() for b in s["bars"]})
    variants = {"bez_padova": crash, "s_padovima": None}
    cands = {}
    for v, cr in variants.items():
        for m, s in series.items():
            zs = rule.Zones(s["h1"], cr)
            for lk in looks:
                cands[(v, m, lk)] = rule.candidates(s["bars"], zs, lk, cr, {"crash_filter": cr is not None})
    out = {"ts": now, "sol_usd": round(sol, 2), "tx_sol": tx, "days": len(days_all), "tokens": len(series),
           "crash_periods": [[a, b] for a, b in crash.periods if a >= (days_all[0] * D if days_all else 0)],
           "variants": {}, "costs": {}, "grid_n": len(cfgs)}
    for size in sizes:
        out["costs"][f"{size:g}"] = {s["symbol"]: round(rule.cost_at(size, s["liq"], sol, rule.fee_side_of(s["dex"]),
                                                                      tx)["rt"] * 100, 3) for s in series.values()}
    if len(days_all) < TRAIN_D + 2:
        out["note"] = f"premalo dana ({len(days_all)}): walk-forward treba barem {TRAIN_D + 2}"
    folds = []
    k = TRAIN_D
    while k < len(days_all):
        folds.append((days_all[k], days_all[min(k + FOLD_D, len(days_all)) - 1] + 1))
        k += FOLD_D
    test_days = sum(b - a for a, b in folds)
    for v, cr in variants.items():
        vo = out["variants"].setdefault(v, {})
        for size in sizes:
            if time.time() > t_end:
                vo[f"{size:g}"] = {"error": "vremenski budžet potrošen"}
                continue
            usd = size * sol
            per_cfg = {}
            for c in cfgs:
                cc = {**c, "crash_filter": cr is not None}
                trs = []
                for m, s in series.items():
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
                    tr = [x for x in trs if x["day"] < a]
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
            st = stats(hold, test_days, usd)
            st["folds"] = picks
            st["worst_trade"] = (min(hold, key=lambda x: x["ret"]) and {
                "token": series[min(hold, key=lambda x: x["ret"])["token"]]["symbol"],
                "ret_pct": round(min(x["ret"] for x in hold) * 100, 2)}) if hold else None
            st["per_token"] = {series[m]["symbol"]: d for m, d in by_key(hold, lambda x: x["token"]).items()}
            st["by_regime"] = by_key(hold, lambda x: reg.at(x["ts"]))
            st["crash_overlap_n"] = sum(1 for x in hold if x.get("crash_overlap"))
            if hold and st["crash_overlap_n"]:
                rest = [x for x in hold if not x.get("crash_overlap")]
                st["bez_preklopa"] = rule.summary(rest) if rest else None
            # the configuration on ALL days (the live rule's candidate) and its in-sample numbers
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
            if v == "bez_padova" and abs(size - DEMO_SIZE) < 1e-9 and hold:
                st["variants_holdout"] = _variants(series, cands, picks, per_cfg, folds, usd, sol, tx, crash, test_days)
            vo[f"{size:g}"] = st
            log(PREFIX + line_size(v, size, st))
    bp = out["variants"].get("bez_padova") or {}
    demo = (bp.get(f"{DEMO_SIZE:g}") or {}).get("best_all")
    out["live_rule"] = ({**demo["cfg"], "key": demo["key"], "n_all": demo["n"], "ev_all_pct": demo["ev_pct"],
                         "size_sol": DEMO_SIZE} if demo else None)
    out["proof"] = {"ts": now, "days": len(days_all), "test_days": test_days,
                    "sizes": {s: {f: x.get(f) for f in ("n", "ev_pct", "ev_usd", "ci90_ev_pct", "usd_day", "hit",
                                                        "max_dd_usd", "per_day", "token_days")}
                              for s, x in bp.items() if isinstance(x, dict) and "n" in x}}
    return out


def _variants(series, cands, picks, per_cfg, folds, usd, sol, tx, crash, test_days):
    """The holdout's picks re-run with a DCA lot at half the stop, and with the stop filled at the bar's low."""
    res = {}
    for name, extra in (("dca", lambda c: {"dca": c["stop_pct"] / 2}), ("stop_na_dnu_svijece", lambda c: {"stop_fill": "low"})):
        hold = []
        for p, (a, b) in zip(picks, folds):
            if not p.get("pick"):
                continue
            c = per_cfg[p["pick"]][0]
            cc = {**c, "crash_filter": True, **extra(c)}
            for m, s in series.items():
                cost = rule.cost_at(usd / sol, s["liq"], sol, rule.fee_side_of(s["dex"]), tx,
                                    lots=2 if name == "dca" else 1)["rt"]
                for x in rule.simulate(s["bars"], cands[("bez_padova", m, c["look_d"])], usd, cost, cc, crash=crash,
                                       t0=a * D, t1=b * D):
                    x["token"] = m
                    hold.append(x)
        st = rule.summary(hold)
        st["usd_day"] = round(st["pnl_usd"] / test_days, 3) if test_days else None
        st["ci90_ev_pct"] = boot_ci(hold) if hold else None
        res[name] = st
    return res


def _pct(x):
    return "—" if x is None else f"{x:+.2f} %"


def line_size(v, size, st):
    if "n" not in st:
        return f"backtest {size:g} SOL ({v.replace('_', ' ')}): {st.get('error')}"
    ci = st.get("ci90_ev_pct")
    return (f"backtest {size:g} SOL ({v.replace('_', ' ')} BTC-a): n={st['n']} ({st.get('per_day')}/dan), EV "
            f"{_pct(st.get('ev_pct'))} ({st.get('ev_usd')} $), CI90 [{ci[0] if ci else '—'}; {ci[1] if ci else '—'}], "
            f"$/dan {st.get('usd_day')}, pogodak {st.get('hit')}, max pad {st.get('max_dd_usd')} $, najgori "
            f"{(st.get('worst_trade') or {}).get('ret_pct', '—')} %")


def regime_line(st):
    br = st.get("by_regime") or {}
    return "po režimu BTC: " + ("; ".join(f"{k} n={v['n']} EV {_pct(v['ev_pct'])}" for k, v in br.items()) or "—")


# ---------- report ---------------------------------------------------------------------------------------------------

def markdown(data):
    if not data:
        return "# Veliki tokeni — range\n\nJoš nema izračuna (run_veliki.py once).\n"
    L = ["# Veliki tokeni — range", "",
         f"Izračun {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(data.get('ts') or 0))}: {data.get('tokens')} tokena, "
         f"{data.get('days')} dana 15m svijeća, SOL ${data.get('sol_usd')}, mreža {data.get('tx_sol')} SOL po swapu, "
         f"mreža konfiguracija {data.get('grid_n')}.", ""]
    if data.get("note"):
        L += [f"**{data['note']}**", ""]
    lst = data.get("list") or []
    if lst:
        L += ["## Lista", "", "| token | MC | likvidnost (sve / najdublji) | volumen 24 h | starost | 15m / 1h dana | kako |",
              "|---|---|---|---|---|---|---|"]
        cov = data.get("coverage") or {}
        for r in lst:
            c = cov.get(r["mint"]) or {}
            L.append(f"| {r['symbol']} | ${(r.get('mcap') or 0) / 1e6:,.0f}M | ${(r.get('liq_total') or 0) / 1e6:,.1f}M / "
                     f"${(r.get('liq') or 0) / 1e6:,.2f}M | ${(r.get('vol24') or 0) / 1e6:,.1f}M | {r.get('age_d')} d | "
                     f"{c.get('d15', 0)} / {c.get('d1h', 0)} | {r.get('how') or ''} |")
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
        L += [f"## Walk-forward: {v.replace('_', ' ')} BTC-a", ""]
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
                L.append(f"- varijanta {k}: n {x.get('n')}, EV {_pct(x.get('ev_pct'))}, CI90 {x.get('ci90_ev_pct')}, "
                         f"$/dan {x.get('usd_day')}")
        if ref.get("bez_preklopa"):
            L.append(f"- bez tradeova koji su preklopili pad: n {ref['bez_preklopa']['n']}, EV "
                     f"{_pct(ref['bez_preklopa']['ev_pct'])}")
        if ref.get("per_token"):
            L += ["", f"| token ({DEMO_SIZE:g} SOL) | n | pogodak | EV % | PnL $ |", "|---|---|---|---|---|"]
            L += [f"| {k} | {x['n']} | {x['hit']} | {x['ev_pct']:+.2f} | {x['pnl_usd']:+.2f} |"
                  for k, x in ref["per_token"].items()]
        if ref.get("grid_top"):
            L += ["", "Najbolje konfiguracije na svim danima (u uzorku, samo za usporedbu): " + "; ".join(
                f"{g['key']} n {g['n']} EV {g['ev_pct']:+.2f} %" for g in ref["grid_top"][:5])]
        L.append("")
    lr = data.get("live_rule")
    L += ["## Pravilo za demo", "", (f"{lr['key']} (svi dani: n {lr['n_all']}, EV {lr['ev_all_pct']:+.2f} %), "
                                     f"{lr['size_sol']} SOL" if lr else "još nema (premalo tradeova)"), ""]
    g = data.get("gate") or {}
    L += ["## Pravi novac", "", g.get("why") or "dopušten", ""]
    return "\n".join(L) + "\n"


# ---------- the run --------------------------------------------------------------------------------------------------

def refresh(now=None, log=print, path=None, gt_budget=None):
    """The list + candles + BTC (run_veliki.py list): the list from scratch, the candles topped up. Returns rows."""
    from veliki import universe
    now = int(now or time.time())
    con = store.connect(path)
    try:
        rows, meta = universe.build(now, log)
        if rows:
            store.save_list(con, rows, now, meta)
        else:
            rows = store.tokens(con)
            log(PREFIX + "lista prazna (izvori nisu odgovorili): ostaje zadnja")
        log(universe.line(rows))
        nh, nd = store.fill_btc(con, now)
        used, budget = 0, store.GT_PASS if gt_budget is None else gt_budget
        for r in rows:
            if used >= budget:
                break
            if r.get("pool"):
                used += store.fill(con, r["mint"], r["pool"], now, budget - used)
        store.prune(con, now)
        cov = store.coverage(con, [r["mint"] for r in rows])
        store.kv_put(con, "coverage", cov)
        store.kv_put(con, "refresh_ts", now)
        con.commit()
        log(PREFIX + f"svijeće: {used} zahtjeva GeckoTerminalu, BTC {nh} sati / {nd} dana; pokrivenost: " + ", ".join(
            f"{r['symbol']} {cov[r['mint']]['d15']:.0f} d 15m / {cov[r['mint']]['d1h']:.0f} d 1h" for r in rows))
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
    finally:
        con.close()
    t0 = time.time()
    data = compute(series, btc_h, btc_d, now, log, budget_s)
    data.update(mode=mode, list=lst, coverage=cov, secs=round(time.time() - t0, 1))
    ref = ((data["variants"].get("bez_padova") or {}).get(f"{DEMO_SIZE:g}") or {})
    if ref.get("by_regime"):
        log(PREFIX + regime_line(ref))
    ref2 = ((data["variants"].get("s_padovima") or {}).get(f"{DEMO_SIZE:g}") or {})
    if ref2.get("by_regime"):
        log(PREFIX + "s padovima BTC-a " + regime_line(ref2))
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
