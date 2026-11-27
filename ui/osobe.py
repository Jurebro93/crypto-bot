"""/osobe and /osobe/<id>: "Osobe iza novčanika" (27.11., vlasnik; osobe/). Logged-in pages only, noindex (run_ui.py
sends X-Robots-Tag noindex for every page behind the login; nothing here is in the sitemap or share/novosti).

List: persons (groups of wallets one person probably runs) with an invented nickname, one reason and the realized
result; the group call power (how a token moves after 1, 2-3 or 4+ tracked accounts call it together, after cost).
Profile: the reasons in plain words, wallets, tokens and themes, timing against pumps, bundles, the result.

The possible links to tracked X accounts are shown to the OWNER only ("moguća veza, X %" with the evidence, never as
a fact; defamation risk, see osobe/xveza.py) and the owner can hide each one. Results only: no weights, thresholds
or formulas on the page (the owner wants the method hidden). Mobile first, Croatian.
"""
import json
import time
from urllib.parse import quote

from osobe import store, xveza
from ui import redak as R
from ui.html import esc

PATH = "/osobe"
LIMIT = 150
CSS = """
.os p,.os li{font-size:15px;line-height:1.45;margin:4px 0;overflow-wrap:anywhere}
.os ul{margin:0;padding:0 0 0 18px}
.os .os-note{background:var(--soft);border-radius:14px;padding:14px 16px;margin:16px 0 0}
.os code{font-size:14px}
.os form{display:inline}
.os button{font:inherit;font-size:14px;border:1px solid var(--line);background:transparent;border-radius:10px;padding:4px 10px;cursor:pointer}
.os .ms-row .ms-s{white-space:normal}
"""
CAVEAT = ("Osoba je skupina novčanika za koje podaci pokazuju da ih vjerojatno vodi ista osoba ili ekipa. To je "
          "statistički zaključak iz javnih on-chain podataka, ne dokazana činjenica. Imena su izmišljena.")
X_CAVEAT = ("Moguća veza s praćenim X računom je procjena iz javnih podataka, nije činjenica ni tvrdnja o nečijoj "
            "namjeri. Vidiš je samo ti; sakrij svaku koja ti ne izgleda uvjerljivo.")
BUCKET_HR = {"1": "Jedan influencer", "2-3": "2–3 influencera zajedno", "4+": "4 i više zajedno"}


def _con():
    return store.ro(store.db_path())


def _w(a):
    return (f'<a href="https://solscan.io/account/{quote(a)}" target=_blank rel="noopener noreferrer" title="{esc(a)}">'
            f'<code>{esc(a[:4])}…{esc(a[-4:])}</code></a>')


def _conf_word(c):
    if c is None:
        return "jedan novčanik"
    return "jaka veza" if c >= 0.8 else "dobra veza" if c >= 0.6 else "slabija veza"


def _person(row):
    pid, members, n, conf, name, traits, prof, pnl, first, last, upd = row
    try:
        prof = json.loads(prof or "{}")
    except ValueError:
        prof = {}
    return {"pid": pid, "n": n, "conf": conf, "name": name, "profile": prof, "pnl": pnl, "first": first, "last": last,
            "updated": upd}


def _rank(d):
    t = (d["profile"].get("timing") or {})
    return (-(t.get("pre_pump") or 0), -(d["pnl"] or 0), -d["n"])


def _sol(x):
    return R.sol(x, 2, sign=True) if x is not None else R.DASH


def _group_html(g):
    if not g or not g.get("events"):
        return str(R.hint("Mjerenje grupnih poziva još nema dovoljno podataka."))
    items = []
    for b in ("1", "2-3", "4+"):
        s24 = (g["sizes"].get(b) or {}).get("24h") or {}
        s1 = (g["sizes"].get(b) or {}).get("1h") or {}
        if not s24.get("n") and not s1.get("n"):
            items.append(R.row(BUCKET_HR[b], "još nema događaja", muted=True))
            continue
        why = []
        if s1.get("n"):
            why.append(f"prvi sat {R.pct(s1.get('mean'), frac=True)}")
        if s24.get("pos_share") is not None:
            why.append(f"u plusu {R.pct(s24['pos_share'], sign=False, frac=True)}")
        if s24.get("sold_into_share"):
            why.append(f"povezane osobe prodale u {R.pct(s24['sold_into_share'], sign=False, frac=True)} poziva")
        items.append(R.row(BUCKET_HR[b], " · ".join(why), R.pct(s24.get("mean"), frac=True) if s24.get("n") else R.DASH,
                           f"{s24.get('n') or s1.get('n')} događaja", value_tone=R.tone(s24.get("mean"))))
    out = (str(R.colhead("Koliko ih zove", "24 h, nakon troška")) + str(R.rows(items))
           + str(R.hint("Kretanje cijene iznad onoga što token inače radi, nakon realnog troška kupnje i prodaje.")))
    pairs = [x for x in g.get("pairs") or [] if x.get("x24") is not None][:10]
    if pairs:
        out += str(R.section("Parovi koji zovu zajedno", sid="parovi")) + str(R.rows([
            R.row(" + ".join("@" + h for h in x["handles"]), f"{x['n']} zajedničkih poziva"
                  + (f" · povezane osobe prodale u {R.pct(x['sold_into_share'], sign=False, frac=True)}"
                     if x.get("sold_into_share") else ""),
                  R.pct(x["x24"], frac=True), "24 h", value_tone=R.tone(x["x24"]),
                  href="/kol/" + quote(x["handles"][0]))
            for x in pairs]))
    return out


def page(qs=None, user=None, now=None):
    """(title, html) of the list."""
    now = int(now or time.time())
    qs = qs or {}
    con = _con()
    top = R.top("Osobe iza novčanika", "Novčanici grupirani u osobe, s izmišljenim imenima")
    head = f'<div class="ms-page os"><style>{CSS}</style>{top}<div class=os-note><p>{esc(CAVEAT)}</p></div>'
    if con is None:
        return "Osobe", head + str(R.hint("Prvi noćni prolaz još nije odrađen.")) + "</div>"
    try:
        rows = [_person(r) for r in store.q(con, "SELECT * FROM os_persons")]
        summ = store.kv(con, "zadnji") or {}
        g = store.kv(con, "grupe")
        find = (qs.get("q") or "").strip()
        hit = None
        if find:
            r = store.q(con, "SELECT pid FROM os_member WHERE wallet = ?", (find,))
            hit = r[0][0] if r else None
    finally:
        con.close()
    rows.sort(key=_rank)
    body = head
    if summ:
        body += str(R.hint(f"Zadnji prolaz {R.ago(summ.get('ts'), now)}: {summ.get('persons', 0)} osoba, "
                           f"{summ.get('wallets', 0)} novčanika."))
    body += ('<form method=get action="/osobe"><input name=q placeholder="Adresa novčanika" '
             f'value="{esc(find)}" style="width:70%"> <button>Traži</button></form>')
    if find:
        body += str(R.hint("Novčanik pripada osobi ispod." if hit else "Taj novčanik nije u nijednoj osobi."))
        if hit:
            rows = [d for d in rows if d["pid"] == hit] + [d for d in rows if d["pid"] != hit]
    items = []
    for i, d in enumerate(rows[:LIMIT], 1):
        reasons = d["profile"].get("reasons") or []
        items.append(R.row(d["name"], reasons[0] if reasons else _conf_word(d["conf"]), _sol(d["pnl"]),
                           f"{d['n']} novčanika", href=f"{PATH}/{quote(d['pid'])}", rank=i,
                           value_tone=R.tone(d["pnl"])))
    body += str(R.section("Osobe", sid="osobe")) + str(R.rows(items, empty="Još nema osoba."))
    body += str(R.section("Moć grupnih poziva", sid="grupe")) + _group_html(g)
    body += str(R.hint("Stranica nije javna i ništa s nje ne ide u objave.")) + "</div>"
    return "Osobe", body


def _xlinks_html(con, pid):
    rows = xveza.visible(con, pid)
    if not rows:
        return str(R.hint("Nema moguće veze s praćenim X računom koja bi bila dovoljno uvjerljiva."))
    out = [f"<div class=os-note><p>{esc(X_CAVEAT)}</p></div><ul>"]
    for _p, h, prob, ev in rows:
        why = "; ".join(xveza.text(ev)) or "više slabih tragova"
        out.append(f"<li><b>@{esc(h)}</b>: moguća veza, {esc(R.pct(prob, sign=False, frac=True))} "
                   f"(dokazi: {esc(why)}) "
                   f'<form method=post action="/osobe/sakrij"><input type=hidden name=pid value="{esc(pid)}">'
                   f'<input type=hidden name=handle value="{esc(h)}"><button>Sakrij</button></form></li>')
    return "".join(out) + "</ul>"


def profile_page(pid, qs=None, user=None, now=None, owner=False):
    now = int(now or time.time())
    back = f'<p class=ms-hint><a href="{PATH}">‹ Osobe</a></p>'
    con = _con()
    r = store.q(con, "SELECT * FROM os_persons WHERE pid = ?", (pid,)) if con is not None else []
    if not r:
        if con is not None:
            con.close()
        return "Osoba", (f'<div class="ms-page os"><style>{CSS}</style>{back}{R.top("Osoba")}'
                         + str(R.hint("Ta osoba više nije na popisu (novčanici su se razdvojili ili prolaz još nije "
                                      "odrađen).")) + "</div>")
    try:
        d = _person(r[0])
        x_html = _xlinks_html(con, pid) if owner else ""
    finally:
        con.close()
    pr = d["profile"]
    t, b, pn, tk = pr.get("timing") or {}, pr.get("bundle") or {}, pr.get("pnl") or {}, pr.get("tokens") or {}
    reasons = pr.get("reasons") or []
    facts = f"{d['n']} novčanika · {_conf_word(d['conf'])}"
    body = (f'<div class="ms-page os"><style>{CSS}</style>{back}'
            + str(R.verdict(d["name"], reasons[0] if reasons else None, label="Osoba iza novčanika", facts=facts,
                            kind="acc"))
            + (("<ul>" + "".join(f"<li>{esc(x)}</li>" for x in reasons[1:]) + "</ul>") if len(reasons) > 1 else ""))
    res = [R.row("Ostvareno", f"{pn.get('closed') or 0} zatvorenih pozicija", _sol(pn.get("realized_sol")),
                 value_tone=R.tone(pn.get("realized_sol")))] if pn else []
    if pn.get("win_rate") is not None and pn.get("closed"):
        res.append(R.row("Udio dobitnih", None, R.pct(pn["win_rate"], sign=False, frac=True)))
    if pn.get("median_hold_min") is not None:
        res.append(R.row("Obično drži", None, _hold(pn["median_hold_min"])))
    body += str(R.section("Rezultat")) + str(R.rows(res, empty="Za ove novčanike još nemamo raščlanjene trejdove."))
    tim = []
    if t.get("events"):
        tim.append(R.row("Pumpe na kojima se pojavio", None, str(t["events"])))
        tim.append(R.row("Kupio prije pumpe", None, str(t.get("pre_pump") or 0)))
        tim.append(R.row("Prodao u rast", None, str(t.get("sold_into") or 0)))
        if t.get("big_pumps"):
            tim.append(R.row("Od toga velike pumpe", None, str(t["big_pumps"])))
    body += str(R.section("Ulaz i izlaz oko pumpi")) + str(R.rows(tim, empty="Nije viđen oko izmjerenih pumpi."))
    if t.get("examples"):
        body += str(R.rows([R.row(x.get("symbol") or x["token"][:6] + "…",
                                  "prodao u rast" if x.get("sold_into") else "kupio prije", mint=x["token"])
                            for x in t["examples"]]))
    bun = []
    if b.get("bundles"):
        bun.append(R.row("Snopovi na lansiranju", f"na {b.get('bundle_pumps') or 0} pumpi", str(b["bundles"])))
    if b.get("launch_bundle_buys"):
        bun.append(R.row("Kupnje u snopu", None, str(b["launch_bundle_buys"])))
    if bun:
        body += str(R.section("Snopovi (bundle)")) + str(R.rows(bun))
    toks = [R.row(x.get("symbol") or x["mint"][:6] + "…", None, f"{x['buys']}×", mint=x["mint"])
            for x in (tk.get("top") or [])]
    body += (str(R.section("Tokeni", f"{tk.get('n_tokens') or 0} ukupno")) if toks else "") + str(R.rows(toks))
    body += str(R.section("Novčanici")) + "<ul>" + "".join(
        f"<li>{_w(w['wallet'])}</li>" for w in pr.get("wallets") or []) + "</ul>"
    body += str(R.section("Kopiranje")) + str(R.hint((pr.get("copy") or {}).get("note") or "Još se ne mjeri."))
    if owner:
        body += str(R.section("Moguće veze s X računima", sid="x")) + x_html
    body += str(R.hint(CAVEAT)) + "</div>"
    return d["name"], body


def _hold(m):
    if m >= 1440:
        return f"{R.num(m / 1440, 1)} d"
    if m >= 60:
        return f"{R.num(m / 60, 1)} h"
    return f"{R.num(m, 0)} min"


def post(path, form, user, now=None):
    """POST /osobe/sakrij (owner only, checked in run_ui.py too): hide one X link for good. -> redirect target."""
    from trade import settings
    pid = (form.get("pid") or "").strip()[:20]
    handle = (form.get("handle") or "").strip().lstrip("@")[:30]
    if path != "/osobe/sakrij" or not settings.is_owner(user) or not pid or not handle:
        return PATH
    con = store.connect()
    try:
        xveza.hide(con, pid, handle, str(user or ""), now or time.time())
        con.commit()
    finally:
        con.close()
    return f"{PATH}/{quote(pid)}#x"
