# Handoff iz grupe 'pogon' (9.11., audit) – datoteke izvan mog vlasništva

## P33 (varijanta iz zadatka: mrežni poziv u 1-sekundnom fragmentu) – ui/pravitrade.py, ui/zivo.py
- ui/pravitrade.py:588 `LIVE_IDEAS_S = 1` i ui/zivo.py:20 `LIVE_TTL = 1`: fragment `/pravi-trade/ideje` (run_ui.py poziva
  `pravitrade.ideas_fragment` u niti zahtjeva, svake sekunde dok je stranica otvorena) na promašaj 1-s cachea zove
  `ui/zivo.rows()` -> `ui/prijedlog.live_market()` (prijedlog.py:88-96) -> `dexscreener.client.tokens(..., fast=True)`:
  mrežni poziv u handler-niti, a `dexscreener/client._Throttle.wait` (client.py:26-29) u istoj niti radi `time.sleep`.
- Što: (a) TTL živih podataka 2–5 s umjesto 1 s (DexScreener limit 300/min po IP-u dijele svi procesi, pravilo vlasnika 9.11.);
  (b) osvježavanje u pozadinskoj niti (daemon thread u ui/zivo ili ui/pravitrade koji svakih N s puni `_ROWS`/`_IDEAS_CACHE`),
  a `ideas_fragment` samo čita cache i nikad ne blokira (ni sleep ni HTTP) u niti zahtjeva.
- Zašto: nalaz P33 (zadatak grupe pogon); u run_ui.py nema što sigurno popraviti bez mijenjanja potpisa funkcija u ui/pravitrade.py,
  pa run_ui.py ostaje nepromijenjen za tu stavku. Ne dira trade/ ni novac.

## P63 (nije nužno po verifikatoru, ali ostaje otvoreno) – run_kol.py
- run_kol.py:295 `heavy.run(args, timeout=max(600, a.every * 60 * 3))`: wait=None (čeka neograničeno) i timeout do 3600 s uz
  --every 20, pa KOL krug može držati bravu do 60 min. Prijedlog: `wait=` eksplicitno (npr. 20 min) uz preskok kruga kad je
  brava zauzeta, ili kraći timeout; samo ako KOL grupa to želi. Market/usage su od sada 'light' (run_sched.py), pa makro gate i
  potrošnja više ne čekaju na tu bravu.

## P33 (review pogon, 9.11.) – ui/pagecache.py:104-115 `_build` ponovno sprema staru kopiju
- Kad run_ui._last_copy vrati zadnji snapshot kao 200, `_build` ga re-gzipa i zove `_save_snap` -> mtime datoteke
  `UI_SNAP_DIR/pregled.html.gz` se resetira, pa `SNAP_MAX_S` (24 h, _load_snap:95) više ne istječe dok dijete pada:
  ista stara kopija može se služiti neograničeno (u stranici je vidljivo njeno vrijeme, ali granica 24 h je zaobiđena).
- Što: u `_build` ne zvati `_save_snap` kad su bajtovi jednaki postojećem snapshotu (ili kad builder označi "replay",
  npr. code 200 + raw identičan `_load_snap(key)[3]` dekompresiranom); ili `_last_copy` vraćati kroz poseban kod.
- Zašto: run_ui.py ne može spriječiti spremanje (pagecache nije u vlasništvu grupe pogon); utjecaj nizak, nije blokirajuće.

## P9 (review pogon, 9.11.) – ops/dbs.slim_signals puni prolaz svaki sat (vlasništvo pogon, ali izvan opsega nalaza)
- hourly() sada radi slim_signals (prolaz po cijeloj hype_signals) svakih 60 min pod teškom bravom, prvi put 10 min
  nakon starta; uz 20+ deployeva dnevno to je puni prolaz po 1,4 GB tablici ~svakih 20 min, za to vrijeme gradnja
  stranica (wait=60) dobiva staru kopiju/503. Prijedlog: vodeni žig (zadnji obrađeni rowid / ts u kv tablici) pa
  satni prolaz obrađuje samo nove retke; sljedeća runda.
