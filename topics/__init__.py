"""Event tokens (11.11., Jure: "event tokeni s Grokom, prvo shadow/paper"), behind the flag event_tokens (G19).

Grok reads X; when a real-world event drives meme tokens (GTA6's release, a launch, an election) it sends the topic
with submit_event_topic: a name, keywords incl. tickers ("GTA6", "GTA 6", "Grand Theft Auto", "$GTA6"), the event
time when known and a buzz score it updates (the trend). MemeSonar finds the Solana tokens that match, tells the
original from the clones and the rugs, and measures the price 24 h before, at and 24 h after the event, to learn
whether buying the rumour and selling before the event pays. Nothing here buys: the event tokens enter the range
watchlist (rangedca/market.py, source event) and get_trade_candidates (source event, never tradeable on its own);
range_dca may trade them only on the demo account while this flag is paper. Never real money.

    match.py   token-aware keyword matching: "GTA 6" == "GTA6" == "gta-6" == "$GTA6", but GTA6 != GTA != GTAV (pure)
    store.py   topics.db: event_topics, topic_tokens, topic_measure, topic_log, kv
    roles.py   main / clone / rug / other of one topic's tokens (pure; the definitions are its docstring)
    hook.py    the PumpPortal feed's real-time match of new tokens (run_live.py; queued writer, never blocks the feed)
    job.py     run_topics.py once: catch-up matching, budgeted DexScreener / Birdeye searches, roles, the measurements
    view.py    the MCP tools (submit_event_topic, get_event_topics, get_event_tokens), the Autopilot card "Eventi",
               the hourly brief's part and the kandidati source
Data cost per day (caps, env-overridable): DexScreener search <= TOPICS_DEX_DAY 1200 (free API; one query per active
topic every 10 min, at most TOPICS_MAX_ACTIVE 8 topics = 1,152), Birdeye search <= TOPICS_BIRDEYE_DAY 100 (only with
BIRDEYE_API_KEY), GeckoTerminal <= TOPICS_GT_DAY 20 (from the shared CoinGecko budget, only for a missing price point),
Helius <= TOPICS_HELIUS_DAY 1000 credits (sniper share of a < 30 min old token at 30k+). No paid X call: the X numbers
are Grok's rows and the scanner's.
"""
