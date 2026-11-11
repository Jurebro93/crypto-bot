"""events.db: one log of everything that happens (events/__init__.py).

    python3 run_events.py tick                 every 5 min (run_sched.py "events", light): append-only sync of the
                                               old tables, the feed health check, stale MCP requests tidied
    python3 run_events.py night [--force] [--steps outcomes,scores]
                                               the night batch, 03:00 Zagreb (start.sh: ops.heavy --night)
    python3 run_events.py backfill [--estimate] [--days 14]
                                               the last 14 days of the old tables; --estimate only prints the rows and
                                               MB it would add (nothing is written)
    python3 run_events.py ev                   the EV report per feature phase (run_sched.py "evreport", 23:30)
    python3 run_events.py parity [--hours 24]  events vs the old tables, row by row
    python3 run_events.py health               the feed status now (types, last event, gaps)
    python3 run_events.py gaps [--hours 48]    when the old tables were silent (wallet feed, calls)
    python3 run_events.py brief [--since ISO]  get_hourly_brief as JSON
"""
import argparse
import datetime as dt
import json
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(description="events.db (jedna tablica događaja)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tick")
    n = sub.add_parser("night")
    n.add_argument("--force", action="store_true", help="i kad nije 03:00 ili je već odrađeno (ručno)")
    n.add_argument("--steps", default="", help="samo ovi koraci, zarezom (npr. outcomes,scores)")
    b = sub.add_parser("backfill")
    b.add_argument("--estimate", action="store_true", help="samo procjena, ništa se ne piše")
    b.add_argument("--days", type=int, default=14)
    sub.add_parser("ev")
    p = sub.add_parser("parity")
    p.add_argument("--hours", type=float, default=24)
    sub.add_parser("health")
    g = sub.add_parser("gaps")
    g.add_argument("--hours", type=float, default=48)
    br = sub.add_parser("brief")
    br.add_argument("--since", default=None)
    br.add_argument("--limit", type=int, default=30)
    a = ap.parse_args(argv)
    try:   # errors go to Sentry like the other loops (a no-op without SENTRY_DSN)
        from ops import sentry
        sentry.init("events")
    except Exception:  # noqa: BLE001
        pass
    if a.cmd == "tick":
        from events import night
        night.tick()
    elif a.cmd == "night":
        from events import night
        night.run(force=a.force, steps=[s for s in a.steps.split(",") if s] or None)
    elif a.cmd == "backfill":
        from events import sources
        est = sources.estimate(a.days)
        if not a.estimate:
            sources.backfill(a.days, est=est)
    elif a.cmd == "ev":
        from events import evreport
        evreport.run()
    elif a.cmd == "parity":
        from events import sources
        print(json.dumps(sources.parity(a.hours), ensure_ascii=False, indent=1))
    elif a.cmd == "health":
        from events import health, store
        con = store.ro()
        if con is None:
            print("events.db još ne postoji")
            return 0
        try:
            for s in health.status(con):
                print(f"{s['type']:12} zadnji {s['gap_min'] if s['gap_min'] is not None else '-':>8} min  "
                      f"7 d {s['n7d']:>8}  {'aktivan' if s['active'] else '-'}  {s['sources']}")
        finally:
            con.close()
    elif a.cmd == "gaps":
        from events import health
        for name, gs in health.gaps(a.hours).items():
            print(f"{name}: {len(gs)} tišina dužih od {health.GAP_MIN} min")
            for t0, t1, m in gs[:10]:
                f = lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%d.%m. %H:%M")  # noqa: E731
                print(f"  {f(t0)} -> {f(t1)} UTC  {m} min")
    elif a.cmd == "brief":
        from events import brief
        print(json.dumps(brief.build(a.since, a.limit), ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
