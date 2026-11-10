#!/usr/bin/env python3
"""Makete mirnog dizajna (10.11.2026.): upisuje zajednički CSS, bočni izbornik, donju traku i graf u svaku maketu.

Svaka maketa (<zaslon>.html) ostaje samostalna datoteka (sve inline, bez vanjskih datoteka); ovaj skript samo
zamijeni blokove između oznaka, pa se jedna promjena stila prenese na svih pet:
    /*OSNOVA*/ ... /*OSNOVA-KRAJ*/       zajednički CSS (boje = varijable iz ui/html.py)
    <!--BOCNO a=kljuc--> ... <!--/BOCNO-->   bočni izbornik (računalo)
    <!--TRAKA a=kljuc--> ... <!--/TRAKA-->   donja traka (mobitel)
    <!--GRAF--> ... <!--/GRAF-->         graf vrijednosti walleta (Autopilot)
Pokretanje:  python3 audit/2026-11-10/makete/sastavi.py
"""
import math
import pathlib
import random
import re

HERE = pathlib.Path(__file__).resolve().parent
SCREENS = ("pregled", "tokeni", "influenceri", "autopilot", "izbornik")

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
SIDE = [("pregled", "Pregled"), ("tokeni", "Tokeni"), ("influenceri", "Influenceri"), ("novcanici", "Novčanici"),
        ("autopilot", "Autopilot"), ("vise", "Više")]


def tabs(active):
    out = []
    for k, label in TABS:
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


def fill(text, key):
    text = re.sub(r"/\*OSNOVA\*/.*?/\*OSNOVA-KRAJ\*/", lambda m: "/*OSNOVA*/" + CSS + "/*OSNOVA-KRAJ*/", text, flags=re.S)
    text = re.sub(r"<!--BOCNO a=(\w+)-->.*?<!--/BOCNO-->",
                  lambda m: f"<!--BOCNO a={m.group(1)}-->{side(m.group(1))}<!--/BOCNO-->", text, flags=re.S)
    text = re.sub(r"<!--TRAKA a=(\w+)-->.*?<!--/TRAKA-->",
                  lambda m: f"<!--TRAKA a={m.group(1)}-->{tabs(m.group(1))}<!--/TRAKA-->", text, flags=re.S)
    text = re.sub(r"<!--GRAF-->.*?<!--/GRAF-->", lambda m: "<!--GRAF-->" + graf() + "<!--/GRAF-->", text, flags=re.S)
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
