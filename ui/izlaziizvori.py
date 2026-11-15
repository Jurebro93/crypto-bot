"""Naučeni izlazi po izvoru (15.11., izlazi/): a compact section on /izlazi and the full table on /izlazi/izvori.
Read-only on izlazi.db (the nightly run_izlazi.py writes it)."""
import datetime as dt

from ui.html import badge, esc, lead, note, num, signed, table


def _p(x):
    return signed(x, "{:+.2f} %") if isinstance(x, (int, float)) else ("–", -1e18, "n")


def _share(x):
    return (f"{x:.0%}" if isinstance(x, (int, float)) else "–", x if isinstance(x, (int, float)) else -1, "n")


def _rows(rows, limit):
    from izlazi import apply, report, sim, store
    out = []
    for r in report.rows_sorted(rows, top=limit):
        st = r.get("stats") or {}
        ok, why = store.proven(r)
        own = st.get("own") or {}
        out.append([esc(apply.key_words((r["source_kind"], r["source_id"]))),
                    esc(sim.words(sim.from_dict(r["params"]))), num(r["n"]), num(r["n_out"]), _p(r.get("ev_out")),
                    _p(r.get("default_ev_out")),
                    esc(f"{r['ci_lo']:+.1f} .. {r['ci_hi']:+.1f} %") if r.get("ci_lo") is not None else "–",
                    _share(st.get("hit_out")),
                    badge("pravi novac", "good") if ok else badge("samo demo", "") + f" <span class=mut>{esc(why)}</span>",
                    esc(f"{st.get('mae_win_p50', '–')} / {st.get('mae_win_p75', '–')} %"),
                    esc(f"{own.get('own_stop_p50', '–')} / {own.get('own_stop_p75', '–')} %") if own else "–"])
    return out


HEAD = ["Koga pratimo", "Naučeno pravilo", ("ulaza", "n"), ("van uzorka", "n"), ("EV van uzorka", "n"),
        ("brzi profit van uzorka", "n"), "90 % interval", ("trejdova u plusu", "n"), "Novac",
        "dobitnici prvo padnu p50/p75", "njegov stop p50/p75"]
DESC = ("Svaki izvor dobije svoj stop, grace, TP1, trailing i vremenski stop, izabrane na starijih 70 % ulaza i "
        "provjerene na novijih 30 %, nakon troška; demo ih koristi odmah, pravi novac tek kad su van uzorka bolji od "
        "brzog profita.")


def section_html(limit=8):
    """The compact block for /izlazi ('' on any error: the page never breaks on it)."""
    try:
        from izlazi import store
        rows = store.load()
        if not rows:
            return ("<h2>Naučeni izlazi po izvoru</h2><div class=card>Još nema izračuna: noćni posao "
                    "(run_izlazi.py, 01–06) ih računa iz naših putanja cijena.</div>")
        ts = max(r["ts"] for r in rows.values())
        return ("<h2>Naučeni izlazi po izvoru</h2>" + lead(DESC)
                + note(f"Izračun {dt.datetime.fromtimestamp(ts):%d.%m. %H:%M}; otvorena pozicija zadržava pravilo s "
                       "kojim je otvorena.")
                + table(HEAD, _rows(rows, limit)) + '<p><a href="/izlazi/izvori">Svi izvori i priori →</a></p>')
    except Exception as e:  # noqa: BLE001
        print(f"izlazi: naučeni izlazi po izvoru: {type(e).__name__}: {e}")
        return ""


def page(qs=None):
    from izlazi import report, sim, store
    rows = store.load()
    b = ["<h1>Naučeni izlazi po izvoru</h1>", lead(DESC)]
    if not rows:
        b.append("<div class=card>Još nema izračuna (noćni posao run_izlazi.py, 01–06 Zagreb).</div>")
        return "Naučeni izlazi", "".join(b)
    pri = sorted((r for r in rows.values() if r["source_id"] == "*"), key=lambda r: r["source_kind"])
    b.append("<h2>Priori</h2>" + table(
        ["Vrsta izvora", "Pravilo", ("ulaza", "n"), ("van uzorka", "n"), ("EV van uzorka", "n"),
         ("brzi profit van uzorka", "n")],
        [[esc(report.KIND_HR.get(r["source_kind"], r["source_kind"])), esc(sim.words(sim.from_dict(r["params"]))),
          num(r["n"]), num(r["n_out"]), _p(r.get("ev_out")), _p(r.get("default_ev_out"))] for r in pri]))
    b.append("<h2>Izvori</h2>" + table(HEAD, _rows(rows, None), tid="izl"))
    return "Naučeni izlazi", "".join(b)
