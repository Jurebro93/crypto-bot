"""Range + DCA strategy (flag range_dca, 10.11., Jure: "range_dca, start paper").

A bonded token that keeps bouncing between a floor and a ceiling (Hope on 10.11.: bought 50-60k with a second lot on
the dip, sold +40-60 %) is traded inside that range: lot 1 at the bottom, lot 2 (DCA) 10-15 % lower, half out when
the top zone is reached, the rest at the top or on a 10 % trailing stop if the top breaks.

    detect.py    the range from minute candles: zones, touches, recoveries, range_score and its six components (pure)
    rules.py     entry, lot 2 and exit rules (pure; the trader and the backtest use the same functions)
    data.py      range.db (DATA_DIR): our own DexScreener snapshots, GeckoTerminal seed candles, the computed ranges;
                 the minute series of a token merged from what the bot already has
    holders.py   "transfer holders net-selling" check, Helius, capped and metered, log-only unless RANGE_HOLDER_RULE=act
    trade.py     entries (league/auto.loop, 20 s) and exits (league/auto.fast_loop, 1 s) on the demo accounts,
                 rounds in league.db range_rounds, the live gate (>= 20 paper rounds with EV > 0)
    backtest.py  the same rules over stored candles -> output/range-backtest-*.json/.md and the log
    run_range.py once (start.sh, every minute) | backtest | status

Data sources, in this order (CLAUDE.md: prefer what we have, measure and cap every paid call):
  1. hype.db token_pulse: DexScreener numbers of every token the hype scan keeps (every ~2 min, free, already paid
     for by nobody). Price, MC, liquidity, volume m5/h1, buys/sells m5/h1.
  2. minute.db call_candles: GeckoTerminal 1-minute OHLCV the KOL measurement already stored around calls.
  3. range.db snaps: our own DexScreener poll, once a minute, ONLY for candidates the hype scan does not snapshot
     (open range positions first), at most RANGE_MAX_TOKENS (40) tokens = 1-2 free requests a minute.
  4. range.db gt_candles: one GeckoTerminal minute-OHLCV request (1000 candles, ~16 h) to seed a candidate that has
     less than 6 h of history; at most RANGE_GT_DAY (60) a day, each token at most once a day. With the CoinGecko key
     these come out of the shared 3000-a-day budget (event_calendar/http counts them), so 2 % of it at most.
  5. Helius getTransactionsForAddress on the pool, only for tokens with an OPEN range position, every 15 min, at most
     RANGE_HELIUS_CREDITS_DAY (3000) credits a day (~10 credits a page of 100 transactions).
Flag off: run_range.py reads the flag and ends; the league loops read one cached flag and do nothing.

11.11. (Jure: "širi range watchlist + event tokeni s Grokom"; market.py, flags range_market G20 and event_tokens G19):
the 40 above (RANGE_MAX_TOKENS) is both a cap and a narrow universe: only tokens our own signals name. The market
watchlist adds up to RANGE_MARKET_MAX (400) bonded tokens of the whole market (PumpPortal migrations, KOL graduates,
the scanner's priced tokens, DexScreener lists, GeckoTerminal trending / top volume, Birdeye only with its key) and
the event topics' tokens, with their own per-source day caps; their series are 5 / 15-minute DexScreener snapshots
in the same range.db snaps (detection reads timestamps, so a 5-minute series finds a range). Every range carries its
source: signal > event > market. A market / event token is traded only on the demo account (paper), never with real
money.
    market.py    the market watchlist: universe, filter, budgeted refresh, the daily cost line per source

11.11. (Jure: "rangedca flip / pauza / stop", flag range_flip G26, default off): a confirmed break up (a 5-minute close
above the top by max(2 %, ATR) with 1.5 x the median volume) makes the old top the candidate for the new bottom (no
entries until 2 retests hold), a confirmed break down pauses the token (the old bottom = resistance, no entries until a
range forms under it), the stop is range_low_low - 1.5 x ATR (5-20 %) instead of x 0.85. detect.flip_step (the
state, range.db range_flip), rules.new_range (the new rules), trade.flip_roles (off / shadow / paper / live past
gate.flip_refusal), backtest FlipCompare (today's rules vs the new ones, nightly, range.db kv flip_backtest).
"""
