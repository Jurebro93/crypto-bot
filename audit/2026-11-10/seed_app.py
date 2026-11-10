#!/usr/bin/env python3
"""Lokalni podaci za prijedlog dizajna (10.11.2026.): puni SQLite baze u korijenu worktreeja uvjerljivim malim
skupom, da zasloni izgledaju kao na običan dan. NIJE dio aplikacije; služi samo za snimke zaslona.

    python3 audit/2026-11-10/seed_app.py            # odbija ako baze već imaju podatke
    python3 audit/2026-11-10/seed_app.py --reset    # obriše lokalne *.db i napuni ispočetka

Što puni (sve izmišljeno osim KOL računa, koji dolaze iz kol/seed.db.gz što je već u repozitoriju):
  local/market.json  "živo" tržište koje local/sitecustomize.py daje umjesto DexScreenera/Jupitera (bez mreže)
  hype.db            signali, detalji, snimke cijene, stanje tržišta i razine za 24 tokena, kupnje praćenih walleta
  rug.db, topcheck.db  rug provjere i svježa provjera preporučenih tokena
  kol.db             358 KOL-ova i 6969 poziva iz kol/seed.db.gz pomaknutih na danas + pozivi na naše tokene
  wallets.db         26 ocijenjenih novčanika (ocjena izračunata pravim wallets/pnl.py) + lista "dokazani"
  league.db          Natjecanje: 5 igrača, zatvoreni i otvoreni tradeovi, praćenja (copy), dnevnik kopiranja, ideje
  trade.db           Autopilot: postavke, probne (dry) pozicije i nalozi; nikad pravi ključ ni pravi novac
  strat.db, paper.db usporedba strategija i botov demo račun
Prazno ostaje (skupo za puniti, nije na traženim zaslonima): calendar.db (eventi), tg.db (Telegram kanali),
dugo.db (dugoročni), market.db osim makro stanja, usage.db, corr.db, watch.db, koltest.db, analytics.db, minute.db.
"""
import glob
import hashlib
import json
import math
import os
import random
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
NOW = int(time.time())
H, D = 3600, 86400
R = random.Random(20261110)
SOL_USD = 162.0
SOL = "So11111111111111111111111111111111111111112"
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58(seed, n=44):
    h = b"".join(hashlib.sha256(f"{seed}:{i}".encode()).digest() for i in range(3))
    return "".join(B58[b % 58] for b in h[:n])


def mint(sym):
    return b58("mint:" + sym, 40) + "pump"


def guard(reset):
    if os.environ.get("RENDER") or os.environ.get("DATA_DIR") or os.path.exists("/var/data"):
        sys.exit("seed_app: ovo izgleda kao produkcija (RENDER / DATA_DIR / /var/data). Ne pokrećem.")
    if "/wt/" not in ROOT + "/" and not os.environ.get("UIPROP_ANYWHERE"):
        sys.exit(f"seed_app: {ROOT} nije radna kopija (git worktree pod .../wt/). Ne pokrećem.")
    dbs = [p for p in glob.glob(os.path.join(ROOT, "*.db")) if os.path.getsize(p) > 0 and not os.path.islink(p)]
    if any(os.path.islink(p) for p in glob.glob(os.path.join(ROOT, "*.db"))):
        sys.exit("seed_app: *.db su simboličke veze (produkcijski disk). Ne pokrećem.")
    if dbs and not reset:
        sys.exit("seed_app: baze već imaju podatke; pokreni s --reset da ih obrišem i napunim ispočetka.")
    for p in glob.glob(os.path.join(ROOT, "*.db*")):
        os.remove(p)
    for p in (".copy_wake",):
        if os.path.exists(os.path.join(ROOT, p)):
            os.remove(os.path.join(ROOT, p))


# symbol, name, mcap now ($), liquidity ($), change 1 h %, change 24 h %, first seen h ago, last signal min ago,
# strength 0..1 (how good the signals look), rug verdict or None
TOKENS = [
    ("GIGAFROG", "Giga Frog", 412_000, 61_000, 18.4, 142.0, 11, 3, 0.95, "PROLAZI"),
    ("ARIA", "Aria AI", 268_000, 48_500, 6.2, 61.0, 19, 6, 0.88, "PROLAZI"),
    ("MOONCAT", "Moon Cat", 186_000, 39_000, 11.8, 88.0, 7, 2, 0.84, "PROLAZI"),
    ("TURBOX", "Turbo X", 734_000, 96_000, -3.1, 34.0, 30, 11, 0.80, "OPREZ"),
    ("SIGMA", "Sigma Boy", 152_000, 33_200, 24.0, 210.0, 5, 4, 0.78, None),
    ("MOCHI", "Mochi Inu", 96_000, 27_400, 4.4, 19.0, 14, 18, 0.74, "PROLAZI"),
    ("RIZZ", "Rizz Coin", 1_340_000, 148_000, 1.9, 12.0, 52, 25, 0.72, "PROLAZI"),
    ("NYAN", "Nyan Sol", 78_500, 24_100, 9.0, 55.0, 8, 9, 0.70, None),
    ("BORK", "Bork", 241_000, 44_800, -6.5, 27.0, 22, 31, 0.66, "OPREZ"),
    ("VIBE", "Vibe Check", 63_000, 21_700, 14.2, 96.0, 4, 5, 0.64, None),
    ("ZOOMER", "Zoomer", 118_000, 30_300, 2.2, -8.0, 26, 44, 0.60, "PROLAZI"),
    ("LAMBO", "Lambo Soon", 51_000, 19_600, 7.7, 41.0, 6, 14, 0.56, None),
    ("PIXEL", "Pixel Pepe", 305_000, 52_000, -1.4, 9.0, 40, 58, 0.54, "PROLAZI"),
    ("KEK", "Kek Lord", 44_000, 18_200, 3.0, 22.0, 9, 37, 0.50, None),
    ("WAGMI", "Wagmi Dog", 89_000, 25_900, -9.8, -21.0, 33, 72, 0.46, "OPREZ"),
    ("CHADAI", "Chad AI", 172_000, 36_400, 0.8, 5.0, 45, 95, 0.44, None),
    ("FROGE", "Froge", 36_500, 15_800, 5.1, 30.0, 10, 51, 0.40, None),
    ("HODLR", "Hodlr", 58_000, 20_500, -2.6, -4.0, 36, 130, 0.38, None),
    ("DEGEN9", "Degen Nine", 27_000, 12_900, -12.0, -35.0, 16, 66, 0.34, None),      # ispod 30k: pravilo ga ne kupuje
    ("SOLDOGE", "Sol Doge", 520_000, 71_000, 0.3, -2.0, 70, 31 * 60, 0.62, "PROLAZI"),   # stariji od 24 h
    ("PEPEAI", "Pepe AI", 143_000, 31_000, -0.9, -14.0, 80, 40 * 60, 0.52, "OPREZ"),
    ("BONKZ", "Bonkz", 66_000, 22_000, 1.1, 3.0, 96, 52 * 60, 0.45, None),
    ("RUGPULL", "Totally Safe", 31_000, 4_100, -41.0, -78.0, 13, 150, 0.30, "ODBAČEN"),  # rug: ne smije biti preporučen
    ("TRUMPET", "Trumpet", 97_000, 26_000, -4.0, 16.0, 28, 85, 0.48, "VISOK RIZIK"),
]
T = {t[0]: dict(zip(("sym", "name", "mcap", "liq", "ch1", "ch24", "age_h", "last_min", "s", "rug"), t), mint=mint(t[0]))
     for t in TOKENS}
OLD = [f"{a}{b}" for a in ("DOGE", "CAT", "PEPE", "MOON", "SHIB", "APE", "WIF", "BONK") for b in ("X", "2", "INU", "AI", "FI")]
OLD_MINT = {s: mint("old:" + s) for s in OLD}


def price(t):
    return t["mcap"] / 1e9


# ---------------------------------------------------------------------------------------------------- market.json
def seed_market():
    out = {}
    for t in T.values():
        vol24 = t["liq"] * R.uniform(3, 9) * (1 + t["s"])
        if t["rug"] == "ODBAČEN":
            vol24 = t["liq"] * 0.8
        vol1 = vol24 / 24 * R.uniform(0.8, 2.4) * (1.6 if t["ch1"] > 8 else 1)
        buy_share = min(0.75, max(0.3, 0.5 + t["ch1"] / 100))
        tx24 = int(vol24 / R.uniform(110, 190))
        tx1 = max(12, int(vol1 / R.uniform(110, 190)))
        if t["last_min"] > 24 * 60:   # stariji: tiho tržište
            tx1, vol1 = max(3, tx1 // 6), vol1 / 6

        def w(n, v, ch):
            b = int(n * buy_share)
            return {"buys": b, "sells": max(0, n - b)}, round(v, 2), round(ch, 2)
        tx, vol, chg = {}, {}, {}
        for k, n, v, ch in (("m5", max(1, tx1 // 9), vol1 / 9, t["ch1"] / 5), ("h1", tx1, vol1, t["ch1"]),
                            ("h6", int(tx24 / 3.2), vol24 / 3.2, t["ch24"] / 2.4), ("h24", tx24, vol24, t["ch24"])):
            tx[k], vol[k], chg[k] = w(n, v, ch)
        out[t["mint"]] = {
            "chainId": "solana", "dexId": "pumpswap", "url": f"https://dexscreener.com/solana/{t['mint']}",
            "pairAddress": b58("pair:" + t["sym"]), "baseToken": {"address": t["mint"], "name": t["name"], "symbol": t["sym"]},
            "quoteToken": {"address": SOL, "name": "Wrapped SOL", "symbol": "SOL"},
            "priceNative": f"{price(t) / SOL_USD:.12f}", "priceUsd": f"{price(t):.10f}", "txns": tx, "volume": vol,
            "priceChange": chg, "liquidity": {"usd": t["liq"], "base": t["liq"] / 2 / price(t), "quote": t["liq"] / 2 / SOL_USD},
            "fdv": t["mcap"], "marketCap": t["mcap"], "pairCreatedAt": (NOW - int((t["age_h"] + 3) * H)) * 1000,
            "info": {"websites": [], "socials": [{"type": "twitter", "url": f"https://x.com/{t['sym'].lower()}_sol"}]}}
    os.makedirs(os.path.join(HERE, "local"), exist_ok=True)
    with open(os.path.join(HERE, "local", "market.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    return out


# -------------------------------------------------------------------------------------------------------- hype.db
def features(t):
    s = t["s"]
    j = lambda lo=0.75, hi=1.15: max(0.0, min(1.0, s * R.uniform(lo, hi)))   # noqa: E731
    f = {"fresh": round(max(0.05, 1 - t["age_h"] / 60), 2), "turnover": round(j(), 2), "buy_pressure": round(j(0.5, 1.1), 2),
         "momentum": round(max(0, min(0.85, 0.4 + t["ch1"] / 40)), 2), "activity": round(j(), 2), "socials": 1.0 if s > 0.45 else 0.0,
         "narrative": round(j(0.3, 0.9), 2), "telegram": round(j(0.2, 1.0), 2) if s > 0.7 else 0.0,
         "smart_money": 1.0 if s > 0.75 else 0.5 if s > 0.6 else 0.0, "x_buzz": round(j(0.4, 1.0), 2),
         "kol_x": 1.0 if s > 0.62 else 0.0, "kol_wallets": round(j(0.3, 0.9), 2) if s > 0.5 else 0.0,
         "kol_group": 1.0 if s > 0.82 else 0.0, "snaga_volumen": round(j(0.6, 1.1), 2), "snaga_txn": round(j(0.6, 1.1), 2),
         "rast_holdera": round(j(0.4, 1.0), 2), "organski": round(j(0.5, 1.1), 2),
         "konvergencija": 1.0 if s > 0.85 else 0.0, "ozbiljan_projekt": 1.0 if s > 0.9 else 0.0,
         "sumnjivi_socijali": 1.0 if s < 0.36 else 0.0, "market_regime": 0.55}
    return f


def seed_hype(kol_handles, wallets):
    from hype import score as hscore, store as hstore, tokenstatus
    from tiers import store as tstore
    from live import store as lstore
    con = hstore.connect(os.path.join(ROOT, "hype.db"))
    con.executescript(lstore.SCHEMA)
    con.execute("CREATE TABLE IF NOT EXISTS chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER, "
                "sol REAL, PRIMARY KEY (sig, mint))")
    tokenstatus.ensure(con)
    con.executescript(tstore.SCHEMA)
    for col, typ in tstore.CURVE_COLS.items():
        try:
            con.execute(f"ALTER TABLE token_tier ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:
            pass
    weights = hscore.load_weights()
    for t in T.values():
        f = features(t)
        t["features"] = f
        t["hype"] = round(10 + 45 * t["s"] + R.uniform(-3, 3), 1)   # 30-65: kao u produkciji, rijetko iznad 70
        first, last = NOW - int(t["age_h"] * H), NOW - t["last_min"] * 60
        n = max(4, min(28, int((last - first) / 1500)))
        m0 = t["mcap"] / (1 + t["ch24"] / 100) if t["age_h"] >= 24 else t["mcap"] / (1 + t["ch24"] / 100) * 0.9
        for i in range(n + 1):
            ts = int(first + (last - first) * i / n)
            k = i / n
            mc = m0 + (t["mcap"] - m0) * k ** 1.4
            mc *= R.uniform(0.93, 1.09) if i < n else 1
            liq = t["liq"] * (0.7 + 0.3 * k)
            fi = {a: (round(max(0, min(1, b * (0.55 + 0.45 * k) * R.uniform(0.9, 1.1))), 2) if 0 < b < 1 else b) for a, b in f.items()}
            sci = round(t["hype"] * (0.6 + 0.4 * k) * R.uniform(0.95, 1.04), 1) if i < n else t["hype"]
            con.execute("INSERT OR REPLACE INTO hype_signals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (ts, t["mint"], t["sym"], t["name"], b58("pair:" + t["sym"]), f"https://dexscreener.com/solana/{t['mint']}",
                         sci, mc / 1e9, mc, liq, json.dumps(fi if i < n else f), "dexscreener,pumpfun" + (",x" if f["x_buzz"] > 0.4 else ""),
                         json.dumps(weights)))
            hstore.snapshot(con, t["mint"], mc / 1e9, mc, liq, ts)
        infl = R.sample(kol_handles, 2) if f["kol_x"] else []
        smart = R.sample(wallets[:10], 3 if f["smart_money"] == 1 else 1) if f["smart_money"] else []
        top10 = R.uniform(18, 31) if t["s"] > 0.5 else R.uniform(36, 58)
        extra = {"x": {"authors": int(4 + 40 * f["x_buzz"]), "tweets": int(6 + 70 * f["x_buzz"]),
                       "influencers": [[h, R.randint(8, 240) * 1000] for h in infl]},
                 "smart_buyers": smart,
                 "pumpfun": {"top10HoldersPercent": round(top10, 1), "bundlerOwnedPercent": round(R.uniform(1, 9) if t["s"] > 0.4 else R.uniform(16, 30), 1),
                             "devHoldingsPercent": round(R.uniform(0, 2.5), 2), "holders": int(180 + 2400 * t["s"] * R.uniform(0.6, 1.3))},
                 "trend": {"name": t["name"]} if f["narrative"] > 0.6 else None}
        con.execute("INSERT OR REPLACE INTO hype_details VALUES (?,?,?)", (t["mint"], last, json.dumps(extra)))
        has_pair = 0 if t["rug"] == "ODBAČEN" and False else 1
        con.execute("INSERT OR REPLACE INTO token_status VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (t["mint"], has_pair, f"https://dexscreener.com/solana/{b58('pair:' + t['sym'])}", "pumpswap", price(t), t["mcap"],
                     t["liq"], None, None, None, NOW - R.randint(60, 600), None))
        klasa = "event" if False else ("svjezi" if t["age_h"] < 24 else "stariji")
        cols = ("token", "symbol", "first_ts", "last_ts", "razina", "klasa", "t0", "t0_razlog", "t0_ts", "mcap", "liquidity",
                "age_h", "score", "put_brzina", "put_skokovitost", "put_zadrzavanje", "razlog")
        con.execute(f"INSERT OR REPLACE INTO token_tier ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                    (t["mint"], t["sym"], first, last, 3 if t["s"] > 0.8 else 2 if t["s"] > 0.6 else 1 if t["s"] > 0.42 else 0, klasa,
                     "pad" if t["rug"] == "ODBAČEN" else "prolaz", "likvidnost ispod praga" if t["rug"] == "ODBAČEN" else "", first + 120,
                     t["mcap"], t["liq"], t["age_h"], t["hype"], round(R.uniform(0.2, 0.9), 2), round(R.uniform(0.1, 0.7), 2),
                     round(R.uniform(0.3, 0.9), 2), "T1: volumen i kupci drže" if t["s"] > 0.6 else "T0 prošao"))
    # puls (svake 2 min) za tokene na razini 1+: zadnja 3 h
    from hype import pulse as hpulse
    hpulse.ensure(con)
    for t in T.values():
        if t["s"] < 0.6 or t["last_min"] > 24 * 60:
            continue
        hold = int(180 + 2400 * t["s"])
        for i in range(90):
            ts = NOW - t["last_min"] * 60 - i * 120
            k = 1 - i / 90
            mc = t["mcap"] / (1 + t["ch1"] / 100 * (i / 30)) * R.uniform(0.985, 1.015)
            v1 = t["liq"] * R.uniform(0.2, 0.5)
            con.execute("INSERT OR REPLACE INTO token_pulse VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (t["mint"], ts, mc / 1e9, mc, t["liq"], v1 / 12, v1, R.randint(3, 22), R.randint(2, 15), R.randint(40, 190),
                         R.randint(25, 140), int(hold * (0.9 + 0.1 * k)) if i % 15 == 0 else None, "helius" if i % 15 == 0 else None))
    # kupnje i prodaje praćenih walleta (Helius webhook tablica), zadnjih 48 h
    hot = [t for t in T.values() if t["s"] >= 0.6 and t["last_min"] < 24 * 60]
    n = 0
    for w in wallets[:10]:
        for t in R.sample(hot, R.randint(1, 3)):
            ts = NOW - R.randint(4 * 60, 40 * H)
            sol = round(R.choice([0.5, 0.8, 1.0, 1.5, 2.0, 3.2]), 2)
            con.execute("INSERT OR IGNORE INTO chain_trades VALUES (?,?,?,?,?,?)", (b58(f"sig:{n}", 88), w, t["mint"], "buy", ts, sol))
            n += 1
            if R.random() < 0.35 and NOW - ts > 2 * H:
                con.execute("INSERT OR IGNORE INTO chain_trades VALUES (?,?,?,?,?,?)",
                            (b58(f"sig:{n}", 88), w, t["mint"], "sell", ts + R.randint(20 * 60, 2 * H), None))
                n += 1
    con.commit()
    con.close()


# --------------------------------------------------------------------------------------------- rug.db, topcheck.db
def seed_rug():
    con = sqlite3.connect(os.path.join(ROOT, "rug.db"))
    con.execute("""CREATE TABLE IF NOT EXISTS rug_reports (
        mint TEXT, checked_at INTEGER, symbol TEXT, verdict TEXT, score REAL, wash_score REAL,
        bundle_pct REAL, sniper_pct REAL, cluster_pct REAL, top10_pct REAL, dev TEXT, data TEXT,
        PRIMARY KEY (mint, checked_at))""")
    for t in T.values():
        if not t["rug"]:
            continue
        v = t["rug"]
        bad = {"PROLAZI": 0.1, "OPREZ": 0.45, "VISOK RIZIK": 0.75, "ODBAČEN": 1.0}[v]
        ts = NOW - min(int(t["age_h"] * H) - 600, R.randint(20 * 60, 9 * H))
        flags = {"PROLAZI": [], "OPREZ": ["snajperi drže 11% ponude"], "VISOK RIZIK": ["klaster povezanih walleta drži 34%", "dev prodao 80%"],
                 "ODBAČEN": ["bundle 62% ponude", "dev prodao sve"]}[v]
        hard = ["likvidnost povučena (LP ispod $5k)"] if v == "ODBAČEN" else []
        pos = ["3 smart walleta među prvim kupcima", "LP na launchpadu, tvorac ga ne može izvući"] if v == "PROLAZI" else []
        cl = [b58(f"cl:{t['sym']}:{i}") for i in range(int(2 + 9 * bad))]
        r = {"mint": t["mint"], "checked_at": ts, "symbol": t["sym"], "name": t["name"], "verdict": v,
             "score": None if hard else round(100 - 62 * bad), "wash_score": round(8 + 60 * bad), "hard_fails": hard, "flags": flags,
             "positives": pos,
             "launch": {"bundle_pct": round(3 + 60 * bad ** 2, 1), "bundle_wallets": int(1 + 14 * bad), "sniper_pct": round(2 + 14 * bad, 1),
                        "sniper_wallets": int(2 + 10 * bad)},
             "cluster": {"holding_pct": round(4 + 34 * bad, 1), "early_pct": round(5 + 30 * bad, 1), "wallets": cl},
             "holders": {"top10_pct": round(19 + 45 * bad, 1), "fresh_early_pct": round(12 + 50 * bad, 1), "fresh_holders_pct": round(9 + 40 * bad, 1),
                         "top": [{"wallet": b58(f"holder:{t['sym']}:{i}"), "pct": round((4.6 - i * 0.35) * (1 + 2 * bad), 1), "insider": bad > 0.4 and i < 3}
                                 for i in range(10)]},
             "volume": {"round_trip_volume_pct": round(3 + 40 * bad, 1), "top5_volume_pct": round(14 + 50 * bad, 1)},
             "rugcheck": {"insider_pct": round(1 + 20 * bad, 1)}, "authorities": {"mintAuthority": None, "freezeAuthority": None},
             "dev": {"wallet": b58("dev:" + t["sym"]), "tokens_created": int(1 + 12 * bad), "tokens_alive": 1, "hold_pct": round(2 * (1 - bad), 1),
                     "sold_pct": round(100 * bad)},
             "market": {"mcap": t["mcap"], "liquidity": t["liq"], "max_entry_usd_5pct": round(t["liq"] * 0.026),
                        "url": f"https://dexscreener.com/solana/{t['mint']}"}}
        con.execute("INSERT OR REPLACE INTO rug_reports VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (r["mint"], ts, t["sym"], v, r["score"], r["wash_score"], r["launch"]["bundle_pct"], r["launch"]["sniper_pct"],
                     max(r["cluster"]["holding_pct"], r["cluster"]["early_pct"]), r["holders"]["top10_pct"], r["dev"]["wallet"], json.dumps(r)))
    con.commit()
    con.close()


# --------------------------------------------------------------------------------------------------------- kol.db
def seed_kol(wallets, wnames):
    from kol import store as kstore
    con = kstore.connect(os.path.join(ROOT, "kol.db"))
    n = kstore.import_seed(con)
    mx = con.execute("SELECT MAX(ts) FROM calls").fetchone()[0] or NOW
    d = NOW - mx - 7 * 60
    con.execute("UPDATE calls SET ts = ts + ?, measured_ts = measured_ts + ?", (d, d))
    con.execute("UPDATE kols SET first_seen = first_seen + ?, last_seen = last_seen + ?, updated = ?", (d, d, NOW - 900))
    con.execute("UPDATE tokens SET created_ts = created_ts + ?, updated = updated + ?", (d, d))
    con.execute("UPDATE groups SET start_ts = start_ts + ?, end_ts = end_ts + ?", (d, d))
    con.execute("UPDATE signals SET ts = ts + ?", (d,))
    con.execute("UPDATE searches SET last_ts = last_ts + ?", (d,))
    good = []
    for h, fol, stats in con.execute("SELECT handle, followers, stats FROM kols WHERE COALESCE(bot, 0) = 0 ORDER BY score DESC"):
        st = json.loads(stats or "{}")
        if (st.get("measured") or 0) >= 8 and not st.get("trial") and not h.startswith(("tg:", "w:")):
            good.append((h, fol or 5000))
        if len(good) >= 14:
            break
    texts = ["${s} looks ready, chart is clean and volume is real. CA: {m}", "aped ${s} here, team is cooking {m}",
             "${s} sending. early holders are not selling {m}", "adding ${s} on this dip. {m}",
             "${s} is the play today imo {m}"]
    k = 0
    for t in T.values():
        con.execute("INSERT OR REPLACE INTO tokens (token, symbol, name, pair, supply, created_ts, liquidity, tries, updated) "
                    "VALUES (?,?,?,?,?,?,?,0,?)", (t["mint"], t["sym"], t["name"], b58("pair:" + t["sym"]), 1e9,
                                                   NOW - int((t["age_h"] + 3) * H), t["liq"], NOW))
        if not t["features"]["kol_x"]:
            continue
        callers = R.sample(good, 4 if t["s"] > 0.82 else 2 if t["s"] > 0.7 else 1)
        base = NOW - min(int(t["age_h"] * H) - 900, R.randint(25 * 60, 20 * H))
        for j, (h, fol) in enumerate(callers):
            ts = base + j * R.randint(90, 900)
            if ts > NOW - 240:
                ts = NOW - 240 - j * 60
            age = NOW - ts
            m0 = t["mcap"] / (1 + R.uniform(0.05, 0.6) * t["s"])
            r1 = R.uniform(-0.12, 0.5) * (0.6 + t["s"]) if age > H else None
            mx24 = max(r1 or 0, t["mcap"] / m0 - 1) * R.uniform(1.0, 1.4) if age > H else None
            tid = str(1987000000000000000 + k * 7919)
            k += 1
            con.execute(
                "INSERT OR REPLACE INTO calls (tweet_id, token, handle, ts, url, text, followers, likes, retweets, views, kind, "
                "match, source, symbol, first_by_kol, first_overall, p0, mcap0, pre2h, r1h, r6h, r24h, max24, vol_before, "
                "vol_after, vol_lift, rug, complete, measured_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (tid, t["mint"], h, ts, f"https://x.com/{h}/status/{tid}", R.choice(texts).format(s=t["sym"], m=t["mint"]), fol,
                 R.randint(20, 900), R.randint(3, 160), R.randint(2, 90) * 1000, "call", "ca", "x", t["sym"], 1, 1 if j == 0 else 0,
                 m0 / 1e9, m0, R.uniform(-0.05, 0.2), r1, None, None, mx24, t["liq"] * 0.4, t["liq"] * 0.9,
                 R.uniform(1.2, 6.0), 0, 0, NOW - 600 if age > H else None))
    # poznati novčanici (javne liste) i koje od njih webhook prati
    for i, w in enumerate(wallets[:12]):
        con.execute("INSERT OR REPLACE INTO kol_ids (wallet, name, twitter, telegram, source, pnl, wins, losses, rank, first_seen, updated) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (w, wnames[i], (wnames[i] + "_sol") if i < 8 else None, None, "kolscan", round(R.uniform(40, 900), 1),
                                                       R.randint(20, 160), R.randint(10, 120), i + 1, NOW - 20 * D, NOW - H))
    con.execute("INSERT OR REPLACE INTO kv VALUES ('chain_hook', ?)", (json.dumps({"wallets": wallets[:10], "ts": NOW - 900}),))
    con.commit()
    try:
        from kol import score as kscore
        cfg = json.load(open(os.path.join(ROOT, "kol", "config.json")))
        kscore.mark_first(con)
        kscore.build_groups(con, cfg)
        kscore.build_signals(con, cfg, NOW)
        con.commit()
    except Exception as e:  # noqa: BLE001
        print(f"  kol: grupe/signali nisu ponovno složeni: {type(e).__name__}: {e}")
    out = [h for h, _ in good]
    con.close()
    return n, out


# ----------------------------------------------------------------------------------------------------- wallets.db
WNAMES = ["frogdaddy", "solshark", "0xnina", "mintmaxi", "degenzg", "lunarwhale", "kairo", "pump_sensei", "tiho", "dalmatinac",
          "bagholder9", "nocna_smjena"]


def seed_wallets(wallets):
    from wallets import dokazani, pnl, store as wstore
    con = wstore.connect(os.path.join(ROOT, "wallets.db"))
    hot = [t for t in T.values() if t["last_min"] < 24 * 60 and t["rug"] != "ODBAČEN"]
    for i, w in enumerate(wallets):
        skill = max(0.15, min(0.8, 0.72 - i * 0.026 + R.uniform(-0.06, 0.06)))     # win rate
        style = "bot" if i in (17, 22) else "sniper" if i == 19 else "normal"
        n = R.randint(9, 34) if style == "normal" else R.randint(60, 110)
        size = R.choice([0.3, 0.5, 0.8, 1.0, 1.5, 2.0])
        rows, prices, k = [], {}, 0
        wstore.observe(con, w, "", R.choice(["harvest", "retro", "kol", "rug"]), R.choice(["early_buyer", "smart", "top_trader"]), NOW - R.randint(2, 19) * D)
        for j in range(n):
            sym = R.choice(OLD)
            m = mint(f"old:{sym}:{i}:{j}")
            hold = R.randint(12, 600) * 60 if style == "normal" else R.randint(1, 8) * 60
            ts = NOW - hold - (R.randint(1 * H, 19 * D) if j > 3 else R.randint(1 * H, 4 * D))   # a few after the cut
            sol_in = round(size * R.uniform(0.6, 1.5), 3)
            win = R.random() < skill
            out = sol_in * (R.uniform(1.15, 3.4) if win else R.uniform(0.25, 0.92))
            rows += [{"sig": b58(f"w{i}b{j}", 88), "ts": ts, "mint": m, "tokens": 1e6, "sol": -sol_in, "kind": "buy"},
                     {"sig": b58(f"w{i}s{j}", 88), "ts": ts + hold, "mint": m, "tokens": -1e6, "sol": round(out, 3), "kind": "sell"}]
        for t in R.sample(hot, R.randint(0, 3)):    # otvorene pozicije u našim tokenima
            ts = NOW - R.randint(20 * 60, 30 * H)
            sol_in = round(size * R.uniform(0.6, 1.4), 3)
            p_then = price(t) / SOL_USD / (1 + R.uniform(-0.2, 0.9))
            rows.append({"sig": b58(f"w{i}o{k}", 88), "ts": ts, "mint": t["mint"], "tokens": sol_in / p_then, "sol": -sol_in, "kind": "buy"})
            prices[t["mint"]] = price(t) / SOL_USD
            wstore.observe(con, w, t["mint"], "hype", "early_buyer" if R.random() < 0.6 else "smart", ts, sol_in)
            k += 1
        rows.sort(key=lambda r: r["ts"])
        con.executemany("INSERT OR IGNORE INTO wallet_trades VALUES (?,?,?,?,?,?,?)",
                        [(w, r["sig"], r["ts"], r["mint"], r["tokens"], r["sol"], r["kind"]) for r in rows])
        labels = {"bot"} if style == "bot" else {"sniper"} if style == "sniper" else set()
        if i == 24:
            labels = {"dev"}
        for lab in labels:
            wstore.label(con, w, lab)
        if i >= 23 and i != 24:     # u redu čekanja, još neocijenjen
            continue
        pos = pnl.positions(rows, prices)
        s = pnl.score(pos, rows, now=NOW, labels=labels)
        tier, nxt = pnl.tier(s)
        wstore.save_score(con, w, s, tier, NOW + (nxt or 7 * D), last_tx_ts=rows[-1]["ts"], history_from=rows[0]["ts"], credits=R.randint(20, 90))
    con.commit()
    try:
        dokazani.ensure(con)
        dokazani.run(con, now=NOW, log=lambda *a: None)
        con.commit()
    except Exception as e:  # noqa: BLE001
        print(f"  wallets: lista dokazanih nije složena: {type(e).__name__}: {e}")
    n_ok = con.execute("SELECT COUNT(*) FROM wallets WHERE stats IS NOT NULL").fetchone()[0]
    try:
        n_dok = con.execute("SELECT COUNT(*) FROM dokazani WHERE passed=1").fetchone()[0]
    except sqlite3.OperationalError:
        n_dok = 0
    con.close()
    return n_ok, n_dok


# ------------------------------------------------------------------------------------------------------ league.db
def _closed(con, store, user, sym, m, size, ret, opened, held, liq, mcap, source=""):
    px = mcap / 1e9
    tid = store.buy(con, user, m, sym, size, px, liq, source=source, score=R.randint(35, 80), mcap=mcap)
    store.sell(con, user, tid, px * (1 + ret), liq, note=R.choice(["", "", "TP +30%", "SL -20%", "ručno"]), mcap=mcap * (1 + ret))
    con.execute("UPDATE trades SET opened_ts=?, closed_ts=? WHERE id=?", (opened, opened + held, tid))
    return tid


def seed_league(kols, wallets):
    from league import copy, members, profiles, roles, store
    con = store.connect()
    copy.ensure(con)
    start = NOW - 12 * D
    # dvoje prijatelja registriranih pozivnicom (uz Jure, Ivan, Panda iz UI_USERS)
    mcon = members.connect()
    for name in ("Marko", "Lana"):
        mcon.execute("INSERT OR IGNORE INTO members (name, salt, hash, created, invite) VALUES (?,?,?,?,?)",
                     (name, "00", "seed-bez-lozinke", start + 2 * D, "seed"))
    mcon.commit()
    mcon.close()
    plan = {   # user: (closed trades, win rate, typical size, open positions)
        "Jure": (11, 0.55, 80, ["GIGAFROG", "ARIA", "MOCHI", "TURBOX"]),
        "Ivan": (16, 0.44, 60, ["SIGMA", "NYAN", "BORK"]),
        "Panda": (7, 0.71, 120, ["MOONCAT", "RIZZ"]),
        "Marko": (9, 0.33, 100, ["VIBE", "LAMBO", "WAGMI"]),
        "Lana": (4, 0.50, 50, ["ARIA"]),
    }
    hot = [t for t in T.values() if t["rug"] != "ODBAČEN"]
    for user, (n, wr, size, open_syms) in plan.items():
        con.execute("INSERT OR REPLACE INTO accounts VALUES (?,?,?)", (user, 1000.0, start if user in ("Jure", "Ivan", "Panda") else start + 2 * D))
        con.commit()
        times = sorted(R.randint(6 * H, 11 * D) for _ in range(n))
        for back in reversed(times):
            win = R.random() < wr
            ret = R.uniform(0.1, 0.7) if win else -R.uniform(0.08, 0.4)
            if R.random() < 0.5:
                sym = R.choice(OLD)
                m, liq, mc = OLD_MINT[sym] if False else mint(f"old:{sym}:{user}:{back}"), R.randint(18, 90) * 1000, R.randint(45, 900) * 1000
            else:
                t = R.choice(hot)
                sym, m, liq, mc = t["sym"] + "", mint(f"prev:{t['sym']}:{user}:{back}"), t["liq"], t["mcap"] * R.uniform(0.4, 1.2)
            src = "copy @" + R.choice(kols[:4]) if user == "Jure" and R.random() < 0.3 else ""
            _closed(con, store, user, sym, m, round(size * R.uniform(0.5, 1.6)), ret, NOW - back, R.randint(15, 900) * 60, liq, mc, src)
        for k, sym in enumerate(open_syms):
            t = T[sym]
            chg = (0.34, -0.12, 0.08, -0.21, 0.52)[k] + R.uniform(-0.04, 0.04) if user == "Jure" else R.uniform(-0.25, 0.6)
            mc0 = t["mcap"] / (1 + chg)
            src = ("copy @" + kols[0]) if user == "Jure" and k == 1 else ""
            tid = store.buy(con, user, t["mint"], sym, round(size * R.uniform(0.7, 1.5)), mc0 / 1e9, t["liq"], source=src,
                            score=round(60 + 30 * t["s"]), mcap=mc0)
            con.execute("UPDATE trades SET opened_ts=? WHERE id=?", (NOW - R.randint(25 * 60, 28 * H), tid))
            if user == "Jure" and k in (0, 2):
                try:
                    from league import auto
                    auto.set_auto(con, user, tid, "tpsl", tp="50%", sl="-20%")
                except Exception as e:  # noqa: BLE001
                    print(f"  league: auto TP/SL nije postavljen: {type(e).__name__}: {e}")
        con.commit()
    # profili: e-mail (bez njega svaka stranica ima žutu kutiju "upiši e-mail"), mreže, opis
    try:
        profiles._set("Jure", email="jure@example.com", social=json.dumps({"x": "jure_memesonar"}), bio="Gradim MemeSonar.")
        profiles._set("Ivan", email="ivan@example.com", bio="Lovim rane pozive.")
        profiles._set("Panda", email="panda@example.com")
    except Exception as e:  # noqa: BLE001
        print(f"  league: profili nisu postavljeni: {type(e).__name__}: {e}")
    # copy trading: koga tko prati, i dnevnik kopiranja
    f1 = copy.follow(con, "Jure", "kol", kols[0], label="@" + kols[0], size_usd=25, per_day=5, exit_mode="smart")
    f2 = copy.follow(con, "Jure", "kol", kols[1], label="@" + kols[1], size_usd=25, per_day=3, exit_mode="tpsl", tp="50%", sl="-20%")
    f3 = copy.follow(con, "Jure", "wallet", wallets[0], label=WNAMES[0], size_usd=40, per_day=5, exit_mode="mirror")
    copy.follow(con, "Ivan", "kol", kols[2], label="@" + kols[2], size_usd=25, per_day=5, exit_mode="smart")
    # račun pravog novca (Autopilot) prati dva influencera i dva dokazana novčanika
    con.execute("INSERT OR IGNORE INTO accounts VALUES (?,?,?)", ("pravi-trade", 1e9, start))
    a1 = copy.follow(con, "pravi-trade", "kol", kols[0], label="@" + kols[0], size_usd=15, per_day=5, exit_mode="podaci")
    a2 = copy.follow(con, "pravi-trade", "kol", kols[3], label="@" + kols[3], size_usd=15, per_day=5, exit_mode="tpsl", tp="15%", sl="-20%")
    a3 = copy.follow(con, "pravi-trade", "wallet", wallets[1], label=WNAMES[1], size_usd=15, per_day=5, exit_mode="tpsl", tp="15%", sl="-20%")
    a4 = copy.follow(con, "pravi-trade", "wallet", wallets[2], label=WNAMES[2], size_usd=15, per_day=5, exit_mode="mirror")
    con.execute("UPDATE follows SET created = created - ?", (5 * D,))
    # tradeovi koje su praćenja otvorila (stupci Ulaza / Uspješnost / Zarada na Copy tradingu i Autopilotu)
    con.execute("UPDATE trades SET follow_id=?, source=? WHERE user='Jure' AND source LIKE 'copy %' AND id % 2 = 0", (f1, "copy @" + kols[0]))
    con.execute("UPDATE trades SET follow_id=?, source=? WHERE user='Jure' AND source LIKE 'copy %' AND follow_id IS NULL", (f2, "copy @" + kols[1]))
    for i in range(9):
        fid, who = R.choice([(a1, "@" + kols[0]), (a1, "@" + kols[0]), (a2, "@" + kols[3]), (a3, "wallet " + WNAMES[1]), (a4, "wallet " + WNAMES[2])])
        sym = R.choice(OLD)
        tid = _closed(con, store, "pravi-trade", sym, mint(f"ap:{sym}:{i}"), 15, R.choice([0.15, 0.15, 0.15, -0.2, -0.2, 0.08, -0.11]),
                      NOW - R.randint(3 * H, 5 * D), R.randint(6, 58) * 60, R.randint(25, 90) * 1000, R.randint(60, 700) * 1000, "copy " + who)
        con.execute("UPDATE trades SET follow_id=? WHERE id=?", (fid, tid))
    # botov 2. krug je u produkciji krenuo 4.11.; na svježoj bazi aplikacija ga upiše s današnjim datumom
    con.execute("UPDATE rekts SET ts=? WHERE user='bot'", (NOW - 6 * D,))
    notes = [("ulaz", "kupljeno za $25 na MC ${mc}, {late} s nakon poziva"), ("preskočeno", "vidjeli smo ga tek 14 min nakon poziva"),
             ("preskočeno", "MC ${mc} je ispod 30k"), ("ulaz", "kupljeno za $25 na MC ${mc}, {late} s nakon poziva"),
             ("izlaz", "Smart sell: +{p} % na pola pozicije, ostatak uz prateći stop"), ("preskočeno", "cijena je već +38 % od poziva"),
             ("ulaz", "kupljeno za $15 na MC ${mc}, {late} s nakon poziva"), ("preskočeno", "dnevni limit ulaza je dosegnut"),
             ("izlaz", "TP +15 %: prodano sve"), ("preskočeno", "likvidnost ispod $20k")]
    toks = [t for t in T.values() if t["last_min"] < 24 * 60]
    used = set()
    for i in range(26):
        fid = R.choice([f1, f1, f2, f3, a1, a1, a2, a3, a4])
        t = R.choice(toks)
        action, note = notes[i % len(notes)]
        side = "sell" if action == "izlaz" else "buy"
        if (fid, t["mint"], side) in used:
            continue
        used.add((fid, t["mint"], side))
        ts = NOW - R.randint(6 * 60, 30 * H)
        copy._log(con, {"id": fid}, t["mint"], side, ts - R.randint(8, 140), ts, action,
                  note.format(mc=f"{t['mcap'] * R.uniform(0.6, 1.0):,.0f}", late=R.randint(4, 55), p=R.randint(15, 60)), t["sym"])
    for user, text, st in (("Ivan", "Alarm na mobitel kad praćeni novčanik kupi token.", "u radu"),
                           ("Panda", "Tamna tema, navečer mi je sve prejako bijelo.", "novo"),
                           ("Marko", "Manje teksta na Autopilotu, ne znam gdje gledati.", "novo")):
        try:
            store.add_idea(con, user, text)
        except Exception:  # noqa: BLE001
            pass
    con.commit()
    out = {"f": (a1, a2, a3, a4)}
    con.close()
    try:
        roles.reset_cache()
        profiles.reset_cache()
    except Exception:  # noqa: BLE001
        pass
    return out


# ------------------------------------------------------------------------------------------------------- trade.db
def seed_trade(kols):
    from trade import executor, settings
    con = executor.connect(settings.DB)
    for k, v in (("on", True), ("wallet_pub", b58("autopilot-wallet")), ("heartbeat", NOW), ("size_sol", 0.1), ("max_open", 5),
                 ("tp_pct", 15)):
        settings.put(con, k, v, "Jure")
    LAM = executor.LAMPORTS
    closed = [("MOCHI", 0.1, 0.1172, 190, 55), ("NYAN", 0.1, 0.0791, 520, 38), ("BORK", 0.1, 0.1156, 700, 64), ("ZOOMER", 0.1, 0.1149, 1100, 47),
              ("PIXEL", 0.1, 0.0803, 1500, 22), ("LAMBO", 0.1, 0.1310, 2300, 58), ("KEK", 0.1, 0.0764, 2900, 41), ("CHADAI", 0.1, 0.1151, 4000, 70)]
    opened = [("GIGAFROG", 0.1, 42, "@" + kols[0]), ("ARIA", 0.1, 133, "@" + kols[3]), ("MOONCAT", 0.1, 17, "wallet " + WNAMES[1])]

    def order(ts, pid, tok, side, status, ain=None, aout=None, reason="", error=None, cost=1.4):
        con.execute("INSERT INTO orders (ts, position_id, token, side, mode, amount_in, amount_out, cost_pct, status, reason, error, "
                    "signature, request_id, route, code, fee_lamports, prio_lamports) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (ts, pid, tok, side, "dry", ain, aout, cost, status, reason, error, None, None, "v2", None, 5000, 120000))
    for sym, sin, sback, mins_ago, held in closed:
        t = T[sym]
        ts = NOW - mins_ago * 60
        cur = con.execute("INSERT INTO positions (paper_id, token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, qty_left, "
                          "sol_back, fills_done, closed_ts, league_id, fees_sol) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (None, t["mint"], sym, ts, "dry", "closed", "TP +15 %" if sback > sin else "SL -20 %", sin, 10 ** 12, 0, sback, 2,
                           ts + held * 60, None, 0.002))
        order(ts, cur.lastrowid, t["mint"], "buy", "dry", int(sin * LAM), 10 ** 12, "kopija @" + R.choice(kols[:4]))
        order(ts + held * 60, cur.lastrowid, t["mint"], "sell", "dry", 10 ** 12, int(sback * LAM), "TP +15 %" if sback > sin else "SL -20 %")
    for sym, sin, mins_ago, who in opened:
        t = T[sym]
        ts = NOW - mins_ago * 60
        cur = con.execute("INSERT INTO positions (paper_id, token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, qty_left, "
                          "sol_back, fills_done, closed_ts, league_id, fees_sol) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (None, t["mint"], sym, ts, "dry", "open", "kopija " + who, sin, 10 ** 12, 10 ** 12 if sym != "ARIA" else 5 * 10 ** 11,
                           0.0 if sym != "ARIA" else 0.0575, 0 if sym != "ARIA" else 1, None, None, 0.001))
        order(ts, cur.lastrowid, t["mint"], "buy", "dry", int(sin * LAM), 10 ** 12, "kopija " + who)
        if sym == "ARIA":
            order(ts + 40 * 60, cur.lastrowid, t["mint"], "sell", "dry", 5 * 10 ** 11, int(0.0575 * LAM), "TP +15 % na pola pozicije")
    for sym, mins_ago, why in (("DEGEN9", 9, "MC ispod 30k"), ("TRUMPET", 26, "rug provjera: VISOK RIZIK"), ("VIBE", 61, "signal star 240 s"),
                               ("FROGE", 95, "bez dokaza u demu"), ("HODLR", 170, "likvidnost ispod $20k"), ("WAGMI", 260, "signal star 410 s")):
        t = T[sym]
        ts = NOW - mins_ago * 60
        cur = con.execute("INSERT INTO positions (paper_id, token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, qty_left, "
                          "sol_back, fills_done, closed_ts, league_id, fees_sol) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (None, t["mint"], sym, ts, "dry", "blocked", why, 0, 0, 0, 0, 0, None, None, 0))
        order(ts, cur.lastrowid, t["mint"], "buy", "blocked", None, None, why)
    con.commit()
    con.close()


# ---------------------------------------------------------------------------------------------- strat.db, paper.db
def seed_strat():
    from strat import run, store as sstore
    con = sstore.connect()
    cfg = run.load_config()
    keys = [s["key"] if isinstance(s, dict) else s for s in (cfg.get("strategies") or [])] or list(getattr(run, "STRATS", []))
    start = NOW - 9 * D
    sstore.kv_set(con, "start_ts", start) if hasattr(sstore, "kv_set") else con.execute("INSERT OR REPLACE INTO kv VALUES ('start_ts', ?)", (str(start),))
    bank = float(cfg.get("bankroll_usd", 1000))
    drift = dict(zip(keys, [0.021, -0.012, 0.009, 0.004, -0.018, 0.013, -0.006]))
    hot = [t for t in T.values() if t["rug"] != "ODBAČEN"]
    for key in keys:
        v, n_cl = bank, R.randint(14, 40)
        for i in range(n_cl):
            t = R.choice(hot)
            ret = R.gauss(drift.get(key, 0) * 3, 0.22)
            ret = max(-0.6, min(1.8, ret))
            size = float(cfg.get("size_usd", 50))
            ts = start + int((NOW - start - 2 * H) * (i + R.random()) / n_cl)
            con.execute("INSERT OR IGNORE INTO positions (strat, token, symbol, url, why, signal_ts, seen_ts, entry_ts, entry_mcap, size_usd, "
                        "status, state, last_ts, last_px, last_liq, pnl_usd, ret, closed_ts, exit_reason, close_reason) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (key, mint(f"strat:{key}:{i}"), R.choice(OLD), None, "seed", ts - 30, ts - 10, ts, R.randint(40, 600) * 1000, size, "closed",
                         "{}", ts + 3000, None, 30000, round(size * ret, 2), ret, ts + R.randint(600, 7200), "tp" if ret > 0 else "sl", ""))
        for t in R.sample(hot, 2):
            ts = NOW - R.randint(20 * 60, 5 * H)
            ret = R.uniform(-0.15, 0.4)
            con.execute("INSERT OR IGNORE INTO positions (strat, token, symbol, url, why, signal_ts, seen_ts, entry_ts, entry_mcap, size_usd, "
                        "status, state, last_ts, last_px, last_liq, pnl_usd, ret) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (key, t["mint"], t["sym"], f"https://dexscreener.com/solana/{t['mint']}", "seed", ts - 30, ts - 10, ts, t["mcap"] / (1 + ret),
                         50.0, "open", "{}", NOW - 60, price(t), t["liq"], round(50 * ret, 2), ret))
        steps = int((NOW - start) / 1800)
        for i in range(steps + 1):
            v += bank * (drift.get(key, 0) / 48 + R.gauss(0, 0.004))
            con.execute("INSERT OR REPLACE INTO equity VALUES (?,?,?)", (start + i * 1800, key, round(v, 2)))
    con.commit()
    con.close()
    return keys


def seed_paper():
    from paper import store as pstore
    con = pstore.connect(os.path.join(ROOT, "paper.db"))
    hot = [t for t in T.values() if t["rug"] != "ODBAČEN"]
    for i in range(34):
        t = R.choice(hot)
        ts = NOW - R.randint(2 * H, 11 * D)
        ret = max(-0.5, min(1.6, R.gauss(0.02, 0.25)))
        con.execute("INSERT INTO trades (token, symbol, opened_ts, closed_ts, status, exit_reason, size_usd, entry_px, entry_eff, pnl_usd, ret, "
                    "max_ret, min_ret, state, config) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (mint(f"paper:{i}"), R.choice(OLD), ts, ts + R.randint(900, 20000), "closed", "tp" if ret > 0 else "sl", 50.0, 1e-4, 1.02e-4,
                     round(50 * ret, 2), ret, max(ret, 0) + 0.1, min(ret, 0) - 0.05, "{}", "{}"))
    for t in R.sample(hot, 3):
        ts = NOW - R.randint(30 * 60, 6 * H)
        ret = R.uniform(-0.12, 0.35)
        cur = con.execute("INSERT INTO trades (token, symbol, opened_ts, status, size_usd, entry_px, entry_eff, pnl_usd, ret, max_ret, min_ret, "
                          "state, config) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (t["mint"], t["sym"], ts, "open", 50.0, price(t) / (1 + ret), price(t) / (1 + ret) * 1.02, round(50 * ret, 2), ret,
                           max(ret, 0.05), min(ret, -0.03), "{}", "{}"))
        con.execute("INSERT OR REPLACE INTO candidates (token, symbol, first_ts, origin, sources, score, features, price, liquidity, mcap, "
                    "decision, reason, rug_verdict, rug_score, rug_flags, trade_id, url) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (t["mint"], t["sym"], ts - 120, "hype", "dexscreener,x", t["hype"], json.dumps(t["features"]), price(t), t["liq"], t["mcap"],
                     "ulaz", "prošao sva pravila", t["rug"], 10, "[]", cur.lastrowid, f"https://dexscreener.com/solana/{t['mint']}"))
    con.commit()
    con.close()


def seed_makro():
    """market.db: BTC i ETH dnevno (40 dana) + BTC po satu, stanje složeno pravim market/makro.collect."""
    from market import makro, store as mstore
    con = mstore.connect()
    day = NOW // D * D
    btc = [(day - (39 - i) * D, 98_000 * (1 + 0.0022 * i + 0.012 * math.sin(i / 3))) for i in range(40)]
    eth = [(day - (39 - i) * D, 3_350 * (1 + 0.0015 * i + 0.015 * math.sin(i / 4))) for i in range(40)]
    con.executemany("INSERT OR REPLACE INTO btc VALUES (?,?)", btc)
    con.executemany("INSERT OR REPLACE INTO price VALUES (?,?)", [(d, SOL_USD * (0.9 + 0.1 * i / 39)) for i, (d, _) in enumerate(btc)])
    hourly = [(NOW - (47 - i) * H, btc[-1][1] * (1 + 0.0004 * (i - 47))) for i in range(48)]
    r = makro.collect(con, NOW, eth=eth, btc_h=hourly)
    con.commit()
    con.close()
    return r


def seed_topcheck(market):
    """Svježa provjera prvih 20 prijedloga, složena pravim topcheck/state.classify i topcheck/safety.judge."""
    from topcheck import safety, state, store as tstore
    con = tstore.connect()
    ranked = sorted([t for t in T.values() if t["last_min"] < 24 * 60], key=lambda t: -t["s"])[:20]
    for i, t in enumerate(ranked):
        st = state.classify(market[t["mint"]])
        bad = t["rug"] in ("ODBAČEN", "VISOK RIZIK")
        rc = {"mint_auth": None, "freeze_auth": None, "rugged": t["rug"] == "ODBAČEN", "launchpad": "pump.fun", "lp_locked": 100.0,
              "has_market": True, "top10": round(R.uniform(17, 29), 1) if not bad else round(R.uniform(52, 71), 1), "insiders": 0.0,
              "dev_pct": round(R.uniform(0, 2), 1) if not bad else 12.0, "creator_tokens": 2 if not bad else 14,
              "holders": int(180 + 2400 * t["s"]), "fee": 0, "perm_delegate": False, "non_transferable": False, "transfer_hook": False,
              "frozen_default": False, "danger": [] if not bad else ["Low Liquidity"], "decimals": 6, "supply": 1e15}
        sell = {"ok": True, "ratio": 0.97 if not bad else 0.71, "impact": 1.4 if not bad else 18.0, "err": None}
        sf = safety.judge(t["mint"], rc, sell, None)
        tstore.put(con, {"token": t["mint"], "symbol": t["sym"], "rank": i + 1, "ts": NOW - R.randint(20, 170), "price": price(t),
                         "mcap": t["mcap"], "liq": t["liq"], "state": st["state"] if st else None,
                         "state_json": json.dumps(st, ensure_ascii=False) if st else None, "verdict": sf["verdict"],
                         "safety_json": json.dumps(sf, ensure_ascii=False), "rc_json": json.dumps(rc), "rc_ts": NOW - 400,
                         "sell_json": json.dumps(sell), "sell_ts": NOW - 400, "full_ts": NOW - 5 * H})
    con.commit()
    con.close()


def main():
    guard("--reset" in sys.argv)
    wallets = [b58(f"wallet:{i}") for i in range(26)]
    print("market.json …")
    market = seed_market()
    print("kol.db (uvoz kol/seed.db.gz, pomak na danas) …")
    for t in T.values():
        t["features"] = features(t)
    n_calls, kols = seed_kol_first(wallets)
    print(f"  {n_calls} poziva uvezeno; najbolji: {', '.join(kols[:5])}")
    print("hype.db …")
    seed_hype(kols, wallets)
    seed_kol_chain()
    print("rug.db, topcheck.db …")
    seed_rug()
    seed_topcheck(market)
    try:
        r = seed_makro()
        print("market.db: makro", (r or {}).get("btc", {}).get("state"), (r or {}).get("score"))
    except Exception as e:  # noqa: BLE001
        print(f"  market.db nije napunjen: {type(e).__name__}: {e}")
    print("wallets.db …")
    n_ok, n_dok = seed_wallets(wallets)
    print(f"  {n_ok} ocijenjenih novčanika, {n_dok} dokazanih dvaput")
    print("league.db …")
    seed_league(kols, wallets)
    print("trade.db …")
    seed_trade(kols)
    print("strat.db, paper.db …")
    try:
        print("  strategije:", ", ".join(seed_strat()))
    except Exception as e:  # noqa: BLE001
        print(f"  strat.db nije napunjen: {type(e).__name__}: {e}")
    seed_paper()
    with open(os.path.join(HERE, "local", "seed.json"), "w", encoding="utf-8") as f:
        json.dump({"token": T["GIGAFROG"]["mint"], "kol": kols[0], "wallet": wallets[0], "seeded": NOW,
                   "tokens": {s: t["mint"] for s, t in T.items()}, "kols": kols, "wallets": wallets[:12]}, f, indent=1)
    print("gotovo. Sljedeće: bash audit/2026-11-10/run_local.sh  (prijava: Jure / demo)")


def seed_kol_first(wallets):
    return seed_kol(wallets, WNAMES)


def seed_kol_chain():
    """Kupnje praćenih walleta iz hype.db chain_trades u kol.db kao pozivi buy/sell (nakon što hype.db postoji)."""
    from kol import collect, store as kstore
    con = kstore.connect(os.path.join(ROOT, "kol.db"))
    try:
        n = collect.from_chain(con, os.path.join(ROOT, "hype.db"))
        con.commit()
        print(f"  kol.db: {n} kupnji/prodaja praćenih novčanika")
    except Exception as e:  # noqa: BLE001
        print(f"  kol: from_chain nije uspio: {type(e).__name__}: {e}")
    con.close()


if __name__ == "__main__":
    main()
