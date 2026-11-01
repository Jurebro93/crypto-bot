"""The ten launch posts of the public blog (English). Numbers come from KriptoRadar's own data:

- RETRO: retrospective of 10,650 pump.fun tokens (October 2026), features at 15 min after launch, at graduation and at
  the first $100k / $1M market-cap cross; "2x" = the price later reached at least double the price at that point.
- WALLETS: snapshot of the wallet tracker on 30 Oct 2026 (469 wallets, 50 with 10+ closed trades).
- KOL: influencer calls measured by the app (price 1 h / 24 h after each call, bots excluded).
Keep numbers here in sync with the text; each post states its sample and date.
"""
from ui.blogviz import bars, grid, stats

RETRO = "KriptoRadar retrospective of 10,650 pump.fun tokens, October 2026"
WALLETS = "KriptoRadar wallet tracker, snapshot of 30 October 2026"
KOL = "KriptoRadar influencer call measurements, October 2026"

POSTS = []


def post(slug, tag, h1, title, desc, kw, mins, tldr, body, related=(), date="2026-11-01"):
    POSTS.append(dict(slug=slug, tag=tag, h1=h1, title=title, desc=desc, kw=kw, mins=mins, tldr=tldr, body=body,
                      related=related, date=date))


# 1 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "what-is-wallet-tracking", "Wallet tracking",
    "What is wallet tracking? How to track Solana wallets (and why most 'smart money' isn't)",
    "What is wallet tracking? A Solana wallet tracker guide with real data | KriptoRadar",
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
snipers and insiders. KriptoRadar adds a fourth: it checks every token a tracked wallet buys against our
<a href=/blog/how-to-spot-a-rug-pull>rug filter</a> before you see it, and it tells you when <b>several</b> good
wallets buy the same token, which matters far more than one wallet alone.</p>
<p>Next: <a href=/blog/what-is-copy-trading>what copy trading is and when it is profitable</a>.</p>
""", related=("what-is-copy-trading", "bundles-and-snipers", "how-to-spot-a-rug-pull"))


# 2 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "what-is-copy-trading", "Copy trading",
    "What is copy trading in crypto, and is it profitable?",
    "What is copy trading? Is crypto copy trading profitable? (real wallet data) | KriptoRadar",
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
    "What is a KOL in crypto? Do crypto influencer calls work? (data) | KriptoRadar",
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
    "Crypto influencer clustering: when several KOLs call one token (data) | KriptoRadar",
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
    "How to spot a rug pull on Solana: a rug checker checklist (data from 10,650 tokens) | KriptoRadar",
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
<p>All seven checks run on every token KriptoRadar shows, before you see it. Tokens that fail are hidden, not just
labelled, and every hour the system learns the profile of the rugs it caught.</p>
""", related=("bundles-and-snipers", "what-is-pump-fun", "market-cap-liquidity-slippage"))


# 6 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "what-is-pump-fun", "Basics",
    "What is pump.fun? How it works, and what our data says about your odds",
    "What is pump.fun and how does it work? Bonding curve, graduation and real odds | KriptoRadar",
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
    "Bundles and sniper bots on Solana explained (with data) | KriptoRadar",
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
<p>KriptoRadar measures bundle share, sniper share and the first buyers on every new token, and caps how much of a
heavily bundled token the system will ever buy. Read the full <a href=/blog/how-to-spot-a-rug-pull>rug checklist</a>.</p>
""", related=("how-to-spot-a-rug-pull", "what-is-pump-fun", "influencer-clustering"))


# 8 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "how-to-trade-meme-coins", "Trading",
    "How to trade meme coins: when to enter, according to 10,650 tokens",
    "How to trade meme coins on Solana: the best entry point (data from 10,650 tokens) | KriptoRadar",
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
<p>KriptoRadar's members trade with a $1,000 demo balance in a friendly league, with the same signals and rug filter
the system uses. It is the cheapest way to find out whether your plan works.</p>
""", related=("what-is-pump-fun", "market-cap-liquidity-slippage", "what-is-dca-in-crypto"))


# 9 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "what-is-dca-in-crypto", "Basics",
    "What is DCA in crypto? Dollar-cost averaging for meme coins, with a worked example",
    "What is DCA in crypto? Dollar-cost averaging explained with an example | KriptoRadar",
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

<h2>DCA in KriptoRadar</h2>
<p>Members can start an automatic DCA on any token from its page: $5 to $500 per buy, every 15 minutes to once a week,
2 to 100 buys. It stops by itself when the plan is done, the money runs out, the token is flagged as a rug or its
liquidity drops under $5,000.</p>
""", related=("how-to-trade-meme-coins", "what-is-copy-trading", "market-cap-liquidity-slippage"))


# 10 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "market-cap-liquidity-slippage", "Basics",
    "Market cap, liquidity and slippage: the three numbers to read before buying a meme coin",
    "What is slippage, liquidity and market cap in crypto? (with a slippage table) | KriptoRadar",
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
