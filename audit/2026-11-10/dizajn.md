# Dizajn i ugovor između grupa (noć 10.11.2026.)

Svaka grupa radi u SVOM git worktreeju na SVOJOJ grani i dira samo svoje datoteke. Ovaj dokument je ugovor: imena
modula, funkcija i ključeva rječnika ispod su obvezna, da se dijelovi spoje bez dogovaranja. Tko zove tuđi modul,
zove ga u `try/except` i ima razuman prikaz kad modula (još) nema. Polazište svih grana: `ccr-232765a7-33e8r8`.

| grupa | worktree | grana | vlasništvo |
|---|---|---|---|
| novac | /home/user/wt/novac | noc/novac | trade/equity.py (novo), trade/aplog.py (novo), run_trade.py, trade/*, league/* + njihovi testovi |
| apui | /home/user/wt/apui | noc/apui | ui/pravitrade.py, ui/apchart.py (novo), u run_ui.py SAMO rute /pravi-trade/* + testovi pravitrade |
| javno | /home/user/wt/javno | noc/javno | ui/apjavno.py (novo), u run_ui.py rute /autopilot*, PUBLIC/SHARED putanje, traka u ui/html.py + testovi |
| pogon | /home/user/wt/pogon | noc/pogon | ops/cpuguard.py (novo), ops/uptime.py (novo), ops/dataaudit.py (novo), ops/*, start.sh, sekundne petlje izvan grupa gore |
| web | /home/user/wt/web | noc/web | run_sched.py, ui/landing.py, ui/sitelog.py (novo), ui/public*.py, ui/blog*.py + testovi |
| sentry | /home/user/wt/sentry | noc/sentry | ops/sentry.py (novo), po JEDAN redak `sentry.init(...)` u ulaznim točkama (run_ui.py, run_trade.py, run_sched.py, run_kol.py ...) |

Zajednička pravila: Python 3.13, samo stdlib (bez novih paketa), UI tekstovi hrvatski, bez em-crtica u tekstu sučelja,
testovi `tests/test_*_offline.py` (unittest, bez mreže), `.copy_wake` i `*.db` se ne commitaju, commit u svojoj grani
s `git -c core.hooksPath=/dev/null commit`. Ništa ne dira `trade/config.json` ("dry"), run_trade.PROOF ni pragove
rizika (30k $ mcap, samo bondani). Nema novih plaćenih izvora. Nema čitanja cijele tablice u petlji koja se vrti
svake sekunde: upit ide po indeksu i po vremenu ("od zadnjeg puta"), rezultat se kešira.

## 1. novac: povijest vrijednosti walleta i dnevnik odluka

### trade/equity.py
Tablica u trade.db (stvara je `ensure(con)`, zove se i iz `executor.connect`):

    equity (ts INTEGER PRIMARY KEY, sol REAL, usdc REAL, tokens_sol REAL, sol_usd REAL, usd_eur REAL,
            flow_sol REAL DEFAULT 0, src TEXT DEFAULT 'live')

- `sol`, `usdc`: stanje walleta; `tokens_sol`: procjena otvorenih PRAVIH pozicija u SOL-u (cijena iz besplatnog izvora
  koji kod već koristi; bez cijene = preostali ulog); `sol_usd`: cijena SOL-a; `usd_eur`: koliko EUR vrijedi 1 USD;
  `flow_sol`: uplata (+) ili isplata (−) otkrivena na ovoj snimci; `src`: 'live' (izmjereno) ili 'recon' (rekonstruirano iz naloga).
- Uplata = promjena SOL stanja koju ne objašnjavaju nalozi (kupnje, prodaje, naknade, povrat rente) između dvije
  snimke, veća od `FLOW_MIN_SOL` (0.02). Prva snimka: cijela vrijednost je "početni ulog" (flow), da PnL krene od 0.

Funkcije (nijedna ne baca iznimku prema pozivatelju petlje; mreža s kratkim timeoutom):

    EVERY_S = 300
    ensure(con)
    rates(now=None)                 -> {"sol_usd": float|None, "usd_eur": float|None, "ts": int}   # keš: SOL 60 s, EUR 6 h, besplatni izvori bez ključa
    snapshot(con, now=None, force=False, **inject) -> dict|None   # najviše jedna snimka u EVERY_S
    series(con, since=None, max_points=600) -> [ {ts, sol, usdc, tokens_sol, value_sol, value_usd, value_eur,
                                                  sol_usd, usd_eur, flow_sol, net_in_sol, pnl_sol, src}, ... ]  # najstarije prvo
    summary(con, now=None)          -> {value_sol, value_usd, value_eur, sol, usdc, tokens_sol, net_in_sol, pnl_sol,
                                        pnl_pct, pnl_24h_sol, first_ts, last_ts, sol_usd, usd_eur, n} ili {} bez podataka
    deposits(con)                   -> [ {ts, sol}, ... ]          # flow_sol != 0
    backfill(con, now=None)         -> int                         # jednokratno iz naloga, src='recon', idempotentno

`value_sol = sol + tokens_sol + usdc / sol_usd`; `net_in_sol` = zbroj flow_sol do te točke; `pnl_sol = value_sol − net_in_sol`.
Snimanje pokreće run_trade (pozadinska dretva sa svojom vezom, da petlja od 1 s nikad ne čeka mrežu).

### trade/aplog.py: jedan dnevnik odluka Autopilota

    KINDS = ("kupio", "prodao", "preskocio", "nije_proslo")
    entries(tcon, lcon=None, limit=80, since=None) -> [ {ts, kind, token, symbol, source, why, why_short, sol,
                                                         pnl_pct, mode, stage, sig, trebao}, ... ]   # najnovije prvo
    summary(rows, now=None) -> {"signali", "kupio", "prodao", "preskocio", "nije_proslo", "razlozi": [(why_short, n), ...]}  # zadnja 24 h
    why_short(text) -> str   # kratke skupine razloga: "signal star", "MC ispod 30k", "bez dokaza u demu", "kasni poziv", "likvidnost", "rug", "limit", ...

- `mode`: "live" | "dry"; `stage`: "demo" (odluka pala u demo kopiranju, league.db copy_log) | "pravi" (u zrcaljenju
  pravim novcem, trade.db); `sig`: potpis transakcije ili None.
- `trebao`: True = signal je prošao sva pravila i trebalo je kupiti, ali nalog nije prošao (tehnika: kotacija, mreža,
  kašnjenje); False = pravilo je reklo ne (i to je ispravno ponašanje); None = ne primjenjuje se (kupio / prodao).
- Izvori: trade.db `orders` i `positions` (status 'blocked' + reason), league.db `copy_log` praćenja računa
  `settings.LEAGUE_USER` (preskakanja u demo fazi). Isti signal se ne broji dvaput.
- Upiti po indeksu i s `LIMIT`; poziva se svake sekunde dok je dnevnik otvoren.

## 2. apui: stranica Autopilota (čista, minimalistička)

Redoslijed: (1) zaglavlje: stanje + vrijednost velikim brojem "1.234 SOL · 187 $ · 172 €" + PnL danas/ukupno + prekidač;
(2) GRAF preko cijele širine; (3) "Dnevnik Autopilota" zatvoren, s jednim retkom sažetka ("Danas: 12 signala · 2 kupljeno
· 9 preskočeno (5 bez dokaza u demu, 3 signal star) · 1 nije prošlo"), na klik popis; (4) otvorene pozicije;
(5) koga prati + dodavanje; (6) ručna kupnja; (7) na dnu, zatvoreno: preporuke alata, "Zovu sada", "Što kupiti sada",
limiti, pozivnice, sigurnost. Zatvorene sekcije se NE dohvaćaju dok ih netko ne otvori. Svaki redak s tokenom je
klikabilan (otvara postojeći pop-up tokena).

### ui/apchart.py (dijeli ga javna stranica)

    chart_html(series, summary, deposits=(), ident="ap", compact=False, lang="hr") -> str

Jedan SVG bez vanjskih biblioteka, širina 100 %: gornja ploha vrijednost walleta (linija), donja ploha PnL (zeleno iznad
nule, crveno ispod), zajednička vremenska os, uplate kao okomite crtkane oznake s iznosom, gumbi raspona 24 h / 7 d /
30 d / sve i jedinice SOL / $ / €, dodir ili prelazak mišem pokazuje vrijednost u točki. Prazno stanje: jasna rečenica
("Graf kreće s prvom snimkom, za najviše 5 minuta"). Rekonstruirani dio (src='recon') crtkano i tako označen.
Nove rute: `/pravi-trade/graf` (fragment grafa + zaglavlja) i `/pravi-trade/dnevnik` (fragment dnevnika).

## 3. javno: javna stranica Autopilota, chat s +1, traka

- Putanja `/autopilot` (hr) i `/en/autopilot`... samo ako postojeći i18n to nudi jeftino; inače samo hr. Čitanje je
  javno (bez prijave), na oba hosta (dodati u SHARED_PATH da se s app hosta ne preusmjerava).
- Sadržaj: stanje (UŽIVO pravim novcem / probno, istinito: `executor.is_live`), javna adresa walleta + Solscan,
  vrijednost SOL · $ · €, graf (`ui.apchart.chart_html`), statistika (zatvoreni tradeovi, dobitni, PnL, najbolji i
  najgori), koga Autopilot prati i TKO je odabrao (korisnik ili alat: polje dodaje ova grupa uz dogovor u ovom
  dokumentu: `follows.label`/postojeći podaci; ako se ne može pouzdano znati, piše "odabrao vlasnik"), zadnji ulazi i
  izlazi (iz `trade.aplog.entries`), pa chat.
- Chat: tablice u league.db `ap_chat (id INTEGER PRIMARY KEY AUTOINCREMENT, ts, user, text, hidden DEFAULT 0)` i
  `ap_chat_votes (msg_id, user, ts, PRIMARY KEY (msg_id, user))`. Pisanje i +1 samo prijavljeni igrači (CSRF kao
  ostali POST-ovi, najviše 500 znakova, ograničenje učestalosti po korisniku), gosti vide poruke i poziv na prijavu.
  Vlasnik može sakriti poruku. Tekst se uvijek escapea, linkovi se ne pretvaraju u klikabilne.
- Ne prikazuje se: ključevi, env imena, interni servisi, troškovi, gumbi za trgovanje.

    ui/apjavno.py
    page(qs, user, lang="hr") -> (title, html)
    post(path, form, user) -> redirect putanja
    banner_html(user=None) -> str        # traka na vrhu svake stranice aplikacije; "" kad Autopilot nije uživo
    landing_strip(lang="hr") -> str      # istaknuti blok za naslovnicu; "" kad Autopilot nije uživo
    live_state() -> {"live": bool, "on": bool, "since": ts|None}   # keš 30 s

Tekst trake (Jure): "Autopilot je live: podacima alata tradamo pravim novcem. Uđi, pogledaj statistiku i dodaj svoj
prijedlog." Traka vodi na /autopilot. Naslovnica: "Tradanje pravim sredstvima je live, provjeri kako nam ide".

## 4. pogon: CPU čuvar, dostupnost, sekundni poslovi

- `ops/cpuguard.py`: čita cgroup (v2 cpu.stat / cpu.max, uz rezervu v1 i /proc/stat) svake sekunde; iznad
  `CPU_HIGH` (90 %) prosjeka kroz nekoliko sekundi kratko pauzira (SIGSTOP/SIGCONT, najviše ~0,5 s odjednom)
  pozadinske poslove koji troše najviše, dok se ne spusti ispod `CPU_LOW`. NIKAD ne dira lanac novca: run_ui (u njemu
  je demo kopiranje), run_trade, slušače poziva praćenih računa (KOL uživo, Telegram), webhookove. Jedna linija u logu
  u minuti (prosjek, vrh, koliko pauza i koga). Gasi se čisto (svi zaustavljeni procesi dobiju SIGCONT, i na TERM).
- Pozadinske petlje u start.sh dobivaju `nice` (prioritet ispod UI-ja i tradea).
- `ops/uptime.py`: svakih 30 s `GET 127.0.0.1:$PORT/healthz` (timeout 5 s); spor ili neuspio odgovor u log; nakon više
  uzastopnih neuspjeha (≥150 s) i izvan prvih minuta nakon starta ponovno pokreće samo UI proces (nadzor `keep` ga diže),
  najviše jednom u 15 min.
- `ops/dataaudit.py`: samo čitanje svih baza: po tablici broj redaka (jeftino), najstariji i najnoviji zapis, svježina,
  pokrivenost ključnih polja; ispis u log kao kratke linije `DATAAUDIT {json}` + datoteka u output/. Jednom dnevno
  u noćnom prozoru i jednom nakon starta.

## 5. web: dnevno osvježavanje u 02:00 i dnevnik naslovnice

- Posao u 02:00 (Zagreb) osvježi sve javne tablice (influenceri, walleti, coin stranice, podatkovni blokovi blogova)
  i upiše redak u `site_log` (što je novo taj dan: novi influenceri, novi walleti, novi izmjereni pozivi / povijesni
  tradeovi, osvježeni blogovi), `ui/sitelog.py`: `today()`, `recent(n)`, `live_days()`.
- Naslovnica: "MemeSonar je live N dana" + zadnjih nekoliko dana promjena s internim linkovima na blogove i stranice.
  Datum početka je konstanta s env nadjačavanjem; izvor datuma zapisati u komentar.
- Naslovnica zove `ui.apjavno.landing_strip(lang)` u try/except (blok se ne prikazuje dok modula nema).

## 6. sentry

`ops/sentry.py` (stdlib): `init(component)` (sys.excepthook + threading.excepthook), `capture(exc=None, where="",
level="error")`, `message(text, level="warning")`. Bez `SENTRY_DSN` ne radi ništa. Slanje u pozadinskoj dretvi s
redom ograničene duljine, najviše N događaja u minuti, isti otisak najviše jednom u 5 min. Šalje se: tip i tekst
iznimke, stog (datoteka, funkcija, redak, BEZ lokalnih varijabli), komponenta, izdanje (git sha ako postoji).
Ne šalje se: env, kolačići, upiti, adrese walleta, ključevi (tekst poruke prolazi kroz čistač uzoraka).
