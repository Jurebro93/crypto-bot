"""Konsenzus izvora (15.11.2026., vlasnik): an entry strategy from profitable influencers, Telegram channels and wallets
together, measured walk-forward over our own data, run in demo, real money only behind its own switch and proof.

    research.py  the unified point-in-time signal stream, the rolling source scores, the candidates, the walk-forward
                 with an untouched holdout (run_konsenzus.py once / night)
    store.py     konsenzus.db (runs, the current best candidate and its source selection)
    live.py      the live entries (league/auto.loop): demo always while the flag is paper; real money only through the
                 owner's switch pravi_novac_izvori AND the holdout proof (gate.py)
    gate.py      the proof rule and the switch
    view.py      the "Konsenzus izvora" card, the MCP tool get_source_strategy and the critic's block
"""
