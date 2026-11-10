"""Read-only analysis tools of the MemeSonar MCP endpoint (/mcp), 10.11. (Jure: an external AI assistant analyses
the full dataset). Every tool reads the databases read-only (file:...?mode=ro), pages its rows (limit 1..500,
offset >= 0, "next_offset" when more rows exist) and gives times as unix seconds. The one write is
submit_caller_weights: suggestions go to trade.db table assistant_suggestions with status 'pending'; nothing reads
them for live scoring, the owner approves or rejects them on the Autopilot page.

Data (see the map in the 10.11. PR): kol.db (calls, kols, kol_ids, tokens, snaps), minute.db (call_path,
call_candles), tg.db, hype.db (chain_trades, live_trades, hype_snapshots, hype_signals, rug_archive), wallets.db
(wallets, wallet_trades), rug.db (rug_reports), topcheck.db (top_check), corr.db (snapshots), league.db (trades,
follows, copy_log), trade.db (positions, orders, settings), paper.db (trades, candidates: old paper-follow positions).

10.11. (Grok MCP audit): the outside analyst's audit of the production answers found nulls where the data exists in
another table (symbol in kol.db tokens, followers in kols, the first call's market cap in minute.db, the exit rule in
the demo note, the smart stop in the trade's auto_state, a refused real position's reason in positions.reason) and a
leaderboard ranked by the 24 h wick. Each tool now falls back along the sources named in its code and says which
source a value came from (*_source fields) and why a value is still null (*_status fields).
"""
import json
import math
import os
import re
import sqlite3
import statistics
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_LIMIT = 500
DEFAULT_LIMIT = 100
_CACHE = {}          # key -> (ts, value): the leaderboard aggregates, 5 min
_LOCK = threading.Lock()
CACHE_S = 300
CO_CALL_S = 900      # "other callers within 15 min before / after"
X2 = 1.0             # max24 >= +100 % = reached 2x
HIT = 0.5            # the project's hit: max24 >= +50 % (kol/score.py hit_rate)
BRAG_MIN, BRAG_SHARE = 3, 0.3
# 10.11. (Grok MCP audit 5): the leaderboard's tradable measures. hit_rate above is the 24 h wick (the high at any
# moment within a day), which no copy can sell at; the EV fields are what a copy that held one hour got.
MIN_MEASURED = 10    # measured calls (one per token) before a caller is on the default list (kol/tpsl.MIN_N)
WILSON_Z = 1.64      # one-sided 95 %, as ui/autopilot.WILSON_Z
EV_Z = 2.0           # the EV lower bound: mean minus EV_Z standard errors (kol/tpsl.Z)
MIN_MCAP = 30_000    # CLAUDE.md: tokens under $30k are not analysed (no EV from them)
SNAP_GAP = 25 * 60   # a snapshot this far from the moment it stands for still counts (kol/snap.SNAP_GAP)
MINUTE_DAYS = 30     # kol/minute.KEEP_DAYS: minute paths older than this are deleted
MINUTE_MIN_AGE_S = 70 * 60   # kol/minute config min_age_min: a call is minute-measured from 70 min after the post
CHECK_S = 24 * 3600 + 300    # kol/measure: the 24 h checkpoint (+ one candle) after which r24h exists


# ---------- plumbing -------------------------------------------------------------------------------------------------

def _path(name):
    from league import store
    from trade import settings
    env = {"kol": "KOL_DB", "hype": "HYPE_DB", "tg": "TG_DB", "wallets": "WALLET_DB", "rug": "RUG_DB",
           "topcheck": "TOPCHECK_DB", "corr": "CORR_DB", "paper": "PAPER_DB"}.get(name)
    if env and os.environ.get(env):
        return os.environ[env]
    if name == "minute":
        from kol import minute
        return minute.db_path()
    if name == "league":
        return store.DB
    if name == "trade":
        return settings.DB
    if name == "kol":
        from kol import store as kstore
        return kstore.DB
    if name == "wallets":
        from wallets import store as wstore
        return wstore.DB
    if name == "topcheck":
        from topcheck import store as tstore
        return tstore.DB
    if name == "corr":
        from corr import store as cstore
        return cstore.DB
    if name in ("hype", "tg"):
        from league import copy
        return copy._paths()[name]
    return os.path.join(ROOT, f"{name}.db")


def _ro(name):
    p = _path(name)
    if not p or not os.path.exists(p) or not os.path.getsize(p):
        return None
    try:
        return sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return None


def _q(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


def _close(*cons):
    for c in cons:
        if c is not None:
            c.close()


def _page(limit, offset):
    try:
        limit = int(limit if limit is not None else DEFAULT_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    try:
        offset = int(offset or 0)
    except (TypeError, ValueError):
        offset = 0
    return max(1, min(MAX_LIMIT, limit)), max(0, offset)


def _paged(rows, limit, offset, total=None, **extra):
    """rows: the whole list (sliced here) or, with total given, the page the query already cut."""
    page = rows[offset:offset + limit] if total is None else rows
    total = len(rows) if total is None else total
    out = {"ts": int(time.time()), "limit": limit, "offset": offset, "total": total, "rows": page}
    if offset + limit < total:
        out["next_offset"] = offset + limit
    out.update(extra)
    return out


def _f(x, nd=6):
    try:
        return round(float(x), nd) if x is not None else None
    except (TypeError, ValueError):
        return None


def _i(x):
    try:
        return int(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else None


def _med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 4) if xs else None


def _cached(key, build):
    now = time.time()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < CACHE_S:
            return hit[1]
    val = build()
    with _LOCK:
        _CACHE[key] = (now, val)
    return val


def platform_of(handle):
    h = handle or ""
    return "telegram" if h.startswith("tg:") else "wallet" if h.startswith("w:") else "x"


def _handle(handle, platform=None):
    h = (handle or "").strip().lstrip("@")
    if (platform or "").lower() == "telegram" and not h.startswith("tg:"):
        h = "tg:" + h
    return h


def _has(con, table):
    return bool(_q(con, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)))


def _cols(con, table):
    """10.11. (Grok MCP audit 1): the columns a table has, so a column another module adds later (league trades
    runup / call_mcap / exit_rule) is read only once it exists."""
    return {r[1] for r in _q(con, f"PRAGMA table_info({table})")}


def _dicts(con, sql, args=()):
    """Rows as dicts (column name -> value); [] on a missing table or database."""
    if con is None:
        return []
    try:
        cur = con.execute(sql, args)
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]
    except sqlite3.Error:
        return []


def _json(x):
    try:
        v = json.loads(x) if isinstance(x, str) and x else x
    except ValueError:
        return {}
    return v if isinstance(v, dict) else {}


_X_URL = re.compile(r"(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})", re.I)


def _xhandle(x):
    """10.11. (Grok MCP audit 8): kol_ids.twitter holds '@name', 'name' or a profile URL -> 'name' or None."""
    s = (x or "").strip()
    m = _X_URL.search(s)
    if m:
        return m.group(1)
    s = s.lstrip("@")
    return s if re.fullmatch(r"[A-Za-z0-9_]{1,15}", s) else None


def wilson_low(k, n, z=WILSON_Z):
    """Lower end of the Wilson interval of k successes in n (0 when n is 0): 6 of 6 is about 0.69, so a short lucky
    run does not outrank a long good record (the formula of ui/autopilot.wilson_low, on counts)."""
    if not n:
        return 0.0
    p = max(0.0, min(1.0, k / n))
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return max(0.0, (c - r) / d)


def _cost():
    """The round-trip cost as a fraction of the stake (kol/tpsl.COST = 2 %: league/store.FEE 1 % a side)."""
    try:
        from kol import tpsl
        return float(tpsl.COST) / 100
    except Exception:  # noqa: BLE001
        return 0.02


def _near(rows, t, after_only=False):
    """The (ts, ...) row closest to t within SNAP_GAP (rows oldest first), or None."""
    best = None
    for r in rows:
        if after_only and r[0] < t:
            continue
        d = abs(r[0] - t)
        if d <= SNAP_GAP and (best is None or d < abs(best[0] - t)):
            best = r
    return best


def _snapshots(kc, hc, tok, start, end):
    """[(ts, price, mcap)] of one token between start and end, oldest first: kol.db snaps (DexScreener every ~20 min
    while a call is younger than 25 h, kept 3 days) and hype.db hype_snapshots (every 20 min while it is followed)."""
    rows = {}
    for ts, px, mc in _q(kc, "SELECT ts, price, mcap FROM snaps WHERE token=? AND ts BETWEEN ? AND ? AND price>0 "
                             "ORDER BY ts", (tok, int(start), int(end))):
        rows[int(ts)] = (int(ts), px, mc)
    for ts, px, mc in _q(hc, "SELECT ts, price, mcap FROM hype_snapshots WHERE token=? AND ts BETWEEN ? AND ? "
                             "AND price>0 ORDER BY ts", (tok, int(start), int(end))):
        rows.setdefault(int(ts), (int(ts), px, mc))
    return [rows[k] for k in sorted(rows)]


def _kol_index(kc):
    """lower(handle) -> (handle, followers, call_power) of kol.db kols. 10.11. (Grok MCP audit 7): handles are
    matched without case; the collectors wrote 0xMarko77 in one table and 0xmarko77 in another."""
    out = {}
    for h, fol, score in _q(kc, "SELECT handle, followers, score FROM kols"):
        if h:
            k = h.lower()
            if k not in out or (fol or 0) > (out[k][1] or 0):
                out[k] = (h, fol, score)
    return out


def _tg_subs(names):
    """lower(channel name) -> subscribers (tg.db channels.subs)."""
    names = sorted({n for n in names if n})
    if not names:
        return {}
    con = _ro("tg")
    try:
        q = ",".join("?" * len(names))
        return {n.lower(): s for n, s in _q(con, f"SELECT name, subs FROM channels WHERE name COLLATE NOCASE IN ({q})",
                                            names) if s}
    finally:
        _close(con)


def _followers(kc, handles, kidx=None):
    """10.11. (Grok MCP audit 7): handle -> (followers, source). calls.followers is what the collector saw at the
    post and is 0 when it saw nothing (an X webhook without the author's profile, a Telegram post); the leaderboard
    read kols.followers, so the two disagreed (0 vs 2863). Order: kols.followers (any case) -> tg.db channels.subs
    for tg:<channel> -> the largest non-zero followers on any of the handle's calls."""
    kidx = kidx if kidx is not None else _kol_index(kc)
    hs = sorted({h for h in handles if h})
    tg = _tg_subs([h[3:] for h in hs if h.startswith("tg:")])
    out = {}
    for h in hs:
        k = kidx.get(h.lower())
        if k and k[1]:
            out[h] = (int(k[1]), "kols")
        elif h.startswith("tg:") and tg.get(h[3:].lower()):
            out[h] = (int(tg[h[3:].lower()]), "tg_channels")
        else:
            r = _q(kc, "SELECT MAX(followers) FROM calls WHERE handle=? COLLATE NOCASE AND followers>0", (h,))
            out[h] = (int(r[0][0]), "calls_max") if r and r[0][0] else (None, None)
    return out


def _symbols(kc, hc, toks):
    """10.11. (Grok MCP audit 6): token -> symbol. calls.symbol is written by only some collectors (82 of 83 calls of
    one caller had none); kol.db tokens.symbol is filled when the pair is resolved (kol/measure, kol/snap), then
    hype.db hype_signals and rug_archive."""
    toks = sorted({t for t in toks if t})
    out = {}
    for i in range(0, len(toks), 400):
        part = toks[i:i + 400]
        q = ",".join("?" * len(part))
        for con, sql in ((kc, f"SELECT token, symbol FROM tokens WHERE token IN ({q}) AND symbol IS NOT NULL AND symbol!=''"),
                         (hc, f"SELECT token, symbol FROM hype_signals WHERE token IN ({q}) AND symbol IS NOT NULL "
                              f"AND symbol!='' GROUP BY token"),
                         (hc, f"SELECT token, symbol FROM rug_archive WHERE token IN ({q}) AND symbol IS NOT NULL "
                              f"AND symbol!=''")):
            for t, s in _q(con, sql, part):
                out.setdefault(t, s)
    return out


# ---------- 1. caller leaderboard --------------------------------------------------------------------------------

SORTS = ("ev_lower", "score", "hit_rate", "calls", "measured_calls", "ev_n", "median_r1h_after_cost",
         "mean_r1h_after_cost", "hit10_wilson_low", "avg_r24h", "x2_share", "followers", "last_call_ts", "power_rel")


def _bad(mc):
    """The call_path bad flag as an SQL expression (a minute.db from before the flag has none)."""
    return "bad" if "bad" in _cols(mc, "call_path") else "NULL"


def _minute_first(mc):
    """(handle, token) -> (ts, r60, t10, sl_min) of the caller's FIRST minute-measured call of that token (entry known,
    no bad flag: under-30k entries, missing candles and unknown pools are out), as kol/minute.handle_stats counts."""
    out = {}
    for h, tok, ts, r60, t10, sl in _q(mc, "SELECT handle, token, ts, r60, t10, sl_min FROM call_path "
                                          f"WHERE entry IS NOT NULL AND {_bad(mc)} IS NULL"):
        k = (h, tok)
        if k not in out or ts < out[k][0]:
            out[k] = (ts, r60, t10, sl)
    return out


def _ev(xs):
    """(n, mean, median, mean - EV_Z standard errors) of per-call returns after cost."""
    n = len(xs)
    if not n:
        return 0, None, None, None
    mean = sum(xs) / n
    lo = mean - EV_Z * statistics.stdev(xs) / math.sqrt(n) if n >= 2 else None
    return n, round(mean, 4), round(statistics.median(xs), 4), (round(lo, 4) if lo is not None else None)


def _leaderboard_rows():
    """Every caller (X and Telegram) with its aggregates; cached CACHE_S per kol.db / minute.db file."""
    def build():
        kc, mc = _ro("kol"), _ro("minute")
        try:
            kols = {h: (name, fol, score, prel, stats, bot) for h, name, fol, score, prel, stats, bot in _q(
                kc, "SELECT handle, name, followers, score, power_rel, stats, COALESCE(bot, 0) FROM kols")}
            if not kols:   # an older kol.db without the bot column
                kols = {h: (name, fol, score, prel, stats, 0) for h, name, fol, score, prel, stats in _q(
                    kc, "SELECT handle, name, followers, score, power_rel, stats FROM kols")}
            agg, first = {}, {}
            for h, tok, ts, kind, r1h, r24h, max24, rug, mcap0, fol in _q(
                    kc, "SELECT handle, token, ts, kind, r1h, r24h, max24, rug, mcap0, followers FROM calls "
                        "WHERE kind IN ('call', 'brag') AND handle NOT LIKE 'w:%'"):
                a = agg.setdefault(h, {"calls": 0, "brags": 0, "first": None, "last": None, "r1h": [], "r24h": [],
                                       "max24": [], "rug": 0, "mcap0": [], "fol": None})
                if kind == "brag":
                    a["brags"] += 1
                    continue
                a["calls"] += 1
                a["first"] = ts if a["first"] is None else min(a["first"], ts)
                a["last"] = ts if a["last"] is None else max(a["last"], ts)
                a["r1h"].append(r1h)
                a["r24h"].append(r24h)
                a["max24"].append(max24)
                a["rug"] += 1 if rug else 0
                if mcap0:
                    a["mcap0"].append(mcap0)
                if fol:
                    a["fol"] = fol
                k = (h, tok)
                if k not in first or ts < first[k][0]:
                    first[k] = (ts, r1h, mcap0)
            mfirst = _minute_first(mc)
        finally:
            _close(kc, mc)
        # 10.11. (Grok MCP audit 5): per caller, one call per token (its first), as kol/score and the minute check
        # count. The 1 h result is minute.db r60 (entry = close of the call's minute, what a copy can pay) when the
        # minute check measured it, else kol.db r1h; minus the round-trip cost. Tokens known to be under $30k at the
        # call are left out (CLAUDE.md: not analysed, never traded).
        cost = _cost()
        ev, mins = {}, {}
        for (h, tok), (_ts, r1h, mcap0) in first.items():
            m = mfirst.get((h, tok))
            if m is None and mcap0 is not None and mcap0 < MIN_MCAP:
                continue
            r = m[1] if m and m[1] is not None else r1h
            if r is not None:
                ev.setdefault(h, []).append(r - cost)
        for (h, _tok), (_ts, _r60, t10, sl) in mfirst.items():
            mins.setdefault(h, []).append((t10 is not None and (sl is None or t10 < sl), sl is not None))
        try:
            from ui import public
            stars = public.star_handles()
        except Exception:  # noqa: BLE001
            stars = set()
        try:
            with open(os.path.join(ROOT, "kol", "config.json")) as f:
                good = json.load(f).get("good_score", 50)
        except (OSError, ValueError):
            good = 50
        rows = []
        for h in set(agg) | {k for k in kols if not k.startswith("w:")}:
            a = agg.get(h) or {"calls": 0, "brags": 0, "first": None, "last": None, "r1h": [], "r24h": [], "max24": [],
                               "rug": 0, "mcap0": [], "fol": None}
            name, fol, score, prel, stats, bot = kols.get(h, (None, None, None, None, None, 0))
            fol = fol or a["fol"]
            measured = [m for m in a["max24"] if m is not None]
            big = (fol or 0) >= 100_000 or h.lower() in stars
            posts = a["calls"] + a["brags"]
            n_ev, mean_ev, med_ev, lo_ev = _ev(ev.get(h) or [])
            mm = mins.get(h) or []
            hits = sum(1 for c, _s in mm if c)
            stops = sum(1 for c, s in mm if s and not c)
            rows.append({
                "handle": h, "platform": platform_of(h), "name": name, "followers": _i(fol),
                "first_call_ts": _i(a["first"]), "last_call_ts": _i(a["last"]), "calls": a["calls"],
                "measured_calls": len(measured),
                "hit_rate": round(sum(1 for m in measured if m >= HIT) / len(measured), 4) if measured else None,
                "avg_r1h": _avg(a["r1h"]), "median_r1h": _med(a["r1h"]),
                "avg_r24h": _avg(a["r24h"]), "median_r24h": _med(a["r24h"]),
                "x2_share": round(sum(1 for m in measured if m >= X2) / len(measured), 4) if measured else None,
                "rug_count": a["rug"], "avg_mcap_at_call": _avg(a["mcap0"]),
                "ev_n": n_ev, "mean_r1h_after_cost": mean_ev, "median_r1h_after_cost": med_ev, "ev_lower": lo_ev,
                "minute_n": len(mm), "hit10_clean": round(hits / len(mm), 4) if mm else None,
                "hit10_wilson_low": round(wilson_low(hits, len(mm)), 4) if mm else None,
                "stop_first_share": round(stops / len(mm), 4) if mm else None,
                "call_power": _f(score, 2), "power_rel": _f(prel, 4), "bot": bool(bot),
                "big_name": big, "rising_star": (not big) and (score or 0) >= good,
                "bragger": a["brags"] >= BRAG_MIN and posts > 0 and a["brags"] / posts >= BRAG_SHARE, "brags": a["brags"]})
        return rows
    return _cached(("lb", _path("kol"), _path("minute")), build)


def caller_leaderboard(platform=None, min_calls=None, sort=None, limit=None, offset=None, min_measured=None):
    limit, offset = _page(limit, offset)
    rows = list(_leaderboard_rows())
    if platform in ("x", "telegram"):
        rows = [r for r in rows if r["platform"] == platform]
    if min_calls:
        rows = [r for r in rows if r["calls"] >= int(min_calls)]
    try:
        mm = MIN_MEASURED if min_measured is None else max(0, int(min_measured))
    except (TypeError, ValueError):
        mm = MIN_MEASURED
    if mm:   # 10.11. (Grok MCP audit 5): a handful of calls ranks nobody
        rows = [r for r in rows if r["ev_n"] >= mm]
    key = sort if sort in SORTS else "ev_lower"
    field = "call_power" if key == "score" else key
    rows.sort(key=lambda r: (r.get(field) is None, -(r.get(field) or 0), r["handle"]))
    cost = _cost()
    return _paged(rows, limit, offset, sort=key, min_measured=mm,
                  definitions={"hit_rate": f"24 h WICK, not tradable: share of measured calls whose highest price at any "
                                           f"moment within 24 h reached +{int(HIT * 100)} % (nobody sells the top); "
                                           "rank by ev_lower instead",
                               "x2_share": "24 h wick: share of measured calls whose 24 h high reached 2x",
                               "r1h/r24h": "price change 1 h / 24 h after the call, as a fraction (0.25 = +25 %)",
                               "ev_n": "measured calls the EV stands on: one per token (the caller's first), tokens "
                                       "under $30k at the call left out; min_measured filters on it (default "
                                       f"{MIN_MEASURED})",
                               "mean_r1h_after_cost/median_r1h_after_cost": (
                                   "1 h result per call after the round-trip cost "
                                   f"({cost * 100:g} %, kol/tpsl.COST): minute.db r60 (entry = close of the call's "
                                   "minute) when measured, else kol.db r1h; fraction"),
                               "ev_lower": f"mean_r1h_after_cost - {EV_Z:g} standard errors (null under 2 calls): the "
                                           "cautious expected result per copied call; the default sort",
                               "hit10_clean/hit10_wilson_low": ("minute.db: share of the caller's first calls per "
                                                                "token where +10 % came before the -20 % stop within "
                                                                f"60 min, and its Wilson lower bound (z {WILSON_Z})"),
                               "stop_first_share": "minute.db: share where the -20 % stop came first",
                               "rug_count": "calls whose price fell 90 %+ within 24 h",
                               "call_power": "MemeSonar caller score 0-100 (kol/score.py)",
                               "big_name": "100k+ followers or on the stars list",
                               "rising_star": "not a big name, call_power >= good_score (kol/config.json)",
                               "bragger": f">= {BRAG_MIN} 'brag' posts and >= {int(BRAG_SHARE * 100)} % of their posts"})


# ---------- 2. caller history ------------------------------------------------------------------------------------

def _minute_status(path, ts, mcap0, pair, has_tokens, now):
    """10.11. (Grok MCP audit 6): why a call has no minute path (max_1h / min_1h null)."""
    if path is not None and path.get("bad"):
        return f"bad:{path['bad']}"   # svijeca = no trade within 5 min of the call, pool = GeckoTerminal has no pool
    if now - ts < MINUTE_MIN_AGE_S:
        return "too_recent"
    if ts < now - MINUTE_DAYS * 86400:
        return "older_than_30d"       # kol/minute keeps 30 days
    if mcap0 is not None and mcap0 < MIN_MCAP:
        return "under_30k"            # CLAUDE.md: not analysed, so never measured
    if has_tokens and not pair:
        return "no_pair"              # the token's pool was never resolved: the minute check cannot ask for candles
    return "waiting"                  # in the minute check's queue


def _candle_path(mc, tok, ts):
    """The minute path of a call from the candles minute.db keeps per token (call_candles: 4 h after each measured
    call of the token), when the call itself has no call_path row (a later call of the same token)."""
    try:
        from kol import minute
        candles = minute.candles_for(mc, tok, ts - 600, ts + 3700) if mc is not None else []
        return minute.path(candles, ts) if candles else None
    except Exception:  # noqa: BLE001 - no call_candles table (older minute.db)
        return None


def _night_outcomes(pairs):
    """{(tweet_id, token): outcome} of events.db call_outcomes (the night batch, events/outcomes + remeasure); {}
    without events.db."""
    try:
        from events import outcomes
        return outcomes.lookup(pairs)
    except Exception:  # noqa: BLE001 - the history answers without it
        return {}


def caller_history(handle, platform=None, since_ts=None, limit=None, offset=None):
    limit, offset = _page(limit, offset)
    h = _handle(handle, platform)
    if not h:
        return {"error": "handle is required"}
    since = int(since_ts or 0)
    now = int(time.time())
    kc, mc, hc = _ro("kol"), _ro("minute"), _ro("hype")
    try:
        total = (_q(kc, "SELECT COUNT(*) FROM calls WHERE handle=? COLLATE NOCASE AND kind='call' AND ts>=?",
                    (h, since)) or [(0,)])[0][0]
        have = _cols(kc, "calls")
        opt = ", ".join(c if c in have else f"NULL AS {c}" for c in ("complete", "measured_ts", "bad", "msrc"))
        tokens = _has(kc, "tokens")
        pair = "(SELECT pair FROM tokens t WHERE t.token=c.token)" if tokens else "NULL"
        calls = _dicts(kc, f"SELECT tweet_id, token, symbol, ts, p0, mcap0, r1h, r24h, max24, rug, url, {opt}, "
                           f"{pair} AS pair FROM calls c WHERE handle=? COLLATE NOCASE AND kind='call' AND ts>=? "
                           f"ORDER BY ts DESC LIMIT ? OFFSET ?", (h, since, limit, offset))
        syms = _symbols(kc, hc, [c["token"] for c in calls if not c["symbol"]])
        night = _night_outcomes([(c["tweet_id"], c["token"]) for c in calls])
        rows = []
        bad = _bad(mc)
        for c in calls:
            tid, tok, ts, p0, r1h, r24h = c["tweet_id"], c["token"], c["ts"], c["p0"], c["r1h"], c["r24h"]
            pr = _dicts(mc, f"SELECT entry, mcap_e, hi60, lo60, r60, {bad} AS bad FROM call_path WHERE tweet_id=? "
                            "AND token=?", (tid, tok))
            path = pr[0] if pr else None
            hi60 = lo60 = r60 = None
            m_src = None
            if path and path["entry"] is not None:
                hi60, lo60, r60, m_src = path["hi60"], path["lo60"], path["r60"], "minute"
            elif mc is not None and not (path and path.get("bad")):
                cp = _candle_path(mc, tok, ts)
                if cp:
                    hi60, lo60, r60, m_src = cp["hi60"], cp["lo60"], cp["r60"], "minute_candles"
                    path = {"entry": cp["entry"], "mcap_e": None, "bad": None}
            entry = path["entry"] if path else None
            snaps = None
            # the price at the call and 1 h / 24 h later: kol.db's measure (5-min candles) first; the minute entry and
            # the DexScreener snapshots when the call was never measured (79 of 83 calls of one caller had no r24h)
            px0, px0_src = (p0, "calls") if p0 else ((entry, "minute") if entry else (None, None))
            if not px0:
                snaps = _snapshots(kc, hc, tok, ts - SNAP_GAP, ts + 24 * 3600 + SNAP_GAP)
                s0 = _near(snaps, ts)
                px0, px0_src = (s0[1], "snapshots") if s0 else (None, None)
            price_1h, ch1, ch1_src = None, None, None
            if p0 and r1h is not None:
                price_1h, ch1, ch1_src = p0 * (1 + r1h), r1h, "calls"
            elif entry and r60 is not None:
                price_1h, ch1, ch1_src = entry * (1 + r60), r60, m_src
            price_24h, ch24, p24_src = None, None, None
            if p0 and r24h is not None:
                price_24h, ch24, p24_src = p0 * (1 + r24h), r24h, "calls"
            elif now >= ts + CHECK_S:
                if snaps is None:
                    snaps = _snapshots(kc, hc, tok, ts - SNAP_GAP, ts + 24 * 3600 + SNAP_GAP)
                s24 = _near(snaps, ts + 24 * 3600)
                if s24:
                    price_24h, p24_src = s24[1], "snapshots"
                    ch24 = s24[1] / px0 - 1 if px0 else None
            mcap0 = c["mcap0"] if c["mcap0"] is not None else (path or {}).get("mcap_e")
            if r24h is not None:
                mstat = "measured"
            elif c["bad"]:
                mstat = f"bad:{c['bad']}"   # mcap = dust pool at the call, skok = an implausible jump: not trusted
            elif now < ts + CHECK_S:
                mstat = "pending"
            elif c["complete"] and not c["p0"] and tokens and not c["pair"]:
                mstat = "no_pair"           # no tradable Solana pair was ever found for the token
            elif c["measured_ts"] is not None:
                mstat = "measured_without_24h"   # the candles stop before the 24 h checkpoint (no trades)
            else:
                mstat = "never_measured"    # kol/backfill_calls.py measures these at night
            before = (_q(kc, "SELECT COUNT(DISTINCT handle) FROM calls WHERE token=? AND kind='call' AND handle!=? "
                             "AND ts>=? AND ts<?", (tok, h, ts - CO_CALL_S, ts)) or [(0,)])[0][0]
            after = (_q(kc, "SELECT COUNT(DISTINCT handle) FROM calls WHERE token=? AND kind='call' AND handle!=? "
                            "AND ts>=? AND ts<=?", (tok, h, ts, ts + CO_CALL_S)) or [(0,)])[0][0]
            rows.append({"token": tok, "symbol": c["symbol"] or syms.get(tok), "call_ts": _i(ts), "url": c["url"],
                         "price_at_call": _f(px0, 12), "price_at_call_source": px0_src,
                         "market_cap_at_call": _f(mcap0, 0),
                         "max_1h": _f(hi60, 4), "min_1h": _f(lo60, 4), "max_1h_source": m_src,
                         "minute_status": "measured" if m_src else _minute_status(path, ts, c["mcap0"], c["pair"],
                                                                                   tokens, now),
                         "max_24h": _f(c["max24"], 4), "min_24h": None,
                         "price_1h": _f(price_1h, 12), "change_1h": _f(ch1, 4), "change_1h_source": ch1_src,
                         "price_24h": _f(price_24h, 12), "change_24h": _f(ch24, 4), "price_24h_source": p24_src,
                         "measure_status": mstat, "rug": bool(c["rug"]),
                         "other_callers_15m_before": before, "other_callers_15m_after": after})
            o = night.get((tid, tok))
            if o and o["status"] in ("ok", "unavailable") and mstat != "measured":
                # 11.11. (events/remeasure.py): the night measured it from minute candles, or says why it cannot
                r = rows[-1]
                r.update(measure_status=o["status"], measure_reason=o["reason"], measure_source=o["src"])
                for k in ("max_1h", "max_24h", "change_24h"):
                    if r.get(k) is None and o.get(k) is not None:
                        r[k] = _f(o[k], 4)
                if r.get("max_1h") is not None and not r.get("max_1h_source"):
                    r["max_1h_source"] = o["src"]
    finally:
        _close(kc, mc, hc)
    return _paged(rows, limit, offset, total=total, handle=h, platform=platform_of(h),
                  definitions={"max_1h/min_1h": "highest / lowest move in the first 60 min after the minute of the call "
                                                "(minute candles, fraction of the entry); max_1h_source minute | "
                                                "minute_candles, null = not measured (minute_status says why: "
                                                "under_30k, older_than_30d, too_recent, no_pair, waiting, bad:svijeca "
                                                "= no trade within 5 min, bad:pool = no pool on GeckoTerminal)",
                               "price_24h": "price 24 h after the call; price_24h_source calls (kol/measure candles) | "
                                            "snapshots (DexScreener, within 25 min); measure_status: measured, "
                                            "pending, no_pair, bad:mcap / bad:skok (untrusted), measured_without_24h, "
                                            "never_measured (queued for the night backfill); after the night "
                                            "remeasure ok (measure_source gt_minute: minute candles) or unavailable "
                                            "(measure_reason says why: nema poola, ispod 30k, no trade within 30 min)",
                               "change_1h": "fraction; change_1h_source calls (r1h) | minute (r60 from the minute entry)",
                               "max_24h": "highest move within 24 h (fraction); min_24h is not measured"})


# ---------- 3. token history -------------------------------------------------------------------------------------

def _thin(points, n=MAX_LIMIT):
    if len(points) <= n:
        return points
    step = len(points) / n
    return [points[int(i * step)] for i in range(n - 1)] + [points[-1]]


def token_history(token_address):
    from trade import settings
    tok = (token_address or "").strip()
    if not tok or len(tok) < 32:
        return {"error": "token_address must be a Solana token address"}
    kc, hc, rc, tc, lc, trc = _ro("kol"), _ro("hype"), _ro("rug"), _ro("topcheck"), _ro("league"), _ro("trade")
    try:
        raw = _q(kc, "SELECT handle, ts, kind, mcap0, followers, url FROM calls WHERE token=? ORDER BY ts LIMIT 500", (tok,))
        fol = _followers(kc, [r[0] for r in raw if r[0] and not r[0].startswith("w:")])
        calls = []
        for h, ts, kind, mc, f0, url in raw:
            f, src = (int(f0), "call") if f0 else fol.get(h, (None, None))
            calls.append({"handle": h, "platform": platform_of(h), "ts": _i(ts), "kind": kind,
                          "market_cap_at_call": _f(mc, 0), "followers": _i(f), "followers_source": src,
                          "followers_at_call": _i(f0), "url": url})
        series = {}
        for ts, price, mcap, liq in _q(hc, "SELECT ts, price, mcap, liquidity FROM hype_snapshots WHERE token=? "
                                           "ORDER BY ts", (tok,)):
            series[int(ts)] = {"ts": int(ts), "price": _f(price, 12), "market_cap": _f(mcap, 0), "liquidity": _f(liq, 0)}
        for ts, price, mcap, liq in _q(kc, "SELECT ts, price, mcap, liq FROM snaps WHERE token=? ORDER BY ts", (tok,)):
            series.setdefault(int(ts), {"ts": int(ts), "price": _f(price, 12), "market_cap": _f(mcap, 0),
                                        "liquidity": _f(liq, 0)})
        rug = [{"checked_ts": _i(ts), "verdict": v, "score": _f(sc, 1), "top10_pct": _f(t10, 1), "bundle_pct": _f(b, 1),
                "sniper_pct": _f(s, 1), "cluster_pct": _f(cl, 1), "dev": dev}
               for ts, v, sc, t10, b, s, cl, dev in _q(rc, "SELECT checked_at, verdict, score, top10_pct, bundle_pct, "
                                                           "sniper_pct, cluster_pct, dev FROM rug_reports WHERE mint=? "
                                                           "ORDER BY checked_at DESC LIMIT 20", (tok,))]
        top = _q(tc, "SELECT ts, verdict, mcap, liq, rc_ts FROM top_check WHERE token=?", (tok,))
        arch = _q(hc, "SELECT archived_ts, kind, reason, peak_mcap, last_mcap FROM rug_archive WHERE token=?", (tok,))
        trades = [{"league_trade_id": d["id"], "opened_ts": _i(d["opened_ts"]), "closed_ts": _i(d["closed_ts"]),
                   "status": d["status"], "source": d["source"], "entry_market_cap": _f(d.get("entry_mcap"), 0),
                   "exit_market_cap": _f(d.get("exit_mcap"), 0), "exit_note": d.get("note"),
                   "exit_reason": (_exit_kind(d.get("note"), d.get("exit_rule")) if d["status"] == "closed" else None),
                   "demo_pnl_usd": _f(d.get("pnl_usd"), 2)}
                  for d in _dicts(lc, "SELECT * FROM trades WHERE user=? AND token=? ORDER BY opened_ts",
                                  (settings.LEAGUE_USER, tok))]
        real = []
        for i, lid, o, c, m, st, si, sb, fe, why in _q(
                trc, "SELECT id, league_id, opened_ts, closed_ts, mode, status, sol_in, sol_back, fees_sol, reason "
                     "FROM positions WHERE token=? ORDER BY id", (tok,)):
            row = {"position_id": i, "league_trade_id": lid, "opened_ts": _i(o), "closed_ts": _i(c), "mode": m,
                   "status": st, "sol_in": _f(si, 4), "sol_back": _f(sb, 4), "fees_sol": _f(fe, 5), "block_reason": None}
            if st in ("blocked", "failed"):   # 10.11. (Grok MCP audit 4): why the real copy did not happen
                row["block_reason"] = _block_reason(trc, i, why)
            real.append(row)
    finally:
        _close(kc, hc, rc, tc, lc, trc)
    pts = _thin([series[k] for k in sorted(series)])
    return {"ts": int(time.time()), "token": tok, "calls": calls, "price_series": pts,
            "rug_checks": rug,
            "top_check": ({"ts": _i(top[0][0]), "verdict": top[0][1], "market_cap": _f(top[0][2], 0),
                           "liquidity": _f(top[0][3], 0), "rugcheck_ts": _i(top[0][4])} if top else None),
            "rug_archive": ({"archived_ts": _i(arch[0][0]), "kind": arch[0][1], "reason": arch[0][2],
                             "peak_market_cap": _f(arch[0][3], 0), "last_market_cap": _f(arch[0][4], 0)} if arch else None),
            "autopilot_demo_trades": trades, "autopilot_real_positions": real,
            "notes": "price_series: hype_snapshots (every 20 min) + kol snaps, thinned to at most 500 points; calls[]."
                     "followers: at the call when the collector saw it (followers_at_call), else kols.followers, "
                     "tg channel subscribers or the handle's largest seen count (followers_source)"}


# ---------- 4. wallets -------------------------------------------------------------------------------------------

def _kol_ids(kc=None):
    own = kc is None
    kc = kc if kc is not None else _ro("kol")
    try:
        return {w: {"name": n, "twitter": tw, "handle": _xhandle(tw), "telegram": tg, "pnl": p, "wins": wi, "losses": lo}
                for w, n, tw, tg, p, wi, lo in _q(kc, "SELECT wallet, name, twitter, telegram, pnl, wins, losses FROM kol_ids")}
    finally:
        if own:
            _close(kc)


def _linked(link):
    return link.get("handle") or link.get("name") if link else None


def _wallet_meta(wc, kidx, ids, wallet):
    """10.11. (Grok MCP audit 8): who a wallet is and how good: tier / score from wallets.db; an influencer's wallet
    the wallet scorer has not reached yet (PainCrypt0, kayz_ce) takes the score of its linked caller (kols
    call_power, score_source linked_kol_call_power). linked_handle from kol.db kol_ids (wallet -> X handle)."""
    t = _q(wc, "SELECT tier, score FROM wallets WHERE wallet=?", (wallet,))
    link = ids.get(wallet) or {}
    h = _linked(link)
    tier, score = (t[0][0], t[0][1]) if t else (None, None)
    src = "wallets" if score is not None else None
    if score is None and h:
        k = kidx.get(h.lower()) or kidx.get((link.get("name") or "").lower())
        if k and k[2] is not None:
            score, src = k[2], "linked_kol_call_power"
    return {"tier": tier, "score": _f(score, 2), "score_source": src, "linked_handle": h,
            "kind": "influencer" if link else ("smart" if tier in ("S", "A", "B") else "other")}


def wallet_leaderboard(kind=None, limit=None, offset=None):
    limit, offset = _page(limit, offset)
    kc = _ro("kol")
    try:
        ids = _kol_ids(kc)
        kidx = _kol_index(kc)
    finally:
        _close(kc)
    wc = _ro("wallets")
    try:
        rows = []
        for w, tier, score, cscore, stats, labels, last_tx in _q(
                wc, "SELECT wallet, tier, score, copy_score, stats, labels, last_tx_ts FROM wallets "
                    "WHERE stats IS NOT NULL ORDER BY COALESCE(score, 0) DESC"):
            st = _json(stats)
            link = ids.get(w) or {}
            meta = _wallet_meta(wc, kidx, ids, w)
            rows.append({"wallet": w, "kind": meta["kind"], "tier": tier, "score": meta["score"],
                         "score_source": meta["score_source"], "copy_score": _f(cscore, 2),
                         "realized_pnl_sol": _f(st.get("realized_sol"), 4), "unrealized_pnl_sol": _f(st.get("unrealized_sol"), 4),
                         "win_rate": _f(st.get("win_rate"), 4), "median_hold_min": _f(st.get("median_hold_min"), 1),
                         "style": st.get("style"), "last_trade_ts": _i(last_tx), "linked_handle": _linked(link)})
        seen = {r["wallet"] for r in rows}
        for w, link in ids.items():   # influencer wallets the wallet scorer has not reached yet
            if w not in seen:
                wins, losses = link.get("wins") or 0, link.get("losses") or 0
                meta = _wallet_meta(wc, kidx, ids, w)
                rows.append({"wallet": w, "kind": "influencer", "tier": meta["tier"], "score": meta["score"],
                             "score_source": meta["score_source"], "copy_score": None,
                             "realized_pnl_sol": _f(link.get("pnl"), 4), "unrealized_pnl_sol": None,
                             "win_rate": round(wins / (wins + losses), 4) if wins + losses else None,
                             "median_hold_min": None, "style": None, "last_trade_ts": None,
                             "linked_handle": _linked(link)})
    finally:
        _close(wc)
    if kind in ("influencer", "smart"):
        rows = [r for r in rows if r["kind"] == kind]
    return _paged(rows, limit, offset,
                  definitions={"kind": "influencer = a known influencer's wallet (kol_ids); smart = wallet tier S/A/B",
                               "score": "wallets.db score; for an influencer wallet not scored yet, its linked caller's "
                                        "call_power (score_source linked_kol_call_power)",
                               "pnl": "SOL; realized from closed positions, unrealized at the last scoring"})


def wallet_history(address, limit=None, offset=None):
    limit, offset = _page(limit, offset)
    w = (address or "").strip()
    if len(w) < 32:
        return {"error": "address must be a Solana wallet address"}
    wc, hc, kc = _ro("wallets"), _ro("hype"), _ro("kol")
    try:
        trades = {}
        for sig, ts, mint, tokens, sol, kind in _q(wc, "SELECT sig, ts, mint, tokens, sol, kind FROM wallet_trades "
                                                        "WHERE wallet=? ORDER BY ts DESC LIMIT 5000", (w,)):
            trades[(sig, mint)] = {"sig": sig, "ts": _i(ts), "token": mint, "side": kind, "sol": _f(sol, 4),
                                   "tokens": _f(tokens, 4), "market_cap_sol": None}
        for sig, mint, side, ts, sol in _q(hc, "SELECT sig, mint, side, ts, sol FROM chain_trades WHERE wallet=? "
                                               "ORDER BY ts DESC LIMIT 5000", (w,)):
            trades.setdefault((sig, mint), {"sig": sig, "ts": _i(ts), "token": mint, "side": side, "sol": _f(sol, 4),
                                            "tokens": None, "market_cap_sol": None})
        for sig, mint, side, sol, tokens, mcs, ts in _q(hc, "SELECT sig, mint, side, sol, tokens, mcap_sol, ts FROM live_trades "
                                                            "WHERE wallet=? ORDER BY ts DESC LIMIT 5000", (w,)):
            row = trades.setdefault((sig, mint), {"sig": sig, "ts": _i(ts), "token": mint, "side": side,
                                                  "sol": _f(sol, 4), "tokens": _f(tokens, 4), "market_cap_sol": None})
            row["market_cap_sol"] = _f(mcs, 2)
        info = _q(wc, "SELECT tier, score, stats FROM wallets WHERE wallet=?", (w,))
        meta = _wallet_meta(wc, _kol_index(kc), _kol_ids(kc), w)
    finally:
        _close(wc, hc, kc)
    rows = sorted(trades.values(), key=lambda r: -(r["ts"] or 0))
    st = _json(info[0][2]) if info else {}
    return _paged(rows, limit, offset, wallet=w, tier=meta["tier"], score=meta["score"],
                  score_source=meta["score_source"], kind=meta["kind"],
                  realized_pnl_sol=_f(st.get("realized_sol"), 4), win_rate=_f(st.get("win_rate"), 4),
                  linked_handle=meta["linked_handle"],
                  notes="sides: buy / sell; sol is the SOL size (sells from webhooks may have none); market_cap_sol "
                        "only for trades seen live (48 h)")


def wallet_clusters():
    """Groups of wallets that buy together (corr/analyze: same funder, same rug cluster, same-second buys) and the
    callers' clusters that call together, from the newest corr.db snapshot."""
    try:
        from corr import store as cstore
        ts, data, _ai = cstore.latest(_path("corr"))
    except Exception:  # noqa: BLE001
        ts, data = None, None
    data = data or {}
    groups = [{"id": g.get("id"), "wallets": (g.get("wallets") or [])[:100], "handles": (g.get("handles") or [])[:50],
               "tokens": (g.get("tokens") or g.get("shared_tokens") or [])[:100] if isinstance(g.get("tokens"), list) else g.get("tokens"),
               "why": g.get("why") or g.get("reasons"), "score": g.get("score"), "callers_clusters": g.get("clusters")}
              for g in (data.get("groups") or [])[:MAX_LIMIT]]
    clusters = [{"id": c.get("id"), "callers": (c.get("members") or [])[:50], "wallets": (c.get("wallets") or [])[:50],
                 "tokens_together": c.get("tokens"), "score": c.get("score"), "leader": c.get("leader")}
                for c in (data.get("clusters") or [])[:MAX_LIMIT]]
    return {"ts": int(time.time()), "snapshot_ts": _i(ts), "wallet_groups": groups, "caller_clusters": clusters,
            "notes": "wallet_groups: wallets joined by a common funder, the same rug cluster or repeated same-second "
                     "buys; caller_clusters: accounts that call the same tokens together (tokens_together = count)"}


# ---------- 6. autopilot trades ----------------------------------------------------------------------------------

# 10.11. (Grok MCP audit 2): the exit rule that fired, in the words league.db trades.exit_rule uses (written by the
# exit code from this day on; older trades are read from the note). SPSC (trade 374) said "smart sell" next to the note
# "auto: stop_loss": every "auto: ..." note was "smart sell", so a smart profile's stop looked like a take profit.
EXIT_RULES = ("tp", "sl", "time", "smart_tp", "smart_sl", "smart_trail", "smart_other", "wallet_sold", "manual", "rug")
# paper/sim.py exit reasons (smart sell: "auto: <reason>" in the demo note, bare in a paper fill)
_SMART_RULE = {"stop_loss": "smart_sl", "trailing": "smart_trail", "moonbag_trailing": "smart_trail",
               "breakeven": "smart_trail", "rug": "rug", "stale": "smart_other", "time": "smart_other",
               "moonbag_time": "smart_other"}
_PARTIAL = ("djelomična", "pokušaj")   # a partial sale or a retried try: not what closed the position
_MC_NOTE = re.compile(r"na MC \$([0-9][0-9,.]*)\s*([kKmM]?)")


def _exit_kind(note, rule=None):
    """The exit rule (one of EXIT_RULES) from league trades.exit_rule when set, else from the exit text:
    'auto TP +40%' -> tp, 'auto SL -60%' -> sl, 'auto vrijeme ...' -> time (a data exit's measured hour ran out),
    'auto: stop_loss' -> smart_sl, 'auto: take_profit_2x' / 'auto: smart_sell_eksplozija' -> smart_tp,
    'auto: trailing' / breakeven -> smart_trail, 'auto: stale' / time -> smart_other, 'copy: X je prodao' ->
    wallet_sold, a button / 'ručno' / an empty closed demo note -> manual, rug / no price -> rug. None = no text."""
    if rule in EXIT_RULES:
        return rule
    n = " ".join((note or "").strip().lower().split())
    if not n:
        return None
    if n.startswith(("auto tp", "tp ")):
        return "tp"
    if n.startswith(("auto sl", "sl ")):
        return "sl"
    if "vrijeme" in n:
        return "time"
    if "je prodao" in n:
        return "wallet_sold"
    if n.startswith(("rekt", "otpisano")):
        return "rug" if "cijen" in n else "manual"
    if "gumb" in n or "ručn" in n or n in ("demo izlaz", "manual", "ručno"):
        return "manual"
    r = n[5:].strip() if n.startswith(("auto:", "auto ")) else n
    r = r.split()[0] if r else ""
    if r.startswith(("take_profit", "smart_sell")):
        return "smart_tp"
    if r in _SMART_RULE:
        return _SMART_RULE[r]
    return "smart_other" if n.startswith("auto") else "manual"


def _exit_detail(note):
    n = (note or "").strip()
    for p in ("auto:", "auto "):
        if n.lower().startswith(p):
            return n[len(p):].strip()
    return n or None


def _mc_from_note(note):
    """'kupljeno za $25 na MC $84,000, ...' (league/copy entry log) -> 84000.0"""
    m = _MC_NOTE.search(note or "")
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", "").rstrip("."))
    except ValueError:
        return None
    return v * {"k": 1e3, "m": 1e6}.get(m.group(2).lower(), 1) or None


def _block_reason(tc, pid, reason):
    """10.11. (Grok MCP audit 4): why a real copy was refused or failed: positions.reason (run_trade writes the gate's
    reason there), else the buy order's error (executor.buy)."""
    if reason and reason not in ("namjera zapisana, šaljem",):
        return reason
    r = _q(tc, "SELECT error FROM orders WHERE position_id=? AND side='buy' AND error IS NOT NULL ORDER BY id DESC "
               "LIMIT 1", (pid,))
    return r[0][0] if r else reason


LOT_COLS = "id, token, symbol, opened_ts, closed_ts, mode, status, reason, sol_in, sol_back, fees_sol, league_id"


def _lot_sql(tc):
    """The positions columns of a lot; paper_id (old paper-follow positions) only when the column exists."""
    return LOT_COLS + (", paper_id" if "paper_id" in _cols(tc, "positions") else ", NULL AS paper_id")


def _groups(tc, since=0):
    """Open and closed positions as trades: the lots of one token whose lives overlap are one trade (DCA)."""
    rows = _q(tc, f"SELECT {_lot_sql(tc)} FROM positions WHERE status IN ('open','closed') AND opened_ts>=? "
                  "ORDER BY opened_ts, id", (since,))
    groups, cur = [], {}
    for r in rows:
        tok, o, c, st = r[1], r[3] or 0, r[4], r[6]
        g = cur.get(tok)
        if g is not None and (g["end"] is None or o <= g["end"]):
            g["lots"].append(r)
            g["end"] = None if (g["end"] is None or st == "open") else max(g["end"], c or 0)
        else:
            g = {"token": tok, "lots": [r], "end": None if st == "open" else (c or o), "kind": "position"}
            groups.append(g)
            cur[tok] = g
    for g in groups:
        g["status"] = "open" if any(l[6] == "open" for l in g["lots"]) else "closed"
        g["id"] = g["lots"][0][0]
        g["entry_ts"] = min(l[3] or 0 for l in g["lots"])
    return groups


def _refused(tc, since=0):
    """10.11. (Grok MCP audit 4): real positions the Autopilot refused (blocked: a gate said no) or that failed (the
    swap did not go through), one trade each. 0xMarko77's Hope copy (position 381) was in trade.db as 'blocked' and the
    tool listed only open and closed ones, so the reason never reached the analyst."""
    return [{"token": r[1], "lots": [r], "end": r[3], "kind": "refused", "status": r[6], "id": r[0],
             "entry_ts": r[3] or 0}
            for r in _q(tc, f"SELECT {_lot_sql(tc)} FROM positions WHERE status IN ('blocked','failed') AND opened_ts>=? "
                            "ORDER BY opened_ts, id", (since,))]


def _demo_only(tc, lc, since=0):
    """Demo trades of the Autopilot account with no real (or dry) position at all: the trade loop was down or the
    trade predates it. Only on request (include_demo_only)."""
    from trade import settings
    mirrored = {r[0] for r in _q(tc, "SELECT DISTINCT league_id FROM positions WHERE league_id IS NOT NULL")}
    return [{"token": tok, "lots": [], "end": c, "kind": "demo_only", "status": st, "id": None, "demo_id": i,
             "entry_ts": o or 0}
            for i, tok, o, c, st in _q(lc, "SELECT id, token, opened_ts, closed_ts, status FROM trades WHERE user=? "
                                           "AND opened_ts>=? ORDER BY opened_ts, id", (settings.LEAGUE_USER, since))
            if i not in mirrored]


def _supply(kc, tok):
    r = _q(kc, "SELECT supply FROM tokens WHERE token=?", (tok,))
    return r[0][0] if r and r[0][0] else None


def _paper(pc, pid):
    """(exit_reason, entry mcap, score) of an old paper-follow position's paper.db trade (positions.paper_id)."""
    if pc is None or not pid:
        return None
    t = _q(pc, "SELECT exit_reason, status FROM trades WHERE id=?", (pid,))
    c = _q(pc, "SELECT mcap, score FROM candidates WHERE trade_id=? LIMIT 1", (pid,))
    if not t and not c:
        return None
    return {"exit_reason": t[0][0] if t and t[0][1] == "closed" else None,
            "entry_mcap": c[0][0] if c else None, "score": c[0][1] if c else None}


def _entry_mcap(d, supply, copy_note, paper):
    """(market cap at the entry, source): the demo's entry_mcap; the market cap league/copy wrote in the entry log
    ("na MC $84,000", the same DexScreener read); the demo's entry price x the token supply (kol.db tokens); the
    paper candidate's."""
    if d and d.get("entry_mcap"):
        return d["entry_mcap"], "demo_trade"
    mc = _mc_from_note(copy_note)
    if mc:
        return mc, "copy_log"
    if d and d.get("entry_px") and supply:
        return d["entry_px"] * supply, "entry_price_x_supply"
    if paper and paper.get("entry_mcap"):
        return paper["entry_mcap"], "paper"
    return None, None


def _exit_policy(follow_exit, d):
    """10.11. (Grok MCP audit 2): which exit this trade ran under and which stop applied: the follow's exit mode
    (smart | tpsl | podaci | mirror | mirror_smart | manual) and the trade's own rule (league trades.auto): TP/SL
    levels, the data exit's deadline, or the smart profile's stop from auto_state (paper/sim cfg sl, e.g. -0.35 with
    sl_delay_min). A -17 % exit under a smart profile is that profile's stop, not the account's sl_default."""
    a = _json((d or {}).get("auto"))
    st = _json((d or {}).get("auto_state"))
    out = {"follow_exit_mode": (follow_exit or {}).get("mode"), "trade_rule": a.get("mode"),
           "tp": a.get("tp") or None, "sl": a.get("sl") or None, "hold_until_ts": _i(a.get("until")),
           "stop_applied": None, "stop_applied_pct": None, "smart_sl_delay_min": None}
    if a.get("mode") == "tpsl" and a.get("sl"):
        out["stop_applied"] = f"TP/SL stop {a['sl']}"
        m = re.fullmatch(r"([+-]?)([0-9.]+)%?", str(a["sl"]).replace(" ", ""))
        if m:   # league/auto labels are signed ("-60%"; "+5%" = a stop above the entry); a bare number is a drop
            out["stop_applied_pct"] = float(m.group(2)) * (1 if m.group(1) == "+" else -1)
    elif a.get("mode") == "smart":
        cfg = st.get("cfg") if isinstance(st.get("cfg"), dict) else {}
        if cfg.get("sl") is not None:
            pct = round(100 * float(cfg["sl"]), 2)
            out["stop_applied_pct"] = pct
            out["smart_sl_delay_min"] = cfg.get("sl_delay_min")
            out["stop_applied"] = (f"smart profile stop {pct:g} %"
                                   + (f" (armed after {cfg['sl_delay_min']:g} min)" if cfg.get("sl_delay_min") else ""))
        else:
            out["stop_applied"] = "smart profile stop (profile not stored for this trade)"
    return out


def _exit_info(d, orders, paper):
    """(rule, source, text) of what closed a trade. The real exit wins where it differs: the owner's sell button on
    the real position (orders reason "… (gumb)" / "ručno") is a manual exit even when the demo trade later closed by
    its own rule. Then league trades.exit_rule, the demo's note, the closing real order's reason (run_trade passes
    the demo note on), paper.db's exit_reason."""
    real = next((o for o in orders if o and not any(p in o.lower() for p in _PARTIAL)), None)
    if real and _exit_kind(real) == "manual" and ("gumb" in real.lower() or "ručn" in real.lower()):
        return "manual", "real_order", real
    if d and d.get("exit_rule") in EXIT_RULES:
        return d["exit_rule"], "exit_rule", d.get("note")
    if d and d.get("status") == "closed":
        k = _exit_kind(d.get("note"))
        return (k, "demo_note", d.get("note")) if k else ("manual", "demo_closed_without_note", None)
    if real:
        k = _exit_kind(real)
        if k:
            return k, "real_order", real
    if paper and paper.get("exit_reason"):
        return _exit_kind(paper["exit_reason"]), "paper", paper["exit_reason"]
    return None, None, None


def _follow_before(mc, follow, entry, days=14):
    """The followed caller's minute-check record over the `days` before the entry (only calls whose measured hour
    ended before it): n, clean +10 % share, stop-first share and the Autopilot pick score wilson_low(hit10) - stop
    share (the formula of ui/autopilot.kol_rank), i.e. what the pick could know at the entry. minute.db keeps 30 days,
    so trades older than that have none."""
    if mc is None or not follow or follow.get("kind") != "kol" or not follow.get("target"):
        return None
    h = follow["target"].lstrip("@")
    first = {}
    # a call counts only once its measured hour had ended before the entry (the triggering call's own outcome, and
    # any call of the last hour, were not known yet)
    for tok, ts, t10, sl in _q(mc, "SELECT token, ts, t10, sl_min FROM call_path WHERE handle IN (?, ?) AND "
                                   f"entry IS NOT NULL AND {_bad(mc)} IS NULL AND ts>=? AND ts<?",
                               (h, h.lower(), entry - days * 86400, entry - 3600)):
        if tok not in first or ts < first[tok][0]:
            first[tok] = (ts, t10, sl)
    n = len(first)
    if not n:
        return {"days": days, "n": 0}
    hits = sum(1 for _ts, t10, sl in first.values() if t10 is not None and (sl is None or t10 < sl))
    stops = sum(1 for _ts, t10, sl in first.values() if sl is not None and not (t10 is not None and t10 < sl))
    wl = wilson_low(hits, n)
    return {"days": days, "n": n, "hit10": round(hits / n, 4), "stop_first": round(stops / n, 4),
            "hit10_wilson_low": round(wl, 4), "pick_score": round(wl - stops / n, 4)}


def _first_call(kc, mc, hc, tok, entry, d):
    """The token's first tracked call up to the entry and its market cap: league trades.call_mcap when stored, then
    calls.mcap0 (kol/measure), minute.db mcap_e of that call, a DexScreener snapshot within 25 min. 10.11. (Grok MCP
    audit 1): most calls are never measured by kol/measure (the queue serves the newest first), so mcap0 was null and
    runup_from_first_call with it."""
    r = _q(kc, "SELECT ts, mcap0, tweet_id, handle FROM calls WHERE token=? AND kind='call' AND handle NOT LIKE 'w:%' "
               "AND ts<=? ORDER BY ts LIMIT 1", (tok, entry + 60))
    if not r:
        return None
    ts, mcap0, tid, h = r[0]
    mc0, src = None, None
    if d and d.get("call_mcap"):
        mc0, src = d["call_mcap"], "demo_trade"
    elif mcap0:
        mc0, src = mcap0, "calls"
    else:
        p = _q(mc, "SELECT mcap_e FROM call_path WHERE tweet_id=? AND token=? AND mcap_e IS NOT NULL", (tid, tok))
        if p:
            mc0, src = p[0][0], "minute"
        else:
            s = _near(_snapshots(kc, hc, tok, ts - SNAP_GAP, ts + SNAP_GAP), ts)
            if s and s[2]:
                mc0, src = s[2], "snapshots"
    return {"ts": ts, "handle": h, "mcap": mc0, "source": src}


def _demo_row(d):
    if not d:
        return None
    return {"league_trade_id": d.get("id"), "status": d.get("status"), "opened_ts": _i(d.get("opened_ts")),
            "closed_ts": _i(d.get("closed_ts")), "source": d.get("source"), "entry_market_cap": _f(d.get("entry_mcap"), 0),
            "exit_market_cap": _f(d.get("exit_mcap"), 0), "note": d.get("note"),
            "exit_reason": _exit_kind(d.get("note"), d.get("exit_rule")) if d.get("status") == "closed" else None,
            "demo_pnl_usd": _f(d.get("pnl_usd"), 2)}


def _detail(g, tc, lc, kc, wc, hc, rc, mc, pc, ctx):
    from trade import settings
    lots = g["lots"]
    tok = g["token"]
    kind = g.get("kind", "position")
    lid0 = lots[0][11] if lots else g.get("demo_id")
    demo = {}
    for l in lots:
        if l[11]:
            r = _dicts(lc, "SELECT * FROM trades WHERE id=?", (l[11],))
            if r:
                demo[l[0]] = r[0]
    d0 = demo.get(lots[0][0]) if lots else ((_dicts(lc, "SELECT * FROM trades WHERE id=?", (lid0,)) or [None])[0])
    supply = _supply(kc, tok)
    s = _q(lc, "SELECT ev_ts, note FROM copy_log WHERE trade_id=? AND action='ulaz' LIMIT 1", (lid0,)) if lid0 else []
    sig_ts, entry_note = s[0] if s else (None, None)
    papers = {l[0]: _paper(pc, l[12]) for l in lots if len(l) > 12 and l[12]}
    # entry market cap per lot (SOL-weighted over the DCA lots), each with its fallback
    emc = {}
    for l in lots:
        emc[l[0]] = _entry_mcap(demo.get(l[0]), supply, entry_note if l[11] == lid0 else None, papers.get(l[0]))
    if lots and kind == "position":
        w = [(emc[l[0]][0], l[8] or 0) for l in lots]
        wsum = sum(x for m, x in w if m and x)
        entry_mc = wsum / sum(x / m for m, x in w if m and x) if wsum else None
        if entry_mc is None:   # a dry lot without SOL: the first lot's market cap
            entry_mc = next((emc[l[0]][0] for l in lots if emc[l[0]][0]), None)
        emc_src = next((emc[l[0]][1] for l in lots if emc[l[0]][1]), None)
    else:
        entry_mc, emc_src = _entry_mcap(d0, supply, entry_note, papers.get(lots[0][0]) if lots else None)
    closed = g["status"] == "closed"
    last = max(lots, key=lambda l: l[4] or 0) if lots else None
    dl = demo.get(last[0]) if last else d0   # the demo trade of the lot that closed last
    ids = [l[0] for l in lots]
    q = ",".join("?" * len(ids))
    orders = [r[0] for r in _q(tc, f"SELECT reason FROM orders WHERE side='sell' AND status IN ('ok','dry') AND "
                                   f"position_id IN ({q}) ORDER BY ts DESC, id DESC", ids)] if ids else []
    exit_mc, xmc_src, rule, rule_src, note = None, None, None, None, None
    if closed:
        rule, rule_src, note = _exit_info(dl, orders, papers.get(last[0]) if last else None)
        if dl and dl.get("exit_mcap"):
            exit_mc, xmc_src = dl["exit_mcap"], "demo_trade"
        elif dl and dl.get("exit_px") and supply:
            exit_mc, xmc_src = dl["exit_px"] * supply, "exit_price_x_supply"
    sin = sum(l[8] or 0 for l in lots)
    sback = sum(l[9] or 0 for l in lots)
    fees = sum(l[10] or 0 for l in lots)
    cost = _q(tc, f"SELECT AVG(cost_pct) FROM orders WHERE side='buy' AND cost_pct IS NOT NULL AND position_id IN "
                  f"({q})", ids) if ids else []
    entry = g["entry_ts"]
    follow, score, score_src = None, None, None
    if d0 and d0.get("follow_id"):
        f = _q(lc, "SELECT kind, target, label, exit FROM follows WHERE id=?", (d0["follow_id"],))
        if f:
            follow = {"kind": f[0][0], "target": f[0][1], "label": f[0][2], "exit_mode": _json(f[0][3]).get("mode")}
            follow["_exit"] = _json(f[0][3])
    # 10.11. (Grok MCP audit 1): score_at_entry. league/copy books copies with score NULL, so it was null for every
    # trade; the stored score wins once the entry writes one, then the paper candidate's score, then the followed
    # caller's pick score from the minute calls he made BEFORE the entry (no look-ahead)
    before = _follow_before(mc, follow, entry) if follow else None
    if d0 and d0.get("score") is not None:
        score, score_src = d0["score"], "demo_trade"
    elif lots and (papers.get(lots[0][0]) or {}).get("score") is not None:
        score, score_src = papers[lots[0][0]]["score"], "paper_candidate"
    elif before and before.get("n"):
        score, score_src = before["pick_score"], "caller_pick_score_before_entry"
    if "kidx" not in ctx:   # read once per page of trades
        ctx["kidx"], ctx["kol_ids"] = _kol_index(kc), _kol_ids(kc)
    kidx, ids_k = ctx["kidx"], ctx["kol_ids"]
    callers = []
    for h, ts, mcap0, tid in _q(kc, "SELECT handle, ts, mcap0, tweet_id FROM calls WHERE token=? AND kind='call' "
                                    "AND ts<=? AND ts>=? ORDER BY ts", (tok, entry + 60, entry - 3600)):
        k = _dicts(kc, "SELECT score, stats, followers FROM kols WHERE handle=? COLLATE NOCASE", (h,))
        k = k[0] if k else None
        st = _json(k["stats"]) if k else {}
        fol = _followers(kc, [h], kidx).get(h, (None, None))[0] if not (k and k["followers"]) else k["followers"]
        callers.append({"handle": h, "platform": platform_of(h), "call_ts": _i(ts), "market_cap_at_call": _f(mcap0, 0),
                        "call_power": _f(k["score"], 2) if k else None, "followers": _i(fol),
                        "stats": {x: st.get(x) for x in ("calls", "measured", "hit_rate", "med_max24", "med_r1h", "rug_rate")
                                  if x in st}})
    first = _first_call(kc, mc, hc, tok, entry, d0)
    wallets = []
    for wal, ts, sol in _q(hc, "SELECT wallet, ts, sol FROM chain_trades WHERE mint=? AND side='buy' AND ts BETWEEN ? AND ? "
                               "ORDER BY ts", (tok, entry - 3600, entry + 60))[:50]:
        meta = _wallet_meta(wc, kidx, ids_k, wal)
        wallets.append({"wallet": wal, "buy_ts": _i(ts), "sol": _f(sol, 4), **meta})
    rug = _q(rc, "SELECT checked_at, verdict, score, top10_pct, bundle_pct, sniper_pct FROM rug_reports WHERE mint=? "
                 "AND checked_at<=? ORDER BY checked_at DESC LIMIT 1", (tok, entry + 300))
    path = None
    if follow and follow["kind"] == "kol" and sig_ts:
        c = _q(kc, "SELECT tweet_id FROM calls WHERE token=? AND handle=? COLLATE NOCASE AND ts BETWEEN ? AND ? "
                   "ORDER BY ABS(ts-?) LIMIT 1", (tok, follow["target"], sig_ts - 300, sig_ts + 300, sig_ts))
        if c:
            pr = _q(mc, "SELECT entry, mcap_e, hi15, hi60, lo60, r60, t10, t15, sl_min FROM call_path WHERE tweet_id=? AND token=?",
                    (c[0][0], tok))
            if pr:
                path = dict(zip(("entry_price", "entry_market_cap", "hi15", "hi60", "lo60", "r60", "min_to_10pct",
                                 "min_to_15pct", "min_to_stop"), pr[0]))
    # run-up from the first call to the entry: league trades.runup when the entry stored it, else entry / first mcap
    runup, runup_src = None, None
    if d0 and d0.get("runup") is not None:
        runup, runup_src = d0["runup"], "demo_trade"
    elif first and first["mcap"] and entry_mc:
        runup, runup_src = entry_mc / first["mcap"] - 1, f"entry_mcap/{first['source']}"
    real = kind == "position"
    pnl = sback - sin - fees if closed and real else None
    # 10.11. (plan 1.5): the demo's exit price next to the real one, per lot (trade/executor.exit_reconcile)
    slip = {r[0]: r[1:] for r in _q(tc, f"SELECT id, demo_exit_px, real_exit_px, exit_slip_pct FROM positions WHERE id IN "
                                       f"({q})", ids)} if ids else {}
    slips = [v[2] for v in slip.values() if v[2] is not None]
    fx = (follow or {}).pop("_exit", None) if follow else None
    return {"trade_id": g["id"], "kind": kind, "league_trade_id": lid0, "token": tok,
            "symbol": (lots[0][2] if lots else None) or (d0 or {}).get("symbol"), "status": g["status"],
            "mode": lots[0][5] if lots else "demo",
            "entry_ts": _i(entry), "exit_ts": (_i(max(l[4] or 0 for l in lots)) if lots else _i((d0 or {}).get("closed_ts")))
            if closed else None,
            "block_reason": _block_reason(tc, lots[0][0], lots[0][7]) if kind == "refused" else None,
            "lots": [{"position_id": l[0], "opened_ts": _i(l[3]), "closed_ts": _i(l[4]), "status": l[6], "sol_in": _f(l[8], 4),
                      "sol_back": _f(l[9], 4), "entry_market_cap": _f(emc[l[0]][0], 0),
                      "demo_exit_px": _f((slip.get(l[0]) or (None,))[0], 10),
                      "real_exit_px": _f((slip.get(l[0]) or (None, None))[1], 10),
                      "exit_slip_pct": _f((slip.get(l[0]) or (None, None, None))[2], 2)} for l in lots],
            "exit_slip_pct": _f(sum(slips) / len(slips), 2) if slips else None,
            "entry_market_cap": _f(entry_mc, 0), "entry_market_cap_source": emc_src if entry_mc else None,
            "exit_market_cap": _f(exit_mc, 0), "exit_market_cap_source": xmc_src,
            "sol_in": _f(sin, 4) if lots else None, "sol_back": _f(sback, 4) if lots else None,
            "fees_sol": _f(fees, 5) if lots else None,
            "cost_pct": _f(cost[0][0], 2) if cost and cost[0][0] is not None else None,
            "pnl_sol": _f(pnl, 4), "pnl_pct": _f(100 * pnl / sin, 2) if pnl is not None and sin else None,
            "exit_reason": rule, "exit_rule_source": rule_src, "exit_detail": _exit_detail(note) if closed else None,
            "exit_note": note if closed else None,
            "exit_policy": _exit_policy(fx, dl or d0),
            "demo_trade": _demo_row(d0),
            "signals": {"follow": follow, "signal_ts": _i(sig_ts), "entry_note": entry_note,
                        "score_at_entry": _f(score, 4), "score_source": score_src,
                        "follow_stats_before_entry": before,
                        "callers_last_hour": callers, "wallet_buys_last_hour": wallets,
                        "rug_check": (dict(zip(("checked_ts", "verdict", "score", "top10_pct", "bundle_pct", "sniper_pct"), rug[0]))
                                      if rug else None),
                        "call_path": path,
                        "first_call_ts": _i(first["ts"]) if first else None,
                        "first_call_handle": first["handle"] if first else None,
                        "first_call_market_cap": _f(first["mcap"], 0) if first else None,
                        "first_call_market_cap_source": first["source"] if first else None,
                        "runup_from_first_call": _f(runup, 4), "runup_source": runup_src},
            "account": settings.LEAGUE_USER}


TRADE_STATUSES = ("open", "closed", "blocked", "failed")


def _trades(since_ts=None, status=None, only=None, include_demo_only=False, refused=True):
    since = int(since_ts or 0)
    tc = _ro("trade")
    lc = _ro("league") if include_demo_only else None
    try:
        groups = _groups(tc, since)
        if refused:
            groups += _refused(tc, since)
        if include_demo_only:
            groups += _demo_only(tc, lc, since)
    finally:
        _close(tc, lc)
    if status in TRADE_STATUSES:
        groups = [g for g in groups if g["status"] == status]
    if only is not None:
        groups = [g for g in groups if only(g)]
    groups.sort(key=lambda g: (-(g["entry_ts"] or 0), -(g["id"] or 0)))
    return groups


def _details(groups):
    cons = [_ro(n) for n in ("trade", "league", "kol", "wallets", "hype", "rug", "minute", "paper")]
    ctx = {}
    try:
        return [_detail(g, *cons, ctx) for g in groups]
    finally:
        _close(*cons)


def _sl_default_pct():
    from trade import settings
    tc = _ro("trade")
    try:
        r = _q(tc, "SELECT v FROM settings WHERE k='sl_default'")
        v = int(json.loads(r[0][0])) if r else settings.SL_DEFAULT
    except (ValueError, TypeError):
        v = settings.SL_DEFAULT
    finally:
        _close(tc)
    return -abs(v)


def autopilot_trades(since_ts=None, limit=None, offset=None, status=None, include_demo_only=False):
    limit, offset = _page(limit, offset)
    groups = _trades(since_ts, status, include_demo_only=bool(include_demo_only))
    return _paged(_details(groups[offset:offset + limit]), limit, offset, total=len(groups),
                  account_sl_default_pct=_sl_default_pct(),
                  notes=("one row per trade: the lots of a token bought while it was held (DCA) are one trade; "
                         "trade_id = its first position_id (use it for submit_trade_review); kind position | refused "
                         "(status blocked / failed: the real copy was refused or failed, block_reason says why, "
                         "demo_trade is the demo it mirrors) | demo_only (include_demo_only: a demo trade with no "
                         "position); pnl_sol = sol_back - sol_in - fees for closed trades; exit_reason = the rule that "
                         "fired (tp | sl | time | smart_tp | smart_sl | smart_trail | smart_other | wallet_sold | manual "
                         "| rug), exit_rule_source where it was read; exit_policy = the follow's exit mode and the stop "
                         "that applied (a smart profile's own stop is not account_sl_default_pct); signals = what the "
                         "Autopilot saw at the entry; *_source = where a value came from"))


def unreviewed_trades(limit=None):
    from ui import assistnotes
    limit, _ = _page(limit, 0)
    tc = _ro("trade")
    try:
        try:
            done = {r[0] for r in tc.execute("SELECT DISTINCT position_id FROM assistant_notes WHERE kind='trade_review'")} \
                if tc is not None else set()
        except sqlite3.Error:
            done = set()
    finally:
        _close(tc)
    groups = _trades(status="closed", only=lambda g: not ({l[0] for l in g["lots"]} & done))
    return _paged(_details(groups[:limit]), limit, 0, total=len(groups),
                  notes="closed trades without a trade_review yet, newest first; review with submit_trade_review(trade_id)")


def assistant_notes(status=None, kind=None, limit=None, offset=None):
    from ui import assistnotes
    limit, offset = _page(limit, offset)
    tc = _ro("trade")
    try:
        if tc is None:
            rows, total = [], 0
        else:
            try:
                tc.execute("SELECT 1 FROM assistant_notes LIMIT 1")
                rows, total = assistnotes.notes(_RoCon(tc), status, kind, limit, offset)
                # 10.11. (Jure): an applied note carries when and what it changed (settings applied_log)
                log = {}
                for a in reversed(assistnotes.applied(tc, 200)):
                    log[a.get("note_id")] = a
                for r in rows:
                    a = log.get(r.get("id"))
                    if a:
                        r.update(applied_ts=a.get("ts"), applied_key=a.get("key"), old_value=a.get("old"),
                                 new_value=a.get("new"))
                    else:
                        r.update(applied_ts=None, applied_key=None, old_value=None, new_value=None)
            except sqlite3.Error:
                rows, total = [], 0
    finally:
        _close(tc)
    return _paged(rows, limit, offset, total=total,
                  notes="status: novo (waits), prihvaćeno (owner agreed, NOTHING changed), odbijeno, primijenjeno "
                        "(applied to the bot: applied_ts, applied_key, old_value -> new_value); owner_note = the "
                        "owner's reason")


class _RoCon:
    """A read-only connection for assistnotes.notes (its ensure() would write)."""
    def __init__(self, con):
        self.con = con

    def execute(self, *a):
        sql = a[0].lstrip().upper()
        if sql.startswith(("CREATE", "ALTER")):
            return self.con.execute("SELECT 1")
        return self.con.execute(*a)

    def commit(self):
        pass


# ---------- 7. scoring config ------------------------------------------------------------------------------------

SAFE_SETTINGS = ("size_sol", "max_sol_per_trade", "max_sol_per_day", "max_loss_day", "max_open", "min_sol_reserve",
                 "max_cost_pct", "max_signal_age_s", "tp_default", "sl_default", "on", "use_pump", "auto_pick",
                 "auto_days", "auto_n")


def scoring_config():
    from league import copy
    from trade import executor, settings
    from ui import autopilot, kolsummary
    out = {"ts": int(time.time())}
    try:
        cfg = json.load(open(os.path.join(ROOT, "kol", "config.json")))
        out["caller_score"] = {k: cfg.get(k) for k in ("weights", "hit_x", "rug_x", "prepump_x", "prior_calls",
                                                         "prior_score", "good_score", "watch", "valid", "minute")}
    except (OSError, ValueError):
        out["caller_score"] = None
    out["caller_verdict"] = {"min_hit_1h": kolsummary.VERDICT_H1, "min_down_24h": kolsummary.VERDICT_D24,
                             "min_calls": kolsummary.VERDICT_MIN_N}
    out["autopilot_pick"] = {k: getattr(autopilot, k) for k in ("HIT", "MIN_CALLS", "MIN_CLOSED", "MIN_MINUTE",
                                                                "OLD_MIN_MINUTE", "WILSON_Z", "HOT_HIT10", "HOT_MAX_SL",
                                                                "MAX_OPEN_SHARE", "MAX_RUG", "TOP", "MOON_MIN_LIQ")
                             if hasattr(autopilot, k)}
    out["copy_filters"] = {**copy.CFG, "DEFAULT_SL_players": copy.DEFAULT_SL, "DATA_TP": copy.DATA_TP,
                           "DATA_MAX_LATE_S": copy.DATA_MAX_LATE_S, "DATA_MAX_RUNUP": copy.DATA_MAX_RUNUP}
    try:
        import run_trade
        out["real_money_proof_gate"] = dict(run_trade.PROOF)
    except Exception:  # noqa: BLE001
        out["real_money_proof_gate"] = None
    tcon = _ro("trade")   # read-only: this tool never creates or writes trade.db
    eff, done = {}, []
    try:
        m = settings.merged(executor.load_config(), tcon) if tcon is not None else executor.load_config()
        raw = settings.raw(tcon) if tcon is not None else {}
        if tcon is not None:   # 10.11. (Jure: "da Grok može provjeriti"): what "Primijeni na bota" changed, and now
            from ui import assistnotes
            try:
                eff = assistnotes.effective(tcon)
            except Exception:  # noqa: BLE001 - a missing table or flag: the rest of the config still answers
                eff = {}
            done = assistnotes.applied(tcon)
    except sqlite3.Error:
        m, raw = executor.load_config(), {}
    finally:
        _close(tcon)
    out["applied_suggestions"] = done   # [{ts, note_id, key, old, new}], newest first
    out["effective_values"] = eff       # {key: {value, flag?, flag_mode?}} for every key "Primijeni na bota" can change
    out["effective_values_note"] = ("value = what the bot uses now. A rule behind a flag (flag/flag_mode): live = it "
                                    "acts on both Autopilot accounts; paper = it acts only on the demo account "
                                    "autopilot-paper, the real Autopilot account only logs; shadow = only logged "
                                    "(shadow_decisions); off = nothing. Applying a suggestion never sets a flag to "
                                    "live. Owner-ordered changes are in applied_suggestions with note_id 0.")
    out["autopilot_settings"] = {k: m.get(k, raw.get(k)) for k in SAFE_SETTINGS}
    # 10.11. (Jure): Grok's autotrade switch and its own limits, read-only (only the owner changes them, on the page)
    try:
        from ui import grokauto
        st = raw.get(grokauto.STATE_KEY) or {}
        out["grok_autotrade"] = {"on": bool(st.get("on")), "paused_until": st.get("paused_until"),
                                 "limits": {k: raw.get(k, d) for k, (d, *_r) in grokauto.LIMITS.items()},
                                 "note": "Only the owner switches it on and sets the limits (Autopilot page)."}
    except Exception:  # noqa: BLE001
        out["grok_autotrade"] = None
    # 10.11. (Phase 0): every flag of the profitability plan with its mode, and the backtest verdicts (read-only)
    out["flags"] = {n: {"item": settings.FLAGS[n][0], "mode": settings._flag_value(raw.get(f"flag:{n}"))["mode"],
                        "backtest": raw.get(f"backtest:{n}")} for n in settings.FLAGS}
    try:
        from rugfilter import score as rscore
        out["rug_filter_thresholds"] = dict(getattr(rscore, "T", {}))
    except Exception:  # noqa: BLE001
        out["rug_filter_thresholds"] = None
    try:
        out["hype_weights"] = json.load(open(os.path.join(ROOT, "hype", "weights.json")))
    except (OSError, ValueError):
        out["hype_weights"] = None
    out["notes"] = ("Read-only. Proposals go through submit_caller_weights (owner review); nothing here changes by "
                    "this API.")
    return json.loads(json.dumps(out, default=str))


# ---------- 8. caller weight suggestions -------------------------------------------------------------------------

SUGG_SCHEMA = ("CREATE TABLE IF NOT EXISTS assistant_suggestions (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, "
               "kind TEXT, handle TEXT, platform TEXT, weight REAL, reason TEXT, status TEXT DEFAULT 'pending', "
               "decided_ts INTEGER, source TEXT)")


def submit_caller_weights(weights, source="mcp", kid="local"):
    """Suggested per-caller weights (0-2): one assistant_notes suggestion each (proposed_change {caller, platform,
    weight}), status 'novo'. Changes no live scoring; the owner applies or rejects each on the Autopilot page."""
    from trade import settings
    from ui import assistnotes
    if not isinstance(weights, list) or not weights:
        return {"error": "weights must be a non-empty list of {handle, platform, weight, reason}"}
    if len(weights) > 50:
        return {"error": "at most 50 suggestions per call"}
    clean = []
    for i, w in enumerate(weights):
        if not isinstance(w, dict):
            return {"error": f"item {i} is not an object"}
        plat = str(w.get("platform") or "x").lower()
        if plat not in ("x", "telegram"):
            return {"error": f"item {i}: platform must be x or telegram"}
        h = _handle(w.get("handle"), plat)
        try:
            wt = float(w.get("weight"))
        except (TypeError, ValueError):
            return {"error": f"item {i}: weight must be a number 0-2"}
        if not h or not 0 <= wt <= 2:
            return {"error": f"item {i}: handle required and weight must be between 0 and 2"}
        clean.append((h, plat, round(wt, 3), str(w.get("reason") or "")[:assistnotes.TEXT_MAX]))
    con = settings.connect()
    ids = []
    try:
        for h, plat, wt, why in clean:
            out = assistnotes.submit_suggestion(con, kid, f"Težina callera {h}: {wt:g}", why or "prijedlog težine",
                                                proposed_change={"caller": h, "platform": plat, "weight": wt})
            ids.append(out["id"])
    except ValueError as e:
        return {"error": str(e), "stored": len(ids), "ids": ids}
    finally:
        con.close()
    return {"ts": int(time.time()), "stored": len(ids), "ids": ids, "status": "novo",
            "message": "Stored for the owner's review on the MemeSonar Autopilot page; live scoring is unchanged."}


def suggestions(tcon, status="pending", limit=50):
    try:
        tcon.execute(SUGG_SCHEMA)
        return [{"id": i, "ts": ts, "handle": h, "platform": p, "weight": wt, "reason": r, "status": st}
                for i, ts, h, p, wt, r, st in tcon.execute(
                    "SELECT id, ts, handle, platform, weight, reason, status FROM assistant_suggestions WHERE status=? "
                    "ORDER BY id DESC LIMIT ?", (status, limit))]
    except sqlite3.Error:
        return []


def decide_suggestion(tcon, sid, status):
    tcon.execute(SUGG_SCHEMA)
    n = tcon.execute("UPDATE assistant_suggestions SET status=?, decided_ts=? WHERE id=? AND status='pending'",
                     (status, int(time.time()), int(sid))).rowcount
    tcon.commit()
    return n
