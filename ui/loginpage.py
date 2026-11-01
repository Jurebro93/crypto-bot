"""/prijava: the login page. A page of its own (no app menu, which needs a login anyway): a centred card in the
MemeSonar colours (light, airy and minimal like the public landing page: same palette, Inter, black pill button, indigo focus), big inputs, built
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
:root{--bg:#fff;--soft:#f6f7fb;--fg:#0b1220;--mut:#5b6474;--line:#e8ebf2;--acc:#4f46e5;--acc2:#0fb5a0;--bad:#991b1b;color-scheme:light}
*{box-sizing:border-box}html,body{margin:0;min-height:100%}
body{background:var(--bg);color:var(--fg);font:16px/1.6 Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
 -webkit-font-smoothing:antialiased;display:flex;flex-direction:column;min-height:100vh;min-height:100dvh}
a{color:inherit;text-decoration:none}
.top{display:flex;align-items:center;justify-content:space-between;gap:12px;width:100%;max-width:1080px;margin:0 auto;padding:0 20px;height:64px}
.brand{display:flex;align-items:center;gap:9px;font-weight:750;font-size:18px;letter-spacing:-.02em}
.lang{display:flex;background:var(--soft);border:1px solid var(--line);border-radius:999px;padding:3px;font-size:13px;font-weight:600}
.lang a{padding:4px 11px;border-radius:999px;color:var(--mut)}.lang a.on{background:#fff;color:var(--fg);box-shadow:0 1px 3px rgba(11,18,32,.08)}
main{flex:1;display:flex;align-items:center;justify-content:center;padding:32px 20px 40px}
.box{width:100%;max-width:420px}
h1{margin:0;font-size:clamp(30px,6vw,38px);line-height:1.1;letter-spacing:-.035em;font-weight:800;text-align:center}
.sub{margin:10px 0 28px;color:var(--mut);font-size:17px;text-align:center}
.card{background:#fff;border:1px solid var(--line);border-radius:24px;padding:28px;box-shadow:0 30px 60px -40px rgba(11,18,32,.25)}
label{display:block;font-size:14px;font-weight:600;margin:0 0 6px}
.f{margin:0 0 16px}.pw{position:relative}
input{width:100%;padding:14px 16px;font:inherit;font-size:16px;color:var(--fg);background:var(--soft);
 border:1px solid var(--line);border-radius:14px;outline:none;-webkit-appearance:none;appearance:none;transition:border-color .15s,box-shadow .15s,background .15s}
.pw input{padding-right:52px}
input:focus{border-color:var(--acc);background:#fff;box-shadow:0 0 0 4px rgba(79,70,229,.12)}
input::placeholder{color:#9aa3b2}
.eye{position:absolute;right:7px;top:50%;transform:translateY(-50%);width:38px;height:38px;border:0;border-radius:10px;background:transparent;
 color:var(--mut);cursor:pointer;display:grid;place-items:center}.eye:hover{color:var(--fg);background:var(--line)}
.err{background:#fef2f2;border:1px solid #fecaca;color:var(--bad);border-radius:16px;padding:12px 14px;margin:0 0 16px;font-size:15px}
.go{width:100%;margin-top:6px;padding:15px 26px;border:0;border-radius:999px;cursor:pointer;font:inherit;font-size:16px;font-weight:650;
 color:#fff;background:var(--fg);display:flex;align-items:center;justify-content:center;gap:8px;transition:transform .15s,box-shadow .15s,background .15s}
.go:hover{background:#1f2937;box-shadow:0 10px 30px -10px rgba(11,18,32,.5)}.go:active{transform:scale(.98)}
.go:focus-visible{outline:3px solid rgba(79,70,229,.35);outline-offset:2px}
.rem{margin:14px 0 0;color:var(--mut);font-size:13px;text-align:center}
.how{margin:18px 0 0;padding:12px 14px;border-radius:14px;background:var(--soft);color:var(--mut);font-size:13.5px;line-height:1.5}
.how b{color:var(--fg);font-weight:600}
.new{margin:26px 0 0;text-align:center;color:var(--mut);font-size:15px}
.req{display:inline-flex;align-items:center;justify-content:center;margin-top:10px;padding:10px 20px;border-radius:999px;background:#fff;
 border:1px solid var(--line);color:var(--fg);font-weight:650;font-size:15px;transition:border-color .15s}.req:hover{border-color:#cfd5e1}
.warn{margin:14px 0 0;color:var(--bad);font-size:13px}
footer{text-align:center;font-size:13px;color:var(--mut);padding:20px;border-top:1px solid var(--line)}footer a:hover{color:var(--fg)}
@media (max-width:480px){main{align-items:flex-start;padding:24px 16px 32px}.top{padding:0 16px}.card{padding:22px 18px;border-radius:20px}.sub{margin-bottom:22px}}
"""

EYE = ('<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
       'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/>'
       '<circle cx="12" cy="12" r="3"/></svg>')

JS = """
(()=>{const b=document.querySelector('.eye'),p=document.getElementById('pw');if(!b||!p)return;
b.onclick=()=>{const s=p.type==='password';p.type=s?'text':'password';b.setAttribute('aria-label',s?b.dataset.hide:b.dataset.show);
b.setAttribute('aria-pressed',s?'true':'false');p.focus()}})();
"""


def _sw():
    from ui import deploypage
    return deploypage.register_tag()


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
        f'<main><div class=box><h1 id=h>{t["hello"]}</h1><p class=sub>{t["sub"]}</p>'
        f'<section class=card aria-labelledby=h>'
        + (f'<div class=err role=alert>{e(err)}</div>' if err else "")
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
        f'<p class=rem>{t["remember"]}</p>'
        f'<p class=how>{_how(t["how"])}</p>'
        + (f'<p class=warn>{e(t["miss"].format(", ".join(missing)))}</p>' if missing else "")
        + f'</section><div class=new>{t["new"]}<br><a class=req href="{e(home)}#pristup">{t["req"]} →</a></div>'
        f'</div></main><footer><a href="{e(home)}">← {t["back"]}</a></footer>')
    return (f"<!doctype html><html lang={'en' if lang == 'en' else 'hr'} translate=no><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1,viewport-fit=cover'>"
            "<meta name=robots content=noindex><meta name=theme-color content='#ffffff'>"
            f"<title>{t['title']} · {e(name)}</title><link rel=icon href=\"data:image/svg+xml,{quote(logo(32)[0])}\">"
            f"<style>{CSS}</style></head><body>{body}<script>{JS}</script>{_sw()}</body></html>")


def _how(text):
    """Bold the two audiences ("Igrači:" / "Samo za gledanje:") so the hint reads at a glance."""
    out = []
    for part in text.split(". "):
        head, sep, rest = part.partition(": ")
        out.append(f"<b>{head}:</b> {rest}" if sep else part)
    return ". ".join(out)
