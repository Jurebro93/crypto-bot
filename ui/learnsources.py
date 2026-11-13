"""Učenje: which entry source beats a random entry? (learn/izvori.py over the strategy comparison, strat.db.)

A plain card on top of the page (one line per source, mobile first) and the numbers in a folded table below. Only
reads; the learning itself happens in learn/champion.py (features izv_*).
"""
from ui.html import esc, info


def _pp(x):
    return "–" if x is None else f"{x * 100:+.1f} pb"


def _pct(x):
    return "–" if x is None else f"{x:+.1%}"


MARK = {"bolje": ("✅", "good"), "losije": ("⛔", "bad"), "isto": ("➖", ""), "premalo": ("⏳", "")}


def _line(v):
    icon, cls = MARK.get(v["status"], ("", ""))
    name = f"{esc(v['icon'])} <b>{esc(v['name'])}</b>"
    if v["status"] == "premalo":
        return f"<li>{icon} {name}: {esc(v['text'])}.</li>"
    lo, hi = v["range"] or (None, None)
    rng = f" (sigurno između {_pp(lo)} i {_pp(hi)})" if lo is not None else ""
    what = {"bolje": "zarađuje više od nasumičnog ulaza", "losije": "zarađuje manje od nasumičnog ulaza",
            "isto": "zasad se ne razlikuje od nasumičnog ulaza"}[v["status"]]
    w = (f" Model mu daje težinu {_pp(v['weight'])}." if v["weight"] else " Model mu zasad ne daje dodatnu težinu.")
    return (f"<li>{icon} {name} {what}: <span class={cls}>{_pp(v['lift'])} po tradeu</span>{rng}, "
            f"{v['n']} zatvorenih.{w}</li>")


def card_html(data=None):
    from learn import izvori
    if data is None:
        data = izvori.current()
    if not data:
        return ""
    vals = list(data.values())
    good = [v for v in vals if v["status"] == "bolje"]
    any_v = next(iter(vals), {})
    if all(v["status"] == "premalo" for v in vals):
        head = ("Još nema dovoljno zatvorenih tradeova da se kaže koji izvor ulaza je bolji od nasumičnog "
                f"(treba barem {izvori.MIN_N} po strategiji i u kontroli).")
    elif good:
        head = "Bolji od nasumičnog ulaza: " + ", ".join(f"{esc(v['icon'])} {esc(v['name'])}" for v in good) + "."
    else:
        head = "Nijedan izvor ulaza zasad nije sigurno bolji od nasumičnog ulaza."
    ctrl = (f"Kontrola (nasumični ulaz): {any_v.get('n_ctrl', 0)} zatvorenih, prosjek {_pct(any_v.get('mean_ctrl'))} "
            "po tradeu.")
    return ("<div class=uc-card id=izvori><h3>Koji izvor ulaza vrijedi? " + info("", "prednost-izvora") + "</h3>"
            f"<p>{head}</p><ul class=uc-ul style='margin-top:10px'>" + "".join(_line(v) for v in vals) + "</ul>"
            f"<p class=uc-small>{esc(ctrl)} Svih {len(vals) + 1} strategija kupuje i prodaje po istim pravilima, pa "
            f"razlika dolazi samo od izvora. Zadnjih {izvori.DAYS} dana, jedan trade najviše +300%. Model učenja ovo "
            "dobiva kao signal i sam odlučuje koliko mu vjeruje.</p></div>")


def details_html(data=None):
    """Folded part: the same numbers as a table."""
    from learn import izvori
    from ui.html import badge, num, table
    if data is None:
        data = izvori.current()
    if not data:
        return ""
    rows = []
    for v in data.values():
        lo, hi = v["range"] or (None, None)
        rows.append([f"{esc(v['icon'])} {esc(v['name'])}", num(v["n"]), (_pct(v["mean"]), v["mean"] or 0, "n"),
                     (_pp(v["lift"]), v["lift"] or 0, "n"),
                     ("–" if lo is None else f"{_pp(lo)} do {_pp(hi)}", lo if lo is not None else -9, "n"),
                     (_pp(v["weight"]), v["weight"], "n"), badge(v["text"])])
    return ("<h2>Izvori ulaza prema nasumičnom</h2>"
            + table(["Izvor", ("Zatvoreno", "n"), ("Prosjek", "n"), ("Prednost", "n"), ("90% raspon", "n"),
                     ("Težina u modelu", "n"), "Presuda"], rows))
