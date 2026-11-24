# Handoff iz grupe "pravitrade" (9.11.2026, audit, val 2) – datoteke izvan mog vlasništva

Što sam napravio (kontekst): ui/pravitrade.py – zadani stop (copy.DEFAULT_SL) u /follow, /followall i tekstovima kartica
(P10/P17/P19); mirror za KOL → zadano (P74); poruka po min_callers i copyfollow prenosi strop/run-up/min_callers (P72);
"w:" novčanici nisu članovi ekipe (P73); pop-up: verdikt traži svjež razlog (P45), veto slabih pozivatelja iz minutne
provjere (P47, i u _post_buy), rug check "nije rađen" + "tko drži supply: nepoznato" (P49/P77/P36), rc_ts umjesto ts (P76),
likvidnost/MC ≥ 3 % (P41); _follows pokazuje dokaz u demu po run_trade.PROOF (P39); _dokazani_items "· N bagova" (P55);
1-s fragmenti /zovu, /ideje i pop-upovi čitaju keš koji puni daemon nit `autopilot-live` (ui/pravitrade._bg_loop),
DexScreener živi TTL LIVE_TTL_S = 3 s, brave oko keševa, "podaci od HH:MM:SS UTC" u fragmentu, JS označava
"nema svježih podataka" (P48/P75/P33). Testovi: tests/test_audit_20261109_pravitrade_offline.py (21 testova).

## run_ui.py (pogon) – NIJE nužno, opcionalno
- Nit kreće lijeno na prvi GET /pravi-trade/zovu ili /ideje (`pravitrade._bg_start()`); potpisi fragmenata su nepromijenjeni.
  Opcionalno: pri startu UI procesa pozvati `from ui import pravitrade; pravitrade._bg_start()` da i prvi gledatelj dobije
  pun keš (inače prvi fragment vraća prazno/stari HTML sa stranice dok nit ne napravi prvi prolaz, ≤1 s).
- Env `AP_BG_REFRESH=0` vraća stari sinkroni put (samo za dijagnostiku).

## ui/zivo.py (zivo) – P75 (dvostruki converge.events u sekundi), P48
- Moja nit svake sekunde zove `callers_inner(force=True)` (gather_callers → converge.events) i najviše svake LIVE_TTL_S (3 s)
  `ideas_inner(force=True)` → `zivo.rows(now)`. Ako zivo dobije vlastitu daemon nit, `rows()` iz moje niti smije biti samo
  čitanje keša (i jest, dok god `rows()` vraća `_ROWS` unutar vašeg TTL-a). Da se converge.events ne računa dvaput u
  sekundi: `zivo._recent_callers` može primiti već dohvaćene događaje (npr. novi parametar `events=`), a moja nit bi ih
  proslijedila – javite pa dodam poziv u `_bg_pass`.
- `zivo.LIVE_TTL = 1` → preporučam ≥ 2 s (DexScreener 300/min po IP-u dijele svi procesi); prijedlog.live_market već ide na
  `client.tokens_live` (3 s), pa je 1 s TTL u zivo bez učinka, ali zbunjuje.

## trade/executor.py (novac) – P75
- `executor.connect` radi `executescript(SCHEMA)` + PRAGMA table_info ×2 pri svakom otvaranju; 4 fragmenta × gledatelj ×
  sekunda. Prijedlog: migraciju izvesti jednom po procesu (module-level flag po putu baze), kasnije samo sqlite3.connect.
  Nije blokirajuće (milisekunde), ali je najčešći poziv u UI procesu.

## ui/topcheckui.py:79 (stranice) – P76
- "Provjereno {ago(top.ts)}" je vrijeme prolaza run_top (svakih 180 s), ne vrijeme RugCheck podatka. Koristiti
  `top.get("rc_ts") or top.get("ts")` za holder/rug red, kao sad u pop-upu Autopilota ("RugCheck podatak prije N min").

## topcheck/safety.py (izvori) – P76, opcionalno
- `judge` bi mogao primiti `rc_age_s` i dodati warn "holderi: podatak star N h" kad je rc stariji od 2 h (nakon odbijenih
  RugCheck upita stari rc ostaje neograničeno). Pop-up sad barem pokazuje starost podatka.

## tests/test_audit_20261109_stranice_offline.py (stranice) – napomena
- U jednom prolazu punog skupa (19:4x) padao je `MinuteStats.test_reads_minute_db_and_hot_list` (UNIQUE call_path.tweet_id,
  token); u završnom prolazu (1009 testova) je zelen – vjerojatno popravljeno paralelno. Nije vezano za moje promjene.

## .copy_wake
- tests/test_pravitrade_offline.py sad patcha `copy.WAKE` u temp dir (setUpModule), kao test_xhook_offline; više ne prlja
  repo. Preostali moduli koji ga pišu (nisu moji): tests/test_hype_sources_offline.py, tests/test_live_offline.py,
  tests/test_register_offline.py – isti obrazac (`mock.patch.object(copy, "WAKE", ...)` + setUpModule/tearDownModule).
- Napomena orkestratoru: vratio sam `.copy_wake` na HEAD stanje (`git checkout -- .copy_wake`) da provjerim da ga moj test
  više ne mijenja; to je jedina git naredba koju sam pokrenuo i ne dira kod. Ostali testovi ga u punom skupu i dalje mogu
  dirnuti – ne komitati `.copy_wake`.

## Odluka za Juru (nije kod)
- P47 veto u ručnoj kupnji: "Kupi odmah" se sad odbija kad SVI poznati pozivatelji tokena u zadnjem satu imaju hit15 < 30 %
  na 5+ izmjerenih poziva (poruka kaže postotak). Ako Jure želi da ručna kupnja ignorira statistiku pozivatelja (samo
  upozorenje u pop-upu), promjena je jedna linija u `_post_buy` (ukloniti `raise`) – ostavio sam konzervativno jer je
  Autopilot uključen.
