#!/usr/bin/env python3
"""Zone alarms to Grok Bot (zonewatch/, data flag zonewatch G21, 11.11. Jure). start.sh keeps one small process at low
priority (low keep zonewatch ... loop): a pass every ZONEWATCH_EVERY_S (30 s); flag off: each pass reads the flag
(cached 2 s) and does nothing else, nothing is fetched or posted.

    python3 run_zonewatch.py loop                 the loop (start.sh)
    python3 run_zonewatch.py once                 one pass
    python3 run_zonewatch.py status               the zones in force, the last alarms and today's DexScreener use
    python3 run_zonewatch.py arm MINT TYPE LO [HI] [--note TEXT] [--ttl-h H]
                                                  the owner arms (or with --ttl-h 0 disarms) one zone, source manual,
                                                  for at most 2 h (default 2)

Env: GROKBOT_WEBHOOK_URL, GROKBOT_WEBHOOK_KEY (secrets, Render dashboard only), GROKBOT_WEBHOOK_AUTH (bearer |
standard), ZONEWATCH_DEX_DAY (3000), ZONEWATCH_EVERY_S (30), ZONEWATCH_FIRST_S (90). Writes zonewatch.db only (and
events.db rows of type zone_alert through events/store.emit).
"""
import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def loop(log=print):
    from zonewatch import job, store
    every = max(10, int(float(os.environ.get("ZONEWATCH_EVERY_S") or job.EVERY_S)))
    time.sleep(max(0, int(float(os.environ.get("ZONEWATCH_FIRST_S") or 90))))   # after the start-up rush
    said_off = None
    while True:
        t0 = time.monotonic()
        try:
            res = job.pass_once(log=log)
            if res.get("mode") == "off":
                if said_off != store.day(time.time()):
                    said_off = store.day(time.time())
                    log("zonewatch: zastavica je off, ništa se ne prati")
            elif res.get("alerts") or res.get("catalyst") or res.get("position_alerts") or res.get("range_off"):
                log(f"zonewatch: {res}")
        except Exception as e:  # noqa: BLE001 - the loop never dies on one pass; never str(e) (may hold a URL)
            log(f"zonewatch: prolaz nije uspio ({type(e).__name__})")
        time.sleep(max(1.0, every - (time.monotonic() - t0)))


def status(log=print):
    from zonewatch import prices, store, view
    d = view.armed_zones(limit=300)
    if "error" in d:
        log(d["error"])
        return d
    now = int(time.time())
    con = store.ro()
    used = store.day_used(con, "dex", now) if con is not None else 0
    log(f"zastavica {d['flag_mode']}, webhook {'postavljen' if d['configured'] else 'NIJE postavljen'}, zona "
        f"{d.get('total', 0)} ({d['counts']}), DexScreener danas {used}/{prices.DEX_DAY}")
    for z in d["zones"]:
        log(f"  {z['source']:6} {z['zone_type']:6} {z.get('symbol') or z['mint'][:6]:10} {z['lo']:>12,.0f} - "
            f"{z['hi']:>12,.0f}  {z['state']:8} MC {z['mcap_now'] or '-'} ({z['distance_pct']} %)  "
            f"do {time.strftime('%d.%m. %H:%M', time.gmtime(z['expires_at']))} UTC  {z.get('note') or ''}")
    if con is not None:
        for r in con.execute("SELECT ts, event, mint, zone_type, status FROM alerts ORDER BY ts DESC LIMIT 15"):
            log(f"  alarm {time.strftime('%d.%m. %H:%M:%S', time.gmtime(r[0]))} UTC {r[1]} {(r[2] or '-')[:6]} {r[3]} → {r[4]}")
        con.close()
    return d


def main(argv=None):
    try:   # errors go to Sentry (ops/sentry.py: scrubbed, no keys or URL paths); a no-op without SENTRY_DSN
        from ops import sentry
        sentry.init("zonewatch")
    except Exception as e:  # noqa: BLE001
        print(f"sentry: {type(e).__name__}", file=sys.stderr, flush=True)
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("loop")
    sub.add_parser("once")
    sub.add_parser("status")
    a = sub.add_parser("arm")
    a.add_argument("mint")
    a.add_argument("zone_type")
    a.add_argument("lo", nargs="?")
    a.add_argument("hi", nargs="?")
    a.add_argument("--note")
    a.add_argument("--ttl-h", type=float)
    args = ap.parse_args(argv)
    if args.cmd == "loop":
        loop()
    elif args.cmd == "once":
        from zonewatch import job
        print(job.pass_once())
    elif args.cmd == "status":
        status()
    else:
        from zonewatch import store
        try:
            print(store.arm(args.mint, args.zone_type, args.lo, args.hi, args.note, args.ttl_h, "manual", kid=store.OWNER))
        except ValueError as e:
            print(f"odbijeno: {e}")
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
