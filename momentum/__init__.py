"""Momentum scalp (flag momentum_scalp, G16; 11.11. Jure: "za česte skokove od +20-30 %, prvo paper").

A bonded token that starts a jump (+5..+15 % in 5 min on 3x the hour's 5-min volume, mostly buys, more unique buyers,
no wash trading, no rug or shill-network flags) is bought on the demo account, half is sold at +15 %, the rest
trails 8 % under the peak; stop -10 %; everything out after 45 minutes. No callers needed.

    rules.py     entry / exit / base-rate / cost rules (pure; the job, the trader and the backtest share them)
    data.py      momentum.db (DATA_DIR): DexScreener minute snapshots, signals with their outcome (the base rate),
                 top 10 cache, the Grok calibration rows; the reads of PumpPortal, GeckoTerminal (capped), Helius
                 (capped), the scanner, the live list, launches and the shill network
    job.py       the data pass (run_momentum.py once, every minute): candidates -> snapshot -> entry rules -> signals;
                 the outcomes of open signals and of the Grok calibration rows
    trade.py     entries (league/auto.loop, 20 s) and exits (league/auto.fast_loop, 1 s) on the demo accounts; league.db
                 momentum_trades; paper only on PAPER_USER, LEAGUE_USER only past the live gate
    gate.py      the live gate: >= 50 closed paper trades, EV > 0, hit rate >= 45 % (trade/settings.LIVE_GATES)
    evgate.py    Grok's EV gate for autotrade (flag grok_ev_gate, G17) and its calibration (Brier, reliability)
    view.py      the MCP / brief / kandidati / report reads
    backtest.py  the last 7 days of minute candles we hold -> output/momentum-backtest-*.{json,md}
    run_momentum.py  once | backtest | status

Cost (CLAUDE.md: measure and cap every paid call): DexScreener free (2 requests a minute for 60 tokens); PumpPortal
free (already streamed); GeckoTerminal only for prequalified tokens PumpPortal does not cover, one /pools/multi request
(30 pools) a pass at most, MOM_GT_DAY 100 a day including the backtest's MOM_BT_GT 60 (~3 % of the shared 3000);
Helius only the top 10 of a token that passed everything else, 4 credits, MOM_HELIUS_DAY 2000 credits a day.
Flag off: run_momentum.py ends at once (only open Grok calibration rows are still priced, free); the league loops
read one cached flag and do nothing; an open trade keeps its exits.
"""
