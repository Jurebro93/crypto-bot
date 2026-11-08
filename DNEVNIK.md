# Dnevnik MemeSonara (Jure + alat)

Jedan zapis po danu, uvijek isti odjeljci: Odlučeno · U tijeku · Čeka Juru · Odbačeno · Bot u 5 brojki.
Piše ga alat svaki dan u 18:00 CET i šalje Juri; stariji dani ostaju ovdje da se ne traži po porukama.

## 7.–8.11.2026.

### Odlučeno i napravljeno (spojeno, radi)
- Prve tri stranice i Pregled počinju kutijom "Prijedlog za danas": tri tokena s razinom vjerojatnosti (visoka/srednja/niska), ulog po razini, živa provjera "još u zoni ulaza", izlaz (pola na +15 %, trail 15 %, stop −25 %). Kutija se sama osvježava svakih 60 s.
- Novčanici: "Za kopiranje" prva, "Aktivnost" zadnja; bez demo kopija piše "Pratio bih" (probnih 10 $), ne "Kopirao bih".
- Dnevnik odluka: svaki prijedlog se zapisuje i 24 h kasnije dobiva ishod (+15 % prije stopa −25 %?); kutija pokazuje vlastiti rezultat po razini. Prvi ishodi 8.11. oko 11:40.
- Stanje tokena: mrtvi tokeni (298 od 900) pišu "nema para", DexScreener ikona vodi na pravi par; svježi mcap.
- Liga: lažni skokovi računa (kriva cijena, npr. Jure 1.11. $8k, Mario AI ×224) izbačeni iz grafa, "?" ostaje s objašnjenjem.
- Strategije: "Telegram poziv", "KOL potvrđen", makro zaštita izlaza (BTC pada → stop −50 %), izlazi za male tokene (pola na +15 %).
- Trošak: Apify pumpfun ugašen (−24 $/mj); discover 0,8 → 0,3 $/dan; apify cache 3 dana; masovno 500/800 → 150/400 GT poziva (dijelio limit s mjerenjem KOL-ova).
- Server: brava teških poslova piše tko je drži; masovno i status tokena izvan brave; lagani poslovi čekaju 3 min pri startu; status upisuje DexScreener odmah; shadow/masovno commit po točki; izvoz baza popravljen; sken ponavlja zaključani upis i imenuje držatelja; učenje više ne pada na klasi None.
- Audit "dnevne odluke" provjeren: D1–D3 točni i ugrađeni, D4 već bio u redu.
- Analize: Unipcs (mali tokeni reagiraju, veliki ne), retro +15 % (100k–300k, momentum, 20–100k pratitelja), trošak vs korist po izvoru (X i Helius novčanici vrijede, pumpfun ne), pump.fun "runner u 10 min" (0 od 129 nasumičnih ima 40k+13k; 2 od 129 doseglo 100k, oba s malim mcapom u 10. minuti), graduation sniper (dio nakon graduacije −9,7 % u 5 min na 117 bondanih).
- Dokumenti na mailu/Driveu: statistika i plan Bubblemaps+StalkChain; SEO plan (programmatic influenceri, Telegram kanali, 5 blogova, novi klasteri); 10 vodiča sa screenshotovima.
- Čišćenje podataka (8.11., Jure: "Kreni s tim"): ops/prune.py, prvo suho brojanje u logu, pa DATA_PRUNE=on briše. Pravila: novčanici bez X računa više ne postaju "pozivi" (572.899 od 744.088 poziva bilo je to), GeckoTerminal ne mjeri swapove ni bot objave (39.743 od 40.772 Telegram poziva nikad izmjereno jer su swapovi uzimali red), bot novčanici (>60 tradeova/dan, 15 ih je radilo 57 % svih događaja) van iz webhooka, gubitnici (tier D, 10+ zatvorenih bez dobiti, neaktivni 30 d) gube tradeove i ne boduju se više, chain_trades 14 d, apify 1 d, mrtvi tokeni 14 d, tickovi netrgovanih tokena 4 d. Rast tablica se prati po satu ("raste brzo").

### U tijeku (alat radi sam)
- Dnevnik odluka skuplja ishode; prvi rezultat po razini 8.11. popodne.
- Nadzor brave: čeka se prva poruka "baza zauzeta ... drže je: ..." da se vidi tko noću drži hype.db.
- Jutarnji krug (06:30) i večernji krug (17:00) s logovima, bazama i izvještajem.

### Čeka Juru (odgovor "da/ne")
1. Čišćenje: nakon deploya suho brojanje u logu (sat vremena), pa uključiti brisanje (DATA_PRUNE=on) i dnevno sažimanje vraća disk. Očekivano: wallets.db −44 % redaka tradeova, paper.db −49 % tickova, kol.db −450k poziva.
2. Strategija "sigurica" (visok confidence + dokazani influencer + dokazani novčanik, izlaz +10 %): započeta, prekinuta usred pripreme. Nastaviti?
3. Sjenovite točke "krivulja92" i "lansiranje10" (mjerenje, bez kupnje): da?
4. Sumnjivi socijali: −$850 dnevno dva dana zaredom, svi rugovi odatle. Strožiji ulaz ili pauza?
5. Bubblemaps/StalkChain Faza 0 (besplatan test na 30 rugova + 30 dobitnika): kad?
6. Apify gmgn 1,7 $/dan: provjera vrijednosti sljedeća na redu.

### Odbačeno / nema smisla (po podacima)
- Pravilo "40k mcap + 13k volumena u 10. minuti" kao detektor runnera: nijedan kandidat, nijedan pogodak; traži se rani promet, ne prag.
- Kopiranje novčanika riskbets/sneaky iz X posta: 22–24 % dobitnih, copy ocjena 2 i 12.
- Graduation sniper kao strategija s pravim novcem: dio nakon graduacije gubi; dio prije nemamo u podacima.
- Bubblemaps API (170 $/mj) prije besplatnog testa; StalkChain prije Faze 0.
- Apify pumpfun feed (ugašen).

### Bot u 5 brojki (7.11. 00:00 – 8.11. 06:00 CET)
- Demo PnL: −$2.725 (dan −$1.266, noć −$1.459); jedina u plusu kol +$3 (dan).
- Najveći gubitnik: sumnjivi socijali −$1.717 na 211 zatvorenih, 32 od 39 rugova.
- Izgubljeno na izlazu: 109 od 405 pozicija dotaklo +15 % pa zatvoreno ispod.
- Prijedlozi: prvi ishodi još nisu stigli (24 h).
- Server: disk 1.519 MB slobodno (2–3 dana), učenje popravljeno u 06:41, sken se noću rušio 10× (popravljeno).
