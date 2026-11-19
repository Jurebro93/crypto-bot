"""The passes (run_bnb.py): backfill (here, overnight: Steps 1-3 against the real sources, resumable), pass (production:
the same, bounded by pass_max_s["pass"] and calls_day), track (the tracking poller and the measurement), report.

Resumable by construction: the universe, the candles (candles_ts), every read slice (bnb_fetch), every swap (tx, log
index) and every read event (bnb_cover) are stored as they are done, so a stop loses at most the slice in flight.
"""
import json
import time

from bnb import chain, izvor, klasa, pumpe, store
from bnb import rpc as brpc


def calls_today(con, now):
    return int(float(store.kv(con, f"calls:{store.day(now)}") or 0))


def add_calls(con, now, n):
    if n > 0:
        store.kv(con, f"calls:{store.day(now)}", calls_today(con, now) + int(n))
        con.commit()


def _rpc(c):
    return brpc.Rpc(c["rpc_logs"], gap=float(c["rpc_gap_s"]))


def fill(con, c, now, clock, log=print, kind="backfill", max_events=None, gt_budget=None):
    """Steps 1-3 once. -> summary dict."""
    out = {"kind": kind}
    t0 = time.monotonic()
    out["px"] = chain.fill_prices(con, now)
    last = int(float(store.kv(con, "discover_ts") or 0))
    if now - last > 20 * 3600:
        kept, seen = pumpe.discover(con, c, now, log)
        store.kv(con, "discover_ts", int(now))
        con.commit()
        out["discover"] = {"kept": kept, "seen": seen}
        log(f"{store.PREFIX}tokeni: {kept} memecoina u pojasu od {seen} viđenih")
    b = pumpe.build(con, c, now, clock, log, gt_budget=gt_budget)
    out["pumpe"] = b
    log(f"{store.PREFIX}svijeće: {b['candled']} tokena ({b['gt_calls']} GeckoTerminal poziva, ostalo {b['left']}); "
        f"pumpi {b['events']} (novih {b['events_new']})")
    events = pumpe.load(con)
    rpc = _rpc(c)
    todo = chain.due(con, events, now, c)
    if max_events:
        todo = todo[:int(max_events)]
    out["due"] = len(todo)
    read = 0
    if todo:
        blocks = chain.Blocks(rpc, c["block_s"])
        px = chain.Px(con)
        cap = int(c["calls_day"])
        for e in todo:
            if clock.over():
                out["cut"] = "vrijeme"
                break
            if store.size_mb() > float(c["db_max_mb"]):
                out["cut"] = f"bnb.db iznad {c['db_max_mb']} MB"
                break
            if kind == "pass" and calls_today(con, now) >= cap:
                out["cut"] = "dnevni strop poziva"
                break
            n0 = rpc.n
            r = chain.fetch_event(con, c, e, rpc, blocks, px, now, clock, log)
            add_calls(con, now, rpc.n - n0)
            read += r["complete"]
            log(f"{store.PREFIX}{e.get('symbol')} {e['tier']} {time.strftime('%d.%m. %H:%M', time.gmtime(e['t0']))}: "
                f"{r['swaps']} swapova, {r['calls']} poziva, {r['reach']}{'' if r['complete'] else ' (nedovršeno)'}; "
                f"baza {store.size_mb():.0f} MB")
    out["read"] = read
    events = pumpe.load(con)
    chain.build_parts(con, c, events)
    st, f = klasa.run(con, c, events, now, rpc)
    out["lijevak"] = f
    out["secs"] = round(time.monotonic() - t0, 1)
    out["calls"] = {"rpc": brpc.calls_line(), "free": dict(izvor.CALLS)}
    store.kv_json(con, "last", out)
    con.execute("INSERT INTO bnb_runs VALUES (?,?,?,?,?)", (int(now), kind, out["secs"], json.dumps(out["calls"]),
                                                           json.dumps(f, ensure_ascii=False)))
    con.commit()
    log(klasa.funnel_line(f))
    return out
