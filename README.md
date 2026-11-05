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
- `score` 0-100: zatvoreni PnL, ROI na ulog, win rate (stisnut prema 50% kad je malo trejdova), profit factor, broj 2x+, i ne ovisi li sve o jednom trejdu. Ispod 10 zatvorenih pozicija ocjena se razmjerno smanjuje. Od 5.11. ocjena vidi i otvorene pozicije: nerealizirani rezultat ulazi s pola težine (`scored_pnl_sol`), a "vreće" (otvoreni gubitnici stariji od 7 dana, `bags`) režu ocjenu po svom udjelu u pozicijama; wallet koji prodaje dobitnike, a drži gubitnike više ne izgleda kao genij.
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
- Novčanici uživo (`kol/chainwatch.py`, Helius webhook, `chain.max_wallets`): od 5.11. ne samo javne KOL ljestvice (kol_ids) nego i naši vlastiti ocijenjeni walleti iz wallets.db, po `chain.share` (zadano 50 % ljestvice, 40 % najbolji po copy ocjeni ≥ `min_copy`, 10 % tier S signalni); prazna grupa prepušta mjesta ostalima. Kupnje tih walleta ulaze u pozive kao `w:<prvih 6 znakova>`.
- Ocjenjivanje KOL-ova svakih 20 min čita samo potrebne stupnjeve (ne i tekst objava) i ocjenjuje samo račune čiji su se pozivi promijenili od prošlog kruga (kv `score_mark`); svi se ponovno ocjenjuju najmanje svaka 4 h i kad se promijeni klasifikacija objava.
- Moć poziva 0-100 i moć po pratitelju; težine u `kol/config.json`. Signal `kol_group` ulazi u hype ocjenu.
- Dashboard: `/kol`, `/kol/<handle>`, i "Tko ga je zvao na X-u" na stranici tokena.

**Trending kao izvor (5.11., `kol/trending.py`).** Svaki KOL krug sprema današnje trending tokene (GeckoTerminal
trending pools za Solanu, 3 stranice, 24 h; DexScreener top boosts kao plaćena promocija) u kol.db `trending`, bez
majora i tokena s FDV iznad 100M. Zatim za do 10 tokena po krugu pita X tko je objavio njihovu adresu u zadnjih 7
dana (twitterapi.io, vlastiti dnevni strop `trending.usd` 0,40 $ unutar discovery stropa): ti računi su zvali
pobjednika, prate li se kod nas ili ne, i postaju KOL kandidati (pozivi s izvorom `kol_trend`). Isti popis ulazi u
KOL backfill (`run_kol.py backfill`) kao pobjednici, pa drugi krug pretražuje i trending tokene koje nitko naš
nije zvao.

**Tragovi (5.11., `kol/traces.py`).** Helius webhook sada šalje i TRANSFER transakcije praćenih novčanika
(hype.db `chain_transfers`: token i SOL ≥ 0,05 transferi). Svaki KOL krug: `primio_pa_zvao` (praćeni novčanik primio
tokene, račun ih zvao unutar 24 h), `veza` (transfer između dva praćena novčanika), `supply` (≥ `traces.supply_pct`
% supplya u jednom transferu). kol.db `traces`; na KOL stranici odjeljak "Tragovi"; u skenu značajka
`primio_supply` (težina −6) i pouzdanost −10 ("primio supply, nije kupio").

**X webhook (5.11., `kol/xhook.py`).** twitterapi.io filter pravila ("from:a OR from:b", do 250 znakova, ~15 računa
po pravilu) za do `xhook.max_handles` (100) računa: lista uživo (watch), veliki računi po dosegu, zvijezde, pa
ostatak po ocjeni; botovi nikad. Provjera svakih `interval_s` (30) sekundi; svaki KOL krug uskladi pravila
(dodaj / ažuriraj / isključi stara). Objave stižu na `/hook/x?key=<KOL_HOOK_KEY>` (URL se jednom upiše u
twitterapi.io dashboard → Webhook; piše na /usage) i kroz isti parser idu u kol.db calls (izvor `x_hook`), pa ih
strategije i demo vide u sekundama. Prvih 5 sirovih payloada čuva se u kv `xhook_samples` radi provjere oblika.

**Doseg (5.11., `kol/reach.py`).** Pratitelji + koliko naših dokazanih KOL-ova prati račun (kol.db `follows`,
graf) daju početnu ocjenu računa: base `prior_score` + do 15 za pratitelje (log skala od 5k) + do 15 za praćenje
(2 → +8, 5+ → +15), najviše `reach.prior_cap`. Izmjereni pozivi je preuzimaju kao i prije (shrinkage). Na stranici
KOL-a: "Doseg: N pratitelja, prate ga M naših → početnih X bodova". Demo strategija "Veliki račun zove"
(strat/config.json, `reach.min_followers` 20k i `min_followed_by` 2; botovi nikad) kupuje na njihove pozive i prije
probe, pa se vrijednost signala mjeri protiv kontrole.

**Socijali tokena (5.11., `hype/socials.py`).** Iz DexScreener podataka para: X link kao profil / zajednica / tuđi
tweet / pretraga, Telegram (besplatni pregled t.me/s: pretplatnici, zadnji post, objave; za grupe broj članova),
web, plaćeni profil (slika + header). Značajke `socijali_x`, `socijali_tg`, `socijali_placeni`,
`ozbiljan_projekt` (plaćeni + pravi X profil + TG 50+ s postom u 24 h) i `sumnjivi_socijali` (tweet/pretraga ili bez
TG-a) ulaze u hype ocjenu (težine 4/3/3/10/−6) i u pouzdanost (+12 / −8, vidljivo u Za/Protiv). Telegram se
provjerava za tokene ≥ 50k, najviše 15 novih po skenu (SOCIALS_PROBES), keš 6 h u hype.db `socials`. Demo
strategije "Ozbiljan projekt" i "Sumnjivi socijali" (strat/config.json) mjere obje tvrdnje protiv kontrole.

**Bondani tokeni (5.11., `kol/graduates.py`).** Svaki KOL krug čita PumpSwap poolove s GeckoTerminala (po
aktivnosti i volumenu, 5 stranica, besplatno) u kol.db `graduates`: tokeni koji su diplomirali s pump.funa i nisu
umrli pri lansiranju (bez majora, FDV ≥ 30k). Popis samo raste. Iz njega: masovna sjenovita knjiga uzima
`povijest_bondao` točke (ulaz = trenutak diplomiranja), a `run_wallets.py harvest` dodaje ih u tokene za koje vuče
rane kupce (Helius), pa ti novčanici ulaze u ocjenjivanje, copy liste, webhook i insajdere. Tako povijest
diplomiranih tokena, današnji novčanici i calleri dijele istu bazu i iste ocjene.

**Obrisane objave (5.11., `kol/deleted.py`).** Poziv jednom pročitan ostaje u bazi; ali povijest iz backfilla ili
kasnije čitanje timelinea vidi samo ono što je preživjelo, pa račun koji briše svaki rug izgleda bolje nego što jest.
Zato se izmjereni X pozivi 2+ dana stari provjeravaju po ID-u objave (twitterapi.io, 0,15 $ na 1000, 200 po krugu,
ponovno svakih 14 dana; prazan odgovor za cijelu seriju = greška API-ja, ne brisanje). Nestala objava dobiva
`deleted_ts`. Obrisani pozivi i dalje se broje u svim statistikama; uz to težina `deletes` (−15) oduzima bodove
razmjerno udjelu gubitnika među obrisanima (puno od 5 obrisanih). Na stranici KOL-a: "Briše gubitnike: obrisao N, od
toga M gubitnika". Pozivi iz backfilla ne mogu sadržavati već obrisane objave, pa su po definiciji "preživjeli";
živo čitanje svakih 30 min hvata objavu prije brisanja i to je glavna obrana.

## Masovna sjenovita knjiga (`learn/masovno.py`, `run_learn.py masovno`)

5.11. (Nicholas: "10.000 nevidljivih tradeova dnevno, demo je samo izlog"). Točke odluke u shadow.db iz filtera:
**bondao** (pump.fun → PumpSwap, živi tok), **trending** (kol.db), **KOL poziv** (prvi poziv dana, bez botova),
**praćeni novčanik kupio** (chain_trades), **kontrola** (40 nasumičnih tokena skena ≥ 30k dnevno, mjerilo). Noću
01–06 po Zagrebu i **povijest**: pozivi do 180 dana unatrag i kupnje naših A/B/S novčanika (1.200 točaka po noći).
Nikad svježi pump.fun tokeni prije bondanja, nikad ispod 30k, nikad majori. Putanja cijene: GeckoTerminal 5-min
svijeće (2 poziva po tokenu), po prolazu najviše `per_run_day` (300) odnosno `per_run_night` (500) poziva;
run_sched svakih 30 min. Svaka točka se odigra s živim pravilima izlaza demo bota (`ret`, `hit`) i s fiksnim
varijantama izlaza (brzi, srednji, spori, sat, ljestvica → `points.varijante`). Učenje čita iste točke kao i
dosad (learn/outcomes). Admin: /usage → "Nevidljivi tradeovi" (po izvoru n, pogodak, prosjek, medijan, PF, varijante,
razlika prema kontroli). Log: "masovno: novih točaka …; povijest +N; označeno M (K poziva)".

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

### Povratak u token nakon gubitka (`rules.povratak`, 4.11.)

Token na kojem je demo izgubio nije gotov. Ako u zadnjih 7 dana demo trade zatvoren s gubitkom (≤ −30 %), a token je sad opet živ (hype signal u zadnjih 30 min s prometom ≥ 30 % likvidnosti i u zadnjih 60 min ili smart walleti među kupcima ili praćeni KOL/copy novčanik kupuje), ide mali drugi ulaz (20 $, najviše 2 po tokenu, 60 min pauze nakon izlaska), mjeren kao vlastiti krak `povratak|sesija`. Svaka procjena okidača (mc100k, kol3, aktivni, povratak), kupljena ili ne, zapisuje se u `paper.db trigger_points` i postaje točka sjenovite knjige (`learn/shadow.py`), pa alat uči i na onome što nije kupio.

### Insajderi kao signal (`kol/insiders.py`, strategija `insajderi`, 5.11.)

Novčanici koji su na 2+ tokena kupili sat prije KOL poziva (`kol.db insiders`, iz Helius tokova oko jakih poziva) nisu za kopiranje (prodaju u poziv), ali jesu signal. `profile()` razdvaja insajdera od snajpera (udio kupljenih tokena koji su ikad pozvani, sekunde nakon lansiranja); pravi ulaze u Helius webhook (`chain.share.insajderi`, 20 % mjesta) i u demo strategiju **Insajderi**: 2+ njih kupi isti token unutar 10 min, a nitko ga još nije pozvao → kupnja; izlaz čim neki od njih proda (`chain_trades`) ili po pravilima bota. `sell_timing()` mjeri kad insajderi prodaju u odnosu na 2. i 3. poziv (kandidat za pravilo izlaza); sve je na `/korelacije`. Na vrhu `/wallets` i `/strategije` stoji „Što bih ja napravio” (`ui/preporuka.py`): preporuke s razlogom, pouzdanost po broju podataka, što su demo kopije stvarno zaradile i što se od njegovih kupnji moglo uzeti (+15/+30/+50 % unutar 24 h).

## Živi tok (`run_live.py`, `live/`)

5.11.: PumpPortal WebSocket (`wss://pumpportal.fun/api/data`) daje svaku kupnju i prodaju na pump.fun i PumpSwapu u
sekundi. Novi tokeni su besplatni bez ključa; pretplata na kupnje/prodaje odabranih tokena i novčanika traži
`PUMPPORTAL_API_KEY` čiji je novčanik napunjen s barem 0,02 SOL (pumpportal.fun → API key). Bez ključa proces to
javi u logu i prima samo nove tokene. Proces `run_live.py loop` (start.sh; `LIVE_OFF=1` isključuje) drži jednu vezu i
pretplaćuje se na: tokene koje gledamo (otvorene demo i strategijske pozicije, pa najsvježiji ocijenjeni kandidati
s mcapom ≥ 30k, najviše 150), novčanike koje pratimo (Helius webhook lista + praćeni iz Natjecanja, najviše 200) i
sve nove tokene. Liste se osvježavaju svaku minutu (pretplata/odjava samo za razliku). Zapisuje u hype.db:
`live_trades` (potpis, token, novčanik, strana, SOL, tokeni, cijena u SOL-u, mcap u SOL-u, pool; 48 h),
`live_launches` (novi tokeni, 7 dana), `live_alerts` (24 h) i `live_state` (zdravlje). Trgovine praćenih novčanika
idu i u `chain_trades`, pa insajderi, strategije i praćenja vide pump.fun kupnju i kad Helius kasni ili je lista od
100 adresa puna. Jedan commit u sekundi, ne po tradeu; ponovno spajanje s rastućim razmakom (PumpPortal banira
klijente koji se spajaju u petlji).

**Dump izlaz** (`paper/config.json` → `live`): svake 2 s za otvorene demo tokene: ako je u zadnjih `window_s` (60 s)
prodalo barem `min_sellers` (5) različitih novčanika, prodaja u SOL-u je `sell_ratio` (2,5×) veća od kupnje i cijena
je `drop` (−8 %) ili niže prema prije `ref_s` (5 min), upiše se upozorenje. Demo bot ga čita svakih 5 s u svojoj
niti (`run_paper.live_exits`) i proda sve po DexScreener cijeni s razlogom `zivi_dump`, umjesto da čeka minutni
tick. `cooldown_s` (120) sprječava ponavljanje. `dump_exit: false` ostavlja mjerenje bez prodaje.

Na stranici tokena kutija "Uživo": kupci, prodavači, kupnja/prodaja u SOL-u i neto za 1/5/15 min, presuda u jednoj
rečenici i zadnji dump. Na /izvori red "PumpPortal živi tok" sa zdravljem; na Pregledu brojač tradeova i novih
tokena. `python3 run_live.py status` i `wanted` za provjeru iz terminala.

**Proporcionalna prodaja (5.11.).** `live_trades.balance_after` (PumpPortal `newTokenBalance`) daje udio koji je
novčanik prodao: `live/pulse.sold_fraction` = prodano / (prodano + ostalo). Strategija Insajderi proda isti udio
(najmanje 25 %), sve tek kad novčanik izađe (`strat/config.json` `proportional_sell`). Bez živog stanja (samo
Helius) i dalje prodaje sve.

Što dalje iz istih podataka (još nije): kupci po prozoru kao značajke ocjene, insajderi među svim kupcima gledanih
tokena, prvih 60 s svakog bondanja za rug filter.

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
| GMGN | `muhammetakkurtt/gmgn-copytrade-wallet-scraper` | 200 profitabilnih walleta tjedno (~$0.80 po vrsti, ~$7/mj), ocijenjeni u `smart_wallets` | `smart_money` |
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

**Nadzor procesa (5.11., `start.sh` → `keep`).** Svaki dugotrajni proces (ui, kol, tg, sched, report, paper, live,
trade) ima vlastitu petlju: kad padne, log "nadzor: <ime> završio (izlaz N), ponovno za 30 s" i samo se on ponovno
pokreće. Prije je `wait -n; exit 1` rušio cijeli worker čim bi ijedan proces završio (5.11. dva puta: run_live je
dobio "database is locked" dok je drugi proces sažimao hype.db). Živi tok sada upisuje u jednoj IMMEDIATE
transakciji, a kod zauzete baze zadrži redove u memoriji (do 20.000) i pokuša u sljedećoj sekundi. Redak zdravlja
razdvaja RAM na "procesi" (stvarno zauzeto) i "cache" (kernel ga oslobađa pod pritiskom): 2 GB plana nije pun kad
piše 2000 MB, a Renderova metrika kaže 1 GB.

**Novosti i večernja objava (5.11.).** `share/novosti.json`: svaki unos ima `naslov`/`tekst` (HR, za aplikaciju) i
`naslov_en`/`tekst_en` (EN, za javni X profil); unos bez engleskih polja ne ide na karticu ni u objavu. Javna
kartica `/share/novosti.png?d=YYYY-MM-DD` (`ui/sharecard.py`, Pillow + Inter font iz `ui/static/fonts`) crta
današnje unose; `?lang=hr` za hrvatsku. Objavu preko Buffera radi rutina u claude.ai (tekst u scratchpadu sesije),
samo iz te datoteke, bez internih podataka.

**Makro režim BTC/ETH (5.11., `market/makro.py`).** Svaki sat (run_market collect): DefiLlama dnevne cijene BTC i ETH
(market.db `btc`, `eth`) i satne BTC (`btc_h`). Stanje po imovini: raste (7 d ≥ +3 %, iznad 30-d prosjeka),
konsolidacija nakon rasta (30 d ≥ +5 %, raspon 5 d ≤ 6 %, do 8 % ispod 30-d vrha, 7 d < +3 %), pada (7 d ≤ −5 % ili
BTC −3 % u 4 h), konsolidacija nakon pada, neutralno. Sklonost altovima 0–1 (konsolidacija rasta 1, raste 0,7,
neutralno 0,5, konsolidacija pada 0,3, pada 0), BTC 0,6 + ETH 0,4, spremljeno as-of u `makro`. Ulazi u hype ocjenu
kao značajka `makro` (težina 8) i u demo gate: dok je BTC u "pada", nema novih ulaza (`gate.makro_pad`). Stranica
Tržište pokazuje rečenicu stanja.

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
