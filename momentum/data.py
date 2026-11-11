"""momentum.db (DATA_DIR) and the reads of what the bot already has (flag momentum_scalp). Writer: run_momentum.py
(one short process a minute) and, for the Grok EV gate's calibration rows only, the MCP request (momentum/evgate);
league/auto (run_ui.py), the MCP API and the reports read it read-only.

Tables
  snaps     our DexScreener snapshot of every watched token, once a minute (price, MC, liquidity, volume m5/h1,
            buys/sells m5/h1, change m5, dex): the base rate's price path, the volume baseline and the backtest
  signals   every time a token met ALL entry conditions (traded or not): the features at that minute and, once the
            45 minutes are over (or +15 % / -10 % came first), the outcome: the honest base rate of the entry
  facts     top 10 wallets' share per token (Helius, 4 credits, cached FACTS_TTL_S)
  calib     the Grok EV gate's calibration rows (momentum/evgate.py)
  gt_candles  GeckoTerminal minute OHLCV the nightly backtest fetched (capped, momentum/backtest.top_up)
  kv        day counters (GeckoTerminal calls, Helius credits), tokens put aside, the last pass (near misses)

Sources, cheapest first (CLAUDE.md: measure and cap every paid call):
  DexScreener /tokens (free, 30 tokens a request): MOM_MAX_TOKENS (60) tokens a minute = 2 requests
  hype.db live_trades (PumpPortal WebSocket, free): exact unique buyers and the wash score for subscribed tokens
  GeckoTerminal /pools/multi (30 pools a request, through the shared CoinGecko day budget event_calendar/http
  counts): only for tokens that passed every DexScreener condition and that PumpPortal does not cover, at most one
  call a pass, MOM_GT_DAY (100) a day together with the backtest's history top-up (MOM_BT_GT, 60)
  Helius (top 10 only, 4 credits a token): only for tokens that passed everything else, MOM_HELIUS_DAY (2000)
  credits a day; scan.db facts, topcheck and rug.db first (free)
"""
import json
import os
import sqlite3
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEEP_DAYS = 8          # the backtest reads 7 days
MAX_TOKENS = int(os.environ.get("MOM_MAX_TOKENS", "60"))
GT_DAY = int(os.environ.get("MOM_GT_DAY", "100"))
HELIUS_DAY = int(os.environ.get("MOM_HELIUS_DAY", "2000"))
FACTS_TTL_S = 6 * 3600
COLD_S = 3600          # a token under 30k, on the curve or without a pool is not polled again for this long
MIN_MCAP = 30_000
PP_COVER = 0.5         # PumpPortal trades of the last 5 min >= this share of DexScreener's txns m5: it covers the token

SCHEMA = """
CREATE TABLE IF NOT EXISTS snaps (token TEXT, ts INTEGER, price REAL, mcap REAL, liq REAL, vol_m5 REAL, vol_h1 REAL,
    buys_m5 INTEGER, sells_m5 INTEGER, buys_h1 INTEGER, sells_h1 INTEGER, ch_m5 REAL, dex TEXT,
    PRIMARY KEY (token, ts));
CREATE INDEX IF NOT EXISTS snaps_ts ON snaps (ts);
CREATE TABLE IF NOT EXISTS pools (token TEXT PRIMARY KEY, pool TEXT, dex TEXT, symbol TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS signals (id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT, symbol TEXT, ts INTEGER,
    price REAL, mcap REAL, liq REAL, features TEXT, status TEXT, first TEXT, hit INTEGER, resolved_ts INTEGER,
    max_pct REAL, min_pct REAL, sim_ret REAL, cost REAL);
CREATE INDEX IF NOT EXISTS signals_ts ON signals (ts);
CREATE INDEX IF NOT EXISTS signals_open ON signals (status, token);
CREATE TABLE IF NOT EXISTS facts (token TEXT PRIMARY KEY, ts INTEGER, top10_pct REAL, src TEXT);
CREATE TABLE IF NOT EXISTS calib (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, token TEXT, strategy TEXT,
    p_tp REAL, tp_pct REAL, sl_pct REAL, cost_pct REAL, ev_pct REAL, horizon_s INTEGER, levels_from TEXT,
    gate_mode TEXT, decision TEXT, request TEXT, amount_sol REAL, entry_px REAL, entry_mcap REAL, status TEXT,
    first TEXT, hit INTEGER, resolved_ts INTEGER, max_pct REAL, min_pct REAL);
CREATE INDEX IF NOT EXISTS calib_open ON calib (status, token);
CREATE TABLE IF NOT EXISTS gt_candles (token TEXT PRIMARY KEY, pool TEXT, first_ts INTEGER, last_ts INTEGER, n INTEGER,
    data BLOB, fetched INTEGER);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""


def db_path():
    """momentum.db on the persistent disk (DATA_DIR, Render /var/data), like range.db and minute.db."""
    if os.environ.get("MOMENTUM_DB"):
        return os.environ["MOMENTUM_DB"]
    data = os.environ.get("DATA_DIR")
    if data and os.path.isdir(data):
        return os.path.join(data, "momentum.db")
    return os.path.join(ROOT, "momentum.db")


def connect(path=None):
    p = path or db_path()
    new = not os.path.exists(p) or not os.path.getsize(p)
    con = sqlite3.connect(p, timeout=30)
    if new:
        con.execute("PRAGMA auto_vacuum=INCREMENTAL")
    con.executescript(SCHEMA)
    return con


def ro(path=None):
    """Read-only connection, None when momentum.db does not exist yet (flag never on)."""
    p = path or db_path()
    if not os.path.exists(p) or not os.path.getsize(p):
        return None
    try:
        return sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return None


def _ro_file(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return None


def _q(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


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


def _day(now):
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def day_used(con, key, now):
    return int((kv_get(con, key) or {}).get(_day(now), 0))


def day_add(con, key, n, now):
    d = kv_get(con, key) or {}
    day = _day(now)
    d = {day: int(d.get(day, 0)) + int(n)}
    kv_put(con, key, d)
    return d[day]


def meter(service, n):
    """The usage meter (usage/meter: the weekly cost per source, CLAUDE.md)."""
    try:
        from usage import meter as m
        m.record(service, "momentum", float(n) if service == "helius" else 0.0, calls=1 if service == "helius" else n)
    except Exception:  # noqa: BLE001
        pass


# ---------- DexScreener ---------------------------------------------------------------------------------------------
def fetch_pairs(tokens):
    """DexScreener /tokens (free, rangedca/data.fetch_pairs: 30 a request, 20 s cache); [] on any error."""
    from rangedca import data as rdata
    return rdata.fetch_pairs(tokens)


def snap_of(p, now):
    from rangedca import data as rdata
    return rdata.snap_of(p, now)


def best_pairs(pairs):
    from rangedca import data as rdata
    return rdata.best_pairs(pairs)


def save_snap(con, token, s):
    con.execute("INSERT OR REPLACE INTO snaps VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (token, s["ts"], s["price"], s["mcap"], s["liq"], s["vol_m5"], s["vol_h1"], s["buys_m5"], s["sells_m5"],
                 s.get("buys_h1"), s.get("sells_h1"), s.get("ch_m5"), s.get("dex")))
    if s.get("pool"):
        con.execute("INSERT OR REPLACE INTO pools VALUES (?,?,?,?,?)", (token, s["pool"], s.get("dex"), s.get("symbol"),
                                                                       s["ts"]))


def poll(con, tokens, now, fetch=None, keep=()):
    """One DexScreener snapshot of every token (at most MAX_TOKENS; `keep` first and never put aside: open signals,
    open trades, open calibration rows). Tokens under 30k, on the curve or without a price are put aside for COLD_S
    and not stored (CLAUDE.md: under 30k is not analysed). Returns {token: snapshot} of what was stored."""
    keep = list(dict.fromkeys(keep))
    cold = {t: u for t, u in (kv_get(con, "cold") or {}).items() if u > now}
    ask = keep + [t for t in tokens if t not in cold and t not in keep]
    ask = ask[:max(MAX_TOKENS, len(keep))]
    got = {}
    if ask:
        pairs = (fetch or fetch_pairs)(ask)
        for t, p in best_pairs(pairs).items():
            if t not in ask:
                continue
            s = snap_of(p, now)
            if t not in keep and (not s["price"] or not s["bonded"] or (s["mcap"] or 0) < MIN_MCAP):
                cold[t] = int(now + COLD_S)
                continue
            if not s["price"]:
                continue
            save_snap(con, t, s)
            got[t] = s
    kv_put(con, "cold", cold)
    con.commit()
    return got


def snap_rows(con, token, t0, t1=None):
    """[(ts, price)] of a token's snapshots t0..t1, oldest first."""
    return [(r[0], r[1]) for r in con.execute("SELECT ts, price FROM snaps WHERE token=? AND ts>=? AND ts<=? AND price>0 "
                                              "ORDER BY ts", (token, int(t0), int(t1 or 10 ** 11)))]


# ---------- candidates ----------------------------------------------------------------------------------------------
def hype_path():
    return os.environ.get("MOM_HYPE_DB") or os.path.join(ROOT, "hype.db")


def _league_ro():
    try:
        from league import store as lstore
        return _ro_file(lstore.DB)
    except Exception:  # noqa: BLE001
        return None


def open_trade_tokens():
    con = _league_ro()
    rows = _q(con, "SELECT DISTINCT token FROM momentum_trades WHERE status='open'")
    if con is not None:
        con.close()
    return [r[0] for r in rows]


def scan_candidates(now, limit=40):
    """The market scanner's migrated candidates checked in the last 30 min at MC >= 30k (scan.db, read only)."""
    try:
        from scan import store as sstore
        con = sstore.ro()
    except Exception:  # noqa: BLE001
        con = None
    rows = _q(con, "SELECT token FROM cand WHERE checked_ts >= ? AND COALESCE(stage,'') = 'migrated' AND "
                   "COALESCE(mcap, 0) >= ? AND COALESCE(liq, 0) >= 20000 ORDER BY COALESCE(vol_h1, 0) DESC LIMIT ?",
              (int(now - 1800), MIN_MCAP, limit))
    if con is not None:
        con.close()
    return [r[0] for r in rows]


def live_list(now, path=None, limit=40):
    """The live list: hype.db token_pulse tokens of the last 30 min at MC >= 30k and liquidity >= 20k, busiest first,
    and the tokens PumpPortal saw bond (migration) in the last 6 h."""
    con = _ro_file(path or hype_path())
    if con is None:
        return []
    try:
        pulse = [r[0] for r in _q(con, "SELECT token, MAX(ts), mcap, liquidity, vol_h1 FROM token_pulse WHERE ts >= ? "
                                       "GROUP BY token HAVING COALESCE(mcap,0) >= ? AND COALESCE(liquidity,0) >= 20000 "
                                       "ORDER BY COALESCE(vol_h1,0) DESC LIMIT ?", (int(now - 1800), MIN_MCAP, limit))]
        mig = [r[0] for r in _q(con, "SELECT mint FROM live_launches WHERE pool='migration' AND ts >= ? ORDER BY ts DESC "
                                     "LIMIT ?", (int(now - 6 * 3600), limit))]
        return pulse + mig
    finally:
        con.close()


def launches(now):
    """Launches the +10/+30/+90 min checks saw at 10k (kol/precall.reached); the snapshot keeps those at 30k+."""
    try:
        from kol import precall
        return [m for m, _s in precall.reached(now)]
    except Exception:  # noqa: BLE001
        return []


def candidates(con, now, extra=()):
    """The tokens watched this pass, most important first: tokens with a signal in the last 2 h (they may jump again),
    the scanner's migrated candidates, the live list, launches that reached 10k (the snapshot keeps 30k+)."""
    recent = [r[0] for r in con.execute("SELECT DISTINCT token FROM signals WHERE ts >= ? ORDER BY ts DESC",
                                        (int(now - 7200),))]
    out = []
    for group in (list(extra), recent, scan_candidates(now), live_list(now), launches(now)):
        for t in group:
            if t and t not in out:
                out.append(t)
    return out


# ---------- unique buyers and wash: PumpPortal (free), GeckoTerminal (capped) --------------------------------------
def pp_trades(token, now, path=None):
    """The token's PumpPortal trades of the last hour as rugfilter/analysis rows (side, wallet, amount SOL, ts)."""
    con = _ro_file(path or hype_path())
    rows = _q(con, "SELECT side, wallet, sol, ts FROM live_trades WHERE mint=? AND ts>=? LIMIT 5000",
              (token, int(now - 3600)))
    if con is not None:
        con.close()
    return [{"side": s, "wallet": w, "amount": sol or 0, "ts": ts} for s, w, sol, ts in rows if s in ("buy", "sell")]


def pp_features(rows, now, txns_m5, sol_usd):
    """(buyers_in, wash_in) from PumpPortal rows, or (None, None) when PumpPortal does not cover the token (its last
    5 minutes hold fewer than PP_COVER of the transactions DexScreener counted, or fewer than 20 trades in the hour)."""
    r5 = [r for r in rows if r["ts"] > now - 300]
    if len(rows) < 20 or not txns_m5 or len(r5) < PP_COVER * txns_m5:
        return None, None
    b_now = len({r["wallet"] for r in r5 if r["side"] == "buy"})
    b_before = len({r["wallet"] for r in rows if r["side"] == "buy" and now - 600 < r["ts"] <= now - 300})
    from rugfilter import analysis
    vq = analysis.volume_quality(rows)
    wallets = vq.get("wallets") or 0
    vol_usd = sum(r["amount"] or 0 for r in rows) * (sol_usd or 150.0)
    wash = {"how": "pumpportal", "wash": analysis.wash_score(vq), "traders_h1": wallets,
            "tx_per_trader": vq.get("trades_per_wallet"), "usd_per_trader": vol_usd / wallets if wallets else None}
    return {"now": b_now, "before": b_before, "how": "pumpportal"}, wash


GT_MULTI = "/networks/solana/pools/multi/"


def gt_multi(pools, fetch=None):
    """{pool: attributes} of up to 30 pools in ONE GeckoTerminal request; None when GeckoTerminal is held by another
    job or failed (the caller does not retry this pass)."""
    if not pools:
        return {}
    if fetch is None:
        from event_calendar import http
        d = http.get_json(f"{http.GT_BASE}{GT_MULTI}{','.join(pools[:30])}", ttl=45,
                          headers={"Accept": "application/json"}, retries=0)
    else:
        d = fetch(pools[:30])
    if d is None:
        return None
    out = {}
    for p in (d or {}).get("data") or []:
        a = p.get("attributes") or {}
        addr = a.get("address") or (p.get("id") or "").split("_", 1)[-1]
        if addr:
            out[addr] = a
    return out


def gt_features(a, vol_h1=None):
    """(buyers_in, wash_in) from a GeckoTerminal pool's transactions (unique buyers / sellers per window)."""
    tx = (a or {}).get("transactions") or {}
    m5, h1 = tx.get("m5") or {}, tx.get("h1") or {}
    if m5.get("buyers") is None or h1.get("buyers") is None:
        return None, None
    b5, bh = int(m5.get("buyers") or 0), int(h1.get("buyers") or 0)
    traders = bh + int(h1.get("sellers") or 0)
    txns = int(h1.get("buys") or 0) + int(h1.get("sells") or 0)
    vol = vol_h1
    if vol is None:
        try:
            vol = float(((a or {}).get("volume_usd") or {}).get("h1") or 0)
        except (TypeError, ValueError):
            vol = 0.0
    buyers = {"now": b5, "hour_rate": max(0, bh - b5) / 11, "how": "gecko"}
    wash = {"how": "gecko", "wash": None, "traders_h1": bh,
            "tx_per_trader": txns / traders if traders else None, "usd_per_trader": vol / traders if traders else None}
    return buyers, wash


def gt_take(con, now, n=1):
    """One GeckoTerminal call from momentum's own day cap (GT_DAY): True when allowed (and counted)."""
    if day_used(con, "gt_day", now) + n > GT_DAY:
        return False
    day_add(con, "gt_day", n, now)
    con.commit()
    meter("coingecko", n)
    return True


# ---------- top 10 ----------------------------------------------------------------------------------------------------
def free_top10(token, now):
    """(top 10 %, source) from what the bot already has: scan.db facts (fresh 6 h), topcheck / rug.db
    (league/copy._conc_tables); (None, None) when unknown."""
    try:
        from scan import store as sstore
        sc = sstore.ro()
    except Exception:  # noqa: BLE001
        sc = None
    r = _q(sc, "SELECT ts, top10_pct, src FROM facts WHERE token=?", (token,))
    if sc is not None:
        sc.close()
    if r and r[0][1] is not None and now - (r[0][0] or 0) < FACTS_TTL_S:
        return float(r[0][1]), f"scan.db ({r[0][2]})"
    try:
        from league import copy as lcopy
        tc, rug = lcopy._conc_tables()
    except Exception:  # noqa: BLE001
        tc, rug = {}, {}
    t10 = (((tc or {}).get(token) or {}).get("rc") or {}).get("top10")
    if t10 is not None:
        return float(t10), "topcheck"
    t10 = ((rug or {}).get(token) or {}).get("top10_pct")
    if t10 is not None:
        return float(t10), "rug.db"
    return None, None


def top10(con, token, now, helius=None):
    """(top 10 %, source): the momentum cache, the free tables, then Helius (4 credits) within HELIUS_DAY."""
    r = con.execute("SELECT ts, top10_pct, src FROM facts WHERE token=?", (token,)).fetchone()
    if r and now - r[0] < FACTS_TTL_S and r[1] is not None:
        return r[1], r[2]
    t, src = free_top10(token, now)
    if t is None:
        if helius is None:
            if not os.environ.get("HELIUS_API_KEY"):
                return None, "nema HELIUS_API_KEY"
            from rugfilter import helius as rh
            helius = rh.rpc
        from scan import filters
        if day_used(con, "helius_day", now) + filters.HELIUS_COST > HELIUS_DAY:
            return None, "dnevni strop Helius kredita"
        facts, credits = filters.helius_facts(token, helius, pages=0)
        day_add(con, "helius_day", credits, now)
        if facts is None or facts.get("top10_pct") is None:
            con.commit()
            return None, "Helius nije odgovorio"
        t, src = float(facts["top10_pct"]), "helius"
    con.execute("INSERT OR REPLACE INTO facts VALUES (?,?,?,?)", (token, int(now), t, src))
    con.commit()
    return t, src


# ---------- the shill network -----------------------------------------------------------------------------------------
def shill_handles():
    """Lowercased handles of the shill network: paid shillers (kol/shillers) and members of caller crews graded
    exit_liquidity or bad (kol/groupdisc, read-only; empty when its tables do not exist)."""
    out = set()
    try:
        from kol import shillers
        out |= set(shillers.handles())
    except Exception:  # noqa: BLE001
        pass
    try:
        from kol import groupdisc
        con = _ro_file(groupdisc.db_path())
        if con is not None:
            try:
                member_of, grades, _owner = groupdisc.load_groups(con, "caller")
            finally:
                con.close()
            bad = {g for g, gr in grades.items() if gr in ("exit_liquidity", "bad")}
            out |= {str(m).lower() for m, g in member_of.items() if g in bad}
    except Exception:  # noqa: BLE001 - groupdisc changes in parallel: an unreadable table is no shill set
        pass
    return out


def shill_calls(token, now, handles, window_s=3600):
    """Handles of the shill network that called the token in the last hour (kol.db calls, read only)."""
    if not handles:
        return set()
    try:
        from kol import store as kstore
        con = _ro_file(kstore.DB)
    except Exception:  # noqa: BLE001
        con = None
    rows = _q(con, "SELECT DISTINCT handle FROM calls WHERE token=? AND ts>=?", (token, int(now - window_s)))
    if con is not None:
        con.close()
    return {h for (h,) in rows if h and h.lower() in handles}


# ---------- signals ---------------------------------------------------------------------------------------------------
def add_signal(con, token, symbol, now, snap, features, cost):
    cur = con.execute("INSERT INTO signals (token, symbol, ts, price, mcap, liq, features, status, cost) "
                      "VALUES (?,?,?,?,?,?,?,?,?)", (token, symbol, int(now), snap["price"], snap.get("mcap"),
                                                     snap.get("liq"), json.dumps(features, separators=(",", ":")),
                                                     "open", cost))
    return cur.lastrowid


def last_signal_ts(con, token):
    r = con.execute("SELECT MAX(ts) FROM signals WHERE token=?", (token,)).fetchone()
    return r[0] if r and r[0] else 0


def open_signals(con):
    cur = con.execute("SELECT * FROM signals WHERE status='open' ORDER BY ts")
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def read_signals(since, path=None, tokens=None):
    """[signal dict] since `since`, newest first, read-only ([] without momentum.db)."""
    con = ro(path)
    if con is None:
        return []
    try:
        sql, args = "SELECT * FROM signals WHERE ts >= ?", [int(since)]
        if tokens:
            sql += f" AND token IN ({','.join('?' * len(tokens))})"
            args += list(tokens)
        cur = con.execute(sql + " ORDER BY ts DESC LIMIT 500", args)
        cols = [c[0] for c in cur.description]
        out = []
        for r in cur.fetchall():
            d = dict(zip(cols, r))
            try:
                d["features"] = json.loads(d["features"] or "{}")
            except ValueError:
                d["features"] = {}
            out.append(d)
        return out
    except sqlite3.Error:
        return []
    finally:
        con.close()


def prune(con, now):
    con.execute("DELETE FROM snaps WHERE ts < ?", (int(now - KEEP_DAYS * 86400),))
    con.execute("DELETE FROM facts WHERE ts < ?", (int(now - 2 * 86400),))
    con.execute("DELETE FROM signals WHERE ts < ?", (int(now - 60 * 86400),))
    con.execute("DELETE FROM calib WHERE ts < ?", (int(now - 90 * 86400),))
    con.commit()
    try:
        con.execute("PRAGMA incremental_vacuum")
    except sqlite3.Error:
        pass
