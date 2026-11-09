# Handoff iz grupe "novac" (9.11.2026) – promjene koje trebaju datoteke izvan mog vlasništva

Što sam napravio u svojim datotekama (za kontekst): league/copy.py (vrata MC≥30k, samo bondani, liq/MC ≥ 3 %,
koncentracija samo na POZNATO lošem podatku, ekipa ts = najnoviji član, zadani SL −20 %, TP/SL od entry_eff, fallback na
Smart sell, Zagreb dan, tekst runupa), league/auto.py (set_auto from_eff, copy prije auto-sella, oba u vlastitom try),
run_trade.py (svježina od poziva preko copy_log.ev_ts, zadnja obrana entry_mcap<30k, live-only vrata "dokaz u demu"
run_trade.PROOF, SIGTERM handler, tp_pct iz demo auto pravila), trade/executor.py (sell intent 'pending' prije swapa +
reconcile prodaja, pending buy nosi namjeru u sol_in, sell_check 429/4xx = "nema odgovora", vrata trošak-vs-TP, dry
procijenjene naknade), trade/config.json (napomena da "mode" ništa ne radi; mode ostaje dry).

## P26 – DexScreener TTL za TP/SL izlaze (league/auto.run_once, league/copy.market) – NISAM mijenjao izvor podataka
- league/auto.py:204 `mk = market(...)` – `market` dolazi iz run_ui.py:1134 (ui.paper.market → dexscreener/client.tokens, ttl = CACHE_TTL 60 s).
- Kad grupa "zivo"/"izvori" doda funkciju s kratkim TTL-om (2–5 s) u dexscreener/client.py, u run_ui.py:1134 proslijediti
  auto.loop-u market funkciju koja za pozicije računa LEAGUE_USER koristi taj TTL; isto i league/copy.market (:309) i ui/paper.market.
- Napomena iz verifikatora: "DexScreener batch keš 1 s" u DNEVNIK.md:23 nije točan opis (stvarno 60 s); ui/pravitrade.py:774 `_live_cached(ttl=1)` ide na isti 60-s keš.

## P27 – copy.wake() iz X/TG čitača (kol/xhook.py, tg/store.py)
- kol/xhook.py:151-180 `ingest()`: nakon `collect.save` kad je n > 0 pozvati `league.copy.wake()` (docstring copy.py:50-53 to obećava).
- tg/store.py:64-86 `save_posts`: pozvati `league.copy.wake()` kad post ima CA i kanal je u `league.copy.followed_handles()`
  (ne za svih ~1000 kanala, inače se auto.loop budi stalno).
- Test: po uzoru na tests/test_focus_offline.py:112-143 (CopyWake); u testu mockati WAKE put (copy.WAKE) da ne piše u root repoa.
- U league/auto.loop copy.run_once sad ide PRVI u ticku i u vlastitom try (gotovo).

## P11 – start.sh trap
- start.sh:35 `keep()` nema trap: dodati `trap 'kill -TERM $pid; wait $pid' TERM` oko `keep trade python3 run_trade.py follow` (:146),
  da deploy proslijedi SIGTERM; run_trade.cmd_follow sad ima handler koji završi tekući prolaz i izađe (run_trade._on_term).

## P34 – ui/autopilot.py wallet_stats: preživjeli uzorak (tokeni koje wallet još drži ne ulaze u ROI)
- ui/autopilot.py:143-150: u `score` dodati kaznu za udio neprodanih (bought−closed)/bought ili vrednovati držane tokene po
  živoj cijeni (wallets/prices.py); u `_wallet_why` (:160) ispisati "još drži N". NE brojati neprodano ≥24 h kao −100 % (verifikator: kažnjava držanje dobitnika).
- Pogođen test: tests/test_pravitrade_offline.py:355-367 (`test_wallet_window_stats`, roi 0.75) – datoteka je u mom vlasništvu; kad promijenite
  autopilot.py, javite koja je nova očekivana vrijednost ili promijenite asertaciju uz note (ja je nisam dirao jer kod nije promijenjen).

## P37 – README.md:333 krivo: live NE traži "mode": "live" u configu
- Ispraviti na: pravi swap traži prekidač na /pravi-trade (settings "on", zadano off) + env TRADE_LIVE=1 + ključ; polje "mode" u
  trade/config.json je napomena (komentar "_mode" dodan). Uz to run_trade sada pušta pravi novac samo praćenju s dokazom u demu
  (run_trade.PROOF: ≥10 zatvorenih, PnL > 0, ≥40 % dobitnih; ručne kupnje izuzete).
- README.md:331 "max_signal_age_s (stari signal se ne kupuje)": sad je točno mjereno od poziva (copy_log.ev_ts), fallback demo ulaz.

## P39 – ui/pravitrade.py _follows (:321-335): prikaz dokaza po praćenju
- Uz "{n} ulaza" prikazati zatvorenih / dobitnih / PnL iz copy.follow_results i oznaku "pravi novac: da/ne (treba 10+ zatvorenih, PnL>0, 40 %+ dobitnih)"
  – isti pragovi kao run_trade.PROOF, da Jure vidi zašto je LIVE kupnja "blocked: praćenje bez dokaza u demu".

## P41 – ui/pravitrade.py token_popup (:929-932)
- Dodati red "likvidnost X % MC-a" s istim pragom kao league/copy.CFG["min_liq_mcap"] (3 %), da pop-up i automatski ulaz kažu isto.

## P61 – hype/sources.py:181 ingest_kol_event: ts primitka umjesto ts objave
- Izračunati ts iz payloada (collect.hook_post / snowflake_ts iz URL-a, kao kol/collect.from_webhook :273-291) i upisati ga u kol_mentions.ts;
  vrijeme primitka držati zasebno. league/copy.events (:259-261) uzima kol_mentions.ts kao ts poziva (max_delay, _runup grana, log "nakon poziva").
- Test: tests/test_hype_sources_offline.py:37-40 (nema URL, ostaje), tests/test_copy_offline.py:44-58 pišu kol_mentions ručno (moje, prolaze).

## P65 – topcheck/safety.judge na light izvještaju bez holdera vraća 'prolazi'
- topcheck/safety.py:158-159 (holderi=None ne ulazi u warns) i :210-217 ('prolazi' kad nema warns): bez podatka o holderima verdikt bi
  trebao biti 'nepoznato' (ili 'oprez'), ne 'prolazi'; ui/zivo.py:79 i ui/autopilot.py:260 to čitaju kao "rug check prošao".
  Pogođeni testovi: test_topcheck_offline.py:119,170,200, test_zivo_offline.py:23, test_autopilot_zovu_offline.py.
- Vrata koncentracije na putu pravog novca su u league/copy._concentration (čita topcheck.store.read_all i ui.data.rug_latest,
  blokira samo na top10 > TOP10_FAIL, klaster/bundle/insajderi iznad rugfilter.score hard pragova, dev > DEV_FAIL, verdikt 'pao';
  bez podatka = "koncentracija: nepoznato" u logu ulaza). Ako topcheck počne spremati `top1`, dodati ga tamo.

## P40 – Jupiter keyless limit (ops)
- sell_check sad 429/4xx tretira kao "nema odgovora → ne kupujem naslijepo". Da se to rjeđe događa, u Renderu postaviti besplatni Jupiter API ključ
  (trade/jupiter.py čita ga iz env-a); nije promjena koda.

## Pregled (review novac) – odluka za Juru: izvori bez praćenja uživo bez dokaza u demu
- run_trade.follow_league_once: demo kupnje bez follow_id koje NISU kopije (league/simianx_feed.py izvor 'simianx', ručne demo
  kupnje 'ručno (pravi trade)' s lige) i dalje idu uživo bez vrata PROOF (postojeće ponašanje, ne nova rupa). Kopija ("copy ...")
  bez follow_id sad nikad ne prolazi kao ručna. Treba odluka: prag PROOF po izvoru (npr. simianx mora imati ≥10 zatvorenih demo
  ulaza) ili ostaju iznimka kao "Kupi ručno". Nije mijenjano bez odluke (promjena bi blokirala ručne kupnje sa stranice).
