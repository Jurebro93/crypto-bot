#!/usr/bin/env bash
# Render background worker: everything that must run 24/7, in one container.
# Databases, output and the HTTP cache live on the persistent disk at $DATA_DIR and are symlinked into place,
# so the code keeps its usual paths and a redeploy loses nothing.
set -u
cd "$(dirname "$0")"
DATA_DIR="${DATA_DIR:-/var/data}"
mkdir -p "$DATA_DIR/output"
for f in calendar.db hype.db paper.db rug.db wallets.db trade.db usage.db league.db market.db kol.db watch.db corr.db dugo.db tg.db koltest.db strat.db shadow.db ai.db nastoken.db public.db analytics.db topcheck.db simianx.db; do
  touch "$DATA_DIR/$f"
  ln -sfn "$DATA_DIR/$f" "$f"
done
ln -sfn "$DATA_DIR/output" output
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
keep() { local name="$1"; shift; ( while true; do "$@"; code=$?; echo "nadzor: $name završio (izlaz $code), ponovno za 30 s"; sleep 30; done ) & }
if [ -n "${PORT:-}" ]; then keep ui python3 run_ui.py --host 0.0.0.0 --port "$PORT"; fi
# 9.11. (audit P9): the real-money follower right after the UI (every loop below is backgrounded, so this only moves it
# ahead of ~20 python start-ups fighting for 0.5 CPU; the real gain is the short --startup above, so a paper entry
# from the deploy window is mirrored before max_signal_age_s runs out; it only reads paper.db/league.db/trade.db)
keep trade python3 run_trade.py follow       # mirrors paper entries/exits as real (or dry-run) swaps

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
( sleep 150; while true; do python3 run_top.py once || echo "topcheck nije uspio"; sleep "${TOP_EVERY_S:-180}"; done ) &

# calendar + DexScreener event tokens every CALENDAR_EVERY_H hours (paper reads the newest dex-*.json)
(
  while true; do
    python3 -m ops.heavy run_calendar.py --days 14 --top 40 >/dev/null || echo "kalendar nije uspio"
    python3 -m ops.heavy run_dex.py scan --min-liq 5000 >/dev/null || echo "dex scan nije uspio"
    sleep $(( ${CALENDAR_EVERY_H:-6} * 3600 ))
  done
) &

# pre-event watch: tokens of events in the next 14 days, DexScreener snapshot every hour, buyers via Helius
# every 6 h (~10 credits per token, capped by --credits), correlation with the event approaching -> watch.db
(
  sleep 900   # first calendar + dex scan must exist
  python3 run_watch.py run --every-min "${WATCH_EVERY_MIN:-60}" --credits "${WATCH_RUN_CREDITS:-3000}" >/dev/null
) &

# Helius Developer plan: new smart wallets once a day (early buyers of recent winners, scored by PnL)
(
  while true; do
    python3 -m ops.heavy run_hype.py learn --auto 5 >/dev/null || echo "learn nije uspio"
    sleep 86400
  done
) &

# wallet registry: every WALLETS_EVERY_H hours (default 3) pull wallets from all analyses, then score the queue.
# score stops at --credits per run and at WALLET_CREDIT_SHARE of the monthly Helius credits (default 15% = 1.5M)
(
  sleep 600   # let the first hype learn finish so its smart wallets are imported
  while true; do
    python3 -m ops.heavy run_wallets.py harvest --feeds --tokens 15 >/dev/null || echo "wallets harvest nije uspio"
    # 9.11. (Jure): 1000 novčanika / 12.000 kredita svaka 3 h davalo je 9 profitabilnih od 100 bodovanih; pola toga
    python3 -m ops.heavy run_wallets.py score --credits "${WALLETS_RUN_CREDITS:-6000}" --max "${WALLETS_RUN_MAX:-500}" >/dev/null || echo "wallets score nije uspio"
    python3 -m ops.heavy run_wallets.py dokazani || echo "wallets dokazani nije uspio"   # 9.11.: proven-twice list
    python3 -m ops.heavy run_wallets.py copy >/dev/null || true
    sleep $(( ${WALLETS_EVERY_H:-3} * 3600 ))   # 7.11. (Jure): fresher copy list; the credit share cap still holds
  done
) &

# KOL calls on X: copy tweets the bot already paid for, measure price/volume after each call (GeckoTerminal, free),
# Helius flows around the strongest calls (kol/config.json flows_per_day), call power per KOL -> /kol and kol_group
keep kol python3 run_kol.py loop --every "${KOL_EVERY_MIN:-20}"
# 9.11. (Jure: "napuni podatke za ekipe i drži ih svježima"): minute candles after every call, own process and own
# minute.db (kol/minute.py); backlog first (crews before single callers), then every new call as soon as it is 70 min old
keep minute python3 run_kol.py minute-loop

# one-off KOL history (5.11.): KOL_BACKFILL_USD=28 runs run_kol.py backfill with that Apify budget once (kol.db kv
# backfill_done remembers the budget value, so later deploys do not pay again). Token list comes from kol.db itself.
# KOL_BACKFILL_AT=HH:MM (UTC) waits for that time instead (23:00 = midnight in Zagreb in winter): a deploy restarts the
# container and with it the backfill, so it is best started when nobody deploys. Without it: 25 min after start.
if [ -n "${KOL_BACKFILL_USD:-}" ]; then
  (
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
keep sched python3 run_sched.py
# morning report e-mail at REPORT_HOUR (Zagreb): reads the DBs only, one Claude call a day -> output/report-*.html
keep report python3 run_report.py loop

# safer layer: older survivors (Fartcoin/Useless style) and waking-up older tokens, free sources, every 6 h,
# guarded weekly learning on the stored daily candles -> dugo.db, page Tokeni -> Dugoročni.
# A fresh process per pass, so it holds no memory in the 6 h between passes.
( sleep 300; while true; do python3 -m ops.heavy run_dugo.py once >/dev/null || echo "dugo nije uspio"; sleep $(( ${DUGO_EVERY_MIN:-360} * 60 )); done ) &

# SimianX second opinion on the long-term list + demo test of its long signals (simianx/, needs SIMIANX_API_KEY;
# without it the pass ends at once). Light: waits on their API, so no ops.heavy slot. Real money only via /pravi-trade.
( sleep 600; while true; do python3 run_simianx.py once || echo "simianx nije uspio"; sleep $(( ${SIMIANX_EVERY_MIN:-180} * 60 )); done ) &

keep paper python3 run_paper.py run --scan --hype-args "--deep 20"   # hype scan, demo entries/exits, daily review
# 5.11.: live buys/sells from PumpPortal (free WebSocket): tokens we watch, wallets we follow, new launches
# -> hype.db live_trades; dump alerts the demo sells on within seconds (run_paper live_exits). LIVE_OFF=1 disables.
if [ -z "${LIVE_OFF:-}" ]; then keep live python3 run_live.py loop ${LIVE_ARGS:-}; fi
# (keep trade: started right after the UI above, 9.11.)

wait   # every loop has its own supervisor; the worker itself only ends when Render stops it
