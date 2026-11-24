# Osluškivači: što već stiže samo, što pingamo, koliko košta 10× i 100× (10.11.2026.)

**Odgovor:** Pingati "svake sekunde" ne isplati se ni za jedan izvor. Za novčanike i Telegram signal je (gotovo) besplatan i kod ga već ima: Helius webhook (u planu od $49, do 100.000 adresa po webhooku) i Telethon sesija (fali samo `TG_SESSION`). Sekunde stvarno koštaju samo na X-u: oko $1–5 po računu mjesečno. Najjeftiniji put danas: +$29–79/mj za X stream "novčanih" računa, uz vjerojatno veću uštedu na današnjim X pravilima koja se ne mjere.

Sve cijene viđene 10.11.2026. u sažetku web pretrage (WebFetch je ovdje blokiran, stranice nisam otvarao). "nepotvrđeno" = blog treće strane, izvor stariji od 2026. ili izvori koji se ne slažu.

## 1. Ping protiv događaja, današnja veličina (100 novčanika, 100 X računa, 30 TG kanala)

| Izvor | Ping svake 1 s: zahtjeva/mj | Ping: trošak/mj | Događaji: trošak/mj | Omjer |
|---|---|---|---|---|
| Novčanici (Helius RPC, 1 kredit po pozivu) | 259,2 M | ≈ $1.295 (plan Professional 200 M + 59 M × $5/M); 100 zahtj./s je iznad limita Developer plana (50/s) | webhook: ≈ 45.000 kredita = 0,45 % plana koji već plaćamo, $0 dodatno | ≈ 5.800× |
| X (twitterapi.io pretraga, 10 računa po upitu) | 25,9 M | ≈ $3.888 (min. $0,00015 po zahtjevu) | Stream: $299 za svih 100 (do 150 računa), $79 za 20, $29 za 6 | ≈ 13× za svih 100 |
| X (filter pravila na 1 s, 7–10 pravila) | 18–26 M provjera | ≈ $2.700–3.900 | isto | isto |
| Telegram (t.me/s) | 77,8 M | $0, ali neizvedivo: petlja u kodu stigne ≈ 0,6–0,7 čitanja/s (1,6–1,8 M/mj), t.me vraća 429 | Telethon: 0 zahtjeva, $0 | – |
| Cijene (DexScreener, 30 tokena po zahtjevu) | 2,6 M | $0; 60/min od limita 300/min po IP-u; iznad ≈ 150 tokena limit puca | PumpPortal ≈ $3,8/dan po vrućem tokenu; Helius WSS ≈ $0,05/dan po tokenu | – |

CPU na 1 jezgri (lokalno izmjereno na kodu iz repoa): parsiranje jedne t.me stranice 2,1 ms, jedan webhook događaj 0,11 ms. Mrežni dio pinga (TLS, bez ponovne upotrebe veze) procjenjujem na 3–10 ms. Znači: 15 čitanja/s za Telegram ≈ 8–18 % jezgre, 100 RPC pingova/s ≈ 30–100 % jezgre; 1.500 webhook događaja dnevno ≈ 0,2 CPU-sekunde dnevno, 150.000 ≈ 16.

## 2. Model troška (najjeftinija arhitektura koja daje kupnju/poziv u 1–3 s)

| | DANAS: 100 novč. / 100 X / 30 TG | 10×: 1.000 / 1.000 / 300 | 100×: 10.000 / 10.000 / 3.000 |
|---|---|---|---|
| Novčanici | Helius webhook kakav jest | isti webhook, `chain.max_wallets` 1000 | isti webhook ili Helius WSS `transactionSubscribe` (isti plan) |
| Događaja/mj (15 po novčaniku dnevno) | 45.000 | 450.000 | 4,5 M |
| Helius krediti | 0,45 % plana | 4,5 % plana | webhook 45 % plana; WSS 0,2–1,1 M kredita |
| Novčanici, dodatni $/mj | 0 | 0 | 0–23 (samo ako ostatak bota potroši svojih 5–7 M) |
| X u 1–3 s, najjeftinije | Stream $29 (6 računa) ili $79 (20) + ostalih ≈ 80 na pravilima od 300 s ≈ $9–13 | Stream $299 (150 najboljih) + 850 kroz timeline ≈ $77 | Stream $499 (500) + 9.500 kroz timeline ≈ $855 |
| X: svi računi u 1–3 s | $299 | $999 | $4.999 |
| X na današnji način (pravila 30 s, kašnjenje 0–30 s) | ≈ $91–130 | ≈ $907–1.296 | ≈ $9.072–12.960 |
| Telegram | 1 Telethon račun, $0 | 1 račun (do 500 kanala), $0 | 6 računa ili 3 Premium, $0–15 (cijena Premiuma nije provjerena) |
| **Slušanje ukupno, novo $/mj** | **≈ $38–92** | **≈ $376** | **≈ $1.354–1.392** |
| Već plaćamo (ostaje) | Helius $49; X timeline do $96 | isto | isto |

Računica: X pravilo košta 388,8 / interval_s dolara mjesečno (30 s = $12,96, 300 s = $1,30, 2 s = $194); 100 računa = 7–10 pravila. Timeline: $0,15 na 1.000 objava, uz pretpostavku 20 objava po računu dnevno.

Što mijenjati u kodu:

| Veličina | Promjene |
|---|---|
| DANAS | (1) `kol/xhook.py`: brojati provjere pravila u usage.db (danas se ne broje), razdvojiti račune na "novčane" (praćeni + vruća lista) i ostale (`interval_s` 300). (2) Stream računi: registrirati ih kod twitterapi.io i primati na postojeći `/hook/x` ili u novom malom procesu preko WebSocketa; parser `collect.calls_from_tweet` i `copy.wake()` ostaju. (3) Telegram: postaviti `TG_API_ID`, `TG_API_HASH`, `TG_SESSION`; u `start.sh:152` dodati `keep`; `tg/live.py` neka prvo ulazi u praćene i vruće kanale; `poll_followed_s` vratiti na 30 s. (4) `kol/chainwatch.ingest`: spremiti vrijeme primitka (danas samo vrijeme bloka) i buditi copy petlju samo za praćene i dokazane novčanike. |
| 10× | `chain.max_wallets` 1000 i `live/pumpportal.MAX_WALLETS`; `/hook/chain` piše u red s jednim upisom u sekundi umjesto upisa po POST-u u UI niti; filtar botova (`too_busy`) ostaje obavezan; `telethon.max_joined` 150 → 450, pridruživanje ručno unaprijed. |
| 100× | vlastiti proces za `transactionSubscribe` (kao `live/pumpportal.py`: jedna veza, ponovno spajanje, upis jednom u sekundi) i vlastiti parser kupnje iz stanja prije/poslije; `chain_trades` u zasebnu bazu (≈ 2 M redaka uz 14 dana čuvanja, disk ima 2,1 GB slobodno); više Telethon sesija. |

## 3. Što aplikacija već prima, a što pinga (iz koda)

| Izvor | Gdje | Način | Opseg i izbor | Kašnjenje | Trošak |
|---|---|---|---|---|---|
| Helius enhanced webhook (SWAP + TRANSFER) → `/hook/chain` → hype.db `chain_trades` | `kol/chainwatch.py`, `run_ui.py:983` | događaj | do 100 adresa: praćeni iz lige (do 25), dokazani dvaput (do 50), ostatak po udjelima ljestvice 40 % / copy 30 % / signal 10 % / insajderi 20 %; botovi (> 60 tradeova dnevno ili oznaka bundler/mev/cex/rugger) van; uskladba na promjenu liste ili svaka 24 h | sekunde, nije mjereno | 1 kredit po događaju, 100 po izmjeni webhooka; ≈ 1–2 tisuće događaja dnevno (docstring) |
| twitterapi.io filter pravila → `/hook/x` → kol.db `calls` | `kol/xhook.py` | događaj prema nama, kod njih provjera svakih 30 s | do 100 računa: praćeni pravim novcem, vruća lista, watch, veliki po dosegu, zvijezde, ostali po ocjeni; pravila do 250 znakova; uskladba 6 h | 0–30 s | po provjeri pravila; ne mjeri se u usage.db |
| Apify xquik monitor → `/hook/kol` | `kol/live.py`, `hype/sources.py:216` | događaj | watch lista, 10 računa (isti su i u X webhooku) | sekunde do minute | $0,0045 po računu na sat ≈ $32/mj (budžet 1,1 $/dan) |
| PumpPortal WebSocket | `run_live.py`, `live/pumpportal.py` | događaj, 1 veza | do 40 tokena (otvorene pozicije, bondani zadnja 2 h, svježi kandidati ≥ 30k), do 200 novčanika, migracije; novi tokeni isključeni | < 1 s | trgovine ugašene: ključ nema 0,02 SOL; migracije besplatne; 6.11. je 150 tokena potrošilo 0,1 SOL u 2 h |
| Telethon (MTProto) | `tg/live.py`, `start.sh:152` | događaj | svi kanali u kojima je račun; ulazi u 5 dnevno, do 150 | < 1 s | $0; ne radi bez `TG_SESSION`; pokrenut bez nadzora `keep` |
| `.copy_wake` | `league/copy.py:62`, `league/auto.py:314` | lokalni signal, provjera svake 1 s | budi copy prolaz umjesto takta od 20 s; zovu ga Helius, PumpPortal, X webhook, xquik i Telegram (samo praćeni kanali) | ≤ 1 s | 0 |
| Telegram t.me/s | `tg/poll.py`, `tg/config.json` | ping | takt 3 s, do 8 čitanja po taktu s razmakom 1 s; praćeni i vrući "svake 2 s", hot 30 s, active 300 s, quiet 3600 s; 429 zaustavlja sva čitanja 5 min | 30 kanala "svake 2 s" traži 15 čitanja/s, petlja stigne ≈ 0,65/s: stvarno ≈ 46 s ili više | $0 |
| X timeline | `kol/collect.py:448`, `kol/twapi.py` | ping | 400 računa (300 stalnih) svakih 30 min, 10 po upitu, strop 3,2 $/dan raspoređen kroz dan | do 30 min | do $96/mj |
| DexScreener `tokens_live` | `dexscreener/client.py:212` | ping | keš 3 s (najmanje 2 s), 30 tokena po zahtjevu, 300/min po IP-u dijele svi procesi | ≥ 3 s | $0 |
| topcheck | `start.sh:57`, `run_top.py` | ping | top 20 svake 3 min (RugCheck + Jupiter test prodaje) | 3 min | $0 |
| Pravi novac | `trade/config.json` `poll_s` 1 | lokalno čitanje baza svake 1 s | – | 1 s | 0 |

Izmjerena mjesečna potrošnja po izvoru: u sandboxu je nema. Lokalni `usage.db` ima samo 14 testnih redaka; README i DNEVNIK daju stropove, ne zbrojeve: Helius 10 M kredita ($49), cilj 5–7 M; twitterapi timeline 3,2 $/dan; Apify budžet $100/mj (gmgn 1,7 $/dan, kol_monitor 1,1 $/dan); jutarnji izvještaj ≈ 0,15 $/dan.

## 4. Proizvodi i cijene

| Proizvod | Cijena i limiti | Za nas | Izvor |
|---|---|---|---|
| Helius planovi | Developer $49 / 10 M kredita / 50 zahtj./s; Business $499 / 100 M; Professional $999 / 200 M; dodatni krediti $5/M (nepotvrđeno) | Developer je dovoljan do 100× novčanika | https://www.helius.dev/docs/billing/plans |
| Helius webhook | 1 kredit po događaju (i kad naš server vrati grešku), 100 kredita po izmjeni; 100.000 adresa po webhooku; broj webhooka 50 ili 3 (stranice se ne slažu: nepotvrđeno) | već radi; "puno više novčanika" je promjena jednog broja | https://www.helius.dev/docs/faqs/webhooks , https://www.helius.dev/docs/billing/rate-limits |
| Helius WSS `transactionSubscribe` | na Developer planu od 7.4.2026.; 2 kredita po 0,1 MB; 50.000 adresa po filtru; 150 veza | 4–20× manje kredita po događaju od webhooka; vrijedi tek na 100× ili za tok trgovina tokena | https://www.helius.dev/docs/billing/credits , https://www.helius.dev/blog/laserstream-websockets |
| Helius LaserStream gRPC | mainnet na Business ($499) i više; stariji izvori kažu samo Professional (nepotvrđeno); dodatak 5 TB $400/mj samo uz Professional | ne treba za 1–3 s | https://www.helius.dev/docs/billing/credits , https://www.helius.dev/pricing |
| QuickNode | gRPC dodatak od $499/mj ili uključen u Scale ($499) od 1.6.2026.; Streams se naplaćuje API kreditima, cijenu po GB nisam našao | skuplje od onog što imamo | https://www.quicknode.com/blog/solana-grpc-is-now-included-with-scale-and-business-plans |
| Chainstack | Growth $49 + gRPC dodatak $49 (2 toka, 50 računa po toku), $149 (7), $449 (25); događaji neograničeni | $98/mj za 100 adresa: bez prednosti | https://chainstack.com/pricing/ , https://docs.chainstack.com/docs/yellowstone-grpc-geyser-plugin |
| Shyft | gRPC $199 / $349 / $649, bez mjerenja prometa; cijenu callbacka nisam našao | ne treba | https://shyft.to/solana-yellowstone-grpc |
| Triton | $0,08/GB + $10 na milijun poziva, polog $125 | rezerva za gRPC bez pretplate | https://triton.one/pricing |
| Syndica ChainStream | ugašen 14.2.2026. (nepotvrđeno, blog treće strane) | – | https://rpcedge.com/blog/migrating-from-syndica-chainstream |
| Alchemy | webhook 0,04 CU po bajtu (≈ 40 CU po događaju), $0,52 na milijun CU; Solana webhook u beti (nepotvrđeno) | ≈ $0,00002 po događaju, ali beta i drugi format | https://www.alchemy.com/docs/reference/compute-unit-costs , https://www.alchemy.com/pricing |
| Moralis Streams | 10 CU po zapisu; Starter $149 (2 M CU), Pro $249 (100 M) | skuplje | https://docs.moralis.com/streams/pricing |
| Bitquery | WebSocket od $99/mj (Pro), Scale $299; Kafka samo Enterprise; stranice se ne slažu (nepotvrđeno) | ne treba | https://bitquery.io/products/websocket-streams |
| Birdeye | WebSocket tek od Premium $199/mj (20 M CU, 500 veza); Business $499 | samo za cijene uživo; preskupo za našu veličinu | https://bds.birdeye.so/pricing |
| Solana Tracker | Datastream od Premium €397/mj | preskupo | https://docs.solanatracker.io/pricing |
| Codex (Defined) | Growth $360/mj, 3 M CU, WebSocket se naplaćuje po poruci, 300 veza | preskupo | https://www.codex.io/pricing , https://docs.codex.io/extra/faq |
| PumpPortal | 0,01 SOL na 10.000 trgovina (tokeni i novčanici); ključ s novčanikom ≥ 0,02 SOL od 1.5.2026.; novi tokeni i migracije besplatno | novčanici ≈ $4/mj (duplikat Heliusa); tokeni do stropa 20.000 dnevno ≈ $52/mj | https://pumpportal.fun/fees/ , https://pumpportal.fun/data-api/real-time/ |
| Cielo | Whale $199/mj uključuje API, 1.000 Solana novčanika, WebSocket feed; Pro $59 (200 novčanika, Telegram/Discord obavijesti); developer stranica daje druge cijene (nepotvrđeno) | ne treba uz Helius | https://cielo.finance/ , https://developer.cielo.finance/docs/getting-started |
| Nansen | API Pro $49/mj (2.000 kredita); obavijesti na Telegram, e-mail ili webhook | krediti premali za tok | https://nansen.ai/api |
| GMGN | nema dokumentiranog javnog webhooka za novčanike; obavijesti idu kroz Telegram bota | – | https://docs.gmgn.ai/index/wallet-alert-on-telegram |
| twitterapi.io filter pravila | najmanje $0,00015 po provjeri pravila (i praznoj) + $0,00015 po objavi; interval 0,05 ili 0,1 do 86.400 s; pravilo do 255 znakova; webhook ili WebSocket (nepotvrđeno: blog samog dobavljača) | današnji način; skup čim je interval kratak | https://twitterapi.io/blog/twitter-webhooks-real-time-api-guide , https://docs.twitterapi.io/api-reference/endpoint/add_webhook_rule |
| twitterapi.io Twitter Stream | po računu, ne po objavi: $29 (6), $79 (20), $149 (50), $299 (150), $499 (500), $999 (2.000); dodatni račun $5 do $0,50; ≈ 500 ms | najjeftiniji push za X | https://twitterapi.io/twitter-stream |
| X službeni API | $0,005 po pročitanoj objavi, strop 2–3 M mjesečno, stream samo Enterprise (nepotvrđeno, blogovi) | 30× skuplje od twitterapi.io | https://twitterapi.io/blog/x-api-cost-breakdown-2026 , https://postproxy.dev/blog/x-api-pricing-2026/ |
| TweetStream | $199/mj za 50 računa, $499 za 250; medijan 170 ms po vlastitom mjerenju | skuplje od twitterapi Streama | https://tweetstream.io/alternatives/twitterapi-io |
| Telegram korisnička sesija (Telethon) | besplatno; 500 kanala po računu, 1.000 s Premiumom | zamjena za ping od 2 s | https://core.telegram.org/api/premium , https://limits.tginfo.me |
| SOL za preračun | ≈ $87 | – | https://www.coinbase.com/price/solana |

## 5. Preporuka: najjeftiniji put, redom

1. **Prvo izmjeriti (0 $):**
   - twitterapi.io dashboard: stvarna dnevna potrošnja. Ako je iznad 3,2 $/dan, razlika su provjere pravila.
   - kol.db: `SELECT value FROM kv WHERE key='xhook'` (broj pravila) i `SELECT handle, COUNT(*) FROM calls WHERE source='x_hook' AND ts >= strftime('%s','now','-14 day') GROUP BY 1 ORDER BY 2 DESC` (koji računi išta daju).
   - tg.db: `SELECT name, ROUND(lag_s) FROM channels WHERE lag_s IS NOT NULL ORDER BY lag_s DESC` (stvarno kašnjenje "2 s" kanala).
   - league.db: `SELECT action, COUNT(*), AVG(ts - ev_ts) FROM copy_log WHERE side='buy' GROUP BY 1` (sekunde od poziva do odluke).
   - usage.db: `SELECT method, SUM(calls), SUM(amount) FROM usage WHERE service='helius' AND method LIKE 'webhook%' GROUP BY 1`.
2. **Telegram: uključiti Telethon ($0).** Jedan broj telefona, `python3 run_tg.py login` na vlastitom računalu, tri varijable na Renderu. Ping od 2 s tada nije potreban.
3. **Novčanici: ostati na Helius webhooku ($0 dodatno).** Do 1.000 novčanika mijenja se jedan broj u `kol/config.json`. PumpPortal ne puniti za novčanike; za dump izlaz tek kad demo pokaže da vrijedi.
4. **X: sekunde platiti samo za račune koje prati pravi novac.** Stream $29 (6) ili $79 (20); ostala pravila na 300 s (≈ $9–13) ili ugasiti; xquik monitor ugasiti ako su istih 10 računa u streamu (−$32/mj).
5. **Ne kupovati:** gRPC (Helius Business $499, QuickNode $499, Shyft $199), Birdeye/Codex/Solana Tracker WebSocket ($199, $360, €397), Cielo API ($199). Nijedan ne daje ništa što Helius za $49 već ne daje za naš cilj od 1–3 s.

## Provjereno / Pretpostavka

**Provjereno (kod i lokalno mjerenje):** sve u tablici 3; kapacitet Telegram petlje (8 čitanja po taktu, razmak 1 s, takt 3 s); X webhook se ne upisuje u usage.db; `chain_trades` nema vrijeme primitka; start.sh pokreće Telethon bez `keep`; CPU po parsiranju (2,1 ms i 0,11 ms na sintetičkim uzorcima od 134 KB i 12 KB).

**Pretpostavka:** 15 događaja po novčaniku dnevno (docstring kaže 1–2 tisuće dnevno na 100 novčanika, prije izbacivanja botova); 7–10 X pravila za 100 računa i naplata svake provjere (izvor je blog dobavljača; iznos od ≈ $91–130/mj treba potvrditi na dashboardu); 20 objava po X računu dnevno; veličina transakcije 2,5–12 KB u Helius WSS-u; CPU mrežnog dijela pinga; kašnjenje Helius webhooka "u sekundama"; proizvodne brojke iz usage.db nisam mogao pročitati.

## Provjera cijena

Druga provjera, 10.11.2026.

**Odgovor:** Računica i tvrdnje o kodu stoje; našao sam 5 sitnih ispravaka i nijedan ne mijenja redoslijed preporuke. Cijene dobavljača **nisam mogao ponovno provjeriti na webu**: WebSearch je odbio prvu pretragu ("budžet pretrage za ovaj krug potrošen", 0 izvedenih), a WebFetch ne može razriješiti `www.helius.dev`, `twitterapi.io` ni `pumpportal.fun` (domene nisu dopuštene u mreži ove sesije). "Potvrđeno" zato znači: broj stoji u našem kodu ili zapisu. Sve ostalo ostaje "nepotvrđeno" dok netko ne otvori službenu stranicu.

### Opcije

| Opcija | Presuda | Na čemu stoji danas | Što nije viđeno / napomena |
|---|---|---|---|
| Helius webhook (Developer) | nepotvrđeno (web) | Plan 10 M kredita: `README.md:131`, `usage/budget.json`. 1 kredit po događaju, 100 po izmjeni: `usage/meter.py:115-121`, `run_ui.py:997`. Isti brojevi ($49, 10 M, $5/M, 1 kredit) neovisno u `audit/2026-11-10/svijece.md:64` | 100.000 adresa po webhooku, broj webhooka i $5/M nisu viđeni na službenoj stranici. Odluku ne mijenja: treba 1 webhook, a 1.000 adresa je 4,5 % plana |
| Helius WSS `transactionSubscribe` | nepotvrđeno | Samo računica: 2 kredita / 0,1 MB × 2,5–12 KB = 0,05–0,24 kredita po događaju | Developer plan "od 7.4.2026.", 2 kredita / 0,1 MB, 50.000 adresa, 150 veza. Provjeriti prije 100×; danas ne utječe |
| Helius LaserStream gRPC | nepotvrđeno | – | $499 / $999 / $400. Ne kupujemo |
| Telegram (Telethon) | nepotvrđeno (limit 500 / 1.000) | Kod: `tg/live.py:16-17,32-40`, `tg/config.json` (5 dnevno, do 150), `start.sh:152` bez `keep`; `telethon` je već u `requirements.txt:4` | Za danas (30) i 10× (300 kanala) granica je naš `max_joined` 150, ne Telegramov limit |
| twitterapi.io Twitter Stream | nepotvrđeno | – | Jedini plaćeni korak preporuke. Cjenik $29–999 nije viđen ni u jednoj od dvije provjere na samoj stranici (prva: sažetak pretrage) |
| twitterapi.io filter pravila | nepotvrđeno | Računica 388,8 / interval_s točna. Kod: `kol/xhook.py:17` (30 s, 250 znakova), `:109-123`; u datoteci nema poziva mjerača | Naplata po provjeri i najmanji interval nisu viđeni. Vidi dopunu 1 dolje |
| X timeline (postojeći) | potvrđeno (repo) | `kol/twapi.py:4-5,17-18` (zapis cijene 1.11.2026.: $0,15 / 1.000, najmanje $0,00015), `README.md:204`; `kol/config.json` `timeline_twapi` 400 / 300 / 10, 30 min, 3,2 $/dan | Web nije ponovno otvoren |
| PumpPortal | potvrđeno (repo) | `live/pumpportal.py:19-21` (poruka dobavljača: ključ ≥ 0,02 SOL), `:26-29` (0,01 SOL / 10.000; 6.11. ≈ 90.000 trgovina za 0,1 SOL; strop 20.000 dnevno); isto u `svijece.md:65` | "od 1.5.2026." nije potvrđeno (kod bilježi poruku 5.11.). $3,8/dan je token točno na pragu 30 trgovina/min (`:30`), a takav se token izbacuje |
| Apify xquik | potvrđeno (repo) | `hype/sources.py:216-222`, `kol/live.py:4-5`, `hype/apify.json` (kol_monitor 1,1 $/dan); $0,0045 × 10 × 24 × 30 = $32,4 | Cijena je naš zapis, ne web. Vidi dopunu 3 |
| QuickNode | nepotvrđeno | – | Ne kupujemo |
| Chainstack | nepotvrđeno | – | Ne kupujemo |
| Shyft i Triton | nepotvrđeno | – | Ne kupujemo |
| Alchemy i Moralis | nepotvrđeno | Moralis $149 / $249 (2 M / 100 M CU) isto u `svijece.md:56` | Alchemy 40 CU vrijedi za ≈ 1 KB po događaju; uz 12 KB (uzorak iz ove datoteke) 480 CU ≈ $0,00025 |
| Birdeye, Solana Tracker, Codex, Bitquery | nepotvrđeno | Birdeye Premium $199 s WebSocketom, Codex Growth $360, Bitquery Pro $99 isto u `svijece.md:49,57,58`; DexScreener 300/min: `dexscreener/client.py:3,6` | Solana Tracker €397 nema drugi nalaz |
| Cielo, Nansen, GMGN | nepotvrđeno | – | Ne kupujemo |
| Službeni X API i TweetStream | nepotvrđeno | – | Izvori su blogovi trećih strana i u prvom nalazu |

### Računica

| Stavka | U datoteci | Preračunato | Presuda |
|---|---|---|---|
| Ping novčanika | 259,2 M; ≈ $1.295; ≈ 5.800× | 100 × 2.592.000; 999 + 59,2 × 5 = 1.295; 259,2 M / 45.000 = 5.760 | točno |
| X ping, pravila na 1 s | 25,9 M = $3.888; 18–26 M = $2.700–3.900 | 25,92 M × 0,00015 = 3.888; 18,1–25,9 M = 2.722–3.888 | točno |
| Telegram | 77,8 M; 1,6–1,8 M; ≈ 46 s | 77,76 M; 0,6–0,7 × 2,592 M = 1,56–1,81 M; 30 / 0,65 = 46 | točno |
| Helius događaji | 45.000 / 450.000 / 4,5 M = 0,45 / 4,5 / 45 % | isto | točno |
| Helius 100×, dodatno | $0–23 "ako ostatak potroši 5–7 M" | (5–7 M + 4,5 M − 10 M) × $5 = $0–7,5; $22,5 tek ako ostatak potroši svih 10 M | **ispravljeno: $0–8** |
| WSS krediti | 0,05–0,25 po događaju; 0,2–1,1 M | 0,05–0,24; 0,225–1,08 M | točno |
| X pravilo | 388,8 / interval; 30 s $12,96; 300 s $1,30; 2 s $194 | 0,00015 × 2.592.000 = 388,8 | točno |
| 100 računa na 30 s | $91–130 | 7–10 pravila × 12,96 = 90,7–129,6 | točno, ako se naplaćuje svaka provjera |
| "ostalih ≈ 80 na 300 s" | $9–13 | 80 računa = 6–8 pravila = $7,8–10,4 ($9–13 vrijedi za 94–100 računa) | **ispravljeno: ≈ $8–10** |
| Ukupno danas | $38–92 | 29 + 8 do 79 + 10 | **ispravljeno: ≈ $37–89** |
| Ukupno 10× / 100× | $376; $1.354–1.392 | 299 + 76,5; 499 + 855 (+ 0–8 + 0–15) | 10× točno; 100× ≈ $1.354–1.377 |
| X, svi u 1–3 s | $299 / $999 / $4.999 | 150 ≥ 100; 2.000 ≥ 1.000; 999 + 8.000 × 0,50 | točno uz nepotvrđeni cjenik |
| Timeline 10× / 100× | $77 / $855 | 850 × 20 × 30 × 0,00015 = 76,5; 9.500 → 855 | točno |
| PumpPortal | $3,8/dan; $52/mj; $4/mj | 43.200 × 0,000001 SOL × 87 = 3,76; 0,6 SOL = 52,2; 4,5 × 0,87 = 3,9 | točno |
| CPU | 8–18 %; 30–100 %; 0,2 s; 16 s | 7,7–18,2 %; 30–100 %; 0,17 s; 16,5 s | točno |

### Tvrdnje o kodu

| Tvrdnja | Gdje | Presuda |
|---|---|---|
| Webhook SWAP + TRANSFER, 100 adresa, udjeli 40/30/10/20, praćeni do 25, dokazani do 50, botovi > 60 dnevno | `kol/chainwatch.py:190, 48, 148, 157, 50-51`; `kol/config.json` `chain` | potvrđeno |
| `/hook/chain` piše u UI niti i broji kredit po događaju | `run_ui.py:982-1004` | potvrđeno |
| `chain_trades` nema vrijeme primitka; budi copy petlju za svaki red | `kol/chainwatch.py:325-326, 211, 377-380` | potvrđeno |
| X pravila: 100 računa, 30 s, 250 znakova, 6 h; trošak se ne mjeri | `kol/xhook.py:17, 107-131` | potvrđeno; postoji samo brojač isporuka `xhook_count` (`kol/xhook.py:237`, `ui/usage.py:201`) |
| PumpPortal 40 tokena, 200 novčanika, novi tokeni isključeni | `live/pumpportal.py:25, 258-261` | potvrđeno |
| `.copy_wake`: provjera 1 s, budi ga 5 izvora | `league/copy.py:62-73`, `league/auto.py:314-322`; `kol/chainwatch.py:380`, `live/store.py:61`, `kol/xhook.py:250`, `hype/sources.py:194`, `tg/store.py:87-91` | potvrđeno |
| t.me/s: takt 3 s, 8 čitanja, razmak 1 s, 2 / 30 / 300 / 3600 s, 429 = 5 min | `tg/config.json`; `tg/poll.py:136-146`; `run_tg.py:116` | potvrđeno |
| X timeline 400 / 300 / 10, 30 min, 3,2 $/dan | `kol/collect.py:448-456`; `kol/config.json` `timeline_twapi` | potvrđeno |
| DexScreener keš 3 s (najmanje 2), 30 po zahtjevu | `dexscreener/client.py:17, 207, 212-215` | potvrđeno |
| topcheck na `start.sh:57` | stvarno `start.sh:65` (komentar 61–64) | **ispravljeno** (broj retka) |
| "README i DNEVNIK: Helius 10 M ($49), izvještaj ≈ 0,15 $/dan" | `README.md:131` ima 10 M i "Developer od 30.10.2026."; iznosa $49 i 0,15 $/dan u ta dva dokumenta nema | **ispravljeno** (sitno) |
| usage.db ima 14 testnih redaka | 14 redaka, samo servis `anthropic` | potvrđeno |
| Disk 2,1 GB slobodno | `DNEVNIK.md:30, 98` | potvrđeno (zapis, nije mjereno danas) |
| SQL upiti iz točke 1 preporuke | `kol/xhook.py:106`; `tg/store.py:21`; `league/copy.py:41-43`; `usage/meter.py:119-121` | potvrđeno (tablice i stupci postoje) |

### Dopune preporuke (redoslijed ostaje isti)

1. **Mjerenje ($0), dodati dvije stavke:** `get_rules` kod twitterapi.io (kod ga već zove, `kol/xhook.py:109`) i pročitati koliko je pravila aktivno i koji `interval_seconds` je stvarno prihvaćen; `SELECT value FROM kv WHERE key='xhook_count'` u kol.db (broj isporuka). O tome ovisi cijela procjena $91–130.
2. **X Stream ($29 ili $79):** cijena nije potvrđena na službenoj stranici. Prije plaćanja otvoriti https://twitterapi.io/twitter-stream i provjeriti cijenu plana i obračun po računu. "Ne prije mjerenja" ostaje.
3. **Gašenje xquika (−$32/mj):** praćenje obrisanih objava nije prepreka, ide preko twitterapi.io po ID-u objave (`kol/deleted.py:3, 43-49`), a `/hook/kol` iz payloada vadi samo adrese i tickere (`hype/sources.py:169-197`). Prepreka je značajka `kol_x` u hype skenu: čita samo `kol_mentions` (`run_hype.py:613`, `hype/sources.py:200-213`), a tu tablicu puni samo xquik (`hype/sources.py:187`). Copy petlja i konvergencija čitaju i `calls` (`league/copy.py:299-306`, `kol/converge.py:62-68`). Prije gašenja: neka `/hook/x` piše i u `kol_mentions` ili neka `kol_counts` čita `calls`.
4. **Helius na 100×:** $0–8/mj dodatno, ne $0–23.

### Provjereno / Pretpostavka

**Provjereno:** sva računica (preračunata skriptom); sve tvrdnje o kodu s retkom; cijene koje stoje u repou (X timeline, PumpPortal, xquik, Helius plan od 10 M kredita).

**Pretpostavka:** sve cijene i limiti dobavljača s weba, jer danas nisu ponovno viđeni. U dopuni 1: dokumentacija twitterapi.io je 2025. za `interval_seconds` navodila najmanje 100 s (sjećanje, bez izvora danas). Ako to još vrijedi, današnja pravila koštaju ≈ $27–39/mj, a kašnjenje je do 100 s, ne do 30 s.

**Za dovršetak provjere:** ponoviti pretragu kad se budžet obnovi ili dopustiti domene `www.helius.dev`, `twitterapi.io`, `pumpportal.fun` u mrežnim postavkama; prvo X Stream i filter pravila, jer jedino oni nose novi trošak.
