"""/registracija?k=<invite>: a friend with an invite link picks a name and password and gets a competition account.

Also the "Pozovi prijatelja" box on Natjecanje: the link to copy, a new link (old one stops working) and
single-use links. Who may see it: players named in UI_ADMINS, or every player when UI_ADMINS is not set.
"""
import os
import sqlite3
from urllib.parse import quote

from league import members, store
from ui.html import ago, esc, page


def admins():
    return {a.strip().lower() for a in os.environ.get("UI_ADMINS", "").split(",") if a.strip()}


def can_invite(user):
    return bool(user) and (not admins() or user.lower() in admins())


def _base():
    return os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")


def link(tok):
    return f"{_base()}/registracija?k={quote(tok)}"


def page_html(qs, err=""):
    k = qs.get("k", "")
    try:
        con = members.connect()
        try:
            inv = members.valid(con, k)
        finally:
            con.close()
    except sqlite3.OperationalError:
        inv = None
    if not inv:
        body = ("<h1>Registracija</h1><div class=card><b class=neg>Ovaj link za registraciju ne vrijedi.</b> "
                "Možda je zamijenjen novim ili je već iskorišten. Zatraži novi link od onoga tko te pozvao.</div>"
                "<p>Već imaš račun? <a href=/prijava>Prijavi se</a>.</p>")
        return page("Registracija", body, "/registracija")
    body = (f"<h1>Pridruži se natjecanju</h1><p class=lead>Dobivaš svoj demo račun od ${store.START_USD:,.0f} "
            "(bez pravog novca). Biraš tokene iz prijedloga alata, kupuješ i prodaješ po živoj cijeni i natječeš se "
            "s ostalima i s botom.</p>"
            "<form method=post action=/registracija class=card style='max-width:380px'>"
            f"<input type=hidden name=k value=\"{esc(k)}\">"
            "<p><label>Tvoje ime u natjecanju<br><input name=name autocomplete=username required maxlength=20 "
            f"value=\"{esc(qs.get('name', ''))}\" style='width:100%' autocapitalize=none placeholder='npr. Marko'>"
            "</label><br><span class=mut style='font-size:12px'>2 do 20 slova ili brojki, bez razmaka. Ovo ime "
            "upisuješ kod prijave.</span></p>"
            "<p><label>Lozinka<br><input name=pw type=password autocomplete=new-password required minlength=6 "
            "style='width:100%'></label><br><span class=mut style='font-size:12px'>Barem 6 znakova.</span></p>"
            "<p><label>Ponovi lozinku<br><input name=pw2 type=password autocomplete=new-password required "
            "minlength=6 style='width:100%'></label></p>"
            + (f"<p class=neg>{esc(err)}</p>" if err else "")
            + "<p><button type=submit>Napravi račun i uđi</button></p></form>"
            "<p class=mut>Prijava se pamti 60 dana na ovom uređaju. Na drugom uređaju se prijaviš istim imenom i "
            "lozinkom. Već imaš račun? <a href=/prijava>Prijavi se</a>.</p>")
    return page("Registracija", body, "/registracija")




def post(form, taken):
    """(name, None) when the account was made, else (None, plain-Croatian reason)."""
    try:
        con = members.connect()
        try:
            name = members.register(con, form.get("k", ""), form.get("name", ""), form.get("pw", ""),
                                    form.get("pw2", ""), taken)
        finally:
            con.close()
    except ValueError as e:
        msg = str(e)
        return None, msg[:1].upper() + msg[1:]
    except sqlite3.IntegrityError:
        return None, "To ime je već zauzeto, odaberi drugo."
    except sqlite3.OperationalError as e:
        from ui import league
        return None, league.db_error(e)
    print(f"natjecanje: {name} registracija -> novi igrač", flush=True)
    try:
        from ui import league
        league._API["ts"] = 0
    except Exception:
        pass
    return name, None


def invite_box(user):
    """'Pozovi prijatelja' on Natjecanje, for players who may invite."""
    if not can_invite(user):
        return ""
    try:
        con = members.connect()
        try:
            tok = members.standing(con, user)
            singles = members.open_singles(con)
            joined = members.joined(con, 20)
        finally:
            con.close()
    except sqlite3.OperationalError:
        return ""
    js_fill = "" if _base() else (
        "<script>document.querySelectorAll('input[data-inv]').forEach(function(i){"
        "i.value=location.origin+i.dataset.inv})</script>")

    def row(t, extra=""):
        url = link(t)
        return (f"<div style='display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin:6px 0'>"
                f"<input readonly data-inv=\"{esc('/registracija?k=' + quote(t))}\" value=\"{esc(url)}\" "
                "style='flex:1;min-width:220px' onclick='this.select()'>"
                "<button type=button onclick=\"var i=this.previousElementSibling;i.select();"
                "navigator.clipboard&&navigator.clipboard.writeText(i.value);this.textContent='✅ Kopirano'\">"
                f"📋 Kopiraj</button>{extra}</div>")

    sing = "".join(row(s["token"], f"<span class=mut style='font-size:12px'>napravljen {ago(s['created'])[0]}</span>"
                       f"<form method=post action=/natjecanje/pozivnica/ukini style='margin:0'>"
                       f"<input type=hidden name=k value=\"{esc(s['token'])}\"><button>Poništi</button></form>")
                   for s in singles)
    who = ", ".join(f"{esc(j['name'])} ({ago(j['created'])[0]})" for j in joined)
    return ("<details class=card id=pozovi><summary><b>👥 Pozovi prijatelja</b> "
            "<span class=mut>pošalji mu link, sam si napravi račun</span>" + _pending_badge() + "</summary>"
            + _requests_note() +
            "<p>Prijatelj otvori link, upiše ime i lozinku i odmah dobije svoj demo račun od "
            f"${store.START_USD:,.0f} na ljestvici. Ti ne moraš ništa namještati.</p>"
            "<p><b>Stalni link</b> (vrijedi za koliko god ljudi, dok ga ne zamijeniš):</p>" + row(tok)
            + "<div style='display:flex;gap:6px;flex-wrap:wrap'>"
            "<form method=post action=/natjecanje/pozivnica/novi style='margin:0'><button "
            "onclick=\"return confirm('Stari link prestaje vrijediti. Računi koji su već napravljeni ostaju.')\">"
            "🔄 Napravi novi stalni link</button></form>"
            "<form method=post action=/natjecanje/pozivnica/jednokratni style='margin:0'><button>"
            "➕ Napravi jednokratni link</button></form></div>"
            "<p class=mut style='font-size:12px'>Stalni link je zgodan za grupu prijatelja. Ako ga netko proslijedi "
            "dalje, napravi novi i stari prestaje raditi. Jednokratni link radi samo za jednu osobu i nakon toga "
            "nestaje.</p>"
            + (f"<p><b>Jednokratni linkovi koji još nisu iskorišteni:</b></p>{sing}" if sing else "")
            + (f"<p class=mut>Registrirali su se: {who}</p>" if who else "")
            + js_fill + "<script>if(location.hash=='#pozovi')document.getElementById('pozovi').open=true</script>"
            "</details>")


def _pending_badge():
    try:
        from ui import landing
        n = landing.pending_count()
    except Exception:  # noqa: BLE001
        n = 0
    return f" <span class='b warn'>📨 {n} čeka</span>" if n else ""


def _requests_note():
    """Pending 'Zatraži pristup' requests from the public page."""
    try:
        from ui import landing
        n = landing.pending_count()
    except Exception:  # noqa: BLE001
        n = 0
    if not n:
        return ("<p class=mut style='font-size:13px'>Ljudi koje ne poznaješ mogu zatražiti pristup na "
                "<a href=/dobrodosli target=_blank>naslovnoj stranici</a>; zahtjevi stižu na "
                "<a href=/zahtjevi>Zahtjevi za pristup</a>.</p>")
    return (f"<p class=card style='border-color:var(--warn)'>📨 <b>{n} {'novi zahtjev' if n == 1 else 'novih zahtjeva'} "
            "za pristup</b> s naslovne stranice. <a href=/zahtjevi>Pogledaj i pošalji pozivnicu →</a></p>")


def post_invite(path, form, user):
    """Buttons in the box; returns where to go next."""
    if not can_invite(user):
        return f"/natjecanje?err={quote('samo organizator natjecanja može raditi linkove')}#pozovi"
    con = members.connect()
    try:
        if path == "/natjecanje/pozivnica/novi":
            members.renew(con, user)
            msg = "Napravljen je novi stalni link, stari više ne vrijedi."
        elif path == "/natjecanje/pozivnica/jednokratni":
            members.single(con, user)
            msg = "Napravljen je jednokratni link, kopiraj ga ispod."
        elif path == "/natjecanje/pozivnica/ukini":
            members.revoke(con, form.get("k", ""))
            msg = "Link je poništen."
        else:
            return "/natjecanje"
    finally:
        con.close()
    return f"/natjecanje?ok={quote(msg)}#pozovi"
