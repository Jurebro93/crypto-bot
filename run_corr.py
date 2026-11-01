"""Korelacije: KOL groups, wallet <-> KOL links, wallet owner groups and pump factors from data the bot already
has, plus an AI interpretation (Claude, if ANTHROPIC_API_KEY is set). No Helius or Apify calls.

    python3 run_corr.py run                # one analysis (+ AI if the data changed and the last one is old enough)
    python3 run_corr.py run --ai           # force a new AI interpretation now
    python3 run_corr.py run --no-ai        # numbers only
    python3 run_corr.py loop --every 60    # every N minutes (start.sh runs this on the server)
    python3 run_corr.py report             # print the newest snapshot summary

Reads kol.db, wallets.db, rug.db, hype.db read-only; writes only corr.db.
"""
import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from corr import ai, analyze, store  # noqa: E402

DBS = {k: os.environ.get(env, os.path.join(ROOT, f)) for k, env, f in (
    ("kol", "KOL_DB", "kol.db"), ("wallets", "WALLET_DB", "wallets.db"), ("rug", "RUG_DB", "rug.db"),
    ("hype", "HYPE_DB", "hype.db"))}


def run_once(force_ai=False, no_ai=False, now=None):
    now = int(now or time.time())
    c = analyze.cfg()
    snap = analyze.build(DBS["kol"], DBS["wallets"], DBS["rug"], DBS["hype"], c, now)
    dg = analyze.digest(snap)
    con = store.connect()
    store.save(con, snap, dg, now)
    last_ts, last_hash = store.last_ai(con)
    interp = None
    want = force_ai or (last_hash != dg and now - last_ts >= c["ai_every_h"] * 3600)
    if not no_ai and want and not os.environ.get("ANTHROPIC_API_KEY"):
        print("korelacije: ANTHROPIC_API_KEY nije u okruženju servisa; tumačenje iz pravila", file=sys.stderr)
    if not no_ai and want and (snap["clusters"] or snap["groups"] or snap["links"]):
        interp, model, cost = ai.interpret(snap)
        if model.startswith("pravila"):
            interp = None          # the page builds rule lines itself; keep trying the model next time
        else:
            store.save_ai(con, dg, model, interp, cost, now)
            print(f"korelacije: AI tumačenje ({model}, ${cost:.3f})", file=sys.stderr)
    if interp is None:
        row = con.execute("SELECT data FROM ai ORDER BY ts DESC LIMIT 1").fetchone()
        import json
        interp = json.loads(row[0]) if row else None
    store.set_follow(con, analyze.follow_list(snap, interp, c), now)
    con.close()
    i = snap["inputs"]
    print(f"korelacije: {i['calls']} poziva, {i['trades']} kupnji/prodaja -> {len(snap['clusters'])} KOL grupa, "
          f"{len(snap['links'])} veza wallet-račun, {len(snap['groups'])} grupa walleta ({snap['secs']} s)",
          file=sys.stderr)
    return snap


def cmd_run(a):
    run_once(a.ai, a.no_ai)


def cmd_loop(a):
    """Each run in its own process: the analysis holds all trades in memory for a moment, and a separate process
    hands that memory back to the 512 MB server as soon as it ends. A failed run never stops the loop."""
    import subprocess
    while True:
        code = subprocess.call([sys.executable, os.path.abspath(__file__), "run"], cwd=ROOT)
        if code:
            print(f"korelacije nisu uspjele (izlaz {code})", file=sys.stderr)
        time.sleep(a.every * 60)


def cmd_report(a):
    ts, snap, interp = store.latest()
    if not snap:
        print("još nema analize")
        return
    print(time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts)), snap["inputs"])
    for cl in snap["clusters"][:10]:
        print(f"  KOL grupa {cl['id']} score {cl['score']}: {', '.join(cl['members'][:6])} · {cl['tokens']} tokena")
    for g in snap["groups"][:10]:
        print(f"  walleti {g['id']} score {g['score']}: {g['size']} walleta, {g['reasons']}")
    if interp:
        print("AI:", interp["model"], interp["data"].get("naslov"))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--ai", action="store_true")
    r.add_argument("--no-ai", action="store_true")
    r.set_defaults(fn=cmd_run)
    lp = sub.add_parser("loop")
    lp.add_argument("--every", type=int, default=60)
    lp.set_defaults(fn=cmd_loop)
    sub.add_parser("report").set_defaults(fn=cmd_report)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
