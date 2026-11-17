"""/stanje: "Stanje sustava" (17.11., owner: "Find all of the implicit state machines in my app ... elevate UX, DX
and AX"; stanja/). The owner's one page that says what is switched on, who set it and since when, what would change
it and what the state does not mean; below it the dictionary of every status word the app uses. Read-only: the
switches themselves stay where they are (the Autopilot page). The same data is the MCP tool get_system_state.

The owner only (run_ui.py answers 403 to anybody else before this is called): the board names switches of the real
account.
"""
import time
from zoneinfo import ZoneInfo

from ui import redak as R
from ui.html import esc

PATH = "/stanje"
TZ = ZoneInfo("Europe/Zagreb")
GOOD = {"<live>", "<on>", "live", "<alive>", "<allowed>", "<clear>", "normalno", "risk_on", "<idle>"}
WARN = {"<dry>", "<paused>", "<stopped>", "dno_se_potvrduje", "<silent>", "?", "<never>", "nalog_vlasnika"}
BAD = {"<active>", "slobodan_pad", "risk_off"}
TONE = {"exit_plans_pause": {"<running>": "good"}, "sell_all": {"<running>": "bad"}}
CSS = """
.st .st-row{border-bottom:1px solid var(--line);padding:12px 0}
.st .st-h{display:flex;justify-content:space-between;gap:12px;align-items:baseline}
.st .st-h b{font-size:17px;font-weight:600}
.st .st-v{font-size:17px;font-weight:600;white-space:nowrap}
.st .st-d{font-size:15px;line-height:1.45;color:var(--mut);margin:4px 0 0;overflow-wrap:anywhere}
.st details{margin:6px 0 0}
.st details>summary{font-size:15px;color:var(--acc);cursor:pointer;min-height:32px;display:flex;align-items:center}
.st details ul{margin:4px 0;padding:0 0 0 18px}
.st details li,.st details p{font-size:15px;line-height:1.45;margin:3px 0;overflow-wrap:anywhere}
.st .st-m{padding:10px 0;border-bottom:1px solid var(--line)}
.st .st-m b{font-size:16px;font-weight:600}
.st code{font-size:14px}
@media (max-width:480px){.st .st-h{flex-direction:column;gap:2px}.st .st-v{white-space:normal}}
"""


def when(ts):
    """A timestamp in Zagreb time, "15.11. 10:12"."""
    from datetime import datetime
    return datetime.fromtimestamp(int(ts), TZ).strftime("%d.%m. %H:%M")


def _tone(key, state):
    k = key.split(":", 1)[0]
    if state in (TONE.get(k) or {}):
        return TONE[k][state]
    return "good" if state in GOOD else "warn" if state in WARN else "bad" if state in BAD else ""


def _short(label):
    """("uključen", "Grok kupuje i prodaje sam") of "uključen: Grok kupuje i prodaje sam"."""
    a, _sep, b = str(label).partition(": ")
    a2, _sep2, b2 = a.partition(", ")
    return (a2, (b2 + (": " + b if b else "")) if b2 else b)


def board_html(rows, now=None):
    out = []
    for r in rows:
        short, rest = _short(r["label"])
        bits = [rest] if rest else []
        if r.get("since"):
            bits.append(f"od {when(r['since'])}")
        if r.get("who"):
            bits.append(str(r["who"]))
        if r.get("detail"):
            bits.append(str(r["detail"]))
        more = ""
        if r.get("changes") or r.get("caveats"):
            ch = "".join(f"<li>{esc(c)}</li>" for c in r.get("changes") or ())
            cv = "".join(f"<li>{esc(c)}</li>" for c in r.get("caveats") or ())
            more = ("<details><summary>Što ga mijenja i na što paziti</summary>"
                    + (f"<ul>{ch}</ul>" if ch else "") + (f"<p><b>Pazi:</b></p><ul>{cv}</ul>" if cv else "") + "</details>")
        out.append(f'<div class="st-row" data-key="{esc(r["key"])}" data-state="{esc(r["state"])}"><div class="st-h">'
                   f'<b>{esc(r["title"])}</b><span class="st-v">{R.dot(_tone(r["key"], r["state"]), short)}</span></div>'
                   + (f'<p class="st-d">{esc(" · ".join(bits))}</p>' if bits else "") + more + "</div>")
    return "".join(out)


def dictionary_html():
    from stanja import registar
    out = []
    for area, name in registar.AREAS.items():
        ms = [m for m in registar.MACHINES if m.area == area]
        if not ms:
            continue
        inner = []
        for m in ms:
            st = "".join(f"<li>{esc(lab)}" + ("" if lit.startswith("<") else f" <code>{esc(lit)}</code>") + "</li>"
                         for lit, lab in m.states.items())
            cv = "".join(f"<li>{esc(c)}</li>" for c in m.caveats)
            inner.append(f'<div class="st-m"><b>{esc(m.title)}</b><p class="st-d">{esc(m.store)} · mijenja: {esc(m.who)}</p>'
                         f"<ul>{st}</ul>" + (f"<p><b>Pazi:</b></p><ul>{cv}</ul>" if cv else "") + "</div>")
        out.append(f"<details><summary>{esc(name)} · {len(ms)}</summary>{''.join(inner)}</details>")
    return "".join(out)


def page(qs=None, user=None, now=None):
    """(title, html) of /stanje for the owner; anybody else gets one sentence and no data."""
    from stanja import ploca, registar
    from trade import settings
    top = R.top("Stanje sustava", "Što je uključeno, tko je to postavio i otkad · vidiš samo ti")
    if not settings.is_owner(user):
        return "Stanje sustava", (f'<div class="ms-page st"><style>{CSS}</style>{R.top("Stanje sustava")}'
                                  '<p class=ms-hint>Ovu stranicu vidi samo vlasnik.</p></div>')
    now = int(now or time.time())
    rows = ploca.now(now)
    back = '<p class=ms-hint><a href="/pravi-trade">‹ Autopilot</a></p>'
    html = (f'<div class="ms-page st"><style>{CSS}</style>{back}{top}{board_html(rows, now)}'
            + str(R.hint("Ovdje se ništa ne mijenja: prekidači su na stranici Autopilot. Isto ovo čitaju Grok i kritičar."))
            + str(R.section(f"Rječnik stanja · {len(registar.MACHINES)}", sid="rjecnik"))
            + str(R.hint("Svaka riječ stanja koju aplikacija koristi, gdje je spremljena i tko je mijenja."))
            + dictionary_html() + "</div>")
    return "Stanje sustava", html
