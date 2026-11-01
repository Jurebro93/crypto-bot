"""Charts for the public blog: plain HTML/CSS, no script, readable on a phone and by search engines.

- bars(): one horizontal bar per category (one measure, one hue; the bar the text talks about is darker), value
  printed at the end of each bar, hover/tap highlights a row and shows its note, "Show as table" view.
- grid(): a small table whose cells are shaded light→dark by value (one hue, sequential), for two-way lookups.
- stats(): a row of big-number tiles.
Colors follow the dataviz palette (series blue #2a78d6, muted gray for comparison bars); text stays in ink colors.
"""
from ui.html import esc


def _fmt(v, fmt, lang="en"):
    out = _fmt_en(v, fmt)
    if lang == "hr":   # 16.8% -> 16,8%   $1,000 -> $1.000
        out = out.replace(",", "\0").replace(".", ",").replace("\0", ".")
    return out


def _fmt_en(v, fmt):
    if fmt == "pct":
        return f"{v:.0f}%" if float(v).is_integer() else f"{v:.1f}%"
    if fmt == "usd":
        return f"${v:,.0f}"
    if fmt == "eur":
        return f"€{v:,.0f}"
    if fmt == "usd2":   # prices: $12.95, $49
        return f"${v:,.0f}" if float(v).is_integer() else f"${v:,.2f}"
    if fmt == "pct2":   # fees: 0.75%, 1%
        return f"{v:g}%"
    if fmt == "min":
        return f"{v:g} min"
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.1f}"


WORDS = {"en": ("Show as table", "Value", "Note", "Source"), "hr": ("Prikaži kao tablicu", "Vrijednost", "Napomena", "Izvor")}


def bars(title, rows, sub="", fmt="pct", hl=None, source="", vmax=None, lang="en"):
    """rows: [(label, value, note)] in display order; hl: indexes drawn in the strong color (default: none = all)."""
    vmax = vmax or max(v for _, v, _ in rows) or 1
    out = []
    for i, (lab, v, note) in enumerate(rows):
        strong = hl is None or i in hl
        w = max(100 * v / vmax, 0.8)
        out.append(f"<div class=bvr tabindex=0 title=\"{esc(lab)}: {esc(_fmt(v, fmt, lang))}{(' · ' + esc(note)) if note else ''}\">"
                   f"<div class=bvl>{esc(lab)}</div><div class=bvt><i class='{'on' if strong else 'off'}' "
                   f"style='width:{w:.1f}%'></i><b>{esc(_fmt(v, fmt, lang))}</b></div>"
                   + (f"<div class=bvn>{esc(note)}</div>" if note else "") + "</div>")
    w = WORDS[lang]
    tbl = (f"<details class=bvtab><summary>{w[0]}</summary><table><thead><tr><th></th><th class=n>{w[1]}</th>"
           f"<th>{w[2]}</th></tr></thead><tbody>"
           + "".join(f"<tr><td>{esc(lab)}</td><td class=n>{esc(_fmt(v, fmt, lang))}</td><td class=mut>{esc(note or '')}</td></tr>"
                     for lab, v, note in rows) + "</tbody></table></details>")
    return (f"<figure class=bv role=group aria-label=\"{esc(title)}\"><figcaption><b>{esc(title)}</b>"
            + (f"<span>{esc(sub)}</span>" if sub else "") + "</figcaption>" + "".join(out)
            + (f"<div class=bvs>{WORDS[lang][3]}: {esc(source)}</div>" if source else "") + tbl + "</figure>")


def grid(title, cols, rows, sub="", fmt="pct", source="", cap=100.0, lang="en"):
    """cols: column headers; rows: [(row label, [values])]. Cells shaded by value/cap (one hue, light→dark)."""
    head = "<th></th>" + "".join(f"<th class=n>{esc(c)}</th>" for c in cols)
    body = []
    for lab, vals in rows:
        cells = []
        for v in vals:
            a = min(max(v / cap, 0), 1)
            ink = "#fff" if a > 0.55 else "var(--fg)"
            cells.append(f"<td class=n style='background:rgba(42,120,214,{0.08 + 0.85 * a:.2f});color:{ink}'>"
                         f"{esc(_fmt(v, fmt, lang))}</td>")
        body.append(f"<tr><th>{esc(lab)}</th>{''.join(cells)}</tr>")
    return (f"<figure class=bv><figcaption><b>{esc(title)}</b>" + (f"<span>{esc(sub)}</span>" if sub else "")
            + f"</figcaption><div class=tw><table class=gv><thead><tr>{head}</tr></thead><tbody>{''.join(body)}"
            "</tbody></table></div>" + (f"<div class=bvs>{WORDS[lang][3]}: {esc(source)}</div>" if source else "") + "</figure>")


def stats(items):
    """items: [(big value, label)]"""
    return "<div class='cards bst'>" + "".join(f"<div class=card><b>{esc(v)}</b><span>{esc(lab)}</span></div>"
                                              for v, lab in items) + "</div>"


CSS = """
.bv{margin:28px 0;border:1px solid var(--line);border-radius:18px;padding:18px 20px 14px;background:#fff}
.bv figcaption{display:flex;flex-direction:column;gap:2px;margin-bottom:14px}.bv figcaption b{font-size:17px}
.bv figcaption span{color:var(--mut);font-size:14px}
.bvr{display:grid;grid-template-columns:minmax(110px,32%) 1fr;gap:4px 14px;align-items:center;padding:6px 6px;
border-radius:10px;outline:0}.bvr:hover,.bvr:focus{background:var(--soft)}
.bvl{font-size:15px;line-height:1.3}.bvt{display:flex;align-items:center;gap:8px;min-width:0}
.bvt i{display:block;height:18px;border-radius:0 4px 4px 0;flex:none;max-width:calc(100% - 64px)}
.bvt i.on{background:#2a78d6}.bvt i.off{background:#b8c0cc}.bvt b{font-size:15px;font-variant-numeric:tabular-nums}
.bvn{grid-column:2;color:var(--mut);font-size:13px;line-height:1.35;display:none}.bvr:hover .bvn,.bvr:focus .bvn{display:block}
@media(max-width:560px){.bvr{grid-template-columns:1fr}.bvn{grid-column:1}}
.bvs{color:var(--mut);font-size:12.5px;margin-top:10px}
.bvtab{margin-top:8px;font-size:14px}.bvtab summary{cursor:pointer;color:var(--acc);font-size:13.5px}
.bvtab table{margin-top:8px;font-size:14px}.bvtab td,.bvtab th{padding:6px 10px}
table.gv th,table.gv td{padding:10px 12px}table.gv tbody th{background:#fff;color:var(--fg);font-weight:600;font-size:14px}
.bst{grid-template-columns:repeat(3,1fr);margin:24px 0}@media(max-width:560px){.bst{grid-template-columns:1fr 1fr}}
"""
