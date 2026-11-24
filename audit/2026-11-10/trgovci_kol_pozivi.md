# KOL pozivi: pretraga nije obavljena; što već imamo i kako to izmjeriti sami (10.11.2026.)

Kut pretrage: `pretraga:kol_pozivi`. Autor: istraživački agent (samo čitanje repozitorija, bez commita).

**Izravan odgovor.** Ovaj kut nije istražen: 0 od traženih 15 pretraga, nijedna nova tvrdnja s weba. Proračun web
pretraga za cijeli krug (200, zajednički svim agentima) bio je potrošen prije mog prvog upita, a izravno otvaranje
stranica je blokirano. Datoteka zato ne ispunjava zadatak (15 tvrdnji s izvorima). Da kut ne ostane prazan, ovdje je:
(1) što susjedne datoteke već imaju o pozivima, (2) plan mjerenja glavnog pitanja ovog kuta na našim podacima, bez
novog troška, (3) upiti i izvori za ponovljeni pokušaj.

## Provjereno / Pretpostavka

**Provjereno:**
- 2 pokušaja WebSearch, oba odbijena ("web search budget is used up, limit 200 per turn, shared by every agent").
  3 pokušaja WebFetch (arxiv.org dvaput, papers.ssrn.com): host nije na popisu dopuštenih. Ograničenje nisam zaobilazio.
- Pročitano u repozitoriju: `kol/minute.py`, zaglavlja `kol/{flows,insiders,shillers,deleted,together,tpsl,crew,
  converge,measure,reach,bots}.py`, sheme `kol.db` i `minute.db`, `league/copy.py` (`copy_log`), `trade/executor.py`
  (`orders`), `trade/config.json`, `kol/shillers.json` (samo broj unosa), DNEVNIK 7.–10.11., `trgovci_x_traderi.md`,
  `trgovci_youtube.md`, `svijece.md`.
- Lokalne baze u sandboxu su prazne (kol.db: 0 redaka u svim tablicama), pa nijedno mjerenje iz odjeljka 3 nije pokrenuto.

**Pretpostavka:**
- Retci u odjeljku 1 preneseni su iz susjednih datoteka. Njihove izvore nisam otvarao ni ponovno tražio; ne brojati
  ih kao drugu, neovisnu potvrdu.
- Odjeljak 4b je iz sjećanja modela (znanje do 6/2026.), bez provjere. Brojke i oznake radova mogu biti krive i ne
  smiju u prijedlog dok ih netko ne otvori.
- Pragovi u odjeljku 3 (10 postotnih bodova, 300 poziva po razredu, 30 %) su moj prijedlog, ne nalaz.
- Da 1-min svijeće dovoljno dobro opisuju ulaz s odgodom; stvarni fill može biti lošiji (zato T8).

## 1. Što o pozivima već piše u susjednim datotekama (preneseno, nije nova pretraga)

Dokaz: **podaci** = studija, dataset, on-chain istraga; **iskustvo**; **mišljenje**.

| # | Tvrdnja (s brojkama) | Tko | Dokaz | Gdje je već zapisano i izvor | Što ovaj kut dodaje (test) |
|---|---|---|---|---|---|
| A | Četiri KOL-a: dio kupuje prosječno 20 s prije poziva, dio prodaje unutar par minuta nakon objave. 0xEthan (oko 88.000 pratitelja): prodaja oko 3 min nakon poziva; 49 poziva = oko 125.000 $, od toga 80.000 $ pump.fun nagrada za pozive. | Bubblemaps (5.11.2026.) | podaci (tvrdnja firme) | `trgovci_x_traderi.md` r. 3; [Bubblemaps](https://blog.bubblemaps.io/bubblemaps-investigates-crypto-kol-moves-onchain/), [CryptoBriefing](https://cryptobriefing.com/bubblemaps-ethan-125k-token-callouts/), [crypto.news](https://crypto.news/bubblemaps-hidden-wallets-crypto-influencers/) | T2 i T3: ako pozivatelj prodaje oko 3. minute, ulaz 2 min nakon poziva kupuje od njega. |
| B | Javni wallet poznatog tradera kao mamac: oko 30 povezanih walleta; 4 operativna kupe, podijele na 12 sporednih, javni wallet kupi, kopisti uđu, sporedni prodaju. 1,74 mil. $ na oko 3.000 tokena od 7.5.2026., uz 331.000 $ nagrada za pozive. | Bubblemaps (9.11.2026., navod) | podaci (istraga, osporivo) | `trgovci_youtube.md` r. 5; [X](https://x.com/bubblemaps/status/2119823688673751416), [CryptoBriefing](https://cryptobriefing.com/bubblemaps-alleges-cupsey-solana-wallet-scheme/) | T3: udio poziva s prodajom ranih kupaca u prvih 5 min, po računu. |
| C | 377 influencera (10.000+ pratitelja), 1.567 tokena: 86 % izgubilo 90 %+ u 3 mjeseca; računi s 200.000+ pratitelja −39 % nakon tjedan dana; ispod 50.000: +25 % nakon tjedna. | CoinWire (11/2024.) | podaci (stariji ciklus) | `trgovci_x_traderi.md` r. 4, `trgovci_youtube.md` r. 11; [CoinWire](https://coinwire.com/76-percent-twitter-influencers-promote-dead-memecoins-study/), [CryptoTimes](https://www.cryptotimes.io/2024/11/22/76-of-memecoins-promoted-by-influencers-are-dead-study/) | Mjeri tjedne i mjesece, ne minute. Naš rez po pratiteljima je već predložen tamo; ovdje ga treba spojiti s T5 (plaćeni računi). |
| D | 457 ocijenjenih KOL walleta: prosječni 30-dnevni win rate 42 %, oko četvrtine iznad 50 %; "kopiranje nasumičnog KOL-a ima negativno očekivanje". | MadeOnSol (6/2026.; prodaje te podatke) | podaci (zainteresirana strana) | `trgovci_x_traderi.md` r. 5; [MadeOnSol](https://madeonsol.com/blog/what-is-a-kol-in-crypto) | T9: predviđa li vanjska ljestvica naš izmjereni ishod. |
| E | Odgoda ubija kopiju: simulacija na krivulji 46 % win rate uz 0,5 s, 28 % uz 1 s, 4 % uz 5 s; ulaz 2 min nakon kupnje velikih klastera −41 % po tokenu (93 tokena). Mjereno na kupnjama walleta, ne na X/Telegram pozivima. | R. Kurnovskii (12/2025.); TokenPost (20.10.2026.) | podaci | `trgovci_youtube.md` r. 3, `trgovci_x_traderi.md` r. 1; [Kurnovskii](https://romankurnovskii.com/en/blog/pumpfun-copy-trading-feasibility/), [TokenPost](https://www.tokenpost.com/news/investing/35409) | T1 i T2 su izravna provjera istog pitanja na pozivima. |
| F | 48,5 % volumena na PumpSwapu je u tokenima mlađim od 1 h. | OnchainDivers (10/2026.) | podaci | `trgovci_youtube.md` r. 12; [OnchainDivers](https://onchaindivers.substack.com/p/pumpfun-migrations-dropped-what-are) | T4: jeka poziva nakon prvog sata tokena. |

## 2. Na što ovaj kut još nema odgovor

- **Udio poziva isplativih za pratitelja koji kupi 30 s, 2 min ili 10 min kasnije:** nijedna vanjska brojka. Autor
  `trgovci_youtube.md` piše da nije našao nijedno mjerenje poziva na razini minuta izvan MemeSonara. Odgovor je T1 i T2.
- **Brzina cijene nakon objave u sekundama:** ništa za X/Telegram pozive; postoji samo kašnjenje kopije walleta (redak E).
- **Plaćeni shill i neoznačene promocije:** nijedan vanjski izvor u ovom krugu. Imamo vlastiti popis (T5).
- **Ljestvice pozivatelja (Kaito, KOLscan, CallAnalyser, statistike Telegram kanala):** ništa. Vidi 4a i T9.
- **Koordinacija grupa:** samo dva Bubblemaps slučaja (retci A, B). Vidi T6.

## 3. Plan mjerenja na našim podacima (0 $ novog troška)

Mjera pogotka svugdje: "+15 % prije −20 % u 60 min" (`kol/minute.clean_hit(row, 15)`), filtar `bad IS NULL AND
mcap_e >= 30000`. Prag isplativosti iz `kol/tpsl.py`: 63 % za TP 15 / SL 20 uz 1 % troška po strani.

| # | Pitanje | Podaci koji već postoje | Rez | Pravilo koje bi slijedilo | Što fali |
|---|---|---|---|---|---|
| T1 | Gubi li poziv vrijednost već unutar prve minute ("30 s kasnije")? | `minute.db call_path.lag_s` = sekunde od objave do ulaza (zatvaranje minute objave, 0–60 s), `t15`, `sl_min`, `hi15`, `r60` | `lag_s` 0–20 / 20–40 / 40–60 s; udio pogodaka i medijan `hi15` | Ako je razred 40–60 s lošiji za 10+ postotnih bodova (300+ poziva po razredu): pozivi stariji od oko 30 s se ne kupuju; vrijede samo izvori s vruće liste (čitanje 1–2 s). | Ništa; jedan upit na serverskoj `minute.db`. Ulaz je zatvaranje svijeće, ne fill. |
| T2 | Koliki je udio pogodaka uz ulaz 2 min i 10 min nakon poziva? | Iste besplatne 1-min svijeće; `minute.path(candles, ts)` je čista funkcija | U istom prolazu pozvati i `path(candles, ts+120)` i `path(candles, ts+600)`; spremiti premiju ulaza i pogodak u `call_lv.lv` | Krivulja 0 / 2 / 10 min prema pragu 63 %: `trade/config.json max_signal_age_s` (danas 180) za pozive = najveća odgoda koja još prelazi prag; ako nijedna ne prelazi, kasni pozivi se ne kupuju. | Svijeće se ne spremaju, pa povijest traži ponovno mjerenje (`relevel_per_run` 40 tokena po prolazu, red je dug). Početi od novih poziva i vruće liste. |
| T3 | Je li poziv izlazna likvidnost ranih kupaca? | `kol.db calls.pre2h`; `flows` (pre_buy_sol, buyers_pre, post_sell_sol, sellers_post, insiders, rotation_selling); `insiders` (call_ts, bought_ts, sold_ts); `insiders.sell_timing()` | Po računu: udio poziva u kojima su kupci iz sata prije poziva prodali unutar 5 min nakon; pogodak s takvom prodajom i bez nje | Račun s 30 %+ takvih poziva se ne kopira; ako se ipak uđe, vremenski izlaz do 3. minute (redak A). | `flows` se mjeri samo za 60 poziva dnevno (`flows_per_day`), pretežno grupne: uzorak je pristran. |
| T4 | Vrijedi li samo prvi poziv na tokenu? | `call_path.first_caller`, `calls.first_by_kol`, `first_overall`, minute od prvog poziva tokena (`MIN(ts)` po tokenu) | Prvi poziv / jeka 0–10 min / 10–60 min / preko 60 min | Kupuje se samo prvi poziv; jeka samo ako njen razred prelazi prag. | Ništa. |
| T5 | Zovu li plaćeni računi lošije? | `kol/shillers.json`: 90 unosa iz vlastite tablice plaćenih promocija (66 X računa, 51 Telegram kanal) + `call_path` | Plaćeni prema ostalima sličnog broja pratitelja: pogodak, stop prvi, rug (`lo60 <= -0.80`) | Ako su lošiji: probni status ostaje (danas `shill.min_calls`), a token koji u 30 min zovu 2+ računa s popisa je kampanja i ne kupuje se (danas `converge` množi s 0,5 samo uzorak od 5 Telegram objava u 120 s kad prvi pozivatelj nije dobar). | Popis je iz jedne tablice (4.11.2026.); računi koje nismo plaćali, a netko drugi jest, nisu označeni. |
| T6 | Grupa: signal ili kampanja? | `groups` (n_authors, good_authors, insiders, dev_selling), `pair_tests` (lift, p), ishod od PRVOG poziva grupe | Veličina 1 / 2–4 / 5+ autora | Brojkom potvrditi ili odbaciti pravilo iz DNEVNIKA "5+ = plaćena kampanja". | Ništa. |
| T7 | Koliko brisanje objava uljepšava rezultat? | `calls.deleted_ts`, `checked_ts` (`kol/deleted.py`) | Udio obrisanih po računu; pogodak obrisanih prema neobrisanima | Vanjske ljestvice čitaju samo preživjele objave: služe za kandidate, ne kao dokaz. Dokaz je naše mjerenje koje pamti obrisane. | Ponovna provjera objava košta 0,15 $ na 1.000 (prema `kol/deleted.py`); nisam provjerio koliko ih je već provjereno. |
| T8 | Kolika je stvarna odgoda i premija Autopilota? | `league.db copy_log` (ev_ts = objava, ts = naša odluka), `trade.db orders` (amount_in, amount_out, cost_pct), `call_path.entry` | Sekunde od objave do odluke; premija filla nad zatvaranjem minute; PnL po razredu odgode | Bez ovoga su T1 i T2 samo papir. | `orders` nema cijenu izvora u trenutku objave; uzeti `call_path.entry`. |
| T9 | Predviđa li vanjska ljestvica naš ishod? | `kol_ids` (source, rank, pnl, wins, losses, twitter) prema `call_path` za isti račun i statusu "dokazan dvaput" za wallet | Rang ljestvice u trećinama prema našem pogotku | Ako veze nema: čitanje javnih lista (`idents`) ostaje samo izvor kandidata, bez utjecaja na ocjenu. | Ništa. |

Podatak koji stvarno fali: cijena u sekundama (točno 30 s). `hype.db live_trades` (PumpPortal, `price_sol`, 48 h) to
daje besplatno kad feed radi; `svijece.md` navodi da trenutno ne radi (ključ ispod 0,02 SOL). Plaćene svijeće od 1 s
nemaju smisla prije nego što T1 pokaže da prva minuta odlučuje.

## 4. Za ponovljeni pokušaj

Trošak: 15 do 20 pretraga u krugu u kojem proračun nije potrošen. Prije toga napraviti T1 (jedan upit), jer on
odgovara na glavno pitanje bez weba.

### 4a. Upiti koje nisam mogao pokrenuti

1. `memecoin KOL calls study returns after call 2026`
2. `pump.fun call rewards KOL how calculated` (redak A spominje nagradu za pozive; pravila ne znamo)
3. `kolscan leaderboard accuracy win rate data`
4. `Kaito mindshare leaderboard price performance study`
5. `CallAnalyser Telegram caller win rate statistics`
6. `Telegram call channels performance statistics 2026 solana`
7. `site:dune.com KOL calls solana dashboard`
8. `KOL "exit liquidity" thread site:x.com 2026`
9. `ZachXBT paid KOL list undisclosed promotion`
10. `undisclosed crypto promotion enforcement 2026 influencers`
11. `"alpha decay" memecoin call seconds after tweet`
12. `crypto influencer tweet intraday returns minutes study`
13. `memecoin cabal coordination on-chain study KOL`
14. `Bubblemaps KOL investigation hidden wallets 2026`
15. `site:youtube.com why following KOL calls loses money data`
16. `Nansen OR Arkham OR Lookonchain KOL wallet buys before call analysis`
17. `paid alpha group early call delay public channel memecoin`

### 4b. Kandidati iz sjećanja modela (NEPROVJERENO, nije izvor)

| Kandidat | Što bi odgovorilo | Što provjeriti |
|---|---|---|
| Merkley, Pacelli, Piorkowski, Williams: "Crypto-Influencers" (Review of Accounting Studies, 2024.; SSRN 4412017) | Prinos nakon tvita po danima; po sjećanju oko 36.000 tvitova, 180 računa, pozitivno prvi dan, negativno nakon otprilike pet dana | Točne brojke; dnevna razina i razdoblje 2021.–2022., nisu Solana memovi |
| ZachXBT (X, 9/2025.) | Procurjeli cjenik 200+ influencera za plaćene objave; po sjećanju gotovo nitko nije označio oglas | Izvorna objava i brojke |
| Xu i Livshits: "The Anatomy of a Cryptocurrency Pump-and-Dump Scheme" (USENIX Security 2019.; arXiv 1811.10109) | Oblik i brzina kretanja nakon objave u Telegram grupama; po sjećanju 412 događaja | Minute do vrha; burze, ne DEX |
| La Morgia i dr.: "Pump and Dumps in the Bitcoin Era" (arXiv 2005.06610) | Plaćene razine u grupama dobiju signal prije javnog kanala | Koliko ranije |
| Dhawan i Putniņš: "A New Wolf in Town?" (Review of Finance, 2023.) | Tko zarađuje, a tko gubi u objavljenom pumpu; po sjećanju 355 slučajeva | Brojke i vrijeme do vrha |
| Kaito | Po sjećanju Yaps ljestvice ugašene 1/2026. nakon promjene X API pravila | Postoji li ljestvica i mjeri li išta osim pažnje |
| Kolscan | Po sjećanju ga je pump.fun kupio 7/2025. | Sukob interesa: plaća li platforma pozive po volumenu |

## Najjače tvrdnje (najviše 7)

Nijedna nije nova: 1–5 su prenesene (odjeljak 1), 6–7 su iz našeg repozitorija.

1. **Pozivatelj prodaje u vlastiti poziv** (A, podaci firme): prodaja oko 3 min nakon objave, dio kupuje 20 s prije;
   80.000 $ od 125.000 $ došlo je od nagrada za pozive. Provjera: T2, T3.
2. **Javni wallet može biti mamac** (B, navod): sporedni walleti prodaju u kopiste. Provjera: T3.
3. **Veliki računi zovu lošije** (C, podaci iz 2024.): 200.000+ pratitelja −39 % nakon tjedan dana. Provjera: rez po
   pratiteljima spojen s T5.
4. **Odgoda gubi i kad izvor vrijedi** (E, podaci, ali za wallete): 0,5 s → 46 %, 5 s → 4 %; 2 min → −41 % po tokenu.
   Za pozive to nitko nije izmjerio. Provjera: T1, T2.
5. **Nasumični KOL ima negativno očekivanje** (D, zainteresirana strana): prosječni win rate 42 %. Provjera: T9.
6. **Vlastito (DNEVNIK 9.11.):** stara mjera poziva precjenjivala je rezultat (ulaz 3–7 min prije poziva, pogodak =
   fitilj +50 % u 24 h); demo "KOL pozivi" +261,6 % na 133 zatvorena uz 22 % dobitnih, bez najboljeg tradea −833 $.
   Svaku vanjsku stopu pogotka bez navedenog trenutka ulaza treba čitati jednako.
7. **Vlastito:** popis 90 plaćenih shill unosa je podatak iz prve ruke koji javne studije nemaju. Provjera: T5.
