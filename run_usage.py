"""Spend on the paid APIs (Helius credits, Apify USD) and warnings when it leaks or grows too fast.

    python3 run_usage.py report          # this cycle, burn rate, projection, warnings, top scripts
    python3 run_usage.py snap            # one reading from the provider accounts + store warnings
    python3 run_usage.py loop --every 15 # snap every N minutes (start.sh runs this on the server)
    python3 run_usage.py dnevno          # 11.11.: the day's cost line per source (run_sched: 23:59 UTC) + usage.db
    python3 run_usage.py dnevno --tjedan # the 7-day sums (the weekly report)

Every Helius call (event_calendar/http.py, trade/wallet.py) and every Apify run (hype/apify.py) is counted
into usage.db by usage/meter.py. The account readings need HELIUS_PROJECT_ID for Helius and APIFY_TOKEN for Apify.
Budgets and thresholds: usage/budget.json. Warnings show on every dashboard page and on /usage.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from usage import account, meter, watch  # noqa: E402


def cmd_snap(a):
    con = meter.connect()
    for k, v in account.snapshot(con).items():
        print(f"  {k} račun: {v}", file=sys.stderr)
    alerts = watch.evaluate(con)
    watch.remember(con, alerts)
    fresh = watch.to_log(con, alerts)
    con.close()
    return fresh


def cmd_report(a):
    con = meter.connect()
    cfg = watch.config()
    for service in ("helius", "apify"):
        st = watch.status(con, service, cfg)
        f = lambda x: watch.fmt(service, x)  # noqa: E731
        print(f"{service}: {f(st['used'])} od {f(st['budget'])} ({st['used'] / st['budget']:.0%}), "
              f"{f(st['rate_day'])}/dan ({st['rate_src']}), projekcija {f(st['projected'])}"
              + ("" if st["account_ts"] else "  [samo brojač bota, nema očitanja s računa]"))
        for sc, m, n, amt in con.execute(
                "SELECT script, method, SUM(calls), SUM(amount) FROM usage WHERE service=? AND hour>=? "
                "GROUP BY script, method ORDER BY 4 DESC LIMIT 8", (service, int(time.time()) - 86400)):
            print(f"    24h {sc:<16} {m:<28} {n:>7} poziva  {f(amt)}")
    for al in watch.evaluate(con, cfg):
        print(f"[{al['level'].upper()}] {al['title']} — {al['detail']}")


def cmd_tick(a):
    """One reading; new or worse warnings go to the log, an ongoing one once a day (run_sched.py calls this)."""
    try:
        for al in cmd_snap(a):
            print(f"potrošnja [{al['level']}] {al['title']} | {al['detail']}")
    except Exception as e:
        print(f"usage snap: {type(e).__name__}: {e}", file=sys.stderr)


def cmd_dnevno(a):
    """11.11. (preporuka 8): the day's cost line per source in the log + usage.db daily_cost (run_sched at 23:59 UTC)."""
    from usage import daily
    if getattr(a, "tjedan", False):
        print("\n".join(daily.week_md(daily.week())))
        return
    daily.run()


def cmd_loop(a):
    while True:
        cmd_tick(a)
        time.sleep(a.every * 60)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("report")
    sub.add_parser("snap")
    sub.add_parser("tick")
    dn = sub.add_parser("dnevno")
    dn.add_argument("--tjedan", action="store_true", help="the 7-day sums instead of today's line")
    lp = sub.add_parser("loop")
    lp.add_argument("--every", type=float, default=15, help="minutes between account readings")
    a = p.parse_args(argv)
    {"report": cmd_report, "snap": cmd_snap, "tick": cmd_tick, "loop": cmd_loop, "dnevno": cmd_dnevno}[a.cmd](a)


if __name__ == "__main__":
    main()
