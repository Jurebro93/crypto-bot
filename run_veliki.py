#!/usr/bin/env python3
"""Veliki tokeni — range (15.11., vlasnik: "Useless, Troll i slično: kad nađu dno ... 5-10 % u kratkom vremenu ...
hvataj range velikih tokena"; "testiraj povijesno, NE računajući velike padove Bitcoina"): veliki/universe (the list)
-> veliki/store (15m / 1h candles, BTC) -> veliki/walk (the grid, the walk-forward per size, with / without BTC crashes)
-> veliki.db, output/veliki.md, log lines "veliki: ...". The demo trades (veliki/live, league/auto.fast_loop) read the
list and the live rule from veliki.db.

    python3 run_veliki.py list     the list + candles + BTC (after a deploy at ~2 min, then every 3 h; light, network
                                   bound, outside the heavy lock: the demo can trade as soon as zones exist)
    python3 run_veliki.py once     the backtest after a deploy (start.sh: low priority under the heavy lock, VEL_BUDGET_S
                                   ~15 min); skipped when the last run is younger than MIN_GAP_S (--force runs anyway)
    python3 run_veliki.py night    nightly, 01-06 Zagreb, once a day (start.sh: ops.heavy --night): list + backtest
    python3 run_veliki.py report   the markdown of the latest run
    python3 run_veliki.py status   the summary (list, zones, backtest, demo, real-money gate), one screen
"""
import datetime as dt
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
MIN_GAP_S = int(os.environ.get("VEL_MIN_GAP_S", str(3 * 3600)))


def in_night(now):
    try:
        from ops import heavy
        return heavy.night_now(dt.datetime.fromtimestamp(now, dt.timezone.utc))
    except Exception:  # noqa: BLE001
        from zoneinfo import ZoneInfo
        return 1 <= dt.datetime.fromtimestamp(now, ZoneInfo("Europe/Zagreb")).hour < 6


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "once"

    def log(s):
        print(s, flush=True)
    from veliki import store, walk
    now = int(time.time())
    if cmd == "list":
        walk.refresh(now, log)
        return 0
    if cmd in ("once", "night"):
        last_ts, last_day = store.last()
        if cmd == "night":
            if "--force" not in argv and not in_night(now):
                return 0
            if "--force" not in argv and last_day == time.strftime("%Y-%m-%d", time.gmtime(now + 3600)):
                return 0
            walk.refresh(now, log)
        elif "--force" not in argv and last_ts and now - int(last_ts) < MIN_GAP_S:
            log(walk.PREFIX + f"zadnji backtest prije {(now - int(last_ts)) / 60:.0f} min, preskačem")
            return 0
        try:
            os.nice(5)
        except OSError:
            pass
        walk.run(now=now, log=log, mode=cmd)
        return 0
    if cmd == "report":
        _ts, data = store.latest()
        print(walk.markdown(data))
        return 0
    if cmd == "status":
        from veliki import view
        print(json.dumps(view.summary(), ensure_ascii=False, indent=1, default=str))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
