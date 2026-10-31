"""Puls: what a token that already earned attention does over time, and the "snaga" features built from it.

Problem it solves: the hype scan only re-scores a token while one of the free feeds still lists it, so yesterday's
featured candidate sat on the dashboard with a 6 h old score. Now every token that reached razina >= 1 in the last
24 h (`retained`) is put back into every scan, its DexScreener numbers (volume, transactions) are written to
`token_pulse` each pass, and its holder count comes from Helius at most every `holderi_svakih_min` minutes, under a
daily credit cap. From that series come features the learning loop weighs like any other:

  snaga_volumen   volume of the last hour vs the best hour in the window (1 = still at its peak)
  snaga_txn       transactions per hour vs the best hour (1 = steady)
  rast_holdera    holder growth per hour (10 %/h = 1)
  organski        new holders per transaction (0.3 = 1): wash-traded tokens churn transactions without new holders

Everything is in hype.db, written only by the scan (one writer per file).
"""
import json
import os
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(HERE, "tiers", "config.json")
SCHEMA = """
CREATE TABLE IF NOT EXISTS token_pulse (
    token TEXT, ts INTEGER, price REAL, mcap REAL, liquidity REAL,
    vol_m5 REAL, vol_h1 REAL, buys_m5 INTEGER, sells_m5 INTEGER, buys_h1 INTEGER, sells_h1 INTEGER,
    holders INTEGER, holders_src TEXT, PRIMARY KEY (token, ts));
CREATE INDEX IF NOT EXISTS token_pulse_ts ON token_pulse (ts);
"""
DEFAULTS = {"max": 30, "sati": 24, "holderi_svakih_min": 30, "holderi_kredita_dan": 20000, "holderi_stranica_max": 3,
            "prozor_h": 6, "cuvaj_dana": 7}
FEATURES = ("snaga_volumen", "snaga_txn", "rast_holdera", "organski")


def config():
    try:
        with open(CONFIG) as f:
            return {**DEFAULTS, **(json.load(f).get("zadrzi") or {})}
    except Exception:
        return dict(DEFAULTS)


def ensure(con):
    con.executescript(SCHEMA)


def _clip(x):
    return max(0.0, min(1.0, x))


# ---------- which tokens stay in the scan ----------

def retained(con, cfg=None, now=None):
    """Tokens that reached razina >= 1 in the last `sati` hours and did not fail T0, best score first."""
    cfg = cfg or config()
    now = now or time.time()
    try:
        rows = con.execute("SELECT token FROM token_tier WHERE last_ts >= ? AND razina >= 1 AND COALESCE(t0, '') != 'pad' "
                           "ORDER BY COALESCE(score, 0) DESC, last_ts DESC LIMIT ?",
                           (int(now - cfg["sati"] * 3600), int(cfg["max"]))).fetchall()
    except sqlite3.OperationalError:  # no token_tier yet
        return []
    return [r[0] for r in rows]


# ---------- recording ----------

def record(con, token, p, now=None, holders=None, holders_src=None):
    """One pulse row from a DexScreener pair (and a holder count when one was fetched this pass)."""
    vol, tx = p.get("volume") or {}, p.get("txns") or {}
    m5, h1 = tx.get("m5") or {}, tx.get("h1") or {}
    con.execute("INSERT OR REPLACE INTO token_pulse VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (token, int(now or time.time()), float(p.get("priceUsd") or 0), p.get("marketCap") or p.get("fdv") or 0,
                 (p.get("liquidity") or {}).get("usd") or 0, vol.get("m5") or 0, vol.get("h1") or 0,
                 m5.get("buys", 0), m5.get("sells", 0), h1.get("buys", 0), h1.get("sells", 0), holders, holders_src))


def prune(con, days=None):
    days = days or config()["cuvaj_dana"]
    con.execute("DELETE FROM token_pulse WHERE ts < ?", (int(time.time() - days * 86400),))


def series(con, token, window_h, now=None):
    now = now or time.time()
    return [dict(zip(("ts", "price", "mcap", "liquidity", "vol_m5", "vol_h1", "buys_m5", "sells_m5", "buys_h1",
                      "sells_h1", "holders", "holders_src"), r))
            for r in con.execute("SELECT ts, price, mcap, liquidity, vol_m5, vol_h1, buys_m5, sells_m5, buys_h1, sells_h1, "
                                 "holders, holders_src FROM token_pulse WHERE token=? AND ts >= ? ORDER BY ts",
                                 (token, int(now - window_h * 3600)))]


# ---------- holders (Helius DAS getTokenAccounts, 10 credits per page) ----------

def holders_last(con, token):
    r = con.execute("SELECT ts, holders FROM token_pulse WHERE token=? AND holders IS NOT NULL ORDER BY ts DESC LIMIT 1",
                    (token,)).fetchone()
    return (r[0], r[1]) if r else (0, None)


def holders_due(con, token, cfg, now=None):
    ts, _ = holders_last(con, token)
    return (now or time.time()) - ts >= cfg["holderi_svakih_min"] * 60


def credits_today(con, now=None):
    """Helius credits the holder counts cost since midnight UTC, from usage.db when it is there."""
    try:
        from usage import meter
        day = int((now or time.time()) // 86400 * 86400)
        mc = meter.connect()
        try:
            r = mc.execute("SELECT COALESCE(SUM(amount), 0) FROM usage WHERE service='helius' AND method='getTokenAccounts' "
                           "AND hour >= ?", (day,)).fetchone()
            return float(r[0] or 0)
        finally:
            mc.close()
    except Exception:
        return 0.0


def holder_count(mint, max_pages=3):
    """Number of wallets holding `mint` (zero balances excluded); `max_pages` x 1000 is the ceiling reported."""
    from rugfilter import helius
    total, page = 0, 1
    while page <= max_pages:
        res = helius.rpc("getTokenAccounts", {"mint": mint, "limit": 1000, "page": page,
                                              "options": {"showZeroBalance": False}})
        accts = res.get("token_accounts") or []
        total += len({a.get("owner") for a in accts if a.get("owner")})
        if len(accts) < 1000:
            break
        page += 1
    return total


# ---------- strength features from the series ----------

def _retention(vals):
    """Last reading vs the best reading in the window; needs a real peak."""
    vals = [v for v in vals if v is not None]
    if len(vals) < 2 or max(vals) <= 0:
        return None
    return _clip(vals[-1] / max(vals))


def strength(rows, now=None):
    """Features from pulse rows ordered by ts; {} until there is at least 1 h of readings (3+ rows)."""
    if len(rows) < 3 or rows[-1]["ts"] - rows[0]["ts"] < 3600:
        return {}
    out = {}
    # one reading per hour-ish: thin the series to readings at least 50 min apart so a 2-minute cadence does not
    # make "the last hour" and "the best hour" the same sample
    thin, last = [], -1e12
    for r in rows:
        if r["ts"] - last >= 3000:
            thin.append(r)
            last = r["ts"]
    if len(thin) >= 2:
        v = _retention([r["vol_h1"] for r in thin])
        if v is not None:
            out["snaga_volumen"] = round(v, 3)
        t = _retention([(r["buys_h1"] or 0) + (r["sells_h1"] or 0) for r in thin])
        if t is not None:
            out["snaga_txn"] = round(t, 3)
    held = [(r["ts"], r["holders"]) for r in rows if r["holders"]]
    if len(held) >= 2 and held[-1][0] - held[0][0] >= 1800 and held[0][1] > 0:
        hours = (held[-1][0] - held[0][0]) / 3600
        growth = (held[-1][1] / held[0][1] - 1) / hours
        out["rast_holdera"] = round(_clip(growth / 0.10), 3)
        # transactions between the two holder readings, from the hourly buckets scaled to the gap between readings
        # (robust to the cadence: 2-minute readings would count a 5-minute bucket two or three times)
        txns, prev = 0.0, held[0][0]
        for r in rows:
            if held[0][0] < r["ts"] <= held[-1][0]:
                txns += ((r["buys_h1"] or 0) + (r["sells_h1"] or 0)) * min(r["ts"] - prev, 3600) / 3600
                prev = r["ts"]
        if txns > 0:
            out["organski"] = round(_clip((held[-1][1] - held[0][1]) / txns / 0.3), 3)
    return out


def describe(f):
    """One short Croatian line for a card or a table cell; '' when nothing was measured."""
    bits = []
    if "snaga_volumen" in f:
        bits.append(f"volumen drži {f['snaga_volumen']:.0%} vrha")
    if "snaga_txn" in f:
        bits.append(f"transakcije {f['snaga_txn']:.0%}")
    if "rast_holdera" in f:
        bits.append(f"holderi +{f['rast_holdera'] * 10:.1f}%/h")
    if "organski" in f:
        bits.append(f"organski {f['organski']:.0%}")
    return "Snaga: " + " · ".join(bits) if bits else ""


# ---------- the step inside the scan ----------

def apply(con, rows, keep, now=None, cfg=None, log=None):
    """Record a pulse row for the retained tokens and the best `keep_top` rows, fetch holders when due and within
    budget, and set the strength features on each row. Returns how many holder counts were fetched."""
    cfg = cfg or config()
    now = now or time.time()
    log = log or (lambda s: print(s, file=sys.stderr))
    ensure(con)
    keep = set(keep)
    fetched = 0
    spent = credits_today(con, now)
    can_fetch = bool(os.environ.get("HELIUS_API_KEY")) and spent < cfg["holderi_kredita_dan"]
    for r in rows:
        t = r["token"]
        if t not in keep:
            continue
        holders, src = None, None
        pf = (r.get("extra") or {}).get("pumpfun") or {}
        if pf.get("holders"):  # free reading from the pump.fun board record
            holders, src = int(pf["holders"]), "pumpfun"
        if can_fetch and holders_due(con, t, cfg, now):
            try:
                holders, src = holder_count(t, cfg["holderi_stranica_max"]), "helius"
                fetched += 1
                spent += 10 * cfg["holderi_stranica_max"]  # upper bound; the meter has the exact figure tomorrow
                if spent >= cfg["holderi_kredita_dan"]:
                    can_fetch = False
            except Exception as e:
                log(f"  holderi {r.get('symbol')}: {e}")
        hist = series(con, t, cfg["prozor_h"], now)
        record(con, t, r["raw"], now, holders, src)
        feats = strength(hist + [{"ts": int(now), "vol_h1": (r["raw"].get("volume") or {}).get("h1") or 0,
                                  "buys_h1": ((r["raw"].get("txns") or {}).get("h1") or {}).get("buys", 0),
                                  "sells_h1": ((r["raw"].get("txns") or {}).get("h1") or {}).get("sells", 0),
                                  "buys_m5": ((r["raw"].get("txns") or {}).get("m5") or {}).get("buys", 0),
                                  "sells_m5": ((r["raw"].get("txns") or {}).get("m5") or {}).get("sells", 0),
                                  "holders": holders}], now)
        r["features"].update(feats)
        r.setdefault("extra", {})["puls"] = {"holders": holders, "holders_src": src, "n": len(hist) + 1, **feats}
    return fetched
