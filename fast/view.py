"""What the Autopilot shows of the fast path and what get_fast_checks answers. Read-only on fast.db (cached CACHE_S).

  card          "Fast path" under "Još" (owner only; nothing while the flag is off): the last TOP_N signals, each with
                every check's result and number (never "nije rađen": a signal still in the queue says "fast_check u
                tijeku", a failed read its CHECK_FAILED reason), seconds from the wallet's buy to the decision, the
                decision and its reason, the source's record, EV, and what happened after (+1/+5/+15/+60 min, max)
  skip_block    the skip pop-up and the token pop-up: the fast_check of that token around that time, as a table
  skip_summary  one line per skipped row of the Autopilot's skip box ("fast_check: SKIP · holderi: top10 62 % > 45 %")
  mcp           MCP get_fast_checks(since, decision, limit, id): 12.11. id = one signal (submit_watch_token's fast_check)
"""
import time

from . import store

CACHE_S = 10
TOP_N = 20
NEAR_S = 900
_CACHE = {}
ICON = {"ok": ("good", "u redu"), "fail": ("bad", "pao"), "error": ("warn", "greška")}
NAMES = {"rug": "Rug", "holders": "Holderi", "flow": "Tok", "price": "Cijena", "source": "Izvor"}
ORDER = ("rug", "holders", "flow", "price", "source")
DEC_HR = {"BUY_PAPER": "KUPI (paper)", "BUY_LIVE": "KUPI (live-eligible)", "SKIP": "PRESKOČI",
          "CHECK_FAILED": "provjera nije uspjela"}   # = fast/estimate.LABEL (11.11., the owner's words)
RULES = ("Every buy of a followed wallet (wallet_follow, insider, pre_shill, group) and every call of a followed "
         "influencer gets five checks at once: rug (mint / freeze authority, LP, RugCheck, top 10, dev, bundle, "
         "snipers), holders (top 20 without pools / CEX, top 10 > 45 % fails, one wallet > 20 %, fresh wallets > 50 %), "
         "fresh flow (5 min buys / sells, buy share < 40 % or < 5 transactions fails, 1 min from PumpPortal when we "
         "have it; wash is a tag: P x 0.5), price (vs the wallet's entry: more than +20 % fails, MC < 30k, liquidity < "
         "$15k, market cap outside the band 30k-5M (FAST_MC_MIN / FAST_MC_MAX: decides first), the source wallet "
         "already selling after its buy; a 4x+ run-up is a tag: P x 0.7, size x 0.5; the lag from the source's entry "
         "in words) and source (closed trades, EV, PnL, tier, copy rank). Also every live candidate of the tool "
         "(convergence, proven wallets, callers, the tool's own live picks). EV = P x 15 % - (1 - P) x 10 % - cost "
         "(2 x fee + 2 x the stake's pool impact), P = (hits + 10 x prior) / (n + 10) x the modifiers: the source's "
         "sample (fast.db outcomes of the source, the copy rank, the callers' +15/-10/45 bench, the Autopilot record: "
         "the first with n >= 10), else its strategy's prior (pooled per kind, >= 20 outcomes, else no edge 48 %), "
         "labelled 'procjena, n izvora < 10'; its 90 % interval is Wilson's on (hits + 10 x prior) of (n + 10), mapped "
         "onto EV. Decision: KUPI (paper) = BUY_PAPER when EV > 0 (0.05 SOL demo); KUPI (live-eligible) = BUY_LIVE only "
         "with run_trade's proof (n >= 10, EV >= +3 % with its 90 % interval above 0) and this signal's EV >= +3 % "
         "(a label: paper mode trades it on the demo account); PRESKOČI = SKIP with the check and its number, or EV "
         "<= 0. An API error is CHECK_FAILED and retried 3x within 30 s, never a skip. "
         "propušteno = SKIP and max >= +20 % within 60 min.")


def _mode():
    try:
        from league import flags
        return flags.mode("fast_path")
    except Exception:  # noqa: BLE001
        return "off"


def recent(limit=TOP_N, path=None, fresh=False):
    t = time.time()
    key = (path or "", limit)
    hit = _CACHE.get(key)
    if hit and not fresh and t - hit[0] < CACHE_S:
        return hit[1]
    con = store.ro(path)
    if con is None:
        rows = []
    else:
        try:
            rows = store.read(con, "1=1", (), order="id DESC", limit=limit)
        finally:
            con.close()
    _CACHE[key] = (t, rows)
    return rows


def clear():
    _CACHE.clear()


def _c(x, nd=1):
    return "–" if x is None else f"{x:.{nd}f}".replace(".", ",")


def _pct(x):
    return "–" if x is None else f"{x:+.1f} %".replace(".", ",")


def pending_text(r):
    """The state of a signal without a final decision, never "nije rađen"."""
    if r.get("status") in ("queued", "running"):
        return "fast_check u tijeku"
    if r.get("status") == "retry":
        return f"CHECK_FAILED, ponovno: {r.get('reason') or ''}"
    return r.get("reason") or "fast_check u tijeku"


def checks_table(r, esc):
    """The five checks of one signal as a small table (status, text, ms)."""
    res = ((r.get("checks") or {}).get("res") or {})
    if not res:
        return f"<p class=mut>{esc(pending_text(r))}</p>"
    rows = []
    for k in ORDER:
        c = res.get(k) or {}
        tone, word = ICON.get(c.get("status"), ("", "–"))
        rows.append(f'<tr><td>{esc(NAMES[k])}</td><td class={tone}>{esc(word)}</td><td>{esc(c.get("text") or "")}</td>'
                    f'<td class=n>{int(c.get("ms") or 0)} ms</td></tr>')
    return "<table class=t>" + "".join(rows) + "</table>"


def _outcome(r):
    o = r.get("out") or {}
    if not o or o.get("max60") is None:
        return None
    s = (f"nakon: 1 min {_pct(o.get('1m'))} · 5 min {_pct(o.get('5m'))} · 15 min {_pct(o.get('15m'))} · 60 min "
         f"{_pct(o.get('60m'))} · najviše {_pct(o.get('max60'))}")
    if r.get("missed"):
        s += " · PROPUŠTENO"
    return s


def head_line(r):
    """"SKIP · 3,2 s od kupnje novčanika · holderi: top10 62 % > 45 %"."""
    if not r.get("decision") or r.get("status") in ("queued", "running"):
        return pending_text(r)
    who = "kupnje novčanika" if r.get("kind") not in ("influencer", "x_call") else "poziva"
    return (f"{r['decision']} · {_c(r.get('latency_s'))} s od {who} · {r.get('reason') or ''}"
            + (f" · {pending_text(r)}" if r.get("status") == "retry" else ""))


def row_inner(r, esc):
    q = r.get("quality") or {}
    b = [checks_table(r, esc)]
    if r.get("decision") and r.get("status") not in ("queued", "running"):
        b.append(f"<p><b>Odluka:</b> {esc(DEC_HR.get(r['decision'], r['decision']))} · {esc(r.get('reason') or '')}</p>")
        base = (r.get("checks") or {}).get("base") or {}
        est = (r.get("checks") or {}).get("est") or {}
        if est:   # 11.11. (fast/estimate): EV with its 90 % interval, P with n and its origin
            from . import estimate
            b.append(f"<p class=mut>{esc(estimate.ev_text(est))} · {esc(estimate.p_text(est))} · trošak "
                     f"{_c(r.get('cost_pct'), 1)} % · prior {esc(base.get('src') or '–')}</p>")
        else:
            b.append(f"<p class=mut>EV {_pct(r.get('ev_pct'))} · P {_c((r.get('p_tp') or 0) * 100, 0)} % · trošak "
                     f"{_c(r.get('cost_pct'), 0)} % · baza {esc(base.get('src') or '–')}</p>")
    if q:
        rate = f"{q['win_rate']:.0%}" if q.get("win_rate") is not None else "–"
        b.append(f"<p class=mut>Izvor: {esc(q.get('label') or q.get('id') or '')} ({esc(q.get('kind_hr') or '')}), "
                 f"zatvorenih {q.get('closed', 0)}, dobitnih {rate}, PnL {q.get('pnl_usd', 0):+.0f} $"
                 + (f", tier {esc(str(q['tier']))}" if q.get("tier") else "")
                 + ("; dokaz za pravi novac: da" if q.get("proof") else "") + "</p>")
    tr = r.get("traded") or {}
    if tr:
        b.append("<p class=mut>Trade: " + esc(
            tr.get("skip") or (f"{tr.get('user')} #{tr.get('trade_id')}, {tr.get('size_sol')} SOL"
                               + (f", zatvoreno {tr.get('pnl_usd'):+.2f} $" if tr.get("closed") else ""))) + "</p>")
    o = _outcome(r)
    if o:
        b.append(f"<p class=mut>{esc(o)}</p>")
    return "".join(b)


def card_html(sec, item, esc, owner=True, path=None, now=None):
    """The closed row "Fast path" under "Još" (see the module text); '' for anybody but the owner or with the flag off."""
    if not owner:
        return ""
    m = _mode()
    if m == "off":
        return ""
    rows = recent(TOP_N, path)
    items = []
    for r in rows:
        name = f"{r.get('symbol') or (r.get('token') or '')[:6]} · {r.get('source_label') or (r.get('source_id') or '')[:8]}"
        val = f"{_c(r.get('latency_s'))} s" if r.get("latency_s") is not None and r.get("decision") else None
        items.append(item(name, head_line(r), row_inner(r, esc), value=val, sub=r.get("decision") or "",
                          iid=f"fp-{r['id']}"))
    lat = [r["latency_s"] for r in rows if r.get("latency_s") is not None and r.get("decision") not in (None, "CHECK_FAILED")]
    meta = (f"mod {m} · zadnjih {len(rows)} signala" + (f", medijan {_c(sorted(lat)[len(lat) // 2])} s" if lat else ""))
    inner = ("".join(items) or "<p class=mut>Još nijedan signal praćenog izvora.</p>") + (
        "<p class=ms-hint>Svaka kupnja praćenog novčanika i svaki poziv praćenog influencera odmah dobije pet provjera "
        "(rug, holderi, tok, cijena prema ulazu novčanika, izvor) i odluku s razlogom i brojem. Greška izvora podataka "
        "je CHECK_FAILED i ponavlja se, nikad preskok. Paper: demo račun kupuje, pravi račun nikad.</p>")
    return sec("Fast path", meta, inner, sid="fast-path", value=str(len(rows)) if rows else None,
               sub="signala" if rows else None)


# ---------- skips and the token pop-up --------------------------------------------------------------------------------

def near(token, ts, path=None, window=NEAR_S):
    """The newest fast_check of the token whose signal or decision is within `window` of ts, or None."""
    con = store.ro(path)
    if con is None:
        return None
    try:
        got = store.read(con, "token=? AND ((sig_ts BETWEEN ? AND ?) OR (decided_ts BETWEEN ? AND ?))",
                         (token, ts - window, ts + window, ts - window, ts + window), order="id DESC", limit=1)
    finally:
        con.close()
    return got[0] if got else None


def skip_block(token, ts, esc, now=None, path=None):
    """HTML for the skip pop-up / token pop-up: the fast_check's decision and its checks; "fast_check u tijeku" for a
    recent skip without one while the flag is on; '' otherwise."""
    r = near(token, int(ts), path)
    now = now or time.time()
    if r is None:
        if now - ts < 600 and _mode() != "off":
            return "<div class=ap-fast><p><b>Fast check:</b> fast_check u tijeku</p></div>"
        return ""
    return ("<div class=ap-fast><p><b>Fast check:</b> " + esc(head_line(r)) + "</p>" + checks_table(r, esc)
            + (f"<p class=mut>{esc(_outcome(r))}</p>" if _outcome(r) else "") + "</div>")


def skip_summary(keys, path=None):
    """{(token, ts): "fast_check: SKIP · 3,2 s · holderi: ..."} for the skip box's rows (one read)."""
    out = {}
    if not keys:
        return out
    con = store.ro(path)
    if con is None:
        return out
    try:
        for tok, ts in keys:
            got = store.read(con, "token=? AND ((sig_ts BETWEEN ? AND ?) OR (decided_ts BETWEEN ? AND ?))",
                             (tok, ts - NEAR_S, ts + NEAR_S, ts - NEAR_S, ts + NEAR_S), order="id DESC", limit=1)
            if got:
                out[(tok, ts)] = "fast_check: " + head_line(got[0])
    finally:
        con.close()
    return out


def token_reason(token, now=None, path=None, window=600):
    """(a fresh reason for the token pop-up's "Za", the fast_check's reason against or None, the row) when a followed
    source's signal on the token came in the last `window` seconds; (None, None, None) otherwise."""
    now = now or time.time()
    con = store.ro(path)
    if con is None:
        return None, None, None
    try:
        got = store.read(con, "token=? AND sig_ts >= ?", (token, int(now - window)), order="id DESC", limit=1)
    finally:
        con.close()
    if not got:
        return None, None, None
    r = got[0]
    from . import sources
    who = "kupio" if r.get("kind") != "influencer" else "zvao"
    za = (f"praćeni izvor {r.get('source_label') or r.get('source_id', '')[:8]} "
          f"({sources.KIND_HR.get(r.get('kind'), r.get('kind'))}) {who} prije {int(now - (r.get('sig_ts') or now))} s")
    against = None
    if r.get("decision") == "SKIP":
        against = f"fast_check: {r.get('reason')}"
    elif r.get("decision") == "CHECK_FAILED":
        against = f"fast_check nije uspio: {r.get('reason')}"
    return za, against, r


def token_block(r, esc):
    """The token pop-up's fast_check block for a row of token_reason."""
    if not r:
        return ""
    return ("<div class=ap-fast><p><b>Fast check:</b> " + esc(head_line(r)) + "</p>" + checks_table(r, esc) + "</div>")


# ---------- MCP ----------------------------------------------------------------------------------------------------------

def _row_out(r):
    c = r.get("checks") or {}
    res = c.get("res") or {}
    return {"id": r["id"], "token": r["token"], "symbol": r.get("symbol"),
            "source": {"kind": r.get("kind"), "id": r.get("source_id"), "label": r.get("source_label"),
                       "follow_id": r.get("follow_id"), "via": r.get("via")},
            "signal_ts": r.get("sig_ts"), "decided_ts": int(r["decided_ts"]) if r.get("decided_ts") else None,
            "latency_s": r.get("latency_s"), "status": r.get("status"), "attempts": r.get("attempts"),
            "decision": r.get("decision"), "reason": r.get("reason") if r.get("decision") else pending_text(r),
            "label": DEC_HR.get(r.get("decision")) if r.get("decision") else None,
            "estimate": c.get("est") or None, "lag": c.get("lag") or None,
            "decided_by": c.get("key"), "ev_pct": r.get("ev_pct"), "p_tp": r.get("p_tp"), "cost_pct": r.get("cost_pct"),
            "base_rate": c.get("base"), "size_sol": r.get("size_sol"), "mode": r.get("mode"),
            "wallet_entry": {"price_usd": (res.get("price") or {}).get("values", {}).get("entry_px"),
                             "price_sol": r.get("entry_sol_px")},
            "price_at_decision": r.get("price0"), "mcap_at_decision": r.get("mcap0"),
            "checks": {k: {kk: (res.get(k) or {}).get(kk) for kk in ("status", "text", "values", "threshold", "ms")}
                       for k in ORDER} if res else None,
            "source_quality": r.get("quality") or None, "outcome": r.get("out") or None, "missed": r.get("missed"),
            "traded": r.get("traded") or None}


def _ids(x):
    """12.11.: id / ids of get_fast_checks -> [int] (None when not given); ValueError on anything but integers."""
    if x in (None, "", []):
        return None
    xs = x if isinstance(x, (list, tuple)) else [x]
    out = []
    for v in xs[:50]:
        if isinstance(v, bool) or not str(v).strip().lstrip("-").isdigit() or int(str(v).strip()) <= 0:
            raise ValueError("id must be a positive integer (the fast_check id submit_watch_token returned)")
        out.append(int(str(v).strip()))
    return out


def _x_calls(con, ids):
    """{signal id: the x_call summary} of the submit_watch_token rows checked by these signals (12.11.)."""
    if not ids:
        return {}
    try:
        q = ",".join("?" * len(ids))
        rows = con.execute(f"SELECT signal_id, id, author, followers, cls, post_id, submitted_ts, entry_status, entry_why, "
                           f"mcap0, measured, net FROM x_calls WHERE signal_id IN ({q}) ORDER BY id", list(ids)).fetchall()
    except Exception:  # noqa: BLE001 - a fast.db without x_calls
        return {}
    out = {}
    for sid, xid, au, fo, cls, pid, ts, es, ew, mc, me, net in rows:
        out.setdefault(sid, []).append({"x_call_id": xid, "author": au, "followers": fo, "class": cls, "post_id": pid,
                                        "submitted_ts": ts, "x_call_scalp": es, "entry_why": ew, "entry_mcap_usd": mc,
                                        "measured": bool(me),
                                        "net_pct": round(net * 100, 2) if net is not None else None})
    return out


def mcp(since=None, decision=None, limit=None, path=None, now=None, ids=None):
    """get_fast_checks: every decision since `since` (default 24 h ago), optionally of one decision, newest first.
    12.11.: ids (id / ids of the tool, e.g. the fast_check id submit_watch_token returned): only those signals, any
    age, with their state (in progress, done, CHECK_FAILED) and the x_call that asked for them."""
    now = int(now or time.time())
    try:
        since = int(since) if since not in (None, "") else now - 86400
        limit = max(1, min(200, int(limit or 50)))
        ids = _ids(ids)
    except (TypeError, ValueError) as e:
        return {"error": str(e) if "id must" in str(e) else "since and limit must be integers"}
    if decision not in (None, "") and decision not in store.DECISIONS:
        return {"error": f"decision must be one of {', '.join(store.DECISIONS)}"}
    out = {"mode": _mode(), "rules": RULES, "since": since, "signals": [], "summary": {}, "report": None}
    if ids:
        out.update(since=None, ids=ids)
    con = store.ro(path)
    if con is None:
        return out
    try:
        if ids:
            where, args = f"id IN ({','.join('?' * len(ids))})", list(ids)
        else:
            where, args = "COALESCE(decided_ts, enq_ts) >= ?", [since]
        if decision:
            where += " AND decision = ?"
            args.append(decision)
        rows = store.read(con, where, args, order="id DESC", limit=limit)
        xc = _x_calls(con, [r["id"] for r in rows])
        for d, n in con.execute("SELECT COALESCE(decision, 'u tijeku'), COUNT(*) FROM signals WHERE "
                                "COALESCE(decided_ts, enq_ts) >= ? GROUP BY 1", (since,)):
            out["summary"][d] = n
        rep = con.execute("SELECT data FROM reports ORDER BY day DESC LIMIT 1").fetchone()
        out["priors"] = store.kv_get(con, "priors")   # 11.11.: the strategy prior per source kind, with its n
    finally:
        con.close()
    import json
    out["signals"] = [dict(_row_out(r), **({"x_calls": xc[r["id"]]} if r["id"] in xc else {})) for r in rows]
    out["count"] = len(rows)
    if ids:
        out["missing_ids"] = [i for i in ids if i not in {r["id"] for r in rows}]
    out["report"] = json.loads(rep[0]) if rep else None
    return out
