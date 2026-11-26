"""python3 -m pumptokeni.posao tick   (start.sh, svake minute)

Jedan prolaz: razriješi nepotvrđena lansiranja, pošalji najviše JEDAN token iz reda (stropovi, razmak, kill switch u
launch.tick), osvježi nadzornu ploču (najviše jednom u PUMP_TOKENI_OSVJEZI_MIN, zadano 10 min: jedan batch zahtjev
DexScreeneru za snimke i dospjele točke ishoda, saldo trezora naknade kroz RPC), jednom dnevno red „pump tokeni: ...”.
Bez baze (pokus nikad otvoren) odmah izlazi: nema mreže, nema retka.
"""
import os
import sys
import time

from pumptokeni import launch, outcomes, store



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
        if now - (store.get(con, "snimak_ts") or 0) >= outcomes.refresh_every_s() and outcomes.launched(con):
            store.put(con, "snimak_ts", now)
            try:
                outcomes.refresh(con, now, log=log)
            except Exception as e:  # noqa: BLE001
                log(f"pump tokeni: ploča nije osvježena ({type(e).__name__})")
            outcomes.read_vaults(con, now, log=log)
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
