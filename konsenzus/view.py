"""What the source consensus strategy shows: the "Konsenzus izvora" card under the terminal page's Postavke, the MCP
read tool get_source_strategy and the OpenAI critic's context block. Read-only (konsenzus.db, league.db, trade.db)."""


def _pct(x):
    return "—" if x is None else f"{x:+.1f} %".replace(".", ",")


def summary():
    """{best, holdout, train, ranking (each family's chosen with holdout numbers), demo, real_money {on, switch,
    why}, run {ts, events, days}} — the one dict the card, the MCP tool and the critic read. No source ids."""
    from konsenzus import gate, live, store
    ts, data = store.latest()
    b = store.best(cached=False)
    demo = live.demo_stats()
    flag = live.mode()
    why = gate.real_refusal(b)
    ranking = []
    for key in (data or {}).get("ranking") or []:
        c = next((x for x in ((data or {}).get("chosen") or {}).values() if x.get("key") == key), None)
        if c:
            ranking.append({"key": key, "family": c["family"], "exit": c["exit"], "params": c["params"],
                            "train": c.get("train"), "holdout": c.get("holdout")})
    base = next((c for c in (data or {}).get("configs") or [] if c.get("family") == "svi" and c.get("exit") == "E"),
                None)
    return {"available": data is not None, "run_ts": ts, "flag": flag,
            "best": ({k: b.get(k) for k in ("key", "family", "family_name", "params", "exit", "exit_words", "proof_ok",
                                           "proof_why", "chosen_why", "n_sources", "n_groups", "ts")} if b else None),
            "holdout": (b or {}).get("holdout"), "train": (b or {}).get("train"), "ranking": ranking,
            "baseline_all_signals_E": (base or {}).get("holdout"),
            "demo": demo, "real_money": {"switch_on": gate.switch_on(), "allowed": why is None, "why": why,
                                         "proof": gate.PROOF},
            "run": {"events": (data or {}).get("events"), "events_by_kind": (data or {}).get("events_by_kind"),
                    "days": {k: len(v) for k, v in ((data or {}).get("days") or {}).items()},
                    "slip_stop_pct": (data or {}).get("slip_stop_pct"), "s": (data or {}).get("s"),
                    "groups": (data or {}).get("groups")}}


def mcp(args=None):
    """MCP get_source_strategy: summary(); with full=true also every configuration's train numbers."""
    args = args or {}
    try:
        d = summary()
    except Exception as e:  # noqa: BLE001
        return {"error": f"konsenzus nije čitljiv ({type(e).__name__})"}
    if args.get("full"):
        from konsenzus import store
        _ts, data = store.latest()
        d["configs"] = [{"key": c["key"], "train": c.get("train"), "holdout": c.get("holdout")}
                        for c in (data or {}).get("configs") or []]
    return d


def critic_summary():
    """A small block for the OpenAI critic: the candidates' holdout numbers, the decision, the demo so far."""
    d = summary()
    if not d.get("available"):
        return None
    keep = ("n", "per_day", "ev_pct", "ci_lo_pct", "ci_hi_pct", "hit", "worst_pct", "max_dd", "rug_share")
    return {"najbolji": (d["best"] or {}).get("key"), "dokaz": (d["best"] or {}).get("proof_why"),
            "kandidati_holdout": [{"k": r["key"], **{k: (r.get("holdout") or {}).get(k) for k in keep},
                                   "trening_n": (r.get("train") or {}).get("n"),
                                   "trening_ev_pct": (r.get("train") or {}).get("ev_pct")} for r in d["ranking"]],
            "osnova_svi_signali": {k: (d.get("baseline_all_signals_E") or {}).get(k) for k in keep},
            "demo": {k: d["demo"].get(k) for k in ("n", "open", "ev_pct", "ci90_lo_pct", "pnl_usd")},
            "pravi_novac": d["real_money"]["why"] or "dopušten", "dogadaja": d["run"]["events"],
            "dani": d["run"]["days"], "klizanje_stopa_pct": d["run"]["slip_stop_pct"]}


def card_html(sec, item, esc, owner=True):
    """The closed row "Konsenzus izvora" (owner only): the best candidate, its holdout numbers, the demo so far and
    why real money is on / off; one row per family's chosen candidate."""
    if not owner:
        return ""
    d = summary()
    if not d.get("available") and d.get("flag") == "off":
        return ""
    b, h, dm, rm = d.get("best") or {}, d.get("holdout") or {}, d.get("demo") or {}, d.get("real_money") or {}
    if not d.get("available"):
        meta = "još nema izračuna (prvi nakon deploya)"
        inner = ("<p class=mut>Istraživanje (run_konsenzus.py) radi nakon deploya i noću; demo ulazi kreću čim postoji "
                 "kandidat.</p>")
        return sec("Konsenzus izvora", meta, inner, sid="konsenzus")
    real = ("uključen" if rm.get("allowed") else "isključen")
    meta = (f"{b.get('key') or '—'} · holdout n {h.get('n', 0)}, EV {_pct(h.get('ev_pct'))} · demo {dm.get('n', 0)} "
            f"zatvorenih · pravi novac {real}")
    rows = []
    for r in d.get("ranking") or []:
        rh, rt = r.get("holdout") or {}, r.get("train") or {}
        txt = (f"<p>Trening: n {rt.get('n', 0)}, EV {_pct(rt.get('ev_pct'))}. Holdout: n {rh.get('n', 0)}, EV "
               f"{_pct(rh.get('ev_pct'))}, 90 % interval [{_pct(rh.get('ci_lo_pct'))}; {_pct(rh.get('ci_hi_pct'))}], "
               f"{rh.get('per_day', 0)} tradeova dnevno, pogodak {rh.get('hit', '—')}, najgori {_pct(rh.get('worst_pct'))}"
               f", max pad {rh.get('max_dd', '—')} uloga, rug {rh.get('rug_share', '—')}.</p>")
        rows.append(item(esc(r["key"]), f"holdout EV {_pct(rh.get('ev_pct'))}", txt, value=str(rh.get("n", 0)),
                         sub="holdout", iid=f"kz-{esc(r['key'])}"))
    base = d.get("baseline_all_signals_E") or {}
    inner = (f"<p><b>Najbolji kandidat:</b> {esc(b.get('family_name') or '—')} ({esc(b.get('key') or '—')}), izlaz: "
             f"{esc(b.get('exit_words') or '—')}. Izvora u selekciji: {b.get('n_sources') or 0}.</p>"
             f"<p><b>Demo do sada:</b> {dm.get('n', 0)} zatvorenih, {dm.get('open', 0)} otvorenih, EV "
             f"{_pct(dm.get('ev_pct'))} (nakon troška), PnL ${dm.get('pnl_usd', 0):,.2f}. Zastavica: {esc(d.get('flag'))}.</p>"
             f"<p><b>Pravi novac:</b> {esc(real)} — {esc(rm.get('why') or 'prekidač uključen i dokaz prošao')}. Dokaz: "
             f"holdout n ≥ {rm['proof']['n']}, EV ≥ +{rm['proof']['ev_min_pct']:g} %, donja granica 90 % intervala "
             f"> 0.</p>"
             f"<p class=mut>Osnova (svi signali, isti izlaz E) na istom holdoutu: n {base.get('n', 0)}, EV "
             f"{_pct(base.get('ev_pct'))}.</p>" + "".join(rows)
             + "<p class=ms-hint>Walk-forward na našim 30 dana: ocjena izvora samo iz onoga što se znalo prije signala, "
               "korelirani izvori (klasteri, grupe novčanika) kao jedan, trošak i klizanje stopa uvijek uključeni; "
               "parametri izabrani na ranijih 75 % dana, zadnjih 25 % (holdout) gleda se jednom.</p>")
    return sec("Konsenzus izvora", meta, inner, sid="konsenzus", value=str(h.get("n", 0)) if h else None,
               sub="holdout" if h else None)
