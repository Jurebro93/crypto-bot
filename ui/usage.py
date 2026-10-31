"""The "Potrošnja" page: Helius credits and Apify dollars this cycle, burn rate, which script spends what,
and the warnings from usage/watch.py. banner() puts active warnings on top of every page."""
import datetime as dt
import os
import sqlite3
import time

from ui.html import ago, badge, bar, esc, num, table, tdesc, ts
from usage import meter, watch

_cache = {"ts": 0, "alerts": []}


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _size(path):
    """Bytes in a file or (recursively) a directory."""
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def disk_html():
    """Free space on the persistent disk and what takes it: a full disk stops every database write."""
    import shutil
    from event_calendar import http
    data_dir = os.environ.get("DATA_DIR") or HERE
    try:
        du = shutil.disk_usage(data_dir)
    except OSError:
        return ""
    free_pct = du.free / du.total if du.total else 0
    level = "ok" if free_pct > 0.2 else "warn" if free_pct > 0.08 else "crit"
    parts = [("HTTP cache", http.CACHE_DIR)] + [(f, os.path.realpath(os.path.join(HERE, f)))
                                                 for f in sorted(os.listdir(HERE)) if f.endswith(".db")] \
        + [("output/", os.path.realpath(os.path.join(HERE, "output")))]
    rows = sorted(((n, _size(p)) for n, p in parts if os.path.exists(p)), key=lambda x: -x[1])
    return ("<h2>Disk</h2>" + tdesc(f"Trajni disk ({esc(data_dir)}): baze, cache i izvještaji. Pun disk ruši svako "
                                    f"spremanje. Cache se sam čisti na {http.CACHE_MAX_MB:.0f} MB i briše sve starije od "
                                    f"{http.CACHE_MAX_AGE // 86400} dana.")
            + f'<div class=card>{badge({"ok": "OK", "warn": "malo mjesta", "crit": "skoro pun"}[level],
                    {"ok": "good", "warn": "warn", "crit": "bad"}[level])} '
              f'{bar(1 - free_pct, 1, 160)} zauzeto <b>{du.used / 1e9:.2f} GB</b> od {du.total / 1e9:.2f} GB, '
              f'slobodno <b>{du.free / 1e6:,.0f} MB</b> ({free_pct:.0%})</div>'
            + table(["Što", ("MB", "n")], [[esc(n), num(b / 1e6, "{:,.1f}")] for n, b in rows]))


def _con():
    if not os.path.exists(meter.DB):
        return None
    return sqlite3.connect(f"file:{meter.DB}?mode=ro", uri=True, timeout=10)


def alerts():
    """Live warnings, cached for a minute so every page view stays cheap."""
    if time.time() - _cache["ts"] > 60:
        con = _con()
        try:
            _cache["alerts"] = watch.evaluate(con) if con else []
        except sqlite3.OperationalError:
            _cache["alerts"] = []
        finally:
            if con:
                con.close()
        _cache["ts"] = time.time()
    return _cache["alerts"]


def banner():
    al = alerts()
    if not al:
        return ""
    kind = "bad" if any(a["level"] == "bad" for a in al) else "warn"
    items = "".join(f"<li class={a['level']}>{esc(a['title'])}</li>" for a in al[:4])
    return (f'<div class=card style="border-color:var(--{kind});background:var(--{kind}bg)">'
            f'<b>⚠ Potrošnja kredita</b> · <a href="/usage">detalji</a><ul class=r>{items}</ul></div>')


def _card(a):
    return (f'<div class=card style="border-left:4px solid var(--{a["level"]})">{badge("HITNO" if a["level"] == "bad" else "PAZI", a["level"])} '
            f'<b>{esc(a["title"])}</b><br><span class=mut>{esc(a["detail"])}</span></div>')


def _service(con, service, cfg):
    st = watch.status(con, service, cfg)
    f = lambda x: watch.fmt(service, x)  # noqa: E731
    pct = st["used"] / st["budget"] * 100 if st["budget"] else 0
    out = st["runs_out"]
    stats = [
        (f"{f(st['used'])} / {f(st['budget'])}", f"potrošeno ovaj ciklus ({pct:.0f}%) {bar(min(pct, 100), 100, 80)}"),
        (f"{f(st['rate_day'])}/dan", f"tempo, izvor: {st['rate_src']} (ravnomjerno {f(st['fair_day'])}/dan)"),
        (f(st["projected"]), "projekcija do kraja ciklusa"),
        (dt.datetime.fromtimestamp(out, dt.timezone.utc).strftime("%d.%m.") if out and out < st["end"] else "ne prije kraja",
         "kad bi budžet nestao ovim tempom"),
        (dt.datetime.fromtimestamp(st["end"], dt.timezone.utc).strftime("%d.%m."), "kraj ciklusa (reset)"),
    ]
    acc = (f"Očitanje s računa {ago(st['account_ts'])[0]}" + (f", limit računa {f(st['account_limit'])}" if st["account_limit"] else "")
           + f"; bot je sam izbrojao {f(st['own'])} ovaj ciklus." if st["account_ts"] else
           "Nema očitanja s računa, brojke su samo ono što je bot sam izbrojao"
           + (" (za Helius dodaj HELIUS_PROJECT_ID u Render env)." if service == "helius" else "."))
    grid = "".join(f'<div class=stat><div class=v>{v}</div><div class=l>{l}</div></div>' for v, l in stats)
    # last 14 days and top spenders
    now = time.time()
    day0 = int(now // 86400 * 86400)
    days = []
    for i in range(13, -1, -1):
        a = watch.counted(con, service, day0 - i * 86400, day0 - (i - 1) * 86400)
        days.append((day0 - i * 86400, a))
    mx = max([a for _, a in days] + [st["fair_day"]]) or 1
    drows = [[ts(d, "%d.%m. %a"), (f(a), a, "n"), bar(a, mx, 200) + (" " + badge("iznad kvote", "warn") if a > st["fair_day"] else "")]
             for d, a in reversed(days)]
    top = con.execute("SELECT script, method, SUM(calls), SUM(errors), SUM(amount) FROM usage WHERE service=? AND hour>=? "
                      "GROUP BY script, method ORDER BY 5 DESC LIMIT 25", (service, int(now) - 86400)).fetchall()
    trows = [[esc(s), f"<code>{esc(m)}</code>", num(n), num(e), (f(a), a, "n")] for s, m, n, e, a in top]
    name = "Helius" if service == "helius" else "Apify"
    unit = "kredita" if service == "helius" else "USD"
    return (f"<h2>{name}</h2><div class=grid>{grid}</div><p class=mut>{esc(acc)}</p>"
            f"<div class=two><div><h3>Po danu ({unit})</h3>"
            + tdesc(f"Ono što je bot sam izbrojao po danu (UTC). Kvota je {f(st['fair_day'])}/dan da budžet traje cijeli ciklus.")
            + table(["Dan", ("Potrošeno", "n"), ""], drows)
            + "</div><div><h3>Tko troši (zadnja 24 h)</h3>"
            + tdesc("Skripta i vrsta poziva. Greške su 429/5xx odgovori; puno grešaka znači petlju koja ponavlja.")
            + table(["Skripta", "Poziv", ("Poziva", "n"), ("Grešaka", "n"), (unit.capitalize(), "n")], trows,
                    empty="Još nema izbrojanih poziva.") + "</div></div>")


def page(qs):
    con = _con()
    head = ("<h1>Potrošnja kredita</h1>"
            "<p class=mut>Helius krediti i Apify dolari: koliko je potrošeno ovaj ciklus, kojim tempom, tko troši, "
            "i upozorenja kad nešto curi ili raste prebrzo. Brojke s računa osvježavaju se svakih 15 min.</p>")
    head += disk_html()
    if con is None:
        return "Potrošnja", head + '<div class=empty>Još nema usage.db: bot još nije napravio nijedan plaćeni poziv.</div>'
    try:
        cfg = watch.config()
        al = watch.evaluate(con, cfg)
        cards = "".join(_card(a) for a in al) or f'<div class=card>{badge("OK", "good")} Nema upozorenja: potrošnja je u okvirima budžeta.</div>'
        hist = con.execute("SELECT level, title, detail, first_ts, last_ts FROM alerts WHERE last_ts>=? ORDER BY last_ts DESC",
                           (int(time.time()) - 14 * 86400,)).fetchall()
        hrows = [[badge(lv, lv), esc(t), f'<span class=mut>{esc(d)}</span>', ts(a), ts(b)] for lv, t, d, a, b in hist]
        body = (head + "<h2>Upozorenja</h2>" + cards + _service(con, "helius", cfg) + _service(con, "apify", cfg)
                + "<h2>Povijest upozorenja (14 dana)</h2>"
                + tdesc("Svako upozorenje koje je provjera svakih 15 min vidjela: kad se prvi i zadnji put pojavilo.")
                + table(["Razina", "Upozorenje", ("Detalj", "wrap"), "Prvi put", "Zadnji put"], hrows,
                        empty="Još nije bilo upozorenja.")
                + "<p class=mut>Pragovi: <code>usage/budget.json</code>. Pravila: budžet nestaje prije kraja ciklusa; "
                  "skripta u 2 h potroši 4x više nego inače (ili 6x ravnomjernu satnu kvotu); dnevna potrošnja raste "
                  "1.5x svaki dan 3 dana zaredom; račun raste brže nego što bot broji (troši nešto izvan bota); "
                  "puno 429/5xx grešaka.</p>")
    finally:
        con.close()
    return "Potrošnja", body
