# Copy trading i praćenje walleta na Solani: što kažu izvori i što se da provjeriti (10.11.2026.)

Kut pretrage: `pretraga:copy_walleti`. Autor: istraživački agent (repozitorij samo čitan, bez commita).

**Izravan odgovor:** zadatak je ispunjen samo djelomično. Od traženih 15+ pretraga prošle su 3; četvrta je odbijena jer
je zajednički limit WebSearcha (200 po turi, dijele ga svi agenti) potrošen. Iz te 3 pretrage i jednog otvorenog
GitHub izvora izvučeno je 18 tvrdnji; samo 5 ih se oslanja na podatke (retci 2, 3, 4, 5, 8), ostalo su vodiči i
prodavači alata. Smjer se slaže s našim mjerenjem: kopija gubi zbog kašnjenja i zato što dobit s ljestvica većinom
nije tržišno trgovanje, a pragovi iz vodiča (60 % win rate, 30+ tradeova) nisu ničim izmjereni i treba ih testirati
na naših 361 kopirljivih walleta, ne preuzeti.

## Provjereno / Pretpostavka

**Provjereno:**
- 3 uspješne pretrage (extended), 1 odbijena zbog limita. Otvorena 1 stranica: GitHub issue dimasaf/paper-trade #1
  (i README tog repozitorija, bez nalaza).
- WebFetch ne prolazi za romankurnovskii.com, arxiv.org i cryptoslate.com (host nije dopušten u mrežnim postavkama
  sesije); github.com prolazi.
- Stanje koda, pročitano: `wallets/dokazani.py` (RULE: `cut_days` 5, `min_closed` 5, `min_win` 0,5, `min_after` 2,
  `min_hold_min` 10, `max_tpd` 50, `max_bag_share` 0,3); `wallets/pnl.py` (bot = više od 300 tradeova na dan ili
  medijan držanja ispod 0,5 min; `free_token_ratio` iznad 0,3 samo množi `copy_score` s 0,3); `kol/insiders.py`
  (`sniper_secs` 60); `run_trade.py` (PROOF = 10 zatvorenih, 40 % dobitnih); `strat/robust.py` (MIN_CLOSED 100,
  bez 5 najboljih); `trade/config.json` (`max_signal_age_s` 180, `max_cost_pct` 6); `strat` pozicije pamte
  `delay_s` i `wallet_fill`.

**Pretpostavka / ograničenja:**
- Brojke su iz sažetaka pretrage, ne iz otvorenih stranica (osim GitHuba). Videe nisam gledao; nijedan YouTube ni
  X izvor nije došao u ove 3 pretrage.
- Retci 13 do 16: pretraga ne kaže koji od vodiča iznosi koju brojku, pa je izvor "skupina V" (popis ispod tablice).
- Brojke rezultata Kurnovskog i autore arXiv rada nisam vidio u svojim isječcima; navodi ih susjedna datoteka
  `trgovci_youtube.md` (retci 2 i 3).
- Stupac "Kako provjeriti" su prijedlozi; nijedno mjerenje nije pokrenuto (baze u sandboxu su prazne).
- Nije pretraženo (limit): filtri i oznake Cielo, Nansen, Arkham, KOLscan, Birdeye, Solscan, Bubblemaps; Dune
  dashboardi; X threadovi i YouTube o izboru walleta; farm walleti koji mame kopiraše, svježi i bundle walleti;
  ponašanje KOL walleta (dio toga je u susjednim datotekama).

## Tablica tvrdnji

Dokaz: **podaci** = studija, dataset, on-chain analiza; **iskustvo** = trader o vlastitom radu; **mišljenje** = bez
mjerenja (vodiči, prodavači, metodologije).

| # | Tvrdnja (s brojevima) | Tko | Dokaz | Izvori | Kako provjeriti u MemeSonaru |
|---|---|---|---|---|---|
| 1 | Kašnjenje određuje cijenu kopije: ispod 60 ms na vlastitoj infrastrukturi kopija ulazi uz oko 1 % klizanja; na 800 ms preko javnog RPC-a "you copy into their exit". Drugi tekst: tipičan copy-bot kasni 0,5 do 2 s, što je na brzim tokenima presudno. | RPC Fast (prodaje RPC infrastrukturu); članak "Pump.fun Bot Strategies" (autor nepoznat, host ymcawhittier.org, slab izvor; atribucija po isključenju, pretraga ga ne imenuje) | mišljenje (prodavač, bez objavljenog mjerenja) | [RPC Fast](https://rpcfast.com/blog/how-to-build-a-solana-copy-trading-bot), [Pump.fun Bot Strategies](https://ymcawhittier.org/pump-fun-bot-strategies-automated-trading-sniping-and-liquidity-farming-bots-explained/) | `strat` pozicije strategije "dokazani" imaju `delay_s` i `wallet_fill`: premija = naša ulazna cijena / walletova − 1 i PnL po razredima kašnjenja (do 2 s, 2 do 5, 5 do 15, 15 do 60, 60 do 180 s). Naše kašnjenje je u sekundama, ne milisekundama (`poll_s` 1, `max_signal_age_s` 180), pa je pitanje isplati li se išta iznad prvog razreda. Podaci postoje od 9.11.; uzorak je još mali. |
| 2 | Na bonding krivulji klizanje zbog kašnjenja djeluje kao "implicit, progressive tax" koji prebacuje dobit s kopiraša na vođe i MEV botove. Simulacija: 100.000 pokušaja kopiranja 50 najboljih walleta. Zaključak: krivulje stalnog umnoška su "structurally hostile" za kopiranje. Brojke rezultata nisu bile u mom isječku. | Roman Kurnovskii (blog, kvantitativna studija pump.fun krivulje) | podaci (simulacija; rezultate nisam vidio) | [Kurnovskii](https://romankurnovskii.com/en/blog/pumpfun-copy-trading-feasibility/) | Studija je o krivulji, a mi kupujemo bondane tokene iznad 30k $ na AMM poolu: provjeriti vrijedi li isto. Premiju iz retka 1 razrezati po likvidnosti poola pri ulazu (`positions.last_liq`) i po mcap razredu (30 do 100k, 100k do 1M, 1M+). Ako premija ne pada s likvidnošću, uzrok nije krivulja nego gužva kopiraša (redak 6). |
| 3 | "Imitation penalty": kopija nužno trguje na lošijoj točki krivulje i kad kopira odmah, bez kašnjenja. Rad se bavi manipulativnim botovima koji ciljaju kopiraše (naslov rada). | arXiv 2601.08641, "Resisting Manipulative Bots in Meme Coin Copy Trading" (1/2026) | podaci (znanstveni rad; brojke nisam vidio) | [arXiv](https://arxiv.org/pdf/2601.08641) | Faktor prijenosa po walletu: povrat naše kopije / povrat walleta na istom tokenu (`wallet_trades` daje njegov ulaz i izlaz, `strat` pozicije naš). Pravilo za test: wallet ostaje na popisu samo ako je (njegov medijan po tradeu × faktor prijenosa − trošak kruga) > 0 u starijem i u novijem dijelu uzorka. Podaci postoje. |
| 4 | Od 752,5 mil. $ dobiti velikih pump.fun walleta samo 26 % prolazi provjere za obično tržišno trgovanje; studija nije mjerila rezultat kopiraša. Vodiči isto upozoravaju da je PnL mnogih walleta napuhan transferima ("transfer-inflated"). | Bitquery (prenosi CryptoSlate; datum 22.10.2026. navodi susjedna datoteka); upozorenje o transferima: jedan od vodiča skupine V | podaci | [CryptoSlate](https://cryptoslate.com/pump-funs-biggest-winners-may-be-impossible-to-copy-as-752-million-study-exposes-hidden-trading-gap/), [iTechGuides (prijenos istog teksta)](https://www.itechguides.com/pump-funs-biggest-winners-may-be-impossible-to-copy-as-752-million-study-exposes-hidden-trading-gap/) | Realizirani PnL kod nas već ne broji prodaje tokena primljenih transferom (`pnl.positions`), ali `free_token_ratio` iznad 0,3 samo smanjuje `copy_score`; `dokazani.copyable` ga ne gleda. Mjerenje: koliko od 48 dokazanih ima `free_token_ratio` iznad 0,3 i kakav im je rezultat nakon reza prema ostalima. Kandidat za tvrdi uvjet u `copyable`. Bez novog troška. |
| 5 | Samo izvršno klizanje na pump.fun nije jednostrano: od 4.844 valjana tradea 2.294 (47 %) prošlo je po boljoj cijeni od očekivane, 2.144 (44 %) po lošijoj. Postoci su moj izračun iz tih brojeva. | Bitquery (blog o klizanju; stariji tekst, oko sredine 2025.) | podaci | [Bitquery](https://bitquery.io/blog/analyzing-slippage-pumpfun-trading-dynamics) | Razdvojiti dva troška koja danas idu zajedno: (a) izvršno klizanje = ponuda prema stvarnom fillu u `trade.db orders`; (b) premija kopije = walletov fill prema našoj ponudi. Ako je (a) oko nule, a (b) velik, veća slippage postavka ne pomaže; pomaže raniji ulaz ili sporiji wallet. Za (a) trebaju pravi nalozi; u demu je trošak modeliran. |
| 6 | Čim wallet skupi dovoljno pratitelja, njegovi ulazi postaju samoispunjujući: kupnje kopiraša dižu cijenu, a tko kopira kasno daje izlaznu likvidnost izvorniku. | Nathan Baldwin (Medium) | mišljenje | [Medium 1](https://medium.com/@nathan.baldwin_31153/copy-trading-on-solana-how-to-find-alpha-wallets-without-getting-faked-out-by-bots-0bc550f07290), [Medium 2](https://medium.com/@nathan.baldwin_31153/copy-trading-on-solana-how-to-find-alpha-wallets-and-avoid-bots-26182d750bb2) | Za svaki praćeni wallet minutna putanja nakon njegove kupnje (`exits/paths`, 1-min svijeće): medijan povrata od cijene u 1. minuti do 5. i 15. minute. Potpis gužve: skok u prvoj minuti pa pad ispod njegovog ulaza. Kandidat za isključenje: medijan 5-min povrata od naše ostvarive cijene ispod 0 na 10+ kupnji. Fali: broj drugih kupaca u prvih 10 s (tok tradeova po tokenu); prvo izmjeriti s minutnim svijećama. |
| 7 | Wallet kojem je 80 %+ kupnji unutar 3 s od kreiranja tokena je skripta, ne čovjek, i ne može se kopirati. | Nathan Baldwin (Medium; pretraga ne potvrđuje u kojem od dva njegova teksta) | mišljenje (heuristika) | [Medium 1](https://medium.com/@nathan.baldwin_31153/copy-trading-on-solana-how-to-find-alpha-wallets-without-getting-faked-out-by-bots-0bc550f07290), [Medium 2](https://medium.com/@nathan.baldwin_31153/copy-trading-on-solana-how-to-find-alpha-wallets-and-avoid-bots-26182d750bb2) | `kol/insiders.profile` već računa `med_secs_after_launch` (snajper ako je medijan do 60 s); `wallets/pnl` bot = više od 300 tradeova na dan ili držanje ispod 0,5 min. Test: udio kupnji unutar 3 s i unutar 60 s od kreiranja za 361 kopirljiv wallet; koliko ih pravilo 80 % / 3 s hvata, a naša pravila ne. Kako kupujemo samo bondane tokene, isto izmjeriti od trenutka graduacije. Fali: vrijeme kreiranja ili graduacije za dio tokena. |
| 8 | Javni wallet poznatog tradera kao mamac: oko 30 povezanih walleta izvuklo oko 1,74 mil. $ od 7.5.2026. (Cupsey). | Bubblemaps, prenosi LiveBitcoinNews (9.11.2026.) | podaci (tvrdnja firme, nepotvrđena) | [LiveBitcoinNews](https://www.livebitcoinnews.com/bubblemaps-cupsey-side-wallets-1-74m/) | Detalji su već u `trgovci_x_traderi.md` (redak 2) i `trgovci_youtube.md` (redak 5). Mjerenje: walleti financirani iz istog izvora kao praćeni wallet (`kol/flows`, `chain_transfers`) koji prodaju unutar 60 s nakon njegove kupnje. Fali: prodaje nepraćenih walleta na tom tokenu. |
| 9 | Kopiranje traži veću slippage postavku nego obični trade jer ulaziš nakon ciljanog walleta, a cijena se pomakne između njegove i tvoje transakcije. | Trojan (blog, vodič 2026.; platforma živi od naknada) | mišljenje | [Trojan](https://trojan.com/blog/solana-copy-trading-guide-2026) | Umjesto veće tolerancije testirati gornju granicu premije: ne kupi ako je trenutna cijena iznad walletovog filla × (1 + X). Na demo kopijama naći X iznad kojeg je PnL negativan (razredi premije: do 2 %, 2 do 5, 5 do 10, 10 do 20, 20 %+). `max_cost_pct` 6 danas ograničava trošak, ne premiju. Podaci: `wallet_fill` i naša ulazna cijena. |
| 10 | Kopirljivost se mjeri krivuljom "copy decay": ROI vođe prema ROI kopije na kašnjenjima 0,5 / 1 / 2 / 3 / 5 / 10 s i veličinama 0,1 / 0,25 / 0,5 / 1 / 2 SOL, u četiri scenarija: idealno, samo kašnjenje, kašnjenje + klizanje (matematika poola), puni trošak (naknade, priority fee, neuspjele transakcije). | dimasaf (GitHub, specifikacija projekta "paper-trade", issue #1; bez objavljenih rezultata) | mišljenje (metodologija) | [GitHub issue](https://github.com/dimasaf/paper-trade/issues/1) | Naša veličina 0,1 do 0,15 SOL je najmanja ćelija te mreže. Minutne svijeće su pregrube za kašnjenja ispod 10 s; jedini mjereni podatak je naš stvarni ulaz (`delay_s`, `wallet_fill`). Izvještaj: tablica kašnjenje × (ROI kopije / ROI walleta). Fali: cijena po sekundi nakon walletove kupnje; ne kupovati te podatke dok razredi iz retka 1 ne pokažu gdje je rez. |
| 11 | Strategija kopiranja prolazi tek ako: očekivanje nakon svih troškova iznad 0, pesimistični scenarij iznad 0, radi na odvojenom zadnjem razdoblju (30 do 90 dana, datumi zamrznuti unaprijed), profit faktor iznad 1,2 na najmanje 100 tradeova i plus ostaje kad se makne najbolji trade. | dimasaf (isti issue, "research verdict") | mišljenje (metodologija) | [GitHub issue](https://github.com/dimasaf/paper-trade/issues/1) | `run_trade.PROOF` za pravi novac traži samo 10 zatvorenih, PnL iznad 0 i 40 % dobitnih; `strat/robust.py` za status "kandidat" traži 100 zatvorenih i plus bez 5 najboljih. Dva različita praga u istom alatu. Test: koliko praćenja koja danas prolaze PROOF prolazi i stroži skup (profit faktor iznad 1,2, plus bez najboljeg tradea, plus u obje vremenske polovice). Podaci postoje (`league.db trades`, `strat` pozicije). |
| 12 | Signal "više walleta kupilo" smije brojati samo neovisne wallete. Starost walleta, izvor financiranja i obrasci transfera smanjuju povjerenje u wallet, ali nisu dokaz. Ocjena walleta koristi "clean PnL" bez tokena primljenih transferom ili airdropom. | dimasaf (isti issue) | mišljenje (metodologija) | [GitHub issue](https://github.com/dimasaf/paper-trade/issues/1) | `kol/converge` (`n_chain`) i signali ekipa: grupirati wallete po izvoru SOL-a (`chain_transfers`, klasteri rug filtera) i brojati klastere, ne adrese; usporediti pogodak signala "3+ walleta" po adresama i po klasterima. `wallets.first_seen` je naše prvo viđenje, ne prva transakcija; prava starost walleta fali (1 Helius poziv po walletu, prvo izmjeriti trošak). |
| 13 | Prag win ratea: jedan vodič traži iznad 60 %, drugi 40 do 60 % zove realnim. Vodiči se ne slažu i ne objavljuju mjerenje. | vodiči skupine V (60 % je prema susjednim datotekama CoinCodeCap; izvor za 40 do 60 % pretraga ne imenuje) | mišljenje | [CoinCodeCap](https://coincodecap.com/10-best-ways-to-find-profitable-solana-wallets-and-copy-trade) (vjerojatno), ostalo [skupina V](#skupina-v) | 361 kopirljiv wallet: razredi win ratea prije reza (ispod 40, 40 do 50, 50 do 60, 60 %+) prema udjelu walleta u plusu nakon reza i prema profit faktoru. Naš prag je `min_win` 0,5. Ako razred 60 %+ nije bolji od 50 do 60 %, prag se ne diže; ako je razred 40 do 50 % uz visok profit faktor u plusu, win rate zamijeniti profit faktorom. |
| 14 | Minimalni uzorak: 30+ tradeova (vodiči uz GMGN), drugdje 50+ tradeova u zadnjih 90 dana i najmanje 7 dana povijesti računa. | vodiči skupine V | mišljenje | [CoinCodeCap GMGN](https://coincodecap.com/best-settings-for-gmgn-bot) (vjerojatno), ostalo [skupina V](#skupina-v) | Naše pravilo: `min_closed` 5 prije reza, `min_after` 2, `cut_days` 5. Test: postojanost (Spearman prije/poslije, danas +0,42) po broju zatvorenih pozicija prije reza: 5 do 9, 10 do 29, 30+. Pokazuje diže li stroži uzorak pogodak iznad 23 od 29 ili samo smanjuje popis s 48. Ograničenje: dubina povijesti (`history_from`) ovisi o potrošenim Helius kreditima. |
| 15 | Wallet mora biti u plusu u sva tri prozora (1 d, 7 d, 30 d); svaki koji prođe filtre još ručno provjeriti na Solscanu prije kopiranja. | vodiči skupine V | mišljenje | [skupina V](#skupina-v) (popis ispod tablice; koji vodič, pretraga ne kaže) | `wallet_pnl` snimke i `wallet_trades`: realizirani PnL u 1, 7 i 30 dana. Usporediti "dokazan dvaput" (naše) s "plus u sva tri prozora": koji skup ima bolji rezultat u sljedećih 5 dana. Ručnu provjeru zamijeniti onim što već imamo: oznake, `bag_share`, `free_token_ratio`, `top_trade_share`. |
| 16 | Previše tradeova je znak kockanja; razuman tempo je nekoliko tradeova dnevno. | vodiči skupine V | mišljenje | [skupina V](#skupina-v) (popis ispod tablice; koji vodič, pretraga ne kaže) | Rezultat nakon reza i PnL naših kopija po razredima `trades_per_day`: ispod 1, 1 do 5, 5 do 20, 20 do 50. Danas `max_tpd` 50 (`dokazani`), kazna tek iznad 60 (`copy_score`). Ako razred 20 do 50 gubi u kopiji, spustiti `max_tpd`. Podaci postoje. |
| 17 | Wallet s GMGN oznakom `wash_trader` isključuje se bez obzira na ostale brojke; rangiranje samo po profitu je zamka. | khadinakbar (Apify, dokumentacija alata "GMGN CopyTrade Wallets") | mišljenje (dokumentacija alata) | [Apify](https://apify.com/khadinakbar/gmgn-copytrade-wallet-scraper) | GMGN oznake ne spremamo. Vlastiti test iz `wallet_trades`: udio pozicija s 5+ kupnji i prodaja istog tokena unutar sata uz neto PnL oko nule; označiti i izbrojati takve među 361 kopirljivim te usporediti njihov rezultat nakon reza. Scraper bi bio novi trošak: prvo vlastita heuristika. |
| 18 | U GMGN-u uključiti filtar "not bot": automatizirani arbitražni walleti ne mogu se realno kopirati. | CoinCodeCap (vodič za GMGN bot, 2026.) | mišljenje | [CoinCodeCap GMGN](https://coincodecap.com/best-settings-for-gmgn-bot) | Naše pravilo za bota: više od 300 tradeova na dan ili medijan držanja ispod 0,5 min. Test na 354 zatvorene kopije strategije "top_novcanici" (−10,6 % po tradeu): PnL po stilu walleta u trenutku kopije (bot, sniper, scalper, swing) i po `trades_per_day`; koji bi prag (300, 100, 50 na dan) uklonio najveći dio gubitka. Podaci postoje. |

### Skupina V

Vodiči iz druge pretrage; sažetak ne kaže koji iznosi koju brojku:
[CoinCodeCap: 10 best ways](https://coincodecap.com/10-best-ways-to-find-profitable-solana-wallets-and-copy-trade),
[CoinCodeCap: GMGN bot settings](https://coincodecap.com/best-settings-for-gmgn-bot),
[CoinCodeCap: free tools](https://coincodecap.com/free-tools-to-find-profitable-crypto-wallets),
[CoinCodeCap: copy trade any wallet](https://coincodecap.com/how-to-easily-copy-trade-any-solana-wallet),
[Parsebird](https://parsebird.com/essay/rank-crypto-wallets-by-pnl-before-you-copy-trade),
[MadeOnSol](https://madeonsol.com/best/copy-trading),
[Wallet Master](https://www.walletmaster.tools/blog/best-solana-copy-trading-tools/),
[Medium / moiofficial](https://medium.com/@moiofficial/meme-coin-traders-wallets-e06b32799b09).

**Ograde o izvorima:** većina su affiliate vodiči i prodavači alata ili popisa walleta (primjer plaćenog popisa
"insider" walleta: [Gumroad](https://solanabins.gumroad.com/l/bkckxz)). Jedna usporedba alata tvrdi da GMGN nema
dokumentiran PnL filtar na copy-trade funkciji, drugi vodiči opisuju ugrađene filtre: stanje sučelja nije provjereno.
Brojanje izvora: 21 različit link u tablici i skupini V (14 s atribucijom po retku, 7 samo kao dio skupine V); samo
naslov, bez sadržaja: GMGN blog, baransel.dev.

## Već pokriveno u susjednim datotekama (nisu moji izvori, nisam ih provjerio)

- `trgovci_youtube.md` redak 1: raščlamba Bitquery nalaza (51 % dobiti od tokena primljenih transferom, 13 % moguće
  koordinirano); redak 2: kopija oko 3 % po tradeu prema 14 % vođe (arXiv 2601.08641); redak 3: win rate kopije
  46 % uz 0,5 s, 28 % uz 1 s, 4 % uz 5 s (Kurnovskii); redak 7: medijan kopirane pozicije 24 s (uwuu.ai).
- `trgovci_x_traderi.md` redak 1: kopija s 2 min odgode −41 % po tokenu; redak 5: prosječni KOL wallet 42 % win rate
  (MadeOnSol); retci 2 i 3: Bubblemaps o sporednim walletima.

## Najjače tvrdnje (najviše 7)

1. **Kopija je lošija od vođe i bez kašnjenja** (retci 2 i 3, podaci): "imitation penalty" i klizanje kao porez na
   kopiraša. Mjeriti faktor prijenosa po walletu i pratiti samo one čiji prosjek po tradeu pokriva kaznu i trošak.
2. **Dobit s ljestvica većinom nije tržišno trgovanje** (redak 4, podaci): samo 26 % od 752,5 mil. $. Kod nas
   `free_token_ratio` danas samo smanjuje `copy_score`; kandidat za tvrdi uvjet u `dokazani.copyable`.
3. **Prag dokaza prije pravog novca je preblag** (redak 11, mišljenje + stanje koda): izvor traži profit faktor iznad
   1,2 na 100+ tradeova i plus bez najboljeg tradea; naš PROOF je 10 zatvorenih i 40 % dobitnih.
4. **Mjeriti premiju, ne dizati slippage** (retci 1, 5, 9, 10): izvršno klizanje je kod Bitqueryja gotovo simetrično
   (47 % bolje, 44 % lošije), pa gubitak kopije dolazi od pomaka cijene između walletove i naše kupnje. Razredi po
   `delay_s` i gornja granica premije nad `wallet_fill`.
5. **Skripte i wash walleti van, po ponašanju** (retci 7, 17, 18, mišljenje): 80 % kupnji unutar 3 s, oznaka
   wash trader, "not bot". Provjeriti na 354 kopije "top_novcanici" koji bi prag uklonio najviše gubitka.
6. **Praćen wallet postaje izlazna likvidnost** (retci 6 i 8): po walletu mjeriti minutnu putanju nakon njegove
   kupnje; skok pa pad ispod njegovog ulaza = isključenje.
7. **Pragovi iz vodiča nisu dokaz** (retci 13 do 16, mišljenje): 60 % ili 40 do 60 % win rate, 30 ili 50 tradeova,
   1 d / 7 d / 30 d. Svaki testirati na 361 kopirljivom walletu prije nego postane parametar.

## Za nastavak

Fali 12+ pretraga iz zadatka. Nastaviti se može u novoj poruci ili uz veći `CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION`.
Za čitanje punih studija treba dopustiti hostove romankurnovskii.com, arxiv.org i cryptoslate.com u mrežnim postavkama
sesije. Nijedan prijedlog mjerenja ne traži novi plaćeni izvor.
