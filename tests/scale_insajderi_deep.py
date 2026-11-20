"""The production shape of insajderi.db after the deep pump reads (20.11.: the full passes "once" / "night" were killed
by the memory watchdog, ops/health.py MEM_KILL_MB 800). Not a test module by itself (the name does not match
test_*offline*); tests/test_insajderi_memorija_offline.py builds it at a small scale, and

    python3 -m tests.scale_insajderi_deep [scale] [n_fetched]

builds it at `scale` (1.0: ~262 pump events, 65 of them >= 15M, a lognormal number of swaps a pump, median ~10k, the
biggest ~160k, ~4.6M i2_trades; ~1,000 call events over 44 days; ~1M i2_part rows, almost all wallets that only
traded in the jump window; ~35k early buyers; a recurring core of ~160 wallets early in 2-8 pumps; same-slot bundles)
and runs ONE full pass (run.run "once", no network: the Helius stage is faked to report the first n_fetched (201)
pumps as read, so chain.build runs on them as in production) and prints the peak RSS, the RSS high-water per step and
the stage times.
"""
import json
import math
import os
import random
import sqlite3
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from insajderi import chain, store  # noqa: E402

D = 86400
NOW = 1_795_300_000
DBS = ("insajderi_db", "early_db", "hype_db", "wallet_db", "kol_db", "midcap_db", "veliki_db", "rug_db", "corr_db",
       "minute_db", "xfeat_db", "trade_db", "usage_db", "listing_db", "tg_db", "league_db", "makroinf_db")


def _w(prefix, i):
    return (f"{prefix}{i:08d}" + "w" * 44)[:44]


def build(d, scale=1.0, seed=11, depth=None, span=175, call_trades=None, call_pool=None):
    """Write insajderi.db (i2_part built by chain.build itself) and small side databases into d. -> (paths, now).
    depth: the scale of the swaps a pump (default `scale`; a small test keeps the deep reads' shape with depth > scale:
    most participants traded only in one jump window); span: the days back the pumps start (a test keeps it short).
    call_trades / call_pool (20.11. (2), production before the deep reads: ~700k participants of ~150k wallets, mostly
    the call events' free sources): that many trades a call event in early.db precall_trades, by wallets drawn from a
    pool of call_pool (they recur across call events); None: 60 a call event in i2_trades, mostly fresh wallets."""
    rnd = random.Random(seed)
    n15, n2, n_calls = max(3, int(65 * scale)), max(4, int(197 * scale)), max(5, int(1000 * scale))
    depth = scale if depth is None else depth
    med = 10_000 * depth
    p = {k: os.path.join(d, f"{k}.db") for k in DBS}
    con = store.connect(p["insajderi_db"])
    ins = [_w("I", i) for i in range(max(20, int(160 * scale)))]      # early in 2-8 pumps, sells into most
    rec = [_w("R", i) for i in range(max(200, int(6000 * scale)))]    # early in 1-3 pumps
    crews = [[_w("B", 10 * k + j) for j in range(rnd.randint(3, 5))] for k in range(max(4, int(40 * scale)))]
    fresh = [0]

    def new_w(pref):
        fresh[0] += 1
        return _w(pref, fresh[0])
    events, pumps = [], []
    for k in range(n15 + n2):
        tier = "pumpa15" if k < n15 else "pumpa2"
        res_d = k % 3 == 0
        t0 = NOW - rnd.randint(2, span) * D + rnd.randint(0, 23) * 3600
        tok = (f"T{k:05d}" + "t" * 44)[:44]
        eid = f"d:{tok}:{t0}" if res_d else f"j:{tok}:{t0}"
        win_end = t0 + (2 * D if res_d else 8 * 3600)
        mc0 = 12e6 if tier == "pumpa15" else 2e6   # events.mark_tiers: mcap0 x (1 + peak_x) is the peak MC
        events.append((eid, "jump", tok, f"S{k}", t0, None, None, 0, "{}", mc0, win_end - 3600, 1.5, win_end, None,
                       None, "c1d 1d" if res_d else "midcap 6h", 2.0, 1, None, NOW, tier,
                       30e6 if tier == "pumpa15" else 5e6))
        pumps.append((eid, tok, t0, win_end))
    for k in range(n_calls):
        t0 = NOW - rnd.randint(1, 44) * D + rnd.randint(0, D - 1)
        tok = (f"C{k:05d}" + "c" * 44)[:44]
        events.append((f"c:{tok}:{t0}", "call", tok, f"C{k}", t0, "h", None, 1, json.dumps({"h": t0, "h2": t0 + 600}),
                       2e5, t0 + 3600, 0.5, t0 + 7200, None, None, "calls", 1.0, 1, None, NOW, None, None))
    con.executemany("INSERT INTO i2_events (eid, kind, token, symbol, t0, handle, crew, n_callers, callers, mcap0, "
                    "peak_ts, peak_x, win_end, catalyst, catalysts, src, prio, fetched, n_part, built_ts, tier, peak_mc) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", events)
    early_of = {eid: [] for eid, *_ in pumps}
    for w in ins:
        for eid, *_ in rnd.sample(pumps, min(len(pumps), rnd.randint(2, 8))):
            early_of[eid].append((w, rnd.random() < 0.85))
    for w in rec:
        for eid, *_ in rnd.sample(pumps, min(len(pumps), rnd.choice((1, 1, 2, 2, 3)))):
            early_of[eid].append((w, rnd.random() < 0.25))
    sig, batch, cover = [0], [], []

    def put(tok, w, ts, side, sol, payer=None, slot=None):
        sig[0] += 1
        px = math.exp(rnd.uniform(-1, 1)) * 1e-6
        batch.append((tok, w, f"s{sig[0]}", int(ts), int(ts) * 2 + rnd.randrange(3) if slot is None else slot, side,
                      sol, sol / px, payer or w, None))
    for eid, tok, t0, we in pumps:
        n = int(min(160_000 * depth + 1000, max(1500 * depth, rnd.lognormvariate(math.log(med), 0.95))))
        pre_lo = t0 - (72 if eid.startswith("d:") else 24) * 3600
        lst = early_of[eid] + [(new_w("E"), rnd.random() < 0.12) for _ in range(max(10, int(40 + n / 250)))]
        used = 0
        for w, sells in lst:
            for _ in range(rnd.randint(1, 3)):
                put(tok, w, rnd.randint(pre_lo, t0 - 60), "buy", round(rnd.uniform(0.06, 3.0), 3))
                used += 1
            for _ in range(rnd.randint(1, 3) if sells else 0):
                put(tok, w, rnd.randint(t0, we), "sell", round(rnd.uniform(0.06, 6.0), 3))
                used += 1
        if rnd.random() < 0.4:   # a same-slot bundle of one crew, one fee payer, early before t0
            crew = crews[rnd.randrange(len(crews))]
            ts = rnd.randint(t0 - 3000, t0 - 60)
            for w in crew:
                put(tok, w, ts, "buy", round(rnd.uniform(0.5, 4.0), 3), payer=crew[0], slot=ts * 2 + 7)
                put(tok, w, rnd.randint(t0, we), "sell", round(rnd.uniform(0.5, 6.0), 3))
                used += 2
        k = 0
        while k < max(0, n - used):   # the jump window: many wallets, a few trades each
            w, m = new_w("J"), rnd.randint(1, 7)
            for _ in range(m):
                put(tok, w, rnd.randint(t0, we), "buy" if rnd.random() < 0.5 else "sell", round(rnd.uniform(0.01, 4), 3))
            k += m
        cover.append((eid, store.FETCH_DEPTH, 86400, rnd.uniform(0.3, 1.0), 8 * 3600, rnd.uniform(0.3, 1.0), n, n // 50,
                      NOW))
        if len(batch) > 300_000:
            con.executemany("INSERT INTO i2_trades VALUES (?,?,?,?,?,?,?,?,?,?)", batch)
            batch.clear()
    call_free = []
    for e in events:
        if e[1] == "call" and call_trades:
            pool = int(call_pool or 150_000 * scale)
            free = []
            for i in range(int(call_trades)):
                w = _w("Q", rnd.randrange(pool)) if rnd.random() < 0.9 else rnd.choice(rec)
                if rnd.random() < 0.55:
                    ts, side = e[4] - rnd.randint(60, 3 * D), "buy"
                else:
                    ts, side = rnd.randint(e[4], e[12]), "sell"
                sol = round(rnd.uniform(0.02, 2.0), 3)
                free.append((w, e[2], ts, side, sol, sol / 1e-6, w, f"q{e[0][-12:]}{i}"))
            call_free.extend(free)
        elif e[1] == "call":
            for _ in range(60):
                w = rnd.choice(rec) if rnd.random() < 0.2 else new_w("K")
                if rnd.random() < 0.5:
                    put(e[2], w, e[4] - rnd.randint(60, 2 * D), "buy", round(rnd.uniform(0.05, 2.0), 3))
                else:
                    put(e[2], w, rnd.randint(e[4], e[12]), "sell", round(rnd.uniform(0.05, 2.0), 3))
    con.executemany("INSERT INTO i2_trades VALUES (?,?,?,?,?,?,?,?,?,?)", batch)
    con.executemany("INSERT OR REPLACE INTO i2_cover VALUES (?,?,?,?,?,?,?,?,?)", cover)
    con.commit()
    ec = sqlite3.connect(p["early_db"])
    ec.executescript("""CREATE TABLE group_buys (wallet TEXT, mint TEXT, ts INTEGER, side TEXT, sol REAL, tokens REAL,
        slot INTEGER, payer TEXT, sig TEXT); CREATE INDEX gb_w ON group_buys (wallet);
        CREATE TABLE precall_trades (wallet TEXT, mint TEXT, ts INTEGER, side TEXT, sol REAL, tokens REAL, payer TEXT,
        sig TEXT); CREATE TABLE group_member (member TEXT, gid TEXT, kind TEXT);
        CREATE TABLE group_fetched (mint TEXT, first_ts INTEGER); CREATE TABLE early_buyers (mint TEXT, wallet TEXT,
        first_buy_ts INTEGER, sol_in REAL, sold_ts INTEGER, sol_out REAL);""")
    ec.executemany("INSERT INTO group_buys VALUES (?,?,?,?,?,?,?,?,?)",
                   [(rnd.choice(rec), f"M{rnd.randrange(5000)}", NOW - rnd.randrange(30 * D), rnd.choice(("buy", "sell")),
                     0.5, 100.0, rnd.randrange(10 ** 6), None, f"g{i}") for i in range(int(50_000 * scale) + 100)])
    ec.executemany("INSERT INTO group_fetched VALUES (?,?)", [(e[2], e[4] - 5 * D) for e in events[::2]])
    ec.executemany("INSERT INTO precall_trades VALUES (?,?,?,?,?,?,?,?)", call_free)
    ec.execute("CREATE INDEX pt_m ON precall_trades (mint)")
    del call_free
    ec.commit()
    ec.close()
    hc = sqlite3.connect(p["hype_db"])
    hc.executescript("""CREATE TABLE live_trades (wallet TEXT, mint TEXT, ts INTEGER, side TEXT, sol REAL, tokens REAL,
        price_sol REAL); CREATE TABLE chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER, sol REAL);
        CREATE TABLE live_launches (mint TEXT, ts INTEGER, pool TEXT); CREATE TABLE live_trades_hourly (mint TEXT,
        hour INTEGER, close_px REAL);""")
    hc.executemany("INSERT INTO live_trades VALUES (?,?,?,?,?,?,?)",
                   [(rnd.choice(rec), f"M{rnd.randrange(5000)}", NOW - rnd.randrange(7 * D), "buy", 0.3, 10.0, 0.03)
                    for _ in range(int(50_000 * scale) + 100)])
    hc.commit()
    hc.close()
    from wallets import store as wstore
    wc = wstore.connect(p["wallet_db"])
    sightings = [(ins[i], "tok", "rug", "holder", NOW, 1.0, json.dumps({"funder": _w("Z", i // 3)}))
                 for i in range(0, len(ins), 2)]
    sightings += [(rec[i], "tok", "rug", "holder", NOW, 1.0, json.dumps({"funder": _w("Y", i // 2)}))
                  for i in range(0, len(rec), 5)]
    wc.executemany("INSERT INTO wallet_sightings VALUES (?,?,?,?,?,?,?)", sightings)
    wc.executemany("INSERT OR IGNORE INTO wallets (wallet, first_seen, last_seen, labels, stats) VALUES (?,?,?,?,?)",
                   [(rec[i], NOW - D, NOW, json.dumps(["bot"] if i % 97 == 0 else []), json.dumps({"trades_per_day": 5}))
                    for i in range(0, len(rec), 3)])
    wc.commit()
    wc.close()
    from kol import store as kstore
    kc = kstore.connect(p["kol_db"])
    kc.executemany("INSERT OR IGNORE INTO tokens (token, symbol, supply, created_ts) VALUES (?,?,?,?)",
                   [(e[2], e[3], 1e9, e[4] - 20 * D) for e in events])
    kc.commit()
    kc.close()
    c = store.config({"sol_usd_hist": False})
    evs = [dict(eid=e[0], kind=e[1], token=e[2], t0=e[4], win_end=e[12], callers=json.loads(e[8]) or {}) for e in events]
    chain.build(con, p, c, evs)
    con.execute("UPDATE i2_events SET built_ts = ?", (NOW,))
    con.commit()
    con.close()
    return p, NOW


def cfg(**k):
    """insajderi/config.json with the bounds lifted (the whole pass runs) and no network price history."""
    with open(os.path.join(ROOT, "insajderi", "config.json"), encoding="utf-8") as f:
        c = json.load(f)
    c.update({"sol_usd_hist": False, "pass_max_s": {"once": 100000, "incr": 100000, "night": 100000},
              "list_max_s": 100000, "helius_day": 250000})
    c.pop("backfill", None)
    c.update(k)
    return c


def full_pass(p, now, n_fetched=201, c=None, log=None):
    """One run.run("once") with the Helius stage faked (the first n_fetched pumps "read" in this pass) -> (summary,
    log lines, {step: RSS MB high-water}, peak RSS MB)."""
    from insajderi import copy, prijepumpe, run, score, smart, walkcache
    stack, peak, done = ["start"], {}, [False]

    def sampler():
        while not done[0]:
            r = store.rss_mb() or 0
            peak[stack[-1]] = max(peak.get(stack[-1], 0), r)
            time.sleep(0.05)

    saved = []

    def wrap(mod, name):
        f = getattr(mod, name)

        def w(*a, **k):
            stack.append(f"{mod.__name__.split('.')[-1]}.{name}")
            try:
                return f(*a, **k)
            finally:
                stack.pop()
        saved.append((mod, name, f))
        setattr(mod, name, w)

    def fake_fetch_due(con, p_, c_, events, now_, budget, **_k):
        if fake_fetch_due.done:
            return 0, 0
        fake_fetch_due.done = True
        pumps = sorted((e for e in events if e.get("tier")), key=chain.order_key)[:n_fetched]
        chain.LAST_FETCHED.extend(e["eid"] for e in pumps)
        return len(pumps), 0
    fake_fetch_due.done = False
    for mod, names in ((chain, ("build", "assign_owners")), (score, ("load_parts", "bots", "classify")),
                       (prijepumpe, ("market_makers", "bundles", "history")), (walkcache, ("run",)),
                       (copy, ("wallet_trades",)), (smart, ("run",))):
        for n in names:
            wrap(mod, n)
    saved.append((chain, "fetch_due", chain.fetch_due))
    chain.fetch_due = fake_fetch_due
    lines = []
    th = threading.Thread(target=sampler, daemon=True)
    th.start()
    old = os.environ.get("INSAJDERI_DB")
    os.environ["INSAJDERI_DB"] = p["insajderi_db"]
    try:
        s = run.run("once", now=now, cfg=c or cfg(), credits=100_000, fetch=_no_network,
                    log=log or lines.append, **p)
    finally:
        done[0] = True
        th.join()
        for mod, name, f in saved:
            setattr(mod, name, f)
        if old is None:
            os.environ.pop("INSAJDERI_DB", None)
        else:
            os.environ["INSAJDERI_DB"] = old
    return s, lines, peak, max(peak.values() or [0])


def _no_network(*_a, **_k):
    raise RuntimeError("no network here")


if __name__ == "__main__":
    sc = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
    nf = int(sys.argv[2]) if len(sys.argv) > 2 else 201
    from insajderi import report
    with tempfile.TemporaryDirectory() as d:
        t0 = time.perf_counter()
        p, now = build(d, sc)
        con = sqlite3.connect(p["insajderi_db"])
        print(f"izgrađeno u {time.perf_counter() - t0:.0f} s:",
              {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("i2_events", "i2_trades", "i2_part")},
              f"{os.path.getsize(p['insajderi_db']) / 1e6:.0f} MB", flush=True)
        con.close()
        report.OUT_DIR = d
        t0 = time.perf_counter()
        s, lines, peak, top = full_pass(p, now + 3600, nf)
        print(f"prolaz {time.perf_counter() - t0:.0f} s, najviše {top} MB RSS")
        for k, v in sorted(peak.items(), key=lambda x: -x[1]):
            print(f"  {k}: {v} MB")
        print("\n".join(x for x in lines if "trajanje" in x or "memorija" in x))
