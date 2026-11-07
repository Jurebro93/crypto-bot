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
    """Up to n tokens to enter now: fresh (<= MAX_AGE_S), relevant, still with a pair, best Šansa/confidence first.
    Each: token, symbol, mcap0 (at analysis), ts0, conf, why (list), chance (share of similar calls that reached
    +30 % in 24 h), band."""
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
    for r in sorted(rows, key=overview._rank, reverse=True):
        if not overview.relevant(r) or now - (r["last_seen"] or 0) > MAX_AGE_S:
            continue
        st = status.get(r["token"])
        if st and not st.get("has_pair"):
            continue
        mcap = (st or {}).get("mcap") or r.get("mcap")
        if not mcap or mcap < 30_000:
            continue
        try:
            from ui.radar import reasons
            why = reasons(r["features"], r["det"])[:3]
        except Exception:  # noqa: BLE001
            why = []
        if not why:
            why = [t for p, t in r.get("conf_parts") or [] if p > 0][:3]
        b = _band(mcap)
        out.append({"token": r["token"], "symbol": r["symbol"], "mcap0": mcap, "ts0": int(r["last_seen"] or now),
                    "conf": r.get("conf"), "why": why, "band": b, "chance": ch.get(b)})
        if len(out) >= n:
            break
    return out


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
<script>(()=>{const b=document.getElementById('pdj');if(!b)return;const items=[...b.querySelectorAll('[data-p]')];if(!items.length)return;
const fmt=v=>v>=1e6?'$'+(v/1e6).toFixed(2)+'M':v>=1e3?'$'+(v/1e3).toFixed(1)+'k':'$'+Math.round(v);
async function tick(){try{const q=items.map(e=>e.dataset.p).join(',');const r=await fetch('/api/prijedlog?t='+q,{cache:'no-store'});if(!r.ok)return;const j=await r.json();
items.forEach(e=>{const m=j[e.dataset.p];const s=e.querySelector('.pnow');if(!s)return;if(!m||!m.mcap){s.textContent='(cijena trenutno nedostupna)';return}
const x=m.mcap/(+e.dataset.m0||m.mcap);let t='sada '+fmt(m.mcap)+' ('+(x>=1?'+':'')+Math.round((x-1)*100)+'% od analize): ';
if(x>=__PULL__){t+='⏳ pričekaj povlačenje, ne juri';s.className='pnow neg'}else if(x<=__DROP__){t+='⚠️ pada, ne ulazi dok se ne okrene';s.className='pnow neg'}else{t+='✅ još je u zoni ulaza';s.className='pnow pos'}s.textContent=t})}catch(e){}}
tick();setInterval(tick,60000)})()</script>""".replace("__PULL__", str(PULL_X)).replace("__DROP__", str(DROP_X))

CSS = ("<style>.pdj{border:2px solid var(--acc);border-radius:14px;padding:12px 14px;margin:8px 0 14px;background:var(--card)}"
       ".pdj h2{margin:0 0 6px;font-size:17px}.pdj .an{color:var(--mut);font-size:13px;margin:0 0 8px}"
       ".pdj ol{margin:0;padding-left:20px}.pdj li{margin:0 0 10px}.pdj .pnow{display:block;font-size:13px;margin-top:2px}"
       ".pdj .pnow.pos{color:var(--good)}.pdj .pnow.neg{color:var(--bad)}.pdj .why{color:var(--mut);font-size:13px}"
       ".pdj details{margin-top:6px}.pdj summary{cursor:pointer;color:var(--acc);font-size:13px}</style>")


def _item(p, status=None):
    st = (status or {}).get(p["token"])
    why = "; ".join(esc(w) for w in p["why"]) or "ocjena alata i Šansa"
    return (f'<li data-p="{esc(p["token"])}" data-m0="{p["mcap0"]:.0f}"><b>{_tl(p["token"], p["symbol"])}</b> '
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
    head = (f"Analizirao sam u zadnja 24 h: {an.get('tokena', 0)} tokena, {an.get('poziva', 0)} poziva od "
            f"{an.get('kolova', 0)} računa, {an.get('novcanika', 0)} ocijenjenih novčanika i {an.get('tradeova', 0)} "
            "demo tradeova strategija.")
    b = [CSS, '<div class="pdj" id="pdj"><h2>Prijedlog za danas</h2>', f"<p class=an>{esc(head)}"
         + (f" Tržište: {esc(mak)}" if mak else "") + "</p>"]
    if kind == "tokeni":
        if picks:
            b.append("<p>Ako želiš zaraditi danas, ovo bih ušao sada, s ulogom koji smiješ izgubiti (demo: 25–50 $):</p><ol>"
                     + "".join(_item(p, status) for p in picks) + "</ol>")
            b.append("<p class=why>Pravilo: cijena ispod označava je li token još u zoni ulaza. Ako je otišao više od 25 % "
                     "od analize, ne juri ga; pričekaj povlačenje ili sljedeći prijedlog. Izlaz: pola na +15 %, ostatak "
                     "s pratećim stopom 15 %, stop −25 %.</p>")
        else:
            b.append("<p>Trenutno <b>ne bih ulazio ni u što</b>: nijedan svjež token nije prošao filtar (pouzdanost, "
                     "rug provjera, živ par). To je isto odluka; novi prijedlog čim ga podaci daju.</p>")
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
            b.append("<p>Koga danas kopirati:</p><ol>")
            for w in ws:
                s = w["stats"]
                l = w["last"]
                b.append(f'<li><b>{wlink(w["wallet"])}</b> · pouzdanost {esc(w["tier"])}, {s.get("closed", 0)} zatvorenih, '
                         f'{(s.get("win_rate") or 0):.0%} dobitnih, {(s.get("closed_pnl_sol") or 0):+.1f} SOL ukupno.'
                         + (f" Zadnja kupnja: {_tl(l['mint'])} prije "
                            f"{max(0, (now - (l['ts'] or now)) / 3600):.1f} h." if l else "") + "</li>")
            b.append("</ol><p class=why>Ulog 20–50 $ po tradeu, najviše 3 otvorene, izlazi po pravilima bota.</p>")
        else:
            b.append("<p>Danas <b>ne bih kopirao nikoga</b>: nitko nema dovoljno zatvorenih tradeova u plusu uz razumno "
                     "držanje. Tablice ispod su za one koji žele kopati sami.</p>")
        if picks:
            b.append("<p>Tokeni koje bih uzeo sada:</p><ol>" + "".join(_item(p, status) for p in picks[:2]) + "</ol>")
    b.append("</div>" + JS)
    return "".join(b)


def api(qs):
    """/api/prijedlog?t=mint,mint → {mint: {mcap, price}} live from DexScreener (the page polls every minute)."""
    toks = [t for t in (qs.get("t") or "").split(",") if t][:12]
    if not toks:
        return "{}"
    try:
        from koltest import run as kt
        mk = kt.market(set(toks)) or {}
    except Exception:  # noqa: BLE001
        mk = {}
    return json.dumps({t: ({"mcap": mk[t][2], "price": mk[t][0]} if t in mk else None) for t in toks})
