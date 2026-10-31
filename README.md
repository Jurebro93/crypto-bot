# Crypto event kalendar

Prvi modul alata: skuplja nadolazeće događaje koji mogu pokrenuti memecoin pumpe, daje svakom hype ocjenu 0 do 100 i ključne riječi (tickere) po kojima se traže tokeni.

## Pokretanje

Treba samo Python 3.10+ i internet, bez dodatnih paketa i bez API ključeva.

```
python3 run_calendar.py --days 14 --top 40
python3 run_calendar.py --start 2026-10-07 --days 10   # backtest, npr. oko Kirkova rođendana
python3 -m unittest discover -s tests                   # test bez interneta
```

Izlaz: `output/calendar-<datum>.md` (tablica), `output/calendar-<datum>.json` i baza `calendar.db` (SQLite).

## Izvori (svi besplatni, bez ključa)

| Izvor | Što daje | Domena |
| --- | --- | --- |
| Wikipedia "On this day" | Rođendani i godišnjice smrti poznatih osoba | api.wikimedia.org |
| Wikidata | Koliko je osoba poznata (broj Wikipedija) | www.wikidata.org |
| Wikipedia pageviews | Interes zadnjih 30 dana i trend | wikimedia.org |
| Polymarket | Događaji s datumom i volumenom oklada | gamma-api.polymarket.com |
| RocketLaunch.live | Lansiranja raketa (SpaceX itd.) | fdo.rocketlaunch.live |
| `event_calendar/events_manual.json` | Ručno dodani događaji (Kirk, Elon, Trump, praznici, Tesla Roadster) | nema |

Novi događaj dodaš u `events_manual.json`. `"recurring": true` s datumom `MM-DD` ponavlja ga svake godine; `"date": null` znači da datum još nije potvrđen.

## Hype ocjena

Zbroj: slavnost osobe (do 25), pregledi na Wikipediji (do 15), rast interesa (do 10), volumen na Polymarketu (do 20), veza s kripto publikom (do 25, popis u `enrich.py`), ručno dodan događaj (10), blizina datuma (do 5). Težine su početna pretpostavka i treba ih podesiti backtestom.

## DexScreener (`run_dex.py`)

Za svaki događaj iz kalendara nađe tokene vezane uz njega na DexScreeneru (javni API, bez ključa, https://docs.dexscreener.com/api/reference) i označi koji je vjerojatno pravi, a koji su kopije.

```
python3 run_dex.py scan --min-liq 5000          # događaj -> tokeni iz najnovijeg kalendara, samo Solana
python3 run_dex.py scan --chain ''              # svi lanci
python3 run_dex.py trending                     # top boostovi, novi profili, trending teme
python3 run_dex.py token <adresa>               # svi parovi jednog tokena + plaćene narudžbe (boost, ads)
```

`scan` piše `output/dex-<datum>.md`, `.json` i tablicu `event_tokens` u `calendar.db`.

Kako radi: iz događaja uzme ime (subject) i ključne riječi, izbaci šum (mjeseci, dani, BTC, SOL i sl., popis `NOISE` u `dexscreener/match.py`) i svaki pojam pretraži jednom. Token pripada događaju ako mu je simbol jednak pojmu ili ime sadrži pojam. Odbacuje prašinu (likvidnost ispod `--min-liq`), mrtve parove (volumen ispod $100) i velike tokene (mcap iznad $500M, npr. wrapped BTC). Ostale rangira ocjenom 0-100: starost, likvidnost, volumen, broj transakcija, omjer kupnji i prodaja, kazna za volumen višestruko veći od likvidnosti (wash trading), društvene mreže, CTO, točan simbol. Prvi je "pravi", ostali "kopije". Broj holdera i kvaliteta walleta nisu tu (to radi Helius rug filter). Ako kalendar ima `token_likelihood`, događaji se obrađuju tim redom. Klijent (`dexscreener/client.py`) pokriva sve endpointe iz dokumentacije i sam usporava upite ispod limita (60 ili 300 u minuti), a odgovore kešira 60 s (`DEX_CACHE_TTL`).

## Praćenje prije eventa (`run_watch.py`)

Od oko 14 dana prije većeg eventa prati tokene koje je `run_dex.py scan` vezao uz taj event (pravi token i dvije najjače kopije, samo eventi s `token_likelihood` od barem 0,4). Cilj je vidjeti rastu li volumen, kupnje i ulazak dobrih walleta kako se event bliži.

```
python3 run_watch.py sync              # newest output/dex-*.json -> popis za praćenje
python3 run_watch.py snap              # snimka s DexScreenera (besplatno)
python3 run_watch.py snap --wallets    # + novi kupci preko Heliusa (~10 kredita po tokenu)
python3 run_watch.py analyze           # korelacije -> output/watch-<datum>.md
python3 run_watch.py run               # petlja na serveru: snimka svaki sat, walleti svakih 6 h
```

Sve ide u `watch.db`: `watch_tokens` (što se prati), `watch_snapshots` (snimke kroz vrijeme), `watch_buyers` (svaki kupac s tierom i oznakama iz `wallets.db`) i `watch_correlation` (Spearmanova korelacija približavanja eventa s volumenom, kupnjama, novim kupcima, smart walletima i cijenom, plus zaključak). Na sučelju je stranica **Prije eventa** (`/watch`). Krediti: oko 40 tokena × 4 provjere dnevno × 10 = ~50k mjesečno, a `--credits` (zadano 3000) ograničava jedno pokretanje.

## Hype skener (`run_hype.py`)

Rano otkrivanje tokena koji rastu na valu hypea, smart money walleti i petlja za mjerenje uspješnosti.

```
python3 run_hype.py scan                      # jedan prolaz: kandidati, značajke, ocjena 0-100, zapis u bazu
python3 run_hype.py watch --interval 120      # skeniranje + praćenje cijena u petlji, alarm za score >= 60
python3 run_hype.py learn --auto 5            # smart walleti: rani kupci nedavnih pobjednika, ocijenjeni po PnL-u
python3 run_hype.py learn <mint> <mint>       # isto, za tokene koje sam zadaš (npr. GTA6)
python3 run_hype.py buyers <mint>             # prvi kupci tokena, smart walleti označeni
python3 run_hype.py wallet <adresa>           # win rate, PnL u SOL, broj 2x+ trejdova, bot ili ne
python3 run_hype.py eval --fit                # uspješnost signala po ocjeni i po značajki, paper trading, nove težine
```

Kandidati: novi DexScreener profili i ažuriranja profila, boostovi, community takeoveri (CTO), tokeni 3 teme (metas) koje najbrže rastu u zadnjem satu, i CA adrese iz Telegram kanala (`hype/channels.txt`).

Značajke (0 do 1, težine u `hype/weights.json`): `fresh` starost, `turnover` volumen 1h / likvidnost, `buy_pressure` udio kupnji, `momentum` rast 1h, `activity` broj transakcija, `paid` plaćeni DexScreener profil/boost, `socials`, `narrative` broj kopija iste teme u 72 h, `calendar` pogodak ključne riječi iz kalendara, `telegram` broj kanala koji su objavili CA u 6 h, `smart_money` broj poznatih smart walleta među ranim kupcima, `revival` stari token (>3 dana) kojem je zadnji sat volumena višestruko iznad prosjeka, `takeover` revival + CTO ili novi profil, `x_buzz` broj različitih autora na X-u koji spominju CA ili $TICKER, influenceri (10k+ pratitelja) i engagement.

X buzz ide preko Apify actora `apidojo/tweet-scraper` (oko $0.40 na 1000 tweetova, treba `APIFY_TOKEN`), samo za top `--x-top 5` kandidata sa score >= 40, keš 15 min. `watch` svake 2 min s tim postavkama troši najviše oko $2 na sat, realno manje jer se keš ponavlja.

Baza je `hype.db` (odvojena od `calendar.db`, jer SQLite na dijeljenom disku loše podnosi istovremeno pisanje).

Petlja poboljšanja: `watch` bilježi svaki signal (`hype_signals`) i cijene (`hype_snapshots`). `eval` za svaki token gleda prvi signal i mjeri max rast i stanje nakon 24 h (rug = likvidnost pala ispod 20%). `eval --fit` uči težine logističkom regresijom i piše `hype/weights.suggested.json`; isprobaj ga s `scan --weights`, a ako paper trading bude bolji, kopiraj u `weights.json`.

Alarmi u tvoj Telegram bot: postavi `TELEGRAM_BOT_TOKEN` i `TELEGRAM_CHAT_ID`. Helius (`HELIUS_API_KEY`) treba za `learn`, `buyers`, `wallet` i smart money provjeru; svaki poziv troši oko 100 kredita.

Izbornik dashboarda ima pet grupa (Pregled, Tokeni, Walleti, Trading, Sustav); stranice grupe su u drugom redu, pa su sve stare rute i dalje tu. Pregled pokazuje samo demo rezultat, istaknute po klasi i tablicu tokena kroz analize; rast baze, klasteri walleta i stanje baza su sklopljeni ispod.

## Slojevita analiza (`tiers/`)

Svaki token koji sken vidi dobiva red u `token_tier` (hype.db): **klasu** (`moonshot` mcap < $150k i mlađi od 3 dana, `stabilni` mcap > $2M i stariji od 7 dana, `event` pravi token iz kalendara, inače `rizican`; granice u `tiers/config.json`), **razinu** do koje je stigao (T0 besplatno sito, T1 rani kupci preko Heliusa, T2 pun rug filter ili X buzz, T3 duboko) i koliko je Helius kredita potrošio. Skupe provjere u `run_hype.py scan` i Apify izvori dobivaju samo tokene koji su prošli T0; `run_paper.py` upisuje T2 kad napravi rug check.

T0 pada **samo na mehanici ruga** (aktivan mint ili freeze authority, LP nezaključan izvan launchpada; pump.fun tokeni prolaze bez poziva, ostali preko RugCheck izvještaja keširanog 6 h). Likvidnost, top 10 holderi, dev udio i bundleri nisu pragovi nego značajke za učenje. Tokeni ispod `--min-liq` ili iznad `--max-mcap` ulaze u `token_tier` kao `t0=nije` i `track` im prati cijenu, pa `eval` vidi i što su pragovi propustili. Oblik puta do mcapa iz snimaka (`put_brzina`, `put_skokovitost`, `put_zadrzavanje`) ulazi u značajke s težinom 0 dok ih fit ne nauči.

### Puls i snaga (`hype/pulse.py`)

Token koji je stigao do razine 1 u zadnjih 24 h ostaje u **svakom** skenu (svake 2 min) i kad ga feedovi više ne nose (izvor `zadrzan`, najviše 30 tokena, `tiers/config.json` → `zadrzi`), pa su njegova ocjena, confidence i Šansa uvijek svježi. Svaki prolaz upisuje red u `token_pulse` (cijena, mcap, volumen 5 min / 1 h, kupnje i prodaje), a broj holdera dolazi iz Heliusa (`getTokenAccounts`, 10 kredita po stranici, najviše 3 stranice) najviše svakih 30 min po tokenu i do 20.000 kredita dnevno, ili besplatno s pump.fun ploče. Iz te serije (zadnjih 6 h) nastaju značajke koje petlja uči kao i sve druge: `snaga_volumen` i `snaga_txn` (zadnji sat prema najboljem satu), `rast_holdera` (%/h, 10 = 1) i `organski` (novi holderi po transakciji; wash-trading vrti transakcije bez novih holdera). Početne težine 6/6/8/6. Rani kupci preko Heliusa keširaju se 6 h po tokenu, pa zadržani token ne plaća tu provjeru svaka 2 min. Puls se čuva 7 dana.

## Petlja učenja (`run_learn.py`, `learn/`)

Ništa ručno. `run_learn.py loop` jednom dnevno (05:00 UTC, `learn/config.json`): za svaku klasu izračuna **skok** (maksimalni rast u 24 h u gornjih 15% ishoda te klase u zadnjih 30 dana; početni pragovi dok klasa nema 20 ishoda), fita težine hype ocjene logističkom regresijom i primjenjuje ih **samo** ako klasa ima barem 200 ishoda, svaka težina se pomiče najviše 20% po runu, i nove težine imaju bolju preciznost gornje petine na obje vremenske polovice. Naučene težine su u `$LEARNED_DIR/weights.<klasa>.json` (na Render disku), sken ih čita po klasi; `.prev` ostaje za rollback, koji se sam dogodi kad primijenjene težine nakon 2 runa bez poboljšanja gube od prethodnih. Svaki run je u `learn_runs` (hype.db). Stranica **Učenje** pokazuje lift po značajki, udio skokova po rasponu sirovih vrijednosti (likvidnost, mcap, top 10, bundleri, smart kupci, skokovitost), parove značajki, povijest težina i "što smo propustili" (tokeni bez plaćene provjere koji su ipak skočili). `run_learn.py status|missed|fit --dry` za terminal.

## Walleti i copytrading (`run_wallets.py`)

Registar svih walleta koje alat vidi (hype, rug filter, rani kupci pobjednika, ručno), ocjena profitabilnosti, PnL kroz vrijeme i shortlista za copytrading. Baza je `wallets.db` (tablice `wallets`, `wallet_sightings`, `wallet_trades`, `wallet_pnl`, `helius_credits`). Drugi moduli upisuju walleta preko `wallets/store.py` (`observe`, `label`), pa nema duplih tablica.

```
python3 run_wallets.py harvest --feeds              # hype.db smart walleti + rani kupci tokena koji su narasli (mcap >= 1M)
python3 run_wallets.py score --credits 3000         # ocijeni red walleta unutar budžeta Helius kredita
python3 run_wallets.py top                          # rang lista (--style bot|sniper|scalper|swing, --by score)
python3 run_wallets.py top --signals                # profitabilni botovi i snajperi (tier S)
python3 run_wallets.py copy --n 5                   # shortlista -> output/wallets-copy-<datum>.md
python3 run_wallets.py wallet <adresa>              # jedan wallet odmah, s otvorenim i zatvorenim pozicijama
python3 run_wallets.py history <adresa>             # ocjena i PnL kroz vrijeme
python3 run_wallets.py label <adresa> rugger        # ručna oznaka (--off makne)
python3 run_wallets.py credits                      # potrošnja kredita ovaj mjesec i procjena
```

Kako se računa:
- Povijest walleta: Helius `getTransactionsForAddress` (10 kredita na 100 transakcija, filtri na serveru: samo uspješne i samo one koje mijenjaju token stanje). Stari Enhanced endpoint (`hype/onchain.py`) košta 100 kredita po pozivu, dakle 10x više.
- Prvi pogled: prvo jedna stranica (10 kredita). Ako je 100 transakcija stalo u manje od 2 h, to je bot i stajemo. Inače do 3 stranice, zadnjih 30 dana.
- Ponovna provjera: samo transakcije novije od zadnje spremljene (obično 10 kredita). Tier A (copy >= 60) svakih 6 h, B dnevno, C tjedno, D nikad osim ako ga neka analiza opet vidi.
- PnL po tokenu prosječnim troškom: realizirani = prodano - udio uloga; nerealizirani = preostali tokeni x cijena s DexScreenera (besplatno) - preostali ulog; bazen ispod $1000 likvidnosti = 0 (rug). Tokeni poslani na drugi wallet se ne broje (PnL nepoznat).
- `score` 0-100: zatvoreni PnL, ROI na ulog, win rate (stisnut prema 50% kad je malo trejdova), profit factor, broj 2x+, i ne ovisi li sve o jednom trejdu. Ispod 10 zatvorenih pozicija ocjena se razmjerno smanjuje.
- `copy_score`: score puta koliko se wallet stvarno da kopirati. Nula za botove, minus PnL i oznake `bot, rugger, bundler, insider, dev, sniper, cex, mev, funder_of_rugger`. Kazne: drži < 2 ili < 10 min (kopija kasni sekundama), previše ili premalo trejdova, neaktivan 5+ dana, sitne kupnje, puno besplatno primljenih tokena. Bonus +5 za svaki dodatni pobjednik u kojem je bio rano.

Stil (`style`): `bot` (300+ trejdova dnevno ili drži < 30 s), `sniper` (kupio u prvim sekundama tokena), `scalper` (drži < 10 min), `swing`. Profitabilni botovi i snajperi (score >= 40) dobiju tier S: ne kopiraju se (prebrzi su), ali se prate svaki dan i služe kao signal. `wallets.store.signal_wallets()` ih vraća, a `run_hype.py scan` ih broji u `smart_money` zajedno s ostalim dobrim walletima. Kod botova se plaća dodatna stranica povijesti samo ako je prva stranica u plusu.

Budžet: `HELIUS_MONTHLY_CREDITS` (zadano 10.000.000, Helius Developer od 2026-10-30) i `WALLET_CREDIT_SHARE` (zadano 0.15, tj. 1,5M mjesečno; ostatak ide rug filteru i hype modulu, cilj ukupno 5-7M). Jedan `score` prolaz zadano troši do 20.000 kredita (oko 1.000 walleta). `score` staje kad potroši svoj dio. Prvi stvarni prolaz 2026-10-30: oko 200 walleta za 3.500 kredita (prosjek 17 po walletu).

## KOL-ovi na X-u (`run_kol.py`, `kol/`, `kol.db`)

Svaki X post s CA tokena postaje poziv: autor, pratitelji, link na post, i što su cijena i volumen napravili nakon njega.

```
python3 run_kol.py once        # jedan krug: collect, search, measure, score, flows
python3 run_kol.py top         # ljestvica KOL-ova po moći poziva
```

- Pozivi: tweetovi koje bot već plaća (`x_buzz` u hype.db apify_cache) + webhook KOL monitora, plus dvije male pretrage (Apify izvori `kol_search` i `kol_timeline`, ~$0.24/dan): ponovna pretraga tokena koje KOL-ovi zovu i zadnji postovi najboljih KOL-ova.
- Hvalisanje ("15x on $X", "115x $X") se odvaja od poziva i ne ulazi u ocjenu.
- Cijena i volumen 2 h prije, 1/6/24 h poslije i max u 24 h: GeckoTerminal 5-min svijeće (besplatno).
- Grupni poziv: 2+ autora na istom tokenu unutar 30 min. Parovi KOL-ova koji često zovu zajedno.
- Helius tokovi oko jakih poziva (`flows_per_day`, ~40 kredita svaki): insajderi kupili sat prije i prodali u poziv; na 3+ tokena = rotacijski dev, ide u wallets.db s oznakom insider.
- Moć poziva 0-100 i moć po pratitelju; težine u `kol/config.json`. Signal `kol_group` ulazi u hype ocjenu.
- Dashboard: `/kol`, `/kol/<handle>`, i "Tko ga je zvao na X-u" na stranici tokena.

## Rug filter (`run_rug.py`)

Za svaki token kaže je li rug, bundle ili lažni volumen, i zašto. Spaja RugCheck (besplatno), Helius (`HELIUS_API_KEY`) i DexScreener.

```
python3 run_rug.py token <mint>        # jedan token -> output/rug/<mint>.md i .json
python3 run_rug.py scan --top 10       # najbolji tokeni iz najnovijeg output/dex-YYYY-MM-DD.json -> output/rug-<datum>.md
python3 -m unittest tests.test_rug_offline
```

Presuda: `ODBAČEN` (pao tvrdi filter), inače ocjena 0 do 100: `PROLAZI` (75+), `OPREZ` (50 do 74), `VISOK RIZIK` (ispod 50). Uz presudu ide popis crvenih zastava, dobrih znakova i najveći ulaz za oko 5% proklizavanja.

Što provjerava (`rugfilter/`):
- Tvrdi filteri: mint ili freeze authority nije ugašena, RugCheck "rugged", bundle iznad 20% supplyja, jedan klaster iznad 25%, serijski kreator (10+ tokena, manje od 10% živih), dev ili njegov izvor SOL-a već označen kao ruger, wash score 60+, likvidnost ispod $5k.
- Kreator: prvih 200 transakcija tokena (Helius, od najstarije) daje dev wallet i blok kreacije. Zatim zadnjih 100 tokena koje je dev napravio i koliko ih još ima likvidnost (DexScreener), koliko je kupio na startu, prodao, prebacio na druge wallete i još drži, star li je wallet i tko ga je financirao.
- Bundle i snajperi: kupnje u istom bloku kao kreacija (bundle) i u prvih ~8 s (snajperi), u % supplyja.
- Holderi i klasteri: top 10 bez poola i burna, fresh walleti (prvi put viđeni manje od 3 dana prije kreacije), klasteri walleta s istim izvorom SOL-a ili financiranih od deva. Izvor koji drži 5.000+ SOL je burza i ne povezuje walleta. RugCheck insajderske mreže se broje samo do 50 walleta (veće su routeri).
- Organski volumen (zadnjih 300 tradeova): koliko volumena rade walleti koji i kupuju i prodaju, udio top 5 walleta, ponavljanje iste veličine tradea, tradeovi u pravilnom ritmu (bot), tradeovi po walletu. Iz toga wash score 0 (organski) do 100 (lažan).
- Kvaliteta walleta: svaki dev, bundler, snajper, rani kupac i holder se upisuje u zajednički registar `wallets.db` (`wallets/store.py`). Dev s dokazanim rugom dobiva oznaku `rugger`, njegov izvor `funder_of_rugger`, bundleri `bundler`, pa sljedeći token s istim walletima odmah dobiva crvenu zastavu. Walleti s tier A iz `run_wallets.py` (ili popis u `smart_wallets.json`) daju plus bodove.

Rezultati idu i u `rug.db` (tablica `rug_reports`). Trošak: oko 800 Helius kredita za novi token (5 Enhanced poziva po 100 i ~25 jeftinih RPC poziva), ponovna provjera unutar 5 min je iz cachea. Besplatni plan (1M kredita) je oko 1.000 tokena mjesečno uz pola budžeta za walleta. Pragovi su u `rugfilter/score.py` i treba ih podesiti backtestom.

## Demo trading i dnevno učenje (`run_paper.py`)

Bot "kupuje" i "prodaje" odabrane tokene virtualnim novcem (start $1000, $50 po ulazu) i svaki dan sam pregleda greške i predloži bolje postavke. Nema pravog novca ni walleta.

```
python3 run_paper.py run --scan          # sve u jednoj petlji: hype scan, ulazi, cijene svake minute, pregled u 08:00
python3 run_paper.py status              # otvorene pozicije i stanje demo računa
python3 run_paper.py review              # dnevni pregled odmah (output/paper/review-<datum>.md)
python3 run_paper.py apply               # prihvati predložene postavke (stara se sprema kao backup)
```

S `--scan` ne pokreći usput `run_hype.py watch` (inače bi oba pisala u hype.db).

Ulazi: hype signali (`hype.db`) sa score >= `min_score` i "pravi" tokeni događaja koji su za 0 do `event_days` dana (najnoviji `output/dex-*.json`, score >= `dex_min_score`). Prije ulaza rug filter (postojeći izvještaj iz zadnjih 6 h ili nova provjera, najviše `rug_budget_per_day` (200) dnevno jer troši Helius kredite; provjeravaju se i preskočeni tokeni sa score >= `rug_shadow_min_score`, da pregled može ocijeniti filter); presude iz `block_verdicts` se ne kupuju. Svaki kandidat dobije jednu odluku: `taken` ili `skip_score`, `skip_liq`, `skip_mcap`, `skip_rug`, `skip_full`. Preskočeni se prate dalje 24 h, da se vidi što su filteri spasili, a što propustili.

Izlazi (`paper/config.json`): stop loss -35%, pola na 2x i četvrtina na 4x, nakon prvog TP-a stop na nulu, trailing 30% od vrha kad je bio +50%, najviše 24 h, rug (likvidnost pala ispod 20%) = izlaz odmah. Svaka kupnja i prodaja plaća 1% naknade i proklizavanje po veličini poola. Trejd zadržava pravila s kojima je otvoren.

Dnevni pregled: rezultat, greške po vrsti (rug, kasni ulaz nakon skoka, profit vraćen, mrtav trejd), propušteni pobjednici s razlogom preskoka, tablica filtera ("da smo ušli u sve"), rug presuda vs. stvarni ishod, izvori signala, lift značajki. Prijedlozi: prag ulaza, stop/TP/trailing/trajanje, koje rug presude blokirati, minimalna likvidnost, nove težine hype ocjene (`paper/weights.suggested.json`). Prijedlog prolazi samo ako ima barem 10 tokena iza sebe i bolji je i u starijoj i u novijoj polovici podataka. Svaka demo kupnja, prodaja i dnevni sažetak zapisuju se u `output/paper/journal.log` (vidljivo i u UI-ju, koji čita `paper.db`). Telegram je isključen; uključuje se s `PAPER_TELEGRAM=1` ili `review --telegram`. Sve naučeno se skuplja u `output/paper/lessons.md`. Baza je `paper.db`.

Svaki trejd pamti market cap na ulazu i na izlazu (`entry_mcap`, `exit_mcap` u `paper.db` i `league.db`; stare baze se dopune iz spremljenih cijena). Dashboard ih pokazuje u Demo tradingu i u Natjecanju.

DCA prijedlog (kupnja u padu, `paper/dca.py`, pravila u `config.json` pod `dca`): kad je otvorena pozicija 20% ili više u minusu, ali barem 3 postotna boda iznad stop lossa, likvidnost je još barem 60% ulazne, cijena je već odskočila 8% od dna i trejd je star barem 20 min, bot zabilježi prijedlog da se dokupi pola uloga. Najviše jedan po trejdu, nikad nakon prvog TP-a. Prijedlog se ne izvršava; dnevni pregled mjeri što bi dokup donio da je prodan zajedno s trejdom i kaže isplati li se (barem 10 signala, isti rezultat u obje polovice podataka). Signal se pokazuje i igračima u Natjecanju ako drže isti token.

## Prave kupnje (`run_trade.py`)

Kupuje i prodaje preko Jupiter Ultra API-ja (sve Solana burze, uključujući pump.fun krivulju; sam bira slippage i priority fee i šalje transakciju, ne treba RPC ni Jito). Ne odlučuje sam: `follow` prati `paper.db` i svaku demo kupnju iz `run_paper.py` ponovi kao pravu, a svaku demo prodaju (take profit, stop loss, trailing, rug) kao pravu prodaju. Pravila ulaza i izlaza su i dalje samo u `paper/config.json`.

```
python3 run_trade.py check                     # mod, wallet, stanje, radi li Jupiter
python3 run_trade.py follow                    # uz `run_paper.py run --scan` u drugom procesu
python3 run_trade.py buy <mint> --sol 0.05     # ručna kupnja kroz iste limite
python3 run_trade.py sell <mint> --frac 0.5
python3 run_trade.py status                    # pozicije i PnL u SOL, odvojeno DRY i LIVE
```

Limiti u `trade/config.json`: `size_sol`, `max_sol_per_trade`, `max_sol_per_day`, `max_open`, `min_sol_reserve` (ostaje za fee), `max_cost_pct` (price impact + fee iz quotea), `max_signal_age_s` (stari signal se ne kupuje). Datoteka `trade/STOP` je kill switch: nema novih kupnji, prodaje i dalje idu.

Dry-run je zadano: dohvati se pravi quote i zapiše u `trade.db`, ništa se ne potpisuje. Live traži sve troje: `"mode": "live"` u configu, `TRADE_LIVE=1` i `SOLANA_PRIVATE_KEY` (zaseban wallet samo za bota) u env secrets servera. `SOLANA_PUBLIC_KEY` je dovoljan za dry-run. Opcijski: `JUP_API_KEY` (veći limiti), `SOLANA_RPC_URL` ili `HELIUS_API_KEY` za stanje walleta. Paketi: `pip install solders base58`.

Prvi stvarni dry-run 2026-10-30: 0.05 SOL u pump.fun token i natrag, ukupni trošak oko 2.8%.

### Apify izvori (`hype/sources.py`, `hype/apify.py`)

Uz `APIFY_TOKEN` skener koristi i plaćene izvore. Svaki ide kroz zaštitu budžeta: dnevni limit po izvoru u `hype/apify.json`, a sve staje kad do mjesečnog limita Apify računa ostane manje od `monthly_reserve_usd`. Svaki run se zapisuje u `apify_runs` (hype.db), a rezultati se keširaju.

| Izvor | Actor | Što daje | Značajka |
| --- | --- | --- | --- |
| pump.fun | `muhammetakkurtt/pump-fun-token-scraper-monitor` | trending i graduating tokeni (mlađi od 3 dana, filtrirani po bundlerima i devu), broj KOL walleta | kandidati, `kol_wallets` |
| X buzz | `apidojo/tweet-scraper` | tweetovi po CA i $tickeru za top kandidate | `x_buzz` |
| X trendovi | `karamelo/twitter-trends-scraper` | trending teme | `x_trend` (ime tokena = trend) |
| Google Trends | `apify/google-trends-scraper` | rast pretrage imena (24 h vs 6 dana), 1 token po prolazu | `search_trend` |
| GMGN | `muhammetakkurtt/gmgn-copytrade-wallet-scraper` | 200 profitabilnih walleta dnevno, ocijenjeni u `smart_wallets` | `smart_money` |
| KOL tracker | `xquik/x-twitter-crypto-tracker` | tweetovi odabranih KOL-ova u realnom vremenu, preko webhooka `/hook/kol` | `kol_x` |

Ocjena je ponderirani prosjek samo izmjerenih značajki: provjera koja nije rađena (npr. X buzz za token izvan top 5) ne ulazi u nazivnik.

KOL tracker je isključen dok mu ne daš budžet (`daily_usd.kol_monitor`) i popis računa. Svaki praćeni račun košta oko $3.24 mjesečno. Pokretanje: `KOL_HOOK_KEY=... python3 run_hype.py kol --handles a,b --base-url https://<dashboard>`; zaustavljanje s `--stop`.

Stranica **Zadnji sken** u dashboardu (`run_ui.py`, `/radar`, grupa Tokeni) prikazuje kandidate iz zadnjeg prolaza s razlozima i rizicima jednostavnim jezikom, narative, smart money, radi li algoritam i Apify potrošnju.

## Tržište: volumen po platformama (`run_market.py`)

Koliko se trejda na kojem launchpadu (pump.fun, LaunchLab = bonk.fun, Meteora DBC = Bags/Believe, StonkFun…), u kojim
terminalima (Axiom, GMGN, Photon, BullX, Trojan…, samo Solana dio) i na cijelom Solana DEX tržištu, plus cijena SOL.
Izvor je DefiLlama (besplatno, bez ključa), pa ništa ne ide u usage.db. Podaci idu u `market.db`.

```
python3 run_market.py collect          # jedno očitanje (prvi put skine 400 dana povijesti)
python3 run_market.py loop --every 60  # server: svaki sat
python3 run_market.py report           # platforme, režim, provjera hipoteze
```

Režim tržišta (`market/regime.py`): prosjek tri ranga u zadnjih 90 dana (volumen launchpada 7 d, volumen cijele Solane 7 d,
rast launchpada tjedan na tjedan), 0-100; 66+ vruće, 33 i manje hladno. Za scoring: `regime.at(ts)["score"] / 100`
(ili `regime.feature(ts)`) je značajka `market_regime` za trenutak ts, iz zadnjeg punog dana prije ts (bez gledanja u budućnost).
Hipoteza "kad raste volumen na Solani, trejda se više shitcoina" provjerava se svaki sat korelacijom dnevnih promjena
(Solana DEX bez PumpSwapa naspram launchpada). Stranica `/market` (Tržište) pokazuje sve to i demo tradeove po režimu.

## Status

Logika je testirana na izmišljenim odgovorima API-ja (`tests/test_offline.py`). Od 2026-10-30 mreža radi: DexScreener, Polymarket i RocketLaunch odgovaraju; Wikipedia je tad vratila 429 (previše upita).

## Web sučelje (`run_ui.py`)

Lokalni dashboard za analizu: koji su walleti izdvojeni i zašto, raspis ocjene svakog walleta i tokena po slojevima (event, hype, rug filter, paper trading) i stranica sa svim kriterijima i težinama. Samo čita baze (`calendar.db`, `hype.db`, `wallets.db`, `rug.db`, `paper.db`) i `output/`, ništa ne piše, pa može raditi dok bot radi. Bez dodatnih paketa.

```
python3 run_ui.py                                      # http://127.0.0.1:8050
python3 run_ui.py --port 9000
UI_PASSWORD=tajna python3 run_ui.py --host 0.0.0.0     # na VPS-u, s lozinkom (korisničko ime bilo koje)
ssh -L 8050:127.0.0.1:8050 korisnik@vps                # sigurnije: tunel, pa otvori http://127.0.0.1:8050 lokalno
```

Stranice: Pregled, Walleti (copy lista, pragovi se mogu mijenjati u formi), detalj walleta (gdje je viđen, raspis ocjene i copy ocjene, pozicije, povijest), Tokeni, detalj tokena (organska ocjena, hype značajke × težine, rug razlozi, walleti), Eventi (raspis hype ocjene), Paper, Kriteriji (težine se čitaju uživo iz koda), Izvještaji (`output/*.md`). Raspisi ocjena ponavljaju formule iz `wallets/pnl.py`, `dexscreener/match.py` i `event_calendar/enrich.py` (`ui/explain.py`); uz svaki je i ocjena spremljena u bazi, pa se razlika odmah vidi ako se formula promijeni.
