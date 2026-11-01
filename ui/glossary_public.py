"""Public, indexable glossary: /glossary (English, main) and /hr/rjecnik (Croatian).

Only general crypto / trading / influencer terms go public; internal app pages, columns and algorithm weights stay in
the members-only /pojmovnik. English texts are written here; the Croatian pages reuse ui/glossary.TERMS, so both
languages always describe the same term (hreflang pairs).

Each entry: HR key in glossary.TERMS -> English slug, name, question (H1/title), one-line answer, longer explanation,
example, and an optional link to a live KriptoRadar page that shows the term in action.
"""
from ui import glossary as G

# (hr_key, en_slug, name, question, short, long, example, live_link)
_E = [
    ("token", "token", "Token", "What is a crypto token?",
     "A digital coin on a blockchain such as Solana that people buy and sell like a share.",
     "Anyone can create a new Solana token for a few dollars, most often on pump.fun. Most of these are meme coins: they "
     "have no value apart from the attention they get. The price goes up when people buy and down when they sell. "
     "KriptoRadar sees thousands of new tokens every day and tries to find the rare ones that grow while filtering out "
     "scams.", "FARTCOIN, USELESS and TRUMP are tokens. Each has its own contract address that tells it apart from "
     "copies with the same name.", ("/solana-meme-coins", "Top Solana meme coins")),
    ("ca", "contract-address", "Contract address (CA)", "What is a contract address (CA)?",
     "The unique address of a token on the blockchain, like an ID number.",
     "Names and tickers can be copied by anyone, so scammers often launch fake tokens with the same name as a popular "
     "one. The contract address is the only reliable way to know you are buying the real token. Always copy it from a "
     "trusted source and check it on DexScreener or Solscan before buying.",
     "The real Pudgy Penguins (PENGU) token has one address; ten other tokens called PENGU are copies.", None),
    ("mcap", "market-cap", "Market cap", "What is market cap in crypto?",
     "Price multiplied by the number of tokens in circulation: what the whole token is worth right now.",
     "Market cap tells you how big a token is and how much room it has to grow. A token at $50k market cap can do 10x "
     "with a little buying; a token at $500M needs billions of dollars to do the same. On thin pools the market cap can "
     "be misleading: if liquidity is tiny, the price (and with it the market cap) can be pushed up with very little "
     "money.", "1 billion tokens at $0.002 = $2M market cap.", ("/solana-meme-coins", "Meme coins by market cap")),
    ("fdv", "fdv", "FDV (fully diluted valuation)", "What is FDV (fully diluted valuation)?",
     "What a token would be worth if every token that can ever exist were already in circulation.",
     "FDV = price x maximum supply. When FDV is much higher than market cap, many tokens are still locked or unissued "
     "and will be sold into the market later, which pushes the price down. For most pump.fun meme coins the whole supply "
     "exists from day one, so FDV and market cap are the same.", "Price $0.01, circulating 100M, max supply 1B: "
     "market cap $1M, FDV $10M.", None),
    ("likvidnost", "liquidity", "Liquidity", "What is liquidity in crypto?",
     "How much money sits in the trading pool, which decides how much you can buy or sell without moving the price.",
     "A token with $5k of liquidity jumps or crashes on a single $500 trade, and you may not be able to sell at the "
     "price you see. Liquidity can also be pulled by the creator, which is the classic rug pull. KriptoRadar ignores "
     "tokens with liquidity under $10k and treats a pool smaller than 0.2% of the market cap as a fake price.",
     "A $1M token with $300k liquidity is easy to trade; a $1M token with $2k liquidity is a trap.", None),
    ("volumen", "trading-volume", "Trading volume", "What is trading volume?",
     "The dollar value of all buys and sells in a period, usually the last 24 hours.",
     "Volume shows real interest. A big market cap with almost no volume usually means nobody is actually trading the "
     "token and the price is not real. A volume spike after an influencer post shows how many buyers the post really "
     "brought, which is one of the things KriptoRadar measures for every call.", "PENGU trades over $2M a day; many "
     "dead tokens trade under $1,000.", None),
    ("holderi", "holders", "Holders", "What are token holders?",
     "The number of wallets that own a token.",
     "More holders usually means wider distribution and less risk that one person can crash the price. A falling "
     "holder count while the price rises is a warning sign. What matters just as much is how much the biggest wallets "
     "own: if the top 10 wallets hold half of the supply, they control the price.", "BONK has over 1 million holders.",
     ("/solana-meme-coins", "Holders of top meme coins")),
    ("wallet", "crypto-wallet", "Wallet", "What is a crypto wallet?",
     "An account on the blockchain that holds your tokens, controlled by a secret key or seed phrase.",
     "On Solana the most popular wallet is Phantom. Every wallet has a public address that anyone can look up, which is "
     "why wallet tracking works: you can see what any wallet buys and sells. Never share your seed phrase or private key "
     "with anyone, including tools and support staff.", "A wallet address looks like 84AWq5Mb...MdTs.", None),
    ("smart-money", "smart-money", "Smart money", "What is smart money in crypto?",
     "Wallets with a proven record of profits that are often early in tokens that later grow.",
     "Because every trade on Solana is public, you can rank wallets by what they actually earned. KriptoRadar scores "
     "thousands of wallets by real profit. When several of them show up among the first buyers of a new token, that is "
     "one of the strongest signals we know.", "Five profitable wallets buying the same token within ten minutes.", None),
    ("dex", "dex", "DEX (decentralized exchange)", "What is a DEX?",
     "An exchange that runs on the blockchain, where you trade straight from your wallet without an account.",
     "On Solana the main DEXes are Raydium, Meteora, Orca and PumpSwap; Jupiter finds the best price across all of "
     "them. New meme coins trade on DEXes long before any centralized exchange lists them.",
     "Swapping SOL for BONK in Phantom goes through a DEX.", None),
    ("cex", "cex", "CEX (centralized exchange)", "What is a CEX?",
     "A classic exchange run by a company, such as Binance, Coinbase or Bybit, where you need an account.",
     "A listing on a big CEX brings new buyers and often moves the price. For long-term tokens KriptoRadar also watches "
     "how much of the supply sits in exchange wallets: a rising share often means holders are getting ready to sell.",
     "WIF and BONK are listed on most big exchanges.", None),
    ("pump-fun", "pump-fun", "pump.fun", "What is pump.fun?",
     "The most popular Solana launchpad, where anyone can create a meme coin in a minute.",
     "Tokens start on a bonding curve: the price rises automatically as people buy. When enough money is collected, the "
     "token graduates to a real DEX pool. Tens of thousands of tokens launch on pump.fun every day; only a tiny share "
     "survive the first day.", "Token addresses ending in 'pump' were created on pump.fun.", None),
    ("graduacija", "graduation", "Graduation", "What does graduation mean on pump.fun?",
     "The moment a pump.fun token collects enough money and moves to a real DEX pool.",
     "Before graduation the token trades on the launchpad's curve; after it, it has a real liquidity pool and shows up on "
     "DexScreener and Jupiter. Tokens close to graduation often get a fresh wave of attention.", "", None),
    ("slippage", "slippage", "Slippage", "What is slippage in crypto?",
     "The difference between the price you see and the price you actually get.",
     "On thin pools a big order moves the price while it is being filled, so you buy higher and sell lower than "
     "planned. Wallets let you set the maximum slippage you accept. KriptoRadar's demo trading includes slippage in "
     "every simulated exit, so results are not better on paper than they would be in real life.",
     "You buy at $0.010 with 5% slippage and get filled at $0.0105.", None),
    ("memecoin", "memecoin", "Meme coin", "What is a meme coin?",
     "A token built on a joke, meme or trend, with no product behind it; its price runs on attention.",
     "Meme coins can do 100x in hours and lose 99% just as fast. Most new ones are abandoned or scams within a day. The "
     "few that survive (such as BONK, WIF or Fartcoin) build communities worth hundreds of millions. That is why data on "
     "who buys and who promotes a coin matters more than the meme itself.", "DOGE on Ethereum, BONK and WIF on Solana.",
     ("/solana-meme-coins", "Top 100 Solana meme coins")),
    ("rug", "rug-pull", "Rug pull", "What is a rug pull?",
     "A scam or crash where the creators take the money and the token falls 90%+ and never recovers.",
     "The creator pulls the liquidity or sells all their tokens at once, leaving buyers with a coin nobody can sell. "
     "KriptoRadar marks a token as rugged when it falls 70%+ from its top within 24 hours or when liquidity is pulled, "
     "hides it from members and learns from every rug how to spot the next one.",
     "A token goes from $400k to $8k in two minutes after the creator sells.", None),
    ("dev", "dev-wallet", "Dev wallet", "What is a dev wallet?",
     "The wallet of the person who created the token.",
     "If the dev holds a big share and starts selling, the price usually crashes. Serial devs who launch a new token "
     "every few hours and dump each one are a common pattern on pump.fun.", "", None),
    ("bundler", "bundler", "Bundler", "What is a bundler in crypto?",
     "Someone who buys a large part of a new token in the same second it launches, spread over many wallets.",
     "It makes the token look like it has many buyers, while one person holds the supply and can sell it all at once. "
     "More than 15% of supply in bundled wallets is a red flag.", "", None),
    ("sniper", "sniper-bot", "Sniper bot", "What is a sniper bot?",
     "A bot that buys a token in the first seconds after launch to sell it quickly.",
     "Snipers sell as soon as the price rises a little, so their buys are not a sign of real interest. KriptoRadar never "
     "puts sniper wallets on its copy-trading list.", "", None),
    ("insajder", "insider-wallet", "Insider wallet", "What is an insider wallet?",
     "A wallet that buys before an influencer posts and sells into the wave of buyers the post brings.",
     "If insiders sell right after a call, the call was probably arranged or paid: the influencer brought buyers so "
     "someone else could sell. KriptoRadar checks wallets around every call and does not count such calls as signals.",
     "", None),
    ("mint-authority", "mint-authority", "Mint authority", "What is mint authority?",
     "The right to create new tokens out of thin air.",
     "If mint authority is still active, the owner can print new tokens and dump them on buyers. Freeze authority is "
     "similar: it lets the owner freeze your tokens so you cannot sell. Safe meme coins have both revoked; every coin "
     "page on KriptoRadar shows this check.", "", ("/solana-meme-coins", "Safety check on every coin")),
    ("kol", "kol", "KOL (key opinion leader)", "What is a KOL in crypto?",
     "An influencer, usually on X (Twitter) or Telegram, whose posts move token prices.",
     "When a KOL calls a token, their followers buy and the price often jumps, sometimes only for minutes. Some KOLs are "
     "early and right; others are paid to bring buyers while insiders sell. KriptoRadar measures every call: how much the "
     "price and volume moved after it, how often the token rugged and whether the KOL was late.",
     "", ("/influencers", "Crypto influencer rankings")),
    ("poziv", "crypto-call", "Call", "What is a crypto call?",
     "A post in which an influencer tells followers to buy a specific token, usually with its address.",
     "KriptoRadar records every call it sees on X and Telegram and measures what happened after 1 hour, 6 hours and 24 "
     "hours. Several influencers calling the same token within 15 minutes is a much stronger signal than one call alone.",
     "", ("/influencers", "Measured calls of influencers")),
    ("moc-poziva", "call-power", "Call power", "What is call power?",
     "A 0-100 score for how much an influencer's calls move price and volume on average.",
     "It combines the hit rate (how many calls grow 50%+ in 24 hours), growth after 1 and 24 hours, how many buyers a "
     "post brings, whether the influencer was first and how rarely their tokens rug; late calls take points away. Until "
     "an influencer has enough measured calls the score stays close to 35.", "",
     ("/influencers", "Influencers ranked by call power")),
    ("pogodak", "hit-rate", "Hit rate", "What is a hit rate for crypto calls?",
     "The share of calls after which the token was at least 50% higher within 24 hours.",
     "A 40% hit rate means 4 out of 10 calls grew by at least half within a day. Hit rate alone can mislead, which is "
     "why KriptoRadar shows it next to the rug rate and late calls.", "", ("/influencers", "Hit rate of every influencer")),
    ("kasni-pozivi", "late-call", "Late call", "What is a late call?",
     "A call posted after the price had already doubled in the two hours before the post.",
     "An influencer who calls only after the jump either catches the top or is paid to bring buyers for someone's exit. "
     "Late calls lower an influencer's score on KriptoRadar.", "", None),
    ("bot-racun", "bot-account", "Bot account", "What is a crypto bot account?",
     "An account that posts token addresses automatically, not a person giving an opinion.",
     "Scanner bots post every new token, so their 'calls' say nothing. KriptoRadar detects them and keeps them out of "
     "rankings, signals and copy trading.", "", None),
    ("copy-trading", "copy-trading", "Copy trading", "What is copy trading in crypto?",
     "Automatically buying what a chosen influencer calls or what a chosen wallet buys.",
     "On KriptoRadar members pick an influencer or a wallet and press Follow; the tool then enters every new call no "
     "older than 10 minutes on the member's demo account and sells by the exit rules. Copy trading works only if you "
     "copy people whose record is measured, which is what the rankings are for.", "", None),
    ("dca", "dca", "DCA (dollar-cost averaging)", "What is DCA (dollar-cost averaging)?",
     "Buying a fixed amount at regular intervals instead of everything at once.",
     "DCA spreads your entry over time, so you do not have to guess the bottom. KriptoRadar's automatic DCA buys a set "
     "amount every 15 minutes to once a week and stops on its own if the token rugs or liquidity drops under $5k.",
     "$25 every day for 20 days instead of $500 today.", None),
    ("take-profit", "take-profit", "Take profit", "What is take profit?",
     "An order that sells automatically when the price reaches your target.",
     "With meme coins gains vanish quickly, so selling part of the position at 2x and letting the rest run is a common "
     "rule.", "Sell half at +100%, the rest at +300%.", None),
    ("stop-loss", "stop-loss", "Stop loss", "What is a stop loss?",
     "An order that sells automatically when the price falls to a set level, to limit the loss.",
     "A trailing stop moves up as the price rises, so it locks in part of the gain.", "Buy at $1, stop loss at $0.70.",
     None),
    ("pnl", "pnl", "PnL (profit and loss)", "What is PnL in trading?",
     "Profit and loss: how much you have earned or lost.",
     "Realized PnL comes from trades you closed; unrealized PnL is the current value of positions you still hold.", "",
     None),
    ("roi", "roi", "ROI", "What is ROI in crypto?",
     "Return on investment: profit as a percentage of what you put in.", "", "Put in $100, got $150: ROI +50%.", None),
    ("multiplikator", "x-multiplier", "2x, 10x (multiplier)", "What does 2x or 10x mean in crypto?",
     "How many times the price grew from where you bought.",
     "2x means the price doubled (+100%), 10x means it grew ten times (+900%).", "", None),
    ("klaster", "wallet-cluster", "Wallet cluster", "What is a wallet cluster?",
     "A group of wallets that look like one owner or one team: same source of money, same buys in the same second.",
     "Clusters can fake many independent buyers. KriptoRadar links wallets by funding and timing so a group counts once.",
     "", None),
    ("dugorocni-token", "long-term-tokens", "Long-term token", "What makes a meme coin a long-term token?",
     "An older token (3+ weeks, $5M+ market cap, $100k+ daily volume) that survives and keeps growing.",
     "A safer layer than hunting brand-new tokens. KriptoRadar looks for tokens that recover from drops, outgrow SOL and "
     "do not lose holders, and checks the top 20 holders and exchange share every week.", "Fartcoin and Useless.",
     ("/solana-meme-coins", "Top Solana meme coins")),
]

ENTRIES = []
BY_EN, BY_HR = {}, {}
for hr, en, name, q, short, long, ex, live in _E:
    if hr not in G.TERMS:           # glossary entry renamed: skip instead of breaking the public site
        continue
    e = {"hr": hr, "en": en, "name": name, "q": q, "short": short, "long": long, "ex": ex, "live": live}
    ENTRIES.append(e)
    BY_EN[en] = e
    BY_HR[hr] = e


def hr_term(e):
    return G.TERMS[e["hr"]]


def related(e, lang):
    """Other public terms this one points to (from the Croatian 'vidi' list), as entries."""
    out = [BY_HR[k] for k in G.TERMS[e["hr"]].get("vidi", []) if k in BY_HR and k != e["hr"]]
    cat = G.TERMS[e["hr"]]["cat"]
    i = ENTRIES.index(e)
    for x in ENTRIES[i + 1:] + ENTRIES[:i]:          # fill up with neighbours from the same group
        if len(out) >= 6:
            break
        if x is not e and x not in out and G.TERMS[x["hr"]]["cat"] == cat:
            out.append(x)
    return out[:6]
