"""What the learned exits say, for the owner (markdown), the pages, the MCP API (get_learned_exits) and the OpenAI
critic (critic_summary): per source the rule, n, EV out of sample against today's default, the interval, whether it
runs with real money, and the source's own behaviour (how deep its winners dip, its own stop)."""
import datetime as dt
import json

from izlazi import apply, sim, store

KIND_HR = {"wallet": "novčanik", "kol": "influencer", "ekipa": "ekipa", "strategy": "strategija", "*": "svi"}


def _pct(x):
    return f"{x:+.2f} %".replace(".", ",") if isinstance(x, (int, float)) else "–"


def _share(x):
    return f"{x:.0%}".replace("%", " %") if isinstance(x, (int, float)) else "–"


def _when(ts):
    return dt.datetime.fromtimestamp(ts).strftime("%d.%m. %H:%M") if ts else "–"


def rows_sorted(rows, kind=None, sid=None, top=None, proven_only=False):
    """Source rows (not the priors), the biggest out-of-sample gain over the default first (n_out >= 1)."""
    out = [r for r in rows.values() if r["source_id"] != "*" and (kind is None or r["source_kind"] == kind)
           and (sid is None or r["source_id"] == sid)]
    if proven_only:
        out = [r for r in out if store.proven(r)[0]]

    def gain(r):
        if r.get("ev_out") is None or r.get("default_ev_out") is None:
            return -1e9
        return r["ev_out"] - r["default_ev_out"]
    out.sort(key=lambda r: (-(gain(r) if (r.get("n_out") or 0) >= store.PROOF_N_OUT else gain(r) - 1e6), -r["n"]))
    return out[:top] if top else out


def compact(r):
    """One row for the critic / the MCP API."""
    p = sim.from_dict(r["params"])
    st = r.get("stats") or {}
    ok, why = store.proven(r)
    beh = {k: st.get(k) for k in ("hit20", "mae_win_p50", "mae_win_p75", "mae_win_p90", "recover_min_p50", "mfe_p50",
                                  "sl_hint") if st.get(k) is not None}
    if st.get("own"):
        beh["own"] = st["own"]
    return {"source": f"{r['source_kind']}:{r['source_id']}", "params": r["params"], "rule": sim.words(p),
            "n": r["n"], "n_out": r["n_out"], "ev_in_pct": r.get("ev_in"), "ev_out_pct": r.get("ev_out"),
            "ci90_pct": [r.get("ci_lo"), r.get("ci_hi")], "default_ev_out_pct": r.get("default_ev_out"),
            "diff_ci90_pct": st.get("diff_ci"), "hit_out": st.get("hit_out"), "worst_out_pct": st.get("worst_out"),
            "default_worst_out_pct": st.get("default_worst_out"), "shrunk": st.get("shrunk"),
            "real_money": ok, "real_money_why": why or "dokazano van uzorka", "behaviour": beh}


def critic_summary(top=30, path=None):
    """The learned exits for the OpenAI critic (critic/ package, the 2-day deep review): JSON-able dict with the run's
    coverage, the global and per-kind priors, the `top` sources with the biggest out-of-sample gain over today's
    default (and every source proven for real money), each with params, n, EV out vs default, interval, behaviour.
    Read-only; {"available": False, "why"} before the first run."""
    rows = store.load(path)
    run = store.last_run(path)
    if not rows:
        return {"available": False, "why": "naučeni izlazi još nisu izračunati (noćni posao run_izlazi.py night)"}
    pri = [compact(r) for r in sorted(rows.values(), key=lambda r: (r["source_kind"] != "*", r["source_kind"]))
           if r["source_id"] == "*"]
    srcs = rows_sorted(rows, top=top)
    seen = {id(r) for r in srcs}
    srcs += [r for r in rows_sorted(rows, proven_only=True) if id(r) not in seen]
    summ = (run or {}).get("summary") or {}
    return {"available": True, "as_of": max(r["ts"] for r in rows.values()), "units": "EV in % of the stake per trade, "
            "net of the measured round-trip cost and stop slippage; out of sample = the newer 30 % by time",
            "default_rule": sim.as_dict(sim.DEFAULT), "default_words": sim.words(sim.DEFAULT),
            "coverage": (run or {}).get("coverage"), "costs": ((run or {}).get("meta") or {}).get("costs"),
            "counts": {"rows": summ.get("rows"), "proven_real_money": summ.get("proven"),
                       "entries": summ.get("entries"), "in": summ.get("in"), "out": summ.get("out")},
            "priors": pri, "sources": [compact(r) for r in srcs],
            "real_money_rule": (f"learned params run with real money only with n_out >= {store.PROOF_N_OUT}, EV out of "
                                f"sample >= default + {store.PROOF_MARGIN:g} point, the 90 % interval not entirely "
                                "under the default and the paired 90 % interval of (learned - default) not under "
                                f"{store.PROOF_DIFF_LO:+g} point at its low end; else today's default (brzi profit)")}


def mcp(args=None, path=None):
    """get_learned_exits: {source_kind?, source_id?, top?, proven_only?}."""
    a = args or {}
    rows = store.load(path)
    if not rows:
        return {"available": False, "why": "naučeni izlazi još nisu izračunati (noćni posao run_izlazi.py night)",
                "default_rule": sim.words(sim.DEFAULT)}
    try:
        top = max(1, min(200, int(a.get("top") or 30)))
    except (TypeError, ValueError):
        top = 30
    kind, sid = a.get("source_kind"), a.get("source_id")
    if kind is not None and kind not in ("wallet", "kol", "ekipa", "strategy", "*"):
        return {"error": "source_kind: wallet | kol | ekipa | strategy | *"}
    out = critic_summary(top=top, path=path)
    if kind or sid or a.get("proven_only"):
        out["sources"] = [compact(r) for r in rows_sorted(rows, kind, sid, top, bool(a.get("proven_only")))]
        if sid and kind:
            pr = rows.get((kind, "*"))
            out["prior"] = compact(pr) if pr else None
    return out


def markdown(path=None, top=25):
    """The report for the owner (CLI `run_izlazi.py report`), in Croatian."""
    rows = store.load(path, fresh=True)
    run = store.last_run(path)
    if not rows:
        return "# Naučeni izlazi\n\nJoš nema izračuna (noćni posao `run_izlazi.py night`, 01–06 Zagreb).\n"
    summ = (run or {}).get("summary") or {}
    cov = (run or {}).get("coverage") or {}
    costs = ((run or {}).get("meta") or {}).get("costs") or {}
    b = [f"# Naučeni izlazi ({_when(max(r['ts'] for r in rows.values()))})", "",
         f"Zadano danas: **{sim.words(sim.DEFAULT)}** (brzi profit). Ulazi: {summ.get('entries', '–')} "
         f"(u uzorku {summ.get('in', '–')}, van uzorka {summ.get('out', '–')}, rez po vremenu {_when(summ.get('cut_ts'))}). "
         f"Trošak po krugu medijan {costs.get('median_pct', '–')} % (p90 {costs.get('p90_pct', '–')} %, najmanje "
         f"{costs.get('min_pct', 2)} %), slippage stopa {costs.get('slip_stop_pct', '–')} % ({costs.get('slip_from', '–')}).", "",
         "## Pokrivenost po vrsti izvora", "",
         "| vrsta | izvora | ulaza | s putanjom | pravila | bez puta | samo grubo | 4 h | 24 h | dovoljno (n ≥ 20) |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for k, c in cov.items():
        kk = (summ.get("kinds") or {}).get(k) or {}
        b.append(f"| {KIND_HR.get(k, k)} | {c.get('izvori', 0)} | {c.get('ulazi', 0)} | {c.get('s_putom', 0)} | "
                 f"{sum((c.get('pravila') or {}).values())} | {c.get('bez_puta', 0)} | {c.get('samo_grubo', 0)} | "
                 f"{(c.get('sati') or {}).get('4h', 0)} | {(c.get('sati') or {}).get('24h', 0)} | {kk.get('enough', 0)} |")
    b += ["", "## Priori (svi izvori jedne vrste)", "", "| izvor | pravilo | n | van uzorka | EV van | zadano van | 90 % |",
          "|---|---|---|---|---|---|---|"]
    for r in sorted((r for r in rows.values() if r["source_id"] == "*"), key=lambda r: r["source_kind"]):
        b.append(f"| {KIND_HR.get(r['source_kind'], r['source_kind'])} | {sim.words(sim.from_dict(r['params']))} | "
                 f"{r['n']} | {r['n_out']} | {_pct(r.get('ev_out'))} | {_pct(r.get('default_ev_out'))} | "
                 f"{_pct(r.get('ci_lo'))} .. {_pct(r.get('ci_hi'))} |")
    b += ["", f"## Najveći dobitak van uzorka (top {top})", "",
          "| izvor | pravilo | n | van | EV van | zadano | 90 % | pogodak | najgori | pravi novac | njegovi dobitnici padnu (p50/p75) | njegov stop |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows_sorted(rows, top=top):
        st = r.get("stats") or {}
        own = st.get("own") or {}
        ok, why = store.proven(r)
        b.append(f"| {apply.key_words((r['source_kind'], r['source_id']))} | {sim.words(sim.from_dict(r['params']))} | "
                 f"{r['n']} | {r['n_out']} | {_pct(r.get('ev_out'))} | {_pct(r.get('default_ev_out'))} | "
                 f"{_pct(r.get('ci_lo'))} .. {_pct(r.get('ci_hi'))} | "
                 f"{_share(st.get('hit_out'))} | {_pct(st.get('worst_out'))} | {'DA' if ok else 'ne: ' + why} | "
                 f"{st.get('mae_win_p50', '–')} / {st.get('mae_win_p75', '–')} % | "
                 f"{own.get('own_stop_p50', '–')} / {own.get('own_stop_p75', '–')} % |")
    b += ["", f"Dokazano za pravi novac: {summ.get('proven', 0)} izvora (n van uzorka ≥ {store.PROOF_N_OUT}, EV van "
          f"uzorka ≥ zadano + {store.PROOF_MARGIN:g} bod, interval nije cijeli ispod zadanog, upareni interval razlike "
          f"ne ispod {store.PROOF_DIFF_LO:+g} boda). Demo koristi naučeno za svaki izvor s redom (mali n: skupljeno "
          "prema prioru)."]
    return "\n".join(b) + "\n"


def dumps(x):
    return json.dumps(x, ensure_ascii=False, indent=1, default=str)
