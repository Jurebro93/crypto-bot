"""Pages of the microcap strategies the owner stopped on 15.11. (ops/fokus.py: "Ne želim više mikrokapove uopće"):
their jobs are OFF, so the pages were empty or showed old numbers as if current. 19.11.: they left the navigation and
"Više"; the routes still answer (old links, bookmarks), with one plain line and the way to what the tool does now.
The old view stays one tap away for the owner (?arhiva=1, admins only: the link is adm-only); nothing is deleted.

  /radar        Zadnji sken            hype scan of new tokens (run_hype scan: OFF)
  /paper        Demo trading           the microcap demo bot (paper: RETARGET, no new entries)
  /kol-test     KOL test               $50 demo on every fresh KOL call (paper: RETARGET, no new entries)
  /learn        Učenje                 hype weights learning (run_learn: OFF)
  /korelacije   Korelacije             KOL / wallet groups and pump factors (run_corr: OFF)
  /izlazi       Izlazi                 exit rules per hype class (run_exits fit, run_izlazi: OFF)
  /izlazi/izvori Izlazi po izvoru      learned exits per microcap call source (run_izlazi: OFF)
"""
from ui.html import esc

LINE = "Ova stranica pripada strategiji koju više ne vodimo (od 15.11.); podaci su arhivirani."
PAGES = {
    "/radar": "Zadnji sken",
    "/paper": "Demo trading",
    "/kol-test": "KOL test",
    "/learn": "Učenje",
    "/korelacije": "Korelacije",
    "/izlazi": "Izlazi",
    "/izlazi/izvori": "Izlazi po izvoru",
}


def retired(path):
    return path in PAGES


def page(path, qs=None):
    """(title, body) of the one-line page, or None when `path` is not retired or the owner asked for the archive."""
    if path not in PAGES or (qs or {}).get("arhiva") == "1":
        return None
    title = PAGES[path]
    body = (f'<div class="ms-page"><div class="ms-top"><h1 class="ms-h1">{esc(title)}</h1></div>'
            f'<p class="ms-sub" style="font-size:17px;color:var(--fg);margin-top:14px">{esc(LINE)}</p>'
            '<p class="ms-hint"><a class="ms-acc" href="/wallets">Novčanici</a> · <a class="ms-acc" href="/tokens">Tokeni</a>'
            f'<span class="adm-only"> · <a class="ms-acc" href="{esc(path)}?arhiva=1">Arhiva (stari prikaz)</a></span></p></div>')
    return title, body
