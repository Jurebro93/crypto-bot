"""BNB Smart Chain (BSC) (19.11., vlasnik: "dodaj BNB chain i praćenje novčanika; popuni preko noći").

The Solana tool "kupuje prije pumpe" (insajderi/events.py, insajderi/prijepumpe.py, league/mjera.py) on BSC, with the
same rules and wording wherever the chain does not force a difference. Analysis and measurement only: there is no BNB
executor and nothing here trades.

  keccak.py  Keccak-256 (event topics, selectors)
  rpc.py     the free public JSON-RPC (48.club for logs, publicnode for the rest), splitting, backoff, call counts
  izvor.py   GeckoTerminal (through the repo's shared gate), DexScreener, Binance market data (BNB / SOL in USD)
  pumpe.py   Step 1: the universe (memecoins 30k-200 M, liquidity >= 25k), candles, pumps by the Solana rules, tiers
  swaps.py   Swap logs (PancakeSwap v2 / v3 / Infinity CL, Uniswap v2 / v3) -> trades; the trader by Transfer chain
  chain.py   Step 2: each pump's windows read slice by slice, coverage, participants; pruning of old swaps
  klasa.py   Step 3: insajderi/prijepumpe.classify on the BSC rows + "ugovor" / "router", the funnel
  prati.py   Step 4: the tracking poller and the measurement (bnb_mjera, league/mjera semantics, its own table)
  run.py     the passes; report.py output/bnb_novcanici.md; pogled.py the read helpers for the UI
  store.py   bnb.db, the configuration (bnb/config.json), BNB_ON (dormant unless 1)

Sources measured 19.11. (scratchpad izvori.md, summarised in the module texts): all free, no key.
"""
