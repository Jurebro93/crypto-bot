"""Točnost next to a score (27.11., vlasnik): one short line under every score the site shows, "pogodila 7 od 10
zadnjih 30 dana (n=10)", with a plain-words tooltip, and the owner-only page /tocnost with the whole table.

The numbers come from the night batch (tocnost/noc.py, table tocnost in tocnost.db), read once per 10 min per process;
nothing is computed on a page view. log(...) writes the score as it is shown right now (tocnost/store.log_shown), so
the night batch can later check it against what happened. No formula or threshold is said in user text.
"""
import time

from ui.html import esc

CSS = ("<style>.toc-l{display:block;font-size:12px;color:var(--mut,#888);margin-top:2px;cursor:help}"
       ".toc-t td,.toc-t th{padding:3px 8px;font-size:13px;text-align:left}.toc-t .n{text-align:right}</style>")


def db_path():
    """TOCNOST_DB, else tocnost.db next to the hype.db the pages use (ui/data.HYPE_DB: the tests' temp folder)."""
    import os
    if os.environ.get("TOCNOST_DB"):
        return os.environ["TOCNOST_DB"]
    from ui import data
    return os.path.join(os.path.dirname(data.HYPE_DB), "tocnost.db")


def log(score, items, now=None):
    """Write what a page shows right now; never raises."""
    try:
        from tocnost import store
        return store.log_shown(score, items, now, db_path())
    except Exception:  # noqa: BLE001 - a page must never fail over its own bookkeeping
        return 0


def _row(score, bucket):
    try:
        from tocnost import store
        return store.latest(db_path()).get((score, str(bucket)))
    except Exception:  # noqa: BLE001
        return None


def _of10(x):
    return f"{round(x * 10):.0f} od 10" if x is not None else "?"


def text(score, bucket, r):
    """(line, tooltip) for one bucket row of the night table, or a 'still measuring' line."""
    from tocnost import izvori
    spec = izvori.SPECS.get(score) or {}
    if not r or not r.get("n"):
        return ("točnost se još mjeri",
                "Ovu ocjenu tek počinjemo provjeravati: bilježimo je kakva je bila kad je prikazana, a što se poslije "
                "stvarno dogodilo usporedit ćemo kad prođe dovoljno vremena.")
    n = r["n"]
    if not r.get("enough"):
        return (f"premalo podataka za točnost (n={n})",
                f"U zadnjih 30 dana provjerili smo tek {n} takvih ocjena; to je premalo da bi se o točnosti išta reklo.")
    if r.get("correct") is not None:
        line = f"pogodila {r['correct']} od {n} zadnjih 30 dana (n={n})"
        between = f"S ovoliko primjera prava točnost je vjerojatno između {_of10(r['acc_lo'])} i {_of10(r['acc_hi'])}."
    else:
        line = f"{r['k']} od {n} {spec.get('kratko', '')} zadnjih 30 dana (n={n})".replace("  ", " ")
        between = f"S ovoliko primjera pravi udio je vjerojatno između {_of10(r['lo'])} i {_of10(r['hi'])}."
    tip = (f"Provjera: {spec.get('ishod', '')}. Gledamo ocjenu točno onakvu kakva je bila kad je prikazana i što se "
           "poslije stvarno dogodilo, i to samo na danima nakon zadnje promjene ocjene, koje ocjena nije vidjela. "
           f"Za usporedbu, kod svih tako ocijenjenih to se dogodilo u {_of10(r.get('base'))} slučajeva. {between}")
    return line, tip


def line(score, bucket, label=None):
    """HTML of the small line under a score ("Pouzdanost: pogodila 7 od 10 ..."); '' for an unknown bucket."""
    if bucket is None:
        return ""
    t, tip = text(score, bucket, _row(score, bucket))
    t = f"{label}: {t}" if label else t
    return f'<span class="toc-l" title="{esc(tip)}">{esc(t)}</span>'


def _pct(x):
    return "–" if x is None else f"{x * 100:.0f} %"


def page(qs=None, user=None, now=None):
    """(title, body) of /tocnost: every score, every bucket, the base rate, n, the 90 % interval, the window and how
    out-of-sample is guaranteed. Owner only (run_ui.py checks before calling)."""
    from tocnost import izvori, store
    now = now or time.time()
    rows = store.latest(db_path(), ttl=0)
    as_of = max((r["as_of"] for r in rows.values()), default=None)
    try:
        refits = izvori.learned_refits(izvori.paths())
    except Exception:  # noqa: BLE001
        refits = {}
    b = [CSS, "<h1>Točnost ocjena</h1><div class=card><p>Svaka ocjena koju stranica pokazuje, provjerena na zadnjih 30 "
         "dana: ocjena kakva je bila u trenutku prikaza (bez ponovnog računanja), ishod izmjeren poslije, samo dani nakon "
         "zadnjeg podešavanja ocjene. Ispod 10 provjerenih: premalo podataka. Interval je 90 %.</p>"
         + (f"<p class=mut>Noćna obrada: {time.strftime('%d.%m.%Y. %H:%M', time.gmtime(as_of))} UTC.</p>" if as_of else
            "<p class=mut>Još nema noćne obrade: prva ide u 3 sata (zona 01–06).</p>") + "</div>"]
    for key in izvori.ORDER:
        spec = izvori.SPECS[key]
        oos = ("svaka ocjena je spremljena kakvu ju je napravio model tog trenutka, prije ishoda (model se uči stalno)"
               if spec["oos"] == "pit" else
               "ručno pravilo: broje se samo dani od zadnje promjene pravila " + time.strftime("%d.%m.%Y.", time.gmtime(spec["since"])))
        tr = []
        for bucket, d in spec["buckets"]:
            r = rows.get((key, bucket)) or {}
            tr.append("<tr>" + "".join(f"<td{c}>{esc(str(v))}</td>" for c, v in (
                ("", bucket), ("", {1: "da", -1: "ne", 0: "bez tvrdnje"}[d]), (" class=n", r.get("n", 0)),
                (" class=n", r.get("k", "–")), (" class=n", _pct(r.get("rate"))),
                (" class=n", f"{_pct(r.get('lo'))}–{_pct(r.get('hi'))}" if r.get("n") else "–"),
                (" class=n", _pct(r.get("base"))),
                (" class=n", (f"{r['correct']} od {r['n']} ({_pct(r.get('acc_lo'))}–{_pct(r.get('acc_hi'))})"
                              if r.get("correct") is not None and r.get("n") else "–")),
                ("", "da" if r.get("enough") else "premalo podataka"))) + "</tr>")
        note = next((r.get("note") for (k, _), r in rows.items() if k == key and r.get("note")), "")
        since = next((r.get("since") for (k, _), r in rows.items() if k == key), None)
        b.append(f"<div class=card><h2>{esc(spec['name'])}</h2><p class=mut>Ishod (1): {esc(spec['ishod'])}. Izvor: "
                 f"{esc(spec['izvor'])}. Izvan uzorka: {esc(oos)}."
                 + (f" Prozor od {time.strftime('%d.%m.', time.gmtime(since))}" if since else "")
                 + (f" {esc(note)}." if note else "") + "</p>"
                 "<table class=toc-t><tr><th>Razina</th><th>Tvrdi ishod</th><th class=n>n</th><th class=n>ishod 1</th>"
                 "<th class=n>udio</th><th class=n>90 %</th><th class=n>svi (baza)</th><th class=n>pogodila</th>"
                 "<th>dovoljno</th></tr>" + "".join(tr) + "</table></div>")
    if refits:
        b.append("<div class=card><h2>Zadnja učenja (learn_runs)</h2><p class=mut>"
                 + esc("; ".join(f"{k}: {time.strftime('%d.%m. %H:%M', time.gmtime(t))}" for k, t in sorted(refits.items())))
                 + "</p></div>")
    b.append("<div class=card><p class=mut>Ne mjeri se: ocjena influencera kao broj (kols.score se svaki krug "
             "prepisuje, bez povijesti; mjeri se presuda koju stranica pokazuje). Stranica samo mjeri: nijedna odluka ni trade ne čita ovu tablicu.</p></div>")
    return "Točnost ocjena", "".join(b)
