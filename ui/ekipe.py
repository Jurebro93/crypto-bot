"""/ekipe: Ekipe i minutna provjera (9.11., Jure). What the numbers say about taking +5/10/15/20/30 % right after an
account or a crew calls, measured on 1-minute candles from the minute of the call (kol/minute.py, minute.db), plus
the hot list that is read every 1-2 s. Per crew: members with followers, who calls first, every shared token with
its path and rug flag, ranked by potential."""
import time
from urllib.parse import quote

from kol import minute, store
from ui.html import ago, badge, esc, lead, num, table, tdesc, ts as fts

TITLE = "Ekipe i minutna provjera"
TOP_CREWS = 12   # crews shown with full detail (the rest is in the table)


def _link(h):
    name = h[3:] if h.startswith("tg:") else h
    icon = "✈ " if h.startswith("tg:") else "@"
    return f'<a href="/kol/{quote(h)}">{icon}{esc(name)}</a>'


def _pct(x, cls=True):
    if x is None:
        return ("–", -1, "n")
    c = "good" if x >= 0.5 else ("warn" if x >= 0.3 else "")
    return (f"{x:.0%}", round(x, 3), f"n {c}" if cls else "n")


def _signed(x):
    if x is None:
        return ("–", -999, "n")
    return (f"{x:+.0%}", round(x, 3), "n " + ("good" if x > 0 else "bad" if x < 0 else ""))


def _stat_row(label_html, s, extra=()):
    return [label_html, *extra, num(s["n"]), _pct(s["hit5"]), _pct(s["hit10"]), _pct(s["hit15"]), _pct(s["hit20"]),
            _pct(s["hit30"]), (f"{s['sl']:.0%}", round(s["sl"], 3), "n " + ("bad" if s["sl"] >= 0.3 else "")),
            (f"{s['rug']:.0%}", round(s["rug"], 3), "n " + ("bad" if s["rug"] >= 0.2 else "")),
            (f"{s['med_t10']:.0f} min" if s["med_t10"] is not None else "–", s["med_t10"] or 999, "n"),
            _signed(s["med_r60"])]


HEAD = [("Pozivi", "n"), ("+5 %", "n"), ("+10 %", "n"), ("+15 %", "n"), ("+20 %", "n"), ("+30 %", "n"),
        ("Stop prvi", "n"), ("Rug", "n"), ("Do +10 %", "n"), ("Nakon 60 min", "n")]

CSS = ("<style>.ek-bars{display:grid;grid-template-columns:auto 1fr auto;gap:4px 8px;align-items:center;font-size:13px;margin:6px 0}"
       ".ek-bars .b{height:10px;border-radius:5px;background:var(--soft);overflow:hidden}.ek-bars .b i{display:block;height:100%;background:var(--good)}"
       ".ek-bars .b i.bad{background:var(--bad)}.ek-crew{border:1px solid var(--line);border-radius:14px;padding:10px 14px;margin:0 0 10px;background:var(--card)}"
       ".ek-crew summary{cursor:pointer;font-weight:600}.ek-mem{font-size:13px;margin:4px 0}.ek-mem span{white-space:nowrap}</style>")


def _fmt_followers(f):
    if f is None:
        return "?"
    return f"{f / 1000:.0f}k" if f >= 1000 else str(f)


def _bars(st):
    rows = [("+5 %", st["hit5"], ""), ("+10 %", st["hit10"], ""), ("+15 %", st["hit15"], ""), ("+20 %", st["hit20"], ""),
            ("+30 %", st["hit30"], ""), ("stop prvi", st["sl"], "bad"), ("rug", st["rug"], "bad")]
    return '<div class=ek-bars>' + "".join(
        f'<span>{lab}</span><div class=b><i class="{cls}" style="width:{v * 100:.0f}%"></i></div><span>{v:.0%}</span>'
        for lab, v, cls in rows) + "</div>"


def _crew_card(d, rank):
    hs = d["handles"]
    foll = d["followers"]
    total = sum(f for f in foll.values() if f)
    mem = " + ".join(f'<span>{_link(h)} <small class=mut>{_fmt_followers(foll.get(h))}</small></span>' for h in hs)
    n_first = sum(d["first"].values()) or 1
    first = ", ".join(f"{_link(h)} {c / n_first:.0%}" for h, c in sorted(d["first"].items(), key=lambda x: -x[1]))
    st = d["stats"]
    head = (f'<summary>#{rank} {" + ".join(h[3:] if h.startswith("tg:") else "@" + h for h in hs)} '
            f'<span class=mut>· {d["n_tokens"]} zajedničkih tokena · {d["rugs"]} rug'
            + (f' · +10 % prije stopa {st["hit10"]:.0%} na {st["n"]} izmjerena' if st else " · još bez minutne provjere") + "</span></summary>")
    body = [f'<p class=ek-mem><b>Članovi:</b> {mem} <span class=mut>(zajedno {_fmt_followers(total)} pratitelja)</span></p>',
            f'<p class=ek-mem><b>Prvi zove:</b> {first or "–"}</p>']
    if st:
        body.append(_bars(st))
    rows = []
    for t in d["tokens"]:
        p = t["path"]
        if p:
            cells = [_signed(p["hi15"]), _signed(p["hi30"]), _signed(p["hi60"]),
                     (f"{p['t10']} min" if minute.clean_hit(p, 10) else ("stop prvi" if p["sl_min"] is not None else "–"),
                      p["t10"] if p["t10"] is not None else 999, "n"),
                     _signed(p["r60"])]
        else:
            cells = [("–", -999, "n mut")] * 3 + [("nema minutne provjere", 999, "mut"), _signed(t["r24"])]
        rows.append([f'<a href="/token/{quote(t["token"])}">{esc(t["symbol"] or t["token"][:6])}</a>', fts(t["ts"]),
                     (f"${t['mcap0'] / 1000:,.0f}k" if t["mcap0"] else "–", t["mcap0"] or 0, "n"),
                     _link(t["first"]) if t["first"] else "–", *cells,
                     (f"{t['max24']:+.0%}" if t["max24"] is not None else "–", t["max24"] or -999, "n"),
                     (badge("rug", "bad") if t["rug"] else badge("ne", "good"), int(t["rug"]), "")])
    body.append(table(["Token", "Kad", ("MC na pozivu", "n"), "Prvi", ("+15 min", "n"), ("+30 min", "n"), ("+60 min", "n"),
                       ("Do +10 %", "n"), ("Nakon 60 min", "n"), ("Max 24 h (stara mjera)", "n"), "Rug"], rows,
                      tid=f"ek_c{rank}", empty="Nema zajedničkih tokena u razdoblju.", limit=40))
    body.append(f'<p class=mut style="font-size:13px"><a href="/pravi-trade?ekipa={quote(",".join(hs))}#pratim">Zaprati ekipu pravim novcem →</a> '
                "(ulaz čim prvi od njih objavi, do MC $1M, ne ako je već +25 %).</p>")
    return f'<details class=ek-crew{" open" if rank <= 3 else ""}>{head}{"".join(body)}</details>'


def _hot_html(h):
    if not any(h.get(k) for k in ("x", "tg", "wallets")):
        return "<p class=mut>Još nitko ne prolazi prag; lista se puni iz brojki ispod nakon svakog kruga.</p>"
    parts = []
    if h.get("x"):
        parts.append("<b>X:</b> " + ", ".join(_link(x) for x in h["x"]))
    if h.get("tg"):
        parts.append("<b>Telegram:</b> " + ", ".join(_link("tg:" + x) for x in h["tg"]))
    if h.get("wallets"):
        parts.append("<b>Walleti (dokazani dvaput):</b> " + ", ".join(
            f'<a href="/wallet/{esc(w)}">{esc(w[:4])}…{esc(w[-4:])}</a>' for w in h["wallets"]))
    return "<p>" + "<br>".join(parts) + "</p>"


def page(qs, now=None):
    now = now or int(time.time())
    kcon, mcon = store.ro(), minute.ro()
    if kcon is None or mcon is None:
        if kcon is not None:
            kcon.close()
        if mcon is not None:
            mcon.close()
        return TITLE, (f"<h1>{TITLE}</h1><p class=mut>Minutna provjera još nije napravila prvi krug (proces 'minute' "
                       "puni minute.db od deploya; prve brojke za nekoliko minuta).</p>")
    try:
        cfg = minute.config(_kol_cfg())
        days = int(qs.get("dani") or cfg["days"]) if isinstance(qs, dict) else cfg["days"]
        days = days if days in (7, 14, 30) else cfg["days"]
        min_n = max(1, int(qs.get("min") or 3)) if isinstance(qs, dict) else 3
        cov = minute.coverage(mcon, kcon, cfg, now)
        hot = minute.hot_list()
        hs = minute.handle_stats(mcon, days, now, min_n=min_n)
        cs = minute.crew_stats(mcon, kcon, days, now, min_n=min(2, min_n))
        try:
            from rugfilter import archive
            archived = archive.blocked()
        except Exception:  # noqa: BLE001
            archived = frozenset()
        top = cs["crews"][:TOP_CREWS]
        # 9.11. 20:20: the groups and minute rows once for all crews (12 crews x 2 full reads took the page to 60 s)
        since = now - days * 86400
        all_groups = minute._groups(kcon, since, max_size=max([4] + [len(c[0]) for c in top]))
        paths = {(r["token"], r["ts"]): r for r in minute._rows(mcon, "ts >= ?", (since,))}
        details = [minute.crew_detail(mcon, kcon, c[0], days, now, archived=archived, all_groups=all_groups, paths=paths)
                   for c in top]
    finally:
        kcon.close()
        mcon.close()
    b = [CSS, f"<h1>{TITLE}</h1>", lead(
        "Može li se nakon poziva uzeti +5, +10, +15, +20 ili +30 %? Brojimo samo pogotke koji dođu PRIJE stopa od −20 %, "
        "unutar 60 minuta od minute poziva, po minutnim svijećama."), tdesc(
        "Vrijeme poziva je unix vrijeme u UTC-u (X i Telegram daju pomak zone u zapisu, lanac daje vrijeme bloka); "
        "svijeće GeckoTerminala su isto unix vrijeme, pa poziv u 10:32:20 pada u svijeću 10:32 bez ikakvog "
        "preračunavanja zona. Ulaz = zatvaranje minute u kojoj je objavljen poziv (kopija u istoj minuti plati otprilike "
        "to). Fitilj se broji najviše do 3× tijela svijeće. Tokeni ispod $30k na ulazu se ne broje. Za ekipu se mjeri "
        "PRVI poziv u grupi, pa kasni odjek ne može popraviti brojku. Rug = najniža cijena u satu ≤ −80 %, rug oznaka "
        "iz 24-satnog mjerenja ili token izbačen rug filterom.")]
    tabs = " · ".join(f"<b>{d} d</b>" if d == days else f'<a href="/ekipe?dani={d}">{d} d</a>' for d in (7, 14, 30))
    grid = [(f"{cov['measured']:,}", "poziva izmjereno po minutama"), (f"{cov['waiting']:,}" if cov["waiting"] is not None else "–", "čeka na red"),
            (f"{cov['no_candle']:,}", "bez svijeće (nema trgovanja)"), (f"{cov['small']:,}", "ispod $30k, ne broje se"),
            (ago(cov["last"])[0] if cov["last"] else "–", "zadnji krug")]
    b.append("<div class=grid>" + "".join(f"<div class=stat><div class=v>{v}</div><div class=l>{l}</div></div>" for v, l in grid)
             + "</div>")
    b.append(f"<p class=mut>Razdoblje: {tabs}. Vlastiti proces puni povijest neprekidno (besplatni GeckoTerminal, ~20 tokena u "
             "minuti), ekipe prije pojedinaca; svaki novi poziv dobiva minutnu provjeru 70 min nakon objave.</p>")
    b.append('<p>Bilo koju ekipu (ili vlastitu, npr. <code>tg:kanal1, tg:kanal2, @ime</code>) bot može pratiti pravim novcem: '
             '<a href="/pravi-trade#pratim">Autopilot → Koga bot prati</a>, upiši račune odvojene zarezom. Ulaz čim prvi od njih objavi, '
             'samo dok je token ispod zadanog MC-a (zadano $1M) i nije već +25 % od poziva.</p>')
    b.append("<h2 id=vruce>Vruća lista: čita se svake 1–2 s</h2>" + tdesc(
        f"Računi s barem {cfg['hot_min_n']} izmjerenih poziva u {cfg['hot_days']} dana, +{cfg['hot_tp']} % prije stopa u "
        f"barem {cfg['hot_min_hit']:.0%} slučajeva i stop prvi u najviše {cfg['hot_max_sl']:.0%}; plus walleti dokazani "
        "dvaput. Telegram kanale s liste čitamo svake 2 s, X račune dobivamo webhookom, wallete Helius javlja odmah. "
        "Tko ispadne iz brojki, ispadne i s liste; tko uđe u brojke, uđe na listu u sljedećem krugu.")
             + _hot_html(hot) + (f"<p class=mut>Lista iz {ago(hot['ts'])[0]}.</p>" if hot.get("ts") else ""))
    b.append("<h2 id=ekipe>Ekipe s najvećim potencijalom</h2>" + tdesc(
        "Dva do četiri računa (X i Telegram) zvala su isti token unutar 30 min; pet i više je plaćena kampanja i ne broji "
        "se. Rang = broj zajedničkih tokena × (udio +10 % prije stopa + pola udjela +20 % − stop prvi − rug), sve od PRVOG "
        "poziva u grupi. Po ekipi: članovi s pratiteljima, tko najčešće zove prvi, svaki zajednički token s putanjom "
        "cijene +15/+30/+60 min, stopom i rug oznakom; stara mjera (najviši fitilj 24 h) uz to za usporedbu."))
    if details:
        b.append("".join(_crew_card(d, i + 1) for i, d in enumerate(details)))
    else:
        b.append("<p class=mut>Još nema ekipe s 2+ izmjerena prva poziva u ovom razdoblju; puni se.</p>")
    rows = [_stat_row(" + ".join(_link(h) for h in hs_), s, [num(nt), (f"{pot:.1f}", pot, "n")]) for hs_, s, nt, pot in cs["crews"][:60]]
    b.append("<h3>Sve ekipe (tablica)</h3>" + table(["Ekipa", ("Tokena", "n"), ("Potencijal", "n"), *HEAD], rows, tid="ek_crews",
                                                     empty="Još nema grupe s 2+ izmjerena prva poziva u ovom razdoblju."))
    rows = [_stat_row(_link(a) + " + " + _link(b_), s) for (a, b_), s in cs["pairs"][:40]]
    b.append("<h3>Parovi</h3>" + table(["Par", *HEAD], rows, tid="ek_pairs", empty="Još nema para s 2+ zajednička tokena."))
    for plat, title, pred in (("x", "X računi", lambda h: not h.startswith("tg:")), ("tg", "Telegram kanali", lambda h: h.startswith("tg:"))):
        rows = []
        for h, s in hs:
            if not pred(h):
                continue
            tag = badge("vruće", "good") if (h in hot.get("x", []) or h[3:] in hot.get("tg", [])) else ""
            rows.append(_stat_row(_link(h) + (" " + tag if tag else ""), s))
        b.append(f"<h2 id={plat}>{title}</h2>" + tdesc(f"Svi izmjereni pozivi računa ({min_n}+), bez obzira na ekipu. Manje poziva: "
                                                       f"<a href=\"/ekipe?dani={days}&min=1\">prikaži sve</a>.")
                 + table(["Račun", *HEAD], rows[:80], tid=f"ek_{plat}", empty=f"Još nema računa s {min_n}+ izmjerena poziva."))
    b.append("<h2 id=metoda>Što je ovdje drukčije od ljestvice influencera</h2>" + tdesc(
        "Ljestvica (/kol) je do sada brojala pogodak kao +50 % najvišeg fitilja u 24 h, a cijenu na pozivu kod većine "
        "poziva uzimala iz DexScreener snimke do 25 min NAKON objave (snimke svakih ~20 min). To je za biranje koga "
        "pratiti u pravom novcu prekasno i preoptimistično. Ovdje je ulaz minuta objave, a cilj je ono što bot stvarno "
        "može prodati: +5 do +30 % prije stopa."))
    return TITLE, "".join(b)


def _kol_cfg():
    import json
    import os
    try:
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kol", "config.json")) as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}
