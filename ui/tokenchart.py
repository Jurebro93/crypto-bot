"""Mcap graf jednog tokena s točkama poziva influencera (stranica /token/<adresa>).

10.11. (Jure: "Ostalo mi se sviđa", prijedlog 4.3, maketa token.html): na vrhu stranice tokena graf mcap-a kao graf
Autopilota (jedna linija naglaska, blaga ploha, dvije vodoravne crte s vrijednostima desno, točka "sada"), a pozivi
influencera su bijele točke na liniji (dodir pokaže tko, mcap i kad). Raspon 1 h | 6 h | 24 h | 7 d se bira bez novog
učitavanja (sva četiri crteža su u stranici, svaki najviše MAX_POINTS točaka).

Podaci (sve čitanje po ključu tokena, bez prolaza kroz cijelu tablicu):
  hype.db  hype_snapshots (svakih ~20 min, mcap ili cijena) i token_pulse (svake 2 min dok je token zanimljiv)
  kol.db   calls (indeks calls_token): prvi poziv svakog računa, s mcap-om kod poziva
Nema mreže: graf se crta na poslužitelju kao SVG, pa radi i na spremljenoj stranici.
"""
import datetime as dt
import math
import time

from ui.redak import NBSP, h, num

RANGES = (("1h", "1 h", 3600), ("6h", "6 h", 6 * 3600), ("24h", "24 h", 86400), ("7d", "7 d", 7 * 86400))
DEFAULT = "24h"
MAX_POINTS = 160          # per range: enough for a smooth line on a 1000-unit wide SVG, a few KB of HTML
W, H = 1000.0, 200.0
X_END = 992.0             # the line ends a little before the right edge, so the "now" dot is not cut (maketa)
MAX_MARKS = 12            # call dots per range; the full list is in "Tko ga je zvao"
PULSE_NEAR_S = 600        # a 20-min snapshot this close to a pulse reading is left out (the pulse is fresher)

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Europe/Zagreb")
except Exception:  # noqa: BLE001 - no tz database: UTC labels
    _TZ = dt.timezone.utc


def series(mint, snaps=None, pulse=None):
    """[(ts, mcap)] sorted, from hype_snapshots and token_pulse merged (one value per ts). snaps / pulse: test seams,
    lists of dicts with ts, mcap, price. A snapshot without mcap is scaled from its price by the newest known
    mcap/price ratio (same token, same supply)."""
    if snaps is None or pulse is None:
        from ui import data
        snaps = data.hype_snapshots(mint) if snaps is None else snaps
        pulse = data.token_pulse(mint, hours=7 * 24, limit=2000) if pulse is None else pulse
    # the pulse (every 2 min, live DexScreener mcap) wins where it exists: a snapshot within PULSE_NEAR_S of a pulse
    # reading is dropped, or two sources that disagree by a few % draw a saw-tooth instead of the price
    import bisect
    pts_ = sorted(int(r["ts"]) for r in pulse or () if r.get("ts") and r.get("mcap"))

    def near(t):
        i = bisect.bisect_left(pts_, t)
        return any(0 <= j < len(pts_) and abs(pts_[j] - t) <= PULSE_NEAR_S for j in (i - 1, i))
    rows = [r for r in snaps or () if not (r.get("ts") and near(int(r["ts"])))] + list(pulse or ())
    ratio = next((r["mcap"] / r["price"] for r in sorted(rows, key=lambda r: -(r.get("ts") or 0))
                  if r.get("mcap") and r.get("price")), None)
    out = {}
    for r in rows:
        t, m = r.get("ts"), r.get("mcap")
        if not m and r.get("price") and ratio:
            m = r["price"] * ratio
        if t and m and m > 0:
            out[int(t)] = float(m)
    return sorted(out.items())


def calls(mint, con=None):
    """[(ts, handle, mcap0)] the first post of each account with this token (no wallet trades, no bots), oldest first."""
    from ui import data
    try:
        from kol import store
        path = store.DB
    except Exception:  # noqa: BLE001
        return []
    rows = data.q(path, """SELECT c.handle, MIN(c.ts) AS ts, c.mcap0 FROM calls c LEFT JOIN kols k ON k.handle = c.handle
        WHERE c.token = ? AND c.kind NOT IN ('buy', 'sell') AND c.handle NOT LIKE 'w:%' AND COALESCE(k.bot, 0) = 0
        GROUP BY c.handle ORDER BY ts""", (mint,))
    return [(int(r["ts"]), r["handle"], r.get("mcap0")) for r in rows if r.get("ts")]


def short_usd(v):
    """Axis label: 200000 -> "200k", 1500000 -> "1,5M", 850 -> "850"."""
    a = abs(v)
    if a >= 1e9:
        return num(v / 1e9, 1).replace(",0", "") + "B"
    if a >= 1e6:
        return num(v / 1e6, 1).replace(",0", "") + "M"
    if a >= 1e3:
        return num(v / 1e3, 0 if a >= 1e4 else 1).replace(",0", "") + "k"
    return num(v, 0)


def ticks(lo, hi, n=2):
    """About n round values strictly between lo and hi (1, 2, 2.5, 5 × 10^k steps)."""
    if hi <= lo:
        return []
    raw = (hi - lo) / (n + 1)
    mag = 10 ** math.floor(math.log10(raw))
    step = next(s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw)
    v = math.ceil(lo / step) * step
    out = []
    while v < hi and len(out) < n + 2:
        if v > lo:
            out.append(v)
        v += step
    if len(out) > n:   # keep the ones closest to the middle of the band
        mid = (lo + hi) / 2
        out = sorted(sorted(out, key=lambda x: abs(x - mid))[:n])
    return out


def _thin(pts, limit=MAX_POINTS):
    if len(pts) <= limit:
        return pts
    step = (len(pts) - 1) / (limit - 1)
    return [pts[round(i * step)] for i in range(limit)]


def _at(pts, t):
    """Value of the line at time t (linear between the two neighbours)."""
    if t <= pts[0][0]:
        return pts[0][1]
    for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
        if t0 <= t <= t1:
            return v0 if t1 == t0 else v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return pts[-1][1]


def _label(t, span, now):
    d = dt.datetime.fromtimestamp(t, _TZ)
    if span > 2 * 86400:
        return f"{d.day}.{d.month}."
    return f"{d.hour}:{d.minute:02d}"


def figure(pts, marks, span, now, ident, sym=""):
    """One chart (Html string) for the points inside the range, or "" with fewer than two points.
    marks: [(ts, handle, mcap0)] of calls; each one inside the range becomes a dot on the line."""
    t_from = now - span
    inr = [p for p in pts if p[0] >= t_from]
    before = [p for p in pts if p[0] < t_from]
    if before and inr and inr[0][0] > t_from:   # start the line at the edge of the range when there is data before it
        inr = [(t_from, _at(before + inr[:1], t_from))] + inr
    if len(inr) < 2:
        return ""
    inr = _thin(inr)
    t0 = inr[0][0]
    t1 = max(inr[-1][0], t0 + 1)
    vals = [v for _, v in inr]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.12 or hi * 0.05 or 1
    lo, hi = max(0.0, lo - pad), hi + pad

    def x(t):
        return X_END * (t - t0) / (t1 - t0)

    def y(v):
        return H - H * (v - lo) / (hi - lo)
    line = " ".join(f"{'M' if i == 0 else 'L'}{x(t):.1f},{y(v):.1f}" for i, (t, v) in enumerate(inr))
    area = f"{line} L{x(inr[-1][0]):.1f},{H:.0f} L0,{H:.0f} Z"
    grid = "".join(f'<line x1="0" y1="{y(v):.1f}" x2="{W:.0f}" y2="{y(v):.1f}" stroke="var(--line)" stroke-width="1" '
                   'vector-effect="non-scaling-stroke"/>' for v in ticks(lo, hi))
    ylab = "".join(f'<span class="tc-yl" style="top:{100 * y(v) / H:.1f}%">{h(short_usd(v))}</span>' for v in ticks(lo, hi))
    gid = f"tcg-{ident}"
    svg = (f'<svg viewBox="0 0 {W:.0f} {H:.0f}" preserveAspectRatio="none" role="img" aria-label="Mcap {h(sym)}">{grid}'
           f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--acc)" '
           f'stop-opacity=".14"/><stop offset="1" stop-color="var(--acc)" stop-opacity="0"/></linearGradient></defs>'
           f'<path d="{area}" fill="url(#{gid})"/><path d="{line}" fill="none" stroke="var(--acc)" stroke-width="2.2" '
           'stroke-linejoin="round" vector-effect="non-scaling-stroke"/></svg>')
    end = (f'<span class="tc-end" style="left:{100 * x(inr[-1][0]) / W:.2f}%;top:{100 * y(inr[-1][1]) / H:.2f}%"></span>')
    mk = []
    shown = [m for m in marks if t0 <= m[0] <= t1][-MAX_MARKS:]
    first = marks[0][0] if marks else None
    for ts_, hnd, m0 in shown:
        v = _at(inr, ts_)
        who = hnd[3:] + " (Telegram)" if hnd.startswith("tg:") else "@" + hnd
        tip = f"{who}{', prvi poziv' if ts_ == first else ''} · {short_usd(m0 or v)}{NBSP}$ · {_ago(ts_, now)}"
        mk.append(f'<button type="button" class="tc-mk" style="left:{100 * x(ts_) / W:.2f}%;top:{100 * y(v) / H:.2f}%" '
                  f'title="{h(tip)}" data-tip="{h(tip)}" aria-label="{h(tip)}"></button>')
    ax = "".join(f'<span style="left:{100 * x(t) / W:.1f}%">{h(_label(t, span, now))}</span>' for t in time_ticks(t0, t1)
                 if 4 <= 100 * x(t) / W <= 86)
    return (f'<div class="tc-fig" data-r="{h(ident)}"><div class="tc-plot"><div class="tc-pw">{svg}{end}{"".join(mk)}</div>'
            f'{ylab}</div><div class="tc-ax"><div class="tc-axw">{ax}<span class="tc-now" style="left:{100 * X_END / W:.1f}%">sada'
            '</span></div></div></div>')


STEPS = (300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400, 2 * 86400)


def time_ticks(t0, t1, most=4):
    """Round clock times between t0 and t1 (local time, Europe/Zagreb): every 15 min, 1 h, 6 h, a day... so that at
    most `most` fit (maketa: 8:00, 14:00, 20:00, 2:00, sada)."""
    span = max(1, t1 - t0)
    step = next((s for s in STEPS if span / s <= most), STEPS[-1])
    off = dt.datetime.fromtimestamp(t0, _TZ).utcoffset().total_seconds()
    t = (int((t0 + off) // step) + 1) * step - off
    out = []
    while t < t1:
        out.append(t)
        t += step
    return out


def _ago(ts_, now):
    d = now - ts_
    if d < 3600:
        return f"prije {max(1, int(d // 60))} min"
    if d < 86400:
        return f"prije {int(d // 3600)} h"
    return f"prije {int(d // 86400)} d"


def chart_html(mint, sym="", now=None, pts=None, marks=None):
    """The whole block: one figure per range that has data (24 h shown first, or the nearest range with data), the
    legend for call dots and the range switch. "" when there are fewer than two price points in 7 days.
    pts / marks: test seams (series(), calls())."""
    now = now or time.time()
    pts = series(mint) if pts is None else pts
    marks = calls(mint) if marks is None else marks
    figs = [(k, lab, figure(pts, marks, span, now, k, sym)) for k, lab, span in RANGES]
    have = [(k, lab, f) for k, lab, f in figs if f]
    if not have:
        return ""
    cur = DEFAULT if any(k == DEFAULT for k, _, _ in have) else have[-1][0]
    body = "".join(f.replace('class="tc-fig"', 'class="tc-fig"' + ("" if k == cur else " hidden"), 1) for k, _, f in have)
    seg = "".join(f'<button type="button" data-r="{k}"{" class=on" if k == cur else ""}>{h(lab)}</button>' for k, lab, _ in have)
    leg = ('<div class="tc-leg" aria-live="polite"><i></i><span>poziv influencera · dodir na točku pokaže tko</span></div>'
           if marks else "")
    return (f'<div class="tc" id="tc">{body}{leg}' + (f'<div class="tc-seg">{seg}</div>' if len(have) > 1 else "")
            + "</div>" + JS)


CSS = """<style>
.tc{margin:16px 0 0}
.tc-plot{position:relative;padding-right:44px}.tc-pw{position:relative}
.tc svg{display:block;width:100%;height:170px;overflow:visible}
.tc-end{position:absolute;width:10px;height:10px;margin:-5px 0 0 -5px;border-radius:50%;background:var(--acc);box-shadow:0 0 0 3px #fff;pointer-events:none}
.tc-mk{all:unset;position:absolute;width:10px;height:10px;margin:-7px 0 0 -7px;border-radius:50%;background:#fff;border:2px solid var(--acc);cursor:pointer}
.tc-mk:hover,.tc-mk.on{background:var(--acc)}
.tc-mk::before{content:"";position:absolute;inset:-9px}
.tc-yl{position:absolute;right:0;transform:translateY(-50%);font-size:13px;color:var(--mut)}
.tc-ax{font-size:13px;color:var(--mut);padding:8px 44px 0 0}.tc-axw{position:relative;height:18px}
.tc-axw span{position:absolute;top:0;transform:translateX(-50%);white-space:nowrap}.tc-axw .tc-now{transform:translateX(-100%)}
.tc-leg{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--mut);margin:8px 0 0;min-height:18px}
.tc-leg i{flex:none;width:10px;height:10px;border-radius:50%;border:2px solid var(--acc);background:#fff;display:inline-block;box-sizing:border-box}
.tc-seg{display:flex;background:var(--soft);border-radius:11px;padding:3px;margin:12px 0 0}
.tc-seg button{all:unset;flex:1;text-align:center;font-size:13px;padding:5px 0;border-radius:9px;cursor:pointer;color:var(--fg)}
.tc-seg button.on{background:#fff;font-weight:600;box-shadow:0 1px 3px rgba(11,18,32,.12)}
.tc-fig[hidden]{display:none}
@media(min-width:900px){.tc svg{height:240px}}
</style>"""

JS = """<script>(()=>{const c=document.getElementById('tc');if(!c)return;const leg=c.querySelector('.tc-leg span'),d0=leg&&leg.textContent;
c.addEventListener('click',e=>{const b=e.target.closest('.tc-seg button');if(b){c.querySelectorAll('.tc-seg button').forEach(x=>x.classList.toggle('on',x===b));
 c.querySelectorAll('.tc-fig').forEach(f=>f.hidden=f.dataset.r!==b.dataset.r);if(leg)leg.textContent=d0;return}
 const m=e.target.closest('.tc-mk');if(m&&leg){const on=!m.classList.contains('on');c.querySelectorAll('.tc-mk.on').forEach(x=>x.classList.remove('on'));
 m.classList.toggle('on',on);leg.textContent=on?m.dataset.tip:d0}})})()</script>"""
