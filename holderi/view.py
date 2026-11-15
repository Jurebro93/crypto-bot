"""What the page (card "Listing signali i holderi" under Ostalo + the red badge on the veliki card), the MCP tools
(get_holder_profile, get_listing_signals, get_profitable_holders, submit_exchange_wallet), veliki/prioritet (prio_facts),
the OpenAI critic and output/holderi.md read. Read-only except submit_exchange_wallet (one row in burze_dodane)."""
import json
import os
import time

from holderi import burze, store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_C = {"ts": 0.0, "v": None}
CLS_HR = {"lp": "LP / pool", "burn": "spaljeno", "exchange": "burze", "team": "tim / dev", "insider": "insajderi",
          "whale": "kitovi", "normal": "ostali"}


def prio_facts(path=None, max_age_s=6 * 3600):
    """{mint: {"listing", "listing_score", "listing_ex", "oprez", "block", "why"}} of the newest pass (kv pri), cached
    60 s; {} without holderi.db."""
    if path is None and _C["v"] is not None and time.time() - _C["ts"] < 60:
        return _C["v"]
    v = {}
    con = store.ro(path)
    if con is not None:
        try:
            p = store.kv_get(con, "pri", {}) or {}
            if time.time() - int(p.get("ts") or 0) <= max_age_s:
                v = p.get("rows") or {}
        except Exception:  # noqa: BLE001
            v = {}
        finally:
            con.close()
    if path is None:
        _C.update(ts=time.time(), v=v)
    return v


def _sig_rows(con, days=7, min_score=0, kind=None, limit=50):
    q = ("SELECT id, mint, symbol, ts, kind, exchange, score, reasons, mcap, px, listed, notified, px_1h, px_24h, px_7d, "
         "ctl_1h, ctl_24h, ctl_7d FROM signals WHERE ts >= ? AND score >= ?")
    args = [int(time.time() - float(days) * 86400), float(min_score)]
    if kind:
        q += " AND kind=?"
        args.append(kind)
    q += " ORDER BY ts DESC LIMIT ?"
    args.append(int(limit))
    out = []
    for r in con.execute(q, args):
        d = dict(zip(("id", "mint", "symbol", "ts", "kind", "exchange", "score", "reasons", "mcap", "px", "listed",
                      "notified", "px_1h", "px_24h", "px_7d", "ctl_1h", "ctl_24h", "ctl_7d"), r))
        d["reasons"] = json.loads(d["reasons"] or "[]")
        for h in ("1h", "24h", "7d"):
            p = d.pop(f"px_{h}")
            d[f"ret_{h}_pct"] = round((p / d["px"] - 1) * 100, 2) if p and p > 0 and d["px"] else None
            d[f"control_{h}_pct"] = d.pop(f"ctl_{h}")
        d["exchange_name"] = burze.NAMES.get(d["exchange"], d["exchange"])
        out.append(d)
    return out


def measure(con, min_score=60):
    """{kind: {h: {"n", "mean_pct", "vs_control_pct", "hit"}}} of the measured signals (pre_listing from min_score)."""
    out = {}
    for kind in ("pre_listing", "deposit_sell"):
        k = {}
        for h in ("1h", "24h", "7d"):
            rows = [(b / a - 1) * 100 - (ctl or 0) for a, b, ctl in con.execute(
                f"SELECT px, px_{h}, ctl_{h} FROM signals WHERE kind=? AND score >= ? AND px > 0 AND px_{h} > 0",
                (kind, min_score if kind == "pre_listing" else 30))]
            raw = [(b / a - 1) * 100 for a, b in con.execute(
                f"SELECT px, px_{h} FROM signals WHERE kind=? AND score >= ? AND px > 0 AND px_{h} > 0",
                (kind, min_score if kind == "pre_listing" else 30))]
            k[h] = {"n": len(raw), "mean_pct": round(sum(raw) / len(raw), 2) if raw else None,
                    "vs_control_pct": round(sum(rows) / len(rows), 2) if rows else None,
                    "hit": round(sum(1 for r in raw if r > 0) / len(raw), 2) if raw else None}
        out[kind] = k
    return out


def listing_signals(args=None):
    """MCP get_listing_signals {days (7), min_score (0), kind}."""
    args = args or {}
    con = store.ro()
    if con is None:
        return {"available": False, "signals": [], "why": "holderi.db još ne postoji (prvi prolaz nakon deploya)"}
    try:
        try:
            days = max(0.1, min(60.0, float(args.get("days") or 7)))
            ms = max(0.0, min(100.0, float(args.get("min_score") or 0)))
            lim = max(1, min(200, int(args.get("limit") or 50)))
        except (TypeError, ValueError):
            return {"error": "days / min_score / limit moraju biti brojevi"}
        kind = args.get("kind") if args.get("kind") in ("pre_listing", "deposit_sell") else None
        from holderi import run as hrun
        c = hrun.config()
        return {"available": True, "signals": _sig_rows(con, days, ms, kind, lim), "measure": measure(con, c["min_score"]),
                "min_score": c["min_score"], "listing_bonus_real_entries": bool(c.get("listing_real")),
                "score_definition": ("(size 20 x % ponude do 40 + pošiljatelj tim 20 / insajder 15 / kit 8 / ostali 4 + "
                                     "razina burze 15/10/5 + rast stanja burze do 10 + market maker do 10 + Grok "
                                     "listing_check ±10) x (0,5 + 0,5 x pouzdanost adrese) x (nije listan 1,0 / "
                                     "nepoznato 0,8 / isti simbol 0,6); VEĆ listan = depozit za prodaju (oprez)"),
                "exchange_wallets": burze.seed_counts()}
    finally:
        con.close()


def holder_profile(args=None):
    """MCP get_holder_profile {token}: the newest classified top 20, shares, metrics, the change vs the previous
    snapshot, the moves of 7 days, the caution / listing facts."""
    args = args or {}
    tok = str(args.get("token") or "").strip()
    if not tok:
        return {"error": "token (mint) je obavezan"}
    con = store.ro()
    if con is None:
        return {"error": "holderi.db još ne postoji"}
    try:
        ts = con.execute("SELECT MAX(ts) FROM profile WHERE mint=?", (tok,)).fetchone()[0]
        if not ts:
            return {"token": tok, "available": False, "why": "nema snimke holdera za ovaj token (nije midcap ili još nije "
                                                              "na redu)"}
        prof = store.latest_profiles(con, {tok}, max_age_s=10 ** 9).get(tok) or {}
        rows = store.snap_rows(con, tok, ts)
        pts = store.prev_ts(con, tok, ts)
        from holderi import klasa
        d = klasa.diff(store.snap_rows(con, tok, pts), rows, 0.5) if pts else None
        moves = [dict(zip(("ts", "sender", "sender_cls", "dest", "dest_cls", "exchange", "pct", "kind", "conf"), r))
                 for r in con.execute("SELECT ts, sender, sender_cls, dest, dest_cls, exchange, pct, kind, conf FROM "
                                      "moves WHERE mint=? AND ts >= ? ORDER BY ts DESC LIMIT 40",
                                      (tok, int(time.time()) - 7 * 86400))]
        pri = (store.kv_get(con, "pri", {}) or {}).get("rows", {}).get(tok)
        hist = [dict(zip(("ts", "data"), r)) for r in con.execute(
            "SELECT ts, data FROM profile WHERE mint=? ORDER BY ts DESC LIMIT 14", (tok,))]
        trend = [{"ts": h["ts"], **{k: json.loads(h["data"]).get(k) for k in ("insider_ex", "hhi", "top10_ex")},
                  "exchange": (json.loads(h["data"]).get("shares") or {}).get("exchange")} for h in hist]
        return {"token": tok, "available": True, "ts": ts, "symbol": prof.get("symbol"), "source": prof.get("src"),
                "shares_pct": prof.get("shares"), "insider_ex_pct": prof.get("insider_ex"), "hhi": prof.get("hhi"),
                "top10_ex_pct": prof.get("top10_ex"), "exchanges_pct": prof.get("exchanges"),
                "holders": rows, "diff_vs_previous": d, "moves_7d": moves, "priority_facts": pri, "history": trend,
                "signals": [s for s in _sig_rows(con, 30, 0, None, 200) if s["mint"] == tok][:10]}
    finally:
        con.close()


def profitable_holders(args=None):
    """MCP get_profitable_holders {limit (30)}."""
    args = args or {}
    con = store.ro()
    if con is None:
        return {"available": False, "why": "holderi.db još ne postoji"}
    try:
        try:
            lim = max(1, min(200, int(args.get("limit") or 30)))
        except (TypeError, ValueError):
            lim = 30
        from holderi import profit
        d = profit.summary(con, limit=lim)
        d["available"] = True
        d["note"] = ("diamond = vrijednost >= $25k, drži >= 30 d, >= 2x na poznatom trošku; kupnje bilo kojeg MC-a samo "
                     "se MJERE (trgovanje mikrokapovima ostaje blokirano); follow = ulaz kad >= 2 klastera kupe isti "
                     "token, neto troška pri 0,1 SOL, samo demo mjerenje")
        return d
    finally:
        con.close()


def submit_exchange_wallet(args, who="grok"):
    """MCP submit_exchange_wallet {address, exchange, kind, evidence}: one row in burze_dodane as "nepotvrđeno"
    (confidence at most 0.6); the owner confirms in holderi/burze_vlasnik.json."""
    args = args or {}
    con = store.connect()
    try:
        n = con.execute("SELECT COUNT(*) FROM burze_dodane WHERE who=? AND ts >= ?",
                        (who, int(time.time()) - 3600)).fetchone()[0]
        if n >= 30:
            return {"error": "najviše 30 adresa na sat"}
        try:
            burze.add(con, args.get("address"), args.get("exchange"), args.get("kind") or "hot",
                      min(0.6, float(args.get("confidence") or 0.4)), str(args.get("evidence") or "")[:300], who)
        except (ValueError, TypeError) as e:
            return {"error": str(e)}
        con.commit()
        return {"stored": True, "status": "nepotvrđeno", "note": "vlasnik potvrđuje u holderi/burze_vlasnik.json"}
    finally:
        con.close()


def critic_summary():
    """A small block for the OpenAI critic: signals of 14 days with outcomes, the measurement, cautions, the digest."""
    con = store.ro()
    if con is None:
        return None
    try:
        sig = _sig_rows(con, 14, 20, None, 30)
        pri = (store.kv_get(con, "pri", {}) or {}).get("rows") or {}
        from holderi import profit, run as hrun
        p = profit.summary(con, limit=10)
        profs = store.latest_profiles(con)
        if not sig and not pri and not p["positions_measured"] and not profs:
            return None
        hi = sorted(profs.values(), key=lambda x: -(x.get("insider_ex") or 0))[:8]
        return {"profili_holdera": len(profs),
                "najvise_insajdera": [{"symbol": x.get("symbol"), "insider_ex": x.get("insider_ex"), "hhi": x.get("hhi"),
                                       "burze": (x.get("shares") or {}).get("exchange")} for x in hi],
                "signali_14d": [{k: s.get(k) for k in ("symbol", "kind", "exchange", "score", "listed", "mcap",
                                                       "ret_1h_pct", "ret_24h_pct", "ret_7d_pct", "control_24h_pct")}
                                for s in sig],
                "mjerenje": measure(con, hrun.config()["min_score"]),
                "oprez_blokira": {v.get("symbol") or m[:6]: v.get("block") for m, v in pri.items() if v.get("block")},
                "listing_bonus": {v.get("symbol") or m[:6]: v.get("listing") for m, v in pri.items() if v.get("listing")},
                "listing_bonus_za_pravi_novac": bool(hrun.config().get("listing_real")),
                "profitabilni_holderi": {"izmjereno": p["positions_measured"], "diamond": p["diamonds"],
                                         "sto_kupuju": [{k: r.get(k) for k in ("symbol", "clusters", "holders", "mc")}
                                                        for r in p["digest"][:10]],
                                         "follow_mjerenje": p["follow"]}}
    finally:
        con.close()


def _badge(text):
    return (f'<span style="background:#d32f2f;color:#fff;border-radius:4px;padding:1px 6px;font-weight:700;'
            f'font-size:12px">{text}</span>')


def badges_html(esc, days=3):
    """The red badges of the active pre-listing signals (for the veliki card), "" without any."""
    con = store.ro()
    if con is None:
        return ""
    try:
        from holderi import run as hrun
        ms = hrun.config()["min_score"]
        rows = _sig_rows(con, days, ms, "pre_listing", 10)
    except Exception:  # noqa: BLE001
        return ""
    finally:
        con.close()
    seen, out = set(), []
    for s in rows:
        if (s["mint"], s["exchange"]) in seen:
            continue
        seen.add((s["mint"], s["exchange"]))
        out.append(_badge(f"LISTING? {esc(s['symbol'] or s['mint'][:6])} → {esc(s['exchange_name'])} "
                          f"{s['score']:.0f}"))
    return ("<p>" + " ".join(out) + "</p>") if out else ""


def card_html(sec, item, esc, owner=True):
    """The closed row "Listing signali i holderi" (owner only): the red badges, the signals of 7 days, the cautions,
    the holder classes of the top midcaps, what profitable holders buy."""
    if not owner:
        return ""
    con = store.ro()
    if con is None:
        return ""
    try:
        from holderi import profit, run as hrun
        c = hrun.config()
        sig = _sig_rows(con, 7, 20, None, 30)
        profs = store.latest_profiles(con)
        pri = (store.kv_get(con, "pri", {}) or {}).get("rows") or {}
        p = profit.summary(con, limit=10)
        d = store.kv_get(con, f"cnt:{store.day(time.time())}", {}) or {}
    finally:
        con.close()
    if not profs and not sig:
        return ""
    strong = [s for s in sig if s["kind"] == "pre_listing" and s["score"] >= c["min_score"]]
    meta = (f"{len(strong)} listing signala (7 d) · {len(profs)} profila holdera · "
            f"{sum(1 for v in pri.values() if v.get('block'))} blokirano oprezom · Helius danas "
            f"{d.get('helius') or 0:,.0f}/{int(c['helius_credits_day']):,}")
    badges = "".join(_badge(f"LISTING? {esc(s['symbol'] or s['mint'][:6])} → {esc(s['exchange_name'])} {s['score']:.0f}")
                     + " " for s in strong[:8])
    li = []
    for s in sig[:20]:
        kind = "PRE-LISTING" if s["kind"] == "pre_listing" else "depozit za prodaju"
        out = ", ".join(f"{h} {s[f'ret_{h}_pct']:+.1f} %" for h in ("1h", "24h", "7d") if s.get(f"ret_{h}_pct") is not None)
        li.append(f"<li><b>{esc(s['symbol'] or s['mint'][:6])}</b> {kind} → {esc(s['exchange_name'])}, score "
                  f"{s['score']:.0f} (MC ${(s['mcap'] or 0) / 1e6:,.1f}M): {esc('; '.join(s['reasons'][:4]))}"
                  f"{(' · poslije: ' + out) if out else ''}</li>")
    ca = [f"<li><b>{esc(v.get('symbol') or m[:6])}</b>: {esc(v.get('block') or '; '.join(v.get('why') or []))} "
          f"({v.get('oprez')})</li>" for m, v in pri.items() if v.get("oprez") or v.get("block")]
    top = sorted(profs.values(), key=lambda x: -(x.get("mcap") or 0))[:15]
    hr = []
    for x in top:
        sh = x.get("shares") or {}
        parts = ", ".join(f"{CLS_HR[k]} {sh[k]:.1f} %" for k in ("exchange", "team", "insider", "whale", "lp")
                          if sh.get(k))
        hr.append(f"<li><b>{esc(x.get('symbol') or x['mint'][:6])}</b>: {parts or '—'}; insajderi bez burzi/LP "
                  f"{x.get('insider_ex') or 0:.1f} %, HHI {x.get('hhi') or 0:,.0f}</li>")
    dg = "".join(f"<li><b>{esc(r.get('symbol') or r['token'][:6])}</b>: {r['clusters']} klastera, {r['holders']} "
                 f"holdera, MC ${(r.get('mc') or 0) / 1e6:,.2f}M, likvidnost ${(r.get('liq') or 0) / 1e3:,.0f}k</li>"
                 for r in p["digest"][:10])
    fm = p["follow"].get("24h") or {}
    inner = (f"<p>{badges}</p>" if badges else "") + \
        (f"<p><b>Signali (7 d)</b> — PRE-LISTING = ponuda stiže na burzu koja token još NE lista (od score "
         f"{c['min_score']} glasno + Telegram); depozit na burzu koja ga već lista = oprez:</p>"
         f"<ul>{''.join(li) or '<li>još nema</li>'}</ul>"
         f"<p><b>Oprez</b> (insajderi bez burzi i LP-a > {c['insider_max']:.0f} %, blok od {c['insider_block']:.0f} % "
         f"ili kad tim izbacuje ponudu):</p><ul>{''.join(ca[:20]) or '<li>nema</li>'}</ul>"
         f"<p><b>Klase holdera</b> (top 20, najveći MC):</p><ul>{''.join(hr) or '<li>još nema</li>'}</ul>"
         f"<p><b>Što kupuju profitabilni holderi</b> ({p['diamonds']} diamond od {p['positions_measured']} izmjerenih; "
         f"follow 24 h: n {fm.get('n', 0)}, EV {fm.get('ev_pct', '—')} % neto, samo mjerenje):</p>"
         f"<ul>{dg or '<li>još nema</li>'}</ul>"
         f"<p>Bonus prioriteta za listing ide demo ulazima; za pravi novac "
         f"{'uključen' if c.get('listing_real') else 'isključen (holderi/config.json listing_real)'}.</p>")
    return sec("Listing signali i holderi", meta, inner, sid="holderi")


def write_md(con, now=None, path=None):
    """output/holderi.md: the signals, the cautions, the holder classes, the profitable holders, the cost."""
    now = int(now or time.time())
    from holderi import profit, run as hrun
    c = hrun.config()
    sig = _sig_rows(con, 7, 20, None, 50)
    pri = (store.kv_get(con, "pri", {}) or {}).get("rows") or {}
    profs = store.latest_profiles(con, now=now)
    p = profit.summary(con, now, 15)
    d = store.kv_get(con, f"cnt:{store.day(now)}", {}) or {}
    sc = burze.seed_counts()
    L = [f"# Holderi i listing signali ({time.strftime('%Y-%m-%d %H:%M', time.gmtime(now))} UTC)", "",
         f"Trošak danas: Helius {d.get('helius') or 0:,.0f}/{int(c['helius_credits_day']):,} kredita, RugCheck "
         f"{int(d.get('rc') or 0)} (besplatno), liste burzi {int(d.get('lists') or 0)} (besplatno). Adrese burzi: "
         f"{sc['potvrđeno']} potvrđenih, {sc['nepotvrđeno']} nepotvrđenih ({', '.join(f'{k} {v}' for k, v in sc['po_burzi'].items())}).",
         "", "## Signali (7 d)", ""]
    for s in sig:
        L.append(f"- {time.strftime('%m-%d %H:%M', time.gmtime(s['ts']))} **{s['symbol']}** {s['kind']} → "
                 f"{s['exchange_name']} score {s['score']:.0f}, MC ${(s['mcap'] or 0) / 1e6:,.1f}M: "
                 f"{'; '.join(s['reasons'][:5])}; poslije 1h/24h/7d: {s.get('ret_1h_pct')}/{s.get('ret_24h_pct')}/"
                 f"{s.get('ret_7d_pct')} % (kontrola 24h {s.get('control_24h_pct')} %)")
    if not sig:
        L.append("- još nema")
    L += ["", "## Mjerenje", "", "```", json.dumps(measure(con, c["min_score"]), ensure_ascii=False, indent=1), "```",
          "", "## Oprez", ""]
    L += [f"- {v.get('symbol') or m[:6]}: {v.get('block') or '; '.join(v.get('why') or [])} ({v.get('oprez')})"
          for m, v in pri.items() if v.get("oprez") or v.get("block")] or ["- nema"]
    L += ["", "## Klase holdera (top 30 po MC)", ""]
    for x in sorted(profs.values(), key=lambda x: -(x.get("mcap") or 0))[:30]:
        sh = x.get("shares") or {}
        L.append(f"- {x.get('symbol') or x['mint'][:6]}: " + ", ".join(f"{CLS_HR[k]} {sh.get(k, 0):.1f} %" for k in CLS_HR)
                 + f"; insajderi bez burzi/LP {x.get('insider_ex') or 0:.1f} %, HHI {x.get('hhi') or 0:,.0f}")
    L += ["", "## Što kupuju profitabilni holderi", "",
          f"Diamond {p['diamonds']} od {p['positions_measured']} izmjerenih; follow: {json.dumps(p['follow'])}", ""]
    L += [f"- {r.get('symbol') or r['token'][:6]} ({r['token']}): {r['clusters']} klastera, {r['holders']} holdera, MC "
          f"${(r.get('mc') or 0) / 1e6:,.2f}M, likvidnost ${(r.get('liq') or 0) / 1e3:,.0f}k, prva kupnja "
          f"{time.strftime('%m-%d %H:%M', time.gmtime(r['first_buy_ts']))}" for r in p["digest"]] or ["- još nema"]
    out = path or os.path.join(ROOT, "output", "holderi.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return out
