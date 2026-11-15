"""What the page (card "Oscilator" under Ostalo), the MCP tool get_oscillators and the OpenAI critic read (one dict)."""


def summary():
    """{available, run_ts, flag, top, top_day, walk (per size@target: top-K and every eligible token), range_scalp,
    fees, coverage, cost, demo, real_money} — no addresses beyond the token mints of the top list."""
    from oscilator import gate, live, store
    ts, data = store.latest()
    demo = live.demo_stats()
    flag = live.mode()
    why = gate.real_refusal()
    ok_wf, why_wf, x_wf = gate.wf_proof()
    d = data or {}
    wf = d.get("walk") or {}
    return {"available": data is not None, "run_ts": ts, "flag": flag, "top": d.get("top") or [],
            "top_day": d.get("top_day"), "walk_days": wf.get("days"), "persistence": wf.get("persistence"),
            "walk_top": wf.get("top"), "walk_all": {k: {f: v.get(f) for f in ("n", "ev_pct", "per_token_day")}
                                                    for k, v in (wf.get("all") or {}).items()},
            "range_scalp": d.get("range_scalp"), "fees": d.get("fees"), "coverage": d.get("coverage"),
            "cost": d.get("cost"), "sensitivity": d.get("sensitivity"), "rule": d.get("rule"),
            "demo": demo, "real_money": {"switch_on": gate.switch_on(), "allowed": why is None, "why": why,
                                         "walk_forward_ok": ok_wf, "walk_forward_why": why_wf,
                                         "walk_forward_at_real_size": x_wf, "proof": gate.PROOF,
                                         "caps": gate.real_caps()}}


def mcp(args=None):
    """MCP get_oscillators: summary(); full=false trims the walk-forward to the 1 $ target."""
    args = args or {}
    try:
        d = summary()
    except Exception as e:  # noqa: BLE001
        return {"error": f"oscilator nije čitljiv ({type(e).__name__})"}
    if not args.get("full"):
        d["walk_top"] = {k: v for k, v in (d.get("walk_top") or {}).items() if k.endswith("@1")}
        d.pop("fees", None)
        d.pop("sensitivity", None)
    return d


def critic_summary():
    """A small block for the OpenAI critic: the walk-forward per size (1 $ target), the range scalp on the same days,
    the demo so far and the real-money decision."""
    d = summary()
    if not d.get("available"):
        return None
    keep = ("n", "per_token_day", "hit", "ev_pct", "ci90_ev_pct", "usd_day", "max_dd_usd", "broke_share", "ev_demo_pct")
    rc = d.get("range_scalp") or {}
    return {"walk_forward_top10_cilj_1usd": {k.split("@")[0]: {f: v.get(f) for f in keep}
                                             for k, v in (d.get("walk_top") or {}).items() if k.endswith("@1")},
            "dana": d.get("walk_days"), "perzistencija": (d.get("persistence") or {}).get("spearman_mean"),
            "range_scalp_isti_dani": {s: {f: v.get(f) for f in ("n", "ev_pct", "usd_day")}
                                      for s, v in rc.items() if isinstance(v, dict) and "n" in v},
            "demo": {k: d["demo"].get(k) for k in ("n", "open", "ev_pct", "ev_demo_pct", "pnl_usd", "ci90_lo_pct")},
            "pravi_novac": d["real_money"]["why"] or "dopušten",
            "top10": [x.get("symbol") for x in d.get("top") or []]}


def _pct(x):
    return "—" if x is None else f"{x:+.2f} %"


def card_html(sec, item, esc, owner=True):
    """The closed row "Oscilator" (owner only): today's top 10, the walk-forward per size, the demo so far and why
    real money is on / off."""
    if not owner:
        return ""
    d = summary()
    if not d.get("available") and d.get("flag") == "off":
        return ""
    dm, rm = d.get("demo") or {}, d.get("real_money") or {}
    if not d.get("available"):
        return sec("Oscilator", "još nema izračuna (prvi ~5 min nakon deploya)",
                   "<p class=mut>run_oscilator.py radi nakon deploya i noću 01-06; demo ulazi kreću čim postoji top "
                   "lista.</p>", sid="oscilator")
    wt = d.get("walk_top") or {}
    ref = wt.get("0.5@1") or {}
    meta = (f"0,5 SOL: EV {_pct(ref.get('ev_pct'))}, $/dan {ref.get('usd_day', '—')} · demo {dm.get('n', 0)} "
            f"zatvorenih · pravi novac {'uključen' if rm.get('allowed') else 'isključen'}")
    rows = []
    for key, x in wt.items():
        s, tg = key.split("@")
        txt = (f"<p>Walk-forward ({d.get('walk_days')} dana, top 10 iz dana D trguje se dan D+1): n {x.get('n', 0)} "
               f"({x.get('per_token_day', '—')} po token-danu), pogodak {x.get('hit', '—')}, EV {_pct(x.get('ev_pct'))} "
               f"({x.get('ev_usd', '—')} $), 90 % interval {x.get('ci90_ev_pct')}, $/dan {x.get('usd_day', '—')}, max "
               f"pad {x.get('max_dd_usd', '—')} $, najgori dan {x.get('worst_day_usd', '—')} $, slomljeni "
               f"{x.get('broke_share', '—')}. Uz demo naknadu EV {_pct(x.get('ev_demo_pct'))}.</p>")
        rows.append(item(f"{esc(s)} SOL, cilj {esc(tg)} $", f"EV {_pct(x.get('ev_pct'))}", txt,
                         value=str(x.get("n", 0)), sub="tradeova", iid=f"osc-{esc(s)}-{esc(tg)}"))
    top = ", ".join(esc(x.get("symbol") or x["token"][:6]) for x in d.get("top") or []) or "nema prihvatljivih"
    rc = d.get("range_scalp") or {}
    rcs = "; ".join(f"{esc(s)} SOL n {v.get('n')} EV {_pct(v.get('ev_pct'))}" for s, v in rc.items()
                    if isinstance(v, dict) and "n" in v) or "—"
    inner = (f"<p><b>Top 10 danas</b> (metrike dana {d.get('top_day')}): {top}.</p>"
             f"<p><b>Range scalp na istim token-danima:</b> {rcs}.</p>"
             f"<p><b>Demo do sada:</b> {dm.get('n', 0)} zatvorenih, {dm.get('open', 0)} otvorenih, danas "
             f"{dm.get('today', 0)}, EV {_pct(dm.get('ev_pct'))} pravim troškom (uz demo naknadu "
             f"{_pct(dm.get('ev_demo_pct'))}), PnL ${dm.get('pnl_usd', 0):,.2f}. Veličina {dm.get('size_sol')} SOL, cilj "
             f"+{dm.get('target_usd')} $ neto. Zastavica: {esc(d.get('flag'))}.</p>"
             f"<p><b>Pravi novac:</b> {esc(rm.get('why') or 'dopušten')}. Dokaz: walk-forward n {rm['proof']['n']}+, EV "
             f"i donja granica 90 % intervala > 0, $/dan > 0 na {rm['caps']['size_sol']} SOL; demo "
             f"{rm['proof']['demo_n']}+ zatvorenih s EV > 0. Stropovi: {rm['caps']['max_open']} otvorene, "
             f"{rm['caps']['max_buys_day']} dnevno, dnevni gubitak {rm['caps']['max_loss_day_sol']} SOL.</p>"
             + "".join(rows))
    return sec("Oscilator", meta, inner, sid="oscilator")
