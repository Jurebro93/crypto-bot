"""Grokove pozicije na vrhu Autopilota (13.11., Jure: "ako su pozicije groka na vrhu, želim onda na vrhu vidjeti
pozicije I da budu skupljene isto koji moje pozicije kad kupim. Znači, ulazni market cap, plan za izlaz, ove osnovne
informacije što stanu jedan redak na mobitelu I onda kad klikom na to se otvori kao dolje padajući izbornik sa
proširenim informacijama za svaku poziciju, sa obrazloženjem I ovo što Grok već dostavio. Plus informacije o
MemeSonara koje potvrđuju Grokovu tezu.").

One collapsed row per open Grok position (autotrade or a request the owner approved; ui/apterm.positions_data rows
with "grok" set): the token (a tap loads its chart: data-sel), live / paper, the entry MC, PnL (ap.js keeps it live
through data-key) and the exit in a few words ("SL −12 % · TP1 +15 % · BE nakon TP1"). A tap on the row opens under it:
  Pozicija              entry / now MC, size, PnL in SOL, bought at (Zagreb time), rounds today, the exit in full
  Grokova teza          the reason Grok sent with each buy (execute_trade), his EV gate numbers (p_tp, strategy, EV)
  Što je Grok dostavio  his X feature rows, signal opinions, predictions (events.db grok_predictions), the exit plan in
                        force and who set it, his review of the position (last 24 h)
  Što MemeSonar vidi    the bot's own data on the token, each marked potvrđuje / proturječi / neutralno: rug check
                        (topcheck) and the rug filter, liquidity / MC / 1 h volume, buyers vs sellers, the range
                        (rangedca), the newest fast_check, callers and followed wallets of the last hour
14.11. (Jure: "grokove sve pozicije ubaci dolje u pozicije samo uz tag"): the terminal has no Grok card at the top any
more; detail() is what Grok's position shows inside its own row of Pozicije (ui/apterm.positions_html); row_html and
block_html stay for the old page (?stari=1).
Only data the bot already stores is read (no new API call, no paid request); MemeSonar's part is cached FACTS_TTL_S
per token, so a page view reads each database at most once in that time. Every part is behind its own try: a missing
database leaves its line out, never the row.
"""
import json
import threading
import time

from trade import settings
from ui import redak
from ui.html import esc

FACTS_TTL_S = 30
DAY_S = 86400
TONES = {"za": ("potvrđuje", "up"), "protiv": ("proturječi", "dn"), "neutral": ("neutralno", "")}
BUY_SHARE_ZA, BUY_SHARE_PROTIV = 0.55, 0.45   # = the token pop-up's "kupci / prodavači prevladavaju" (pravitrade)
_LOCK = threading.Lock()
_FACTS = {}   # token -> (ts, facts)


def _zg(ts, now=None):
    from ui import pravitrade
    return pravitrade.zg_time(ts, now)


def _handle(h):
    h = str(h or "")
    if h.startswith("tg:"):
        return h[3:]
    if h.startswith("w:"):
        return "novčanik " + h[2:]
    return "@" + h.lstrip("@")


# ---------- the exit in a few words -----------------------------------------------------------------------------------

def exit_short(p, plan=None):
    """"SL −12 % · TP1 +15 % · trailing 10 % · BE nakon TP1": the exit plan in force when the position has one (the
    plan Grok or the buy set, league/exitplan), else the position's own TP / SL."""
    from league import exitplan as xp
    pl = (plan or {}).get("plan") if plan else None
    bits = []
    if pl:
        st = pl.get("stop")
        if st:
            bits.append("SL " + (xp.pct_words(st["v"]) if st["kind"] == "pct" else "MC " + xp.mc_words(st["v"])))
        tps = pl.get("take_profits") or []
        for i, tp in enumerate(tps[:2]):
            lab = "TP" if len(tps) == 1 else f"TP{i + 1}"
            bits.append(f"{lab} " + (xp.pct_words(tp["v"]) if tp["kind"] == "pct" else "MC " + xp.mc_words(tp["v"])))
        tr = pl.get("trailing")
        if tr:
            bits.append(f"trailing {xp.pct_words(tr['trail_pct'], sign=False)}")
        if pl.get("breakeven_after_tp1"):
            bits.append("BE nakon TP1")
        ts_min = (pl.get("time_stop") or {}).get("after_min") or pl.get("time_stop_min")
        if ts_min:
            bits.append(f"time stop {ts_min:g} min")
    else:
        if p.get("sl_pct") is not None:
            bits.append("SL " + redak.pct(p["sl_pct"], 0))
        if p.get("tp_pct") is not None:
            bits.append("TP " + redak.pct(p["tp_pct"], 0))
        if p.get("trail"):
            bits.append(f'trailing {p["trail"].get("trail_pct")} %')
        if p.get("smart"):
            bits.append("Smart sell")
    return " · ".join(bits) or "bez TP/SL-a"


# ---------- what Grok sent ----------------------------------------------------------------------------------------------

def _lids(tcon, ids):
    if not ids:
        return set()
    q = ",".join("?" * len(ids))
    return {r[0] for r in tcon.execute(f"SELECT league_id FROM positions WHERE id IN ({q}) AND league_id IS NOT NULL",
                                       list(ids))}


def thesis(tcon, p):
    """Grok's buys of this position, newest first: [{"ts", "amount", "reason", "ev", "override", "how"}]: the
    autotrade log's executed buys of its lots (ui/grokauto), else the approved requests of the token."""
    from ui import grokauto
    lids = _lids(tcon, p.get("ids") or [])
    tok = p["token"]
    out = []
    for r in grokauto.log_rows(tcon, 300):
        if r.get("token") != tok or r.get("side") != "buy" or r.get("status") != "executed":
            continue
        if lids and r.get("league_id") and r["league_id"] not in lids:
            continue
        out.append({"ts": r.get("ts"), "amount": r.get("amount"), "reason": r.get("reason") or "",
                    "ev": r.get("ev_gate"), "override": r.get("override"), "how": "Grok auto"})
    if not out:
        for r in settings.raw(tcon).get("mcp_requests") or []:
            if r.get("token") == tok and r.get("side") == "buy" and r.get("status") == "approved":
                out.append({"ts": r.get("ts"), "amount": r.get("amount"), "reason": r.get("reason") or "",
                            "ev": ({"p_tp": r.get("p_tp"), "strategy": r.get("strategy")} if r.get("p_tp") is not None
                                   else None), "override": None, "how": "odobren zahtjev"})
        out.sort(key=lambda x: -(x.get("ts") or 0))
    return out[:6]


def delivered(tcon, lcon, p, now):
    """[(kind, ts, text)] of what Grok sent on the token in the last DAY_S, newest first: X features, signal
    opinions, predictions, the exit plan in force (and who set it) and his review of the position."""
    tok = p["token"]
    out = []
    try:
        from scan import xmom
        from ui import xfeat
        for r in xfeat.read(tok, "token", since=int(now - DAY_S), limit=3)["rows"]:
            f = r.get("features") or {}
            g = xmom._grok(r.get("ts_asof"), json.dumps(f)) or {}
            bits = []
            if g.get("known_callers"):
                bits.append("pozivatelji " + ", ".join(_handle(h) for h in g["known_callers"][:4]))
            if g.get("large_accounts"):
                bits.append("veliki računi " + ", ".join(_handle(h) for h in g["large_accounts"][:3]))
            if g.get("x_momentum_score") is not None:
                bits.append(f"zamah {redak.num(g['x_momentum_score'], 2, sign=True)}")
            if g.get("posts60") is not None:
                bits.append(f"{g['posts60']} objava u 60 min")
            if g.get("authors15") is not None:
                bits.append(f"{g['authors15']} autora u 15 min")
            if f.get("note"):
                bits.append(str(f["note"])[:200])
            out.append(("X značajke", r.get("ts_observed") or r.get("ts_asof"), " · ".join(bits) or "bez brojki"))
    except Exception:  # noqa: BLE001 - no xfeat.db: nothing to list
        pass
    try:
        from ui import assistnotes
        cols = ", ".join(assistnotes.COLS)
        ids = [int(i) for i in p.get("ids") or []]
        q = ",".join("?" * len(ids)) or "NULL"
        for r in tcon.execute(f"SELECT {cols} FROM assistant_notes WHERE ts >= ? AND ((kind='signal_opinion' AND token=?) "
                              f"OR (kind='trade_review' AND position_id IN ({q}))) ORDER BY id DESC LIMIT 4",
                              (int(now - DAY_S), tok, *ids)):
            d = assistnotes._row(r)
            conf = f" ({d['confidence'] * 100:.0f} %)" if d.get("confidence") is not None else ""
            kind = "mišljenje" if d["kind"] == "signal_opinion" else "recenzija pozicije"
            out.append((kind, d.get("ts"), f"{d.get('verdict') or ''}{conf}: {d.get('interpretation') or ''}".strip(": ")))
    except Exception:  # noqa: BLE001
        pass
    try:
        from events import store as estore
        econ = estore.ro()
        if econ is not None:
            try:
                for ts, strat, ptp, tp, sl, verdict, reasons in econ.execute(
                        "SELECT ts, strategy, p_tp, tp_pct, sl_pct, verdict, reasons FROM grok_predictions WHERE token=? "
                        "AND ts >= ? ORDER BY ts DESC LIMIT 2", (tok, int(now - DAY_S))):
                    bits = [f"p_tp {redak.num(ptp, 2)}" + (f" (TP {redak.pct(tp, 0)} prije SL −{redak.num(sl, 0)} %)"
                                                          if tp is not None and sl is not None else "")
                            if ptp is not None else "", f"strategija {strat}" if strat else "", verdict or "",
                            str(reasons or "")[:200]]
                    out.append(("predviđanje", ts, " · ".join(b for b in bits if b)))
            finally:
                econ.close()
    except Exception:  # noqa: BLE001 - no events.db / no grok_predictions yet
        pass
    try:
        from league import exitplan as xp
        if lcon is not None:
            pl = xp.active(lcon, tok, ro=True)
            if pl and str(pl.get("client") or "").startswith("mcp"):   # only a plan Grok set himself (set_exit_plan)
                out.append(("plan izlaza", pl.get("created_ts"), f"{xp.describe(pl['plan'])} · postavio Grok (set_exit_plan)"
                            + (f" · {pl['reason']}" if pl.get("reason") else "")))
    except Exception:  # noqa: BLE001
        pass
    out.sort(key=lambda x: -(x[1] or 0))
    return out


# ---------- what MemeSonar sees -----------------------------------------------------------------------------------------

def _rug_facts(token, tables):
    out = []
    tc, rug = tables or ({}, {})
    t = (tc or {}).get(token) or {}
    s = t.get("safety") if isinstance(t.get("safety"), dict) else {}
    v = t.get("verdict")
    if v == "prolazi":
        hold = ((s.get("checks") or {}).get("holderi") or [None, ""])[1]
        out.append(("za", "rug provjera (topcheck)", "prolazi" + (f": {hold}" if hold else "")))
    elif v == "oprez":
        out.append(("neutral", "rug provjera (topcheck)", "oprez: " + "; ".join((s.get("warns") or [])[:2])))
    elif v == "pao":
        out.append(("protiv", "rug provjera (topcheck)", "pala: " + "; ".join((s.get("fails") or [])[:2])))
    else:
        out.append(("neutral", "rug provjera (topcheck)", "nije rađena za ovaj token"))
    r = (rug or {}).get(token) or {}
    rv = r.get("verdict")
    if rv:
        sc = f", ocjena {float(r['score']):.0f}/100" if r.get("score") is not None else ""
        tone = "za" if rv == "PROLAZI" else "protiv" if rv in ("VISOK RIZIK", "ODBAČEN") else "neutral"
        out.append((tone, "rug filter", f"{rv.lower()}{sc}"))
    return out


def _market_facts(lv):
    from league import copy
    from trade import cost
    if not lv or not lv.get("mcap"):
        return [("neutral", "tržište", "nema svježe cijene (DexScreener se još nije javio za ovaj token)")]
    out = []
    liq, mcap, vol = float(lv.get("liq") or 0), float(lv["mcap"]), float(lv.get("vol_h1") or 0)
    floor = max(copy.CFG.get("min_liq", 0), cost.LIQ_HARD_MIN)
    share = liq / mcap if mcap else 0
    words = (f"likvidnost {redak.usd(liq)} ({redak.pct(share, 0, sign=False, frac=True)} MC-a) · MC {redak.usd(mcap)} · "
             f"promet sata {redak.usd(vol)}")
    if liq < floor or share < copy.CFG.get("min_liq_mcap", 0.03):
        out.append(("protiv", "likvidnost", words + ": ispod granice za ulaz"))
    elif vol < cost.VOL_FLOOR:
        out.append(("protiv", "promet", words + f": promet ispod {redak.usd(cost.VOL_FLOOR)} u satu"))
    else:
        out.append(("neutral", "likvidnost i promet", words))
    b, s_ = lv.get("buys_m5"), lv.get("sells_m5")
    win = "5 min"
    if b is None or s_ is None or not (b + s_):
        b, tx, win = lv.get("buys_h1"), lv.get("txns_h1"), "sat"
        s_ = (tx - b) if b is not None and tx else None
    if b is not None and s_ is not None and b + s_:
        sh = b / (b + s_)
        txt = f"{b} kupnji i {s_} prodaja ({win}), kupci {redak.pct(sh, 0, sign=False, frac=True)}"
        tone = "za" if sh >= BUY_SHARE_ZA else "protiv" if sh <= BUY_SHARE_PROTIV else "neutral"
        out.append((tone, "kupci / prodavači", txt))
    return out


def _range_fact(token, now):
    from rangedca import data, rules, view
    r = data.read_ranges(tokens=[token]).get(token)
    if not r or r.get("pos_pct") is None:
        return []
    pos, sc = float(r["pos_pct"]), r.get("score")
    sc_txt = f", ocjena raspona {redak.num(sc, 2)}" if sc is not None else ""
    age = f", izračun prije {max(0, int((now - (r.get('ts') or now)) // 60))} min" if r.get("ts") else ""
    if view.is_breakout(r):
        return [("neutral", "raspon (range)", f"cijena je iznad raspona ({redak.num(pos, 0)} %): breakout{sc_txt}{age}")]
    if pos <= rules.RULES["entry_bottom"] * 100:
        return [("za", "raspon (range)", f"cijena je pri dnu raspona ({redak.num(pos, 0)} % od dna){sc_txt}{age}")]
    if pos >= 85:
        return [("protiv", "raspon (range)", f"cijena je pri vrhu raspona ({redak.num(pos, 0)} %): tu range prodaje"
                                             f"{sc_txt}{age}")]
    return [("neutral", "raspon (range)", f"sredina raspona ({redak.num(pos, 0)} % od dna){sc_txt}{age}")]


def _fast_fact(token, now):
    from fast import store as fstore
    con = fstore.ro()
    if con is None:
        return []
    try:
        got = fstore.read(con, "token=? AND sig_ts >= ?", (token, int(now - DAY_S)), order="id DESC", limit=1)
    finally:
        con.close()
    if not got or not got[0].get("decision"):
        return []
    r = got[0]
    d = r["decision"]
    tone = "za" if d.startswith("BUY") else "protiv" if d == "SKIP" else "neutral"
    word = {"BUY_PAPER": "kupi (paper)", "BUY_LIVE": "kupi", "SKIP": "preskoči", "CHECK_FAILED": "nije uspio"}.get(d, d)
    when = f" (prije {max(0, int((now - (r.get('sig_ts') or now)) // 60))} min)" if r.get("sig_ts") else ""
    return [(tone, "fast_check", f"{word}{when}" + (f": {r['reason']}" if r.get("reason") else ""))]


def _social_facts(token, now):
    from ui import pravitrade
    ev = [e for e in pravitrade._events_hour(now) if e[0] == token]
    callers = sorted({e[3] for e in ev if e[4] == "call" and e[2] != "chain"})
    buys = {e[3] for e in ev if e[2] == "chain" and e[4] == "buy"}
    sells = {e[3] for e in ev if e[2] == "chain" and e[4] == "sell"}
    out = []
    if callers:
        out.append(("za", "pozivatelji", f"zvali u zadnjih 60 min: {', '.join(_handle(h) for h in callers[:5])}"
                                         + (f" (+{len(callers) - 5})" if len(callers) > 5 else "")))
    else:
        out.append(("neutral", "pozivatelji", "nitko ga nije zvao u zadnjih 60 min"))
    if buys or sells:
        tone = "za" if len(buys) > len(sells) else "protiv" if len(sells) > len(buys) else "neutral"
        out.append((tone, "praćeni novčanici", f"{len(buys)} kupilo, {len(sells)} prodalo u zadnjih 60 min"))
    return out


def facts(token, now=None, live=None, tables=None):
    """[(tone, what, text)] of MemeSonar's own data on the token (tone za | protiv | neutral), cached FACTS_TTL_S."""
    now = now or time.time()
    with _LOCK:
        hit = _FACTS.get(token)
    if hit and now - hit[0] < FACTS_TTL_S:
        return hit[1]
    out = []
    if tables is None:
        try:
            from scan import filters
            tables = filters.rug_tables()
        except Exception:  # noqa: BLE001
            tables = ({}, {})
    parts = ((_rug_facts, (token, tables)), (_market_facts, (live,)), (_range_fact, (token, now)),
             (_fast_fact, (token, now)), (_social_facts, (token, now)))
    for fn, args in parts:
        try:
            out += fn(*args)
        except Exception as e:  # noqa: BLE001 - a missing database leaves its line out
            print(f"grok pozicije: {fn.__name__} {token[:6]}: {type(e).__name__}", flush=True)
    with _LOCK:
        _FACTS[token] = (now, out)
        if len(_FACTS) > 64:
            for k in sorted(_FACTS, key=lambda k: _FACTS[k][0])[:32]:
                _FACTS.pop(k, None)
    return out


# ---------- HTML ---------------------------------------------------------------------------------------------------------

def _live_of(tok, now):
    try:
        from ui import apterm
        return apterm._peek_live([tok], now)[0].get(tok) or {}
    except Exception:  # noqa: BLE001
        return {}


def detail(tcon, lcon, p, now, rounds=None, round_cap=None, tables=None):
    """What one Grok position says beyond the row of Pozicije (14.11., Jure: "grokove sve pozicije ubaci dolje u
    pozicije samo uz tag"; ui/apterm puts it into the position's expanded row): {"exit": the exit in a few words,
    "plan": the exit plan in force or None, "cells": [(label, html, cls)] Kupljeno / Način / Krugovi danas, "html":
    Izlaz + Grokova teza + Što je Grok dostavio + Što MemeSonar vidi}."""
    from league import exitplan as xp
    from ui import apterm
    tok = p["token"]
    plan = None
    if lcon is not None:
        try:
            plan = xp.active(lcon, tok, ro=True)
        except Exception:  # noqa: BLE001
            plan = None
    xs = exit_short(p, plan)
    kind = "Grok auto" if p.get("grok") == "auto" else "odobren Grokov zahtjev"
    cells = [("Kupljeno", esc(_zg(p.get("opened_ts"), now)), "n"),
             ("Način", ("uživo (pravi novac)" if not p["paper"] else "paper (bez novca)") + f" · {kind}", "t")]
    if rounds:
        cells.append(("Krugovi danas", f'{rounds["rounds_today"]} od {round_cap}'
                      + (f' · stopom {rounds["stop_outs_today"]}' if rounds.get("stop_outs_today") else ""), "n"))
    own = []
    if p.get("sl_mc"):
        own.append(f'SL {apterm._pct(p["sl_pct"], 0)} ({apterm.mc(p["sl_mc"])})')
    if p.get("tp_mc"):
        own.append(f'TP {apterm._pct(p["tp_pct"], 0)} ({apterm.mc(p["tp_mc"])})')
    exit_ = (f'<p class=apx-gpx><b>Izlaz:</b> {esc(xs)}'
             + (f' <span class=apx-mut>· TP/SL pozicije: {esc(" · ".join(own))}</span>' if own and plan else "") + '</p>')
    # Grokova teza
    th = []
    for b in thesis(tcon, p):
        ev = b.get("ev") or {}
        nums = " · ".join(x for x in (
            f"p_tp {redak.num(ev['p_tp'], 2)}" if ev.get("p_tp") is not None else "",
            f"strategija {ev['strategy']}" if ev.get("strategy") else "",
            f"EV {redak.pct(ev['ev'] * 100, 1)}" if ev.get("ev") is not None else "") if x)
        ov = (f'<small>nadjačao rug ocjenu ({esc(b["override"].get("rug_risk") or "")}) svježim dokazom</small>'
              if b.get("override") else "")
        th.append(f'<li><span class=apx-mut>{esc(_zg(b.get("ts"), now))} · {esc(b["how"])} · '
                  f'{redak.num(b.get("amount"), 3)} SOL</span> <span translate=no>{esc(b["reason"] or "bez razloga")}</span>'
                  + (f'<small>{esc(nums)}</small>' if nums else "") + ov + '</li>')
    teza = (f'<h4>Grokova teza</h4><ul class=apx-gl>{"".join(th)}</ul>' if th
            else '<h4>Grokova teza</h4><p class=apx-mut>Uz kupnju nije zapisan razlog.</p>')
    # Što je Grok dostavio
    # Grok's own words stay as he wrote them (translate=no); the plan's line is the page's own Croatian
    dl = "".join(f'<li><b>{esc(k)}</b> <span class=apx-mut>{esc(_zg(ts, now))}</span> · '
                 + (esc(t) if k == "plan izlaza" else f'<span translate=no>{esc(t)}</span>') + '</li>'
                 for k, ts, t in delivered(tcon, lcon, p, now))
    dost = ('<h4>Što je Grok dostavio <span class=apx-mut>(24 h)</span></h4>'
            + (f'<ul class=apx-gl>{dl}</ul>' if dl else
               '<p class=apx-mut>Osim razloga uz kupnju ništa: ni X značajke, ni mišljenje, ni predviđanje, ni plan '
               'izlaza.</p>'))
    # Što MemeSonar vidi
    lv = _live_of(tok, now) or ({"mcap": p["mc_now"]} if p.get("mc_now") else {})
    fs = facts(tok, now, lv, tables)
    n = {k: sum(1 for t, _w, _x in fs if t == k) for k in TONES}
    fl = "".join(f'<li class="apx-gf {TONES[t][1]}"><b>{TONES[t][0]}</b> · {esc(w)}: {esc(x)}</li>' for t, w, x in fs)
    vidi = (f'<h4>Što MemeSonar vidi <span class=apx-mut>· {n["za"]} potvrđuje · {n["protiv"]} proturječi · '
            f'{n["neutral"]} neutralno</span></h4><ul class="apx-gl apx-gfl">{fl}</ul>')
    return {"exit": xs, "plan": plan, "cells": cells, "html": f'{exit_}{teza}{dost}{vidi}'}


def row_html(tcon, lcon, p, now, rounds=None, round_cap=None, tables=None):
    """One Grok position: the collapsed line (summary) and, under it, Pozicija / Grokova teza / Što je Grok dostavio /
    Što MemeSonar vidi (the old page's card; the terminal lists Grok's positions in Pozicije since 14.11.)."""
    from ui import apterm
    tok = p["token"]
    g = detail(tcon, lcon, p, now, rounds, round_cap, tables)
    badge = apterm.BADGE_PAPER if p["paper"] else apterm.BADGE_LIVE
    sol = redak.sol(p["pnl_sol"], 4, sign=True) if p.get("pnl_sol") is not None else ""
    pnl = (f'{apterm._pct(p["pnl_pct"])}<small>{sol}</small>' if p.get("pnl_pct") is not None
           else '<span class=apx-sk>čekam cijenu</span>')
    summ = (f'<summary class=apx-gps><span class=apx-gps-t>{apterm._sel_btn(tok, p["sym"])}{badge}</span>'
            f'<span class="n apx-gps-mc" title="Ulazni MC">ulaz {apterm.mc(p["avg_mc"])}</span>'
            f'<span class="n apx-pnl {apterm._tone(p.get("pnl_pct"))}" data-f=pnl>{pnl}</span>'
            f'<span class=apx-gps-x>{esc(g["exit"])}</span></summary>')
    cells = [("Ulaz (MC)", apterm.mc(p["avg_mc"]), "n"),
             ("Sada (MC)", f'<span data-f=mc>{apterm.mc(p["mc_now"])}</span>', "n"),
             ("PnL", f'<span class="n apx-pnl {apterm._tone(p.get("pnl_pct"))}" data-f=pnl>{pnl}</span>', "n"),
             ("Veličina", redak.sol(p["sol_in"], 3) + (f' · {p["n_lots"]} ulaza' if p.get("n_lots", 1) > 1 else ""), "n"),
             *g["cells"]]
    grid = "".join(f'<div><span>{k}</span><b class={c}>{v}</b></div>' for k, v, c in cells)
    act = (f'<button type=button class=apx-b data-edit="ed-{p["pid"]}" data-goto="poz-{p["pid"]}">Uredi SL-TP ili prodaj '
           '(u Pozicijama)</button>')
    html = g["html"]
    i = html.index("</p>") + 4   # the plan's line right under "Izlaz:", as before
    body = (f'<div class=apx-gpd><div class=apx-gpg data-key="{esc(p["key"])}">{grid}</div>'
            f'{html[:i]}{apterm.plan_html(p.get("plan"))}{html[i:]}<div class=apx-gpa>{act}</div></div>')
    return (f'<details class="apx-gp{" is-paper" if p["paper"] else ""}" id=gp-{p["pid"]} data-key="{esc(p["key"])}" '
            f'data-tok="{esc(tok)}">{summ}{body}</details>')


def block_html(tcon, positions, now, lim=None):
    """The Grok positions at the top of the page: a heading and one collapsed row each; '' without any."""
    import sqlite3
    from ui import grokauto, pravitrade
    rows = [p for p in positions or [] if p.get("grok")]
    if not rows:
        return ""
    lim = lim or grokauto.limits(tcon)
    lcon = pravitrade._league_ro()
    try:
        rinfo = {}
        if lcon is not None:
            lcon.row_factory = sqlite3.Row
            for p in rows:
                if p.get("grok") == "auto":
                    try:
                        rinfo[p["token"]] = grokauto.round_info(tcon, lcon, p["token"], now)
                    except Exception:  # noqa: BLE001
                        pass
        # the topcheck / rug filter rows are read by facts() only when its FACTS_TTL_S copy of the token is old
        out = [row_html(tcon, lcon, p, now, rinfo.get(p["token"]), lim["max_round_trips_per_token_day"])
               for p in rows]
    finally:
        if lcon is not None:
            lcon.close()
    return (f'<h3 class=apx-gh>Grokove pozicije <span class=apx-cnt>{len(rows)}</span>'
            '<span class=apx-mut>dodirni red za obrazloženje</span></h3>'
            f'<div class=apx-gps-list>{"".join(out)}</div>')
