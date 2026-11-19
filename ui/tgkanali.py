"""/telegram-kanali: Telegram kanali, samo informativno (19.11.2026., vlasnik: "Makni Telegram KOL-ove iz izračuna. Ali
zadrži popis kanala, osvježen jednom tjedno, samo za broj pratitelja. Neka to bude samo informativni popis sakriven
negdje sa strane.").

Every user may open it; it is not in the bottom bar (the "Više" page links it). Rows: the channel (a link to its public
Telegram page), followers, the change in 7 and 30 days, the last refresh; most followers first; a search box (the
table's own filter, plus ?q= for a link). Data: tg/pratitelji.pregled (tg.db, read-only). English goes through
ui/i18n like every app page (the strings are in ui/i18n_en.json). /izvori redirects here (run_ui.py).
"""
import re

from ui.html import ago, esc, filt, num, signed, table

PATH = "/telegram-kanali"
TITLE = "Telegram kanali (informativno)"
LEAD = ("Ovo je samo popis kanala i broja pratitelja, osvježava se jednom tjedno. Pozive s Telegrama više ne mjerimo i "
        "ne ulaze ni u jedan izračun.")
LINK_TEXT = "Telegram kanali (informativno)"
NAME = re.compile(r"[A-Za-z0-9_]{3,40}")


def rows(path=None):
    try:
        from tg import pratitelji
        return pratitelji.pregled(path)
    except Exception:  # noqa: BLE001 - no tg.db / an old file: an empty list, never an error page
        return []


def page(qs, path=None):
    q = str((qs or {}).get("q") or "").strip().lower()[:40]
    data = [r for r in rows(path) if not q or q in r["kanal"].lower() or q in str(r.get("naslov") or "").lower()]
    out = []
    for r in data:
        ch = r["kanal"]
        link = (f'<a href="https://t.me/{esc(ch)}" target=_blank rel="noopener nofollow" translate=no>{esc(ch)}</a>'
                if NAME.fullmatch(ch or "") else esc(ch))
        title = f' <span class=mut translate=no>{esc(r["naslov"])}</span>' if r.get("naslov") else ""
        out.append([link + title, num(r["pratitelji"]), signed(r["d7"], "{:+,.0f}"), signed(r["d30"], "{:+,.0f}"),
                    ago(r["ts"])])
    search = (f'<form method=get action="{PATH}" style="display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 12px">'
              f'<input type=search name=q value="{esc(q)}" placeholder="Traži kanal…" size=24> '
              f'<button class="btn sm">Traži</button> {filt("tgk", "Filtriraj…")}</form>')
    body = (f"<h1>{TITLE}</h1><p class=lead>{LEAD}</p>{search}"
            + table(["Kanal", ("Broj pratitelja", "n"), ("Promjena 7 dana", "n"), ("Promjena 30 dana", "n"),
                     "Zadnje osvježavanje"], out, tid="tgk",
                    empty="Nema kanala za prikaz." if q else "Popis je prazan: prvo tjedno brojanje još nije prošlo."))
    return TITLE, body
