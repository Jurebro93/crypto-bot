"""veliki.db: the list, the candles, BTC, the runs (run_veliki.py writes it; the demo trades, the page, the MCP tool,
the critic and the real-money gate only read it).

    tokens  the current list "veliki" (one row a mint: symbol, pool, dex, MC, liquidity, 24 h volume, age, seed, how
            the mint was chosen, rank) - replaced by every list pass
    c15     GeckoTerminal 15-minute OHLCV of the list's pools (token, ts, o, h, l, c, v), the last KEEP_DAYS
    c1h     GeckoTerminal 1-hour OHLCV, the same
    btc_h   BTC hourly closes (DefiLlama, free; the crash periods), btc_d BTC daily closes (the makro regime labels)
    runs    one row per backtest (JSON), the last RUNS_KEEP; kv: list, proof, rule (the live config), last_ts, last_day

On the persistent disk (VELIKI_DB, else DATA_DIR/veliki.db, else next to the code). ~20 tokens x 45 days x 96 + 24
candles: ~2 MB.

Requests (CLAUDE.md: cost per source): GeckoTerminal through event_calendar/http.get_json (the shared pacing, the 429
pause and, with the CoinGecko key, the shared day budget under job "veliki"): the first fill 3 pages of 15m (~31 d) +
1 page of 1h (~41 d) a token, then ONE 15m request a token a pass (every 3 h: 8 a day) and one 1h a day; capped at
GT_PASS requests a pass. DexScreener (free) and DefiLlama (free) otherwise.
"""
import json
import math
import os
import sqlite3
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEEP_DAYS = 45
RUNS_KEEP = 20
CACHE_S = 60
DAYS_15M = int(os.environ.get("VEL_DAYS_15M", "31"))
DAYS_1H = int(os.environ.get("VEL_DAYS_1H", "41"))
GT_PASS = int(os.environ.get("VEL_GT_PASS", "300"))
GECKO = "https://api.geckoterminal.com/api/v2/networks/solana"
LLAMA = "https://coins.llama.fi/chart/coingecko:bitcoin"
SCHEMA = """
CREATE TABLE IF NOT EXISTS tokens (mint TEXT PRIMARY KEY, symbol TEXT, name TEXT, pool TEXT, dex TEXT, url TEXT,
    mcap REAL, liq REAL, liq_total REAL, vol24 REAL, age_d REAL, created_ts INTEGER, seed INTEGER, how TEXT,
    rank INTEGER, ts INTEGER);
CREATE TABLE IF NOT EXISTS hist (mint TEXT PRIMARY KEY, symbol TEXT, name TEXT, pool TEXT, dex TEXT, url TEXT,
    mcap REAL, liq REAL, liq_total REAL, vol24 REAL, age_d REAL, created_ts INTEGER, seed INTEGER, how TEXT,
    rank INTEGER, ts INTEGER);
CREATE TABLE IF NOT EXISTS c1d (token TEXT, ts INTEGER, o REAL, h REAL, l REAL, c REAL, v REAL, PRIMARY KEY (token, ts));
CREATE TABLE IF NOT EXISTS grok_sig (token TEXT, ts INTEGER, kind TEXT, verdict TEXT, confidence REAL, data TEXT,
    PRIMARY KEY (token, ts, kind));
CREATE TABLE IF NOT EXISTS c15 (token TEXT, ts INTEGER, o REAL, h REAL, l REAL, c REAL, v REAL, PRIMARY KEY (token, ts));
CREATE TABLE IF NOT EXISTS c1h (token TEXT, ts INTEGER, o REAL, h REAL, l REAL, c REAL, v REAL, PRIMARY KEY (token, ts));
CREATE TABLE IF NOT EXISTS btc_h (ts INTEGER PRIMARY KEY, usd REAL);
CREATE TABLE IF NOT EXISTS btc_d (day INTEGER PRIMARY KEY, usd REAL);
CREATE TABLE IF NOT EXISTS runs (ts INTEGER PRIMARY KEY, data TEXT);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""
_CACHE = {}
FETCH = {}   # tests replace "gt" (pool, tf, agg, before, limit) and "llama" (period, span) -> no network


def db_path():
    if os.environ.get("VELIKI_DB"):
        return os.environ["VELIKI_DB"]
    data = os.environ.get("DATA_DIR")
    if data and os.path.isdir(data):
        return os.path.join(data, "veliki.db")
    return os.path.join(ROOT, "veliki.db")


def connect(path=None):
    con = sqlite3.connect(path or db_path(), timeout=30)
    con.executescript(SCHEMA)
    return con


def ro(path=None):
    path = path or db_path()
    if not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        con.execute("SELECT 1 FROM kv LIMIT 1")
        return con
    except sqlite3.Error:
        return None


def kv_get(con, k, default=None):
    r = con.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    if not r:
        return default
    try:
        return json.loads(r[0])
    except (TypeError, ValueError):
        return default


def kv_put(con, k, v):
    con.execute("INSERT OR REPLACE INTO kv (k, v) VALUES (?, ?)", (k, json.dumps(v, ensure_ascii=False)))


# ---------- the list -------------------------------------------------------------------------------------------------

COLS = ("mint", "symbol", "name", "pool", "dex", "url", "mcap", "liq", "liq_total", "vol24", "age_d", "created_ts",
        "seed", "how", "rank")


def save_list(con, rows, now, meta=None):
    con.execute("DELETE FROM tokens")
    for i, r in enumerate(rows):
        con.execute(f"INSERT OR REPLACE INTO tokens ({', '.join(COLS)}, ts) VALUES ({', '.join('?' * (len(COLS) + 1))})",
                    tuple(r.get(k) if k != "rank" else i + 1 for k in COLS) + (int(now),))
    kv_put(con, "list", {"ts": int(now), "tokens": [{k: r.get(k) for k in COLS if k != "name"} for r in rows],
                         **(meta or {})})
    con.commit()
    _CACHE.clear()


def tokens(con):
    cur = con.execute(f"SELECT {', '.join(COLS)}, ts FROM tokens ORDER BY rank")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def save_history(con, rows, now):
    """The tokens that fell out of the list (survivorship): kept, their candles fetched, never traded."""
    for i, r in enumerate(rows):
        con.execute(f"INSERT OR REPLACE INTO hist ({', '.join(COLS)}, ts) VALUES ({', '.join('?' * (len(COLS) + 1))})",
                    tuple(r.get(k) if k != "rank" else i + 1 for k in COLS) + (int(now),))
    con.execute("DELETE FROM hist WHERE mint IN (SELECT mint FROM tokens)")
    con.commit()


def history_rows(con):
    cur = con.execute(f"SELECT {', '.join(COLS)}, ts FROM hist ORDER BY mcap DESC")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r), dead=1) for r in cur.fetchall()]


# ---------- candles --------------------------------------------------------------------------------------------------

# 15.11. navečer (coordinator, production 11:45 UTC: every backtest variant n=0, the 1h candles never arrived - HTTP 429
# and another job's reservation made the pass give up at the first refusal, and the next pass came 3 h later): a refused
# call waits for the shared limiter (event_calendar/http: the cooldown after a 429, another job's reservation) and tries
# again, up to GT_TRIES times, while the pass still has time (DEADLINE: monotonic, set by the caller; 0 = no deadline)
GT_TRIES = int(os.environ.get("VEL_GT_TRIES", "4"))
GT_WAIT_MAX_S = float(os.environ.get("VEL_GT_WAIT_MAX_S", "90"))
DEADLINE = [0.0]
GT_STATS = {"ok": 0, "refused": 0, "waited_s": 0.0}


def _gt_wait(url, attempt):
    """Seconds slept before the next try (the limiter's own cooldown, else a growing pause); 0 = give up."""
    from event_calendar import http
    try:
        wait = float(http.cooling(url) or 0.0)
    except Exception:  # noqa: BLE001
        wait = 0.0
    wait = min(GT_WAIT_MAX_S, max(wait, 5.0 * (2 ** attempt)))
    if DEADLINE[0] and time.monotonic() + wait > DEADLINE[0]:
        return 0.0
    time.sleep(wait)
    GT_STATS["waited_s"] += wait
    return wait


def gt_ohlcv(pool, tf, agg, before, limit):
    """[(ts, o, h, l, c, v)] from GeckoTerminal (oldest first), None when GeckoTerminal stays busy (another job's
    reservation, a 429) after GT_TRIES patient tries."""
    if "gt" in FETCH:
        return FETCH["gt"](pool, tf, agg, before, limit)
    from event_calendar import http
    url = f"{GECKO}/pools/{pool}/ohlcv/{tf}"
    d = None
    for attempt in range(max(1, GT_TRIES)):
        try:
            from kol import measure
            measure._GT.wait()
        except Exception:  # noqa: BLE001 - the pacing helper is an optimisation; http paces the host anyway
            pass
        try:
            d = http.get_json(url, {"aggregate": agg, "before_timestamp": int(before), "limit": int(limit),
                                    "currency": "usd"}, ttl=600, headers={"Accept": "application/json"}, retries=0)
        except Exception as e:  # noqa: BLE001 - a 429 / timeout: wait for the limiter, then once more
            d = None
            if attempt == 0 or attempt == GT_TRIES - 1:
                print(f"veliki: GeckoTerminal {tf} za pool {str(pool)[:6]}: {type(e).__name__} {getattr(e, 'code', '')}"
                      + (", čekam i pokušavam ponovno" if attempt < GT_TRIES - 1 else ", odustajem do sljedećeg prolaza"),
                      flush=True)
        if d is not None:
            GT_STATS["ok"] += 1
            break
        GT_STATS["refused"] += 1
        if attempt == GT_TRIES - 1 or not _gt_wait(url, attempt):
            return None
    if d is None:
        return None
    rows = (d.get("data") or {}).get("attributes", {}).get("ohlcv_list") or []
    return sorted((int(r[0]), *map(float, r[1:6])) for r in rows)


def put_candles(con, table, token, rows):
    con.executemany(f"INSERT OR REPLACE INTO {table} (token, ts, o, h, l, c, v) VALUES (?,?,?,?,?,?,?)",
                    [(token, int(r[0]), *r[1:6]) for r in rows])


def candles(con, table, token, t0=0, t1=10 ** 11):
    return [tuple(r) for r in con.execute(f"SELECT ts, o, h, l, c, v FROM {table} WHERE token=? AND ts>=? AND ts<=? "
                                          "ORDER BY ts", (token, int(t0), int(t1)))]


def span(con, table, token):
    r = con.execute(f"SELECT MIN(ts), MAX(ts), COUNT(*) FROM {table} WHERE token=?", (token,)).fetchone()
    return (r[0], r[1], r[2] or 0) if r else (None, None, 0)


# daily: 180 days (the free GeckoTerminal API answers 401 for older daily history; with the CoinGecko key it is served)
TF = {"c15": ("minute", 15, 900, DAYS_15M), "c1h": ("hour", 1, 3600, DAYS_1H), "c1d": ("day", 1, 86400, 180)}
TOP_1H = int(os.environ.get("VEL_TOP_1H", "40"))      # 1h candles for the top 40 of the list (breadth first: daily for all)
HIST_1H = int(os.environ.get("VEL_HIST_1H", "20"))    # and for the 20 largest that fell out (survivorship)


def fill(con, token, pool, now, budget, tables=("c15", "c1h"), log=None):
    """Top the token's candles up: newest first (one request from the last stored bar to now), then backwards until
    DAYS_* of history. Returns requests used (stops at `budget`; None from GeckoTerminal = busy, stop)."""
    used = 0
    for table in tables:
        tf, agg, step, days = TF[table]
        lo, hi, n = span(con, table, token)
        want0 = now - days * 86400
        # forward: from the newest stored bar to now (or the whole wanted span when empty)
        if hi is None or now - hi > step:
            if used >= budget:
                return used
            limit = min(1000, int(math.ceil((now - (hi or want0)) / step)) + 2)
            rows = gt_ohlcv(pool, tf, agg, now + step, limit)
            used += 1
            if rows is None:
                return used
            put_candles(con, table, token, rows)
            con.commit()
            lo, hi, n = span(con, table, token)
        # backward: page until the wanted span is covered (a token younger than that stops on an empty page)
        while lo is not None and lo > want0 + step and used < budget:
            rows = gt_ohlcv(pool, tf, agg, lo, 1000)
            used += 1
            if rows is None:
                return used
            rows = [r for r in rows if r[0] < lo]
            if not rows:
                break
            put_candles(con, table, token, rows)
            con.commit()
            lo, hi, n = span(con, table, token)
    return used


def merge_own_bars(con, bars_by_token, now):
    """15.11. navečer (coordinator: "a free fallback: 15m / 1h candles from our own DexScreener price polls ... merge
    GT history when it arrives"): veliki/live's own 15m bars (league.db veliki_bars, built from the DexScreener quotes
    it polls every 10 s, 30 tokens a request) into c15 and, rebuilt into hours, c1h - INSERT OR IGNORE, so an hour
    GeckoTerminal already has keeps GeckoTerminal's candle (with its volume) and a GeckoTerminal candle that arrives
    later replaces ours (put_candles is INSERT OR REPLACE). Only completed bars. Returns (n15, n1h) inserted."""
    n15 = n1h = 0
    cut15 = int(now) - int(now) % 900
    cut1h = int(now) - int(now) % 3600
    for tok, bars in (bars_by_token or {}).items():
        done = [b for b in bars if b[0] < cut15 and b[1] and b[4]]
        if not done:
            continue
        n15 += con.executemany("INSERT OR IGNORE INTO c15 (token, ts, o, h, l, c, v) VALUES (?,?,?,?,?,?,0)",
                               [(tok, int(b[0]), b[1], b[2], b[3], b[4]) for b in done]).rowcount
        hours = {}
        for b in done:
            h = int(b[0]) - int(b[0]) % 3600
            x = hours.get(h)
            hours[h] = [h, b[1], b[2], b[3], b[4]] if x is None else [h, x[1], max(x[2], b[2]), min(x[3], b[3]), b[4]]
        rows = [(tok, h, x[1], x[2], x[3], x[4]) for h, x in sorted(hours.items()) if h + 3600 <= cut1h]
        n1h += con.executemany("INSERT OR IGNORE INTO c1h (token, ts, o, h, l, c, v) VALUES (?,?,?,?,?,?,0)",
                               rows).rowcount
    con.commit()
    return n15, n1h


def own_bars(tokens_, since, league_db=None):
    """{token: [(ts, o, h, l, c)]} veliki/live's own 15m bars from league.db (read-only)."""
    p = league_db or os.path.join(ROOT, "league.db")
    if not tokens_ or not os.path.exists(p):
        return {}
    out = {}
    try:
        lc = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
        try:
            q = ",".join("?" * len(tokens_))
            for tok, ts, o, h, l, c in lc.execute(
                    f"SELECT token, ts, o, h, l, c FROM veliki_bars WHERE token IN ({q}) AND ts >= ? ORDER BY ts",
                    (*tokens_, int(since))):
                out.setdefault(tok, []).append((ts, o, h, l, c))
        finally:
            lc.close()
    except sqlite3.Error:
        return {}
    return out


def coverage(con, tokens_):
    """{mint: {"d15": days, "d1h": days, "n15", "n1h"}}."""
    out = {}
    for m in tokens_:
        a = span(con, "c15", m)
        b = span(con, "c1h", m)
        c = span(con, "c1d", m)
        out[m] = {"d15": round(((a[1] or 0) - (a[0] or 0)) / 86400, 1) if a[2] else 0.0, "n15": a[2],
                  "d1h": round(((b[1] or 0) - (b[0] or 0)) / 86400, 1) if b[2] else 0.0, "n1h": b[2],
                  "d1d": round(((c[1] or 0) - (c[0] or 0)) / 86400 + 1, 1) if c[2] else 0.0}
    return out


# ---------- BTC ------------------------------------------------------------------------------------------------------

def llama(period, span_, start=None):
    """[(ts, usd)] BTC from DefiLlama (free; at most 500 points a request, so `start` pages hourly history)."""
    if "llama" in FETCH:
        return FETCH["llama"](period, span_, start)
    from event_calendar import http
    q = {"span": min(int(span_), 500), "period": period}
    if start:
        q["start"] = int(start)
    d = http.get_json(LLAMA, q, ttl=900, retries=1)
    pts = ((d or {}).get("coins") or {}).get("coingecko:bitcoin", {}).get("prices") or []
    return [(int(p["timestamp"]), float(p["price"])) for p in pts]


def fill_btc(con, now, hours=1000, days=120):
    """BTC hourly (the crash periods) and daily (the makro labels) closes from DefiLlama (free). (n_hourly, n_daily)."""
    nh = nd = 0
    try:
        h = []
        have = con.execute("SELECT MAX(ts) FROM btc_h").fetchone()[0]
        start = max(int(now) - hours * 3600, (have or 0) - 6 * 3600)
        while start < now - 3600:
            chunk = llama("1h", 500, start)
            if not chunk:
                break
            h += chunk
            start = chunk[-1][0] + 3600
            if len(chunk) < 450:
                break
        con.executemany("INSERT OR REPLACE INTO btc_h VALUES (?,?)", [(t // 3600 * 3600, p) for t, p in h])
        nh = len(h)
    except Exception as e:  # noqa: BLE001
        print(f"veliki: BTC po satu nije stigao ({type(e).__name__})", flush=True)
    try:
        d = llama("1d", days)
        con.executemany("INSERT OR REPLACE INTO btc_d VALUES (?,?)", [(t // 86400 * 86400, p) for t, p in d])
        nd = len(d)
    except Exception as e:  # noqa: BLE001
        print(f"veliki: BTC po danu nije stigao ({type(e).__name__})", flush=True)
    con.execute("DELETE FROM btc_h WHERE ts < ?", (int(now) - 60 * 86400,))
    con.commit()
    return nh, nd


def btc_hourly(con=None):
    """[(ts, usd)] BTC hourly: veliki.db btc_h + market.db btc_h (market/makro collects it every hour), newest wins."""
    out = {}
    own = con is None
    con = con or ro()
    if con is not None:
        try:
            out.update({int(t): p for t, p in con.execute("SELECT ts, usd FROM btc_h")})
        except sqlite3.Error:
            pass
        finally:
            if own:
                con.close()
    try:
        from market import store as mstore
        mc = mstore.ro()
        if mc is not None:
            try:
                out.update({int(t): p for t, p in mc.execute("SELECT ts, usd FROM btc_h")})
            finally:
                mc.close()
    except Exception:  # noqa: BLE001 - market.db unreadable: our own closes
        pass
    return sorted(out.items())


def btc_daily(con):
    return [tuple(r) for r in con.execute("SELECT day, usd FROM btc_d ORDER BY day")]


def archive_grok(con, mints, now, since_s=4 * 3600):
    """The critic (15.11.): Grok's per-token social signals (submit_signal_opinion notes, assistant_notes) copied here
    with their own timestamps, so the strategy can later be compared with and without Grok out of sample. n copied."""
    if not mints:
        return 0
    try:
        from ui import kandidati
        ops = kandidati.Sources().opinions(list(mints), int(now), since_s)
    except Exception:  # noqa: BLE001 - no notes readable: nothing archived this pass
        return 0
    n = 0
    for tok, rows in ops.items():
        for r in rows:
            con.execute("INSERT OR IGNORE INTO grok_sig VALUES (?,?,?,?,?,?)",
                        (tok, int(r.get("ts") or 0), "signal_opinion", r.get("verdict"), r.get("confidence"),
                         json.dumps({"interpretation": r.get("interpretation")}, ensure_ascii=False)))
            n += 1
    con.commit()
    return n


def grok_latest(con, mints):
    """{mint: {"ts", "verdict", "confidence"}} of the newest archived Grok opinion."""
    out = {}
    for tok, ts, v, c in con.execute("SELECT token, ts, verdict, confidence FROM grok_sig ORDER BY ts"):
        if tok in mints:
            out[tok] = {"ts": ts, "verdict": v, "confidence": c}
    return out


def prune(con, now):
    cut = int(now) - KEEP_DAYS * 86400
    con.execute("DELETE FROM c15 WHERE ts < ?", (cut,))
    con.execute("DELETE FROM c1h WHERE ts < ?", (cut - 10 * 86400,))
    con.execute("DELETE FROM c1d WHERE ts < ?", (int(now) - 420 * 86400,))
    con.commit()


# ---------- runs -----------------------------------------------------------------------------------------------------

def save_run(data, now=None, path=None):
    now = int(now or time.time())
    con = connect(path)
    try:
        con.execute("INSERT OR REPLACE INTO runs (ts, data) VALUES (?, ?)", (now, json.dumps(data, ensure_ascii=False)))
        con.execute("DELETE FROM runs WHERE ts NOT IN (SELECT ts FROM runs ORDER BY ts DESC LIMIT ?)", (RUNS_KEEP,))
        kv_put(con, "proof", data.get("proof") or {})
        if data.get("live_rule"):
            kv_put(con, "rule", data["live_rule"])
        kv_put(con, "last_ts", now)
        if data.get("mode") == "night":
            kv_put(con, "last_day", time.strftime("%Y-%m-%d", time.gmtime(now + 3600)))
        con.commit()
    finally:
        con.close()
    _CACHE.clear()


def _cached(k, path=None):
    hit = _CACHE.get((k, path))
    if hit and time.time() - hit[0] < CACHE_S:
        return hit[1]
    con = ro(path)
    v = None
    if con is not None:
        try:
            v = kv_get(con, k)
        except sqlite3.Error:
            v = None
        finally:
            con.close()
    _CACHE[(k, path)] = (time.time(), v)
    return v


def the_list(path=None):
    """{"ts", "tokens": [...]} of the newest list pass, or None."""
    return _cached("list", path)


def proof(path=None):
    return _cached("proof", path)


def live_rule(path=None):
    return _cached("rule", path)


def latest(path=None):
    con = ro(path)
    if con is None:
        return None, None
    try:
        r = con.execute("SELECT ts, data FROM runs ORDER BY ts DESC LIMIT 1").fetchone()
    except sqlite3.Error:
        r = None
    finally:
        con.close()
    if not r:
        return None, None
    try:
        return r[0], json.loads(r[1])
    except (TypeError, ValueError):
        return r[0], None


def last(path=None):
    con = ro(path)
    if con is None:
        return None, None
    try:
        return kv_get(con, "last_ts"), kv_get(con, "last_day")
    finally:
        con.close()


def reset_cache():
    _CACHE.clear()
