"""Točnost ocjena (tocnost/): the night batch and a quick look.

    python3 run_tocnost.py noc [--bez-snimke]   # run_sched.py "tocnost", 03:00 Zagreb, heavy lock
    python3 run_tocnost.py pokazi               # print the newest table
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["noc", "pokazi"])
    ap.add_argument("--bez-snimke", action="store_true")
    a = ap.parse_args()
    from tocnost import noc, store
    if a.cmd == "noc":
        try:
            os.nice(10)
        except OSError:
            pass
        noc.run(snapshot=not a.bez_snimke)
        return 0
    for (score, bucket), r in sorted(store.latest(ttl=0).items()):
        print(f"{score:12} {bucket:14} n={r['n']:4} k={r['k']:4} pogodila={r['correct']} baza={r['base']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
