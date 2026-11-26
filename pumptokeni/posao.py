"""python3 -m pumptokeni.posao tick   (start.sh, svake minute)

Jedan prolaz: razriješi nepotvrđena lansiranja, pošalji najviše JEDAN token iz reda (stropovi, razmak, kill switch u
launch.tick), osvježi nadzornu ploču (najviše jednom u PUMP_TOKENI_OSVJEZI_MIN, zadano 10 min: jedan batch zahtjev
DexScreeneru za snimke i dospjele točke ishoda, saldo trezora naknade kroz RPC), jednom dnevno red „pump tokeni: ...”.
Bez baze (pokus nikad otvoren) odmah izlazi: nema mreže, nema retka.

26.11. (vlasnik): suha proba rasporeda (provjera.run, samo simulateTransaction i Pinata autentifikacija, nikad
sendTransaction ni učitavanje) jednom nakon pokretanja procesa (start.sh petlja; identitet: roditeljski proces i
njegovo vrijeme pokretanja) i zatim najviše jednom u DRY_EVERY_S dok postoji zakazan a nelansiran nacrt. Kupci u prvih
10 min (outcomes.measure_buyers) jednom po tokenu, 11+ min nakon lansiranja, kroz isti RPC, uz tvrdi strop poziva.
"""
import os
import sys
import time

from pumptokeni import launch, outcomes, provjera, store

DRY_EVERY_S = 1800


def proc_id():
    """Identitet dugog procesa koji svake minute zove tick (petlja u start.sh): roditelj + vrijeme pokretanja."""
    pp = os.getppid()
    try:
        with open(f"/proc/{pp}/stat", encoding="ascii") as f:
            start = f.read().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        start = "?"
    return f"{pp}:{start}"


def dry_run_due(con, now, proc):
    """True kad treba suha proba: postoji zakazan a nelansiran nacrt i (novi proces ili prošlo DRY_EVERY_S)."""
    if not provjera.scheduled_ids(con, now):
        return False
    st = store.get(con, "suha_proba") or {}
    o = store.get(con, store.NALOG_2611) or {}
    every = 600 if (o and not o.get("gotovo") and now < int(o.get("do") or 0)) else DRY_EVERY_S   # nalog čeka zeleno
    return st.get("proc") != proc or now - (st.get("ts") or 0) >= every


def dry_run(con, now, proc, log=print, **kw):
    """Suha proba cijelog rasporeda. Samo simulacija: provjera.run nikad ne zove sendTransaction ni Pinata upload."""
    store.put(con, "suha_proba", {"ts": now, "proc": proc})
    return provjera.run(con, provjera.scheduled_ids(con, now), now=now, log=log, **kw)



def owner_order(con, now, log=print):
    """Vlasnikov nalog iz chata 26.11. ("pilot je već odobren i ne želim ga 100 puta odobravati, smatraj da je odobren"):
    njegovo odobrenje od 13:31 palo je na staru verziju bez rasporeda. JEDNOM, samo za večerašnji raspored sjemenskih
    nacrta i samo do store.NALOG_2611_DO: kad je suha proba cijelog rasporeda zelena, raspored se odobrava istim putem
    kao njegov dodir (launch.approve_pilot: svi čuvari, termini, kupnje, rezerva). Bez zelene provjere se ne odobrava
    ništa. Tekst ili None."""
    o = store.get(con, store.NALOG_2611)
    if o is None and not store.get(con, "nalog_2611_upisan") and now < store.NALOG_2611_DO:
        # 26.11. 14:40 CET: nacrti su iz starog reda vraćeni već u 13:38 (prije jednokratnog ispravka), pa nalog nije bio
        # upisan; vlasnikov nalog iz chata vrijedi svejedno. Upisuje se jednom.
        o = {"ts": now, "do": store.NALOG_2611_DO, "gotovo": False}
        store.put(con, store.NALOG_2611, o)
        store.put(con, "nalog_2611_upisan", now)
    if not o or o.get("gotovo") or now >= int(o.get("do") or 0):
        return None
    seme = {r[3] for r in store.SEED}
    ids = [i for i in provjera.scheduled_ids(con, now) if (store.draft(con, i) or {}).get("simbol") in seme]
    pf = store.get(con, "provjera") or {}
    if not ids or not pf.get("zeleno") or set(ids) - set(pf.get("ids") or []) or now - (pf.get("ts") or 0) > 1500:
        return None
    from trade import settings
    try:
        n, notes = launch.approve_pilot(con, ids, settings.owner(), True, now=now)
    except ValueError as e:
        log(f"pump tokeni: nalog vlasnika 26.11. nije izvršen ({str(e)[:160]})")
        return None
    store.put(con, store.NALOG_2611, {**o, "gotovo": True, "izvrseno_ts": now, "n": n})
    txt = (f"pump tokeni: raspored odobren po nalogu vlasnika iz chata 26.11. ({n} nacrta)"
           + (": " + "; ".join(notes) if notes else ""))
    log(txt)
    return txt


def tick(now=None, log=print, path=None, proc=None, dry_kw=None):
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
            proc = proc or proc_id()
            if dry_run_due(con, now, proc):
                dry_run(con, now, proc, log=log, **(dry_kw or {}))
        except Exception as e:  # noqa: BLE001
            log(f"pump tokeni provjera: suha proba nije uspjela ({type(e).__name__}: {str(e)[:120]})")
        try:
            owner_order(con, now, log=log)
        except Exception as e:  # noqa: BLE001
            log(f"pump tokeni: nalog vlasnika 26.11. nije obrađen ({type(e).__name__}: {str(e)[:120]})")
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
        try:
            outcomes.measure_buyers(con, now, log=log)
        except Exception as e:  # noqa: BLE001
            log(f"pump tokeni: kupci u prvih 10 min nisu izmjereni ({type(e).__name__})")
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
