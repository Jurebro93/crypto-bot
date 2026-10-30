"""Demo trading dashboard: account balance, open positions marked to live DexScreener prices, closed trades.

The page polls /api/paper every REFRESH_S seconds and redraws the account cards and the open-positions table.
run_paper.py itself prices open trades once a minute; here they are re-marked on every poll (DexScreener answers
are cached for 60 s by dexscreener/client.py, so polling does not add API load).
"""
import json
import time

from ui import data
from ui.html import ago, badge, esc, filt, jsonblock, num, scorecell, signed, table, tlink, ts, usd, verdict

REFRESH_S = 15
EXIT = {"stop_loss": "stop loss", "trailing": "trailing stop", "breakeven": "breakeven nakon TP", "time": "isteklo vrijeme",
        "rug": "rug (likvidnost nestala)", "open": "otvoreno"}


def _cfg():
    try:
        from paper import sim
        return sim.load_config()
    except Exception:
        return {}


def _live(mints):
    """mint -> (price, liquidity, url) from the deepest pair, {} if DexScreener is unreachable."""
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
            best[t] = (float(p.get("priceUsd") or 0), liq, p.get("url"))
    return best


def snapshot():
    """Everything the live part of the page shows, as plain JSON-able data."""
    cfg = _cfg()
    trades = data.paper_trades()
    opened = [t for t in trades if t["status"] == "open"]
    closed = [t for t in trades if t["status"] == "closed"]
    live = _live({t["token"] for t in opened})
    rows = []
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
        tp = (cfg.get("tp") or [])[pos.get("tp_done", 0):]
        rows.append({"id": t["id"], "token": t["token"], "symbol": t["symbol"], "opened_ts": t["opened_ts"],
                     "size": t["size_usd"], "entry": entry, "price": price, "move": price / entry - 1 if price and entry else None,
                     "pnl": pnl, "ret": ret, "max": t["max_ret"], "min": t["min_ret"], "left": pos.get("left", 1.0),
                     "sl": None if pos.get("tp_done") else cfg.get("sl"), "next_tp": tp[0][0] if tp else None,
                     "liq": liq, "src": src})
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
px=x=>x==null?'–':x.toPrecision(4),age=t=>{const h=(Date.now()/1e3-t)/3600;return h<1?Math.round(h*60)+' min':h.toFixed(1)+' h'};
function draw(d){
 const c=[[usd(d.equity),'stanje računa (equity)',cls(d.equity-d.bankroll)],[usd(d.cash),'slobodno ($)',''],
  [usd(d.in_use),'u otvorenim pozicijama',''],[f2(d.realized)+' $','ostvareno (zatvoreni)',cls(d.realized)],
  [f2(d.unrealized)+' $','otvoreno (live)',cls(d.unrealized)],[d.open+(d.max_open?' / '+d.max_open:''),'otvorenih pozicija',''],
  [d.wins+' / '+d.closed,'dobitnih zatvorenih','']];
 $('#cards').innerHTML=c.map(([v,l,k])=>`<div class=stat><div class="v ${k}">${v}</div><div class=l>${l}</div></div>`).join('');
 const rows=d.positions.map(p=>`<tr><td><a href="https://dexscreener.com/solana/${p.token}" target=_blank>${p.symbol||p.token.slice(0,6)}</a> <a href="/token/${p.token}" class=mut title="detalji">ⓘ</a></td>
  <td>${age(p.opened_ts)}</td><td class=n>${usd(p.size)}</td><td class=n>${px(p.entry)}</td><td class=n>${px(p.price)}</td>
  <td class="n ${cls(p.move)}">${pc(p.move)}</td><td class="n ${cls(p.pnl)}"><b>${f2(p.pnl)}</b></td><td class="n ${cls(p.ret)}">${pc(p.ret)}</td>
  <td class=n>${pc(p.max)}</td><td class=n>${pc(p.min)}</td><td class=n>${Math.round(p.left*100)}%</td>
  <td class=n>${p.sl==null?'breakeven':pc(p.sl)}</td><td class=n>${p.next_tp==null?'–':pc(p.next_tp)}</td>
  <td class=n>${usd(p.liq)}</td><td class=mut>${p.src}</td></tr>`).join('');
 $('#open').innerHTML=rows||'<tr><td colspan=15 class=empty>Nema otvorenih pozicija.</td></tr>';
 $('#upd').textContent='osvježeno '+new Date(d.ts*1000).toLocaleTimeString()+(d.live?'':' · DexScreener nedostupan, prikaz iz baze');
}
async function poll(){try{const r=await fetch('/api/paper',{cache:'no-store'});if(r.ok)draw(await r.json())}catch(e){$('#upd').textContent='veza prekinuta, pokušavam ponovo…'}}
poll();setInterval(poll,REFRESH*1000);
"""


def page(qs):
    trades = data.paper_trades()
    cands = data.paper_candidates()
    cfg = _cfg()
    b = ["<h1>Demo trading</h1><p class=mut>Trgovanje bez pravog novca (<code>run_paper.py</code>). Otvorene pozicije se "
         f"ovdje preračunavaju po živoj cijeni s DexScreenera svakih {REFRESH_S} s, uz fee i slippage kao pri pravoj "
         "prodaji. Klik na token otvara DexScreener, ⓘ otvara analizu tokena. "
         "<span id=upd class=mut></span></p><div class=grid id=cards></div>"]
    if not (trades or cands):
        b.append("<div class=card>Još nema demo trejdova. Na Renderu ih pokreće <code>start.sh</code> "
                 "(<code>run_paper.py run --scan</code>); lokalno pokreni istu naredbu.</div>")
    b.append("<h2>Otvorene pozicije (live)</h2><div class=tw><table><thead><tr><th>Token</th><th>Otvoreno prije</th>"
             "<th class=n>Ulog</th><th class=n>Ulazna cijena</th><th class=n>Sada</th><th class=n>Pomak</th>"
             "<th class=n>PnL $</th><th class=n>Povrat</th><th class=n>Max</th><th class=n>Min</th><th class=n>Ostalo</th>"
             "<th class=n>Stop loss</th><th class=n>Sljedeći TP</th><th class=n>Likvidnost</th><th>Cijena iz</th></tr>"
             "</thead><tbody id=open><tr><td colspan=15 class=empty>Učitavam…</td></tr></tbody></table></div>")
    if cfg:
        tps = ", ".join(f"+{lv:.0%} prodaj {fr:.0%}" for lv, fr in cfg.get("tp", []))
        b.append(f"<p class=mut>Pravila: ulog ${cfg.get('size_usd')}, stop loss {cfg.get('sl', 0):.0%}, take profit {esc(tps)}, "
                 f"trailing {cfg.get('trail', 0):.0%} od vrha nakon +{cfg.get('trail_after', 0):.0%}, najdulje "
                 f"{cfg.get('max_hold_h')} h. Sve u <a href=/criteria#paper>Kriterijima</a>.</p>")

    closed = [t for t in trades if t["status"] == "closed"]
    b.append(_curve(closed, cfg.get("bankroll_usd", 0)))
    b.append(f'<h2>Zatvoreni trejdovi</h2><div class=flt>{filt("pt", "Filtriraj token, razlog izlaza…")}</div>')
    b.append(table(["Token", "Otvoren", "Zatvoren", ("Trajanje h", "n"), ("Ulog $", "n"), ("PnL $", "n"), ("Povrat", "n"),
                    ("Max", "n"), ("Min", "n"), "Izlaz"],
                   [[tlink(t["token"], t["symbol"]), ts(t["opened_ts"]), ts(t["closed_ts"]),
                     num(((t["closed_ts"] or 0) - t["opened_ts"]) / 3600 if t["closed_ts"] else None, "{:.1f}"),
                     num(t["size_usd"]), signed(t["pnl_usd"]), signed(t["ret"], "{:+.0%}"), signed(t["max_ret"], "{:+.0%}"),
                     signed(t["min_ret"], "{:+.0%}"), esc(EXIT.get(t["exit_reason"] or "", t["exit_reason"] or ""))]
                    for t in closed], "pt", "Još nema zatvorenih trejdova."))

    b.append(f'<h2>Kandidati i odluke</h2><p class=mut>Svaki token koji je bot razmotrio: uzet ili preskočen s razlogom.</p>'
             f'<div class=flt>{filt("pc", "Filtriraj token, razlog…")}</div>')
    b.append(table(["Token", "Viđen", "Porijeklo", ("Hype", "n"), "Odluka", ("Razlog", "wrap"), "Rug", ("Mcap", "n"),
                    ("Likvidnost", "n")],
                   [[tlink(c["token"], c["symbol"]), ago(c["first_ts"]), esc(c["origin"]), scorecell(c["score"]),
                     badge(c["decision"] or "–", "good" if c.get("trade_id") else ""), (esc(c["reason"] or ""), "", "wrap"),
                     verdict(c["rug_verdict"]), usd(c["mcap"]), usd(c["liquidity"])] for c in cands[:500]], "pc",
                   "Još nema kandidata."))
    revs = data.paper_reviews()
    if revs:
        b.append("<h2>Dnevni pregledi</h2>")
        for r in revs[:7]:
            b.append(f"<h3>{esc(r['day'])}</h3>" + jsonblock(r["data"]))
    b.append(f"<script>const REFRESH={REFRESH_S};{JS}</script>")
    return "Demo trading", "".join(b)
