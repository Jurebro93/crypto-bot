#!/usr/bin/env bash
# Lokalna kopija MemeSonara za prijedlog dizajna (10.11.2026.). Ne dira produkciju: čisto okruženje (bez ijednog
# ključa), bez mreže (local/sitecustomize.py odbija sve odlazne pozive, cijene čita iz local/market.json),
# baze su *.db u korijenu worktreeja koje puni seed_app.py.   Pokretanje:  bash audit/2026-11-10/run_local.sh [port]
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE/../.." || exit 1
S="${UIPROP_STATE:-/tmp/claude-0/-home-user/4912361d-d525-5b3e-b714-652a838e02b7/scratchpad/uiprop}"
mkdir -p "$S/ttl" "$S/snap" "$S/cache" "$S/gate"
exec env -i PATH="$PATH" HOME="${HOME:-/root}" LANG=C.UTF-8 LC_ALL=C.UTF-8 TZ=Europe/Zagreb PYTHONUNBUFFERED=1 \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$HERE/local" \
  UI_USERS=Jure,Ivan,Panda UI_PASS_JURE=demo UI_PASS_IVAN=demo UI_PASS_PANDA=demo UI_ADMINS=Jure TRADE_OWNER=Jure \
  UI_TTL_DIR="$S/ttl" UI_SNAP_DIR="$S/snap" CAL_CACHE_DIR="$S/cache" HTTP_GATE_DIR="$S/gate" \
  DEPLOY_WAIT_FLAG="$S/starting" HEAVY_LOCK="$S/heavy.lock" LEAGUE_AUTO_SELL=0 I18N_OFF=1 \
  python3 run_ui.py --port "${1:-8790}"
