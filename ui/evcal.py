"""Month calendar for /events: one coloured dot per event (light blue = minor, red = big), a colour scale on top,
and a tap on a day opens a pop-up with that day's events in full (Nicholas 4.11.). The list below stays the
chronological view; this is the overview.

Everything is rendered on the server (one <section> per month, one <template> per day), the small script only
switches months and opens the pop-up, so the page stays cacheable.
"""
import calendar as _cal
import datetime as dt

from ui.html import esc

# Hype is 0-100 on paper, in practice most events are 5-45 (calendar.db 4.11.: median 18, 97th pct 34).
# Fixed steps keep the colour meaning stable from day to day instead of re-scaling with each batch.
LEVELS = [  # (from hype, colour, label)
    (0, "#7dd3fc", "slab"),
    (10, "#3b82f6", "manji"),
    (20, "#facc15", "srednji"),
    (30, "#f97316", "jak"),
    (40, "#dc2626", "vrlo jak"),
]
MONTHS = ["siječanj", "veljača", "ožujak", "travanj", "svibanj", "lipanj", "srpanj", "kolovoz", "rujan",
          "listopad", "studeni", "prosinac"]


def level(h):
    """(colour, label) for a hype value; None counts as the lowest step."""
    h = h or 0
    out = LEVELS[0]
    for lv in LEVELS:
        if h >= lv[0]:
            out = lv
    return out[1], out[2]


def dot(h, title=""):
    c, lab = level(h)
    return f'<i class=ecd style="background:{c}" title="{esc(title or lab)}"></i>'


CSS = """<style>
.ecal{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:10px 12px;margin:8px 0 14px;max-width:760px}
.ecal .eh{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:6px}
.ecal .eh b{font-size:15px;text-transform:capitalize}.ecal .eh button{background:var(--card);border:1px solid var(--line);
 border-radius:8px;padding:4px 12px;font:inherit;cursor:pointer;color:var(--fg)}.ecal .eh button:disabled{opacity:.3;cursor:default}
.eleg{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:12px;color:var(--mut);margin:0 0 8px;align-items:center}
.eleg span{display:inline-flex;align-items:center;gap:4px}
.ecd{display:inline-block;width:9px;height:9px;border-radius:50%;flex:none;box-shadow:0 0 0 1px rgba(0,0,0,.08)}
.egrid{display:grid;grid-template-columns:repeat(7,1fr);gap:3px}
.egrid .wd{font-size:11px;color:var(--mut);text-align:center;padding:2px 0}
.egrid .d{min-height:46px;border:1px solid var(--line);border-radius:8px;padding:3px 4px;font-size:12px;background:var(--bg);
 display:flex;flex-direction:column;gap:3px;text-align:left;font-family:inherit;color:var(--fg)}
.egrid button.d{cursor:pointer}.egrid button.d:hover{border-color:var(--acc)}
.egrid .d.x{visibility:hidden}.egrid .d.past{opacity:.5}.egrid .d.now{border-color:var(--acc);box-shadow:inset 0 0 0 1px var(--acc)}
.egrid .dots{display:flex;flex-wrap:wrap;gap:2px;align-items:center}.egrid .more{font-size:10px;color:var(--mut)}
.egrid .n{font-weight:600}
@media(min-width:700px){.egrid .d{min-height:58px}.ecd{width:10px;height:10px}}
dialog#ecdlg{max-width:620px;width:calc(100% - 24px);max-height:85vh;border:1px solid var(--line);border-radius:18px;
 background:var(--card);color:var(--fg);padding:0;box-shadow:0 30px 60px -20px rgba(11,18,32,.35)}
dialog#ecdlg::backdrop{background:rgba(11,18,32,.45)}
dialog#ecdlg .bar2{position:sticky;top:0;display:flex;justify-content:space-between;align-items:center;padding:8px 12px;
 background:var(--card);border-bottom:1px solid var(--line)}
dialog#ecdlg .bar2 button{background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:999px;padding:5px 12px;font:inherit;cursor:pointer}
dialog#ecdlg .body{padding:6px 16px 16px;font-size:14px;line-height:1.5}
.ecev{border-bottom:1px solid var(--line);padding:10px 0}.ecev:last-child{border-bottom:0}
.ecev h3{font-size:16px;margin:0 0 4px;display:flex;gap:6px;align-items:baseline}.ecev .row{display:flex;flex-wrap:wrap;gap:4px 14px;margin:4px 0}
.ecev .lab{color:var(--mut);font-size:12px}
</style>"""

JS = """<script>
(function(){var c=document.querySelector('.ecal');if(!c)return;var ms=c.querySelectorAll('section'),i=+c.dataset.start||0,
p=c.querySelector('.prev'),n=c.querySelector('.next'),t=c.querySelector('.eh b');
function show(){ms.forEach(function(m,k){m.hidden=k!==i});t.textContent=ms[i].dataset.t;p.disabled=i<=0;n.disabled=i>=ms.length-1}
p.onclick=function(){if(i>0){i--;show()}};n.onclick=function(){if(i<ms.length-1){i++;show()}};show();
var d=document.getElementById('ecdlg');c.addEventListener('click',function(e){var b=e.target.closest('button.d');if(!b)return;
var tp=document.getElementById('ecd-'+b.dataset.d);if(!tp)return;d.querySelector('.ttl').textContent=b.dataset.l;
var body=d.querySelector('.body');body.innerHTML='';body.appendChild(tp.content.cloneNode(true));d.showModal()});
d.addEventListener('click',function(e){if(e.target===d)d.close()});})();
</script>"""


def legend():
    return ("<div class=eleg><span>Važnost (hype):</span>"
            + "".join(f'<span><i class=ecd style="background:{c}"></i>{esc(lab)} {f"{lo}+" if lo else "0-9"}</span>'
                      for lo, c, lab in LEVELS) + "</div>")


def render(items, today=None):
    """items: [(event dict with date/title/hype, detail html)]. Returns the calendar block + pop-up + script,
    or "" when no event has a date."""
    today = today or dt.date.today()
    by_day = {}
    for e, det in items:
        try:
            d = dt.date.fromisoformat(str(e.get("date") or "")[:10])
        except ValueError:
            continue
        by_day.setdefault(d, []).append((e, det))
    if not by_day:
        return ""
    first, last = min(by_day), max(by_day)
    months, y, m = [], first.year, first.month
    while (y, m) <= (last.year, last.month):
        months.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    start = next((k for k, (yy, mm) in enumerate(months) if (yy, mm) >= (today.year, today.month)), len(months) - 1)
    secs, tmpls = [], []
    for y, m in months:
        cells = [f"<div class=wd>{w}</div>" for w in ("pon", "uto", "sri", "čet", "pet", "sub", "ned")]
        for week in _cal.Calendar(0).monthdatescalendar(y, m):
            for d in week:
                if d.month != m:
                    cells.append("<div class='d x'></div>")
                    continue
                evs = sorted(by_day.get(d, []), key=lambda x: -(x[0].get("hype") or 0))
                cls = "d" + (" past" if d < today else "") + (" now" if d == today else "")
                if not evs:
                    cells.append(f"<div class='{cls}'><span class=n>{d.day}</span></div>")
                    continue
                key = d.isoformat()
                dots = "".join(dot(e.get("hype"), e.get("title")) for e, _ in evs[:6])
                more = f"<span class=more>+{len(evs) - 6}</span>" if len(evs) > 6 else ""
                lab = f"{d.day}.{d.month}. · {len(evs)} {'event' if len(evs) == 1 else 'eventa' if len(evs) < 5 else 'evenata'}"
                cells.append(f'<button type=button class="{cls}" data-d="{key}" data-l="{esc(lab)}" '
                             f'aria-label="{esc(lab)}"><span class=n>{d.day}</span><span class=dots>{dots}{more}</span></button>')
                tmpls.append(f'<template id="ecd-{key}">' + "".join(det for _, det in evs) + "</template>")
        secs.append(f'<section data-t="{MONTHS[m - 1]} {y}" hidden><div class=egrid>{"".join(cells)}</div></section>')
    return (CSS + f'<div class=ecal data-start={start}><div class=eh><button type=button class=prev aria-label="Prethodni mjesec">‹</button>'
            f'<b></b><button type=button class=next aria-label="Sljedeći mjesec">›</button></div>{legend()}{"".join(secs)}</div>'
            + "".join(tmpls)
            + '<dialog id=ecdlg><div class=bar2><b class=ttl></b><button type=button onclick="this.closest(\'dialog\').close()">'
              'Zatvori ✕</button></div><div class=body></div></dialog>' + JS)
