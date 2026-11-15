"""The consensus index (the critic: "konsenzus bez dvostrukog brojanja"; "dokaz da indeks pomaže MIDCAPOVIMA").

Stance: ONE current stance per account and index asset (BTC = calls on BTC or the whole market; SOL; memes): the
newest call available at time t that is in force (unconditional: until its horizon bucket's stance days; conditional:
only once the condition hit; a withdrawal ends it). +1 up / bottom_in, -1 down / top_in, 0 range. An account without a
stance is NOT a neutral vote: it is left out of the denominator.
Availability (no look-ahead): "prospektivno" = the time WE fetched the post (fetched_ts): the index exists only from
the real fetch time on; "povijesno" = the post time + lag_s, the backfill's history, biased (we only see the posts that
survived until we fetched them; the accounts are the ones famous now) and labelled so everywhere.
Index = sum(w x stance) / sum(w) over the accounts with a stance. Clusters (text similarity, quoting, simultaneous
calls, direction correlation; computed from data BEFORE the period they are used in) are capped at cluster_cap
weight together. Kinds: "svi" (every account, weight 1), "top" (the K most accurate by the shrunk hit rate of the
outcomes FINISHED by t, n >= min_top_n), "kontra" (the K worst, chosen on the training period ONLY, stance inverted:
a separate hypothesis).
Walk-forward: days with coverage, chronological train (50 %) -> validation (25 %) -> locked test (25 %), an embargo of
fwd_days between the parts; K and the threshold are chosen on train only; the test is read once per run and never
used for a choice. Target: the sign of BTC's forward 7-day return.
Incremental EV: the same locked midcap strategy (veliki/walk variants on the holdout's own picks) with the macro
filter alone ("makro_filter") vs with the index ("makro_indeks": the day is risk_off also when the top index <= -thr);
the index input of the DEMO is switched off automatically when it degrades (input_state).
"""
import hashlib
import json
import math
import re
import time

from makroinf import rules, score, store

D = 86400
INDEX_LOCKED = {
    "lag_s": 3600, "min_top_n": 5, "k_grid": [5, 10], "thr_grid": [0.25, 0.5], "default_k": 10, "default_thr": 0.5,
    "cluster_cap": 1.5, "min_coverage": 3, "fwd_days": 7, "embargo_d": 7, "train": 0.5, "val": 0.25, "min_n_eval": 10,
    "sim_text": 0.5, "quote_min": 3, "quote_strong": 5, "simul_h": 6, "simul_ratio": 0.3, "simul_min": 3,
    "corr_min": 0.7, "corr_days": 20, "corr_window_d": 120, "degrade_pp": 0.5, "degrade_n": 30, "degrade_walk_n": 20,
    "assets": {"BTC": ["BTC", "total"], "SOL": ["SOL"], "memes": ["memes"]}, "overlay_asset": "BTC",
}
INDEX_HASH = hashlib.sha256(json.dumps(INDEX_LOCKED, sort_keys=True).encode()).hexdigest()[:12]
WORD = re.compile(r"[a-z][a-z0-9']{2,}")
STOP = frozenset("the and for this that with you are was have not but just will all from they your our out its can "
                 "what about more when now been one get how like has would there their than them were who")


# ---------- calls / stances ------------------------------------------------------------------------------------------

def load_calls(con):
    keys = ("id", "asset", "handle", "ts", "avail_ts", "direction", "horizon_days", "conditional", "trigger_level",
            "trigger_dir", "target", "invalidation", "confidence", "prob", "promo", "unclear", "withdraws")
    rows = store.q(con, f"""SELECT {', '.join('c.' + k for k in keys)} FROM calls c JOIN accounts a ON a.handle =
        c.handle WHERE a.status IN ('aktivan', 'neaktivan')""")
    return [dict(zip(keys, r)) for r in rows]


def activations(calls, truth, L=rules.LOCKED):
    """{call id: activation ts} of the conditional calls whose condition hit within the expiry (a fact of the price
    path; used only once t >= that ts)."""
    out = {}
    for c in calls:
        if not c.get("conditional") or rules.thesis(c) is None:
            continue
        t, exp = c["ts"], c["ts"] + L["cond_expiry_d"] * D
        s = truth.fine(c["asset"], t, exp)
        for ts, p in s.window(t, exp):
            if (c["trigger_dir"] == "below" and p <= c["trigger_level"]) or \
                    (c["trigger_dir"] == "above" and p >= c["trigger_level"]):
                out[str(c["id"])] = ts
                break
    return out


def avail(c, mode, cfg=INDEX_LOCKED):
    return int(c.get("avail_ts") or c["ts"]) if mode == "prospektivno" else int(c["ts"]) + cfg["lag_s"]


def group(calls, asset, cfg=INDEX_LOCKED):
    """{handle: [call, ...] oldest first} of the calls that count for the index asset."""
    want = set(cfg["assets"][asset])
    by = {}
    for c in sorted(calls, key=lambda x: (x["ts"], str(x["id"]))):
        if c["asset"] in want:
            by.setdefault(c["handle"], []).append(c)
    return by


def stance(cs, t, mode, act, L=rules.LOCKED, cfg=INDEX_LOCKED):
    """(+1 / 0 / -1, call) of one account at t, or None (no stance in force)."""
    for c in reversed(cs):
        if c["ts"] > t or avail(c, mode, cfg) > t:
            continue
        if c.get("withdraws"):
            return None
        if rules.skip_reason(c):
            continue
        if c.get("conditional"):
            a = act.get(str(c["id"]))
            if a is None or a > t:
                continue
            if t <= a + L["stance_h_d"][rules.bucket(c.get("horizon_days"), L)] * D:
                return rules.SIGN.get(c["direction"], 0), c
            continue
        if t <= rules.stance_until(c, L):
            return rules.SIGN.get(c["direction"], 0), c
        return None
    return None


def stances(by, t, mode, act):
    out = {}
    for h, cs in by.items():
        s = stance(cs, t, mode, act)
        if s is not None:
            out[h] = s[0]
    return out


# ---------- clusters ---------------------------------------------------------------------------------------------------

def _bigrams(text):
    w = [x for x in WORD.findall((text or "").lower()) if x not in STOP and not x.startswith("http")]
    return [f"{a} {b}" for a, b in zip(w, w[1:])]


def _cos(a, b):
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def _pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if not sx or not sy:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def clusters(calls, texts, quotes, t_end, cfg=INDEX_LOCKED):
    """{handle: cluster id} from data BEFORE t_end only. texts: {handle: [macro post text]}, quotes: [(handle,
    quoted handle, ts)]. Two accounts are joined when 2+ signals agree (text cosine >= sim_text, quotes >= quote_min,
    simultaneous calls ratio >= simul_ratio, stance correlation >= corr_min), or on quote_strong quotes alone."""
    cs = [c for c in calls if c["ts"] < t_end and not rules.skip_reason(c) and not c.get("withdraws")]
    hs = sorted({c["handle"] for c in cs} | set(texts))
    vec = {}
    for h in hs:
        v = {}
        for t in texts.get(h) or []:
            for g in _bigrams(t):
                v[g] = v.get(g, 0) + 1
        vec[h] = v
    qn = {}
    for a, b, ts in quotes:
        if ts < t_end and a and b and a != b:
            k = tuple(sorted((a.lower(), b.lower())))
            qn[k] = qn.get(k, 0) + 1
    ev = {}
    for c in cs:
        ev.setdefault((c["asset"], c["direction"]), []).append((c["ts"], c["handle"]))
    co, nc = {}, {}
    for c in cs:
        nc[c["handle"]] = nc.get(c["handle"], 0) + 1
    w = cfg["simul_h"] * 3600
    for lst in ev.values():
        lst.sort()
        j = 0
        for i, (ts, h) in enumerate(lst):
            while lst[j][0] < ts - w:
                j += 1
            seen = set()
            for ts2, h2 in lst[j:i]:
                if h2 != h and h2 not in seen:
                    seen.add(h2)
                    k = tuple(sorted((h, h2)))
                    co[k] = co.get(k, 0) + 1
    # daily BTC stance per account over the window before t_end (historic availability: the stances of the time)
    by = group(cs, "BTC", cfg)
    days = [t_end - k * D for k in range(cfg["corr_window_d"], 0, -1)]
    st = {h: [stance(by[h], d, "povijesno", {}) for d in days] for h in by}
    parent = {h: h for h in hs}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for i, a in enumerate(hs):
        for b in hs[i + 1:]:
            q = qn.get(tuple(sorted((a.lower(), b.lower()))), 0)
            sig = 0
            sig += _cos(vec.get(a), vec.get(b)) >= cfg["sim_text"]
            sig += q >= cfg["quote_min"]
            k = tuple(sorted((a, b)))
            n_min = min(nc.get(a, 0), nc.get(b, 0))
            sig += co.get(k, 0) >= cfg["simul_min"] and n_min and co[k] / n_min >= cfg["simul_ratio"]
            if a in st and b in st:
                pairs = [(x[0], y[0]) for x, y in zip(st[a], st[b]) if x is not None and y is not None]
                if len(pairs) >= cfg["corr_days"]:
                    r = _pearson([p[0] for p in pairs], [p[1] for p in pairs])
                    sig += r is not None and r >= cfg["corr_min"]
            if sig >= 2 or q >= cfg["quote_strong"]:
                parent[find(a)] = find(b)
    return {h: find(h) for h in hs}


def value(st, weights, cl, cfg=INDEX_LOCKED):
    """(index, coverage, clusters) of {handle: stance} with {handle: weight}; each cluster's total weight is capped."""
    act = {h: s for h, s in st.items() if weights.get(h, 0) > 0}
    if not act:
        return None, 0, 0
    tot = {}
    for h in act:
        k = cl.get(h, h)
        tot[k] = tot.get(k, 0.0) + weights[h]
    num = den = 0.0
    for h, s in act.items():
        k = cl.get(h, h)
        f = min(1.0, cfg["cluster_cap"] / tot[k]) if tot[k] > 0 else 0.0
        w = weights[h] * f
        num += w * s
        den += w
    return (num / den if den else None), len(act), len(tot)


# ---------- weights from finished outcomes -----------------------------------------------------------------------------

def accuracy_at(outs, t, L=rules.LOCKED):
    """{handle: (shrunk hit rate, n episodes)} from the outcomes FINISHED by t (done_ts <= t) only."""
    fin = [o for o in outs if o.get("res") in ("hit", "miss") and o.get("done_ts") and o["done_ts"] <= t]
    prior = score.pooled_rate(fin) if fin else 0.5
    by = {}
    for o in fin:
        by.setdefault(o["handle"], []).append(o)
    out = {}
    for h, xs in by.items():
        hw = sum(o["w"] for o in xs if o["res"] == "hit")
        nw = sum(o["w"] for o in xs)
        out[h] = ((hw + L["shrink_k"] * prior) / (nw + L["shrink_k"]), len({o["eid"] for o in xs}))
    return out


def top_set(acc, k, worst=False, cfg=INDEX_LOCKED):
    ok = [(h, a) for h, (a, n) in acc.items() if n >= cfg["min_top_n"]]
    ok.sort(key=lambda x: (x[1], x[0]) if worst else (-x[1], x[0]))
    return [h for h, _a in ok[:k]]


# ---------- series and walk-forward ------------------------------------------------------------------------------------

def series(calls, outs, truth, days, mode="povijesno", asset="BTC", k=None, cl=None, contra_set=None,
           cfg=INDEX_LOCKED):
    """{day: {"svi", "top", "kontra", "n_svi", "n_top"}} at each day's 00:00 UTC (t = day)."""
    k = k or cfg["default_k"]
    act = activations(calls, truth)
    by = group(calls, asset, cfg)
    cl = cl or {}
    out = {}
    for d in days:
        st = stances(by, d, mode, act)
        v_all, n_all, _ = value(st, {h: 1.0 for h in st}, cl, cfg)
        top = top_set(accuracy_at(outs, d), k, cfg=cfg)
        v_top, n_top, _ = value(st, {h: 1.0 for h in top}, cl, cfg)
        row = {"svi": v_all, "n_svi": n_all, "top": v_top, "n_top": n_top}
        if contra_set:
            inv = {h: -s for h, s in st.items() if h in contra_set}
            v_k, n_k, _ = value(inv, {h: 1.0 for h in inv}, cl, cfg)
            row.update(kontra=v_k, n_kontra=n_k)
        out[d] = row
    return out


def fwd_sign(truth, d, days=7, asset="BTC"):
    s = truth.daily(asset)
    a, b = s.known(d), s.known(d + days * D)
    if not a or not b or b[0] < d + (days - 1) * D:
        return None
    return 1 if b[1] > a[1] else -1


def _hits(rows, key, thr, y):
    xs = [(r[key], y[d]) for d, r in rows if r.get(key) is not None and abs(r[key]) >= thr and y.get(d) is not None]
    hit = sum(1 for v, yy in xs if (1 if v > 0 else -1) == yy)
    base = sum(1 for _v, yy in xs if yy == 1)
    return hit, len(xs), base


def splits(days, cfg=INDEX_LOCKED):
    """(train, validation, test) day lists, chronological, with an embargo of embargo_d between the parts."""
    n = len(days)
    a, b = int(n * cfg["train"]), int(n * (cfg["train"] + cfg["val"]))
    emb = cfg["embargo_d"] * D
    tr = [d for d in days[:a] if not days[a:] or d < days[a] - emb]
    va = [d for d in days[a:b] if not days[b:] or d < days[b] - emb]
    return tr, va, days[b:]


def walk(calls, outs, truth, texts, quotes, now, cfg=INDEX_LOCKED, log=print):
    """The walk-forward of the BTC index (historic availability). K / thr chosen on train only; validation and the
    locked test reported with Wilson intervals against always-bull on the same days; the contrarian index with its
    worst set chosen at the end of train."""
    if not calls:
        return {"available": False, "why": "nema izjava"}
    t0 = min(c["ts"] for c in calls) // D * D + 30 * D
    days = list(range(int(t0), int(now) // D * D - cfg["fwd_days"] * D + 1, D))
    if len(days) < 40:
        return {"available": False, "why": f"premalo dana ({len(days)}), treba 40+"}
    y = {d: fwd_sign(truth, d, cfg["fwd_days"]) for d in days}
    tr, va, te = splits(days, cfg)
    if not tr or not va or not te:
        return {"available": False, "why": "premalo dana za podjelu"}
    cl = clusters(calls, texts, quotes, tr[-1] + D, cfg)
    contra = top_set(accuracy_at(outs, tr[-1] + D), max(cfg["k_grid"]), worst=True, cfg=cfg)
    per_k = {k: series(calls, outs, truth, days, "povijesno", "BTC", k, cl, contra if k == max(cfg["k_grid"]) else None,
                       cfg) for k in cfg["k_grid"]}
    best = None
    for k in cfg["k_grid"]:
        rows = [(d, per_k[k][d]) for d in tr]
        for thr in cfg["thr_grid"]:
            h, n, _b = _hits(rows, "top", thr, y)
            if n >= cfg["min_n_eval"] and (best is None or h / n > best[0]):
                best = (h / n, k, thr, n)
    k = best[1] if best else cfg["default_k"]
    thr = best[2] if best else cfg["default_thr"]

    def part(ds, key="top", kk=None):
        rows = [(d, per_k[kk or k][d]) for d in ds]
        h, n, b = _hits(rows, key, thr, y)
        lo, hi = score.wilson(h, n)
        blo, bhi = score.wilson(b, n)
        return {"n": n, "pogodak": round(h / n, 4) if n else None, "wilson95": [lo and round(lo, 4), hi and round(hi, 4)],
                "uvijek_bik": round(b / n, 4) if n else None, "uvijek_bik95": [blo and round(blo, 4), bhi and round(bhi, 4)],
                "od": time.strftime("%Y-%m-%d", time.gmtime(ds[0])) if ds else None,
                "do": time.strftime("%Y-%m-%d", time.gmtime(ds[-1])) if ds else None}
    kk = max(cfg["k_grid"])
    out = {"available": True, "ts": int(now), "mode": "povijesno (pristrano: samo objave koje su preživjele do dohvata)",
           "k": k, "thr": thr, "izabrano_na_treningu": best is not None, "trening": part(tr), "validacija": part(va),
           "test_zakljucan": part(te), "svi_test": part(te, "svi"), "kontra_test": part(te, "kontra", kk),
           "kontra_skup": contra, "klasteri": len(set(cl.values())), "racuna_u_klasterima": len(cl),
           "index_hash": INDEX_HASH, "rules_v": rules.RULES_VERSION}
    out["dani"] = {d: {"top": per_k[k][d]["top"], "n_top": per_k[k][d]["n_top"], "svi": per_k[k][d]["svi"],
                       "n_svi": per_k[k][d]["n_svi"]} for d in days}
    return out


def overlay_days(dani, thr, base=None, cfg=INDEX_LOCKED):
    """{UTC day number: regime} for veliki/walk's "makro_indeks" variant: the base regime, risk_off on the days the
    top index (known at the day's start) is <= -thr with coverage >= min_coverage."""
    out = dict(base or {})
    for d, r in (dani or {}).items():
        v, n = r.get("top"), r.get("n_top") or 0
        if v is not None and n >= cfg["min_coverage"] and v <= -thr:
            out[int(d) // D] = "risk_off"
    return out


def veliki_overlay(path=None):
    """For veliki/walk: (thr, {day: row}) of the newest stored walk, or None (no index yet)."""
    con = store.ro(path)
    if con is None:
        return None
    try:
        w = store.kv_json(con, "walk")
    finally:
        con.close()
    if not w or not w.get("available"):
        return None
    return w["thr"], {int(d): r for d, r in (w.get("dani") or {}).items()}


# ---------- incremental EV and the input state ------------------------------------------------------------------------

_EV = {"ts": 0.0, "v": None}


def incremental_ev(max_age_s=300):
    """The same locked midcap strategy without / with the index (veliki.db newest backtest, 0.5 SOL, the holdout's
    own picks): {"bez", "s_indeksom", "razlika_pp"} or {"todo": why}. Cached 5 min (the card and MCP ask often)."""
    if _EV["v"] is not None and time.monotonic() - _EV["ts"] < max_age_s:
        return _EV["v"]
    v = _incremental_ev()
    _EV.update(ts=time.monotonic(), v=v)
    return v


def _incremental_ev():
    try:
        from veliki import store as vstore
        ts, data = vstore.latest()
    except Exception as e:  # noqa: BLE001
        return {"todo": f"veliki backtest nečitljiv ({type(e).__name__})"}
    vh = ((((data or {}).get("variants") or {}).get("dno") or {}).get("0.5") or {}).get("variants_holdout") or {}
    a, b = vh.get("makro_filter"), vh.get("makro_indeks")
    if not a or not b:
        return {"todo": "čeka veliki backtest s varijantom makro_indeks (noćni prolaz nakon prvog indeksa)",
                "veliki_ts": ts}
    diff = None if a.get("ev_pct") is None or b.get("ev_pct") is None else round(b["ev_pct"] - a["ev_pct"], 3)
    return {"veliki_ts": ts, "bez": {k: a.get(k) for k in ("n", "ev_pct", "usd_day", "max_dd_usd", "ci95_day_pct")},
            "s_indeksom": {k: b.get(k) for k in ("n", "ev_pct", "usd_day", "max_dd_usd", "ci95_day_pct")},
            "razlika_pp": diff, "napomena": "ista zaključana midcap strategija (holdout), troškovi uključeni; indeks "
                                            "povijesni (pristran)"}


def input_state(con, w=None, ev=None, now=None, cfg=INDEX_LOCKED):
    """{"state": aktivan | na_cekanju | iskljucen, "why"} of the index as the DEMO input (auto-disable on degradation)."""
    now = int(now or time.time())
    q = store.kv_json(con, "provjera", {}) or {}
    if not (q.get("passed") or q.get("forced")):
        return {"state": "na_cekanju", "why": "provjera klasifikacije još nije prošla (≥ 85 % po kategoriji)"}
    w = w if w is not None else (store.kv_json(con, "walk", {}) or {})
    for part in ("validacija", "test_zakljucan"):
        x = (w or {}).get(part) or {}
        if (x.get("n") or 0) >= cfg["degrade_walk_n"] and x.get("pogodak") is not None and \
                x.get("uvijek_bik") is not None and x["pogodak"] < x["uvijek_bik"]:
            return {"state": "iskljucen", "why": f"degradacija: {part} pogodak {x['pogodak']:.0%} ispod uvijek-bik "
                                                 f"{x['uvijek_bik']:.0%} (n={x['n']})"}
    ev = ev if ev is not None else incremental_ev()
    if ev.get("razlika_pp") is not None and (ev.get("s_indeksom") or {}).get("n", 0) >= cfg["degrade_n"] and \
            ev["razlika_pp"] <= -cfg["degrade_pp"]:
        return {"state": "iskljucen", "why": f"degradacija: midcap EV s indeksom {ev['razlika_pp']:+.2f} pp prema bez"}
    r = store.q(con, "SELECT value, coverage FROM index_d WHERE asset = ? AND mode = 'prospektivno' AND kind = 'top' "
                     "ORDER BY day DESC LIMIT 1", (cfg["overlay_asset"],))
    if not r or (r[0][1] or 0) < cfg["min_coverage"]:
        return {"state": "na_cekanju", "why": f"prospektivni indeks ima manje od {cfg['min_coverage']} računa sa stavom"}
    return {"state": "aktivan", "why": "provjera prošla, bez degradacije"}


def demo_check(now=None, path=None, cfg=INDEX_LOCKED):
    """For veliki/makro (the DEMO account only): (blocks: bool, why, index value) from the stored state and today's
    prospective top index. Never raises."""
    con = store.ro(path)
    if con is None:
        return False, "makroinf.db još ne postoji", None
    try:
        st = store.kv_json(con, "ulaz", {}) or {}
        w = store.kv_json(con, "walk", {}) or {}
        r = store.q(con, "SELECT value, coverage, day FROM index_d WHERE asset = ? AND mode = 'prospektivno' AND "
                         "kind = 'top' ORDER BY day DESC LIMIT 1", (cfg["overlay_asset"],))
    finally:
        con.close()
    if st.get("state") != "aktivan":
        return False, f"ulaz indeksa: {st.get('state') or 'na_cekanju'} ({st.get('why') or 'još nema stanja'})", None
    if not r:
        return False, "nema prospektivnog indeksa", None
    v, n, day = r[0]
    thr = float(w.get("thr") or cfg["default_thr"])
    if now and day < int(now) // D * D - 2 * D:
        return False, "prospektivni indeks star više od 2 dana", v
    if v is not None and (n or 0) >= cfg["min_coverage"] and v <= -thr:
        return True, f"makro influenceri: indeks najtočnijih {v:+.2f} (≤ −{thr:g}, {n} računa)", v
    return False, f"indeks najtočnijih {v if v is None else round(v, 2)} ({n} računa)", v
