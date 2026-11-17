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
    try:   # 15.11. (holderi/): the red badges of the active PRE-LISTING signals
        from holderi import view as hview
        badges = hview.badges_html(esc)
    except Exception:  # noqa: BLE001
        badges = ""
    inner = (badges + f"<p><b>Tablica</b> ({len(tab)} tokena, MC 5-150M, 15+ dana; prvih 30):</p><ul>{trs or '<li>još nema</li>'}</ul>"
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


# ---------- the strategy's own exit of an open position (the Autopilot page, read-only) ------------------------------
# 16.11. (owner, on /pravi-trade: SL and TP of the midcap positions showed "–", the row said "samo paper" and the
# critic "Nema TP ni trailing"): the midcap rules sell their positions themselves (veliki/live.manage: the league trade
# has no auto rule), so the page and the critic never saw the stop and the target. They are read from veliki_trades
# here, never written.

RULE_NAMES = {"intra": "midcap dnevni raspon", "range": "midcap raspon 7 d"}


def _hr_pct(x, dec=0):
    """-20.0 -> "−20 %", 11.24 -> "+11,2 %" (dec=1): the page's own way of writing a percent."""
    s = f"{abs(x):.{dec}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return ("−" if x < 0 else "+") + s.replace(".", ",") + " %"


def _hr_px(x):
    """A token price in dollars with the page's decimal comma: $0,9412, $0,01204, $0,0000612."""
    if not x:
        return "–"
    s = f"{x:.4g}" if x < 1 else f"{x:,.4f}".rstrip("0").rstrip(".")
    if "e" in s:
        s = f"{x:.10f}".rstrip("0")
    return "$" + s.replace(",", " ").replace(".", ",")


def exit_state(r):
    """The stop and the target of one open veliki_trades row, as the page shows them: percent from the (average)
    entry and the price, whose rule it is, and the stop's state in plain words:
      "stop na ulazu"            the +5 % rule (or a BTC episode above break-even) moved the stop to break-even
      "uži stop (BTC pada)"      the tight stop of a BTC episode (rule.OWNER_STOP), intraday positions
      "široki stop −20 %"        only the wide safety stop under the first entry, intraday positions
      "stop −20 %"               the 7-day rule's stop
    None for a row without an entry price."""
    entry = r.get("entry_px")
    if not entry:
        return None
    kind = "intra" if (r.get("kind") or "") == "intra" else "range"
    first = r.get("first_px") or entry
    stop, tp, be = r.get("stop_px"), r.get("tp_px"), r.get("be_px")
    out = {"kind": kind, "name": RULE_NAMES[kind], "entry_px": entry,
           "sl_px": stop, "sl_pct": round((stop / entry - 1) * 100, 2) if stop else None,
           "tp_px": tp, "tp_pct": round((tp / entry - 1) * 100, 2) if tp else None,
           "half": bool(r.get("half_px")), "trail": r.get("trail") or 0.0, "lots": r.get("lots") or 1}
    if not stop:
        out.update(state="", words="bez stopa")
    elif be and stop >= be * 0.999:
        out.update(state="be", words="stop na ulazu")
    elif kind == "intra" and r.get("tight_ts"):
        out.update(state="tight", words="uži stop (BTC pada)")
    elif kind == "intra":
        out.update(state="wide", words="široki stop " + _hr_pct((stop / first - 1) * 100))
    else:
        out.update(state="stop", words="stop " + _hr_pct((stop / first - 1) * 100))
    out["sl_text"] = f"{out['words']}" + (f" ({_hr_px(stop)})" if stop else "")
    out["tp_text"] = (f"cilj {_hr_pct(out['tp_pct'], 1)} ({_hr_px(tp)})" if tp else "bez cilja")
    out["summary"] = f"{out['words']} · {out['tp_text'].split(' (')[0]}"
    return out


def exit_sentence(x, live=True):
    """Who sells the position and by which rule, in plain words (one short paragraph under the opened row)."""
    if not x:
        return ""
    head = (f"Izlaz vodi strategija {x['name']} (program), pravim novcem" if live
            else f"Demo pozicija, bez pravog novca. Izlaz vodi strategija {x['name']} (program)")
    if x.get("half"):
        sale = (f"pola je prodano na cilju, ostatak se prodaje kad cijena padne {x['trail']:.0%} od vrha".replace("%", " %")
                + (f" ili na stopu {_hr_px(x['sl_px'])}" if x.get("sl_px") else ""))
    else:
        sale = (f"prodaje na cilju {_hr_pct(x['tp_pct'], 1)} ({_hr_px(x['tp_px'])})" if x.get("tp_px") else "bez cilja")
        if x.get("tp_px") and x.get("trail"):   # veliki/live.full_tp: half + trailing only while the whole market rises
            sale += " cijelu poziciju (kad cijelo tržište raste samo pola, ostatak prati vrh)"
        if x.get("sl_px") and x.get("state") == "be":
            sale += f" ili na stopu na ulazu ({_hr_px(x['sl_px'])})"
        elif x.get("sl_px"):
            sale += f" ili na stopu {_hr_pct(x['sl_pct'], 1)} ({_hr_px(x['sl_px'])})"
    now = {"be": "stop je na ulazu (pozicija je bila u plusu 5 % ili više), pa ne može završiti u minusu",
           "tight": "BTC pada, pa je stop uži (4 % ispod cijene u tom trenutku); kad se BTC smiri, vraća se široki",
           "wide": "BTC je miran, pa vrijedi samo široki stop; ako BTC padne 1,5 % u 4 h, stop ide 4 % ispod cijene, "
                   "a na +5 % neto ide na ulaz",
           "stop": "na +5 % neto stop ide na ulaz"}.get(x.get("state"), "")
    return (f"{head}: {sale}. " + (f"Sada: {now}. " if now else "")
            + "Razine postavlja pravilo strategije; ovdje se samo čitaju.")


def open_exits(trade_ids, path=None):
    """{league trade id: exit_state} of the open midcap positions behind the listed league trades (the first lot's
    id and the DCA lot's id both lead to their row). league.db read-only; {} when it cannot be read."""
    import os
    import sqlite3
    ids = [int(x) for x in trade_ids or () if x]
    if not ids:
        return {}
    if path is None:
        from league import store as lstore
        path = lstore.DB
    if not os.path.exists(path):
        return {}
    out = {}
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return {}
    try:
        con.row_factory = sqlite3.Row
        q = ",".join("?" * len(ids))
        for r in con.execute(f"SELECT * FROM veliki_trades WHERE status='open' AND (trade_id IN ({q}) OR "
                             f"dca_trade_id IN ({q}))", ids + ids):
            d = dict(r)
            x = exit_state(d)
            if not x:
                continue
            for k in (d.get("trade_id"), d.get("dca_trade_id")):
                if k in ids:
                    out[k] = x
    except sqlite3.Error:   # no veliki_trades (the strategy never ran here) or an older schema
        return out
    finally:
        con.close()
    return out
