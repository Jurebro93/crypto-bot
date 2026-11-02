"""How the fresh check of a recommended token (topcheck/, run_top.py) looks on the pages: market state badge,
rug check badge, advice cell, and the token page box."""
import time

from ui.html import ago, badge, esc

RUG = {"prolazi": ("✓ rug check", "good"), "oprez": ("⚠ oprez", "warn"), "pao": ("✗ pao na rug checku", "bad"),
       "nepoznato": ("? rug check čeka", "")}


def _reasons(top):
    sf = (top or {}).get("safety") or {}
    return sf.get("fails") or [], sf.get("warns") or [], sf.get("oks") or []


def state_badge(top):
    st = (top or {}).get("state")
    if not st:
        return ""
    return f'<span title="{esc(st.get("why") or "")}">{badge(st["label"], st.get("css") or "")}</span>'


def rug_badge(top):
    if not top or not top.get("verdict"):
        return ""
    lab, css = RUG.get(top["verdict"], (top["verdict"], ""))
    fails, warns, oks = _reasons(top)
    tip = "; ".join(fails + warns) or "; ".join(oks)
    return f'<span title="{esc(tip)}">{badge(lab, css)}</span>'


def badges(top):
    """One line under the token name: state + rug check (visible on a phone without scrolling the table)."""
    b = " ".join(x for x in (state_badge(top), rug_badge(top)) if x)
    return f'<div style="margin-top:3px;font-size:12px;white-space:normal">{b}</div>' if b else ""


def advice_cell(top):
    """(html, sort, cls) for the Savjet column."""
    st = (top or {}).get("state")
    if not top:
        return ('<span class=mut>provjera kad uđe među prvih 20</span>', "", "wrap")
    fails, warns, _ = _reasons(top)
    parts = []
    if st:
        parts.append(esc(st["advice"]))
    if fails:
        parts.append('<span class=neg>Rug check: ' + esc("; ".join(fails[:2])) + "</span>")
    elif warns:
        parts.append('<span style="color:var(--warn,#b45309)">Oprez: ' + esc("; ".join(warns[:2])) + "</span>")
    age = ago(top.get("ts"))[0]
    parts.append(f'<span class=mut style="font-size:11px">provjereno {esc(age)}</span>')
    return ('<div style="font-size:12px;line-height:1.35;min-width:180px;max-width:260px">' + "<br>".join(parts) + "</div>",
            st["state"] if st else "", "wrap")


def fresh(top, max_age_min=30):
    return bool(top and top.get("ts") and time.time() - top["ts"] < max_age_min * 60)


CHECK_LABEL = {"mint": "Mint authority", "freeze": "Freeze authority", "lp": "LP zaključan", "holderi": "Top 10 holdera",
               "dev": "Dev", "honeypot": "Honeypot", "rugfilter": "Rug filter (Helius)", "rugcheck": "RugCheck"}
ICON = {"ok": "✓", "warn": "⚠", "fail": "✗", None: "–"}


def token_box(top):
    """Token page: the fresh market state and the line-by-line rug check (only for recommended tokens)."""
    if not top:
        return ""
    st = top.get("state") or {}
    rows = "".join(
        f'<li><b>{ICON.get(s, "–")}</b> {esc(CHECK_LABEL.get(k, k))}: {esc(t)}</li>'
        for k, (s, t) in ((top.get("safety") or {}).get("checks") or {}).items())
    return ('<div class=card style="margin:10px 0"><h3 style="margin:0 0 6px">Svježa provjera (preporučeni token)</h3>'
            + (f'<p style="margin:4px 0">{state_badge(top)} {esc(st.get("advice") or "")}<br>'
               f'<span class=mut style="font-size:12px">{esc(st.get("why") or "")}</span></p>' if st else "")
            + f'<p style="margin:4px 0">{rug_badge(top)}</p><ul style="margin:4px 0 0 18px;padding:0;font-size:13px">{rows}</ul>'
            + f'<p class=mut style="font-size:12px;margin:6px 0 0">Provjereno {esc(ago(top.get("ts"))[0])}; osvježava se svake '
              '3 minute dok je token među prvih 20 prijedloga.</p></div>')
