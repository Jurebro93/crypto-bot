"""Automatic re-fit of the hype weights per class, with guardrails instead of a human.

A run per class: enough outcomes -> logistic fit -> each weight moves at most max_step of its value toward the
fit -> the candidate must score better than the current weights on both time halves (precision of the top fifth)
-> written to the learned dir and logged. If the applied weights lose to their predecessor rollback_runs times in a
row, the predecessor comes back.
"""
import time

from hype import evaluate, score
from learn import outcomes, store, weights


def precision_top(rows, w, share=0.2):
    """Hit rate among the top `share` of rows by score under weights w; None when too few rows."""
    if len(rows) < 10:
        return None
    scored = sorted(rows, key=lambda r: -score.score(r["features"], w))
    top = scored[:max(1, int(len(scored) * share))]
    return round(sum(r["hit"] for r in top) / len(top), 3)


def step(old, fit, cfg):
    """Move every weight at most max_step (share of its value, floor min_weight_floor) toward the fitted value."""
    new = dict(old)
    for k in set(old) | set(fit):
        o, f = old.get(k, 0.0), fit.get(k, 0.0)
        lim = cfg["max_step"] * max(abs(o), cfg["min_weight_floor"])
        new[k] = round(o + max(-lim, min(lim, f - o)), 1)
    return new


def _halves(rows):
    ts = sorted(r["ts"] for r in rows)
    cut = ts[len(ts) // 2]
    return [r for r in rows if r["ts"] < cut], [r for r in rows if r["ts"] >= cut]


def better(rows, old, new):
    """(ok, metric_old, metric_new): new must win overall and on both halves (ties do not count)."""
    mo, mn = precision_top(rows, old), precision_top(rows, new)
    if mo is None or mn is None or mn <= mo:
        return False, mo, mn
    for h in _halves(rows):
        po, pn = precision_top(h, old), precision_top(h, new)
        if po is not None and pn is not None and pn < po:
            return False, mo, mn
    return True, mo, mn


def run(con, cfg=None, now=None, apply=True, base=None):
    """One learning run over all classes. Returns [{klasa, n, applied, ...}]."""
    cfg = cfg or outcomes.config()
    now = now or time.time()
    base = base or score.load_weights()
    rows, thr = outcomes.rows(con, cfg, now)
    report = []
    for klasa in sorted(set(r["klasa"] for r in rows) | set(thr)):
        rk = [r for r in rows if r["klasa"] == klasa]
        old = weights.load(klasa, base)
        rec = {"klasa": klasa, "n": len(rk), "skok": thr[klasa], "applied": False, "old": old, "new": None,
               "metric_old": None, "metric_new": None, "note": ""}
        if len(rk) < cfg["min_rows"]:
            rec["note"] = f"premalo ishoda ({len(rk)} od potrebnih {cfg['min_rows']})"
        else:
            fit = evaluate.fit_weights(rk)
            if not fit:
                rec["note"] = "još nema nijednog skoka u podacima, nema se iz čega učiti"
            else:
                new = step(old, fit["weights"], cfg)
                ok, mo, mn = better(rk, old, new)
                rec.update(new=new, metric_old=mo, metric_new=mn)
                if ok:
                    rec["note"] = f"pogađanje među 20% najbolje ocijenjenih {mo} → {mn}"
                    if apply:
                        weights.save(klasa, new, now)
                        rec["applied"] = True
                else:
                    rec["note"] = f"nove težine nisu bile bolje i na starijim i na novijim podacima ({mo} prema {mn})"
        rec["rollback"] = _maybe_rollback(con, klasa, rk, cfg, apply) if rec["applied"] is False and rec["new"] else False
        store.log_run(con, now, klasa, rec["n"], rec["skok"], rec["applied"], rec["metric_old"], rec["metric_new"],
                      old, rec["new"] or {}, rec["note"])
        report.append(rec)
    store.prune_empty(con)
    con.commit()
    return report


def _maybe_rollback(con, klasa, rows, cfg, apply):
    """After rollback_runs runs in a row without an improvement, if the weights applied last lose on today's data
    to the ones they replaced (.prev), the previous ones come back."""
    from learn.weights import path
    import json
    import os
    last = store.runs(con, klasa, cfg["rollback_runs"])
    if len(last) < cfg["rollback_runs"] or any(r["applied"] for r in last):
        return False
    if not os.path.exists(path(klasa) + ".prev"):
        return False
    with open(path(klasa) + ".prev") as f:
        prev = json.load(f)
    po, pc = precision_top(rows, prev), precision_top(rows, weights.load(klasa))
    if po is not None and pc is not None and po > pc and apply:
        return weights.rollback(klasa)
    return False
