#!/usr/bin/env python3
"""Learning loop: re-fit the hype weights per token class from outcomes, automatically and with guardrails.

    python3 run_learn.py fit              # one run over all classes, applies what passes the guardrails
    python3 run_learn.py fit --dry        # same, but only reports
    python3 run_learn.py status           # current per-class weights, pump thresholds, last runs
    python3 run_learn.py missed           # tokens that never got a paid check and still pumped
    python3 run_learn.py loop             # on the server: one run a day at learn/config.json run_at_utc

Learned weights go to LEARNED_DIR (default $DATA_DIR/learned); runs are logged to learn_runs in hype.db.
"""
import argparse
import datetime as dt
import os
import sys
import time

from learn import fit, outcomes, store, weights

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "hype.db")


def cmd_fit(a):
    con = store.connect(DB)
    rep = fit.run(con, now=time.time(), apply=not a.dry)
    for r in rep:
        flag = "PRIMIJENJENO" if r["applied"] else ("ROLLBACK" if r.get("rollback") else "bez promjene")
        print(f"{r['klasa']:<9} n={r['n']:<5} skok ≥ {r['skok']:+.0%}  {flag}: {r['note']}")
    try:  # confidence: the same facts the pop-up lists, re-weighed from outcomes (learn/confmodel.py)
        from learn import confmodel
        c = confmodel.run(con, now=time.time(), apply_model=not a.dry)
        print(f"confidence n={c['n']:<5} {'PRIMIJENJENO' if c['applied'] else 'bez promjene'}: {c['note']}")
    except Exception as e:
        print(f"confidence fit: {type(e).__name__}: {e}", file=sys.stderr)
    return rep


def cmd_status(a):
    con = store.connect(DB)
    rows, thr = outcomes.rows(con)
    for k in sorted(thr):
        n = sum(1 for r in rows if r["klasa"] == k)
        print(f"{k:<9} ishoda {n:<5} skok ≥ {thr[k]:+.0%}  težine: {'naučene' if os.path.exists(weights.path(k)) else 'osnovne'}")
    for r in store.runs(con, limit=10):
        print(f"  {dt.datetime.fromtimestamp(r['ts']):%d.%m %H:%M} {r['klasa']:<9} n={r['n']:<4} "
              f"{'primijenjeno' if r['applied'] else 'ne'}  {r['note']}")


def cmd_missed(a):
    con = store.connect(DB)
    rows, thr = outcomes.rows(con)
    for m in outcomes.missed(con, thr, hours=a.hours)[:a.top]:
        print(f"{m['max_ret']:+6.0%}  {m['symbol'] or m['token'][:8]:<12} {m['klasa']:<9} T{m['razina']}  {m['reason']}")


def cmd_loop(a):
    cfg = outcomes.config()
    hh, mm = map(int, cfg["run_at_utc"].split(":"))
    last_day = None
    while True:
        now = dt.datetime.now(dt.timezone.utc)
        if (now.hour, now.minute) >= (hh, mm) and last_day != now.date():
            try:
                cmd_fit(argparse.Namespace(dry=False))
            except Exception as e:
                print(f"learn fit: {type(e).__name__}: {e}", file=sys.stderr)
            last_day = now.date()
        time.sleep(300)


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fit")
    f.add_argument("--dry", action="store_true")
    sub.add_parser("status")
    m = sub.add_parser("missed")
    m.add_argument("--hours", type=float, default=168)
    m.add_argument("--top", type=int, default=30)
    sub.add_parser("loop")
    a = p.parse_args(argv)
    {"fit": cmd_fit, "status": cmd_status, "missed": cmd_missed, "loop": cmd_loop}[a.cmd](a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
