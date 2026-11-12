"""Zone alarms to Grok Bot (11.11., Jure: "real-time zone alarm na Grok Bot webhook"), behind the data flag zonewatch
(trade settings G25: off = nothing is watched or posted; any other mode = watch and post while the webhook env is set).

Every token with zones is watched: the range engine's active ranges (source range: bottom, dca, top, stop in market cap
USD, rangedca/; the only source of computed zones, read from range.db, each newer computation a new zone_version), for
tokens with an open range round, an entry-ready range or an open position on the real account, and the zones Grok or
the owner arm by hand (MCP arm_zone, source manual | event, at most 2 h). Never a fixed seed (11.11.). When the market
cap enters a zone the bot POSTs one JSON alarm to the Grok Bot webhook (GROKBOT_WEBHOOK_URL / GROKBOT_WEBHOOK_KEY).

    store.py    zonewatch.db: armed_zones, zone_state, alerts, zonewatch_log, arm_log, px, kv; arm / disarm with
                validation, the caps and the hourly limit; the range sync and its versions (range_ver); the one-time
                migration that expired PR #122's fixed HOPE seed
    zones.py    pure: inside / outside with hysteresis, distance to a zone, the events (zone_enter, zone_exit,
                stop_hit, top_hit), the debounce windows
    prices.py   the numbers of a token: the snapshots the bot already stores (range.db snaps incl. the market
                watchlist, hype.db token_pulse) first, then one DexScreener batch (30 tokens a request) only for the
                tokens near a zone or armed without a fresh snapshot, inside a daily cap; unique traders from the
                PumpPortal stream we already store; the rug verdict (ui/kandidati.rug_view) cached per token
    notify.py   the POST: payload, Bearer or Standard Webhooks signing, timeout 5 s, 3 retries with backoff only on a
                network error / timeout / 429 / 5xx, zonewatch_log without the key or the URL path; post_alert(dict)
                for direct callers (team_catalyst)
    positions.py  11.11. (Jure): the real account's open positions (league.db, LEAGUE_USER; never the demo account)
                with their OWN levels: the lots' SL / TP, Smart sell's stop / trailing / next TP, an exit plan in force
                (it replaces the lots' own), the range round's stop, the owner's DCA and buy orders; PnL in % / USD /
                SOL; what the executors did since the last pass (a level sold within the second)
    job.py      one pass (run_zonewatch.py loop, every 30 s): range sync, prices, events, debounce, the alerts
                (also into events.db as type zone_alert), the positions' own levels (event position_level: sl_near,
                sl_hit, tp_hit, dca_hit; no range needed) and range_off (a held token's range switched off, once,
                with the reason), team_catalyst rows of events.db forwarded once, delivery, the daily cost line
    view.py     MCP arm_zone / get_armed_zones and the zonewatch part of get_hourly_brief

Nothing here trades (Grok only advises from the alarms). Data cost: DexScreener only (free API; at most ZONEWATCH_DEX_DAY requests a day, at most 4 a
pass), the webhook POSTs (free); no Helius, no GeckoTerminal, no paid X.
"""
