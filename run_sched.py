"""One small scheduler for the loops that work only now and then (learning, exits, market volume, spend, correlations).

Before, each of them was its own Python process sleeping 24/7: ~18 MB each just to exist, and after its first
daily fit a process kept the fit's memory for good (Python does not hand it back). Here every run is a short
process that ends and gives its memory back; this process only keeps the clock. Same commands, same times:

  learn   run_learn.py fit      once a day after learn/config.json run_at_utc (UTC), checked every 5 min
  exits   run_exits.py fit      once a day after exits/config.json run_at_utc (UTC), checked every 5 min
  market  run_market.py collect every MARKET_EVERY_MIN minutes (default 60)
  usage   run_usage.py tick     every USAGE_EVERY_MIN minutes (default 15)
  corr    run_corr.py run       every CORR_EVERY_MIN minutes (default 60)
"""
import datetime as dt
import json
import os
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))


def run(name, args):
    code = subprocess.call([sys.executable, os.path.join(ROOT, args[0]), *args[1:]], cwd=ROOT)
    if code:
        print(f"{name}: izlaz {code}", file=sys.stderr, flush=True)
    return code


def every(name, args, minutes):
    while True:
        run(name, args)
        time.sleep(minutes * 60)


def daily(name, args, config):
    """Same rule as the old in-process loops: after run_at_utc, once per UTC day (again after a restart)."""
    last_day = None
    while True:
        try:
            with open(os.path.join(ROOT, config)) as f:
                hh, mm = map(int, json.load(f)["run_at_utc"].split(":"))
            now = dt.datetime.now(dt.timezone.utc)
            if (now.hour, now.minute) >= (hh, mm) and last_day != now.date():
                run(name, args)
                last_day = now.date()
        except Exception as e:  # noqa: BLE001 - the scheduler must not die (start.sh restarts everything)
            print(f"{name}: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        time.sleep(300)


JOBS = [
    ("learn", daily, (["run_learn.py", "fit"], "learn/config.json")),
    ("exits", daily, (["run_exits.py", "fit"], "exits/config.json")),
    ("market", every, (["run_market.py", "collect"], float(os.environ.get("MARKET_EVERY_MIN", "60")))),
    ("usage", every, (["run_usage.py", "tick"], float(os.environ.get("USAGE_EVERY_MIN", "15")))),
    ("corr", every, (["run_corr.py", "run"], float(os.environ.get("CORR_EVERY_MIN", "60")))),
]


def main():
    for name, fn, args in JOBS:
        threading.Thread(target=fn, args=(name, *args), name=name, daemon=True).start()
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
