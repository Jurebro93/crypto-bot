"""Hrvatske verzije deset blog postova (/hr/blog/<slug>). Iste brojke kao engleske (ui/blogposts.py), isti izvori.
Ključ rječnika = engleski slug, tako da se dvije verzije povezuju (hreflang)."""
from ui import calcs as CALC
from ui.blogviz import bars, grid, stats

RETRO = "MemeSonar retrospektiva 10.650 pump.fun tokena, listopad 2026."
WALLETS = "MemeSonar praćenje novčanika, stanje 30. 10. 2026."
KOL = "MemeSonar mjerenja poziva influencera, listopad 2026."

HR = {}


def post(en, slug, tag, h1, title, desc, mins, tldr, body):
    HR[en] = dict(slug=slug, tag=tag, h1=h1, title=title, desc=desc, mins=mins, tldr=tldr, body=body)


def B(*a, **k):
    return bars(*a, lang="hr", **k)


# 1 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "what-is-wallet-tracking", "sto-je-pracenje-novcanika", "Praćenje novčanika",
    "Što je praćenje novčanika (wallet tracking) i zašto većina 'smart moneyja' nije pametna",
    "Što je wallet tracking? Kako pratiti Solana novčanike uz podatke | MemeSonar",
    "Wallet tracking znači pratiti što određeni Solana novčanici kupuju i prodaju. Pratili smo 469 novčanika: samo 11 "
    "od 50 aktivnih bilo je u plusu. Kako pronaći one koje vrijedi pratiti.", 7,
    "Praćenje novčanika znači gledati kupnje i prodaje određenih adresa na blockchainu, da bi učio od tradera koji su "
    "redovito rani (ili ih kopirao). Radi samo uz strogo filtriranje: od 469 Solana novčanika koje smo pratili, 50 ih je "
    "trgovalo dovoljno za ocjenu, 11 je bilo u plusu, a samo 2 vrijedilo je kopirati.",
    f"""
<h2>Što je praćenje novčanika</h2>
<p>Svaki trade na Solani je javan. Adresa novčanika je kao broj računa koji svatko može pogledati: koje je tokene
kupio, kada, za koliko SOL-a i kada je prodao. <b>Wallet tracker</b> prati popis adresa i javi ti u nekoliko sekundi
kad netko od njih trguje.</p>
<p>Ideja je jednostavna. Neki traderi redovito ulaze rano u tokene koji kasnije narastu. Ako vidiš njihove kupnje dok
se događaju, možeš učiti od njih ili ih pratiti s malim iznosom. Takve adrese zovu se <b>smart money</b>.</p>

<h2>Problem: većina "smart moneyja" nije pametna</h2>
<p>Popisa "pametnih novčanika" ima posvuda na X-u i Telegramu. Skupili smo njih 469 iz javnih izvora (popisi
novčanika influencera, rani kupci tokena koji su narasli, novčanici dijeljeni u kanalima) i izmjerili svaki trade. Ovo
je ostalo nakon svakog koraka:</p>
{B("Od 469 'pametnih' novčanika do 2 koja vrijedi kopirati", [
    ("Skupljeni novčanici", 469, "javni popisi, rani kupci pobjednika, dijeljeni u kanalima"),
    ("S dovoljno povijesti za ocjenu", 293, "uspjeli smo rekonstruirati tradeove"),
    ("10+ zatvorenih tradeova", 50, "dovoljno za ocjenu vještine, a ne sreće"),
    ("U plusu nakon svih tradeova", 11, "ostvarena dobit iznad nule"),
    ("Vrijedi kopirati", 2, "u plusu, nije bot, snajper ni insajder, drži dovoljno dugo"),
], sub="Broj novčanika nakon svakog filtra", fmt="num", hl=(4,), source=WALLETS)}
<p>Samo 22% aktivnih novčanika bilo je u plusu. Tipičan aktivni novčanik dobio je 31% tradeova, držao poziciju
<b>manje od 4 minute</b> i radio oko 100 tradeova dnevno. To je bot ili snajper, a ne netko koga možeš pratiti rukom:
dok vidiš kupnju, on je već prodao.</p>

<h2>Oznake koje te trebaju zaustaviti</h2>
<p>Dobar tracker označi novčanike prije nego što ih počneš pratiti. Na našem popisu 124 novčanika imala su barem
jednu oznaku upozorenja:</p>
{B("Oznake upozorenja na praćenom popisu", [
    ("Snajper (kupuje u prvim sekundama)", 61, "zarađuje jer je prvi, ti ne možeš biti brži"),
    ("Insajder (blizu tima tokena)", 22, "zna za lansiranje prije tebe"),
    ("Bundler (kupuje u bloku lansiranja)", 17, "kontrolira ponudu od početka"),
    ("Bot (trguje bez prestanka)", 16, "stotine tradeova dnevno"),
    ("Kreator tokena", 15, "stvara tokene i prodaje kupcima"),
    ("Burza ili veza s rugom", 11, "novčanici burzi, rugera i onih koji ih financiraju"),
], sub="Novčanici po oznaci (jedan novčanik može imati više oznaka)", fmt="num", hl=(0,), source=WALLETS)}

<h2>Kako ispravno pratiti Solana novčanik</h2>
<ol>
<li><b>Ocjenjuj po zatvorenim tradeovima, ne po screenshotovima.</b> Deset zatvorenih tradeova je minimum; jedan trade
od 50x može sakriti četrdeset gubitaka. Kod nas je 3 od 11 profitabilnih novčanika više od pola dobiti zaradilo na
jednom tradeu.</li>
<li><b>Gledaj koliko drži.</b> Ako je tipično držanje kraće od 10 minuta, ne možeš ga kopirati ručno.</li>
<li><b>Provjeri u što je kupovao.</b> Novčanik koji stalno kupuje tokene koji se kasnije rugaju ili nema sreće ili je
dio igre.</li>
<li><b>Izbaci snajpere, bundlere, insajdere i botove.</b> Njihova prednost je brzina ili informacija iznutra, a to
kopiranjem ne dobiješ.</li>
<li><b>Ponovo ocijeni svaki tjedan.</b> Novčanici koji su bili vrući prošli mjesec ohlade se. Tracker bi ih trebao
sam izbaciti.</li>
</ol>

<h2>Wallet tracker ili block explorer?</h2>
<p>Svaku adresu možeš pogledati na Solscanu ili DEX screeneru, ali to ti pokazuje povijest, ne odluku. Wallet tracker
dodaje tri stvari: obavijesti u stvarnom vremenu, ocjenu iz zatvorenih tradeova i oznake koje upozoravaju na snajpere
i insajdere. MemeSonar dodaje i četvrtu: svaki token koji praćeni novčanik kupi prvo prolazi naš
<a href=/hr/blog/kako-prepoznati-rug-pull>filtar za rug</a>, a javlja ti i kad <b>više</b> dobrih novčanika kupi isti
token, što je puno važnije od jednog novčanika.</p>
<p>Dalje: <a href=/hr/blog/sto-je-copy-trading>što je copy trading i kad se isplati</a>.</p>
""")

# 2 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "what-is-copy-trading", "sto-je-copy-trading", "Copy trading",
    "Što je copy trading u kriptu i isplati li se?",
    "Što je copy trading? Isplati li se kopirati tradere u kriptu (stvarni podaci) | MemeSonar",
    "Copy trading znači automatski ponavljati kupnje i prodaje drugog tradera. Izmjerili smo Solana novčanike i "
    "influencere: kada kopiranje radi, kada gubi i kako postaviti granice.", 7,
    "Copy trading znači da tvoj račun automatski kupuje i prodaje kad to napravi trader kojeg pratiš. Može se isplatiti, "
    "ali samo ako kopiraš rijetkog tradera sa stvarnom, ponovljivom prednošću i ograničiš koliko jedan kopirani trade "
    "smije izgubiti. Kod nas je tu granicu prešlo samo 2 od 50 aktivnih Solana novčanika.",
    f"""
<h2>Kako copy trading radi</h2>
<p>Odabereš tradera, adresu novčanika ili influencera čijim pozivima vjeruješ. Svaki put kad on kupi token, tvoj
račun kupi isti token iznosom koji si postavio, na primjer $25. Kad on proda, ili kad se aktivira tvoj stop-loss ili
take-profit, prodaješ i ti.</p>
<p>Na velikim burzama copy trading znači pratiti "glavnog tradera" unutar burze. Kod Solana meme coina to znači
pratiti <a href=/hr/blog/sto-je-pracenje-novcanika>praćeni novčanik</a> ili <a href=/hr/blog/sto-je-kol-u-kriptu>KOL-a</a>
izravno na blockchainu, što je brže i rizičnije.</p>

<h2>Isplati li se copy trading?</h2>
<p>Gotovo sve ovisi o tome koga kopiraš. Ovo su srednje vrijednosti za 50 Solana novčanika s barem 10 zatvorenih
tradeova:</p>
{stats([("31%", "tipičan udio dobitnih tradeova"), ("3,8 min", "tipično vrijeme držanja pozicije"),
        ("22%", "novčanika u plusu nakon svih tradeova")])}
<p>Kopiranje tipičnog novčanika gubi novac: njegov profit factor (dobiveno podijeljeno s izgubljenim) bio je 0,65,
dakle svaki izgubljeni $1 vratio je 65 centi. Dva novčanika koja su prošla naš filtar izgledala su potpuno drukčije:</p>
{B("Povrat na uloženo, zadnjih 30 do 60 dana", [
    ("Kandidat A (16 zatvorenih tradeova)", 36, "pogodak 38%, 4 tradea 2x+, drži ~35 min"),
    ("Kandidat B (18 zatvorenih tradeova)", 73, "pogodak 39%, 5 tradeova 2x+, drži ~8 min"),
], sub="Dobit kao % uloženog SOL-a", fmt="pct", source=WALLETS)}
<p>Za usporedbu, tipičan aktivni novčanik vratio je -7% na uloženo. Primijeti da i dobri gube većinu tradeova. Copy
trading meme coina radi jer nekoliko tradeova napravi 2x do 10x, a ne zato što većina pobjeđuje. Zato su granice
važnije od odabira.</p>

<h2>Copy trading za početnike: pet pravila</h2>
<ol>
<li><b>Kopiraj fiksnim malim iznosom</b> po tradeu (kod nas je zadano $25) i s dnevnim limitom (zadano 10 tradeova).
Jedan loš dan tada košta $250, a ne cijeli račun.</li>
<li><b>Kopiraj samo svježe ulaze.</b> Ako je trader kupio prije 30 minuta i cijena se već udvostručila, ti si njegova
izlazna likvidnost. Naše kopiranje ulazi samo u pozive stare najviše 10 minuta.</li>
<li><b>Preskoči što ne prođe provjeru ruga.</b> I dobri traderi se kockaju. Tvoje kopiranje treba odbiti tokene s
uključenim mint authorityjem, lažnim bazenima likvidnosti ili koncentriranom ponudom. Vidi
<a href=/hr/blog/kako-prepoznati-rug-pull>kako prepoznati rug</a>.</li>
<li><b>Ne kopiraj ono što ne možeš pratiti.</b> Novčanik koji drži 20 sekundi je snajperski bot. Uvijek ćeš biti
sporiji.</li>
<li><b>Automatski prestani kopirati gubitnike.</b> Ocijeni svakog tradera iznova svaki tjedan i stani kad je zadnjih
20 kopiranih tradeova u minusu.</li>
</ol>

<h2>Kopirati novčanike ili influencere?</h2>
<p>Novčanici pokazuju što je netko stvarno napravio s novcem. Pozivi influencera pokazuju što je netko rekao. Pozivi
pomiču tržište (tokeni koje je pozvao izmjereni influencer došli su do 2x u 52% slučajeva, naspram 14% bez poziva),
ali influenceri mogu biti i plaćeni za objavu. Najbolji signal je oboje: <a href=/hr/blog/grupiranje-influencera>više
nezavisnih influencera</a> i dobri novčanici na istom tokenu u nekoliko minuta.</p>
""")

# 3 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "what-is-a-kol-in-crypto", "sto-je-kol-u-kriptu", "Influenceri",
    "Što je KOL u kriptu? Kako pozivi influencera pomiču Solana tokene",
    "Što je KOL u kriptu? Rade li pozivi kripto influencera? (podaci) | MemeSonar",
    "KOL je kripto influencer čije objave pomiču cijene. Izmjerili smo svaki poziv Solana tokena: pozvani tokeni došli "
    "su do 2x u 52% slučajeva, bez poziva u 14%. Kako čitati KOL-a.", 6,
    "KOL (key opinion leader) je kripto influencer, najčešće na X-u ili Telegramu, čija objava o tokenu može pomaknuti "
    "cijenu. Pozivi stvarno djeluju: kod nas je 52% pozvanih Solana tokena došlo do 2x, a tokena bez poziva 14%. Ali "
    "svaki KOL je drukčiji, pa ga ocjenjuješ po povijesti, a ne po broju pratitelja.",
    f"""
<h2>Što znači KOL</h2>
<p><b>KOL</b> je kratica za key opinion leader, osobu od utjecaja. U kriptu to je račun s dovoljno pažnje da njegove
objave mijenjaju što ljudi kupuju: trader na X-u s 50.000 pratitelja, Telegram kanal koji objavljuje nove tokene,
YouTuber. <b>Poziv</b> (call) je objava koja spominje token, obično s adresom ugovora, i kaže ili sugerira "kupi".</p>

<h2>Rade li KOL pozivi?</h2>
<p>Pratimo X račune influencera koji objavljuju Solana tokene i mjerimo cijenu svakog pozvanog tokena 1 sat i 24 sata
nakon objave te najvišu točku unutar 24 sata.</p>
{B("Udio tokena koji su došli do 2x", [
    ("Tokeni bez izmjerenog poziva", 14, "isto razdoblje"),
    ("Tokeni koje je pozvao izmjereni KOL", 52, "cijena se barem udvostručila nakon poziva"),
], sub="Solana tokeni, cijena u odnosu na trenutak poziva", fmt="pct", hl=(1,), source=KOL)}
<p>To je gotovo četiri puta veća šansa. Upravo zato se pozivi kupuju i prodaju: neki računi su plaćeni za objavu,
neki kupe prije objave i prodaju svojim pratiteljima. Poziv je signal, ne jamstvo.</p>

<h2>Kako ocijeniti kripto influencera</h2>
<p>Pratitelji pokazuju doseg, ne kvalitetu. Svakog KOL-a ocjenjujemo po tome što se dogodilo nakon njegovih poziva:</p>
<ul>
<li><b>Pogodak</b>: udio poziva koji su narasli barem 50% unutar 24 sata.</li>
<li><b>Tipičan vrh u 24 h</b>: uobičajena najviša točka nakon poziva. KOL čiji pozivi vrhunce imaju na +300% vrijedi
više od onoga na +40%, čak i uz isti pogodak.</li>
<li><b>Udio rugova</b>: udio pozvanih tokena koji su kasnije pali 90% ili više. To je broj koji te štiti.</li>
<li><b>Kasni pozivi</b>: pozivi nakon što se cijena već udvostručila u prethodna dva sata. Na grafu izgledaju dobro,
ali kupuješ vrh.</li>
<li><b>Sluša li ga tržište?</b> Je li se volumen barem udvostručio u satu nakon objave? Neki veliki računi ne pomaknu
ništa.</li>
</ul>
<p>Izbacujemo i botove. Petnaest računa u našim podacima automatski je objavljivalo svaki novi token; izgledali su kao
najaktivniji "KOL-ovi", a nisu imali nikakav signal. Žive ocjene vidiš na javnoj
<a href=/hr/influenceri>ljestvici kripto influencera</a>.</p>

<h2>Kada vrijedi reagirati na poziv</h2>
<ol>
<li>KOL ima barem 10 izmjerenih poziva, pogodak iznad 50% i nizak udio rugova.</li>
<li>Poziv je svjež (minute, ne sati) i cijena se još nije udvostručila.</li>
<li>Token prolazi <a href=/hr/blog/kako-prepoznati-rug-pull>provjeru ruga</a>.</li>
<li>Idealno, zovu ga i drugi nezavisni KOL-ovi. To je najjači obrazac u našim podacima, vidi
<a href=/hr/blog/grupiranje-influencera>grupiranje influencera</a>.</li>
</ol>
""")

# 4 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "influencer-clustering", "grupiranje-influencera", "Influenceri",
    "Grupiranje influencera: zašto su važna 3 KOL-a koja zovu isti token u 15 minuta",
    "Grupiranje kripto influencera: kad više KOL-ova zove isti token (podaci) | MemeSonar",
    "Kad 3+ kripto influencera zove isti Solana token u 15 minuta, 59% tih tokena se udvostruči, inače 33%. Kako "
    "nastaju grupe i kako prepoznati plaćenu kampanju.", 6,
    "Grupa (klaster) nastaje kad više nezavisnih influencera zove isti token u kratkom razmaku. Kod nas su tokeni koje su "
    "3+ KOL-a pozvala unutar 15 minuta došli do 2x u 59% slučajeva, naspram 33% kad ih je zvalo manje (snimka 1. 11. 2026.; "
    "živi broj je na naslovnici). Ali i grupe se "
    "mogu kupiti, pa provjeravaš tko je u grupi i pojavljuju li se uvijek zajedno.",
    f"""
<h2>Što je grupiranje influencera?</h2>
<p>Jedan influencer koji zove token je jedno mišljenje. Kad ga nekoliko njih zove u nekoliko minuta, ili su ga našli
nezavisno (pravi signal: različiti ljudi, isti zaključak) ili su dogovoreni (grupa koja pumpa zajedno, ponekad
plaćena). Oboje pomiče cijenu. Samo jedno je sigurno pratiti.</p>

<h2>Podaci: grupe se puno češće udvostruče</h2>
{B("Pozvani tokeni koji su došli do 2x unutar 24 sata", [
    ("1-2 KOL-a unutar 15 minuta", 33, "prvi poziv i najviše još jedan"),
    ("3+ različita KOL-a unutar 15 minuta", 59, "računa se od prvog poziva"),
], sub="Solana tokeni s barem jednim izmjerenim pozivom, snimka 1. 11. 2026.; živi broj je na naslovnici", fmt="pct", hl=(1,), source=KOL)}
<p>Prozor od 15 minuta je bitan. Kasniji pozivi obično prate prvi poziv i nisu nezavisni, a dotad se pomak često već
dogodio. Brojimo različite račune, pa je jedan KOL koji objavi tri puta i dalje jedan.</p>

<h2>Prirodna grupa ili dogovorena ekipa?</h2>
<p>Tjednima pratimo koji influenceri zovu iste tokene. Ističu se tri obrasca:</p>
<ul>
<li><b>Nezavisna grupa</b>: računi koji se rijetko preklapaju odjednom zovu isti token. To je najjači signal koji
vidimo.</li>
<li><b>Stalna ekipa</b>: istih 4 do 6 računa zove iste tokene iznova, često u istoj minuti. To je promotivna grupa.
Prve minute i dalje mogu pumpati, ali i pad je organiziran.</li>
<li><b>Jeka</b>: jedan veliki račun zove, a mali računi ponavljaju. Mali pozivi dodaju malo; oni su pratitelji.</li>
</ul>
<p>Prikaz "Korelacije" u aplikaciji pokazuje te grupe kao mrežu, a signal za copy trading nezavisnoj grupi daje veću
težinu nego stalnoj ekipi.</p>

<h2>Kako koristiti grupe, a ne biti izlazna likvidnost</h2>
<ol>
<li>Reagiraj na <b>treći nezavisni</b> poziv, ne na deseti. Nakon toga gomila kasni.</li>
<li>Provjeri cijenu prije kupnje. Ako se već udvostručila od prvog poziva, preskoči.</li>
<li>Provuci token kroz <a href=/hr/blog/kako-prepoznati-rug-pull>provjeru ruga</a>. Dogovorene ekipe često lansiraju
tokene s bundlanom ponudom (vidi <a href=/hr/blog/bundleri-i-snajperi>bundleri i snajperi</a>).</li>
<li>Koristi male, fiksne iznose i rano uzmi dio dobiti. Grupe brzo dođu do vrha.</li>
</ol>
<p>Ocjene svakog izmjerenog influencera su na javnoj <a href=/hr/influenceri>ljestvici KOL-ova</a>.</p>
""")

# 5 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "how-to-spot-a-rug-pull", "kako-prepoznati-rug-pull", "Rug pull",
    "Kako prepoznati rug pull na Solani: 7 provjera iz 10.650 tokena",
    "Kako prepoznati rug pull na Solani: popis provjera (podaci iz 10.650 tokena) | MemeSonar",
    "Sedam provjera koje hvataju većinu Solana rug pullova, s brojkama iz 10.650 pump.fun tokena: serijski kreatori, "
    "prodaja developera, mint authority, lažni bazeni, društvene mreže.", 8,
    "Rug pull je kad ljudi iza tokena uzmu novac, a cijena se sruši: prodajom svoje ponude, povlačenjem likvidnosti ili "
    "tiskanjem novih tokena. Većina se vidi prije kupnje: kod nas su tokeni kreatora koji su prije lansirali 20+ tokena "
    "došli do 2x u samo 1,4% slučajeva, a tokeni novih kreatora u 16,8%.",
    f"""
<h2>Što je rug pull?</h2>
<p><b>Rug pull</b> je token čiji kreatori ili insajderi unovče sve i ostave kupce s nečim bezvrijednim. Na Solani se
najčešće događa na jedan od tri načina: kreator i povezani novčanici prodaju velik dio ponude kupcima, bazen
likvidnosti se povuče ili se mint authorityjem tiskaju novi tokeni. Tiša verzija je spori rug: tim prodaje malo
svaki sat dok ništa ne ostane.</p>
<p>Kad svaki sat čistimo bazu, to se jasno vidi. U prvom čišćenju 1. studenoga 2026. uklonjen je 61 token stariji od
dana: 52 su pala 70% ili više, a 9 je imalo mehaniku ruga, na primjer povučenu likvidnost.</p>

<h2>Provjera 1: tko ga je napravio i koliko puta prije?</h2>
<p>Najjače pojedinačno upozorenje u našim podacima je <b>serijski kreator</b>: novčanik koji je prije lansirao puno
tokena.</p>
{B("Tokeni koji su došli do 2x, po prijašnjim lansiranjima kreatora", [
    ("Prvi token ovog novčanika", 16.8, "2.598 tokena, 1. 11. 2026."),
    ("1-5 prijašnjih tokena", 9.2, "769 tokena"),
    ("6-20 prijašnjih tokena", 3.8, "764 tokena"),
    ("Više od 20 prijašnjih tokena", 1.4, "1.528 tokena"),
], sub="Mjereno 15 minuta nakon lansiranja; 2x = cijena se kasnije udvostručila", fmt="pct", hl=(3,), source=RETRO)}

<h2>Provjera 2: je li developer već prodao?</h2>
{B("Tokeni koji su došli do 2x, po ponašanju developera", [
    ("Developer još drži", 16.1, "2.696 tokena"),
    ("Developer je već nešto prodao", 6.6, "4.505 tokena"),
], sub="Mjereno 15 minuta nakon lansiranja", fmt="pct", hl=(1,), source=RETRO)}
<p>Pazi i kad developer prebaci tokene na puno novih novčanika. Tako skriva stvarni udio; mi to označimo kad prebaci
više od 90% svojih tokena.</p>

<h2>Provjera 3: mogu li se tiskati novi tokeni ili zamrznuti novčanici?</h2>
<p>Ako je <b>mint authority</b> još uključen, kreator može tiskati novu ponudu i prodati je. Ako je uključen
<b>freeze authority</b>, može te spriječiti da prodaš. Pump.fun tokeni imaju oba isključena; tokeni napravljeni drugdje
često nemaju. I jedno i drugo kod nas je automatsko odbijanje.</p>

<h2>Provjera 4: je li likvidnost stvarna?</h2>
<p>Traži barem $10.000 likvidnosti i provjeri da je u glavnom bazenu, a ne u lažnom bazenu napravljenom da token
izgleda trgovan. Naš filtar odbija tokene ispod $10k likvidnosti i tokene čiji jedini bazen nije na poznatom DEX-u.</p>

<h2>Provjera 5: društvene mreže (da, važne su)</h2>
{B("Tokeni koji su došli do 2x, po broju linkova", [
    ("Bez web stranice, X-a i Telegrama", 4.9, "1.134 tokena"),
    ("Jedan link", 9.3, "686 tokena"),
    ("Dva linka", 16.1, "852 tokena"),
    ("Sva tri", 31.3, "67 tokena"),
], sub="Mjereno 15 minuta nakon lansiranja", fmt="pct", hl=(0,), source=RETRO)}
<p>Linkove je besplatno dodati, pa sami po sebi malo dokazuju. Ali kad ih nema, to je jako upozorenje.</p>

<h2>Provjera 6: bundleri i snajperi</h2>
<p>Bundlana ponuda (kupljena u istom bloku kao lansiranje) i snajperi (kupili u prvim sekundama) daju maloj grupi
kontrolu nad cijenom. Tokeni s puno bundla češće pumpaju, a onda jače padaju. Pročitaj
<a href=/hr/blog/bundleri-i-snajperi>bundleri i snajperi</a>.</p>

<h2>Provjera 7: koncentracija vlasnika</h2>
<p>Ako top 10 vlasnika (bez bazena likvidnosti) drži više od otprilike trećine ponude, nekoliko novčanika može
završiti zabavu. Prati raste li taj udio nakon lansiranja: insajderi koji skupljaju preko novih novčanika klasičan su
scenarij.</p>

<h2>Rug checker to napravi u sekundi</h2>
<p>Svih sedam provjera radi na svakom tokenu koji MemeSonar pokaže, prije nego što ga vidiš. Tokeni koji padnu su
sakriveni, a ne samo označeni, i sustav svaki sat uči profil rugova koje je uhvatio.</p>
""")

# 6 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "what-is-pump-fun", "sto-je-pump-fun", "Osnove",
    "Što je pump.fun? Kako radi i što naši podaci kažu o tvojim šansama",
    "Što je pump.fun i kako radi? Bonding curve, graduacija i stvarne šanse | MemeSonar",
    "Na pump.funu svatko u minuti lansira Solana meme coin. Kako rade bonding curve i graduacija, i zašto se samo 0,8% "
    "nasumičnih novih tokena ikad udvostruči nakon prvih 15 minuta.", 6,
    "Pump.fun je Solana platforma na kojoj svatko za nekoliko centi napravi meme coin. Cijena prati bonding curve dok "
    "token ne 'diplomira' u običan DEX bazen. Većina nikad ne stigne do tamo: od 6.104 nasumična nova tokena koja smo "
    "pratili, 0,8% se udvostručilo nakon prvih 15 minuta.",
    f"""
<h2>Kako pump.fun radi</h2>
<p>Odabereš ime, ticker i sliku, platiš malu naknadu i token postoji. Nema tima, predprodaje ni likvidnosti koju treba
uložiti. Svaki token počinje s istom ponudom (milijarda) i istom početnom cijenom.</p>
<p>Cijena prati <b>bonding curve</b>: formulu koja diže cijenu kad ljudi kupuju i spušta je kad prodaju. Rani kupci
dobiju više tokena po SOL-u. Kad se uloži dovoljno SOL-a, token <b>diplomira</b>: likvidnost se seli u običan DEX
bazen i token se trguje kao bilo koji drugi, na DEX screenerima i trading botovima.</p>

<h2>Tvoje šanse, u brojkama</h2>
<p>Nasumično smo uzimali pump.fun tokene 15 minuta nakon lansiranja i pratili što je cijena radila dalje.</p>
{B("Što se dogodilo nasumičnim novim pump.fun tokenima", [
    ("Kasnije došli do 2x", 0.8, "od cijene 15 minuta nakon lansiranja"),
    ("Kasnije došli do 3x", 0.3, ""),
    ("Diplomirali u DEX bazen", 0.1, "otprilike 1 od 1.000 u nasumičnom uzorku"),
], sub="6.104 nasumična tokena, listopad 2026.", fmt="pct", hl=(0,), source=RETRO)}
<p>Drugim riječima, kupiti nasumičan novi token i čekati je igra na gubitak. Tokeni koji diplomiraju to naprave brzo:
tipično vrijeme do graduacije bilo je oko 15 minuta.</p>

<h2>Graduacija nije cilj</h2>
<p>Puno tradera čeka graduaciju kao dokaz interesa. Pomaže, ali manje nego što ljudi misle:</p>
{B("Diplomirani tokeni: udio koji je nakon graduacije otišao više", [
    ("Došli do 2x nakon graduacije", 9.5, ""),
    ("Došli do 3x", 7.3, ""),
    ("Došli do 5x", 4.9, ""),
], sub="2.784 diplomirana tokena, cijena u trenutku graduacije", fmt="pct", hl=(0,), source=RETRO)}
<p>Puno bolja točka ulaza u našim podacima je prvi put kad token prijeđe $100.000 tržišne kapitalizacije; zašto,
objašnjavamo u <a href=/hr/blog/kako-trgovati-meme-coinima>kako trgovati meme coinima</a>. Rijetki koji su uspjeli
nalaze se na našoj listi <a href=/hr/solana-meme-coini>top 100 Solana meme coina</a>.</p>

<h2>Je li pump.fun siguran?</h2>
<p>Sama platforma uklanja neke klasične trikove: mint i freeze authority su isključeni, a krivulja drži likvidnost do
graduacije. Ono što ne može zaustaviti su ljudi. Serijski kreatori, bundlana lansiranja i snajperi česti su na
pump.funu. Prije kupnje provjeri povijest kreatora i prve kupce, kao u
<a href=/hr/blog/kako-prepoznati-rug-pull>kako prepoznati rug pull</a>.</p>
""")

# 7 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "bundles-and-snipers", "bundleri-i-snajperi", "Rug pull",
    "Bundleri i snajperi: tko zapravo posjeduje novi Solana token",
    "Bundleri i snajperski botovi na Solani, objašnjeno (s podacima) | MemeSonar",
    "Bundleri kupuju u bloku lansiranja, snajperi u prvim sekundama. Tokeni s puno bundla češće pumpaju, a onda padaju "
    "dvostruko jače. Što to znači za tebe, s brojkama iz 7.201 tokena.", 6,
    "Bundle je grupa novčanika koja kupi token u istom bloku u kojem je napravljen; snajper kupuje u prvim sekundama. Oboje "
    "daje nekolicini novčanika velik dio ponude po najnižoj cijeni. Kod nas su tokeni s više od 20% bundlane ponude češće "
    "došli do 2x (25,5% naspram 3,6%), ali tipičan pad od vrha bio im je 54%.",
    f"""
<h2>Što je bundle?</h2>
<p>Na Solani se više transakcija može poslati zajedno i završiti u istom bloku. <b>Bundle</b> znači da kreator (ili
netko blizak) kupi velik dio vlastitog tokena u bloku u kojem je napravljen, raspoređeno na više novčanika, da izgleda
kao puno kupaca. <b>Bundle checker</b> pogleda taj prvi blok i zbroji što je kupljeno.</p>

<h2>Što je snajperski bot?</h2>
<p><b>Snajper</b> je bot koji kupi novi token u prvim sekundama, prije nego što ljudi stignu reagirati. Snajperi nisu
uvijek povezani s timom; mnogi se samo klade na svako lansiranje i prodaju prvom valu kupaca.</p>

<h2>Iznenađenje: bundlani tokeni češće pumpaju</h2>
{B("Tokeni koji su došli do 2x, po bundlanom udjelu ponude", [
    ("Ispod 2% bundlano", 3.6, "3.554 tokena"),
    ("2-10%", 10.8, "1.683 tokena"),
    ("10-20%", 15.4, "768 tokena"),
    ("Više od 20%", 25.5, "1.196 tokena"),
], sub="Mjereno 15 minuta nakon lansiranja", fmt="pct", hl=(3,), source=RETRO)}
<p>Izgleda kao signal za kupnju. Nije, a sljedeći graf pokazuje zašto. Bundlani token je organizirano lansiranje:
netko ima plan, možda i budžet za promociju, i cijena se gura gore. Pitanje je samo tko izlazi prvi.</p>
{B("Tipičan pad od najviše cijene", [
    ("Ispod 2% bundlano", 46, "srednji pad od vrha"),
    ("2-10%", 17, ""),
    ("10-20%", 35, ""),
    ("Više od 20%", 54, "insajderi prodaju u pumpu"),
], sub="Srednji najveći pad u prvim satima, %", fmt="pct", hl=(3,), source=RETRO)}
<p>Snajperi pokazuju isti obrazac: tokeni u kojima su snajperi uzeli više od 30% ponude došli su do 2x u 31,8%
slučajeva, a tipičan pad od vrha bio im je 58%.</p>

<h2>Što to znači za tebe</h2>
<ul>
<li>Velik bundle govori da je token nečiji projekt. Cilj tog projekta je prodati tebi po višoj cijeni.</li>
<li>Ako trguješ bundlanim tokenima, trguj prvi val malim iznosom i rano uzmi dobit. Ne drži ih preko noći.</li>
<li>Provjeri drže li bundle novčanici još uvijek. Kad počnu prodavati, pad je brz.</li>
<li>Kombiniraj s poviješću kreatora: bundlano lansiranje novčanika s 20+ prijašnjih tokena je klasičan rug.</li>
</ul>
<p>MemeSonar mjeri bundle udio, udio snajpera i prve kupce na svakom novom tokenu i ograničava koliko će sustav ikad
kupiti jako bundlanog tokena. Pročitaj cijeli <a href=/hr/blog/kako-prepoznati-rug-pull>popis provjera za rug</a>.</p>
""")

# 8 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "how-to-trade-meme-coins", "kako-trgovati-meme-coinima", "Trgovanje",
    "Kako trgovati meme coinima: kada ući, prema 10.650 tokena",
    "Kako trgovati meme coinima na Solani: najbolja točka ulaza (podaci iz 10.650 tokena) | MemeSonar",
    "Trenutak ulaza odlučuje većinu meme coin tradeova. Nasumični novi tokeni udvostručili su se u 0,8% slučajeva, "
    "diplomirani u 9,5%, a tokeni na prvom prelasku $100k u 24%. Praktičan plan.", 7,
    "Kada ulaziš važnije je od toga što biraš. Kod nas je kupnja nasumičnih tokena 15 minuta nakon lansiranja dovela do 2x "
    "u samo 0,8% slučajeva; na graduaciji u 9,5%; na prvom prelasku $100.000 tržišne kapitalizacije u 24%. Dobar plan čeka "
    "dokaz potražnje, filtrira rugove, ulaže malo i dobit uzima u koracima.",
    f"""
<h2>Točka ulaza važnija je od odabira tokena</h2>
<p>Iste tokene izmjerili smo u različitim trenucima njihova života i pitali: od ove cijene, koliko ih se kasnije
udvostručilo?</p>
{B("Tokeni koji su kasnije došli do 2x, po trenutku ulaza", [
    ("15 minuta nakon lansiranja (nasumično)", 0.8, "6.104 tokena"),
    ("Na graduaciji", 9.5, "2.784 tokena"),
    ("Prvi prelazak $100k tržišne kapitalizacije", 24.0, "217 tokena"),
    ("Prvi prelazak $1M tržišne kapitalizacije", 31.6, "19 tokena, mali uzorak"),
], sub="Cijena na ulazu prema kasnijem vrhu", fmt="pct", hl=(2,), source=RETRO)}
<p>Kasniji ulaz znači višu cijenu, ali i da je većina gubitnika već otpala. Prvi prelazak $100k je najbolji omjer koji
smo našli: dovoljno rano za 2x do 10x, dovoljno kasno da token ima prave kupce. Red za $1M izgleda još bolje, ali s 19
tokena to još nije pouzdan broj.</p>

<h2>Plan za trgovanje meme coinima</h2>
<h3>1. Pronađi kandidate</h3>
<p>Koristi signale koji predviđaju potražnju: više nezavisnih <a href=/hr/blog/grupiranje-influencera>poziva
influencera</a>, <a href=/hr/blog/sto-je-pracenje-novcanika>dobre novčanike</a> koji kupuju, rastući volumen. Izbjegavaj
tokene koje si našao jer su na ekranu već bili +300%.</p>
<h3>2. Filtriraj</h3>
<p>Prođi <a href=/hr/blog/kako-prepoznati-rug-pull>provjere za rug</a>: povijest kreatora, prodaja developera,
authorityji, stvarna likvidnost od barem $10.000, vlasnici.</p>
<h3>3. Odredi iznos</h3>
<p>Koristi fiksni iznos koji možeš izgubiti, na primjer 1 do 2% novca za trgovanje po tokenu. Kod meme coina rezultat
napravi nekoliko tradeova; veličina pozicije drži te u igri dovoljno dugo da ih pogodiš.</p>
<h3>4. Provjeri trošak ulaza i izlaza</h3>
<p>U bazenu od $10.000 kupnja od $1.000 dobije oko 17% manje tokena od prikazane cijene. Vidi
<a href=/hr/blog/market-cap-likvidnost-slippage>market cap, likvidnost i slippage</a>.</p>
<h3>5. Dobit uzimaj u koracima</h3>
<p>Prodaj dio na 2x da vratiš ulog, još dio na putu gore, a ostatak pusti uz trailing stop. Držanje svega za "100x"
je način na koji većina dobitnih tradeova postane gubitak.</p>
<h3>6. Doba dana</h3>
<p>Kod nas su signali influencera najbolje radili tijekom američkih sati, a ulazi u toj sesiji bili su najskuplji.
Znaj u kojoj sesiji trguješ.</p>

<h2>Gdje gledati danas</h2>
<p>Naša javna lista <a href=/hr/solana-meme-coini>top 100 Solana meme coina</a> pokazuje tržišnu kapitalizaciju,
likvidnost, volumen i vlasnike svakog tokena, na primjer <a href=/hr/coin/bonk>BONK</a>, <a href=/hr/coin/wif>WIF</a>
ili <a href=/hr/coin/fartcoin>Fartcoin</a>. To su preživjeli; tokeni iz grafova u ovom tekstu uglavnom nisu uspjeli.</p>

<h2>Vježbaj prije pravog novca</h2>
<p>Članovi MemeSonara trguju s demo saldom od $1.000 u prijateljskoj ligi, s istim signalima i filtrom za rug koje
koristi sustav. To je najjeftiniji način da saznaš radi li tvoj plan.</p>
""")

# 9 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "what-is-dca-in-crypto", "sto-je-dca", "Osnove",
    "Što je DCA u kriptu? Postupno ulaganje u meme coine, s primjerom",
    "Što je DCA u kriptu? Postupno ulaganje objašnjeno na primjeru | MemeSonar",
    "DCA znači kupovati fiksan iznos u pravilnim razmacima umjesto odjednom. Primjer: $500 odjednom naspram 10 x $50, "
    "na tokenu koji pada i na tokenu koji se ruga.", 5,
    "DCA (dollar-cost averaging, postupno ulaganje) znači kupovati isti iznos u fiksnim razmacima, na primjer $50 svakih "
    "12 sati, umjesto da uložiš sve odjednom. Spušta prosječnu cijenu kad cijena oscilira, a s automatskim zaustavljanjem "
    "ograničava štetu kad token propadne. Loš token ne pretvara u dobar.",
    f"""
<h2>Što znači DCA</h2>
<p><b>Dollar-cost averaging</b> raspodijeli jednu kupnju kroz vrijeme. Odabereš iznos, razmak i broj kupnji: na
primjer 10 kupnji po $50, jedna svakih 12 sati. Kad je cijena niska, $50 kupi više tokena; kad je visoka, manje.
Prosječna cijena tako završi ispod običnog prosjeka cijena po kojima si kupovao.</p>

<h2>Primjer: jedna kupnja ili deset</h2>
<p>Ilustrativni token padne s $1,00 na $0,45 kroz pet dana, a onda se oporavi na $0,90. Imaš $500.</p>
{B("Vrijednost $500 kad je cijena opet $0,90", [
    ("Sve odjednom po $1,00", 450, "500 tokena po $0,90"),
    ("10 x $50 kroz pet dana (DCA)", 692, "768 tokena, prosječna cijena $0,65"),
], sub="Ilustrativni primjer, nije stvarni token", fmt="usd", hl=(1,))}
<p>Isti novac, isti token, ista završna cijena: kupnja odjednom je -10%, DCA je +38%, jer je pola kupnji bilo ispod
$0,65.</p>

<h2>Gdje DCA stvarno pomaže kod meme coina: zaustavljanje</h2>
<p>Veći rizik kod meme coina nije pad, nego token koji ode na nulu. Recimo da se token ruga nakon tvoje treće kupnje i
odjednom vrijedi $0,03.</p>
{B("Što ostane nakon ruga", [
    ("Sve odjednom po $1,00", 15, "izgubljeno $485"),
    ("DCA koji stane kod ruga", 156, "potrošeno $150, ostalo ~$6, $350 nikad uloženo"),
], sub="Ilustrativni primjer: ostatak = preostali tokeni + neuloženi novac", fmt="usd", hl=(1,))}
<p>Automatski DCA treba sam stati kad token padne na sigurnosnom pravilu: likvidnost ispod minimuma, signal ruga ili
kraj budžeta.</p>

<h2>Kada je DCA loša ideja</h2>
<ul>
<li>Na tokenima koji stalno padaju: stalno dokupljuješ gubitnika. Postavi čvrst stop.</li>
<li>Na vrlo plitkim bazenima, gdje svaka kupnja pomakne cijenu (vidi
<a href=/hr/blog/market-cap-likvidnost-slippage>slippage</a>).</li>
<li>Kad naknade pojedu kupnje: na Solani su naknade male, ali kupnje od $5 ipak gube primjetan dio na naknade i
slippage.</li>
</ul>

<h2>DCA u MemeSonaru</h2>
<p>Članovi mogu pokrenuti automatski DCA na bilo kojem tokenu s njegove stranice: $5 do $500 po kupnji, svakih 15
minuta do jednom tjedno, 2 do 100 kupnji. Sam stane kad je plan gotov, kad ponestane novca, kad je token označen kao
rug ili kad mu likvidnost padne ispod $5.000.</p>
""")

# 10 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "market-cap-liquidity-slippage", "market-cap-likvidnost-slippage", "Osnove",
    "Market cap, likvidnost i slippage: tri broja koja čitaš prije kupnje meme coina",
    "Što su slippage, likvidnost i market cap u kriptu? (s tablicom slippagea) | MemeSonar",
    "Market cap govori veličinu, likvidnost koliko možeš trgovati, slippage koliko trade stvarno košta. Tablica slippagea "
    "za kupnje od $100 do $5.000 u bazenima od $10k do $1M, i što je FDV.", 6,
    "Market cap je cijena puta ponuda: veličina tokena. Likvidnost je novac u bazenu za trgovanje: koliko možeš kupiti ili "
    "prodati bez pomicanja cijene. Slippage je razlika između prikazane cijene i onoga što stvarno dobiješ. U bazenu od "
    "$10.000 kupnja od $1.000 dobije oko 17% manje tokena od prikazanog.",
    f"""
<h2>Market cap (tržišna kapitalizacija)</h2>
<p><b>Market cap</b> = cijena x ponuda u optjecaju. Pump.fun token ima milijardu tokena, pa cijena od $0,0001 znači
market cap od $100.000. Po market capu traderi uspoređuju tokene i postavljaju ciljeve: "na $100k je, zadnji sličan
otišao je na $5M".</p>
<p><b>FDV</b> (fully diluted valuation) je cijena x najveća moguća ponuda. Kod pump.fun tokena to je isto. Kod tokena
sa zaključanom ili budućom ponudom FDV može biti višestruko veći od market capa, a otključavanja mogu spustiti
cijenu.</p>

<h2>Likvidnost</h2>
<p><b>Likvidnost</b> je novac u bazenu s kojim trguješ, obično pola SOL, pola token. Token može imati market cap od $1M
i samo $20.000 likvidnosti: na papiru vrijedi milijun, a u praksi se može prodati tek mali dio prije nego što se cijena
sruši. Zato naš filtar odbija tokene s manje od $10.000 likvidnosti.</p>

<h2>Slippage</h2>
<p><b>Slippage</b> je razlika između cijene koju vidiš i cijene koju dobiješ. U standardnom bazenu cijena se pomiče po
krivulji dok kupuješ, pa veća kupnja u odnosu na bazen u prosjeku plati više. Tablica pokazuje koliko manje tokena
dobiješ nego po prikazanoj cijeni:</p>
{grid("Manje tokena od prikazane cijene, po iznosu kupnje i likvidnosti bazena",
      ["$100", "$500", "$1.000", "$5.000"],
      [("Bazen $10k", [2.0, 9.1, 16.7, 50.0]), ("Bazen $50k", [0.4, 2.0, 3.8, 16.7]),
       ("Bazen $250k", [0.1, 0.4, 0.8, 3.8]), ("Bazen $1M", [0.0, 0.1, 0.2, 1.0])],
      sub="Bazen s konstantnim produktom, pola likvidnosti na svakoj strani, prije naknada (oko 0,25-1%)", cap=50,
      lang="hr")}
{CALC.slippage("hr")}
<p>Prodaja na izlazu košta isto toliko. Kupnja i prodaja od $1.000 u bazenu od $10k izgubi otprilike trećinu novca
prije nego što se cijena uopće pomaknula.</p>

<h2>Tolerancija slippagea</h2>
<p>Aplikacije za swap traže da postaviš <b>toleranciju slippagea</b>: najviše što prihvaćaš. Preniska i trade ne prođe na
brzom tržištu; previsoka i botovi mogu "sendvičirati" tvoj nalog (kupe malo prije tebe i prodaju malo poslije). Kod
meme coina drži je na razini koju bi prihvatio kao cijeli trošak i prilagodi iznos bazenu.</p>

<h2>Čitaj sva tri zajedno</h2>
<ul>
<li>Market cap govori koliko prostora ima. Token od $50k može napraviti 20x; token od $500M rijetko.</li>
<li>Likvidnost govori možeš li izaći. Ciljaj barem $10k, više za veće tradeove.</li>
<li>Slippage govori koliko trade košta. Drži svaku kupnju ispod otprilike 2% likvidnosti bazena.</li>
</ul>
<p>Dalje: <a href=/hr/blog/kako-trgovati-meme-coinima>kako trgovati meme coinima</a> ili provjere u
<a href=/hr/blog/kako-prepoznati-rug-pull>kako prepoznati rug pull</a>.</p>
""")


# 11 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
EXCH_SRC = "HANFA registar, objave ESMA-e i nacionalnih regulatora, cjenici mjenjačnica; provjereno 1. 11. 2026."
FEE_SRC = "cjenici mjenjačnica i usporedba top7.hr od 28. 9. 2026.; naknade se mijenjaju, provjeri prije plaćanja"
HANFA_URL = ("https://www.hanfa.hr/registri/trziste-kriptoimovine/"
             "registar-drustava-ovlastenih-pruzati-usluge-povezane-s-kriptoimovinom/")
post(
    "best-crypto-exchanges-croatia", "najbolje-kripto-mjenjacnice-hrvatska", "Mjenjačnice",
    "Najbolje kripto mjenjačnice u Hrvatskoj i EU (2026.): s MiCA licencom, usporedba",
    "Najbolje kripto mjenjačnice u Hrvatskoj 2026.: MiCA licenca i naknade | MemeSonar",
    "Koje kripto mjenjačnice smiju raditi u Hrvatskoj 2026.? 5 hrvatskih tvrtki s HANFA licencom i 9 MiCA mjenjačnica "
    "uspoređenih po regulatoru, naknadama, podršci na hrvatskom i gotovini.", 9,
    "Od 1. srpnja 2026. svaka kripto mjenjačnica koja radi s hrvatskim klijentima mora imati MiCA licencu. U HANFA-inom "
    "registru je pet hrvatskih tvrtki (Electrocoin, Bitcoin Store, Kriptomat, Whitely, IN Kapital), a velike EU "
    "mjenjačnice (Kraken, Coinbase, Bitstamp, Bitpanda, Revolut, OKX, Bybit, Crypto.com, Bitvavo) svoju licencu "
    "prenose u Hrvatsku. Najjeftinije trgovanje: OKX, Bitstamp i Kraken Pro. Najlakše na hrvatskom: Electrocoin i "
    "Bitcoin Store.",
    f"""
<h2>Zašto je licenca sad važna</h2>
<p>EU uredba o tržištima kriptoimovine (<b>MiCA</b>) zamijenila je nacionalna pravila. Prijelazno razdoblje završilo je
<b>1. srpnja 2026.</b>: od tog dana tvrtka smije raditi s klijentima u Hrvatskoj samo uz MiCA licencu, od HANFA-e ili od
drugog EU regulatora uz prijenos (passporting) u Hrvatsku. Licenca znači kapitalne zahtjeve, odvojena sredstva
klijenata, rješavanje prigovora i regulatora kojem se možeš obratiti. Ne znači da su coini koje kupuješ sigurni; meme
coini ostaju meme coini.</p>
{stats([("5", "hrvatskih tvrtki u HANFA registru"), ("9+", "velikih EU mjenjačnica s MiCA licencom"),
        ("1. 7. 2026.", "kraj prijelaznog razdoblja")])}

<h2>Hrvatske mjenjačnice s HANFA licencom</h2>
<p>Ove tvrtke su u HANFA-inom registru društava ovlaštenih pružati usluge povezane s kriptoimovinom. Electrocoin je prvi
dobio punu MiCA licencu od HANFA-e.</p>
<div class=tw><table><thead><tr><th>Mjenjačnica</th><th>Tvrtka</th><th>Sjedište</th><th>Dobra za</th></tr></thead><tbody>
<tr><td><b>Electrocoin</b></td><td>Electrocoin d.o.o.</td><td>Zagreb</td><td>Podrška na hrvatskom 0-24, kupnja u eurima, plaćanje u trgovinama</td></tr>
<tr><td><b>Bitcoin Store</b></td><td>Digital Assets d.o.o.</td><td>Split</td><td>Poslovnice s gotovinom, bez naknada za uplatu i isplatu</td></tr>
<tr><td><b>Kriptomat</b></td><td>Bitblock d.o.o.</td><td>Zagreb</td><td>Jednostavna aplikacija na hrvatskom</td></tr>
<tr><td><b>Whitely</b></td><td>White Tech d.o.o.</td><td>Zagreb</td><td>Kupnja i čuvanje, podrška na hrvatskom</td></tr>
<tr><td><b>IN Kapital</b></td><td>IN Kapital d.o.o.</td><td>Sesvete</td><td>Zamjena kripta za eure</td></tr>
</tbody></table></div>
<p class=mut>Izvor: <a href="{HANFA_URL}" rel=nofollow>HANFA registar</a>, provjereno 1. 11. 2026.</p>

<h2>EU mjenjačnice s MiCA licencom</h2>
<p>Ove imaju MiCA licencu iz druge EU države i mogu raditi u Hrvatskoj preko prijenosa licence.</p>
<div class=tw><table><thead><tr><th>Mjenjačnica</th><th>Regulator</th><th>Datum licence</th></tr></thead><tbody>
<tr><td><b>Crypto.com</b></td><td>MFSA (Malta)</td><td>27. 1. 2025.</td></tr>
<tr><td><b>OKX</b></td><td>MFSA (Malta)</td><td>27. 1. 2025.</td></tr>
<tr><td><b>Bitpanda</b></td><td>BaFin (Njemačka), i Austrija</td><td>2025.</td></tr>
<tr><td><b>Bitstamp</b></td><td>CSSF (Luksemburg)</td><td>15. 5. 2025.</td></tr>
<tr><td><b>Bybit</b></td><td>FMA (Austrija)</td><td>28. 5. 2025.</td></tr>
<tr><td><b>Coinbase</b></td><td>CSSF (Luksemburg)</td><td>20. 6. 2025.</td></tr>
<tr><td><b>Kraken</b></td><td>Središnja banka Irske</td><td>25. 6. 2025.</td></tr>
<tr><td><b>Bitvavo</b></td><td>AFM (Nizozemska)</td><td>26. 6. 2025.</td></tr>
<tr><td><b>Revolut</b></td><td>CySEC (Cipar)</td><td>2025.</td></tr>
</tbody></table></div>
<p>Binance nije imao MiCA licencu kad smo provjerili (1. 11. 2026.), pa su mu usluge za korisnike u EU ograničene. Prije
uplate uvijek provjeri registar samog regulatora; stranica na kojoj piše "regulirano" nije dokaz.</p>

<h2>Koliko kupnja košta</h2>
<p>Mjenjačnice naplaćuju na dva načina: vidljivu <b>naknadu za trgovanje</b> na platformi s knjigom naloga (Kraken Pro,
Bitstamp, OKX) ili <b>spread</b> skriven u cijeni na jednostavnom gumbu "Kupi". Spread je obično veći trošak. Grafikon
pokazuje najniži objavljeni trošak kupnje:</p>
{B("Najniži objavljeni trošak kupnje kripta",
   [("OKX (knjiga naloga, taker)", 0.10, "maker 0,08%"),
    ("Bitstamp (knjiga naloga, taker)", 0.40, "jednostavna kupnja: spread oko 1,8% plus do 0,5%"),
    ("Kraken Pro (taker)", 0.40, "jednostavna kupnja: 1% plus spread"),
    ("Bitcoin Store (spread)", 0.50, "spread 0,5-5% ovisno o coinu i iznosu"),
    ("Revolut (standardni paket)", 1.49, "plus 0-3% spreada; 0,99% na Premium/Metal"),
    ("Electrocoin (Trade račun)", 1.75, "oko 2% pri kupnji na webu")],
   sub="Postotak iznosa, prije naknada za uplatu i isplatu", fmt="pct2", hl=(0, 1, 2), source=FEE_SRC)}
<div class=tw><table><thead><tr><th>Mjenjačnica</th><th>Uplata eura</th><th>Isplata eura</th><th>Podrška na hrvatskom</th></tr></thead><tbody>
<tr><td>Kraken</td><td>SEPA besplatno</td><td>1 €</td><td>Ne</td></tr>
<tr><td>Bitstamp</td><td>SEPA besplatno; kartica 4%</td><td>3 €</td><td>Ne</td></tr>
<tr><td>Revolut</td><td>S Revolut računa</td><td>Besplatno unutar Revoluta</td><td>Da (aplikacija)</td></tr>
<tr><td>Electrocoin</td><td>Bankovni prijenos, trgovine</td><td>0,50 € (najmanje 5 €)</td><td>Da, 0-24</td></tr>
<tr><td>Bitcoin Store</td><td>Besplatno, gotovina u poslovnicama</td><td>Besplatno</td><td>Da</td></tr>
</tbody></table></div>
<p class=mut>Naknade iz cjenika mjenjačnica i top7.hr (28. 9. 2026.). Često se mijenjaju: provjeri cjenik na dan kupnje.</p>

<h2>Koju odabrati</h2>
<ul>
<li><b>Želiš najmanji trošak:</b> platforma s knjigom naloga (OKX, Bitstamp, Kraken Pro). Koristi limit nalog i preskoči
jednostavni gumb "Kupi".</li>
<li><b>Želiš hrvatski jezik i broj telefona:</b> Electrocoin ili Bitcoin Store. Plaćaš više po kupnji, ali podrška i
gotovina su lokalni.</li>
<li><b>Već koristiš Revolut:</b> najbrži početak, ali plaćaš 1,49% plus spread, što se zbraja kod čestih kupnji.</li>
<li><b>Želiš kupiti Solana meme coine:</b> nijedna od ovih ne nudi većinu meme coina. Kupi <b>SOL</b> na bilo kojoj,
pošalji ga na Solana mreži u svoj novčanik i tamo zamijeni. Taj put je u vodiču
<a href=/hr/blog/kako-kupiti-solana-meme-coine>kako kupiti Solana meme coine</a>, a svaki coin ima svoju stranicu, npr.
<a href=/hr/kako-kupiti/bonk>kako kupiti Bonk</a>.</li>
</ul>

<h2>Prije uplate</h2>
<ul>
<li>Pronađi tvrtku u <a href="{HANFA_URL}" rel=nofollow>HANFA registru</a> ili u ESMA registru MiCA pružatelja.</li>
<li>Uključi prijavu u dva koraka s aplikacijom, ne SMS-om.</li>
<li>Prvo napravi malu probnu isplatu i provjeri da se mreža (npr. Solana) poklapa s novčanikom.</li>
<li>Nikad nikome ne daj frazu za oporavak. Nijedna mjenjačnica, podrška ni aplikacija je nikad ne treba.</li>
<li>U Hrvatskoj se dobit od kripta oporezuje (12% porez na kapitalnu dobit; što držiš dulje od dvije godine je
oslobođeno). Čuvaj izvode s mjenjačnice; vidi <a href=/hr/blog/porez-na-kriptovalute>porez na kriptovalute</a>. Želiš
plaćati kriptom u trgovinama? Usporedi <a href=/hr/blog/kripto-kartice-hrvatska>kripto kartice</a>; kupnja preko firme
je u članku <a href=/hr/blog/ulaganje-firme-u-kriptovalute>može li firma ulagati u kriptovalute</a>.</li>
</ul>
<p class=mut>Na ovoj stranici nemamo affiliate linkova ni plaćanja od mjenjačnica. Izvor: {EXCH_SRC}</p>
""")


# 12 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "how-to-buy-solana-meme-coins", "kako-kupiti-solana-meme-coine", "Vodiči",
    "Kako kupiti Solana meme coine: siguran put, korak po korak",
    "Kako kupiti Solana meme coine (2026.): vodič korak po korak | MemeSonar",
    "Kako sigurno kupiti Solana meme coine: kupi SOL na licenciranoj mjenjačnici, prebaci ga u Phantom, zamijeni na "
    "Jupiteru i provjeri token prije kupnje. Korak po korak, sa stvarnim brojkama.", 6,
    "Kupi SOL na mjenjačnici s MiCA licencom, pošalji ga na Solana mreži u novčanik kao što je Phantom, pa na Jupiteru "
    "zamijeni SOL za meme coin koristeći točnu adresu ugovora. Prije swapa provjeri likvidnost, mint i freeze authority "
    "i najveće holdere: od novih pump.fun tokena kupljenih 15 minuta nakon lansiranja samo se 0,8% ikad udvostručilo.",
    f"""
<h2>Put u jednoj rečenici</h2>
<p>Euro → <b>SOL</b> na licenciranoj mjenjačnici → tvoj Solana novčanik → swap na <b>DEX</b>-u (Jupiter) → meme coin.
Gotovo nijedan Solana meme coin nije na reguliranoj mjenjačnici, pa se zamjena radi na blockchainu.</p>

<h2>1. Kupi SOL na licenciranoj mjenjačnici</h2>
<p>Odaberi mjenjačnicu s MiCA licencom. Usporedili smo ih u članku
<a href=/hr/blog/najbolje-kripto-mjenjacnice-hrvatska>najbolje kripto mjenjačnice u Hrvatskoj i EU</a>: najjeftinije su
platforme s knjigom naloga (oko 0,1-0,4% po tradeu); hrvatske koštaju više, ali imaju lokalnu podršku.</p>

<h2>2. Instaliraj novčanik i čuvaj frazu</h2>
<p>Instaliraj Phantom ili Solflare (vidi <a href=/hr/najbolji-kripto-alati/kripto-novcanici>najbolje kripto
novčanike</a>). Zapiši frazu za oporavak od 12 ili 24 riječi na papir. Tko ima frazu, ima novac; nijedna stranica,
podrška ni bot je nikad ne treba.</p>

<h2>3. Pošalji SOL u svoj novčanik</h2>
<p>Kopiraj adresu novčanika, na mjenjačnici odaberi mrežu <b>Solana</b> i prvo pošalji mali probni iznos. Ostavi oko
0,02 SOL u novčaniku za naknade mreže.</p>

<h2>4. Pronađi pravu adresu ugovora</h2>
<p>Lažni tokeni kopiraju ime i logo. Uzmi adresu s pouzdane stranice, npr. naših stranica coina kao što je
<a href=/hr/coin/bonk>Bonk</a> ili <a href=/hr/solana-meme-coini>top 100 Solana meme coina</a>, i provjeri da se simbol,
logo i market cap poklapaju.</p>

<h2>5. Provjeri token prije swapa</h2>
{B("Novi pump.fun tokeni koji su se kasnije udvostručili",
   [("15 minuta nakon lansiranja (nasumično)", 0.8, "6.104 tokena"),
    ("Pri prelasku u DEX bazen", 9.5, "2.784 tokena"),
    ("Prvi prelazak market capa od $100k", 24.0, "217 tokena")],
   sub="Kupljeno u tom trenutku, cijena je kasnije dosegla barem 2x", hl=(2,), source=RETRO)}
<ul>
<li><b>Likvidnost</b> barem $10k, a tvoja kupnja ispod otprilike 2% nje (vidi
<a href=/hr/blog/market-cap-likvidnost-slippage>market cap, likvidnost i slippage</a>).</li>
<li><b>Mint authority</b> i freeze authority isključeni.</li>
<li>Top 10 holdera ispod otprilike 35%, developer ispod 5%.</li>
</ul>
<p>Svaki coin iz našeg top 100 ima automatsku provjeru, npr. <a href=/hr/provjera/bonk>je li Bonk siguran?</a></p>

<h2>6. Zamijeni na Jupiteru</h2>
<p>Otvori jup.ag (ili swap u Phantomu), spoji novčanik, odaberi SOL → zalijepi adresu ugovora, upiši iznos i toleranciju
<b>slippagea</b> koju možeš prihvatiti, pa potvrdi. Postavke su u našem
<a href=/hr/blog/kako-koristiti-jupiter-swap>vodiču za Jupiter swap</a>.</p>

<h2>7. Planiraj izlaz prije kupnje</h2>
<p>Odluči gdje uzimaš dobit, a gdje režeš gubitak, i zapiši to. Meme coini se pomaknu 50% u sat vremena; bez plana
odluku donose emocije. Vidi <a href=/hr/blog/kako-trgovati-meme-coinima>kako trgovati meme coinima</a>.</p>
""")


# 13 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "how-to-use-jupiter-swap", "kako-koristiti-jupiter-swap", "Vodiči",
    "Kako koristiti Jupiter swap na Solani: postavke koje štede novac",
    "Kako koristiti Jupiter swap: slippage, priority fee, limit nalozi | MemeSonar",
    "Praktični vodič za Jupiter swap: spajanje novčanika, provjera tokena, postavke slippagea i priority feeja, limit "
    "nalozi i DCA te greške koje najviše koštaju.", 6,
    "Jupiter (jup.ag) je agregator swapova na Solani: dijeli tvoj nalog po bazenima da dobiješ najbolju cijenu. Spoji "
    "novčanik, odaberi SOL i zalijepi adresu ugovora tokena, drži kupnju malom u odnosu na likvidnost bazena, postavi "
    "slippage koji prihvaćaš kao cijeli trošak i koristi limit naloge kad ti se ne žuri.",
    f"""
<h2>Što je Jupiter</h2>
<p>Jupiter nije mjenjačnica s vlastitom knjigom naloga; to je <b>agregator</b>. Gleda bazene na Solana <b>DEX</b>-ovima
(Raydium, Orca, Meteora, pump.fun bazeni i drugi) i vodi tvoj trade najjeftinijim putem, ponekad podijeljen na više
bazena. Coini su cijelo vrijeme u tvom novčaniku.</p>

<h2>Korak po korak</h2>
<ol>
<li>Otvori <b>jup.ag</b> (upiši sam; lažne Jupiter stranice čest su trik za pražnjenje novčanika) i spoji Phantom ili
Solflare.</li>
<li>"You pay": SOL ili USDC. "You receive": zalijepi <b>adresu ugovora</b> tokena, ne ime.</li>
<li>Pogledaj oznake upozorenja: Jupiter označava neprovjerene tokene. Neprovjeren nije dokaz prevare, ali prvo pogledaj
<a href=/hr/provjera>provjeru ruga</a>.</li>
<li>Prije potvrde pogledaj redak "price impact".</li>
<li>Potvrdi u novčaniku i pročitaj što novčanik kaže da potpisuješ.</li>
</ol>

<h2>Slippage i price impact</h2>
<p><b>Price impact</b> je koliko tvoj vlastiti trade pomakne bazen; tolerancija <b>slippagea</b> je koliko lošije od
ponude prihvaćaš prije nego trade propadne. U tankom bazenu sam impact može biti velik:</p>
{grid("Price impact po iznosu kupnje i likvidnosti bazena",
      ["$100", "$500", "$1.000", "$5.000"],
      [("Bazen $10k", [2.0, 9.1, 16.7, 50.0]), ("Bazen $50k", [0.4, 2.0, 3.8, 16.7]),
       ("Bazen $250k", [0.1, 0.4, 0.8, 3.8]), ("Bazen $1M", [0.0, 0.1, 0.2, 1.0])],
      sub="Bazen s konstantnim produktom, pola likvidnosti na svakoj strani, prije naknada", cap=50, lang="hr")}
{CALC.slippage("hr")}
<p>Jupiterov automatski slippage je u redu za likvidne coine. Kod svježih tokena vrlo visoka tolerancija privlači
"sandwich" botove koji kupe tik prije tebe i prodaju tik poslije.</p>

<h2>Priority fee</h2>
<p>Kad je Solana zagušena, mala dodatna naknada (priority fee) brže ubacuje tvoju transakciju. Za običan swap dovoljna
je zadana; plaćanje više pomaže samo u prvim minutama lansiranja, a tad je i rizik najveći.</p>

<h2>Limit nalozi i DCA</h2>
<p>Jupiter nudi i <b>limit naloge</b> (kupi ili prodaj kad cijena dođe do tvoje razine) i ponavljajuće kupnje
(<a href=/hr/blog/sto-je-dca>DCA</a>). Limit nalozi sprječavaju jurenje za pumpama; DCA razvlači jednu odluku kroz
vrijeme.</p>

<h2>Greške koje najviše koštaju</h2>
<ul>
<li>Traženje tokena po imenu i odabir kopije s istim logom.</li>
<li>Kupnja više od otprilike 2% likvidnosti bazena odjednom.</li>
<li>Odobravanje transakcije na stranici do koje si došao preko linka iz poruke.</li>
<li>Potrošiti sav SOL i nemati ništa za naknadu pri prodaji.</li>
</ul>
<p>Kako uopće doći do SOL-a: <a href=/hr/blog/najbolje-kripto-mjenjacnice-hrvatska>licencirane mjenjačnice u Hrvatskoj i
EU</a>.</p>
""")


# 14 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "what-is-a-pump-and-dump", "sto-je-pump-and-dump", "Rugovi",
    "Što je pump and dump u kriptu? Kako radi i kako ga prepoznati",
    "Što je pump and dump u kriptu? Znakovi i primjeri iz podataka | MemeSonar",
    "Pump and dump je dogovoreno guranje cijene nakon kojeg insajderi prodaju kupcima. Kako radi kod Solana meme coina, "
    "znakovi upozorenja i što o tome pokazuju naši podaci.", 6,
    "Pump and dump je kad grupa rano kupi token, napuhne cijenu hypeom (plaćeni pozivi, grupe na chatu, lažni volumen) "
    "i proda ljudima koji dođu kasno. Znakovi: nekoliko novčanika drži većinu ponude, bundlane kupnje pri lansiranju, "
    "puno poziva u par minuta s računa koji se pojave samo za taj coin i volumen koji nestane nakon vrha.",
    f"""
<h2>Kako radi</h2>
<ol>
<li><b>Skupljanje:</b> insajderi kupe jeftino, često u istom bloku kao lansiranje (<b>bundlovi</b> i
<b>snajperi</b>).</li>
<li><b>Pumpa:</b> stvaraju pažnju: plaćeni postovi influencera, Telegram "alpha" grupe, botovi koji trguju sami sa sobom
da napuhnu volumen.</li>
<li><b>Dump:</b> novi kupci guraju cijenu gore; insajderi im prodaju. Graf pada brže nego što je rastao.</li>
</ol>
<p>Za razliku od <a href=/hr/blog/kako-prepoznati-rug-pull>rug pulla</a>, likvidnost obično ostaje; token se samo vrati
blizu nule jer je jedina stvarna potražnja bio hype.</p>

<h2>Što pokazuju naši podaci</h2>
<p>Jako bundlani tokeni češće pumpaju (25,5% je doseglo 2x kad je više od 20% ponude bundlano, naspram 3,6% ispod 2%),
i baš to privlači kasne kupce. Ali pad s vrha je najdublji:</p>
{B("Tipičan pad s najviše cijene, po bundlanom udjelu ponude",
   [("2-10% bundlano", 17, ""), ("10-20%", 35, ""), ("Više od 20%", 54, "insajderi prodaju u pumpu")],
   sub="Medijan najvećeg pada u prvim satima, %", hl=(2,), source=RETRO)}
<p>Snajperi pokazuju isti obrazac: gdje su snajperi uzeli više od 30% ponude, medijan pada s vrha bio je 58%.</p>
<p>Ni puno istovremenih poziva influencera nije uvijek organsko: grupe od tri ili više <b>KOL</b> poziva u 15 minuta
dosegle su 2x u 59% slučajeva naspram 33% inače, ali neke grupe su isti ljudi s više računa. Zato grupiramo
influencere (<a href=/hr/blog/grupiranje-influencera>kako radi grupiranje influencera</a>) i isključujemo bot račune.</p>

<h2>Znakovi upozorenja</h2>
<ul>
<li>Top 10 novčanika drži više od otprilike 35% ponude ili developer više od 5%.</li>
<li>Puno kupnji u prvom bloku iz novčanika financiranih iz istog izvora.</li>
<li>Nalet postova s računa koji se pojavljuju samo za ovaj coin.</li>
<li>Pritisak "zadnja prilika", odbrojavanja, zajamčeni ciljevi.</li>
<li>Volumen i holderi koji se uruše par sati nakon vrha.</li>
</ul>
<p>Svaki coin iz našeg top 100 ima automatsku provjeru tih brojki, npr. <a href=/hr/provjera/wif>je li WIF siguran?</a></p>

<h2>Je li to nezakonito?</h2>
<p>U EU MiCA izričito zabranjuje manipulaciju tržištem kriptoimovine, uključujući širenje obmanjujućih informacija radi
pomicanja cijene. Provedba protiv anonimnih projekata na blockchainu je teška, pa je u praksi zaštita na tebi: mali
iznos, jasan izlaz i nikakva kupnja samo zato što chat kaže "sad".</p>
""")


# 15 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
CARD_SRC = "stranice i cjenici izdavatelja kartica, jeangalea.com (6. 10. 2026.), cardpilled.com (provjereno 22. 9. 2026.)"
TAX_SRC = ("mišljenje Porezne uprave 410-01/17-08/29 (19. 3. 2018.), obavijest Porezne uprave o JOPPD-u, "
           "top7.hr (29. 9. 2026.)")
post(
    "crypto-cards-croatia", "kripto-kartice-hrvatska", "Kartice",
    "Kripto kartice u Hrvatskoj (2026.): koje rade, koliko koštaju i porezna zamka",
    "Najbolje kripto kartice u Hrvatskoj 2026.: Revolut, Crypto.com, Bybit | MemeSonar",
    "Koje kripto debitne kartice možeš koristiti u Hrvatskoj 2026.? Revolut, Crypto.com, Bybit EU, Bitpanda, Kraken i "
    "OKX uspoređeni po licenci, naknadama i cashbacku, i zašto je svako plaćanje prodaja kripta.", 7,
    "Hrvatska je u europodručju i EGP-u, pa ovdje rade EU kripto kartice: Revolutova kripto kartica, Crypto.com Visa, "
    "Bybit EU kartica, Bitpanda Card, Krakenova Krak kartica i OKX kartica, sve od tvrtki s MiCA licencom. Besplatne "
    "razine daju 0-1% cashbacka; veće nagrade traže staking ili pretplatu. Zamka: svako plaćanje karticom prodaje kripto "
    "za eure, što se za porez računa kao prodaja (12% na dobit ako si ga držao kraće od dvije godine).",
    f"""
<h2>Kako radi kripto kartica</h2>
<p>Kripto kartica je obična Visa ili Mastercard debitna kartica. Kad platiš, izdavatelj u tom trenutku proda potreban
iznos tvog kripta (ili stablecoina) za eure i trgovac dobije eure. Trgovac nikad ne vidi kripto, pa kartica radi
svugdje gdje se primaju kartice, uključujući hrvatske trgovine i bankomate.</p>
<p>U toj zamjeni se skriva trošak: <b>spread</b> ili naknada za konverziju od otprilike 0-1% na svako plaćanje, uz
eventualnu mjesečnu naknadu.</p>

<h2>Kartice koje možeš dobiti u Hrvatskoj</h2>
<p>Navodimo samo kartice tvrtki s EU MiCA licencom (vidi <a href=/hr/blog/najbolje-kripto-mjenjacnice-hrvatska>koje
mjenjačnice imaju licencu</a>). Uvjeti se često mijenjaju; prije narudžbe provjeri cjenik izdavatelja.</p>
<div class=tw><table><thead><tr><th>Kartica</th><th>Tvrtka / licenca</th><th>Mjesečna naknada</th><th>Cashback na besplatnoj razini</th><th>Dobro je znati</th></tr></thead><tbody>
<tr><td><b>Revolut kripto kartica</b></td><td>Revolut, MiCA preko CySEC-a</td><td>Tvoj Revolut paket</td><td>Nema</td><td>Virtualna od 2025., fizička od svibnja 2026.; konverzija pri plaćanju, naknade za pravednu upotrebu ovisno o paketu</td></tr>
<tr><td><b>Crypto.com Visa</b></td><td>Crypto.com, MiCA preko MFSA (Malta)</td><td>0 € (Midnight Blue)</td><td>Nema</td><td>1,5% na Ruby Steel (3,99 €/mj. ili zaključani CRO); najviše razine traže veliki ulog u CRO</td></tr>
<tr><td><b>Bybit EU kartica</b></td><td>Bybit EU GmbH, MiCA preko FMA (Austrija)</td><td>0 €</td><td>1% (u BTC-u)</td><td>Mastercard; veće stope samo za VIP razine, s mjesečnim limitom</td></tr>
<tr><td><b>Bitpanda Card</b></td><td>Bitpanda, MiCA</td><td>0 €</td><td>Do 1% (u kriptu kojim plaćaš)</td><td>Visa, europodručje</td></tr>
<tr><td><b>Krak kartica (Kraken)</b></td><td>Kraken, MiCA preko Središnje banke Irske</td><td>0 €</td><td>Do 2% (uz uvjete)</td><td>UK i EGP</td></tr>
<tr><td><b>OKX kartica</b></td><td>OKX, MiCA preko MFSA (Malta)</td><td>0 €</td><td>2%+ u stablecoinu, mjesečni limit</td><td>Troši saldo stablecoina, ne ostale coine</td></tr>
</tbody></table></div>
<p class=mut>Više nije dostupna u EGP-u: Binance Card (ukinuta u prosincu 2023.). Izvori: {CARD_SRC}.</p>
{B("Cashback na besplatnoj razini",
   [("Krak (Kraken)", 2.0, "do, uz uvjete"), ("Bybit EU kartica", 1.0, "svi korisnici, bez mjesečnog limita"),
    ("Bitpanda Card", 1.0, "do, isplata u kriptu kojim plaćaš"), ("Crypto.com Visa (Midnight Blue)", 0, "1,5% od 3,99 €/mj."),
    ("Revolut kripto kartica", 0, "nema cashbacka")],
   sub="Postotak svakog plaćanja, prije naknada za konverziju; cashback se često isplaćuje u tokenu kojem se cijena mijenja",
   fmt="pct2", hl=(0, 1, 2), vmax=2.5, source=CARD_SRC)}

<h2>Porezna zamka: svako plaćanje je prodaja</h2>
<p>Za hrvatski porez, kad izdavatelj kartice zamijeni tvoj kripto za eure, to je isto kao da si ga ti prodao. Ako si
coine kupio prije manje od dvije godine i vrijede više nego što si platio, svako plaćanje stvara malu oporezivu dobit
(12% na dobit, prijava jednom godišnje do kraja veljače). Coini koje držiš dulje od dvije godine su oslobođeni.</p>
{stats([("1.000 €", "BTC kupljen u ožujku 2026."), ("1.500 €", "potrošeno kripto karticom u listopadu 2026."),
        ("60 €", "porez: 12% od 500 € dobiti")])}
<p>Plaćanje stablecoinom koji si kupio za eure stvara gotovo nikakvu dobit. Naš <a href=/hr/blog/porez-na-kriptovalute>vodič
za porez na kriptovalute</a> ima sva pravila, a svaka aplikacija za karticu daje izvoz transakcija; čuvaj ga.</p>

<h2>Koju odabrati</h2>
<ul>
<li><b>Već koristiš Revolut:</b> najjednostavnije, bez novog računa, ali bez cashbacka.</li>
<li><b>Želiš cashback bez stakinga:</b> Bybit EU (ravno 1%) ili Bitpanda (do 1%).</li>
<li><b>Želiš trošiti stablecoine:</b> OKX ili kartica koja dopušta USDC kao izvor, što pojednostavljuje porez.</li>
<li><b>Držiš dugoročno:</b> ne troši coine koje planiraš držati dulje od dvije godine; rano trošenje pretvara
neoporezivu dobit u oporezivu.</li>
</ul>
<p class=mut>Nemamo affiliate linkova ni plaćanja od izdavatelja kartica. Nije financijski ni porezni savjet.</p>
""")


# 16 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "crypto-tax-croatia", "porez-na-kriptovalute", "Porez",
    "Porez na kriptovalute u Hrvatskoj (2026.): 12%, pravilo dvije godine i prijava JOPPD-om",
    "Porez na kriptovalute 2026.: stopa 12%, pravilo dvije godine, JOPPD | MemeSonar",
    "Kako se oporezuju kriptovalute u Hrvatskoj: 12% na dobit, neoporezivo nakon dvije godine, zamjena kripta za kripto "
    "se ne oporezuje, gubici unutar godine i prijava JOPPD-om do kraja veljače. S primjerima.", 8,
    "U Hrvatskoj se dobit od prodaje kripta oporezuje po stopi od 12% (bez prireza od 2024.), samo kad ga zamijeniš za "
    "eure ili drugi novac i samo ako si ga držao kraće od dvije godine. Zamjena jednog coina za drugi se ne oporezuje. "
    "Godišnju neto dobit računaš sam (FIFO, minus naknade i gubici iste godine), prijaviš je na obrascu JOPPD u "
    "ePoreznoj i platiš do kraja veljače sljedeće godine.",
    f"""
<h2>Pravila u jednoj tablici</h2>
<div class=tw><table><thead><tr><th>Pitanje</th><th>Odgovor za fizičke osobe</th></tr></thead><tbody>
<tr><td>Vrsta poreza</td><td>Dohodak od kapitala (kapitalni dobici)</td></tr>
<tr><td>Stopa</td><td><b>12%</b> na dobit od 2024.; bez prireza. Prije 2024.: 10% plus prirez</td></tr>
<tr><td>Držano dulje od dvije godine</td><td>Neoporezivo, bez obzira na iznos</td></tr>
<tr><td>Kripto zamijenjen za kripto</td><td>Ne oporezuje se pri zamjeni; dobit se računa kad zamijeniš za novac</td></tr>
<tr><td>Kripto prodan za eure ili potrošen kripto karticom</td><td>Oporezivo ako postoji dobit</td></tr>
<tr><td>Samo kupnja ili držanje</td><td>Ne oporezuje se</td></tr>
<tr><td>Gubici</td><td>Umanjuju dobit samo u istoj kalendarskoj godini; ne prenose se</td></tr>
<tr><td>Metoda troška</td><td>FIFO, svaki coin zasebno; naknade mjenjačnice i mreže umanjuju dobit</td></tr>
<tr><td>Obrazac i rok</td><td>JOPPD u ePoreznoj, prijava i plaćanje do kraja veljače za prethodnu godinu</td></tr>
<tr><td>Mali iznosi</td><td>Ne prijavljuje se ako bi porez bio 2 € ili manje (dobit do oko 16,70 €)</td></tr>
</tbody></table></div>
<p class=mut>Izvori: {TAX_SRC}. Mišljenje iz 2018. starije je od kasnijih izmjena zakona (stopa, prirez), pa za svoj
slučaj provjeri aktualne upute Porezne uprave ili poreznog savjetnika.</p>

<h2>Primjeri</h2>
{B("Porez na dobit od 5.000 €",
   [("Prodano za eure nakon 8 mjeseci", 600, "12% od 5.000 €"),
    ("Prodano za eure nakon 26 mjeseci", 0, "držano dulje od dvije godine: oslobođeno"),
    ("Zamijenjeno za drugi coin, nije isplaćeno", 0, "još nisi primio novac"),
    ("5.000 € dobiti i 2.000 € gubitka iste godine", 360, "12% od 3.000 € neto dobiti")],
   sub="Fizičke osobe, porezni rezidenti Hrvatske", fmt="eur", hl=(0, 3), source=TAX_SRC)}

{CALC.tax("hr")}

<h2>Zamjene: pravilo važno za meme coine</h2>
<p>Prema mišljenju Porezne uprave zamjena jedne kriptovalute za drugu ne stvara oporezivu dobit u tom trenutku, jer
nema novčanog toka. Njihov primjer: 10 BTC kupljenih za 6.000 $, zamijenjenih za ETH, kasnije prodanih za 35.400 $:
oporeziva dobit od 29.400 $ računa se kad se ETH proda za novac. Za Solana tradera to znači da SOL u meme coin i natrag u
SOL nije oporezivo dok ne isplatiš u eure, ali evidencija ti svejedno treba da tad izračunaš dobit.</p>

<h2>Kako izračunati dobit</h2>
<ol>
<li>Izvezi svaku kupnju, prodaju i zamjenu sa svake mjenjačnice i novčanika za tu godinu.</li>
<li>Za svaku prodaju za novac uzmi trošak najstarijih coina prvo (<b>FIFO</b>).</li>
<li>Dobit = iznos prodaje minus trošak minus naknade. Zbroji sve dobiti, oduzmi sve gubitke iste godine.</li>
<li>Preskoči coine držane dulje od dvije godine; oslobođeni su.</li>
<li>Porez = 12% neto dobiti.</li>
</ol>

<h2>Kako predati JOPPD</h2>
<ol>
<li>Prijavi se u <b>ePoreznu</b> (vjerodajnicama e-Građana) i otvori novi obrazac JOPPD.</li>
<li>Ispuni ga za ukupne kapitalne dobitke prethodne godine, s datumom 31. prosinca te godine.</li>
<li>Predaj i uplati porez na navedeni račun do kraja veljače (za dobit iz 2026.: do kraja veljače 2027.).</li>
<li>Čuvaj izvoze i svoj izračun; Porezna ih može zatražiti.</li>
</ol>
<p>Od 2026. EU pravila (DAC8) obvezuju pružatelje kripto usluga da prikupljaju i šalju poreznim upravama podatke o
transakcijama klijenata, pa će provjere postati uobičajene.</p>

<h2>Drugi dohodak</h2>
<p>Kripto zarađen rudarenjem, zadacima ili promocijama nije kapitalni dobitak: Porezna uprava ga tretira kao drugi
dohodak, koji se drukčije oporezuje, a redovito rudarenje kao posao može tražiti registriranu djelatnost. Za nagrade od
stakinga nema objavljenog mišljenja; pitaj prije prijave. Za tvrtke su pravila potpuno drukčija, vidi
<a href=/hr/blog/ulaganje-firme-u-kriptovalute>može li firma ulagati u kriptovalute</a>.</p>
<p class=mut>Nije porezni savjet. Pravila i obrasci se mijenjaju; provjeri s Poreznom upravom ili poreznim savjetnikom.</p>
""")


# 17 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
CO_SRC = ("Zakon o porezu na dobit (10%/18%), porez na dividendu 12% od 2024., HSFI 5/10 i MRS 38/2 prema Kopun Group i "
          "Data-Link Unija, mišljenje Porezne uprave o PDV-u (2015.)")
post(
    "company-crypto-investment-croatia", "ulaganje-firme-u-kriptovalute", "Poslovanje",
    "Može li firma ulagati u kriptovalute u Hrvatskoj? d.o.o., obrt, porez i knjiženje",
    "Može li d.o.o. ulagati u kriptovalute? Porez, knjiženje, banke | MemeSonar",
    "Da, hrvatski d.o.o. smije kupiti kripto vlastitim novcem. Kako se knjiži (HSFI 5 ili 10), oporezuje (10% ili 18% "
    "porez na dobit, bez pravila dvije godine), PDV, banke i kad je privatno držanje jeftinije.", 8,
    "Hrvatski d.o.o. smije ulagati vlastiti novac u kripto; MiCA licenca ne treba osim ako drugima pruža kripto usluge. "
    "Kripto knjiži kao nematerijalnu imovinu (dugoročno) ili zalihe (trgovanje), po trošku, i plaća porez na dobit "
    "(10% ili 18%) na dobit kad proda. Nema oslobođenja nakon dvije godine, a isplata dobiti kao dividende dodaje 12%, "
    "pa je za dugoročno držanje privatno vlasništvo obično jeftinije.",
    f"""
<h2>Je li dopušteno?</h2>
<p>Da. MiCA regulira tvrtke koje drugima pružaju kripto usluge (mjenjačnice, čuvanje, savjetovanje). Tvrtka koja kupuje
kripto za vlastitu bilancu je ulagač, kao kod kupnje dionica, i ne treba licencu. Treba licenciranu mjenjačnicu (vidi
<a href=/hr/blog/najbolje-kripto-mjenjacnice-hrvatska>licencirane mjenjačnice</a>) koja otvara poslovne račune; velike
(Kraken, Coinbase, Bitstamp, Bitpanda) imaju poslovno otvaranje računa uz dokumente tvrtke i provjeru stvarnih
vlasnika.</p>

<h2>Kako se knjiži</h2>
<div class=tw><table><thead><tr><th>Namjena</th><th>Standard</th><th>Vrednovanje</th><th>Cijena padne ispod troška</th><th>Cijena raste</th></tr></thead><tbody>
<tr><td>Dugoročno držanje</td><td>Nematerijalna imovina: HSFI 5 / MRS 38</td><td>Trošak (ili model revalorizacije)</td><td>Rashod umanjenja, porezno nepriznat do prodaje</td><td>Ništa do prodaje (model troška)</td></tr>
<tr><td>Trgovanje</td><td>Zalihe: HSFI 10 / MRS 2</td><td>Niži od troška i neto utržive vrijednosti</td><td>Otpis, porezno nepriznat do prodaje</td><td>Ostaje po trošku</td></tr>
</tbody></table></div>
<p>Kripto za računovodstvo nije novac ni financijska imovina. Odaberi politiku prije prve kupnje, čuvaj svaku potvrdu
mjenjačnice i koristi FIFO za trošak prodanog.</p>

<h2>Kako se oporezuje</h2>
<ul>
<li><b>Porez na dobit</b> na dobit pri prodaji: 10% ako su godišnji prihodi tvrtke do 1 milijun €, 18% iznad.</li>
<li><b>Nema oslobođenja nakon dvije godine.</b> To pravilo vrijedi samo za fizičke osobe.</li>
<li><b>PDV:</b> kupnja i prodaja kripta za novac oslobođena je PDV-a (Porezna uprava 2015., u skladu s presudom Suda EU
Hedqvist). Ako tvrtka prima kripto kao plaćanje za svoju robu ili usluge, sama prodaja podliježe PDV-u kao i inače.</li>
<li><b>Isplata vlasniku:</b> dobit isplaćena kao dividenda oporezuje se ponovno s 12%.</li>
</ul>
{B("Porez na 10.000 € kripto dobiti koja završi kod vlasnika",
   [("Privatno, dulje od dvije godine", 0, "oslobođeno"),
    ("Privatno, kraće od dvije godine", 1200, "12% porez na kapitalnu dobit"),
    ("d.o.o. s prihodom do 1 mil. €, pa isplata", 2080, "10% porez na dobit, pa 12% na dividendu"),
    ("d.o.o. s prihodom iznad 1 mil. €, pa isplata", 2784, "18% porez na dobit, pa 12% na dividendu")],
   sub="Pojednostavljeno: bez drugih prihoda i troškova", fmt="eur", hl=(0, 1), source=CO_SRC)}

{CALC.company("hr")}

<h2>Kad firma ipak ima smisla</h2>
<ul>
<li>Novac je već u firmi i porez na dividendu bi ionako platio da ga izvučeš.</li>
<li>Firma aktivno trguje i može prebiti dobit s poslovnim troškovima i gubicima (firma prenosi porezne gubitke u
sljedeće godine, fizička osoba ne može).</li>
<li>Primaš kripto od kupaca i želiš dio zadržati.</li>
</ul>

<h2>A obrt?</h2>
<p>Obrt se oporezuje kroz porez na dohodak vlasnika po stopama koje određuje grad (od 2024. otprilike 15-23,6% i
25-35,4%), plus doprinosi, ako je kripto dio poslovanja. Paušalni obrt nema prave knjige za takva ulaganja. Većini
obrtnika bolje je držati kripto privatno, gdje vrijede pravila 12% i dvije godine. Dogovori pristup s
knjigovođom prije kupnje.</p>

<h2>Banke</h2>
<p>Hrvatske banke moraju provjeravati podrijetlo novca. Očekuj pitanja kad stignu veći iznosi s mjenjačnice: imaj
spremne izvode mjenjačnice i odluku uprave o ulaganju, i koristi isti račun firme za uplate i isplate.</p>

<h2>Popis prije prve kupnje</h2>
<ol>
<li>Odluka uprave ili vlasnika o ulaganju, s iznosom i namjenom (držanje ili trgovanje).</li>
<li>Računovodstvena politika dogovorena s knjigovođom (HSFI 5 ili HSFI 10).</li>
<li>Poslovni račun na mjenjačnici s MiCA licencom.</li>
<li>Plan čuvanja: na mjenjačnici ili firmin <a href=/hr/rjecnik/multisig>multisig</a> novčanik s dva potpisnika.</li>
<li>Mjesečni izvoz svih transakcija za knjige.</li>
</ol>
<p class=mut>Nije porezni ni pravni savjet; pravila se mijenjaju, a situacije se razlikuju. Provjeri s poreznim
savjetnikom. Pravila za fizičke osobe: <a href=/hr/blog/porez-na-kriptovalute>porez na kriptovalute u Hrvatskoj</a>.</p>
""")


# 18 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "why-big-influencer-calls-are-hard-to-trade", "zasto-je-tesko-trgovati-pozive-velikih-influencera", "Influenceri",
    "Zašto je tako teško trgovati pozive najvećih kripto influencera (i gdje je prilika)",
    "Zašto kopiranje velikih influencera ne uspijeva: snajperi i naknade | MemeSonar",
    "Pozive velikih influencera gledaju tisuće ljudi i sniper botovi koji plaćaju veću naknadu da kupe prvi. Kako rade "
    "prioritetne naknade i Jito napojnice i zašto rastuće zvijezde daju više prostora.", 7,
    "Kad slavni influencer objavi token, tisuće pratitelja i deseci botova pokušavaju kupiti u istoj sekundi. Botovi "
    "plaćaju veću prioritetnu naknadu ili Jito napojnicu da validator stavi njihovu kupnju prvu u blok; svaka kupnja "
    "ispred tebe diže cijenu, pa ulaziš znatno iznad cijene pri pozivu i često postaneš izlaz botovima. Manje poznati "
    "influenceri s dobrim rezultatima (naše Rastuće zvijezde) imaju manje botova za sobom, pa je cijena pri tvom ulazu "
    "bliža cijeni pri pozivu.",
    f"""
<h2>Dvije vrste influencera</h2>
<p>Naša <a href=/hr/influenceri>ljestvica influencera</a> sada ima dva taba. <b>Zvijezde</b> su najpoznatiji računi
(100.000+ pratitelja, imena poput Murada ili Ansema): njihovi postovi pomiču tržište, ali ih svi vide u istom trenutku.
<b>Rastuće zvijezde</b> su manje poznati računi s izmjerenim rezultatima: teže ih je pronaći, prati ih manje ljudi, i
upravo zato se njihovi pozivi još mogu trgovati.</p>
<p>Pozivi su važni: prema našim mjerenjima 52% tokena koje je pozvao izmjereni <b>KOL</b> doseglo je 2x, naspram 14%
tokena bez poziva. Pitanje nije pomiče li poziv cijenu, nego tko uzme taj pomak.</p>

<h2>Što se događa u prvoj sekundi nakon velikog poziva</h2>
<ol>
<li>Post se pojavi. Botovi koji prate račun u milisekundama pročitaju ticker ili adresu ugovora.</li>
<li>Šalju kupnje s visokom <a href=/hr/rjecnik/prioritetna-naknada>prioritetnom naknadom</a> ili Jito napojnicom.</li>
<li>Tisuće ljudi otvore post, kopiraju adresu i kliknu kupi, obično sa zadanom naknadom novčanika.</li>
<li>Validator koji slaže sljedeći blok prvo ga puni onima koji najviše plaćaju. Tvoja transakcija završi iza botova,
ako uopće uđe u zagušeni blok.</li>
<li>Svaka kupnja ispred tebe gura cijenu uz krivulju bazena. Botovi zatim prodaju gomili koja još kupuje.</li>
</ol>

<h2>Kako botovi plaćaju da budu prvi</h2>
<p>Svaka Solana transakcija plaća malu osnovnu naknadu (5.000 lamporta po potpisu, djelić centa). Povrh toga pošiljatelj
može dodati prioritetnu naknadu: cijenu po jedinici izračuna koja proizvođaču bloka kaže "uključi me prvog". Kad se
puno transakcija u istom trenutku natječe za isti token, one koje plaćaju više po jedinici izračuna uglavnom idu prve.</p>
<p>Drugi put je <b>Jito napojnica</b>. Većina Solana validatora koristi Jito klijent, koji prodaje na dražbi "bundleove":
skupinu transakcija koja se izvrši zajedno, točnim redom, samo ako je napojnica plaćena. Bot može staviti svoju kupnju
odmah iza transakcije samog influencera ili odmah ispred vala kupnji, što je
<a href=/hr/rjecnik/front-running>front-running</a>. Nekoliko dolara napojnice je jeftino kad bot očekuje da će
sekundu kasnije prodati tisućama kupaca.</p>
<p>Zato "biti brz" na velikom pozivu nije igra za ljude: osoba koja čita X ne može nadmašiti softver koji reagira u
milisekundama i plaća svoje mjesto u bloku.</p>

<h2>Koliko te košta biti iza botova</h2>
{B("Tvoja ulazna cijena iznad cijene pri pozivu, po mjestu u bloku",
   [("1. (najbrži bot)", 0, "plaća cijenu pri pozivu"), ("Iza 5 botova", 10.3, ""), ("Iza 10 botova", 21, ""),
    ("Iza 20 botova", 44, "tipično mjesto malog ulagača na velikom pozivu"), ("Iza 40 botova", 96, "")],
   sub="Model: svaki bot kupi za $500, bazen s $100k likvidnosti, krivulja konstantnog produkta", hl=(3, 4),
   source="MemeSonar izračun")}
<p>U bazenu s konstantnim produktom svaka kupnja diže cijenu sljedećoj. Probaj svoje brojke:</p>
{CALC.queue("hr")}
<p>S 20 botova koji kupe po $500 u bazenu s $100k likvidnosti, cijena je već oko 44% viša kad se izvrši tvoja kupnja.
Ako botovi zatim prodaju natrag do cijene pri pozivu, gubiš oko 31% a da se s tokenom ništa nije dogodilo. Ista logika kao kod
<a href=/hr/blog/bundleri-i-snajperi>bundlera i snajpera</a> pri lansiranju: tokeni u kojima su snajperi uzeli više od
30% ponude pali su s vrha za 58% u medijanu.</p>

<h2>Zašto rastuće zvijezde ostavljaju više prostora</h2>
<ul>
<li><b>Prati ih manje botova.</b> Sniper botovi prate račune s najvećim dosegom; račun s 15.000 pratitelja i dobrim
rezultatima rijetko je na njihovom popisu.</li>
<li><b>Manja gomila, manji prvi val.</b> Tvoja kupnja se ne natječe s tisućama drugih u istom bloku.</li>
<li><b>Izmjereni, ne slavni.</b> Rangiramo ih po pogotku, medijanu vrha, udjelu rugova i kasnim pozivima, ne po broju
pratitelja.</li>
<li><b>Slaganje je i dalje važno.</b> Kad tri ili više izmjerenih influencera pozove isti token u 15 minuta, 59% dosegne
2x naspram 33% inače (<a href=/hr/blog/grupiranje-influencera>grupiranje influencera</a>).</li>
</ul>

<h2>Ako ipak želiš trgovati poziv Zvijezde</h2>
<ul>
<li>Ne juri prvu minutu. Pričekaj da prvi val botova proda, pa odluči prema grafu.</li>
<li>Prije kupnje postavi najvišu cijenu, npr. ne više od 30% iznad cijene pri pozivu.</li>
<li>Drži kupnju ispod otprilike 2% likvidnosti bazena (<a href=/hr/blog/kako-koristiti-jupiter-swap>postavke
Jupitera</a>).</li>
<li>Veća prioritetna naknada pomaže da transakcija prođe, ali te ne stavlja ispred Jito bundleova.</li>
</ul>
<p>Članovi vide oba taba uživo, svaki poziv izmjeren u par minuta i copy trading na influencere koji pogađaju.</p>
""")


# Croatian versions of the 1 November 2026 posts.
from ui import blogposts_hr_nov  # noqa: E402,F401
from ui import blogposts_hr_seo  # noqa: E402,F401
