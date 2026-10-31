"""/izvjestaj: the morning e-mail reports (output/report-*.html) and whether e-mail is set up."""
import os
import re
from html import escape as esc

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "output")
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def raw(day):
    """Bytes of one report for the iframe, or None."""
    if not DAY.match(day or ""):
        return None
    try:
        with open(os.path.join(OUT, f"report-{day}.html"), "rb") as f:
            return f.read()
    except OSError:
        return None


def page(qs):
    import glob
    import json
    from report import mail
    days = sorted((os.path.basename(p)[7:17] for p in glob.glob(os.path.join(OUT, "report-????-??-??.html"))),
                  reverse=True)
    try:
        with open(os.path.join(OUT, "report-state.json")) as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    sel = qs.get("dan") if qs.get("dan") in days else (days[0] if days else None)
    hour = os.environ.get("REPORT_HOUR", "7")
    b = ["<h1>Jutarnji izvještaj</h1><p class=mut>Svako jutro u "
         f"{esc(hour)}:00 (Zagreb) bot složi izvještaj iz svojih baza: što je naučio, koje KOL-ove pratiti, tokeni za "
         "današnje sesije, puls holdera i volumena i prijedlozi za algoritam. AI (Claude) interpretira brojke. "
         "Šalje se na e-mail; ovdje su zadnja 14.</p>"]
    miss = mail.missing()
    ai = "da" if os.environ.get("ANTHROPIC_API_KEY") else "ne (dodaj ANTHROPIC_API_KEY)"
    line = (f"E-mail: <b>{'nije podešen, nedostaje ' + esc(', '.join(miss)) if miss else esc(mail.method()) + ' → ' + esc(', '.join(mail.recipients()))}</b>"
            f" · AI interpretacija: <b>{esc(ai)}</b>")
    if st.get("sent"):
        line += f" · zadnji poslan: {esc(st['sent'])}"
    if st.get("error"):
        line += f"<br><span class=bad>{esc(_err(st['error']))}</span>"
    b.append(f"<div class=card>{line}</div>")
    if not sel:
        b.append("<div class=card>Još nema izvještaja. Prvi nastaje nakon deploya (ako je prošlo "
                 f"{esc(hour)}:00) ili sljedeće jutro.</div>")
        return "Izvještaj", "".join(b)
    b.append("<p>" + " · ".join(f'<a href="/izvjestaj?dan={d}">{"<b>" + d + "</b>" if d == sel else d}</a>'
                                for d in days) + "</p>")
    b.append(f'<iframe src="/izvjestaj/raw/{sel}" style="width:100%;height:2400px;border:0;background:#f6f7f9;'
             f'border-radius:8px"></iframe>')
    return "Izvještaj", "".join(b)


def _err(e):
    """Last send error in plain words: no exception names or setting names."""
    e = str(e or "")
    if "nije podešen" in e or "SMTP" in e or "RESEND" in e:
        return ("Izvještaj se ne može poslati e-mailom: na serveru još nije upisana lozinka za slanje e-maila "
                "(Gmail lozinka za aplikaciju). Izvještaj se i dalje radi i vidi ovdje.")
    return "Zadnje slanje nije uspjelo: " + (e.split(": ", 1)[1] if ": " in e and e.split(": ", 1)[0].endswith("Error") else e)
