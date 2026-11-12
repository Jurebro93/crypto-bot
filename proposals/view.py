"""What the Autopilot card "Prijedlozi" and the MCP tool get_proposals show. Read-only on proposals.db (the pass
writes it), cached CACHE_S per process: the page and Grok never build anything.

The card (owner only, right after "Brza kupnja", nothing while the flag is off): the open proposals ranked by EV
then by independent sources, TOP_N rows in sight and the rest behind "još"; each row opens to the plain why, the
links, the entry zone and the exits in market cap, the chance with n and its interval, EV, the size, the risks and
until when it is valid, with "Kupi" (fills Brza kupnja with the token, size, TP and SL: the owner confirms there) and
"Odbij" (a preset reason or his own words, stored for learning). Under it the last 24 h: decided and expired
proposals with what happened after (missed opportunities). The list is a fragment (/pravi-trade/prijedlozi) polled
every EVERY_S seconds by the page's poller, not a page reload.
11.11. (the owner's rules after HAOBIBI): every open row says whether it waits ("čeka ulaz": the market cap outside
its entry zone or under its stop), is "u zoni", or the demo account already entered ("ušao (paper) na MC ..."); the
status in proposals.db stays novo (entry_state; get_proposals entry_state and report.zone_misses).
"""
import datetime as dt
import json
import time
from urllib.parse import quote
from zoneinfo import ZoneInfo

from . import calib, store, strategies

CACHE_S = 30
TOP_N = 5
EVERY_S = 150
TZ = "Europe/Zagreb"
_CACHE = {}
RULES_TEXT = (
    "One row per token over the strategies range, momentum, influencer, group, insider, event, grok (sources = the "
    "strategies proposing it). EV per strategy = p_tp x TP - (1 - p_tp) x SL - cost, TP / SL of that strategy's exit "
    "from the market cap now; cost = trade/cost: 2 x fee_side + 2 x size / (liq / 2 + size) (fee_side 1 % until real "
    "swaps calibrate it). p_tp = the strategy's measured hits / n shrunk toward no edge: (hits + 20 x p0) / (n + 20), "
    "p0 = (SL + cost) / (TP + SL), so an unmeasured strategy has EV 0 and is never shown; ci90 = Wilson 90 % of the raw "
    "hit rate. Grok's p_tp is calibrated on its measured predictions first (grok_calibration). Modifiers, never blocks: "
    "run-up 4x+ from the first signal p x 0.7 and size x 0.5 (not when X bursts and buys >= 60 %), wash or shill-driven "
    "p x 0.5; size = min(caps, the stake with <= 2 % slippage) x (1 h volume / $10k under $10k). Blocks only: rug high, "
    "liquidity < $15k, 1 h volume < $3k, under $30k, not bonded, fake pool, not trading. Shown with EV > 0 (paper); "
    "ranked by EV per expected minute, then the EV at the low end of the 90 % interval, then liquidity. Live / "
    "autotrade needs EV >= +3 %, the interval's low end > 0 and n >= 10. paper_only rows (event / market watchlist) "
    "never trade real money.")


def _mode():
    try:
        from league import flags
        return flags.mode("proposals")
    except Exception:  # noqa: BLE001
        return "off"


def load(now=None, path=None, fresh=False):
    """{"active", "waiting", "recent", "last_pass", "report", "calib"} (cached CACHE_S). 11.11. (the owner's decision
    4): "active" = the PUBLISHED open proposals only (what "Što kupiti" and the card show); "waiting" = the open ones in
    the state "čeka zonu" (proposals/publish.check), also put first among last_pass "near" (the "prikaži skoro" list)."""
    t = time.time()
    key = path or ""
    hit = _CACHE.get(key)
    if hit and not fresh and now is None and t - hit[0] < CACHE_S:
        return hit[1]
    now_i = int(now or t)
    con = store.ro(path)
    if con is None:
        d = {"active": [], "waiting": [], "recent": [], "last_pass": None, "report": None, "calib": None}
    else:
        try:
            act = store.read(con, "status='novo' AND expires_ts > ?", (now_i,), order="ev_pct DESC, n_independent DESC, id",
                             limit=60)
            rec = store.read(con, "status != 'novo' AND status_ts >= ?", (now_i - 86400,), order="status_ts DESC", limit=60)
            d = {"active": [p for p in act if store.published(p)], "waiting": [p for p in act if not store.published(p)],
                 "recent": rec, "last_pass": store.kv_get(con, "last_pass"), "calib": store.kv_get(con, "grok_calib")}
            d["last_pass"] = waiting_near(d["waiting"], d["last_pass"])
            r = con.execute("SELECT data FROM reports ORDER BY day DESC LIMIT 1").fetchone()
            d["report"] = json.loads(r[0]) if r else None
        except Exception:  # noqa: BLE001 - a half-written database shows nothing, never an error page
            d = {"active": [], "waiting": [], "recent": [], "last_pass": None, "report": None, "calib": None}
        finally:
            con.close()
    if now is None:
        _CACHE[key] = (t, d)
    return d


def clear():
    _CACHE.clear()


def waiting_near(waiting, lp):
    """last_pass with the waiting proposals ("čeka zonu") first among its near misses (the "prikaži skoro" list reads
    them: token, symbol, strategies, ev_pct, why, blocks)."""
    if not waiting:
        return lp
    lp = dict(lp or {})
    w = [{"token": p["token"], "symbol": p.get("symbol"), "strategies": p.get("sources") or [], "ev_pct": p.get("ev_pct"),
          "why": f"{WAIT_ZONE}: {p.get('wait_why')}", "blocks": [], "mcap": p.get("last_mcap"), "proposal_id": p["id"],
          "state": WAIT_ZONE} for p in waiting]
    have = {x["token"] for x in w}
    lp["near"] = w + [n for n in lp.get("near") or [] if n.get("token") not in have]
    return lp


def _hm(ts):
    return dt.datetime.fromtimestamp(int(ts), ZoneInfo(TZ)).strftime("%H:%M") if ts else "?"


def _usd(x):
    return strategies._usd(x)


def _pct(x, sign=True):
    if x is None:
        return "-"
    s = f"{x:+.1f}" if sign else f"{x:.0f}"
    return s.replace(".", ",") + " %"


def _exits_text(r):
    e = r.get("exits_mcap") or {}
    parts = []
    for i, (mc, sh) in enumerate(zip(e.get("tp") or [], e.get("tp_share") or [])):
        parts.append(f"TP {_usd(mc)}" + (" (pola)" if sh and sh < 1 and i == 0 else ""))
    if e.get("trailing_pct"):
        parts.append(f"trailing {e['trailing_pct']:g} %".replace(".", ","))
    if e.get("sl"):
        parts.append(f"SL {_usd(e['sl'])}")
    if e.get("time_min"):
        parts.append(f"van nakon {int(e['time_min'])} min" if e["time_min"] < 600 else
                     f"van nakon {e['time_min'] / 60:.0f} h")
    return " · ".join(parts)


def _p_text(r):
    ci = r.get("ci90") or [None, None]
    tail = f"; 90 %: {ci[0] * 100:.0f}–{ci[1] * 100:.0f} %" if ci and ci[0] is not None and r.get("n") else ""
    g = r.get("grok") or {}
    gt = (f"; Grok rekao {g['p_tp_raw'] * 100:.0f} %, kalibrirano {g['p_tp_calibrated'] * 100:.0f} %"
          if g.get("p_tp_raw") is not None and r.get("strategy") == "grok" else "")
    return f"{(r.get('p_tp') or 0) * 100:.0f} % (n={r.get('n') or 0}{tail}{gt})"


REJECT_HR = store.REJECT_REASONS
PAPER_IN = "ušao (paper)"
WAIT_ZONE = "čeka zonu"   # 11.11. (decision 4): not published (proposals/publish.check), wait_why says why


def entry_state(p, now=None):
    """11.11. (the owner's rules after HAOBIBI) the waiting state of an open proposal (status stays novo in the
    database): {"state": "čeka ulaz" | "u zoni" | "ušao (paper)", "text", "mcap", "mcap_ts", "zone": [low, high],
    "sl", "below_sl_at_creation"}. The market cap: the newest the pass or the demo account's paper loop read (last_mcap,
    at most store.PRICE_FRESH_S old), else the one of the pass that last showed it."""
    now = int(now or time.time())
    r = p.get("row") or {}
    mc, ts = p.get("last_mcap"), p.get("last_mcap_ts")
    if not mc or now - (ts or 0) > store.PRICE_FRESH_S:
        mc, ts = (r.get("market") or {}).get("market_cap_usd") or mc, p.get("updated_ts") or ts
    chk = strategies.wait_check(p, mc) or {"state": strategies.WAIT, "zone": strategies.zone_of(r, p.get("mcap0")),
                                           "sl": strategies.stop_of(r)}
    z = chk["zone"]
    out = {"state": chk["state"], "mcap": mc, "mcap_ts": ts, "zone": [round(z[0]), round(z[1])] if z else None,
           "sl": chk["sl"], "below_sl_at_creation": p.get("below_sl_at_creation")}
    if p.get("paper_ts"):
        out.update(state=PAPER_IN, text=f"{PAPER_IN} na MC {_usd(p.get('paper_mcap'))} u {_hm(p['paper_ts'])}",
                   paper_ts=p["paper_ts"], paper_mcap=p.get("paper_mcap"))
        return out
    if p.get("wait_why"):   # 11.11. (decision 4): not published; the 20-s loop decides again until expires_ts
        out.update(state=WAIT_ZONE, text=f"{WAIT_ZONE} · {p['wait_why']}", wait_why=p["wait_why"])
        return out
    where = f"sada {_usd(mc)}, zona {strategies.zone_text(z)}" if mc else f"zona {strategies.zone_text(z)}"
    if chk["state"] == strategies.WAIT and mc and chk["sl"] and mc < chk["sl"]:
        where += (f", pao ispod SL-a {_usd(chk['sl'])}: ističe" if chk.get("dead") else
                  f", ispod SL-a {_usd(chk['sl'])} već pri prijedlogu: čeka zonu")
    out["text"] = f"{chk['state']} · {where}"
    return out


def _row_inner(p, esc):
    r = p.get("row") or {}
    tok = p["token"]
    m = r.get("market") or {}
    ez = r.get("entry_zone") or {}
    b = r.get("buy") or {}
    pk = json.dumps({"id": p["id"], "token": tok, "sol": f"{p.get('size_sol') or 0:g}", "tp": b.get("tp") or "",
                     "sl": b.get("sl") or "", "sym": p.get("symbol") or tok[:6]})
    rows = [("Stanje", entry_state(p)["text"]),
            ("Ulaz (MC)", f"{_usd(ez.get('mcap_low'))} – {_usd(ez.get('mcap_high'))} (sada {_usd(m.get('market_cap_usd'))})"
             if ez else f"sada {_usd(m.get('market_cap_usd'))}"),
            ("Izlaz (MC)", _exits_text(r)),
            ("Šansa TP prije SL", _p_text(r)),
            ("EV", f"{_pct(p.get('ev_pct'))} nakon troška {str(r.get('cost_pct') or '-').replace('.', ',')} %"),
            ("Ulog", f"{p.get('size_sol') or 0:g} SOL".replace(".", ",")),
            ("Vrijedi do", _hm(p.get("expires_ts")))]
    if r.get("dca"):
        rows.insert(2, ("DCA", r["dca"]))
    if (r.get("range_tier") or {}).get("text"):   # rangedca.tier (noc/tier): "Tier T2 · ulog 0.25 · razlog: ..."
        rows.insert(2, ("Tier raspona", r["range_tier"]["text"]))
    cells = "".join(f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in rows)
    risks = r.get("risks") or []
    opts = "".join(f'<label><input type=radio name=reason value="{esc(x)}"{" checked" if i == 0 else ""}> {esc(x)}</label> '
                   for i, x in enumerate(REJECT_HR))
    return (f'<p>{esc(r.get("why") or "")}</p>'
            f'<p class=mut><a href="https://dexscreener.com/solana/{quote(tok)}" target=_blank rel=noopener>DexScreener ↗</a>'
            f' · <a href="https://solscan.io/token/{quote(tok)}" target=_blank rel=noopener>Solscan ↗</a> · '
            f'<code>{esc(tok[:4])}…{esc(tok[-4:])}</code> · izvori: '
            f'{esc(", ".join(strategies.HR.get(s, s) for s in p.get("sources") or []))}'
            f' ({p.get("n_independent") or 1} neovisn{"i" if (p.get("n_independent") or 1) == 1 else "ih"})</p>'
            f'<table class=t>{cells}</table>'
            + (f'<p class=mut>Rizici: {esc("; ".join(risks))}.</p>' if risks else "")
            + ('<p class=mut>Samo paper: event token ili tržišna range lista nikad ne trguje pravim novcem.</p>'
               if r.get("paper_only") else
               f'<p><button type=button class=ap-buy data-pk="{esc(pk)}">Kupi</button> '
               '<span class=mut>otvara Brzu kupnju s ovim tokenom, ulogom, TP-om i SL-om; potvrđuješ ti</span></p>')
            + f'<details><summary class=mut>Odbij</summary><form method=post action=/pravi-trade/prijedlog-odbij>'
            f'<input type=hidden name=id value={int(p["id"])}>{opts}'
            '<input name=note placeholder="zašto (neobavezno)" size=24 maxlength=300 autocomplete=off>'
            '<button>Odbij</button></form></details>')


def _after_text(p):
    a = (p.get("after") or {}).get("4h") or (p.get("after") or {}).get("1h") or {}
    if a.get("status") != "ok":
        return "ishod se još mjeri"
    first = {"tp": "TP prije SL-a", "sl": "SL prije TP-a", "none": "ni TP ni SL"}.get(a.get("first"), "?")
    k = "4 h" if (p.get("after") or {}).get("4h") else "1 h"
    return f"{k}: najviše {_pct(a.get('max_gain_pct'))}, najdublje {_pct(a.get('max_dd_pct'))}, {first}"


def fragment(esc, item, now=None, path=None):
    """The inside of the card (the polled box)."""
    d = load(now, path)
    act = d["active"]
    out = []

    def one(p):
        reason = entry_state(p, now)["state"] + " · " + \
            " · ".join([strategies.HR.get(s, s) for s in p.get("sources") or []][:3]) + \
            f" · {p.get('size_sol') or 0:g} SOL".replace(".", ",") + f" · do {_hm(p.get('expires_ts'))}"
        return item(p.get("symbol") or p["token"][:6], reason, _row_inner(p, esc), value=_pct(p.get("ev_pct")),
                    sub="EV", iid=f"pr-{p['id']}", value_tone="pos")
    if not act:
        lp = d.get("last_pass") or {}
        out.append('<p class=mut>Trenutno nijedan prijedlog nema EV iznad nule bez blokade.'
                   + (f' Zadnja provjera {_hm(lp.get("ts"))}, skoro: {len(lp.get("near") or [])}.' if lp.get("ts") else "")
                   + (f' Čeka zonu: {len(d.get("waiting") or [])}.' if d.get("waiting") else "")
                   + '</p>')
    out += [one(p) for p in act[:TOP_N]]
    if len(act) > TOP_N:
        out.append(f'<details class=ap-it><summary class=mut>još {len(act) - TOP_N}</summary><div class=in>'
                   + "".join(one(p) for p in act[TOP_N:]) + '</div></details>')
    rec = d["recent"]
    if rec:
        n = {s: sum(1 for p in rec if p["status"] == s) for s in ("kupljeno", "odbijeno", "isteklo")}
        lines = "".join(
            f'<li><b>{esc(p.get("symbol") or p["token"][:6])}</b> {esc(p["status"])} {esc(_hm(p.get("status_ts")))} '
            f'({esc(", ".join(strategies.HR.get(s, s) for s in p.get("sources") or []))}, EV {esc(_pct(p.get("ev_pct")))}'
            + (f', razlog: {esc(p.get("reject_reason"))}' if p.get("reject_reason") else "")
            + f') · {esc(_after_text(p))}</li>' for p in rec[:15])
        out.append(f'<details class=ap-it id=pr-zadnje><summary class=mut>Zadnja 24 h: kupljeno {n["kupljeno"]}, odbijeno '
                   f'{n["odbijeno"]}, isteklo {n["isteklo"]} (što se dogodilo poslije)</summary><div class=in><ul>{lines}'
                   '</ul></div></details>')
    return "".join(out)


KUPI_JS = ("<script>(()=>{if(window.apPk)return;window.apPk=1;document.addEventListener('click',e=>{"
           "const b=e.target.closest('[data-pk]');if(!b)return;e.preventDefault();const d=JSON.parse(b.dataset.pk);"
           "const s=document.getElementById('kupi-odmah'),f=s&&s.querySelector('form');if(!f)return;const el=f.elements;"
           "el.token.value=d.token;el.sol.value=d.sol;if(el.at)el.at.value='';el.tp.value=d.tp;el.sl.value=d.sl;"
           "if(el.exit)el.exit.value='tpsl';let h=el.prijedlog;if(!h){h=document.createElement('input');h.type='hidden';"
           "h.name='prijedlog';f.appendChild(h)}h.value=d.id;let n=document.getElementById('ap-pk-note');"
           "if(!n){n=document.createElement('p');n.id='ap-pk-note';n.className='mut';f.after(n)}"
           "n.textContent='Prijedlog '+d.sym+': ulog '+d.sol+' SOL, TP '+d.tp+', SL '+d.sl+'. Provjeri i dodirni Kupi.';"
           "s.scrollIntoView({behavior:'smooth',block:'start'});})})()</script>")


def card(esc, item, owner, now=None, path=None):
    """The card (owner only, '' while the flag is off)."""
    if not owner or _mode() == "off":
        return ""
    d = load(now, path)
    n = len(d["active"])
    mode = _mode()
    head = f'Prijedlozi <span class=mut>· {n} otvoren{"" if n == 1 else "ih"} · {esc(mode)}</span>'
    return (f'<section class="ap-qb ap-prop" id=prijedlozi-trade><h2 class=ap-qb-h data-sec="">{head}</h2>'
            f'<div id=ap-prijedlozi data-src=/pravi-trade/prijedlozi data-every={EVERY_S}>{fragment(esc, item, now, path)}'
            '</div><p class=mut>Iz svih strategija; prikazuje se samo EV iznad nule nakon troška. Ništa se ne kupuje samo: '
            'Kupi popunjava Brzu kupnju, a izlazi prijedloga postaju TP i SL pozicije.</p></section>' + KUPI_JS)


# ---------- MCP get_proposals --------------------------------------------------------------------------------------------

def _mcp_row(p):
    r = p.get("row") or {}
    st = {}
    for k, v in (r.get("strategies") or {}).items():
        st[k] = ({kk: v.get(kk) for kk in ("p_tp", "p_tp_raw", "n", "hits", "ci90", "prior", "p_from", "tp_pct", "sl_pct",
                                           "cost_pct", "ev_pct", "ev_lo_pct", "ev_per_min", "duration_min", "p_mult",
                                           "expires_ts", "entry_zone", "exits_mcap", "why", "calibrated",
                                           "similar_shadow")}
                 if v.get("valid") else {"valid": False, "why_not": v.get("why_not")})
    return {"id": p["id"], "token": p["token"], "symbol": p.get("symbol"), "status": p["status"],
            "status_why": p.get("status_why"),
            "entry_state": entry_state(p) if p["status"] == "novo" else None, "created_ts": p.get("created_ts"), "expires_ts": p.get("expires_ts"),
            # 11.11. (decision 4): published = shown in "Što kupiti"; else "čeka zonu" with wait_why; the EV is measured
            # from the middle of the entry zone (ev_from), the publication against 1 x ATR (atr_mcap, atr_from)
            "published": store.published(p), "wait_why": p.get("wait_why"), "published_ts": p.get("published_ts"),
            "ev_from": r.get("ev_from"), "atr_mcap": r.get("atr_mc"), "atr_from": r.get("atr_from"),
            "strategy": p.get("strategy"), "sources": p.get("sources"), "n_independent": p.get("n_independent"),
            "ev_pct": p.get("ev_pct"), "p_tp": {"value": p.get("p_tp"), "n": r.get("n"), "ci90": r.get("ci90")},
            "grok": r.get("grok"), "strategies": st, "entry_zone_mcap": r.get("entry_zone"),
            "exits_mcap": r.get("exits_mcap"), "exit_plan": r.get("exit_plan"), "size_sol": p.get("size_sol"),
            "range_tier": r.get("range_tier"), "ev_lo_pct": r.get("ev_lo_pct"), "ev_per_min": r.get("ev_per_min"),
            "duration_min": r.get("duration_min"), "modifiers": r.get("modifiers"), "paper_only": bool(r.get("paper_only")),
            "cost_pct": r.get("cost_pct"), "risks": r.get("risks"), "why": r.get("why"), "market_at_update": r.get("market"),
            "rug": r.get("rug"), "runup_x": r.get("runup_x"), "after": p.get("after") or None,
            "reject_reason": p.get("reject_reason"), "reject_note": p.get("reject_note"), "bought_sol": p.get("bought_sol"),
            # 11.11. (rangedca/owner.py): the owner's pin (never an automatic real-money buy) and the similarity's
            # shadow P bonus (recorded only, P unchanged)
            "pinned": bool(r.get("pinned")), "pin_only": bool(r.get("pin_only")), "similar_shadow": r.get("similar_shadow")}


def owner_labels():
    """The owner's learning labels (rangedca/owner.py, league.db owner_labels) for get_proposals; [] when unreadable."""
    try:
        from rangedca import owner
        return [owner.label_view(lb) for lb in owner.labels()]
    except Exception:  # noqa: BLE001 - no labels readable: none shown
        return []


def _num(x, default, lo, hi, cast=float):
    try:
        return max(lo, min(hi, cast(x)))
    except (TypeError, ValueError):
        return default


def mcp(since=None, min_ev=None, include_blocked=False, status=None, limit=None, now=None, path=None):
    """get_proposals."""
    now_i = int(now or time.time())
    since_i = int(_num(since, now_i - 86400, 0, now_i, int)) if since not in (None, "") else now_i - 86400
    me = _num(min_ev, 0.0, -100.0, 1000.0) if min_ev not in (None, "") else 0.0
    lim = int(_num(limit, 50, 1, 200, int)) if limit not in (None, "") else 50
    if status not in (None, "") and status not in store.STATUSES:
        return {"error": f"status must be one of {', '.join(store.STATUSES)}"}
    m = _mode()
    base = {"ts": now_i, "flag_mode": m, "rules": RULES_TEXT,
            "notes": ("Read-only; nothing here buys. Grok autotrade may buy a proposal only through execute_trade within "
                      "its own grok_autotrade limits (p_tp = the proposal's p_tp, strategy as named), then set_exit_plan "
                      "with the proposal's exit_plan. Add a proposal with submit_signal_opinion (verdict kupi, p_tp, "
                      "optional strategy, entry_zone, exit_zone, valid_min); your p_tp is calibrated before it counts. "
                      "An open proposal (status novo) WAITS for its entry zone: entry_state.state 'čeka ulaz' while the "
                      "market cap is outside entry_zone_mcap (or under the stop), 'u zoni' inside it, 'ušao (paper)' "
                      "once the demo account entered; buy only 'u zoni'. 11.11.: EV is measured from the MIDDLE of the "
                      "entry zone (ev_from); a proposal is published only while the market cap is inside its zone and "
                      ">= 1 x ATR above its stop (atr_mcap; 5 % of MC for strategies without an ATR), else it is kept "
                      "as published false, entry_state 'čeka zonu' with wait_why (re-checked every 20 s until it "
                      "expires); never buy a 'čeka zonu' row. report.zone_misses: the proposals of the last "
                      "48 h that went through their zone without a paper entry and what would have happened. "
                      "pinned / pin_only rows come from the owner's pin (a recommendation: never buy them with real "
                      "money on your own; only the owner's tap does). owner_labels: the owner's learning labels "
                      "(counterfactual; the booked results never change)."),
            "owner_labels": owner_labels()}
    if m == "off":
        return {**base, "total": 0, "proposals": [], "note": "zastavica proposals (G21) je isključena"}
    con = store.ro(path)
    if con is None:
        return {**base, "total": 0, "proposals": [], "note": "još nema nijednog prijedloga (pass nije prošao)"}
    try:
        where, args = "created_ts >= ? AND COALESCE(ev_pct, 0) >= ?", [since_i, me]
        if status:
            where += " AND status = ?"
            args.append(status)
        rows = store.read(con, where, args, order="(status = 'novo') DESC, ev_pct DESC, n_independent DESC, id DESC",
                          limit=lim)
        lp = store.kv_get(con, "last_pass") or {}
        model = store.kv_get(con, "grok_calib")
        r = con.execute("SELECT data FROM reports ORDER BY day DESC LIMIT 1").fetchone()
        rep = json.loads(r[0]) if r else None
        zm = store.kv_get(con, "zone_misses")   # 11.11.: proposals through their zone without a paper entry (48 h)
        if zm:
            rep = {**(rep or {}), "zone_misses": zm}
    finally:
        con.close()
    out = {**base, "total": len(rows), "open": sum(1 for p in rows if p["status"] == "novo"),
           "proposals": [_mcp_row(p) for p in rows], "last_pass_ts": lp.get("ts"),
           "grok_calibration": calib.summary(model), "report": rep}
    if include_blocked:
        out["blocked"] = [{k: n.get(k) for k in ("token", "symbol", "strategies", "why", "blocks", "ev_pct", "mcap")}
                          for n in lp.get("near") or []]
    return out
