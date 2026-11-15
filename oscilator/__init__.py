"""Oscilator (15.11., vlasnik: "Zašto ne bismo pronašli token za koji znamo da ide gore-dolje tijekom dana i tradali ga
50 puta dnevno, uzimajući 1-2 $ na svakom (s naknadama)? ... 10 takvih tokena od ~100.000 dnevno ... manji profit,
čekaj da cijena opet padne, kupi opet").

    rule.py   the scalp rule on 1-minute bars and the cost model at a size (pure: the backtest and the demo call it)
    scan.py   per token and Zagreb day: liquidity, volume, range, trend, zigzag swings >= cost + target (pure) and the
              server's minute data (range.db / minute.db / hype.db, read-only, coverage counted)
    walk.py   the walk-forward: rank tokens by day D, trade the top 10 on day D+1 with the rule (no look-ahead), per
              size 0.1 / 0.3 / 0.5 / 1.0 SOL, bootstrap by token-day, vs every eligible token and vs the range scalp
    store.py  oscilator.db (runs, today's top 10, the proof numbers)
    live.py   the demo account's trades (flag oscilator, paper; league/auto.fast_loop every OSC_TICK_S)
    gate.py   the real-money gate (owner switch pravi_novac_oscilator, off; walk-forward proof + demo proof)
    view.py   the card (Ostalo), MCP get_oscillators, the OpenAI critic's block
run_oscilator.py runs walk.run after a deploy (low priority, a time budget) and nightly 01-06 Zagreb.
"""
