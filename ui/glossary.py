"""Pojmovnik: one source of truth for every term, metric, page and table name the dashboard shows.

Every ⓘ in the app opens an entry from here (pop-up with the long explanation), the /pojmovnik page lists all of
them, and ui.html annotates headings, stat tiles and table headers whose text matches a term or alias. Column
explanations from ui/help.py and page intros from ui/html.INTRO are pulled in automatically, so a new column or page
is covered as soon as it has a HELP / INTRO entry; terms that deserve more get a hand-written entry below.

Plain Croatian, no developer words: the reader is a friend who has never traded a memecoin.
"""
import re
import unicodedata

CATS = [
    ("osnove", "📘 Osnove kripta", "Riječi koje se koriste svugdje: token, mcap, likvidnost, wallet, rug…"),
    ("ocjene", "🎯 Ocjene alata", "Brojevi koje alat sam računa da bi odlučio što je dobro: hype, confidence, šansa…"),
    ("eventi", "📅 Eventi i kalendar", "Događaji oko kojih nastaju tokeni i kako se ocjenjuju."),
    ("trading", "🏆 Natjecanje i trgovanje", "Demo račun, pozicije, dobit, copy trading, DCA, izlazi."),
    ("kol", "📣 KOL-ovi i influenceri", "Tko zove tokene i kako mjerimo koliko vrijede njihovi pozivi."),
    ("walleti", "👛 Novčanici (walleti)", "Kako ocjenjujemo novčanike i kojima vjerujemo."),
    ("grupe", "🕸 Grupe i veze", "Tko radi zajedno: grupe KOL-ova, povezani novčanici."),
    ("dugo", "🌱 Dugoročni tokeni", "Sigurniji sloj: stariji tokeni koji preživljavaju."),
    ("nastoken", "🪙 Naš token", "Pojmovi oko vlastitog tokena: trezor, lansiranje, ponuda."),
    ("sustav", "🧠 Učenje i sustav", "Kako alat uči, troši i izvještava."),
    ("stranice", "🧭 Stranice aplikacije", "Što je na kojoj stranici i čemu služi."),
    ("stupci", "📋 Stupci u tablicama", "Kratka objašnjenja svakog stupca u tablicama."),
]
CAT_NAME = {k: n for k, n, _ in CATS}


def slug(s):
    s = unicodedata.normalize("NFKD", str(s).replace("đ", "d").replace("Đ", "D"))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "x"


def norm(s):
    """Text as it appears on a page -> lookup key (case, emoji, ⓘ, trailing ':' and extra spaces don't matter)."""
    s = re.sub(r"<[^>]+>", "", str(s or "")).replace("ⓘ", "")
    s = "".join(c for c in s if c.isalnum() or c in " %×+-/().,≥?#").strip(" :·-.")
    return re.sub(r"\s+", " ", s).lower()


TERMS = {}


def T(name, cat, short, long="", primjer="", vidi=(), gdje=(), alias=(), k=None):
    k = k or slug(name)
    assert k not in TERMS, k
    TERMS[k] = {"k": k, "name": name, "cat": cat, "short": short, "long": long, "primjer": primjer,
                "vidi": list(vidi), "gdje": list(gdje), "alias": list(alias)}


# ---------------------------------------------------------------- osnove
T("Token", "osnove", "Digitalni novčić na Solana mreži kojim se trguje kao dionicom.",
  "Svatko može za par dolara napraviti novi token (najčešće na pump.fun). Većina takvih tokena su meme novčići: nemaju "
  "nikakvu vrijednost osim pažnje koju dobiju. Cijena raste kad ga ljudi kupuju i pada kad prodaju. Alat svaki dan vidi "
  "tisuće novih tokena i pokušava pronaći one rijetke koji će narasti, a izbaciti prevare.",
  "FARTCOIN, USELESS i TRUMP su tokeni. Svaki ima svoju adresu (CA) po kojoj se razlikuje od kopija istog imena.",
  vidi=["ca", "mcap", "memecoin", "rug"], gdje=[("/tokens", "Svi tokeni")], alias=["tokeni", "coin"])
T("CA", "osnove", "Contract address: jedinstvena adresa tokena, kao OIB.",
  "Ime tokena (npr. TRUMP) može imati stotine kopija, ali adresa je jedinstvena. Kad netko 'zove' token, objavi njegovu "
  "adresu da ljudi kupe baš taj. Gumb 'Kopiraj adresu' u alatu kopira CA da ga zalijepiš u Phantom ili Jupiter.",
  "6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN je CA pravog TRUMP tokena.",
  vidi=["token", "kol"], alias=["adresa tokena", "contract address", "mint"])
T("Mcap", "osnove", "Tržišna kapitalizacija: cijena tokena × broj tokena. Koliko 'vrijedi' cijeli token.",
  "Mcap je bolji od cijene za usporedbu tokena, jer cijena ovisi o tome koliko je tokena napravljeno. Novi tokeni kreću "
  "oko $5k; $100k je prvi ozbiljan prag, $1M+ znači da je token stvarno zaživio. Iz povijesti od 25 tisuća tokena znamo "
  "da je najbolji trenutak za ulaz kad mcap prvi put prijeđe $100k.",
  "Token po cijeni $0,0005 s milijardu komada ima mcap $500k.",
  vidi=["likvidnost", "volumen"], alias=["market cap", "mc", "tržišna kapitalizacija", "ulazni mc", "mcap u pozivu"])
T("FDV", "osnove", "Fully diluted valuation: koliko bi token vrijedio da su svi tokeni koji ikad mogu postojati već u opticaju.",
  "FDV = cijena × najveća moguća količina tokena. Kad je FDV puno veći od tržišne vrijednosti (mcap), velik dio tokena je "
  "još zaključan i kasnije će se prodavati, što gura cijenu dolje. Kod većine pump.fun meme coina sva količina postoji od "
  "prvog dana, pa su FDV i mcap isti.", "Cijena $0,01, u opticaju 100 mil., najviše 1 mlrd.: mcap $1M, FDV $10M.",
  vidi=["mcap", "likvidnost"], alias=["fully diluted valuation"], k="fdv")
T("Likvidnost", "osnove", "Koliko je novca u bazenu (poolu) iz kojeg se kupuje i prodaje token.",
  "Kad kupuješ token, ne kupuješ od osobe nego iz bazena u kojem su token i SOL. Što je u bazenu više novca, to manje tvoja "
  "kupnja pomakne cijenu i lakše izađeš. Mala likvidnost (ispod $10k) znači da ćeš pri prodaji izgubiti puno na klizanju "
  "cijene i da token lako manipulirati. Ako netko izvuče likvidnost, token je mrtav (to je rug).",
  "Token s $5k likvidnosti: prodaja za $500 može sama srušiti cijenu 10%.",
  vidi=["slippage", "rug", "mcap"], alias=["likv", "liquidity", "liq"])
T("Volumen", "osnove", "Koliko se dolara tokenom trgovalo u nekom razdoblju (kupnje + prodaje).",
  "Volumen pokazuje koliko ljudi stvarno trguje. Rast cijene bez volumena je sumnjiv; rast uz velik volumen znači pravi "
  "interes. Alat posebno gleda volumen sat prije i sat poslije KOL posta, da vidi koliko je post doveo kupaca.",
  "$200k volumena u 24 h na tokenu od $1M mcapa je živ token.",
  vidi=["volumen-x", "likvidnost"], alias=["volume", "volumen 24 h"])
T("Holderi", "osnove", "Broj novčanika koji drže token.",
  "Više holdera = token je raširen među više ljudi. Važno je i koliko drže najveći: ako top 10 novčanika drži više od "
  "35%, oni mogu jednom prodajom srušiti cijenu. Alat broji holdere i prati raste li im broj iz sata u sat.",
  "Token s 2.000 holdera gdje top 10 drži 20% je zdraviji od tokena s 300 holdera gdje top 10 drži 70%.",
  vidi=["wallet", "bundler"], alias=["holders", "holderi (puls)"])
T("Wallet", "osnove", "Novčanik na blockchainu (npr. Phantom). Ima javnu adresu; svatko vidi što kupuje i prodaje.",
  "Svaka kupnja i prodaja na Solani je javna. Zato alat može pratiti novčanike koji stalno zarađuju (smart money) i "
  "novčanike KOL-ova, i vidjeti kupuju li prije nego što objave. Riječi wallet i novčanik znače isto.",
  vidi=["smart-money", "copy-ocjena", "kol-novcanik"], gdje=[("/wallets", "Novčanici")],
  alias=["novčanik", "novčanici", "walleti", "adresa"])
T("SOL", "osnove", "Kriptovaluta Solana mreže. Njome se plaćaju tokeni i naknade.",
  "Novčanici kupuju tokene za SOL, pa su zarade novčanika u alatu izražene u SOL-u. Jedan SOL vrijedi oko $150-250 (mijenja "
  "se). Na stranici Dugoročni tokeni se uspoređuju sa SOL-om: token koji ne raste brže od SOL-a nije vrijedan rizika.",
  alias=["solana"])
T("DEX", "osnove", "Mjenjačnica na blockchainu bez posrednika (Raydium, Meteora, Jupiter…).",
  "Na DEX-u trguješ izravno iz svog novčanika. Suprotno je CEX: burza poput Binancea gdje novac držiš kod njih. Novi "
  "tokeni se uvijek prvo trguju na DEX-u.", vidi=["cex", "launchpad"], alias=["solana dex", "decentralizirana mjenjačnica"])
T("CEX", "osnove", "Centralizirana burza (Binance, Coinbase, Bybit…) koja drži novac korisnika.",
  "Kad velik dio tokena leži na adresama burzi, to znači da su ga burze uvrstile, što je dobar znak za stariji token. "
  "Na stranici Dugoročni pratimo koliki udio top 20 holdera su burze.", vidi=["dugorocni-token"], alias=["burza", "burze"])
T("Launchpad", "osnove", "Stranica na kojoj svatko može napraviti novi token (pump.fun, LaunchLab, Meteora DBC…).",
  "Token se rodi na launchpadu i trguje na njegovoj krivulji dok ne skupi dovoljno novca; tada 'diplomira' na pravi DEX. "
  "Ukupni volumen launchpada je dobar termometar koliko je tržište memecoina vruće.",
  vidi=["pump-fun", "graduacija", "rezim-trzista"], alias=["launchpadi"])
T("pump.fun", "osnove", "Najveći launchpad za meme tokene na Solani.",
  "Na pump.fun token nastaje za par centi. Cijena prvo ide po krivulji (bonding curve): što više ljudi kupi, to je skuplje. "
  "Kad mcap dođe do oko $69-100k, token diplomira na PumpSwap/Raydium. Većina pump.fun tokena nikad ne diplomira.",
  vidi=["graduacija", "launchpad"], alias=["pumpfun", "pump fun"])
T("Graduacija", "osnove", "Trenutak kad token na pump.fun skupi dovoljno novca i prijeđe na pravi DEX.",
  "Prije graduacije token je na krivulji launchpada, poslije ima pravi bazen likvidnosti. 'Pred graduacijom' znači da je "
  "blizu tog praga i tada često privuče novu pažnju.", vidi=["pump-fun"], alias=["diplomira", "pred graduacijom"])
T("Slippage", "osnove", "Klizanje cijene: razlika između cijene koju vidiš i cijene koju stvarno dobiješ.",
  "Što je likvidnost manja i kupnja veća, to je klizanje veće. Alat ga uračunava u demo trgovanje i u Natjecanje, pa su "
  "rezultati realni, a ne idealni.", "Kupiš za $100 token s malo likvidnosti: dobiješ tokena kao da si platio $103.",
  vidi=["likvidnost", "naknada"], alias=["klizanje cijene", "klizanje"])
T("Naknada", "osnove", "Trošak transakcije (fee) koji plaćaš mreži, mjenjačnici i botu za trgovanje.",
  "U demo trgovanju i Natjecanju svaka kupnja i prodaja plaća realnu naknadu, da brojke budu kao u stvarnosti.",
  alias=["fee", "naknade"])
T("Memecoin", "osnove", "Token bez stvarne namjene čija vrijednost dolazi samo iz šale, priče i pažnje.",
  "Memecoini mogu narasti 100× u danu i pasti 99% u satu. Zato alat traži signale pažnje (X objave, KOL-ovi, volumen) i "
  "istovremeno filtrira prevare.", alias=["meme coin", "meme token", "meme tokeni"])
T("Hardverski novčanik", "osnove", "Mali uređaj (npr. Ledger, Trezor, Tangem kartica) koji drži privatni ključ izvan interneta.",
  "Transakciju potpisuješ na uređaju, pa haker koji zarazi računalo ili preglednik ne može doći do ključa. Za "
  "trgovanje se drži mali iznos u vrućem novčaniku (Phantom), a ušteđevina na hardverskom. Košta od oko $50.",
  "Ledger spojen s Phantomom: aplikacija ostaje ista, ali svaka kupnja traži potvrdu na uređaju.",
  vidi=["wallet", "multisig"], alias=["hladni novčanik", "cold wallet", "hardware wallet", "hladno čuvanje"],
  k="hardverski-novcanik")
T("Multisig", "osnove", "Zajednički novčanik kojem za svaku transakciju treba odobrenje više ljudi (npr. 2 od 3).",
  "Na Solani se najčešće koristi Squads. Nitko sam ne može potrošiti novac, pa je to standard za blagajne projekata i "
  "zajedničke fondove. Članovi mogu biti i hardverski novčanici.", "Blagajna našeg tokena kasnije ide u Squads multisig.",
  vidi=["hardverski-novcanik", "wallet"], alias=["multi-sig", "squads"], k="multisig")
T("Trading bot", "trading", "Aplikacija ili Telegram bot koji kupuje i prodaje tokene jednim klikom ili automatski.",
  "Terminali (Axiom, Photon, GMGN) i Telegram botovi (Trojan, BonkBot) drže spreman novčanik i pokazuju nove tokene "
  "čim se pojave. Naplaćuju oko 1% na svaku kupnju i prodaju. Ubrzaju te, ali ne biraju bolje tokene umjesto tebe.",
  "Kupnja i prodaja od $100 uz 1% naknade košta ukupno $2 plus mrežne naknade.",
  vidi=["copy-trading", "slippage"], alias=["trading terminal", "terminal", "telegram bot", "trading botovi"],
  k="trading-bot")
T("Rug checker", "osnove", "Besplatan alat (npr. RugCheck) koji prije kupnje provjeri token na znakove prevare.",
  "Pokaže može li kreator kovati nove tokene ili zamrznuti novčanike, koliko je likvidnosti, je li zaključana i "
  "koliko drže najveći holderi. Ne vidi povijest kreatora ni polagano prodavanje, pa prolaz nije jamstvo.",
  vidi=["rug", "mint-authority"], alias=["rugcheck", "provjera ruga", "rug check"], k="rug-checker")
T("API", "osnove", "Način na koji program (bot, aplikacija) traži podatke od drugog servisa, npr. cijenu tokena.",
  "Kripto aplikacije koriste RPC čvor (npr. Helius) za čitanje blockchaina i slanje transakcija, i API za podatke "
  "(DexScreener, Birdeye, CoinGecko) za cijene, poolove i holdere. Besplatne razine imaju ograničen broj poziva.",
  "KriptoRadar koristi Helius za novčanike i DexScreener za cijene.", alias=["rpc", "rpc čvor", "api ključ"], k="api")
T("Udio u dobiti", "trading", "Postotak dobiti koji kod copy tradinga na burzi ide traderu kojeg kopiraš (obično 10-20%).",
  "Naplaćuje se samo na dobitne tradeove. On-chain copy trading umjesto toga naplaćuje oko 1% na svaki trade, i "
  "dobitni i gubitni.", "Kopirani trade zaradi $100, trader s 10% udjela dobije $10.",
  vidi=["copy-trading"], alias=["profit share", "profit sharing"], k="udio-u-dobiti")
T("Rug", "osnove", "Prevara ili krah: tvorci izvuku novac ili token padne 90%+ i više se ne oporavi.",
  "Rug pull znači da tvorac izvuče likvidnost ili proda sve svoje tokene odjednom. U alatu 💀 RUGAN znači da je cijena 70%+ "
  "ispod vrha u zadnja 24 h ili da je likvidnost izvučena. Rugani tokeni se ne prikazuju i ne mogu se kupiti, ali alat iz "
  "njih uči kako prepoznati sljedeći (stranica Učenje → Rugovi).",
  vidi=["rug-filter", "rug-profil", "likvidnost"], gdje=[("/learn", "Učenje")], alias=["rugan", "rug pull", "rugovi", "💀 rugan"])
T("Dev", "osnove", "Tvorac tokena (developer). Njegov novčanik je napravio token.",
  "Dev često drži velik dio tokena. Ako dev proda u trenutku kad KOL objavi token, ljudi kupuju od njega i on zarađuje "
  "na njima. Rotacijski dev to radi na više tokena zaredom.", vidi=["rotacijski-dev", "insajder"], alias=["devovi", "developer"])
T("Bundler", "osnove", "Netko tko je u istoj sekundi kad je token nastao kupio veliki dio preko više novčanika.",
  "Tako izgleda kao da token ima puno kupaca, a zapravo ga drži jedna osoba koja može sve prodati odjednom. Više od 15% "
  "u rukama bundlera je crvena zastavica.", vidi=["holderi", "rug-filter"], alias=["bundleri"])
T("Sniper", "osnove", "Bot koji kupuje token u prvim sekundama nakon nastanka da bi brzo prodao.",
  "Snajperi obično prodaju čim cijena malo naraste, pa njihove kupnje nisu znak pravog interesa. Takvi novčanici nikad ne "
  "idu na copy listu.", alias=["snajper", "snajperi"])
T("Prioritetna naknada", "osnove", "Dodatna naknada kojom se kupnja na Solani gura ispred drugih u istom bloku.",
  "Kad u istoj sekundi stigne puno kupnji istog tokena, mreža prvo obradi one koje plate veću naknadu (priority fee ili "
  "Jito tip). Snajperski botovi zato plate više od običnog kupca i uvijek uđu prvi, po nižoj cijeni. Tvoja kupnja dođe "
  "iza njih, gura cijenu gore, a botovi ti prodaju. Zato je kod najpoznatijih influencera teško zaraditi na pozivu.",
  "Običan kupac plati 0,0001 SOL naknade, bot 0,01 SOL: bot je prvi u bloku i kupi prije svih.",
  vidi=["sniper", "front-running", "zvijezde-i-rastuce-zvijezde"], alias=["priority fee", "jito tip", "prioritetne naknade"],
  k="prioritetna-naknada")
T("Front-running", "osnove", "Kad bot vidi da dolazi val kupnji i kupi prije njih da bi im prodao skuplje.",
  "Botovi prate objave poznatih influencera i nove transakcije. Čim vide poziv, kupe s većom prioritetnom naknadom, pa "
  "uđu prije ljudi koji su post tek pročitali, i prodaju im u istoj minuti. Poziv tada izgleda dobro na grafu, a "
  "većina pratitelja kupi na vrhu.", vidi=["prioritetna-naknada", "sniper"], alias=["frontrunning", "front-run"])
T("Zvijezde i rastuće zvijezde", "kol", "Zvijezde su najpoznatiji influenceri (100k+ pratitelja), rastuće zvijezde manje poznati koje tražimo.",
  "Zvijezde (npr. Murad, Ansem) prati masa ljudi i botovi, pa nakon njihovog posta snajperi kupe prvi i cijena često "
  "padne čim pratitelji uđu. Rastuće zvijezde imaju manje pratitelja, pa manje botova čeka njihove pozive, a dobri "
  "među njima zovu tokene ranije. Na ljestvici influencera to su dvije kartice.",
  vidi=["kol", "prioritetna-naknada", "front-running", "moc-poziva"], alias=["zvijezde", "rastuće zvijezde", "stars",
                                                                          "rising stars"], k="zvijezde-i-rastuce-zvijezde")
T("Insajder", "osnove", "Novčanik koji kupi token prije nego KOL objavi, pa proda u valu kupaca koji post dovede.",
  "Ako su insajderi prodavali odmah nakon poziva, poziv je vjerojatno dogovoren ili plaćen: KOL je doveo kupce da bi netko "
  "drugi prodao. Takvi pozivi ne dobivaju KOL signal.", vidi=["rotacijski-dev", "kol"], alias=["insajderi", "insajdera"])
T("Smart money", "osnove", "Novčanici s dokazanom poviješću zarade: često su rano u tokenima koji kasnije narastu.",
  "Alat ocjenjuje tisuće novčanika po stvarnoj zaradi. Kad se više takvih pojavi među prvim kupcima novog tokena, to je "
  "jedan od jačih signala.", vidi=["ocjena-profitabilnosti", "konvergencija"], alias=["smart wallet", "smart walleti"])
T("Mint authority", "osnove", "Pravo tvorca da napravi još tokena kad hoće.",
  "Ako je aktivno, tvorac može 'naštampati' milijune novih tokena i prodati ih, pa cijena pada u nulu. Zato token s aktivnim "
  "mint ili freeze pravom odmah pada na prvom situ (T0).", vidi=["t0", "rug-filter"], alias=["freeze authority", "mint", "freeze"])
T("KOL", "kol", "Key Opinion Leader: influencer na X-u ili Telegramu koji objavljuje (\"zove\") tokene.",
  "Kad poznati KOL objavi adresu tokena, njegovi pratitelji kupuju i cijena često skoči. Alat mjeri svaki poziv: koliko je "
  "token narastao 1 h, 6 h i 24 h poslije, koliko je post doveo volumena i je li KOL zvao rano ili kasno. Iz toga dobije "
  "'moć poziva'. Iz podataka: kad KOL zove token, 52% ih se udvostruči (bez poziva 14%).",
  vidi=["poziv", "moc-poziva", "pogodak"], gdje=[("/kol", "KOL-ovi"), ("/copy-trading", "Copy trading")],
  alias=["kol-ovi", "influencer", "influenceri", "kol-ovi i njihovi pozivi"])
T("Poziv", "kol", "Objava u kojoj KOL objavi adresu tokena i potiče ljude da ga kupe (eng. call).",
  "Brojimo samo prvi post po tokenu. Postovi tipa '15x on $X' nakon skoka su hvalisanje, a ne poziv, i ne ulaze u ocjenu. "
  "Post samo s $TICKEROM bez adrese se zove 'ticker' jer možda misli na drugi token istog imena.",
  vidi=["kol", "hvalisanje", "kasni-pozivi"], alias=["pozivi", "call", "vrsta poziva", "svi pozivi", "poziva"])
T("Hvalisanje", "kol", "Post nakon što je token već skočio ('20x on $X'), a ne poziv unaprijed.",
  "Hvalisanja ne govore ništa o tome zna li KOL birati tokene, zato se ne broje u ocjenu.", vidi=["poziv"],
  alias=["hvalisanja"])
T("Multiplikator", "osnove", "2x, 5x, 10x: koliko puta je cijena narasla od ulaza.",
  "2x znači da se uloženo udvostručilo (+100%). '2x zajedno' ili '2x u 24 h' je udio tokena koji su se udvostručili.",
  alias=["2x", "2x+", "x"])
T("Medijan", "osnove", "Srednja vrijednost kad se svi brojevi poredaju: polovica je ispod, polovica iznad.",
  "Koristimo medijan umjesto prosjeka jer jedan token koji naraste 100× ne smije izgledati kao da KOL uvijek pogađa.",
  "Pozivi +5%, +10%, +900%: prosjek je +305%, a medijan +10%, što je poštenija slika.", alias=["medijana"])
T("Korelacija", "osnove", "Broj od −1 do +1 koji kaže idu li dvije stvari zajedno.",
  "+1: kad jedno raste, raste i drugo. 0: nema veze. −1: obrnuto. Između −0,15 i +0,15 je to praktički slučajnost.",
  alias=["korelacija s max 24 h", "spearmanova korelacija"])
T("UTC", "osnove", "Svjetsko vrijeme. Kod nas je zimi UTC+1, ljeti UTC+2.",
  "Neke tablice pokazuju vrijeme u UTC jer tako rade izvori podataka. 14:00 UTC je zimi 15:00 u Zagrebu.")
T("DexScreener", "osnove", "Besplatna stranica s cijenama, grafovima i volumenom svih tokena.",
  "Glavni izvor cijena u alatu. Male ikone pored imena tokena otvaraju ga na DexScreeneru, GMGN-u, Birdeyeu, Solscanu, "
  "RugChecku i drugdje.", alias=["dexscreener"])
T("Solscan", "osnove", "Preglednik blockchaina: tu se vidi svaka transakcija i svaki novčanik.",
  "Link 'transakcija ↗' otvara točnu kupnju ili prodaju na Solscanu, kao dokaz.", alias=["transakcija"])
T("Phantom", "osnove", "Najpopularniji Solana novčanik (aplikacija i dodatak za preglednik).",
  "Alat nikad ne traži tvoju seed frazu ni privatni ključ. Prave kupnje i lansiranje našeg tokena potpisuju se samo u "
  "tvom Phantomu.", alias=["seed fraza"])

# ---------------------------------------------------------------- ocjene alata
T("Hype ocjena", "ocjene", "0-100: koliko je pažnje token upravo dobio (volumen, kupci, X, KOL-ovi, kopije teme).",
  "Hype skener svake 2 minute gleda nove tokene i zbraja signale: rast volumena, broj kupaca, spominjanja na X-u, KOL "
  "pozive, smart money među kupcima, vrućinu tržišta. Svaki signal ima težinu koju bot sam prilagođava prema tome što je "
  "stvarno prethodilo skokovima. Hype 50+ je prag za ulaz u demo trading. Hype nije preporuka: mjeri buku, a ne sigurnost.",
  "Hype 72 = token je jedan od najglasnijih u zadnjem skenu.",
  vidi=["confidence", "sansa-za-skok", "signal", "tezina"], gdje=[("/radar", "Zadnji sken"), ("/learn", "Učenje")],
  alias=["hype", "hype max", "hype ≥ 50", "zadnji hype"])
T("Confidence", "ocjene", "0-100: koliko alat vjeruje da će token napraviti skok svoje klase.",
  "Počinje od hype ocjene, pa dodaje bodove za neovisne potvrde (X buzz, smart money, KOL, prolaz rug filtera) i oduzima za "
  "rizike. Kad alat skupi barem 200 ishoda, sam nauči koliko koja činjenica stvarno vrijedi. 55+ je visoka, 35-55 srednja, "
  "ispod 35 niska. Tokeni s niskim confidenceom se ne prikazuju.",
  "Confidence 75 = takvi tokeni skaču otprilike tri puta češće od prosječnog tokena iste klase.",
  vidi=["hype-ocjena", "sansa-za-skok", "klasa", "kalibracija"], gdje=[("/paper", "Demo trading"), ("/learn", "Učenje")],
  alias=["confidence pri ulazu", "pouzdanje"])
T("Šansa za skok", "ocjene", "0-100: confidence prilagođen tome koliko je neovisnih provjera token prošao.",
  "Token kojeg su pogledale sve analize i koji ih je prošao dobiva punu šansu; token koji je samo glasan, a ništa nije "
  "provjereno, dobiva manje. Neanalizirani sloj se ne računa kao prolaz, a svaki pad provjere oduzima. Po Šansi su poredani "
  "Pregled i Svi tokeni.", "Confidence 70, provjereno 4 od 7 slojeva, ništa nije palo → Šansa oko 55.",
  vidi=["confidence", "razina"], alias=["šansa", "sansa"])
T("Klasa", "ocjene", "Vrsta tokena po veličini i starosti, jer se različiti tokeni ponašaju različito.",
  "Moonshot: mcap ispod $150k i mlađi od 3 dana (najveći rizik i najveći mogući skok). Rizičan: između. Event: pravi token "
  "nekog događaja iz kalendara. Stabilni: mcap iznad $2M i stariji od 7 dana. Svaka klasa ima svoj cilj (što se smatra "
  "skokom) i svoja pravila.", vidi=["confidence", "event"], alias=["moonshot", "rizičan", "stabilni"])
T("Razina", "ocjene", "Dokle je token stigao u analizi: T0 → T1 → T2 → T3. Skuplje provjere dobivaju samo bolji tokeni.",
  "T0 je besplatno sito (samo prevare u mehanici tokena). T1 gleda prve kupce preko Heliusa. T2 radi pun rug filter i "
  "provjeru X-a. T3 je duboka analiza. Tako alat štedi novac: tisuće tokena prođu T0, samo desetci dođu do T3.",
  vidi=["t0", "rug-filter", "helius-krediti"], alias=["t1", "t2", "t3", "slojevita analiza"])
T("T0", "ocjene", "Prvo, besplatno sito: izbacuje samo tokene s očitom prevarom u mehanici.",
  "Pada token s aktivnim mint ili freeze pravom, nezaključanom likvidnošću izvan launchpada ili lažnim bazenom. "
  "Likvidnost ispod $10k se također odbija.", vidi=["mint-authority", "razina"])
T("Rug filter", "ocjene", "Provjera prevare prije ulaza: Helius + RugCheck podaci o tokenu i tvorcu.",
  "Presude: PROLAZI (nema zastavica), OPREZ (manje zastavice), VISOK RIZIK, ODBAČEN (tvrdi pad, npr. dev drži previše ili "
  "je već radio rugove). Ocjena kreće od 100 i svaka zastavica oduzima bodove.",
  vidi=["rug", "t0", "bundler"], alias=["rug presuda", "rug ocjena", "prolazi", "oprez", "visok rizik", "odbačen"])
T("Signal", "ocjene", "Jedna izmjerena činjenica o tokenu koja možda najavljuje skok (npr. 'KOL ga je zvao').",
  "Hype ocjena je zbroj signala, a svaki ima težinu. Na stranici Učenje vidiš koliko puta češće dolazi skok kad je signal "
  "jak: iznad 1 signal pomaže, ispod 1 smeta.", vidi=["tezina", "hype-ocjena"], alias=["signali", "izmjereno 0-1"])
T("Težina", "ocjene", "Koliko neki signal vrijedi u ocjeni. Bot je sam pomiče gore-dolje prema ishodima.",
  "Svaki dan bot provjeri koji signali su stvarno prethodili skokovima i pomakne težine, ali samo ako promjena radi bolje i "
  "na starijim i na novijim podacima (zaštita od slučajnosti). Povijest promjena je na stranici Učenje.",
  vidi=["signal", "ucenje"], alias=["težine"])
T("Konvergencija", "ocjene", "Više neovisnih izvora (KOL-ovi, Telegram kanali, smart novčanici) dira isti token u kratkom roku.",
  "Jedan poziv može biti slučajan ili plaćen; kad 3+ KOL-a zove isti token u 15 minuta, 59% se udvostruči (naspram 33%). "
  "Za konvergenciju novčanika treba barem 6 novčanika.", vidi=["kol", "smart-money"], alias=["konvergencija izvora", "grupni poziv"])
T("X buzz", "ocjene", "Token na X-u spominje barem 5 različitih autora ili barem jedan influencer s 10k+ pratitelja.",
  vidi=["kol", "hype-ocjena"])
T("Snaga", "ocjene", "Drži li token volumen i raste li mu broj holdera kroz zadnjih 6 sati.",
  "Iz očitanja svake 2 minute (puls): volumen i transakcije prema najboljem satu, rast holdera po satu i koliko su novi "
  "holderi stvarni ljudi. Token koji tone nakon prvog skoka gubi snagu.", vidi=["puls"])
T("Puls", "ocjene", "Očitanja svake 2 minute za zanimljive tokene: cijena, mcap, volumen, kupnje, prodaje, holderi.",
  vidi=["snaga"])
T("Put", "ocjene", "Oblik puta do današnjeg mcapa: koliko brzo, koliko u skokovima i koliko blizu vrha je sada.",
  "Zadržavanje 1 znači da je na vrhu; 0,3 znači da je pao na 30% vrha.")
T("Istaknuti tokeni", "ocjene", "Tokeni koje alat upravo smatra najboljima, po klasi, poredani po Šansi.",
  "Pojavljuju se na Pregledu i u Predloženim tokenima u Natjecanju. Rugani i tokeni niskog confidencea se nikad ne "
  "prikazuju.", vidi=["sansa-za-skok", "predlozeni-tokeni"], gdje=[("/", "Pregled")], alias=["istaknuti", "kandidat", "kandidati"])
T("Jaki tokeni", "ocjene", "Tokeni koji se ne ruše nakon prvog skoka nego drže vrijednost i volumen.",
  vidi=["dugorocni-token", "snaga"])

# ---------------------------------------------------------------- eventi
T("Event", "eventi", "Događaj iz stvarnog svijeta oko kojeg ljudi rade tokene (rođendan, lansiranje, izbori, viralna vijest).",
  "Kad se nešto veliko dogodi, za par minuta nastane hrpa tokena istog imena. Alat unaprijed skuplja kalendar takvih "
  "događaja, ocjenjuje koliko je pažnje oko njih (hype eventa) i koliko je vjerojatno da će netko napraviti token (šansa "
  "za token), pa traži pravi token među kopijama.",
  vidi=["hype-eventa", "sansa-za-token", "pravi-token"], gdje=[("/events", "Eventi"), ("/watch", "Prije eventa")],
  alias=["eventi", "događaj", "događaji"])
T("Hype eventa", "eventi", "0-100: koliko pažnje događaj ima u svijetu i među kripto publikom.",
  "Zbroj 7 dijelova: Slavnost (do 25), Pregledi 30 dana (do 15), Rast interesa (do 10), Polymarket volumen (do 20), Veza s "
  "kripto publikom (do 25), Ručno dodan (10) i Blizina datuma (do 5). Najviše 100. U tablici Eventi pod 'Zašto ta ocjena → "
  "raspis' vidiš koliko je koji dio dao i zašto.",
  "Trump event: Slavnost 0 (nije osoba nego oklada), Polymarket 13,7/20, Veza s kripto publikom 25/25, Blizina 5/5 → oko 44.",
  vidi=["slavnost-wikidata", "polymarket-volumen", "veza-s-kripto-publikom"], alias=["zašto ta ocjena", "raspis"])
T("Slavnost (Wikidata)", "eventi", "Do 25 bodova: koliko je osoba ili tema poznata u svijetu.",
  "Brojimo na koliko jezika Wikipedija ima članak o osobi (podatak s Wikidate). Što više jezika, to je osoba poznatija. "
  "Skala je logaritamska: 300 jezika = punih 25 bodova, 30 jezika ≈ 15 bodova. Za oklade i događaje koji nisu osoba "
  "obično je 0.", "Elon Musk ima članak na 200+ jezika → oko 23/25.",
  vidi=["hype-eventa"], alias=["slavnost", "slavnost osobe", "wikidata"])
T("Pregledi 30 dana", "eventi", "Do 15 bodova: koliko je ljudi u zadnjih 30 dana čitalo Wikipediju o toj temi.",
  "Mjeri trenutni interes, ne samo slavu. 10 milijuna pregleda = punih 15 bodova, log skala (100k ≈ 10 bodova).",
  vidi=["hype-eventa", "rast-interesa"], alias=["pregledi"])
T("Rast interesa", "eventi", "Do 10 bodova: raste li interes za temu upravo sada.",
  "Trend = pregledi zadnjih dana naspram uobičajenih. Trend 1,0× znači isto kao inače (0 bodova); 2,0× znači dvostruko "
  "više (punih 10). Tema koja naglo raste privlači i tvorce tokena.", vidi=["pregledi-30-dana"], alias=["trend"])
T("Polymarket volumen", "eventi", "Do 20 bodova: koliko je novca uloženo u oklade o tom događaju na Polymarketu.",
  "Polymarket je tržište predviđanja: ljudi se klade na ishode (npr. 'Hoće li Trump razgovarati s X do 31.10.?'). Više "
  "novca = više ljudi prati događaj. $100M = punih 20 bodova, log skala ($300k ≈ 14 bodova).",
  vidi=["trziste-predvidanja", "hype-eventa"], alias=["polymarket"])
T("Tržište predviđanja", "eventi", "Stranica (Polymarket) na kojoj se ljudi klade na ishod stvarnih događaja.",
  "Vrsta eventa 'oklada na tržištu predviđanja' znači da je događaj preuzet s Polymarketa. Takvi događaji rijetko dobiju "
  "svoj token (oko 15%), ali često spominju osobe koje kripto publika voli.",
  vidi=["polymarket-volumen"], alias=["oklada na tržištu predviđanja", "prediction market"])
T("Veza s kripto publikom", "eventi", "Do 25 bodova: tiče li se događaj osoba i tema koje kripto publika voli.",
  "Elon, Trump, Doge, SpaceX, AI, poznati memeovi i slično nose pune bodove; sport, nagrade i strana politika gotovo ništa, "
  "jer za njih memecoin publika ne mari.", vidi=["hype-eventa"], alias=["veza s kriptom"])
T("Ručno dodan", "eventi", "10 bodova ako je netko od nas ručno dodao događaj u kalendar.",
  "Ručno dodan događaj je već netko procijenio kao važan, pa dobiva bonus.", vidi=["hype-eventa"])
T("Blizina datuma", "eventi", "Do 5 bodova: što je događaj bliže, to više.",
  "Danas = 5 bodova, svaki dan dalje oduzima pola boda (za 10+ dana 0). Tokeni nastaju najčešće na sam dan.",
  vidi=["hype-eventa"])
T("Šansa za token", "eventi", "0-1: procjena koliko je vjerojatno da će netko napraviti token za ovaj događaj.",
  "Polazi od iskustva po vrsti događaja (lansiranje igre 0,8, Starship let 0,75, oklada 0,15, rutinsko lansiranje rakete "
  "0,05), pa dodaje za vezu s kripto publikom, meme riječi u naslovu, nagli skok interesa i puno vijesti. 0,45 znači "
  "otprilike 45% šanse, tj. skoro svaki drugi takav događaj dobije token.",
  "Trump oklada: vrsta 0,15 + veza s kriptom 0,30 = 0,45.", vidi=["event", "hype-eventa"])
T("Pravi token", "eventi", "Najbolje ocijenjeni token za neki događaj (★). Ostali tokeni istog imena su kopije.",
  "Za svaki event alat traži sve tokene s ključnim riječima i ocjenjuje ih (starost, likvidnost, volumen, društvene mreže). "
  "Kopije su najčešće prevare koje parazitiraju na imenu.", vidi=["event"], alias=["kopija", "★", "tokeni (★ = pravi)", "uloga"])
T("Ključne riječi", "eventi", "Riječi po kojima alat traži tokene za događaj (npr. TRUMP, STARSHIP).")
T("Vrsta događaja", "eventi", "Kakav je događaj: rođendan, obljetnica smrti, lansiranje, izdanje igre, oklada, viralna vijest…",
  "O vrsti ovisi početna šansa za token: izdanja igara i lansiranja proizvoda često dobiju token, rođendani rijetko (osim "
  "okruglih).", vidi=["sansa-za-token"], alias=["vrsta"])

# ---------------------------------------------------------------- trading
T("Demo račun", "trading", "Račun s izmišljenih $1,000 na kojem kupuješ prave tokene po pravim cijenama, bez pravog novca.",
  "Svi igrači Natjecanja kreću s $1,000. Cijene, naknade i klizanje su stvarni, pa se vidi tko bi stvarno zaradio. Bot "
  "ima svoj demo račun i natječe se s ljudima.", vidi=["stanje-racuna", "dry-run"], gdje=[("/natjecanje", "Natjecanje")],
  alias=["demo", "demo trading", "paper"])
T("Dry-run", "trading", "Način rada u kojem bot sve izračuna kao da trguje, ali ne šalje prave transakcije.",
  "Bot je namjerno u dry-run načinu: nema privatni ključ ni pravi novac.", alias=["dry run"])
T("Stanje računa", "trading", "Slobodan novac + koliko bi donijele otvorene pozicije da ih prodaš sada.",
  "Isto što i equity. Ako je iznad $1,000, igrač je u plusu. Vrijednost otvorenih pozicija računa se s naknadom i "
  "klizanjem, kao da stvarno prodaješ.", "Imaš $600 slobodno i pozicije vrijedne $550 → stanje $1,150, profit +$150.",
  vidi=["ostvareno", "neostvareno", "demo-racun"], alias=["equity", "stanje računa (equity)"])
T("Ostvareno", "trading", "Dobit ili gubitak na pozicijama koje si već prodao. Taj novac je siguran.",
  vidi=["neostvareno"], alias=["realizirano", "realiz", "realizirano sol", "ostvareno (zatvoreni)", "pnl zatvorenih"])
T("Neostvareno", "trading", "Dobit ili gubitak na pozicijama koje još držiš, po trenutnoj cijeni. Još se može promijeniti.",
  vidi=["ostvareno"], alias=["nerealizirano", "nerealiz", "nerealizirano sol", "otvoreno (live)"])
T("Pozicija", "trading", "Jedna kupnja tokena koju držiš dok je ne prodaš. Otvorena = još je držiš; zatvorena = prodana.",
  "Take profit može prodati dio pozicije, pa je 'Ostalo' koliki dio još držiš.", alias=["pozicije", "otvorena", "zatvorena",
                                                                                         "otvoreno", "zatvoreno"])
T("PnL", "trading", "Profit and Loss: dobit ili gubitak u dolarima ili SOL-u.", alias=["pnl $", "pnl sol", "profit", "profit $"])
T("ROI", "trading", "Povrat na uloženo u postocima. +100% = udvostručio si novac, −50% = izgubio si pola.",
  alias=["povrat", "roi na uloženo", "prosj. povrat"])
T("Uspješnost", "trading", "Udio zatvorenih tradeova koji su završili u plusu (win rate).",
  "Visoka uspješnost nije sve: 30% uspješnih s velikim dobicima može biti bolje od 70% uspješnih s malim.",
  alias=["win rate", "win", "pogodak (trade)"])
T("Take profit", "trading", "Automatska prodaja dijela pozicije kad dosegne zadani rast (npr. +100%).",
  "Tako se zarada osigura usput, a ostatak može dalje rasti. Nakon prvog take profita stop loss se pomakne na ulaznu "
  "cijenu, pa ta pozicija više ne može završiti u minusu.", vidi=["stop-loss", "trailing-stop"], alias=["tp", "sljedeći tp", "auto tp"])
T("Stop loss", "trading", "Automatska prodaja ako cijena padne za zadani postotak ispod ulaza, da gubitak ne bude veći.",
  vidi=["take-profit"], alias=["sl"])
T("Trailing stop", "trading", "Stop koji se penje s cijenom: prodaje kad cijena padne zadani postotak ispod najvišeg vrha.",
  "Tako se uhvati većina skoka, a izađe se čim krene ozbiljan pad.", vidi=["stop-loss"])
T("Izlaz", "trading", "Prodaja pozicije i razlog: take profit, stop loss, trailing stop, isteklo vrijeme ili rug.",
  gdje=[("/izlazi", "Izlazi")], alias=["izlazi"])
T("Ulog", "trading", "Koliko je dolara uloženo u jednu poziciju.", alias=["ulog $"])
T("Copy trading", "trading", "Alat umjesto tebe ulazi na svaki poziv odabranog influencera ili kupnju odabranog novčanika.",
  "Na stranici Copy trading odabereš KOL-a ili novčanik i pritisneš 'Prati'. Alat tada na tvoj demo račun kupi svaki "
  "njegov novi poziv star do 10 minuta (zadano $25, najviše 10 dnevno) i prodaje po pravilima izlaza. 'Prestani' "
  "zaustavlja praćenje.", vidi=["kol", "copy-ocjena"], gdje=[("/copy-trading", "Copy trading")], alias=["copy trade", "kopiraj"])
T("DCA", "trading", "Automatsko kupovanje istog tokena u jednakim dijelovima kroz vrijeme (Dollar Cost Averaging).",
  "Umjesto da sve uložiš odjednom na vrhu, alat kupuje npr. $20 svakih sat vremena 10 puta. Tako dobiješ prosječnu cijenu. "
  "Staje sam kad završi, kad ti ponestane novca, ako token rugne ili likvidnost padne ispod $5k.",
  gdje=[("/natjecanje", "Natjecanje")], alias=["automatski dca", "🔄 automatski dca"])
T("Predloženi tokeni", "trading", "Tokeni koje alat predlaže za kupnju u Natjecanju, s gumbima za brzu kupnju.",
  "Fartcoin, Useless, najbolji jaki i dugoročni tokeni i 3 najbolja nova kandidata.", vidi=["istaknuti-tokeni"],
  alias=["⭐ predloženi tokeni"])
T("Serija", "trading", "Koliko zadnjih zatvorenih tradeova zaredom je bilo u plusu (🔥) ili minusu (🧊).")
T("Ljestvica", "trading", "Poredak igrača Natjecanja po stanju računa.", alias=["podij"])
T("Sesija", "kol", "Doba dana po tome koje tržište je budno: Azija, Europa ili SAD.",
  "Azija 00-08 UTC, Europa 08-14 UTC, SAD 14-24 UTC. Iz podataka: KOL signali su najbolji u SAD sesiji, a ulazi najgori.",
  alias=["sesije", "azija", "europa", "sad"])

# ---------------------------------------------------------------- KOL metrike
T("Moć poziva", "kol", "0-100: koliko KOL-ovi pozivi u prosjeku pomaknu cijenu i volumen.",
  "Sastoji se od: Pogodak (koliko poziva naraste 50%+ u 24 h), Rast 24 h, Rast 1 h, Volumen (koliko kupaca post dovede), "
  "Prvi (je li prvi zvao token) i Bez ruga; Kasni pozivi oduzimaju. Dok KOL nema puno izmjerenih poziva, ocjena je bliže "
  "35 (ne vjerujemo mu još). Raspis je na stranici svakog KOL-a pod 'Kako je dobio ocjenu'.",
  "Moć 70 = jedan od jačih KOL-ova; njegovi pozivi u pravilu pomaknu token.",
  vidi=["pogodak", "volumen-x", "kasni-pozivi", "moc-po-pratitelju"], gdje=[("/kol", "KOL-ovi")],
  alias=["moć objava (bot)", "moć"])
T("Moć po pratitelju", "kol", "Pomiče li KOL tržište više ili manje nego što bi njegov broj pratitelja dao očekivati.",
  "1× = kao prosječan KOL s toliko pratitelja; 2× = pomiče dvostruko više. Mali KOL s velikom moći po pratitelju je "
  "zlata vrijedan jer ga gomila još nije otkrila.", vidi=["moc-poziva"], alias=["moć/pratitelj"])
T("Pogodak", "kol", "Udio poziva nakon kojih je token barem +50% u 24 h.",
  "Pogodak 40% znači da je 4 od 10 njegovih poziva u 24 sata narastao barem pola.", vidi=["moc-poziva"],
  alias=["točnost signala", "pogodak (volumen)", "hit rate"])
T("Rast 24 h", "kol", "Najveći rast cijene u 24 h nakon poziva (vrh, ne cijena na kraju).",
  "Pokazuje koliko je bilo moguće zaraditi da si izašao na vrhu. Medijan preko svih poziva je u ocjeni.",
  alias=["max 24 h", "medijan max 24 h", "signal max 24 h", "volumen max 24 h"])
T("Volumen ×", "kol", "Volumen u satu nakon posta podijeljen s volumenom sat prije: koliko je post doveo kupaca.",
  "8× znači da se nakon posta trgovalo osam puta više nego prije. '50×+' znači da sat prije gotovo nije bilo trgovanja.",
  vidi=["volumen"], alias=["medijan volumen ×", "volumen x"], k="volumen-x")
T("Kasni pozivi", "kol", "Pozivi objavljeni kad je cijena već bila udvostručena u 2 h prije posta.",
  "KOL koji zove tek nakon skoka ili hvata vrh ili je plaćen da dovede kupce za nečiju prodaju. Kasni pozivi oduzimaju "
  "bodove.", vidi=["insajder", "moc-poziva"], alias=["kasni", "2 h prije"])
T("Prvi", "kol", "Udio poziva u kojima je KOL prvi autor kojeg smo vidjeli na tom tokenu.",
  "Tko zove prvi, pronalazi tokene sam; tko je uvijek treći, vjerojatno prepisuje.")
T("Bez ruga", "kol", "Koliko rijetko KOL-ovi tokeni padnu 90%+. Više rugova = manje bodova.")
T("Engagement", "kol", "Koliko publika stvarno reagira: (lajkovi + 2× repostovi) / pratitelji.",
  "Na X-u je 1% već dobro. Puno pratitelja a malo reakcija = kupljeni pratitelji.", alias=["angažman"])
T("Pregledi objave", "kol", "Koliko je ljudi vidjelo post. Bolje predviđa skok od broja pratitelja.",
  alias=["medijan pregleda", "pregleda"])
T("Koliko ga tržište sluša", "kol", "Tablica: što se dogodilo s volumenom i cijenom nakon svakog posta i tko je zvao poslije.",
  "Ako nakon njegovih postova volumen skače i drugi KOL-ovi ga slijede, KOL stvarno pokreće tržište.")
T("Bot račun", "kol", "Automatski ili promo račun koji objavljuje svaki novi token po predlošku. Nije pravi KOL.",
  "Njegove objave ne ulaze u ljestvicu, copy trading ni signale, ali brojke na njegovoj stranici se i dalje vide.",
  alias=["bot", "automatska objava"])
T("Zona", "kol", "Procjena vremenske zone KOL-a iz sati kad objavljuje (najtiših 6 h je njegova noć).")
T("KOL test", "kol", "7-dnevni pokus: $50 na svaki svjež KOL poziv, da vidimo isplati li se ući odmah.",
  gdje=[("/kol-test", "KOL test")])

# ---------------------------------------------------------------- walleti
T("Ocjena profitabilnosti", "walleti", "0-100: koliko novčanik stvarno zarađuje (PnL, ROI, uspješnost, profit factor, 2x tradeovi).",
  "Računa se iz svih njegovih kupnji i prodaja u zadnjih 30-60 dana. Visoka ocjena = dosljedno zarađuje, a ne jednom imao "
  "sreće.", vidi=["copy-ocjena", "profit-factor"], alias=["ocjena", "raspis ocjene profitabilnosti (0-100)"])
T("Copy ocjena", "walleti", "0-100: koliko se isplati kopirati novčanik. Profitabilnost minus kazne za stvari koje se ne daju kopirati.",
  "Kazne: prebrzo trguje (ne stigneš ga kopirati), kupuje premale iznose, sva zarada iz jednog tradea, neaktivan, izgleda "
  "kao bot. Copy 60+ je tier A.", vidi=["tier", "copy-lista", "ocjena-profitabilnosti"], alias=["copy", "raspis copy ocjene"])
T("Tier", "walleti", "Razred novčanika: A (copy 60+, provjera svakih 6 h), B (dobar), C (ostali), D (bot ili u minusu).",
  vidi=["copy-ocjena"])
T("Copy lista", "walleti", "Novčanici koji prolaze sve uvjete da ih vrijedi kopirati.", alias=["na listi", "na listi?"])
T("Profit factor", "walleti", "Ukupni dobici podijeljeni s ukupnim gubicima. Iznad 1 = zarađuje; 2 = zaradi dvostruko više nego izgubi.")
T("Rano u pobjednicima", "walleti", "U koliko tokena koji su kasnije narasli je novčanik ušao među prvim kupcima.",
  alias=["rano u pobj."])
T("Rotacijski dev", "walleti", "Novčanik koji na 3+ tokena kupi prije KOL poziva i proda u poziv. Upozorenje, ne signal.",
  vidi=["insajder"], alias=["rotacijski devovi"])
T("KOL novčanik", "walleti", "Javno poznat novčanik nekog KOL-a. Vidimo što stvarno kupuje, ne samo što objavljuje.",
  alias=["kol novčanici", "kol walleti"])
T("Klaster", "grupe", "Skupina novčanika koji izgledaju kao jedan vlasnik ili ekipa (isti izvor novca, iste kupnje u istoj sekundi).",
  alias=["klasteri", "grupa walleta"])
T("Financijer", "grupe", "Novčanik koji je poslao SOL drugim novčanicima prije njihovih kupnji. Često je glava klastera.")
T("KOL grupa", "grupe", "KOL-ovi koji opetovano zovu iste tokene unutar 30 minuta.",
  "Ako grupa zajedno zove token, šansa za 2x je veća nego kad zove jedan član. Vođa je onaj koji najčešće zove prvi.",
  alias=["kol grupe", "grupa"])
T("Organiziranost", "grupe", "0-100: koliko grupa izgleda kao jedna ekipa. 60+ alat prati automatski.")

# ---------------------------------------------------------------- dugoročni
T("Dugoročni token", "dugo", "Stariji token (3+ tjedna, $5M+ mcap, $100k+ dnevni volumen) koji preživljava i raste.",
  "Sigurniji sloj od lova na nove tokene: uzor su Fartcoin i Useless. Alat traži tokene koji se oporavljaju od padova, "
  "rastu brže od SOL-a i kojima broj holdera ne pada. Tjedno gleda i top 20 holdera i koliko drže burze.",
  vidi=["cex", "jaki-tokeni"], gdje=[("/dugorocno", "Dugoročni")], alias=["dugoročni", "dugoročni tokeni"])

# ---------------------------------------------------------------- naš token
T("Trezor", "nastoken", "Zajednički novčanik u koji igrači uplaćuju za lansiranje našeg tokena. Alat čita stanje svakih 10 min.",
  "Ključ trezora je samo u Phantomu vlasnika; alat ga nikad ne vidi. Svaki igrač upiše adresu s koje šalje, pa se vidi tko "
  "je koliko uplatio.", gdje=[("/nas-token", "Naš token")], alias=["vault", "sef"])
T("Ponuda", "nastoken", "Ukupan broj tokena koji postoje (supply) i kako su podijeljeni (tim, likvidnost, marketing).",
  alias=["supply"])
T("First buy", "nastoken", "Prva kupnja našeg tokena odmah pri lansiranju na pump.fun, da tim dobije dio po najnižoj cijeni.")
T("MiCA", "nastoken", "EU pravila za kripto. Uz HANFA-u i porez (12%) i oznaku #ad za plaćene objave, važno za naš token.")

# ---------------------------------------------------------------- sustav
T("Učenje", "sustav", "Alat svaki dan iz ishoda sam mijenja težine signala, pragove i ocjene, uz zaštitu od slučajnosti.",
  "Promjena se primijeni samo ako radi bolje i na starijim i na novijim podacima. Povijest svih promjena je na stranici "
  "Učenje.", vidi=["tezina", "kalibracija", "rug-profil"], gdje=[("/learn", "Učenje")])
T("Kalibracija", "sustav", "Provjera odgovaraju li brojevi stvarnosti: skaču li tokeni s confidenceom 70 stvarno češće od onih s 40.",
  vidi=["confidence"])
T("Rug profil", "sustav", "Naučeni opis kako izgledaju tokeni koji rugnu, da se sljedeći izbace prije ulaza.",
  "Uči se dnevno kad ima barem 30 rugova; pravilo se uključi samo ako je točno 85%+ i izgubi najviše 5% dobrih tokena.",
  vidi=["rug"])
T("Režim tržišta", "sustav", "0-100 i vruće/neutralno/hladno: koliko je memecoin tržište živo (volumen launchpada i DEX-a).",
  gdje=[("/market", "Tržište")], alias=["režim", "market_regime"])
T("Helius krediti", "sustav", "Plaćeni podaci s blockchaina (Helius). Imamo 10M kredita mjesečno; alat sam pazi da ne potroši previše.",
  gdje=[("/usage", "Potrošnja")], alias=["helius", "kredita", "helius kredita"])
T("Apify", "sustav", "Plaćeni servis koji čita X (Twitter) za nas. Ograničen na oko $100 mjesečno.",
  gdje=[("/usage", "Potrošnja")])
T("Jutarnji izvještaj", "sustav", "Dnevni sažetak svega bitnog, napisan svako jutro prije 8 h.",
  gdje=[("/izvjestaj", "Jutarnji izvještaj")])


def _merge_help():
    """Every column explanation from ui/help.py is also a glossary entry (category 'stupci') unless a hand-written
    term already covers that label."""
    from ui.help import HELP
    idx = _index()
    for label, text in HELP.items():
        if norm(label) in idx:
            continue
        k = slug(label)
        while k in TERMS:
            k += "-s"
        TERMS[k] = {"k": k, "name": label, "cat": "stupci", "short": text, "long": "", "primjer": "", "vidi": [],
                    "gdje": [], "alias": []}
        idx[norm(label)] = k


def _merge_pages():
    """One entry per page from the menu + its intro box."""
    from ui import html as H
    for sec, items in H.SECTIONS:
        for p in items:
            intro = H.INTRO.get(p["href"])
            k = "str-" + slug(p["href"]) if p["href"] != "/" else "str-pregled"
            long = (f"{intro[0]}. {intro[1]}\n\nUloga u cjelini: {intro[2]}" if intro else "")
            TERMS[k] = {"k": k, "name": f"Stranica: {p['name']}", "cat": "stranice", "short": p["desc"], "long": long,
                        "primjer": "", "vidi": [], "gdje": [(p["href"], f"Otvori {p['name']}")], "alias": [],
                        "href": p["href"], "section": sec}


_IDX = None


def _index():
    idx = {}
    for k, t in TERMS.items():
        idx.setdefault(norm(t["name"]), k)
        for a in t["alias"]:
            idx.setdefault(norm(a), k)
    return idx


def index():
    """{normalised label: key} for every term, alias and column."""
    global _IDX
    if _IDX is None:
        _merge_help()
        _merge_pages()
        _IDX = _index()
    return _IDX


def lookup(label):
    """Key of the term behind a label as shown on a page, or None."""
    return index().get(norm(label))


def get(k):
    index()
    return TERMS.get(k)


def page_key(path):
    """Glossary key of the page a path belongs to (detail pages map to their menu page)."""
    from ui import html as H
    index()
    href = H.nav_item(path)
    if not href:
        return None
    k = "str-" + slug(href) if href and href != "/" else "str-pregled"
    return k if k in TERMS else None


def all_terms():
    index()
    return list(TERMS.values())
