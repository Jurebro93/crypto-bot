#!/usr/bin/env bash
# Render background worker: everything that must run 24/7, in one container.
# Databases, output and the HTTP cache live on the persistent disk at $DATA_DIR and are symlinked into place,
# so the code keeps its usual paths and a redeploy loses nothing.
set -u
cd "$(dirname "$0")"
DATA_DIR="${DATA_DIR:-/var/data}"
mkdir -p "$DATA_DIR/output"
for f in xfeat.db calendar.db hype.db paper.db rug.db wallets.db trade.db usage.db league.db market.db kol.db watch.db corr.db dugo.db tg.db koltest.db strat.db shadow.db ai.db nastoken.db public.db analytics.db topcheck.db scan.db simianx.db minute.db; do
  touch "$DATA_DIR/$f"
  ln -sfn "$DATA_DIR/$f" "$f"
done
ln -sfn "$DATA_DIR/output" output
# 10.11. early.db (smart_discovery's early buyers + group_discovery's group_* tables, kol/groupdisc.py): persistent too
touch "$DATA_DIR/early.db"; ln -sfn "$DATA_DIR/early.db" early.db
# 11.11. events.db (one log of every call, wallet trade, price, trade and signal, events/store.py): persistent too; the
# collectors write into it only once this file exists
touch "$DATA_DIR/events.db"; ln -sfn "$DATA_DIR/events.db" events.db
# 15.11. insajderi.db (Insajderi 2.0, insajderi/store.py): persistent too
touch "$DATA_DIR/insajderi.db"; ln -sfn "$DATA_DIR/insajderi.db" insajderi.db
# 15.11. makroinf.db (makro influenceri, makroinf/store.py): persistent too
touch "$DATA_DIR/makroinf.db"; ln -sfn "$DATA_DIR/makroinf.db" makroinf.db
# 19.11. bnb.db (BNB Smart Chain: pumpe i novčanici, bnb/store.py): persistent too
# 20.11. (vlasnik: "BNB treba stalno pratiti i tražiti novčanike"): on by default from here on; BNB_ON=0 on Render
# turns the whole line off again (the Python side stays dormant unless it sees BNB_ON=1, so the export decides).
export BNB_ON="${BNB_ON:-1}"
if [ "$BNB_ON" = "1" ]; then touch "$DATA_DIR/bnb.db"; ln -sfn "$DATA_DIR/bnb.db" bnb.db; fi
export CAL_CACHE_DIR="$DATA_DIR/cache" LEARNED_DIR="$DATA_DIR/learned" PYTHONUNBUFFERED=1 UI_SNAP_DIR="$DATA_DIR/pagecache"
# memory: glibc gives every thread its own malloc arena (up to 8 per CPU the host reports, not our 0.5 CPU), and
# freed memory stays parked in them, so the threaded dashboard climbed to ~200 MB and the 512 MB server ran out
# of memory every few minutes (1.11.). Two arenas per process: same speed here, about half the memory (UI test
# 79 -> 44 MB after the same page loads). Applies to every python process started below.
export MALLOC_ARENA_MAX="${MALLOC_ARENA_MAX:-2}"

# web service only: a stand-in on Render's port from the first second (deploy_wait.py): visitors get the funny
# "deploy in progress" page instead of Render's black 502 while the databases are prepared and run_ui.py loads;
# it hands the port over the moment run_ui.py is ready to bind (~0.1 s), or gives up after 4 min.
# disown: it ends on purpose, and "wait -n" at the bottom must not take that for a crashed loop
if [ -n "${PORT:-}" ]; then python3 deploy_wait.py --port "$PORT" & disown; fi

# databases once before anything opens them: old raw Apify answers out, auto_vacuum switched on (one VACUUM per
# file, only when the disk has room), WAL journal on (ops/dbs.py). A full disk (<100 MB free) no longer stops this.
# 9.11. (audit P9): seconds, not minutes: the hype_signals slimming and the per-file compaction moved to the hourly
# upkeep below (they ran here on every deploy, 20+ a day, while the UI, webhooks and trade waited); only a tight disk
# (ops/dbs.STARTUP_COMPACT_FREE_MB) still compacts offline here, the one case where nothing else works.
python3 -m ops.health --startup || echo "baze: priprema nije uspjela"
# 11.11. (Jure, preporuka 3): one line in the log at every start: which Apify sources are off (hype/apify.json
# "ugaseno") and which stay on and why ("zadrzano"); reading a small JSON, no network
python3 -m hype.apify || true
# 15.11. navečer (vlasnik: "ne želim više mikrokapove uopće ... sve resurse prebaci na midcapove 2M-200M"; owner switch
# fokus_midcap, ops/fokus.py): one line at every start: which microcap jobs are off, which are retargeted, how many
# midcaps the collector holds and from which sources (reads trade.db / midcap.db, no network)
python3 -m ops.fokus || true
# 19.11. (vlasnik: "stop spending resources on scraping influencers and Telegram channels ... refreshed once every 5
# days. What I want every day is wallets"; ops/drustveni.py): one line at every start with the social refresh window
# (open / closed, next); the first start after this deploy opens the first window (SOCIAL_EVERY_D 5 days,
# SOCIAL_WINDOW_H 6 h; state DATA_DIR/drustveni.json). Every influencer / Telegram job below asks the same gate
# (KOL search round and push rules, minute candles after calls, Telegram reader, makroinf, call power, X momentum, AI
# labels, zadnjih5, konsenzus); outside the window each says so once a day. SOCIAL_ALWAYS=1 = the old behaviour.
python3 -m ops.drustveni || true

# web service only: dashboard on Render's port, password from UI_PASSWORD (run_ui refuses to start without it).
# Started first so the page is back as soon as possible after a deploy (it only reads the databases).
# 5.11.: keep <name> <command...>: restarts just that process when it dies (30 s pause, logged), instead of
# "wait -n; exit 1" taking the whole worker down (two full restarts on 5.11. because run_live hit a locked database)
# 9.11. (audit P11): a deploy's SIGTERM reaches the supervised process (run_trade.cmd_follow finishes the pass it is
# in and exits, run_trade._on_term) instead of only the shell: the supervisor forwards TERM to its child and stops.
# 10.11. (Jure: "CPU u svakom momentu najviše 90-95 %, aplikacija dostupna u svakom momentu"): background loops run at a
# lower CPU priority (nice BG_NICE, default 10) than the UI, the trade loop, the listeners that bring the calls the
# money path acts on (kol, tg, live) and the demo loop (paper: its live exits react to a dump within seconds): where
# they wait for the same core, the kernel serves those first.
#   low keep <name> <command...>   a supervised process at low priority (its children inherit it)
#   low <command...>               one command at low priority, inside the plain loops below
# Jobs started through "python3 -m ops.heavy" need no "low": heavy.run already puts its child at HEAVY_NICE (10).
# The memory watchdog loop below stays at normal priority too: it is a safety check of a few ms a minute.
# Priority alone does not keep the container under its CPU quota (the kernel then stops everything, the UI included);
# that is the CPU guard's job, started right after the trade loop below.
BG_NICE="${BG_NICE:-10}"
low() { if [ "$1" = keep ]; then BG_LOW=1 "$@"; else nice -n "$BG_NICE" "$@"; fi; }
keep() { local name="$1"; shift; ( pid=; trap 'kill -TERM $pid 2>/dev/null; wait $pid 2>/dev/null; exit 0' TERM; while true; do ${BG_LOW:+nice -n "$BG_NICE"} "$@" & pid=$!; wait $pid; code=$?; echo "nadzor: $name završio (izlaz $code), ponovno za 30 s"; sleep 30 & wait $!; done ) & }
trap 'kill -TERM $(jobs -p) 2>/dev/null; wait' TERM
if [ -n "${PORT:-}" ]; then keep ui python3 run_ui.py --host 0.0.0.0 --port "$PORT"; fi
# 9.11. (audit P9): the real-money follower right after the UI (every loop below is backgrounded, so this only moves it
# ahead of ~20 python start-ups fighting for 0.5 CPU; the real gain is the short --startup above, so a paper entry
# from the deploy window is mirrored before max_signal_age_s runs out; it only reads paper.db/league.db/trade.db)
keep trade python3 run_trade.py follow       # mirrors paper entries/exits as real (or dry-run) swaps
# 10.11. (Jure, same request): CPU guard (ops/cpuguard.py): every second the container's CPU from the cgroup; when the
# average of a few seconds is above CPU_HIGH (90 %) it pauses the biggest background consumers for a fraction of a
# second at a time (SIGSTOP/SIGCONT) until it is back under CPU_LOW (80 %), in the order of the 10.11. audit (page
# builds first, run_top's rug check last). Never the UI, the trade loop, the listeners or a supervisor (the list with
# the reasons: python3 -m ops.cpuguard --popis). One log line a minute. CPUGUARD=0: measures and logs, pauses nothing.
# Started before the background loops so their start-up rush is already watched.
keep cpuguard python3 -m ops.cpuguard
# availability check (ops/uptime.py), web service only: /healthz every 30 s, slow and missing answers go to the log;
# after 150 s without an answer it ends ONLY the UI process (keep above brings it back), at most once in 15 min and
# not in the first 5 min after a start. UPTIME_RESTART=0: logs only.
if [ -n "${PORT:-}" ]; then keep uptime python3 -m ops.uptime; fi

# every hour: HTTP cache trim, raw-data retention, freed pages back to the disk, WAL files cut back (ops/health.py);
# every 10 min one log line with memory per process and the size of every database, so the trend shows on Render
# 9.11. (audit P9): first pass after HOURLY_FIRST_S (10 min), not an hour: with 20+ deploys a day a loop that sleeps
# an hour first never got its turn, and the hype_signals slimming + compaction now live only here (under the heavy lock)
# 11.11. (Jure: "NIŠTA ne briši bez moje potvrde"): right after it, the disk report (ops/diskreport.py, its own
# low-priority process so the CPU guard may pause it; the upkeep above is protected): read-only, at the first pass after
# a deploy and once a day from 06:30 Zagreb, never 01-06; otherwise it ends at once. One "disk izvještaj" block in the log.
# 11.11. (Jure: "ništa se stvarno ne briše bez moje potvrde nakon što vidim brojke"): then the retention of live_trades
# and the Telegram text (ops/retencija.py, low priority): the hourly aggregate of live_trades every pass, the measurement
# ("što BI obrisao i koliko MB") at the first pass after a deploy and daily from 06:30; it deletes only behind the
# owner switches live_trades_retention / tg_text_retention, inside 01-06 Zagreb, under the heavy-job lock.
( sleep "${HOURLY_FIRST_S:-600}"; while true; do python3 -m ops.heavy -m ops.health --hourly || echo "održavanje nije uspjelo"; low python3 -m ops.diskreport --auto || echo "disk izvještaj nije uspio"; low python3 -m ops.retencija --auto || echo "retencija nije uspjela"; sleep 3600; done ) &
# 15.11. (Jure: "Arhiviraj onda dok ima prostora na disku"; ops/arhiva.py, owner switch arhiva_mikrokapova): rows of
# microcap and rugged tokens move from the live databases into .gz archives on the data disk (copy, verify, gzip,
# verify, then delete), only 01-06 Zagreb, once a night, the heavy-job lock per table, low priority (the CPU guard may
# pause it). Switch off: the night's plan only (output/arhiva_plan.md). Its own loop: a night's move must not hold the
# hourly upkeep above. Outside the window a pass ends at once.
( sleep "${ARHIVA_FIRST_S:-900}"; while true; do low python3 run_arhiva.py --auto || echo "arhiva nije uspjela"; sleep 1800; done ) &
# (every minute for the first 10 minutes: the start, when everything loads at once, is where memory peaks)
# 9.11.: every minute the memory watchdog (ops/health.watchdog: one process over MEM_KILL_MB is stopped and restarted
# by keep, instead of Render killing the whole service at 2 GiB); the log line every 10 min (every minute at the start)
( i=0; while true; do if [ $i -le 10 ] || [ $((i % 10)) -eq 0 ]; then python3 -m ops.health || true; else python3 -m ops.health --quiet || true; fi; i=$((i+1)); sleep 60; done ) &
# rugged tokens out of hype.db (rugfilter/archive.py): 2 min after every start, then hourly. Not tied to the hourly
# upkeep above: deploys restart the service more often than once an hour, and that loop sleeps first.
( sleep 120; while true; do python3 -m ops.heavy -m rugfilter.archive || true; sleep 3600; done ) &

# recommended tokens kept fresh (run_top.py, topcheck/): every 3 min the top 20 Natjecanje suggestions get the
# market state (pumpa / pad uz oporavak / pada / stabilno) and the mandatory rug check (RugCheck + Jupiter sell test,
# free; full Helius rug filter at most every 12 h per token, 30 a day). A short process per pass: RugCheck reports can
# be 2 MB of JSON, and a process that ends gives that memory back.
( sleep 150; while true; do low python3 run_top.py once || echo "topcheck nije uspio"; sleep "${TOP_EVERY_S:-180}"; done ) &

# 10.11. (Jure: skener tržišta bez callera; scan/, flag market_scan G11): every SCAN_EVERY_S (150 s) one short pass:
# pump.fun / PumpSwap / Raydium tokens from what the bot already stores (PumpPortal migrations and trades, hype scan,
# KOL graduates), DexScreener (free) and a few GeckoTerminal pages; the copy loop's filters + fees / rug / stage; every
# candidate that passes is measured in shadow per source (caller, wallet, scan, beta). It never buys, in any mode.
# Flag off: the pass ends at once (no database, no network, no log line). Day caps in scan/config.json: Helius 5000
# credits, GeckoTerminal 150 calls, X $0.30. The 15-min meta refresh takes the heavy-job lock only when it is free.
( sleep 420; while true; do low python3 run_scan.py once || echo "skener tržišta nije uspio"; sleep "${SCAN_EVERY_S:-150}"; done ) &

# calendar + DexScreener event tokens every CALENDAR_EVERY_H hours (paper reads the newest dex-*.json)
# 9.11. 21:40 (Jure: "brave zakaži za iza ponoć"): --night = waits for the night window (ops/heavy.NIGHT, 01-06
# Zagreb) before taking the heavy-job lock. The calendar used to block the KOL round 2-3 min at EVERY start (20+
# deploys a day) and the whole set below (wallets score, dugo, learn) held the single CPU during the day.
(
  while true; do
    python3 -m ops.heavy --night run_calendar.py --days 14 --top 40 >/dev/null || echo "kalendar nije uspio"
    python3 -m ops.heavy --night run_dex.py scan --min-liq 5000 >/dev/null || echo "dex scan nije uspio"
    sleep $(( ${CALENDAR_EVERY_H:-6} * 3600 ))
  done
) &

# pre-event watch: tokens of events in the next 14 days, DexScreener snapshot every hour, buyers via Helius
# every 6 h (~10 credits per token, capped by --credits), correlation with the event approaching -> watch.db
# 15.11. navečer: in a loop, so a run that ended at once under the owner switch fokus_midcap starts again (10 min) once
# he turns it off; while it runs normally it never ends
(
  sleep 900   # first calendar + dex scan must exist
  while true; do low python3 run_watch.py run --every-min "${WATCH_EVERY_MIN:-60}" --credits "${WATCH_RUN_CREDITS:-3000}" >/dev/null; sleep 600; done
) &

# Helius Developer plan: new smart wallets once a day (early buyers of recent winners, scored by PnL)
(
  while true; do
    python3 -m ops.heavy --night run_hype.py learn --auto 5 >/dev/null || echo "learn nije uspio"
    sleep 86400
  done
) &

# wallet registry: every WALLETS_EVERY_H hours (default 3) pull wallets from all analyses, then score the queue.
# score stops at --credits per run and at WALLET_CREDIT_SHARE of the monthly Helius credits (default 15% = 1.5M)
(
  sleep 600   # let the first hype learn finish so its smart wallets are imported
  while true; do
    # 9.11. 21:40: harvest + score (Helius credits, minutes of CPU) only in the night window (--night); the proven
    # list and the copy list are recomputed right after them, so they follow the nightly scores
    python3 -m ops.heavy --night run_wallets.py harvest --feeds --tokens 15 >/dev/null || echo "wallets harvest nije uspio"
    # 9.11. (Jure): 1000 novčanika / 12.000 kredita svaka 3 h davalo je 9 profitabilnih od 100 bodovanih; pola toga
    python3 -m ops.heavy --night run_wallets.py score --credits "${WALLETS_RUN_CREDITS:-6000}" --max "${WALLETS_RUN_MAX:-500}" >/dev/null || echo "wallets score nije uspio"
    python3 -m ops.heavy run_wallets.py dokazani || echo "wallets dokazani nije uspio"   # 9.11.: proven-twice list
    # 11.11. (Jure): rang za kopiranje (wallets/rang.py, DB reads only); the first run logs "prije ... / poslije ..."
    python3 -m ops.heavy run_wallets.py rang || echo "wallets rang nije uspio"
    python3 -m ops.heavy run_wallets.py copy >/dev/null || true
    sleep $(( ${WALLETS_EVERY_H:-3} * 3600 ))   # 7.11. (Jure): fresher copy list; the credit share cap still holds
  done
) &
# 9.11. (audit): the proven-twice list (first source of the Autopilot's auto pick) and the copy list are DB reads
# only (no Helius), but in the loop above they sat behind harvest/score --night and so ran once a night; by day
# our wallets' closed copies still change, so they get their own WALLETS_EVERY_H loop (the night loop keeps its
# pass right after the scores)
(
  sleep 1200
  while true; do
    # 16.11. (wallets/kopija.py): the PAID refresh of the proven wallets' trades (the scorer is off under fokus_midcap, so
    # "dokazan dvaput" and the copy measurement go stale). Does nothing and calls nothing unless the owner sets
    # wallets/config.json "kopija" osvjezi true (default false); then at most kredita_dan Helius credits a day.
    python3 -m ops.heavy run_wallets.py osvjezi || echo "wallets osvjezi nije uspio"
    python3 -m ops.heavy run_wallets.py dokazani || echo "wallets dokazani nije uspio"
    python3 -m ops.heavy run_wallets.py rang || echo "wallets rang nije uspio"
    python3 -m ops.heavy run_wallets.py copy >/dev/null || true
    sleep $(( ${WALLETS_EVERY_H:-3} * 3600 ))
  done
) &
# 19.11. (vlasnik: "povijesni profit i gubitak za sve novčanike ... što više novčanika, posebno rani kupci tokena koji su
# skočili"; wallets/povijest.py): the history queue (pump-group members, bundles, early buyers of the pumps, long
# holders, the old registry), scored by the existing scorer into wallets.db. Helius at most wallets/config.json
# "povijest" kredita_dan (60k) a UTC day, 5 pages a wallet, never past WALLET_CREDIT_SHARE of the month. Night: under
# the heavy lock (--night, 01-06 Zagreb), each pass at most 60 min, hourly while the day cap lasts. Day: every
# POVIJEST_DAY_S (2 h) a short pass WITHOUT the heavy lock (network bound), at most 5 min and 40 % of the day cap.
( sleep "${POVIJEST_FIRST_S:-1800}"; while true; do python3 -m ops.heavy --night run_wallets.py povijest --kind night || echo "novčanici povijest (noć) nisu uspjeli"; sleep 3600; done ) &
( sleep "${POVIJEST_DAY_FIRST_S:-2400}"; while true; do low python3 run_wallets.py povijest --kind day || echo "novčanici povijest (dan) nisu uspjeli"; sleep "${POVIJEST_DAY_S:-7200}"; done ) &
# 10.11. (Grok MCP audit 9): sale amounts missing in hype.db chain_trades (sol NULL) read from the transaction itself
# (wallets/solfill.py, one Helius getTransaction each): night window only (--night, 01-06 Zagreb), at most
# SOLFILL_MAX_NIGHT (200) calls a night, counted by the job itself, so the hourly tries after the first find it spent
( sleep 1500; while true; do python3 -m ops.heavy --night -m wallets.solfill || echo "solfill nije uspio"; sleep 3600; done ) &

# 10.11. (Jure, flag group_discovery, kol/groupdisc.py): caller crews and hidden wallet lists, shadow only. The full pass
# in the night window (--night, 01-06 Zagreb; at most once in 20 h however often we deploy): caller groups from kol.db,
# Helius for the first 30 min of called tokens under 100k (at most GROUPS_NIGHT_CREDITS a pass, default 3000), wallet
# groups, results. Every 15 min a cheap pass on our databases (no Helius by default). Flag off: both end at once.
( sleep 1800; while true; do python3 -m ops.heavy --night -m kol.groupdisc night --credits "${GROUPS_NIGHT_CREDITS:-3000}" || echo "grupe (noć) nisu uspjele"; sleep 3600; done ) &
( sleep 960; while true; do low python3 -m kol.groupdisc incr || echo "grupe (15 min) nisu uspjele"; sleep 900; done ) &

# 10.11. (Jure, flag insider_copy G14, kol/precall.py): pre-call insiders. Every 15 min a cheap pass: new pump.fun
# launches priced by DexScreener at +10/+30/+90 min (free; at most 40 calls a pass, 4000 a day; a token at 10k goes to
# the market scanner as final_stretch, never bought), fresh calls and their buyers from our databases, the copy step
# (shadow lines; paper: the demo account follows the confirmed wallets). In the night window the Helius windows before
# the calls (INSIDERS_NIGHT_CREDITS, default 3000 a pass) and the wallet analysis. Flag off: both end at once.
( sleep 2100; while true; do python3 -m ops.heavy --night -m kol.precall night --credits "${INSIDERS_NIGHT_CREDITS:-3000}" || echo "insajderi (noć) nisu uspjeli"; sleep 3600; done ) &
( sleep 1020; while true; do low python3 -m kol.precall incr || echo "insajderi (15 min) nisu uspjeli"; sleep 900; done ) &

# 11.11. (Jure, flag pre_shill G15, kol/preshill.py): wallets that buy before the paid shill network, shadow only. The
# night pass (--night, 01-06 Zagreb; at most once in 20 h): the chain check of the big caller groups, the network's
# tokens of 14 days, Helius for the 6 h before its first call and the candidates' sells (PRESHILL_NIGHT_CREDITS, default
# 3000 a pass), the wallet analysis. Every 30 min a cheap pass: our databases, the newest page of the 8 best wallets
# (PRESHILL_POLL_CREDITS a day, default 1000), signals, the network's calls as exit, results. Flag off: both end at once.
( sleep 2400; while true; do python3 -m ops.heavy --night -m kol.preshill night --credits "${PRESHILL_NIGHT_CREDITS:-3000}" || echo "shill mreža (noć) nije uspjela"; sleep 3600; done ) &
( sleep 1080; while true; do low python3 -m kol.preshill incr --credits "${PRESHILL_POLL_CREDITS:-1000}" || echo "shill mreža (30 min) nije uspjela"; sleep 1800; done ) &

# 10.11. (Jure, Hope research, option 1): one read-only run after the deploy, ~120 Helius pages (~1.2k credits);
# writes DATA_DIR/research/hope-20261110.* (MCP get_research) and a .done marker, so later restarts skip it
( sleep "${RESEARCH_FIRST_S:-240}"; python3 -m ops.heavy -m research.hope || echo "research hope nije uspio"; python3 -m research.hope_report || true ) &

# 10.11. (Jure, flag range_dca): range + DCA data (rangedca/, run_range.py), a short process every RANGE_EVERY_S:
# DexScreener snapshots of the range candidates the hype scan does not snapshot itself (free), every 5 min the ranges
# from the minute series, at most RANGE_GT_DAY (60) GeckoTerminal seeds a day, Helius only for open range positions
# (RANGE_HELIUS_CREDITS_DAY 3000, log-only unless RANGE_HOLDER_RULE=act). Flag off: it reads the flag and ends.
# The backtest over the data we have, nightly (01-06 Zagreb) -> output/range-backtest-*.{json,md} and the log.
# 11.11. (flags range_market G20 / event_tokens G19): the same pass also keeps the market watchlist (rangedca/market.py):
# up to RANGE_MARKET_MAX (400) bonded tokens, DexScreener snapshots every 5 / 15 min inside RANGE_MKT_DEX_DAY (3000) and
# the other per-source day caps, one cost line per source a day. Both flags off: nothing of it runs.
# 12.11. (nalog 3): every watched token with liquidity >= $15k at least every 5 min, also under 30k (measured only,
# never bought); RANGE_MKT_DEX_DAY default 6500 (rangedca/market.py: the worst case of a full list).
# 12.11. popodne (owner, točka 1: after deploy #156 no range pass for ~6 min, every candidate "5-minutni podaci nisu
# svježi"): the first pass RANGE_FIRST_S (30 s, was 270 s) after a start, then every RANGE_EVERY_S counted from the start
# of a pass (deadline, not 60 s after its end: no drift), at least 5 s apart; run_range.py catches up after a gap itself
( sleep "${RANGE_FIRST_S:-30}"; while true; do r0=$(date +%s); low python3 run_range.py once || echo "range nije uspio"; rs=$(( ${RANGE_EVERY_S:-60} - $(date +%s) + r0 )); [ "$rs" -lt 5 ] && rs=5; sleep "$rs"; done ) &
( sleep 900; while true; do python3 -m ops.heavy --night run_range.py backtest || echo "range backtest nije uspio"; sleep 86400; done ) &

# 11.11. (Jure, flag event_tokens G19, topics/): Grok's event topics (MCP submit_event_topic) and their tokens, a short
# process every TOPICS_EVERY_S: catch-up string matching of stored launches (the PumpPortal feed matches new tokens in
# real time itself), one DexScreener search per active topic every 10 min (TOPICS_DEX_DAY 1200), Birdeye only with its
# key (TOPICS_BIRDEYE_DAY 100), roles main / clone / rug, the price 24 h before / at / after the event (GeckoTerminal
# only for a missing point, TOPICS_GT_DAY 20). Flag off: it reads the flag and ends.
( sleep 330; while true; do low python3 run_topics.py once || echo "eventi nisu uspjeli"; sleep "${TOPICS_EVERY_S:-120}"; done ) &

# 11.11. (Jure: "real-time zone alarm na Grok Bot", data flag zonewatch G21, zonewatch/): one small process (~20 MB) at
# low priority, a pass every ZONEWATCH_EVERY_S (30 s): zones of the active ranges + the zones Grok arms (MCP arm_zone,
# HOPE seeded once), numbers from the snapshots range.db / hype.db already hold, DexScreener (free, 30 tokens a request)
# only for tokens within 10 % of a zone or armed without a fresh snapshot, at most 4 requests a pass and
# ZONEWATCH_DEX_DAY (3000) a day; an alarm (zone_enter / zone_exit / stop_hit / top_hit, team_catalyst rows of
# events.db) is POSTed to GROKBOT_WEBHOOK_URL. Time-sensitive, so not under ops.heavy --night. Flag off: nothing runs.
low keep zonewatch python3 run_zonewatch.py loop

# 11.11. (Jure, flag momentum_scalp): momentum data (momentum/, run_momentum.py), a short process every MOM_EVERY_S:
# DexScreener minute snapshots of 60 tokens (free), PumpPortal's unique buyers (free), GeckoTerminal /pools/multi only
# for prequalified tokens (MOM_GT_DAY 100), Helius top 10 only for a full match (MOM_HELIUS_DAY 2000 credits); the
# signals' base rate and Grok's EV-gate calibration outcomes. Flag off: it reads the flag and ends. The backtest over
# the last 7 days of candles, nightly (01-06 Zagreb, MOM_BT_GT 60 GeckoTerminal requests) -> output/momentum-backtest-*.
( sleep 300; while true; do low python3 run_momentum.py once || echo "momentum nije uspio"; sleep "${MOM_EVERY_S:-60}"; done ) &
( sleep 960; while true; do python3 -m ops.heavy --night run_momentum.py backtest || echo "momentum backtest nije uspio"; sleep 86400; done ) &

# 11.11. (Jure, flag proposals G21): Prijedlozi (proposals/, run_proposals.py), a short low-priority process every
# PROPOSALS_EVERY_S (150 s): the merged list over every strategy on ui/kandidati (DexScreener free), proposals.db sync,
# near misses, after-outcomes from the minute data we keep (+ at most PROPOSALS_DEX_DAY free DexScreener batches a day).
# The UI and the MCP only read proposals.db. Nightly (01-06 Zagreb, once a day) the callers' quick-exit benchmark from
# minute.db. Flag off: both read the flag and end.
( sleep 330; while true; do low python3 run_proposals.py once || echo "prijedlozi nisu uspjeli"; sleep "${PROPOSALS_EVERY_S:-150}"; done ) &
( sleep 1110; while true; do python3 -m ops.heavy --night run_proposals.py night || echo "prijedlozi (noć) nisu uspjeli"; sleep 3600; done ) &

# 14.11. (owner: "zaprati sve influencere koji su u zadnjih 5 poziva imali barem 10% profita ... i volete isto ... jesmo
# li u profitu nakon fijeva", kol/zadnjih5.py): the walk-forward of influencers and wallets over our own 30 days (minute.db,
# wallets / hype / events.db; read-only, no API call), ZADNJIH5_FIRST_S (300 s) after a start under the heavy-job lock
# (nice 10; skipped when the last run is younger than 3 h), then nightly (01-06 Zagreb, once a day). Writes
# output/zadnjih5.json (MCP get_last5) and "zadnjih 5: " lines; follows only behind the owner switch prati_zadnjih5 or,
# per type, when its walk-forward EV after costs is > 0 on 30+ trades. Trading never waits for it.
( sleep "${ZADNJIH5_FIRST_S:-300}"; python3 -m ops.heavy -m kol.zadnjih5 once || echo "zadnjih 5 nije uspio"; while true; do sleep 3600; python3 -m ops.heavy --night -m kol.zadnjih5 night || echo "zadnjih 5 (noć) nije uspio"; done ) &

# 15.11. (owner: "nauči iz podataka najbolji stop loss i najbolji take profit, po izvoru ... OpenAI neka to pregleda",
# izlazi/, run_izlazi.py): every followed / copyable wallet, influencer, crew and automatic strategy gets its own exit
# (stop, grace, TP1, trailing, time stop, mirror) from our own price paths (minute.db, range/momentum gt_candles,
# hype.db prints and snapshots, events.db ticks; read-only, no API call), walk-forward 70/30 with shrinkage toward its
# kind; izlazi.db on DATA_DIR. Nightly (01-06 Zagreb, once a Zagreb day) under the heavy-job lock (nice 10); the demo
# uses it for new positions at once, real money only when proven out of sample (league/exitplan.quick_cover).
( sleep "${IZLAZI_FIRST_S:-1290}"; while true; do python3 -m ops.heavy --night run_izlazi.py night || echo "naučeni izlazi (noć) nisu uspjeli"; sleep 3600; done ) &

# 15.11. (vlasnik: "hitno pronađi profitabilnu strategiju kombiniranjem profitabilnih novčanika i influencera ... kreni
# odmah", konsenzus/, run_konsenzus.py): X influencers, Telegram channels and tracked wallets scored point-in-time,
# candidates (top sources, 2+ independent sources, wallet + KOL, Telegram only) walk-forward with an untouched holdout;
# read-only, no API call. KONSENZUS_FIRST_S (420 s) after a start under the heavy-job lock (nice 10, the CPU guard's
# job class, a 20-min budget; skipped when the last run is younger than 3 h), then nightly (01-06 Zagreb, once a day).
# Writes konsenzus.db (DATA_DIR), output/konsenzus.md and "konsenzus: " lines; the demo entries (flag konsenzus) read it.
( sleep "${KONSENZUS_FIRST_S:-420}"; python3 -m ops.heavy run_konsenzus.py once || echo "konsenzus nije uspio"; while true; do sleep 3600; python3 -m ops.heavy --night run_konsenzus.py night || echo "konsenzus (noć) nije uspio"; done ) &

# 15.11. (vlasnik: "Nastavi koristiti influencere, posebno u grupama ... insajdere i botove koji kupuju prije poziva ...
# koji su novčanici prodavali u skok i jesu li kupili danima prije ... dio resursa za ovo, veći dio na midcapove";
# insajderi/, run_insajderi.py): an explicit, budgeted exception of fokus_midcap (ops/fokus.EXCEPTIONS). A Helius day
# cap (INSAJDERI: 16 % of what the old insider / crew / shill / wallet jobs used, usage.db; 3500 without a measurement),
# nice 10 under the heavy lock. INSAJDERI_FIRST_S (600 s) after a start: the existing data, Helius at most 40 % of the
# cap (skipped when the last pass is younger than 3 h); nightly 01-06 Zagreb (--night, once in 20 h) the rest of the
# cap; every 3 h a light pass over the new calls (at most 10 % of the cap). Writes insajderi.db, output/insajderi.md,
# output/pametni_novac.md and "insajderi2: " lines; the demo (flag insajderi2, league/auto.loop) reads the groups.
# 18.11. (vijeće, prijedlog #845, prihvatili OpenAI i Grok; pokus 7 dana, do 25.11.): Insajderi 2.0 are demo-only (no
# real-money decision reads them: insider copy -2.7 % a trade, n=1043), yet took ~40 % of the tool's Helius credits and
# held the heavy-job lock for hours a day (the midcap candles loop waited 52 min behind it on 18.11.). So: ONE pass a
# night (ops.heavy --night, 01-06 CET), no pass at every start, no pass every 3 h; the day cap is 15,000 credits
# (insajderi/config.json). Nothing is deleted. Back as before: INSAJDERI_ONCE=1 and INSAJDERI_INCR=1 (and the config).
# 19.11. (vlasnik: "svaki dan želim novčanike ... svi resursi u pronalaženje novčanika koji kupuju PRIJE pumpe i prodaju
# u pumpu"): reversed. Insajderi 2.0 is the daily wallet job again: the pass after a start (INSAJDERI_ONCE default 1,
# at most 40 % of the cap), the night pass, the light pass every 3 h (INSAJDERI_INCR default 1, at most 10 %); the day
# cap is 60,000 credits (the monthly plan 10M). Helius goes to pumps peaking >= 15M first, then 2-15M, then calls
# (insajderi/chain.order_key); the list and the copy test: insajderi/prijepumpe.py, output/novcanici_prije_pumpe.md,
# one line "novčanici prije pumpe: ...". The influencers' side-wallet search stays paused (kol_helius_share 0).
( sleep "${INSAJDERI_FIRST_S:-600}"; if [ "${INSAJDERI_ONCE:-1}" = "1" ]; then python3 -m ops.heavy run_insajderi.py once || echo "insajderi2 nije uspio"; fi; while true; do sleep 3600; python3 -m ops.heavy --night run_insajderi.py night || echo "insajderi2 (noć) nije uspio"; done ) &
if [ "${INSAJDERI_INCR:-1}" = "1" ]; then
( sleep "${INSAJDERI_INCR_FIRST_S:-3600}"; while true; do python3 -m ops.heavy run_insajderi.py incr || echo "insajderi2 (3 h) nije uspio"; sleep "${INSAJDERI_INCR_S:-10800}"; done ) &
# 19.11. (vlasnik: "dodaj BNB chain i praćenje novčanika"; bnb/, run_bnb.py): BSC pumps, who bought before and sold
# into them, the class "kupuje prije pumpe" (insajderi/prijepumpe.classify), the measurement of their new buys (bnb.db
# bnb_mjera); free sources only (GeckoTerminal, DexScreener, public BSC RPC, Binance market data), analysis only, never
# trades. Low priority, NOT under the heavy lock (network bound), 30 min after a start then every 3 h, a pass bounded by
# bnb/config.json pass_max_s.pass and calls_day. On unless BNB_ON=0 (20.11., see the export above; off: the loop only sleeps, no bnb.db).
# One line "bnb: ..." and output/bnb_novcanici.md.
( sleep "${BNB_FIRST_S:-1800}"; while true; do if [ "$BNB_ON" = "1" ]; then nice -n 10 python3 run_bnb.py pass || echo "bnb nije uspio"; fi; sleep "${BNB_EVERY_S:-10800}"; done ) &
fi

# 15.11. (vlasnik: "Slažem se s prijedlogom koraka za plan makroinfluencera s dopunama kritičara"; makroinf/,
# run_makroinf.py): the PILOT of 50 macro accounts starts soon after a deploy (MAKROINF_FIRST_S, 480 s; the owner wants
# the work to start at once, it is small) and continues in short rounds every MAKROINF_KRUG_S (600 s) at low priority
# (nice 10, network bound: twitterapi.io, OpenAI gpt-5-mini, CoinGecko; NOT under the heavy lock, a round is at most
# ~7 min; while the pilot has paid work left the round answers 3 and the next one starts a minute later): the backfill (monthly quotas over 12 months + the last 100 posts) under the one-off cap 5 $, its
# classification under 4 $, then the day's posts, deletion checks (+1 / +7 / +30 d) and the light scoring under
# 0,50 $ / 0,25 $ a day; one line "makroinf: sat: ..." an hour. The heavy re-scoring (clusters, the walk-forward of the
# index, the quality check when missing) nightly 01-06 Zagreb (--night, once in 20 h). An explicit, budgeted exception
# of fokus_midcap (ops/fokus.EXCEPTIONS). Writes makroinf.db, output/makroinf.md, output/makroinf_provjera.md.
# 15.11. navečer (the owner's order, makroinf/discover.py): after the pilot the expansion to 300-500 accounts (discovery,
# 18 months of history each) under its own one-off caps (40 $ / 15 $), the daily fetch of every account and the topics
# under 1,50 $ / 0,50 $ a day; while the expansion has paid work under its caps the round answers 3 as in the pilot.
( sleep "${MAKROINF_FIRST_S:-480}"; while true; do low python3 run_makroinf.py krug; rc=$?; if [ "$rc" = 3 ]; then sleep 60; else [ "$rc" = 0 ] || echo "makroinf krug nije uspio"; sleep "${MAKROINF_KRUG_S:-600}"; fi; done ) &
( sleep 3300; while true; do python3 -m ops.heavy --night run_makroinf.py noc || echo "makroinf (noć) nije uspio"; sleep 3600; done ) &

# 15.11. (vlasnik: "token koji ide gore-dolje tijekom dana ... 50 puta dnevno, 1-2 $ na svakom", oscilator/,
# run_oscilator.py): per token-day the zigzag swings larger than the round-trip cost at 0.1-1 SOL + 1 $ net, then the
# walk-forward (top 10 of day D traded on D+1 with the scalp rule) per size and the range scalp on the same token-days;
# read-only on the minute data we hold, no API call. OSCILATOR_FIRST_S (300 s) after a start under the heavy-job lock
# (nice 10, the CPU guard's job class, a 15-min budget OSC_BUDGET_S; skipped when the last run is younger than 3 h),
# then nightly (01-06 Zagreb, once a day). Writes oscilator.db (DATA_DIR), output/oscilator.md and "oscilator: " lines;
# the demo trades (flag oscilator, league/auto.fast_loop) read today's top 10 from it.
( sleep "${OSCILATOR_FIRST_S:-300}"; python3 -m ops.heavy run_oscilator.py once || echo "oscilator nije uspio"; while true; do sleep 3600; python3 -m ops.heavy --night run_oscilator.py night || echo "oscilator (noć) nije uspio"; done ) &

# 15.11. (vlasnik: "Useless, Troll i slično: kad nađu dno ... 5-10 % u kratkom vremenu ... hvataj range velikih
# tokena"; "testiraj povijesno, NE računajući velike padove Bitcoina"; veliki/, run_veliki.py): the list "veliki"
# (MC 20M+, liquidity 500k+, 14+ days, volume 500k+, USELESS / TROLL on their real mints) and its 15m / 1h candles
# (GeckoTerminal, incremental, the shared budget) VELIKI_LIST_FIRST_S (90 s) after a start, then every 3 h, low
# priority but outside the heavy lock (network bound; the demo trades as soon as zones exist). The backtest (grid,
# walk-forward per size, with and without BTC crashes) VELIKI_FIRST_S (420 s) after a start under the heavy-job lock
# (nice 10, a 15-min budget VEL_BUDGET_S, skipped when the last run is younger than 3 h), then nightly (01-06 Zagreb,
# once a day). Writes veliki.db (DATA_DIR), output/veliki.md and "veliki: " lines; the demo (flag veliki_range,
# league/auto.fast_loop) reads the list and the live rule from it.
( sleep "${VELIKI_LIST_FIRST_S:-90}"; while true; do nice -n 10 python3 run_veliki.py list || echo "veliki lista nije uspjela"; sleep 10800; done ) &
# 15.11. navečer (coordinator: every backtest variant n=0, the 1h candles never arrived: GeckoTerminal 429 and the pass
# gave up at the first refusal, 3 h until the next): every VEL_CANDLES_EVERY_S (15 min) the list's candles only: our own
# 15m / 1h bars from veliki/live's DexScreener polls (free; GeckoTerminal's candle replaces ours when it arrives), then
# GeckoTerminal by need (1h of the top tokens first), waiting on the shared limiter instead of giving up; veliki and
# the midcap collector have the CoinGecko key's priority (event_calendar/http CG_PRIORITY). Then, while no rule is
# picked yet, the backtest again (at most once an hour, run_veliki.py once --ako-nema-pravila; veliki/live trades the
# documented default rule until then).
( sleep "${VELIKI_CANDLES_FIRST_S:-240}"; while true; do low python3 run_veliki.py candles || echo "veliki svijeće nisu uspjele"; python3 -m ops.heavy run_veliki.py once --ako-nema-pravila || true; sleep "${VEL_CANDLES_EVERY_S:-900}"; done ) &
# 15.11. navečer (owner switch fokus_midcap; veliki/midcap.py): the midcap collector, a short low-priority process every
# MIDCAP_EVERY_S (90 s, counted from the start of a pass), outside the heavy lock: DexScreener trending / boosts /
# profiles / CTO + GeckoTerminal trending + Jupiter lists every 15 min, every pass DexScreener numbers of the whole
# 2M-200M list (free, 30 a request) -> midcap.db (one row a token a pass), GeckoTerminal 15m / 1h / 1d by volume inside
# its own day cap (gt_day 4000; never the last part of veliki's key slice), RugCheck holders / LP, X momentum inside the scanner's day cap, the priority order of
# veliki/live; one "midcap: sat:" line an hour (counts, API use, MB a day). Switch off: the pass ends at once.
( sleep "${MIDCAP_FIRST_S:-120}"; while true; do r0=$(date +%s); low python3 run_veliki.py midcap || echo "midcap sakupljač nije uspio"; rs=$(( ${MIDCAP_EVERY_S:-90} - $(date +%s) + r0 )); [ "$rs" -lt 10 ] && rs=10; sleep "$rs"; done ) &
( sleep "${VELIKI_FIRST_S:-420}"; python3 -m ops.heavy run_veliki.py once || echo "veliki nije uspio"; while true; do sleep 3600; python3 -m ops.heavy --night run_veliki.py night || echo "veliki (noć) nije uspio"; done ) &
# 16.11. (vlasnik: "želim više podataka koji će pomoći da postanemo profitabilni"; veliki/replay.py): the intraday rule
# trades real money without history, so it is replayed over EVERY midcap collector member's 15m candles (midcap.db
# only: no network, no paid call): the live exits, a small pre-declared grid of variants, walk-forward (60 % / 40 %),
# each trade tagged (MC, zone, hour, BTC, macro, the token's answer to BTC) -> where the rule makes or loses money.
# REPLAY_FIRST_S (900 s) after a start only when no result exists yet, then nightly (01-06 Zagreb, once a day), under
# the heavy-job lock (nice 10), a 5-min budget REPLAY_BUDGET_S; one line "veliki replay: ..." and midcap.db kv replay
# (the morning report and /strategije show it).
( sleep "${REPLAY_FIRST_S:-900}"; python3 -m ops.heavy run_veliki.py replay --ako-nema || echo "veliki replay nije uspio"; while true; do sleep 3600; python3 -m ops.heavy --night run_veliki.py replay --night || echo "veliki replay (noć) nije uspio"; done ) &
# 18.11. (vlasnik: "da program što više nauči iz tih mid-capova ... da nauči kombinirati te faktore ... želim da demo
# što prije bude profitabilan"; veliki/nauceno.py): the shadow book replayed over the midcaps' candles and the
# walk-forward of what it has learned (history + the live book). Local databases only, ~1 min, under the heavy-job
# lock: 8.5 min after a start (18.11. 12:25: at 20 min it queued 25+ min behind run_insajderi.py once, which starts at
# 10 min), then every 6 h. One line "veliki naučeno: ...", its own file nauceno.db.
( sleep "${NAUCENO_FIRST_S:-510}"; while true; do python3 -m ops.heavy run_veliki.py nauceno || echo "veliki naučeno nije uspio"; sleep "${NAUCENO_EVERY_S:-21600}"; done ) &
# 18.11. (vlasnik: "Twitter API kredite koristiš za ove mid-capove ... tko agresivno gura ... velike influencere koji
# imaju veliku moć poziva"; veliki/moc.py): the posts already bought + one X search per midcap a week (at most ~$2.50 a
# pass, hard cap MOC_DAY_USD 4 $ a UTC day), the price after each post from our candles. 9.5 min after a start (ahead
# of run_insajderi.py once, like the learner above), then every 3 h (18.11.: one pass searches ~35 tokens in its
# 240 s, 176 are queued; a token is searched once in 7 days, so later passes cost nothing), under the heavy-job lock. One line "moć poziva: ...", its own file moc.db.
( sleep "${MOC_FIRST_S:-570}"; while true; do python3 -m ops.heavy run_veliki.py moc || echo "moć poziva nije uspjela"; sleep "${MOC_EVERY_S:-10800}"; done ) &
# 16.11. (vlasnik: "Objasni mi kako ovdje postoji profitabilni wallet, a mi nemamo profitabilnu strategiju"; wallets/
# kopija.py): what WE would have earned copying the "dokazan dvaput" wallets: picked on the older 60 % of the stored
# days, their buys of the newer 40 % taken 30 / 60 / 180 s later at the stored prices, sold after their sale / at a stop
# / after 24 h, minus the real round trip at 0.1 SOL. Databases only (wallets.db trades + the stored price series): no
# network, no paid call, no account trades. KOPIJA_FIRST_S (1200 s) after a start only when no result exists yet, then
# nightly (01-06 Zagreb, once a day), under the heavy-job lock (nice 10), a 5-min budget KOPIJA_BUDGET_S; one line
# "novčanici kopija: ..." and wallets.db copy_rank_kv "kopija" (the morning report and /strategije show it). Not a
# microcap job of ops/fokus.OFF: it runs under the owner switch fokus_midcap too.
( sleep "${KOPIJA_FIRST_S:-1200}"; python3 -m ops.heavy run_wallets.py kopija --ako-nema || echo "novčanici kopija nije uspjela"; while true; do sleep 3600; python3 -m ops.heavy --night run_wallets.py kopija --night || echo "novčanici kopija (noć) nije uspjela"; done ) &
# 15.11. (vlasnik: "insajderi drže velik dio ponude? oprez — ali to su često BURZE ... kad dio ponude ode na novčanik
# burze, a token tamo još nije listan, to je jak signal"; holderi/, run_holderi.py): every HOLDERI_EVERY_S (10 min), a
# short low-priority process outside the heavy lock, only with the owner switch fokus_midcap: the top 20 holders of the
# midcaps (RugCheck free; top 50 every 6 h = the transfer watch), classes and insider share without exchanges / LP, the
# moves of supply traced to exchange wallets (Helius inside holderi/config.json helius_credits_day, 15000), the
# exchanges' free market lists once a day -> PRE-LISTING signals (loud log line + Telegram), the caution / listing
# components of veliki/prioritet, the profitable holders' buys; one "holderi: sat:" line an hour with the cost.
( sleep "${HOLDERI_FIRST_S:-300}"; while true; do low python3 run_holderi.py pass || echo "holderi nisu uspjeli"; sleep "${HOLDERI_EVERY_S:-600}"; done ) &

# 11.11. (Jure, flag fast_path G24): the fast path's worker (fast/, run_fast.py): every buy of a followed wallet and
# every call of a followed influencer -> fast.db queue -> five checks (rug, holders, flow, price vs the wallet's entry,
# source) and a decision within seconds, 20 at once. Time-sensitive, so a supervised process polling every 0.5 s (and
# woken by the webhooks), never under ops.heavy --night; low priority, paused last by the CPU guard. Free sources first
# (DexScreener, RugCheck), Helius only when RugCheck fails, FAST_HELIUS_DAY (20000) credits a day at most. Flag off: it
# reads the flag every 15 s and holds no thread pool. The demo trades run in run_ui (league/auto.loop).
low keep fast python3 run_fast.py loop

# 11.11. (Jure, events.db): the night batch (events/night.py) at 03:00 Zagreb, once a night: call and wallet-buy
# outcomes, never-measured calls from GeckoTerminal minute candles (600 requests a night at most), scores of callers,
# channels and wallets, groupdisc's night pass (skipped when its own loop above already ran), the range backtest
# (skipped when today's exists), early wallets, retention and the size line; Helius at most 5000 credits a night.
# Tried every 30 min under the heavy lock inside the night window; before 03:00 or once done it ends at once.
( sleep 2100; while true; do python3 -m ops.heavy --night run_events.py night || echo "noćna obrada događaja nije uspjela"; sleep 1800; done ) &

# KOL calls on X: copy tweets the bot already paid for, measure price/volume after each call (GeckoTerminal, free),
# Helius flows around the strongest calls (kol/config.json flows_per_day), call power per KOL -> /kol and kol_group
keep kol python3 run_kol.py loop --every "${KOL_EVERY_MIN:-20}"
# 9.11. (Jure: "napuni podatke za ekipe i drži ih svježima"): minute candles after every call, own process and own
# minute.db (kol/minute.py); backlog first (crews before single callers), then every new call as soon as it is 70 min old
low keep minute python3 run_kol.py minute-loop

# one-off KOL history (5.11.): KOL_BACKFILL_USD=28 runs run_kol.py backfill with that Apify budget once (kol.db kv
# backfill_done remembers the budget value, so later deploys do not pay again). Token list comes from kol.db itself.
# KOL_BACKFILL_AT=HH:MM (UTC) waits for that time instead (23:00 = midnight in Zagreb in winter): a deploy restarts the
# container and with it the backfill, so it is best started when nobody deploys. Without it: 25 min after start.
if [ -n "${KOL_BACKFILL_USD:-}" ]; then
  (
    # 10.11. (spojeno iz grane "veliki poslovi od ponoći", uz CLAUDE.md 01-06): without KOL_BACKFILL_AT it waits for
    # 00:05 UTC (01:05 Zagreb in winter), the start of the night window, not 25 min after a deploy in the day
    KOL_BACKFILL_AT="${KOL_BACKFILL_AT:-00:05}"
    if [ -n "${KOL_BACKFILL_AT:-}" ]; then
      python3 -c "import time, datetime as d; h, m = map(int, '${KOL_BACKFILL_AT}'.split(':')); n = d.datetime.now(d.timezone.utc); t = n.replace(hour=h, minute=m, second=0, microsecond=0); t = t if t > n else t + d.timedelta(days=1); print(f'kol backfill: čekam do {t:%Y-%m-%d %H:%M} UTC', flush=True); time.sleep((t - n).total_seconds())"
    else
      sleep 1500   # after the first KOL round, so the two do not fight for kol.db
    fi
    echo "kol backfill: u redu za bravu 'jedan težak posao odjednom' (KOL krug, učenje, ocjenjivanje walleta idu prije)"
    # KOL_BACKFILL_ARGS (5.11., 2nd round): e.g. "--winners 700 --losers 700 --kols 300 --max-age-d 180"; tokens and
    # KOLs already searched are skipped, so a bigger list pays for new ones only
    python3 -m ops.heavy --prio run_kol.py backfill --budget "$KOL_BACKFILL_USD" ${KOL_BACKFILL_ARGS:---winners 300 --losers 300 --kols 100} \
      || echo "kol backfill nije uspio"
  ) &
fi

# 19.11. (vlasnik: "Makni Telegram KOL-ove iz izračuna. Ali zadrži popis kanala, osvježen jednom tjedno, samo za broj
# pratitelja"): the Telegram call reader (run_tg.py loop), the Telethon listener, discovery, history and TGStat are
# gone. Left: the follower count of the existing channel list, a channel at most once in TG_FOLLOWERS_EVERY_D (7)
# days (tg/pratitelji.py); asked once a day, it reads only the due channels (one free t.me page each, header only).
( sleep "${TG_FOLLOWERS_FIRST_S:-2700}"; while true; do low python3 run_tg.py pratitelji || echo "telegram pratitelji nisu uspjeli"; sleep 86400; done ) &

# loops that work only now and then, each run a short process that ends and hands its memory back (run_sched.py):
#   spend on Helius/Apify every 15 min (warnings on /usage and a banner on every page), correlations every
#   CORR_EVERY_MIN (KOL groups, wallet groups, pump factors, a Claude reading once a day if ANTHROPIC_API_KEY is set),
#   once a day re-fit of hype weights and of exit rules per class (guarded, rollback), market volume every hour
low keep sched python3 run_sched.py
# morning report e-mail at REPORT_HOUR (Zagreb): reads the DBs only, one Claude call a day -> output/report-*.html
low keep report python3 run_report.py loop
# 15.11. (vlasnik: "OpenAI kao kritičar", critic/live.py): the watcher of real-money fills; every 5 s one indexed read of
# trade.db orders, 20 s after the newest live buy / sell one short child comments it (OpenAI, advice only, never trades).
# Owner switch openai_kritika off or no OPENAI_API_KEY: it looks again once a minute. The re-checks, the daily review
# and the deep session run from run_sched (above).
low keep kriticar python3 run_critic.py loop
# 18.11. (vlasnik: "Kad Grok pošalje prijedlog, Claude i OpenAI moraju biti kritični prema njemu, doraditi ga i
# prihvatiti ako se slažu ... neka alat sam sebe popravlja i uči i odlučuje u kojem smjeru ići"; vijece/, run_vijece.py):
# the council's pass, 3 min after a start and then every 15 min: Claude's four proposals stored once, the direction
# session when due (once after the deploy, weekly, when the learner's verdict changes), the waiting reviews of OpenAI
# and Claude (0.60 $ a day each: VIJECE_OPENAI_DAY_USD / VIJECE_CLAUDE_DAY_USD), the decisions; Grok reviews through
# the MCP tools when it polls (6 h, then it is decided without it). Light: it only waits on the two APIs, so no
# ops.heavy slot. Real money is never applied by the council. Lines "vijeće: ocjena / odluka / smjer". VIJECE=0: off.
( sleep "${VIJECE_FIRST_S:-180}"; while true; do low python3 run_vijece.py tick || echo "vijeće nije uspjelo"; sleep "${VIJECE_EVERY_S:-900}"; done ) &

# safer layer: older survivors (Fartcoin/Useless style) and waking-up older tokens, free sources, every 6 h,
# guarded weekly learning on the stored daily candles -> dugo.db, page Tokeni -> Dugoročni.
# A fresh process per pass, so it holds no memory in the 6 h between passes.
# 9.11. 21:40: --night (it held the lock and the CPU for 29 min every 6 h in the middle of the day)
( sleep 300; while true; do python3 -m ops.heavy --night run_dugo.py once >/dev/null || echo "dugo nije uspio"; sleep $(( ${DUGO_EVERY_MIN:-360} * 60 )); done ) &

# SimianX second opinion on the long-term list + demo test of its long signals (simianx/, needs SIMIANX_API_KEY;
# without it the pass ends at once). Light: waits on their API, so no ops.heavy slot. Real money only via /pravi-trade.
( sleep 600; while true; do low python3 run_simianx.py once || echo "simianx nije uspio"; sleep $(( ${SIMIANX_EVERY_MIN:-180} * 60 )); done ) &

keep paper python3 run_paper.py run --scan --hype-args "--deep 20"   # hype scan, demo entries/exits, daily review
# 5.11.: live buys/sells from PumpPortal (free WebSocket): tokens we watch, wallets we follow, new launches
# -> hype.db live_trades; dump alerts the demo sells on within seconds (run_paper live_exits). LIVE_OFF=1 disables.
# 10.11.: every new pump.fun token is captured by default (free event; run_live.new_tokens_on): only LIVE_NEW_TOKENS=0
# or "--no-new" in LIVE_ARGS switch it off, so LIVE_ARGS without "--new" no longer does
if [ -z "${LIVE_OFF:-}" ]; then keep live python3 run_live.py loop ${LIVE_ARGS:-}; fi
# (keep trade: started right after the UI above, 9.11.)

wait   # every loop has its own supervisor; the worker itself only ends when Render stops it
