"""Hrvatske verzije četiri istraživačka posta od 23. 11. 2026. (ui/blogposts_nov23.py). Iste brojke, isti izvori.
Sve brojke su MemeSonarova vlastita mjerenja od 23. 11. 2026.: statistika, ne optužbe, nikad adresa novčanika."""
from ui import blogsources as S
from ui.blogposts_hr import post
from ui.blogviz import bars, stats

SRC = "MemeSonarova vlastita mjerenja, 23. 11. 2026."
RISK = ("<p class=note><b>Upozorenje o riziku.</b> Meme coini su izuzetno rizični i većina završi na nuli. Ništa ovdje "
        "nije preporuka za kupnju, prodaju ili kopiranje bilo koga; brojke opisuju prošlost i tako se i čitaju.</p>")
METHOD = "<a href=/hr/blog/kako-memesonar-mjeri>kako MemeSonar mjeri</a>"


def B(*a, **k):
    return bars(*a, lang="hr", **k)


# a ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "wallets-that-buy-before-a-solana-token-jumps", "novcanici-koji-kupuju-prije-skoka-solana-tokena", "Novčanici",
    "Novčanici koji kupuju prije skoka Solana tokena: što pokazuje 345 pumpi",
    "Novčanici koji kupuju prije skoka Solana tokena: 345 pumpi",
    "Pročitali smo 345 Solana pumpi do kraja: 47.752 rana kupca, 8.273 prodalo je u pumpu, 257 grupa koje se "
    "ponavljaju. Tko su u statistici, kako se grupe potvrđuju i granice.", 8,
    "Rani novčanici postoje, ali nisu jedan klub. U 345 Solana pumpi kroz 180 dana našli smo 47.752 novčanika koji su "
    "kupili prije skoka; otprilike svaki šesti (8.273) prodao je u skok. Samo 257 grupa novčanika bilo je rano u tri "
    "ili više pumpi, a 90 tih grupa potvrđeno je na kasnijim danima. Biti rano lako se vidi naknadno, a teško se od "
    "toga zarađuje: kopiranje je zaseban test i nije ga prošlo.",
    f"""
<h2>Pitanje</h2>
<p>Svaki Solana token koji skoči ostavlja javni trag: novčanike koji su kupili prije skoka i često prodali u njega.
"Nađi te novčanike i prati ih" najčešći je savjet u trgovanju meme coinima i ideja iza svakog
<a href=/hr/najbolji-kripto-alati/pracenje-novcanika>alata za praćenje novčanika</a>. Htjeli smo znati koliko takvih
novčanika stvarno ima, koliko ih se ponavlja i je li ponavljanje stvarno ili samo sreća. Ovaj tekst je popis;
tekst <a href=/hr/blog/isplati-li-se-kopirati-pametne-novcanike>isplati li se kopirati pametne novčanike nakon
stvarnih troškova</a> je test novca.</p>

<h2>Što smo pročitali</h2>
<p>Alat traži pumpe na tokenima od otprilike 2 milijuna $ tržišne vrijednosti naviše, s prednošću za pumpe koje dođu
do 15-200 milijuna $. Za svaku pumpu čita kupce prije skoka do kraja, ne samo prvu stranicu koju pokaže explorer. Na
Solani je to moguće jer je svaki swap javan i može se {S.a("helius_etx", "pretvoriti u čitljive kupnje, prodaje i prijenose")}. U 180 dana povijesti to je dalo:</p>
{stats([("345", "pumpi pročitanih do kraja"), ("47.752", "rana kupca"), ("8.273", "prodalo je u pumpu")])}
{B("345 pumpi po tržišnoj vrijednosti tokena", [
    ("15 M $ i više", 96, "raspon u kojem bi MemeSonar razmatrao ulaze pravim novcem"),
    ("2 M $ do 15 M $", 249, "samo demo"),
], sub="Broj pumpi, 180 dana povijesti", fmt="num", hl=(0,), source=SRC)}
<p>Većina pumpi događa se na manjim tokenima, gdje kopirana kupnja više pomakne cijenu i više košta. Imaj to na umu
kad vidiš screenshot "ovaj novčanik je pogodio 40 runnera".</p>

<h2>Tko su, u statistici</h2>
<p>"Rani kupac" ovdje je svaki novčanik koji je kupio prije skoka. Većina nije napravila ništa posebno: kupili su,
cijena je kasnije narasla, a mnogi nikad nisu prodali na vrhu. Samo 8.273 od 47.752, otprilike svaki šesti, prodao
je u pumpu. To je skupina na koju ljudi misle kad kažu <a href=/hr/rjecnik/smart-money>smart money</a>, a i u njoj se
većina novčanika pojavi jednom i nikad više.</p>
<p>Da bismo našli vještinu, a ne sreću, tražimo ponavljanja i brojimo <a href=/hr/rjecnik/klaster>grupe
novčanika</a>, a ne pojedine adrese: nekoliko novčanika financiranih iz istog izvora ili koji uvijek kupuju u istom
trenutku jedan su igrač, ne deset. Brojati ih kao deset upravo je način na koji tim glumi "puno neovisnih kupaca".</p>
{B("Koliko je često ista grupa bila rano", [
    ("Rano u 3+ pumpe", 257, "obrazac vrijedan testiranja"),
    ("...od toga potvrđeno na kasnijim danima", 90, "obrazac je izdržao na pumpama koje odabir nije vidio"),
    ("Blizu: rano u 2 pumpe", 297, "pratimo, još nije obrazac"),
], sub="Grupe novčanika, 345 pumpi", fmt="num", hl=(1,), source=SRC)}
<p>"Potvrđeno" znači da je grupa odabrana samo iz ranijih pumpi i zatim se opet pojavila rano u pumpama koje su došle
kasnije. Grupa koja je rano u tri pumpe istog tjedna može biti jedan sretan tjedan; grupa koja se nastavi pojavljivati
nakon odabira bolji je kandidat. Tu je granicu prešlo 90 grupa.</p>

<h2>Tko su te grupe vjerojatno</h2>
<p>Objavljujemo statistiku, ne optužbe, i nikad ne objavljujemo adrese novčanika. Ipak, oblici su poznati. Neke
grupe kupuju u bloku lansiranja, što se na Solani često radi
{S.a("jito_bundles", "Jito bundleovima: do pet transakcija koje se izvrše redom ili nijedna")}; to je obrazac
<a href=/hr/blog/bundleri-i-snajperi>bundlera i snajpera</a>. Neke su timovi koji sami lansiraju tokene: istraživanje
na Ethereumu i BNB Chainu pokazalo je da {S.a("arxiv_1day", "1 % adresa stvara 20-25 % svih tokena")}. Neke su
jednostavno brzi traderi. Nedavna studija 200.443 pump.fun lansiranja našla je koordinirane grupe koje su
{S.a("arxiv_earlybuyers", "kupovale ranije i izvukle više novca od usporedivih novčanika, dok su kasni kupci gubili")}. Naše brojke idu u istom smjeru.</p>

<h2>Biti rano nije isto što i biti vrijedan praćenja</h2>
<p>Grupa može stvarno biti rana i ipak ti biti beskorisna. Ako kupuje u prvom bloku, ne možeš biti raniji. Ako prodaje
u skok za nekoliko minuta, kupuješ ono što ona prodaje. A ako je dio kupnje kupnja samog tima, ti si izlaz. Zato je
popis samo pola posla. U testu kopiranja kopiranje tih novčanika 60 sekundi nakon njih u prosjeku je izgledalo
pozitivno, ali nije dokazano, a brza kopija za 2 sekunde gubila je uz realnih 1 % slippagea. Ista studija pump.fun
grupa pokazala je da je onaj tko ulazi na prvi signal grupe izvan uzorka gubio u sve 32 isprobane postavke. Detalji:
<a href=/hr/blog/isplati-li-se-kopirati-pametne-novcanike>test kopiranja</a>.</p>
<p>Od 19. studenoga demo račun prati takve novčanike bez pravog novca. Nakon stvarnih troškova praćenje novčanika
prije pumpe na tokenima od 15-200 milijuna $ ima 23 tradea i prosjek −7,5 %; širi popis kandidata ima 43 tradea i
+16,3 %, ali taj prosjek nosi nekoliko tradeova, pa još malo govori.</p>

<h2>Granice</h2>
<ul>
<li><b>Preživjeli.</b> Krećemo od tokena koji su skočili. Novčanici koji su rano kupili tokene koji nikad nisu skočili
nisu u ovom popisu, pa rana kupnja izgleda bolje nego što jest.</li>
<li><b>Grupe su zaključene.</b> Zajednički izvor novca i isto vrijeme jaki su tragovi, ali ne i dokaz da novčanike drži
jedna osoba. Neke grupe bit će krive, u oba smjera.</li>
<li><b>180 dana.</b> Obrasci u meme coinima brzo se mijenjaju; grupa potvrđena u listopadu može stati u prosincu.</li>
<li><b>Vlastita mjerenja.</b> Ovo su brojke samog alata od 23. studenoga 2026.; pravila objašnjavamo u tekstu
{METHOD}.</li>
</ul>

<h2>Što s tim napraviti</h2>
<p>Ako pratiš novčanike, prati grupe i broji ponavljanja na danima nakon što si ih odabrao, kako je opisano u tekstu
<a href=/hr/blog/sto-je-pracenje-novcanika>što je praćenje novčanika</a>. Provjeri je li "kupnja" novčanika bila kupnja,
a ne <a href=/hr/blog/tokeni-poslani-na-kol-novcanike>token koji mu je netko poslao besplatno</a>. I svaki popis
novčanika, uključujući naš, smatraj popisom kandidata za testiranje, ne popisom tradeova za kopiranje.</p>
{RISK}
""")

# b ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "does-copying-smart-wallets-pay", "isplati-li-se-kopirati-pametne-novcanike", "Copy trading",
    "Isplati li se kopirati pametne novčanike nakon stvarnih troškova? Naš test",
    "Isplati li se kopirati pametne novčanike? Naš test",
    "Kopirali smo Solana novčanike prije pumpe na povijesti, uz kašnjenje, trošak i promašene kupnje: +29,7 % na 60 s, "
    "ali interval od -12,9 % do +114,3 %. Nije dokazano.", 8,
    "Nije dokazano. Kopiranje novčanika prije pumpe 60 sekundi nakon njihove kupnje na povijesti je u prosjeku donijelo "
    "+29,7 % po kopiji, ali interval od 95 % ide od −12,9 % do +114,3 % na 1.219 kopija, a 34,8 % njihovih kupnji nije "
    "se moglo kopirati. Brza kopija za 2 sekunde u prosjeku je gubila −7,6 % uz pretpostavljenih 1 % slippagea. "
    "MemeSonarova presuda: nije dovoljno dobro za pravi novac.",
    f"""
<h2>Tvrdnja koju smo testirali</h2>
<p>"Kopiraj novčanike koji kupuju prije pumpe" zvuči kao besplatan novac:
<a href=/hr/blog/novcanici-koji-kupuju-prije-skoka-solana-tokena>novčanici postoje</a>, tradeovi su im javni, a copy
botovi ih ponove u sekundi. Pitanje je zadržiš li ti, koji dolaziš nakon njih i plaćaš svoje troškove, išta od njihove
prednosti. Pošten test mora kopirati onako kako bi kopirao stvaran sljedbenik. Naš radi četiri stvari koje većina
backtestova preskoči.</p>
<ol>
<li><b>Odabir samo iz prošlosti.</b> Novčanik se bira iz pumpi prije dana kopiranja. Odabrati novčanike na cijeloj
povijesti pa ih "kopirati" na istoj povijesti znači gledati u budućnost.</li>
<li><b>Kašnjenje.</b> Vidiš njihovu kupnju, pa kupiš. Testiramo 60 sekundi i 2 sekunde.</li>
<li><b>Stvarni trošak.</b> Trošak trgovanja oduzima se od svake kopije; na meme coinima nikad ne računamo ukupni
trošak ispod 3 %.</li>
<li><b>Promašene kupnje se broje.</b> Kupnja koja se nije mogla kopirati ostaje u brojanju kao promašena, umjesto da
tiho nestane.</li>
</ol>
<p>Sva pravila su u tekstu {METHOD}.</p>

<h2>Rezultat</h2>
{B("Kopiranje novčanika prije pumpe na povijesti: prosjek po kopiji", [
    ("Kopija 60 s nakon njih", 29.7, "interval 95%: -12,9 % do +114,3 %, n = 1.219, promašeno 34,8 % kupnji"),
    ("Nasumični rani kupci (kontrola)", 2.7, "interval -22,4 % do +45,0 %, n = 49"),
    ("Ulaz kad token već ima 15 M $+", -3.3, "interval -7,3 % do +1,6 %, n = 41"),
    ("Brza kopija, 2 s, pretpostavljen slippage 1%", -7.6, "interval -9,3 % do -5,7 %, n = 1.202"),
], sub="Prosjek u % po kopiranoj kupnji nakon stvarnih troškova; prijeđi preko trake za interval", fmt="pct", hl=(0,),
    source=SRC, vmax=30)}
<p>Negativne vrijednosti nacrtane su najmanjom širinom; čitaj brojke, ne duljinu traka.</p>

<h2>Zašto +29,7 % nije dokaz</h2>
<p>Prosjek je jedan broj; interval govori koliko smo u njega sigurni. Interval od 95 % raspon je u kojem stvarni
prosjek vjerojatno leži, s obzirom na to koliko se pojedini rezultati rasipaju
({S.a("nist_ci", "NIST: što je interval uži, procjena je preciznija")}). Ovdje raspon ide od gubitka od 12,9 % do
dobitka od 114,3 %. Ta širina dolazi od samih prinosa meme coina: većina kopija izgubi malo ili puno, a nekoliko
golemih dobitnika digne prosjek. Makni ih par i prosjek može otići u minus. Kad interval uključuje nulu, pošteno
čitanje je "ovo ne možemo razlikovati od nikakve prednosti".</p>
<p>Dvije stvari to dodatno slabe. Trećina kupnji (34,8 %) nije se uopće mogla kopirati, a u stvarnosti su to često
najbolje, jer je cijena pobjegla prije nego što ju je itko mogao pratiti. A nasumična kontrola, rani kupci odabrani
bez ikakvog filtra vještine, također ima pozitivan prosjek (+2,7 %) uz interval od −22,4 % do +45 %: biti rano na
tokenu koji je kasnije skočio izgleda dobro naknadno, tko god bio.</p>

<h2>Brzina to ne popravlja</h2>
<p>Intuitivno rješenje je kopirati brže. Kopija za 2 sekunde najprecizniji je rezultat u testu (1.202 kopije, interval
od −9,3 % do −5,7 % ne dotiče nulu) i jasno je negativan. Kad isti novčanik kopira puno botova, natječu se za isti
blok; oni koji plate višu {S.a("helius_pf", "prioritetnu naknadu po compute jedinici")} idu prvi, a ostali kupuju
skuplje. Pretpostavljenih 1 % slippagea dovoljno je da kopija postane stalan gubitak. Ulaz samo na većim tokenima (od
15 milijuna $) jeftiniji je za izvršenje, ali nije ostavio ništa: −3,3 %, interval −7,3 % do +1,6 %, na samo 41
kopiji.</p>
<p>Neovisno istraživanje našlo je isto. U studiji 200.443 pump.fun lansiranja onaj tko ulazi na prvi signal grupe
novčanika {S.a("arxiv_earlybuyers", "gubio je izvan uzorka u sve 32 postavke")} i nije bio bolji od nasumičnog ulaza.
Jupiterova stranica o rizicima kaže općenito: kad kopiraš novčanik
{S.a("jup_risks", "trguješ kasnije, po svojoj cijeni, a njegovi prošli rezultati ne predviđaju tvoje")}.</p>

<h2>Što zasad kaže demo</h2>
<p>Od 19. studenoga demo račun prati te novčanike uživo, bez pravog novca i nakon stvarnih troškova:</p>
{B("Demo praćenje od 19. 11. 2026.", [
    ("Kandidati (širi popis)", 16.3, "n = 43; prosjek nosi nekoliko tradeova"),
    ("Stariji popis insajdera", -7.7, "n = 73"),
    ("Novčanici prije pumpe na tokenima 15-200 M $", -7.5, "n = 23"),
    ("Kopiranje 'dokazanih' novčanika", -10.1, "n = 30"),
], sub="Prosjek u % po tradeu nakon stvarnih troškova", fmt="pct", hl=(0,), source=SRC, vmax=17)}
<p>Četiri dana i nekoliko desetaka tradeova po popisu premalo je za zaključak, a jedini pozitivni popis nosi nekoliko
tradeova. Pokazujemo ga jer se skrivanjem ranih brojki rezultati biraju po volji.</p>

<h2>Što bi se računalo kao dokaz</h2>
<ul>
<li>Isti test izvan uzorka (odabir iz prošlosti, kašnjenje, stvarni trošak, promašene kupnje brojane) s prosjekom iznad
nule <b>i</b> intervalom od 95 % čiji je donji kraj iznad nule.</li>
<li>Jasno bolje od nasumične kontrole, ne samo u plusu.</li>
<li>Izdrži na kasnijim danima koje odabir nikad nije vidio, u demu, ne samo na povijesti.</li>
</ul>
<p>Zašto tri uvjeta, a ne jedan? Pozitivan prosjek na povijesti lako je dobiti slučajno, posebno kad nekoliko golemih
dobitnika nosi sve. Usporedba s nasumičnom kontrolom pokazuje je li odabir novčanika uopće išta dodao, a demo na
kasnijim danima pokazuje vrijedi li to i kad se tržište promijeni. Test koji prođe samo jedan uvjet nije test, nego
nada.</p>
<p>Dok ne vrijede sva tri, MemeSonar ne kopira novčanike pravim novcem; za to treba namjerno ručno uključenje, i to tek
kad test prođe. Ako koristiš <a href=/hr/najbolji-kripto-alati/copy-trading-platforme>alat za copy trading</a>, traži od
njega iste tri stvari. Većina ne zna odgovoriti.</p>
{RISK}
""")

# c ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "do-solana-meme-coins-follow-bitcoin", "prate-li-solana-meme-coini-bitcoin", "Tržište",
    "Prate li Solana meme coini Bitcoin? 201 dan podataka",
    "Prate li Solana meme coini Bitcoin? 201 dan podataka",
    "Medijan korelacije dnevnog kretanja praćenog meme coina s BTC-om: 0,28 kroz 201 dan. Skokovi po režimu BTC-a, "
    "volumen launchpada 23. 11. i zašto je popis pristran.", 7,
    "Samo labavo. Kroz 201 dan medijan korelacije dnevnog kretanja praćenog Solana meme coina s Bitcoinom bio je 0,28 "
    "(197 tokena), a 17 tokena često se kretalo suprotno od tržišta. Skokova je bilo više na crvene dane Bitcoina (1,61 "
    "na 100 token-dana) nego na zelene (0,61), ali popis tokena pristran je prema nedavnim skakačima, pa to nije razlog "
    "za kupnju kad Bitcoin pada.",
    f"""
<h2>Zašto pitati</h2>
<p>Većina kripto tradera prvo pogleda Bitcoin. Ako BTC padne, pretpostave da pada sve. Za velike coine to otprilike
vrijedi; za meme coine veza je slabija nego što ljudi misle, a korisno pitanje nije "prate li", nego "koliko i što se
mijenja kad se BTC pomakne". Istraživanje na velikim coinima već je pokazalo da prinosi kriptovaluta
{S.a("nber_crypto", "malo ovise o burzi i makroekonomiji, a pokreću ih momentum i pažnja specifični za kripto")}. Meme
coini to guraju dalje.</p>

<h2>Što smo izmjerili</h2>
<p>Alat svaki dan prati popis Solana meme coina i označava svaki dan po kretanju Bitcoina kao zeleni, bočni ili
crveni. Kroz 201 dan:</p>
{B("Dani Bitcoina po režimu", [
    ("Zeleni", 42, "BTC raste"), ("Bočni", 99, "BTC otprilike miruje"), ("Crveni", 59, "BTC pada"),
], sub="Broj dana od 201", fmt="num", hl=(1,), source=SRC)}
{stats([("0,28", "medijan korelacije s BTC-om (197 tokena)"), ("17", "tokena često ide suprotno od tržišta"),
        ("285 / 123", "otkrivenih skokova / padova")])}
<p>Korelacija od 0,28 znači da BTC objašnjava tek mali dio dnevnog kretanja tipičnog meme coina. 1,0 bilo bi kretanje u
korak, 0 nikakva veza. Sedamnaest tokena često je išlo suprotno od tržišta. Dakle, "BTC raste, rast će i moj meme coin"
slabo je pravilo.</p>

<h2>Skokovi po režimu Bitcoina</h2>
{B("Skokova na 100 token-dana", [
    ("Zeleni dan BTC-a", 0.61, ""), ("Bočni dan BTC-a", 0.79, ""), ("Crveni dan BTC-a", 1.61, "vidi upozorenje o pristranosti"),
], sub="Koliko je često praćeni token skočio, po režimu BTC-a toga dana", fmt="num", hl=(2,), source=SRC)}
<p>Na prvi pogled skokova je na crvene dane bilo više nego dvostruko. <b>Ne čitaj to kao signal za kupnju.</b> Popis
praćenih tokena pristran je prema tokenima koji su nedavno skočili, jer su mnogi baš tako ušli na popis. Nedavni
skakač na crveni dan i dalje je u uzorku; token koji je isti dan izblijedio možda nikad nije dodan. Režim Bitcoina i
način punjenja popisa međusobno su isprepleteni, a u 201 danu ima samo 59 crvenih dana. Ono što broj podržava je
slabija tvrdnja: skokovi meme coina nisu ograničeni na dobre dane Bitcoina.</p>

<h2>Gdje je novac danas</h2>
<p>Drugi termometar je volumen: koliko se stvarno trguje na Solani i gdje. Stanje 23. studenoga 2026., 24 sata, u
usporedbi sa 7-dnevnim prosjekom svakog mjesta:</p>
{B("Volumen Solana DEX-ova po mjestu, 24 h (23. 11. 2026.)", [
    ("Orca", 149.9, "-32% prema 7-dnevnom prosjeku"), ("PumpSwap", 109.8, "-39%"), ("Meteora", 108.3, "-35%"),
    ("Raydium", 103.7, "-34%"), ("pump.fun (bonding krivulja)", 83.4, "-6%"),
], sub="Milijuni US$; ukupni volumen Solana DEX-ova 1,12 mlrd. $ (-19% prema 7-dnevnom prosjeku)", fmt="num", hl=(4,),
    source=SRC)}
<p>Ukupni volumen Solana DEX-ova bio je 1,12 milijardi $, 19 % ispod 7-dnevnog prosjeka, a cijeli Solana meme sektor
vrijedio je 1,89 milijardi $. Zanimljiv detalj: volumen na pump.fun bonding krivulji, gdje se potpuno novi coini trguju
prije nego {S.a("pump_fees", "diplomiraju na PumpSwap")}, pao je samo 6 %, dok su veliki poolovi pali za trećinu.
Trgovanje novim coinima držalo se dok se trgovanje u velikim poolovima na {S.a("meteora_docs", "Meteori")} i
{S.a("orca_docs", "Orci")} hladilo. Aktivnost novih coina najmanje je vezana uz Bitcoin, a ujedno ima najviše
rugova; vidi <a href=/hr/blog/sto-je-pump-fun>što je pump.fun i kakvi su ti izgledi</a>.</p>
<p>Brojke uživo: <a href=/hr/solana-trziste>Solana tržište danas</a> i
<a href=/hr/indeks-sezone-meme-coina>indeks sezone meme coina</a>.</p>

<h2>Što s tim napraviti</h2>
<ul>
<li>Bitcoin koristi kao termometar rizika, ne kao signal. Oštar pad BTC-a važan je za stopove i veličinu pozicije; ne
predviđa koji će meme coin skočiti.</li>
<li>Uz BTC prati volumen launchpada i DEX-ova. Kad volumen presuši, izlazi poskupe, što god radio BTC
(<a href=/hr/blog/market-cap-likvidnost-slippage>slippage objašnjen</a>).</li>
<li>Zapamti tko gubi u slomovima. Nakon slomova 2022. BIS je utvrdio da su
{S.a("bis_69", "veliki imatelji prodavali, a mali ulagači kupovali, i da je većina korisnika aplikacija izgubila")}.</li>
</ul>

<h2>Tri greške na koje ovi podaci upozoravaju</h2>
<ol>
<li><b>Prodati svaki meme coin čim BTC padne.</b> Uz medijan korelacije od 0,28 crveni dan Bitcoina malo govori o
pojedinom tokenu. Stop vezan uz cijenu i likvidnost samog tokena govori više od Bitcoinove svijeće.</li>
<li><b>Kupiti zato što je BTC crven.</b> Veća učestalost skokova na crvene dane dolazi s pristranim popisom, pa bi
pravilo izgrađeno na tome testiralo način punjenja popisa, a ne tržište. Svako takvo pravilo moralo bi proći isti
test izvan uzorka kao i sve ostalo što objavljujemo.</li>
<li><b>Zanemariti volumen.</b> Pad volumena PumpSwapa od 39 % prema tjednom prosjeku znači manje kupaca za sve što
trebaš prodati. Tihi poolovi znače više slippagea na izlazu, što god radio Bitcoin.</li>
</ol>
<p>Ne imenujemo 17 tokena koji su se često kretali suprotno od tržišta. Kretanje u suprotnom smjeru kroz 201 dan
činjenica je o prošlosti, a ne zaštita na koju se možeš osloniti idući mjesec.</p>

<h2>Granice</h2>
<p>Popis tokena nije nasumičan i pristran je prema nedavnim skakačima; korelacije dnevnih kretanja skrivaju što se
događa unutar dana; a 201 dan je jedna faza tržišta. Stanje volumena je jedan dan. Metoda i definicije: {METHOD}.</p>
{RISK}
""")

# d ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "how-memesonar-measures", "kako-memesonar-mjeri", "Metoda",
    "Kako MemeSonar mjeri: troškovi, kašnjenja, promašeni tradeovi i intervali",
    "Kako MemeSonar mjeri: troškovi, kašnjenja i intervali",
    "Pravila iza svake MemeSonarove brojke: stvarni trošak od najmanje 3 %, kašnjenje kopije, brojanje promašenih "
    "tradeova, odabir izvan uzorka i intervali od 95 %.", 7,
    "Svaki rezultat koji objavimo je nakon stvarnih troškova (na meme coinima nikad ispod 3 %), koristi samo informacije "
    "dostupne u tom trenutku, broji tradeove koje bi sljedbenik promašio i dolazi s intervalom od 95 % i veličinom "
    "uzorka. Rezultat zovemo dokazanim tek kad je donji kraj intervala iznad nule na podacima koje odabir nije vidio.",
    f"""
<h2>Zašto stranica o metodi</h2>
<p>Kripto je pun brojki koje ne mogu izgubiti: screenshotovi dobitnika, kanali s "90 % pogodaka", popisi novčanika
odabrani naknadno. To nisu toliko laži koliko mjerenja napravljena da izgledaju dobro. Tekstovi na ovom blogu, na
primjer <a href=/hr/blog/novcanici-koji-kupuju-prije-skoka-solana-tokena>novčanici koji kupuju prije pumpe</a> i
<a href=/hr/blog/isplati-li-se-kopirati-pametne-novcanike>test kopiranja</a>, slijede pravila ispod. Ako je negdje
pravilo prekršeno, to je greška i želimo za nju čuti.</p>

<h2>1. Uvijek stvarni troškovi</h2>
<p>Trade koji prije troškova izgleda kao +5 % nakon njih je često gubitak. Svaka kupnja i prodaja plaća mrežnu naknadu,
često prioritetnu naknadu i slippage: razliku između cijene koju vidiš i cijene koju dobiješ, koja brzo raste kad je
trade velik u odnosu na pool ({S.a("jup_risks", "Jupiter objašnjava slippage i utjecaj na cijenu")}). Na meme coinima
nikad ne računamo ukupni trošak kupnje i prodaje ispod 3 %. U testu kopiranja skromnih 1 % slippagea na brzoj kopiji
bilo je dovoljno da prosjek postane gubitak od 7,6 %.</p>

<h2>2. Kašnjenje</h2>
<p>Sljedbenik djeluje nakon vođe. Naši testovi kopiranja kupuju fiksno vrijeme nakon kopiranog novčanika: 60 sekundi
(čovjek ili spori bot) i 2 sekunde (brzi bot). Brzina ima cijenu: da uđeš u isti blok, natječeš se s drugim botovima
{S.a("helius_pf", "prioritetnom naknadom po compute jedinici")}.</p>

<h2>3. Promašeni tradeovi se broje</h2>
<p>Neki se tradeovi ne mogu kopirati: tokena više nema, cijena je pobjegla, pool je pretanak. Izbacivanje takvih
tradeova svaku strategiju čini boljom, jer su promašeni često najbolji. Objavljujemo koliko ih je promašeno; u testu
kopiranja to je bilo 34,8 % kupnji novčanika.</p>

<h2>4. Odabir samo iz prošlosti</h2>
<p>Ako najbolje novčanike odabereš na cijeloj povijesti i onda ih testiraš na istoj povijesti, izgledat će sjajno:
odabrao si ih zato što su na njoj sjajni. Mi biramo iz prošlosti i testiramo na onome što je došlo poslije, a zatim
ponovno na kasnijim danima u demu. Obrazac je "potvrđen" tek kad izdrži na danima koje odabir nije vidio; tako je
potvrđeno, na primjer, 90 od 257 grupa novčanika koje se ponavljaju.</p>

<p>Isto vrijedi i za brojanje grupa: novčanik koji se pojavi rano u tri pumpe istog tjedna nije isto što i grupa
koja se nastavi pojavljivati tjednima nakon što je odabrana. Prvo je priča, drugo je obrazac koji vrijedi testirati.</p>

<h2>5. Kontrolna skupina</h2>
<p>Svaki test ide uz nešto glupo: nasumične rane kupce, nasumične ulaze. Ako pametna verzija nije jasno bolja od glupe,
nije pametna. U testu kopiranja nasumični rani kupci u prosjeku su imali +2,7 % uz širok interval; to je letvica.</p>

<h2>6. Intervali, ne samo prosjeci</h2>
<p>Rezultati meme coina su divlji: nekoliko golemih dobitnika i puno gubitnika. Sam prosjek to skriva. Uz svaki
prosjek pokazujemo interval od 95 %, raspon u kojem stvarni prosjek vjerojatno leži s obzirom na rasipanje rezultata
({S.a("nist_ci", "NIST-ov priručnik o granicama pouzdanosti")}), i broj tradeova (n). Naše pravilo:</p>
<ol>
<li>Donji kraj intervala od 95 % je iznad nule, na podacima izvan uzorka.</li>
<li>Rezultat je jasno bolji od nasumične kontrole.</li>
<li>Izdrži u demu na kasnijim danima, prije bilo kakvog pravog novca.</li>
</ol>
<p>Veličina uzorka važna je koliko i prosjek. Na ovoliko kopija počiva svaki rezultat testa kopiranja:</p>
{B("Test kopiranja: broj kopija iza svakog rezultata", [
    ("Kopija 60 s nakon njih", 1219, "prosjek +29,7 %, interval -12,9 % do +114,3 %"),
    ("Brza kopija, 2 s", 1202, "prosjek -7,6 %, interval -9,3 % do -5,7 %"),
    ("Nasumični rani kupci (kontrola)", 49, "prosjek +2,7 %, interval -22,4 % do +45,0 %"),
    ("Ulaz od 15 M $+", 41, "prosjek -3,3 %, interval -7,3 % do +1,6 %"),
], sub="n po rezultatu, 23. 11. 2026.", fmt="num", hl=(0, 1), source=SRC)}
<p>Mali uzorci daju široke intervale: 41 ili 49 tradeova može skriti gotovo sve. Po pravilu iznad test kopiranja na 60
sekundi (+29,7 %, interval −12,9 % do +114,3 %) nije dokazan, a kopija za 2 sekunde (−7,6 %, interval −9,3 % do
−5,7 %) dokazano je negativna.</p>

<p>Zato uz svaki rezultat piše i n. Prosjek na 1.200 kopija i prosjek na 41 kopiji nisu jednako vrijedni, čak i kad
su brojke slične.</p>

<h2>7. Demo prije pravog novca</h2>
<p>Nove ideje prvo trguju na demo računu, uz iste troškove, i svaki demo ulaz označen je režimom tržišta u kojem je
uzet. Demo rezultati nikad se ne računaju kao dokaz za pravi novac, osim ako bi i pravi novac uzeo isti ulaz.</p>

<h2>8. Statistika, ne optužbe</h2>
<p>Opisujemo grupe i obrasce. Nikad ne objavljujemo adrese novčanika, a riječi poput "insajder" ili "tim" opisuju
statistički oblik (zajednički izvor novca, kupnje u istoj sekundi), ne tvrdnju o osobi. Grupe novčanika zaključuju se
iz javnih podataka, koji se mogu {S.a("helius_etx", "pretvoriti iz sirovih Solana transakcija u swapove i prijenose")},
i neki će zaključci biti krivi.</p>

<h2>9. Datumi i izvori</h2>
<p>Svaka brojka ima datum. Naša mjerenja označena su kao MemeSonarova; vanjske činjenice vode na službenu
dokumentaciju, regulatore ili istraživanja, svaki izvor provjeren prije nego što je povezan. Tržišni podaci dolaze iz
javnih on-chain i DEX podataka, poput {S.a("dexs_api", "javnog API-ja DEX Screenera")}.</p>

<h2>Što ovo ne radi</h2>
<p>Ne čini da prošlost predviđa budućnost. Ovakva metoda može reći da nešto nije radilo, ili da je radilo uz poznatu
nesigurnost; ne može obećati sljedeći mjesec. Meme coini ostaju izuzetno rizični, a većina onoga što mjerimo su
gubici.</p>
{RISK}
""")
