"""/korisnici (admins only, checked in run_ui before this runs): every user and their role, one tap to change it.

19.11. (owner's order: users without a visit in 5 days are removed, league/izbaceni.py): every row shows the last
recorded visit (league/posjeti.py), the top says when the removal runs (or that it ran) and the collapsed block
"Izbačeni" brings anyone back with one tap ("Vrati", POST /korisnici/vrati)."""
import datetime as _dt
import time
from urllib.parse import quote

from league import izbaceni, members, posjeti, roles
from ui.html import esc, tip

KIND = {"env": "stari igrač (Render)", "member": "registriran pozivnicom", "viewer": "račun samo za gledanje"}
TIP = {
    "admin": "Admin: " + roles.WHAT["admin"],
    "prijatelj": "Prijatelj: " + roles.WHAT["prijatelj"],
    "osnovni": "Osnovni: " + roles.WHAT["osnovni"],
}


def _users(env_names, viewer):
    env_names = [n for n in env_names if not izbaceni.is_out(n)]   # 19.11.: removed ones are listed under Izbačeni
    out = [(n, "env") for n in env_names]
    have = {n.lower() for n in env_names}
    for n in members.names():
        if n.lower() not in have:
            out.append((n, "member"))
            have.add(n.lower())
    if viewer and viewer.lower() not in have:
        out.append((viewer, "viewer"))
    return out


def _date(ts):
    return _dt.datetime.fromtimestamp(ts, posjeti.TZ).strftime("%d.%m.%Y.")


def ago(ts, now=None):
    """Relative time of a visit in plain Croatian; "nema zapisa" when none was recorded."""
    if not ts:
        return "nema zapisa"
    d = max(0, (now or time.time()) - ts)
    if d < 3600:
        return f"prije {max(1, int(d // 60))} min"
    if d < 86400:
        return f"prije {int(d // 3600)} h"
    return f"prije {int(d // 86400)} d"


def _order_line(now=None):
    """The one sentence about the owner's order of 19.11.: when it runs, or what it did."""
    res = izbaceni.done()
    if res:
        return (f"<div class=card><b>Izbačeno {len(res.get('izbaceni') or [])} korisnika {esc(_date(res['ts']))} "
                f"(bez posjeta 5 dana).</b></div>")
    start = posjeti.started_at() or int(now or time.time())
    return (f"<div class=card><b>Posjeti se bilježe od {esc(_date(start))} {esc(_date(start + izbaceni.WINDOW))} alat "
            "sam izbacuje sve koji u tih 5 dana nisu otvorili aplikaciju (tvoj nalog 19.11.).</b></div>")


def _removed_block(rows):
    if not rows:
        return ""
    items = "".join(
        f"<div class=card style='display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap'>"
        f"<div><b translate=no>{esc(r['name'])}</b> <span class=mut style='font-size:12px'>"
        f"{esc(_date(r['ts']) if r.get('ts') else '')}</span><br><span class=mut style='font-size:12px'>"
        f"{esc(r.get('why') or '')}</span></div>"
        f"<form method=post action=/korisnici/vrati style='margin:0'><input type=hidden name=name value=\"{esc(r['name'])}\">"
        f"<button type=submit>Vrati</button></form></div>" for r in rows)
    return (f"<details><summary><b>Izbačeni ({len(rows)})</b></summary><p class=mut>Ne mogu se prijaviti i nisu ni na "
            f"jednom popisu; ništa njihovo nije obrisano (demo račun, tradeovi, profil). Vrati ih vraća kakvi su bili."
            f"</p>{items}</details>")


def page(qs, who, env_names, viewer):
    b = ["<h1>Korisnici i uloge</h1>", _order_line()]
    if qs.get("ok"):
        b.append(f"<div class=card><b class=pos>{esc(qs['ok'])}</b></div>")
    if qs.get("err"):
        b.append(f"<div class=card><b class=neg>{esc(qs['err'])}</b></div>")
    b.append("<div class=card><h3 style='margin-top:0'>Što koja uloga smije</h3><ul style='padding-left:18px;margin:0'>"
             + "".join(f"<li><b>{roles.LABEL[r]}</b> {tip(TIP[r])}: {esc(roles.WHAT[r])}</li>" for r in roles.ROLES)
             + "</ul><p class=mut style='margin-bottom:0'>Novi korisnici iz pozivnice su automatski Osnovni. "
               "Zabrane provjerava server za svaku stranicu i svaki gumb, ne samo izbornik.</p></div>")
    locked = roles.locked_admins()
    seen = posjeti.visits()
    rows = []
    for name, kind in _users(env_names, viewer):
        r = roles.role(name)
        if name.lower() in locked:
            ctl = f"<b>{roles.LABEL[r]}</b> <span class=mut>(stalno, postavljeno na serveru)</span>"
        else:
            opts = "".join(f"<option value={x}{' selected' if x == r else ''}>{roles.LABEL[x]}</option>"
                           for x in roles.ROLES)
            ctl = (f"<form method=post action=/korisnici/uloga style='display:flex;gap:6px;flex-wrap:wrap;margin:0'>"
                   f"<input type=hidden name=name value=\"{esc(name)}\">"
                   f"<select name=role aria-label='Uloga za {esc(name)}'>{opts}</select>"
                   f"<button type=submit>Spremi ulogu</button></form>")
        rows.append(f"<div class=card style='display:flex;justify-content:space-between;align-items:center;gap:10px;"
                    f"flex-wrap:wrap'><div><b translate=no>{esc(name)}</b>{' <span class=mut>(ti)</span>' if who and name.lower() == who.lower() else ''}"
                    f"<br><span class=mut style='font-size:12px'>{esc(KIND[kind])}</span>"
                    f"<br><span class=mut style='font-size:12px'>Zadnji posjet: "
                    f"<b>{esc(ago((seen.get(name.lower()) or {}).get('last_ts')))}</b></span></div>{ctl}</div>")
    b.append(f"<h2>Svi korisnici ({len(rows)})</h2>" + "".join(rows))
    b.append(_removed_block(izbaceni.rows()))
    return "Korisnici i uloge", "".join(b)


def post(path, form, who):
    if path == "/korisnici/vrati":   # 19.11.: brings a removed user back (admins only: roles.POSTS "/korisnici/")
        name = (form.get("name") or "").strip()
        con = izbaceni.connect()
        try:
            name = izbaceni.restore(con, name, who or "")
        except ValueError as e:
            return f"/korisnici?err={quote(str(e))}"
        finally:
            con.close()
        return f"/korisnici?ok={quote(f'{name} je vraćen i može se opet prijaviti.')}"
    if path != "/korisnici/uloga":
        return "/korisnici"
    name, new = (form.get("name") or "").strip(), form.get("role", "")
    try:
        roles.set_role(name, new, who or "")
    except ValueError as e:
        return f"/korisnici?err={quote(str(e))}"
    return f"/korisnici?ok={quote(f'{name} je sada {roles.LABEL[new]}.')}"
