"""/kol-insajderi: "Insajderski novčanici" (16.11., vlasnik: "Mora postojati stavka 'insider wallet' i algoritam koji
ih traži"; insajderi/kolwallets.py). The OWNER's view only: per influencer of the seed list the state ("pratimo" /
"nema poziva u podacima" / "handle nije potvrđen"), his public wallets with their source, and the wallet groups that
are PROBABLY linked to him: class, calls bought before, share sold into the call, lead time, the link evidence and,
one tap deeper, every call and transaction behind the row.

These are real, named people: every sentence here says "vjerojatno povezani", never a fact about anybody's intent,
and the page is never public (login + owner on the server, noindex by being behind the login, not in the sitemap, not
in share/novosti). Mobile first (390 px): one column, addresses shortened, no table. Croatian, no internal names.
"""
import time
from urllib.parse import quote

from ui import redak as R
from ui.html import esc

PATH = "/kol-insajderi"
DOT = {"pratimo": "good", "nema_poziva": "", "bez_handlea": "warn"}
CLS_DOT = {"potvrđen": "bad", "kandidat": "warn"}
CSS = """
.ki details{border-bottom:1px solid var(--line)}
.ki details>summary{list-style:none;cursor:pointer}
.ki details>summary::-webkit-details-marker{display:none}
.ki details>summary .ms-row{border-bottom:0}
.ki .ki-in{padding:2px 0 16px}
.ki .ki-g{border:0;background:var(--soft);border-radius:14px;margin:10px 0 0;padding:0 14px}
.ki .ki-g .ki-in{padding:0 0 14px}
.ki h3{font-size:15px;font-weight:600;color:var(--mut);margin:16px 0 4px}
.ki p,.ki li{font-size:15px;line-height:1.45;margin:4px 0;overflow-wrap:anywhere}
.ki ul{margin:0;padding:0 0 0 18px}
.ki code{font-size:14px}
.ki .ki-ev{font-size:14px;color:var(--mut)}
.ki .ki-call{margin:10px 0 0;padding:10px 0 0;border-top:1px solid var(--line2)}
.ki .ki-note{background:var(--soft);border-radius:14px;padding:14px 16px;margin:16px 0 0}
.ki a{overflow-wrap:anywhere}
.ki .ms-row .ms-s{white-space:normal}
"""


def _t(ts):
    """"9.11. 14:05" in the app's time zone; "–" unknown."""
    if not ts:
        return R.DASH
    try:
        from ui import kolchart
        d = kolchart._local(int(ts))
    except Exception:  # noqa: BLE001
        d = None
    if d is None:
        return time.strftime("%d.%m. %H:%M", time.gmtime(int(ts)))
    return f"{d.day}.{d.month}. {d:%H:%M}"


def _w(a):
    """A shortened address that opens the public explorer (the full one is in the link and the title)."""
    return (f'<a href="https://solscan.io/account/{quote(a)}" target=_blank rel="noopener noreferrer" title="{esc(a)}">'
            f'<code>{esc(a[:4])}…{esc(a[-4:])}</code></a>')


def _tx(sig, word="transakcija"):
    return (f'<a href="https://solscan.io/tx/{quote(sig)}" target=_blank rel="noopener noreferrer">{esc(word)}</a>'
            if sig and sig != "?" else "")


def _src(url, word="izvor"):
    u = str(url or "")
    if u.startswith("https://"):
        return f' · <a href="{esc(u)}" target=_blank rel="noopener noreferrer">{esc(word)}</a>'
    return f" · {esc(u)}" if u else ""


def _lead(m):
    if m is None:
        return R.DASH
    return f"{R.num(m)} min" if m < 120 else f"{R.num(m / 60, 1)} h" if m < 2880 else f"{R.num(m / 1440, 1)} d"


def _public_html(d):
    from insajderi import kolwallets as kw
    if not d["public"]:
        return "<p>Javni novčanik nije poznat: traže se samo ponavljanja oko njegovih poziva.</p>"
    return "<ul>" + "".join(
        f'<li>{_w(w["address"])} · {esc(kw.WALLET_STATUS_HR.get(w.get("status"), w.get("status") or ""))}'
        f'{_src(w.get("source"))}</li>' for w in d["public"]) + "</ul>"


def _evidence_html(g):
    from insajderi import kolwallets as kw
    out = []
    for c in (g.get("evidence") or {}).get("calls") or []:
        what = ("kupio prije i prodao nakon" if c["front"] and c["sold"] else "kupio prije, nije prodao u 24 h"
                if c["front"] else "prodao nakon")
        head = (f'<b>{esc(c.get("symbol") or c["token"][:6])}</b> · {esc(kw.KIND_HR.get(c["kind"], c["kind"]))} '
                f'{esc(_t(c["t0"]))} · {what}'
                + (f' · <a href="{esc(c["url"])}" target=_blank rel="noopener noreferrer">poziv</a>'
                   if str(c.get("url") or "").startswith("https://") else ""))
        ws = []
        for w in c["wallets"]:
            bits = []
            if w.get("last_buy"):
                bits.append(f'kupnja {esc(_t(w["last_buy"]))}'
                            + (f' ({esc(R.sol(w["sol_in"], 2))})' if w.get("sol_in") is not None else ""))
            if w.get("first_sell"):
                bits.append(f'prodaja {esc(_t(w["first_sell"]))}'
                            + (f' ({esc(R.sol(w["sol_out"], 2))})' if w.get("sol_out") is not None else ""))
            txs = " ".join(_tx(x["sig"], "kupnja" if x["side"] == "buy" else "prodaja") for x in w.get("tx") or [])
            ws.append(f'<li>{_w(w["wallet"])}: {", ".join(bits) or "–"}{" · " + txs if txs else ""}</li>')
        out.append(f'<div class=ki-call><p>{head}</p><ul class=ki-ev>{"".join(ws)}</ul></div>')
    return "".join(out) or "<p class=ki-ev>Nema spremljenih poziva za ovaj redak.</p>"


def _group_html(g):
    share = R.pct(g["share_sold"], frac=True, sign=False) if g["share_sold"] is not None else R.DASH
    facts = R.cat(R.dot(CLS_DOT.get(g["cls"], ""), g["cls"]),
                  f" · {g['n_front']} poziva · prodao nakon {share} · {_lead(g['med_lead_min'])} prije")
    name = R.raw(f"<code>{esc(g['members'][0][:4])}…{esc(g['members'][0][-4:])}</code>"
                 + (f" + još {len(g['members']) - 1}" if len(g["members"]) > 1 else ""))
    ev = g.get("evidence") or {}
    nums = [f"Kupio prije <b>{g['n_front']}</b> njegovih poziva; nakon poziva prodao u <b>{g['n_sold']}</b> "
            f"(u prvih sat vremena {g['n_sold60']}).",
            f"Zadnja kupnja prije poziva, medijan: <b>{esc(_lead(g['med_lead_min']))}</b>"
            + (f" (do 10 min: {ev['buckets'].get('<10 min', 0)}, do 24 h: {ev['buckets'].get('<24 h', 0)}, do 7 dana: "
               f"{ev['buckets'].get('<7 d', 0)})." if ev.get("buckets") else ".")]
    if g.get("lift") is not None:
        nums.append(f"Prema slučajnosti: <b>{esc(R.num(g['lift'], 1))}×</b> češće nego što bi se očekivalo "
                    f"(uspoređeno na {ev.get('u', R.DASH)} događaja; ova grupa je rano kupila u {ev.get('n_w', R.DASH)} "
                    f"od njih, od toga {esc(R.pct(g['exclusivity'], frac=True, sign=False))} su njegovi pozivi).")
    if g["sol_in"] or g["sol_out"]:
        nums.append(f"Uloženo prije poziva {esc(R.sol(g['sol_in'], 2))}, prodano nakon poziva {esc(R.sol(g['sol_out'], 2))} "
                    "(samo ono što vidimo u podacima).")
    links = "".join(f'<li>{_w(lk["wallet"])} → {_w(lk["public"])}: {esc(lk.get("text") or "")}'
                    f'{" · " + " ".join(_tx(s) for s in lk.get("sigs") or []) if lk.get("sigs") else ""}</li>'
                    for lk in g.get("links") or [])
    inner = (f'<p>{esc(g["why"] or "")}.</p><h3>Novčanici grupe</h3><p>{", ".join(_w(w) for w in g["members"])}</p>'
             f'<h3>Brojke</h3><ul>{"".join(f"<li>{x}</li>" for x in nums)}</ul>'
             f'<h3>Veza s javnim novčanikom</h3>'
             + (f"<ul>{links}</ul>" if links else "<p>Nema poznate veze: zaključak stoji samo na ponavljanju oko "
                                                  "poziva.</p>")
             + f'<h3>Dokazi (pozivi i transakcije)</h3>{_evidence_html(g)}')
    return (f'<details class=ki-g><summary>{R.row(name, facts)}</summary><div class=ki-in>{inner}</div></details>')


def _inf_html(d):
    hs = [h for h in d["handles"] if not h.startswith("tg:")]
    who = ", ".join("@" + h for h in hs)
    n = len(d["wallets"])
    value = str(n) if n else None
    sub = (f"{d['n_confirmed']} potvrđ." if d["n_confirmed"] else "kandidati") if n else None
    head = R.row(d["name"], R.cat(R.dot(DOT.get(d["status"], ""), d["status_hr"]), f" · {who}" if who else ""),
                 value=value, sub=sub)
    if d["status"] == "bez_handlea":
        body = "<p>Ne znamo njegov račun, pa ne znamo ni njegove pozive. Ništa se ne pogađa: upiši handle kad ga znaš.</p>"
    elif d["status"] == "nema_poziva":
        body = ("<p>U našim podacima još nema njegovih objava s adresom tokena ni kupnji njegova javnog novčanika, pa "
                "nema što usporediti.</p>")
    elif not n:
        body = (f"<p>{d['n_calls']} poziva u podacima ({d['n_covered']} s tradeovima oko poziva): nijedan novčanik se "
                "ne ponavlja dovoljno da bi bio na popisu.</p>")
    else:
        body = (f"<p>{d['n_calls']} poziva u podacima, {d['n_covered']} s tradeovima oko poziva.</p>"
                + "".join(_group_html(g) for g in d["wallets"]))
    note = f"<p class=ki-ev>{esc(d['note'])}</p>" if d.get("note") else ""
    return (f'<details id="ki-{esc(d["id"])}"><summary>{head}</summary><div class=ki-in>'
            f'<h3>Javni novčanici</h3>{_public_html(d)}{note}<h3>Vjerojatno povezani novčanici</h3>{body}</div></details>')


def _pred_html(now):
    from insajderi import kolwallets as kw
    rows, st = kw.pred_rows(limit=20)
    if not st or not st.get("n"):
        return R.hint("Još nema događaja: bilježi se kad potvrđena grupa kupi token koji influencer još nije objavio.")
    names = {d["id"]: d["name"] for d in kw.view(evidence=False)}
    head = (f"<p>{st['n']} događaja, zaključeno {st['settled']}: u {st['called']} ga je poslije i objavio"
            + (f" ({esc(R.pct(st['hit_pct'], sign=False))})" if st["hit_pct"] is not None else "")
            + (f", medijan {esc(_lead(st['med_lead_min']))} nakon kupnje" if st["med_lead_min"] is not None else "")
            + (f"; grupa je nakon objave prodala u {st['sold_after']}" if st["called"] else "") + ".</p>")
    items = []
    for r in rows:
        if r["called"] == 1:
            what, tone = f"objavio {_lead((r['call_ts'] - r['buy_ts']) / 60)} kasnije", "pos"
        elif r["closed"]:
            what, tone = "nije objavio", "mut"
        else:
            what, tone = "čeka", "mut"
        sub = R.pct(r["r1h"], frac=True) if r.get("r1h") is not None else None
        items.append(R.row(R.raw(f"{esc(r.get('symbol') or r['token'][:6])} · {esc(names.get(r['inf'], r['inf']))}"),
                           f"kupnja {_t(r['buy_ts'])} · {R.ago(r['buy_ts'], now)}", value=what, sub=sub,
                           value_tone=tone, sub_tone=R.tone(r.get("r1h"))))
    return head + str(R.rows(items)) + str(R.hint("Postotak ispod je kretanje cijene u prvom satu nakon njegove objave. "
                                                  "Samo mjerenje: nijedan račun ne kupuje."))


def page(qs=None, user=None, now=None):
    """(title, html) of /kol-insajderi for the owner; anybody else gets one sentence and no data (run_ui.py also
    refuses them with 403 before this is called)."""
    from insajderi import kolwallets as kw
    from trade import settings
    top = R.top("Insajderski novčanici", "Vjerojatno povezani novčanici influencera · vidiš samo ti")
    if not settings.is_owner(user):
        return "Insajderski novčanici", (f'<div class="ms-page ki"><style>{CSS}</style>{R.top("Insajderski novčanici")}'
                                         '<p class=ms-hint>Ovu stranicu vidi samo vlasnik.</p></div>')
    now = int(now or time.time())
    rows, s = kw.view(), kw.summary()
    back = '<p class=ms-hint><a href="/kol">‹ Influenceri</a></p>'
    caveat = f'<div class=ki-note><p>{esc(kw.CAVEAT)}</p></div>'
    if not rows:
        return "Insajderski novčanici", (f'<div class="ms-page ki"><style>{CSS}</style>{back}{top}{caveat}'
                                         '<p class=ms-hint>Prvi prolaz još nije odrađen. Popis se puni desetak minuta '
                                         'nakon objave nove verzije, zatim svaka tri sata i noću.</p></div>')
    state = (f"Zadnji prolaz {esc(R.ago(s.get('ts'), now))}: {s.get('with_calls', 0)} od {s.get('influencers', len(rows))} "
             f"influencera ima pozive u podacima, {s.get('listed', 0)} grupa na popisu, {s.get('confirmed', 0)} "
             f"potvrđenih, {s.get('linked', 0)} s izravnom vezom.") if s else ""
    props = kw.proposals(limit=20)
    prop_html = ""
    if props:
        prop_html = (str(R.section("Prijedlozi koji čekaju tvoju potvrdu", sid="prijedlozi")) + "<ul>" + "".join(
            f"<li>{esc(x['influencer'])}: {('@' + esc(x['handle'])) if x['handle'] else ''} "
            f"{_w(x['address']) if x['address'] else ''}{_src(x['source'])} · {esc(R.ago(x['ts'], now))}</li>"
            for x in props) + "</ul>" + str(R.hint("Prijedlog se ne koristi dok ga ne potvrdiš u popisu influencera.")))
    body = (f'<div class="ms-page ki"><style>{CSS}</style>{back}{top}{caveat}'
            + (f"<p class=ms-hint>{state}</p>" if state else "")
            + str(R.section("Influenceri", sid="influenceri"))
            + "".join(_inf_html(d) for d in rows)
            + str(R.section("Kupnja prije poziva, uživo", sid="predpoziv")) + _pred_html(now)
            + prop_html
            + str(R.section("Kako čitati", sid="kako"))
            + "<ul><li><b>Potvrđen</b>: kupio je prije barem 3 njegova poziva (barem 2 su objave, ne samo kupnje "
              "njegova javnog novčanika), to se ponovilo i na novijim pozivima i događa se bar dvostruko češće nego "
              "slučajno; ili postoji izravna veza s njegovim javnim novčanikom uz barem 2 poziva.</li>"
              "<li><b>Kandidat</b>: 2 poziva ili samo izravna veza.</li>"
              "<li><b>Izravna veza</b>: SOL ili tokeni poslani S javnog novčanika, isti prvi izvor sredstava ili isti "
              "vlasnik po našim podacima. Uplata NA javni novčanik se ne broji (njima se često šalje), kao ni veza "
              "preko burze.</li><li>Botovi, snajperi i novčanici koji kupuju gotovo sve su izbačeni.</li></ul>"
            + str(R.hint("Stranica nije javna i ništa s nje ne ide u objave.")) + "</div>")
    return "Insajderski novčanici", body
