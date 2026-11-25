"""Email-safe HTML: tables and inline styles only (Gmail/Outlook drop <style>, SVG and scripts), charts are
table-cell bars. Every section links to the dashboard page with the details."""
import html
import os
import sys
import time

from .collect import NAMES, SESSIONS

INK, MUT, LINE, BG = "#111827", "#6b7280", "#e5e7eb", "#f6f7f9"
GOOD, BAD, ACC = "#15803d", "#b91c1c", "#4338ca"
SESS_COLOR = {"asia": "#d97706", "eu": "#2563eb", "us": "#7c3aed"}
FONT = "font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif"


def base_url():
    return (os.environ.get("REPORT_BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL")
            or "https://crypto-bot-ylvn.onrender.com").rstrip("/")


def e(x):
    return html.escape("" if x is None else str(x))


def link(path, text):
    return f'<a href="{base_url()}{path}" style="color:{ACC};text-decoration:none">{text}</a>'


def pct(x, signed=False):
    if x is None:
        return "–"
    return f"{x:+.0%}" if signed else f"{x:.0%}"


def money(x):
    if x is None:
        return "–"
    a = abs(x)
    s = f"${a / 1e6:.1f}M" if a >= 1e6 else f"${a / 1e3:.0f}k" if a >= 1e3 else f"${a:.0f}"
    return ("-" if x < 0 else "") + s


def mult(x):
    return "–" if x is None else f"{x:.1f}x" if x < 10 else f"{x:.0f}x"


def hbar(frac, color=ACC, width=110):
    frac = max(0.0, min(1.0, frac or 0))
    w = max(1, int(width * frac))
    return (f'<table cellpadding=0 cellspacing=0 style="border-collapse:collapse"><tr>'
            f'<td style="width:{w}px;height:8px;background:{color};border-radius:4px;font-size:0;line-height:0">&nbsp;</td>'
            f'<td style="width:{width - w}px;height:8px;background:{LINE};font-size:0;line-height:0">&nbsp;</td></tr></table>')


def stacked(shares, width=120):
    if not shares:
        return f'<span style="color:{MUT}">nema svijeća</span>'
    cells = ""
    for s, _, _ in SESSIONS:
        w = int(width * (shares.get(s) or 0))
        if w > 0:
            cells += (f'<td title="{NAMES[s]} {shares[s]:.0%}" style="width:{w}px;height:10px;background:{SESS_COLOR[s]};'
                      f'font-size:0;line-height:0">&nbsp;</td>')
    return f'<table cellpadding=0 cellspacing=0 style="border-collapse:collapse"><tr>{cells}</tr></table>'


def spark(vals, color=GOOD, h=26, w=4):
    vals = [v for v in vals if v is not None]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1
    cells = "".join(
        f'<td valign=bottom style="padding:0 1px 0 0"><div style="width:{w}px;height:{max(2, int(2 + (h - 2) * (v - lo) / rng))}px;'
        f'background:{color};font-size:0;line-height:0">&nbsp;</div></td>' for v in vals)
    return f'<table cellpadding=0 cellspacing=0 style="border-collapse:collapse;height:{h}px"><tr>{cells}</tr></table>'


def vbars(items, h=60):
    """[(label, value)] signed column chart (green up, red down)."""
    if not items:
        return ""
    mx = max(abs(v) for _, v in items) or 1
    top, bottom, labels = "", "", ""
    for lab, v in items:
        bh = max(2, int(h * abs(v) / mx))
        col = GOOD if v >= 0 else BAD
        bar = f'<div style="width:26px;height:{bh}px;background:{col};margin:0 auto;font-size:0;line-height:0">&nbsp;</div>'
        top += f'<td valign=bottom style="height:{h}px;padding:0 4px">{bar if v >= 0 else ""}</td>'
        bottom += f'<td valign=top style="height:{h // 2}px;padding:0 4px">{bar if v < 0 else ""}</td>'
        labels += (f'<td style="font-size:11px;color:{MUT};text-align:center;padding:2px 4px">{e(lab)}<br>'
                   f'<b style="color:{col}">{money(v)}</b></td>')
    return (f'<table cellpadding=0 cellspacing=0 style="border-collapse:collapse"><tr>{top}</tr>'
            f'<tr><td colspan={len(items)} style="border-top:1px solid {LINE};font-size:0;height:1px">&nbsp;</td></tr>'
            f'<tr>{bottom}</tr><tr>{labels}</tr></table>')


def table(headers, rows):
    th = "".join(f'<th align="left" style="font-size:11px;color:{MUT};font-weight:600;padding:6px 8px;'
                 f'border-bottom:1px solid {LINE};text-transform:uppercase;letter-spacing:.03em">{h}</th>' for h in headers)
    trs = "".join("<tr>" + "".join(f'<td style="font-size:13px;padding:6px 8px;border-bottom:1px solid {LINE};'
                                   f'vertical-align:middle">{c}</td>' for c in r) + "</tr>" for r in rows)
    return f'<table width="100%" cellpadding=0 cellspacing=0 style="border-collapse:collapse"><tr>{th}</tr>{trs}</table>'


def bullets(items):
    if not items:
        return ""
    lis = "".join(f'<li style="margin:0 0 6px">{e(x)}</li>' for x in items)
    return f'<ul style="margin:8px 0 4px;padding-left:20px;font-size:14px;line-height:1.5">{lis}</ul>'


def para(text):
    return f'<p style="margin:6px 0 10px;font-size:14px;line-height:1.5">{e(text)}</p>' if text else ""


def section(title, body, more=None):
    m = f'<div style="margin-top:10px;font-size:13px">{link(*more)} →</div>' if more else ""
    return (f'<tr><td style="background:#fff;border:1px solid {LINE};border-radius:10px;padding:14px 12px">'
            f'<div style="font-size:16px;font-weight:700;margin-bottom:6px">{title}</div>{body}{m}</td></tr>'
            f'<tr><td style="height:12px;font-size:0">&nbsp;</td></tr>')


def kpi(label, value, sub="", color=INK):
    return (f'<td width="25%" style="padding:10px 12px;background:#fff;border:1px solid {LINE};border-radius:10px">'
            f'<div style="font-size:11px;color:{MUT};text-transform:uppercase;letter-spacing:.03em">{label}</div>'
            f'<div style="font-size:20px;font-weight:700;color:{color};margin-top:2px">{value}</div>'
            f'<div style="font-size:11px;color:{MUT}">{sub}</div></td>')


def tlink(mint, sym):
    return link(f"/token/{e(mint)}", e(sym or (mint or "")[:6]))


RULE_HR = {"intra": "dnevni raspon", "range": "raspon 7 d"}
RULE_SHORT = {"intra": "dnevni", "range": "7 d"}
ACC_HR = {"demo": "Demo", "pravi": "Pravi"}
REGIME_HR = {"risk_on": "risk-on (tržište raste)", "neutral": "neutralno", "risk_off": "risk-off (bez novih ulaza)"}
BTC_HR = {"slobodan_pad": "slobodan pad", "dno_se_potvrduje": "dno se potvrđuje", "normalno": "normalno"}


def small(t):
    return f'<span style="font-size:11px;color:{MUT}">{t}</span>'


def colored(x, txt):
    c = GOOD if (x or 0) > 0 else BAD if (x or 0) < 0 else INK
    return f'<span style="color:{c}">{txt}</span>'


def usd(x, signed=True):
    return "–" if x is None else (f"{x:+,.2f} $" if signed else f"{x:,.2f} $")


def sol(x, d=3, signed=True):
    return "–" if x is None else (f"{x:+.{d}f} SOL" if signed else f"{x:.{d}f} SOL")


def pp(x, d=1):
    """A percentage already in % (EV / the price move), signed."""
    return "–" if x is None else f"{x:+.{d}f} %"


def hr(x):
    """A plain number the Croatian way (0,1)."""
    return "–" if x is None else f"{x:g}".replace(".", ",")


def ci_txt(ci):
    return "–" if not ci or ci[0] is None else f"{ci[0]:+.1f} … {ci[1]:+.1f} %"


def ctable(headers, rows, nowrap=False):
    """A compact table for the phone: 12px, tight padding, the first column left, the rest right (nowrap: the number
    columns never break inside a value)."""
    nw = "white-space:nowrap;" if nowrap else ""
    th = "".join(f'<th align="{"left" if i == 0 else "right"}" style="font-size:10px;color:{MUT};font-weight:600;'
                 f'padding:5px 4px;border-bottom:1px solid {LINE};text-transform:uppercase;letter-spacing:.02em;'
                 f'line-height:1.25">{h}</th>' for i, h in enumerate(headers))
    trs = "".join("<tr>" + "".join(
        f'<td align="{"left" if i == 0 else "right"}" style="font-size:12px;padding:5px 4px;border-bottom:1px solid '
        f'{LINE};vertical-align:top;line-height:1.35;{nw if i else ""}">{c}</td>' for i, c in enumerate(r)) + "</tr>"
        for r in rows)
    return f'<table width="100%" cellpadding=0 cellspacing=0 style="border-collapse:collapse"><tr>{th}</tr>{trs}</table>'


def sub(title):
    return f'<div style="font-size:13px;font-weight:600;margin:12px 0 2px">{title}</div>'


def trading_table(t, key):
    """Per account x rule (columns) the window's numbers (rows): yesterday or 7 days."""
    rows = t.get("rows") or []
    heads = [""] + [f'{ACC_HR[r["racun"]]}<br>{RULE_SHORT[r["pravilo"]]}' for r in rows]

    def chain(r):
        c = (r.get("lanac") or {}).get(key)
        if r["racun"] != "pravi":
            return small("demo")
        if c is None:
            return small("nepoznato")
        return f'{c["kupljeno"]} / {c["odbijeno"]}' + (small(f'<br>{c["bez_zapisa"]} bez naloga') if c.get("bez_zapisa") else "")

    lines = (("Ulaza", lambda r: str(r[key]["ulaza"])),
             ("Zatvoreno", lambda r: str(r[key]["zatvoreno"])),
             ("Neto", lambda r: colored(r[key]["pnl_usd"], usd(r[key]["pnl_usd"])) + "<br>"
              + small(sol(r[key]["pnl_sol"]))),
             ("Pogodak", lambda r: pct(r[key]["pogodak"])),
             ("Do cilja", lambda r: str(r[key]["cilj"])),
             ("Break-even", lambda r: str(r[key]["be"])),
             ("TP cijeli / pola", lambda r: f'{r[key]["tp_cijeli"]} / {r[key]["tp_pola"]}'),
             ("Stop", lambda r: str(r[key]["stop"])),
             ("Na lancu: kupljeno / odbijeno", chain))
    return ctable(heads, [[lab] + [f(r) for r in rows] for lab, f in lines], nowrap=True)


def open_table(op):
    rows = []
    for x in op:
        tail = [f'{ACC_HR[x["racun"]].lower()} · {RULE_SHORT[x["pravilo"]]}', f'ulaz {x["ulaz"]:.6g}',
                f'{x["sati"]:g} h']
        if x.get("pola"):
            tail.append("pola prodano")
        if x.get("be"):
            tail.append("stop na BE")
        if x.get("lanac") in ("blocked", "failed", "bez naloga"):
            tail.append("na lancu odbijeno: samo u knjizi")
        rows.append([tlink(x["token"], x["symbol"]) + "<br>" + small(" · ".join(tail)),
                     colored(x.get("sada_pct"), pp(x.get("sada_pct"))), pp(x.get("stop_pct")), pp(x.get("cilj_pct"))])
    return ctable(["Pozicija", "Sada", "Stop", "Cilj"], rows, nowrap=True)


def regime_items(rows):
    out = []
    for r in rows or []:
        ci = f", interval 90 % {r['ci'][0]:+.1f} do {r['ci'][1]:+.1f} %" if r.get("ci") else ""
        ev = f"prosjek {r['ev']:+.1f} % po tradeu{ci}" if r.get("ev") is not None else "bez prosjeka"
        out.append(f"{'Demo' if r['racun'] == 'demo' else 'Pravi'}, {REGIME_HR.get(r['rezim'], r['rezim'])}: "
                   f"{r['n']} zatvorenih, {ev}, zbroj {r['zbroj']:+.2f} $.")
    return out


def rules_items(pr):
    if not pr or pr.get("greska"):
        return ["Pravila: veliki/ se ne može pročitati" + (f" ({pr['greska']})" if pr else "") + "."]
    out = []
    for rk in ("intra", "range"):
        r = pr.get(rk) or {}
        src = (r.get("izvor") or "").replace("0.1 SOL", "0,1 SOL")
        if r.get("n") is None:
            ho = f"{src}: još nema izračuna"
        else:
            ho = (f"{src}: n {r['n']}, EV {pp(r.get('ev_pct'), 2)} po tradeu (95 % interval po danu "
                  f"{ci_txt(r.get('ci'))}), pogodak {pct(r.get('hit'))}")
        real = "DA" if r.get("pravi") else "NE"
        why = r.get("pravi_zasto")
        out.append(f"{RULE_HR[rk].capitalize()}: {ho}. Pravi novac: {real}" + (f" ({why})" if why else "") + ".")
    mode = {"walk": "walk-forward holdout", "demo": "demo dokaz", "nalog_vlasnika": "nalog vlasnika (bez čekanja dokaza)"}
    out.append(f"Prekidač pravi_novac_veliki: {'uključen' if pr.get('prekidac') else 'isključen'}; dokaz: "
               f"{mode.get(pr.get('nacin'), pr.get('nacin') or '?')}.")
    return out


def replay_block(rp):
    """16.11. (veliki/replay.py): the intraday rule's historical test on every midcap: the verdict in one sentence, a
    small table, what would be worth changing, the known biases. "" before its first run."""
    if not rp:
        return ""
    rows = []
    for r in rp.get("redovi") or []:
        if r.get("malo"):
            rows.append([e(r["naziv"]), str(r.get("n") or 0), small("premalo podataka"), "–", "–", "–"])
            continue
        rows.append([e(r["naziv"]), str(r["n"]), colored(r.get("ev_pct"), pp(r.get("ev_pct"), 2)), ci_txt(r.get("ci")),
                     pct(r.get("pogodak")), colored(r.get("zbroj_sol"), sol(r.get("zbroj_sol"), 2))])
    body = sub("Dnevni raspon: povijesni test na svim midcapovima") + para(rp.get("presuda"))
    body += ctable(["", "Tradeova", "Prosjek po tradeu", "90 % interval", "Pogodak", "Zbroj"], rows, nowrap=True)
    full = next((r for r in rp.get("redovi") or [] if not r.get("malo")), None)
    body += small(f"{rp.get('tokena')} tokena, {rp.get('dana')} dana svijeća od 15 minuta, ulog {hr(rp.get('ulog_sol'))} "
                  f"SOL, sve nakon troška kruga od {hr(rp.get('trosak_pct'))} %. Izvan uzorka = zadnjih "
                  f"{rp.get('dana_izvan')} dana, koje odabir varijante nije vidio."
                  + (f" Svi dani: pozicija se tipično drži {hr(full.get('drzanje_h'))} h, najdublji pad zbroja "
                     f"{sol(full.get('max_pad_sol'), 2)}." if full and full["naziv"] == "Svi dani" else ""))
    if rp.get("nalazi"):
        more = (rp.get("nalaza") or 0) - len(rp["nalazi"])
        body += sub("Što bi vrijedilo promijeniti") + bullets(rp["nalazi"] + ([f"I još {more} slabijih nalaza."]
                                                                             if more > 0 else []))
    else:
        body += para("Nijedna skupina tradeova nema dovoljno jasan rezultat za promjenu pravila.")
    body += sub("Kako čitati i gdje test griješi") + bullets((rp.get("napomene") or []) + (rp.get("pristranosti") or []))
    return body


def kopija_block(k):
    """16.11. (wallets/kopija.py): what WE would have earned copying the proven wallets: the verdict in one sentence, a
    small table, the gap between the wallet's own return and ours, the demo copies, what is stale. "" before its first
    run."""
    if not k or not (k.get("presuda") or k.get("demo")):
        return ""

    def trow(r):
        if r.get("malo"):
            return [e(r["naziv"]), str(r.get("n") or 0), small("premalo podataka"), "–", "–", "–"]
        return [e(r["naziv"]), str(r["n"]), colored(r.get("ev_pct"), pp(r.get("ev_pct"), 2)), ci_txt(r.get("ci")),
                pct(r.get("pogodak")), colored(r.get("zbroj_sol"), sol(r.get("zbroj_sol"), 2))]
    body = sub("Kopiranje dokazanih novčanika: koliko bismo zaradili mi")
    if k.get("presuda"):
        body += para(k["presuda"])
        if k.get("redovi"):
            body += ctable(["", "Kopija", "Prosjek po tradeu", "90 % interval", "Pogodak", "Zbroj"],
                           [trow(r) for r in k["redovi"]])
            body += small(f"Novčanici su odabrani na starijem dijelu podataka, a mjereno je samo na zadnjih "
                          f"{k.get('dana_izvan')} dana koje odabir nije vidio. Ulog {hr(k.get('ulog_sol'))} SOL, sve nakon "
                          "kašnjenja i troška kupnje i prodaje.")
        if k.get("razlika"):
            body += sub("Zašto je novčanik u plusu, a kopija nije ista") + bullets(k["razlika"])
        if k.get("skupine"):
            body += sub("Po veličini tokena, likvidnosti i načinu trgovanja novčanika (glavno pravilo)")
            body += ctable(["", "Kopija", "Prosjek po tradeu", "90 % interval", "Pogodak", "Zbroj"],
                           [trow(r) for r in k["skupine"]])
    d = k.get("demo")
    if d:
        items = [f"Demo kopije (od 16.11., i ispod 5M $): zatvoreno {d['n']}, otvoreno {d['otvoreno']}"
                 + (f", prosjek po kopiji {pp(d['ev_pct'], 2)} nakon troška" if d.get("ev_pct") is not None else "")
                 + (f" (interval 90 %: {ci_txt(d['ci'])})" if d.get("ci") else "") + "."]
        if d.get("kasnjenje_med_s") is not None:
            items.append(f"Naš ulaz tipično {d['kasnjenje_med_s']:.0f} s nakon njegove kupnje"
                         + (f"; naša cijena tipično {pp(d['ulaz_med_pct'], 1)} prema njegovoj (poznato za "
                            f"{d['ulaz_n']} kopija)" if d.get("ulaz_n") else "; njegova cijena još nije poznata ni za "
                            "jednu kopiju") + ".")
        if d.get("usporedba_n"):
            items.append(f"Na {d['usporedba_n']} zatvorenih kopija s poznatim njegovim cijenama: on {pp(d['njegov_pct'], 1)}, "
                         f"mi {pp(d['nas_pct'], 1)}.")
        if d.get("zastavica") != "paper":
            items.append("Zastavica kopija_dokazani nije u paper modu: demo ne otvara nove kopije.")
        body += sub("Demo kopije (mjerenje unaprijed)") + bullets(items)
        body += small(f"Samo demo račun: {hr(d.get('ulog_sol'))} SOL po kopiji, najviše {d.get('max_otvorenih')} otvorenih i "
                      f"{d.get('dnevno')} dnevno, jedna pozicija po tokenu, izlaz: {e(k.get('demo_izlaz') or 'njegov izlaz ili stop −20 %')}. "
                      "Pravi novac i njegova pravila nisu dirani.")
    if k.get("svjezina"):
        body += sub("Što je zastarjelo i što bi koštalo osvježavanje") + bullets(k["svjezina"])
    if k.get("napomene") or k.get("pristranosti"):
        body += sub("Kako čitati i gdje test griješi") + bullets((k.get("napomene") or []) + (k.get("pristranosti") or []))
    return body


def wallet_items(w):
    out = []
    if w.get("value_sol") is not None:
        out.append(f"Novčanik: {sol(w['value_sol'], signed=False)}"
                   + (f" ({w['value_usd']:,.0f} $)" if w.get("value_usd") else "")
                   + f", promjena 24 h {sol(w.get('pnl_24h_sol'))}, ukupni PnL {sol(w.get('pnl_sol'))}.")
    else:
        out.append("Novčanik: još nema snimke vrijednosti (trade/equity).")
    if w.get("pod_sol") is not None:
        if w.get("pod_ok") is None:
            out.append(f"Pod {hr(w['pod_sol'])} SOL: vrijednost nepoznata.")
        else:
            out.append(f"Pod {hr(w['pod_sol'])} SOL: " + ("iznad" if w["pod_ok"] else "ISPOD, automatske prave kupnje stoje")
                       + f" ({sol(w.get('vrijednost'), signed=False)}, {w.get('izvor')}).")
    c = w.get("stropovi") or {}
    if c:
        out.append(f"Stropovi pravog novca (midcap): {hr(c.get('size_sol'))} SOL po tradeu, {c.get('max_open')} "
                   f"otvorenih, {c.get('max_buys_day')} kupnji dnevno, dnevni gubitak {hr(c.get('max_loss_day_sol'))} SOL "
                   f"(danas {sol(w.get('dan_pravi_sol'))} na {w.get('dan_pravi_n', 0)} zatvorenih).")
    return out


def market_items(m, mi=None):
    out = []
    b = (m or {}).get("btc") or {}
    if b and not b.get("poznato"):
        out.append("BTC: cijena po satu nepoznata (veliki.db / market.db); pravi novac tada ne kupuje.")
    elif b:
        out.append(f"BTC: {BTC_HR.get(b.get('stanje'), b.get('stanje') or '?')}"
                   + (f" ({b['zasto']})" if b.get("zasto") else "")
                   + (f", 24 h {b['chg24'] * 100:+.1f} %" if b.get("chg24") is not None else "") + ".")
    mk = (m or {}).get("makro")
    if mk:
        pl = ", ".join(f"{k} {v * 100:+.0f} %" for k, v in (mk.get("platforme") or {}).items() if v is not None)
        out.append(f"Makro režim: {REGIME_HR.get(mk.get('rezim'), mk.get('rezim') or '?')} ({mk.get('zasto')}). Volumen "
                   f"prema prosjeku 7 d: meme platforme {pct(mk.get('meme_chg'), True)}"
                   + (f" ({pl})" if pl else "")
                   + (f"; Solana meme sektor {mk['sektor_chg24']:+.1f} % u 24 h" if mk.get("sektor_chg24") is not None
                      else "")
                   + (f"; midcapovi {pct(mk.get('midcap_chg'), True)}" if mk.get("midcap_chg") is not None else "") + ".")
        op = mk.get("oporavak")
        if op and op.get("zasto"):
            out.append(("Oporavak: DA" if op.get("da") else "Oporavak: ne") + f" ({op['zasto']})."
                       + (" Kandidati idu redom po odzivu na rast BTC-a; ulaz ostaje samo na dnu raspona."
                          if op.get("da") else ""))
        out.append("Izlaz danas: " + ("pola na cilju, ostatak trailing (tržište raste: " if mk.get("bull")
                                      else "cijeli profit na cilju (") + f"{mk.get('bull_zasto')}).")
    else:
        out.append("Makro režim: nema svježe snimke (midcap.db makro_h); veliki ga tretira kao neutralno.")
    if mi:
        from makroinf import report as mireport
        out.append(mireport.morning_text(mi))
    sv = (m or {}).get("svemir") or {}
    if sv:
        out.append(f"Midcap svemir: {sv.get('clanova', 0)} tokena (2M–200M), od toga {sv.get('trending', 0)} trending; "
                   f"velika lista (raspon 7 d, pravi novac): {sv.get('lista', 0)}.")
    for key, word in (("gore", "Najviše gore 24 h"), ("dolje", "Najviše dolje 24 h")):
        xs = (m or {}).get(key) or []
        if xs:
            out.append(f"{word}: " + ", ".join(f"{x['symbol']} {x['chg24']:+.0f} % (MC {money(x.get('mcap'))})"
                                              for x in xs) + ".")
    return out


def research_items(i2, hd):
    out = []
    if i2:
        w, dm = i2.get("wf") or {}, i2.get("demo") or {}
        line = (f"Insajderi 2.0 (zastavica {i2.get('zastavica') or '?'}): odluka "
                f"{'kopirati u demu' if i2.get('kopirati') else 'ne kopirati'}"
                + (f" — {i2['odluka']}" if i2.get("odluka") else "")
                + f". Događaja {i2.get('dogadaja') or 0}, potvrđenih grupa {i2.get('potvrdenih') or 0}; kopiranje MC ≥ 5M "
                f"walk-forward n {w.get('n') or 0}, EV {pp(w.get('ev_pct'))}.")
        if dm:
            line += (f" Demo: {dm.get('n', 0)} zatvorenih, EV {pp(dm.get('ev_pct'))} (90 % {ci_txt(dm.get('ci'))}), "
                     f"PnL {usd(dm.get('pnl_usd'))}, otvoreno {dm.get('otvoreno', 0)}.")
        out.append(line)
    else:
        out.append("Insajderi 2.0: još nema prolaza ni demo tradeova.")
    if hd:
        nv = hd.get("novi_24h") or {}
        tops = ", ".join(f"{x['symbol']} → {x['burza']} ({x['score']:.0f})" for x in hd.get("top") or [])
        line = (f"Holderi i listing (24 h): prije listinga {nv.get('pre_listing', 0)}, depozit na burzu "
                f"{nv.get('deposit_sell', 0)}" + (f"; najjači {tops}" if tops else "") + ".")
        mj = []
        for k, x in (hd.get("mjerenje") or {}).items():
            if x.get("n"):
                from report.midcap import KIND_HR
                mj.append(f"{KIND_HR.get(k, k)} n {x['n']}, prosjek 24 h {pp(x.get('ev_pct'))}"
                          + (f" (kontrola {pp(x.get('kontrola_pct'))})" if x.get("kontrola_pct") is not None else ""))
        out.append(line + (" Izmjereno: " + "; ".join(mj) + "." if mj else " Izmjerenih ishoda još nema."))
    else:
        out.append("Holderi i listing: još nema signala.")
    return out


def kriticar_short(k):
    """The critic in the midcap report: its newest review (first paragraph), up to 3 findings, one line of record
    and cost. The full table stays on the page."""
    if not k:
        return para("Kritičar još nema pregleda.")
    body = ""
    sm = k.get("sazetak")
    if sm:
        body += f'<div style="font-size:13px;font-weight:600;margin:4px 0 2px">{e(sm.get("title"))}</div>'
        body += para((sm.get("text") or "").split("\n\n")[0])
    if k.get("nalazi"):
        body += bullets([f"{x['title']}: {x['text']}" + (f" Prijedlog: {x['prijedlog']}" if x.get("prijedlog") else "")
                         for x in k["nalazi"][:3]])
    pv = k.get("presude") or {}
    rec = "; ".join(f"{CRITIC_WORDS.get(v, v)} {d['n']} (u pravu na zatvaranju {pct(d.get('pogodak_zatvaranje'))})"
                    for v, d in sorted(pv.items(), key=lambda kv: -kv[1]["n"])[:4])
    j, m, b = k.get("jucer") or {}, k.get("mjesec") or {}, k.get("budzet") or {}
    body += para((f"Presude 7 dana: {rec}. " if rec else "")
                 + f"Trošak: jučer {j.get('poziva', 0)} poziva, ${j.get('usd', 0):.3f}; ovaj mjesec ${m.get('usd', 0):.2f}"
                 + (f" od ${b.get('mjesec_strop', 0):.0f}." if b.get("mjesec_strop") else "."))
    return body


def _n(x):
    return f"{int(x or 0):,}".replace(",", ".")


def costs_rows(c):
    """[(source, yesterday)] of usage/daily's saved row."""
    rows = []
    cg = c.get("coingecko") or {}
    if cg:
        rows.append(("CoinGecko / GeckoTerminal", f"ključem {_n(cg.get('kljuc'))} od {_n(cg.get('strop'))}, besplatno "
                                                  f"{_n(cg.get('besplatno_ukupno'))}, HTTP 429: {_n(cg.get('e429_ukupno'))}"))
    tw = c.get("twitterapi") or {}
    if tw:
        rows.append(("X (twitterapi.io)", f"{tw.get('usd') or 0:.2f} $"))
    ap = c.get("apify") or {}
    if ap:
        rows.append(("Apify", f"{ap.get('usd_bot') or 0:.2f} $"))
    pp_ = c.get("pumpportal") or {}
    if pp_:
        rows.append(("PumpPortal", f"{_n(pp_.get('tradeova'))} tradeova ≈ {pp_.get('sol') or 0:.3f} SOL"))
    he = c.get("helius") or {}
    if he:
        acc = he.get("racun") or {}
        rows.append(("Helius", f"{_n(he.get('krediti_bot'))} kredita"
                     + (f" (račun +{(acc.get('dan') or 0) / 1e3:,.0f}k)" if acc.get("dan") is not None else "")))
    ai_ = c.get("ai") or {}
    if ai_:
        rows.append(("AI oznake (Claude)", f"{ai_.get('usd') or 0:.2f} $, {_n(ai_.get('objava'))} objava"))
    oa = c.get("openai") or {}
    if oa:
        dec = oa.get("odluke_vlasnika") or {}
        rows.append(("OpenAI kritičar", f"{oa.get('usd') or 0:.2f} $, {_n(oa.get('poziva'))} poziva, "
                                        f"{_n(oa.get('presuda'))} presuda"
                     + (", odluke vlasnika: " + ", ".join(f"{k} {v}" for k, v in dec.items()) if dec else "")))
    errs = [k for k, v in c.items() if isinstance(v, dict) and v.get("greska")]
    if errs:
        rows.append(("Nije izmjereno", ", ".join(errs)))
    return rows


def mikrokap_line(mk):
    if not mk:
        return ("Mikrokap strategije pauzirane od 15.11. (fokus midcap); konačni rezultat: nema zapisa usporedbe "
                "strategija.")
    return (f"Mikrokap strategije pauzirane od {mk.get('od') or '15.11.'} (fokus midcap); konačni rezultat: "
            f"{mk['racuna']} demo računa, {_n(mk['zatvoreno'])} zatvorenih tradeova, ukupno {money(mk['pnl_usd'])} "
            f"(najbolji {mk['najbolji']['name']} {mk['najbolji']['ret']:+.1%}, najslabiji {mk['najgori']['name']} "
            f"{mk['najgori']['ret']:+.1%})"
            + (f"; još otvoreno {mk['otvoreno']}, zatvaraju se svojim izlazima." if mk.get("otvoreno") else "."))


def _sum(t, acc, key, f):
    return sum((r[key] or {}).get(f) or 0 for r in (t or {}).get("rows") or [] if r["racun"] == acc)


def mkpi(label, value, sub="", color=INK):
    """kpi() for the phone: four of them fit 390 px (smaller number, tighter padding)."""
    return (f'<td width="25%" valign="top" style="padding:7px 5px;background:#fff;border:1px solid {LINE};border-radius:10px">'
            f'<div style="font-size:10px;color:{MUT};text-transform:uppercase;letter-spacing:.03em">{label}</div>'
            f'<div style="font-size:16px;font-weight:700;color:{color};margin-top:2px;white-space:nowrap">{value}</div>'
            f'<div style="font-size:10px;color:{MUT};line-height:1.3">{sub}</div></td>')


def kusd(x):
    return f"{x:+.0f} $" if abs(x) >= 10 else f"{x:+.2f} $"


def midcap_kpis(m):
    t, w, mk = m.get("trgovanje") or {}, m.get("novcanik") or {}, (m.get("trziste") or {}).get("makro") or {}
    dz = _sum(t, "demo", "jucer", "zatvoreno")
    dp = _sum(t, "demo", "jucer", "pnl_usd")
    rz = _sum(t, "pravi", "jucer", "zatvoreno")
    rp = _sum(t, "pravi", "jucer", "pnl_sol")
    btc = ((m.get("trziste") or {}).get("btc") or {}).get("stanje")
    reg = mk.get("rezim")
    rc = {"risk_on": GOOD, "risk_off": BAD}.get(reg, INK)
    return "".join([
        mkpi("Demo jučer", kusd(dp) if t else "–", f"{dz} zatvorenih", GOOD if dp > 0 else BAD if dp < 0 else INK),
        "<td width=3></td>",
        mkpi("Pravi jučer", f"{rp:+.3f}" if t else "–", f"SOL · {rz} zatvorenih", GOOD if rp > 0 else BAD if rp < 0 else INK),
        "<td width=3></td>",
        mkpi("Novčanik", f"{w['value_sol']:.2f}" if w.get("value_sol") is not None else "–",
            f"SOL · 24 h {w['pnl_24h_sol']:+.3f}" if w.get("pnl_24h_sol") is not None else "SOL"),
        "<td width=3></td>",
        mkpi("Makro", {"risk_on": "risk-on", "risk_off": "risk-off", "neutral": "neutralno"}.get(reg, "–"),
            f"BTC {BTC_HR.get(btc, btc or '?')}", rc),
    ])


def midcap_sections(data, ai):
    """The midcap report (16.11.): trading, market, research, costs, the paused microcap line."""
    m = data.get("midcap") or {}
    out = []
    t = m.get("trgovanje")
    body = bullets(ai.get("trgovanje"))
    if t:
        body += sub(f"Jučer ({t['jucer']['dan']})") + trading_table(t, "jucer")
        body += sub("Zadnjih 7 dana") + trading_table(t, "7d")
        body += small("Neto = nakon pravog troška (pool, ruta, mreža, utjecaj). Do cilja = cilj dodirnut (cijeli TP ili "
                      "pola na cilju). Break-even = stop pomaknut na ulaz na +5 % neto pa pogođen.")
        op = t.get("otvoreno") or []
        body += sub(f"Otvorene pozicije ({t.get('otvoreno_n', len(op))})")
        body += open_table(op) + small("Sada / stop / cilj: cijena prema ulaznoj, bez troška.") if op else \
            para("Nema otvorenih midcap pozicija.")
    else:
        body += para("Još nema midcap tradeova (league.db veliki_trades).")
    rz = regime_items((t or {}).get("po_rezimu"))
    if rz:
        body += sub("Rezultat po makro režimu ulaza (zatvoreno u 7 d)") + bullets(rz) + small(
            "Režim se bilježi na ulazu od 16.11.; raniji tradeovi su „bez oznake”. Raspoloženje influencera je samo "
            "oznaka, ne uvjet.")
    body += sub("Pravila: dokaz izvan uzorka i pravi novac") + bullets(rules_items(m.get("pravila")))
    body += replay_block(m.get("replay"))
    body += kopija_block(m.get("kopija"))
    body += sub("Novčanik i stropovi") + bullets(wallet_items(m.get("novcanik") or {}))
    out.append(section("Midcap trgovanje", body, ("/strategije", "Usporedba midcap strategija")))
    body = para(ai.get("trziste")) + bullets(market_items(m.get("trziste"), data.get("makroinf")))
    out.append(section("Tržište", body, ("/kol-makro", "Makro influenceri")))
    body = para(ai.get("istrazivanje")) + bullets(research_items(m.get("insajderi2"), m.get("holderi")))
    body += sub("Kritičar (OpenAI)") + kriticar_short(data.get("kriticar"))
    out.append(section("Istraživanje", body))
    c = m.get("troskovi")
    body = para(ai.get("troskovi"))
    if c:
        body += sub(f"Jučer ({e(c.get('day'))}, UTC dan, brojke bota)") + ctable(["Izvor", "Jučer"],
                                                                               [[e(a), e(b)] for a, b in costs_rows(c)])
    else:
        body += para("Još nema spremljenog dana (usage.db daily_cost se piše u 23:59 UTC).")
    tw = data.get("tjedni_trosak")
    if tw:   # 19.11. (CLAUDE.md: every week the cost per source and what of it led to a decision or a trade)
        from report import tjedni
        body += sub("Tjedni trošak po izvoru") + tjedni.html(tw, sys.modules[__name__])
    out.append(section("Troškovi po izvoru", body, ("/usage", "Potrošnja")))
    if data.get("fokus"):
        out.append(section("Mikrokap", para(mikrokap_line(m.get("mikrokap"))), ("/strategije#arhiva", "Arhiva")))
    return out


def pump_mjerenje_section(s):
    """25.11. (live/pumpmjerenje.py): jednokratno mjerenje naknade kreatoru na pump.fun, po razredima deva. Bez adresa."""
    from live import pumpmjerenje as pm
    when = time.strftime("%d.%m. %H:%M UTC", time.gmtime(s["rok"])) if s.get("rok") else "?"
    body = para(("Završni rezultat" if s.get("final") else f"Privremeno (mjerenje traje do {when})")
                + f": {s['lansiranja']} lansiranja zabilježeno, uzorak {pm._pct(s['udio'])}, ishod za "
                f"{s['s_ishodom']} tokena" + (" (samo provjera nakon 12 h)." if s.get("final") else
                                              " (zadnja dostupna provjera: 1 h ili 12 h)."))
    body += ctable(["Razred deva", "Tokena", "Medijan SOL", "Prosjek SOL", "≥5k $", "≥10k $", "≥30k $", "≥100k $",
                    "Migrirao", "Gornjih 1 %", "Nepoznat", "Bez USD"], [[e(c) for c in r] for r in pm.table_rows(s)], nowrap=True)
    body += small(
        "Naknada = promet tokena (DexScreener, od lansiranja do provjere) × 0,30 % — prema objavi, NEPROVJERENO: "
        f"službena stranica pump.funa ({e(s.get('izvor'))}) nije bila dostupna; nakon prelaska na PumpSwap stopa "
        "vjerojatno ovisi o vrijednosti tokena. Pragovi = najviša viđena vrijednost na provjerama (donja granica "
        "vrha). „Prvi token” = dev nije lansirao drugi token u 24 h prije, koliko je mjerenje vidjelo. „Nepoznat” = "
        "DexScreener ne zna token (računa se s 0 prometa). „Bez USD” = DexScreener zna token, ali za njega još ne daje promet u dolarima: "
        "izvan svih brojki u retku (samo prebrojen). Razred ispod 30 tokena: premalo. Gornjih 1 % = udio "
        f"ukupne naknade koji nose najbolji tokeni. DexScreener ~{s.get('dex_dnevno')} zahtjeva dnevno (besplatno); "
        f"baza {s.get('mb')} MB. Statistika, ne optužba.")
    return section("Mjerenje: naknada devu na pump.fun", body)


def render(data, ai, source):
    now = data["ts"]
    day = time.strftime("%d.%m.%Y.", time.localtime(now))
    out = [section("Ukratko", bullets(ai.get("ukratko")))]
    sp = data.get("spend") or []
    if sp:   # urgent only (2.11.: the banner is gone from the app; warnings live on /usage)
        out.append(section(f'<span style="color:{BAD}">Hitno: potrošnja</span>',
                           "".join(para(f"{a['title']}: {a['detail']}") for a in sp), ("/usage", "Potrošnja")))
    out += midcap_sections(data, ai)
    if data.get("pump_mjerenje"):
        out.append(pump_mjerenje_section(data["pump_mjerenje"]))
    if not data.get("fokus") and data.get("paper") is not None:   # the switch off: the microcap sections as before
        out += mikrokap_sections(data, ai)
    sg = ai.get("prijedlozi") or []
    if sg:
        col = {"visok": BAD, "srednji": "#d97706", "nizak": MUT}
        body = "".join(f'<div style="margin:8px 0 10px"><span style="font-size:11px;color:#fff;background:'
                       f'{col.get(x["prioritet"], MUT)};border-radius:4px;padding:1px 6px">{e(x["prioritet"])}</span> '
                       f'<b style="font-size:14px">{e(x["naslov"])}</b>'
                       f'<div style="font-size:13px;line-height:1.5;color:#374151;margin-top:3px">{e(x["opis"])}</div></div>'
                       for x in sg)
        out.append(section("Prijedlozi za midcap strategiju", body))
    if ai.get("upozorenja"):
        out.append(section("Upozorenja", bullets(ai["upozorenja"])))
    kpis = midcap_kpis(data.get("midcap") or {})
    src = "AI interpretacija: " + e(source) if source and not source.startswith("pravila") else \
        "Bez AI interpretacije (pravila)"
    return f"""<!DOCTYPE html><html lang="hr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Jutarnji izvještaj {day}</title></head>
<body style="margin:0;padding:0;background:{BG};{FONT};color:{INK}">
<table width="100%" cellpadding=0 cellspacing=0 style="background:{BG}"><tr><td align="center" style="padding:16px 8px">
<table width="680" cellpadding=0 cellspacing=0 style="max-width:680px;width:100%">
<tr><td style="padding:0 2px 12px"><div style="font-size:12px;color:{MUT}">MemeSonar · jutarnji izvještaj · midcap · {day}</div>
<div style="font-size:22px;font-weight:800;line-height:1.25;margin-top:4px">{e(ai.get("naslov"))}</div></td></tr>
<tr><td><table width="100%" cellpadding=0 cellspacing=0><tr>{kpis}</tr></table></td></tr>
<tr><td style="height:12px;font-size:0">&nbsp;</td></tr>
{"".join(out)}
<tr><td style="font-size:11px;color:{MUT};padding:4px 2px 20px">{src} · podaci iz baza bota, bez dodatnih plaćenih poziva ·
{link("/izvjestaj", "svi izvještaji")} · {link("/strategije", "usporedba strategija")} · {link("/", "dashboard")}</td></tr>
</table></td></tr></table></body></html>"""


def mikrokap_sections(data, ai):
    """The microcap sections of the old report (learned weights, KOLs, today's tokens, the pulse, the microcap demo,
    the KOL test, the strategy comparison, the scanner, pre-call insiders, momentum, the archive, the entry rules).
    16.11.: only while the owner switch fokus_midcap is OFF (collect.collect leaves their data out while it is on)."""
    p, k, acc, today = data["paper"], data["kols"], data["sessions"], data["today"]
    cur = today["now"]
    out = []
    # what was learned
    body = bullets(ai.get("naucio"))
    wrows, seen = [], set()
    # learning re-runs often propose the same change many times: show each change once, applied ones first
    for r in sorted(data["weights"]["runs"], key=lambda r: not r["applied"]):
        for t in r["top"][:4]:
            d = t["new"] - t["old"]
            key = (r["klasa"], t["feature"], round(t["old"], 2), round(t["new"], 2))
            if key in seen:
                continue
            seen.add(key)
            wrows.append([e(r["klasa"]), e(t["feature"]), f"{t['old']:+.2f} → <b>{t['new']:+.2f}</b>",
                          f'<span style="color:{GOOD if d > 0 else BAD}">{d:+.2f}</span>',
                          "da" if r["applied"] else f'<span style="color:{MUT}">ne</span>'])
    if wrows:
        body += '<div style="font-size:13px;font-weight:600;margin:10px 0 2px">Najveće promjene težina</div>'
        body += table(["Klasa", "Faktor", "Težina", "Pomak", "Primijenjeno"], wrows[:10])
    srows = []
    for s, a, b in SESSIONS:
        v = acc.get(s) or {}
        # the measure with the bigger sample (group signals are rare, single KOL calls are many)
        sig = max((x for x in (v.get("signal"), v.get("call")) if x), key=lambda x: x.get("n") or 0, default=None)
        name = f'<b style="color:{SESS_COLOR[s]}">{NAMES[s]}</b> <span style="color:{MUT}">{a:02d}-{b:02d} UTC</span>'
        if s == cur:
            name += f' <span style="font-size:11px;color:{GOOD}">● sada</span>'
        if sig:
            srows.append([name, hbar(sig["hit"], SESS_COLOR[s]) + f'<span style="font-size:12px">{pct(sig["hit"])}</span>',
                          f"{sig['n']}", f"×{sig['factor']:.2f}" if sig.get("factor") else "–"])
        else:
            srows.append([name, f'<span style="color:{MUT}">još nema mjerenja</span>', "0", "×1.00"])
    body += f'<div style="font-size:13px;font-weight:600;margin:12px 0 2px">Točnost KOL signala po sesiji (pogodak = {e(data.get("kol_hit_definition"))})</div>'
    body += table(["Sesija", "Pogodak", "n", "Faktor"], srows)
    ex = data["exits"]["changed"]
    if ex:
        body += '<div style="font-size:13px;font-weight:600;margin:12px 0 2px">Nova pravila izlaza</div>'
        body += table(["Profil", "Verzija", "Win", "Medijan"],
                      [[e(c["profil"]), f"v{c['v']}", pct((c["eval"] or {}).get("win")),
                        pct((c["eval"] or {}).get("median"), True)] for c in ex])
    out.append(section("Što sam naučio jučer", body, ("/learn", "Učenje i težine")))

    # KOLs
    body = para(ai.get("kol_komentar"))
    pr = ai.get("kol_pratiti") or []
    if pr:
        body += '<div style="font-size:13px;font-weight:600;margin:6px 0 2px">Prati</div>'
        body += bullets([f"@{x['handle']}: {x['zasto']}" for x in pr])
    krows = [[link(f"/kol/{e(x['handle'])}", "@" + e(x["handle"])), f"<b>{x['score']:.0f}</b>",
              hbar(x["hit_rate"], GOOD, 80) + f'<span style="font-size:12px">{pct(x["hit_rate"])} od {x["measured"]}</span>',
              mult(1 + x["med_max24"]) if x.get("med_max24") is not None else "–", pct(x.get("late")),
              f"{x['followers']:,}" if x.get("followers") else "–",
              ("★" if x["handle"] in k["watch"] else "")] for x in k["top"][:8]]
    if krows:
        body += table(["KOL", "Score", "Pogodak", "Med. max 24 h", "Kasni", "Followeri", "Live"], krows)
    bc = [c for c in k["best_calls"] if c.get("max24") or c.get("r6h")][:5]
    if bc:
        body += '<div style="font-size:13px;font-weight:600;margin:12px 0 2px">Najbolji pozivi zadnja 48 h</div>'
        body += table(["KOL", "Token", "MC na pozivu", "Max 24 h", "Post"],
                      [["@" + e(c["handle"]), tlink(c["token"], c["symbol"]), money(c["mcap0"]),
                        mult(1 + c["max24"]) if c.get("max24") is not None else pct(c.get("r6h"), True) + " (6 h)",
                        f'<a href="{e(c["url"])}" style="color:{ACC}">otvori</a>' if c.get("url") else ""] for c in bc])
    out.append(section("Influenceri (KOL)", body, ("/kol", "Svi KOL-ovi i sesije")))

    # today
    body = para(ai.get("danas_komentar"))
    ist = ai.get("danas_istaknuti") or []
    if ist:
        body += bullets([f"{x['simbol']}: {x['zasto']}" for x in ist])
    trows = [[tlink(t["token"], t["symbol"]), e(t.get("klasa") or "–"), money(t.get("mcap")),
              stacked(t["shares"]) + (f'<span style="font-size:11px;color:{SESS_COLOR[t["dominant"]]}">'
                                      f'{NAMES[t["dominant"]]}</span>' if t.get("dominant") else ""),
              f"{t['score']:.0f}" if t.get("score") is not None else "–",
              ("KOL ✓" if t.get("kol") else "")] for t in today["tokens"]]
    if trows:
        legend = " ".join(f'<span style="color:{SESS_COLOR[s]}">■ {NAMES[s]}</span>' for s, _, _ in SESSIONS)
        body += table(["Token", "Klasa", "MC", "Volumen po sesiji", "Score", ""], trows)
        body += f'<div style="font-size:11px;color:{MUT};margin-top:4px">{legend}</div>'
    else:
        body += para("Nema tokena razine 1+ u zadnja 24 h.")
    out.append(section(f"Tokeni za danas (sada: {NAMES[cur]})", body, ("/tokens", "Svi tokeni")))

    # pulse
    body = para(ai.get("puls_komentar"))
    prow = [[tlink(x["token"], x["symbol"]), spark(x["holders_series"]),
             f"{x['holders0']:,} → <b>{x['holders1']:,}</b> ({pct(x['growth'], True)})", pct(x["consistency"]),
             pct(x["vol_trend"], True), money(x.get("mcap"))] for x in data["pulse"]]
    body += table(["Token", "Holderi 24 h", "Holderi", "Sati rasta", "Volumen 2. pol.", "MC"], prow) if prow else \
        para("Još nema tokena s dovoljno mjerenja pulsa (treba 3+ sata).")
    out.append(section("Konstantan rast holdera i volumena", body, ("/tokens", "Tokeni (stupac Snaga)")))

    # demo trading
    body = vbars([(d["day"], d["pnl"]) for d in p["week"]])
    if p["best"]:
        body += '<div style="font-size:13px;font-weight:600;margin:12px 0 2px">Najbolji i najgori jučer</div>'
        body += table(["Token", "Rezultat", "Vrh", "Izlaz"],
                      [[tlink(t["token"], t["symbol"]),
                        f'<span style="color:{GOOD if (t["ret"] or 0) >= 0 else BAD}">{pct(t["ret"], True)}</span>',
                        pct(t.get("max_ret"), True), e(t.get("exit_reason"))] for t in p["best"] + p["worst"]])
    out.append(section("Demo trading (7 dana)", body or para("Još nema zatvorenih tradeova."),
                       ("/paper", "Demo trading")))

    # KOL test book (separate, measuring only)
    kt = data.get("koltest")
    if kt and kt["all"]["n"]:
        a, d = kt["all"], kt["day"]
        body = para(f"Dan {min(kt['day_n'], kt['days'])} od {kt['days']} (do kraja: {kt['left']}). Na svaki svjež KOL "
                    f"poziv demo ulaz ${kt['size']}, odvojeno od glavnog demo tradinga. Zadnja 24 h: {d['n']} ulaza, "
                    f"{d['hit20']} doseglo +20%, {d['hit50']} doseglo +50%, knjiga {money(d['pnl'])}. Ukupno: {a['n']} "
                    f"ulaza, {a['never20']} završenih nije doseglo +20% ({a.get('pending20', 0)} se još prati), knjiga {money(a['pnl'])}.")
        lv = [[f"+{r['level']:.0%}", f"{r['hit']}/{r['n']} ({pct(r['share'])})",
               f"{r['med_min']:.0f} min" if r["med_min"] is not None else "–", pct(r["med_drop"], True)]
              for r in kt["levels"] if r["level"] <= 1.0]
        body += table(["Razina", "Doseglo", "Medijan vremena", "Medijan pada prije"], lv)
        if kt.get("best"):
            g = kt["best"]
            body += para(f"Najbolji izlaz dosad: prodaj na +{g['tp']:.0%}"
                         + (" bez stopa" if g["sl"] is None else " sa stopom " + _sl_label(g["sl"]))
                         + f": prosjek {pct(g['avg'], True)} po ulazu, {g['wins']} od {g['n']} u plusu.")
        if kt.get("top"):
            body += bullets([f"{x['caller']}: {x['n']} ulaza, {x['hit20']} do +20%, knjiga {money(x['pnl'])}"
                             for x in kt["top"]])
        out.append(section("KOL test: ulaz odmah na poziv", body, ("/kol-test", "KOL test")))

    # five $1000 demo accounts, one per entry source (strat/, page /strategije)
    sg = data.get("strategije")
    if sg:
        rows = [[f"{i + 1}. {e(x['name'])}", money(x["value"] - 1000) + f" ({pct(x['ret'], True)})",
                 money(x["pnl_24h"]), f"{x['closed']} / {x['open']}",
                 pct(x["hit"]) if x["hit"] is not None else "–"] for i, x in enumerate(sg)]
        body = para("Pet demo računa po $1000, svaki kupuje iz drugog izvora, svi prodaju po istim pravilima. "
                    f"Vodi: {e(sg[0]['name'])}.")
        body += table(["Strategija", "Ukupno", "Zadnja 24 h", "Zatvoreno / otvoreno", "Uspješnost"], rows)
        out.append(section("Usporedba strategija", body, ("/strategije", "Usporedba strategija")))

    # 10.11.: the market scanner in shadow (scan/, flag market_scan): one line per signal source
    sk = data.get("skener")
    if sk and (sk.get("day") or sk.get("gate_window") or sk.get("checked_24h")):
        out.append(section("Skener tržišta: sjena po izvoru", skener_body(sk)))

    # 10.11.: pre-call insiders and launches from 10k (kol/precall.py, flag insider_copy)
    ins = data.get("insajderi")
    if ins:
        out.append(section("Insajderi prije poziva i nova lansiranja od 10k", insajderi_body(ins)))

    # 11.11.: momentum_scalp and Grok's EV gate calibration (momentum/view.lines)
    mo = data.get("momentum")
    if mo:
        from momentum import view as mview
        out.append(section("Momentum scalp i Grokova EV vrata", bullets(mview.lines(mo))))

    # 15.11. (ops/arhiva.py): last night's archive of microcap / rug rows, in one line
    ar = data.get("arhiva")
    if ar:
        out.append(section("Arhiva mikrokapova", para(arhiva_text(ar))))

    # the 1.11. entry rules and their effect
    ru = data.get("rules")
    if ru:
        sess = {"asia": "Azija", "eu": "Europa", "us": "Amerika"}
        rug = {r["label"]: r for r in ru["rug"]}
        pr, po = rug.get("prije filtra") or {}, rug.get("nakon filtra") or {}
        items = []
        if po.get("n"):
            items.append(f"Rugovi u demo tradeovima: {pct(po['share'])} ({po['rugs']} od {po['n']}) nakon tvrdog filtra"
                         + (f", prije {pct(pr['share'])} ({pr['rugs']} od {pr['n']})" if pr.get("n") else "") + ".")
        g = ru["gate"]
        if g["n"]:
            items.append(f"Filtar je odbio {g['n']} tokena (zadnja 24 h: {ru['refused_day']}); {g['collapsed']} od njih "
                         "se kasnije srušilo, što bi bio gubitak.")
        ab = ru.get("ab") or {}
        if ab:
            A, B = ab.get("A") or {}, ab.get("B") or {}
            items.append(f"A/B ulaza: uobičajeni {A.get('n', 0)} zatvorenih (prosjek {pct(A.get('mean'), True)}), "
                         f"prvi prelazak 100k $ {B.get('n', 0)} zatvorenih (prosjek {pct(B.get('mean'), True)}). "
                         + ("Pobjednik: " + ("100k $." if ab.get("winner") == "B" else "uobičajeni ulaz.")
                            if ab.get("winner") else "Još nema dovoljno tradeova za odluku."))
        k3 = ru.get("kol3") or {}
        if k3:
            items.append("Okidač 3+ KOL autora u 15 min: " + ", ".join(
                f"{sess[s]} {v['win']:.0%} dobitnih od {v['n']}" for s, v in k3.items() if s in sess) + ".")
        kt = ru.get("kol3_10") or {}
        if kt:
            lab = {"10": "unutar 10 min", "15": "tek unutar 15 min"}
            items.append("Grupni poziv 3+ autora: " + "; ".join(
                f"{lab[k]} {v['n']} zatvorenih, {v['win']:.0%} dobitnih, medijan {pct(v['median'], True)}"
                for k, v in sorted(kt.items()) if k in lab) + ".")
        ss = ru.get("sessions") or {}
        small = [f"{sess[s]} " + ("pauza" if v.get("factor") == 0 else f"ulog {v['factor']:.0%}")
                 for s, v in ss.items() if s in sess and v.get("factor", 1) < 1]
        items.append("Ulog po sesiji: " + (", ".join(small) if small else "sve sesije puni ulog") + ".")
        items += [h["text"] for h in ru.get("history") or []]
        out.append(section("Nova pravila ulaza: učinak", bullets(items), ("/paper", "Demo trading")))

    return out


SOURCE_HR = {"caller": "Calleri (X, Telegram)", "wallet": "Praćeni novčanici", "scan": "Skener (bez callera)",
             "beta": "Beta mete", "kandidati": "Kandidati (spoj izvora)",
             "grok_override": "Grok nadjačao rug ocjenu"}


CRITIC_WORDS = {"drzi": "drži", "prodaj": "prodaj", "prodaj_dio": "prodaj dio", "stegni_sl": "stegni SL",
                "prosiri_sl": "proširi SL"}


def kriticar_body(k):
    """The morning e-mail's "Kritičar (OpenAI)" section; one line while the critic has nothing yet."""
    if not k:
        return para("Kritičar još nema pregleda.")
    body = ""
    sm = k.get("sazetak")
    if sm:
        body += f'<div style="font-size:13px;font-weight:600;margin:4px 0 2px">{e(sm.get("title"))}</div>'
        body += "".join(para(x) for x in (sm.get("text") or "").split("\n\n")[:3])
    else:
        body += para("Dnevni pregled još nije napravljen.")
    if k.get("nalazi"):
        body += '<div style="font-size:13px;font-weight:600;margin:10px 0 2px">Glavni nalazi</div>'
        body += bullets([f"{x['title']}: {x['text']}" + (f" Prijedlog: {x['prijedlog']}" if x.get("prijedlog") else "")
                         for x in k["nalazi"]])
    if k.get("pozicije"):
        body += '<div style="font-size:13px;font-weight:600;margin:10px 0 2px">Presude za otvorene pozicije</div>'
        body += table(["Pozicija", "Presuda", "Sigurnost", "PnL tada"],
                      [[e(p.get("symbol") or "?") + ("" if p.get("mode") == "live" else ' <span style="color:#6b7280">(demo)</span>'),
                        e(CRITIC_WORDS.get(p.get("verdict"), p.get("verdict") or "")),
                        pct(p.get("confidence")), pct((p.get("pnl_pct") or 0) / 100, True) if p.get("pnl_pct") is not None else "–"]
                       for p in k["pozicije"]])
    pv = k.get("presude") or {}
    if pv:
        rows = []
        for v, d in sorted(pv.items(), key=lambda kv: -kv[1]["n"]):
            rows.append([e(CRITIC_WORDS.get(v, v)), str(d["n"]), pct(d.get("pogodak_30")), pct(d.get("pogodak_60")),
                         pct(d.get("pogodak_zatvaranje")), f"{d.get('usd_60min') or 0:+.2f} $",
                         f"{d.get('usd_zatvaranje') or 0:+.2f} $"])
        body += '<div style="font-size:13px;font-weight:600;margin:10px 0 2px">Koliko je kritičar bio u pravu (7 dana)</div>'
        body += table(["Presuda", "n", "Pogodak 30 min", "60 min", "Na zatvaranju", "$ da je praćen (60 min)",
                       "$ (zatvaranje)"], rows)
    j, m, b = k.get("jucer") or {}, k.get("mjesec") or {}, k.get("budzet") or {}
    body += para(f"Trošak: jučer {j.get('poziva', 0)} poziva, ${j.get('usd', 0):.3f}; ovaj mjesec {m.get('poziva', 0)} "
                 f"poziva, ${m.get('usd', 0):.2f} od ${b.get('mjesec_strop', 0):.0f}.")
    return body


def skener_body(sk):
    """The scanner's section: per source the last 24 h next to the gate window, the paper gate, lead time, spend."""
    gate = {r["source"]: r for r in sk.get("gate_window") or []}
    day = {r["source"]: r for r in sk.get("day") or []}
    rows = []
    for s in ("caller", "wallet", "scan", "beta", "kandidati", "grok_override"):
        d, g = day.get(s) or {}, gate.get(s) or {}
        if not d and not g:
            continue
        rows.append([e(SOURCE_HR[s]), f"{d.get('found', 0)}", pct(d.get("hit1h")), pct(d.get("hit4h")),
                     pct(d.get("sl_first")), pct(d.get("ev"), True),
                     f"{g.get('n', 0)} · EV {pct(g.get('ev'), True)}", e(sk["paper_gate"].get(s) or "–")])
    rule = sk.get("rule") or {}
    body = para(f"Svaki kandidat koji prođe sve filtre dobiva ulaz u sjeni u trenutku kad je nađen. Pravilo: +"
                f"{rule.get('tp', 0.2):.0%} ili −{rule.get('sl', 0.3):.0%}, što prvo dođe, inače izlaz nakon "
                f"{rule.get('horizon_h', 4)} h, trošak {rule.get('cost', 0.02):.0%}. Ništa se ne kupuje.")
    body += table(["Izvor", "Prošlo 24 h", "+20 % u 1 h", "+20 % u 4 h", "−30 % prvo", "EV 24 h",
                   f"Ishoda {sk.get('gate_days', 30)} d", "Paper"], rows) if rows else para("Još nema ulaza u sjeni.")
    items = []
    # 10.11. (ui/kandidati.py): does the combined list beat the best single source, and do Grok's overrides pay?
    cb = sk.get("combined") or {}
    kd, go, best = cb.get("kandidati") or {}, cb.get("grok_override") or {}, cb.get("best_single")
    if kd.get("n") or go.get("n"):
        line = (f"Kandidati (spoj izvora, {sk.get('gate_days', 30)} d): {kd.get('n') or 0} ishoda, EV "
                f"{pct(kd.get('ev'), True)}")
        if best:
            line += f"; najbolji pojedinačni izvor {SOURCE_HR.get(best['source'], best['source'])} EV {pct(best['ev'], True)}"
        if go.get("n"):
            line += f"; Grok nadjačao rug ocjenu: {go['n']} ishoda, EV {pct(go.get('ev'), True)}"
        items.append(line + ".")
    lt = sk.get("lead_time") or {}
    if lt.get("n"):
        items.append(f"Prednost pred callerima (7 dana): medijan {lt['median_min']:+.0f} min na {lt['n']} tokena, "
                     f"skener prvi u {pct(lt['share_before_callers'])} slučajeva.")
    mo = [r for r in sk.get("measured_only_day") or [] if r.get("n")]
    if mo:
        items.append("Samo mjerenje (krivulja, ispod 30k): " + "; ".join(
            f"{SOURCE_HR.get(r['source'], r['source'])} {r['n']} ishoda, EV {pct(r['ev'], True)}" for r in mo) + ".")
    for b in sk.get("beta_by_meta_state") or []:
        if b["window"] == "4h":
            items.append(f"Beta dok meta {b['state']} (4 h): {b['n']} tokena, prosjek {pct(b['mean'], True)}, "
                         f"u plusu {pct(b['hit'])}.")
    sp, cap = sk.get("spend_today") or {}, sk.get("caps") or {}
    items.append(f"Trošak danas: Helius {sp.get('helius_credits', 0):.0f}/{cap.get('helius_credits', 0)} kredita, "
                 f"GeckoTerminal {sp.get('gt_calls', 0):.0f}/{cap.get('gt_calls', 0)} poziva, X "
                 f"{sp.get('x_usd', 0):.2f}/{cap.get('x_usd', 0):.2f} $.")
    return body + bullets(items)


def insajderi_body(d):
    """kol/precall.report_data: launches, new candidates, the confirmed wallets, their paper copies, the day's cost."""
    st = d.get("status") or {}
    items = [f"Zastavica insider_copy: {e(d.get('mode'))}. Nova lansiranja (24 h): {d.get('launches_24h', 0)}, "
             f"provjereno na DexScreeneru {d.get('checked_24h', 0)}, do 10k {d.get('reached_10k_24h', 0)} (idu skeneru "
             f"kao final stretch, ne kupuju se).",
             f"Novčanici: {st.get('confirmed', 0)} potvrđenih izvan uzorka, {st.get('candidate', 0)} kandidata, "
             f"{st.get('excluded', 0)} isključenih (snajperi, botovi, relayeri, dev), {st.get('watch', 0)} se promatra."]
    p = d.get("paper") or {}
    if p.get("n") or p.get("open"):
        items.append(f"Demo kopije insajdera: {p['n']} zatvorenih, EV {pct(p.get('ev'), True)}, PnL {money(p.get('pnl'))}"
                     f", otvoreno {p.get('open', 0)} (za live treba 20+ zatvorenih s EV iznad nule).")
    cost = d.get("cost_24h") or {}
    items.append("Trošak 24 h: Helius " + str(sum(v["helius_credits"] for v in cost.values())) + " kredita, DexScreener "
                 + str(sum(v["dex_calls"] for v in cost.values())) + " poziva (besplatno, s ograničenjem).")
    body = bullets(items)
    rows = [[e(r["wallet"][:6] + "…"), e(r["status"]), str(r["tokens"]), str(r["first"]),
             f"{r['med_min']:.0f} min" if r.get("med_min") is not None else "–", pct(r.get("rose30"))]
            for r in d.get("new_24h") or []]
    if rows:
        body += para("Novi u zadnja 24 h:") + table(["Novčanik", "Status", "Tokena", "Prije 1. poziva",
                                                     "Medijan prije poziva", "+30 % u 1 h"], rows)
    rows = [[e(r["wallet"][:6] + "…"), f"{r['sel']} / {r['conf']}", str(r["tokens"]),
             f"{r['med_min']:.0f} min" if r.get("med_min") is not None else "–", pct(r.get("rose30")),
             pct(r.get("sold_into"))] for r in d.get("confirmed") or []]
    if rows:
        body += para("Potvrđeni (odabir / potvrda):") + table(["Novčanik", "Odabir / potvrda", "Tokena",
                                                               "Medijan prije poziva", "+30 % u 1 h", "Prodao u poziv"], rows)
    return body


def _sl_label(sl):
    from koltest import book
    return book.sl_label(sl)


def arhiva_text(ar):
    """One sentence on last night's archive move (ops/arhiva.run's summary)."""
    if ar.get("dry"):
        return (f"Samo plan (prekidač arhiva_mikrokapova isključen): {ar.get('plan_rows', 0):,} redaka "
                f"≈ {(ar.get('plan_b') or 0) / 1e6:,.0f} MB bi se premjestilo.").replace(",", ".")
    txt = (f"Premješteno {ar.get('moved', 0):,} redaka u .gz arhive ({(ar.get('gz_b') or 0) / 1e6:,.0f} MB), "
           f"oslobođeno {(ar.get('freed_b') or 0) / 1e6:,.0f} MB, disk slobodno "
           f"{(ar.get('free_b') or 0) / 1e9:.1f} GB.").replace(",", ".")
    return txt + (" Nastavlja sljedeće noći." if ar.get("stopped") else "")
