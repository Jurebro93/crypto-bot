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
- Midcap dnevni raspon (16.11., vlasnik): 5 pozicija × 0,2 SOL; dok je BTC miran samo široki stop −20 % od ulaza; uži
  stop (4 % ispod cijene, ili na ulaz ako je pozicija u plusu) tek kad BTC padne 1,5 % u 4 h ili je u slobodnom padu;
  kad se BTC smiri, vraća se široki stop. Bez vremenskog stopa; na +5 % neto stop ide na ulaz; cijeli profit na cilju.
  Automatske kupnje staju kad vrijednost novčanika padne ispod 1 SOL. Ostale automatske kupnje ostaju na 0,1 SOL.
- Teški poslovi koji ne smiju biti prekinuti: 01–06 CET. Deploy skuplja više promjena u jedan merge.
- Za sve što se ne može poništiti (brisanje, plaćanje, slanje van, produkcija) pitaj prije.
- X objave (Buffer): samo sadržaj iz share/novosti.json, bez env imena, ključeva, adresa, troškova, internih servisa.
