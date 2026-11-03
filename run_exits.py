#!/usr/bin/env python3
"""Exit rules learned from price paths, per token class, applied to new paper trades automatically.

    python3 run_exits.py fit              # rollback check + guarded re-fit per class; applies what passes
    python3 run_exits.py fit --dry        # same, only reports
    python3 run_exits.py status           # rules each class uses now, last runs
    python3 run_exits.py compare          # current vs. paper/config.json rules on all paths, per entry type
    python3 run_exits.py seed --retro retro.db retro2.db --series series.jsonl.gz --kol kol.db  # rebuild seed
    python3 run_exits.py loop             # on the server: once a day at exits/config.json run_at_utc

Paths: exits/seed_paths.json.gz (retrospective study, in git) + paper.db ticks of every tracked candidate.
Learned rules: LEARNED_DIR/exits.json (a few KB). Guardrails are described in exits/learn.py.
"""
import argparse
import datetime as dt
import os
import sys
import time

from exits import fit, learn, paths, profiles
from paper import sim

HERE = os.path.dirname(os.path.abspath(__file__))
PAPER_DB = os.path.join(HERE, "paper.db")
HYPE_DB = os.path.join(HERE, "hype.db")


def _pct(x):
    return f"{x:+.0%}" if isinstance(x, (int, float)) else "?"


def cmd_fit(a):
    rep = fit.run(PAPER_DB, HYPE_DB, now=time.time(), apply=not a.dry)
    for r in rep:
        flag = "PRIMIJENJENO" if r.get("applied") else ("ROLLBACK" if r.get("rollback") else "bez promjene")
        new = r.get("new") or {}
        print(f"{r['klasa']:<9} n={r.get('n', '-'):<5} live={r.get('n_live', '-'):<5} "
              f"sjena={r.get('n_shadow', '-'):<5} {flag}: {r['note']}")
        if new:
            now = r["now"]
            print(f"          sada: prosjek {_pct(now['mean'])}, medijan {_pct(now['median'])}, u plusu {now['win']:.0%}"
                  f" | novo: prosjek {_pct(new['mean'])}, medijan {_pct(new['median'])}, u plusu {new['win']:.0%}")
            if r.get("applied"):
                print(f"          {learn.describe(r['new_params'])}")
    g = profiles.load().get("sl_grid") or {}
    for key in ("sve", "kol"):
        t = g.get(key)
        if t and t.get("rows"):
            ok = [x for x in t["rows"] if x.get("score") is not None]
            b = max(ok, key=lambda x: x["score"])
            sl = "bez stopa" if b["sl"] is None else f"{b['sl']:.0%}"
            print(f"stop loss tablica {key}: n={t['n']} najbolje {sl}, odgoda {b['delay']} min, "
                  f"prosjek {_pct(b['mean'])}, u plusu {b['win']:.0%}")
    return rep


def cmd_status(a):
    state, base = profiles.load(), sim.load_config()
    if not state.get("profiles"):
        print(f"Nema naučenih pravila; svi koriste paper/config.json: {learn.describe(learn.params_of(base))}")
    for k, p in sorted(state.get("profiles", {}).items()):
        ev = p.get("eval") or {}
        print(f"{k:<9} v{p['v']} od {dt.datetime.fromtimestamp(p['ts']):%d.%m %H:%M}  "
              f"(na {ev.get('n', '?')} putanja: prosjek {_pct(ev.get('mean'))}, u plusu {_pct(ev.get('win'))})")
        print(f"          {learn.describe(p['params'])}")
    for run in state.get("runs", [])[-5:]:
        print(f"  {dt.datetime.fromtimestamp(run['ts']):%d.%m %H:%M}: " +
              "; ".join(f"{i['klasa']} {'✓' if i.get('applied') else '·'} {i['note']}" for i in run["items"]))


def cmd_compare(a):
    ecfg, base, state = learn.load_config(), sim.load_config(), profiles.load()
    ps = paths.load_seed() + paths.from_paper(PAPER_DB, HYPE_DB, since=time.time() - ecfg["live_days"] * 86400)
    by = {}
    for p in ps:
        by.setdefault(p.get("entry") or p["src"], []).append(p)
    for name, sub in sorted(by.items()):
        k = sub[0]["klasa"]
        a_ = learn.evaluate(sub, learn.to_sim(base, learn.params_of(base)), ecfg["lambda_loss"], ecfg["ret_cap"])
        b_ = learn.evaluate(sub, learn.to_sim(base, profiles.current(state, k, base)[0]), ecfg["lambda_loss"], ecfg["ret_cap"])
        print(f"{name:<14} n={len(sub):<5} config.json: prosjek {_pct(a_['mean'])} medijan {_pct(a_['median'])} "
              f"plus {a_['win']:.0%} | naučeno: prosjek {_pct(b_['mean'])} medijan {_pct(b_['median'])} plus {b_['win']:.0%}")


def cmd_seed(a):
    from exits import seed
    out, meta = seed.build(a.retro, a.series, usd=a.usd, kol_db=a.kol)
    meta["built"] = int(time.time())
    p = paths.save_seed(out, meta)
    print(f"{len(out)} putanja -> {p} ({os.path.getsize(p) / 1e6:.1f} MB): {meta['counts']}")


def cmd_loop(a):
    hh, mm = map(int, learn.load_config()["run_at_utc"].split(":"))
    last_day = None
    while True:
        now = dt.datetime.now(dt.timezone.utc)
        if (now.hour, now.minute) >= (hh, mm) and last_day != now.date():
            try:
                cmd_fit(argparse.Namespace(dry=False))
            except Exception as e:
                print(f"exits fit: {type(e).__name__}: {e}", file=sys.stderr)
            last_day = now.date()
        time.sleep(300)


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fit")
    f.add_argument("--dry", action="store_true")
    sub.add_parser("status")
    sub.add_parser("compare")
    s = sub.add_parser("seed")
    s.add_argument("--retro", nargs="+", required=True)
    s.add_argument("--series", required=True)
    s.add_argument("--kol", help="kol.db with the X call history (gunzip kol/seed.db.gz)")
    s.add_argument("--usd", type=float, default=96.0, help="USD per SOL in the study window")
    sub.add_parser("loop")
    a = p.parse_args(argv)
    {"fit": cmd_fit, "status": cmd_status, "compare": cmd_compare, "seed": cmd_seed, "loop": cmd_loop}[a.cmd](a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
