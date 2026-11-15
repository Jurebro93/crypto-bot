"""Veliki tokeni — range (15.11., vlasnik: "Useless, Troll i slično: kad nađu dno, vrlo vjerojatno se odbiju gore i
naprave 5-10 % u kratkom vremenu. Hvataj range velikih tokena, to su recimo sigurni ... Ako je Bitcoin stabilan /
konsolidira se, oni će rangeati i na tome trebamo profitirati"; isti dan: "testiraj range trading povijesno, NE
računajući velike padove Bitcoina ... sada se stvara novi range, iskoristi ga za veće tokene").

    universe.py  the list (15.11. popodne: the midcaps): Solana memecoins MC $5M-$150M, older than 15 d, liquidity
                 >= $150k (a real buy $500k), 24 h volume >= $100k, AMM pools only, not in the rug archive, + the
                 owner's examples ANSEM, TROLL, GOODGUY, CHILLGUY, FARTCOIN, USELESS resolved to the REAL mint
                 (copycats and fake pools refused; outside 5-150M listed as such); up to 200, + up to 40 that fell out
    metrics.py   per token: age bucket, volume persistence, BTC beta / correlation, drawdown from ATH, behaviour after
                 BTC +3 % days, bounces from the 30-day range's bottom -> category A / B / C
    store.py     veliki.db: the list, 15m / 1h candles (GeckoTerminal, incremental, the shared budget), BTC hourly and
                 daily closes (DefiLlama, free), runs, kv
    rule.py      pure: BTC crash periods, quantile zones on 1h candles (fresh range after a crash), the bounce entry on
                 15m bars, the exits, the real cost at a size (trade/cost.round_trip with the token's liquidity)
    walk.py      the backtest grid, walk-forward (pick on older days, test on newer), bootstrap by token-day, report
    live.py      the demo account's trades (flag veliki_range, paper; league/auto.fast_loop every VEL_TICK_S)
    gate.py      the real-money gate (owner switch pravi_novac_veliki, off; holdout proof at the real size)
    view.py      the card (Ostalo), MCP get_big_ranges, the OpenAI critic's block
run_veliki.py: list (after a deploy, every 3 h: the list + candles), once (the backtest after a deploy, heavy lock),
night (01-06 Zagreb, once a day), report, status.
"""
