#!/usr/bin/env python3
"""Osobe iza novčanika (osobe/): wallets grouped into persons, profiles, possible links to tracked X accounts and the
group call power. Reads the other jobs' databases only (no API call, no credits); writes osobe.db.

    python3 run_osobe.py noc        the night pass (run_sched.py "osobe", 03:20 Zagreb, heavy-job lock)
    python3 run_osobe.py status     the last pass's summary (JSON)
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "status"
    if cmd == "noc":
        try:
            os.nice(10)
        except OSError:
            pass
        from osobe import run
        try:
            run.run(log=lambda s: print(s, flush=True))
        except Exception as e:  # noqa: BLE001 - one line, the scheduler retries tomorrow
            print(f"osobe: greška {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            return 1
        return 0
    if cmd == "status":
        from osobe import run
        print(json.dumps(run.summary(), ensure_ascii=False, indent=1))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
