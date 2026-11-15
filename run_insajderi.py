#!/usr/bin/env python3
"""Insajderi 2.0 (15.11., vlasnik): who bought before the influencer calls / the big jumps and sold into them, are they
one owner, can WE copy them at our constraints (bonded, MC >= 5M) and the "pametni novac" list (insajderi/).

    python3 run_insajderi.py once [--credits N]    after a deploy (start.sh, ~10 min, ops.heavy): existing data first,
                                                   Helius at most 40 % of the day's cap
    python3 run_insajderi.py night [--credits N]   01-06 Zagreb (ops.heavy --night), at most once in 20 h
    python3 run_insajderi.py incr [--credits N]    light: new events of the last 2 days, no Helius by default
    python3 run_insajderi.py report                the log lines and output/insajderi.md, output/pametni_novac.md
    python3 run_insajderi.py budget                the Helius day cap and what was spent today

Runs under the owner switch fokus_midcap as an explicit, budgeted exception (ops/fokus.EXCEPTIONS). Real money: never.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    kind = a[0] if a and not a[0].startswith("-") else "once"
    credits = None
    if "--credits" in a:
        try:
            credits = int(a[a.index("--credits") + 1])
        except (IndexError, ValueError):
            print("insajderi2: --credits treba broj", flush=True)
            return 2
    if kind == "budget":
        from insajderi import store
        c, now = store.config(), int(time.time())
        con = store.connect()
        try:
            cap, how = store.helius_cap(c, now, store.paths().get("usage_db"))
            print(f"{store.PREFIX}Helius strop {cap:,} kr./dan ({how}); danas potrošeno {store.helius_spent(con, now):,}",
                  flush=True)
        finally:
            con.close()
        return 0
    if kind not in ("once", "night", "incr", "report"):
        print(__doc__)
        return 2
    try:
        os.nice(int(os.environ.get("INSAJDERI_NICE", "10")))   # a part of the resources: low priority always
    except (OSError, ValueError):
        pass
    from insajderi import run
    t = time.time()
    run.run(kind, credits=credits, log=lambda m: print(m, flush=True))
    print(f"insajderi2: prolaz {kind} gotov za {time.time() - t:.0f} s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
