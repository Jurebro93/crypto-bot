"""A production-scale generator for insajderi.db and the side databases the list stage reads (19.11. navečer: the
forced once pass sat 21 minutes in the list stage on the deep pump data). Not a test module by itself (the name does
not match test_*offline*); tests/test_popis_brzina_offline.py runs it at 1/10 scale, and

    python3 -m tests.scale_insajderi [scale]     # times every step of the list stage on a fresh build (scale 1.0 =
                                                 # ~200 pumps x ~3,500 trades, ~150k wallets, ~1,200 call events)
"""
import json
import os
import random
import sqlite3
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from insajderi import store  # noqa: E402

D = 86400
NOW = 1_795_300_000


def _w(i):
    return f"W{i:07d}" + "x" * 36


def build(d, scale=1.0, seed=7):
    """Write insajderi.db, early.db, hype.db, wallets.db, kol.db into d. -> (paths, now)."""
    rnd = random.Random(seed)
    n15, n2, n_calls = max(3, int(65 * scale)), max(3, int(135 * scale)), max(5, int(1200 * scale))
    per_ev = max(50, int(3500 * scale ** 0.5))          # trades a pump: thinned slower than the event count
    n_wallets = max(500, int(150_000 * scale))
    recur = max(50, int(3000 * scale))                  # wallets that recur across events
    p = {k: os.path.join(d, f"{k}.db") for k in ("insajderi_db", "early_db", "hype_db", "wallet_db", "kol_db",
                                                   "midcap_db", "veliki_db", "rug_db", "corr_db", "minute_db",
                                                   "xfeat_db", "trade_db", "usage_db", "listing_db", "tg_db")}
    con = store.connect(p["insajderi_db"])
    events = []
    for k in range(n15 + n2):
        tier = "pumpa15" if k < n15 else "pumpa2"
        res_d = k % 3 == 0
        t0 = NOW - rnd.randint(2, 170) * D + rnd.randint(0, 23) * 3600
        tok = f"T{k:05d}" + "t" * 38
        eid = (f"d:{tok}:{t0}" if res_d else f"j:{tok}:{t0}")
        win_end = t0 + (2 * D if res_d else 8 * 3600)
        events.append((eid, "jump", tok, f"S{k}", t0, None, None, 0, "{}", 5e6, win_end - 3600, 1.5, win_end, None,
                       None, "c1d 1d" if res_d else "midcap 6h", 2.0, 1, None, NOW, tier, 30e6 if tier == "pumpa15" else 5e6))
    for k in range(n_calls):
        t0 = NOW - rnd.randint(1, 44) * D
        tok = f"C{k:05d}" + "c" * 38
        events.append((f"c:{tok}:{t0}", "call", tok, f"C{k}", t0, "h", None, 1, json.dumps({"h": t0}), 2e5,
                       t0 + 3600, 0.5, t0 + 7200, None, None, "calls", 1.0, 1, None, NOW, None, None))
    con.executemany("INSERT INTO i2_events (eid, kind, token, symbol, t0, handle, crew, n_callers, callers, mcap0, "
                    "peak_ts, peak_x, win_end, catalyst, catalysts, src, prio, fetched, n_part, built_ts, tier, peak_mc) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", events)
    sig = 0
    trades, parts, cover = [], [], []
    for e in events:
        eid, tok, t0, win_end, tiered = e[0], e[2], e[4], e[12], e[20] is not None
        n = per_ev if tiered else 30
        ws = {}
        for _ in range(n):
            w = _w(rnd.randrange(recur)) if rnd.random() < 0.15 else _w(rnd.randrange(n_wallets))
            side = "buy" if rnd.random() < 0.55 else "sell"
            ts = (t0 - rnd.randint(60, 24 * 3600)) if side == "buy" else (t0 + rnd.randint(0, win_end - t0))
            sig += 1
            sol = round(rnd.uniform(0.01, 3.0), 3)
            payer = w if rnd.random() < 0.9 else _w(rnd.randrange(200))
            trades.append((tok, w, f"sig{sig}", ts, ts * 2 + rnd.randrange(3), side, sol, 1000.0, payer,
                           "A" + w[1:12]))
            r = ws.setdefault(w, [None, 0.0, 0, 0.0, None])
            if side == "buy":
                r[0] = ts if r[0] is None else min(r[0], ts)
                r[1] += sol
            else:
                r[2] += 1
                r[3] += sol
                r[4] = ts if r[4] is None else min(r[4], ts)
        for w, (bts, sin, ns, sout, fs) in ws.items():
            bb = int(bts is not None and sin >= 0.05)
            si = int(ns > 0 and sout >= 0.05)
            if not bb and not si:
                continue
            parts.append((eid, w, None, bts, sin or None, ns, sout or None, fs, bb, si, (t0 - bts) if bts else None,
                          "helius2"))
        con.execute("UPDATE i2_events SET n_part = ? WHERE eid = ?", (len(ws), eid))
        if tiered:
            cover.append((eid, store.FETCH_DEPTH, 86400, rnd.random(), 8 * 3600, rnd.random(), n, n * 2, NOW))
        if len(trades) > 200_000:
            con.executemany("INSERT OR IGNORE INTO i2_trades VALUES (?,?,?,?,?,?,?,?,?,?)", trades)
            trades = []
    con.executemany("INSERT OR IGNORE INTO i2_trades VALUES (?,?,?,?,?,?,?,?,?,?)", trades)
    con.executemany("INSERT OR IGNORE INTO i2_part VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", parts)
    con.executemany("INSERT OR REPLACE INTO i2_cover VALUES (?,?,?,?,?,?,?,?,?)", cover)
    con.commit()
    con.close()
    # side databases, plausible sizes
    ec = sqlite3.connect(p["early_db"])
    ec.executescript("""CREATE TABLE group_buys (wallet TEXT, mint TEXT, ts INTEGER, side TEXT, sol REAL, tokens REAL,
        slot INTEGER, payer TEXT, sig TEXT); CREATE INDEX gb_w ON group_buys (wallet);
        CREATE TABLE precall_trades (wallet TEXT, mint TEXT, ts INTEGER, side TEXT, sol REAL, tokens REAL, payer TEXT,
        sig TEXT); CREATE TABLE group_member (member TEXT, gid TEXT, kind TEXT);
        CREATE TABLE group_fetched (mint TEXT, first_ts INTEGER); CREATE TABLE early_buyers (mint TEXT, wallet TEXT,
        ts INTEGER, sol REAL);""")
    rows = [(_w(rnd.randrange(n_wallets)), f"M{rnd.randrange(5000)}", NOW - rnd.randrange(30 * D),
             rnd.choice(("buy", "sell")), 0.5, 100.0, rnd.randrange(10 ** 6), None, f"g{i}") for i in range(int(100_000 * scale) + 100)]
    ec.executemany("INSERT INTO group_buys VALUES (?,?,?,?,?,?,?,?,?)", rows)
    ec.commit()
    ec.close()
    hc = sqlite3.connect(p["hype_db"])
    hc.executescript("""CREATE TABLE live_trades (wallet TEXT, mint TEXT, ts INTEGER, side TEXT, sol REAL, tokens REAL,
        price_sol REAL); CREATE TABLE chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER, sol REAL);
        CREATE TABLE live_launches (mint TEXT, ts INTEGER, pool TEXT);""")
    hc.executemany("INSERT INTO live_trades VALUES (?,?,?,?,?,?,?)",
                   [(_w(rnd.randrange(n_wallets)), f"M{rnd.randrange(5000)}", NOW - rnd.randrange(7 * D), "buy", 0.3,
                     10.0, 0.03) for _ in range(int(100_000 * scale) + 100)])
    hc.commit()
    hc.close()
    from wallets import store as wstore
    wc = wstore.connect(p["wallet_db"])
    wc.executemany("INSERT OR IGNORE INTO wallets (wallet, first_seen, last_seen, labels, stats) VALUES (?,?,?,?,?)",
                   [(_w(i), NOW - D, NOW, json.dumps(["bot"] if i % 97 == 0 else []),
                     json.dumps({"trades_per_day": 5})) for i in range(0, n_wallets, 7)])
    wc.executemany("INSERT OR IGNORE INTO wallet_sightings VALUES (?,?,?,?,?,?,?)",
                   [(_w(i), "tok", "rug", "holder", NOW, 1.0, json.dumps({"funder": _w(i // 3 + 7)}))
                    for i in range(0, n_wallets, 11)])
    wc.commit()
    wc.close()
    from kol import store as kstore
    kc = kstore.connect(p["kol_db"])
    kc.commit()
    kc.close()
    return p, NOW


STEPS = ("vlasnici", "dijelovi", "prvi_tradeovi", "botovi", "klase", "spremanje", "katalizatori", "popis_prije_pumpe")


def time_steps(p, now, c=None):
    """Seconds of every step of the list stage (and chain.build of the pumps) on a built database."""
    from insajderi import chain, events as ev, prijepumpe, score
    c = c or store.config({"days": 45, "mkt_days": 45, "sol_usd_hist": False})
    con = store.connect(p["insajderi_db"])
    out = {}

    def t(name, fn):
        t0 = time.perf_counter()
        r = fn()
        out[name] = round(time.perf_counter() - t0, 2)
        print(f"  {name}: {out[name]} s", flush=True)
        return r
    evs = ev.load_horizon(con, c, now)
    t("build_pumpi", lambda: chain.build(con, p, c, [e for e in evs if e.get("tier")]))
    own, relay = t("vlasnici", lambda: chain.assign_owners(con, p, c))
    parts = t("dijelovi", lambda: score.load_parts(con))
    ft = t("prvi_tradeovi", lambda: score.first_trades(p, {e["token"] for e in evs}))
    owners_hit = {r[2] or r[1] for r in parts if r[8] and r[9]}
    cand = {r[1] for r in parts if (r[2] or r[1]) in owners_hit}
    bad = t("botovi", lambda: score.bots(con, p, c, cand, now - int(c["days"]) * 86400))
    stats = t("klase", lambda: score.classify(parts, evs, now + 1, c, bad, ft))
    t("spremanje", lambda: score.save(con, stats, now))
    t("katalizatori", lambda: ev.catalyze(con, p, evs, chain.waves(con, c)))
    t("popis_prije_pumpe", lambda: prijepumpe.run_list(con, c, now, evs, parts, bad, ft, {}))
    con.close()
    return out


if __name__ == "__main__":
    sc = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
    with tempfile.TemporaryDirectory() as d:
        t0 = time.perf_counter()
        p, now = build(d, sc)
        print(f"izgrađeno u {time.perf_counter() - t0:.1f} s", flush=True)
        con = sqlite3.connect(p["insajderi_db"])
        print({t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("i2_events", "i2_trades", "i2_part")},
              "novčanika", con.execute("SELECT COUNT(DISTINCT wallet) FROM i2_part").fetchone()[0], flush=True)
        con.close()
        time_steps(p, now)
