"""Prijedlozi (flag proposals, G21; 11.11. Jure): one list of trade proposals from every strategy on the Autopilot
page and in the MCP tool get_proposals. Paper first: nothing here buys on the real account; the owner taps Kupi
(Brza kupnja, prefilled) and Grok autotrade may use get_proposals within its existing limits.

    strategies.py  the eight proposal sources (range, momentum, influencer, group, insider, event, catalyst, grok):
                   entry, exit, measured record, expiry
    calib.py       p_tp from a record (shrunk toward no edge, Wilson 90 %) and Grok's calibration (buckets, shrink to
                   identity, monotone)
    build.py       merge per token on ui/kandidati.build (the same sources, market, rug view, run-up, crews and keyed
                   blocks), cost by liquidity, EV, blocks, independent sources, ranking
    job.py         the pass (run_proposals.py once, every 150 s, low priority): proposals.db sync (novo / isteklo),
                   near misses, price points, after-outcomes; the night step: the callers' quick-exit benchmark
    outcomes.py    what happened 1 h and 4 h after every proposal (missed opportunities)
    paper.py       paper mode: the demo account takes a waiting proposal with its exit when the price is in its entry
                   zone and above its stop, never next to a range_dca round (league/auto.loop, 11.11.)
    report.py      the 23:30 report per strategy and the day's missed risers (events/evreport)
    view.py        the Autopilot card, its fragment and get_proposals (read-only, cached)
    store.py       proposals.db (DATA_DIR)

Modes: off nothing at all (the pass ends at once, the card and the tool are empty); shadow the list and every
measurement; paper also the demo account's entries; live is refused (paper.live_refusal): no new automatic path to
the real account. Cost (CLAUDE.md): DexScreener only (free), at most PROPOSALS_DEX_DAY (300) batch requests a day for
proposals the pass no longer reads; no Helius, no paid X.
"""
