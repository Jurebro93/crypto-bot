# MemeSonar: stalna pravila (Jure)

- Odgovaraj kratko, na hrvatskom, prvo izravan odgovor; uvijek odvoji "Provjereno" od "Pretpostavka".
- **KONSTANTNO preispituj efikasnost: kako više učiti za manje novca i kako postati profitabilniji.** Prije svakog
  novog troška (API, pretplata, SOL za podatke) izmjeri što stvarno koristimo i predloži jeftiniji način; svaki tjedan
  u izvještaju navedi trošak po izvoru i što je od toga donijelo odluku ili trade. (6.11.2026.)
- Tokeni ispod 30k $ mcapa se ne kupuju automatski (ni Grok); vlasnik ih smije kupiti ručno uz upozorenje i upisan
  razlog (11.11.). Smiju se analizirati i mjeriti u sjeni (scanner od 10k $; 10.11.).
- Ručna kupnja vlasnika nadjačava limite (ulog, strop po tokenu, broj pozicija, dnevni gubitak, trošak, SL) uz okvir
  upozorenja i njegovu potvrdu; kill switch, stanje walleta, rug i Autopilot isključen ostaju tvrdi (11.11.).
  Novi pump.fun tokeni se ne kupuju dok su na krivulji; kupuju se bondani.
- Pravi novac (14.11., vlasnik): kad vlasnik uključi prekidač pravi_novac_sve, sve strategije trguju pravim novcem
  unutar stropova: 0,1 SOL po tradeu, najviše 10 otvorenih, 100 tradeova dnevno, dnevni gubitak 0,5 SOL. Bez
  prekidača pravi novac samo uz dokaz u demu. SOLANA_PRIVATE_KEY se nikad ne kopira u sandbox. PumpPortal novčanik
  za podatke drži samo male iznose (strop LIVE_MAX_TRADES_DAY).
- Midcap dnevni raspon (16.11., vlasnik): 5 pozicija × 0,1 SOL (0,2 SOL tek kad povijesni test novog pravila stopa
  pokaže plus; globalni strop za midcap raspon dopušta do 0,2 SOL); dok je BTC miran samo široki stop −20 % od ulaza; uži
  stop (4 % ispod cijene, ili na ulaz ako je pozicija u plusu) tek kad BTC padne 1,5 % u 4 h ili je u slobodnom padu;
  kad se BTC smiri, vraća se široki stop. Bez vremenskog stopa; na +5 % neto stop ide na ulaz; cijeli profit na cilju.
  Automatske kupnje staju kad vrijednost novčanika padne ispod 1 SOL. Ostale automatske kupnje ostaju na 0,1 SOL.
- Demo istraživač (18.11., vlasnik: „što više demo tradeova”): drugi demo račun kupuje kandidate koje dnevno pravilo
  odbije (šira zona, svijeće još padaju, Grokov „kupi” s X-a), svaki s oznakom; nikad pravi novac, ne ulazi u dokaz.
  Grok bot je analitičar (X, objave, hype) i drugi kritičar uz OpenAI; Grok autotrade pravim novcem pali samo vlasnik.
- Knjiga sjene (18.11., vlasnik: „1000 demo tradeova dnevno da bi program mogao naučiti”): svaki midcap kandidat
  ulazi kao zamišljeni trade u pet profila izlaza (samo redci, bez računa i novca); ocjena po token-danu, ćelija
  vrijedi tek uz 20 token-dana i potvrdu na kasnijim danima; ništa što odlučuje o trgovanju je ne čita.
  Broj tradeova nije cilj (18.11.): cilj je da program nauči koje kombinacije (mjesto u zoni, svijeće, BTC, makro,
  Grok, izlaz) zarađuju na danima koje nije vidio, uz stvarni trošak (nikad ispod 3 %), i da demo bude u plusu.
- Twitter API krediti (18.11., vlasnik): za midcapove koje pratimo: tko ih zove i gura, izmjerena moć poziva (kretanje
  nakon objave iznad prosjeka tokena), pa praćenje najjačih kad pozovu mali token (demo). Makro influenceri: dohvat
  zaustavljen dok vlasnik ne odobri. Pretraga po midcapu: strop 4 $ dnevno, oko 2,50 $ po tjednom prolazu.
  (19.11.: zamijenjeno fokusom na novčanike, vidi dolje)
- Vijeće (18.11., vlasnik: „kad Grok pošalje prijedlog, Claude i OpenAI moraju biti kritični, doraditi ga i prihvatiti
  ako se slažu; isto za OpenAI i Claude”): prijedlog jednog člana (Grok, OpenAI, Claude) ocjenjuju druga dva; kad su oba
  bez „protiv”, prihvaća se sam (dopuštena postavka se primijeni, najviše do sjene; ostalo ide Claude Codeu za izvedbu),
  oba protiv = odbijeno, podijeljeno = vlasnik. Pravi novac (ulog, broj pozicija, TP, SL, copy.*, live, autotrade, kill)
  vijeće nikad ne primjenjuje: samo vlasnik. Grok ima 6 h, zatim se odlučuje bez njega. Budžet 0,60 $ dnevno po članu
  (OpenAI, Claude); sjednica o smjeru jednom tjedno (ponedjeljak) i kad se presuda učenja promijeni.
- Pravi novac PAUZIRAN (19.11., vlasnik: „Autopilot kupovinu s pravim novcem isključi"): automatske kupnje pravim novcem
  stoje (pet prekidača isključeno + pauza), otvorene pozicije zadržavaju izlaze, ručna kupnja vlasnika ostaje; uključuje
  samo vlasnik svojim prekidačem; dotad što više demo tradeova s praćenjem novčanika. Ranije (18.11.): Pravi novac
  (18.11., vlasnik: „Ne želim da se pravi novac pauzira, nego da se da sve od sebe da tradeovi s pravim novcem postanu
  profitabilni. To mi je najbitnije."): pravi novac se ne pauzira; najvažniji cilj svih resursa je profitabilnost
  tradeova pravim novcem. Što pravi novac kupuje mijenja samo vlasnik svojim prekidačem (pravi_novac_veliki,
  pravi_novac_nauceno); nalog iz chata („odmah na naučeno pravilo", 18.11.) izvršava se jednom i samo ako ga ispravljeni
  test učenja (bez curenja budućnosti) potvrdi, inače pravi novac ostaje na dosadašnjem pravilu. Mjerenje troška jednim
  stvarnim krugom pri 0,1 / 0,3 / 0,5 SOL je odobreno (18.11.), jednokratno.
- Fokus novčanici (19.11., vlasnik: „svi resursi u pronalaženje profitabilnih voleta"): prvo novčanici koji kupuju prije
  pumpe i prodaju u pumpu (svaki dan; Helius; traženje od 2 M $ naviše, prednost pumpama do 15-200 M $; i bundle
  novčanici koji pomiču cijenu), drugo ulaz i izlaz za midcapove: novi ulazi pravim novcem samo od 15 M $, demo kao
  dosad od 2 M $ (otvorene pozicije se ne diraju). Influenceri, Telegram i skeniranje X-a osvježavaju se jednom u 5 dana
  i ne dobivaju druge resurse. Kopiranje pravim novcem tek kad povijesni test izvan uzorka (odabir samo iz prošlosti,
  kašnjenje, stvarni trošak, promašene kupnje brojane) bude u plusu s intervalom iznad nule; prekidač pali samo vlasnik.
- Teški poslovi koji ne smiju biti prekinuti: 01–06 CET. Deploy skuplja više promjena u jedan merge.
- Za sve što se ne može poništiti (brisanje, plaćanje, slanje van, produkcija) pitaj prije.
- X objave (Buffer): samo sadržaj iz share/novosti.json, bez env imena, ključeva, adresa, troškova, internih servisa.
