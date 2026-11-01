"""Ten posts added on 1 November 2026 (English). Topics come from the MemeSonar research library plus outside sources.

None of the numbers here are MemeSonar measurements: every figure is someone else's case or study and the post names
the source right next to it (chart "Source:" line or the sentence). Keep it that way when editing.
"""
from ui.blogposts import post
from ui.blogviz import bars, stats

D = "2026-11-01"

# 1 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "address-poisoning", "Scams",
    "Address poisoning: how to check a wallet address before you send (step by step)",
    "Address poisoning: how to check a crypto address before sending | MemeSonar",
    "Address poisoning puts a lookalike address in your history right after you send a test transfer. Here is the "
    "exact routine that stops it in Phantom, MetaMask and on exchanges.",
    ["address poisoning", "address poisoning attack", "crypto address scam", "wrong wallet address"], 6,
    "Address poisoning is a scam where an attacker sends you a tiny or zero-value transfer from an address that "
    "starts and ends with the same characters as one you use. If you later copy the address from your history, you "
    "send money to the attacker. The fix is a routine: never copy from history, save addresses in the address book, "
    "and check the middle characters, not just the start and end.",
    f"""
<h2>How the attack works</h2>
<p>Wallets shorten addresses to the first and last few characters, like <code>0xbaf4...B6495F8b5</code>. Attackers
generate an address that matches those visible characters and then put it into your transaction history in one of
three ways: a tiny "dust" transfer to you, a fake token transfer, or (on EVM chains) a zero-value transfer that looks
like it came from you. The next time you open "recent" and copy the top address, it is theirs.</p>
<p>It costs the attacker almost nothing. A Carnegie Mellon study counted about 270 million poisoning attempts on
Ethereum and BNB Chain between July 2022 and June 2024, aimed at 17 million wallets, with more than $83 million in
confirmed losses. Blockaid says it flagged over 65 million poisoning transactions in 2025 alone, and Solana has its
own automated tools for it.</p>

{bars("Single address poisoning losses", [
    ("Wallet 0xcB80 (Dec 2025)", 50_000_000, "sent 50M USDT after a 50 USDT test transfer"),
    ("Address linked to sillytuna", 24_000_000, "aEthUSDC drained"),
    ("Bofur Capital", 2_000_000, "copied a spoofed address after a Compound withdrawal"),
    ("Unnamed wallet (28 Oct 2026)", 50_059, "same first 4 and last 6 characters"),
    ("Solana wallet (Nov 2025)", 30_750, "lookalike address got dust 12 seconds after a test payment"),
], sub="US dollars lost in one transfer", fmt="usd", hl=(0,),
   source="lookonchain, PeckShield, Scam Sniffer, CryptoSlate (each case as they reported it)")}

<h2>The part most people miss: the test transfer</h2>
<p>A test transfer feels safe. In the biggest cases it was the trigger. The victim sends 50 USDT to their own
address, a bot sees it on-chain, and within seconds a lookalike address sends dust to the same wallet. The victim
then goes back to history to copy "the address that worked" and picks the fake one. The test does not protect you;
<b>where you copy the address from</b> does.</p>

<h2>The routine, step by step</h2>
<ol>
<li><b>Save every address you send to more than once.</b> Phantom: Settings, Address Book, Add address. MetaMask:
Settings, Contacts. Give it a name you would recognise ("Binance deposit SOL"). From then on, send by picking the
name, never by pasting.</li>
<li><b>Never copy an address from transaction history.</b> Not in the wallet, not on Solscan or Etherscan. Copy it
from the source: the exchange deposit page, your own wallet's "Receive" screen, or the address book.</li>
<li><b>Check the middle, not the ends.</b> Attackers match the first and last characters because those are what you
see. Compare 4 characters from the middle of the address against the source. It takes five seconds.</li>
<li><b>After a test transfer, do not go back to history.</b> Send the main amount from the same source you used for
the test (address book or the exchange page), not from "recent".</li>
<li><b>Hide spam in your explorer.</b> On Solscan, turn on "Hide spam" and "Hide low value" in the activity table.
Zero-value transfers and dust you never asked for are the warning sign that you are being targeted.</li>
<li><b>Use whitelisting on exchanges.</b> Most large exchanges let you lock withdrawals to saved addresses only, with
a waiting period for new ones. Turn it on before you need it.</li>
</ol>

<h2>If you already sent to the wrong address</h2>
<p>A blockchain transfer cannot be reversed. What still helps: post the transaction hash and the attacker address
quickly, report it to the exchange the funds move to (exchanges can freeze deposits if they are told in time), and
file a police report, which exchanges often ask for. Large thefts have been partly frozen this way, small ones
rarely are, which is why the routine above matters more than the recovery.</p>
<p>Related: <a href=/blog/zero-trust-support-calls>the fake support call script</a> and
<a href=/blog/how-to-spot-a-rug-pull>how to spot a rug pull</a>.</p>
""", related=("zero-trust-support-calls", "how-to-spot-a-rug-pull", "how-to-buy-solana-meme-coins"), date=D)


# 2 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "zero-trust-support-calls", "Scams",
    "\"Ledger support is calling\": a 5-question check that stops fake support scams",
    "Fake Ledger and exchange support scams: how to check a call in 5 questions | MemeSonar",
    "The largest crypto thefts lately were not hacks but people pretending to be support. Five questions to ask "
    "before you do anything a 'support agent' asks.",
    ["ledger support scam", "fake crypto support", "crypto social engineering", "seed phrase scam"], 6,
    "Real wallet and exchange support never calls you first, never asks for your seed phrase and never asks you to "
    "move funds to a 'safe' wallet. If any of those happen, hang up and contact support yourself through the app or "
    "the address you type in by hand.",
    f"""
<h2>Why this is the attack that works now</h2>
<p>Smart contract hacks get the headlines, but many of the largest personal losses in the past two years came from
one phone call. On-chain investigator ZachXBT has traced several of them. The pattern repeats: someone calls or
messages as "Ledger support", "Coinbase security" or "Trezor", says your account or device is compromised, and walks
you through "protecting" your funds, straight into their wallet.</p>

{bars("Losses from fake support (social engineering) cases", [
    ("Hardware wallet scam, Jan 2026", 282_000_000, "LTC and BTC, converted to Monero within hours"),
    ("Genesis creditor, Aug 2024", 243_000_000, "the same group was linked to other thefts"),
    ("Exchange and wallet support impersonated, Aug 2025", 91_000_000, "783 BTC"),
    ("One US threat actor, several victims", 19_000_000, "total traced to a single person"),
], sub="US dollars, as reported at the time", fmt="usd", hl=(0,), source="ZachXBT investigations on X")}

<p>The theft is technically simple. Your keys are safe until you hand them over, type the seed phrase into a
"verification" page, install "security software", or approve a transfer yourself. That is why the defence is a
script, not a tool.</p>

<h2>The 5 questions</h2>
<ol>
<li><b>Did I contact them first?</b> If not, stop. Ledger says plainly that it never calls, never DMs and never asks
for your 24 words. Exchanges work the same way. An incoming call, SMS or DM is the scam until proven otherwise.</li>
<li><b>Are they asking for the seed phrase, a private key or a "verification" of my words?</b> There is no legitimate
reason. The seed phrase is only ever typed on the device itself when you set it up or recover it.</li>
<li><b>Are they asking me to move funds to a new "safe" or "vault" address?</b> This is the most common ending of the
script. Real support cannot and does not move your crypto.</li>
<li><b>Are they asking me to install something or share my screen?</b> Remote access tools give them your computer.
Say no.</li>
<li><b>Is there a deadline?</b> "Your funds will be lost in 30 minutes" is pressure, not security. Real problems wait
for you to log in yourself.</li>
</ol>
<p>One "yes" is enough. Hang up, then open the official app or type the support address by hand (not a link from the
message) and ask there.</p>

<h2>How they find you</h2>
<ul>
<li><b>Public support posts.</b> Ask a question to an official support account on X, and fake "support" DMs you within
minutes. Use the ticket system in the app instead.</li>
<li><b>Leaked customer data.</b> Old exchange and wallet shop leaks include names, phone numbers and home addresses,
which is why the caller already knows your name.</li>
<li><b>Paper letters and emails.</b> Ledger has confirmed scam letters sent by post asking customers to "upgrade
security" with their seed phrase.</li>
</ul>

<h2>If you already typed the seed phrase somewhere</h2>
<p>Treat the wallet as gone. Set up a new wallet with a new seed on a device you trust and move everything that is
still there right away, starting with the largest balance. Do not reuse the old seed for anything.</p>
<p>Related: <a href=/blog/address-poisoning>address poisoning</a> and
<a href=/blog/how-to-buy-solana-meme-coins>how to buy meme coins safely</a>.</p>
""", related=("address-poisoning", "how-to-buy-solana-meme-coins", "best-crypto-exchanges-croatia"), date=D)


# 3 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "polymarket-rules-checklist", "Prediction markets",
    "How to read Polymarket rules before you bet: a 6-point checklist",
    "How Polymarket markets resolve: rules, UMA disputes and a checklist | MemeSonar",
    "On Polymarket you can predict the event correctly and still lose, because markets resolve on the written "
    "rules. A 6-point checklist and how UMA disputes work.",
    ["polymarket rules", "how polymarket resolves", "uma dispute polymarket", "prediction market resolution"], 7,
    "A Polymarket market pays out according to its written rules and resolution source, not according to what most "
    "people think happened. Before you buy, read the end date and time zone, the exact wording, the resolution source "
    "and what happens in edge cases, and know that a disputed market can take two days or more to pay out.",
    f"""
<h2>Why people lose when they were right</h2>
<p>Every Polymarket market has a "Rules" box under the chart. That text, not the headline, decides who gets paid.
Experienced traders such as Domer, who has traded on the site since 2021, have written long threads about markets
that resolved against the obvious reality because of a single word, a missed time zone or a resolution source that
said something different. Kalshi has had the same fights, for example ruling in a "mention" market that
saying "Alexis de Tocqueville" counted as a mention of the company John Deere.</p>

<h2>How resolution works</h2>
<p>Polymarket uses UMA's Optimistic Oracle. Anyone can propose the outcome by posting a bond (usually $750 in
USDC). If nobody disputes it within the challenge window, the market resolves. If someone disputes it, a new
proposal is made, and a second dispute sends the question to a vote of UMA token holders.</p>

{bars("Minimum time until a market pays out", [
    ("No dispute", 2, "the 2-hour challenge window passes"),
    ("Disputed once, new proposal accepted", 4, "a second 2-hour window"),
    ("Disputed twice, goes to UMA vote", 52, "about 48 hours of voting on top"),
], sub="Hours after the first proposal (minimum, can be longer)", fmt="num", hl=(2,),
   source="Polymarket and UMA documentation")}

<p>The vote is where the criticism is. Reporting has shown that a small number of large UMA holders decide many
disputes and that a large share of active voters also trade on Polymarket. In 2025 UMA limited proposals to
whitelisted accounts to cut the number of bad proposals. None of this changes the practical rule: if a market can be
argued, assume it will be.</p>

<h2>The checklist before you buy</h2>
<ol>
<li><b>End date and time zone.</b> "By December 31" means a specific time in a specific zone, written in the rules.
Events that happen a few hours "late" in your time zone can resolve No.</li>
<li><b>Exact wording.</b> "Announces", "signs", "takes office" and "is confirmed" are different events. Copy the key
verb from the rules and ask: what if only half of it happens?</li>
<li><b>Resolution source.</b> Many markets name one source (an official website, a specific outlet). If that source
is slow, vague or can change its page, that is your risk.</li>
<li><b>Edge cases written in the rules.</b> Look for what happens if the event is postponed, cancelled or ambiguous.
If the rules are silent, the result depends on the vote.</li>
<li><b>Clarifications.</b> Polymarket sometimes adds clarifications after a market opens. Check the comments and
"additional context" before a big position, and again before the end date.</li>
<li><b>Price of the "obvious" side.</b> If the obvious outcome trades at 85 cents instead of 99, someone is pricing in
a rules problem. Find out what they see before you buy the cheap certainty.</li>
</ol>

<h2>When to skip a market</h2>
<p>Skip it if the outcome depends on interpreting words someone says (mention markets), if the resolution source is
a person's social media account, or if the rules were changed after the market opened. These are the markets where
traders have lost money while being right about the world.</p>
<p>Next: <a href=/blog/polymarket-insider-moves>how to spot an information leak in Polymarket odds</a>.</p>
""", related=("polymarket-insider-moves", "how-to-trade-meme-coins", "what-is-a-pump-and-dump"), date=D)


# 4 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "polymarket-insider-moves", "Prediction markets",
    "How to spot an information leak on Polymarket: when the odds move before the news",
    "Polymarket insider trading: how to spot odds moving before the news | MemeSonar",
    "Odds on Polymarket have jumped hours before official news several times, from the Nobel Peace Prize to "
    "Venezuela. What those moves looked like and how to watch for them yourself.",
    ["polymarket insider trading", "polymarket odds", "prediction market leak", "polymarket whale tracking"], 6,
    "A leak on a prediction market looks like a sharp jump in the odds of an unlikely outcome with no public news, "
    "driven by one or a few new accounts with large bets. You can watch for it with the market's activity tab and a "
    "wallet explorer, but treat it as a signal to investigate, not a reason to follow blindly.",
    f"""
<h2>The cases that made this a topic</h2>
<p><b>Nobel Peace Prize, October 2025.</b> María Corina Machado's odds on Polymarket rose from a few percent to above
70% in the hours before the announcement in Oslo. Reporting by Bloomberg and others traced much of the buying to a
few accounts, including one created that month with no earlier bets. Norwegian officials opened an inquiry into a
possible leak.</p>
<p><b>Venezuela, January 2026.</b> Markets on Nicolás Maduro leaving power moved before the public announcement that
he was in US custody, and one account reportedly made several hundred thousand dollars.</p>
<p>Prediction market trader Domer documented more cases on X, including a market where the price started climbing
about 12 hours before a military strike, and analyst Alex Krüger pointed to a spike in the odds of a Fed chair
nomination the day before the announcement.</p>

{bars("Machado's odds of winning the Nobel Peace Prize on Polymarket", [
    ("Before the overnight buying", 3.6, "the day before the announcement"),
    ("Hours before the announcement", 70, "after a few accounts bought heavily"),
], sub="Implied probability, %", fmt="pct", hl=(1,), source="Bloomberg, The Block, Decrypt (October 2025)")}

<h2>What a leak looks like on the screen</h2>
<ol>
<li><b>An unlikely outcome moves fast with no news.</b> A jump from single digits to 30%+ within hours, while news
sites and X have nothing new.</li>
<li><b>The buying comes from few accounts.</b> Open the market's activity or "top holders" tab. Leaks are usually a
handful of large buys, not hundreds of small ones.</li>
<li><b>The accounts are new or single-purpose.</b> A wallet created days ago that only ever bet on this market is the
classic pattern. Check the wallet on Polygonscan: when was it funded and from where?</li>
<li><b>Timing fits a decision that is already made.</b> Prize committees, court rulings and military operations are
decided before they are announced. That gap is where leaks happen.</li>
</ol>

<h2>What to do with it</h2>
<p>A move like this is information, but not proof. Sometimes the "insider" is a fan with a big wallet, as with a
Polymarket user who kept buying a celebrity outcome against all odds. Before you follow a move, ask what decision is
already made, who could know, and how much is left to win if you buy at the new price. Buying at 70 cents to win 30
is a very different bet from the insider's 4 cents.</p>
<p>The same signal is useful in the other direction. MemeSonar's event calendar reads Polymarket because large money
moving on an event often comes before tokens named after that event start to move. A sudden odds shift on an event
in the calendar is a reason to look at those tokens, and at <a href=/blog/how-to-spot-a-rug-pull>their rug risk</a>,
before the crowd does.</p>
<p>Also read: <a href=/blog/polymarket-rules-checklist>how to read Polymarket rules before you bet</a>.</p>
""", related=("polymarket-rules-checklist", "influencer-clustering", "what-is-wallet-tracking"), date=D)


# 5 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "perps-settings-after-october-10", "Trading",
    "5 perps settings that would have saved you on October 10",
    "Crypto perps risk settings: isolated margin, ADL and the October 10 crash | MemeSonar",
    "On 10 October 2025 about $19 billion of crypto positions were liquidated in a day. Five settings that decide "
    "whether a crash like that takes your trade or your whole account.",
    ["auto deleveraging", "isolated margin vs cross margin", "crypto liquidation", "hyperliquid adl"], 7,
    "Use isolated margin for every leveraged trade, size so that your liquidation price is far beyond any recent wick, "
    "keep collateral off the exchange you trade on, understand that auto-deleveraging can close even a winning position, "
    "and do not open new leverage after a big loss. These five rules decided who survived 10 October 2025.",
    f"""
<h2>What happened on 10 October</h2>
<p>A tariff headline hit a market full of leverage. Order books thinned out, market makers pulled liquidity, some
exchange APIs stopped working, and liquidations fed more liquidations. Most trackers counted around $19 billion of
liquidated positions in about a day, the largest on record, and more than a million accounts were hit. About half
of it happened on Hyperliquid.</p>

{bars("Liquidations on 10–11 October 2025", [
    ("All exchanges", 19.3, "the largest liquidation day on record"),
    ("Hyperliquid", 10, "about half of the total"),
    ("Binance", 2.4, "the largest centralised exchange"),
], sub="Billions of US dollars (estimates differ by source and time window)", fmt="num", hl=(0,),
   source="Kobeissi Letter, CoinGlass-based reporting, Sentora")}

<p>Experienced traders lost too. The White Whale, a well-known trader, wrote a public debrief after losing about $62
million that day. Unipcs wrote about the biggest one-day loss of their career "due to systemic failures on the biggest
exchanges." Their posts, and trader Cred's list of what not to do after a big move, are the basis of this list.</p>

<h2>1. Isolated margin, always</h2>
<p>In cross margin, your whole account backs every position, so one bad trade can drain the rest. In isolated
margin, only the margin you put into that trade can be lost. On 10 October, accounts in cross margin lost positions
they had not even been watching.</p>

<h2>2. Put the liquidation price beyond the worst wick, not the chart</h2>
<p>ETH dropped more than $1,000 in minutes on some venues. Before you open a trade, look at the liquidation price the
exchange shows and compare it with the biggest wick of the past year, not with your stop. If a repeat of that wick
would liquidate you, lower the leverage until it would not.</p>

<h2>3. Know what auto-deleveraging (ADL) is</h2>
<p>When a liquidated account goes below zero and the exchange cannot close it in the market, it closes positions on
the winning side instead. On Hyperliquid, winners are ranked by (mark price / entry price) times (position size /
account value), so the most profitable, most leveraged positions go first, at the previous mark price. On 10
October, tens of thousands of accounts on Hyperliquid, Binance and Bybit had profitable positions closed this way,
some of them hedges, which left the other leg open. If you hedge with perps, check the ADL indicator on your position and take profit on
hedges in a crash instead of assuming they will stay open.</p>

<h2>4. Do not keep all your collateral on the exchange you trade on</h2>
<p>When APIs and withdrawals stall, you cannot add margin or move funds. Keep only the margin you need on the
exchange and the rest in your own wallet, so a frozen exchange cannot take everything.</p>

<h2>5. No new leverage for 24 hours after a big loss</h2>
<p>Cred's list of the worst impulses after a big move: revenge short, oversized buy, and trying to make it all back
the same day. Unipcs wrote the same after the crash: shut it down, step away, do not open new leverage. Write the
rule down before you need it.</p>
<p>Meme coins have no perps for most of their life, but the same rules apply to size: see
<a href=/blog/how-to-trade-meme-coins>how to trade meme coins</a> and
<a href=/blog/what-is-dca-in-crypto>DCA</a>.</p>
""", related=("how-to-trade-meme-coins", "what-is-dca-in-crypto", "market-cap-liquidity-slippage"), date=D)


# 6 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "tokens-sent-to-kol-wallets", "Copy trading",
    "Why a random token showed up in a famous trader's wallet (and why copy traders buy it)",
    "Unsolicited tokens in KOL wallets: the trick that fools copy traders | MemeSonar",
    "Token teams send their coins to famous traders' wallets so it looks like a buy. Copy trading bots and "
    "followers then buy for real. How to tell a gift from a purchase in 30 seconds.",
    ["copy trading scam", "kol wallet", "unsolicited token solana", "fake buy copy trading"], 5,
    "Many tokens in well-known traders' wallets were never bought: the token team sent them for free so it looks like "
    "the trader is in. Copy trading bots and followers see the new token and buy for real. Before you copy, check that "
    "SOL left the wallet in the same transaction; a plain token transfer in is a gift, not a buy.",
    f"""
<h2>The trick</h2>
<p>Solana trader Unipcs, one of the most copied wallets on the trading app Fomo, wrote that around 90% of the tokens
that land in their public wallet were sent by other people, not bought. In their words, people send them "to
capitalize on my copytraders and/or the optics of: 'Unipcs bought this'." Some of those gifts were fine tokens, but
the overwhelming majority came "from people with nefarious intentions."</p>

{bars("Where the tokens in one famous trader's wallet came from", [
    ("Sent for free by others", 90, "the trader's own estimate"),
    ("Bought by the trader", 10, ""),
], sub="Share of tokens received, %", fmt="pct", hl=(0,), source="Unipcs on X (estimate for their public Fomo wallet)")}

<p>The playbook is cheap. The team sends a small slice of supply to several famous wallets. Portfolio trackers and
"what is smart money holding" lists show the token. Copy trading bots that follow balances rather than swaps buy it,
followers see the name in the wallet and buy too, and the team sells into that demand.</p>

<h2>How to check in 30 seconds</h2>
<ol>
<li><b>Open the wallet on Solscan and find the first transaction with that token.</b></li>
<li><b>Look at what left the wallet in the same transaction.</b> A real buy is a swap: SOL or USDC goes out, the
token comes in, usually through Jupiter, Raydium, pump.fun or another DEX. A gift is a plain "transfer" with only
the token coming in.</li>
<li><b>Check who sent it.</b> If the sender is the token's creator or a wallet funded by the creator, it is
marketing, not conviction.</li>
<li><b>Check if the famous wallet ever sold.</b> Many simply never touch gifted tokens, so "still holding" means
nothing.</li>
</ol>

<h2>What this means for copy trading</h2>
<p>A copy trading setup should follow <b>swaps the wallet paid for</b>, never balance changes. That is how MemeSonar's
<a href=/blog/what-is-wallet-tracking>wallet tracker</a> counts trades: a position only exists if SOL left the
wallet for it. Gifted tokens never enter the score, so they cannot trigger a copy. If you use another bot, check
its settings for "copy transfers" or "copy on balance change" and turn it off.</p>
<p>Also check the token itself before buying anything you saw in a wallet:
<a href=/blog/bundles-and-snipers>who really owns the supply</a> and
<a href=/blog/how-to-spot-a-rug-pull>the 7 rug checks</a>.</p>
""", related=("what-is-copy-trading", "what-is-wallet-tracking", "bundles-and-snipers"), date=D)


# 7 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "what-to-do-with-an-airdrop", "Airdrops",
    "What to do with an airdrop in the first 24 hours: sell, hold or hedge",
    "Sell or hold an airdrop? What the data says about the first 24 hours | MemeSonar",
    "Most airdropped tokens trade below their launch price within months, and most recipients sell on day one. A "
    "simple rule for the first 24 hours, plus how to spot a fake claim page.",
    ["sell airdrop or hold", "airdrop claim", "airdrop strategy", "token generation event"], 6,
    "Studies of 2025 token launches found that about 85% of tokens traded below their launch price and that most "
    "airdrop wallets sold within 90 days. Unless you have a specific reason to hold, sell at least the part you would "
    "regret losing on day one, and only claim through a link you found yourself on the project's official channels.",
    f"""
<h2>What happened to airdrops in 2025</h2>
{bars("Airdrops and token launches in 2025", [
    ("Tokens below launch price (Arrakis, 125 launches)", 85, "measured at the end of 2025"),
    ("Tokens below TGE valuation (Memento, 118 launches)", 84.7, ""),
    ("Airdrop wallets that sold within 90 days (Delphi, upper end)", 94, "lower end of the range: 78%"),
    ("Recipients who sold on day one (Arrakis, upper end)", 80, ""),
    ("ZKsync recipients who sold everything on day one (Nansen)", 41, ""),
], sub="% (each figure from the named study)", fmt="pct", hl=(0,),
   source="Arrakis, Memento Research, Delphi Digital, Nansen, via The Defiant and BeInCrypto")}
<p>Airdrop researcher Stacy Muur summed up the year on X: selling airdrops immediately was the best strategy,
shorting them worked but liquidations were common even at low leverage, and everyone grinds, including teams and VCs.
DeFi Ignas described the same playbook: claim and sell first, buy back later once the airdrop selling stops.</p>

<h2>A rule for the first 24 hours</h2>
<ol>
<li><b>Decide before the claim opens.</b> Write down how much you will sell at claim and why you would hold the rest.
"I like the project" is not a reason; "I use it daily and the team has a reason to keep the price up" can be.</li>
<li><b>Sell at least your "regret amount" on day one.</b> The amount you would be upset to watch fall 80%. For most
people that is half or more.</li>
<li><b>Check the unlock schedule.</b> If team and investor tokens unlock within 30–90 days, that is selling pressure
coming. Haseeb Qureshi (Dragonfly) has argued airdrops should reward holders, and some projects now do (Espresso used
"holder scores"), but most still do not.</li>
<li><b>Hedging is for experienced traders only.</b> Shorting a fresh token on a perp exchange can lock in the price,
but new listings are thin and spike easily. If you do it, use isolated margin and low leverage, as in
<a href=/blog/perps-settings-after-october-10>these perps settings</a>.</li>
<li><b>Watch the first hours, not the first minute.</b> Prices often swing wildly while liquidity settles. Selling in
two or three parts over the first day avoids selling the exact low.</li>
</ol>

<h2>Do not lose it on the claim page</h2>
<p>The day of a big airdrop is the best day of the year for drainers. Fake claim tokens are sent to wallets (for
example fake "$CJUP" tokens pretending to be a Jupiter airdrop), and fake claim sites are advertised in replies and
search ads. Only claim from a link on the project's official site or verified X account, typed or bookmarked by you,
and read what you sign: a claim should never ask you to approve spending of your other tokens.</p>
<p>Related: <a href=/blog/address-poisoning>address poisoning</a> and
<a href=/blog/zero-trust-support-calls>fake support scams</a>.</p>
""", related=("perps-settings-after-october-10", "address-poisoning", "what-is-a-pump-and-dump"), date=D)


# 8 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "fake-volume-check", "Rug pulls",
    "How to check if trading volume is fake (on a DEX or an exchange)",
    "Fake crypto volume: how to spot wash trading in 3 checks | MemeSonar",
    "High volume makes a token look alive, and a lot of it is fake. Three checks anyone can run: volume vs "
    "liquidity, volume that copies another exchange, and walls that flicker.",
    ["fake volume crypto", "wash trading crypto", "volume to liquidity ratio", "spoofing crypto"], 6,
    "Wash trading inflates volume so a token looks popular. Compare 24-hour volume with liquidity (dozens of times "
    "more volume than liquidity is a red flag), check whether the volume just mirrors another exchange, and watch for "
    "large orders that appear and disappear. None is proof alone; two together usually are.",
    f"""
<h2>How common it is</h2>
<p>Wash trading means trading with yourself (or a friendly wallet) to create volume. On DEXs it is cheap, and it
works: trending lists, screeners and bots rank by volume. Studies keep finding a lot of it.</p>
{bars("Wash trading in research", [
    ("DEX pools manipulated by wash traders (Solidus Labs)", 67, "sample of about 30,000 pools"),
    ("Volume faked on unregulated exchanges (Cong et al.)", 70, "upper estimate"),
    ("Share of volume that was wash trading in those pools (Solidus)", 16, "a lower bound"),
], sub="%", fmt="pct", hl=(0,), source="Solidus Labs; Cong et al., cited in Victor and Weintraud (2021)")}

<h2>Check 1: volume against liquidity</h2>
<p>On DexScreener or Birdeye, divide 24-hour volume by the pool's liquidity. Real trading rarely turns a pool over
dozens of times a day for long; data firm Kaiko flags assets with volume above 100 times their order book depth as a
possible sign of wash trading. Memes and low caps naturally run hot, so use it as a filter: very high ratio plus few
unique traders is the pattern.</p>
<p>MemeSonar uses this check in its token score: a token whose volume is many times its liquidity gets a penalty,
so it does not rank as "hot" just because a bot trades it back and forth.</p>

<h2>Check 2: volume that copies another exchange</h2>
<p>DefiLlama's 0xngmi showed that volume on one perp exchange started to mirror Binance perp volume almost exactly,
with a ratio close to 1, while other exchanges looked nothing like it. Real users do not trade in perfect sync with
another venue. Compare the hourly volume chart of a pair on two exchanges; if one is a near copy of the other, it is
probably being farmed, often for points or a listing.</p>

<h2>Check 3: walls that flicker (spoofing)</h2>
<p>On centralised exchanges, watch the order book. Trader The White Whale described a sell order of about $200,000
on Bybit spot that kept flipping in and out of view, the classic sign of spoofing: an order placed to scare buyers
and pulled before it can be filled. Large walls that move away as price approaches are not real supply.</p>

<h2>Quick on-chain signs</h2>
<ul>
<li><b>Few wallets, many trades.</b> Hundreds of trades from a dozen wallets.</li>
<li><b>Balanced buys and sells.</b> The same wallets buy and sell almost the same amount; research flags differences
under 5% between linked wallets.</li>
<li><b>Round-trip funding.</b> Trading wallets funded from the same source, often the deployer.</li>
</ul>
<p>More on reading a token before buying: <a href=/blog/market-cap-liquidity-slippage>market cap, liquidity and
slippage</a> and <a href=/blog/what-is-a-pump-and-dump>pump and dumps</a>.</p>
""", related=("market-cap-liquidity-slippage", "what-is-a-pump-and-dump", "how-to-spot-a-rug-pull"), date=D)


# 9 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "after-kaito-yaps", "For crypto projects",
    "Kaito Yaps is gone: what crypto projects should do for X visibility now",
    "After Kaito Yaps: how crypto projects get visibility on X in 2026 | MemeSonar",
    "X cut off apps that pay people to post in January 2026 and Kaito shut Yaps down. What went wrong with paid "
    "mindshare and a checklist for any paid X campaign now.",
    ["kaito yaps", "infofi", "crypto marketing x", "crypto kol campaign"], 6,
    "In January 2026 X revoked API access for apps that reward posting, and Kaito ended Yaps and its incentivised "
    "leaderboards. The lesson for projects: paid mindshare produced interactions without real reach. Measure "
    "impressions per interaction, pay a few creators for defined work instead of everyone for volume, and disclose it.",
    f"""
<h2>What happened</h2>
<p>Kaito's Yaps paid crypto accounts in "mindshare" for posting about projects on leaderboards. Projects paid to be
on those boards. On 16 January 2026, after X restricted apps that reward posting (citing spam and low-quality
engagement), Kaito founder Yu Hu announced Yaps and the incentivised leaderboards would be wound down, replaced by
Kaito Studio, a curated marketplace where brands work with selected creators. Cookie DAO shut its similar "Snaps"
programme. The KAITO token fell about 15% on the news.</p>

{bars("KAITO price around the announcement", [
    ("Before", 0.70, ""),
    ("After", 0.57, "about -15%"),
], sub="US dollars", fmt="usd2", hl=(1,), source="CoinGape, January 2026")}

<h2>What went wrong with paid mindshare</h2>
<ul>
<li><b>Interactions without reach.</b> Crypto writer Olimpio noticed his airdrop post got dozens of interactions but
few impressions, and found the token had an active InfoFi campaign: accounts were engaging to farm rewards, not
because anyone was reading.</li>
<li><b>Grind replaced value.</b> Stacy Muur wrote that KOLs kept asking her to engage with their leaderboard posts,
and that grinding too hard loses sight of the actual value. Even guides on winning boards recommended 50 to 300
replies a day.</li>
<li><b>Trust cost.</b> The White Whale called paid KOL culture "an absolute cancer": paying for manufactured
consensus instead of earning attention. Audiences learned to discount it.</li>
</ul>

<h2>A checklist for any paid X campaign now</h2>
<ol>
<li><b>Measure impressions per interaction.</b> Ask creators for screenshots of post analytics. As a rule of thumb,
posts people actually read get dozens or hundreds of impressions per interaction; ten or fewer points to engagement
rings, not readers.</li>
<li><b>Check who replies.</b> Open the replies of a creator's last three paid posts. Generic praise from accounts
that reply to every campaign is farming.</li>
<li><b>Pay for defined work, not volume.</b> One thread that explains how your product works, a video demo, or a
data post. Kaito Studio moved to the same model: selected creators, defined scopes.</li>
<li><b>Prefer a few creators your users already read.</b> Ask your existing users who they follow. Three of those
beat thirty leaderboard accounts.</li>
<li><b>Disclose.</b> Paid posts should say so. It protects the creator and the project, and undisclosed promotion is
exactly what audiences now punish.</li>
<li><b>Track what matters after the post.</b> New wallets using the product, not likes. Put a unique link or code in
each creator's post.</li>
</ol>
<p>How influencer calls move tokens, measured: <a href=/blog/what-is-a-kol-in-crypto>what a KOL is</a> and
<a href=/blog/why-big-influencer-calls-are-hard-to-trade>why big calls are hard to trade</a>.</p>
""", related=("what-is-a-kol-in-crypto", "why-big-influencer-calls-are-hard-to-trade", "fair-token-launch-cca"), date=D)


# 10 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "fair-token-launch-cca", "For crypto projects",
    "How to launch a token without snipers: Uniswap's CCA auction step by step",
    "Fair token launch without snipers: Uniswap CCA auction guide | MemeSonar",
    "A Continuous Clearing Auction sells tokens block by block at one clearing price, so snipers and bundlers lose "
    "their edge. How to set one up, and how to bid as a buyer.",
    ["fair token launch", "uniswap cca", "continuous clearing auction", "token launch without snipers"], 7,
    "Uniswap's Continuous Clearing Auction (CCA) spreads a token sale over many blocks. Each bid is split across the "
    "remaining blocks and fills at that block's clearing price, so being first gives no advantage. Founders set the "
    "supply, floor price, duration and pool share; buyers should bid early at their true maximum price.",
    f"""
<h2>The problem it solves</h2>
<p>On a classic launch, whoever is fastest gets the cheapest tokens. That is why <a href=/blog/bundles-and-snipers>bundlers
and snipers</a> own a big part of new supply within seconds, and why on-chain sleuths like Bubblemaps keep finding
insiders in "presidential" and celebrity coins. The team loses control of who holds the token, and buyers pay the
snipers' exit.</p>

<h2>How a CCA works</h2>
<p>The team puts a part of supply into an auction that runs over a set period. A buyer enters a budget and a maximum
price. The bid is spread evenly across all remaining blocks. In each block, the auction finds one clearing price
from all active bids, and every bid at or above it fills at that same price. Price can only go up as demand comes in.
At the end, if the auction reaches its minimum raise, the final clearing price becomes the starting price of a
Uniswap v4 pool funded with part of the proceeds.</p>

<h2>The first big test: Aztec</h2>
{bars("Aztec's CCA token sale", [
    ("Clearing price above the floor", 60, "Hayden Adams said 59%"),
    ("Bidders who put in under $10,000", 96, "about 17,000 bidders from 191 countries"),
], sub="%", fmt="pct", hl=(1,), source="Uniswap Labs blog, February 2026")}
{stats([("$59M", "total bids in Aztec's auction"), ("~17,000", "bidders"), ("0", "clear sniping cases found on-chain, per Uniswap")])}
<p>Uniswap founder Hayden Adams summed it up as "no sniping, bundling, timing games, just slow, fair price
discovery", and noted that even a bid at a huge valuation on day one would not have overpaid, because it fills at
the clearing price. The numbers come from Uniswap's own reporting, so read them as the organiser's view.</p>

<h2>Setting one up (for founders)</h2>
<ol>
<li><b>Supply in the auction.</b> Decide what share of the total goes to the public. Less than you think looks
greedy; more than you need leaves no room for incentives.</li>
<li><b>Floor price.</b> The minimum price per token. Uniswap's docs warn that an excessively high floor can make the
auction fail and lose funds, so set it at a valuation you would accept as the worst case.</li>
<li><b>Duration and curve.</b> Days, not minutes. You can sell fewer tokens early and more later with a custom curve.</li>
<li><b>Early bid period.</b> Optional window for past contributors or community before the public auction (Aztec used
one).</li>
<li><b>Pool share and LP settings.</b> The part of raised funds and tokens that seeds the Uniswap v4 pool at the
clearing price, so trading starts with real liquidity.</li>
<li><b>Validation.</b> Optional checks such as proof of personhood (zkPassport) to limit sybil bidders.</li>
</ol>

<h2>Bidding (for buyers)</h2>
<p>Bid early at the highest price you would really pay. Waiting does not get you a better price: your budget is
spread over fewer blocks, and the price only rises as others bid. Bidding at your true maximum just means you fill
in more blocks, always at the clearing price, never at your maximum.</p>
<p>Related: <a href=/blog/what-is-pump-fun>how pump.fun launches work</a> and
<a href=/blog/after-kaito-yaps>X marketing after Kaito Yaps</a>.</p>
""", related=("bundles-and-snipers", "what-is-pump-fun", "after-kaito-yaps"), date=D)
