"""The "Tokeni" page: every token the bot has seen, by priority (confidence), split into tables that each make
sense on their own: active candidates, event tokens and older ones. Rugged, rejected and weak tokens are not listed
(one line says how many were left out)."""
import time

from ui import overview
from ui.html import tdesc, ago, badge, esc, filt, modal, rugcell, scorecell, table, tlink, usd  # noqa: F401

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
    return table(["Token", ("Confidence", "n"), ("Zašto", "wrap"), ("Analize", "wrap"), ("Hype", "n"), "Rug", ("Mcap", "n"),
                  ("Likv.", "n"), "Zadnje"],
                 [[tlink(r["token"], r["symbol"]), (confidence.badge_html(r["conf"]), r["conf"], "n"), (_why(r), "", "wrap"),
                   (_checks(r), r["passed"], "wrap"), scorecell(r["hype_last"]),
                   rugcell(r), usd(r["mcap"]), usd(r["liq"]),
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
    return ("<h2>Jaki tokeni <span class=mut style='font-weight:400'>· stariji, veća vrijednost, stalan volumen</span></h2>"
            + tdesc("Najbolji s popisa Jaki na stranici Dugoročni: tokeni koji su tu već tjednima, vrijede barem 5 M$ i imaju "
                    "stalan volumen svaki dan. " + ("" if grown else "Rast broja holdera prikazat će se kad bot skupi barem "
                    "tjedan dana dnevnih brojanja. ") + "Sigurniji od novih tokena ispod.")
            + table(head, tr, "tj", "", mints=[r[0] for r in rows])
            + "<p class=mut><a href=/dugorocno#jaki>Cijeli popis jakih tokena →</a></p>")


def page(qs):
    now = time.time()
    rows = sorted(overview.token_rows(), key=overview._rank, reverse=True)
    good = [r for r in rows if overview.relevant(r)]
    n_hidden = len(rows) - len(good)
    active = [r for r in good if r["last_seen"] >= now - ACTIVE_H * 3600]
    older = [r for r in good if r["last_seen"] < now - ACTIVE_H * 3600]
    event = [r for r in rows if r["events"] and not overview.bad(r)]

    b = ["<h1>Tokeni</h1><p class=mut>Samo tokeni koji su još kandidati, poredani po <b>confidenceu</b>: hype ocjena plus "
         "neovisne potvrde (X, smart money, KOL, holderi, rug filter, event), minus rizici. Rugani, odbačeni i slabi "
         f"(confidence ispod {overview.MIN_SHOW_CONF}) se ne prikazuju. Klik na ime otvara stranicu tokena sa svim "
         "provjerama, a sličice pored imena otvaraju ga na vanjskim stranicama. Starije, jače tokene s većom tržišnom vrijednošću i stalnim volumenom vidi na "
         "<a href=/dugorocno>Dugoročnima</a>.</p>",
         f"<div class=flt>{filt('tt', 'Filtriraj simbol…')}<span class=mut>{len(active)} aktivnih, {len(event)} uz event, "
         f"{len(older)} starijih</span></div>", overview.hidden_line(n_hidden)]

    b.append(_strong())
    b.append(f"<h2>Aktivni kandidati (zadnja {ACTIVE_H} h)</h2>")
    b.append(tdesc('Tokeni viđeni u zadnja 24 h koji nisu rugani ni odbačeni i imaju confidence barem '
                   f'{overview.MIN_SHOW_CONF}, poredani po confidenceu (najjači gore). Klik na red otvara analizu s '
                   'interpretacijom i dokazima.') + _main_table(active, "tt", f"U zadnja {ACTIVE_H} h nema dovoljno dobrih tokena."))

    b.append("<h2>Tokeni vezani uz evente</h2><p class=mut>Tokeni koje je DexScreener našao za događaje iz kalendara. "
             "<b>Pravi</b> je najbolje ocijenjen token eventa, ostali su kopije.</p>")
    erows = []
    for r in event:
        for e in r["events"]:
            erows.append([tlink(r["token"], r["symbol"]), (f"{esc(e['event'])}", e["event"], "wrap"), esc(e["event_date"]),
                          badge("pravi", "good") if e["role"] == "canonical" else badge("kopija"),
                          scorecell(e["score"]), (overview.confidence.badge_html(r["conf"]), r["conf"], "n"),
                          rugcell(r), usd(e["mcap"]),
                          usd(e["liquidity"])])
    b.append(tdesc('Tokeni nazvani po nadolazećem događaju iz kalendara (rođendan, lansiranje, Polymarket…). Pravi = najbolje ocijenjen token tog eventa, kopija = ostali s istim imenom.') + table(["Token", ("Event", "wrap"), "Datum", "Uloga", ("Event ocjena", "n"), ("Confidence", "n"), "Rug",
                    ("Mcap", "n"), ("Likv.", "n")], erows, "te", "Nijedan token nije vezan uz event.",
                   mints=[r["token"] for r in event for _ in r["events"]]))

    b.append(f"<details style='margin-top:18px'><summary>Stariji dobri tokeni ({len(older)}), nisu viđeni u zadnja {ACTIVE_H} h"
             f"</summary>{_main_table(older, 'to', 'Nema.')}</details>")
    b.append(modal())
    return "Tokeni", "".join(b)
