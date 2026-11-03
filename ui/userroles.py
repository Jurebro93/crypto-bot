"""/korisnici (admins only, checked in run_ui before this runs): every user and their role, one tap to change it."""
from urllib.parse import quote

from league import members, roles
from ui.html import esc, tip

KIND = {"env": "stari igrač (Render)", "member": "registriran pozivnicom", "viewer": "račun samo za gledanje"}
TIP = {
    "admin": "Admin: " + roles.WHAT["admin"],
    "prijatelj": "Prijatelj: " + roles.WHAT["prijatelj"],
    "osnovni": "Osnovni: " + roles.WHAT["osnovni"],
}


def _users(env_names, viewer):
    out = [(n, "env") for n in env_names]
    have = {n.lower() for n in env_names}
    for n in members.names():
        if n.lower() not in have:
            out.append((n, "member"))
            have.add(n.lower())
    if viewer and viewer.lower() not in have:
        out.append((viewer, "viewer"))
    return out


def page(qs, who, env_names, viewer):
    b = ["<h1>Korisnici i uloge</h1>"]
    if qs.get("ok"):
        b.append(f"<div class=card><b class=pos>{esc(qs['ok'])}</b></div>")
    if qs.get("err"):
        b.append(f"<div class=card><b class=neg>{esc(qs['err'])}</b></div>")
    b.append("<div class=card><h3 style='margin-top:0'>Što koja uloga smije</h3><ul style='padding-left:18px;margin:0'>"
             + "".join(f"<li><b>{roles.LABEL[r]}</b> {tip(TIP[r])}: {esc(roles.WHAT[r])}</li>" for r in roles.ROLES)
             + "</ul><p class=mut style='margin-bottom:0'>Novi korisnici iz pozivnice su automatski Osnovni. "
               "Zabrane provjerava server za svaku stranicu i svaki gumb, ne samo izbornik.</p></div>")
    locked = roles.locked_admins()
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
                    f"<br><span class=mut style='font-size:12px'>{esc(KIND[kind])}</span></div>{ctl}</div>")
    b.append(f"<h2>Svi korisnici ({len(rows)})</h2>" + "".join(rows))
    return "Korisnici i uloge", "".join(b)


def post(path, form, who):
    if path != "/korisnici/uloga":
        return "/korisnici"
    name, new = (form.get("name") or "").strip(), form.get("role", "")
    try:
        roles.set_role(name, new, who or "")
    except ValueError as e:
        return f"/korisnici?err={quote(str(e))}"
    return f"/korisnici?ok={quote(f'{name} je sada {roles.LABEL[new]}.')}"
