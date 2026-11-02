"""Svježa provjera tokena koje alat preporučuje (Nicholas 2.11.: "za mali dio tokena koji alat odluči preporučiti
podaci moraju biti svježi", "je li token u padu uz šansu oporavka ili je trenutno pumpa", "rug check ... to je jako
bitno").

    state.py   stanje tržišta iz DexScreener promjena cijene: pumpa / pad uz oporavak / pada / stabilno + savjet
    safety.py  obavezan rug check: RugCheck izvještaj + Jupiter test prodaje (honeypot) + pun rug filter (Helius)
    store.py   topcheck.db (jedan pisac: run_top.py)
"""
