"""One events log for everything that happens to a token (11.11., Jure: "jedna tablica eventova").

    events/store.py     events.db: the table, emit() for the collectors (never blocks, never raises), retention,
                        the daily size log, the disk guard
    events/hooks.py     the collectors' one-line dual write (kol/collect, kol/chainwatch, live/store, ui/xfeat, kol/snap)
    events/sources.py   old table -> event rows: the 5-min sync (watermark per source), the 14-day backfill
                        (estimate first, then batches) and the parity check events vs the old tables
    events/health.py    no events of an active type for > 60 min between 08 and 24 Zagreb -> an alert
    events/outcomes.py  night: call / wallet-buy outcomes (max 1 h / 4 h / 24 h, min before max, change 24 h, EV) and
                        the scores of callers, channels and wallets; early wallets
    events/remeasure.py night: calls never measured or bad:svijeca measured from GeckoTerminal minute candles
    events/night.py     the night batch (03:00 Zagreb, ops.heavy --night): watermarks, the Helius cap, the steps
    events/evreport.py  the daily EV report per feature flag phase (23:30 Zagreb)
    events/brief.py     get_hourly_brief (MCP, read-only)

Entry point: run_events.py (tick | night | backfill | ev | parity | health | brief). The old tables stay as they are:
every collector keeps writing them; events.db is written next to them (dual write) until parity is confirmed.
"""
