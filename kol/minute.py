"""Minutna provjera poziva (9.11., Jure): what a caller's token did in the minutes right after the call, from
GeckoTerminal 1-minute candles, so the question "can we take +5/10/15/20/30 % after this account or this crew calls"
has a measured answer instead of the 24-hour wick (calls.max24) that the leaderboard used.

Time: every call carries unix seconds in UTC (X createdAt with its +0000 offset, Telegram <time datetime> with its
offset, Telethon's aware msg.date, block time for wallet swaps), and GeckoTerminal candles are unix seconds too,
so a call at 10:32:20 UTC lands in the 10:32 candle with no time-zone conversion anywhere.

Entry = the CLOSE of the minute the call was posted in (a copy placed within the same minute pays about that;
`lag_s` says how many seconds after the post that close is). Without a trade in that minute, the open of the first
candle within 5 minutes after it; none = the call is recorded without an outcome (bad 'svijeca').
Then over the next 60 minutes, minute by minute: the highest capped high at 15/30/60 min (a one-print wick counts
up to wick_x times the candle body, as in kol/measure.py), the lowest low, the close at 60 min, the first minute
each target (+5..+30 %) was reached and the first minute the stop (-20 %) was hit. A target counts as a clean hit
only when it came BEFORE the stop. Calls with the token under $30k market cap at the entry are kept but not
counted (CLAUDE.md: tokens under 30k are not analysed).

Priority: tokens called by two or more different accounts first (crews), newest first; bot accounts and wallet
pseudo-calls never. One request per token covers every call of that token within 16 hours.

Output for the pages: handle_stats (per account), crew_stats (per group of callers, measured from the FIRST call
of the group so a late echo cannot improve it), hot() = the small set worth reading every 1-2 s (kv hot_list),
which tg/poll.py and kol/xhook.py read.
"""
import json
import math
import statistics
import time

from event_calendar import http

MIN = 60
TPS = (5, 10, 15, 20, 30)
SL = -0.20
HORIZON_MIN = 60
MIN_MCAP = 30000
KEEP_DAYS = 30
SPAN_S = 16 * 3600   # 1000 one-minute candles per request

DEFAULT = {"budget_s": 150, "per_run": 60, "days": 14, "min_age_min": 70, "hot_min_n": 5, "hot_min_hit": 0.5,
           "hot_tp": 10, "hot_max_sl": 0.3, "hot_days": 14, "wick_x": 3.0}

SCHEMA = """CREATE TABLE IF NOT EXISTS call_path (
    tweet_id TEXT, token TEXT, handle TEXT, ts INTEGER, entry REAL, lag_s INTEGER, mcap_e REAL,
    hi15 REAL, hi30 REAL, hi60 REAL, lo60 REAL, r60 REAL,
    t5 INTEGER, t10 INTEGER, t15 INTEGER, t20 INTEGER, t30 INTEGER, sl_min INTEGER,
    first_caller INTEGER, bad TEXT, measured_ts INTEGER, PRIMARY KEY (tweet_id, token));
CREATE INDEX IF NOT EXISTS call_path_handle ON call_path (handle, ts);
CREATE INDEX IF NOT EXISTS call_path_token ON call_path (token, ts)"""


def config(cfg):
    return {**DEFAULT, **((cfg or {}).get("minute") or {})}


def ensure(con):
    con.executescript(SCHEMA)


def minutes(pool, start, end):
    """[(ts, o, h, l, c, v)] 1-minute candles covering start..end, oldest first (GeckoTerminal, free)."""
    from kol import measure
    limit = max(2, min(1000, math.ceil((end - start) / MIN) + 2))
    measure._GT.wait()
    d = http.get_json(f"{measure.GECKO}/pools/{pool}/ohlcv/minute",
                      {"aggregate": 1, "before_timestamp": int(end) + MIN, "limit": limit, "currency": "usd"},
                      ttl=3600, headers={"Accept": "application/json"}, retries=1)
    rows = ((d or {}).get("data") or {}).get("attributes", {}).get("ohlcv_list") or []
    return sorted((int(r[0]), *map(float, r[1:6])) for r in rows)


def path(candles, ts, horizon_min=HORIZON_MIN, wick=3.0):
    """Outcome of one call from 1-minute candles, or None when no candle starts within 5 minutes of the call."""
    m0 = ts - ts % MIN
    by = {c[0]: c for c in candles}
    cur = by.get(m0)
    if cur:
        entry, lag = cur[4], m0 + MIN - ts
    else:
        nxt = next((c for c in candles if m0 < c[0] <= m0 + 5 * MIN), None)
        if not nxt:
            return None
        entry, lag = nxt[1], nxt[0] - ts
    if not entry or entry <= 0:
        return None
    o = {"entry": entry, "lag_s": int(lag), "hi15": None, "hi30": None, "hi60": None, "lo60": None, "r60": None,
         "sl_min": None, **{f"t{tp}": None for tp in TPS}}
    hi = {15: None, 30: None, 60: None}
    lo = None
    last_close = None
    for c in candles:
        if c[0] <= m0 or c[0] > m0 + horizon_min * MIN:
            continue
        k = (c[0] - m0) // MIN                       # minutes after the entry minute
        capped = min(c[2], max(c[1], c[4]) * wick)   # a wick counts up to wick× the body
        for w in hi:
            if k <= w:
                hi[w] = capped if hi[w] is None else max(hi[w], capped)
        lo = c[3] if lo is None else min(lo, c[3])
        last_close = c[4]
        for tp in TPS:
            if o[f"t{tp}"] is None and capped >= entry * (1 + tp / 100):
                o[f"t{tp}"] = int(k)
        if o["sl_min"] is None and c[3] <= entry * (1 + SL):
            o["sl_min"] = int(k)
    for w in hi:
        o[f"hi{w}"] = (hi[w] / entry - 1) if hi[w] is not None else None
    o["lo60"] = (lo / entry - 1) if lo is not None else None
    o["r60"] = (last_close / entry - 1) if last_close is not None else None
    return o


def clean_hit(row, tp):
    """Target reached before the stop (row: sqlite row or dict with t<tp> and sl_min)."""
    t, sl = row[f"t{tp}"], row["sl_min"]
    return t is not None and (sl is None or t < sl)


def due(con, c, now):
    """{token: [(tweet_id, handle, ts)]} of real calls without a minute path, crews first, newest first; at most
    c['per_run'] tokens, and per token only the calls within SPAN_S of its newest one (the rest next time)."""
    rows = con.execute("""
        SELECT c.tweet_id, c.token, c.handle, c.ts,
               (SELECT COUNT(DISTINCT handle) FROM calls x WHERE x.token = c.token AND x.kind = 'call'
                  AND x.handle NOT LIKE 'w:%') AS n_callers
          FROM calls c LEFT JOIN call_path p ON p.tweet_id = c.tweet_id AND p.token = c.token
          LEFT JOIN kols k ON k.handle = c.handle
          JOIN tokens t ON t.token = c.token AND t.pair IS NOT NULL
         WHERE p.tweet_id IS NULL AND c.kind = 'call' AND c.handle NOT LIKE 'w:%' AND COALESCE(k.bot, 0) = 0
           AND c.bad IS NULL AND (c.mcap0 IS NULL OR c.mcap0 >= ?) AND c.ts BETWEEN ? AND ?
         ORDER BY (n_callers >= 2) DESC, c.ts DESC""",
                       (MIN_MCAP, now - c["days"] * 86400, now - c["min_age_min"] * 60)).fetchall()
    out = {}
    for tid, tok, h, ts, _n in rows:
        if tok not in out and len(out) >= c["per_run"]:
            continue
        out.setdefault(tok, []).append((tid, h, ts))
    for tok, calls in out.items():
        newest = max(ts for _, _, ts in calls)
        out[tok] = [x for x in calls if newest - x[2] <= SPAN_S - 2 * 3600]
    return out


def _supply(con, token):
    r = con.execute("SELECT supply FROM tokens WHERE token = ?", (token,)).fetchone()
    return r[0] if r else None


def run(con, cfg, now=None, fetch=None, log=print):
    """Measure due calls within the budget. Returns (tokens fetched, calls stored)."""
    from kol import measure
    ensure(con)
    c = config(cfg)
    now = now or int(time.time())
    fetch = fetch or minutes
    todo = due(con, c, now)
    if not todo:
        return 0, 0
    if fetch is minutes:
        http.reserve(measure.GECKO, c["budget_s"])
    stop_at = time.monotonic() + c["budget_s"]
    n_tok = n_calls = 0
    try:
        for tok, calls in todo.items():
            if time.monotonic() > stop_at or (fetch is minutes and http.cooling(measure.GECKO) > 30):
                break
            pair = con.execute("SELECT pair FROM tokens WHERE token = ?", (tok,)).fetchone()[0]
            first = min(ts for _, _, ts in calls)
            start, end = first - 10 * MIN, min(now, max(ts for _, _, ts in calls) + (HORIZON_MIN + 5) * MIN)
            try:
                candles = fetch(pair, start, end)
            except Exception as e:  # noqa: BLE001
                log(f"  minute {tok[:8]}: {type(e).__name__}: {e}")
                continue
            if candles is None:    # another job holds the GeckoTerminal budget (http.reserve): next round
                break
            n_tok += 1
            supply = _supply(con, tok)
            first_ts = con.execute("SELECT MIN(ts) FROM calls WHERE token = ? AND kind = 'call' AND handle NOT LIKE 'w:%'",
                                   (tok,)).fetchone()[0]
            for tid, h, ts in calls:
                o = path(candles, ts, wick=c["wick_x"])
                if not o:
                    con.execute("INSERT OR REPLACE INTO call_path (tweet_id, token, handle, ts, bad, measured_ts) "
                                "VALUES (?,?,?,?,'svijeca',?)", (tid, tok, h, ts, now))
                    continue
                mcap = o["entry"] * supply if supply else None
                bad = "mcap" if mcap is not None and mcap < MIN_MCAP else None
                con.execute("""INSERT OR REPLACE INTO call_path VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (tid, tok, h, ts, o["entry"], o["lag_s"], mcap, o["hi15"], o["hi30"], o["hi60"], o["lo60"],
                             o["r60"], o["t5"], o["t10"], o["t15"], o["t20"], o["t30"], o["sl_min"],
                             int(first_ts == ts), bad, now))
                n_calls += 1
            con.commit()
    finally:
        if fetch is minutes:
            http.release(measure.GECKO)
    con.execute("DELETE FROM call_path WHERE ts < ?", (now - KEEP_DAYS * 86400,))
    waiting = con.execute("""SELECT COUNT(*) FROM calls c LEFT JOIN call_path p ON p.tweet_id = c.tweet_id AND p.token = c.token
        LEFT JOIN kols k ON k.handle = c.handle WHERE p.tweet_id IS NULL AND c.kind = 'call' AND c.handle NOT LIKE 'w:%'
        AND COALESCE(k.bot, 0) = 0 AND c.bad IS NULL AND c.ts BETWEEN ? AND ?""",
                          (now - c["days"] * 86400, now - c["min_age_min"] * 60)).fetchone()[0]
    con.execute("INSERT OR REPLACE INTO kv VALUES ('minute_stats', ?)",
                (json.dumps({"ts": now, "tokens": n_tok, "calls": n_calls, "waiting": waiting}),))
    con.commit()
    return n_tok, n_calls


def _agg(rows):
    """rows: dicts with t5..t30, sl_min, r60, hi15 -> stats dict (n, hit<tp>, sl, med_t10, med_r60, med_hi15)."""
    n = len(rows)
    if not n:
        return None
    out = {"n": n}
    for tp in TPS:
        out[f"hit{tp}"] = sum(1 for r in rows if clean_hit(r, tp)) / n
    out["sl"] = sum(1 for r in rows if r["sl_min"] is not None and not clean_hit(r, 10)) / n
    t10 = [r["t10"] for r in rows if clean_hit(r, 10)]
    out["med_t10"] = statistics.median(t10) if t10 else None
    r60 = [r["r60"] for r in rows if r["r60"] is not None]
    out["med_r60"] = statistics.median(r60) if r60 else None
    hi = [r["hi15"] for r in rows if r["hi15"] is not None]
    out["med_hi15"] = statistics.median(hi) if hi else None
    return out


def _rows(con, where, args):
    cols = ("tweet_id", "token", "handle", "ts", "entry", "lag_s", "t5", "t10", "t15", "t20", "t30", "sl_min", "r60", "hi15",
            "first_caller")
    return [dict(zip(cols, r)) for r in con.execute(
        f"SELECT {', '.join(cols)} FROM call_path WHERE entry IS NOT NULL AND bad IS NULL AND {where}", args)]


def handle_stats(con, days=14, now=None, min_n=1):
    """[(handle, stats)] over the account's measured calls of the last `days`, most calls first."""
    now = now or int(time.time())
    by = {}
    for r in _rows(con, "ts >= ?", (now - days * 86400,)):
        by.setdefault(r["handle"], []).append(r)
    out = [(h, _agg(rs)) for h, rs in by.items() if len(rs) >= min_n]
    out.sort(key=lambda x: (-x[1]["n"], -x[1]["hit10"]))
    return out


def crew_stats(con, days=14, now=None, min_n=2, max_size=4):
    """Groups of accounts that called the same token within the group window (kol.db groups), measured from the
    FIRST call of each group: {'crews': [(handles tuple, stats, n_tokens)], 'pairs': [((a, b), stats)]}. Groups of
    more than max_size callers are paid campaigns, not a crew: skipped."""
    now = now or int(time.time())
    first = {(r["token"], r["ts"]): r for r in _rows(con, "ts >= ?", (now - days * 86400,))}
    crews, pairs = {}, {}
    for tok, start, handles in con.execute("SELECT token, start_ts, handles FROM groups WHERE start_ts >= ?",
                                           (now - days * 86400,)):
        hs = sorted(set(json.loads(handles or "[]")))
        if len(hs) < 2 or len(hs) > max_size:
            continue
        r = first.get((tok, start))
        if not r:
            continue
        crews.setdefault(tuple(hs), []).append(r)
        for i in range(len(hs)):
            for j in range(i + 1, len(hs)):
                pairs.setdefault((hs[i], hs[j]), []).append(r)
    out_c = [(hs, _agg(rs), len({r["token"] for r in rs})) for hs, rs in crews.items() if len(rs) >= min_n]
    out_c.sort(key=lambda x: (-x[1]["n"], -x[1]["hit10"]))
    out_p = [(ab, _agg(rs)) for ab, rs in pairs.items() if len(rs) >= min_n]
    out_p.sort(key=lambda x: (-x[1]["n"], -x[1]["hit10"]))
    return {"crews": out_c, "pairs": out_p}


def coverage(con, c=None, now=None):
    """How much of the recent call history has a minute path: {measured, no_candle, small, waiting, last}."""
    c = c or DEFAULT
    now = now or int(time.time())
    try:
        m, nc, sm = con.execute("""SELECT SUM(entry IS NOT NULL AND bad IS NULL), SUM(bad = 'svijeca'), SUM(bad = 'mcap')
                                   FROM call_path WHERE ts >= ?""", (now - c["days"] * 86400,)).fetchone()
        st = con.execute("SELECT value FROM kv WHERE key = 'minute_stats'").fetchone()
    except Exception:  # noqa: BLE001
        return {"measured": 0, "no_candle": 0, "small": 0, "waiting": None, "last": None}
    st = json.loads(st[0]) if st else {}
    return {"measured": m or 0, "no_candle": nc or 0, "small": sm or 0, "waiting": st.get("waiting"), "last": st.get("ts")}


def hot(con, cfg, now=None, wallet_db=None):
    """The small set worth reading every 1-2 s: accounts whose measured calls of the last hot_days reached +hot_tp %
    before the stop at least hot_min_hit of the time, on hot_min_n+ calls, with the stop first on at most hot_max_sl;
    plus the proven-twice copyable wallets (wallets/dokazani.py). Saved as kv hot_list. Anyone can enter or leave
    the list at the next scoring, from the numbers alone."""
    c = config(cfg)
    now = now or int(time.time())
    x, tg = [], []
    for h, s in handle_stats(con, c["hot_days"], now, c["hot_min_n"]):
        if s[f"hit{c['hot_tp']}"] >= c["hot_min_hit"] and s["sl"] <= c["hot_max_sl"]:
            (tg if h.startswith("tg:") else x).append(h)
    wallets = []
    try:
        from wallets import dokazani
        wallets = sorted(dokazani.current(wallet_db))
    except Exception:  # noqa: BLE001
        pass
    out = {"ts": now, "x": x, "tg": [h[3:] for h in tg], "wallets": wallets}
    con.execute("INSERT OR REPLACE INTO kv VALUES ('hot_list', ?)", (json.dumps(out),))
    con.commit()
    return out


def hot_list(path=None):
    """The saved hot list ({ts, x, tg, wallets}); empty lists when kol.db has none yet."""
    from kol import store
    empty = {"ts": 0, "x": [], "tg": [], "wallets": []}
    con = store.ro(path)
    if con is None:
        return empty
    try:
        r = con.execute("SELECT value FROM kv WHERE key = 'hot_list'").fetchone()
        return {**empty, **json.loads(r[0])} if r else empty
    except Exception:  # noqa: BLE001
        return empty
    finally:
        con.close()
