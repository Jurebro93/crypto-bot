"""Pump Fun tokeni (25.11., vlasnik): kontrolirani pokus lansiranja vlastitih tokena na pump.fun, token se ostavlja.
26.11. večer: vlastita kupnja po nacrtu (0–0,1 SOL, samo u transakciji lansiranja, nikad prodaja), poveznice u
metapodacima, zakazana lansiranja (raspored koji odobrava vlasnik), suha proba rasporeda iz posla, kupci u prvih 10 min.
Vidi i radi samo vlasnik (/pump-tokeni, ui/pumptokeni.py).

  store.py     pump_tokeni.db: nacrti, pokušaji lansiranja, ishodi, postavke (kv)
  own.py       is_own(mint): naši mintovi; zabrana samotrgovanja na uskim grlima (executor, demo, sjena, kandidati)
  guards.py    čuvari imena (DexScreener ≥ 50k $ istog imena/simbola, zabranjene riječi, URL u opisu)
  image.py     generator slike (Pillow, 512×512 PNG, deterministički), normalizacija vlasnikove slike i slike sjemena
               iz pumptokeni/slike/<SIMBOL>.png
  launch.py    IPFS metapodaci, create zahtjev (PumpPortal trade-local), potpis, simulacija, slanje, red i stropovi
  outcomes.py  knjiga ishoda (+1 h, +12 h, +24 h, +7 d), snimci nadzorne ploče (svakih 10 min, jedan batch zahtjev),
               procjena naknade (0,30 % na krivulji, potvrđeno s lanca), trezor naknade, neto, CSV, dnevni red
  naknada.py   „Podigni naknadu”: collectCreatorFee kroz PumpPortal, samo vlasnikov potvrđeni dodir, simulacija
  posao.py     python3 -m pumptokeni.posao tick   (start.sh, svake minute: red, ploča, ishodi, red u logu)

Ništa ovdje ne prodaje nijedan token (ni naš) i ne kupuje izvan transakcije lansiranja (vlastita kupnja, „amount” u
create zahtjevu); ništa se ne objavljuje automatski (X, Buffer, Telegram).
"""
