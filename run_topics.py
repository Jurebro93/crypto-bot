#!/usr/bin/env python3
"""Event topics and their tokens (topics/, flag event_tokens G19, 11.11. Jure: "event tokeni s Grokom"). One short
process every TOPICS_EVERY_S (start.sh, low priority); flag off: it reads the flag and ends, nothing is fetched.

    python3 run_topics.py once                       matching, budgeted searches, roles, the price around events
    python3 run_topics.py status                     the topics, their tokens and today's use per source
    python3 run_topics.py add NAME KW [KW ...] [--event-ts ISO|unix] [--buzz N] [--status upcoming|live|done]
                                                     the owner adds or updates a topic (created_by owner)

Grok sends topics through the MCP tool submit_event_topic (ui/mcpapi -> topics/view.submit). Writes topics.db only.
"""
import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def status(log=print):
    from topics import job, store, view
    con = store.ro()
    if con is None:
        log("eventi: još nema teme")
        return {}
    try:
        now = int(time.time())
        log("danas: " + ", ".join(f"{name} {store.day_used(con, key, now)}/{cap()}" for name, key, cap in job.CAPS))
        for t in store.topics(con):
            arrow, spark = view.trend(t.get("buzz_hist"))
            rows = store.tokens_of(con, t["id"])
            log(f"#{t['id']} {t['name']} [{t['status']}] događaj {view._when(t.get('event_ts'))} buzz "
                f"{t.get('buzz_score')} {arrow} {spark} · {len(rows)} tokena")
            for r in rows[:20]:
                log(f"    {r.get('role') or 'other':6} {r.get('symbol') or r['token'][:6]:12} {r['token']} "
                    f"({r.get('match_field')}: {r.get('match_kw')}, {r.get('via')})")
        return {}
    finally:
        con.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("once")
    sub.add_parser("status")
    a = sub.add_parser("add")
    a.add_argument("name")
    a.add_argument("keywords", nargs="+")
    a.add_argument("--event-ts")
    a.add_argument("--buzz", type=float)
    a.add_argument("--status", choices=("upcoming", "live", "done"))
    args = ap.parse_args(argv)
    if args.cmd == "once":
        from topics import job
        job.once()
    elif args.cmd == "status":
        status()
    else:
        from topics import view
        try:
            d = view.submit(args.name, args.keywords, args.event_ts, args.buzz, args.status, "owner", kid="owner",
                            created_by="owner")
        except ValueError as e:
            print(f"eventi: nije spremljeno: {e}", flush=True)
            return 1
        print(f"eventi: tema #{d['id']} {d['name']} ({', '.join(d['changed']) or 'bez promjene'})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
