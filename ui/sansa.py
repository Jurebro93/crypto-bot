"""Šansa za skok: one number to rank tokens by, rewarding how many independent analyses they passed, not only hype.

    šansa = confidence × (0.5 + 0.5 × analizirano / 7) × (1 − 0.15 × palo)

Seven independent layers: hype/market, holders (pump.fun), smart money, KOL, rug filter, X buzz, event. "Paper uzeo"
is a consequence of the score, so it does not count. A token with every layer analysed and confidence 60 ranks
above one with confidence 75 that only two layers looked at.
"""
LAYERS = ("Hype ≥ 50", "X buzz", "Smart money", "KOL", "Holderi", "Rug filter", "Event")
N = len(LAYERS)


def coverage(checks):
    """(analizirano, prošlo, palo) over the independent layers only."""
    an = pr = pa = 0
    for lab, ok, _ in checks:
        if lab not in LAYERS or ok is None:
            continue
        an += 1
        pr += ok is True
        pa += ok is False
    return an, pr, pa


def score(conf, checks):
    an, pr, pa = coverage(checks)
    s = (conf or 0) * (0.5 + 0.5 * an / N) * max(0.0, 1 - 0.15 * pa)
    return round(s), an, pr, pa


MIN_VOL_KEEP = 0.2  # Puls: volume of the last hour must hold at least 20% of its best hour (1.11. review)


def featured_ok(r, min_razina=1, min_analysed=3):
    """Only tokens that reached a paid tier, failed nothing hard, had enough layers actually analysed, passed T0 (not
    'nije' = never checked, 1.11.: such tokens were on the list) and whose volume has not died (Puls)."""
    an, _, _ = coverage(r["checks"])
    t0 = (r.get("tier") or {}).get("t0")
    sv = (r.get("features") or {}).get("snaga_volumen")
    return ((r.get("razina") or 0) >= min_razina and not r.get("hard") and an >= min_analysed
            and t0 not in ("nije", "pad") and (sv is None or sv >= MIN_VOL_KEEP))


def dots_html(checks):
    """One dot per layer: green passed, red failed, grey not analysed; title names the layer."""
    from ui.html import esc
    by = {lab: (ok, det) for lab, ok, det in checks}
    out = []
    for lab in LAYERS:
        ok, det = by.get(lab, (None, ""))
        col = "var(--good)" if ok else "var(--bad)" if ok is False else "var(--line)"
        out.append(f'<span title="{esc(lab)}: {esc(det or ("nije analiziran" if ok is None else ""))}" '
                   f'style="display:inline-block;width:10px;height:10px;border-radius:5px;background:{col};margin-right:3px"></span>')
    return "".join(out)


def explain_html(s, conf, an, pr, pa):
    from ui.html import esc
    return (f"<p>Šansa za skok <b>{s}</b> = confidence {conf} × pokrivenost {0.5 + 0.5 * an / N:.2f} "
            f"({an} od {N} slojeva analizirano) × {max(0.0, 1 - 0.15 * pa):.2f} ({pa} palo). "
            f"<span class=mut>{esc('Prošlo ' + str(pr) + ' slojeva. Sloj koji nije analiziran ne računa se kao prolaz.')}</span></p>")
