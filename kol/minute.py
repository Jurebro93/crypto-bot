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

Own database minute.db (next to kol.db): the only writer is `run_kol.py minute-loop` (start.sh), which fills the
history as fast as the free GeckoTerminal budget allows and then keeps up with new calls; the KOL round and the
pages only read it. kol.db (calls, tokens, kols, groups) is read-only here. 10.11.: after each pass the loop also
measures the Autopilot's skipped buys the same way (kol/preskoceni.py, table skip_path), within a small budget.

Priority: tokens called by two or more different accounts first (crews), newest first. One request per token
covers every call of that token within 16 hours.

For the pages: handle_stats (per account), crew_stats (per group of callers, measured from the FIRST call of the
group so a late echo cannot improve it), crew_detail (members, followers, who calls first, every shared token with
its path and rug flag), hot() = the small set worth reading every 1-2 s (kv hot_list), read by tg/poll.py and
kol/xhook.py.
"""
import json
import math
import os
import sqlite3
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
RUG_LO = -0.80       # the low within the hour at or under this: the call rugged on the copier
# 9.11. (Jure: "TP 20 / SL -40? alat neka sam odluči"): the first minute each level above and below the entry was
# touched, so kol/tpsl.py can answer "target before stop?" for ANY take profit / stop pair, not only +5..+30 / -20
UPS = (5, 10, 15, 20, 30, 40, 50, 75, 100, 150, 200)
DOWNS = (10, 15, 20, 25, 30, 40, 50, 60, 70)
# 10.11. (plan 1.3: "SL −60 % se u podacima ne može izmjeriti"): DOWNS 60/70 and UPS 150/200 added. Rows measured
# with the old levels (LV_VERSION missing in call_lv.lv) do not know them; kol/tpsl.py takes them against us and
# relevel_due() measures them again from the same free candles.
LV_VERSION = 2
OLD_UPS = (5, 10, 15, 20, 30, 40, 50, 75, 100)
OLD_DOWNS = (10, 15, 20, 25, 30, 40, 50)

DEFAULT = {"budget_s": 150, "per_run": 60, "days": 30, "min_age_min": 70, "hot_min_n": 5, "hot_min_hit": 0.5,
           "hot_tp": 10, "hot_max_sl": 0.3, "hot_days": 14, "wick_x": 3.0, "loop_budget_s": 540, "loop_sleep_s": 20,
           "idle_sleep_s": 120,
           # calls measured before the levels were stored are measured again (no new source, the same free candles),
           # but only when fewer than this many tokens with NEW calls are waiting, at most this many tokens a pass
           "relevel_per_run": 40,
           # 10.11. (plan 4.4): tokens a pass whose candles after the call (CANDLE_MIN) are still missing
           "candles_per_run": 10,
           # 10.11. (CLAUDE.md: heavy jobs 01-06 CET): the second measurement of rows that only miss the new wide
           # levels and the candle top-ups run in these Zagreb hours [from, to), at most night_requests a night (the
           # paid CoinGecko day starts at 00 UTC: the night must not eat it)
           "extra_hours": [1, 6], "night_requests": 600}

SCHEMA = """CREATE TABLE IF NOT EXISTS call_path (
    tweet_id TEXT, token TEXT, handle TEXT, ts INTEGER, entry REAL, lag_s INTEGER, mcap_e REAL,
    hi15 REAL, hi30 REAL, hi60 REAL, lo60 REAL, r60 REAL,
    t5 INTEGER, t10 INTEGER, t15 INTEGER, t20 INTEGER, t30 INTEGER, sl_min INTEGER,
    first_caller INTEGER, bad TEXT, measured_ts INTEGER, PRIMARY KEY (tweet_id, token));
CREATE INDEX IF NOT EXISTS call_path_handle ON call_path (handle, ts);
CREATE INDEX IF NOT EXISTS call_path_token ON call_path (token, ts);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS call_lv (tweet_id TEXT, token TEXT, ts INTEGER, lv TEXT, PRIMARY KEY (tweet_id, token));
CREATE INDEX IF NOT EXISTS call_lv_ts ON call_lv (ts);
CREATE TABLE IF NOT EXISTS call_candles (token TEXT PRIMARY KEY, first_ts INTEGER, last_ts INTEGER, n INTEGER,
    data BLOB, full INTEGER DEFAULT 0, updated INTEGER)"""
LV_FAILED = "x"   # call_lv.lv of a call whose second measurement found no candle: the old row stays, not asked again
# 10.11. (plan 4.4, "call_candles"): the 1-minute candles themselves, CANDLE_MIN minutes after every call, for the
# backtest of exits that need the whole path (a ladder, a trailing stop) and not only the first touch of a level.
# One row per TOKEN (calls of one token share the candles), zlib-compressed JSON [[ts, o, h, l, c, v], ...] with 6
# significant digits: about 4 KB per call instead of ~250 rows. Filled from the request the measurement makes anyway;
# a call measured at ~70 min gets the rest later by candles_due() (one more request per token, only when the
# queue of new calls is short; full=1 then, also when the token stopped trading).
CANDLE_MIN = 240
CANDLE_LIMIT = 998   # minutes one request may span (GeckoTerminal: 1000 candles)


def db_path():
    """minute.db on the persistent disk (DATA_DIR, Render /var/data): 9.11. 17:43 the first version put it next to
    kol.db's path in the repo folder, which start.sh symlinks only for the known names, so a deploy wiped 1,265
    measured calls. start.sh now symlinks minute.db too; this is the belt to that suspender."""
    from kol import store
    if os.environ.get("MINUTE_DB"):
        return os.environ["MINUTE_DB"]
    data = os.environ.get("DATA_DIR")
    if data and os.path.isdir(data):
        return os.path.join(data, "minute.db")
    return os.path.join(os.path.dirname(os.path.abspath(store.DB)), "minute.db")


def connect(path=None):
    con = sqlite3.connect(path or db_path(), timeout=60)
    con.executescript(SCHEMA)
    con.commit()
    return con


def ro(path=None):
    path = path or db_path()
    if not os.path.exists(path) or not os.path.getsize(path):
        return None
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)


def config(cfg):
    return {**DEFAULT, **((cfg or {}).get("minute") or {})}


def ensure(con):
    """Kept for callers that pass their own connection (tests)."""
    con.executescript(SCHEMA)


def minutes(pool, start, end):
    """[(ts, o, h, l, c, v)] 1-minute candles covering start..end, oldest first (GeckoTerminal, free)."""
    from kol import measure
    limit = max(2, min(1000, math.ceil((end - start) / MIN) + 2))
    measure._GT.wait()
    d = http.get_json(f"{measure.GECKO}/pools/{pool}/ohlcv/minute",
                      {"aggregate": 1, "before_timestamp": int(end) + MIN, "limit": limit, "currency": "usd"},
                      ttl=3600, headers={"Accept": "application/json"}, retries=0)
    if d is None:
        # 10.11. (review): get_json answers None only when ANOTHER job holds GeckoTerminal (http.reserve). This used
        # to become [] here, run() took it for "no candle" and wrote the call off for good (bad 'svijeca'). None
        # makes run() stop the pass and try again next round.
        return None
    rows = (d.get("data") or {}).get("attributes", {}).get("ohlcv_list") or []
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
    up, dn = {}, {}   # level % -> first minute touched (UPS on the capped high, DOWNS on the low)
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
        for u in UPS:
            if u not in up and capped >= entry * (1 + u / 100):
                up[u] = int(k)
        for d in DOWNS:
            if d not in dn and c[3] <= entry * (1 - d / 100):
                dn[d] = int(k)
    o["lv"] = {"u": {str(u): m for u, m in up.items()}, "d": {str(d): m for d, m in dn.items()}, "v": LV_VERSION}
    for w in hi:
        o[f"hi{w}"] = (hi[w] / entry - 1) if hi[w] is not None else None
    o["lo60"] = (lo / entry - 1) if lo is not None else None
    o["r60"] = (last_close / entry - 1) if last_close is not None else None
    return o


def clean_hit(row, tp):
    """Target reached before the stop (row: sqlite row or dict with t<tp> and sl_min)."""
    t, sl = row[f"t{tp}"], row["sl_min"]
    return t is not None and (sl is None or t < sl)


def _pack(rows):
    import zlib
    txt = json.dumps([[int(r[0])] + [float(f"{x:.6g}") for x in r[1:6]] for r in rows], separators=(",", ":"))
    return zlib.compress(txt.encode(), 6)


def _unpack(blob):
    import zlib
    if not blob:
        return []
    return [tuple(r) for r in json.loads(zlib.decompress(blob).decode())]


def keep_candles(mcon, tok, candles, calls, end, now):
    """Merge the candles of one fetch into call_candles: only [first call - 10 min, last call + CANDLE_MIN], the
    rest of the 16-hour request is not kept. full = the stored candles reach CANDLE_MIN after the newest call."""
    if not candles or not calls:
        return 0
    lo = min(ts for _, _, ts in calls) - 10 * MIN
    hi = max(ts for _, _, ts in calls) + CANDLE_MIN * MIN
    keep = {c[0]: c for c in candles if lo <= c[0] <= hi}
    old = mcon.execute("SELECT data, first_ts FROM call_candles WHERE token = ?", (tok,)).fetchone()
    if old:
        for c in _unpack(old[0]):
            keep.setdefault(c[0], c)
    if not keep:
        return 0
    rows = [keep[k] for k in sorted(keep)]
    full = int(end >= hi)
    mcon.execute("INSERT OR REPLACE INTO call_candles VALUES (?,?,?,?,?,?,?)",
                 (tok, rows[0][0], rows[-1][0], len(rows), _pack(rows), full, int(now)))
    return len(rows)


def candles_for(mcon, tok, start, end):
    """[(ts, o, h, l, c, v)] stored for one token between start and end (unix s), oldest first."""
    r = mcon.execute("SELECT data FROM call_candles WHERE token = ?", (tok,)).fetchone()
    return [c for c in _unpack(r[0]) if start <= c[0] <= end] if r else []


def call_candles(mcon, tok, ts, minutes=CANDLE_MIN):
    """{k: (o, h, l, c, v)}: the candles k minutes after the call's minute (k = 0 is the call's own minute)."""
    m0 = ts - ts % MIN
    return {(c[0] - m0) // MIN: c[1:] for c in candles_for(mcon, tok, m0, m0 + minutes * MIN)}


def candles_due(mcon, c, now, skip=(), cap=10):
    """{token: [(tweet_id, handle, ts)]}: measured calls at least CANDLE_MIN + 5 minutes old whose token's stored
    candles do not reach CANDLE_MIN after them yet (not full), newest first, at most cap tokens."""
    if cap <= 0:
        return {}
    skip = set(skip) | {t for t, u in _retry(mcon).items() if u > now}
    out = {}
    for tid, tok, h, ts in mcon.execute(
            "SELECT p.tweet_id, p.token, p.handle, p.ts FROM call_path p LEFT JOIN call_candles k ON k.token = p.token "
            "WHERE p.entry IS NOT NULL AND p.bad IS NULL AND p.ts BETWEEN ? AND ? AND COALESCE(k.full, 0) = 0 "
            "ORDER BY p.ts DESC", (now - c["days"] * 86400, now - (CANDLE_MIN + 5) * MIN)):
        if tok in skip:
            continue
        if tok not in out and len(out) >= cap:
            continue
        out.setdefault(tok, []).append((tid, h, ts))
    for tok, calls in out.items():
        newest = max(ts for _, _, ts in calls)
        out[tok] = [x for x in calls if newest - x[2] <= SPAN_S - 2 * 3600 - CANDLE_MIN * MIN]
    return out


def _fetch_end(calls, start, now):
    """End of the one request for these calls: the measured hour as before, and up to CANDLE_MIN after the newest
    call as far as one request (CANDLE_LIMIT minutes from `start`) reaches, never past now."""
    last = max(ts for _, _, ts in calls)
    need = last + (HORIZON_MIN + 5) * MIN
    want = min(last + (CANDLE_MIN + 5) * MIN, start + CANDLE_LIMIT * MIN)
    return min(now, max(need, want))


def _done(mcon):
    return {(r[0], r[1]) for r in mcon.execute("SELECT tweet_id, token FROM call_path")}


RETRY_S = 3600   # 9.11. (audit P24): a token whose candles failed (403, timeout) waits this long before the next try
RELEVEL_RETRY_S = 86400   # a second measurement that came back empty: once a day is enough


def _retry(mcon):
    """{token: not before ts} from kv minute_retry."""
    try:
        r = mcon.execute("SELECT value FROM kv WHERE key = 'minute_retry'").fetchone()
        return json.loads(r[0]) if r else {}
    except Exception:  # noqa: BLE001
        return {}


def _set_retry(mcon, token, until, now):
    d = {t: u for t, u in _retry(mcon).items() if u > now}
    d[token] = int(until)
    mcon.execute("INSERT OR REPLACE INTO kv VALUES ('minute_retry', ?)", (json.dumps(d),))


def candidates(kcon, c, now):
    """[(tweet_id, token, handle, ts, n_callers)] of real calls in the window (kol.db), crews first, newest first."""
    return kcon.execute("""
        SELECT c.tweet_id, c.token, c.handle, c.ts,
               (SELECT COUNT(DISTINCT handle) FROM calls x WHERE x.token = c.token AND x.kind = 'call'
                  AND x.handle NOT LIKE 'w:%') AS n_callers
          FROM calls c LEFT JOIN kols k ON k.handle = c.handle
          JOIN tokens t ON t.token = c.token AND t.pair IS NOT NULL
         WHERE c.kind = 'call' AND c.handle NOT LIKE 'w:%' AND COALESCE(k.bot, 0) = 0
           AND c.bad IS NULL AND (c.mcap0 IS NULL OR c.mcap0 >= ?) AND c.ts BETWEEN ? AND ?
         ORDER BY (n_callers >= 2) DESC, c.ts DESC""",
                        (MIN_MCAP, now - c["days"] * 86400, now - c["min_age_min"] * 60)).fetchall()


def due(kcon, mcon, c, now, per_run=None):
    """{token: [(tweet_id, handle, ts)]} without a minute path yet; at most per_run tokens, and per token only the
    calls within SPAN_S of its newest one (the rest next time)."""
    done = _done(mcon)
    wait = {t for t, u in _retry(mcon).items() if u > now}   # 9.11. (audit P24): failed fetch: not every pass
    out = {}
    cap = per_run or c["per_run"]
    for tid, tok, h, ts, _n in candidates(kcon, c, now):
        if (tid, tok) in done or tok in wait:
            continue
        if tok not in out and len(out) >= cap:
            continue
        out.setdefault(tok, []).append((tid, h, ts))
    for tok, calls in out.items():
        newest = max(ts for _, _, ts in calls)
        out[tok] = [x for x in calls if newest - x[2] <= SPAN_S - 2 * 3600]
    return out


def _give_up_lv(mcon, tok, rows):
    """A second measurement that cannot be done (pool gone, no candle any more): a call without levels gets
    LV_FAILED, a call that has the OLD levels keeps them with "stuck" so it is not asked for again (10.11.: they
    used to be replaced by LV_FAILED, which would throw away the levels it had)."""
    for tid, _h, ts in rows:
        old = mcon.execute("SELECT lv FROM call_lv WHERE tweet_id = ? AND token = ?", (tid, tok)).fetchone()
        lv = LV_FAILED
        if old and old[0] and old[0] != LV_FAILED:
            try:
                d = json.loads(old[0])
                d["stuck"] = LV_VERSION
                lv = json.dumps(d, separators=(",", ":"))
            except ValueError:
                pass
        mcon.execute("INSERT OR REPLACE INTO call_lv VALUES (?,?,?,?)", (tid, tok, ts, lv))


def _extra_window(c, now):
    """True inside extra_hours (Europe/Zagreb)."""
    import datetime as _dt
    import zoneinfo
    lo, hi = (c.get("extra_hours") or [1, 6])[:2]
    h = _dt.datetime.fromtimestamp(now, zoneinfo.ZoneInfo("Europe/Zagreb")).hour
    return lo <= h < hi


def _night_key(now):
    import datetime as _dt
    import zoneinfo
    return "minute_night:" + _dt.datetime.fromtimestamp(now, zoneinfo.ZoneInfo("Europe/Zagreb")).strftime("%Y-%m-%d")


def _night_used(mcon, now):
    r = mcon.execute("SELECT value FROM kv WHERE key = ?", (_night_key(now),)).fetchone()
    return int(r[0]) if r else 0


def _night_spend(mcon, now, n=1):
    mcon.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)", (_night_key(now), str(_night_used(mcon, now) + n)))


def relevel_due(mcon, c, now, skip=(), cap=None, upgrade=True):
    """{token: [(tweet_id, handle, ts)]} of calls measured before call_lv existed (a path, no levels), newest first,
    at most `cap` tokens and per token only the calls within the span of its newest one. They are measured again
    with the same candles so every stop level gets its exact minute; kol/tpsl.py is cautious with them until then."""
    cap = c["relevel_per_run"] if cap is None else cap
    if cap <= 0:
        return {}
    wait = {t for t, u in _retry(mcon).items() if u > now}
    out = {}
    # 10.11. (plan 1.3): also the rows measured with the old levels (no "v":LV_VERSION in the JSON), oldest
    # version last: calls without any levels first, then the ones that only miss the new wide levels
    for tid, tok, h, ts in mcon.execute(
            "SELECT p.tweet_id, p.token, p.handle, p.ts FROM call_path p LEFT JOIN call_lv l "
            "ON l.tweet_id = p.tweet_id AND l.token = p.token WHERE (l.tweet_id IS NULL OR "
            "(? AND l.lv != ? AND l.lv NOT LIKE ? AND l.lv NOT LIKE ?)) AND p.entry IS NOT NULL "
            "AND p.bad IS NULL AND p.ts >= ? ORDER BY (l.tweet_id IS NULL) DESC, p.ts DESC",
            (int(bool(upgrade)), LV_FAILED, f'%"v":{LV_VERSION}%', f'%"stuck":{LV_VERSION}%',
             now - c["days"] * 86400)):
        if tok in skip or tok in wait:
            continue
        if tok not in out and len(out) >= cap:
            continue
        out.setdefault(tok, []).append((tid, h, ts))
    for tok, calls in out.items():
        newest = max(ts for _, _, ts in calls)
        out[tok] = [x for x in calls if newest - x[2] <= SPAN_S - 2 * 3600]
    return out


def waiting(kcon, mcon, c, now):
    """How many real calls of the window still have no minute path."""
    done = _done(mcon)
    return sum(1 for tid, tok, _h, _ts, _n in candidates(kcon, c, now) if (tid, tok) not in done)


def run(kcon, mcon, cfg, now=None, fetch=None, log=print, budget_s=None, per_run=None):
    """Measure due calls within the budget. Returns (tokens fetched, calls stored, tokens left due)."""
    from kol import measure
    ensure(mcon)
    c = config(cfg)
    now = now or int(time.time())
    fetch = fetch or minutes
    budget = budget_s or c["budget_s"]
    todo = due(kcon, mcon, c, now, per_run)
    # 10.11.: the extra work (old rows -> the new wide levels, candles after the first hour) only at night, within
    # its own request budget; rows with no levels at all are measured again any time, as before
    night = _extra_window(c, now) and _night_used(mcon, now) < c["night_requests"]
    relevel = {}
    if len(todo) < c["relevel_per_run"]:   # the backlog of new calls is (nearly) done: old rows get their levels
        relevel = relevel_due(mcon, c, now, skip=todo, cap=c["relevel_per_run"] - len(todo), upgrade=night)
    topup = {}
    if night and len(todo) + len(relevel) < c["relevel_per_run"]:   # 10.11.: candles after old calls, last in line
        topup = candles_due(mcon, c, now, skip=set(todo) | set(relevel), cap=c["candles_per_run"])
    if not todo and not relevel and not topup:
        return 0, 0, 0
    n_new = len(todo)
    n_top = 0
    todo = {**todo, **relevel, **topup}   # new calls first (dict order), then second measurements, then candles
    # 10.11. (review): only NEW calls are worth holding GeckoTerminal for; a pass of second measurements alone
    # runs unreserved (40 tokens x 3.5 s every few minutes would keep the KOL round and the shadow book off the
    # host for hours) and stops the moment anybody else needs it
    hold = fetch is minutes and n_new > 0
    if hold:
        http.reserve(measure.GECKO, budget)
    stop_at = time.monotonic() + budget
    n_tok = n_calls = 0
    left = n_new   # tokens with NEW calls still waiting (the log line); second measurements are not counted
    supply = dict(kcon.execute("SELECT token, supply FROM tokens WHERE token IN (%s)" % ",".join("?" * len(todo)), list(todo)))
    pairs = dict(kcon.execute("SELECT token, pair FROM tokens WHERE token IN (%s)" % ",".join("?" * len(todo)), list(todo)))
    try:
        for tok, calls in todo.items():
            if time.monotonic() > stop_at:
                break
            if fetch is minutes:   # after a 429 every process pauses (http.limited): wait it out inside the budget
                cool = http.cooling(measure.GECKO)
                if cool > 0:
                    if tok in relevel or tok in topup or time.monotonic() + cool > stop_at:
                        break   # second measurements never wait on the host: next pass
                    time.sleep(min(cool + 1, 180))
            if tok in topup and not pairs.get(tok):   # the pool is gone: no more candles to ask for
                mcon.execute("INSERT OR IGNORE INTO call_candles (token, n, full, updated) VALUES (?,0,1,?)", (tok, now))
                mcon.execute("UPDATE call_candles SET full = 1 WHERE token = ?", (tok,))
                mcon.commit()
                continue
            if tok in relevel and not pairs.get(tok):
                # kol.db dropped the token (retention) or its pool since the first measurement: the path stays as it
                # is, and the token must not come back every pass and hold a place in the short relevel queue
                _give_up_lv(mcon, tok, calls)
                mcon.commit()
                continue
            first = min(ts for _, _, ts in calls)
            start = first - 10 * MIN
            end = _fetch_end(calls, start, now)
            if night and (tok in relevel or tok in topup):
                if _night_used(mcon, now) >= c["night_requests"]:
                    continue   # tonight's budget is spent: the rest waits for tomorrow night
                _night_spend(mcon, now)
            try:
                candles = fetch(pairs[tok], start, end)
            except Exception as e:  # noqa: BLE001
                log(f"  minute {tok[:8]}: {type(e).__name__}: {e}")
                # 9.11. (audit P24): 404 = GeckoTerminal does not know the pool: the calls are recorded as bad 'pool'
                # so the token leaves the queue; anything else (403, timeout) waits RETRY_S instead of heading every pass
                if tok in topup:
                    # only the candles were asked for: the measured paths are never touched. Gone pool: given up
                    if getattr(e, "code", None) == 404:
                        mcon.execute("INSERT OR IGNORE INTO call_candles (token, n, full, updated) VALUES (?,0,1,?)",
                                     (tok, now))
                        mcon.execute("UPDATE call_candles SET full = 1 WHERE token = ?", (tok,))
                    else:
                        _set_retry(mcon, tok, now + RETRY_S, now)
                elif getattr(e, "code", None) == 404 and tok in relevel:
                    # measured once already: the path stays, only the levels are given up on
                    _give_up_lv(mcon, tok, calls)
                elif getattr(e, "code", None) == 404:
                    mcon.executemany("INSERT OR REPLACE INTO call_path (tweet_id, token, handle, ts, bad, measured_ts) "
                                     "VALUES (?,?,?,?,'pool',?)", [(tid, tok, h, ts, now) for tid, h, ts in calls])
                    left -= 1
                else:
                    _set_retry(mcon, tok, now + RETRY_S, now)
                mcon.commit()
                continue
            if candles is None:    # another job holds the GeckoTerminal budget (http.reserve): next round
                break
            if tok in topup:   # only the candles after the call were missing: the paths stay as they are
                if candles:
                    keep_candles(mcon, tok, candles, calls, end, now)
                mcon.execute("UPDATE call_candles SET full = 1 WHERE token = ?", (tok,))
                mcon.commit()
                n_top += 1
                continue
            if tok in relevel and not candles:
                _set_retry(mcon, tok, now + RELEVEL_RETRY_S, now)   # nothing came back: ask again tomorrow
                mcon.commit()
                continue
            try:
                keep_candles(mcon, tok, candles, calls, end, now)
            except sqlite3.Error as e:   # a full disk loses the candles, never the measurement
                log(f"  minute {tok[:8]}: svijeće nisu spremljene ({type(e).__name__}: {e})")
            n_tok += 1
            if tok not in relevel:
                left -= 1
            first_ts = kcon.execute("SELECT MIN(ts) FROM calls WHERE token = ? AND kind = 'call' AND handle NOT LIKE 'w:%'",
                                    (tok,)).fetchone()[0]
            for tid, h, ts in calls:
                o = path(candles, ts, wick=c["wick_x"])
                if tok in relevel:
                    # a second measurement only ADDS the levels: the stored path (entry, t5..t30, sl_min, first_caller,
                    # which the leaderboard and the crews read) is never rewritten, and a call whose candle is gone
                    # since then is marked so it is not asked for again
                    if o:
                        mcon.execute("INSERT OR REPLACE INTO call_lv VALUES (?,?,?,?)",
                                     (tid, tok, ts, json.dumps(o["lv"], separators=(",", ":"))))
                        n_calls += 1
                    else:
                        _give_up_lv(mcon, tok, [(tid, h, ts)])
                    continue
                if not o:
                    mcon.execute("INSERT OR REPLACE INTO call_path (tweet_id, token, handle, ts, bad, measured_ts) "
                                 "VALUES (?,?,?,?,'svijeca',?)", (tid, tok, h, ts, now))
                    continue
                mcap = o["entry"] * supply[tok] if supply.get(tok) else None
                bad = "mcap" if mcap is not None and mcap < MIN_MCAP else None
                mcon.execute("INSERT OR REPLACE INTO call_path VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (tid, tok, h, ts, o["entry"], o["lag_s"], mcap, o["hi15"], o["hi30"], o["hi60"], o["lo60"],
                              o["r60"], o["t5"], o["t10"], o["t15"], o["t20"], o["t30"], o["sl_min"],
                              int(first_ts == ts), bad, now))
                mcon.execute("INSERT OR REPLACE INTO call_lv VALUES (?,?,?,?)",
                             (tid, tok, ts, json.dumps(o["lv"], separators=(",", ":"))))
                n_calls += 1
            mcon.commit()
    finally:
        if hold:
            http.release(measure.GECKO)
    mcon.execute("DELETE FROM call_path WHERE ts < ?", (now - KEEP_DAYS * 86400,))
    mcon.execute("DELETE FROM call_lv WHERE ts < ?", (now - KEEP_DAYS * 86400,))
    mcon.execute("DELETE FROM call_candles WHERE COALESCE(last_ts, updated) < ?", (now - KEEP_DAYS * 86400,))
    mcon.execute("INSERT OR REPLACE INTO kv VALUES ('minute_stats', ?)",
                 (json.dumps({"ts": now, "tokens": n_tok, "calls": n_calls, "candles": n_top,
                              "waiting": waiting(kcon, mcon, c, now)}),))
    mcon.commit()
    return n_tok, n_calls, left


def cooling():
    """Seconds GeckoTerminal is to be left alone (shared 429 pause, event_calendar/http.limited)."""
    from kol import measure
    try:
        return http.cooling(measure.GECKO)
    except Exception:  # noqa: BLE001
        return 0.0


def loop(cfg, log=print, once=False, sleep=time.sleep, fetch=None):
    """`run_kol.py minute-loop`: the only writer of minute.db. Passes of loop_budget_s while there is a backlog
    (crews first), then a short pass whenever new calls are old enough (min_age_min), idle otherwise."""
    from kol import store
    c = config(cfg)
    mcon = connect()
    _late = []
    try:
        while True:
            kcon = store.ro()
            if kcon is None:
                sleep(c["idle_sleep_s"])
                if once:
                    return
                continue
            try:
                t, n, left = run(kcon, mcon, cfg, fetch=fetch, log=log, budget_s=c["loop_budget_s"], per_run=10_000)
                hot_ = hot(mcon, kcon, cfg)
                try:   # 9.11.: which TP/SL pair pays over ALL measured calls (kol/tpsl.py), kept in kv tpsl_pool
                    from kol import tpsl
                    tpsl.save_pool(mcon)
                except Exception as e:  # noqa: BLE001 - the measuring loop never dies on a statistic
                    log(f"  tpsl: {type(e).__name__}: {e}")
                # 10.11. (Jure: "12 preskočeno: zašto, i jesu li ipak dosegli +15 %?"): the Autopilot's skipped buys,
                # measured the same way, AFTER the calls and within their own small budget: unreserved, never waiting
                # on GeckoTerminal, only a few while calls are still waiting (kol/preskoceni.py)
                try:
                    from kol import preskoceni
                    preskoceni.maybe_run(mcon, kcon, cfg, fetch=fetch, busy=left > 0,
                                         log=lambda *a, **k: _late.append((a, k)))
                except Exception as e:  # noqa: BLE001 - never stops the call measurements
                    _late.append(((f"  preskočeni: {type(e).__name__}: {e}",), {}))
            finally:
                kcon.close()
            log(f"minute: {t} tokena, {n} poziva po minutnim svijećama, još {left} tokena čeka; vruća lista "
                f"{len(hot_['x'])} X, {len(hot_['tg'])} TG, {len(hot_['wallets'])} walleta", flush=True)
            for a, k in _late:   # the skips' lines after the pass's own line, which stays the first
                log(*a, **k)
            _late.clear()
            if once:
                return
            cool = cooling() if fetch is None else 0
            sleep(max(c["loop_sleep_s"] if left else c["idle_sleep_s"], cool + 2 if t == 0 else 0))
    finally:
        mcon.close()


def _agg(rows):
    """rows: dicts with t5..t30, sl_min, r60, hi15 -> stats dict (n, hit<tp>, sl, rug, med_t10, med_r60, med_hi15)."""
    n = len(rows)
    if not n:
        return None
    out = {"n": n}
    for tp in TPS:
        out[f"hit{tp}"] = sum(1 for r in rows if clean_hit(r, tp)) / n
    out["sl"] = sum(1 for r in rows if r["sl_min"] is not None and not clean_hit(r, 10)) / n
    out["rug"] = sum(1 for r in rows if r.get("rug")) / n
    t10 = [r["t10"] for r in rows if clean_hit(r, 10)]
    out["med_t10"] = statistics.median(t10) if t10 else None
    r60 = [r["r60"] for r in rows if r["r60"] is not None]
    out["med_r60"] = statistics.median(r60) if r60 else None
    hi = [r["hi15"] for r in rows if r["hi15"] is not None]
    out["med_hi15"] = statistics.median(hi) if hi else None
    return out


COLS = ("tweet_id", "token", "handle", "ts", "entry", "lag_s", "mcap_e", "hi15", "hi30", "hi60", "lo60", "r60",
        "t5", "t10", "t15", "t20", "t30", "sl_min", "first_caller")


def _rows(mcon, where, args):
    out = []
    for r in mcon.execute(f"SELECT {', '.join(COLS)} FROM call_path WHERE entry IS NOT NULL AND bad IS NULL AND {where}", args):
        d = dict(zip(COLS, r))
        d["rug"] = d["lo60"] is not None and d["lo60"] <= RUG_LO
        out.append(d)
    return out


def handle_stats(mcon, days=14, now=None, min_n=1):
    """[(handle, stats)] over the account's measured calls of the last `days`, most calls first. 9.11. (audit P23):
    one call per (account, token), the FIRST one, as kol/score and sessions count (first_by_kol): an account that
    posts the same CA five times is one measured call, not five; stats['n_posts'] keeps the raw count."""
    now = now or int(time.time())
    posts, first = {}, {}
    for r in _rows(mcon, "ts >= ?", (now - days * 86400,)):
        posts[r["handle"]] = posts.get(r["handle"], 0) + 1
        k = (r["handle"], r["token"])
        if k not in first or r["ts"] < first[k]["ts"]:
            first[k] = r
    by = {}
    for (h, _tok), r in first.items():
        by.setdefault(h, []).append(r)
    out = []
    for h, rows in by.items():
        if len(rows) >= min_n:
            s = _agg(rows)
            s["n_posts"] = posts[h]
            out.append((h, s))
    out.sort(key=lambda x: (-x[1]["n"], -x[1]["hit10"]))
    return out


def _groups(kcon, since, max_size=4):
    """[(token, start_ts, handles sorted tuple, first_handle)] from kol.db groups, crews of 2..max_size."""
    out = []
    for tok, start, handles, first in kcon.execute("SELECT token, start_ts, handles, first_handle FROM groups WHERE start_ts >= ?", (since,)):
        hs = sorted(set(json.loads(handles or "[]")))
        if 2 <= len(hs) <= max_size:
            out.append((tok, start, tuple(hs), first))
    return out


def potential(stats, n_tokens):
    """One number to rank crews by: how many shared tokens, times how often +10 % came before the stop, minus stops
    and rugs. Shown on the page with its parts, never alone."""
    return round(n_tokens * (stats["hit10"] + 0.5 * stats["hit20"] - stats["sl"] - stats["rug"]), 2)


def crew_stats(mcon, kcon, days=14, now=None, min_n=2, max_size=4):
    """Groups of accounts that called the same token within the group window (kol.db groups), measured from the
    FIRST call of each group: {'crews': [(handles, stats, n_tokens, potential)], 'pairs': [((a, b), stats)]}.
    Groups of more than max_size callers are paid campaigns, not a crew: skipped."""
    now = now or int(time.time())
    first = {(r["token"], r["ts"]): r for r in _rows(mcon, "ts >= ?", (now - days * 86400,))}
    crews, pairs = {}, {}
    for tok, start, hs, _first in _groups(kcon, now - days * 86400, max_size):
        r = first.get((tok, start))
        if not r:
            continue
        crews.setdefault(hs, []).append(r)
        for i in range(len(hs)):
            for j in range(i + 1, len(hs)):
                pairs.setdefault((hs[i], hs[j]), []).append(r)
    out_c = []
    for hs, rs in crews.items():
        if len(rs) < min_n:
            continue
        st = _agg(rs)
        nt = len({r["token"] for r in rs})
        out_c.append((hs, st, nt, potential(st, nt)))
    out_c.sort(key=lambda x: (-x[3], -x[1]["n"]))
    out_p = [(ab, _agg(rs)) for ab, rs in pairs.items() if len(rs) >= min_n]
    out_p.sort(key=lambda x: (-x[1]["n"], -x[1]["hit10"]))
    return {"crews": out_c, "pairs": out_p}


def followers_of(kcon, handles, tg_db=None):
    """handle -> followers (X: kols.followers; tg:channel: tg.db channels.subs); None when unknown."""
    out = {h: None for h in handles}
    xs = [h for h in handles if not h.startswith("tg:")]
    if xs:
        q = ",".join("?" * len(xs))
        for h, f in kcon.execute(f"SELECT handle, followers FROM kols WHERE handle IN ({q})", xs):
            out[h] = f
    tgs = [h[3:] for h in handles if h.startswith("tg:")]
    if tgs:
        p = tg_db or os.environ.get("TG_DB") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tg.db")
        if os.path.exists(p):
            try:
                tc = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
                try:
                    q = ",".join("?" * len(tgs))
                    for n, s in tc.execute(f"SELECT name, subs FROM channels WHERE name IN ({q})", tgs):
                        out["tg:" + n] = s
                finally:
                    tc.close()
            except sqlite3.Error:
                pass
    return out


def crew_detail(mcon, kcon, handles, days=30, now=None, tg_db=None, archived=frozenset()):
    """Everything the page shows for one crew: members with followers, who called first how often, and every shared
    token (newest first) with the first call's minute path, the old 24-h measure as fallback and the rug flag
    (low within the hour <= RUG_LO, kol.db calls.rug, or the token archived by the rug filter)."""
    now = now or int(time.time())
    hs = tuple(sorted(set(handles)))
    since = now - days * 86400
    groups = [g for g in _groups(kcon, since, max_size=max(4, len(hs))) if g[2] == hs]
    first_counts = {}
    for _tok, _start, _hs, first in groups:
        first_counts[first] = first_counts.get(first, 0) + 1
    paths = {(r["token"], r["ts"]): r for r in _rows(mcon, "ts >= ?", (since,))}
    toks = sorted({g[0] for g in groups})
    syms, old = {}, {}
    if toks:
        q = ",".join("?" * len(toks))
        syms = dict(kcon.execute(f"SELECT token, symbol FROM tokens WHERE token IN ({q})", toks))
        for tok, ts, mcap0, max24, r24, rug in kcon.execute(
                f"SELECT token, ts, mcap0, max24, r24h, rug FROM calls WHERE token IN ({q}) AND kind = 'call'", toks):
            old.setdefault(tok, {})[ts] = (mcap0, max24, r24, rug)
            if rug:
                old[tok]["_rug"] = True
    tokens = []
    for tok, start, _hs, first in sorted(groups, key=lambda g: -g[1]):
        p = paths.get((tok, start))
        o = (old.get(tok) or {}).get(start) or (None, None, None, None)
        rug = bool((p and p["rug"]) or (old.get(tok) or {}).get("_rug") or tok in archived)
        tokens.append({"token": tok, "symbol": syms.get(tok), "ts": start, "first": first, "mcap0": o[0],
                       "path": p, "max24": o[1], "r24": o[2], "rug": rug})
    rs = [t["path"] for t in tokens if t["path"]]
    return {"handles": hs, "followers": followers_of(kcon, hs, tg_db), "first": first_counts, "tokens": tokens,
            "stats": _agg(rs), "n_tokens": len(tokens), "rugs": sum(1 for t in tokens if t["rug"]),
            "doubled": sum(1 for t in tokens if (t["max24"] or 0) >= 1.0)}


def coverage(mcon, kcon=None, c=None, now=None):
    """How much of the recent call history has a minute path: {measured, no_candle, small, waiting, last}."""
    c = c or DEFAULT
    now = now or int(time.time())
    try:
        m, nc, sm = mcon.execute("""SELECT SUM(entry IS NOT NULL AND bad IS NULL), SUM(bad = 'svijeca'), SUM(bad = 'mcap')
                                    FROM call_path WHERE ts >= ?""", (now - c["days"] * 86400,)).fetchone()
        st = mcon.execute("SELECT value FROM kv WHERE key = 'minute_stats'").fetchone()
    except Exception:  # noqa: BLE001
        return {"measured": 0, "no_candle": 0, "small": 0, "waiting": None, "last": None}
    st = json.loads(st[0]) if st else {}
    return {"measured": m or 0, "no_candle": nc or 0, "small": sm or 0, "waiting": st.get("waiting"), "last": st.get("ts")}


def hot(mcon, kcon, cfg, now=None, wallet_db=None):
    """The small set worth reading every 1-2 s: accounts whose measured calls of the last hot_days reached +hot_tp %
    before the stop at least hot_min_hit of the time, on hot_min_n+ calls, with the stop first on at most hot_max_sl;
    plus the proven-twice copyable wallets (wallets/dokazani.py). Saved as kv hot_list in minute.db."""
    c = config(cfg)
    now = now or int(time.time())
    x, tg = [], []
    for h, s in handle_stats(mcon, c["hot_days"], now, c["hot_min_n"]):
        if s[f"hit{c['hot_tp']}"] >= c["hot_min_hit"] and s["sl"] <= c["hot_max_sl"]:
            (tg if h.startswith("tg:") else x).append(h)
    wallets = []
    try:
        from wallets import dokazani
        wallets = sorted(dokazani.current(wallet_db))
    except Exception:  # noqa: BLE001
        pass
    out = {"ts": now, "x": x, "tg": [h[3:] for h in tg], "wallets": wallets}
    mcon.execute("INSERT OR REPLACE INTO kv VALUES ('hot_list', ?)", (json.dumps(out),))
    mcon.commit()
    return out


def hot_list(path=None):
    """The saved hot list ({ts, x, tg, wallets}); empty lists when minute.db has none yet."""
    empty = {"ts": 0, "x": [], "tg": [], "wallets": []}
    con = ro(path)
    if con is None:
        return empty
    try:
        r = con.execute("SELECT value FROM kv WHERE key = 'hot_list'").fetchone()
        return {**empty, **json.loads(r[0])} if r else empty
    except Exception:  # noqa: BLE001
        return empty
    finally:
        con.close()
