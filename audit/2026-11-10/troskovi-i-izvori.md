# Troškovi i izvori podataka: odgovori na Jurina pitanja 1, 2 i 12 (10.11.2026.)

Sinteza noćnih nalaza iz iste mape: `osluskivaci.md`, `svijece.md`, `hosting.md`, `sekundni.md`, `baze.md`. Kod nije mijenjan.

Oznake: **(prov.)** = provjereno u našem kodu, našim podacima ili Render API-ju; **(izvor)** = navedeni vanjski izvor, broj viđen
samo u sažetku web pretrage; **(pretp.)** = pretpostavka ili procjena; **nepotvrđeno** uz cijenu = stranica dobavljača nije otvorena.

**Ograda o cijenama.** Iz sandboxa se službene stranice nisu mogle otvoriti (WebFetch odbija helius.dev, twitterapi.io,
pumpportal.fun, coingecko.com, render.com, hetzner.com). Cijene dobavljača podataka viđene su samo u sažetku pretrage
10.11.2026.; druga provjera iste noći nije uspjela jer je zajednički budžet pretrage (200) bio potrošen. Cijene Rendera i
Hetznera su iz znanja modela, ni pretragom nisu viđene. **Sve "nepotvrđeno" treba pogledati na stranici ili checkoutu prije
plaćanja.** Provjerene su samo cijene zapisane u našem kodu: X timeline, PumpPortal, Apify xquik, Helius plan od 10 M kredita.

## Izravni odgovori

1. **Sekunde i listener.** Pingati svake sekunde ne isplati se ni za jedan izvor: 100 novčanika ≈ $1.295/mj, 100 X računa
   ≈ $2.700–3.900/mj, Telegram uopće ne ide (429) (pretp., račun iz cjenika, nepotvrđeno). **Listener već imamo i gotovo je
   besplatan:** Helius webhook javi svaku kupnju praćenog novčanika za 1 kredit po događaju, ≈ 0,45 % plana koji već plaćamo,
   $0 dodatno; do 1.000 novčanika mijenja se jedan broj (prov. kod, pretp. broj događaja). Telegram slušač (Telethon) je u kodu,
   $0, fali samo prijava brojem mobitela (prov.). Novac za sekunde traži samo X: Stream $29 (6 računa) ili $79 (20)
   (nepotvrđeno), i to tek kad mjerenje pokaže da kašnjenje X poziva od 0–30 s gubi pogotke.
2. **2 CPU-a: djelomično, i ne sada.** Trgovanju CPU već ne fali (lanac odluke troši milisekunde, ostalo je mreža). Skupljanje
   stoji na API limitima i na bravi "jedan težak posao", ne na CPU-u, a jedan Python proces ionako koristi najviše jednu jezgru
   (prov.). Gušenje od 9.11. riješio je jedan popravljen upit za $0. Razlika je ≈ +$60/mj (nepotvrđeno): prvo optimizacija
   ($0), 2 CPU tek kad se ispuni okidač iz točke (b).
3. **Minutne svijeće već imamo besplatno** (GeckoTerminal). Fali propusnost, ne izvor: oko 17 poziva/min dijeli 8–9 poslova,
   red od 4.591 tokena stoji, a kupnje novčanika se po minutama uopće ne mjere (prov.). Prvo besplatni CoinGecko Demo ključ samo
   za minutnu petlju i brojanje poziva; CoinGecko Basic $35/mj (nepotvrđeno) tek ako 7 dana brojanja pokaže potrebu.

## (a) Koliko bi koštalo sve svake sekunde i koji listener je jeftiniji

Današnja veličina: ~100 novčanika u webhooku, ~100 X računa u filter pravilima, 400 X računa u timelineu, ~30 Telegram
kanala na brzom čitanju (prov.).

| Izvor | Kako ga dobivamo danas | Trošak danas | Ping svake 1 s | Događaj / listener i cijena | Preporuka |
|---|---|---|---|---|---|
| Kupnje i prodaje novčanika | Helius webhook → `/hook/chain` → hype.db `chain_trades`, do 100 adresa (prov.) | u planu Developer $49/mj, 10 M kredita (prov. plan, cijena nepotvrđena); ~1–2 tisuće događaja dnevno (prov. docstring) | 259,2 M zahtjeva/mj ≈ $1.295/mj; 100 zahtj./s je iznad limita plana (50/s) (pretp., nepotvrđeno) | **to već je listener**: 1 kredit po događaju, 1.000 novčanika ≈ 4,5 % plana, $0 dodatno; Helius WSS tek na 10.000 novčanika, $0–8/mj (pretp.) | Ostati. Dodati vrijeme primitka (danas samo vrijeme bloka) i buditi kopiju samo za praćene/dokazane (prov. nalaz) |
| X pozivi, webhook | twitterapi.io filter pravila, oni provjeravaju svakih 30 s → `/hook/x` → kol.db `calls` (prov.) | **ne mjeri se** u usage.db (prov.); ≈ $91–130/mj ako se naplaćuje svaka provjera (izvor: blog dobavljača, nepotvrđeno), ≈ $27–39 ako vrijedi najmanji interval 100 s (pretp.) | ≈ $2.700–3.900/mj (pretp., nepotvrđeno) | Twitter Stream po računu: $29 (6), $79 (20), $299 (150), ≈ 500 ms (nepotvrđeno) | Prvo izmjeriti stvarnu potrošnju. Zatim brzi samo "novčani" računi (praćeni + vruća lista), ostali na 300 s (≈ $8–10/mj, pretp.) |
| X timeline | ping, 400 računa svakih 30 min, 10 po upitu (prov.) | strop 3,2 $/dan = do $96/mj (prov. kod) | isto kao gore | Stream za podskup | Izmjeriti koji računi u 14 d daju ijedan poziv; mrtve maknuti |
| Apify xquik monitor | webhook `/hook/kol`, 10 računa (isti su u X webhooku) (prov.) | ≈ $32/mj (prov. naš zapis $0,0045/račun/sat) | n/p | već je događaj | **Ugasiti (−$32/mj)** nakon što `/hook/x` počne pisati u `kol_mentions` (hype sken čita samo tu tablicu) (prov.) |
| Telegram | ping t.me/s, takt 3 s, do 8 čitanja po taktu (prov.) | $0 | 77,8 M zahtjeva/mj, neizvedivo: t.me vraća 429; danas "svake 2 s" stvarno znači ≥ 3 s, a uz 30 takvih kanala ≈ 46 s (prov.) | **Telethon (MTProto): $0**, kod postoji (`run_tg.py telethon`), fali `TG_SESSION`; u start.sh se pokreće bez `keep` (prov.) | Uključiti Telethon ($0). Treba broj mobitela i prijava `python3 run_tg.py login` na Jurinom računalu |
| Cijene tokena | DexScreener `tokens_live`, keš 3 s, 30 tokena po zahtjevu, 300/min po IP-u dijele svi procesi (prov.) | $0 | 2,6 M/mj, $0, ali limit puca iznad ≈ 150 tokena (pretp.) | PumpPortal ≈ $3,8/dan po vrućem tokenu; Helius WSS ≈ $0,05/dan po tokenu (pretp. račun) | Ostati; samo otvorene pozicije i ono što netko gleda. Gašenje niti bez gledatelja oslobađa do ~45 poziva/min (pretp.) |
| PumpPortal tok | 1 WebSocket; trgovine **ugašene**: ključ nema 0,02 SOL; migracije stižu besplatno (prov.) | 0 | n/p | 0,01 SOL na 10.000 trgovina; strop 20.000/dan ≈ 0,6 SOL/mj ≈ $52/mj (prov. naš trošak 6.11.) | Ne puniti za novčanike (duplikat Heliusa). 0,02 SOL tek ako mjerenje pokaže da sekunde cijene mijenjaju odluku |
| Minutne svijeće | GeckoTerminal bez ključa, ~17 poziva/min za sve (prov.) | $0 | n/p | n/p | vidi (c) |
| Rug provjera | topcheck: top 20 svake 3 min (RugCheck + Jupiter test prodaje) (prov.) | $0 | n/p | n/p | Ostaje |
| Pravi novac | `run_trade` čita trade.db i league.db svake 1 s, 5 punih prolaza tablica (prov.) | $0 (CPU 3,5 ms/s ≈ 0,35 %, sintetika) | već jest | `PRAGMA data_version` kao signal promjene (prov., testirano) | Indeksi + data_version: −88 % rada, reakcija ≤ 0,25 s (pretp. iz sintetike) |

Model "kupnja ili poziv u 1–3 s, najjeftinije" (pretp., nepotvrđene cijene): danas ≈ $37–89/mj novog troška (X Stream +
ostala pravila na 300 s), 10× veličina ≈ $376/mj, 100× ≈ $1.354–1.377/mj. Novčanici i Telegram ostaju $0 do 10×.

### Najjeftiniji put, redom

0. **Izmjeriti (0 $), prije ijednog plaćanja** (svi upiti postoje u kodu ili bazi, prov.):
   - twitterapi.io dashboard: stvarna dnevna potrošnja; iznad 3,2 $/dan razlika su provjere pravila. Plus `get_rules`
     (kod ga već zove, `kol/xhook.py:109`): koliko je pravila aktivno i koji `interval_seconds` je stvarno prihvaćen.
   - kol.db: `SELECT value FROM kv WHERE key IN ('xhook','xhook_count')` i koji X računi u 14 dana daju pozive
     (`SELECT handle, COUNT(*) FROM calls WHERE source='x_hook' AND ts >= strftime('%s','now','-14 day') GROUP BY 1`).
   - tg.db: `SELECT name, ROUND(lag_s) FROM channels WHERE lag_s IS NOT NULL ORDER BY lag_s DESC` (stvarno kašnjenje).
   - league.db: `SELECT action, COUNT(*), AVG(ts - ev_ts) FROM copy_log WHERE side='buy' GROUP BY 1` (sekunde od poziva do odluke).
   - usage.db: Helius webhook krediti; i **početi brojati GeckoTerminal i X pravila** (danas se ne broje).
1. **Telegram: Telethon ($0).** Ping od 2 s tada ne treba.
2. **Novčanici: ostati na Helius webhooku ($0).** Do 1.000 novčanika promjena `chain.max_wallets`.
3. **Ugasiti xquik (−$32/mj)** uz preduvjet iz tablice.
4. **X: sekunde platiti samo za račune pravog novca**, Stream $29 ili $79, i samo ako mjerenje kašnjenja (profitabilnost.md, E4)
   pokaže da 0–30 s gubi pogotke. Prije plaćanja otvoriti https://twitterapi.io/twitter-stream.
5. **Ne kupovati** gRPC (Helius Business $499, QuickNode $499, Shyft $199), Birdeye/Codex/Solana Tracker WebSocket ($199,
   $360, €397), Cielo API ($199) (sve nepotvrđeno): za cilj od 1–3 s ništa ne daju preko onoga što Helius daje za $49.

### Trošak po izvoru danas i što je donio (tjedno pravilo iz CLAUDE.md)

Izmjerene mjesečne potrošnje nema: lokalni usage.db ima 14 testnih redaka, produkcijski nije čitan (prov.). Zato stropovi:

| Izvor | $/mj | Izmjereno? | Donio odluku ili trade? |
|---|---|---|---|
| Helius Developer | 49 (plan) | plan (prov.), cijena nepotvrđena | da: jedini izvor s izmjerenom vještinom, "dokazani dvaput" novčanici (prov.) |
| X timeline (twitterapi.io) | do 96 (strop 3,2 $/dan) | strop (prov.) | da: hrani KOL pozive i pravi novac (DNEVNIK 9.11.) |
| X filter pravila | 27–130 | **ne** (pretp.) | da, isti izvor kao gore; trošak nevidljiv |
| Apify xquik | ≈ 32 | strop 1,1 $/dan (prov.) | ne: duplikat X webhooka |
| Apify gmgn | strop 1,7 $/dan; README ~7 | **ne** | nije izmjereno; "provjera vrijednosti" čeka od 8.11. |
| Render (1c-2g + disk) | ≈ 26 | nepotvrđeno (pretp.) | infrastruktura |
| Anthropic (AI oznake 2.000/dan, izvještaji) | nije izmjereno | ne | nije izmjereno |
| DexScreener, GeckoTerminal, Telegram, RugCheck, Jupiter, DefiLlama | 0 | prov. | da (cijene, minutna mjera, rug) |

Već srezano 7.–9.11. (prov., DNEVNIK): Apify pumpfun ugašen (−24 $/mj), discover 0,8 → 0,3 $/dan, reakcije na pozive
(twitterapi 0,8 $/dan) isključene, bodovanje novčanika 1.000/12.000 → 500/6.000 kredita svaka 3 h, AI oznake 12.000 →
2.000/dan, Insajderi i Ekipa zamrznuti, PumpPortal poruka 1× u 30 min.

## (b) Dva CPU-a: hoće li alat punom parom skupljati, analizirati i tradati?

**Odgovor: djelomično, i ne sada.** Brojke (prov., Render API i logovi 9.–10.11., `hosting.md`):

| Mjera | Prije PR #75 (9.11.) | Poslije #75 (127 min) |
|---|---|---|
| CPU ≥ 90 % | 35 % vremena (465 min, 20 epizoda, najdulja 50 min) | 0 minuta |
| CPU medijan / p95 / vrh | medijan 42 % | 18 % / 49 % / 72 % |
| KOL search krug | 1.193–2.809 s | 71–86 s |
| HTTP | 18,3 % odustalih (499), 12,6 % 502/503 | 96,9 % uspješnih bez deploya |

- **Što je jelo CPU:** jedan upit (`graph_candidates`, cijela tablica poziva za svaki redak grafa) i čitanja bez indeksa po
  vremenu. Popravljeno 9.11. za $0 (prov.).
- **Što danas ruši dostupnost:** deployi, ne CPU. 29 deploya 9.11., 659 odgovora 502/503 u satu deploya #76 uz CPU ispod 60 % (prov.).
- **Što 2 CPU-a NE popravljaju** (prov.): API limite (GeckoTerminal, DexScreener 300/min, Helius, twitterapi, Jupiter 429),
  GIL (sve niti `run_ui`, uključujući copy petlju i webhookove, dijele jednu jezgru na svakom planu), bravu teških poslova
  (jedan po jedan), jednog pisca po SQLite bazi, prekid pri deployu. Noćas je `run_dugo` držao bravu 21 min uz ≈ 10 % CPU-a,
  a 6 poslova čekalo je 12–22 min: to je brava, ne jezgra.

**Preostali sekundni otpad** (sintetika na kopijama baza; apsolutni udio na Renderu nije izmjeren, pretp.):

| Što | Trošak | Popravak (sekundni.md) |
|---|---|---|
| `prijedlog.chances()` bez keša, svake 2 s zauvijek i svake 1 s po pop-upu | 166 ms po čitanju, ≈ 7–8 % jezgre stalno | S1: keš 10 min ili zbroj u SQL-u |
| Pozadinske niti Autopilota i "zivo" nikad ne staju | ≈ 2 % + drže zivo živim, do ~45 DexScreener poziva/min | S3: stani nakon 30 s bez gledatelja |
| Pop-up tokena čita cijelu `token_tier` i `top_check` svake sekunde | ≈ 320 ms po osvježavanju ≈ 30 % jezgre po otvorenom pop-upu | S2: čitanje po ključu |
| 4 fragmenta u sekundi po gledatelju, i za zatvorene sekcije | 62.638 odgovora i 40.689 prekinutih u 24 h (prov., audit 9.11.) | S12: samo otvorene sekcije, jedan zahtjev |
| `run_trade` 5 punih prolaza tablica svake sekunde | 3,5 ms ≈ 0,35 % | S5: indeksi + `PRAGMA data_version` |

S1 + S2 + S3 skidaju ≈ 10 % CPU-a stalno i ≈ 30 % po otvorenom pop-upu (pretp., sintetika), trud mali, rizik nizak.

**Cijena** (pretp., znanje modela, nepotvrđeno; provjera: Render dashboard → Settings → Instance Type, 1 minuta):

| Opcija | $/mj | Napomena |
|---|---|---|
| A. Ostati na `1c-2g` + čuvar CPU-a (`ops/cpuguard.py`) + S1–S3 | +0 (danas ≈ 26) | teški poslovi mogu raditi 24 h s ostatkom do 90 %: ≈ 17 CPU-sati dnevno umjesto 5 (pretp., iz 2 h mjerenja) |
| B. Render `2c-4g` | ≈ 86 (+≈ 60, ≈ 720/god) | tip postoji (prov. Render API); u 127 min nakon #75 potražnja nijednom nije prešla 0,72 jezgre (prov.) |
| C. web + worker | ≈ 51 + Postgres | disk vidi samo jedan servis: selidba 24 baze, tjedni rada; ne sada |
| D. Hetzner VPS | ≈ 5–43 | sami radimo deploy, backup, TLS; privatni ključ na vlastitom serveru |

**Je li optimizacija bolji novac? Da** ($0 i skida izmjereni otpad). Uz to: upisati `/healthz` kao health check u Renderu
(danas prazno), uskladiti `render.yaml` (`plan: starter`) sa stvarnim planom, jedan skupni deploy dnevno (prov. nalazi).
2 CPU kupiti kad u 7 dana s čuvarom vrijedi **jedan** okidač (`hosting.md` §6): T1 čuvar pauzira pozadinu > 20 % dana u 3 od 7
dana; T2 noćni posao u 06:00 još radi u 2 od 7 noći, a držač brave troši > 70 % jezgre; T3 p95 `/healthz` > 1 s u > 1 % sondi
uz `cpu.pressure` > 20 %; T4 p95 "signal → demo ulaz" > 3 s u minutama s CPU ≥ 90 %. Sporost gradnji uz slobodan CPU (46–59 s
noćas) upućuje na RAM ili disk (baze 2,9 GB ne stanu u 2 GB keša) (pretp.): prvo izmjeriti `io.pressure`.

## (c) Kako doći do 1-minutnih svijeća

**Danas** (prov., `kol/minute.py`): GeckoTerminal `/pools/{pool}/ohlcv/minute`, do 1.000 svijeća po zahtjevu, bez ključa.
Mjere se samo X i Telegram pozivi (kupnje novčanika `w:` isključene), 60 min nakon objave, prva minuta dodira svake razine
(minute.db `call_path`, `call_lv`). Zajednički razmak 3,5 s ≈ 17 poziva/min dijeli 8–9 modula; `learn/masovno` sam traži do
~10.000 poziva dnevno, noću do 78 % limita. Red: 35.834 poziva na 4.603 tokena čekalo 9.11.; u 01:03 još 4.591 tokena: red stoji.
Volumen po minuti i cijena prije poziva skidaju se pa bacaju; `chain_trades` baca količinu tokena.

**Koliko treba** (pretp.): uživo 860–2.240 zahtjeva dnevno (pozivi + kupnje novčanika) = 26.000–67.000/mj ≈ 0,6–1,6 u
minuti; jednokratni zaostatak 7.400–33.000. Problem je raspodjela besplatnog limita, ne količina.

| Opcija | $/mj | Limit | Ograničenje | Status |
|---|---|---|---|---|
| GeckoTerminal bez ključa (danas) | 0 | službeno 30, 10 ili ~5/min (stranice se razilaze); kod nas 429 već na 24/min | dijeli se po IP-u i poslu | limit nepotvrđen; 429 prov. |
| **CoinGecko Demo ključ** | 0 | 100/min, 10.000 poziva/mj | prvi mjesec cijeli fond ide na zaostatak; uvjeti uporabe neprovjereni | nepotvrđeno |
| **CoinGecko Basic** | 35 (29 godišnje) | 300/min, 100.000/mj, višak $0,0005/poziv | prvi mjesec sa zaostatkom na rubu fonda | nepotvrđeno |
| DexPaprika Dev | 30 | 120/min, 500k kredita, 30 dana povijesti | besplatni plan nema 1 min; novi klijent | nepotvrđeno |
| Birdeye Lite | 39 | 2,5 M CU, 15-s svijeće | novi klijent | nepotvrđeno |
| Solana Tracker Free / Advanced | 0 / 50 € | 2.500 / 200.000 zahtjeva/mj, 1-s svijeće | Free premalen | nepotvrđeno |
| Vlastiti DexScreener tickovi svakih 15 s za vruću listu | 0 | 8–16 od 300/min | snimka, ne OHLC | prov. (klijent i tablica postoje) |
| Slaganje iz Helius swapova / PumpPortala | do ~$120–170 / do 0,6 SOL | – | 5+ GB JSON-a dnevno na 1 CPU | ne (pretp. račun) |

**Preporuka, redom:**
1. **Odmah, 0 $:** Demo ključ samo za `kol/minute.py`, noću 01–06 (ekipe → zadnjih 14 dana → ostatak); prvi poziv provjeri
   `limit=1000`, na prvi 429 razmak s 0,7 na 2,1 s. Petlja s ključem ne smije držati `http.reserve` za GeckoTerminal
   (`kol/minute.py:285-287`) ni čekati `measure._GT` (prov.). Uz to: brojati GT pozive po poslu i 429 po satu u usage.db;
   kupnje praćenih i dokazanih novčanika u isti red (prva kupnja po novčanik/token/dan, bondani, MC ≥ 30k); spremati volumen po
   minuti i cijenu prije poziva (0 novih poziva); red s prioritetom umjesto prepisivanja rezervacije (`baze.md` B3); popraviti
   B24 i B2 da masovna knjiga ne troši pozive na točke koje se odmah otpišu.
2. **Nakon 7 dana brojanja:** ako treba više od onoga što daju put bez ključa i Demo, CoinGecko Basic $35 **mjesečno**, ne
   godišnje; otkazati ako potrošnja padne ispod 10.000/mj. Ako na checkoutu nije ≤ $39 i 100.000 poziva, usporediti s DexPaprika
   Dev i Birdeye Lite.
3. **Finije od minute tek uz dokaz:** besplatni test pogotka po razredima `lag_s` (0–15, 15–30, 30–45, 45–60 s). Ako se
   razlikuju: vlastiti 15-s tickovi ($0); tek onda Birdeye Lite ($39) ili Solana Tracker Advanced (50 €).
4. **Ne kupovati za ovo:** Codex, Moralis, Mobula, Bitquery, Dune.

## Provjereno / Pretpostavka

**Provjereno:** sve tvrdnje o kodu (retci u izvornim datotekama); Render plan `1c-2g`, limit 1 CPU / 2 GiB, CPU, HTTP i deploy
brojke; naš trošak PumpPortala 6.11.; stropovi u kodu (X timeline, xquik, Helius plan); stanje reda minutne petlje.
**Pretpostavka:** sve cijene dobavljača i hostinga (nepotvrđeno, vidi ogradu); broj događaja po novčaniku (15 dnevno); broj
kupnji novčanika za mjerenje; da twitterapi.io naplaćuje svaku provjeru pravila; CPU udjeli na Renderu po petlji (mjereno
sintetički); 17 CPU-sati dnevno s čuvarom (iz 2 h); uzrok sporih gradnji uz slobodan CPU.
