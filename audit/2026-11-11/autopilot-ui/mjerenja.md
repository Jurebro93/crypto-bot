# Autopilot kao terminal: mjerenja prije / poslije (11.11.2026.)

**Sve brojke su s lokalnih seed podataka, ne s produkcije.** Aplikacija je pokrenuta lokalno (`run_ui.py` na 127.0.0.1,
bez mreže: `audit/2026-11-10/local/sitecustomize.py`), baze iz `audit/2026-11-10/seed_app.py` +
`audit/2026-11-11/autopilot-ui/seed_extra.py` (iste baze za obje strane). Na Renderu iza Cloudflarea TTFB i RTT su
veći nego na localhostu, pa će LCP u produkciji biti viši za vrijeme odgovora poslužitelja i jedan RTT; omjer
prije/poslije vrijedi, apsolutne brojke ne.

- **Prije**: `origin/main` ac30775 (stara stranica `/pravi-trade`).
- **Poslije**: grana `noc/autopilot-ui` (Lighthouse na a9a1302; kasniji commitovi mijenjaju samo SSE oslobađanje mjesta i
  simbol u zaglavlju, ne prvo učitavanje).
- Lighthouse 12.8.2, Chromium 153 headless, samo kategorija Performance, prijavljen vlasnik (Jure), 3 pokretanja po
  strani, medijan. Mobitel = zadani Lighthouse profil (Moto G Power, simulirani spori 4G: 150 ms RTT, 1,6 Mbit/s, CPU
  4x). Desktop = `--preset=desktop`. "Mobitel, primijenjeni 4G" = `--throttling-method=devtools` (stvarno usporena mreža
  i CPU), 2 pokretanja.

| | Prije | Poslije |
|---|---|---|
| Mobitel: Performance | 90 (88 / 93 / 90) | **99** (100 / 99 / 99) |
| Mobitel: LCP | 1,18 s | **1,11 s** |
| Mobitel: FCP | 0,95 s | 0,80 s |
| Mobitel: TBT | 272 ms | **93 ms** |
| Mobitel: CLS | 0,128 | **0** |
| Mobitel, primijenjeni 4G: Performance / LCP | 89 / 0,80 s | 99,5 / 0,90 s |
| Mobitel, primijenjeni 4G: TBT | 454 ms | 83 ms |
| Desktop: Performance | 100 | 100 |
| Desktop: LCP | 0,31 s | 0,37 s |
| Desktop: TBT / CLS | 8 ms / 0,046 | 0 ms / 0 |
| Preneseno pri prvom učitavanju | 136-140 KB | 74 KB |

Lighthouse je na staroj stranici svaki put javio "The page loaded too slowly to finish within the time limit" (njeni
1-sekundni pozivi nikad ne puste mrežu da se smiri); na novoj nijednom.

LCP element: prije tekst u kartici "Brza kupnja" / zaglavlju, poslije tekst ispod grafa. Graf (TradingView Lightweight
Charts, 51 KB gzip) i svijeće stižu nakon prvog iscrtavanja (`requestIdleCallback`), zato nisu u LCP-u ni u bajtovima
gore. Koliko do nacrtanog grafa: `lcp4g.js` (Playwright + CDP: 150 ms RTT, 1,6 Mbit/s, CPU 4x, prazan cache, 412x823):

| | Prije | Poslije |
|---|---|---|
| LCP (medijan 3) | 0,33 s | 0,43 s |
| događaj `load` | 0,95 s | 0,65 s |
| graf nacrtan (svijeće + linije + zone) | nema grafa tokena | **1,43 s** |

Veličine (gzip): HTML prvog prikaza 34 KB (prije 47 KB, isti podaci), `ap.js` 12 KB, graf 51 KB; oba statička su pod
`/pravi-trade/static/...?v=<hash>` s `Cache-Control: private, max-age=31536000, immutable`, pa drugi posjet skida
samo HTML.

## Memorija i SSE (isti lokalni poslužitelj)

- Isti posjet na obje strane (10 učitavanja stranice + svi dijelovi koje stranica dohvaća): RSS staroga 59 MB, novoga
  62 MB (start oba 35 MB).
- 7 istodobnih SSE veza: 6 dobije stream, 7. dobije 503 (preglednik onda svakih 5 s pita `/pravi-trade/api/tick`);
  RSS s 6 otvorenih streamova 61 MB (bez rasta). Zatvorena kartica oslobađa mjesto u par sekundi.

## Kako ponoviti

    UIPROP_ANYWHERE=1 python3 audit/2026-11-10/seed_app.py --reset
    python3 audit/2026-11-11/autopilot-ui/seed_extra.py --seed audit/2026-11-10/local/seed.json
    # run_ui.py s PYTHONPATH=audit/2026-11-10/local (kao audit/2026-11-10/run_local.sh), prijava Jure / demo
    NODE_PATH=/opt/node22/lib/node_modules node audit/2026-11-11/autopilot-ui/shots.js --base http://127.0.0.1:8790 --cookie 'cb_s=...' --prefix poslije
    NODE_PATH=/opt/node22/lib/node_modules node audit/2026-11-11/autopilot-ui/lcp4g.js --base http://127.0.0.1:8790 --cookie 'cb_s=...'
    npx lighthouse http://127.0.0.1:8790/pravi-trade --only-categories=performance --chrome-path /opt/pw-browsers/chromium \
      --chrome-flags="--headless=new --no-sandbox" --extra-headers '{"Cookie":"cb_s=..."}' [--preset=desktop]

Pojedinačna pokretanja: `lighthouse.json` u ovoj mapi. Snimke: `prije-{375,768,1440}.png` i `poslije-{375,768,1440}.png`
(cijela stranica, deviceScaleFactor 2; ljepljiva traka i zatvoreni panel su na snimkama `-prvi-ekran` i `-nalog`),
`*-shots.json`: bez vodoravnog skrola na sve tri širine (`scrollWidth <= innerWidth`).

## Otvaranje kartica (`<details>`), 11.11. popodne

Jure: „klikom na zatvorene kartice (npr. Postavke i dijagnostika) ne otvaraju se iz prvoga, kao da je lag”. Mjereno
`kartice.js` (Playwright, lokalni seed, isti poslužitelj): stranica se učita, pričeka 2,5 s, kartica se skrola na sredinu
ekrana, 0,4 s kasnije dodir (375 px, touch) ili klik (1440 px); vrijeme od `pointerdown` do vidljivo otvorene kartice i
do vidljivog sadržaja (bez kostura / „učitavam”), te je li kartica otvorena 1,2 s kasnije. `--cpu 4` = spori mobitel.

| | Prije | Poslije |
|---|---|---|
| Autopilot, „Postavke i dijagnostika”, 1440 / 375 | **ne otvori se iz prvog** (oboje) | 9 ms / 19 ms, sadržaj odmah |
| isto, CPU 4x | ne otvori se | 35 ms / 77 ms |
| Autopilot, kartice u „Što kupiti” / „Koga pratimo” | još nisu učitane kad se do njih dođe | 11–21 ms (CPU 4x: 27–52 ms) |
| Demo trading (/paper), 6 kartica, 1440 / 375 | 9–23 ms / 16–19 ms | 8–35 ms / 15–21 ms |
| isto, CPU 4x, najsporija („Zatvoreni trejdovi”) | 130 ms / 111 ms | 60 ms / 67 ms |
| Tokeni (/tokens), „Odbačeni” | 4–16 ms (CPU 4x: 25–30 ms) | 10–16 ms (CPU 4x: 29–37 ms) |
| Pregled, Novčanici | u ovoj verziji nemaju sklopljenih kartica (0 pronađenih) | – |

Uzrok na Autopilotu nije bio spor JavaScript nego pomak sadržaja: „Što kupiti” i „Koga pratimo” učitavali su se tek
300 px prije ulaska u ekran, pa su u trenutku dodira na „Postavke i dijagnostika” (ispod njih) narasli za ~540 px i
dodir je pao na prazno. Popravak: dijelovi se učitavaju 1200 px unaprijed i svi čim je stranica mirna nakon prvog
iscrtavanja; zatvorena kartica s lijenim sadržajem dohvati ga kad je blizu ekrana ili na dodir / prelazak mišem preko
naslova; dijelovi koji se osvježavaju nisu sidro skrola (`overflow-anchor:none`); otvorena kartica odmah piše
„Učitavam…”. Općenito (sve stranice, `ui/secnav.py`): trake sekcija se više ne preračunavaju 250 ms nakon SVAKOG
klika (mjerenje svih `<h2>`), nego samo kad se struktura stranice promijeni (MutationObserver, u mirnom trenutku);
straničenje tablica reagira samo na promjene tablica, ne na svaki tekst (sat „prije X s”, tooltip). Osvježavanje
dijela (PATCH_JS, `refreshFirst`) zadržava otvorene `<details>` i otvoren „Uredi SL-TP”.
Brojke: `kartice-prije.json`, `kartice-poslije.json`, `kartice-*-cpu4.json`.
