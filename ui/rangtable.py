"""Tablica "Za kopiranje" (11.11.2026, Jure): one table for wallets (/wallets) and influencers (/kol), from the copy
ranking wallets/rang.py stores in wallets.db copy_rank (read-only, cached; no new endpoint, no heavy query).

Columns (the owner's): Ocjena · ROI % · Medijan/trade · Win (donja granica) · n · Koncentracija · Kopirljivo (da/ne +
likvidnost) · Drži · Zadnji trade. Default order Ocjena; every header sorts on the client (data-* on the rows, no new
request). A tap on a row opens its details row: total SOL PnL and the average stake (never in the score), PnL
without the best trade, profit factor, raw win rate, our cost at 0.1-0.15 SOL, our lag, the gain left after it, the
last 7 days, the score's parts. autopilot_box() is the small block the Autopilot page can call (ui/pravitrade is being
redesigned on a parallel branch: it only needs to call this one function).
"""
from urllib.parse import quote

from ui import redak as rd

COLS = (("name", "Novčanik", "s"), ("sc", "Ocjena", "n"), ("roi", "ROI %", "n"), ("med", "Medijan/trade", "n"),
        ("wlo", "Win (donja granica)", "n"), ("n", "n", "n"), ("conc", "Koncentracija", "n"),
        ("cp", "Kopirljivo", "n"), ("hold", "Drži", "n"), ("last", "Zadnji trade", "n"))
TITLES = {"sc": "Ocjena 0-100: donja granica win ratea, medijan po tradeu, profit factor, kopirljivost, svježina; "
                "koncentracija iznad 50 % × 0,6. Apsolutna zarada u SOL-u nije u ocjeni.",
          "wlo": "Donja granica (Wilson, 90 %) udjela tokena zatvorenih u plusu: 5 od 5 ne pobjeđuje 40 od 55.",
          "conc": "Udio najvećeg tradea u ukupnoj zaradi; iznad 50 % ocjena × 0,6.",
          "cp": "Medijan likvidnosti poola kod njegovih ulaza; ispod 15k $ ili nepoznato = nije kopirljivo (Autopilot ga "
                "ne kopira pravim novcem).",
          "n": "Zatvoreni tokeni (pozivi) u 30 dana; od 10 je dokazan."}

CSS = """<style>
.rt-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:12px 0 0;max-width:100%}
.rt{border-collapse:collapse;width:100%;font-size:14px;min-width:820px}
.rt th,.rt td{padding:9px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
.rt th:first-child,.rt td:first-child{text-align:left;position:sticky;left:0;background:var(--bg,#fff);z-index:1}
.rt th{font-size:12.5px;font-weight:600;color:var(--mut);cursor:pointer;user-select:none}
.rt th[aria-sort=descending]::after{content:" ▾"}.rt th[aria-sort=ascending]::after{content:" ▴"}
.rt tr.rt-r{cursor:pointer}.rt tr.rt-r:hover td{background:var(--soft)}
.rt td.sc{font-weight:700;font-size:15px}.rt .pos{color:var(--good)}.rt .neg{color:var(--bad)}.rt .warn{color:var(--warn)}
.rt .mut{color:var(--mut)}.rt a{color:var(--fg);text-decoration:none;font-weight:600}.rt a:hover{color:var(--acc)}
.rt tr.rt-d td{white-space:normal;text-align:left;background:var(--soft);font-size:13.5px;color:var(--mut);line-height:1.5}
.rt tr.rt-d b{color:var(--fg);font-weight:600}
.rt-note{font-size:13px;color:var(--mut);margin:8px 0 0}
</style>"""

JS = """<script>(()=>{document.querySelectorAll('table[data-rt]').forEach(t=>{const b=t.tBodies[0];
const pairs=()=>[...b.querySelectorAll('tr.rt-r')].map(r=>[r,r.nextElementSibling&&r.nextElementSibling.classList.contains('rt-d')?r.nextElementSibling:null]);
t.querySelectorAll('th[data-k]').forEach(th=>th.onclick=()=>{const k=th.dataset.k,s=th.dataset.t==='s';
const asc=th.getAttribute('aria-sort')==='descending';t.querySelectorAll('th').forEach(x=>x.removeAttribute('aria-sort'));
th.setAttribute('aria-sort',asc?'ascending':'descending');const ps=pairs();
ps.sort((a,c)=>{const x=a[0].dataset[k]||'',y=c[0].dataset[k]||'';const v=s?x.localeCompare(y):(+x)-(+y);return asc?v:-v});
ps.forEach(p=>{b.appendChild(p[0]);if(p[1])b.appendChild(p[1])})});
b.addEventListener('click',e=>{if(e.target.closest('a'))return;const r=e.target.closest('tr.rt-r');if(!r)return;
const d=r.nextElementSibling;if(d&&d.classList.contains('rt-d')){d.hidden=!d.hidden;r.setAttribute('aria-expanded',String(!d.hidden))}})})})()</script>"""


def _n(x, missing=-1e9):
    try:
        return f"{float(x):.6g}"
    except (TypeError, ValueError):
        return f"{missing:.6g}"


def _tone(x):
    return {"pos": " pos", "neg": " neg"}.get(rd.tone(x) or "", "")


def _hold(m):
    if m is None:
        return rd.DASH
    m = float(m)
    return f"{m:.0f} min" if m < 59.5 else f"{round(m / 60)} h" if m < 48 * 60 else f"{round(m / 1440)} d"


def _liq(x):
    return rd.usd(x) if x is not None else "nepoznato"


def details(r, kind):
    """The details row's sentence parts (Croatian, plain): what is shown but not scored, and how the score came."""
    p = r.get("parts") or {}
    out = []
    if kind == "wallet":
        out.append(f"<b>Zarada ukupno</b> {rd.h(rd.sol(r.get('pnl'), 2, sign=True))} na {rd.h(rd.num(r.get('n')))} "
                   f"zatvorenih (bez najboljeg tradea {rd.h(rd.sol(r.get('pnl_ex_top'), 2, sign=True))}); "
                   f"<b>prosječan ulog</b> {rd.h(rd.sol(r.get('stake'), 2))}. Ni jedno ni drugo nije u ocjeni.")
    else:
        out.append(f"<b>Zbroj povrata</b> {rd.h(rd.pct(r.get('pnl'), sign=True, frac=True))} na {rd.h(rd.num(r.get('n')))} "
                   f"poziva (bez najboljeg {rd.h(rd.pct(r.get('pnl_ex_top'), sign=True, frac=True))}); jednak ulog po pozivu, "
                   "povrat 4 h nakon poziva gdje je izmjeren, inače 1 h.")
    pf = r.get("pf")
    out.append(f"<b>Profit factor</b> {rd.h(rd.num(pf, 2) if pf is not None else rd.DASH)} · <b>win</b> "
               f"{rd.h(rd.share(r.get('wins'), r.get('n')))} ({rd.h(rd.pct(r.get('win'), sign=False, frac=True))}, donja "
               f"granica {rd.h(rd.pct(r.get('win_lo'), sign=False, frac=True))}).")
    src = r.get("liq_src") or {}
    srcs = ", ".join(f"{'snimka poola' if k == 'snimka' else 'procjena iz cijene ulaza' if k == 'model' else k} {v}"
                     for k, v in sorted(src.items()))
    cp = (f"<b>Kopiranje</b>: medijan likvidnosti na ulazu {rd.h(_liq(r.get('liq')))} (poznato za "
          f"{rd.h(rd.num(r.get('liq_known')))} od {rd.h(rd.num(r.get('n')))}{'; ' + rd.h(srcs) if srcs else ''})")
    if r.get("slip") is not None:
        cp += (f", naš trošak za 0,1–0,15 SOL {rd.h(rd.pct(r.get('slip_lo'), 1, sign=False, frac=True))}–"
               f"{rd.h(rd.pct(r.get('slip'), 1, sign=False, frac=True))} (ulaz + izlaz)")
    lag_src = {"fast": "brza provjera", "copy_log": "Autopilot kopije", "zadano": "zadano"}.get(r.get("lag_src"), r.get("lag_src"))
    cp += f"; naše kašnjenje {rd.h(rd.num(r.get('lag_s')))} s ({rd.h(lag_src or rd.DASH)})"
    cp += (f", nakon njega ostaje {rd.h(rd.pct(r.get('avail'), sign=False, frac=True))} dobitka (izmjereno na "
           f"{rd.h(rd.num(r.get('avail_n')))})" if r.get("avail") is not None else ", dio dobitka nakon kašnjenja nije izmjeren")
    if not r.get("copyable"):
        cp += f". <span class=warn>Nije kopirljivo: {rd.h(r.get('why') or '')}</span>"
    out.append(cp + ".")
    parts = " · ".join(f"{lbl} {rd.num(100 * (p.get(k) or 0))}" for k, lbl in
                       (("win", "win"), ("median", "medijan"), ("pf", "profit factor"), ("copy", "kopirljivost"),
                        ("recency", "svježina")))
    pen = r.get("pen") or 1
    out.append(f"<b>Dijelovi ocjene</b> (0–100): {rd.h(parts)}"
               + ((f"; koncentracija {rd.h(rd.pct(r.get('conc'), sign=False, frac=True))} pa × {rd.h(rd.num(pen, 1))}"
                   if r.get("conc") is not None else
                   f"; bez najboljeg tradea u minusu, pa × {rd.h(rd.num(pen, 1))}") if pen < 1 else "")
               + f". Zadnjih 7 dana: {rd.h(rd.num(r.get('n7')))} zatvorenih.")
    if not r.get("proven"):
        out.append("<span class=warn>Nije dokazan: manje od 10 u 30 dana.</span>")
    return " ".join(out)


def _name(r, kind, names=None, tags=None):
    """The first cell: the link, and next to it the Autopilot's own marks (tags: {target: ["dokazan dvaput", ...]})."""
    t = r["target"]
    if kind == "wallet":
        lab = (names or {}).get(t) or f"{t[:4]}…{t[-4:]}"
        a = f'<a href="/wallet/{quote(t)}">{rd.h(lab)}</a>'
    else:
        a = f'<a href="/kol/{quote(t)}">@{rd.h(t.lstrip("@"))}</a>'
    tg = (tags or {}).get(t)
    return a + (f' <span class=mut>· {rd.h(" · ".join(tg))}</span>' if tg else "")


def row_html(r, kind, now=None, names=None, tags=None):
    conc = r.get("conc")
    cp = r.get("copyable")
    liq = r.get("liq")
    cps = (f'<span class=pos>da</span> <span class=mut>{rd.h(_liq(liq))}</span>' if cp else
           f'<span class=warn>ne</span> <span class=mut>{rd.h(_liq(liq))}</span>')
    hold = (f"{int(r['hold_min'] // 60)} h" if kind == "kol" and r.get("hold_min") else _hold(r.get("hold_min")))
    n = r.get("n") or 0
    data = {"name": rd.h(r["target"].lower()), "sc": _n(r.get("score")), "roi": _n(r.get("roi")), "med": _n(r.get("median")),
            "wlo": _n(r.get("win_lo")), "n": _n(n), "conc": _n(conc), "cp": _n((1e9 if cp else 0) + (liq or 0)),
            "hold": _n(r.get("hold_min")), "last": _n(r.get("last_ts"))}
    attrs = " ".join(f'data-{k}="{v}"' for k, v in data.items())
    cells = [f"<td>{_name(r, kind, names, tags)}</td>",
             f'<td class=sc title="{rd.h(TITLES["sc"])}">{rd.h(rd.num(r.get("score"), 1))}</td>',
             f'<td class="{_tone(r.get("roi")).strip()}">{rd.h(rd.pct(r.get("roi"), sign=True, frac=True))}</td>',
             f'<td class="{_tone(r.get("median")).strip()}">{rd.h(rd.pct(r.get("median"), sign=True, frac=True))}</td>',
             f'<td>{rd.h(rd.pct(r.get("win_lo"), sign=False, frac=True))}</td>',
             f'<td{"" if n >= 10 else " class=warn"}>{rd.h(rd.num(n))}</td>',
             f'<td{" class=warn" if r.get("conc_hi") or (conc is not None and conc > 0.5) else ""}>'
             f'{rd.h(rd.pct(conc, sign=False, frac=True) if conc is not None else "u minusu" if r.get("conc_hi") else rd.DASH)}</td>',
             f"<td>{cps}</td>", f"<td>{rd.h(hold)}</td>",
             f'<td class=mut>{rd.h(rd.ago(r.get("last_ts"), now))}</td>']
    return (f'<tr class=rt-r {attrs} aria-expanded="false">{"".join(cells)}</tr>'
            f'<tr class=rt-d hidden><td colspan={len(COLS)}>{details(r, kind)}</td></tr>')


def table(rows, kind="wallet", now=None, names=None, empty=None, tags=None):
    """The ranking table (HTML, CSS and JS included). rows: rang.ranked() rows, already in the order to show (the
    default is Ocjena, high to low). tags: {target: [short marks]} shown next to the name (dokazan dvaput, prati
    Autopilot)."""
    if not rows:
        return rd.hint(empty or "Rang za kopiranje još nije izračunat (računa se nakon ocjenjivanja novčanika, svaka 3 h).")
    head = []
    for k, t, typ in COLS:
        lbl = ("Influencer" if kind == "kol" else "Novčanik") if k == "name" else ("Drži (mjereno)" if k == "hold" and kind == "kol" else t)
        title = f' title="{rd.h(TITLES[k])}"' if k in TITLES else ""
        sort = ' aria-sort="descending"' if k == "sc" else ""
        head.append(f'<th data-k="{k}" data-t="{typ}"{title}{sort} scope=col>{rd.h(lbl)}</th>')
    body = "".join(row_html(r, kind, now, names, tags) for r in rows)
    return rd.raw(f'{CSS}<div class=rt-wrap><table class=rt data-rt><thead><tr>{"".join(head)}</tr></thead>'
                  f'<tbody>{body}</tbody></table></div>{JS}')


def note(kind="wallet"):
    from wallets import rang
    who = "zatvorenih tokena" if kind == "wallet" else "poziva"
    pc = lambda x: rd.pct(x, sign=False, frac=True)
    return rd.raw('<p class=rt-note>' + rd.h(
        f"Ocjena 0–100 iz zadnjih {rang.WINDOW_D} dana: donja granica win ratea {pc(rang.WEIGHTS['win'])}, medijan po "
        f"tradeu {pc(rang.WEIGHTS['median'])}, profit factor {pc(rang.WEIGHTS['pf'])}, kopirljivost "
        f"{pc(rang.WEIGHTS['copy'])}, svježina {pc(rang.WEIGHTS['recency'])}; koncentracija iznad "
        f"{pc(rang.CONC_MAX)} × {rd.num(rang.CONC_MULT, 1)}. Dokazan: {rang.MIN_N}+ {who}. Kopirljivo: medijan "
        f"likvidnosti na ulazu {rang.MIN_LIQ_USD // 1000}k $+ (nepoznato = ne). Ukupna zarada u SOL-u i prosječan ulog "
        "su u retku detalja (dodir na redak), nisu u ocjeni. Stupci se poredaju klikom na naslov.") + "</p>")


def autopilot_box(kind="wallet", n=5, now=None, path=None):
    """Small block for the Autopilot page: the best n proven AND copyable sources of the copy ranking (the only ones
    real money copies), plus how many were left out as "nije kopirljivo". HTML string; "" without a ranking."""
    from wallets import rang
    try:
        allr = rang.ranked(kind, path, proven=True)
    except Exception:  # noqa: BLE001
        return ""
    if not allr:
        return ""
    ok = [r for r in allr if r["copyable"]][:n]
    out_n = sum(1 for r in allr if not r["copyable"])
    who = "novčanika" if kind == "wallet" else "influencera"
    items = [{"name": (f"{r['target'][:4]}…{r['target'][-4:]}" if kind == "wallet" else "@" + r["target"].lstrip("@")),
              "reason": f"medijan {rd.pct(r.get('median'), sign=True, frac=True)} · win (donja) "
                        f"{rd.pct(r.get('win_lo'), sign=False, frac=True)} · n {rd.num(r.get('n'))} · likv. {_liq(r.get('liq'))}",
              "value": rd.num(r.get("score"), 1), "sub": "ocjena",
              "href": (f"/wallet/{quote(r['target'])}" if kind == "wallet" else f"/kol/{quote(r['target'])}")} for r in ok]
    tail = (f"{out_n} dokazanih {who} nije kopirljivo (likvidnost na ulazu ispod {rang.MIN_LIQ_USD // 1000}k $ ili "
            "nepoznata): Autopilot ih ne kopira pravim novcem.") if out_n else ""
    return str(rd.rows(items, empty=f"Nijedan dokazani {who[:-1]} nije kopirljiv.")) + (str(rd.hint(tail)) if tail else "")
