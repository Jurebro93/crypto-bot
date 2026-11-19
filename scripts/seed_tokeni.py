#!/usr/bin/env python3
"""Fixture for the Tokeni page and Pregled (19.11.): NOT production data, never run on the server. Fills the databases
the new Tokeni page reads (ui/midcaplist.py) with a made-up but plausible set:

    midcap.db         ~500 member tokens across both tiers (>= 15 M $ and 2-15 M $), a few non-members, 6 snapshot
                      rows each (the newest carries the 24 h change), one hostile symbol
    tokenstranice.db  names of the tokens (pages)
    insajderi.db      20 tiered pumps (i2_events tier / peak_mc) on member tokens, early buyers (i2_part) of a few owner
                      groups (i2_pp: prije_pumpe and other classes); added next to what seed_novcanici.py put there
    trade.db          the real-money pause key (pravi_novac_pauza), unless --no-pause

    python3 scripts/seed_tokeni.py DIR             # into DIR (the screenshots: the worktree root)
    python3 scripts/seed_tokeni.py DIR --empty     # empty midcap.db / no pumps (the empty state)

seed(paths, n=500, n_pumps=20, empty=False, now=None) is what the tests call with their temporary paths.
"""
import hashlib
import json
import os
import random
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
D, H = 86400, 3600
HOSTILE = '<img src=x onerror=alert(7)>'
WORDS = ["Frog", "Cat", "Dog", "Moon", "Pepe", "Wif", "Bonk", "Giga", "Chill", "Goat", "Mew", "Pnut", "Fwog", "Spx",
         "Troll", "Useless", "Lock", "Michi", "Retard", "Zeb", "Act", "Popcat", "Mood", "Hat", "Bull"]


def b58(seed, n=44):
    h = b"".join(hashlib.sha256(f"{seed}:{i}".encode()).digest() for i in range(3))
    return "".join(B58[b % 58] for b in h[:n])


COOLDOG = "Coo1dogXyzABCDEFGHJKLMNPQRSTUVWXYZabcdefpump"


def paths_in(d):
    return {k: os.path.join(d, f"{k}.db") for k in ("midcap", "tokenstranice", "insajderi", "trade", "kol")}


def mint_of(i):
    return b58(f"midcap{i}", 40) + "pump"


def seed(paths, n=500, n_pumps=20, empty=False, now=None, paused=True):
    now = int(now or time.time())
    R = random.Random(19112026)
    from veliki import midcap
    from tokenstranice import store as tstore
    from insajderi import store as istore
    con = midcap.connect(paths["midcap"])
    for t in ("tokens", "snap"):
        con.execute(f"DELETE FROM {t}")
    out = {"tokens": [], "pumps": [], "groups": []}
    if not empty:
        rows, snaps = [], []
        for i in range(n):
            # about a fifth >= 15 M $ (log-uniform 15-200 M), the rest 2-15 M $
            mc = (15e6 * (200 / 15) ** R.random()) if i % 5 == 0 else (2e6 * 7.5 ** R.random())
            sym = HOSTILE if i == 7 else (R.choice(WORDS) + R.choice(["", "AI", "COIN", "INU", "X", "2"])).upper()[:10]
            m = mint_of(i)
            liq = mc * R.uniform(0.03, 0.18)
            rows.append((m, i + 1, sym, b58(f"pool{i}", 44), "raydium", mc, liq, mc * R.uniform(0.05, 1.5),
                         now - R.randint(20, 400) * D, now - R.randint(2, 30) * D, now - R.randint(10, 80), None, "dex",
                         None, 1, None))
            for k in range(6):
                ts = now - k * 900 - R.randint(10, 80)
                c24 = round(R.gauss(0, 12), 2)
                snaps.append((i + 1, ts, mc / 1e9, int(mc * (1 - k * 0.002)), int(liq), 1000, 20000, 90000,
                              int(mc * 0.3), 5, 4, 60, 55, 900, 870, 0.1, 0.5, 1.2, c24))
            out["tokens"].append((m, sym, mc))
        for j in range(5):   # left the list: never shown
            rows.append((b58(f"gone{j}", 40) + "pump", n + j + 1, f"GONE{j}", None, "raydium", 900_000, 20_000, 1e5,
                         now - 90 * D, now - 20 * D, now - 3 * D, now - 2 * D, "dex", None, 0, "ispod 2M"))
        con.executemany("INSERT OR REPLACE INTO tokens VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        con.executemany("INSERT OR REPLACE INTO snap VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", snaps)
    con.commit()
    con.close()

    tcon = tstore.connect(paths["tokenstranice"])
    tcon.execute("DELETE FROM pages")
    for i, (m, sym, mc) in enumerate(out["tokens"]):
        if i % 4 == 3:
            continue   # a quarter without a page: the row shows the symbol only
        nm = ("Evil <b>name</b>" if i == 7 else f"{sym.title()} {R.choice(['Coin', 'on Solana', 'Token', 'Club'])}")
        tcon.execute("INSERT OR REPLACE INTO pages (mint, slug, symbol, name, src, first_ts, last_ts, active, enough, "
                     "mcap, vol24, updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (m, f"t{i}", sym, nm, "midcap", now - 9 * D, now, 1, 1, mc, mc * 0.3, now))
    tcon.commit()
    tcon.close()

    icon = istore.connect(paths["insajderi"])
    icon.execute("DELETE FROM i2_events WHERE eid LIKE 'seedtok:%'")
    icon.execute("DELETE FROM i2_part WHERE eid LIKE 'seedtok:%'")
    icon.execute("DELETE FROM i2_pp WHERE owner LIKE 'seedtok:%'")
    if not empty and out["tokens"]:
        owners = [f"seedtok:g{k}" for k in range(8)]
        cls = ["prije_pumpe"] * 5 + ["bot", "kandidat", "snajper"]
        for o, c in zip(owners, cls):
            mem = [b58(o + str(x), 44) for x in range(R.randint(2, 6))]
            icon.execute("INSERT OR REPLACE INTO i2_pp VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (o, json.dumps(mem), len(mem), c, "seed", R.randint(1, 5), R.randint(0, 3), R.randint(3, 8),
                          R.uniform(20, 300), R.uniform(-1, 9), now - 2 * D if c == "prije_pumpe" else None,
                          now - H, now))
            out["groups"].append((o, c, mem))
        picks = R.sample(range(len(out["tokens"])), min(n_pumps, len(out["tokens"])))
        for k, idx in enumerate(picks):
            m, sym, mc = out["tokens"][idx]
            t0 = now - (3 + k * 31) * H   # 20 pumps spread over ~26 days, 14 of them in the last 7 days... roughly
            px = round(R.uniform(0.35, 4.0), 2)
            peak = mc * R.uniform(1.0, 1.4)
            tier = "pumpa15" if peak >= 15e6 else "pumpa2"
            eid = f"seedtok:{m[:8]}:{t0}"
            dur = min(R.choice([2 * H, 9 * H, D + 3 * H, 2 * D, 3 * D]), max(H, now - t0 - 600))
            icon.execute("INSERT OR REPLACE INTO i2_events (eid, kind, token, symbol, t0, mcap0, peak_ts, peak_x, win_end, "
                         "src, tier, peak_mc, n_part) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (eid, "jump", m, sym, t0, peak / (1 + px), t0 + dur, px, t0 + dur + 6 * H, "midcap", tier, peak,
                          5))
            if k % 4 != 3:   # three of four pumps have early buyers of some groups
                for o, c, mem in R.sample(out["groups"], R.randint(1, 4)):
                    w = mem[0]
                    icon.execute("INSERT OR REPLACE INTO i2_part (eid, wallet, owner, buy_ts, sol_in, n_sells, sol_out, "
                                 "first_sell_ts, bought_before, sold_into, lead_s, src) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                                 (eid, w, o, t0 - 3600, 2.0, 1, 5.0, t0 + H, 1, 1, 3600, "helius"))
            out["pumps"].append((eid, m, t0, px, tier))
    icon.commit()
    icon.close()

    if not empty and paths.get("kol"):   # the Cooldog case: an untracked token worth 3,1k $ with an influencer call
        from kol import store as kstore
        kc = kstore.connect(paths["kol"])
        cd = COOLDOG
        kc.execute("INSERT OR REPLACE INTO snaps (token, ts, price, vol_h1, liq, mcap) VALUES (?,?,?,?,?,?)",
                   (cd, now - 1800, 0.0000031, 40, 1900, 3100))
        kc.execute("INSERT OR REPLACE INTO tokens (token, symbol, name, updated) VALUES (?,?,?,?)",
                   (cd, "COOLDOG", "Cooldog", now))
        h = (kc.execute("SELECT handle FROM kols WHERE handle NOT LIKE 'tg:%' AND handle NOT LIKE 'w:%' "
                        "ORDER BY score DESC LIMIT 1").fetchone() or ["seedkol"])[0]
        for k in range(3):
            kc.execute("INSERT OR REPLACE INTO calls (tweet_id, token, handle, ts, url, text, kind, first_by_kol, mcap0, "
                       "r1h, r24h) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (f"seedtok{k}", cd, h, now - (k + 1) * 3 * H, f"https://x.com/{h}/status/{k}", "$COOLDOG", "call",
                        1, 48_000, -0.4, -0.93))
        kc.commit()
        kc.close()
        out["cooldog"] = (cd, h)
    if paused is not None and paths.get("trade"):
        c = sqlite3.connect(paths["trade"])
        c.execute("CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT, ts INTEGER)")
        cols = [r[1] for r in c.execute("PRAGMA table_info(settings)")]
        vals = {"k": "pravi_novac_pauza", "v": json.dumps({"on": bool(paused), "ts": now}), "ts": now}
        use = [x for x in cols if x in vals]
        c.execute(f"INSERT OR REPLACE INTO settings ({','.join(use)}) VALUES ({','.join('?' * len(use))})",
                  [vals[x] for x in use])
        c.commit()
        c.close()
    return out


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else ROOT
    o = seed(paths_in(d), empty="--empty" in sys.argv, paused=None if "--no-pause" in sys.argv else True)
    print(f"seed_tokeni: {len(o['tokens'])} tokena, {len(o['pumps'])} skokova, {len(o['groups'])} skupina u {d}")
