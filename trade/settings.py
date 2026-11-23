"""Settings of the real-money trader that the owner changes on the page /pravi-trade, kept in trade.db (on the
persistent disk, so a redeploy keeps them). trade/config.json holds the defaults.

Who may change them: TRADE_OWNER (Render env, default "Jure", Nicholas's account). Other players see the page only
when the owner invites them, and only to look.
"""
import json
import os
import sqlite3
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("TRADE_DB", os.path.join(HERE, "trade.db"))
LEAGUE_USER = "pravi-trade"   # the competition account whose follows (KOL/wallet) drive the real trades
# 10.11. (Jure: "default stop loss treba biti na minus 60 %, a to moram na stranici Autopilota moći promijeniti"): the
# stop of every Autopilot entry with "moj TP/SL" and no stop of its own (copies, auto picks, crews, manual buys), in
# percent below the entry; the owner picks one of SL_CHOICES under "Pravila". Players keep league/copy.DEFAULT_SL.
SL_DEFAULT = 60
SL_CHOICES = (20, 30, 40, 50, 60, 70)

# 10.11. (Jure, "Specifikacija za Claudea", Phase 0): every new rule of the profitability plan ships behind a flag.
#   off     the rule does nothing (default; behaviour exactly as before)
#   shadow  the new decision is computed and logged (league.db shadow_decisions), nothing changes
#   paper   the new rule runs on the demo account PAPER_USER, which copies LEAGUE_USER's follows; run_trade.py never
#           mirrors PAPER_USER, so no real money moves
#   live    the rule runs on LEAGUE_USER (real money through run_trade). Allowed only with a passed backtest
#           (settings "backtest:<flag>" = {"pass": true, ...} from run_backtest.py) after PAPER_DAYS in paper with
#           the paper account in the plus (live_refusal)
# Data flags (DATA_FLAGS) only switch a collector or an MCP inbox on: any mode but off means "on".
PAPER_USER = "autopilot-paper"
FLAG_MODES = ("off", "shadow", "paper", "live")
PAPER_DAYS = 7
FLAGS = {   # name -> (item of the plan, what it does, in Croatian for the page)
    "caller_ev_rank": ("2.1", "Calleri po donjoj granici EV-a, samo iz poziva prije signala"),
    "runup_default": ("2.3", "Preskok kad je cijena više od 10 % iznad prvog poziva"),
    "x_features_ingest": ("3.6", "X značajke od Groka (MCP upis)"),
    "grok_predictions": ("3d", "Grok predviđanja (nepromjenjiva) za usporedbu s MemeSonarom"),
    # 19.11. (vlasnik: "Ukloniti dvadesetak prekidača koji ništa ne rade? Da."): removed 26 flags no code read (plan 1.1,
    # 1.2, 1.4, 2.2, 2.4-2.8, 3.1-3.4, 3b.1-3b.2, 3c, 3d.4, 4.1-4.4, 3e.1, 3e.2, 3e.4 x2, 3e.5): auto_exit_data,
    # sl_default_v2, dca_guard, latency_entry, holder_hard, proof_v2, survivor_fix, zombie_guard, organic_volume,
    # xhook_fast, helius_streams, holder_snap, clusters_ext, junk_skip, junk_flags, event_flags, grok_features_fit,
    # regime_sizing, time_filter, caller_decay, ladder_exit, early_score, early_persist, wallet_stream, sender_exec,
    # demo_grok. A row "flag:<name>" of one of them in trade.db is simply not listed any more (flag_state iterates
    # FLAGS) and never read. Back: git (this commit).
    # 10.11. (addendum, Phase 3e)
    "smart_discovery": ("3e.3", "Otkrivanje novčanika koji rano ulaze u pobjednike"),
    # 10.11. (Grok MCP audit 4): a proven caller's copy is not stopped out in the first minutes (league/auto.grace)
    "stop_grace": ("G4", "Prve 3 min bez stopa za dokazane callere (osim kod ruga)"),
    # 10.11. (Jure: "Primijeni" na Grokov prijedlog mijenja ove postavke, svaku iza zastavice, prvo sjena)
    "caller_weights": ("G6", "Težine callera iz prijedloga u automatskom izboru influencera"),
    "dca_cap": ("G7", "Najviše SOL-a ukupno po tokenu (zadano 0,3)"),
    "require_signal": ("G8", "Bez ulaza bez signala: barem jedan caller ili kupnja novčanika s tierom"),
    # 10.11. ~21:00 (Grok, "Prihvaćeno, ali nije primijenjeno", Jure: "Primijeni ovo"): TP +10 % / stop -20 % pays only
    # at ~73 % hits and the best callers have 50-60 %, so an entry needs 2+ callers AND a tiered wallet's buy
    "confluence": ("G9", "Ulaz tek kad se poklope 2+ callera i kupnja novčanika s tierom"),
    # 10.11. ~21:45 (Jure): the MCP client's exit plan per position, executed by the server (league/exitplan.py)
    "exit_plans": ("G10", "Planovi izlaza s MCP-a (set_exit_plan): TP-ovi, trailing, stop, time stop"),
    # 10.11. (Jure: skener tržišta bez callera, scan/): never buys; shadow = measured per source, paper only through
    # paper_refusal (>= 30 shadow outcomes and EV > 0 of the scanner's own sources)
    "market_scan": ("G11", "Skener tržišta bez callera (final stretch, migrirani, beta mete, rani X), mjeri u sjeni"),
    # 10.11. (Jure, kol/groupdisc.py): caller crews and hidden wallet lists; in paper only past PAPER_GATES
    "group_discovery": ("G12", "Ekipe callera i skriveni popisi novčanika: ekipa unutar 10 min = jedan signal, "
                               "ekipa izlazne likvidnosti negativno"),
    # 10.11. (Jure, range_dca): range + DCA on bonded tokens (rangedca/); live only after >= 20 paper rounds, trade/edge live proof
    "range_dca": ("G13", "Raspon + DCA: ulaz na dnu raspona, lot 2 na -10 do -15 %, pola van u gornjoj zoni"),
    # 10.11. (Jure, kol/precall.py): wallets that buy before the callers' calls; copied only in paper, live only past
    # live_refusal + LIVE_GATES
    "insider_copy": ("G14", "Insajderi prije poziva: novčanici koji kupuju prije poziva callera, kopiranje u demo"),
    # 11.11. (Jure, kol/preshill.py): wallets that buy before the paid shill network calls; shadow only, never buys
    "pre_shill": ("G15", "Kupci prije shill mreže: novčanici koji kupe prije plaćene mreže callera, poziv mreže je "
                         "znak za izlaz"),
    # 11.11. (Jure, momentum/): the +20-30 % jumps without callers; paper on the demo account, live only past
    # LIVE_GATES (>= 50 paper trades, the trade/edge live proof: EV >= +3 % and its 90 % interval above 0)
    "momentum_scalp": ("G16", "Momentum scalp: ulaz na početku skoka (+5 do +15 % u 5 min, volumen 3x, kupci rastu), "
                              "pola van na +15 %, ostatak trailing 8 %, stop -10 %, 45 min"),
    # 11.11. (Jure, momentum/evgate.py): Grok's autotrade buy only with EV = p x TP - (1 - p) x SL - cost > 0
    "grok_ev_gate": ("G17", "Grokova vrata po EV-u: kupnja samo kad je p(TP prije SL-a) x TP - (1 - p) x SL - trošak "
                            "iznad nule"),
    # 11.11. (Jure: GTA's plan was only logged, the real exit went through the default TP): an owner switch, uživo =
    # Grok's exit plans run on the REAL account for Grok autotrade positions (league/exitplan.grok_live), whatever
    # exit_plans' mode; it only sells, never buys; default off, only the owner moves it. 11.11. (owner: "Plan izlaza uz
    # kupnju: DA"): also the plan a buy from the panel / Uredi SL-TP sets (league/exitplan.panel_live)
    "exit_plan_live": ("G18", "Planovi izlaza na pravom računu: plan uz kupnju iz panela (i spremljen SL/TP pozicije) "
                              "i Grokove autotrade pozicije (samo prodaja)"),
    # 11.11. evening (Jure: "Dok se ne preoznači ponovno, za blokiranje vrijedi stroža oznaka ... Nove oznake nemoj
    # koristiti dok ne prođe korak 3"): an owner switch (live = on, rugfilter/labels). Off (default): blocking takes
    # the STRICTER of the old and the new rug labels (a rug if any says rug), statistics keep the old labels. Live:
    # the SOL-side labels (rugfilter/collapse sol_v2) decide both. Only the owner moves it, after checking the relabel.
    "rug_labels_v2_ok": ("G28", "Nove rug oznake (SOL strana poola) u blokiranju i statistikama; isključeno = blok po "
                                "strožoj oznaci (stara ili nova), statistike po starim oznakama"),
    # 11.11. (Jure: "ništa se stvarno ne briše bez moje potvrde nakon što vidim brojke"): owner switches of the data
    # retention (ops/retencija.py). Off (default): only the measurement in the log (after a deploy and daily at 06:30,
    # what WOULD go and how many MB); live: the deletion, only 01-06 Zagreb under the heavy-job lock.
    "live_trades_retention": ("G29", "Retencija živog toka (hype.db live_trades): sirovi PumpPortal tradeovi drugih "
                                     "tradera stariji od 48 h brišu se noću, nakon satnog agregata; nikad naši "
                                     "swapovi, praćeni i ocjenjivani novčanici ni redovi koje treba čitač s duljim "
                                     "prozorom; isključeno = samo mjerenje u logu"),
    "tg_text_retention": ("G30", "Tekst Telegram objava starijih od 14 dana briše se noću (red i metapodaci ostaju) "
                                 "kad je svaki poziv objave potpuno izmjeren ili objava nije dala poziv; isključeno = "
                                 "samo mjerenje u logu"),
    # 11.11. (Jure: "event tokeni s Grokom", topics/): Grok's event topics, their matching tokens (main / clone / rug),
    # the price 24 h before / at / after the event; shadow = measure only, paper = range_dca may trade them on the demo
    # account; never real money (NEVER_LIVE)
    "event_tokens": ("G19", "Event tokeni: teme događaja od Groka (npr. GTA6), tokeni koji im odgovaraju (glavni, klon, "
                            "rug) i cijena 24 h prije, u trenutku i 24 h nakon događaja"),
    # 11.11. (Jure: "širi range watchlist", rangedca/market.py): up to 400 bonded tokens of the whole market in the range
    # watchlist (5 / 15-min DexScreener snapshots inside daily caps); shadow = data, paper = range_dca may trade them on
    # the demo account; never real money (NEVER_LIVE)
    "range_market": ("G20", "Range lista cijelog tržišta: do 400 bondanih tokena (MC 30k-5M, likvidnost 15k+, volumen "
                            "1 h 5k+, stariji od 6 h; 14.11. i PumpSwap poolovi, CTO liste, pozivi 7 dana, bivši rasponi), "
                            "snimke svakih 5/15 min unutar dnevnih stropova"),
    # 11.11. (Jure, proposals/): one list of proposals from every strategy on the Autopilot card and in get_proposals;
    # shadow = list and measure, paper = the demo account takes a proposal in its entry zone; never live (LIVE_GATES)
    "proposals": ("G21", "Prijedlozi svih strategija na Autopilotu: sjena = popis i mjerenje, paper = demo račun uzima "
                         "svaki prikazani prijedlog s planom izlaza; pravi račun kupuje samo na tvoj dodir"),
    # 19.11. (vlasnik, zatvoreno kao napušteno): market-maker scalp, the team catalyst watcher (team_catalyst, G22) and
    # the stake by token tier (G23) are closed as abandoned ideas; none of them has a flag here (G22 / G23 stay
    # reserved numbers); the blog from the research is dropped. Code that runs today (zonewatch, the catalyst
    # proposal rows, tiers/) is not removed by this note.
    # 11.11. (Jure: "real-time zone alarm na Grok Bot", zonewatch/): a data flag (DATA_FLAGS): off = nothing watched or
    # posted; any other mode = the zones are watched and every alarm is POSTed to the Grok Bot webhook (when its env
    # is set). It never trades.
    "zonewatch": ("G25", "Zonski alarmi Grok Botu: ulaz cijene u zonu (dno, DCA, vrh, stop) raspona i ručno postavljenih "
                         "zona, POST na webhook u stvarnom vremenu"),
    # 11.11. (Jure, fast/): every signal of a followed wallet / influencer gets five checks at once (rug, holders,
    # flow, price vs the wallet's entry, source) and a decision with its number; shadow = decide and log, paper = the
    # demo account trades BUY_PAPER and BUY_LIVE with the fast exit plan; live only past LIVE_GATES (G22, G23 reserved)
    "fast_path": ("G24", "Brzi put: svaki signal praćenog novčanika ili influencera odmah dobije rug, holdere, tok, "
                         "cijenu prema ulazu novčanika i zapis izvora (< 10 s); paper = demo račun kupuje, pola van na "
                         "+15 %, trailing 8 %, stop -10 %, 45 min, izlaz kad izvor proda"),
    # 11.11. (Jure: "rangedca flip / pauza / stop", rangedca/detect.flip_step): off = today's range rules; shadow =
    # compute the flip / pause state and the volatility stop, log what would differ; paper = range_dca's demo account
    # trades the new rules; live only past LIVE_GATES (the nightly backtest: new max drawdown <= today's)
    "range_flip": ("G26", "Raspon flip / pauza / ATR stop: potvrđen proboj gore (zatvaranje + volumen) čini stari vrh "
                          "kandidatom za novo dno (ulaz tek nakon 2 retesta), proboj dolje = pauza sa starim dnom kao "
                          "otporom, stop range_low_low - 1,5 × ATR (5-20 %) umjesto × 0,85"),
    # 11.11. (Jure: "propušteni tokeni u range praćenje", rangedca/missed.py): every token a skip journal labels
    # propušteno (skipped, then >= +20 % within 60 min) is on the range watchlist as source missed for 72 h, behind the
    # owner's hard blocks and volume 1 h >= $10k; shadow = data, paper = range_dca trades it on the demo account by the
    # range rules; live only past LIVE_GATES (>= 20 closed demo rounds of source missed, trade/edge live proof)
    "range_missed": ("G27", "Propušteni tokeni na range listi: preskočen pa +20 % u 60 min = 72 h praćenja (filteri: "
                            "rug, honeypot/freeze, dev dump, MC 30k+, likvidnost 15k+, volumen 1 h 10k+), ulaz samo po "
                            "rasponu; live tek nakon 20 rundi izvora missed s EV > 0"),
    # 12.11. (Jure, nalog točka 2, fast/xscalp.py): every token Grok sends with the MCP tool submit_watch_token that
    # passes the hard blocks gets a VIRTUAL paper entry at the market cap of the detection; measured net of cost (max
    # gain before -8 %, +15 min, +1 h, the dev / top holder dump) per author class. shadow and paper do the same (no
    # account buys, not even the demo one: submit_watch_token never trades); never live (NEVER_LIVE). Default shadow
    # (FLAG_DEFAULTS): it only measures.
    "x_call_scalp": ("G31", "X call scalp: token koji Grok pošalje (submit_watch_token) i prođe tvrde blokove (rug, "
                            "honeypot, likvidnost 15k+, MC 30k+, bondan) dobiva papirnati ulaz na MC u trenutku "
                            "detekcije; mjeri se max dobit prije −8 %, +15 min i +1 h neto nakon troška i dump deva / "
                            "top holdera, po razredu autora (followeri × brzina); nijedan račun ne kupuje"),
    # 14.11. (Jure: "želim da danas otvoriš barem 5 tradeova ... u donjem dijelu range-a ... nemoj stavljati preblizu
    # stop loss ... da se uzima barem 10-15% profita"; rangedca/rules.DEMO): paper = range_dca's DEMO account trades the
    # demo profile (entry score 0.6, bottom 25 %, no crashed token; TP +10 % / +15 % net, ATR stop held at -12..-25 %);
    # off = the demo account trades RULES like the real one. Never live (NEVER_LIVE); default paper (FLAG_DEFAULTS).
    "range_demo": ("G32", "Range demo (14.11. popodne, scalp): demo račun ulazi s 60 % uloga u donjoj polovici raspona ili do "
                          "10 % iznad donje zone (15.11.: ocjena 0,5+, pad 5 min do −8 %, volumen 15 min 20 %+; pravi "
                          "račun ostaje na 0,6+ / −5 % / 35 %; 10 tokena s najviše volumena), DCA 40 % na −10 %, pola van "
                          "na +0,60 $ neto od prosječnog ulaza, ostatak na +15 % / gornjoj zoni, stop ATR −17 do −25 % od "
                          "lota 1, nikad token koji je u 24 h pao više od 45 %; do 10 rundi po tokenu dnevno; cilj 100 "
                          "tradeova dnevno"),
}
# 12.11. (owner: "zadano shadow ili paper"): a flag's mode while the owner has never set it; every other flag is off
FLAG_DEFAULTS = {"x_call_scalp": "shadow"}
FLAG_DEFAULTS["range_demo"] = "paper"   # 14.11. (owner's order): the demo account trades the demo profile from the deploy
# 14.11.: a profile flag changes HOW a strategy already in paper trades on the demo account; its paper mode never makes
# the paper account follow anybody (any_paper leaves it out)
PROFILE_FLAGS = frozenset({"range_demo"})
# 11.11.: flags that never go live, whatever the proofs say (their tokens are traded at most on the demo account)
NEVER_LIVE = {"event_tokens": "event tokeni nikad ne trguju pravim novcem (najviše paper na demo računu)",
              "range_market": "tržišna range lista nikad ne trguje pravim novcem (najviše paper na demo računu)",
              "x_call_scalp": "x_call_scalp nikad ne trguje pravim novcem (samo papirnati ulazi, bez računa)",
              "range_demo": "demo pravila range-a (14.11.) nikad ne trguju pravim novcem (samo demo račun)"}
# 11.11.: owner switches: "live" means on, without a backtest or paper days (live_refusal lets them through); they
# never move on their own, only the owner's tap on the page sets them
OWNER_SWITCHES = frozenset({"exit_plan_live", "rug_labels_v2_ok", "live_trades_retention", "tg_text_retention"})
# what "uživo" does, per owner switch (the page /pravi-trade; one without a note gets the exit-plan text)
OWNER_SWITCH_NOTES = {
    "rug_labels_v2_ok": "Tvoj prekidač: „uživo” uključuje nove rug oznake (bez backtesta); svaki drugi mod ostavlja "
                        "stroži blok i stare oznake u statistikama.",
    "live_trades_retention": "Tvoj prekidač: „uživo” uključuje brisanje (noću 01-06, nakon satnog agregata); svaki drugi "
                             "mod samo mjeri i piše u log što bi se obrisalo i koliko MB.",
    "tg_text_retention": "Tvoj prekidač: „uživo” uključuje brisanje teksta (noću 01-06, red objave ostaje); svaki drugi "
                         "mod samo mjeri i piše u log što bi se obrisalo i koliko MB.",
}
# 14.11. (owner: "Ja sada ne govorim o demu ... nema više demo ... idemo s pravim novcem"): ONE owner switch, "uživo" =
# on, default off, only his tap on /pravi-trade (set_flag refuses anybody else). On: every automatic strategy whose
# flag is paper or live trades the REAL account (LEAGUE_USER) without the demo proofs, within trade/executor's
# SWITCH_CAPS; x_call_scalp (no account) and Grok autotrade (its own switch) stay out. Off: exactly as before.
SWITCH_ALL = "pravi_novac_sve"
# Range part (rangedca/trade.profile, scalp_live): the real account trades range_dca's scalp profile (rules.SCALP: lot 1
# 60 % + DCA 40 % at -10 %, the whole position out at a fixed net USD target after the real costs, the focus list of
# 10 tokens, up to 10 rounds a token a day); its exits run as exit plans on the real account (league/exitplan.scalp_live)
FLAGS[SWITCH_ALL] = ("P14", "Pravi novac za sve strategije (vlasnik 14.11.): svaka automatska strategija u paper ili "
                            "live modu kupuje pravim novcem, bez dokaza u demu, unutar stropova (0,1 SOL po tradeu, "
                            "10 otvorenih, 100 kupnji dnevno, dnevni gubitak 0,5 SOL); range trguje scalp (lot 1 60 % "
                            "+ DCA 40 % na −10 %, cijela pozicija van na neto cilju u $, 10 tokena, do 10 rundi dnevno)")
OWNER_SWITCHES = OWNER_SWITCHES | {SWITCH_ALL}
OWNER_SWITCH_NOTES[SWITCH_ALL] = ("Tvoj prekidač: „uživo” = sve strategije trguju pravim novcem (i one s negativnim "
                                  "izmjerenim EV-om); svaki drugi mod = kao prije, pravi novac samo s dokazom u demu.")


# 14.11. navečer (owner: "Zaprati sve influencere koji su u zadnjih 5 poziva imali barem 10% profita ... vidi na volete
# isto ... izlazi na 10% profita"; kol/zadnjih5.py): an owner switch, "uživo" = the Autopilot account follows every
# influencer and wallet whose last 5 measured calls / buys reached +10 % (strict 5/5), exit tp 10% and the default stop,
# refreshed after a start and nightly. Default off. On top of it the runner itself turns ONE type on (settings
# zadnjih5_auto) only while that type's walk-forward is in the plus after the real costs on 30+ trades.
ZADNJIH5 = "prati_zadnjih5"
FLAGS[ZADNJIH5] = ("P15", "Zadnjih 5: prati influencere i novčanike čijih je zadnjih 5 poziva / kupnji doseglo +10 %, "
                          "ulaz na svaki njihov sljedeći, izlaz na +10 % uz zadani stop; bez prekidača runner sam "
                          "uključuje vrstu samo kad je njen walk-forward nakon troškova u plusu na 30+ tradeova")
OWNER_SWITCHES = OWNER_SWITCHES | {ZADNJIH5}
OWNER_SWITCH_NOTES[ZADNJIH5] = ("Tvoj prekidač: „uživo” = Autopilot prati sve izvore koji trenutno prolaze pravilo "
                                "zadnjih 5 (influenceri i novčanici, najviše 50 po vrsti), izlaz +10 % i zadani stop; "
                                "svaki drugi mod = runner prati samo vrstu kojoj je izmjereni EV nakon troškova > 0 "
                                "na 30+ tradeova (log „zadnjih 5: odluka”).")


# 15.11. (vlasnik: "OpenAI kao kritičar algoritma ... otvorenih tradeova, analiza"; critic/): an owner switch, "uživo" =
# on and its DEFAULT (FLAG_DEFAULTS), any other mode = off. ADVICE ONLY: the critic never places, changes or closes a
# trade and never changes a setting; it writes notes. Without OPENAI_API_KEY it does nothing (one log line an hour).
KRITICAR = "openai_kritika"
FLAGS[KRITICAR] = ("P16", "Kritičar (OpenAI): savjeti za otvorene pozicije (drži, prodaj, prodaj dio, stegni / proširi SL) "
                          "i dnevna revizija algoritma kao skeptični data scientist; samo bilješke, nikad ne trguje ni "
                          "ne mijenja postavke; dnevni i mjesečni strop troška")
FLAG_DEFAULTS[KRITICAR] = "live"
OWNER_SWITCHES = OWNER_SWITCHES | {KRITICAR}
OWNER_SWITCH_NOTES[KRITICAR] = ("Tvoj prekidač: „uživo” (zadano) = kritičar radi (treba OPENAI_API_KEY; strop troška "
                                "OPENAI_DAY_USD dnevno, OPENAI_MONTH_USD mjesečno); svaki drugi mod = kritičar ne zove "
                                "OpenAI. Samo savjeti: ništa ne kupuje, ne prodaje i ne mijenja.")


# 15.11. (vlasnik: "Isključi pravi novac zasad, ali hitno pronađi profitabilnu strategiju kombiniranjem profitabilnih
# novčanika i influencera ... analizu tokena isključi za pravi novac, pozadinu ostavi za demo"; konsenzus/): the source
# consensus strategy. FLAG "konsenzus": paper = the DEMO account PAPER_USER enters whenever the currently best candidate
# of konsenzus/research fires (league/auto.loop -> konsenzus/live); shadow = only the research runs; never live by this
# flag (NEVER_LIVE): real money goes only through the owner switch below.
KONSENZUS = "konsenzus"
FLAGS[KONSENZUS] = ("P17", "Konsenzus izvora: najbolji kandidat iz walk-forwarda influencera, Telegram kanala i novčanika "
                           "(top izvori, 2+ neovisna izvora, novčanik + KOL) ulazi na demo računu čim se pojavi signal")
NEVER_LIVE[KONSENZUS] = "konsenzus sam nikad ne trguje pravim novcem: pravi novac samo kroz prekidač pravi_novac_izvori"
# its paper mode does not make the paper account follow anybody (it enters by itself)
PROFILE_FLAGS = PROFILE_FLAGS | {KONSENZUS}
# The owner switch: "uživo" = the konsenzus signals ALSO buy on the real account, but only while the best candidate's
# holdout passes konsenzus/gate.PROOF (n >= 30, EV >= +3 %, the 90 % interval's low > 0); caps trade/executor.
# IZVORI_CAPS. Default off; only the owner's own tap (set_flag refuses anybody else and every code order).
IZVORI = "pravi_novac_izvori"
FLAGS[IZVORI] = ("P18", "Pravi novac za konsenzus izvora: signal najboljeg kandidata kupuje i pravim novcem, samo dok "
                        "njegov holdout prolazi dokaz (n 30+, EV +3 %+, donja granica 90 % intervala > 0); 0,1 SOL po "
                        "tradeu, najviše 5 otvorenih, 30 kupnji dnevno, dnevni gubitak 0,3 SOL")
OWNER_SWITCHES = OWNER_SWITCHES | {IZVORI}
OWNER_SWITCH_NOTES[IZVORI] = ("Tvoj prekidač: „uživo” = signali konsenzusa izvora kupuju i pravim novcem, ali samo dok "
                              "najbolji kandidat ima dokaz na holdoutu (n 30+, EV +3 %+, donja granica 90 % intervala "
                              "> 0); stropovi 0,1 SOL po tradeu, 5 otvorenih, 30 kupnji dnevno, dnevni gubitak 0,3 SOL; "
                              "tvrda pravila (kill switch, rug arhiva, MC 30k+, bondani, likvidnost 15k+, trošak do 6 %, "
                              "jedna pozicija po tokenu, stop na serveru) uvijek. Svaki drugi mod = samo demo.")


# 15.11. (vlasnik: "Zašto ne bismo pronašli token za koji znamo da ide gore-dolje tijekom dana i tradali ga 50 puta
# dnevno, uzimajući 1-2 $ na svakom (s naknadama)? ... 10 takvih tokena"; oscilator/): FLAG "oscilator": paper = the
# DEMO account PAPER_USER scalps today's top 10 oscillating tokens (oscilator/walk ranks them by day D's swings net of
# the cost; oscilator/rule: the lower quarter of the last hour's range + the momentum turn, out at +1 $ net of the real
# cost, stop -8 %, 60 min), 0.5 SOL a trade (OSC_DEMO_SOL), 10 open, 300 a day; never live by this flag (NEVER_LIVE).
OSCILATOR = "oscilator"
FLAGS[OSCILATOR] = ("P19", "Oscilator: demo račun skalpira 10 tokena koji su jučer najviše oscilirali (swingovi veći od "
                           "troška + 1 $ neto, malo trenda); ulaz u donjoj četvrtini raspona zadnjeg sata kad cijena "
                           "okrene gore, izlaz na +1 $ neto nakon pravog troška, stop −8 %, 60 min; 0,5 SOL, najviše 10 "
                           "otvorenih, 300 ulaza dnevno")
NEVER_LIVE[OSCILATOR] = "oscilator sam nikad ne trguje pravim novcem: pravi novac samo kroz prekidač pravi_novac_oscilator"
PROFILE_FLAGS = PROFILE_FLAGS | {OSCILATOR}   # its paper mode never makes the paper account follow anybody
# The owner switch (15.11., real money NOT now): "uživo" = the oscillator's entries ALSO buy on the real account, but
# only while oscilator/gate.real_refusal() is None: the walk-forward proof at 0.1 SOL (n >= 100, EV > 0, the 90 %
# interval's low > 0, $ a day > 0) AND the demo's own >= 50 closed trades with EV > 0; caps oscilator/gate.REAL (0.1
# SOL, 3 open, 30 a day, a day's loss 0.3 SOL). Default off; only the owner's own tap (set_flag), never an order.
OSC_SWITCH = "pravi_novac_oscilator"
FLAGS[OSC_SWITCH] = ("P20", "Pravi novac za oscilator: ulazi oscilatora kupuju i pravim novcem, samo dok walk-forward na "
                            "0,1 SOL ima dokaz (n 100+, EV i donja granica 90 % intervala > 0, $/dan > 0) i demo 50+ "
                            "zatvorenih s EV > 0; 0,1 SOL po tradeu, najviše 3 otvorena, 30 dnevno, dnevni gubitak 0,3 SOL")
OWNER_SWITCHES = OWNER_SWITCHES | {OSC_SWITCH}
OWNER_SWITCH_NOTES[OSC_SWITCH] = ("Tvoj prekidač: „uživo” = ulazi oscilatora kupuju i pravim novcem, ali samo dok "
                                  "walk-forward na 0,1 SOL ima dokaz (n 100+, EV > 0, donja granica 90 % intervala > 0, "
                                  "$/dan > 0) i demo ima 50+ zatvorenih s EV > 0 nakon pravog troška; stropovi 0,1 SOL, "
                                  "3 otvorena, 30 dnevno, dnevni gubitak 0,3 SOL. Svaki drugi mod = samo demo.")


# 15.11. (vlasnik: "Od sada nema smisla, čak ni u demu, tradati ove mikrokapove tražeći 10 % ... moonshot samo ako vidimo
# ogromnu bazu na društvenim mrežama i puno influencera ... Inače sada tradamo samo mid-capove: 5M-150M $"; trade/capgate):
# an owner switch, "uživo" = on: every AUTOMATIC entry (demo and real) needs MC >= 5M (trade/config.json mikrokap
# min_mc), except the moonshot below; the owner's manual buy is never held by it. Switched on once by his order 15.11.
# (ui/assistnotes.OWNER_FLAG_ORDERS); any other mode = the old behaviour (MC >= 30k only).
MIKROKAP = "mikrokap_blokada"
FLAGS[MIKROKAP] = ("MK1", "Mikrokap blokada: automatski ulazi (demo i pravi račun) samo uz MC od 5M $ naviše; ispod toga "
                          "samo moonshot iznimka u demu (jaka društvena baza); tvoje ručne kupnje ne drži")
OWNER_SWITCHES = OWNER_SWITCHES | {MIKROKAP}
OWNER_SWITCH_NOTES[MIKROKAP] = ("Tvoj prekidač: „uživo” (uključeno tvojim nalogom 15.11.) = automatski ulazi svih strategija "
                                "samo uz MC ≥ 5M $, ispod toga samo moonshot iznimka u demu; pravi račun ispod 5M nikad "
                                "(tvrdo pravilo „MC ispod 5M (mikrokap)”). Svaki drugi mod = kao prije (samo MC ≥ 30k).")
# The moonshot exception of the gate (coordinator 15.11. after the OpenAI critic: demo only, locked rules, its own
# measured strategy): "paper" = the exception on the DEMO accounts (default, FLAG_DEFAULTS), "off" = no exception at
# all; never live (NEVER_LIVE): no switch or order ever lets a moonshot use real money.
MIKROKAP_MOON = "mikrokap_moonshot"
FLAGS[MIKROKAP_MOON] = ("MK2", "Moonshot iznimka mikrokap blokade, samo demo: MC 30k+ bondan, likvidnost 50k+, top10 holdera "
                               "do 45 %, 4+ neovisna influencera / TG kanala u 6 h (klasteri jednom, bez botova i shill "
                               "mreža), X momentum 1+ i organski autori u rastu; pola uloga, najviše 0,05 SOL, oznaka "
                               "moonshot")
FLAG_DEFAULTS[MIKROKAP_MOON] = "paper"
NEVER_LIVE[MIKROKAP_MOON] = "moonshot iznimka nikad ne trguje pravim novcem (samo demo računi)"
PROFILE_FLAGS = PROFILE_FLAGS | {MIKROKAP_MOON}   # its paper mode never makes the paper account follow anybody
OWNER_SWITCHES = OWNER_SWITCHES | {MIKROKAP_MOON}
OWNER_SWITCH_NOTES[MIKROKAP_MOON] = ("Tvoj prekidač: „paper” (zadano) = moonshot iznimka vrijedi na demo računima; "
                                     "„isključeno” = ispod 5M nema nikakve iznimke; „uživo” nije moguće (nikad pravi "
                                     "novac). Pravila su zaključana unaprijed (config.json ih smije samo pooštriti).")

# 15.11. (vlasnik: "Useless, Troll i slično: kad nađu dno, vrlo vjerojatno se odbiju gore i naprave 5-10 % ... hvataj
# range velikih tokena"; veliki/): FLAG "veliki_range": paper = the DEMO account PAPER_USER trades the list "veliki"
# (MC 20M+, liquidity 500k+, 14+ days, volume 500k+; USELESS, TROLL) with the range rule of veliki/rule (support from
# the last 3-7 days of 1h candles, the bounce on 15m, target / stop / time stop picked by the walk-forward, no entry
# while BTC crashes), 0.5 SOL a trade (VEL_DEMO_SOL), 8 open, 40 a day; never live by this flag (NEVER_LIVE).
VELIKI = "veliki_range"
FLAGS[VELIKI] = ("P21", "Veliki tokeni — range: demo račun trguje 15-20 velikih memecoina (MC 20M+, likvidnost 500k+, "
                        "USELESS, TROLL) na odbijanju od podrške raspona zadnjih 3-7 dana; cilj, stop i vremenski stop "
                        "iz walk-forwarda, bez ulaza dok BTC pada; 0,5 SOL, najviše 8 otvorenih, 40 ulaza dnevno")
NEVER_LIVE[VELIKI] = "veliki_range sam nikad ne trguje pravim novcem: pravi novac samo kroz prekidač pravi_novac_veliki"
PROFILE_FLAGS = PROFILE_FLAGS | {VELIKI}   # its paper mode never makes the paper account follow anybody
# The owner switch (15.11., real money NOT now): "uživo" = the big-token range entries ALSO buy on the real account, but
# only while veliki/gate.real_refusal() is None: the walk-forward holdout at the real size (n >= 40, EV > 0, the 90 %
# interval's low > 0; or, once the owner says so in trade/config.json, the demo's own record), BTC known and not
# crashing; caps veliki/gate.REAL (0.1 SOL, up to 0.5 by the owner; 5 open; a day's loss 0.3 SOL). Default off; only
# the owner's own tap (set_flag), never an order.
VEL_SWITCH = "pravi_novac_veliki"
FLAGS[VEL_SWITCH] = ("P22", "Pravi novac za velike tokene: ulazi range pravila velikih tokena kupuju i pravim novcem, samo "
                            "dok holdout walk-forwarda na 0,1 SOL ima dokaz (n 40+, EV i donja granica 90 % intervala > 0) "
                            "i BTC ne pada; 0,1 SOL po tradeu, najviše 5 otvorenih, dnevni gubitak 0,3 SOL")
OWNER_SWITCHES = OWNER_SWITCHES | {VEL_SWITCH}
OWNER_SWITCH_NOTES[VEL_SWITCH] = ("Tvoj prekidač: „uživo” = ulazi velikih tokena kupuju i pravim novcem, ali samo dok "
                                  "holdout walk-forwarda na 0,1 SOL ima dokaz (n 40+, EV > 0, donja granica 90 % intervala "
                                  "> 0 nakon pravog troška) i BTC ne pada; stropovi 0,1 SOL (do 0,5 u trade/config.json), "
                                  "5 otvorenih, dnevni gubitak 0,3 SOL; kill switch, rezerva walleta, arhiva rugova, jedna "
                                  "pozicija po tokenu, trošak do 6 % i stop na serveru uvijek. Svaki drugi mod = samo demo.")

# 15.11. navečer (vlasnik: "Ne želim više mikrokapove uopće: ni trgovanje, ni skeniranje, ni analiza ... sve resurse
# prebaci na midcapove, 2M do 200M, posebno TRENDING tokene na DexScreeneru"; ops/fokus.py): ONE owner switch, "uživo" =
# every recurring microcap job (scanner, launch pricing, insiders, crews, the hype scan and its learning, range_market,
# momentum, oscilator, konsenzus research, events backfill ...) stops or is pointed at the midcap list, and the midcap
# collector (veliki/midcap.py, MC 2M-200M) runs; any other mode = exactly the old behaviour. Switched on once by his
# order 15.11. (ui/assistnotes.OWNER_FLAG_ORDERS); one tap under Prekidači undoes it. Never trades by itself.
FOKUS = "fokus_midcap"
FLAGS[FOKUS] = ("MK3", "Fokus midcap: nikakvi resursi na mikrokapove (skener, nova lansiranja, insajderi, ekipe, hype "
                       "sken, range_market, momentum, oscilator, konsenzus, noćni backfill su ugašeni ili preusmjereni); "
                       "prikupljanje podataka o midcapovima 2M-200M (DexScreener trending, GeckoTerminal, Jupiter)")
OWNER_SWITCHES = OWNER_SWITCHES | {FOKUS}
OWNER_SWITCH_NOTES[FOKUS] = ("Tvoj prekidač: „uživo” (uključeno tvojim nalogom 15.11.) = poslovi za mikrokapove ne rade "
                             "ili rade samo na midcap listi (popis: python3 -m ops.fokus, output/midpivot.md), a "
                             "sakupljač midcapova 2M-200M radi svakih 90 s; otvorene pozicije, tvoje ručne kupnje, "
                             "veliki/, kritičar i sigurnosne provjere ostaju. Svaki drugi mod = sve kao prije.")

# 15.11. (vlasnik: "Makni mikrokapove i rugove i sve njihove povijesne podatke iz baze ... one koji su od početka
# zadržali volumen, njih zadrži"; then "Arhiviraj onda dok ima prostora na disku"; ops/arhiva.py): an owner switch,
# "uživo" = at night (01-06 Zagreb, under the heavy-job lock) the rows of microcap (last MC < 2M) and rugged / dead tokens
# move from the live databases into gzipped archive files on the data disk (archive/<db>/<table>_<date>.sqlite.gz,
# copied, verified, compressed, verified again, only then deleted; run_arhiva.py vrati puts them back); it stops when
# the disk is short. Any other mode = only the plan (output/arhiva_plan.md), nothing moves. Never trade.db, league.db,
# veliki / midcap / konsenzus / oscilator / izlazi, the rug archive list, open positions or the owner's own trades.
ARHIVA = "arhiva_mikrokapova"
FLAGS[ARHIVA] = ("A1", "Arhiva mikrokapova: noću (01-06) retci tokena s MC ispod 2M $ i rugova / mrtvih tokena sele iz "
                       "živih baza u komprimirane arhive na disku (kopija, provjera, gzip, provjera, tek onda brisanje); "
                       "staje kad ponestaje prostora; midcapovi, otvorene pozicije, tvoji tradeovi i popis rugova ostaju")
OWNER_SWITCHES = OWNER_SWITCHES | {ARHIVA}
OWNER_SWITCH_NOTES[ARHIVA] = ("Tvoj prekidač: „uživo” (uključeno tvojim nalogom 15.11.) = noću 01-06 retci mikrokapova "
                              "(zadnji MC < 2M $) i rugova sele u .gz arhive na disku (archive/), dok ima prostora; ništa "
                              "se ne uništava, python3 run_arhiva.py vrati <baza> <tablica> ih vraća. Svaki drugi mod = "
                              "samo plan u logu i output/arhiva_plan.md, ništa se ne seli.")


# 15.11. (vlasnik: "i dalje želim naći insajdere i botove koji kupuju prije poziva ... kako ih pratiti da budemo sigurno
# u plusu"; insajderi/): FLAG "insajderi2": paper = the DEMO account PAPER_USER enters when a CONFIRMED insider group
# (insajderi/score: bought before AND sold into the pump on 3+ tokens, out of sample) buys a token in real time (the
# Helius webhook), behind every hard rule and the 5M capgate; exit when the group sells, stop -25 %, 24 h. Never live
# by this flag (NEVER_LIVE) and no owner switch: real money is the owner's decision later, with the numbers.
INSAJDERI2 = "insajderi2"
FLAGS[INSAJDERI2] = ("P23", "Insajderi 2.0: demo račun ulazi kad potvrđena grupa insajdera (kupili prije poziva i prodali "
                            "u skok na 3+ tokena, potvrđeno na novijim danima) kupi token; samo bondani i MC ≥ 5M, izlaz "
                            "kad grupa proda, stop −25 %, 24 h; 0,1 SOL, najviše 5 otvorenih, 10 dnevno")
NEVER_LIVE[INSAJDERI2] = "insajderi2 nikad ne trguje pravim novcem (samo demo račun); vlasnik odlučuje kasnije s brojkama"
PROFILE_FLAGS = PROFILE_FLAGS | {INSAJDERI2}   # its paper mode never makes the paper account follow anybody

# 15.11. (vlasnik: "Slažem se s prijedlogom koraka za plan makroinfluencera s dopunama kritičara"; makroinf/): FLAG
# "makroinf_indeks": the consensus index of the most accurate macro influencers as a DEMO input of the midcap macro
# regime (veliki/makro.demo_regime): paper = the DEMO account takes no new midcap entry while the index (prospective,
# the most accurate accounts) is bearish beyond the walk-forward's threshold AND makroinf's input state is "aktivan"
# (quality check passed, enough accounts with a stance, no degradation of the incremental EV); shadow = only the line
# "bi blokirao"; the REAL account never reads it. Never live (NEVER_LIVE): real money only after the critic's proof.
MAKROINF = "makroinf_indeks"
FLAGS[MAKROINF] = ("MI1", "Makro influenceri: indeks najtočnijih makro računa kao DEMO ulaz makro režima midcapova; demo "
                          "ne ulazi dok je indeks medvjeđi ispod praga walk-forwarda i ulaz je aktivan (provjera prošla, "
                          "bez degradacije dodatnog EV-a); pravi račun ga nikad ne čita")
NEVER_LIVE[MAKROINF] = ("makroinf_indeks nikad ne trguje pravim novcem (samo DEMO ulaz), dok indeks ne dokaže dodatni EV "
                        "prema kritičarevom pragu")
PROFILE_FLAGS = PROFILE_FLAGS | {MAKROINF}   # its paper mode never makes the paper account follow anybody
# The owner switch of the PUBLIC pages (/macro-influencers, /hr/makro-influenceri, one page per account): publishing is
# "sending out", so default off (the routes answer 404 and nothing is in the sitemap) and only the owner turns it on
# ("uživo" = published): his own tap, or his own order in the chat applied once in his name (15.11.: "Možeš ti odmah
# objaviti te stranice javno ..."; ui/assistnotes.OWNER_FLAG_ORDERS). No other code path.
MAKROINF_JAVNO = "makroinf_javno"
FLAGS[MAKROINF_JAVNO] = ("MI2", "Javne stranice makro influencera (EN + HR): zbirne ocjene s intervalima, metodologija, "
                                "stav s odgodom 7 dana; isključeno = stranice ne postoje (404) i nisu u sitemapu")
OWNER_SWITCHES = OWNER_SWITCHES | {MAKROINF_JAVNO}
OWNER_SWITCH_NOTES[MAKROINF_JAVNO] = ("Tvoj prekidač: „uživo” = javne stranice /macro-influencers i /hr/makro-influenceri "
                                      "(i po jedna za svaki račun) postoje i ulaze u sitemap; svaki drugi mod = 404 i "
                                      "ništa u sitemapu. Uključuje samo vlasnik (objava je slanje van); uključen "
                                      "tvojim nalogom u chatu 15.11.")
PROFILE_FLAGS = PROFILE_FLAGS | {MAKROINF_JAVNO}

# 16.11. (vlasnik: "Kako naći njihove sekundarne wallete ... Mora postojati stavka 'insider wallet' i algoritam koji ih
# traži"; insajderi/kolwallets.py): FLAG "insajderi_kol": the LIVE MEASUREMENT of the influencers' probably linked
# wallets. shadow (the default) / paper = when a "potvrđen" wallet group of an influencer buys a token (the trades we
# already store), a "predpoziv" event is recorded and later settled: did he call it, the lead time, the price after the
# call, did the group sell after the post. off = nothing recorded. No account ever buys in any mode and it never goes
# live (NEVER_LIVE); the analysis itself (the owner's page) does not depend on the flag.
INSAJDERI_KOL = "insajderi_kol"
FLAGS[INSAJDERI_KOL] = ("P24", "Insajderski novčanici influencera: mjeri se kad vjerojatno povezani (potvrđeni) novčanik "
                               "influencera kupi token prije njegova poziva: je li ga poslije zvao, koliko ranije je "
                               "kupljeno i što je cijena napravila; samo mjerenje, nijedan račun ne kupuje")
FLAG_DEFAULTS[INSAJDERI_KOL] = "shadow"
NEVER_LIVE[INSAJDERI_KOL] = "insajderi_kol samo mjeri (nijedan račun ne kupuje); nikad ne trguje pravim novcem"
PROFILE_FLAGS = PROFILE_FLAGS | {INSAJDERI_KOL}   # its paper mode never makes the paper account follow anybody

# 16.11. (vlasnik: "Objasni mi kako ovdje postoji profitabilni wallet, a mi nemamo profitabilnu strategiju ... Nađi mi
# profitabilnu strategiju"; wallets/kopija.py, wallets/kopija_demo.py): FLAG "kopija_dokazani": paper = the DEMO account
# PAPER_USER copies every fresh buy of a wallet that is "dokazan dvaput" and "kopirljiv" (0.1 SOL, 10 open, 30 a day,
# one position a token; exit when he sells, else stop -20 %), also under 5M MC (a demo-only exception to trade/capgate:
# the module never asks it and never trades another account), and stores his price, ours and the delay. Never live
# (NEVER_LIVE), no owner switch: real money stays exactly where it is. Default paper (FLAG_DEFAULTS): it reads the
# webhook the proven wallets are already on, so it adds no paid volume.
KOPIJA = "kopija_dokazani"
FLAGS[KOPIJA] = ("P25", "Kopija dokazanih novčanika (demo): demo račun kopira svaku svježu kupnju novčanika koji je "
                        "dokazan dvaput i kopirljiv (0,1 SOL, najviše 10 otvorenih, 30 dnevno, jedna pozicija po tokenu; "
                        "izlaz kad on proda ili stop −20 %), i ispod 5M $ (iznimka samo za demo), i bilježi njegovu cijenu, "
                        "našu i kašnjenje; mjeri koliko bismo zaradili kopirajući ih")
NEVER_LIVE[KOPIJA] = "kopija_dokazani nikad ne trguje pravim novcem (samo demo račun); to je mjerenje kopiranja"
PROFILE_FLAGS = PROFILE_FLAGS | {KOPIJA}   # its paper mode never makes the paper account follow anybody
FLAG_DEFAULTS[KOPIJA] = "paper"

# 18.11. (vlasnik: "Ne želim da se pravi novac pauzira, nego želim da se da sve od sebe da tradeovi s pravim novcem
# postanu profitabilni"; veliki/ucenik.py): the owner switch of the LEARNED rule. Off by default; set_flag accepts
# "live" only from the owner (his tap under Prekidači, or his own order in the chat applied once in his name:
# ui/assistnotes.owner_nauceno_real, 18.11.: "Odmah želim da pravi novac krene raditi", executed ONLY if the learner's
# corrected, purged walk-forward confirms the +1 % threshold, else parked for him); no applied suggestion and no
# council decision turns it on. "uživo" = an entry of the demo account autopilot-nauceno (the stored model predicts
# its best exit profile above +1 % net) ALSO gets a real twin when every check of a real midcap entry passes
# (veliki/ucenik._enter_real -> veliki/live.enter): through the same mirror and executor.buy as the midcap range and
# inside the same caps (veliki/gate.real_caps: max open, buys a day, a day's loss; the global automatic caps; the
# wallet floor; the kill switch), at 0.1 SOL and never more, sold at the same fixed target / stop / 72 h as its demo
# twin (plus a rug or a liquidity collapse). It does not read or change pravi_novac_veliki: the two are decided apart.
NAUCENO_SWITCH = "pravi_novac_nauceno"
FLAGS[NAUCENO_SWITCH] = ("P26", "Pravi novac za naučeno pravilo: ulaz demo računa „naučeno” (model učenja predviđa "
                                "najbolji izlaz iznad +1 % neto) kupuje i pravim novcem kad prođe sve provjere pravog "
                                "midcap ulaza (velika lista, MC 5-150M $, likvidnost 500k+ $, bez opreza holdera), 0,1 SOL "
                                "po tradeu i nikad više, unutar istih stropova kao midcap raspon (najviše 5 otvorenih, 20 "
                                "kupnji dnevno, dnevni gubitak 0,3 SOL); izlaz na cilju, stopu ili nakon 72 h tog profila")
OWNER_SWITCHES = OWNER_SWITCHES | {NAUCENO_SWITCH}
OWNER_SWITCH_NOTES[NAUCENO_SWITCH] = ("Tvoj prekidač: „uživo” = ulaz demo računa „naučeno” kupuje i pravim novcem kad "
                                      "prođe provjere pravog midcap ulaza (0,1 SOL, nikad više; stropovi midcap raspona "
                                      "vrijede za oba pravila zajedno: 5 otvorenih, 20 kupnji dnevno, dnevni gubitak 0,3 "
                                      "SOL; pod novčanika 1 SOL, kill switch, arhiva rugova, velika lista, MC 5-150M $, "
                                      "likvidnost 500k+ $, trošak do 6 %). Pravilo još NIJE dokazano na novim danima: demo "
                                      "ga tek mjeri (presuda nakon 21 dana ili 60 token-dana). Izlazi: cilj, stop ili 72 h "
                                      "profila, uz rug i pad likvidnosti. Ne ovisi o prekidaču pravi_novac_veliki. Svaki "
                                      "drugi mod = samo demo.")


# 19.11. (vlasnik: "Autopilot kupovinu s pravim novcem isključi ... dok je pravi novac isključen radi što više demo
# tradeova sa praćenjem voleta"): the PAUSE of every AUTOMATIC real-money buy. Set once by his order
# (ui/assistnotes.owner_pauza_1911: his five real-money switches go off and this key goes on); while it is on,
# run_trade's mirror refuses every automatic buy of the real account and trade/executor.auto_hard refuses every
# automatic real buy whatever path asked (copies with a demo proof and Grok autotrade included). NOT touched: every
# sale and exit of an open real position, the owner's own manual buy and his own DCA / limit orders, every demo
# account. It ends only when the owner himself turns one of his real-money switches back to "uživo" (set_flag).
PAUZA_KEY = "pravi_novac_pauza"

# 23.11. (vlasnik u chatu: "kreni da najviše dvije pozicije mogu biti otvorene, ali ako se zatvore, otvori dvije nove
# ... želim puno tradeova sa uključenim 4% fijem kojeg plaćamo za tradeove. Tako da pazite kad se zatvara da bi profit
# postojao"; veliki/riskoff.py): the owner switch of the RISK-OFF EXCEPTION of the midcap daily range. Default off.
# "uživo" by his own tap on the Autopilot page with its confirmation (set_flag needs his name AND tap=True: no chat
# order, applied suggestion or council decision can turn it on), or by his one-time order of 23.11.
# (riskoff_order_2311 below; written, tested, NOT wired to any start until he allows it). On: while the macro regime
# risk_off is the ONLY market gate holding real money, the real account may still enter the daily-range rule under
# veliki/riskoff's conditions (BTC not falling, the Solana meme sector >= 0 % in 24 h, MC >= 15M, at most 2 open real
# midcap positions, 0.1 SOL, a 4 % round-trip cost floor, the target >= +3 % net and voluntary profit exits only from
# +1 % net). His tap to "uživo" also turns pravi_novac_veliki on when it is off and ends the pause of 19.11. (it is one
# of REAL_SWITCHES). Turning it off never touches an open position.
RISKOFF_SWITCH = "pravi_novac_risk_off"
RISKOFF_LABEL = "midcap raspon u risk-offu (iznimka, najviše 2 pozicije)"
RISKOFF_CONFIRM = "Uključuje i 'midcap raspon' pravim novcem i skida pauzu od 19.11."
FLAGS[RISKOFF_SWITCH] = ("P27", "Pravi novac: " + RISKOFF_LABEL + ": dok je makro režim risk-off jedini filtar, dnevni "
                                "raspon smije kupiti pravim novcem kad BTC ne pada (4 h ≥ −1 %), Solana meme sektor nije "
                                "u minusu 24 h i MC ≥ 15M $; 0,1 SOL, najviše 2 otvorene; trošak kruga najmanje 4 %, cilj "
                                "barem +3 % neto, dobrovoljni izlaz tek od +1 % neto")
OWNER_SWITCHES = OWNER_SWITCHES | {RISKOFF_SWITCH}
OWNER_SWITCH_NOTES[RISKOFF_SWITCH] = ("Tvoj prekidač (samo dodirom na stranici Autopilot, uz potvrdu): „uživo” = u "
                                      "risk-offu pravi novac smije do 2 pozicije dnevnog raspona po 0,1 SOL, samo dok BTC "
                                      "ne pada i meme sektor nije u minusu 24 h, MC ≥ 15M $; trošak kruga računa se "
                                      "najmanje 4 %, ulaz samo kad je cilj barem +3 % neto, dobrovoljni izlaz tek od +1 % "
                                      "neto (stopovi uvijek). " + RISKOFF_CONFIRM + " Isključivanje ne dira otvorene "
                                      "pozicije.")
REAL_SWITCHES = (VEL_SWITCH, NAUCENO_SWITCH, SWITCH_ALL, IZVORI, OSC_SWITCH, RISKOFF_SWITCH)
PAUZA_1911_SWITCHES = REAL_SWITCHES[:5]
PAUZA_TEXT = ("pravi novac je pauziran (vlasnik 19.11.: promjena strategije): automatske prave kupnje stoje dok vlasnik "
              "ne uključi svoj prekidač; otvorene pozicije zadržavaju izlaze")


def pauza(con):
    """The stored pause ({"on": True, "ts", "who", "why"}) while it is on, else None. Never raises: a database
    without the settings table or an unreadable value is "not paused" (the five switches are read separately)."""
    try:
        row = con.execute("SELECT v FROM settings WHERE k = ?", (PAUZA_KEY,)).fetchone()
        v = json.loads(row[0]) if row else None
    except (sqlite3.Error, ValueError, TypeError):
        return None
    return v if isinstance(v, dict) and v.get("on") else None


def pauza_set(con, on, who="", why="", now=None):
    """Turn the pause on / off (the owner's order, or his own tap of a real-money switch)."""
    put(con, PAUZA_KEY, {"on": bool(on), "ts": int(now or time.time()), "who": who, "why": why}, who)


PAUZA_ONCE = "owner_once:pravi_novac_pauza_1911"
PAUZA_WHY = "vlasnik u chatu 19.11.: Autopilot kupovinu pravim novcem isključi (promjena strategije: novčanici)"


def pauza_order_1911(con, now=None):
    """The owner's order of 19.11., ONCE (both run_trade and the page process ask at their start; whoever is first
    does it): his five real-money switches go off and the pause goes on. -> [text of each change]; [] when it has
    already run or the database cannot be read. No position is sold, no cap or stake is touched."""
    try:
        if con.execute("SELECT 1 FROM settings WHERE k = ?", (PAUZA_ONCE,)).fetchone():
            return []
        done = []
        for name in PAUZA_1911_SWITCHES:   # the five of that day (the risk-off exception came on 23.11.)
            old = flag_state(con)[name]["mode"]
            if old == "off":
                done.append(f"{name}: već off")
                continue
            set_flag(con, name, "off", owner(), now=now)   # going down is always allowed
            done.append(f"{name}: {old} → off")
        pauza_set(con, True, owner(), PAUZA_WHY, now)
        put(con, PAUZA_ONCE, {"ts": int(now or time.time()), "promjene": done}, owner())
    except (sqlite3.Error, ValueError, TypeError):
        return []
    return done


def pauza_order_line(done):
    return ("pravi trade: nalog vlasnika 19.11. izvršen: automatske kupnje pravim novcem su ISKLJUČENE ("
            + "; ".join(done) + "); otvorene prave pozicije ostaju otvorene i zadržavaju izlaze; ručna kupnja vlasnika i "
            "njegovi DCA / limit nalozi nisu dirani; demo računi rade dalje; uključuje samo vlasnik svojim prekidačem")


# 23.11. 14:38-14:40 UTC (vlasnik): he set pravi_novac_veliki live himself (the pause of 19.11. ended by his tap) and
# wrote "Kreni odmah s tradeovima, uključeni su svi prekidači, live trade je uključen. Pazi samo da se uspostavi novi
# range, da pametno ulaziš", after "Ok, kreni da najviše dvije pozicije mogu biti otvorene ... sa uključenim 4%
# fijem": his explicit order for the risk-off exception. ONE time order (the only code path besides his tap that may
# set RISKOFF_SWITCH live): at a process start, until RISKOFF_ORDER_UNTIL, ONLY while pravi_novac_veliki is live by
# his own setting, the pause is off and the kill switch is off; otherwise nothing (not marked done, so a later start
# before the expiry may still apply it). It never touches pravi_novac_veliki, the pause, sizes or caps. Once it ran
# (or the switch already had any stored setting of his) it never runs again: the switch is then his alone.
RISKOFF_ONCE = "owner_once:risk_off_iznimka_2311"
RISKOFF_WHY = "vlasnik u chatu 23.11.: najviše dvije pozicije, 4 % trošak, kreni odmah"
RISKOFF_ORDER_UNTIL = 1795521600   # 2026-11-24 12:00 UTC
RISKOFF_ORDER_LINE = ("pravi trade: nalog vlasnika 23.11. izvršen: risk-off iznimka UKLJUČENA (najviše 2 pozicije po "
                      "0,1 SOL, trošak 4 %); gasi se prekidačem na stranici Autopilot")


def riskoff_order_2311(con, now=None, stop_file=None):
    """The owner's order of 23.11. for the risk-off exception (above), at most once. -> the log line when it switched
    the exception on, else None. Never raises (an unreadable database does nothing)."""
    now = int(now or time.time())
    try:
        if now >= RISKOFF_ORDER_UNTIL:
            return None
        if con.execute("SELECT 1 FROM settings WHERE k = ?", (RISKOFF_ONCE,)).fetchone():
            return None
        if raw(con).get(f"flag:{RISKOFF_SWITCH}") is not None:
            # he already set it himself (on or off): his setting stands, the order is spent
            put(con, RISKOFF_ONCE, {"ts": now, "primijenjeno": False, "zasto": "prekidač je već postavio vlasnik"},
                owner())
            return None
        vel = flag_state(con)[VEL_SWITCH]
        stored = raw(con).get(f"flag:{VEL_SWITCH}")
        if vel["mode"] != "live" or not is_owner(vel["who"]) or (isinstance(stored, dict) and stored.get("uz")):
            return None
        if pauza(con):
            return None
        if stop_file is None:
            from trade import executor
            stop_file = executor.STOP_FILE
        if os.path.exists(stop_file):
            return None
        put(con, f"flag:{RISKOFF_SWITCH}", {"mode": "live", "since": now, "who": owner(), "nalog": RISKOFF_WHY},
            owner())
        put(con, RISKOFF_ONCE, {"ts": now, "primijenjeno": True, "zasto": RISKOFF_WHY}, owner())
        _FLAG_CACHE.clear()
    except (sqlite3.Error, ValueError, TypeError):
        return None
    return RISKOFF_ORDER_LINE


def pravi_novac_izvori(con=None, path=None):
    """True while the owner's switch pravi_novac_izvori is on (mode "live"); never raises (unreadable = off)."""
    try:
        return flag(IZVORI, con, path) == "live"
    except Exception:  # noqa: BLE001
        return False


def pravi_novac_sve(con=None, path=None):
    """True while the owner's switch pravi_novac_sve is on (mode "live"); never raises (unreadable = off)."""
    try:
        return flag(SWITCH_ALL, con, path) == "live"
    except Exception:  # noqa: BLE001
        return False
# 10.11. (group_discovery): flags whose move to paper needs a proof of their own, "module:function"(con, now=) -> None
# or the reason in Croatian. Asked only by set_flag (the owner's tap), so it is enforced and never automatic.
PAPER_GATES = {"group_discovery": "kol.groupdisc:paper_refusal"}
PAPER_GATES["pre_shill"] = "kol.preshill:paper_refusal"   # 11.11.: 7 days of shadow, >= 30 measured signals, EV > 0
# 10.11. (insider_copy): flags whose move to live needs a proof of their own on top of live_refusal's (same shape)
LIVE_GATES = {"insider_copy": "kol.precall:live_refusal",
              "momentum_scalp": "momentum.gate:live_refusal"}   # >= 50 paper trades, trade/edge live proof
LIVE_GATES["proposals"] = "proposals.paper:live_refusal"   # 11.11.: never live (no automatic path to the real account)
LIVE_GATES["fast_path"] = "fast.paper:live_refusal"   # >= 30 closed fast-path paper trades, trade/edge live proof
LIVE_GATES["range_flip"] = "rangedca.gate:flip_live_refusal"   # 11.11.: nightly backtest, new max DD <= today's
LIVE_GATES["range_missed"] = "rangedca.gate:missed_live_refusal"   # 11.11.: >= 20 rounds of source missed, EV proof
DCA_TOKEN_CAP = 0.3   # SOL in one token at most under dca_cap, until the owner applies another (settings "dca_token_cap")
DATA_FLAGS = frozenset({"x_features_ingest", "grok_predictions", "zonewatch"})   # 19.11.: 4 dead ones removed
_FLAG_CACHE = {}       # db path -> (monotonic read time, {name: mode})
FLAG_CACHE_S = 2.0     # loops ask every second; a change on the page holds within this

# key -> (label, type, min, max); the owner edits these on the page
LIMITS = {
    "size_sol": ("Ulog po kupnji (SOL)", float, 0.005, 5.0),
    "max_sol_per_day": ("Najviše potrošeno na automatske kupnje u danu (SOL)", float, 0.01, 50.0),
    "max_loss_day": ("Najveći gubitak u danu, onda stop (SOL)", float, 0.01, 50.0),
    "max_open": ("Najviše otvorenih pozicija", int, 1, 50),
    "min_sol_reserve": ("Uvijek ostavi u walletu (SOL)", float, 0.01, 10.0),
    "max_cost_pct": ("Najveći trošak swapa (%)", float, 0.5, 20.0),
    # 14.11. popodne (pravi_novac_sve, rangedca/trade): the real account's range scalp; defaults LIMIT_DEFAULTS
    "range_scalp_trades_day": ("Range scalp: najviše rundi pravog računa u danu", int, 1, 500),
    "range_scalp_target_usd": ("Range scalp: neto cilj po rundi nakon troškova ($)", float, 0.1, 50.0),
}
# 14.11. popodne: the value of a LIMITS key config.json does not carry (merged() sets it when the owner never did)
LIMIT_DEFAULTS = {"range_scalp_trades_day": 100, "range_scalp_target_usd": 0.60}

# Audit 4.11. §14.4/§22: switches that stay off whatever is saved, until the proof the audit asks for exists.
# The page shows them greyed out with this reason; run_trade and the SimianX job read the effective value.
LOCKED = {
    "follow_paper": "zaključano: demo strategija smije u pravi novac tek kad dobije status „kandidat” "
                    "(bije kontrolu nakon troška, na obje polovice, i bez 5 najboljih trejdova)",
    "simianx": "zaključano: SimianX signali nemaju isti dokaz kao praćeni influenceri i novčanici "
               "(odgođena kopija koja bije kontrolu), pa ne idu u pravi novac",
}

SCHEMA = "CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT, ts INTEGER, who TEXT)"


def connect(path=None):
    con = sqlite3.connect(path or DB, timeout=30)
    con.execute(SCHEMA)
    return con


# 12.11. (Jure, nalog točka 6: "Prikazuj samo stvarno otvorene lotove iz portfolija"): ONE definition of a real open
# lot for every reader that says "the real account" (zonewatch's positions, their alarms, get_armed_zones): a trade.db
# positions row with mode 'live' and status 'open' that still holds tokens (qty_left > 0), or a 'pending' one younger
# than LIVE_PENDING_FRESH_S (its swap is in flight: executor.buy books the quantity when it lands, reconcile_pending
# settles an older one). These are the live rows of the portfolio (get_portfolio_status, the Autopilot page's live
# positions). A league.db trade of LEAGUE_USER alone is never one: that account also holds the demo copies whose real
# swap was blocked, failed or ran dry (positions status blocked / failed, mode dry) or never started.
LIVE_PENDING_FRESH_S = 180
LIVE_LOT_COLS = ("id", "token", "symbol", "opened_ts", "status", "sol_in", "qty_raw", "qty_left", "league_id", "reason")


def live_lots(con, now=None):
    """[dict LIVE_LOT_COLS] of the real open lots (see above), oldest first; [] while trade.db has no positions table.
    Any other sqlite3 error propagates: the caller decides what an unreadable trade.db means."""
    now = int(now or time.time())
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='positions'").fetchone():
        return []
    return [dict(zip(LIVE_LOT_COLS, r)) for r in con.execute(
        f"SELECT {', '.join(LIVE_LOT_COLS)} FROM positions WHERE mode='live' AND ((status='open' AND qty_left > 0) "
        "OR (status='pending' AND opened_ts >= ?)) ORDER BY id", (now - LIVE_PENDING_FRESH_S,))]


def owner():
    return (os.environ.get("TRADE_OWNER") or "Jure").strip().lower()


def is_owner(user):
    return bool(user) and user.lower() == owner()


def raw(con):
    return {k: json.loads(v) for k, v in con.execute("SELECT k, v FROM settings")}


def put(con, key, value, who=""):
    con.execute("INSERT OR REPLACE INTO settings VALUES (?,?,?,?)", (key, json.dumps(value), int(time.time()), who))
    con.commit()


def merged(cfg, con):
    """config.json defaults + what the owner set on the page. The switch ("on") lives only here: off by default."""
    s = raw(con)
    out = dict(cfg)
    for k in LIMITS:
        if k in s:
            out[k] = s[k]
    for k, v in LIMIT_DEFAULTS.items():   # 14.11. popodne: the range scalp's own two settings
        out.setdefault(k, v)
    out["max_sol_per_trade"] = max(out.get("max_sol_per_trade", 0), out["size_sol"])
    out["on"] = bool(s.get("on", False))
    out["follow_paper"] = bool(s.get("follow_paper", False)) and "follow_paper" not in LOCKED
    out["use_pump"] = bool(s.get("use_pump", True))
    out["simianx"] = bool(s.get("simianx", False)) and "simianx" not in LOCKED
    out["dca_cap_owner"] = bool(s.get("dca_cap_owner", False))     # 10.11. ~21:00: the owner's per-token SOL cap
    out["dca_token_cap"] = s.get("dca_token_cap", DCA_TOKEN_CAP)
    # 11.11. (Jure: "promijeni maksimalnu poziciju tokenu na 1 sol"): the cap of the OWNER's buys (manual, DCA,
    # buy orders) apart from dca_token_cap, which stays the Autopilot's copy cap (10.11.: 0,3 SOL on autopilot-paper)
    out["owner_token_cap"] = s.get("owner_token_cap", out["dca_token_cap"])
    out.setdefault("day_tz", "Europe/Zagreb")
    out["sell_all"] = s.get("sell_all") or 0
    out["sell_req"] = s.get("sell_req") or {}
    out["manual_size"] = s.get("manual_size") or {}
    # 11.11. (owner: "ručno uvijek nadjačava sve ostalo"): demo trade id -> {"why": [...], "ts", "who"} of the owner's
    # buys he confirmed over his limits (ui/pravitrade._post_buy); run_trade hands it to executor.buy(override=...)
    out["manual_override"] = s.get("manual_override") or {}
    out["heartbeat"] = s.get("heartbeat") or 0
    out["tp_default"] = int(s.get("tp_default") or 15)   # 9.11. (Jure): the exit target for new copies, set at the top of the page
    out["sl_default"] = int(s.get("sl_default") or SL_DEFAULT)
    out["last_exit"] = s.get("last_exit") or {}   # 10.11. (Jure): the TP / SL the owner used last, for the next order
    out["buy_orders"] = s.get("buy_orders") or []   # 10.11. (Jure): buy orders at a market cap (ui/pravitrade.limit_once)
    out["buy_log"] = s.get("buy_log") or []
    return out


def sl_text(pct):
    """60 -> "-60%": the stop as a level league/auto.parse_level reads."""
    return f"-{int(pct)}%"


def sl_default(path=None):
    """The Autopilot's default stop as a level ("-60%"), read-only from trade.db (league/copy asks it at every
    entry, in another process than the page). SL_DEFAULT when the database or the key is not there."""
    path = path or DB
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        try:
            row = con.execute("SELECT v FROM settings WHERE k='sl_default'").fetchone()
        finally:
            con.close()
        v = int(json.loads(row[0])) if row else SL_DEFAULT
    except (sqlite3.Error, ValueError, TypeError):
        v = SL_DEFAULT
    return sl_text(v if v in SL_CHOICES else SL_DEFAULT)


def _flag_value(v, default="off"):
    """Stored flag value -> {"mode", "since", "who"} (a bare string from a hand edit counts too). default: the mode of
    a flag never set (FLAG_DEFAULTS; "off" for every other)."""
    if v is None:
        v = {"mode": default}
    if isinstance(v, str):
        v = {"mode": v}
    v = v if isinstance(v, dict) else {}
    mode = v.get("mode") if v.get("mode") in FLAG_MODES else "off"
    return {"mode": mode, "since": int(v.get("since") or 0), "who": v.get("who") or ""}


def flag_state(con):
    """{name: {"mode", "since", "who"}} of every flag in FLAGS (never set: FLAG_DEFAULTS, else "off"; since 0)."""
    s = raw(con)
    return {n: _flag_value(s.get(f"flag:{n}"), FLAG_DEFAULTS.get(n, "off")) for n in FLAGS}


def _flags_ro(path):
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        try:
            rows = con.execute("SELECT k, v FROM settings WHERE k LIKE 'flag:%'").fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return None   # unreadable: flag() answers "off" for every flag, defaults included
    out = {}
    for k, v in rows:
        try:
            out[k[5:]] = _flag_value(json.loads(v))["mode"]
        except (ValueError, TypeError):
            continue
    return out


def flag(name, con=None, path=None):
    """The mode of one flag: "off" | "shadow" | "paper" | "live". With con: read now; without: read-only from
    trade.db, cached FLAG_CACHE_S per process (the copy and exit loops ask every pass). Never raises: a flag that
    cannot be read is "off", i.e. the old behaviour."""
    if name not in FLAGS:
        raise KeyError(f"nepoznata zastavica {name}")
    if con is not None:
        try:
            return _flag_value(raw(con).get(f"flag:{name}"), FLAG_DEFAULTS.get(name, "off"))["mode"]
        except (sqlite3.Error, ValueError, TypeError):
            return "off"
    path = path or DB
    now = time.monotonic()
    hit = _FLAG_CACHE.get(path)
    if hit is None or now - hit[0] > FLAG_CACHE_S:
        hit = (now, _flags_ro(path))
        _FLAG_CACHE[path] = hit
    if hit[1] is None:   # trade.db unreadable: the old behaviour, every flag off
        return "off"
    return hit[1].get(name, FLAG_DEFAULTS.get(name, "off"))


def flag_on(name, con=None, path=None):
    """A data flag (DATA_FLAGS) collects or accepts input in every mode but off."""
    return flag(name, con, path) != "off"


def any_paper(con=None, path=None):
    """True while at least one flag is in paper mode (only then the paper account follows anybody)."""
    if con is not None:
        return any(v["mode"] == "paper" for n, v in flag_state(con).items() if n not in PROFILE_FLAGS)
    return any(flag(n, path=path) == "paper" for n in FLAGS if n not in PROFILE_FLAGS)


def live_refusal(con, name, paper=None, now=None):
    """None when `name` may go live, else the reason in Croatian. paper: {"n": closed trades, "pnl": USD} of the
    paper account since the flag went to paper (league/flags.paper_result); None = not known."""
    now = int(now or time.time())
    if name in NEVER_LIVE:
        return NEVER_LIVE[name]
    if name in DATA_FLAGS or name in OWNER_SWITCHES:
        return None
    bt = raw(con).get(f"backtest:{name}") or {}
    if not (isinstance(bt, dict) and bt.get("pass") is True):
        return f"nema prolaza backtesta (python3 run_backtest.py --flag {name})"
    st = flag_state(con)[name]
    if st["mode"] == "live":
        return None
    if name == "range_dca":   # 10.11. (Jure): >= 20 closed paper rounds, trade/edge live proof (rangedca/gate.py)
        try:
            from rangedca import gate as _range_gate
            why = _range_gate.refusal(now=now)
        except Exception as e:  # noqa: BLE001 - a proof that cannot be read is no proof
            why = f"dokaz range_dca nije čitljiv ({type(e).__name__})"
        if why:
            return why
    if st["mode"] != "paper" or not st["since"]:
        return f"prvo najmanje {PAPER_DAYS} dana u paper modu"
    days = (now - st["since"]) / 86400
    if days < PAPER_DAYS:
        return f"u paper modu tek {days:.1f} od {PAPER_DAYS} dana"
    if not paper or not paper.get("n"):
        return "paper račun još nema nijedan zatvoren trade"
    if (paper.get("pnl") or 0) <= 0:
        return f"paper račun je u minusu ({paper['pnl']:+.2f} $ na {paper['n']} tradeova)"
    spec = LIVE_GATES.get(name)
    if spec:   # 10.11.: e.g. insider_copy also needs >= 20 closed paper copies of its own with EV > 0
        try:
            import importlib
            mod, fn = spec.split(":")
            return getattr(importlib.import_module(mod), fn)(con, now=now)
        except Exception as e:  # noqa: BLE001 - a proof that cannot be read is no proof
            return f"dokaz za live se ne može pročitati ({type(e).__name__})"
    return None


def paper_refusal(con, name, now=None):
    """None when `name` may go from off / shadow to paper, else the reason in Croatian. Most flags may (paper moves
    no real money); market_scan only with its sources' measured proof (scan/shadow.flag_paper_refusal: >= 30 finished
    shadow outcomes and EV > 0); the flags in PAPER_GATES through their own proof (e.g. group_discovery). A proof that
    cannot be read refuses. Nothing calls set_flag on its own."""
    if name == "market_scan":
        try:
            from scan import shadow
            return shadow.flag_paper_refusal(now=now)
        except Exception as e:  # noqa: BLE001 - no proof readable: no paper
            return f"dokaz iz sjene nije čitljiv ({type(e).__name__})"
    spec = PAPER_GATES.get(name)
    if not spec:
        return None
    try:
        import importlib
        mod, fn = spec.split(":")
        return getattr(importlib.import_module(mod), fn)(con, now=now)
    except Exception as e:  # noqa: BLE001 - a proof that cannot be read is no proof
        return f"dokaz se ne može pročitati ({type(e).__name__})"


def set_flag(con, name, mode, who="", paper=None, now=None, tap=False):
    """Owner's change of one flag (the page checks is_owner). Raises ValueError with the reason when refused.
    Going down (to off or shadow) is always allowed, and to paper from live; up to paper only past paper_refusal;
    "since" restarts on every change of mode. tap (23.11.): True only from the owner's own confirmed tap on the page
    (ui/pravitrade /pravi-trade/flag with the confirmation field); RISKOFF_SWITCH goes live only with it."""
    if name not in FLAGS:
        raise ValueError("nepoznata zastavica")
    if mode not in FLAG_MODES:
        raise ValueError("nepoznat mod (off, shadow, paper, live)")
    now = int(now or time.time())
    cur = flag_state(con)[name]
    if mode == cur["mode"]:
        return cur
    if mode == "live" and name in (SWITCH_ALL, IZVORI, OSC_SWITCH, VEL_SWITCH, NAUCENO_SWITCH, MAKROINF_JAVNO,
                                   RISKOFF_SWITCH) and not is_owner(who):
        # 14.11.: real money for every strategy only by the owner's own tap (the page passes his user name), never by a
        # chat order, an applied suggestion or any other code path
        raise ValueError(f"{name}: uključuje samo vlasnik, svojim dodirom na /pravi-trade")
    if mode == "live" and name == RISKOFF_SWITCH and tap is not True:
        # 23.11.: never in his name from code (a chat order, a seed, a start): only his confirmed tap on the page
        raise ValueError(f"{name}: uključuje samo vlasnik dodirom na prekidač na stranici Autopilot, uz potvrdu")
    if mode == "live":
        why = live_refusal(con, name, paper, now)
        if why:
            raise ValueError(f"{name} ne može u live: {why}")
    if mode == "paper" and cur["mode"] in ("off", "shadow"):
        why = paper_refusal(con, name, now)
        if why:
            raise ValueError(f"{name} ne može u paper: {why}")
    val = {"mode": mode, "since": now, "who": who}
    if mode == "live" and name == RISKOFF_SWITCH and flag_state(con)[VEL_SWITCH]["mode"] != "live":
        # 23.11.: the same confirmed tap turns the midcap range's real money on too (the exception runs inside it);
        # set first, so a refusal leaves both as they were
        put(con, f"flag:{VEL_SWITCH}", {"mode": "live", "since": now, "who": who, "uz": RISKOFF_SWITCH}, who)
    put(con, f"flag:{name}", val, who)
    _FLAG_CACHE.clear()
    if mode == "live" and name in REAL_SWITCHES and pauza(con):   # 19.11.: his own tap ends the pause of 19.11.
        pauza_set(con, False, who, f"vlasnik uključio {name}", now)
    return val


def parse_limits(form):
    """Form -> {key: value}; raises ValueError with a Croatian message on a bad number."""
    out = {}
    for k, (label, typ, lo, hi) in LIMITS.items():
        txt = (form.get(k) or "").strip().replace(",", ".")
        if not txt:
            continue
        try:
            v = typ(float(txt))
        except ValueError:
            raise ValueError(f"{label}: upiši broj")
        if not lo <= v <= hi:
            raise ValueError(f"{label}: mora biti između {lo:g} i {hi:g}")
        out[k] = v
    return out


def invited(con):
    return [u for u in raw(con).get("invited", []) if u]


def can_view(con, user):
    return is_owner(user) or bool(user) and user.lower() in {u.lower() for u in invited(con)}


def simianx_on(con=None):
    """The owner's approval for SimianX long signals on the real-trade account (off by default). The SimianX job
    opens its demo trades on LEAGUE_USER only while this is on (league.store.buy + auto.set_auto with its stop and
    target); run_trade.py then mirrors them like any copy trade, inside the same limits."""
    own = con is None
    con = con or connect()
    try:
        return bool(raw(con).get("simianx", False)) and "simianx" not in LOCKED
    finally:
        if own:
            con.close()
