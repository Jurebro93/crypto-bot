"""Top of the Učenje page: is the tool better now than when it started? One look, plain words.

Built only from closed demo trades in paper.db (the same trades the Demo trading page shows; manual sales left out):
the first 3 days with trades against the last 3 days, plus a small bar chart of every day. Nothing here changes how
the tool learns; it only reads.
"""
import datetime as dt
import json
import os
import re
import sqlite3
import time

from ui import data
from ui.html import esc, tip

WINDOW_D = 3        # days on each side of the comparison: one lucky or unlucky day must not decide it
MIN_N = 10          # closed trades needed on each side before we say better/worse
SAME_PP = 0.02      # average per trade within ±2 percentage points = "about the same"
CAP = 3.0           # one trade counts at most +300%, like everywhere else on the page
BAD_EXITS = ("rug", "stop_loss")

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Zagreb")
except Exception:  # noqa: BLE001
    TZ = None

CSS = """<style>
.uc-top{border:1px solid var(--line);border-radius:18px;background:var(--card);padding:16px;margin:0 0 14px}
.uc-v{font-size:18px;font-weight:650;line-height:1.35;margin:0 0 4px}
.uc-v.good{color:var(--good)}.uc-v.bad{color:var(--bad)}
.uc-sub{font-size:13px;color:var(--mut);margin:0 0 12px}
.uc-kpi{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:0 0 12px}
.uc-kpi>div{background:var(--soft);border-radius:12px;padding:10px}
.uc-kpi .l{font-size:12px;color:var(--mut);line-height:1.3}
.uc-kpi .n{font-size:20px;font-weight:650;margin:2px 0 0;white-space:nowrap}
.uc-kpi .o{font-size:12px;color:var(--mut)}
.uc-kpi .d{font-size:12px;font-weight:600}.uc-kpi .d.good{color:var(--good)}.uc-kpi .d.bad{color:var(--bad)}
.uc-chart{margin:4px 0 0}.uc-chart svg{width:100%;height:auto;display:block}
.uc-cap{display:flex;justify-content:space-between;font-size:11px;color:var(--mut);margin-top:2px}
.uc-go{display:block;margin:12px 0 0;padding:11px 14px;border-radius:12px;background:var(--soft);color:var(--fg);
  text-decoration:none;font-size:14px}
.uc-go b{font-weight:600}
details.uc-sec{border:1px solid var(--line);border-radius:16px;margin:0 0 10px;background:var(--card)}
details.uc-sec>summary{list-style:none;padding:13px 16px;display:flex;justify-content:space-between;gap:10px;
  align-items:center;font-weight:600;cursor:pointer}
details.uc-sec>summary::-webkit-details-marker{display:none}
details.uc-sec>summary::after{content:'▾';color:var(--mut)}details.uc-sec[open]>summary::after{content:'▴'}
details.uc-sec>.in{padding:0 16px 14px;overflow-x:auto}
details.uc-sec>.in>h2:first-child{display:none}
.uc-card{border:1px solid var(--line);border-radius:16px;background:var(--card);padding:14px 16px;margin:0 0 10px}
.uc-card h3{font-size:16px;margin:0 0 8px}.uc-card h3 .mut{font-weight:400;font-size:13px}
.uc-card p{margin:0;font-size:14px;line-height:1.5}
.uc-ul{margin:0;padding-left:18px}.uc-ul li{margin:0 0 8px;font-size:14px;line-height:1.5}
.uc-m{font-size:14px;margin:10px 0 0;line-height:1.5}.uc-small{font-size:13px;color:var(--mut);margin:6px 0 0!important}
.uc-more{font-size:13px;color:var(--mut);margin:18px 0 8px}
@media(max-width:420px){.uc-kpi{gap:6px}.uc-kpi>div{padding:8px}.uc-kpi .n{font-size:17px}}
</style>"""

OPEN_JS = ("<script>(()=>{const o=()=>{const h=decodeURIComponent(location.hash.slice(1));if(!h)return;"
           "const e=document.getElementById(h);const d=e&&e.closest('details');if(d){d.open=true;e.scrollIntoView()}};"
           "o();addEventListener('hashchange',o)})()</script>")


def _day(ts):
    t = dt.datetime.fromtimestamp(ts, TZ) if TZ else dt.datetime.fromtimestamp(ts)
    return t.date()


def trades(path=None, full=False):
    """Closed demo trades without manual sales: [(closed_ts, ret, exit_reason)], with full=True also
    (pnl_usd, config dict) at the end."""
    path = path or data.PAPER_DB
    if not os.path.exists(path):
        return []
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    try:
        out = []
        for ts, r, ex, pnl, conf in con.execute(
                "SELECT closed_ts, ret, exit_reason, pnl_usd, config FROM trades WHERE status='closed' "
                "AND closed_ts IS NOT NULL AND COALESCE(state,'') NOT LIKE '%\"rucno\"%' ORDER BY closed_ts"):
            row = (int(ts), float(r or 0), str(ex or ""))
            if full:
                try:
                    c = json.loads(conf or "{}")
                except ValueError:
                    c = {}
                row += (float(pnl or 0), c if isinstance(c, dict) else {})
            out.append(row)
        return out
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


def _stats(rows):
    n = len(rows)
    if not n:
        return {"n": 0, "win": None, "mean": None, "bad": None}
    rs = [min(CAP, x[1]) for x in rows]
    return {"n": n, "win": sum(r > 0 for r in rs) / n, "mean": sum(rs) / n,
            "bad": sum(x[2] in BAD_EXITS for x in rows) / n}


def daily(rows, today=None):
    """{date: stats} for every calendar day from the first trade to today (days without trades have n=0)."""
    if not rows:
        return {}
    by = {}
    for x in rows:
        by.setdefault(_day(x[0]), []).append(x)
    d, end = min(by), max(max(by), today or max(by))
    out = {}
    while d <= end:
        out[d] = _stats(by.get(d, []))
        d += dt.timedelta(days=1)
    return out


def compare(rows, now=None):
    """Start (first WINDOW_D days that had trades) against now (last WINDOW_D calendar days, today included)."""
    now = now or time.time()
    if not rows:
        return None
    today = _day(now)
    days = sorted({_day(x[0]) for x in rows})
    first = set(days[:WINDOW_D])
    recent = {today - dt.timedelta(days=i) for i in range(WINDOW_D)}
    if first & recent:  # too young: the two windows overlap
        return {"start": _stats([x for x in rows if _day(x[0]) in first]), "now": None,
                "first_day": days[0], "days": len(days), "today": today}
    return {"start": _stats([x for x in rows if _day(x[0]) in first]),
            "now": _stats([x for x in rows if _day(x[0]) in recent]),
            "first_day": days[0], "start_to": max(first), "days": len(days), "today": today}


def verdict(c):
    """(css class, sentence) for the headline."""
    if not c:
        return "", "Još nema zatvorenih demo tradeova, pa se napredak ne može mjeriti."
    s, n = c["start"], c["now"]
    if n is None:
        return "", (f"Alat trguje u demu tek {c['days']} {'dan' if c['days'] == 1 else 'dana'}. Usporedba s početkom "
                    f"kreće kad prođe više od {2 * WINDOW_D} dana.")
    if s["n"] < MIN_N or n["n"] < MIN_N:
        return "", (f"Premalo tradeova za pošten zaključak (početak {s['n']}, zadnja {WINDOW_D} dana {n['n']}; "
                    f"treba barem {MIN_N} na svakoj strani).")
    d = n["mean"] - s["mean"]
    if d >= SAME_PP:
        return "good", (f"Alat je bolji nego na početku: prosječan trade sad donosi {n['mean']:+.0%}, "
                        f"a na početku {s['mean']:+.0%}.")
    if d <= -SAME_PP:
        return "bad", (f"Alat je zasad lošiji nego na početku: prosječan trade sad donosi {n['mean']:+.0%}, "
                       f"a na početku {s['mean']:+.0%}. "
                       "Učenje radi dalje i ovo će pokazati čim se popravi.")
    return "", "Alat je otprilike jednak kao na početku (razlika po tradeu manja od 2 postotna boda)."


def _pct(x, sign=True):
    return "–" if x is None else (f"{x:+.0%}" if sign else f"{x:.0%}")


def _delta(a, b, lower_better=False, pp=True):
    if a is None or b is None:
        return ""
    d = b - a
    if abs(d) < 0.005:
        return "<span class=d>bez promjene</span>"
    good = (d < 0) if lower_better else (d > 0)
    return f"<span class='d {'good' if good else 'bad'}'>{'▲' if d > 0 else '▼'} {abs(d) * 100:.0f} {'p.b.' if pp else ''}</span>"


def _kpi(label, explain, now, start, delta, gk=None):
    return (f"<div><div class=l>{esc(label)} {tip(explain, gk)}</div><div class=n>{now}</div>"
            f"<div class=o>na početku {start}</div>{delta}</div>")


def chart(days):
    """Bar per day: average result per trade after costs (green above zero, red below). Faded = fewer than 3 trades."""
    items = list(days.items())[-30:]
    if not items:
        return ""
    vals = [s["mean"] for _, s in items if s["mean"] is not None]
    top = max([0.05] + [abs(v) for v in vals])
    w, h, gap = 300, 90, 2
    bw = max(2.0, (w - gap * (len(items) - 1)) / len(items))
    mid = h / 2
    bars = []
    for i, (d, s) in enumerate(items):
        x = i * (bw + gap)
        if s["mean"] is None:
            bars.append(f'<rect x="{x:.1f}" y="{mid - 0.5:.1f}" width="{bw:.1f}" height="1" fill="var(--line)">'
                        f'<title>{d:%d.%m.}: nema zatvorenih tradeova</title></rect>')
            continue
        v = s["mean"]
        bh = max(1.5, abs(v) / top * (mid - 4))
        y = mid - bh if v >= 0 else mid
        op = "1" if s["n"] >= 3 else ".45"
        col = "var(--good)" if v >= 0 else "var(--bad)"
        bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="1.5" fill="{col}" '
                    f'opacity="{op}"><title>{d:%d.%m.}: {s["n"]} tradeova, u plusu {s["win"]:.0%}, '
                    f'prosjek {v:+.0%} po tradeu</title></rect>')
    first, last = items[0][0], items[-1][0]
    return (f'<div class=uc-chart><svg viewBox="0 0 {w} {h}" role="img" aria-label="Prosjek po tradeu, dan po dan">'
            f'<line x1="0" y1="{mid}" x2="{w}" y2="{mid}" stroke="var(--line)" stroke-width="1"/>{"".join(bars)}</svg>'
            f'<div class=uc-cap><span>{first:%d.%m.}</span><span>prosjek po tradeu, dan po dan</span>'
            f'<span>{last:%d.%m.}</span></div></div>')


def progress_html(now=None, path=None):
    now = now or time.time()
    rows = trades(path)
    c = compare(rows, now)
    cls, line = verdict(c)
    out = [CSS, "<div class=uc-top>", f"<p class='uc-v {cls}'>{esc(line)}</p>"]
    if c:
        s, n = c["start"], c["now"] or {"n": 0, "win": None, "mean": None, "bad": None}
        span = (f"{c['first_day']:%d.%m.}–{c['start_to']:%d.%m.}" if c.get("start_to") else f"od {c['first_day']:%d.%m.}")
        out.append(f"<p class=uc-sub>Zadnja {WINDOW_D} dana ({n['n']} tradeova) prema prva {WINDOW_D} dana "
                   f"({esc(span)}, {s['n']} tradeova). Demo, nakon naknada i slippagea. "
                   + tip("Gledamo 3 dana, ne jedan, da jedan sretan ili loš dan ne odluči. Brojimo zatvorene demo tradeove "
                         "bez ručnih prodaja; jedan trade najviše +300%, da jedan sretan pogodak ne iskrivi prosjek.")
                   + "</p>")
        usd_now = "" if n["mean"] is None else f"<div class=o>na $100: {_usd(n['mean'] * 100)}</div>"
        out.append("<div class=uc-kpi>"
                   + _kpi("U plusu", "Koliko tradeova je završilo u plusu nakon troškova (win rate).",
                          _pct(n["win"], False), _pct(s["win"], False), _delta(s["win"], n["win"]), "uspjesnost")
                   + _kpi("Prosjek po tradeu", "Prosječna zarada ili gubitak po tradeu nakon naknada i slippagea. "
                          "Ovo je glavni broj: alat je bolji kad ovaj broj raste.",
                          _pct(n["mean"]), _pct(s["mean"]), _delta(s["mean"], n["mean"]) + usd_now)
                   + _kpi("Rug i stop loss", "Koliki dio tradeova je završio rugom (likvidnost nestala) ili stop "
                          "lossom. Manje je bolje.", _pct(n["bad"], False), _pct(s["bad"], False),
                          _delta(s["bad"], n["bad"], lower_better=True), "stop-loss")
                   + "</div>")
        out.append(chart(daily(rows, c["today"])))
    out.append("<a class=uc-go href=/pravi-trade>Koga pratiti s pravim novcem? Alat sam bira influencere i wallete po "
               "rezultatima: <b>Autopilot →</b></a>")
    out.append("</div>")
    return "".join(out)


_H2 = re.compile(r"<h2(?: id=([\w-]+))?>(.*?)</h2>", re.S)


def fold(body):
    """Every <h2> section of the old page becomes a closed section that opens on tap (content untouched)."""
    parts = _H2.split(body)
    out = [parts[0]]
    for i in range(1, len(parts), 3):
        sid, title, chunk = parts[i], parts[i + 1], parts[i + 2]
        idattr = f" id={sid}" if sid else ""
        out.append(f"<details class=uc-sec{idattr}><summary>{title}</summary><div class=in>{chunk}</div></details>")
    return "".join(out) + OPEN_JS


# --- the plain-words story under the headline: where it earned, where it lost, what it learned, how it fixes itself

PLAT_HR = {"tg": "Telegram", "x": "KOL-ovi na X-u", "dex": "DexScreener", "pump": "pump.fun i KOL novčanici",
           "chain": "novčanici na lancu", "meta": "vruća tema"}
SESS_WORD = {"asia": "noću (azijska sesija)", "eu": "ujutro i rano popodne (europska sesija)",
             "us": "popodne i navečer (američka sesija)"}
EXIT_WORD = {"take_profit": "take profitom (prodao na cilju)", "trailing": "trailing stopom (prodao kad je počeo padati s vrha)",
             "moonbag_trailing": "moonbagom (zadnji dio prodan kad je pao s vrha)", "smart_sell_eksplozija": "smart sellom na naglom skoku",
             "stop_loss": "stop loss (cijena je pala ispod granice)", "rug": "rug (likvidnost je nestala)",
             "time": "isteklo vrijeme bez rasta", "stale": "token je stao, nema rasta", "breakeven": "prodaja na ulaznoj cijeni",
             "moonbag_time": "moonbag: isteklo vrijeme"}
DAYS_STORY = 7
MIN_GROUP = 5


def _exit_key(ex):
    return "take_profit" if ex.startswith("take_profit") else ex


def group_name(c):
    """Plain words for what triggered the trade: sources + time of day (+ 'više izvora odjednom')."""
    arm = str(c.get("arm") or "")
    plats, _, sess = arm.partition("|")
    names = [PLAT_HR.get(p, p) for p in plats.split("+") if p]
    src = " + ".join(names) or "ostali signali"
    if c.get("entry_mode") == "konv":
        src = "više izvora odjednom (" + src + ")"
    return src + (f", {SESS_WORD[sess]}" if sess in SESS_WORD else "")


def groups(rows, now=None, days=DAYS_STORY):
    now = now or time.time()
    by = {}
    for ts, ret, ex, pnl, c in rows:
        if ts < now - days * 86400:
            continue
        g = by.setdefault(group_name(c), {"n": 0, "usd": 0.0, "w": 0, "exits_w": {}, "exits_l": {}})
        g["n"] += 1
        g["usd"] += pnl
        k = _exit_key(ex)
        if ret > 0:
            g["w"] += 1
            g["exits_w"][k] = g["exits_w"].get(k, 0) + pnl
        else:
            g["exits_l"][k] = g["exits_l"].get(k, 0) - pnl
    return {k: v for k, v in by.items() if v["n"] >= MIN_GROUP}


def _usd(x):
    return f"{'+' if x >= 0 else '−'}${abs(x):,.0f}"


def _why(exits, win):
    if not exits:
        return ""
    k = max(exits, key=exits.get)
    tot = sum(v for v in exits.values() if v > 0) or 1
    share = exits[k] / tot
    return (f"{'Dobit' if win else 'Gubitak'} najčešće {'uzima' if win else 'dolazi od:'} {EXIT_WORD.get(k, k.replace('_', ' '))}"
            f" ({share:.0%} {'dobiti' if win else 'gubitka'}).")


def money_html(rows, now):
    tot = sum(x[3] for x in rows)
    wk = [x for x in rows if x[0] >= now - DAYS_STORY * 86400]
    s7 = sum(x[3] for x in wk)
    return (f"<p class=uc-m>Je li zaradio? Demo od početka: <b class={'pos' if tot >= 0 else 'neg'}>{_usd(tot)}</b> na "
            f"{len(rows)} tradeova; zadnjih {DAYS_STORY} dana <b class={'pos' if s7 >= 0 else 'neg'}>{_usd(s7)}</b> na {len(wk)}. "
            + tip("Demo novac, ulog po tradeu je mali (oko $20). Nakon naknada i slippagea; ručne prodaje se ne broje.")
            + "</p>")


def earn_lose_html(rows, now):
    g = groups(rows, now)
    if not g:
        return ""
    win = sorted([(k, v) for k, v in g.items() if v["usd"] > 0], key=lambda kv: -kv[1]["usd"])[:3]
    lose = sorted([(k, v) for k, v in g.items() if v["usd"] < 0], key=lambda kv: kv[1]["usd"])[:3]

    def item(k, v, w):
        return (f"<li><b>{esc(k)}</b>: {_usd(v['usd'])} na {v['n']} tradeova, {v['w'] / v['n']:.0%} u plusu. "
                f"<span class=mut>{esc(_why(v['exits_w'] if w else v['exits_l'], w))}</span></li>")
    out = ["<div class=uc-card><h3>✅ Na čemu zarađuje <span class=mut>(zadnjih 7 dana)</span></h3>"]
    out.append("<ul class=uc-ul>" + "".join(item(k, v, True) for k, v in win) + "</ul>" if win else
               "<p class=mut>Nijedna vrsta ulaza zasad nije u plusu.</p>")
    out.append("</div><div class=uc-card><h3>❌ Na čemu gubi <span class=mut>(zadnjih 7 dana)</span></h3>")
    out.append("<ul class=uc-ul>" + "".join(item(k, v, False) for k, v in lose) + "</ul>" if lose else
               "<p class=mut>Nijedna vrsta ulaza nije u minusu.</p>")
    # where the losing money went overall
    lost = {}
    for ts, ret, ex, pnl, c in rows:
        if ts >= now - DAYS_STORY * 86400 and pnl < 0:
            k = _exit_key(ex)
            lost[k] = lost.get(k, 0) - pnl
    tot = sum(lost.values())
    if tot > 0:
        parts = ", ".join(f"{EXIT_WORD.get(k, k).split(' (')[0]} {v / tot:.0%}"
                          for k, v in sorted(lost.items(), key=lambda kv: -kv[1])[:3])
        out.append(f"<p class=uc-small>Odakle dolazi izgubljeni novac: {esc(parts)}.</p>")
    out.append("</div>")
    # what a person can do with it
    act = []
    if win:
        act.append(f"Najbolje prolaze tokeni iz izvora <b>{esc(win[0][0])}</b>.")
    if lose:
        act.append(f"Najlošije: <b>{esc(lose[0][0])}</b>; tu budi oprezniji ili uzmi manji ulog.")
    if act:
        out.append("<div class=uc-card><h3>👉 Što ti možeš s tim</h3><p>" + " ".join(act)
                   + " <span class=mut>To je rezultat demo tradeova iz prošlosti, ne jamstvo zarade.</span></p></div>")
    return "".join(out)


def _ts_day(ts):
    return f"{_day(ts):%d.%m.}"


def learned_html(now):
    """What the tool changed by itself, newest first, from the logs the learning already keeps (read only)."""
    ev = []
    try:
        from paper import auto, rules
        for h in auto.load().get("history") or []:
            if h.get("text"):
                ev.append((h.get("ts") or 0, h["text"]))
        for h in rules.load().get("history") or []:
            if h.get("text"):
                ev.append((h.get("ts") or 0, h["text"]))
    except Exception as e:  # noqa: BLE001
        print(f"učenje: povijest pravila: {type(e).__name__}: {e}")
    # signal weights: cumulative change of the last 7 days, all classes together
    try:
        if os.path.exists(data.HYPE_DB):
            from learn import store as lstore
            from ui.labels import feat
            con = sqlite3.connect(f"file:{data.HYPE_DB}?mode=ro", uri=True, timeout=10)
            con.row_factory = sqlite3.Row
            try:
                runs = [r for r in lstore.runs(con, None, 200) if r["applied"] and r["ts"] >= now - DAYS_STORY * 86400
                        and r["klasa"] not in ("confidence", "rugprofil", "model")]
            finally:
                con.close()
            d = {}
            for r in runs:
                for k, v in (r["new"] or {}).items():
                    o = (r.get("old") or {}).get(k, 0)
                    if isinstance(v, (int, float)) and isinstance(o, (int, float)) and not isinstance(v, bool):
                        d[k] = d.get(k, 0) + (v - o)
            up = [feat(k) for k, x in sorted(d.items(), key=lambda kv: -kv[1]) if x >= 0.5][:3]
            dn = [feat(k) for k, x in sorted(d.items(), key=lambda kv: kv[1]) if x <= -0.5][:3]
            if up or dn:
                ev.append((max(r["ts"] for r in runs), "Ocjena tokena: " + (
                    ("sad više vjeruje signalima " + ", ".join(up)) if up else "") + ("; " if up and dn else "") + (
                    ("manje vjeruje " + ", ".join(dn)) if dn else "") + " (naučeno iz stvarne zarade)."))
    except Exception as e:  # noqa: BLE001
        print(f"učenje: težine: {type(e).__name__}: {e}")
    try:
        from learn import detektiv
        ov = detektiv.overview() or {}
        for h in ov.get("rows") or []:
            if h["status"] == "prošla":
                ev.append((h["ts"] if "ts" in h.keys() else now, f"Novo pravilo prošlo test na novim podacima: {h['naslov']}."))
    except Exception as e:  # noqa: BLE001
        print(f"učenje: hipoteze: {type(e).__name__}: {e}")
    ev = sorted(ev, key=lambda e: -e[0])[:6]
    if not ev:
        return ("<div class=uc-card><h3>🧠 Što je naučio i sam promijenio</h3><p class=mut>Još ništa nije promijenio: "
                "svaka promjena treba dovoljno tradeova i mora biti bolja i na starijim i na novijim podacima.</p></div>")
    return ("<div class=uc-card><h3>🧠 Što je naučio i sam promijenio</h3><ul class=uc-ul>"
            + "".join(f"<li><span class=mut>{_ts_day(ts) if ts else ''}</span> {esc(t)}</li>" for ts, t in ev)
            + "</ul></div>")


def selffix_html(now):
    """How it fixes itself, each line with today's state."""
    li = []
    try:
        from learn import outcomes
        li.append(f"<b>Svaki dan</b> ({esc(outcomes.config()['run_at_utc'])} UTC) ponovno računa koliko vjeruje kojem "
                  "signalu, iz stvarne zarade. Promjena ulazi samo ako je bolja i na starijim i na novijim podacima, "
                  "inače ostaje staro.")
    except Exception:  # noqa: BLE001
        pass
    try:
        from paper import liga
        if os.path.exists(data.PAPER_DB):
            con = sqlite3.connect(f"file:{data.PAPER_DB}?mode=ro", uri=True, timeout=10)
            try:
                g = liga.proven(con, now)
            finally:
                con.close()
            ok = [k for k, v in g.items() if v["proven"]]
            li.append(f"<b>Svakih 10 minuta</b> bot u Natjecanju bira samo vrste ulaza koje su zadnjih 7 dana dokazano "
                      f"zarađivale. Sada: <b>{len(ok)} od {len(g)}</b>" + (". Dok nijedna nije dokazana, ne troši novac."
                                                                           if not ok else ".")
                      + " " + tip("Vrsta ulaza = odakle je signal došao + doba dana. Dokazana = barem 15 tradeova, "
                                  "prosjek nakon troškova iznad nule i to sigurno, ne slučajno.", "liga"))
    except Exception as e:  # noqa: BLE001
        print(f"učenje: liga: {type(e).__name__}: {e}")
    try:
        from paper import rules
        by = ((rules.load().get("sessions") or {}).get("by") or {})
        cut = []
        for s, v in by.items():
            f = v.get("factor", 1.0)
            if s in SESS_WORD and f is not None and f < 1:
                cut.append(SESS_WORD[s].split(" (")[0] + (" pauza" if f == 0 else f" ulog {f:.0%}"))
        li.append("<b>Jednom dnevno</b> doba dana koje gubi dobije manji ulog ili pauzu. Sada: "
                  + (esc(", ".join(cut)) if cut else "sva doba dana igraju punim ulogom") + ".")
    except Exception:  # noqa: BLE001
        pass
    li.append("<b>Svaki dan</b> na tisućama prilika isproba različite stop lossove i izlaze i sam uzme najbolje.")
    li.append("<b>Svaki sat</b> izbaci rugove i uči kako izgleda rug na ulazu, pa sličan token odmah preskoči.")
    return "<div class=uc-card><h3>🔧 Kako se sam popravlja</h3><ul class=uc-ul>" + "".join(f"<li>{x}</li>" for x in li) + "</ul></div>"


def story_html(now=None, path=None):
    now = now or time.time()
    rows = trades(path, full=True)
    out = []
    for name, fn in (("zarada", lambda: money_html(rows, now) if rows else ""),
                     ("zarada/gubitak", lambda: earn_lose_html(rows, now)),
                     ("naučeno", lambda: learned_html(now)), ("popravak", lambda: selffix_html(now))):
        try:
            out.append(fn())
        except Exception as e:  # noqa: BLE001
            print(f"učenje: {name}: {type(e).__name__}: {e}")
    return "".join(out)
