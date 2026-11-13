"""Five posts from the SEO plan of 7 November 2026 (English), added 9 November 2026.

Unlike the November-1 posts, these use MemeSonar's own measurements, taken from a copy of the database on
8 November 2026 and said so in the text. Every claim about an account or a channel points to the live pages
(/influencers, /telegram-channels), which carry the current numbers; the posts never name an account as
profitable, because on 8 November no account passed the honesty tests described in them.
"""
from ui.blogposts import post
from ui.blogviz import bars, stats

D = "2026-11-09"

# 1 ────────────────────────────────────────────────────────────────────────
post(
    "best-crypto-telegram-channels", "Telegram",
    "Best crypto Telegram channels in 2026: ranked by what their calls did, not by members",
    "Best crypto Telegram channels 2026, ranked by measured hit rate | MemeSonar",
    "We measure every token call posted in 1,900 crypto Telegram channels: price 1 hour and 24 hours later, rugs. "
    "Here is how the ranking works and why most 'best channels' lists are wrong.",
    ["best crypto telegram channels", "crypto telegram channels", "crypto signal telegram channel",
     "telegram crypto group"], 7,
    "A crypto Telegram channel is only as good as what the price did after its calls. We track 1,916 call channels "
    "and measure every post with a contract address the same way we measure an influencer on X: 1 hour later, 24 "
    "hours later, and whether the token rugged. The ranking lives on our Telegram channels page and changes daily; "
    "this post explains the method and what the first weeks of data say.",
    f"""
<h2>Why member counts and screenshots are useless</h2>
<p>Every "best crypto Telegram channels" list you find ranks by members or by the admin's own screenshots of winners.
Neither tells you what happened to the people who bought on the call. A channel with 80,000 members and a 1,000 %
screenshot can lose money on nine calls out of ten; the screenshot is the tenth.</p>
<p>We do the boring thing instead. Our bot reads the public t.me pages of call channels, pulls every post with a
Solana <a href=/glossary/contract-address>contract address</a>, and measures the token's price 1 hour and 24 hours
after the post, plus whether it fell 90 % or more (a <a href=/glossary/rug-pull>rug</a>). The same measurement we
run on every <a href=/glossary/kol>KOL</a> on X.</p>

<h2>What the first weeks of data say</h2>
{bars("Telegram call posts in our database (8 Nov 2026)", [
    ("Posts with a contract address", 40772, "from 1,916 channels"),
    ("Posts by alert bots (templates)", 36600, "same text for every new token, excluded from any score"),
    ("Calls with a measured outcome", 2194, "measurement was starved by other jobs until 8 Nov"),
], sub="count", fmt="num", hl=(2,), source="MemeSonar kol.db, copy of 8 Nov 2026")}
<p>Two things stand out. First, almost half of everything posted with a contract address comes from
<a href=/glossary/bot-account>alert bots</a>: scanner templates that fire on every new token. They are not calls and
we drop them before any channel is scored. Second, only 5 % of real Telegram calls had a measured outcome on 8
November, because the free price-history API was shared with other jobs and the Telegram calls kept losing the
queue. That is fixed; the numbers on the channel pages fill in day by day.</p>
<p>So on 8 November we could not honestly name a single "best" channel. We say that on the pages too: a channel
gets a verdict only after 10 clean measured calls, and the list shows how many calls each verdict rests on.</p>

<h2>How to read a channel's page</h2>
<ul>
<li><b>Clean calls</b>: real call posts with a measured outcome, excluding <a href=/glossary/late-call>late calls</a>
(the price had already doubled in the 2 hours before) and calls found through searches that start from winning
tokens, which would make any channel look good.</li>
<li><b>Higher after 1 hour</b>: the share of calls where the price was above the post price an hour later. It is the
simplest thing a follower could have traded. Across all clean X and Telegram calls in our data that share is 29 %.</li>
<li><b>Reached +15 % in 24 hours</b> and <b>median 24 h result</b>: a quick spike is not a result; the median tells you
what a typical call did a day later. For all clean calls together it was −55 %.</li>
<li><b>Calls per day</b>: a channel that posts 30 contract addresses a day is a feed, not a signal. Twelve posts a
day with a 30 % <a href=/glossary/hit-rate>hit rate</a> is noise you could get from a random token list.</li>
</ul>

<h2>What a good channel would look like</h2>
<p>Higher after 1 hour well above 29 %, a median 24 h result near zero or positive, a rug share under 10 %, and no
more than a handful of calls a day, sustained over two separate months. We have not seen one yet. When we do, it will
be on the <a href=/telegram-channels>Telegram channels page</a> with the number of calls behind it, and members get
its calls live with a 24-hour head start over this public page.</p>
""", related=("memecoin-telegram-groups-explained", "how-to-check-a-kol-track-record", "what-is-a-kol-in-crypto"),
    date=D)

# 2 ────────────────────────────────────────────────────────────────────────
post(
    "top-crypto-twitter-accounts-by-call-accuracy", "Influencers",
    "Top crypto Twitter (X) accounts to follow in 2026: by call accuracy, not followers",
    "Top crypto Twitter accounts 2026, ranked by call accuracy | MemeSonar",
    "We measured 5,092 clean token calls from crypto X accounts: price higher after 1 hour in 29 % of cases, median "
    "24 h result −55 %. What 'accuracy' has to mean before you follow anyone.",
    ["best crypto twitter accounts", "top crypto twitter accounts 2026", "crypto influencers to follow",
     "crypto twitter calls"], 8,
    "Follower count says nothing about whether an account's calls make money. We measured 5,092 clean Solana token "
    "calls from X accounts: an hour after the post the price was higher only 29 % of the time and the median result "
    "after 24 hours was −55 %. Of 39 accounts with 20+ clean calls, two were positive in both halves of their "
    "history, and shuffling the outcomes at random produces one such account anyway. The live leaderboard shows who "
    "is ahead today, with the number of calls behind every figure.",
    f"""
<h2>The test most lists fail</h2>
<p>Pick any "top crypto influencers" list. It ranks by followers, by engagement or by a few famous wins. We asked a
different question: if you had bought every token an account called, at the moment it was posted, and sold an hour
later, would you have money left? That is the simplest <a href=/glossary/crypto-call>call</a> you can actually
trade; everything fancier (ladders, trailing stops) builds on it.</p>

<h2>The numbers (8 November 2026)</h2>
{stats([("5,092", "clean measured calls"), ("29 %", "price higher 1 h after the post"), ("−55 %", "median result after 24 h"), ("2 of 39", "accounts positive in both halves")])}
<p>"Clean" matters. We exclude <a href=/glossary/bot-account>bot accounts</a>, calls posted after the price had
already doubled (<a href=/glossary/late-call>late calls</a>, 10–30 % of what accounts post) and calls we found
through searches that start from tokens that already pumped: those make any account look brilliant by construction.
What is left is what a follower could really have traded.</p>
{bars("Price higher one hour after the call, by market cap at the call", [
    ("Under $50k", 25, "median 1 h result −19 %"),
    ("$50k – $200k", 30, "−18 %"),
    ("$200k – $1M", 38, "−6 %"),
    ("Over $1M", 26, "−4 %"),
], sub="share of clean calls, %", fmt="pct", hl=(2,), source="MemeSonar kol.db, 3,929 clean calls with a 1 h price")}
<p>The least bad place to follow a call is a token already worth $200k to $1M: enough <a href=/glossary/liquidity>
liquidity</a> that the caller's own followers do not move it, not so big that nothing happens. Below $50k a call is
mostly a sniper's exit.</p>

<h2>Why "100 % hit rate" accounts lose money</h2>
<p>Many trackers (ours included, until this week) counted a call as a hit when the price <i>touched</i> +50 % at any
point in 24 hours. By that measure some accounts scored 85 to 100 %. Their median result 24 hours after the call was
−84 % to −99 %. The spike is the moment the caller and the bots sell; a wick is not a trade anyone else made. On
our profile pages the <a href=/glossary/hit-rate>hit rate</a> you should look at is "higher after 1 hour", next to
"reached +15 %" and the median 24 h result, always with the number of calls.</p>

<h2>Skill or luck: the shuffle test</h2>
<p>Of 39 accounts with 20 or more clean calls, two had a positive average 1-hour result in both the first and the
second half of their history. We then shuffled all outcomes randomly across the same accounts 100 times: the median
run produced one such account, the 95th percentile three. Two is not evidence of skill. It may become evidence with
more calls, which is why every profile shows its history month by month.</p>

<h2>How to use the leaderboard</h2>
<ol>
<li>Open the <a href=/influencers>influencer leaderboard</a> and ignore followers.</li>
<li>Open a profile and read "higher after 1 h", "median 24 h" and the number of clean calls. Under 10 calls there is
no verdict and the page says so.</li>
<li>Check the month-by-month table: a good first month followed by a bad second one is the normal shape of luck.</li>
<li>Compare with the median account shown on the page. "Better than the median" still means most calls lose.</li>
<li>Members see the account's calls live and our entry rule per account; this public page is 24 hours behind.</li>
</ol>
<p>Not financial advice. Meme coins are extremely risky and most go to zero.</p>
""", related=("how-to-check-a-kol-track-record", "why-big-influencer-calls-are-hard-to-trade", "what-is-a-kol-in-crypto"),
    date=D)

# 3 ────────────────────────────────────────────────────────────────────────
post(
    "memecoin-telegram-groups-explained", "Telegram",
    "Memecoin Telegram groups: signal, whale and sniper channels explained, with numbers",
    "Memecoin Telegram groups explained: signal, whale and sniper channels | MemeSonar",
    "The three kinds of memecoin Telegram groups, how to tell them apart in five minutes, and what our measurement of "
    "40,772 call posts says about each.",
    ["memecoin telegram groups", "memecoin whale pumps telegram", "solana meme coin telegram groups",
     "free crypto signals telegram group"], 6,
    "Memecoin Telegram groups come in three kinds: signal channels (a person posts a token with a reason), whale or "
    "wallet channels (a bot posts what tracked wallets bought) and sniper or alert channels (a bot posts every new "
    "token). They need completely different reading. Alert bots were 47 % of all posts with a contract address in "
    "our data and are worthless as calls; whale channels are only as good as the wallets behind them; signal "
    "channels are the only ones a hit rate even applies to.",
    f"""
<h2>Three kinds of channel</h2>
<p><b>Signal channels</b>: a person (or a small team) posts a token, usually with a reason: a narrative, a chart, a
known developer. These are the channels a <a href=/glossary/hit-rate>hit rate</a> makes sense for, because someone
chose the token. They post a few calls a day at most.</p>
<p><b>Whale or wallet channels</b>: a bot posts "wallet X bought token Y for 40 SOL". The quality is the quality of
the wallet list behind it, which you cannot see. In our own data 1,504 of 6,792 scored wallets were profitable, and
582 of those were bots or snipers that hold a token for a median of 3 minutes; a channel relaying their buys shows
you trades that are already over.</p>
<p><b>Sniper or alert channels</b>: a bot posts every new launch, every <a href=/glossary/pump-fun>pump.fun</a>
<a href=/glossary/graduation>graduation</a>, every "paid DEX update". They post dozens to hundreds of times a day.
They are a feed, and their "calls" have the hit rate of a random token.</p>

<h2>What the data says</h2>
{bars("Telegram posts with a contract address, by kind (8 Nov 2026)", [
    ("Alert-bot templates", 36600, "scanner bots, same text for every token"),
    ("Real calls", 40772, "posts a person wrote"),
    ("Reposts / forwards", 3286, "forwarded from another channel"),
], sub="count of posts", fmt="num", hl=(0,), source="MemeSonar kol.db, 1,916 channels")}
<p>Forty-seven percent of everything with an address is a template. We detect them by shape: the same wording with
a different address, "AI signal", "migration spotted", "Liq / Holders / Top10" blocks, dozens of distinct tokens a
day. Those posts are excluded from every score on our pages.</p>

<h2>How to classify a channel in five minutes</h2>
<ol>
<li>Scroll one day back. Count the posts with addresses. More than 20 a day: it is a feed, treat it as a token list,
not as advice.</li>
<li>Read three posts. If every one has the same layout and no reason, it is a bot. If there is a reason, a person
wrote it.</li>
<li>Look at the timing. A whale channel posts "bought" after the wallet bought; by the time you read it, the wallet
is minutes from selling (median hold of profitable bots in our data: 3 minutes).</li>
<li>Check what the admin does not show: the calls that went to zero. Our <a href=/telegram-channels>channel pages</a>
show all of them, with the share that fell 90 % or more.</li>
<li>Check for <a href=/glossary/late-call>late calls</a>: a call after the price already doubled is a sell signal
dressed as a buy.</li>
</ol>

<h2>The honest expectation</h2>
<p>Across every clean call we measured on X and Telegram together, the price was higher one hour later 29 % of the
time and the median result after a day was −55 %. A memecoin group that beats that consistently is rare; one that
beats it with few calls a day and a low <a href=/glossary/rug-pull>rug</a> share is what the ranking is looking for.
Until a channel has 10 clean measured calls, our page for it says "too little data" rather than guessing.</p>
""", related=("best-crypto-telegram-channels", "bundles-and-snipers", "what-is-wallet-tracking"), date=D)

# 4 ────────────────────────────────────────────────────────────────────────
post(
    "how-to-spot-a-pump-fun-runner", "Guides",
    "How to spot a pump.fun runner in the first 10 minutes: what 129 launches show",
    "How to spot a pump.fun runner in the first 10 minutes (129 launches measured) | MemeSonar",
    "A viral X post says a pump.fun runner shows $40k market cap and $13k volume by minute 10. We checked 129 fresh "
    "launches: none did, and the two that later reached $100k looked ordinary at minute 10.",
    ["pump fun runner", "how to find runners pump fun", "pump.fun early signals", "pump fun sniping"], 7,
    "We tested the popular rule 'a runner has $40k market cap and $13k volume by minute 10' on 129 fresh pump.fun "
    "launches. Zero matched the rule. Two of the 129 later reached $100k market cap, and both were small at minute "
    "10. Copying the 'runner' wallets the post names was no better: in our wallet data their style wins 22 to 24 % of "
    "the time. What does help is waiting for graduation and a $30k+ market cap, then judging the token like any other.",
    f"""
<h2>The claim</h2>
<p>A widely shared post on X gives a recipe: a <a href=/glossary/pump-fun>pump.fun</a> token that shows $40k market
cap and $13k of volume ten minutes after launch is a "runner", and a few named wallets catch them every time. It is
the kind of rule that feels right because the runners you remember did look busy early. The question is how many
busy-looking tokens went nowhere.</p>

<h2>The test</h2>
<p>We took 129 fresh launches from the live feed over one evening, recorded market cap and volume at minute 10, and
followed each for 24 hours.</p>
{stats([("129", "fresh launches followed"), ("0", "met the $40k + $13k rule at minute 10"), ("2", "reached $100k within 24 h"), ("−9.7 %", "median 5 min after graduation, 117 tokens")])}
<p>Not one of the 129 matched the rule, so the rule would have told you to buy nothing, which is at least cheap. The
two tokens that did reach $100k had small market caps at minute 10 and nothing in their first ten minutes separated
them from the other 127. Early volume did not predict anything in this sample; this is one evening and 129 tokens,
not a law.</p>

<h2>The wallets named in the post</h2>
<p>The post names a few wallets as runner catchers. We score wallets by their own on-chain history. The style the
post describes, buying in the first minute and selling in the first ten, wins 22 to 24 % of the time in our data, with
a copy score of 2 and 12 out of 100. A wallet that trades a few hundred times a day and holds for three minutes cannot
be copied by a person two minutes behind it; by the time your buy lands, it is selling to you. More on this in our
<a href=/blog/what-is-wallet-tracking>wallet tracking guide</a>.</p>

<h2>What the data does support</h2>
{bars("Where buying a token after a call went least badly (clean calls, 1 h later)", [
    ("Under $50k market cap", 25, "mostly a sniper's exit"),
    ("$50k – $200k", 30, ""),
    ("$200k – $1M", 38, "best band in our data"),
    ("Over $1M", 26, ""),
], sub="share of calls with a higher price 1 h later, %", fmt="pct", hl=(2,), source="MemeSonar kol.db, 3,929 calls, 8 Nov 2026")}
<ol>
<li>Skip the bonding curve. Tokens under $30k are not analysed by our tool at all; the first minutes belong to
<a href=/glossary/sniper-bot>sniper bots</a> and bundles.</li>
<li>Wait for <a href=/glossary/graduation>graduation</a>, then wait again: in our 117 measured graduations the median
price five minutes after the pool opened was −9.7 %. The "buy the graduation" bot strategy lost.</li>
<li>Judge the token at $30k to $1M like any other: <a href=/glossary/liquidity>liquidity</a> to market cap, holder
spread, a dev wallet that is not selling, and who is calling it. Our <a href=/solana-meme-coins>meme coin list</a>
and the rug check on every coin page do exactly this.</li>
<li>If you still want early tokens, size for 90 % losses: most of them end at zero.</li>
</ol>
<p>Members get the live feed of graduations with the safety checks applied; this guide is the public version. Not
financial advice.</p>
""", related=("what-is-pump-fun", "bundles-and-snipers", "how-to-spot-a-rug-pull"), date=D)

# 5 ────────────────────────────────────────────────────────────────────────
post(
    "how-to-check-a-kol-track-record", "Influencers",
    "KOL in crypto: how to check a KOL's track record before you follow a call",
    "How to check a crypto KOL's track record before following a call | MemeSonar",
    "Of 6,995 crypto accounts we track, 5,192 have no measured call. A five-step check for any KOL and the traps "
    "that make bad callers look good: wick hit rates, late calls, winner-selected samples.",
    ["kol crypto", "what is a kol in crypto", "kol meaning crypto", "crypto kol track record"], 7,
    "A KOL (key opinion leader) is an account whose token calls move prices. Before you follow one, check five things: "
    "how many of their calls were actually measured, whether the hit rate counts spikes or real results, how many "
    "calls came after the pump, whether the record was built from winners only, and whether the first half of their "
    "history looks like the second. Of 6,995 accounts in our database, 5,192 have zero measured calls, so most "
    "'proven KOLs' are unproven.",
    f"""
<h2>What a KOL is</h2>
<p>In crypto a <a href=/glossary/kol>KOL</a> is an account on X or Telegram whose <a href=/glossary/crypto-call>
calls</a> make other people buy. The word says nothing about whether those buyers made money. Our earlier post
<a href=/blog/what-is-a-kol-in-crypto>explains the term</a>; this one is the checklist.</p>

<h2>Step 1: how many calls were measured?</h2>
{bars("Crypto accounts in our database, by measured calls (8 Nov 2026)", [
    ("Zero measured calls", 5192, "nothing to judge"),
    ("1 to 9 measured", 1655, "page exists, no verdict"),
    ("10 or more clean calls", 148, "verdict possible"),
], sub="accounts", fmt="num", hl=(2,), source="MemeSonar kol.db, 6,995 accounts")}
<p>Most accounts people call KOLs have never had a call measured by anyone. A screenshot is not a measurement. We
need 10 clean measured calls before a page says anything, and the page shows the count.</p>

<h2>Step 2: what does "hit" mean?</h2>
<p>If a tracker counts a call as a hit when the price touched +50 % at any moment in 24 hours, it is counting wicks.
Accounts with 85 to 100 % such hits had median 24-hour results of −84 % to −99 % in our data. Ask for "price higher
one hour later" and "median 24 h result". Those are what a follower could have had. See
<a href=/glossary/hit-rate>hit rate</a>.</p>

<h2>Step 3: how many calls came after the pump?</h2>
<p>A <a href=/glossary/late-call>late call</a> is posted after the price already doubled in the previous two hours.
Depending on the source, 10 to 30 % of measured calls are late. They are exits, not entries, and a record that
includes them is a record of other people's exits.</p>

<h2>Step 4: how was the record built?</h2>
<p>Many trackers find callers by starting from tokens that pumped and asking "who posted this first?". Every
account found that way looks good: you only ever see their winners. We tag those sources and leave them out of the
public numbers; the honest record is built from an account's whole timeline, losers included.</p>

<h2>Step 5: does the first half look like the second?</h2>
<p>Split the calls in time. Of 39 accounts with 20+ clean calls in our data, two were positive in both halves, and
random shuffling of the same outcomes gives one such account anyway. A good month followed by a bad one is the shape
of luck. The month-by-month table on every <a href=/influencers>profile</a> shows it.</p>

<h2>What to do with a KOL that passes</h2>
<ul>
<li>Follow calls on tokens between $200k and $1M market cap (the only band where the 1-hour result was not badly
negative in our data).</li>
<li>Never enter a late call; never enter under $30k.</li>
<li>Plan the exit before the entry; our demo accounts sell half at +15 % and the rest with a 15 % trailing stop.</li>
<li>Expect most calls to lose anyway: the best accounts beat the median, they do not beat gravity.</li>
</ul>
<p>Members see each account's live calls and our entry rule per account. Not financial advice.</p>
""", related=("what-is-a-kol-in-crypto", "top-crypto-twitter-accounts-by-call-accuracy",
              "why-big-influencer-calls-are-hard-to-trade"), date=D)
