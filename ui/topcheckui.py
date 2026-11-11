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
               "dev": "Dev", "honeypot": "Honeypot", "rugfilter": "Rug filter (Helius)", "rugcheck": "RugCheck",
               "volumen": "Volumen (botovi)"}
ICON = {"ok": "✓", "warn": "⚠", "fail": "✗", None: "–"}


# ---------- 10.11.: "Provjera ruga" on the token page as rows (prijedlog 4.3, maketa token.html) --------------------
# One row per check: name left, the result in a few words right ("Mint authority · ugašen"), a state line on top
# ("● Prolazi sve provjere") and the age of the data next to the heading. Same data as token_box, calmer.
ROW_LABEL = {"mint": "Mint authority", "freeze": "Freeze authority", "lp": "Likvidnost", "holderi": "Top 10 holdera",
             "dev": "Dev", "honeypot": "Probna prodaja", "rugfilter": "Rug filter", "rugcheck": "RugCheck",
             "volumen": "Volumen"}
# the words a check's text starts with, dropped on the right side ("mint authority ugašen" -> "ugašen")
_LEAD = {"mint": "mint authority", "freeze": "freeze authority", "lp": "likvidnost", "holderi": "top 10 holdera",
         "dev": "dev", "honeypot": "testna prodaja", "rugfilter": "rug filter", "rugcheck": "rugcheck",
         "volumen": "volumen"}
KIND = {"ok": "", "warn": "warn", "fail": "bad"}


def _value(k, text):
    """The result part of a check text, short: "top 10 holdera drži 21%" -> "21 %",
    "testna prodaja prolazi (97% vrijednosti)" -> "prolazi, vraća 97 %"."""
    import re
    t = (text or "").strip()
    lead = _LEAD.get(k)
    if lead and t.lower().startswith(lead):
        t = t[len(lead):].strip(" :,")
    if k == "holderi":
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", t)
        if m:
            return m.group(1).replace(".", ",") + " %"
    if k == "honeypot":
        m = re.search(r"\((\d+(?:[.,]\d+)?)\s*% vrijednosti\)", t)
        head = re.split(r"[(,]", t)[0].strip()
        return f"{head}, vraća {m.group(1)} %" if m else head
    t = re.split(r"[(]", t)[0].strip().rstrip(",")
    return re.sub(r"(\d)%", r"\1 %", t) or "–"


def check_rows(top):
    """[(label, value, kind)] from the fresh check of a recommended token (topcheck safety.checks); [] without one.
    kind: "" ok, "warn", "bad" (ui/redak tones), None when the check did not run."""
    out = []
    for k, (s, t) in (((top or {}).get("safety") or {}).get("checks") or {}).items():
        out.append((ROW_LABEL.get(k, CHECK_LABEL.get(k, k)), _value(k, t), KIND.get(s)))
    return out


def check_state(top):
    """(dot kind, sentence, ts) for the state line above the rows; None without a fresh check."""
    if not top or not top.get("verdict"):
        return None
    fails, warns, _ = _reasons(top)
    ts = top.get("rc_ts") or top.get("ts")
    v = top["verdict"]
    if v == "pao" or fails:
        return "bad", "Pao: " + "; ".join(fails[:2]) if fails else "Pao na provjeri ruga", ts
    if v == "oprez" or warns:
        return "warn", "Oprez: " + "; ".join(warns[:2]) if warns else "Oprez", ts
    if v == "prolazi":
        return "good", "Prolazi sve provjere", ts
    return "", "Provjera čeka", ts


def rug_rows(rug):
    """[(label, value, kind)] from the newest rug filter report (rug.db) when the token has no fresh check."""
    if not rug:
        return []
    d = rug.get("data") or {}
    au = d.get("authorities") or {}
    L, hd, dv = (d.get(k) or {} for k in ("launch", "holders", "dev"))

    def pct(v):
        return "–" if v is None else f"{v:g} %".replace(".", ",")
    rows = [("Mint authority", "aktivan" if au.get("mintAuthority") else "ugašen", "bad" if au.get("mintAuthority") else ""),
            ("Freeze authority", "aktivan" if au.get("freezeAuthority") else "ugašen", "bad" if au.get("freezeAuthority") else "")]
    if hd.get("top10_pct") is not None:
        rows.append(("Top 10 holdera", pct(hd["top10_pct"]), "warn" if hd["top10_pct"] >= 35 else ""))
    if dv:
        rows.append(("Dev", f"drži {pct(dv.get('hold_pct'))}, prodao {pct(dv.get('sold_pct'))}",
                     "warn" if (dv.get("hold_pct") or 0) >= 5 else ""))
    if L.get("bundle_pct") is not None:
        rows.append(("Bundle", pct(L["bundle_pct"]), "warn" if L["bundle_pct"] >= 15 else ""))
    if L.get("sniper_pct") is not None:
        rows.append(("Snajperi", pct(L["sniper_pct"]), ""))
    return rows


def rug_state(rug):
    """(dot kind, sentence, ts) from the rug filter verdict."""
    if not rug:
        return None
    d = rug.get("data") or {}
    v = (rug.get("verdict") or "").upper()
    if v == "PROLAZI":
        return "good", "Prolazi rug filter", rug.get("checked_at")
    if v == "OPREZ":
        return "warn", "Oprez: " + "; ".join((d.get("flags") or ["manje zastavice"])[:2]), rug.get("checked_at")
    if v == "ODBAČEN":
        return "bad", "Odbačen: " + "; ".join((d.get("hard_fails") or ["tvrdi pad"])[:2]), rug.get("checked_at")
    if v == "VISOK RIZIK":
        return "bad", "Visok rizik: " + "; ".join((d.get("flags") or [])[:2]), rug.get("checked_at")
    return "", v.capitalize() or "Nije provjeren", rug.get("checked_at")


def token_box(top):
    """Token page: the fresh market state and the line-by-line rug check (only for recommended tokens)."""
    if not top:
        return ""
    st = top.get("state") or {}
    pass_txt = f' (prolaz provjere {esc(ago(top.get("ts"))[0])})' if top.get("rc_ts") else ""
    rows = "".join(
        f'<li><b>{ICON.get(s, "–")}</b> {esc(CHECK_LABEL.get(k, k))}: {esc(t)}</li>'
        for k, (s, t) in ((top.get("safety") or {}).get("checks") or {}).items())
    return ('<div class=card style="margin:10px 0"><h3 style="margin:0 0 6px">Svježa provjera (preporučeni token)</h3>'
            + (f'<p style="margin:4px 0">{state_badge(top)} {esc(st.get("advice") or "")}<br>'
               f'<span class=mut style="font-size:12px">{esc(st.get("why") or "")}</span></p>' if st else "")
            + f'<p style="margin:4px 0">{rug_badge(top)}</p><ul style="margin:4px 0 0 18px;padding:0;font-size:13px">{rows}</ul>'
            # 9.11. (audit P76): the RugCheck data time (rc_ts) when known, not the time of the last run_top pass
            + f'<p class=mut style="font-size:12px;margin:6px 0 0">Podatak od {esc(ago(top.get("rc_ts") or top.get("ts"))[0])}'
              f'{pass_txt}; osvježava se svake 3 minute dok je token među prvih 20 prijedloga.</p></div>')
