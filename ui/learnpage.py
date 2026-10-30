"""The "Učenje" page: what the data says (correlations), what the loop changed and why, and what it missed."""
import datetime as dt
import json
import os
import sqlite3

from ui import data
from ui.html import tdesc, ago, badge, bar, esc, klasab, num, razinab, table, tlink

HR = {"moonshot": "Moonshot", "rizican": "Rizičan", "event": "Event", "stabilni": "Stabilni"}


def _con():
    if not os.path.exists(data.HYPE_DB):
        return None
    con = sqlite3.connect(f"file:{data.HYPE_DB}?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def _rows(con):
    from learn import correlations, outcomes
    rows, thr = outcomes.rows(con)
    return correlations.with_details(con, rows), thr


def page(qs):
    from learn import correlations, outcomes, weights
    b = ["<h1>Učenje</h1><p class=mut>Alat sam uči iz ishoda: svaki dan ponovno računa što je \"skok\" po klasi, "
         "ponovno fita težine hype ocjene po klasi i primjenjuje ih ako prolaze zaštitu (barem 200 ishoda, pomak najviše "
         "20% po težini, bolje na obje vremenske polovice). Ovdje vidiš što je našlo, što je promijenilo i što je propustilo. "
         "Ništa se ne radi ručno.</p>"]
    con = _con()
    cfg = outcomes.config()
    if con is None:
        return "Učenje", "".join(b) + "<div class=card>Još nema baze.</div>"
    try:
        rows, thr = _rows(con)
    except Exception as e:
        return "Učenje", "".join(b) + f"<div class=card>Ishodi se ne mogu izračunati: {esc(str(e))}</div>"
    klasa = qs.get("klasa") or ""
    sel = [r for r in rows if not klasa or r["klasa"] == klasa]

    # 1. pump thresholds and weights per class
    b.append("<h2>Što je skok, po klasi</h2>")
    b.append(tdesc(f"Skok = maksimalni rast u {cfg['horizon_h']} h koji je u gornjih {100 - cfg['skok_pct']}% ishoda te klase u zadnjih "
                   f"{cfg['skok_window_d']} dana; dok klasa nema {cfg['min_class_rows']} ishoda vrijedi početni prag. Prag se sam preračunava.")
             + table(["Klasa", ("Skok ≥", "n"), ("Ishoda", "n"), ("Pogodaka", "n"), "Težine", "Filtar"],
                     [[klasab(k), (f"{thr[k]:+.0%}", thr[k], "n"), num(sum(1 for r in rows if r["klasa"] == k)),
                       num(sum(1 for r in rows if r["klasa"] == k and r["hit"])),
                       badge("naučene", "good") if os.path.exists(weights.path(k)) else badge("osnovne"),
                       f'<a href="?klasa={k}">samo {esc(HR.get(k, k))}</a>' if klasa != k else "<a href='/learn'>sve klase</a>"]
                      for k in sorted(thr)]))

    if len(sel) < 10:
        b.append(f"<div class=card>Premalo ishoda ({len(sel)}) za korelacije; treba barem 10, za fit {cfg['min_rows']}. "
                 "Ishod nastaje 24 h nakon prvog signala, pa tablice ispod rastu same.</div>")
    else:
        # 2. feature lift
        b.append(f"<h2>Koliko svaka značajka pomaže{(' · ' + HR.get(klasa, klasa)) if klasa else ''}</h2>")
        lf = sorted(correlations.lift(sel), key=lambda x: -(x["lift"] or 0))
        b.append(tdesc("Udio skokova kad je značajka jaka (≥ 0,5) i kad je slaba. Lift > 1 znači da značajka pomaže; "
                       "lift blizu 1 znači da ne nosi informaciju. Ovo je ono iz čega fit mijenja težine.")
                 + table(["Značajka", ("n jakih", "n"), ("Skok kad jaka", "n"), ("Skok kad slaba", "n"), ("Lift", "n")],
                         [[esc(x["feature"]), num(x["n_strong"]), (f"{x['hit_strong']:.0%}", x["hit_strong"], "n"),
                           (f"{x['hit_weak']:.0%}", x["hit_weak"], "n"),
                           (f"<b>{x['lift']}</b>" if x["lift"] else "–", x["lift"] or 0, "n")] for x in lf]))

        # 3. threshold curves
        b.append("<h2>Gdje bi prag trebao biti</h2>")
        b.append(tdesc("Udio skokova i rugova po rasponu sirove vrijednosti. Tu se vidi vrijedi li uopće rezati po likvidnosti ili "
                       "holderima, i gdje; alat ne reže, nego ovo ulazi u težine."))
        cv = correlations.curves(sel)
        if not cv:
            b.append("<div class=card>Još nema dovoljno tokena s ovim vrijednostima.</div>")
        for c in cv:
            b.append(f"<h3>{esc(c['label'])}</h3>" + table(["Raspon", ("Tokena", "n"), ("Skok", "n"), ("Rug", "n"), ""],
                     [[esc(x["bin"]), num(x["n"]), (f"{x['hit_rate']:.0%}", x["hit_rate"], "n"),
                       (f"{x['rug_rate']:.0%}", x["rug_rate"], "n"), bar(x["hit_rate"] * 100, 100, 160)] for x in c["bins"]]))

        # 4. pairs
        pr = correlations.pairs(sel)
        if pr:
            b.append("<h2>Parovi značajki koji zajedno znače više</h2>")
            b.append(tdesc("Kad su obje značajke jake: udio skokova prema onome što bi svaka zasebno predvidjela. Lift > 1 znači da "
                           "kombinacija nosi nešto što pojedinačne težine ne vide.")
                     + table(["Značajka A", "Značajka B", ("n", "n"), ("Skok", "n"), ("Lift", "n")],
                             [[esc(p["a"]), esc(p["b"]), num(p["n"]), (f"{p['hit_rate']:.0%}", p["hit_rate"], "n"),
                               (f"<b>{p['lift']}</b>", p["lift"], "n")] for p in pr]))

    # 5. weight history
    from learn import store as lstore
    try:
        runs = lstore.runs(con, klasa or None, 30)
    except Exception:
        runs = []
    b.append("<h2>Što je petlja promijenila</h2>")
    if not runs:
        b.append("<div class=card>Još nijedan run. Prvi se pokreće u " + esc(cfg["run_at_utc"]) + " UTC, a mijenja težine tek s "
                 f"{cfg['min_rows']} ishoda po klasi.</div>")
    else:
        rr = []
        for r in runs:
            diff = ", ".join(f"{k} {r['old'].get(k, 0):g}→{v:g}" for k, v in sorted(r["new"].items(), key=lambda kv: -abs(kv[1] - r["old"].get(kv[0], 0)))
                             if abs(v - r["old"].get(k, 0)) >= 0.1)[:200] if r["new"] else ""
            rr.append([esc(dt.datetime.fromtimestamp(r["ts"]).strftime("%d.%m. %H:%M")), klasab(r["klasa"]), num(r["n"]),
                       badge("primijenjeno", "good") if r["applied"] else badge("bez promjene"),
                       (f"{r['metric_old'] if r['metric_old'] is not None else '–'} → {r['metric_new'] if r['metric_new'] is not None else '–'}", r["metric_new"] or 0, "n"),
                       (esc(r["note"]), "", "wrap"), (esc(diff), "", "wrap")])
        b.append(tdesc("Svaki dnevni run: koliko je ishoda imao, je li promijenio težine i zašto. Metrika je preciznost gornje petine "
                       "tokena po ocjeni (udio skokova među 20% najbolje ocijenjenih).")
                 + table(["Kad", "Klasa", ("Ishoda", "n"), "Odluka", ("Preciznost staro → novo", "n"), ("Zašto", "wrap"), ("Pomaci težina", "wrap")], rr))

    # 6. missed
    try:
        ms = outcomes.missed(con, thr)
    except Exception:
        ms = []
    b.append("<h2>Što smo propustili</h2>")
    b.append(tdesc("Tokeni iz zadnjih 7 dana koji nisu dobili nijednu plaćenu provjeru (ostali na T0, pali na situ ili bili izvan "
                   "pragova skena), a svejedno napravili skok svoje klase. Razlog kaže gdje su stali; to je trošak sadašnjih pragova.")
             + table(["Token", "Klasa", ("Razina", "n"), "T0", ("Max rast", "n"), ("Mcap", "n"), ("Gdje je stao", "wrap"), "Prvi put"],
                     [[tlink(m["token"], m["symbol"]), klasab(m["klasa"]), (razinab(m["razina"]), m["razina"] or 0, "n"),
                       badge({"pad": "pao", "nije": "izvan skena", "prolaz": "prošao"}.get(m["t0"], m["t0"] or "–"), "bad" if m["t0"] == "pad" else ""),
                       (f"<b>{m['max_ret']:+.0%}</b>", m["max_ret"], "n"), num(m["mcap"], "${:,.0f}"), (esc(m["reason"]), "", "wrap"),
                       ago(m["first_ts"])] for m in ms[:40]], empty="Ništa propušteno u zadnjih 7 dana (ili još nema snimaka)."))
    con.close()
    return "Učenje", "".join(b)
