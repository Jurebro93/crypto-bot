"""Pages of the public API (27.11., ui/javniapi.py):

  /api              short docs for every logged-in user (noindex like every app page): endpoints and fields, results only
  /api-kljucevi     OWNER only (run_ui.py checks before anything is read): make a key for a user (shown ONCE), change its
                    plan / cap, revoke it, usage per key today / 7 days / total, and "Provjeri procurjeli uzorak" (trace
                    a leaked sample to the key through the canaries). Never cached.
"""
import time
from urllib.parse import quote

from ui import javniapi as A
from ui.html import esc

PATH = "/api-kljucevi"
CSS = (".ja table{border-collapse:collapse;width:100%;font-size:13px}.ja td,.ja th{padding:5px 6px;border-bottom:1px "
       "solid var(--line,#333);text-align:left;vertical-align:top}.ja code{word-break:break-all}.ja .key{font-size:15px;"
       "padding:10px;border:2px solid #c90;border-radius:8px;margin:10px 0}.ja form.inl{display:inline}.ja input,"
       ".ja select,.ja textarea{max-width:100%}.ja .mut{opacity:.7}")


def _users():
    names = []
    try:
        from league import members, store
        names += store.env_users()
        names += members.names()
    except Exception:  # noqa: BLE001
        pass
    return list(dict.fromkeys(names))


def _when(ts):
    return time.strftime("%d.%m.%Y. %H:%M", time.gmtime(ts)) + " UTC" if ts else "–"


def owner_page(qs=None, new_key=None, trace_rows=None, trace_text=""):
    qs = qs or {}
    con = A.connect()
    try:
        rows = A.keys(con)
    finally:
        con.close()
    pl = A.plans()
    plan_opts = "".join(f"<option value='{esc(p)}'>{esc(p)} ({v['daily']}/dan{', svježe' if v['fresh'] else ', 24 h kasni'})"
                        "</option>" for p, v in pl.items())
    msg = ""
    if qs.get("ok"):
        msg = f"<p class=card>✅ {esc(qs['ok'])}</p>"
    if qs.get("err"):
        msg = f"<p class=card>⚠️ {esc(qs['err'])}</p>"
    if new_key:
        kid, key = new_key
        msg += (f"<div class='card key'><b>Novi ključ #{kid}</b> (vidi se samo sada, spremljen je samo njegov otisak):<br>"
                f"<code>{esc(key)}</code><br><span class=mut>Pošalji ga korisniku sigurnim kanalom. Izgubljen ključ se "
                "ne može vratiti: opozovi ga i napravi novi.</span></div>")
    users = "".join(f"<option value='{esc(u)}'>" for u in _users())
    body = [f"<div class='ms-page ja'><style>{CSS}</style><h1>API ključevi</h1>"
            "<p class=mut>Javni API (/api/v1/) vraća samo rezultate. Vidiš samo ti. Opis za korisnike: <a href=/api>/api</a>."
            f" Burst: {A.BURST_N} zahtjeva u {A.BURST_S} s po ključu.</p>{msg}",
            f"<h2>Novi ključ</h2><form method=post action={PATH}/novi><input name=owner list=ja-users placeholder='korisnik' "
            f"required><datalist id=ja-users>{users}</datalist> <select name=plan>{plan_opts}</select> "
            "<input name=label placeholder='oznaka (npr. bot korisnika)' maxlength=60> "
            "<input name=cap placeholder='vlastiti dnevni strop' inputmode=numeric size=10> <button>Napravi</button></form>"]
    tr = []
    for k in rows:
        state = f"opozvan {_when(k['revoked_ts'])}" if k["revoked"] else "aktivan"
        act = "" if k["revoked"] else (
            f"<form class=inl method=post action={PATH}/plan><input type=hidden name=id value={k['id']}>"
            f"<select name=plan>{plan_opts.replace(chr(39) + esc(k['plan']) + chr(39), chr(39) + esc(k['plan']) + chr(39) + ' selected')}"
            f"</select><input name=cap size=7 value='{k['daily_cap'] or ''}' placeholder='plan'><button>Spremi</button></form> "
            f"<form class=inl method=post action={PATH}/opozovi onsubmit=\"return confirm('Opozvati ključ #{k['id']}?')\">"
            f"<input type=hidden name=id value={k['id']}><button>Opozovi</button></form>")
        tr.append(f"<tr><td>#{k['id']}<br><code>{esc(k['prefix'] or '')}…</code></td><td>{esc(k['owner'])}<br>"
                  f"<span class=mut>{esc(k['label'] or '')}</span></td><td>{esc(k['plan'])}<br>{k['cap']}/dan</td>"
                  f"<td>{k['today']} danas<br><span class=mut>{k['refused_today']} odbijeno · {k['week']} u 7 dana · "
                  f"{k['total']} ukupno</span></td><td>{state}<br><span class=mut>zadnje {_when(k['last_used'])}</span></td>"
                  f"<td>{act}</td></tr>")
    body.append("<h2>Ključevi i potrošnja</h2>" + (
        "<div style='overflow-x:auto'><table><tr><th>Ključ</th><th>Korisnik</th><th>Plan</th><th>Zahtjevi</th>"
        "<th>Stanje</th><th></th></tr>" + "".join(tr) + "</table></div>" if tr else "<p class=mut>Još nema ključeva.</p>"))
    res = ""
    if trace_rows is not None:
        if not trace_rows:
            res = "<p class=card>Uzorak ne pokazuje ni na jedan ključ (nema kontrolnih redaka ni vodenog žiga).</p>"
        else:
            res = "<table><tr><th>Ključ</th><th>Korisnik</th><th>Kontrolni redci</th><th>Vodeni žig</th></tr>" + "".join(
                f"<tr><td>#{r['key_id']}</td><td>{esc(r['owner'])} <span class=mut>{esc(r['label'] or '')}</span></td>"
                f"<td>{len(r['canaries'])}" + (" (" + ", ".join(esc(d) for d, _m in r["canaries"][:5]) + ")" if r["canaries"] else "")
                + f"</td><td>{r['wm_match']} od {r['wm_rows']} redaka</td></tr>" for r in trace_rows) + "</table>"
    body.append(
        "<h2>Provjeri procurjeli uzorak</h2><p class=mut>Zalijepi procurjeli JSON ili tekst s adresama. Svaki ključ u "
        "svakom odgovoru na /signals dobije jedan izmišljeni token tog dana (adresa postoji samo u odgovorima tom "
        "ključu) i vodeni žig u sekundama polja first_seen_ts. Pronađena izmišljena adresa imenuje ključ; žig koji se "
        "poklapa na većini redaka (slučajno 1 od 60 po retku) upućuje na ključ i kad su izmišljeni redci izbrisani.</p>"
        f"<form method=post action={PATH}/trag><textarea name=uzorak rows=6 style='width:100%'>{esc(trace_text[:20000])}"
        "</textarea><br><button>Provjeri</button></form>" + res + "</div>")
    return "API ključevi", "".join(body)


def post(path, form, user):
    """(redirect location or None, (title, html) to render directly or None). The new key is rendered, never put in
    an address (it would stay in the browser's history and the logs)."""
    from trade import settings
    if not settings.is_owner(user):
        return PATH + "?err=" + quote("samo vlasnik"), None
    act = path[len(PATH) + 1:]
    con = A.connect()
    try:
        if act == "novi":
            kid, key = A.create(con, form.get("owner"), form.get("plan") or "free", form.get("label"),
                                form.get("cap") or None, by=user)
            return None, owner_page(new_key=(kid, key))
        if act == "opozovi":
            ok = A.revoke(con, int(form.get("id") or 0))
            return PATH + "?" + ("ok=" + quote("ključ opozvan") if ok else "err=" + quote("nema tog aktivnog ključa")), None
        if act == "plan":
            A.set_plan(con, int(form.get("id") or 0), form.get("plan"), form.get("cap") or None)
            return PATH + "?ok=" + quote("plan spremljen"), None
        if act == "trag":
            text = form.get("uzorak") or ""
            return None, owner_page(trace_rows=A.trace(con, text), trace_text=text)
        return PATH + "?err=" + quote("nepoznata radnja"), None
    except (ValueError, TypeError) as e:
        return PATH + "?err=" + quote(str(e) or "neispravan unos"), None
    finally:
        con.close()


DOCS = """
<h1>MemeSonar API</h1>
<p>Rezultati MemeSonara za tvoje programe: presude i kratki razlozi, bez internih pravila. Ključ ti daje vlasnik
aplikacije; čuvaj ga kao lozinku. Svaki odgovor je JSON.</p>
<h2>Prijava</h2>
<p><code>Authorization: Bearer &lt;ključ&gt;</code> ili <code>X-API-Key: &lt;ključ&gt;</code>. Bez ključa ili s opozvanim: 401.</p>
<h2>Ograničenja</h2>
<p>Dnevni broj zahtjeva ovisi o planu (dan po UTC-u) i kratki burst limit. Preko granice: <b>429</b> s
<code>Retry-After</code> (sekunde) i <code>retry_after_s</code>. Odgovori nose <code>X-RateLimit-Limit</code> i
<code>X-RateLimit-Remaining</code>. Plan bez svježih podataka vidi signale s 24 h zakašnjenja.</p>
<h2>Krajnje točke (GET)</h2>
<table>
<tr><td><code>/api/v1/token/&lt;adresa&gt;</code></td><td><b>risk</b>: low_risk · caution · high_risk · avoid · unknown;
<b>late</b>: cijena je već daleko iznad prvog signala; <b>reasons</b>: do 3 kratka razloga; market_cap_usd,
liquidity_usd; uz svježi plan i <b>calls_last_hour</b> (broj poziva praćenih računa u zadnjem satu).</td></tr>
<tr><td><code>/api/v1/wallet/&lt;adresa&gt;</code></td><td><b>verdict</b>: worth_copying · do_not_copy_with_real_money ·
do_not_copy · not_proven_yet · not_proven · not_rated; <b>copyable</b> (da/ne/nepoznato), <b>proven_twice</b>,
<b>grade</b> (S–D), <b>labels</b> (npr. bot, sniper, insider), <b>reasons</b>. 404 kad novčanik ne poznajemo.</td></tr>
<tr><td><code>/api/v1/influencer/&lt;handle&gt;</code></td><td>X handle ili <code>tg:&lt;kanal&gt;</code>. Na čistim
izmjerenim pozivima starijim od 24 h: measured_calls, enough_data, price_up_after_1h_share,
reached_plus_15pct_in_24h_share, median_24h_return, fell_90pct_share (udjeli 0–1), vs_median_account (better · same ·
worse), measured_since.</td></tr>
<tr><td><code>/api/v1/signals?limit=50</code></td><td>Do 50 nedavnih signala: token, symbol, kind (social_call ·
wallet_buy · market_scan), callers, first_seen_ts (unix, na minutu), market_cap_usd, risk; uz zakašnjeli plan i
change_24h_after_first_call. Tokeni s premalim market capom se ne navode.</td></tr>
<tr><td><code>/api/v1/usage</code></td><td>Tvoj plan, dnevni strop, potrošeno danas (ne broji se).</td></tr>
</table>
<p class=mut>Prošli rezultati nisu predviđanje ni financijski savjet. Podaci su za tvoju upotrebu; ne dijeli ih dalje.</p>
"""


def docs_page():
    return "API", f"<div class='ms-page ja'><style>{CSS}</style>{DOCS}</div>"
