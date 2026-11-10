"""One function per page. Each returns (title, body_html)."""
import datetime as dt
import os
import time
from urllib.parse import quote

from ui import data, explain, jobs, labels
from eventpick import load as pickload, score as pickscore
from ui.labels import FEATURE_DESC
from ui.html import (tdesc, info, ago, badge, bar, breakdown, esc, ext_icons, ext_token, ext_wallet, filt, mins, num, price, scorecell,
                     short, signed, table, tierb, tlink, ts, usd, verdict, wlink)

ROLE = {
    "early_buyer": ("rani kupac", "kupio među prvima token koji je kasnije narastao (pobjednik)"),
    "smart": ("smart money", "označen kao uspješan trader"),
    "top_trader": ("top trader", "među najboljim traderima tokena"),
    "holder": ("holder", "među top holderima tokena u rug provjeri"),
    "manual": ("ručno", "dodan ručno"),
    "dev": ("dev", "kreator tokena: nikad se ne kopira"),
    "bundler": ("bundler", "kupio u istom bloku kao kreacija (bundle)"),
    "sniper": ("snajper", "kupio u prvih par sekundi: bot, ne kopira se"),
    "funder": ("financijer", "poslao SOL devu ili ranim kupcima"),
    "dust": ("sitni kupac", "kupio premalo (ispod 0.1 SOL) da bi se računao"),
}
SOURCE = {"harvest": "rani kupci pobjedničkih tokena", "hype_learn": "smart walleti iz hype skenera",
          "rug": "rug filter", "manual": "ručno"}

FEATURE = FEATURE_DESC  # kept for older imports


# ---------------- wallets ----------------
# 10.11. (Jure: "Ostalo mi se sviđa", prijedlog 4.6 i 4.7, makete audit/2026-11-10/makete/novcanici.html i novcanik.html):
# Novčanici i jedan novčanik u mirnom jeziku ui/redak.py. Popis: hero "Koga kopirati", segment, polje za traženje,
# reci "adresa + jedan razlog + zarada" (stupci samo na računalu). Novčanik: presuda s "dokazan dvaput" (brojke prije i
# poslije reza iz wallets/dokazani), četiri broja, graf s crtom reza, traka pozicija, pet zadnjih tradeova, a raspisi,
# sve brojke, povijest i registar su jedan dodir dalje (?v=...). Podaci, ocjene i pravila se ne mijenjaju.
from ui import redak as rd  # noqa: E402
from ui import walletchart  # noqa: E402

W_CSS = """<style>
.ms-wl{margin:0}
.ms-wr,.ms-wth{display:grid;grid-template-columns:minmax(0,1fr) auto 12px;column-gap:12px;align-items:center}
.ms-wr{grid-template-areas:"tk v chev" "why w chev";padding:11px 0;border-bottom:1px solid var(--line);min-height:64px;color:var(--fg);text-decoration:none}
a.ms-wr:hover .tk{color:var(--acc)}
.ms-wr .tk{grid-area:tk;font-size:17px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ms-wr .why{grid-area:why;font-size:15px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ms-wr .v{grid-area:v;text-align:right;font-size:17px;font-weight:600;white-space:nowrap}
.ms-wr .w{grid-area:w;text-align:right;font-size:15px;color:var(--mut);white-space:nowrap}
.ms-wr .ms-chev{grid-area:chev}.ms-wr .x{display:none}
.ms-wl>.ms-wr:last-child{border-bottom:0}
.ms-wr .pos{color:var(--good)}.ms-wr .neg{color:var(--bad)}.ms-wr .warn{color:var(--warn)}
.ms-wth{display:flex;justify-content:space-between;align-items:baseline;font-size:15px;color:var(--mut);padding:18px 0 8px;border-bottom:1px solid var(--line)}
.ms-wth .d{display:none}
.ms-so{position:relative}.ms-so summary{list-style:none;cursor:pointer;color:var(--acc);font-weight:500;white-space:nowrap}
.ms-so summary::-webkit-details-marker{display:none}
.ms-so summary::after{content:"";display:inline-block;width:6px;height:6px;border-right:1.5px solid var(--acc);border-bottom:1.5px solid var(--acc);transform:rotate(45deg);margin:0 0 3px 7px}
.ms-so .mn{position:absolute;left:0;top:calc(100% + 6px);z-index:5;background:#fff;border:1px solid var(--line);border-radius:12px;box-shadow:0 8px 24px rgba(11,18,32,.12);padding:6px;min-width:220px}
.ms-so .mn a{display:block;padding:8px 10px;border-radius:8px;font-size:15px;color:var(--fg);text-decoration:none;white-space:nowrap}
.ms-so .mn a:hover{background:var(--soft)}.ms-so .mn a.on{color:var(--acc);font-weight:600}
.ms-fld{display:flex;align-items:center;gap:8px;background:var(--soft);border-radius:11px;padding:9px 12px;color:var(--mut);font-size:17px;margin:14px 0 0}
.ms-fld svg{width:17px;height:17px;fill:none;stroke:var(--mut);stroke-width:2;stroke-linecap:round;flex:none}
.ms-fld input{flex:1;min-width:0;border:0;background:transparent;font:inherit;color:var(--fg);padding:0;outline:0;-webkit-appearance:none;appearance:none}
.ms-fld input::placeholder{color:var(--mut)}
.ms-foot{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px 12px;padding:14px 0;border-top:1px solid var(--line);margin:18px 0 0;font-size:15px;color:var(--mut)}
.ms-foot form{margin:0}.ms-foot button{border:0;background:none;padding:0;font:inherit;font-weight:500;color:var(--acc);cursor:pointer}
.ms-foot button[disabled]{color:var(--mut);cursor:default}
.ms-foot details{flex-basis:100%}.ms-foot details pre{font-size:12px;white-space:pre-wrap;color:var(--mut)}
.ms-empty{text-align:center;padding:28px 6px 16px}.ms-empty b{display:block;font-size:17px;font-weight:600;color:var(--fg)}
.ms-empty p{font-size:15px;color:var(--mut);margin:6px 0 12px;line-height:1.4}.ms-empty a{font-size:15px;color:var(--acc);font-weight:500;text-decoration:none}
.ms-hint a{color:var(--acc);text-decoration:none}
.ms-panel .ms-go b{color:var(--fg);font-weight:600}
.ms-back{display:inline-flex;align-items:center;gap:7px;color:var(--acc);font-size:17px;padding:8px 0 0;text-decoration:none}
.ms-back::before{content:"";width:9px;height:9px;border-left:2px solid var(--acc);border-bottom:2px solid var(--acc);transform:rotate(45deg);margin-left:3px}
.ms-dh{padding:12px 0 0}.ms-dh .ms-s{font-size:15px;color:var(--mut);margin-top:4px;overflow-wrap:anywhere}
.ms-dh .ms-s a{color:var(--acc);text-decoration:none}
.ms-cp{display:inline-block;vertical-align:middle;width:11px;height:13px;border:1.6px solid var(--mut);border-radius:3px;margin:0 6px 3px 6px;box-shadow:2px -2px 0 -.5px #fff,3px -3px 0 0 var(--mut);cursor:pointer}
.ms-key{margin-top:6px}.ms-key .ms-v{font-size:22px;font-weight:700;letter-spacing:-.02em}
.ms-ap{border-top:1px solid var(--line);margin:8px 0 0}
.ms-ap .ms-row{min-height:60px}
.ms-wrap .ms-s{white-space:normal}.ms-dh+.ms-list,.ms-dh+.ms-colhead,.ms-dh+.ms-sub{margin-top:14px}
@media(min-width:900px){
 .ms-wr,.ms-wth.grid{display:grid;grid-template-columns:minmax(0,1fr) 64px 104px 92px 56px 72px 76px 92px 14px;column-gap:14px}
 .ms-wr{grid-template-areas:"tk cs v w hd dk ap last chev" "why cs v w hd dk ap last chev"}
 .ms-wr .x{display:block;text-align:right;font-size:15px;grid-row:1/3}
 .ms-wr .v,.ms-wr .w{grid-row:1/3}.ms-wr .w{font-size:17px;color:var(--fg)}
 .ms-wr .cs{grid-area:cs;font-size:17px;font-weight:600}.ms-wr .hd{grid-area:hd}.ms-wr .dk{grid-area:dk}.ms-wr .ap{grid-area:ap}
 .ms-wr .last{grid-area:last;color:var(--mut)}
 .ms-wth.grid{font-size:13px}.ms-wth.grid>span{text-align:right}.ms-wth.grid>:first-child{text-align:left}
 .ms-wth .p{display:none}.ms-wth .d{display:inline}
 .ms-g2{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);column-gap:44px;align-items:start}
 .ms-g2>div>.ms-h2:first-child{margin-top:28px}
}
</style>"""

# one tap to copy the full address (the old 📋 next to tokens is an emoji; rule 5: a line icon instead)
_W_JS = ("<script>document.querySelectorAll('input[data-wf]').forEach(function(i){i.oninput=function(){"
         "var q=i.value.trim().toLowerCase();document.querySelectorAll('.ms-wr').forEach(function(r){"
         "r.style.display=!q||((r.dataset.k||'')+' '+r.textContent).toLowerCase().indexOf(q)>=0?'':'none'})}});"
         "document.querySelectorAll('.ms-cp').forEach(function(b){b.onclick=function(){var m=b.dataset.m;"
         "(navigator.clipboard?navigator.clipboard.writeText(m):Promise.reject()).then(function(){"
         "b.title='Kopirano'},function(){prompt('Kopiraj adresu:',m)})}})</script>")

SORTS = [("dokaz", "Poredano: prvo dokazani", "Prvo dokazani"), ("copy", "Poredano po copy ocjeni", "Po copy ocjeni"),
         ("zarada", "Poredano po zaradi", "Po zaradi"), ("plus", "Poredano po udjelu u plusu", "Po udjelu u plusu"),
         ("zadnji", "Poredano po zadnjem tradeu", "Po zadnjem tradeu")]


def _pl(n, one, few, many):
    """Hrvatski oblik uz broj: 1, 21, 31 -> one; 2-4, 22-24 -> few; ostalo (i 11-14) -> many."""
    try:
        n = abs(int(n or 0))
    except (TypeError, ValueError):
        n = 0
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _hold(m, full=False):
    """Držanje: "5 min", "4 h", "2 d"; full=True: "4 h 24 min". None -> "–"."""
    if m is None:
        return rd.DASH
    m = float(m)
    if m < 59.5:
        return f"{m:.0f} min"
    if m < 48 * 60:
        if full:
            hh, mm = divmod(int(round(m)), 60)
            return f"{hh} h" + (f" {mm} min" if mm else "")
        return f"{round(m / 60)} h"
    return f"{round(m / 1440)} d"


def _wwhen(t, now=None):
    """"danas 07:10", "jučer 23:55" ili "9.11. 18:58" (Jurino vrijeme)."""
    if not t:
        return rd.DASH
    now = now or time.time()
    d0, d1 = walletchart.day(t), walletchart.day(now)
    if d0 == d1:
        return "danas " + walletchart.clock(t)
    if d0 == walletchart.day(now - 86400):
        return "jučer " + walletchart.clock(t)
    return walletchart.day(t, with_time=True)


def _syms_for(mints):
    """mint -> simbol za nekoliko tokena (zadnji tradeovi novčanika). 10.11.: čitanja po ključu u hype.db, rug.db i
    paper.db umjesto data.symbols(), koji za svaku stranicu novčanika čita 20.000 signala i cijele tablice."""
    ms = [m for m in dict.fromkeys(mints or ()) if m]
    out = {}
    for i in range(0, len(ms), 400):
        part = tuple(ms[i:i + 400])
        q = ",".join("?" * len(part))
        for group, sql in (("hype", f"SELECT token AS t, symbol FROM hype_signals WHERE token IN ({q}) GROUP BY token"),
                           ("rug", f"SELECT mint AS t, symbol FROM rug_reports WHERE mint IN ({q}) GROUP BY mint"),
                           ("paper", f"SELECT token AS t, symbol FROM candidates WHERE token IN ({q})")):
            try:
                for r in data.multi(group, sql, part):
                    if r.get("symbol"):
                        out.setdefault(r["t"], str(r["symbol"]).strip().lstrip("$"))
            except Exception:  # noqa: BLE001 - a name is a nicety; the short address stays
                pass
    return out


def _tok(mint, syms):
    return syms.get(mint) or short(mint)


def _bad(w):
    """Loše oznake novčanika (bot, sniper...) i zastavica bota iz ocjene: zbog njih se ne kopira."""
    bad = sorted(set(w.get("labels") or ()) & explain.BAD_LABELS)
    if (w.get("stats") or {}).get("bot") and "bot" not in bad:
        bad.insert(0, "bot")
    return bad


def _last_buy(addr, now=None):
    """Zadnja kupnja novčanika: {mint, ts, sol, sold} ili None. Prvo živi feed (hype.db chain_trades, zadnjih 48 h po
    indeksu ts), pa spremljeni tradeovi (wallet_trades, indeks (wallet, ts)). sold: kad je isti token prodao poslije."""
    now = now or time.time()
    try:
        rows = data.q(data.HYPE_DB, "SELECT mint, ts, sol FROM chain_trades WHERE ts >= ? AND wallet=? AND side='buy' "
                      "ORDER BY ts DESC LIMIT 1", (int(now - 48 * 3600), addr))
        if rows:
            b = rows[0]
            s = data.q(data.HYPE_DB, "SELECT MAX(ts) AS ts FROM chain_trades WHERE ts >= ? AND wallet=? AND mint=? "
                       "AND side='sell'", (b["ts"], addr, b["mint"]))
            return {"mint": b["mint"], "ts": b["ts"], "sol": abs(b["sol"] or 0) or None, "sold": (s[0]["ts"] if s else None)}
        rows = data.multi("wallets", "SELECT mint, ts, sol FROM wallet_trades WHERE wallet=? AND kind='buy' "
                          "ORDER BY ts DESC LIMIT 1", (addr,))
        if rows:
            b = rows[0]
            s = data.multi("wallets", "SELECT MAX(ts) AS ts FROM wallet_trades WHERE wallet=? AND ts >= ? AND mint=? "
                           "AND kind='sell'", (addr, b["ts"], b["mint"]))
            return {"mint": b["mint"], "ts": b["ts"], "sol": abs(b["sol"] or 0) or None, "sold": (s[0]["ts"] if s else None)}
    except Exception:  # noqa: BLE001
        pass
    return None


def autopilot_marks(now=None):
    """9.11. (audit P44): what the bot copies by, next to the page's copy_score: the proven-twice list
    (wallets/dokazani.latest: wallet -> row with as_of, bags), the wallets the real-money account follows
    (ui/pravitrade.followed_wallets) and the Autopilot's 14-day wallet stats (ui/autopilot.wallet_recs). Read-only;
    every source may be missing (empty until the first run after a deploy), the page then shows "ne" / dashes."""
    proven, followed, recs, as_of = {}, set(), {}, None
    try:
        from wallets import dokazani
        for r in dokazani.latest():
            proven[r["wallet"]] = r
            as_of = max(as_of or 0, r.get("as_of") or 0) or as_of
    except Exception:  # noqa: BLE001
        pass
    try:
        from ui import pravitrade
        followed = set(pravitrade.followed_wallets())
    except Exception:  # noqa: BLE001
        pass
    try:
        from ui import autopilot
        recs = {r["wallet"]: r["s"] for r in (autopilot.wallet_recs(now) or {}).get(14) or []}
    except Exception:  # noqa: BLE001
        pass
    return {"proven": proven, "followed": followed, "recs": recs, "as_of": as_of}


def _mark_cells(w, marks):
    """Three cells: Dokazani dvaput · Prati Autopilot · Autopilot 14 d (ROI, win, closed of its chain buys)."""
    pr = marks["proven"].get(w)
    bags = f' <span class=mut title="otvorenih gubitnika koje nije zatvorio">{pr["bags"]} bagova</span>' if pr and pr.get("bags") else ""
    yes_p = (badge("DA", "good") + bags, 1, "n") if pr else (badge("ne"), 0, "n")
    yes_f = (badge("DA", "good"), 1, "n") if w in marks["followed"] else (badge("ne"), 0, "n")
    r = marks["recs"].get(w)
    rec = ((f'{signed(r["roi"], "{:+.0%}")[0]} · win {r["win"]:.0%} · {r["closed"]} zatv.', r["roi"], "n") if r
           else ("–", -1e18, "n mut"))
    return [yes_p, yes_f, rec]


MARK_HEAD = [("Dokazani dvaput", "n"), ("Prati Autopilot", "n"), ("Autopilot 14 d", "n")]


def _wallet_hero(ws, marks, now=None):
    """Hero "Koga kopirati": prvi s popisa preporuke (ui/preporuka.rank_wallets: pouzdanost, copy ocjena, zarada,
    isti red kao prijedlog na Pregledu) koji je i dokazan dvaput; bez dokazanih prvi s preporuke. None bez ikoga."""
    from ui import preporuka
    from wallets import dokazani
    try:
        ranked = preporuka.rank_wallets(ws, preporuka.copies_from_strat())
    except Exception:  # noqa: BLE001
        return None
    if not ranked:
        return None
    w, r = next(((w, r) for w, r in ranked if w["wallet"] in marks["proven"]), ranked[0])
    s, addr = w.get("stats") or {}, w["wallet"]
    proven = addr in marks["proven"]
    cop = dokazani.copyable(s, w.get("labels") or [])
    facts = rd.cat(rd.dot("good" if proven else ""), "dokazan dvaput" if proven else "nije dokazan dvaput",
                   " · ", "kopirljiv" if cop else "nije kopirljiv", " · copy ocjena" + rd.NBSP, rd.num(w.get("copy_score")))
    n = s.get("closed") or 0
    lead = {"visoka": "Najviše dokaza", "srednja": "Dovoljno dokaza"}.get(r.get("tier"), "Malo dokaza")
    why = (f"{lead}: {rd.sol(s.get('closed_pnl_sol'), 1, sign=True)} na {rd.num(n)} "
           f"{_pl(n, 'zatvorenoj', 'zatvorene', 'zatvorenih')}, {rd.pct(s.get('win_rate'), sign=False, frac=True)} u plusu"
           + (", prije i poslije reza" if proven else "") + f". Drži oko {_hold(s.get('median_hold_min'))}.")
    c = r.get("copy")
    if c and c[0]:   # the only real test of copying him: what the demo's copies earned (strat.db)
        why += f" Naše demo kopije: {rd.num(c[0])}, {rd.pct(c[1], sign=True, frac=True)} po tradeu."
    foot = None
    lb = _last_buy(addr, now)
    if lb:
        sym = _tok(lb["mint"], _syms_for([lb["mint"]]))
        foot = rd.raw("<span>" + rd.cat("Zadnja kupnja: ", rd.raw("<b>"), sym, rd.raw("</b> "), rd.ago(lb["ts"], now),
                                         ", još drži" if not lb.get("sold") else f", prodao {rd.ago(lb['sold'], now)}")
                      + "</span>")
    return rd.hero(short(addr), why=why, label="Koga kopirati", facts=facts, href=f"/wallet/{quote(addr)}", foot=foot)


def _wrow(w, marks, now=None, show_bad=False):
    """Jedan redak novčanika: adresa i jedan razlog lijevo, zarada i "68 % od 31" desno; na računalu i stupci Copy,
    Drži, Dokazan, Autopilot, Zadnji trade (prijedlog 4.6). show_bad: botovi i snajperi narančasto (pogled Svi)."""
    s, addr = w.get("stats") or {}, w["wallet"]
    proven, followed = addr in marks["proven"], addr in marks["followed"]
    rec = marks["recs"].get(addr)
    bad = _bad(w) if show_bad else []
    why = []
    if bad:
        why.append(rd.raw(f'<span class="warn">{rd.h(", ".join(labels.wallet_label(b) for b in bad))}</span>'))
    if proven:
        why.append(rd.cat(rd.dot("good"), "dokazan dvaput"))
    if not s:
        why.append("još nije ocijenjen")
    else:
        why.append(f"drži {_hold(s.get('median_hold_min'))}")
        if bad:
            why.append(f"{rd.num(s.get('trades_per_day'))} dnevno")
    if followed and not proven:
        why.append("prati Autopilot")
    n = s.get("closed") or 0
    pnl = s.get("closed_pnl_sol")
    val = rd.sol(pnl, 1, sign=True) if s else rd.DASH
    sub = f"{rd.pct(s.get('win_rate'), sign=False, frac=True)} od {rd.num(n)}" if s and n else ""
    if rec:
        ap = (f'<span class="x ap {rd.tone(rec.get("roi"))}" title="Autopilot 14 d: {rd.h(rd.pct(rec.get("win"), sign=False, frac=True))} '
              f'u plusu, {rd.h(rd.num(rec.get("closed")))} zatvorenih">{rd.h(rd.pct(rec.get("roi"), sign=True, frac=True))}</span>')
    else:
        ap = f'<span class="x ap">{"da" if followed else rd.DASH}</span>'
    pr = marks["proven"].get(addr) or {}
    dk_t = f' title="{rd.h(rd.num(pr["bags"]))} otvorenih gubitnika"' if pr.get("bags") else ""
    key = " ".join([addr] + list(w.get("labels") or []))
    return rd.raw(
        f'<a class="ms-wr" href="/wallet/{quote(addr)}" data-k="{rd.h(key)}"><span class="tk">{rd.h(short(addr))}</span>'
        f'<span class="why">{rd.cat(*why, sep=" · ")}</span>'
        f'<span class="v {rd.tone(pnl) if s else ""}">{rd.h(val)}</span><span class="w">{rd.h(sub)}</span>'
        f'<span class="x cs">{rd.h(rd.num(w.get("copy_score")))}</span>'
        f'<span class="x hd">{rd.h(_hold(s.get("median_hold_min")) if s else rd.DASH)}</span>'
        f'<span class="x dk"{dk_t}>{"da" if proven else rd.DASH}</span>{ap}'
        f'<span class="x last">{rd.h(rd.ago(w.get("last_tx_ts"), now))}</span><span class="ms-chev" aria-hidden="true"></span></a>')


def _f(x, default=0.0):
    return default if x is None else float(x)


def _sort_ws(ws, key, marks):
    if key == "dokaz":
        # 9.11. (audit P44): the wallets the Autopilot actually copies by (proven twice, followed) on top of the
        # copy_score order, so the hand pick and the bot's pick are the same list (stable sort keeps copy_score order)
        return sorted(ws, key=lambda w: (w["wallet"] in marks["proven"], w["wallet"] in marks["followed"]), reverse=True)
    if key == "zarada":
        return sorted(ws, key=lambda w: -_f((w.get("stats") or {}).get("closed_pnl_sol"), -1e9))
    if key == "plus":
        return sorted(ws, key=lambda w: (-((w.get("stats") or {}).get("win_rate") or 0), -((w.get("stats") or {}).get("closed") or 0)))
    if key == "zadnji":
        return sorted(ws, key=lambda w: -(w.get("last_tx_ts") or 0))
    return list(ws)   # "copy": data.wallets already orders by copy_score, score, priority


def _sort_menu(v, cur):
    base = "/wallets" + ("?v=svi&" if v == "svi" else "?")
    label = next((t for k, t, _ in SORTS if k == cur), SORTS[0][1])
    items = "".join(f'<a href="{base}s={k}"{" class=on" if k == cur else ""}>{rd.h(m)}</a>' for k, _, m in SORTS)
    return rd.raw(f'<details class="ms-so"><summary>{rd.h(label)}</summary><div class="mn">{items}</div></details>')


def _wallets_foot(ws, marks, now=None):
    """Redak na dnu: kad su ocjene i lista dokazanih zadnji put izračunate, i (samo administrator) "Ocijeni sada"."""
    now = now or time.time()
    scored = max((w.get("scored_at") or 0 for w in ws), default=0)
    left = []
    if scored:
        left.append(f"Ocijenjeno {rd.ago(scored, now)}")
    if marks.get("as_of"):
        every = float(os.environ.get("WALLETS_EVERY_H", "3") or 3) * 3600
        nxt = marks["as_of"] + every - now
        left.append(f"lista dokazanih {rd.ago(marks['as_of'], now)}"
                    + (f", sljedeća za {_hold(nxt / 60)}" if nxt > 60 else ""))
    elif ws:
        left.append("lista dokazanih još nije izračunata")
    since, last, tail = jobs.status("wallets")
    if since:
        btn = f'<button disabled>Ocjenjivanje radi ({rd.h(rd.ago(since, now))})</button>'
    else:
        err = f" (zadnji put greška, kod {last[2]})" if last and last[2] else ""
        btn = f'<button>Ocijeni sada{rd.h(err)}</button>'
    run = f'<form id=run method=post action=/run/wallets class="adm-only">{btn}</form>'
    log = (f"<details class=adm-only><summary>Zadnji ispis</summary><pre>{esc(tail)}</pre></details>" if tail else "")
    return rd.raw(f'<div class="ms-foot"><span>{rd.h(", ".join(left) or "Još nije ocijenjen nijedan novčanik")}</span>'
                  f'{run}{log}</div>')


def _wallets_hint():
    from wallets import dokazani
    r = dokazani.RULE
    return rd.raw('<p class="ms-hint" style="margin-top:4px">' + rd.h(
        f"Dokazan dvaput: u plusu na {r['min_closed']}+ zatvorenih prije reza od {r['cut_days']} dana (pola ili više "
        f"u plusu) i opet u plusu poslije njega. Kopirljiv: drži {r['min_hold_min']}+ min, do {r['max_tpd']} tradeova "
        "dnevno, nije bot ni sniper. Zarada je njegova, na lancu, ne naša kopija. ")
        + '<a href="/wallets?v=tablica">Sve brojke u tablici</a> · <a href="/pojmovnik">Pojmovnik</a></p>')


def _activity_rows(n=40, hours=48, now=None):
    """Aktivnost: tko je što kupio ili prodao (kol.db calls kind buy/sell, isti upit kao ui/core.wallet_block), kao reci:
    token lijevo, "kupio Vfdn…At74 · prije 10 h", desno SOL."""
    from ui import core
    from ui.kol import _sol
    now = now or time.time()
    con = core._con()
    if con is None:
        return rd.hint("Još nema podataka o praćenim novčanicima.")
    try:
        rows = con.execute("SELECT handle, token, symbol, kind, ts, text FROM calls WHERE kind IN ('buy', 'sell') "
                           "AND ts >= ? ORDER BY ts DESC LIMIT ?", (now - hours * 3600, n)).fetchall()
        wmap, syms = {}, {}
        if rows:
            try:
                from kol.collect import wallet_handles
                wmap = {hd: w for w, hd in wallet_handles(con).items()}
            except Exception:  # noqa: BLE001
                wmap = {}
            toks = list({r[1] for r in rows})
            syms = dict(con.execute(f"SELECT token, symbol FROM tokens WHERE token IN ({','.join('?' * len(toks))})",
                                    toks).fetchall())
    finally:
        con.close()
    items = []
    for hd, tok, sym, kind, t, text in rows:
        who = hd[2:] if hd.startswith("w:") else "@" + hd
        x = _sol(text)
        items.append({"name": syms.get(tok) or sym or short(tok),
                      "reason": f"{'kupio' if kind == 'buy' else 'prodao'} {who}",
                      "value": rd.sol(x, 2) if x else None, "sub": rd.ago(t, now), "href": f"/token/{quote(tok)}"})
    return rd.rows(items, empty=f"Praćeni novčanici u zadnjih {hours} h nisu ništa kupili ni prodali.")


def wallets(qs):
    """Novčanici: Za kopiranje (the copy list) · Svi (every wallet) · Aktivnost (who just bought or sold); ?v=tablica
    keeps the old table with every column one tap away (prijedlog 6: "tablice sa svim stupcima na računalu")."""
    # 7.11. (Jure): the copy list with its verdict opens first; the raw activity feed (addresses) goes last
    v = qs.get("v") or ("svi" if qs.get("all") == "1" else "lista")
    if v == "tablica":
        return _wallets_table(qs)
    sw = rd.seg([("/wallets", "Za kopiranje"), ("/wallets?v=svi", "Svi"), ("/wallets?v=aktivnost", "Aktivnost")],
                "/wallets" + (f"?v={v}" if v in ("svi", "aktivnost") else ""))
    # 10.11. (Jure, prijedlog 4.6 i 5.1): "Prijedlog za danas" (prijedlog.box) lives only on Pregled; Novčanici
    # start with their own answer (hero) and list
    now = time.time()
    if v == "aktivnost":
        try:
            act = _activity_rows(n=40, hours=48, now=now)
        except Exception as e:  # noqa: BLE001 - a broken block must not take the page down
            act = rd.hint(f"Aktivnost se trenutno ne može prikazati ({type(e).__name__}).")
        body = (rd.top("Novčanici", "Kupnje i prodaje praćenih novčanika, zadnjih 48 h") + sw
                + rd.colhead("Token · tko", "SOL · kada") + act
                + rd.hint("Kupnje i prodaje influencera s njihovih novčanika su i na Influencerima."))
        return "Novčanici", W_CSS + f'<div class="ms-page ms-wide">{body}</div>'
    show_all = v == "svi"
    min_score = float(qs.get("min_score", explain.COPY_MIN_SCORE))
    min_closed = int(qs.get("min_closed", explain.COPY_MIN_CLOSED))
    ws = data.wallets(scored_only=not show_all)
    marks = autopilot_marks()   # 9.11. (audit P44): the bot's own lists next to the page's copy_score
    scored = [w for w in ws if w.get("stats")]
    sub = (f"{rd.num(len(scored))} {_pl(len(scored), 'ocijenjen', 'ocijenjena', 'ocijenjenih')} · "
           f"{rd.num(len(marks['proven']))} {_pl(len(marks['proven']), 'dokazan', 'dokazana', 'dokazanih')} dvaput")
    try:
        hero = _wallet_hero(scored, marks, now) or ""
    except Exception:  # noqa: BLE001 - the answer is a nicety; the list below still works
        hero = ""
    srt = qs.get("s") if qs.get("s") in {k for k, _, _ in SORTS} else ("copy" if show_all else "dokaz")
    ws = _sort_ws(ws, srt, marks)
    if not show_all:
        ws = [w for w in ws if explain.shortlist(w, min_score, min_closed)[0]]
    head = rd.raw('<div class="ms-wth grid">' + _sort_menu(v, srt)
                  + "".join(f'<span class="d">{t}</span>' for t in ("Copy", "Zarada", "U plusu", "Drži", "Dokazan",
                                                                     "Autopilot", "Zadnji trade"))
                  + '<span class="p">zarada · u plusu</span><span class="d"></span></div>')
    rows = "".join(_wrow(w, marks, now, show_bad=show_all) for w in ws)
    if not rows:
        rows = ('<div class="ms-empty"><b>Trenutno nema koga kopirati</b><p>Nijedan novčanik ne prolazi uvjete kopiranja '
                f"(copy ocjena {min_score:g}+, {min_closed}+ zatvorenih, bez loših oznaka). Ocjene se računaju noću iz "
                'spremljenih tradeova.</p><a href="/wallets?v=svi">Pogledaj sve</a></div>' if not show_all else
                '<div class="ms-empty"><b>Još nema novčanika</b><p>Bot ih skuplja i ocjenjuje sam, noću.</p></div>')
    fld = ('<label class="ms-fld"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/>'
           '<path d="M20 20l-4.2-4.2"/></svg><input type="search" data-wf placeholder="Adresa ili oznaka" '
           'aria-label="Traži novčanik po adresi ili oznaci" autocomplete="off" enterkeyhint="search"></label>')
    body = (rd.top("Novčanici", sub) + hero + sw + fld + head + f'<div class="ms-wl">{rows}</div>'
            + _wallets_foot(scored, marks, now) + _wallets_hint())
    return "Novčanici", W_CSS + f'<div class="ms-page ms-wide">{body}</div>' + _W_JS


def _wallets_table(qs):
    """/wallets?v=tablica: every scored and unscored wallet with all columns (the table /wallets?v=svi showed until
    10.11.), one tap away from the rows; column chooser and phone cards as before."""
    ws = data.wallets(scored_only=False)
    marks = autopilot_marks()
    min_score = float(qs.get("min_score", explain.COPY_MIN_SCORE))
    min_closed = int(qs.get("min_closed", explain.COPY_MIN_CLOSED))
    rows = []
    for w in ws:
        s = w["stats"]
        ok, why = explain.shortlist(w, min_score, min_closed)
        rows.append([wlink(w["wallet"]), tierb(w["tier"]), *_mark_cells(w["wallet"], marks),
                     badge("DA", "good") if ok else badge("ne"),
                     scorecell(w["copy_score"]), scorecell(w["score"]),
                     signed(s.get("closed_pnl_sol")), signed(s.get("roi_on_cost"), "{:+.0%}"),
                     num(s.get("win_rate"), "{:.0%}"), num(s.get("closed")), num(s.get("big_wins")),
                     mins(s.get("median_hold_min")), num(s.get("median_buy_sol"), "{:.2f}"),
                     num(s.get("trades_per_day"), "{:.1f}"), num(s.get("last_trade_days"), "{:.0f}"),
                     num(s.get("early_in_winners")),
                     esc(", ".join(f"{SOURCE.get(k, k)}" for k in w["sources"])),
                     " ".join(badge(labels.wallet_label(l), "bad") for l in w["labels"]),
                     (esc("; ".join(why + (s.get("copy_notes") or []))) or "–", "", "wrap")])
    head = ["Wallet", "Tier", *MARK_HEAD, "Na listi", ("Copy", "n"), ("Ocjena", "n"), ("PnL SOL", "n"), ("ROI", "n"),
            ("Win", "n"), ("Zatv.", "n"), ("2x+", "n"), ("Medijan držanja", "n"), ("Kupnja SOL", "n"), ("Trejd/dan", "n"),
            ("Neaktivan d", "n"), ("Rano u pobj.", "n"), "Izvor", "Oznake", ("Zašto nije na listi / napomene", "wrap")]
    form = f'<div class=flt>{filt("wt", "Filtriraj adresu, oznaku…")}</div>'
    n_pf = sum(1 for w in ws if w["wallet"] in marks["proven"] or w["wallet"] in marks["followed"])
    legend = ('<p class=mut style="font-size:13px"><b>Dokazani dvaput</b> = prošao wallets/dokazani (prije i poslije reza'
              + (f"; lista iz {ago(marks['as_of'])[0]}" if marks["as_of"] else "; lista još nije izračunata") + "), "
              "<b>Prati Autopilot</b> = račun pravog novca ga prati ili je dokazan (to su novčanici čije kupnje bot broji kao "
              "poziv), <b>Autopilot 14 d</b> = ROI/win/zatvoreno na njegovim kupnjama u 14 dana (Autopilot preporuke). "
              f"Copy ocjena je zasebno bodovanje ove stranice; u ovom pogledu {n_pf} novčanika ima oznaku bota.</p>")
    return "Novčanici", (W_CSS + '<a class="ms-back" href="/wallets?v=svi">Novčanici</a>'
                         + rd.top("Sve brojke novčanika") + form + legend
                         + table(head, rows, "wt", "Još nema novčanika. Bot ih skuplja i ocjenjuje sam, noću."))


POS_STATUS = {"closed": "zatvoreno", "open": "otvoreno", "moved": "prebačeno na drugi wallet",
              "no_cost": "bez kupnje (dobio ga je)"}
# stats that are shares (0.38 -> 38%) and ones that are signed SOL amounts
_SHARE = {"win_rate", "roi_on_cost", "median_roi", "top_trade_share", "free_token_ratio", "bag_share"}
_SOL = {"realized_sol", "unrealized_sol", "closed_pnl_sol", "pnl_sol", "scored_pnl_sol", "bag_sol"}
STAT_LABEL = {"positions": "pozicija", "closed": "zatvorenih", "open": "otvorenih", "win_rate": "u plusu (udio zatvorenih)",
              "realized_sol": "ostvareno", "unrealized_sol": "neostvareno (otvorene)",
              "closed_pnl_sol": "zarada na zatvorenima", "roi_on_cost": "povrat na uloženo", "profit_factor": "profit factor",
              "big_wins": "tradeova 2× i više", "rugged_in": "zatvoreno s −90 % ili gore (rug)", "median_roi": "medijan povrata",
              "top_trade_share": "udio najvećeg tradea u zaradi", "median_hold_min": "medijan držanja",
              "median_buy_sol": "medijan kupnje", "trades_per_day": "tradeova dnevno",
              "free_token_ratio": "udio tokena dobivenih besplatno", "last_trade_days": "dana od zadnjeg tradea",
              "history_days": "dana povijesti", "early_in_winners": "rano u pobjednicima", "credits": "Helius kredita",
              "score": "ocjena profitabilnosti", "copy_score": "copy ocjena", "bot": "izgleda kao bot",
              "style": "stil trgovanja", "pnl_sol": "zarada ukupno (s otvorenima)", "scored_pnl_sol": "zarada za ocjenu",
              "bags": "stari gubitnici (otvoreni)", "bag_share": "udio starih gubitnika u knjizi",
              "bag_sol": "stari gubitnici, uloženo"}
STYLE = {"swing": "swing (drži satima)", "scalper": "scalper (brzi ulaz i izlaz)", "bot": "bot", "sniper": "snajper",
         "holder": "holder"}


def _statfmt(k, v):
    """Jedna brojka iz wallets.stats u hrvatskom zapisu (pravilo 8)."""
    if v is True or v is False:
        return "da" if v else "ne"
    if k == "style":
        return STYLE.get(v, str(v))
    if not isinstance(v, (int, float)):
        return str(v)
    if k in _SHARE:
        return rd.pct(v, sign=k in ("roi_on_cost", "median_roi"), frac=True)
    if k in _SOL:
        return rd.sol(v, 2, sign=True)
    if k == "median_hold_min":
        return _hold(v, full=True)
    if k == "median_buy_sol":
        return rd.sol(v, 2)
    if k == "profit_factor":
        return rd.num(v, 2)
    return rd.num(v, 0 if float(v).is_integer() or abs(v) >= 100 else 1)


def _smart(addr):
    """The hype scanner's smart-wallet row for one wallet (primary key read; it used to read the whole table)."""
    try:
        rows = data.multi("hype", "SELECT * FROM smart_wallets WHERE wallet=?", (addr,), key=lambda r: r["wallet"])
    except Exception:  # noqa: BLE001
        return None
    return rows[0] if rows else None


def _verdict(w, row, now=None):
    """(word, kind of dot, facts, sentence) for the wallet page: the Autopilot's own judgement (wallets/dokazani:
    passed in the latest run, copyable), said with its numbers. Judges nothing itself."""
    from wallets import dokazani
    s, labs = w.get("stats") or {}, w.get("labels") or []
    cs = f"copy ocjena{rd.NBSP}{rd.num(w.get('copy_score'))}" if w.get("copy_score") is not None else ""
    if not s:
        return "Još nije ocijenjen", "", cs, "Bot ga ocjenjuje u sljedećem krugu (noću), iz njegovih tradeova na lancu."
    miss_c = dokazani.not_copyable(s, labs)
    cut = walletchart.day(row["cut"]) if row else ""
    proven = bool(row and row.get("passed"))
    facts = rd.cat("dokazan dvaput" if proven else "nije dokazan dvaput", " · ",
                   "kopirljiv" if not miss_c else "nije kopirljiv", (" · " + cs) if cs else "")
    hold = _hold(s.get("median_hold_min"))
    if proven:
        nb, na = row.get("closed_before") or 0, row.get("closed_after") or 0
        return ("Vrijedi kopirati", "good", facts,
                f"U plusu i prije i poslije reza {cut}: {rd.sol(row.get('realized_before'), 1, sign=True)} na {rd.num(nb)} "
                f"{_pl(nb, 'zatvorenoj', 'zatvorene', 'zatvorenih')}, pa {rd.sol(row.get('realized_after'), 1, sign=True)} "
                f"na {rd.num(na)}. Drži oko {hold}, pa ga bot stigne pratiti.")
    if miss_c:
        say = []
        for k, have, need in miss_c:
            if k == "hold":
                say.append(f"Drži medijan {_hold(have, full=True)}, a bot ga stigne pratiti tek od {need} min.")
            elif k == "tpd":
                say.append(f"Trguje {rd.num(have)} puta dnevno, a granica je {need}.")
            elif k == "bags":
                say.append(f"{rd.pct(have, sign=False, frac=True)} knjige su stari gubitnici koje ne prodaje "
                           f"(granica {rd.pct(need, sign=False, frac=True)}).")
            elif k == "labels":
                say.append("Oznaka: " + ", ".join(labels.wallet_label(b) for b in have) + ".")
        return "Ne kopirati", "bad", facts, " ".join(say)
    if not row:
        return ("Još nije dokazan", "", facts,
                "U zadnjem računanju nije imao zatvorenih tradeova i prije i poslije reza od "
                f"{dokazani.RULE['cut_days']} dana, pa još nema drugog dokaza.")
    nb, na = row.get("closed_before") or 0, row.get("closed_after") or 0
    say = (f"Prije reza {cut}: {rd.sol(row.get('realized_before'), 1, sign=True)} na {rd.num(nb)} "
           f"{_pl(nb, 'zatvorenoj', 'zatvorene', 'zatvorenih')}, {rd.pct(row.get('win_before'), sign=False, frac=True)} u plusu; "
           f"poslije {rd.sol(row.get('realized_after'), 1, sign=True)} na {rd.num(na)}.")
    m = (dokazani.misses(row) or [(None, None, None)])[0]
    say += " " + {"closed_before": f"Za dokaz treba barem {m[2]} zatvorenih prije reza.",
                  "realized_before": "Prije reza nije bio u plusu.",
                  "win_before": f"Prije reza treba barem {rd.pct(m[2], sign=False, frac=True)} u plusu.",
                  "closed_after": f"Poslije reza treba barem {m[2]} zatvorene, da se vidi ponavlja li se.",
                  "realized_after": "Poslije reza nije u plusu, pa se prvi rezultat nije ponovio."}.get(
        m[0], "U zadnjem računanju nije prošao uvjete.")
    return "Još nije dokazan", "warn", facts, say


def _sec(title, link_text=None, href=None):
    """rd.section without the section chips (ui/secnav builds them from 3+ <h2>): the wallet page is short and calm,
    like the mock; the chips would add a second row of buttons under the bar (10.11.)."""
    return rd.raw(rd.section(title, link_text, href).replace('class="ms-h2"', 'class="ms-h2 nosec"', 1))


def _wallet_head(addr, back_href="/wallets", back="Novčanici", title=None):
    q = quote(addr)
    return rd.raw(f'<a class="ms-back" href="{rd.h(back_href)}">{rd.h(back)}</a><div class="ms-dh">'
                  f'<h1 class="ms-h1">{rd.h(title or short(addr))}</h1>'
                  f'<div class="ms-s">{rd.h(short(addr, 8))}<span class="ms-cp" role="button" tabindex="0" '
                  f'data-m="{rd.h(addr)}" title="Kopiraj adresu" aria-label="Kopiraj adresu"></span> · '
                  f'<a href="https://solscan.io/account/{q}" target=_blank rel=noopener>Solscan</a> · '
                  f'<a href="https://gmgn.ai/sol/address/{q}" target=_blank rel=noopener>GMGN</a></div></div>')


def _closed_sorted(pos):
    return sorted((p for p in pos.values() if p["status"] == "closed" and p.get("last_ts") and p.get("realized") is not None),
                  key=lambda p: p["last_ts"])


def _pos_row(p, syms, priced, now=None):
    """Jedan redak pozicije: token, "06:07 · 0,52 SOL · 34 min" (zatvorena) ili "kupio prije 10 h · 0,56 SOL"
    (otvorena), desno ostvareno u SOL-u i povrat (otvorena: "otvoreno" i povrat po živoj cijeni ako je ima)."""
    roi_known = p["status"] != "open" or p["mint"] in priced
    if p["status"] == "open":
        return {"name": _tok(p["mint"], syms),
                "reason": f"kupio {rd.ago(p.get('first_buy'), now)} · {rd.sol(p.get('cost'), 2)}",
                "value": "otvoreno", "sub": rd.pct(p.get("roi"), sign=True, frac=True) if roi_known else None,
                "sub_tone": rd.tone(p.get("roi")) if roi_known else None, "href": f"/token/{quote(p['mint'])}"}
    t = p.get("last_sell") or p.get("last_ts")
    when = walletchart.clock(t) if walletchart.day(t) == walletchart.day(now or time.time()) else walletchart.day(t, True)
    return {"name": _tok(p["mint"], syms),
            "reason": f"{when} · {rd.sol(p.get('cost'), 2)} · {_hold(p.get('hold_min'))}",
            "value": rd.sol(p.get("realized"), 2, sign=True), "value_tone": rd.tone(p.get("realized")),
            "sub": rd.pct(p.get("roi"), sign=True, frac=True), "sub_tone": rd.tone(p.get("roi")),
            "href": f"/token/{quote(p['mint'])}"}


def _recent(pos):
    """Open positions first, then the newest closed (the mock: "Zadnji tradeovi", otvorena prva)."""
    return sorted(pos.values(), key=lambda p: (p["status"] != "open", -(p.get("last_ts") or 0)))


WALLET_VIEWS = {"ocjena", "brojke", "povijest", "registar", "pozicije"}


def wallet(addr, qs):
    w = data.wallet(addr)
    sm = _smart(addr)
    if not w and not sm:
        body = (_wallet_head(addr) + rd.hint("Ovog novčanika nema u registru: bot ga nije vidio ni u jednoj analizi. "
                                             "Na lancu ga možeš pogledati preko Solscana ili GMGN-a gore."))
        return "Novčanik", W_CSS + f'<div class="ms-page">{body}</div>' + _W_JS
    w = w or {"wallet": addr, "stats": {}, "labels": [], "sources": {}, "tier": None, "score": None,
              "copy_score": None}
    v = qs.get("v") or ""
    if v in WALLET_VIEWS:
        title, body = _wallet_sub(v, addr, w, sm)
        return f"{title} · {short(addr)}", W_CSS + f'<div class="ms-page">{body}</div>' + _W_JS
    from wallets import dokazani
    now = time.time()
    s = w["stats"]
    row = dokazani.for_wallet(addr)
    word, kind, facts, sentence = _verdict(w, row, now)
    left = [rd.verdict(word, sentence, label="Presuda", facts=facts, kind=kind)]
    if s:
        n, wins = s.get("closed") or 0, round((s.get("win_rate") or 0) * (s.get("closed") or 0))
        days = round(s.get("history_days") or 0)
        key = [{"name": "Zarada na zatvorenima",
                "reason": f"{rd.num(n)} {_pl(n, 'pozicija', 'pozicije', 'pozicija')}"
                          + (f" u {rd.num(days)} {_pl(days, 'dan', 'dana', 'dana')}" if days else ""),
                "value": rd.sol(s.get("closed_pnl_sol"), 2, sign=True), "value_tone": rd.tone(s.get("closed_pnl_sol")),
                "sub": (rd.pct(s.get("roi_on_cost"), frac=True) + " na uloženo") if s.get("roi_on_cost") is not None else None},
               {"name": "U plusu", "reason": "zatvorene pozicije", "value": rd.share(wins, n),
                "sub": rd.pct(s.get("win_rate"), sign=False, frac=True) if n else None},
               {"name": "Drži", "reason": "medijan, od kupnje do prodaje", "value": _hold(s.get("median_hold_min"), full=True),
                "sub": f"{rd.num(s.get('trades_per_day'), 1)} tradea dnevno" if s.get("trades_per_day") is not None else None}]
        top = s.get("top_trade_share")
        if top is not None and (s.get("closed_pnl_sol") or 0) > 0:
            key.append({"name": "Najveći trade", "reason": "udio u ukupnoj zaradi", "value": rd.pct(top, sign=False, frac=True),
                        "sub": "nije jedna sretna oklada" if top < 0.5 else "većina zarade iz jednog tradea"})
        if s.get("bags"):
            key.append({"name": "Stari gubitnici", "reason": "otvorene u minusu, kupljene prije 7+ dana",
                        "value": rd.num(s.get("bags")), "sub": rd.pct(s.get("bag_share"), sign=False, frac=True) + " knjige"})
        left.append(rd.rows(key, cls="ms-key"))
    try:
        from ui import pravitrade
        followed = addr in set(pravitrade.followed_wallets())
    except Exception:  # noqa: BLE001
        followed = False
    # 10.11.: the mock's switch "Autopilot ga kopira" is shown as a state: there is no per-wallet control today, and
    # adding one would change what real money does (CLAUDE.md: ask first). Followed = its buys count as a call.
    ap_why = ("njegove kupnje Autopilot broji kao poziv" if followed else
              "nije dokazan dvaput ni ručno praćen")
    left.append(rd.raw('<div class="ms-ap">' + rd.rows([rd.row("Prati ga Autopilot", ap_why,
                                                               rd.cat(rd.dot("good"), "da") if followed else "ne")]) + "</div>"))
    pos, priced = _positions(addr)
    closed = _closed_sorted(pos)
    right = [_sec("Kako je zarađivao")]
    if len(closed) >= 2:
        run_, pts = 0.0, [(closed[0]["last_ts"] - 1, 0.0)]
        for p in closed:
            run_ += p["realized"]
            pts.append((p["last_ts"], run_))
        right.append(walletchart.earnings(pts, cut=row["cut"] if row else None))
        if row:
            def half(lbl, sol_, n_, win_):
                wins_ = round((win_ or 0) * (n_ or 0))
                return (f'<span>{rd.h(lbl)} <b class="{rd.tone(sol_)}">{rd.h(rd.sol(sol_, 2, sign=True))}</b> · '
                        f'{rd.h(rd.num(wins_))}/{rd.h(rd.num(n_))}</span>')
            right.append(rd.raw('<div class="wc-split">'
                                + half("prije reza", row.get("realized_before"), row.get("closed_before"), row.get("win_before"))
                                + half("poslije", row.get("realized_after"), row.get("closed_after"), row.get("win_after"))
                                + "</div>"))
        right.append(_sec("Svaka zatvorena pozicija"))
        right.append(walletchart.strip([p["realized"] > 0 for p in closed], closed[0]["last_ts"], closed[-1]["last_ts"]))
    else:
        right.append(rd.hint("Premalo zatvorenih pozicija za graf: treba barem dvije."))
    out = [_wallet_head(addr), '<div class="ms-g2"><div>', *left, "</div><div>", *right, "</div></div>"]
    recent = _recent(pos)[:5]
    if recent:
        syms = _syms_for([p["mint"] for p in recent])
        out.append(_sec("Zadnji tradeovi", f"Sve {rd.num(len(pos))}", f"/wallet/{quote(addr)}?v=pozicije"))
        out.append(rd.rows([_pos_row(p, syms, priced, now) for p in recent]))
    more = []
    if s:
        sc = w.get("score")
        more.append({"name": f"Kako je dobio ocjenu {rd.num(sc)}" if sc is not None else "Kako se računa ocjena",
                     "reason": "zatvoreni profit, povrat, udio u plusu, profit factor"
                               + (f"; copy ocjena {rd.num(w.get('copy_score'))}" if w.get("copy_score") != sc else ""),
                     "href": f"/wallet/{quote(addr)}?v=ocjena"})
        big = s.get("big_wins") or 0
        more.append({"name": "Sve brojke",
                     "reason": f"profit factor {rd.num(s.get('profit_factor'), 2)} · medijan povrata "
                               f"{rd.pct(s.get('median_roi'), frac=True)} · {rd.num(big)} {_pl(big, 'trade', 'tradea', 'tradeova')} 2× i više",
                     "href": f"/wallet/{quote(addr)}?v=brojke"})
    hist = data.wallet_pnl(addr)
    if hist:
        more.append({"name": "Povijest ocjena", "reason": f"zadnja {_wwhen(hist[-1]['ts'], now)}",
                     "href": f"/wallet/{quote(addr)}?v=povijest"})
    sg = data.sightings(wallet=addr)
    reg = ""
    if sg:
        x = sg[0]
        reg = f"{ROLE.get(x['role'], (x['role'],))[0]}{' na tokenu' if x.get('token') else ''}, " \
              f"{SOURCE.get(x['source'], x['source'])}, {walletchart.day(x['ts'])}"
    elif sm:
        reg = "smart wallet iz hype skenera"
    more.append({"name": "Zašto je u registru", "reason": reg or "nema zapisa gdje je viđen",
                 "href": f"/wallet/{quote(addr)}?v=registar"})
    out.append(_sec("Više o njemu"))
    out.append(rd.rows(more))
    r = dokazani.RULE
    out.append(rd.raw('<p class="ms-hint">' + rd.h(
        f"Dokazan dvaput: u plusu na {r['min_closed']}+ zatvorenih prije reza od {r['cut_days']} dana i opet poslije "
        f"njega. Kopirljiv: drži {r['min_hold_min']}+ min, do {r['max_tpd']} tradeova dnevno, nije bot ni sniper. ")
        + '<a href="/pojmovnik">Pojmovnik</a></p>'))
    return f"Novčanik {short(addr)}", (W_CSS + walletchart.CSS + '<div class="ms-page ms-wide">' + "".join(out) + "</div>"
                                       + _W_JS)


def _wallet_sub(v, addr, w, sm):
    """One tap further from the wallet page (prijedlog 4.7, "Više o njemu"): the score breakdowns, every number,
    the score history, why it is in the registry, every position. (title, body)."""
    s = w["stats"]
    q = quote(addr)
    now = time.time()

    def head(title):
        return _wallet_head(addr, f"/wallet/{q}", short(addr), title)

    if v == "ocjena":
        if not s:
            return "Ocjena", head("Ocjena") + rd.hint("Još nije ocijenjen: bot ga ocjenjuje u sljedećem krugu (noću).")
        parts, ev = explain.wallet_score(s)
        items = [{"name": n_, "reason": x_, "value": f"{rd.num(p_, 1)} od {m_}"} for n_, p_, m_, x_ in parts]
        items.append({"name": "Dokaz", "reason": f"{rd.num(s.get('closed') or 0)} zatvorenih; ispod 10 zbroj se smanjuje",
                      "value": f"× {rd.num(ev, 2)}"})
        items.append({"name": "Ocjena", "reason": "zbroj puta dokaz, 0 do 100", "value": rd.num(w.get("score"))})
        mults = explain.copy_multipliers(s, w["labels"])
        m = 1.0
        citems = []
        for reason, f in mults:
            m *= f
            citems.append({"name": reason, "value": f"× {rd.num(f, 1)}", "value_tone": "neg" if f == 0 else None})
        if not mults:
            citems.append({"name": "Bez kazni", "reason": "drži dovoljno dugo, aktivan, normalne veličine kupnji"})
        e = s.get("early_in_winners", 0) or 0
        bonus = 5 * min(3, e - 1) if e > 1 else 0
        if bonus and m:
            citems.append({"name": "Rano u više pobjednika", "reason": f"ušao rano u {rd.num(e)} pobjednika", "value": f"+{bonus}"})
        citems.append({"name": "Copy ocjena", "reason": f"ocjena {rd.num(w.get('score'))} × {rd.num(m, 2)}"
                                                         + (f" + {bonus}" if bonus and m else ""),
                       "value": rd.num(w.get("copy_score"))})
        ok, why = explain.shortlist(w)
        litems = [{"name": "Na copy listi", "reason": "prolazi sve uvjete" if ok else "; ".join(why),
                   "value": rd.cat(rd.dot("good"), "da") if ok else "ne"},
                  {"name": "Razred", "reason": "A najbolji, D najslabiji", "value": w.get("tier") or rd.DASH}]
        if w["labels"]:
            litems.append({"name": "Oznake", "reason": "oznake s popisa loših nikad ne idu na copy listu",
                           "value": ", ".join(labels.wallet_label(x) for x in w["labels"]), "value_tone": "warn"})
        title = f"Kako je dobio ocjenu {rd.num(w.get('score'))}"
        return "Ocjena", (head(title) + rd.rows(items, cls="ms-wrap") + _sec(f"Copy ocjena {rd.num(w.get('copy_score'))}")
                          + rd.rows(citems, cls="ms-wrap") + _sec("Copy lista") + rd.rows(litems, cls="ms-wrap")
                          + rd.hint("Ocjena 0 do 100 dolazi iz zatvorenih pozicija; copy ocjena je ista ocjena s kaznama "
                                    "za stil koji bot teško prati. Presuda na vrhu novčanika je Autopilotova: dokazan "
                                    "dvaput i kopirljiv."))
    if v == "brojke":
        items = [{"name": STAT_LABEL.get(k, k.replace("_", " ")), "value": _statfmt(k, val)}
                 for k, val in s.items() if not isinstance(val, (list, dict))]
        return "Sve brojke", (head("Sve brojke") + rd.rows(items, empty="Još nije ocijenjen.")
                              + rd.hint("Sirove brojke iz zadnjeg ocjenjivanja, iz kojih su izračunate ocjene."))
    if v == "povijest":
        hist = data.wallet_pnl(addr)
        chart = ""
        if len(hist) >= 2:
            from ui import charts
            chart = charts.line([{"name": "Ocjena profitabilnosti", "pts": [(x["ts"], x["score"]) for x in hist if x["score"] is not None]},
                                 {"name": "Copy ocjena", "pts": [(x["ts"], x["copy_score"]) for x in hist if x["copy_score"] is not None]}],
                                "Ocjene kroz vrijeme", "0-100", fmt="num", ymin=0, ymax=100)
        items = [{"name": _wwhen(x["ts"], now),
                  "reason": f"{rd.sol(x['realized_sol'], 2, sign=True)} ostvareno · {rd.num(x['closed'])} zatvorenih · "
                            f"{rd.pct(x['win_rate'], sign=False, frac=True)} u plusu",
                  "value": rd.num(x["score"]), "sub": f"copy {rd.num(x['copy_score'])}"} for x in reversed(hist)]
        return "Povijest ocjena", (head("Povijest ocjena") + chart + rd.colhead("Ocjenjivanje", "ocjena · copy")
                                   + rd.rows(items, empty="Još nije ocijenjen.")
                                   + rd.hint("Svako ocjenjivanje ovog novčanika: vidi se popravlja li se ili kvari."))
    if v == "registar":
        sg = data.sightings(wallet=addr)
        syms = _syms_for([x["token"] for x in sg if x.get("token")])
        items = []
        for x in sg:
            role, desc = ROLE.get(x["role"], (x["role"], ""))
            e = x["extra"] or {}
            det = []
            if e.get("secs_after_first") is not None:
                det.append(f"{e['secs_after_first']} s nakon prve kupnje")
            if x.get("sol_in"):
                det.append(f"uložio {rd.sol(x['sol_in'], 2)}")
            if e.get("mcap_now"):
                det.append(f"token danas {rd.usd(e['mcap_now'])}")
            if e.get("verdict"):
                det.append(f"rug presuda: {e['verdict']}")
            if e.get("funded"):
                det.append(f"financirao {short(e['funded'])}")
            if e.get("funder"):
                det.append(f"financiran iz {short(e['funder'])}")
            k = "bad" if x["role"] in ("dev", "bundler", "sniper", "funder") else "good" if x["role"] in (
                "early_buyer", "smart", "top_trader", "manual") else ""
            items.append({"name": rd.cat(rd.dot(k), role, (" na " + _tok(x["token"], syms)) if x.get("token") else ""),
                          "reason": "; ".join([desc] + det) if desc or det else None,
                          "value": walletchart.day(x["ts"]), "sub": SOURCE.get(x["source"], x["source"]),
                          "href": f"/token/{quote(x['token'])}" if x.get("token") else None})
        extra = []
        if sm:
            found = [m_ for m_ in (sm.get("found_via") or "").split(",") if m_]
            fs = _syms_for(found)
            extra.append({"name": "Smart wallet iz hype skenera",
                          "reason": "pronađen preko: " + (", ".join(_tok(m_, fs) for m_ in found) or rd.DASH),
                          "value": rd.num(sm.get("score")), "sub": "ocjena"})
        if s.get("early_in_winners"):
            e = s["early_in_winners"]
            extra.append({"name": "Rano u pobjednicima", "reason": "kupio među prvima tokene koji su kasnije narasli",
                          "value": rd.num(e)})
        if w["labels"]:
            extra.append({"name": "Oznake", "reason": "oznake s popisa loših nikad ne idu na copy listu",
                          "value": ", ".join(labels.wallet_label(x) for x in w["labels"]), "value_tone": "warn"})
        return "Zašto je u registru", (head("Zašto je u registru")
                                       + rd.rows(items, empty="Nema zapisa gdje je viđen.", cls="ms-wrap")
                                       + rd.rows(extra, cls="ms-wrap"))
    # pozicije
    pos, priced = _positions(addr)
    items = _recent(pos)
    syms = _syms_for([p["mint"] for p in items])
    op = [p for p in items if p["status"] == "open"]
    unr = [p["unrealized"] for p in op if p.get("unrealized") is not None]
    sub = (f"{rd.num(len(items))} {_pl(len(items), 'pozicija', 'pozicije', 'pozicija')}, od toga {rd.num(len(op))} "
           f"{_pl(len(op), 'otvorena', 'otvorene', 'otvorenih')}"
           + (f", neostvareno {rd.sol(sum(unr), 2, sign=True)}" if unr else ""))
    return "Pozicije", (head("Sve pozicije") + rd.raw(f'<p class="ms-sub">{rd.h(sub)}</p>')
                        + rd.rows([_pos_row(p, syms, priced, now) for p in items], empty="Nema spremljenih tradeova.")
                        + rd.hint("Iz spremljenih tradeova. Otvorene se vrednuju živom cijenom s DexScreenera (najviše "
                                  "1 min stara); povrat uključuje i već prodano. Token bez para na DexScreeneru ostaje "
                                  "bez cijene."))


def _positions(addr):
    """({mint: position}, {mint: live SOL price}) with open positions valued at the DexScreener price."""
    rows = data.wallet_trades(addr)
    if not rows:
        return {}, {}
    try:
        from wallets import pnl
        pos = pnl.positions(rows)
        prices = {}
        open_ = [m for m, p in pos.items() if p.get("status") == "open"]
        if open_:
            try:
                from wallets import prices as wprices
                prices = wprices.sol_prices(open_)
            except Exception:
                prices = {}
            if prices:
                pos = pnl.positions(rows, prices)
        return {m: p for m, p in pos.items() if p.get("status") in ("open", "closed")}, prices
    except Exception:
        return {}, {}


# ---------------- tokens ----------------

def tier_html(mint):
    """Where the token stands in the tiered analysis: class, tier reached, T0 verdict, shape of its mcap path."""
    from ui.html import klasab, razinab
    t = data.token_tier(mint)   # 10.11. (audit S2): one row by key, not the whole table
    if not t:
        return ""
    t0 = {"prolaz": badge("T0 prošao", "good"), "pad": badge("T0 pao", "bad"), "nije": badge("izvan skena")}.get(t.get("t0"), "")
    put = ""
    if t.get("put_skokovitost") is not None:
        put = (f" · put do mcapa: brzina {t['put_brzina']:+.2f}/h, skokovitost {t['put_skokovitost']:.0%}, "
               f"zadržavanje {t['put_zadrzavanje']:.0%}")
    return (f"<p>Slojevita analiza: {razinab(t.get('razina'))} {klasab(t.get('klasa'))} {t0} "
            f"<span class=mut>{esc(t.get('t0_razlog') or '')}{esc(put)} · potrošeno ~{t.get('credits') or 0} Helius kredita</span></p>")


# 10.11. (Jure: "Ostalo mi se sviđa", prijedlog 4.3, maketa token.html): the token page as a detail page in the calm
# language. Top like Apple Dionice (name and short address left, mcap and 24 h right), the mcap chart with the calls as
# dots (ui/tokenchart), one verdict panel (pouzdanost, the same number as on the list, šansa next to it; one sentence;
# one "Za / Protiv" line), Kupi as a sheet and Kopiraj adresu, the outside sites as words, then Tržište, Tko ga je
# zvao, Smart walleti, Provjera ruga, and "Kako je dobio ocjenu" (full reading, the seven layers, live pulse) one tap
# away. Every number of the old page is still here; nothing is computed differently.

TOKEN_CSS = """<style>
.tkp-back{display:inline-flex;align-items:center;gap:7px;color:var(--acc);font-size:17px;padding:8px 0 0;text-decoration:none}
.tkp-back::before{content:"";width:9px;height:9px;border-left:2px solid var(--acc);border-bottom:2px solid var(--acc);transform:rotate(45deg);margin-left:3px}
.tkp-dh{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;padding:12px 0 0}
.tkp-dh>div{min-width:0}.tkp-dh .ms-h1{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.tkp-r{text-align:right;flex:none}
.tkp-px{font-size:22px;font-weight:700;letter-spacing:-.02em;white-space:nowrap;font-variant-numeric:tabular-nums}
.tkp-s{font-size:15px;color:var(--mut);margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tkp-cp{all:unset;cursor:pointer;color:var(--mut)}.tkp-cp:hover{color:var(--fg)}
.tkp-ci{display:inline-block;width:11px;height:13px;border:1.6px solid currentColor;border-radius:3px;margin:0 2px -2px 6px;box-shadow:2px -2px 0 -.5px #fff,3px -3px 0 0 currentColor}
.tkp-msg{border:1px solid var(--line);border-radius:14px;padding:10px 14px;margin:12px 0 0;font-size:15px}
.tkp-msg.neg{border-color:var(--bad)}
.tkp-v .ms-name{margin-top:2px}.tkp-v .ms-name+p{margin-top:6px}
.tkp-go{margin:12px 0 0;padding:11px 0 0;border-top:1px solid var(--line2);font-size:15px;color:var(--mut);line-height:1.4}
.tkp-go b{color:var(--fg);font-weight:600}
.tkp-btns{display:flex;gap:10px;margin:16px 0 0}
.tkp-btn{all:unset;box-sizing:border-box;flex:1;display:block;text-align:center;border-radius:12px;padding:13px 0;font-size:17px;font-weight:600;cursor:pointer}
.tkp-btn.p{background:var(--fg);color:#fff}.tkp-btn.s{background:var(--soft);color:var(--fg)}
.tkp-btn.p[aria-disabled=true]{background:var(--line2)}
.tkp-links{font-size:15px;color:var(--mut);margin:12px 0 0;line-height:1.6}.tkp-links a{color:var(--acc);text-decoration:none}
.tkp-chg{display:grid;grid-template-columns:repeat(4,1fr);border:1px solid var(--line);border-radius:14px;margin:12px 0 0;overflow:hidden}
.tkp-chg div{padding:9px 0;text-align:center}.tkp-chg div+div{border-left:1px solid var(--line)}
.tkp-chg span{display:block;font-size:13px;color:var(--mut)}.tkp-chg b{font-size:17px;font-weight:600;font-variant-numeric:tabular-nums}
.tkp-kv{display:grid;grid-template-columns:1fr 1fr;column-gap:24px;margin:4px 0 0}
.tkp-kv div{padding:11px 0;border-bottom:1px solid var(--line);min-width:0}
.tkp-kv span{display:block;font-size:13px;color:var(--mut)}.tkp-kv b{font-size:17px;font-weight:600;font-variant-numeric:tabular-nums}
.tkp .pos{color:var(--good)}.tkp .neg{color:var(--bad)}
.tkp-h2s{font-size:15px;font-weight:400;letter-spacing:0;color:var(--mut)}
.tkp-state{font-size:15px;color:var(--mut);margin:8px 0 2px}
.tkp-chk{display:flex;justify-content:space-between;align-items:center;gap:12px;min-height:46px;border-bottom:1px solid var(--line);font-size:17px}
.tkp-chk:last-child{border-bottom:0}.tkp-chk span{font-size:15px;color:var(--mut);text-align:right}
.tkp-chk span.warn{color:var(--warn)}.tkp-chk span.bad{color:var(--bad)}
.tkp-d>summary{list-style:none;cursor:pointer}.tkp-d>summary::-webkit-details-marker{display:none}
.tkp-d[open]>summary .ms-chev{transform:rotate(135deg)}
.tkp-d>.tkp-in{padding:4px 0 18px;font-size:15px;line-height:1.5}
.tkp-d:not(:last-child)>summary.ms-row{border-bottom:1px solid var(--line)}
.tkp-list{list-style:none;margin:6px 0;padding:0}.tkp-list li{padding:3px 0}
.tkp-all{margin:6px 0 0}.tkp-all>summary{font-size:15px;color:var(--acc)}
.tkp-g2>section>.ms-h2:first-child{margin-top:40px}
@media(min-width:900px){
 .tkp-g2{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);column-gap:44px;align-items:start}
 .tkp-g2.a .ms-panel{margin-top:16px}
 .tkp-kv{grid-template-columns:1fr 1fr 1fr}
}
</style>"""

TOKEN_JS = """<script>(()=>{const sh=document.getElementById('qb-sheet');
document.addEventListener('click',e=>{const c=e.target.closest('[data-copy]');if(c){e.preventDefault();const m=c.dataset.copy,
 t=c.querySelector('.tkp-cl')||c,o=t.textContent,done=()=>{t.textContent='Kopirano';setTimeout(()=>t.textContent=o,1500)};
 (navigator.clipboard?navigator.clipboard.writeText(m):Promise.reject()).then(done,()=>prompt('Kopiraj adresu:',m));return}
 const b=e.target.closest('[data-buy]');if(b&&sh&&sh.showModal){e.preventDefault();sh.showModal();return}
 if(sh&&(e.target===sh||e.target.closest('#qb-sheet [data-close]')))sh.close();
 const a=e.target.closest('a[href^="#"]');if(a){const d=document.getElementById(a.getAttribute('href').slice(1));if(d&&d.tagName==='DETAILS')d.open=true}});
const d=location.hash&&document.getElementById(location.hash.slice(1));if(d&&d.tagName==='DETAILS')d.open=true})()</script>"""

DEX_NAME = {"raydium": "Raydium", "pumpswap": "PumpSwap", "meteora": "Meteora", "orca": "Orca", "launchlab": "LaunchLab"}
TOKEN_LINKS = (("DexScreener", "dexscreener.com"), ("Birdeye", "birdeye.so"), ("GMGN", "gmgn.ai"), ("Solscan", "solscan.io"),
               ("X", "x.com"))


def _short_addr(a):
    return f"{a[:4]}…{a[-4:]}" if a and len(a) > 10 else (a or "")


def _price_txt(p):
    """0.000412 -> "0,000412 $" (three significant digits), 1.234 -> "1,23 $"."""
    import math
    from ui.redak import NBSP, num
    try:
        p = float(p)
    except (TypeError, ValueError):
        return None
    if p <= 0:
        return None
    dec = 2 if p >= 1 else max(2, -math.floor(math.log10(p)) + 2)
    return f"{num(p, min(dec, 12))}{NBSP}$"


def _age_txt(ms):
    if not ms:
        return None
    d = time.time() - ms / 1000
    return f"{int(d // 3600)} h" if d < 2 * 86400 else f"{int(d // 86400)} d"


def _token_status(mint):
    """The token's hype/tokenstatus row by its key (the page used to read the whole table for one row)."""
    rows = data.q(data.HYPE_DB, "SELECT * FROM token_status WHERE token=?", (mint,))
    return rows[0] if rows else None


def _zone_mcap0(mint, now):
    """mcap at the moment today's suggestion (Pregled) showed this token, or None (prijedlog_log, by key)."""
    rows = data.q(data.HYPE_DB, "SELECT mcap0 FROM prijedlog_log WHERE token=? AND ts>=? ORDER BY ts DESC LIMIT 1",
                  (mint, int(now - 86400)))
    return rows[0]["mcap0"] if rows and rows[0].get("mcap0") else None


def _token_links(mint, url=None, dead=False):
    from ui.html import EXT_SITES
    from urllib.parse import quote as _q
    mk = {dom: f for _, dom, f in EXT_SITES}
    out = []
    for name, dom in TOKEN_LINKS:
        href = url if (dom == "dexscreener.com" and url and not dead) else (
            f"https://dexscreener.com/search?q={_q(mint)}" if dom == "dexscreener.com" and dead else mk[dom](_q(mint)))
        out.append(f'<a href="{esc(href)}" target=_blank rel=noopener>{esc(name)}</a>')
    return " · ".join(out)


def _market_html(pair, st, top, rug, det, pl, url):
    """Tržište (like DexScreener): 5 min, 1 h, 6 h, 24 h in one strip, then price, liquidity, volume, buys / sells,
    holders, top 10, age and where it trades. Live pair first (DexScreener, 60 s cache), then what the bases know."""
    from ui import redak as R
    b = [R.section("Tržište", "DexScreener" if url else None, url)]
    ch = (pair or {}).get("priceChange") or {}
    if pair and any(ch.get(k) is not None for k in ("m5", "h1", "h6", "h24")):
        b.append('<div class="tkp-chg">' + "".join(
            f'<div><span>{lab}</span><b class="{R.tone(ch.get(k))}">{esc(R.pct(ch.get(k)))}</b></div>'
            for k, lab in (("m5", "5 min"), ("h1", "1 h"), ("h6", "6 h"), ("h24", "24 h"))) + "</div>")
    last = pl[-1] if pl else {}
    tx = ((pair or {}).get("txns") or {}).get("h1") or {}
    rc = (top or {}).get("rc") or {}
    pf = (det or {}).get("pumpfun") or {}
    holders = rc.get("holders") or next((x["holders"] for x in reversed(pl or []) if x.get("holders")), None) or pf.get("holders")
    t10 = rc.get("top10")
    if t10 is None:
        t10 = (rug or {}).get("top10_pct")
    if t10 is None and pf.get("top10HoldersPercent") is not None:
        v = pf["top10HoldersPercent"]
        t10 = v / 100 if v > 100 else v
    dex = (pair or {}).get("dexId") or (st or {}).get("dex_id")
    kv = [("Cijena", _price_txt((pair or {}).get("priceUsd") or (st or {}).get("price"))),
          ("Likvidnost", R.usd(((pair or {}).get("liquidity") or {}).get("usd") or (st or {}).get("liq") or None)),
          ("Volumen 1 h", R.usd(((pair or {}).get("volume") or {}).get("h1") or last.get("vol_h1") or None)),
          ("Kupnje / prodaje 1 h", f'{R.num(tx.get("buys"))} / {R.num(tx.get("sells"))}' if tx else
           (f'{R.num(last.get("buys_h1"))} / {R.num(last.get("sells_h1"))}' if last.get("buys_h1") is not None else None)),
          ("Holderi", R.num(holders) if holders else None),
          ("Top 10 holdera", R.pct(t10, sign=False) if t10 is not None else None),
          ("Starost", _age_txt((pair or {}).get("pairCreatedAt"))),
          ("Bondan", None if not dex else ("ne, još na krivulji" if dex == "pumpfun" else f"da, {DEX_NAME.get(dex, dex)}"))]
    kv = [(k, v) for k, v in kv if v and v != R.DASH and v != "– / –"]
    if kv:
        b.append('<div class="tkp-kv">' + "".join(f"<div><span>{esc(k)}</span><b>{esc(v)}</b></div>" for k, v in kv) + "</div>")
    if st and not st.get("has_pair"):
        b.append(R.hint("DexScreener više nema par za ovaj token (nema trgovanja)."
                        + (f" GeckoTerminal: vrijednost {R.usd(st['gt_fdv'])}, promet 24 h {R.usd(st.get('gt_vol24') or 0)}."
                           if st.get("gt_fdv") else "")))
    elif not kv:
        b.append(R.hint("Tržišni podaci za ovaj token trenutno nisu dostupni."))
    s = (top or {}).get("state") or {}
    if s.get("advice"):
        lab = (s.get("label") or "").split(" ", 1)[-1] if s.get("label") else ""
        b.append(R.hint(f"{lab}: {s['advice']}" if lab else s["advice"]))
    return "".join(b)


def _callers_html(mint, mcap_now, now):
    """Tko ga je zvao: the four newest first calls with the one influencer verdict (ui/kolsummary), the mcap at the
    call and the rise since; "Svih N" opens the full table of posts and KOL wallet trades (ui/kol.token_section)."""
    import json
    from ui import redak as R
    from ui import tokenchart
    cs = tokenchart.calls(mint)
    try:
        from ui import kol as _kol
        full = _kol.token_section(mint)
    except Exception:  # noqa: BLE001
        full = ""
    head = R.section("Tko ga je zvao", f"Svih {len(cs)}" if len(cs) > 4 or (full and cs) else None, "#pozivi")
    if not cs:
        return head + R.hint("Nitko od praćenih računa ga nije objavio.") + (
            f'<details class="tkp-all" id="pozivi"><summary>Kupnje KOL novčanika</summary>{full}</details>' if full else "")
    show = sorted(cs, key=lambda c: -c[0])[:4]
    first = cs[0][0]
    rug = {}
    try:
        from kol import store
        hs = [c[1] for c in show]
        for r in data.q(store.DB, f"SELECT handle, stats FROM kols WHERE handle IN ({','.join('?' * len(hs))})", hs):
            rug[r["handle"]] = (json.loads(r["stats"] or "{}") or {}).get("rug_rate")
    except Exception:  # noqa: BLE001
        pass
    from ui import kolsummary
    items = []
    for ts_, hnd, m0 in show:
        v = kolsummary.kol_verdict(hnd)
        rr = rug.get(hnd)
        when = ("prvi, " if ts_ == first else "") + R.ago(ts_, now)
        if rr is not None and rr >= 0.3:
            reason = R.cat(R.raw(f'<span class="ms-warn">{esc(R.pct(rr, sign=False, frac=True))} rugova</span>'), " · ", when)
        else:
            reason = R.cat(R.dot(v["dot"]) if v.get("dot") else "", v["word"], " · ", when)
        growth = (mcap_now / m0 - 1) * 100 if (mcap_now and m0) else None
        name = (hnd[3:] + " (TG)") if hnd.startswith("tg:") else "@" + hnd
        items.append(R.row(name, reason=reason, value=R.usd(m0) if m0 else R.DASH,
                           sub=R.pct(growth) if growth is not None else None, sub_tone=R.tone(growth), href=f"/kol/{hnd}"))
    return (head + R.rows(items) + R.hint("Desno: mcap kod poziva i koliko je od tada narastao.")
            + (f'<details class="tkp-all" id="pozivi"><summary>Svi pozivi i kupnje KOL novčanika</summary>{full}</details>'
               if full else ""))


def _smart_html(mint, det, now):
    """Smart walleti: who of the registry bought it (good roles only), how much, and whether it still holds."""
    from ui import redak as R
    sg = [x for x in data.sightings(token=mint) if x.get("role") in ("early_buyer", "smart", "top_trader", "holder", "manual")]
    seen, rows = set(), []
    for x in sg:
        if x["wallet"] not in seen:
            seen.add(x["wallet"])
            rows.append(x)
    n_sm = len((det or {}).get("smart_buyers") or [])
    sub = f"{n_sm} među prvima" if n_sm else (f"{len(rows)} iz registra" if rows else "")
    head = f'<h2 class="ms-h2"><span>Smart walleti</span><span class="tkp-h2s">{esc(sub)}</span></h2>'
    if not rows:
        return head + R.hint("Nijedan wallet iz registra nije zabilježen na ovom tokenu.")
    rows = sorted(rows, key=lambda x: -(x.get("sol_in") or 0))[:5]
    ws = [x["wallet"] for x in rows]
    proven = set()
    try:
        from wallets import dokazani
        proven = {r["wallet"] for r in dokazani.latest()}
    except Exception:  # noqa: BLE001
        pass
    reg = {r["wallet"]: r for r in data.q(data.WALLET_DB, f"SELECT wallet, copy_score FROM wallets WHERE wallet IN "
                                                          f"({','.join('?' * len(ws))})", ws)}
    items = []
    for x in rows:
        w = x["wallet"]
        tr = data.q(data.WALLET_DB, "SELECT tokens, kind FROM wallet_trades WHERE wallet=? AND mint=?", (w, mint))
        bought = sum(t["tokens"] or 0 for t in tr if t["kind"] == "buy")
        sold = sum(t["tokens"] or 0 for t in tr if t["kind"] == "sell")
        if bought and sold:
            f = min(1.0, sold / bought)
            hold = "prodao sve" if f >= 0.95 else "prodao pola" if 0.4 <= f <= 0.6 else f"prodao {R.pct(f, sign=False, frac=True)}"
        elif bought:
            hold = "još drži"
        else:
            hold = None
        cs_ = (reg.get(w) or {}).get("copy_score")
        if w in proven:
            what = R.cat(R.dot("good"), "dokazan dvaput")
        elif cs_:
            what = f"copy ocjena {R.num(cs_)}"
        else:
            what = ROLE.get(x["role"], (x["role"],))[0]
        items.append(R.row(_short_addr(w), reason=R.cat(what, " · ", R.ago(x.get("ts"), now)),
                           value=R.sol(x.get("sol_in"), 2) if x.get("sol_in") else None, sub=hold, href=f"/wallet/{w}"))
    return head + R.rows(items)


def _rug_html(top, rug, now):
    """Provjera ruga: the fresh check of a recommended token (topcheck) or else the newest rug filter report."""
    from ui import redak as R, topcheckui
    state, rows = topcheckui.check_state(top), topcheckui.check_rows(top)
    if not rows:
        state, rows = topcheckui.rug_state(rug), topcheckui.rug_rows(rug)
    when = R.ago(state[2], now) if state and state[2] else ""
    head = f'<h2 class="ms-h2"><span>Provjera ruga</span><span class="tkp-h2s">{esc(when)}</span></h2>'
    if not state:
        return head + R.hint("Još nije provjeren: puna provjera ide tokenima koji prođu prve razine analize.")
    return (head + f'<div class="tkp-state">{R.dot(state[0], state[1])}</div>'
            + "".join(f'<div class="tkp-chk">{esc(k)}<span class="{kind or ""}">{esc(v)}</span></div>' for k, v, kind in rows))


def _sum_row(title, sub=None, value=None):
    """A row that opens what is under it (<summary> in the ms-row look)."""
    return (f'<summary class="ms-row"><div class="ms-m"><div class="ms-t">{esc(title)}</div>'
            + (f'<div class="ms-s">{esc(sub)}</div>' if sub else "") + "</div>"
            + (f'<div class="ms-e"><div class="ms-v mut" style="font-weight:400">{esc(value)}</div></div>' if value else "")
            + '<span class="ms-chev" aria-hidden="true"></span></summary>')


def token(mint, qs):
    from ui import redak as R
    now = time.time()
    ev = data.event_tokens(mint)
    sigs = data.hype_signals("token=?", (mint,), "ts DESC")
    rugs = data.rug_reports(mint)
    from ui import evidence, quickbuy, tokenchart
    from ui.tokens import SHEET_CSS
    dsym, dlist = quickbuy.dugo_info(mint)
    try:   # 7.11.: the exact pair page, or "no pair any more" (hype/tokenstatus)
        st = _token_status(mint)
    except Exception:  # noqa: BLE001
        st = None
    pair = evidence.live_pair(mint)
    rug = rugs[0] if rugs else None
    sym = (ev[0]["symbol"] if ev else None) or (sigs[0]["symbol"] if sigs else None) or (rug["symbol"] if rug else None) \
        or ((pair or {}).get("baseToken") or {}).get("symbol") or dsym
    name = ((pair or {}).get("baseToken") or {}).get("name") or ((rug or {}).get("data") or {}).get("name") \
        or (sigs[0].get("name") if sigs else None)
    url = (ev[0]["url"] if ev else None) or (sigs[0]["url"] if sigs else None)
    if st and st.get("has_pair") and st.get("pair_url"):
        url = st["pair_url"]
    url = (pair or {}).get("url") or url
    dead = bool(st) and not st.get("has_pair") and not pair
    analysed = bool(ev or sigs or rugs)

    locked = why_bad = rec_note = None
    top = None
    if analysed:
        from rugfilter import archive, collapse
        arch = archive.get(mint, data.HYPE_DB)
        col = None if arch else collapse.check(collapse.peaks(data.HYPE_DB, [mint]).get(mint))
        if arch:
            why_bad = (f'Rugan i izbačen iz praćenja {time.strftime("%d.%m. %H:%M", time.gmtime(arch["archived_ts"]))} UTC: '
                       f'{arch["reason"]} ({archive.KIND_HR.get(arch["kind"], arch["kind"])}); kupnja je zaključana')
        rec = None if arch else archive.recovered(mint, data.HYPE_DB)
        if rec:
            rec_note = (f'Vraćen u praćenje {time.strftime("%d.%m. %H:%M", time.gmtime(rec["recovered_ts"]))} UTC: bio je '
                        f'izbačen kao rug {time.strftime("%d.%m.", time.gmtime(rec["archived_ts"]))} ({rec["reason"] or ""}), '
                        f'a zatim se oporavio na {R.pct(rec["mcap"] / rec["peak_mcap"], sign=False, frac=True)} vrha '
                        f'({R.usd(rec["mcap"])} od {R.usd(rec["peak_mcap"])}).')
        if col:
            why_bad = f'Rugan: {col["text"]}; maknut je s prijedloga i kupnja je zaključana'
        if arch or col:
            locked = "token je rugan"
        from topcheck import store as topstore
        top = topstore.read_all().get(mint)
        if top and top.get("verdict") == "pao" and not locked:
            locked = "token je pao na obaveznom rug checku"
            why_bad = why_bad or ("Pao na obaveznoj provjeri ruga: " + "; ".join(((top.get("safety") or {}).get("fails") or [])[:2]))
        if not why_bad and rug and rug["verdict"] == "ODBAČEN":
            why_bad = "Rug filter ga je odbacio: " + "; ".join((rug["data"].get("hard_fails") or ["tvrdi pad"])[:2])

    sig = sigs[0] if sigs else None
    from ui import confidence, sansa
    _, det = evidence.details(mint)
    pc = data.paper_candidates(mint)
    cand = pc[0] if pc else None
    cs = evidence.checks(mint, sig, det, rug, ev, cand)
    role = "canonical" if any(e["role"] == "canonical" for e in ev) else None
    mk = (rug["data"].get("market") if rug else None) or {}
    feats = (data.js(sig["features"], {}) or {}) if sig else {}
    cargs = (sig["score"] if sig else None, feats, det, rug["verdict"] if rug else None, role,
             (sig or {}).get("liquidity") or mk.get("liquidity"), (sig or {}).get("mcap") or mk.get("mcap"))
    conf, parts = confidence.score(*cargs)
    keyed = confidence.parts_keyed(*cargs)
    sn, an, pr, pa = sansa.score(conf, cs)
    best = max(ev, key=lambda e: e["score"] or 0) if ev else None
    mcap_now = (pair or {}).get("marketCap") or (pair or {}).get("fdv") or ((st or {}).get("mcap") if (st or {}).get("has_pair") else None) \
        or (sig or {}).get("mcap") or mk.get("mcap")
    ch = (pair or {}).get("priceChange") or {}
    h1 = ch.get("h1")
    m0 = _zone_mcap0(mint, now) if analysed else None
    zone_x = mcap_now / m0 if (mcap_now and m0) else None
    from ui import narrative
    try:
        from ui.radar import reasons as _reasons
        why = _reasons(feats, det) if sig else []
    except Exception:  # noqa: BLE001
        why = []

    b = [TOKEN_CSS, tokenchart.CSS, f"<style>{SHEET_CSS}{quickbuy.SHEET_CSS}</style>", '<div class="ms-page ms-wide tkp">']
    if qs.get("err"):
        b.append(f'<p class="tkp-msg neg">Nije prošlo, ništa nije spremljeno: {esc(qs["err"])}</p>')
    elif qs.get("ok"):
        b.append(f'<p class="tkp-msg">{esc(qs["ok"])} <a href="/natjecanje#moj">Vidi svoj račun na Natjecanju</a></p>')
    b.append('<a class="tkp-back" href="/tokens">Tokeni</a>')
    sub = R.cat(name + " · " if name and name != sym else "",
                R.raw(f'<button type="button" class="tkp-cp" data-copy="{esc(mint)}" title="Kopiraj adresu {esc(mint)}">'
                      f'<span class="tkp-cl">{esc(_short_addr(mint))}</span><span class="tkp-ci" aria-hidden="true"></span></button>'))
    right = ""
    if mcap_now:
        right = (f'<div class="tkp-r"><div class="tkp-px">{esc(R.usd(mcap_now))}</div>'
                 + (f'<div class="tkp-s">24 h <span class="{R.tone(ch["h24"])}">{esc(R.pct(ch["h24"]))}</span></div>'
                    if ch.get("h24") is not None else "") + "</div>")
    b.append(f'<div class="tkp-dh"><div><h1 class="ms-h1" translate=no>{esc(sym or _short_addr(mint))}</h1>'
             f'<div class="tkp-s">{sub}</div></div>{right}</div>')

    # verdict panel, buttons, outside sites
    if analysed:
        word, kind = narrative.token_verdict(conf, mcap_now, rug["verdict"] if rug else None, locked,
                                             (top or {}).get("verdict"), h1, zone_x)
        sentence = narrative.token_sentence(why, word, zone_x, why_bad, h1)
        za, protiv = narrative.za_protiv(keyed, parts)
        zt, pt = narrative.za_protiv_line(za, protiv)
        lbl = R.cat(R.dot(kind) if kind in ("warn", "bad") else "", f"Pouzdanost {conf} · šansa za skok {sn}")
        panel = (f'<div class="ms-panel ms-verdict tkp-v"><div class="ms-lbl">{lbl}</div><div class="ms-name">{esc(word)}</div>'
                 f'<p>{esc(sentence)}</p><div class="tkp-go"><b>Za:</b> {esc(zt)} <b>Protiv:</b> {esc(pt)}</div></div>')
    else:
        panel = (f'<div class="ms-panel ms-verdict tkp-v"><div class="ms-lbl">Bez analize</div><div class="ms-name">'
                 f'{"Na popisu " + esc(dlist) if dlist else "Nije u analizi"}</div><p>'
                 + (f'Token je na popisu <a href="/dugorocno">{esc(dlist)}</a>; brojke su na stranici Dugoročni.' if dlist else
                    "Ovaj token nije ni u jednoj analizi. Tržište i vanjske stranice su ispod.") + "</p></div>")
    if rec_note:
        panel += R.hint(rec_note)
    buy_txt = (f"Kupnja je zaključana: {locked}." if locked else
               'Kupnja: demo 50 $ na Natjecanju<span class="adm-only"> ili Autopilot (pravi novac)</span>.')
    actions = ('<div class="tkp-btns"><button type="button" class="tkp-btn p" data-buy'
               + (' aria-disabled="true"' if locked else "") + '>Kupi</button>'
               f'<button type="button" class="tkp-btn s" data-copy="{esc(mint)}"><span class="tkp-cl">Kopiraj adresu</span></button></div>'
               f'<p class="tkp-links">{buy_txt}<br>{_token_links(mint, url, dead)}</p>')
    chart = tokenchart.chart_html(mint, sym or "", now)
    if chart:
        b.append(f'<div class="tkp-g2 a"><div>{chart}</div><div>{panel}{actions}</div></div>')
    else:
        b.append(panel + actions)

    pl = data.token_pulse(mint)
    b.append('<div class="tkp-g2"><section>' + _market_html(pair, st, top, rug, det, pl, url) + "</section><section>"
             + _callers_html(mint, mcap_now, now) + "</section></div>")
    b.append('<div class="tkp-g2"><section>' + _smart_html(mint, det, now) + "</section><section>"
             + _rug_html(top, rug, now) + "</section></div>")

    # how it got its grade: the full reading, the seven layers, live pulse (all one tap away)
    opened = qs.get("sve") == "1"
    b.append(R.section("Kako je dobio ocjenu"))
    full = []
    if analysed:
        try:
            head_, paras = narrative.interpret(mint)
        except Exception as e:  # noqa: BLE001 - never break the page over the summary
            print(f"narrative {mint}: {type(e).__name__}: {e}")
            head_, paras = "", []
        pts = "".join(f'<li><b class="{R.tone(p)}">{esc(R.num(p, 0, sign=True))}</b> {esc(t)}</li>' for p, t in parts)
        full.append(f'<details class="tkp-d"{" open" if opened else ""}>'
                    + _sum_row("Cijelo tumačenje", "za i protiv, svaki razlog s brojem")
                    + f'<div class="tkp-in"><p>{head_}</p>{"".join(paras)}'
                    + (f"<p><b>Pouzdanost {conf}</b>, po dijelovima:</p><ul class=tkp-list>{pts}</ul>" if pts else "")
                    + sansa.explain_html(sn, conf, an, pr, pa).replace("confidence", "pouzdanost") + "</div></details>")
    layers = _layers_html(mint, ev, sigs, rugs, pc, best, role, opened)
    full.append(f'<details class="tkp-d" id="slojevi"{" open" if opened else ""}>'
                + _sum_row("Slojevi analize", "KOL, hype, rug, puls, walleti, X, event", f"{an} od {sansa.N}")
                + f'<div class="tkp-in">{sansa.dots_html(cs)} {tier_html(mint) if analysed else ""}{layers}</div></details>')
    from hype import pulse as hpulse
    sf = hpulse.strength(pl) if pl else {}
    try:
        from live import pulse as _lp
        live_html = _lp.token_html(mint)
    except Exception:  # noqa: BLE001 - the live card never breaks the page
        live_html = ""
    full.append(f'<details class="tkp-d" id="puls"{" open" if opened else ""}>'
                + _sum_row("Puls uživo", (hpulse.describe(sf) or "").replace("Snaga: ", "")
                           or ("kupci i prodavači u zadnjih 15 min" if live_html else "nema očitanja u zadnja 24 h"))
                + f'<div class="tkp-in">{live_html}{_pulse_table(pl)}</div></details>')
    b.append('<div class="ms-list">' + "".join(full) + "</div>")
    b.append(R.hint("Pouzdanost: koliko se neovisni izvori slažu. Šansa za skok: koliko je sličnih tokena nastavilo rasti.")
             .replace("</p>", ' <a class="ms-acc" href="/pojmovnik#confidence" style="text-decoration:none">Pojmovnik</a></p>'))
    b.append(quickbuy.buy_sheet(mint, sym, locked) + "</div>" + TOKEN_JS)
    # a detail page of about three screens: no row of section chips on top (ui/secnav builds one from 3+ <h2>)
    return sym or short(mint), "".join(b).replace("<h2", '<h2 data-sec=""')


def _pulse_table(pl):
    """The pulse readings (hype/pulse, every 2 min while the token is interesting), newest first."""
    if not pl:
        return ""
    return table(["Vrijeme", ("Mcap", "n"), ("Vol 5 min", "n"), ("Vol 1 h", "n"), ("Kupnje 1 h", "n"), ("Prodaje 1 h", "n"),
                  ("Holderi (puls)", "n")],
                 [[ts(x["ts"]), usd(x["mcap"]), usd(x["vol_m5"]), usd(x["vol_h1"]), num(x["buys_h1"]), num(x["sells_h1"]),
                   (f"{x['holders']} <span class=mut>{esc(x['holders_src'] or '')}</span>", x["holders"], "n") if x["holders"] else num(None)]
                  for x in pl[::-1][:48]])


def _layers_html(mint, ev, sigs, rugs, pc, best, role, opened):
    """The analysis layers as they were on the old page (event, hype, rug filter, demo trading, wallets), each folded,
    with every table. 10.11.: moved under "Kako je dobio ocjenu → Slojevi analize"; the KOL layer is under "Tko ga je
    zvao" and the pulse under "Puls uživo"."""
    b = [f"<p class=mut style='font-size:13px'><a href='?sve={'0' if opened else '1'}'>{'Sklopi sve' if opened else 'Otvori sve'}</a></p>"]
    sigs_asc = sigs[::-1]

    def sec(sid, title, summary, force=False):
        return (f"<details id={sid}{' open' if opened or force else ''}><summary><b>{title}</b> "
                f"<span class=mut>· {summary}</span></summary>")

    # layer 1: event
    ev_sum = (f"{esc(best['event'])} · {'pravi' if role else 'kopija'} · ocjena {best['score']}" if best else "nije vezan uz event")
    b.append(sec("event", "1. Event sloj", ev_sum))
    if not ev:
        b.append("<p class=mut>Nije pronađen ni za jedan event iz kalendara.</p>")
    for e in ev:
        d = dict(e["data"])
        d.setdefault("cto", e["cto"])
        erole = "pravi (canonical)" if e["role"] == "canonical" else "kopija (copycat)"
        b.append(f'<div class=card><b>{esc(e["event"])}</b> · {esc(e["event_date"])} · pojam '
                 f'<code>{esc(e["keyword"])}</code> · {badge(erole, "good" if e["role"] == "canonical" else "")}'
                 f'<p class=mut>Token pripada eventu jer mu je simbol jednak pojmu ili ime sadrži pojam. '
                 f'Unutar eventa najviša ocjena je "pravi", ostali su kopije.</p>')
        b.append(breakdown(explain.organic(d), "Organska ocjena", e["score"]))
        b.append("</div>")
    b.append("</details>")

    # layer 2: hype
    hy_sum = (f"zadnja ocjena {sigs[0]['score']}, max {max(x['score'] or 0 for x in sigs)}, {len(sigs)} signala" if sigs
              else "hype skener ga nije uhvatio")
    b.append(sec("hype", "2. Hype sloj", hy_sum))
    if not sigs:
        b.append("<p class=mut>Hype skener ga nije uhvatio.</p>")
    else:
        last = sigs[0]
        f = data.js(last["features"], {}) or {}
        wts = data.js(last["weights"], {}) or {}
        tot = sum(wts.get(k, 0) for k in f) or 1  # same as hype/score.py: only measured features count
        rows = []
        for k in sorted(set(f), key=lambda k: -(wts.get(k, 0) * f.get(k, 0))):
            val, wt = f.get(k, 0) or 0, wts.get(k, 0)
            pts = 100 * wt * val / tot
            rows.append([esc(labels.feat(k)), (f"{val:.2f}", val, "n"), (f"{wt:g}", wt, "n"), (f"{pts:.1f}", pts, "n"),
                         bar(pts, 100 * wt / tot if wt else 1), (f'<span class=mut>{esc(FEATURE.get(k, ""))}</span>', "", "wrap")])
        b.append(f"<p>Zadnji signal {ts(last['ts'])[0]} UTC, ocjena <b>{last['score']}</b>, otkud je došao: "
                 f"{esc(labels.sources(last['sources']))}. Ocjena = Σ(signal × težina) / Σ težina izmjerenih signala × 100; "
                 f"provjera koja nije rađena (npr. X buzz) ne ulazi ni u zbroj ni u nazivnik.</p>")
        b.append(table(["Signal", ("Vrijednost 0-1", "n"), ("Težina", "n"), ("Doprinos", "n"), "", ("Što mjeri", "wrap")], rows))
        b.append(f"<p>Zbroj doprinosa: <b>{sum(r[3][1] for r in rows):.1f}</b> <span class=mut>(spremljeno {last['score']})</span></p>")
        snaps = data.hype_snapshots(mint)
        if len(snaps) > 1:
            b.append("<h3>Cijena od prvog signala</h3>" + _spark(snaps, sigs_asc[0]["price"]))
        b.append("<h3>Svi signali</h3>")
        b.append(table(["Vrijeme", ("Ocjena", "n"), ("Cijena", "n"), ("Mcap", "n"), ("Likvidnost", "n"), "Izvori"],
                       [[ts(s["ts"]), scorecell(s["score"]), price(s["price"]), usd(s["mcap"]),
                         usd(s["liquidity"]), (esc(labels.sources(s["sources"])), "", "wrap")] for s in sigs[:200]]))
    b.append("</details>")

    # layer 3: rug
    rg_sum = (f"{esc(rugs[0]['verdict'])}, ocjena {rugs[0]['score'] if rugs[0]['score'] is not None else '–'}, "
              f"{len(rugs[0]['data'].get('hard_fails', []))} tvrdih, {len(rugs[0]['data'].get('flags', []))} zastavica" if rugs
              else "nije provjeren")
    b.append(sec("rug", "3. Rug filter", rg_sum, force=bool(rugs and rugs[0]["verdict"] in ("ODBAČEN", "VISOK RIZIK"))))
    if not rugs:
        b.append("<p class=mut>Nije provjeren rug filterom: puna provjera ide samo tokenima koji prođu prve razine analize.</p>")
    else:
        r = rugs[0]
        d = r["data"]
        b.append(f"<p>{verdict(r['verdict'])} ocjena <b>{r['score'] if r['score'] is not None else '– (tvrdi pad)'}</b>"
                 f" · provjereno {ts(r['checked_at'])[0]} UTC</p><div class=card><ul class=r>")
        for x in d.get("hard_fails", []):
            b.append(f'<li class=bad><b>TVRDI PAD:</b> {esc(x)}</li>')
        for x in d.get("flags", []):
            b.append(f'<li class=warn>{esc(x)}</li>')
        for x in d.get("positives", []):
            b.append(f'<li class=good>{esc(x)}</li>')
        if not (d.get("hard_fails") or d.get("flags") or d.get("positives")):
            b.append("<li>Nema zabilježenih razloga.</li>")
        b.append("</ul><p class=mut>Kreće od 100, svaka zastavica oduzima bodove, smart walleti dodaju do +15. "
                 "Tvrdi pad = odmah ODBAČEN. ≥75 PROLAZI, 50-74 OPREZ, &lt;50 VISOK RIZIK.</p></div>")
        L, h, c, v, dv, m = (d.get(k) or {} for k in ("launch", "holders", "cluster", "volume", "dev", "market"))
        metr = [("Bundle (blok kreacije)", f"{L.get('bundle_pct', '–')}% · {L.get('bundle_wallets', '–')} walleta"),
                ("Snajperi (~8 s)", f"{L.get('sniper_pct', '–')}% · {L.get('sniper_wallets', '–')} walleta"),
                ("Top 10 holdera", f"{h.get('top10_pct', '–')}%"),
                ("Fresh walleti (rani / holderi)", f"{h.get('fresh_early_pct', '–')}% / {h.get('fresh_holders_pct', '–')}%"),
                ("Klaster (isti izvor SOL-a)", f"{max(c.get('holding_pct', 0), c.get('early_pct', 0))}% · {len(c.get('wallets') or [])} walleta"),
                ("Wash score", f"{d.get('wash_score', '–')} (round-trip {v.get('round_trip_volume_pct', '–')}%, top5 {v.get('top5_volume_pct', '–')}%)"),
                ("RugCheck insajderi", f"{(d.get('rugcheck') or {}).get('insider_pct', '–')}%"),
                ("Mint / freeze authority", f"{'AKTIVNA' if (d.get('authorities') or {}).get('mintAuthority') else 'ugašena'} / "
                                            f"{'AKTIVNA' if (d.get('authorities') or {}).get('freezeAuthority') else 'ugašena'}"),
                ("Dev", f"{short(dv.get('wallet', ''))} · napravio {dv.get('tokens_created', '–')} tokena (živih {dv.get('tokens_alive', '–')}) · "
                        f"drži {dv.get('hold_pct', '–')}% · prodao {dv.get('sold_pct', '–')}%"),
                ("Likvidnost / max ulaz (5% slippage)", f"${m.get('liquidity') or 0:,.0f} / ${m.get('max_entry_usd_5pct') or 0:,.0f}")]
        b.append(table(["Provjera", ("Vrijednost", "wrap")], [[esc(k), (esc(x), "", "wrap")] for k, x in metr]))
        top = h.get("top") or []
        if top:
            b.append("<h3>Top holderi</h3>" + table(["Wallet", ("%", "n"), "Insajder"],
                                                   [[wlink(x["wallet"]), num(x.get("pct"), "{:.1f}"),
                                                     badge("da", "bad") if x.get("insider") else "ne"] for x in top]))
        md = os.path.join("rug", f"{mint}.md")
        if data.read_output(md) is not None:
            b.append(f'<p><a href="/outputs/{quote(md)}">Puni rug izvještaj</a></p>')
        if len(rugs) > 1:
            b.append("<h3>Ranije provjere</h3>" + table(["Vrijeme", "Presuda", ("Ocjena", "n")],
                                                       [[ts(x["checked_at"]), verdict(x["verdict"]), num(x["score"])] for x in rugs[1:]]))
    b.append("</details>")

    if pc:
        c = pc[0]
        b.append(sec("paper", "4. Demo trading", f"{esc(labels.decision(c['decision']))} · {esc(labels.reason(c['reason']))}"))
        b.append(f"<div class=card>{_decision(c)} {esc(labels.reason(c['reason']))} <span class=mut>· {esc(labels.source(c['origin']))} · "
                 f"{ts(c['first_ts'])[0]} UTC</span>" + "".join(f"<div class=mut>rug: {esc(x)}</div>" for x in c["rug_flags"]))
        for t in data.paper_trades(mint):
            b.append(f"<p>Trejd #{t['id']}: {'otvoren' if t['status'] == 'open' else 'zatvoren'}, povrat {(t['ret'] or 0):+.0%}, "
                     f"max {(t['max_ret'] or 0):+.0%}" + (f", izlaz: {esc(labels.exit_reason(t['exit_reason']))}" if t['exit_reason'] else "") + "</p>")
        b.append("</div></details>")

    # wallets on this token (10.11.: copy score and labels of just these wallets, by key, not the whole registry)
    sg = data.sightings(token=mint)
    b.append(sec("walleti", "5. Walleti viđeni na ovom tokenu", f"{len(sg)} iz registra"))
    ws = sorted({x["wallet"] for x in sg})
    wmap = {}
    for i in range(0, len(ws), 500):
        part = ws[i:i + 500]
        for w in data.q(data.WALLET_DB, f"SELECT wallet, copy_score, tier, labels FROM wallets WHERE wallet IN ({','.join('?' * len(part))})", part):
            w["labels"] = data.js(w.get("labels"), []) or []
            wmap[w["wallet"]] = w
    b.append(table(["Wallet", "Uloga", "Izvor", ("SOL", "n"), ("Copy", "n"), "Tier", "Oznake"],
                   [[wlink(x["wallet"]), esc(ROLE.get(x["role"], (x["role"],))[0]), esc(SOURCE.get(x["source"], x["source"])),
                     num(x["sol_in"], "{:.2f}"), num((wmap.get(x["wallet"]) or {}).get("copy_score")),
                     tierb((wmap.get(x["wallet"]) or {}).get("tier")),
                     " ".join(badge(l, "bad") for l in (wmap.get(x["wallet"]) or {}).get("labels", []))] for x in sg],
                   empty="Nijedan wallet nije zabilježen za ovaj token."))
    b.append("</details>")
    return "".join(b)


def _spark(snaps, base):
    pts = [(s["ts"], s["price"]) for s in snaps if s["price"]]
    if len(pts) < 2:
        return ""
    base = base or pts[0][1]
    t0, t1 = pts[0][0], pts[-1][0]
    ys = [p / base - 1 for _, p in pts]
    lo, hi = min(ys + [0]), max(ys + [0])
    W, H = 600, 120

    def xy(t, y):
        return (W * (t - t0) / max(1, t1 - t0), H - H * (y - lo) / max(1e-9, hi - lo))
    path = " ".join(f"{x:.1f},{y:.1f}" for x, y in (xy(t, v) for (t, _), v in zip(pts, ys)))
    zy = xy(t0, 0)[1]
    return (f'<div class=card><svg viewBox="0 0 {W} {H}" width="100%" height="{H}" preserveAspectRatio=none>'
            f'<line x1=0 x2={W} y1={zy:.1f} y2={zy:.1f} stroke="currentColor" stroke-opacity=.2 />'
            f'<polyline points="{path}" fill=none stroke="var(--bar)" stroke-width=2 vector-effect=non-scaling-stroke /></svg>'
            f'<span class=mut>max {max(ys):+.0%} · zadnje {ys[-1]:+.0%} od cijene prvog signala · {len(pts)} točaka</span></div>')


# ---------------- events ----------------

def _pick_cell(ranked, watches=None):
    """Event row: the most likely pumper on one line (name, icons, score); its reasons and every other token
    ranked sit in one closed <details>, so the row stays short until someone opens it (Nicholas 4.11.)."""
    if not ranked:
        return "–"
    best = ranked[0]
    if best["pump"] is None:
        return "<span class=mut>nijedan token ne prolazi provjere</span>"
    pk = "good" if best["pump"] >= 60 else "warn" if best["pump"] >= 35 else ""
    score = f"{best['pump']:.0f}/100"
    head = f"{tlink(best['token'], best['symbol'])} {badge(score, pk)}"
    w = (watches or {}).get(best["token"])
    if w and w.get("verdict"):
        from ui.watch import VERDICT_KIND
        head += f'<div class=evw>⏳ {badge(w["verdict"], VERDICT_KIND.get(w["verdict"], ""))}</div>'
    why = "".join(f"<div>{p:+.0f} {esc(t)}</div>" for p, t in best["reasons"][:6])
    others = []
    for i, t in enumerate(ranked[1:], 2):
        val = "isključen: " + esc(t["excluded"]) if t["pump"] is None else f"{t['pump']:.0f}/100"
        others.append(f"<div>{i}. {tlink(t['token'], t['symbol'])} {val}</div>")
    lab = "zašto" + (f" · još {len(others)}" if others else "")
    body = (f"<div class=mut>{why}</div>" + (f"<div class=evo><b>Ostali tokeni</b>{''.join(others)}</div>" if others else ""))
    return head + f"<details class=evd><summary>{lab}</summary><div class=evx>{body}</div></details>"


def _when(date, hype=None):
    """'danas' / 'sutra' / 'za 3 d' / 'prije 2 d' with the date and the calendar colour dot; sorts by date."""
    try:
        d = time.strptime(str(date)[:10], "%Y-%m-%d")
        n = round((time.mktime(d) - time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d"))) / 86400)
    except (ValueError, TypeError):
        return ("–", "", "")
    txt = {0: "danas", 1: "sutra", -1: "jučer"}.get(n) or (f"za {n} d" if n > 0 else f"prije {-n} d")
    from ui import evcal
    return (f"<b>{txt}</b><div class=mut>{evcal.dot(hype)} {d.tm_mday}.{d.tm_mon}.</div>", str(date), "")


def _ev_cell(e):
    """Event title + one small line (kind · source) + keyword chips (max 4): replaces three wide columns."""
    t = (f'<a href="{esc(e["url"])}" target=_blank rel=noopener>{esc(e["title"])}</a>' if e.get("url") else esc(e["title"]))
    meta = f'<div class=evm>{esc(labels.kind(e["kind"]))} · {esc(labels.event_source(e["source"]))}</div>'
    kws = e.get("keywords") or []
    chips = "".join(f"<span class=kw translate=no>{esc(k)}</span>" for k in kws[:4])
    if len(kws) > 4:
        chips += f'<span class="kw mut" title="{esc(" ".join(kws[4:]))}">+{len(kws) - 4}</span>'
    return (t + meta + (f"<div class=kws>{chips}</div>" if chips else ""), e["title"] + " " + " ".join(kws), "wrap evc")


EV_CSS = """<style>
#et td.evc{min-width:210px;max-width:340px}.evm{font-size:12px;color:var(--mut);margin-top:2px}
.kws{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px}.kw{font-size:11px;padding:1px 6px;border-radius:6px;
 background:color-mix(in srgb,var(--acc) 8%,var(--card));border:1px solid var(--line);white-space:nowrap}
#et td.evt{min-width:170px;max-width:300px;white-space:normal}.evw{margin-top:3px}
details.evd summary{font-size:12px;color:var(--acc);cursor:pointer;margin-top:3px}
.evx{font-size:12px;white-space:normal;max-width:300px;padding-top:3px}.evo{margin-top:6px}
details.evh summary{font-size:12px;color:var(--acc);cursor:pointer}.evh .evx div{white-space:normal}
table.cards#et td.evt,table.cards#et td.evc{max-width:none}table.cards#et td.evt .evx{max-width:none}
.evstat{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 10px}.evstat a,.evstat span{font-size:13px;padding:6px 10px;
 border:1px solid var(--line);border-radius:10px;background:var(--card);text-decoration:none;color:var(--fg)}
.evstat b{font-size:15px}
</style>"""


def _ev_detail(e, ranked, det):
    """Pop-up body for one event (calendar tap): everything the list row has, written out."""
    from ui import evcal
    c, lab = evcal.level(e.get("hype"))
    t = (f'<a href="{esc(e["url"])}" target=_blank rel=noopener>{esc(e["title"])} ↗</a>' if e.get("url") else esc(e["title"]))
    kws = " ".join(f"<span class=kw translate=no>{esc(k)}</span>" for k in e.get("keywords") or [])
    tl = e.get("token_likelihood")
    pick = _pick_cell(ranked, None) if ranked else "<span class=mut>još nema tokena</span>"
    return (f'<div class=ecev><h3>{evcal.dot(e.get("hype"))}{t}</h3>'
            f'<div class=lab>{esc(labels.kind(e["kind"]))} · {esc(labels.event_source(e["source"]))} · {esc(e["date"])}</div>'
            f'<div class=row><span><span class=lab>Hype {info("Hype")}</span> {bar(e["hype"] or 0, 100, 60)} <b>{(e["hype"] or 0):g}</b> ({lab})</span>'
            f'<span><span class=lab>Šansa za token {info("Šansa za token")}</span> <b>{"–" if tl is None else f"{tl:.2f}"}</b></span></div>'
            + (f'<div class="kws">{kws}</div>' if kws else "")
            + f'<div class=row style="display:block"><span class=lab>Najizgledniji token {info("Najizgledniji token")}</span><div>{pick}</div></div>'
            + f'<div class=row style="display:block"><span class=lab>Zašto ta ocjena</span>{det}</div></div>')


def _events_rows(evs, watches):
    """[(event, list row, pop-up html)] for every event, best token per event ranked with eventpick."""
    et = {}
    for t in data.event_tokens():
        et.setdefault((t["event_date"], t["event"]), []).append(t)
    rugs, kol = data.rug_latest(), pickload.kol_mentions()
    out = []
    for e in evs:
        toks = sorted(et.get((e["date"], e["title"]), []), key=lambda t: -(t["score"] or 0))
        ranked = pickscore.rank(toks, rugs, watches, kol) if toks else []
        parts = explain.event_hype(e)
        det = (f"<details class=evh><summary>raspis</summary><div class=evx>"
               + "".join(f"<div>{esc(n)} {info(n)}: <b>{p:.1f}</b>/{m} <span class=mut>{esc(x)}</span></div>" for n, p, m, x in parts)
               + "</div></details>")
        row = [_ev_cell(e), _when(e["date"], e.get("hype")), scorecell(e["hype"]), num(e.get("token_likelihood"), "{:.2f}"),
               (_pick_cell(ranked, watches) if toks else "", (ranked[0]["pump"] or 0) if ranked else -1, "wrap evt"),
               (det, "", "")]
        e["_has_tok"] = bool(toks)
        out.append((e, row, _ev_detail(e, ranked, det)))
    return out


def events(qs):
    from ui import evcal, watch
    allev = data.events()
    past = qs.get("past") == "1"
    only_tok = qs.get("tok") == "1"
    today = time.strftime("%Y-%m-%d")
    watches = pickload.watches()
    built = _events_rows(allev, watches)
    shown = [(e, r) for e, r, _ in built if (past or not e["date"] or e["date"] >= today) and (not only_tok or e["_has_tok"])]
    tbl = table([("Event", "wrap"), "Kada", ("Hype", "n"), ("Šansa za token", "n"), "Najizgledniji token",
                 "Zašto ta ocjena"], [r for _, r in shown], "et",
                "Nema evenata za ovaj izbor. Bot osvježava kalendar sam svakih 6 h.")
    upcoming = [e for e, _, _ in built if not e["date"] or e["date"] >= today]
    n_watch = watch.tracked_count()
    stat = (f'<div class=evstat><span><b>{len(upcoming)}</b> nadolazećih</span>'
            f'<span><b>{sum(e["_has_tok"] for e in upcoming)}</b> s tokenom</span>'
            f'<a href="#prije"><b>{n_watch}</b> tokena u praćenju ⏳ ↓</a></div>')
    form = (f'<form class=flt method=get>{filt("et", "Filtriraj event, ključnu riječ…")}'
            f'<label><input type=checkbox name=tok value=1 {"checked" if only_tok else ""} onchange="this.form.submit()"> samo s tokenom</label> '
            f'<label><input type=checkbox name=past value=1 {"checked" if past else ""} onchange="this.form.submit()"> i prošli</label></form>')
    intro = ("<h1>Eventi</h1><p class=mut>Događaji iz kalendara, tokeni napravljeni za njih i kreću li ti tokeni prije "
             "događaja. <a href=/criteria#eventi>Kriteriji</a>.</p>")
    cal = evcal.render([(e, d) for e, _, d in built], dt.date.fromisoformat(today))
    lst = ("<h2 id=lista>📋 Svi eventi po datumu</h2>" + tdesc(
        'Iz kalendara alat uzme ključne riječi događaja i na DexScreeneru traži tokene s tim imenom ili simbolom. '
        'Hype = koliko se o događaju priča, šansa za token = procjena da će netko napraviti token. '
        '<i>Najizgledniji token</i> je onaj s najvećom ocjenom pumpe 0-100 (organsko trgovanje, prostor za rast, rug provjera, '
        'volumen i smart walleti prema eventu, KOL-ovi); „zašto” otvara razloge i ostale tokene, ⏳ je zaključak praćenja prije '
        'eventa. Tokeni koje rug provjera odbaci ili s likvidnošću ispod $2k ne mogu biti izbor. Ocjena je procjena, ne garancija.')
        + form + tbl)
    return "Eventi", (EV_CSS + intro + stat + "<h2 id=kalendar>📅 Kalendar</h2>"
                      + '<p class=mut style="margin:0">Dodirni dan za detalje događaja.</p>' + cal
                      + lst + '<h2 id=prije>⏳ Prije eventa</h2>' + watch.sections())


# ---------------- outputs ----------------

def outputs(qs):
    files = data.outputs()
    syms = data.symbols()
    rows = [[f'<a href="/outputs/{quote(p)}">{esc(labels.report_name(p, syms))}</a>', ts(m)] for p, m, sz in files]
    return "Izvještaji", ("<h1>Izvještaji</h1><p class=mut>Izvještaji koje bot sam piše: dnevni pregled demo tradinga, "
                          "kalendar, rug provjere, copy lista walleta.</p>"
                          + tdesc('Klik otvara izvještaj.') + table([("Izvještaj", "wrap"), "Napisan"], rows, empty="Još nema izvještaja."))


def output(rel, qs):
    txt = data.read_output(rel)
    if txt is None:
        return None
    name = labels.report_name(rel, data.symbols())
    return name, (f'<p><a href="/outputs">← izvještaji</a></p><h1>{esc(name)}</h1>'
                  f'<pre style="white-space:pre-wrap">{esc(labels.plain_md(txt))}</pre>')


# ---------------- paper trading ----------------

DECISION = {"taken": "good", "take": "good", "buy": "good", "skip": "", "skipped": ""}


def _decision(c):
    d = c.get("decision") or "–"
    return badge(labels.decision(d), DECISION.get(d, "warn" if d.startswith("skip") else "good"))
