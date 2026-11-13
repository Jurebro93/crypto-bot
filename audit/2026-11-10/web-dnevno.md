# Javni web: odakle svaka stranica dobiva brojke i koliko mogu biti stare (10.11.2026.)

Jure: "podaci bi se trebali jednom dnevno osvježiti na cijelom webu, znači da sve tablice na cijelom webu budu
prikazane s novim podacima; možda napravi zadatak u 2 po noći."

## Kratko

- **Provjereno (kod):** javne tablice se već danas grade iz naših baza pri otvaranju stranice i u memoriji web
  procesa žive najviše 15 minuta (`ui/public.CACHE_S`), tržište 30 + 15 minuta, brojke naslovnice 30 minuta. Nijedna
  javna tablica nije "zamrznuta" kešom. Starost ovisi o tome kad je petlja koja puni bazu zadnji put radila.
- **Provjereno (kod):** jedino što se nikad nije osvježavalo su brojke u tekstovima bloga (upisane u kod, sa
  snimke 30.10., 1.11. ili 8.11.) i `lastmod` u sitemapu (uvijek današnji datum za sve, i za tekst koji se ne mijenja).
- **Napravljeno:** posao `web` u 02:00 po Zagrebu (`run_sched.py` -> `run_web.py daily`) ponovno pročita listu
  coina ako je starija od sat vremena, prebroji "Stanje danas" za 13 članaka bloga, upiše redak u dnevnik weba
  (`public.db site_log`) i time javi web procesu da odbaci sve kopije u memoriji i odmah ponovno složi glavne tablice.
- **Pretpostavka:** Jurin dojam da je /influencers "star" dolazi od toga što javna stranica pokazuje samo pozive
  starije od 24 h i što se ocjena mijenja sporo; u kodu nema keša duljeg od 15 minuta. Na produkciji to nisam mogao
  provjeriti (sandbox nema pristup stranici).

## Karta

| stranica | izvor brojki | keš | koliko stara može biti danas | nakon ove promjene |
|---|---|---|---|---|
| `/`, `/hr` brojke (tokeni, novčanici, influenceri, pozivi) | hype.db, wallets.db, kol.db, tg.db: jeftini COUNT / MAX(rowid) u pozadinskoj dretvi (`ui/landing.compute`) | memorija 30 min | do 30 min; omjer "3+ influencera" do 90 min (`ourtoken/advisor` 1 h) | isto, plus odbacuje se i broji odmah nakon 02:00; uz brojke se čita i dnevnik weba |
| `/`, `/hr` blok "MemeSonar je live N dana" (novo) | public.db `site_log` (redak noćnog posla), čita se uz brojke naslovnice, nikad pri otvaranju | memorija, uz brojke | do 30 min iza noćnog posla; u praksi minuta (oznaka) | n/a |
| `/influencers`, `/hr/influenceri` | kol.db `kols.score`, `kols.stats` (KOL krug svakih ~20 min), `calls` | memorija 15 min | 15 min iza zadnjeg KOL kruga; prikazuju se samo pozivi stariji od 24 h | isto; u 02:00 kopija se odbaci i tablica se odmah složi nanovo |
| `/influencer/<račun>`, `/hr/influencer/<račun>` | kol.db `calls` (čisti pozivi, `ui/kolstats`), medijan svih računa | 15 min; medijan računa 1 h | do 15 min, usporedba s medijanom do 1 h | isto; u 02:00 se odbace i stranica i medijan |
| `/telegram-channels`, `/telegram/<kanal>` (+ hr) | kol.db pozivi `tg:<kanal>`, tg.db naslov i članovi | 15 min | do 15 min iza KOL kruga | isto; odbacuje se u 02:00 |
| `/solana-meme-coins`, `/coin/<slug>` (+ hr) | public.db `coins`, `coin_hist` (Jupiterova besplatna lista svaka 3 h, dretva web procesa); svijeće i holderi iz dugo.db (noćni prolaz); pozivi iz kol.db | 15 min | lista do 3 h 15 min; svijeće i holderi do jednog dana | u 02:00 lista se čita ponovno ako je starija od 1 h; ostalo isto |
| `/how-to-buy/...`, `/rug-check/...`, prognoza cijene, dnevne liste (rast, popularni, novi) (`ui/coinseo`) | public.db, dugo.db | 15 min | kao coin stranice | kao coin stranice |
| `/solana-market`, `/meme-coin-season-index`, `/solana-launchpads`, `/solana-dex-volume`, `/best-time-to-trade-crypto`, `/embed/...` (+ hr) | market.db (DefiLlama, posao `market` svaki sat), kol.db | snimka 30 min (`ui/marketpub`) + 15 min | do 45 min iza satnog skupljanja; podaci su "zadnji puni UTC dan" | isto; u 02:00 se snimka računa nanovo (stara ostaje ako računanje padne) |
| `/blog`, kategorije, članci (+ hr) | tekst i brojke upisani u kod (`ui/blogposts*.py`) | 15 min | brojke su sa snimke navedene u tekstu (30.10., 1.11., 8.11.); mijenjale su se samo deployem | 13 članaka o našim mjerenjima dobiva blok "Stanje danas" koji se broji svake noći (`ui/bloglive.py`); `dateModified` prati noć kad su se brojke promijenile |
| `/glossary/...`, `/best-crypto-tools/...`, vodiči za botove (+ hr) | upisano u kod (`ui/glossary_public.py`, `ui/toolsdata.py`, `ui/botguides.py`) | 15 min | ne mijenja se bez deploya (cijene alata se upisuju ručno) | bez promjene |
| `/sitemap.xml` | popisi svih gornjih stranica | 15 min | `lastmod` = današnji datum za svaki URL, svaki dan | članci bloga nose dan kad su se stvarno promijenili; stranice s podacima ostaju na današnjem datumu (istina je: grade se iz baza cijeli dan) |
| `/robots.txt` | kod | 15 min | ne mijenja se | bez promjene |
| `/share/novosti.png` | share/novosti.json | po zahtjevu | mijenja se deployem | bez promjene |
| snimke stranica na disku (`$DATA_DIR/pagecache`) | stranice aplikacije iza prijave (`ui/pagecache.py`) | disk, do 24 h | nisu javne; osvježavaju se svakih 5 min | ne diramo |

## Što posao u 02:00 radi (i što ne)

1. Lista top 100 meme coina (public.db): ponovno se čita s Jupiterove besplatne liste ako je starija od sat vremena.
   To je jedini mrežni poziv posla; besplatan je, bez ključa, i web proces ga ionako radi svaka 3 h.
2. Blokovi "Stanje danas" za blog: brojanje u kol.db, wallets.db, tg.db i hype.db (jedno čitanje tablice poziva).
3. Redak u `site_log`: brojke te noći, razlika prema prošloj noći (samo rast), članci s novim brojkama, novi članci.
4. Taj redak je ujedno oznaka. Web proces je gleda jednom u minuti u pozadinskoj dretvi (jedan redak po ključu,
   nikad pri otvaranju stranice); kad se pomakne, jednom odbaci kopije u memoriji (javne stranice, snimka tržišta,
   medijan računa, omjer grupnih poziva, brojke naslovnice) i složi glavne tablice na oba jezika s pauzom između.

Posao ne zove nijedan plaćeni izvor. Traje nekoliko sekundi, pa ide kao "laki" posao (bez brave teških poslova):
iza noćnih dugih poslova (KOL povijest, učenje) čekao bi satima i "02:00" bi značilo 05:00. Prioritet procesa je
spušten na razinu ostalih pozadinskih poslova (nice 10, postavljeno na tu razinu, ne dodano: raspored koji ga pokreće
nakon promjene grupe "pogon" i sam radi na nice 10). Ako server u 02:00 ne radi, posao se odradi pri prvoj provjeri
nakon toga istog dana; dan se pamti u `sched_state.json`, pa ga deploy ne ponavlja. Neuspjeh: novi pokušaj za 30 min,
najviše 3 pokušaja po danu.

Lanac (provjereno testom koji pokreće pravi proces, `tests/test_web_daily_offline.py` EndToEnd): `start.sh`
(`keep sched python3 run_sched.py`) -> `run_sched.py` posao `web` (`daily_local`, 02:00 Zagreb, ljeti i zimi) ->
`run_web.py daily` kao zaseban kratki proces -> redak u `site_log` -> web proces (`run_ui.py` -> `landing.start()` ->
`sitelog.watch`) jednom u minuti pogleda oznaku i jednom odbaci kopije.

Prvi put nakon deploya posao se pokreće 3 min nakon starta rasporeda (taj dan još nije odrađen), pa naslovnica ima
prvi zapis odmah, ne tek sljedeće noći. Prvi zapis nema razliku (nema prethodnog dana): imenuje članke iz zadnjeg
tjedna i blogove koji su prvi put dobili blok "Stanje danas".

"Novi članci": članak je nov tjedan dana od svog datuma, dok ga neki redak ne imenuje (ne "datiran poslije prethodnog
retka": članak s današnjim datumom koji stigne deployem iza 02:00 inače bi pao između dva retka).

## Što se može osvježiti samo plaćenim pozivom (nije dodano)

- Novi X pozivi i broj pratitelja influencera: čitači objava (twitterapi.io / Apify / xquik) u KOL petlji, svaki
  sa svojim dnevnim stropom. Noćni posao ih ne zove; čita ono što su oni već spremili.
- Ocjene i povijest tradeova novčanika: Helius krediti u noćnom `run_wallets.py score`. Isto: samo čitamo rezultat.
- Sve ostalo javno ide iz besplatnih izvora (Jupiter lista, DefiLlama, GeckoTerminal, t.me/s) ili iz naših baza.
