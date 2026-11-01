"""Champion / challenger for the decision model, with a locked holdout week. Nothing is applied on faith.

- The CHAMPION is what live trading uses: "tezine" (the per-class hype weights, learn/fit.py) or "gbm"
  (learn/gbm.py trained on the shadow book).
- A CHALLENGER gbm is trained on the shadow book and then only watched for `trial_days` days: it scores the decision
  points that arrive after it was trained (data it never saw). At the end its top `top_pct`% picks are compared
  with the champion's top picks on the same points, and with the control (every point = "buy every first $100k
  crossing / every candidate"). It wins only if its mean return is higher, also without the top 1% (one lucky
  50x does not decide), and the 90% bootstrap range of the difference is above zero. Then it becomes champion.
- A gbm champion is re-checked daily on the last week; if the weights would have done better on both measures, the
  weights come back (rollback).
- The HOLDOUT week (config holdout from/to) is used by no training and no trial. After it ends, one final report
  says how champion, weights and control did on it: the honest "did learning help" number.

State: LEARNED_DIR/model.json. Runs logged to hype.db learn_runs (klasa 'model').
"""
import datetime as dt
import json
import os
import random
import time

from learn import gbm, shadow
from learn import weights as _w

DEFAULT = {"trial_days": 7, "min_eval": 300, "top_pct": 20, "points": ["mc100k", "kandidat"], "half_life_d": 7,
           "holdout": {"from": "2026-11-07", "to": "2026-11-14"}, "boot": 300, "train_days": 30}


def config():
    from learn import outcomes
    return {**DEFAULT, **(outcomes.config().get("model") or {})}


def path():
    return os.path.join(_w.LEARNED_DIR, "model.json")


def load():
    try:
        with open(path()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"champion": "tezine", "gbm": None, "challenger": None, "history": []}


def save(state):
    os.makedirs(_w.LEARNED_DIR, exist_ok=True)
    state["history"] = state.get("history", [])[-60:]
    tmp = path() + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, path())


def _day_ts(s):
    return dt.datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp()


def holdout_range(cfg=None):
    cfg = cfg or config()
    h = cfg.get("holdout") or {}
    if not h.get("from") or not h.get("to"):
        return None
    return _day_ts(h["from"]), _day_ts(h["to"]) + 86400


def in_holdout(ts, cfg=None):
    r = holdout_range(cfg)
    return bool(r and r[0] <= ts < r[1])


def _xy(rs, hyps=True):
    return [{"x": gbm.context(r, hyps), "y": bool(r["hit"]), "ts": r["ts"]} for r in rs]


def decay(rs, now, half_life_d):
    return [0.5 ** (max(0.0, now - r["ts"]) / 86400 / half_life_d) for r in rs]


def train_rows(now, cfg=None, path=None):
    cfg = cfg or config()
    rs = [r for p in cfg["points"] for r in shadow.rows(path, point=p, since=now - cfg["train_days"] * 86400)]
    return sorted((r for r in rs if r["ts"] < now and not in_holdout(r["ts"], cfg)), key=lambda r: r["ts"])


def pick(rs, scorer, top_pct):
    """The top_pct% of points by scorer, per point type (each type is its own decision)."""
    out = []
    for p in {r["point"] for r in rs}:
        group = sorted((r for r in rs if r["point"] == p), key=lambda r: -scorer(r))
        out += group[:max(1, len(group) * top_pct // 100)]
    return out


def _mean(xs, cap=3.0):
    return sum(min(cap, x) for x in xs) / len(xs) if xs else 0.0


def boot_diff(a, b, n=300, seed=7):
    """90% bootstrap range of mean(a) - mean(b) (returns capped at +300%)."""
    if not a or not b:
        return None
    rnd = random.Random(seed)
    d = sorted(_mean([rnd.choice(a) for _ in a]) - _mean([rnd.choice(b) for _ in b]) for _ in range(n))
    return round(d[int(n * 0.05)], 4), round(d[int(n * 0.95)], 4)


def strip_ai(r):
    return {**r, "features": {k: v for k, v in (r.get("features") or {}).items() if not k.startswith(("ai_", "h_"))}}


def compare(rs, model, cfg=None, noai=None):
    """Champion weights (the score live trading had) vs model vs control on the same labelled points. noai: the
    same model trained without the AI signals (ai_*, h_*), judged on the same points with those signals removed:
    the difference is what the paid AI adds."""
    cfg = cfg or config()
    rs = [r for r in rs if r["point"] in cfg["points"]]
    out = {"n": len(rs), "kontrola": shadow.stats(rs)}
    w = pick(rs, lambda r: r["score"] or 0, cfg["top_pct"])
    out["tezine"] = shadow.stats(w)
    if model:
        m = pick(rs, lambda r: gbm.predict(model, gbm.context(r)), cfg["top_pct"])
        out["model"] = shadow.stats(m)
        out["razlika"] = boot_diff([r["ret"] for r in m], [r["ret"] for r in w], cfg["boot"])
    if noai:
        n = pick(rs, lambda r: gbm.predict(noai, gbm.context(strip_ai(r), hyps=False)), cfg["top_pct"])
        out["bez_ai"] = shadow.stats(n)
    return out


def wins(c):
    """Model beats the weights: higher mean, higher mean without the top 1%, bootstrap range above zero."""
    m, w = c.get("model") or {}, c.get("tezine") or {}
    if not m.get("n") or not w.get("n"):
        return False
    return (m["mean"] > w["mean"] and m["mean_trim"] > w["mean_trim"]
            and c.get("razlika") is not None and c["razlika"][0] > 0)


def run(now=None, cfg=None, shadow_path=None, apply=True):
    """Daily: judge the running trial (promote or drop), re-check a gbm champion, start a new trial when none runs.
    Returns a report dict for run_learn / learn_runs."""
    cfg = cfg or config()
    now = now or time.time()
    st = load()
    rep = {"champion": st["champion"], "events": []}
    ch = st.get("challenger")
    if ch:
        rs = [r for p in cfg["points"] for r in shadow.rows(shadow_path, point=p, since=ch["trained_ts"]) if not in_holdout(r["ts"], cfg)]
        c = compare(rs, ch["model"], cfg, ch.get("model_noai"))
        ch["eval"] = c
        days = (now - ch["trained_ts"]) / 86400
        if days >= cfg["trial_days"] and c["n"] >= cfg["min_eval"]:
            if wins(c):
                st["champion"], st["gbm"] = "gbm", {**ch, "promoted_ts": int(now)}
                rep["events"].append(f"model prošao probu ({c['n']} točaka): prosjek {c['model']['mean']:+.1%} prema "
                                     f"težinama {c['tezine']['mean']:+.1%}; sad odlučuje model")
            else:
                rep["events"].append(f"model nije prošao probu ({c['n']} točaka): prosjek "
                                     f"{(c.get('model') or {}).get('mean', 0):+.1%} prema težinama {c['tezine']['mean']:+.1%}")
            st["history"].append({"ts": int(now), "kind": "proba", "won": wins(c), "eval": c})
            st["challenger"] = ch = None
        elif days >= 3 * cfg["trial_days"]:  # too few points for too long: retrain on fresher data
            rep["events"].append("proba bez dovoljno točaka 3 tjedna; novi model")
            st["challenger"] = ch = None
    if st["champion"] == "gbm" and st.get("gbm"):
        rs = [r for p in cfg["points"] for r in shadow.rows(shadow_path, point=p, since=now - cfg["trial_days"] * 86400)
              if not in_holdout(r["ts"], cfg)]
        c = compare(rs, st["gbm"]["model"], cfg, st["gbm"].get("model_noai"))
        st["gbm"]["eval_week"] = c
        m, w = c.get("model") or {}, c.get("tezine") or {}
        if c["n"] >= cfg["min_eval"] and w.get("n") and m.get("n") and w["mean"] > m["mean"] and w["mean_trim"] > m["mean_trim"]:
            st["champion"] = "tezine"
            rep["events"].append(f"model zadnji tjedan lošiji od težina ({m['mean']:+.1%} prema {w['mean']:+.1%}); vraćam težine")
            st["history"].append({"ts": int(now), "kind": "rollback", "eval": c})
    if not ch:
        rs = train_rows(now, cfg, shadow_path)
        xy = _xy(rs)
        model = gbm.train(xy, weights=decay(rs, now, cfg["half_life_d"]))
        if model:
            st["challenger"] = {"model": model, "trained_ts": int(now), "n_train": len(rs)}
            if any(k.startswith(("ai_", "h_")) for x in xy for k in x["x"]):
                st["challenger"]["model_noai"] = gbm.train(_xy([strip_ai(r) for r in rs], hyps=False),
                                                           weights=decay(rs, now, cfg["half_life_d"]))
            rep["events"].append(f"novi model u probi {cfg['trial_days']} dana (naučen na {len(rs)} točaka)")
        else:
            rep["events"].append(f"premalo točaka za model ({len(rs)}, treba {gbm.DEFAULT['min_rows']})")
    hr = holdout_range(cfg)
    if hr and now >= hr[1] and not st.get("holdout_report"):
        rs = [r for r in shadow.rows(shadow_path, since=hr[0]) if r["ts"] < hr[1]]
        model = (st.get("gbm") or {}).get("model") if st["champion"] == "gbm" else (st.get("challenger") or {}).get("model")
        st["holdout_report"] = {"ts": int(now), "champion": st["champion"], "eval": compare(rs, model, cfg)}
        rep["events"].append("zaključani tjedan otvoren: konačna usporedba spremljena")
    rep["champion"] = st["champion"]
    st["weeks"] = weekly(now, cfg, shadow_path, st)
    if apply:
        save(st)
    return rep


def weekly(now, cfg, shadow_path, st):
    """This week and last week on the same decision points: control / weights / model. Computed here (the short
    learning process) and stored, so the dashboard, which lives 24/7, only reads a small JSON."""
    model = (st.get("gbm") or {}).get("model") if st.get("champion") == "gbm" else (st.get("challenger") or {}).get("model")
    out = []
    for k in (0, 1):
        a, b = now - (k + 1) * 7 * 86400, now - k * 7 * 86400
        rs = [r for p in cfg["points"] for r in shadow.rows(shadow_path, point=p, since=a) if r["ts"] < b]
        out.append({"from": int(a), "to": int(b), "eval": compare(rs, model, cfg)})
    return {"ts": int(now), "weeks": out}


# ---------------------------------------------------------------- live side (run_paper)

_LIVE = {"ts": 0, "model": None}


def live(now=None):
    """The gbm model when it is champion, else None (re-read at most every 5 minutes)."""
    now = now or time.time()
    if now - _LIVE["ts"] > 300:
        st = load()
        _LIVE.update(ts=now, model=(st.get("gbm") or {}).get("model") if st.get("champion") == "gbm" else None)
    return _LIVE["model"]


def candidate_p(model, c, now):
    """Model probability for a paper candidate (point 'kandidat'), from what the candidate carries right now."""
    from exits import paths
    from tiers import classify
    feats = dict(c.get("features") or {})
    if c.get("token"):
        try:
            from learn import postai
            feats.update(postai.features(c["token"], now))
        except Exception:  # noqa: BLE001
            pass
    r = {"features": feats, "point": "kandidat", "klasa": classify.klasa(c.get("mcap"), None),
         "sess": paths.session_of(now), "mcap": c.get("mcap"), "liq": c.get("liquidity"), "score": c.get("score")}
    return gbm.predict(model, gbm.context(r))


def ai_lift(st=None):
    """(lift per trade, n points) of the AI signals from the latest evaluation: model minus the same model without
    them, on the same points. None until a trial with AI signals has been judged."""
    st = st or load()
    for src in ((st.get("gbm") or {}).get("eval_week"), (st.get("challenger") or {}).get("eval")):
        if src and (src.get("bez_ai") or {}).get("n") and (src.get("model") or {}).get("n"):
            return round(src["model"]["mean"] - src["bez_ai"]["mean"], 4), src["n"]
    for h in reversed(st.get("history") or []):
        e = h.get("eval") or {}
        if (e.get("bez_ai") or {}).get("n") and (e.get("model") or {}).get("n"):
            return round(e["model"]["mean"] - e["bez_ai"]["mean"], 4), e["n"]
    return None
