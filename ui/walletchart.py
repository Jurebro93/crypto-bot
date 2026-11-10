"""Graf "Kako je zarađivao" jednog novčanika s crtkanom crtom reza i traka svih zatvorenih pozicija.

10.11. (Jure, prijedlog 4.7, maketa audit/2026-11-10/makete/novcanik.html): "dokazan dvaput" je glavni razlog zašto
Autopilot broji kupnje novčanika, a na stranici se nije vidio. Graf pokazuje zbroj ostvarene zarade nakon svake
zatvorene pozicije i okomitu crtu reza (wallets/dokazani: prije reza i poslije njega), traka svaku zatvorenu poziciju
kao zeleni ili crveni kvadratić. Mjere i boje su prepisane iz makete; boje idu kroz varijable iz ui/html.py.

Statični SVG s poslužitelja, bez JS-a (stranica se ne mijenja dok je otvorena). Zajedničke funkcije ui/charts.py
se ne diraju: ovaj modul je samo za stranicu novčanika.
"""
import datetime as dt
import math

from ui.redak import Html, h, num

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Zagreb")      # dan je Jurin dan, kao u ui/sitelog.py
except Exception:  # noqa: BLE001 - bez baze vremenskih zona ostaje lokalno vrijeme procesa
    TZ = None

W, HT, TOP, BOT, RIGHT = 1000.0, 200.0, 22.0, 14.0, 8.0   # viewBox kao u maketi; desno mjesto za točku kraja
STRIP_MAX = 200          # traka: zadnjih 200 pozicija (stari stupčasti graf je imao isti rez)
STRIP_COLS = 40          # više od 40 kvadratića u retku postanu crte; dalje se lome u novi red

CSS = """<style>
.wc{margin:14px 0 0}
.wc .plot{position:relative;padding-right:30px}.wc .pw{position:relative}
.wc svg{display:block;width:100%;height:170px;overflow:visible}
.wc .zero{stroke:var(--line2);stroke-width:1;stroke-dasharray:4 4}.wc .grid{stroke:var(--line);stroke-width:1}
.wc .cut{stroke:var(--line2);stroke-width:1.5;stroke-dasharray:4 4}
.wc .ln{fill:none;stroke:var(--acc);stroke-width:2.2;stroke-linejoin:round}.wc .ar{fill:url(#wc-g)}
.wc .end{position:absolute;width:10px;height:10px;margin:-5px 0 0 -5px;border-radius:50%;background:var(--acc);box-shadow:0 0 0 3px #fff}
.wc .yl{position:absolute;right:0;transform:translateY(-50%);font-size:13px;color:var(--mut)}
.wc .dep{position:absolute;top:-2px;font-size:13px;color:var(--mut);transform:translateX(6px);white-space:nowrap}
.wc .dep.l{transform:translateX(calc(-100% - 6px))}
.wc .ax{display:flex;justify-content:space-between;font-size:13px;color:var(--mut);padding:8px 30px 0 0}
.wc-split{display:flex;flex-wrap:wrap;gap:4px 18px;font-size:15px;color:var(--mut);margin:12px 0 0}
.wc-split b{font-weight:600}.wc-split .pos{color:var(--good)}.wc-split .neg{color:var(--bad)}
.ws{display:grid;gap:2px;margin:12px 0 0}
.ws i{display:block;height:16px;border-radius:3px;background:var(--good)}.ws i.n{background:var(--bad)}
.ws-k{display:flex;justify-content:space-between;gap:10px;font-size:13px;color:var(--mut);margin:8px 0 0}
@media(min-width:900px){.wc svg{height:200px}}
</style>"""


def day(ts, with_time=False):
    """"5.11." (ili "5.11. 07:10") u Jurinom vremenu; prazno za None."""
    if not ts:
        return ""
    d = dt.datetime.fromtimestamp(ts, TZ) if TZ else dt.datetime.fromtimestamp(ts)
    return f"{d.day}.{d.month}." + (f" {d:%H:%M}" if with_time else "")


def clock(ts):
    """"07:10" u Jurinom vremenu."""
    d = dt.datetime.fromtimestamp(ts, TZ) if TZ else dt.datetime.fromtimestamp(ts)
    return f"{d:%H:%M}"


def ticks(lo, hi):
    """Okrugle oznake osi y između lo i hi: najveći korak 1, 2 ili 5 puta 10^k koji daje barem tri oznake,
    npr. (0, 11.9) -> [0, 5, 10], (−9, 11) -> [−5, 0, 5, 10]."""
    span = hi - lo
    if span <= 0:
        return [lo]
    top = math.floor(math.log10(span))
    for k in range(top, top - 4, -1):
        for m in (5, 2, 1):
            step = m * 10 ** k
            first = math.ceil(lo / step - 1e-9) * step
            out = []
            v = first
            while v <= hi + 1e-9:
                out.append(round(v, 10) + 0.0)
                v += step
            if len(out) >= 3:
                return out
    return [lo, hi]


def _dec(step):
    return 0 if step >= 1 else 1 if step >= 0.1 else 2


def earnings(points, cut=None, label="Zarada na zatvorenima, SOL"):
    """Linija zbroja ostvarene zarade u SOL-u s površinom ispod, nulom (crtkano), mrežom na okruglim brojevima,
    točkom na kraju i, ako je zadan, okomitom crtkanom crtom reza (cut: unix sekunde) s natpisom "rez 5.11.".

    points: [(ts, zbroj SOL)] po vremenu (prva točka je obično 0 prije prve prodaje). Manje od dvije točke -> "".
    Vraća Html."""
    pts = sorted((float(t), float(v)) for t, v in points or () if t is not None and v is not None)
    if len(pts) < 2:
        return Html("")
    t0, t1 = pts[0][0], pts[-1][0]
    if not (cut and t0 < cut < t1):
        cut = None
    vals = [v for _, v in pts]
    lo, hi = min(0.0, min(vals)), max(0.0, max(vals))
    if hi - lo < 1e-9:
        hi = lo + 1.0
    span_t = (t1 - t0) or 1.0
    inner = HT - TOP - BOT

    def x(t):
        return (t - t0) / span_t * (W - RIGHT)

    def y(v):
        return TOP + (hi - v) / (hi - lo) * inner

    marks = ticks(lo, hi)
    step = (marks[1] - marks[0]) if len(marks) > 1 else 1
    svg = []
    for m in marks:
        cls = "zero" if abs(m) < 1e-9 else "grid"
        svg.append(f'<line class="{cls}" x1="0" y1="{y(m):.1f}" x2="{W:.0f}" y2="{y(m):.1f}" vector-effect="non-scaling-stroke"/>')
    if cut:
        svg.append(f'<line class="cut" x1="{x(cut):.1f}" y1="0" x2="{x(cut):.1f}" y2="{HT:.0f}" vector-effect="non-scaling-stroke"/>')
    line = " ".join(f"{'M' if i == 0 else 'L'}{x(t):.1f},{y(v):.1f}" for i, (t, v) in enumerate(pts))
    svg.append('<defs><linearGradient id="wc-g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" style="stop-color:var(--acc);'
               'stop-opacity:.14"/><stop offset="1" style="stop-color:var(--acc);stop-opacity:0"/></linearGradient></defs>')
    svg.append(f'<path class="ar" d="{line} L{x(t1):.1f},{HT:.0f} L0,{HT:.0f} Z"/>')
    svg.append(f'<path class="ln" d="{line}" vector-effect="non-scaling-stroke"/>')
    end = (f'<span class="end" style="left:{x(t1) / W * 100:.2f}%;top:{y(pts[-1][1]) / HT * 100:.2f}%"></span>')
    dep = ""
    if cut:
        left = x(cut) / W * 100
        dep = f'<span class="dep{" l" if left > 82 else ""}" style="left:{left:.1f}%">rez {h(day(cut))}</span>'
    yl = "".join(f'<span class="yl" style="top:{y(m) / HT * 100:.1f}%">{h(num(m, _dec(step)))}</span>' for m in marks)
    n_ax = 5
    short = span_t < 36 * 3600
    ax = "".join(f"<span>{h(clock(t0 + span_t * i / (n_ax - 1)) if short else day(t0 + span_t * i / (n_ax - 1)))}</span>"
                 for i in range(n_ax))
    return Html(f'<div class="wc"><div class="plot"><div class="pw"><svg viewBox="0 0 {W:.0f} {HT:.0f}" '
                f'preserveAspectRatio="none" role="img" aria-label="{h(label)}">{"".join(svg)}</svg>{end}{dep}</div>'
                f'{yl}</div><div class="ax">{ax}</div></div>')


def strip(results, first_ts=None, last_ts=None):
    """Traka: jedan kvadratić po zatvorenoj poziciji po vremenu, zeleno u plusu, crveno u minusu (zadnjih
    STRIP_MAX), ispod "22.10. · 21 u plusu · 10 u minusu · 10.11.". results: [True/False]. Prazno -> ""."""
    res = list(results or ())[-STRIP_MAX:]
    if not res:
        return Html("")
    wins = sum(1 for r in res if r)
    cols = min(len(res), STRIP_COLS)
    sq = "".join('<i></i>' if r else '<i class="n"></i>' for r in res)
    k = f"{num(wins)} u plusu · {num(len(res) - wins)} u minusu"
    return Html(f'<div class="ws" style="grid-template-columns:repeat({cols},minmax(0,1fr))" role="img" '
                f'aria-label="{h(k)}">{sq}</div>'
                f'<div class="ws-k"><span>{h(day(first_ts))}</span><span>{h(k)}</span><span>{h(day(last_ts))}</span></div>')
