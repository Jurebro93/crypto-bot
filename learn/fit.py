"""Automatic re-fit of the hype weights per class, with guardrails instead of a human.

A run per class: enough outcomes -> split by time BEFORE fitting (learn/split.py: older 70% train, newer 30%
validation, label windows overlapping the validation removed) -> logistic fit on train only -> each weight moves
at most max_step of its value toward the fit -> the candidate must beat the current weights on the validation part
and on both of its halves, ties do not count (precision of the top fifth) -> written to the learned dir and logged.
Audit 4.11. C04: it used to fit and judge on the same rows. C05: with cilj "zarada" a class without enough shadow
outcomes says "nedovoljno podataka" instead of quietly learning the peak under the same name. If the applied weights lose to their predecessor rollback_runs times in a
row, the predecessor comes back.
"""
import time

from hype import evaluate, score
from learn import outcomes, split, store, weights


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
        if po is not None and pn is not None and pn <= po:   # a tie on a half is not a win (C04)
            return False, mo, mn
    return True, mo, mn


def run(con, cfg=None, now=None, apply=True, base=None, shadow_path=None):
    """One learning run over all classes. Returns [{klasa, n, applied, ...}]."""
    cfg = cfg or outcomes.config()
    now = now or time.time()
    base = base or score.load_weights()
    rows, thr = outcomes.rows(con, cfg, now)
    sh = []
    if cfg.get("cilj") == "zarada":
        try:
            sh = outcomes.shadow_rows(cfg, now, shadow_path)
        except Exception as e:  # noqa: BLE001 - a missing/locked shadow.db must not stop the daily learning
            print(f"učenje: sjenovita knjiga nije dostupna: {type(e).__name__}: {e}")
    # 8.11.: a row without a class (token_tier missing, mcap unknown) crashed the whole run ('<' between str and
    # None) since the evening of 7.11.: learning and the 6-hourly weights had not run all night. Such rows learn
    # with the default class.
    for r in rows:
        if not r.get("klasa"):
            r["klasa"] = "default"
    for r in sh:
        if not r.get("klasa"):
            r["klasa"] = "default"
    report = []
    for klasa in sorted(set(r["klasa"] for r in rows) | set(k for k in thr if k) | set(r["klasa"] for r in sh)):
        rk_sh = [r for r in sh if r["klasa"] == klasa]
        need_sh = max(30, cfg.get("min_rows_zarada", cfg["min_rows"]))   # never below 30 (R8)
        use_sh = len(rk_sh) >= need_sh
        zarada = cfg.get("cilj") == "zarada"
        rk = rk_sh if use_sh else ([] if zarada else [r for r in rows if r["klasa"] == klasa])
        old = weights.load(klasa, base)
        rec = {"klasa": klasa, "n": len(rk), "skok": (cfg.get("shadow") or {}).get("hit_ret", 0.1) if use_sh else thr.get(klasa, 0),
               "cilj": "zarada" if use_sh else ("nedovoljno" if zarada else "vrh"), "n_shadow": len(rk_sh),
               "applied": False, "old": old, "new": None, "metric_old": None, "metric_new": None, "note": ""}
        train, val = split.by_time(rk, horizon_s=cfg.get("purge_h", cfg.get("horizon_h", 24)) * 3600)
        if zarada and not use_sh:
            rec["note"] = (f"nedovoljno podataka za cilj zarada: {len(rk_sh)} od {need_sh} ishoda u sjenovitoj "
                           "knjizi; težine se ne mijenjaju (vrh se više ne uči pod istim imenom)")
        elif len(rk) < cfg["min_rows"] and not use_sh:
            rec["note"] = f"premalo ishoda ({len(rk)} od potrebnih {cfg['min_rows']})"
        elif len(val) < 20 or len(train) < 10:
            rec["note"] = f"premalo za odvojeno učenje i provjeru ({len(train)} za učenje, {len(val)} za provjeru)"
        else:
            fit = evaluate.fit_weights(train)              # learned on the older part only
            if not fit:
                rec["note"] = "još nema nijednog skoka u podacima, nema se iz čega učiti"
            else:
                new = step(old, fit["weights"], cfg)
                ok, mo, mn = better(val, old, new)         # judged on the newer part it never saw
                rec.update(new=new, metric_old=mo, metric_new=mn)
                if ok:
                    rec["note"] = (f"pogađanje među 20% najbolje ocijenjenih na provjeri (noviji {len(val)} ishoda) "
                                   f"{mo} → {mn}")
                    if use_sh:
                        rec["note"] += " (cilj: ostvariva zarada, sjenovita knjiga)"
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
