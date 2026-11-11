#!/usr/bin/env python3
"""Fast path (fast/, flag fast_path G24, 11.11. Jure): every signal of a followed wallet or influencer gets the full
analysis at once, before the decision.

    python3 run_fast.py loop      the worker (start.sh: low keep fast; time-sensitive, never under ops.heavy --night):
                                  queue every 0.5 s or on a wake-up, 20 checks at once, outcomes, the 23:30 report;
                                  flag off: it only reads the flag every 15 s
    python3 run_fast.py once      one pass of the loop (the jobs it starts run to the end)
    python3 run_fast.py report    today's report and cost line now
    python3 run_fast.py status    the last decisions as get_fast_checks answers
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def main(argv=None):
    try:   # errors go to Sentry (ops/sentry.py) like every kept process; a no-op without SENTRY_DSN, never stops the start
        from ops import sentry
        sentry.init("fast")
    except Exception as e:  # noqa: BLE001
        print(f"sentry: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("loop", "once", "report", "status"))
    a = ap.parse_args(argv)

    def log(s):
        print(s, flush=True)
    if a.cmd in ("loop", "once"):
        from fast import worker
        w = worker.Worker(log=log)
        if a.cmd == "loop":
            log("fast: radnik pokrenut (zastavica fast_path)")
            w.loop()
        else:
            w.step(woke=True)
            w.stop(wait=True)
    elif a.cmd == "report":
        from fast import report
        for ln in report.lines(report.daily()):
            log(ln)
    else:
        from fast import view
        print(json.dumps(view.mcp(limit=20), ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
