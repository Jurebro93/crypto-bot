"""KOL / influencer tracking: every call on X, what the price and volume did after it, call groups, call power
per KOL, and the wallets that sell into calls. Writes kol.db (only this script writes it).

    python3 run_kol.py loop                 # on the server: everything below every --every minutes
    python3 run_kol.py collect              # copy calls from tweets the bot already paid for (free)
    python3 run_kol.py search               # follow-up search + timeline of the best KOLs (Apify, budgeted)
    python3 run_kol.py measure              # price/volume after each call (GeckoTerminal, free)
    python3 run_kol.py flows                # who bought before / sold into a call (Helius, ~40 credits each)
    python3 run_kol.py score                # call power, groups, signals for the hype score
    python3 run_kol.py top                  # print the leaderboard

Budgets: Apify sources kol_search and kol_timeline in hype/apify.json, Helius flows_per_day in kol/config.json.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kol import collect, flows, measure, score, store  # noqa: E402

CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kol", "config.json")


def config():
    with open(CONFIG) as f:
        return json.load(f)


def cmd_collect(a, con=None, cfg=None):
    con = con or store.connect()
    n = collect.from_hype_cache(con) + collect.from_webhook(con)
    con.commit()
    print(f"collect: {n} novih poziva")
    return n


def cmd_search(a, con=None, cfg=None):
    from hype import apify
    con, cfg = con or store.connect(), cfg or config()
    if not apify.enabled():
        print("search: nema APIFY_TOKEN, preskačem")
        return 0
    n = 0
    for name, fn in (("followup", collect.followup), ("timeline", collect.timeline)):
        try:
            k = fn(con, cfg)
            con.commit()
            n += k
            print(f"search {name}: {k} novih poziva")
        except apify.BudgetExceeded as e:
            print(f"search {name}: {e}")
        except Exception as e:
            print(f"search {name}: {type(e).__name__}: {e}", file=sys.stderr)
    return n


def cmd_measure(a, con=None, cfg=None):
    con, cfg = con or store.connect(), cfg or config()
    t, c = measure.run(con, cfg, verbose=getattr(a, "verbose", False))
    print(f"measure: {t} tokena, {c} poziva izmjereno")


def cmd_flows(a, con=None, cfg=None):
    con, cfg = con or store.connect(), cfg or config()
    if not os.environ.get("HELIUS_API_KEY"):
        print("flows: nema HELIUS_API_KEY, preskačem")
        return
    n, cr = flows.run(con, cfg, verbose=getattr(a, "verbose", False))
    print(f"flows: {n} poziva provjereno, {cr} Helius kredita")


def cmd_score(a, con=None, cfg=None):
    con, cfg = con or store.connect(), cfg or config()
    n, g, s = score.run(con, cfg)
    print(f"score: {n} KOL-ova, {g} grupnih poziva, {s} svježih signala")


def cmd_top(a):
    con = store.connect()
    rows = con.execute("SELECT handle, followers, score, power_rel, stats FROM kols WHERE score IS NOT NULL "
                       "ORDER BY score DESC LIMIT ?", (a.n,)).fetchall()
    for h, f, s, p, st in rows:
        st = json.loads(st or "{}")
        print(f"{s:5.1f}  @{h:<20} {f or 0:>8,} pratitelja  {st.get('measured', 0):>3} poziva  "
              f"pogodak {st.get('hit_rate', 0):.0%}  moć/pratitelj {p or 0:.2f}x")


def cycle(a):
    con, cfg = store.connect(), config()
    for step in (cmd_collect, cmd_search, cmd_collect, cmd_measure, cmd_score, cmd_flows, cmd_score):
        try:
            step(a, con, cfg)
        except Exception as e:
            print(f"{step.__name__}: {type(e).__name__}: {e}", file=sys.stderr)
    con.close()


def cmd_loop(a):
    while True:
        cycle(a)
        time.sleep(a.every * 60)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("collect", "search", "measure", "flows", "score", "once"):
        sub.add_parser(name)
    lp = sub.add_parser("loop")
    lp.add_argument("--every", type=int, default=20, help="minuta između krugova")
    tp = sub.add_parser("top")
    tp.add_argument("-n", type=int, default=30)
    a = p.parse_args(argv)
    {"collect": cmd_collect, "search": cmd_search, "measure": cmd_measure, "flows": cmd_flows, "score": cmd_score,
     "top": cmd_top, "loop": cmd_loop, "once": cycle}[a.cmd](a)


if __name__ == "__main__":
    main()
