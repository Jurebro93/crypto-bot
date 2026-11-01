"""⚙️ Postavke (/postavke): everything a user changes about himself, on one page.

Sections: profile picture, language, password, e-mail + social networks + short bio, morning report by e-mail,
log out everywhere, delete account (invite-link players only; UI_USERS players are managed on the server).
A view-only login (no player) only gets the language.
"""
from urllib.parse import quote

from league import profiles
from ui.html import esc

CSS = """<style>
.set{max-width:760px}.set .card{margin:0 0 16px}.set h2{margin:6px 0 10px;font-size:17px}
.set label{display:block;margin:10px 0 4px;font-weight:600;font-size:13.5px}.set .hint{color:var(--mut);font-size:12.5px;margin:2px 0 0}
.set input[type=text],.set input[type=email],.set input[type=password],.set textarea{width:100%;max-width:420px;padding:8px 10px;font-size:15px}
.set textarea{min-height:64px;font:inherit}
.set label>input,.set label>textarea{display:block;margin-top:5px;font-weight:400}
.set .row{display:flex;gap:14px;flex-wrap:wrap;align-items:center}
.set button{padding:8px 16px;border-radius:999px;border:0;background:var(--fg);color:#fff;font-weight:600;cursor:pointer;font:inherit}
.set button.sec{background:var(--card);color:var(--fg);border:1px solid var(--line)}.set button.bad{background:var(--bad)}
.set .soc{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:4px 16px}
.bigav{width:96px;height:96px;border-radius:50%;background:var(--c,#7a92ff) center/cover no-repeat;display:flex;align-items:center;
 justify-content:center;color:#fff;font-size:40px;font-weight:700;flex:none}
.langs{display:flex;gap:8px}.langs a{border:1px solid var(--line);border-radius:999px;padding:6px 14px;text-decoration:none;color:var(--fg)}
.langs a.on{border-color:var(--acc);background:color-mix(in srgb,var(--acc) 12%,transparent);color:var(--acc);font-weight:650}
.set .chk{display:flex;gap:8px;align-items:flex-start;font-weight:400}.set .chk>input{display:inline;margin-top:4px}
</style>"""

AV_JS = """<script>
(()=>{const f=document.getElementById('avf'),inp=document.getElementById('avi'),out=document.getElementById('avd'),
 prev=document.getElementById('avp'),btn=document.getElementById('avb'),msg=document.getElementById('avm');if(!inp)return;
 inp.onchange=()=>{const file=inp.files&&inp.files[0];if(!file)return;
  if(file.size>15e6){msg.textContent=msg.dataset.big;return}
  const img=new Image(),url=URL.createObjectURL(file);img.onload=()=>{const s=Math.min(img.width,img.height),c=document.createElement('canvas');
   c.width=c.height=256;c.getContext('2d').drawImage(img,(img.width-s)/2,(img.height-s)/2,s,s,0,0,256,256);
   out.value=c.toDataURL('image/jpeg',0.85);prev.style.backgroundImage='url('+out.value+')';prev.textContent='';btn.disabled=false;
   msg.textContent=msg.dataset.ready;URL.revokeObjectURL(url)};img.onerror=()=>{msg.textContent=msg.dataset.bad};img.src=url}})();
</script>"""


def _msg(qs):
    if qs.get("err"):
        return (f'<div class=card style="border:2px solid var(--bad);background:var(--badbg)"><b class=neg>❌ Nije '
                f'spremljeno:</b> {esc(qs["err"])}</div>')
    if qs.get("ok"):
        return f'<div class=card style="border:2px solid var(--good);background:var(--goodbg)">✅ {esc(qs["ok"])}</div>'
    return ""


def avatar_html(user, color="#7a92ff", cls="bigav", extra=""):
    url = profiles.avatar_url(user) if user else None
    if url:
        return f'<span class={cls} style="--c:{color};background-image:url({url})"{extra}></span>'
    return f'<span class={cls} style="--c:{color}"{extra}>{esc((user or "?")[:1].upper())}</span>'


def page(qs, user, kind, lang):
    """(title, body). kind: 'env' (UI_USERS player), 'member' (invite link), 'viewer' (look only)."""
    b = [CSS, "<div class=set><h1>⚙️ Postavke</h1>",
         f"<p class=lead>{'Prijavljen si kao <b translate=no>' + esc(user) + '</b>. ' if user else ''}Ovdje mijenjaš lozinku, "
         "profilnu sliku, jezik i podatke koje vide ostali igrači.</p>", _msg(qs)]

    # language: for everybody
    b.append("<div class=card id=jezik><h2>🌐 Jezik</h2><div class=langs>"
             f"<a href='/jezik?l=hr&next=/postavke' class='{'on' if lang == 'hr' else ''}' translate=no>🇭🇷 Hrvatski</a>"
             f"<a href='/jezik?l=en&next=/postavke' class='{'on' if lang == 'en' else ''}' translate=no>🇬🇧 English</a></div>"
             "<p class=hint>Isti prekidač je u izborniku pored Odjave. Jezik se pamti na ovom uređaju"
             + (" i u tvom računu, pa vrijedi i na drugim uređajima." if user else ".") + "</p></div>")
    if not user:
        b.append("<div class=card><b>Ovo je račun samo za gledanje.</b> Lozinka, slika i profil postoje samo za "
                 "igrače. Igrači se prijavljuju svojim imenom; novi igrač dobiva link za registraciju u "
                 "<a href=/natjecanje#pozovi>Natjecanju</a>.</div></div>")
        return "Postavke", "".join(b)

    p = profiles.get(user)
    soc = profiles.social(user)

    # profile picture
    b.append("<div class=card id=slika><h2>🖼 Profilna slika</h2><div class=row>"
             + avatar_html(user, extra=" id=avp") +
             "<div><form id=avf method=post action=/postavke/slika><input type=hidden name=data id=avd>"
             "<input type=file id=avi accept='image/*' style='max-width:260px'><p class=hint id=avm "
             "data-ready='Slika je spremna, klikni Spremi sliku.' data-bad='Ovu sliku ne mogu otvoriti, probaj JPG ili PNG.' "
             "data-big='Slika je veća od 15 MB, odaberi manju.'>Slika se prikazuje na ljestvici i na podiju u "
             "Natjecanju. Izreže se na kvadrat i smanji na 256×256 prije slanja.</p>"
             "<p><button id=avb disabled>Spremi sliku</button></p></form>"
             + ("<form method=post action=/postavke/slika-makni><button class=sec>Makni sliku</button></form>"
                if p.get("avatar") else "") + "</div></div></div>" + AV_JS)

    # password
    if kind in ("env", "member"):
        b.append("<div class=card id=lozinka><h2>🔑 Lozinka</h2><form method=post action=/postavke/lozinka>"
                 "<input type=text name=name value=\"" + esc(user) + "\" autocomplete=username hidden>"
                 "<label>Trenutna lozinka<input type=password name=old autocomplete=current-password required></label>"
                 "<label>Nova lozinka<input type=password name=new autocomplete=new-password minlength=6 required></label>"
                 "<label>Ponovi novu lozinku<input type=password name=new2 autocomplete=new-password minlength=6 "
                 "required></label><p class=hint>Barem 6 znakova. Nakon promjene ostaješ prijavljen ovdje, a na "
                 "svim ostalim uređajima trebaš se ponovo prijaviti.</p><p><button>Promijeni lozinku</button></p>"
                 "</form></div>")

    # profile + social
    rows = []
    for k, label, icon, _ in profiles.SOCIAL:
        ph = "https://…" if k == "web" else "@ime"
        rows.append(f"<div><label>{icon} {esc(label)}<input type=text name=s_{k} value=\"{esc(soc.get(k, ''))}\" "
                    f"placeholder=\"{ph}\" autocapitalize=none></label></div>")
    b.append("<div class=card id=profil><h2>👤 Profil i društvene mreže</h2><form method=post action=/postavke/profil>"
             "<label>O meni <span class=mut>(do 160 znakova, vide ga ostali igrači)</span>"
             f"<textarea name=bio maxlength=160>{esc(p.get('bio') or '')}</textarea></label>"
             "<p class=hint>Društvene mreže se prikazuju na tvojoj kartici u Natjecanju, da te prijatelji mogu "
             "pratiti. Upiši samo ime računa ili zalijepi link profila.</p>"
             f"<div class=soc>{''.join(rows)}</div>"
             "<label>E-mail <span class=mut>(ne prikazuje se drugima)</span><input type=email name=email "
             f"value=\"{esc(p.get('email') or '')}\" autocomplete=email placeholder='ime@primjer.com'></label>"
             "<label class=chk><input type=checkbox name=email_report value=1"
             f"{' checked' if p.get('email_report') else ''}> Šalji mi jutarnji izvještaj na ovaj e-mail (svaki dan "
             "prije 8 h). Kreće čim se na serveru uključi slanje e-maila.</label>"
             "<p><button>Spremi profil</button></p></form></div>")

    # sessions
    b.append("<div class=card id=sesije><h2>📱 Prijave na uređajima</h2><p>Prijava se pamti 60 dana na svakom "
             "uređaju. Ako si se prijavio na tuđem mobitelu ili računalu, odjavi se svugdje odjednom.</p>"
             "<form method=post action=/postavke/odjava-svugdje><button class=sec>Odjavi me sa svih ostalih uređaja"
             "</button></form></div>")

    # delete account
    if kind == "member":
        b.append("<div class=card id=brisanje style='border-color:var(--bad)'><h2>🗑 Obriši račun</h2>"
                 "<p>Tvoj račun nestaje s ljestvice i više se ne možeš prijaviti. Copy trading i automatski DCA se "
                 "zaustave. Ime ostaje zauzeto. Ovo se ne može poništiti.</p>"
                 "<form method=post action=/postavke/obrisi><label>Za potvrdu upiši svoje ime "
                 f"(<b translate=no>{esc(user)}</b>)<input type=text name=confirm autocomplete=off required></label>"
                 "<p><button class=bad>Obriši moj račun zauvijek</button></p></form></div>")
    else:
        b.append("<div class=card><h2>🗑 Brisanje računa</h2><p class=mut>Tvoj račun je postavljen na serveru. "
                 "Za brisanje javi se organizatoru natjecanja.</p></div>")
    b.append("</div>")
    return "Postavke", "".join(b)


def post(path, form, user, kind, check_pw):
    """(location, extra) after a settings form. extra: 'relogin' when this device needs a fresh cookie,
    'logout' after deleting the account."""
    action = path[len("/postavke/"):]
    back = "/postavke"
    if not user:
        return f"{back}?err={quote('samo igrači imaju ove postavke.')}", None
    try:
        if action == "slika":
            profiles.save_avatar(user, form.get("data"))
            return f"{back}?ok={quote('Profilna slika je spremljena.')}#slika", None
        if action == "slika-makni":
            profiles.remove_avatar(user)
            return f"{back}?ok={quote('Profilna slika je maknuta.')}#slika", None
        if action == "lozinka":
            if kind not in ("env", "member"):
                raise ValueError("ovaj račun nema lozinku koju možeš mijenjati.")
            if not check_pw(user, form.get("old", "")):
                raise ValueError("trenutna lozinka nije točna.")
            profiles.validate_new(form.get("new"), form.get("new2"))
            if kind == "member":
                profiles.set_member_password(user, form["new"])
            else:
                profiles.set_password(user, form["new"])
            return f"{back}?ok={quote('Lozinka je promijenjena. Na ostalim uređajima prijavi se novom lozinkom.')}", \
                "relogin"
        if action == "profil":
            profiles.save_profile(user, form)
            return f"{back}?ok={quote('Profil je spremljen.')}#profil", None
        if action == "odjava-svugdje":
            profiles.logout_everywhere(user)
            return f"{back}?ok={quote('Odjavljen si sa svih ostalih uređaja.')}#sesije", "relogin"
        if action == "obrisi":
            if kind != "member":
                raise ValueError("ovaj račun briše organizator na serveru.")
            if (form.get("confirm") or "").strip().lower() != user.lower():
                raise ValueError("za potvrdu upiši točno svoje ime.")
            profiles.delete_member(user)
            return "/prijava", "logout"
    except ValueError as e:
        return f"{back}?err={quote(str(e))}", None
    except OSError as e:
        return f"{back}?err={quote('spremanje nije uspjelo (' + str(e)[:80] + '). Pokušaj ponovo za minutu.')}", None
    return back, None
