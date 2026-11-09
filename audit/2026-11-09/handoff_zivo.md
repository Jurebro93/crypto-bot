# Handoff – grupa "zivo" (audit 9.11.2026)

Napravljeno u mojim datotekama (kontekst): ui/autopilot.py (minutna provjera primarni rang KOL-ova, fitilj samo fallback s
oznakom mjera='fitilj'; kol_stats gornja granica 24 h+svijeća; wallet_stats: prodaja bez SOL-a = zatvoreno ali roi None,
udio neprodanih kažnjava score i >50 % ispada; proven_wallets() iz wallets/dokazani.latest kao prvi izvor walleta za
auto-izbor; auto-follow KOL/ekipa dobiva exit tpsl s tp_default i copy.DEFAULT_SL, wallet ostaje mirror), ui/zivo.py
(LIVE_TTL 2 s, osvježavanje u daemon niti "zivo-live", rows() nikad ne radi HTTP u niti pozivatelja, rows(sync=True) za
Pregled; izvor 'prijedlog' preko ui.pravitrade.latest_picks; alat preskače rank=None; expectation vagana po n, fallback
s prefiksom "stara mjera"), ui/prijedlog.py (live_market → client.tokens_live; chances() samo kind='call' AND bad IS NULL;
zivo retci razina='uživo' + prijedlog_log kind='zivo'; badge "svježina"/"uživo (Autopilot)"; group_pick n ≥ together.MIN_N
+ minutna provjera ekipe kad postoji; svježina iz r['signal_ts'] ako ga red ima), ui/prijedlog_log.py (sentence 'uživo'),
ui/paper.py (live_pairs → client.tokens_live, fallback na 2-arg stand-in client.tokens iz testova). Testovi:
tests/test_audit_20261109_zivo_offline.py (17). Puni suite: 968 OK.

## ui/pravitrade.py (grupa pravitrade)
- _kol_section (:440-463): red sad nosi `r["s"]["mjera"]` ('minutna' | 'fitilj') i `r["s"]["minute"]` (n, hit10, hit15, sl,
  med_t10). Za 'minutna' prikazati `{minute['hit10']:.0%} +10 % prije stopa · {minute['n']} poziva` umjesto `s["hit"]`/`s["n"]`
  (koji su stara mjera i mogu biti 0), a legenda "Pogodak = +50 % u 24 h" vrijedi samo za retke 'fitilj' (P12/P15/P16).
- latest_picks (:616) `order` dict: dodati "uživo": 3 (ili ga preskočiti) – Pregled od sada upisuje zivo retke s
  razina='uživo', kind='zivo'; ui/zivo._sources uzima samo razina=='visoka' pa nema petlje (P50/P51).
- token_popup (:952): naslov "Očekivanje +15 %" → "Očekivanje" – fallback tekst sad počinje s "stara mjera: … +30 % u 24 h" (P85).
- _wallet_section (:518-523) tekst "nijedan wallet … nema barem 3 prodana tokena u plusu" je kriv: chain_trades prodaje
  nemaju SOL iznos, pa je povrat po prozoru 'nepoznato' (wallet_stats roi=None). Napisati "iznos prodaja se ne zapisuje,
  povrat po prozoru nepoznat; auto-izbor uzima 'dokazane dvaput'" (P14). _dokazani_items (:466): prikazati r["bags"]/
  r["bag_share"] ("· N bagova") – isto traži handoff_izvori P55.
- callers_inner/_live_cached (:774 `ttl=1`): fragment /pravi-trade/zovu i dalje radi DexScreener HTTP (i _Throttle sleep) u
  niti zahtjeva svake sekunde; ui/zivo.rows više ne. Prijedlog: ttl ≥ 2 i isti uzorak kao zivo (_ensure_bg daemon nit koja
  puni _CALLERS_CACHE, handler samo čita), ili gather_callers pozivati iz zivo niti (P33, pogon handoff).
- LIVE_IDEAS_S = 1 može ostati: ideas_inner → zivo.rows(now) sad vraća keš bez HTTP-a; podaci su stari ≤ ~2×LIVE_TTL
  (zivo.LIVE_TTL 2 s). Red nosi r["checked"] (vrijeme podatka) – po želji ispisati "prije N s" umjesto "⟳ 1 s".
- tests/test_pravitrade_offline.py: test_wallet_window_stats i AutoPick prolaze bez promjene (roi 0.75 ostaje jer prodaje u
  fixtureu imaju sol). Novi ključevi u wallet_stats: priced, open, open_share; roi može biti None.

## league/copy.py (grupa novac)
- market() (:330) `client.tokens("solana", …)` → `client.tokens_live(...)` (P2/P26, handoff_izvori); ui/paper.market i
  ui/prijedlog.live_market su prebačeni. Pozor: testovi koji patchaju `client.tokens` 2-arg lambdom (test_quickbuy,
  test_audit_novac) – tokens_live zove tokens(ttl=…) pa stand-in puca; u ui/paper.live_pairs to rješava fallback na
  TypeError; isto treba ovdje ili patchati `client.tokens_live` u testovima.
- run_once (:499-): vrata po pozivatelju iz minutne provjere SAMO za auto-followe (settings auto_follows): kad
  minute.handle_stats(…, min_n=5) za handle ima hit10 < 0.4 ili sl > 0.4 → why = "minutna provjera: +10 % prije stopa samo
  X %" (keš 60 s). Ručne followe ne dirati (P12, verifikator). Nisam mijenjao jer copy.py nije moj.

## kol/chainwatch.py (grupa izvori)
- parse (:232) upisuje sell sa sol=None; bez SOL-a primljenog pri prodaji (nativeTransfers toUserAccount == w) ROI po
  prozoru u ui/autopilot.wallet_stats ostaje 'nepoznato' i lista "po 7/14/30 d" prazna (P14). Kad se doda, wallet_recs
  radi bez daljnjih promjena.

## ui/overview.py (grupa stranice)
- _token_rows: dodati `"signal_ts": s["last"]["ts"] if s else 0` (vrijeme zadnjeg stvarnog signala, bez rug checked_at i cand
  first_ts). ui/prijedlog.token_picks_ex već čita r.get("signal_ts") i pada na last_seen dok ga nema (P79).

## tests/test_ekipa_follow_offline.py:112 (grupa pravitrade) – P66
- Asertacija `_runup(m, 1800) == 0.80` zaključava h1 za slučaj koji run_once nikad ne doseže (max_delay_min=10). Verifikator:
  ne uvoditi linearno skaliranje; dodati run_once slučaj s m5 ≠ h1 i age 5–10 min. Tekst bilješke je grupa novac već
  promijenila. Nisam dirao (datoteka nije moja).

## DNEVNIK.md
- :23 "DexScreener batch keš 1 s" → "živi keš 3 s (DEX_LIVE_TTL), zivo lista 2 s u pozadinskoj niti, skeneri 60 s".

## Dopuna nakon pregleda (9.11., zivo – reviewer suggestions)
- ui/pravitrade.py `latest_picks` (order dict ~ "visoka":0,"srednja":1,"niska":2): dodati `"uživo": 0` – zivo redci iz prijedlog_log (kind='zivo', razina='uživo') sada padaju na order 3 iza 'niska'. ui/zivo filtrira na 'visoka' pa trenutno ne smeta, ali ako se latest_picks ponovno koristi na stranici, redoslijed je kriv. (P50/P51)
- ui/pravitrade.py `ideas_inner`: prvi poziv `zivo.rows(now)` bez keša vraća [] dok daemon 'zivo-live' ne napuni (~1 DexScreener zahtjev, ≤2 s); fragment tada kešira prazan HTML LIVE_IDEAS_S. Predlažem: kad `zivo.rows()` vrati [] a `zivo._ROWS` još nije popunjen (ts == 0), prikazati 'učitavam…' umjesto praznog i ne keširati. (P33)
- kol/chainwatch.py `parse`: bez SOL-a primljenog pri prodaji (nativeTransfers toUserAccount == w) autopilot.wallet_recs je u produkciji trajno prazan (roi None → preskok, nikad 'prolazi'); proven_wallets (dokazani.latest) pokriva auto-izbor, ali P14 ostaje otvoren dok se SOL s prodaje ne upiše.
