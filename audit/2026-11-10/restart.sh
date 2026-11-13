#!/usr/bin/env bash
# Ponovno napuni lokalne baze i pokreni aplikaciju (staru zaustavi). bash audit/2026-11-10/restart.sh [port] [--noseed]
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE/../.." || exit 1
PORT="${1:-8790}"
S="${UIPROP_STATE:-/tmp/claude-0/-home-user/4912361d-d525-5b3e-b714-652a838e02b7/scratchpad/uiprop}"
mkdir -p "$S"
pkill -f "run_ui.py --port $PORT" 2>/dev/null; sleep 1
rm -rf "$S/ttl" "$S/snap"
if [ "${2:-}" != "--noseed" ]; then python3 "$HERE/seed_app.py" --reset || exit 1; fi
nohup bash "$HERE/run_local.sh" "$PORT" > "$S/ui.log" 2>&1 &
for i in $(seq 1 40); do curl -s -o /dev/null "http://127.0.0.1:$PORT/healthz" && break; sleep 0.5; done
curl -s -o /dev/null -w "healthz %{http_code}\n" "http://127.0.0.1:$PORT/healthz"
