"""Turn retro.db into features + outcomes, then measure which early signals separated the tokens that exploded.

Outputs output/retro-features.csv (one row per token and decision point) and output/retro-stats.json,
which the report is written from. Weights come from a logistic regression trained on the older half of the
window and scored on the newer half, so the same code can be rerun as data grows (learned, not fixed).
"""
import csv
import json
import math
import os
from collections import defaultdict

import numpy as np

from retro import features as F

DAY = 86400
HORIZON = 7 * DAY


def load(con):
    toks = {r[0]: dict(zip(("mint", "stratum", "t_create", "slot_create", "creator", "curve", "name", "symbol",
                                "t_grad", "pool", "complete", "n_tx"), r))
            for r in con.execute("""SELECT mint, stratum, t_create, slot_create, creator, curve, name, symbol, t_grad,
                pool, complete, n_tx FROM tokens WHERE fetched_at IS NOT NULL AND err IS NULL AND t_create IS NOT NULL""")}
    creators = {r[0]: {"prior_creates": r[1], "prior_txs": r[2]} for r in
                con.execute("SELECT wallet, prior_creates, prior_txs FROM creators")}
    meta = {m: json.loads(d) for m, d in con.execute("SELECT mint, data FROM meta WHERE data IS NOT NULL")}
    series = {m: json.loads(c) for m, c in con.execute("SELECT mint, candles FROM series WHERE candles IS NOT NULL")}
    series_err = {m for (m,) in con.execute("SELECT mint FROM series WHERE candles IS NULL")}
    dex = {m: json.loads(d) for m, d in con.execute("SELECT mint, data FROM dex")}
    return toks, creators, meta, series, series_err, dex


def trades_of(con, mint):
    cols = ("n", "ts", "slot", "wallet", "side", "tokens", "sol", "price")
    return [dict(zip(cols, r)) for r in con.execute(
        "SELECT n, ts, slot, wallet, side, tokens, sol, price FROM trades WHERE mint=? ORDER BY n", (mint,))]


def sol_usd(dex):
    """USD per SOL: median over DexScreener pairs quoted in WSOL (one odd pair must not skew it)."""
    xs = []
    for pairs in dex.values():
        for p in pairs:
            try:
                if p.get("quoteToken", {}).get("address") == "So11111111111111111111111111111111111111112":
                    xs.append(float(p["priceUsd"]) / float(p["priceNative"]))
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                continue
    return float(np.median(xs)) if xs else 180.0


def build(con, early_min=15):
    toks, creators, meta, series, series_err, dex = load(con)
    usd = sol_usd(dex)
    rows = []
    skipped = defaultdict(int)
    for mint, t in toks.items():
        trs = trades_of(con, mint)
        if not trs:
            continue
        # pump.fun also launches curves quoted in other tokens (BuyExactQuoteInV2); their prices are not in SOL
        # a SOL curve starts at ~28 SOL mcap (~14 for 2B-supply "mayhem" tokens); far below that = quoted in another token
        priced = [r["price"] for r in trs if r["price"]]
        if not priced or float(np.median(priced)) * 1e9 < 2 or (len(trs) > 3 and not any(r["price"] for r in trs if r["n"] > 0)):
            skipped["non_sol_or_unpriced"] += 1
            continue
        grad = t["t_grad"]
        instant = grad is not None and grad - t["t_create"] < 60
        s = series.get(mint)
        # outcome is unknown if the token graduated (or the curve history was cut) and no price series came back
        known = (not grad and t["complete"]) or s is not None
        cr = creators.get(t["creator"])
        mt = meta.get(mint)
        base = {"mint": mint, "stratum": t["stratum"], "t_create": t["t_create"], "graduated": 1 if grad else 0,
                "instant_grad": 1 if instant else 0, "grad_min": (grad - t["t_create"]) / 60 if grad else None,
                "known": 1 if known else 0, "name": t["name"]}
        # decision A: 15 min after creation, only if still on the curve
        cut = t["t_create"] + early_min * 60
        if not grad or grad > cut:
            p = F.price_at(trs, cut)
            if p is not None and p * 1e9 < 5:  # a SOL curve never trades below ~14 SOL mcap: not a real price
                p = None
            f = F.at(trs, t, cut, cr, mt)
            f.update(F.path_shape([(r["ts"], r["price"]) for r in trs], cut, t["t_create"]))
            f["top3_buy_share"] = F.buy_concentration(trs, cut)
            peak = F.peak_after(trs, s, cut, t["t_create"] + HORIZON) if known else None
            rows.append({**base, "point": "A15", "price": p, "mcap_usd": p * 1e9 * usd if p else None,
                         "mult": (peak / p) if (p and peak is not None) else None, **f})
        # decision G: the moment of graduation (bot's "graduating" feed)
        if grad and not instant and t["complete"]:
            p = F.price_at(trs, grad)
            if p is not None and p * 1e9 < 5:
                p = None
            f = F.at(trs, t, grad, cr, mt)
            f.update(F.path_shape([(r["ts"], r["price"]) for r in trs], grad, t["t_create"]))
            f["top3_buy_share"] = F.buy_concentration(trs, grad)
            peak = F.peak_after([], s, grad + 60, grad + HORIZON) if s is not None else None
            peak_h = F.peak_after([], s, grad + 60, grad + HORIZON, use="high") if s is not None else None
            p1h = None
            if s:
                after = [c[2] for c in s if grad + 3600 <= c[0] <= grad + 2 * 3600]
                p1h = after[0] if after else None
            rows.append({**base, "point": "G", "price": p, "mcap_usd": p * 1e9 * usd if p else None,
                         "mult": (peak / p) if (p and peak) else None, "mult_high": (peak_h / p) if (p and peak_h) else None,
                         "dump_1h": (1 if p1h and p and p1h < 0.3 * p else 0) if p1h is not None else None, **f})
        # band crossings: first close at >= $100k / $1M / $10M market cap, outcome over the next 7 days
        if s and grad and not instant:
            for band in (1e5, 1e6, 1e7):
                lvl = band / usd / 1e9
                ts, pc = F.first_cross(s, lvl, grad)
                if ts is None:
                    continue
                peak = F.peak_after([], s, ts + 900, ts + HORIZON)
                if ts + HORIZON > max(x[0] for x in s) + 900:
                    complete_window = 0
                else:
                    complete_window = 1
                pre = [(x[0], x[2]) for x in sorted(s) if x[0] <= ts]
                shape = F.path_shape(pre, ts, max(grad, ts - 24 * 3600))
                vol6 = sum(x[3] for x in s if len(x) > 3 and ts - 6 * 3600 <= x[0] <= ts)
                vol1 = sum(x[3] for x in s if len(x) > 3 and ts - 3600 <= x[0] <= ts)
                rows.append({**base, "point": f"B{int(band):d}", "price": pc, "mcap_usd": band,
                             "mult": peak / pc if peak else None, "hours_to_band": (ts - t["t_create"]) / 3600,
                             "window_full": complete_window, **F.at(trs, t, grad, cr, mt), **shape,
                             "top3_buy_share": F.buy_concentration(trs, grad),
                             "vol6h_usd": vol6, "vol_last1h_share": vol1 / vol6 if vol6 else None})
    return rows, usd, dict(skipped)


# ---------- statistics ----------

def auc(x, y):
    """Probability a random winner has a higher x than a random loser (0.5 = no signal)."""
    x, y = np.asarray(x, float), np.asarray(y, int)
    ok = ~np.isnan(x)
    x, y = x[ok], y[ok]
    n1, n0 = y.sum(), len(y) - y.sum()
    if n1 == 0 or n0 == 0:
        return None
    order = x.argsort(kind="mergesort")
    ranks = np.empty(len(x))
    xs = x[order]
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[j + 1] == xs[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def quantile_rates(x, y, q=5):
    x, y = np.asarray(x, float), np.asarray(y, int)
    ok = ~np.isnan(x)
    x, y = x[ok], y[ok]
    if len(x) < q * 10:
        return []
    edges = np.unique(np.quantile(x, np.linspace(0, 1, q + 1)))
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (x >= lo) & ((x <= hi) if hi == edges[-1] else (x < hi))
        if m.sum():
            out.append({"lo": float(lo), "hi": float(hi), "n": int(m.sum()), "rate": float(y[m].mean())})
    return out


def logistic(X, y, l2=1.0, iters=3000, lr=0.1):
    X = np.asarray(X, float)
    y = np.asarray(y, float)
    w = np.zeros(X.shape[1])
    b = math.log((y.mean() + 1e-9) / (1 - y.mean() + 1e-9))
    for _ in range(iters):
        p = 1 / (1 + np.exp(-(X @ w + b)))
        g = X.T @ (p - y) / len(y) + l2 * w / len(y)
        w -= lr * g
        b -= lr * (p - y).mean()
    return w, b


def prep(rows, cols):
    X = np.array([[r.get(c) if r.get(c) is not None else np.nan for c in cols] for r in rows], float)
    # heavy-tailed counts and sizes on a log scale, then standardise; missing -> mean
    X = np.sign(X) * np.log1p(np.abs(X))
    mu, sd = np.nanmean(X, 0), np.nanstd(X, 0) + 1e-9
    X = (X - mu) / sd
    return np.nan_to_num(X), mu, sd


FEATURES = ["age_min", "n_trades", "n_buys", "uniq_buyers", "uniq_sellers", "sell_buy_ratio", "buy_sol", "net_sol",
            "mcap_sol", "median_buy_sol", "small_buy_frac", "big_buy_frac", "holders", "top1_pct", "top10_pct",
            "dev_buy_pct", "dev_hold_pct", "dev_sold_frac", "dev_sold_any", "bundle_wallets", "bundle_pct",
            "snipe3_wallets", "snipe3_pct", "churn_frac", "heavy_wallet_frac", "last5_buy_share",
            "dev_prior_creates", "dev_fresh", "has_twitter", "has_website", "has_telegram", "n_socials",
            "tw_is_status", "desc_len", "smart_wallets", "spike_share", "up_steps", "max_dd_pct", "vol",
            "top3_buy_share", "hours_to_band", "vol6h_usd", "vol_last1h_share", "mayhem", "proto_vol_frac"]


def study(rows, target, split_ts, cols=FEATURES):
    """Per-feature AUC, medians, quintile rates, plus a time-split logistic model."""
    ys = np.array([1 if r["mult"] >= target else 0 for r in rows])
    out = {"n": len(rows), "winners": int(ys.sum()), "base_rate": float(ys.mean()) if len(ys) else 0, "features": {}}
    for c in cols:
        x = [r.get(c) if r.get(c) is not None else np.nan for r in rows]
        a = auc(x, ys)
        if a is None:
            continue
        xa = np.array(x, float)
        out["features"][c] = {"auc": a,
                              "med_win": float(np.nanmedian(xa[ys == 1])) if (ys == 1).any() else None,
                              "med_rest": float(np.nanmedian(xa[ys == 0])) if (ys == 0).any() else None,
                              "quintiles": quantile_rates(x, ys)}
    used = [c for c in cols if c in out["features"]]
    tr = [i for i, r in enumerate(rows) if r["t_create"] < split_ts]
    te = [i for i, r in enumerate(rows) if r["t_create"] >= split_ts]
    if used and len(tr) > 100 and len(te) > 100 and ys[tr].sum() >= 10 and ys[te].sum() >= 5:
        X, mu, sd = prep(rows, used)
        w, b = logistic(X[tr], ys[tr])
        score = X[te] @ w + b
        k = max(1, len(te) // 10)
        top = np.argsort(-score)[:k]
        out["model"] = {"train": len(tr), "test": len(te), "auc_test": auc(score, ys[te]),
                        "precision_top10": float(ys[te][top].mean()), "base_test": float(ys[te].mean()),
                        "weights": sorted(((c, float(v)) for c, v in zip(used, w)), key=lambda t: -abs(t[1]))}
    return out


def filter_cost(rows, target, rules):
    """For each hard cut-off: share of eventual winners it would have thrown away vs share of the rest."""
    ys = np.array([1 if r["mult"] >= target else 0 for r in rows])
    out = []
    for name, fn in rules:
        cut = np.array([1 if fn(r) else 0 for r in rows])
        w, l = ys == 1, ys == 0
        out.append({"rule": name, "cut_winners": float(cut[w].mean()) if w.any() else None,
                    "cut_rest": float(cut[l].mean()) if l.any() else None,
                    "winners_lost": int(cut[w].sum()), "rate_if_kept": float(ys[cut == 0].mean()) if (cut == 0).any() else None,
                    "rate_if_cut": float(ys[cut == 1].mean()) if (cut == 1).any() else None})
    return out


RULES = [
    ("top10 > 45%", lambda r: (r.get("top10_pct") or 0) > 45),
    ("top10 > 30%", lambda r: (r.get("top10_pct") or 0) > 30),
    ("bundle > 20% (rugfilter hard)", lambda r: (r.get("bundle_pct") or 0) > 20),
    ("bundle > 10%", lambda r: (r.get("bundle_pct") or 0) > 10),
    ("dev drži > 10%", lambda r: (r.get("dev_hold_pct") or 0) > 10),
    ("dev drži > 15%", lambda r: (r.get("dev_hold_pct") or 0) > 15),
    ("dev prodao išta", lambda r: (r.get("dev_sold_any") or 0) > 0),
    ("dev prodao > 50%", lambda r: (r.get("dev_sold_frac") or 0) > 0.5),
    ("serijski dev (>= 10 prijašnjih tokena)", lambda r: (r.get("dev_prior_creates") or 0) >= 10),
    ("nema nijedne mreže", lambda r: r.get("n_socials") == 0),
    ("nema X/Twittera", lambda r: r.get("has_twitter") == 0),
    ("< 20 kupaca", lambda r: (r.get("uniq_buyers") or 0) < 20),
    ("> 50% kupnji < 0.05 SOL (bot spam)", lambda r: (r.get("small_buy_frac") or 0) > 0.5),
]


def band_table(rows, usd):
    """Multiple distribution by starting market cap: what a 'jump' realistically means per band."""
    bands = [(0, 2e4), (2e4, 1e5), (1e5, 1e6), (1e6, 1e7), (1e7, 1e12)]
    out = []
    for lo, hi in bands:
        ms = [r["mult"] for r in rows if r["mult"] is not None and r["mcap_usd"] and lo <= r["mcap_usd"] < hi]
        if len(ms) < 20:
            continue
        a = np.array(ms)
        out.append({"lo": lo, "hi": hi, "n": len(ms), "p2": float((a >= 2).mean()), "p3": float((a >= 3).mean()),
                    "p5": float((a >= 5).mean()), "p10": float((a >= 10).mean()), "p100": float((a >= 100).mean()),
                    "median": float(np.median(a)), "p90": float(np.quantile(a, 0.9))})
    return out


def learn_smart(rows, split_ts, target=5.0, min_hits=2):
    """Wallets that bought before graduation in >= min_hits winners of the older half (no look-ahead)."""
    return min_hits, target, split_ts


def main(con, outdir):
    os.makedirs(outdir, exist_ok=True)
    rows, usd, skipped = build(con)
    with open(os.path.join(outdir, "retro-features.csv"), "w", newline="") as f:
        cols = sorted({k for r in rows for k in r})
        w = csv.DictWriter(f, cols)
        w.writeheader()
        w.writerows(rows)
    stats = {"sol_usd": usd, "points": {}}
    ts_all = sorted(r["t_create"] for r in rows)
    split = ts_all[len(ts_all) // 2] if ts_all else 0
    stats["split_ts"] = split
    for point, targets in (("A15", (10, 3)), ("G", (5, 3, 10)), ("B100000", (3, 5)), ("B1000000", (2, 3)),
                           ("B10000000", (2,))):
        pr = [r for r in rows if r["point"] == point and r["mult"] is not None and r["known"]]
        if point == "A15":
            pr = [r for r in pr if r["stratum"] == "rand"]  # the population the bot sees at 15 min
        stats["points"][point] = {"n": len(pr), "bands": band_table(pr, usd),
                                  "targets": {str(t): {**study(pr, t, split), "filters": filter_cost(pr, t, RULES)}
                                              for t in targets}}
    rand = [r for r in rows if r["stratum"] == "rand" and r["point"] == "A15"]
    allrand = {r["mint"] for r in rows if r["stratum"] == "rand"}
    stats["population"] = {
        "rand_tokens": len(allrand),
        "rand_graduated": len({r["mint"] for r in rows if r["stratum"] == "rand" and r["graduated"]}),
        "rand_instant": len({r["mint"] for r in rows if r["stratum"] == "rand" and r["instant_grad"]}),
        "grad_tokens": len({r["mint"] for r in rows if r["stratum"] == "grad"}),
        "grad_instant": len({r["mint"] for r in rows if r["stratum"] == "grad" and r["instant_grad"]}),
        "a15_known": len(rand),
        "skipped": skipped,
    }
    with open(os.path.join(outdir, "retro-stats.json"), "w") as f:
        json.dump(stats, f, indent=1)
    from retro import report
    report.main(outdir)
    print(json.dumps(stats["population"], indent=1))
    return stats
