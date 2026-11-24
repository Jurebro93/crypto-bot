"""The best stop, grace, take profit, trailing and time stop per source, learned from its own history (15.11., owner:
"ako pratimo neki novčanik, vidi njegove prosječne stop lossove i prema tome postavi naše ... nauči sve iz podataka").

1. The entries (izlazi/data.build): every source's entries with their paths, costs and mirror sales.
2. Walk-forward by TIME (split): per kind one cut at the IN_SHARE (70 %) quantile of its entry times; in-sample = the
   entries whose whole path ended before the cut (an embargo: no outcome the cut could not have known), out-of-sample
   = the entries from the cut on. Every prior a source is shrunk toward is fitted on entries whose paths ended before
   its kind's cut only (the global one too): nothing a source is judged on out of sample was seen by its fit.
3. Priors (hierarchical, empirical Bayes): the global rule (every kind, a sample of GLOBAL_SAMPLE) -> per kind (wallet,
   kol, ekipa, strategy; a sample of KIND_SAMPLE, shrunk toward the global by K_DEFAULT pseudo-entries) -> per source:
   the source's in-sample mean of a rule is shrunk toward its kind's mean of the same rule by K pseudo-entries, K =
   within-source variance / between-source variance of the kind (method of moments on the default rule; K_MIN..K_MAX).
   Ten lucky trades do not make a rule; a source with 3 entries gets (almost) its kind's rule.
4. Search (fit): the stop x grace grid jointly (the owner's question: a wider stop and waiting), then coordinate descent
   over TP1, share, trailing, time stop, mirror, stop and grace (PASSES passes), on score = shrunk mean - DD_W x the
   in-sample drawdown per trade (a rule that loses in streaks is worse than its mean). A time stop is offered only when
   COVER_SHARE of the source's paths reach it. Multiple testing (95+ rules on a few dozen trades): among the rules
   within ONE standard error of the best score, the SIMPLEST (sim.complexity: no grace, no partial, no trailing, no
   time stop) is taken, then the best.
5. Out of sample, on the newer entries the rule was not chosen on: n_out, its EV, 90 % bootstrap interval, hit rate,
   worst trade, drawdown, and the same for today's default (brzi profit) on the same entries, with the paired interval
   of the difference. izlazi/store.proven decides real money from these (izlazi/apply).
Rows: every source with at least MIN_ROW_N entries (a source under MIN_N entries or MIN_OUT out of sample is flagged
"shrunk": its rule rests mostly on the prior), every kind's prior ("<kind>", "*") and the global ("*", "*"); at most
MAX_ROWS (the most entries first).
"""
import math
import statistics
import time

from izlazi import data as idata, sim, store

IN_SHARE = 0.7
MIN_N = 20
MIN_OUT = 8
MIN_ROW_N = 5
MIN_COVER_S = 30 * 60       # an entry whose path is shorter than this is not used (a 45-min time stop needs 45 min)
DD_W = 0.25
K_DEFAULT = 20.0
K_MIN, K_MAX = 5.0, 200.0
GLOBAL_SAMPLE = 2000
KIND_SAMPLE = 1500
OUT_SAMPLE = 3000
PASSES = 2
COVER_SHARE = 0.8
BOOT = 500
MAX_ROWS = 3000
WIN_MFE = 0.20
KINDS = ("wallet", "kol", "ekipa", "strategy")
SEED = 11


def split(entries, share=IN_SHARE, horizon=sim.HORIZON_S):
    """(in-sample, out-of-sample, cut ts): one time cut for every source (see the module text)."""
    ts = sorted(e["ts"] for e in entries)
    if not ts:
        return [], [], None
    cut = ts[min(len(ts) - 1, int(len(ts) * share))]
    ins = [e for e in entries if e["ts"] + min(e["cover"], horizon) <= cut]
    outs = [e for e in entries if e["ts"] >= cut]
    return ins, outs, cut


def sample(xs, n, seed=SEED):
    """At most n of xs, spread evenly over time (xs sorted by time), always the same for the same input."""
    if len(xs) <= n:
        return list(xs)
    step = len(xs) / n
    return [xs[int(i * step)] for i in range(n)]


class Scorer:
    """Results of rules over a fixed set of entries (in time order), cached per rule."""

    def __init__(self, entries, slip_stop=sim.SLIP_STOP):
        self.entries = entries
        self.preps = [sim.Prep(e["arrs"], e["cost"], e.get("sell_s"), e.get("rug_s"), e.get("cover"), slip_stop)
                      for e in entries]
        self.n = len(entries)
        self._r = {}
        self.mirror_ok = any(e.get("sell_s") is not None for e in entries)

    def rets(self, p):
        r = self._r.get(p)
        if r is None:
            r = [x.net(p) for x in self.preps]
            self._r[p] = r
        return r

    def mean(self, p):
        r = self.rets(p)
        return sum(r) / len(r) if r else None

    def allowed(self, cover_share=COVER_SHARE, also=None):
        """The grid this set of entries (and `also`'s) can judge: the time stops COVER_SHARE of the paths reach; the
        mirror only when some entry has a sale."""
        preps = self.preps + (also.preps if also is not None else [])
        n = len(preps)
        tm = [t for t in sim.TMAXS if n and sum(x.covers(t) for x in preps) >= cover_share * n]
        if not tm:
            tm = [sim.TMAXS[0]]
        return {**sim.VALUES, "tmax": tuple(tm), "mirror": sim.MIRRORS if self.mirror_ok else (0,)}


def start_rule(allowed, mirror_ok):
    d = sim.DEFAULT
    return sim.canon(d._replace(tmax=max(allowed["tmax"])), mirror_ok)


def default_rule(mirror_ok):
    return sim.canon(sim.DEFAULT, mirror_ok)


def fit(sc, prior=None, k=0.0, passes=PASSES, dd_w=DD_W, allowed=None):
    """(chosen rule, memo {rule: (score, shrunk mean, raw mean, drawdown, sd)}) on the scorer's entries (see 4.)."""
    n = sc.n
    allowed = allowed or sc.allowed()
    mo = sc.mirror_ok
    memo = {}

    def score(p):
        p = sim.canon(p, mo)
        v = memo.get(p)
        if v is None:
            r = sc.rets(p) if n else []
            m = sum(r) / n if n else None
            pm = prior(p) if prior is not None else None
            if m is None:
                shr = pm if pm is not None else 0.0
            elif pm is not None and k > 0:
                shr = (n * m + k * pm) / (n + k)
            else:
                shr = m
            dd = sim.max_dd(r) if r else 0.0
            v = (shr - dd_w * dd / max(n, 1), shr, m, dd, sim.sd(r) if r else 0.0)
            memo[p] = v
        return v[0]

    best = start_rule(allowed, mo)
    bs = score(best)
    for sl in allowed["sl"]:
        for g in allowed["grace"]:
            p = sim.canon(best._replace(sl=sl, grace=g), mo)
            s = score(p)
            if s > bs + 1e-12:
                best, bs = p, s
    for _ in range(passes):
        changed = False
        for dim in ("tp1", "share", "trail", "tmax", "mirror", "sl", "grace"):
            for v in allowed[dim]:
                p = sim.canon(best._replace(**{dim: v}), mo)
                s = score(p)
                if s > bs + 1e-12:
                    best, bs, changed = p, s, True
        if not changed:
            break
    score(default_rule(mo))   # today's rule in the memo too (its in-sample numbers go on the row)
    se = (memo[best][4] / math.sqrt(n)) if n > 1 else 0.0
    cands = [p for p, v in memo.items() if v[0] >= bs - se - 1e-12 and p.tmax in allowed["tmax"]]
    hold = max(allowed["tmax"])
    chosen = min(cands, key=lambda p: (sim.complexity(p, hold), -memo[p][0], p != default_rule(mo)))
    return chosen, memo


def eb_k(groups, k_min=K_MIN, k_max=K_MAX):
    """Empirical-Bayes prior strength from [(n, mean, var)] of the sources of one kind (method of moments)."""
    gs = [g for g in groups if g[0] >= 2]
    if len(gs) < 3:
        return K_DEFAULT
    w = sum(g[0] - 1 for g in gs)
    sigma2 = sum((g[0] - 1) * g[2] for g in gs) / w if w else 0.0
    means = [g[1] for g in gs]
    tau2 = statistics.pvariance(means) - statistics.mean([sigma2 / g[0] for g in gs])
    if tau2 <= 1e-12:
        return k_max
    return max(k_min, min(k_max, sigma2 / tau2))


def oos(sc, p, d):
    """Out-of-sample numbers of rule p against the default d on the scorer's entries (percent)."""
    if not sc.n:
        return {"n_out": 0}
    r, rd = sc.rets(p), sc.rets(d)
    lo, hi = sim.bootstrap(r, BOOT)
    dlo, dhi = sim.bootstrap(r, BOOT, ys=rd)
    pct = lambda x: round(x * 100, 2) if x is not None else None   # noqa: E731
    return {"n_out": sc.n, "ev_out": pct(sim.mean(r)), "ci_lo": pct(lo), "ci_hi": pct(hi),
            "default_ev_out": pct(sim.mean(rd)), "diff_ci": [pct(dlo), pct(dhi)],
            "hit_out": round(sum(1 for x in r if x > 0) / sc.n, 3), "worst_out": pct(min(r)),
            "dd_out": round(sim.max_dd(r), 3), "default_hit_out": round(sum(1 for x in rd if x > 0) / sc.n, 3),
            "default_worst_out": pct(min(rd)), "default_dd_out": round(sim.max_dd(rd), 3)}


def behaviour(entries, own=None):
    """The source's own behaviour from its paths (+ a wallet's own exits): how deep its winners dip before rising, how
    long they take to come back, MFE, hit rate, and the grid stop that 75 % of its winners survive (sl_hint)."""
    st = [e["stats"] for e in entries if e.get("stats")]
    win = [s for s in st if s["mfe"] >= WIN_MFE]
    mae = [-s["mae_before_peak"] * 100 for s in win]
    rec = [s["recover_min"] for s in win if s.get("recover_min") is not None]
    mfe = [s["mfe"] * 100 for s in st]
    out = {"n": len(st), "winners": len(win), "hit20": round(len(win) / len(st), 3) if st else None,
           "mae_win_p50": _r(sim.quantile(mae, 0.5)), "mae_win_p75": _r(sim.quantile(mae, 0.75)),
           "mae_win_p90": _r(sim.quantile(mae, 0.9)), "recover_min_p50": _r(sim.quantile(rec, 0.5)),
           "mfe_p50": _r(sim.quantile(mfe, 0.5)), "mfe_p75": _r(sim.quantile(mfe, 0.75)),
           "t_peak_min_p50": _r(sim.quantile([s["t_peak_min"] for s in win], 0.5))}
    p75 = out["mae_win_p75"]
    out["sl_hint"] = next((s for s in sim.SLS if p75 is not None and s >= p75), None) if p75 is not None else None
    if own:
        out["own"] = own
    return out


def _r(x, k=1):
    return round(x, k) if x is not None else None


def _row(kind, sid, chosen, memo, n, sc_out, d, stats, k, prior_key, mirror_ok, cut, now):
    o = oos(sc_out, chosen, d) if sc_out is not None else {"n_out": 0}
    v = memo.get(chosen)
    dv = memo.get(d)
    stats = dict(stats)
    stats.update({k_: o[k_] for k_ in o if k_ not in ("n_out", "ev_out", "ci_lo", "ci_hi", "default_ev_out")})
    stats.update({"ev_in_raw": round(v[2] * 100, 2) if v and v[2] is not None else None,
                  "default_ev_in": round(dv[2] * 100, 2) if dv and dv[2] is not None else None,
                  "dd_in": round(v[3], 3) if v else None, "k": round(k, 1), "prior": prior_key,
                  "shrunk": bool(n < MIN_N or o["n_out"] < MIN_OUT), "complexity": sim.complexity(chosen),
                  "rules_tried": len(memo), "cut_ts": cut, "words": sim.words(chosen),
                  "mirror_judged": bool(mirror_ok)})
    row = {"source_kind": kind, "source_id": sid, "params": sim.as_dict(chosen), "n": n, "n_out": o["n_out"],
           "ev_in": round(v[1] * 100, 2) if v else None, "ev_out": o.get("ev_out"), "ci_lo": o.get("ci_lo"),
           "ci_hi": o.get("ci_hi"), "default_ev_out": o.get("default_ev_out"), "stats": stats, "ts": now}
    ok, why = store.proven(row)
    row["stats"]["proof"] = ok
    row["stats"]["proof_why"] = why
    return row


def learn(entries, meta=None, now=None, log=print, budget_s=None, slip_stop=None):
    """Rows for learned_exits from the entries (see the module text) and a summary."""
    t0 = time.monotonic()
    now = int(now or time.time())
    meta = meta or {}
    slip = slip_stop if slip_stop is not None else (meta.get("costs") or {}).get("slip_stop_pct", sim.SLIP_STOP * 100) / 100
    entries = [e for e in entries if e["cover"] >= MIN_COVER_S - sim.TOL_S]
    entries.sort(key=lambda e: e["ts"])
    ins, outs, cut = split(entries)
    rows = []
    # the global row (its own cut)
    g_sc = Scorer(sample(ins, GLOBAL_SAMPLE), slip)
    g_out = Scorer(sample(outs, OUT_SAMPLE), slip)
    g_rule, g_memo = fit(g_sc)
    if g_sc.n or g_out.n:
        rows.append(_row("*", "*", g_rule, g_memo, len(entries), g_out, default_rule(g_sc.mirror_ok),
                         behaviour(sample(entries, GLOBAL_SAMPLE)), 0.0, None, g_sc.mirror_ok, cut, now))
    by_kind = {}
    for e in entries:
        by_kind.setdefault(e["kind"], []).append(e)
    summary = {"entries": len(entries), "in": len(ins), "out": len(outs), "cut_ts": cut, "kinds": {}}
    own = meta.get("wallet_own") or {}
    for kind in KINDS:
        es = by_kind.get(kind) or []
        if not es:
            continue
        # every kind has its own time cut (its sources trade in different weeks); the global prior a kind is shrunk
        # toward holds only entries whose paths ended before THAT cut (no look-ahead for any source of the kind)
        k_in, k_out, k_cut = split(es)
        in_ids, out_ids = {id(e) for e in k_in}, {id(e) for e in k_out}
        gk_sc = Scorer(sample([e for e in entries if e["ts"] + min(e["cover"], sim.HORIZON_S) <= k_cut],
                              GLOBAL_SAMPLE // 2), slip)
        k_sc = Scorer(sample(k_in, KIND_SAMPLE), slip)
        kg = K_DEFAULT

        def kprior(p, g_mean=gk_sc.mean, gn=gk_sc.n):
            return g_mean(p) if gn else None
        k_rule, k_memo = fit(k_sc, kprior, kg)
        k_out_sc = Scorer(sample(k_out, OUT_SAMPLE), slip)
        rows.append(_row(kind, "*", k_rule, k_memo, len(es), k_out_sc, default_rule(k_sc.mirror_ok),
                         behaviour(sample(es, KIND_SAMPLE)), kg, "*:*", k_sc.mirror_ok, k_cut, now))
        kn = k_sc.n

        def prior(p, k_mean=k_sc.mean, kn=kn, kprior=kprior, kg=kg):
            m = k_mean(p) if kn else None
            pm = kprior(p)
            if m is None:
                return pm
            return (kn * m + kg * pm) / (kn + kg) if pm is not None else m
        srcs = {}
        for e in es:
            srcs.setdefault(e["src"], []).append(e)
        groups = []
        for sid, xs in srcs.items():
            xi = [e for e in xs if id(e) in in_ids]
            if len(xi) >= 2:
                r = [sim.Prep(e["arrs"], e["cost"], e.get("sell_s"), e.get("rug_s"), e.get("cover"), slip).net(
                    default_rule(any(x.get("sell_s") is not None for x in xi))) for e in xi]
                groups.append((len(r), sim.mean(r), sim.sd(r) ** 2))
        k = eb_k(groups)
        done = 0
        stopped = None
        for sid, xs in sorted(srcs.items(), key=lambda x: -len(x[1])):
            if len(xs) < MIN_ROW_N:
                continue
            if budget_s and time.monotonic() - t0 > budget_s:
                stopped = f"stalo nakon {budget_s} s"
                break
            xi = [e for e in xs if id(e) in in_ids]
            xo = [e for e in xs if id(e) in out_ids]
            sc = Scorer(xi, slip)
            so = Scorer(xo, slip)
            mo = sc.mirror_ok or so.mirror_ok
            sc.mirror_ok = so.mirror_ok = mo
            allowed = sc.allowed(also=so)
            rule, memo = fit(sc, prior, k, allowed=allowed)
            b = behaviour(xs, own.get(sid) if kind == "wallet" else None)
            b["how"] = _hows(xs)
            b["cost_pct_p50"] = _r(statistics.median(e["cost"] for e in xs) * 100, 2)
            rows.append(_row(kind, sid, rule, memo, len(xs), so, default_rule(mo), b, k, f"{kind}:*", mo, k_cut, now))
            done += 1
        summary["kinds"][kind] = {"entries": len(es), "in": len(k_in), "out": len(k_out), "cut_ts": k_cut,
                                  "sources": len(srcs),
                                  "rows": done, "k": round(k, 1), "rule": sim.as_dict(k_rule),
                                  "enough": sum(1 for xs in srcs.values() if len(xs) >= MIN_N), "stopped": stopped}
    src_rows = sorted((r for r in rows if r["source_id"] != "*"), key=lambda r: -r["n"])[:MAX_ROWS]
    rows = [r for r in rows if r["source_id"] == "*"] + src_rows
    summary["rows"] = len(rows)
    summary["proven"] = sum(1 for r in rows if r["stats"].get("proof"))
    summary["s"] = round(time.monotonic() - t0, 1)
    log(f"naučeni izlazi: {len(rows)} redova ({summary['proven']} dokazano van uzorka za pravi novac) za "
        f"{summary['s']:.0f} s")
    return rows, summary


def _hows(xs):
    out = {}
    for e in xs:
        out[e["how"]] = out.get(e["how"], 0) + 1
    return dict(sorted(out.items(), key=lambda x: -x[1])[:4])


def run(p=None, now=None, log=print, path=None, budget_s=None, entries=None, cov=None, meta=None):
    """The whole learning run: data -> rows -> izlazi.db. Returns the summary."""
    now = int(now or time.time())
    t0 = time.monotonic()
    if entries is None:
        entries, cov, meta = idata.build(p, now, log=log)
    rows, summary = learn(entries, meta, now, log=log, budget_s=budget_s)
    info = {"summary": summary, "coverage": cov or {}, "meta": {k: v for k, v in (meta or {}).items()
                                                                if k != "wallet_own"},
            "s": round(time.monotonic() - t0, 1)}
    if not [r for r in rows if r["source_id"] != "*"] and not entries:
        # nothing read tonight (a locked or missing database): yesterday's rows stay (izlazi/store.MAX_AGE_S retires
        # them after 3 days), never an empty table over them
        log("naučeni izlazi: nema ulaza s putanjom, prethodni naučeni izlazi ostaju")
        info["kept_previous"] = True
        return info
    con = store.connect(path)
    try:
        store.save(con, rows, info, now)
    finally:
        con.close()
    return info

