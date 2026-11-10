# Miran i pregledan MemeSonar: prijedlozi dizajna (10.11.2026.)

Odgovor ukratko: svaki ekran neka počne jednim odgovorom (jedan veliki broj ili jedno ime), ispod toga kratki reci
"ime + jedan razlog + jedan broj", a sve ostalo jedan dodir dalje. Isti blok ne ponavljati na četiri stranice, maknuti
emojije, ⓘ uz svaki broj i stalne trake, i staviti Autopilot u donju traku. Makete pet zaslona su gotove i snimljene.
Drugi krug (odjeljak 4): isti jezik na naslovnici, tokenima, influencerima i novčanicima, sa stranicama detalja; profil
influencera počinje iskrenom presudom (rezultat nakon 1 h i nakon 24 h), ista presuda je na ljestvici i u Autopilotu.

Kako gledati:
- makete (otvaraju se izravno u pregledniku, sve je u jednoj datoteci): `audit/2026-11-10/makete/pregled.html`,
  `tokeni.html`, `influenceri.html`, `autopilot.html`, `izbornik.html`
- snimke su u `/tmp/claude-0/-home-user/4912361d-d525-5b3e-b714-652a838e02b7/scratchpad/shots/ui/`:
  `sada-*.png` (današnja aplikacija), `novo-<zaslon>-phone.png` i `-desktop.png` (makete),
  `usporedba-<zaslon>.png` (prvi ekran mobitela, lijevo sada, desno novo, s brojkama ispod)
- ponovno snimanje: `python3 audit/2026-11-10/makete/sastavi.py && node audit/2026-11-10/makete/snimi.js`
  (sastavi.py upisuje zajednički CSS, traku i bočni izbornik u svih pet maketa; snimi.js snima i mjeri isto kao
  `shots.js` za "sada", pa su brojke usporedive)
- drugi krug (odjeljak 4): `naslovna.html`, `tokeni-popis.html`, `token.html`, `influenceri-ljestvica.html`,
  `influencer.html`, `novcanici.html`, `novcanik.html`; snimke i usporedbe istog imena

## 1. U jednoj minuti

1. **Jedan odgovor na vrhu svakog ekrana.** Pregled: "Najbolji ulaz sada: GIGAFROG". Influenceri: "Koga danas
   slušati: @Humanevolvd". Autopilot: "2,00 SOL" i graf. Sve ostalo su kratki reci ispod.
2. **"Prijedlog za danas" samo na Pregledu.** Danas isti blok stoji na vrhu Pregleda, Tokena, Influencera i
   Novčanika, pa Tokeni i Influenceri na prvom ekranu ne pokazuju svoj popis. Na Tokenima prvi token iz popisa
   dolazi tek na drugom ekranu, u maketi je na prvom ekranu šest tokena.
3. **Redak umjesto kartice.** Token ima 6 polja s ⓘ, influencer 20 polja (pola "–"). Novo: ime, jedan razlog,
   jedan broj; detalji na dodir, a stupci samo na računalu. Ljestvica influencera pada s 20,1 na 2,2 ekrana,
   Tokeni sa 7,8 na 1,9.
4. **Mirnija navigacija.** Autopilot ide u donju traku (za administratora). "Više" postaje stranica sa 17 redaka u
   četiri skupine umjesto ladice s 37 poveznica u šest skupina. Nestaju ☰ (radi isto što i "Više") i traka "Novo"
   s vrha svake stranice.
5. **Jedan vizualni jezik.** Pet veličina slova umjesto do 14, nula emojija (Pregled ih danas ima 35), jedna boja
   naglaska (`--acc`), zelena i crvena samo za brojeve s predznakom, hrvatski zapis brojeva ("2,00 SOL", "412k $").

## 2. Pravila koja vrijede za svaki ekran

1. **Jedan odgovor prvi.** Ekran počinje jednim velikim brojem ili jednim imenom s jednom rečenicom zašto. Ako se
   ne zna što je odgovor ekrana, ekran vjerojatno ne treba postojati.
2. **Redak, ne kartica.** Lijevo ime i jedan redak razloga, desno jedan broj (ispod njega najviše jedan sporedni),
   pa strelica. Sve ostalo je na dodir (postojeći pop-up ili stranica detalja).
3. **Pet veličina slova:** 34 naslov, 22 sekcija, 17 tekst i imena, 15 sporedno, 13 osi grafa i zaglavlja stupaca.
   Iznimka je samo vrijednost walleta (48). Debljine: 700 naslovi, 600 imena i brojevi, 400 ostalo. Sistemski font.
4. **Boje imaju posao.** Tekst je `--fg` ili `--mut`. `--acc` (#4f46e5) samo za ono što se dodiruje i za aktivno
   stanje. `--good` i `--bad` samo za brojeve s predznakom i za "Prodaj sve". `--warn` samo za upozorenje
   (rug, probno). Bez gradijenata i bez obojenih pozadina iza riječi.
5. **Bez emojija i ikona u tekstu.** Stanje je riječ ili točka od 8 px ("● dokazan", "Rug: oprez"). Linijske
   ikone samo u donjoj traci i bočnom izborniku.
6. **Objašnjenje je jedan dodir dalje.** Nema ⓘ uz svaki broj ni odlomaka iznad sadržaja. Najviše jedna rečenica
   objašnjenja na dnu popisa, sve ostalo u Pojmovniku. Nema stalnih traka ("Novo", "Dobro došao").
7. **Ništa se ne ponavlja.** Svaki blok živi na jednom mjestu; drugdje je jedan redak koji vodi do njega.
   Ista veličina ima jedno ime (ne "moć poziva" na jednom mjestu i "ocjena" na drugom).
8. **Brojevi su mirni.** Tabularne znamenke, desno poravnati, decimalni zarez, jedinica iza broja ("0,100 SOL",
   "412k $", "+18 %"), vrijeme kao "prije 3 min". Zaokruženo koliko odluka treba (mcap bez decimale ispod 100k).

## 3. Po zaslonima

Brojke "sada" su izmjerene na lokalnoj kopiji s izmišljenim podacima (`seed_app.py`), mobitel 390 px
(`sada-metrics.json`); "novo" isto mjerenje na maketama (`novo-metrics.json`).

### 3.1 Pregled (/pregled)

**Sada** (`sada-pregled-phone.png`, `sada-pregled-phone-fold.png`, `sada-pregled-desktop.png`): 5,1 ekrana na
mobitelu, 858 riječi, 35 emojija (21 vrsta), 14 veličina slova, 52 poveznice. Redom: traka "Novo" (tri retka), red
čipova (prvi je odrezan: "iko podataka alat ima"), "Prijedlog za danas" (uvod od četiri retka, tri tokena s tezom od
oko 50 riječi, novčanik, odlomak o izlazu), "Najprofitabilnija strategija" (veliko zeleno +9,6 %, a ispod sitno
"Presuda: zamrznuto, 125 zatvorenih, −45,7 %": naslov i presuda si proturječe) sa šest strategija s emojijima,
"Koliko podataka alat ima" (7 kartica), "Zanimljivo sada" (4 kartice), "Brzi linkovi" (8 kartica s emojijima, isto
što i izbornik). Na prvom ekranu mobitela vidi se jedan token.

**Novo** (`novo-pregled-phone.png`, `novo-pregled-desktop.png`, `usporedba-pregled.png`): 1,5 ekrana, 152 riječi,
0 emojija, 5 veličina slova.
- "Najbolji ulaz sada": GIGAFROG velikim slovima, jedan red činjenica (pouzdanost 94 · 412k $ · 1 h +18 %),
  jedna rečenica teze, ulog i "još je u zoni ulaza".
- ARIA i MOCHI kao reci, ispod jedan redak pravila izlaza.
- "Vrijedi pratiti": @Humanevolvd i novčanik Vfdn…At74.
- "Ovaj tjedan": najveći pogodak, strategije u demu (s istinitim stanjem "zamrznuta"), praćeni novčanici.
- Na dnu jedan redak "Podaci alata: 3 638 novih zapisa ovaj tjedan".

**Uklonjeno, spojeno, preimenovano i gdje ostaje:**
- Puna teza tokena (transakcije, volumen, povijest, slični tokeni, BTC pravilo) → dodir na token (pop-up/stranica tokena).
- Uvod "Analizirao sam u zadnja 24 h…" → podnaslov Tokena ("21 token analiziran u zadnja 24 h").
- Blok strategije sa šest redaka → redak "Strategije u demu" → Usporedba strategija.
- 7 kartica podataka → redak "Podaci alata" → zasebna stranica (isti sadržaj).
- "Zanimljivo sada" (4 kartice) → "Ovaj tjedan" (3 retka); "Najbolji trade strategije" ulazi u redak strategija.
- "Brzi linkovi" i red čipova → uklonjeno (traka i "Više" vode na iste stranice; stranica je dovoljno kratka).

**Trud: M.** `ui/pocetna.py` (raspored), `ui/prijedlog.py` (kompaktna inačica `box("pregled")`: hero + reci; puni
tekst ostaje za pop-up), `ui/html.py` (zajednički CSS retka i heroja), `ui/novo.py` (traka).

### 3.2 Tokeni: prijedlozi (/tokens)

**Sada** (`sada-tokeni-phone.png`, `-phone-fold.png`, `-desktop.png`): 7,8 ekrana, 883 riječi, 20 emojija,
75 ⓘ, 29 bedževa, 158 poveznica. Prvo ponovljeni "Prijedlog za danas" (isti tri tokena kao na Pregledu, s legendom
"uživo = živa lista…, visoka = svjež do 6 h…"), pa kartica "Dobro došao", pa 15 kartica sa po 6 polja (Confidence,
Mcap, Likv., Zašto, Rug, Zadnji signal) i ⓘ uz svako. "Confidence" je na engleskom, uz svako ime je ikona
kopiranja, iznad popisa su četiri kontrole (filtar, Sortiraj, Tablica, Stupci). Na mobitelu redoslijed nije po
broju koji se vidi (BORK 62, NYAN 63, VIBE 56, SOLDOGE 59).

**Novo** (`novo-tokeni-phone.png`, `novo-tokeni-desktop.png`, `usporedba-tokeni.png`): 1,9 ekrana, 201 riječ,
0 emojija, 3 veličine slova, šest tokena na prvom ekranu.
- Podnaslov "21 token analiziran u zadnja 24 h · 3 u zoni ulaza", segment Novi | Jaki | Dugoročni (ostaje).
- Jedno polje "Simbol ili adresa": filtrira popis, a zalijepljena adresa otvara token (spaja filtar i tražilicu).
- "Poredano po pouzdanosti ▾" je jedini izbornik na mobitelu.
- Skupine "U zoni ulaza · današnji prijedlog" (3) i "Ostali" (12): tako prijedlog ostaje vidljiv bez ponovljenog bloka.
- Redak: simbol, kratki razlog i "prije 3 min"; desno pouzdanost i mcap. Rug se piše samo kad je "oprez" (narančasto).
- Računalo: isti reci kao tablica (Pouzdanost, Mcap, Likv., Rug, Zadnji signal); "Stupci" ostaje samo ondje.

**Uklonjeno, spojeno, preimenovano:** blok prijedloga → Pregled; "Dobro došao" → samo prvi posjet, na Pregledu;
75 ⓘ → Pojmovnik i jedan link "Što znači pouzdanost" na dnu (na računalu tooltip na zaglavlju stupca); ikona
kopiranja i likvidnost → detalj tokena na mobitelu, stupac na računalu; Tablica i Stupci → samo računalo;
"Confidence" → "pouzdanost".

**Trud: M.** `ui/tokens.py` (HELLO, `prijedlog.box`, kartice → reci), `ui/cols.py` (stupci samo na računalu),
`ui/html.py` (redak, segment).

### 3.3 Influenceri: ljestvica (/kol)

**Sada** (`sada-influenceri-phone.png`, `sada-influenceri-ljestvica-phone.png`, `-desktop.png`): zatvorena stranica
ima 3,3 ekrana i 16 sklopljenih sekcija (6 + 10 "Detalji za znatiželjne") plus "Pročitaj više"; na vrhu je opet
"Prijedlog za danas" (tri KOL-a s po četiri retka teksta i dva tokena). Kad se otvori "Najbolji influenceri":
20,1 ekran, 1694 riječi, 376 ⓘ, 31 emoji, tablica s 21 stupcem (na računalu ne stane u širinu), a na mobitelu je
svaka osoba kartica s 20 polja od kojih je pola "–". Gumbi "⭐ Rastuće zvijezde (238)" i "🌟 Zvijezde (7)" ne
govore što filtriraju. Isti broj se zove "moć poziva 58" u prijedlogu i "ocjena 58" u ljestvici.

**Novo** (`novo-influenceri-phone.png`, `novo-influenceri-desktop.png`, `usporedba-influenceri.png`): 2,2 ekrana,
221 riječ, 0 emojija, 5 veličina slova.
- Hero "Koga danas slušati": @Humanevolvd, "● dokazan · ocjena 58 · 17 poziva", jedna rečenica, "Još dokazanih".
- Segment Ljestvica | Upravo zvali.
- Filtar "Manje poznati računi · 238 ▾" (bivše "Rastuće zvijezde"); druga mogućnost je "Veliki računi · 7"
  (bivše "Zvijezde").
- Redak: mjesto, @ime, "17 poziva · 71 % pogodaka" ili narančasto "33 % rugova" kad je rugova 30 % i više;
  desno ocjena i stanje ("● dokazan", "prosječan", "malo poziva").
- Računalo: šest stupaca (Ocjena, Poziva, Pogodak, Vrh 24 h, Rugovi, Zadnji poziv), ostalih 14 iza "Stupci".
- "Analize": Zovu zajedno, Plaćeni shilleri, Telegram calleri, Kupnje i prodaje, Za znatiželjne (10).

**Uklonjeno, spojeno, preimenovano:** blok prijedloga → hero (KOL-ovi) i Pregled (tokeni); sekcija "Upravo zvali"
→ segment; 10 sekcija "za znatiželjne" → jedna podstranica (sadržaj isti, i dalje se gradi tek kad se otvori);
"Pročitaj više: kako mjerimo" → jedna rečenica ispod ljestvice i Pojmovnik; 20 polja kartice → stranica
influencera (`/kol/<ime>`, već postoji) i "Stupci" na računalu; "moć poziva" → "ocjena" svugdje.

**Trud: L.** `ui/kol.py` (951 redak, teška stranica iz SNAPSHOT_ONLY), `ui/kolsummary.py` (nazivi stanja),
`ui/prijedlog.py` (`kol_picks` za hero), `ui/cols.py`, `run_ui.py` ako se doda `/kol/analize`.

### 3.4 Autopilot (/pravi-trade)

**Sada** (`sada-autopilot-phone.png`, `-phone-fold.png`, `-desktop.png`): 3,6 ekrana, 489 riječi, 11 emojija,
19 gumba (od toga 9 za prodaju triju pozicija: 20 %, 50 %, sve), 10 sklopljenih sekcija. Otvoreno "Postavljanje
walleta" (četiri koraka teksta) zauzima pola drugog ekrana. Vrijednost walleta nije jedan broj (1.842 SOL i
25.00 USDC u dvije kartice). Stanje je narančasta pilula s emojijem, oznaka "probno" ponovljena je na svakoj poziciji.
Na mobitelu je stranica šira od ekrana: snimka cijele stranice je široka 417 px umjesto 390 (redak "zarada =
vraćeno − uloženo − mrežne naknade ⓘ" izlazi iz okvira).

**Novo** (`novo-autopilot-phone.png`, `novo-autopilot-desktop.png`, `usporedba-autopilot.png`), redoslijed iz
ugovora grupe apui (`dizajn.md`, točka 2): 2,2 ekrana, 169 riječi, 0 emojija, 6 veličina slova.
- Naslov i prekidač "Uključen" (zamjenjuje gumb "Isključi Autopilot (nove kupnje staju)").
- Jedan redak stanja: "● Probno: ključ još nije postavljen · Dovrši 3/4" (spaja pilulu stanja i Postavljanje walleta).
- Vrijednost "2,00 SOL", ispod "≈ 323 $ · 278 € · danas 0,00 SOL".
- Graf preko cijele širine: jedna linija, uplata kao crtkana oznaka, dvije vodoravne crte s vrijednostima,
  raspon 24 h | 7 d | 30 d | Sve.
- "Dnevnik odluka": jedan redak sažetka, popis na dodir.
- "Otvorene pozicije 3 od 5": redak po poziciji (koga kopira, kad, uloženo, koliko još drži); prodaja 20 %, 50 %
  ili sve na dodir retka. "Zatvorene 8". Crveni "Prodaj sve i isključi" odmah ispod pozicija.
- "Kako trguje": Koga prati (4), Pravila (spaja "Cilj izlaza" i "Limiti"), Kupi ručno.
- "Još" na dnu (ne dohvaća se dok se ne otvori): Zovu sada, Što kupiti sada, Preporuke alata (spaja tri sekcije
  preporuka), Wallet i uplata (adresa, Solscan, 1,842 SOL i 25 USDC), Tko vidi stranicu, Kako je zaštićeno.

**Prijedlog grupi apui:** PnL ploha ispod grafa neka bude skrivena po zadanom (broj "danas" već kaže rezultat), a
jedinice $ i € stoje u retku ispod broja, pa grafu na mobitelu ne treba prekidač jedinica.

**Pazi:** "Prodaj sve i isključi" više nije na prvom ekranu nego jedan pomak niže; nove kupnje se odmah zaustavljaju
prekidačem na vrhu. Ako ti treba na prvom ekranu, može kao crveni tekst u retku stanja.

**Trud: M** (uz posao apui koji gradi graf i dnevnik). `ui/pravitrade.py`, `ui/apchart.py` (apui), CSS retka iz `ui/html.py`.

### 3.5 Navigacija: donja traka i "Više"

**Sada** (`sada-izbornik-phone.png`, `sada-izbornik-phone-dno.png`, `sada-izbornik-desktop.png`): ladica s 37
poveznica u 6 skupina, visoka 1,6 ekrana. Otvaraju je i ☰ gore lijevo i "Više" dolje (dva gumba za isto).
Autopilot je narančasti gradijent s emojijem i oznakom "pravi novac · admin", a nije u donjoj traci.
"Dugoročni" je i u izborniku i kao kartica na Tokenima; "Sve stranice" ponavlja izbornik. Na vrhu svake stranice
su ☰, logo i tražilica, pa traka "Novo" (na mobitelu oko 150 px).

**Novo** (`novo-izbornik-phone.png`, `novo-izbornik-desktop.png`, `usporedba-izbornik.png`):
- Donja traka za administratora: Pregled, Tokeni, Influenceri, Autopilot, Više. Ostali korisnici imaju Novčanike
  umjesto Autopilota (Autopilot ionako ne vide).
- "Više" je stranica, ne ladica: polje za traženje i četiri skupine (Istraživanje 4, Demo 5, Zajednica 3,
  Pomoć 2), pa Sustav (8, samo administrator), Postavke, Odjava. Ukupno 17 redaka.
- ☰ se uklanja; tražilica je ikona gore desno (Pregled, Influenceri) ili polje (Tokeni, Više).
- Traka "Novo" se uklanja sa svih stranica; nova stvar je točka na "Više" i "1 novo" uz "Što je novo".
- Računalo: bočni izbornik ima iste stavke (plus Novčanici) i tražilicu na vrhu, bez narančastog bloka; stranica
  "Više" ondje ima dva stupca.

**Uklonjeno, spojeno, preimenovano:** Dugoročni → segment na Tokenima; Korelacije → Influenceri, Analize;
Izlazi i Jutarnji izvještaj → kartice na Demo tradingu; Sve stranice → "Više" je sama mapa (`/mapa` ostaje zbog
starih linkova); Naslovna stranica i HR/EN → Postavke; osam stavki Sustava → jedna podstranica.

**Trud: M.** `ui/html.py` (BOTTOM, SECTIONS, `side_menu`, NAV_CSS, LIGHT_CSS, zaglavlje u `page()`, `map_page` kao
"Više"), `ui/novo.py` (traka → točka), `ui/admstrip.py` (razlika administrator/ostali u traci), `run_ui.py`
(ruta `/vise` ili preimenovanje `/mapa`).

## 4. Drugi krug, 10.11.: naslovnica, tokeni, influenceri, novčanici

Odgovor ukratko: isti jezik i na ostalim zaslonima. Svaka stranica detalja počinje presudom u jednoj rečenici i s
četiri broja koji je nose, a ista presuda (ista mjera, ista riječ) stoji na popisu, na profilu i u Autopilotu.
Najveća promjena je profil influencera: danas na vrhu piše "moć poziva 58 · pogodak 71 %", a rezultat nakon 24 h
(na Jureovoj snimci 2 u plusu, 28 u minusu, −185 $) dolazi tek na šestom ekranu. U maketi je to prva rečenica.

Kako gledati:
- makete: `naslovna.html`, `tokeni-popis.html` i `token.html`, `influenceri-ljestvica.html` i `influencer.html`,
  `novcanici.html` i `novcanik.html` (sve u `audit/2026-11-10/makete/`, svaka jedna datoteka)
- snimke u istoj mapi kao prvi krug: `novo-<ime>-phone.png` (cijela stranica), `-phone-fold.png` (prvi ekran),
  `-desktop.png`; za stranice detalja i `novo-<ime>-phone-cijela.png`; usporedbe `usporedba-<ime>.png`
- "sada" je snimljen na DANAŠNJEM kodu (f4dc160, s trakom "Tradanje pravim sredstvima je live" na naslovnoj i crnom
  trakom "Autopilot je live" na svakoj stranici aplikacije), na lokalnoj kopiji s istim podacima (`seed_app.py`);
  Autopilot je "live" samo u tom procesu (`sada_drugi_krug.py`). Zato su brojke "sada" za Tokene drukčije nego u
  prvom krugu (6,8 ekrana umjesto 7,8: današnji kod je skratio prijedlog). Novi zaslon u `shots.js`: `novcanik`.
- ponovno: `node audit/2026-11-10/makete/snimi.js --only tokeni-popis,token,influenceri-ljestvica,influencer,novcanici,novcanik`,
  pa `python3 audit/2026-11-10/makete/sastavi.py` (naslovna uzima slike novih ekrana iz tih snimki), pa
  `node audit/2026-11-10/makete/snimi.js --only naslovna`
- brojke "do stanja" ispod su duljina stranice bez dodanog bloka "Druga stanja istog ekrana" (taj blok je samo za
  izradu: učitavanje, prazno, traženje, filtri)

### 4.0 Jedna presuda za influencera (ljestvica, profil, Autopilot, Pregled)

Danas isti račun ima tri različite ocjene. Autopilot ga rangira po minutnoj mjeri ("+10 % prije stopa −20 % u 60 min",
`kol/minute.py`, "najbolji 14 d"). Ljestvica i prijedlog ga zovu "dokazan" po "pogotku" (vrh +50 % u 24 h,
`calls.max24`). Stupci na profilu pokazuju cijenu 24 h nakon poziva (`calls.r24h`). Vrh od +50 % rijetko tko uhvati,
pa "71 % pogodaka" i "2 od 30 u plusu" mogu biti istina za isti račun, a Autopilot trguje pravim novcem po prvoj mjeri.

Prijedlog: dva broja svuda, istim imenom i istim redom.
- **1 h**: udio poziva koji su došli do +10 % prije stopa −20 %, od minute poziva (po tome Autopilot bira koga prati).
- **24 h**: udio poziva u plusu dan kasnije.
- **Presuda** iz ta dva broja, jedna funkcija za sve stranice (npr. `kolsummary.verdict`): **drži se** (1 h ≥ 50 % i
  24 h ≥ 40 %), **samo brzo** (1 h ≥ 50 %, 24 h ispod 40 %), **ne isplati se** (1 h ispod 50 %), **premalo poziva**
  (manje od 5 u 14 dana). Pragovi su prijedlog; konačni izbor je Jurin.
- "Pogodak" (vrh +50 %) i "dokazan" se više ne pokazuju kao presuda; vrh 24 h ostaje u bodovima ocjene i kao stupac
  na računalu. Ocjena 0 do 100 ostaje.

### 4.1 Naslovnica (memesonar.app/hr)

> **ODBIJENO (Jure, 10.11. ujutro): "Naslovna mi je bolja stara. Nova mi izgleda kao klasičan AI."** Naslovnica
> ostaje kakva je; ništa iz ovog odjeljka se ne radi. Pouka za ostale ekrane: izbjegavati generički "AI" izgled
> (veliki opći naslov, sivi paneli jedan za drugim, mreža od četiri broja bez priče); ostali ekrani iz oba kruga
> (Autopilot, Pregled, Tokeni, Influenceri, Novčanici, izbornik) Juri se sviđaju i ostaju u planu.

**Sada** (`sada-naslovna-phone.png`, `-phone-fold.png`, `-desktop.png`): 17,2 ekrana na mobitelu (računalo 14,1),
963 riječi, 9 emojija, 20 veličina slova, 12 sekcija, 14 slika ekrana (3 u heroju, 5 u "Kako izgleda", 6 u galeriji),
sve starog sučelja; "Zatraži pristup" 7 puta u stranici. Današnja crna traka "Tradanje pravim sredstvima je live"
stoji iznad naslova i zauzima gotovo pola prvog ekrana: naslov "Pametniji ulaz u Solana tokene" počinje na 70 % visine,
gumb "Zatraži pristup" je odrezan na dnu. Brojke uživo su na drugom ekranu, dnevnik "MemeSonar je live 9 dana" na
trećem. Iste javne poveznice su tri puta (izbornik, blok "Javni podaci" s 26 poveznica, podnožje s 30). Blok
"1,1× veća šansa kad zove 3+ influencera" je tamni s velikim brojem, a razlika je 36 % naspram 33 %.

**Novo** (`novo-naslovna-phone.png`, `-desktop.png`, `usporedba-naslovna.png`): 5,1 ekran (računalo 3,4), 370 riječi,
0 emojija, 5 veličina slova, 3 slike.
- Prvi ekran: naslov, jedna rečenica, crni gumb "Zatraži pristup" preko cijele širine, pa traka Autopilota kao
  istaknuti panel: zelena točka "Uživo · pravi novac", naslov, jedna rečenica, tri broja (2,000 SOL u novčaniku,
  8 zatvorenih, −0,042 SOL rezultat, crveno jer je minus) i "Pogledaj uživo" na /autopilot. Na računalu su naslov i
  traka jedno do drugog.
- Četiri broja iz baze (2 × 2) i "Uživo iz baze · osvježeno prije 12 min".
- "Što dobiješ": četiri retka umjesto osam kartica s emojijima, jedan redak "Još: event tokeni, dugoročni tokeni, demo
  bot i copy trading", pa tri prave slike NOVIH ekrana (Tokeni, profil influencera, novčanik), vodoravno.
- "MemeSonar je live 9 dana": po noći jedan redak brojki (+4 influencera · +212 poziva · +96 tokena, svaki broj vodi na
  svoju stranicu) i jedan redak članaka s poveznicama.
- "Provjeri sam, bez prijave": prva tri retka javne ljestvice istim stupcima kao u aplikaciji (1 h, 24 h, presuda iz
  4.0), "Cijela ljestvica, 358 računa", pa Top 100 meme coina, Provjera ruga, Blog.
- Obrazac i Pitanja (5) jedno do drugog na računalu; podnožje kao danas (svih 30 poveznica) plus "Autopilot uživo".

**Uklonjeno, spojeno, preimenovano i gdje ostaje:**
- Pilula "Za sada besplatno" i kartica "Cijena 0 €" → jedan redak iznad naslova i rečenica ispod obrasca ("Bez kartice
  i plaćanja. Nikad ne tražimo seed frazu ni privatni ključ.").
- Tri slike u heroju, "Kako izgleda" (5) i galerija (6) → tri slike novih ekrana; mijenjaju se kad nove stranice budu
  gotove (do tada ostaju današnje, samo tri).
- Osam kartica funkcija → četiri retka i redak "Još".
- "1,1× veća šansa" → s naslovne van; ostaje u članku "Grupiranje influencera".
- Blok "Ljestvica influencera" s gumbom → tri retka ljestvice i poveznica.
- "Javni podaci MemeSonara" (26 poveznica) i ploča coina → tri retka; svih 26 ostaje u izborniku i podnožju, pa nijedna
  javna stranica ne gubi unutarnju poveznicu (SEO). Članci iz dnevnika ostaju poveznice kao danas.
- "Zatraži pristup" 7 → 3 (gumb u heroju, obrazac, gumb u traci na računalu); ljepljivi gumb na mobitelu ostaje.
  "Prijava" jednom (gore desno).
- Gradijent na "Solana tokene." → crni naslov; EN gore → "English" u podnožju (hreflang u zaglavlju ostaje).

**Trud: M.** `ui/landing.py` (`page_html`: redoslijed, CSS, `T`: funkcije 8 → 4, bez bloka "moć" i galerije,
`log_html`: jedan redak brojki po danu), `ui/apjavno.py` (`landing_strip` i `STRIP_CSS`: svijetli panel, hrvatski zapis
brojeva "2,000 SOL", "−0,042 SOL"), `ui/public.py` (`explore` se ne zove na naslovnoj, `_foot_links` dobiva "Autopilot
uživo"), nove slike u `ui/static/landing/` kad nove stranice budu gotove (S).

### 4.2 Tokeni: cijeli popis (/tokens)

**Sada** (`sada-tokeni-phone.png`, današnji kod): 6,8 ekrana, 580 riječi, 17 emojija, 75 ⓘ, 26 bedževa, 154 poveznice.
Iznad naslova dvije trake (crna "Autopilot je live" i siva "Novo"), pa ponovljeni "Prijedlog za danas". Za prazno
stanje, učitavanje i "nema rezultata" nema nacrta.

**Novo** (`novo-tokeni-popis-phone.png`, `-desktop.png`, `usporedba-tokeni-popis.png`): prvi ekran isti kao u prvom
krugu (`tokeni.html`); cijela stranica 1,8 ekrana do stanja (3,8 s njima), 0 emojija, 0 ⓘ, 5 veličina slova.
- Kraj popisa: redak "Odbačeni · 6 (rug ili pao na provjeri)" i jedna rečenica "Osvježeno prije 1 min, sljedeće za
  2 min. Povuci prema dolje za odmah." s "Što znači pouzdanost".
- Četiri stanja istog ekrana: (1) prvo učitavanje: sive linije umjesto redaka i "Učitavam tokene iz zadnja 24 h"; kad
  postoji spremljen popis, odmah se pokaže uz "Osvježavam, popis od 07:10"; (2) prazno "Novi": jedna rečenica zašto i
  "Pogledaj Jake"; (3) traženje bez rezultata: što je traženo i da zalijepljena adresa otvara bilo koji token;
  (4) dodir na "Poredano po pouzdanosti" otvara list odozdo: Poredaj po (Pouzdanost, Šansa za skok, Zadnji signal, Mcap,
  Rast 1 h) i dva prekidača (Rug: oprez, Samo sa smart walletima).
- Jaki i Dugoročni koriste isti redak.

**Uklonjeno, spojeno:** kao u prvom krugu (3.2). Novo su redak odbačenih i četiri stanja; "Sortiraj", "Tablica" i
"Stupci" na mobitelu → jedan list "Poredaj i filtriraj".

**Trud: S** povrh prvog kruga. `ui/tokens.py` (prazno stanje, redak odbačenih), `ui/cols.py` (list umjesto tri
kontrole na mobitelu), `ui/pagecache.py` (stari popis dok se gradi novi, kao za /kol).

### 4.3 Jedan token (/token/<adresa>)

**Sada** (`sada-token-phone.png`, `-phone-fold.png`, `-desktop.png`): 3,4 ekrana, 400 riječi, 6 emojija, 11 veličina
slova, 6 ⓘ, 7 sklopljenih slojeva. Na vrhu velikim "Šansa 87", a popis pokazuje pouzdanost 94 (ovdje "Confidence 94"
u tekstu). Za i Protiv su dva uska stupca (jedna do tri riječi u retku, 15 redaka za 4 razloga). Nema grafa ni
tržišta na jednom mjestu: cijena, promjene i kupnje/prodaje su u "Svježoj provjeri", holderi u sloju "Puls",
likvidnosti nema. Tko ga je zvao i smart walleti su sklopljeni slojevi. Osam ikona vanjskih stranica bez natpisa.
Kupnja (Natjecanje) je zadnja, s tri gumba i poljem iznosa.

**Novo** (`novo-token-phone.png`, `-phone-cijela.png`, `-desktop.png`, `usporedba-token.png`): 3,2 ekrana (računalo
2,1 umjesto 2,6), 330 riječi, 0 emojija, 6 veličina slova. Stranica nije puno kraća, ali sad na njoj ima i ono čega
danas nema (graf, tržište, tko je zvao) bez ijednog sklopljenog sloja.
- Vrh kao Apple Dionice: ime i kratka adresa (dodir kopira) lijevo, mcap i 24 h desno.
- Graf mcap-a (1 h | 6 h | 24 h | 7 d), iste linije kao graf Autopilota; točke su pozivi influencera.
- Presuda u panelu: "Pouzdanost 94 · šansa za skok 87", velikim "U zoni ulaza", jedna rečenica, pa jedan redak
  "Za: ... Protiv: ...".
- Dva gumba: "Kupi" (list: Autopilot 0,1 SOL, demo 50 $ na Natjecanju, DCA) i "Kopiraj adresu"; vanjske stranice
  kao riječi (DexScreener, Birdeye, GMGN, Solscan, X).
- "Tržište" kao na DexScreeneru: 5 min, 1 h, 6 h, 24 h u jednoj traci, pa cijena, likvidnost, volumen 1 h,
  kupnje/prodaje, holderi, top 10, starost, bondan.
- "Tko ga je zvao": redak po računu s presudom iz 4.0, mcap kod poziva i rast od tada; "Svih 24".
- "Smart walleti" (koliko je uložio, drži li još) i "Provjera ruga" (šest provjera kao reci, vrijeme zadnje).
- "Kako je dobio ocjenu": cijelo tumačenje, slojevi analize (6 od 7), puls uživo.

**Uklonjeno, spojeno, preimenovano:** "Šansa" kao glavni broj → pouzdanost (isti broj kao na popisu), šansa u istom
retku; "Confidence" → pouzdanost; stupci Za/Protiv → jedan redak (sve u "Cijelo tumačenje"); "Brojke" (6 kartica) →
panel i Tržište; sedam slojeva → redak "Slojevi analize 6 od 7" (isti sadržaj); blok Natjecanje → list "Kupi"; osam
ikona → pet riječi; "Svježa provjera" → Tržište i Provjera ruga.

**Trud: M.** `ui/pages.py` (`token()`: redoslijed i zaglavlje), `ui/narrative.py` (jedna rečenica), `ui/topcheckui.py`
i `live/pulse.py` (reci Tržišta i provjere ruga), `ui/quickbuy.py` (list "Kupi"), `ui/charts.py` (linija s točkama;
mcap iz snimki cijene u hype.db, pozivi iz kol.db).

### 4.4 Influenceri: cijela ljestvica (/kol)

**Sada** (`sada-influenceri-ljestvica-phone.png`, današnji kod): 19,5 ekrana, 1525 riječi, 29 emojija, 376 ⓘ, tablica
s 21 stupcem, 16 sklopljenih sekcija. Prijedlog na vrhu zove @Humanevolvd "dokazan, pogodak 71 %" i sam piše "još bez
minutne provjere: brojke su po staroj mjeri".

**Novo** (`novo-influenceri-ljestvica-phone.png`, `-desktop.png`, `usporedba-influenceri-ljestvica.png`): 2,6 ekrana
do stanja (3,6 s njima), 0 emojija, 0 ⓘ, 6 veličina slova.
- Hero "Najbolji za brzi ulaz i izlaz": @Humanevolvd, "● samo brzo · 30 poziva · Autopilot ga prati" i jedna rečenica
  s oba broja; ispod "Drže se i 24 h: @ddddddd8a · @bitecong".
- Segment Ljestvica | Upravo zvali; "Manje poznati računi · 238" i razdoblje "14 dana".
- Redak: mjesto, @ime, presuda i broj poziva (ili narančasto "rug 32 %" kad je rugova 30 % i više); desno dva broja,
  1 h i 24 h. Poredano po 1 h.
- Računi s manje od 5 poziva u skupini "Premalo poziva" (sivi brojevi), da 100 % na 2 poziva ne bude prvo.
- Računalo: 1 h, 24 h, Poziva, Ocjena, Rugovi, Uživo, Zadnji poziv.
- Stanja: Upravo zvali (token, tko, prije koliko, promjena), osvježavanje ("Osvježavam. Dotad ljestvica od 06:12",
  stara ljestvica odmah umjesto poruke "gradi se"), prazno za velike račune.

**Mijenja prvi krug:** hero "Koga danas slušati" i stanja "dokazan / prosječan" iz `influenceri.html` zamjenjuje
presuda iz 4.0; segment, filtar, Analize i stupci ostaju kako su u prvom krugu. U `pregled.html` redak "Vrijedi
pratiti: @Humanevolvd · 71 % pogodaka" postaje "samo brzo · 70 % u 1 h".

**Trud: L** (zajedno s prvim krugom). `ui/kol.py`, `ui/kolsummary.py` (`verdict`), `kol/minute.py` (`handle_stats`
već daje hit10; udio u plusu nakon 24 h iz kol.db), `ui/pravitrade.py` (`_kol_section`: ista riječ uz "najbolji
14 d"), `ui/public.py` (javna ljestvica, isti stupci).

### 4.5 Jedan influencer (/kol/<ime>)

**Sada** (`sada-influencer-phone.png`, `-phone-fold.png`, `-desktop.png`): 18,7 ekrana, 1466 riječi, 55 emojija,
360 ⓘ, 282 poveznice, 30 bedževa. Na vrhu šest kartica (moć poziva 58, moć po pratitelju 7,08×, pratitelja,
17 izmjerenih poziva, pogodak 71 %, hvalisanja 0) i red čipova; "Kako je dobio ocjenu" 9 kartica bodova; stupci
"Kako su mu prolazili pozivi" (lokalno 0 u plusu i 31 u minusu, na Jureovoj snimci 2 i 28) i "Da si uložio $10"
(−185 $) tek na šestom ekranu; "Koliko ga tržište sluša" 8 kartica; "Svi pozivi" 25 kartica po 12 polja (od 76).
Minutne mjere, po kojoj ga Autopilot zove "najbolji 14 d", na profilu nema.

**Novo** (`novo-influencer-phone.png`, `-phone-cijela.png`, `-desktop.png`, `usporedba-influencer.png`): 2,6 ekrana,
308 riječi, 0 emojija, 6 veličina slova.
- Presuda na vrhu: "Samo za brzi izlaz", "● samo brzo · 30 poziva · ocjena 58" i jedna rečenica: "U prvom satu 21 od
  30 poziva dođe do +10 %. Ako držiš dan, 28 od 30 završi u minusu."
- Četiri broja: nakon 60 min 21 od 30 (70 %); nakon 24 h 2 od 30 (28 u minusu); 10 $ u svaki poziv +3 $ s brzim
  izlazom i −185 $ ako držiš 24 h (prije naknada); stižemo li ga: da, pratimo ga uživo, +10 % dođe za medijan 6 min.
- Prekidač "Autopilot ga prati" s pravilom izlaza.
- Graf "10 $ u svaki poziv": dvije linije na jednoj osi (brzi izlaz i drži 24 h), vrijednosti u legendi.
- "Svaki poziv, redom": dva reda kvadratića (1 h i 24 h), zeleno plus, crveno minus. Razlika se vidi bez čitanja.
- "Zadnji pozivi" (5): token, kad, mcap kod poziva; desno ishod u prvom satu ("+10 % u 4 min", "stop −20 %") i
  24 h; pozivi ispod 30k $ pišu "ne broji se".
- "Više o njemu": kako je dobio ocjenu, koliko ga tržište sluša, zove zajedno s, njegov novčanik.

**Uklonjeno, spojeno, preimenovano:** šest kartica → presuda i četiri retka (pratitelji u podnaslovu, moć po
pratitelju i hvalisanje u "Kako je dobio ocjenu"); "moć poziva" → ocjena; "pogodak" → 1 h i 24 h (vrh +50 % ostaje
u bodovima); graf stupaca → dva reda kvadratića (broj na dodir); 25 kartica poziva → 5 redaka i "Svih 76" (podstranica
s današnjom tablicom); "Koliko ga tržište sluša" → redak, podstranica.

**Trud: M.** `ui/kol.py` (`kol_page` redoslijed, `_charts` → dvije linije i trake, "Svi pozivi" → podstranica),
`kol/minute.py` (`handle_stats` za jedan račun: hit10, sl, med_t10, `lag_s`), `ui/charts.py` (druga linija, traka),
`ui/kolsummary.py` (`verdict`), prekidač iz postojećeg praćenja Autopilota.

### 4.6 Novčanici (/wallets)

**Sada** (`sada-novcanici-phone.png`, `-phone-fold.png`, `-desktop.png`): 5,5 ekrana, 444 riječi, 72 ⓘ, 24 bedža;
svaki novčanik je kartica s 9 polja (Dokazani dvaput DA/ne, Prati Autopilot DA/ne, Autopilot 14 d "–" kod svih,
Copy s trakom, PnL, Win, Zatv., Medijan držanja, Neaktivan d). Na vrhu opet "Prijedlog za danas" (isti tekst kao na
Pregledu), iznad popisa legenda od 70 riječi.

**Novo** (`novo-novcanici-phone.png`, `-desktop.png`, `usporedba-novcanici.png`): 1,8 ekrana do stanja (2,8 s
njima), 0 ⓘ, 6 veličina slova. Donja traka je inačica za ostale korisnike (Novčanici umjesto Autopilota).
- Hero "Koga kopirati": Vfdn…At74, "● dokazan dvaput · kopirljiv · copy ocjena 80", jedna rečenica, zadnja kupnja.
- Segment Za kopiranje | Svi | Aktivnost, polje "Adresa ili oznaka", "Poredano po copy ocjeni".
- Redak: adresa, "● dokazan dvaput · drži 5 h" (ili "prati Autopilot"); desno zarada u SOL-u i "80 % od 20".
- Računalo: Copy, Zarada, U plusu, Drži, Dokazan, Autopilot, Zadnji trade.
- Na dnu "Ocijenjeno prije 2 h, sljedeće za 4 h · Ocijeni sada" i jedna rečenica što znače "dokazan dvaput" i
  "kopirljiv".
- Stanja: Aktivnost (tko je što kupio ili prodao), Svi (botovi i snajperi označeni narančasto), prazno.

**Uklonjeno, spojeno:** "Prijedlog za danas" → Pregled (prvi krug) i hero; legenda → rečenica na dnu i Pojmovnik;
"Autopilot 14 d" (prazno kod svih) → stupac na računalu kad ima broj; "Neaktivan d" → "Zadnji trade"; traka Copy →
broj; gumb "Ocijeni novčanike sada" → tekst u retku na dnu.

**Trud: M.** `ui/pages.py` (popis novčanika: kartice → reci, hero), `ui/cols.py`, `ui/prijedlog.py` (`box` van, prvi
krug).

### 4.7 Jedan novčanik (/wallet/<adresa>)

**Sada** (`sada-novcanik-phone.png`, `-phone-fold.png`, `-desktop.png`): 13,7 ekrana, 913 riječi, 29 emojija, 176 ⓘ,
260 poveznica. Šest kartica na vrhu (tier A, copy ocjena 80.0, ocjena profitabilnosti 80.0, NA COPY LISTI,
+11.86 SOL, 68 % (31)), od kojih su dvije isti broj; "Raspis ocjene" 8 kartica, "Raspis copy ocjene", "Statistika"
tablica s 25 redaka, 25 pozicija kao kartice s 10 polja, a graf zarade, stupci i povijest ocjena tek od desetog
ekrana. "Dokazan dvaput" (plus prije i poslije reza), glavni razlog zašto ga Autopilot kopira, na stranici se ne vidi.

**Novo** (`novo-novcanik-phone.png`, `-phone-cijela.png`, `-desktop.png`, `usporedba-novcanik.png`): 2,6 ekrana,
283 riječi, 0 emojija, 6 veličina slova.
- Presuda: "Vrijedi kopirati", "● dokazan dvaput · kopirljiv · copy ocjena 80", rečenica s brojkama prije i poslije
  reza.
- Četiri broja: zarada na zatvorenima +11,86 SOL (+68 % na uloženo), u plusu 21 od 31, drži 4 h 24 min (3,3 tradea
  dnevno), najveći trade 10 % zarade ("nije jedna sretna oklada").
- Prekidač "Autopilot ga kopira".
- Graf "Kako je zarađivao" s crtkanom crtom reza 5.11. i ispod "prije reza +7,40 SOL · 14/20, poslije +4,46 SOL · 7/11".
- Traka svih 31 zatvorenih pozicija (21 u plusu, 10 u minusu).
- "Zadnji tradeovi" (5, otvorena prva) i "Sve 31".
- "Više o njemu": kako je dobio ocjenu 80, sve brojke, povijest ocjena, zašto je u registru.

**Uklonjeno, spojeno:** šest kartica → presuda i četiri retka; "ocjena profitabilnosti 80.0" i "copy ocjena 80.0" →
jedan broj (razlika, kad postoji, u "Kako je dobio ocjenu"); tier → "Kako je dobio ocjenu"; dva raspisa → jedna
podstranica; "Statistika" (25 redaka) → "Sve brojke"; kartice pozicija → 5 redaka i "Sve 31"; stupci povrata → traka;
"Zašto je odabran / izdvojen" → redak.

**Trud: M.** `ui/pages.py` (`wallet()`: redoslijed, kartice → reci, raspisi na podstranicu), `wallets/dokazani.py`
(brojke prije i poslije reza za jedan novčanik; `realized_before/after` već postoje), `ui/charts.py` (okomita crta
reza, traka).

## 5. Preporučeni redoslijed (svi zasloni, prvi i drugi krug)

1. **Jedna večer (oko 3 do 4 sata), najveći vidljivi dobitak, sve S:**
   - `prijedlog.box` ostaje samo na Pregledu (makni ga iz `ui/tokens.py`, `ui/kol.py` i `ui/pages.py` za
     Novčanike). Tokeni, Influenceri i Novčanici odmah počinju svojim popisom.
   - Traka "Novo" postaje točka na "Više"; ☰ se skriva na mobitelu.
   - Autopilot u donju traku za administratora (popis BOTTOM u `ui/html.py`).
   - Zajednički CSS: pet veličina slova, redak, segment, točka stanja, panel presude (`ui/html.py`).
   - **Pitanje za Juru:** crna traka "Autopilot je live" (danas na vrhu svake stranice aplikacije, iznad trake "Novo")
     neka bude jedan redak na Pregledu i točka uz Autopilot u traci, a ostaje velika samo na naslovnici. Tražio ju je
     danas, pa bez njegovog da ne dirati.
2. **Jedna presuda za influencera (4.0), M:** `kolsummary.verdict` iz 1 h i 24 h; na profilu presuda i četiri broja
   na vrh (4.5, bez grafa i traka u prvom koraku), ista riječ u Autopilotu ("najbolji 14 d · samo brzo"), na Pregledu
   i stupci 1 h i 24 h na ljestvici. Ide rano jer nije samo izgled: Autopilot trguje pravim novcem po mjeri koju
   profil danas ne pokazuje, a ljestvica isti račun zove "dokazan".
3. **Autopilot (3.4), M:** pravila iz `dizajn.md` grupi apui, reci pozicija, prekidač, "Još".
4. **Naslovnica (4.1), M:** naslov i "Zatraži pristup" na prvo mjesto, traka Autopilota kao svijetli panel ispod,
   12 sekcija na 7. Slike novih ekrana tek u koraku 9. Javna je i prvi dojam, a danas joj traka gura objašnjenje na
   dno prvog ekrana.
5. **"Više" kao stranica (3.5), M.**
6. **Tokeni (3.2 i 4.2) i jedan token (4.3), M + M:** reci, stanja, list "Poredaj i filtriraj"; token s presudom,
   grafom i tržištem.
7. **Novčanici (4.6) i jedan novčanik (4.7), M + M.**
8. **Pregled (3.1), M.**
9. **Ostatak influencera (3.3, 4.4, 4.5), L:** cijela ljestvica (hero, "Premalo poziva", Analize kao podstranica),
   graf i trake na profilu, "Svi pozivi" kao podstranica; pa nove slike na naslovnici (S).

Ukupno oko 3 do 4 večeri za korake 1 do 4 i još oko tjedan dana večeri za 5 do 9 (procjena). Deploy po pravilu:
svaki korak je jedan merge sa svim svojim promjenama, izvan 01 do 06 CET.

## 6. Što namjerno ne mijenjamo

- Boje (sve varijable iz `ui/html.py`), svijetlu temu, crne gumbe, logo i font.
- Adrese i tri glavne funkcije (Tokeni, Influenceri, Novčanici). Nijedna stranica se ne briše, samo se seli
  jedan dodir dalje.
- Podatke, izračune i pravila trgovanja: pragovi (30k $ mcap, samo bondani), "dry" način, provjere i potvrde
  prije prodaje. Presuda iz 4.0 samo pokazuje mjere koje već postoje (`kol/minute.py`, `calls.r24h`).
- Tablice sa svim stupcima na računalu i sve brojke detalja: u drugom krugu stranice detalja dobivaju presudu na
  vrhu, a raspisi, statistika i svi pozivi ostaju jedan dodir dalje.
- Natjecanje (39,9 ekrana) i Copy trading (25,9 ekrana) u ovom krugu; to su sljedeći kandidati za ista pravila.
- Prijavu. (Javna naslovnica je u drugom krugu, 4.1.)

## Provjereno i pretpostavke

**Provjereno:** sve brojke "sada" su iz `sada-metrics.json` i snimaka lokalne kopije (izmišljeni podaci iz
`seed_app.py`, ne produkcija); makete su renderirane u Chromiumu na 390×844 i 1280×800 i pregledane; brojke "novo"
su isto mjerenje (`novo-metrics.json`); vodoravni preljev Autopilota vidi se na snimci (417 px).

**Pretpostavke:** da Autopilot otvaraš češće od Novčanika (posjete po stranici nisam mjerio; provjeriti prije
promjene trake); brojke grafa i sažetak dnevnika u maketi Autopilota su primjer (tablice equity i aplog nisu u ovom
worktreeju); tečaj SOL 162 $ i 1 $ = 0,86 € samo za maketu; da je mobilni redoslijed Tokena po Šansi koja se ne
prikazuje; procjene truda.

**Provjereno (drugi krug):** "sada" je snimljen na kopiji današnjeg koda (f4dc160, `git archive` u scratchpad) s
podacima iz `seed_app.py`; za Tokene, token, ljestvicu, influencera, Novčanike i naslovnicu `sada-metrics.json` je
prepisan tim snimanjem (brojke "sada" u odjeljku 3 su s koda prije današnjih promjena). Makete su renderirane na
390×844 i 1280×800, pregledane, i nijedna nema vodoravni preljev. Mjere su iz koda: `kol/minute.py` (+10 % prije
stopa −20 % u 60 min, hot lista koja se čita svake 1 do 2 s), `ui/kol.py` `_charts` (cijena 24 h poslije, 10 $ po
pozivu), `ui/pravitrade.py` ("najbolji 14 d" po minutnoj mjeri), `ui/sitelog.py` (live od 1.11., dakle 9 dana).

**Pretpostavke (drugi krug):** brojke 24 h na profilu (2 u plusu, 28 u minusu, −185 $) su s Jureove snimke, a račun
na njoj nije imenovan: u maketi je @Humanevolvd jer lokalna kopija za njega pokazuje isti obrazac (0 u plusu,
31 u minusu, oko −190 $). Brojke prvog sata (21 od 30, +10 % za 6 min, +3 $ s brzim izlazom) i postotci 1 h i
24 h na ljestvici su primjer (lokalna kopija nema minute.db). Pragovi presude su prijedlog. Brojke trake Autopilota
na naslovnici (2,000 SOL, 8, −0,042 SOL) su izmišljene, a "live" je samo u lokalnom procesu. Oblik grafova tokena i
novčanika je primjer (zbrojevi su točni: +7,40 i +4,46 SOL, +3 i −185 $). Da hype.db ima dovoljno gustih snimki cijene
za graf od 1 h; da je broj odbačenih tokena dostupan iz rug filtra; tokeni BLOOP i WOJAK su izmišljeni; procjene truda
i vremena.
