# Sekundni poslovi: što čitaju svaki otkucaj i što popraviti (audit 10.11.2026.)

Grana `ccr-232765a7-33e8r8`, kod samo čitan. Mjerenja su na sintetičkim kopijama baza u scratchpadu, sa shemama
iz koda i redovima veličine produkcije (kol.db 216 MB: 8.000 kols, 290.000 calls; tg.db 122 MB: 300.000 posts,
12.000 kanala; hype.db 915 MB: 900.000 chain_trades, 1,2 M live_trades, 30.000 token_tier; trade.db 5.000 pozicija,
8.000 naloga; league.db 3.000 tradeova, 25 praćenja). Brojke su ms CPU-a na ovom stroju: omjeri vrijede, apsolutne
vrijednosti na Renderu (1 CPU) nisu izmjerene.

## Izravan odgovor

- Lanac novca (run_trade, copy petlja) po otkucaju je jeftin (3,5 ms i ~10–25 ms), ali svaki put čita SVE: 5 punih
  prolaza tablica u run_trade svake sekunde, 120 min četiriju tablica (kol.db, hype.db, tg.db) u copy petlji. Raste s brojem redaka.
- Pravi potrošači su "svježina" stranice Autopilota, ne trgovanje: (1) `prijedlog.chances()` bez keša čita 14 dana
  poziva svake 2 s zauvijek i svake sekunde po otvorenom pop-upu (166 ms po čitanju); (2) pop-up tokena svake
  sekunde čita cijelu `token_tier` da uzme jedan redak (146 ms); (3) pozadinska nit Autopilota se nikad ne gasi
  i drži i zivo nit živom, pa sve to radi i kad nitko ne gleda.
- Tri popravka truda S (S1, S2, S3) skidaju procijenjenih ~10 % CPU-a stalno i ~30 % po otvorenom pop-upu
  (sintetika). Ništa od predloženog ne dira `trade/config.json` ("dry"), `run_trade.PROOF`, prag 30k $ ni pravilo
  "samo bondani".

## 1. Inventar: sve što se vrti na 60 s ili brže

| # | petlja (proces / nit) | kadenca | čita po otkucaju | piše | HTTP | cijela tablica? | trošak |
|---|---|---|---|---|---|---|---|
| P1 | `run_trade.py follow` (proces trade), run_trade.py:313-338 | 1 s (trade/config.json:10) | config.json (executor.py:44); trade.db nova veza + 3 DDL + 2 PRAGMA (executor.py:49-58); `settings` cijela + JSON (settings.py:52); `positions status='pending'` (executor.py:363); `orders⨝positions pending` (executor.py:390); `league_id IS NOT NULL` (run_trade.py:196); otvorene (run_trade.py:231); league.db nova veza: `trades user/status/opened_ts` (run_trade.py:138) | heartbeat svakih 60 s (run_trade.py:325) | nema u mirovanju | DA: SCAN positions ×3, SCAN orders, SCAN league trades (EXPLAIN) | 3,5 ms/otkucaj = 0,35 % CPU; raste s 'blocked' redovima |
| P2 | `league/auto.loop` (nit auto-sell u run_ui, run_ui.py:1214) | 20 s (auto.py:22) ili ≥1 s nakon wake (auto.py:314-322) | league.db + DDL (store.py:54-58); `copy.ensure` ×2 (copy.py:571, 200); sva aktivna praćenja; `events()`: 3–4 nove veze kol/hype/tg, 4 upita po vremenu za 120 min (copy.py:582, 299-323); `_logged` po događaju (copy.py:330); auto sell: `trades status='open' AND auto` (auto.py:218), hype.db token_tier IN, paper/config.json (auto.py:223); simianx → trade.db settings (simianx_feed.py:19); dca DDL + plans (dca.py:163-165); `MAX(ts)` equity | copy_log, trades, auto_state + commit (auto.py:258-259); DELETE copy_log (copy.py:617) | DexScreener live (TTL 3 s) za otvorene auto pozicije i nove kandidate | SCAN league trades (nema indeksa); prozor 120 min svaki put | events 9,4 ms (25 praćenja); cijeli prolaz ~15–25 ms (procjena) |
| P3 | `pravitrade._bg_loop` (nit autopilot-live u run_ui), pravitrade.py:1131-1135 | 1 s, bez gašenja | `converge.events(3600)`: `kols` cijela (converge.py:50), `kol_ids` cijela (:52), `sessions` (:57), `kols WHERE bot=1` (bots.py:145), calls/kol_mentions/posts/chain_trades po ts (:62-75; chain se odmah baci, pravitrade.py:989); `followed_wallets()` league.db + wallets.db (pravitrade.py:916-935); chain_trades za praćene (:996); kol.db tokens IN (:1010); league.db follows (:1155) | samo memorijski keš | DexScreener svake 3 s za do 16 tokena (:1017) | DA: kols 2× (8.000 redaka), kol_ids | 17,5 ms/prolaz ≈ 2 % CPU stalno |
| P4 | `zivo._bg_loop` (nit zivo-live u run_ui), zivo.py:228-236 | 2 s; gašenje nakon 30 s ne radi (S3) | svakih 60 s kandidati: top_check cijela (zivo.py:83), prijedlog_log, converge, opet gather_callers (:119); svaki prolaz: `converge.events(600)` (:132), `_smart_buys` (:149-160), `prijedlog.chances()` = 14 dana `calls` bez keša (prijedlog.py:41-42; zivo.py:260) | datoteka HTTP keša po odgovoru (http.py:307) | DexScreener do 30 tokena svake ~2 s (zivo.py:254) | chances: ~54.000 redaka po prolazu (sintetika) | 166 ms + 8,6 ms po prolazu ≈ 7–8 % CPU stalno |
| P5 | preglednik: 4 fragmenta po kartici (pravitrade.py:1717-1728) | 1 s po gledatelju | po zahtjevu `_tcon()` + can_view + `_cfg` (pravitrade.py:135, 126-132); log: zadnjih 15 naloga (:1673); pozicije: 60 pozicija (:1624) + SVI potpisi iz orders (:1629); zovu/ideje: samo keš | ništa | ništa | orders cijela za potpise | auth+cfg 0,29 ms; pozicije 1,6 ms |
| P6 | pop-up tokena / ekipe (pravitrade.py:274-287, 1326, 1471) | 1 s dok je otvoren, jedan zahtjev u letu | `_events_hour` (keš 3 s); `_smart_buys` (:1355); top_check cijela + 4× JSON po retku (:1359; topcheck/store.py:60-81); `token_tier` CIJELA (:1362; ui/data.py:310-313); `chances()` 14 dana (:1439); minute stats i supply (keš 60 s) | ništa | DexScreener kroz keš 3 s | DA: token_tier, top_check, calls 14 d | ~320 ms po osvježavanju ≈ 30 % CPU po otvorenom pop-upu |
| P7 | `run_live.py loop` (proces live), pumpportal.py:245-346 | flush ≤1/s, provjera dumpa 2 s, popisi 60 s, čišćenje 600 s | dump: live_alerts PK + live_trades (mint, ts) po otvorenom demo tokenu (pulse.py:17, 46, 64); 60 s `wanted()`: 5 veza, live_launches SCAN (:109), hype_signals po ts (:113) | live_trades, chain_trades (+ `CREATE TABLE IF NOT EXISTS` svaki flush, store.py:53), live_state, 2 commita/s; wake (store.py:59-61); 600 s `DELETE live_trades WHERE ts<?` | WebSocket PumpPortal | čišćenje: SCAN live_trades (194 MB) u pisaćoj transakciji | čišćenje 54 ms toplo (1,2 M redaka); u produkciji ključ bez SOL-a (audit 9.11., red 25) |
| P8 | `run_tg.py loop` (proces tg), run_tg.py:104-116 | 3 s; praćeni kanali 2 s (tg/config.json) | `due()`: svi kandidati + sort (poll.py:58-62), svi mrtvi (:60), minute.db hot lista + league.db 2× (:17-43), SVA imena kanala (:72), svi aktivni (:74); po kanalu t.me stranica + regex 20 objava | `UPDATE channels` + commit po čitanju (poll.py:115, 147) | t.me/s po praćenom kanalu svake 2 s | DA: channels 3× po otkucaju | due 7,2 ms (12.000 kanala); satni housekeeping zaustavi petlju (S9) |
| P9 | webhookovi u run_ui: /hook/chain, /hook/x, /hook/kol (run_ui.py:945-1004) | po događaju | ključ iz `.hook_key` (kol/store.py:290); kol.db `store.connect` = ~22 CREATE + 8 PRAGMA po X webhooku (kol/store.py:90-97) | chain_trades (+3 DDL, chainwatch.py:324-329), calls, kol_mentions, wake | ništa | ne | mali; već su događaji |
| P10 | `run_paper.py run` (proces paper): glavna 60 s, `_live_loop` 5 s, koltest 30 s, strat 60 s (run_paper.py:908, 1076, 1088, 1164) | 5–60 s | `candidates decision/first_ts` bez indeksa (:931), otvoreni tradeovi s JSON-om, kol.db calls po tokenu; live_alerts po ts (pulse.py:105); koltest → `converge.events` (koltest/run.py:55); intake → `converge.compute` (:337) | ticks, trades, koltest.db, strat.db | DexScreener 60-s keš | SCAN candidates svake minute | nije izmjereno (nije na putu Autopilota) |
| P11 | `python3 -m ops.health --quiet` (start.sh:56) | 60 s, svaki put novi proces | /proc svih procesa (health.py:15-36); svakih 10 min os.walk cijelog diska (:141) | log | ništa | ne | pokretanje Pythona ~0,1 s/min |
| P12 | `run_kol.py minute-loop` (proces minute), kol/minute.py:385-416 | prolazi ≥20 s dok ima zaostatka | kandidati 30 dana iz kol.db, `_done` cijela (minute.py:217-233); nakon SVAKOG prolaza hot lista (14 d) i TP/SL bazen (30 d) (:400-404) | minute.db | GeckoTerminal (dijeljeni limit) | bazen se računa i kad ništa nije izmjereno | nije izmjereno |
| P13 | druge stranice: /api/paper 15 s (ui/paper.py:14), /api/natjecanje 60 s (keš 20 s, ui/league.py:102), /api/prijedlog 60 s | po gledatelju | /api/paper: SVI paper tradeovi + JSON stanja (ui/data.py:473-478) | ništa | DexScreener | DA: paper trades | nije izmjereno |
| P14 | run_ui po zahtjevu | svaki zahtjev | HMAC kolačića (run_ui.py:134); za člana s pozivnicom league.db veza + DDL (league/members.py:91-102); ~20 regexa javnog rutera prije fragmenata (run_ui.py:522; ui/public.py:795); `_send`: prijevod fragmenta za EN (:734), gzip >1 KB (:745); puna stranica: `novo.notice_data` getmtime (novo.py:15-25), `_pages_json()` (ui/html.py:521, 666) | kolačići | ništa | ne | mikrosekunde do <1 ms |

## 2. Nalazi

| ID | gdje (file:line) | dokaz | prijedlog popravka | učinak | trud | rizik |
|---|---|---|---|---|---|---|
| S1 | ui/prijedlog.py:35-51; ui/zivo.py:260, 305-310; ui/pravitrade.py:1439 | `chances()` nema keš: svaki poziv otvara kol.db i vuče sve pozive 14 dana (`calls_ts` raspon). Zove se u svakom prolazu zivo niti (2 s) i u svakom osvježavanju pop-upa (1 s). Sintetika: 166 ms za 54.000 redaka (~3 ms na 1.000) | TTL keš 10 min u `prijedlog.chances` (rječnik po `days`); podatak se mijenja tek kad KOL krug izmjeri max24. Bolje: zbroj po razredu MC-a u SQL-u (COUNT + SUM uvjeta), bez prijenosa redaka | −7–8 % CPU stalno, −166 ms i ~17 % CPU po otvorenom pop-upu (sintetika; broj poziva u 14 d u produkciji nije provjeren) | S | nizak: šansa po razredu do 10 min stara |
| S2 | ui/pravitrade.py:1359, 1362; ui/zivo.py:34-39; ui/data.py:310-313; topcheck/store.py:60-81 | pop-up svake sekunde: `SELECT * FROM token_tier` (cijela tablica u rječnik) da uzme jedan mint, i `read_all` (cijela top_check + 4 JSON-a po retku). Sintetika: 146 ms za 30.000 redaka naspram 0,12 ms po ključu | `data.token_tier(mint)` s `WHERE token=?` (PRIMARY KEY) i čitanje top_check po ključu, ili keš po mintu 30 s kao `_SUPPLY_CACHE` | −146 ms po osvježavanju pop-upa (~15 % CPU po pop-upu; broj redaka token_tier u produkciji nije provjeren) | S | nizak |
| S3 | ui/pravitrade.py:1131-1135, 1088-1098, 1119-1122; ui/zivo.py:207, 228-236 | `_bg_loop` je `while True` bez uvjeta izlaza; pokrene je prvi zahtjev fragmenta. Svake 3 s zove `zivo.rows()`, što postavlja `_BG["asked"]`, pa se ni zivo (IDLE_STOP_S 30) nikad ne ugasi. Posljedica: P3 + P4 rade 24/7 i bez gledatelja, uz do ~45 DexScreener poziva/min (26 + 20, nije izmjereno) | u fragmentima i pop-upima bilježiti vrijeme zadnjeg zahtjeva; `_bg_loop` izlazi nakon 30 s bez zahtjeva (kao zivo); korak "ideje" samo ako je /ideje tražen u zadnjih 30 s | bez gledatelja 0 rada: sa S1 zajedno ~10 % CPU manje stalno (sintetika), DexScreener limit slobodan za copy petlju | S | nizak: prvi gledatelj vidi "učitavam…" 1–3 s (isto kao nakon deploya) |
| S4 | kol/converge.py:50-61, 75; kol/bots.py:145; ui/pravitrade.py:989 | svaki `events()` čita cijelu `kols` dvaput (ocjene i bot=1), cijelu `kol_ids`, `sessions`; sat `chain_trades` svih walleta se u `gather_callers` odmah baci. Sintetika: 17,5 ms po pozivu, od toga ~6,3 ms dimenzije; pozivi: 1/s (P3), 0,5/s (P4), koltest 30 s, paper 60 s | (a) keš 60 s za (ocjene, wallet→ime, faktore, botove) u converge; (b) parametar da pozivatelj preskoči chain dio; (c) kasnije: čitanje "od zadnjeg rowida" po tablici i držanje sata događaja u memoriji | 17,5 → ~3–5 ms (a+b), <1 ms (c) | S (a, b), M (c) | nizak: nova ocjena ili bot oznaka vidljiva do 60 s kasnije |
| S5 | run_trade.py:313-338, 196, 231-233; trade/executor.py:49-58, 363, 390; trade/settings.py:52-53; league/store.py:16-29 | svake sekunde nova veza, DDL, config.json i 5 punih prolaza: EXPLAIN daje `SCAN positions` ×3, `SCAN o` (orders), `SCAN trades` (league.db nema nijedan indeks). `have` skuplja SVE league_id ikad (i 'blocked'). Sintetika: 3,52 ms; s indeksima 1,83 ms; s indeksima, bez DDL-a i s `have` samo za svježe id-jeve 0,43 ms | (1) indeksi: positions(status), positions(league_id), orders(status, side, ts), orders(position_id, id); league trades(user, status, opened_ts), trades(status), trades(follow_id); (2) DDL jednom po procesu; (3) trajne veze + `PRAGMA data_version` (4 µs, provjereno u WAL-u): puni prolaz samo kad se trade.db ili league.db promijenio, kad ima posla u tijeku (neuspjela prodaja, pending, gumb) ili svakih 5 s | −88 % po otkucaju i gotovo 0 u mirovanju; provjera može ići svakih 0,25 s pa reakcija na demo ulaz ≤0,25 s umjesto ≤1 s | S (indeksi), M (data_version) | srednji: pravi novac; obvezan sigurnosni puni prolaz i testovi za ponavljanje prodaje. PROOF i limiti se ne diraju |
| S6 | live/store.py:53-61; live/pumpportal.py:117-131, 253, 325; kol/chainwatch.py:377-381; hype/sources.py:191-196; league/auto.py:265-311 | wake datoteku dira trade BILO kojeg od do 200 walleta s popisa (ne samo praćenih u league.db), svaki Helius događaj i svaki KOL post s CA; nakon wakea vrti se cijelo tijelo petlje (copy, auto sell, simianx, dca, rekt, povijest). Učestalost u produkciji nije izmjerena: PumpPortal ključ je bez SOL-a (audit/2026-11-09-autopilot.md:25) | wake samo kad je wallet ili račun stvarno praćen (skup aktivnih praćenja, keš 30 s); na wake samo `copy.run_once`, ostali koraci na 20 s | copy prolazi samo na bitne događaje; kad se tok financira nema ~1 punog prolaza u sekundi (15–25 ms + do 20 DexScreener poziva/min) | S | nizak; 20-s otkucaj ostaje kao mreža |
| S7 | league/copy.py:582-583, 288-327, 600-606 | `since` je 120 min za SVE izvore, iako se kupnja starija od 10 min samo zapiše kao "prekasno"; svaki prolaz otvara 3–4 veze i čita isti prozor. Sintetika 9,4 ms | brzi prolaz (wake i 20 s): pozivi 40 min (10 + prozor ekipe 30), kupnje walleta 10 min, prodaje 120 min samo za tokene s otvorenom kopijom; puni prolaz od 120 min jednom u minuti (da "prekasno" i dalje uđe u dnevnik) | 3–10× manje redaka po brzom prolazu; manje `_logged` upita i "info" redaka | M | srednji: ulazna logika pravog novca, testovi copy petlje moraju ostati zeleni |
| S8 | dexscreener/client.py:40-42, 203-215; event_calendar/http.py:18, 201-226, 295-308; league/copy.py:379-387; ui/paper.py:45-52 | živi dohvat ide kroz `get_json(timeout=30)` s 4 ponavljanja i `sleep(min(60, max(Retry-After, 2**n)))`: copy i TP/SL petlja mogu stajati do ~150 s (ili 4×60 s) na jednom DexScreener zastoju. Svaki odgovor s TTL-om 3 s piše se kao datoteka na disk | `tokens_live` s `timeout=4, retries=0` (neuspjeh = "nema cijene ovaj prolaz", već podržano); za TTL ≤5 s keš u memoriji procesa, bez diska | petlja novca nikad ne stoji dulje od ~4 s; −~45 upisa datoteka/min (40–200 KB svaka, procjena) | S | nizak |
| S9 | run_tg.py:104-116, 86-97, 56-83; tg/history.py:38-56; tg/poll.py:58-76 | satni `housekeeping` (otkrivanje, TGStat, 30 stranica povijesti s razmakom 1,5 s) ide u istoj petlji prije `poll.tick`: praćeni kanali se tada ne čitaju ~1–2 min. `due()` svake 3 s čita sve kandidate, sve mrtve i sva imena kanala; sintetika 7,2 ms | housekeeping u vlastitu nit ili proces sa svojom vezom; u `due()`: kandidati s LIMIT i samo kad je validacija na redu, `known` samo za praćena imena, keš praćenih 15 s | poziv praćenog kanala stiže u 2–3 s i tijekom sata (sada rupa; poziv stariji od 120 s "po podacima" se preskače, league/copy.py:58, 696-698); due <1 ms | M | nizak do srednji: dva pisca u tg.db, kratke transakcije |
| S10 | ui/pravitrade.py:916-929; league/copy.py:209-212 | `followed_wallets()` zove `copy.follows()` na običnoj read-only vezi; `dict(r)` baca TypeError koji se proguta. Ponovljeno na kopiji: 10 praćenih walleta → funkcija vraća 0 (`followed_targets` vraća 25). "Zovu sada", "pametni novčanici kupili" i pop-up zato vide samo dokazane wallete, ne one koje Autopilot prati; baza se pritom otvara svake sekunde uzalud | običan upit `SELECT target FROM follows WHERE user=? AND active=1 AND kind='wallet'` + keš 15 s (i za `dokazani.current`) | točan signal praćenih walleta; 2 veze manje u sekundi | S | nizak |
| S11 | ui/pravitrade.py:1629, 1608-1618 | fragment pozicija svake sekunde čita sve potpise iz `orders` za rječnik iz kojeg treba najviše 60 | `WHERE position_id IN (prikazane zatvorene)` uz indeks orders(position_id, id); HTML fragmenta keširati po `PRAGMA data_version` trade.db | 1,6 → ~0,2 ms; ne raste s poviješću | S | nizak |
| S12 | ui/pravitrade.py:1717-1728; audit/2026-11-09-autopilot.md:27 | JS svake sekunde redom dohvaća 4 fragmenta i kad je sekcija zatvorena; u 24 h 62.638 odgovora 200 i 40.689 prekinutih (499) | dohvat samo otvorenih sekcija (dizajn.md §2 to već traži); jedan zahtjev s verzijama koji vraća samo promijenjene dijelove ili 204 | 4 → ≤1 zahtjev/s po gledatelju | M | nizak |
| S13 | live/store.py:53-54, 64-68; live/pumpportal.py:341-344, 109 | EXPLAIN: `DELETE FROM live_trades WHERE ts < ?` = `SCAN live_trades` (indeksi su samo (sig, mint) i (mint, ts)); `CREATE TABLE IF NOT EXISTS` u svakom flushu; live_launches SCAN + sort svake minute | brisanje po rowidu (redovi ulaze redom vremena: zapamtiti najveći rowid pri svakom čišćenju i brisati do onoga od prije 48 h); DDL jednom; indeks live_launches(ts) | čišćenje razmjerno obrisanom, kraća brava pisanja na hype.db (webhook i hype scan manje čekaju) | S | nizak |
| S14 | ui/paper.py:14, 109-150; ui/data.py:473-478 | /api/paper svakih 15 s po gledatelju čita SVE paper tradeove i parsira JSON stanja svakog | zajednički keš 10 s (kao ui/league.py:102-113); zatvorene zbrojiti jednom i osvježiti kad se promijeni `MAX(closed_ts)` | nije izmjereno; raste s brojem demo tradeova | S | nizak |
| S15 | run_paper.py:931-932; paper/store.py:10-13; live/pulse.py:105-106 | minutni `_tick` filtrira `candidates` po first_ts bez indeksa; `_live_loop` svakih 5 s čita live_alerts po ts (ključ počinje tokenom) | indeks candidates(first_ts), indeks live_alerts(kind, ts) | nije izmjereno | S | nizak |
| S16 | trade/executor.py:49-58; league/copy.py:83-90; league/dca.py:36-46; kol/store.py:90-97; kol/chainwatch.py:324-329; ops/health.py + start.sh:56; kol/minute.py:400-404; run_ui.py:734-736 | sitnice istog oblika: DDL i PRAGMA table_info pri svakom otkucaju ili webhooku; novi Python proces svake minute za nadzor memorije; hot lista i TP/SL bazen i kad prolaz nije ništa izmjerio; prijevod fragmenta za EN svake sekunde | "jednom po procesu" zastavica (kao league/store._MIGRATED); nadzor memorije u dugoživući proces CPU čuvara; bazen samo kad je n > 0 ili svakih 10 min; keš prijevoda po sažetku tijela | mali, ali uklanja ~15 DDL naredbi po otkucaju | S | nizak |

## 3. Što može biti događaj umjesto anketiranja

- **run_trade (1 s)**: signal promjene već postoji u SQLiteu: `PRAGMA data_version` na trajnoj vezi (provjereno, mijenja
  se na tuđi commit i u WAL-u). Alternativa je druga wake datoteka koju dira copy petlja pri ulazu i izlazu te gumbi
  stranice. Anketiranje baze ostaje samo kao sigurnosni prolaz od 5 s.
- **copy petlja**: wake postoji; nedostaje sam događaj. Webhook i PumpPortal znaju (wallet, mint, strana, vrijeme):
  zapisati ga u mali red (datoteka s recima) pa `run_once` obradi baš njega, a čitanje baza po vremenu ostane za
  20-s prolaz.
- **"Zovu sada" i zivo**: preračun na isti wake (novi poziv, objava ili kupnja), DexScreener osvježavanje samo dok
  netko gleda (S3).
- **Telegram 2 s**: slušač već postoji u kodu (`run_tg.py telethon`, start.sh:152). Treba Telegram račun s brojem
  mobitela; sam API se ne plaća. Po pravilu o troškovima prvo izmjeriti koliko praćenih kanala i koliko kašnjenja
  danas ima (stupac `lag_s`), pa odlučiti.
- **X pozivi**: već su webhook (kol/xhook.py:17, provjera kod pružatelja svakih 30 s). Kraći interval je trošak:
  prvo izmjeriti.
- **Walleti**: Helius webhook i PumpPortal su već događaji. PumpPortal trenutno ne isporučuje tradeove (ključ bez SOL-a).
- **Cijene za TP/SL**: besplatnog guranja nema. `wanted()` ne pretplaćuje otvorene pozicije računa pravi-trade
  (live/pumpportal.py:100-107 čita samo paper.db i strat.db); pretplata na njih stoji 0,01 SOL na 10.000 tradeova
  (pumpportal.py:26-28): prvo izmjeriti na 1–2 pozicije. Do tada DexScreener svake 3 s samo za otvorene pozicije.
- **Fragmenti stranice**: jedan zahtjev s verzijama (ili SSE) umjesto 4 u sekundi (S12).
- **Dump provjera (2 s)**: provjeravati samo tokene koji su dobili trade od zadnje provjere.

## 4. CPU čuvar: što pauzirati prvo

Nikad ne pauzirati (lanac novca):
1. `run_trade.py follow` (swap u tijeku).
2. `run_ui.py`: u njemu su copy petlja, TP/SL, webhookovi i stranica. Proces se ne zaustavlja; njegove niti se
   usporavaju iznutra (zastavica "CPU vruć": osvježivač Autopilota i zivo s 1–2 s na 5 s, warmer stranica čeka).
3. `run_live.py` (PumpPortal veza: zaustavljanje puni red i izaziva ponovno spajanje, a on brani petlje spajanja).
4. `run_tg.py loop` dok postoje praćeni Telegram kanali (nakon S9 housekeeping se smije pauzirati zasebno).

Smije čekati, ovim redom (prvo se pauzira ono na vrhu):
1. djeca gradnje stranica (`run_ui.py --render`): /pregled 60–116 s i /tokens ~60 s CPU-a svakih ~7 min
   (audit/2026-11-09-autopilot.md:26), najveći dnevni potrošač.
2. `run_hype.py scan` (dijete run_papera svakih 120 s) i `run_paper.py` (demo, koltest, strat; nije izvor pravog novca
   dok je follow_paper zaključan).
3. `run_kol.py loop` (krug svakih 20 min) i `run_kol.py minute-loop` (zaostatak mjerenja).
4. `run_sched.py` poslovi (masovno, postai, market, usage, tokenstatus), `run_report.py`, `run_simianx.py`,
   `run_watch.py`, wallets dokazani/copy, rugfilter.archive, satno održavanje baza.
5. `run_top.py once` zadnji u ovoj skupini: njegov rug check hrani zaštitu ulaza (`_concentration`).

Ograničenje: proces zaustavljen usred pisaće transakcije drži bravu baze (hype.db, kol.db) pa webhook ide u spool;
zato kratki odsječci (do ~0,5 s, kako dizajn predviđa) i nikad dulje zaustavljanje.

## 5. Provjereno / Pretpostavka

**Provjereno** (kod pročitan na navedenim recima; EXPLAIN QUERY PLAN i mjerenja na sintetičkim kopijama):
planovi upita u S5 i S13; vremena 166 / 146 / 17,5 / 9,4 / 7,2 / 3,5 ms; S10 ponovljen stvarnim funkcijama;
`PRAGMA data_version` radi kao signal promjene; indeksi iz S5 daju SEARCH umjesto SCAN.

**Pretpostavka / nije provjereno**: brojevi redaka u produkciji osim zadanih veličina tablica (pozivi u 14 dana,
token_tier, positions, orders, channels, paper trades); stvarni udio CPU-a na Renderu po petlji; učestalost wake
datoteke (ovisi o financiranom PumpPortal ključu); broj praćenih i vrućih Telegram kanala; veličina DexScreener
odgovora. Prije i poslije popravaka izmjeriti na Renderu: CPU u mirovanju bez otvorene stranice, CPU s otvorenim
pop-upom, broj DexScreener poziva u minuti.
