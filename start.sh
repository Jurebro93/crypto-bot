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
( sleep "${HOURLY_FIRST_S:-600}"; while true; do python3 -m ops.heavy -m ops.health --hourly || echo "održavanje nije uspjelo"; sleep 3600; done ) &
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
(
  sleep 900   # first calendar + dex scan must exist
  low python3 run_watch.py run --every-min "${WATCH_EVERY_MIN:-60}" --credits "${WATCH_RUN_CREDITS:-3000}" >/dev/null
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
    python3 -m ops.heavy run_wallets.py dokazani || echo "wallets dokazani nije uspio"
    python3 -m ops.heavy run_wallets.py copy >/dev/null || true
    sleep $(( ${WALLETS_EVERY_H:-3} * 3600 ))
  done
) &
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

# 10.11. (Jure, Hope research, option 1): one read-only run after the deploy, ~120 Helius pages (~1.2k credits);
# writes DATA_DIR/research/hope-20261110.* (MCP get_research) and a .done marker, so later restarts skip it
( sleep "${RESEARCH_FIRST_S:-240}"; python3 -m ops.heavy -m research.hope || echo "research hope nije uspio"; python3 -m research.hope_report || true ) &

# 10.11. (Jure, flag range_dca): range + DCA data (rangedca/, run_range.py), a short process every RANGE_EVERY_S:
# DexScreener snapshots of the range candidates the hype scan does not snapshot itself (free), every 5 min the ranges
# from the minute series, at most RANGE_GT_DAY (60) GeckoTerminal seeds a day, Helius only for open range positions
# (RANGE_HELIUS_CREDITS_DAY 3000, log-only unless RANGE_HOLDER_RULE=act). Flag off: it reads the flag and ends.
# The backtest over the data we have, nightly (01-06 Zagreb) -> output/range-backtest-*.{json,md} and the log.
( sleep 270; while true; do low python3 run_range.py once || echo "range nije uspio"; sleep "${RANGE_EVERY_S:-60}"; done ) &
( sleep 900; while true; do python3 -m ops.heavy --night run_range.py backtest || echo "range backtest nije uspio"; sleep 86400; done ) &

# 11.11. (Jure, flag momentum_scalp): momentum data (momentum/, run_momentum.py), a short process every MOM_EVERY_S:
# DexScreener minute snapshots of 60 tokens (free), PumpPortal's unique buyers (free), GeckoTerminal /pools/multi only
# for prequalified tokens (MOM_GT_DAY 100), Helius top 10 only for a full match (MOM_HELIUS_DAY 2000 credits); the
# signals' base rate and Grok's EV-gate calibration outcomes. Flag off: it reads the flag and ends. The backtest over
# the last 7 days of candles, nightly (01-06 Zagreb, MOM_BT_GT 60 GeckoTerminal requests) -> output/momentum-backtest-*.
( sleep 300; while true; do low python3 run_momentum.py once || echo "momentum nije uspio"; sleep "${MOM_EVERY_S:-60}"; done ) &
( sleep 960; while true; do python3 -m ops.heavy --night run_momentum.py backtest || echo "momentum backtest nije uspio"; sleep 86400; done ) &

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

# Telegram call channels: discovery every hour, hot channels read every 30 s via t.me/s (free) -> tg.db,
# hype.db tg_mentions, and kol.db calls on the next run_kol round. TGStat (TGSTAT_TOKEN) adds paid search by CA.
keep tg python3 run_tg.py loop
# optional live listener on a Telegram account (paid option: needs a phone number), only with its secrets set
if [ -n "${TG_SESSION:-}" ] && [ -n "${TG_API_ID:-}" ]; then python3 run_tg.py telethon & fi

# loops that work only now and then, each run a short process that ends and hands its memory back (run_sched.py):
#   spend on Helius/Apify every 15 min (warnings on /usage and a banner on every page), correlations every
#   CORR_EVERY_MIN (KOL groups, wallet groups, pump factors, a Claude reading once a day if ANTHROPIC_API_KEY is set),
#   once a day re-fit of hype weights and of exit rules per class (guarded, rollback), market volume every hour
low keep sched python3 run_sched.py
# morning report e-mail at REPORT_HOUR (Zagreb): reads the DBs only, one Claude call a day -> output/report-*.html
low keep report python3 run_report.py loop

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
