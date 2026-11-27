"""python3 -m bondmodel.posao run   (start.sh, jednom dnevno): model bondanja na svim dostupnim podacima mjerenja.
Bez podataka odmah izlazi. Samo čita podatke mjerenja i piše bond_model.db; ništa ne kupuje i ništa ne dohvaća s mreže."""
import sys

from bondmodel import model


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    cmd = a[0] if a else "run"
    if cmd == "run":
        model.run(log=lambda s: print(s, flush=True))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
