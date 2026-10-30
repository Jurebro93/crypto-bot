#!/usr/bin/env bash
# Render background worker: everything that must run 24/7, in one container.
# Databases, output and the HTTP cache live on the persistent disk at $DATA_DIR and are symlinked into place,
# so the code keeps its usual paths and a redeploy loses nothing.
set -u
cd "$(dirname "$0")"
DATA_DIR="${DATA_DIR:-/var/data}"
mkdir -p "$DATA_DIR/output"
for f in calendar.db hype.db paper.db rug.db wallets.db trade.db; do
  touch "$DATA_DIR/$f"
  ln -sfn "$DATA_DIR/$f" "$f"
done
ln -sfn "$DATA_DIR/output" output
export CAL_CACHE_DIR="$DATA_DIR/cache" PYTHONUNBUFFERED=1

# calendar + DexScreener event tokens every CALENDAR_EVERY_H hours (paper reads the newest dex-*.json)
(
  while true; do
    python3 run_calendar.py --days 14 --top 40 >/dev/null || echo "kalendar nije uspio"
    python3 run_dex.py scan --min-liq 5000 >/dev/null || echo "dex scan nije uspio"
    sleep $(( ${CALENDAR_EVERY_H:-6} * 3600 ))
  done
) &

python3 run_paper.py run --scan &   # hype scan, demo entries/exits, daily review
python3 run_trade.py follow &       # mirrors paper entries/exits as real (or dry-run) swaps

wait -n   # if any loop dies, exit so Render restarts the whole worker
exit 1
