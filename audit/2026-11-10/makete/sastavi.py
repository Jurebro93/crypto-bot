#!/usr/bin/env python3
"""Makete mirnog dizajna (10.11.2026.): upisuje zajednički CSS, bočni izbornik, donju traku i graf u svaku maketu.

Svaka maketa (<zaslon>.html) ostaje samostalna datoteka (sve inline, bez vanjskih datoteka); ovaj skript samo
zamijeni blokove između oznaka, pa se jedna promjena stila prenese na svih pet:
    /*OSNOVA*/ ... /*OSNOVA-KRAJ*/       zajednički CSS (boje = varijable iz ui/html.py)
    <!--BOCNO a=kljuc--> ... <!--/BOCNO-->   bočni izbornik (računalo)
    <!--TRAKA a=kljuc--> ... <!--/TRAKA-->   donja traka (mobitel)
    <!--GRAF--> ... <!--/GRAF-->         graf vrijednosti walleta (Autopilot)
    <!--CRTEZ k=ime--> ... <!--/CRTEZ-->  drugi krug: grafovi i trake detalja (token, influencer, novčanik)
    <!--SLIKA k=ime--> ... <!--/SLIKA-->  drugi krug: slika nove makete na naslovnoj (iz snimke novo-<ime>-phone-fold.png)
Drugi krug (10.11.): naslovna, tokeni-popis, token, influenceri-ljestvica, influencer, novcanici, novcanik.
Naslovna je javna stranica: dobiva samo OSNOVA (bez trake i bočnog izbornika).
Pokretanje:  python3 audit/2026-11-10/makete/sastavi.py
"""
import math
import pathlib
import random
import re

HERE = pathlib.Path(__file__).resolve().parent
SCREENS = ("pregled", "tokeni", "influenceri", "autopilot", "izbornik",
           "naslovna", "tokeni-popis", "token", "influenceri-ljestvica", "influencer", "novcanici", "novcanik")

CSS = r"""
/* Boje: iste varijable kao ui/html.py (:root). Novo su samo veličine, razmaci i ritam. */
:root{--bg:#fff;--soft:#f6f7fb;--card:#fff;--fg:#0b1220;--mut:#5b6474;--line:#e8ebf2;--line2:#cfd5e1;--acc:#4f46e5;
 --good:#16a34a;--warn:#d97706;--bad:#dc2626;--goodbg:#ecfdf5;--warnbg:#fffbeb;--badbg:#fef2f2;
 --pad:20px;--font:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",system-ui,Inter,Roboto,sans-serif}
*{box-sizing:border-box}html,body{margin:0}
body{background:var(--bg);color:var(--fg);font:17px/1.4 var(--font);-webkit-font-smoothing:antialiased;
 font-variant-numeric:tabular-nums;letter-spacing:-.01em}
a{color:inherit;text-decoration:none}.acc{color:var(--acc)}.mut{color:var(--mut)}.pos{color:var(--good)}.neg{color:var(--bad)}
.nw{white-space:nowrap}
main{display:block;max-width:760px;margin:0 auto;padding:0 var(--pad) 120px}
/* naslov: velik, jedan po ekranu; desno najviše jedna ikona */
.top{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:52px 0 0}
h1{font-size:34px;line-height:1.1;font-weight:700;letter-spacing:-.03em;margin:0}
.sub{font-size:15px;color:var(--mut);margin:6px 0 0}
.ico{flex:none;width:38px;height:38px;border-radius:50%;background:var(--soft);display:grid;place-items:center}
.ico svg{width:19px;height:19px;fill:none;stroke:var(--fg);stroke-width:2;stroke-linecap:round}
/* glavni odgovor ekrana */
.hero{margin:24px 0 0}
.hero .lbl{font-size:15px;color:var(--mut);margin:0 0 2px}
.big{font-size:48px;line-height:1.05;font-weight:700;letter-spacing:-.035em}
.big small{font-size:22px;font-weight:600;color:var(--mut);letter-spacing:-.01em;margin-left:6px}
.hero .line{font-size:15px;color:var(--mut);margin:8px 0 0}
.panel{display:block;background:var(--soft);border-radius:18px;padding:18px 18px 16px;margin:20px 0 0}
.panel .name{font-size:28px;font-weight:700;letter-spacing:-.03em;line-height:1.15;display:flex;align-items:center;justify-content:space-between}
.panel .facts{font-size:15px;color:var(--mut);margin:4px 0 10px}
.panel p{margin:0;font-size:17px;line-height:1.4}
/* sekcije: razmak umjesto okvira */
h2{font-size:22px;font-weight:700;letter-spacing:-.025em;margin:40px 0 2px;display:flex;justify-content:space-between;align-items:baseline;gap:12px}
h2 a{font-size:15px;font-weight:500;color:var(--acc);letter-spacing:0}
.hint{font-size:15px;color:var(--mut);margin:12px 0 0;line-height:1.4}
/* redak popisa: ime + jedan redak objašnjenja lijevo, jedan broj desno */
.list{margin:0;padding:0;list-style:none}
.row{display:flex;align-items:center;gap:12px;min-height:64px;padding:11px 0;border-bottom:1px solid var(--line)}
.list>.row:last-child,.list>li:last-child>.row{border-bottom:0}
.row .m{flex:1;min-width:0}
.row .t{font-size:17px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row .s{font-size:15px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:1px}
.row .e{flex:none;text-align:right}
.row .v{font-size:17px;font-weight:600;white-space:nowrap}
.row .e .s{margin-top:1px}
.chev{flex:none;width:8px;height:8px;border-right:2px solid var(--line2);border-top:2px solid var(--line2);transform:rotate(45deg);margin:0 2px 0 0}
.rk{flex:none;width:24px;font-size:15px;color:var(--mut)}
.colhead{display:flex;justify-content:space-between;font-size:13px;color:var(--mut);padding:14px 0 6px;border-bottom:1px solid var(--line)}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--line2);margin:0 6px 1px 0;vertical-align:middle}
.dot.good{background:var(--good)}.dot.warn{background:var(--warn)}.dot.bad{background:var(--bad)}
.warn{color:var(--warn)}.danger{color:var(--bad)}
/* segmentirani izbor (jedan po ekranu) */
.seg{display:flex;background:var(--soft);border-radius:11px;padding:3px;margin:22px 0 0}
.seg a{flex:1;text-align:center;font-size:15px;padding:7px 0;border-radius:9px;white-space:nowrap}
.seg a.on{background:#fff;font-weight:600;box-shadow:0 1px 3px rgba(11,18,32,.12)}
.fld{display:flex;align-items:center;gap:8px;background:var(--soft);border-radius:11px;padding:9px 12px;color:var(--mut);font-size:17px;margin:14px 0 0}
.fld svg{width:17px;height:17px;fill:none;stroke:var(--mut);stroke-width:2;stroke-linecap:round;flex:none}
/* prekidač */
.sw{flex:none;width:51px;height:31px;border-radius:999px;background:var(--good);position:relative}
.sw::after{content:"";position:absolute;top:2px;right:2px;width:27px;height:27px;border-radius:50%;background:#fff;box-shadow:0 2px 4px rgba(0,0,0,.2)}
/* donja traka (mobitel): 5 mjesta, linijske ikone, jedna boja za aktivno */
.tabs{position:fixed;left:0;right:0;bottom:0;z-index:20;display:flex;background:rgba(255,255,255,.94);
 -webkit-backdrop-filter:blur(16px);backdrop-filter:blur(16px);border-top:1px solid var(--line);padding:7px 2px 24px}
.tabs a{flex:1;display:flex;flex-direction:column;align-items:center;gap:3px;font-size:11px;font-weight:500;color:var(--mut);letter-spacing:0}
.tabs a.on{color:var(--acc)}
.tabs svg{width:25px;height:25px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}
.tabs .badge{position:relative;display:block;height:25px}.tabs .badge::after{content:"";position:absolute;top:1px;right:-3px;width:8px;height:8px;border-radius:50%;background:var(--acc)}
/* bočni izbornik (računalo): isto što i donja traka + Više, ništa više */
.side{display:none}
.side .brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:17px;letter-spacing:-.02em;padding:4px 10px 18px}
.side .brand svg{width:26px;height:26px}
.side .fld{margin:0 0 14px;font-size:15px;padding:8px 10px}
.side nav a{display:flex;align-items:center;gap:11px;padding:9px 10px;border-radius:10px;font-size:15px;font-weight:500;color:var(--fg)}
.side nav a svg{width:20px;height:20px;fill:none;stroke:var(--mut);stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}
.side nav a.on{background:var(--soft);color:var(--acc);font-weight:600}.side nav a.on svg{stroke:var(--acc)}
.side .foot{margin:18px 0 0;padding:12px 0 0;border-top:1px solid var(--line)}
.side .foot a{display:block;padding:8px 10px;font-size:15px;color:var(--mut)}
@media(min-width:900px){
 body{display:grid;grid-template-columns:252px minmax(0,1fr)}
 .side{display:block;min-height:100vh;border-right:1px solid var(--line);padding:22px 12px;background:#fff}
 .tabs{display:none}
 main{width:100%;padding:0 48px 80px}
 .top{padding-top:40px}
 .wide{max-width:980px}
 .top .ico{display:none}
}
"""

_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true">{}</svg>'
ICONS = {
    "pregled": _SVG.format('<path d="M4 11l8-7 8 7"/><path d="M6 10v9h12v-9"/>'),
    "tokeni": _SVG.format('<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/>'),
    "influenceri": _SVG.format('<path d="M4 10v4l11 5V5L4 10z"/><path d="M15 9a4 4 0 0 1 0 6"/>'),
    "novcanici": _SVG.format('<rect x="3" y="6" width="18" height="13" rx="2"/><path d="M16 12h2"/>'),
    "autopilot": _SVG.format('<path d="M3.5 16a8.5 8.5 0 0 1 17 0"/><path d="M12 16l4.2-4.6"/><circle cx="12" cy="16" r="1.2"/>'),
    "vise": _SVG.format('<circle cx="5.5" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="18.5" cy="12" r="1.3"/>'),
}
SEARCH = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/></svg>'
LOGO = ('<svg viewBox="0 0 32 32" aria-hidden="true"><defs><linearGradient id="lgm" x1="0" y1="1" x2="1" y2="0">'
        '<stop offset="0" stop-color="#4f46e5"/><stop offset="1" stop-color="#06b6d4"/></linearGradient></defs>'
        '<rect width="32" height="32" rx="9" fill="url(#lgm)"/><circle cx="16" cy="16" r="9" fill="none" stroke="#fff" '
        'stroke-width="2" opacity=".55"/><circle cx="16" cy="16" r="4.5" fill="none" stroke="#fff" stroke-width="2"/>'
        '<circle cx="16" cy="16" r="1.6" fill="#fff"/></svg>')
# administrator (Jure): Autopilot umjesto Novčanika u traci; ostali korisnici zadržavaju Novčanike (Autopilot ne vide)
TABS = [("pregled", "Pregled"), ("tokeni", "Tokeni"), ("influenceri", "Influenceri"), ("autopilot", "Autopilot"), ("vise", "Više")]
# drugi krug: Novčanici se snimaju s trakom ostalih korisnika (Novčanici na mjestu Autopilota), da se vidi i ta inačica
TABS_OSTALI = [("pregled", "Pregled"), ("tokeni", "Tokeni"), ("influenceri", "Influenceri"), ("novcanici", "Novčanici"), ("vise", "Više")]
SIDE = [("pregled", "Pregled"), ("tokeni", "Tokeni"), ("influenceri", "Influenceri"), ("novcanici", "Novčanici"),
        ("autopilot", "Autopilot"), ("vise", "Više")]


def tabs(active):
    out = []
    for k, label in (TABS_OSTALI if active == "novcanici" else TABS):
        cls = ' class="on"' if k == active else ""
        icon = ICONS[k] if k != "vise" else f'<span class="badge">{ICONS[k]}</span>'
        out.append(f'<a{cls} href="#">{icon}{label}</a>')
    return '<nav class="tabs" aria-label="Glavni izbornik">' + "".join(out) + "</nav>"


def side(active):
    items = "".join(f'<a{" class=on" if k == active else ""} href="#">{ICONS[k]}{label}</a>' for k, label in SIDE)
    return (f'<aside class="side"><div class="brand">{LOGO}MemeSonar</div>'
            f'<div class="fld">{SEARCH}Traži</div><nav>{items}</nav>'
            '<div class="foot"><a href="#">Postavke</a></div></aside>')


def graf():
    """Vrijednost walleta 3.11. do 10.11. u SOL-u (PRIMJER: equity tablica grupe novac još nije spojena)."""
    rnd = random.Random(1011)
    n, dep_at = 84, 48                      # točka svaka 2 h; uplata +0,50 SOL 7.11. u 9 h
    pnl, vals = 0.0, []
    for i in range(n + 1):
        pnl += rnd.uniform(-0.009, 0.009) + 0.012 * math.sin(i / 7) / 7
        vals.append((1.50 if i < dep_at else 2.00) + pnl)
    shift = (vals[-1] - 1.996)
    vals = [v - shift * (i / n) for i, v in enumerate(vals)]
    lo, hi = 1.40, 2.10
    W, H = 1000, 200
    pts = [(i * (W - 8) / n, H - (v - lo) / (hi - lo) * H) for i, v in enumerate(vals)]
    line = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = line + f" L{W},{H} L0,{H} Z"
    dx = dep_at * (W - 8) / n
    yl = lambda v: (hi - v) / (hi - lo) * 100
    return (
        '<div class="chart"><div class="plot"><div class="pw">'
        '<svg viewBox="0 0 1000 200" preserveAspectRatio="none" aria-label="Vrijednost walleta, 7 dana">'
        '<defs><linearGradient id="gf" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#4f46e5" stop-opacity=".16"/>'
        '<stop offset="1" stop-color="#4f46e5" stop-opacity="0"/></linearGradient></defs>'
        + "".join(f'<line x1="0" y1="{yl(v) * 2:.1f}" x2="1000" y2="{yl(v) * 2:.1f}" stroke="#e8ebf2" stroke-width="1" '
                  'vector-effect="non-scaling-stroke"/>' for v in (1.5, 2.0)) +
        f'<line x1="{dx:.1f}" y1="0" x2="{dx:.1f}" y2="200" stroke="#cfd5e1" stroke-width="1.5" stroke-dasharray="4 4" vector-effect="non-scaling-stroke"/>'
        f'<path d="{area}" fill="url(#gf)"/>'
        f'<path d="{line}" fill="none" stroke="#4f46e5" stroke-width="2.2" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>'
        '</svg>'
        f'<span class="end" style="left:{pts[-1][0] / 10:.2f}%;top:{pts[-1][1] / 2:.2f}%"></span>'
        f'<span class="dep" style="left:{dx / 10:.1f}%">uplata +0,50</span></div>'
        + "".join(f'<span class="yl" style="top:{yl(v):.1f}%">{str(v).replace(".", ",")}</span>' for v in (1.5, 2.0)) +
        '</div><div class="ax"><span>3.11.</span><span>5.11.</span><span>7.11.</span><span>9.11.</span><span>sada</span></div></div>')


# ---------- drugi krug (10.11.): grafovi i trake detalja ---------------------------------------------------------
# Isti izgled kao graf() Autopilota: jedna os, linija 2 px, recesivna mreža, oznake osi 13 px desno, os x ispod.
# Brojke su PRIMJER (influencer: brojke s Jureove snimke; novčanik i token: lokalna kopija iz seed_app.py).

def _hr(v, d=0):
    t = f"{abs(v):,.{d}f}".replace(",", " ").replace(".", ",")
    return ("−" if v < 0 else "") + t


# 10.11.: kept outside the f-strings (a backslash inside an f-string expression needs Python 3.12; the suite checks 3.10/3.11)
DASH44, DASH65 = 'stroke-dasharray="4 4" ', 'stroke-dasharray="6 5" '


def _crt(series, lo, hi, ticks, xlabels, label, dots=(), vmark=None, area=True, end=True, H=200):
    """series: [(vals, boja, debljina, crtkano)], prva je glavna (ploha i točka na kraju). ticks: [(vrijednost, tekst)].
    dots: [(indeks u prvoj seriji, naslov)] oznake na liniji (npr. pozivi). vmark: (indeks, tekst) okomita crtkana crta."""
    W = 1000
    n = max(len(v) for v, *_ in series) - 1
    X = lambda i: i * (W - 8) / n
    Y = lambda v: H - (v - lo) / (hi - lo) * H
    out = [f'<div class="chart"><div class="plot"><div class="pw"><svg viewBox="0 0 {W} {H}" preserveAspectRatio="none" '
           f'aria-label="{label}">']
    for v, _t in ticks:
        out.append(f'<line x1="0" y1="{Y(v):.1f}" x2="{W}" y2="{Y(v):.1f}" stroke="{"#cfd5e1" if v == 0 else "#e8ebf2"}" '
                   f'stroke-width="1" {DASH44 if v == 0 else ""}vector-effect="non-scaling-stroke"/>')
    if vmark:
        out.append(f'<line x1="{X(vmark[0]):.1f}" y1="0" x2="{X(vmark[0]):.1f}" y2="{H}" stroke="#cfd5e1" stroke-width="1.5" '
                   'stroke-dasharray="4 4" vector-effect="non-scaling-stroke"/>')
    for k, (vals, col, w, dash) in enumerate(series):
        pts = [(X(i), Y(v)) for i, v in enumerate(vals)]
        line = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        if k == 0 and area:
            gid = "g" + label[:3].lower().replace(" ", "")
            out.append(f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{col}" '
                       f'stop-opacity=".14"/><stop offset="1" stop-color="{col}" stop-opacity="0"/></linearGradient></defs>'
                       f'<path d="{line} L{pts[-1][0]:.1f},{H} L0,{H} Z" fill="url(#{gid})"/>')
        out.append(f'<path d="{line}" fill="none" stroke="{col}" stroke-width="{w}" stroke-linejoin="round" '
                   f'{DASH65 if dash else ""}vector-effect="non-scaling-stroke"/>')
    out.append("</svg>")
    main = series[0][0]
    if end:
        out.append(f'<span class="end" style="left:{X(n) / 10:.2f}%;top:{Y(main[-1]) / H * 100:.2f}%"></span>')
    for i, t in dots:
        out.append(f'<span class="mk" title="{t}" style="left:{X(i) / 10:.2f}%;top:{Y(main[i]) / H * 100:.2f}%"></span>')
    if vmark:
        out.append(f'<span class="dep" style="left:{X(vmark[0]) / 10:.1f}%">{vmark[1]}</span>')
    out.append("</div>")
    out += [f'<span class="yl" style="top:{Y(v) / H * 100:.1f}%">{t}</span>' for v, t in ticks]
    out.append('</div><div class="ax">' + "".join(f"<span>{x}</span>" for x in xlabels) + "</div></div>")
    return "".join(out)


def _walk(anchors, n, rnd, noise):
    """Glatka nasumična putanja kroz zadane točke [(indeks, vrijednost)]."""
    vals = []
    for (i0, v0), (i1, v1) in zip(anchors, anchors[1:]):
        for i in range(i0, i1):
            f = (i - i0) / (i1 - i0)
            vals.append(v0 + (v1 - v0) * f)
    vals.append(anchors[-1][1])
    out, drift = [], 0.0
    for i, v in enumerate(vals):
        drift = drift * 0.7 + rnd.uniform(-noise, noise)
        pin = min(1.0, min(abs(i - a) for a, _ in anchors) / 3)
        out.append(v * (1 + drift * pin))
    return out[:n + 1]


def graf_token():
    """GIGAFROG, mcap zadnja 24 h (točka svakih 15 min): 170k prije 24 h, 259k prije 6 h, 349k prije 1 h, 412k sada
    (24 h +142 %, 6 h +59 %, 1 h +18 % kao na snimci tokena). Točke = pozivi influencera."""
    rnd = random.Random(94)
    v = _walk([(0, 170e3), (24, 151e3), (44, 205e3), (60, 214e3), (72, 259e3), (92, 349e3), (96, 412e3)], 96, rnd, 0.035)
    v[-1] = 412e3
    return _crt([(v, "#4f46e5", 2.2, False)], 100e3, 450e3, [(200e3, "200k"), (400e3, "400k")],
                ["8:00", "14:00", "20:00", "2:00", "sada"], "Mcap GIGAFROG, 24 h",
                dots=[(52, "@bitecong, prvi poziv"), (64, "@PumpWatch1"), (88, "@TortillasTown"), (93, "@Humanevolvd")])


def _kol_calls():
    """30 poziva u 14 dana: 21 do +10 % u prvom satu (+1 $ na 10 $), 8 stopova (−2 $), 1 prodan nakon 60 min (−2 $)
    = +3 $. Nakon 24 h: 2 u plusu (+30 %, +12 %), 28 u minusu, zbroj −185 $ (Jureova snimka 10.11.)."""
    rnd = random.Random(30)
    hits = set(rnd.sample(range(30), 21))
    quick = [1.0 if i in hits else -2.0 for i in range(30)]
    plus = sorted(rnd.sample(sorted(hits), 2))
    w = [rnd.uniform(0.35, 1.0) for _ in range(28)]
    tot = -185.0 - (3.0 + 1.2)
    neg = [max(-10.0, tot * x / sum(w)) for x in w]
    neg[-1] += tot - sum(neg)
    day, it = [], iter(neg)
    for i in range(30):
        day.append(3.0 if i == plus[0] else 1.2 if i == plus[1] else next(it))
    return quick, day


def graf_kol():
    quick, day = _kol_calls()
    a, b = [0.0], [0.0]
    for q, d in zip(quick, day):
        a.append(a[-1] + q)
        b.append(b[-1] + d)
    return _crt([(a, "#4f46e5", 2.2, False), (b, "#5b6474", 2, False)], -200, 25,
                [(0, "0 $"), (-100, "−100"), (-200, "−200")], ["27.10.", "31.10.", "3.11.", "7.11.", "10.11."],
                "Deset dolara u svaki poziv", area=False)


def _traka(vals, naslov):
    cells = "".join(f'<i class="{"p" if x > 0 else "n"}"></i>' for x in vals)
    return f'<div class="strip"><span class="sl">{naslov}</span><span class="sq">{cells}</span></div>'


def traka_kol():
    quick, day = _kol_calls()
    return (_traka(quick, "1 h") + _traka(day, "24 h"))


def _novcanik_trades():
    """31 zatvorena pozicija Vfdn…At74: 20 prije reza (5.11.) = +7,40 SOL, 11 poslije = +4,46 SOL; 21 u plusu."""
    rnd = random.Random(31)
    def grp(n, n_plus, total):
        idx = set(rnd.sample(range(n), n_plus))
        v = [rnd.uniform(0.12, 1.3) if i in idx else -rnd.uniform(0.05, 0.45) for i in range(n)]
        k = max(idx)
        v[k] += total - sum(v)
        return v
    return grp(20, 14, 7.40) + grp(11, 7, 4.46)


def graf_novcanik():
    t = _novcanik_trades()
    c = [0.0]
    for x in t:
        c.append(c[-1] + x)
    return _crt([(c, "#4f46e5", 2.2, False)], -1, 13.5, [(0, "0"), (5, "5"), (10, "10")],
                ["22.10.", "27.10.", "1.11.", "5.11.", "10.11."], "Zarada na zatvorenima, SOL", vmark=(20, "rez 5.11."))


def traka_novcanik():
    return _traka(_novcanik_trades(), "")


# naslovna: prave slike novih ekrana (prvi ekran mobitela iz snimi.js), umetnute kao JPEG, da maketa ostane jedna datoteka.
# Redoslijed: snimi.js za ostale makete, pa sastavi.py, pa snimi.js --only naslovna.
SHOTS = pathlib.Path(__import__("os").environ.get(
    "UIPROP_SHOTS", "/tmp/claude-0/-home-user/4912361d-d525-5b3e-b714-652a838e02b7/scratchpad/shots/ui"))
SLIKE = {"tokeni": "Tokeni", "influencer": "Profil influencera", "novcanik": "Novčanik"}


def slika(k):
    src = SHOTS / f"novo-{k}-phone-fold.png"
    if not src.exists():
        return f'<div class="ph-missing">{SLIKE[k]}</div>'
    import base64
    import io
    from PIL import Image
    im = Image.open(src).convert("RGB")
    im = im.resize((360, round(im.size[1] * 360 / im.size[0])), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=74, optimize=True, progressive=True)
    return (f'<img alt="{SLIKE[k]}, nova maketa" width="180" height="390" loading="lazy" '
            f'src="data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}">')


CRTEZI = {"token": graf_token, "kol": graf_kol, "kol-traka": traka_kol, "novcanik": graf_novcanik,
          "novcanik-traka": traka_novcanik}


def fill(text, key):
    text = re.sub(r"/\*OSNOVA\*/.*?/\*OSNOVA-KRAJ\*/", lambda m: "/*OSNOVA*/" + CSS + "/*OSNOVA-KRAJ*/", text, flags=re.S)
    text = re.sub(r"<!--BOCNO a=(\w+)-->.*?<!--/BOCNO-->",
                  lambda m: f"<!--BOCNO a={m.group(1)}-->{side(m.group(1))}<!--/BOCNO-->", text, flags=re.S)
    text = re.sub(r"<!--TRAKA a=(\w+)-->.*?<!--/TRAKA-->",
                  lambda m: f"<!--TRAKA a={m.group(1)}-->{tabs(m.group(1))}<!--/TRAKA-->", text, flags=re.S)
    text = re.sub(r"<!--GRAF-->.*?<!--/GRAF-->", lambda m: "<!--GRAF-->" + graf() + "<!--/GRAF-->", text, flags=re.S)
    text = re.sub(r"<!--CRTEZ k=([\w-]+)-->.*?<!--/CRTEZ-->",
                  lambda m: f"<!--CRTEZ k={m.group(1)}-->{CRTEZI[m.group(1)]()}<!--/CRTEZ-->", text, flags=re.S)
    text = re.sub(r"<!--SLIKA k=([\w-]+)-->.*?<!--/SLIKA-->",
                  lambda m: f"<!--SLIKA k={m.group(1)}-->{slika(m.group(1))}<!--/SLIKA-->", text, flags=re.S)
    return text


if __name__ == "__main__":
    for k in SCREENS:
        p = HERE / f"{k}.html"
        if p.exists():
            old = p.read_text(encoding="utf-8")
            new = fill(old, k)
            if new != old:
                p.write_text(new, encoding="utf-8")
            print(k, "ok" if new != old else "bez promjene")
