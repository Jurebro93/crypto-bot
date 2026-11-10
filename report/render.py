"""Email-safe HTML: tables and inline styles only (Gmail/Outlook drop <style>, SVG and scripts), charts are
table-cell bars. Every section links to the dashboard page with the details."""
import html
import os
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
    return (f'<tr><td style="background:#fff;border:1px solid {LINE};border-radius:10px;padding:16px 18px">'
            f'<div style="font-size:16px;font-weight:700;margin-bottom:6px">{title}</div>{body}{m}</td></tr>'
            f'<tr><td style="height:12px;font-size:0">&nbsp;</td></tr>')


def kpi(label, value, sub="", color=INK):
    return (f'<td width="25%" style="padding:10px 12px;background:#fff;border:1px solid {LINE};border-radius:10px">'
            f'<div style="font-size:11px;color:{MUT};text-transform:uppercase;letter-spacing:.03em">{label}</div>'
            f'<div style="font-size:20px;font-weight:700;color:{color};margin-top:2px">{value}</div>'
            f'<div style="font-size:11px;color:{MUT}">{sub}</div></td>')


def tlink(mint, sym):
    return link(f"/token/{e(mint)}", e(sym or (mint or "")[:6]))


def render(data, ai, source):
    now = data["ts"]
    p, k, acc, today = data["paper"], data["kols"], data["sessions"], data["today"]
    day = time.strftime("%d.%m.%Y.", time.localtime(now))
    cur = today["now"]
    cur_sig = (acc.get(cur) or {}).get("signal") or (acc.get(cur) or {}).get("call") or {}
    wr = (p["wins"] / p["closed"]) if p["closed"] else None
    mk = data.get("market")
    kpis = "".join([
        kpi("Demo PnL 24 h", money(p["pnl"]), f"{p['closed']} zatvorenih, {p['open_now']} otvoreno",
            GOOD if p["pnl"] >= 0 else BAD),
        "<td width=8></td>", kpi("Win rate", pct(wr), f"medijan {pct(p['median_ret'], True)}"),
        "<td width=8></td>", kpi("KOL pozivi 24 h", f"{k['calls_24h']}", f"{k['new_kols']} novih KOL-ova"),
        "<td width=8></td>", kpi("Tržište", f"{mk['score']:.0f}/100" if mk else "–", e(mk["label"]) if mk else ""),
    ])
    out = [section("Ukratko", bullets(ai.get("ukratko")))]
    sp = data.get("spend") or []
    if sp:   # urgent only (2.11.: the banner is gone from the app; warnings live on /usage)
        out.append(section(f'<span style="color:{BAD}">Hitno: potrošnja</span>',
                           "".join(para(f"{a['title']}: {a['detail']}") for a in sp), ("/usage", "Potrošnja")))

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

    # suggestions
    sg = ai.get("prijedlozi") or []
    if sg:
        col = {"visok": BAD, "srednji": "#d97706", "nizak": MUT}
        body = "".join(f'<div style="margin:8px 0 10px"><span style="font-size:11px;color:#fff;background:'
                       f'{col.get(x["prioritet"], MUT)};border-radius:4px;padding:1px 6px">{e(x["prioritet"])}</span> '
                       f'<b style="font-size:14px">{e(x["naslov"])}</b>'
                       f'<div style="font-size:13px;line-height:1.5;color:#374151;margin-top:3px">{e(x["opis"])}</div></div>'
                       for x in sg)
        out.append(section("Prijedlozi za bolji algoritam", body))
    if ai.get("upozorenja"):
        out.append(section("Upozorenja", bullets(ai["upozorenja"])))

    src = "AI interpretacija: " + e(source) if source and not source.startswith("pravila") else \
        "Bez AI interpretacije (pravila)"
    return f"""<!DOCTYPE html><html lang="hr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Jutarnji izvještaj {day}</title></head>
<body style="margin:0;padding:0;background:{BG};{FONT};color:{INK}">
<table width="100%" cellpadding=0 cellspacing=0 style="background:{BG}"><tr><td align="center" style="padding:20px 10px">
<table width="680" cellpadding=0 cellspacing=0 style="max-width:680px;width:100%">
<tr><td style="padding:0 2px 12px"><div style="font-size:12px;color:{MUT}">Crypto bot · jutarnji izvještaj · {day}</div>
<div style="font-size:22px;font-weight:800;line-height:1.25;margin-top:4px">{e(ai.get("naslov"))}</div></td></tr>
<tr><td><table width="100%" cellpadding=0 cellspacing=0><tr>{kpis}</tr></table></td></tr>
<tr><td style="height:12px;font-size:0">&nbsp;</td></tr>
{"".join(out)}
<tr><td style="font-size:11px;color:{MUT};padding:4px 2px 20px">{src} · podaci iz baza bota, bez dodatnih Helius/Apify poziva ·
{link("/izvjestaj", "svi izvještaji")} · {link("/", "dashboard")}</td></tr>
</table></td></tr></table></body></html>"""


SOURCE_HR = {"caller": "Calleri (X, Telegram)", "wallet": "Praćeni novčanici", "scan": "Skener (bez callera)",
             "beta": "Beta mete"}


def skener_body(sk):
    """The scanner's section: per source the last 24 h next to the gate window, the paper gate, lead time, spend."""
    gate = {r["source"]: r for r in sk.get("gate_window") or []}
    day = {r["source"]: r for r in sk.get("day") or []}
    rows = []
    for s in ("caller", "wallet", "scan", "beta"):
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


def _sl_label(sl):
    from koltest import book
    return book.sl_label(sl)
