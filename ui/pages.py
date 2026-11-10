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


def token(mint, qs):
    ev = data.event_tokens(mint)
    sigs = data.hype_signals("token=?", (mint,), "ts DESC")
    rugs = data.rug_reports(mint)
    sym = (ev[0]["symbol"] if ev else None) or (sigs[0]["symbol"] if sigs else None) or (rugs[0]["symbol"] if rugs else None)
    url = (ev[0]["url"] if ev else None) or (sigs[0]["url"] if sigs else None)
    from ui import league as _league, quickbuy
    dsym, dlist = quickbuy.dugo_info(mint)
    sym = sym or dsym
    # top to bottom: name + Šansa, rug warnings, one-sentence verdict, Za / Protiv, copy, outside sites; then the
    # layers behind taps; the Natjecanje buy box (bonus) last
    try:   # 7.11.: the exact pair page, or "no pair any more" (hype/tokenstatus)
        from hype import tokenstatus as _ts
        st = _ts.read(data.HYPE_DB).get(mint)
    except Exception:  # noqa: BLE001
        st = None
    if st and st.get("has_pair") and st.get("pair_url"):
        url = st["pair_url"]
    dead_note = ("<p class=mut>DexScreener više nema par za ovaj token (nema trgovanja). "
                 + (f"GeckoTerminal: vrijednost ${st['gt_fdv']:,.0f}, promet 24 h ${st.get('gt_vol24') or 0:,.0f}." if st.get("gt_fdv") else "")
                 + "</p>") if st and not st.get("has_pair") else ""
    actions = (f"<p>{quickbuy.copy_btn(mint, label='Kopiraj adresu ' + short(mint), big=True)}</p>"
               f"<div class=ext-big>{ext_icons(mint, url, dead=bool(st) and not st.get('has_pair'))}</div>{dead_note}")
    b = [_league._err(qs) + ('<p><a href="/natjecanje#moj"><b>Vidi svoj račun na Natjecanju →</b></a></p>' if qs.get("ok") else "")]
    natj = ""
    locked = None
    if not (ev or sigs or rugs):
        b.insert(0, f"<h1>{esc(sym or short(mint))}</h1>")
        b.append((f'<p class=mut>Na popisu <a href="/dugorocno">{esc(dlist)}</a>.</p>' if dlist else
                  "<p class=mut>Ovaj token nije ni u jednoj analizi.</p>") + actions)
        b.append(quickbuy.token_box(mint, sym))
    else:
        from rugfilter import archive, collapse
        arch = archive.get(mint, data.HYPE_DB)
        col = None if arch else collapse.check(collapse.peaks(data.HYPE_DB, [mint]).get(mint))
        if arch:
            import time as _t
            b.append(f'<div class=card style="border-color:var(--bad)"><b class=neg>💀 Rugan i izbačen iz praćenja:</b> '
                     f'{esc(arch["reason"])} ({esc(archive.KIND_HR.get(arch["kind"], arch["kind"]))}). '
                     f'Izbačen {_t.strftime("%d.%m. %H:%M", _t.gmtime(arch["archived_ts"]))} UTC: bot ga više ne prati i ne troši '
                     'API kredite na njega, a čuva samo podatke s ulaza da iz njih uči kako izgleda rug. Kupnja je zaključana.</div>')
        rec = None if arch else archive.recovered(mint, data.HYPE_DB)
        if rec:
            import time as _t
            b.append(f'<div class=card><b>↩ Vraćen u praćenje</b> {_t.strftime("%d.%m. %H:%M", _t.gmtime(rec["recovered_ts"]))} UTC: '
                     f'bio je izbačen kao rug {_t.strftime("%d.%m.", _t.gmtime(rec["archived_ts"]))} ({esc(rec["reason"] or "")}), '
                     f'a zatim se oporavio na {rec["mcap"] / rec["peak_mcap"]:.0%} vrha (${rec["mcap"] / 1000:,.0f}k od '
                     f'${rec["peak_mcap"] / 1000:,.0f}k). Rug profil ga više ne broji kao rug; bot ga opet prati.</div>')
        if col:
            b.append(f'<div class=card style="border-color:var(--bad)"><b class=neg>💀 Rugan:</b> {esc(col["text"])}. '
                     'Maknut je s prijedloga i kupnja u natjecanju je zaključana.</div>')
        if arch or col:
            locked = "token je rugan"
        from topcheck import store as topstore
        from ui import topcheckui
        top = topstore.read_all().get(mint)
        if top and top.get("verdict") == "pao" and not locked:
            locked = "token je pao na obaveznom rug checku"
        topbox = topcheckui.token_box(top)
        natj = quickbuy.token_box(mint, sym, locked)
        from ui import narrative
        b.append(narrative.verdict_html(mint))
        tiers = tier_html(mint)

    # summary: one card with the verdict numbers, then "za" / "protiv" from the confidence parts
    sigs_asc = sigs[::-1]
    sig = sigs[0] if sigs else None
    from ui import confidence, evidence, sansa
    _, det = evidence.details(mint)
    pc = data.paper_candidates(mint)
    cand = pc[0] if pc else None
    cs = evidence.checks(mint, sig, det, rugs[0] if rugs else None, ev, cand)
    role = "canonical" if any(e["role"] == "canonical" for e in ev) else None
    mk = (rugs[0]["data"].get("market") if rugs else None) or {}
    conf, parts = confidence.score(sig["score"] if sig else None, (data.js(sig["features"], {}) or {}) if sig else {}, det,
                                   rugs[0]["verdict"] if rugs else None, role,
                                   (sig or {}).get("liquidity") or mk.get("liquidity"), (sig or {}).get("mcap") or mk.get("mcap"))
    sn, an, pr, pa = sansa.score(conf, cs)
    best = max(ev, key=lambda e: e["score"] or 0) if ev else None
    if ev or sigs or rugs:
        b.insert(0, f"<div class=tokhead><h1>{esc(sym or short(mint))}</h1><div class=sn><small>Šansa {info('Šansa')}</small>"
                    f"<b>{sn}</b></div></div>")
    za = [t for p_, t in parts if p_ > 0]
    protiv = [t for p_, t in parts if p_ < 0]
    if ev or sigs or rugs:
        if za or protiv:
            b.append("<div class=grid style='grid-template-columns:1fr 1fr;gap:12px'>"
                     "<div class=card><b style='color:var(--good)'>Za</b><ul class=r>"
                     + "".join(f"<li class=good>{esc(t)}</li>" for t in za[:5]) + ("<li class=mut>ništa izmjereno</li>" if not za else "")
                     + "</ul></div><div class=card><b style='color:var(--bad)'>Protiv</b><ul class=r>"
                     + "".join(f"<li class=bad>{esc(t)}</li>" for t in protiv[:5]) + ("<li class=mut>nema zabilježenih rizika</li>" if not protiv else "")
                     + "</ul></div></div>")
        try:
            from live import pulse as _lp
            topbox += _lp.token_html(mint)
        except Exception:  # noqa: BLE001 - the live card never breaks the page
            pass
        b.append(actions + topbox)
        b.append("<h2>Brojke</h2><div class=grid>")
        for v, l in [(f"<b>{sn}</b>", "šansa za skok"), (conf, "confidence"),
                     (f"{an}/{sansa.N} {sansa.dots_html(cs)}", "slojeva analizirano"),
                     (max(s["score"] or 0 for s in sigs) if sigs else "–", "hype max"),
                     (verdict(rugs[0]["verdict"]) if rugs else "–", "rug presuda"),
                     (best["score"] if best else "–", "event ocjena")]:
            b.append(f"<div class=stat><div class=v>{v}</div><div class=l>{l}</div></div>")
        b.append("</div>" + tiers)
    opened = qs.get("sve") == "1"
    b.append(f"<h2>Slojevi</h2><p class=mut style='font-size:12px'><a href='?sve={'0' if opened else '1'}'>"
             f"{'Sklopi sve' if opened else 'Otvori sve'}</a></p>")

    def sec(sid, title, summary, force=False):
        return (f"<details id={sid}{' open' if opened or force else ''}><summary><b>{title}</b> "
                f"<span class=mut>· {summary}</span></summary>")

    from ui import kol
    kol_html = kol.token_section(mint)
    if kol_html:
        b.append(sec("kol", "KOL sloj", "tko ga je zvao na X-u i što je cijena napravila") + kol_html + "</details>")

    # layer 1: event
    ev_sum = (f"{esc(best['event'])} · {'pravi' if role else 'kopija'} · ocjena {best['score']}" if best else "nije vezan uz event")
    b.append(sec("event", "1. Event sloj", ev_sum))
    if not ev:
        b.append("<p class=mut>Nije pronađen ni za jedan event iz kalendara.</p>")
    for e in ev:
        d = dict(e["data"])
        d.setdefault("cto", e["cto"])
        role = "pravi (canonical)" if e["role"] == "canonical" else "kopija (copycat)"
        b.append(f'<div class=card><b>{esc(e["event"])}</b> · {esc(e["event_date"])} · pojam '
                 f'<code>{esc(e["keyword"])}</code> · {badge(role, "good" if e["role"] == "canonical" else "")}'
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
        b.append(tdesc('Raspis zadnje hype ocjene: koliko je svaki signal izmjeren (0-1), koliko vrijedi i koliko je bodova donio.') + table(["Signal", ("Vrijednost 0-1", "n"), ("Težina", "n"), ("Doprinos", "n"), "", ("Što mjeri", "wrap")], rows))
        b.append(f"<p>Zbroj doprinosa: <b>{sum(r[3][1] for r in rows):.1f}</b> <span class=mut>(spremljeno {last['score']})</span></p>")
        snaps = data.hype_snapshots(mint)
        if len(snaps) > 1:
            b.append("<h3>Cijena od prvog signala</h3>" + _spark(snaps, sigs_asc[0]["price"]))
        b.append("<h3>Svi signali</h3>")
        b.append(tdesc('Svaki put kad ga je hype skener zabilježio, s cijenom i izvorima u tom trenutku.') + table(["Vrijeme", ("Ocjena", "n"), ("Cijena", "n"), ("Mcap", "n"), ("Likvidnost", "n"), "Izvori"],
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
        b.append(tdesc('Rezultati pojedinih provjera rug filtera (Helius + RugCheck): ovlasti, dev, holderi, likvidnost.') + table(["Provjera", ("Vrijednost", "wrap")], [[esc(k), (esc(x), "", "wrap")] for k, x in metr]))
        top = h.get("top") or []
        if top:
            b.append("<h3>Top holderi</h3>" + tdesc('Najveći holderi i jesu li povezani s devom ili međusobno (insajderi).') + table(["Wallet", ("%", "n"), "Insajder"],
                                                     [[wlink(x["wallet"]), num(x.get("pct"), "{:.1f}"),
                                                       badge("da", "bad") if x.get("insider") else "ne"] for x in top]))
        md = os.path.join("rug", f"{mint}.md")
        if data.read_output(md) is not None:
            b.append(f'<p><a href="/outputs/{quote(md)}">Puni rug izvještaj</a></p>')
        if len(rugs) > 1:
            b.append("<h3>Ranije provjere</h3>" + tdesc('Prijašnje rug provjere istog tokena.') + table(["Vrijeme", "Presuda", ("Ocjena", "n")],
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

    # pulse: what the token did after it earned attention (retained in every scan)
    pl = data.token_pulse(mint)
    if pl:
        from hype import pulse as hpulse
        sf = hpulse.strength(pl)
        hold = [x for x in pl if x["holders"]]
        b.append(sec("puls", "6. Puls (osvježavanje svaka 2 min)",
                     (hpulse.describe(sf) or f"{len(pl)} očitanja") + (f" · holderi {hold[-1]['holders']}" if hold else "")))
        b.append(tdesc("Očitanja za token koji je stigao do razine 1: ostaje u svakom skenu dok god je zanimljiv, pa su ocjena "
                       "i snaga svježi. Najnovije prvo; holderi iz Heliusa svakih 30 min ili s pump.fun ploče.")
                 + table(["Vrijeme", ("Mcap", "n"), ("Vol 5 min", "n"), ("Vol 1 h", "n"), ("Kupnje 1 h", "n"), ("Prodaje 1 h", "n"),
                          ("Holderi (puls)", "n")],
                         [[ts(x["ts"]), usd(x["mcap"]), usd(x["vol_m5"]), usd(x["vol_h1"]), num(x["buys_h1"]), num(x["sells_h1"]),
                           (f"{x['holders']} <span class=mut>{esc(x['holders_src'] or '')}</span>", x["holders"], "n") if x["holders"] else num(None)]
                          for x in pl[::-1][:48]]))
        b.append("</details>")

    # wallets on this token
    sg = data.sightings(token=mint)
    b.append(sec("walleti", "5. Walleti viđeni na ovom tokenu", f"{len(sg)} iz registra"))
    wmap = {w["wallet"]: w for w in data.wallets(scored_only=False)}
    b.append(tdesc('Walleti iz registra koji su kupovali ovaj token, s ulogom (rani kupac, top trader…) i ocjenom.') + table(["Wallet", "Uloga", "Izvor", ("SOL", "n"), ("Copy", "n"), "Tier", "Oznake"],
                   [[wlink(x["wallet"]), esc(ROLE.get(x["role"], (x["role"],))[0]), esc(SOURCE.get(x["source"], x["source"])),
                     num(x["sol_in"], "{:.2f}"), num((wmap.get(x["wallet"]) or {}).get("copy_score")),
                     tierb((wmap.get(x["wallet"]) or {}).get("tier")),
                     " ".join(badge(l, "bad") for l in (wmap.get(x["wallet"]) or {}).get("labels", []))] for x in sg],
                   empty="Nijedan wallet nije zabilježen za ovaj token."))
    b.append("</details>")
    if natj:
        b.append("<h2>Natjecanje</h2>" + natj)
    return sym or short(mint), "".join(b)


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
