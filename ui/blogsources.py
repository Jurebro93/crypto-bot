"""Outside sources for the editorial pages (blog posts and public glossary terms), 23 November 2026.

Every URL here was fetched on 23.11.2026 and the page was read: it loads and says what the "supports" text claims.
docs/seo/izvori_2311.md lists the same URLs with where each one is used (scripts/izvori_md.py writes it from this
file) and tests/test_urednicki_izvori_offline.py checks that no editorial page links outside without the URL being listed there.
Rules: official docs, regulators, research with data; no affiliate links, no competitors' sales pages.
External links render like the rest of the site's outbound links: rel="nofollow noopener" target=_blank.
"""
from ui.html import esc

VERIFIED = "2026-11-23"
REL = 'rel="nofollow noopener" target=_blank'

# key -> (url, publisher, title, supports EN, supports HR)
S = {
    # regulators and consumer warnings
    "esma_mica": ("https://www.esma.europa.eu/esmas-activities/digital-finance-and-innovation/markets-crypto-assets-regulation-mica",
                  "ESMA", "Markets in Crypto-Assets Regulation (MiCA)",
                  "Firms that served crypto clients under national law before 30 December 2024 could continue only until 1 July 2026 or until their MiCA authorisation is granted or refused.",
                  "Firme koje su kripto usluge pružale po nacionalnom zakonu prije 30. 12. 2024. smjele su nastaviti najkasnije do 1. 7. 2026. ili do odluke o MiCA odobrenju."),
    "hanfa_casp": ("https://www.hanfa.hr/registri/trziste-kriptoimovine/registar-drustava-ovlastenih-pruzati-usluge-povezane-s-kriptoimovinom/",
                   "HANFA", "Registar društava ovlaštenih pružati usluge povezane s kriptoimovinom",
                   "The Croatian supervisor's register of firms authorised to provide crypto-asset services.",
                   "Hanfin registar društava ovlaštenih pružati usluge povezane s kriptoimovinom."),
    "esas_warning": ("https://www.esma.europa.eu/press-news/esma-news/eu-financial-regulators-warn-consumers-risks-crypto-assets",
                     "ESMA / EBA / EIOPA", "EU financial regulators warn consumers on the risks of crypto-assets (17 March 2022)",
                     "The three EU supervisory authorities warn that many crypto-assets are highly risky and speculative.",
                     "Tri europska nadzorna tijela upozoravaju da je velik dio kriptoimovine izrazito rizičan i špekulativan."),
    "fca_basics": ("https://www.fca.org.uk/investsmart/crypto-basics", "UK Financial Conduct Authority", "Crypto: the basics",
                   "If you invest in crypto, be prepared to lose all the money you put in.",
                   "Tko ulaže u kripto, mora biti spreman izgubiti sav uloženi novac."),
    "fca_derivs": ("https://www.fca.org.uk/news/press-releases/fca-bans-sale-crypto-derivatives-retail-consumers",
                   "UK Financial Conduct Authority", "FCA bans the sale of crypto-derivatives to retail consumers",
                   "The UK regulator banned crypto derivatives for retail consumers because of the harm they pose.",
                   "Britanski regulator zabranio je kripto derivate malim ulagačima zbog štete koju im nanose."),
    "investor_pd": ("https://www.investor.gov/protect-your-investments/fraud/types-fraud/pump-dump-schemes",
                    "Investor.gov (U.S. SEC)", "Pump and dump schemes",
                    "A pump and dump first pushes the price up with false or misleading claims, then the promoters sell their holdings into the buyers.",
                    "Pump and dump prvo lažnim ili obmanjujućim tvrdnjama digne cijenu, a zatim promotori prodaju svoje udjele kupcima."),
    "investor_social": ("https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-alerts/social-media-and-investment-fraud-investor-alert",
                        "Investor.gov (U.S. SEC)", "Social media and investment fraud: investor alert",
                        "Fraudsters pay social media influencers and celebrities to tout investments; information on social media may be inaccurate or misleading.",
                        "Prevaranti plaćaju influencere i poznate osobe da hvale ulaganje; informacije s društvenih mreža mogu biti netočne ili obmanjujuće."),
    "cftc_pd": ("https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/beware_virtual_currency_pump_dump.html",
                "U.S. CFTC", "Customer advisory: beware virtual currency pump-and-dump schemes",
                "Pump-and-dump groups organise in chat rooms with thousands of members and hype tokens on social media; do not buy on social media tips or sudden price spikes.",
                "Pump-and-dump grupe organiziraju se u chat sobama s tisućama članova i napuhuju tokene na mrežama; ne kupuj na savjet s mreža ni na nagli skok cijene."),
    "porezna_joppd": ("https://porezna-uprava.gov.hr/hr/primjer-podnosenja-obrasca-joppd-za-primitke-po-osnovi-trgovanja-kriptoimovinom/8342",
                      "Porezna uprava", "Primjer podnošenja Obrasca JOPPD za primitke po osnovi trgovanja kriptoimovinom (6. 2. 2026.)",
                      "Croatian Tax Administration: a gain on crypto held more than two years is not taxed, but it must still be reported on the JOPPD form for the year it was made.",
                      "Porezna uprava: dobitak od kriptoimovine držane dulje od dvije godine ne oporezuje se, ali se i dalje iskazuje Obrascem JOPPD za godinu u kojoj je ostvaren."),
    # official documentation
    "spl_token": ("https://spl.solana.com/token", "Solana Program Library", "Token program documentation",
                  "A Solana token has a mint authority that can create new supply (and can be disabled) and an optional freeze authority that can freeze token accounts.",
                  "Solana token ima mint authority koja može stvarati novu količinu (i može se ugasiti) te opcionalnu freeze authority koja može zamrznuti račune."),
    "helius_pf": ("https://www.helius.dev/docs/priority-fee-api", "Helius docs", "Priority Fee API",
                  "A priority fee is a price per compute unit; under congestion transactions paying more are processed first.",
                  "Prioritetna naknada je cijena po compute jedinici; kad je mreža zagušena, prvo prolaze transakcije koje plate više."),
    "helius_mev": ("https://www.helius.dev/blog/solana-mev-an-introduction", "Helius", "Solana MEV: an introduction",
                   "Explains MEV on Solana: value from adding, removing or reordering transactions in a block, sandwiching and why Jito closed its mempool in March 2024.",
                   "Objašnjava MEV na Solani: vrijednost od dodavanja, izbacivanja ili preslagivanja transakcija u bloku, sandwich napade i zašto je Jito u ožujku 2024. zatvorio mempool."),
    "helius_etx": ("https://www.helius.dev/docs/api-reference/enhanced-transactions", "Helius docs", "Enhanced Transactions API",
                   "Raw Solana transactions can be parsed into readable swaps and transfers, which is how a wallet's buys and sells are reconstructed.",
                   "Sirove Solana transakcije mogu se pretvoriti u čitljive swapove i prijenose; tako se rekonstruiraju kupnje i prodaje novčanika."),
    "jito_bundles": ("https://docs.jito.wtf/lowlatencytxnsend/", "Jito Labs docs", "Low latency transaction send: bundles",
                     "A Jito bundle is up to five transactions executed in order and all-or-nothing; bundles compete on tips paid to the validator.",
                     "Jito bundle je do pet transakcija koje se izvršavaju redom i sve ili ništa; bundleovi se natječu napojnicom validatoru."),
    "jup_risks": ("https://docs.jup.ag/user-docs/trade/swap/risks", "Jupiter docs", "Jupiter Swap: risks and limitations",
                  "Defines slippage and price impact, warns that low-liquidity tokens can be hard to exit, and that a copied wallet's past results do not predict future ones because you trade later, at your own price.",
                  "Definira slippage i utjecaj na cijenu, upozorava da se iz tokena s malo likvidnosti teško izlazi i da prošli rezultati kopiranog novčanika ne predviđaju buduće jer trguješ kasnije, po svojoj cijeni."),
    "jup_slip": ("https://developers.jup.ag/docs/swap/advanced/slippage", "Jupiter developer docs", "Slippage estimation",
                 "Jupiter can estimate slippage automatically; the fixed default on its router path is 50 bps (0.5%).",
                 "Jupiter može sam procijeniti slippage; fiksna zadana vrijednost na router putu je 50 bps (0,5 %)."),
    "pump_fees": ("https://pump.fun/docs/fees", "pump.fun docs", "Pump.fun fees",
                  "Coins trade on a bonding curve and graduate to PumpSwap; the page lists the fees, including 0.015 SOL charged when a coin graduates.",
                  "Coini se trguju na bonding krivulji i diplomiraju na PumpSwap; stranica navodi naknade, uključujući 0,015 SOL pri diplomi."),
    "raydium_ll": ("https://docs.raydium.io/products/launchlab", "Raydium docs", "LaunchLab",
                   "On LaunchLab buyers trade against a bonding curve until a funding threshold, then the supply and raised funds migrate into a Raydium AMM pool.",
                   "Na LaunchLabu kupci trguju po bonding krivulji do praga financiranja, a zatim zaliha i prikupljena sredstva prelaze u Raydium AMM pool."),
    "meteora_docs": ("https://docs.meteora.ag/", "Meteora docs", "Meteora documentation",
                     "Meteora runs DLMM and DAMM pools and a Dynamic Bonding Curve for launches that graduate to a DAMM pool once a threshold is hit.",
                     "Meteora vodi DLMM i DAMM poolove i Dynamic Bonding Curve za lansiranja koja nakon praga prelaze u DAMM pool."),
    "orca_docs": ("https://docs.orca.so/", "Orca docs", "Orca documentation",
                  "Orca is a Solana DEX built on concentrated-liquidity pools (Whirlpools).",
                  "Orca je Solana DEX s poolovima koncentrirane likvidnosti (Whirlpools)."),
    "phantom_sec": ("https://help.phantom.com/hc/en-us/articles/13515761228051-Security-tips-for-Phantom-users",
                    "Phantom Help Center", "Security tips for Phantom users",
                    "Phantom support never asks for your Secret Recovery Phrase; tokens that appear in your wallet with instructions to visit a site should not be touched, only hidden and reported.",
                    "Phantomova podrška nikad ne traži Secret Recovery Phrase; tokene koji se pojave u novčaniku s uputom da posjetiš stranicu ne diraj, samo ih sakrij i prijavi."),
    "ledger_phish": ("https://www.ledger.com/phishing-campaigns-status", "Ledger", "Ongoing phishing campaigns",
                     "Ledger never contacts users by phone call or text message and never asks for the 24 words of the recovery phrase.",
                     "Ledger nikad ne zove telefonom ni ne šalje SMS i nikad ne traži 24 riječi recovery phrasea."),
    "polymarket_res": ("https://docs.polymarket.com/concepts/resolution", "Polymarket docs", "Resolution",
                       "Markets resolve by their written rules through the UMA Optimistic Oracle: a proposal with a bond (typically $750), about 2 hours if undisputed, a token-holder vote if disputed twice.",
                       "Tržišta se rješavaju po pisanim pravilima preko UMA Optimistic Oraclea: prijedlog uz jamčevinu (obično 750 $), oko 2 sata bez spora, glasanje vlasnika tokena nakon dva spora."),
    "polymarket_markets": ("https://docs.polymarket.com/concepts/markets-events", "Polymarket docs", "Markets and events",
                           "A market is one question with Yes and No positions; the winning position redeems for $1, the losing one for nothing.",
                           "Tržište je jedno pitanje s pozicijama Da i Ne; dobitna pozicija isplaćuje 1 $, gubitna ništa."),
    "uniswap_cca": ("https://docs.uniswap.org/contracts/liquidity-launchpad/CCA", "Uniswap docs", "Continuous Clearing Auction",
                    "In a CCA every bidder has a budget and a max price; all bidders in a block pay that block's clearing price, discovered gradually over the auction.",
                    "U CCA aukciji svaki ponuđač ima budžet i najvišu cijenu; svi u bloku plaćaju cijenu poravnanja tog bloka, koja se otkriva postupno."),
    "uniswap_blog_cca": ("https://blog.uniswap.org/continuous-clearing-auctions", "Uniswap Labs blog",
                         "Continuous Clearing Auctions: bootstrapping liquidity on Uniswap v4 (13 November 2025)",
                         "Spreading supply over time rewards early bids, reduces sniping, and the proceeds seed a Uniswap v4 pool at the discovered price.",
                         "Raspodjela ponude kroz vrijeme nagrađuje rane ponude, smanjuje sniping, a prikupljeno otvara Uniswap v4 pool po otkrivenoj cijeni."),
    "hl_adl": ("https://hyperliquid.gitbook.io/hyperliquid-docs/trading/auto-deleveraging", "Hyperliquid docs", "Auto-deleveraging",
               "When an account goes negative, profitable traders on the other side are ranked by profit and leverage and closed at the previous mark price.",
               "Kad račun ode u minus, profitabilni traderi na suprotnoj strani rangiraju se po dobiti i polugi i zatvaraju po prethodnoj mark cijeni."),
    "hl_margin": ("https://hyperliquid.gitbook.io/hyperliquid-docs/trading/margining", "Hyperliquid docs", "Margining",
                  "Cross margin shares collateral between positions; isolated margin keeps an asset's collateral to that position.",
                  "Cross margin dijeli kolateral između pozicija; isolated margin drži kolateral samo uz tu poziciju."),
    "dexs_api": ("https://docs.dexscreener.com/api/reference", "DEX Screener docs", "API reference",
                 "Public pair and token data (prices, liquidity, volume) with published rate limits.",
                 "Javni podaci o parovima i tokenima (cijena, likvidnost, volumen) uz objavljena ograničenja upita."),
    # research and data
    "chainalysis_pd": ("https://www.chainalysis.com/blog/crypto-market-manipulation-wash-trading-pump-and-dump-2025/",
                       "Chainalysis", "Crypto market manipulation 2025: suspected wash trading, pump and dump schemes",
                       "3.59% of tokens launched in 2024 (74,037) showed patterns linked to pump-and-dump schemes, about 94% of those pools rugged by their deployer; suspected wash trading on Ethereum, BNB Chain and Base was about $704 million in 2024.",
                       "3,59 % tokena lansiranih 2024. (74.037) pokazalo je obrasce povezane s pump-and-dumpom, oko 94 % tih poolova izvukao je onaj tko ih je otvorio; sumnjivi wash trading na Ethereumu, BNB Chainu i Baseu oko 704 milijuna $ u 2024."),
    "chainalysis_poison": ("https://www.chainalysis.com/blog/address-poisoning-scam/", "Chainalysis", "Anatomy of an address poisoning scam",
                           "Attackers generate look-alike addresses, dust the victim with small transfers and rely on the victim copying the address from transaction history.",
                           "Napadači stvaraju adrese koje izgledaju slično, šalju sitne iznose i računaju da će žrtva kopirati adresu iz povijesti transakcija."),
    "arxiv_poison": ("https://arxiv.org/abs/2501.16681", "Tsuchiya et al., USENIX Security 2025 (arXiv)", "Blockchain address poisoning",
                     "270 million on-chain poisoning attempts against 17 million victims; 6,633 incidents caused at least $83.8 million in losses.",
                     "270 milijuna pokušaja trovanja adrese prema 17 milijuna žrtava; 6.633 slučaja s najmanje 83,8 milijuna $ gubitka."),
    "arxiv_memecoin": ("https://arxiv.org/abs/2512.11850", "Mancino, IEEE ISCC 2025 (arXiv)", "The memecoin phenomenon: an in-depth study of Solana's blockchain trends",
                       "In Q4 2024 pump.fun accounted for up to 71.1% of tokens minted on Solana and 40-67.4% of DEX transactions, yet fewer than 2% of its tokens moved to major DEXs.",
                       "U zadnjem kvartalu 2024. pump.fun je činio do 71,1 % tokena stvorenih na Solani i 40-67,4 % DEX transakcija, a manje od 2 % tokena prešlo je na velike DEX-ove."),
    "arxiv_pfsuccess": ("https://arxiv.org/abs/2602.14860", "Marino et al. (arXiv, 2026)", "Predicting the success of new crypto-tokens: the pump.fun case",
                        "Graduation from the pump.fun bonding curve is modelled from the SOL locked in the curve plus behavioural variables of the launch.",
                        "Diploma s pump.fun krivulje modelira se iz SOL-a zaključanog u krivulji i varijabli ponašanja pri lansiranju."),
    "arxiv_earlybuyers": ("https://arxiv.org/abs/2610.39458", "Gafarov (arXiv, 2026)", "Early-buyer groups and fast-wallet teams on a bonding-curve launchpad",
                          "On 200,443 pump.fun launches, group members bought earlier and extracted more cash than a placebo set while late buyers lost; a follower entering at the earliest group signal lost money out of sample in all 32 configurations.",
                          "Na 200.443 pump.fun lansiranja članovi grupa kupovali su ranije i izvukli više novca od kontrolne skupine, a kasni kupci gubili; tko je ulazio na prvi signal grupe gubio je izvan uzorka u sve 32 postavke."),
    "arxiv_scamtokens": ("https://arxiv.org/abs/2109.00229", "Xia et al. (arXiv)", "Trade or trick? Detecting and characterizing scam tokens on Uniswap",
                         "Over 10,000 scam tokens were found on Uniswap, roughly 50% of the tokens listed there, built for rug pulls.",
                         "Na Uniswapu je nađeno više od 10.000 lažnih tokena, otprilike 50 % izlistanih, napravljenih za rug pull."),
    "arxiv_rug": ("https://arxiv.org/abs/2201.07220", "Mazorra et al. (arXiv)", "Do not rug on me: zero-dimensional scam detection",
                  "Classifies malicious maneuvers on Uniswap and detects potential rug pulls before they happen from token and contract features.",
                  "Razvrstava zlonamjerne poteze na Uniswapu i otkriva mogući rug pull prije nego se dogodi, iz značajki tokena i ugovora."),
    "arxiv_1day": ("https://arxiv.org/abs/2206.08202", "Cernera et al., USENIX Security 2023 (arXiv)", "Token spammers, rug pulls, and sniper bots",
                   "About 60% of tokens were active for less than a day, 1% of addresses created 20-25% of tokens, '1-day rug pulls' made about $240 million, and sniper bots took part.",
                   "Oko 60 % tokena bilo je aktivno kraće od dana, 1 % adresa stvorilo je 20-25 % tokena, 'jednodnevni rug pullovi' donijeli su oko 240 milijuna $, a sudjelovali su i sniper botovi."),
    "arxiv_pd2019": ("https://arxiv.org/abs/1811.10109", "Xu & Livshits, USENIX Security 2019 (arXiv)", "The anatomy of a cryptocurrency pump-and-dump scheme",
                     "Studied 412 pump-and-dumps organised in Telegram channels between June 2018 and February 2019.",
                     "Proučeno 412 pump-and-dumpova organiziranih u Telegram kanalima od lipnja 2018. do veljače 2019."),
    "arxiv_doge": ("https://arxiv.org/abs/2105.00733", "La Morgia et al. (arXiv)", "The Doge of Wall Street: analysis and detection of pump and dump cryptocurrency manipulations",
                   "Pump-and-dump groups coordinate on Telegram and Discord; about 900 events were monitored over more than three years.",
                   "Pump-and-dump grupe koordiniraju se na Telegramu i Discordu; praćeno je oko 900 događaja kroz više od tri godine."),
    "arxiv_pd765": ("https://arxiv.org/abs/2309.06608", "Karbalaii et al. (arXiv)", "Pump, dump, and then what? The long-term impact of cryptocurrency pump-and-dump schemes",
                    "Across 765 coins the long-term effect of a pump-and-dump is negative: on average a 30% relative price drop a year later.",
                    "Na 765 coina dugoročni učinak pump-and-dumpa je negativan: u prosjeku 30 % relativnog pada cijene godinu dana kasnije."),
    "arxiv_flashboys": ("https://arxiv.org/abs/1904.05234", "Daian et al. (arXiv)", "Flash Boys 2.0: frontrunning, transaction reordering, and consensus instability",
                        "Bots bid up transaction fees in 'priority gas auctions' to get early block position for their trades.",
                        "Botovi u 'aukcijama za prioritet' dižu naknade da bi njihove transakcije došle prve u bloku."),
    "nber_crypto": ("https://www.nber.org/papers/w24877", "Liu & Tsyvinski, NBER working paper 24877", "Risks and returns of cryptocurrency",
                    "Crypto returns have little exposure to common stock-market and macro factors and are driven by crypto-specific factors such as momentum and investor attention.",
                    "Prinosi kriptovaluta malo ovise o uobičajenim faktorima burze i makroekonomije, a pokreću ih faktori specifični za kripto, poput momentuma i pažnje ulagača."),
    "bis_69": ("https://www.bis.org/publ/bisbull69.htm", "Bank for International Settlements, Bulletin 69", "Crypto shocks and retail losses",
               "After the 2022 crashes large holders sold while small retail investors bought, and a majority of crypto app users in nearly all economies lost money on their bitcoin.",
               "Nakon slomova 2022. veliki imatelji su prodavali, a mali ulagači kupovali; većina korisnika kripto aplikacija u gotovo svim zemljama izgubila je na bitcoinu."),
    "nist_ci": ("https://www.itl.nist.gov/div898/handbook/eda/section3/eda352.htm", "NIST/SEMATECH e-Handbook of Statistical Methods",
                "Confidence limits for the mean",
                "A confidence interval gives a lower and upper limit for the mean and shows how uncertain the estimate is; the narrower, the more precise.",
                "Interval pouzdanosti daje donju i gornju granicu za prosjek i pokazuje koliko je procjena nesigurna; što uži, to precizniji."),
    "theblock_kaito": ("https://www.theblock.co/post/385805/kaito-token-plummets-x-revises-api-policies-ban-infofi-crypto-projects",
                       "The Block", "Kaito token plummets after X revises API policies to ban InfoFi crypto projects",
                       "X revoked API access for apps that reward users for posting, and Kaito announced it would sunset Yaps and its incentivised leaderboards.",
                       "X je ukinuo API pristup aplikacijama koje plaćaju objave, a Kaito je najavio gašenje Yapsa i nagradnih ljestvica."),
}

# Blog post (EN slug) -> source keys, in the order they are shown.
POSTS = {
    "what-is-wallet-tracking": ("helius_etx", "arxiv_earlybuyers", "jup_risks", "spl_token"),
    "what-is-copy-trading": ("jup_risks", "arxiv_earlybuyers", "investor_social", "fca_basics"),
    "what-is-a-kol-in-crypto": ("investor_social", "cftc_pd", "arxiv_pd2019"),
    "influencer-clustering": ("cftc_pd", "arxiv_doge", "investor_social"),
    "how-to-spot-a-rug-pull": ("spl_token", "arxiv_scamtokens", "arxiv_rug", "arxiv_1day", "chainalysis_pd"),
    "what-is-pump-fun": ("pump_fees", "arxiv_memecoin", "arxiv_pfsuccess", "raydium_ll"),
    "bundles-and-snipers": ("jito_bundles", "arxiv_1day", "arxiv_earlybuyers", "helius_mev"),
    "how-to-trade-meme-coins": ("fca_basics", "arxiv_memecoin", "jup_risks", "esas_warning"),
    "what-is-dca-in-crypto": ("fca_basics", "esas_warning", "jup_risks"),
    "market-cap-liquidity-slippage": ("jup_risks", "jup_slip", "orca_docs", "meteora_docs"),
    "best-crypto-exchanges-croatia": ("esma_mica", "hanfa_casp", "esas_warning"),
    "how-to-buy-solana-meme-coins": ("phantom_sec", "spl_token", "jup_risks", "esma_mica"),
    "how-to-use-jupiter-swap": ("jup_risks", "jup_slip", "helius_pf", "helius_mev"),
    "what-is-a-pump-and-dump": ("investor_pd", "cftc_pd", "chainalysis_pd", "arxiv_pd2019", "arxiv_pd765"),
    "crypto-cards-croatia": ("esma_mica", "hanfa_casp", "porezna_joppd"),
    "crypto-tax-croatia": ("porezna_joppd", "esma_mica"),
    "company-crypto-investment-croatia": ("esma_mica", "hanfa_casp", "esas_warning"),
    "why-big-influencer-calls-are-hard-to-trade": ("helius_pf", "jito_bundles", "arxiv_flashboys", "helius_mev"),
    "address-poisoning": ("arxiv_poison", "chainalysis_poison", "phantom_sec"),
    "zero-trust-support-calls": ("ledger_phish", "phantom_sec", "investor_social"),
    "polymarket-rules-checklist": ("polymarket_res", "polymarket_markets"),
    "polymarket-insider-moves": ("polymarket_markets", "polymarket_res"),
    "perps-settings-after-october-10": ("hl_margin", "hl_adl", "fca_derivs"),
    "tokens-sent-to-kol-wallets": ("phantom_sec", "helius_etx", "jup_risks"),
    "what-to-do-with-an-airdrop": ("phantom_sec", "esas_warning", "fca_basics"),
    "fake-volume-check": ("chainalysis_pd", "dexs_api", "arxiv_doge"),
    "after-kaito-yaps": ("theblock_kaito", "investor_social"),
    "fair-token-launch-cca": ("uniswap_cca", "uniswap_blog_cca", "arxiv_1day"),
    "best-crypto-telegram-channels": ("cftc_pd", "arxiv_pd2019", "arxiv_doge"),
    "top-crypto-twitter-accounts-by-call-accuracy": ("investor_social", "cftc_pd", "nist_ci"),
    "memecoin-telegram-groups-explained": ("cftc_pd", "arxiv_doge", "arxiv_pd765"),
    "how-to-spot-a-pump-fun-runner": ("pump_fees", "arxiv_pfsuccess", "arxiv_earlybuyers", "arxiv_memecoin"),
    "how-to-check-a-kol-track-record": ("investor_social", "nist_ci", "arxiv_pd2019"),
    # 23.11.2026
    "wallets-that-buy-before-a-solana-token-jumps": ("arxiv_earlybuyers", "helius_etx", "jito_bundles", "arxiv_1day"),
    "does-copying-smart-wallets-pay": ("arxiv_earlybuyers", "jup_risks", "nist_ci", "helius_pf"),
    "do-solana-meme-coins-follow-bitcoin": ("nber_crypto", "bis_69", "pump_fees", "meteora_docs", "orca_docs"),
    "how-memesonar-measures": ("nist_ci", "jup_risks", "helius_etx", "dexs_api", "helius_pf"),
}

# Public glossary term (EN slug) -> source keys. Terms that make no outside factual claim have none.
GLOSS = {
    "token": ("spl_token",), "contract-address": ("spl_token", "phantom_sec"), "market-cap": ("arxiv_memecoin",),
    "liquidity": ("jup_risks", "orca_docs"), "trading-volume": ("chainalysis_pd",), "crypto-wallet": ("phantom_sec",),
    "smart-money": ("arxiv_earlybuyers", "jup_risks"), "dex": ("orca_docs", "meteora_docs", "raydium_ll"),
    "cex": ("esma_mica", "hanfa_casp"), "pump-fun": ("pump_fees", "arxiv_memecoin"), "graduation": ("pump_fees", "arxiv_pfsuccess"),
    "slippage": ("jup_risks", "jup_slip"), "memecoin": ("arxiv_memecoin", "fca_basics"),
    "rug-pull": ("arxiv_scamtokens", "arxiv_1day", "chainalysis_pd"), "dev-wallet": ("arxiv_1day",),
    "bundler": ("jito_bundles", "arxiv_earlybuyers"), "sniper-bot": ("arxiv_1day",), "priority-fee": ("helius_pf",),
    "front-running": ("arxiv_flashboys", "helius_mev"), "insider-wallet": ("arxiv_earlybuyers",),
    "mint-authority": ("spl_token",), "kol": ("investor_social",), "crypto-call": ("cftc_pd",),
    "bot-account": ("theblock_kaito",), "copy-trading": ("jup_risks", "arxiv_earlybuyers"),
    "hardware-wallet": ("ledger_phish",), "mev-protection": ("helius_mev", "jito_bundles"),
    "rug-checker": ("spl_token",), "launchpad": ("pump_fees", "raydium_ll", "meteora_docs"),
    "wallet-cluster": ("arxiv_earlybuyers",), "hit-rate": ("nist_ci",),
}

L = {"en": ("Sources", "Checked on 23 November 2026. Outside sources support the general facts; the numbers marked as "
                       "MemeSonar's are our own measurements."),
     "hr": ("Izvori", "Provjereno 23. studenoga 2026. Vanjski izvori potkrepljuju opće činjenice; brojke označene kao "
                      "MemeSonarove naša su vlastita mjerenja.")}


def url(key):
    return S[key][0]


def a(key, text):
    """Inline link to a source, for a specific claim in the text."""
    return f'<a href="{esc(S[key][0])}" {REL}>{text}</a>'


def block(keys, lang="en"):
    """The 'Sources' list under a post or glossary term; '' when there are none."""
    if not keys:
        return ""
    h, note = L[lang]
    i = 3 if lang == "en" else 4
    lis = "".join(f'<li><a href="{esc(S[k][0])}" {REL}>{esc(S[k][2])}</a> <span class=mut>({esc(S[k][1])})</span>: '
                  f"{esc(S[k][i])}</li>" for k in keys)
    return f"<section class=src aria-label={h}><h2 class=s>{h}</h2><ul>{lis}</ul><p class=note>{note}</p></section>"


def used():
    """{key: [where used]} for docs/seo/izvori_2311.md."""
    out = {k: [] for k in S}
    for slug, ks in POSTS.items():
        for k in ks:
            out[k].append(f"/blog/{slug}")
    for slug, ks in GLOSS.items():
        for k in ks:
            out[k].append(f"/glossary/{slug}")
    return out
