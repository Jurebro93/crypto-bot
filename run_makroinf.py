#!/usr/bin/env python3
"""Makro influenceri (15.11., vlasnik: "Slažem se s prijedlogom koraka za plan makroinfluencera s dopunama
kritičara"; makroinf/): pilot 50 računa, mjerenje izjava o smjeru tržišta zaključanim pravilima, tri ocjene, indeks
konsenzusa najtočnijih kao DEMO ulaz u veliki/makro.

    python3 run_makroinf.py krug                 jedan ograničeni krug (start.sh svakih ~10 min, niski prioritet):
                                                 pilot dohvat / dnevni dohvat, klasifikacija, brisanja, ocjene, sat;
                                                 izlaz 3 = pilot u tijeku (start.sh se vraća za minutu)
    python3 run_makroinf.py noc                  puni izračun 01-06 Zagreb (ops.heavy --night), najviše jednom u 20 h
    python3 run_makroinf.py ocjene               samo ocjene i indeks iz onoga što je u bazi (bez mreže)
    python3 run_makroinf.py provjera             izvoz 300 uzoraka + kritičar na ~100 (strop 1 $)
    python3 run_makroinf.py prosiri [--vlasnik-forsira] [--cilj 300]
                                                 proširenje na 300 računa: odbija dok provjera nije prošla
    python3 run_makroinf.py kandidati            kandidati za račune bez poznatog handlea
    python3 run_makroinf.py izvjestaj            log linije i output/makroinf.md
    python3 run_makroinf.py procjena             procjena troška proširenja prije troška (bez mreže)
    python3 run_makroinf.py otkrivanje           stanje proširenja po nalogu vlasnika i trošak po fazi

Trošak: pilot twitterapi 5 $ i OpenAI 4 $ jednokratno; proširenje po nalogu vlasnika (15.11. navečer, 300-500 računa)
twitterapi 40 $ i OpenAI 15 $ jednokratno; zatim 1,50 $ / 0,50 $ dnevno (makroinf/store.py). Pravi novac: nikad
(zastavica makroinf_indeks je NEVER_LIVE). Radi i dok je fokus_midcap uključen (ops/fokus.EXCEPTIONS).
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    kind = a[0] if a and not a[0].startswith("-") else "krug"
    log = lambda m: print(m, flush=True)  # noqa: E731
    if kind not in ("krug", "noc", "ocjene", "provjera", "prosiri", "kandidati", "izvjestaj", "procjena", "otkrivanje"):
        print(__doc__)
        return 2
    try:
        os.nice(int(os.environ.get("MAKROINF_NICE", "10")))   # background work: low priority always
    except (OSError, ValueError):
        pass
    from makroinf import quality, racuni, report, run, store
    t = time.time()
    if kind == "krug":
        r = run.krug(log=log) or {}
        if r.get("pilot_u_tijeku"):   # start.sh: the next round in a minute while the pilot runs
            log(store.PREFIX + f"krug gotov za {time.time() - t:.0f} s (pilot u tijeku, sljedeći za minutu)")
            return 3
    elif kind == "noc":
        run.noc(log=log)
    else:
        con = store.connect()
        try:
            if kind == "ocjene":
                s = run.score_all(con, log=log)
                log(store.PREFIX + f"ocjene: {s['episodes']} epizoda, {s['enough']} računa s dovoljno dokaza")
            elif kind == "provjera":
                quality.run(con, store.config(), log=log)
            elif kind == "prosiri":
                cilj = None
                if "--cilj" in a:
                    try:
                        cilj = int(a[a.index("--cilj") + 1])
                    except (IndexError, ValueError):
                        log("--cilj treba broj")
                        return 2
                ok, txt = run.expand(con, force="--vlasnik-forsira" in a, who="vlasnik (CLI)", target=cilj, log=log)
                log(store.PREFIX + txt)
                return 0 if ok else 1
            elif kind == "kandidati":
                for x in racuni.candidates(con):
                    log(f"{x['for_name']}: @{x['handle']} ({x['followers'] or 0:,} pratitelja, {x['status']}) — "
                        f"{(x['bio'] or '')[:100]}")
            elif kind == "izvjestaj":
                for ln in report.lines(con):
                    log(ln)
                report.write(con)
            elif kind == "procjena":
                from makroinf import discover
                log(discover.estimate_line(discover.estimate(con)))
            elif kind == "otkrivanje":
                import json
                from makroinf import discover
                log(json.dumps(discover.summary(con), ensure_ascii=False, indent=1, default=str))
                log(discover.phase_line(con))
        finally:
            con.close()
    log(store.PREFIX + f"{kind} gotov za {time.time() - t:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
