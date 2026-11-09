"""Hrvatske verzije pet postova iz SEO plana 7. 11. 2026. (ui/blogposts_seo.py), dodane 9. 11. 2026.

Brojke su MemeSonarova mjerenja iz kopije baze od 8. 11. 2026. i tekst to kaže. Nijedan račun ni kanal se ne
imenuje kao profitabilan: 8. 11. nijedan nije prošao testove opisane u tekstovima; žive stranice nose aktualne brojke.
"""
from ui.blogposts_hr import post
from ui.blogviz import bars, stats


def B(*a, **k):
    return bars(*a, lang="hr", **k)


# 1 ────────────────────────────────────────────────────────────────────────
post(
    "best-crypto-telegram-channels", "najbolji-kripto-telegram-kanali", "Telegram",
    "Najbolji kripto Telegram kanali 2026.: rangirani po tome što su im pozivi napravili, ne po broju članova",
    "Najbolji kripto Telegram kanali 2026., rangirani po izmjerenom pogotku | MemeSonar",
    "Mjerimo svaki poziv tokena objavljen u 1.900 kripto Telegram kanala: cijena sat i 24 sata kasnije, rugovi. Kako "
    "ranking radi i zašto većina popisa 'najboljih kanala' nema veze s rezultatom.", 7,
    "Kripto Telegram kanal vrijedi onoliko koliko je cijena napravila nakon njegovih poziva. Pratimo 1.916 call "
    "kanala i mjerimo svaku objavu s adresom ugovora kao i objavu influencera na X-u: sat kasnije, 24 sata kasnije i "
    "je li token završio kao rug. Rang lista živi na našoj stranici Telegram kanala i mijenja se svaki dan; ovaj tekst "
    "objašnjava metodu i što kažu prvi tjedni podataka.",
    f"""
<h2>Zašto su broj članova i screenshotovi beskorisni</h2>
<p>Svaki popis "najboljih kripto Telegram kanala" rangira po članovima ili po adminovim screenshotovima dobitnika.
Nijedno ne govori što se dogodilo ljudima koji su kupili na poziv. Kanal s 80.000 članova i screenshotom od 1.000 %
može gubiti na devet od deset poziva; screenshot je onaj deseti.</p>
<p>Mi radimo dosadnu stvar. Bot čita javne t.me stranice call kanala, vadi svaku objavu sa Solana
<a href=/hr/rjecnik/ca>adresom ugovora</a> i mjeri cijenu tokena sat i 24 sata nakon objave, plus je li
pala 90 % ili više (<a href=/hr/rjecnik/rug>rug</a>). Isto mjerenje koje radimo svakom
<a href=/hr/rjecnik/kol>KOL-u</a> na X-u.</p>

<h2>Što kažu prvi tjedni podataka</h2>
{B("Telegram objave s adresom ugovora u našoj bazi (8. 11. 2026.)", [
    ("Objave s adresom ugovora", 40772, "iz 1.916 kanala"),
    ("Objave alert botova (predlošci)", 36600, "isti tekst za svaki novi token, izbačene iz svake ocjene"),
    ("Pozivi s izmjerenim ishodom", 2194, "mjerenje su do 8. 11. gušili drugi poslovi"),
], sub="broj", fmt="num", hl=(2,), source="MemeSonar kol.db, kopija 8. 11. 2026.")}
<p>Dvije stvari upadaju u oči. Prvo, gotovo polovica svega objavljenog s adresom dolazi od
<a href=/hr/rjecnik/bot-racun>alert botova</a>: skenerskih predložaka koji se pale na svaki novi token. To nisu
pozivi i izbacujemo ih prije nego što se ijedan kanal ocijeni. Drugo, samo 5 % pravih Telegram poziva imalo je 8.
studenoga izmjeren ishod, jer je besplatni API povijesti cijena bio dijeljen s drugim poslovima i Telegram pozivi su
stalno gubili red. To je popravljeno; brojke na stranicama kanala pune se iz dana u dan.</p>
<p>Zato 8. studenoga nismo mogli pošteno imenovati nijedan "najbolji" kanal. To kažemo i na stranicama: kanal dobiva
presudu tek nakon 10 čistih izmjerenih poziva, a popis pokazuje na koliko poziva svaka presuda stoji.</p>

<h2>Kako čitati stranicu kanala</h2>
<ul>
<li><b>Čisti pozivi</b>: prave objave poziva s izmjerenim ishodom, bez <a href=/hr/rjecnik/kasni-pozivi>kasnih
poziva</a> (cijena se već udvostručila u 2 sata prije) i bez poziva nađenih pretragom koja kreće od tokena koji su
narasli, jer bi takva pretraga svaki kanal učinila dobrim.</li>
<li><b>Viša nakon sat vremena</b>: udio poziva kod kojih je cijena sat kasnije bila iznad cijene u trenutku objave.
Najjednostavnija stvar koju je pratitelj mogao odraditi. Na svim čistim X i Telegram pozivima u našim podacima taj je
udio 29 %.</li>
<li><b>Doseglo +15 % u 24 h</b> i <b>medijan nakon 24 h</b>: brzi skok nije rezultat; medijan kaže što je tipičan
poziv napravio dan kasnije. Za sve čiste pozive zajedno bio je −55 %.</li>
<li><b>Poziva po danu</b>: kanal koji objavi 30 adresa dnevno je feed, a ne signal. Dvanaest objava dnevno s 30 %
<a href=/hr/rjecnik/pogodak>pogotka</a> je šum koji bi dala i nasumična lista tokena.</li>
</ul>

<h2>Kako bi izgledao dobar kanal</h2>
<p>Viša nakon sat vremena puno iznad 29 %, medijan nakon 24 h oko nule ili pozitivan, udio rugova ispod 10 % i najviše
nekoliko poziva dnevno, i to kroz dva odvojena mjeseca. Još ga nismo vidjeli. Kad ga vidimo, bit će na
<a href=/hr/telegram-kanali>stranici Telegram kanala</a> s brojem poziva iza sebe, a članovi dobivaju njegove pozive
uživo, 24 sata prije ove javne stranice.</p>
""")

# 2 ────────────────────────────────────────────────────────────────────────
post(
    "top-crypto-twitter-accounts-by-call-accuracy", "najbolji-kripto-x-racuni-po-tocnosti-poziva", "Influenceri",
    "Najbolji kripto Twitter (X) računi 2026.: po točnosti poziva, ne po pratiteljima",
    "Najbolji kripto Twitter računi 2026., rangirani po točnosti poziva | MemeSonar",
    "Izmjerili smo 5.092 čista poziva tokena s kripto X računa: cijena viša sat kasnije u 29 % slučajeva, medijan "
    "nakon 24 h −55 %. Što 'točnost' mora značiti prije nego ikoga zapratiš.", 8,
    "Broj pratitelja ne govori ništa o tome zarađuju li pozivi nekog računa. Izmjerili smo 5.092 čista poziva Solana "
    "tokena s X računa: sat nakon objave cijena je bila viša samo u 29 % slučajeva, a medijan rezultata nakon 24 sata "
    "bio je −55 %. Od 39 računa s 20+ čistih poziva dva su bila pozitivna u obje polovice svoje povijesti, a nasumično "
    "miješanje ishoda ionako proizvede jedan takav račun. Živa ljestvica pokazuje tko danas vodi, s brojem poziva iza "
    "svake brojke.",
    f"""
<h2>Test koji većina popisa pada</h2>
<p>Uzmi bilo koji popis "najboljih kripto influencera". Rangira po pratiteljima, po reakcijama ili po par slavnih
pogodaka. Mi smo postavili drugo pitanje: da si kupio svaki token koji je račun pozvao, u trenutku objave, i prodao
sat kasnije, bi li ti ostalo novca? To je najjednostavniji <a href=/hr/rjecnik/poziv>poziv</a> koji se stvarno može
odraditi; sve složenije (ljestvice, prateći stopovi) gradi se na tome.</p>

<h2>Brojke (8. 11. 2026.)</h2>
{stats([("5.092", "čistih izmjerenih poziva"), ("29 %", "cijena viša sat nakon objave"), ("−55 %", "medijan rezultata nakon 24 h"), ("2 od 39", "računa pozitivna u obje polovice")])}
<p>"Čisti" je bitno. Izbacujemo <a href=/hr/rjecnik/bot-racun>bot račune</a>, pozive objavljene nakon što se cijena
već udvostručila (<a href=/hr/rjecnik/kasni-pozivi>kasne pozive</a>, 10 do 30 % onoga što računi objavljuju) i
pozive koje smo našli pretragom koja kreće od tokena koji su već pumpali: od njih svaki račun izgleda genijalno po
konstrukciji. Ostaje ono što je pratitelj stvarno mogao trgovati.</p>
{B("Cijena viša sat nakon poziva, po tržišnoj vrijednosti u trenutku poziva", [
    ("Ispod 50k $", 25, "medijan nakon 1 h −19 %"),
    ("50k – 200k $", 30, "−18 %"),
    ("200k – 1M $", 38, "−6 %"),
    ("Iznad 1M $", 26, "−4 %"),
], sub="udio čistih poziva, %", fmt="pct", hl=(2,), source="MemeSonar kol.db, 3.929 čistih poziva s cijenom nakon 1 h")}
<p>Najmanje loše mjesto za praćenje poziva je token koji već vrijedi 200k do 1M $: dovoljno
<a href=/hr/rjecnik/likvidnost>likvidnosti</a> da ga pratitelji callera ne pomaknu, a ne tako velik da se ništa ne
dogodi. Ispod 50k $ poziv je uglavnom sniperov izlaz.</p>

<h2>Zašto računi sa "100 % pogodaka" gube novac</h2>
<p>Mnogi trackeri (i naš, do ovog tjedna) brojali su poziv kao pogodak kad je cijena <i>dotakla</i> +50 % u bilo kojem
trenutku u 24 sata. Po toj mjeri neki računi imaju 85 do 100 %. Njihov medijan rezultata 24 sata nakon poziva bio je
−84 % do −99 %. Skok je trenutak kad caller i botovi prodaju; fitilj nije trade koji je itko drugi napravio. Na našim
profilima <a href=/hr/rjecnik/pogodak>pogodak</a> koji vrijedi gledati je "viša nakon 1 h", uz "doseglo +15 %" i
medijan nakon 24 h, uvijek s brojem poziva.</p>

<h2>Vještina ili sreća: test miješanja</h2>
<p>Od 39 računa s 20 ili više čistih poziva, dva su imala pozitivan prosječni rezultat nakon sat vremena i u prvoj i
u drugoj polovici svoje povijesti. Zatim smo sve ishode 100 puta nasumično izmiješali među istim računima: medijan
takvog miješanja dao je jedan takav račun, 95. percentil tri. Dva nisu dokaz vještine. Mogu postati dokaz s više
poziva, zato svaki profil pokazuje povijest mjesec po mjesec.</p>

<h2>Kako koristiti ljestvicu</h2>
<ol>
<li>Otvori <a href=/hr/influenceri>ljestvicu influencera</a> i zanemari pratitelje.</li>
<li>Otvori profil i pročitaj "viša nakon 1 h", "medijan 24 h" i broj čistih poziva. Ispod 10 poziva nema presude i
stranica to kaže.</li>
<li>Pogledaj tablicu po mjesecima: dobar prvi mjesec pa loš drugi uobičajen je oblik sreće.</li>
<li>Usporedi s medijanom računa na stranici. "Bolje od medijana" i dalje znači da većina poziva gubi.</li>
<li>Članovi vide pozive računa uživo i naše pravilo ulaza po računu; ova javna stranica kasni 24 sata.</li>
</ol>
<p>Nije financijski savjet. Meme coini su izuzetno rizični i većina završi na nuli.</p>
""")

# 3 ────────────────────────────────────────────────────────────────────────
post(
    "memecoin-telegram-groups-explained", "memecoin-telegram-grupe-signal-whale-sniper", "Telegram",
    "Memecoin Telegram grupe: signal, whale i sniper kanali objašnjeni, s brojkama",
    "Memecoin Telegram grupe: signal, whale i sniper kanali objašnjeni | MemeSonar",
    "Tri vrste memecoin Telegram grupa, kako ih razlikovati u pet minuta i što naše mjerenje 40.772 objave poziva kaže "
    "o svakoj.", 6,
    "Memecoin Telegram grupe dolaze u tri vrste: signal kanali (osoba objavi token s razlogom), whale ili wallet kanali "
    "(bot objavi što su praćeni novčanici kupili) i sniper ili alert kanali (bot objavi svaki novi token). Čitaju se "
    "potpuno različito. Alert botovi bili su 47 % svih objava s adresom ugovora u našim podacima i kao pozivi ne vrijede "
    "ništa; whale kanali vrijede koliko i novčanici iza njih; signal kanali su jedini na koje se pogodak uopće odnosi.",
    f"""
<h2>Tri vrste kanala</h2>
<p><b>Signal kanali</b>: osoba (ili mali tim) objavi token, obično s razlogom: tema, graf, poznati dev. To su kanali za
koje <a href=/hr/rjecnik/pogodak>pogodak</a> ima smisla, jer je netko birao token. Objave najviše nekoliko poziva
dnevno.</p>
<p><b>Whale ili wallet kanali</b>: bot objavi "novčanik X kupio token Y za 40 SOL". Kvaliteta je kvaliteta liste
novčanika iza toga, koju ne vidiš. U našim podacima 1.504 od 6.792 bodovana novčanika bilo je profitabilno, a 582 od
njih su botovi ili sniperi koji token drže u medijanu 3 minute; kanal koji prenosi njihove kupnje pokazuje ti tradeove
koji su već gotovi.</p>
<p><b>Sniper ili alert kanali</b>: bot objavi svako novo lansiranje, svaku <a href=/hr/rjecnik/pump-fun>pump.fun</a>
<a href=/hr/rjecnik/graduacija>graduaciju</a>, svaki "paid DEX update". Objavljuju desetke do stotine puta dnevno. To
je feed, a njihovi "pozivi" imaju pogodak nasumičnog tokena.</p>

<h2>Što kažu podaci</h2>
{B("Telegram objave s adresom ugovora, po vrsti (8. 11. 2026.)", [
    ("Predlošci alert botova", 36600, "skenerski botovi, isti tekst za svaki token"),
    ("Pravi pozivi", 40772, "objave koje je napisala osoba"),
    ("Reposti / proslijeđeno", 3286, "proslijeđeno iz drugog kanala"),
], sub="broj objava", fmt="num", hl=(0,), source="MemeSonar kol.db, 1.916 kanala")}
<p>Četrdeset sedam posto svega s adresom je predložak. Prepoznajemo ih po obliku: isti tekst s drugom adresom, "AI
signal", "migration spotted", blokovi "Liq / Holders / Top10", deseci različitih tokena dnevno. Te su objave izbačene
iz svake ocjene na našim stranicama.</p>

<h2>Kako klasificirati kanal u pet minuta</h2>
<ol>
<li>Skrolaj dan unatrag. Prebroji objave s adresama. Više od 20 dnevno: feed, tretiraj ga kao listu tokena, ne kao
savjet.</li>
<li>Pročitaj tri objave. Ako svaka ima isti raspored i nijedan razlog, bot je. Ako ima razlog, pisala je osoba.</li>
<li>Pogledaj vrijeme. Whale kanal objavi "kupio" nakon što je novčanik kupio; dok ti to pročitaš, novčanik je par
minuta od prodaje (medijan držanja profitabilnih botova u našim podacima: 3 minute).</li>
<li>Provjeri što admin ne pokazuje: pozive koji su otišli na nulu. Naše <a href=/hr/telegram-kanali>stranice
kanala</a> pokazuju sve, s udjelom onih koji su pali 90 % ili više.</li>
<li>Provjeri <a href=/hr/rjecnik/kasni-pozivi>kasne pozive</a>: poziv nakon što se cijena već udvostručila je signal
za prodaju odjeven u kupnju.</li>
</ol>

<h2>Pošteno očekivanje</h2>
<p>Na svim čistim pozivima koje smo izmjerili na X-u i Telegramu zajedno, cijena je sat kasnije bila viša u 29 %
slučajeva, a medijan rezultata nakon dana bio je −55 %. Memecoin grupa koja to dosljedno tuče je rijetka; ona koja to
tuče s malo poziva dnevno i niskim udjelom <a href=/hr/rjecnik/rug>rugova</a> je ono što rang lista traži. Dok kanal
nema 10 čistih izmjerenih poziva, naša stranica za njega kaže "premalo podataka" umjesto da nagađa.</p>
""")

# 4 ────────────────────────────────────────────────────────────────────────
post(
    "how-to-spot-a-pump-fun-runner", "kako-prepoznati-pump-fun-runnera-u-10-minuta", "Vodiči",
    "Kako prepoznati pump.fun runnera u prvih 10 minuta: što pokazuje 129 lansiranja",
    "Kako prepoznati pump.fun runnera u prvih 10 minuta (129 izmjerenih lansiranja) | MemeSonar",
    "Viralna objava na X-u tvrdi da runner na pump.funu u 10. minuti ima 40k $ mcapa i 13k $ volumena. Provjerili smo "
    "129 svježih lansiranja: nijedno, a dva koja su kasnije došla do 100k $ u 10. minuti izgledala su obično.", 7,
    "Testirali smo popularno pravilo 'runner u 10. minuti ima 40k $ mcapa i 13k $ volumena' na 129 svježih pump.fun "
    "lansiranja. Nula ih je odgovaralo pravilu. Dva od 129 kasnije su dosegla 100k $ mcapa i oba su u 10. minuti bila "
    "mala. Kopiranje 'runner' novčanika iz objave nije bolje: u našim podacima taj stil pobjeđuje u 22 do 24 % slučajeva. "
    "Pomaže čekanje graduacije i 30k+ $ mcapa, pa ocjena tokena kao i svakog drugog.",
    f"""
<h2>Tvrdnja</h2>
<p>Široko dijeljena objava na X-u daje recept: <a href=/hr/rjecnik/pump-fun>pump.fun</a> token koji deset minuta nakon
lansiranja ima 40k $ mcapa i 13k $ volumena je "runner", a par imenovanih novčanika hvata ih svaki put. Pravilo zvuči
točno jer su runneri kojih se sjećaš rano doista izgledali živo. Pitanje je koliko je živih tokena otišlo nikamo.</p>

<h2>Test</h2>
<p>Uzeli smo 129 svježih lansiranja iz živog toka tijekom jedne večeri, zabilježili mcap i volumen u 10. minuti i
pratili svako 24 sata.</p>
{stats([("129", "praćenih svježih lansiranja"), ("0", "ispunilo pravilo 40k + 13k u 10. minuti"), ("2", "doseglo 100k $ unutar 24 h"), ("−9,7 %", "medijan 5 min nakon graduacije, 117 tokena")])}
<p>Nijedan od 129 nije odgovarao pravilu, pa bi ti pravilo reklo da ne kupiš ništa, što je barem jeftino. Dva tokena
koja su došla do 100k $ imala su mali mcap u 10. minuti i ništa u njihovih prvih deset minuta nije ih razlikovalo od
ostalih 127. Rani volumen nije predvidio ništa u ovom uzorku; ovo je jedna večer i 129 tokena, a ne zakon.</p>

<h2>Novčanici iz objave</h2>
<p>Objava imenuje par novčanika kao lovce na runnere. Mi novčanike bodujemo po njihovoj on-chain povijesti. Stil koji
objava opisuje, kupnja u prvoj minuti i prodaja u prvih deset, pobjeđuje u 22 do 24 % slučajeva u našim podacima, s
ocjenom za kopiranje 2 i 12 od 100. Novčanik koji trguje nekoliko stotina puta dnevno i drži tri minute ne može
kopirati čovjek dvije minute iza njega; dok tvoja kupnja sjedne, on ti prodaje. Više u našem
<a href=/hr/blog/sto-je-pracenje-novcanika>vodiču o praćenju novčanika</a>.</p>

<h2>Što podaci podržavaju</h2>
{B("Gdje je kupnja tokena nakon poziva prošla najmanje loše (čisti pozivi, sat kasnije)", [
    ("Ispod 50k $ mcapa", 25, "uglavnom sniperov izlaz"),
    ("50k – 200k $", 30, ""),
    ("200k – 1M $", 38, "najbolji razred u našim podacima"),
    ("Iznad 1M $", 26, ""),
], sub="udio poziva s višom cijenom sat kasnije, %", fmt="pct", hl=(2,), source="MemeSonar kol.db, 3.929 poziva, 8. 11. 2026.")}
<ol>
<li>Preskoči bonding curve. Tokene ispod 30k $ naš alat uopće ne analizira; prve minute pripadaju
<a href=/hr/rjecnik/sniper>sniper botovima</a> i bundleovima.</li>
<li>Čekaj <a href=/hr/rjecnik/graduacija>graduaciju</a>, pa čekaj još: u naših 117 izmjerenih graduacija medijan cijene
pet minuta nakon otvaranja poola bio je −9,7 %. Bot strategija "kupi graduaciju" je izgubila.</li>
<li>Ocijeni token na 30k do 1M $ kao i svaki drugi: <a href=/hr/rjecnik/likvidnost>likvidnost</a> naspram mcapa,
raspodjela holdera, dev novčanik koji ne prodaje i tko ga zove. Naša <a href=/hr/solana-meme-coini>lista meme coina</a>
i rug provjera na svakoj stranici coina rade točno to.</li>
<li>Ako ipak želiš rane tokene, dimenzioniraj za gubitak od 90 %: većina završi na nuli.</li>
</ol>
<p>Članovi dobivaju živi tok graduacija s primijenjenim sigurnosnim provjerama; ovaj vodič je javna verzija. Nije
financijski savjet.</p>
""")

# 5 ────────────────────────────────────────────────────────────────────────
post(
    "how-to-check-a-kol-track-record", "kako-provjeriti-rezultate-kol-a", "Influenceri",
    "KOL u kriptu: kako provjeriti rezultate KOL-a prije nego pratiš poziv",
    "Kako provjeriti rezultate kripto KOL-a prije praćenja poziva | MemeSonar",
    "Od 6.995 kripto računa koje pratimo, 5.192 nemaju nijedan izmjeren poziv. Provjera u pet koraka za svakog KOL-a, "
    "sa zamkama zbog kojih loši calleri izgledaju dobro: pogoci na fitilj, kasni pozivi i uzorci od pobjednika.", 7,
    "KOL (key opinion leader) je račun čiji pozivi tokena pomiču cijene. Prije nego ga zapratiš, provjeri pet stvari: "
    "koliko je njegovih poziva uopće izmjereno, broji li pogodak skokove ili stvarne rezultate, koliko je poziva došlo "
    "nakon pumpa, je li povijest sastavljena samo od pobjednika i sliči li prva polovica povijesti drugoj. Od 6.995 "
    "računa u našoj bazi 5.192 imaju nula izmjerenih poziva, pa je većina 'dokazanih KOL-ova' nedokazana.",
    f"""
<h2>Što je KOL</h2>
<p>U kriptu je <a href=/hr/rjecnik/kol>KOL</a> račun na X-u ili Telegramu čiji <a href=/hr/rjecnik/poziv>pozivi</a>
natjeraju druge da kupe. Riječ ne govori ništa o tome jesu li ti kupci zaradili. Naš raniji tekst
<a href=/hr/blog/sto-je-kol-u-kriptu>objašnjava pojam</a>; ovo je kontrolna lista.</p>

<h2>Korak 1: koliko je poziva izmjereno?</h2>
{B("Kripto računi u našoj bazi, po broju izmjerenih poziva (8. 11. 2026.)", [
    ("Nula izmjerenih poziva", 5192, "nema što ocijeniti"),
    ("1 do 9 izmjerenih", 1655, "stranica postoji, presude nema"),
    ("10 ili više čistih poziva", 148, "presuda moguća"),
], sub="računa", fmt="num", hl=(2,), source="MemeSonar kol.db, 6.995 računa")}
<p>Većini računa koje ljudi zovu KOL-ovima nitko nikad nije izmjerio nijedan poziv. Screenshot nije mjerenje. Nama
treba 10 čistih izmjerenih poziva prije nego stranica išta kaže, i stranica pokazuje taj broj.</p>

<h2>Korak 2: što znači "pogodak"?</h2>
<p>Ako tracker broji poziv kao pogodak kad je cijena dotakla +50 % u bilo kojem trenutku u 24 sata, broji fitilje.
Računi s 85 do 100 % takvih pogodaka imali su u našim podacima medijan rezultata nakon 24 sata −84 % do −99 %. Traži
"cijena viša sat kasnije" i "medijan nakon 24 h". To je ono što je pratitelj mogao imati. Vidi
<a href=/hr/rjecnik/pogodak>pogodak</a>.</p>

<h2>Korak 3: koliko je poziva došlo nakon pumpa?</h2>
<p><a href=/hr/rjecnik/kasni-pozivi>Kasni poziv</a> objavljen je nakon što se cijena već udvostručila u prethodna dva
sata. Ovisno o izvoru, 10 do 30 % izmjerenih poziva je kasno. To su izlazi, ne ulazi, a povijest koja ih uključuje je
povijest tuđih izlaza.</p>

<h2>Korak 4: kako je povijest sastavljena?</h2>
<p>Mnogi trackeri nalaze callere tako da krenu od tokena koji su pumpali i pitaju "tko je ovo prvi objavio?". Svaki
tako nađeni račun izgleda dobro: vidiš samo njegove pobjednike. Mi takve izvore označavamo i izostavljamo iz javnih
brojki; poštena povijest gradi se iz cijelog timelinea računa, uključujući gubitnike.</p>

<h2>Korak 5: sliči li prva polovica drugoj?</h2>
<p>Podijeli pozive u vremenu. Od 39 računa s 20+ čistih poziva u našim podacima, dva su bila pozitivna u obje
polovice, a nasumično miješanje istih ishoda ionako daje jedan takav račun. Dobar mjesec pa loš mjesec oblik je sreće.
Tablica po mjesecima na svakom <a href=/hr/influenceri>profilu</a> to pokazuje.</p>

<h2>Što s KOL-om koji prođe</h2>
<ul>
<li>Prati pozive na tokenima između 200k i 1M $ mcapa (jedini razred u kojem rezultat nakon sat vremena u našim
podacima nije bio izrazito negativan).</li>
<li>Nikad ne ulazi na kasni poziv; nikad ispod 30k $.</li>
<li>Isplaniraj izlaz prije ulaza; naši demo računi prodaju pola na +15 %, ostatak s pratećim stopom od 15 %.</li>
<li>Očekuj da većina poziva ipak gubi: najbolji računi tuku medijan, ne tuku gravitaciju.</li>
</ul>
<p>Članovi vide žive pozive svakog računa i naše pravilo ulaza po računu. Nije financijski savjet.</p>
""")
