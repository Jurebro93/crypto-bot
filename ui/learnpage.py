"""The "Učenje" page: what the data says (correlations), what the loop changed and why, and what it missed."""
import datetime as dt
import json
import math
import os
import sqlite3

from ui import data
from ui.labels import feat
from ui.html import tdesc, ago, badge, bar, esc, klasab, num, razinab, table, tlink

HR = {"moonshot": "Moonshot", "rizican": "Rizičan", "event": "Event", "stabilni": "Stabilni", "default": "Ostali"}


def note_hr(note):
    """learn_runs.note in plain words (old runs were written in shorthand)."""
    import re
    n = str(note or "")
    m = re.match(r"premalo ishoda \((\d+) < (\d+)\)", n)
    if m:
        return f"premalo ishoda ({m.group(1)} od potrebnih {m.group(2)})"
    m = re.match(r"preciznost gornje petine (\S+) -> (\S+)", n)
    if m:
        return f"pogađanje među 20% najbolje ocijenjenih {m.group(1)} → {m.group(2)}"
    m = re.match(r"nove težine nisu bolje na obje polovice \((\S+) vs (\S+)\)", n)
    if m:
        return f"nove težine nisu bile bolje i na starijim i na novijim podacima ({m.group(1)} prema {m.group(2)})"
    if n.startswith("fit nije uspio"):
        return "još nema nijednog skoka u podacima, nema se iz čega učiti"
    return n


def rugs_html():
    """Archived rugs and the learned rug profile: what is learned from the tokens thrown out of the database."""
    from learn import rugprofile
    from rugfilter import archive
    sm = archive.summary(data.HYPE_DB)
    out = ["<h2>Rugovi: izbačeni iz baze, ali bot uči iz njih</h2>", tdesc(
        "Svaki sat bot pogleda tokene starije od dan: tko se srušio 70%+ od vrha, kome je izvučena likvidnost ili ima "
        "mehaniku ruga, izbaci se iz baze i više se ne prati (nema API troška). Zadrži se samo kako je token izgledao kad "
        "ga je bot prvi put vidio i koliko je pao. Iz toga bot svaki dan uči profil ruga: koje kombinacije signala na ulazu "
        "najčešće završe rugom. Novi token koji jako sliči rugovima zaustavi se odmah, ali samo ako je profil na provjeri "
        f"bio u pravu barem {rugprofile.MIN_PRECISION:.0%} puta i ne bi izgubio više od {rugprofile.MAX_HIT_LOSS:.0%} pravih skokova.")]
    if not sm["n"]:
        out.append("<div class=card>Još nijedan token nije izbačen; prvo čišćenje kreće unutar sat vremena od pokretanja.</div>")
    else:
        kinds = ", ".join(f"{archive.KIND_HR.get(k, k)} {n}" for k, n in sorted(sm["by_kind"].items(), key=lambda kv: -kv[1]))
        out.append(f"<p>Izbačeno <b>{sm['n']}</b> tokena ({esc(kinds)}), od toga {sm['n24']} u zadnja 24 h; obrisano "
                   f"{sm['rows_deleted']:,} zapisa.</p>")
    saved = rugprofile.load()
    if not saved:
        out.append(f"<div class=card>Profil ruga se računa jednom dnevno uz ostalo učenje. Treba barem {rugprofile.MIN_ROWS} "
                   f"tokena i {rugprofile.MIN_RUGS} rugova.</div>")
    else:
        state = (badge(f"aktivan: zaustavlja sličnost ≥ {saved['thr']:.0%}", "good") if saved.get("active")
                 else badge("samo prikaz, ne zaustavlja"))
        out.append(f"<p>Profil ruga: {state} <span class=mut>{esc(saved.get('note') or '')}</span></p>")
        ex = rugprofile.explain(saved)
        if ex:
            out.append(table(["Signal na ulazu", "Smjer", ("Težina", "n")],
                             [[esc(feat(k) if k not in rugprofile.NAMES.values() else k), esc(d), num(w, "{:+.2f}")] for k, d, w in ex]))
    return "".join(out)


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
         "ponovno računa težine hype ocjene po klasi i primjenjuje ih ako prolaze zaštitu (barem 200 ishoda, pomak najviše "
         "20% po težini, bolje na obje vremenske polovice). Ovdje vidiš što je našlo, što je promijenilo i što je propustilo. "
         "Ništa se ne radi ručno.</p>"]
    con = _con()
    cfg = outcomes.config()
    if con is None:
        return "Učenje", "".join(b) + "<div class=card>Još nema podataka za učenje.</div>"
    try:
        rows, thr = _rows(con)
    except Exception as e:
        print(f"učenje: ishodi nisu uspjeli: {type(e).__name__}: {e}")
        return "Učenje", "".join(b) + "<div class=card>Ishodi se trenutno ne mogu izračunati; pokušat će ponovno pri sljedećem osvježavanju.</div>"
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
        b.append(f"<div class=card>Premalo ishoda ({len(sel)}) za korelacije; treba barem 10, za promjenu težina {cfg['min_rows']}. "
                 "Ishod nastaje 24 h nakon prvog signala, pa tablice ispod rastu same.</div>")
    else:
        # 2. feature lift
        b.append(f"<h2>Koliko svaki signal pomaže{(' · ' + HR.get(klasa, klasa)) if klasa else ''}</h2>")
        lf = sorted(correlations.lift(sel), key=lambda x: -(x["lift"] or 0))
        b.append(tdesc("Koliko često token napravi skok kad je signal jak, a koliko kad je slab. „Puta češće” iznad 1 znači da "
                       "signal pomaže; blizu 1 znači da ne govori ništa. Iz ovoga bot sam mijenja težine.")
                 + table(["Signal", ("Tokena s jakim", "n"), ("Skok kad jaka", "n"), ("Skok kad slaba", "n"), ("Puta češće", "n")],
                         [[esc(feat(x["feature"])), num(x["n_strong"]), (f"{x['hit_strong']:.0%}", x["hit_strong"], "n"),
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
            b.append("<h2>Parovi signala koji zajedno znače više</h2>")
            b.append(tdesc("Kad su oba signala jaka: koliko češće dolazi skok nego što bi svaki zasebno predvidio. Iznad 1 znači "
                           "da kombinacija govori nešto što pojedinačni signali ne vide.")
                     + table(["Signal A", "Signal B", ("Tokena", "n"), ("Skok", "n"), ("Puta češće", "n")],
                             [[esc(feat(p["a"])), esc(feat(p["b"])), num(p["n"]), (f"{p['hit_rate']:.0%}", p["hit_rate"], "n"),
                               (f"<b>{p['lift']}</b>", p["lift"], "n")] for p in pr]))

    # 5. weight history
    from learn import store as lstore
    try:
        runs = lstore.runs(con, klasa or None, 30)
    except Exception:
        runs = []
    # 5b. confidence: does the number mean what it says?
    try:
        from learn import confmodel
        crows, _ = confmodel.dataset(con, cfg)
        model = confmodel.load()
        b.append("<h2>Confidence: pogađa li broj</h2>")
        if not crows:
            b.append("<div class=card>Još nema ishoda za provjeru confidencea.</div>")
        else:
            cal_h = confmodel.calibration(crows, confmodel.hand_scorer)
            cal_m = confmodel.calibration(crows, lambda r: confmodel.conf_of(model, r)) if model else []
            b.append(f"<p>{'<b>Naučeni model je uključen</b>' if model else 'Ručne težine (model još nije prošao zaštitu)'}: "
                     f"{len(crows)} tokena s ishodom. Ako confidence vrijedi, udio skokova raste s pojasom.</p>")
            b.append(tdesc("Svaki pojas confidencea: koliko je tokena u njemu i koliki je dio napravio skok svoje klase. Lijevo ručne "
                           "težine, desno naučeni model ako je uključen.")
                     + table(["Confidence", ("Tokena (ručno)", "n"), ("Skok % (ručno)", "n"), ("Tokena (model)", "n"), ("Skok % (model)", "n")],
                             [[esc(bk), num(n), (f"{hr:.0%}", hr, "n"),
                               num(next((n2 for bk2, n2, _ in cal_m if bk2 == bk), None)),
                               (lambda h2: (f"{h2:.0%}", h2, "n") if h2 is not None else num(None))(next((h2 for bk2, _, h2 in cal_m if bk2 == bk), None))]
                              for bk, n, hr in cal_h]))
            if model:
                co = sorted(model["coef"].items(), key=lambda kv: -abs(kv[1]))
                b.append(tdesc("Što je model naučio: koliko puta svaka činjenica množi izglede za skok (1 = ništa, 2 = dvostruko, 0,5 = upola).")
                         + table(["Činjenica", ("Množi izglede", "n")],
                                 [[esc(confmodel.HR.get(k, k)), (f"×{math.exp(v):.2f}", v, "n")] for k, v in co]
                                 + [[esc("hype ocjena (0→100)"), (f"×{math.exp(model['hype']):.2f}", model["hype"], "n")]]))
    except Exception as e:
        print(f"učenje: confidence: {type(e).__name__}: {e}")

    b.append(rugs_html())

    b.append("<h2>Što je bot promijenio</h2>")
    if not runs:
        b.append("<div class=card>Učenje još nije pokrenuto. Prvi put kreće u " + esc(cfg["run_at_utc"]) + " UTC, a mijenja težine tek s "
                 f"{cfg['min_rows']} ishoda po klasi.</div>")
    else:
        rr = []
        for r in runs:
            diff = ", ".join(f"{feat(k)} {r['old'].get(k, 0):g}→{v:g}" for k, v in sorted(r["new"].items(), key=lambda kv: -abs(kv[1] - r["old"].get(kv[0], 0)))
                             if abs(v - r["old"].get(k, 0)) >= 0.1)[:200] if r["new"] else ""
            rr.append([esc(dt.datetime.fromtimestamp(r["ts"]).strftime("%d.%m. %H:%M")),
                       badge("confidence", "good") if r["klasa"] == "confidence" else badge("profil ruga", "bad") if r["klasa"] == "rugprofil" else klasab(r["klasa"]), num(r["n"]),
                       badge("primijenjeno", "good") if r["applied"] else badge("bez promjene"),
                       (f"{r['metric_old'] if r['metric_old'] is not None else '–'} → {r['metric_new'] if r['metric_new'] is not None else '–'}", r["metric_new"] or 0, "n"),
                       (esc(note_hr(r["note"])), "", "wrap"), (esc(diff), "", "wrap")])
        b.append(tdesc("Svako dnevno učenje: koliko je ishoda imao, je li promijenio težine i zašto. Mjeri se koliko skokova "
                       "ima među 20% najbolje ocijenjenih tokena (više = ocjena bolje pogađa).")
                 + table(["Kad", "Klasa", ("Ishoda", "n"), "Odluka", ("Pogađanje staro → novo", "n"), ("Zašto", "wrap"), ("Pomaci težina", "wrap")], rr))

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
