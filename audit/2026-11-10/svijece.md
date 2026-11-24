# Minutne svijeće: odakle, koliko zahtjeva, po kojoj cijeni (audit 10.11.2026.)

**Izravan odgovor.** Minutne svijeće već imamo (GeckoTerminal, besplatno). Ne nedostaje izvor, nego propusnost i
obuhvat: besplatni limit bez ključa dijeli 8 naših modula i IP adresa, pa red od ~4.600 tokena stoji, a kupnje
novčanika se po minutama uopće ne mjere. Najjeftiniji pouzdan put:
1. **0 $:** besplatni CoinGecko Demo ključ samo za minutnu petlju (isti podaci i format, vlastiti limit 100/min,
   10.000 poziva/mj) → zadnjih 14 dana zaostatka gotovo za ~2 h; uz to brojanje GeckoTerminal poziva po poslu.
2. **35 $/mj** (29 $/mj uz godišnju naplatu), tek ako 7 dana brojanja potvrdi potrebu: CoinGecko **Basic**
   (100.000 poziva/mj, 300/min). Pokriva pozive + kupnje novčanika + cijeli zaostatak u prvom mjesecu.
3. Sve ostalo ostaje besplatno; Birdeye/Solana Tracker samo ako se pokaže da sekunde mijenjaju rezultat.

**Ograda o izvorima:** WebFetch je u ovoj sesiji blokiran za sve službene stranice (coingecko.com, bds.birdeye.so,
dexpaprika.com, docs.solanatracker.io nisu u dopuštenim domenama). SVE cijene i limiti dolje viđeni su **samo u
sažetku pretrage 10.11.2026.**; prije plaćanja pogledati plan na samoj stranici/checkoutu.

## 1. Što imamo danas (Provjereno, iz koda)

| Dio | Izvor i rezolucija | Što mjeri | Ograničenje |
|---|---|---|---|
| `kol/minute.py` (proces `run_kol.py minute-loop`, baza `minute.db`) | GeckoTerminal `/pools/{pool}/ohlcv/minute`, aggregate=1, do 1000 svijeća po zahtjevu (16,7 h), USD, bez ključa | Samo X/Telegram pozive (`kind='call'`, bez botova, MC ≥ 30k). Ulaz = zatvaranje minute objave (`lag_s`), pa 60 min: hi15/30/60, lo60, r60, prva minuta +5/10/15/20/30 % i stopa −20 % | `handle NOT LIKE 'w:%'`: kupnje novčanika isključene. Poziv se mjeri kad je star 70 min. Jedan zahtjev pokriva pozive tokena unutar 14 h. 404 = `bad 'pool'`, bez svijeće u 5 min = `bad 'svijeca'` |
| `minute.db` tablica `call_lv` | ista svijeća | JSON `{"u":{5,10,15,20,30,40,50,75,100}, "d":{10,15,20,25,30,40,50}}` = prva minuta (1–60) dodira svake razine; gore na fitilju ograničenom na 3× tijela, dolje na lowu; `x` = ponovno mjerenje nije uspjelo | Čuva se 30 dana. Same svijeće, volumen i cijena PRIJE poziva se ne spremaju (petlja ih skida: 10 min prije prvog poziva, stupac volumena) |
| `kol/measure.py` | GeckoTerminal, 5-min svijeće (aggregate=5), 2 h prije do 24 h poslije | p0, pre2h, r1h/r6h/r24h, max24, vol_lift; kontrolne točke 1/6/24 h | Ulaz 3–7 min prije poziva (DNEVNIK 9.11.); `w:` i `buy/sell/bot` isključeni |
| `learn/masovno.py` (sjenovita knjiga) | GeckoTerminal 5-min, 24 h, 2 poziva po tokenu | Točke `kol_poziv`, `novcanik_kupio` (prva kupnja praćenog novčanika u danu), bondao, trending, kontrola; 5 varijanti izlaza | 150 poziva po prolazu danju / 400 noću (svakih 30 min) = do ~10.000 GT poziva/dan (bilješka u `learn/config.json`), najveći potrošač istog limita |
| Demo tickovi (`paper.db ticks`) | DexScreener, vlastiti tick svake minute (cijena, likvidnost, MC) | Samo tokeni koje demo prati 24 h i otvorene pozicije | Snimka, ne OHLC; netrgovani tokeni brišu se nakon 4 dana |
| Swap tok | Helius webhook → `hype.db chain_trades (sig, wallet, mint, side, ts, sol)`; PumpPortal → `live_trades` (ima `price_sol`, 48 h) | Tko je kupio/prodao i kada | `chain_trades` ne sprema količinu tokena (cijena kupnje se baca, prodaje bez SOL iznosa), čuva 14 dana. PumpPortal feed trenutno odbija (ključ ispod 0,02 SOL) |

Zajednički limit (`event_calendar/http.py`): razmak 3,5 s za sve procese (~17/min), pauza 60 s nakon 429 i 300 s nakon
403, `reserve()` daje host jednom poslu. Isti host zovu: `kol/measure`, `kol/minute`, `learn/masovno`, `kol/trending`,
`kol/graduates`, `hype/tokenstatus`, `dugo/sources`, `retro/collect`. GeckoTerminal pozivi se NE broje u `usage.db`
(`usage/meter.py` nema taj servis).

Izmjereno: 9.11. navečer 1.265 poziva izmjereno, 35.834 čeka na 4.603 tokena, 31–69 tokena po prolazu od ~10 min
(DNEVNIK, večer); 10.11. 01:03 "30 tokena, 56 poziva… još 4591 tokena čeka" (NOCNI-PROGRAM). Između ta dva zapisa
red je pao s 4.603 na 4.591 tokena (novi pozivi stižu usput, deployi prekidaju petlju): procjena "gotovo za ~22 h" ne drži.

## 2. Izvori 1-min (ili finijih) svijeća za Solana DEX poolove

Stupac "Status": **službeno** = službena stranica u sažetku pretrage; **nepotvrđeno** = stranica starija od 2026.,
treća strana ili se službene stranice međusobno razilaze. Brojevi u [ ] = popis izvora na dnu.

| Izvor | Rezolucija | Cijena (USD/mj) | Limit | Dubina | Po zahtjevu / batch | Status |
|---|---|---|---|---|---|---|
| GeckoTerminal bez ključa (danas) | 1 min (i 5/15) | 0 | FAQ: 30/min [1]; novija CoinGecko stranica: ~5/min, dijeli se po IP-u, "nije za produkciju ni zakazano čitanje" [2]; dex-api stranica spominje 10/min [3] | 6 mj [4] | do 1000 svijeća [5]; batch OHLCV ne postoji | službene stranice se razilaze → limit **nepotvrđen**; naša mjera 1–3,5 zahtjeva/min za petlju |
| CoinGecko **Demo** ključ | 1 min, samo po poolu | 0 | 100/min (od 17.5.2026., prije 30) [6]; 10.000 poziva/mj [7] | 6 mj [4] | isti endpoint pod `/onchain`, zaglavlje ključa, host api.coingecko.com | službeno; uvjeti (atribucija, komercijalna uporaba) nisu provjereni |
| CoinGecko **Basic** | 1 min | 35 (29 uz godišnju naplatu) [7] | 300/min (17.5.2026.: 250→300) [6]; 100.000 poziva/mj; prekoračenje 0,0005 $/poziv [7] | 6 mj [4] | 1 poziv = 1 kredit, do 1000 svijeća | službeno |
| CoinGecko Analyst | 1 s, 1 min | 129 [7] | 500/min, 500.000/mj | od 2021. [4] | isto | službeno |
| CoinGecko Lite / Pro | 1 s, 1 min | 499 / 999 [7] | 500 / 1000 po min; 2M / 5M poziva | od 2021. | isto | nepotvrđeno (sažetak kaže da je kopija stranice možda stara) |
| Birdeye Lite | 1 s, 15 s, 30 s, 1 min | 39; prekoračenje 15 $/1M CU, najviše 7,5M CU [8] | 15 rps; 2,5M CU/mj | 1 s do 2 tjedna, 15/30 s do 3 mj [10] | OHLCV v3: ≤1000 svijeća 60 CU, ≤2000 90 CU, ≤5000 120 CU [9] → 41.600 zahtjeva/mj | plan službeno; zadržavanje i pojedinačni limiti nepotvrđeni (stranice iz 2025.) |
| Birdeye Starter / Premium | isto | 99 / 199 [8] | 15 / 50 rps; 8M / 20M CU; WebSocket od Premium | isto | 133.000 / 333.000 zahtjeva po 60 CU | službeno |
| Birdeye Standard (besplatno) | ? | 0 | 30.000 CU/mj, 1 rps [11] = ~500 zahtjeva | ? | ? | nepotvrđeno (članak star ~18 mj) |
| DexPaprika besplatni ključ | od 10 min naviše | 0 | 30/min, 100.000 kredita / 30 dana [12] | 7 dana | – | službeno; **1 min nije u besplatnom** |
| DexPaprika **Dev** | 1 min | 30 [12] | 120/min, 500.000 kredita/mj, prekoračenje 20 $/1M | 30 dana | najviše 366 svijeća po zahtjevu [13] | plan službeno; 366 nepotvrđeno (druga stranica kaže 100) |
| DexPaprika Pro | 1 min | 99 [14] | 500/min, 5M zahtjeva | neograničeno | isto | cijena nepotvrđena (viđena samo na podstranici) |
| Solana Tracker Free | 1 s do 1 mj | 0 | 2.500 zahtjeva/mj [15] | ? | `/chart/{token}/{pool}`, time_from/time_to; limit svijeća nije dokumentiran [16] | službeno |
| Solana Tracker Advanced / Pro | 1 s do 1 mj | 50 € / 200 € (≈ 55–60 $ / 220–240 $, tečaj nije provjeren) [15] | 200.000 / 1M zahtjeva/mj, bez limita po sekundi | ? | isto | službeno; dubina povijesti nepotvrđena |
| Moralis Starter / Pro | 1 min | 149 / 249 [17] | 2M / 100M CU; OHLCV 150 CU [18] = 13.300 / 666.000 zahtjeva | ? | po paru | službeno |
| Codex.io Growth | 1 s do 7 d | 360 [19] | 3M CU, 300 rps | ispod minute samo zadnja 24 h [20] | 1500 točaka po zahtjevu | službeno; CU po getBars nije nađen |
| Bitquery Personal / Pro / Scale | OHLC iz tradeova (GraphQL, više tokena u jednom upitu) | 49 / 99 / 299 (29/69/199 godišnje) [21] | 30 / 90 / 240 po min; 100k / 1M / 5M bodova | **povijest nije u samouslužnim planovima** [21] | bodovi po upitu nepoznati | nepotvrđeno za naš slučaj |
| Mobula Start-up / Growth | svijeće po paru | 50 / 400 [22] | 125k / 1,25M kredita; OHLCV 5 kredita = 25.000 / 250.000 zahtjeva | ? | ? | službeno; vijest o preuzimanju (treća strana) nepotvrđena |
| Vybe Developer | svijeće (REST i WS) | 49 [23] | 500/min, 500.000 kredita | ? | krediti po OHLC pozivu nisu nađeni | službeno, nepotpuno |
| Dune | SQL nad `dex_solana.trades` (bulk: sve svijeće jednim upitom) | Free = samo gledanje, bez API-ja; proba 2.500 kredita / 14 dana [24]; Analyst 65–75 | – | puna | izvoz se plaća po MB | cijena nepotvrđena (treće strane); trošak upita treba izmjeriti na probi |
| Flipside | SQL | ? | 500 "query seconds"/mj [25] | ? | ? | nepotvrđeno (stranica stara ~2 god.) |
| DexScreener | nema povijesti ni svijeća | 0 | 300/min parovi, 60/min profili [26] | – | 30 tokena po zahtjevu (trenutna cijena) | Provjereno u našem klijentu (pokriva sve endpointe) |
| Helius (već plaćamo, Developer 49 $, 10M kredita) | nema OHLCV; svijeće se slažu iz swapova | u planu; prekoračenje 5 $/1M [27] | `getTransactionsForAddress` 10 kredita / 100 punih transakcija; Enhanced parse 100/poziv; webhook 1 kredit/događaj [27] | cijeli lanac | – | službeno (sažetak) |
| PumpPortal | svaki trade (pump.fun + PumpSwap), uživo | 0,01 SOL / 10.000 događaja; ključ s ≥ 0,02 SOL [28] | – | nema povijesti | – | službeno; poklapa se s `live/pumpportal.py` |
| Jupiter Price API / Pyth | nije za male memecoine ni povijest po poolu | – | – | – | – | nije potvrđeno pretragom (Pretpostavka) |

## 3. Koliko nam treba

| Veličina | Vrijednost | Odakle |
|---|---|---|
| Pozivi u prozoru 30 dana | 37.099 na 4.603 tokena (8,1 poziva po tokenu) | DNEVNIK 9.11. (Provjereno) |
| Poziva dnevno | ~1.237 (≈ 52 na sat) | 37.099 / 30 |
| Poziva po jednom zahtjevu | 1,87 | prolaz 10.11. 01:03: 56 poziva / 30 tokena (jedan uzorak) |
| Zahtjeva za zaostatak poziva | 4.600 (donja granica, 1 po tokenu) do ~19.200 (35.834 / 1,87) | računica; samo zadnjih 14 dana ≈ pola |
| Zahtjeva uživo, pozivi | 660–1.237 na dan = 20.000–37.000 na mjesec (0,5–0,9 po minuti) | 1 zahtjev po pozivu je gornja granica |
| Kupnje novčanika za mjerenje | 200–1.000 na dan = 6.000–30.000 na mjesec | **Pretpostavka**: ~100 webhook novčanika, 1–2k događaja/dan (`kol/chainwatch.py`), pola su kupnje, dio ispod 30k/nebondan; ~48 dokazanih ≈ pola toga. Lokalna baza je prazna, broj treba očitati na serveru |
| Zaostatak kupnji | 2.800–14.000 | `chain_trades` čuva 14 dana |
| **Ukupno uživo (pozivi + kupnje)** | **860–2.240 zahtjeva/dan = 26.000–67.000/mj = 0,6–1,6 po minuti** | 60 svijeća po događaju = 52–134 tisuće svijeća dnevno |
| Jednokratno (zaostatak) | 7.400–33.000 zahtjeva | pozivi + kupnje |

Zaključak iz brojki: uživo treba najviše ~1,6 zahtjeva u minuti, a `learn/masovno` smije tražiti do ~7 u minuti od istog limita.
Problem je raspodjela besplatnog limita i jednokratni zaostatak, ne količina podataka.

## 4. Trošak po opciji za taj teret

| Opcija | USD/mj | (a) zaostatak u jednom danu | (b) pozivi uživo | (c) + kupnje novčanika | Rad u kodu |
|---|---|---|---|---|---|
| GeckoTerminal bez ključa (danas) | 0 | ne: 22 h u najboljem slučaju (4.600 po 3,5/min), do 13 dana (19.200 po 1/min) | da, ako petlja stalno dobiva ≥ 0,9/min | na rubu (treba 1,6/min, izmjereno 1–3,5) | 0 |
| + CoinGecko Demo ključ za minutnu petlju | 0 | 10.000 zahtjeva u 100 min: cijeli zaostatak ako je ≤ 10k, sigurno zadnjih 14 dana; ostatak ide starim putem | bez ključa + 333/dan s ključem | na rubu | malo: drugi host i zaglavlje, razmak 0,7 s, tvrdi brojač 9.500/mj |
| **CoinGecko Basic** | **35** (29 godišnje) | da: 19.200 zahtjeva u 64 min | da | da: 67k + zaostatak 19k < 100k; višak 5 $ na 10.000 poziva | isto kao Demo (drugi ključ) |
| DexPaprika Dev | 30 | da (ako je 366 svijeća po zahtjevu: 10–25k zahtjeva, do 3,5 h) | da | da (500k kredita) | novi klijent; povijest točno 30 dana (bez rezerve); pokrivenost malih PumpSwap poolova nije provjerena |
| Birdeye Lite | 39; 62 pri 67k zahtjeva | da (≤ 1,2M CU) | da (≤ 2,2M CU) | do 41.600 zahtjeva u planu, iznad toga 15 $/1M CU | novi klijent; daje 15-s svijeće |
| Birdeye Starter | 99 | da | da | da (133k zahtjeva) | novi klijent |
| Solana Tracker Advanced | ≈ 55–60 (50 €) | da | da | da (200k zahtjeva) | novi klijent; 1-s svijeće |
| Mobula Start-up | 50 | na rubu (25k zahtjeva/mj ukupno) | na rubu | ne | novi klijent |
| Moralis Starter | 149 | ne (13.300 zahtjeva/mj) | ne | ne | – |
| Codex Growth | 360 | – | – | – | preskupo za ovo |
| Bitquery Pro | 99 | ne (povijest nije u planu) | nepoznato | nepoznato | GraphQL |
| Helius: svijeće iz swapova | 1,3–34M kredita/mj povrh današnje potrošnje (500–5.000 swapova po token-satu); iznad 10M plana 5 $/1M, tj. do ~120 $ | ne: 5+ GB JSON-a dnevno na 1 CPU | ne | ne | velik; isplati se samo za desetak odabranih događaja dnevno (~0,3M kredita/mj) |
| PumpPortal: svaki trade | 0,6–6,2 SOL **na dan** za sve pozive; strop 20.000 tradeova/dan = 0,6 SOL/mj (≈ 54 $ po tečaju iz `live/pumpportal.py`) | nema povijesti | ne | ne | postoji |
| Vlastiti tickovi s DexScreenera svakih 15 s, 60 min nakon događaja | 0 (8–12 zahtjeva/min od 300) | nema povijesti | da (dopuna, ne zamjena svijeća) | da | malo: kao demo tickovi |

## 5. Preporuka

**Redoslijed (jeftinije prvo, mjerenje prije troška):**

1. **Odmah, 0 $.**
   - CoinGecko Demo ključ samo za `kol/minute.py`: zaostatak redom ekipe → zadnjih 14 dana (vruća lista gleda 14 dana) → ostatak; pustiti u noćnom prozoru 01–06 CET.
   - Brojati GeckoTerminal pozive po poslu u `usage.db` (danas se ne broje) i 429 po satu: to je podatak za odluku u točki 2.
   - Kupnje dokazanih (~48) i praćenih novčanika u isti red: prva kupnja po (novčanik, token, dan), samo bondani i MC ≥ 30k, jedan zahtjev po tokenu zajedno s pozivima tog tokena.
   - Iz podataka koje već skidamo, a bacamo: volumen po minuti (1/5/15 min nakon naspram 10 min prije) i cijena minutu prije poziva = izravna mjera utjecaja. Bez ijednog novog poziva.
   - U `chain_trades` spremiti količinu tokena iz webhooka (već plaćen događaj) = točna cijena po kojoj je novčanik kupio.
2. **Nakon 7 dana brojanja:** ako petlja treba više od ~330 poziva s ključem dnevno (očekivano 860–2.240), uzeti
   **CoinGecko Basic, 35 $/mj mjesečno** (ne godišnje dok se ne dokaže korist). Isti podaci kao dosad, pa stara i
   nova mjerenja ostaju usporediva. Otkazati ako brojanje pokaže manje od 10.000/mj.
3. **Finije od minute tek uz dokaz.** Besplatan test na postojećim podacima: pogodak +10 % po razredima `lag_s`
   (0–15, 15–30, 30–45, 45–60 s). Ako se razlikuje, vlastiti 15-s tickovi s DexScreenera (0 $) za vruću listu; ako
   treba prava svijeća ispod minute: Birdeye Lite 39 $ (15 s) ili Solana Tracker Advanced 50 € (1 s).
4. **Ne kupovati za ovo:** Codex, Moralis, Mobula, Bitquery, Dune, slaganje svijeća iz Heliusa ili PumpPortala.

**Ostaje besplatno:** GeckoTerminal bez ključa za 5-min svijeće (`kol/measure`, `learn/masovno`, trending, bondani),
DexScreener (žive cijene, pool, tickovi), CoinGecko Demo, Helius webhook u postojećem planu, RugCheck, Telegram.

**Ušteda bez troška koju treba izmjeriti (Pretpostavka):** isti pozvani token danas skidaju tri posla zasebno
(minute 1 min, measure 5 min u 3 kontrolne točke, masovno 2 poziva); zajednička predmemorija svijeća po poolu
mogla bi prepoloviti GT pozive. Brojanje iz točke 1 pokazat će isplati li se.

## Provjereno / Pretpostavka

- **Provjereno (kod i dnevnici):** sve u odjeljku 1; brojke 37.099 / 4.603 / 4.591; `w:` isključeni; GT pozivi se ne broje; `chain_trades` bez količine tokena i 14 dana.
- **Provjereno samo u sažetku pretrage (10.11.2026.):** sve cijene i limiti u odjeljku 2.
- **Pretpostavka:** broj kupnji novčanika dnevno; broj zahtjeva po tokenu u zaostatku (1,87 poziva po zahtjevu je jedan uzorak); da Render dijeli izlazni IP s drugim korisnicima pa nam oni troše limit bez ključa; da Demo ključ prima `limit=1000` kao javni endpoint (provjera = jedan poziv); EUR/USD.
- **Nepotvrđeno:** stvarni limit GeckoTerminala bez ključa (30, 10 ili ~5 u minuti); Birdeye besplatni plan i zadržavanje svijeća ispod minute; DexPaprika 366 svijeća po zahtjevu i cijena Pro; Bitquery za povijest; Dune/Flipside cijene; Jupiter/Pyth.

## Izvori (svi viđeni 10.11.2026., sažetak pretrage)

1. https://apiguide.geckoterminal.com/faq
2. https://docs.coingecko.com/docs/keyless-public-api
3. https://www.geckoterminal.com/dex-api
4. https://docs.coingecko.com/changelog (1 s i povijest starija od 6 mj samo Analyst i više)
5. https://docs.coingecko.com/reference/pool-ohlcv-contract-address , https://apiguide.geckoterminal.com/llms-full.txt
6. https://docs.coingecko.com/changelog (17.5.2026.), https://docs.coingecko.com/docs/errors-and-rate-limits
7. https://www.coingecko.com/en/api/pricing
8. https://bds.birdeye.so/pricing
9. https://docs.birdeye.so/reference/dynamic-compute-unit-cost , https://docs.birdeye.so/docs/compute-unit-cost
10. https://data.birdeye.so/docs/changelog/new-ohlcv-endpoints-on-solana , https://docs.birdeye.so/docs/per-api-rate-limit
11. https://bds-support.birdeye.so/hc/en-us/articles/46936561906073-Your-Complete-Guide-to-Account-Creation
12. https://dexpaprika.com/api/pricing , https://docs.dexpaprika.com/knowledge-base/rate-limits
13. https://docs.dexpaprika.com/tutorials/retrieve-historical-data
14. https://dexpaprika.com/api/solana
15. https://docs.solanatracker.io/pricing , https://www.solanatracker.io/data-api
16. https://docs.solanatracker.io/data-api/chart/get-ohlcv-data-for-a-token , https://www.solanatracker.io/resources/solana-token-ohlcv-chart-api
17. https://moralis.com/pricing/ , https://docs.moralis.com/get-started/pricing
18. https://docs.moralis.com/data-api/solana/price/ohlc
19. https://www.codex.io/pricing
20. https://docs.codex.io/api-reference/queries/getbars
21. https://bitquery.io/pricing , https://docs.bitquery.io/docs/ide/points/
22. https://docs.mobula.io/pricing
23. https://docs.vybenetwork.com/docs/plans-rate-limits
24. https://docs.dune.com/learning/how-tos/credit-system , https://docs.dune.com/api-reference/overview/billing
25. https://docs.flipsidecrypto.xyz/data/data-products/api-sdk-developers/getting-started
26. https://docs.dexscreener.com/api/reference
27. https://www.helius.dev/pricing , https://www.helius.dev/docs/agents/overview
28. https://pumpportal.fun/data-api/real-time/

## Provjera cijena

(druga provjera, 10.11.2026.)

**Izravan odgovor.** Cijene i limiti dobavljača NISU ponovno viđeni: zajednički budžet pretrage (200 po krugu) bio je
potrošen prije mog prvog upita (0 izvršenih pretraga), a WebFetch ne dopire do `www.coingecko.com` ni
`docs.coingecko.com` (domene nisu dopuštene u mrežnim postavkama sesije; nakon dva odbijanja nisam išao dalje ni
zaobilazio). Zato nijedna cijena nije ni potvrđena ni ispravljena: 11 od 12 opcija ostaje **nepotvrđeno** (jedini trag
je sažetak pretrage prvog prolaza), PumpPortal je potvrđen vlastitim troškom. Iz repozitorija: tvrdnje o kodu su točne
(4 napomene), računica je točna uz 5 ispravaka. Redoslijed preporuke ostaje; 3 dopune na dnu.

### Opcije

| Opcija | Presuda | Provjereno danas (repozitorij, vlastiti trag) | Nije viđeno na stranici dobavljača |
|---|---|---|---|
| GeckoTerminal bez ključa | nepotvrđeno | 0 $ i do 1000 svijeća po zahtjevu rade u produkciji (`kol/minute.py:111-115`, `kol/measure.py:98-102`). Vlastiti trag 9.11.2026.: pri razmaku 2,5 s (24/min) stizali su 429 (`event_calendar/http.py:36-38`, `:134-135`), dakle stvarni limit na Renderovom izlazu je ispod 24/min | službeni limit (30, 10 ili ~5/min), 6 mj povijesti |
| CoinGecko Demo | nepotvrđeno | U kodu nema ključa ni zaglavlja (grep `x-cg`, `COINGECKO_API`: ništa) | 100/min od 17.5.2026. (prije 30), 10.000/mj, je li onchain OHLCV u Demo planu, prima li `limit=1000` |
| CoinGecko Basic | nepotvrđeno | ništa | 35 $/mj (29 godišnje), 100.000 poziva, 300/min, prekoračenje 0,0005 $ |
| DexPaprika Dev | nepotvrđeno | ništa | 30 $/mj, 500k kredita, 120/min, 30 dana, 366 ili 100 svijeća po zahtjevu, krediti po pozivu |
| Birdeye Lite / Starter | nepotvrđeno | samo naš stariji tekst "≈ $39-99 mjesečno" (`ui/koltest.py:193`, nije izvor) | 39 / 99 $, 2,5M / 8M CU, 60 CU do 1000 svijeća, 15 $/1M CU, zadržavanje 1 s i 15 s |
| Solana Tracker Advanced | nepotvrđeno | ništa | 50 €/mj, 200.000 zahtjeva, tečaj EUR/USD, svijeća po zahtjevu, dubina |
| Vlastiti tickovi s DexScreenera | nepotvrđeno (službeni limit) | Naš klijent: 300/min za tokene i parove, 30 adresa po zahtjevu (`dexscreener/client.py:3`, `:87`, `:204-208`); tablica tickova postoji (`paper/store.py:14-15`). Potreba je 8–16 zahtjeva/min (ne 8–12): 60–94 tokena u satu = 2–4 zahtjeva × 4 čitanja | limit 300/min na docs.dexscreener.com |
| Helius | nepotvrđeno (cijena) | 10M kredita/mj (`ui/glossary.py:702`). Naš brojač: 10 kredita na 100 punih transakcija, 100 po Enhanced pozivu, 1 po webhook događaju (`usage/meter.py:75`, `:88`, `:97`, `:115-121`, uz oznaku "approximate"). Količina tokena stiže u webhooku i baca se (`kol/chainwatch.py:213-233`, shema `:325-326`) | 49 $/mj, 5 $/1M iznad plana |
| PumpPortal | potvrđeno (vlastiti trag, ne stranica) | Poruka samog servisa "funded with at least 0.02 SOL" i naš trošak 6.11.2026.: ~45.000 tradeova/h potrošilo 0,1 SOL u dva sata = 0,01 SOL na 10.000 (`live/pumpportal.py:20-21`, `:26-29`, `:176-181`) | – |
| Moralis, Codex, Mobula, Vybe, Bitquery | nepotvrđeno | ništa | sve cijene i CU po OHLCV pozivu |
| Dune / Flipside | nepotvrđeno | ništa (i prvi prolaz ih vodi kao nepotvrđene) | cijena, API u Free planu |
| Jupiter Price API / Pyth | nepotvrđeno | ništa; ostaje Pretpostavka | – |

### Računica (ponovljena)

| Tvrdnja | Ponovljeni račun | Presuda |
|---|---|---|
| 37.099 poziva, 1.237/dan, 52/h, 1,87 poziva po zahtjevu, zaostatak 4.600–19.200 | 1.265 + 35.834 = 37.099; /30 = 1.237; 56/30 = 1,87; 35.834/1,87 = 19.197 | točno |
| "8,1 poziva po tokenu" | 4.603 je broj tokena koji ČEKAJU (35.834 poziva) → 7,8 | ispravljeno (bez posljedica) |
| Uživo 860–2.240/dan = 26–67 tis./mj = 0,6–1,6/min; jednokratno 7.400–33.000 | 660 + 200 i 1.237 + 1.000; ×30 = 25.800–67.110; /1440 = 0,60–1,55; 4.600 + 2.800 i 19.200 + 14.000 | točno |
| GT bez ključa: "naša mjera 1–3,5/min", zaostatak 22 h do 13 dana | DNEVNIK.md:80: 31–69 tokena po prolazu od ~10 min = 3,1–6,9/min; 22 h vrijedi za 3,5/min, najbolji slučaj je 11 h. "1/min" nije mjera ni u jednom zapisu. Stvarni neto pomak od 9.11. navečer do 10.11. 01:03 je 12 tokena (4.603 → 4.591) | ispravljeno; zaključak isti (red stoji) |
| Demo: 10.000 zahtjeva u 100 min, ~2 h za 14 dana, "+333/dan uživo" | 10.000/100 = 100 min; 9.600 × 0,7 s = 112 min. Ali to je ISTI mjesečni fond: zaostatak 14 dana troši 2.300–9.600 od 9.500, pa uživo ostaje 0–240/dan, ne 333 | ispravljeno |
| Basic: 19.200 u 64 min, "67k + 19k < 100k" | 19.200/300 = 64 min. S kupnjama novčanika gornja granica je 67.000 + 33.000 = 100.000 = cijeli fond, bez rezerve; višak 5 $ na 10.000 | ispravljeno (prvi mjesec na rubu) |
| Birdeye Lite 41.600 zahtjeva, 62 $ pri 67k; Starter 133k | 2,5M/60 = 41.667; 39 + 1,52M × 15 $ = 61,8 $; 8M/60 = 133.333. Prvi mjesec sa zaostatkom: 3,4–6,0M CU = 52–92 $ | točno; dodan prvi mjesec |
| Moralis 13.300, Mobula 25.000, DexPaprika do 3,5 h | 2M/150; 125k/5; 25.000/120 = 208 min | točno |
| Helius 1,3–34M kredita/mj, "do ~120 $", "desetak događaja ~0,3M" | 860 × 50 × 30 = 1,29M; 2.240 × 500 × 30 = 33,6M. 120 $ vrijedi samo ako je današnja potrošnja 0, inače do 170 $. Deset događaja = 0,015–0,15M | ispravljeno (zaključak "ne" isti) |
| PumpPortal 0,6–6,2 SOL/dan; strop 0,6 SOL/mj ≈ 54 $ | 1.237 × 500–5.000 tradeova × 0,01/10.000; 600.000 tradeova = 0,6 SOL; 90 $/SOL iz `live/pumpportal.py:28` (tečaj od 6.11., nije provjeren) | točno |
| masovno ~10.000 poziva/dan, ~7/min | 19 h × 2 × 150 + 5 h × 2 × 400 = 9.700; prosjek 6,7/min, ali noću 13,3/min od najviše ~17/min | točno; noću (01–06) uzima do 78 % limita bez ključa |

### Tvrdnje o kodu

| Tvrdnja | Gdje | Presuda |
|---|---|---|
| GT `/pools/{pool}/ohlcv/minute`, aggregate=1, do 1000, USD, bez ključa | `kol/minute.py:108-122`, `kol/measure.py:13` | točno |
| Samo pozivi, bez `w:` i botova, MC ≥ 30k, poziv star 70 min | `kol/minute.py:203-214`, `:43`, `:52` | točno |
| Jedan zahtjev pokriva 14 h; 10 min prije prvog poziva; volumen se skida, ne sprema | `kol/minute.py:232`, `:311`, `:109`, `:122`, shema `:59-68` | točno (docstring `:22-23` kaže 16 h, kod 14 h) |
| 404 = `pool`, bez svijeće u 5 min = `svijeca`; razine `call_lv`; `x`; 30 dana | `kol/minute.py:322-324`, `:133`, `:351-353`, `:49-50`, `:160-166`, `:69`, `:44`, `:368-369` | točno |
| measure: 5-min svijeće, 2 h prije do 24 h poslije, 1/6/24 h, bez `w:`/buy/sell/bot, ulaz prije poziva | `kol/measure.py:14`, `:101`, `:232-233`, `:179-188`, `:122`; DNEVNIK.md:71 | točno |
| masovno: 150/400 po prolazu svakih 30 min, 2 poziva po tokenu, 5 varijanti | `learn/config.json:67-69`, `run_sched.py:181`, `learn/masovno.py:244`, `:257`, `:31-37` | točno |
| Zajednički razmak 3,5 s, 60 s nakon 429, 300 s nakon 403, `reserve()` | `event_calendar/http.py:38-40`, `:78-131`, `:220-223` | točno; uz to razmak raste ×1,5 do 20 s nakon svakog 429 (`:134-145`) |
| Osam modula na istom hostu | `kol/measure.py:13`, `kol/minute.py:113`, `learn/masovno.py:244,257`, `kol/trending.py:14`, `kol/graduates.py:10`, `hype/tokenstatus.py:68-70`, `dugo/sources.py:18`, `retro/collect.py:214` | točno; deveti je `kol/sessions.backfill` (`run_kol.py:118`). `retro/collect.py:214-222` zove izravno, mimo zajedničkog razmaka (nije u start.sh ni run_sched.py) |
| GT pozivi se ne broje u `usage.db` | `usage/meter.py:40`: `record()` zovu samo anthropic, apify, helius, twitterapi (grep) | točno |
| `chain_trades (sig, wallet, mint, side, ts, sol)`, 14 dana, prodaje bez SOL; `live_trades` ima `price_sol`, 48 h | `kol/chainwatch.py:325-326`, `:49`, `:363`, `:230-233`; `live/store.py:9-11`, `:18` | točno |
| Demo tickovi: cijena, likvidnost, MC; netrgovani 4 dana | `paper/store.py:14-15`, `ops/prune.py:46` | točno |
| 1.265 / 35.834 / 4.603 / 4.591; vruća lista 14 dana | DNEVNIK.md:80; audit/2026-11-10-NOCNI-PROGRAM.md:99; `kol/minute.py:53` | točno |
| ~100 webhook novčanika, 1–2k događaja/dan; "~48 dokazanih" | `kol/chainwatch.py:4`, DNEVNIK.md:112 | 100 i 1–2k točno; broj 48 nisam našao u repozitoriju (nepotvrđeno) |

### Ispravak preporuke

Redoslijed ostaje (0 $ prvo, Basic tek nakon brojanja). Tri dopune:

1. **Demo ključ (točka 1).** U prvom mjesecu cijeli fond (10.000, tvrdi brojač 9.500) ide na zaostatak; ne računati na
   "333/dan uživo" u istom mjesecu. Prvi poziv neka provjeri `limit=1000` i zaglavlja limita. Krenuti s razmakom 0,7 s;
   na prvi 429 spustiti na 2,1 s (stari limit 30/min): tada zadnjih 14 dana traje 1,3–5,3 h (jedna do dvije noći)
   umjesto ~2 h. U kodu: petlja s ključem ne smije držati `http.reserve` za geckoterminal.com (`kol/minute.py:285-287`)
   niti čekati `measure._GT` (3,0 s; `kol/minute.py:112`, `kol/measure.py:30`), inače blokira ostale poslove odnosno
   radi najviše 20/min.
2. **Prag za Basic (točka 2).** Mjeriti brojem zahtjeva minutne petlje i 429 po satu u `usage.db` (potreba na dan
   naspram onoga što put bez ključa stvarno da), ne potrošnjom ključa: fond ključa je tada već potrošen na zaostatak.
   Zaostatak očistiti Demo ključem PRIJE Basica, pa Basic nosi samo živi teret (26–67 tis./mj od 100.000); sa
   zaostatkom i kupnjama novčanika prvi mjesec dolazi do ruba fonda (100.000).
3. **Plaćanje.** Ni u ovoj provjeri nijedna cijena nije viđena na stranici dobavljača. 35 $/mj vrijedi tek kad se vidi
   na checkoutu; ako Basic nije ≤ 39 $/mj ili nema 100.000 poziva, usporediti s DexPaprika Dev (30 $) i Birdeye Lite
   (39 $), koji traže novi klijent i novu provjeru podataka.

- **Provjereno (repozitorij, 10.11.2026.):** tablice "Tvrdnje o kodu" i "Računica"; PumpPortal cijena iz vlastitog troška 6.11.2026.
- **Nije provjereno:** sve cijene i limiti dobavljača (0 pretraga, 0 otvorenih stranica u ovoj provjeri).
- **Za dovršetak:** dopustiti coingecko.com i docs.coingecko.com (i domene ostalih dobavljača) u mrežnim postavkama
  sesije ili ponoviti provjeru s novim budžetom pretrage.
