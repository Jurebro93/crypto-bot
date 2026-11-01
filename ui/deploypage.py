"""Funny "deploy in progress" page shown instead of Render's black 502 while a new version starts.

Render cannot do a zero-downtime deploy for a service with a persistent disk: the old instance stops, then the new
one boots (~30-40 s, see start.sh). This page covers that gap in two ways:
  1. deploy_wait.py serves it (status 503) on $PORT from the first second of start.sh, until run_ui.py takes over;
  2. a tiny service worker (/sw.js) keeps a copy in the browser of everyone who opened the site once and shows it
     whenever a page comes back 502/503/504 or the server cannot be reached (the seconds before start.sh runs).
The page checks every 3 s whether the real site is back and reloads by itself.

Light landing style (rule 34), mobile first, Croatian + English in one file; Croatian only for now
(Nicholas, 1.11.), DEPLOY_LANG=auto picks from the cb_lang cookie, then the browser language. DEPLOY_SW=0 turns the service worker off everywhere (kill switch).
"""
import hashlib
import html as _html
import json
import os
from ui import favicon as _fav  # noqa: E402

PATH = "/cekamo-deploy"      # the page itself: preview + what the service worker caches
HEADER = "X-MemeSonar-Deploy"  # marks our own page, so the service worker never swaps it for the cached copy
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# headlines, one picked at random on every view: [hr, en, sub hr, sub en]
JOKES = [
    ["Sonar je zaronio po nove značajke 🐋", "Sonar dove deep for new features 🐋",
     "Izranja za tridesetak sekundi. Ne paničari, samo je duboko.",
     "Surfacing in about thirty seconds. No panic, it's just deep down there."],
    ["Ne, nije rug. Ovo je update 😅", "No, it's not a rug. It's an update 😅",
     "Likvidnost je na mjestu, dev ne prodaje, samo ugrađujemo nešto novo.",
     "Liquidity is still there and the dev isn't selling, we're just adding something new."],
    ["Diamond hands 💎🙌", "Diamond hands 💎🙌",
     "Ne zatvaraj tab od panike. HODL 30 sekundi i vraćamo se jači.",
     "Don't panic-close the tab. HODL for 30 seconds and we're back, stronger."],
    ["Nova verzija ide 100x 🚀", "This version is going 100x 🚀",
     "Trenutno je na krivulji. Za pola minute izlazi na otvoreno tržište.",
     "Still on the bonding curve. Graduating to the open market in half a minute."],
    ["Dev je budan i pusha kod 👨‍💻", "The dev is awake and pushing code 👨‍💻",
     "Svježa verzija se pali. Kava se još kuha, stranica skoro.",
     "A fresh build is starting up. The coffee's still brewing, the site is almost ready."],
    ["Tiho, punimo rakete ⛽", "Shh, we're fuelling the rockets ⛽",
     "Mali deploy, veliki koraci. Probaj za 30 sekundi, ili samo pričekaj ovdje.",
     "Small deploy, big steps. Try again in 30 seconds, or just wait here."],
]


def _news(n=3):
    """Newest entries of share/novosti.json (what was added lately): the hint on the page."""
    try:
        with open(os.path.join(_ROOT, "share", "novosti.json"), encoding="utf-8") as f:
            items = json.load(f)
    except (OSError, ValueError):
        return []
    out = []
    for it in items[:n]:
        if not isinstance(it, dict) or not it.get("naslov"):
            continue
        hr_t, hr_x = str(it["naslov"]), str(it.get("tekst") or "")
        en_t = en_x = None
        try:   # English from the app's own translations, when they already exist (no API call here)
            from ui import i18n
            en_t, en_x = i18n.lookup(" ".join(hr_t.split())), i18n.lookup(" ".join(hr_x.split()))
        except Exception:  # noqa: BLE001
            pass
        out.append({"hr": [hr_t, hr_x[:1].upper() + hr_x[1:]], "en": [en_t, en_x] if en_t else None})
    return out


def _logo():
    try:
        from ui.html import logo
        return logo(30)
    except Exception:  # noqa: BLE001
        return "", "MemeSonar"


CSS = """
:root{--bg:#fff;--soft:#f6f7fb;--fg:#0b1220;--mut:#5b6474;--line:#e8ebf2;--acc:#4f46e5;--acc2:#0fb5a0;--good:#16a34a}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:17px/1.6 Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
-webkit-font-smoothing:antialiased;min-height:100vh;display:flex;flex-direction:column}
main{flex:1;width:100%;max-width:560px;margin:0 auto;padding:22px 16px 36px;text-align:center}
.top{display:flex;align-items:center;justify-content:center;gap:10px;font-weight:750;font-size:18px;letter-spacing:-.01em}
.top svg{display:block}
.pill{display:inline-flex;align-items:center;gap:8px;background:var(--soft);border:1px solid var(--line);border-radius:999px;
padding:5px 13px;font-size:13px;color:var(--mut);font-weight:600;margin-top:26px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--acc2);animation:bl 1.2s infinite}
@keyframes bl{50%{opacity:.25}}
.sonar{position:relative;width:170px;height:170px;margin:26px auto 8px}
.sonar i{position:absolute;inset:0;border-radius:50%;border:2px solid var(--acc2);opacity:0;animation:ping 3s infinite}
.sonar i:nth-child(2){animation-delay:1s}.sonar i:nth-child(3){animation-delay:2s}
@keyframes ping{0%{transform:scale(.35);opacity:.9}100%{transform:scale(1);opacity:0}}
.sonar b{position:absolute;inset:50px;border-radius:50%;background:var(--fg);display:grid;place-items:center;font-size:34px;
box-shadow:0 18px 40px -18px rgba(11,18,32,.6)}
.sweep{position:absolute;inset:8px;border-radius:50%;background:conic-gradient(from 0deg,rgba(15,181,160,.0),rgba(15,181,160,.22));
animation:spin 2.4s linear infinite;-webkit-mask:radial-gradient(circle,transparent 39px,#000 40px);mask:radial-gradient(circle,transparent 39px,#000 40px)}
@keyframes spin{to{transform:rotate(360deg)}}
h1{font-size:clamp(26px,7vw,36px);line-height:1.15;letter-spacing:-.02em;margin:10px 0 10px}
.sub{color:var(--mut);margin:0 auto;max-width:440px}
.cnt{display:flex;align-items:center;justify-content:center;gap:10px;margin:22px 0 4px;color:var(--mut);font-size:15px}
.cnt svg{transform:rotate(-90deg)}.cnt circle{fill:none;stroke-width:4}
.btn{display:inline-flex;align-items:center;justify-content:center;border-radius:999px;padding:14px 26px;font-weight:650;font-size:16px;
border:1px solid transparent;cursor:pointer;font-family:inherit;min-height:48px;transition:transform .15s,background .15s}
.btn:active{transform:scale(.97)}
.btn.p{background:var(--fg);color:#fff}.btn.g{background:#fff;border-color:var(--line);color:var(--fg)}
.row{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin-top:14px}
.card{background:#fff;border:1px solid var(--line);border-radius:22px;padding:18px 18px 16px;margin-top:26px;text-align:left;
box-shadow:0 30px 60px -45px rgba(11,18,32,.35)}
.card h2{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut);margin:0 0 8px;font-weight:700}
.card p{margin:0;font-size:15px;color:var(--mut)}.card p b{color:var(--fg);display:block;font-size:16px;margin-bottom:2px}
.game{display:flex;align-items:flex-end;justify-content:center;gap:5px;height:84px;margin:6px 0 10px;
border-bottom:1px solid var(--line);padding-bottom:6px;overflow:hidden}
.game span{width:12px;border-radius:3px;background:var(--good);transition:height .25s}
.game span.r{background:#ef4444}
.meta{display:flex;justify-content:space-between;font-size:13px;color:var(--mut);margin-bottom:10px}
.safe{font-size:13px;color:var(--mut);margin-top:22px}
footer{text-align:center;font-size:12px;color:var(--mut);padding:0 16px 22px}
@media (prefers-reduced-motion:reduce){.sonar i,.sweep,.dot{animation:none}}
"""

JS = r"""
(function(){
var D=window.__D,lang=D.lang||'hr';   // Croatian only for now (DEPLOY_LANG=auto: cookie, then browser language)
if(lang==='auto')lang=(document.cookie.match(/(?:^|; )cb_lang=(hr|en)/)||[])[1]||
  (/^(hr|bs|sr)/.test((navigator.language||'').toLowerCase())||location.hostname.indexOf('app.')===0?'hr':'en');
var en=lang==='en',T=D.t[lang],$=function(id){return document.getElementById(id)};
document.documentElement.lang=lang;
var off=navigator.onLine===false,j=D.jokes[Math.floor(Math.random()*D.jokes.length)];
$('h').textContent=off?T.offH:j[en?1:0];$('s').textContent=off?T.offS:j[en?3:2];
document.title=(off?T.offH:T.title)+' · MemeSonar';
$('pill').textContent=off?T.offPill:T.pill;$('again').textContent=T.again;$('safe').textContent=T.safe;
$('gh').textContent=T.gh;$('pump').textContent=T.pump;$('dump').textContent=T.dump;
var news=D.news.filter(function(n){return en?n.en:1});
if(news.length){var k=0,show=function(){var n=news[k%news.length],v=en?n.en:n.hr;$('nt').textContent=v[0];$('nx').textContent=v[1]||'';k++};
  $('nh').textContent=T.nh;show();setInterval(show,7000)}else{$('news').style.display='none'}
// countdown ring + a quiet check every 3 s: back as soon as the real site answers
var left=30,C=2*Math.PI*14,ring=$('ring');ring.style.strokeDasharray=C;
function paint(){ring.style.strokeDashoffset=C*(1-left/30);$('cl').textContent=left>0?T.cnt.replace('{s}',left):T.soon}
function check(){fetch(location.href,{cache:'no-store',credentials:'same-origin',redirect:'manual'}).then(function(r){
  var dep=r.headers.get('X-MemeSonar-Deploy');
  if(!dep&&[502,503,504].indexOf(r.status)<0){$('cl').textContent=T.back;location.reload()}}).catch(function(){})}
paint();setInterval(function(){if(left>0)left--;paint();if(left%3===0)check()},1000);
$('again').onclick=function(){location.reload()};
// pump it while you wait: every tap a green candle, now and then the market answers with a red one
var g=$('g'),h=40,ath=0,taps=0;try{ath=+localStorage.getItem('ms_deploy_ath')||0}catch(e){}
function candle(up){var s=document.createElement('span');var d=up?(8+Math.random()*14):-(6+Math.random()*12);h=Math.max(8,Math.min(78,h+d));
  s.style.height=h+'px';if(!up)s.className='r';g.appendChild(s);while(g.children.length>22)g.removeChild(g.firstChild)}
for(var i=0;i<10;i++)candle(Math.random()>.45);
function score(){$('sc').textContent=T.sc.replace('{n}',taps);$('ath').textContent=T.ath.replace('{n}',ath)}
$('pump').onclick=function(){taps++;candle(Math.random()>.18);if(taps>ath){ath=taps;try{localStorage.setItem('ms_deploy_ath',ath)}catch(e){}}score()};
$('dump').onclick=function(){candle(false);$('sc').textContent=T.paper};
score();
})();
"""

TEXT = {
    "hr": {"title": "Deploy u tijeku", "pill": "Radimo super cool deploy", "again": "Probaj sad",
           "cnt": "Sam provjeravam za {s} s", "soon": "Još malo, provjeravam…", "back": "Tu smo! Učitavam…",
           "nh": "💡 Zadnje dodano", "gh": "🚀 Pumpaj dok čekaš", "pump": "Pumpaj", "dump": "Prodaj",
           "sc": "Tvojih pumpi: {n}", "ath": "Rekord (ATH): {n}", "paper": "Paper hands detektirane 🧻",
           "safe": "Traje 20–40 sekundi. Ništa se ne gubi: demo pozicije, postavke i podaci su na sigurnom. "
                   "Stranica se sama osvježi čim smo spremni.",
           "offH": "Nema interneta 📵", "offS": "Izgleda da ti je mobitel izgubio vezu. Čim se vrati, stranica se sama učita.",
           "offPill": "Bez veze"},
    "en": {"title": "Deploy in progress", "pill": "Shipping a super cool deploy", "again": "Try now",
           "cnt": "Checking again in {s} s", "soon": "Almost there, checking…", "back": "We're back! Loading…",
           "nh": "💡 Recently added", "gh": "🚀 Pump it while you wait", "pump": "Pump", "dump": "Sell",
           "sc": "Your pumps: {n}", "ath": "Record (ATH): {n}", "paper": "Paper hands detected 🧻",
           "safe": "This takes 20–40 seconds. Nothing is lost: demo positions, settings and data are safe. "
                   "The page reloads by itself as soon as we're ready.",
           "offH": "No internet 📵", "offS": "Looks like your phone lost its connection. The page loads by itself once it's back.",
           "offPill": "Offline"},
}

_cache = {}


def html():
    """The whole page as one string (no outside files: it must work while the server is down)."""
    if "p" not in _cache:
        svg, name = _logo()
        data = json.dumps({"jokes": JOKES, "news": _news(), "t": TEXT,
                           "lang": os.environ.get("DEPLOY_LANG", "hr")}, ensure_ascii=False).replace("</", "<\\/")
        j = JOKES[0]
        _cache["p"] = f"""<!doctype html><html lang=hr><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><meta name=robots content="noindex,nofollow">
<meta name=theme-color content="#ffffff"><title>Deploy u tijeku · {_html.escape(name)}</title>{_fav.HEAD}
<style>{CSS}</style></head><body><main>
<div class=top>{svg}<span>{_html.escape(name)}</span></div>
<div class=pill><span class=dot></span><span id=pill>{TEXT['hr']['pill']}</span></div>
<div class=sonar aria-hidden=true><i></i><i></i><i></i><div class=sweep></div><b>🚀</b></div>
<h1 id=h>{_html.escape(j[0])}</h1><p class=sub id=s>{_html.escape(j[2])}</p>
<div class=cnt><svg width=34 height=34 viewBox="0 0 34 34"><circle cx=17 cy=17 r=14 stroke="#e8ebf2"/>
<circle id=ring cx=17 cy=17 r=14 stroke="#0fb5a0" stroke-linecap=round /></svg><span id=cl>…</span></div>
<div class=row><button class="btn p" id=again type=button>Probaj sad</button></div>
<section class=card id=news><h2 id=nh></h2><p><b id=nt></b><span id=nx></span></p></section>
<section class=card><h2 id=gh></h2><div class=game id=g aria-hidden=true></div>
<div class=meta><span id=sc></span><span id=ath></span></div>
<div class=row style="margin-top:4px"><button class="btn p" id=pump type=button>Pumpaj</button>
<button class="btn g" id=dump type=button>Prodaj</button></div></section>
<p class=safe id=safe>{TEXT['hr']['safe']}</p>
</main><footer>memesonar.app</footer>
<script>window.__D={data};</script><script>{JS}</script></body></html>"""
    return _cache["p"]


def sw_on():
    return os.environ.get("DEPLOY_SW", "1") != "0"


def sw_js():
    """Service worker: keeps the page above in the browser and shows it when the server is restarting.
    It touches only page loads (navigations), never API calls, and passes every normal answer through untouched.
    The version follows the page, so a new novosti.json entry refreshes the stored copy on the next visit."""
    if not sw_on():   # kill switch: removes itself from every browser that has it
        return ("self.addEventListener('install',function(){self.skipWaiting()});"
                "self.addEventListener('activate',function(e){e.waitUntil(caches.keys().then(function(k){"
                "return Promise.all(k.filter(function(n){return n.indexOf('ms-deploy')===0}).map(function(n){return caches.delete(n)}))})"
                ".then(function(){return self.registration.unregister()}))});")
    ver = hashlib.sha1(html().encode("utf-8")).hexdigest()[:10]
    return f"""// MemeSonar: friendly page instead of a bare 502 while a new version starts (ui/deploypage.py)
var C='ms-deploy-{ver}',P='{PATH}',H='{HEADER.lower()}';
self.addEventListener('install',function(e){{e.waitUntil(caches.open(C).then(function(c){{return c.add(new Request(P,{{cache:'reload'}}))}})
  .then(function(){{return self.skipWaiting()}}))}});
self.addEventListener('activate',function(e){{e.waitUntil(caches.keys().then(function(k){{return Promise.all(k.filter(function(n){{
  return n.indexOf('ms-deploy')===0&&n!==C}}).map(function(n){{return caches.delete(n)}}))}}).then(function(){{return self.clients.claim()}}))}});
function stored(){{return caches.open(C).then(function(c){{return c.match(P)}})}}
self.addEventListener('fetch',function(e){{var r=e.request;if(r.mode!=='navigate'||r.method!=='GET')return;
  e.respondWith(fetch(r).then(function(res){{
    if([502,503,504].indexOf(res.status)<0||res.headers.get(H))return res;
    return stored().then(function(s){{return s||res}})}},function(err){{return stored().then(function(s){{if(s)return s;throw err}})}}))}});
"""


def register_tag():
    """<script> every page carries: registers /sw.js (or nothing when DEPLOY_SW=0)."""
    if not sw_on():
        return ("<script>navigator.serviceWorker&&navigator.serviceWorker.getRegistrations&&navigator.serviceWorker"
                ".getRegistrations().then(function(r){r.forEach(function(x){x.unregister()})}).catch(function(){})</script>")
    return ("<script>if('serviceWorker'in navigator&&location.protocol==='https:')window.addEventListener('load',function()"
            "{navigator.serviceWorker.register('/sw.js').catch(function(){})})</script>")
