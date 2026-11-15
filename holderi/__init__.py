"""Holderi midcapova i listing signali (15.11., vlasnik: "For the midcaps use metrics designed for that token range: do
insiders hold a large share of supply — if yes, be careful — but the holders of large shares are often EXCHANGES ... if a
large part of the supply is sent to an external wallet previously known as an exchange wallet, that must be a STRONG
signal ... print it and clearly highlight when you think a token will be listed on an exchange"; the same evening: "If
the token is NOT yet listed on that exchange, how would anyone sell it there?"; and "Find wallets that hold large amounts
of established, profitable tokens ... what are they buying now? Cluster them").

    burze.py       exchange wallets (curated burze.json, the owner's burze_vlasnik.json, Grok / heuristics in holderi.db,
                   wallets.db cex) with confidence; heuristics; listing status per exchange (free public market lists +
                   CoinGecko by contract)
    klasa.py       top-20 classification (lp, burn, exchange, team, insider, whale, normal) and the metrics (shares,
                   insider share excluding exchanges and LP, HHI, top 10 without them), the snapshot diff
    signal.py      the listing score 0-100 (PRE-LISTING vs deposit to sell) and the insider caution
    chain.py       RugCheck (free) and Helius reads inside the daily credit cap (Budget)
    run.py         one pass: lists, snapshots (transfer watch on the top 50), traces, exchange balances, signals,
                   notification, outcomes 1 h / 24 h / 7 d against the median midcap
    profit.py      profitable diamond holders of established midcaps, what they buy (holder_buys), clusters, the digest,
                   the follow measurement
    view.py        card (Ostalo), red badge, MCP tools, the critic's block, output/holderi.md, kv "pri" for
                   veliki/prioritet (components listing / oprez)
    store.py       holderi.db
run_holderi.py: pass | status | profile <mint> | signals | md.
"""
