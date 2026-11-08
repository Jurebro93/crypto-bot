"""How good were past signals? Outcomes from price snapshots, report by score bucket and feature,
paper trading, and a logistic-regression fit that suggests new weights.

A signal is judged on the first time a token was logged. Max return is the best snapshot inside the
horizon, so it is only as fine as the polling interval of `watch` / `track`.
"""
import json
import math


def outcomes(con, horizon_h=24, hit=1.0, rug_liq=0.2, now=None):
    """One row per token: features at first signal plus max/end return and rug flag within horizon."""
    import time
    now = now or time.time()
    rows = con.execute("""SELECT s.token, s.symbol, s.ts, s.score, s.price, s.liquidity, s.features
                          FROM hype_signals s JOIN (SELECT token, MIN(ts) ts FROM hype_signals GROUP BY token) f
                          ON s.token = f.token AND s.ts = f.ts WHERE s.ts <= ? AND s.price > 0""",
                       (now - horizon_h * 3600,)).fetchall()
    out = []
    for token, symbol, ts, score, price, liq, feats in rows:
        snaps = con.execute("SELECT ts, price, liquidity FROM hype_snapshots WHERE token=? AND ts>? AND ts<=? "
                            "ORDER BY ts", (token, ts, ts + horizon_h * 3600)).fetchall()
        if not snaps:
            continue
        path = [p / price - 1 for _, p, _ in snaps if p]
        max_ret, end_ret = max(path), path[-1]
        # second-highest snapshot: one wick (or a dust print) does not make a pump; the retrospective used this
        max2_ret = sorted(path)[-2] if len(path) >= 2 else max_ret
        rug = bool(liq) and (snaps[-1][2] or 0) < rug_liq * liq
        out.append({"token": token, "symbol": symbol, "ts": ts, "score": score, "features": json.loads(feats),
                    "path": path, "max_ret": max_ret, "max2_ret": max2_ret, "end_ret": -1.0 if rug else end_ret,
                    "hit": max_ret >= hit, "rug": rug})
    return out


def by_bucket(rows, step=20):
    res = []
    for lo in range(0, 100, step):
        b = [r for r in rows if lo <= r["score"] < lo + step]
        if b:
            res.append({"bucket": f"{lo}-{lo + step}", "n": len(b),
                        "hit_rate": round(sum(r["hit"] for r in b) / len(b), 2),
                        "rug_rate": round(sum(r["rug"] for r in b) / len(b), 2),
                        "median_end": round(sorted(r["end_ret"] for r in b)[len(b) // 2], 2)})
    return res


def feature_lift(rows):
    """Hit rate when a feature is strong (>= 0.5) vs weak. Audit 4.11. C10: two named ratios, never one bare "lift".
    lift = lift_vs_all = hit_strong / base (all tokens); lift_vs_weak = hit_strong / hit_weak. Lift > 1 = helps."""
    res = []
    base = sum(r["hit"] for r in rows) / len(rows) if rows else 0
    for f in sorted({k for r in rows for k in r["features"]}):
        hi = [r for r in rows if r["features"].get(f, 0) >= 0.5]
        lo = [r for r in rows if r["features"].get(f, 0) < 0.5]
        hr = sum(r["hit"] for r in hi) / len(hi) if hi else 0
        lr = sum(r["hit"] for r in lo) / len(lo) if lo else 0
        res.append({"feature": f, "n_strong": len(hi), "hit_strong": round(hr, 2), "hit_weak": round(lr, 2),
                    "base": round(base, 2), "lift": round(hr / base, 2) if base and hi else None,
                    "lift_vs_weak": round(hr / lr, 2) if lr and hi else None})
    return res


def paper_trade(rows, min_score=60, tp=1.0, sl=-0.5, size=1.0):
    """Buy every signal >= min_score at the signal price; sell at TP, SL, or horizon end."""
    trades = []
    for r in rows:
        if r["score"] < min_score:
            continue
        exit_ret = r["end_ret"]
        for x in r["path"]:
            if x >= tp:
                exit_ret = tp
                break
            if x <= sl:
                exit_ret = sl
                break
        trades.append(exit_ret)
    if not trades:
        return {"trades": 0}
    return {"trades": len(trades), "win_rate": round(sum(t > 0 for t in trades) / len(trades), 2),
            "avg_ret": round(sum(trades) / len(trades), 3), "pnl": round(size * sum(trades), 2)}


def fit_weights(rows, epochs=400, lr=0.5, l2=0.01):
    """Logistic regression hit ~ features; coefficients rescaled so the positive ones sum to 100. A negative
    coefficient stays negative (before 2.11. it was cut to 0, so a signal that hurts could never be penalised);
    score.score subtracts it."""
    rows = [{**r, "features": {k: v for k, v in r["features"].items() if isinstance(v, (int, float))
                                and not isinstance(v, bool)}} for r in rows]   # 8.11.: a text or None is no feature
    feats = sorted({k for r in rows for k in r["features"]})
    if len(rows) < 30 or not any(r["hit"] for r in rows):
        return None
    w, b = {f: 0.0 for f in feats}, 0.0
    sw = [r.get("w", 1.0) for r in rows]  # sample weight: newer outcomes count more (learn/fit time decay)
    tot = sum(sw) or 1
    for _ in range(epochs):
        gw, gb = {f: 0.0 for f in feats}, 0.0
        for r, wi in zip(rows, sw):
            z = b + sum(w[f] * r["features"].get(f, 0) for f in feats)
            err = wi * (1 / (1 + math.exp(-max(-30, min(30, z)))) - r["hit"])
            gb += err
            for f in feats:
                gw[f] += err * r["features"].get(f, 0)
        b -= lr * gb / tot
        for f in feats:
            w[f] -= lr * (gw[f] / tot + l2 * w[f])
    total = sum(max(0.0, v) for v in w.values()) or 1
    return {"weights": {f: round(100 * v / total, 1) for f, v in w.items()},
            "coefficients": {f: round(v, 3) for f, v in w.items()}, "n": len(rows)}
