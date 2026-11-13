#!/usr/bin/env python3
"""Prijedlozi (proposals/, flag proposals G21, 11.11. Jure). A short process per pass, so it holds no memory between
passes; flag off: it reads the flag and ends.

    python3 run_proposals.py once      one pass (proposals/job.py); start.sh runs it every PROPOSALS_EVERY_S (150 s)
    python3 run_proposals.py night     the callers' quick-exit benchmark (01-06 Zagreb under ops.heavy --night)
    python3 run_proposals.py report    today's report per strategy now (the 23:30 one runs in events/evreport)
    python3 run_proposals.py status    the open proposals as get_proposals answers
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("once", "night", "report", "status"))
    ap.add_argument("--force", action="store_true", help="night: also while the flag is off / done today")
    a = ap.parse_args(argv)
    from proposals import job

    def log(s):
        print(s, flush=True)
    if a.cmd == "once":
        job.once(log=log)
    elif a.cmd == "night":
        job.night(log=log, force=a.force)
    elif a.cmd == "report":
        from proposals import report
        for ln in report.lines(report.daily()):
            log(ln)
    else:
        from proposals import view
        print(json.dumps(view.mcp(status="novo"), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
