"""Trading volume in the trenches per platform (pump.fun, LaunchLab/bonk.fun, Meteora DBC…), trading terminals
(Axiom, GMGN, Photon…) and the whole Solana DEX market, plus the market regime the scoring can use.

    python3 run_market.py collect          # one reading: hourly 24 h snapshot, daily history, SOL price, regime
    python3 run_market.py loop --every 60  # collect every N minutes (start.sh runs this on the server)
    python3 run_market.py report           # platforms, trend, regime and the hypothesis check

Sources are free and keyless (DefiLlama), so nothing is counted in usage.db. Data goes to market.db.
"""
import argparse
import datetime as dt
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from market import collect, regime, sources, store  # noqa: E402

D = 86400


def cmd_collect(a):
    con = store.connect()
    ov = sources.overview(history=False)
    n = collect.snapshot(con, ov)
    newest = con.execute("SELECT MAX(day) FROM daily WHERE slug='all:launchpad'").fetchone()[0] or 0
    hist = a.history or newest < collect.today() - D or time.gmtime().tm_hour % 6 == 0
    days = 0
    if hist:
        days = collect.daily(con, sources.overview(history=True))
        collect.prices(con, sources.sol_prices(collect.KEEP_DAYS if newest == 0 else 30))
        for name, fn in (("btc", lambda: collect.btc(con, sources.btc_prices(collect.KEEP_DAYS if newest == 0 else 30))),
                         ("fng", lambda: collect.fng(con, sources.fear_greed(0 if newest == 0 else 30)))):
            try:   # audit 4.11. §15: BTC and Fear & Greed, free; a failure never stops the volume collection
                fn()
            except Exception as e:  # noqa: BLE001
                print(f"market {name}: {type(e).__name__}: {e}", file=sys.stderr)
        regime.compute_all(con)
    con.commit()
    r = regime.current(con)
    con.close()
    print(f"market: {n} platformi u snimci" + (f", {days} dana povijesti" if hist else "")
          + (f", režim {r['label']} {r['score']:.0f}/100" if r else ", režim još nepoznat"), file=sys.stderr)


def cmd_loop(a):
    while True:
        try:
            cmd_collect(a)
        except Exception as e:
            print(f"market collect: {type(e).__name__}: {e}", file=sys.stderr)
        time.sleep(a.every * 60)


def _m(x):
    return "–" if x is None else f"${x / 1e9:.2f}B" if x >= 1e9 else f"${x / 1e6:.1f}M" if x >= 1e6 else f"${x / 1e3:.0f}k"


def cmd_report(a):
    con = store.connect()
    day = con.execute("SELECT MAX(day) FROM daily").fetchone()[0]
    if not day:
        print("market.db je prazan: pokreni `python3 run_market.py collect`.")
        return
    print(f"Zadnji puni dan: {dt.datetime.fromtimestamp(day, dt.timezone.utc):%Y-%m-%d}")
    for g in ("launchpad", "terminal"):
        print(f"\n{sources.GROUP_NAMES[g]}:")
        rows = con.execute("""SELECT p.slug, p.name, SUM(CASE WHEN d.day>? THEN d.volume END), SUM(CASE WHEN d.day<=? THEN d.volume END)
            FROM daily d JOIN platforms p ON p.slug=d.slug WHERE p.grp=? AND d.day>? GROUP BY p.slug ORDER BY 3 DESC LIMIT 12""",
                           (day - 7 * D, day - 7 * D, g, day - 14 * D)).fetchall()
        for s, n, v7, p7 in rows:
            gr = f"{v7 / p7 - 1:+.0%}" if v7 and p7 else "–"
            print(f"  {sources.label(s, n):<48} 7d {_m(v7):>9}  vs prošli tjedan {gr}")
    r = regime.current(con)
    if r:
        f = r["features"]
        print(f"\nRežim: {r['label']} {r['score']:.0f}/100 (launchpadi 7d {_m(f['launchpad_7d'])} {f['launchpad_growth7d']:+.0%}, "
              f"Solana DEX 7d {_m(f['dex_7d'])} {f['dex_growth7d']:+.0%})")
    print("\n" + regime.verdict(regime.hypothesis(con)))
    con.close()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--history", action="store_true", help="always fetch the daily history too")
    lp = sub.add_parser("loop")
    lp.add_argument("--every", type=float, default=60, help="minutes between readings")
    lp.add_argument("--history", action="store_true")
    sub.add_parser("report")
    a = p.parse_args(argv)
    {"collect": cmd_collect, "loop": cmd_loop, "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    main()
