#!/usr/bin/env python3
"""Oscilator (15.11., vlasnik: "token koji ide gore-dolje tijekom dana ... 50 puta dnevno, 1-2 $ na svakom"):
oscilator/walk (the scanner per token-day -> the walk-forward of the top 10 with the scalp rule per size -> the range
scalp on the same token-days) -> oscilator.db, output/oscilator.md, log lines "oscilator: ...". Read-only on every other
database, no API call, no cost. The demo trades (oscilator/live, league/auto.fast_loop) read today's top 10 from it.

    python3 run_oscilator.py once     after a deploy (start.sh: low priority under the heavy lock, OSC_BUDGET_S ~15 min);
                                      skipped when the last run is younger than MIN_GAP_S (--force runs anyway)
    python3 run_oscilator.py night    nightly, 01-06 Zagreb, once a Zagreb day (start.sh: ops.heavy --night)
    python3 run_oscilator.py fixtures the same on tests/fixtures range_*.json.gz (local; writes nothing but the report)
    python3 run_oscilator.py report   the markdown of the latest run
    python3 run_oscilator.py status   the summary (top 10, walk-forward, demo, real-money gate), one screen
"""
import datetime as dt
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
MIN_GAP_S = int(os.environ.get("OSC_MIN_GAP_S", str(3 * 3600)))


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
    from oscilator import scan, store, walk
    now = int(time.time())
    if cmd in ("once", "night"):
        last_ts, last_day = store.last()
        if cmd == "night":
            if "--force" not in argv and not in_night(now):
                log(walk.PREFIX + "izvan noćnog prozora 01-06, ništa")
                return 0
            if "--force" not in argv and last_day == scan.day_of(now):
                return 0
        elif "--force" not in argv and last_ts and now - int(last_ts) < MIN_GAP_S:
            log(walk.PREFIX + f"zadnji izračun prije {(now - int(last_ts)) / 60:.0f} min, preskačem")
            return 0
        try:
            os.nice(5)   # under ops.heavy (nice 10) already; alone: low priority anyway
        except OSError:
            pass
        walk.run(now=now, log=log, mode=cmd)
        return 0
    if cmd == "fixtures":
        walk.run(now=now, log=log, mode=cmd, series=walk.fixture_series(), db_path=os.environ.get("OSCILATOR_DB")
                 or os.path.join(ROOT, "output", "oscilator-fixtures.db"))
        return 0
    if cmd == "report":
        _ts, data = store.latest()
        print(walk.markdown(data))
        return 0
    if cmd == "status":
        from oscilator import view
        print(json.dumps(view.summary(), ensure_ascii=False, indent=1, default=str))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    try:   # 15.11. (owner switch fokus_midcap, ops/fokus.py): a microcap job ends at once while it is on
        from ops import fokus
        fokus.gate()
    except ImportError:
        pass
    sys.exit(main())
