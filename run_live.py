"""Live buys and sells from PumpPortal (free WebSocket) into hype.db: live_trades, live_launches, live_alerts.

    python3 run_live.py loop            # the process start.sh runs
    python3 run_live.py status          # is it alive, what it counted
    python3 run_live.py wanted          # what it would subscribe to right now
"""
import argparse
import asyncio
import json
import os
import sys
import time

from live import pulse, pumpportal, store


def new_tokens_on(a, env=None):
    """10.11. (Jure: "uključi hvatanje svih novih tokena"): every new pump.fun token is captured by default (free
    PumpPortal event; kol/precall.py measures the ones that reach 10k). Off only on purpose: --no-new, or
    LIVE_NEW_TOKENS=0 in the environment. --new keeps working (on), so an old LIVE_ARGS cannot switch it off by
    leaving it out."""
    env = os.environ if env is None else env
    if getattr(a, "no_new", False):
        return False, "--no-new"
    if getattr(a, "new", False):
        return True, "--new"
    v = (env.get("LIVE_NEW_TOKENS") or "1").strip().lower()
    if v in ("0", "false", "no", "off", "ne"):
        return False, "LIVE_NEW_TOKENS=0"
    return True, "zadano (LIVE_NEW_TOKENS)"


def cmd_loop(a):
    con = store.connect()
    log = lambda s: print(s, flush=True)
    new, why = new_tokens_on(a)
    log(f"live: novi pump.fun tokeni {'se hvataju' if new else 'se NE hvataju'} ({why})")
    asyncio.run(pumpportal.run(con, log=log, refresh_s=a.refresh, new_tokens=new, migrations=not a.no_migrations))


def cmd_status(a):
    con = store.ro()
    if con is None:
        print("live: nema podataka (hype.db bez live_trades)")
        return
    s = pulse.status(con)
    age = s["last_trade_age_s"]
    print(f"live: zadnji trade prije {age:.0f} s" if age is not None else "live: još nijedan trade",
          f"| 24 h: {s['trades_24h']} tradeova, {s['launches_24h']} novih tokena, {s['alerts_24h']} dump upozorenja",
          f"| pretplate: {s['tokens']} tokena, {s['wallets']} novčanika")


def cmd_wanted(a):
    t, w, o = pumpportal.wanted()
    print(json.dumps({"tokens": t, "wallets": w, "open": sorted(o)}, indent=1))


if __name__ == "__main__":
    try:   # 10.11. (Jure): errors go to Sentry (ops/sentry.py); a no-op without SENTRY_DSN, never stops the start
        from ops import sentry
        sentry.init("live")
    except Exception as e:  # noqa: BLE001
        print(f"sentry: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("loop")
    s.add_argument("--refresh", type=int, default=60, help="seconds between re-reading the watched lists")
    s.add_argument("--new", action="store_true", help="every new pump.fun token (the default since 10.11.)")
    s.add_argument("--no-new", action="store_true", help="no new pump.fun tokens (or LIVE_NEW_TOKENS=0)")
    s.add_argument("--no-migrations", action="store_true", help="skip bonded (migrated) tokens")
    s.set_defaults(fn=cmd_loop)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("wanted").set_defaults(fn=cmd_wanted)
    a = p.parse_args()
    a.fn(a)
