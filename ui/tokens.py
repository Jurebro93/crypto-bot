"""The "Tokeni" page: every token the bot has seen, by priority (confidence), split into tables that each make
sense on their own: active candidates, event tokens, older ones, and rug-rejected / high-risk at the bottom."""
import time

from ui import overview
from ui.html import tdesc, ago, badge, esc, filt, modal, scorecell, table, tlink, usd, verdict

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
                   verdict(r["rug"]["verdict"]) if r["rug"] else "<span class=mut>–</span>", usd(r["mcap"]), usd(r["liq"]),
                   ago(r["last_seen"])] for r in rows], tid, empty, mints=[r["token"] for r in rows])


def page(qs):
    now = time.time()
    rows = sorted(overview.token_rows(), key=overview._rank, reverse=True)
    bad = [r for r in rows if r["rug"] and r["rug"]["verdict"] in ("ODBAČEN", "VISOK RIZIK")]
    ok = [r for r in rows if r not in bad]
    active = [r for r in ok if r["last_seen"] >= now - ACTIVE_H * 3600]
    older = [r for r in ok if r["last_seen"] < now - ACTIVE_H * 3600]
    event = [r for r in rows if r["events"]]

    b = ["<h1>Tokeni</h1><p class=mut>Poredani po <b>confidenceu</b>: hype ocjena plus neovisne potvrde (X, smart money, "
         "KOL, holderi, rug filter, event), minus rizici. Klik na red otvara raspis s dokazima, klik na ime otvara "
         "DexScreener. ⓘ uz stupac objašnjava što znači. Pravila su na stranici <a href=/criteria>Kriteriji</a>.</p>",
         f"<div class=flt>{filt('tt', 'Filtriraj simbol…')}<span class=mut>{len(active)} aktivnih, {len(event)} uz event, "
         f"{len(older)} starijih, {len(bad)} odbačenih</span></div>"]

    b.append(f"<h2>Aktivni kandidati (zadnja {ACTIVE_H} h)</h2>")
    b.append(tdesc('Tokeni viđeni u zadnja 24 h koje rug filter nije odbacio, poredani po confidenceu (najjači gore). Klik na red otvara analizu s interpretacijom i dokazima.') + _main_table(active, "tt", f"U zadnja {ACTIVE_H} h nema tokena koji nisu odbačeni."))

    b.append("<h2>Tokeni vezani uz evente</h2><p class=mut>Tokeni koje je DexScreener našao za događaje iz kalendara. "
             "<b>Pravi</b> je najbolje ocijenjen token eventa, ostali su kopije.</p>")
    erows = []
    for r in event:
        for e in r["events"]:
            erows.append([tlink(r["token"], r["symbol"]), (f"{esc(e['event'])}", e["event"], "wrap"), esc(e["event_date"]),
                          badge("pravi", "good") if e["role"] == "canonical" else badge("kopija"),
                          scorecell(e["score"]), (overview.confidence.badge_html(r["conf"]), r["conf"], "n"),
                          verdict(r["rug"]["verdict"]) if r["rug"] else "<span class=mut>–</span>", usd(e["mcap"]),
                          usd(e["liquidity"])])
    b.append(tdesc('Tokeni nazvani po nadolazećem događaju iz kalendara (rođendan, lansiranje, Polymarket…). Pravi = najbolje ocijenjen token tog eventa, kopija = ostali s istim imenom.') + table(["Token", ("Event", "wrap"), "Datum", "Uloga", ("Event ocjena", "n"), ("Confidence", "n"), "Rug",
                    ("Mcap", "n"), ("Likv.", "n")], erows, "te", "Nijedan token nije vezan uz event.",
                   mints=[r["token"] for r in event for _ in r["events"]]))

    b.append(f"<details style='margin-top:18px'><summary>Stariji tokeni ({len(older)}), nisu viđeni u zadnja {ACTIVE_H} h"
             f"</summary>{_main_table(older, 'to', 'Nema.')}</details>")

    b.append("<h2>Odbačeni i visok rizik</h2><p class=mut>Rug filter ih je odbacio (tvrdi pad) ili im dao ocjenu ispod 50. "
             "Ne ulazi se u njih bez obzira na hype.</p>")
    b.append(tdesc('Ovdje su da se vidi zašto su izbačeni; po defaultu se ne trejdaju.') + table(["Token", "Rug presuda", ("Rug ocjena", "n"), ("Glavni razlog", "wrap"), ("Hype", "n"), ("Mcap", "n"), "Zadnje"],
                   [[tlink(r["token"], r["symbol"]), verdict(r["rug"]["verdict"]), scorecell(r["rug"]["score"]),
                     (esc(((r["rug"]["data"].get("hard_fails") or []) + (r["rug"]["data"].get("flags") or []) or ["–"])[0]), "", "wrap"),
                     scorecell(r["hype_last"]), usd(r["mcap"]), ago(r["last_seen"])] for r in bad], "tb",
                   "Nijedan token nije odbačen.", mints=[r["token"] for r in bad]))
    b.append(modal())
    return "Tokeni", "".join(b)
