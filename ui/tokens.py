"""The "Tokeni" page, where the app opens: one list with three views (Novi · Jaki · Dugoročni). Novi = active
candidates by confidence (event tokens and older ones folded below), Jaki = the strong long-term list, Dugoročni is
its own page (/dugorocno) with the same switch on top. Rugged, rejected and weak tokens are never listed."""
import time

from ui import overview
from ui.html import tdesc, ago, badge, esc, filt, modal, rugcell, scorecell, seg, table, tlink, usd  # noqa: F401

ACTIVE_H = 24


def _why(r):
    try:
        from ui.radar import reasons
        why = reasons(r["features"], r["det"])[:2]
    except Exception:
        why = []
    if not why:
        why = [t for p, t in r["conf_parts"] if p > 0][:2]
    return ("<ul class=r>" + "".join(f"<li class=good>{esc(w)}</li>" for w in why) + "</ul>") if why else "<span class=mut>–</span>"


def _checks(r):
    return " ".join(badge(("✓ " if ok else "✗ ") + lab, "good" if ok else "bad") for lab, ok, _ in r["checks"] if ok is not None)


def _main_table(rows, tid, empty):
    from ui import confidence
    return table(["Token", ("Confidence", "n"), ("Mcap", "n"), ("Likv.", "n"), ("Zašto", "wrap"), "Rug", "Zadnje"],
                 [[tlink(r["token"], r["symbol"]), (confidence.badge_html(r["conf"]), r["conf"], "n"),
                   usd(r["mcap"]), usd(r["liq"]), (_why(r), "", "wrap"), rugcell(r),
                   ago(r["last_seen"])] for r in rows], tid, empty, mints=[r["token"] for r in rows])


def _strong(n=5):
    """Top of the "jaki" list from the long-term layer (dugo.db): older, bigger tokens with steady volume and holders."""
    try:
        import json
        from dugo import store as dstore
        con = dstore.ro()
        if con is None:
            return ""
        try:
            rows = con.execute("""SELECT s.mint, t.symbol, s.score, s.mcap, s.features, s.why FROM snap s JOIN tokens t
                ON t.mint=s.mint WHERE s.kind='jaki' AND s.day=(SELECT MAX(day) FROM snap) ORDER BY s.rank LIMIT ?""",
                               (n,)).fetchall()
        finally:
            con.close()
    except Exception as e:  # noqa: BLE001 - a side box must not break the page
        print(f"tokeni: jaki tokeni: {type(e).__name__}: {e}")
        return ""
    if not rows:
        return ""
    from ui.html import num
    tr = []
    for m, sym, sc, mc, fj, why in rows:
        f = json.loads(fj or "{}")
        tr.append([tlink(m, sym), num(sc, "{:.0f}"), usd(mc), usd(f.get("volumen_dan")),
                   num(None if f.get("holderi_30d") is None else 100 * f["holderi_30d"], "{:+.0f}%"), (esc(why), "", "wrap")])
    head = ["Token", ("Ocjena", "n"), ("Vrijednost", "n"), ("Volumen dnevno", "n"), ("Rast holdera 30 d", "n"), ("Zašto", "wrap")]
    grown = any(json.loads(r[4] or "{}").get("holderi_30d") is not None for r in rows)
    if not grown:  # holder growth needs a week of daily counts: until then the column would be all dashes
        head.pop(4)
        tr = [r[:4] + r[5:] for r in tr]
    return table(head, tr, "tj", "", mints=[r[0] for r in rows])


# shown once per browser on the first visit (rule: friends use the app without explanation), then never again
HELLO = ("<div class=card id=hello hidden><b>Dobro došao.</b><ol style='margin:6px 0 8px;padding-left:20px'>"
         "<li><b>Tokeni</b>: najbolji prijedlozi, najjači gore.</li>"
         "<li><b>Influenceri</b>: tko stvarno pogađa i što je upravo zvao.</li>"
         "<li><b>Novčanici</b>: tko je upravo kupio ili prodao.</li></ol>"
         "<span class=mut>Dodirni ⓘ uz broj za objašnjenje.</span> <button type=button class=sm id=hello-ok>U redu</button></div>"
         "<script>(()=>{const h=document.getElementById('hello');try{if(localStorage.getItem('ms_hello'))return}catch(e){return}"
         "h.hidden=false;document.getElementById('hello-ok').onclick=()=>{h.hidden=true;try{localStorage.setItem('ms_hello','1')}catch(e){}}})()</script>")

VIEWS = [("/tokens", "Novi"), ("/tokens/jaki", "Jaki"), ("/dugorocno", "Dugoročni")]


def switch(cur):
    """Novi · Jaki · Dugoročni on top of all three views."""
    return seg(VIEWS, cur)


def page(qs, view="novi"):
    if view == "jaki":
        strong = _strong(n=50)
        return "Tokeni", ("<h1>Tokeni</h1>" + switch("/tokens/jaki")
                          + (strong or "<p class=mut>Popis jakih tokena još se slaže (jednom dnevno).</p>") + modal())
    now = time.time()
    t = time.time()
    rows = sorted(overview.token_rows(), key=overview._rank, reverse=True)
    from ui import data as _d
    _d.stage("/tokens token_rows", t)
    good = [r for r in rows if overview.relevant(r)]
    active = [r for r in good if r["last_seen"] >= now - ACTIVE_H * 3600]
    older = [r for r in good if r["last_seen"] < now - ACTIVE_H * 3600]
    event = [r for r in rows if r["events"] and not overview.bad(r)]

    b = ["<h1>Tokeni</h1>", HELLO, switch("/tokens"), f"<div class=flt>{filt('tt', 'Filtriraj simbol…')}</div>",
         _main_table(active, "tt", f"U zadnja {ACTIVE_H} h nema dovoljno dobrih tokena.")]

    erows = []
    for r in event:
        for e in r["events"]:
            erows.append([tlink(r["token"], r["symbol"]), (f"{esc(e['event'])}", e["event"], "wrap"), esc(e["event_date"]),
                          badge("pravi", "good") if e["role"] == "canonical" else badge("kopija"),
                          scorecell(e["score"]), (overview.confidence.badge_html(r["conf"]), r["conf"], "n"),
                          rugcell(r), usd(e["mcap"]),
                          usd(e["liquidity"])])
    if erows:
        b.append(f"<details style='margin-top:18px'><summary>Uz evente ({len(erows)})</summary>"
                 + table(["Token", ("Event", "wrap"), "Datum", "Uloga", ("Event ocjena", "n"), ("Confidence", "n"), "Rug",
                          ("Mcap", "n"), ("Likv.", "n")], erows, "te", "",
                         mints=[r["token"] for r in event for _ in r["events"]]) + "</details>")
    if older:
        b.append(f"<details style='margin-top:10px'><summary>Stariji, nisu viđeni u zadnja {ACTIVE_H} h ({len(older)})"
                 f"</summary>{_main_table(older, 'to', 'Nema.')}</details>")
    b.append(modal())
    return "Tokeni", "".join(b)
