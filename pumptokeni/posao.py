"""python3 -m pumptokeni.posao tick   (start.sh, svake minute)

Jedan prolaz: razriješi nepotvrđena lansiranja, pošalji najviše JEDAN token iz reda (stropovi, razmak, kill switch u
launch.tick), zapiši dospjele točke ishoda (najviše jednom u 10 min), jednom dnevno red „pump tokeni: ...”.
Bez baze (pokus nikad otvoren) odmah izlazi: nema mreže, nema retka.
"""
import os
import sys
import time

from pumptokeni import launch, outcomes, store

OUTCOME_EVERY_S = 600


def tick(now=None, log=print, path=None):
    p = path or store.db_path()
    if not os.path.exists(p):
        return None
    now = int(now or time.time())
    con = store.connect(p)
    try:
        try:
            launch.reconcile(con, now, log=log)
        except Exception as e:  # noqa: BLE001
            log(f"pump tokeni: provjera poslanih nije uspjela ({type(e).__name__})")
        res = None
        try:
            res = launch.tick(con, now, log=log)
        except Exception as e:  # noqa: BLE001 - one bad pass never stops the next
            log(f"pump tokeni: red nije obrađen ({type(e).__name__}: {str(e)[:120]})")
        if now - (store.get(con, "ishodi_ts") or 0) >= OUTCOME_EVERY_S:
            store.put(con, "ishodi_ts", now)
            outcomes.check_pass(con, now, log=log)
        outcomes.daily_line(con, now, log=log)
        return res
    finally:
        con.close()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["tick"]:
        tick()
        return 0
    if argv[:1] == ["red"]:
        p = store.db_path()
        if os.path.exists(p):
            con = store.connect(p)
            try:
                print(outcomes.line(con))
            finally:
                con.close()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
