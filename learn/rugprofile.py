"""Rug profile: which entry profiles end as rugs, learned from the archived rugs (rugfilter/archive.py).

Nicholas, 1.11.: learn from the old rugged tokens so that new ones like them are not added.

Data: every token's FIRST hype signal (the same entry row the other learning loops use) older than the archive's
waiting time. Label 1 = the token was archived because it actually crashed or its liquidity was pulled (kinds
"srusen"/"likvidnost"); tokens only stopped by this profile or by rug mechanics are labelled by what really happened,
so the profile never learns from its own decisions. Inputs: the hype features (0-1), log liquidity, log market cap
and liquidity / market cap.

Guardrails (nothing is applied by hand, nothing is applied blindly):
- at least MIN_ROWS tokens and MIN_RUGS rugs;
- trained on the older half it must separate rugs on the newer half, and the other way round (AUC >= MIN_AUC both);
- a token is stopped only above a threshold chosen on held-out data where at least MIN_PRECISION of the stopped
  tokens really rugged AND at most MAX_HIT_LOSS of the class pumps ("skok", learn/outcomes) would have been stopped.
  Nicholas fears cutting future pumps (tiered plan, 31.10.), so without such a threshold nothing is stopped and the
  similarity is only shown.
Result: LEARNED_DIR/rugprofile.json; each run logged in learn_runs with klasa 'rugprofil'.
"""
import json
import math
import os
import time

MIN_ROWS = 200
MIN_RUGS = 30
MIN_AUC = 0.65
MIN_PRECISION = 0.85
MAX_HIT_LOSS = 0.05
MIN_BLOCKED = 5
FEATURE_MIN_SHARE = 0.05
MAX_ROWS = 5000   # newest tokens only: pure-Python fit stays around a minute in the daily run
THRESHOLDS = [round(0.5 + 0.05 * i, 2) for i in range(10)]   # 0.50 .. 0.95

NAMES = {"liq_log": "likvidnost", "mcap_log": "tržišna vrijednost", "liq_mcap": "likvidnost u odnosu na vrijednost"}


def path():
    d = os.environ.get("LEARNED_DIR") or os.path.join(os.environ.get("DATA_DIR") or
                                                       os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "learned")
    return os.path.join(d, "rugprofile.json")


_model = {"mtime": None, "m": None}


def load():
    """The saved model (cached by file time) or None."""
    p = path()
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return None
    if _model["mtime"] != mt:
        try:
            with open(p) as f:
                _model.update(mtime=mt, m=json.load(f))
        except (OSError, ValueError):
            return None
    return _model["m"]


def save(model):
    p = path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".tmp", "w") as f:
        json.dump(model, f)
    os.replace(p + ".tmp", p)


# ---------- inputs ----------

def inputs(features, mcap, liq):
    """{name: value} the profile reads: hype features as they are, plus market size inputs."""
    x = {k: float(v) for k, v in (features or {}).items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    x["liq_log"] = math.log10(liq) / 7 if liq and liq > 0 else 0.0
    x["mcap_log"] = math.log10(mcap) / 9 if mcap and mcap > 0 else 0.0
    x["liq_mcap"] = min(1.0, liq / mcap) if liq and mcap else 0.0
    return x


def dataset(con, now=None):
    """[{token, ts, y, hit, x}] from first signals, archive labels and class-relative pump outcomes."""
    from learn import outcomes
    from rugfilter import archive
    now = now or time.time()
    con.executescript(archive.SCHEMA)
    rugs = {t for (t,) in con.execute(f"SELECT token FROM rug_archive WHERE kind IN ({','.join('?' * len(archive.KINDS_REAL))})",
                                      archive.KINDS_REAL)}
    try:
        orows, _ = outcomes.rows(con, now=now)
        hits = {r["token"]: bool(r["hit"]) for r in orows}
    except Exception:  # noqa: BLE001 - without outcomes the pump-loss guard cannot be checked, hits stay unknown
        hits = {}
    cutoff = int(now - archive.MIN_AGE_H * 3600)
    out = []
    for t, ts, mcap, liq, feats in con.execute(
            "SELECT s.token, s.ts, s.mcap, s.liquidity, s.features FROM hype_signals s JOIN "
            "(SELECT token, MIN(ts) ts FROM hype_signals GROUP BY token) f ON s.token=f.token AND s.ts=f.ts WHERE s.ts <= ?",
            (cutoff,)):
        try:
            fd = json.loads(feats) if feats else {}
        except ValueError:
            fd = {}
        out.append({"token": t, "ts": ts, "y": 1 if t in rugs else 0, "hit": hits.get(t), "x": inputs(fd, mcap, liq)})
    return out


# ---------- model ----------

def _keys(rows):
    cnt = {}
    for r in rows:
        for k, v in r["x"].items():
            if v:
                cnt[k] = cnt.get(k, 0) + 1
    return sorted(k for k, n in cnt.items() if n >= FEATURE_MIN_SHARE * len(rows))


def fit(rows, keys, epochs=150, lr=0.3, l2=0.01):
    """Logistic regression on standardised inputs. Returns {keys, mu, sd, w, b}."""
    n = len(rows)
    mu = {k: sum(r["x"].get(k, 0.0) for r in rows) / n for k in keys}
    sd = {k: (sum((r["x"].get(k, 0.0) - mu[k]) ** 2 for r in rows) / n) ** 0.5 or 1.0 for k in keys}
    X = [[(r["x"].get(k, 0.0) - mu[k]) / sd[k] for k in keys] for r in rows]
    Y = [r["y"] for r in rows]
    pos = sum(Y) or 1
    wpos = (n - pos) / pos   # rugs are often the majority or the minority: balance the classes
    w, b = [0.0] * len(keys), 0.0
    for _ in range(epochs):
        gw, gb, tot = [0.0] * len(keys), 0.0, 0.0
        for xi, yi in zip(X, Y):
            z = b + sum(a * c for a, c in zip(w, xi))
            p = 1 / (1 + math.exp(-max(-30, min(30, z))))
            cw = wpos if yi else 1.0
            e = (p - yi) * cw
            tot += cw
            gb += e
            for j, v in enumerate(xi):
                gw[j] += e * v
        b -= lr * gb / tot
        w = [wj - lr * (gj / tot + l2 * wj) for wj, gj in zip(w, gw)]
    return {"keys": keys, "mu": mu, "sd": sd, "w": dict(zip(keys, w)), "b": b}


def prob(model, x):
    if not model:
        return None
    z = model["b"] + sum(model["w"][k] * (x.get(k, 0.0) - model["mu"][k]) / model["sd"][k] for k in model["keys"])
    return 1 / (1 + math.exp(-max(-30, min(30, z))))


def auc(scores, ys):
    pos = [s for s, y in zip(scores, ys) if y]
    neg = [s for s, y in zip(scores, ys) if not y]
    if not pos or not neg:
        return None
    allv = sorted([(s, 1) for s in pos] + [(s, 0) for s in neg])
    rank, i, rsum = 0, 0, 0.0
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
            j += 1
        avg = (i + j) / 2 + 1
        rsum += avg * sum(1 for k in range(i, j + 1) if allv[k][1])
        i = j + 1
    return (rsum - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def threshold(test, probs):
    """Lowest threshold (stops the most rugs) that is precise enough and costs almost no pumps, or None."""
    hits_total = sum(1 for r in test if r["hit"])
    for thr in THRESHOLDS:
        sel = [r for r, p in zip(test, probs) if p >= thr]
        if len(sel) < MIN_BLOCKED:
            continue
        prec = sum(r["y"] for r in sel) / len(sel)
        lost = sum(1 for r in sel if r["hit"])
        if prec >= MIN_PRECISION and (lost / hits_total if hits_total else 0) <= MAX_HIT_LOSS:
            return {"thr": thr, "precision": round(prec, 3), "stopped": len(sel), "share_rugs": round(
                sum(r["y"] for r in sel) / max(1, sum(r["y"] for r in test)), 3), "hits_lost": lost, "hits": hits_total}
    return None


def run(con, now=None, apply_model=True):
    """One guarded fit. Returns {"n", "rugs", "applied", "note", ...}."""
    now = now or time.time()
    rows = sorted(dataset(con, now), key=lambda r: r["ts"])[-MAX_ROWS:]
    n, nr = len(rows), sum(r["y"] for r in rows)
    res = {"n": n, "rugs": nr, "applied": False, "note": ""}
    if n < MIN_ROWS or nr < MIN_RUGS or nr == n:
        res["note"] = f"premalo podataka ({n} tokena, {nr} rugova; treba {MIN_ROWS} i {MIN_RUGS}), samo se skuplja"
        _log(con, now, res)
        return res
    keys = _keys(rows)
    old, new = rows[:n // 2], rows[n // 2:]
    m_old, m_new = fit(old, keys), fit(new, keys)
    p_new = [prob(m_old, r["x"]) for r in new]
    p_old = [prob(m_new, r["x"]) for r in old]
    a1, a2 = auc(p_new, [r["y"] for r in new]), auc(p_old, [r["y"] for r in old])
    res.update(auc_new=None if a1 is None else round(a1, 3), auc_old=None if a2 is None else round(a2, 3))
    if a1 is None or a2 is None or min(a1, a2) < MIN_AUC:
        res["note"] = (f"profil ruga ne razlikuje dovoljno dobro (AUC {a1 or 0:.2f} / {a2 or 0:.2f} < {MIN_AUC}); "
                       "ništa se ne blokira")
        _log(con, now, res)
        if apply_model:
            save({"ts": int(now), "active": False, "thr": None, **res, "model": fit(rows, keys)})
        return res
    thr = threshold(new, p_new)
    model = fit(rows, keys)
    top = sorted(model["w"].items(), key=lambda kv: -abs(kv[1]))[:8]
    res.update(thr=thr["thr"] if thr else None, check=thr, top=[(k, round(v, 3)) for k, v in top])
    res["applied"] = bool(apply_model)
    res["note"] = (f"AUC {a1:.2f}/{a2:.2f}; " + (
        f"blokira nove tokene sa sličnošću ≥ {thr['thr']:.0%} (na provjeri {thr['precision']:.0%} od njih stvarno rugano, "
        f"izgubljeno {thr['hits_lost']} od {thr['hits']} skokova)" if thr else
        "nijedan prag nije dovoljno siguran za blokiranje, sličnost se samo prikazuje"))
    if apply_model:
        save({"ts": int(now), "active": bool(thr), "thr": thr["thr"] if thr else None, **res, "model": model})
    _log(con, now, res)
    return res


def _log(con, now, res):
    try:
        from learn import store
        store.log_run(con, int(now), "rugprofil", res["n"], None, 1 if res.get("applied") and res.get("thr") else 0,
                      res.get("auc_old"), res.get("auc_new"), {}, {}, res["note"])
        con.commit()
    except Exception:  # noqa: BLE001 - logging must not break the fit
        pass


# ---------- use in the scan ----------

def judge(features, mcap, liq, saved=None):
    """(similarity 0-1 or None, stop: bool). stop only when the saved profile passed its guardrails."""
    saved = saved if saved is not None else load()
    if not saved or not saved.get("model"):
        return None, False
    p = prob(saved["model"], inputs(features, mcap, liq))
    return p, bool(saved.get("active") and saved.get("thr") is not None and p >= saved["thr"])


def explain(saved=None):
    """Plain Croatian lines about what makes a token look like the rugs (for the Učenje page)."""
    saved = saved if saved is not None else load()
    if not saved or not saved.get("model"):
        return []
    out = []
    for k, w in sorted(saved["model"]["w"].items(), key=lambda kv: -abs(kv[1]))[:6]:
        out.append((NAMES.get(k, k), "više → češće rug" if w > 0 else "više → rjeđe rug", round(w, 2)))
    return out
