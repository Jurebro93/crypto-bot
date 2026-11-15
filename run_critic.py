"""Kritičar (OpenAI): the critic of open trades, of the algorithm and of the analyses (15.11., vlasnik). Advice only.

    python3 run_critic.py trades           # one open-trade pass (run_sched every KRITICAR_EVERY_MIN, default 5 min)
    python3 run_critic.py trades --sada    # the same, a call even when nothing changed (the budget still holds)
    python3 run_critic.py daily            # the daily review (run_sched: after a start when today has none, 06:40)
    python3 run_critic.py daily --sada     # on demand, also when today's exists (the budget still holds)
    python3 run_critic.py stats [--dana 7] # calls, cost, hit rates (also MCP get_critic_stats)
    python3 run_critic.py loop             # the watcher of real-money fills (start.sh, supervised): a comment each
    python3 run_critic.py live --od A --do B   # comment the live fills A < id <= B (the watcher's child)
    python3 run_critic.py deep --auto      # the deep session when due (run_sched every 10 min); --sada: now

Needs OPENAI_API_KEY (without it: one log line an hour, nothing else); the owner switch openai_kritika (on by default).
critic/ has the details. Exit code 1 only when an API call failed (run_sched then retries the daily review later).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main(argv=None):
    try:   # errors go to Sentry like the other loops (a no-op without SENTRY_DSN)
        from ops import sentry
        sentry.init("kriticar")
    except Exception as e:  # noqa: BLE001
        print(f"sentry: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
    ap = argparse.ArgumentParser(description="Kritičar (OpenAI)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("trades")
    t.add_argument("--sada", action="store_true")
    d = sub.add_parser("daily")
    d.add_argument("--sada", action="store_true")
    s = sub.add_parser("stats")
    s.add_argument("--dana", type=int, default=7)
    sub.add_parser("loop")
    lv = sub.add_parser("live")
    lv.add_argument("--od", type=int, required=True)
    lv.add_argument("--do", type=int, required=True)
    dp = sub.add_parser("deep")
    dp.add_argument("--auto", action="store_true")
    dp.add_argument("--sada", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "stats":
        from critic import store
        con = store.connect()
        try:
            print(json.dumps(store.stats(con, a.dana), ensure_ascii=False, indent=1))
        finally:
            con.close()
        return 0
    if a.cmd == "loop":
        from critic import live
        live.loop()
        return 0
    if a.cmd == "live":
        from critic import live
        res = live.run(a.od, getattr(a, "do"))
    elif a.cmd == "deep":
        from critic import deep
        res = deep.run(auto=a.auto and not a.sada)
    elif a.cmd == "trades":
        from critic import trades
        res = trades.run(force=a.sada)
    else:
        from critic import daily
        res = daily.run(force=a.sada)
    if getattr(a, "sada", False):
        print(json.dumps(res, ensure_ascii=False))
    return 1 if res.get("skip") in ("greška API-ja", "neispravan odgovor") else 0


if __name__ == "__main__":
    sys.exit(main())
