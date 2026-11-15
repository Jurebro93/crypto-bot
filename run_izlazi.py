#!/usr/bin/env python3
"""Naučeni izlazi po izvoru (15.11., vlasnik: "nauči iz podataka najbolji stop loss i najbolji take profit, po izvoru
... alat mora postati profitabilan"): izlazi/ (data -> learn -> izlazi.db), read by league/exitplan for new positions.

    python3 run_izlazi.py night            nightly, 01-06 Zagreb, once a Zagreb day (start.sh: ops.heavy --night)
    python3 run_izlazi.py run              on demand, now (read-only on every other database, no API call)
    python3 run_izlazi.py report           the markdown report of the latest run (also output/izlazi.md after a run)
    python3 run_izlazi.py critic           the JSON summary the OpenAI critic reads (izlazi.report.critic_summary)
    python3 run_izlazi.py uzorak [--out P] a local run on the repo's own paths (exits/seed_paths.json.gz graduation /
                                           100k entries, tests/fixtures range candles): no production data needed;
                                           writes P (default: a temporary file) and prints the report
"""
import argparse
import datetime as dt
import glob
import gzip
import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
TZ = "Europe/Zagreb"


def zagreb_day(now):
    from zoneinfo import ZoneInfo
    return dt.datetime.fromtimestamp(now, ZoneInfo(TZ)).date().isoformat()


def in_night(now):
    try:
        from ops import heavy
        return heavy.night_now(dt.datetime.fromtimestamp(now, dt.timezone.utc))
    except Exception:  # noqa: BLE001
        from zoneinfo import ZoneInfo
        return 1 <= dt.datetime.fromtimestamp(now, ZoneInfo(TZ)).hour < 6


def write_md(path=None):
    from izlazi import report
    out = os.path.join(ROOT, "output")
    try:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "izlazi.md"), "w") as f:
            f.write(report.markdown(path))
    except OSError:
        pass


def night(force=False, log=print, now=None):
    from izlazi import learn, store
    now = int(now or time.time())
    if not force and not in_night(now):
        log("naučeni izlazi (noć): izvan noćnog prozora 01-06, ništa")
        return None
    con = store.connect()
    try:
        if not force and store.kv_get(con, "night_day") == zagreb_day(now):
            return None
    finally:
        con.close()
    info = learn.run(now=now, log=log, budget_s=int(os.environ.get("IZLAZI_LEARN_BUDGET_S", "900")))
    con = store.connect()
    try:
        store.kv_put(con, "night_day", zagreb_day(now))
        con.commit()
    finally:
        con.close()
    write_md()
    return info


def seed_entries(cost_liq=None):
    """Entries from the repo's own paths (no production data): the seed study's graduation / 100k entries (a source
    per entry type: 'strategy' rows) and the 7 range fixtures (a source per token, an entry every 15 minutes)."""
    from izlazi import sim
    from trade import cost as tcost
    out = []
    with gzip.open(os.path.join(ROOT, "exits", "seed_paths.json.gz"), "rt") as f:
        d = json.load(f)
    for p in d["paths"]:
        if p.get("entry") not in ("graduacija", "100k") or not p.get("pts"):
            continue
        by = {}
        for s, m, _liq in p["pts"]:
            if not m or m <= 0:
                continue
            k = int(s) + 1
            b = by.get(k)
            by[k] = [k, m, m, m] if b is None else [k, max(b[1], m), min(b[2], m), m]
        bars = [tuple(by[k]) for k in sorted(by) if k <= sim.HORIZON_S]
        if not bars:
            continue
        fitted = sim.fit(bars)
        liq = p.get("liq0") or cost_liq
        out.append({"kind": "strategy", "src": f"seed {p['entry']}", "tok": p.get("mint"), "ts": int(p["ts"]),
                    "arrs": sim.pack(fitted), "cover": min(sim.HORIZON_S, bars[-1][0]),
                    "cost": max(0.02, tcost.round_trip(15.0, liq)), "sell_s": None, "rug_s": None, "how": "seed",
                    "stats": sim.path_stats(fitted)})
    for fn in sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "range_*.json.gz"))):
        with gzip.open(fn, "rt") as f:
            fx = json.load(f)
        c = sorted(tuple(r) for r in fx.get("candles") or [] if r[4])
        sym = fx.get("symbol") or os.path.basename(fn)
        for i in range(0, max(0, len(c) - 60), 15):
            got = sim.bars_from_candles(c, c[i][0] + 30)
            if not got or not got[2]:
                continue
            _e, t0, bars = got
            fitted = sim.fit(bars)
            out.append({"kind": "kol", "src": f"fixture {sym}", "tok": sym, "ts": int(t0), "arrs": sim.pack(fitted),
                        "cover": bars[-1][0], "cost": max(0.02, tcost.round_trip(15.0, 25_000.0)), "sell_s": None,
                        "rug_s": None, "how": "fixture", "stats": sim.path_stats(fitted)})
    out.sort(key=lambda e: e["ts"])
    return out


def uzorak(out=None, log=print):
    from izlazi import learn, report, store
    path = out or os.path.join(tempfile.mkdtemp(prefix="izlazi-"), "izlazi.db")
    es = seed_entries()
    t0 = time.time()
    rows, summary = learn.learn(es, {"costs": {"slip_stop_pct": 5.0}}, log=log)
    cov = {}
    for e in es:
        c = cov.setdefault(e["kind"], {"izvori": set(), "ulazi": 0, "s_putom": 0, "sati": {"1h": 0, "4h": 0, "24h": 0}})
        c["izvori"].add(e["src"])
        c["ulazi"] += 1
        c["s_putom"] += 1
        for lab, s in (("1h", 3600), ("4h", 14400), ("24h", 86400)):
            c["sati"][lab] += int(e["cover"] >= s - 900)
    for c in cov.values():
        c["izvori"] = len(c["izvori"])
    con = store.connect(path)
    try:
        store.save(con, rows, {"summary": summary, "coverage": cov, "meta": {"costs": {"slip_stop_pct": 5.0,
                                                                                         "slip_from": "zadano"}},
                               "s": round(time.time() - t0, 1)})
    finally:
        con.close()
    print(report.markdown(path))
    log(f"uzorak: {path}")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("night", "run", "report", "critic", "uzorak"))
    ap.add_argument("--force", action="store_true", help="night: also outside the window / when done today")
    ap.add_argument("--out", help="uzorak: the izlazi.db to write")
    a = ap.parse_args(argv)

    def log(s):
        print(s, flush=True)
    if a.cmd == "night":
        night(force=a.force, log=log)
    elif a.cmd == "run":
        from izlazi import learn
        learn.run(log=log)
        write_md()
    elif a.cmd == "report":
        from izlazi import report
        print(report.markdown())
    elif a.cmd == "critic":
        from izlazi import report
        print(report.dumps(report.critic_summary()))
    else:
        uzorak(a.out, log=log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
