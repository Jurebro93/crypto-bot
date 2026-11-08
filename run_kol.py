"""KOL / influencer tracking: every call on X, what the price and volume did after it, call groups, call power
per KOL, and the wallets that sell into calls. Writes kol.db (only this script writes it).

    python3 run_kol.py loop                 # on the server: everything below every --every minutes
    python3 run_kol.py collect              # copy calls from tweets the bot already paid for (free)
    python3 run_kol.py search               # follow-up search + timeline of the best KOLs (Apify, budgeted)
    python3 run_kol.py measure              # price/volume after each call (GeckoTerminal, free)
    python3 run_kol.py flows                # who bought before / sold into a call (Helius, ~40 credits each)
    python3 run_kol.py score                # call power, groups, signals for the hype score
    python3 run_kol.py top                  # print the leaderboard
    python3 run_kol.py live                 # sync the real-time monitor with the watchlist (xquik, on the server)
    python3 run_kol.py backfill --tokens retro.json --budget 11   # one-off history: X posts on past tokens + KOL timelines

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
    for name, fn in (("telegram", collect.from_telegram), ("chain", collect.from_chain)):
        try:
            k = fn(con)
            n += k
            if k:
                print(f"collect {name}: {k} novih")
        except Exception as e:
            print(f"collect {name}: {type(e).__name__}: {e}", file=sys.stderr)
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
    from kol import discover
    from kol import graduates, trending
    try:
        k = trending.collect_today(con, cfg)
        con.commit()
        if k:
            print(f"trending: {k} novih tokena danas (GeckoTerminal + DexScreener boosts)")
    except Exception as e:  # noqa: BLE001
        print(f"trending: {type(e).__name__}: {e}", file=sys.stderr)
    try:   # 5.11.: graduated pump.fun tokens (PumpSwap pools by activity): the pool of tokens that did not die
        k = graduates.collect(con, cfg)
        con.commit()
        if k:
            print(f"bondani: {k} novih tokena u popisu (GeckoTerminal pumpswap)")
    except Exception as e:  # noqa: BLE001
        print(f"bondani: {type(e).__name__}: {e}", file=sys.stderr)
    for name, fn in (("followup", collect.followup), ("timeline", collect.timeline), ("stars", collect.stars),
                     ("winners", discover.winners), ("trending", trending.search), ("audit", discover.audit),
                     ("graph", discover.graph)):
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


def cmd_deleted(a, con=None, cfg=None):
    """Re-check measured X calls by tweet id: deleted posts get deleted_ts (kol/deleted.py), the score punishes
    accounts that delete their losers."""
    from kol import deleted
    con, cfg = con or store.connect(), cfg or config()
    return deleted.check(con, cfg)


def cmd_snap(a, con=None, cfg=None):
    """DexScreener price/volume snapshot of every token called in the last day, then outcomes from snapshots."""
    from kol import snap
    con, cfg = con or store.connect(), cfg or config()
    k = snap.take(con)
    n = snap.measure(con, cfg)
    print(f"snap: {k} tokena snimljeno (DexScreener), {n} poziva izmjereno iz snimki")


def cmd_measure(a, con=None, cfg=None):
    con, cfg = con or store.connect(), cfg or config()
    t, c = measure.run(con, cfg, verbose=getattr(a, "verbose", False))
    print(f"measure: {t} tokena, {c} poziva izmjereno")
    from kol import sessions
    b = sessions.backfill(con, cfg, measure.ohlcv)
    if b:
        print(f"sesije: satni volumen za {b} starijih tokena")


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


def _load_tokens(path):
    """JSON list or JSONL of {mint, launch_ts, peak_ts, winner, peak_mult?, symbol?}."""
    with open(path) as f:
        txt = f.read().strip()
    return json.loads(txt) if txt.startswith("[") else [json.loads(l) for l in txt.splitlines() if l.strip()]


def cmd_backfill(a):
    """History in one night: posts on past winners and non-winners, then the found KOLs' timelines, then prices."""
    from hype import apify
    from kol import backfill
    cfg_a = apify.config()
    cfg_a["daily_usd"]["kol_backfill"] = a.budget  # one-off budget for this run only, the server keeps 0
    apify.config = lambda: cfg_a
    con, cfg = store.connect(), config()
    # on the server (start.sh, KOL_BACKFILL_USD): once per budget value, so a redeploy does not pay again
    done = (con.execute("SELECT value FROM kv WHERE key = 'backfill_done'").fetchone() or (None,))[0]
    if done == str(a.budget) and not a.force:
        print(f"backfill: budžet ${a.budget} već odrađen, preskačem (--force za ponovno)")
        return
    from kol import trending
    pool = _load_tokens(a.tokens) if a.tokens else backfill.tokens_from_db(con, max_age_d=getattr(a, "max_age_d", 90))
    pool += [t for t in trending.for_backfill(con) if t["mint"] not in {x["mint"] for x in pool}]   # 5.11.: trending too
    toks = backfill.pick(pool, a.winners, a.losers, exclude=backfill.done_targets(con, "backfill_token"))
    print(f"backfill: {len(toks)} tokena ({a.winners} pobjednika + {a.losers} ostalih), budžet ${a.budget}"
          + ("" if a.tokens else " (lista iz kol.db)"), flush=True)
    try:
        backfill.search_tokens(con, toks, apify.run, a.per_token)
        since = min(t["launch_ts"] for t in toks) if toks else int(time.time()) - 30 * 86400
        backfill.search_timelines(con, backfill.top_handles(con, a.kols), apify.run, since, a.per_kol)
    except apify.BudgetExceeded as e:
        print(f"backfill: {e}")
    con.execute("INSERT OR REPLACE INTO kv VALUES ('backfill_done', ?)", (str(a.budget),))
    con.commit()
    print(f"backfill: pretraga gotova, potrošeno ${apify.spent('kol_backfill'):.2f}", flush=True)
    cmd_collect(a, con, cfg)
    cfg["measure_tokens_per_run"] = 100000
    cmd_measure(a, con, cfg)
    cmd_score(a, con, cfg)


def cmd_live(a, con=None, cfg=None):
    from kol import live
    con, cfg = con or store.connect(), cfg or config()
    r = live.sync(con, cfg)
    if r is None:
        print("live: nema javnog URL-a (RENDER_EXTERNAL_URL) ili APIFY_TOKEN, preskačem")


def cmd_traces(a, con=None, cfg=None):
    """Suspicious transfers around tracked wallets (kol/traces.py) from the Helius TRANSFER events."""
    from kol import chainwatch, traces
    con, cfg = con or store.connect(), cfg or config()
    n = traces.run(con, chainwatch.HYPE_DB, cfg)
    if n:
        print(f"tragovi: {n} novih (primio pa zvao / veza / supply)")


def cmd_crew(a, con=None, cfg=None):
    """Who engages on fresh calls of reaching accounts and whether they bought before (kol/crew.py)."""
    from kol import chainwatch, crew
    con, cfg = con or store.connect(), cfg or config()
    crew.run(con, cfg, chainwatch.HYPE_DB)


def cmd_xhook(a, con=None, cfg=None):
    """twitterapi.io filter rules for the live X watch (kol/xhook.py)."""
    from kol import xhook
    con, cfg = con or store.connect(), cfg or config()
    r = xhook.sync(con, cfg)
    if r is None:
        print("xhook: nema TWITTERAPI_IO_KEY ili javnog URL-a, preskačem")


def cmd_chain(a, con=None, cfg=None):
    """KOL wallets from public lists (daily) and the Helius webhook that follows their swaps."""
    from kol import chainwatch, idents
    con, cfg = con or store.connect(), cfg or config()
    got = idents.refresh(con, cfg)
    if got:
        print(f"kol novčanici: {got}")
    r = chainwatch.sync(con, cfg["chain"])
    if r is None:
        print("chain: nema HELIUS_API_KEY ili javnog URL-a, preskačem")


def cmd_converge(a, con=None, cfg=None):
    from kol import converge
    con, cfg = con or store.connect(), cfg or config()
    conv = converge.compute(cfg=cfg.get("converge"), good=cfg["good_score"])
    converge.save(con, conv)
    con.commit()
    best = sorted(conv.items(), key=lambda kv: -kv[1]["score"])[:5]
    print(f"konvergencija: {len(conv)} tokena" + "".join(f"\n  {t} {r['score']:.0f} {'+'.join(r['platforms'])}" for t, r in best))


def cycle(a):
    # 8.11. 21:00: two rounds without bot detection still died at 60 min with no scoring part finished; nothing in
    # the log said where. Every 10 min the main thread's stack goes to stderr, so the next kill shows the exact line.
    import faulthandler
    faulthandler.dump_traceback_later(600, repeat=True)
    con, cfg = store.connect(), config()
    # the quick steps first: the slow GeckoTerminal measure used to come before scoring, and with several deploys an
    # hour the process restarted inside it, so bot flags, groups and the watchlist were rarely recomputed (1.11.)
    # 8.11.: scoring ran 30+ min and the round was killed at 60 min every time for 2+ days, so the webhook list
    # (cmd_chain), the X watch (cmd_xhook), convergence and measuring never ran; the cheap steps go first now
    # 8.11. 18:00: cmd_search (twitterapi.io timelines of ~300 accounts) took 20-31 min of network waiting while
    # holding the heavy-job lock, so the round still died before scoring finished; it goes last now
    for step in (cmd_collect, cmd_chain, cmd_xhook, cmd_live, cmd_snap, cmd_converge, cmd_score, cmd_traces, cmd_measure,
                 cmd_flows, cmd_deleted, cmd_crew, cmd_search, cmd_collect):
        t = time.time()
        try:
            step(a, con, cfg)
        except Exception as e:
            print(f"{step.__name__}: {type(e).__name__}: {e}", file=sys.stderr)
        if time.time() - t >= 60:   # 8.11.: the round was killed at 60 min for days and nobody could tell which step
            print(f"krug: {step.__name__} trajao {time.time() - t:.0f} s", flush=True)
    con.close()


def cmd_loop(a):
    # history collected off-server, imported once per file: kol/seed.db.gz (X backfill) and
    # kol/seed_callanalyser.db.gz (Telegram calls from Nicholas's Call Analyser export, measured off-server)
    for path in (store.SEED, store.SEED_CA):
        try:
            con = store.connect()
            n = store.import_seed(con, path)
            con.close()
            if n:
                print(f"seed {os.path.basename(path)}: {n} povijesnih poziva uvezeno")
        except Exception as e:
            print(f"seed {os.path.basename(path)}: {type(e).__name__}: {e}", file=sys.stderr)
    while True:
        # each round in its own short process (1.11.: this loop sat at ~85 MB between rounds on the 512 MB server,
        # trim could not hand it back); the round's memory goes back to the system when it ends
        import subprocess
        args = [sys.executable, os.path.abspath(__file__)] + (["--verbose"] if a.verbose else []) + ["once"]
        try:
            from ops import heavy   # one heavy job at a time on the 512 MB server (2.11.)
            heavy.run(args, timeout=max(600, a.every * 60 * 3))
        except subprocess.TimeoutExpired:
            print("krug: predugo, prekinut", file=sys.stderr)
        time.sleep(a.every * 60)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("collect", "search", "snap", "measure", "flows", "score", "once", "live", "chain", "converge"):
        sub.add_parser(name)
    lp = sub.add_parser("loop")
    lp.add_argument("--every", type=int, default=20, help="minuta između krugova")
    bp = sub.add_parser("backfill")
    bp.add_argument("--tokens", help="JSON/JSONL s tokenima iz retrospektive; bez toga lista iz kol.db (pozivi + snimke)")
    bp.add_argument("--force", action="store_true", help="ponovi i kad je taj budžet već odrađen (kv backfill_done)")
    bp.add_argument("--max-age-d", type=int, default=90, help="tokens called within this many days (2nd round: 180)")
    bp.add_argument("--winners", type=int, default=400)
    bp.add_argument("--losers", type=int, default=400)
    bp.add_argument("--per-token", type=int, default=20, help="postova po tokenu")
    bp.add_argument("--kols", type=int, default=150, help="koliko KOL-ova dobiva povijest timelinea")
    bp.add_argument("--per-kol", type=int, default=100)
    bp.add_argument("--budget", type=float, default=11.0, help="USD za cijeli backfill (Apify)")
    tp = sub.add_parser("top")
    tp.add_argument("-n", type=int, default=30)
    a = p.parse_args(argv)
    {"collect": cmd_collect, "search": cmd_search, "snap": cmd_snap, "measure": cmd_measure, "flows": cmd_flows, "score": cmd_score,
     "top": cmd_top, "live": cmd_live, "loop": cmd_loop, "once": cycle, "backfill": cmd_backfill,
     "chain": cmd_chain, "converge": cmd_converge}[a.cmd](a)


if __name__ == "__main__":
    main()
