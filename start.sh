#!/usr/bin/env bash
# Render background worker: everything that must run 24/7, in one container.
# Databases, output and the HTTP cache live on the persistent disk at $DATA_DIR and are symlinked into place,
# so the code keeps its usual paths and a redeploy loses nothing.
set -u
cd "$(dirname "$0")"
DATA_DIR="${DATA_DIR:-/var/data}"
mkdir -p "$DATA_DIR/output"
for f in calendar.db hype.db paper.db rug.db wallets.db trade.db usage.db league.db market.db kol.db watch.db corr.db dugo.db tg.db koltest.db shadow.db ai.db nastoken.db public.db analytics.db; do
  touch "$DATA_DIR/$f"
  ln -sfn "$DATA_DIR/$f" "$f"
done
ln -sfn "$DATA_DIR/output" output
export CAL_CACHE_DIR="$DATA_DIR/cache" LEARNED_DIR="$DATA_DIR/learned" PYTHONUNBUFFERED=1

# web service only: a stand-in on Render's port from the first second (deploy_wait.py): visitors get the funny
# "deploy in progress" page instead of Render's black 502 while the databases are prepared and run_ui.py loads;
# it hands the port over the moment run_ui.py is ready to bind (~0.1 s), or gives up after 4 min.
# disown: it ends on purpose, and "wait -n" at the bottom must not take that for a crashed loop
if [ -n "${PORT:-}" ]; then python3 deploy_wait.py --port "$PORT" & disown; fi

# databases once before anything opens them: old raw Apify answers out, auto_vacuum switched on (one VACUUM per
# file, only when the disk has room), WAL journal on (ops/dbs.py). A full disk (<100 MB free) no longer stops this.
python3 -m ops.health --startup || echo "baze: priprema nije uspjela"

# web service only: dashboard on Render's port, password from UI_PASSWORD (run_ui refuses to start without it).
# Started first so the page is back as soon as possible after a deploy (it only reads the databases).
if [ -n "${PORT:-}" ]; then python3 run_ui.py --host 0.0.0.0 --port "$PORT" & fi

# every hour: HTTP cache trim, raw-data retention, freed pages back to the disk, WAL files cut back (ops/health.py);
# every 10 min one log line with memory per process and the size of every database, so the trend shows on Render
( while true; do sleep 3600; python3 -m ops.health --hourly || echo "održavanje nije uspjelo"; done ) &
( while true; do python3 -m ops.health || true; sleep 600; done ) &
# rugged tokens out of hype.db (rugfilter/archive.py): 2 min after every start, then hourly. Not tied to the hourly
# upkeep above: deploys restart the service more often than once an hour, and that loop sleeps first.
( sleep 120; while true; do python3 -m rugfilter.archive || true; sleep 3600; done ) &

# calendar + DexScreener event tokens every CALENDAR_EVERY_H hours (paper reads the newest dex-*.json)
(
  while true; do
    python3 run_calendar.py --days 14 --top 40 >/dev/null || echo "kalendar nije uspio"
    python3 run_dex.py scan --min-liq 5000 >/dev/null || echo "dex scan nije uspio"
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
    python3 run_hype.py learn --auto 5 >/dev/null || echo "learn nije uspio"
    sleep 86400
  done
) &

# wallet registry: every WALLETS_EVERY_H hours (default 6) pull wallets from all analyses, then score the queue.
# score stops at --credits per run and at WALLET_CREDIT_SHARE of the monthly Helius credits (default 15% = 1.5M)
(
  sleep 600   # let the first hype learn finish so its smart wallets are imported
  while true; do
    python3 run_wallets.py harvest --feeds --tokens 15 >/dev/null || echo "wallets harvest nije uspio"
    python3 run_wallets.py score --credits "${WALLETS_RUN_CREDITS:-12000}" --max 1000 >/dev/null || echo "wallets score nije uspio"
    python3 run_wallets.py copy >/dev/null || true
    sleep $(( ${WALLETS_EVERY_H:-6} * 3600 ))
  done
) &

# KOL calls on X: copy tweets the bot already paid for, measure price/volume after each call (GeckoTerminal, free),
# Helius flows around the strongest calls (kol/config.json flows_per_day), call power per KOL -> /kol and kol_group
python3 run_kol.py loop --every "${KOL_EVERY_MIN:-20}" &

# Telegram call channels: discovery every hour, hot channels read every 30 s via t.me/s (free) -> tg.db,
# hype.db tg_mentions, and kol.db calls on the next run_kol round. TGStat (TGSTAT_TOKEN) adds paid search by CA.
python3 run_tg.py loop &
# optional live listener on a Telegram account (paid option: needs a phone number), only with its secrets set
if [ -n "${TG_SESSION:-}" ] && [ -n "${TG_API_ID:-}" ]; then python3 run_tg.py telethon & fi

# loops that work only now and then, each run a short process that ends and hands its memory back (run_sched.py):
#   spend on Helius/Apify every 15 min (warnings on /usage and a banner on every page), correlations every
#   CORR_EVERY_MIN (KOL groups, wallet groups, pump factors, a Claude reading once a day if ANTHROPIC_API_KEY is set),
#   once a day re-fit of hype weights and of exit rules per class (guarded, rollback), market volume every hour
python3 run_sched.py &
# morning report e-mail at REPORT_HOUR (Zagreb): reads the DBs only, one Claude call a day -> output/report-*.html
python3 run_report.py loop &

# safer layer: older survivors (Fartcoin/Useless style) and waking-up older tokens, free sources, every 6 h,
# guarded weekly learning on the stored daily candles -> dugo.db, page Tokeni -> Dugoročni.
# A fresh process per pass, so it holds no memory in the 6 h between passes.
( sleep 300; while true; do python3 run_dugo.py once >/dev/null || echo "dugo nije uspio"; sleep $(( ${DUGO_EVERY_MIN:-360} * 60 )); done ) &

python3 run_paper.py run --scan --hype-args "--deep 20" &   # hype scan, demo entries/exits, daily review
python3 run_trade.py follow &       # mirrors paper entries/exits as real (or dry-run) swaps

wait -n   # if any loop dies, exit so Render restarts the whole worker
exit 1
