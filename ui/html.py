"""Small HTML helpers: layout, tables, badges, bars. No templates, no JS framework."""
import contextvars
import datetime as dt
import html
import os
import re
import time
from urllib.parse import quote
from ui.urls import home_link as _home_link
from ui.cols import CSS as COLS_CSS, JS as COLS_JS
from ui import favicon as _fav  # noqa: E402

# Menu: a few plain groups, every page with an icon and a one-line description. The same list drives the side menu
# (laptop), the drawer + bottom bar (phone), the "Gdje je što" page and the page part of the search box.
def _p(href, icon, name, desc, kw=""):
    return {"href": href, "icon": icon, "name": name, "desc": desc, "kw": kw}


SECTIONS = [
    # the three things the app is about: the only items at the top of the menu and in the phone bar
    ("Glavno", [
        _p("/pregled", "🏠", "Pregled", "Najprofitabilnija strategija, koliko podataka imamo, rast u tjedan dana i brzi linkovi.",
           "overview home početna pregled start nadzorna ploča dashboard sažetak rast strategija"),
        _p("/tokens", "🪙", "Tokeni", "Prijedlozi tokena: novi, jaki i dugoročni, poredani po Šansi za skok.",
           "radar hype novi zadnji sken kandidati lista coin prijedlozi"),
        _p("/kol", "📣", "Influenceri", "Koji KOL-ovi stvarno pogađaju i što su upravo zvali.",
           "influenceri pozivi twitter x ljestvica kol"),
        _p("/wallets", "👛", "Novčanici", "Tko je upravo kupio ili prodao i koga se isplati kopirati.",
           "walleti wallet smart money copy praćenje"),
    ]),
    ("Tokeni", [
        _p("/dugorocno", "🌱", "Dugoročni", "Sigurniji stariji tokeni koji se oporavljaju i rastu.",
           "dugorocno long term preživjeli veliki holderi burze"),
        _p("/radar", "📡", "Zadnji sken", "Što je skener našao u zadnjem prolazu.", "radar hype novi zadnji sken"),
        _p("/events", "📅", "Eventi", "Kalendar događaja, njihovi tokeni i kreću li prije događaja.",
           "kalendar događaji prije eventa watch praćenje"),
    ]),
    ("Influenceri i novčanici", [
        _p("/izvori", "💬", "Telegram i KOL novčanici", "Telegram kanali i novčanici KOL-ova.",
           "telegram kanali konvergencija kol novčanici"),
        _p("/korelacije", "🕸", "Korelacije", "Novčanici i KOL-ovi koji rade zajedno.", "grupe klasteri veze"),
        _p("/kol-test", "🧪", "KOL test", "Isplati li se ući odmah na KOL poziv.", "test"),
    ]),
    ("Bot (demo)", [
        _p("/paper", "🤖", "Demo trading", "Bi li bot zaradio, bez pravog novca.", "paper trejd"),
        _p("/strategije", "🏁", "Usporedba strategija", "5 demo računa po $1000.",
           "strategije usporedba budžet račun novčanici kol mix kontrola nasumično"),
        _p("/izlazi", "🚪", "Izlazi", "Kada bot prodaje i koliko to vrijedi.", "exit prodaja stop"),
        _p("/izvjestaj", "📰", "Jutarnji izvještaj", "Dnevni sažetak, gotov prije 8 h.", "email mail report sažetak"),
    ]),
    ("Pomoć", [
        _p("/pojmovnik", "📖", "Pojmovnik", "Što znači svaki pojam i broj.",
           "objašnjenje pojmovi rječnik značenje help pomoć info"),
        _p("/mapa", "🧭", "Sve stranice", "Sve stranice na jednom mjestu.", "izbornik mapa pomoć help gdje je što"),
        _p("/novo", "✨", "Što je novo", "Sve što je dodano u aplikaciju, po datumima.",
           "novosti novo promjene dnevnik log povijest update changelog dodano"),
    ]),
    ("Bonus", [
        _p("/natjecanje", "🏆", "Natjecanje", "Demo račun: kupi tokene iz prijedloga i natječi se s ostalima.",
           "liga ljestvica igra igrači demo račun kupi dca automatska kupnja prosjek"),
        _p("/copy-trading", "🔁", "Copy trading", "Alat ulazi i izlazi umjesto tebe, prema influenceru ili novčaniku.",
           "kopiraj prati influencer kol wallet novčanik copy trade"),
        _p("/nas-token", "🪙", "Naš token", "Naš vlastiti Solana meme token.",
           "token generator trezor vault sef lansiraj pump.fun meme coin marketing suradnja strategija promocija"),
        _p("/whatsapp", "📲", "Za WhatsApp", "Slika i poruka za WhatsApp grupu.", "whatsapp grupa podijeli pošalji share novosti"),
        _p("/prijedlozi", "💡", "Ideje za alat", "Predloži što bi alat trebao raditi bolje.", "ideje feedback"),
    ]),
    ("Autopilot", [
        _p("/pravi-trade", "💰", "Autopilot", "Bot trguje pravim novcem iz tvog walleta, po onima koje odabereš.",
           "pravi trade pravi novac live trading wallet phantom jupiter prekidač limit kupnja prodaja autopilot usdc"),
    ]),
    ("Sustav", [
        _p("/learn", "🧠", "Učenje", "Što bot uči iz ishoda i kako mijenja ocjene.", "learn težine"),
        _p("/criteria", "📏", "Pravila", "Svi pragovi i težine po kojima bot ocjenjuje.", "kriteriji criteria"),
        _p("/market", "🌡", "Tržište", "Je li tržište vruće ili hladno.", "market volumen"),
        _p("/analitika", "📈", "Analitika", "Posjete s Googlea.", "google search console gsc seo klikovi prikazi upiti posjete"),
        _p("/usage", "💸", "Potrošnja", "Koliko trošimo na servise.", "trošak helius apify budžet"),
        _p("/zahtjevi", "📨", "Pozivnice i zahtjevi", "Linkovi za registraciju i tko je zatražio pristup.",
           "pristup zahtjev pozivnica invite lista čekanja novi korisnici registracija"),
        _p("/outputs", "🗂", "Izvještaji modula", "Pisani izvještaji pojedinih dijelova bota.", "outputs datoteke"),
        _p("/korisnici", "👥", "Korisnici i uloge", "Tko što smije vidjeti i raditi u aplikaciji.",
           "uloge admin prijatelj osnovni pristup prava korisnici dozvole"),
    ]),
]
# the three things the app is about (Nicholas 2.11.): they lead the menu, Pregled, the phone bar and the map
CORE = ("Glavno",)
BONUS = "Bonus"
# menu groups only an admin sees (UI_ADMINS); everyone else still reaches the pages by link or search
ADMIN = ("Sustav",)
# only the trade owner and the players they invite (cookie cb_pt, see run_ui._trade_cookie)
PRIVATE = ("Autopilot",)
# detail pages light up the menu item they belong to
NAV_PREFIX = {"/postavke": "/postavke", "/token/": "/tokens", "/tokens/": "/tokens", "/dugorocno": "/tokens", "/wallet/": "/wallets", "/outputs/": "/outputs", "/natjecanje/": "/natjecanje",
              "/prijedlozi/": "/prijedlozi", "/kol/": "/kol",
              "/prijava": "/", "/nas-token/": "/nas-token", "/registracija": "/natjecanje", "/izvjestaj/": "/izvjestaj"}
# phone bottom bar: the three core features + Više (opens the menu). Line icons, one colour.
_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true">{}</svg>'
BOTTOM = [("/pregled", _SVG.format('<path d="M4 11l8-7 8 7"/><path d="M6 10v9h12v-9"/>'), "Pregled"),
          ("/tokens", _SVG.format('<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/>'), "Tokeni"),
          ("/kol", _SVG.format('<path d="M4 10v4l11 5V5L4 10z"/><path d="M15 9a4 4 0 0 1 0 6"/>'), "Influenceri"),
          ("/wallets", _SVG.format('<rect x="3" y="6" width="18" height="13" rx="2"/><path d="M16 12h2"/>'), "Novčanici")]
MORE_ICON = _SVG.format('<circle cx="6" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="18" cy="12" r="1"/>')

# Logo: candidates, LOGO picks the one shown. Plain SVG, no files to serve.
LOGOS = {
    "sonar": ("MemeSonar", '<svg viewBox="0 0 32 32" width="{s}" height="{s}" aria-hidden="true"><defs><linearGradient '
              'id="lgm" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="#4f46e5"/><stop offset="1" '
              'stop-color="#06b6d4"/></linearGradient></defs><rect width="32" height="32" rx="9" fill="url(#lgm)"/>'
              '<g fill="none" stroke="#fff" stroke-width="1.9">'
              '<circle cx="16" cy="16" r="5.2" stroke-opacity=".9"/>'
              '<circle cx="16" cy="16" r="9.6" stroke-opacity=".55"/>'
              '<circle cx="16" cy="16" r="14" stroke-opacity=".25"/></g>'
              '<circle cx="16" cy="16" r="2.3" fill="#fff"/><circle cx="22.8" cy="9.2" r="2.6" fill="#a7f3d0"/>'
              '<circle cx="22.8" cy="9.2" r="4.3" fill="none" stroke="#a7f3d0" stroke-opacity=".5" stroke-width="1.2"/></svg>'),
    "radar": ("Radar", '<svg viewBox="0 0 32 32" width="{s}" height="{s}" aria-hidden="true"><defs><linearGradient '
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
LOGO = os.environ.get("UI_LOGO", "sonar") if os.environ.get("UI_LOGO", "sonar") in LOGOS else "sonar"


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
    "/pregled": ("Početna: najvažnije na jednom mjestu", "Koja strategija najviše zarađuje i koliko, koliko podataka alat "
                 "ima i kako je narastao u odnosu na prošli tjedan, zanimljivosti sada i brzi linkovi.",
                 "Prvo što vidiš nakon prijave; odavde ideš na Tokene, Influencere i Novčanike."),
    "/postavke": ("Tvoj račun, tvoja pravila", "Lozinka, profilna slika, jezik aplikacije (hrvatski ili engleski), "
                  "društvene mreže i e-mail, odjava sa svih uređaja i brisanje računa.",
                  "Slika i društvene mreže se vide u Natjecanju; jezik vrijedi za cijelu aplikaciju."),
    "/novo": ("Dnevnik promjena", "Svaka nova mogućnost i popravak, s datumom.",
              "Kad se nešto doda, na vrhu aplikacije se pojavi kratka obavijest s linkom ovamo."),
    "/pojmovnik": ("Što znači svaki pojam u alatu", "Svaki pojam, ocjena, stupac i stranica objašnjeni običnim riječima, "
                   "s primjerom, gdje ga vidiš i povezanim pojmovima. Svaki ⓘ u aplikaciji otvara objašnjenje odavde.",
                   "Jedno mjesto istine za objašnjenja: kad se doda novi pojam, objašnjenje se pojavi svugdje."),
    "/korelacije": ("Tko radi zajedno i kako", "KOL grupe koje zovu iste tokene, walleti koji kupe prije poziva određenog "
                    "računa, walleti istog vlasnika, signali koji idu uz pumpu i što poznate grupe diraju sada, s AI "
                    "tumačenjem na vrhu.", "Spaja X, Telegram i on-chain podatke: praćene grupe idu u registar walleta, "
                    "a njihova aktivnost je rani signal za ulaz prije gomile."),
    "/": ("Odgovor na pitanje \"što sad?\"", "Tri glavne stvari alata: prijedlozi tokena po Šansi za skok, najbolji influenceri i "
          "njihovi zadnji pozivi, te što praćeni novčanici kupuju. Ispod su veliki pogoci, demo rezultat, kako se baza puni i "
          "tablica tokena koji su prošli više analiza.",
          "Završna točka cjevovoda: ovdje se vidi što je iz svih slojeva izašlo kao kandidat."),
    "/tokens": ("Sve što alat zna o svakom tokenu", "Svaki token viđen u zadnjih 7 dana kroz sve analize (hype, X, smart money, "
                "KOL, holderi, rug, event, demo), poredan po Šansi; odvojeno event tokeni, stariji i odbačeni.",
                "Povijest i puna slika; za trenutak zadnjeg prolaza služi Zadnji sken, za odluku Pregled."),
    "/radar": ("Što je hype skener vidio u zadnjem prolazu", "Kandidati iz zadnjeg skena (svake 2 min) s razlozima i rizicima, "
               "odbačeni, narativi (X trendovi, kopije), smart money, radi li ocjena, Apify trošak.",
               "Prvi sloj cjevovoda: sirovi signali s DexScreenera, pump.funa i X-a prije skupljih provjera."),
    "/events": ("Događaji oko kojih bi mogli nastati tokeni", "Kalendar s točkicama po važnosti, lista događaja s hype ocjenom i "
                "najizglednijim tokenom, te praćenje tokena od 14 dana prije eventa (volumen, kupci, smart money).", "Ulaz za klasu Event: pravi token događaja ide u slojevitu analizu kao event kandidat."),
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
    "/korisnici": ("Tko što smije", "Svi korisnici i njihove uloge: Admin, Prijatelj ili Osnovni.",
                   "Novi korisnici su Osnovni: gledaju, ali ne vide potrošnju i ne pokreću ništa što košta."),
    "/zahtjevi": ("Novi ljudi koji žele ući", "Zahtjevi s javne naslovne stranice: ime, kontakt, iskustvo i što ih "
                  "zanima. Gumb Pozovi napravi jednokratni link za registraciju.", "Ulaz u Natjecanje: od zahtjeva do "
                  "pozivnice i demo računa od $1.000."),
    "/natjecanje": ("Ljudi protiv bota", "Demo računi korisnika, njihovi ulazi i ljestvica.",
                    "Usporedba ljudskog izbora s botovim na istim tokenima."),
    "/pravi-trade": ("Autopilot: bot trguje pravim novcem", "Wallet i upute za postavljanje na vrhu, pa koga bot prati, "
                     "preporuke alata (influenceri, walleti, tokeni po zadnjih 7/14/30 dana), pozicije i limiti.", "Pravi novac ide samo kad je prekidač uključen i ključ postavljen u Renderu."),
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
    "/analitika": ("Kako nas ljudi nalaze na Googleu", "Klikovi, prikazi, CTR i prosječna pozicija iz Google Search "
                   "Consolea, upiti blizu vrha, najjače stranice, zemlje i uređaji.", "Pokazuje koje javne stranice "
                   "rade i koje vrijedi poboljšati; podaci kasne oko 2 dana."),
    "/usage": ("Koliko trošimo i gdje curi", "Helius krediti i Apify dolari po modulu, dnevno i mjesečno, upozorenja.",
               "Čuvar budžeta za slojevitu analizu: skupe razine T2/T3 žive unutar ovih limita."),
    "/outputs": ("Pisani izvještaji modula", "Markdown datoteke koje moduli pišu u output/ (kalendar, dex, rug, demo).",
                 "Sirovi izlaz za provjeru; sve bitno iz njih je i u bazama i na stranicama."),
    "/izvori": ("Telegram kanali, KOL novčanici i konvergencija", "Javni Telegram call kanali, KOL novčanici na lancu i "
                "trenutci kad više izvora zove isti token.", "Izvor značajki telegram i konvergencija u hype ocjeni i "
                "konvergencijskih demo ulaza."),
    "/dugorocno": ("Sigurniji sloj: preživjeli i oživljeni tokeni", "Stariji tokeni koji se oporavljaju od padova i rastu s "
                   "tržištem (uzor Fartcoin i Useless) i stari tokeni koji se bude, s ocjenom, razlozima i demo portfeljem "
                   "usporedno sa SOL-om.", "Odvojeno od lova na nove tokene: drugi izvori, drugi horizont (tjedni i mjeseci), "
                   "vlastito učenje na povijesti cijena."),
    "/strategije": ("Koji izvor kupnji zarađuje", "Pet demo računa po $1000: praćeni novčanici, KOL pozivi, izbor alata, "
                    "mix (dva izvora se slažu) i nasumična kontrola, svi s istim pravilima izlaza.", "Mjeri koji izvor "
                    "ulaza vrijedi najviše; rezultat ide u jutarnji izvještaj i učenje."),
    "/kol-test": ("Isplati li se ući odmah na KOL poziv", "Odvojena 7-dnevna demo knjiga: $50 na svaki svjež poziv KOL-a "
                  "(X, Telegram, KOL novčanici), koliko daleko i koliko brzo token ode, pad prije toga i što bi zaradio "
                  "izlaz na +20, +30, +40 ili +50%.", "Samo mjerenje: ne miješa se s glavnim demo tradingom i bot iz nje "
                  "ne uči; rezultat pokazuje koje KOL-ove i koje izlaze vrijedi uključiti u glavnu strategiju."),
    "/kol": ("Tko zove tokene i što se nakon toga dogodi", "KOL-ovi i influenceri s X-a i Telegrama, njihovi pozivi s linkovima, "
             "pomak cijene i volumena poslije, grupe koje zovu zajedno, moć poziva.", "Signal koordiniranog poziva u hype ocjeni "
             "i izvor rotacijskih dev walleta."),
}


def bottom_item(path):
    """href of the phone-bar tab that is lit for this path (a detail page lights its core feature)."""
    hrefs = [h for h, _, _ in BOTTOM]
    if path in hrefs:
        return path
    for pre, href in NAV_PREFIX.items():
        if path.startswith(pre) and href in hrefs:
            return href
    return None


CSS = """
button.sm{padding:2px 7px;font-size:12px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg);cursor:pointer}
button.sm:hover{border-color:var(--acc);color:var(--acc)}.nw{white-space:nowrap}
/* landing palette (ui/landing.py, ui/loginpage.py): always light, same colours everywhere */
:root{--bg:#fff;--soft:#f6f7fb;--card:#fff;--fg:#0b1220;--mut:#5b6474;--line:#e8ebf2;--line2:#cfd5e1;--acc:#4f46e5;--acc2:#0fb5a0;
--good:#16a34a;--warn:#d97706;--bad:#dc2626;--goodbg:#ecfdf5;--warnbg:#fffbeb;--badbg:#fef2f2;--bar:#4f46e5;color-scheme:light}
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
.side .sec-c{background:color-mix(in srgb,var(--acc) 6%,transparent);border-radius:12px;padding:2px 0 6px;margin-top:8px}
.side .sec-c h4{color:var(--acc);margin-top:10px}
.side .sec-b{margin-top:22px;padding-top:6px;border-top:1px dashed var(--line)}.side .sec-b a{font-size:13px;color:var(--mut)}.side .sec-b a.on{color:var(--acc)}
.side .pub{font-weight:650;margin:0 0 10px}.side .out{color:var(--mut);font-size:13px;flex:1}
.side a.set{margin-top:18px;border-top:1px solid var(--line);border-radius:0 0 9px 9px;padding-top:11px}
.outrow{display:flex;align-items:center;gap:6px;margin-top:4px}.lsw{display:inline-flex;border:1px solid var(--line);border-radius:999px;overflow:hidden;flex:none}
.side .lsw a{padding:3px 9px;font-size:12px;border-radius:0;color:var(--mut);font-weight:600}.side .lsw a.on{background:var(--acc);color:#fff}.side-head{display:none}
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
a.mapcard.pillar{border-color:color-mix(in srgb,var(--acc) 35%,var(--line));background:linear-gradient(135deg,color-mix(in srgb,var(--acc) 7%,var(--card)),var(--card))}
.pillars{grid-template-columns:repeat(3,minmax(0,1fr));margin-top:4px}
@media(max-width:700px){.pillars{grid-template-columns:1fr;gap:8px}.pillars a.mapcard{padding:10px 14px}.core-list .xl,.core-list .cpy,.core-list [title*='Kopiraj']{display:none!important}.core-list li{padding:9px 12px;gap:4px 10px}.core-list .st{gap:4px 10px}}
.core-list{list-style:none;margin:0;padding:0;background:var(--card);border:1px solid var(--line);border-radius:14px}
.core-list li{display:flex;gap:10px;align-items:center;justify-content:space-between;padding:10px 14px;border-bottom:1px solid var(--line);flex-wrap:wrap}
.core-list li:last-child{border-bottom:0}.core-list .who{font-weight:600;min-width:0}.core-list .st{display:flex;gap:12px;flex-wrap:wrap;font-size:13px;color:var(--mut)}
.core-list .st b{color:var(--fg);font-variant-numeric:tabular-nums}.core-more{margin:8px 2px 0;font-size:14px}
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

LIGHT_CSS = """
/* 2026-11-01: every in-app page in the landing style (ui/landing.py): always light, white and airy, thin #e8ebf2
   lines, big soft corners, black pill buttons. Colours, fonts and lines only: nothing is moved, added or removed. */
html{color-scheme:light}body{background:var(--bg);color:var(--fg);font-family:Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
h1{font-size:28px;font-weight:800;letter-spacing:-.035em;line-height:1.15}h2{font-weight:750;letter-spacing:-.025em}
.lead,.tdesc{color:var(--mut)}.tdesc{border-left:2px solid var(--line)}
.card,.stat,.tw,pre,main>details,details.homemap,.gl-term,ul.sres{border-color:var(--line);border-radius:18px;box-shadow:none}
.stat .v{font-weight:750;letter-spacing:-.02em}
.intro{background:var(--soft);border:1px solid var(--line);border-radius:16px}
th{background:var(--card);color:var(--mut)}tr:hover td{background:var(--soft)}
input,select,textarea{background:var(--soft);color:var(--fg);border:1px solid var(--line);border-radius:12px;font:inherit}
input:focus,select:focus,textarea:focus{outline:none;border-color:var(--acc);background:#fff;box-shadow:0 0 0 4px rgba(79,70,229,.12)}
input[type=checkbox],input[type=radio]{accent-color:var(--fg)}
/* buttons: like the landing .btn.p (black pill); type=button toggles like .btn.g (white pill with a thin line).
   :where() keeps this at zero specificity, so a page's own button style still wins. */
:where(button){font:inherit;font-weight:600;cursor:pointer;border-radius:999px;padding:8px 16px;border:1px solid var(--fg);
 background:var(--fg);color:#fff;transition:background .15s,border-color .15s,box-shadow .15s,transform .15s}
:where(button):hover{background:#1f2937;border-color:#1f2937;box-shadow:0 10px 30px -14px rgba(11,18,32,.5)}
:where(button):active{transform:scale(.98)}:where(button):disabled{opacity:.45;cursor:not-allowed;box-shadow:none}
:where(button[type=button]){background:#fff;color:var(--fg);border-color:var(--line)}
:where(button[type=button]):hover{background:#fff;border-color:var(--line2);box-shadow:none}
button.sm{border-radius:999px;padding:3px 11px;font-weight:600;background:#fff;border-color:var(--line)}
button.sm:hover{border-color:var(--line2);color:var(--fg)}
.sform button{border-radius:999px;background:var(--fg);padding:9px 18px}.sform button:hover{background:#1f2937}
/* header + menus */
header.top{background:rgba(255,255,255,.85);-webkit-backdrop-filter:blur(12px);backdrop-filter:blur(12px);border-bottom-color:var(--line)}
.srch input{background:var(--soft);border-radius:14px}.srch input:focus{background:#fff;box-shadow:0 0 0 4px rgba(79,70,229,.12)}
.cta{background:var(--fg);box-shadow:none}.cta:hover{filter:none;background:#1f2937;box-shadow:0 10px 30px -10px rgba(11,18,32,.5)}
.menu-btn{border-radius:999px;border-color:var(--line);background:#fff}
aside.side{background:#fff;border-right-color:var(--line)}.side h4{color:var(--mut)}
.side a:hover{background:var(--soft)}.side a.on{background:var(--soft);color:var(--fg);font-weight:650;box-shadow:inset 0 0 0 1px var(--line)}
.side .sec-c{background:linear-gradient(135deg,rgba(79,70,229,.06),rgba(15,181,160,.06));border-radius:16px}.side .sec-c h4{color:var(--acc)}
.side .lsw a.on{background:var(--fg)}.side a.set{border-top-color:var(--line)}
.bbar{background:rgba(255,255,255,.92);border-top-color:var(--line)}.bbar .on{color:var(--fg)}.bbar a.n .bi{background:var(--fg)}
/* cards and chips */
a.mapcard{border-radius:18px}a.mapcard:hover{border-color:var(--line2);box-shadow:0 20px 40px -28px rgba(11,18,32,.3)}
a.mapcard.hot,.quick a.hot{border-color:#c7d2fe;background:linear-gradient(135deg,rgba(79,70,229,.06),rgba(15,181,160,.06)),#fff}
.quick a{border-radius:16px}.quick a:hover{border-color:var(--line2)}
.secnav a:hover{border-color:var(--line2);color:var(--fg)}.secnav a.on{background:var(--fg);border-color:var(--fg)}
.cand{border-radius:18px}.cand:hover{border-color:var(--line2);box-shadow:0 20px 40px -28px rgba(11,18,32,.3)}
dialog#ev,dialog#gl{border-color:var(--line);border-radius:22px;background:#fff;box-shadow:0 40px 80px -30px rgba(11,18,32,.35)}
dialog#ev::backdrop,dialog#gl::backdrop{background:rgba(11,18,32,.45)}dialog#ev .bar2{background:#fff}
dialog#gl .bar2 button{border-radius:999px;background:#fff}.gl-here{background:var(--soft)}
@media(max-width:1000px){aside.side{box-shadow:none}body.nav-open aside.side{box-shadow:0 0 40px rgba(11,18,32,.25)}}
@media(max-width:700px){h1{font-size:24px}}
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
    from ui.i18n import t
    return json.dumps([{"href": p["href"], "icon": p["icon"], "name": t(p["name"]), "desc": t(p["desc"]),
                        "kw": p["kw"] + " " + p["name"], "sec": t(sec)}
                       for sec, items in SECTIONS for p in items], ensure_ascii=False).replace("</", "<\\/")


def _role_cls(href):
    """' r-pri' / ' r-adm' on menu items a basic user cannot open (league/roles.PAGES), hidden through the cb_r cookie."""
    from league import roles
    need = roles.PAGES.get(href)
    return " r-pri" if need == "prijatelj" else " r-adm" if need == "admin" else ""


def side_menu(cur):
    """Left menu (laptop) / drawer (phone): the three core features on top, everything else in small groups below.
    The Sustav group carries class adm-only and shows only for admins (see ADMIN_JS)."""
    svg, name = logo(26)
    b = [f'<aside class=side id=side aria-label="Izbornik"><div class=side-head><a class=brand href="/pregled">{svg}<span>{esc(name)}</span></a>'
         '<button data-nav aria-label="Zatvori izbornik">✕</button></div>']
    for sec, items in SECTIONS:
        links = "".join(f'<a href="{p["href"]}" class="{"on" if p["href"] == cur else ""}{_role_cls(p["href"])}">'
                        f'{esc(p["name"])}</a>' for p in items)
        if sec in CORE:
            b.append(f'<div class=sec-c>{links}</div>')
        else:
            extra = " adm-only" if sec in ADMIN else " pt-only" if sec in PRIVATE else ""
            b.append(f'<div class="sec{extra}"><h4>{esc(sec)}</h4>{links}</div>')
    from ui.i18n import lang
    en = lang() == "en"
    b.append(f'<a href="/postavke" class="set{" on" if cur == "/postavke" else ""}">Postavke</a>'
             f'<a class=pub href="{_home_link()}" target=_blank rel=noopener>Naslovna stranica ↗</a>'
             '<div class=outrow><a class=out href="/odjava">Odjava</a>'
             '<span class=lsw translate=no aria-label="Jezik / Language">'
             f'<a href="/jezik?l=hr" class="{"" if en else "on"}" title="Hrvatski">HR</a>'
             f'<a href="/jezik?l=en" class="{"on" if en else ""}" title="English">EN</a></span></div></aside>')
    return "".join(b)


# Admin-only bits (Sustav menu, spend warnings, manual job buttons) carry class adm-only. Pages are cached and the
# same for everyone, so the server sets a cb_adm=1 cookie for admins and this shows them; it only declutters,
# the pages themselves stay reachable by link.
ADMIN_CSS = (".adm-only{display:none!important}html.adm .adm-only{display:revert!important}"
             ".pt-only{display:none!important}html.pt .pt-only{display:revert!important}"
             "html.r-osnovni .r-pri,html.r-osnovni .r-adm,html.r-prijatelj .r-adm{display:none!important}"
             ".novo-bar{display:flex;gap:6px;align-items:baseline;flex-wrap:wrap;font-size:13.5px;padding:7px 12px;"
             "margin:0 0 12px;border-radius:10px;background:var(--soft);color:var(--fg);text-decoration:none}"
             ".novo-bar span{flex:1;min-width:0}.novo-bar u{text-decoration:none;font-weight:600;white-space:nowrap}"
             ".nomail{background:#fff7e6;border-color:#f5d08a;margin:0 0 14px}.nomail a{font-weight:600}")
ADMIN_JS = ("if(/(^|; )cb_adm=1/.test(document.cookie))document.documentElement.classList.add('adm');"
            "if(/(^|; )cb_pt=1/.test(document.cookie))document.documentElement.classList.add('pt');"
            "var _r=/(^|; )cb_r=(\\w+)/.exec(document.cookie);"
            "document.documentElement.classList.add('r-'+(_r?_r[2]:'osnovni'));"
            # 4.11.: one quiet line about the newest change until the user opens /novo
            "document.addEventListener('DOMContentLoaded',function(){var h=document.documentElement,"
            "q=document.querySelector('meta[name=novo]'),k=q&&q.content;"
            "if(!k||location.pathname==='/novo')return;var c=/(^|; )cb_novo=([^;]*)/.exec(document.cookie);"
            "if(c&&c[2]===k)return;var m=document.querySelector('main');if(!m)return;var en=h.lang==='en',"
            "a=document.createElement('a');a.className='novo-bar';a.href='/novo';a.innerHTML='✨ <span>'+"
            "(en?'New':'Novo')+': <b></b></span><u>'+(en?'See what is new':'Pogledaj što je novo')+' →</u>';"
            "a.querySelector('b').textContent=q.dataset.t||'';m.insertBefore(a,m.firstChild)});"
            # players without an e-mail (3.11.): a box on top of every page until they add one in Postavke
            "if(/(^|; )cb_nm=1/.test(document.cookie)&&location.pathname!=='/postavke')"
            "document.addEventListener('DOMContentLoaded',function(){var m=document.querySelector('main');if(!m)return;"
            "var en=document.documentElement.lang==='en',d=document.createElement('div');d.className='card nomail';"
            "d.innerHTML=en?'<b>📧 Please add your e-mail.</b> We will use it to tell you about new features and "
            "important changes. <a href=\"/postavke#profil\">Add e-mail →</a>':'<b>📧 Upiši svoj e-mail.</b> Njime ti "
            "javljamo nove mogućnosti alata i važne promjene. <a href=\"/postavke#profil\">Upiši e-mail →</a>';"
            "m.insertBefore(d,m.firstChild)});")

SIMPLE_CSS = """
/* 2.11. simpler look: data first, quiet menu, segmented filters, line icons in the phone bar */
.side .sec-c{background:none!important;padding:4px 0 6px;margin-top:4px;border-bottom:1px solid var(--line);border-radius:0!important}
.side .sec-c a{font-size:15px;font-weight:600;padding:9px 10px}
.side .sec h4{margin:16px 10px 3px}.side .sec a{font-size:13.5px;color:var(--mut);padding:5px 10px}
.side .sec a.on{color:var(--fg)}
.side .pub{font-weight:400;font-size:13px;color:var(--mut);margin:4px 0 0}
.seg{display:inline-flex;background:var(--soft);border-radius:10px;padding:3px;gap:2px;margin:2px 0 14px;max-width:100%;overflow-x:auto}
.seg a{padding:6px 14px;border-radius:8px;font-size:13.5px;color:var(--mut);text-decoration:none;white-space:nowrap;font-weight:500}
.seg a.on{background:var(--card);color:var(--fg);box-shadow:0 1px 2px rgba(11,18,32,.1)}
h1{font-size:26px;letter-spacing:-.02em;margin:10px 0 12px}
.bbar svg{width:22px;height:22px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round;display:block}
.bbar .bi{height:24px;display:grid;place-items:center}
.ext-big .xl{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 4px}.ext-big .xl a{width:34px;height:34px;border-radius:9px;background:var(--soft);display:grid;place-items:center}
.ext-big .xl img{width:18px;height:18px}
.tokhead{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;margin:6px 0 10px}
.tokhead h1{margin:0}.tokhead .sn{text-align:right}.tokhead .sn small{display:block;font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.06em}
.tokhead .sn b{font-size:26px;font-variant-numeric:tabular-nums}
.verdict{background:var(--soft);border-radius:10px;padding:10px 14px;margin:0 0 12px;font-size:15px}
.verdict details{font-size:14px;margin-top:6px}.verdict summary{color:var(--mut);font-size:13px;cursor:pointer}
"""


def seg(items, cur):
    """Segmented control: [(href, label)], the one whose href == cur is lit. Plain links, so it works cached."""
    return "<nav class=seg>" + "".join(f'<a href="{h}" class="{"on" if h == cur else ""}">{esc(t)}</a>' for h, t in items) + "</nav>"


def page(title, body, path="/"):
    from ui.charts import CSS as CH_CSS, JS as CH_JS
    cur = nav_item(path)
    svg, name = logo(30)
    header = (f'<header class=top><button class=menu-btn data-nav aria-label="Otvori izbornik">☰</button>'
              f'<a class=brand href="/pregled" title="Pregled">{svg}<span>{esc(name)}</span></a>'
              '<form class=srch action="/trazi" role=search autocomplete=off><span class=si>🔍</span>'
              '<input id=q name=q placeholder="Traži token, adresu ili KOL" aria-label="Traži" enterkeyhint=search>'
              '<kbd>/</kbd><div class=sdrop id=sdrop hidden></div></form></header>')
    bcur = bottom_item(path)
    bbar = ("<nav class=bbar aria-label='Brzi izbornik'>" + "".join(
        f'<a href="{h}" class="{"on" if h == bcur else ""}"><span class=bi>{i}</span>{t}</a>'
        for h, i, t in BOTTOM) + f"<button data-nav><span class=bi>{MORE_ICON}</span>Više</button></nav>")
    from ui import deploypage, i18n, secnav
    try:
        from ui import novo
        nk, nt = novo.notice_data()
    except Exception:  # noqa: BLE001
        nk, nt = "", ""
    return (f"<!doctype html><html lang={i18n.lang()}><head><meta charset=utf-8><meta name=viewport content='width=device-width,"
            f"initial-scale=1'><meta name=color-scheme content=light><title>{esc(title)} · {esc(name)}</title>{_fav.HEAD}"
            f"<meta name=novo content=\"{esc(nk)}\" data-t=\"{esc(nt)}\" translate=no><script>{ADMIN_JS}</script>"
            f"<style>{CSS}{COLS_CSS}{NAV_CSS}{CH_CSS}{secnav.CSS}{LIGHT_CSS}{SIMPLE_CSS}{ADMIN_CSS}</style></head><body>"
            f"{header}<div class=shell>{side_menu(cur)}<div class=scrim data-nav></div><main>{secnav.markup()}{annotate(body)}</main></div>"
            f"{bbar}<script>{(JS + GL_JS + CH_JS + COLS_JS + NAV_JS).replace('__PAGES__', _pages_json())}{secnav.JS}</script>{deploypage.register_tag()}</body></html>")


def map_page(qs=None):
    """/mapa: every page as a card, grouped like the menu; the three core features first."""
    b = ["<h1>Sve stranice</h1>"]
    for sec, items in SECTIONS:
        b.append(f"<h2{' class=adm-only' if sec in ADMIN else ''}>{esc(sec)}</h2>"
                 f"<div class='mapgrid{' adm-only' if sec in ADMIN else ''}'>" + "".join(
                     f'<a class="mapcard{" pillar" if sec in CORE else ""}{_role_cls(p["href"])}" href="{p["href"]}"><span class=mi>{p["icon"]}</span>'
                     f'<b>{esc(p["name"])}</b><span class=mut>{esc(p["desc"])}</span></a>' for p in items) + "</div>")
    return "Sve stranice", "".join(b)


def note(text):
    """A short line of real information under a heading (a count, a warning) — unlike the old tdesc explanations."""
    return f'<p class=mut style="font-size:13px;margin:4px 0 8px">{text}</p>'


def tdesc(text):
    """Was a "what this table covers" line above every table. Removed (2.11.): the heading and the column ⓘ say it,
    the explanation lives in the Pojmovnik. Kept as a no-op so old calls keep working; don't add new ones."""
    return ""


def lead(text):
    """One visible plain-language line under a heading: what the table shows (4.11.: Nicholas found the tables unclear
    after tdesc became a no-op). Keep it to one sentence."""
    return f'<p class="mut tlead" style="margin:0 0 10px;font-size:13px;line-height:1.45">{esc(text)}</p>'


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


_ANN = re.compile(r'(<div class=l>)([^<>]{2,70})(?=</div>)')


def annotate(body):
    """Add a glossary ⓘ to every stat-tile label whose text is a known term. Headings stay clean: the page says
    what it is through its layout; terms are explained where the numbers are (column headers, stat labels)."""
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
    return f'<a href="/token/{quote(mint)}" title="Otvori stranicu tokena" translate=no>{label}</a> ' + copy_icon(mint) + ext_icons(mint)


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
