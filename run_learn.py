#!/usr/bin/env python3
"""Learning loop: re-fit the hype weights per token class from outcomes, automatically and with guardrails.

    python3 run_learn.py fit              # one run over all classes, applies what passes the guardrails
    python3 run_learn.py fit --dry        # same, but only reports
    python3 run_learn.py status           # current per-class weights, pump thresholds, last runs
    python3 run_learn.py missed           # tokens that never got a paid check and still pumped
    python3 run_learn.py fit --samo-tezine # only the hype weights (every learn/config.json every_h hours, run_sched)
    python3 run_learn.py model            # decision model: trial, promotion, rollback (also part of the daily fit)
    python3 run_learn.py postai           # AI labels KOL/TG posts in batches (every 30 min, run_sched)
    python3 run_learn.py ideja "tekst"    # an idea for the detective: it becomes a hypothesis that tests itself
    python3 run_learn.py shadow           # shadow book: collect decision points, label the due ones (hourly, run_sched)
    python3 run_learn.py loop             # on the server: one run a day at learn/config.json run_at_utc

Learned weights go to LEARNED_DIR (default $DATA_DIR/learned); runs are logged to learn_runs in hype.db.
"""
import argparse
import datetime as dt
import os
import sys
import time

from learn import fit, outcomes, store, weights

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "hype.db")


def cmd_fit(a):
    con = store.connect(DB)
    rep = fit.run(con, now=time.time(), apply=not a.dry)
    for r in rep:
        flag = "PRIMIJENJENO" if r["applied"] else ("ROLLBACK" if r.get("rollback") else "bez promjene")
        print(f"{r['klasa']:<9} n={r['n']:<5} cilj {r.get('cilj', 'vrh')} ≥ {r['skok'] or 0:+.0%}  {flag}: {r['note']}")
    if getattr(a, "samo_tezine", False):  # the 6-hourly refit: weights only, the rest stays daily
        con.close()
        return rep
    if not a.dry:
        try:  # AI detective: judge open hypotheses, propose new ones (learn/detektiv.py); before the model, which uses them
            from learn import detektiv
            print(f"detektiv: {detektiv.propose()}")
        except Exception as e:
            print(f"detektiv: {type(e).__name__}: {e}", file=sys.stderr)
    try:  # decision model: champion / challenger on the shadow book (learn/champion.py)
        cmd_model(a, con)
    except Exception as e:
        print(f"model: {type(e).__name__}: {e}", file=sys.stderr)
    try:  # confidence: the same facts the pop-up lists, re-weighed from outcomes (learn/confmodel.py)
        from learn import confmodel
        c = confmodel.run(con, now=time.time(), apply_model=not a.dry)
        print(f"confidence n={c['n']:<5} {'PRIMIJENJENO' if c['applied'] else 'bez promjene'}: {c['note']}")
        store.prune_empty(con)
        con.commit()
    except Exception as e:
        print(f"confidence fit: {type(e).__name__}: {e}", file=sys.stderr)
    try:  # rug profile: entry profiles that ended as rugs (learn/rugprofile.py, labels from rugfilter/archive.py)
        from learn import rugprofile
        r = rugprofile.run(con, now=time.time(), apply_model=not a.dry)
        print(f"profil ruga n={r['n']:<5} rugova {r['rugs']}: {r['note']}")
    except Exception as e:
        print(f"profil ruga: {type(e).__name__}: {e}", file=sys.stderr)
    return rep


def cmd_status(a):
    con = store.connect(DB)
    rows, thr = outcomes.rows(con)
    for k in sorted(thr):
        n = sum(1 for r in rows if r["klasa"] == k)
        print(f"{k:<9} ishoda {n:<5} skok ≥ {thr[k]:+.0%}  težine: {'naučene' if os.path.exists(weights.path(k)) else 'osnovne'}")
    for r in store.runs(con, limit=10):
        print(f"  {dt.datetime.fromtimestamp(r['ts']):%d.%m %H:%M} {r['klasa']:<9} n={r['n']:<4} "
              f"{'primijenjeno' if r['applied'] else 'ne'}  {r['note']}")


def cmd_missed(a):
    con = store.connect(DB)
    rows, thr = outcomes.rows(con)
    for m in outcomes.missed(con, thr, hours=a.hours)[:a.top]:
        print(f"{m['max_ret']:+6.0%}  {m['symbol'] or m['token'][:8]:<12} {m['klasa']:<9} T{m['razina']}  {m['reason']}")


def cmd_model(a, con=None):
    from learn import champion
    own = con is None
    con = con or store.connect(DB)
    t0 = time.time()
    rep = champion.run(now=t0, apply=not a.dry)
    note = "; ".join(rep["events"]) or "bez promjene"
    print(f"model: glavni = {rep['champion']}; {note} ({time.time() - t0:.0f} s)")
    store.log_run(con, t0, "model", 0, None, any("sad odlučuje model" in e for e in rep["events"]), None, None,
                  {}, {"champion": rep["champion"]}, note)
    con.commit()
    if own:
        con.close()


def cmd_postai(a):
    from learn import postai
    print(f"AI čitanje objava: {postai.step()}")


def cmd_ideja(a):
    from learn import detektiv
    detektiv.add_idea(" ".join(a.tekst), a.autor)
    print("ideja spremljena: detektiv je sutra pretvara u hipotezu koja se sama testira")


def cmd_shadow(a):
    from learn import shadow
    r = shadow.run()
    new = ", ".join(f"{shadow.POINTS.get(k, k)} {v}" for k, v in sorted(r["new"].items())) or "nema novih"
    print(f"sjenovita knjiga: novih točaka {new}; označeno {r['labeled']}; obrisano starih {r['pruned']}")


def cmd_masovno(a):
    """Mass shadow book (learn/masovno.py): today's points from the token filter, history at night, labels within
    the GeckoTerminal budget. run_sched every MASOVNO_EVERY_MIN minutes."""
    from learn import masovno
    r = masovno.run(budget=a.budget if getattr(a, "budget", None) else None)
    if not r.get("enabled", True):
        print("masovno: isključeno (learn/config.json masovno.enabled)")
        return
    new = ", ".join(f"{k} {v}" for k, v in sorted(r["new"].items())) or "nema novih"
    print(f"masovno: novih točaka {new}; povijest +{r['history']}; označeno {r['labeled']} ({r['calls']} poziva"
          f"{', noć' if r['night'] else ''})", flush=True)


def cmd_loop(a):
    cfg = outcomes.config()
    hh, mm = map(int, cfg["run_at_utc"].split(":"))
    last_day = None
    while True:
        now = dt.datetime.now(dt.timezone.utc)
        if (now.hour, now.minute) >= (hh, mm) and last_day != now.date():
            try:
                cmd_fit(argparse.Namespace(dry=False))
            except Exception as e:
                print(f"learn fit: {type(e).__name__}: {e}", file=sys.stderr)
            last_day = now.date()
        time.sleep(300)


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fit")
    f.add_argument("--dry", action="store_true")
    f.add_argument("--samo-tezine", dest="samo_tezine", action="store_true")
    mo = sub.add_parser("model")
    mo.add_argument("--dry", action="store_true")
    sub.add_parser("status")
    m = sub.add_parser("missed")
    m.add_argument("--hours", type=float, default=168)
    m.add_argument("--top", type=int, default=30)
    sub.add_parser("shadow")
    mp = sub.add_parser("masovno")
    mp.add_argument("--budget", type=int, help="GeckoTerminal poziva za ovaj prolaz (zadano: dan/noć iz configa)")
    sub.add_parser("postai")
    i = sub.add_parser("ideja")
    i.add_argument("tekst", nargs="+")
    i.add_argument("--autor", default="Nicholas")
    sub.add_parser("loop")
    a = p.parse_args(argv)
    {"fit": cmd_fit, "status": cmd_status, "missed": cmd_missed, "shadow": cmd_shadow, "model": cmd_model, "postai": cmd_postai, "ideja": cmd_ideja, "loop": cmd_loop, "masovno": cmd_masovno}[a.cmd](a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
