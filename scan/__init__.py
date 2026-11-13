"""Market scanner (10.11., Jure: "skener tržišta bez callera"), behind the flag market_scan (trade/settings G11).

Every SCAN_EVERY_S (150 s) one short pass (run_scan.py once, started from start.sh):
  market.py   collect Solana pump.fun / PumpSwap / Raydium tokens from what the bot already stores (PumpPortal
              migrations and trades in hype.db, the hype scan, the KOL round's PumpSwap graduates) plus DexScreener
              profiles/boosts and a few budgeted GeckoTerminal pool pages; price them on DexScreener; run the filters
  filters.py  the copy loop's entry gates (league/copy._enter), rug collapse / archive, plus fees_filter, rug_check
              and stage_filter (final_stretch on the curve, migrated with volume)
  meta.py     every 15 min the top runners become the active metas; new tokens and caller signals that copy a
              runner's narrative (beta_score >= 0.6) become source "beta"
  xmom.py     X early momentum for passers and beta candidates (twitterapi.io, own daily USD cap; Grok's rows win)
  shadow.py   a shadow entry per source (caller, wallet, scan, beta) for every candidate that passes all filters,
              its price path, +20 % / -30 % outcomes, the EV of a TP/SL shadow trade, and the paper gate
  kandidati   every 5 min the combined list of ui/kandidati.py (one row per token over every source): its top
              tradeable rows as shadow source kandidati, Grok's overrides of a rug risk rating as grok_override
Storage: scan.db (store.py). The scanner never buys, in any mode: only get_market_signals, the MCP read tool
get_source_stats and the daily report read it.
"""
