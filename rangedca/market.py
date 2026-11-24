"""The market watchlist of range_dca (11.11., Jure: "širi range watchlist"; flag range_market G20, event tokens flag
event_tokens G19). run_range.py once calls pass_once() every minute while either flag is on; it writes range.db only.

Why: the signal pass (data.candidates) watches at most RANGE_MAX_TOKENS (40) tokens and only those our own signals
name (open rounds, Autopilot tokens, recent ranges, the hype scan's top 40, KOL calls), so get_range_candidates
showed watched=40 out of a market of hundreds of ranging tokens. This pass adds the whole bonded market, inside a
measured daily budget per source (CLAUDE.md: izmjeri i odaberi najjeftinije).

Universe (table mkt), cheapest first:
  migracija    hype.db live_launches pool 'migration' (PumpPortal's free migration event, kept 7 days)
  graduates    kol.db graduates (the KOL round's PumpSwap listing, already paid by nobody)
  skener       scan.db cand: the market scanner's tokens with the numbers it priced in the last 10 min (free)
  event        the main / other tokens of the active event topics (topics.db, flag event_tokens)
  dex_liste    DexScreener latest profiles, latest and top boosts: 3 requests every LISTS_EVERY_S (free API, the
               60-a-minute endpoints), at most LISTS_DAY a day
  gt           GeckoTerminal trending pools and the top pools by 24 h volume: 2 requests every GT_EVERY_S, at most GT_DAY
               a day out of the SHARED CoinGecko budget (3000 a day; scan 150, range seeds 60, events 600 a night,
               momentum 100); their numbers admit a pool without another request
  birdeye      Birdeye's token list by 24 h volume, ONLY with BIRDEYE_API_KEY, every BIRD_EVERY_S, at most BIRDEYE_DAY
  propusteno   11.11. (flag range_missed G27, rangedca/missed.py): every token a skip journal labels propušteno
               (skipped, then >= +20 % within 60 min: preskoceni, fast path, proposals), src 'missed' for 72 h, due at
               once; filter: bonded, MC >= 30k, liquidity >= $15k, volume 1 h >= $10k and the owner's hard blocks
               (missed.hard_block); after 72 h back to src 'market' (the market filter keeps it or it leaves)
  14.11. (Jure: "U svakom momentu na kripto tržištu ima stotine tokena koji se kreću u range-u ... pronađi ga"; the
  Render log of 14.11. 06:31-07:26 UTC: 8,780 tokens in the universe, 74 % of them PumpPortal migrations, of which
  4,930 never had a DexScreener price, 1,948 under 30k, 806 on the curve, 646 in the rug archive; only ~11 due for a
  check at any time, admitted 0 a pass, 4-8 market tokens watched): the sources that bring OLDER living tokens, all
  free or inside the caps below:
  gt_dex       GeckoTerminal's top pools of the PumpSwap dex (bonded pump.fun tokens of every age) by 24 h volume,
               GT_DEX_PAGES pages in the same round as gt (20 pools a page; their numbers admit a pool at once)
  dex_liste    + DexScreener community takeovers and recent profile updates (older tokens revived by their community):
               5 list requests every LISTS_EVERY_S
  hype         hype.db token_pulse: the hype scan's tokens of the last 2 h at MC >= 30k, liquidity >= $15k (free)
  pozivi       kol.db calls of the last 7 days at a known MC >= 30k (the tokens that were hot before the crash; free)
  raspon       range.db events "aktivan" of the last 3 days: every token that had an active range (free)
  promote      a known token that a source sees passing the filter NOW (its own numbers) is due at once, whatever it
               waited for (11.11.: add() never moved next_ts, so a token put aside a day under 30k or 2 h under 50k
               stayed aside while GeckoTerminal saw it pass ~30 times a round: "prolazi filter 33, primljeno 0")
  14.11. večer (owner: "Želim više tradeova"; the backtest: a token is in an active range ~6 % of the time, so the
  number of range trades follows the number of LIVE tokens watched). Measured from the sandbox 14.11. 13:20-14:00 UTC:
  the Render log's universe of 8,875 held 41 watched; 5,012 "nema cijene" are PumpPortal migrations that DexScreener
  no longer lists (two fresh migrations sampled: MC $1 and $17, liquidity $1 and $12: junk launches, not asked too
  early, they are asked 6 h after migrating); every GeckoTerminal list together (104 requests) held 61 tokens passing
  the market filter, the 12 Jupiter lists 177 tokens in the band (MC/liquidity, bonded), 73 of them with volume 1 h
  >= $5k; GeckoTerminal + Jupiter 88 passing at once. The PumpSwap top pages by 24 h volume were mostly drained pumps
  (126 of 200 under $15k liquidity, pages 1-4 not one passing); the trending lists (1 h, 6 h, 24 h) held 35-40 each.
  jup          Jupiter's token lists (tokens/v2/{toptraded,toptrending,toporganicscore}/{interval}, 100 tokens each,
               free, no key: lite-api.jup.ag, never the swap key JUP_API_KEY), JUP_LISTS, ONE list a pass in turn so
               the whole set is read every JUP_EVERY_S (15 min), at most JUP_DAY a day (hour-sliced): every DEX at
               once (PumpSwap, Raydium, Meteora, ...), the token's MC, liquidity, buy + sell volume of the hour and
               its pool's age; launchpad tokens only once graduated (bonded), tokenized stocks / RWA / LST skipped.
               Measured: 7 lists held 78 of the 80 passing tokens of all 12 (toptraded 1h 40, toptrending 24h +14,
               toporganicscore 1h +8, toptraded 5m +6, toporganicscore 5m +4, toporganicscore 24h +3, toptrending 1h
               +3). A token that passes is due now (promote); one that only misses the volume or the age is put
               in the universe to be asked again then; other rows are not stored (MC out of the band is most of them)
  gt           (14.11. večer) the round is the trending lists of 1 h, 6 h and 24 h (GT_TREND_PAGES pages each), then
               the top pools and the PumpSwap pools by 24 h transactions (GT_TOP_PAGES / GT_DEX_PAGES): the same 16
               requests held 38 passing tokens where the old set (more top-volume and PumpSwap-volume pages) held 19.
               It is asked GT_REQ_PASS pages a pass and resumes where it stopped (a 60-s pass never waits a minute on
               GeckoTerminal), only the requests really sent are charged, and it stops at the first page that fails
               or that another job holds. The Render log's "15 upita, 20 poolova": 15 charged, one page answered:
               the key's hour slice was spent, so the round went to the free GeckoTerminal (measured from here: a
               429 every ~8 requests at 27 a minute, and the minute loop reserves the free host), and every page
               after the first came back empty but was charged. Now, while the CoinGecko key's hour slice is spent
               (the day's is not), the round waits for the next hour (range is a priority job of the key, so it is
               served first then); without a key, or with the day's calls gone, it asks the free host GT_REQ_PASS_FREE
               pages a pass and stops at the first 429.
Source priority of a token: event > missed > market (and the signal pass above them all, rangedca/view.source_of).
Market filter (a market token): bonded, MC $30k-$5M (14.11.: was $50k; the owner's floor is 30k), liquidity >= $15k,
volume 1 h >= $5k (14.11.: was $10k; a token that ranges trades calmly), at least 6 h old. An
event token only needs what every analysed token needs: bonded and MC >= $30k (CLAUDE.md). A token that fails waits
(next_ts) by its reason: under 30k a day, on the curve 6 h, otherwise 1-2 h; too young until it is 6 h old.

Price series: DexScreener /tokens batches (free, 30 tokens a request, data.fetch_pairs) stored as range.db snaps,
the same table the signal pass writes: the HOT_N (100) most important tokens every HOT_EVERY_S (5 min), the rest
every COLD_EVERY_S (15 min). 12.11. (owner, nalog 3: "STC ima cijene samo do 10:55 CET, iako je likvidnost bila 16k";
test: "token na watch listi s likvidnošću >= 15k dobiva cijenu barem svakih 5 min"): every watched token with
liquidity >= KEEP_LIQ gets a price at least every PRICE_EVERY_S (5 min), whatever its place in the order (it is asked
one run_range pass early, PASS_GAP_S, so a late pass never makes the gap longer), and served first when the hour's
budget is short; a watched token whose MC fell under 30k (or under the market band's 50k) stays on the list while its
liquidity holds (>= KEEP_LIQ) and it trades (KEEP_VOL_H1): under 30k it is only measured (CLAUDE.md: "smiju se
analizirati i mjeriti u sjeni"), never bought (rangedca/detect marks it "ispod 30k", rangedca/trade._guards refuses
it). The signal pass hands such a token over (adopt()), so it keeps its price once it leaves the signal candidates.
Order: active ranges near the bottom (entry close), event tokens, then 1 h volume. A token the hype scan snapshotted
in the last 150 s is not asked again (its token_pulse rows are merged by data.series). A token of the signal pass is
left to it (one snapshot a minute). Minute OHLCV from GeckoTerminal for 300 tokens would be ~28,800 requests a day:
impossible inside 3000; a GeckoTerminal seed is spent only on a token close to an entry (run_range.py, inside
RANGE_GT_DAY and MKT_SEED_DAY).

Budget per source per UTC day (env-overridable), hour-sliced (by the end of hour h at most cap * (h + 1) / 24), so a
busy morning never spends the night's share. When a pass needs more DexScreener requests than its slice allows, the
LOWEST-volume due tokens are dropped first (the refresh order is by volume) and that is logged. At the first pass of
a new day one line per source: "range watchlist trošak (dan): dexscreener N/cap, ...".
Estimate at 400 watched: 100 x 288 / 30 + 300 x 96 / 30 = ~2,100 requests a day for the series (less what the hype
scan already snapshots), plus discovery (<= DISC_REQ_PASS a pass and its own DISC_DAY 600, so it never eats the
refresh's share) = at most ~2,700 a day under DEX_DAY 3000, ~2 a minute against DexScreener's 300 a minute (a pass
sends at most MAX_REQ_PASS 20). 12.11. (5 minutes for every liquid token): measured 12.11. 11:07 UTC, 29 watched and
910 requests since midnight (~2,000 a day); at that size the change adds ~70 a day (one batch every ~4 passes instead
of every 5). Worst case, 400 liquid tokens: 14 batches every ~248 s = ~4,900 a day + discovery <= 1,500, hence
DEX_DAY 6500 (~4.5 a minute against the free 300; DexScreener costs nothing, the cap only guards the rate limit).
14.11. večer (svemir), a day before -> after, every cap unchanged: DexScreener refresh + discovery ~2,000 (41 watched)
-> ~2,000-3,500 (120-200 watched: 1-2 batches a pass); DexScreener lists 480 -> 480; Jupiter 0 -> 672 (JUP_DAY 700,
free); GeckoTerminal list 192 charged (most of it never answered on the free host) -> at most 192, only what went
out; GeckoTerminal seeds of market tokens at most SEED_DAY 20 (of RANGE_GT_DAY 60) -> the same, up to 12 of them for
new tokens without history. A live run from the sandbox (14.11. ~14:00 UTC, 10 passes, Jupiter + the free
GeckoTerminal + DexScreener lists only, no scanner / hype / calls / migrations): 60 watched after 20 minutes (jup 52,
gt 29, dex_liste 11), 22 DexScreener requests.
Nothing here trades. range_dca may enter a market / event token only on the demo account (paper), while its flag
(range_market / event_tokens) is paper; never on the real account (rangedca/trade.py). A missed token: the demo
account while range_missed is paper; the real account only while it is live AND >= 20 closed demo rounds of source
missed pass the live proof (rangedca/gate.missed_refusal).
"""
import os
import sqlite3
import time

from . import data

MARKET_MAX = int(os.environ.get("RANGE_MARKET_MAX", "400"))
# 14.11. (owner: the 30k floor, CLAUDE.md; the market band's 50k held out every token the crash put at 30-50k)
MIN_MCAP = float(os.environ.get("RANGE_MKT_MIN_MCAP", "30000"))
MAX_MCAP = float(os.environ.get("RANGE_MKT_MAX_MCAP", "5000000"))
MIN_LIQ = float(os.environ.get("RANGE_MKT_MIN_LIQ", "15000"))   # 11.11. owner rule B: = trade/cost.LIQ_HARD_MIN
MIN_VOL_H1 = float(os.environ.get("RANGE_MKT_MIN_VOL_H1", "5000"))   # 14.11.: was 10k (ranging tokens trade calmly)
MIN_AGE_H = float(os.environ.get("RANGE_MKT_MIN_AGE_H", "6"))
HOT_N = int(os.environ.get("RANGE_MKT_HOT_N", "100"))
HOT_EVERY_S = 300
COLD_EVERY_S = 900
SLACK_S = 30              # the pass runs every 60 s: a token due within 30 s is taken now
# 12.11. (owner, nalog 3): a watched token with liquidity >= KEEP_LIQ gets a price at least every PRICE_EVERY_S. A
# run_range pass comes every ~62 s (start.sh: 60 s sleep + the pass), so such a token is asked once its price is
# PRICE_EVERY_S - PASS_GAP_S old: the next pass would already be past the 5 minutes (HOT_EVERY_S - SLACK_S = 270 s
# with 62-s passes gave 310 s). 12.11. popodne: start.sh now starts a pass every 60 s from the start of the last one
# (deadline), so the gap is ~60 s unless a pass runs longer; PASS_GAP_S keeps the margin for that
PRICE_EVERY_S = 300
PASS_GAP_S = 70
MEASURE_WHY = "MC ispod 30k: samo mjerenje, ne kupuje se"
DEX_DAY = int(os.environ.get("RANGE_MKT_DEX_DAY", "6500"))   # 12.11.: was 4000 (see the module text, worst case)
DISC_DAY = int(os.environ.get("RANGE_MKT_DISC_DAY", "1500"))   # of DEX_DAY at most this for discovery (the rest refreshes)
LISTS_DAY = int(os.environ.get("RANGE_MKT_LISTS_DAY", "500"))   # 14.11.: 5 lists x 96 rounds (was 3 lists, 300)
# 14.11.: 4 trending + 6 top + 5 PumpSwap pages every 2 h = 180 a day of the shared CoinGecko 3000 (was 130);
# 14.11. popodne (owner: 50-100 range trades a day, the scalp's focus list): 6 PumpSwap pages = 16 a round, 192 a day,
# still inside GT_DAY 200 (free, no new spend)
GT_DAY = int(os.environ.get("RANGE_MKT_GT_DAY", "200"))
# 11.11. (Jure: "watchlist 300+", faza 1): after 40 min the list held 8 market tokens: PumpPortal migrations mostly die
# under 50k and one page of GeckoTerminal's top pools (20) an hour found almost nothing else. Now GT_TOP_PAGES pages of
# the top pools by 24 h volume + GT_TREND_PAGES of trending (1 h and 6 h) every GT_EVERY_S: 20 pools a request, their
# numbers admit a pool without a DexScreener request. ~10 requests every 2 h = ~120 a day of the shared 3000.
# 14.11. večer (svemir, measured: module text): trending 1 h / 6 h / 24 h x 4 pages + 2 top + 2 PumpSwap pages by 24 h
# transactions = the same 16 requests a round (192 a day), twice the passing tokens
GT_TREND_DURATIONS = tuple(x.strip() for x in os.environ.get("RANGE_MKT_GT_TREND_DUR", "1h,6h,24h").split(",") if x.strip())
GT_TOP_PAGES = int(os.environ.get("RANGE_MKT_GT_PAGES", "2"))
GT_TREND_PAGES = int(os.environ.get("RANGE_MKT_GT_TREND_PAGES", "4"))
GT_SORT = os.environ.get("RANGE_MKT_GT_SORT", "h24_tx_count_desc")   # 14.11. večer: by volume = drained pumps first
# 14.11. (owner: tokens that survived the crash): the PumpSwap dex's top pools by 24 h volume, every age (the trending
# lists are mostly hours old); measured 14.11. 07:50 UTC: of its 219 top pools 30 were in MC 30k-5M with $15k+
GT_DEX = os.environ.get("RANGE_MKT_GT_DEX", "pumpswap")
GT_DEX_PAGES = int(os.environ.get("RANGE_MKT_GT_DEX_PAGES", "2"))
# 14.11. večer: GeckoTerminal pages a pass (the round resumes next pass): the key's pace is 0.25 s, the free host's
# 3.5 s (a whole round of 16 on the free host held a 60-s run_range pass for a minute)
GT_REQ_PASS = int(os.environ.get("RANGE_MKT_GT_REQ_PASS", "6"))
GT_REQ_PASS_FREE = 2
# 14.11. večer (svemir): Jupiter's token lists, free and keyless (module text). One list a pass, every list once in
# JUP_EVERY_S; 7 lists x 96 = 672 a day <= JUP_DAY. lite-api answers a few calls a second per IP (x-ratelimit
# headers; the swap path uses api.jup.ag with its own key), so one call a minute or two is nothing to it
JUP_URL = os.environ.get("RANGE_MKT_JUP_URL", "https://lite-api.jup.ag/tokens/v2")
JUP_LISTS = tuple(x.strip() for x in os.environ.get(
    "RANGE_MKT_JUP_LISTS", "toptraded/1h,toptrending/24h,toporganicscore/1h,toptraded/5m,toporganicscore/5m,"
                           "toporganicscore/24h,toptrending/1h").split(",") if x.strip())
JUP_EVERY_S = int(os.environ.get("RANGE_MKT_JUP_EVERY_S", "900"))
JUP_DAY = int(os.environ.get("RANGE_MKT_JUP_DAY", "700"))
JUP_PAUSE_S = 600          # after an error / 429 from Jupiter the lists rest this long
JUP_SKIP_TAGS = frozenset(("stocks", "rwa", "lst"))   # tokenized shares, real-world assets, staked SOL: not memes
# 14.11. večer: GeckoTerminal seeds (run_range.py) for a newly watched market token with volume 1 h >= this that has no
# 6 h of history yet: its range is computed at once instead of 6 h later; only while the market's seed day has more
# than SEED_NEAR_RESERVE left (those stay for tokens close to an entry). Inside SEED_DAY and RANGE_GT_DAY, no new cap
EARLY_SEED_VOL_H1 = float(os.environ.get("RANGE_MKT_EARLY_SEED_VOL_H1", "20000"))
SEED_NEAR_RESERVE = 8
# a watched token stays while it keeps these (admission needs MIN_VOL_H1 / MIN_LIQ): one quiet hour no longer drops it
# 14.11.: 3k (was 5k) = the range's own floor (detect min_vol_h1, trade/cost.VOL_FLOOR), under the new 5k admission
KEEP_VOL_H1 = float(os.environ.get("RANGE_MKT_KEEP_VOL_H1", "3000"))
KEEP_LIQ = float(os.environ.get("RANGE_MKT_KEEP_LIQ", "15000"))
BIRDEYE_DAY = int(os.environ.get("RANGE_MKT_BIRDEYE_DAY", "24"))
SEED_DAY = int(os.environ.get("RANGE_MKT_SEED_DAY", "20"))   # GeckoTerminal seeds of market / event tokens (in GT_DAY 60)
MAX_REQ_PASS = 30         # DexScreener /tokens requests in one pass (refresh + discovery)
# 11.11. (all 6 range candidates "5-minutni podaci nisu svježi"): the market part of a run_range pass stops asking
# DexScreener after this many seconds, so the active ranges' numbers are renewed every pass (METRICS_FRESH_S 4 min)
PASS_BUDGET_S = float(os.environ.get("RANGE_MKT_PASS_S", "25"))
# 11.11. 09:48 (faza 1, dijagnostika): 4,627 in the universe, 2,748 due for a check, 10 watched: 3 requests a pass
# (90 tokens) could not clear the backlog of PumpPortal migrations; DexScreener is free (300 a minute)
DISC_REQ_PASS = int(os.environ.get("RANGE_MKT_DISC_PASS", "10"))   # of them at most this many for discovery
LISTS_EVERY_S = 900
GT_EVERY_S = 7200
BIRD_EVERY_S = 7200
NO_PRICE_WAIT_S = 3 * 86400   # 11.11.: 1,244 dead migrations were asked again every 6 h
KEEP_SNAPS_DAYS = 3       # snapshots of market-only tokens (7 for the signal pass)
MIN_ANALYSED = data.MIN_MCAP   # 30k (CLAUDE.md)
WATCH_FLAG = {"market": "range_market", "event": "event_tokens"}   # never live: trade/settings.NEVER_LIVE
WATCH_FLAG["missed"] = "range_missed"   # 11.11. (G27): live only past rangedca/gate.missed_refusal (LIVE_GATES)
SRC_ORDER = ("signal", "event", "missed", "market")   # the priority of a range's watchlist source (view.source_of)
_RANK = {"event": 0, "missed": 1}                    # the universe's own sources (the signal pass is not in mkt)
MISSED_MIN_LIQ = 15_000.0      # 11.11. owner's rule B for a missed token: trade/cost.LIQ_HARD_MIN
MISSED_MIN_VOL_H1 = 10_000.0
GT ="https://api.geckoterminal.com/api/v2/networks/solana"
CURVE_DEX = ("pumpfun", "pump-fun", "moonshot", "moonit", "launchlab", "raydium-launchlab", "letsbonk", "letsbonk-fun",
             "meteora-dbc")
DAY_KEYS = (("dexscreener", "mkt_dex_day", lambda: DEX_DAY),
            ("od toga otkrivanje", "mkt_disc_day", lambda: DISC_DAY),
            ("dexscreener liste", "mkt_lists_day", lambda: LISTS_DAY),
            ("gt", "mkt_gt_day", lambda: GT_DAY), ("birdeye", "mkt_bird_day", lambda: BIRDEYE_DAY),
            ("jupiter", "mkt_jup_day", lambda: JUP_DAY))   # 14.11. večer (svemir)

SCHEMA = """
CREATE TABLE IF NOT EXISTS mkt (token TEXT PRIMARY KEY, via TEXT, src TEXT, first_seen INTEGER, checked_ts INTEGER,
    next_ts INTEGER, watched INTEGER DEFAULT 0, watched_ts INTEGER, last_snap INTEGER, symbol TEXT, mcap REAL, liq REAL,
    vol_h1 REAL, created_ts INTEGER, why TEXT);
CREATE INDEX IF NOT EXISTS mkt_due ON mkt (watched, next_ts);
"""


def ensure(con):
    con.executescript(SCHEMA)
    from . import missed
    missed.ensure(con)   # 11.11.: missed_until / missed_ts / missed_pct / missed_via


class Net:
    """The network seams (the offline tests pass their own). pairs: DexScreener /tokens through data.fetch_pairs."""

    def __init__(self, fetch=None):
        self._fetch = fetch

    def pairs(self, tokens, deadline=None):
        if self._fetch:
            return self._fetch(tokens)
        return data.fetch_pairs_fast(tokens, deadline)   # 11.11.: short leash, inside the pass's time budget

    def lists(self):
        from dexscreener import client
        out = []
        # 14.11.: + community takeovers and recent profile updates (older tokens their community revived)
        for fn in (client.latest_token_profiles, client.latest_boosts, client.top_boosts, client.community_takeovers,
                   client.recent_profile_updates):
            try:
                out += list(fn() or [])
            except Exception:  # noqa: BLE001 - discovery is best effort
                pass
        return out

    def gt_pools(self, n_req=None, start=0, deadline=None):
        """The round's pages (gt_plan) from `start`, at most n_req requests: a Fetched list of pools (sent = requests
        that went out, done = pages answered in order, stop = why it stopped early). None when another job holds the
        shared GeckoTerminal host before the first page (11.11.: the first round got 0 pools from 10 requests that
        way): nothing was asked, the round waits for a free minute. 14.11. večer: it stops at the first page another
        job holds (get_json answers None, nothing sent), at the first error (a 429 pauses every process on the host:
        asking on would only lengthen the pause) and at `deadline` (monotonic)."""
        from event_calendar import http
        if http.reserved_by_other(f"{GT}/pools") > 0:
            return None
        out = Fetched()
        plan = gt_plan()
        end = len(plan) if n_req is None else min(len(plan), start + n_req)
        for path, params in plan[start:end]:
            if deadline is not None and time.monotonic() >= deadline:
                out.stop = "vrijeme prolaza"
                break
            if http.cooling(f"{GT}{path}") > 0:   # after a 429 every process pauses: never sleep in the pass
                out.stop = "pauza nakon 429"
                break
            try:
                d = http.get_json(f"{GT}{path}", params, ttl=600, headers={"Accept": "application/json"}, retries=0)
            except Exception as e:  # noqa: BLE001
                out.sent += 1
                out.stop = f"greška {getattr(e, 'code', None) or type(e).__name__}"
                break
            if d is None:
                out.stop = "zauzet"
                break
            out.sent += 1
            out.done += 1
            out += [p for p in (d.get("data") or []) if isinstance(p, dict)]
        return out

    def jup_list(self, name):
        """One Jupiter token list (JUP_URL/{category}/{interval}, up to 100 tokens; free, keyless: the swap key
        JUP_API_KEY is never sent here). Raises on an HTTP error (a 429 included)."""
        from event_calendar import http
        d = http.get_json(f"{JUP_URL}/{name}", {"limit": 100}, ttl=300, timeout=10,
                          headers={"Accept": "application/json"}, retries=0)
        return [t for t in (d or []) if isinstance(t, dict)]

    def birdeye_list(self):
        key = os.environ.get("BIRDEYE_API_KEY")
        if not key:
            return None
        import urllib.parse
        import urllib.request
        from event_calendar import http
        url = "https://public-api.birdeye.so/defi/tokenlist?" + urllib.parse.urlencode(
            {"sort_by": "v24hUSD", "sort_type": "desc", "offset": 0, "limit": 50, "min_liquidity": int(MIN_LIQ)})
        req = urllib.request.Request(url, headers={"X-API-KEY": key, "x-chain": "solana", "Accept": "application/json",
                                                   "User-Agent": http.USER_AGENT})
        d = http._fetch(req, 20, retries=1)
        return list(((d or {}).get("data") or {}).get("tokens") or [])


class Fetched(list):
    """14.11. večer: what one discovery call brought plus its cost: sent (requests that went out: charged), done
    (pages answered in order: where the next pass resumes), stop (why it stopped early, "" when it did not)."""

    def __init__(self, *a):
        super().__init__(*a)
        self.sent = self.done = 0
        self.stop = ""


def gt_plan():
    """[(path, params)] of one GeckoTerminal discovery round, the most yielding first (14.11. večer, measured): the
    trending pools of every GT_TREND_DURATIONS, page by page; the top pools; the GT_DEX (PumpSwap) pools by GT_SORT."""
    reqs = [("/trending_pools", {"page": pg, "duration": d}) for d in GT_TREND_DURATIONS
            for pg in range(1, GT_TREND_PAGES + 1)]
    reqs += [("/pools", {"page": pg, "sort": GT_SORT}) for pg in range(1, GT_TOP_PAGES + 1)]
    reqs += [(f"/dexes/{GT_DEX}/pools", {"page": pg, "sort": GT_SORT}) for pg in range(1, GT_DEX_PAGES + 1)]
    return reqs


def _f(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _iso_ts(x):
    """An ISO time ("2026-11-14T09:27:24Z") -> unix s, None when unreadable."""
    if not x:
        return None
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _meter(service, method, n=1):
    try:
        from usage import meter
        meter.record(service, method, 0.0, calls=n)
    except Exception:  # noqa: BLE001
        pass


# ---------- budget ------------------------------------------------------------------------------------------------------

def slice_left(con, key, cap, now):
    """Requests this source may still make now: by the end of UTC hour h at most cap * (h + 1) / 24 in total."""
    hour = int(now % 86400 // 3600)
    return max(0, min(cap, int(cap * (hour + 1) / 24)) - data.day_used(con, key, now))


def spend_line(con, now, log=print):
    """At the first pass of a new UTC day: one line with every source's use of the day that ended (the counters
    still hold that day). Also the signal pass's own DexScreener polls and GeckoTerminal seeds."""
    today = data._day(now)
    last = data.kv_get(con, "mkt_spend_day")
    if last == today:
        return None
    data.kv_put(con, "mkt_spend_day", today)
    if not last:
        return None

    def used(key):
        return int((data.kv_get(con, key) or {}).get(last, 0))
    parts = [f"{name} {used(key)}/{cap()}" + (" (bez ključa)" if key == "mkt_bird_day" and not os.environ.get("BIRDEYE_API_KEY")
                                              else "") for name, key, cap in DAY_KEYS]
    line = (f"range watchlist trošak ({last}): " + ", ".join(parts)
            + f"; signalni prolaz dexscreener {used('sig_dex_day')}, gt sjeme {used('gt_day')}/{data.GT_DAY} "
              f"(tržište {used('mkt_seed_day')}/{SEED_DAY}, od toga rano {used('mkt_seed_early_day')}), helius "
              f"{used('helius_day')} kredita; iz hype skena bez "
              f"troška {used('mkt_reuse_day')} snimki")
    log(line)
    return line


# ---------- filters -------------------------------------------------------------------------------------------------------

def check(s, created_ts, src, now, keep=False):
    """(ok, why, wait_s) of one snapshot (data.snap_of shape) against the filter of its source. keep: a token already
    watched stays with the softer KEEP_VOL_H1 / KEEP_LIQ (11.11.: one quiet hour dropped it at once)."""
    if not s or not s.get("price"):
        return False, "nema cijene na DexScreeneru", NO_PRICE_WAIT_S
    if not s.get("bonded"):
        return False, "još na krivulji (uzimaju se bondani)", 6 * 3600
    mc = s.get("mcap") or 0
    if keep and (s.get("liq") or 0) >= KEEP_LIQ and not (src == "market" and mc > MAX_MCAP):
        # 12.11. (owner, nalog 3: STC under 30k with $16k of liquidity lost its prices): a WATCHED token with liquidity
        # >= KEEP_LIQ stays whatever its MC (under 30k: measured only, never bought; between 30k and the market band's
        # 50k: as any 30k+ token); it leaves when it stops trading (an event token excepted, as before), when its
        # liquidity goes under KEEP_LIQ, or a market token above MAX_MCAP
        if src != "event" and (s.get("vol_h1") or 0) < KEEP_VOL_H1:
            return False, f"volumen 1 h ${s.get('vol_h1') or 0:,.0f}", 3600
        return True, "", 0
    if mc < MIN_ANALYSED:
        return False, "MC ispod 30k (ne analizira se)", 86400
    if src == "event":
        return True, "", 0
    if src == "missed":   # 11.11. (range_missed): rule B's numbers; the hard blocks are missed.hard_block's (_store)
        if (s.get("liq") or 0) < (KEEP_LIQ if keep else MISSED_MIN_LIQ):
            return False, f"likvidnost ${s.get('liq') or 0:,.0f}", 2 * 3600
        if (s.get("vol_h1") or 0) < (KEEP_VOL_H1 if keep else MISSED_MIN_VOL_H1):
            return False, f"volumen 1 h ${s.get('vol_h1') or 0:,.0f}", 3600
        return True, "", 0
    if mc < MIN_MCAP:
        return False, f"MC ${mc:,.0f} ispod ${MIN_MCAP:,.0f}", 2 * 3600
    if mc > MAX_MCAP:
        return False, f"MC ${mc:,.0f} iznad ${MAX_MCAP:,.0f}", 86400
    if (s.get("liq") or 0) < (KEEP_LIQ if keep else MIN_LIQ):
        return False, f"likvidnost ${s.get('liq') or 0:,.0f}", 2 * 3600
    if (s.get("vol_h1") or 0) < (KEEP_VOL_H1 if keep else MIN_VOL_H1):
        return False, f"volumen 1 h ${s.get('vol_h1') or 0:,.0f}", 3600
    if created_ts and now - created_ts < MIN_AGE_H * 3600:
        return False, f"mlađi od {MIN_AGE_H:g} h", int(created_ts + MIN_AGE_H * 3600 - now) + 60
    return True, "", 0


# ---------- universe --------------------------------------------------------------------------------------------------

PROMOTE_GAP_S = 1800   # 14.11.: a promoted token is checked again at most every 30 min


def add(con, tok, via, now, src="market", symbol=None, created_ts=None, due=None, nums=None, promote=False):
    """A token into the universe (or one more `via` for a known one). An event token is marked src 'event' and is due
    at once; 11.11. a missed one (rangedca/missed.py) src 'missed' (over 'market', never over 'event'), due at once.
    promote (14.11.): the source's own numbers pass the filter now, so a known token that is not watched is due at
    `due` (default now) even when it was put aside for longer (a day under 30k, 3 days without a price): one
    DexScreener check (1/30 of a request) instead of waiting while it trades; at most once every PROMOTE_GAP_S
    (a token the scanner lists every minute but DexScreener refuses is not asked every minute)."""
    r = con.execute("SELECT via, src, next_ts, watched, checked_ts FROM mkt WHERE token=?", (tok,)).fetchone()
    nums = nums or {}
    if r is None:
        con.execute("INSERT INTO mkt (token, via, src, first_seen, next_ts, watched, symbol, mcap, liq, vol_h1, created_ts) "
                    "VALUES (?,?,?,?,?,0,?,?,?,?,?)", (tok, via, src, int(now), int(due if due is not None else now),
                                                       symbol, nums.get("mcap"), nums.get("liq"), nums.get("vol_h1"),
                                                       int(created_ts) if created_ts else None))
        return True
    vias = set((r[0] or "").split(",")) - {""}
    upd = {}
    if via not in vias:
        upd["via"] = ",".join(sorted(vias | {via}))
    if src in _RANK and _RANK[src] < _RANK.get(r[1], 9):
        upd["src"] = src
        if not r[3]:
            upd["next_ts"] = int(now)
    when = int(due if due is not None else now)
    if promote and not r[3] and (r[2] or 0) > when and "next_ts" not in upd and now - (r[4] or 0) >= PROMOTE_GAP_S:
        upd["next_ts"] = when
    if created_ts:
        upd["created_ts"] = int(created_ts)
    for k in ("mcap", "liq", "vol_h1"):
        if nums.get(k) is not None:
            upd[k] = nums[k]
    if upd:
        con.execute(f"UPDATE mkt SET {', '.join(k + '=?' for k in upd)} WHERE token=?", (*upd.values(), tok))
    return False


def adopt(con, snaps, now):
    """12.11. (owner, nalog 3): the signal pass's tokens measured under 30k (rangedca/data.poll: bonded, liquidity >=
    KEEP_LIQ) join the watched list, src market, via "signal": a range "ispod 30k" is no longer a recent range there,
    so without this the token fell out of the signal candidates and nobody asked its price again. Here it keeps a
    price every 5 min while check()'s keep rule holds (liquidity, volume). snaps: {token: data.snap_of dict}. Returns
    how many were put on the list."""
    ensure(con)
    n = 0
    for tok, s in (snaps or {}).items():
        if not s or not s.get("price") or not s.get("bonded") or (s.get("mcap") or 0) >= MIN_ANALYSED:
            continue
        if (s.get("liq") or 0) < KEEP_LIQ or (s.get("vol_h1") or 0) < KEEP_VOL_H1:
            continue
        add(con, tok, "signal", now, symbol=s.get("symbol"),
            nums={"mcap": s.get("mcap"), "liq": s.get("liq"), "vol_h1": s.get("vol_h1")})
        n += con.execute("UPDATE mkt SET watched=1, watched_ts=?, checked_ts=?, last_snap=?, why=? WHERE token=? AND "
                         "watched=0", (int(now), int(now), int(s.get("ts") or now), MEASURE_WHY, tok)).rowcount
    return n


def _ro(path):
    return data._ro_file(path)


def from_migrations(con, now, hype_db=None):
    wm = data.kv_get(con, "mkt_wm_mig") or 0
    hc = _ro(hype_db or data.hype_path())
    n = 0
    if hc is None:
        return 0
    try:
        for mint, ts, sym in hc.execute("SELECT mint, ts, symbol FROM live_launches WHERE pool='migration' AND ts > ? "
                                        "ORDER BY ts", (int(wm),)):
            n += add(con, mint, "migracija", now, symbol=sym or None, created_ts=ts,
                     due=max(now, ts + MIN_AGE_H * 3600))
            wm = max(wm, ts)
    except sqlite3.Error:
        pass
    finally:
        hc.close()
    data.kv_put(con, "mkt_wm_mig", wm)
    return n


def from_graduates(con, now):
    try:
        from kol import store as kstore
        kc = _ro(kstore.DB)
    except Exception:  # noqa: BLE001
        kc = None
    if kc is None:
        return 0
    wm = data.kv_get(con, "mkt_wm_grad") or 0
    n = 0
    try:
        for tok, sym, created, first in kc.execute("SELECT token, symbol, created_ts, first_seen FROM graduates WHERE "
                                                   "first_seen > ? ORDER BY first_seen", (int(wm),)):
            n += add(con, tok, "graduates", now, symbol=sym, created_ts=created,
                     due=max(now, (created or now) + MIN_AGE_H * 3600))
            wm = max(wm, first or 0)
    except sqlite3.Error:
        pass
    finally:
        kc.close()
    data.kv_put(con, "mkt_wm_grad", wm)
    return n


def from_scanner(con, now, scan_db=None):
    """scan.db cand rows priced in the last 10 min that pass the market filter's numbers (free; seen by the scanner
    for 6 h or more counts as old enough)."""
    try:
        from scan import store as sstore
        sc = _ro(scan_db or sstore.db_path())
    except Exception:  # noqa: BLE001
        sc = None
    if sc is None:
        return 0
    n = 0
    try:
        for tok, sym, first, mc, liq, v1, stage in sc.execute(
                "SELECT token, symbol, first_seen, mcap, liq, vol_h1, stage FROM cand WHERE checked_ts >= ? AND mcap >= ? "
                "AND mcap <= ? AND liq >= ? AND vol_h1 >= ?", (int(now - 600), MIN_MCAP, MAX_MCAP, MIN_LIQ, MIN_VOL_H1)):
            if stage in ("final_stretch", "curve"):
                continue
            n += add(con, tok, "skener", now, symbol=sym, nums={"mcap": mc, "liq": liq, "vol_h1": v1}, promote=True)
    except sqlite3.Error:
        pass
    finally:
        sc.close()
    return n


def from_events(con, now, topics_db=None):
    """The main / other tokens of the active event topics (topics.db), src 'event'."""
    try:
        from topics import store as tstore
        tc = tstore.ro(topics_db)
    except Exception:  # noqa: BLE001
        tc = None
    if tc is None:
        return set()
    try:
        toks = tstore.active_tokens(tc)
    except sqlite3.Error:
        toks = {}
    finally:
        tc.close()
    for tok in toks:
        add(con, tok, "event", now, src="event")
    # an event token whose topic ended (or whose role became clone / rug) is a market token again (a missed one while
    # its 72 h last, 11.11.) or leaves
    from . import missed
    for (tok,) in con.execute("SELECT token FROM mkt WHERE src='event'").fetchall():
        if tok not in toks:
            con.execute(f"UPDATE mkt SET src={missed.fallback_sql()} WHERE token=?", (int(now), tok))
    return set(toks)


FREE_EVERY_S = 600                # 14.11.: the free sources below are read every 10 min (a pass is every minute)
PULSE_LOOKBACK_S = 2 * 3600       # 14.11.: the hype scan's tokens of the last 2 h
CALLS_LOOKBACK_S = 7 * 86400      # 14.11.: KOL calls of the last 7 days (the tokens that were hot before the crash)
CALLS_MAX = 300                   # ... at most this many a round, the most called first
RANGED_LOOKBACK_S = 3 * 86400     # 14.11.: tokens that had an active range in the last 3 days


def from_pulse(con, now, hype_db=None):
    """14.11.: hype.db token_pulse, the newest row of every token of the last PULSE_LOOKBACK_S whose own numbers pass
    the market filter's (MC MIN_MCAP-MAX_MCAP, liquidity MIN_LIQ, volume 1 h MIN_VOL_H1): via "hype", due now
    (promote: the numbers are seconds old). Free (a read of hype.db)."""
    hc = _ro(hype_db or data.hype_path())
    if hc is None:
        return 0
    n = 0
    try:
        rows = hc.execute("SELECT token, MAX(ts), mcap, liquidity, vol_h1 FROM token_pulse WHERE ts >= ? GROUP BY token",
                          (int(now - PULSE_LOOKBACK_S),)).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        hc.close()
    for tok, _ts, mc, liq, v1 in rows:
        if tok and MIN_MCAP <= (mc or 0) <= MAX_MCAP and (liq or 0) >= MIN_LIQ and (v1 or 0) >= MIN_VOL_H1:
            n += add(con, tok, "hype", now, nums={"mcap": mc, "liq": liq, "vol_h1": v1}, promote=True)
    return n


def from_calls(con, now):
    """14.11.: kol.db calls of the last CALLS_LOOKBACK_S at a known MC >= 30k (CLAUDE.md), new ones since the last
    round (watermark mkt_wm_calls: the newest call read), the most called first, at most CALLS_MAX a round (the less
    called rest of a busy window is left out): via "pozivi", due now when new (their numbers of today are unknown, so
    a known token waits for its own next_ts). Free (a read of kol.db)."""
    try:
        from kol import store as kstore
        kc = _ro(kstore.DB)
    except Exception:  # noqa: BLE001
        kc = None
    if kc is None:
        return 0
    wm = int(data.kv_get(con, "mkt_wm_calls") or now - CALLS_LOOKBACK_S)
    n = 0
    try:
        rows = kc.execute("SELECT token, MAX(symbol), COUNT(*), MAX(ts) FROM calls WHERE ts > ? AND COALESCE(mcap0, 0) "
                          ">= ? GROUP BY token ORDER BY COUNT(*) DESC, MAX(ts) DESC LIMIT ?",
                          (wm, MIN_ANALYSED, CALLS_MAX)).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        kc.close()
    top = wm
    for tok, sym, _n, last in rows:
        if tok:
            n += add(con, tok, "pozivi", now, symbol=sym)
            top = max(top, int(last or 0))
    data.kv_put(con, "mkt_wm_calls", top)
    return n


def from_ranged(con, now):
    """14.11. (owner: "ako se vratio u range, pronađi ga"): every token with a range.db event "aktivan" (its range
    became active) since the last round (watermark mkt_wm_ranged, first round RANGED_LOOKBACK_S back): via "raspon",
    due now (promote). A token that ranged before the crash stays on the list after the signal pass drops it, so
    its return into a range is seen. Free (range.db itself)."""
    wm = int(data.kv_get(con, "mkt_wm_ranged") or now - RANGED_LOOKBACK_S)
    n, top = 0, wm
    for tok, ts in con.execute("SELECT token, MAX(ts) FROM events WHERE kind='aktivan' AND ts > ? GROUP BY token",
                               (wm,)).fetchall():
        n += add(con, tok, "raspon", now, promote=True)
        top = max(top, int(ts or 0))
    data.kv_put(con, "mkt_wm_ranged", top)
    return n


def gt_row(p):
    """A GeckoTerminal pool -> (token, symbol, created_ts, snapshot dict like data.snap_of), or None."""
    a = p.get("attributes") or {}
    rel = p.get("relationships") or {}
    tok = (((rel.get("base_token") or {}).get("data") or {}).get("id") or "").split("_", 1)[-1]
    dex = ((rel.get("dex") or {}).get("data") or {}).get("id") or ""
    if not tok:
        return None
    vol = a.get("volume_usd") or {}
    liq = _f(a.get("reserve_in_usd")) or 0.0
    created = None
    if a.get("pool_created_at"):
        try:
            from datetime import datetime
            created = int(datetime.fromisoformat(str(a["pool_created_at"]).replace("Z", "+00:00")).timestamp())
        except ValueError:
            created = None
    s = {"price": _f(a.get("base_token_price_usd")), "mcap": _f(a.get("market_cap_usd")) or _f(a.get("fdv_usd")),
         "liq": liq, "vol_h1": _f(vol.get("h1")) or 0.0, "bonded": bool(liq > 0 and dex not in CURVE_DEX)}
    return tok, (a.get("name") or "").split(" / ")[0][:20] or None, created, s


def jup_row(t):
    """A Jupiter token (tokens/v2 list) -> (token, symbol, created_ts, snapshot dict like data.snap_of), or None
    (no address, or a tokenized stock / RWA / LST: JUP_SKIP_TAGS). Volume 1 h = the hour's buy + sell volume; a
    launchpad token (pump.fun, letsbonk, ...) is bonded only once it graduated (graduatedPool); its age is the
    graduation's (the pool DexScreener and GeckoTerminal date), else the first pool's."""
    tok = t.get("id")
    if not tok or JUP_SKIP_TAGS & set(t.get("tags") or ()):
        return None
    s1 = t.get("stats1h") or {}
    liq = _f(t.get("liquidity")) or 0.0
    created = _iso_ts(t.get("graduatedAt")) or _iso_ts((t.get("firstPool") or {}).get("createdAt"))
    s = {"price": _f(t.get("usdPrice")), "mcap": _f(t.get("mcap")) or _f(t.get("fdv")), "liq": liq,
         "vol_h1": (_f(s1.get("buyVolume")) or 0.0) + (_f(s1.get("sellVolume")) or 0.0),
         "bonded": bool(liq > 0 and (not t.get("launchpad") or t.get("graduatedPool")))}
    return tok, (t.get("symbol") or "")[:20] or None, created, s


def cg_day_text(con, now):
    """The shared CoinGecko day in one phrase: the key's calls today of CG_DAILY_CALLS (all jobs) and the range list's
    own GT requests of GT_DAY; without the key, the free GeckoTerminal."""
    own = f"range lista {data.day_used(con, 'mkt_gt_day', now)}/{GT_DAY}"
    try:
        from event_calendar import http
        if not http._cg_key_raw():
            return f"CoinGecko bez ključa (besplatni GT), {own}"
        used, cap = http.cg_used()
        lim = int(http.allowance(cap, now))   # the hour's slice of the day (main's budget since 11.11.)
        note = (" (potrošen: ostatak dana besplatni GT)" if used >= cap else
                f" (satni dio {lim} potrošen: do sljedećeg sata besplatni GT)" if used >= lim else "")
        return f"CoinGecko ključ danas {used}/{cap}{note}, {own}"
    except Exception:  # noqa: BLE001
        return own


def gt_requests():
    """GeckoTerminal requests of one discovery round (gt_plan: the trending pages of every duration, the top pages,
    the PumpSwap dex's pages)."""
    return len(GT_TREND_DURATIONS) * GT_TREND_PAGES + GT_TOP_PAGES + GT_DEX_PAGES


N_LISTS = 5   # 14.11.: DexScreener list requests a round (profiles, boosts latest / top, takeovers, profile updates)
DISC_NET_S = 10   # 14.11. večer: the network discovery of one pass (lists, Jupiter, GeckoTerminal pages) stops here


def gt_route():
    """14.11. večer: how the GeckoTerminal round may ask now. "key": the CoinGecko key serves this job now (range is
    one of its priority jobs); "hour": the key is set and the day has calls left, but this hour's slice is spent: the
    round waits for the next hour instead of taking the free host the minute loop lives on; "free": no key, or the
    day's calls are gone: the free host, GT_REQ_PASS_FREE pages a pass."""
    try:
        from event_calendar import http
        if not http.cg_configured():
            return "free"
        if http.cg_key():
            return "key"
        used, cap = http.cg_used()
        return "free" if used >= cap else "hour"
    except Exception:  # noqa: BLE001 - unreadable budget: the free host, carefully
        return "free"


def discover_lists(con, now, net, log, deadline=None):
    """DexScreener lists, Jupiter's lists (14.11. večer), GeckoTerminal pools and Birdeye's list, each on its own
    cadence and day cap. deadline (monotonic): this pass's network discovery stops there (the GeckoTerminal round
    resumes next pass)."""
    n = 0
    if (now - (data.kv_get(con, "mkt_lists_ts") or 0) >= LISTS_EVERY_S
            and slice_left(con, "mkt_lists_day", LISTS_DAY, now) >= N_LISTS):
        data.kv_put(con, "mkt_lists_ts", int(now))
        data.day_add(con, "mkt_lists_day", N_LISTS, now)
        _meter("dexscreener", "range tržište liste", N_LISTS)
        for it in net.lists() or []:
            if isinstance(it, dict) and it.get("chainId") == "solana" and it.get("tokenAddress"):
                n += add(con, it["tokenAddress"], "dex_liste", now)
    n += discover_jup(con, now, net, log)
    n += discover_gt(con, now, net, log, deadline)
    if (os.environ.get("BIRDEYE_API_KEY") and now - (data.kv_get(con, "mkt_bird_ts") or 0) >= BIRD_EVERY_S
            and slice_left(con, "mkt_bird_day", BIRDEYE_DAY, now) >= 1):
        data.kv_put(con, "mkt_bird_ts", int(now))
        data.day_add(con, "mkt_bird_day", 1, now)
        _meter("birdeye", "range tržište")
        try:
            for t in net.birdeye_list() or []:
                if isinstance(t, dict) and t.get("address"):
                    mc = _f(t.get("mc"))
                    n += add(con, t["address"], "birdeye", now, symbol=t.get("symbol"),
                             nums={"mcap": mc, "liq": _f(t.get("liquidity"))})
        except Exception as e:  # noqa: BLE001
            log(f"range tržište: Birdeye: {type(e).__name__}")
    return n


def _jup_hour(con, now, log):
    """The Jupiter counters of this UTC hour (kv mkt_jup_hour); at the first call of a new hour the last hour's line
    is logged (one line an hour, not one a list)."""
    h = int(now // 3600 * 3600)
    hr = data.kv_get(con, "mkt_jup_hour") or {}
    if hr.get("h") != h:
        if hr.get("h"):
            log(jup_line(con, hr, now))
        hr = {"h": h, "req": 0, "fail": 0, "rows": 0, "new": 0, "ok": [], "err": ""}
    return hr


def jup_line(con, hr, now):
    """"range tržište Jupiter (sat HH UTC): N upita, M tokena, novih K, prolazi filter P; danas X/JUP_DAY"."""
    err = f", greške {hr.get('fail')} ({hr.get('err')})" if hr.get("fail") else ""
    return (f"range tržište Jupiter (sat {time.gmtime(hr.get('h') or now).tm_hour:02d} UTC): {hr.get('req', 0)} upita, "
            f"{hr.get('rows', 0)} tokena, novih {hr.get('new', 0)}, prolazi filter {len(hr.get('ok') or [])}{err}; "
            f"danas {data.day_used(con, 'mkt_jup_day', now)}/{JUP_DAY} (besplatno)")


def discover_jup(con, now, net, log):
    """14.11. večer (svemir): one Jupiter list a pass in turn (JUP_LISTS), so every list is read once in JUP_EVERY_S,
    inside JUP_DAY (hour-sliced). A token whose own numbers pass the market filter is due now (promote); one that only
    misses the volume or the age goes into the universe for then; the rest (MC out of the band, on the curve, thin
    liquidity) is not stored. An error or a 429 rests the lists JUP_PAUSE_S. A stand-in net without jup_list (the
    offline tests) asks nothing. Returns the new universe rows."""
    fn = getattr(net, "jup_list", None)
    if fn is None or not JUP_LISTS or now < (data.kv_get(con, "mkt_jup_pause") or 0):
        return 0
    if now - (data.kv_get(con, "mkt_jup_ts") or 0) < JUP_EVERY_S / len(JUP_LISTS) - SLACK_S:
        return 0
    if slice_left(con, "mkt_jup_day", JUP_DAY, now) < 1:
        return 0
    i = int(data.kv_get(con, "mkt_jup_i") or 0) % len(JUP_LISTS)
    data.kv_put(con, "mkt_jup_ts", int(now))
    data.day_add(con, "mkt_jup_day", 1, now)
    _meter("jupiter", "range tržište liste")
    hr = _jup_hour(con, now, log)
    hr["req"] += 1
    try:
        rows = fn(JUP_LISTS[i]) or []
    except Exception as e:  # noqa: BLE001 - discovery is best effort
        data.kv_put(con, "mkt_jup_pause", int(now + JUP_PAUSE_S))
        hr["fail"] += 1
        hr["err"] = f"{JUP_LISTS[i]}: {getattr(e, 'code', None) or type(e).__name__}"
        data.kv_put(con, "mkt_jup_hour", hr)
        return 0
    data.kv_put(con, "mkt_jup_i", (i + 1) % len(JUP_LISTS))
    n, ok_toks = 0, set(hr.get("ok") or [])
    for t in rows:
        g = jup_row(t) if isinstance(t, dict) else None
        if not g:
            continue
        tok, sym, created, s = g
        hr["rows"] += 1
        ok, why, wait = check(s, created, "market", now)
        if not ok and not why.startswith(("volumen", "mlađi")):
            continue
        if ok:
            ok_toks.add(tok)
        n += add(con, tok, "jup", now, symbol=sym, created_ts=created, due=now if ok else now + wait,
                 nums={"mcap": s["mcap"], "liq": s["liq"], "vol_h1": s["vol_h1"]}, promote=ok)
    hr["new"] += n
    hr["ok"] = sorted(ok_toks)
    data.kv_put(con, "mkt_jup_hour", hr)
    return n


def _gt_round_add(con, now, pools):
    """The pools of one GeckoTerminal call into the universe: (pools read, new rows, passing the filter)."""
    got = ok_n = new_n = 0
    for p in pools or []:
        g = gt_row(p) if isinstance(p, dict) else None
        if not g:
            continue
        got += 1
        tok, sym, created, s = g
        ok, why, wait = check(s, created, "market", now)
        ok_n += int(ok)
        new_n += add(con, tok, "gt", now, symbol=sym, created_ts=created, due=now if ok else now + wait,
                     nums={"mcap": s["mcap"], "liq": s["liq"], "vol_h1": s["vol_h1"]}, promote=ok)   # 14.11.: due now
    return got, new_n, ok_n


def discover_gt(con, now, net, log, deadline=None):
    """The GeckoTerminal round (gt_plan) every GT_EVERY_S, GT_REQ_PASS pages a pass (GT_REQ_PASS_FREE on the free
    host), resumed next pass where it stopped (kv mkt_gt_idx); only the requests that went out are charged; while
    the CoinGecko key's hour slice is spent it waits for the next hour (gt_route). One line when the round is done:
    "range tržište GT: N upita, M poolova, novih K, prolazi filter P[, zastoji Z (zadnji: why)]; CoinGecko ...".
    A stand-in net whose gt_pools takes no `start` (the first versions' tests) asks the whole round at once."""
    total = gt_requests()
    idx = int(data.kv_get(con, "mkt_gt_idx") or 0)
    if idx >= total:
        idx = 0
    if not idx and now - (data.kv_get(con, "mkt_gt_ts") or 0) < GT_EVERY_S:
        return 0
    left = slice_left(con, "mkt_gt_day", GT_DAY, now)
    if left < 1:
        return 0
    route = gt_route()
    if route == "hour":
        if now - (data.kv_get(con, "mkt_gt_hour_log") or 0) >= 3600:
            data.kv_put(con, "mkt_gt_hour_log", int(now))
            log("range tržište GT: satni dio CoinGecko ključa potrošen, runda čeka sljedeći sat (besplatni GeckoTerminal "
                f"ostaje minutnoj petlji); {cg_day_text(con, now)}")
        return 0
    n_req = min(GT_REQ_PASS if route == "key" else GT_REQ_PASS_FREE, total - idx, left)
    try:
        pools = net.gt_pools(n_req, start=idx, deadline=deadline)
    except TypeError:   # an injected net of the first versions: the whole round at once
        idx, n_req = 0, min(total, left)
        try:
            pools = net.gt_pools(n_req)
        except TypeError:
            pools = net.gt_pools()
    if pools is None:   # the host is held by another job: not charged, asked again next pass
        if now - (data.kv_get(con, "mkt_gt_busy_log") or 0) >= 3600:
            data.kv_put(con, "mkt_gt_busy_log", int(now))
            log("range tržište GT: GeckoTerminal drži drugi posao, runda čeka slobodnu minutu")
        return 0
    sent, done = getattr(pools, "sent", n_req), getattr(pools, "done", n_req)
    stop = getattr(pools, "stop", "")
    if sent:
        data.day_add(con, "mkt_gt_day", sent, now)
        _meter("coingecko", "range tržište", sent)
    got, new_n, ok_n = _gt_round_add(con, now, pools)
    rnd = data.kv_get(con, "mkt_gt_round") or {}
    rnd = {"sent": int(rnd.get("sent") or 0) + sent, "pools": int(rnd.get("pools") or 0) + got,
           "new": int(rnd.get("new") or 0) + new_n, "ok": int(rnd.get("ok") or 0) + ok_n,
           "stops": int(rnd.get("stops") or 0) + int(bool(stop)), "why": stop or rnd.get("why") or ""}
    # a page that failed (sent, no answer) is not asked again this round (a page that always fails never stalls it);
    # one another job held, or the pass had no time for, is asked next pass
    idx += done + int(stop.startswith("greška"))
    if idx < total:
        data.kv_put(con, "mkt_gt_idx", idx)
        data.kv_put(con, "mkt_gt_round", rnd)
        return new_n
    data.kv_put(con, "mkt_gt_idx", 0)
    data.kv_put(con, "mkt_gt_round", {})
    data.kv_put(con, "mkt_gt_ts", int(now))
    real = ""
    if rnd["pools"]:   # 11.11. (Jure): more GT pages only if the shared day has room after the first two real rounds
        k = int(data.kv_get(con, "mkt_gt_real") or 0) + 1
        data.kv_put(con, "mkt_gt_real", k)
        real = f" (prava runda {k})" if k <= 2 else ""
    stops = f", zastoji {rnd['stops']} (zadnji: {rnd['why']})" if rnd["stops"] else ""
    log(f"range tržište GT: {rnd['sent']} upita, {rnd['pools']} poolova, novih {rnd['new']}, prolazi filter "
        f"{rnd['ok']}{stops}{real}; {cg_day_text(con, now)}")
    return new_n


# ---------- the pass ----------------------------------------------------------------------------------------------------

def _near_entry(con):
    """{token: pos_pct} of active ranges in the bottom 40 % (entry close): refreshed every 5 min first."""
    out = {}
    for tok, pos in con.execute("SELECT token, pos_pct FROM ranges WHERE active=1 AND pos_pct IS NOT NULL AND pos_pct <= 40"):
        out[tok] = pos
    return out


def order(rows, near, open_toks=()):
    """The refresh order: open positions, active ranges near the bottom, event tokens, missed tokens (11.11.), then
    the 1 h volume (highest first). rows: [(token, src, vol_h1)]."""
    return sorted(rows, key=lambda r: (r[0] not in open_toks, r[0] not in near, _RANK.get(r[1], 9), -(r[2] or 0), r[0]))


def watched(con):
    return [r[0] for r in con.execute("SELECT token FROM mkt WHERE watched=1")]


def _store(con, tok, s, now, src, created_ts, keep, watched=False):
    """Store a fresh snapshot of a watched / candidate token; returns (ok, why, wait). watched: the softer keep
    thresholds of check()."""
    ok, why, wait = check(s, created_ts, src, now, keep=watched)
    if ok and src == "missed":   # 11.11. (range_missed): the owner's hard blocks (rug, honeypot / freeze, dev dump)
        from . import missed
        hb = missed.hard_block(con, tok, s, now)
        if hb:
            ok, why, wait = False, hb, missed.HARD_WAIT_S
    under = bool(s) and (s.get("mcap") or 0) < MIN_ANALYSED
    # 12.11. (owner, nalog 3): a watched token kept under 30k (liquidity >= KEEP_LIQ, check()) is stored too: its price
    # every 5 minutes, measured only (rangedca/detect: "ispod 30k")
    saved = bool(s and s.get("price") and s.get("bonded") and (not under or (watched and ok)))
    if saved:
        data.save_snap(con, tok, s)
    if keep:
        ok, why = True, ""
    if saved and under:
        why = MEASURE_WHY
    con.execute("UPDATE mkt SET checked_ts=?, last_snap=?, mcap=?, liq=?, vol_h1=?, symbol=COALESCE(?, symbol), "
                "why=? WHERE token=?", (int(now), int(now) if s else None, (s or {}).get("mcap"), (s or {}).get("liq"),
                                         (s or {}).get("vol_h1"), (s or {}).get("symbol"), why or None, tok))
    return ok, why, wait


def _created(pairs):
    """{token: the oldest pairCreatedAt of its pairs, unix s}."""
    out = {}
    for p in pairs or []:
        t = (p.get("baseToken") or {}).get("address")
        c = p.get("pairCreatedAt")
        if t and c:
            c = int(c / 1000)
            out[t] = min(out.get(t, c), c)
    return out


def _pairs(net, tokens, deadline):
    """net.pairs inside the pass's time budget; a test net without the deadline argument is called as before. 12.11.
    (owner, točka 1): any other failure (a 502, an overload, a timeout) is no snapshot this pass, never the end of it.
    Returns a data.PairList: `answered` = the tokens DexScreener answered for (data.fetch_pairs_fast says per batch; a
    plain list from a stand-in answered for all of them); the rest are unknown this pass, not priceless."""
    try:
        try:
            got = net.pairs(tokens, deadline=deadline)
        except TypeError:
            got = net.pairs(tokens)
    except Exception as e:  # noqa: BLE001
        print(f"range tržište: DexScreener nije odgovorio ({type(e).__name__}), snimke ovog prolaza preskočene",
              flush=True)
        return data.PairList()
    if isinstance(got, data.PairList):
        return got
    out = data.PairList(got or [])
    out.answered.update(tokens)
    return out


def _unanswered_line(con, now, n, log):
    """One line at most every 10 min when DexScreener left tokens of this pass unanswered (12.11.)."""
    if n and now - (data.kv_get(con, "mkt_unans_log") or 0) >= 600:
        data.kv_put(con, "mkt_unans_log", int(now))
        log(f"range tržište: DexScreener nije odgovorio za {n} tokena (502, preopterećenje ili vrijeme prolaza): ostaju "
            "na listi i pitaju se sljedeći prolaz")


ARCHIVE_WAIT_S = 86400   # 12.11.: a rug-archive token is asked again (admission) a day later (it may have recovered)
ARCHIVE_WHY = "rug arhiva: ne prati se, ne trguje i ne naoružava"


def drop_archived(con, now, archived, open_toks=(), log=print):
    """12.11. popodne (owner, točka 4): watched tokens in the rug archive (rugfilter/archive.blocked) leave the list
    (no DexScreener request for them, no range); a token with an open range round stays (its exits need prices).
    Returns the tokens dropped."""
    if not archived:
        return []
    out = [t for (t,) in con.execute("SELECT token FROM mkt WHERE watched=1").fetchall()
           if t in archived and t not in set(open_toks)]
    for t in out:
        con.execute("UPDATE mkt SET watched=0, next_ts=?, why=? WHERE token=?", (int(now + ARCHIVE_WAIT_S), ARCHIVE_WHY, t))
    if out:
        log(f"range tržište: {len(out)} tokena iz arhive rugova maknuto s liste ({', '.join(t[:6] for t in out[:8])})")
    return out


def pass_once(con, now, net=None, log=print, signal=(), pulse=None, market_on=True, event_on=True, open_toks=(),
              hype_db=None, scan_db=None, topics_db=None, missed_on=False, archived=None):
    """One pass: discovery, refresh of the due watched tokens within the budget, admission of due universe tokens.
    Returns {"tokens": watched tokens in refresh order, "src": {token: market | event | missed}, "stats": {...}}.
    missed_on (11.11., flag range_missed): the missed tokens (rangedca/missed.py) join the list for 72 h.
    archived (12.11.): the rug archive's tokens, never refreshed nor admitted (drop_archived)."""
    from . import missed
    ensure(con)
    now = int(now)
    net = net or Net()
    t_end = time.monotonic() + PASS_BUDGET_S
    spend_line(con, now, log)
    stats = {"refreshed": 0, "reused": 0, "dropped": 0, "admitted": 0, "left": 0, "requests": 0, "new": 0}
    if market_on:
        stats["new"] += from_migrations(con, now, hype_db) + from_graduates(con, now) + from_scanner(con, now, scan_db)
        # 14.11. (owner: the tokens that survived the crash): the free sources of older living tokens, every FREE_EVERY_S
        if now - (data.kv_get(con, "mkt_free_ts") or 0) >= FREE_EVERY_S:
            data.kv_put(con, "mkt_free_ts", int(now))
            stats["new"] += from_pulse(con, now, hype_db) + from_calls(con, now) + from_ranged(con, now)
        # 14.11. večer: the network discovery has its own few seconds (DISC_NET_S); the refresh keeps PASS_BUDGET_S
        stats["new"] += discover_lists(con, now, net, log, deadline=time.monotonic() + DISC_NET_S)
        t_end = max(t_end, time.monotonic() + PASS_BUDGET_S - DISC_NET_S)
    if missed_on:
        stats["new"] += missed.from_missed(con, now, log)
    ev = from_events(con, now, topics_db) if event_on else set()
    if not event_on:
        con.execute(f"UPDATE mkt SET src={missed.fallback_sql()} WHERE src='event'", (now,))
    missed.expire(con, now, missed_on, log)
    if not market_on:   # event / missed tokens only: the market part of the list rests
        con.execute("UPDATE mkt SET watched=0 WHERE watched=1 AND src NOT IN ('event', 'missed')")
    signal = set(signal)
    pulse = set(pulse if pulse is not None else data.pulse_recent(now))
    open_toks = set(open_toks)
    archived = set(archived or ())
    drop_archived(con, now, archived, open_toks, log)
    near = _near_entry(con)
    rows = con.execute("SELECT token, src, vol_h1, last_snap, liq FROM mkt WHERE watched=1").fetchall()
    ordered = order([(t, s, v) for t, s, v, _l, _q in rows], near, open_toks)
    last = {t: l for t, _s, _v, l, _q in rows}
    liquid = {t for t, _s, _v, _l, q in rows if (q or 0) >= KEEP_LIQ}   # 12.11.: a price at least every 5 min
    srcs = {t: s for t, s, _v in ordered}
    hot = {t for t, _s, _v in ordered[:HOT_N]}
    due, due_rest = [], []
    for t, s, v in ordered:
        if t in signal:
            continue   # the signal pass snapshots it every minute
        if t in liquid:   # 12.11. (owner, nalog 3): every 5 min whatever its place in the order (HOT_N)
            every = PRICE_EVERY_S - PASS_GAP_S
        else:
            every = (HOT_EVERY_S if t in hot else COLD_EVERY_S) - SLACK_S
        if now - (last.get(t) or 0) < every:
            continue
        if t in pulse:   # the hype scan snapshotted it in the last 150 s: its token_pulse rows are the series
            stats["reused"] += 1
            # 12.11.: that row may be PULSE_FRESH_S old; a liquid token counts from there, so its 5 minutes hold
            con.execute("UPDATE mkt SET last_snap=? WHERE token=?",
                        (int(now) - (data.PULSE_FRESH_S if t in liquid else 0), t))
            continue
        (due if t in liquid else due_rest).append(t)
    due += due_rest   # 12.11.: the liquid tokens first, so a short hour drops the others first
    if stats["reused"]:
        data.day_add(con, "mkt_reuse_day", stats["reused"], now)
    allowed = min(MAX_REQ_PASS, slice_left(con, "mkt_dex_day", DEX_DAY, now))
    need = -(-len(due) // 30)
    if need > allowed:
        keep = due[:allowed * 30]
        stats["dropped"] = len(due) - len(keep)
        if now - (data.kv_get(con, "mkt_drop_log") or 0) >= 600:
            data.kv_put(con, "mkt_drop_log", int(now))
            log(f"range tržište: strop DexScreenera ({data.day_used(con, 'mkt_dex_day', now)}/{DEX_DAY} danas, ovaj sat "
                f"još {allowed} upita): preskočeno {stats['dropped']} tokena najmanjeg volumena")
        due = keep
    if due:
        n_req = -(-len(due) // 30)
        data.day_add(con, "mkt_dex_day", n_req, now)
        _meter("dexscreener", "range tržište", n_req)
        stats["requests"] += n_req
        pairs = _pairs(net, due, t_end)
        best = data.best_pairs(pairs)
        made = _created(pairs)
        for t in due:
            if t not in pairs.answered:   # 12.11.: a failed / unsent batch: unknown, kept, asked again next pass
                stats["unanswered"] = stats.get("unanswered", 0) + 1
                continue
            p = best.get(t)
            s = data.snap_of(p, now) if p else None
            src = srcs.get(t, "market")
            ok, why, wait = _store(con, t, s, now, src, made.get(t), t in open_toks, watched=True)
            if made.get(t):
                con.execute("UPDATE mkt SET created_ts=? WHERE token=?", (made[t], t))
            stats["refreshed"] += int(bool(s))
            if not ok:
                con.execute("UPDATE mkt SET watched=0, next_ts=?, why=? WHERE token=?", (int(now + wait), why, t))
                stats["left"] += 1
    # admission: due universe tokens (event tokens first, then the known volume), within the discovery share
    n_w = con.execute("SELECT COUNT(*) FROM mkt WHERE watched=1").fetchone()[0]
    room = min(DISC_REQ_PASS, MAX_REQ_PASS - stats["requests"], slice_left(con, "mkt_dex_day", DEX_DAY, now),
               slice_left(con, "mkt_disc_day", DISC_DAY, now))   # discovery never eats the refresh's share
    if room > 0:
        cond = "" if market_on else " AND src IN ('event', 'missed')"
        cand = [r for r in con.execute(
            f"SELECT token, src, vol_h1, created_ts FROM mkt WHERE watched=0 AND next_ts <= ?{cond} "
            f"ORDER BY src='event' DESC, src='missed' DESC, COALESCE(vol_h1, 0) DESC, first_seen DESC LIMIT ?",
            (int(now), room * 30))
            if r[0] not in signal]
        for r in [r for r in cand if r[0] in archived]:   # 12.11.: not asked; looked at again a day later
            con.execute("UPDATE mkt SET next_ts=?, why=? WHERE token=?", (int(now + ARCHIVE_WAIT_S), ARCHIVE_WHY, r[0]))
        cand = [r for r in cand if r[0] not in archived]
        if cand:
            n_req = -(-len(cand) // 30)
            data.day_add(con, "mkt_dex_day", n_req, now)
            data.day_add(con, "mkt_disc_day", n_req, now)
            _meter("dexscreener", "range tržište otkrivanje", n_req)
            stats["requests"] += n_req
            pairs = _pairs(net, [r[0] for r in cand], t_end) if time.monotonic() < t_end else data.PairList()
            best = data.best_pairs(pairs)
            made = _created(pairs)
            for tok, src, _v, created in cand:
                if tok not in pairs.answered:   # 12.11.: not asked (time) or not answered: due again, not "no price"
                    stats["unanswered"] = stats.get("unanswered", 0) + 1
                    continue
                p = best.get(tok)
                s = data.snap_of(p, now) if p else None
                created = made.get(tok) or created
                ok, why, wait = _store(con, tok, s, now, src, created, False)
                if created:
                    con.execute("UPDATE mkt SET created_ts=? WHERE token=?", (created, tok))
                if not ok:
                    con.execute("UPDATE mkt SET next_ts=? WHERE token=?", (int(now + wait), tok))
                    continue
                if n_w >= MARKET_MAX:   # full: a newcomer replaces the quietest market token when it trades more
                    low = con.execute("SELECT token, vol_h1 FROM mkt WHERE watched=1 AND src='market' ORDER BY "
                                      "COALESCE(vol_h1, 0) LIMIT 1").fetchone()
                    if not low or (src not in _RANK and (low[1] or 0) >= ((s or {}).get("vol_h1") or 0)) \
                            or low[0] in open_toks:
                        con.execute("UPDATE mkt SET next_ts=?, why=? WHERE token=?", (int(now + 3600), "lista puna", tok))
                        continue
                    con.execute("UPDATE mkt SET watched=0, next_ts=?, why=? WHERE token=?",
                                (int(now + 3600), "istisnut: najmanji volumen na punoj listi", low[0]))
                    n_w -= 1
                con.execute("UPDATE mkt SET watched=1, watched_ts=? WHERE token=?", (int(now), tok))
                n_w += 1
                stats["admitted"] += 1
    _unanswered_line(con, now, stats.get("unanswered", 0), log)
    con.commit()
    universe_line(con, now, log)
    rows = con.execute("SELECT token, src, vol_h1 FROM mkt WHERE watched=1").fetchall()
    ordered = order(rows, near, open_toks)[:MARKET_MAX]
    stats["watched"] = len(ordered)
    stats["events"] = sum(1 for _t, s, _v in ordered if s == "event")
    stats["missed"] = sum(1 for _t, s, _v in ordered if s == "missed")
    return {"tokens": [t for t, _s, _v in ordered], "src": {t: s for t, s, _v in ordered}, "stats": stats,
            "event_tokens": ev}


def universe_line(con, now, log=print, every_s=3600):
    """Once an hour (11.11., faza 1: why the list stays short): the universe by source, watched / waiting, and the
    commonest reasons a token is not watched."""
    if now - (data.kv_get(con, "mkt_uni_log") or 0) < every_s:
        return None
    data.kv_put(con, "mkt_uni_log", int(now))
    vias = {}
    for via, n in con.execute("SELECT via, COUNT(*) FROM mkt GROUP BY via"):
        for v in (via or "?").split(","):
            vias[v] = vias.get(v, 0) + n
    w = con.execute("SELECT COUNT(*) FROM mkt WHERE watched=1").fetchone()[0]
    due = con.execute("SELECT COUNT(*) FROM mkt WHERE watched=0 AND next_ts <= ?", (int(now),)).fetchone()[0]
    wait = con.execute("SELECT COUNT(*) FROM mkt WHERE watched=0 AND next_ts > ?", (int(now),)).fetchone()[0]
    whys = {}
    for why, n in con.execute("SELECT why, COUNT(*) FROM mkt WHERE watched=0 AND why IS NOT NULL GROUP BY why"):
        k = (why or "").split(" $")[0].split(" (")[0]
        whys[k] = whys.get(k, 0) + n
    top = ", ".join(f"{k} {n}" for k, n in sorted(whys.items(), key=lambda kv: -kv[1])[:6])
    text = (f"range tržište svemir: {sum(1 for _ in con.execute('SELECT 1 FROM mkt'))} tokena "
            f"({', '.join(f'{k} {n}' for k, n in sorted(vias.items(), key=lambda kv: -kv[1]))}); prati {w}, čeka provjeru "
            f"{due}, odgođeno {wait}; razlozi: {top or '-'}")
    # 14.11. večer (CLAUDE.md: cost per source and what it brought): the watched tokens and the active ranges by the
    # source that found them (a token found by several counts for each)
    w_by, a_by = by_source(con)
    if w_by:
        text += "; prati po izvoru: " + ", ".join(f"{k} {n}" for k, n in sorted(w_by.items(), key=lambda kv: (-kv[1], kv[0])))
        text += "; aktivni rasponi po izvoru: " + (", ".join(f"{k} {n}" for k, n in sorted(
            a_by.items(), key=lambda kv: (-kv[1], kv[0]))) or "-")
    log(text)
    return text


def by_source(con):
    """({via: watched tokens}, {via: watched tokens with an active range}) of the market list (14.11. večer)."""
    w_by, a_by = {}, {}
    try:
        rows = con.execute("SELECT m.via, COALESCE(r.active, 0) FROM mkt m LEFT JOIN ranges r ON r.token = m.token "
                           "WHERE m.watched = 1").fetchall()
    except sqlite3.Error:
        return {}, {}
    for via, act in rows:
        for v in (via or "?").split(","):
            w_by[v] = w_by.get(v, 0) + 1
            if act:
                a_by[v] = a_by.get(v, 0) + 1
    return w_by, a_by


def prune(con, now, keep_tokens=()):
    """Universe rows not watched and not seen for 7 days; snapshots of market-only tokens older than KEEP_SNAPS_DAYS
    (the signal pass's tokens and open rounds keep data.KEEP_DAYS)."""
    ensure(con)
    con.execute("DELETE FROM mkt WHERE watched=0 AND COALESCE(checked_ts, first_seen) < ?", (int(now - 7 * 86400),))
    keep = list(keep_tokens)
    q = f" AND token NOT IN ({','.join('?' * len(keep))})" if keep else ""
    con.execute(f"DELETE FROM snaps WHERE ts < ? AND token IN (SELECT token FROM mkt){q}",
                (int(now - KEEP_SNAPS_DAYS * 86400), *keep))
    con.commit()


def cost_today(con, now):
    """{source: {"used", "cap"}} of today, for get_range_candidates and run_range.py status."""
    out = {name: {"used": data.day_used(con, key, now), "cap": cap()} for name, key, cap in DAY_KEYS}
    out["gt sjeme (tržište)"] = {"used": data.day_used(con, "mkt_seed_day", now), "cap": SEED_DAY}
    out["od toga rano (bez 6 h povijesti)"] = {"used": data.day_used(con, "mkt_seed_early_day", now),
                                               "cap": SEED_DAY - SEED_NEAR_RESERVE}   # 14.11. večer
    out["dexscreener signalni prolaz"] = {"used": data.day_used(con, "sig_dex_day", now), "cap": None}
    out["iz hype skena (besplatno)"] = {"used": data.day_used(con, "mkt_reuse_day", now), "cap": None}
    return out


def counts(con):
    """{"market": n, "event": n, "missed": n} of watched tokens."""
    try:
        return {s: n for s, n in con.execute("SELECT src, COUNT(*) FROM mkt WHERE watched=1 GROUP BY src")}
    except sqlite3.Error:
        return {}


def info(path=None, now=None):
    """Read-only: (counts, cost_today) for the MCP view; ({}, {}) without range.db or the table."""
    con = data.ro(path)
    if con is None:
        return {}, {}
    try:
        return counts(con), cost_today(con, now or time.time())
    except sqlite3.Error:
        return {}, {}
    finally:
        con.close()


def dump(con):
    """For run_range.py status: the watched tokens, most traded first."""
    return [dict(zip(("token", "src", "symbol", "mcap", "liq", "vol_h1", "last_snap", "via"), r)) for r in con.execute(
        "SELECT token, src, symbol, mcap, liq, vol_h1, last_snap, via FROM mkt WHERE watched=1 ORDER BY vol_h1 DESC")]
