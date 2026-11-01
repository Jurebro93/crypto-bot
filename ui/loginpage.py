"""/prijava: the login page. A page of its own (no app menu, which needs a login anyway): a centred card in the
MemeSonar colours (dark like the app, orange like the Natjecanje button), big inputs and one orange button, built
mobile first. Written in both languages here (the cb_lang cookie picks one) and marked translate=no, so the
background translator never touches it."""
from urllib.parse import quote

from ui import i18n
from ui.html import esc as e, logo

T = {
    "hr": dict(title="Prijava", hello="Dobro došao natrag", sub="Prijavi se u MemeSonar", name="Ime",
               name_ph="npr. Ivan", pw="Lozinka", show="Prikaži lozinku", hide="Sakrij lozinku", go="Prijavi se",
               remember="Ostaješ prijavljen 60 dana na ovom uređaju.",
               how="Igrači: svoje ime i svoja lozinka. Samo za gledanje: bilo koje ime i zajednička lozinka.",
               new="Nemaš račun? MemeSonar je samo na pozivnicu.", req="Zatraži pristup", back="Natrag na naslovnu",
               miss="Lozinke još nisu postavljene za: {}. Postavljaju se u postavkama servera na Renderu.",
               err="Pogrešno ime ili lozinka."),
    "en": dict(title="Log in", hello="Welcome back", sub="Log in to MemeSonar", name="Name",
               name_ph="e.g. Ivan", pw="Password", show="Show password", hide="Hide password", go="Log in",
               remember="You stay logged in for 60 days on this device.",
               how="Players: your own name and password. View only: any name and the shared password.",
               new="No account? MemeSonar is invite only.", req="Request access", back="Back to the home page",
               miss="Passwords are not set yet for: {}. They are set in the server settings on Render.",
               err="Wrong name or password."),
}

CSS = """
:root{--bg:#0d1016;--card:#161a22;--fg:#eef1f5;--mut:#8b96a5;--line:#283040;--in:#0f131a;--acc:#f59f00;--acc2:#f76707;
--bad:#ff6b6b;--badbg:#2c1517;--glow1:rgba(247,103,7,.16);--glow2:rgba(80,120,255,.14);color-scheme:dark}
@media (prefers-color-scheme:light){:root{--bg:#f4f5f8;--card:#fff;--fg:#1b1f24;--mut:#5f6b7a;--line:#e1e5eb;--in:#f8f9fb;
--bad:#c92a2a;--badbg:#fff0f0;--glow1:rgba(247,103,7,.12);--glow2:rgba(80,120,255,.10);color-scheme:light}}
*{box-sizing:border-box}html,body{margin:0;min-height:100%}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
 background-image:radial-gradient(600px 380px at 85% -5%,var(--glow1),transparent 70%),
 radial-gradient(560px 400px at 0% 105%,var(--glow2),transparent 70%);background-attachment:fixed;
 display:flex;flex-direction:column;min-height:100vh;min-height:100dvh;padding:16px}
a{color:var(--acc)}
.top{display:flex;align-items:center;justify-content:space-between;gap:12px;width:100%;max-width:440px;margin:0 auto}
.brand{display:flex;align-items:center;gap:10px;color:var(--fg);text-decoration:none;font-weight:750;font-size:19px;letter-spacing:-.01em}
.lang{display:flex;border:1px solid var(--line);border-radius:999px;overflow:hidden;font-size:13px;font-weight:600}
.lang a{padding:5px 11px;color:var(--mut);text-decoration:none}.lang a.on{background:var(--card);color:var(--fg)}
main{flex:1;display:flex;align-items:center;justify-content:center;padding:28px 0}
.card{width:100%;max-width:440px;background:var(--card);border:1px solid var(--line);border-radius:20px;padding:30px 26px 24px;
 box-shadow:0 20px 50px rgba(0,0,0,.28),0 0 0 1px rgba(255,255,255,.02) inset;position:relative;overflow:hidden}
.card::before{content:"";position:absolute;left:0;right:0;top:0;height:3px;background:linear-gradient(90deg,var(--acc),var(--acc2))}
h1{margin:0;font-size:25px;line-height:1.2;letter-spacing:-.02em}.sub{margin:6px 0 22px;color:var(--mut)}
label{display:block;font-size:13px;font-weight:600;color:var(--mut);margin:0 0 6px}
.f{margin:0 0 16px}.pw{position:relative}
input{width:100%;height:48px;padding:0 14px;font:inherit;font-size:16px;color:var(--fg);background:var(--in);
 border:1px solid var(--line);border-radius:12px;outline:none;transition:border-color .15s,box-shadow .15s}
.pw input{padding-right:50px}
input:focus{border-color:var(--acc);box-shadow:0 0 0 4px color-mix(in srgb,var(--acc) 20%,transparent)}
input::placeholder{color:var(--mut);opacity:.7}
.eye{position:absolute;right:6px;top:6px;width:38px;height:36px;border:0;border-radius:9px;background:transparent;
 color:var(--mut);cursor:pointer;display:grid;place-items:center}.eye:hover{color:var(--fg);background:var(--line)}
.err{display:flex;gap:8px;align-items:flex-start;background:var(--badbg);color:var(--bad);border:1px solid color-mix(in srgb,var(--bad) 35%,transparent);
 border-radius:12px;padding:10px 12px;margin:0 0 16px;font-size:14px}
.go{width:100%;height:50px;margin-top:4px;border:0;border-radius:12px;cursor:pointer;font:inherit;font-size:16px;font-weight:700;
 color:#fff;background:linear-gradient(135deg,var(--acc),var(--acc2));box-shadow:0 6px 18px rgba(247,103,7,.32);
 display:flex;align-items:center;justify-content:center;gap:8px;transition:filter .15s,transform .05s}
.go:hover{filter:brightness(1.07)}.go:active{transform:translateY(1px)}
.go:focus-visible{outline:3px solid color-mix(in srgb,var(--acc) 45%,transparent);outline-offset:2px}
.rem{display:flex;gap:8px;align-items:center;justify-content:center;margin:14px 0 0;color:var(--mut);font-size:13px}
.how{margin:16px 0 0;padding:10px 12px;border-radius:12px;background:var(--in);border:1px dashed var(--line);color:var(--mut);font-size:13px}
.how b{color:var(--fg);font-weight:600}
.new{margin:22px 0 0;padding-top:18px;border-top:1px solid var(--line);text-align:center;color:var(--mut);font-size:14px}
.req{display:inline-flex;align-items:center;gap:6px;margin-top:10px;padding:9px 18px;border-radius:999px;border:1px solid var(--acc);
 color:var(--acc);font-weight:650;text-decoration:none}.req:hover{background:color-mix(in srgb,var(--acc) 12%,transparent)}
.warn{margin:14px 0 0;color:var(--bad);font-size:13px}
footer{text-align:center;font-size:13px;padding:4px 0 6px}footer a{color:var(--mut);text-decoration:none}footer a:hover{color:var(--fg)}
@media (max-width:480px){body{padding:14px 16px}main{align-items:flex-start;padding:22px 0}.card{padding:24px 18px 20px;border-radius:18px}h1{font-size:23px}}
"""

EYE = ('<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
       'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/>'
       '<circle cx="12" cy="12" r="3"/></svg>')

JS = """
(()=>{const b=document.querySelector('.eye'),p=document.getElementById('pw');if(!b||!p)return;
b.onclick=()=>{const s=p.type==='password';p.type=s?'text':'password';b.setAttribute('aria-label',s?b.dataset.hide:b.dataset.show);
b.setAttribute('aria-pressed',s?'true':'false');p.focus()}})();
"""


def html(nxt="/", who="", err="", missing=(), site_url="", lang=None):
    """The whole login page. nxt = where to go after logging in (already checked), who = name to prefill,
    err = an error from the last try (Croatian text from run_ui, shown in the page's language)."""
    lang = lang or i18n.lang()
    t = T["en" if lang == "en" else "hr"]
    if err == T["hr"]["err"]:
        err = t["err"]
    svg, name = logo(34)
    here = "/prijava" + (f"?next={quote(nxt)}" if nxt and nxt != "/" else "")
    switch = "".join(f'<a href="/jezik?l={c}&amp;next={quote(here)}" class="{"on" if c == lang else ""}" '
                     f'hreflang={c} lang={c}>{c.upper()}</a>' for c in ("hr", "en"))
    home = (site_url or "") + ("/" if lang == "en" else "/hr")
    focus_pw = " autofocus" if who else ""
    body = (
        f'<div class=top><a class=brand href="{e(home)}">{svg}<span>{e(name)}</span></a>'
        f'<nav class=lang aria-label="Jezik / Language">{switch}</nav></div>'
        f'<main><section class=card aria-labelledby=h>'
        f'<h1 id=h>{t["hello"]}</h1><p class=sub>{t["sub"]}</p>'
        + (f'<div class=err role=alert><span aria-hidden=true>⚠️</span><span>{e(err)}</span></div>' if err else "")
        + f'<form method=post action=/prijava>'
        f'<input type=hidden name=next value="{e(nxt)}">'
        f'<div class=f><label for=name>{t["name"]}</label><input id=name name=name autocomplete=username '
        f'autocapitalize=none autocorrect=off spellcheck=false required placeholder="{t["name_ph"]}" value="{e(who)}"'
        f'{"" if who else " autofocus"}></div>'
        f'<div class=f><label for=pw>{t["pw"]}</label><div class=pw><input id=pw name=pw type=password '
        f'autocomplete=current-password required{focus_pw}>'
        f'<button type=button class=eye aria-label="{t["show"]}" aria-pressed=false data-show="{t["show"]}" '
        f'data-hide="{t["hide"]}">{EYE}</button></div></div>'
        f'<button type=submit class=go>{t["go"]} <span aria-hidden=true>→</span></button></form>'
        f'<p class=rem><span aria-hidden=true>🔒</span>{t["remember"]}</p>'
        f'<p class=how>{_how(t["how"])}</p>'
        + (f'<p class=warn>{e(t["miss"].format(", ".join(missing)))}</p>' if missing else "")
        + f'<div class=new>{t["new"]}<br><a class=req href="{e(home)}#pristup">✉️ {t["req"]}</a></div>'
        f'</section></main><footer><a href="{e(home)}">← {t["back"]}</a></footer>')
    return (f"<!doctype html><html lang={'en' if lang == 'en' else 'hr'} translate=no><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1,viewport-fit=cover'>"
            "<meta name=robots content=noindex><meta name=theme-color content='#0d1016'>"
            f"<title>{t['title']} · {e(name)}</title><link rel=icon href=\"data:image/svg+xml,{quote(logo(32)[0])}\">"
            f"<style>{CSS}</style></head><body>{body}<script>{JS}</script></body></html>")


def _how(text):
    """Bold the two audiences ("Igrači:" / "Samo za gledanje:") so the hint reads at a glance."""
    out = []
    for part in text.split(". "):
        head, sep, rest = part.partition(": ")
        out.append(f"<b>{head}:</b> {rest}" if sep else part)
    return ". ".join(out)
