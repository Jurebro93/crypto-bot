#!/usr/bin/env python3
"""momentum_scalp's data job (momentum/, flag momentum_scalp, 11.11. Jure). One short process a minute (start.sh), so
it holds no memory between passes; flag off: it reads the flag and ends (only open Grok EV gate calibration rows are
still priced, from one free DexScreener read).

    python3 run_momentum.py once        one pass (momentum/job.py); start.sh runs it every MOM_EVERY_S (60 s)
    python3 run_momentum.py backtest [--days 7] [--gt N] [--force]   the backtest over the candles we have (nightly)
    python3 run_momentum.py status      the newest signals, the base rate, the paper proof, the Grok calibration
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("once")
    b = sub.add_parser("backtest")
    b.add_argument("--days", type=int, default=7)
    b.add_argument("--gt", type=int, default=int(os.environ.get("MOM_BT_GT", "60")),
                   help="GeckoTerminal OHLCV requests for history at most (inside momentum's day cap)")
    b.add_argument("--force", action="store_true", help="also while the flag is off")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    from momentum import job
    if a.cmd == "once":
        job.once(log=lambda s: print(s, flush=True))
    elif a.cmd == "backtest":
        if job.mode() == "off" and not a.force:
            print("momentum backtest: zastavica momentum_scalp je isključena, ništa se ne radi", flush=True)
            return 0
        from momentum import backtest
        backtest.run_server(days=a.days, gt=a.gt)
    else:
        from momentum import view
        rep = view.report_data()
        for ln in view.lines(rep):
            print(ln)
        print(json.dumps(view.latest(minutes=120), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
