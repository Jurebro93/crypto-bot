#!/usr/bin/env python3
"""Konsenzus izvora (15.11., vlasnik: "hitno pronađi profitabilnu strategiju kombiniranjem profitabilnih novčanika i
influencera"): konsenzus/research (stream -> rolling source scores -> candidates -> walk-forward with an untouched
holdout) -> konsenzus.db, output/konsenzus.md, log lines "konsenzus: ...". Read-only on every other database, no API
call, no cost. The live entries (konsenzus/live, league/auto.loop) read the best candidate from konsenzus.db.

    python3 run_konsenzus.py once     after a deploy (start.sh: low priority under the heavy lock, a time budget);
                                      skipped when the last run is younger than MIN_GAP_S (--force runs anyway)
    python3 run_konsenzus.py night    nightly, 01-06 Zagreb, once a Zagreb day (start.sh: ops.heavy --night)
    python3 run_konsenzus.py report   the markdown of the latest run
    python3 run_konsenzus.py status   the best candidate, its proof and the demo so far, one screen
"""
import datetime as dt
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
MIN_GAP_S = int(os.environ.get("KONSENZUS_MIN_GAP_S", str(3 * 3600)))


def in_night(now):
    try:
        from ops import heavy
        return heavy.night_now(dt.datetime.fromtimestamp(now, dt.timezone.utc))
    except Exception:  # noqa: BLE001
        from zoneinfo import ZoneInfo
        return 1 <= dt.datetime.fromtimestamp(now, ZoneInfo("Europe/Zagreb")).hour < 6


def _last(path=None):
    from konsenzus import store
    con = store.ro(path)
    if con is None:
        return None, None
    try:
        return store.kv_get(con, "last_ts"), store.kv_get(con, "last_day")
    finally:
        con.close()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "once"

    def log(s):
        print(s, flush=True)
    from konsenzus import research, store
    now = int(time.time())
    if cmd in ("once", "night"):
        last_ts, last_day = _last()
        if cmd == "night":
            if "--force" not in argv and not in_night(now):
                log(research.PREFIX + "izvan noćnog prozora 01-06, ništa")
                return 0
            if "--force" not in argv and last_day == research.day_of(now):
                return 0
        elif "--force" not in argv and last_ts and now - int(last_ts) < MIN_GAP_S:
            log(research.PREFIX + f"zadnji izračun prije {(now - int(last_ts)) / 60:.0f} min, preskačem")
            return 0
        try:
            os.nice(5)   # under ops.heavy (nice 10) already; alone: low priority anyway
        except OSError:
            pass
        research.run(now=now, log=log, mode=cmd)
        return 0
    if cmd == "report":
        _ts, data = store.latest()
        print(research.markdown(data))
        return 0
    if cmd == "status":
        from konsenzus import view
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
    try:   # 19.11. (vlasnik: influenceri i Telegram jednom u 5 dana, ops/drustveni.py): outside the window it ends at once
        from ops import drustveni
        drustveni.gate_main()
    except ImportError:
        pass
    sys.exit(main())
