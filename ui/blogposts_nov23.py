"""Four research posts of 23 November 2026 (English), built on the site's focus: wallets that buy before a Solana
token jumps, measured after real costs.

Every number here is MemeSonar's own measurement as of 23.11.2026, given by the tool and stated as such in the text:
statistics, never accusations, never a wallet address. Outside facts link to sources checked on 23.11.2026
(ui/blogsources.py, docs/seo/izvori_2311.md). The negative results are the point: they are what these posts add.
"""
from ui import blogsources as S
from ui.blogposts import post
from ui.blogviz import bars, stats

D = "2026-11-23"
SRC = "MemeSonar's own measurements, 23 November 2026"
RISK = ("<p class=note><b>Risk note.</b> Meme coins are extremely risky and most go to zero. Nothing here is a "
        "recommendation to buy, sell or copy anyone; the numbers describe the past and say so.</p>")
METHOD = "<a href=/blog/how-memesonar-measures>how MemeSonar measures</a>"

# a ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "wallets-that-buy-before-a-solana-token-jumps", "Wallets",
    "Wallets that buy before a Solana token jumps: what 345 pumps show",
    "Wallets that buy before a Solana token jumps: 345 pumps",
    "We read 345 Solana pumps to full depth: 47,752 early buyers, 8,273 sold into the pump, 257 repeat groups. Who "
    "they are in statistics, how groups are confirmed, and the limits.",
    ["wallets that buy before pumps", "solana early buyers", "smart money solana", "pre-pump wallets",
     "solana wallet tracker"], 8,
    "Early wallets exist, but they are not one club. In 345 Solana pumps over 180 days we found 47,752 wallets that "
    "bought before the jump; about one in six (8,273) sold into it. Only 257 groups of wallets were early in three or "
    "more pumps, and 90 of those groups were confirmed on later days. Being early is easy to see afterwards and hard "
    "to profit from: copying them is a separate test, and it did not pass.",
    f"""
<h2>The question</h2>
<p>Every Solana token that jumps leaves a public trail: the wallets that bought before the move and, often, sold
into it. "Find those wallets and follow them" is the most common advice in meme coin trading, and the idea behind
every <a href=/best-crypto-tools/wallet-trackers>wallet tracker</a>. We wanted to know how many such wallets there
really are, how many of them repeat, and whether the repeat is real or just luck. This post is the census; the
companion post <a href=/blog/does-copying-smart-wallets-pay>does copying smart wallets pay after real costs?</a>
is the money test.</p>

<h2>What we read</h2>
<p>The tool looks for pumps on tokens from about $2 million market cap upwards, with priority to pumps that reach
$15-200 million. For each pump it reads every buyer before the jump, not just the first page an explorer shows
("full depth"). On Solana this is possible because every swap is public and can be
{S.a("helius_etx", "parsed into readable buys, sells and transfers")}. Over 180 days of history that gave:</p>
{stats([("345", "pumps read to full depth"), ("47,752", "early buyers"), ("8,273", "sold into the pump")])}
{bars("The 345 pumps by the token's market cap", [
    ("$15M and above", 96, "the band where MemeSonar would consider real-money entries"),
    ("$2M to $15M", 249, "demo only"),
], sub="Number of pumps, 180 days of history", fmt="num", hl=(0,), source=SRC)}
<p>So most pumps happen on smaller tokens, where a copied buy moves the price more and costs more. Keep that in mind
when you read any "this wallet called 40 runners" screenshot.</p>

<h2>Who they are, in statistics</h2>
<p>An "early buyer" here is any wallet that bought before the jump. Most of them did nothing special: they bought,
the price later rose, and many never sold at the top. Only 8,273 of 47,752, roughly one in six, sold into the
pump. That is the group people mean by <a href=/glossary/smart-money>smart money</a>, and even inside it most
wallets appear once and never again.</p>
<p>To find skill rather than luck we look for repeats, and we count <a href=/glossary/wallet-cluster>groups of
wallets</a> rather than single addresses: several wallets funded from one source or always buying in the same
moment are one actor, not ten. Counting them as ten is exactly how a team fakes "many independent buyers".</p>
{bars("How often the same group was early", [
    ("Early in 3+ pumps", 257, "a pattern worth testing"),
    ("...of which confirmed on later days", 90, "the pattern held on pumps the selection had not seen"),
    ("Close: early in 2 pumps", 297, "watched, not yet a pattern"),
], sub="Groups of wallets, 345 pumps", fmt="num", hl=(1,), source=SRC)}
<p>"Confirmed" means the group was picked from earlier pumps only and then turned up early again in pumps that came
later. A group that is early in three pumps of the same week can be one lucky week; a group that keeps showing up
after it was picked is a better candidate. 90 groups passed that bar.</p>

<h2>Who these groups probably are</h2>
<p>We report statistics, not accusations, and we never publish wallet addresses. Still, the shapes are familiar.
Some groups buy in the launch block, which on Solana is often done with
{S.a("jito_bundles", "Jito bundles: up to five transactions that execute in order or not at all")}; that is the
<a href=/blog/bundles-and-snipers>bundle and sniper</a> pattern. Some are teams that launch tokens themselves:
research on Ethereum and BNB Chain found that {S.a("arxiv_1day", "1% of addresses created 20-25% of all tokens")}.
Some are simply fast traders. A recent study of 200,443 pump.fun launches found coordinated groups that
{S.a("arxiv_earlybuyers", "bought earlier and took out more cash than comparable wallets, while late buyers lost")}.
Our numbers point the same way.</p>

<h2>Being early is not the same as being followable</h2>
<p>A group can be genuinely early and still be useless to you. If it buys in the first block, you cannot be
earlier. If it sells into the jump within minutes, you buy what it sells. And if part of its buying is the team's
own, you are the exit. That is why the census is only half the work. In the copy test, copying these wallets 60
seconds after them looked positive on average but was not proven, and a fast 2-second copy lost money after a
realistic 1% slippage. The same study of pump.fun groups found that a follower entering at the earliest group signal
lost money out of sample in all 32 settings it tried. Details:
<a href=/blog/does-copying-smart-wallets-pay>the copy test</a>.</p>
<p>Since 19 November our demo account follows such wallets with no real money. After real costs, following
pre-pump wallets on $15-200 million tokens has 23 trades and a mean of −7.5 %; a wider list of candidates has 43
trades and +16.3 %, but a few trades carry that mean, so it says little yet.</p>

<h2>Limits</h2>
<ul>
<li><b>Survivorship.</b> We start from tokens that jumped. Wallets that bought early into tokens that never jumped
are not in this census, which makes early buying look better than it is.</li>
<li><b>Groups are inferred.</b> Shared funding and timing are strong hints, not proof that one person owns the
wallets. Some groups will be wrong, in both directions.</li>
<li><b>180 days.</b> Patterns in meme coins change quickly; a group confirmed in October may stop in December.</li>
<li><b>Own measurements.</b> These are the tool's own counts as of 23 November 2026; we explain the rules in
{METHOD}.</li>
</ul>

<h2>What to do with this</h2>
<p>If you track wallets, track groups and count repeats on days after you picked them, as described in
<a href=/blog/what-is-wallet-tracking>what wallet tracking is</a>. Check that a wallet's "buy" was a buy and not
<a href=/blog/tokens-sent-to-kol-wallets>a token sent to it for free</a>. And treat any wallet list, ours included,
as a list of candidates to test, not a list of trades to copy.</p>
{RISK}
""",
    related=("does-copying-smart-wallets-pay", "how-memesonar-measures", "what-is-wallet-tracking"), date=D)

# b ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "does-copying-smart-wallets-pay", "Copy trading",
    "Does copying smart wallets pay after real costs? Our test",
    "Does copying smart wallets pay after real costs? Our test",
    "We copied pre-pump Solana wallets on history with real delay, cost and missed buys: +29.7% mean at 60 s, but "
    "an interval from -12.9% to +114.3%. Not proven. Here is why.",
    ["copy trading solana", "copy smart money wallets", "does copy trading work", "copy trading backtest",
     "solana copy trading profitable"], 8,
    "Not proven. Copying pre-pump wallets 60 seconds after their buy averaged +29.7 % per copy on history, but the 95 % "
    "interval runs from −12.9 % to +114.3 % across 1,219 copies, and 34.8 % of their buys could not be copied at all. "
    "A fast 2-second copy lost −7.6 % on average after an assumed 1 % slippage. MemeSonar's verdict: not good enough "
    "for real money.",
    f"""
<h2>The claim we tested</h2>
<p>"Copy the wallets that buy before pumps" sounds like free money: <a href=/blog/wallets-that-buy-before-a-solana-token-jumps>the
wallets exist</a>, their trades are public, and copy bots can mirror them in seconds. The question is whether you,
arriving after them and paying your own costs, keep any of their edge. A test that answers it honestly has to copy
the way a real follower would. Ours does four things most backtests skip.</p>
<ol>
<li><b>Selection from the past only.</b> A wallet is chosen using pumps before the day of the copy. Picking wallets
with the whole history, then "copying" them on that same history, is looking into the future.</li>
<li><b>Delay.</b> You see their buy, then you buy. We test 60 seconds and 2 seconds.</li>
<li><b>Real cost.</b> The trading cost is subtracted from every copy; on meme coins we never assume a total cost
below 3 %.</li>
<li><b>Missed buys counted.</b> When a buy could not have been copied, it stays in the count as missed instead of
quietly disappearing.</li>
</ol>
<p>The full rules are in {METHOD}.</p>

<h2>The result</h2>
{bars("Copying pre-pump wallets on history: mean result per copy", [
    ("Copy 60 s after them", 29.7, "95% interval -12.9% to +114.3%, n = 1,219, 34.8% of buys missed"),
    ("Random early buyers (control)", 2.7, "interval -22.4% to +45.0%, n = 49"),
    ("Entry when token already had $15M+ market cap", -3.3, "interval -7.3% to +1.6%, n = 41"),
    ("Fast copy, 2 s, assumed 1% slippage", -7.6, "interval -9.3% to -5.7%, n = 1,202"),
], sub="Mean % per copied buy after real costs; hover a bar for the interval", fmt="pct", hl=(0,), source=SRC,
    vmax=30)}
<p>The bar for negative values is drawn at the minimum width; read the numbers, not the bar lengths.</p>

<h2>Why +29.7 % is not proof</h2>
<p>A mean is one number; the interval says how sure we can be about it. A 95 % interval is the range in which the
true average plausibly lies, given how much the individual results scatter
({S.a("nist_ci", "NIST: the narrower the interval, the more precise the estimate")}). Here the range goes from a loss
of 12.9 % to a gain of 114.3 %. That width comes from meme coin returns themselves: most copies lose a little or a
lot, and a handful of huge winners lift the average. Remove a few of them and the mean can turn negative. When the
interval includes zero, the honest reading is "we cannot tell this apart from no edge".</p>
<p>Two more things weaken it. A third of the buys (34.8 %) could not be copied at all, and in real life those are
often the best ones, because the price ran before anyone could follow. And the random control, early buyers picked
without any skill filter, also shows a positive mean (+2.7 %) with an interval from −22.4 % to +45 %: being early on
a token that later jumped looks good in hindsight whoever you are.</p>

<h2>Speed does not fix it</h2>
<p>The intuitive fix is to copy faster. The 2-second copy is the most precise result in the test (1,202 copies, the
interval from −9.3 % to −5.7 % does not touch zero) and it is clearly negative. When many bots copy the same wallet,
they compete for the same block; the ones that pay a higher
{S.a("helius_pf", "priority fee per compute unit")} go first and the rest buy higher. An assumed 1 % slippage is
enough to turn the copy into a steady loss. Entering only on bigger tokens ($15 million and up) is cheaper to execute
but left nothing: −3.3 %, interval −7.3 % to +1.6 %, on only 41 copies.</p>
<p>Independent research found the same. In a study of 200,443 pump.fun launches, a follower entering at the earliest
signal of a wallet group {S.a("arxiv_earlybuyers", "lost money out of sample in all 32 configurations")} and did no
better than random entry. Jupiter's own risk page makes the general point: when you copy a wallet
{S.a("jup_risks", "you trade later, at your own price, and its past results do not predict yours")}.</p>

<h2>What the demo says so far</h2>
<p>Since 19 November a demo account follows these wallets live, with no real money and net of real costs:</p>
{bars("Demo following since 19 November 2026", [
    ("Candidates (wider list)", 16.3, "n = 43; a few trades carry the mean"),
    ("Older insider list", -7.7, "n = 73"),
    ("Pre-pump wallets on $15-200M tokens", -7.5, "n = 23"),
    ("Copying 'proven' wallets", -10.1, "n = 30"),
], sub="Mean % per trade after real costs", fmt="pct", hl=(0,), source=SRC, vmax=17)}
<p>Four days and a few dozen trades per list are too few to conclude anything, and the one positive list is carried
by a few trades. We show it because hiding the early numbers is how track records get cherry-picked.</p>

<h2>What would count as proof</h2>
<ul>
<li>The same out-of-sample test (selection from the past, delay, real cost, missed buys counted) with a mean above
zero <b>and</b> a 95 % interval whose lower end is above zero.</li>
<li>Clearly better than the random control, not just positive.</li>
<li>Holding on later days the selection never saw, in the demo, not only on history.</li>
</ul>
<p>Until all three hold, MemeSonar does not copy wallets with real money; that takes a deliberate manual switch,
and only after the test passes. If you use a <a href=/best-crypto-tools/copy-trading-platforms>copy trading tool</a>,
ask it for the same three things. Most cannot answer.</p>
{RISK}
""",
    related=("wallets-that-buy-before-a-solana-token-jumps", "how-memesonar-measures", "what-is-copy-trading"), date=D)

# c ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "do-solana-meme-coins-follow-bitcoin", "Market",
    "Do Solana meme coins follow Bitcoin? 201 days of data",
    "Do Solana meme coins follow Bitcoin? 201 days of data",
    "Median correlation of a tracked meme coin's daily move with BTC: 0.28 over 201 days. Jumps by BTC regime, "
    "launchpad volume on 23 November and why the list is biased.",
    ["do meme coins follow bitcoin", "meme coin bitcoin correlation", "solana meme coins market", "btc correlation",
     "meme coin season"], 7,
    "Only loosely. Over 201 days the median correlation between a tracked Solana meme coin's daily move and Bitcoin's "
    "was 0.28 (197 tokens), and 17 tokens often moved against the market. Jumps were more frequent on red Bitcoin days "
    "(1.61 per 100 token-days) than on green ones (0.61), but our token list is biased toward recent jumpers, so this "
    "is not a reason to buy when Bitcoin falls.",
    f"""
<h2>Why ask</h2>
<p>Most crypto traders check Bitcoin before anything else. If BTC drops, they assume everything drops. For large
coins that is roughly true; for meme coins the link is weaker than people think, and the useful question is not "do
they follow" but "how much, and what changes when BTC moves". Research on large coins already found that crypto
returns have {S.a("nber_crypto", "little exposure to stock-market and macro factors and are driven by crypto-specific momentum and attention")}. Meme coins push that further.</p>

<h2>What we measured</h2>
<p>The tool tracks a list of Solana meme coins every day and labels each day by Bitcoin's move as green, sideways or
red. Over 201 days:</p>
{bars("Bitcoin days by regime", [
    ("Green", 42, "BTC up"), ("Sideways", 99, "BTC roughly flat"), ("Red", 59, "BTC down"),
], sub="Number of days out of 201", fmt="num", hl=(1,), source=SRC)}
{stats([("0.28", "median correlation with BTC (197 tokens)"), ("17", "tokens often moved against the market"),
        ("285 / 123", "jumps / drops detected")])}
<p>A correlation of 0.28 means BTC explains only a small part of a typical meme coin's daily move. 1.0 would be
moving in lockstep, 0 no relation at all. Seventeen tokens often went the other way from the market. So "BTC is up,
my meme coin will be up" is a weak rule.</p>

<h2>Jumps by Bitcoin regime</h2>
{bars("Jumps per 100 token-days", [
    ("Green BTC day", 0.61, ""), ("Sideways BTC day", 0.79, ""), ("Red BTC day", 1.61, "see the bias warning below"),
], sub="How often a tracked token jumped, by the day's BTC regime", fmt="num", hl=(2,), source=SRC)}
<p>At first sight jumps were more than twice as frequent on red days. <b>Do not read this as a buy signal.</b> The list
of tracked tokens is biased toward tokens that jumped recently, because that is how many of them got onto the list.
A recent jumper on a red day is still in the sample; a token that faded on the same day may never have been added.
Bitcoin's regime and the list's selection are tangled together, and 201 days include only 59 red days. What the
number does support is the weaker point: meme coin jumps are not confined to good Bitcoin days.</p>

<h2>Where the money is today</h2>
<p>The other thermometer is volume: how much is actually traded on Solana and where. Snapshot of 23 November 2026,
24 hours, compared with each venue's 7-day average:</p>
{bars("Solana DEX volume by venue, 24 h (23 November 2026)", [
    ("Orca", 149.9, "-32% vs 7-day average"), ("PumpSwap", 109.8, "-39%"), ("Meteora", 108.3, "-35%"),
    ("Raydium", 103.7, "-34%"), ("pump.fun (bonding curve)", 83.4, "-6%"),
], sub="US$ millions; total Solana DEX volume $1.12B (-19% vs its 7-day average)", fmt="num", hl=(4,),
    source=SRC)}
<p>Total Solana DEX volume was $1.12 billion, 19 % below its 7-day average, and the whole Solana meme sector was worth
$1.89 billion. Interesting detail: volume on the pump.fun bonding curve, where brand-new coins trade before they
{S.a("pump_fees", "graduate to PumpSwap")}, fell only 6 %, while the big pools fell by a third. Trading on new coins held up while
trading in the big pools on {S.a("meteora_docs", "Meteora")} and {S.a("orca_docs", "Orca")} cooled. New-coin activity is the
part least tied to Bitcoin, and also the part with the most rugs; see
<a href=/blog/what-is-pump-fun>what pump.fun is and what your odds are</a>.</p>
<p>Live numbers: <a href=/solana-market>Solana market today</a> and the
<a href=/meme-coin-season-index>meme coin season index</a>.</p>

<h2>What to do with it</h2>
<ul>
<li>Use Bitcoin as a risk thermometer, not a signal. A sharp BTC drop matters for stops and position size; it does
not predict which meme coin jumps.</li>
<li>Watch launchpad and DEX volume next to BTC. When volume dries up, exits get more expensive, whatever BTC does
(<a href=/blog/market-cap-liquidity-slippage>slippage explained</a>).</li>
<li>Remember who loses in crashes. After the 2022 crashes the BIS found that
{S.a("bis_69", "large holders sold while small retail investors bought, and most app users lost money")}.</li>
</ul>

<h2>Three mistakes this data warns against</h2>
<ol>
<li><b>Selling every meme coin when BTC dips.</b> With a median correlation of 0.28, a red Bitcoin day says little
about a single token. A stop based on the token's own price and liquidity tells you more than Bitcoin's candle.</li>
<li><b>Buying because BTC is red.</b> The higher jump rate on red days comes with a biased list, so a rule built on it
would be testing how the list was filled, not the market. Any such rule would have to pass the same out-of-sample
test as everything else we publish.</li>
<li><b>Ignoring volume.</b> A 39 % drop in PumpSwap volume against its weekly average means fewer buyers for whatever
you need to sell. Quiet pools mean more slippage on the way out, whatever Bitcoin does.</li>
</ol>
<p>We do not name the 17 tokens that often moved against the market. Moving the other way over 201 days is a fact
about the past, not a hedge you can rely on next month.</p>

<h2>Limits</h2>
<p>The token list is not random and is biased toward recent jumpers; correlations of daily moves hide what happens
inside a day; and 201 days is one market phase. The volume snapshot is one day. Method and definitions:
{METHOD}.</p>
{RISK}
""",
    related=("how-to-trade-meme-coins", "what-is-pump-fun", "how-memesonar-measures"), date=D)

# d ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
post(
    "how-memesonar-measures", "Method",
    "How MemeSonar measures: costs, delays, missed trades and intervals",
    "How MemeSonar measures: costs, delays and intervals",
    "The rules behind every MemeSonar number: real costs of at least 3%, copy delays, missed trades counted, "
    "out-of-sample selection and 95% intervals. Plus what we never publish.",
    ["memesonar methodology", "backtest crypto honestly", "out of sample test", "confidence interval trading",
     "copy trading test method"], 7,
    "Every result we publish is net of real costs (never assumed below 3 % on meme coins), uses only information "
    "available at the time, counts the trades a follower would have missed, and comes with a 95 % interval and a "
    "sample size. A result is called proven only when the interval's lower end is above zero on data the selection "
    "never saw.",
    f"""
<h2>Why a method page</h2>
<p>Crypto is full of numbers that cannot lose: screenshots of winners, "90 % hit rate" channels, wallet lists picked
after the fact. They are not lies so much as measurements built to look good. The posts on this blog, for example
<a href=/blog/wallets-that-buy-before-a-solana-token-jumps>wallets that buy before pumps</a> and
<a href=/blog/does-copying-smart-wallets-pay>the copy test</a>, follow the rules below. If a rule is broken
somewhere, that is a bug and we want to hear about it.</p>

<h2>1. Real costs, always</h2>
<p>A trade that looks like +5 % before costs is often a loss after them. Every buy and sell pays a network fee, often a
priority fee, and slippage: the difference between the price you see and the price you get, which grows fast when
the trade is large relative to the pool ({S.a("jup_risks", "Jupiter explains slippage and price impact")}). On meme
coins we never assume a total round-trip cost below 3 %. In the
copy test a modest 1 % slippage on a fast copy was enough to turn it into an average loss of 7.6 %.</p>

<h2>2. Delay</h2>
<p>A follower acts after the leader. Our copy tests buy a fixed time after the copied wallet: 60 seconds (a person
or a slow bot) and 2 seconds (a fast bot). Speed has a price: to land in the same block you compete with other bots
on the {S.a("helius_pf", "priority fee per compute unit")}.</p>

<h2>3. Missed trades are counted</h2>
<p>Some trades cannot be copied: the token is gone, the price ran too far, the pool is too thin. Dropping them makes
any strategy look better, because the missed ones are often the best ones. We report how many were missed; in the
copy test it was 34.8 % of the wallets' buys.</p>

<h2>4. Selection from the past only</h2>
<p>If you pick the best wallets using all history and then test them on that same history, they will look great: you
picked them for being great on it. We select from the past and test on what came after, then check again on later
days in the demo. A pattern is "confirmed" only when it holds on days the selection had not seen; for example 90 of
257 repeat wallet groups were confirmed this way.</p>

<h2>5. A control group</h2>
<p>Every test runs next to something dumb: random early buyers, random entries. If the clever version is not clearly
better than the dumb one, it is not clever. In the copy test random early buyers averaged +2.7 % with a wide
interval; that sets the bar.</p>

<h2>6. Intervals, not just averages</h2>
<p>Meme coin results are wild: a few huge winners and many losers. An average alone hides that. With each mean we
show a 95 % interval, the range in which the true average plausibly lies given how much the results scatter
({S.a("nist_ci", "NIST's handbook on confidence limits")}), and the number of trades (n). Our rule:</p>
<ol>
<li>The lower end of the 95 % interval is above zero, on out-of-sample data.</li>
<li>The result is clearly better than the random control.</li>
<li>It holds in the demo on later days, before any real money.</li>
</ol>
<p>The sample size matters as much as the mean. This is how many copies each copy-test result rests on:</p>
{bars("Copy test: number of copies behind each result", [
    ("Copy 60 s after them", 1219, "mean +29.7%, interval -12.9% to +114.3%"),
    ("Fast copy, 2 s", 1202, "mean -7.6%, interval -9.3% to -5.7%"),
    ("Random early buyers (control)", 49, "mean +2.7%, interval -22.4% to +45.0%"),
    ("Entry at $15M+ market cap", 41, "mean -3.3%, interval -7.3% to +1.6%"),
], sub="n per result, 23 November 2026", fmt="num", hl=(0, 1), source=SRC)}
<p>Small samples give wide intervals: 41 or 49 trades can hide almost anything. By the rule above the 60-second copy test (+29.7 %, interval −12.9 % to +114.3 %) is not proven, and the 2-second copy
(−7.6 %, interval −9.3 % to −5.7 %) is proven negative.</p>

<h2>7. Demo before real money</h2>
<p>New ideas trade in a demo account first, net of the same costs, and every demo entry is labelled with the market
regime it was taken in. Demo results never count as proof for real money unless real money would have taken the
same entry.</p>

<h2>8. Statistics, not accusations</h2>
<p>We describe groups and patterns. We never publish wallet addresses, and words like "insider" or "team" describe a
statistical shape (shared funding, same-second buys), not a claim about a person. Wallet groups are inferred from
public data, which can be
{S.a("helius_etx", "parsed from raw Solana transactions into swaps and transfers")}, and some inferences will be wrong.</p>

<h2>9. Dates and sources</h2>
<p>Every number carries its date. Our own measurements are marked as MemeSonar's; outside facts link to official
documentation, regulators or research, each checked before it was linked. Market data comes from public on-chain and
DEX data such as {S.a("dexs_api", "DEX Screener's public API")}.</p>

<h2>What this does not do</h2>
<p>It does not make the past predict the future. A method like this can tell you that something did not work, or did
work with known uncertainty; it cannot promise the next month. Meme coins remain extremely risky, and most of what
we measure is losses.</p>
{RISK}
""",
    related=("does-copying-smart-wallets-pay", "wallets-that-buy-before-a-solana-token-jumps",
             "how-to-check-a-kol-track-record"), date=D)
