"""A synthetic fixture for market/trziste.py (20.11.): market.db, midcap.db, veliki.db, insajderi.db and league.db in a
directory, deterministic (seeded), no network. Not a test module by itself; tests/test_trziste_offline.py uses it and

    python3 -m tests.trziste_fixture <dir>      # builds it and runs one offline pass (for a look at the page)
"""
import json
import math
import os
import random
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

D = 86400
NOW = 1795132800 + 12 * 3600          # 2026-11-20 12:00 UTC
TODAY = NOW // D * D
DAYS = 230


def btc_series(days=DAYS):
    """{day: close} of the finished days before TODAY: a slow wave with a deterministic wobble."""
    rnd = random.Random(3)
    out, px = {}, 70000.0
    for i in range(days, 0, -1):
        d = TODAY - i * D
        px *= 1 + 0.012 * math.sin((days - i) / 9.0) + rnd.uniform(-0.01, 0.01)
        out[d] = round(px, 2)
    return out


def fng_label(v):
    return "Extreme Fear" if v <= 25 else "Fear" if v <= 46 else "Neutral" if v <= 54 else "Greed" if v <= 75 \
        else "Extreme Greed"


def build(d, tokens=30, seed=7):
    """Write the databases into d. -> (paths dict for trziste, btc {day: close})."""
    rnd = random.Random(seed)
    btc = btc_series()
    bdays = sorted(btc)
    rets = {bdays[i]: btc[bdays[i]] / btc[bdays[i - 1]] - 1 for i in range(1, len(bdays))}
    p = {k: os.path.join(d, f"{k}.db") for k in ("market", "midcap", "veliki", "insajderi", "league")}
    from market import store
    m = store.connect(p["market"])
    for i, day in enumerate(bdays + [TODAY]):
        v = int(max(3, min(97, 50 + 45 * math.sin(i / 9.0 - 0.6))))
        m.execute("INSERT INTO fng VALUES (?,?,?,?,?)", (day, v, fng_label(v), day, day))
        for s, base in (("pump.fun", 1.2e8), ("pumpswap", 2.0e8), ("launchlab", 1e6), ("meteora-dynamic-bonding-curve", 4e6)):
            if day < TODAY:
                m.execute("INSERT INTO daily VALUES (?,?,?)", (day, s, base * (1 + 0.4 * math.sin(i / 8.0))))
    m.commit()
    m.close()
    from veliki import midcap, store as vstore
    mc = sqlite3.connect(p["midcap"])
    mc.executescript(midcap.SCHEMA)
    vc = sqlite3.connect(p["veliki"])
    vc.executescript(vstore.SCHEMA)
    ic = sqlite3.connect(p["insajderi"])
    ic.executescript("""CREATE TABLE i2_events (eid TEXT PRIMARY KEY, kind TEXT, token TEXT, symbol TEXT, t0 INTEGER,
        handle TEXT, crew TEXT, n_callers INTEGER, callers TEXT, mcap0 REAL, peak_ts INTEGER, peak_x REAL,
        win_end INTEGER, catalyst TEXT, catalysts TEXT, src TEXT, prio REAL, fetched INTEGER DEFAULT 0,
        n_part INTEGER, built_ts INTEGER, tier TEXT, peak_mc REAL);""")
    mints = []
    for k in range(tokens):
        mint = f"Tok{k:02d}" + "x" * 38
        mints.append(mint)
        follows = k % 3 != 0                 # every third token moves on its own
        mcap = 3e6 + k * 1.5e6
        con = mc if k % 2 == 0 else vc
        if con is mc:
            con.execute("INSERT INTO tokens (mint, id, symbol, mcap, member) VALUES (?,?,?,?,1)", (mint, k, f"T{k}", mcap))
        else:
            con.execute("INSERT INTO tokens (mint, symbol, mcap) VALUES (?,?,?)", (mint, f"T{k}", mcap))
        px = 1.0
        for day in bdays[-200:]:
            r = (2.0 * rets.get(day, 0) if follows else 0) + rnd.gauss(0, 0.04 if follows else 0.08)
            if k == 4 and day == bdays[-60]:
                r = -0.45                    # a drop for the derived drops
            if k == 5 and day == bdays[-40]:
                r = 0.9                      # a jump in the candles
            px *= max(0.05, 1 + r)
            con.execute("INSERT INTO c1d VALUES (?,?,?,?,?,?,?)", (mint, day, px, px, px, px, 1000))
        for j in range(3):
            t0 = bdays[-150 + 40 * j + k] + 3600 * (k % 12)
            ic.execute("INSERT INTO i2_events (eid, kind, token, symbol, t0, peak_x, src, tier, n_callers) VALUES "
                       "(?,?,?,?,?,?,?,?,0)", (f"j:{mint}:{t0}", "jump", mint, f"T{k}", t0, 0.6 + 0.1 * j, "midcap 6h",
                                               "pumpa15" if mcap >= 15e6 else "pumpa2"))
    mc.execute("INSERT INTO tokens (mint, id, symbol, mcap, member) VALUES ('Small' || 'x', 999, 'SM', 20000, 1)")
    mc.execute("INSERT INTO tokens (mint, id, symbol, mcap, member) VALUES ('NoCandles', 998, 'NC', 5e6, 1)")
    for h in range(60 * 24, 0, -1):
        ts = (NOW // 3600 - h) * 3600
        vc.execute("INSERT INTO btc_h VALUES (?,?)", (ts, 60000 * (1 + 0.05 * math.sin(h / 50.0))))
    vc.execute("INSERT INTO kv VALUES ('x', '1')")
    # trades: good on green days, poor otherwise, so the colour filter has something to find
    from market import trziste
    sm = trziste.colours(btc)

    def ret_of(ts):
        b = (sm.get(ts // D * D - D) or {}).get("boja")
        return (0.04 if b == "zeleno" else -0.03 if b == "crveno" else -0.005) + rnd.gauss(0, 0.03)
    trades = []
    for i in range(400):
        ts = TODAY - rnd.randint(1, 120) * D + rnd.randint(0, 80000)
        trades.append([rnd.choice(mints), ts, round(ret_of(ts), 5)])
    mc.execute("INSERT INTO kv VALUES ('replay_trades', ?)", (json.dumps({"ts": NOW, "trades": trades}),))
    lg = sqlite3.connect(p["league"])
    lg.executescript("""CREATE TABLE veliki_sjena (id INTEGER PRIMARY KEY, token TEXT, opened_ts INTEGER, profil TEXT,
        rt REAL, status TEXT, ret REAL);
        CREATE TABLE veliki_trades (id INTEGER PRIMARY KEY, user TEXT, token TEXT, opened_ts INTEGER, rt REAL,
        status TEXT, ret REAL, varijanta TEXT);
        CREATE TABLE signal_mjera (id INTEGER PRIMARY KEY, token TEXT, entry_ts INTEGER, status TEXT, ret_net_01 REAL,
        entry_mcap REAL);""")
    for i in range(300):
        ts = TODAY - rnd.randint(1, 40) * D + rnd.randint(0, 80000)
        lg.execute("INSERT INTO veliki_sjena (token, opened_ts, profil, rt, status, ret) VALUES (?,?,?,?,?,?)",
                   (rnd.choice(mints), ts, "pravilo" if i % 2 else "skalp", 0.02, "closed", ret_of(ts)))
    for i in range(30):
        ts = TODAY - rnd.randint(1, 20) * D
        lg.execute("INSERT INTO veliki_trades (user, token, opened_ts, rt, status, ret, varijanta) VALUES (?,?,?,?,?,?,?)",
                   ("autopilot-paper", rnd.choice(mints), ts, 0.035, "closed", ret_of(ts),
                    "nauceno:skalp" if i % 5 == 0 else None))
        lg.execute("INSERT INTO signal_mjera (token, entry_ts, status, ret_net_01, entry_mcap) VALUES (?,?,?,?,?)",
                   (rnd.choice(mints), ts, "closed", ret_of(ts), 20000 if i == 0 else 4e6))
    for c in (mc, vc, ic, lg):
        c.commit()
        c.close()
    return p, btc


def fetch_for(btc):
    """trziste.update's fetchers over the fixture (no network)."""
    def f_btc(days):
        return sorted((d, c) for d, c in btc.items() if d >= TODAY - days * D)

    def f_fng(limit):
        return []

    def f_slug(slug):
        return []
    return {"btc": f_btc, "fng": f_fng, "slug": f_slug}


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/trziste_fixture"
    os.makedirs(out, exist_ok=True)
    paths, b = build(out)
    from market import trziste
    res = trziste.run(NOW, paths, fetch_for(b), council=False)
    print(json.dumps(paths))
