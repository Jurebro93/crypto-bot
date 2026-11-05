"""Live buys and sells from PumpPortal (free WebSocket) into hype.db: live_trades, live_launches, live_alerts.

    python3 run_live.py loop            # the process start.sh runs
    python3 run_live.py status          # is it alive, what it counted
    python3 run_live.py wanted          # what it would subscribe to right now
"""
import argparse
import asyncio
import json
import sys
import time

from live import pulse, pumpportal, store


def cmd_loop(a):
    con = store.connect()
    log = lambda s: print(s, flush=True)
    asyncio.run(pumpportal.run(con, log=log, refresh_s=a.refresh, new_tokens=a.new, migrations=not a.no_migrations))


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
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("loop")
    s.add_argument("--refresh", type=int, default=60, help="seconds between re-reading the watched lists")
    s.add_argument("--new", action="store_true", help="also every new pump.fun token (off: 99% die in minutes)")
    s.add_argument("--no-migrations", action="store_true", help="skip bonded (migrated) tokens")
    s.set_defaults(fn=cmd_loop)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("wanted").set_defaults(fn=cmd_wanted)
    a = p.parse_args()
    a.fn(a)
