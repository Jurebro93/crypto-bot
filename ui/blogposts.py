"""The ten launch posts of the public blog (English). Numbers come from MemeSonar's own data:

- RETRO: retrospective of 10,650 pump.fun tokens (October 2026), features at 15 min after launch, at graduation and at
  the first $100k / $1M market-cap cross; "2x" = the price later reached at least double the price at that point.
- WALLETS: snapshot of the wallet tracker on 30 Oct 2026 (469 wallets, 50 with 10+ closed trades).
- KOL: influencer calls measured by the app (price 1 h / 24 h after each call, bots excluded).
Keep numbers here in sync with the text; each post states its sample and date.
"""
from ui import calcs as CALC
from ui.blogviz import bars, grid, stats

RETRO = "MemeSonar retrospective of 10,650 pump.fun tokens, October 2026"
WALLETS = "MemeSonar wallet tracker, snapshot of 30 October 2026"
KOL = "MemeSonar influencer call measurements, October 2026"

POSTS = []


def post(slug, tag, h1, title, desc, kw, mins, tldr, body, related=(), date="2026-11-01"):
    POSTS.append(dict(slug=slug, tag=tag, h1=h1, title=title, desc=desc, kw=kw, mins=mins, tldr=tldr, body=body,
                      related=related, date=date))


# 1 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "what-is-wallet-tracking", "Wallet tracking",
    "What is wallet tracking? How to track Solana wallets (and why most 'smart money' isn't)",
    "What is wallet tracking? A Solana wallet tracker guide with real data | MemeSonar",
    "Wallet tracking means following what specific Solana wallets buy and sell. We tracked 469 wallets: only 11 of "
    "50 active ones made money. Here is how to find the few worth following.",
    ["wallet tracker", "solana wallet tracker", "smart money tracker", "how to track crypto wallets"], 7,
    "Wallet tracking means watching the buys and sells of specific blockchain addresses so you can learn from (or "
    "copy) traders who are consistently early. It works only if you filter hard: of 469 Solana wallets we tracked, "
    "50 traded enough to judge, 11 were profitable and just 2 were worth copying.",
    f"""
<h2>What wallet tracking is</h2>
<p>Every trade on Solana is public. A wallet address is like an account number that anyone can look up: which
tokens it bought, when, for how much SOL, and when it sold. A <b>wallet tracker</b> watches a list of addresses and
tells you, in seconds, when one of them trades.</p>
<p>The idea is simple. Some traders are consistently early on tokens that go on to pump. If you can see their buys
as they happen, you can learn from them, or follow them with a small amount. People call these addresses
<b>smart money</b>.</p>

<h2>The problem: most "smart money" isn't smart</h2>
<p>Lists of "smart wallets" are everywhere on crypto X and Telegram. We collected 469 of them from public sources
(KOL wallet lists, early buyers of tokens that pumped, wallets shared in channels) and measured every trade. This is
what was left after each step:</p>
{bars("From 469 'smart' wallets to 2 worth copying", [
    ("Wallets collected", 469, "public lists, early buyers of winners, shared in channels"),
    ("With enough history to score", 293, "we could reconstruct their trades"),
    ("10+ closed trades", 50, "enough trades to judge skill, not luck"),
    ("Profitable after all trades", 11, "realised profit above zero"),
    ("Worth copying", 2, "profitable, not a bot, sniper or insider, holds long enough to follow"),
], sub="Number of wallets left after each filter", fmt="num", hl=(4,), source=WALLETS)}
<p>Only 22% of active wallets were in profit. The typical active wallet won 31% of its trades, held a position for
<b>under 4 minutes</b> and made about 100 trades a day. That is a bot or a sniper, not someone you can follow by
hand: by the time you see the buy, they have already sold.</p>

<h2>Labels that should make you stop</h2>
<p>A good tracker labels wallets before you follow them. In our list, 124 wallets carried at least one warning
label:</p>
{bars("Warning labels in the tracked list", [
    ("Sniper (buys in the first seconds)", 61, "profits from being first, you can't be faster"),
    ("Insider (close to the token's team)", 22, "knows about the launch before you"),
    ("Bundler (buys in the launch block)", 17, "controls supply from the start"),
    ("Bot (trades nonstop)", 16, "hundreds of trades a day"),
    ("Developer of tokens", 15, "creates tokens and sells into buyers"),
    ("Exchange or rug-linked", 11, "exchange wallets, ruggers and their funders"),
], sub="Wallets per label (one wallet can have several)", fmt="num", hl=(0,), source=WALLETS)}

<h2>How to track a Solana wallet properly</h2>
<ol>
<li><b>Judge on closed trades, not screenshots.</b> Ten closed trades is the minimum; one 50x trade can hide forty
losses. In our data, 3 of the 11 profitable wallets made more than half of their profit on a single trade.</li>
<li><b>Look at holding time.</b> If the median hold is under 10 minutes, you cannot copy it manually. Our copy filter
flags these as "holds &lt; 10 min".</li>
<li><b>Check what it bought into.</b> A wallet that keeps buying tokens that later rug (we found a median of one
rugged token per active wallet) is either unlucky or part of the scheme.</li>
<li><b>Exclude snipers, bundlers, insiders and bots.</b> Their edge is speed or inside information, which you
don't get by copying.</li>
<li><b>Re-score every week.</b> Wallets that were hot last month cool down. A tracker should drop them
automatically.</li>
</ol>

<h2>Wallet tracker vs. block explorer</h2>
<p>You can look up any address on Solscan or a DEX screener, but that shows you history, not a decision. A wallet
tracker adds three things: alerts in real time, a score built from closed trades, and labels that warn you about
snipers and insiders. MemeSonar adds a fourth: it checks every token a tracked wallet buys against our
<a href=/blog/how-to-spot-a-rug-pull>rug filter</a> before you see it, and it tells you when <b>several</b> good
wallets buy the same token, which matters far more than one wallet alone.</p>
<p>Next: <a href=/blog/what-is-copy-trading>what copy trading is and when it is profitable</a>.</p>
""", related=("what-is-copy-trading", "bundles-and-snipers", "how-to-spot-a-rug-pull"))


# 2 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "what-is-copy-trading", "Copy trading",
    "What is copy trading in crypto, and is it profitable?",
    "What is copy trading? Is crypto copy trading profitable? (real wallet data) | MemeSonar",
    "Copy trading means automatically repeating another trader's buys and sells. We measured Solana wallets and "
    "influencers: here is when copying works, when it loses money, and how to set limits.",
    ["what is copy trading", "is copy trading profitable", "copy trading for beginners", "solana copy trading"], 7,
    "Copy trading means your account automatically buys and sells when a trader you follow does. It can be "
    "profitable, but only if you copy the rare trader with a real, repeatable edge and cap how much each copied trade "
    "can lose. In our data only 2 of 50 active Solana wallets passed that bar.",
    f"""
<h2>How copy trading works</h2>
<p>You choose a trader, either a wallet address or an influencer whose calls you trust. Every time they buy a token,
your account buys the same token with an amount you set, for example $25. When they sell, or when your own
stop-loss or take-profit triggers, you sell too.</p>
<p>On centralised exchanges copy trading means following a "lead trader" inside the exchange. On Solana meme coins it
means following a <a href=/blog/what-is-wallet-tracking>tracked wallet</a> or a <a href=/blog/what-is-a-kol-in-crypto>
KOL</a> on-chain, which is faster and riskier.</p>

<h2>Is copy trading profitable?</h2>
<p>It depends almost entirely on who you copy. These are the median numbers for the 50 Solana wallets in our tracker
that had at least 10 closed trades:</p>
{stats([("31%", "median share of winning trades"), ("3.8 min", "median time a position is held"),
        ("22%", "wallets in profit after all trades")])}
<p>Copying the median wallet loses money: its profit factor (money won divided by money lost) was 0.65, so every $1
lost brought back 65 cents. The two wallets that passed our copy filter looked very different:</p>
{bars("Return on money spent, last 30-60 days", [
    ("Candidate A (16 closed trades)", 36, "win rate 38%, 4 trades did 2x+, holds ~35 min"),
    ("Candidate B (18 closed trades)", 73, "win rate 39%, 5 trades did 2x+, holds ~8 min"),
], sub="Profit as % of SOL spent", fmt="pct", source=WALLETS)}
<p>For comparison, the median active wallet returned -7% on the money it spent.</p>
<p>Notice that even the good ones lose most trades. Copy trading meme coins works because a few trades do 2x to 10x,
not because most trades win. That is why limits matter more than picking.</p>

<h2>Copy trading for beginners: five rules</h2>
<ol>
<li><b>Copy with a fixed small amount</b> per trade (we default to $25) and a daily cap (we default to 10 trades).
One bad day then costs $250, not your account.</li>
<li><b>Only copy fresh entries.</b> If a trader bought 30 minutes ago and the price has already doubled, you are their
exit liquidity. Our copy feature only enters calls that are at most 10 minutes old.</li>
<li><b>Skip what fails the rug check.</b> Good traders also gamble. Your copy should refuse tokens with mint authority
still on, fake liquidity pools or concentrated supply. See <a href=/blog/how-to-spot-a-rug-pull>how to spot a
rug</a>.</li>
<li><b>Don't copy what you can't follow.</b> A wallet that holds 20 seconds is a sniper bot. You will always be
slower.</li>
<li><b>Stop copying losers automatically.</b> Re-score each trader every week, and stop when their last 20 copied
trades are negative.</li>
</ol>

<h2>Copy trading wallets vs. copy trading influencers</h2>
<p>Wallets show you what someone actually did with money. Influencer calls show you what someone said. Calls move
the market (tokens called by a measured influencer reached 2x in 52% of cases, against 14% without a call), but
influencers can also be paid to post. The best signal is both: <a href=/blog/influencer-clustering>several
independent influencers</a> and good wallets on the same token within minutes.</p>
""", related=("what-is-wallet-tracking", "influencer-clustering", "what-is-dca-in-crypto"))


# 3 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "what-is-a-kol-in-crypto", "Influencers",
    "What is a KOL in crypto? How influencer calls move Solana tokens",
    "What is a KOL in crypto? Do crypto influencer calls work? (data) | MemeSonar",
    "A KOL (key opinion leader) is a crypto influencer whose posts move prices. We measured every Solana token call: "
    "called tokens doubled in 52% of cases vs 14% without a call. How to read a KOL.",
    ["what is a kol", "crypto kol", "kol crypto", "crypto influencers"], 6,
    "A KOL, or key opinion leader, is a crypto influencer (usually on X or Telegram) whose posts about a token can move "
    "its price. Calls do matter: in our measurements 52% of called Solana tokens reached 2x, against 14% of "
    "tokens without a call. But each KOL is different, so you score them on their history, not their follower count.",
    f"""
<h2>KOL meaning</h2>
<p><b>KOL</b> stands for key opinion leader. In crypto it means an account with enough attention that its posts
change what people buy: a trader on X with 50,000 followers, a Telegram channel that posts new tokens, a YouTuber.
A <b>call</b> is a post that names a token, usually with its contract address, and says or implies "buy".</p>

<h2>Do KOL calls work?</h2>
<p>We follow the X accounts of influencers who post Solana tokens and measure the price of every called token 1 hour
and 24 hours after the post, and its highest point within 24 hours.</p>
{bars("Share of tokens that reached 2x", [
    ("Tokens without a measured call", 14, "same period"),
    ("Tokens called by a measured KOL", 52, "price at least doubled after the call"),
], sub="Solana tokens, price relative to the moment of the call", fmt="pct", hl=(1,), source=KOL)}
<p>That is close to a 4x higher chance. It is also why calls are bought and sold: some accounts are paid to post,
some buy before they post and sell into their followers. A call is a signal, not a guarantee.</p>

<h2>How to judge a crypto influencer</h2>
<p>Followers tell you reach, not quality. We score each KOL on what happened after their calls:</p>
<ul>
<li><b>Hit rate</b>: share of calls that gained at least 50% within 24 hours.</li>
<li><b>Median 24h peak</b>: the typical highest point after a call. A KOL whose calls peak at +300% is worth more
than one at +40%, even with the same hit rate.</li>
<li><b>Rug rate</b>: share of called tokens that later dropped 90% or more. This is the number that protects you.</li>
<li><b>Late calls</b>: calls made after the price had already doubled in the two hours before. Late calls look good
on a chart but you buy the top.</li>
<li><b>Does the market listen?</b> Did volume at least double in the hour after the post? Some big accounts move
nothing.</li>
</ul>
<p>We also remove bots. Fifteen accounts in our data posted every new token automatically; they looked like the most
active "KOLs" and had no signal at all. You can see live scores on our public
<a href=/influencers>crypto influencer leaderboard</a>.</p>

<h2>When a call is worth acting on</h2>
<ol>
<li>The KOL has at least 10 measured calls, a hit rate above 50% and a low rug rate.</li>
<li>The call is fresh (minutes, not hours) and the price has not already doubled.</li>
<li>The token passes a <a href=/blog/how-to-spot-a-rug-pull>rug check</a>.</li>
<li>Ideally, other independent KOLs call it too. That is the strongest pattern in our data, see
<a href=/blog/influencer-clustering>influencer clustering</a>.</li>
</ol>
""", related=("influencer-clustering", "what-is-copy-trading", "how-to-trade-meme-coins"))


# 4 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "influencer-clustering", "Influencers",
    "Influencer clustering: why 3 KOLs calling the same token in 15 minutes matters",
    "Crypto influencer clustering: when several KOLs call one token (data) | MemeSonar",
    "When 3+ crypto influencers call the same Solana token within 15 minutes, 59% of those tokens doubled vs 33% "
    "otherwise. How clusters form, and how to spot a paid campaign.",
    ["kol crypto", "crypto influencers", "best crypto influencers", "crypto kol"], 6,
    "A cluster is when several independent influencers call the same token within a short window. In our data, tokens "
    "called by 3+ KOLs within 15 minutes reached 2x in 59% of cases, against 33% when fewer KOLs called. But clusters "
    "can be bought too, so you check who is in the group and whether they always appear together.",
    f"""
<h2>What is influencer clustering?</h2>
<p>One influencer calling a token is a single opinion. When several call the same token within minutes, either they
found it independently (a real signal: different people, same conclusion) or they are coordinated (a group that
pumps together, sometimes paid). Both move the price. Only one is safe to follow.</p>

<h2>The data: clusters double far more often</h2>
{bars("Called tokens that reached 2x within 24 hours", [
    ("1-2 KOLs within 15 minutes", 33, "the first call plus at most one more"),
    ("3+ different KOLs within 15 minutes", 59, "counted from the first call"),
], sub="Solana tokens with at least one measured call", fmt="pct", hl=(1,), source=KOL)}
<p>The 15-minute window matters. Later calls tend to be followers of the first call, not independent finds, and by
then the move has often happened. We count distinct accounts, so one KOL posting three times is still one.</p>

<h2>Organic cluster or coordinated group?</h2>
<p>We map which influencers call the same tokens over weeks. Three patterns stand out:</p>
<ul>
<li><b>Independent cluster</b>: accounts that rarely overlap suddenly call the same token. This is the strongest
signal we see.</li>
<li><b>Fixed group</b>: the same 4-6 accounts call the same tokens again and again, often within the same minute.
This is a promotion group. The first minutes can still pump, but the dump is organised too.</li>
<li><b>Echo</b>: one large account calls, then small accounts repeat it. The small calls add little; they are
followers.</li>
</ul>
<p>Our "Correlations" view inside the app shows these groups as a network, and the copy-trading signal weights an
independent cluster higher than a fixed group.</p>

<h2>How to use clusters without being exit liquidity</h2>
<ol>
<li>React to the <b>third independent</b> call, not the tenth. After that the crowd is late.</li>
<li>Check the price before you buy. If it already doubled since the first call, skip.</li>
<li>Run the token through a <a href=/blog/how-to-spot-a-rug-pull>rug check</a>. Coordinated groups often launch tokens
with bundled supply (see <a href=/blog/bundles-and-snipers>bundles and snipers</a>).</li>
<li>Use small, fixed amounts and take some profit early. Clusters peak fast.</li>
</ol>
<p>See the scores of every measured influencer on the public <a href=/influencers>KOL leaderboard</a>.</p>
""", related=("what-is-a-kol-in-crypto", "bundles-and-snipers", "how-to-trade-meme-coins"))


# 5 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "how-to-spot-a-rug-pull", "Rug pulls",
    "How to spot a rug pull on Solana: 7 checks from 10,650 tokens",
    "How to spot a rug pull on Solana: a rug checker checklist (data from 10,650 tokens) | MemeSonar",
    "Seven checks that catch most Solana rug pulls, with numbers from 10,650 pump.fun tokens: serial creators, dev "
    "selling, mint authority, fake pools, missing socials and concentrated holders.",
    ["how to avoid rug pulls", "solana rug checker", "rug checker", "what is a rug pull", "rug check"], 8,
    "A rug pull is when the people behind a token take the money and the price collapses, by selling their supply, "
    "pulling liquidity or minting new tokens. Most are visible before you buy: in our data, tokens from creators who "
    "had launched 20+ tokens before doubled only 1.4% of the time, against 16.8% for first-time creators.",
    f"""
<h2>What is a rug pull?</h2>
<p>A <b>rug pull</b> is a token whose creators or insiders cash out and leave buyers holding something worthless. On
Solana it usually happens in one of three ways: the creator and connected wallets sell a large share of supply into
buyers, the liquidity pool is pulled, or the token's mint authority is used to print new tokens. A quiet version
is the slow rug: the team sells a little every hour until nothing is left.</p>
<p>When we clean up our database every hour, these show up clearly. In the first clean-up on 1 November 2026, 61
tokens older than a day were removed: 52 had crashed 70% or more and 9 showed rug mechanics such as pulled
liquidity.</p>

<h2>Check 1: who created it, and how many times before?</h2>
<p>The strongest single warning in our data is a <b>serial creator</b>: a wallet that has launched many tokens
before.</p>
{bars("Tokens that reached 2x, by the creator's previous launches", [
    ("First token from this wallet", 16.8, "2,598 tokens"),
    ("1-5 previous tokens", 9.2, "769 tokens"),
    ("6-20 previous tokens", 3.8, "764 tokens"),
    ("More than 20 previous tokens", 1.4, "1,528 tokens"),
], sub="Measured 15 minutes after launch; 2x = price later doubled", fmt="pct", hl=(3,), source=RETRO)}

<h2>Check 2: has the developer already sold?</h2>
{bars("Tokens that reached 2x, by developer behaviour", [
    ("Developer still holding", 16.1, "2,696 tokens"),
    ("Developer already sold some", 6.6, "4,505 tokens"),
], sub="Measured 15 minutes after launch", fmt="pct", hl=(1,), source=RETRO)}
<p>Watch for a developer moving tokens to many fresh wallets too. That hides the real share; we flag it when more
than 90% of the developer's tokens are moved out.</p>

<h2>Check 3: can new tokens be minted or wallets frozen?</h2>
<p>If <b>mint authority</b> is still on, the creator can print new supply and sell it. If <b>freeze authority</b> is
on, they can stop you from selling. Pump.fun tokens have both off by default; tokens created elsewhere often don't.
Either one is an automatic reject in our filter.</p>

<h2>Check 4: is the liquidity real?</h2>
<p>Look for at least $10,000 of liquidity, and check that it sits in the main pool, not in a fake pool created to make
the token look tradable. Our filter rejects tokens below $10k liquidity and tokens whose only pool is not a known
DEX.</p>

<h2>Check 5: socials (yes, they matter)</h2>
{bars("Tokens that reached 2x, by number of social links", [
    ("No website, X or Telegram", 4.9, "1,134 tokens"),
    ("One link", 9.3, "686 tokens"),
    ("Two links", 16.1, "852 tokens"),
    ("All three", 31.3, "67 tokens"),
], sub="Measured 15 minutes after launch", fmt="pct", hl=(0,), source=RETRO)}
<p>Social links cost nothing to add, so they prove little alone. Their absence is still a strong warning.</p>

<h2>Check 6: bundles and snipers</h2>
<p>Bundled supply (bought in the same block as the launch) and snipers (bought in the first seconds) give a small group
control over the price. Tokens with heavy bundles actually pump more often, and then fall harder. Read
<a href=/blog/bundles-and-snipers>bundles and snipers explained</a>.</p>

<h2>Check 7: holder concentration</h2>
<p>If the top 10 holders (excluding the liquidity pool) own more than about a third of supply, a few wallets can end
the party. Watch whether the share grows after launch: insiders accumulating through fresh wallets is a classic
setup.</p>

<h2>A rug checker does this in seconds</h2>
<p>All seven checks run on every token MemeSonar shows, before you see it. Tokens that fail are hidden, not just
labelled, and every hour the system learns the profile of the rugs it caught.</p>
""", related=("bundles-and-snipers", "what-is-pump-fun", "market-cap-liquidity-slippage"))


# 6 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "what-is-pump-fun", "Basics",
    "What is pump.fun? How it works, and what our data says about your odds",
    "What is pump.fun and how does it work? Bonding curve, graduation and real odds | MemeSonar",
    "Pump.fun lets anyone launch a Solana meme coin in a minute. How the bonding curve and graduation work, and why "
    "only 0.8% of random new tokens ever double after their first 15 minutes.",
    ["what is pump fun", "how does pump fun work", "pump fun bonding curve", "pump fun graduation"], 6,
    "Pump.fun is a Solana launchpad where anyone can create a meme coin for a few cents. The price follows a bonding "
    "curve until the token 'graduates' to a normal DEX pool. Most tokens never get there: of 6,104 random new tokens "
    "we followed, 0.8% doubled after their first 15 minutes.",
    f"""
<h2>How pump.fun works</h2>
<p>You pick a name, a ticker and an image, pay a small fee, and the token exists. There is no team, no presale and no
liquidity to provide. Every token starts with the same supply (one billion) and the same starting price.</p>
<p>Prices follow a <b>bonding curve</b>: a formula that raises the price as people buy and lowers it as they sell.
Early buyers get more tokens per SOL. When enough SOL has been put in, the token <b>graduates</b>: its liquidity moves
to a normal DEX pool and it trades like any other token, on DEX screeners and trading bots.</p>

<h2>Your odds, in numbers</h2>
<p>We sampled pump.fun tokens at random, 15 minutes after launch, and followed what the price did next.</p>
{bars("What happened to random new pump.fun tokens", [
    ("Later reached 2x", 0.8, "from the price 15 minutes after launch"),
    ("Later reached 3x", 0.3, ""),
    ("Graduated to a DEX pool", 0.1, "about 1 in 1,000 in our random sample"),
], sub="6,104 random tokens, October 2026", fmt="pct", hl=(0,), source=RETRO)}
<p>In other words, picking a random new token and waiting is a losing game. The tokens that do graduate do it fast:
the median time to graduation was about 15 minutes.</p>

<h2>Graduation is not the finish line</h2>
<p>Many traders wait for graduation as proof of interest. It helps, but less than people think:</p>
{bars("Graduated tokens: share that went higher after graduating", [
    ("Reached 2x after graduation", 9.5, ""),
    ("Reached 3x", 7.3, ""),
    ("Reached 5x", 4.9, ""),
], sub="2,784 graduated tokens, price measured at the moment of graduation", fmt="pct", hl=(0,), source=RETRO)}
<p>A much better entry point in our data is the first time a token crosses $100,000 of market cap; we explain why in
<a href=/blog/how-to-trade-meme-coins>how to trade meme coins</a>. The few that made it big are on our
<a href=/solana-meme-coins>top 100 Solana meme coins</a> list.</p>

<h2>Is pump.fun safe?</h2>
<p>The platform itself removes some classic rug tricks: mint and freeze authority are off, and the curve holds the
liquidity until graduation. What it cannot stop is people. Serial creators, bundled launches and snipers are all common
on pump.fun. Before you buy, check the creator's history and the first buyers, as in
<a href=/blog/how-to-spot-a-rug-pull>how to spot a rug pull</a>.</p>
""", related=("how-to-trade-meme-coins", "bundles-and-snipers", "how-to-spot-a-rug-pull"))


# 7 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "bundles-and-snipers", "Rug pulls",
    "Bundles and snipers explained: who really owns a new Solana token",
    "Bundles and sniper bots on Solana explained (with data) | MemeSonar",
    "Bundlers buy in the launch block, snipers in the first seconds. Tokens with heavy bundles pump more often, and "
    "then fall twice as hard. What that means for you, with numbers from 7,201 tokens.",
    ["solana sniper bot", "what is a sniper bot", "bundle checker", "sniper bot"], 6,
    "A bundle is a group of wallets that buy a token in the same block it is created; a sniper buys in the first "
    "seconds. Both give a few wallets a big share of supply at the lowest price. In our data, tokens with more than 20% "
    "bundled supply reached 2x more often (25.5% vs 3.6%) but their typical drop from the top was 54%.",
    f"""
<h2>What is a bundle?</h2>
<p>On Solana several transactions can be sent together and land in the same block. A <b>bundle</b> is the creator (or
someone close to them) buying a large share of their own token in the very block it is created, spread over several
wallets so it looks like many buyers. A <b>bundle checker</b> looks at that first block and adds up what was bought.</p>

<h2>What is a sniper bot?</h2>
<p>A <b>sniper</b> is a bot that buys a new token within the first seconds, before people can react. Snipers are not
always connected to the team; many just bet on every launch and sell into the first wave of buyers.</p>

<h2>The surprising part: bundled tokens pump more often</h2>
{bars("Tokens that reached 2x, by bundled share of supply", [
    ("Under 2% bundled", 3.6, "3,554 tokens"),
    ("2-10%", 10.8, "1,683 tokens"),
    ("10-20%", 15.4, "768 tokens"),
    ("Over 20%", 25.5, "1,196 tokens"),
], sub="Measured 15 minutes after launch", fmt="pct", hl=(3,), source=RETRO)}
<p>That looks like a buy signal. It is not, and the next chart shows why. A bundled token is an organised launch:
someone has a plan, maybe a promotion budget, and the price is pushed up. The question is who gets out first.</p>
{bars("Typical fall from the highest price", [
    ("Under 2% bundled", 46, "median drop from the peak"),
    ("2-10%", 17, ""),
    ("10-20%", 35, ""),
    ("Over 20%", 54, "insiders sell into the pump"),
], sub="Median maximum drawdown in the first hours, %", fmt="pct", hl=(3,), source=RETRO)}
<p>Snipers show the same pattern: tokens where snipers took more than 30% of supply reached 2x in 31.8% of cases, and
their median fall from the top was 58%.</p>

<h2>What this means for you</h2>
<ul>
<li>A heavy bundle tells you the token is someone's project. That project's goal is to sell to you at a higher
price.</li>
<li>If you trade bundled tokens, trade the first wave with a small amount and take profit early. Do not hold them
overnight.</li>
<li>Check whether bundle wallets are still holding. When they start selling, the drop is fast.</li>
<li>Combine with the creator's history: a bundled launch from a wallet with 20+ previous tokens is the classic rug.</li>
</ul>
<p>MemeSonar measures bundle share, sniper share and the first buyers on every new token, and caps how much of a
heavily bundled token the system will ever buy. Read the full <a href=/blog/how-to-spot-a-rug-pull>rug checklist</a>.</p>
""", related=("how-to-spot-a-rug-pull", "what-is-pump-fun", "influencer-clustering"))


# 8 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "how-to-trade-meme-coins", "Trading",
    "How to trade meme coins: when to enter, according to 10,650 tokens",
    "How to trade meme coins on Solana: the best entry point (data from 10,650 tokens) | MemeSonar",
    "Entry timing decides most meme coin trades. Random new tokens doubled 0.8% of the time, graduated ones 9.5%, and "
    "tokens first crossing $100k market cap 24%. A practical meme coin trading plan.",
    ["how to trade meme coins", "meme coin trading", "memecoin trading", "how to buy meme coins on solana"], 7,
    "When you enter matters more than what you pick. In our data, buying random tokens 15 minutes after launch led to "
    "2x only 0.8% of the time; at graduation 9.5%; at the first cross of $100,000 market cap 24%. A good plan waits for "
    "proof of demand, filters rugs, sizes small and takes profit in steps.",
    f"""
<h2>Entry point beats token picking</h2>
<p>We measured the same tokens at different moments of their life and asked: from this price, how many later
doubled?</p>
{bars("Tokens that later reached 2x, by entry moment", [
    ("15 minutes after launch (random)", 0.8, "6,104 tokens"),
    ("At graduation", 9.5, "2,784 tokens"),
    ("First cross of $100k market cap", 24.0, "217 tokens"),
    ("First cross of $1M market cap", 31.6, "19 tokens, small sample"),
], sub="Price at entry vs. later peak", fmt="pct", hl=(2,), source=RETRO)}
<p>Buying later means paying more, but it also means most of the losers are already gone. The first $100k
cross is the best balance we found: still early enough for 2x-10x, late enough that the token has real buyers. The
$1M row looks even better, but with 19 tokens it is not a reliable number yet.</p>

<h2>A meme coin trading plan</h2>
<h3>1. Find candidates</h3>
<p>Use signals that predict demand: several independent <a href=/blog/influencer-clustering>influencer calls</a>,
<a href=/blog/what-is-wallet-tracking>good wallets</a> buying, volume growing. Avoid tokens you found because they
were already up 300% on your screen.</p>
<h3>2. Filter</h3>
<p>Run the <a href=/blog/how-to-spot-a-rug-pull>rug checklist</a>: creator history, developer selling, authorities,
real liquidity of at least $10,000, holders.</p>
<h3>3. Size</h3>
<p>Use a fixed amount you can lose, for example 1-2% of your trading money per token. With meme coins, a few trades
make the result; position size keeps you in the game long enough to hit them.</p>
<h3>4. Check the cost of getting in and out</h3>
<p>On a $10,000 pool, a $1,000 buy gets you about 17% fewer tokens than the quoted price. See
<a href=/blog/market-cap-liquidity-slippage>market cap, liquidity and slippage</a>.</p>
<h3>5. Take profit in steps</h3>
<p>Sell a part at 2x to recover your stake, another part on the way up, and let the rest run with a trailing stop.
Holding everything for the "100x" is how most winners turn into losses.</p>
<h3>6. Time of day</h3>
<p>In our data, influencer signals worked best during US hours, while entries in that session were the most expensive.
Know which session you are trading.</p>

<h2>Where to look today</h2>
<p>Our public <a href=/solana-meme-coins>top 100 Solana meme coins</a> list shows market cap, liquidity, volume and
holder data for each token, for example <a href=/coin/bonk>BONK</a>, <a href=/coin/wif>WIF</a> or
<a href=/coin/fartcoin>Fartcoin</a>. These are the survivors; the tokens in this article's charts are mostly
the ones that didn't make it.</p>

<h2>Practice before you use real money</h2>
<p>MemeSonar's members trade with a $1,000 demo balance in a friendly league, with the same signals and rug filter
the system uses. It is the cheapest way to find out whether your plan works.</p>
""", related=("what-is-pump-fun", "market-cap-liquidity-slippage", "what-is-dca-in-crypto"))


# 9 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "what-is-dca-in-crypto", "Basics",
    "What is DCA in crypto? Dollar-cost averaging for meme coins, with a worked example",
    "What is DCA in crypto? Dollar-cost averaging explained with an example | MemeSonar",
    "DCA (dollar-cost averaging) means buying a fixed amount at regular intervals instead of all at once. A worked "
    "example: $500 at once vs. 10 x $50, on a falling and on a rugging token.",
    ["what is dca", "dca crypto", "crypto dca bot", "dollar cost averaging crypto"], 5,
    "DCA, or dollar-cost averaging, means buying the same amount at fixed intervals (for example $50 every 12 hours) "
    "instead of investing everything at once. It lowers your average price when the price swings, and with automatic "
    "stops it limits the damage when a token fails. It does not turn a bad token into a good one.",
    f"""
<h2>DCA meaning</h2>
<p><b>Dollar-cost averaging</b> spreads one purchase over time. You choose an amount, an interval and how many buys:
for example 10 buys of $50, one every 12 hours. When the price is low, $50 buys more tokens; when it is high,
fewer. Your average price ends up below the simple average of the prices you paid on.</p>

<h2>Worked example: one buy vs. ten</h2>
<p>An illustrative token falls from $1.00 to $0.45 over five days, then recovers to $0.90. You have $500.</p>
{bars("Value of $500 when the price is back at $0.90", [
    ("All at once at $1.00", 450, "500 tokens at $0.90"),
    ("10 x $50 over five days (DCA)", 692, "768 tokens, average price $0.65"),
], sub="Illustrative example, not a real token", fmt="usd", hl=(1,))}
<p>Same money, same token, same end price: the lump sum is down 10%, the DCA is up 38%, because half of the buys
happened below $0.65.</p>

<h2>Where DCA really helps with meme coins: the stop</h2>
<p>The bigger risk with meme coins is not a dip, it is a token going to zero. Suppose the token rugs after your third
buy and is suddenly worth $0.03.</p>
{bars("What is left after a rug", [
    ("All at once at $1.00", 15, "lost $485"),
    ("DCA that stops at the rug", 156, "$150 spent, ~$6 left, $350 never invested"),
], sub="Illustrative example: money left = remaining tokens + cash not yet spent", fmt="usd", hl=(1,))}
<p>An automatic DCA should stop by itself when the token fails a safety rule: liquidity below a minimum, a rug signal,
or your budget running out.</p>

<h2>When DCA is a bad idea</h2>
<ul>
<li>On tokens in a steady decline: you keep averaging down into a loser. Set a hard stop.</li>
<li>On very thin pools, where each buy moves the price (see <a href=/blog/market-cap-liquidity-slippage>slippage</a>).
</li>
<li>When fees eat the buys: on Solana fees are small, but $5 buys still lose a noticeable share to fees and
slippage.</li>
</ul>

<h2>DCA in MemeSonar</h2>
<p>Members can start an automatic DCA on any token from its page: $5 to $500 per buy, every 15 minutes to once a week,
2 to 100 buys. It stops by itself when the plan is done, the money runs out, the token is flagged as a rug or its
liquidity drops under $5,000.</p>
""", related=("how-to-trade-meme-coins", "what-is-copy-trading", "market-cap-liquidity-slippage"))


# 10 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "market-cap-liquidity-slippage", "Basics",
    "Market cap, liquidity and slippage: the three numbers to read before buying a meme coin",
    "What is slippage, liquidity and market cap in crypto? (with a slippage table) | MemeSonar",
    "Market cap tells you the size, liquidity how much you can trade, slippage what a trade really costs. A table of "
    "slippage for $100 to $5,000 buys in pools from $10k to $1M, and what FDV means.",
    ["what is slippage", "what is liquidity in crypto", "what is market cap in crypto", "what is fdv"], 6,
    "Market cap is price times supply: the token's size. Liquidity is the money in the trading pool: how much you can buy "
    "or sell without moving the price. Slippage is the difference between the quoted price and what you actually get. "
    "On a $10,000 pool a $1,000 buy gets about 17% fewer tokens than the quote.",
    f"""
<h2>Market cap</h2>
<p><b>Market cap</b> = price x circulating supply. A pump.fun token has one billion tokens, so a price of $0.0001
means a $100,000 market cap. Market cap is how traders compare tokens and set targets: "it's at $100k, the last one
like it went to $5M".</p>
<p><b>FDV</b> (fully diluted valuation) is price x maximum supply. For pump.fun tokens the two are the same. For tokens
with locked or future supply, FDV can be many times the market cap, and unlocks can push the price down.</p>

<h2>Liquidity</h2>
<p><b>Liquidity</b> is the money sitting in the pool you trade against, usually half SOL and half the token. A token
can have a $1M market cap and only $20,000 of liquidity: on paper it is worth a million, in practice only a fraction
can be sold before the price collapses. That is why our filter rejects tokens with less than $10,000 of liquidity.</p>

<h2>Slippage</h2>
<p><b>Slippage</b> is the gap between the price you see and the price you get. In a standard pool the price moves
along a curve as you buy, so a larger buy relative to the pool pays more on average. The table shows how many fewer
tokens you receive than at the quoted price:</p>
{grid("Fewer tokens than the quoted price, by buy size and pool liquidity",
      ["$100", "$500", "$1,000", "$5,000"],
      [("Pool $10k", [2.0, 9.1, 16.7, 50.0]), ("Pool $50k", [0.4, 2.0, 3.8, 16.7]),
       ("Pool $250k", [0.1, 0.4, 0.8, 3.8]), ("Pool $1M", [0.0, 0.1, 0.2, 1.0])],
      sub="Constant-product pool, half of the liquidity on each side, before fees (about 0.25-1%)", cap=50)}
{CALC.slippage("en")}
<p>Selling costs the same again on the way out. A $1,000 round trip in a $10k pool loses roughly a third of the
money before the price has even moved.</p>

<h2>Slippage tolerance</h2>
<p>Swap apps let you set a <b>slippage tolerance</b>: the most you accept. Too low and your trade fails in a fast
market; too high and bots can sandwich your order (buy just before you and sell just after). For meme coins, keep it
at a level you could live with as the full cost, and size the trade to the pool.</p>

<h2>Read all three together</h2>
<ul>
<li>Market cap tells you how much room is left. A $50k token can do 20x; a $500M token rarely does.</li>
<li>Liquidity tells you whether you can get out. Aim for at least $10k, more for bigger trades.</li>
<li>Slippage tells you what the trade costs. Keep each buy below about 2% of the pool's liquidity.</li>
</ul>
<p>Next: <a href=/blog/how-to-trade-meme-coins>how to trade meme coins</a>, or the checks in
<a href=/blog/how-to-spot-a-rug-pull>how to spot a rug pull</a>.</p>
""", related=("how-to-trade-meme-coins", "what-is-dca-in-crypto", "how-to-spot-a-rug-pull"))


# 11 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
EXCH_SRC = "HANFA register, ESMA/national regulator announcements, published fee pages; checked 1 Nov 2026"
FEE_SRC = "exchanges' published fee pages and the top7.hr comparison of 28 Sep 2026; fees change, check before you pay"
post(
    "best-crypto-exchanges-croatia", "Exchanges",
    "Best crypto exchanges in Croatia and the EU (2026): licensed under MiCA, compared",
    "Best crypto exchanges in Croatia 2026: MiCA-licensed, fees compared | MemeSonar",
    "Which crypto exchanges are licensed for Croatia in 2026? 5 HANFA-licensed Croatian firms and 9 MiCA exchanges "
    "compared by regulator, fees, Croatian support and cash options.",
    ["best crypto exchange croatia", "crypto exchange eu regulated", "mica licensed exchanges", "kriptomjenjačnica"], 9,
    "Since 1 July 2026 every crypto exchange serving Croatians must hold a MiCA licence. Five Croatian firms are on "
    "HANFA's register (Electrocoin, Bitcoin Store, Kriptomat, Whitely, IN Kapital), and the big EU exchanges (Kraken, "
    "Coinbase, Bitstamp, Bitpanda, Revolut, OKX, Bybit, Crypto.com, Bitvavo) passport their licence into Croatia. "
    "Cheapest to trade: OKX, Bitstamp and Kraken Pro. Easiest in Croatian: Electrocoin and Bitcoin Store.",
    f"""
<h2>Why the licence matters now</h2>
<p>The EU's Markets in Crypto-Assets regulation (<b>MiCA</b>) replaced national rules. The transition period ended on
<b>1 July 2026</b>: from that day a company may serve customers in Croatia only with a MiCA licence, either from
HANFA (the Croatian regulator) or from another EU regulator, passported into Croatia. A licence means capital
requirements, segregated customer funds, complaint handling and a regulator you can write to. It does not mean the
coins you buy are safe; meme coins stay meme coins.</p>
{stats([("5", "Croatian firms on HANFA's register"), ("9+", "big EU exchanges licensed under MiCA"),
        ("1 Jul 2026", "end of the transition period")])}

<h2>Croatian exchanges licensed by HANFA</h2>
<p>These companies are on HANFA's register of firms authorised to provide crypto-asset services. Electrocoin was the
first to receive a full MiCA licence from HANFA.</p>
<div class=tw><table><thead><tr><th>Exchange</th><th>Company</th><th>Based in</th><th>Good for</th></tr></thead><tbody>
<tr><td><b>Electrocoin</b></td><td>Electrocoin d.o.o.</td><td>Zagreb</td><td>Croatian support 24/7, buying in euros, pay at shops</td></tr>
<tr><td><b>Bitcoin Store</b></td><td>Digital Assets d.o.o.</td><td>Split</td><td>Branches with cash, no deposit or withdrawal fees</td></tr>
<tr><td><b>Kriptomat</b></td><td>Bitblock d.o.o.</td><td>Zagreb</td><td>Simple app, Croatian interface</td></tr>
<tr><td><b>Whitely</b></td><td>White Tech d.o.o.</td><td>Zagreb</td><td>Buy and store, Croatian support</td></tr>
<tr><td><b>IN Kapital</b></td><td>IN Kapital d.o.o.</td><td>Sesvete</td><td>Exchange of crypto for euros</td></tr>
</tbody></table></div>
<p class=mut>Source: <a href="https://www.hanfa.hr/registri/trziste-kriptoimovine/registar-drustava-ovlastenih-pruzati-usluge-povezane-s-kriptoimovinom/" rel=nofollow>HANFA register</a>, checked 1 Nov 2026.</p>

<h2>EU exchanges licensed under MiCA</h2>
<p>These hold a MiCA licence from another EU country and can serve Croatia through passporting.</p>
<div class=tw><table><thead><tr><th>Exchange</th><th>Regulator</th><th>Licence date</th></tr></thead><tbody>
<tr><td><b>Crypto.com</b></td><td>MFSA (Malta)</td><td>27 Jan 2025</td></tr>
<tr><td><b>OKX</b></td><td>MFSA (Malta)</td><td>27 Jan 2025</td></tr>
<tr><td><b>Bitpanda</b></td><td>BaFin (Germany), also Austria</td><td>2025</td></tr>
<tr><td><b>Bitstamp</b></td><td>CSSF (Luxembourg)</td><td>15 May 2025</td></tr>
<tr><td><b>Bybit</b></td><td>FMA (Austria)</td><td>28 May 2025</td></tr>
<tr><td><b>Coinbase</b></td><td>CSSF (Luxembourg)</td><td>20 Jun 2025</td></tr>
<tr><td><b>Kraken</b></td><td>Central Bank of Ireland</td><td>25 Jun 2025</td></tr>
<tr><td><b>Bitvavo</b></td><td>AFM (Netherlands)</td><td>26 Jun 2025</td></tr>
<tr><td><b>Revolut</b></td><td>CySEC (Cyprus)</td><td>2025</td></tr>
</tbody></table></div>
<p>Binance did not hold a MiCA licence when we checked (1 Nov 2026), so its services for EU users are restricted.
Always check the regulator's own register before you deposit; a website that says "regulated" is not proof.</p>

<h2>What buying costs</h2>
<p>Exchanges charge in two ways: a visible <b>trading fee</b> on an order-book platform (Kraken Pro, Bitstamp, OKX), or
a <b>spread</b> hidden in the price on a simple "Buy" button. The spread is usually the bigger cost. The chart shows
the lowest published cost of a buy:</p>
{bars("Lowest published cost of buying crypto",
      [("OKX (order book, taker)", 0.10, "maker 0.08%"),
       ("Bitstamp (order book, taker)", 0.40, "simple buy: spread about 1.8% plus up to 0.5%"),
       ("Kraken Pro (taker)", 0.40, "simple buy: 1% plus spread"),
       ("Bitcoin Store (spread)", 0.50, "spread 0.5-5% depending on coin and amount"),
       ("Revolut (standard plan)", 1.49, "plus 0-3% spread; 0.99% on Premium/Metal"),
       ("Electrocoin (Trade account)", 1.75, "about 2% on the web buy")],
      sub="Percent of the amount, before deposit and withdrawal fees", fmt="pct2", hl=(0, 1, 2), source=FEE_SRC)}
<div class=tw><table><thead><tr><th>Exchange</th><th>Euro deposit</th><th>Euro withdrawal</th><th>Croatian support</th></tr></thead><tbody>
<tr><td>Kraken</td><td>SEPA free</td><td>€1</td><td>No</td></tr>
<tr><td>Bitstamp</td><td>SEPA free; card 4%</td><td>€3</td><td>No</td></tr>
<tr><td>Revolut</td><td>From your Revolut account</td><td>Free inside Revolut</td><td>Yes (app)</td></tr>
<tr><td>Electrocoin</td><td>Bank transfer, shops</td><td>€0.50 (min €5)</td><td>Yes, 24/7</td></tr>
<tr><td>Bitcoin Store</td><td>Free, cash at branches</td><td>Free</td><td>Yes</td></tr>
</tbody></table></div>
<p class=mut>Fees from the exchanges' fee pages and top7.hr (28 Sep 2026). They change often: check the fee page on the
day you buy.</p>

<h2>Which one to pick</h2>
<ul>
<li><b>You want the lowest cost:</b> an order-book platform (OKX, Bitstamp, Kraken Pro). Use a limit order and skip the
simple "Buy" button.</li>
<li><b>You want Croatian and a phone number:</b> Electrocoin or Bitcoin Store. You pay more per buy, but support and
cash options are local.</li>
<li><b>You already use Revolut:</b> fastest to start, but you pay 1.49% plus spread, and the cost adds up on frequent buys.</li>
<li><b>You want to buy Solana meme coins:</b> none of these lists most meme coins. Buy <b>SOL</b> on any of them, withdraw
it on the Solana network to your own wallet, and swap there. That route is in our guide
<a href=/blog/how-to-buy-solana-meme-coins>how to buy Solana meme coins</a>, and every coin has its own page, for example
<a href=/how-to-buy/bonk>how to buy Bonk</a>.</li>
</ul>

<h2>Before you deposit</h2>
<ul>
<li>Find the company on <a href="https://www.hanfa.hr/registri/trziste-kriptoimovine/registar-drustava-ovlastenih-pruzati-usluge-povezane-s-kriptoimovinom/" rel=nofollow>HANFA's register</a> or the ESMA register of MiCA providers.</li>
<li>Turn on two-factor login with an app, not SMS.</li>
<li>Send a small test withdrawal first and check that the network (for example Solana) matches your wallet.</li>
<li>Never give anyone your recovery phrase. No exchange, support agent or app will ever need it.</li>
<li>In Croatia, gains on crypto are taxed (12% capital gains tax; holdings kept longer than two years are exempt). Keep
your exchange statements; see <a href=/blog/crypto-tax-croatia>crypto tax in Croatia</a>. Want to spend crypto in shops?
Compare <a href=/blog/crypto-cards-croatia>crypto cards in Croatia</a>; buying through a company is covered in
<a href=/blog/company-crypto-investment-croatia>can a company invest in crypto</a>.</li>
</ul>
<p class=mut>We have no affiliate links and no payment from any exchange on this page. Source: {EXCH_SRC}.</p>
""", related=("how-to-buy-solana-meme-coins", "market-cap-liquidity-slippage", "how-to-spot-a-rug-pull"))


# 12 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "how-to-buy-solana-meme-coins", "Guides",
    "How to buy Solana meme coins: the safe route, step by step",
    "How to buy Solana meme coins (2026): step-by-step guide | MemeSonar",
    "How to buy Solana meme coins safely: buy SOL on a licensed exchange, move it to Phantom, swap on Jupiter, and "
    "check the token before you buy. Step by step, with real numbers.",
    ["how to buy solana meme coins", "how to buy meme coins", "buy solana meme coins", "where to buy meme coins"], 6,
    "Buy SOL on a MiCA-licensed exchange, withdraw it on the Solana network to a wallet such as Phantom, then swap SOL "
    "for the meme coin on Jupiter using the exact contract address. Before you swap, check liquidity, mint and freeze "
    "authority and top holders: of new pump.fun tokens bought 15 minutes after launch, only 0.8% ever doubled.",
    f"""
<h2>The route in one line</h2>
<p>Euro → <b>SOL</b> on a licensed exchange → your own Solana wallet → swap on a <b>DEX</b> (Jupiter) → the meme coin.
Almost no Solana meme coin is listed on a regulated exchange, so the swap happens on-chain.</p>

<h2>1. Buy SOL on a licensed exchange</h2>
<p>Pick an exchange with a MiCA licence. We compared them in
<a href=/blog/best-crypto-exchanges-croatia>the best crypto exchanges in Croatia and the EU</a>: the cheapest are
order-book platforms (around 0.1-0.4% per trade); Croatian ones cost more but have local support.</p>

<h2>2. Install a wallet and protect the phrase</h2>
<p>Install Phantom or Solflare (see <a href=/best-crypto-tools/crypto-wallets>the best crypto wallets</a>). Write the
12 or 24-word recovery phrase on paper. Anyone with the phrase owns the money; no site, support agent or bot will ever
need it.</p>

<h2>3. Withdraw SOL to your wallet</h2>
<p>Copy your wallet address, choose the <b>Solana</b> network on the exchange and send a small test amount first.
Keep about 0.02 SOL in the wallet for network fees.</p>

<h2>4. Find the real contract address</h2>
<p>Scam tokens copy names and logos. Get the address from a trusted page, for example our coin pages such as
<a href=/coin/bonk>Bonk</a> or the <a href=/solana-meme-coins>top 100 Solana meme coins</a>, and check that the
symbol, logo and market cap match.</p>

<h2>5. Check the token before you swap</h2>
{bars("Share of new pump.fun tokens that later doubled",
      [("15 minutes after launch (random)", 0.8, "6,104 tokens"),
       ("At graduation to a DEX pool", 9.5, "2,784 tokens"),
       ("First cross of $100k market cap", 24.0, "217 tokens")],
      sub="Bought at that moment, price later reached at least 2x", hl=(2,), source=RETRO)}
<ul>
<li><b>Liquidity</b> at least $10k, and your buy below about 2% of it (see
<a href=/blog/market-cap-liquidity-slippage>market cap, liquidity and slippage</a>).</li>
<li><b>Mint authority</b> and freeze authority switched off.</li>
<li>Top 10 holders under about 35%, developer under 5%.</li>
</ul>
<p>Every coin in our top 100 has an automatic check, for example <a href=/rug-check/bonk>is Bonk safe?</a></p>

<h2>6. Swap on Jupiter</h2>
<p>Open jup.ag (or the swap inside Phantom), connect the wallet, choose SOL → paste the contract address, set the
amount and a <b>slippage</b> tolerance you could live with, and confirm. Our <a href=/blog/how-to-use-jupiter-swap>Jupiter
swap guide</a> covers the settings.</p>

<h2>7. Plan the exit before you buy</h2>
<p>Decide where you take profit and where you cut the loss, and write it down. Meme coins move 50% in an hour; without
a plan the decision gets made by emotion. See <a href=/blog/how-to-trade-meme-coins>how to trade meme coins</a>.</p>
""", related=("best-crypto-exchanges-croatia", "how-to-use-jupiter-swap", "how-to-spot-a-rug-pull"))


# 13 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "how-to-use-jupiter-swap", "Guides",
    "How to use Jupiter swap on Solana: settings that save you money",
    "How to use Jupiter swap (jup.ag): slippage, priority fees, limit orders | MemeSonar",
    "A practical Jupiter swap guide: connecting a wallet, checking the token, slippage and priority fee settings, "
    "limit orders and DCA, and the mistakes that cost the most.",
    ["jupiter swap", "how to use jupiter swap", "jup.ag", "jupiter exchange solana"], 6,
    "Jupiter (jup.ag) is a Solana swap aggregator: it splits your order across pools to get the best price. Connect a "
    "wallet, pick SOL and paste the token's contract address, keep the buy small relative to the pool's liquidity, set "
    "slippage you can accept as the full cost, and use limit orders when you are not in a hurry.",
    f"""
<h2>What Jupiter is</h2>
<p>Jupiter is not an exchange with its own order book; it is an <b>aggregator</b>. It looks at the Solana
<b>DEX</b> pools (Raydium, Orca, Meteora, pump.fun's pools and others) and routes your trade through the cheapest
path, sometimes splitting it across several pools. You keep your coins in your own wallet the whole time.</p>

<h2>Step by step</h2>
<ol>
<li>Open <b>jup.ag</b> (type it yourself; fake Jupiter sites are a common wallet-drainer trick) and connect Phantom or
Solflare.</li>
<li>"You pay": SOL or USDC. "You receive": paste the token's <b>contract address</b>, not its name.</li>
<li>Check the warning badges: Jupiter flags unverified tokens. Unverified is not proof of a scam, but check the
<a href=/rug-check>rug check</a> first.</li>
<li>Look at the price impact line before you confirm.</li>
<li>Confirm in the wallet and read what the wallet says it will sign.</li>
</ol>

<h2>Slippage and price impact</h2>
<p><b>Price impact</b> is how far your own trade moves the pool; <b>slippage</b> tolerance is how much worse than the
quote you accept before the trade fails. In a thin pool the impact alone can be large:</p>
{grid("Price impact by buy size and pool liquidity",
      ["$100", "$500", "$1,000", "$5,000"],
      [("Pool $10k", [2.0, 9.1, 16.7, 50.0]), ("Pool $50k", [0.4, 2.0, 3.8, 16.7]),
       ("Pool $250k", [0.1, 0.4, 0.8, 3.8]), ("Pool $1M", [0.0, 0.1, 0.2, 1.0])],
      sub="Constant-product pool, half the liquidity on each side, before fees", cap=50)}
{CALC.slippage("en")}
<p>Jupiter's automatic slippage is fine for liquid coins. For fresh tokens, a very high tolerance invites
"sandwich" bots that buy right before you and sell right after.</p>

<h2>Priority fee</h2>
<p>When Solana is busy, a small priority fee gets your transaction in sooner. For a normal swap the default is enough;
paying more only helps in the first minutes of a launch, which is also when risk is highest.</p>

<h2>Limit orders and DCA</h2>
<p>Jupiter also offers <b>limit orders</b> (buy or sell when the price reaches your level) and recurring buys
(<a href=/blog/what-is-dca-in-crypto>DCA</a>). Limit orders avoid chasing pumps; DCA spreads one decision over time.</p>

<h2>Mistakes that cost the most</h2>
<ul>
<li>Searching the token by name and picking a copy with the same logo.</li>
<li>Buying more than about 2% of the pool's liquidity in one go.</li>
<li>Approving a transaction on a site you reached from a link in a DM.</li>
<li>Spending all the SOL and having nothing left for the fee to sell.</li>
</ul>
<p>Getting SOL in the first place: <a href=/blog/best-crypto-exchanges-croatia>licensed exchanges in Croatia and the EU</a>.</p>
""", related=("how-to-buy-solana-meme-coins", "market-cap-liquidity-slippage", "what-is-dca-in-crypto"))


# 14 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "what-is-a-pump-and-dump", "Rugs",
    "What is a pump and dump in crypto? How it works and how to spot one",
    "What is a pump and dump in crypto? Signs, examples from data | MemeSonar",
    "A pump and dump is a coordinated price push followed by insiders selling into the buyers. How it works on Solana "
    "meme coins, the warning signs, and what our data shows about it.",
    ["pump and dump crypto", "what is a pump and dump", "crypto pump and dump", "pump and dump scheme"], 6,
    "A pump and dump is when a group buys a token early, pushes the price up with hype (paid calls, group chats, fake "
    "volume) and sells into the people who arrive late. Warning signs: a few wallets holding most of the supply, "
    "bundled buys at launch, many calls within minutes from accounts that never call the same coin twice, and "
    "volume that disappears after the peak.",
    f"""
<h2>How it works</h2>
<ol>
<li><b>Accumulate:</b> insiders buy cheaply, often in the same block as the launch (<b>bundles</b> and
<b>snipers</b>).</li>
<li><b>Pump:</b> they create attention: paid influencer posts, Telegram "alpha" groups, bots that trade back and forth
to fake volume.</li>
<li><b>Dump:</b> new buyers push the price up; the insiders sell into them. The chart drops faster than it rose.</li>
</ol>
<p>Unlike a <a href=/blog/how-to-spot-a-rug-pull>rug pull</a>, the liquidity usually stays; the token just goes back
to near nothing because the only real demand was the hype.</p>

<h2>What our data shows</h2>
<p>Heavily bundled tokens do pump more often (25.5% reached 2x when over 20% of the supply was bundled, against 3.6%
under 2%), which is exactly what attracts late buyers. But the fall from the top is the deepest:</p>
{bars("Typical fall from the highest price, by bundled share of supply",
      [("2-10% bundled", 17, ""), ("10-20%", 35, ""), ("Over 20%", 54, "insiders sell into the pump")],
      sub="Median maximum drawdown in the first hours, %", hl=(2,), source=RETRO)}
<p>Snipers show the same pattern: where snipers took more than 30% of the supply, the median fall from the top was 58%.</p>
<p>And many simultaneous influencer calls are not always organic: groups of three or more <b>KOL</b> calls within 15
minutes reached 2x 59% of the time versus 33% otherwise, but some groups are the same people posting from several
accounts. That is why we cluster influencers (<a href=/blog/influencer-clustering>how influencer clustering works</a>)
and exclude bot accounts.</p>

<h2>Warning signs</h2>
<ul>
<li>Top 10 wallets hold more than about 35% of the supply, or the developer wallet holds more than 5%.</li>
<li>Many buys in the first block from wallets funded by the same source.</li>
<li>A burst of posts from accounts that appear only for this coin.</li>
<li>"Last chance" urgency, countdowns, guaranteed targets.</li>
<li>Volume and holders that collapse a few hours after the peak.</li>
</ul>
<p>Every coin in our top 100 has an automatic check of these numbers, for example
<a href=/rug-check/wif>is WIF safe?</a></p>

<h2>Is it illegal?</h2>
<p>In the EU, MiCA explicitly bans market manipulation in crypto-assets, including spreading misleading information to
move a price. Enforcement on anonymous on-chain projects is hard, so in practice protecting yourself is your job: small
size, a clear exit, and no buying because a chat says "now".</p>
""", related=("how-to-spot-a-rug-pull", "bundles-and-snipers", "influencer-clustering"))


# 15 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
CARD_SRC = "issuers' card pages and fee schedules, jeangalea.com (6 Oct 2026), cardpilled.com (verified 22 Sep 2026)"
TAX_SRC = "Porezna uprava opinion 410-01/17-08/29 (19 Mar 2018), Porezna uprava JOPPD notice, top7.hr (29 Sep 2026)"
post(
    "crypto-cards-croatia", "Cards",
    "Crypto cards in Croatia (2026): which ones work, what they cost, and the tax catch",
    "Best crypto cards in Croatia 2026: Revolut, Crypto.com, Bybit, Bitpanda compared | MemeSonar",
    "Which crypto debit cards can you use in Croatia in 2026? Revolut, Crypto.com, Bybit EU, Bitpanda, Kraken and OKX "
    "compared by licence, fees and cashback, plus why every card payment is a crypto sale.",
    ["crypto card croatia", "crypto debit card europe", "best crypto card", "kripto kartica"], 7,
    "Croatia is in the euro area and the EEA, so the EU crypto cards work here: Revolut's crypto card, Crypto.com Visa, "
    "the Bybit EU card, the Bitpanda Card, Kraken's Krak card and the OKX card, all from MiCA-licensed companies. Free "
    "tiers pay 0-1% cashback; bigger rewards need staking or a subscription. The catch: every card payment sells crypto "
    "for euros, which counts as a sale for Croatian tax (12% on the gain if you held it under two years).",
    f"""
<h2>How a crypto card works</h2>
<p>A crypto card is a normal Visa or Mastercard debit card. When you pay, the card company sells the needed amount of
your crypto (or stablecoin) for euros at that moment and the shop receives euros. The shop never sees crypto, so the
card works anywhere cards are accepted, including Croatian shops and ATMs.</p>
<p>That conversion is where the cost hides: a <b>spread</b> or conversion fee of roughly 0-1% on each payment, on top of
any monthly fee.</p>

<h2>Cards you can get in Croatia</h2>
<p>We list only cards from companies with an EU MiCA licence (see <a href=/blog/best-crypto-exchanges-croatia>which
exchanges are licensed</a>). Terms change often; check the issuer's fee page before ordering.</p>
<div class=tw><table><thead><tr><th>Card</th><th>Company / licence</th><th>Monthly fee</th><th>Cashback on the free tier</th><th>Good to know</th></tr></thead><tbody>
<tr><td><b>Revolut crypto card</b></td><td>Revolut, MiCA via CySEC</td><td>Your Revolut plan</td><td>None</td><td>Virtual since 2025, physical since May 2026; converts at payment, plan-dependent fair-usage fees</td></tr>
<tr><td><b>Crypto.com Visa</b></td><td>Crypto.com, MiCA via MFSA (Malta)</td><td>€0 (Midnight Blue)</td><td>None</td><td>1.5% on Ruby Steel (€3.99/month or CRO lockup); top tiers need large CRO stakes</td></tr>
<tr><td><b>Bybit EU Card</b></td><td>Bybit EU GmbH, MiCA via FMA (Austria)</td><td>€0</td><td>1% (in BTC)</td><td>Mastercard; higher rates only for VIP tiers, with monthly caps</td></tr>
<tr><td><b>Bitpanda Card</b></td><td>Bitpanda, MiCA</td><td>€0</td><td>Up to 1% (in the crypto used)</td><td>Visa, euro area</td></tr>
<tr><td><b>Krak card (Kraken)</b></td><td>Kraken, MiCA via Central Bank of Ireland</td><td>€0</td><td>Up to 2% (with conditions)</td><td>UK and EEA</td></tr>
<tr><td><b>OKX Card</b></td><td>OKX, MiCA via MFSA (Malta)</td><td>€0</td><td>2%+ in stablecoin, monthly cap</td><td>Spends a stablecoin balance, not your other coins</td></tr>
</tbody></table></div>
<p class=mut>No longer available in the EEA: the Binance Card (ended December 2023). Sources: {CARD_SRC}.</p>
{bars("Cashback on the free tier",
      [("Krak (Kraken)", 2.0, "up to, with conditions"), ("Bybit EU Card", 1.0, "all cardholders, no monthly cap"),
       ("Bitpanda Card", 1.0, "up to, paid in the crypto you spend"), ("Crypto.com Visa (Midnight Blue)", 0, "1.5% from €3.99/month"),
       ("Revolut crypto card", 0, "no cashback")],
      sub="Percent of each payment, before conversion fees; cashback is often paid in a token whose price moves",
      fmt="pct2", hl=(0, 1, 2), vmax=2.5, source=CARD_SRC)}

<h2>The tax catch: every payment is a sale</h2>
<p>For Croatian tax, the card company exchanging your crypto for euros is the same as you selling it. If you bought the
coins less than two years ago and they are worth more than you paid, each payment creates a small taxable gain
(12% on the gain, reported once a year by the end of February). Coins held longer than two years are exempt.</p>
{stats([("€1,000", "BTC bought in March 2026"), ("€1,500", "spent with a crypto card in October 2026"),
        ("€60", "tax: 12% of the €500 gain")])}
<p>Paying with a stablecoin you bought for euros creates almost no gain. Our <a href=/blog/crypto-tax-croatia>Croatian
crypto tax guide</a> has the full rules, and every card app lets you export a transaction history; keep it.</p>

<h2>Which one to pick</h2>
<ul>
<li><b>You already use Revolut:</b> the simplest, no new account, but no cashback.</li>
<li><b>You want cashback without staking:</b> Bybit EU (1% flat) or Bitpanda (up to 1%).</li>
<li><b>You want to spend stablecoins:</b> OKX or a card that lets you choose USDC as the source, which keeps the tax
side simple.</li>
<li><b>You hold long-term:</b> don't spend coins you plan to keep past two years; spending them early turns a tax-free
gain into a taxed one.</li>
</ul>
<p class=mut>We have no affiliate links and no payment from any card issuer. Not financial or tax advice.</p>
""", related=("best-crypto-exchanges-croatia", "crypto-tax-croatia", "how-to-buy-solana-meme-coins"))


# 16 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "crypto-tax-croatia", "Tax",
    "Crypto tax in Croatia (2026): 12%, the two-year rule and how to file JOPPD",
    "Crypto tax in Croatia 2026: 12% rate, two-year rule, JOPPD step by step | MemeSonar",
    "How crypto is taxed in Croatia: 12% on gains, tax-free after two years, crypto-to-crypto swaps not taxed, losses "
    "within the year, and how to file the JOPPD form by the end of February. With examples.",
    ["crypto tax croatia", "porez na kriptovalute", "croatia capital gains tax crypto", "joppd kriptovalute"], 8,
    "In Croatia, profit from selling crypto is taxed at 12% (no surtax since 2024), only when you exchange it for euros "
    "or other money and only if you held it less than two years. Swapping one coin for another is not taxed. You "
    "calculate the year's net gain yourself (FIFO, minus fees and same-year losses), report it on the JOPPD form in "
    "ePorezna and pay by the end of February of the next year.",
    f"""
<h2>The rules in one table</h2>
<div class=tw><table><thead><tr><th>Question</th><th>Answer for individuals</th></tr></thead><tbody>
<tr><td>Tax type</td><td>Income from capital (capital gains)</td></tr>
<tr><td>Rate</td><td><b>12%</b> on gains from 2024 on; no surtax (prirez). Before 2024: 10% plus surtax</td></tr>
<tr><td>Held more than two years</td><td>Tax-free, whatever the amount</td></tr>
<tr><td>Crypto swapped for crypto</td><td>Not taxed at the swap; the gain is counted when you exchange for money</td></tr>
<tr><td>Crypto sold for euros, or spent with a crypto card</td><td>Taxable if there is a gain</td></tr>
<tr><td>Just buying or holding</td><td>Not taxed</td></tr>
<tr><td>Losses</td><td>Offset gains in the same calendar year only; no carry-forward</td></tr>
<tr><td>Cost method</td><td>FIFO, each coin tracked separately; exchange and network fees reduce the gain</td></tr>
<tr><td>Form and deadline</td><td>JOPPD in ePorezna, filed and paid by the end of February for the previous year</td></tr>
<tr><td>Small amounts</td><td>No filing if the tax would be €2 or less (a gain up to about €16.70)</td></tr>
</tbody></table></div>
<p class=mut>Sources: {TAX_SRC}. The 2018 opinion predates later law changes (rate, surtax), so check current
Porezna uprava guidance or an adviser for your case.</p>

<h2>Examples</h2>
{bars("Tax due on a €5,000 gain",
      [("Sold for euros after 8 months", 600, "12% of €5,000"),
       ("Sold for euros after 26 months", 0, "held over two years: exempt"),
       ("Swapped into another coin, not cashed out", 0, "no money received yet"),
       ("€5,000 gain and €2,000 loss in the same year", 360, "12% of the €3,000 net gain")],
      sub="Individuals, Croatian tax resident", fmt="eur", hl=(0, 3), source=TAX_SRC)}

{CALC.tax("en")}

<h2>Swaps: the rule that matters for meme coins</h2>
<p>Porezna uprava's opinion is that exchanging one cryptocurrency for another does not create a taxable gain at that
moment, because no money changes hands. Its example: 10 BTC bought for $6,000, swapped for ETH, later sold for $35,400:
the taxable gain of $29,400 is counted when the ETH is sold for money. For a Solana trader this means SOL to meme coin
and back to SOL is not taxed until you cash out to euros, but you still need the records to calculate the gain then.</p>

<h2>How to calculate the gain</h2>
<ol>
<li>Export every buy, sell and swap from each exchange and wallet for the year.</li>
<li>For each sale for money, take the cost of the oldest coins first (<b>FIFO</b>).</li>
<li>Gain = sale amount minus cost minus fees. Add all gains, subtract all losses of the same year.</li>
<li>Skip coins held longer than two years; they are exempt.</li>
<li>Tax = 12% of the net gain.</li>
</ol>

<h2>How to file JOPPD</h2>
<ol>
<li>Log in to <b>ePorezna</b> (with e-Građani credentials) and open a new JOPPD form.</li>
<li>Fill it in for the previous year's total capital gains, dated 31 December of that year.</li>
<li>Submit and pay the tax to the account shown, by the end of February (for 2026 gains: end of February 2027).</li>
<li>Keep the exports and your calculation; the tax office can ask for them.</li>
</ol>
<p>Since 2026 EU rules (DAC8) require crypto service providers to collect and report their customers' transactions to
tax authorities, so cross-checks will become routine.</p>

<h2>Other income</h2>
<p>Crypto earned from mining, tasks or promotions is not a capital gain: Porezna uprava treats it as "other income"
(drugi dohodak), taxed differently, and regular mining as a business may need a registered activity. Staking rewards
are not covered by a published opinion; ask before you file. For companies the rules are completely different, see
<a href=/blog/company-crypto-investment-croatia>can a company invest in crypto in Croatia</a>.</p>
<p class=mut>Not tax advice. Rules and forms change; confirm with Porezna uprava or a tax adviser.</p>
""", related=("crypto-cards-croatia", "company-crypto-investment-croatia", "best-crypto-exchanges-croatia"))


# 17 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
CO_SRC = ("Zakon o porezu na dobit (10%/18%), dividend tax 12% since 2024, HSFI 5/10 and MRS 38/2 treatment as described "
          "by Kopun Group and Data-Link Unija, Porezna uprava VAT opinion (2015)")
post(
    "company-crypto-investment-croatia", "Business",
    "Can a company invest in crypto in Croatia? d.o.o., obrt, tax and accounting",
    "Can a Croatian company (d.o.o.) invest in crypto? Tax, accounting, banks | MemeSonar",
    "Yes, a Croatian d.o.o. can buy crypto with its own money. How it is booked (HSFI 5 or 10), taxed (10% or 18% "
    "profit tax, no two-year exemption), VAT, banks, and when holding privately is cheaper.",
    ["can a company invest in crypto", "business crypto account", "d.o.o. kriptovalute", "company crypto tax croatia"], 8,
    "A Croatian d.o.o. may invest its own money in crypto; no MiCA licence is needed unless it offers crypto services to "
    "others. It books crypto as an intangible asset (long-term) or inventory (trading), at cost, and pays profit tax "
    "(10% or 18%) on gains when it sells. There is no two-year exemption, and taking the profit out as a dividend adds "
    "12%, so for a long-term holder, owning crypto privately is usually cheaper.",
    f"""
<h2>Is it allowed?</h2>
<p>Yes. MiCA regulates companies that provide crypto services to others (exchanges, custody, advice). A company buying
crypto for its own balance sheet is an investor, like buying shares, and needs no licence. It does need a licensed
exchange (see <a href=/blog/best-crypto-exchanges-croatia>licensed exchanges</a>) that opens business accounts; the
large ones (Kraken, Coinbase, Bitstamp, Bitpanda) have business onboarding with company documents and beneficial owner
checks.</p>

<h2>How it is booked</h2>
<div class=tw><table><thead><tr><th>Purpose</th><th>Standard</th><th>Measured at</th><th>Price falls below cost</th><th>Price rises</th></tr></thead><tbody>
<tr><td>Long-term holding</td><td>Intangible asset: HSFI 5 / MRS 38</td><td>Cost (or revaluation model)</td><td>Impairment expense, not tax-deductible until sold</td><td>Nothing until sold (cost model)</td></tr>
<tr><td>Trading</td><td>Inventory: HSFI 10 / MRS 2</td><td>Lower of cost and net realisable value</td><td>Write-down, not tax-deductible until sold</td><td>Stays at cost</td></tr>
</tbody></table></div>
<p>Crypto is not cash and not a financial asset for accounting purposes. Choose the policy before the first purchase,
keep every exchange confirmation, and use FIFO for the cost of what you sell.</p>

<h2>How it is taxed</h2>
<ul>
<li><b>Profit tax</b> on the gain when sold: 10% if the company's annual revenue is up to €1 million, 18% above.</li>
<li><b>No two-year exemption.</b> That rule is only for individuals.</li>
<li><b>VAT:</b> buying and selling crypto for money is VAT-exempt (Porezna uprava 2015, in line with the EU Court's
Hedqvist ruling). If the company accepts crypto as payment for its own goods or services, the sale itself is taxed for
VAT as usual.</li>
<li><b>Taking the money out:</b> profit paid as a dividend is taxed again at 12%.</li>
</ul>
{bars("Tax on a €10,000 crypto gain that ends up in the owner's pocket",
      [("Held privately, over two years", 0, "exempt"),
       ("Held privately, under two years", 1200, "12% capital gains tax"),
       ("d.o.o. with revenue up to €1M, then paid out", 2080, "10% profit tax, then 12% dividend tax on the rest"),
       ("d.o.o. with revenue over €1M, then paid out", 2784, "18% profit tax, then 12% dividend tax on the rest")],
      sub="Simplified: no other income or costs; amounts in euros", fmt="eur", hl=(0, 1), source=CO_SRC)}

{CALC.company("en")}

<h2>When a company still makes sense</h2>
<ul>
<li>The money is already in the company and you would pay dividend tax to take it out anyway.</li>
<li>The company trades actively and can offset gains against business costs and losses (a company can carry tax losses
forward, an individual cannot).</li>
<li>You accept crypto from customers and want to hold part of it.</li>
</ul>

<h2>What about an obrt?</h2>
<p>An obrt is taxed through its owner's income tax at the rates set by the city (roughly 15-23.6% and 25-35.4% since
2024), plus contributions, if the crypto is part of the business. A flat-rate (paušalni) obrt has no proper books for
such investments. Most obrtnici are better off holding crypto privately, where the 12% and two-year rules apply. Agree
the approach with your accountant before buying.</p>

<h2>Banks</h2>
<p>Croatian banks must check where money comes from. Expect questions when large amounts arrive from an exchange:
keep the exchange statements and the board decision to invest ready, and use the same company account for deposits and
withdrawals.</p>

<h2>Checklist before the first purchase</h2>
<ol>
<li>Board or owner decision to invest, with the amount and purpose (holding or trading).</li>
<li>Accounting policy agreed with the accountant (HSFI 5 or HSFI 10).</li>
<li>Business account at a MiCA-licensed exchange.</li>
<li>Custody plan: exchange custody or a company <a href=/glossary/multisig>multisig</a> wallet with two signers.</li>
<li>Monthly export of all transactions for the books.</li>
</ol>
<p class=mut>Not tax or legal advice; rules change and individual situations differ. Confirm with a tax adviser.
Personal crypto tax rules: <a href=/blog/crypto-tax-croatia>crypto tax in Croatia</a>.</p>
""", related=("crypto-tax-croatia", "best-crypto-exchanges-croatia", "crypto-cards-croatia"))


# 18 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "why-big-influencer-calls-are-hard-to-trade", "Influencers",
    "Why trading calls from the biggest crypto influencers is so hard (and where the edge is)",
    "Why copying big crypto influencers fails: sniper bots, priority fees, front-running | MemeSonar",
    "Big influencer calls are watched by thousands of people and sniper bots that pay higher fees to buy first. How "
    "priority fees and Jito tips work, and why rising stars leave more room.",
    ["crypto influencer calls", "front running crypto", "solana priority fee", "sniper bot solana"], 7,
    "When a famous influencer posts a token, thousands of followers and dozens of bots try to buy in the same second. "
    "Bots pay a higher priority fee or a Jito tip so the validator puts their buy first in the block; every buy ahead "
    "of you lifts the price, so you enter well above the call price and often become the exit for the bots. Lesser-known "
    "influencers with a good record (our Rising stars) are watched by fewer bots, so the price at your entry is closer "
    "to the price at the call.",
    f"""
<h2>Two kinds of influencers</h2>
<p>Our <a href=/influencers>influencer ranking</a> now has two tabs. <b>Stars</b> are the most famous accounts
(100,000+ followers, names like Murad or Ansem): their posts move the market, but everyone sees them at the same
moment. <b>Rising stars</b> are lesser-known accounts with a measured record: harder to find, followed by fewer
people, and that is exactly why their calls can still be traded.</p>
<p>Calls do matter: in our measurements 52% of tokens called by a measured <b>KOL</b> reached 2x, against 14% of
tokens without a call. The question is not whether a call moves the price, but who gets the move.</p>

<h2>What happens in the first second after a big call</h2>
<ol>
<li>The post appears. Bots that watch the account parse the ticker or contract address in milliseconds.</li>
<li>They send buy transactions with a high <b>priority fee</b> or a Jito tip.</li>
<li>Thousands of people open the post, copy the address and press buy, usually with the wallet's default fee.</li>
<li>The validator building the next block fills it with the highest bidders first. Your transaction lands behind the
bots, if it lands at all in a congested block.</li>
<li>Each buy ahead of you pushes the price up the pool's curve. The bots then sell into the crowd that is still buying.</li>
</ol>

<h2>How bots pay to go first</h2>
<p>Every Solana transaction pays a small base fee (5,000 lamports per signature, a fraction of a cent). On top of
that a sender can add a <b>priority fee</b>: a price per compute unit that tells the block producer "include me first".
When many transactions compete for the same token in the same moment, the ones paying more per compute unit are
generally scheduled first.</p>
<p>The second route is a <b>Jito tip</b>. Most Solana validators run Jito's client, which auctions "bundles": a group of
transactions that executes together, in a fixed order, only if the tip is paid. A bot can bundle its buy right after
the influencer's own transaction or right before a wave of buys, which is <a href=/glossary/front-running>front-running</a>.
Paying a few dollars of tip is cheap when the bot expects to sell to thousands of buyers seconds later.</p>
<p>That is why "being fast" on a big call is not a human game: a person reading X cannot outbid software that reacts in
milliseconds and pays for its place in the block.</p>

<h2>What it costs you to be behind the bots</h2>
{bars("Your entry price above the call price, by place in the block",
      [("1st (the fastest bot)", 0, "pays the call price"), ("After 5 bots", 10.3, ""), ("After 10 bots", 21, ""),
       ("After 20 bots", 44, "typical retail position on a big call"), ("After 40 bots", 96, "")],
      sub="Model: each bot buys $500, pool with $100k of liquidity, constant-product curve", hl=(3, 4),
      source="MemeSonar calculation")}
<p>In a constant-product pool, each buy lifts the price for the next one. Try your own numbers:</p>
{CALC.queue("en")}
<p>With 20 bots buying $500 each in a pool with $100k of liquidity, the price is already about 44% higher when your
buy executes. If the bots then sell back to the call price, you are down about 31% without the token having done anything.
Same logic as <a href=/blog/bundles-and-snipers>bundles and snipers</a> at launch: tokens where snipers took more than
30% of the supply fell 58% from the top in the median case.</p>

<h2>Why rising stars leave more room</h2>
<ul>
<li><b>Fewer bots watch them.</b> Sniper bots follow the accounts with the most reach; a 15,000-follower account with a
good record is rarely on their list.</li>
<li><b>Smaller crowd, smaller first wave.</b> Your buy is not competing with thousands of others in the same block.</li>
<li><b>Measured, not famous.</b> We rank them by hit rate, median peak, rug rate and late calls, not by follower count.</li>
<li><b>Agreement still matters.</b> When three or more measured influencers call the same token within 15 minutes,
59% reached 2x versus 33% otherwise (<a href=/blog/influencer-clustering>influencer clustering</a>).</li>
</ul>

<h2>If you still want to trade a Star's call</h2>
<ul>
<li>Don't chase the first minute. Wait for the first wave of bots to sell, then decide on the chart.</li>
<li>Set a maximum price before you buy, for example no more than 30% above the price at the call.</li>
<li>Keep the buy under about 2% of the pool's liquidity (<a href=/blog/how-to-use-jupiter-swap>Jupiter settings</a>).</li>
<li>A higher priority fee helps you land, but it does not get you ahead of Jito bundles.</li>
</ul>
<p>Members see both tabs live, with every call measured within minutes and copy-trading on the influencers that hit.</p>
""", related=("what-is-a-kol-in-crypto", "influencer-clustering", "bundles-and-snipers"))


# Posts added on 1 November 2026 live in their own module (sources noted per figure).
from ui import blogposts_nov  # noqa: E402,F401
