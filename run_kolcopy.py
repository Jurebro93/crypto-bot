"""KOL copy replay: would copying KOL wallets pay, after our delay and costs? (kolcopy/, kolcopy.db)

  python3 run_kolcopy.py run [--credits N]   one pass: new KOL buys from hype.db chain_trades, prices of due points
  python3 run_kolcopy.py report [--delay 30] results per delay and exit, the out-of-sample test, best wallets

On the server run_sched starts `run` every KOLCOPY_EVERY_MIN minutes (default 30). Needs HELIUS_API_KEY; the
dashboard page is /kol-kopiranje.
"""
import argparse
import os
import sys
import time

from kolcopy import prices, replay, stats, store


def cmd_run(a):
    if not os.environ.get("HELIUS_API_KEY"):
        print("kolcopy: nema HELIUS_API_KEY, preskačem")
        return 0
    cfg = replay.load_config()
    con = store.connect()
    try:
        res = replay.step(con, cfg, prices.Prices(con, cfg), credits=a.credits)
    finally:
        con.close()
    print(f"kolcopy: {res['added']} novih kupnji, {res['points']} cijena, {res['done']} završenih, "
          f"{res['skipped']} preskočenih, {res['credits']:.0f} kredita" + (" (budžet potrošen)" if res["stopped"] else ""))
    return 0


def cmd_report(a):
    cfg = replay.load_config()
    con = store.ro()
    if con is None:
        print("kolcopy.db još ne postoji")
        return 0
    try:
        rs = stats.rets(stats.load(con), cfg, time.time())
    finally:
        con.close()
    table, skips = stats.by_delay(rs, cfg)
    print(f"{len(rs)} kupnji KOL novčanika; neto po trejdu nakon troškova ({replay.cost(cfg):.1%})")
    for (d, x), s in table.items():
        if s:
            print(f"  kašnjenje {d:>3} s  izlaz {x:<6}  n={s['n']:<5} prosjek {stats.fmt_pct(s['mean'])}  "
                  f"medijan {stats.fmt_pct(s['median'])}  u plusu {s['win']:.0%}  "
                  f"90% [{stats.fmt_pct(s['lo'])}, {stats.fmt_pct(s['hi'])}]  {stats.verdict(s, cfg['min_n_verdict'])}"
                  + (f"  (KOL prodao prije ulaza: {skips[(d, x)]})" if skips[(d, x)] else ""))
    o = stats.oos(rs, cfg, a.delay)
    if o:
        print(f"provjera na budućnosti ({a.delay} s, zrcaljenje prodaje): {len(o['picked'])} izabranih novčanika")
        for k, label in (("picked_first", "izabrani, starija polovica"), ("picked_second", "izabrani, novija polovica"),
                         ("all_second", "svi, novija polovica")):
            s = o[k]
            print(f"  {label:<28} " + (f"n={s['n']} prosjek {stats.fmt_pct(s['mean'])}" if s else "–"))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--credits", type=float, default=None, help="strop kredita za ovaj prolaz")
    r.set_defaults(fn=cmd_run)
    rp = sub.add_parser("report")
    rp.add_argument("--delay", type=int, default=30)
    rp.set_defaults(fn=cmd_report)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
