"""What the page (card "Veliki tokeni — range" under Ostalo), the MCP tool get_big_ranges and the OpenAI critic read."""
import time

_C = {"ts": 0.0, "v": None}


def summary(zones=True):
    """{available, run_ts, flag, list, zones (where the price is now), walk-forward per variant and size, costs, demo,
    real_money} - no addresses beyond the token mints of the list."""
    from veliki import gate, live, store
    if zones and _C["v"] is not None and time.time() - _C["ts"] < 60:
        return _C["v"]
    ts, data = store.latest()
    d = data or {}
    lst = store.the_list() or {}
    why = gate.real_refusal()
    ok_wf, why_wf, x_wf = gate.wf_proof(size_sol=gate.real_caps()["size_sol"])
    btc = live.btc_state()
    out = {"available": data is not None, "run_ts": ts, "flag": live.mode(), "list_ts": lst.get("ts"),
           "list": [{k: x.get(k) for k in ("symbol", "mint", "mcap", "liq", "liq_total", "vol24", "age_d", "seed", "how")}
                    for x in lst.get("tokens") or []],
           "seeds": lst.get("seeds"), "zones": live.zones_now() if zones else None,
           "btc": {"known": btc["known"], "crash": btc["crash"], "state": btc.get("state"), "why": btc.get("why"),
                   "last_crash_end": btc["last_end"]},
           "days": d.get("days"), "crash_periods": d.get("crash_periods"), "costs_pct": d.get("costs"),
           "walk": {v: {s: {f: x.get(f) for f in ("n", "per_day", "hit", "ev_pct", "ev_usd", "ci90_ev_pct", "ci95_day_pct",
                                                   "ev_2x_cost_pct", "loto_min_pct", "loto_min_without", "profit_factor",
                                                   "worst5_pct", "mae_med_pct", "mfe_med_pct", "hold_med_h", "usd_day",
                                                   "max_dd_usd", "worst_trade", "token_days", "crash_overlap_n")}
                        for s, x in sizes.items() if isinstance(x, dict)}
                    for v, sizes in (d.get("variants") or {}).items()},
           "live_rule": d.get("live_rule") or store.live_rule(), "demo": live.demo_stats(),
           "real_money": {"switch_on": gate.switch_on(), "allowed": why is None, "why": why, "proof_mode": gate.proof_mode(),
                          "walk_forward_ok": ok_wf, "walk_forward_why": why_wf, "walk_forward_at_real_size": x_wf,
                          "proof": gate.PROOF, "caps": gate.real_caps()}}
    ref = ((d.get("variants") or {}).get("dno") or {}).get("0.5") or {}
    out["detail_0_5"] = {k: ref.get(k) for k in ("per_token", "by_regime", "folds", "variants_holdout", "by_age",
                                                 "dead_n", "grid_top")}
    out["stops_0_5"] = d.get("stops")
    out["table"] = d.get("table") or []
    out["out_of_range"] = d.get("out_of_range") or []
    out["dead_included"] = d.get("dead_included")
    if zones:
        _C.update(ts=time.time(), v=out)
    return out


def mcp(args=None):
    """MCP get_big_ranges: summary(); full=false leaves out the per-token / per-fold detail."""
    args = args or {}
    try:
        d = dict(summary())
    except Exception as e:  # noqa: BLE001
        return {"error": f"veliki nije čitljiv ({type(e).__name__})"}
    if not args.get("full"):
        d.pop("detail_0_5", None)
        d["list"] = [{k: x.get(k) for k in ("symbol", "mint", "mcap", "liq_total")} for x in d.get("list") or []]
    return d


def critic_summary():
    """A small block for the OpenAI critic: the holdout per size (rule without BTC crashes, and with them), the demo,
    the real-money decision, the list."""
    d = summary(zones=False)
    if not d.get("available") and not d.get("list"):
        return None
    keep = ("n", "per_day", "hit", "ev_pct", "ci95_day_pct", "ev_2x_cost_pct", "loto_min_pct", "usd_day", "max_dd_usd")
    return {"holdout_po_btc_pravilu": {v: {s: {f: x.get(f) for f in keep} for s, x in sizes.items()}
                                       for v, sizes in (d.get("walk") or {}).items()},
            "btc_stanje": (d.get("btc") or {}).get("state"),
            "tablica_top10": [{k: x.get(k) for k in ("symbol", "cat", "mcap", "pers90", "corr_d", "hit15")}
                              for x in (d.get("table") or [])[:10]],
            "dana": d.get("days"), "pravilo": (d.get("live_rule") or {}).get("key"),
            "demo": {k: d["demo"].get(k) for k in ("n", "open", "ev_pct", "pnl_usd", "ci90_lo_pct")},
            "btc_pada_sada": d["btc"]["crash"], "pravi_novac": d["real_money"]["why"] or "dopušten",
            "lista": [x.get("symbol") for x in d.get("list") or []]}


def _pct(x):
    return "—" if x is None else f"{x:+.2f} %"


def card_html(sec, item, esc, owner=True):
    """The closed row "Veliki tokeni — range" (owner only): the list with zones and where the price is now, the
    backtest per size (without / with BTC crashes), the demo so far, the switch."""
    if not owner:
        return ""
    d = summary()
    if not d.get("list") and not d.get("available") and d.get("flag") == "off":
        return ""
    dm, rm = d.get("demo") or {}, d.get("real_money") or {}
    wb = (d.get("walk") or {}).get("dno") or {}
    ref = wb.get("0.5") or {}
    meta = (f"{len(d.get('list') or [])} tokena · 0,5 SOL holdout: EV {_pct(ref.get('ev_pct'))}, $/dan "
            f"{ref.get('usd_day', '—')} · demo {dm.get('n', 0)} zatvorenih · pravi novac "
            f"{'uključen' if rm.get('allowed') else 'isključen'}")
    zr = []
    for z in d.get("zones") or []:
        if z.get("zone_ok"):
            txt = (f"podrška {z['s_lo']:.6g}–{z['s_hi']:.6g}, otpor {z['r_lo']:.6g}–{z['r_hi']:.6g} (širina "
                   f"{(z.get('width') or 0) * 100:.1f} %){', novi raspon nakon pada BTC-a' if z.get('fresh') else ''}; "
                   f"cijena {z.get('price') or 0:.6g} na {z.get('pos_pct')} % raspona")
        else:
            txt = f"nema raspona ({esc(z.get('why') or '—')}); cijena {z.get('price') or 0:.6g}"
        zr.append(f"<li><b>{esc(z.get('symbol') or z['mint'][:6])}</b>: {txt}</li>")
    rows = []
    for v, sizes in (d.get("walk") or {}).items():
        for s, x in sizes.items():
            if "n" not in x or x.get("n") is None:
                continue
            ci = x.get("ci90_ev_pct")
            txt = (f"<p>Holdout ({d.get('days')} dana, konfiguracija birana na starijim danima): n {x.get('n')} "
                   f"({x.get('per_day')} dnevno), pogodak {x.get('hit')}, EV {_pct(x.get('ev_pct'))} ({x.get('ev_usd')} $), "
                   f"90 % interval {ci}, $/dan {x.get('usd_day')}, max pad {x.get('max_dd_usd')} $, najgori "
                   f"{(x.get('worst_trade') or {}).get('ret_pct', '—')} %.</p>")
            rows.append(item(f"{esc(s)} SOL, {esc(v.replace('_', ' '))} BTC-a", f"EV {_pct(x.get('ev_pct'))}", txt,
                             value=str(x.get("n", 0)), sub="tradeova", iid=f"vel-{esc(v)}-{esc(s)}"))
    lr = d.get("live_rule") or {}
    tab = d.get("table") or []
    trs = "".join(f"<li><b>{esc(str(x.get('symbol')))}</b> {esc(str(x.get('cat')))}: MC ${(x.get('mcap') or 0) / 1e6:,.1f}M, "
                  f"{esc(str(x.get('age_bucket')))}, stalnost 90 d {x.get('pers90')}, korelacija BTC {x.get('corr_d')}, "
                  f"odbijanja +15 % {x.get('hit15')}</li>" for x in tab[:30])
    inner = (f"<p><b>Tablica</b> ({len(tab)} tokena, MC 5-150M, 15+ dana; prvih 30):</p><ul>{trs or '<li>još nema</li>'}</ul>"
             f"<p><b>Zone sada</b>:</p><ul>{''.join(zr[:40]) or '<li>još nema</li>'}</ul>"
             f"<p><b>BTC:</b> {esc(str((d.get('btc') or {}).get('state') or '?'))} — {esc(str((d.get('btc') or {}).get('why') or ''))}"
             f"{'' if (d.get('btc') or {}).get('known') else ', cijena po satu nepoznata'}.</p>"
             f"<p><b>Pravilo za demo:</b> {esc(lr.get('key') or 'zadano tp5%/sl5/24h/3d')}.</p>"
             f"<p><b>Demo do sada:</b> {dm.get('n', 0)} zatvorenih, {dm.get('open', 0)} otvorenih, danas "
             f"{dm.get('today', 0)}, EV {_pct(dm.get('ev_pct'))} pravim troškom, PnL ${dm.get('pnl_usd', 0):,.2f}; "
             f"{dm.get('size_sol')} SOL. Zastavica: {esc(d.get('flag'))}.</p>"
             f"<p><b>Pravi novac</b> (prekidač pravi_novac_veliki): {esc(rm.get('why') or 'dopušten')}. Dokaz: holdout na "
             f"{rm['caps']['size_sol']} SOL n {rm['proof']['n']}+, EV > 0 i donja granica 90 % intervala > 0. Stropovi: "
             f"{rm['caps']['size_sol']} SOL, {rm['caps']['max_open']} otvorenih, dnevni gubitak "
             f"{rm['caps']['max_loss_day_sol']} SOL.</p>" + "".join(rows))
    return sec("Veliki tokeni — range", meta, inner, sid="veliki")


def midcaps(args=None):
    """MCP get_midcaps (Grok's view): the ranked table with categories and metrics, the zones now, BTC's state, Grok's
    own archived verdicts per token, the out-of-range examples; limit (default 60)."""
    args = args or {}
    try:
        d = summary()
    except Exception as e:  # noqa: BLE001
        return {"error": f"veliki nije čitljiv ({type(e).__name__})"}
    try:
        lim = max(1, min(200, int(args.get("limit") or 60)))
    except (TypeError, ValueError):
        lim = 60
    from veliki import store
    zones = {z["mint"]: z for z in d.get("zones") or []}
    gl = {}
    con = store.ro()
    if con is not None:
        try:
            gl = store.grok_latest(con, {x["mint"] for x in d.get("table") or []})
        except Exception:  # noqa: BLE001
            gl = {}
        finally:
            con.close()
    rows = []
    for x in (d.get("table") or [])[:lim]:
        z = zones.get(x["mint"]) or {}
        rows.append({**{k: x.get(k) for k in ("symbol", "mint", "cat", "mcap", "age_d", "age_bucket", "pers30", "pers90",
                                               "cv30", "beta_d", "corr_d", "beta_4h", "corr_4h", "dd_ath", "btc_up_24h",
                                               "btc_up_72h", "bounce_n", "hit15", "med_up7", "med_dn7", "score")},
                     "zone": {k: z.get(k) for k in ("zone_ok", "why", "s_lo", "s_hi", "r_lo", "r_hi", "pos_pct", "price")},
                     "grok_last": gl.get(x["mint"])})
    return {"ts": d.get("run_ts"), "btc": d.get("btc"), "categories": {"A": "stari + stalni volumen + prati BTC",
                                                                       "B": "srednji ili stalan volumen",
                                                                       "C": "mlad ili nestalan volumen"},
            "tokens": rows, "out_of_range": d.get("out_of_range"), "live_rule": d.get("live_rule"),
            "how_to_help": ("Per token: search X for $SYMBOL and the mint (posts 15 / 60 min, organic authors, known "
                            "callers, large accounts), then submit_signal_opinion {token, verdict kupi | preskoči, "
                            "confidence, interpretation}. Your verdicts are archived with their time (veliki.db "
                            "grok_sig) and compared later with / without you; the demo account trades the rule, real "
                            "money only by the owner's switch.")}
