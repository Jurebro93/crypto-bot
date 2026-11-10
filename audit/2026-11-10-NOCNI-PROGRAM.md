# Noćni program 10.11.2026. (Jure, poruka u 00:31 CET)

Ova bilješka je izvor istine za posao koji traje cijelu noć. Ako se sesija prekine (potrošnja, kontejner), nastavi
odavde: pročitaj tablicu "Stanje" na dnu, `git status`, `git log origin/main..HEAD`, pa kreni od prvog retka koji
nije GOTOVO. Grana: `ccr-232765a7-33e8r8`. Usage se resetira u 01:10 CET: teški višeagentni poslovi kreću tada.

## Što je Jure tražio (njegovim riječima, sažeto po točkama)

1. **Pitanje, trošak:** koliko bi koštalo pratiti puno više podataka i osvježavati ih svake sekunde; postoji li
   jeftiniji "listener" koji na aktivnost (npr. novu kupnju walleta) sam javi signal, da ne pingamo stalno.
2. **Pitanje, 2 CPU-a:** bi li alat tada mogao punom parom skupljati i analizirati podatke i istovremeno tradati.
3. **Prezentacija** kao za osnovnu školu: kako bot radi, koje podatke uzima i osvježava, kako algoritam nalazi nove
   tokene, kako novi token i novi wallet dolaze "u opticaj", kako se sve filtrira (workflow, data flow, filtri).
   Poslati na msjure321@gmail.com.
4. **Sekundni poslovi:** oni koji drže Autopilot svježim ne smiju čitati cijelu bazu svake sekunde, samo ono što
   ima smisla. **CPU najviše 90–95 % u svakom trenutku**, aplikacija uvijek dostupna; skripta/nadzor koji to
   provjerava. **Log Autopilota na klik pri vrhu:** kad je kupio, kad nije, što je preskočio i zašto.
   Cijela aplikacija se optimizira oko Autopilota: on mora vratiti troškove i zaraditi ("pokazati da AI može trgovati").
5. **Plan profitabilnosti:** istražiti i razraditi; logika koja obrađuje postojeće podatke i kontrolira dotok novih
   u smjeru profitabilnog Autopilota; reći treba li više podataka.
6. **Na kraju jedan PR sa svime, pa merge svega zajedno.** (Deploy ne 01–06 CET: merge iza 06:00.)
7. **Preko noći audit podataka backenda** + **prijedlozi minimalističkog UI-ja sa screenshotovima** do jutra
   (jednostavno i pregledno kao Apple i najbolje aplikacije).
8. **Sentry:** iskoristiti za analizu i popravak koda. (Stanje 00:36: org `serprise` (de.sentry.io) nema nijedan
   projekt ni grešku; aplikacija ne šalje ništa. Treba: projekt + DSN + mali stdlib pošiljatelj + env na Renderu.)
9. **Javna stranica Autopilota za sve igrače:** velika poruka na vrhu aplikacije "Autopilot je live: podacima alata
   tradamo pravim novcem; uđi, pogledaj statistiku i dodaj svoj prijedlog". Ispod **chat/prijedlozi**: svatko ostavi
   poruku, čuva se, svi vide i reagiraju s +1. Stranica istaknuta na naslovnici ("tradanje pravim sredstvima je
   live, provjeri kako nam ide"): koga se prati i je li ga odabrao korisnik ili alat, ulazi, izlazi, **javna adresa
   novčanika**, interaktivni elementi; na vrhu homepagea vidljivo kad je Autopilot uključen.
10. **"Zovu sada" i "Što kupiti sada"** su mu nejasni (tokeni na koje se ne može kliknuti): na dno ili maknuti.
    Stranica Autopilota mora biti čista, minimalistička, pregledna.
11. **Graf na vrhu Autopilota** preko cijele širine: vrijednost walleta kroz vrijeme, uplate označene na grafu;
    uz iznos u SOL-u živa pretvorba u USD i EUR; PnL kroz vrijeme u istom grafu.
12. **U 01:10 (reset usagea) pokrenuti audit svih podataka u bazi:** kako ih nadopuniti, kako povećati efikasnost,
    kojim podacima dopuniti bazu, kako doći do 1-minutnih svijeća (točniji rast i utjecaj influencera i walleta).
    **Istraživanje profitabilnosti:** deseci/stotine YouTube videa, članaka, X objava poznatih meme tradera; svi
    savjeti u prijedlog.
13. **Dnevno osvježavanje cijelog weba u 02:00** (npr. https://memesonar.app/influencers): sve tablice na javnim
    stranicama s novim podacima. Na naslovnici **dnevnik "stranica je live N dana"**: što je dodano (blogovi
    osvježeni novim podacima, novi influenceri, novi walleti, novi povijesni tradeovi), s internim linkovima.

## Pravila koja vrijede cijelo vrijeme (CLAUDE.md + večerašnje odluke)

- Pravi novac: `trade/config.json` ostaje `dry`; brava "dokaz u demu" (run_trade.PROOF) se ne dira bez Jurinog "da".
- SOLANA_PRIVATE_KEY nikad u sandbox. Javna adresa novčanika (SOLANA_PUBLIC_KEY) smije na javnu stranicu: Jure je to izričito tražio (točka 9).
- Tokeni ispod 30k $ se ne analiziraju; samo bondani.
- Deploy: jedan merge za sve, NE između 01:00 i 06:00 CET. Jure je merge odobrio unaprijed ("na kraju … sve merge zajedno").
- Svaki novi trošak (API, plan, SOL) prvo izmjeriti i predložiti jeftinije; ništa se ne plaća bez pitanja.
- X objave samo iz share/novosti.json; novi unosi bez engleskih polja ne idu na X.
- UI tekstovi hrvatski; `.copy_wake` se nikad ne commita; puni suite: `python3 -m unittest discover -s tests`.
- Javno (svi igrači i posjetitelji) smije: statistika Autopilota, praćeni, ulazi/izlazi, adresa novčanika, chat.
  Ne smije: ključevi, env imena, interni servisi, troškovi, gumbi za trgovanje (ostaju admin-only).

## Faze

| # | Faza | Kako | Izlaz |
|---|---|---|---|
| 0 | Merge skupljenog u 00:45 (TP/SL po podacima, Što je novo, popravci Autopilota) | ručno, GitHub MCP | PR #76 |
| 1 | Razumijevanje i audit (01:10): sekundni poslovi, baze, Render, javne stranice, Autopilot stranica, izvori podataka i cijene, savjeti tradera | Workflow, paralelni čitači + protuprovjera | `audit/2026-11-10/*.md` |
| 2 | Odgovori na pitanja 1 i 2 (trošak, listener, 2 CPU) | iz faze 1 + web | u jutarnjem izvještaju |
| 3 | Dizajn: Autopilot stranica (graf, log, čisto), javna stranica + chat + traka, dnevno osvježavanje + dnevnik naslovnice, CPU čuvar | Workflow (više nacrta, suci) | `audit/2026-11-10/dizajn.md` |
| 4 | Implementacija po grupama datoteka (bez sudara), svaka: implementacija → protupregled → dorada | Workflow | commitovi na grani |
| 5 | Integracija: puni suite, lokalno pokretanje aplikacije, screenshotovi (Playwright), protupregled cijelog diffa | Workflow + ručno | zeleno stablo |
| 6 | Isporuke: prezentacija (artifact + mail), prijedlog profitabilnosti, audit podataka, prijedlozi UI-ja sa screenshotovima | artifact / mail | linkovi u izvještaju |
| 7 | Jedan PR, merge iza 06:00, provjera deploya na Renderu, jutarnji izvještaj | GitHub + Render MCP | PR #77 |

## Grupe datoteka za fazu 4 (vlasništvo, da se agenti ne sudaraju)

| grupa | datoteke | što |
|---|---|---|
| pogon | ops/*, start.sh, run_sched.py, kol/converge.py, event_calendar/http.py | sekundni poslovi bez punih čitanja, CPU čuvar (90–95 %), nadzor dostupnosti |
| novac-podaci | trade/*, run_trade.py, league/* | povijest vrijednosti walleta, uplate, SOL→USD/EUR, dnevnik odluka Autopilota (kupio / preskočio / zašto) |
| autopilot-ui | ui/pravitrade.py (+ testovi pravitrade) | graf na vrhu, log na klik, čista stranica, "Zovu sada" i "Što kupiti sada" na dno ili van |
| javno | nova ui/uzivo_javno.py (ili sl.), run_ui.py rute, ui/html.py traka, ui/landing.py isticanje | javna stranica Autopilota, chat s +1, traka "Autopilot je live" |
| web-dnevno | run_sched.py posao 02:00, ui/public*.py / ui/landing.py dnevnik "live N dana" | dnevno osvježavanje javnih tablica, dnevnik naslovnice |
| sentry | ops/sentry.py, točke hvatanja u run_ui.py i petljama | slanje grešaka u Sentry (stdlib), popravci onoga što Sentry/logovi pokažu |

Sudari: ui/landing.py dijele "javno" i "web-dnevno" → jedna grupa ("javno") drži landing, druga joj predaje nacrt.
run_ui.py dijele "pogon" (zaglavlje/HEAVY), "javno" (rute) → rute dodaje "javno", ostalo "pogon", redom, ne paralelno.

## Stanje (ažurirati nakon svake faze)

| faza | stanje | bilješka |
|---|---|---|
| 0 | GOTOVO | PR #76 spojen 00:44 CET (47723d9); grana vraćena na main; deploy provjeren u 00:5x |
| 1 | U TIJEKU od 01:10 | tri workflowa: audit koda (7 mapa + skeptik + praznine), web izvori i cijene, savjeti tradera (10 kutova) |
| 2 | čeka fazu 1 | |
| 3 | GOTOVO 01:00 | `audit/2026-11-10/dizajn.md`: ugovor između grupa (imena modula, funkcija, ključeva) |
| 4 | U TIJEKU od 01:11 | po jedan workflow po grupi u worktreeju `/home/user/wt/<grupa>` (grana `noc/<grupa>`): novac, apui, javno, pogon, web, sentry; svaki: implementacija → neovisni pregled → dorada |
| 5 | čeka fazu 4 | |
| 6 | čeka | prezentacija, prijedlog profitabilnosti, audit podataka, UI prijedlozi |
| 7 | čeka 06:00 | jedan PR, merge iza 06:00 (odobreno unaprijed) |

## Dnevnik noći (kratko, novije gore)

- 01:12 Pokrenuto 11 workflowa: audit koda, web izvori, savjeti tradera, 6 grupa implementacije (worktreeji `/home/user/wt/*`, grane `noc/*`), sadržaj prezentacije, prijedlozi sučelja. Popis ID-eva: scratchpad `NOC-STANJE.md`. Popravljen test topchecka koji je pao zbog datuma (fiksni 2.11.).
- 01:05 Sentry projekt `memesonar` stvoren (org serprise, de.sentry.io); DSN ide u env SENTRY_DSN na Renderu tik uz jutarnji merge.
- 01:03 Deploy #76 provjeren: minutna petlja radi s novim kodom ("minute: 30 tokena, 56 poziva… još 4591 tokena čeka"), bez Tracebacka, CPU vrh 27 %.
- 01:00 Worktreeji po grupama otvoreni; skripte workflowa u scratchpadu `wf/` (audit_koda, web_izvori, trgovci, impl, ui_prijedlozi).
- 00:44 PR #76 spojen. Sentry: org `serprise` (de.sentry.io) bez projekata i grešaka.
- 00:36 Zakazani osigurači: 01:12 i 03:30 (nastavi ako je stalo), 06:40 (jutarnja provjera).
