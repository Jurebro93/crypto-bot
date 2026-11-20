"""The page "Tržište i tokeni" (/trziste, 20.11.) and its compact block on a token's page: the BTC colour, Fear & Greed
and the meme platforms' volume on one timeline with the jumps and drops of the midcap list, and the tables of
market/trziste.py (does a token follow the market, when do jumps and drops happen, would standing still in fear and
buying when BTC turns up have improved the existing trades). Read-only on market.db (and the daily candles of the one
token on its page). Server-side HTML + SVG, no external JS: the bands are HTML blocks with CSS patterns (not stretched
by the SVG's scaling), the lines are SVG with non-scaling strokes, every label is HTML so it stays readable on a phone.
"""
import datetime as dt
import sqlite3

from market import store, trziste as T
from ui import redak as R
from ui.html import esc, lead, table

D = 86400
RANGES = (30, 90, 180)
CSS = """<style>
.tz-seg{display:flex;gap:6px;margin:6px 0 10px}.tz-seg a{padding:4px 10px;border:1px solid var(--line2);border-radius:14px;
text-decoration:none;color:var(--fg);font-size:13px}.tz-seg a.on{background:var(--acc);border-color:var(--acc);color:#fff}
.tz-ans{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px;margin:8px 0 14px}
.tz-ans .card{margin:0}.tz-ans b{display:block;margin-bottom:4px}
.tz-fig{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:8px 0}
.tz-leg{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:12px;color:var(--mut);margin:0 0 8px}
.tz-leg span{display:inline-flex;align-items:center;gap:5px}.tz-sw{display:inline-block;width:18px;height:12px;
border:1px solid var(--line2);border-radius:2px}
.tz-p{position:relative;width:100%;margin:2px 0}.tz-p svg{position:absolute;inset:0;width:100%;height:100%;overflow:visible}
.tz-bands{position:absolute;inset:0;display:flex}.tz-bands i{display:block;height:100%}
.tz-lab{position:absolute;font-size:11px;color:var(--mut);background:var(--card);padding:0 3px;border-radius:3px;
line-height:15px;white-space:nowrap;pointer-events:none}
.tz-lab.tl{top:2px;left:2px}.tz-lab.tr{top:2px;right:2px}.tz-lab.br{bottom:2px;right:2px}.tz-lab.bl{bottom:2px;left:2px}
.tz-g{background:rgba(22,163,74,.16)}
.tz-y{background:repeating-linear-gradient(135deg,rgba(217,119,6,.42) 0 2px,rgba(217,119,6,.12) 2px 7px)}
.tz-r{background:repeating-linear-gradient(0deg,rgba(220,38,38,.40) 0 1px,rgba(220,38,38,.12) 1px 5px)}
.tz-n{background:transparent}
.tz-f1{background:rgba(220,38,38,.10)}.tz-f2{background:rgba(217,119,6,.08)}.tz-f3{background:transparent}
.tz-f4{background:rgba(22,163,74,.07)}.tz-f5{background:rgba(22,163,74,.14)}
.tz-fb{position:absolute;left:0;right:0}.tz-fb em{position:absolute;right:4px;top:50%;transform:translateY(-50%);
font-size:10px;font-style:normal;color:var(--mut)}
.tz-x{display:flex;justify-content:space-between;font-size:11px;color:var(--mut);margin-top:3px}
.tz-src{font-size:12px;color:var(--mut);margin:6px 0 0}
.tz-tbl details{margin:6px 0 14px}.tz-tbl summary{cursor:pointer;color:var(--acc);font-size:13px}
.tz-flag{color:var(--warn)}
</style>"""
BAND = {"zeleno": "tz-g", "zuto": "tz-y", "crveno": "tz-r", None: "tz-n"}
FNG_BANDS = ((0, 25, "tz-f1", "ekstremni strah"), (25, 46, "tz-f2", "strah"), (46, 54, "tz-f3", ""),
             (54, 75, "tz-f4", "pohlepa"), (75, 100, "tz-f5", "ekstremna pohlepa"))


def _f(x, dec=1, sign=False):
    return R.num(x, dec, sign)


def _pc(x, dec=1, sign=True):
    return R.pct(x, dec, sign=sign, frac=True)


def _day(d):
    return dt.datetime.fromtimestamp(d, dt.timezone.utc).strftime("%d.%m.")


def _rows(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


# ---------- the timeline -------------------------------------------------------------------------------------------------

def _runs(cols):
    """[(colour, length)] of consecutive equal colours."""
    out = []
    for c in cols:
        if out and out[-1][0] == c:
            out[-1][1] += 1
        else:
            out.append([c, 1])
    return out


def _bands(cols):
    n = len(cols) or 1
    return ('<div class=tz-bands aria-hidden=true>' + "".join(
        f'<i class="{BAND.get(c, "tz-n")}" style="width:{100 * k / n:.4f}%"></i>' for c, k in _runs(cols)) + "</div>")


def _line(vals, lo, hi, cls_stroke, dash=""):
    """A polyline over x = 0..n-1 (viewBox n x 100), None values break it."""
    n = len(vals)
    if n < 2 or hi <= lo:
        return ""
    segs, cur = [], []
    for i, v in enumerate(vals):
        if v is None:
            if len(cur) > 1:
                segs.append(cur)
            cur = []
            continue
        cur.append(f"{i + 0.5:.2f},{100 - 100 * (v - lo) / (hi - lo):.2f}")
    if len(cur) > 1:
        segs.append(cur)
    da = f' stroke-dasharray="{dash}"' if dash else ""
    return "".join(f'<polyline points="{" ".join(s)}" fill=none stroke="{cls_stroke}" stroke-width=2 '
                   f'vector-effect=non-scaling-stroke stroke-linejoin=round{da} />' for s in segs)


def _svg(n, inner, label):
    return (f'<svg viewBox="0 0 {max(n, 1)} 100" preserveAspectRatio=none role=img aria-label="{esc(label)}">'
            f'{inner}</svg>')


def _series(con, days, since, step4h):
    """[(t, btc, colour)] of the window: 4-hour bars when step4h and they cover it, else the days."""
    if step4h:
        rows = _rows(con, "SELECT ts, btc, boja FROM trziste_4h WHERE ts >= ? ORDER BY ts", (since,))
        if rows and rows[0][0] <= since + D:
            return rows, 4 * 3600
    return [(d, r.get("btc"), r.get("boja")) for d, r in sorted(days.items()) if d >= since and r.get("btc")], D


def timeline(con, days, n_days, now, token=None, events=None, tok_closes=None):
    """The figure: legend, BTC with colour bands (and the token's line), F&G, platform volume, jumps / drops."""
    today = int(now) // D * D
    since = today - n_days * D
    ser, step = _series(con, days, since, n_days <= 30 and token is None)
    if len(ser) < 3:
        return '<div class=empty>Još nema dovoljno dana za vremensku crtu.</div>'
    ts = [t for t, _p, _c in ser]
    btc = [p for _t, p, _c in ser]
    cols = [c for _t, _p, c in ser]
    n = len(ser)
    lo, hi = min(p for p in btc if p), max(p for p in btc if p)
    pad = (hi - lo) * 0.08 or hi * 0.01
    inner = _line(btc, lo - pad, hi + pad, "var(--fg)")
    if tok_closes:
        tv = [tok_closes.get(t // D * D) for t in ts]
        have = [v for v in tv if v]
        if len(have) >= 2:
            tl, th = min(have), max(have)
            tp = (th - tl) * 0.08 or th * 0.01
            inner += _line(tv, tl - tp, th + tp, "var(--acc)", "5 3")
    tips = "".join(f'<rect x={i} y=0 width=1 height=100 fill=transparent><title>'
                   f'{esc(_tip(t, p, c, days.get(t // D * D), step))}</title></rect>' for i, (t, p, c) in enumerate(ser))
    p1 = (f'<div class=tz-p style="height:170px">{_bands(cols)}{_svg(n, inner + tips, "Cijena BTC-a s bojom stanja")}'
          f'<span class="tz-lab tl">BTC {R.num(btc[-1], 0)} $ · {esc(T.BOJA_HR.get(cols[-1], "–"))}</span>'
          f'<span class="tz-lab tr">{R.num(hi, 0)} $</span><span class="tz-lab br">{R.num(lo, 0)} $</span>'
          + ('<span class="tz-lab bl">isprekidano: cijena tokena (preračunata)</span>' if tok_closes else "") + "</div>")
    # Fear & Greed by day over the same window (one point a bar: the bar's day)
    fv = [(days.get(t // D * D) or {}).get("fng") for t in ts]
    fb = "".join(f'<div class="tz-fb {c}" style="top:{100 - b:.0f}%;height:{b - a:.0f}%"><em>{esc(lab)}</em></div>'
                 for a, b, c, lab in FNG_BANDS)
    cur_f = next((v for v in reversed(fv) if v is not None), None)
    p2 = (f'<div class=tz-p style="height:120px">{fb}{_svg(n, _line(fv, 0, 100, "var(--acc)"), "Fear and Greed 0 do 100")}'
          f'<span class="tz-lab tl">Strah i pohlepa {cur_f if cur_f is not None else "–"}'
          f'{" (" + esc(T.FNG_HR.get(T.fng_class(cur_f), "")) + ")" if cur_f is not None else ""}</span></div>')
    # platform volume, one bar a day (also on the 4-hour view: the day's bar spans its six bars)
    vol = [(days.get(t // D * D) or {}).get("vol") for t in ts]
    vmax = max((v for v in vol if v), default=0)
    bars = "".join(f'<rect x={i + 0.1:.2f} y={100 - 100 * v / vmax:.2f} width=0.8 height={100 * v / vmax:.2f} '
                   'fill="var(--bar)" fill-opacity=.55 />' for i, v in enumerate(vol) if v and vmax)
    vt = next((r.get("vol_trend") for _d, r in sorted(days.items(), reverse=True) if r.get("vol_trend")), None)
    p3 = (f'<div class=tz-p style="height:64px">{_svg(n, bars, "Volumen meme platformi po danu")}'
          f'<span class="tz-lab tl">Volumen meme platformi'
          f'{": 7 dana " + esc(T.VOL_HR.get(vt, "")) if vt else ""}</span>'
          f'<span class="tz-lab tr">do {R.usd(vmax) if vmax else "–"}</span></div>')
    # jumps up, drops down, per day (the token's own on its page)
    up, dn = [0] * n, [0] * n
    idx = {}
    for i, t in enumerate(ts):
        idx.setdefault(t // D * D, i)
    for d, (a, b) in (events or {}).items():
        if d in idx:
            up[idx[d]] += a
            dn[idx[d]] += b
    emax = max(up + dn + [1])
    w = 1.0 if step == D else 6.0
    ev = "".join(f'<rect x={i:.2f} y={50 - 48 * a / emax:.2f} width={min(w, n - i) * 0.8:.2f} height={48 * a / emax:.2f} '
                 'fill="var(--good)" />' for i, a in enumerate(up) if a)
    ev += "".join(f'<rect x={i:.2f} y=50 width={min(w, n - i) * 0.8:.2f} height={48 * b / emax:.2f} fill="var(--bad)" />'
                  for i, b in enumerate(dn) if b)
    ev += '<line x1=0 x2="100%" y1=50 y2=50 stroke="var(--line2)" vector-effect=non-scaling-stroke />'.replace(
        'x2="100%"', f"x2={n}")
    who = "tokena" if token else "midcap liste"
    p4 = (f'<div class=tz-p style="height:70px">{_svg(n, ev, "Skokovi i padovi po danu")}'
          f'<span class="tz-lab tl">▲ skokovi {who}</span><span class="tz-lab bl">▼ padovi</span>'
          f'<span class="tz-lab tr">najviše {emax} na dan</span></div>')
    marks = [0, n // 2, n - 1] if n < 12 else [0, n // 4, n // 2, 3 * n // 4, n - 1]
    xax = '<div class=tz-x aria-hidden=true>' + "".join(f"<span>{_day(ts[i])}</span>" for i in marks) + "</div>"
    legend = ('<div class=tz-leg><span><i class="tz-sw tz-g"></i>BTC raste (zeleno, puna boja)</span>'
              '<span><i class="tz-sw tz-y"></i>konsolidira (žuto, kose crte)</span>'
              '<span><i class="tz-sw tz-r"></i>pada (crveno, vodoravne crte)</span>'
              '<span>━ cijena BTC-a</span>' + ('<span style="color:var(--acc)">┅ cijena tokena</span>' if tok_closes else "")
              + '<span style="color:var(--good)">▲ skok</span><span style="color:var(--bad)">▼ pad</span>'
              + (f'<span>korak: {"4 sata" if step != D else "1 dan"}</span>') + "</div>")
    return (f'<div class=tz-fig>{legend}{p1}{p2}{p3}{p4}{xax}'
            '<p class=tz-src>Izvor: alternative.me (Fear &amp; Greed), DefiLlama (BTC, volumen platformi).</p></div>')


def _tip(t, p, c, day, step):
    when = dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%d.%m.%Y" + (" %H:%M UTC" if step != D else ""))
    s = f"{when}: BTC {R.num(p, 0)} $, {T.BOJA_HR.get(c, 'bez boje')}"
    if day:
        if day.get("fng") is not None:
            s += f", strah i pohlepa {day['fng']} ({T.FNG_HR.get(day.get('fng_klasa'), '')})"
        if day.get("vol"):
            s += f", meme volumen {R.usd(day['vol'])}"
    return s


def _events_per_day(res, since):
    out = {}
    for k, v in ((res or {}).get("po_danu") or {}).items():
        if int(k) >= since:
            out[int(k)] = v
    return out


# ---------- tables -----------------------------------------------------------------------------------------------------

def _state_hr(dim, v):
    if dim.startswith("boja"):
        return T.BOJA_HR.get(v, v)
    if dim.startswith("fng"):
        return T.FNG_HR.get(v, v)
    if dim == "zajedno":
        b, f = (v.split("/") + [""])[:2]
        return f"{T.BOJA_HR.get(b, b).split(' ')[0]}, {'strah' if f == 'strah' else 'bez straha'}"
    return T.VOL_HR.get(v, v)


def _cell_pct(x, dec=1):
    return (_pc(x, dec), x if x is not None else -1e18, "n")


def _cell_num(x, dec=0):
    return (_f(x, dec), x if x is not None else -1e18, "n")


def _stats_cells(s):
    ci = (f"{_pc(s['lo'])} do {_pc(s['hi'])}" if s.get("lo") is not None else "–")
    word = "" if s.get("dovoljno") else ' <span class=mut>(nedovoljno podataka)</span>'
    return [_cell_num(s["n"]), _cell_num(s["k"]), (_pc(s["mean"]) + word, s["mean"] if s["mean"] is not None else -1e18,
                                                     "n"), (ci, s.get("lo") or -1e18, "n"),
            _cell_pct(s.get("hit"), 0)]


def _follow_html(con, res):
    s = (res or {}).get("slijede") or {}
    head = "<h2>Prate li tokeni tržište?</h2>" + lead(
        "Za svaki token s dnevnim svijećama: koliko se njegove dnevne promjene poklapaju s BTC-om (korelacija i beta) "
        "i koliko često se snažno kreće suprotno od BTC-a.")
    if not s.get("dovoljno"):
        return head + '<div class=card>Nedovoljno podataka.</div>'
    grid = (f'<div class=grid><div class=stat><div class=v>{_f(s["corr_med"], 2)}</div><div class=l>medijan korelacije '
            f's BTC-om (n={s["tokena"]})</div></div><div class=stat><div class=v>{s["prate"]}</div><div class=l>tokena s '
            f'korelacijom barem {_f(T.FOLLOW_CORR, 1)}</div></div><div class=stat><div class=v>{_f(s["beta_med"], 2)}'
            f'</div><div class=l>medijan bete</div></div><div class=stat><div class=v>{_pc(s["isti_smjer_med"], 0, False)}'
            f'</div><div class=l>dana u smjeru BTC-a (medijan)</div></div><div class=stat><div class=v>{s["protiv"]}</div>'
            f'<div class=l>tokena često protiv tržišta</div></div></div>')
    cols = ["Token", ("Dana", "n"), ("Korelacija", "n"), ("Beta", "n"), ("Korelacija 30 d", "n"), ("U smjeru BTC-a", "n"),
            ("Protiv", "n"), ("Uz tržište", "n")]
    rows = _rows(con, "SELECT token, symbol, n, corr, beta, corr30, isti_smjer, protiv, uz, protiv_udio, oznaka FROM "
                      "trziste_tok ORDER BY oznaka DESC, protiv_udio DESC")

    def r_(r):
        sym = esc(r[1] or r[0][:6])
        return [f'<a href="/token/{esc(r[0])}" translate=no>{sym}</a>' + (' <span class=tz-flag>⚑</span>' if r[10] else ""),
                _cell_num(r[2]), _cell_num(r[3], 2), _cell_num(r[4], 2), _cell_num(r[5], 2), (_pc(r[6], 0, False), r[6] or 0, "n"),
                (f"{r[7]} ({_pc(r[9], 0, False)})", r[9] or 0, "n"), _cell_num(r[8])]
    flagged = [r for r in rows if r[10]]
    out = head + grid
    out += ("<p class=mut>⚑ " + esc(T.WORDING) + "</p>")
    if flagged:
        out += lead(f"Tokeni koji se snažno kreću protiv BTC-a barem jednako često kao s njim ({len(flagged)}).")
        out += table(cols, [r_(r) for r in flagged[:30]])
    out += ("<div class=tz-tbl><details><summary>Svi tokeni (" + str(len(rows)) + ")</summary>"
            + lead("Protiv = snažan rast na crveni dan ili snažan pad na zeleni dan (barem 2 puta veći od tokenove "
                   "tipične dnevne promjene).") + table(cols, [r_(r) for r in rows], limit=300) + "</details></div>")
    return out


def _events_html(res):
    ev = (res or {}).get("dogadaji") or {}
    out = "<h2>Kad se događaju skokovi, a kad padovi?</h2>" + lead(
        f"Svaki skok i pad midcap liste u zadnjih {T.EVENT_D} dana s bojom BTC-a, strahom i pohlepom i trendom "
        "volumena na dan kad je počeo; broj je preračunat na 100 token-dana u tom stanju, da se vidi koliko je "
        "stanje stvarno češće, a ne samo duže.")
    out += f'<p class=mut>Skokovi: {esc((res or {}).get("skokovi_izvor") or "–")}. Padovi: iz dnevnih svijeća, isto pravilo ' \
           "u suprotnom smjeru (pad barem 33 % u danu ili 50 % u 3 dana).</p>"
    cols = ["Stanje", ("Token-dana", "n"), ("Skokova", "n"), ("Skokova na 100", "n"), ("Medijan skoka", "n"),
            ("Padova", "n"), ("Padova na 100", "n"), ("Medijan pada", "n")]

    def rows_of(dim, tier="svi"):
        return [[esc(_state_hr(dim, r["stanje"])), _cell_num(r["token_dana"]), _cell_num(r["skokova"]),
                 _cell_num(r["skok_na_100"], 2), _cell_pct(r["skok_med"], 0), _cell_num(r["padova"]),
                 _cell_num(r["pad_na_100"], 2), _cell_pct(r["pad_med"], 0)]
                for r in ev.get(dim) or [] if r["tier"] == tier and (r["token_dana"] or r["skokova"] or r["padova"])]
    if not ev.get("boja"):
        return out + '<div class=card>Nedovoljno podataka.</div>'
    out += "<h3>Po boji BTC-a na dan početka</h3>" + table(cols, rows_of("boja"))
    det = ""
    for dim, title in (("boja_prije", "Po boji BTC-a dan prije"), ("fng_klasa", "Po strahu i pohlepi"),
                       ("fng_klasa_prije", "Po strahu i pohlepi dan prije"), ("vol_trend", "Po trendu volumena platformi"),
                       ("vol_trend_prije", "Po trendu volumena dan prije")):
        det += f"<h3>{title}</h3>" + table(cols, rows_of(dim))
    for tier in T.TIERS:
        det += f"<h3>Po boji BTC-a, tokeni {tier} $</h3>" + table(cols, rows_of("boja", tier))
        det += f"<h3>Po strahu i pohlepi, tokeni {tier} $</h3>" + table(cols, rows_of("fng_klasa", tier))
    return out + f"<div class=tz-tbl><details><summary>Više tablica (dan prije, strah i pohlepa, volumen, po veličini)</summary>{det}</details></div>"


def _rule_html(res):
    pr = (res or {}).get("pravilo") or {}
    out = "<h2>Bi li mirovanje u strahu i kupnja kad BTC krene gore popravili rezultat?</h2>" + lead(
        "Postojeći ulazi sa stvarnim rezultatom nakon troška (najmanje 3 % po krugu), svaki s onim što se znalo u trenutku "
        "ulaza: boja BTC-a i trend volumena od prethodnog dana, strah i pohlepa tog dana.")
    out += ("<p class=mut>Filtar se bira na prve dvije trećine dana, a rezultat se pokazuje na zadnjoj trećini koju "
            f"filtar nije vidio. Interval je 90 %, po token-danima; ispod {T.MIN_TD} token-dana piše „nedovoljno podataka”. "
            "Ništa od ovoga ne mijenja trgovanje.</p>")
    if not pr:
        return out + '<div class=card>Nedovoljno podataka.</div>'
    sc = ["Stanje pri ulazu", ("Ulaza", "n"), ("Token-dana", "n"), ("Prosjek po ulazu", "n"), ("Interval 90 %", "n"),
          ("Pogodak", "n")]
    fc = ["Filtar", ("Ranije: prosjek", "n"), ("Ranije: token-dana", "n"), ("Kasnije: prosjek", "n"),
          ("Kasnije: interval", "n"), ("Kasnije: token-dana", "n"), ("Miče ulaza", "n")]
    for name in ("replay", "sjena", "demo", "novcanici"):
        a = pr.get(name)
        if not a:
            continue
        s, o = a["svi"], a["oos"]
        out += f"<h3>{esc(T.SET_HR[name][:1].upper() + T.SET_HR[name][1:])}</h3>"
        if not s["n"]:
            out += '<p class=mut>Nema ulaza.</p>'
            continue
        b = o.get("base") or {}
        if o.get("odabran"):
            t = o["odabran_test"]
            msg = (f"Na ranijim danima najbolji je bio filtar „{T.FILTERS[o['odabran']][0]}”. Na kasnijim danima: "
                   + (f"{_pc(t['mean'])} po ulazu (n={t['n']}, {t['k']} token-dana) prema {_pc(b.get('mean'))} bez filtra "
                      f"(n={b.get('n')}); filtar miče {o['filtri'][o['odabran']]['maknuto']} od {b.get('n')} ulaza."
                      if t.get("dovoljno") else f"nedovoljno podataka ({t['k']} token-dana nakon filtra)."))
        elif o.get("split"):
            msg = ("Nijedan filtar nije bio bolji od ulaženja uvijek na ranijim danima"
                   + (f"; bez filtra na kasnijim danima {_pc(b.get('mean'))} po ulazu (n={b.get('n')})." if b.get("n") else "."))
        else:
            msg = "Nedovoljno podataka za podjelu na ranije i kasnije dane."
        if not s.get("dovoljno"):
            msg = f"Nedovoljno podataka ({s['k']} token-dana ukupno). " + msg
        out += f'<div class=card>{esc(msg)}</div>'
        out += table(sc, [[esc("svi ulazi")] + _stats_cells(s)]
                     + [[esc("BTC " + _state_hr("boja", k))] + _stats_cells(v) for k, v in a["po_stanju"]["boja"].items()])
        det = "<h3>Po strahu i pohlepi</h3>" + table(sc, [[esc(_state_hr("fng", k))] + _stats_cells(v)
                                                           for k, v in a["po_stanju"]["fng_klasa"].items()])
        det += "<h3>Po trendu volumena platformi</h3>" + table(sc, [[esc(_state_hr("vol", k))] + _stats_cells(v)
                                                                    for k, v in a["po_stanju"]["vol_trend"].items()])
        det += "<h3>BTC i strah zajedno</h3>" + table(sc, [[esc(_state_hr("zajedno", k) if k != "nepoznato" else k)]
                                                           + _stats_cells(v)
                                                           for k, v in a["po_stanju"]["zajedno"].items()])
        frows = []
        for f, v in (o.get("filtri") or {}).items():
            te = v["test"]
            frows.append([esc(T.FILTERS[f][0]) + (" ✓" if f == o.get("odabran") else ""), _cell_pct(v["train"]["mean"]),
                          _cell_num(v["train"]["k"]),
                          (_pc(te["mean"]) + ("" if te["dovoljno"] else ' <span class=mut>(nedovoljno)</span>'),
                           te["mean"] if te["mean"] is not None else -1e18, "n"),
                          (f"{_pc(te['lo'])} do {_pc(te['hi'])}" if te.get("lo") is not None else "–", te.get("lo") or -1e18,
                           "n"), _cell_num(te["k"]), (f"{v['maknuto']} ({_pc(v['maknuto_udio'], 0, False)})",
                                                      v["maknuto"], "n")])
        if o.get("split"):
            det += (f"<h3>Filtri: ranije {o['train_dana']} dana, kasnije {o['test_dana']} dana (od {_day(o['split'])})</h3>"
                    + lead("✓ je filtar odabran na ranijim danima; samo njegov kasniji broj je pošten test.")
                    + table(fc, frows))
        out += f"<div class=tz-tbl><details><summary>Detalji: strah i pohlepa, volumen, svi filtri</summary>{det}</details></div>"
    return out


def _lead_html(res):
    v = (res or {}).get("vodi") or {}
    out = "<h2>Volumen meme platformi i rast</h2>" + lead(
        "Korelacija dnevne promjene volumena (pump.fun, PumpSwap, LaunchLab, Meteora DBC) s brojem skokova i s "
        "medijanom dnevne promjene midcap tokena isti dan i do 3 dana prije ili poslije.")
    if not v.get("n"):
        return out + '<div class=card>Nedovoljno podataka.</div>'
    rows = []
    for lag in T.LAGS:
        k = str(lag)
        name = ("isti dan" if lag == 0 else f"volumen {lag} d prije" if lag > 0 else f"volumen {-lag} d poslije")
        rows.append([esc(name), _cell_num(v["skokovi"].get(k), 2), _cell_num(v["povrat"].get(k), 2)])
    return out + table(["Pomak", ("Sa skokovima", "n"), ("S promjenom midcapova", "n")], rows) + \
        f'<p class=mut>n={v["n"]} dana. +1 = uvijek zajedno, 0 = nema veze, −1 = suprotno.</p>'


# ---------- the page -----------------------------------------------------------------------------------------------------

def _load(now):
    con = store.ro()
    if con is None:
        return None, None, {}
    try:
        res = T.kv_get(con, "rezultat")
        days = T.load_days(con)
    except Exception:  # noqa: BLE001 - an old market.db without the tables
        res, days = None, {}
    return con, res, days


def page(qs, now=None):
    import time
    now = now or time.time()
    try:
        n_days = int((qs or {}).get("d") or 90)
    except (TypeError, ValueError):
        n_days = 90
    n_days = n_days if n_days in RANGES else 90
    head = (CSS + "<h1>Tržište i tokeni</h1><p class=mut>BTC, strah i pohlepa i volumen meme platformi na jednoj "
            "vremenskoj crti, uz skokove i padove tokena koje pratimo. " + esc(T.RULE_HR) + "</p>")
    con, res, days = _load(now)
    try:
        if con is None or not days:
            return "Tržište i tokeni", head + ('<div class=empty>Još nema izračuna. Posao ga radi sam nekoliko puta '
                                               'dnevno.</div>') + _foot()
        ans = T.answers(res or {})
        body = [head, '<div class=tz-ans>'
                + f'<div class=card><b>Prate li tokeni tržište?</b>{esc(ans["slijede"])}</div>'
                + f'<div class=card><b>Kad se događaju skokovi, a kad padovi?</b>{esc(ans["kada"])}</div>'
                + f'<div class=card><b>Bi li mirovanje u strahu i kupnja kad BTC krene gore popravili rezultat?</b>'
                  f'{esc(ans["pravilo"])}</div></div>']
        seg = '<nav class=tz-seg aria-label="Raspon">' + "".join(
            f'<a href="/trziste?d={r}"{" class=on" if r == n_days else ""}>{r} dana</a>' for r in RANGES) + "</nav>"
        since = int(now) // D * D - n_days * D
        body.append("<h2>Vremenska crta</h2>" + seg + timeline(con, days, n_days, now, events=_events_per_day(res, since)))
        if res:
            body.append(_follow_html(con, res))
            body.append(_events_html(res))
            body.append(_rule_html(res))
            body.append(_lead_html(res))
            body.append(f'<p class=mut>Izračunato {esc(R.ago(res["ts"], now))}.</p>')
        body.append(_foot())
        return "Tržište i tokeni", "".join(body)
    finally:
        if con is not None:
            con.close()


def _foot():
    return (f'<p class=tz-src>{esc(T.SOURCE_LINE)} Za token koji se često kreće protiv tržišta vrijedi: {esc(T.WORDING[:1].lower() + T.WORDING[1:])} '
            'Fear &amp; Greed: <a href="https://alternative.me/crypto/fear-and-greed-index/" rel=noopener>'
            'alternative.me</a>.</p>')


# ---------- a token's page --------------------------------------------------------------------------------------------

def _token_closes(mint):
    """{day: close} of the token's daily candles (midcap.db, else veliki.db), read-only."""
    p = T.paths()
    for name in ("midcap", "veliki"):
        con = T._ro(p.get(name))
        if con is None:
            continue
        try:
            rows = _rows(con, "SELECT ts, c FROM c1d WHERE token=? ORDER BY ts", (mint,))
        finally:
            con.close()
        if rows:
            return {int(t) // D * D: float(c) for t, c in rows if c}
    return {}


def token_html(mint, now=None):
    """The compact block on a token's page: two sentences and a 90-day timeline with the token's line and its own
    jumps and drops; "" when nothing is computed for it."""
    import time
    now = now or time.time()
    st = T.token_stats(mint)
    if not st:
        return ""
    con, res, days = _load(now)
    try:
        if con is None or not days:
            return ""
        ev = {}
        for d, kind in _rows(con, "SELECT day, kind FROM trziste_dog WHERE token=?", (mint,)):
            a = ev.setdefault(int(d), [0, 0])
            a[0 if kind == "skok" else 1] += 1
        s1 = (f"Korelacija dnevnih promjena s BTC-om {_f(st['corr'], 2)} (beta {_f(st['beta'], 2)}, {st['n']} dana)"
              + (f", zadnjih 30 dana {_f(st['corr30'], 2)}" if st.get("corr30") is not None else "")
              + f"; u smjeru BTC-a {_pc(st['isti_smjer'], 0, False)} dana.")
        s2 = (f"Snažno protiv tržišta {st['protiv']} od {st['obojanih']} zelenih i crvenih dana, uz tržište {st['uz']}."
              + (" " + T.WORDING if st["oznaka"] else ""))
        fig = timeline(con, days, 90, now, token=mint, events=ev, tok_closes=_token_closes(mint))
        return (CSS + '<section><h2>Tržište i ovaj token</h2>'
                + f'<p>{esc(s1)} {esc(s2)}</p>{fig}<p class=mut><a href="/trziste">Tržište i tokeni</a></p></section>')
    finally:
        con.close()
