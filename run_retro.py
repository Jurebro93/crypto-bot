"""Retrospective study of pump.fun tokens that exploded (see retro/).

  python3 run_retro.py sample --days 2026-10-08:2026-10-22 --rand 125 --grad 100
  python3 run_retro.py fetch            # trades (Helius), creators, DexScreener, metadata, Gecko series
  python3 run_retro.py analyze          # features + correlations -> output/retro-report.md
"""
import argparse
import calendar
import os
import sys
import time

from retro import chain, collect

ROOT = os.path.dirname(os.path.abspath(__file__))


def _day(s):
    return calendar.timegm(time.strptime(s, "%Y-%m-%d"))


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["sample", "fetch", "repair", "analyze"])
    p.add_argument("--db", default=os.environ.get("RETRO_DB", os.path.join(ROOT, "retro.db")))
    p.add_argument("--days", default="2026-10-08:2026-10-22")
    p.add_argument("--rand", type=int, default=125, help="time slices of 20 random creations")
    p.add_argument("--grad", type=int, default=100, help="time slices of 20 random graduations")
    p.add_argument("--pages", type=int, default=40, help="max 100-tx pages per token (10 credits each)")
    p.add_argument("--rand-pages", type=int, default=10)
    p.add_argument("--limit", type=int)
    p.add_argument("--seed", type=int, default=0, help="add to the sampling seeds to draw more slices")
    p.add_argument("--steps", default="trades,creators,dex,meta,series")
    a = p.parse_args(argv)
    con = collect.connect(a.db)
    start, end = (_day(x) for x in a.days.split(":"))
    if a.cmd == "sample":
        print("rand +", collect.sample_creations(con, start, end, a.rand, seed=1 + 10 * a.seed))
        print("grad +", collect.sample_graduations(con, start, end, a.grad, seed=2 + 10 * a.seed))
    elif a.cmd == "fetch":
        steps = a.steps.split(",")
        if "trades" in steps:
            collect.fetch_all(con, "rand", a.rand_pages, limit=a.limit)
            collect.fetch_all(con, "grad", a.pages, limit=a.limit)
        if "creators" in steps:
            collect.creators_all(con)
        if "dex" in steps:
            collect.dex_all(con)
        if "meta" in steps:
            collect.meta_all(con)
        if "series" in steps:
            collect.series_all(con)
        if "series_helius" in steps:
            collect.series_helius(con, limit=a.limit)
    elif a.cmd == "repair":
        print("repaired", collect.repair(con))
    else:
        from retro import analyze
        analyze.main(con, os.path.join(ROOT, "output"))
    print(f"Helius credits used by this run: {chain.credits_used()}", file=sys.stderr)


if __name__ == "__main__":
    main()
