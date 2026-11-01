"""Marketing strategy for our token (/nas-token/strategija): from idea to the first months, built on research done
1.11.2026 (guides, case studies, pump.fun data, newsletters; sources in SOURCES) plus what our own bot measures.

Plain data so the page stays a renderer. {SYM} is replaced with the chosen project's ticker.
"""

SUMMARY = [
    "Meme tokeni žive od pažnje i zajednice, ne od proizvoda. Pobjeđuje token koji izgleda kao dio kulture, a ne "
    "kao reklama koja od nje uzima.",
    "Odlučuju prva 72 sata. Manje od 2% tokena na pump.fun ikad napuni krivulju, pa sve mora biti spremno prije "
    "lansiranja: priča, slike, web, grupa i dogovoreni influenceri.",
    "Najbolji meme se može remiksati. WIF je imao kapu koju svatko stavlja na sve, a Useless ponosno \"ne radi "
    "ništa\". Ljudi sami rade sadržaj i to je besplatan marketing.",
    "Bolji je influencer kojem publika razumije šalu nego najveći influencer. Naši podaci to potvrđuju: val od "
    "3+ influencera u 15 minuta vrijedi više od jedne velike objave.",
    "Povjerenje je marketing: isključen mint i freeze, javne adrese tima, postupna isplata influencerima i "
    "označene plaćene objave. Lažni volumen i botovi kupce tjeraju.",
    "Claude Code skraćuje tjedne posla na dane: web stranicu, generator memeova, Telegram bota, mini igricu i "
    "dnevni plan objava.",
]

CONCEPTS = [
    {"name": "$RADAR, meme token koji ima svog bota",
     "story": "Jedini meme coin čiji vlasnici imaju vlastiti radar za tokene. Maskota je mali radar-pas koji "
              "\"njuši\" rugove. Šala je da token koji upozorava na rugove nikad ne može biti rug: mint i freeze "
              "su isključeni, a adrese tima su javne.",
     "use": "Tko drži npr. 100k tokena, dobiva pristup MemeSonar natjecanju, jutarnjem izvještaju i tablici "
            "\"Rug ili ne\". Stvarna korist od alata koji već imamo.",
     "why": "Ima priču, korist i sadržaj koji se sam piše: svaki dan bot nađe nove rugove, a to su gotove objave.",
     "best": True},
    {"name": "$POMALO, token koji se nikad ne žuri",
     "story": "Dalmatinsko \"pomalo\" protiv kripto pohlepe: dok svi jure 100x, mi ležimo u hladu. Maskota je "
              "magarac s naočalama na rivi.",
     "use": "Natječaj \"najsporiji holder\": nagrada iz trezora tima ide onome tko najduže ne proda.",
     "why": "Lako se remiksa (magarac u svakoj situaciji), simpatičan je i izvan kripta i odgovara diaspori i "
            "turistima. Rizik je da je preuzak za globalnu publiku.",
     "best": False},
    {"name": "$RUGORNOT, igra pogađanja",
     "story": "Token je ulaznica za igru: svaki dan 10 pravih novih tokena iz našeg skenera, a ti pogađaš koji će "
              "biti rug. Rezultat se otkrije za 24 h.",
     "use": "Za igranje treba držati token. Najbolji tjedni pogađači dobivaju tokene iz trezora tima.",
     "why": "Igra je od prvog dana pokretač sadržaja (\"danas je 7/10 bilo rugova\"), a podatke već imamo.",
     "best": False},
]

GAMES = [
    ("🎯 Rug ili ne", "Kviz od 10 pravih tokena dnevno iz našeg skenera, s tablicom najboljih. Podaci su već tu, "
                      "Claude Code napravi stranicu za 1-2 dana.", "besplatno"),
    ("🐶 Tapni maskotu (Telegram mini app)", "Jednostavna igra u Telegramu, rezultat se dijeli u grupi. Najbolji "
                                             "tjedno dobivaju tokene. Tap igre (Hamster Kombat, DOGS) su tako "
                                             "skupile milijune korisnika.", "besplatno (hosting Netlify)"),
    ("🖼 Generator memeova s maskotom", "Upišeš situaciju, a AI nacrta maskotu u njoj s našim logom. Svaka "
                                       "slika je besplatan oglas.", "~$5-20/mj za AI slike"),
    ("🏆 Holder ljestvica i značke", "Javna stranica: tko drži najduže dobiva značku \"dijamantne ruke\". "
                                    "Čita se s blockchaina preko Heliusa.", "besplatno (Helius već plaćamo)"),
    ("📈 Predviđanja", "Pogodi gdje će biti {SYM} ili SOL u petak. Bez uloga, samo bodovi i nagrade iz trezora "
                      "tima.", "besplatno"),
]

# (phase, [(when, what, who)])  who = role index 1-4
TIMELINE = [
    ("Faza 0 · Ideja i identitet (T-14 do T-8 dana)", [
        ("dan 1", "Odabrati koncept i maskotu, napisati priču u 3 rečenice i jednu rečenicu za bio.", "svi"),
        ("dan 1-2", "Ime, ticker i provjera da ih nitko nema (DexScreener, pump.fun, X).", "1"),
        ("dan 2-4", "Maskota u 10 poza, logo, banner za X i Telegram (AI + Claude Code).", "2"),
        ("dan 3-5", "Web stranica (Claude Code, Netlify besplatno): priča, raspodjela supplyja, adrese tima, linkovi, "
                    "\"kako kupiti\".", "1"),
        ("dan 4-6", "X račun, Telegram grupa (razgovor) + kanal (objave), bot dobrodošlice i zaštita od spama.", "3"),
        ("dan 5-7", "Popis 10-15 influencera iz tablice ispod; prvi kontakt i dogovor s postupnom isplatom.", "4"),
    ]),
    ("Faza 1 · Zagrijavanje (T-7 do T-1)", [
        ("svaki dan", "3 objave na X-u (memeovi, priča maskote, \"nešto dolazi\"), bez adrese tokena.", "2"),
        ("svaki dan", "Odgovarati ispod većih Solana računa: duhovito i bez spama, s maskotom kao profilnom.", "3"),
        ("T-5", "Banka od 30 memeova i 5 kratkih videa spremna za dan lansiranja i prvi tjedan.", "2"),
        ("T-3", "Igra ili generator memeova uživo (Claude Code), da ljudi imaju što raditi prvi dan.", "1"),
        ("T-2", "Potvrditi termin s influencerima: točno vrijeme, tekst je njihov, oznaka #ad.", "4"),
        ("T-1", "Probno lansiranje na testnoj mreži (gumb 🧪), provjera slike i linkova, pinana pravila u grupi.", "1"),
    ]),
    ("Faza 2 · Dan lansiranja (sat po sat)", [
        ("H-1", "Svi online. Objava \"za sat vremena\" na X-u i u grupi.", "svi"),
        ("H0", "Lansiranje gumbom 🚀 u najbolje vrijeme iz naših podataka; odmah objaviti adresu svugdje.", "1"),
        ("H0-H0:15", "Val influencera: svi dogovoreni objavljuju u istih 15 minuta.", "4"),
        ("H0-H2", "Grupa: dobrodošlica svakom novom, odgovori na pitanja, pinana adresa i upozorenje na lažne "
                  "linkove.", "3"),
        ("H0-H6", "Svakih 30-60 min novi meme ili video, retweet svakog tko spomene token.", "2"),
        ("H1", "Objava: mint i freeze isključeni, adrese tima, link na Solscan; povjerenje privlači kupce.", "1"),
        ("H2+", "Gledati Naš token stranicu: kupnje/prodaje, top 10 novčanika, volumen; prilagoditi objave.", "4"),
    ]),
    ("Faza 3 · Prva 72 sata", [
        ("dan 1-3", "Space na X-u svaku večer (30 min, ugostiti jednog influencera).", "3"),
        ("dan 1-3", "Natječaj za memeove (nagrada iz trezora tima), najbolji idu na službeni račun.", "2"),
        ("dan 2", "Ako volumen raste: DexScreener profil ($299) i jedan boost ($99).", "1"),
        ("dan 3", "Drugi val influencera (oni koji nisu bili u prvom), opet u istih 15 minuta.", "4"),
    ]),
    ("Faza 4 · Tjedni 1-4", [
        ("tjedno", "Jedna nova stvar tjedno (igra, značke, predviđanja), da uvijek ima vijesti.", "1"),
        ("tjedno", "Izvještaj zajednici: holderi, volumen, što je napravljeno, što slijedi.", "4"),
        ("dan 7+", "Prijava na CoinGecko i Jupiter popis tokena (besplatno).", "1"),
        ("stalno", "60% zabava (memeovi, maskota), 30% napredak zajednice, 10% podaci tokena.", "2"),
        ("stalno", "Influencerima tjedna isplata 25% dogovorenog, samo za odrađene objave.", "4"),
    ]),
]

FREE = [
    ("Memeovi i kratki videi (X, TikTok, Reels)", "najjači besplatni kanal; maskota koja se remiksa radi sama"),
    ("Odgovori ispod velikih Solana računa", "pažnja bez plaćanja; ljudski i duhovito, nikad botovima"),
    ("Telegram grupa + natječaji za pozivnice", "zadržava kupce; vodiči navode da grupe s 200+ aktivnih nakon tjedan dana češće prežive (procjena agencija)"),
    ("Spaces na X-u", "jedan sat razgovora = povjerenje; ugostiti manje influencere besplatno"),
    ("Suradnja s drugim zajednicama", "zajedničke objave i natječaji s tokenima slične šale"),
    ("Igra / generator memeova", "ljudi imaju što raditi i dijele rezultate"),
    ("CoinGecko, Jupiter, DexScreener osnovni podaci", "besplatni popisi, tamo ljudi traže token"),
    ("Naljepnice i grafiti s QR kodom (gerilski)", "lokalno i za fotke na X-u; pazi na zakon o oglašavanju"),
]

PAID = [
    ("Influenceri: dio supplyja kroz 4 tjedna", "0.5-1.5% po influenceru", "najveći pojedinačni utjecaj ako je publika prava"),
    ("Influenceri: plaćena objava", "~$50-500 po objavi (manji računi)", "provjeriti angažman: ispod 1% znači puno botova"),
    ("DexScreener profil", "$299", "logo i linkovi tamo gdje kupci gledaju; tek kad ima volumena"),
    ("DexScreener boost", "$99+", "kratko trending mjesto; samo uz val objava"),
    ("AI slike/video za maskotu", "~$5-20/mj", "puno sadržaja brzo"),
    ("Oglasne mreže za kripto (banneri)", "od ~$100", "slabije za meme tokene; tek za mjesec 2+"),
]

ROLES = [
    ("1 · Voditelj i blockchain", "Nicholas", [
        "trezor, lansiranje gumbom, adrese tima, CoinGecko/Jupiter prijave",
        "web stranica i igre s Claude Codeom", "odluke o budžetu (plaćeni boost, DexScreener)"]),
    ("2 · Sadržaj", "igrač 2", [
        "maskota, memeovi, videi; banka sadržaja unaprijed", "3+ objave dnevno na X-u, 3 tjedno na TikToku",
        "natječaji za memeove"]),
    ("3 · Zajednica", "igrač 3", [
        "Telegram grupa: dobrodošlica, pitanja, zaštita od prevaranata", "Spaces na X-u",
        "odgovori ispod velikih računa (ručno, bez botova)"]),
    ("4 · Influenceri i brojke", "igrač 4", [
        "popis i dogovori s influencerima iz tablice, tjedne isplate", "praćenje stranice Naš token (holderi, volumen)",
        "tjedni izvještaj zajednici"]),
]

# Claude Code: (what, how long, prompt to paste)
CLAUDE = [
    ("Web stranica (landing)", "1-2 h",
     "Napravi jednostranični web za meme token {SYM}: hero s maskotom, priča u 3 rečenice, raspodjela supplyja "
     "(graf), adrese tima i trezora s linkovima na Solscan, kako kupiti u 3 koraka (Phantom, pump.fun), linkovi na "
     "X i Telegram, upozorenje da je meme bez obećanja zarade. Statični HTML/CSS, mobitel prvo, spremno za Netlify."),
    ("Generator memeova", "pola dana",
     "Napravi web generator memeova za {SYM}: korisnik odabere pozu maskote (10 PNG slika), upiše gornji i donji "
     "tekst, preuzme sliku 1080x1080 s malim logom {SYM}. Canvas u pregledniku, bez servera."),
    ("Telegram bot za grupu", "pola dana",
     "Napravi Telegram bota u Pythonu za grupu {SYM}: dobrodošlica s pravilima i službenom adresom, /cijena "
     "(DexScreener API), /kupi (upute), brisanje poruka s linkovima koje nisu na bijeloj listi, mute za spam. "
     "Token bota iz varijable okoline."),
    ("Igra \"Rug ili ne\"", "1-2 dana",
     "Na postojećem MemeSonar dashboardu dodaj stranicu /rug-ili-ne: svaki dan 10 tokena iz hype.db starih 24-48 h, "
     "igrač pogađa rug ili ne, rezultat iz rug podataka, ljestvica tjedna. Testovi bez mreže."),
    ("Telegram mini igra", "1-2 dana",
     "Napravi Telegram Mini App igru: tapni maskotu {SYM} što brže u 30 sekundi, rezultat se dijeli u grupu, "
     "tjedna ljestvica. HTML5 + Telegram WebApp SDK, hosting na Netlify."),
    ("Plan objava za 30 dana", "30 min",
     "Napiši 90 objava za X za meme token {SYM} (priča: ...): 60% humor s maskotom, 30% zajednica, 10% podaci. "
     "Kratko, bez obećanja zarade, s idejom za sliku uz svaku. Tablica: dan, sat, tekst, slika."),
    ("Holder ljestvica i značke", "1 dan",
     "Dodaj na MemeSonar stranicu koja preko Helius getTokenLargestAccounts i povijesti transakcija pokazuje "
     "holdere {SYM} s danima držanja i značkama (7, 30, 90 dana)."),
    ("Kratki opis i lite paper", "1 h",
     "Napiši lite paper od 1 stranice za {SYM}: priča, maskota, raspodjela supplyja, što zajednica radi (igre, "
     "natječaji), jasno da nema obećanja zarade ni plana za cijenu, rizici."),
]

KPIS = [
    ("Holderi", "raste svaki dan prvi tjedan", "stagnira 2 dana: novi natječaj ili val objava"),
    ("Aktivni u Telegramu", "200+ dnevno nakon 7 dana", "ispod 50: više Spacesa, igra, pozivnice s nagradom"),
    ("Volumen / tržišna vrijednost", "iznad 10% dnevno", "ispod: novi val 3+ influencera"),
    ("Top 10 novčanika", "ispod 25% supplyja", "iznad 35%: raspodjela kroz natječaje, objasniti adrese"),
    ("Kupnje / prodaje", "više kupnji", "više prodaja 2 dana: provjeriti tko prodaje, odgovoriti zajednici"),
]

DONT = [
    "Ne kupovati lažni volumen ni pratitelje: alati (i naš) to vide, kupci odlaze.",
    "Ne raditi \"raidove\" botovima. Ljudi da, automatizirani spam ne (pravila X-a i povjerenje).",
    "Ne obećavati zaradu, cijenu ni \"100x\". To je i pravni rizik (MiCA, HANFA).",
    "Ne davati influencerima sve tokene unaprijed: prodaju odmah i sruše cijenu.",
    "Ne skrivati adrese tima. Pinati službene linkove, jer najviše štete rade prevaranti koji glume tim.",
    "Ne lansirati bez gotovog sadržaja za prva 3 dana.",
]

SOURCES = [
    ("Solana Compass: 42.000 tokena dnevno, ispod 2% završi na DEX-u",
     "https://solanacompass.com/news/pumpfun-launched-42000-tokens-in-one-day-fewer-than-2-will-ever-reach-a-dex"),
    ("SolTokenCreator: studije uspješnih Solana meme lansiranja (WIF, BONK)",
     "https://www.soltokencreator.io/blog/successful-solana-meme-coin-case-studies"),
    ("SolTokenCreator: pump.fun graduation", "https://www.soltokencreator.io/blog/pump-fun-graduation-explained"),
    ("Yellow: zašto ljudi kupuju token koji se zove beskoristan (Useless)",
     "https://yellow.com/news/why-traders-keep-buying-a-token-that-calls-itself-useless"),
    ("arXiv: studija Solana meme tokena", "https://arxiv.org/html/2512.11850v3"),
    ("Luv Kaizen: okvir meme marketinga 2026", "https://www.luvkaizen.com/blogs/meme-coin-marketing-strategy"),
    ("TokenMinds: meme coin marketing 2026", "https://tokenminds.co/blog/meme-coin-marketing"),
    ("TokenMinds: lansiranje na bonding krivulji", "https://tokenminds.co/blog/bonding-curve-token-launches"),
    ("Coinbound: kako lansirati meme coin", "https://coinbound.io/launch-a-memecoin/"),
    ("Flexe: Telegram grupe za meme tokene", "https://flexe.io/blog/meme-coin-telegram-groups/"),
    ("Variant (Li Jin): kripto kao ekonomija pažnje",
     "https://variant.fund/articles/crypto-next-iteration-attention-economy/"),
    ("Metaplex: $TRUMP i ekonomija pažnje",
     "https://www.metaplex.com/blog/articles/-trump-a-lesson-about-memecoins-and-the-attention-economy"),
    ("Cryptonary: organski vs korporativni meme tokeni",
     "https://cryptonary.com/research/corporate-vs-organic-memecoins-dont-become-exit-liquidity-for-vcs"),
    ("Yellow: što poslije airdropova", "https://yellow.com/research/what-comes-after-airdrops-building-sustainable-crypto-communities-in-2025"),
    ("Cointelegraph: rizici utrke za pažnjom", "https://cointelegraph.com/magazine/pump-fun-go-bounty-memecoin-risks"),
    ("PumpPortal: kreiranje tokena", "https://pumpportal.fun/creation"),
]
