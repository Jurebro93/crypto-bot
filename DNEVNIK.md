# Dnevnik MemeSonara (Jure + alat)

Jedan zapis po danu, uvijek isti odjeljci: Odlučeno · U tijeku · Čeka Juru · Odbačeno · Bot u 5 brojki.
Piše ga alat svaki dan u 18:00 CET i šalje Juri; stariji dani ostaju ovdje da se ne traži po porukama.

## 9.11.2026. (kasna večer, deploy #75 i TP/SL po podacima)

### Odlučeno i napravljeno (spojeno, radi)
- Deploy #75 u 23:16 CET (Jure: "Da, mergaj sada"): gušenje servera i pop-up "Učitavam…". Provjereno na Renderu 12 min nakon deploya: KOL search krug 86 s (prije 2.809 s i 1.981 s), CPU 5–41 % (prije 100 % po 30–47 min svakog sata), nula 5xx od 23:21 (502/503 samo u minuti deploya), UI proces 66–69 MB, pravi trade petlja živa.
- Uzroci (Render metrike + ispisi stanja procesa): upit graph_candidates skenirao je tablicu poziva za svaki redak grafa praćenja; čitanje "poziva zadnjeg sata" svake sekunde skeniralo je cijelu tablicu Telegram objava (85 MB) i X spominjanja jer nemaju indeks po vremenu; pop-up je slao zahtjev svake sekunde ne čekajući prethodni; UI je držao samo 5 veza u redu čekanja.

### U tijeku (alat radi sam, u grani, nije na serveru)
- TP/SL po podacima (Jure: "TP 20 / SL −40? koliko pogodaka treba? neka alat dinamički odluči"). Račun: treba = (SL + trošak) / (TP + SL); TP 15/SL 20 traži 63 %, TP 20/SL 40 traži 70 %: širi stop diže prag. Minutna provjera sprema prvu minutu dodira svake razine; kol/tpsl.py po izvoru bira par (10+ poziva, povučeno prema "bez prednosti", dokazano na starijim i novijim pozivima, prosjek iznad nule i na donjoj granici od 2 standardne pogreške) ili kaže "ne ulazi". Simulacija: izvor bez prednosti prolazi u 1–9 % slučajeva (samo po prosjeku 7–30 %), izvor s jakom prednošću u 42–97 %, ovisno o broju poziva i nemiru cijene. Novi izlaz praćenja "po podacima" za influencere i ekipe, zatvaranje nakon 60 min; na stranici redak "Po podacima: …" uz svako praćenje i tablica "Koji TP/SL se isplati" preko svih izmjerenih poziva. Brojke se pune nakon sljedećeg deploya.

- "Što je novo" stajalo je na 5.11. (Jure 23:35: "ispada da se na alatu ne radi"): upisano 31 novost za 6.–10.11. u share/novosti.json, samo hrvatski tekst (bez engleskih polja unos ne ide na karticu ni u večernju X objavu), bez internih naziva i troškova. Vidljivo nakon sljedećeg deploya.

### Čeka Juru
1. Merge TP/SL po podacima i novosti (sljedeći skupni deploy), ne 01–06 CET.
2. Za koja praćenja uključiti izlaz "po podacima": samo nova, ili prebaciti i postojeća influencer/ekipa praćenja?
3. Novosti 6.–10.11. i na X (engleski tekst uz unose), ili ostaju samo u aplikaciji?
4. Brava "dokaz u demu" za pravi novac ostaje (10 zatvorenih, PnL > 0, 40 % dobitnih); prijedlog da izvor s dokazom iz povijesti prođe ranije čeka tvoju odluku.

### Odbačeno / nema smisla (po podacima)
- Fiksni TP 20 / SL −40 kao zadani par: traži 70 % čistih pogodaka; dnevnik prijedloga (7 d) ima 49 % za +15 % prije stopa −20 %.

### Bot u 5 brojki
- Bez novih mjerenja večeras; vrijede brojke iz zapisa "9.11.2026. (večer)" dolje. Server nakon deploya: CPU 5–41 %, RAM 1,6–1,8 GB (od toga 1,3–1,5 GB keš datoteka), disk 2,1 GB slobodno.

## 9.11.2026. (noć, audit)

### Odlučeno i napravljeno (spojeno, radi)
- Audit Autopilota (audit/2026-11-09-autopilot.md; 61 nalaz spojen iz 85 potvrđenih, 12 odbačenih) našao je tri vrste problema: (1) svježina – "⟳ 1 s" je crtao brojke iz 60-s DexScreener keša, 1-s fragmenti radili su HTTP i spavali u niti zahtjeva, prikazivalo se vrijeme crtanja umjesto vremena podatka; (2) tumačenje – light RugCheck izvještaj bez holdera bio je "rug check prošao", nepoznati udjeli holdera brojali su se kao 0 (bodovi za "dobru koncentraciju"), stara mjera pogotka (fitilj +50 % u 24 h) rangirala je influencere iako minutna mjera postoji, prodaje bez SOL iznosa pravile su ROI novčanika; (3) novac – kopije bez stopa, TP/SL od sirove umjesto stvarne cijene ulaza, svježina mjerena od demo ulaza umjesto od poziva, pravi novac bez dokaza u demu, Jupiter 429 tumačen kao "nema prodavača". Popravljeno u 6 grupa datoteka (pogon, izvori, novac, pravitrade, zivo, stranice) + integracija predaja među grupama; 1.037 testova zeleno (uključeno noćno pregledavanje dolje).
- Pogon (PR #69–#72, #74, grana): priprema baza pri deployu traje sekunde (sažimanje i čišćenje prešlo u satni posao), teške stranice nikad se ne grade u UI procesu (dijete na nice 5, warmer ne gradi stranicu mlađu od 4 min), /ekipe i /kol u djetetu sa zadnjom kopijom na disku, market/usage lagani poslovi, noćni prozor 01–06 CET za teške poslove (Jure: "brave zakaži za iza ponoć"), danju CPU Autopilotu i stranicama.
- Izvori: DexScreener živi keš 3 s (najmanje 2 s; limit 300/min dijele svi procesi) za Autopilot, demo TP/SL i copy petlju, skeneri 60 s; X i Helius webhook pri zaključanoj bazi spremaju na disk i vraćaju 200 (ništa se ne gubi); svježa provjera bez podatka o holderima = "oprez", ne "prolazi"; praćeni TG kanal koji nije u bazi ulazi odmah; dokazani novčanici s udjelom "bagova" (neprodanih) ≥ 30 % nisu za kopiranje; udjeli holdera/bundlera/snajpera iz RugCheck + rug filtera kad pump.fun ploče nema (i u skenu).
- Novac: ulaz samo MC ≥ 30k, samo bondani, likvidnost ≥ 3 % MC-a, koncentracija blokira samo na POZNATO lošem podatku; zadani stop −20 % za svaku TP/SL kopiju bez upisanog stopa (isti prag kao minutna provjera), TP/SL od stvarne cijene ulaza; svježina od poziva; pravi novac samo praćenju s dokazom u demu (10+ zatvorenih, PnL > 0, 40 %+ dobitnih; ručne kupnje izuzete); prodaja upisuje namjeru prije swapa i usklađuje se poslije; Jupiter 429/4xx = "nema odgovora, ne kupujem naslijepo"; ručna kupnja provjerava TP/SL i ulog PRIJE upisa demo tradea; deploy šalje SIGTERM procesu pravog novca, koji dovrši prolaz i izađe.
- Autopilot uživo (pravitrade + zivo): minutna provjera je primarni rang influencera (fitilj samo rezerva, označena "stara mjera"), i na karticama "+10 % prije stopa · N poziva"; pop-up verdikt traži svjež razlog, veto pozivatelja iz minutne provjere (svi poznati pozivatelji hit15 < 30 % na 5+ poziva → Kupi odbija), rug check "nije rađen" i "tko drži supply: nepoznato" umjesto prolaza, vrijeme RugCheck podatka umjesto prolaza provjere, red "likvidnost X % MC-a", dokaz u demu po praćenju ("pravi novac: da/ne"); 1-s fragmenti čitaju keš koji puni pozadinska nit (nema HTTP-a ni spavanja u niti zahtjeva), "podaci od HH:MM:SS UTC" umjesto vremena crtanja, "učitavam…" dok prve brojke ne stignu; novčanici: prodaja bez SOL iznosa = zatvoreno ali povrat nepoznat, udio neprodanih kažnjava; dokazani novčanici prvi izvor auto-izbora.
- Stranice: minutna mjera i vruća lista na Influenceri/Copy trading/Pregled, oznake Autopilota na Walleti, starost tržišnih podataka i "ispod 30k" na Tokeni, holderi "nepoznato" (nikad bodovi za nepoznato), zadnji stvarni signal kao svježina prijedloga, kartica "Kupnje i prodaje svih webhook novčanika" (brojala je sve webhook novčanike, ne samo praćene).
- Zašto samo jedan pravi trade (Jure, 9.11. večer): razlozi blokade bili su samo u tablici pozicija. Sad /pravi-trade pod "Koga bot prati" za svako praćenje piše "Zadnjih 24 h: N signala · M ulaza · preskočeno (razlozi)" iz dnevnika kopiranja, a svaka blokirana prava narudžba ide u serverski log ("trade: … PRESKOČENO simbol (izvor): razlog").
- 22:00 "nešto guši aplikaciju" (Jure): Render metrike 1 CPU na 100 % po 30–47 min svakog sata, 502/499 na stranicama. Uzrok iz faulthandler ispisa KOL search kruga: upit graph_candidates (kol/discover.py) s NOT EXISTS … LOWER() skenirao je cijelu tablicu poziva (130 MB) za svaki redak grafa praćenja, pa je svaki krug sjedio 30+ min na toj liniji (dumpovi 20:06–21:36, "cmd_search trajao 2809 s" i "1981 s"). Popravak: handleovi koji su već objavljivali čitaju se jednom preko indeksa i filtriraju u Pythonu; uz to backlog UI servera 5 → 128 da nalet anketa čeka umjesto da ga kernel odbije (502). Uz noćni prozor za run_dugo/corr/wallets iz ove grane, dnevni CPU ostaje Autopilotu i stranicama.
- 23:07 pop-up na Autopilotu stoji na "Učitavam…" (Jure, snimka): CPU opet 100 % od 23:03 (isti KOL search krug), a pop-up je slao novi zahtjev svake sekunde ne čekajući prethodni, i svaki je zahtjev iznova čitao kol.db, tg.db i hype.db; čitanje "zadnjih sat vremena" skeniralo je cijelu tablicu Telegram objava (85 MB) i X spominjanja jer nemaju indeks po vremenu. Popravak: indeksi posts(ts) i kol_mentions(ts) pri startu, zadnjih sat vremena poziva čita se jednom (pozadinska nit) i dijeli svim pop-upovima, skripte drže najviše jedan zahtjev u letu (odustanu nakon 8 s i napišu "server je spor"), isto za žive kartice, demo i natjecanje.
- Ispravak ranijeg zapisa (popodne, "DexScreener batch keš 1 s"): keš je stvarno bio 60 s; sada živi keš 3 s, živa lista 2 s u pozadinskoj niti, skeneri 60 s.
- Noćno pregledavanje grane (Jure: "optimiziraj rad servera na Renderu, brave zakaži za iza ponoć tek"): zadani noćni prozor u kodu bio je 00–06 Zagreb, sad je 01–06 kao u pravilu i masovnoj knjizi (u 00:xx još stižu deployi); lista "dokazani dvaput" i copy lista (samo čitanje baze) dobile vlastitu dnevnu petlju svaka 3 h umjesto jednom po noći iza bodovanja; "Što kupiti sada" na serveru kaže "učitavam…" dok pozadinska nit ne složi prvi prolaz (prije: prazno, odjeljak skriven); DexScreener odbijenica (429/5xx) za pop-up pamti se 3 s pa 1-s anketa ne radi HTTP u niti zahtjeva (vraća se slot star do 60 s ili ništa); zagrijavanje stranica preskače stranicu mlađu od 4 min bez ponovnog pakiranja (starost se više ne resetira); pečat "podaci od" na živoj listi uzima najstariji DexScreener podatak u redovima, ne vrijeme slaganja HTML-a.

### U tijeku (alat radi sam)
- Minutno punjenje 30 dana nastavlja (brojke u večernjem zapisu dolje); teški poslovi (dugoročni sken, puni KOL krug, bodovanje novčanika) čekaju noćni prozor 01–06 CET.
- Pozadinske niti Autopilota pune živi keš; prvi gledatelj nakon deploya vidi "učitavam…" dok prve brojke ne stignu (nekoliko sekundi, ovisi o DexScreeneru).
- Kalendar i DexScreener sken event-tokena idu samo noću (po Jurinoj želji): demo ulazi po događajima čitaju zadnji noćni popis, pa su event-tokeni po danu svježi najviše jedan dan.
- Deploy ove grane: jedan merge za sve valove (pogon + izvori + novac su već u main kroz #69–#74; pravitrade, zivo, stranice, noćni prozor i integracija čekaju jedan PR).

### Čeka Juru
1. LIVE prekidač na /pravi-trade uključen od 16:20 UTC, a pravilo (CLAUDE.md) kaže "dry dok strategija ne dokaže edge u demu": ostaje uključen (sad s vratima "dokaz u demu"), ili isključiti dok barem jedno praćenje ne prođe prag?
2. Pragovi dokaza u demu (10+ zatvorenih, PnL > 0, 40 %+ dobitnih) – potvrda; vrijede li i za izvore bez praćenja (SimianX, ručne kupnje s lige), koji sad idu bez tih vrata?
3. PumpPortal podatkovni ključ/novčanik (≥ 0,02 SOL) – kao jučer: bez uplate živi tok ostaje ugašen.
4. Jedan merge po valu (deploy skuplja promjene) ostaje pravilo, ili se svaka grupa spaja zasebno čim je zelena?
5. Pravi trade SPSC 17:19–17:28 UTC, −0,024 SOL: tvoj ručni test ili ulaz Autopilota? S novim vratima (dokaz u demu, svježina od poziva) takav ulaz bi sada bio blokiran – je li to u redu?
6. Tri manje odluke: smiju li X webhook računi bez monitora u auto-izbor influencera (P42)? Ostaje li veto slabih pozivatelja i na ručnu kupnju "Kupi odmah" (P47)? Smije li se .copy_wake maknuti iz gita (datoteka je u .gitignore, a ipak praćena)?
7. Kalendar i sken event-tokena samo noću: ostaje li tako (cijena je dnevna svježina event-tokena za demo ulaze), ili sken natrag na dnevnu petlju (lagan, bez Heliusa)?

### Odbačeno / nema smisla (po podacima)
- 12 nalaza audita (§6 izvještaja): namjerni rezervni putovi i dokumentirane odluke (Pregled nudi zadnje prijedloge kad je živa lista prazna, 'since' pri startu pravog novca, holder polja kao značajke za učenje a ne pragovi, javna lista /tokens po broju holdera, UTC vs Zagreb u dnevnom limitu kozmetika) – ostaju kako jesu.

### Bot u 5 brojki
- Bez novih mjerenja (noć je otišla na popravke, ništa od ovoga još nije na serveru); vrijede brojke iz zapisa "9.11.2026. (večer)" dolje.

## 9.11.2026. (večer)

### Odlučeno i napravljeno (spojeno, radi)
- Samokritika mjerenja: zone su bile ispravne (sve unix UTC), ali ulaz je kod GeckoTerminala bio 3–7 min PRIJE poziva, kod većine poziva cijena iz DexScreener snimke do 25 min POSLIJE, a "pogodak" fitilj +50 % u 24 h. Nova minutna provjera (kol/minute.py, vlastiti proces i baza minute.db): ulaz = zatvaranje minute poziva, +5/10/15/20/30 % samo PRIJE stopa −20 % u 60 min; stranica /ekipe po ekipi (članovi, pratitelji, tko zove prvi, zajednički tokeni, rug) i vruća lista koja se čita svake 2 s (TG) / prva u X webhooku. PR #54, #62–#66.
- Autopilot (PR #53–#67): pozicije na vrhu s prodajom 20/50/100 %, Kupi odmah (adresa + SOL), cilj izlaza 5–30 %, praćenje bilo kojeg walleta/@računa/tg:kanala i EKIPE (zarezom; ulaz čim prvi objavi, do MC $1M, ne ako je već +25 %), "Zovu sada" po ekipi, "Što kupiti sada" uživo (svi filteri + svake 1 s cijena/volumen/novi pozivatelji/pametne kupnje, samo svježi razlozi), pop-upovi za svaki token i ekipu s presudom U REDU ZA ULAZ / NE KUPUJ, sve osvježeno svake 1 s; zapraćeni nestaju s lista, prazni odjeljci skriveni, odjeljci zatvoreni osim Pozicija; gumb Kupi odbija token koji ne prolazi živu provjeru u trenutku dodira.
- Krivi podaci koje je Jure našao i što je promijenjeno u pravilo: RIPTRUMP ($0 prometa, nuđen zbog kalendarskog događaja) → prijedlog samo sa živim prometom i tezom, event ocjena bez nagrade za mrtav token; WBTC/COINx u "Zovu sada" → majori/zamotano/xStock/likvidnost >$1,5M nisu pozivi, kupnje broje samo tvoji i dokazani novčanici; EVM adrese iz Telegrama ("x47c…") → svaka adresa mora biti Solana mint (32 bajta); JENSEN rugiran na vrhu → ispada istog trena, Kupi odbija; GROK "pozvan prije 24 h" → samo svježi razlozi; "Protiv: rug filter: PROLAZI" → ispravljeno.
- Rezanje troška (PR #57): zamrznuti Insajderi (−45,7 %) i Ekipa (0 ulaza, $0,8/dan reakcija), bodovanje novčanika 500/6.000 kredita, AI oznake 2.000/dan, PumpPortal poruka 1×/30 min.
- 18:00–18:20 "aplikacija puca": (1) KOL korak cmd_search (twitterapi.io timelinei ~300 računa + GeckoTerminal trending) držao je tešku bravu 45 min (16:41) i 20+ min (18:05) pa nijedna stranica nije mogla graditi, a nakon klika (POST briše predmemoriju) Pregled/Tokeni su 20 min bili 503 → cmd_search ide u vlastiti proces BEZ brave, a zadnja spremljena kopija služi se i nakon klika; (2) utrka u signal_summary (dva prozora čitana jedan za drugim, novi signal između) rušila je /natjecanje svake sekunde dok UI nije narastao na 883 MB → jedna čitajuća transakcija + nedostajući token uzima svoj redak; /natjecanje gradi retke najviše 1× u 2 min.
- 20:04 "aplikacija se predugo učitava": brava je i bez KOL searcha stalno zauzeta (run_dugo 29 min, wallets score...), gradnja Pregleda čekala je 60 s na nju pri svakom otvaranju nakon klika, CPU 100 % → gradnja stranice više ne čeka bravu (ide uz teški posao kad je slobodno ≥600 MB, inače odmah zadnja kopija), spremljena kopija služi se odmah i nakon klika pa se osvježi u pozadini, teški poslovi idu s nice 10 da UI prvi dobije CPU.
- Stabilnost: OOM 12:30/12:56 (moj odjeljak gradio sve hype retke u UI procesu) → popravljeno (#55), nadzor memorije svake minute gasi proces iznad 800 MB umjesto da Render ugasi sve (#59), stranice se grade jedna po jedna. GeckoTerminal 429 → razmak uči stvarni limit (#66).

### U tijeku (alat radi sam)
- Minutno punjenje 30 dana: 1.265 poziva izmjereno, 35.834 čeka (4.603 tokena); 31–69 tokena po prolazu od ~10 min → gotovo za ~22 h (sutra popodne); ekipe prve. Prva ekipa s karticom: cryptobossgamble + vortex_gamble (37 zajedničkih tokena, 4 rug, +10 % prije stopa na 2 izmjerena). Vruća lista: 25 X, 6 TG računa.
- Sutra 07:30: 10 vodiča s novim snimkama zaslona + zamjena stare mjere pogotka na ljestvici i preporučenim influencerima minutnom mjerom.
- U grani, nespojeno (deploy sutra): BrokenPipe iz 1-s anketa više ne puni log Tracebackom.

### Čeka Juru
1. PumpPortal podatkovni novčanik: uplatiti ≥0,02 SOL ili živi tok ostaje ugašen.
2. Ako minutno punjenje ostane ispod ~10 tokena/min: plaćeni izvor minutnih svijeća (Birdeye, ključ postoji) — cijena plana prije uključivanja.
3. Ekipa robinhood_trending/chinesewhalespump…: zapratiti kao ekipu kad /ekipe pokaže njihove minutne brojke (danas nema dovoljno mjerenja).

### Odbačeno / nema smisla (po podacima)
- "Udvostručio se u 75 % (4 zajednička poziva)" kao dokaz za ekipu: stara mjera (fitilj 24 h) na 4 uzorka; zamjena su minutne brojke na /ekipe.
- Prijedlog iz dnevnika Pregleda svakih 60 s na Autopilotu: nije live trading; zamijenjen živom listom.

### Bot u 5 brojki (Provjereno sa /strategije, /pregled, /ekipe i Render loga; /admin/export mom računu nije dostupan)
1. Demo: KOL pozivi $3.616 (+261,6 %, 133 zatvorenih, 22 % dobitnih; bez najboljeg tradea −$833), Izbor alata srednji $1.087 (+8,7 %); glavna demo knjiga danas −$121. KOL pozivi danas −$74.
2. Najveći gubitnik: Sumnjivi socijali −$3.282 realizirano (zamrznuto); danas KOL potvrđen −$116 (7 zatvorenih, 0 % dobitnih).
3. Pozicije koje su dotakle +15 % pa zatvorene ispod: ne mogu izmjeriti bez izvoza baze (pretpostavka: iz tablice tradeova 7 dana, više od polovice KOL tradeova s "najviši rast" >15 % zatvoreno je u minusu).
4. Dnevnik prijedloga (7 d, 24 h kasnije): visoka 28 od 57 dalo +15 % prije stopa, stop prvi 24, medijan vrha +14 %; danas upisano 0 novih ishoda.
5. Server: disk 2.071 MB slobodno (+40 MB/dan → ~50 dana), RAM stabilno (UI 100–260 MB, svi procesi ≤710 MB), greške: GeckoTerminal 429 ~3/h, BrokenPipe iz anketa (popravak u grani), KOL krug drži bravu 30+ min (bodovanje).

## 9.11.2026. (popodne, dopuna)

### Odlučeno i napravljeno (spojeno, radi)
- Samokritika mjerenja (Jure: "poziv u 10:32 ↔ svijeća 10:32, točne zone"): zone su bile u redu (sve je unix UTC: X createdAt s +0000, Telegram <time datetime> s pomakom, Telethon aware, lanac vrijeme bloka; Telegram bez pomaka od sada čita kao UTC). Problem je bio drugdje: GeckoTerminal mjeri 5-min svijeće i ulaz 3-7 min PRIJE poziva, a većina poziva dobivala je cijenu iz DexScreener snimke do 25 min NAKON objave, a "pogodak" je bio fitilj +50 % u 24 h. Za pravi novac to je prekasno i preoptimistično.
- Nova minutna provjera (kol/minute.py, stranica /ekipe): minutne svijeće od minute poziva, ulaz = zatvaranje te minute (kašnjenje zapisano), +5/10/15/20/30 % broji se samo ako dođe PRIJE stopa −20 % unutar 60 min; fitilj najviše 3× tijela; ispod $30k ne broji se. Po računu, po ekipi (2-4 računa, mjereno od PRVOG poziva grupe; 5+ = plaćena kampanja) i po paru. Red: tokeni koje zove 2+ računa prvi, ~60 tokena po KOL krugu iz besplatnog GeckoTerminala; povijest 14 dana puni se kroz dan-dva.
- Vruća lista (kv hot_list): računi s 5+ izmjerenih poziva u 14 d, +10 % prije stopa u 50 %+ i stop prvi ≤30 %, plus walleti dokazani dvaput. Telegram kanale s liste i kanale koje Autopilot prati čitamo svake 2 s (ostalih ~1000 ostaje na starom rasporedu), X računi s liste prvi u webhook, walleti su već prvi u Helius listi. Tko ispadne iz brojki, ispadne s liste.
- Autopilot: cilj izlaza (+5/10/15/20/30 %) na vrhu za sve nove kopije; "Zovu sada" (tko je u zadnjih 60 min zvao koji token, X/Telegram/praćeni walleti, svake 2 s) s "Zaprati sve" i kupnjom odmah nakon prvog pozivatelja; "Što kupiti sada" = isti prijedlozi kao Pregled s DexScreener linkom; "Uživo: nalozi" više ne prikazuje stare probne/preskočene naloge kao da su svježi (Jure: "osvježeno sada, nalozi od prije 5,8 dana?").
- Praćenje ekipe pravim novcem (Jure: "čekao bih da ova ekipa objavi token… ulaz čim objave, ako je ispod 1 M $ i još nije +25 %"): nova vrsta praćenja "ekipa" (računi odvojeni zarezom) na Autopilotu: jedan ulaz po tokenu čim prvi (ili 2–3) od njih objavi, samo dok je MC ispod zadanog (zadano $1M) i cijena nije već više od zadanog (+25 %) iznad poziva (DexScreener 5-min/1-h promjena kao vrata na ulazu); isti uvjeti rade i na pojedinačnom KOL-u. "Zaprati sve" iz "Zovu sada" i "zaprati ekipu →" s /ekipe prave takvo praćenje. Praćeni X računi idu prvi u X webhook, praćeni TG kanali čitaju se svake 2 s.
- Hitni popravak (PR #55): "Što kupiti sada" je svakih 10 s gradio sve hype retke u UI procesu (RAM 100 MB → 1,6 GB, OOM restart 12:30); sada čita dnevnik prijedloga koji Pregled već upisuje, svakih 60 s.
- Rezanje troška (Jure: "isključi strategije koje troše API, a nisu profitabilne; fokus na prave tradeove i svježe podatke"): zamrznuti Insajderi (125 zatvorenih, −45,7 %, ispod kontrole) i Ekipa (0 ulaza u 4 dana); čitanje reakcija na pozive (twitterapi $0,8/dan) isključeno; bodovanje novčanika 1000/12.000 kredita → 500/6.000 svaka 3 h (Helius); AI oznake objava (Haiku) 12.000 → 2.000/dan; PumpPortal poruka o nefinanciranom ključu jednom u 30 min umjesto 2×/min. Ostaje: Telegram (besplatno), X webhook + timeline ($3,2/dan, hrani KOL pozive = jedini izvor u plusu i pravi novac), DexScreener/GeckoTerminal (besplatno), Helius webhook za praćene novčanike.
- Samokritika ugrađena u prijedloge (Jure, RIPTRUMP: alat nudio token s $0 prometa jer je "pravi" token kalendarskog događaja): svaki predloženi token mora upravo sada imati 10+ transakcija, $1k+ volumena u zadnjem satu i $20k+ likvidnosti (DexScreener, provjera u trenutku prijedloga) i dolazi s tezom iz podataka (uživo, tko ga je zvao, minutna provjera, kako je prošao kad je ranije predložen, što govori protiv); razina "niska" više ne postoji, a kad ništa ne prolazi, kutija kaže zašto i koje tokene NE kupiti. Preporučeni influenceri dobivaju minutnu provjeru + rug/kasni pozivi, novčanici "dokazani dvaput" i kopirljivost. Event ocjena: volumen od $1k/dan i transakcije od 10/dan (log), omjer kupnji tek od 50 tx/dan; RIPTRUMP pada sa 63 na ispod 40.
- Render OOM (Jure 13:10 "memory exceed limit"): Renderov zapis server_failed oomKilled 2Gi u 12:56 odnosi se na staru instancu s kodom iz #54 (UI proces 1,6 GB) koju je deploy #57 upravo zamjenjivao; nove instance drže ~100 MB UI / ~480 MB svi procesi. Da se ne ponovi: nadzor memorije svake minute (ops/health.watchdog: proces iznad MEM_KILL_MB=800 MB, trade 1200, gasi se i keep ga vraća za 30 s umjesto da Render ugasi cijeli servis), stranice se grade jedna po jedna (UI_BUILDS 1).
- "Zovu sada" (Jure: WBTC s 41 "pozivom" prvi): kupnje su se brojale za svih ~100 webhook novčanika koji kroz WBTC/COINx rutiraju. Pravilo za sve na Autopilotu (kol/converge.not_a_memecoin): majori, zamotana imovina, tokenizirane dionice (xStock) i likvidnost iznad $1,5M nikad nisu poziv; kupnje se broje samo za novčanike koje račun prati i dokazane; isto pravilo na preporučenim tokenima. U zaglavlju ui/pravitrade.py tri pitanja koja svaki odjeljak mora proći kodom, ne napomenom.
- Ekipe (Jure: "napuni podatke za ekipe, drži ih svježima, vizualiziraj"): minutna provjera dobila vlastiti proces (keep minute → run_kol.py minute-loop) i vlastitu bazu minute.db; puni 30 dana povijesti neprekidno (~20 tokena/min, ekipe prije pojedinaca), pa svaki novi poziv 70 min nakon objave. Razlog: u KOL krugu minute nikad nije došao na red (backfill sesija držao krug 10+ min), a deployevi su krug stalno prekidali. /ekipe: po ekipi članovi s pratiteljima (X iz kols, TG iz tg.db), tko najčešće zove prvi, svaki zajednički token s +15/+30/+60 min, stopom, rug oznakom (low u satu ≤ −80 %, rug iz 24 h mjerenja ili arhiva) i starom mjerom za usporedbu; rang po potencijalu = tokeni × (udio +10 % + ½ udjela +20 % − stop − rug); gumb "Zaprati ekipu pravim novcem".
- Autopilot čišći (Jure: "zapratio sam Arc Trending i dalje stoji na listi; prazne kategorije sakriti; na vrhu pozicije i jednostavan unos/zatvaranje"): zapraćeni računi, članovi ekipa i walleti nestaju iz svih lista za praćenje i iz "Zovu sada" (token čiji su svi pozivatelji već praćeni je posao bota); prazni odjeljci (preporučeni influenceri/walleti/tokeni, Zovu sada, Što kupiti sada) se ne prikazuju dok nemaju konkretan prijedlog (živi odjeljci se sami pokažu kad nešto stigne); redoslijed: wallet → Pozicije → Kupi odmah (adresa + SOL + Kupi, ostalo pod "Više") → Cilj izlaza; "Prodaj sve" crveni gumb kod svake pozicije; dupli obrazac "Kupi drugi token" maknut.
- "Zovu sada" pokazao EVM adrese (Jure 15:37, robinhood_trending: "8699…4cd7", "x47c…a396", DexScreener link ne otvara ništa): Telegram čitač je rep 0x adrese propuštao kao base58 token. Sada: svaka adresa mora base58-dekodirati u 32 bajta (kol/collect.is_solana_mint; Telegram čitač i Telethon koriste isti filtar kao X), a svaki token u "Zovu sada" prije prikaza prolazi živu DexScreener provjeru (par postoji, MC 30k+, nije major/zamotan/xStock, nije arhiviran rug) i u retku piše MC, likvidnost i promjena u satu; ako provjera ne uspije, ne prikazuje se ništa.
- "Što kupiti sada" uživo (Jure 15:40: "isti prijedlozi kao na Pregledu, 60 s, signal star 11 h: to nije live trading"): novi ui/zivo.py. Kandidati svakih 60 s kroz sve spore filtere (rug check 'prolazi' i stanje nije pumpa/pad iz svježe provjere, prijedlozi do 6 h, konvergencija 30 min, Zovu sada; mint, ne major/zamotan/xStock, ne arhiviran rug, tier nije 'pad', MC 30k+). Svake 2 s: DexScreener (cijena, MC, likvidnost, 5 min i 1 h volumen/tx/promjena), novi pozivatelji u 10 min, kupnje praćenih/dokazanih novčanika u 10 min; token ostaje samo dok trguje i ne pada; red: tko je zadnji zvao, pametne kupnje, 5-min promjena, brzina novca; očekivanje za +15 % iz minutne provjere pozivatelja ili iz šanse pojasa. Token ostaje samo s barem jednim SVJEŽIM razlogom (novi pozivatelj ili pametna kupnja u 10 min, ili +5 % u 5 min s $1k+ i 5+ tx); "pozvan u Telegramu prije 24 h" (Jure, GROK) više nije razlog, nego oznaka izvora. Autopilot je izvor; "Prijedlog za danas" na Pregledu uzima istu živu listu.
- Autopilot pop-upovi i 1 s (Jure 15:50: JENSEN rugiran 127k→14k stajao na vrhu; svi tabovi otvoreni; Robinhood 6× zaredom; sve u pop-up, ne nova stranica; osvježavaju li se podaci svake sekunde?): sve liste (pozicije, nalozi, Zovu sada, Što kupiti sada) osvježavaju se svake 1 s (DexScreener batch keš 1 s); token ispada iz liste čim padne (MC < 30k, −20 % u satu, bez prometa) i gumb Kupi ga odbija istom živom provjerom u trenutku dodira; odjeljci zatvoreni osim Pozicija; "Zovu sada" jedan red po ekipi (ime po lideru: "ekipa @x +N"), dodir otvara pop-up (tokeni u 60 min uživo, pozivatelji, uspjeh iz minutne provjere, zaprati kao ekipu); svaki token (prijedlozi, dugoročni, moonshot, iz ekipe) ima pop-up "U REDU ZA ULAZ / NE KUPUJ" sa za/protiv, kupci vs prodavači, pozivatelji 60 min, pametne kupnje, rug check alata, tier, očekivanje +15 %, osvježava se svake sekunde dok je otvoren.
- Objašnjenje "kašnjenja": uspješnost kanala mjeri se od trenutka objave (ne od našeg čitanja); "kašnjenje čitanja" na /izvori je koliko kasno MI pročitamo objavu, i to sada ima objašnjenje na stranici.

### U tijeku (alat radi sam)
- /ekipe se puni; prve brojke za ekipe nekoliko sati nakon deploya, cijelih 14 dana za dan-dva. Tek kad ekipa ima 5+ mjerenja s +10 % prije stopa u 50 %+, ulazi na vruću listu.

### Čeka Juru
- Odabir ekipa/računa s /ekipe za Autopilot (pravi novac tek kad Jure uključi prekidač; bot sam ne kreće).
- PumpPortal novčanik za podatke: treba ≥0,02 SOL.

## 8.11.2026. (večer)

### Odlučeno i napravljeno (spojeno, radi)
- Čišćenje podataka (PR #40, #41): obrisano ~275k pseudo-poziva anonimnih novčanika, 785 neaktivnih X računa, tradeovi 2.354 gubitnika (770k redaka), 1,05 M tickova netrgovanih tokena. wallets.db 937→555 MB, kol.db 567→416, paper.db 355→198; disk 1,5→2,1 GB slobodno. Brisanje radi satni posao (pri startu samo broji); nadzor rasta tablica javlja "raste brzo".
- Izvori smeća zatvoreni: novčanik bez X računa više nije "poziv"; GeckoTerminal ne mjeri swapove ni bot objave (39.743 od 40.772 Telegram poziva nikad nije bilo izmjereno jer su swapovi uzimali red); bot novčanici (>60 tradeova/dan, 15 ih je radilo 57 % svih chain događaja) van iz Helius webhooka i PumpPortal praćenja.
- KOL krug (PR #42): webhook, X watch i konvergencija idu prije sporog bodovanja; webhook prvi put sinkroniziran od 5.11. (13:20 UTC); validacija svakih 6 h umjesto svaki krug.
- Učenje: u težine ulaze samo brojevi (masovno je spremao adresu novčanika i None kao "feature", learn6 padao svakih 6 h); run_hype learn više ne pada kad nema kandidata.
- Pregled: kartica PumpPortal piše "zadnjih 48 h" (tablica čuva 48 h, pa je "ovaj tjedan" bio cijeli sadržaj).

### U tijeku (alat radi sam)
- KOL krug i dalje pada na rok od 60 min: search (Apify timeline) ~20 min, bodovanje 40+ min na serveru (lokalno 146 s). Od 15:55 UTC log mjeri trajanje svakog koraka (PR #43); popravak sporog dijela slijedi po tim brojkama.
- Satno čišćenje briše inkrementalno (14:21: 8.767 w: poziva, 37 gubitnika, 23.506 tickova; 15:43: 10.267 / 7 / 19.539).
- Dnevnik prijedloga skuplja ishode: do 16:10 upisano 13 ishoda.

### Čeka Juru (odgovor "da/ne")
1. Wallets score: 1.000 novčanika i 12.000 Helius kredita svaka 3 h puni wallet_trades +72k redaka/sat; od 100 bodovanih 9 ispadne profitabilno. Smanjiti na 500 / 6.000?
2. Strategija "sigurica": započeta, prekinuta. Nastaviti?
3. Sjenovite točke "krivulja92" i "lansiranje10": da?
4. Sumnjivi socijali: strožiji ulaz ili pauza?
5. Bubblemaps/StalkChain Faza 0 (besplatan test): kad?
6. Apify gmgn 1,7 $/dan: provjera vrijednosti.

### Odbačeno / nema smisla (po podacima)
- "Koliko podataka alat ima" kao mjera vrijednosti: brojevi su bili točni zbrojevi redaka, ali 573k od 629k "kupnji novčanika" bili su swapovi botova koje ništa ne čita; 5.102 "influencera" uključivalo je 785 mrtvih računa. Od sada se broji samo što se koristi.
- PumpPortal dnevni strop (70k) kao kontrola troška: strop reže tokene, a promet su radili praćeni botovi (114–199k tradeova/dan). Riješeno izbacivanjem botova, ne stropom.

### Bot u 5 brojki (8.11., stanje 17:50 CET)
- Strategije (ukupno od starta): KOL pozivi +294 % ($3.944), ali bez najboljeg tradea −$580 → "ne diraj pravi novac"; nasumična kontrola −44 %. Najveći gubitnici: Izbor alata mali −34,5 %, Insajderi −34,2 % (114 zatvorenih, 39 % uspješnih), Ozbiljan projekt −15 %, Telegram poziv −15,5 %.
- Demo knjiga (paper) danas: −$108, 0 otvorenih pozicija u 16:48 UTC.
- Prijedlozi zadnjih 7 dana, provjereni 24 h kasnije: razina visoka 3 od 12 dala +15 % prije stopa (stop prvi 6, medijan vrha +4 %). Srednja/niska još bez dovoljno ishoda.
- Server: disk 2.139 MB slobodno (bilo 1.543), hype.db 1.406, wallets.db 555, kol.db 416, paper.db 198 MB. Greške danas: cmd_learn UnboundLocalError i learn6 TypeError (oba popravljena), 3 ponovna starta pri prvom brisanju (popravljeno).
- PumpPortal: 4–13k tradeova po 10 min ovisno o vrućim tokenima; veza se prekida i obnavlja svakih par minuta ("no close frame") cijeli dan, podaci teku.

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
