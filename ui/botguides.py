"""Telegram trading bots: overview article + one setup guide per bot (EN main, HR under /hr). Part of the tools cluster.

- /best-crypto-tools/telegram-trading-bots          /hr/najbolji-kripto-alati/telegram-trading-botovi
- /best-crypto-tools/<bot>-setup-guide              /hr/najbolji-kripto-alati/<bot>-vodic

Facts (official links, fees, menu names, the bots' own recommended values) come from each bot's official docs, checked
1 November 2026: docs.bonkbot.io, docs.maestrobots.com, docs.gmgn.ai, docs.trojan.com, docs.bananagun.io. Our own
starting values are labelled as ours and lean on MemeSonar data (slippage by pool size, drawdowns after the peak).
Only official links: fake bots are the most common way people lose money with Telegram bots.
"""
from ui.html import esc

CHECKED = "2026-11-01"
OVERVIEW = {"en": "telegram-trading-bots", "hr": "telegram-trading-botovi"}


def T(en, hr):
    return {"en": en, "hr": hr}


# ───────────────────────────────────────────────────────────────────────────────────────────────── bots
# name, key, en/hr slug, links [(label, url)], chains, fee, known for, docs url
BOTS = [
    dict(key="trojan", name="Trojan", slug=T("trojan-setup-guide", "trojan-vodic"),
         links=[("trojan.com", "https://trojan.com"), ("Telegram: t.me/trojan", "https://t.me/trojan")],
         docs="https://docs.trojan.com", chains=T("Solana", "Solana"),
         fee=T("1% per trade, SOL cashback that grows with your rank", "1% po tradeu, SOL povrat koji raste s rangom"),
         known=T("Most features: presets, DCA, limit orders, copy trading, web Terminal",
                 "Najviše funkcija: profili, DCA, limit nalozi, copy trading, web Terminal")),
    dict(key="bonkbot", name="BonkBot", slug=T("bonkbot-setup-guide", "bonkbot-vodic"),
         links=[("Telegram: @bonkbot_bot", "https://t.me/bonkbot_bot"), ("bonkbot.io", "https://bonkbot.io")],
         docs="https://docs.bonkbot.io", chains=T("Solana", "Solana"),
         fee=T("1% per successful swap", "1% po uspješnoj zamjeni"),
         known=T("Simplest start; MEV Turbo/Secure; trailing stop loss", "Najjednostavniji početak; MEV Turbo/Secure; "
                 "trailing stop loss")),
    dict(key="maestro", name="Maestro", slug=T("maestro-setup-guide", "maestro-vodic"),
         links=[("Telegram: t.me/maestro", "https://t.me/maestro"), ("Pro: @MaestroProBot", "https://t.me/MaestroProBot")],
         docs="https://docs.maestrobots.com", chains=T("Solana, BSC, Base, Ethereum and 8 more", "Solana, BSC, Base, Ethereum i još 8"),
         fee=T("1% on every buy and sell; Premium $200/month optional", "1% na svaku kupnju i prodaju; Premium "
               "$200 mjesečno po želji"),
         known=T("12 chains, auto-snipe, copytrade, detailed buy and sell checks",
                 "12 mreža, auto-snipe, copytrade, detaljne provjere kupnje i prodaje")),
    dict(key="gmgn", name="GMGN Bot", slug=T("gmgn-bot-setup-guide", "gmgn-bot-vodic"),
         links=[("Telegram: @GMGN_sol_bot", "https://t.me/GMGN_sol_bot"), ("gmgn.ai", "https://gmgn.ai")],
         docs="https://docs.gmgn.ai", chains=T("Solana (separate bots for ETH, Base, BSC, Tron)", "Solana (zasebni botovi za ETH, Base, BSC, Tron)"),
         fee=T("1% per trade", "1% po tradeu"),
         known=T("Smart money signals, copy trade, published recommended settings",
                 "Smart money signali, copy trade, objavljene preporučene postavke")),
    dict(key="banana", name="Banana Gun", slug=None,
         links=[("bananagun.io", "https://bananagun.io"), (T("Official links", "Službeni linkovi"), "https://docs.bananagun.io/resources/official-links")],
         docs="https://docs.bananagun.io", chains=T("Solana + EVM chains", "Solana + EVM mreže"),
         fee=T("Not listed in its docs; check the fee line in the bot", "Nije navedena u dokumentaciji; provjeri "
               "naknadu u botu"),
         known=T("Launch sniping on EVM and Solana; Banana Pro web app", "Sniping lansiranja na EVM-u i Solani; web "
                 "aplikacija Banana Pro")),
]
BY_KEY = {b["key"]: b for b in BOTS}

# ───────────────────────────────────────────────────────────────────────────────────────── every setting
# (name EN, name HR, what EN, what HR, our starting value EN, HR)
SETTINGS = [
    ("Buy presets", "Gumbi za kupnju",
     "The SOL amounts on your buy buttons, so one tap buys a fixed size.",
     "Iznosi u SOL-u na gumbima za kupnju, pa jedan dodir kupi fiksni iznos.",
     "Small and fixed, e.g. 0.1 / 0.25 / 0.5 SOL; each buy under about 2% of the pool's liquidity",
     "Mali i fiksni, npr. 0,1 / 0,25 / 0,5 SOL; svaka kupnja ispod oko 2% likvidnosti poola"),
    ("Sell presets", "Gumbi za prodaju",
     "The % of your position each sell button sells.", "Koliki % pozicije prodaje svaki gumb za prodaju.",
     "25% / 50% / 100%", "25% / 50% / 100%"),
    ("Slippage (buy / sell)", "Slippage (kupnja / prodaja)",
     "The most the price may move against you before the trade fails. Too low: trades fail on fast tokens. Too high: "
     "bots can sandwich you.",
     "Najviše koliko se cijena smije pomaknuti protiv tebe prije nego trade propadne. Premalo: tradeovi propadaju na "
     "brzim tokenima. Previše: botovi te mogu 'sendvičirati'.",
     "Start at 10-15% (Trojan's advice); 30-35% for automatic orders and 50%+ only for brand-new tokens (GMGN's "
     "advice)",
     "Kreni s 10-15% (Trojanov savjet); 30-35% za automatske naloge, a 50%+ samo za posve nove tokene (GMGN-ov savjet)"),
    ("Max price impact", "Najveći utjecaj na cijenu",
     "Blocks or warns when your own buy would move the price too much, i.e. the pool is too small for your size.",
     "Blokira ili upozori kad bi tvoja kupnja previše pomaknula cijenu, tj. pool je premalen za tvoj iznos.",
     "On, around 5-10%", "Uključeno, oko 5-10%"),
    ("Priority fee (gas)", "Prioritetna naknada (gas)",
     "Extra SOL paid to validators so your transaction lands sooner. Goes to the network, not the bot.",
     "Dodatni SOL koji plaćaš validatorima da transakcija prođe prije. Ide mreži, ne botu.",
     "Total on-chain fee 0.002-0.005 SOL for normal trades, 0.006+ SOL for automatic orders (GMGN's advice)",
     "Ukupna mrežna naknada 0,002-0,005 SOL za obične tradeove, 0,006+ SOL za automatske naloge (GMGN-ov savjet)"),
    ("MEV protection / bribe (tip)", "MEV zaštita / bribe (tip)",
     "Sends your trade privately (through Jito or similar relays) so sandwich bots can't see it first. The bribe or tip "
     "pays for that route.",
     "Šalje trade privatno (preko Jita ili sličnih releja) pa ga sendvič botovi ne vide prvi. Bribe ili tip plaća tu "
     "rutu.",
     "On for every buy above a few dollars; GMGN needs at least 0.002 SOL priority fee for Anti-MEV",
     "Uključeno za svaku kupnju veću od par dolara; GMGN za Anti-MEV traži barem 0,002 SOL prioritetne naknade"),
    ("Auto buy", "Automatska kupnja",
     "Buys immediately when you paste a contract address, with no confirmation.",
     "Kupi odmah čim zalijepiš adresu tokena, bez potvrde.",
     "Off until you know the bot; then on with a small amount", "Isključeno dok ne upoznaš bota; zatim uključeno s "
     "malim iznosom"),
    ("Confirm trades / sell protection", "Potvrda tradea / zaštita prodaje",
     "Asks for one more tap before a manual buy or sell, so a mis-tap doesn't trade.",
     "Traži još jedan dodir prije ručne kupnje ili prodaje, pa slučajan dodir ne trguje.",
     "On for sells while you learn", "Uključeno za prodaje dok učiš"),
    ("Take profit (TP)", "Take profit (TP)",
     "A sell order that triggers when the price is X% above your entry.",
     "Nalog za prodaju koji se aktivira kad je cijena X% iznad tvoje ulazne.",
     "Sell 50% at +100% (your stake back), let the rest run", "Prodaj 50% na +100% (vratiš ulog), ostatak pusti"),
    ("Stop loss (SL)", "Stop loss (SL)",
     "A sell order that triggers when the price is X% below your entry.",
     "Nalog za prodaju koji se aktivira kad je cijena X% ispod tvoje ulazne.",
     "-30% to -40%; tighter stops get hit by normal meme coin swings", "-30% do -40%; uži stopovi se aktiviraju na "
     "običnim ljuljanjima meme coina"),
    ("Trailing stop loss", "Trailing stop loss",
     "A stop that moves up with the highest price and sells when the price falls X% from that high.",
     "Stop koji se penje s najvišom cijenom i prodaje kad cijena padne X% od tog vrha.",
     "-30% to -35% after the first take profit", "-30% do -35% nakon prvog take profita"),
    ("Auto sell on buy", "Automatska prodaja nakon kupnje",
     "Creates your TP/SL orders automatically right after every buy.",
     "Odmah nakon svake kupnje sam postavi tvoje TP/SL naloge.",
     "On, with the TP/SL above", "Uključeno, s TP/SL-om iznad"),
    ("Auto-buy checks (min/max market cap, liquidity)", "Provjere automatske kupnje (min/max mcap, likvidnost)",
     "Auto buys only fire when the token is inside your limits.", "Automatske kupnje rade samo kad je token unutar "
     "tvojih granica.",
     "Liquidity at least $10k; skip tokens with mint or freeze authority on", "Likvidnost najmanje $10k; preskoči "
     "tokene s uključenom mint ili freeze ovlasti"),
    ("Two-factor authentication (2FA)", "Dvofaktorska autentifikacija (2FA)",
     "A second code before withdrawals or exports, on the bot and on your Telegram account.",
     "Drugi kod prije podizanja ili izvoza ključa, na botu i na Telegram računu.",
     "On, always", "Uključeno, uvijek"),
]

# Three starting profiles (labelled as ours): rows (label EN, HR, careful, balanced, new launches)
PROFILES = [
    (("Buy size", "Iznos kupnje"), ("0.1 SOL", "0.25 SOL", "0.1 SOL"), ("0,1 SOL", "0,25 SOL", "0,1 SOL")),
    (("Slippage buy / sell", "Slippage kupnja / prodaja"), ("10% / 10%", "15% / 20%", "35% / 35%"),
     ("10% / 10%", "15% / 20%", "35% / 35%")),
    (("Priority + tip", "Prioritet + tip"), ("0.002 SOL", "0.004 SOL", "0.006 SOL"), ("0,002 SOL", "0,004 SOL", "0,006 SOL")),
    (("MEV protection", "MEV zaštita"), ("Secure", "On", "On (Turbo)"), ("Secure", "Uključena", "Uključena (Turbo)")),
    (("Auto buy", "Automatska kupnja"), ("Off", "Off", "On, small"), ("Isključena", "Isključena", "Uključena, malo")),
    (("Take profit", "Take profit"), ("50% at +100%", "50% at +100%", "50% at +100%, 25% at +300%"),
     ("50% na +100%", "50% na +100%", "50% na +100%, 25% na +300%")),
    (("Stop loss", "Stop loss"), ("-30%", "Trailing -35%", "-40%"), ("-30%", "Trailing -35%", "-40%")),
]

# ───────────────────────────────────────────────────────────────────────────────────────── guides per bot
# steps: [(title EN, text EN, title HR, text HR)], table: [(setting, where in the bot, value EN, value HR)],
# panel: [(button label, value)] for the illustration, watch: [EN], [HR]
GUIDES = {
    "bonkbot": dict(
        h1=T("How to set up BonkBot: step-by-step guide and best settings (2026)",
             "Kako postaviti BonkBot: vodič korak po korak i najbolje postavke (2026.)"),
        title=T("BonkBot setup guide 2026: best settings, slippage, MEV, trailing stop | MemeSonar",
                "BonkBot vodič 2026: najbolje postavke, slippage, MEV, trailing stop | MemeSonar"),
        desc=T("Set up BonkBot on Telegram safely: official link, wallet, every setting explained (slippage, priority, "
               "MEV Turbo vs Secure, auto buy, trailing stop) and the values we start with.",
               "Sigurno postavi BonkBot na Telegramu: službeni link, novčanik, svaka postavka objašnjena (slippage, "
               "prioritet, MEV Turbo ili Secure, auto buy, trailing stop) i vrijednosti s kojima krećemo."),
        tldr=T("Open BonkBot only from the official link <b>t.me/bonkbot_bot</b>, back up the wallet key it creates, "
               "send a small amount of SOL, then in <b>/settings</b>: buy buttons 0.1/0.25/0.5 SOL, slippage 10-15%, "
               "MEV Protect <b>Secure</b>, priority Medium, Sell Protection on, 2FA on. BonkBot charges 1% per swap.",
               "BonkBot otvaraj samo preko službenog linka <b>t.me/bonkbot_bot</b>, spremi ključ novčanika koji "
               "napravi, pošalji malo SOL-a, pa u <b>/settings</b>: gumbi 0,1/0,25/0,5 SOL, slippage 10-15%, MEV "
               "Protect <b>Secure</b>, prioritet Medium, Sell Protection uključen, 2FA uključen. BonkBot naplaćuje 1% "
               "po zamjeni."),
        steps=[("Open the official bot", "Use t.me/bonkbot_bot from BonkBot's docs. Fake bots copy the name and ask you "
                "to deposit SOL; check the username letter by letter.",
                "Otvori službenog bota", "Koristi t.me/bonkbot_bot iz BonkBotove dokumentacije. Lažni botovi kopiraju ime "
                "i traže uplatu SOL-a; provjeri korisničko ime slovo po slovo."),
               ("Back up your wallet", "BonkBot creates a Solana wallet for you. Export the private key once and store it "
                "offline. Anyone with it can empty the wallet, so never paste it anywhere else.",
                "Spremi novčanik", "BonkBot ti napravi Solana novčanik. Jednom izvezi privatni ključ i spremi ga offline. "
                "Tko ga ima, može isprazniti novčanik, zato ga nikad nigdje ne lijepi."),
               ("Fund it with a small amount", "Send only what you plan to trade from your main wallet (Phantom, "
                "Solflare). Keep the rest in your own wallet or a hardware wallet.",
                "Uplati mali iznos", "Pošalji samo ono čime planiraš trgovati iz glavnog novčanika (Phantom, Solflare). "
                "Ostatak drži u svom ili hardverskom novčaniku."),
               ("Turn on security first", "In /settings → Security Config: enable 2FA and, if you want, require 2FA for "
                "token approvals. Also turn on 2FA in Telegram itself.",
                "Prvo uključi sigurnost", "U /settings → Security Config: uključi 2FA i po želji traži 2FA za odobrenja. "
                "Uključi 2FA i u samom Telegramu."),
               ("Set buttons, slippage and MEV", "Buy/Sell Buttons Config, Slippage Config, MEV Protect and Transaction "
                "Priority, with the values in the table below.",
                "Postavi gumbe, slippage i MEV", "Buy/Sell Buttons Config, Slippage Config, MEV Protect i Transaction "
                "Priority, s vrijednostima iz tablice ispod."),
               ("First trade", "Paste a token's contract address, check the safety lines BonkBot shows (mint authority, "
                "freeze authority, LP burnt), then tap a buy button.",
                "Prvi trade", "Zalijepi adresu tokena, provjeri sigurnosne retke koje BonkBot pokaže (mint authority, "
                "freeze authority, LP burnt), pa dodirni gumb za kupnju."),
               ("Protect the position", "Limit → Limit Sell %: a take profit, and a trailing stop loss (BonkBot's example "
                "sells 50% if market cap falls to 0.8x of any high).",
                "Zaštiti poziciju", "Limit → Limit Sell %: take profit i trailing stop loss (BonkBotov primjer prodaje "
                "50% ako market cap padne na 0,8x bilo kojeg vrha).")],
        table=[("Buy Buttons", "/settings → Buy/Sell Buttons Config", "0.1 / 0.25 / 0.5 SOL", "0,1 / 0,25 / 0,5 SOL"),
               ("Sell Buttons", "Buy/Sell Buttons Config", "25% / 50% / 100%, Sell Initial on +100%",
                "25% / 50% / 100%, Sell Initial na +100%"),
               ("Buy / Sell Slippage", "Slippage Config", "10-15% / 15-20%", "10-15% / 15-20%"),
               ("Max Price Impact", "Slippage Config", "5-10%", "5-10%"),
               ("MEV Protect", "MEV Protect", "Secure (Turbo only when speed matters more)",
                "Secure (Turbo samo kad je brzina važnija)"),
               ("Transaction Priority", "Transaction Priority", "Medium, High when the network is busy",
                "Medium, High kad je mreža zagušena"),
               ("Auto Buy", "Auto Buy", "Off at first (it buys with no warning)", "Isprva isključeno (kupuje bez "
                "upozorenja)"),
               ("Sell Protection", "Sell Protection", "On", "Uključeno"),
               ("2FA", "Security Config", "On", "Uključeno"),
               ("Trailing stop", "Limit → Limit Sell %", "50% at 0.65-0.7x of the high", "50% na 0,65-0,7x vrha")],
        panel=[("💰 Buy 0.1 SOL", ""), ("💰 Buy 0.25 SOL", ""), ("💰 Buy 0.5 SOL", ""), ("Slippage", "15%"),
               ("MEV Protect", "Secure"), ("Priority", "Medium"), ("Auto Buy", "Off"), ("Sell Protection", "On"),
               ("2FA", "On")],
        watch=T(["Auto Buy buys the moment you paste an address, with no confirmation.",
                 "BonkBot shows ads; its docs warn that links in ads can lead to scams.",
                 "BonkBot admins never DM first and never ask for your key."],
                ["Auto Buy kupuje čim zalijepiš adresu, bez potvrde.",
                 "BonkBot prikazuje oglase; dokumentacija upozorava da linkovi u oglasima mogu voditi na prevare.",
                 "BonkBot admini nikad ne pišu prvi i nikad ne traže tvoj ključ."])),
    "maestro": dict(
        h1=T("How to set up Maestro bot: step-by-step guide and best settings (2026)",
             "Kako postaviti Maestro bot: vodič korak po korak i najbolje postavke (2026.)"),
        title=T("Maestro bot setup guide 2026: best settings, Anti-MEV, gas delta | MemeSonar",
                "Maestro bot vodič 2026: najbolje postavke, Anti-MEV, gas delta | MemeSonar"),
        desc=T("Set up Maestro on Telegram for Solana: official link, chains, wallets, Global Settings explained "
               "(Anti-MEV, Degen Mode, Gas Delta, slippage, auto-buy checks, sell limits) and our starting values.",
               "Postavi Maestro na Telegramu za Solanu: službeni link, novčanici, Global Settings objašnjene "
               "(Anti-MEV, Degen Mode, Gas Delta, slippage, provjere auto-buya, sell limiti) i naše početne vrijednosti."),
        tldr=T("Start Maestro from <b>t.me/maestro</b>, solve the captcha, enable only the chains you use, create a fresh "
               "wallet, then in <b>Global Settings</b>: Anti-MEV on, Degen Mode <b>off</b>, Gas Delta about 0.002-0.005 "
               "SOL, slippage 10-15%, Duplicate Buy off, and Sell Limit presets (TP +100% for 50%, stop -35%). Maestro "
               "takes 1% of every buy and sell; Premium is $200/month and optional.",
               "Pokreni Maestro preko <b>t.me/maestro</b>, riješi captchu, uključi samo mreže koje koristiš, napravi novi "
               "novčanik, pa u <b>Global Settings</b>: Anti-MEV uključen, Degen Mode <b>isključen</b>, Gas Delta oko "
               "0,002-0,005 SOL, slippage 10-15%, Duplicate Buy isključen i Sell Limit predlošci (TP +100% za 50%, stop "
               "-35%). Maestro uzima 1% svake kupnje i prodaje; Premium je $200 mjesečno i nije obavezan."),
        steps=[("Start the bot", "Open t.me/maestro (the link in Maestro's docs), press Start and solve the captcha. "
                "Then send /start for the main menu.",
                "Pokreni bota", "Otvori t.me/maestro (link iz Maestrove dokumentacije), pritisni Start i riješi captchu. "
                "Zatim pošalji /start za glavni izbornik."),
               ("Enable chains", "🔗 Chains: turn on Solana (and only the others you really use; Maestro supports 12).",
                "Uključi mreže", "🔗 Chains: uključi Solanu (i samo druge koje stvarno koristiš; Maestro podržava 12)."),
               ("Create a wallet", "💳 Wallets: generate a new wallet for the bot, save the key offline, send a small "
                "amount of SOL.",
                "Napravi novčanik", "💳 Wallets: napravi novi novčanik za bota, spremi ključ offline, pošalji malo SOL-a."),
               ("General settings", "⚙️ Global Settings → General: Anti-MEV on (routes Solana trades through Jito, "
                "Temporal or NextBlock), Degen Mode off (it removes the honeypot and liquidity checks on auto buys).",
                "Opće postavke", "⚙️ Global Settings → General: Anti-MEV uključen (Solana tradeove šalje preko Jita, "
                "Temporala ili NextBlocka), Degen Mode isključen (miče provjere honeypota i likvidnosti na auto kupnjama)."),
               ("Buy settings", "Buy: Buy KB presets, Gas Delta, Price Impact Alert, Slippage, Auto Buy Checks (min/max "
                "market cap and liquidity), Duplicate Buy off.",
                "Postavke kupnje", "Buy: Buy KB predlošci, Gas Delta, Price Impact Alert, Slippage, Auto Buy Checks "
                "(min/max mcap i likvidnost), Duplicate Buy isključen."),
               ("Sell settings", "Sell: Confirm Manual Sell, Sell KB, Slippage, Auto Sell on Manual Buy on, and ⚙️ Sell "
                "Limit presets (Take Profit, Stop Loss, Trailing Stop Loss; max duration 168 h).",
                "Postavke prodaje", "Sell: Confirm Manual Sell, Sell KB, Slippage, Auto Sell on Manual Buy uključen i ⚙️ "
                "Sell Limit predlošci (Take Profit, Stop Loss, Trailing Stop Loss; najdulje 168 h)."),
               ("First trade", "⚡ BUY & SELL NOW: paste a contract address, read the Token Report, buy with a preset.",
                "Prvi trade", "⚡ BUY & SELL NOW: zalijepi adresu tokena, pročitaj Token Report, kupi gumbom.")],
        table=[("Anti-MEV", "Global Settings → General", "On", "Uključeno"),
               ("Degen Mode", "General", "Off", "Isključeno"),
               ("Initial Includes Fees", "General", "On (default): TP/SL count fees", "Uključeno (zadano): TP/SL "
                "računaju naknade"),
               ("Confirm Manual Buy", "Buy", "On while learning", "Uključeno dok učiš"),
               ("Buy KB", "Buy", "0.1 / 0.25 / 0.5 SOL", "0,1 / 0,25 / 0,5 SOL"),
               ("Gas Delta (Solana)", "Buy and Sell", "0.002-0.005 SOL (0.01 SOL = 0.010005 SOL total fee)",
                "0,002-0,005 SOL (0,01 SOL = 0,010005 SOL ukupne naknade)"),
               ("Price Impact Alert", "Buy and Sell", "5-10%", "5-10%"),
               ("Slippage", "Buy / Sell", "10-15% / 15-20%", "10-15% / 15-20%"),
               ("Auto Buy Checks", "Buy", "Min liquidity $10k", "Najmanja likvidnost $10k"),
               ("Duplicate Buy", "Buy", "Off (no second buy of a token you hold)", "Isključeno (bez druge kupnje "
                "tokena koji držiš)"),
               ("Auto Sell on Manual Buy", "Sell", "On", "Uključeno"),
               ("Sell Limit presets", "Sell → ⚙️ Sell Limit", "TP +100% 50%; Trailing -35% 100%",
                "TP +100% 50%; Trailing -35% 100%")],
        panel=[("🛡 Anti-MEV", "On"), ("😈 Degen Mode", "Off"), ("⛽ Gas Delta", "0.003 SOL"), ("Slippage", "15%"),
               ("Price Impact Alert", "8%"), ("Duplicate Buy", "Off"), ("Auto Sell", "On"), ("TP", "+100% · 50%"),
               ("Trailing SL", "-35%")],
        watch=T(["Degen Mode turns off the bot's honeypot and liquidity checks on auto buys.",
                 "On EVM chains fees are collected later from your largest wallet, not in each trade.",
                 "Premium ($200/month) adds speed and limits, not better tokens; start without it."],
                ["Degen Mode isključuje botove provjere honeypota i likvidnosti na automatskim kupnjama.",
                 "Na EVM mrežama naknada se naplaćuje kasnije iz najvećeg novčanika, ne u svakom tradeu.",
                 "Premium ($200 mjesečno) daje brzinu i veća ograničenja, ne bolje tokene; kreni bez njega."])),
    "gmgn": dict(
        h1=T("How to set up the GMGN Telegram bot: guide and recommended settings (2026)",
             "Kako postaviti GMGN Telegram bota: vodič i preporučene postavke (2026.)"),
        title=T("GMGN bot setup guide 2026: slippage, priority fee, Anti-MEV, auto sell | MemeSonar",
                "GMGN bot vodič 2026: slippage, prioritetna naknada, Anti-MEV | MemeSonar"),
        desc=T("Set up the GMGN Solana Telegram bot: the official bot list, wallet, settings explained and GMGN's own "
               "recommended slippage and fees, plus auto sell with take profit and stop loss.",
               "Postavi GMGN Solana Telegram bota: službeni popis botova, novčanik, objašnjene postavke i GMGN-ove "
               "preporučene vrijednosti slippagea i naknada, plus auto sell s take profitom i stop lossom."),
        tldr=T("Use only the bots on GMGN's official list (main one <b>@GMGN_sol_bot</b>). GMGN itself recommends: "
               "auto slippage for manual trades, <b>30-35%</b> for automatic orders and 50%+ only for new hot tokens; "
               "a total on-chain fee of <b>0.002-0.005 SOL</b> (0.006+ for automatic orders). Anti-MEV needs at least "
               "0.002 SOL priority fee. Fee: 1% per trade.",
               "Koristi samo botove sa službenog GMGN popisa (glavni <b>@GMGN_sol_bot</b>). GMGN sam preporučuje: auto "
               "slippage za ručne tradeove, <b>30-35%</b> za automatske naloge, a 50%+ samo za nove popularne tokene; "
               "ukupnu mrežnu naknadu <b>0,002-0,005 SOL</b> (0,006+ za automatske naloge). Anti-MEV traži barem 0,002 "
               "SOL prioritetne naknade. Naknada: 1% po tradeu."),
        steps=[("Open an official bot", "GMGN lists @GMGN_sol_bot and backups @GMGN_sol02_bot, 03, 04 and @US_GMGNBOT. "
                "Its docs warn that fakes use a capital 'I' instead of a lowercase 'l'.",
                "Otvori službenog bota", "GMGN navodi @GMGN_sol_bot i rezervne @GMGN_sol02_bot, 03, 04 i @US_GMGNBOT. "
                "Dokumentacija upozorava da lažni koriste veliko 'I' umjesto malog 'l'."),
               ("Wallet", "On first /start the bot generates a Solana wallet. Save the key offline and fund it with a "
                "small amount. If you receive WSOL, use Wallet → Exchange WSOL → SOL.",
                "Novčanik", "Na prvi /start bot napravi Solana novčanik. Spremi ključ offline i uplati mali iznos. Ako "
                "dobiješ WSOL, koristi Wallet → Exchange WSOL → SOL."),
               ("Settings", "Setting (or /set): auto slippage on for manual trades, custom slippage for orders, priority "
                "and tip fee, Anti-MEV mode.",
                "Postavke", "Setting (ili /set): auto slippage uključen za ručne tradeove, vlastiti slippage za naloge, "
                "prioritetna i tip naknada, Anti-MEV način."),
               ("Auto sell", "/autosell → + Add Preset Order: a negative % is a stop loss, a positive % a take profit; "
                "take-profit amounts should add up to 100%. Orders stay valid 24 h.",
                "Auto sell", "/autosell → + Add Preset Order: negativan % je stop loss, pozitivan take profit; iznosi "
                "take profita trebaju zajedno dati 100%. Nalozi vrijede 24 h."),
               ("Telegram security", "Turn on Telegram 2FA, install Telegram only from the official stores, no "
                "third-party language packs (GMGN's own safety list).",
                "Sigurnost Telegrama", "Uključi 2FA na Telegramu, instaliraj ga samo iz službenih trgovina, bez "
                "jezičnih paketa trećih strana (GMGN-ov sigurnosni popis)."),
               ("First trade", "Buy/Sell → paste a contract address → choose Turbo (faster) or Anti-MEV (protected, "
                "slightly slower) → buy.",
                "Prvi trade", "Buy/Sell → zalijepi adresu tokena → odaberi Turbo (brže) ili Anti-MEV (zaštićeno, malo "
                "sporije) → kupi.")],
        table=[("Auto slippage", "Setting", "On for manual trades (GMGN)", "Uključeno za ručne tradeove (GMGN)"),
               ("Slippage for orders", "Setting", "30-35%; 50%+ only for new hot tokens (GMGN)",
                "30-35%; 50%+ samo za nove popularne tokene (GMGN)"),
               ("Priority + tip fee", "Setting", "0.002-0.005 SOL total; 0.006+ for auto orders (GMGN)",
                "0,002-0,005 SOL ukupno; 0,006+ za automatske naloge (GMGN)"),
               ("Anti-MEV", "Swap / Setting", "On; needs priority fee of at least 0.002 SOL",
                "Uključeno; traži prioritetnu naknadu od barem 0,002 SOL"),
               ("Anti-MEV RPC", "Setting", "Secure for bigger buys, Reduced for speed",
                "Secure za veće kupnje, Reduced za brzinu"),
               ("Auto sell", "/autosell", "On: +100% sell 50%, +300% sell 50%, -35% sell 100%",
                "Uključeno: +100% prodaj 50%, +300% prodaj 50%, -35% prodaj 100%")],
        panel=[("⚡ Turbo", "Off"), ("🛡 Anti-MEV", "On"), ("Auto slippage", "On"), ("Order slippage", "30%"),
               ("Priority", "0.002 SOL"), ("Tip", "0.002 SOL"), ("TP", "+100% · 50%"), ("TP", "+300% · 50%"),
               ("SL", "-35% · 100%")],
        watch=T(["Only the bots on GMGN's list are real; others drain wallets.",
                 "Auto slippage can lag on very fast tokens (GMGN's own note).",
                 "Auto sell orders expire after 24 hours; set them again for longer holds."],
                ["Pravi su samo botovi s GMGN-ova popisa; drugi prazne novčanike.",
                 "Auto slippage može kasniti na vrlo brzim tokenima (GMGN-ova napomena).",
                 "Auto sell nalozi istječu nakon 24 sata; za dulje držanje postavi ih ponovno."])),
    "trojan": dict(
        h1=T("How to set up Trojan: step-by-step guide and best settings (2026)",
             "Kako postaviti Trojan: vodič korak po korak i najbolje postavke (2026.)"),
        title=T("Trojan bot setup guide 2026: presets, slippage, priority fee, bribe | MemeSonar",
                "Trojan vodič 2026: profili, slippage, prioritetna naknada, bribe | MemeSonar"),
        desc=T("Set up Trojan for Solana: official links, wallet, Trade Settings profiles explained (quick amounts, "
               "priority fee, bribe, slippage, spam buy, auto sell) and our starting values.",
               "Postavi Trojan za Solanu: službeni linkovi, novčanik, Trade Settings profili objašnjeni (brzi iznosi, "
               "prioritetna naknada, bribe, slippage, spam buy, auto sell) i naše početne vrijednosti."),
        tldr=T("Trojan started as a Telegram bot and now also runs Trojan Terminal at <b>trojan.com</b>; its docs list "
               "Telegram at <b>t.me/trojan</b>. Set up three <b>Trade Settings</b> profiles (careful, balanced, new "
               "launches), start slippage at <b>10-15%</b> as Trojan advises, add a bribe for MEV protection and turn on "
               "<b>Auto-Sell</b> before you buy. Fee: 1% per trade, minus SOL cashback by rank.",
               "Trojan je krenuo kao Telegram bot, a sada ima i Trojan Terminal na <b>trojan.com</b>; dokumentacija "
               "navodi Telegram na <b>t.me/trojan</b>. Postavi tri <b>Trade Settings</b> profila (oprezno, uravnoteženo, "
               "nova lansiranja), kreni sa slippageom <b>10-15%</b> kako Trojan savjetuje, dodaj bribe za MEV zaštitu i "
               "uključi <b>Auto-Sell</b> prije kupnje. Naknada: 1% po tradeu, umanjeno za SOL povrat po rangu."),
        steps=[("Use the official links", "trojan.com, or Telegram t.me/trojan as listed on Trojan's docs Links page. "
                "Never use a 'Trojan' link from a DM or an ad.",
                "Koristi službene linkove", "trojan.com, ili Telegram t.me/trojan kako piše na stranici Links u "
                "Trojanovoj dokumentaciji. Nikad ne koristi 'Trojan' link iz privatne poruke ili oglasa."),
               ("Log in and create a trading wallet", "Log in with a Solana wallet or a passkey; for limit and DCA orders "
                "Trojan needs its own (or an imported) trading wallet. Use a fresh wallet with a small balance.",
                "Prijava i trading novčanik", "Prijavi se Solana novčanikom ili passkeyem; za limit i DCA naloge Trojan "
                "treba svoj (ili uvezen) trading novčanik. Koristi novi novčanik s malim iznosom."),
               ("Fund it", "Send SOL (not USDC/USDT: you need SOL for fees). Each new token costs a one-time ~0.002 SOL "
                "account fee, refunded when you sell.",
                "Uplati", "Pošalji SOL (ne USDC/USDT: SOL ti treba za naknade). Svaki novi token košta jednokratno "
                "~0,002 SOL za račun tokena, vraća se kad prodaš."),
               ("Build three profiles", "Trade Settings has three presets. Edit Buy and Sell tabs of each: quick amounts, "
                "clipboard quick buy, priority fee, bribe, slippage, snipe slippage.",
                "Napravi tri profila", "Trade Settings ima tri predloška. Uredi kartice Buy i Sell za svaki: brzi "
                "iznosi, clipboard quick buy, prioritetna naknada, bribe, slippage, snipe slippage."),
               ("Turn on Auto-Sell", "Auto-Sell must be set before you buy: add orders with a positive % (take profit) "
                "and negative % (stop loss) from your entry price.",
                "Uključi Auto-Sell", "Auto-Sell se mora postaviti prije kupnje: dodaj naloge s pozitivnim % (take "
                "profit) i negativnim % (stop loss) od ulazne cijene."),
               ("First trade", "Pick the profile, paste or click a token, check holders and safety score, buy with a "
                "quick amount.",
                "Prvi trade", "Odaberi profil, zalijepi ili klikni token, provjeri holdere i sigurnosnu ocjenu, kupi "
                "brzim iznosom.")],
        table=[("Quick amounts (buy)", "Trade Settings → Buy", "0.1 / 0.25 / 0.5 SOL", "0,1 / 0,25 / 0,5 SOL"),
               ("Quick amounts (sell)", "Trade Settings → Sell", "25% / 50% / 100%", "25% / 50% / 100%"),
               ("Slippage", "Trade Settings", "Start 10-15% (Trojan), raise only if trades fail",
                "Kreni s 10-15% (Trojan), povećaj samo ako tradeovi propadaju"),
               ("Snipe slippage", "Trade Settings", "30-35%, only for the new-launch profile",
                "30-35%, samo za profil novih lansiranja"),
               ("Priority fee", "Trade Settings", "0.001-0.003 SOL", "0,001-0,003 SOL"),
               ("Bribe (MEV)", "Trade Settings", "0.001-0.002 SOL", "0,001-0,002 SOL"),
               ("Spam buy", "Trade Settings", "Off (1); it multiplies your buy", "Isključeno (1); množi tvoju kupnju"),
               ("Auto-Sell", "Trade Settings / Trade Panel", "+100% sell 50%, -35% sell 100%",
                "+100% prodaj 50%, -35% prodaj 100%")],
        panel=[("Profile", "Balanced"), ("Quick buy", "0.25 SOL"), ("Slippage", "15%"), ("Priority", "0.002 SOL"),
               ("Bribe", "0.001 SOL"), ("Spam buy", "1"), ("Auto-Sell", "On"), ("TP", "+100% · 50%"), ("SL", "-35%")],
        watch=T(["Spam buy repeats your buy up to 10 times: 5 x 0.1 SOL is 0.5 SOL.",
                 "Auto-Sell only applies to buys made after you turn it on.",
                 "Remember to fill in both the Buy and the Sell tab of each profile."],
                ["Spam buy ponavlja kupnju do 10 puta: 5 x 0,1 SOL je 0,5 SOL.",
                 "Auto-Sell vrijedi samo za kupnje nakon što ga uključiš.",
                 "Ne zaboravi ispuniti i karticu Buy i karticu Sell u svakom profilu."])),
}
ORDER = ("trojan", "bonkbot", "maestro", "gmgn")

# ───────────────────────────────────────────────────────────────────────────────────────── texts
TX = {
    "en": dict(
        h1="The best-known Telegram trading bots in 2026, and how to set them up",
        title="Best Telegram trading bots 2026: Trojan, BonkBot, Maestro, GMGN | MemeSonar",
        desc="The most used Telegram crypto trading bots compared (fees, chains, official links) with every setting "
             "explained: slippage, priority fee, MEV, auto buy, take profit, stop loss. A setup guide per bot.",
        tag="Telegram bots", crumb="← Best crypto tools",
        tldr="The best-known Telegram trading bots are <b>Trojan</b>, <b>BonkBot</b>, <b>Maestro</b>, the <b>GMGN</b> "
             "bot and <b>Banana Gun</b>. They all charge about <b>1% per trade</b>, so pick on features and safety. "
             "Whatever you choose: open it only from the official link, use a separate small wallet, turn on MEV "
             "protection, keep slippage at 10-15% for normal trades, and set a take profit and stop loss before you buy.",
        intro="<p>A Telegram trading bot is a chat you trade through: paste a token's address, tap a button, and the "
              "bot buys from a wallet it created for you. It is faster than a normal wallet for brand-new Solana tokens "
              "and works from any phone. The price is a fee of about 1% on every buy and sell, and the fact that the bot "
              "holds your trading wallet's key. Below: the bots people actually use, what every setting means, the "
              "values we start with, and a step-by-step guide for each bot.</p>",
        table_h="The bots compared", cols=("Bot", "Chains", "Fee (official docs)", "Official link", "Known for", "Guide"),
        guide="Setup guide", no_guide="–",
        safety_h="Before you start: five safety rules",
        safety=["<b>Official links only.</b> Fake bots copy names (GMGN warns about a capital 'I' posing as an 'l'); "
                "use the links in this table, taken from each bot's own docs.",
                "<b>A separate, small wallet.</b> The bot holds the key of the wallet it creates. Keep only trading money "
                "there; savings belong in your own or a hardware wallet.",
                "<b>Never share the private key or seed phrase.</b> Real admins never DM first and never ask for it.",
                "<b>2FA on Telegram and on the bot.</b> Most stolen bot wallets start with a stolen Telegram account.",
                "<b>Withdraw profits regularly</b> to your own wallet."],
        settings_h="Every setting explained", settings_cols=("Setting", "What it does", "Our starting value"),
        settings_note="<p>Names differ a little between bots, but the ideas are the same. 'Our starting value' is where "
                      "we would begin, not advice; values marked Trojan or GMGN are those bots' own recommendations.</p>",
        panel_h="What a sensible setup looks like", panel_cap="Illustration of the settings we start with, not a "
                                                              "screenshot of any bot",
        slip_h="Slippage: why pool size matters more than the setting",
        slip_note="<p>Slippage is mostly decided by how big your buy is compared with the pool. This is how many fewer "
                  "tokens you get than the quoted price, by buy size and pool liquidity. If the table says 9% for your "
                  "trade, no slippage setting will make it cheap: buy less.</p>",
        cost_h="What one buy really costs",
        cost_note="<p>A 0.5 SOL buy through a 1% bot, with GMGN's recommended on-chain fee. The token account rent comes "
                  "back when you sell; the rest does not. Selling costs the bot fee again.</p>",
        profiles_h="Three starting profiles", profiles_cols=("", "Careful", "Balanced", "New launches"),
        profiles_note="<p>Our starting points for three kinds of trades. The stop loss is wide on purpose: in our data the "
                      "median token fell 46% from its peak even when nothing was wrong with it, so a -10% stop mostly "
                      "sells good tokens on noise.</p>",
        guides_h="Setup guides, bot by bot", faq_h="FAQ",
        faq=[("Which Telegram trading bot is best?",
              "For Solana beginners, BonkBot is the simplest and Trojan has the most features; Maestro if you also "
              "trade on BSC, Base or Ethereum; the GMGN bot if you already use GMGN for research. Fees are about 1% "
              "for all of them."),
             ("Are Telegram trading bots safe?",
              "The bot holds the key of the wallet it creates, so treat it like a hot wallet: small balance, 2FA on, "
              "official links only, and withdraw profits."),
             ("What slippage should I use?",
              "10-15% for normal trades (Trojan's advice), 30-35% for automatic orders and 50%+ only for brand-new "
              "tokens (GMGN's advice). If you need more than that, your buy is too big for the pool."),
             ("What is MEV protection?",
              "It sends your trade through a private route (Jito or similar) so sandwich bots can't buy just before you "
              "and sell just after. It costs a small tip and can be slightly slower."),
             ("Do I need Maestro Premium?",
              "No. Premium ($200/month) adds a faster bot and higher limits; it does not pick better tokens.")],
        sources_h="Sources (official docs, checked 1 November 2026)",
        g_crumb="← Telegram trading bots", facts=("Official link", "Chains", "Fee", "Docs"),
        steps_h="Step by step", g_table_h="Settings to change", g_cols=("Setting", "Where", "Our starting value"),
        watch_h="Watch out", other_h="Other bot guides",
        g_note="Not financial advice. Bot menus change; if a name differs, look for the same idea in the bot's settings. "
               "Facts from the bot's official docs, checked 1 November 2026. No affiliate links."),
    "hr": dict(
        h1="Najpoznatiji Telegram trading botovi 2026. i kako ih postaviti",
        title="Najbolji Telegram trading botovi 2026: Trojan, BonkBot, Maestro, GMGN | MemeSonar",
        desc="Najkorišteniji Telegram trading botovi uspoređeni (naknade, mreže, službeni linkovi) uz "
             "objašnjenje svake postavke: slippage, prioritet, MEV, auto buy, take profit, stop loss. Vodič za svaki.",
        tag="Telegram botovi", crumb="← Najbolji kripto alati",
        tldr="Najpoznatiji Telegram trading botovi su <b>Trojan</b>, <b>BonkBot</b>, <b>Maestro</b>, <b>GMGN</b> bot i "
             "<b>Banana Gun</b>. Svi naplaćuju oko <b>1% po tradeu</b>, pa biraj po funkcijama i sigurnosti. Što god "
             "odabrao: otvaraj ga samo preko službenog linka, koristi poseban mali novčanik, uključi MEV zaštitu, drži "
             "slippage na 10-15% za obične tradeove i postavi take profit i stop loss prije kupnje.",
        intro="<p>Telegram trading bot je chat preko kojeg trguješ: zalijepiš adresu tokena, dodirneš gumb i bot kupi iz "
              "novčanika koji ti je napravio. Brži je od običnog novčanika za posve nove Solana tokene i radi s bilo "
              "kojeg mobitela. Cijena je naknada od oko 1% na svaku kupnju i prodaju te to što bot drži ključ tvog "
              "trading novčanika. Ispod: botovi koje ljudi stvarno koriste, što znači svaka postavka, vrijednosti s "
              "kojima mi krećemo i vodič korak po korak za svaki bot.</p>",
        table_h="Usporedba botova", cols=("Bot", "Mreže", "Naknada (službeno)", "Službeni link", "Poznat po", "Vodič"),
        guide="Vodič", no_guide="–",
        safety_h="Prije početka: pet sigurnosnih pravila",
        safety=["<b>Samo službeni linkovi.</b> Lažni botovi kopiraju imena (GMGN upozorava na veliko 'I' umjesto malog "
                "'l'); koristi linkove iz ove tablice, preuzete iz dokumentacije svakog bota.",
                "<b>Poseban, mali novčanik.</b> Bot drži ključ novčanika koji napravi. Drži tamo samo novac za "
                "trgovanje; ušteđevina ide u tvoj ili hardverski novčanik.",
                "<b>Nikad ne dijeli privatni ključ ni seed frazu.</b> Pravi admini nikad ne pišu prvi i nikad je ne traže.",
                "<b>2FA na Telegramu i na botu.</b> Većina ukradenih bot novčanika krene od ukradenog Telegram računa.",
                "<b>Redovito podiži dobit</b> u svoj novčanik."],
        settings_h="Svaka postavka objašnjena", settings_cols=("Postavka", "Što radi", "Naša početna vrijednost"),
        settings_note="<p>Nazivi se malo razlikuju među botovima, ali ideje su iste. 'Naša početna vrijednost' je odakle "
                      "bismo mi krenuli, nije savjet; vrijednosti označene s Trojan ili GMGN su preporuke samih botova.</p>",
        panel_h="Kako izgleda razumna postavka", panel_cap="Ilustracija postavki s kojima krećemo, nije snimka "
                                                           "zaslona nijednog bota",
        slip_h="Slippage: zašto je veličina poola važnija od postavke",
        slip_note="<p>Slippage uglavnom ovisi o tome kolika je tvoja kupnja u odnosu na pool. Ovo je koliko manje tokena "
                  "dobiješ od navedene cijene, prema iznosu kupnje i likvidnosti poola. Ako tablica za tvoj trade "
                  "kaže 9%, nijedna postavka slippagea ga neće pojeftiniti: kupi manje.</p>",
        cost_h="Koliko jedna kupnja stvarno košta",
        cost_note="<p>Kupnja od 0,5 SOL preko bota s 1% naknade, uz GMGN-ovu preporučenu mrežnu naknadu. Najam računa "
                  "tokena vraća se kad prodaš; ostalo ne. Prodaja opet košta naknadu bota.</p>",
        profiles_h="Tri početna profila", profiles_cols=("", "Oprezno", "Uravnoteženo", "Nova lansiranja"),
        profiles_note="<p>Naše početne točke za tri vrste tradeova. Stop loss je namjerno širok: u našim podacima medijan "
                      "tokena pao je 46% od vrha i kad s njim nije bilo ništa loše, pa stop od -10% uglavnom proda dobre "
                      "tokene na običnom ljuljanju.</p>",
        guides_h="Vodiči za postavljanje, bot po bot", faq_h="Česta pitanja",
        faq=[("Koji je Telegram trading bot najbolji?",
              "Za početnike na Solani BonkBot je najjednostavniji, a Trojan ima najviše funkcija; Maestro ako trguješ i "
              "na BSC-u, Baseu ili Ethereumu; GMGN bot ako već koristiš GMGN za istraživanje. Naknade su oko 1% za sve."),
             ("Jesu li Telegram trading botovi sigurni?",
              "Bot drži ključ novčanika koji napravi, pa ga tretiraj kao vrući novčanik: mali iznos, 2FA uključen, samo "
              "službeni linkovi i podiži dobit."),
             ("Koji slippage koristiti?",
              "10-15% za obične tradeove (Trojanov savjet), 30-35% za automatske naloge, a 50%+ samo za posve nove "
              "tokene (GMGN-ov savjet). Ako trebaš više od toga, kupnja ti je prevelika za pool."),
             ("Što je MEV zaštita?",
              "Šalje tvoj trade privatnom rutom (Jito ili slično) pa sendvič botovi ne mogu kupiti tik prije tebe i "
              "prodati tik poslije. Košta mali tip i može biti malo sporije."),
             ("Trebam li Maestro Premium?",
              "Ne. Premium ($200 mjesečno) daje bržeg bota i veća ograničenja; ne bira bolje tokene.")],
        sources_h="Izvori (službena dokumentacija, provjereno 1. studenoga 2026.)",
        g_crumb="← Telegram trading botovi", facts=("Službeni link", "Mreže", "Naknada", "Dokumentacija"),
        steps_h="Korak po korak", g_table_h="Postavke koje treba promijeniti",
        g_cols=("Postavka", "Gdje", "Naša početna vrijednost"), watch_h="Na što paziti", other_h="Vodiči za druge botove",
        g_note="Nije financijski savjet. Izbornici botova se mijenjaju; ako se naziv razlikuje, potraži istu ideju u "
               "postavkama bota. Činjenice iz službene dokumentacije bota, provjereno 1. studenoga 2026. Bez affiliate "
               "linkova."),
}

CSS = """
.tgw{display:flex;justify-content:center;margin:24px 0}.tgm{width:min(360px,100%);background:#17212b;border-radius:22px;
padding:14px;color:#e9eef4;box-shadow:0 20px 50px -25px rgba(11,18,32,.6);font-size:14px}
.tgm .hd{display:flex;align-items:center;gap:10px;padding:4px 4px 12px;border-bottom:1px solid #26323e;margin-bottom:12px}
.tgm .av{width:34px;height:34px;border-radius:50%;background:linear-gradient(135deg,#4f46e5,#0fb5a0);display:grid;
place-items:center;font-weight:700}.tgm .hd b{display:block}.tgm .hd span{color:#8b9bab;font-size:12px}
.tgm .bub{background:#182533;border:1px solid #26323e;border-radius:14px 14px 14px 4px;padding:10px 12px;margin-bottom:8px}
.tgm .kb{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px}.tgm .kb div{background:#2b5278;border-radius:10px;
padding:8px 6px;text-align:center;line-height:1.25}.tgm .kb div b{display:block;font-size:12.5px;font-weight:600}
.tgm .kb div span{font-size:12px;color:#c9e2ff}.tgcap{text-align:center;color:var(--mut);font-size:13px;margin-top:-12px}
.steps{list-style:none;padding:0;counter-reset:s}.steps li{counter-increment:s;position:relative;padding:14px 16px 14px
58px;border:1px solid var(--line);border-radius:16px;margin:10px 0;background:#fff}.steps li:before{content:counter(s);
position:absolute;left:16px;top:14px;width:28px;height:28px;border-radius:50%;background:var(--fg);color:#fff;
display:grid;place-items:center;font-weight:700;font-size:14px}.steps b{display:block;margin-bottom:2px}
.facts{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin:18px 0}.facts div{background:var(--soft);
border-radius:14px;padding:10px 14px;font-size:15px}.facts b{display:block;color:var(--mut);font-size:12.5px;
text-transform:uppercase;letter-spacing:.05em}@media(max-width:560px){.facts{grid-template-columns:1fr}}
"""


def _base(lang):
    return "/best-crypto-tools" if lang == "en" else "/hr/najbolji-kripto-alati"


def gpath(key, lang):
    return f"{_base(lang)}/{GUIDES_SLUG[key][lang]}"


GUIDES_SLUG = {b["key"]: b["slug"] for b in BOTS if b["slug"]}


def opath(lang):
    return f"{_base(lang)}/{OVERVIEW[lang]}"


def urls():
    out = [(opath("en"), opath("hr"), "0.7")]
    return out + [(gpath(k, "en"), gpath(k, "hr"), "0.6") for k in ORDER]


def nav_items(lang):
    """Menu entry in the Tools group (ui/sitenav.py PLUGINS)."""
    return [("tools", opath(lang), "Telegram trading bots" if lang == "en" else "Telegram trading botovi",
             "Setup guides and best settings" if lang == "en" else "Vodiči i najbolje postavke")]


def _ext(url, label):
    return f"<a href=\"{esc(url)}\" rel=\"nofollow noopener\" target=_blank>{esc(label)} ↗</a>"


def _panel(rows, title):
    kb = "".join(f"<div><b>{esc(a)}</b>" + (f"<span>{esc(b)}</span>" if b else "") + "</div>" for a, b in rows)
    return (f"<div class=tgw><div class=tgm role=img aria-label=\"{esc(title)}\"><div class=hd><div class=av>⚙</div>"
            f"<div><b>{esc(title)}</b><span>/settings</span></div></div><div class=bub>⚙️ Settings</div>"
            f"<div class=kb>{kb}</div></div></div>")


def _table(cols, rows):
    head = "".join(f"<th>{c}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<div class=tw><table class=ttab><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def _slip_grid(lang):
    from ui.blogviz import grid
    if lang == "en":
        return grid("Fewer tokens than the quoted price, by buy size and pool liquidity",
                    ["$100", "$500", "$1,000", "$5,000"],
                    [("Pool $10k", [2.0, 9.1, 16.7, 50.0]), ("Pool $50k", [0.4, 2.0, 3.8, 16.7]),
                     ("Pool $250k", [0.1, 0.4, 0.8, 3.8]), ("Pool $1M", [0.0, 0.1, 0.2, 1.0])],
                    sub="Constant-product pool, before fees", cap=50, lang=lang)
    return grid("Manje tokena od navedene cijene, prema iznosu kupnje i likvidnosti poola",
                ["$100", "$500", "$1.000", "$5.000"],
                [("Pool $10k", [2.0, 9.1, 16.7, 50.0]), ("Pool $50k", [0.4, 2.0, 3.8, 16.7]),
                 ("Pool $250k", [0.1, 0.4, 0.8, 3.8]), ("Pool $1M", [0.0, 0.1, 0.2, 1.0])],
                sub="Pool s konstantnim produktom, prije naknada", cap=50, lang=lang)


def _cost_bars(lang):
    from ui.blogviz import bars
    en = lang == "en"
    rows = [("Bot fee (1%)" if en else "Naknada bota (1%)", 0.005, "kept by the bot" if en else "zadrži bot"),
            ("Priority + tip" if en else "Prioritet + tip", 0.004,
             "GMGN: 0.002-0.005 SOL" if en else "GMGN: 0,002-0,005 SOL"),
            ("Token account rent" if en else "Najam računa tokena", 0.002,
             "refunded when you sell" if en else "vraća se kad prodaš"),
            ("Network base fee" if en else "Osnovna mrežna naknada", 0.000005, "0.000005 SOL" if en else "0,000005 SOL")]
    return bars("Costs of a 0.5 SOL buy" if en else "Troškovi kupnje od 0,5 SOL", rows,
                sub="SOL", fmt="sol", hl=(0,), source="Official docs: GMGN, Trojan, Maestro" if en else
                "Službena dokumentacija: GMGN, Trojan, Maestro", lang=lang)


def _faq(faq):
    html = "<div class=faq>" + "".join(f"<h3>{esc(q)}</h3><p>{esc(a)}</p>" for q, a in faq) + "</div>"
    return html, {"@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": q,
                                                      "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]}


def _guide_cards(lang, skip=None):
    out = []
    for k in ORDER:
        if k == skip:
            continue
        g, b = GUIDES[k], BY_KEY[k]
        out.append(f"<a href={gpath(k, lang)}><em>{esc(b['name'])}</em><b>{esc(g['h1'][lang])}</b>"
                   f"<span>{esc(g['desc'][lang])}</span></a>")
    return "".join(out)


def _ld(obj):
    from ui.tools import _ld as ld
    return ld(obj)


def overview(lang):
    from ui.public import _shell
    from ui.tools import L as TL
    t, s = TX[lang], TL[lang]
    rows = []
    for b in BOTS:
        links = "<br>".join(_ext(u, n[lang] if isinstance(n, dict) else n) for n, u in b["links"])
        guide = f"<a href={gpath(b['key'], lang)}>{t['guide']} →</a>" if b["slug"] else t["no_guide"]
        rows.append((f"<b>{esc(b['name'])}</b>", esc(b["chains"][lang]), esc(b["fee"][lang]), links, esc(b["known"][lang]),
                     guide))
    i = 0 if lang == "en" else 1
    sets = [(f"<b>{esc(r[0 + i])}</b>", esc(r[2 + i]), esc(r[4 + i])) for r in SETTINGS]
    profs = [(f"<b>{esc(lab[i])}</b>",) + tuple(esc(v) for v in (en if lang == "en" else hr))
             for lab, en, hr in PROFILES]
    panel = _panel(GUIDES["bonkbot"]["panel"], "Trading bot")
    faq_html, faq_ld = _faq(t["faq"])
    src = "".join(f"<li>{_ext(b['docs'], b['name'] + ' docs')}</li>" for b in BOTS)
    body = (f"<article class=art><section class=ph1><div class=crumb><a href={_base(lang)}>{t['crumb']}</a> · "
            f"{esc(t['tag'])}</div><h1>{esc(t['h1'])}</h1><div class=meta>{s['checked']} · {s['by']}</div>"
            f"<div class=tldr><b>{s['short']}</b><p>{t['tldr']}</p></div></section>{t['intro']}"
            f"<h2>{t['table_h']}</h2></article>{_table(t['cols'], rows)}<article class=art>"
            f"<h2>{t['safety_h']}</h2><ol>{''.join(f'<li>{x}</li>' for x in t['safety'])}</ol>"
            f"<h2>{t['settings_h']}</h2>{t['settings_note']}</article>{_table(t['settings_cols'], sets)}"
            f"<article class=art><h2>{t['panel_h']}</h2>{panel}<p class=tgcap>{t['panel_cap']}</p>"
            f"<h2>{t['slip_h']}</h2>{t['slip_note']}{_slip_grid(lang)}"
            f"<h2>{t['cost_h']}</h2>{t['cost_note']}{_cost_bars(lang)}"
            f"<h2>{t['profiles_h']}</h2>{t['profiles_note']}</article>{_table(t['profiles_cols'], profs)}"
            f"<h2 class=s>{t['guides_h']}</h2><div class=bl>{_guide_cards(lang)}</div>"
            f"<article class=art><h2>{t['faq_h']}</h2>{faq_html}"
            f"<div class=lock><p>{s['lock']}</p><a class='btn sm' href={s['home']}#pristup>{s['cta']}</a></div>"
            f"<p class=note>{t['g_note']}</p><h2 style='font-size:19px'>{t['sources_h']}</h2><ul class=src>{src}</ul>"
            f"</article>{_chips(lang)}")
    url = _site() + opath(lang)
    jsonld = _ld({"@context": "https://schema.org", "@graph": [
        {"@type": "Article", "headline": t["h1"], "description": t["desc"], "datePublished": CHECKED,
         "dateModified": CHECKED, "mainEntityOfPage": url, "inLanguage": lang,
         "author": {"@type": "Organization", "name": "MemeSonar"}, "publisher": {"@type": "Organization", "name": "MemeSonar"}},
        {"@type": "ItemList", "itemListElement": [{"@type": "ListItem", "position": n, "name": b["name"],
                                                   "url": b["links"][0][1]} for n, b in enumerate(BOTS, 1)]},
        faq_ld]})
    return _shell(lang, t["title"], t["desc"], opath("en"), opath("hr"), body, jsonld=jsonld, og_type="article")


def _chips(lang):
    from ui.tools import _chips as ch
    return ch(("trading-bot", "slippage", "priority-fee", "mev-protection", "take-profit", "stop-loss", "sniper-bot", "liquidity"), lang)


def _site():
    import os
    return os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")


def guide(key, lang):
    from ui.public import _shell
    from ui.tools import L as TL
    t, s, g, b = TX[lang], TL[lang], GUIDES[key], BY_KEY[key]
    links = " · ".join(_ext(u, n[lang] if isinstance(n, dict) else n) for n, u in b["links"])
    facts = (f"<div class=facts><div><b>{t['facts'][0]}</b>{links}</div><div><b>{t['facts'][1]}</b>{esc(b['chains'][lang])}"
             f"</div><div><b>{t['facts'][2]}</b>{esc(b['fee'][lang])}</div><div><b>{t['facts'][3]}</b>"
             f"{_ext(b['docs'], b['docs'].replace('https://', ''))}</div></div>")
    j = 0 if lang == "en" else 2
    steps = "".join(f"<li><b>{esc(st[j])}</b>{esc(st[j + 1])}</li>" for st in g["steps"])
    rows = [(f"<b>{esc(r[0])}</b>", esc(r[1]), esc(r[2] if lang == "en" else r[3])) for r in g["table"]]
    watch = "".join(f"<li>{esc(w)}</li>" for w in g["watch"][lang])
    howto = {"@type": "HowTo", "name": g["h1"][lang], "step": [
        {"@type": "HowToStep", "position": n, "name": st[j], "text": st[j + 1]} for n, st in enumerate(g["steps"], 1)]}
    body = (f"<article class=art><section class=ph1><div class=crumb><a href={opath(lang)}>{t['g_crumb']}</a> · "
            f"{esc(b['name'])}</div><h1>{esc(g['h1'][lang])}</h1><div class=meta>{s['checked']} · {s['by']}</div>"
            f"<div class=tldr><b>{s['short']}</b><p>{g['tldr'][lang]}</p></div></section>{facts}"
            f"<h2>{t['steps_h']}</h2><ol class=steps>{steps}</ol>"
            f"<h2>{t['g_table_h']}</h2></article>{_table(t['g_cols'], rows)}<article class=art>"
            f"<h2>{t['panel_h']}</h2>{_panel(g['panel'], b['name'])}<p class=tgcap>{t['panel_cap']}</p>"
            f"<h2>{t['watch_h']}</h2><ul>{watch}</ul>"
            f"<p>{'Every setting in detail, and three starting profiles' if lang == 'en' else 'Svaka postavka detaljno i tri početna profila'}: "
            f"<a href={opath(lang)}>{esc(t['h1'])}</a>.</p>"
            f"<div class=lock><p>{s['lock']}</p><a class='btn sm' href={s['home']}#pristup>{s['cta']}</a></div>"
            f"<p class=note>{t['g_note']}</p></article>{_chips(lang)}"
            f"<h2 class=s>{t['other_h']}</h2><div class=bl>{_guide_cards(lang, skip=key)}</div>")
    url = _site() + gpath(key, lang)
    jsonld = _ld({"@context": "https://schema.org", "@graph": [
        {"@type": "Article", "headline": g["h1"][lang], "description": g["desc"][lang], "datePublished": CHECKED,
         "dateModified": CHECKED, "mainEntityOfPage": url, "inLanguage": lang,
         "author": {"@type": "Organization", "name": "MemeSonar"}, "publisher": {"@type": "Organization", "name": "MemeSonar"}},
        howto]})
    return _shell(lang, g["title"][lang], g["desc"][lang], gpath(key, "en"), gpath(key, "hr"), body, jsonld=jsonld,
                  og_type="article")


def page(slug, lang):
    """Overview or a bot guide for this slug in this language, or None."""
    if slug == OVERVIEW[lang]:
        return overview(lang)
    for k in ORDER:
        if GUIDES_SLUG[k][lang] == slug:
            return guide(k, lang)
    return None


def promo(lang):
    """Box on the trading-bots category page that points to the overview and the four setup guides."""
    en = lang == "en"
    links = " · ".join(f"<a href={gpath(k, lang)}>{esc(BY_KEY[k]['name'])}</a>" for k in ORDER)
    return (f"<div class=tldr><b>{'Setup guides' if en else 'Vodiči za postavljanje'}</b><p>"
            + ("Using a Telegram bot? Read <a href=" + opath(lang) + ">the best-known Telegram trading bots, every "
               "setting explained and the values we start with</a>, or jump to a step-by-step guide: " if en else
               "Koristiš Telegram bota? Pročitaj <a href=" + opath(lang) + ">najpoznatiji Telegram trading botovi, "
               "objašnjena svaka postavka i vrijednosti s kojima počinjemo</a> ili otvori vodič korak po korak: ")
            + links + ".</p></div>")
