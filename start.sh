#!/usr/bin/env bash
# Render background worker: everything that must run 24/7, in one container.
# Databases, output and the HTTP cache live on the persistent disk at $DATA_DIR and are symlinked into place,
# so the code keeps its usual paths and a redeploy loses nothing.
set -u
cd "$(dirname "$0")"
DATA_DIR="${DATA_DIR:-/var/data}"
mkdir -p "$DATA_DIR/output"
for f in calendar.db hype.db paper.db rug.db wallets.db trade.db usage.db league.db market.db kol.db; do
  touch "$DATA_DIR/$f"
  ln -sfn "$DATA_DIR/$f" "$f"
done
ln -sfn "$DATA_DIR/output" output
export CAL_CACHE_DIR="$DATA_DIR/cache" LEARNED_DIR="$DATA_DIR/learned" PYTHONUNBUFFERED=1

# HTTP cache shares the 1 GB disk with the databases: trim it before anything else starts (a full disk makes
# every SQLite write fail and the first loop to crash restarts the service), then every hour
prune_cache() {
  python3 -c "from event_calendar import http; n, mb = http.prune(); print(f'cache: obrisano {n} datoteka, {mb:.0f} MB')" \
    || echo "cache prune nije uspio"
}
prune_cache
( while true; do sleep 3600; prune_cache; done ) &

# calendar + DexScreener event tokens every CALENDAR_EVERY_H hours (paper reads the newest dex-*.json)
(
  while true; do
    python3 run_calendar.py --days 14 --top 40 >/dev/null || echo "kalendar nije uspio"
    python3 run_dex.py scan --min-liq 5000 >/dev/null || echo "dex scan nije uspio"
    sleep $(( ${CALENDAR_EVERY_H:-6} * 3600 ))
  done
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

# spend on Helius/Apify: account readings every 15 min, warnings on the dashboard (/usage and a banner on every page)
python3 run_usage.py loop --every 15 &

python3 run_learn.py loop &         # once a day: re-fit hype weights per token class, guarded, no human step
python3 run_exits.py loop &         # once a day: re-learn exit rules per class from price paths, guarded, rollback
# trading volume per launchpad/terminal and the whole Solana DEX (DefiLlama, free) + market regime, every hour
python3 run_market.py loop --every 60 &

python3 run_paper.py run --scan --hype-args "--deep 20" &   # hype scan, demo entries/exits, daily review
python3 run_trade.py follow &       # mirrors paper entries/exits as real (or dry-run) swaps
# web service only: dashboard on Render's port, password from UI_PASSWORD (run_ui refuses to start without it)
if [ -n "${PORT:-}" ]; then python3 run_ui.py --host 0.0.0.0 --port "$PORT" & fi

wait -n   # if any loop dies, exit so Render restarts the whole worker
exit 1
