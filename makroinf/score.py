"""THREE separate scores per account (the critic: "tri odvojene ocjene - prediktivna kvaliteta, ekonomska vrijednost,
integritet", never one product: a penalty times a negative number makes a better number).

  prediktivno   decided outcomes (hit / miss; flat is not decided), each with its weight (0.5 per horizon for calls
                without a horizon): hit rate, Wilson interval (fractional counts are fine), the three baselines on the
                SAME outcomes (always-bull, defined random, 7-day trend), Brier only where the author gave a probability,
                the shrunk hit rate (k pseudo-outcomes at the pooled rate of all accounts) for the rank
  ekonomski     mean follow return (after the locked cost) against always-bull's on the same outcomes, the difference
                and its normal 95 % interval
  integritet    macro calls later unavailable ("naknadno nedostupno": confirmed deleted, unavailable, account
                protected / suspended) with a Wilson interval, promo share; NO automatic penalty. The deletion rate of
                misses vs hits is compared only when both groups have >= 10 calls.
Fewer than min_episodes (10) scored episodes = "nedovoljno dokaza": no verdict and no rank.
"""
import math

from makroinf import rules

VERDICT_FEW = "nedovoljno dokaza"


def wilson(h, n, z=1.96):
    """(low, high) of a proportion h / n (fractional counts allowed); (None, None) for n <= 0."""
    if not n or n <= 0:
        return None, None
    p = h / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    m = z * math.sqrt(max(0.0, p * (1 - p) / n + z * z / (4 * n * n))) / den
    return max(0.0, c - m), min(1.0, c + m)


def _r(x, k=4):
    return None if x is None else round(x, k)


def mean_ci(xs, z=1.96):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None, None, None
    m = sum(xs) / len(xs)
    if len(xs) < 2:
        return m, None, None
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))
    e = z * sd / math.sqrt(len(xs))
    return m, m - e, m + e


def decided(outs):
    return [o for o in outs if o.get("res") in ("hit", "miss")]


def predictive(outs, prior=None, L=rules.LOCKED):
    """The predictive block of one set of outcomes (see the module text)."""
    d = decided(outs)
    hw = sum(o["w"] for o in d if o["res"] == "hit")
    nw = sum(o["w"] for o in d)
    eps = {o["eid"] for o in d}
    lo, hi = wilson(hw, nw, L["z"])
    rate = hw / nw if nw else None

    def base(field):
        xs = [o for o in d if o.get(field) is not None]
        if field == "b_rand":
            h_ = sum(o["w"] * o["b_rand_hit"] for o in d if o.get("b_rand_hit") is not None)
            n_ = sum(o["w"] * o["b_rand_dec"] for o in d if o.get("b_rand_dec") is not None)
            return (h_ / n_) if n_ else None
        bd = [o for o in xs if o[field] in ("hit", "miss")]
        n_ = sum(o["w"] for o in bd)
        return (sum(o["w"] for o in bd if o[field] == "hit") / n_) if n_ else None
    b = {"uvijek_bik": base("b_bull"), "nasumicno": base("b_rand"), "trend_7d": base("b_trend")}
    known = [v for v in b.values() if v is not None]
    best = max(known) if known else None
    k = L["shrink_k"]
    m = prior if prior is not None else 0.5
    shrunk = (hw + k * m) / (nw + k) if nw or k else None
    pr = [(o["prob"], 1.0 if o["res"] == "hit" else 0.0) for o in d if o.get("prob") is not None]
    if len(eps) < L["min_episodes"]:
        verdict = VERDICT_FEW
    elif best is not None and lo is not None and lo > best:
        verdict = "bolji od baznih strategija"
    elif best is not None and hi is not None and hi < best:
        verdict = "lošiji od baznih strategija"
    else:
        verdict = "ne razlikuje se od baznih strategija"
    return {"n_epizoda": len(eps), "n_tezinski": _r(nw, 2), "pogoci_tezinski": _r(hw, 2), "pogodak": _r(rate),
            "wilson95": [_r(lo), _r(hi)], "bazne": {k_: _r(v) for k_, v in b.items()}, "najbolja_bazna": _r(best),
            "razlika_prema_najboljoj": _r(rate - best if rate is not None and best is not None else None),
            "skupljeno": _r(shrunk), "brier": _r(sum((p - y) ** 2 for p, y in pr) / len(pr)) if pr else None,
            "n_vjerojatnosti": len(pr), "ravno": sum(1 for o in outs if o.get("res") == "flat"), "presuda": verdict}


def economic(outs, L=rules.LOCKED):
    """Per EPISODE (its horizons averaged by weight, so a call without a horizon is not counted twice): the follow
    return minus always-bull's on the same outcomes; the mean over episodes and its normal 95 % interval."""
    xs = [o for o in outs if o.get("res") in ("hit", "miss", "flat") and o.get("follow") is not None
          and o.get("b_bull_follow") is not None]
    if not xs:
        return {"n": 0, "presuda": VERDICT_FEW}
    by = {}
    for o in xs:
        by.setdefault(o["eid"], []).append(o)

    def wavg(items, key):
        w = sum(o["w"] or 0 for o in items) or 1.0
        return sum((o["w"] or 0) * o[key] for o in items) / w
    f = [wavg(v, "follow") for v in by.values()]
    b = [wavg(v, "b_bull_follow") for v in by.values()]
    m, lo, hi = mean_ci([a - c for a, c in zip(f, b)], L["z"])
    eps = len(by)
    verdict = VERDICT_FEW if eps < L["min_episodes"] else (
        "dodaje vrijednost" if lo is not None and lo > 0 else "gubi prema uvijek-bik" if hi is not None and hi < 0
        else "ne razlikuje se od uvijek-bik")
    return {"n": eps, "n_epizoda": eps, "prosjek_slijedi": _r(sum(f) / len(f)), "prosjek_uvijek_bik": _r(sum(b) / len(b)),
            "razlika": _r(m), "razlika95": [_r(lo), _r(hi)], "presuda": verdict}


GONE = ("confirmed_deleted", "unavailable", "account_protected", "account_suspended")


def integrity(n_macro, del_states, n_promo, outs_by_id=None, L=rules.LOCKED):
    """del_states: {tweet id: state}; outs_by_id: {first tweet id of an episode: 'hit' | 'miss'} for the comparison."""
    gone = [i for i, s in (del_states or {}).items() if s in GONE]
    lo, hi = wilson(len(gone), n_macro, L["z"]) if n_macro else (None, None)
    out = {"makro_izjava": n_macro, "provjereno": len(del_states or {}), "naknadno_nedostupno": len(gone),
           "udio": _r(len(gone) / n_macro if n_macro else None), "wilson95": [_r(lo), _r(hi)],
           "po_stanju": {s: sum(1 for x in (del_states or {}).values() if x == s) for s in GONE + ("api_error",)},
           "promocije": n_promo, "udio_promocija": _r(n_promo / (n_macro + n_promo) if (n_macro + n_promo) else None),
           "kazna": "nema (dok dokaz nije jak)"}
    if outs_by_id:
        hits = [i for i, r in outs_by_id.items() if r == "hit"]
        miss = [i for i, r in outs_by_id.items() if r == "miss"]
        if len(hits) >= 10 and len(miss) >= 10:
            gh = sum(1 for i in hits if i in gone)
            gm = sum(1 for i in miss if i in gone)
            out["promasaji_prema_pogocima"] = {
                "pogoci": {"n": len(hits), "nedostupno": gh, "wilson95": [_r(x) for x in wilson(gh, len(hits))]},
                "promasaji": {"n": len(miss), "nedostupno": gm, "wilson95": [_r(x) for x in wilson(gm, len(miss))]}}
        else:
            out["promasaji_prema_pogocima"] = "premalo za usporedbu (treba 10+ pogodaka i 10+ promašaja)"
    return out


def by_horizon(outs):
    """{"s rokom 7 d", "s rokom 30 d", "bez roka 7 d", "bez roka 30 d"}: hit rate, n, Wilson (both no-horizon tests are
    always shown)."""
    groups = {"s_rokom_7d": [o for o in outs if o["hz"] == "7"], "s_rokom_30d": [o for o in outs if o["hz"] == "30"],
              "bez_roka_7d": [{**o, "w": 1.0} for o in outs if o["hz"] == "oba" and o["horizon"] == "7"],
              "bez_roka_30d": [{**o, "w": 1.0} for o in outs if o["hz"] == "oba" and o["horizon"] == "30"]}
    out = {}
    for k, xs in groups.items():
        d = decided(xs)
        h = sum(o["w"] for o in d if o["res"] == "hit")
        n = sum(o["w"] for o in d)
        lo, hi = wilson(h, n)
        out[k] = {"n": len(d), "pogodak": _r(h / n) if n else None, "wilson95": [_r(lo), _r(hi)]}
    return out


def account(outs, n_macro, del_states, n_promo, prior=None):
    """The three scores (and the horizon split) of one account."""
    first = {}
    for o in outs:
        if o.get("res") in ("hit", "miss") and o["first_id"] not in first:
            first[o["first_id"]] = o["res"]
    return {"prediktivno": predictive(outs, prior), "ekonomski": economic(outs),
            "integritet": integrity(n_macro, del_states, n_promo, first), "po_horizontu": by_horizon(outs),
            "stanja": {k: sum(1 for o in outs if o.get("res") == k) for k in
                       ("hit", "miss", "flat", "ceka", "neaktiviran", "bez_podataka", "dugo")}}


def pooled_rate(all_outs):
    d = decided(all_outs)
    n = sum(o["w"] for o in d)
    return (sum(o["w"] for o in d if o["res"] == "hit") / n) if n else 0.5


def rank(scores):
    """Handles in rank order: accounts with enough evidence by the shrunk hit rate (then n), the rest after."""
    def key(item):
        h, s = item
        p = s["prediktivno"]
        ok = p["presuda"] != VERDICT_FEW
        return (0 if ok else 1, -(p.get("skupljeno") or 0), -p["n_epizoda"], h.lower())
    return [h for h, _s in sorted(scores.items(), key=key)]
