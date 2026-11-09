"""/ekipe: Ekipe i minutna provjera (9.11., Jure). What the numbers say about taking +5/10/15/20/30 % right after an
account or a crew calls, measured on 1-minute candles from the minute of the call (kol/minute.py), plus the hot
list that is read every 1-2 s."""
import time
from urllib.parse import quote

from kol import minute, store
from ui.html import ago, badge, esc, lead, num, table, tdesc

TITLE = "Ekipe i minutna provjera"


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
            (f"{s['med_t10']:.0f} min" if s["med_t10"] is not None else "–", s["med_t10"] or 999, "n"),
            _signed(s["med_r60"])]


HEAD = [("Pozivi", "n"), ("+5 %", "n"), ("+10 %", "n"), ("+15 %", "n"), ("+20 %", "n"), ("+30 %", "n"),
        ("Stop prvi", "n"), ("Do +10 %", "n"), ("Nakon 60 min", "n")]


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
    con = store.ro()
    if con is None:
        return TITLE, f"<h1>{TITLE}</h1><p class=mut>Još nema podataka.</p>"
    try:
        cfg = minute.config(_kol_cfg())
        days = int(qs.get("dani") or cfg["days"]) if isinstance(qs, dict) else cfg["days"]
        days = days if days in (7, 14, 30) else cfg["days"]
        cov = minute.coverage(con, cfg, now)
        hot = minute.hot_list()
        min_n = max(1, int(qs.get("min") or 3)) if isinstance(qs, dict) else 3
        hs = minute.handle_stats(con, days, now, min_n=min_n)
        cs = minute.crew_stats(con, days, now, min_n=min(2, min_n))
    finally:
        con.close()
    b = [f"<h1>{TITLE}</h1>", lead(
        "Može li se nakon poziva uzeti +5, +10, +15, +20 ili +30 %? Brojimo samo pogotke koji dođu PRIJE stopa od −20 %, "
        "unutar 60 minuta od minute poziva, po minutnim svijećama."), tdesc(
        "Vrijeme poziva je unix vrijeme u UTC-u (X i Telegram daju pomak zone u zapisu, lanac daje vrijeme bloka); "
        "svijeće GeckoTerminala su isto unix vrijeme, pa poziv u 10:32:20 pada u svijeću 10:32 bez ikakvog "
        "preračunavanja zona. Ulaz = zatvaranje minute u kojoj je objavljen poziv (kopija u istoj minuti plati otprilike "
        "to). Fitilj se broji najviše do 3× tijela svijeće. Tokeni ispod $30k na ulazu se ne broje. Za ekipu se mjeri "
        "PRVI poziv u grupi, pa kasni odjek ne može popraviti brojku.")]
    tabs = " · ".join(f"<b>{d} d</b>" if d == days else f'<a href="/ekipe?dani={d}">{d} d</a>' for d in (7, 14, 30))
    grid = [(f"{cov['measured']:,}", "poziva izmjereno po minutama"), (f"{cov['waiting']:,}" if cov["waiting"] is not None else "–", "čeka na red"),
            (f"{cov['no_candle']:,}", "bez svijeće (nema trgovanja)"), (f"{cov['small']:,}", "ispod $30k, ne broje se"),
            (ago(cov["last"])[0] if cov["last"] else "–", "zadnji krug")]
    b.append("<div class=grid>" + "".join(f"<div class=stat><div class=v>{v}</div><div class=l>{l}</div></div>" for v, l in grid)
             + "</div>")
    b.append(f"<p class=mut>Razdoblje: {tabs}. Red: prvo tokeni koje zove 2+ računa, pa najnoviji; oko "
             f"{cfg['per_run']} tokena po KOL krugu (besplatni GeckoTerminal), pa se povijest puni kroz dan-dva.</p>")
    b.append('<p>Bilo koju ekipu (ili vlastitu, npr. <code>tg:kanal1, tg:kanal2, @ime</code>) bot može pratiti pravim novcem: '
             '<a href="/pravi-trade#pratim">Autopilot → Koga bot prati</a>, upiši račune odvojene zarezom. Ulaz čim prvi od njih objavi, '
             'samo dok je token ispod zadanog MC-a (zadano $1M) i nije već +25 % od poziva.</p>')
    b.append("<h2 id=vruce>Vruća lista: čita se svake 1–2 s</h2>" + tdesc(
        f"Računi s barem {cfg['hot_min_n']} izmjerenih poziva u {cfg['hot_days']} dana, +{cfg['hot_tp']} % prije stopa u "
        f"barem {cfg['hot_min_hit']:.0%} slučajeva i stop prvi u najviše {cfg['hot_max_sl']:.0%}; plus walleti dokazani "
        "dvaput. Telegram kanale s liste čitamo svake 2 s, X račune dobivamo webhookom, wallete Helius javlja odmah. "
        "Tko ispadne iz brojki, ispadne i s liste; tko uđe u brojke, uđe na listu u sljedećem krugu.")
             + _hot_html(hot) + (f"<p class=mut>Lista iz {ago(hot['ts'])[0]}.</p>" if hot.get("ts") else ""))
    rows = [_stat_row(" + ".join(_link(h) for h in hs_) + f' <a class=mut href="/pravi-trade?ekipa={quote(",".join(hs_))}#pratim">zaprati ekipu →</a>',
                      s, [num(nt)]) for hs_, s, nt in cs["crews"][:40]]
    b.append("<h2 id=ekipe>Ekipe koje zovu zajedno</h2>" + tdesc(
        "Dva do četiri računa (X i Telegram) zvala su isti token unutar 30 min; pet i više je plaćena kampanja i ne broji "
        "se. Brojka je od PRVOG poziva u grupi: toliko bi dobio tko kupi čim prvi od njih objavi.")
             + table(["Ekipa", ("Tokena", "n"), *HEAD], rows, tid="ek_crews",
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
        b.append(f"<h2 id={plat}>{title}</h2>" + tdesc(f"Svi izmjereni pozivi računa ({min_n}+), bez obzira na ekipu. Manje poziva: <a href=\"/ekipe?dani={days}&min=1\">prikaži sve</a>.")
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
