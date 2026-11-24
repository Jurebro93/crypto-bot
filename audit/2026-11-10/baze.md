# Baze: što imamo, što fali profitabilnom Autopilotu, noćni "data audit" (audit 10.11.2026.)

Grana `ccr-232765a7-33e8r8`, kod samo čitan. Produkcija se nije mogla upitati: veličine su iz zadatka (satni ispis
`zdravlje: ... najveće tablice`, ops/health.py:155-159), sve ostalo iz koda. Planovi upita i uštede indeksa provjereni
su na praznim/sintetičkim kopijama shema u scratchpadu (SQLite 3.53.1). **Provjereno** = pročitano u kodu ili izmjereno
na kopiji; **(P)** = pretpostavka / nije provjereno na produkciji.

## Izravan odgovor

1. **Najveća rupa za Autopilot su novčanici, ne influenceri.** `chain_trades` prodaje nemaju SOL iznos ni količinu
   tokena (B1), pa ROI praćenih novčanika uživo ne postoji, lista "novčanici 7/14/30 d" je uvijek prazna (B15), a
   "dokazani" se osvježavaju samo iz noćne povijesti (B20). Minutne staze postoje samo za pozive, ne za kupnje
   novčanika (B4). Kašnjenje naše kopije se zapisuje, ali ga nitko ne čita (B9).
2. **Masovna sjenovita knjiga tiho gubi točke na dva načina.** (a) `shadow.label` otpisuje svaku masovnu točku
   stariju od 24 h jer još nema cijenu, a `shadow.prune` briše povijesne starije od 30 d (B24, reproducirano na
   kopiji baze). (b) Dok minutna petlja ima zaostatak (4.591 tokena) drži GeckoTerminal do 540 s po prolazu;
   `learn/masovno.py` tada dobije prazno i točku otpiše kao `bez_cijene` (B2, B3).
3. **Mjera pogotka je preoptimistična na dva mjesta:** token bez poznatog supplyja prolazi prag 30k (B7), a za X
   pozive ne znamo kad smo ih mi vidjeli (nema `seen_ts`, B6), pa "ulaz u minuti objave" nije dokazan po izvoru.
4. **Pohrana:** sigurno se vraća ~390 MB (wallet_trades −320 MB, ticks −70 MB, mjereno na kopiji), vjerojatno još
   150–250 MB (P). Disk nije hitan (2,2 GB slobodno); dobitak je manji page cache i brže čitanje.
5. **`ops/dataaudit.py`:** nacrt u §3, 66 upita, svi izvršeni na kopijama shema; noću puni prolaz pod `ops.heavy`,
   nakon starta samo lagani (indeks ili mala tablica). Isti JSON hrani dnevnik naslovnice (§4) i može zamijeniti tri
   dnevna puna čitanja `calls` (B17).

## 1. Karta baza (svrha · tko piše · tko čita · indeksi · retencija · svježina)

Procesi (start.sh): `ui` :42, `trade` :46, satno održavanje :52, arhiva rugova :59, `run_top` :65, kalendar/dex noću
:73-74, `run_watch` :83, `run_hype learn` noću :89, novčanici harvest/score noću :101-103 i dokazani/copy svaka 3 h
:104-117, `kol` krug 20 min :124, `minute` :127, `tg` :150, `sched` :158 (run_sched.py:169-189), `dugo` noću :166,
`simianx` :170, `paper` :172, `live` :175. Noć = 01–06 Zagreb (ops/heavy.py:120). KOL krug danju: collect, chain,
xhook, live, snap, converge, crew; noću još score, traces, measure, flows, deleted (run_kol.py:258-264).

### hype.db (1,39 GB) · piše 7+ procesa (B19)
| tablica | svrha | piše | čita | indeksi | retencija | svježina |
|---|---|---|---|---|---|---|
| hype_signals (207 MB) | red po tokenu po skenu: ocjena, cijena, mcap, features | hype/store.py:29, sken u `paper` svakih 120 s (run_paper.py:1129,1174) | ~22 modula (learn/*, ui/*, live/pumpportal.py:113, strat/signals.py) | PK(token,ts); `hype_signals_cover` (ops/dbs.py:105) | bez brisanja po starosti; satno sažimanje features/weights (dbs.py:69-97); arhiva ruga ostavi prvi red (rugfilter/archive.py:234) | 2 min |
| hype_snapshots | cijena/mcap/liq praćenih tokena | hype/store.py:46 (run_hype.py:402,570) | learn/outcomes, learn/shadow, ui/prijedlog_log.py:71, ui/data.py:295 | PK(token,ts) | samo mrtvi tokeni 14 d (ops/prune.py:191-199) | ~20 min |
| hype_details | JSON "extra" po tokenu po skenu | hype/store.py:41 | prvi red: learn/confmodel.py:93, learn/correlations.py:26; zadnji: ui/evidence.py:62, ui/data.py:274; svježi: ui/radar.py:125 | PK(token,ts) | kao snapshots; NIJE u sažimanju (B16) | po skenu |
| live_trades (194 MB) | PumpPortal tradeovi ≤40 tokena i ≤200 novčanika (live/pumpportal.py:25) | live/store.py:44 (`live`) | live/pulse.py:17,46,84,118; wallets/dokazani.py:171; kol/crew.py:89; run_paper.py:491 | PK(sig,mint); (mint,ts); nema (ts) | 48 h, DELETE svakih 10 min punim čitanjem (live/store.py:19,68; pumpportal.py:341) | < 1 s (kad ključ ima SOL) |
| live_launches / live_alerts / live_state | lansiranja i migracije / dump alarmi / stanje toka | live/store.py:48, live/pulse.py:69 | learn/masovno.py:96, live/pumpportal.py:109 | PK | 7 d / 24 h | s |
| chain_trades (150 + 150 MB) | swapovi ≤100 webhook novčanika (Helius) + praćeni iz PumpPortala | kol/chainwatch.py:359 (`ui` /hook/chain), live/store.py:57 | 15 modula: league/copy.py:321, ui/autopilot.py:290, ui/pravitrade.py:996, ui/zivo.py:157, kol/converge.py:75, kol/insiders.py:122,161, strat/signals.py:81, learn/masovno.py:101, kol/collect.py:637 | PK(sig,mint); `chain_trades_ts` | 14 d (chainwatch.py:49,363; prune.py:44) | sekunde |
| chain_transfers | TRANSFER događaji | chainwatch.py:360 | kol/traces.py:51 | PK(sig,src,dst,mint); nema (ts) | 14 d, DELETE bez indeksa (chainwatch.py:364) | sekunde |
| kol_mentions | X webhook objave (ts = vrijeme objave) | hype/sources.py:187 (`ui` /hook/kol) | league/copy.py:304, kol/converge.py:66, strat/signals.py:109, kol/collect.py:282 (SVE), ui/evidence.py:252 | `kol_mentions_ts` | nema (B11) | sekunde |
| tg_mentions | kopija TG objava s CA | tg/store.py:108 | hype/store.py:61, ui/evidence.py:258, corr/analyze.py:75, dugo/sources.py:78,168 | PK(post,ca); nema (ca) | nema | 30 s |
| token_pulse | DexScreener volumen, kupnje/prodaje m5/h1, holderi za ≤40 zadržanih tokena | hype/pulse.py:100 | ui/data.py:303, report/collect.py:193, rugfilter/collapse.py:59 | PK(token,ts); (ts) | 7 d (pulse.py:31,108) | po skenu |
| token_status | postoji li još par | hype/tokenstatus.py (sched 6 h, run_sched.py:188) | ops/prune.py:190, rugfilter/archive.py | PK | nema | 6 h |
| token_tier / tier_events | klasa i razina tokena / prvi prelazak 100k i 1M | tiers/store.py:107 | learn/shadow.py:126, paper/rules.py:181, ui/data.py:313, ui/landing.py:65 | PK | nema | sken |
| smart_wallets / socials / apify_runs / apify_cache / learn_runs | pomoćno | hype/store.py:55, hype/socials.py:143, hype/apify.py:138, learn/store.py:24 | ui/data.py:331, kol/collect.py:199, ui/radar.py:202 | PK | apify_cache 1 d (dbs.py:28,56); ostalo nema | noć / po pozivu |
| rug_archive / rug_watch / rug_recovered | arhiva rugova | rugfilter/archive.py (satno) | learn/rugprofile, ui/landing.py:65-66 | PK; (archived_ts) | nema | 1 h |
| prijedlog_log | dnevnik prijedloga i ishoda | ui/prijedlog_log.py; ishodi run_hype.py:708 | ui/prijedlog.py:584, ui/pravitrade.py | PK(token,day) | nema | pri gradnji stranice |

### kol.db (353 MB) · piše samo `run_kol.py` (krug, search-round, backfill)
| tablica | svrha | piše | čita | indeksi | retencija | svježina |
|---|---|---|---|---|---|---|
| calls (130 + 47 MB PK) | red po (objava, token) + ishod 1/6/24 h | kol/collect.py:157,650; kol/measure.py:257; kol/snap.py:139 | league/copy.py:299, kol/minute.py:205, ui/public.py:411,505, ui/landing.py:71,82, ui/pocetna.py:269-271, kol/score.py | PK(tweet_id,token); calls_token; calls_handle; calls_ts | `w:` 2 d i neaktivni X 30 d (ops/prune.py:82-108) | unos 20 min, x_hook sekunde; ishod: DexScreener snimke 20 min, GeckoTerminal samo noću |
| kols | račun, ocjena, stats JSON | collect.py:163; kol/score.py | ui/public.py:268 i svi KOL prikazi | PK | neaktivni 30 d | ocjena 1× noću (kv `score_mark`, score.py:442) |
| tokens | par i supply tokena | kol/measure.py:84-92, kol/snap.py:60 | kol/minute.py:209,292-293, learn/masovno.py:236 | PK | nema | 20 min |
| snaps (21 MB) | DexScreener cijena, vol_h1, liq, mcap pozvanih tokena | kol/snap.py:69 | kol/snap.py:127 | PK(token,ts); nema (ts) | 3 d, DELETE punim čitanjem (snap.py:19,70) | 20 min |
| groups / signals / watch | ekipe, signali, lista uživo (DELETE + ponovno) | kol/score.py:211,243,350 | kol/minute.py:478, run_hype, kol/xhook.py | PK | – | 1× noću |
| converge | tokeni koje zove više strana | kol/converge.py | ui/zivo, ui/autopilot, ui/pocetna | PK | 7 d | 20 min |
| kol_ids | KOL novčanik ↔ X račun | kol/idents.py | kol/chainwatch.py:126, collect.py:620, ui/autopilot.py:280 | PK | nema | search-round |
| flows / insiders / kol_wallets, token_hours / sessions | Helius tokovi oko poziva; satni volumen i sesije | kol/flows.py, kol/sessions.py | kol/insiders.py, ui/kol.py, ui/marketpub.py:183 | PK | nema | noć |
| engagers | tko pojačava pozive | kol/crew.py | samo kol/crew.py | PK + 2 | nema | zamrznuto (crew.daily_usd 0, kol/config.json:25) |
| trending, graduates, traces, audits, follows, pair_tests, searches, seen_cache, monitor, kv | pomoćno | istoimeni moduli | isti + learn/masovno.py:125,175 | PK | nema | krug |

### minute.db · piše samo `run_kol.py minute-loop` (start.sh:127)
| tablica | svrha | čita | indeksi | retencija | svježina |
|---|---|---|---|---|---|
| call_path | minutni ishod poziva: entry, lag_s, mcap_e, hi15/30/60, lo60, r60, t5..t30, sl_min (kol/minute.py:59-63, :357) | minute.handle_stats/crew_stats/hot, kol/tpsl.py:183, ui/prijedlog.py | PK; (handle,ts); (token,ts) | 30 d (minute.py:44,368) | poziv star ≥ 70 min, koliko GeckoTerminal dopusti; "još 4591 tokena čeka" (NOCNI-PROGRAM.md:99) |
| call_lv | prva minuta svake razine gore/dolje | kol/tpsl.py | PK; (ts) | 30 d | isto |
| kv | minute_stats, hot_list, minute_retry, tpsl_pool | tg/poll.py, kol/xhook.py, league/copy.py:554-565 | PK | – | svaki prolaz |

### wallets.db (609 MB) · piše `run_wallets.py` (+ `run_rug` krediti, ops/prune)
| tablica | svrha | čita | indeksi | retencija | svježina |
|---|---|---|---|---|---|
| wallets | registar, ocjena, tier, stats | kol/chainwatch.py:104, wallets/dokazani.py:65, ui | PK; (next_check) | nema (oznaka `izbačen`) | bodovanje noću, ≤500 novčanika / 6000 kredita po prolazu (start.sh:103) |
| wallet_trades (252 + 259 + 74 MB) | parsirani swapovi (povijest, sa SOL iznosima obje strane) | wallets/store.py:104 (dokazani, pnl), ui/data.py:368, ui/overview.py:384,436 (puno čitanje), corr/analyze.py:101, dugo/holders.py:128, learn/masovno.py:192, kol/insiders.py:58 | PK(sig,wallet,mint); trades_wallet(wallet,ts) | gubitnicima se brišu (prune.py:156) | noć |
| wallet_sightings / wallet_pnl / helius_credits | viđenja / povijest ocjene / krediti | wallets/store.py:142, ui/data.py:374, ui/overview.py:258, run_wallets.py:182 | PK; (token) | nema | harvest i score noću |
| dokazani | "dokazan dvaput" po prolazu | dokazani.current/latest → chainwatch.py:153, minute.py:605, ui/autopilot.py:261 | PK(wallet,as_of); (as_of) | 30 d (dokazani.py:94) | svaka 3 h (start.sh:116) + nakon noćnog bodovanja |

### Ostale baze
| baza (veličina) | tablice | piše | glavni čitači | indeksi / retencija | svježina |
|---|---|---|---|---|---|
| paper.db (198 MB) | ticks (91 + 70 MB), candidates, trades, trigger_points, reviews, rug_budget, manual_exits, dca_signals | `run_paper` (paper/store.py) | paper/review.py:84, exits/paths.py:99, exits/fit.py:48, learn/shadow.py:184, run_trade.py (trades) | ticks PK(token,ts); ticks 30 d + netrgovani 4 d (store.py:99-103, prune.py:216); ostalo bez retencije | 1 min |
| tg.db (138 MB) | posts (85 MB), channels, kv | `run_tg` (tg/store.py:74, tg/history.py:27, tg/tgstat.py:74) | kol/collect.py:593, league/copy.py:310, kol/converge.py:69, strat/signals.py:112, learn/postai.py:141 | posts PK(channel,post), (seen_ts), (ts); 30 d: bez CA briše, s CA ostaje bez teksta (store.py:116-121) | 30 s (praćeni kanali brže) |
| shadow.db (87 MB) | points (78 MB), kv | DVA pisca iste tablice (B24): `run_learn shadow` (noću satno, run_sched.py:179) i `run_learn masovno` (30 min, :181) | learn/gbm, champion, detektiv, ui/learnpage | PK(id); (status,ts); (point,ts); 30 d (learn/config.json:24) | oznaka 24 h nakon točke |
| ai.db (84 MB) | posts_ai, post_tokens, batches, kv, hipoteze, ideje, detektiv_runs | `run_learn postai` (30 min), detektiv dnevno | postai.features (learn/shadow.py:276, learn/champion.py:264), ui/learnpage.py:220 | (ts), (token,ts); bez retencije | 30 min |
| dugo.db (24 MB) | tokens, candles, ref, snap, book, holders, big_holders, holder_info, listings, learn_runs | `run_dugo` (noću) | ui/dugo, ui/coins.py:217, ui/autopilot.py:319, wallets/store.py:241 | PK; candles i snap 400 d (dugo/store.py:100-102) | 1× noću |
| league.db | follows, copy_log, trades, equity, accounts, auto_rules, dca_*, members, profiles, roles, access_requests … | samo `ui` (nit auto-sell, league/copy.py) | run_trade.py:123-250, kol/chainwatch.py:142, live/pumpportal.py:124, ui/pravitrade | copy_log PK(follow_id,token,side), (ts), 30 d (copy.py:28,617); equity 180 d | 1–20 s |
| trade.db | positions, orders, settings | `run_trade follow` (+ `ui` postavke) | ui/pravitrade.py | PK id; bez retencije | 1 s |
| usage.db | usage (sat, servis, skripta, metoda), account, alerts | svaki proces kroz usage/meter.py (flush 30 s), `run_usage tick` 15 min | ui/usage, banner | PK(hour,…); bez retencije | 15 min |
| public.db | coins, coin_hist | nit `coins-refresh` u `ui` (ui/coins.py:163-172) | ui/coins.py, ui/public.py | PK; hist 400 d (coins.py:141) | 3 h |
| rug.db, topcheck.db | rug_reports; top_check, full_budget | run_rug.py:83-90, run_top.py (3 min) | run_paper, corr, ui/data, league/copy._concentration | PK; rug bez retencije; topcheck 3 d | 3 min / po provjeri |
| corr.db, market.db, calendar.db, watch.db | korelacije; volumen tržišta i makro; događaji; praćenje prije eventa | run_corr (noću), run_market (1 h), run_calendar/run_dex (noću), run_watch (1 h) | ui stranice, eventpick, market/makro | PK; corr KEEP 8, market snap 60 d | kako piše |
| strat.db, koltest.db | demo strategije; KOL test knjiga | niti u `run_paper` (run_paper.py:1076-1096) | ui/strategije, ui/koltest, report | (status,strat), (seen_ts); skip 10 d | 60 s / 30 s |
| simianx.db, nastoken.db, analytics.db | drugo mišljenje; naš token; GSC/GA4 | run_simianx (3 h), `ui` | ui | PK | – |
| retro.db | retrospektivna studija (retro/collect.py:20-30) | ručno, nema posla na serveru | retro/* | – | nije u popisu symlinkova (start.sh:9): na serveru bi nestala pri deployu |

## 2. Nalazi

| ID | gdje (file:line) | dokaz | prijedlog popravka | učinak | trud | rizik |
|---|---|---|---|---|---|---|
| B1 | kol/chainwatch.py:230-232; live/store.py:56; ui/autopilot.py:206,225,300 | Helius parser za prodaju upisuje `sol=None`; PumpPortal zrcalo baca SOL prodaje iako ga ima u retku (`r[4] if r[3]=="buy" else None`); tablica nema stupac količine tokena (chainwatch.py:325). Zato `roi=None` i novčanik nikad ne prođe uvjet. | (a) live/store.py:56 upisati `r[4]` i za prodaju (0 troška). (b) u `parse()` zbrojiti wSOL i native transfere PREMA novčaniku kod prodaje; prvo dan-dva spremiti uzorak payloada (P: polja na živom payloadu nisu provjerena). (c) dodati `tokens REAL`; sva tri pisca imaju pozicijski INSERT (chainwatch.py:359, live/store.py:57) pa se mijenjaju zajedno. | ROI i cijena svake kupnje/prodaje praćenih novčanika uživo, bez Helius kredita za povijest; lista 7/14/30 d proradi; temelj za B4, B9, B20 | S (a), M (b, c) | nizak; predznak i naknade u iznosu provjeriti na uzorku |
| B24 | learn/shadow.py:258-259, 271-272, 329-330; learn/masovno.py:69-74, 29, 143-158; run_sched.py:179, 181; learn/config.json:24, 74-75 | Sjenovita i masovna knjiga dijele tablicu `points`. `shadow.label` uzima SVE `ceka` točke starije od 24 h, bez filtra po vrsti; masovna točka nema `price` dok je masovno ne označi, pa je redak 271-272 otpiše kao `bez_cijene`. Reproducirano na kopiji: `kol_poziv`, `novcanik_kupio` i `povijest_poziv` → `bez_cijene`. `shadow.prune` uz to otpisuje `ceka` starije od 72 h i briše sve starije od 30 d, a masovno noću dodaje do 1.200 povijesnih točaka starih do 180 d: starije od 30 d nestanu u istom satu i sutradan se dodaju ponovno. | U `shadow.label` i `shadow.prune` filtar na vlastite vrste (`shadow.POINTS`: prvi_signal, mc100k, mc1m, kandidat); masovno otpisuje i briše samo svoje; `history_days` ≤ `keep_days` ili brisanje po `labeled_ts`. | Masovna knjiga (izvori `kol_poziv`, `novcanik_kupio`, bondao, trending, kontrola) prestaje gubiti točke koje ne stigne označiti prije sljedećeg prolaza sjenovite knjige; GeckoTerminal pozivi ne idu na točke koje se odmah brišu | S | nizak. (P) broj izgubljenih u produkciji: metrike s1, s4 |
| B2 | learn/masovno.py:257-263, 287-292; event_calendar/http.py:303-304; kol/measure.py:103, 239-241 | `get_json` vrati None kad host drži drugi posao → `ohlcv` vrati `[]` → točka starija od 6 h dobije trajno `bez_cijene` (dospjele točke su uvijek starije od 24 h). Ista stvar u kol/measure: prazan odgovor zatvara pozive starije od 24 h bez ishoda (`complete = (ts+24h <= now)`). Minutna petlja je isti kvar popravila 10.11. (kol/minute.py:117-120). | Prije dohvaćanja `if http.cooling(GECKO) > 0: break` bez promjene statusa; `bez_cijene` samo kad je host slobodan i odgovor stvarno prazan; vratiti u `ceka` masovne točke otpisane u zadnja 72 h (starije otpisuje `shadow.prune`, B24). | Sjenovita knjiga ("učionica", 5 izvora točaka uključujući `novcanik_kupio`) prestaje gubiti oznake dok traje minutni zaostatak | S | nizak. (P) opseg gubitka u produkciji nije izmjeren: metrike s3, s4 u §3 |
| B3 | kol/minute.py:53,285-287,400,414; event_calendar/http.py:78-91; kol/measure.py:198-199 | Dok ima zaostatka minutna petlja rezervira host na 540 s pa spava 20 s; `reserve()` prepiše bilo čiju rezervaciju (zadnji pisac pobjeđuje), pa se s noćnim KOL mjerenjem (480 s) međusobno prekidaju. Zajednički razmak 3,5 s = ~17 poziva/min (http.py:38). | Jedan red čekanja s prioritetima umjesto prepisivanja: novi pozivi praćenih i kandidata za vruću listu, pa noćni `measure`, pa masovno; ili minutna drži najviše pola vremena danju. Usporediti s prijedlogom ključa u svijece.md. | Svi poslovi dobiju dio besplatnog limita; nema izgladnjivanja | S–M | nizak |
| B4 | kol/minute.py:203-214 (`kind='call'`, bez `w:`), :108-120, :236-258; learn/masovno.py:99-104 | Minutna staza postoji samo za pozive. Kupnje novčanika imaju samo 5-min/24-h stazu prve kupnje u danu (masovno). Svijeće se nakon izračuna bacaju, pa "relevel" iste svijeće skida ponovno (do 40 tokena po prolazu). `kol/tpsl.py:183` čita samo `call_path`, pa praćenje novčanika nema izlaz "po podacima". | Tablica `wallet_path` u minute.db (sig, wallet, token, ts, entry, lag_s, mcap_e, hi15/30/60, lo60, r60, lv, exit_ts i exit_ret na prvoj prodaji novčanika) za kupnje dokazanih i praćenih; iste funkcije `path()`. Prvo izmjeriti koliko je takvih kupnji dnevno (metrika h9). Svijeće čuvati komprimirano samo ako disk dopusti (procjena 2–4 KB po tokenu). | TP/SL po podacima i "isplati li se kopirati s našim kašnjenjem" za novčanike, jedini izvor s dokazanom vještinom (wallets/dokazani.py:3-6) | M | GeckoTerminal budžet; mjeriti prije |
| B5 | kol/measure.py:96-104, 178-190; kol/minute.py:108-116; learn/masovno.py:248-266 | Isti pozvani token skidaju tri modula: 5-min svijeće na kontrolnim točkama 1/6/24 h, 1-min nakon 70 min, 5-min za točku `kol_poziv`. HTTP keš ne pomaže (URL sadrži `before_timestamp`). | Minutni dohvat proširiti na 2 h prije poziva (i dalje ≤ 1000 svijeća) i iz njega upisati p0, pre2h, r1h, volumen; `measure` tada preskače točku 1 h; `kol_poziv` uzima ishod iz `calls` umjesto vlastitog dohvaćanja. | (P) ~30–40 % manje GeckoTerminal poziva po pozvanom tokenu → zaostatak pada brže bez novog troška | M | srednji (dira mjerenje); testovi measure/minute |
| B6 | kol/store.py:27-33, 84-87; kol/collect.py:157-161; hype/sources.py:171-181; tg/store.py:23-25 | `calls` i `kol_mentions` čuvaju samo vrijeme objave; vrijeme kad smo objavu vidjeli ima samo tg.db (`seen_ts`, `channels.lag_s`). Minutna mjera uzima ulaz na zatvaranju minute objave (minute.py:126-135), a "po podacima" ulazi samo do 120 s nakon poziva (league/copy.py:58). | Stupac `seen_ts` u `calls` (MIGRATE) i `kol_mentions`, upis `now` pri INSERT-u (collect.save ima imenovane stupce: sigurno); TG prenosi `p.seen_ts`. Minutna staza iz istih svijeća računa i ulaz "u minuti kad smo vidjeli". | Stvarno uhvatljiv postotak pogodaka po izvoru (x_hook, webhook, timeline, tg); izvori koji strukturno kasne izlaze iz "po podacima" | M | nizak (dodatni stupac) |
| B7 | kol/measure.py:73-81, 209, 221-224; kol/minute.py:211-212, 355-356, 442-446 | GeckoTerminal rezerva upisuje token sa `supply=None`; kandidati propuštaju `mcap0 IS NULL`; `bad='mcap'` se postavlja samo kad je mcap poznat; `_rows` broji i `mcap_e IS NULL`. Pravilo: ispod 30k se ne analizira. Token bez para nakon 3 pokušaja zatvara sve pozive bez ishoda. | (a) supply iz istog odgovora poola (fdv / cijena) (P: polja odgovora nisu provjerena); (b) dok je nepoznat: `mcap_e IS NULL` ne ulazi u hot/tpsl; (c) ponovno otvoriti pozive kad `tokens.pair` stigne kasnije. | Pogodak računa samo tokene ≥ 30k; manje trajno neizmjerenih poziva | S | nizak; nekim računima pada broj izmjerenih |
| B8 | kol/minute.py:44; kol/tpsl.py:46,51 | Staza se briše nakon 30 d, a odluka traži 10 izmjerenih poziva u 30 d. Račun s 5 dobrih poziva mjesečno nikad ne dobije odluku. | `KEEP_DAYS` 120 za call_path/call_lv (tablice su male), tpsl prozor 90 d uz postojeće pravilo "noviji dio mora biti u plusu". Prvo pogledati raspodjelu (metrika m3). | Više izvora s odlukom, bez ijednog novog poziva API-ju | S | nizak |
| B9 | strat/run.py:151-162, 333, 107; league/copy.py:41-43, 334-336, 28, 617 | `pos["kopija"]` (delay_s, entry_px, wallet_fill) se upisuje u JSON `positions.state`, a nigdje se ne čita (grep); `wallet_rank` broji samo strategije 'novcanici' i 'top_novcanici'. `copy_log` ima `ev_ts` i `ts`, ali jedan red po (praćenje, token, strana), 30 d i razlog kao slobodan tekst. | Zbirka po izvoru: n kopija, medijan kašnjenja, premija ulaza prema njegovoj cijeni, prosječan povrat; ispis u dataaudit (x2, l2) i treći dokaz u `wallets/dokazani` (naša kopija). PROOF brava ostaje ista. | Zna se koji se dokazani novčanik isplati NAMA, s našim kašnjenjem | M | nizak |
| B10 | kol/snap.py:57-58, 69; hype/pulse.py:25-31; ui/coins.py:31-36 | Broj kupnji/prodaja kroz vrijeme čuva samo `token_pulse` (≤ 40 tokena, 7 d). `kol.snaps` iz istog DexScreener odgovora sprema cijenu, vol_h1, liq, mcap, a `txns` baca. | Stupci buys_m5, sells_m5, buys_h1, sells_h1 u `snaps` (INSERT je pozicijski, snap.py:69). +~5 MB. | Omjer kupnji/prodaja u trenutku poziva i nakon njega za svaki pozvani token (DNEVNIK 9.11., "Čeka Juru" 2), 0 novih poziva | S | nizak |
| B11 | hype/sources.py:184-188; kol/collect.py:257-296; run_kol.py:36 | `kol_mentions` nema brisanja; svaki krug (20 min, i u search-roundu) čita SVE retke i svaki ponovno sprema (INSERT OR IGNORE + upsert `kols`); `fix_hook_rows` uz to radi `tweet_id LIKE 'hook-%'` = puno čitanje `calls` (plan: SCAN calls). | Vodeni žig u `seen_cache` kao `from_chain` (collect.py:634,654); retencija 30 d u ops/prune; `fix_hook_rows` jednom, ne svaki krug. | Lakši dnevni krug, manje WAL prometa u kol.db | S | nizak |
| B12 | wallets/store.py:40-43 | PK(sig,wallet,mint) služi samo za `INSERT OR IGNORE`; nijedan upit ne traži po `sig` (grep). Svi čitači idu po novčaniku (i vremenu) ili čitaju sve. Sintetika 200k redaka: 96,2 MB → 43,3 MB s `PRIMARY KEY (wallet, ts, sig, mint) WITHOUT ROWID` (−55 %); plan `SEARCH ... USING PRIMARY KEY (wallet=? AND ts>?)`. | Noćna migracija pod `ops.heavy` (jedini pisac `run_wallets` ide pod istu bravu). Ovisnosti: ui/landing.py:69 i ui/pocetna.py:302-325 (`MAX(rowid)`). | ~−320 MB (585 → ~265 MB), brže čitanje povijesti novčanika | M | srednji: prepis 609 MB baze; kopija prije |
| B13 | paper/store.py:14-15 | `ticks` PK(token,ts): autoindeks 70 MB uz tablicu 91 MB; svi upiti su `token=? AND ts...`. Sintetika: 43,2 → 24,6 MB (−43 %) s WITHOUT ROWID. | Jednokratna migracija u `paper/store.connect` (kao ALTER na :33-44). Ovisnost: ops/prune.py:74 briše po `rowid`. | ~−70 MB | S–M | srednji: `paper` piše svaku minutu, 10–20 s stanke pri startu |
| B14 | live/store.py:68, live/pulse.py:118; kol/chainwatch.py:364, kol/traces.py:51; kol/snap.py:70; ui/evidence.py:258; kol/measure.py:186-190 | Planovi: `DELETE FROM live_trades WHERE ts<?` = SCAN (194 MB, svakih 10 min); brisanje `chain_transfers` i `snaps` po ts = SCAN; `tg_mentions WHERE ca=?` = SCAN pri svakom otvaranju dokaza tokena; `measure.due` = SCAN calls preko calls_token. | Indeksi kroz `ops/dbs.TIME_INDEXES` (dbs.py:105-107), građeni u satnom/noćnom poslu: `live_trades(ts)`, `chain_transfers(ts)`, `tg_mentions(ca, time)`, djelomični `calls(token, ts) WHERE complete = 0` (plan nakon toga: SCAN samo otvorenih). | Manje stalnog IO-a danju; brži noćni `measure` | S | nizak (+~10–20 MB indeksa) |
| B15 | ui/autopilot.py:10, 20-22, 272-304, 254-258; kol/chainwatch.py:49 | `wallet_recs` svakih 5 min čita "30 dana" `chain_trades` za sve webhook novčanike, a retencija je 14 d i rezultat je zbog B1 uvijek prazan (i sam kod to kaže, :254-258). Komentar ":10 kept 30 days" je zastario. | Do B1: ne čitati (vratiti prazno); nakon B1: prozori 7/14 i čitanje samo novih redaka od zadnjeg puta. | Manje čitanja 150 MB tablice u UI procesu | S | nizak |
| B16 | ops/dbs.py:69-97; learn/confmodel.py:91-94, ui/evidence.py:62; learn/postai.py:110, 204, 277; kol/config.json:25; strat/run.py:333; start.sh:9 | Nitko ne čita: srednje retke `hype_details` (čitaju se prvi, zadnji i zadnji sati); `batches.ids` gotovih serija (čita se samo `status='poslano'`); `posts_ai`/`post_tokens` starije od prozora (6 h prije točke, točke žive 30 d); `engagers` se više ne puni; `state.kopija` (B9); retro.db nema posla. | `hype_details`: brisati retke starije od 48 h koji nisu prvi ni zadnji po tokenu; `batches.ids = NULL` po završetku; `posts_ai` i `post_tokens` > 45 d. Prvo izmjeriti (dbstat 12 najvećih, §3). | ai.db −30 do −50 MB (P); `hype_details` (P) nepoznato | S | nizak |
| B17 | ui/landing.py:23, 71, 82-83; ui/pocetna.py:233-244, 269-277; ui/marketpub.py:24, 183, 194-199 | Brojači stranica danju čitaju cijele tablice: naslovnica svakih 30 min dvaput cijeli `calls` (plan: SCAN calls); Pregled `_sql_counts` bez raspona u WHERE: `calls` ×2, `live_trades`, `posts`; javna "sati trgovanja" cijeli `token_hours` i agregat `calls`. | Stranice čitaju gotove brojke iz noćnog JSON-a (§3, §4); živo ostaje samo ono što je indeksirano. | CPU i IO danju ostaju Autopilotu (cilj ≤ 90–95 %) | M | nizak; brojke na stranici stare do 24 h (napisati "stanje u 02:00") |
| B18 | kol/minute.py:180-181, 203-214, 219-224, 260-263, 371 | `candidates()` ima koreliran podupit po pozivu (plan: CORRELATED SCALAR SUBQUERY ×2) i zove se dvaput po prolazu (`due` i `waiting`), uz učitavanje svih ključeva `call_path`. | Jedan `GROUP BY token` za broj pozivatelja, `waiting` iz rezultata `due`. | Manje CPU-a procesa `minute` (nije pod `nice`) | S | nizak. (P) trajanje u produkciji nije izmjereno |
| B19 | kol/chainwatch.py:266-283, 348-360; live/store.py:21-27; tg/store.py:101-111; start.sh:36-38, 59; ops/dbs.py:253-289 | U hype.db pišu: sken (`paper`), `live`, `ui` (dva webhooka), `tg`, poslovi `sched`, satna arhiva rugova, sažimanje/VACUUM. Zbog zaključavanja postoji spool za webhook i ponavljanje u `live`. | Kasnije: tablice puta novca (chain_trades, chain_transfers, kol_mentions, live_*) u vlastitu `live.db`. Prije toga mjeriti: broj datoteka u `chain_spool` (metrika f2). | Sažimanje baze od 1,39 GB više ne može zadržati upis signala | L | srednji–visok (15 čitača po putanji); ne u ovom valu |
| B20 | start.sh:101-117; wallets/dokazani.py:57-84; kol/chainwatch.py:152-161 | Lista "dokazani dvaput" računa se svaka 3 h, ali iz `wallet_trades` koji se puni samo noću; isti novčanici su u webhooku (prvi u `wanted`), no njihove prodaje nemaju SOL (B1). | Nakon B1: dio "poslije reza" računati i iz `chain_trades` zadnjih dana. | Novčanik koji je počeo gubiti ispada isti dan, ne sutra | M | nizak |
| B21 | ops/prune.py:54-55, 232-270; render.yaml (nema DATA_PRUNE); DNEVNIK.md:182 | Brisanje radi samo uz `DATA_PRUNE=on`; u render.yaml ga nema, a u dnevniku je "Čeka Juru". `.rows.json` pamti samo zadnje brojeve, pa rast po danu nije vidljiv. | dataaudit ispisuje način rada čišćenja i rast po danu iz vlastite povijesti. | Vidi se briše li se išta | S | – (P) stanje varijable na Renderu nije provjereno |
| B22 | kol/collect.py:163-169; wallets/store.py:66-72 | `kols.first_seen` je vrijeme najstarije objave, `wallets.first_seen` vrijeme viđenja na lancu: oboje može biti u prošlosti, pa "novi danas" po tom stupcu ne broji ono što je danas otkriveno. | Brojači "novo danas" iz razlike dviju snimki u 02:00 (§4), ne iz `first_seen`. | Dnevnik naslovnice ne laže | S | – |
| B23 | tg/store.py:116-121; run_tg.py:92 | Satno `UPDATE posts SET text=NULL WHERE seen_ts < ?` svaki put prepisuje sve stare retke (i one već bez teksta). | Dodati `AND text IS NOT NULL`. | Manje WAL prometa u tg.db | S | nizak |

## 3. Nacrt `ops/dataaudit.py` (samo čita)

**Pokretanje.** `python3 -m ops.dataaudit --light`: 15 min nakon starta, samo ako je zadnji izvještaj stariji od 6 h
(20+ deploya dnevno). `python3 -m ops.heavy --night -m ops.dataaudit --full`: jednom po noći (datum Zagreb u
izvještaju; drugi poziv istog dana izlazi odmah).
**Osigurači.** Veza `file:...?mode=ro` + `PRAGMA query_only=ON`, `timeout=2`; svaki upit ima stoper
(`set_progress_handler`: prekid nakon 3 s u lakom, 30 s u punom načinu, metrika tada piše `"prekinuto"`); zaključana
ili nepostojeća baza/tablica se preskače; cijeli lagani prolaz ≤ 60 s, puni ≤ 10 min. `MIN` i `MAX` uvijek u ZASEBNIM
upitima (zajedno čitaju cijeli indeks: plan `SCAN ... COVERING INDEX`). Gdje planer zna pogriješiti stoji `INDEXED BY`.
**Izlaz.** Do 14 linija `DATAAUDIT <dio> ...` u logu + `$DATA_DIR/output/dataaudit/YYYY-MM-DD.json` i `latest.json`
(čuva se 60 dana). Rast po danu = razlika prema jučerašnjem JSON-u. Broj redaka velikih tablica uzima se iz
`DATA_DIR/.rows.json` (ops/prune.py:232-270 ih već broji svaki sat), bez novog čitanja.

    DATAAUDIT 2026-11-11 02:41 puni | disk 3,0/5,2 GB | 24 baze | upozorenja 4
    DATAAUDIT pozivi: 24 h 1.812 (X 402, TG 1.391, hook 19) · 24–48 h s ishodom 71 % (gecko 12, dex 59) · bez para 22 % · supply nepoznat 9 % · ocjene stare 3 h
    DATAAUDIT minutna: staza 12.440 (čista 9.120, bez svijeće 2.010, <30k 1.310, mcap nepoznat 640) · pozivi 2–26 h pokriveni 38 % · čeka 4.591 tokena · računi 1: 2.210, 2–4: 610, 5–9: 140, 10+: 38 · vruća lista 6 X, 2 TG, 14 novč.
    DATAAUDIT lanac: 24 h 31.220 (kupnje 17.400, SOL 100 %; prodaje 13.820, SOL 0 %) · praćeni: 420 kupnji, 310 prodaja (SOL 0 %) · najglasniji novčanik 4.110 · spool 0
    DATAAUDIT novcanici: 61.300 (ocijenjeno 9.800, danas 212) · dokazani 14 od 96 (stari 3 h, povijest medijan 19 h) · wallet_trades +18.400/dan
    DATAAUDIT autopilot: praćenja 9 (4 kol, 3 novč., 2 ekipe) · 24 h 31 signal: 3 ulaza, 28 preskočeno (prekasno 11) · kašnjenje medijan 14 s · pravi: 1 live, 2 dry
    DATAAUDIT rast/dan: hype.db +41 MB (live_trades +22) · kol.db +6 · wallets.db +3 · zastarjelo: masovno 7 h

(Brojke u primjeru su izmišljene radi oblika.)

**Metrike i SQL.** Režim L = i u lakom prolazu (indeks ili tablica < 25 MB), N = samo noću pod `ops.heavy`.
Parametri: `:d1` = sada − 24 h, `:d2` = − 48 h, `:d14`, `:d30`; `:prati` = aktivna praćenja novčanika (l1) + dokazani (w5).

| # | baza | metrika | SQL | cijena | režim |
|---|---|---|---|---|---|
| h1 | hype | zadnji sken | `SELECT MAX(ts) FROM hype_signals` | cover indeks, O(log n) | L |
| h2 | hype | skenova i tokena 24 h | `SELECT COUNT(*), COUNT(DISTINCT token) FROM hype_signals INDEXED BY hype_signals_cover WHERE ts >= :d1` | samo indeks, 1 dan | L |
| h3 | hype | tokena ≥ 30k u 24 h | `SELECT COUNT(DISTINCT token) FROM hype_signals INDEXED BY hype_signals_cover WHERE ts >= :d1 AND mcap >= 30000` | samo indeks | L |
| h4 | hype | redaka starijih od 14 d (kandidat za prorjeđivanje) | `SELECT COUNT(*) FROM hype_signals INDEXED BY hype_signals_cover WHERE ts < :d14` | samo indeks | N |
| h5, h6 | hype | najstariji i najnoviji swap | `SELECT MIN(ts) FROM chain_trades` ; `SELECT MAX(ts) FROM chain_trades` | O(log n) | L |
| h7 | hype | swapova po danu, 14 d | `SELECT ts / 86400 AS d, COUNT(*) FROM chain_trades INDEXED BY chain_trades_ts WHERE ts >= :d14 GROUP BY d` | samo indeks | N |
| h8 | hype | udio kupnji/prodaja sa SOL iznosom, 24 h | `SELECT side, COUNT(*), SUM(sol IS NOT NULL AND sol > 0), COUNT(DISTINCT wallet) FROM chain_trades INDEXED BY chain_trades_ts WHERE ts >= :d1 GROUP BY side` | raspon 1 dan + redci | L |
| h9 | hype | isto samo za praćene i dokazane | `... WHERE ts >= :d1 AND wallet IN (:prati) GROUP BY side` | isto | L |
| h10 | hype | 5 najglasnijih novčanika 24 h (bot u webhooku?) | `SELECT wallet, COUNT(*) n FROM chain_trades INDEXED BY chain_trades_ts WHERE ts >= :d1 GROUP BY wallet ORDER BY n DESC LIMIT 5` | isto | L |
| h11 | hype | stanje živog toka | `SELECT key, value FROM live_state WHERE key IN ('last_trade_ts','trades_day','subscribed','counts')` | PK | L |
| h12, h13 | hype | najstariji redak i približan broj redaka live_trades | `SELECT ts FROM live_trades ORDER BY rowid LIMIT 1` ; `SELECT (SELECT MAX(rowid) FROM live_trades) - (SELECT MIN(rowid) FROM live_trades) + 1` | prvi redak; O(log n) | L |
| h14, h15 | hype | X webhook objava 24 h; zadnja | `SELECT COUNT(*) FROM kol_mentions WHERE ts >= :d1` ; `SELECT MAX(ts) FROM kol_mentions` | indeks | L |
| h16 | hype | zadnji puls | `SELECT MAX(ts) FROM token_pulse` | indeks | L |
| h17 | hype | tokeni bez para (status) | `SELECT COUNT(*), SUM(COALESCE(has_pair, 1) = 0), MAX(checked_ts) FROM token_status` | mala tablica | L |
| h18 | hype | rugova arhivirano 24 h | `SELECT COUNT(*) FROM rug_archive WHERE archived_ts >= :d1` | indeks | L |
| h19 | hype | tokena ukupno i novih 24 h | `SELECT COUNT(*), SUM(first_ts >= :d1) FROM token_tier` | mala tablica | L |
| h20 | hype | zadnja snimka cijene | `SELECT ts FROM hype_snapshots ORDER BY rowid DESC LIMIT 1` | zadnji redak | L |
| h21 | hype | dnevnik prijedloga 7 d | `SELECT razina, COUNT(*), SUM(hit), SUM(stop_first) FROM prijedlog_log WHERE ts >= :d7 AND labelled_ts IS NOT NULL GROUP BY razina` | mala tablica | L |
| k1 | kol | zadnji poziv | `SELECT MAX(ts) FROM calls` | indeks | L |
| k2 | kol | novi redci 24 h po vrsti i izvoru | `SELECT kind, source, COUNT(*) FROM calls INDEXED BY calls_ts WHERE ts >= :d1 GROUP BY kind, source` | raspon 1 dan | L |
| k3 | kol | pozivi 24–48 h: s ishodom, po izvoru mjere, loši, bez mcapa, zatvoreni bez ishoda | `SELECT COUNT(*), SUM(p0 IS NOT NULL), SUM(r1h IS NOT NULL), SUM(msrc = 'gecko'), SUM(msrc = 'dex'), SUM(bad IS NOT NULL), SUM(p0 IS NOT NULL AND mcap0 IS NULL), SUM(complete = 1 AND p0 IS NULL) FROM calls INDEXED BY calls_ts WHERE ts >= :d2 AND ts < :d1 AND kind = 'call'` | raspon 1 dan | L |
| k4 + m5 | kol + minute | udio poziva starih 2–26 h s minutnom stazom (spajanje u Pythonu) | `SELECT tweet_id, token, handle FROM calls INDEXED BY calls_ts WHERE ts >= :h26 AND ts < :h2 AND kind = 'call' AND handle NOT LIKE 'w:%'` ; `SELECT tweet_id, token, entry IS NOT NULL AND bad IS NULL FROM call_path WHERE ts >= :h26` | raspon 1 dan; mala tablica | L |
| k5 | kol | računi: ukupno, TG, botovi, ocijenjeni, zadnje bodovanje | `SELECT COUNT(*), SUM(handle LIKE 'tg:%'), SUM(COALESCE(bot, 0)), SUM(score IS NOT NULL), MAX(updated) FROM kols` | mala tablica | L |
| k6 | kol | tokeni bez para / bez supplyja / odustali | `SELECT COUNT(*), SUM(pair IS NULL), SUM(pair IS NOT NULL AND supply IS NULL), SUM(pair IS NULL AND tries >= 3) FROM tokens` | mala tablica | L |
| k7 | kol | isto, samo tokeni pozvani u 24 h | `SELECT COUNT(DISTINCT c.token), COUNT(DISTINCT CASE WHEN t.pair IS NULL THEN c.token END), COUNT(DISTINCT CASE WHEN t.pair IS NOT NULL AND t.supply IS NULL THEN c.token END) FROM calls c INDEXED BY calls_ts LEFT JOIN tokens t ON t.token = c.token WHERE c.ts >= :d1 AND c.kind = 'call'` | raspon 1 dan | L |
| k8 | kol | zadnja snimka | `SELECT ts FROM snaps ORDER BY rowid DESC LIMIT 1` | zadnji redak | L |
| k9 | kol | oznake poslova (ocjena, webhook lista) | `SELECT key, value FROM kv WHERE key IN ('score_mark','chain_hook','slow_ts','validate_ts')` | PK | L |
| k10 | kol | ekipe | `SELECT COUNT(*), MAX(start_ts) FROM groups` | mala tablica | L |
| k11 | kol | 30 dana po vrsti (nazivnik pokrivenosti) | `SELECT kind, COUNT(*), SUM(complete), SUM(p0 IS NOT NULL), SUM(bad IS NOT NULL) FROM calls INDEXED BY calls_ts WHERE ts >= :d30 GROUP BY kind` | velik raspon tablice od 130 MB | N |
| m1 | minute | staze: ukupno, čiste, bez svijeće, < 30k, bez poola, mcap nepoznat, raspon, zadnje mjerenje, danas, prosječni lag | `SELECT COUNT(*), SUM(entry IS NOT NULL AND bad IS NULL), SUM(bad = 'svijeca'), SUM(bad = 'mcap'), SUM(bad = 'pool'), SUM(entry IS NOT NULL AND bad IS NULL AND mcap_e IS NULL), MIN(ts), MAX(ts), MAX(measured_ts), SUM(measured_ts >= :d1), AVG(lag_s) FROM call_path` | mala tablica | L |
| m2 | minute | razine: ukupno i neuspjele | `SELECT COUNT(*), SUM(lv = 'x') FROM call_lv` | mala tablica | L |
| m3 | minute | raspodjela izmjerenih poziva po računu (košare 1, 2–4, 5–9, 10+) | `SELECT handle, COUNT(DISTINCT token) FROM call_path WHERE entry IS NOT NULL AND bad IS NULL GROUP BY handle` | mala tablica | L |
| m4 | minute | zaostatak i vruća lista | `SELECT key, value FROM kv WHERE key IN ('minute_stats','hot_list')` | PK | L |
| w1 | wallets | registar: ukupno, ocijenjeni, ocijenjeni danas, zadnje bodovanje, na čekanju | `SELECT COUNT(*), SUM(scored_at IS NOT NULL), SUM(scored_at >= :d1), MAX(scored_at), SUM(next_check IS NOT NULL AND next_check <= :now) FROM wallets` | mala tablica (< 24 MB) | L |
| w2 | wallets | po tieru | `SELECT tier, COUNT(*) FROM wallets WHERE scored_at IS NOT NULL GROUP BY tier` | mala tablica | L |
| w3 | wallets | povijesnih tradeova ikad (razlika = novi danas) | `SELECT MAX(rowid) FROM wallet_trades` | O(log n) | L |
| w4, w5 | wallets | dokazani: zadnji prolaz, ocijenjeno i prošlo | `SELECT MAX(as_of) FROM dokazani` ; `SELECT COUNT(*), SUM(passed) FROM dokazani WHERE as_of = :zadnji` | indeks | L |
| w6 | wallets | starost povijesti dokazanih | `SELECT d.wallet, w.scored_at, w.last_tx_ts FROM dokazani d JOIN wallets w ON w.wallet = d.wallet WHERE d.as_of = :zadnji AND d.passed = 1` | indeks + PK | L |
| w7 | wallets | Helius krediti ovaj mjesec po metodi | `SELECT method, SUM(credits) FROM helius_credits WHERE ts >= :mjesec GROUP BY method` | mala tablica | L |
| p1, p2 | paper | zadnji tick; demo tradeovi | `SELECT ts FROM ticks ORDER BY rowid DESC LIMIT 1` ; `SELECT status, COUNT(*), SUM(pnl_usd) FROM trades GROUP BY status` | zadnji redak; mala | L |
| t1 | tg | kanali po statusu | `SELECT status, COUNT(*) FROM channels GROUP BY status` | samo indeks | L |
| t2 | tg | objave 24 h, s CA, zadnja | `SELECT COUNT(*), SUM(cas != ''), MAX(seen_ts) FROM posts INDEXED BY posts_seen WHERE seen_ts >= :d1` | raspon 1 dan | L |
| t3 | tg | kašnjenje viđenja (medijan, p90 u Pythonu) | `SELECT seen_ts - ts FROM posts INDEXED BY posts_seen WHERE seen_ts >= :d1 AND cas != '' AND ts > 0 AND source = 'web'` | raspon 1 dan | L |
| s1 | shadow | točke po statusu | `SELECT status, COUNT(*), MIN(ts), MAX(ts) FROM points GROUP BY status` | samo indeks (status,ts) | L |
| s2 | shadow | zadnji prolaz masovne knjige | `SELECT k, v FROM kv WHERE k = 'masovno_last'` | PK | L |
| s3 | shadow | oznake 24 h po izvoru (udio `bez_cijene`, B2, B24) | `SELECT point, status, COUNT(*) FROM points WHERE labeled_ts >= :d1 GROUP BY point, status` | cijela tablica 78 MB | N |
| s4 | shadow | masovne točke stare 1–3 dana po statusu, za svaki izvor (kol_poziv, novcanik_kupio, bondao, trending, kontrola): koliko je `gotovo`, a koliko `bez_cijene` (B24) | `SELECT status, COUNT(*) FROM points INDEXED BY points_point WHERE point = :izvor AND ts >= :d3 AND ts < :d1 GROUP BY status` | raspon indeksa (point,ts) | L |
| a1–a3 | ai | zadnja oznaka, oznaka 24 h, serije po statusu | `SELECT MAX(ts) FROM posts_ai` ; `SELECT COUNT(*) FROM posts_ai WHERE ts >= :d1` ; `SELECT status, COUNT(*) FROM batches GROUP BY status` | indeks; mala | L |
| l1 | league | aktivna praćenja po vrsti | `SELECT kind, COUNT(*) FROM follows WHERE active = 1 GROUP BY kind` | indeks | L |
| l2 | league | odluke kopiranja 24 h: ulazi, preskočeno, kašnjenje | `SELECT side, action, ts - ev_ts, note FROM copy_log WHERE ts >= :d1` | indeks | L |
| l3 | league | dokaz u demu po praćenju | `SELECT follow_id, COUNT(*), SUM(pnl_usd > 0), SUM(pnl_usd) FROM trades WHERE follow_id IS NOT NULL AND status != 'open' GROUP BY follow_id` | mala tablica | L |
| r1, r2 | trade | pozicije po načinu i statusu; nalozi 24 h | `SELECT mode, status, COUNT(*) FROM positions GROUP BY mode, status` ; `SELECT side, status, COUNT(*) FROM orders WHERE ts >= :d1 GROUP BY side, status` | male tablice | L |
| u1 | usage | pozivi, greške i potrošnja po servisu 24 h (ostaje u logu i JSON-u, ne ide na javnu stranicu) | `SELECT service, SUM(calls), SUM(errors), SUM(amount) FROM usage WHERE hour >= :sat24 GROUP BY service` | PK raspon | L |
| x1, x2 | strat | strategije po statusu; kašnjenje kopija dokazanih (JSON `state.kopija`) | `SELECT strat, status, COUNT(*) FROM positions GROUP BY strat, status` ; `SELECT state FROM positions WHERE strat = 'dokazani' AND status IN ('open','closed') AND entry_ts >= :d7` | indeks | L |
| d1, d2 | dugo | tokeni i zadnje svijeće; zadnji dan snimke | `SELECT COUNT(*), MAX(candles_ts) FROM tokens` ; `SELECT MAX(day) FROM snap` | mala; indeks | L |
| f1 | datoteke | veličina svake baze + WAL, slobodan disk | `os.path.getsize`, `ops.disk.free_mb()` | – | L |
| f2 | datoteke | webhook payloadi na čekanju | broj datoteka u `chain_spool` (kol/chainwatch.py:267-270) | – | L |
| f3 | sve | 12 najvećih tablica i indeksa po bazi | `ops.dbs.table_sizes(path, top=12)` (dbstat; satni posao već radi top 4) | čita cijelu datoteku | N |
| f4 | env | način rada čišćenja | `ops.prune.on()` | – | L |

**Upozorenja (zastavice u JSON-u i u zadnjoj liniji).** Zastarjelo: najnoviji zapis stariji od 3× kadence posla (sken
2 min, tick 1 min, KOL krug 20 min, snimke 20 min, TG 30 s, masovno 30 min, ocjene i bodovanje 1 dan, dugo 1 dan).
Ostalo: prodaje sa SOL < 50 % (h8, h9); pokrivenost minutnom < 60 % (k4+m5) ili zaostatak raste dva dana zaredom (m4);
`bez_cijene` > 30 % masovnih točaka starih 1–3 dana (s4, s3); pozvani tokeni bez para > 30 % (k7); čiste staze s nepoznatim mcapom > 5 %
(m1); dokazanih 0 ili vruća lista prazna (w5, m4); spool > 0 (f2); slobodan disk < 1 GB ili tablica raste > 50 MB/dan (f1,
f3); čišćenje nije uključeno (f4); bilo koji upit "prekinuto".

## 4. Dnevno osvježavanje u 02:00 i brojači "novo danas"

**Redoslijed je bitan.** U 02:00 noćni poslovi tek rade: prozor počinje u 01:00, teški poslovi idu jedan po jedan
(ops/heavy.py:1-10), ocjenjivanje KOL-ova traje 40+ min (run_kol.py:258-261), učenje je u 03:30 CET
(learn/config.json:17), izlazi u 04:30 CET (exits/config.json:4). Prijedlog: u 02:00 posao uzme snimku brojača i
objavi dnevnik za dan koji je završio; tablice ponovno složi kad vidi oznake da je noćni posao gotov (`kv score_mark.ts`
u kol.db, `MAX(scored_at)` u wallets.db, `MAX(day)` u dugo.db snap), najkasnije u 05:45. Što stigne nakon 02:00 ulazi u
sutrašnji dnevnik (razlika snimke prema snimci), pa se ništa ne broji dvaput.

| javna stranica | izvor | danas se osvježava | u 02:00 |
|---|---|---|---|
| /influencers, /influencer/x (ui/public.py:261-290, 490-560) | kol.db `kols.score`, `kols.stats`, `calls` | ocjene 1× noću; HTML keš 15 min (public.py:26) | složiti nakon `score_mark`; spremiti popis računa na ljestvici (za "novi") |
| /telegram-channels, /telegram/x (ui/telegrampub.py:107-121) | kol.db pozivi `tg:`, tg.db channels | isto | isto, popis kanala |
| /solana-meme-coins, /coin/x (ui/coins.py, ui/public.py:972-1135) | public.db coins i coin_hist; dugo.db svijeće i holderi; kol.db pozivi | Jupiter svaka 3 h u UI niti; dugo 1× noću | jedan prisilni prolaz + red u coin_hist; složiti nakon `run_dugo` |
| naslovnica, brojke (ui/landing.py:61-103) | hype, wallets, kol, tg, dugo, paper | svakih 30 min, dva puna čitanja `calls` (B17) | računati jednom; naslovnica čita gotov JSON |
| "sati trgovanja", tržište (ui/marketpub.py:113-245) | market.db daily; kol.db token_hours i agregat calls | najviše svakih 30 min pri posjetu | računati jednom (token_hours se ionako puni noću) |
| blogovi s podatkovnim blokovima (ui/blog*.py, ui/blogposts_*.py) | tekst s brojkama "kopija 8.11." (ui/blogposts_hr_seo.py:40) | ručno | blokove puniti iz istog JSON-a; "osvježen" samo kad se blok stvarno promijenio |
| sitemap (ui/public.py:718-779) | popisi gore | pri zahtjevu | `lastmod` = dan zadnje promjene tablice |
| Pregled "Rast baze" (interno, ui/pocetna.py:247-281) | kol, hype, tg | puna čitanja pri gradnji (B17) | čitati `dataaudit/latest.json` |

**Brojači za dnevnik "MemeSonar je live N dana"** (svi javno dopušteni: bez troškova, env imena i internih servisa):

| brojač | kako | cijena |
|---|---|---|
| novi influenceri na ljestvici (s poveznicama /influencer/x) | razlika skupova `public.influencers()` danas i jučer | iz već složene tablice |
| novi Telegram kanali na ljestvici | razlika skupova `telegrampub.rows()` | isto |
| novi pozivi izmjereni po minutama | `SELECT COUNT(*) FROM call_path WHERE measured_ts >= :t0 AND entry IS NOT NULL AND bad IS NULL` | mala tablica |
| pozivi kojima je istekla 24-satna mjera | `SELECT COUNT(*) FROM calls INDEXED BY calls_ts WHERE ts >= :t0 - 172800 AND ts < :t0 - 86400 AND kind = 'call' AND max24 IS NOT NULL` | raspon 1 dan |
| novi novčanici u registru / novo ocijenjeni | razlika `SELECT COUNT(*) FROM wallets` ; `SELECT COUNT(*) FROM wallets WHERE scored_at >= :t0` | mala tablica |
| novi dokazani novčanici | razlika skupova `wallets.dokazani.current()` | indeks |
| novi povijesni tradeovi | razlika `SELECT MAX(rowid) FROM wallet_trades` (nakon B12: razlika broja iz `.rows.json`) | O(log n) |
| kupnje i prodaje praćenih novčanika u danu | `SELECT COUNT(*) FROM chain_trades WHERE ts >= :t0` | samo indeks |
| novi tokeni analizirani / rugovi arhivirani | `SELECT COUNT(*) FROM token_tier WHERE first_ts >= :t0` ; `SELECT COUNT(*) FROM rug_archive WHERE archived_ts >= :t0` | mala; indeks |
| novi coini na javnoj listi (s poveznicama /coin/x) | razlika skupova `SELECT slug FROM coins WHERE rank IS NOT NULL` | mala tablica |
| Autopilot jučer (ulazi, izlazi, zatvoreni tradeovi) | `trade.aplog.summary` iz dizajn.md §1; do tada l2 i r2 | indeks |

`first_seen` se ne koristi za "novo danas" (B22). Mjesto zapisa: JSON datoteke `output/sitelog/YYYY-MM-DD.json` ili
vlastita baza; pravilo "jedan pisac po SQLite datoteci" (kol/store.py:3-4) govori protiv upisa u public.db iz posla
izvan UI procesa. Svaka nova `.db` mora u popis u start.sh:9, inače nestane pri deployu (minute.db je tako 9.11.
izgubio 1.265 izmjerenih poziva, kol/minute.py:74-77).

## 5. Pohrana: što se može obrisati ili sažeti

| stavka | dokaz da se ne čita / da je višak | ušteda | trud · rizik |
|---|---|---|---|
| `wallet_trades`: autoindeks PK + `trades_wallet` (B12) | nijedan upit po `sig`; mjereno na kopiji −55 % | ~320 MB | M · srednji |
| `ticks`: autoindeks PK (B13) | svi upiti `token=? AND ts...`; mjereno −43 % | ~70 MB | S–M · srednji |
| `live_trades`: 48 h → 30 h | najdulji pogled unatrag 26 h (kol/crew.py:13-14, sada ugašen), inače ≤ 24 h (live/pulse.py:118); promijeniti natpis "zadnjih 48 h" (ui/pocetna.py:272) | (P) ~70 MB; 0 ako je PumpPortal tok ugašen | S · nizak |
| ai.db: `batches.ids` gotovih serija, `posts_ai` i `post_tokens` > 45 d (B16) | čita se samo `status='poslano'`; značajke gledaju 6 h prije točke mlađe od 33 d | (P) 30–50 MB | S · nizak |
| `chain_trades`: bez promjene sheme | WITHOUT ROWID ne pomaže (kopija: 75 → 70 MB jer indeks po ts tada nosi cijeli ključ). Od 8.11. bot novčanici su izvan webhooka (chainwatch.py:50-58: 15 novčanika = 57 % događaja), pa se tablica sama prazni do 22.11.; indeks od 150 MB je napuhan (na kopiji je 2/3 tablice) | (P) 100–150 MB do 22.11.; mjeriti h7 | – |
| `hype_details` srednji redci (B16) | čitaju se prvi i zadnji red te zadnji sati | (P) nepoznato, izmjeriti f3 | S · nizak |
| `hype_signals` stariji od 14 d: jedan red na sat | srednji redci već nemaju features/weights (dbs.py:69-97); čitači: grafovi i prvi/zadnji red | (P) nepoznato, izmjeriti h4 | M · srednji (grafovi povijesti grublji) |
| `kol_mentions`, `tg_mentions` > 30 d (B11) | čitači gledaju sate do 30 dana (dugo/sources.py:168) | malo | S · nizak |
| NE dirati: `posts` s CA | tg/history.py:45 koristi `MIN(post)` po kanalu kao kursor povijesti | – | – |

Zbroj: sigurno ~390 MB, vjerojatno još 150–250 MB (P). Nove tablice iz §2 (wallet_path, 4 stupca u snaps, seen_ts,
call_path 120 d) koštaju procijenjenih 30–80 MB (P): izmjeriti u prvom tjednu preko f3.

## 6. Nije provjereno (treba produkcija)

- Stvarni broj redaka i rast po danu (posebno live_trades 194 MB uz retenciju 48 h i strop 20.000 tradeova/dan,
  live/pumpportal.py:29: ili je strop u env-u viši, ili prevladavaju tradeovi novčanika; h12/h13 to pokažu).
- Koliko je točaka masovne knjige otpisano kao `bez_cijene` (B24 od 5.11., B2 od 9.11.) i koliko traje jedan minutni prolaz (B18).
- Polja Helius payloada za SOL primljen pri prodaji i GeckoTerminal polja za supply (B1b, B7a).
- Je li `DATA_PRUNE=on` postavljen na Renderu (B21) i veličine tablica izvan 4 najveće po bazi (hype_details,
  indeksi hype_signals, kol_mentions, rug.db).
- Sve uštede u §5 osim dviju mjerenih na sintetičkoj kopiji.
