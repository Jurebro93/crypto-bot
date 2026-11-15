#!/usr/bin/env python3
"""15.11. (owner: "autopilot mora bolje uzimati profit ... brže uzimati profit"): replay of the old exits against the
quick-profit rule (league/exitplan "brzi profit": half at +12 % net, the rest's stop to break-even, a 10 % trailing
from the peak, stop -20 %) on the price paths we hold offline. Yesterday's real trades have no stored paths, so:

  seed    exits/seed_paths.json.gz (retro.db study, shipped in git): entries at graduation ("graduacija", ~$38k MC)
          and at the first $100k ("100k"): bonded pump.fun tokens like the ones the copies buy; [(s, price x entry,
          liquidity)] thinned at 3 % (a stop / trailing that gapped fills at the next point: the pessimistic side)
  range   tests/fixtures/range_*.json.gz: 1-minute GeckoTerminal candles of 7 bonded tokens (10.-11.11.), an entry at
          the close of every 15th minute (a copy's entry has no signal here: an even sample), fills on the wicks

Rules (cost: trade/cost.round_trip of a $15 stake (0.1 SOL) in the entry's pool, taken off every result):
  old_copy_H   a wallet / insider copy "mirror" + the protective -30 % stop (14.11.): out at the -30 % stop or when the
               source sells; the source's sale is unknown here, so at H minutes (30 / 60 / 120: the proxy)
  old_tp15_H   a "tpsl" copy with the owner's tp_default +15 % (all of it) and the stop -60 % (sl_default), out at H
  new_H        half at +12 % net (+12 % + cost), the rest's stop at break-even (entry + cost), trailing 10 % from the peak
               once TP1 sold, stop -20 %, the rest out at H (the mirror sale) if still held
  fast_old / fast_new   the fast path's own exit (half +15 %, trailing 8 %, stop -10 %, 45 min) vs it inside the
               quick-profit plan (TP1 at min(+15 %, +12 % net), break-even after TP1)

    python3 scripts/replay_brzi_profit.py            # prints the table (EV per trade, hit rate, median, worst)
"""
import glob
import gzip
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from trade import cost as tcost  # noqa: E402

STAKE = 15.0
H_MIN = (30, 60, 120)


def rt_of(liq):
    return tcost.round_trip(STAKE, liq, fee=tcost.FEE_DEMO)


def run(path, rule, rt):
    """path: [(s, low, high, close)] after the entry (price as a multiple of the entry). rule: {"tp1", "share", "tp_all",
    "stop", "trail", "be", "until_s"}. Returns the gross return (multiple - 1) of the whole stake."""
    left, got, peak, tp1_done, stop = 1.0, 0.0, 1.0, False, rule["stop"]
    for s, lo, hi, cl in path:
        if s > rule["until_s"]:
            break
        if lo <= stop:                                     # the stop (or break-even) first: pessimistic
            return got + left * (stop if hi >= stop else hi) - 1   # gapped under it: the price there
        if rule.get("tp_all") and hi >= rule["tp_all"]:
            return got + left * rule["tp_all"] - 1
        if rule.get("tp1") and not tp1_done and hi >= rule["tp1"]:
            got += rule["share"] * rule["tp1"]
            left -= rule["share"]
            tp1_done, peak = True, max(peak, hi)
            if rule.get("be"):
                stop = max(stop, 1 + rt)                   # the rest's break-even: entry + the round trip
            continue
        peak = max(peak, hi)
        if tp1_done and rule.get("trail") and lo <= peak * (1 - rule["trail"]):
            lvl = peak * (1 - rule["trail"])
            return got + left * (lvl if hi >= lvl else hi) - 1
    last = path[-1][3] if path else 1.0
    for s, _lo, _hi, cl in path:
        if s <= rule["until_s"]:
            last = cl
    return got + left * last - 1


def rules_for(rt):
    out = {}
    for h in H_MIN:
        out[f"old_copy_{h}"] = {"stop": 0.70, "until_s": h * 60}
        out[f"old_tp15_{h}"] = {"stop": 0.40, "tp_all": 1.15, "until_s": h * 60}
        out[f"new_{h}"] = {"stop": 0.80, "tp1": 1.12 + rt, "share": 0.5, "be": True, "trail": 0.10, "until_s": h * 60}
    out["fast_old"] = {"stop": 0.90, "tp1": 1.15, "share": 0.5, "trail": 0.08, "until_s": 45 * 60}
    out["fast_new"] = {"stop": 0.90, "tp1": min(1.15, 1.12 + rt), "share": 0.5, "trail": 0.08, "be": True,
                       "until_s": 45 * 60}
    return out


def seed_paths(entries=("graduacija", "100k")):
    with gzip.open(os.path.join(ROOT, "exits", "seed_paths.json.gz"), "rt") as f:
        d = json.load(f)
    for p in d["paths"]:
        if p.get("entry") not in entries or not p.get("pts"):
            continue
        pts = [(int(s), float(m), float(m), float(m)) for s, m, _liq in p["pts"] if m and m > 0]
        if pts and pts[0][0] <= 300:
            yield p["entry"], pts, p.get("liq0") or None


def range_paths(every_min=15, horizon_min=120):
    for fn in sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "range_*.json.gz"))):
        with gzip.open(fn, "rt") as f:
            fx = json.load(f)
        c = [r for r in fx.get("candles") or [] if r[4]]
        for i in range(0, len(c) - horizon_min, every_min):
            e = c[i][4]
            t0 = c[i][0]
            pts = [(r[0] - t0, r[3] / e, r[2] / e, r[4] / e) for r in c[i + 1:i + 1 + horizon_min]]
            yield fx.get("symbol"), pts, 25_000.0


def summary(rets):
    if not rets:
        return None
    return {"n": len(rets), "ev_pct": round(statistics.mean(rets) * 100, 2),
            "hit_pct": round(sum(1 for r in rets if r > 0) / len(rets) * 100, 1),
            "median_pct": round(statistics.median(rets) * 100, 2), "worst_pct": round(min(rets) * 100, 1),
            "best_pct": round(max(rets) * 100, 1)}


def replay(source):
    res = {}
    for _name, pts, liq in source:
        rt = rt_of(liq)
        for k, rule in rules_for(rt).items():
            res.setdefault(k, []).append(run(pts, rule, rt) - rt)
    return {k: summary(v) for k, v in res.items()}


def main():
    out = {"seed": replay(seed_paths()), "range": replay(range_paths())}
    for src, tab in out.items():
        print(f"== {src} ==")
        for k, s in tab.items():
            print(f"  {k:14s} n {s['n']:5d}  EV {s['ev_pct']:+6.2f} %  pogodak {s['hit_pct']:5.1f} %  medijan "
                  f"{s['median_pct']:+6.2f} %  najgori {s['worst_pct']:+6.1f} %  najbolji {s['best_pct']:+7.1f} %")
    return out


if __name__ == "__main__":
    main()
