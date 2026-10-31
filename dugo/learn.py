"""Learning the weights of both lists from history, with guardrails and no human step.

Backtest on the stored daily candles: every 7th day of every token is an "anchor"; features are computed from the
candles up to that day only, the outcome is the token's return over the next `horizont_d` days minus SOL's
(so a list that only rides the market learns nothing). Social and liquidity features have no history, so only
candle features are re-weighed; the others keep their weights.

Guardrails (same spirit as learn/ for the hype weights):
- at least `min_uzoraka` anchors, otherwise nothing changes;
- a step moves weights only `korak` (20%) of the way towards what the data suggests;
- the new weights must pick better top-20% tokens than the current ones in BOTH halves of history (older/newer);
- the previous weights are kept; if they beat the current ones on the newest third, the bot rolls back.
"""
import json
import math
import os
import time

from dugo import features, score as sc, store
from learn import weights as lw

CANDLE_FEATS = {"starost_d", "oporavaka", "udio_oporavaka", "korelacija_btc", "rast_s_btc", "rast_s_sol", "ma30_iznad_ma90",
                "iznad_ma30", "pad_od_vrha", "volatilnost", "od_dna_30d", "volumen_trend", "povrat_7d", "pregrijan"}
D = 86400


def path():
    return os.path.join(lw.LEARNED_DIR, "dugo.json")


def load_learned():
    try:
        with open(path()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def current(cfg):
    """{kind: weights} in use: learned when present, else config.json."""
    L = load_learned()
    # new features added to config.json later keep their starting weight until learning touches them
    return {k: {**cfg["tezine"][k], **(L.get(k) or {})} for k in ("dugorocni", "budjenje")}


def samples(con, cfg, kind, step_d=7):
    """[(anchor_day, mint, features, excess_return)]"""
    sol = store.ref(con, "SOL")
    btc = store.ref(con, "BTC")
    h = cfg["ucenje"]["horizont_d"]
    g = cfg[kind]
    out = []
    for (mint,) in con.execute("SELECT DISTINCT mint FROM candles"):
        cs = store.candles(con, mint)
        if len(cs) < g["min_starost_d"] + h:
            continue
        for i in range(g["min_starost_d"], len(cs) - h, step_d):
            day = cs[i][0]
            past = cs[:i + 1]
            if sum(c[5] or 0 for c in past[-7:]) / 7 < 20000:     # dead or tiny then: not a real candidate
                continue
            f = features.compute(past, sol, btc)
            if not f:
                continue
            p7 = f.get("povrat_7d")
            f["pregrijan"] = max(0.0, p7 - 1.0) if p7 is not None else None
            if kind == "budjenje" and not ((f.get("pad_od_vrha") or 0) <= g["max_pad_od_vrha"]
                                            and (f.get("od_dna_30d") or 0) >= g["min_od_dna_30d"]):
                continue
            r = features.forward(cs, day, h)
            s0, s1 = sol.get(day), sol.get(day + h * D)
            if r is None or not s0 or not s1:
                continue
            out.append((day, mint, f, math.log(1 + max(r, -0.99)) - math.log(s1 / s0)))
    return out


def _by_day(smp):
    days = {}
    for d, m, f, y in smp:
        days.setdefault(d, []).append((m, f, y))
    return days


def top_return(smp, w, share=0.2):
    """Mean excess return of the top `share` by score, per anchor day, averaged over days with >= 5 tokens."""
    res = []
    for d, rows in _by_day(smp).items():
        if len(rows) < 5:
            continue
        s = sc.score({m: f for m, f, _ in rows}, w)
        ys = {m: y for m, _, y in rows}
        top = sorted(s, key=lambda m: -s[m][0])[:max(1, int(len(rows) * share))]
        res.append(sum(ys[m] for m in top) / len(top))
    return sum(res) / len(res) if res else None


def _ic(smp, c):
    vals = []
    for d, rows in _by_day(smp).items():
        if len(rows) < 5:
            continue
        p = sc._pct({m: f.get(c) for m, f, _ in rows})
        q = sc._pct({m: y for m, _, y in rows})
        ks = [m for m in p if m in q]
        if len(ks) < 5:
            continue
        mx = sum(p[k] for k in ks) / len(ks)
        my = sum(q[k] for k in ks) / len(ks)
        num = sum((p[k] - mx) * (q[k] - my) for k in ks)
        den = (sum((p[k] - mx) ** 2 for k in ks) * sum((q[k] - my) ** 2 for k in ks)) ** 0.5
        if den:
            vals.append(num / den)
    return sum(vals) / len(vals) if vals else None


def fit(con, cfg, kind, now=None, write=True):
    """One guarded learning step for one list. Returns a dict describing what happened."""
    now = int(now or time.time())
    uc = cfg["ucenje"]
    L = load_learned()
    cur = {**cfg["tezine"][kind], **(L.get(kind) or {})}
    smp = samples(con, cfg, kind)
    res = {"kind": kind, "n": len(smp), "applied": 0, "before": None, "after": None, "note": ""}
    if len(smp) < uc["min_uzoraka"]:
        res["note"] = f"premalo povijesti ({len(smp)} < {uc['min_uzoraka']}), težine ostaju"
        return _log(con, res, cur, now, write)
    days = sorted({d for d, *_ in smp})
    cut = days[len(days) // 2]
    old, new_half = [s for s in smp if s[0] < cut], [s for s in smp if s[0] >= cut]
    prev = (L.get("prev") or {}).get(kind)
    if prev:
        recent = [s for s in smp if s[0] >= days[2 * len(days) // 3]]
        a, b = top_return(recent, cur), top_return(recent, prev)
        if a is not None and b is not None and b > a:
            L[kind], L.setdefault("prev", {})[kind] = prev, None
            res.update(applied=-1, before=a, after=b, note="prethodne težine bolje na najnovijim podacima: vraćene")
            return _log(con, res, prev, now, write, L)
    total = sum(abs(v) for v in cur.values())
    target = dict(cur)
    for c in cur:
        if c in CANDLE_FEATS:
            ic = _ic(smp, c)
            if ic is not None:
                target[c] = max(-2.0, min(2.0, ic * 20))
    new = {c: round(cur[c] + uc["korak"] * (target[c] - cur[c]), 3) for c in cur}
    s = sum(abs(v) for v in new.values())
    if s and total:
        new = {c: round(v * total / s, 3) for c, v in new.items()}
    b0, b1 = top_return(old, cur), top_return(new_half, cur)
    a0, a1 = top_return(old, new), top_return(new_half, new)
    res.update(before=top_return(smp, cur), after=top_return(smp, new))
    if None in (a0, a1, b0, b1) or not (a0 > b0 and a1 > b1):
        res["note"] = "nove težine nisu bolje u obje polovice povijesti: ostaju stare"
        return _log(con, res, cur, now, write)
    L.setdefault("prev", {})[kind] = cur
    L[kind] = new
    res.update(applied=1, note="nove težine bolje u starijoj i novijoj polovici: primijenjene")
    return _log(con, res, new, now, write, L)


def _log(con, res, w, now, write, L=None):
    if write:
        if L is not None:
            os.makedirs(lw.LEARNED_DIR, exist_ok=True)
            with open(path(), "w") as f:
                json.dump(L, f, indent=1)
        con.execute("INSERT INTO learn_runs VALUES (?,?,?,?,?,?,?,?)",
                    (now, res["kind"], res["applied"], res["n"], res["before"], res["after"], res["note"], store.dumps(w)))
        con.commit()
    res["weights"] = w
    return res
