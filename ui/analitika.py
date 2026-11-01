"""The "Analitika" page: how people find memesonar.app on Google, from Google Search Console (analytics/gsc.py →
analytics.db). Last 28 complete days against the 28 before: clicks, impressions, CTR, average position, a daily chart,
"almost on page one" queries (where a better page pays off most), top queries, pages, countries and devices.
Without the key it shows the setup steps instead."""
import datetime as dt
import os
import sqlite3
import urllib.parse

from analytics import gsc
from ui import charts
from ui.html import ago, esc, table, tdesc

DEVICES = {"MOBILE": "📱 Mobitel", "DESKTOP": "💻 Računalo", "TABLET": "📟 Tablet"}


def _con():
    if not os.path.exists(gsc.DB) or not os.path.getsize(gsc.DB):
        return None
    try:
        return gsc.connect(gsc.DB)
    except sqlite3.Error:
        return None


def _stat(v, label, change=""):
    return f"<div class=stat><div class=v>{v}</div><div class=l>{esc(label)} {change}</div></div>"


def _chg(cur, prev, better_up=True, pct=True):
    if cur is None or prev in (None, 0):
        return ""
    d = (cur - prev) / prev if pct else cur - prev
    if abs(d) < (0.005 if pct else 0.05):
        return "<span class=mut>(isto)</span>"
    good = (d > 0) == better_up
    txt = f"{d * 100:+.0f}%" if pct else f"{d:+.1f}"
    return f"<span class={'pos' if good else 'neg'}>({txt})</span>"


def _totals(con, a, b):
    r = con.execute("SELECT SUM(clicks), SUM(impressions), SUM(position * impressions) FROM gsc_daily "
                    "WHERE day BETWEEN ? AND ?", (a, b)).fetchone()
    c, i, pw = r
    if not i:
        return {"clicks": c or 0, "impr": i or 0, "ctr": None, "pos": None}
    return {"clicks": c or 0, "impr": i, "ctr": (c or 0) / i, "pos": pw / i}


def _top(con, kind, period="cur"):
    return con.execute("SELECT key, clicks, impressions, ctr, position FROM gsc_top WHERE kind=? AND period=? "
                       "ORDER BY clicks DESC, impressions DESC", (kind, period)).fetchall()


def _ctr(x):
    return (f"{x * 100:.1f}%", x, "n") if x is not None else ("–", 0, "n")


def _pos(x):
    return (f"{x:.1f}", x, "n") if x is not None else ("–", 0, "n")


def _short_page(url):
    p = urllib.parse.urlparse(url)
    path = p.path or "/"
    return f'<a href="{esc(url)}" target=_blank rel=noopener>{esc(path if len(path) <= 48 else path[:46] + "…")}</a>'


def _rows(rows, fmt_key, prev=None):
    prev = prev or {}
    out = []
    for k, c, i, ctr, pos in rows:
        pc = prev.get(k)
        trend = _chg(c, pc[0], True) if pc and pc[0] else ("<span class=mut>novo</span>" if not pc else "")
        out.append([fmt_key(k), (f"{c:,.0f} {trend}", c, "n"),
                    (f"{i:,.0f}", i, "n"), _ctr(ctr), _pos(pos)])
    return out


HEAD = ["Upit", ("Klikovi", "n"), ("Prikazi", "n"), ("CTR", "n"), ("Prosj. pozicija", "n")]


def setup_html(err=None):
    email = gsc.account_email()
    steps = [
        'Otvori <a href="https://console.cloud.google.com" target=_blank rel=noopener>Google Cloud konzolu</a> i napravi '
        'novi projekt (npr. "MemeSonar").',
        'APIs &amp; Services → Library → <b>Google Search Console API</b> → <b>Enable</b>.',
        'IAM &amp; Admin → Service Accounts → <b>Create service account</b>, ime <code>memesonar-gsc</code>, uloge preskoči → Done.',
        'Klikni na račun → Keys → Add key → <b>JSON</b>; skine se datoteka.',
        f'Search Console → {esc(gsc.site().removeprefix("sc-domain:"))} → Settings → Users and permissions → <b>Add user</b> → '
        + (f'upiši <b>{esc(email)}</b>' if email else 'upiši e-mail računa (završava na .iam.gserviceaccount.com)')
        + ', dovoljno je Restricted.',
        'Render → crypto-bot → Environment → <code>GSC_SERVICE_ACCOUNT_JSON</code> = cijeli sadržaj JSON datoteke → Save.',
    ]
    head = (f"<div class=card><p class=neg><b>Spajanje ne radi:</b> {esc(err)}</p></div>" if err else
            "<div class=card><p><b>Još nije spojeno.</b> Čim ključ bude na Renderu, podaci se sami povuku za par "
            "minuta i zatim svakih 6 sati.</p></div>")
    return (head + "<h2>Kako spojiti Google Search Console</h2>"
            + tdesc("Jednom, oko 5 minuta. Besplatno. Ključ se nikad ne lijepi u chat, samo na Render.")
            + "<ol>" + "".join(f"<li>{s}</li>" for s in steps) + "</ol>")


def page(qs=None):
    title = "Analitika"
    body = ["<h1>📈 Analitika</h1>",
            tdesc("Koliko ljudi nas nađe na Googleu, preko kojih riječi i na kojim stranicama. Izvor: Google Search "
                  "Console. Google kasni oko 2 dana, pa su zadnja 2 dana uvijek nepotpuna i ne broje se.")]
    try:
        gsc.key_info()
        key_err = None
    except gsc.GscError as e:
        key_err = str(e)
    con = _con()
    m = gsc.meta(con) if con else {}
    have = con.execute("SELECT COUNT(*) FROM gsc_daily").fetchone()[0] if con else 0
    if not gsc.configured() or key_err or (not have and m.get("last_error")) or not have:
        if gsc.configured() and not key_err and not m.get("last_error"):
            body.append("<div class=card><p><b>Ključ je postavljen.</b> Prvo povlačenje podataka kreće par minuta nakon "
                        "pokretanja servera; osvježi stranicu malo kasnije.</p></div>")
        else:
            body.append(setup_html(key_err or m.get("last_error")))
        if con:
            con.close()
        return title, "".join(body)
    try:
        cs, ce = (m.get("cur") or "|").split("|")
        ps, pe = (m.get("prev") or "|").split("|")
        if not cs:
            a, b, c_, d_ = gsc.periods()
            cs, ce, ps, pe = str(a), str(b), str(c_), str(d_)
        cur, prev = _totals(con, cs, ce), _totals(con, ps, pe)
        if m.get("last_error"):
            body.append(f"<div class=card><p class=neg><b>Zadnje osvježavanje nije uspjelo:</b> {esc(m['last_error'])}"
                        "</p><p class=mut>Prikazani su zadnji dobri podaci.</p></div>")
        fmt = lambda s: dt.date.fromisoformat(s).strftime("%d.%m.")  # noqa: E731
        body.append(f"<p class=mut>Zadnjih 28 dana ({fmt(cs)}–{fmt(ce)}) u zagradi usporedba s 28 dana prije. "
                    f"Osvježeno {ago(int(m.get('last_ok') or 0))[0]}.</p>")
        body.append("<div class=grid>"
                    + _stat(f"{cur['clicks']:,.0f}", "Klikovi", _chg(cur["clicks"], prev["clicks"]))
                    + _stat(f"{cur['impr']:,.0f}", "Prikazi", _chg(cur["impr"], prev["impr"]))
                    + _stat(_ctr(cur["ctr"])[0], "CTR", _chg(cur["ctr"], prev["ctr"]))
                    + _stat(_pos(cur["pos"])[0], "Prosječna pozicija",
                            _chg(cur["pos"], prev["pos"], better_up=False, pct=False))
                    + "</div>")
        days = con.execute("SELECT day, clicks, impressions FROM gsc_daily WHERE day >= ? ORDER BY day",
                           (str(dt.date.fromisoformat(ce) - dt.timedelta(days=89)),)).fetchall()
        ts_ = lambda d: int(dt.datetime.fromisoformat(d).replace(tzinfo=dt.timezone.utc).timestamp())  # noqa: E731
        body.append(charts.line([{"name": "Klikovi", "pts": [(ts_(d), c) for d, c, _ in days]}],
                                "Klikovi po danu", "Zadnjih 90 dana; koliko je ljudi kliknulo na nas u Googleu."))
        body.append(charts.line([{"name": "Prikazi", "pts": [(ts_(d), i) for d, _, i in days]}],
                                "Prikazi po danu", "Koliko puta se naša stranica pojavila u rezultatima pretrage."))

        queries = _top(con, "query")
        prevq = {k: (c, i) for k, c, i, _, _ in _top(con, "query", "prev")}
        near = sorted([r for r in queries if 4.5 <= (r[4] or 0) <= 20 and r[2] >= 20], key=lambda r: -r[2])[:15]
        body.append("<h2>Blizu vrha</h2>"
                    + tdesc("Tu se isplati poboljšati stranicu: upiti s puno prikaza na kojima smo na poziciji 5 do 20. Malo bolja stranica (naslov, "
                            "tekst, poveznice) ovdje donese najviše novih klikova.")
                    + table(HEAD, _rows(near, esc, prevq), "gscnear",
                            empty="Još nema takvih upita (treba barem 20 prikaza na poziciji 5-20)."))
        body.append("<h2>Upiti</h2>" + tdesc("Što ljudi upisuju u Google prije nego nas nađu. Google skriva rijetke "
                                            "upite radi privatnosti, pa zbroj ne daje ukupne klikove.")
                    + table(HEAD, _rows(queries, esc, prevq), "gscq", empty="Još nema upita."))
        prevp = {k: (c, i) for k, c, i, _, _ in _top(con, "page", "prev")}
        body.append("<h2>Stranice</h2>" + tdesc("Koje naše stranice Google najviše prikazuje i klika.")
                    + table(["Stranica"] + HEAD[1:], _rows(_top(con, "page"), _short_page, prevp), "gscp",
                            empty="Još nema stranica."))
        body.append("<h2>Zemlje</h2>" + table(["Zemlja"] + HEAD[1:], _rows(_top(con, "country"), lambda k: esc(k.upper())),
                                              "gscc"))
        body.append("<h2>Uređaji</h2>" + table(["Uređaj"] + HEAD[1:],
                                               _rows(_top(con, "device"), lambda k: esc(DEVICES.get(k, k.title()))), "gscd"))
        body.append(f"<p class=mut>Svojstvo {esc(m.get('site') or gsc.site())}, račun {esc(gsc.account_email() or '–')}. "
                    f"Podaci se osvježavaju svakih {os.environ.get('GSC_EVERY_H', '6')} h.</p>")
    finally:
        con.close()
    return title, "".join(body)
