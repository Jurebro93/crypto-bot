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
        "Par minuta nakon svakog pokretanja i zatim svaki sat bot pogleda tokene starije od dan: tko se srušio 70%+ od vrha, kome je izvučena likvidnost ili ima "
        "mehaniku ruga, izbaci se iz baze i više se ne prati (nema API troška). Zadrži se samo kako je token izgledao kad "
        "ga je bot prvi put vidio i koliko je pao. Iz toga bot svaki dan uči profil ruga: koje kombinacije signala na ulazu "
        "najčešće završe rugom. Novi token koji jako sliči rugovima zaustavi se odmah, ali samo ako je profil na provjeri "
        f"bio u pravu barem {rugprofile.MIN_PRECISION:.0%} puta i ne bi izgubio više od {rugprofile.MAX_HIT_LOSS:.0%} pravih skokova.")]
    if not sm["n"]:
        out.append("<div class=card>Još nijedan token nije izbačen; prvo čišćenje kreće par minuta nakon pokretanja.</div>")
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


def _pct(x):
    return "–" if x is None else f"{x:+.1%}"


def liga_html():
    """League round 2 (paper/liga.py): which kinds of demo trades proved themselves and count for the bot."""
    from paper import liga
    if not os.path.exists(data.PAPER_DB):
        return ""
    con = sqlite3.connect(f"file:{data.PAPER_DB}?mode=ro", uri=True, timeout=10)
    try:
        g = liga.proven(con)
    finally:
        con.close()
    lc = liga.config()
    out = ["<h2 id=liga>Bot u Natjecanju: uči iz grešaka</h2>" + tdesc(
        "Demo i dalje kupuje svaku priliku da bi učio, ali za bota u Natjecanju broji se samo vrsta ulaza koja se "
        f"dokazala: u zadnjih {lc['days']} dana barem {lc['min_n']} zatvorenih tradeova te vrste, prosjek nakon troškova "
        "iznad nule i to sigurno (90% raspon iznad nule, jedan trade najviše +300%). Provjerava se svakih 10 minuta: "
        "vrsta koja počne gubiti sama ispada, a ona koja počne zarađivati ulazi. Vrsta = način ulaza + izvori + sesija.")]
    rows = []
    for k, v in sorted(g.items(), key=lambda kv: (-kv[1]["proven"], -(kv[1]["low"] if kv[1]["low"] is not None else -9))):
        rows.append([esc(k), num(v["n"]), (_pct(v["mean"]), v["mean"], "n"),
                     (_pct(v["low"]), v["low"] if v["low"] is not None else -9, "n"),
                     (f"{v['win']:.0%}", v["win"], "n"),
                     badge("broji se", "ok") if v["proven"] else badge("samo učenje")])
    n_ok = sum(v["proven"] for v in g.values())
    out.append(f"<p>Dokazanih vrsta: <b>{n_ok}</b> od {len(g)}." + ("" if n_ok else
               " Dok nijedna nije dokazana, bot u Natjecanju čeka i ne gubi novac.") + "</p>")
    out.append(table(["Vrsta ulaza", ("Tradeova", "n"), ("Prosjek", "n"), ("Sigurno barem", "n"), ("U plusu", "n"),
                      "Natjecanje"], rows, empty="Još nema zatvorenih demo tradeova u zadnjih 7 dana."))
    return "".join(out)


def shadow_html():
    """Shadow book (learn/shadow.py): a virtual demo trade at every decision point, labelled with the return the bot
    could actually have taken. Since 2.11. the hype weights learn from it."""
    from learn import shadow
    sm = shadow.summary(days=7)
    out = ["<h2>Sjenovita knjiga: učenje iz svake prilike</h2>", tdesc(
        "Na svakoj točki odluke (prvi signal, prvi prelazak $100k i $1M, svaki demo kandidat, kupljen ili preskočen) alat "
        "\"na papiru\" kupi token i nakon 24 h izračuna koliko bi zaradio s istim pravilima izlaza, naknadama i slippageom "
        "kao demo. Lažne pojedinačne cijene se izbace prije računa. Iz toga uči hype ocjena: pogodak je trade koji je "
        f"nakon troškova zaradio barem {shadow.config()['hit_ret']:.0%}. Zarada je ograničena na +300% da jedan sretan "
        "pogodak ne odluči sve; stupac \"bez 1% najboljih\" to provjerava.")]
    st = sm.get("status") or {}
    if not st:
        return "".join(out) + "<div class=card>Knjiga se puni svaki sat; prve ocjene stižu 24 h nakon prve točke.</div>"
    out.append(f"<p>U knjizi <b>{sum(st.values()):,}</b> točaka: ocijenjeno {st.get('gotovo', 0):,}, čeka 24 h "
               f"{st.get('ceka', 0):,}, bez cijene {st.get('bez_cijene', 0):,}.</p>")

    def row(name, x):
        return [esc(name), num(x["n"]), (_pct(x.get("mean")), x.get("mean") or 0, "n"), (_pct(x.get("median")), x.get("median") or 0, "n"),
                (f"{x['win']:.0%}" if x.get("n") else "–", x.get("win") or 0, "n"),
                (f"{x['pf']:.2f}" if x.get("pf") is not None else "–", x.get("pf") or 0, "n"),
                (_pct(x.get("mean_trim")), x.get("mean_trim") or 0, "n")]
    rr = [row(shadow.POINTS[p], sm["by_point"][p]) for p in shadow.POINTS if sm["by_point"][p].get("n")]
    k = sm["kandidat"]
    if k["kupljeno"].get("n"):
        rr.append(row("demo kandidat: kupljen", k["kupljeno"]))
    if k["preskoceno"].get("n"):
        rr.append(row("demo kandidat: preskočen", k["preskoceno"]))
    out.append(tdesc(f"Zadnjih {sm['days']} dana. \"Prelazak $100k\" je i kontrola: da smo kupili svaki prvi prelazak. "
                     "Ako preskočeni kandidati zarađuju više od kupljenih, filteri režu dobre tokene.")
               + table(["Točka odluke", ("Trgovina", "n"), ("Prosjek", "n"), ("Medijan", "n"), ("U plusu", "n"),
                        ("Profit faktor", "n"), ("Bez 1% najboljih", "n")], rr, empty="Još nema ocijenjenih točaka."))
    return "".join(out)


def _demo_week(since, until):
    """Closed demo trades in [since, until): (n, mean return capped at +300%)."""
    if not os.path.exists(data.PAPER_DB):
        return 0, None
    con = sqlite3.connect(f"file:{data.PAPER_DB}?mode=ro", uri=True, timeout=10)
    try:
        rs = [min(3.0, r or 0) for (r,) in con.execute(
            "SELECT ret FROM trades WHERE status='closed' AND closed_ts>=? AND closed_ts<? AND state NOT LIKE '%\"rucno\"%'",
            (since, until))]
    except sqlite3.OperationalError:
        rs = []
    finally:
        con.close()
    return len(rs), (sum(rs) / len(rs) if rs else None)


def smarter_html(now=None):
    """Top of the page: is the tool smarter this week than last week? Same decision points, three ways to pick:
    every point (control), the top 20% by the score live trading used (weights), the top 20% by the model."""
    import time
    from learn import champion
    now = now or time.time()
    st = champion.load()
    cfg = champion.config()
    weeks = []
    stored = (st.get("weeks") or {}).get("weeks") or []  # computed by the daily learning run (learn/champion.weekly)
    for k, label in ((0, "Ovaj tjedan"), (1, "Prošli tjedan")):
        a, b = now - (k + 1) * 7 * 86400, now - k * 7 * 86400
        c = stored[k]["eval"] if k < len(stored) else {"n": 0}
        n_d, m_d = _demo_week(a, b)
        weeks.append((label, c, n_d, m_d))
    out = ["<h2>Je li alat pametniji?</h2>", tdesc(
        "Na istim prilikama za kupnju (prelazak $100k i demo kandidati) uspoređujemo tri izbora: kupi sve (kontrola), "
        f"{cfg['top_pct']}% najbolje ocijenjenih po težinama (to koristi demo) i {cfg['top_pct']}% najboljih po modelu. "
        "Broj je prosječna ostvariva zarada po tradeu nakon troškova (jedan trade najviše +300%). Demo je stvarni rezultat "
        "zatvorenih demo tradeova u tom tjednu.")]
    this = weeks[0][1]
    if this.get("n"):
        best = max((("model", (this.get("model") or {}).get("mean")), ("težine", (this.get("tezine") or {}).get("mean")),
                    ("kontrola", this["kontrola"].get("mean"))), key=lambda kv: kv[1] if kv[1] is not None else -9)
        last = weeks[1][1]
        line = (f"Ovaj tjedan najbolje bira <b>{esc(best[0])}</b> ({_pct(best[1])} po tradeu)")
        if last.get("n") and (last.get("tezine") or {}).get("n"):
            line += f"; težine {_pct(this['tezine'].get('mean'))} prema {_pct(last['tezine'].get('mean'))} prošli tjedan"
        out.append(f"<div class=card>{line}.</div>")
    rows = []
    for label, c, n_d, m_d in weeks:
        if not c.get("n"):
            rows.append([esc(label), num(0), "–", "–", "–", (_pct(m_d) + (f" ({n_d})" if n_d else ""), m_d or 0, "n")])
            continue
        m = c.get("model") or {}
        rows.append([esc(label), num(c["n"]), (_pct(c["kontrola"].get("mean")), c["kontrola"].get("mean") or 0, "n"),
                     (_pct(c["tezine"].get("mean")), c["tezine"].get("mean") or 0, "n"),
                     (_pct(m.get("mean")), m.get("mean") or 0, "n"), (_pct(m_d) + (f" ({n_d})" if n_d else ""), m_d or 0, "n")])
    out.append(table(["Tjedan", ("Prilika", "n"), ("Kupi sve", "n"), ("Težine", "n"), ("Model", "n"), ("Demo (tradeova)", "n")], rows))
    # model state
    if st.get("champion") == "gbm":
        state = badge("odlučuje model", "good")
    elif st.get("challenger"):
        days = (now - st["challenger"]["trained_ts"]) / 86400
        state = badge(f"model u probi: dan {days:.0f} od {cfg['trial_days']}")
    else:
        state = badge("odlučuju težine; model čeka dovoljno podataka")
    out.append(f"<p>Stanje: {state}</p>")
    hr = st.get("holdout_report")
    h = cfg.get("holdout") or {}
    if hr:
        c = hr["eval"]
        out.append(f"<p>Zaključani tjedan ({esc(h.get('from', ''))} do {esc(h.get('to', ''))}), konačno: kupi sve "
                   f"{_pct(c['kontrola'].get('mean'))}, težine {_pct((c.get('tezine') or {}).get('mean'))}, model "
                   f"{_pct((c.get('model') or {}).get('mean'))}.</p>")
    elif h.get("from"):
        out.append(f"<p class=mut>Zaključani tjedan {esc(h['from'])} do {esc(h['to'])}: nijedno učenje ga ne vidi; "
                   "konačna usporedba stiže dan nakon kraja.</p>")
    return "".join(out)


def payoff_html(now=None):
    """Does the paid AI pay for itself? Its cost in the last 30 days next to what it measurably adds."""
    import time
    from learn import champion, detektiv, postai
    now = now or time.time()
    sp = postai.spend(30, now)
    ov = detektiv.overview(days=30, now=now) or {"by": {}, "usd": 0.0}
    lift = champion.ai_lift()
    n_demo, _ = _demo_week(now - 30 * 86400, now)
    stake = 20
    out = ["<h2>Isplati li se AI?</h2>", tdesc(
        "Trošak plaćenih AI dijelova u zadnjih 30 dana i koliko mjerljivo pomažu. Doprinos AI čitanja objava mjeri se "
        "tako da se isti model nauči i bez AI signala pa se oba ocijene na istim novim prilikama: razlika u zaradi po "
        f"tradeu × broj demo tradeova × ulog ${stake}. Hipoteza vrijedi tek kad prođe test na novim podacima.")]
    rows = []
    if lift:
        gain = lift[0] * n_demo * stake
        verdict = badge("isplati se", "good") if gain > sp["usd"] else badge("još se ne isplati", "bad") if lift[0] <= 0 else badge("blizu")
        rows.append([esc("AI čita objave (Haiku 5.5)"), (f"${sp['usd']:.2f}", sp["usd"], "n"), num(sp["posts"]),
                     (f"{lift[0]:+.1%} po tradeu ({lift[1]} prilika)", lift[0], "n"), (f"≈ ${gain:,.0f}", gain, "n"), verdict])
    else:
        rows.append([esc("AI čita objave (Haiku 5.5)"), (f"${sp['usd']:.2f}", sp["usd"], "n"), num(sp["posts"]),
                     ("mjeri se (prva proba modela s AI signalima)", 0, "wrap"), "–", badge("mjeri se")])
    passed = (ov.get("by") or {}).get("prošla", 0)
    rows.append([esc("AI detektiv (Opus 5.5)"), (f"${ov['usd']:.2f}", ov["usd"], "n"), num(sum((ov.get("by") or {}).values())),
                 (f"{passed} hipoteza prošlo test", passed, "n"), "–",
                 badge("donosi nove signale", "good") if passed else badge("mjeri se")])
    out.append(table(["Dio", ("Trošak 30 d", "n"), ("Obrađeno", "n"), ("Učinak", "n"), ("Vrijednost 30 d", "n"), "Ocjena"], rows))
    return "".join(out)


def hypotheses_html():
    from learn import detektiv
    ov = detektiv.overview()
    out = ["<h2>Hipoteze: ideje koje se same testiraju</h2>", tdesc(
        "Svaki dan AI detektiv pročita najbolje, najgore i propuštene prilike i predloži pravila (npr. \"KOL poziv u US "
        "sesiji uz malu likvidnost\"). Tvoje ideje ulaze u isti red. Svako pravilo se testira samo na prilikama nakon što "
        "je zapisano; prolazi kad tokeni koji mu odgovaraju zarađuju sigurno više od ostalih, i tada postaje signal "
        "modela.")]
    if not ov or not ov["rows"]:
        return "".join(out) + "<div class=card>Prve hipoteze stižu sa sljedećim dnevnim učenjem.</div>"
    by = ov["by"]
    out.append(f"<p>Prošlo {by.get('prošla', 0)}, palo {by.get('pala', 0)}, testira se {by.get('testira se', 0)}"
               + (f", tvojih ideja na čekanju {ov['ideje']}" if ov.get("ideje") else "") + ".</p>")
    rr = []
    for h in ov["rows"]:
        ev = json.loads(h["eval"] or "{}")
        m, r = ev.get("match") or {}, ev.get("rest") or {}
        st = h["status"]
        rr.append([(esc(h["naslov"]) + f"<div class=mut>{esc(h['objasnjenje'] or '')}</div>", "", "wrap"),
                   badge(st, "good" if st == "prošla" else "bad" if st == "pala" else ""), num(h["n"] or 0),
                   (_pct(m.get("mean")), m.get("mean") or 0, "n"), (_pct(r.get("mean")), r.get("mean") or 0, "n"),
                   esc("tvoja ideja" if h["izvor"] == "ideja" else "AI")])
    out.append(table([("Hipoteza", "wrap"), "Stanje", ("Poklapanja", "n"), ("Zarada kad vrijedi", "n"), ("Ostali", "n"), "Izvor"], rr))
    return "".join(out)


def missed_shadow_html(now=None):
    """Candidates the demo skipped that the shadow book shows would have paid +50% or more, by the reason."""
    import time
    from learn import shadow
    now = now or time.time()
    rs = [r for r in shadow.light_rows(point="kandidat", since=now - 7 * 86400) if not r["kupljeno"]]
    if not rs:
        return ""
    big = [r for r in rs if r["ret"] >= 0.5]
    by = {}
    for r in rs:
        d = r["decision"] or "?"
        x = by.setdefault(d, [0, 0])
        x[0] += 1
        x[1] += r["ret"] >= 0.5
    from ui.labels import decision as dlabel
    rows = [[esc(dlabel(d) if callable(dlabel) else d), num(n), num(b), (f"{b / n:.0%}", b / n, "n")]
            for d, (n, b) in sorted(by.items(), key=lambda kv: -kv[1][1])]
    return ("<h2>Propušteni pobjednici (sjenovita knjiga)</h2>" + tdesc(
        "Demo kandidati koje alat nije kupio, a nakon 24 h bi s našim pravilima izlaza zaradili +50% ili više. Po razlogu "
        "zašto nisu kupljeni: ako jedan razlog reže puno pobjednika, taj filter je preoštar.")
            + f"<p>Zadnjih 7 dana: {len(big)} od {len(rs)} preskočenih bi zaradilo +50% ili više.</p>"
            + table(["Zašto nije kupljen", ("Preskočeno", "n"), ("Od toga +50%", "n"), ("Udio", "n")], rows))


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
    from ui import learnprogress
    b = ["<h1>Učenje</h1>"]
    for name, fn in (("napredak", learnprogress.progress_html), ("priča", learnprogress.story_html)):
        try:
            b.append(fn())
        except Exception as e:  # noqa: BLE001
            print(f"učenje: {name}: {type(e).__name__}: {e}")
    head = "".join(b)
    b = []
    con = _con()
    cfg = outcomes.config()
    if con is None:
        return "Učenje", head
    try:
        rows, thr = _rows(con)
    except Exception as e:
        print(f"učenje: ishodi nisu uspjeli: {type(e).__name__}: {e}")
        return "Učenje", head
    klasa = qs.get("klasa") or ""
    for name, fn in (("je li pametniji", smarter_html), ("liga", liga_html), ("isplativost", payoff_html)):
        try:
            b.append(fn())
        except Exception as e:  # noqa: BLE001
            print(f"učenje: {name}: {type(e).__name__}: {e}")
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
    for name, fn in (("sjenovita knjiga", shadow_html), ("propušteni", missed_shadow_html), ("hipoteze", hypotheses_html)):
        try:
            b.append(fn())
        except Exception as e:  # noqa: BLE001
            print(f"učenje: {name}: {type(e).__name__}: {e}")

    b.append("<h2>Što je bot promijenio</h2>")
    if not runs:
        b.append("<div class=card>Učenje još nije pokrenuto. Prvi put kreće u " + esc(cfg["run_at_utc"]) + " UTC, a mijenja težine tek s "
                 f"{cfg['min_rows']} ishoda po klasi.</div>")
    else:
        rr = []
        for r in runs:
            def _n(x):
                return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None
            # only numeric weights: some runs (e.g. the rug profile) also store text values, which have no "change"
            pairs = [(k, _n(v), _n(r["old"].get(k, 0)) if r.get("old") else 0) for k, v in (r["new"] or {}).items()]
            pairs = [(k, v, o or 0) for k, v, o in pairs if v is not None]
            diff = ", ".join(f"{feat(k)} {o:g}→{v:g}" for k, v, o in sorted(pairs, key=lambda p: -abs(p[1] - p[2]))
                             if abs(v - o) >= 0.1)[:200]
            rr.append([esc(dt.datetime.fromtimestamp(r["ts"]).strftime("%d.%m. %H:%M")),
                       badge("confidence", "good") if r["klasa"] == "confidence" else badge("profil ruga", "bad") if r["klasa"] == "rugprofil" else badge("model") if r["klasa"] == "model" else klasab(r["klasa"]), num(r["n"]),
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
    return "Učenje", (head + "<p class=uc-more>Detalji za znatiželjne (sve brojke i tablice, otvori dodirom):</p>"
                      + learnprogress.fold("".join(b)))
