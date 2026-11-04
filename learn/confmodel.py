"""Learned confidence: the hand-set confidence parts (ui/confidence.parts_keyed) re-weighed from real outcomes.

Every day (run_learn.py, after the hype weights) the same facts the confidence lists for a token (smart money
bought, rug PROLAZI, KOL call, low liquidity, concentrated holders, ...) are fitted as indicators in a logistic
regression against the class-relative "skok" of learn/outcomes. The fitted model is applied only when it beats
the hand-set points at picking skokovi among the top fifth of tokens, overall and on both time halves, and only
with at least `min_rows` outcomes. The model lives in LEARNED_DIR/confidence.json (previous one in .prev).

With the model in place confidence means: 50 = an average token of its class, 75 = three times the class's skok
rate, 90 = nine times; 0 = no chance at all. Every part still shows its points: the points are what the confidence loses when
that fact is taken away, so the pop-up stays honest about why the number is what it is.
"""
import json
import math
import os
import sqlite3
import time

from learn import outcomes, store, weights

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUG_DB = os.path.join(HERE, "rug.db")
NAME = "confidence"
HR = {"hype": "hype ocjena", "x_buzz": "X buzz", "smart_money": "smart money", "kol": "KOL", "telegram": "Telegram kanali",
      "x_trend": "trending na X-u", "event": "pravi token eventa", "holders_ok": "zdravi holderi",
      "holders_conc": "koncentrirani holderi", "rug_ok": "rug PROLAZI", "rug_oprez": "rug OPREZ", "rug_rizik": "rug VISOK RIZIK",
      "liq_low": "mala likvidnost", "mcap_big": "velik mcap", "top_chase": "kupnja vrha", "snaga_volumen": "drži volumen",
      "rast_holdera": "rast holdera", "organski": "organski promet"}


def path():
    return os.path.join(weights.LEARNED_DIR, f"{NAME}.json")


def load():
    try:
        with open(path()) as f:
            return json.load(f)
    except Exception:
        return None


def save(model, now=None):
    os.makedirs(weights.LEARNED_DIR, exist_ok=True)
    p = path()
    if os.path.exists(p):
        os.replace(p, p + ".prev")
    model = {**model, "ts": int(now or time.time())}
    with open(p + ".tmp", "w") as f:
        json.dump(model, f, indent=1)
    os.replace(p + ".tmp", p)
    return model


# ---------- dataset ----------

RUG_MAX_AGE_S = 6 * 3600   # a rug check older than this at the decision is "unknown", not still valid


def _rug_verdicts(tokens, max_age_s=RUG_MAX_AGE_S):
    """mint -> verdict of the newest rug check that EXISTED at the first signal (checked_at <= signal, at most
    max_age_s old). Audit 4.11. C06/R2: a check made after the decision (it used to take the closest one up to a
    day later) is the future and never enters the dataset; no check then = unknown (left out)."""
    if not os.path.exists(RUG_DB):
        return {}
    try:
        con = sqlite3.connect(f"file:{RUG_DB}?mode=ro", uri=True, timeout=10)
        try:
            rows = con.execute("SELECT mint, checked_at, verdict FROM rug_reports ORDER BY checked_at").fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return {}
    out = {}
    for mint, at, verdict in rows:
        ts = tokens.get(mint)
        if ts is not None and at <= ts and ts - at <= max_age_s:
            out[mint] = verdict          # rows are in time order: the last one kept is the newest before ts
    return out


def dataset(con, cfg=None, now=None):
    """[{token, ts, klasa, hit, hype, parts:[(key, points, text)], keys:{key: 1}}] from outcomes + details + rug."""
    from ui import confidence
    rows, thr = outcomes.rows(con, cfg, now)
    if not rows:
        return [], thr
    first = {r["token"]: r["ts"] for r in rows}
    sig = {t: (liq, mcap) for t, liq, mcap in con.execute(
        "SELECT s.token, s.liquidity, s.mcap FROM hype_signals s JOIN (SELECT token, MIN(ts) ts FROM hype_signals GROUP BY token) f "
        "ON s.token=f.token AND s.ts=f.ts")}
    dets = {}
    for t, ts, extra in con.execute("SELECT token, ts, extra FROM hype_details ORDER BY ts"):
        if t in first and ts <= first[t] + 60:
            dets[t] = extra    # newest details known at the first signal (+60 s: written in the same scan); R2
    rug = _rug_verdicts(first)
    out = []
    for r in rows:
        liq, mcap = sig.get(r["token"], (None, None))
        try:
            extra = json.loads(dets[r["token"]]) if r["token"] in dets else {}
        except Exception:
            extra = {}
        role = "canonical" if (r["features"] or {}).get("calendar") else None
        parts = confidence.parts_keyed(r["score"], r["features"], extra, rug.get(r["token"]), role, liq, mcap)
        if parts and parts[0][0] == "odbacen":
            continue  # a hard rejection is never learned, it is a rule
        out.append({"token": r["token"], "ts": r["ts"], "klasa": r["klasa"], "hit": bool(r["hit"]), "hype": r["score"] or 0,
                    "parts": parts, "keys": {k: 1.0 for k, _, _ in parts if k != "hype"}})
    return out, thr


# ---------- model ----------

def _x(row, keys):
    v = [1.0 if k in row["keys"] else 0.0 for k in keys]
    v.append((row["hype"] or 0) / 100)
    return v


def fit(rows, epochs=400, lr=0.5, l2=0.01):
    """Logistic regression hit ~ indicators + hype/100; {coef:{key}, hype, bias, base:{klasa: rate}, n}."""
    if len(rows) < 30 or not any(r["hit"] for r in rows) or all(r["hit"] for r in rows):
        return None
    keys = sorted({k for r in rows for k in r["keys"]})
    xs = [_x(r, keys) for r in rows]
    w, b = [0.0] * (len(keys) + 1), 0.0
    for _ in range(epochs):
        gw, gb = [0.0] * len(w), 0.0
        for x, r in zip(xs, rows):
            z = b + sum(wi * xi for wi, xi in zip(w, x))
            err = 1 / (1 + math.exp(-max(-30, min(30, z)))) - r["hit"]
            gb += err
            for i, xi in enumerate(x):
                gw[i] += err * xi
        b -= lr * gb / len(rows)
        w = [wi - lr * (gi / len(rows) + l2 * wi) for wi, gi in zip(w, gw)]
    base = {}
    for k in sorted({r["klasa"] for r in rows}):
        rk = [r for r in rows if r["klasa"] == k]
        base[k] = sum(r["hit"] for r in rk) / len(rk)
    base["*"] = sum(r["hit"] for r in rows) / len(rows)
    return {"coef": {k: round(v, 4) for k, v in zip(keys, w)}, "hype": round(w[-1], 4), "bias": round(b, 4),
            "base": {k: round(v, 4) for k, v in base.items()}, "n": len(rows)}


def prob(model, keys, hype):
    z = model["bias"] + model["hype"] * (hype or 0) / 100 + sum(model["coef"].get(k, 0.0) for k in keys)
    return 1 / (1 + math.exp(-max(-30, min(30, z))))


def _scale(model, p, klasa):
    """0-100 relative to the class: p = base rate -> 50, 3x the base -> 75, 9x -> 90; never saturates at 100."""
    base = model["base"].get(klasa or "*") or model["base"].get("*") or 1e-9
    return max(0, min(100, round(100 * p / (p + base))))


def apply(model, parts, hype, klasa=None):
    """(confidence, {key: points}) for a token's keyed parts. Points of a part = confidence lost without it."""
    keys = {k for k, _, _ in parts if k != "hype"}
    total = _scale(model, prob(model, keys, hype), klasa)
    pts = {}
    for k in keys:
        pts[k] = round(total - _scale(model, prob(model, keys - {k}, hype), klasa), 1)
    if any(k == "hype" for k, _, _ in parts):
        pts["hype"] = round(total - _scale(model, prob(model, keys, 0), klasa), 1)
    return total, pts


def conf_of(model, row):
    return apply(model, row["parts"], row["hype"], row["klasa"])[0] if model else None


# ---------- guardrails ----------

def precision_top(rows, scorer, share=0.2):
    if len(rows) < 10:
        return None
    top = sorted(rows, key=lambda r: -scorer(r))[:max(1, int(len(rows) * share))]
    return round(sum(r["hit"] for r in top) / len(top), 3)


def _halves(rows):
    ts = sorted(r["ts"] for r in rows)
    cut = ts[len(ts) // 2]
    return [r for r in rows if r["ts"] < cut], [r for r in rows if r["ts"] >= cut]


def hand_scorer(r):
    from ui import confidence
    return confidence.hand_total(r["parts"])


def better(rows, old_scorer, new_scorer):
    mo, mn = precision_top(rows, old_scorer), precision_top(rows, new_scorer)
    if mo is None or mn is None or mn <= mo:
        return False, mo, mn
    for h in _halves(rows):
        po, pn = precision_top(h, old_scorer), precision_top(h, new_scorer)
        if po is not None and pn is not None and pn <= po:   # ties do not count (C04)
            return False, mo, mn
    return True, mo, mn


def calibration(rows, scorer, step=20):
    """[(bucket, n, skok_rate)] : how often tokens in each confidence band actually made the class skok."""
    out = []
    for lo in range(0, 100, step):
        b = [r for r in rows if lo <= scorer(r) < lo + step or (lo + step == 100 and scorer(r) == 100)]
        if b:
            out.append((f"{lo}-{lo + step}", len(b), round(sum(r["hit"] for r in b) / len(b), 3)))
    return out


def flat(model):
    """Coefficients as one flat {name: value} dict, the shape learn_runs and the Učenje page expect."""
    if not model:
        return {}
    return {**{HR.get(k, k): v for k, v in model["coef"].items()}, "hype ocjena": model["hype"], "osnova": model["bias"]}


def run(con, cfg=None, now=None, apply_model=True):
    """One guarded learning run for the confidence model; logged in learn_runs under klasa 'confidence'."""
    cfg = cfg or outcomes.config()
    now = now or time.time()
    rows, _ = dataset(con, cfg, now)
    current = load()
    old_scorer = (lambda r: conf_of(current, r)) if current else hand_scorer
    rec = {"n": len(rows), "applied": False, "metric_old": None, "metric_new": None, "note": "", "model": None}
    if len(rows) < cfg["min_rows"]:
        rec["note"] = f"premalo ishoda ({len(rows)} od potrebnih {cfg['min_rows']})"
    else:
        from learn import split   # audit 4.11. C04: fit on the older part, judge on the newer part it never saw
        train, val = split.by_time(rows, horizon_s=cfg.get("purge_h", cfg.get("horizon_h", 24)) * 3600)
        model = fit(train) if len(train) >= 10 and len(val) >= 20 else None
        if not model:
            rec["note"] = ("premalo za odvojeno učenje i provjeru" if len(train) < 10 or len(val) < 20 else
                           "još nema nijednog skoka u podacima, nema se iz čega učiti")
        else:
            ok, mo, mn = better(val, old_scorer, lambda r: conf_of(model, r))
            rec.update(metric_old=mo, metric_new=mn, model=model)
            if ok:
                rec["note"] = f"pogađanje među 20% najbolje ocijenjenih {mo} → {mn}"
                if apply_model:
                    save(model, now)
                    rec["applied"] = True
            else:
                rec["note"] = f"naučeni confidence nije bio bolji od {'trenutnog' if current else 'ručnog'} i na starijim i na novijim podacima ({mo} prema {mn})"
    store.log_run(con, now, NAME, rec["n"], None, rec["applied"], rec["metric_old"], rec["metric_new"],
                  flat(current), flat(rec["model"]), rec["note"])
    con.commit()
    return rec
