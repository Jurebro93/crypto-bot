"""Demo trading dashboard: account balance, open positions marked to live DexScreener prices, closed trades.

The page polls /api/paper every REFRESH_S seconds and redraws the account cards and the open-positions table.
run_paper.py itself prices open trades once a minute; here they are re-marked on every poll (DexScreener answers
are cached for 60 s by dexscreener/client.py, so polling does not add API load).
"""
import json
import time

from paper import sim
from ui import confidence, data, labels
from ui.html import tdesc, ago, badge, esc, filt, num, scorecell, signed, table, th, tlink, ts, usd, verdict

REFRESH_S = 15
EXIT = {"stop_loss": "stop loss", "trailing": "trailing stop", "breakeven": "breakeven nakon TP", "time": "isteklo vrijeme",
        "rug": "rug (likvidnost nestala)", "open": "otvoreno", "stale": "nema rasta (mirovanje)",
        "moonbag_trailing": "moonbag: trailing od vrha", "moonbag_time": "moonbag: isteklo vrijeme"}


def _cfg():
    try:
        from paper import sim
        return sim.load_config()
    except Exception:
        return {}


def market(mints):
    """mint -> (price, liquidity, url, mcap) from the deepest pair, {} if DexScreener is unreachable."""
    if not mints:
        return {}
    try:
        from dexscreener import client
        pairs = client.tokens("solana", list(mints))
    except Exception:
        return {}
    best = {}
    for p in pairs:
        t, liq = p["baseToken"]["address"], (p.get("liquidity") or {}).get("usd") or 0
        if liq >= best.get(t, (0, -1))[1]:
            best[t] = (float(p.get("priceUsd") or 0), liq, p.get("url"), p.get("marketCap") or p.get("fdv"))
    return best


def _live(mints):
    """mint -> (price, liquidity, url) from the deepest pair, {} if DexScreener is unreachable."""
    return {t: v[:3] for t, v in market(mints).items()}


def snapshot():
    """Everything the live part of the page shows, as plain JSON-able data."""
    cfg = _cfg()
    trades = data.paper_trades()
    opened = [t for t in trades if t["status"] == "open"]
    closed = [t for t in trades if t["status"] == "closed"]
    live = _live({t["token"] for t in opened})
    dca_open = {d["trade_id"]: d for d in data.paper_dca() if not d["done"]}
    rows = []
    pend = _pending() if opened else {}
    for t in opened:
        pos = t["state"]
        price, liq, url = live.get(t["token"], (None, None, None))
        pnl, ret, src = t["pnl_usd"] or 0, t["ret"] or 0, "bot"
        if price and pos and cfg:
            try:
                from paper import sim
                r = sim.result(pos, price, liq, {**cfg, **(data.js(t["config"], {}) or {})})
                pnl, ret, src = r["pnl_usd"], r["ret"], "live"
            except Exception:
                pass
        entry = pos.get("entry_px") or t["entry_px"]
        tc = {**(cfg or {}), **(data.js(t["config"], {}) or {})}  # the trade's own rules (learned exits per class)
        tp = (tc.get("tp") or [])[pos.get("tp_done", 0):]
        rows.append({"id": t["id"], "token": t["token"], "symbol": t["symbol"], "name_html": tlink(t["token"], t["symbol"]), "opened_ts": t["opened_ts"],
                     "size": t["size_usd"], "entry": entry, "price": price, "move": price / entry - 1 if price and entry else None,
                     "pnl": pnl, "ret": ret, "max": t["max_ret"], "min": t["min_ret"], "left": pos.get("left", 1.0),
                     "sl": (sim.after_tp_stop(pos, tc) if pos.get("tp_done") else tc.get("sl")) if not pos.get("bag") else None,
                     "next_tp": tp[0][0] if tp else None, "profile": labels.profile(tc.get("exit_profile")),
                     "liq": liq, "src": src, "mc_in": t.get("entry_mcap"),
                     "mc_now": t["entry_mcap"] * price / entry if price and entry and t.get("entry_mcap") else None,
                     "dca": dca_open.get(t["id"], {}).get("reason"), "pending": pend.get(t["id"])})
    bank = cfg.get("bankroll_usd", 0)
    realized = sum(t["pnl_usd"] or 0 for t in closed)
    unreal = sum(r["pnl"] for r in rows)
    in_use = sum((r["size"] or 0) * (r["left"] or 0) for r in rows)
    wins = sum(1 for t in closed if (t["pnl_usd"] or 0) > 0)
    return {"ts": int(time.time()), "bankroll": bank, "realized": round(realized, 2), "unrealized": round(unreal, 2),
            "equity": round(bank + realized + unreal, 2), "cash": round(bank + realized - in_use, 2),
            "in_use": round(in_use, 2), "open": len(rows), "max_open": cfg.get("max_open"), "closed": len(closed),
            "wins": wins, "positions": rows, "live": bool(live) or not opened}


def api(qs):
    return json.dumps(snapshot())


def post(path, form, user=None):
    """POST /paper/izlaz: sell part or all of an open demo position by hand (25/50/100% of what is left). The paper
    loop carries it out at its next price tick (about a minute) with the usual fee and slippage."""
    from paper import store
    try:
        tid, frac = int(form.get("trade", "")), float(form.get("frac", ""))
    except ValueError:
        return "/paper#open"
    if frac not in (0.25, 0.5, 1.0):
        return "/paper#open"
    con = store.connect(data.PAPER_DB)
    try:
        store.request_exit(con, tid, frac, user)
        con.commit()
    finally:
        con.close()
    return "/paper?izlaz=1#open"


def _pending():
    """{trade_id: share of what is left that is waiting to be sold by hand}."""
    import sqlite3
    try:
        con = sqlite3.connect(f"file:{data.PAPER_DB}?mode=ro", uri=True, timeout=5)
        try:
            rows = con.execute("SELECT trade_id, MAX(frac) FROM manual_exits WHERE done_ts IS NULL GROUP BY trade_id")
            return {t: f for t, f in rows}
        finally:
            con.close()
    except sqlite3.Error:
        return {}


def _curve(closed, bank):
    """Inline SVG of the account value after each closed trade."""
    pts = sorted((t["closed_ts"] or t["opened_ts"], t["pnl_usd"] or 0) for t in closed)
    if len(pts) < 2:
        return ""
    vals, v = [bank], bank
    for _, p in pts:
        v += p
        vals.append(v)
    lo, hi = min(vals), max(vals)
    W, H = 600, 120
    xy = [(W * i / (len(vals) - 1), H - H * (y - lo) / max(1e-9, hi - lo)) for i, y in enumerate(vals)]
    by = H - H * (bank - lo) / max(1e-9, hi - lo)
    return (f'<div class=card><b>Stanje računa po zatvorenim trejdovima</b><svg viewBox="0 0 {W} {H}" width="100%" '
            f'height="{H}" preserveAspectRatio=none><line x1=0 x2={W} y1={by:.1f} y2={by:.1f} stroke="currentColor" '
            f'stroke-opacity=.25 stroke-dasharray=4 /><polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in xy)}" '
            f'fill=none stroke="var(--bar)" stroke-width=2 vector-effect=non-scaling-stroke /></svg>'
            f'<span class=mut>start ${bank:,.0f} · sada ${vals[-1]:,.2f} · najniže ${lo:,.2f} · najviše ${hi:,.2f}</span></div>')


JS = """
const $=s=>document.querySelector(s),f2=x=>x==null?'–':(x>=0?'+':'')+x.toFixed(2),pc=x=>x==null?'–':(x>=0?'+':'')+(x*100).toFixed(0)+'%',
cls=x=>x>0?'pos':x<0?'neg':'',usd=x=>x==null?'–':'$'+x.toLocaleString('en',{maximumFractionDigits:2}),
px=x=>x==null?'–':x.toPrecision(4),mc=x=>x==null?'–':x>=1e6?'$'+(x/1e6).toFixed(2)+'M':x>=1e3?'$'+(x/1e3).toFixed(1)+'k':'$'+x.toFixed(0),age=t=>{const h=(Date.now()/1e3-t)/3600;return h<1?Math.round(h*60)+' min':h.toFixed(1)+' h'};
function draw(d){
 const c=[[usd(d.equity),'stanje računa (equity)',cls(d.equity-d.bankroll)],[usd(d.cash),'slobodno ($)',''],
  [usd(d.in_use),'u otvorenim pozicijama',''],[f2(d.realized)+' $','ostvareno (zatvoreni)',cls(d.realized)],
  [f2(d.unrealized)+' $','otvoreno (live)',cls(d.unrealized)],[d.open+(d.max_open?' / '+d.max_open:''),'otvorenih pozicija',''],
  [d.wins+' / '+d.closed,'dobitnih zatvorenih','']];
 $('#cards').innerHTML=c.map(([v,l,k])=>`<div class=stat><div class="v ${k}">${v}</div><div class=l>${l}</div></div>`).join('');
 const rows=d.positions.map(p=>`<tr><td>${p.name_html}</td>
  <td>${age(p.opened_ts)}</td><td class=n>${usd(p.size)}</td><td class=n>${px(p.entry)}</td><td class=n>${px(p.price)}</td><td class=n>${mc(p.mc_in)}</td><td class=n>${mc(p.mc_now)}</td>
  <td class="n ${cls(p.move)}">${pc(p.move)}</td><td class="n ${cls(p.pnl)}"><b>${f2(p.pnl)}</b></td><td class="n ${cls(p.ret)}">${pc(p.ret)}</td>
  <td class=n>${pc(p.max)}</td><td class=n>${pc(p.min)}</td><td class=n>${Math.round(p.left*100)}%</td>
  <td class=n title="pravila: ${p.profile}">${p.sl==null?'moonbag':pc(p.sl)}</td><td class=n>${p.next_tp==null?'–':pc(p.next_tp)}</td>
  <td class=n>${usd(p.liq)}</td><td class=mut>${p.src}</td>
  <td>${p.dca?'<span class="b warn" title="'+p.dca.replace(/"/g,'&quot;')+'">DCA prijedlog</span>':''}</td>
  <td class=nw>${p.pending?'<span class=mut>prodajem '+Math.round(p.pending*100)+'%…</span>':[0.25,0.5,1].map(f=>`<form method=post action=/paper/izlaz style="display:inline" onsubmit="return confirm('Prodati ${f*100}% ostatka ${p.symbol||''} po trenutnoj cijeni?')"><input type=hidden name=trade value=${p.id}><input type=hidden name=frac value=${f}><button class=sm title="prodaj ${f*100}% onoga što je ostalo">${f==1?'Sve':f*100+'%'}</button></form>`).join(' ')}</td></tr>`).join('');
 $('#open').innerHTML=rows||'<tr><td colspan=19 class=empty>Nema otvorenih pozicija.</td></tr>';
 $('#upd').textContent='osvježeno '+new Date(d.ts*1000).toLocaleTimeString()+(d.live?'':' · DexScreener nedostupan, prikaz iz baze');
}
async function poll(){try{const r=await fetch('/api/paper',{cache:'no-store'});if(r.ok)draw(await r.json())}catch(e){$('#upd').textContent='veza prekinuta, pokušavam ponovo…'}}
poll();setInterval(poll,REFRESH*1000);
"""


def _mc(x):
    if not x:
        return "?"
    return f"${x / 1e6:,.2f}M" if x >= 1e6 else f"${x / 1e3:,.1f}k" if x >= 1e3 else f"${x:,.0f}"


def dca_html():
    """Buy-the-dip suggestions on bot trades and what the extra buy would have made (paper/dca.py)."""
    rows = data.paper_dca()
    if not rows:
        return ("<h2>DCA prijedlozi (kupnja u padu)</h2><p class=mut>Još nema signala. Bot ga daje kad je otvorena pozicija "
                "u padu (ali iznad stop lossa), likvidnost je još tu i cijena već odskače od dna. Samo se bilježi, ne kupuje.</p>")
    from paper import dca
    s = dca.summary(rows)
    head = (f"{s['n']} signala" + (f", {s['closed']} sa zatvorenim trejdom: dokup bi dao prosječno {s['avg']:+.0%}, "
                                  f"pogodak {s['win']:.0%}, ukupno {s['pnl']:+.2f} $" if s.get("closed") else ""))
    body = table(["Token", "Kada", ("MC", "n"), ("Pad", "n"), ("Razlog", "wrap"), ("Dokup", "n"), ("Do izlaza", "n"),
                  ("PnL dokupa", "n"), ("Max 24 h", "n"), "Trejd"],
                 [[tlink(r["token"], r["symbol"]), ts(r["ts"]), usd(r["mcap"]), signed(r["dip"], "{:+.0%}"),
                   (esc(r["reason"]), "", "wrap"), usd(r["size_usd"]), signed(r["ret_to_exit"], "{:+.0%}"),
                   signed(r["pnl_usd"]), signed(r["max_24h"], "{:+.0%}"),
                   badge("zatvoren" if r["done"] else "otvoren", "" if r["done"] else "warn")] for r in reversed(rows)])
    return (f"<h2>DCA prijedlozi (kupnja u padu)</h2><p class=mut>{esc(head)}. Signal se samo bilježi; „Do izlaza” je što "
            "bi dokup po cijeni signala donio da je prodan zajedno s trejdom. Dnevni pregled kaže isplati li se.</p>" + body)


def _top(features, n=3):
    return [k for k, v in sorted((features or {}).items(), key=lambda kv: -(kv[1] or 0))[:n] if (v or 0) >= 0.5]


def why_taken(c):
    """Why the bot bought: its decision reason plus the strongest signals at entry, in words."""
    if not c:
        return "<span class=mut>nema zapisa kandidata</span>"
    try:
        from ui.radar import reasons
        why = reasons(c.get("features") or {}, {})[:2]
    except Exception:
        why = []
    out = f"<b>{esc(c.get('reason') or c.get('decision') or '')}</b>"
    if why:
        out += "<ul class=r>" + "".join(f"<li class=good>{esc(w)}</li>" for w in why) + "</ul>"
    if c.get("rug_verdict"):
        out += f"<div class=mut>rug filter pri ulazu: {esc(c['rug_verdict'])}</div>"
    return out


def lesson(t, c):
    """What happened and what the daily review (paper/review.py) does with this kind of outcome."""
    ret, mx = t["ret"] or 0, t["max_ret"] or 0
    top = ", ".join(labels.feat_low(k) for k in _top((c or {}).get("features"))) or "-"
    ex = t["exit_reason"] or ""
    if t["status"] == "open":
        return "<span class=mut>još otvoreno</span>"
    if ret > 0:
        return (f"<span class=pos>Pobjeda {ret:+.0%}</span> ({esc(labels.exit_reason(ex))}). Jaki signali pri ulazu: {esc(top)}. "
                "<span class=mut>Ishod ulazi u učenje težina: signali koji se ponavljaju kod pobjednika dobivaju na težini.</span>")
    if ex == "rug":
        return (f"<span class=neg>Rug {ret:+.0%}.</span> Rug filter je rekao: {esc((c or {}).get('rug_verdict') or 'nije provjeren')}. "
                "<span class=mut>Lekcija: dnevni pregled broji rugove po presudi; kad barem pola od 10+ tokena s istom presudom "
                "rugne, bot sam prestaje kupovati tokene s tom presudom.</span>")
    if ex == "stop_loss" and mx < 0.15:
        late = ((c or {}).get("features") or {}).get("momentum", 0) >= 0.5
        if late:
            return (f"<span class=neg>Stop loss {ret:+.0%}</span>, nikad iznad {mx:+.0%}. Kupili smo nakon velikog skoka u "
                    "zadnjem satu, tj. vrh. <span class=mut>Lekcija: pregled testira viši prag ulaza, a učenje težina "
                    "smanjuje težinu momentuma ako gubitnici redovno imaju jak momentum.</span>")
        return (f"<span class=neg>Stop loss {ret:+.0%}</span>, nikad iznad {mx:+.0%}. Signali ({esc(top)}) nisu predvidjeli rast. "
                "<span class=mut>Lekcija: bot pri dnevnom učenju smanjuje težinu signala koji su jaki kod gubitnika.</span>")
    if mx >= 0.5 and ret <= 0.05:
        return (f"<span class=neg>Profit vraćen:</span> bio {mx:+.0%}, zatvoren {ret:+.0%}. <span class=mut>Lekcija: "
                "bot uči izlaze po klasi tokena: stroži trailing stop ili raniji take profit uzima sam ako su bolji "
                "i na starijim i na novijim podacima.</span>")
    if ex == "time":
        return (f"<span class=neg>Ništa se nije dogodilo</span> ({ret:+.0%} nakon isteka vremena). <span class=mut>Lekcija: "
                "bot pri učenju izlaza testira kraće držanje da novac ne stoji.</span>")
    return (f"<span class=neg>Gubitak {ret:+.0%}</span> ({esc(labels.exit_reason(ex))}). <span class=mut>Ishod ulazi u dnevni "
            "pregled i učenje težina.</span>")


def suggestions():
    """Latest daily review's suggested changes (paper/review.py), newest first."""
    for r in data.paper_reviews():
        sg = (r["data"] or {}).get("suggestions") or []
        if sg or r["data"]:
            return r["day"], sg, (r["data"] or {}).get("mistakes") or []
    return None, [], []


def weights_lines(hours=36):
    """One plain sentence per token class about the last daily re-fit of the hype score weights (learn/)."""
    try:
        import sqlite3
        from learn import store as lstore
        con = sqlite3.connect(f"file:{data.HYPE_DB}?mode=ro", uri=True, timeout=10)
        con.row_factory = sqlite3.Row
        runs = lstore.runs(con, None, 40)
        con.close()
    except Exception:
        return []
    from ui.learnpage import HR, note_hr
    seen, out = set(), []
    for r in runs:
        if r["klasa"] in seen or r["ts"] < time.time() - hours * 3600:
            continue
        seen.add(r["klasa"])
        k = HR.get(r["klasa"], r["klasa"])
        if r["applied"]:
            out.append(f"{k}: bot je ažurirao težine hype ocjene na temelju {r['n']} tokena ({note_hr(r['note'])}).")
        else:
            out.append(f"{k}: težine ostaju iste, {note_hr(r['note'])}.")
    return out


def learned_html():
    """"Što je bot naučio": what the daily review changed by itself, what it only observed, and the weight re-fit.
    Everything in plain words: nothing here asks for a manual step."""
    from ui.labels import plain
    day, sg, _ = suggestions()
    rep = next((r["data"] for r in data.paper_reviews() if r["day"] == day), None) or {}
    auto = rep.get("auto")
    items = []
    if auto:
        items += [f"<li class={'good' if a.get('kind') == 'primijenjeno' else 'bad' if a.get('kind') == 'vraćeno' else ''}>"
                  f"{esc(plain(a.get('text')))}</li>" for a in auto]
    # observations without a rule change (and, in reviews from before automatic changes, the old suggestions)
    for x in sg:
        if x.get("weights") or (auto is not None and x.get("change")):
            continue
        t = plain(x.get("text"))
        if t:
            items.append(f"<li>{esc(('Opažanje: ' if not x.get('change') else 'Primijećeno: ') + t)}</li>")
    wl = weights_lines()
    items += [f"<li>{esc(t)}</li>" for t in wl]
    if not items:
        if not day:
            return ""
        return (f"<p class=mut>Dnevni pregled {esc(day)}: bez promjena. Premalo podataka ili nijedna promjena nije bila "
                "bolja i na starijim i na novijim trejdovima.</p>")
    return (f"<div class=card><b>Što je bot naučio{(' (dnevni pregled ' + esc(day) + ')') if day else ''}:</b>"
            f"<ul class=r>{''.join(items)}</ul><span class=mut>Bot sve promjene radi sam, uz zaštite: mijenja tek kad "
            "ima dovoljno tokena i kad je novo bolje i na starijim i na novijim podacima, a ako se kasnije pokaže lošije, "
            "sam se vraća na staro.</span></div>")


def _calibration(trades, cands):
    rows = confidence.calibration(trades, cands)
    if not any(n for _, n, _, _ in rows):
        return ""
    return ("<h3>Je li confidence točan?</h3><p class=mut>Zatvoreni demo trejdovi po confidence razini pri ulazu. "
            "Ako visoka razina ne pobjeđuje češće od niske, težine confidencea treba mijenjati.</p>"
            + table(["Razina", ("Trejdova", "n"), ("U plusu", "n"), ("Prosječan povrat", "n")],
                    [[esc(n), num(k), num(w, "{:.0%}"), signed(a, "{:+.0%}")] for n, k, w, a in rows]))


def summary_html(limit=5):
    """Demo P&L block for the home page: account, wins and losses with their story, what was learned."""
    cfg = _cfg()
    trades = data.paper_trades()
    if not trades:
        return ("<div class=card>Demo trading još nije napravio nijedan trejd. Kad krene, ovdje će biti stanje računa, "
                "pobjede i porazi s objašnjenjem.</div>")
    cands = {c["trade_id"]: c for c in data.paper_candidates() if c.get("trade_id")}
    closed = [t for t in trades if t["status"] == "closed"]
    opened = [t for t in trades if t["status"] == "open"]
    bank = cfg.get("bankroll_usd", 0)
    real = sum(t["pnl_usd"] or 0 for t in closed)
    unreal = sum(t["pnl_usd"] or 0 for t in opened)
    wins = [t for t in closed if (t["pnl_usd"] or 0) > 0]
    losses = [t for t in closed if (t["pnl_usd"] or 0) <= 0]
    cls = lambda v: "pos" if v > 0 else "neg" if v < 0 else ""  # noqa: E731
    b = ["<div class=grid>"]
    for v, l, k in [(f"${bank + real + unreal:,.2f}", f"demo račun (start ${bank:,.0f})", cls(real + unreal)),
                    (f"{real:+,.2f} $", "ostvareno (zatvoreni)", cls(real)), (f"{unreal:+,.2f} $", f"otvoreno ({len(opened)} poz.)", cls(unreal)),
                    (f"{len(wins)} / {len(losses)}", "pobjede / porazi", ""),
                    (f"{len(wins) / len(closed):.0%}" if closed else "–", "pogodak", "")]:
        b.append(f"<a class=stat href=/paper style='text-decoration:none;color:inherit'><div class='v {k}'>{v}</div><div class=l>{l}</div></a>")
    b.append("</div>")

    def item(t):
        c = cands.get(t["id"], {})
        try:
            from ui.radar import reasons
            why = (reasons(c.get("features") or {}, {}) or [c.get("reason") or ""])[0]
        except Exception:
            why = c.get("reason") or ""
        return (f"<li class={'good' if (t['pnl_usd'] or 0) > 0 else 'bad'}>{tlink(t['token'], t['symbol'])} "
                f"<b class={cls(t['pnl_usd'] or 0)}>{(t['pnl_usd'] or 0):+.2f} $ ({(t['ret'] or 0):+.0%})</b> "
                f"<span class=mut>· {esc(labels.exit_reason(t['exit_reason']))}</span>"
                f"<div style='font-size:12px'><b>Zašto:</b> {esc(why)}</div>"
                f"<div style='font-size:12px'>{lesson(t, c)}</div></li>")
    b.append("<div class=two><div><h3>Najveće pobjede</h3>"
             + ("<ul class=r>" + "".join(item(t) for t in sorted(wins, key=lambda t: -(t["pnl_usd"] or 0))[:limit]) + "</ul>"
                if wins else "<p class=mut>Još nema pobjeda.</p>")
             + "</div><div><h3>Najveći porazi</h3>"
             + ("<ul class=r>" + "".join(item(t) for t in sorted(losses, key=lambda t: t["pnl_usd"] or 0)[:limit]) + "</ul>"
                if losses else "<p class=mut>Još nema poraza.</p>") + "</div></div>")
    b.append(learned_html())
    return "".join(b) + "<p><a href=/paper>Svi demo trejdovi s objašnjenjima →</a></p>"


def _learning_box(trades, cfg):
    """Core vs. exploration trades side by side, and what feeds the learning."""
    ex = (cfg or {}).get("explore") or {}
    groups = {"core": [], "explore": []}
    for t in trades:
        mode = (data.js(t.get("config"), {}) or {}).get("entry_mode") or "core"
        groups.setdefault(mode, []).append(t)
    rows = []
    for mode, label in (("core", "Glavni (score ≥ " + str(cfg.get("min_score")) + ")"),
                        ("explore", "Istraživački (manji ulog)"), ("konv", "Konvergencija izvora"),
                        ("mc100k", "Prvi prelazak 100k $ (A/B, ulaz B)"),
                        ("mc100k2", "Ponovni prelazak 100k $ nakon pada"), ("kol3", "3+ KOL autora u 15 min")):
        g = groups.get(mode) or []
        closed = [t for t in g if t["status"] == "closed"]
        n = len(closed)
        wins = sum(1 for t in closed if (t["ret"] or 0) > 0)
        rows.append([esc(label), num(len(g)), num(n), (f"{wins}/{n}" if n else "–", wins / n if n else -1, "n"),
                     (f"{sum(t['ret'] or 0 for t in closed) / n:+.0%}" if n else "–",
                      sum(t["ret"] or 0 for t in closed) / n if n else -9, "n"),
                     (f"{sum(t['pnl_usd'] or 0 for t in closed):+.2f} $" if n else "–",
                      sum(t["pnl_usd"] or 0 for t in closed), "n")])
    intro = ("<h2>Više tradeova, brže učenje</h2>" + tdesc(
        f"Osim glavnih ulaza (score ≥ {cfg.get('min_score')}, ulog ${cfg.get('size_usd')}), bot radi i "
        f"<b>istraživačke</b> demo ulaze: token ispod praga, ali u gornjih {ex.get('top_pct', '?')}% ocjena zadnja 24 h "
        f"(i barem {ex.get('min_score', '?')}), s ulogom ${ex.get('size_usd', '?')}, najviše {ex.get('max_open', '?')} otvorenih "
        f"i {ex.get('max_per_day', '?')} dnevno. Ne troše nove Helius kredite na rug provjeru (koriste samo postojeći izvještaj) i nikad se ne kopiraju u pravi trading. Svaki ishod, i dobitak i gubitak, "
        "ide u učenje: težine ocjene uče se iz svih skeniranih tokena, izlazi iz putanja svih praćenih tokena, a dnevni "
        "pregled uspoređuje obje skupine.") if ex.get("enabled") else "<h2>Učenje</h2>")
    kc = (cfg or {}).get("konv") or {}
    if kc.get("enabled"):
        intro += tdesc(f"<b>Konvergencija</b>: kad u {kc.get('max_age_min')} min isti token zovu dobri KOL-ovi na X-u, dobri "
                       f"Telegram kanali i/ili ga kupuju KOL novčanici (skor konvergencije ≥ {kc.get('min_score')}), bot "
                       f"ulazi malim ulogom prije gomile. Prodaje {kc.get('tp', [[0, 0]])[0][1]:.0%} na "
                       f"+{kc.get('tp', [[0, 0]])[0][0]:.0%}, izlazi nakon {kc.get('stale_min')} min ako nema "
                       f"+{kc.get('stale_ret', 0):.0%}, i odmah ako KOL novčanik koji je kupio počne prodavati. "
                       "Samo demo dok ne pokaže dobit.")
    out = intro + table(["Vrsta ulaza", ("Ukupno", "n"), ("Zatvoreno", "n"), ("Dobitnih", "n"), ("Prosjek", "n"),
                         ("PnL", "n")], rows)
    try:
        import sqlite3
        from paper import arms
        con = sqlite3.connect(f"file:{data.PAPER_DB}?mode=ro", uri=True, timeout=10)
        arm_rows, reasons = arms.report(con)
        con.close()
    except Exception:
        arm_rows, reasons = [], {}
    if arm_rows:
        out += ("<h3>Krakovi: koja kombinacija izvora radi</h3>" + tdesc(
            "Krak = izvori koji su pokrenuli istraživački ili konvergencijski ulaz (x = KOL-ovi na X-u, tg = Telegram, "
            "chain = KOL novčanici, pump = pump.fun, dex = DexScreener) i sesija. Krakovi koji gube dobivaju sve "
            "manje ulaza, ali nikad nula.") + table(["Krak", ("Tradeova", "n"), ("Dobitnih", "n"), ("Prosjek", "n"),
                                                     ("PnL", "n")],
            [[esc(a), num(n), num(w), (f"{avg:+.0%}", avg, "n"), (f"{p:+.2f} $", p, "n")] for a, n, w, avg, p in arm_rows]))
    if reasons:
        out += "<h3>Zašto gubimo</h3>" + table(["Razlog", ("Tradeova", "n")],
                                              [[esc(k), num(v)] for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])])
    return out


def _pct(x):
    return "–" if x is None else f"{x:+.0%}"


def rules_html(now=None):
    """What changed on 1.11. ("Prijedlozi za bolji algoritam") and how each change is doing, in plain words."""
    import sqlite3
    from paper import rules
    now = now or time.time()
    cfg = _cfg()
    R = rules.config(cfg)
    st = rules.load()
    g = R["gate"]
    out = ["<h2>Nova pravila ulaza (od 1. 11.)</h2>" + tdesc(
        "Pet prijedloga iz jutarnjeg izvještaja ugrađeno je u bota. Sve se uči i mjeri samo, ništa se ne podešava ručno.")]
    items = [
        f"<b>Tvrdi filter protiv rugova.</b> Bot ne ulazi ako token nije prošao T0 provjeru (token izvan pump.funa mora biti "
        f"stvarno provjeren), ako je likvidnost ispod {g['min_liq']:,.0f} $, ako je pool veći od {g['max_liq_mcap']:.0%} "
        "vrijednosti tokena (lažni pool, tako su izgledali noćni rugovi na −100%), ako je cijena iznad 1 $ uz mali supply "
        "(tokenizirane dionice) ili ako mu je volumen pao ispod 20% najboljeg sata. Konvergencija samo iz novčanika, bez "
        "ijednog posta, traži barem 6 novčanika. Token s rug ocjenom „visok rizik” dobiva samo mali ulog.".replace(",", "."),
        "<b>Ulaz na prvom prelasku 100k $.</b> Uz uobičajene ulaze (A) bot sad ulazi i kad token prvi put prijeđe 100k $ "
        f"vrijednosti uz prolaz T0 (B), istim ulogom. Ako nakon izlaza token padne ispod 80k $ i ponovno prijeđe 100k $, bot ulazi još jednom (mjeri se zasebno). Kad obje strane imaju barem {R['ab']['min_n']} zatvorenih tradeova, "
        f"bolja dobiva većinu ulaza, a slabija {R['ab']['keep_frac']:.0%} da se usporedba nastavi. Provjerava se svaki dan.",
        "<b>Simulacija izlaza bliža stvarnosti.</b> Svaka kupnja i prodaja plaća proklizavanje "
        f"({cfg.get('slip', 0):.0%}), stop na grubim povijesnim podacima puni se tamo gdje bi ga minutna provjera stvarno "
        "uhvatila (izmjereno na našim demo stopovima), naši live podaci nose barem pola ocjene, a nova pravila izlaza "
        "moraju biti bolja i kad se izbace najveći pogoci.",
        f"<b>Okidač: {R['kol3']['authors']}+ različita KOL autora u {R['kol3']['window_min']} min.</b> Poseban mali demo "
        "ulaz; botovi-skeneri koji objave svaki novi token ne broje se. Točnost se mjeri po sesiji; u sesiji gdje gubi "
        "dobiva samo mali dio ulaza.",
        "<b>Ulog po sesiji.</b> Iz zadnjih 7 dana demo tradeova bot računa faktor dobiti za Aziju, Europu i Ameriku. "
        "Sesija koja gubi dobiva manji ulog (75% ili 50%), a ako jako gubi pauzu (uz mali dio ulaza za mjerenje). "
        "Mijenja se najviše jedan korak dnevno i vraća se sam kad se rezultati poprave.",
    ]
    out.append("<ol>" + "".join(f"<li style='margin-bottom:6px'>{x}</li>" for x in items) + "</ol>")
    try:
        con = sqlite3.connect(f"file:{data.PAPER_DB}?mode=ro", uri=True, timeout=10)
    except Exception:
        return "".join(out)
    try:
        gs = (st.get("since") or {}).get("gate") or (st.get("since") or {}).get("ab")
        rows = []
        if gs:
            for r in rules.rug_share(con, gs):
                rows.append([esc(r["label"]), num(r["n"]), num(r["rugs"]),
                             (f"{r['share']:.0%}" if r["share"] is not None else "–", r["share"] or 0, "n")])
            sh = rules.gate_shadow(con, gs)
            out.append("<h3>Rugovi prije i poslije filtra</h3>" + tdesc(
                "Udio zatvorenih demo tradeova koji su završili kao rug (likvidnost nestala ili −90% i gore); usporedba "
                "zadnjih 7 dana prije filtra i svega nakon njega.") + table(
                ["Razdoblje", ("Tradeova", "n"), ("Rugova", "n"), ("Udio", "n")], rows)
                + (f"<p class=mut>Filtar je odbio {sh['n']} tokena; {sh['collapsed']} od njih se kasnije srušilo "
                   f"(−70% ili nestala likvidnost), što bi bio gubitak.</p>" if sh["n"] else ""))
        ab = st.get("ab") or {}
        if ab:
            w = ab.get("winner")
            out.append("<h3>A/B: uobičajeni ulaz ili prvi prelazak 100k $</h3>" + tdesc(
                "Povrat po tradeu (najviše +300% po tradeu, da jedan pogodak ne odluči), od početka testa.") + table(
                ["Ulaz", ("Zatvoreno", "n"), ("Dobitnih", "n"), ("Prosjek", "n"), ("Medijan", "n")],
                [[esc(lab) + (" ✓" if w == k else ""), num(ab.get(k, {}).get("n", 0)),
                  (f"{ab[k]['win']:.0%}" if ab.get(k, {}).get("n") else "–", (ab.get(k) or {}).get("win", -1), "n"),
                  (_pct((ab.get(k) or {}).get("mean")), (ab.get(k) or {}).get("mean", -9), "n"),
                  (_pct((ab.get(k) or {}).get("median")), (ab.get(k) or {}).get("median", -9), "n")]
                 for k, lab in (("A", "A: uobičajeni ulaz"), ("B", "B: prvi prelazak 100k $"))])
                + f"<p class=mut>{'Pobjednik: ' + ('B (100k $)' if w == 'B' else 'A (uobičajeni)') if w else 'Još nema pobjednika: obje strane trebaju barem ' + str(R['ab']['min_n']) + ' zatvorenih tradeova i bolji prosjek i medijan u obje polovice.'}</p>")
        k3 = rules.by_session(con, "kol3", 14, now)
        ss = (st.get("sessions") or {}).get("by") or {}
        srows = []
        for s in ("asia", "eu", "us"):
            a = ss.get(s) or {}
            k = k3.get(s) or {}
            f = a.get("factor", 1.0)
            srows.append([esc(rules.SESS_HR[s]), num(a.get("n", 0)),
                          (f"{a['win']:.0%}" if a.get("win") is not None else "–", a.get("win") or 0, "n"),
                          (str(a.get("pf")) if a.get("pf") is not None else "–", a.get("pf") or 0, "n"),
                          ("pauza" if f == 0 else f"{f:.0%}", f, "n"),
                          (f"{k['win']:.0%} od {k['n']}" if k else "–", k.get("win", -1), "n")])
        out.append("<h3>Sesije: ulog i točnost okidača 3 KOL-a</h3>" + tdesc(
            "Zadnjih 7 dana zatvorenih demo tradeova po sesiji (UTC). Faktor dobiti = zbroj dobitaka / zbroj gubitaka "
            "(ispod 1 znači gubitak). Ulog se primjenjuje na sve nove ulaze u toj sesiji.") + table(
            ["Sesija", ("Tradeova", "n"), ("Dobitnih", "n"), ("Faktor dobiti", "n"), ("Ulog", "n"),
             ("Okidač 3 KOL-a (14 dana)", "n")], srows))
    except Exception as e:  # noqa: BLE001 - never break the page
        out.append(f"<p class=mut>Statistika novih pravila trenutno nije dostupna ({esc(type(e).__name__)}).</p>")
    finally:
        con.close()
    try:
        from exits import profiles
        real = profiles.load().get("reality") or {}
        if real:
            out.append("<p class=mut>Simulacija izlaza: " + (
                f"na {real['n']} naših demo stopova {real['p_caught']:.0%} ih je minutna provjera uhvatila blizu stopa, "
                f"prosječno {abs(real['gap']):.0%} ispod njega" if real.get("measured") else
                f"premalo naših stopova za mjerenje ({real.get('n', 0)}), vrijedi pretpostavka: 70% uhvaćeno, 5% ispod stopa")
                + f"; proklizavanje {real.get('slip', 0):.0%} na svakoj kupnji i prodaji.</p>")
    except Exception:
        pass
    hist = [h for h in (st.get("history") or [])][-6:]
    if hist:
        out.append("<h3>Što je bot sam promijenio</h3><ul>" + "".join(
            f"<li>{esc(time.strftime('%d.%m. %H:%M', time.gmtime(h['ts'])))} UTC: {esc(h['text'])}</li>" for h in reversed(hist))
            + "</ul>")
    return "".join(out)


def page(qs):
    trades = data.paper_trades()
    cands = data.paper_candidates()
    cfg = _cfg()
    b = ["<h1>Demo trading</h1><p class=mut>Trgovanje bez pravog novca. Otvorene pozicije se "
         f"ovdje preračunavaju po živoj cijeni s DexScreenera svakih {REFRESH_S} s, uz fee i slippage kao pri pravoj "
         "prodaji. Klik na token otvara DexScreener, ⓘ otvara analizu tokena. "
         "<span id=upd class=mut></span></p><div class=grid id=cards></div>"]
    b.append(_learning_box(trades, cfg))
    try:
        b.append(rules_html())
    except Exception:
        pass
    if not (trades or cands):
        b.append("<div class=card>Još nema demo trejdova. Bot ih otvara sam čim neki token prođe pravila ulaza.</div>")
    b.append("<h2>Otvorene pozicije (live)</h2>" + tdesc("Demo pozicije koje su još otvorene; cijena se osvježava s DexScreenera svakih 15 s. Stop loss i sljedeći TP pokazuju kad će bot prodati. Gumbi u stupcu Ručni izlaz prodaju 25%, 50% ili sve što je ostalo: bot to izvrši u idućoj minuti po živoj cijeni, uz isti fee i slippage. Ručno prodani tradeovi ne ulaze u učenje izlaza i krakova.") + "<div class=tw><table><thead><tr>"
             + "".join(th(*h) for h in [("Token", ""), ("Otvoreno prije", ""), ("Ulog", "n"), ("Ulazna cijena", "n"),
                                        ("Sada", "n"), ("MC ulaz", "n"), ("MC sada", "n"), ("Pomak", "n"), ("PnL $", "n"), ("Povrat", "n"), ("Max", "n"),
                                        ("Min", "n"), ("Ostalo", "n"), ("Stop loss", "n"), ("Sljedeći TP", "n"),
                                        ("Likvidnost", "n"), ("Cijena iz", ""), ("DCA", ""), ("Ručni izlaz", "")])
             + "</tr></thead><tbody id=open><tr><td colspan=19 class=empty>Učitavam…</td></tr></tbody></table></div>")
    if cfg:
        try:
            from exits import learn as xl
            rules = xl.describe(xl.params_of(cfg))
        except Exception:
            rules = ""
        b.append(f"<p class=mut>Ulog ${cfg.get('size_usd')}. Izlaze bira naučeni skup pravila klase tokena (stranica "
                 f"<a href=/izlazi>Izlazi</a>); bez naučenog skupa vrijedi osnovni: {esc(rules)}. "
                 "Sve u <a href=/criteria#paper>Kriterijima</a>.</p>")

    closed = [t for t in trades if t["status"] == "closed"]
    b.append(_curve(closed, cfg.get("bankroll_usd", 0)))
    b.append(f'<h2>Zatvoreni trejdovi</h2><div class=flt>{filt("pt", "Filtriraj token, razlog izlaza…")}</div>')
    by_trade = {c["trade_id"]: c for c in cands if c.get("trade_id")}
    rows = []
    for t in closed:
        c = by_trade.get(t["id"], {})
        conf, _ = confidence.for_candidate(c) if c else (None, [])
        hold = ((t["closed_ts"] or 0) - t["opened_ts"]) / 3600 if t["closed_ts"] else 0
        rows.append([(f'{tlink(t["token"], t["symbol"])}<div class=mut style="font-size:12px">{ts(t["opened_ts"])[0]} · '
                      f'{hold:.1f} h · MC {_mc(t.get("entry_mcap"))} → {_mc(t.get("exit_mcap"))}</div>', t["opened_ts"], ""),
                     (f'{signed(t["pnl_usd"])[0]}<div style="font-size:12px">{signed(t["ret"], "{:+.0%}")[0]} · max '
                      f'{(t["max_ret"] or 0):+.0%}</div><div class=mut style="font-size:12px">'
                      f'{esc(labels.exit_reason(t["exit_reason"]))}</div>', t["pnl_usd"] or 0, "n"),
                     (confidence.badge_html(conf), conf, "n") if conf is not None else "–",
                     (why_taken(c), "", "wrap"), (lesson(t, c), "", "wrap")])
    b.append(tdesc('Svaki zatvoreni demo trejd: koliko je zaradio ili izgubio, kolika je bila procjena pri ulazu, zašto je uzet i što alat iz ishoda uči.') + table(["Token", ("PnL $", "n"), ("Confidence pri ulazu", "n"), ("Zašto uzet", "wrap"), ("Ishod i lekcija", "wrap")],
                   rows, "pt", "Još nema zatvorenih trejdova."))
    b.append(_calibration(trades, cands))
    b.append(dca_html())

    b.append(f'<h2>Kandidati i odluke</h2><p class=mut>Svaki token koji je bot razmotrio: uzet ili preskočen s razlogom.</p>'
             f'<div class=flt>{filt("pc", "Filtriraj token, razlog…")}</div>')
    b.append(table(["Token", "Viđen", "Porijeklo", ("Hype", "n"), "Odluka", ("Razlog", "wrap"), "Rug", ("Mcap", "n"),
                    ("Likvidnost", "n")],
                   [[tlink(c["token"], c["symbol"]), ago(c["first_ts"]), esc(labels.source(c["origin"])), scorecell(c["score"]),
                     badge(labels.decision(c["decision"]), "good" if c.get("trade_id") else ""), (esc(labels.reason(c["reason"])), "", "wrap"),
                     verdict(c["rug_verdict"]), usd(c["mcap"]), usd(c["liquidity"])] for c in cands[:500]], "pc",
                   "Još nema kandidata."))
    revs = data.paper_reviews()
    if revs:
        b.append("<h2>Dnevni pregledi: što je alat naučio</h2>")
        for r in revs[:7]:
            d = r["data"] or {}
            sm = d.get("summary") or {}
            b.append(f"<h3>{esc(r['day'])}</h3><p>Zatvoreno {sm.get('closed', 0)}, PnL {sm.get('pnl_usd', 0):+.2f} $"
                     + (f", pogodak {sm['win_rate']:.0%}" if sm.get("win_rate") is not None else "")
                     + f"; preskočeni koji bi izgubili: {d.get('saved', 0)} (ušteda {d.get('saved_pnl', 0):+.0f} $).</p>")
            if d.get("mistakes"):
                b.append("<b>Greške:</b><ul class=r>" + "".join(f"<li class=bad>{esc(labels.plain(m['text']))}</li>" for m in d["mistakes"]) + "</ul>")
            if d.get("missed"):
                b.append("<b>Propušteni pobjednici:</b><ul class=r>" + "".join(
                    f"<li class=warn>{tlink(m['token'], m['symbol'])} do {m['raw_max']:+.0%}, preskočen: {esc(labels.reason(m['reason']))}</li>"
                    for m in d["missed"]) + "</ul>")
            done = [x for x in d.get("auto") or [] if x.get("text")]
            obs = [labels.plain(x.get("text")) for x in d.get("suggestions") or []
                   if not x.get("weights") and not (d.get("auto") is not None and x.get("change"))]
            b.append("<b>Što je bot promijenio ili primijetio:</b><ul class=r>"
                     + ("".join(f"<li>{esc(labels.plain(x['text']))}</li>" for x in done)
                        + "".join(f"<li>{esc(t)}</li>" for t in obs if t)
                        or "<li class=mut>ništa (premalo podataka ili ništa nije bilo bolje)</li>") + "</ul>")
    b.append(f"<script>const REFRESH={REFRESH_S};{JS}</script>")
    return "Demo trading", "".join(b)
