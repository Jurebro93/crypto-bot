"""The "Prijedlog za danas" box on top of Tokeni, Influenceri and Novčanici (Jure 7.11.): the first thing a user
sees is what the tool concluded from everything it analysed and, concretely, where to put money today and why.
The tables come after. Each pick carries the market cap at the moment of the analysis; the page asks
/api/prijedlog every minute for the live market cap and says "OK" / "pričekaj povlačenje" (the user may read the
page minutes later, when a $50k entry is already $70k)."""
import json
import sqlite3
import time

from ui import data
from ui.html import esc, tlink, usd, wlink


def _kol_db():
    from kol import store as _ks
    return _ks.DB

PULL_X = 1.25    # above this multiple of the analysed market cap: wait for a pullback
DROP_X = 0.80    # below: falling, do not chase
MAX_AGE_S = 6 * 3600
TARGET = 0.30    # "chance of +30 %": share of measured calls in the same market-cap band that reached +30 % in 24 h


def _band(m):
    m = m or 0
    return ("<50k" if m < 5e4 else "50–100k" if m < 1e5 else "100–300k" if m < 3e5 else "300k–1M" if m < 1e6
            else "1–10M" if m < 1e7 else "10M+")


def _band_lo_hi(b):
    return {"<50k": (0, 5e4), "50–100k": (5e4, 1e5), "100–300k": (1e5, 3e5), "300k–1M": (3e5, 1e6),
            "1–10M": (1e6, 1e7), "10M+": (1e7, 1e99)}[b]


def chances(days=14):
    """{band: (share of calls with max24 >= TARGET, n)} from kol.db measured calls (the retro of 7.11.)."""
    out = {}
    try:
        rows = data.q(_kol_db(), "SELECT mcap0, max24 FROM calls WHERE max24 IS NOT NULL AND kind IN ('call','bot') "
                                   "AND ts >= ? AND source NOT IN ('kol_win')", (int(time.time() - days * 86400),))
    except Exception:  # noqa: BLE001
        rows = []
    by = {}
    for r in rows:
        by.setdefault(_band(r["mcap0"]), []).append(r["max24"] or 0)
    for b, xs in by.items():
        if len(xs) >= 30:
            out[b] = (sum(1 for x in xs if x >= TARGET) / len(xs), len(xs))
    return out


def analysed(now=None):
    """What the tool looked at in the last 24 h, in plain numbers."""
    now = now or time.time()
    since = int(now - 86400)
    n = {}
    try:
        n["tokena"] = data.q(data.HYPE_DB, "SELECT COUNT(DISTINCT token) c FROM hype_signals WHERE ts >= ?", (since,))[0]["c"]
    except Exception:  # noqa: BLE001
        n["tokena"] = 0
    try:
        n["poziva"] = data.q(_kol_db(), "SELECT COUNT(*) c FROM calls WHERE ts >= ? AND kind='call'", (since,))[0]["c"]
        n["kolova"] = data.q(_kol_db(), "SELECT COUNT(*) c FROM kols")[0]["c"]
    except Exception:  # noqa: BLE001
        n["poziva"], n["kolova"] = 0, 0
    try:
        n["novcanika"] = data.q(data.WALLET_DB, "SELECT COUNT(*) c FROM wallets WHERE score IS NOT NULL")[0]["c"]
    except Exception:  # noqa: BLE001
        n["novcanika"] = 0
    try:
        from strat import store as sstore
        con = sstore.ro()
        if con is not None:
            try:
                n["tradeova"] = con.execute("SELECT COUNT(*) FROM positions WHERE seen_ts >= ? AND status != 'skip'",
                                            (since,)).fetchone()[0]
            finally:
                con.close()
    except Exception:  # noqa: BLE001
        n["tradeova"] = 0
    return n


def token_picks(now=None, n=3, rows=None, status=None, ch=None):
    """Up to n tokens to enter now, best Šansa/confidence first. Jure 7.11.: "danas ništa" is useless, so the
    picks are graded instead of hidden: 'visoka' = passes every filter and is fresh (<= 6 h); 'srednja' = passes
    but is older (<= 24 h); 'niska' = below the confidence bar but not rugged, with a live pair. The stake shrinks
    with the grade. Each: token, symbol, mcap0 (at analysis), ts0, conf, why (list), chance, band, razina."""
    from ui import overview
    now = now or time.time()
    rows = rows if rows is not None else overview.token_rows()
    if status is None:
        try:
            from hype import tokenstatus
            status = tokenstatus.read(data.HYPE_DB)
        except Exception:  # noqa: BLE001
            status = {}
    ch = ch if ch is not None else chances()
    out = []
    ranked = sorted(rows, key=overview._rank, reverse=True)
    for razina, ok in (("visoka", lambda r: overview.relevant(r) and now - (r["last_seen"] or 0) <= MAX_AGE_S),
                       ("srednja", lambda r: overview.relevant(r) and now - (r["last_seen"] or 0) <= 24 * 3600),
                       ("niska", lambda r: not overview.bad(r) and (r.get("conf") or 0) >= 20
                        and now - (r["last_seen"] or 0) <= 24 * 3600)):
        for r in ranked:
            if len(out) >= n:
                break
            if any(p["token"] == r["token"] for p in out) or not ok(r):
                continue
            p = _pick(r, status, ch, now)
            if p:
                p["razina"] = razina
                out.append(p)
        if len(out) >= n:
            break
    return out


def _pick(r, status, ch, now):
    if True:
        st = status.get(r["token"])
        if st and not st.get("has_pair"):
            return None
        mcap = (st or {}).get("mcap") or r.get("mcap")
        if not mcap or mcap < 30_000:
            return None
        try:
            from ui.radar import reasons
            why = reasons(r["features"], r["det"])[:3]
        except Exception:  # noqa: BLE001
            why = []
        if not why:
            why = [t for p, t in r.get("conf_parts") or [] if p > 0][:3]
        b = _band(mcap)
        return {"token": r["token"], "symbol": r["symbol"], "mcap0": mcap, "ts0": int(r["last_seen"] or now),
                "conf": r.get("conf"), "why": why, "band": b, "chance": ch.get(b)}


def kol_picks(now=None, n=3):
    """KOLs worth following today: proven score, enough measured calls, and what they called in the last 6 h."""
    now = now or time.time()
    try:
        from ui.kol import _cfg
        good = _cfg().get("good_score", 60)
    except Exception:  # noqa: BLE001
        good = 60
    try:
        kols = data.q(_kol_db(), "SELECT handle, score, followers, stats FROM kols WHERE score IS NOT NULL "
                                   "ORDER BY score DESC LIMIT 40")
    except Exception:  # noqa: BLE001
        return []
    out = []
    proven = []
    for k in kols:
        try:
            s = json.loads(k["stats"] or "{}")
        except ValueError:
            s = {}
        k = dict(k)
        k["_s"] = s
        if (s.get("measured") or 0) >= 5 and (k["score"] or 0) >= good:
            proven.append(k)
    # proven accounts first; with fewer than n of them, the best on trial with at least 3 measured calls fill in
    rest = [k for k in kols if (dict(k).get("stats") and json.loads(k["stats"] or "{}").get("measured", 0) >= 3)
            and k["handle"] not in {p["handle"] for p in proven}]
    for k in list(proven) + [dict(x, _s=json.loads(x["stats"] or "{}"), _trial=True) for x in rest]:
        s = k["_s"]
        last = data.q(_kol_db(), "SELECT token, symbol, ts, mcap0 FROM calls WHERE handle=? AND kind='call' "
                                   "ORDER BY ts DESC LIMIT 1", (k["handle"],))
        last = last[0] if last else None
        out.append({"handle": k["handle"], "score": k["score"], "followers": k["followers"], "hit": s.get("hit_rate"),
                    "measured": s.get("measured"), "last": dict(last) if last else None, "trial": bool(k.get("_trial")),
                    "fresh": bool(last and now - (last["ts"] or 0) <= MAX_AGE_S)})
        if len(out) >= n:
            break
    return out


def wallet_picks(now=None, n=2):
    """Wallets to copy today (ui/preporuka ranking) and their freshest buy."""
    try:
        from ui import preporuka
        ranked = preporuka.rank_wallets(data.wallets(scored_only=True), preporuka.copies_from_strat())
    except Exception:  # noqa: BLE001
        return []
    if not ranked:   # nobody passes the copy bar: the best by closed trades and win rate, graded 'niska'
        try:
            ws = [w for w in data.wallets(scored_only=True) if (w.get("stats") or {}).get("closed", 0) >= 3
                  and (w.get("stats") or {}).get("closed_pnl_sol", 0) > 0]
            ws.sort(key=lambda w: (-(w["stats"].get("win_rate") or 0), -(w["stats"].get("closed") or 0)))
            ranked = [(w, {"tier": "niska"}) for w in ws[:n]]
        except Exception:  # noqa: BLE001
            ranked = []
    out = []
    for w, r in ranked[:n]:
        last = None
        try:
            rows = data.q(data.HYPE_DB, "SELECT mint, ts FROM chain_trades WHERE wallet=? AND side='buy' ORDER BY ts DESC LIMIT 1",
                          (w["wallet"],))
            last = dict(rows[0]) if rows else None
        except Exception:  # noqa: BLE001
            pass
        out.append({"wallet": w["wallet"], "tier": r["tier"], "stats": w.get("stats") or {}, "last": last})
    return out


def _tl(token, sym=None):
    """Compact token link for the box (no icon row: the lists below have them)."""
    from ui.html import short
    from urllib.parse import quote
    return f'<a href="/token/{quote(token)}" translate=no>{esc(sym) if sym else "<code>" + esc(short(token)) + "</code>"}</a>'


def group_pick():
    """The best crew of KOLs that call together (kol/together): follow them, enter when they post."""
    try:
        from kol import shillers, store as _ks, together
        con = _ks.ro() if hasattr(_ks, "ro") else None
        if con is None:
            import sqlite3 as _s
            con = _s.connect(f"file:{_ks.DB}?mode=ro", uri=True)
            con.row_factory = _s.Row
        try:
            tog = together.build(con, shillers.handles())
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        return None
    good = [c for c in tog.get("clusters") or [] if c["stats"]["n"] >= 3 and (c["stats"]["hit"] or 0) >= 0.5
            and (c["stats"]["rug"] or 0) < 0.4 and not c.get("shill")]
    if not good:
        return None
    c = good[0]
    return {"members": c["members"][:5], "n": c["stats"]["n"], "hit": c["stats"]["hit"], "rug": c["stats"]["rug"],
            "tokens": c["tokens"]}


def _chance_txt(c):
    if not c:
        return "povijest još nema dovoljno sličnih poziva"
    return f"{c[0]:.0%} sličnih tokena (po market capu) napravilo je +30 % u 24 h ({c[1]} izmjerenih poziva)"


def _makro_line():
    try:
        from market import makro
        return makro.line()
    except Exception:  # noqa: BLE001
        return ""


JS = r"""
<script>(()=>{let b=document.getElementById('pdj');if(!b)return;
// 7.11. (Jure): the box rebuilds itself every 60 s from the server (fresh picks), the page need not reload
async function reload(){try{const r=await fetch('/api/prijedlog?box='+encodeURIComponent(b.dataset.kind),{cache:'no-store'});if(!r.ok)return;
 const t=document.createElement('div');t.innerHTML=await r.text();const nb=t.querySelector('#pdj');if(!nb)return;b.replaceWith(nb);b=nb;prices()}catch(e){}}
function age(){const a=document.getElementById('pdj-age'),ts=+(b.dataset.ts||0);if(!a||!ts)return;const s=Math.round(Date.now()/1000-ts);
 a.textContent=s<15?'osvježeno upravo sada':'osvježeno prije '+(s<60?s+' s':Math.round(s/60)+' min')}
setInterval(age,5000);setInterval(reload,60000);
function prices(){const items=[...b.querySelectorAll('[data-p]')];if(!items.length)return;
const fmt=v=>v>=1e6?'$'+(v/1e6).toFixed(2)+'M':v>=1e3?'$'+(v/1e3).toFixed(1)+'k':'$'+Math.round(v);
async function tick(){try{const q=items.map(e=>e.dataset.p).join(',');const r=await fetch('/api/prijedlog?t='+q,{cache:'no-store'});if(!r.ok)return;const j=await r.json();
items.forEach(e=>{const m=j[e.dataset.p];const s=e.querySelector('.pnow');if(!s)return;if(!m||!m.mcap){s.textContent='(cijena trenutno nedostupna)';return}
const x=m.mcap/(+e.dataset.m0||m.mcap);let t='sada '+fmt(m.mcap)+' ('+(x>=1?'+':'')+Math.round((x-1)*100)+'% od analize): ';
if(x>=__PULL__){t+='⏳ pričekaj povlačenje, ne juri';s.className='pnow neg'}else if(x<=__DROP__){t+='⚠️ pada, ne ulazi dok se ne okrene';s.className='pnow neg'}else{t+='✅ još je u zoni ulaza';s.className='pnow pos'}s.textContent=t})}catch(e){}}
tick()}
prices();setInterval(()=>{if(!document.hidden)prices()},60000)})()</script>""".replace("__PULL__", str(PULL_X)).replace("__DROP__", str(DROP_X))

CSS = ("<style>.pdj{border:2px solid var(--acc);border-radius:14px;padding:12px 14px;margin:8px 0 14px;background:var(--card)}"
       ".pdj h2{margin:0 0 6px;font-size:17px}.pdj .an{color:var(--mut);font-size:13px;margin:0 0 8px}"
       ".pdj ol{margin:0;padding-left:20px}.pdj li{margin:0 0 10px}.pdj .pnow{display:block;font-size:13px;margin-top:2px}"
       ".pdj .pnow.pos{color:var(--good)}.pdj .pnow.neg{color:var(--bad)}.pdj .why{color:var(--mut);font-size:13px}"
       ".pdj details{margin-top:6px}.pdj summary{cursor:pointer;color:var(--acc);font-size:13px}</style>")


def _item(p, status=None):
    st = (status or {}).get(p["token"])
    why = "; ".join(esc(w) for w in p["why"]) or "ocjena alata i Šansa"
    raz = p.get("razina") or "visoka"
    cls = {"visoka": "good", "srednja": "warn", "niska": "bad"}[raz]
    stake = {"visoka": "25–50 $", "srednja": "20–25 $", "niska": "10 $ ili samo gledaj"}[raz]
    return (f'<li data-p="{esc(p["token"])}" data-m0="{p["mcap0"]:.0f}"><b>{_tl(p["token"], p["symbol"])}</b> '
            f'<span class="b {cls}">vjerojatnost {raz}</span> ulog {stake} · '
            f'na <b>{usd(p["mcap0"])[0]}</b> u trenutku analize · pouzdanost {p["conf"] or 0:.0f}'
            f'<span class=why><br>Zašto: {why}. {esc(_chance_txt(p["chance"]))}.</span>'
            f'<span class="pnow mut">provjeravam trenutnu cijenu…</span></li>')


def box(kind, now=None, rows=None):
    """kind: tokeni | influenceri | novcanici. HTML of the box (with the live-price script)."""
    now = now or time.time()
    an = analysed(now)
    try:
        from hype import tokenstatus
        status = tokenstatus.read(data.HYPE_DB)
    except Exception:  # noqa: BLE001
        status = {}
    picks = token_picks(now, rows=rows, status=status)
    mak = _makro_line()
    rec = ""
    try:   # dnevnik odluka: write the picks down, show the box's own 7-day record (ui/prijedlog_log)
        from ui import prijedlog_log
        prijedlog_log.log(data.HYPE_DB, picks, kind, now)
        rec = prijedlog_log.sentence(prijedlog_log.summary(data.HYPE_DB, now=now))
    except Exception:  # noqa: BLE001
        pass
    head = (f"Analizirao sam u zadnja 24 h: {an.get('tokena', 0)} tokena, {an.get('poziva', 0)} poziva od "
            f"{an.get('kolova', 0)} računa, {an.get('novcanika', 0)} ocijenjenih novčanika i {an.get('tradeova', 0)} "
            "demo tradeova strategija.")
    b = [CSS, f'<div class="pdj" id="pdj" data-kind="{esc(kind)}" data-ts="{int(now)}"><h2>Prijedlog za danas '
         f'<small class=mut style="font-weight:400;font-size:12px" id=pdj-age>osvježeno upravo sada</small></h2>',
         f"<p class=an>{esc(head)}" + (f" Tržište: {esc(mak)}" if mak else "") + (f" {esc(rec)}" if rec else "") + "</p>"]
    if kind == "tokeni":
        if picks:
            b.append("<p>Ako želiš zaraditi danas, ovo bih ušao sada; ulog po razini vjerojatnosti (visoka = prošao sve "
                     "filtre i svjež, srednja = prošao ali stariji od 6 h, niska = ispod praga pouzdanosti, samo mali ulog):</p><ol>"
                     + "".join(_item(p, status) for p in picks) + "</ol>")
            b.append("<p class=why>Pravilo: cijena ispod označava je li token još u zoni ulaza. Ako je otišao više od 25 % "
                     "od analize, ne juri ga; pričekaj povlačenje ili sljedeći prijedlog. Izlaz: pola na +15 %, ostatak "
                     "s pratećim stopom 15 %, stop −25 %.</p>")
        else:
            b.append("<p>Trenutno <b>nema nijednog tokena sa živim parom koji nije rug</b> u zadnja 24 h; novi prijedlog "
                     "čim ga podaci daju (sken ide svake 2 minute).</p>")
    elif kind == "influenceri":
        ks = kol_picks(now)
        if ks:
            b.append("<p>Koga danas slušati (dokazani prvi; „na probi” = dobar početak, još premalo izmjerenih poziva):</p><ol>")
            for k in ks:
                l = k["last"]
                lt = (f" Zadnji poziv: {_tl(l['token'], l.get('symbol'))}" + (f" na {usd(l['mcap0'])[0]}" if l.get("mcap0") else "") + " "
                      f"prije {max(0, (now - (l['ts'] or now)) / 3600):.1f} h." if l else " Bez poziva u zadnje vrijeme.")
                b.append(f'<li><b><a href="/kol/{esc(k["handle"])}">@{esc(k["handle"])}</a></b>'
                         + (' <span class="b warn">na probi</span>' if k.get("trial") else ' <span class="b good">dokazan</span>')
                         + f' · moć poziva {k["score"]:.0f}, pogodak {(k["hit"] or 0):.0%} na {k["measured"]} poziva.{lt}'
                         + (f'<span class=why><br>Ulaz ima smisla samo ako je token još blizu cijene poziva; '
                            f'provjeri ispod.</span>' if l and k["fresh"] else "") + "</li>")
            b.append("</ol>")
        else:
            b.append("<p>Danas <b>nema dokazanog influencera sa svježim pozivom</b>; ne ulazim na poziv samo zato što je "
                     "poznat račun. Ljestvica ispod pokazuje tko je blizu probe.</p>")
        if picks:
            b.append("<p>Tokeni koje bih uzeo sada (iz svih izvora):</p><ol>" + "".join(_item(p, status) for p in picks[:2]) + "</ol>")
    elif kind == "novcanici":
        ws = wallet_picks(now)
        if ws:
            b.append("<p>Koga danas kopirati (visoka/srednja = prošao uvjete kopiranja, niska = najbolji dostupni, još ispod praga, mali ulog):</p><ol>")
            for w in ws:
                s = w["stats"]
                l = w["last"]
                b.append(f'<li><b>{wlink(w["wallet"])}</b> · pouzdanost {esc(w["tier"])}, {s.get("closed", 0)} zatvorenih, '
                         f'{(s.get("win_rate") or 0):.0%} dobitnih, {(s.get("closed_pnl_sol") or 0):+.1f} SOL ukupno.'
                         + (f" Zadnja kupnja: {_tl(l['mint'])} prije "
                            f"{max(0, (now - (l['ts'] or now)) / 3600):.1f} h." if l else "") + "</li>")
            b.append("</ol><p class=why>Ulog 20–50 $ po tradeu, najviše 3 otvorene, izlazi po pravilima bota.</p>")
        else:
            b.append("<p>Još <b>nijedan novčanik nema ni 3 zatvorena tradea u plusu</b>; čim ga ima, piše ovdje s razinom "
                     "vjerojatnosti. Tablice ispod su za one koji žele kopati sami.</p>")
        if picks:
            b.append("<p>Tokeni koje bih uzeo sada:</p><ol>" + "".join(_item(p, status) for p in picks[:2]) + "</ol>")
    elif kind == "pregled":
        parts = []
        if picks:
            parts.append("<p><b>U ovom trenutku bih uložio</b> u ove tokene (demo 25–50 $ po tokenu):</p><ol>"
                         + "".join(_item(p, status) for p in picks) + "</ol>")
        else:
            parts.append("<p><b>U ovom trenutku nema tokena sa živim parom koji nije rug</b> u zadnja 24 h.</p>")
        ws = wallet_picks(now, n=1)
        if ws:
            w, st_ = ws[0], ws[0]["stats"]
            parts.append(f"<p><b>Pratio bih novčanik</b> {wlink(w['wallet'])} (pouzdanost {esc(w['tier'])}, "
                         f"{st_.get('closed', 0)} zatvorenih, {(st_.get('win_rate') or 0):.0%} dobitnih) i kopirao njegove kupnje "
                         "unutar 2 minute, 20–50 $ po tradeu.</p>")
        else:
            parts.append("<p><b>Novčanici:</b> još nijedan nema ni 3 zatvorena tradea u plusu; čim ga ima, piše ovdje.</p>")
        g = group_pick()
        if g:
            mem = ", ".join(f'<a href="/kol/{esc(h)}">@{esc(h)}</a>' for h in g["members"])
            parts.append(f"<p><b>Čekao bih da ova ekipa objavi token</b>: {mem}. Kad su zvali zajedno ({g['n']} puta), "
                         f"token se udvostručio u {g['hit']:.0%} slučajeva, rug {(g['rug'] or 0):.0%}. Ulaz čim objave, "
                         "ako je token ispod 1 M $ i još nije +25 % od poziva.</p>")
        ch = chances()
        mid = ch.get("100–300k") or ch.get("300k–1M")
        parts.append("<p><b>Očekivanje i izlaz:</b> "
                     + (f"u zadnja 2 tjedna {mid[0]:.0%} sličnih tokena (100k–1M) napravilo je +30 % u 24 h ({mid[1]} poziva); "
                        if mid else "")
                     + "ciljam +15 % na pola pozicije, ostatak vodim s pratećim stopom 15 %, stop −25 %; kod tokena 1 M+ "
                     "ljestvica +15 %/+30 % i stop −20 %. Ako BTC pada, stop se širi na −50 % i držim do oporavka.</p>")
        b += parts
    b.append("</div>" + JS)
    return "".join(b)


def api(qs):
    """/api/prijedlog?t=mint,mint → {mint: {mcap, price}} live from DexScreener (the page polls every minute);
    ?box=tokeni|influenceri|novcanici|pregled → the whole box rebuilt now (HTML, no script)."""
    kind = qs.get("box")
    if kind in ("tokeni", "influenceri", "novcanici", "pregled"):
        html = box(kind)
        return html.split("<script>")[0]
    toks = [t for t in (qs.get("t") or "").split(",") if t][:12]
    if not toks:
        return "{}"
    try:
        from koltest import run as kt
        mk = kt.market(set(toks)) or {}
    except Exception:  # noqa: BLE001
        mk = {}
    return json.dumps({t: ({"mcap": mk[t][2], "price": mk[t][0]} if t in mk else None) for t in toks})
