"""Točnost ocjena (27.11., vlasnik: "Every score shown on the site gets its own measured accuracy (last 30 days,
checked on days the model did not see)"). Measurement and display only: nothing here changes a score, a rule or a
trade, and no decision reads these tables.

  store.py   tocnost.db: `prikaz` (a score as it was shown, one row per score, subject and UTC day; written by the
             pages and by the night snapshot) and `tocnost` (the night's result per score and bucket)
  stat.py    pure counting: Wilson 90 % interval, aggregate() per bucket with the base rate and the no-lookahead window
  izvori.py  SPECS (what every score predicts, its outcome, horizon and the last tuning date) and the read-only row
             loaders over the source databases
  noc.py     the night batch (run_tocnost.py noc, run_sched.py "tocnost" at 03:00 Zagreb, heavy lock)
"""
