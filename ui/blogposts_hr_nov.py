"""Hrvatske verzije deset postova od 1. 11. 2026. (ui/blogposts_nov.py). Iste brojke i isti izvori kao engleske.
Nijedna brojka nije MemeSonar mjerenje: svaka je tuđi slučaj ili studija i izvor stoji uz nju."""
from ui.blogposts_hr import post
from ui.blogviz import bars, stats


def B(*a, **k):
    return bars(*a, lang="hr", **k)


# 1 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "address-poisoning", "address-poisoning-provjera-adrese", "Prevare",
    "Metoda: kako provjeriti adresu prije slanja da te ne opelješi address poisoning",
    "Address poisoning: kako provjeriti kripto adresu prije slanja | MemeSonar",
    "Address poisoning ti ubaci lažnu adresu u povijest odmah nakon testne uplate. Točna rutina koja to sprječava u "
    "Phantomu, MetaMasku i na mjenjačnicama.", 6,
    "Address poisoning je prevara u kojoj ti napadač pošalje sitnu ili nultu uplatu s adrese koja počinje i završava "
    "istim znakovima kao adresa koju koristiš. Ako kasnije adresu kopiraš iz povijesti, novac šalješ napadaču. Rješenje "
    "je rutina: nikad ne kopiraj iz povijesti, spremi adrese u adresar i provjeri znakove u sredini, ne samo početak i kraj.",
    f"""
<h2>Kako napad radi</h2>
<p>Novčanici skraćuju adrese na prvih i zadnjih nekoliko znakova, npr. <code>0xbaf4...B6495F8b5</code>. Napadač
generira adresu koja se poklapa u tim vidljivim znakovima i ubaci je u tvoju povijest na jedan od tri načina: sitna
"dust" uplata tebi, lažni token ili (na EVM lancima) prijenos nulte vrijednosti koji izgleda kao da je od tebe.
Sljedeći put kad otvoriš "nedavno" i kopiraš adresu na vrhu, ona je njegova.</p>
<p>Napadača to ne košta gotovo ništa. Studija sa Sveučilišta Carnegie Mellon izbrojala je oko 270 milijuna pokušaja
na Ethereumu i BNB Chainu između srpnja 2022. i lipnja 2024., na 17 milijuna novčanika, uz više od 83 milijuna dolara
potvrđenih gubitaka. Blockaid kaže da je samo u 2025. označio više od 65 milijuna takvih transakcija, a i Solana ima
svoje automatizirane alate za to.</p>

{B("Pojedinačni gubici od address poisoninga", [
    ("Novčanik 0xcB80 (prosinac 2025.)", 50_000_000, "poslao 50 mil. USDT nakon testne uplate od 50 USDT"),
    ("Adresa povezana sa sillytuna", 24_000_000, "ispražnjen aEthUSDC"),
    ("Bofur Capital", 2_000_000, "kopirao lažnu adresu nakon povlačenja s Compounda"),
    ("Neimenovani novčanik (28. 10. 2026.)", 50_059, "isti prva 4 i zadnjih 6 znakova"),
    ("Solana novčanik (studeni 2025.)", 30_750, "lažna adresa poslala dust 12 sekundi nakon testne uplate"),
], sub="Američki dolari izgubljeni u jednom prijenosu", fmt="usd", hl=(0,),
   source="lookonchain, PeckShield, Scam Sniffer, CryptoSlate (svaki slučaj kako su ga oni objavili)")}

<h2>Dio koji većina propusti: testna uplata</h2>
<p>Testna uplata djeluje sigurno. U najvećim slučajevima upravo je ona bila okidač. Žrtva pošalje 50 USDT na svoju
adresu, bot to vidi na lancu i za nekoliko sekundi lažna adresa pošalje dust na isti novčanik. Žrtva se zatim vrati u
povijest da kopira "adresu koja je radila" i uzme lažnu. Test te ne štiti; štiti te <b>odakle kopiraš adresu</b>.</p>

<h2>Rutina, korak po korak</h2>
<ol>
<li><b>Spremi svaku adresu na koju šalješ više puta.</b> Phantom: Settings, Address Book, Add address. MetaMask:
Settings, Contacts. Daj joj ime koje ćeš prepoznati ("Binance uplata SOL"). Od tada šalješ birajući ime, nikad
lijepljenjem.</li>
<li><b>Nikad ne kopiraj adresu iz povijesti transakcija.</b> Ni u novčaniku, ni na Solscanu ili Etherscanu. Kopiraj je
iz izvora: stranice za uplatu na mjenjačnici, ekrana "Receive" u svom novčaniku ili iz adresara.</li>
<li><b>Provjeri sredinu, ne krajeve.</b> Napadači poklapaju prve i zadnje znakove jer njih vidiš. Usporedi 4 znaka iz
sredine adrese s izvorom. Traje pet sekundi.</li>
<li><b>Nakon testne uplate ne vraćaj se u povijest.</b> Glavni iznos pošalji iz istog izvora kao test (adresar ili
stranica mjenjačnice), ne iz "nedavno".</li>
<li><b>Sakrij spam u exploreru.</b> Na Solscanu uključi "Hide spam" i "Hide low value" u tablici aktivnosti. Nulti
prijenosi i dust koji nisi tražio znak su da si meta.</li>
<li><b>Uključi whitelist na mjenjačnicama.</b> Većina velikih mjenjačnica dopušta povlačenje samo na spremljene adrese,
uz čekanje za nove. Uključi to prije nego što ti zatreba.</li>
</ol>

<h2>Ako si već poslao na krivu adresu</h2>
<p>Prijenos na blockchainu ne može se poništiti. Što još pomaže: brzo objavi hash transakcije i adresu napadača,
prijavi to mjenjačnici na koju sredstva idu (mjenjačnice mogu zamrznuti uplate ako na vrijeme saznaju) i prijavi
policiji, jer mjenjačnice to često traže. Velike krađe ponekad su djelomično zamrznute na ovaj način, male rijetko,
zato je rutina iznad važnija od povrata.</p>
<p>Povezano: <a href=/hr/blog/lazna-podrska-ledger-prevara>skripta za lažne pozive podrške</a> i
<a href=/hr/blog/kako-prepoznati-rug-pull>kako prepoznati rug pull</a>.</p>
""")


# 2 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "zero-trust-support-calls", "lazna-podrska-ledger-prevara", "Prevare",
    "Metoda: \"zove te podrška Ledgera\", provjera u 5 pitanja koja zaustavlja lažnu podršku",
    "Lažna podrška Ledgera i mjenjačnica: kako provjeriti poziv u 5 pitanja | MemeSonar",
    "Najveće kripto krađe zadnjih godina nisu bile hakovi nego ljudi koji glume podršku. Pet pitanja prije nego "
    "napraviš bilo što što ti 'agent podrške' kaže.", 6,
    "Prava podrška novčanika i mjenjačnica nikad te ne zove prva, nikad ne traži seed frazu i nikad ne traži da "
    "prebaciš sredstva u 'sigurni' novčanik. Ako se išta od toga dogodi, prekini i sam se javi podršci kroz aplikaciju "
    "ili adresu koju sam upišeš.",
    f"""
<h2>Zašto je ovo napad koji danas radi</h2>
<p>Hakovi pametnih ugovora dobiju naslove, ali mnogi od najvećih osobnih gubitaka u zadnje dvije godine došli su iz
jednog telefonskog poziva. On-chain istražitelj ZachXBT pratio je nekoliko njih. Obrazac se ponavlja: netko zove ili
piše kao "Ledger podrška", "Coinbase sigurnost" ili "Trezor", kaže da je račun ili uređaj kompromitiran i vodi te kroz
"zaštitu" sredstava, ravno u svoj novčanik.</p>

{B("Gubici u slučajevima lažne podrške (social engineering)", [
    ("Prevara s hardverskim novčanikom, siječanj 2026.", 282_000_000, "LTC i BTC, u satima pretvoreni u Monero"),
    ("Vjerovnik Genesisa, kolovoz 2024.", 243_000_000, "ista grupa povezana je s drugim krađama"),
    ("Lažna podrška mjenjačnice i novčanika, kolovoz 2025.", 91_000_000, "783 BTC"),
    ("Jedan napadač iz SAD-a, više žrtava", 19_000_000, "ukupno povezano s jednom osobom"),
], sub="Američki dolari, kako je objavljeno u to vrijeme", fmt="usd", hl=(0,), source="istrage ZachXBT-a na X-u")}

<p>Sama krađa je tehnički jednostavna. Ključevi su sigurni dok ih ne predaš, ne upišeš seed frazu na stranicu za
"provjeru", ne instaliraš "sigurnosni softver" ili sam ne odobriš prijenos. Zato je obrana skripta, a ne alat.</p>

<h2>5 pitanja</h2>
<ol>
<li><b>Jesam li ja njih prvi kontaktirao?</b> Ako nisi, stani. Ledger jasno kaže da nikad ne zove, nikad ne šalje
poruke i nikad ne traži tvojih 24 riječi. Mjenjačnice rade isto. Dolazni poziv, SMS ili DM je prevara dok se ne
dokaže suprotno.</li>
<li><b>Traže li seed frazu, privatni ključ ili "provjeru" riječi?</b> Za to ne postoji legitiman razlog. Seed fraza
upisuje se samo na sam uređaj, kad ga postavljaš ili vraćaš.</li>
<li><b>Traže li da prebacim sredstva na novu "sigurnu" adresu ili "trezor"?</b> To je najčešći kraj skripte. Prava
podrška ne može i ne prebacuje tvoj kripto.</li>
<li><b>Traže li da nešto instaliram ili podijelim ekran?</b> Alati za udaljeni pristup daju im tvoje računalo.
Reci ne.</li>
<li><b>Postoji li rok?</b> "Sredstva će nestati za 30 minuta" je pritisak, a ne sigurnost. Pravi problemi čekaju da se
sam prijaviš.</li>
</ol>
<p>Jedno "da" je dovoljno. Prekini, zatim otvori službenu aplikaciju ili sam upiši adresu podrške (ne link iz
poruke) i pitaj tamo.</p>

<h2>Kako te pronađu</h2>
<ul>
<li><b>Javna pitanja podršci.</b> Postaviš pitanje službenom računu podrške na X-u i lažna "podrška" ti piše u
nekoliko minuta. Umjesto toga koristi sustav prijava u aplikaciji.</li>
<li><b>Procurjeli podaci kupaca.</b> Stara curenja podataka mjenjačnica i trgovina novčanicima sadrže imena, brojeve
telefona i kućne adrese, zato pozivatelj već zna kako se zoveš.</li>
<li><b>Papirnata pisma i e-mailovi.</b> Ledger je potvrdio lažna pisma poslana poštom u kojima se od kupaca traži
"nadogradnja sigurnosti" sa seed frazom.</li>
</ul>

<h2>Ako si već negdje upisao seed frazu</h2>
<p>Smatraj novčanik izgubljenim. Napravi novi novčanik s novom seed frazom na uređaju kojem vjeruješ i odmah prebaci
sve što je još tamo, počevši od najvećeg iznosa. Staru seed frazu više ne koristi ni za što.</p>
<p>Povezano: <a href=/hr/blog/address-poisoning-provjera-adrese>address poisoning</a> i
<a href=/hr/blog/kako-kupiti-solana-meme-coine>kako sigurno kupiti meme coine</a>.</p>
""")


# 3 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "polymarket-rules-checklist", "polymarket-pravila-provjera", "Prediction marketi",
    "Metoda: kako pročitati pravila Polymarket tržišta prije nego uložiš (6 točaka)",
    "Kako se rješavaju Polymarket tržišta: pravila, UMA sporovi i checklista | MemeSonar",
    "Na Polymarketu možeš točno predvidjeti događaj i svejedno izgubiti, jer tržište rješavaju napisana pravila. "
    "Checklista od 6 točaka i kako rade UMA sporovi.", 7,
    "Polymarket tržište isplaćuje prema napisanim pravilima i izvoru rješavanja, a ne prema onome što većina misli da "
    "se dogodilo. Prije kupnje pročitaj datum završetka i vremensku zonu, točnu formulaciju, izvor rješavanja i što "
    "se događa u rubnim slučajevima, i znaj da sporno tržište može isplatiti tek za dva dana ili više.",
    f"""
<h2>Zašto ljudi gube iako su bili u pravu</h2>
<p>Svako Polymarket tržište ima okvir "Rules" ispod grafa. Taj tekst, a ne naslov, odlučuje tko dobiva novac.
Iskusni traderi poput Domera, koji na stranici trguje od 2021., pisali su duge objave o tržištima riješenima protiv
očite stvarnosti zbog jedne riječi, propuštene vremenske zone ili izvora rješavanja koji je rekao nešto drugo. Kalshi
je imao iste svađe, npr. kad je u "mention" tržištu odlučio da izgovoreno "Alexis de Tocqueville" vrijedi kao
spominjanje tvrtke John Deere.</p>

<h2>Kako rješavanje radi</h2>
<p>Polymarket koristi UMA Optimistic Oracle. Bilo tko može predložiti ishod uz polog (obično 750 dolara u USDC-u).
Ako ga nitko ne ospori u roku za prigovor, tržište je riješeno. Ako ga netko ospori, daje se novi prijedlog, a drugi
prigovor šalje pitanje na glasanje vlasnika UMA tokena.</p>

{B("Najkraće vrijeme do isplate", [
    ("Bez spora", 2, "prođe rok za prigovor od 2 sata"),
    ("Jedan spor, novi prijedlog prihvaćen", 4, "još jedan rok od 2 sata"),
    ("Dva spora, ide na UMA glasanje", 52, "plus oko 48 sati glasanja"),
], sub="Sati od prvog prijedloga (najmanje, može biti i dulje)", fmt="num", hl=(2,),
   source="dokumentacija Polymarketa i UMA-e")}

<p>Kritike su usmjerene na glasanje. Izvještaji su pokazali da mali broj velikih vlasnika UMA tokena odlučuje mnoge
sporove i da velik dio aktivnih glasača i sam trguje na Polymarketu. UMA je 2025. ograničila prijedloge na odobrene
račune da smanji broj loših prijedloga. Ništa od toga ne mijenja praktično pravilo: ako se o tržištu može raspravljati,
pretpostavi da hoće.</p>

<h2>Checklista prije kupnje</h2>
<ol>
<li><b>Datum završetka i vremenska zona.</b> "Do 31. prosinca" znači određeno vrijeme u određenoj zoni, napisano u
pravilima. Događaj koji se dogodi nekoliko sati "kasnije" u tvojoj zoni može se riješiti kao Ne.</li>
<li><b>Točna formulacija.</b> "Najavi", "potpiše", "preuzme dužnost" i "bude potvrđen" različiti su događaji. Kopiraj
ključni glagol iz pravila i pitaj se: što ako se dogodi samo pola?</li>
<li><b>Izvor rješavanja.</b> Mnoga tržišta navode jedan izvor (službenu stranicu, određeni medij). Ako je taj izvor
spor, nejasan ili može promijeniti stranicu, to je tvoj rizik.</li>
<li><b>Rubni slučajevi u pravilima.</b> Potraži što se događa ako je događaj odgođen, otkazan ili nejasan. Ako pravila
šute, ishod ovisi o glasanju.</li>
<li><b>Pojašnjenja.</b> Polymarket ponekad doda pojašnjenja nakon otvaranja tržišta. Provjeri komentare i "additional
context" prije velike pozicije i ponovno prije datuma završetka.</li>
<li><b>Cijena "očite" strane.</b> Ako se očiti ishod trguje po 85 centi umjesto 99, netko u cijenu uključuje problem s
pravilima. Saznaj što vidi prije nego kupiš jeftinu sigurnost.</li>
</ol>

<h2>Kada preskočiti tržište</h2>
<p>Preskoči ga ako ishod ovisi o tumačenju nečijih riječi (mention tržišta), ako je izvor rješavanja nečiji profil na
društvenim mrežama ili ako su pravila promijenjena nakon otvaranja tržišta. To su tržišta na kojima su traderi
gubili novac iako su bili u pravu o svijetu.</p>
<p>Sljedeće: <a href=/hr/blog/polymarket-curenje-informacija>kako uočiti curenje informacija u Polymarket kvotama</a>.</p>
""")


# 4 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "polymarket-insider-moves", "polymarket-curenje-informacija", "Prediction marketi",
    "Kako uočiti curenje informacija na Polymarketu: kvote se pomaknu prije vijesti",
    "Insider trading na Polymarketu: kako uočiti kvote koje se mijenjaju prije vijesti | MemeSonar",
    "Kvote na Polymarketu više su puta skočile satima prije službene vijesti, od Nobelove nagrade za mir do "
    "Venezuele. Kako su ti pomaci izgledali i kako ih pratiti sam.", 6,
    "Curenje na prediction marketu izgleda kao nagli skok kvote za malo vjerojatan ishod bez javne vijesti, iza kojeg "
    "stoji jedan ili nekoliko novih računa s velikim ulozima. Možeš ga pratiti kroz karticu aktivnosti tržišta i "
    "blockchain explorer, ali to je signal za istraživanje, a ne razlog da slijepo pratiš.",
    f"""
<h2>Slučajevi zbog kojih je ovo tema</h2>
<p><b>Nobelova nagrada za mir, listopad 2025.</b> Kvota Maríje Corine Machado na Polymarketu porasla je s nekoliko
posto na više od 70% u satima prije objave u Oslu. Bloomberg i drugi povezali su velik dio kupnje s nekoliko računa,
među njima i jednim otvorenim taj mjesec bez ranijih oklada. Norveški dužnosnici pokrenuli su provjeru mogućeg
curenja.</p>
<p><b>Venezuela, siječanj 2026.</b> Tržišta o odlasku Nicolása Madura s vlasti pomaknula su se prije javne objave da
je u pritvoru SAD-a, a jedan račun navodno je zaradio nekoliko stotina tisuća dolara.</p>
<p>Trader Domer opisao je na X-u još slučajeva, uključujući tržište na kojem je cijena počela rasti oko 12 sati prije
vojnog napada, a analitičar Alex Krüger upozorio je na skok kvote za imenovanje šefa Feda dan prije objave.</p>

{B("Kvota da Machado osvoji Nobelovu nagradu za mir na Polymarketu", [
    ("Prije noćne kupnje", 3.6, "dan prije objave"),
    ("Sati prije objave", 70, "nakon što je nekoliko računa snažno kupovalo"),
], sub="Implicirana vjerojatnost, %", fmt="pct", hl=(1,), source="Bloomberg, The Block, Decrypt (listopad 2025.)")}

<h2>Kako curenje izgleda na ekranu</h2>
<ol>
<li><b>Malo vjerojatan ishod brzo raste bez vijesti.</b> Skok s jednoznamenkastog postotka na 30%+ u nekoliko sati,
dok portali i X nemaju ništa novo.</li>
<li><b>Kupnja dolazi od malo računa.</b> Otvori karticu aktivnosti ili "top holders" na tržištu. Curenja su obično
nekoliko velikih kupnji, a ne stotine malih.</li>
<li><b>Računi su novi ili imaju samo jednu svrhu.</b> Novčanik otvoren prije nekoliko dana koji se kladio samo na ovo
tržište klasičan je obrazac. Provjeri ga na Polygonscanu: kada je napunjen i odakle?</li>
<li><b>Vrijeme odgovara već donesenoj odluci.</b> Odbori za nagrade, sudske presude i vojne operacije odlučeni su
prije objave. U tom razmaku događaju se curenja.</li>
</ol>

<h2>Što s tim napraviti</h2>
<p>Ovakav pomak je informacija, ali ne i dokaz. Ponekad je "insajder" samo obožavatelj s velikim novčanikom, kao
korisnik Polymarketa koji je uporno kupovao ishod vezan uz slavnu osobu protiv svih izgleda. Prije nego što pratiš
pomak, pitaj se koja je odluka već donesena, tko bi mogao znati i koliko još možeš zaraditi ako kupiš po novoj
cijeni. Kupiti po 70 centi da zaradiš 30 posve je druga oklada od insajderovih 4 centa.</p>
<p>Isti signal koristan je i u drugom smjeru. MemeSonarov kalendar događaja čita Polymarket jer veliki novac koji se
pomiče na događaj često dolazi prije nego što se pokrenu tokeni nazvani po tom događaju. Nagli pomak kvote za događaj
iz kalendara razlog je da pogledaš te tokene, i <a href=/hr/blog/kako-prepoznati-rug-pull>njihov rizik od ruga</a>,
prije gomile.</p>
<p>Pročitaj i: <a href=/hr/blog/polymarket-pravila-provjera>kako pročitati pravila Polymarketa prije oklade</a>.</p>
""")


# 5 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "perps-settings-after-october-10", "postavke-za-perpse-10-listopada", "Trgovanje",
    "Metoda: 5 postavki za perpse koje bi te spasile 10. listopada",
    "Rizik kod perpsa: isolated margin, ADL i krah 10. listopada | MemeSonar",
    "10. listopada 2025. likvidirano je oko 19 milijardi dolara kripto pozicija u jednom danu. Pet postavki koje "
    "odlučuju hoće li ti takav krah uzeti trade ili cijeli račun.", 7,
    "Koristi isolated margin za svaki trade s polugom, postavi veličinu tako da je cijena likvidacije daleko iza "
    "svakog nedavnog fitilja, ne drži kolateral na burzi na kojoj trguješ, znaj da auto-deleveraging može zatvoriti i "
    "poziciju u plusu i ne otvaraj novu polugu nakon velikog gubitka. Tih pet pravila odlučilo je tko je preživio 10. 10. 2025.",
    f"""
<h2>Što se dogodilo 10. listopada</h2>
<p>Vijest o carinama pogodila je tržište puno poluge. Order bookovi su se istanjili, market makeri povukli
likvidnost, neki API-ji burzi prestali su raditi, a likvidacije su izazivale nove likvidacije. Većina praćenja
izbrojala je oko 19 milijardi dolara likvidiranih pozicija u otprilike jednom danu, najviše ikad, s više od milijun
pogođenih računa. Otprilike polovica dogodila se na Hyperliquidu.</p>

{B("Likvidacije 10. i 11. listopada 2025.", [
    ("Sve burze", 19.3, "najveći dan likvidacija ikad"),
    ("Hyperliquid", 10, "otprilike polovica ukupnog"),
    ("Binance", 2.4, "najveća centralizirana burza"),
], sub="Milijarde američkih dolara (procjene se razlikuju po izvoru i razdoblju)", fmt="num", hl=(0,),
   source="Kobeissi Letter, izvještaji temeljeni na CoinGlassu, Sentora")}

<p>Gubili su i iskusni traderi. The White Whale, poznati trader, objavio je javnu analizu nakon gubitka od oko 62
milijuna dolara tog dana. Unipcs je pisao o najvećem jednodnevnom gubitku u karijeri "zbog sistemskih kvarova na
najvećim burzama". Njihove objave i popis tradera Creda o tome što ne raditi nakon velikog pomaka temelj su ove liste.</p>

<h2>1. Uvijek isolated margin</h2>
<p>Kod cross margine cijeli račun pokriva svaku poziciju, pa jedan loš trade može isprazniti ostatak. Kod isolated
margine možeš izgubiti samo marginu koju si stavio u taj trade. 10. listopada računi na cross margini gubili su
pozicije koje nisu ni gledali.</p>

<h2>2. Cijena likvidacije iza najgoreg fitilja, ne iza grafa</h2>
<p>ETH je na nekim mjestima pao više od 1.000 dolara u nekoliko minuta. Prije otvaranja tradea pogledaj cijenu
likvidacije koju burza pokazuje i usporedi je s najvećim fitiljem u zadnjih godinu dana, a ne sa svojim stopom. Ako
bi te ponavljanje tog fitilja likvidiralo, smanji polugu dok ne bi.</p>

<h2>3. Znaj što je auto-deleveraging (ADL)</h2>
<p>Kad likvidirani račun padne ispod nule, a burza ga ne može zatvoriti na tržištu, zatvara pozicije na dobitničkoj
strani. Na Hyperliquidu se dobitnici rangiraju po (mark cijena / ulazna cijena) puta (veličina pozicije / vrijednost
računa), pa prve idu najprofitabilnije pozicije s najviše poluge, po prethodnoj mark cijeni. 10. listopada desecima
tisuća računa na Hyperliquidu, Binanceu i Bybitu tako su zatvorene profitabilne pozicije, među njima i hedgevi, pa je
druga noga ostala otvorena. Ako se štitiš perpsima, prati ADL pokazatelj na poziciji i u krahu uzmi profit na hedgu
umjesto da pretpostaviš da će ostati otvoren.</p>

<h2>4. Ne drži sav kolateral na burzi na kojoj trguješ</h2>
<p>Kad API-ji i povlačenja zastanu, ne možeš dodati marginu ni maknuti sredstva. Na burzi drži samo marginu koja ti
treba, a ostatak u svom novčaniku, da ti zamrznuta burza ne uzme sve.</p>

<h2>5. Nema nove poluge 24 sata nakon velikog gubitka</h2>
<p>Credov popis najgorih poriva nakon velikog pomaka: osvetnički short, prevelika kupnja i pokušaj da se sve vrati
isti dan. Unipcs je nakon kraha napisao isto: ugasi sve, odmakni se, ne otvaraj novu polugu. Zapiši pravilo prije
nego što ti zatreba.</p>
<p>Meme coini većinu života nemaju perpse, ali ista pravila vrijede za veličinu pozicije: pogledaj
<a href=/hr/blog/kako-trgovati-meme-coinima>kako trgovati meme coinima</a> i
<a href=/hr/blog/sto-je-dca>DCA</a>.</p>
""")


# 6 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "tokens-sent-to-kol-wallets", "tokeni-poslani-na-kol-novcanike", "Copy trading",
    "Zašto je nepoznati token sletio u novčanik poznatog tradera (i zašto ga copytraderi kupuju)",
    "Neželjeni tokeni u KOL novčanicima: trik koji vara copy tradere | MemeSonar",
    "Timovi tokena šalju svoje coine na novčanike poznatih tradera da izgleda kao kupnja. Copy trading botovi i "
    "pratitelji onda kupe stvarno. Kako u 30 sekundi razlikovati poklon od kupnje.", 5,
    "Mnoge tokene u novčanicima poznatih tradera nitko nije kupio: tim tokena ih je poslao besplatno da izgleda kao da "
    "je trader ušao. Copy trading botovi i pratitelji vide novi token i kupe ga stvarno. Prije kopiranja provjeri je "
    "li SOL izašao iz novčanika u istoj transakciji; običan dolazni prijenos tokena je poklon, a ne kupnja.",
    f"""
<h2>Trik</h2>
<p>Solana trader Unipcs, jedan od najkopiranijih novčanika na trading aplikaciji Fomo, napisao je da oko 90% tokena
koji stignu u njihov javni novčanik šalju drugi ljudi, a ne kupuje sam. Prema njegovim riječima, ljudi ih šalju "da
iskoriste moje copytradere i/ili dojam da je 'Unipcs ovo kupio'". Neki od tih poklona bili su dobri tokeni, ali
velika većina došla je "od ljudi s lošim namjerama".</p>

{B("Odakle su tokeni u novčaniku jednog poznatog tradera", [
    ("Drugi su ih poslali besplatno", 90, "procjena samog tradera"),
    ("Trader ih je kupio", 10, ""),
], sub="Udio primljenih tokena, %", fmt="pct", hl=(0,), source="Unipcs na X-u (procjena za njihov javni Fomo novčanik)")}

<p>Postupak je jeftin. Tim pošalje mali dio ponude na nekoliko poznatih novčanika. Pregledi portfelja i liste "što
drži smart money" pokažu token. Copy trading botovi koji prate stanje, a ne swapove, kupe ga, pratitelji vide ime u
novčaniku i kupe i oni, a tim prodaje u tu potražnju.</p>

<h2>Kako provjeriti u 30 sekundi</h2>
<ol>
<li><b>Otvori novčanik na Solscanu i nađi prvu transakciju s tim tokenom.</b></li>
<li><b>Pogledaj što je izašlo iz novčanika u istoj transakciji.</b> Prava kupnja je swap: izađe SOL ili USDC, uđe
token, obično preko Jupitera, Raydiuma, pump.funa ili drugog DEX-a. Poklon je običan "transfer" u kojem samo token
ulazi.</li>
<li><b>Provjeri tko ga je poslao.</b> Ako je pošiljatelj kreator tokena ili novčanik koji je kreator napunio, to je
marketing, a ne uvjerenje.</li>
<li><b>Provjeri je li poznati novčanik ikad prodao.</b> Mnogi poklonjene tokene jednostavno nikad ne diraju, pa "još
drži" ne znači ništa.</li>
</ol>

<h2>Što to znači za copy trading</h2>
<p>Copy trading treba pratiti <b>swapove koje je novčanik platio</b>, nikad promjene stanja. Tako MemeSonarov
<a href=/hr/blog/sto-je-pracenje-novcanika>wallet tracker</a> broji tradeove: pozicija postoji samo ako je SOL za
nju izašao iz novčanika. Poklonjeni tokeni nikad ne ulaze u ocjenu pa ne mogu pokrenuti kopiranje. Ako koristiš drugi
bot, potraži u postavkama "copy transfers" ili "copy on balance change" i isključi to.</p>
<p>Provjeri i sam token prije kupnje bilo čega što si vidio u nečijem novčaniku:
<a href=/hr/blog/bundleri-i-snajperi>tko stvarno drži ponudu</a> i
<a href=/hr/blog/kako-prepoznati-rug-pull>7 provjera za rug</a>.</p>
""")


# 7 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "what-to-do-with-an-airdrop", "sto-napraviti-s-airdropom", "Airdropovi",
    "Metoda: što napraviti s airdropom u prvih 24 sata (prodati, držati ili hedgati)",
    "Prodati ili držati airdrop? Što podaci kažu o prvih 24 sata | MemeSonar",
    "Većina airdrop tokena za nekoliko mjeseci trguje ispod početne cijene, a većina primatelja proda prvi dan. "
    "Jednostavno pravilo za prvih 24 sata i kako prepoznati lažnu stranicu za claim.", 6,
    "Studije lansiranja tokena u 2025. pokazale su da je oko 85% tokena završilo ispod početne cijene i da je većina "
    "airdrop novčanika prodala u 90 dana. Ako nemaš konkretan razlog za držanje, prvi dan prodaj barem dio za kojim bi "
    "žalio da ga izgubiš i claimaj samo preko linka koji si sam našao na službenim kanalima projekta.",
    f"""
<h2>Što se dogodilo s airdropovima u 2025.</h2>
{B("Airdropovi i lansiranja tokena u 2025.", [
    ("Tokeni ispod početne cijene (Arrakis, 125 lansiranja)", 85, "mjereno krajem 2025."),
    ("Tokeni ispod TGE vrijednosti (Memento, 118 lansiranja)", 84.7, ""),
    ("Airdrop novčanici koji su prodali u 90 dana (Delphi, gornja granica)", 94, "donja granica raspona: 78%"),
    ("Primatelji koji su prodali prvi dan (Arrakis, gornja granica)", 80, ""),
    ("ZKsync primatelji koji su sve prodali prvi dan (Nansen)", 41, ""),
], sub="% (svaka brojka iz navedene studije)", fmt="pct", hl=(0,),
   source="Arrakis, Memento Research, Delphi Digital, Nansen, prema The Defiantu i BeInCryptu")}
<p>Istraživačica airdropova Stacy Muur sažela je godinu na X-u: odmah prodati airdrop bila je najbolja strategija,
shortanje je radilo, ali likvidacije su bile česte i uz malu polugu, a svi grindaju, uključujući timove i VC-jeve.
DeFi Ignas opisao je isti postupak: prvo claimaj i prodaj, kasnije kupi natrag kad prestane prodaja od airdropa.</p>

<h2>Pravilo za prvih 24 sata</h2>
<ol>
<li><b>Odluči prije otvaranja claima.</b> Zapiši koliko prodaješ pri claimu i zašto bi držao ostatak. "Sviđa mi se
projekt" nije razlog; "koristim ga svaki dan i tim ima razlog održavati cijenu" može biti.</li>
<li><b>Prvi dan prodaj barem "iznos za kojim bi žalio".</b> Iznos za kojim bi ti bilo žao da padne 80%. Za većinu
ljudi to je pola ili više.</li>
<li><b>Provjeri raspored otključavanja.</b> Ako se tokeni tima i investitora otključavaju za 30 do 90 dana, dolazi
pritisak prodaje. Haseeb Qureshi (Dragonfly) zagovara da airdropovi nagrađuju one koji drže, i neki projekti to sada
rade (Espresso je koristio "holder score"), ali većina još ne.</li>
<li><b>Hedganje je samo za iskusne tradere.</b> Short svježeg tokena na perp burzi može zaključati cijenu, ali nova
tržišta su tanka i lako skaču. Ako to radiš, koristi isolated margin i malu polugu, kao u
<a href=/hr/blog/postavke-za-perpse-10-listopada>ovim postavkama za perpse</a>.</li>
<li><b>Gledaj prve sate, ne prvu minutu.</b> Cijene često divlje skaču dok se likvidnost ne smiri. Prodaja u dva ili
tri dijela tijekom prvog dana sprječava prodaju točno na dnu.</li>
</ol>

<h2>Ne izgubi ga na stranici za claim</h2>
<p>Dan velikog airdropa najbolji je dan u godini za drainere. Lažni claim tokeni šalju se na novčanike (npr. lažni
"$CJUP" tokeni koji glume Jupiterov airdrop), a lažne stranice reklamiraju se u odgovorima i oglasima na tražilici.
Claimaj samo preko linka sa službene stranice ili verificiranog X računa projekta, koji si sam upisao ili spremio, i
čitaj što potpisuješ: claim nikad ne bi smio tražiti odobrenje za trošenje tvojih drugih tokena.</p>
<p>Povezano: <a href=/hr/blog/address-poisoning-provjera-adrese>address poisoning</a> i
<a href=/hr/blog/lazna-podrska-ledger-prevara>prevare s lažnom podrškom</a>.</p>
""")


# 8 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "fake-volume-check", "lazni-volumen-provjera", "Rug pull",
    "Kako provjeriti je li volumen trgovanja lažan (na DEX-u ili burzi)",
    "Lažni kripto volumen: kako prepoznati wash trading u 3 provjere | MemeSonar",
    "Visok volumen čini token živim, a velik dio je lažan. Tri provjere koje svatko može napraviti: volumen prema "
    "likvidnosti, volumen koji kopira drugu burzu i zidovi koji trepere.", 6,
    "Wash trading napuhuje volumen da token izgleda popularno. Usporedi 24-satni volumen s likvidnošću (desetke puta "
    "više volumena od likvidnosti je crvena zastavica), provjeri preslikava li volumen samo drugu burzu i pazi na "
    "velike naloge koji se pojavljuju i nestaju. Nijedno samo po sebi nije dokaz; dva zajedno obično jesu.",
    f"""
<h2>Koliko je to često</h2>
<p>Wash trading znači trgovati sam sa sobom (ili s prijateljskim novčanikom) da se stvori volumen. Na DEX-ovima je
jeftin i radi: trending liste, screeneri i botovi rangiraju po volumenu. Istraživanja ga stalno nalaze puno.</p>
{B("Wash trading u istraživanjima", [
    ("DEX poolovi kojima manipuliraju wash traderi (Solidus Labs)", 67, "uzorak od oko 30.000 poolova"),
    ("Lažni volumen na nereguliranim burzama (Cong i sur.)", 70, "gornja procjena"),
    ("Udio wash tradinga u volumenu tih poolova (Solidus)", 16, "donja granica"),
], sub="%", fmt="pct", hl=(0,), source="Solidus Labs; Cong i sur., citirano u Victor i Weintraud (2021.)")}

<h2>Provjera 1: volumen prema likvidnosti</h2>
<p>Na DexScreeneru ili Birdeyeu podijeli 24-satni volumen s likvidnošću poola. Stvarno trgovanje rijetko dugo obrće
pool desetke puta dnevno; podatkovna tvrtka Kaiko označava imovinu s volumenom većim od 100 puta dubine order booka
kao mogući znak wash tradinga. Memeovi i mali tokeni prirodno su vrući, pa to koristi kao filter: vrlo visok omjer i
malo različitih tradera je obrazac.</p>
<p>MemeSonar koristi ovu provjeru u ocjeni tokena: token čiji je volumen višestruko veći od likvidnosti dobiva kaznu,
pa ne ispada "vruć" samo zato što ga bot trguje naprijed-natrag.</p>

<h2>Provjera 2: volumen koji kopira drugu burzu</h2>
<p>0xngmi iz DefiLlame pokazao je da je volumen na jednoj perp burzi počeo gotovo točno preslikavati Binanceov perp
volumen, s omjerom blizu 1, dok druge burze nisu izgledale ni slično. Stvarni korisnici ne trguju savršeno usklađeno
s drugim mjestom. Usporedi satni graf volumena para na dvije burze; ako je jedan gotovo kopija drugoga, vjerojatno se
farma, često zbog bodova ili listinga.</p>

<h2>Provjera 3: zidovi koji trepere (spoofing)</h2>
<p>Na centraliziranim burzama gledaj order book. Trader The White Whale opisao je prodajni nalog od oko 200.000
dolara na Bybitu koji se stalno pojavljivao i nestajao, klasičan znak spoofinga: nalog postavljen da uplaši kupce i
povučen prije nego se može izvršiti. Veliki zidovi koji se odmiču kako se cijena približava nisu stvarna ponuda.</p>

<h2>Brzi znakovi na lancu</h2>
<ul>
<li><b>Malo novčanika, puno tradeova.</b> Stotine tradeova s desetak novčanika.</li>
<li><b>Uravnotežene kupnje i prodaje.</b> Isti novčanici kupuju i prodaju gotovo isti iznos; istraživanja označavaju
razliku manju od 5% između povezanih novčanika.</li>
<li><b>Kružno financiranje.</b> Trading novčanici napunjeni iz istog izvora, često od deployera.</li>
</ul>
<p>Više o čitanju tokena prije kupnje: <a href=/hr/blog/market-cap-likvidnost-slippage>market cap, likvidnost i
slippage</a> i <a href=/hr/blog/sto-je-pump-and-dump>pump and dump</a>.</p>
""")


# 9 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "after-kaito-yaps", "nakon-kaito-yapsa", "Za kripto projekte",
    "Metoda: Kaito Yaps je ugašen, kako kripto projekt sada dobiva vidljivost na X-u",
    "Nakon Kaito Yapsa: kako kripto projekti dobivaju vidljivost na X-u u 2026. | MemeSonar",
    "X je u siječnju 2026. odrezao aplikacije koje plaćaju objavljivanje, a Kaito je ugasio Yaps. Što nije valjalo s "
    "plaćenim mindshareom i checklista za svaku plaćenu kampanju na X-u.", 6,
    "U siječnju 2026. X je ukinuo API pristup aplikacijama koje nagrađuju objavljivanje, a Kaito je ugasio Yaps i "
    "ljestvice s nagradama. Pouka za projekte: plaćeni mindshare donio je interakcije bez stvarnog dosega. Mjeri "
    "impresije po interakciji, plati nekoliko kreatora za definiran posao umjesto svih za volumen i označi to.",
    f"""
<h2>Što se dogodilo</h2>
<p>Kaitov Yaps plaćao je kripto račune u "mindshareu" za objave o projektima na ljestvicama. Projekti su plaćali da
budu na tim ljestvicama. 16. siječnja 2026., nakon što je X ograničio aplikacije koje nagrađuju objavljivanje (zbog
spama i niske kvalitete angažmana), osnivač Kaita Yu Hu najavio je gašenje Yapsa i ljestvica s nagradama i prelazak na
Kaito Studio, kurirano tržište na kojem brendovi rade s odabranim kreatorima. Cookie DAO ugasio je sličan program
"Snaps". KAITO token pao je oko 15% na tu vijest.</p>

{B("Cijena KAITO tokena oko objave", [
    ("Prije", 0.70, ""),
    ("Poslije", 0.57, "oko -15%"),
], sub="Američki dolari", fmt="usd2", hl=(1,), source="CoinGape, siječanj 2026.")}

<h2>Što nije valjalo s plaćenim mindshareom</h2>
<ul>
<li><b>Interakcije bez dosega.</b> Kripto autor Olimpio primijetio je da je njegova objava o airdropu dobila desetke
interakcija, ali malo impresija, i otkrio da token ima aktivnu InfoFi kampanju: računi su reagirali da skupe nagrade,
a ne zato što je itko čitao.</li>
<li><b>Grind je zamijenio vrijednost.</b> Stacy Muur napisala je da je KOL-ovi stalno mole da reagira na njihove
objave za ljestvice i da se pretjeranim grindom gubi stvarna vrijednost. Čak su i vodiči za pobjedu na ljestvicama
preporučivali 50 do 300 odgovora dnevno.</li>
<li><b>Cijena povjerenja.</b> The White Whale nazvao je kulturu plaćenih KOL-ova "apsolutnim rakom": plaćanje za
proizvedeni konsenzus umjesto zarađene pažnje. Publika je to naučila ignorirati.</li>
</ul>

<h2>Checklista za svaku plaćenu kampanju na X-u</h2>
<ol>
<li><b>Mjeri impresije po interakciji.</b> Traži od kreatora screenshot analitike objave. Okvirno pravilo: objave
koje ljudi stvarno čitaju imaju desetke ili stotine impresija po interakciji; deset ili manje upućuje na prstene
angažmana, a ne čitatelje.</li>
<li><b>Provjeri tko odgovara.</b> Otvori odgovore na zadnje tri plaćene objave kreatora. Generičke pohvale od računa
koji odgovaraju na svaku kampanju su farmanje.</li>
<li><b>Plati definiran posao, ne volumen.</b> Jedan thread koji objašnjava kako proizvod radi, video demo ili objava s
podacima. Kaito Studio prešao je na isti model: odabrani kreatori, definiran opseg.</li>
<li><b>Biraj nekoliko kreatora koje tvoji korisnici već čitaju.</b> Pitaj postojeće korisnike koga prate. Tri takva
vrijede više od trideset računa s ljestvica.</li>
<li><b>Označi suradnju.</b> Plaćene objave trebaju to reći. To štiti kreatora i projekt, a neoznačena promocija je
upravo ono što publika danas kažnjava.</li>
<li><b>Prati što je važno nakon objave.</b> Nove novčanike koji koriste proizvod, ne lajkove. Stavi jedinstveni link
ili kod u objavu svakog kreatora.</li>
</ol>
<p>Kako pozivi influencera pomiču tokene, izmjereno: <a href=/hr/blog/sto-je-kol-u-kriptu>što je KOL</a> i
<a href=/hr/blog/zasto-je-tesko-trgovati-pozive-velikih-influencera>zašto je teško trgovati velike pozive</a>.</p>
""")


# 10 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "fair-token-launch-cca", "fer-lansiranje-tokena-cca", "Za kripto projekte",
    "Metoda: kako lansirati token bez snajpera, Uniswap CCA aukcija korak po korak",
    "Fer lansiranje tokena bez snajpera: vodič za Uniswap CCA aukciju | MemeSonar",
    "Continuous Clearing Auction prodaje tokene blok po blok po jednoj cijeni, pa snajperi i bundleri gube prednost. "
    "Kako je postaviti i kako licitirati kao kupac.", 7,
    "Uniswapova Continuous Clearing Auction (CCA) raspoređuje prodaju tokena na mnogo blokova. Svaka ponuda dijeli se "
    "na preostale blokove i izvršava po cijeni tog bloka, pa biti prvi ne donosi prednost. Osnivači postavljaju "
    "količinu, minimalnu cijenu, trajanje i dio za pool; kupci trebaju licitirati rano po svojoj stvarnoj najvišoj cijeni.",
    f"""
<h2>Problem koji rješava</h2>
<p>Kod klasičnog lansiranja najbrži dobiva najjeftinije tokene. Zato <a href=/hr/blog/bundleri-i-snajperi>bundleri i
snajperi</a> u nekoliko sekundi drže velik dio nove ponude i zato on-chain istražitelji poput Bubblemapsa stalno
nalaze insajdere u "predsjedničkim" i celebrity coinima. Tim gubi kontrolu nad time tko drži token, a kupci plaćaju
izlaz snajperima.</p>

<h2>Kako CCA radi</h2>
<p>Tim stavi dio ponude u aukciju koja traje određeno razdoblje. Kupac upiše budžet i najvišu cijenu. Ponuda se
ravnomjerno raspoređuje na sve preostale blokove. U svakom bloku aukcija iz svih aktivnih ponuda nađe jednu cijenu i
svaka ponuda na toj cijeni ili iznad nje izvršava se po toj istoj cijeni. Cijena može samo rasti kako dolazi
potražnja. Na kraju, ako aukcija dosegne minimalni iznos, završna cijena postaje početna cijena Uniswap v4 poola
napunjenog dijelom prikupljenog novca.</p>

<h2>Prvi veliki test: Aztec</h2>
{B("Aztecova CCA prodaja tokena", [
    ("Završna cijena iznad minimalne", 60, "Hayden Adams naveo je 59%"),
    ("Licitanti koji su uložili manje od 10.000 dolara", 96, "oko 17.000 licitanata iz 191 zemlje"),
], sub="%", fmt="pct", hl=(1,), source="blog Uniswap Labsa, veljača 2026.")}
{stats([("59 mil. $", "ukupne ponude u Aztecovoj aukciji"), ("~17.000", "licitanata"), ("0", "jasnih slučajeva snajpanja na lancu, prema Uniswapu")])}
<p>Osnivač Uniswapa Hayden Adams sažeo je to kao "bez snajpanja, bundlanja i igara s vremenom, samo sporo i fer
otkrivanje cijene" i naglasio da ni ponuda po ogromnoj vrijednosti prvog dana ne bi preplatila, jer se izvršava po
završnoj cijeni. Brojke dolaze iz Uniswapovih izvještaja, pa ih čitaj kao pogled organizatora.</p>

<h2>Postavljanje (za osnivače)</h2>
<ol>
<li><b>Količina u aukciji.</b> Odluči koji udio ukupne ponude ide javnosti. Premalo izgleda pohlepno; više nego što
treba ne ostavlja mjesta za poticaje.</li>
<li><b>Minimalna cijena.</b> Najniža cijena po tokenu. Uniswapova dokumentacija upozorava da previsoka minimalna
cijena može srušiti aukciju i izgubiti sredstva, pa je postavi na vrijednost koju bi prihvatio kao najgori slučaj.</li>
<li><b>Trajanje i krivulja.</b> Dani, ne minute. Prilagođenom krivuljom možeš rano prodavati manje tokena, a kasnije
više.</li>
<li><b>Rano razdoblje ponuda.</b> Neobavezan prozor za dosadašnje suradnike ili zajednicu prije javne aukcije (Aztec
ga je imao).</li>
<li><b>Dio za pool i LP postavke.</b> Dio prikupljenog novca i tokena koji puni Uniswap v4 pool po završnoj cijeni,
da trgovanje počne sa stvarnom likvidnošću.</li>
<li><b>Provjera.</b> Neobavezne provjere poput dokaza osobnosti (zkPassport) da se ograniče sybil licitanti.</li>
</ol>

<h2>Licitiranje (za kupce)</h2>
<p>Licitiraj rano po najvišoj cijeni koju bi stvarno platio. Čekanje ti ne donosi bolju cijenu: budžet se raspoređuje
na manje blokova, a cijena samo raste kako drugi licitiraju. Ponuda po stvarnom maksimumu samo znači da se izvršavaš
u više blokova, uvijek po završnoj cijeni bloka, nikad po svom maksimumu.</p>
<p>Povezano: <a href=/hr/blog/sto-je-pump-fun>kako rade pump.fun lansiranja</a> i
<a href=/hr/blog/nakon-kaito-yapsa>marketing na X-u nakon Kaito Yapsa</a>.</p>
""")
