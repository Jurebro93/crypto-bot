"""Every live candidate's fast_check where the owner looks (11.11., Jure: "živi kandidati alata: za svakog odmah
fast_check i procjena EV-a, nikad 'nije izmjeren'").

  ensure(rows)      the rows of the live list (ui/zivo): their triggers go into the queue (fast/enqueue.submit_live; at
                    once for a token without any check, every ENSURE_EVERY_S for the rest; enqueue dedupes a (token,
                    source) per 10 min), each with its own source: the callers of the last 10 min
                    (influencer), the buys of the followed / proven wallets of the last 10 min (wallet_follow / proven),
                    the convergence (konvergencija), else the tool's own pick (alat, the moment it is listed). The
                    worker decides within seconds; until then the row says "provjera u tijeku".
  lookup(tokens)    {token: verdict}: the newest fast_check of the token in the last WINDOW_S (one read-only query)
  attach(rows)      ensure + lookup: r["fast"] on every live row, the lag recomputed on the row's live price
  verdict           {"state" done | pending | failed | off, "decision", "label" (KUPI (paper) / KUPI (live-eligible) /
                    PRESKOČI / provjera u tijeku / CHECK_FAILED), "ev_pct", "ev_lo_pct", "ev_hi_pct" (90 %), "p",
                    "p_lo", "p_hi", "n", "origin" (source | prior: <strategy>), "n_label" ("procjena, n izvora < 10"),
                    "lag_pct", "lag_txt" (jeftinije od njega / izlazi / skuplje od njega), "reason", "kind", "source"}
                    Of several checks on one token: the best KUPI, else the newest PRESKOČI, else one in progress,
                    else the failed one (its failing check).
  cells_html        the EV and P cells of a "Što kupiti" row (ui/apterm), short() one line for the other lists
  skip_rows /       the PRESKOČI journal: every fast_check skip of the last 24 h with its reason, its numbers and
  skip_html         what happened after (fast/outcomes: +1/+5/+15/+60 min, max; propušteno = max >= +20 % within
                    60 min), for the Autopilot's "Preskočeni" box (ui/pravitrade.skip_box, owner only)
  kupi_rows         the KUPI decisions of the last 15 min for proposals/ (strategy "fast", proposals/strategies.fast_ev)
Reads fast.db read-only (WAL: never waits for the worker); the only write is the queue insert of ensure().
"""
import time

from . import estimate, sources, store

WINDOW_S = 900
SLOW_S = 10            # the owner's "≤ 10 s": a check pending longer says how long
KUPI_S = 900           # a KUPI decision is a proposal this long (proposals/strategies.EXPIRY_S["fast"])
SKIP_DAY_S = 86400
SKIP_SHOW = 15
RECENT_S = 600         # = ui/zivo.RECENT_S: the triggers of a live row
ENSURE_EVERY_S = 30    # every row's triggers are re-offered this often (a new caller on a checked token)
BUY = ("BUY_PAPER", "BUY_LIVE")
_ENS = {"ts": 0.0}
_COLS = "id, token, symbol, kind, source_id, source_label, sig_ts, enq_ts, status, decided_ts, decision, reason, " \
        "ev_pct, p_tp, cost_pct, checks, price0, mcap0, entry_px, entry_mcap, out, max60, missed, hit, latency_s"


def _mode():
    try:
        from . import enqueue
        return enqueue.mode()
    except Exception:  # noqa: BLE001
        return "off"


def _rows(con, where, args, limit=2000):
    import json
    out = []
    try:
        cur = con.execute(f"SELECT {_COLS} FROM signals WHERE {where} ORDER BY id DESC LIMIT ?", (*args, int(limit)))
    except Exception:  # noqa: BLE001 - an old fast.db: nothing
        return out
    names = [c.strip() for c in _COLS.split(",")]
    for r in cur:
        d = dict(zip(names, r))
        for k in ("checks", "out"):
            try:
                d[k] = json.loads(d[k]) if d[k] else {}
            except ValueError:
                d[k] = {}
        out.append(d)
    return out


# ---------- one verdict ---------------------------------------------------------------------------------------------------

def _state(r):
    st, dec = r.get("status"), r.get("decision")
    if st in ("queued", "running"):
        return "pending"
    if st in ("retry", "failed") or dec == "CHECK_FAILED":
        return "failed"
    return "done" if dec else "pending"


def _failing(r):
    """The check that failed to read (CHECK_FAILED), its text."""
    c = r.get("checks") or {}
    k = c.get("key")
    res = (c.get("res") or {}).get(k) or {}
    return res.get("text") or r.get("reason") or "provjera nije uspjela"


def one(r, now=None, live=None):
    """The verdict of one fast.db signal row (see the module text); live: the row's live market (price) for the lag."""
    now = now or time.time()
    c = r.get("checks") or {}
    est = c.get("est") or {}
    pv = ((c.get("res") or {}).get("price") or {}).get("values") or {}
    state = _state(r)
    v = {"state": state, "id": r.get("id"), "token": r.get("token"), "symbol": r.get("symbol"), "kind": r.get("kind"),
         "kind_hr": sources.KIND_HR.get(r.get("kind"), r.get("kind")),
         "source": r.get("source_label") or (r.get("source_id") or "")[:8], "source_id": r.get("source_id"),
         "sig_ts": r.get("sig_ts"), "decided_ts": r.get("decided_ts"), "decision": r.get("decision"),
         "key": c.get("key"),
         "ev_pct": r.get("ev_pct"), "ev_lo_pct": est.get("ev_lo_pct"), "ev_hi_pct": est.get("ev_hi_pct"),
         "p": est.get("p", r.get("p_tp")), "p_lo": est.get("p_lo"), "p_hi": est.get("p_hi"), "p0": est.get("p0"),
         "p_mult": est.get("p_mult"),
         "n": est.get("n"), "hits": est.get("hits"), "origin": est.get("origin"), "n_label": est.get("label"),
         "prior": est.get("prior"), "cost_pct": r.get("cost_pct"), "reason": r.get("reason"),
         "lag_pct": pv.get("from_entry_pct"), "lag_txt": pv.get("lag_txt"), "sold": bool(pv.get("src_sold")),
         "entry_px": pv.get("entry_px") or r.get("entry_px"), "price0": r.get("price0"), "mcap0": r.get("mcap0"),
         "max60": r.get("max60"), "missed": r.get("missed"), "out": r.get("out") or {}}
    if state == "pending":
        age = max(0, int(now - (r.get("enq_ts") or now)))
        v["label"] = "provjera u tijeku" + (f" ({age} s)" if age > SLOW_S else "")
        v["reason"] = None
    elif state == "failed":
        v["label"] = "CHECK_FAILED"
        v["reason"] = _failing(r) + (" (ponovno za nekoliko s)" if r.get("status") == "retry" else "")
    else:
        v["label"] = estimate.label(r.get("decision"))
    price = (live or {}).get("price")
    if price and v["entry_px"]:   # the lag NOW: the live price against the source's entry
        ch = float(price) / float(v["entry_px"]) - 1
        lg = estimate.lag(ch, v["sold"], r.get("kind"))
        v["lag_pct"], v["lag_txt"] = lg["pct"], lg["txt"]
    return v


def pick(rows, now=None, live=None, prefer=()):
    """The verdict of a token from its signal rows (newest first): KUPI with the best EV, else the newest PRESKOČI,
    else one in progress, else the failed one. prefer: source ids of the row's own triggers (taken first if any)."""
    if not rows:
        return None
    own = [r for r in rows if r.get("source_id") in set(prefer or ())]
    rs = own or rows
    vs = [one(r, now, live) for r in rs]
    pend = sum(1 for v in vs if v["state"] == "pending")
    buys = [v for v in vs if v["state"] == "done" and v["decision"] in BUY]
    skips = [v for v in vs if v["state"] == "done" and v["decision"] == "SKIP"]
    if buys:
        v = max(buys, key=lambda x: (x["ev_pct"] if x["ev_pct"] is not None else -99))
    elif skips:
        v = skips[0]
    elif pend:
        v = next(x for x in vs if x["state"] == "pending")
    else:
        v = vs[0]
    v = dict(v, n_checks=len(vs), n_pending=pend if v["state"] != "pending" else pend - 1)
    return v


def lookup(tokens, now=None, path=None, live=None, prefer=None, window=WINDOW_S):
    """{token: verdict} of the tokens' fast_checks of the last `window` (one read-only query); a token without one
    is missing. live: {token: market} for the lag now; prefer: {token: [source ids]}."""
    now = now or time.time()
    toks = [t for t in dict.fromkeys(tokens or ()) if t]
    if not toks:
        return {}
    con = store.ro(path)
    if con is None:
        return {}
    try:
        q = ",".join("?" * len(toks))
        rows = _rows(con, f"token IN ({q}) AND COALESCE(sig_ts, enq_ts) >= ?", (*toks, int(now - window)))
    finally:
        con.close()
    by = {}
    for r in rows:
        by.setdefault(r["token"], []).append(r)
    return {t: pick(rs, now, (live or {}).get(t), (prefer or {}).get(t) or ()) for t, rs in by.items()}


def missing(tok, mode):
    """The verdict of a live row without any fast_check: in progress (ensure just queued it), or off."""
    if mode == "off":
        return {"state": "off", "token": tok, "label": "fast_check isključen (fast_path: off)", "decision": None,
                "ev_pct": None, "reason": None}
    return {"state": "pending", "token": tok, "label": "provjera u tijeku", "decision": None, "ev_pct": None,
            "reason": None}


# ---------- the live list ----------------------------------------------------------------------------------------------

def _wallet_buys(now, tokens, paths=None):
    """{token: [(wallet, ts)]} of the followed and proven wallets' buys of the last RECENT_S (hype.db chain_trades),
    the same set ui/zivo counts as "pametnih novčanika kupilo"."""
    if not tokens:
        return {}
    try:
        from league import copy as lcopy
        from ui import pravitrade
        ws = pravitrade.followed_wallets()
        if not ws:
            return {}
        hc = lcopy._ro((paths or lcopy._paths())["hype"])
        if hc is None:
            return {}
        try:
            qt, qw = ",".join("?" * len(tokens)), ",".join("?" * len(ws))
            rows = lcopy._q(hc, f"SELECT mint, wallet, MIN(ts) FROM chain_trades WHERE ts >= ? AND side = 'buy' AND "
                                f"mint IN ({qt}) AND wallet IN ({qw}) GROUP BY mint, wallet",
                            (int(now) - RECENT_S, *tokens, *sorted(ws)))
        finally:
            hc.close()
    except Exception:  # noqa: BLE001 - unreadable: the row falls back to another trigger
        return {}
    out = {}
    for m, w, ts in rows:
        out.setdefault(m, []).append((w, int(ts)))
    return out


def _proven():
    try:
        from wallets import dokazani
        return dokazani.current()
    except Exception:  # noqa: BLE001
        return set()


def _call_times(now, tokens):
    """{(token, handle): first call ts} of the last RECENT_S (kol/converge.events, the same read as ui/zivo)."""
    try:
        from kol import converge
        ev, _s, _f = converge.events(int(now), RECENT_S)
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for tok, ts, plat, who, kind in ev:
        if tok in tokens and kind == "call" and plat != "chain":
            k = (tok, who.lstrip("@"))
            out[k] = min(out.get(k, int(ts)), int(ts))
    return out


def triggers(r, now, wallets=None, calls=None, proven=None):
    """The fast_check signals of one live row (ui/zivo): its callers of the last 10 min, its followed / proven
    wallets' buys, its convergence; else the tool's own pick at `now`."""
    tok = r["token"]
    m = r.get("live") or {}
    out = []
    for h in r.get("callers10") or []:
        sid = h.lstrip("@")
        ts = (calls or {}).get((tok, sid)) or int(now - min(r.get("age_s") or 0, RECENT_S))
        out.append({"token": tok, "source_id": sid, "sig_ts": int(ts), "via": "živa lista", "kind": "influencer",
                    "label": ("@" + sid) if not sid.startswith("tg:") else sid, "symbol": r.get("symbol")})
    for w, ts in (wallets or {}).get(tok) or []:
        out.append({"token": tok, "source_id": w, "sig_ts": int(ts), "via": "živa lista",
                    "kind": "proven" if w in (proven or ()) else "wallet_follow",
                    "label": f"{w[:4]}…{w[-4:]}", "symbol": r.get("symbol")})
    if r.get("src") == "konvergencija" and r.get("ts0") and now - r["ts0"] <= 900:
        out.append({"token": tok, "source_id": sources.CONVERGENCE, "sig_ts": int(r["ts0"]), "via": "živa lista",
                    "kind": "convergence", "label": "konvergencija izvora", "symbol": r.get("symbol"),
                    "entry_mcap": r.get("mcap0") or None})
    if not out:   # the tool's own pick (topcheck / the Pregled box) with a fresh move: checked as it is listed
        out.append({"token": tok, "source_id": sources.TOOL, "sig_ts": int(now), "via": "živa lista", "kind": "tool",
                    "label": f"alat ({r.get('src') or 'živo'})", "symbol": r.get("symbol") or m.get("symbol"),
                    "entry_px": m.get("price") or None})
    return out


def ensure(rows, now=None, have=None):
    """Queue the triggers of the live rows: at once for a row whose token has no fast_check yet; every
    ENSURE_EVERY_S for every row (a new caller or wallet on a token that already has a check gets its own; enqueue
    dedupes a (token, source) per 10 min, in memory before any read). Returns how many were queued."""
    now = now or time.time()
    have = have or {}
    rows = [r for r in rows or () if r.get("token")]
    full = now - _ENS["ts"] >= ENSURE_EVERY_S or now < _ENS["ts"]
    need = rows if full else [r for r in rows if r["token"] not in have]
    if not need or _mode() == "off":
        return 0
    if full:
        _ENS["ts"] = now
    from . import enqueue
    toks = [r["token"] for r in need]
    wallets = _wallet_buys(now, toks) if any(r.get("smart10") for r in need) else {}
    calls = _call_times(now, set(toks)) if any(r.get("callers10") for r in need) else {}
    proven = _proven() if wallets else set()
    items = []
    for r in need:
        ts = triggers(r, now, wallets, calls, proven)
        if r["token"] in have:   # the tool's own pick only stands in for a token without any check
            ts = [t for t in ts if t["kind"] != "tool"]
        items += ts
    return enqueue.submit_live(items, now=now)


def attach(rows, now=None, path=None):
    """r["fast"] on every live row (ensure first, then one lookup). Never raises."""
    now = now or time.time()
    if not rows:
        return rows
    try:
        toks = [r["token"] for r in rows]
        live = {r["token"]: r.get("live") or {} for r in rows}
        # the row's own triggers first ("for that token + source"): its callers, its convergence
        prefer = {r["token"]: [h.lstrip("@") for h in r.get("callers10") or []]
                  + ([sources.CONVERGENCE] if r.get("src") == "konvergencija" else []) for r in rows}
        have = lookup(toks, now, path, live, prefer)
        if ensure(rows, now, have):
            have = lookup(toks, now, path, live, prefer)
        m = _mode()
        for r in rows:
            r["fast"] = have.get(r["token"]) or missing(r["token"], m)
    except Exception as e:  # noqa: BLE001 - the live list stays without the numbers, never without its rows
        print(f"fast: živi kandidati bez fast_check-a ({type(e).__name__}: {e})", flush=True)
        for r in rows:
            r.setdefault("fast", {"state": "pending", "label": "provjera u tijeku", "decision": None, "ev_pct": None})
    return rows


# ---------- text ---------------------------------------------------------------------------------------------------------

def ev_line(v):
    """"EV +2,1 % (90 %: −1,0 do +5,2 %)"."""
    return estimate.ev_text(v)


def p_line(v):
    return estimate.p_text(v)


def lag_line(v):
    if not v or (v.get("lag_pct") is None and not v.get("lag_txt")):
        return ""
    return estimate.lag_text({"pct": v.get("lag_pct"), "txt": v.get("lag_txt")})


def short(v):
    """One line of a verdict, e.g. "KUPI (paper) · EV +2,1 % (90 %: −1,0 do +5,2 %) · P 58 % (n=3, prior: ...) ·
    −10,0 % od ulaza: jeftinije od njega", or "PRESKOČI · <reason>", "provjera u tijeku", "CHECK_FAILED: <check>"."""
    if not v:
        return "provjera u tijeku"
    if v.get("state") in ("pending", "off"):
        return v.get("label") or "provjera u tijeku"
    if v.get("state") == "failed":
        return f"CHECK_FAILED: {v.get('reason') or ''}".strip()
    parts = [v.get("label") or "", ev_line(v), p_line(v), lag_line(v)]
    if v.get("decision") == "SKIP":
        parts.append(v.get("reason") or "")
    return " · ".join(p for p in parts if p and p not in ("EV –", "P –"))


def ev_per_min(v):
    """EV % per expected minute of a KUPI verdict (the fast exit's 45 min, trade/edge.TIME_MIN), else None: the
    "Što kupiti" list sorts by it like the proposals."""
    from trade import edge
    if not v or v.get("decision") not in BUY or v.get("ev_pct") is None:
        return None
    return float(v["ev_pct"]) / edge.TIME_MIN


def cells_html(v, esc, tone=None):
    """The "Što kupiti" row's EV and p_tp cells (ui/apterm's data-l columns) of a verdict; never "nije izmjeren"."""
    tone = tone or (lambda x: "up" if (x or 0) > 0 else "dn" if (x or 0) < 0 else "")
    if not v or v.get("state") in ("pending", "off", "failed") or v.get("ev_pct") is None:
        txt = (v or {}).get("label") or "provjera u tijeku"
        if (v or {}).get("state") == "failed":
            txt = f"CHECK_FAILED: {v.get('reason') or ''}"
        return (f'<span class=n data-l="EV">…<small>{esc(txt[:90])}</small></span>'
                f'<span class=n data-l="p_tp (n)">–</span>')
    ci = (f"{estimate.pct(v.get('ev_lo_pct')).replace(' %', '')} do {estimate.pct(v.get('ev_hi_pct'))}"
          if v.get("ev_lo_pct") is not None else "")
    org = "izvor" if v.get("origin") == "source" else (v.get("origin") or "")
    p = v.get("p")
    lag = lag_line(v)
    return (f'<span class="n {tone(v.get("ev_pct"))}" data-l="EV" title="{esc(short(v))}">{esc(estimate.pct(v["ev_pct"]))}'
            f'<small>{esc(ci)} · {esc(v.get("label") or "")}' + (f' · {esc(lag)}' if lag else "") + '</small></span>'
            f'<span class=n data-l="p_tp (n)">{esc(f"{p * 100:.0f} %" if p is not None else "–")}'
            f'<small>n={int(v.get("n") or 0)} · {esc(org)}' + (f' · {esc(v["n_label"])}' if v.get("n_label") else "")
            + '</small></span>')


# ---------- the PRESKOČI journal ------------------------------------------------------------------------------------------

def skip_rows(now=None, path=None, day_s=SKIP_DAY_S, limit=300):
    """The fast_check skips of the last day, newest first, as verdicts with their outcome."""
    now = now or time.time()
    con = store.ro(path)
    if con is None:
        return []
    try:
        rows = _rows(con, "decision='SKIP' AND status='done' AND decided_ts >= ?", (int(now - day_s),), limit)
    finally:
        con.close()
    return [one(r, now) for r in rows]


def skip_verdict(v, now=None):
    """{"kind" miss | ok | wait, "word", "detail"} of one skip by its fast.db outcome (fast/outcomes: propušteno =
    max >= +20 % within 60 min of the decision)."""
    from . import outcomes
    now = now or time.time()
    o = v.get("out") or {}
    if v.get("max60") is None:
        left = int((v.get("decided_ts") or now) + outcomes.HORIZON_S - now)
        return {"kind": "wait", "word": "mjeri se",
                "detail": f"rezultat za {max(1, left // 60)} min" if left > 0 else "čeka cijenu"}
    if v.get("missed"):
        return {"kind": "miss", "word": "propušteno", "detail": f"najviše {estimate.pct(v['max60'], 0)} u 60 min"}
    tail = f", nakon 60 min {estimate.pct(o.get('60m'), 0)}" if o.get("60m") is not None else ""
    return {"kind": "ok", "word": "dobro preskočen" if o.get("hit") != 1 else "rubno: +15 % prije −10 %",
            "detail": f"najviše {estimate.pct(v['max60'], 0)} u 60 min{tail}"}


def skip_html(rows, esc, now=None, show=SKIP_SHOW):
    """The block of the fast_check skips for the owner's "Preskočeni" box: one sentence with the counts, then a row
    per skip (token, source, reason with the numbers, what happened after). '' without any."""
    from . import outcomes
    if not rows:
        return ""
    now = now or time.time()
    vs = [skip_verdict(v, now) for v in rows]
    n = {k: sum(1 for x in vs if x["kind"] == k) for k in ("miss", "ok", "wait")}
    head = (f"Fast check, zadnja 24 h: {len(rows)} preskočeno · propušteno {n['miss']} (≥ +{outcomes.MISS_PCT:.0f} % u "
            f"60 min) · dobro preskočeno {n['ok']} · mjeri se {n['wait']}.")
    items = []
    for v, sv in list(zip(rows, vs))[:show]:
        nums = " · ".join(x for x in (ev_line(v), p_line(v), lag_line(v)) if x and x not in ("EV –", "P –"))
        items.append(f'<li><b>{esc((v.get("token") or "")[:6])}</b> · {esc(v.get("source") or "")} '
                     f'({esc(v.get("kind_hr") or "")}): {esc(v.get("reason") or "")}'
                     + (f'<br><small class=mut>{esc(nums)}</small>' if nums else "")
                     + f' <span class="ap-skv {"warn" if sv["kind"] == "miss" else ""}">{esc(sv["word"])}: '
                       f'{esc(sv["detail"])}</span></li>')
    more = f"<p class=mut>… i još {len(rows) - show}.</p>" if len(rows) > show else ""
    return (f'<div class=ap-fsk id=ap-fsk><h3 class=ap-sub><span>Fast check: preskočeni</span></h3>'
            f'<p class=ap-sk-h>{esc(head)}</p><ul class=ap-fsk-l>{"".join(items)}</ul>{more}</div>')


# ---------- proposals -----------------------------------------------------------------------------------------------------

def kupi_rows(now=None, path=None, window=KUPI_S):
    """{token: the best KUPI fast_check of the last `window`} (status done, BUY_PAPER / BUY_LIVE) for proposals/."""
    now = now or time.time()
    con = store.ro(path)
    if con is None:
        return {}
    try:
        rows = _rows(con, "status='done' AND decision IN ('BUY_PAPER', 'BUY_LIVE') AND decided_ts >= ?",
                     (int(now - window),), 500)
    finally:
        con.close()
    out = {}
    for r in rows:
        v = one(r, now)
        best = out.get(r["token"])
        if best is None or (v["ev_pct"] or -99) > (best["ev_pct"] or -99):
            out[r["token"]] = v
    return out
