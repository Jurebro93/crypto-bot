"""A small gradient-boosted tree model in pure Python (no numpy, no new dependency, little RAM).

Why not LightGBM: the server has 512 MB and the live bot uses ~350 MB; numpy + lightgbm in a training process could
push the container over the limit and Render would restart everything. Our data is small (thousands of decision
points, ~50 signals), where a few dozen depth-3 trees on 16 histogram bins do the same job. Training runs in the
short `run_learn.py model` process, prediction is a few hundred comparisons per token.

What it adds over the linear weights: interactions (a KOL call means more in the US session, low liquidity is
fine on a fresh pump.fun token but not on an old one), signals that hurt (negative effect), and a probability that
can be calibrated ("40 %" = 4 out of 10).

Model JSON: {"feats": [...], "edges": {f: [cut, ...]}, "base": logit, "lr": x, "trees": [node, ...]}
node = {"f": feature, "t": bin threshold (go left when bin <= t), "l": node, "r": node} or {"v": leaf value}.
A missing feature has bin -1 and always goes left (learned like any other value: "not measured" is information).
"""
import math

DEFAULT = {"bins": 16, "depth": 3, "rounds": 80, "lr": 0.12, "lam": 1.0, "min_h": 3.0, "patience": 12,
           "min_rows": 300, "max_rows": 8000, "min_share": 0.02}


def _sig(z):
    return 1 / (1 + math.exp(-max(-30.0, min(30.0, z))))


def context(r, hyps=True):
    """Model inputs of one decision point: its stored signals plus the context the linear weights cannot use, plus
    one h_<id> flag per hypothesis that passed its test (learn/detektiv.py)."""
    x = dict(r.get("features") or {})
    for k in ("point", "klasa", "sess"):
        if r.get(k):
            x[f"{k}={r[k]}"] = 1.0
    for k in ("mcap", "liq"):
        v = r.get(k)
        if v and v > 0:
            x[f"log_{k}"] = math.log10(v)
    if r.get("score") is not None:
        x["hype_ocjena"] = float(r["score"])
    if hyps:
        try:
            from learn import detektiv
            for h in detektiv.passed():
                x[f"h_{h['id']}"] = 1.0 if detektiv.matches(h, r, x) else 0.0
        except Exception:  # noqa: BLE001 - no ai.db yet / unreadable: no hypothesis flags
            pass
    return x


def _edges(xs, bins):
    vals = sorted(v for v in xs if v is not None)
    if not vals:
        return []
    cuts = []
    for i in range(1, bins):
        c = vals[min(len(vals) - 1, int(len(vals) * i / bins))]
        if not cuts or c > cuts[-1]:
            cuts.append(c)
    return cuts[:-1] if len(cuts) > 1 and cuts[-1] >= vals[-1] else cuts


def _bin(v, cuts):
    if v is None:
        return -1
    lo, hi = 0, len(cuts)
    while lo < hi:  # first cut >= v
        mid = (lo + hi) // 2
        if cuts[mid] < v:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _encode(X, feats, edges):
    return [[_bin(x.get(f), edges[f]) for f in feats] for x in X]


def _best_split(idx, B, g, h, nf, nb, lam, min_h):
    G = sum(g[i] for i in idx)
    H = sum(h[i] for i in idx)
    parent = G * G / (H + lam)
    best = None
    for j in range(nf):
        gs = [0.0] * (nb + 1)  # slot 0 = missing (bin -1), slot b+1 = bin b
        hs = [0.0] * (nb + 1)
        for i in idx:
            b = B[i][j] + 1
            gs[b] += g[i]
            hs[b] += h[i]
        gl = hl = 0.0
        for b in range(nb):  # left = slots 0..b
            gl += gs[b]
            hl += hs[b]
            gr, hr = G - gl, H - hl
            if hl < min_h or hr < min_h:
                continue
            gain = gl * gl / (hl + lam) + gr * gr / (hr + lam) - parent
            if best is None or gain > best[0]:
                best = (gain, j, b - 1)
    return best


def _grow(idx, B, g, h, depth, cfg, nf, nb):
    G = sum(g[i] for i in idx)
    H = sum(h[i] for i in idx)
    leaf = {"v": -G / (H + cfg["lam"])}
    if depth == 0 or len(idx) < 2 * cfg["min_h"]:
        return leaf
    sp = _best_split(idx, B, g, h, nf, nb, cfg["lam"], cfg["min_h"])
    if not sp or sp[0] <= 1e-6:
        return leaf
    _, j, t = sp
    left = [i for i in idx if B[i][j] <= t]
    right = [i for i in idx if B[i][j] > t]
    if not left or not right:
        return leaf
    return {"f": j, "t": t, "l": _grow(left, B, g, h, depth - 1, cfg, nf, nb),
            "r": _grow(right, B, g, h, depth - 1, cfg, nf, nb)}


def _tree_out(node, b):
    while "v" not in node:
        node = node["l"] if b[node["f"]] <= node["t"] else node["r"]
    return node["v"]


def _logloss(y, w, z):
    s = sw = 0.0
    for yi, wi, zi in zip(y, w, z):
        p = min(1 - 1e-9, max(1e-9, _sig(zi)))
        s -= wi * (yi * math.log(p) + (1 - yi) * math.log(1 - p))
        sw += wi
    return s / (sw or 1)


def train(rows, cfg=None, weights=None):
    """rows: [{"x": {feature: value}, "y": 0/1, "ts": ...}] (any order). The newest 20% by time are validation
    (half for early stopping, half for calibration), so the model is judged on data it did not see; features,
    bins and everything else are learned on the older 80% only (purge_s gap between them). weights: per-row sample weights (time
    decay). Returns the model dict or None when there is too little data."""
    cfg = {**DEFAULT, **(cfg or {})}
    if len(rows) < cfg["min_rows"] or not any(r["y"] for r in rows) or all(r["y"] for r in rows):
        return None
    order = sorted(range(len(rows)), key=lambda i: rows[i]["ts"])[-cfg["max_rows"]:]
    rows = [rows[i] for i in order]
    w = [weights[i] for i in order] if weights else [1.0] * len(rows)
    n = len(rows)
    # audit 4.11. C12: split by time FIRST; features and bin edges come from the training part only; training rows
    # whose 24 h label window reaches the validation start are dropped; one half of validation stops early, the
    # other calibrates (they used to be the same rows)
    cut = int(n * 0.8)
    gap = cfg.get("purge_s", 24 * 3600)
    tr = [i for i in range(cut) if rows[i]["ts"] + gap <= rows[cut]["ts"]] if cut < n else []
    va = list(range(cut, n))
    if len(tr) < 10 or len(va) < 4:
        return None
    va_es, va_cal = va[::2], va[1::2]
    counts = {}
    for i in tr:
        for k in rows[i]["x"]:
            counts[k] = counts.get(k, 0) + 1
    feats = sorted(k for k, c in counts.items() if c >= cfg["min_share"] * len(tr))
    edges = {f: _edges([rows[i]["x"].get(f) for i in tr], cfg["bins"]) for f in feats}
    B = _encode([r["x"] for r in rows], feats, edges)
    y = [1.0 if r["y"] else 0.0 for r in rows]
    va = va_es
    pos = sum(y[i] * w[i] for i in tr) / (sum(w[i] for i in tr) or 1)
    base = math.log(max(1e-4, pos) / max(1e-4, 1 - pos))
    z = [base] * n
    trees, best, best_k, bad = [], _logloss([y[i] for i in va], [w[i] for i in va], [z[i] for i in va]), 0, 0
    nb = cfg["bins"] + 1
    for _ in range(cfg["rounds"]):
        g = [0.0] * n
        h = [0.0] * n
        for i in tr:
            p = _sig(z[i])
            g[i] = w[i] * (p - y[i])
            h[i] = w[i] * max(1e-6, p * (1 - p))
        t = _grow(tr, B, g, h, cfg["depth"], cfg, len(feats), nb)
        trees.append(t)
        for i in range(n):
            z[i] += cfg["lr"] * _tree_out(t, B[i])
        ll = _logloss([y[i] for i in va], [w[i] for i in va], [z[i] for i in va])
        if ll < best - 1e-5:
            best, best_k, bad = ll, len(trees), 0
        else:
            bad += 1
            if bad >= cfg["patience"]:
                break
    trees = trees[:best_k]
    if not trees:
        return None
    m = {"feats": feats, "edges": edges, "base": base, "lr": cfg["lr"], "trees": trees, "n": n,
         "val_logloss": round(best, 4), "pos_rate": round(pos, 4)}
    m["calib"] = calibrate(m, [rows[i] for i in va_cal])
    m["n_train"], m["n_val"] = len(tr), len(va_es) + len(va_cal)
    return m


def raw(model, x):
    b = [_bin(x.get(f), model["edges"][f]) for f in model["feats"]]
    return model["base"] + model["lr"] * sum(_tree_out(t, b) for t in model["trees"])


def predict(model, x):
    """Calibrated probability that this point is a win (see calibrate)."""
    p = _sig(raw(model, x))
    cal = model.get("calib")
    if not cal:
        return p
    for lo, hi, val in cal:  # isotonic-style bins on validation data
        if lo <= p < hi:
            return val
    return p


def calibrate(model, rows, nbins=5):
    """Bins of predicted probability on validation rows with the observed win rate in each, made monotone
    (pool-adjacent-violators): what "p" really meant on data the trees did not train on."""
    if len(rows) < 50:
        return None
    ps = sorted((_sig(raw({**model, "calib": None}, r["x"])), 1.0 if r["y"] else 0.0) for r in rows)
    size = max(1, len(ps) // nbins)
    groups = [ps[i:i + size] for i in range(0, len(ps), size)]
    blocks = [[g[0][0], g[-1][0], sum(y for _, y in g), len(g)] for g in groups]
    i = 0
    while i < len(blocks) - 1:  # merge while the rate goes down
        a, b = blocks[i], blocks[i + 1]
        if a[2] / a[3] > b[2] / b[3]:
            blocks[i] = [a[0], b[1], a[2] + b[2], a[3] + b[3]]
            del blocks[i + 1]
            i = max(0, i - 1)
        else:
            i += 1
    out = []
    for k, (lo, hi, s, c) in enumerate(blocks):
        out.append([0.0 if k == 0 else lo, 1.0 + 1e-9 if k == len(blocks) - 1 else blocks[k + 1][0],
                    round((s + 0.5) / (c + 1), 4)])
    return out


def importance(model, top=12):
    """How often each signal is used to split (a rough "what the model looks at")."""
    cnt = {}

    def walk(n):
        if "v" in n:
            return
        f = model["feats"][n["f"]]
        cnt[f] = cnt.get(f, 0) + 1
        walk(n["l"])
        walk(n["r"])
    for t in model["trees"]:
        walk(t)
    return sorted(cnt.items(), key=lambda kv: -kv[1])[:top]
