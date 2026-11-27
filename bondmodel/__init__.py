"""Model vjerojatnosti bondanja pump.fun lansiranja (27.11., vlasnik: „iz baze pump.fun lansiranja napravi model koji
rano procjenjuje vjerojatnost bondanja i provjeri ga na kasnijim danima”).

SAMO ISTRAŽIVANJE. Nijedan posao koji kupuje, prodaje ili bira tokene ovo ne čita (tests/test_bondmodel_offline.py
to provjerava): novi pump.fun tokeni se ne kupuju dok su na krivulji (CLAUDE.md).

  model.py   učitavanje (baza mjerenja i/ili njezine gzip arhive), značajke iz trenutka lansiranja (bez gledanja
             unaprijed), logistička regresija (Newton, L2, samo stdlib), walk-forward provjera po vremenu, mjere
             (AUC, kalibracija po decilima, preciznost u gornjih 1 % / 5 %, osnovna stopa), spremanje u bond_model.db
  posao.py   python3 -m bondmodel.posao run   (start.sh, jednom dnevno; bez podataka odmah izlazi)
Prikaz: odjeljak „Procjena bondanja” na vlasnikovoj stranici /pump-tokeni (ui/bondmodel.py).
"""
