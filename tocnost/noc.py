"""The night batch: snapshot the scores that keep no history (influencer verdict, copy rank), then count every score's
accuracy over the last 30 days into tocnost.db. Read-only on every source database; writes only tocnost.db.
"""
import time

from tocnost import izvori, stat, store

DAYS = 30


def measure(key, P, now, days=DAYS, min_n=stat.MIN_N):
    """(aggs, note) of one score at `now`."""
    spec = izvori.SPECS[key]
    lo, _ = stat.window(now, days, spec.get("since"))
    rows = izvori.LOADERS[key](P, lo, now)
    aggs = stat.aggregate(rows, spec, now, days, min_n)
    unknown = sum(1 for r in rows if r.get("outcome") not in (0, 1))
    return aggs, f"redaka {len(rows)}, bez ishoda {unknown}"


def run(now=None, paths=None, log=print, snapshot=True):
    now = int(now or time.time())
    P = izvori.paths(paths)
    if snapshot:
        for name, fn in (("kol", lambda: izvori.snapshot_kol(now, P["tocnost"])),
                         ("rang", lambda: izvori.snapshot_rang(now, P, P["tocnost"]))):
            try:
                log(f"točnost: snimka {name}: {fn()} redaka")
            except Exception as e:  # noqa: BLE001 - one source down never stops the others
                log(f"točnost: snimka {name} nije uspjela: {type(e).__name__}: {str(e)[:160]}")
    res = {}
    for key in izvori.ORDER:
        try:
            res[key] = measure(key, P, now)
        except Exception as e:  # noqa: BLE001
            log(f"točnost: {key} nije izmjeren: {type(e).__name__}: {str(e)[:160]}")
    con = store.connect(P["tocnost"])
    try:
        for key, (aggs, note) in res.items():
            store.save(con, now, key, aggs, note)
        store.prune(con, now)
        con.commit()
    finally:
        con.close()
    store.clear_cache()
    for key, (aggs, note) in res.items():
        parts = [f"{a['bucket']} {a['k']}/{a['n']}" for a in aggs if a["n"]]
        log(f"točnost {key}: " + ("; ".join(parts) if parts else "još nema provjerenih") + f" ({note})")
    return res
