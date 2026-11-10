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
"""
