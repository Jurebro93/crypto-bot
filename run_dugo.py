"""Dugoročni i oživljeni tokeni: the safer list next to the new-token hunt (page Tokeni -> Dugoročni).

    python3 run_dugo.py once                 # one pass: collect, rank, demo book (+ learning when due, every 7 days)
    python3 run_dugo.py loop --every 360     # same in one long-lived process
    python3 run_dugo.py learn                # one guarded learning step for both lists
    python3 run_dugo.py report               # top of both lists in the terminal

Free sources only (DexScreener, GeckoTerminal, CoinGecko, own kol.db/hype.db), no Helius credits.
BIRDEYE_API_KEY (paid) adds holder growth. Data: dugo.db; learned weights: LEARNED_DIR/dugo.json.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dugo import learn, run, store  # noqa: E402


def cmd_once(a):
    """One pass; learning too when the last learning run is older than ucenje.svaki_d days."""
    cfg = run.config()
    con = store.connect()
    try:
        last = con.execute("SELECT MAX(ts) FROM learn_runs").fetchone()[0] or 0
        run.once(con, cfg, learn_too=time.time() - last > cfg["ucenje"]["svaki_d"] * 86400)
    finally:
        con.close()


def cmd_loop(a):
    while True:
        try:
            cmd_once(a)
        except Exception as e:
            print(f"dugo: {type(e).__name__}: {e}", file=sys.stderr)
        time.sleep(a.every * 60)


def cmd_learn(a):
    cfg = run.config()
    con = store.connect()
    for kind in ("dugorocni", "budjenje"):
        r = learn.fit(con, cfg, kind)
        print(kind, r["n"], r["note"])


def cmd_report(a):
    con = store.connect()
    for kind in ("dugorocni", "budjenje"):
        print(f"\n{kind}:")
        for sym, s, why in con.execute("""SELECT t.symbol, s.score, s.why FROM snap s JOIN tokens t ON t.mint=s.mint
                WHERE s.kind=? AND s.day=(SELECT MAX(day) FROM snap) ORDER BY s.rank LIMIT ?""", (kind, a.top)):
            print(f"  {sym:<12} {s:5.1f}  {why}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("once").set_defaults(fn=cmd_once)
    lp = sub.add_parser("loop")
    lp.add_argument("--every", type=int, default=360)
    lp.set_defaults(fn=cmd_loop)
    sub.add_parser("learn").set_defaults(fn=cmd_learn)
    rp = sub.add_parser("report")
    rp.add_argument("--top", type=int, default=15)
    rp.set_defaults(fn=cmd_report)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
