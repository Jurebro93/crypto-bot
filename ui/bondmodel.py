"""Odjeljak „Procjena bondanja” na vlasnikovoj stranici /pump-tokeni (27.11.; bondmodel/). Samo čita bond_model.db.
Tekst bez formula i bez adresa tokena; samo istraživanje, ne kupuje."""
import time

from bondmodel import model
from ui.html import esc, table


def _pct(x, d=1):
    return "–" if x is None else f"{x * 100:.{d}f} %".replace(".", ",")


def _d(ts):
    return time.strftime("%d.%m. %H:%M", time.gmtime(ts)) + " UTC" if ts else "–"


def _grade(a):
    if a is None:
        return "–"
    return ("dobro" if a >= 0.75 else "korisno" if a >= 0.65 else "slabo" if a >= 0.55 else "kao bacanje novčića")


def section_html(path=None):
    runs = model.latest(path)
    head = ("<details class=card><summary><span class=pt-t>Procjena bondanja</span><span class=mut>"
            "rana procjena za tuđa lansiranja, provjerena na kasnijim satima</span></summary><div class=in>")
    note = ("<p class=pt-note>Samo istraživanje: procjena se ne koristi ni za jednu kupnju (tokeni na krivulji se ne "
            "kupuju). Model uči samo iz ranijih sati i provjerava se na kasnijim koje nije vidio. Ishod se gleda do "
            "12 sati nakon lansiranja.</p>")
    if not runs:
        return head + note + "<p class=mut>Još nema izračuna (nema podataka mjerenja ili posao još nije radio).</p>" \
                             "</div></details>"
    b = [head, note]
    rows = []
    for t in model.TARGETS:
        r = runs.get(t)
        if not r:
            continue
        d = r["detail"]
        rows.append([esc(model.TARGET_NAMES[t]), (str(r["n_test"]), r["n_test"], "n"), _pct(r["base"], 2),
                     esc(_grade(r["auc"])) + (f" <span class=mut>({r['auc']:.2f})</span>" if r["auc"] else ""),
                     f"{_pct(r['p1'])} <span class=mut>({d.get('hits1', 0)}/{d.get('k1', 0)})</span>",
                     f"{_pct(r['p5'])} <span class=mut>({d.get('hits5', 0)}/{d.get('k5', 0)})</span>",
                     esc(r["verdict"])])
    any_r = next(iter(runs.values()))
    b.append(f"<p class=pt-note>Podaci {_d(any_r['od_ts'])} – {_d(any_r['do_ts'])}, {any_r['n_rows']} lansiranja s "
             f"ishodom; izračun {_d(any_r['ts'])}.</p>")
    b.append(table(["Cilj", ("Provjereno lansiranja", "n"), "Osnovna stopa", "Rangiranje",
                    "Pogodak u gornjih 1 %", "Pogodak u gornjih 5 %", "Presuda"], rows, tid="bmrez"))
    main = runs.get("bond") or any_r
    cal = main["detail"].get("kalibracija") or []
    if cal:
        b.append(f"<h3>Procjena prema stvarnom ({esc(model.TARGET_NAMES[main['cilj']])})</h3>"
                 "<p class=pt-note>Lansiranja provjere podijeljena u deset jednakih skupina po procjeni; dobro "
                 "kalibrirano znači da su stupci slični.</p>")
        b.append(table(["Skupina", ("Lansiranja", "n"), "Procjena", "Stvarno"],
                       [[str(c[0]), (str(c[1]), c[1], "n"), _pct(c[2], 2), _pct(c[3], 2)] for c in cal], tid="bmkal"))
    fac = main["detail"].get("cimbenici") or []
    if fac:
        b.append("<h3>Što najviše utječe</h3><ul>" + "".join(
            f"<li>{esc(f[0])}: {esc(f[2])} {esc(f[1])} šansu</li>" for f in fac[:6]) + "</ul>")
    b.append("</div></details>")
    return "".join(b)
