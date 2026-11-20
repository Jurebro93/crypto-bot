#!/usr/bin/env python3
"""Insajderi 2.0 (15.11., vlasnik): who bought before the influencer calls / the big jumps and sold into them, are they
one owner, can WE copy them at our constraints (bonded, MC >= 5M) and the "pametni novac" list (insajderi/).

    python3 run_insajderi.py once [--credits N]    after a deploy (start.sh, ~10 min, ops.heavy): existing data first,
                                                   Helius at most 40 % of the day's cap
    python3 run_insajderi.py night [--credits N]   01-06 Zagreb (ops.heavy --night), at most once in 20 h
    python3 run_insajderi.py incr [--credits N]    light: new events of the last 2 days, no Helius by default
    python3 run_insajderi.py report                the log lines and output/insajderi.md, output/pametni_novac.md
    python3 run_insajderi.py budget                the Helius day cap and what was spent today

20.11. (2): once / night / incr run as child processes, "--stage a" (events, Helius), "--stage b" (the list, the copy
tests), "--stage c" (trending, smart money, kol, the lines), so each starts fresh (see stages()); INSAJDERI_STAGES=0
runs the whole pass here.

once / night / incr end with the pass of the influencers' probably linked wallets (insajderi/kolwallets.py, 16.11.:
the seed list insajderi/kol_seed.json, its own small share of the same Helius day cap, the log line "insajderi kol:
..."); report prints its last line too.

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
    stage = a[a.index("--stage") + 1] if "--stage" in a and a.index("--stage") + 1 < len(a) else None
    if stage not in (None, "a", "b", "c"):
        print("insajderi2: --stage je a, b ili c", flush=True)
        return 2
    if stage is None:   # a stage child keeps the nice level it inherited (os.nice adds)
        try:
            os.nice(int(os.environ.get("INSAJDERI_NICE", "10")))   # a part of the resources: low priority always
        except (OSError, ValueError):
            pass
    from insajderi import run
    t = time.time()
    if stage is None and kind != "report" and os.environ.get("INSAJDERI_STAGES", "1") == "1":
        rc = stages(kind, a)
        if rc == 0:
            print(f"insajderi2: prolaz {kind} gotov za {time.time() - t:.0f} s", flush=True)
        return rc
    res = run.run(kind, credits=credits, log=lambda m: print(m, flush=True), stage=stage)
    if stage in ("a", "b"):   # 3: nothing left for the next stage (skipped, or finished here)
        return 0 if (res or {}).get("next") else 3
    if stage is None:
        print(f"insajderi2: prolaz {kind} gotov za {time.time() - t:.0f} s", flush=True)
    return 0


def stages(kind, argv):
    """20.11. (2), production: the full pass was stopped by the memory watchdog at 869 MB; what the events and the
    Helius read (6 threads, full transactions) had once held stayed with the process, and the analysis came on top. Now
    the pass is up to three child processes run one after the other: "a" (događaji, lanac), "b" (the list, the copy
    tests) and "c" (trending, smart money, kol, the summary and the lines), each "run_insajderi.py <kind> --stage
    a|b|c" (the same name for ops/health's watchdog and ops/cpuguard), sharing the log (stdout) and handing over
    through insajderi.db (i2_kv pass_state: the pass's time, the clock's stages and cuts, the summary so far). A child
    that fails or is stopped fails the pass: one line, a non-zero exit (start.sh: "insajderi2 nije uspio"). A stage
    exits 3 when nothing is left for the next one (the once / night gap; incr, a cut or a skipped list end in "b").
    INSAJDERI_STAGES=0: the whole pass in this process, as before."""
    import subprocess
    rest = argv[1:] if argv and argv[0] == kind else list(argv)
    base = [sys.executable, os.path.abspath(__file__), kind] + rest
    what = {"a": "događaji i Helius", "b": "popis i kopija", "c": "ostalo i kol"}
    for st in ("a", "b", "c"):
        r = subprocess.run(base + ["--stage", st])
        if st != "c" and r.returncode == 3:
            return 0
        if r.returncode != 0:
            how = f"signal {-r.returncode}" if r.returncode < 0 else f"kod {r.returncode}"
            print(f"insajderi2: dio prolaza {st} ({what[st]}) nije uspio ({how})", flush=True)
            return 128 - r.returncode if r.returncode < 0 else r.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
