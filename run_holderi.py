#!/usr/bin/env python3
"""Holderi midcapova i listing signali (holderi/): classified top holders, PRE-LISTING signals (supply to an exchange
that does not list the token yet), the insider caution for veliki/prioritet, the profitable holders' buys.

    python3 run_holderi.py pass             one pass (start.sh every HOLDERI_EVERY_S, 10 min; only with the owner switch
                                            fokus_midcap; --force runs anyway)
    python3 run_holderi.py status           counts, today's cost, the newest signals
    python3 run_holderi.py profile <mint>   one token's holder profile (JSON)
    python3 run_holderi.py signals [days]   the signals (JSON)
    python3 run_holderi.py md               writes output/holderi.md
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "status"
    if cmd == "pass":
        from holderi import run
        out = run.run_pass(log=lambda s: print(s, flush=True), force="--force" in argv)
        if out and (out.get("signals") or "--force" in argv):
            print("holderi: prolaz " + json.dumps(out, ensure_ascii=False), flush=True)
        return 0
    if cmd == "profile" and len(argv) > 1:
        from holderi import view
        print(json.dumps(view.holder_profile({"token": argv[1]}), ensure_ascii=False, indent=1))
        return 0
    if cmd == "signals":
        from holderi import view
        print(json.dumps(view.listing_signals({"days": argv[1] if len(argv) > 1 else 7}), ensure_ascii=False, indent=1))
        return 0
    if cmd == "md":
        from holderi import store, view
        con = store.connect()
        try:
            print(view.write_md(con))
        finally:
            con.close()
        return 0
    if cmd == "status":
        from holderi import burze, run, store
        con = store.connect()
        try:
            print(run.hour_line(con, run.config(), int(time.time())))
            sc = burze.seed_counts()
            print(f"adrese burzi: {sc}")
            for r in con.execute("SELECT ts, symbol, kind, exchange, score FROM signals ORDER BY ts DESC LIMIT 10"):
                print(time.strftime("%m-%d %H:%M", time.gmtime(r[0])), *r[1:])
        finally:
            con.close()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
