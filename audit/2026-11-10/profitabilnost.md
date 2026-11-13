# Kako Autopilot učiniti profitabilnim (prijedlog, 10.11.2026.)

Odgovor na Jurinu točku 5 i istraživački dio točke 12. Izvori: `trgovci_youtube.md`, `trgovci_x_traderi.md`,
`trgovci_copy_walleti.md`, `trgovci_kol_pozivi.md`, `baze.md`, `sekundni.md`, `svijece.md`, DNEVNIK.md, README.md i kod.
Kod nije mijenjan. Pravilo čitanja: **naše mjerenje vrijedi više od tuđe anegdote**; vanjska brojka je hipoteza za test.

Oznake: **(prov.)** = naš kod ili naši podaci; **(izvor)** = navedeni vanjski izvor, brojka iz sažetka pretrage (stranica nije
otvorena); **(pretp.)** = pretpostavka, procjena ili moj prijedlog praga.

## 1. Sažetak u 10 redaka

1. Autopilot danas nema dokazanu prednost: zadani izlaz +15/−20 uz 2 % troška traži 62,9 % pogodaka, dnevnik prijedloga ima 49 % (prov.).
2. Demo "KOL pozivi" +261,6 % na 133 zatvorena, ali bez najboljeg tradea −$833; dan ranije +294 %, bez najboljeg −$580 (prov.).
3. Jedini izmjereni prediktor: vlastiti realizirani rezultat novčanika ostaje (23 od 29, Spearman +0,42); kopije "top" novčanika gubile su ~10 % po tradeu (prov.).
4. Vanjski podaci kažu isto: 26 % dobiti s ljestvica je kopirljivo, kopija dobije ~3 % od vođinih ~14 %, 2 min kašnjenja = −41 % po tokenu (izvor).
5. Najveća nepoznanica je naš stvarni trošak kruga na 0,1 SOL: model 2 %, jedan izmjereni krug 2,8 %, strop 6 % (prov.).
6. Odmah: izlaz "po podacima" za sva praćenja, PROOF strože (plus i bez najboljeg tradea), `max_signal_age_s` 180 → 120, transfer-novčanici van, 7 popravaka podataka.
7. Prvo mjerimo besplatno: trošak kruga, kašnjenje i premiju kopija dokazanih, faktor prijenosa po novčaniku, vrijednost prve minute poziva.
8. **Više plaćenih podataka sada NE treba**: svaka odluka iz točke 7 stoji na podacima koje imamo ili sada bacamo.
9. Dotok: prioritet praćenim i dokazanim novčanicima; masovna knjiga i X računi bez poziva se stišavaju; xquik van (−$32/mj).
10. Istraživanje stoji na 4 od 10 kutova (dva krnja); šest kutova nije završilo pa je prijedlog uži nego što je planiran.

## 2. Što odmah uvodimo (jeftino, dokaz jak, nijedno sigurnosno pravilo se ne labavi)

| Pravilo | Zašto (izvor) | Gdje u kodu | Rizik |
|---|---|---|---|
| R1. Izlaz "po podacima" za **sva** influencer i ekipa praćenja, i postojeća: ulaz samo kad `tpsl.decide` nađe par u plusu na novijoj trećini i na donjoj granici | 49 % pogodaka prema potrebnih 62,9 % za 15/20 (prov., DNEVNIK 9.11.); 416 filtara i izlaza bez ijednog značajno profitabilnog, TP 100/SL 35 = −10,8 % ([Arrow Algo](https://arrowalgo.com/solana-memecoin-trading/), izvor) | `league/copy.py` (način "podaci", `DATA_MAX_LATE_S` 120, `DATA_MAX_RUNUP` 0,10), `kol/tpsl.py` | Manje ulaza. Izvor s < 10 izmjerenih poziva i dalje ulazi sa zadanim 15 % (`DATA_TP`) (prov.). Odgovor na "Čeka Juru 2a" |
| R2. PROOF za pravi novac: uz 10 zatvorenih, PnL > 0 i 40 % dobitnih još **PnL > 0 bez najboljeg zatvorenog tradea** | Naš demo: plus koji stoji na jednom tradeu, dvaput zaredom (prov., DNEVNIK 8. i 9.11.); `strat/robust.py` već traži plus bez 5 najboljih (prov.); metodologija traži PF > 1,2 na 100+ tradeova ([dimasaf](https://github.com/dimasaf/paper-trade/issues/1), mišljenje) | `run_trade.py:130`, `:177` | Kasniji prelazak na pravi novac. **Brava se ne dira bez Jurinog "da"** (NOCNI-PROGRAM) |
| R3. `max_signal_age_s` 180 → 120 s | Kopija 2 min nakon kupnje klastera −41 % po tokenu ([TokenPost](https://www.tokenpost.com/news/investing/35409), izvor); win rate 46 % uz 0,5 s, 4 % uz 5 s ([Kurnovskii](https://romankurnovskii.com/en/blog/pumpfun-copy-trading-feasibility/), simulacija); naš put "po podacima" već odbija ulaz stariji od 120 s (prov.) | `trade/config.json`, zadano i u `ui/pravitrade.py:132` | Manje ulaza. Studije mjere krivulju i nova lansiranja, ne bondane iznad 30k (pretp. da smjer vrijedi). Konačni prag daje E2 |
| R4. Novčanik s `free_token_ratio` > 0,3 nije kopirljiv (danas samo množi `copy_score` s 0,3) | Samo 26 % dobiti velikih pump.fun novčanika je obično trgovanje, 51 % od prodaje tokena primljenih transferom ([CryptoSlate/Bitquery](https://cryptoslate.com/pump-funs-biggest-winners-may-be-impossible-to-copy-as-752-million-study-exposes-hidden-trading-gap/), izvor); sporedni novčanici primaju tokene i prodaju u kopiste ([Bubblemaps](https://x.com/bubblemaps/status/2119823688673751416), tvrdnja firme) | `wallets/dokazani.py:43-48` (`copyable`); vrijednost već postoji, `wallets/pnl.py:116`, `:182` (prov.) | Popis dokazanih se smanji; koliko, nije izmjereno |

**Popravci podataka (preduvjet poštenog mjerenja, $0):**

| Popravak | Zašto | Gdje | Rizik |
|---|---|---|---|
| B1a: PumpPortal zrcalo upisuje SOL i za prodaju | prodaje novčanika nemaju SOL, pa ROI praćenih uživo ne postoji (prov.) | `live/store.py:56` | nizak |
| B1b/c: SOL i količina tokena iz Helius prodaje | isto; temelj za `wallet_path` i "dokazani isti dan" | `kol/chainwatch.py:230-232`, shema `:325` | prvo dan-dva uzorka payloada (pretp. polja) |
| Vrijeme primitka (`seen_ts`) u `calls`, `kol_mentions`, `chain_trades` | danas samo vrijeme objave/bloka: kašnjenje po izvoru se ne može izmjeriti (prov.) | `kol/store.py`, `hype/sources.py`, `kol/chainwatch.py` | nizak |
| B24 + B2: masovna knjiga ne smije otpisivati tuđe točke ni "bez_cijene" dok host drži drugi posao | točke `novcanik_kupio` i `kol_poziv` se gube, reproducirano na kopiji (prov.) | `learn/shadow.py:258-272`, `learn/masovno.py:257-263` | nizak |
| B7b: poziv s nepoznatim mcapom ne ulazi u vruću listu ni TP/SL | pravilo "ispod 30k ne analiziramo" curi (prov.) | `kol/minute.py:211-212`, `:442-446` | nekim računima pada broj mjerenja |
| S10: `followed_wallets()` vraća 0 | "Zovu sada" i pop-up ne vide kupnje novčanika koje Autopilot prati (prov., ponovljeno) | `ui/pravitrade.py:916-929` | nizak |
| B8: `call_path`/`call_lv` čuvati 120 d umjesto 30 | račun s 5 poziva mjesečno nikad ne dobije odluku (traži 10 u 30 d) (prov.) | `kol/minute.py:44`, `kol/tpsl.py` | nizak; prvo raspodjela (metrika m3) |

## 3. Što prvo mjerimo, besplatno, na postojećim podacima (po očekivanoj vrijednosti)

Uzorci su moj prijedlog (pretp.); gdje kod već ima prag, naveden je.

| # | Pokus | Tablice | Usporedba | Uzorak | Odluka po ishodu |
|---|---|---|---|---|---|
| E1 | Stvarni trošak kruga na 0,1 SOL | trade.db `orders` (amount_in, amount_out, cost_pct), `positions`; kol.db `snaps` (liq) | trošak u % uloga po likvidnosti poola; kotacija prema fillu | svi dry nalozi s kotacijom (30+); pravih je malo | ≤ 2 %: model stoji. 3–5 %: `tpsl.COST` na izmjereno. > 5 %: 15/20 ne može u plus ni s 65 % pogodaka, pravi novac stoji |
| E2 | Kašnjenje i premija kopija dokazanih novčanika | strat.db `positions` (strat 'dokazani', `state.kopija`: delay_s, entry_px, wallet_fill); league.db `copy_log` (ev_ts, ts), `trades` | PnL po kašnjenju ≤ 2 / 2–5 / 5–15 / 15–60 / 60–180 s i po premiji nad njegovim fillom 0–5 / 5–15 / 15–50 / > 50 % | podaci od 9.11.; koliko ih ima, nije izmjereno; 30+ po razredu | Najveće kašnjenje i premija još u plusu = novi `max_signal_age_s` i granica premije. Ako je i prvi razred u minusu: novčanici ostaju demo |
| E3 | Faktor prijenosa po novčaniku | wallets.db `wallet_trades` (njegov ulaz/izlaz); strat.db `positions`, league.db `trades` (naš) | naš povrat / njegov na istom tokenu, starija i novija polovica | 10+ kopija po novčaniku | Ostaje samo ako (njegov medijan × faktor − trošak) > 0 u obje polovice ([arXiv 2601.08641](https://arxiv.org/abs/2601.08641v2): 14 % → ~3 %, izvor) |
| E4 | Vrijedi li poziv nakon prve minute (T1) i 2 / 10 min kasnije (T2) | minute.db `call_path` (lag_s, t15, hi15, sl_min), `call_lv`; kol.db `calls` | pogodak "+15 prije −20" po `lag_s` 0–20 / 20–40 / 40–60 s; T2 iz istih svijeća s ulazom ts+120 i ts+600 | 300+ poziva po razredu | 40–60 s lošiji za 10+ postotnih bodova: pozivi stariji od ~30 s se ne kupuju i tek tada X Stream ima smisla. Bez razlike: sekunde na X-u se ne plaćaju |
| E5 | Postoji li ijedan TP/SL par preko svih poziva | minute.db `call_lv` | 25 parova (`tpsl.TPS` × `SLS`), starije 2/3 prema novijoj 1/3, donja granica 2 SE | `POOL_MIN_N` 200 (prov.) | Nijedan globalno: odluka samo po izvoru. Ni po izvoru: pozivi ostaju demo |
| E6 | Insajderi prodaju u poziv (T3) | kol.db `flows`, `insiders`, `calls`; minute.db `call_path` | pogodak s prodajom ranih kupaca u 5 min nakon poziva i bez nje, po računu | `flows` samo 60 poziva/dan, pristrano (prov.) | Račun s 30 %+ takvih poziva se ne kopira ili izlaz do 3. minute ([Bubblemaps](https://blog.bubblemaps.io/bubblemaps-investigates-crypto-kol-moves-onchain/): prodaja ~3 min nakon poziva, tvrdnja firme) |
| E7 | Profit faktor umjesto win ratea za novčanike | wallets.db `wallet_trades`, `dokazani`, `wallet_pnl` | PF i razredi win ratea (< 40 / 40–50 / 50–60 / 60+ %) prije reza prema rezultatu poslije, isti rez kao `dokazani` | svi kopirljivi (361 prema istraživačkim datotekama; u repou nije nađeno) | PF predviđa bolje: dopuniti `min_win` 0,5. Razred 60+ nije bolji: prag se ne diže |
| E8 | Pratitelji i plaćeni računi (T5) | kol.db `calls.followers`, `kols`; `kol/shillers.json` (90 unosa, prov.); minute.db `call_lv` | < 50k / 50–200k / > 200k; plaćeni prema ostalima | 300+ po razredu | Veliki lošiji: doseg (`kol/reach.py`) ne diže ocjenu; prior po razredu u `tpsl` ([CoinWire](https://coinwire.com/76-percent-twitter-influencers-promote-dead-memecoins-study/), 2024., izvor) |
| E9 | Graduacija, starost i mcap tokena | kol.db `tokens` (created_ts), `graduates`, `calls.mcap0`; minute.db `call_lv` | minute od graduacije 0–10 / 10–60 / 1–24 h; mcap 30–100k / 100k–1M / 1M+ | 300+ po razredu | Prvi prozor najgori: čekanje nakon graduacije (26,4 % graduiranih drži mcap nakon 1 h, [memefees](https://memefees.com/research/memecoin-survival-2026), izvor, nepotvrđeno). Fali točan ts migracije |
| E10 | Ponovni ulaz i redni broj tradea u danu | league.db `trades`; trade.db `positions` | 2. i 3. ulaz u isti token prema prvom; PnL 1. / 2. / 3.+ tradea u danu | sve zatvoreno | Lošije: zabrana ponovnog ulaza 24 h, niži dnevni strop |
| E11 | Doba dana | kol.db `sessions`, `token_hours`; league.db `trades` | pogodak po satu UTC i danu u tjednu | 30 dana | 00–08 UTC značajno lošije: Autopilot tada samo bilježi |

## 4. Koji podaci nedostaju

**Više plaćenih podataka sada NE treba.** Prvo se popravlja ono što imamo ili bacamo; plaća se tek kad pokus pokaže da odluka ovisi o tome.

| Podatak | $/mj | Odluka koju otključava | Kada |
|---|---|---|---|
| Vrijeme primitka u `calls`, `kol_mentions`, `chain_trades` | 0 | stvarno kašnjenje po izvoru (E2, E4); plaćati li X Stream | odmah |
| SOL i količina tokena u prodajama novčanika | 0 (događaj je već plaćen) | ROI praćenih uživo; dokazani ispadaju isti dan, ne sutra | odmah |
| Volumen po minuti i cijena prije poziva | 0 (svijeće se već skidaju) | izlaz "volumen stao" ([Euris](https://x.com/Euris_x/status/1878136656227627334), iskustvo); utjecaj poziva | odmah |
| `buys/sells` m5 i h1 u `snaps` | 0, +~5 MB (pretp.) | omjer kupnji i prodaja oko poziva (DNEVNIK, Čeka Juru 2) | odmah |
| Minutne staze kupnji novčanika (`wallet_path`) | 0 s Demo ključem; 35 s Basic (nepotvrđeno) | TP/SL po novčaniku; isplati li se kopija s našim kašnjenjem | nakon B1 i 7 dana brojanja |
| Trgovine nepraćenih adresa ±2 min oko kopirane kupnje | Helius krediti, nije izmjereno | crna lista "mamaca" (sporedni novčanici) | test na 20 kupnji |
| Sekundne cijene (PumpPortal, ključ ≥ 0,02 SOL) | do ≈ 52 (strop 20.000 trgovina/dan, prov.) | vrijedi li razlika od 30 s | samo ako E4 pokaže razliku u prvoj minuti |
| X Stream za račune pravog novca | 29–79 (nepotvrđeno) | brži X pozivi | samo ako E4 i mjerenje kašnjenja to traže |
| Oznaka narativa (mem, celebrity, vijest, AI) | 0 (200 poziva ručno) | vrijedi li narativ kao značajka | nizak prioritet |

## 5. Kontrola dotoka podataka (vrijednost po trošku)

| Izvor | $/mj | Što je donio | Potez |
|---|---|---|---|
| Helius webhook, praćeni i dokazani novčanici | u planu 49 (prov. plan) | jedini izvor s izmjerenom vještinom (prov.) | **Više:** prvi u redu za minutne staze, vrijeme primitka, SOL prodaje; do 1.000 adresa $0 |
| Telegram praćeni i vrući kanali | 0 | dio poziva | **Brže:** Telethon $0 umjesto pinga (danas ≥ 3 s, uz 30 kanala ≈ 46 s, prov.) |
| GeckoTerminal minutna petlja | 0 | jedina poštena mjera poziva (`call_lv`) | **Više:** Demo ključ, red s prioritetom: praćeni → vruća lista → noćni measure → masovno |
| X filter pravila | nije izmjereno (≈ 27–130, pretp.) | hrani pozive i pravi novac (prov.) | **Izmjeriti**, zatim brzo samo praćeni i vruća lista, ostali 300 s |
| X timeline, 400 računa | do 96 (strop, prov.) | kandidati za pozive | **Stišati:** maknuti račune bez ijednog poziva u 14 d |
| `learn/masovno` | 0, ali do ~10.000 GT poziva/dan, noću do 78 % limita (prov.) | točke se gube (B24, B2) | **Stišati** dok se B24 i B2 ne poprave: sad troši limit na otpis |
| Apify xquik | ≈ 32 | duplikat 10 računa X webhooka | **Ugasiti** kad `/hook/x` piše u `kol_mentions` |
| Apify gmgn | strop 1,7 $/dan, stvarno nije izmjereno | novčanici s ljestvica; vani: 26 % kopirljivo (izvor) | **Izmjeriti** koliko dokazanih ima izvor gmgn (`wallets.sources`, `wallet_sightings.source`); 0 u 30 d → ugasiti |
| Pozadinske niti Autopilota bez gledatelja, 4 fragmenta/s | CPU ≈ 10 % stalno sa S1 (pretp., sintetika; S1 je u grani `fe250af`), do ~45 DexScreener/min | ništa kad nitko ne gleda | **Zaustaviti** bez gledatelja (S3, S12) |
| PumpPortal za novčanike | ≈ 4 (pretp.) | duplikat Heliusa | **Ne** |
| Sekundne svijeće, gRPC, Birdeye/Codex WebSocket | 39–499 (nepotvrđeno) | – | **Ne** |

## 6. Što ne radimo i zašto

- **Ne kopiramo ljestvice ni PnL kartice.** Survivorship: vidimo samo preživjele; 74 % od 2,9 mil. kupaca ima manje SOL-a 2
  tjedna kasnije, 1 % uzima više od pola dobiti ([Bitquery](https://bitquery.io/investigations/solana-memecoin-traders-lose-money), izvor); naše kopije "top" novčanika −10 % po tradeu (prov.). Ocjena ostaje samo ono što vidimo na lancu.
- **Ne preuzimamo pragove od prodavača tečajeva i alata.** "0,1 SOL strategije" i "Axiom filtri" s YouTubea nemaju brojke u
  opisu, jedan ima referral link; vodiči (CoinCodeCap, Trojan, Odin.tools, MadeOnSol) žive od naknada ili prodaje podataka;
  brojke im se ne slažu (60 % ili 40–60 % win rate, 30 ili 50 tradeova) (izvor). Cyclop je plaćeno partnerstvo. Svaki prag tek nakon testa (E7).
- **Ne skalpiramo kao Cupsey.** 300+ coina dnevno, držanje 18 s do 4 min, cilj desetci dolara po tradeu (izvor). Bot koji
  ulazi sekunde nakon **javnog** signala s 0,1 SOL kupuje od takvih, ne s njima: 46 % → 4 % win rate od 0,5 s do 5 s (izvor).
  Zato `min_hold_min` 10 ostaje (prov.).
- **Ne uzimamo nove pump.fun tokene ni snajpove** (CLAUDE.md): same-block snajperi vezani su uz deployera, 87 % profitabilnih
  ([Pine](https://pineanalytics.substack.com/p/exit-liquidity-machines), izvor).
- **Ne dižemo slippage za kopije** (Trojan savjet): izvršno klizanje je simetrično, 47 % bolje i 44 % lošije
  ([Bitquery](https://bitquery.io/blog/analyzing-slippage-pumpfun-trading-dynamics), izvor); gubitak je premija kopije, mjeri se (E2).
- **Ne širimo stop bez podataka:** 20/40 traži 70 % pogodaka (§7, prov. račun).
- **Ne dižemo ulog da razrijedimo fiksni trošak** dok PROOF ne prođe: limiti pravog novca ostaju Jurina odluka.
- **Ne radimo dugoročni "Murad" stil** ni "narrative trumps everything": izvan svemira Autopilota (svježi bondani, izlaz u 60 min) i nemjerljivo bez oznake narativa.

## 7. Aritmetika: trošak i prag isplativosti za 0,1 SOL

| Stavka troška | Iznos | Oznaka |
|---|---|---|
| Naknada poola (krivulja, PumpSwap) | do 1,25 % po strani, do 2,5 % po krugu | izvor ([Altrady](https://www.altrady.com/blog/crypto-trading-strategies/pump-fun-solana-memecoin-trading), [DevBundler](https://devbundler.com/blog/trading-after-migration-to-pumpswap)) |
| Priority fee i tip (fiksno, ne raste s ulogom) | 0,002–0,008 SOL po krugu = 2–8 % od 0,1 SOL | pretp. (račun iz cjenika terminala; mi idemo preko Jupiter Ultra, koji sam bira fee) |
| Naš model | 2 % po krugu (1 % po strani) + utjecaj na pool povrh | prov. (`kol/tpsl.py` COST, `league/store.py` FEE) |
| Jedini izmjereni krug | ≈ 2,8 % na 0,05 SOL (dry-run 30.10.) | prov., n = 1 |
| Strop u pravilima | 6 % (price impact + fee iz kotacije) | prov. (`max_cost_pct`) |
| Premija kopije (cijena se pomakne prije nas) | nije izmjereno | E2 |
| Sendvič napadi | 21–33 na 10.000 swapova | izvor (Bitquery preko CryptoSlatea) |

Prag pogodaka: **potrebno = (SL + trošak) / (TP + SL)**, gdje je pogodak "+TP dotaknut prije −SL" (prov., `kol/tpsl.breakeven`).

| TP / SL | bez troška | **trošak 2 %** | 2,8 % (izmjereno jednom) | 6 % (strop) |
|---|---|---|---|---|
| 15 / 20 | 57,1 % | **62,9 %** | 65,1 % | 74,3 % |
| 20 / 40 | 66,7 % | **70,0 %** | 71,3 % | 76,7 % |
| 20 / 20 | 50,0 % | **55,0 %** | 57,0 % | 65,0 % |
| 30 / 15 | 33,3 % | **37,8 %** | 39,6 % | 46,7 % |

Izmjereno za 15/20: 49 % (dnevnik prijedloga, 7 d, prov.). Očekivanje po tradeu = p × TP − (1 − p) × SL − trošak =
0,49 × 15 − 0,51 × 20 − 2 = **−4,85 %**, oko −0,005 SOL na tradeu od 0,1 SOL (račun; izlazi "ni cilj ni stop u 60 min"
nisu uračunati). Za 20/20 i 30/15 udio pogodaka nije izmjeren: E5 ga daje iz `call_lv`. Uži stop spušta prag, ali se
češće dotakne; samo izmjerene putanje kažu koji par nosi plus (prov., `kol/tpsl.py`).

## 8. Izvori

**Pokrivenost.** Planirano je 10 kutova istraživanja; **šest nije završilo** (on-chain statistika, signali ulaza, izlazi i
rizik, botovi, rug provjere, režim tržišta). Prijedlog stoji na četiri: YouTube (70 pretraga), X traderi (60), copy
novčanici (3 od 15+, limit) i KOL pozivi (0 pretraga, samo plan mjerenja T1–T9). U tablicama su 73 izvorne tvrdnje (30 + 25
+ 18) i 6 prenesenih. Brojke su iz sažetaka pretrage; WebFetch je bio blokiran, otvorena je samo stranica dimasaf na GitHubu.

**YouTube** (videe nitko nije gledao; sadržaj samo preko sažetaka i prijepisa; 44 od 47 videa samo naslov i opis):
[Cupsey](https://www.youtube.com/watch?v=JbWa-Jss-18) i [sažetak](https://coconote.app/notes/f63fd4b3-c340-4c8e-bc02-072c694569b3);
["2 Months Trading Memecoins"](https://videohighlight.com/v/3qPyBt7p2js?mediaType=youtube&language=en&summaryType=compressed&summaryId=ys-DnqMgQUmDZ6pdI7mp&aiFormatted=false);
[Orangie prijepis](https://sozai.app/transcript/made-450000-trading-memecoins-30-days/);
[0,1 SOL strategija](https://www.youtube.com/watch?v=EtExDND_Is4) i [Axiom postavke](https://www.youtube.com/watch?v=W5784fFpamc) (bez brojki, referral).

**X:** [Bubblemaps o Cupseyju](https://x.com/bubblemaps/status/2119823688673751416), [Cupsey klip](https://x.com/CoaelOne/status/1948866565224776029),
[Seee](https://x.com/seeexbt/status/1961474223152468120), [camol](https://x.com/camolNFT/status/2097069948128645547),
[Euris](https://x.com/Euris_x/status/1878136656227627334), [Sajad](https://x.com/SajadFlips/status/2013734249023623206),
[Miles Deutscher](https://x.com/milesdeutscher/status/1654546259510988801), [cyclop](https://x.com/nobrainflip/article/2103496245109043636) (plaćeno),
[West](https://x.com/ratwizardx/status/1888176994371694805).

**Članci:** [CryptoSlate/Bitquery 752 mil.](https://cryptoslate.com/pump-funs-biggest-winners-may-be-impossible-to-copy-as-752-million-study-exposes-hidden-trading-gap/),
[TokenPost, kopija s odgodom](https://www.tokenpost.com/news/investing/35409), [Bubblemaps blog](https://blog.bubblemaps.io/bubblemaps-investigates-crypto-kol-moves-onchain/),
[CryptoBriefing](https://cryptobriefing.com/bubblemaps-alleges-cupsey-solana-wallet-scheme/), [MadeOnSol](https://madeonsol.com/blog/what-is-a-kol-in-crypto) (prodaje podatke),
[CoinWire](https://coinwire.com/76-percent-twitter-influencers-promote-dead-memecoins-study/), [fomo: Wood](https://fomo.family/blog/learn/notanicecat69-memecoin-trading-strategy),
[fomo: Washed](https://fomo.family/blog/learn/memecoin-trading-strategies-lessons-from-six-figure-trader), [OnchainDivers](https://onchaindivers.substack.com/p/pumpfun-migrations-dropped-what-are);
vodiči prodavača (mišljenje): [Trojan](https://trojan.com/blog/solana-copy-trading-guide-2026), [CoinCodeCap](https://coincodecap.com/best-settings-for-gmgn-bot),
[Odin.tools](https://odin.tools/blog/pump-fun-autosell-take-profit-stop-loss-2026), [RPC Fast](https://rpcfast.com/blog/how-to-build-a-solana-copy-trading-bot).

**Studije i podaci:** [arXiv 2601.08641](https://arxiv.org/abs/2601.08641v2), [Kurnovskii](https://romankurnovskii.com/en/blog/pumpfun-copy-trading-feasibility/),
[Arrow Algo](https://arrowalgo.com/solana-memecoin-trading/), [Bitquery: gubici kupaca](https://bitquery.io/investigations/solana-memecoin-traders-lose-money),
[Bitquery: klizanje](https://bitquery.io/blog/analyzing-slippage-pumpfun-trading-dynamics), [Bitquery: snajperi](https://bitquery.io/investigations/pump-fun-snipers-bundles),
[Pine Analytics](https://pineanalytics.substack.com/p/exit-liquidity-machines), [memefees](https://memefees.com/research/memecoin-survival-2026),
[Dune preko crypto.news](https://crypto.news/pump-fun-data-shows-49-of-march-traders-in-the-red-as-platform-locks-fees/),
papirni botovi [tymkow](https://github.com/tymkow/Memecoin-bot-test) i [maxmckittrick1](https://github.com/maxmckittrick1-oss/memecoin-paper-bot),
metodologija [dimasaf](https://github.com/dimasaf/paper-trade/issues/1). Studije o krivulji i novim lansiranjima prenose se na
bondane iznad 30k samo smjerom, ne iznosom (pretp.).

## Provjereno / Pretpostavka

**Provjereno:** brojke iz DNEVNIKA (49 %, +261,6 % / −$833, +294 % / −$580), `wallets/dokazani.py` (23 od 29, +0,42, −10 %),
`run_trade.PROOF`, `trade/config.json`, `kol/tpsl.py`, `league/copy.py`, nalazi B1–B24 i S1–S16 s retcima koda; aritmetika u §7.
**Pretpostavka:** svi pragovi i uzorci koje predlažem (120 s, 30+ i 300+ po razredu, 30 %); da se nalazi s krivulje prenose na
bondane; 361 kopirljivih (iz istraživačkih datoteka, u repou nije nađeno); fiksni trošak 2–8 % od 0,1 SOL; sve vanjske brojke
dok netko ne otvori stranicu.
