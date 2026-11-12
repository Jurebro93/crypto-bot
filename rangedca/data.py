"""range.db and the minute series of a token (flag range_dca). Writer: run_range.py only (one short process a minute);
league/auto (run_ui.py) and the MCP API read it read-only.

Tables
  snaps       our own DexScreener snapshot of a candidate the hype scan does not snapshot itself, once a minute
  gt_candles  GeckoTerminal 1-minute OHLCV that seeded a candidate with < 6 h of history (zlib JSON, one row a token)
  ranges      the newest computed range of every candidate (detect.analyze) + its exclusion state, JSON in `data`
  events      breakdowns, exclusions, give-ups, holder checks (for the owner and the backtest's comparison)
  kv          day counters (GeckoTerminal requests, Helius credits), the last detection, tokens put aside
  range_flip  11.11. (flag range_flip G26): the flip / pause state of every candidate (detect.flip_step), one row a
              token: v (the state's format version, detect.FLIP["v"]; another version is read as none), ver (+1 on every
              change of state), state, since, ts, alt_active (the range after a break is active: the trader reads
              those tokens too), data (the state, JSON). Written only while the flag is not off.

The minute series (candles) of a token is merged from, best first: GeckoTerminal candles we hold (range.db gt_candles,
minute.db call_candles: real OHLCV), then DexScreener snapshots (range.db snaps, hype.db token_pulse: one price per
minute; the minute's volume and transactions estimated from the 5-minute numbers, vol_m5 / 5 for every minute the
snapshot stands for, at most 5).
11.11. (market watchlist, rangedca/market.py): a token of the market list has a snapshot every 5 or 15 minutes, not
every minute. Such a series is one candle per snapshot (detect.py reads timestamps, never candle counts), and a
candle standing for more than 5 minutes gets the volume / transactions of the minutes its 5-minute numbers do not
cover from the rest of the hour's rate ((vol_h1 - vol_m5) / 55 per minute, at most the hour), so the 15-minute and
1-hour volumes of a 15-minute series are not a third of the truth. ranges.src: signal | market | event (the watchlist
that brought the token; JSON data also lists every source).
"""
import json
import os
import sqlite3
import time
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEEP_DAYS = 7          # snaps (the backtest reads them; ~3 MB a day for 20 tokens)
GT_KEEP_DAYS = 15
MAX_TOKENS = int(os.environ.get("RANGE_MAX_TOKENS", "40"))
GT_DAY = int(os.environ.get("RANGE_GT_DAY", "60"))          # GeckoTerminal requests a day (seed + backtest top-up)
GT_PER_PASS = 3
GT_RESEED_S = 86400
COLD_S = 6 * 3600      # a token under 30k or still on the curve is not polled again for this long
PULSE_FRESH_S = 150    # a token_pulse row this fresh: the hype scan already snapshots it, we do not poll it
MIN_MCAP = 30_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS snaps (token TEXT, ts INTEGER, price REAL, mcap REAL, liq REAL, vol_m5 REAL, vol_h1 REAL,
    vol_h6 REAL, buys_m5 INTEGER, sells_m5 INTEGER, buys_h1 INTEGER, sells_h1 INTEGER, ch_m5 REAL, PRIMARY KEY (token, ts));
CREATE TABLE IF NOT EXISTS pools (token TEXT PRIMARY KEY, pool TEXT, dex TEXT, symbol TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS gt_candles (token TEXT PRIMARY KEY, pool TEXT, first_ts INTEGER, last_ts INTEGER, n INTEGER,
    data BLOB, fetched INTEGER);
CREATE TABLE IF NOT EXISTS ranges (token TEXT PRIMARY KEY, ts INTEGER, symbol TEXT, status TEXT, active INTEGER,
    score REAL, price REAL, mcap REAL, pos_pct REAL, data TEXT, state TEXT);
CREATE TABLE IF NOT EXISTS events (token TEXT, ts INTEGER, kind TEXT, note TEXT);
CREATE INDEX IF NOT EXISTS events_ts ON events (ts);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS range_flip (token TEXT PRIMARY KEY, v INTEGER, ver INTEGER, state TEXT, since INTEGER,
    ts INTEGER, alt_active INTEGER, data TEXT);
"""


def db_path():
    """range.db on the persistent disk (DATA_DIR, Render /var/data), like minute.db: no symlink needed in start.sh."""
    if os.environ.get("RANGE_DB"):
        return os.environ["RANGE_DB"]
    data = os.environ.get("DATA_DIR")
    if data and os.path.isdir(data):
        return os.path.join(data, "range.db")
    return os.path.join(ROOT, "range.db")


def connect(path=None):
    p = path or db_path()
    new = not os.path.exists(p) or not os.path.getsize(p)
    con = sqlite3.connect(p, timeout=30)
    if new:
        con.execute("PRAGMA auto_vacuum=INCREMENTAL")
    con.executescript(SCHEMA)
    if "src" not in {r[1] for r in con.execute("PRAGMA table_info(ranges)")}:   # 11.11.: the watchlist source
        con.execute("ALTER TABLE ranges ADD COLUMN src TEXT")
        con.commit()
    return con


def has_src(con):
    """True when ranges has the src column (a range.db written before 11.11. and not opened by the job since)."""
    try:
        return "src" in {r[1] for r in con.execute("PRAGMA table_info(ranges)")}
    except sqlite3.Error:
        return False


def ro(path=None):
    """Read-only connection, None when range.db does not exist yet (flag never on)."""
    p = path or db_path()
    if not os.path.exists(p) or not os.path.getsize(p):
        return None
    try:
        return sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return None


def kv_get(con, k, default=None):
    r = con.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    if not r:
        return default
    try:
        return json.loads(r[0])
    except ValueError:
        return default


def kv_put(con, k, v):
    con.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (k, json.dumps(v)))


def event(con, token, kind, note, now=None):
    con.execute("INSERT INTO events VALUES (?,?,?,?)", (token, int(now or time.time()), kind, note))


def _day(now):
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def day_used(con, key, now):
    d = kv_get(con, key) or {}
    return int(d.get(_day(now), 0))


def day_add(con, key, n, now):
    d = kv_get(con, key) or {}
    day = _day(now)
    d = {day: int(d.get(day, 0)) + int(n)}
    kv_put(con, key, d)
    return d[day]


# ---------- packing (same format as kol/minute call_candles) ------------------------------------------------------
def pack(rows):
    txt = json.dumps([[int(r[0])] + [float(f"{x:.6g}") for x in r[1:6]] for r in rows], separators=(",", ":"))
    return zlib.compress(txt.encode(), 6)


def unpack(blob):
    if not blob:
        return []
    return [tuple(r) for r in json.loads(zlib.decompress(blob).decode())]


# ---------- DexScreener ---------------------------------------------------------------------------------------------
def best_pairs(pairs):
    """{token: pair} the deepest pair per base token."""
    best = {}
    for p in pairs or []:
        try:
            t = p["baseToken"]["address"]
        except (KeyError, TypeError):
            continue
        liq = (p.get("liquidity") or {}).get("usd") or 0
        if t not in best or liq > ((best[t].get("liquidity") or {}).get("usd") or 0):
            best[t] = p
    return best


def snap_of(p, now):
    """A DexScreener pair -> snapshot dict (the columns of snaps + pool, dex, symbol, bonded)."""
    vol, tx, ch = p.get("volume") or {}, p.get("txns") or {}, p.get("priceChange") or {}
    m5, h1 = tx.get("m5") or {}, tx.get("h1") or {}
    liq = (p.get("liquidity") or {}).get("usd") or 0
    dex = p.get("dexId") or ""
    return {"ts": int(now), "price": float(p.get("priceUsd") or 0), "mcap": p.get("marketCap") or p.get("fdv") or 0,
            "liq": liq, "vol_m5": vol.get("m5") or 0, "vol_h1": vol.get("h1") or 0, "vol_h6": vol.get("h6"),
            "buys_m5": m5.get("buys", 0), "sells_m5": m5.get("sells", 0), "buys_h1": h1.get("buys", 0),
            "sells_h1": h1.get("sells", 0), "ch_m5": ch.get("m5"), "pool": p.get("pairAddress"), "dex": dex,
            "symbol": (p.get("baseToken") or {}).get("symbol"),
            # CLAUDE.md "novi pump.fun tokeni se ne uzimaju; uzimaju se bondani": a curve pair has no pool liquidity
            "bonded": bool(liq > 0 and dex != "pumpfun")}


def fetch_pairs(tokens):
    """DexScreener /tokens for up to 30 tokens a request (free); [] on any error."""
    if not tokens:
        return []
    try:
        from dexscreener import client
        return client.tokens("solana", list(tokens), ttl=20) or []
    except Exception as e:  # noqa: BLE001 - no snapshot this minute
        print(f"range: DexScreener nije odgovorio ({type(e).__name__})", flush=True)
        return []


def fetch_pairs_fast(tokens, deadline=None):
    """11.11. (stale 5-minute data): the market watchlist's DexScreener batches on the short leash of tokens_live (a
    few seconds, no retry), one batch of 30 at a time, and no new batch after `deadline` (monotonic). The scanners'
    path (fetch_pairs) waits up to 30 s a try and retries with back-off up to a minute: 30 batches of the market pass
    held a run_range pass for minutes, so the active ranges' 5-minute numbers went older than METRICS_FRESH_S."""
    import time as _t
    out = []
    try:
        from dexscreener import client
    except Exception:  # noqa: BLE001
        return out
    for i in range(0, len(tokens or []), 30):
        if deadline is not None and _t.monotonic() >= deadline:
            break
        try:
            out += client.tokens_live("solana", list(tokens[i:i + 30]), ttl=20) or []
        except Exception:  # noqa: BLE001 - this batch has no snapshot this pass
            continue
    return out


def save_snap(con, token, s):
    con.execute("INSERT OR REPLACE INTO snaps VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (token, s["ts"], s["price"], s["mcap"], s["liq"], s["vol_m5"], s["vol_h1"], s["vol_h6"], s["buys_m5"],
                 s["sells_m5"], s["buys_h1"], s["sells_h1"], s["ch_m5"]))
    if s.get("pool"):
        con.execute("INSERT OR REPLACE INTO pools VALUES (?,?,?,?,?)", (token, s["pool"], s["dex"], s["symbol"], s["ts"]))


def poll(con, tokens, now, fetch=None, pulse_fresh=None):
    """One DexScreener snapshot of every token in `tokens` the hype scan has not snapshotted in the last
    PULSE_FRESH_S. Tokens under 30k or on the bonding curve are put aside for COLD_S (not stored: CLAUDE.md, under
    30k is not analysed). Returns {token: snapshot} of what was stored."""
    fresh = pulse_fresh if pulse_fresh is not None else pulse_recent(now)
    cold = {t: u for t, u in (kv_get(con, "cold") or {}).items() if u > now}
    ask = [t for t in tokens if t not in fresh and t not in cold][:MAX_TOKENS]
    got = {}
    if ask:
        day_add(con, "sig_dex_day", -(-len(ask) // 30), now)   # 11.11.: counted for the daily cost line
        pairs = (fetch or fetch_pairs)(ask)
        for t, p in best_pairs(pairs).items():
            if t not in ask:
                continue
            s = snap_of(p, now)
            if not s["price"] or not s["bonded"] or (s["mcap"] or 0) < MIN_MCAP:
                cold[t] = int(now + COLD_S)
                continue
            save_snap(con, t, s)
            got[t] = s
    kv_put(con, "cold", cold)
    con.commit()
    return got


# ---------- what the bot already has --------------------------------------------------------------------------------
def _ro_file(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return None


def hype_path():
    return os.environ.get("RANGE_HYPE_DB") or os.path.join(ROOT, "hype.db")


def minute_path():
    try:
        from kol import minute
        return minute.db_path()
    except Exception:  # noqa: BLE001
        return None


def pulse_recent(now, path=None):
    """Tokens with a token_pulse row in the last PULSE_FRESH_S (the hype scan snapshots them)."""
    con = _ro_file(path or hype_path())
    if con is None:
        return set()
    try:
        return {r[0] for r in con.execute("SELECT DISTINCT token FROM token_pulse WHERE ts >= ?", (int(now - PULSE_FRESH_S),))}
    except sqlite3.Error:
        return set()
    finally:
        con.close()


def pulse_rows(token, t0, path=None):
    con = _ro_file(path or hype_path())
    if con is None:
        return []
    try:
        return [{"ts": r[0], "price": r[1], "mcap": r[2], "liq": r[3], "vol_m5": r[4], "vol_h1": r[5], "buys_m5": r[6],
                 "sells_m5": r[7], "buys_h1": r[8], "sells_h1": r[9], "vol_h6": None, "ch_m5": None}
                for r in con.execute("SELECT ts, price, mcap, liquidity, vol_m5, vol_h1, buys_m5, sells_m5, buys_h1, sells_h1 "
                                     "FROM token_pulse WHERE token=? AND ts>=? ORDER BY ts", (token, int(t0)))]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def own_rows(con, token, t0):
    return [{"ts": r[0], "price": r[1], "mcap": r[2], "liq": r[3], "vol_m5": r[4], "vol_h1": r[5], "vol_h6": r[6],
             "buys_m5": r[7], "sells_m5": r[8], "ch_m5": r[9], "buys_h1": r[10], "sells_h1": r[11]}
            for r in con.execute("SELECT ts, price, mcap, liq, vol_m5, vol_h1, vol_h6, buys_m5, sells_m5, ch_m5, buys_h1, "
                                 "sells_h1 FROM snaps WHERE token=? AND ts>=? ORDER BY ts", (token, int(t0)))]


def call_candles(token, t0, t1, path=None):
    """minute.db call_candles of the token (GeckoTerminal OHLCV stored around calls)."""
    con = _ro_file(path or minute_path())
    if con is None:
        return []
    try:
        r = con.execute("SELECT data FROM call_candles WHERE token=?", (token,)).fetchone()
        return [c for c in unpack(r[0]) if t0 <= c[0] <= t1] if r else []
    except sqlite3.Error:
        return []
    finally:
        con.close()


def gt_rows(con, token, t0, t1):
    r = con.execute("SELECT data FROM gt_candles WHERE token=?", (token,)).fetchone()
    return [c for c in unpack(r[0]) if t0 <= c[0] <= t1] if r else []


def _spread(s, k5, kh, gap, extra):
    """What a snapshot's 5-minute number k5 stands for over `gap` minutes (<= 5) plus `extra` minutes beyond the 5
    its numbers cover, those at the rest of the hour's rate ((kh - k5) / 55 a minute). None when k5 is unknown."""
    v5 = s.get(k5)
    if v5 is None:
        return None
    out = v5 / 5 * gap
    vh = s.get(kh)
    if extra and vh is not None and vh > v5:
        out += (vh - v5) / 55 * extra
    return out


def merge(true_candles, snaps):
    """[(ts, o, h, l, c, v, buys, sells)] by minute, oldest first: real OHLCV where we have it (buys / sells from the
    snapshot of that minute when one exists), else the snapshot's price with the volume and transactions it stands
    for (vol_m5 / 5 for each minute since the previous data minute, at most 5; 11.11.: the minutes beyond 5 of a
    sparser series at the rest of the hour's rate, _spread)."""
    real = {}
    for c in true_candles:
        m = int(c[0]) - int(c[0]) % 60
        real[m] = (m, float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5] or 0))
    snap_min = {}
    for s in sorted(snaps, key=lambda s: s["ts"]):
        if not s.get("price"):
            continue
        m = int(s["ts"]) - int(s["ts"]) % 60
        snap_min.setdefault(m, []).append(s)
    minutes = sorted(set(real) | set(snap_min))
    out, prev = [], None
    for m in minutes:
        ss = snap_min.get(m)
        last = ss[-1] if ss else None
        raw_gap = 1 if prev is None else max(1, (m - prev) // 60)
        gap, extra = min(5, raw_gap), max(0, min(55, raw_gap - 5))
        b = s_ = None
        if last is not None and last.get("buys_m5") is not None and last.get("sells_m5") is not None:
            b, s_ = _spread(last, "buys_m5", "buys_h1", gap, extra), _spread(last, "sells_m5", "sells_h1", gap, extra)
        if m in real:
            out.append((*real[m], b, s_))
        else:
            px = [x["price"] for x in ss]
            out.append((m, px[0], max(px), min(px), px[-1], _spread(last, "vol_m5", "vol_h1", gap, extra) or 0.0, b, s_))
        prev = m
    return out


def series(con, token, now, hours=24, pulse_path=None, minute_db=None):
    """(candles, latest snapshot with supply / vol_h1_avg6 / symbol / pool / bonded, or None) of one token."""
    t0 = int(now - hours * 3600) - 120
    snaps = own_rows(con, token, t0) + pulse_rows(token, t0, pulse_path)
    true = gt_rows(con, token, t0, now) + call_candles(token, t0, now, minute_db)
    candles = merge(true, snaps)
    snap = None
    if snaps:
        last = max(snaps, key=lambda s: s["ts"])
        snap = dict(last)
        if last.get("price") and last.get("mcap"):
            snap["supply"] = last["mcap"] / last["price"]
        h6 = [s["vol_h1"] for s in snaps if s["ts"] >= now - 6 * 3600 and s.get("vol_h1") is not None]
        if len(h6) >= 12:
            snap["vol_h1_avg6"] = sum(h6) / len(h6)
        elif last.get("vol_h6"):
            snap["vol_h1_avg6"] = last["vol_h6"] / 6
        v15 = [s for s in snaps if s["ts"] >= now - 15 * 60]
        if v15:   # three 5-minute windows of the last 15 minutes, from the snapshots nearest to t, t-5, t-10 min
            pick = []
            for back in (0, 300, 600):
                near = min(snaps, key=lambda s, b=back: abs(s["ts"] - (now - b)))
                if abs(near["ts"] - (now - back)) <= 150:
                    pick.append(near.get("vol_m5") or 0)
            if len(pick) == 3:
                snap["vol_15m"] = sum(pick)
            elif now - last["ts"] <= 300 and last.get("vol_m5") is not None:
                # 11.11.: a 15-minute series (market watchlist) has no snapshot at t-5 / t-10: the last 5 minutes
                # plus 10 minutes at the rest of the hour's rate
                snap["vol_15m"] = _spread(last, "vol_m5", "vol_h1", 5, 10)
        p = con.execute("SELECT pool, dex, symbol FROM pools WHERE token=?", (token,)).fetchone()
        if p:
            snap.update(pool=p[0], dex=p[1], symbol=p[2])
    return candles, snap


# ---------- candidates ----------------------------------------------------------------------------------------------
def _league_ro():
    try:
        from league import store as lstore
        return _ro_file(lstore.DB)
    except Exception:  # noqa: BLE001
        return None


def open_round_tokens():
    con = _league_ro()
    if con is None:
        return []
    try:
        return [r[0] for r in con.execute("SELECT DISTINCT token FROM range_rounds WHERE status='open'")]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def autopilot_tokens():
    """The open tokens of the Autopilot accounts, newest first, at most 15. 11.11.: the real account's (LEAGUE_USER)
    first, so its positions (the owner's manual HOPE one, whose zones zonewatch alarms) are never pushed out of the
    signal pass by the demo account's newer ones."""
    con = _league_ro()
    if con is None:
        return []
    try:
        from trade import settings as ts
        return [r[0] for r in con.execute("SELECT token, MAX(user = ?) AS real_acc, MAX(opened_ts) AS last FROM trades "
                                          "WHERE status='open' AND user IN (?,?) GROUP BY token "
                                          "ORDER BY real_acc DESC, last DESC LIMIT 15",
                                          (ts.LEAGUE_USER, ts.LEAGUE_USER, ts.PAPER_USER))]
    except (sqlite3.Error, ImportError):
        return []
    finally:
        con.close()


def pulse_candidates(now, path=None, limit=40):
    """token_pulse tokens of the last 30 min whose latest row meets the range minimums."""
    con = _ro_file(path or hype_path())
    if con is None:
        return []
    try:
        rows = con.execute("SELECT token, MAX(ts), mcap, liquidity, vol_h1 FROM token_pulse WHERE ts >= ? GROUP BY token",
                           (int(now - 1800),)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    ok = [r for r in rows if (r[2] or 0) >= MIN_MCAP and (r[3] or 0) >= 20_000 and (r[4] or 0) >= 10_000]
    return [r[0] for r in sorted(ok, key=lambda r: -(r[4] or 0))[:limit]]


def call_candidates(now, limit=30):
    """Tokens called in the last 24 h at a known MC >= 30k, the most called first (kol.db, read only)."""
    try:
        from kol import store as kstore
        con = _ro_file(kstore.DB)
    except Exception:  # noqa: BLE001
        con = None
    if con is None:
        return []
    try:
        return [r[0] for r in con.execute(
            "SELECT token, COUNT(*) n, MAX(ts) FROM calls WHERE ts >= ? AND COALESCE(mcap0, 0) >= ? GROUP BY token "
            "ORDER BY n DESC, MAX(ts) DESC LIMIT ?", (int(now - 86400), MIN_MCAP, limit))]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def candidates(con, now, extra=()):
    """The tokens watched this pass, most important first, at most MAX_TOKENS: open range positions, the Autopilot
    accounts' open tokens, tokens with a range seen in the last 2 h, the hype scan's tokens that meet the minimums,
    tokens called in the last 24 h at MC >= 30k."""
    recent = [r[0] for r in con.execute("SELECT token FROM ranges WHERE ts >= ? AND status NOT IN "
                                        "('ispod 30k', 'premalo podataka') ORDER BY active DESC, score DESC",
                                        (int(now - 7200),))]
    out = []
    for group in (list(extra), open_round_tokens(), autopilot_tokens(), recent, pulse_candidates(now), call_candidates(now)):
        for t in group:
            if t and t not in out:
                out.append(t)
    return out[:MAX_TOKENS]


# ---------- GeckoTerminal seed (capped) -----------------------------------------------------------------------------
def gt_fetch(pool, start, end):
    """[(ts, o, h, l, c, v)] from GeckoTerminal (kol/minute.minutes: its pacing, the shared 429 pause and, with the
    CoinGecko key, the shared day budget), None when another job holds GeckoTerminal right now."""
    from kol import minute
    return minute.minutes(pool, start, end)


def store_gt(con, token, pool, candles, now):
    have = {c[0]: c for c in gt_rows(con, token, 0, 10 ** 11)}
    for c in candles:
        have[int(c[0])] = tuple(c[:6])
    rows = [have[k] for k in sorted(have)]
    if not rows:
        return 0
    con.execute("INSERT OR REPLACE INTO gt_candles VALUES (?,?,?,?,?,?,?)",
                (token, pool, rows[0][0], rows[-1][0], len(rows), pack(rows), int(now)))
    return len(rows)


def gt_left(con, now):
    return max(0, GT_DAY - day_used(con, "gt_day", now))


def seed(con, token, pool, now, fetch=None, span_s=998 * 60):
    """One GeckoTerminal request for the last ~16.6 h of minute candles, within the day cap. Returns the number of
    candles stored, None when the cap or GeckoTerminal said no."""
    if not pool or gt_left(con, now) <= 0:
        return None
    r = con.execute("SELECT fetched FROM gt_candles WHERE token=?", (token,)).fetchone()
    if r and now - (r[0] or 0) < GT_RESEED_S:
        return None
    day_add(con, "gt_day", 1, now)
    con.commit()
    try:
        candles = (fetch or gt_fetch)(pool, int(now - span_s), int(now))
    except Exception as e:  # noqa: BLE001
        print(f"range: GeckoTerminal za {token[:6]}: {type(e).__name__}", flush=True)
        candles = None
    if candles is None:
        return None
    n = store_gt(con, token, pool, candles, now)
    event(con, token, "gt", f"{n} minutnih svijeća (GeckoTerminal)", now)
    con.commit()
    return n


# ---------- the computed ranges -------------------------------------------------------------------------------------
def save_range(con, token, res, state, symbol=None):
    con.execute("INSERT OR REPLACE INTO ranges (token, ts, symbol, status, active, score, price, mcap, pos_pct, data, "
                "state, src) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (token, res["ts"], symbol, res["status"], int(bool(res["active"])), res.get("score"),
                 (res.get("metrics") or {}).get("price"), (res.get("metrics") or {}).get("mcap"), res.get("pos_pct"),
                 json.dumps(res, separators=(",", ":")), json.dumps(state or {}, separators=(",", ":")),
                 res.get("source") or "signal"))


def load_range(con, token):
    r = con.execute("SELECT data, state, symbol FROM ranges WHERE token=?", (token,)).fetchone()
    if not r:
        return None, {}
    try:
        d = json.loads(r[0])
        d["symbol"] = r[2]
        return d, json.loads(r[1] or "{}")
    except ValueError:
        return None, {}


def read_ranges(path=None, since=None, tokens=None, active_only=False):
    """{token: range dict with "state" and "symbol"} read-only (for the trader and the MCP API); {} without range.db.
    active_only: only the active ranges (11.11.: with the market watchlist range.db holds ~400 ranges; the trader's
    loops parse only what they can trade)."""
    con = ro(path)
    if con is None:
        return {}
    try:
        sql, args = "SELECT token, data, state, symbol FROM ranges WHERE 1=1", []
        if since:
            sql += " AND ts >= ?"
            args.append(int(since))
        if active_only:
            sql += " AND active = 1"
        if tokens:
            sql += f" AND token IN ({','.join('?' * len(tokens))})"
            args += list(tokens)
        out = {}
        for tok, d, st, sym in con.execute(sql, args):
            try:
                x = json.loads(d)
                x["state"], x["symbol"] = json.loads(st or "{}"), sym
                out[tok] = x
            except ValueError:
                continue
        return out
    except sqlite3.Error:
        return {}
    finally:
        con.close()


# ---------- range_flip state (11.11., flag range_flip G26) ----------------------------------------------------------
def flip_load(con, token):
    """The token's range_flip state (detect.flip_step), None when there is none or it is of another version."""
    from . import detect
    try:
        r = con.execute("SELECT v, data FROM range_flip WHERE token=?", (token,)).fetchone()
    except sqlite3.Error:
        return None
    if not r or r[0] != detect.FLIP["v"]:
        return None
    try:
        return json.loads(r[1])
    except ValueError:
        return None


def flip_save(con, token, st):
    alt = st.get("alt") or {}
    con.execute("INSERT OR REPLACE INTO range_flip (token, v, ver, state, since, ts, alt_active, data) VALUES "
                "(?,?,?,?,?,?,?,?)", (token, st.get("v"), st.get("ver") or 0, st.get("state"), st.get("since"), st.get("ts"),
                                      int(bool(st.get("state") in ("flipped", "resumed") and alt.get("active"))),
                                      json.dumps(st, separators=(",", ":"))))


def flip_rows(path=None, since=None, states=None, alt_active=False):
    """{token: state} of range_flip read-only (current version only): since (ts >=), states (only these), alt_active
    (only the tokens whose range after a break is active); {} without range.db or the table."""
    from . import detect
    con = ro(path)
    if con is None:
        return {}
    try:
        sql, args = "SELECT token, data FROM range_flip WHERE v = ?", [detect.FLIP["v"]]
        if since:
            sql += " AND ts >= ?"
            args.append(int(since))
        if states:
            sql += f" AND state IN ({','.join('?' * len(states))})"
            args += list(states)
        if alt_active:
            sql += " AND alt_active = 1"
        out = {}
        for tok, d in con.execute(sql, args):
            try:
                out[tok] = json.loads(d)
            except ValueError:
                continue
        return out
    except sqlite3.Error:
        return {}
    finally:
        con.close()


def prune(con, now):
    con.execute("DELETE FROM snaps WHERE ts < ?", (int(now - KEEP_DAYS * 86400),))
    con.execute("DELETE FROM gt_candles WHERE last_ts < ?", (int(now - GT_KEEP_DAYS * 86400),))
    con.execute("DELETE FROM ranges WHERE ts < ?", (int(now - 3 * 86400),))
    con.execute("DELETE FROM range_flip WHERE ts < ?", (int(now - 3 * 86400),))
    con.execute("DELETE FROM events WHERE ts < ?", (int(now - 30 * 86400),))
    con.commit()
    try:
        con.execute("PRAGMA incremental_vacuum")
    except sqlite3.Error:
        pass
