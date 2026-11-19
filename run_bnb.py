#!/usr/bin/env python3
"""BNB Smart Chain (BSC): pumps, who bought before and sold into them, the class "kupuje prije pumpe", and the
measurement of the listed wallets' new buys (bnb/). Analysis and measurement only: nothing here trades, and there is
no BNB executor.

    python3 run_bnb.py backfill [--hours H] [--events N]   the first fill (Steps 1-3), resumable, wall clock
                                                          pass_max_s["backfill"] (or H hours)
    python3 run_bnb.py pass                               production (start.sh, every 3 h): the same, bounded by
                                                          pass_max_s["pass"] and calls_day, then the tracker, then
                                                          output/bnb_novcanici.md and one line "bnb: ..."
    python3 run_bnb.py track                              the tracking poller + the measurement once
    python3 run_bnb.py report                             output/bnb_novcanici.md and the line from bnb.db

Dormant unless BNB_ON=1: unset (or anything else) every command prints one line and exits 0, no network call,
no database file. bnb.db: BNB_DB, else $DATA_DIR/bnb.db.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def _arg(a, name, cast, default=None):
    if name in a:
        try:
            return cast(a[a.index(name) + 1])
        except (IndexError, ValueError):
            return default
    return default


def main(argv=None):
    from bnb import store
    a = list(sys.argv[1:] if argv is None else argv)
    kind = a[0] if a and not a[0].startswith("-") else "pass"
    if not store.on():
        print(f"{store.PREFIX}isključeno (BNB_ON nije 1)", flush=True)
        return 0
    c, now = store.config(), int(time.time())
    con = store.connect()
    try:
        if kind in ("backfill", "pass"):
            from bnb import report, run
            hours = _arg(a, "--hours", float)
            lim = hours * 3600 if hours else (c["pass_max_s"] or {}).get(kind)
            clock = store.Clock(lim)
            out = run.fill(con, c, now, clock, kind=kind, max_events=_arg(a, "--events", int),
                           gt_budget=None if kind == "backfill" else int(c["gt_calls_pass"]))
            if kind == "pass" and not clock.over():
                from bnb import prati
                prati.run(con, c, int(time.time()), store.Clock((c["pass_max_s"] or {}).get("track")))
            report.write(con, c)
            print(report.line(con, out), flush=True)
        elif kind == "track":
            from bnb import prati
            print(prati.line(prati.run(con, c, now, store.Clock((c["pass_max_s"] or {}).get("track")))), flush=True)
        elif kind == "report":
            from bnb import report
            report.write(con, c)
            print(report.line(con), flush=True)
        else:
            print(__doc__)
            return 2
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
