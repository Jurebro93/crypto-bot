"""Insajderi 2.0 (15.11., vlasnik: "nastavi s influencerima, posebno u grupama; i dalje želim naći insajdere i botove
koji kupuju prije poziva ... alat koji i na POSTOJEĆIM podacima gleda kad su zvali, kad je cijena skočila, koji su
novčanici najviše PRODAVALI tada i jesu li isti KUPILI prije poziva (danima prije), poveži to ... i kako ih pratiti da
budemo sigurno u plusu. Dio resursa za to, veći dio ide na midcapove").

Extension 15.11. (vlasnik): every token that jumped drastically (not only after a call), its catalyst, the early
buyers of each jump, what precedes a token entering trending, and one "pametni novac" list with clusters.

  store.py     insajderi.db, config, the Helius day cap (a share of what the old microcap jobs used, usage.db)
  events.py    the event set: influencer calls with a price jump (X, Telegram, crews) and market jumps of any token
               (midcap.db candles, minute.db call candles); the catalyst of each jump
  chain.py     who traded each event: our free sources first, Helius only within the cap (the jump window of the mint,
               then the token accounts of the top / recurring sellers 7 days back); trades attributed to the signer,
               same-owner wallets merged by funding source
  score.py     per owner group across events: bought before AND sold into, distinct callers, lift vs chance, lead
               time, PnL; insajder | bot_snajper | relayer | kandidat | promatra; walk-forward confirmation
  copy.py      copyability at OUR constraints: a call after their buy within 1/3/7 d, our return after their buy with
               delay and costs (exit when they sell / stop / time), per MC bucket, walk-forward (no look-ahead)
  trending.py  entering trending: what preceded it, the "uskoro trending" score, walk-forward
  smart.py     the "pametni novac" list (early buyers of several jumps, insiders before calls, profitable holders of
               midcaps when the listing agent's table exists), clusters, the 2-3 independent clusters signal
  report.py    output/insajderi.md, output/pametni_novac.md, the log lines, the card, get_insiders2, the critic block
  live.py      the demo strategy (flag insajderi2, paper, NEVER_LIVE): their buys in real time -> demo entries
  run.py       the passes (run_insajderi.py once | night | incr | report)

Real money: never from here (NEVER_LIVE; no switch); the owner decides later with the numbers.
"""
