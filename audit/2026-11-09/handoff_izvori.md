# Handoff – grupa "izvori" (audit 9.11.2026)

Promjene izvan mojeg vlasništva koje treba napraviti da popravci budu potpuni. Sve je testirano offline u
tests/test_audit_20261109_izvori_offline.py; ništa dolje ne ruši postojeće testove ako se NE napravi (sve je opcionalno
dodatno poboljšanje), ali bez toga nalazi ostaju djelomično otvoreni.

## P2 – DexScreener živi TTL (dexscreener/client.py: NOVA funkcija `tokens_live(chain, mints, ttl=None)`, LIVE_TTL = 3 s, env DEX_LIVE_TTL, min 2 s)
Potpis `client.tokens(chain, addresses)` je nepromijenjen (testovi ga patchaju 2-arg lambdom); `tokens_live` dijeli isti
request path i rate limiter (_FAST), samo s kraćim diskovnim kešom. Pozivači koje treba prebaciti na `client.tokens_live`:
- ui/prijedlog.py:96  `pairs = (fetch or (lambda t: client.tokens("solana", t)))(tokens)`  → `client.tokens_live("solana", t)`
  (live_market: Zovu sada / Što kupiti sada / pop-up / gumb Kupi)
- ui/paper.py:35      `pairs = client.tokens("solana", list(mints))` → `client.tokens_live(...)`  (market: demo TP/SL auto-sell, league/auto petlja 20 s)
- league/copy.py:330  `pairs = client.tokens("solana", list(tokens))` → `client.tokens_live(...)`  (copy.market)
- DNEVNIK.md:23 tvrdi "DexScreener batch keš 1 s" → ispraviti na "živi keš 3 s (DEX_LIVE_TTL), skeneri 60 s".
Skeneri (run_top, hype, run_kol) ostaju na `tokens` (60 s). Ne stavljati 1 s: limit 300/min je po IP-u i dijele ga svi procesi.

## P3 – X webhook na zaključanom kol.db (kol/xhook.py)
`xhook.ingest` sada na sqlite3.OperationalError spoola payload u `<realpath dir kol.db>/xhook_spool/*.json` i vraća 0
(dakle run_ui `_x_hook` šalje 200, ne 400). `xhook.drain()` se zove iz `run_kol.py cmd_collect`. 
run_ui.py: NIJE potrebna promjena. Opcionalno (brže punjenje bez čekanja KOL kruga): u league/auto.loop ili run_ui auto-sell
petlji svakih 20 s pozvati `from kol import xhook; xhook.drain(log=lambda *a, **k: None)` u try/except (kol.db je tad slobodan
ili i dalje zaključan – drain tada ostavlja datoteke).

## P21 – Helius webhook na zaključanom hype.db (kol/chainwatch.py)
`chainwatch.ingest` sada spoola u `<realpath dir hype.db>/chain_spool/` i vraća broj redaka (run_ui šalje 200), timeout
handlera 10 s umjesto 60 s; retencijski DELETE najviše jednom na sat (PRUNE_EVERY_S); `chainwatch.drain()` se zove pri idućem
uspješnom ingestu i iz run_kol collect. Ostaje za ops/dbs.py (nije moje): u `hourly()` compact() za hype.db (1,4 GB) dopustiti
samo kad nema pisaca (startup, offline=True), ne online dok UI/sken/run_tg pišu – ili barem preskočiti datoteke koje drže
drugi procesi (ops/dblock.holders). run_ui.py `_chain_hook` bez promjene.

## P29/P36 – topcheck verdikt (topcheck/safety.py, run_top.py)
- judge: holderi nepoznati → status "warn" ("nema podatka o holderima: koncentracija nepoznata") pa verdikt 'oprez', ne 'prolazi'.
- judge: puni rug filter OPREZ → "warn" s prvom zastavicom; VISOK RIZIK s prvom zastavicom; top10 iz rug.db kad RugCheck nema.
- run_top.latest_full/full_check vraćaju `data` = {hard_fails, flags, score, holders.top10_pct, launch.bundle_pct/sniper_pct, cluster.holding_pct}.
Posljedica za UI (nije moje, provjeriti tekst): ui/zivo.py:79, ui/autopilot.py:261-272, ui/pravitrade.py:915 pišu "rug check
prošao" samo za verdict=='prolazi' – to sad stvarno znači da su i holderi provjereni. Tokeni s light RugCheck izvještajem
(bez holdera) sad padaju u 'oprez' i ispadaju iz "Što kupiti sada"/moonshot liste; pop-up bi uz 'oprez' trebao prikazati
checks['holderi'][1] (tekst s "nepoznato"), ne "NE KUPUJ" bez razloga.

## P35 – praćeni TG kanal koji nije u tg.db (tg/poll.py)
due() sad čita praćene kanale bez obzira na status i upisuje nepoznate kao kandidate (found_via 'follow'). Opcionalno za
league/copy.py:114 follow(): kad je target 'tg:<ime>', odmah pozvati `tg.store.add_candidates(con_tg, [ime], "follow")`
da kanal uđe u tg.db i prije prvog poll tick-a (sad ulazi na prvom due(), tj. unutar 3 s).

## P55 – dokazani novčanici (wallets/dokazani.py)
copyable() sad odbija bag_share >= 0.3 (RULE.max_bag_share; isti prag kao pnl.score). latest() redci nose `bags` i `bag_share`.
ui/pravitrade.py:466 _dokazani_items (nije moje): prikazati `r.get("bags")` npr. "· {bags} bagova" uz hold/tpd, da Jure vidi
koliko kupljenih tokena novčanik nije zatvorio.

## P56 – holderi/bundle/snajperi bez pump.fun Apify-a (NOVI topcheck/holders.py)
`topcheck.holders.pumpfun_shape(mints, tc=None, rug=None)` → mint -> {top10HoldersPercent, bundlerOwnedPercent,
snipersOwnedPercent, devHoldingsPercent, insidersPercent, izvor} iz topcheck rc_json (top10 bez poolova, dev_pct, insiders)
i rug.db rug_reports (bundle_pct, sniper_pct, top10_pct). Nepoznato ostaje None (nikad 0). Pozivač (nije moje):
run_hype.py:287-290 – kad je `pf` prazan: `extra["pumpfun"] = holders.pumpfun_shape([t]).get(t)` (ili jednom za sve tokene
prije petlje: `hs = holders.pumpfun_shape(tokens)`), i/ili ui/overview.token_rows. ui/evidence.py:92-93 tekst "nema pump.fun
podataka" → "nema podatka o holderima" kad je i to None. ui/confidence.py:39-49 i ui/radar.py:66-73 rade bez promjene jer čitaju
iste ključeve; `_pct(None)` mora ostati 0-tolerantan (provjeriti da None ne daje "holders_ok": u confidence.py uvjet
`top10 < 35 and bund < 15` s None→0 bi dao +6 – zato prije poziva preskočiti ključeve koji su None ili promijeniti uvjet).

## Nepogođeno / napomena
- hype/sources.ingest_kol_event: ts = vrijeme objave (snowflake iz status linka), inače vrijeme primitka; novi opcionalni
  parametar `now`. run_ui.py:877 poziv bez promjene.
- Sve nove tablice/kv: minute.db kv 'minute_retry' (P24), call_path bad='pool' (P24) – ui/coverage ne broji 'pool' zasebno
  (ui nije moje; po želji dodati SUM(bad='pool') u kol/minute.coverage – to je moje, javite ako treba).

## Recenzija (adversarial review, izvori) – popravljeno u vlasništvu grupe
- run_kol.py:37 `con.commit()` prije `xhook.drain()`: drain otvara vlastitu konekciju, a `collect.from_webhook` (kols UPSERT
  piše uvijek) je držao write lock → drain bi čekao 60 s i spool se nikad ne bi praznio (P3). Test: XHookSpool.test_collect_drains_although_its_own_connection_wrote_first.
- tg/poll.py due(): praćeni kanal sa statusom 'dead' i fails >= max_fails (tipfeler, privatni) čita se svakih poll_active_s, ne 2 s
  zauvijek (t.me IP i 429 backoff su zajednički). Prvi uspješan visit() ga vraća u 2-s skup.
- kol/xhook.py + kol/chainwatch.py spool(): ime datoteke s os.urandom tailom (dvije niti u istoj ms više ne prepisuju jedna drugu).
- kol/chainwatch.py: drain() dobiva `timeout`; drain iz webhook niti čeka 10 s, ne 60.
## Recenzija – izvan vlasništva (napomene)
- .copy_wake (tracked u gitu iako je u .gitignore) je prljav u radnom stablu. Orkestrator: ne komitati; dugoročno
  `git rm --cached .copy_wake` (pitati Juru). Moduli koji pišu pravi copy.WAKE (izmjereno po modulu, mtime prije/poslije):
  tests/test_xhook_offline.py (moje – popravljeno: setUpModule patcha copy.WAKE u temp dir),
  tests/test_hype_sources_offline.py (nije moje; piše ga preko hype/sources.ingest_kol_event → league/copy.wake, P25),
  tests/test_live_offline.py, tests/test_pravitrade_offline.py, tests/test_register_offline.py (nisu moji; preko live/store.py:61
  _copy.wake(), postojeće prije audita). Popravak za svaki: u modulu
  `_WAKE = mock.patch.object(copy, "WAKE", os.path.join(tempfile.mkdtemp(), ".copy_wake"))` + setUpModule/tearDownModule start/stop
  (kao u tests/test_xhook_offline.py), ili centralno u league/copy.wake: preskočiti pisanje kad je env MEMESONAR_TEST=1.
- kol/chainwatch.ingest: payload bez swapova sad zove ensure_tables() (jednom po procesu, timeout 1 s, zaključan hype.db se preskače),
  pa svježa instalacija dobiva chain_trades/chain_transfers i prije prvog pravog swapa (recenzentska napomena, popravljeno).
- ui/pravitrade.py:930: 'oprez' sad obuhvaća i "holderi nepoznati" → pop-up kaže "NE KUPUJ" i skriva gumb Kupi za tokene s light
  RugCheck izvještajem; treba prikazati checks['holderi'][1] ("koncentracija nepoznata") kao razlog, kako je već u P36 handoffu.
