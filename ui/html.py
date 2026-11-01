"""Small HTML helpers: layout, tables, badges, bars. No templates, no JS framework."""
import contextvars
import datetime as dt
import html
import os
import re
import time
from urllib.parse import quote
from ui.cols import CSS as COLS_CSS, JS as COLS_JS

# Menu: a few plain groups, every page with an icon and a one-line description. The same list drives the side menu
# (laptop), the drawer + bottom bar (phone), the "Gdje je što" page and the page part of the search box.
def _p(href, icon, name, desc, kw=""):
    return {"href": href, "icon": icon, "name": name, "desc": desc, "kw": kw}


SECTIONS = [
    ("Početak", [
        _p("/", "🏠", "Pregled", "Najjači tokeni upravo sada i kako bot stoji danas.", "home početna dashboard kandidati"),
        _p("/mapa", "🧭", "Gdje je što", "Sve stranice na jednom mjestu, s kratkim opisom.", "izbornik mapa pomoć help"),
        _p("/pojmovnik", "📖", "Pojmovnik", "Što znači svaki pojam, broj i stranica, običnim riječima.",
           "objašnjenje pojmovi rječnik značenje help pomoć info"),
        _p("/izvjestaj", "📰", "Jutarnji izvještaj", "Dnevni sažetak svega bitnog, gotov prije 8 h.", "email mail report sažetak"),
        _p("/whatsapp", "📲", "Za WhatsApp", "Slika i poruka za vašu WhatsApp grupu: ljestvica, tradeovi, novosti.",
           "whatsapp grupa podijeli pošalji share novosti"),
    ]),
    ("Natjecanje", [
        _p("/natjecanje", "🏆", "Natjecanje", "Tvoj demo račun: kupi tokene iz prijedloga alata i natječi se s ostalima.",
           "liga ljestvica igra igrači demo račun kupi dca automatska kupnja prosjek"),
        _p("/copy-trading", "🔁", "Copy trading", "Prati influencera ili wallet: alat ulazi i izlazi umjesto tebe.",
           "kopiraj prati influencer kol wallet novčanik copy trade"),
        _p("/nas-token", "🪙", "Naš token", "Naš vlastiti Solana meme token: trezor, generator, marketing i influenceri.",
           "token generator trezor vault sef lansiraj pump.fun meme coin marketing suradnja strategija promocija"),
        _p("/prijedlozi", "💡", "Prijedlozi", "Predloži što bi alat trebao raditi bolje.", "ideje feedback"),
        _p("/zahtjevi", "📨", "Zahtjevi za pristup", "Tko je na naslovnoj stranici zatražio pristup; pozivnica jednim klikom.",
           "pristup zahtjev pozivnica invite lista čekanja novi korisnici registracija"),
        _p("/dobrodosli", "🚀", "Naslovna stranica", "Javna prodajna stranica koju vide ljudi bez računa.",
           "landing naslovnica reklama marketing javna stranica home"),
    ]),
    ("Tokeni", [
        _p("/tokens", "🪙", "Svi tokeni", "Svaki token iz zadnjih 7 dana sa svim provjerama.", "lista coin"),
        _p("/radar", "📡", "Zadnji sken", "Što je skener upravo našao (svake 2 minute).", "radar hype novi"),
        _p("/dugorocno", "🌱", "Dugoročni", "Sigurniji stariji tokeni koji se oporavljaju i rastu (Fartcoin, Useless…).",
           "dugorocno long term preživjeli veliki holderi burze"),
        _p("/events", "📅", "Eventi", "Događaji oko kojih nastaju tokeni.", "kalendar događaji"),
        _p("/watch", "⏳", "Prije eventa", "Kreću li tokeni prije događaja.", "watch"),
    ]),
    ("Ljudi i novčanici", [
        _p("/kol", "📣", "KOL-ovi", "Tko zove tokene na X-u i Telegramu i što se nakon toga dogodi.",
           "influenceri pozivi twitter x ljestvica"),
        _p("/izvori", "💬", "Telegram i novčanici", "Telegram kanali, KOL novčanici i kad više izvora zove isti token.",
           "telegram kanali konvergencija"),
        _p("/wallets", "👛", "Novčanici", "Tko kupuje rano i zarađuje; lista za kopiranje.", "walleti wallet smart money copy"),
        _p("/korelacije", "🕸", "Korelacije", "Tko radi zajedno: grupe KOL-ova, povezani novčanici, AI tumačenje.",
           "grupe klasteri veze"),
    ]),
    ("Bot trguje (demo)", [
        _p("/paper", "🤖", "Demo trading", "Bi li bot zaradio: njegovi ulazi i izlazi bez pravog novca.", "paper trejd"),
        _p("/kol-test", "🧪", "KOL test", "7-dnevni test: isplati li se ući odmah na KOL poziv.", "test"),
        _p("/izlazi", "🚪", "Izlazi", "Kada bot prodaje i koliko to vrijedi.", "exit prodaja stop"),
    ]),
    ("Sustav", [
        _p("/learn", "🧠", "Učenje", "Što bot uči iz ishoda i kako mijenja ocjene.", "learn težine"),
        _p("/criteria", "📏", "Pravila", "Svi pragovi i težine po kojima bot ocjenjuje.", "kriteriji criteria"),
        _p("/market", "🌡", "Tržište", "Je li tržište vruće ili hladno.", "market volumen"),
        _p("/usage", "💸", "Potrošnja", "Koliko trošimo na servise i hoće li budžet izdržati.", "trošak helius apify budžet"),
        _p("/outputs", "🗂", "Izvještaji modula", "Pisani izvještaji pojedinih dijelova bota.", "outputs datoteke"),
    ]),
]
# detail pages light up the menu item they belong to
NAV_PREFIX = {"/token/": "/tokens", "/wallet/": "/wallets", "/outputs/": "/outputs", "/natjecanje/": "/natjecanje",
              "/prijedlozi/": "/prijedlozi", "/kol/": "/kol",
              "/prijava": "/natjecanje", "/nas-token/": "/nas-token", "/registracija": "/natjecanje", "/izvjestaj/": "/izvjestaj"}
# phone bottom bar: the four places people go most, Natjecanje in the middle
BOTTOM = [("/", "🏠", "Pregled"), ("/tokens", "🪙", "Tokeni"), ("/natjecanje", "🏆", "Natjecanje"), ("/paper", "🤖", "Demo")]

# Logo: three candidates, LOGO picks the one shown. Plain SVG, no files to serve.
LOGOS = {
    "radar": ("KriptoRadar", '<svg viewBox="0 0 32 32" width="{s}" height="{s}" aria-hidden="true"><defs><linearGradient '
              'id="lgr" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#5b5bf6"/><stop offset="1" '
              'stop-color="#12c9a4"/></linearGradient></defs><rect width="32" height="32" rx="9" fill="url(#lgr)"/>'
              '<circle cx="16" cy="16" r="10" fill="none" stroke="#fff" stroke-opacity=".4" stroke-width="1.6"/>'
              '<circle cx="16" cy="16" r="5.5" fill="none" stroke="#fff" stroke-opacity=".7" stroke-width="1.6"/>'
              '<path d="M16 16L24 9.5" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/>'
              '<circle cx="21.6" cy="19.6" r="2.3" fill="#fff"/></svg>'),
    "skok": ("Skok", '<svg viewBox="0 0 32 32" width="{s}" height="{s}" aria-hidden="true"><defs><linearGradient id="lgs" '
             'x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="#f76707"/><stop offset="1" stop-color="#e64980"/>'
             '</linearGradient></defs><rect width="32" height="32" rx="9" fill="url(#lgs)"/><path d="M7 23l6-7 4 3.5 8-9.5" '
             'fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>'
             '<path d="M19 10h6v6" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" '
             'stroke-linejoin="round"/></svg>'),
    "signal": ("Signal", '<svg viewBox="0 0 32 32" width="{s}" height="{s}" aria-hidden="true"><defs><linearGradient '
               'id="lgg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#9945ff"/><stop offset="1" '
               'stop-color="#14f195"/></linearGradient></defs><path d="M16 1.5l12.6 7.25v14.5L16 30.5 3.4 23.25V8.75z" '
               'fill="url(#lgg)"/><path d="M7.5 16.5h3.5l2.2-5.5 3.6 10 2.2-6h5.5" fill="none" stroke="#fff" '
               'stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"/></svg>'),
}
LOGO = os.environ.get("UI_LOGO", "radar") if os.environ.get("UI_LOGO", "radar") in LOGOS else "radar"


def logo(size=30, variant=None):
    name, svg = LOGOS[variant or LOGO]
    return svg.replace("{s}", str(size)), name


def nav_item(path):
    """href of the menu item that is lit for this path."""
    for _, items in SECTIONS:
        if any(path == p["href"] for p in items):
            return path
    for pre, href in NAV_PREFIX.items():
        if path.startswith(pre):
            return href
    return None


def nav_group(path):
    href = nav_item(path)
    return next((sec for sec, items in SECTIONS if any(p["href"] == href for p in items)), None)


# one box at the top of every page: what the page is for, which data is on it, and where it sits in the pipeline
# (kalendar -> skener -> slojevi T0-T3 -> Šansa -> demo trading -> učenje). Keyed by route or route prefix.
INTRO = {
    "/pojmovnik": ("Što znači svaki pojam u alatu", "Svaki pojam, ocjena, stupac i stranica objašnjeni običnim riječima, "
                   "s primjerom, gdje ga vidiš i povezanim pojmovima. Svaki ⓘ u aplikaciji otvara objašnjenje odavde.",
                   "Jedno mjesto istine za objašnjenja: kad se doda novi pojam, objašnjenje se pojavi svugdje."),
    "/korelacije": ("Tko radi zajedno i kako", "KOL grupe koje zovu iste tokene, walleti koji kupe prije poziva određenog "
                    "računa, walleti istog vlasnika, signali koji idu uz pumpu i što poznate grupe diraju sada, s AI "
                    "tumačenjem na vrhu.", "Spaja X, Telegram i on-chain podatke: praćene grupe idu u registar walleta, "
                    "a njihova aktivnost je rani signal za ulaz prije gomile."),
    "/": ("Odgovor na pitanje \"što sad?\"", "Istaknuti tokeni po klasi poredani po Šansi za skok, demo rezultat, kako se baza "
          "puni u odnosu na prethodne dane i tablica tokena koji su prošli više analiza. Klasteri walleta i stanje baza su sklopljeni ispod.",
          "Završna točka cjevovoda: ovdje se vidi što je iz svih slojeva izašlo kao kandidat."),
    "/tokens": ("Sve što alat zna o svakom tokenu", "Svaki token viđen u zadnjih 7 dana kroz sve analize (hype, X, smart money, "
                "KOL, holderi, rug, event, demo), poredan po Šansi; odvojeno event tokeni, stariji i odbačeni.",
                "Povijest i puna slika; za trenutak zadnjeg prolaza služi Zadnji sken, za odluku Pregled."),
    "/radar": ("Što je hype skener vidio u zadnjem prolazu", "Kandidati iz zadnjeg skena (svake 2 min) s razlozima i rizicima, "
               "odbačeni, narativi (X trendovi, kopije), smart money, radi li ocjena, Apify trošak.",
               "Prvi sloj cjevovoda: sirovi signali s DexScreenera, pump.funa i X-a prije skupljih provjera."),
    "/events": ("Događaji oko kojih bi mogli nastati tokeni", "Kalendar događaja s hype ocjenom i tokeni koje je DexScreener našao "
                "za svaki (pravi vs. kopije).", "Ulaz za klasu Event: pravi token događaja ide u slojevitu analizu kao event kandidat."),
    "/wallets": ("Tko kupuje rano i zarađuje", "Registar walleta iz svih analiza (rani kupci, smart, top traderi, botovi, devovi), "
                 "ocjena profitabilnosti, copy lista.", "Smart walleti među prvim kupcima su signal u hype ocjeni i T1 provjeri; "
                 "rotacijski devovi su upozorenje."),
    "/wallet/": ("Jedan wallet do detalja", "Trejdovi, PnL, tokeni u kojima je bio rano, oznake.",
                 "Dokaz iza signala smart money i klastera na stranici tokena."),
    "/token/": ("Jedan token kroz sve slojeve", "Šansa, confidence, klasa i razina, Za/Protiv, pa svaki sloj (event, hype, rug, "
                "demo, walleti) sklopljen sa sažetkom.", "Mjesto gdje se svaki broj s Pregleda može provjeriti do izvora."),
    "/paper": ("Bi li bot zaradio da trguje", "Demo trgovanje bez novca: ulazi po pravilima, izlazi, rezultat, dnevni pregled "
               "s greškama i lekcijama, kalibracija confidencea.", "Bot iz ishoda demo trejdova uči; pravi trading "
               "samo preslikava ove ulaze."),
    "/zahtjevi": ("Novi ljudi koji žele ući", "Zahtjevi s javne naslovne stranice: ime, kontakt, iskustvo i što ih "
                  "zanima. Gumb Pozovi napravi jednokratni link za registraciju.", "Ulaz u Natjecanje: od zahtjeva do "
                  "pozivnice i demo računa od $1.000."),
    "/natjecanje": ("Ljudi protiv bota", "Demo računi korisnika, njihovi ulazi i ljestvica.",
                    "Usporedba ljudskog izbora s botovim na istim tokenima."),
    "/copy-trading": ("Kopiraj influencera ili wallet", "Statistika influencera i walleta, gumb za praćenje, svaki ulaz i "
                      "izlaz iz praćenja s razlogom.", "Ulazi idu na tvoj demo račun u Natjecanju."),
    "/nas-token/strategija": ("Kako naš token privući ljude", "Koncepti priče i use casea, igrice, plan po fazama od "
                              "ideje do prvog mjeseca, besplatne i plaćene metode, uloge za tim od 4, gotovi "
                              "Claude Code promptovi, brojke za praćenje i izvori istraživanja.", "Marketinški dio "
                              "Našeg tokena; spaja istraživanje s našim podacima o influencerima i vremenu objava."),
    "/nas-token": ("Naš vlastiti token, od ideje do lansiranja", "Popis naših tokena, zajednički trezor (tko je "
                   "koliko uplatio), generator s troškom lansiranja, paket za pump.fun, marketinški plan i "
                   "influenceri za suradnju, a nakon lansiranja brojke tokena i prijedlozi.", "Koristi sve što alat "
                   "već mjeri (KOL-ove, vrijeme objava, val poziva) za naš token; ključeve nikad ne drži."),
    "/prijedlozi": ("Što bi alat trebao raditi drugačije", "Prijedlozi korisnika i njihov status.", "Ulaz za sljedeće faze razvoja."),
    "/learn": ("Što alat uči iz ishoda", "Skok po klasi, koliko koji signal pomaže, udio skokova po rasponu vrijednosti, parovi signala, "
               "povijest automatskih promjena težina, propušteni tokeni.", "Zatvara krug: ishodi iz Pregleda i Demo tradinga "
               "mijenjaju težine kojima skener ocjenjuje sutra."),
    "/criteria": ("Pravila i težine, uživo iz koda", "Svaki prag i težina po modulu: eventi, DexScreener, klase i razine, hype, "
                  "rug filter, walleti, confidence, demo.", "Referenca: kad te zanima zašto je broj takav kakav jest."),
    "/market": ("Je li tržište vruće ili hladno", "Volumen po launchpadima i Solana DEX-u (DefiLlama), režim 0-100.",
                "Vrućina tržišta je jedan od signala u hype ocjeni; koliko vrijedi, bot uči sam."),
    "/usage": ("Koliko trošimo i gdje curi", "Helius krediti i Apify dolari po modulu, dnevno i mjesečno, upozorenja.",
               "Čuvar budžeta za slojevitu analizu: skupe razine T2/T3 žive unutar ovih limita."),
    "/outputs": ("Pisani izvještaji modula", "Markdown datoteke koje moduli pišu u output/ (kalendar, dex, rug, demo).",
                 "Sirovi izlaz za provjeru; sve bitno iz njih je i u bazama i na stranicama."),
    "/watch": ("Kreću li tokeni prije eventa", "Tokeni vezani uz veće evente prate se od 14 dana prije: satne snimke "
               "volumena i kupnji, kupci preko Heliusa usporedno s registrom walleta, korelacija s približavanjem eventa.",
               "Nastavak Eventa: pokazuje skuplja li se volumen i smart money prije eventa, prije nego token uđe u skener."),
    "/izvori": ("Telegram kanali, KOL novčanici i konvergencija", "Javni Telegram call kanali, KOL novčanici na lancu i "
                "trenutci kad više izvora zove isti token.", "Izvor značajki telegram i konvergencija u hype ocjeni i "
                "konvergencijskih demo ulaza."),
    "/dugorocno": ("Sigurniji sloj: preživjeli i oživljeni tokeni", "Stariji tokeni koji se oporavljaju od padova i rastu s "
                   "tržištem (uzor Fartcoin i Useless) i stari tokeni koji se bude, s ocjenom, razlozima i demo portfeljem "
                   "usporedno sa SOL-om.", "Odvojeno od lova na nove tokene: drugi izvori, drugi horizont (tjedni i mjeseci), "
                   "vlastito učenje na povijesti cijena."),
    "/kol-test": ("Isplati li se ući odmah na KOL poziv", "Odvojena 7-dnevna demo knjiga: $50 na svaki svjež poziv KOL-a "
                  "(X, Telegram, KOL novčanici), koliko daleko i koliko brzo token ode, pad prije toga i što bi zaradio "
                  "izlaz na +20, +30, +40 ili +50%.", "Samo mjerenje: ne miješa se s glavnim demo tradingom i bot iz nje "
                  "ne uči; rezultat pokazuje koje KOL-ove i koje izlaze vrijedi uključiti u glavnu strategiju."),
    "/kol": ("Tko zove tokene i što se nakon toga dogodi", "KOL-ovi i influenceri s X-a i Telegrama, njihovi pozivi s linkovima, "
             "pomak cijene i volumena poslije, grupe koje zovu zajedno, moć poziva.", "Signal koordiniranog poziva u hype ocjeni "
             "i izvor rotacijskih dev walleta."),
}


def intro_html(path):
    key = path if path in INTRO else next((k for k in INTRO if k != "/" and path.startswith(k.rstrip("/") + "/")), None)
    if key is None:
        return ""
    cilj, sto, uloga = INTRO[key]
    return (f"<details class=intro><summary><b>{esc(cilj)}</b> <span class=mut>· što je na ovoj stranici</span></summary>"
            f"<div>{esc(sto)}</div><div class=mut style='margin-top:4px'>Uloga u cjelini: {esc(uloga)}</div></details>")


def _h1_info(body, path):
    """The page title gets an ⓘ that explains the whole page."""
    i = body.find("</h1>")
    if i < 0:
        return body
    pi = page_info(path)
    return body[:i] + (" " + pi if pi else "") + body[i:] if pi else body


def with_intro(body, path):
    """The intro box goes right under the page title, or at the top when the page has no <h1>."""
    intro = intro_html(path)
    if not intro:
        return body
    return body.replace("</h1>", "</h1>" + intro, 1) if "</h1>" in body else intro + body


CSS = """
button.sm{padding:2px 7px;font-size:12px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg);cursor:pointer}
button.sm:hover{border-color:var(--acc);color:var(--acc)}.nw{white-space:nowrap}
:root{--bg:#f6f7f9;--card:#fff;--fg:#1b1f24;--mut:#5f6b7a;--line:#e3e6ea;--acc:#3b5bdb;
--good:#2b8a3e;--warn:#e67700;--bad:#c92a2a;--goodbg:#ebfbee;--warnbg:#fff4e6;--badbg:#fff5f5;--bar:#4c6ef5}
@media (prefers-color-scheme:dark){:root{--bg:#101318;--card:#181c23;--fg:#e6e9ee;--mut:#8b96a5;--line:#2a303a;
--acc:#7a92ff;--good:#51cf66;--warn:#ffa94d;--bad:#ff6b6b;--goodbg:#13261a;--warnbg:#2b2012;--badbg:#2c1517;--bar:#748ffc}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
.intro{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--acc);border-radius:8px;padding:10px 14px;margin:0 0 14px;font-size:14px}
main{max-width:1400px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:8px 0 4px}h2{font-size:16px;margin:24px 0 8px}h3{font-size:14px;margin:16px 0 6px}
.mut{color:var(--mut)}.tdesc{color:var(--mut);font-size:13px;margin:4px 0 8px;padding-left:8px;border-left:3px solid var(--line)}.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin:10px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 14px}
.stat .v{font-size:22px;font-weight:600}.stat .l{color:var(--mut);font-size:12px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:900px){.two{grid-template-columns:1fr}}
.tw{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%}th,td{padding:6px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;white-space:nowrap}
td.wrap,th.wrap{white-space:normal;min-width:220px}th{font-size:12px;color:var(--mut);font-weight:600;cursor:pointer;user-select:none;position:sticky;top:0;background:var(--card)}
table.s th::after{content:' ⇅';opacity:.35;font-size:11px}table.s th:hover{color:var(--fg)}table.s th[data-asc='1']::after{content:' ▲';opacity:1;color:var(--acc)}table.s th[data-asc='0']::after{content:' ▼';opacity:1;color:var(--acc)}
tr:hover td{background:color-mix(in srgb,var(--acc) 5%,transparent)}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
a{color:var(--acc)}code{font:12px ui-monospace,Menlo,monospace}
.b{display:inline-block;padding:1px 7px;border-radius:10px;font-size:12px;font-weight:600;border:1px solid var(--line)}
.b.good{color:var(--good);background:var(--goodbg);border-color:transparent}.b.warn{color:var(--warn);background:var(--warnbg);border-color:transparent}
.b.bad{color:var(--bad);background:var(--badbg);border-color:transparent}
.pos{color:var(--good)}.neg{color:var(--bad)}
.bar{display:inline-block;height:8px;border-radius:4px;background:var(--line);width:120px;vertical-align:middle;overflow:hidden}
.bar i{display:block;height:100%;background:var(--bar)}
ul.r{margin:4px 0;padding-left:18px}ul.r li{margin:2px 0}li.good::marker{color:var(--good)}li.bad::marker{color:var(--bad)}li.warn::marker{color:var(--warn)}
.flt{margin:8px 0;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
input,select{background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:5px 8px;font:inherit}
pre{white-space:pre-wrap;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px;font:12px/1.5 ui-monospace,Menlo,monospace;overflow-x:auto}
details summary{cursor:pointer;color:var(--acc)}
.xl{display:inline-flex;gap:5px;vertical-align:middle;margin-left:2px;flex-wrap:wrap}.xl a{display:inline-flex;align-items:center;gap:3px;opacity:.75;text-decoration:none}.xl a:hover{opacity:1}.xl img{width:14px;height:14px;border-radius:3px;display:block}td .xl{display:flex;margin:4px 0 0;min-width:150px}.xlb{gap:10px}.xlb a{opacity:1}
.cand{text-align:left;cursor:pointer;font:inherit;color:inherit;width:100%}.cand:hover{border-color:var(--acc)}
dialog#ev{max-width:980px;width:calc(100% - 32px);max-height:88vh;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--fg);padding:0}
dialog#ev::backdrop{background:rgba(0,0,0,.45)}dialog#ev .bar2{position:sticky;top:0;display:flex;justify-content:flex-end;padding:8px;background:var(--bg)}
dialog#ev .body{padding:0 18px 18px}tr.clk{cursor:pointer}
.tip{color:var(--acc);cursor:help;font-weight:400;font-size:12px}
#tipbox{position:fixed;z-index:50;max-width:300px;background:var(--fg);color:var(--bg);padding:7px 10px;border-radius:6px;font:12px/1.4 system-ui,sans-serif;white-space:normal;pointer-events:none;display:none;box-shadow:0 4px 14px rgba(0,0,0,.25)}.empty{color:var(--mut);padding:14px}

dialog#gl{max-width:620px;width:calc(100% - 24px);max-height:85vh;border:1px solid var(--line);border-radius:14px;background:var(--card);color:var(--fg);padding:0;box-shadow:0 12px 40px rgba(0,0,0,.3)}
dialog#gl::backdrop{background:rgba(0,0,0,.45)}dialog#gl .bar2{position:sticky;top:0;display:flex;justify-content:space-between;align-items:center;padding:8px 12px;background:var(--card);border-bottom:1px solid var(--line)}
dialog#gl .bar2 button{background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:5px 10px;font:inherit;cursor:pointer}
dialog#gl .body{padding:6px 18px 18px;font-size:15px;line-height:1.55}dialog#gl h3{font-size:18px;margin:6px 0 6px}
.gl-cat{font-size:12px;color:var(--mut);margin-top:10px}.gl-short{font-weight:600}.gl-here{background:var(--bg);border-radius:8px;padding:8px 10px;margin:8px 0;font-size:14px}
.gl-ex{border-left:3px solid var(--acc);padding:4px 10px;margin:10px 0;font-size:14px}.gl-where,.gl-rel{margin:8px 0;font-size:14px}
.gl-chip{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:1px 9px;margin:2px 2px 2px 0;text-decoration:none;font-size:13px}
.tip{display:inline-block;min-width:18px;text-align:center}
.gl-top input{width:100%;max-width:560px;font-size:16px;padding:9px 12px;border-radius:10px}
.gl-cats{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0}.gl-cats a{border:1px solid var(--line);background:var(--card);border-radius:999px;padding:4px 11px;text-decoration:none;font-size:13px}
.gl-term{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 16px;margin:8px 0;scroll-margin-top:80px}
.gl-term h3{margin:4px 0}.gl-term p{margin:6px 0}.gl-term.hl{border-color:var(--acc);box-shadow:0 0 0 2px color-mix(in srgb,var(--acc) 25%,transparent)}
.gl-a{margin-left:6px;opacity:.3;text-decoration:none;font-weight:400}.gl-al{font-size:12px}
/* design pass 2026-10-31: calmer surfaces, clear hierarchy */
body{font:14.5px/1.5 Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;-webkit-font-smoothing:antialiased}
main{padding:20px 20px 48px}
h1{font-size:24px;font-weight:700;letter-spacing:-.02em;margin:6px 0 10px}
h2{font-size:18px;font-weight:650;letter-spacing:-.01em;margin:36px 0 4px;padding-top:4px}
h2 .tip,h3 .tip{font-size:13px}h3{font-size:14.5px;margin:18px 0 8px}
.lead{color:var(--mut);margin:0 0 12px;font-size:14px}
.card,.stat,.tw,.intro,pre{border-radius:12px;box-shadow:0 1px 2px rgba(16,24,40,.04)}
.card{padding:14px 16px}.stat{padding:12px 16px}.stat .v{font-size:24px;font-weight:650;letter-spacing:-.01em;font-variant-numeric:tabular-nums}
.stat .l{font-size:12.5px}.grid{gap:12px}
.intro{border-left:3px solid var(--acc);padding:8px 14px;font-size:13.5px;margin:0 0 16px}
.intro summary{color:var(--fg);list-style:none}.intro summary::-webkit-details-marker{display:none}
.intro summary::after{content:' ▾';color:var(--mut)}.intro[open] summary{margin-bottom:6px}
details>summary{padding:4px 0}main>details{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 16px}
.cand{transition:border-color .15s,box-shadow .15s}.cand:hover{box-shadow:0 4px 14px rgba(16,24,40,.08)}
.b{border-radius:999px}th{text-transform:none;letter-spacing:.01em}
.gt .l{font-weight:600;color:var(--fg);font-size:13px}.spark{display:block;margin-top:4px;overflow:visible}
.spark rect:hover{fill-opacity:1}.gtg{grid-template-columns:repeat(4,minmax(0,1fr))}@media(max-width:1000px){.gtg{grid-template-columns:repeat(2,minmax(0,1fr))}}
.spark-ax{display:flex;justify-content:space-between;font-size:11px}
@media(max-width:700px){h2{font-size:16px;margin-top:26px}main>details{padding:8px 12px}.gt .v{font-size:18px}.gt{padding:10px}.spark{height:40px}}
"""

JS = """
(()=>{const box=document.createElement('div');box.id='tipbox';document.body.appendChild(box);
 const show=el=>{box.textContent=el.dataset.tip;box.style.display='block';const r=el.getBoundingClientRect();
  box.style.left=Math.max(8,Math.min(innerWidth-box.offsetWidth-8,r.left-20))+'px';
  box.style.top=(r.bottom+6+box.offsetHeight>innerHeight?r.top-box.offsetHeight-6:r.bottom+6)+'px'},hide=()=>box.style.display='none';
 document.addEventListener('mouseover',e=>{const t=e.target.closest('.tip');t?show(t):hide()});
 document.addEventListener('focusin',e=>{const t=e.target.closest('.tip');if(t)show(t)});
 addEventListener('scroll',hide,true)})();
document.querySelectorAll('table.s').forEach(t=>{t.querySelectorAll('th').forEach(th=>th.onclick=e=>{if(e.target.closest('.tip'))return;
 const i=[...th.parentNode.cells].indexOf(th),b=t.tBodies[0],rows=[...b.rows],asc=th.dataset.asc==='0';t.querySelectorAll('th').forEach(x=>delete x.dataset.asc);th.dataset.asc=asc?'1':'0';
 const v=r=>{const c=r.cells[i];const s=c?(c.dataset.v??c.innerText):'';const n=parseFloat(s.replace(/[$,%+ ]/g,''));return isNaN(n)?s.toLowerCase():n};
 rows.sort((a,c)=>{const x=v(a),y=v(c);return (x>y?1:x<y?-1:0)*(asc?1:-1)});rows.forEach(r=>b.appendChild(r))})});
document.querySelectorAll('input[data-f]').forEach(inp=>inp.oninput=()=>{const q=inp.value.toLowerCase();
 document.querySelectorAll('#'+inp.dataset.f+' tbody tr').forEach(r=>r.style.display=r.innerText.toLowerCase().includes(q)?'':'none')});
"""


def esc(x):
    return html.escape("" if x is None else str(x))


NAV_CSS = """
header.top{position:sticky;top:0;z-index:30;display:flex;align-items:center;gap:14px;height:60px;padding:0 18px;
 background:color-mix(in srgb,var(--card) 90%,transparent);backdrop-filter:saturate(1.4) blur(8px);border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:10px;text-decoration:none;color:var(--fg);font-weight:750;font-size:17px;
 letter-spacing:-.02em;white-space:nowrap;min-width:214px}.brand svg{flex:none;display:block}
.srch{position:relative;flex:1;max-width:620px;margin:0}
.srch input{width:100%;padding:9px 38px 9px 36px;border-radius:10px;background:var(--bg);border:1px solid var(--line);font-size:14.5px}
.srch input:focus{outline:none;border-color:var(--acc);box-shadow:0 0 0 3px color-mix(in srgb,var(--acc) 18%,transparent);background:var(--card)}
.srch .si{position:absolute;left:11px;top:50%;transform:translateY(-50%);opacity:.55;font-size:14px;pointer-events:none}
.srch kbd{position:absolute;right:9px;top:50%;transform:translateY(-50%);font:11px ui-monospace,monospace;color:var(--mut);
 border:1px solid var(--line);border-radius:4px;padding:0 5px}
.sdrop{position:absolute;left:0;right:0;top:calc(100% + 6px);background:var(--card);border:1px solid var(--line);border-radius:12px;
 box-shadow:0 14px 36px rgba(16,24,40,.2);max-height:72vh;overflow:auto;padding:6px;z-index:40}
.sdrop .sh{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut);padding:8px 10px 4px}
.sdrop a{display:flex;gap:10px;align-items:center;padding:7px 10px;border-radius:8px;color:var(--fg);text-decoration:none;line-height:1.3}
.sdrop a>span:last-child{min-width:0}.sdrop a .mut{font-size:12px}.sdrop .ic{width:22px;text-align:center;flex:none;font-size:16px}
.sdrop a.sel,.sdrop a:hover{background:color-mix(in srgb,var(--acc) 10%,var(--card))}.sdrop a.all{color:var(--acc);font-weight:600}
.cta{display:inline-flex;align-items:center;gap:7px;padding:8px 15px;border-radius:999px;margin-left:auto;
 background:linear-gradient(135deg,#f59f00,#f76707);color:#fff!important;font-weight:650;text-decoration:none;white-space:nowrap;
 box-shadow:0 2px 10px rgba(247,103,7,.28)}.cta:hover{filter:brightness(1.07)}
.menu-btn{display:none;align-items:center;justify-content:center;width:40px;height:40px;border-radius:10px;border:1px solid var(--line);
 background:var(--card);color:var(--fg);font-size:19px;cursor:pointer;flex:none}
.shell{display:flex;align-items:flex-start}.shell>main{flex:1;min-width:0}
aside.side{position:sticky;top:60px;height:calc(100vh - 60px);overflow-y:auto;width:240px;flex:none;padding:6px 10px 28px;
 border-right:1px solid var(--line);background:var(--card);scrollbar-width:thin}
.side h4{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--mut);margin:18px 10px 5px;font-weight:650}
.side a{display:flex;align-items:center;gap:10px;padding:7px 10px;border-radius:9px;color:var(--fg);text-decoration:none;font-size:14px;line-height:1.25}
.side .mi{width:20px;text-align:center;flex:none}.side a:hover{background:color-mix(in srgb,var(--acc) 7%,transparent)}
.side a.on{background:color-mix(in srgb,var(--acc) 14%,transparent);color:var(--acc);font-weight:650}
.side .sec-n{background:color-mix(in srgb,#f59f00 9%,transparent);border-radius:12px;padding:2px 0 6px;margin-top:10px}
.side .sec-n h4{color:#d9480f;margin-top:10px}
.side .out{color:var(--mut);font-size:13px;margin-top:20px}.side-head{display:none}
.scrim{display:none}.bbar{display:none}
.mapgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px;margin:8px 0 6px}
a.mapcard{display:grid;grid-template-columns:auto 1fr;align-content:start;column-gap:12px;row-gap:2px;align-items:start;background:var(--card);
 border:1px solid var(--line);border-radius:14px;padding:14px 16px;text-decoration:none;color:var(--fg);transition:border-color .15s,box-shadow .15s,transform .15s}
a.mapcard:hover{border-color:var(--acc);box-shadow:0 6px 18px rgba(16,24,40,.08);transform:translateY(-1px)}
a.mapcard .mi{grid-row:span 2;font-size:24px;line-height:1.1}a.mapcard b{font-size:15px}a.mapcard .mut{font-size:13px;line-height:1.4}
details.homemap{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin:0 0 16px}details.homemap>summary{list-style:none;color:var(--fg)}details.homemap>summary::-webkit-details-marker{display:none}details.homemap>summary::after{content:' ▾';color:var(--mut)}.mapgrid.hm{grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:8px;margin-top:10px}.mapgrid.hm a.mapcard{padding:9px 12px}@media(max-width:700px){.mapgrid.hm{grid-template-columns:1fr 1fr}.mapgrid.hm a.mapcard{grid-template-columns:1fr}.mapgrid.hm a.mapcard .mi{grid-row:auto;font-size:20px}.mapgrid.hm a.mapcard b{font-size:14px}.mapgrid.hm a.mapcard .mut{font-size:12px}}a.mapcard.hot{border-color:#f59f00;background:linear-gradient(135deg,color-mix(in srgb,#f59f00 10%,var(--card)),var(--card))}
.quick{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:4px 0 18px}
.quick a{display:flex;align-items:center;gap:10px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:11px 13px;
 text-decoration:none;color:var(--fg);font-weight:600;font-size:14px}.quick a:hover{border-color:var(--acc)}
.quick a span{font-size:20px}.quick a.hot{border-color:#f59f00;background:color-mix(in srgb,#f59f00 9%,var(--card))}
.sform{display:flex;gap:8px;max-width:640px}.sform input{flex:1;padding:9px 12px;font-size:15px}
button,.btn{font:inherit}.sform button{padding:8px 16px;border-radius:8px;border:0;background:var(--acc);color:#fff;font-weight:600;cursor:pointer}
ul.sres{list-style:none;padding:0;margin:0;background:var(--card);border:1px solid var(--line);border-radius:12px}
ul.sres li{padding:10px 14px;border-bottom:1px solid var(--line)}ul.sres li:last-child{border-bottom:0}
@media(max-width:1000px){
 .menu-btn{display:inline-flex}.brand{min-width:0}
 aside.side{position:fixed;top:0;left:0;bottom:0;height:100%;z-index:60;width:min(300px,86vw);transform:translateX(-102%);
  transition:transform .2s ease;box-shadow:0 0 40px rgba(0,0,0,.25);padding-top:0}
 body.nav-open aside.side{transform:none}body.nav-open{overflow:hidden}
 .side-head{display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;background:var(--card);
  padding:12px 8px;border-bottom:1px solid var(--line);margin:0 -10px 4px;padding-left:18px}
 .side-head button{border:0;background:none;font-size:22px;color:var(--mut);cursor:pointer;padding:4px 10px}
 .scrim{position:fixed;inset:0;background:rgba(0,0,0,.42);z-index:55}body.nav-open .scrim{display:block}
 .bbar{display:flex;position:fixed;bottom:0;left:0;right:0;z-index:30;background:color-mix(in srgb,var(--card) 96%,transparent);
  backdrop-filter:blur(8px);border-top:1px solid var(--line);padding:3px 2px calc(3px + env(safe-area-inset-bottom))}
 .bbar a,.bbar button{flex:1;display:flex;flex-direction:column;align-items:center;gap:1px;font-size:11px;color:var(--mut);
  text-decoration:none;background:none;border:0;padding:5px 0;cursor:pointer;font-family:inherit}
 .bbar .bi{font-size:20px;line-height:1.1}.bbar .on{color:var(--acc);font-weight:650}
 .bbar a.n .bi{background:linear-gradient(135deg,#f59f00,#f76707);border-radius:12px;padding:2px 9px;margin-top:-1px}
 .shell>main{padding-bottom:86px}}
@media(max-width:700px){header.top{gap:8px;padding:0 10px;height:56px}header.top .brand span{display:none}.srch kbd{display:none}
 .cta{display:none}.srch input{font-size:16px;padding:8px 10px 8px 32px}a.mapcard{padding:12px 14px}}
"""

NAV_JS = """
(()=>{const P=__PAGES__;
document.querySelectorAll('[data-nav]').forEach(b=>b.addEventListener('click',()=>document.body.classList.toggle('nav-open')));
const inp=document.getElementById('q'),dd=document.getElementById('sdrop');if(!inp)return;
const f=s=>(s||'').toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g,'');
const e=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const sh=a=>a&&a.length>10?a.slice(0,4)+'…'+a.slice(-4):(a||'');
let t=null,sel=-1,last='';
const it=(href,ic,main,sub)=>`<a href="${href}"><span class=ic>${ic}</span><span><b>${main}</b>${sub?'<br><span class=mut>'+sub+'</span>':''}</span></a>`;
function render(q,j){const w=f(q).split(/\\s+/).filter(Boolean);let h='';
 const pg=P.filter(p=>w.every(x=>f(p.name+' '+p.desc+' '+p.kw+' '+p.sec).includes(x))).slice(0,5);
 if(pg.length)h+='<div class=sh>Stranice</div>'+pg.map(p=>it(p.href,p.icon,e(p.name),e(p.desc))).join('');
 if(j){if(j.tokens.length)h+='<div class=sh>Tokeni</div>'+j.tokens.slice(0,6).map(x=>it('/token/'+encodeURIComponent(x.mint),'🪙',
   e(x.sym||sh(x.mint))+(x.name&&x.name!==x.sym?' <span class=mut>'+e(x.name)+'</span>':''),sh(x.mint)+' · '+e(x.src.join(', ')))).join('');
  if(j.kols.length)h+='<div class=sh>KOL-ovi i kanali</div>'+j.kols.slice(0,5).map(x=>it('/kol/'+encodeURIComponent(x.handle),'📣',e(x.label),e(x.name||''))).join('');
  if(j.wallets.length)h+='<div class=sh>Novčanici</div>'+j.wallets.slice(0,5).map(x=>it('/wallet/'+encodeURIComponent(x.wallet),'👛',e(x.label||sh(x.wallet)),x.label?sh(x.wallet):'')).join('');
  if(j.addr&&!j.tokens.length)h+='<div class=sh>Adresa</div>'+it('/token/'+encodeURIComponent(q),'🪙','Otvori kao token','')+it('/wallet/'+encodeURIComponent(q),'👛','Otvori kao novčanik','');
  if(!h)h='<div class=sh>Ništa nije pronađeno</div>';}
 else if(q.length>=2)h+='<div class=sh>Tražim tokene, KOL-ove i novčanike…</div>';
 h+=`<a class=all href="/trazi?q=${encodeURIComponent(q)}">Svi rezultati za „${e(q)}” →</a>`;dd.innerHTML=h;dd.hidden=false;sel=-1}
inp.addEventListener('input',()=>{const q=inp.value.trim();last=q;clearTimeout(t);if(!q){dd.hidden=true;return}render(q,null);if(q.length<2)return;
 t=setTimeout(async()=>{try{const r=await fetch('/api/trazi?q='+encodeURIComponent(q));const j=await r.json();if(last===q)render(q,j)}catch(err){}},250)});
inp.addEventListener('keydown',ev=>{const a=[...dd.querySelectorAll('a')];
 if(ev.key==='ArrowDown'||ev.key==='ArrowUp'){ev.preventDefault();if(!a.length||dd.hidden)return;sel=(sel+(ev.key==='ArrowDown'?1:-1)+a.length)%a.length;
  a.forEach((x,i)=>x.classList.toggle('sel',i===sel));a[sel].scrollIntoView({block:'nearest'})}
 else if(ev.key==='Enter'&&sel>=0&&a[sel]&&!dd.hidden){ev.preventDefault();location=a[sel].href}
 else if(ev.key==='Escape'){dd.hidden=true;inp.blur()}});
inp.addEventListener('focus',()=>{if(inp.value.trim()&&dd.innerHTML)dd.hidden=false});
document.addEventListener('click',ev=>{if(!ev.target.closest('.srch'))dd.hidden=true});
document.addEventListener('keydown',ev=>{if(ev.key==='/'&&!/INPUT|TEXTAREA|SELECT/.test((document.activeElement||{}).tagName||'')){ev.preventDefault();inp.focus()}});
})();
"""


def _pages_json():
    import json
    return json.dumps([{"href": p["href"], "icon": p["icon"], "name": p["name"], "desc": p["desc"], "kw": p["kw"], "sec": sec}
                       for sec, items in SECTIONS for p in items], ensure_ascii=False).replace("</", "<\\/")


def side_menu(cur):
    svg, name = logo(26)
    b = [f'<aside class=side id=side aria-label="Izbornik"><div class=side-head><a class=brand href="/">{svg}<span>{esc(name)}</span></a>'
         '<button data-nav aria-label="Zatvori izbornik">✕</button></div>']
    for sec, items in SECTIONS:
        b.append(f'<div class="{"sec-n" if sec == "Natjecanje" else ""}"><h4>{esc(sec)}</h4>' + "".join(
            f'<a href="{p["href"]}" class="{"on" if p["href"] == cur else ""}"><span class=mi>{p["icon"]}</span>{esc(p["name"])}</a>'
            for p in items) + "</div>")
    b.append('<a class=out href="/odjava"><span class=mi>↩</span>Odjava</a></aside>')
    return "".join(b)


def page(title, body, path="/"):
    from ui.charts import CSS as CH_CSS, JS as CH_JS
    cur = nav_item(path)
    svg, name = logo(30)
    header = (f'<header class=top><button class=menu-btn data-nav aria-label="Otvori izbornik">☰</button>'
              f'<a class=brand href="/" title="Na početnu">{svg}<span>{esc(name)}</span></a>'
              '<form class=srch action="/trazi" role=search autocomplete=off><span class=si>🔍</span>'
              '<input id=q name=q placeholder="Traži token, adresu, KOL ili stranicu…" aria-label="Traži" enterkeyhint=search>'
              '<kbd>/</kbd><div class=sdrop id=sdrop hidden></div></form>'
              f'<a class=cta href="/natjecanje">🏆 <span>Natjecanje</span></a></header>')
    bbar = ("<nav class=bbar aria-label='Brzi izbornik'>" + "".join(
        f'<a href="{h}" class="{"on" if h == cur else ""}{" n" if h == "/natjecanje" else ""}"><span class=bi>{i}</span>{t}</a>'
        for h, i, t in BOTTOM) + "<button data-nav><span class=bi>☰</span>Izbornik</button></nav>")
    return (f"<!doctype html><html lang=hr><head><meta charset=utf-8><meta name=viewport content='width=device-width,"
            f"initial-scale=1'><title>{esc(title)} · {esc(name)}</title><link rel=icon href=\"data:image/svg+xml,"
            f"{quote(logo(32)[0])}\"><style>{CSS}{COLS_CSS}{NAV_CSS}{CH_CSS}</style></head><body>"
            f"{header}<div class=shell>{side_menu(cur)}<div class=scrim data-nav></div><main>{annotate(with_intro(_h1_info(body, path), path))}</main></div>"
            f"{bbar}<script>{JS}{GL_JS}{CH_JS}{COLS_JS}{NAV_JS.replace('__PAGES__', _pages_json())}</script></body></html>")


def map_page(qs=None):
    """/mapa: every page as a card with what it is for, grouped like the menu."""
    b = ["<h1>Gdje je što</h1><p class=lead>Sve stranice alata na jednom mjestu. Isti popis je u izborniku lijevo "
         "(na mobitelu gumb ☰ Izbornik dolje desno), a tražilica na vrhu nalazi i stranice, tokene, KOL-ove i novčanike.</p>",
         "<div class=card><b>Novi ovdje?</b> Počni s <a href=/>Pregledom</a> (što je bot našao danas), zatim "
         "<a href=/natjecanje>Natjecanjem</a> (kupi tokene na svom demo računu, bez pravog novca) i "
         "<a href=/dugorocno>Dugoročnim</a> tokenima (sigurniji sloj).</div>"]
    for sec, items in SECTIONS:
        b.append(f"<h2>{esc(sec)}</h2><div class=mapgrid>" + "".join(
            f'<a class="mapcard{" hot" if p["href"] == "/natjecanje" else ""}" href="{p["href"]}"><span class=mi>{p["icon"]}</span>'
            f'<b>{esc(p["name"])}</b><span class=mut>{esc(p["desc"])}</span></a>' for p in items) + "</div>")
    return "Gdje je što", "".join(b)


HOME_MAP = ["/natjecanje", "/copy-trading", "#istaknuti", "/dugorocno", "/kol", "/wallets", "/paper", "/events",
            "/whatsapp", "/pojmovnik", "/mapa"]
_EXTRA = {"#istaknuti": {"href": "#istaknuti", "icon": "⭐", "name": "Istaknuti tokeni",
                         "desc": "Najbolji tokeni upravo sada, odmah ispod na ovoj stranici."},
          "/mapa": {"href": "/mapa", "icon": "🧭", "name": "Sve stranice", "desc": "Popis svih stranica s kratkim opisom."}}


def quick_links():
    """"Gdje je što" at the top of Pregled: the most important places, one click each, with one line on what's
    there. Collapsible; the browser remembers if the user closed it."""
    pages = {p["href"]: p for _, items in SECTIONS for p in items}
    cards = []
    for h in HOME_MAP:
        p = _EXTRA.get(h) if h in _EXTRA else pages.get(h)
        if p:
            cards.append(f'<a class="mapcard{" hot" if h == "/natjecanje" else ""}" href="{p["href"]}"><span class=mi>'
                         f'{p["icon"]}</span><b>{esc(p["name"])}</b><span class=mut>{esc(p["desc"])}</span></a>')
    return ("<details class=homemap id=homemap open><summary><b>🧭 Gdje je što</b> <span class=mut>· najvažnije "
            "stranice jednim klikom; ⓘ uz svaki pojam objašnjava što znači</span></summary>"
            f"<div class='mapgrid hm'>{''.join(cards)}</div></details>"
            "<script>(()=>{const d=document.getElementById('homemap');try{if(localStorage.getItem('homemap')==='0')d.open=false}catch(e){}"
            "d.addEventListener('toggle',()=>{try{localStorage.setItem('homemap',d.open?'1':'0')}catch(e){}})})();</script>")


def tdesc(text):
    """Short "what this table covers" line shown above a table."""
    return f'<p class=tdesc>{text}</p>'


def tip(text, k=None, label=None):
    """Small ⓘ: hover shows `text`; click/tap opens the glossary pop-up (term `k` from ui/glossary.py, if any)."""
    extra = (f' data-gk="{esc(k)}"' if k else "") + (f' data-gl="{esc(label)}"' if label else "")
    return f'<span class=tip tabindex=0 role=button aria-label="Objašnjenje" data-tip="{esc(text)}"{extra}>ⓘ</span>'


def info(label, k=None):
    """ⓘ for a glossary term found by its visible label (or key `k`); "" when the glossary doesn't know it."""
    from ui import glossary
    k = k or glossary.lookup(label)
    t = glossary.get(k) if k else None
    return tip(t["short"], k, label) if t else ""


def th(label, cls=""):
    """Column header with its explanation from ui/help.py and the matching glossary term, if there is one."""
    from ui.help import HELP
    from ui import glossary
    h, k = HELP.get(label), glossary.lookup(label)
    if not h and k:
        h = glossary.get(k)["short"]
    return f'<th class="{cls}">{label}{" " + tip(h, k, label) if h else ""}</th>'


_ANN = re.compile(r'(<h[23](?:\s[^>]*)?>|<div class=l>)([^<>]{2,70})(?=</h[23]>|</div>)')


def annotate(body):
    """Add a glossary ⓘ to every section heading and stat-tile label whose text is a known term, so a new page
    is explained without touching its code."""
    from ui import glossary
    idx = glossary.index()

    def sub(m):
        k = idx.get(glossary.norm(m.group(2)))
        return m.group(0) + (" " + info(m.group(2), k) if k else "")
    return _ANN.sub(sub, body)


def page_info(path):
    """ⓘ next to the page title explaining the whole page."""
    from ui import glossary
    k = glossary.page_key(path)
    return info("", k) if k else ""


GL_JS = """
(()=>{const d=document.createElement('dialog');d.id='gl';d.innerHTML='<div class=bar2><a href=/pojmovnik class=glall>📖 Pojmovnik</a><button type=button>Zatvori ✕</button></div><div class=body></div>';
document.body.appendChild(d);const body=d.querySelector('.body');d.querySelector('button').onclick=()=>d.close();
d.addEventListener('click',e=>{if(e.target===d)d.close()});
const open=async(k,l,t)=>{const tb=document.getElementById('tipbox');if(tb)tb.style.display='none';
 body.innerHTML='<p class=mut>Učitavam objašnjenje…</p>';if(!d.open)d.showModal();d.scrollTop=0;
 try{const r=await fetch('/api/pojam?k='+encodeURIComponent(k||'')+'&l='+encodeURIComponent(l||'')+'&t='+encodeURIComponent(t||''));
  body.innerHTML=await r.text()}catch(e){const p=document.createElement('p');p.textContent=t||'Greška pri učitavanju.';body.replaceChildren(p)}};
document.addEventListener('click',e=>{const t=e.target.closest('.tip,[data-gk].gl-chip');if(!t)return;
 if(t.classList.contains('gl-chip')&&!d.contains(t))return;
 e.preventDefault();e.stopPropagation();open(t.dataset.gk,t.dataset.gl,t.dataset.tip)},true);
document.addEventListener('keydown',e=>{if((e.key==='Enter'||e.key===' ')&&e.target.classList&&e.target.classList.contains('tip')){e.preventDefault();e.target.click()}});
})();
"""


# Rows a table sends by default. A 20k-row table is megabytes of HTML that a phone can't download, parse and lay
# out in time; ?sve=1 on the page (link under the table) sends every row. Set per request by run_ui.
MAX_ROWS = int(os.environ.get("UI_MAX_ROWS", "200"))
SHOW_ALL = contextvars.ContextVar("show_all", default=False)


def table(headers, rows, tid=None, empty="Nema podataka.", mints=None, limit=None):
    """headers: [(label, cls)] or labels; rows: [[cell]] where a cell is html or (html, sort_value, cls).
    mints: one token address per row; the row then opens the evidence pop-up (needs modal() on the page).
    Only the first `limit` rows (default MAX_ROWS) are sent unless the page was opened with ?sve=1; rows are
    expected in their most useful order already, sorting and filtering then work on the rows shown."""
    if not rows:
        return f'<div class="tw"><div class="empty">{empty}</div></div>'
    limit = MAX_ROWS if limit is None else limit
    more = ""
    if limit and not SHOW_ALL.get() and len(rows) > limit:
        more = (f'<p class="mut more">Prikazano prvih {limit} od {len(rows)} redova (filtar i sortiranje rade na '
                f'prikazanima). <a href="?sve=1">Prikaži sve</a> (sporije na mobitelu)</p>')
        rows, mints = rows[:limit], (mints[:limit] if mints else mints)
    hs = [th(*(h if isinstance(h, tuple) else (h, ""))) for h in headers]
    body = []
    for r in rows:
        tds = []
        for c in r:
            if isinstance(c, tuple):
                h, v, cls = (c + ("",))[:3]
                tds.append(f'<td class="{cls}" data-v="{esc(v)}">{h}</td>')
            else:
                tds.append(f"<td>{c}</td>")
        m = mints[len(body)] if mints else None
        body.append((f'<tr class=clk data-mint="{esc(m)}">' if m else "<tr>") + "".join(tds) + "</tr>")
    idattr = f' id="{tid}"' if tid else ""
    return f'<div class="tw"><table class="s"{idattr}><thead><tr>{"".join(hs)}</tr></thead><tbody>{"".join(body)}</tbody></table></div>{more}'


def filt(tid, placeholder="Filtriraj…"):
    return f'<input data-f="{tid}" placeholder="{placeholder}" size=30>'


def num(x, fmt="{:,.0f}", cls="n"):
    if x is None:
        return ("–", -1e18, cls)
    return (esc(fmt.format(x)), x, cls)


def signed(x, fmt="{:+.2f}"):
    if x is None:
        return ("–", -1e18, "n")
    c = "pos" if x > 0 else "neg" if x < 0 else ""
    return (f'<span class="{c}">{esc(fmt.format(x))}</span>', x, "n")


def usd(x):
    if x is None:
        return ("–", -1, "n")
    s = f"${x / 1e9:,.2f}B" if x >= 1e9 else f"${x / 1e6:,.2f}M" if x >= 1e6 else f"${x / 1e3:,.1f}k" if x >= 1e3 else f"${x:,.0f}"
    return (s, x, "n")


def price(x):
    """Token price in dollars, readable for tiny memecoin prices: $1.23, $0.0042, $0.000001625."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return ("–", -1, "n")
    s = f"${x:,.2f}" if x >= 1 else f"${x:.4g}"
    if "e" in s:  # 1.62e-07 -> 0.000000162
        s = "$" + f"{x:.12f}".rstrip("0")
    return (s, x, "n")


def mins(x):
    """Duration given in minutes, in words: 34 min, 25 h, 5 d."""
    if x is None:
        return ("–", -1e18, "n")
    s = f"{x:.0f} min" if x < 90 else f"{x / 60:.0f} h" if x < 48 * 60 else f"{x / 1440:.0f} d"
    return (s, x, "n")


def bar(v, mx=100, w=120):
    pct = 0 if not mx else max(0, min(100, 100 * (v or 0) / mx))
    return f'<span class="bar" style="width:{w}px"><i style="width:{pct:.0f}%"></i></span>'


def scorecell(v, mx=100):
    if v is None:
        return ("–", -1, "n")
    return (f"{bar(v, mx, 60)} {v:g}", v, "n")


def badge(text, kind=""):
    return f'<span class="b {kind}">{esc(text)}</span>'


VERDICT = {"PROLAZI": "good", "OPREZ": "warn", "VISOK RIZIK": "bad", "ODBAČEN": "bad"}


def verdict(v):
    return badge(v, VERDICT.get(v, "")) if v else "–"


def rugcell(r):
    """Rug column for a token row: collapsed after the fact wins over the rug filter's verdict from before."""
    col = r.get("collapse")
    if col:
        lab = badge("💀 RUGAN −{:.0%}".format(col["drop"]), "bad")
        return f'<span title="{esc(col["text"])}">{lab}</span>', "ZZ", ""
    return verdict(r["rug"]["verdict"]) if r.get("rug") else "<span class=mut>–</span>"


def klasab(k):
    from tiers.classify import KLASA_HR
    return badge(KLASA_HR.get(k, k), {"moonshot": "warn", "event": "good", "stabilni": ""}.get(k, "bad")) if k else ""


def razinab(r):
    return badge(f"T{r}", "good" if (r or 0) >= 2 else "") if r is not None else ""


def tierb(t):
    return badge(t, {"A": "good", "B": "warn", "D": "bad"}.get(t, "")) if t else badge("neocijenjen")


def short(a, n=4):
    return f"{a[:n]}…{a[-n:]}" if a and len(a) > 2 * n + 1 else (a or "")


def wlink(w):
    return f'<a href="/wallet/{quote(w)}"><code>{esc(short(w))}</code></a>'


# Small external links shown next to every token: (name shown on hover, site for the icon, url builder).
EXT_SITES = [
    ("DexScreener", "dexscreener.com", lambda m: f"https://dexscreener.com/solana/{m}"),
    ("pump.fun", "pump.fun", lambda m: f"https://pump.fun/coin/{m}"),
    ("GMGN", "gmgn.ai", lambda m: f"https://gmgn.ai/sol/token/{m}"),
    ("Birdeye", "birdeye.so", lambda m: f"https://birdeye.so/token/{m}?chain=solana"),
    ("Solscan", "solscan.io", lambda m: f"https://solscan.io/token/{m}"),
    ("RugCheck", "rugcheck.xyz", lambda m: f"https://rugcheck.xyz/tokens/{m}"),
    ("Jupiter (kupi)", "jup.ag", lambda m: f"https://jup.ag/swap/SOL-{m}"),
    ("X (objave o tokenu)", "x.com", lambda m: f"https://x.com/search?q={m}&f=live"),
]


def ext_icons(mint, url=None, labels=False):
    """Row of small site icons, each opens the token on that site in a new tab. pump.fun only for pump.fun tokens.
    url: the exact DexScreener pair page when we have it. labels=True also writes the site name (token page)."""
    if not mint:
        return ""
    m = quote(mint)
    out = []
    for name, dom, mk in EXT_SITES:
        if dom == "pump.fun" and not mint.endswith("pump"):
            continue
        href = url if (url and dom == "dexscreener.com") else mk(m)
        out.append(f'<a href="{esc(href)}" target=_blank rel=noopener title="Otvori na: {esc(name)}">'
                   f'<img src="https://www.google.com/s2/favicons?domain={dom}&sz=32" alt="" loading=lazy width=14 height=14>'
                   + (f"<span>{esc(name)}</span>" if labels else "") + "</a>")
    return f'<span class="xl{" xlb" if labels else ""}">' + "".join(out) + "</span>"


def tlink(mint, sym=None):
    """Token name opens our own page for the token; the small icons next to it open it on outside sites."""
    label = esc(sym) if sym else f"<code>{esc(short(mint))}</code>"
    return f'<a href="/token/{quote(mint)}" title="Otvori stranicu tokena">{label}</a> ' + copy_icon(mint) + ext_icons(mint)


_COPY_JS = ("var m=this.dataset.m,b=this;(navigator.clipboard?navigator.clipboard.writeText(m):Promise.reject())"
            ".then(function(){b.textContent='✅'},function(){prompt('Kopiraj adresu:',m)});return false")


def copy_icon(mint):
    """Tiny one-tap "copy address" next to every token name in every table (Nicholas 1.11.: react fast)."""
    if not mint:
        return ""
    return (f'<a href="#" role=button class=cpy data-m="{esc(mint)}" title="Kopiraj adresu" '
            f'style="text-decoration:none;font-size:12px" onclick="{_COPY_JS}">📋</a> ')


def ext_wallet(w):
    return (f'<a href="https://gmgn.ai/sol/address/{quote(w)}" target=_blank>GMGN</a> · '
            f'<a href="https://solscan.io/account/{quote(w)}" target=_blank>Solscan</a>')


def ext_token(mint, url=None):
    return ext_icons(mint, url, labels=True)


def ts(t, fmt="%Y-%m-%d %H:%M"):
    if not t:
        return ("–", 0, "")
    return (dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime(fmt), t, "")


def ago(t):
    if not t:
        return ("–", 0, "")
    d = time.time() - t
    s = f"{d / 60:.0f} min" if d < 3600 else f"{d / 3600:.1f} h" if d < 86400 else f"{d / 86400:.1f} d"
    return (f"prije {s}", t, "")


def breakdown(parts, total_label="Zbroj", stored=None, mult=None, mult_label=None):
    """Score parts as a table with bars."""
    rows = [[esc(n) + (" " + info(n) if info(n) else ""), (f"{p:+.1f}" if p < 0 else f"{p:.1f}", p, "n"), (f"/ {m}", m, "n mut"),
             bar(p, m) if m else "", f'<span class="mut">{esc(x)}</span>'] for n, p, m, x in parts]
    raw = sum(p for _, p, _, _ in parts)
    foot = f"<b>{total_label}: {raw:.1f}</b>"
    if mult is not None:
        foot += f" × {mult:.2f} {esc(mult_label or '')} = <b>{raw * mult:.1f}</b>"
    if stored is not None:
        foot += f' <span class="mut">(spremljeno u bazi: {esc(stored)})</span>'
    return table(["Dio", ("Bodovi", "n"), ("Max", "n"), "", ("Objašnjenje", "wrap")], rows) + f'<p>{foot}</p>'


MODAL_JS = """
const dlg=document.getElementById('ev');
document.querySelectorAll('[data-mint]').forEach(b=>b.addEventListener('click',async e=>{if(e.target.closest('a,.tip'))return;
 dlg.querySelector('.body').innerHTML='<p class=mut>Učitavam analizu…</p>';dlg.showModal();
 try{const r=await fetch('/api/evidence/'+encodeURIComponent(b.dataset.mint));dlg.querySelector('.body').innerHTML=await r.text()}
 catch(err){dlg.querySelector('.body').innerHTML='<p>Greška pri učitavanju.</p>'}}));
dlg.addEventListener('click',e=>{if(e.target===dlg)dlg.close()});
"""


def modal():
    """The evidence pop-up: any element with data-mint opens /api/evidence/<mint> in it."""
    return ("<dialog id=ev><div class=bar2><button onclick=\"this.closest('dialog').close()\">Zatvori ✕</button></div>"
            f"<div class=body></div></dialog><script>{MODAL_JS}</script>")


def jsonblock(o):
    """Raw data dumps are not for the trader: kept as a no-op so old call sites stay valid."""
    return ""
