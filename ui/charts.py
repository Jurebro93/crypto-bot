"""Small server-rendered charts: a line over time and a diverging bar per event (gain up, loss down).

Plain SVG stretched to the box width (preserveAspectRatio=none, strokes don't scale) with axis labels in HTML so
text stays readable on a phone. One shared script adds the hover/tap read-out: crosshair + tooltip for lines,
per-bar highlight + tooltip for bars. Every chart has a "Prikaži kao tablicu" view with the same numbers.

Colors follow the dataviz palette: series 1 blue, series 2 orange (validated light + dark); bars diverge
blue (gain) / red (loss) around a gray zero line. Text never wears a series color.
"""
import datetime as dt
import json
import math

from ui.html import esc

W = 1000


def _fmt(v, f):
    if v is None:
        return "–"
    if f == "usd":
        return f"{'−' if v < 0 else ''}${abs(v):,.2f}" if abs(v) < 1000 else f"{'−' if v < 0 else ''}${abs(v):,.0f}"
    if f == "usd+":
        return f"{'+' if v >= 0 else '−'}${abs(v):,.2f}"
    if f == "pct":
        return f"{v * 100:+,.0f}%"
    if f == "sol":
        return f"{v:+,.2f} SOL"
    if f == "x":
        return f"{v:.2f}×"
    return f"{v:,.0f}" if abs(v) >= 10 else f"{v:,.1f}"


def _tick_fmt(v, f):
    if f in ("usd", "usd+"):
        a = abs(v)
        s = f"${a / 1000:,.1f}k" if a >= 10000 else f"${a:,.0f}"
        return ("−" if v < 0 else "") + s
    if f == "pct":
        return f"{v * 100:+,.0f}%"
    if f == "sol":
        return f"{v:+,.1f}"
    return f"{v:,.0f}" if abs(v) >= 10 else f"{v:,.1f}"


def _nice(lo, hi, n=4):
    if hi - lo < 1e-12:
        hi, lo = hi + (abs(hi) or 1) * 0.1, lo - (abs(lo) or 1) * 0.1
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    a, b = math.floor(lo / step) * step, math.ceil(hi / step) * step
    ticks, t = [], a
    while t <= b + step / 2:
        ticks.append(round(t, 10))
        t += step
    return a, b, ticks


def _date(t):
    return dt.datetime.utcfromtimestamp(t).strftime("%d.%m.")


def _datetime(t):
    return dt.datetime.utcfromtimestamp(t).strftime("%d.%m. %H:%M")


def _frame(title, sub, legend, plot, x_labels, table_rows, table_head, data, cls):
    xl = "".join(f"<span>{esc(x)}</span>" for x in x_labels)
    tbl = ("<details class=chtbl><summary>Prikaži kao tablicu</summary><div class=tw><table class=nocols><thead><tr>"
           + "".join(f"<th>{esc(h)}</th>" for h in table_head) + "</tr></thead><tbody>"
           + "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>" for r in table_rows)
           + "</tbody></table></div></details>")
    return (f'<figure class="ch {cls}"><figcaption><b>{esc(title)}</b>'
            + (f'<span class=mut>{sub}</span>' if sub else "") + "</figcaption>" + legend
            + f"<div class=chp data-ch='{esc(json.dumps(data, separators=(',', ':')))}'>{plot}"
            + "<i class=chc hidden></i><div class=cht hidden></div></div>"
            + f"<div class=chx>{xl}</div>{tbl}</figure>")


def line(series, title, sub="", fmt="num", base=None, base_label="", height=170, ymin=None, ymax=None):
    """series: [{"name", "pts": [(unix_ts, value), …]}] (1-2 series, same unit). base: dashed reference line."""
    series = [s for s in series if len(s["pts"]) >= 2][:2]
    if not series:
        return ""
    allv = [v for s in series for _, v in s["pts"]] + ([base] if base is not None else [])
    t0 = min(t for s in series for t, _ in s["pts"])
    t1 = max(t for s in series for t, _ in s["pts"])
    span = max(1, t1 - t0)
    lo, hi, ticks = _nice(min(allv) if ymin is None else ymin, max(allv) if ymax is None else ymax)
    H = 100

    def X(t):
        return W * (t - t0) / span

    def Y(v):
        return H - H * (v - lo) / (hi - lo)
    grid = "".join(f'<line x1=0 x2={W} y1={Y(v):.2f} y2={Y(v):.2f} class=chg />' for v in ticks)
    ref = (f'<line x1=0 x2={W} y1={Y(base):.2f} y2={Y(base):.2f} class=chb />' if base is not None else "")
    paths = "".join(
        f'<polyline class="chl s{i + 1}" points="{" ".join(f"{X(t):.1f},{Y(v):.2f}" for t, v in s["pts"])}" />'
        for i, s in enumerate(series))
    ylab = "".join(f'<span class=chy style="top:{100 * Y(v) / H:.2f}%">{esc(_tick_fmt(v, fmt))}</span>' for v in ticks)
    plot = (f'<svg viewBox="0 0 {W} {H}" preserveAspectRatio=none style="height:{height}px" role=img '
            f'aria-label="{esc(title)}">{grid}{ref}{paths}</svg>{ylab}'
            + (f'<span class=chbl style="top:{100 * Y(base) / H:.2f}%">{esc(base_label)}</span>' if base_label and base is not None else ""))
    # one read-out row per distinct time, every series' value at that time (last known)
    times = sorted({t for s in series for t, _ in s["pts"]})
    rows, cur = [], [None] * len(series)
    iters = [iter(sorted(s["pts"])) for s in series]
    nxt = [next(it, None) for it in iters]
    for t in times:
        for i, it in enumerate(iters):
            while nxt[i] is not None and nxt[i][0] <= t:
                cur[i] = nxt[i][1]
                nxt[i] = next(it, None)
        rows.append((t, list(cur)))
    data = {"t": "l", "x": [round(X(t) / W, 4) for t, _ in rows],
            "y": [[(round(Y(v) / H, 4) if v is not None else None) for v in vs] for _, vs in rows],
            "lab": [_datetime(t) for t, _ in rows], "n": [s["name"] for s in series],
            "v": [[_fmt(v, fmt) for v in vs] for _, vs in rows]}
    legend = ""
    if len(series) > 1:
        legend = "<div class=chlg>" + "".join(
            f'<span><i class="s{i + 1}"></i>{esc(s["name"])} <b>{esc(_fmt(s["pts"][-1][1], fmt))}</b></span>'
            for i, s in enumerate(series)) + "</div>"
    xl = [_date(t0), _date(t0 + span / 2), _date(t1)] if span > 86400 else [_datetime(t0), _datetime(t1)]
    trows = [[_datetime(t)] + [_fmt(v, fmt) for v in vs] for t, vs in reversed(rows)]
    return _frame(title, sub, legend, plot, xl, trows, ["Vrijeme"] + [s["name"] for s in series], data, "chline")


def bars(items, title, sub="", fmt="pct", height=150, cap=None):
    """items: [(unix_ts, label, value)] oldest first; one bar each, up = gain (blue), down = loss (red).
    cap: values beyond ±cap are drawn at the cap (the read-out and table keep the real number)."""
    items = [i for i in items if i[2] is not None]
    if len(items) < 2:
        return ""
    vals = [v for _, _, v in items]
    if cap is None:
        s = sorted(abs(v) for v in vals)
        p90 = s[int(0.9 * (len(s) - 1))]
        cap = max(p90 * 1.5, 1e-9) if s[-1] > p90 * 2 else None
    cl = [max(-cap, min(cap, v)) if cap else v for v in vals]
    lo, hi, ticks = _nice(min(0, min(cl)), max(0, max(cl)), 3)
    H = 100

    def Y(v):
        return H - H * (v - lo) / (hi - lo)
    n = len(items)
    slot = W / n
    gap = min(slot * 0.25, 6)
    grid = "".join(f'<line x1=0 x2={W} y1={Y(v):.2f} y2={Y(v):.2f} class=chg />' for v in ticks if abs(v) > 1e-12)
    zero = f'<line x1=0 x2={W} y1={Y(0):.2f} y2={Y(0):.2f} class=chz />'
    rects = []
    for i, v in enumerate(cl):
        y0, y1 = sorted((Y(0), Y(v)))
        h = max(y1 - y0, 0.6)
        rects.append(f'<rect data-i={i} class="{"up" if v >= 0 else "dn"}" x="{i * slot + gap / 2:.2f}" '
                     f'y="{y0 if v >= 0 else Y(0):.2f}" width="{max(slot - gap, 1):.2f}" height="{h:.2f}" />')
    ylab = "".join(f'<span class=chy style="top:{100 * Y(v) / H:.2f}%">{esc(_tick_fmt(v, fmt))}</span>' for v in ticks)
    plot = (f'<svg viewBox="0 0 {W} {H}" preserveAspectRatio=none style="height:{height}px" role=img '
            f'aria-label="{esc(title)}">{grid}{zero}{"".join(rects)}</svg>{ylab}')
    data = {"t": "b", "x": [round((i + 0.5) / n, 4) for i in range(n)],
            "lab": [f"{_datetime(t)} · {lab}" for t, lab, _ in items], "n": [""],
            "v": [[_fmt(v, fmt) + (" (vrh grafa odrezan)" if cap and abs(v) > cap else "")] for v in vals]}
    up = sum(1 for v in vals if v > 0)
    legend = (f'<div class=chlg><span><i class=up></i>u plusu <b>{up}</b></span>'
              f'<span><i class=dn></i>u minusu <b>{n - up}</b></span></div>')
    t0, t1 = items[0][0], items[-1][0]
    xl = [_date(t0), _date(t1)] if t1 - t0 > 86400 else [_datetime(t0), _datetime(t1)]
    trows = [[_datetime(t), lab, _fmt(v, fmt)] for t, lab, v in reversed(items)]
    return _frame(title, sub, legend, plot, xl, trows, ["Vrijeme", "Što", "Vrijednost"], data, "chbar")


CSS = """
.ch{margin:12px 0 18px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px 8px}
.ch figcaption{display:flex;flex-wrap:wrap;gap:4px 10px;align-items:baseline;margin-bottom:6px}.ch figcaption .mut{font-size:13px}
.chp{position:relative;margin-left:46px;touch-action:pan-y;cursor:crosshair}.chp svg{display:block;width:100%;overflow:visible}
.chg{stroke:var(--line);stroke-width:1;vector-effect:non-scaling-stroke}
.chz{stroke:var(--mut);stroke-opacity:.6;stroke-width:1;vector-effect:non-scaling-stroke}
.chb{stroke:var(--mut);stroke-width:1;stroke-dasharray:5 4;vector-effect:non-scaling-stroke}
.chl{fill:none;stroke-width:2;vector-effect:non-scaling-stroke;stroke-linejoin:round;stroke-linecap:round}
.chl.s1{stroke:#2a78d6}.chl.s2{stroke:#eb6834}.chbar rect.up{fill:#2a78d6}.chbar rect.dn{fill:#e34948}
.chbar rect{transition:opacity .1s}.chbar.hov rect{opacity:.35}.chbar.hov rect.on{opacity:1}
.chy{position:absolute;right:calc(100% + 6px);transform:translateY(-50%);font-size:11px;color:var(--mut);white-space:nowrap;font-variant-numeric:tabular-nums}
.chbl{position:absolute;right:2px;transform:translateY(-120%);font-size:11px;color:var(--mut)}
.chx{display:flex;justify-content:space-between;margin-left:46px;font-size:11px;color:var(--mut);padding-top:3px}
.chlg{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:13px;margin:0 0 6px}.chlg i{display:inline-block;width:14px;height:3px;border-radius:2px;vertical-align:middle;margin-right:5px}
.chlg i.s1,.chlg i.up{background:#2a78d6}.chlg i.s2{background:#eb6834}.chlg i.dn{background:#e34948}.chlg i.up,.chlg i.dn{height:10px;width:10px;border-radius:2px}
.chc{position:absolute;top:0;bottom:0;width:1px;background:var(--mut);opacity:.6;pointer-events:none}
.chd{position:absolute;width:9px;height:9px;border-radius:50%;transform:translate(-50%,-50%);border:2px solid var(--card);pointer-events:none}
.chd.s1{background:#2a78d6}.chd.s2{background:#eb6834}
.cht{position:absolute;top:0;z-index:5;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px 9px;font-size:12px;
 box-shadow:0 4px 14px rgba(0,0,0,.15);pointer-events:none;white-space:nowrap;min-width:110px}
.cht b{font-size:14px;font-variant-numeric:tabular-nums}.cht .r{display:flex;gap:6px;align-items:center}.cht .r i{width:12px;height:2px;display:inline-block}
.chtbl{margin-top:6px;font-size:13px}.chtbl .tw{max-height:260px;overflow:auto;margin-top:6px}
@media (prefers-color-scheme:dark){.chl.s1{stroke:#3987e5}.chl.s2{stroke:#d95926}.chbar rect.up{fill:#3987e5}.chbar rect.dn{fill:#e66767}
.chlg i.s1,.chlg i.up,.chd.s1{background:#3987e5}.chlg i.s2,.chd.s2{background:#d95926}.chlg i.dn{background:#e66767}}
"""

JS = r"""
(()=>{const C={};document.addEventListener('pointermove',mv,{passive:true});document.addEventListener('pointerdown',mv,{passive:true});
function mv(e){const p=e.target.closest&&e.target.closest('.chp');document.querySelectorAll('.chp.act').forEach(q=>{if(q!==p)hide(q)});if(p)show(p,e)}
function hide(p){p.classList.remove('act');p.querySelector('.chc').hidden=true;p.querySelector('.cht').hidden=true;
 p.querySelectorAll('.chd').forEach(d=>d.remove());const f=p.closest('.ch');f.classList.remove('hov');p.querySelectorAll('rect.on').forEach(r=>r.classList.remove('on'))}
function show(p,e){const d=p._d||(p._d=JSON.parse(p.dataset.ch)),r=p.getBoundingClientRect(),fx=(e.clientX-r.left)/r.width;
 let i=0,b=1e9;d.x.forEach((x,j)=>{const k=Math.abs(x-fx);if(k<b){b=k;i=j}});p.classList.add('act');
 const tip=p.querySelector('.cht'),cx=d.x[i]*r.width;tip.replaceChildren();
 const h=document.createElement('div');h.className='mut';h.textContent=d.lab[i];tip.appendChild(h);
 d.v[i].forEach((v,s)=>{const row=document.createElement('div');row.className='r';if(d.n.length>1){const k=document.createElement('i');
  k.className='s'+(s+1);row.appendChild(k)}
  const bb=document.createElement('b');bb.textContent=v;row.appendChild(bb);if(d.n[s]&&d.n.length>1){const nn=document.createElement('span');nn.className='mut';nn.textContent=d.n[s];row.appendChild(nn)}
  tip.appendChild(row)});
 tip.querySelectorAll('.r i').forEach((k,s)=>{k.style.background=s?'#eb6834':'#2a78d6'});
 tip.hidden=false;const tw=tip.offsetWidth;tip.style.left=Math.max(0,Math.min(r.width-tw,cx+12>r.width-tw?cx-tw-12:cx+12))+'px';
 if(d.t==='l'){const c=p.querySelector('.chc');c.hidden=false;c.style.left=cx+'px';p.querySelectorAll('.chd').forEach(x=>x.remove());
  const sh=p.querySelector('svg').getBoundingClientRect().height;
  d.y[i].forEach((y,s)=>{if(y==null)return;const dot=document.createElement('i');dot.className='chd s'+(s+1);dot.style.left=cx+'px';dot.style.top=(y*sh)+'px';p.appendChild(dot)})}
 else{const f=p.closest('.ch');f.classList.add('hov');p.querySelectorAll('rect.on').forEach(x=>x.classList.remove('on'));const rc=p.querySelector('rect[data-i="'+i+'"]');if(rc)rc.classList.add('on')}}
})();
"""
