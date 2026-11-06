"""5.11. (Nicholas): "BTC/ETH režim mora imati veliku težinu: ako je BTC rastao i konsolidira se, vrijeme je za
altove". Daily closes (DefiLlama, free: market.db btc / eth) plus hourly BTC for sudden drops. One state per asset:
  raste                 7 d up >= +3 % and above the 30 d average
  konsolidacija_rasta   30 d up >= +5 %, last 5 d range <= 6 %, within 8 % of the 30 d high   (alt season window)
  pada                  7 d <= -5 %, or BTC down >= 3 % in the last 4 h
  konsolidacija_pada    30 d down <= -5 % and 5 d range <= 6 %
  neutralno             the rest
Score 0-1 (how friendly to memecoins): konsolidacija_rasta 1.0, raste 0.7, neutralno 0.5, konsolidacija_pada 0.3,
pada 0.0; BTC weighs 0.6, ETH 0.4. Stored hourly in market.db `makro` (as-of: only what was known at ts).
Used as the hype feature `makro` (weight 8, learning may move it but not below 4) and as a demo-bot gate: no new
entries while BTC is in `pada` (paper/config.json gate.makro_pad)."""
import json
import time

from market import store

D = 86400
ETH_PRICES = "https://coins.llama.fi/chart/coingecko:ethereum"
BTC_HOURLY = "https://coins.llama.fi/chart/coingecko:bitcoin"
SCORE = {"konsolidacija_rasta": 1.0, "raste": 0.7, "neutralno": 0.5, "konsolidacija_pada": 0.3, "pada": 0.0}
NAMES = {"konsolidacija_rasta": "konsolidacija nakon rasta (vrijeme za altove)", "raste": "raste", "neutralno": "neutralno",
         "konsolidacija_pada": "konsolidacija nakon pada", "pada": "pada"}
SCHEMA = """CREATE TABLE IF NOT EXISTS eth (day INTEGER PRIMARY KEY, usd REAL);
CREATE TABLE IF NOT EXISTS btc_h (ts INTEGER PRIMARY KEY, usd REAL);
CREATE TABLE IF NOT EXISTS makro (ts INTEGER PRIMARY KEY, score REAL, btc TEXT, eth TEXT, features TEXT);"""
DEFAULT = {"up7": 0.03, "up30": 0.05, "range5": 0.06, "near_high": 0.08, "down7": -0.05, "down30": -0.05, "drop4h": -0.03}


def ensure(con):
    con.executescript(SCHEMA)


def fetch_eth(days=120):
    from event_calendar import http
    data = http.get_json(ETH_PRICES, {"span": days, "period": "1d"}, ttl=1800)
    pts = (data.get("coins") or {}).get("coingecko:ethereum", {}).get("prices") or []
    return [(int(p["timestamp"]), float(p["price"])) for p in pts]


def fetch_btc_hourly(hours=48):
    from event_calendar import http
    data = http.get_json(BTC_HOURLY, {"span": hours, "period": "1h"}, ttl=900)
    pts = (data.get("coins") or {}).get("coingecko:bitcoin", {}).get("prices") or []
    return [(int(p["timestamp"]), float(p["price"])) for p in pts]


def collect(con, now=None, eth=None, btc_h=None):
    """Store ETH daily and BTC hourly prices (fetched unless given), then today's state. Returns the state row."""
    ensure(con)
    now = int(now or time.time())
    try:
        con.executemany("INSERT OR REPLACE INTO eth VALUES (?,?)", [(t // D * D, p) for t, p in (eth if eth is not None else fetch_eth())])
    except Exception as e:  # noqa: BLE001
        print(f"makro eth: {type(e).__name__}: {e}")
    try:
        con.executemany("INSERT OR REPLACE INTO btc_h VALUES (?,?)", [(t // 3600 * 3600, p) for t, p in (btc_h if btc_h is not None else fetch_btc_hourly())])
        con.execute("DELETE FROM btc_h WHERE ts < ?", (now - 14 * D,))
    except Exception as e:  # noqa: BLE001
        print(f"makro btc_h: {type(e).__name__}: {e}")
    r = compute(con, now)
    if r:
        con.execute("INSERT OR REPLACE INTO makro VALUES (?,?,?,?,?)",
                    (now // 3600 * 3600, r["score"], r["btc"]["state"], r["eth"]["state"], json.dumps(r)))
    con.commit()
    return r


def _state(closes, cfg, drop4h=None):
    """closes: [(day, usd)] oldest first, >= 31 days. Returns (state, features)."""
    if len(closes) < 31:
        return None, {}
    px = [p for _, p in closes]
    last, d7, d30 = px[-1], px[-8], px[-31]
    f = {"chg7": last / d7 - 1, "chg30": last / d30 - 1, "avg30": sum(px[-30:]) / 30,
         "high30": max(px[-30:]), "range5": (max(px[-5:]) - min(px[-5:])) / max(px[-5:])}
    f["from_high30"] = last / f["high30"] - 1
    f["drop4h"] = drop4h
    if (drop4h is not None and drop4h <= cfg["drop4h"]) or f["chg7"] <= cfg["down7"]:
        s = "pada"
    elif (f["chg30"] >= cfg["up30"] and f["range5"] <= cfg["range5"] and f["from_high30"] >= -cfg["near_high"]
          and f["chg7"] < cfg["up7"]):   # went up, now flat near the high: not still running
        s = "konsolidacija_rasta"
    elif f["chg7"] >= cfg["up7"] and last >= f["avg30"]:
        s = "raste"
    elif f["chg30"] <= cfg["down30"] and f["range5"] <= cfg["range5"]:
        s = "konsolidacija_pada"
    else:
        s = "neutralno"
    return s, {k: (round(v, 4) if isinstance(v, float) else v) for k, v in f.items()}


def compute(con, now=None, cfg=None):
    """{score, btc: {state, ...}, eth: {state, ...}} from what is stored up to `now`, or None without history."""
    ensure(con)
    cfg = {**DEFAULT, **(cfg or {})}
    now = int(now or time.time())
    day = now // D * D
    btc = con.execute("SELECT day, usd FROM btc WHERE day <= ? ORDER BY day", (day,)).fetchall()
    eth = con.execute("SELECT day, usd FROM eth WHERE day <= ? ORDER BY day", (day,)).fetchall()
    hourly = con.execute("SELECT ts, usd FROM btc_h WHERE ts <= ? AND ts >= ? ORDER BY ts", (now, now - 5 * 3600)).fetchall()
    drop4h = (hourly[-1][1] / hourly[0][1] - 1) if len(hourly) >= 4 else None
    bs, bf = _state(btc, cfg, drop4h)
    if bs is None:
        return None
    es, ef = _state(eth, cfg)
    score = 0.6 * SCORE[bs] + 0.4 * SCORE[es] if es else SCORE[bs]
    return {"score": round(score, 2), "btc": {"state": bs, **bf}, "eth": {"state": es, **ef} if es else {"state": None},
            "ts": now}


def at(ts, con=None):
    """The makro row that was known at ts (hourly), or None."""
    own = con is None
    con = con or store.ro()
    if con is None:
        return None
    try:
        r = con.execute("SELECT ts, score, btc, eth, features FROM makro WHERE ts <= ? ORDER BY ts DESC LIMIT 1",
                        (int(ts),)).fetchone()
    except Exception:  # noqa: BLE001 - old market.db
        r = None
    finally:
        if own:
            con.close()
    if not r:
        return None
    try:
        d = json.loads(r[4] or "{}")
    except ValueError:
        d = {}
    return {"ts": r[0], "score": r[1], "btc": r[2], "eth": r[3], "detail": d}


def feature(now=None):
    """0-1 for the hype score ('makro'), None without data."""
    r = at(now or time.time())
    return r["score"] if r else None


def falling(now=None):
    """True while BTC is in 'pada': the demo bot opens nothing new (paper gate)."""
    r = at(now or time.time())
    return bool(r and r.get("btc") == "pada" and (now or time.time()) - r["ts"] < 3 * 3600)


def line(now=None):
    """One sentence for pages and the report."""
    r = at(now or time.time())
    if not r:
        return "Makro (BTC/ETH): još nema podataka."
    b, e = r.get("btc"), r.get("eth")
    return (f"Makro: BTC {NAMES.get(b, b)}, ETH {NAMES.get(e, e) if e else '–'}; sklonost altovima {r['score']:.0%}"
            + (", novi demo ulazi zaustavljeni dok BTC pada" if b == "pada" else "") + ".")
