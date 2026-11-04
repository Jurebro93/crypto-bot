"""/novo "Što je novo": every entry of share/novosti.json by date, open to every role. Every app page shows a small
one-line notice ("✨ Novo: <title> · Pogledaj što je novo") until the user opens this page (cookie cb_novo)."""
import datetime as dt
import json
import os

from ui.html import esc

FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "share", "novosti.json")
MONTHS = ["siječnja", "veljače", "ožujka", "travnja", "svibnja", "lipnja", "srpnja", "kolovoza", "rujna",
          "listopada", "studenoga", "prosinca"]
_cache = {"mtime": None, "items": []}


def items():
    """Entries newest first; re-read only when the file changes (it changes with a deploy)."""
    try:
        m = os.path.getmtime(FILE)
        if m != _cache["mtime"]:
            with open(FILE, encoding="utf-8") as f:
                data = json.load(f)
            _cache.update(mtime=m, items=[x for x in data if isinstance(x, dict) and x.get("naslov")])
    except (OSError, ValueError):
        pass
    return _cache["items"]


def latest_key():
    """Changes whenever an entry is added: the number of entries + the newest title."""
    it = items()
    return f"{len(it)}" if it else ""


def notice_data():
    """(key, newest title) for the notice on every page; ("", "") when there is no news file."""
    it = items()
    return (latest_key(), it[0]["naslov"]) if it else ("", "")


def _day(d):
    try:
        x = dt.date.fromisoformat(d)
    except (TypeError, ValueError):
        return esc(d or "")
    return f"{x.day}. {MONTHS[x.month - 1]} {x.year}."


def page(qs):
    it = items()
    b = ["<h1>Što je novo</h1>"]
    if not it:
        return "Što je novo", "".join(b) + "<p class=mut>Još nema zapisanih novosti.</p>"
    days = []
    for x in it:
        if not days or days[-1][0] != x.get("datum"):
            days.append((x.get("datum"), []))
        days[-1][1].append(x)
    for d, xs in days:
        rows = "".join(
            f"<li><b>{esc(x['naslov'])}</b><br><span class=mut>{esc((x.get('tekst') or '')[:1].upper() + (x.get('tekst') or '')[1:])}</span></li>"
            for x in xs)
        b.append(f"<h2 class=nvd>{_day(d)}</h2><ul class=nvl>{rows}</ul>")
    # opening this page clears the notice on every other page
    b.append(f"<script>document.cookie='cb_novo={latest_key()}; Path=/; Max-Age=31536000; SameSite=Lax'</script>"
             "<style>.nvd{font-size:15px;margin:18px 0 6px;color:var(--mut)}.nvl{list-style:none;padding:0;margin:0;"
             "display:grid;gap:8px}.nvl li{background:var(--card);border:1px solid var(--line);border-radius:12px;"
             "padding:10px 12px;font-size:14.5px;line-height:1.45}</style>")
    return "Što je novo", "".join(b)
