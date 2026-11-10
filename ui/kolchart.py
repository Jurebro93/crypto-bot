"""Profil influencera (/kol/<ime>): niz njegovih poziva u razdoblju presude i dva crteža iz njega.

10.11. (Jure, prijedlog 4.5, maketa audit/2026-11-10/makete/influencer.html): profil počinje presudom i s četiri broja,
a ispod su graf "10 $ u svaki poziv" (dvije linije na jednoj osi: brzi izlaz i drži 24 h) i "Svaki poziv, redom"
(dva reda kvadratića, 1 h i 24 h). Sve je iz ISTIH poziva koje broji presuda (ui/kolsummary.verdict_stats):
  * 1 h: kol/minute.py call_path, prvi poziv računa po tokenu u razdoblju, bez poziva ispod 30k $ (bad 'mcap'),
    "pogodak" = +10 % prije stopa −20 % (minute.clean_hit), kao handle_stats["hit10"];
  * 24 h: kol.db calls.r24h, prvi poziv po tokenu, samo objave (ne kupnje/prodaje), bez bad, mcap kod poziva 30k $
    ili nepoznat, kao kolsummary._day24.
Brzi izlaz po pozivu: +10 % kad je cilj došao prije stopa, −20 % kad je stop bio prvi, inače cijena nakon 60 min
(r60). Drži 24 h: cijena dan poslije (r24h, najviše −100 %). Oba su "prije naknada". Ništa se ne mijenja u tome
kako Autopilot bira račune; ovo samo pokazuje mjere koje već postoje.

Čita samo indeksom (call_path_handle, calls_handle) za jedan račun; nema skeniranja tablica po zahtjevu.
"""
import datetime as _dt
import statistics
import time

from ui.redak import Html, MINUS, NBSP, h, num, pct

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Zagreb")
except Exception:  # noqa: BLE001 - bez baze zona: lokalno vrijeme poslužitelja
    TZ = None

STAKE = 10.0          # $ u svaki poziv (maketa: "10 $ u svaki poziv")
FAST_TP, FAST_SL = 0.10, -0.20
STRIP_MAX = 50        # najviše ovoliko kvadratića u redu (najnoviji); više od toga postaju mrvice na mobitelu


def _local(ts):
    return _dt.datetime.fromtimestamp(ts, TZ) if TZ else _dt.datetime.fromtimestamp(ts)


def day(ts):
    """"9.11." (datum bez godine, hrvatski zapis)."""
    d = _local(ts)
    return f"{d.day}.{d.month}."


def when(ts, now=None):
    """Kad je poziv bio: "prije 43 min" (zadnji sat), "danas 05:27", inače "9.11. 22:14"."""
    now = time.time() if now is None else now
    if now - ts < 3600:
        return f"prije {max(1, int((now - ts) // 60))} min"
    d, n = _local(ts), _local(now)
    if d.date() == n.date():
        return f"danas {d:%H:%M}"
    return f"{d.day}.{d.month}. {d:%H:%M}"


def fast_ret(r):
    """Rezultat brzog izlaza za jedan red call_path: +10 % (cilj prije stopa), −20 % (stop prvi) ili r60."""
    from kol.minute import clean_hit
    if clean_hit(r, 10):
        return FAST_TP
    if r.get("sl_min") is not None:
        return FAST_SL
    return r.get("r60") or 0.0


def series(handle, days=14, now=None, kol_db=None, minute_db=None):
    """Pozivi jednog računa u zadnjih `days` dana, istim pravilima kao presuda:
        h1:  [{ts, token, sym, hit, t10, sl, r60, ret, usd}] (call_path, najstariji prvi)
        d24: [{ts, token, sym, r24, usd}] (kol.db, samo s poznatom cijenom dan kasnije, najstariji prvi)
        n1, hits1, n24, plus24, fast_usd, hold_usd, med_t10 (medijan minuta do +10 % kod pogodaka, ili None).
    Prazni popisi kad baze nema."""
    from kol import minute, store
    end = int(now or time.time())
    since = end - int(days) * 86400
    h1, d24, syms = [], [], {}
    mcon = minute.ro(minute_db)
    if mcon is not None:
        try:
            first = {}
            for r in minute._rows(mcon, "handle = ? AND ts >= ?", (handle, since)):
                if r["token"] not in first or r["ts"] < first[r["token"]]["ts"]:
                    first[r["token"]] = r
        finally:
            mcon.close()
        for r in sorted(first.values(), key=lambda x: x["ts"]):
            ret = fast_ret(r)
            h1.append({"ts": r["ts"], "token": r["token"], "tweet_id": r["tweet_id"], "hit": minute.clean_hit(r, 10),
                       "t10": r["t10"], "sl": r["sl_min"], "r60": r["r60"], "ret": ret, "usd": STAKE * ret})
    kcon = store.ro(kol_db)
    if kcon is not None:
        try:
            cols = {r[1] for r in kcon.execute("PRAGMA table_info(calls)")}
            bad = " AND bad IS NULL" if "bad" in cols else ""
            rows = kcon.execute("SELECT token, ts, r24h, mcap0, symbol FROM calls WHERE handle = ? AND ts >= ? AND ts <= ? "
                                f"AND kind NOT IN ('buy', 'sell'){bad} ORDER BY ts", (handle, since, end)).fetchall()
            toks = list({r[0] for r in rows} | {r["token"] for r in h1})[:400]
            if toks:
                try:
                    syms = dict(kcon.execute(f"SELECT token, symbol FROM tokens WHERE token IN ({','.join('?' * len(toks))})",
                                             toks).fetchall())
                except Exception:  # noqa: BLE001 - bez tablice tokens: simbol iz poziva
                    syms = {}
        finally:
            kcon.close()
        seen = set()
        for tok, ts, r24, mc, sym in rows:
            if tok in seen:
                continue
            seen.add(tok)
            if mc is not None and mc < minute.MIN_MCAP:
                continue
            syms.setdefault(tok, sym)
            if r24 is None:
                continue
            ret = max(-1.0, r24)
            d24.append({"ts": ts, "token": tok, "r24": r24, "usd": STAKE * ret})
    for r in h1 + d24:
        r["sym"] = syms.get(r["token"]) or r["token"][:6]
    t10 = [r["t10"] for r in h1 if r["hit"] and r["t10"] is not None]
    return {"h1": h1, "d24": d24, "n1": len(h1), "hits1": sum(1 for r in h1 if r["hit"]), "n24": len(d24),
            "plus24": sum(1 for r in d24 if r["r24"] > 0), "fast_usd": sum(r["usd"] for r in h1) if h1 else None,
            "hold_usd": sum(r["usd"] for r in d24) if d24 else None,
            "med_t10": statistics.median(t10) if t10 else None, "since": since, "end": end, "days": int(days)}


def money(x):
    """"+3 $", "−185 $", "0 $" (cijeli dolari, kao u maketi)."""
    return f"{num(x, 0, sign=True)}{NBSP}$" if x is not None else "–"


def _nice(span):
    """Lijep korak osi (1, 2, 2,5, 5 × 10^k) tako da raspon stane u dva do četiri koraka."""
    import math
    raw = max(span / 2.0, 1e-9)
    p = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if m * p >= raw:
            return m * p
    return 10 * p


def _axis(vals):
    import math
    lo, hi = min([0.0] + vals), max([0.0] + vals)
    if hi - lo < 1e-9:
        hi = lo + STAKE
    s = _nice(hi - lo)
    top, bot = math.ceil(hi / s - 1e-9) * s, math.floor(lo / s + 1e-9) * s
    ticks, v = [], top
    while v >= bot - 1e-9:
        ticks.append(round(v, 6))
        v -= s
    return top, bot, ticks


def chart(sr, label="Deset dolara u svaki poziv"):
    """SVG s dvije linije (zbroj po vremenu): brzi izlaz (--acc) i drži 24 h (--mut), vrijednosti desno, datumi
    ispod, legenda s oba zbroja. Html; "" kad nema nijednog izmjerenog poziva."""
    lines = []
    for key, cls in (("h1", "kc-f"), ("d24", "kc-h")):
        pts, run = [], 0.0
        for r in sr[key]:
            run += r["usd"]
            pts.append((r["ts"], run))
        lines.append((cls, pts))
    if not any(p for _, p in lines):
        return Html("")
    x0, x1 = sr["since"], sr["end"]
    top, bot, ticks = _axis([v for _, p in lines for _, v in p])
    W, H = 1000.0, 200.0

    def X(t):
        return max(0.0, min(W, (t - x0) / max(1, x1 - x0) * W))

    def Y(v):
        return (top - v) / (top - bot) * H
    svg = [f'<svg viewBox="0 0 1000 200" preserveAspectRatio="none" role="img" aria-label="{h(label)}">']
    for t in ticks:
        dash = ' stroke-dasharray="4 4"' if abs(t) < 1e-9 else ""
        svg.append(f'<line class="{"kc-z" if dash else "kc-g"}" x1="0" y1="{Y(t):.1f}" x2="1000" y2="{Y(t):.1f}"'
                   f'{dash} vector-effect="non-scaling-stroke"/>')
    end = None
    for cls, pts in reversed(lines):      # brzi izlaz zadnji, da bude iznad
        if not pts:
            continue
        d = [f"M0,{Y(0):.1f}"]   # obje linije kreću od nule na početku razdoblja, kao u maketi
        for t, v in pts:
            d.append(f"L{X(t):.1f},{Y(v):.1f}")
        svg.append(f'<path class="{cls}" d="{" ".join(d)}" fill="none" vector-effect="non-scaling-stroke"/>')
        if cls == "kc-f":
            end = (X(pts[-1][0]) / W * 100, Y(pts[-1][1]) / H * 100)
    svg.append("</svg>")
    dot = f'<span class="kc-end" style="left:{end[0]:.2f}%;top:{end[1]:.2f}%"></span>' if end else ""
    yl = "".join(f'<span class="kc-yl" style="top:{Y(t) / H * 100:.1f}%">'
                 f'{"0" + NBSP + "$" if abs(t) < 1e-9 else num(t, 0, sign=True)}</span>' for t in ticks)
    ax = "".join(f"<span>{day(x0 + (x1 - x0) * i / 4)}</span>" for i in range(5))
    leg = []
    if sr["h1"]:
        leg.append(f'<span><i class="kc-lf"></i>brzi izlaz <b class="{_tone(sr["fast_usd"])}">{money(sr["fast_usd"])}</b></span>')
    if sr["d24"]:
        leg.append(f'<span><i class="kc-lh"></i>drži 24 h <b class="{_tone(sr["hold_usd"])}">{money(sr["hold_usd"])}</b></span>')
    return Html(f'<div class="kc-chart"><div class="kc-plot"><div class="kc-pw">{"".join(svg)}{dot}</div>{yl}</div>'
                f'<div class="kc-ax">{ax}</div></div><div class="kc-legend">{"".join(leg)}</div>')


def _tone(x):
    return "pos" if (x or 0) > 0 else "neg" if (x or 0) < 0 else ""


def _href(tok):
    from urllib.parse import quote
    return f"/token/{quote(tok)}"


def strips(sr):
    """"Svaki poziv, redom": red 1 h (zeleno = +10 % prije stopa) i red 24 h (zeleno = u plusu dan kasnije), jedan
    kvadratić po pozivu, najstariji lijevo; dodir otvara token, a naslov kaže ishod. Html; "" bez poziva."""
    a, b = sr["h1"][-STRIP_MAX:], sr["d24"][-STRIP_MAX:]
    if not a and not b:
        return Html("")
    cols = max(len(a), len(b), 12)

    def sq(r, ok, what):
        return (f'<a class="kc-sq{"" if ok else " n"}" href="{h(_href(r["token"]))}" '
                f'title="{h(r["sym"])} · {h(when(r["ts"], sr["end"]))} · {h(what)}"></a>')

    def o1(r):
        if r["hit"]:
            return f"+10{NBSP}% u {r['t10']} min"
        if r["sl"] is not None:
            return f"stop {MINUS}20{NBSP}%"
        return f"nakon 60 min {pct(r['r60'] or 0, frac=True)}"
    row1 = "".join(sq(r, r["hit"], o1(r)) for r in a)
    row2 = "".join(sq(r, r["r24"] > 0, f"24 h {pct(r['r24'], frac=True)}") for r in b)
    first = min([r["ts"] for r in a[:1] + b[:1]] or [sr["since"]])
    last = max([r["ts"] for r in a[-1:] + b[-1:]] or [sr["end"]])
    grid = f' style="grid-template-columns:repeat({cols},minmax(0,1fr))"'
    out = []
    if a:
        out.append(f'<div class="kc-strip"><span class="kc-sl">1 h</span><span class="kc-sqs"{grid}>{row1}</span></div>')
    if b:
        out.append(f'<div class="kc-strip"><span class="kc-sl">24 h</span><span class="kc-sqs"{grid}>{row2}</span></div>')
    out.append(f'<div class="kc-k"><span>{day(first)}</span><span>zeleno +10{NBSP}% ili u plusu · crveno ne</span>'
               f'<span>{day(last)}</span></div>')
    return Html("".join(out))


# Vrijednosti prepisane iz makete influencer.html (.chart, .legend, .strip); prefiks kc- da ništa staro ne dira.
CSS = """
.kc-chart{margin:14px 0 0}
.kc-plot{position:relative;padding-right:44px}.kc-pw{position:relative}
.kc-chart svg{display:block;width:100%;height:170px;overflow:visible}
.kc-g{stroke:var(--line);stroke-width:1}.kc-z{stroke:var(--line2);stroke-width:1}
.kc-f{stroke:var(--acc);stroke-width:2.2;stroke-linejoin:round}.kc-h{stroke:var(--mut);stroke-width:2;stroke-linejoin:round}
.kc-end{position:absolute;width:10px;height:10px;margin:-5px 0 0 -5px;border-radius:50%;background:var(--acc);box-shadow:0 0 0 3px #fff}
.kc-yl{position:absolute;right:0;transform:translateY(-50%);font-size:13px;color:var(--mut);white-space:nowrap}
.kc-ax{display:flex;justify-content:space-between;font-size:13px;color:var(--mut);padding:8px 44px 0 0}
.kc-legend{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:15px;color:var(--mut);margin:12px 0 0}
.kc-legend span{display:inline-flex;align-items:center;gap:7px}
.kc-legend i{display:inline-block;width:16px;height:3px;border-radius:2px}.kc-lf{background:var(--acc)}.kc-lh{background:var(--mut)}
.kc-legend b{font-weight:600}
.kc-strip{display:flex;align-items:center;gap:10px;margin:12px 0 0}
.kc-sl{flex:none;width:36px;font-size:13px;color:var(--mut)}
.kc-sqs{flex:1;display:grid;gap:2px}
.kc-sq{display:block;height:16px;border-radius:3px;background:var(--good)}.kc-sq.n{background:var(--bad)}
.kc-k{display:flex;justify-content:space-between;gap:8px;font-size:13px;color:var(--mut);margin:8px 0 0 46px}
@media(min-width:900px){.kc-chart svg{height:200px}}
"""
