# Miran i pregledan MemeSonar: prijedlozi dizajna (10.11.2026.)

Odgovor ukratko: svaki ekran neka počne jednim odgovorom (jedan veliki broj ili jedno ime), ispod toga kratki reci
"ime + jedan razlog + jedan broj", a sve ostalo jedan dodir dalje. Isti blok ne ponavljati na četiri stranice, maknuti
emojije, ⓘ uz svaki broj i stalne trake, i staviti Autopilot u donju traku. Makete pet zaslona su gotove i snimljene.

Kako gledati:
- makete (otvaraju se izravno u pregledniku, sve je u jednoj datoteci): `audit/2026-11-10/makete/pregled.html`,
  `tokeni.html`, `influenceri.html`, `autopilot.html`, `izbornik.html`
- snimke su u `/tmp/claude-0/-home-user/4912361d-d525-5b3e-b714-652a838e02b7/scratchpad/shots/ui/`:
  `sada-*.png` (današnja aplikacija), `novo-<zaslon>-phone.png` i `-desktop.png` (makete),
  `usporedba-<zaslon>.png` (prvi ekran mobitela, lijevo sada, desno novo, s brojkama ispod)
- ponovno snimanje: `python3 audit/2026-11-10/makete/sastavi.py && node audit/2026-11-10/makete/snimi.js`
  (sastavi.py upisuje zajednički CSS, traku i bočni izbornik u svih pet maketa; snimi.js snima i mjeri isto kao
  `shots.js` za "sada", pa su brojke usporedive)

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

## 4. Preporučeni redoslijed

1. **Jedna večer (oko 3 do 4 sata), najveći vidljivi dobitak:**
   - `prijedlog.box` ostaje samo na Pregledu (makni ga iz `ui/tokens.py`, `ui/kol.py` i `ui/pages.py` za
     Novčanike). Tokeni i Influenceri odmah počinju svojim popisom; tri stranice kraće za oko 1,3 do 1,5 ekrana. (S)
   - Traka "Novo" postaje točka na "Više"; ☰ se skriva na mobitelu. (S)
   - Autopilot u donju traku za administratora (popis BOTTOM u `ui/html.py`). (S)
   - Zajednički CSS: pet veličina slova, redak, segment, točka stanja (`ui/html.py`). Odmah smiruje sve stranice. (S)
2. **Autopilot:** pravila iz točke 2 predati grupi apui sada, dok gradi graf i dnevnik; ostatak (reci pozicija,
   prekidač, "Još") ista ili sljedeća večer. (M)
3. **"Više" kao stranica** umjesto ladice. (M)
4. **Tokeni u recima.** (M)
5. **Pregled** s herojem i tri kratke sekcije. (M)
6. **Influenceri** (najveći posao, ali i najveća razlika: 20,1 → 2,2 ekrana). (L)

Deploy po pravilu: sve skupiti u jedan merge, izvan 01 do 06 CET.

## 5. Što namjerno ne mijenjamo

- Boje (sve varijable iz `ui/html.py`), svijetlu temu, crne gumbe, logo i font.
- Adrese i tri glavne funkcije (Tokeni, Influenceri, Novčanici). Nijedna stranica se ne briše, samo se seli
  jedan dodir dalje.
- Podatke, izračune i pravila trgovanja: pragovi (30k $ mcap, samo bondani), "dry" način, provjere i potvrde
  prije prodaje.
- Stranice detalja (token, influencer, wallet) i tablice sa svim stupcima na računalu, za kad treba sve brojke.
- Natjecanje (39,9 ekrana) i Copy trading (25,9 ekrana) u ovom krugu; to su sljedeći kandidati za ista pravila.
- Javnu naslovnu i prijavu.

## Provjereno i pretpostavke

**Provjereno:** sve brojke "sada" su iz `sada-metrics.json` i snimaka lokalne kopije (izmišljeni podaci iz
`seed_app.py`, ne produkcija); makete su renderirane u Chromiumu na 390×844 i 1280×800 i pregledane; brojke "novo"
su isto mjerenje (`novo-metrics.json`); vodoravni preljev Autopilota vidi se na snimci (417 px).

**Pretpostavke:** da Autopilot otvaraš češće od Novčanika (posjete po stranici nisam mjerio; provjeriti prije
promjene trake); brojke grafa i sažetak dnevnika u maketi Autopilota su primjer (tablice equity i aplog nisu u ovom
worktreeju); tečaj SOL 162 $ i 1 $ = 0,86 € samo za maketu; da je mobilni redoslijed Tokena po Šansi koja se ne
prikazuje; procjene truda.
