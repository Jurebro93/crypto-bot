"""Stranice tokena (tokenstranice/, 15.11.2026.): satno osvježavanje i mišljenja AI-ja.

    python3 run_tokenstranice.py sat          # run_sched svaki sat: sve stranice iz naših baza + mala serija mišljenja,
                                              # jedan red "tokenstranice: sat: N stranica, mišljenja M, trošak $x ..."
    python3 run_tokenstranice.py sat --bez-ai # samo brojke (bez poziva OpenAI-ja)
    python3 run_tokenstranice.py status       # zadnji red i današnji trošak

Niski prioritet (nice 10), bez teške brave: čita samo naše baze (read-only), piše tokenstranice.db; mrežu koristi samo
za mišljenja (OpenAI, vlastiti strop TOKENSTRANICE_AI_USD_DAY, zadano 0,30 $/dan). Nije posao za mikrokapove, pa radi i
dok je uključen fokus_midcap (ops/fokus.py: nije u OFF).
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("sat", "status"))
    ap.add_argument("--bez-ai", action="store_true")
    a = ap.parse_args(argv)
    try:
        os.nice(10)
    except (OSError, AttributeError):
        pass
    try:
        from ops import sentry
        sentry.init("tokenstranice")
    except Exception:  # noqa: BLE001
        pass
    from tokenstranice import misljenje, osvjezi, store
    if a.cmd == "status":
        con = store.ro()
        if con is None:
            print(osvjezi.PREFIX + "još nema baze (prvi prolaz nakon deploya)")
            return 0
        try:
            last = store.kv_get(con, "last") or {}
            print(last.get("line") or osvjezi.PREFIX + "još nema prolaza")
            print(osvjezi.PREFIX + f"danas ${store.spent(con, store.day_start(time.time())):.3f} od "
                                   f"${misljenje.DAY_USD:.2f}")
        finally:
            con.close()
        return 0
    try:
        osvjezi.run(log=lambda s: print(s, flush=True), ai=not a.bez_ai)
    except Exception as e:  # noqa: BLE001 - one line, never a traceback with paths in the shared log
        print(osvjezi.PREFIX + f"prolaz nije uspio: {type(e).__name__}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
