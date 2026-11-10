"""Preskočeni signali (10.11., Jure: "piše da je 12 redova preskočeno; zanima me zašto i kako su performali nakon
toga: jesu li uspjeli doseći 15 % ili su preskočeni s dobrim razlogom").

What the price did in the hour after every buy the Autopilot skipped (trade/aplog.py kinds "preskocio" and
"nije_proslo", buy side), measured exactly like a call in kol/minute.py: GeckoTerminal 1-minute candles, entry = the
close of the minute of the decision, then +15 % (the Autopilot's default target) and -20 % (league/copy.DEFAULT_SL)
minute by minute for 60 minutes. One row per (token, minute of the skip) in minute.db table skip_path.

Who runs it: only kol/minute.loop, after its own pass (the call measurements always go first). It never reserves
GeckoTerminal, never waits on it: a pass stops the moment the host is cooling after a 429 or another job holds it
(minutes() answers None), at most PER_RUN skips and BUDGET_S seconds a pass. trade.db and league.db are read through
read-only connections; nothing here can change a trade (it is a measurement of a decision already made). Tokens
under $30k market cap are NOT measured (CLAUDE.md: tokens under $30k are not analysed): a skip whose short reason is
"MC ispod 30k" is listed with the verdict "ispod 30k" and costs no request.

Pool: kol.db tokens.pair when the token was called, else the deepest DexScreener pair (the scanner's 60-s cache,
30 tokens a request), else a 'pool' failure. Failures retry: no candle / unknown pool once a day, a network error
after an hour, a busy host on the next pass. Decisions older than 48 h are not measured any more.

10.11. (Jure: "stavi na koliko market capa ga je zvao dotični wallet ili influencer ... koliko se cijena makla u 5, 10,
15 minuta"): the same single candle request now starts at the minute of the CALL (trade/aplog sig_ts: the followed
account's post or buy) when that came before the decision, and the row also keeps the price at the call (p_sig: the
close of the call's minute, or the open of the next candle within 5 min), the last close at or before call + 5, 10
and 15 minutes (p5, p10, p15) and the token's supply, so any of those prices reads as a market cap (supply x price).
Supply: kol.db tokens.supply, else marketCap (or fdv) / priceUsd of the DexScreener pair the pool lookup reads anyway
(one batched request per pass). Without a known call time, or without a trade within 5 min of it, p5/p10/p15 are
measured from the decision minute instead (p_sig stays NULL, which is how the page knows). Rows measured before this
(ver NULL) are measured once more while their decision is within WINDOW_S; a failure of that second try keeps the
old numbers.

For the page (ui/pravitrade.py, the box under the log's one-line summary and the pop-up of one skip): lookup() reads
rows by key, verdict() turns one into "propušteno" / "dobro preskočen" / "mjeri se" / "nema podataka" with its
numbers, sentence() the one-line answer, moves() the market caps and moves from the call. All pure: no network, no
write.
"""
import datetime
import json
import os
import sqlite3
import time

MIN = 60
WAIT_S = 65 * MIN          # a skip is measured once its hour (and 5 minutes for GeckoTerminal's lag) is over
WINDOW_S = 48 * 3600       # decisions older than this are not measured any more
HORIZON_MIN = 60
TP, SL = 15, 20            # the verdict Jure asked for: +15 % before -20 %, both within 60 min of the skip
KEEP_DAYS = 30
RETRY_EMPTY_S = 86400      # no candle / unknown pool: once a day
RETRY_ERR_S = 3600         # 403, timeout, DexScreener down: in an hour
SPAN_S = 12 * 3600         # skips of one token within this share one candle request
MAX_SPAN_S = 990 * MIN     # one GeckoTerminal request returns at most 1000 one-minute candles
STEPS = (5, 10, 15)        # 10.11. (Jure): "koliko se cijena makla u 5, 10, 15 minuta" from the call
VER = 2                    # rows measured with the call's prices and the supply (NULL: measured before 10.11.)
KINDS = ("preskocio", "nije_proslo")
DEFAULT = {"budget_s": 60, "per_run": 20, "per_run_busy": 5, "every_s": 120}

SCHEMA = """CREATE TABLE IF NOT EXISTS skip_path (
    token TEXT, ts INTEGER, pool TEXT, entry REAL, lag_s INTEGER, t15 INTEGER, sl_min INTEGER, hi60 REAL, lo60 REAL,
    r60 REAL, max_min INTEGER, lv TEXT, bad TEXT, retry_ts INTEGER, done_ts INTEGER, sig_ts INTEGER, p_sig REAL,
    p5 REAL, p10 REAL, p15 REAL, supply REAL, ver INTEGER, PRIMARY KEY (token, ts));
CREATE INDEX IF NOT EXISTS skip_path_ts ON skip_path (ts)"""
# 10.11. (Jure): added to tables made before (ensure); NULL in the rows measured before
NEW_COLS = (("sig_ts", "INTEGER"), ("p_sig", "REAL"), ("p5", "REAL"), ("p10", "REAL"), ("p15", "REAL"),
            ("supply", "REAL"), ("ver", "INTEGER"))
COLS = ("token", "ts", "pool", "entry", "lag_s", "t15", "sl_min", "hi60", "lo60", "r60", "max_min", "lv", "bad",
        "retry_ts", "done_ts") + tuple(c for c, _ in NEW_COLS)
TZ = "Europe/Zagreb"
_LAST = {"ts": 0.0}


def ensure(con):
    """The table, and the columns of 10.11. on a table made before (ALTER TABLE, idempotent)."""
    con.executescript(SCHEMA)
    have = {r[1] for r in con.execute("PRAGMA table_info(skip_path)")}
    for name, typ in NEW_COLS:
        if name not in have:
            con.execute(f"ALTER TABLE skip_path ADD COLUMN {name} {typ}")
    con.commit()


def config(cfg):
    return {**DEFAULT, **((cfg or {}).get("preskoceni") or {})}


def minute_of(ts):
    ts = int(ts or 0)
    return ts - ts % MIN


# ---------- which decisions -------------------------------------------------------------------------------------

def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)


def skipped(rows):
    """The buy-side skips of aplog rows: the set the log's "N preskočeno" (and "nije prošlo") counts."""
    return [e for e in rows or () if e.get("kind") in KINDS and e.get("side") != "sell" and e.get("token")]


UNDER_FLOOR = "MC ispod 30k"   # trade/aplog.why_short of the $30k rule


def under_floor(e):
    """10.11. (CLAUDE.md, Jure: tokeni ispod 30k $ se ne analiziraju): a skip because of the $30k floor is not measured."""
    return (e.get("why_short") or "") == UNDER_FLOOR


def decisions(now, trade_db=None, league_db=None):
    """[aplog entry] of the buy-side skips of the last WINDOW_S, newest first, read through read-only connections
    (trade.db: settings.DB, league.db: league.store.DB). [] when trade.db is not there."""
    from trade import aplog, settings
    from league import store
    tcon = _ro(trade_db or settings.DB)
    if tcon is None:
        return []
    lcon = None
    try:
        lcon = _ro(league_db or store.DB)
        rows = aplog.entries(tcon, lcon, limit=aplog.MAX_LIMIT, since=int(now) - WINDOW_S, now=now)
    finally:
        tcon.close()
        if lcon is not None:
            lcon.close()
    return [e for e in skipped(rows) if not under_floor(e)]   # the $30k rule: nothing to measure


def signals(entries):
    """{(token, decision minute): sig_ts}: when the call (or the followed wallet's buy) behind the skip happened.
    Two follows that skipped the same token in the same minute on different signals: the earliest, i.e. what
    following the first caller would have got."""
    out = {}
    for e in entries or ():
        s = e.get("sig_ts")
        if not s or not e.get("token"):
            continue
        k = (e["token"], minute_of(e["ts"]))
        out[k] = min(out.get(k, int(s)), int(s))
    return out


def due(mcon, entries, now, cap, sigs=None):
    """{token: [minute ts, ...]} of skips older than WAIT_S without a row (or whose retry time came), newest first,
    one per (token, minute): two follows skipping the same call in the same minute are one measurement. At most `cap`
    of them; per token only those within SPAN_S of its newest, counted from the call when it came first (the rest
    next pass). 10.11.: a row measured before the call's prices were kept (ver NULL) is due once more."""
    keys, seen = [], set()   # 10.11. (pregled): a set for the check, the list keeps the newest-first order
    for e in entries:
        k = (e["token"], minute_of(e["ts"]))
        if now - e["ts"] < WAIT_S or now - e["ts"] > WINDOW_S or k in seen:
            continue
        seen.add(k)
        keys.append(k)
    have = {}
    for i in range(0, len(keys), 400):
        ch = keys[i:i + 400]
        toks = sorted({t for t, _ in ch})
        q = ",".join("?" * len(toks))
        for tok, ts, retry, ver, good in mcon.execute(
                f"SELECT token, ts, retry_ts, ver, entry IS NOT NULL AND bad IS NULL FROM skip_path WHERE token IN ({q}) "
                "AND ts >= ?", (*toks, int(now) - WINDOW_S - MIN)):
            have[(tok, ts)] = (retry, good and ver is None)
    sigs = sigs or {}
    out, n = {}, 0
    for tok, ts in keys:
        if (tok, ts) in have:
            retry, again = have[(tok, ts)]
            if (retry is not None and retry > now) or (retry is None and not again):
                continue
        if n >= cap:
            break
        lst = out.setdefault(tok, [])
        if lst and lst[0] - min(ts, minute_of(sigs.get((tok, ts)) or ts)) > SPAN_S:
            continue
        lst.append(ts)
        n += 1
    return out


# ---------- pools ----------------------------------------------------------------------------------------------

def _dex_pairs(tokens):
    from dexscreener import client
    # 10.11. (pregled): the live path (5-s timeout, no retry); the scanner path retries with back-off for minutes and
    # this runs inside the minute loop
    return client.tokens_live("solana", list(tokens), ttl=60)


def pair_supply(p):
    """Token supply from a DexScreener pair: marketCap (else fdv) / priceUsd; None when either is missing."""
    try:
        price = float(p.get("priceUsd") or 0)
        mcap = float(p.get("marketCap") or p.get("fdv") or 0)
    except (TypeError, ValueError):
        return None
    return mcap / price if price > 0 and mcap > 0 else None


def resolve(kcon, mcon, tokens, pairs_fn=None, log=print, supply=True):
    """({token: pool address}, {token: supply}, dex_failed). Order for both: kol.db tokens (pair, supply of a called
    token), what an earlier try stored in skip_path, the deepest DexScreener pair (one request per 30 tokens, asked
    once for every token that still lacks one of the two). dex_failed: DexScreener did not answer, so a token without
    a pool is a network failure, not an unknown token. supply=False: the pools only (DexScreener only for those)."""
    tokens = list(tokens)
    pool, sup = {}, {}
    if kcon is not None and tokens:
        try:
            q = ",".join("?" * len(tokens))
            for t, p, s in kcon.execute(f"SELECT token, pair, supply FROM tokens WHERE token IN ({q})", tokens):
                if p:
                    pool[t] = p
                if s and float(s) > 0:
                    sup[t] = float(s)
        except (sqlite3.Error, TypeError, ValueError):
            pass
    left = [t for t in tokens if t not in pool or (supply and t not in sup)]
    if left:
        q = ",".join("?" * len(left))
        for t, p, s in mcon.execute(f"SELECT token, pool, supply FROM skip_path WHERE token IN ({q}) "
                                    "AND (pool IS NOT NULL OR supply IS NOT NULL)", left):
            if p:
                pool.setdefault(t, p)
            if s and s > 0:
                sup.setdefault(t, float(s))
    left = [t for t in tokens if t not in pool or (supply and t not in sup)]
    if not left:
        return pool, sup, False
    try:
        pairs = (pairs_fn or _dex_pairs)(left) or []
    except Exception as e:  # noqa: BLE001 - DexScreener down: these tokens wait an hour, the rest goes on
        log(f"  preskočeni: DexScreener {type(e).__name__}: {str(e)[:80]}")
        return pool, sup, True
    best = {}
    for p in pairs:
        t = (p.get("baseToken") or {}).get("address")
        if t not in left or not p.get("pairAddress") or p.get("chainId") not in (None, "solana"):
            continue
        try:
            liq = float((p.get("liquidity") or {}).get("usd") or 0)
        except (TypeError, ValueError):
            liq = 0.0
        if t not in best or liq > best[t][0]:
            best[t] = (liq, p)
    for t, (_, p) in best.items():
        pool.setdefault(t, p["pairAddress"])
        if supply and t not in sup and pair_supply(p):
            sup[t] = pair_supply(p)
    return pool, sup, False


def pools(kcon, mcon, tokens, pairs_fn=None, log=print):
    """({token: pool address}, dex_failed): resolve() without the supply."""
    out, _, failed = resolve(kcon, mcon, tokens, pairs_fn, log, supply=False)
    return out, failed


# ---------- the measurement ------------------------------------------------------------------------------------

def peak_minute(candles, ts, wick=3.0, horizon_min=HORIZON_MIN):
    """Minute after the entry minute in which the capped high of the hour was reached (as kol/minute.path caps it)."""
    m0 = minute_of(ts)
    best = None
    for c in candles:
        if c[0] <= m0 or c[0] > m0 + horizon_min * MIN:
            continue
        capped = min(c[2], max(c[1], c[4]) * wick)
        if best is None or capped > best[0]:
            best = (capped, (c[0] - m0) // MIN)
    return int(best[1]) if best else None


def price_at(candles, ts):
    """The price at a moment as kol/minute.path takes the entry: the close of its minute, else the open of the first
    candle within 5 minutes after it; None without either."""
    m = minute_of(ts)
    for c in candles:
        if c[0] == m:
            return c[4] if c[4] and c[4] > 0 else None
        if m < c[0] <= m + 5 * MIN:
            return c[1] if c[1] and c[1] > 0 else None
    return None


def last_close(candles, until):
    """The last close of a candle that starts at or before `until` (candles oldest first): the price then, also
    when nobody traded in that very minute."""
    out = None
    for c in candles:
        if c[0] > until:
            break
        out = c[4]
    return out


def at_signal(candles, ts, sig_ts=None):
    """10.11. (Jure: "koliko se cijena makla u 5, 10, 15 minuta"): {"sig_ts", "p_sig", "p5", "p10", "p15"}.
    p_sig: the price at the call; p5/p10/p15: the last close at or before the call's minute + 5/10/15. Without a call
    time or a trade within 5 minutes of it, p_sig is None and p5/p10/p15 are counted from the decision minute (whose
    price is the row's entry)."""
    candles = sorted(candles or ())
    p_sig = price_at(candles, sig_ts) if sig_ts else None
    m = minute_of(sig_ts if p_sig else ts)
    out = {"sig_ts": int(sig_ts) if sig_ts else None, "p_sig": p_sig}
    for k in STEPS:
        out[f"p{k}"] = last_close(candles, m + k * MIN)
    return out


def _put_bad(mcon, tok, ts, pool, bad, retry, now):
    mcon.execute("INSERT OR REPLACE INTO skip_path (token, ts, pool, bad, retry_ts, done_ts) VALUES (?,?,?,?,?,?)",
                 (tok, ts, pool, bad, retry, now))


def _put(mcon, tok, ts, pool, o, peak, now, supply=None):
    v = {"token": tok, "ts": ts, "pool": pool, "entry": o["entry"], "lag_s": o["lag_s"], "t15": o["t15"],
         "sl_min": o["sl_min"], "hi60": o["hi60"], "lo60": o["lo60"], "r60": o["r60"], "max_min": peak,
         "lv": json.dumps(o["lv"], separators=(",", ":")), "bad": None, "retry_ts": None, "done_ts": now,
         "sig_ts": o.get("sig_ts"), "p_sig": o.get("p_sig"), "p5": o.get("p5"), "p10": o.get("p10"),
         "p15": o.get("p15"), "supply": supply, "ver": VER}
    mcon.execute(f"INSERT OR REPLACE INTO skip_path ({', '.join(v)}) VALUES ({','.join('?' * len(v))})", tuple(v.values()))


def _keep(mcon, tok, ts, retry):
    """10.11.: the second measurement of a row measured before (ver NULL) failed: its numbers stay. A network error
    is tried again at `retry`; anything else (no candle, no pool any more) is not asked again."""
    mcon.execute("UPDATE skip_path SET retry_ts=?, ver=? WHERE token=? AND ts=?", (retry, None if retry else VER, tok, ts))


def run(mcon, kcon, cfg=None, now=None, fetch=None, log=print, busy=False, entries=None, pairs_fn=None):
    """One pass: measure the due skips. busy = the call measurements still have a backlog: then only per_run_busy
    skips. Returns (candle requests, rows stored, skips left due)."""
    from event_calendar import http
    from kol import measure, minute
    ensure(mcon)
    c = config(cfg)
    mc = minute.config(cfg)
    now = int(now or time.time())
    real = fetch is None or fetch is minute.minutes
    fetch = fetch or minute.minutes
    if not real and pairs_fn is None:   # a stand-in for the candles (tests) never reaches the real DexScreener either
        pairs_fn = lambda toks: []   # noqa: E731
    if real and http.cooling(measure.GECKO) > 0:   # after a 429, or another job holds the host: not our turn
        return 0, 0, None
    if entries is None:
        entries = decisions(now)
    cap = c["per_run_busy"] if busy else c["per_run"]
    sigs = signals(entries)
    todo = due(mcon, entries, now, cap, sigs)
    if not todo:
        _prune(mcon, now)
        return 0, 0, 0
    again = _measured(mcon, todo)
    found, supply, dex_failed = resolve(kcon, mcon, todo, pairs_fn, log)
    stop_at = time.monotonic() + c["budget_s"]
    n_req = n_rows = 0
    left = sum(len(v) for v in todo.values())
    for tok, keys in todo.items():
        if time.monotonic() > stop_at:
            break
        pool = found.get(tok)
        if not pool:
            bad, retry = ("greska", now + RETRY_ERR_S) if dex_failed else ("pool", now + RETRY_EMPTY_S)
            for ts in keys:
                if (tok, ts) in again:
                    _keep(mcon, tok, ts, retry if dex_failed else None)
                else:
                    _put_bad(mcon, tok, ts, None, bad, retry, now)
            mcon.commit()
            left -= len(keys)
            continue
        if real and http.cooling(measure.GECKO) > 0:
            break   # never wait on the host: the call measurements and the KOL round come first
        # 10.11. (Jure): from the minute of the call when it came before the decision, still ONE request (at most
        # 1000 candles: a call older than that keeps only its time, the moves are then counted from the decision)
        end = min(now, max(keys) + WAIT_S)
        start = max(min(min(ts, minute_of(sigs.get((tok, ts)) or ts)) for ts in keys) - 10 * MIN, end - MAX_SPAN_S)
        try:
            candles = fetch(pool, start, end)
        except Exception as e:  # noqa: BLE001
            log(f"  preskočeni {tok[:8]}: {type(e).__name__}: {str(e)[:80]}")
            gone = getattr(e, "code", None) == 404   # GeckoTerminal does not know the pool
            for ts in keys:
                if (tok, ts) in again:
                    _keep(mcon, tok, ts, None if gone else now + RETRY_ERR_S)
                else:
                    _put_bad(mcon, tok, ts, pool, "pool" if gone else "greska",
                             now + (RETRY_EMPTY_S if gone else RETRY_ERR_S), now)
            mcon.commit()
            left -= len(keys)
            continue
        if candles is None:   # another job holds GeckoTerminal (http.reserve): next pass, nothing written
            break
        n_req += 1
        for ts in keys:
            o = minute.path(candles, ts, wick=mc["wick_x"]) if candles else None
            if o is None:
                if (tok, ts) in again:
                    _keep(mcon, tok, ts, None)
                else:
                    _put_bad(mcon, tok, ts, pool, "svijeca", now + RETRY_EMPTY_S, now)
                continue
            o.update(at_signal(candles, ts, sigs.get((tok, ts))))
            _put(mcon, tok, ts, pool, o, peak_minute(candles, ts, mc["wick_x"]), now, supply.get(tok))
            n_rows += 1
        mcon.commit()
        left -= len(keys)
    _prune(mcon, now)
    return n_req, n_rows, left


def _measured(mcon, todo):
    """{(token, minute)} of the due keys that already have measured numbers (a second measurement, ver NULL)."""
    out = set()
    for tok, keys in todo.items():
        for ts in keys:
            if mcon.execute("SELECT 1 FROM skip_path WHERE token=? AND ts=? AND entry IS NOT NULL AND bad IS NULL",
                            (tok, ts)).fetchone():
                out.add((tok, ts))
    return out


def _prune(mcon, now):
    mcon.execute("DELETE FROM skip_path WHERE ts < ?", (now - KEEP_DAYS * 86400,))
    mcon.commit()


def maybe_run(mcon, kcon, cfg=None, fetch=None, log=print, busy=False, now=None):
    """kol/minute.loop's hook: at most once every every_s seconds, never an exception towards the loop."""
    c = config(cfg)
    t = time.time() if now is None else now
    if 0 <= t - _LAST["ts"] < c["every_s"]:
        return None
    _LAST["ts"] = t
    try:
        res = run(mcon, kcon, cfg, now=now, fetch=fetch, log=log, busy=busy)
    except Exception as e:  # noqa: BLE001 - a statistic never stops the call measurements
        log(f"  preskočeni: {type(e).__name__}: {str(e)[:120]}")
        return None
    if res[0] or res[1]:
        log(f"preskočeni: {res[0]} zahtjeva za svijeće, {res[1]} odluka izmjereno, još {res[2]} čeka", flush=True)
    return res


# ---------- for the page -------------------------------------------------------------------------------------------

def lookup(con, keys):
    """{(token, minute ts): row dict} for the given (token, minute ts) keys, read by the primary key. A table the
    minute loop has not migrated yet (the page reads minute.db read-only, right after a deploy) gives None for the
    columns of 10.11."""
    out = {}
    have = {r[1] for r in con.execute("PRAGMA table_info(skip_path)")}
    cols = [c for c in COLS if c in have]
    sql = f"SELECT {', '.join(cols)} FROM skip_path WHERE token = ? AND ts = ?"
    for k in dict.fromkeys(keys):
        r = con.execute(sql, k).fetchone()
        if r:
            out[k] = {**dict.fromkeys(COLS), **dict(zip(cols, r))}
    return out


def _first(row, key, level, std, col):
    """(first minute the level was touched or None, whether that level is stored at all): the column for the
    standard level (+15 / -20), else kol/minute's levels JSON (UPS / DOWNS)."""
    if int(level) == std:
        return row.get(col), True
    from kol import minute
    if int(level) not in (minute.UPS if key == "u" else minute.DOWNS):
        return None, False
    try:
        d = json.loads(row.get("lv") or "{}")
        if int(d.get("v") or 1) < minute.LV_VERSION and int(level) not in (minute.OLD_UPS if key == "u"
                                                                             else minute.OLD_DOWNS):
            return None, False   # 10.11.: measured before -60/-70 and +150/+200 were stored: not known
        return (d.get(key) or {}).get(str(int(level))), True
    except (ValueError, AttributeError, TypeError):
        return None, False


def hit(row, tp=TP, sl=SL):
    """True: +tp % came before -sl % within the hour; False: it did not; None: no measured path, or a level that is
    not stored (then nothing is claimed)."""
    if not row or row.get("entry") is None or row.get("bad"):
        return None
    t, ok_t = _first(row, "u", tp, TP, "t15")
    s, ok_s = _first(row, "d", sl, SL, "sl_min")
    if not (ok_t and ok_s):
        return None
    return t is not None and (s is None or t < s)


def pct(x):
    """+42 % / −8 % (a real minus sign, a space before %, as the page writes percentages). 10.11. (pregled snimki):
    the space does not break, a lone "%" at the start of a phone line read as a separate number."""
    v = round(100 * float(x))
    return f"{'+' if v >= 0 else '−'}{abs(v)}\u00a0%"


def clock(ts, now=None, sec=True):
    """14:05:41 (sec=False: 14:05), or 'jučer 23:10:05', '8.11. 23:10:05', in Zagreb time (Jure: "sa točnim
    vremenom, satom")."""
    try:
        from zoneinfo import ZoneInfo
        z = ZoneInfo(TZ)
    except Exception:  # noqa: BLE001 - no tz database: UTC, said so
        z = datetime.timezone.utc
    d = datetime.datetime.fromtimestamp(int(ts), z)
    n = datetime.datetime.fromtimestamp(int(now or time.time()), z)
    s = (f"{d:%H:%M:%S}" if sec else f"{d:%H:%M}") + ("" if z is not datetime.timezone.utc else " UTC")
    if d.date() == n.date():
        return s
    if (n.date() - d.date()).days == 1:
        return f"jučer {s}"
    return f"{d.day}.{d.month}. {s}"


def hm(ts, now=None):
    """14:05, or 'jučer 23:10', in Zagreb time."""
    return clock(ts, now, sec=False)


def measured(row):
    """True when the row carries a measured price path (not a failure, not missing)."""
    return bool(row) and isinstance(row, dict) and row.get("entry") is not None and not row.get("bad")


def moves(row, supply=None):
    """10.11. (Jure: "na koliko market capa ga je zvao ... koliko se cijena makla u 5, 10, 15 minuta"): the prices of
    one measured skip as market caps and moves. None without a measured path.
    {"ref": "poziv" | "odluka" (what the moves are counted from: the call when its price is known, else the decision),
     "ref_min": the minute the +5/+10/+15 are counted from, "supply": the row's supply (else `supply`, e.g. from the
     live quote; None = only the moves are known),
     "poziv": (price, mcap) or None, "odluka": (price, mcap, change),
     "steps": [(k, minute ts, price, mcap, change)], "hi": (minute ts, price, mcap, change) or None}
    mcap = supply x price (None without a supply); change = price / reference price - 1."""
    if not measured(row):
        return None
    sup = row.get("supply") or supply
    sup = float(sup) if sup and float(sup) > 0 else None
    p_sig, entry = row.get("p_sig"), float(row["entry"])
    ref = float(p_sig) if p_sig else entry

    def mc(p):
        return p * sup if (p is not None and sup) else None

    def ch(p):
        return p / ref - 1 if p is not None and ref > 0 else None

    ref_min = minute_of(row["sig_ts"]) if (p_sig and row.get("sig_ts")) else int(row["ts"])
    steps = []
    for k in STEPS:
        p = row.get(f"p{k}")
        p = float(p) if p is not None else None
        steps.append((k, ref_min + k * MIN, p, mc(p), ch(p)))
    hi = None
    if row.get("hi60") is not None:
        p = entry * (1 + float(row["hi60"]))
        at = int(row["ts"]) + int(row["max_min"]) * MIN if row.get("max_min") is not None else None
        hi = (at, p, mc(p), ch(p))
    return {"ref": "poziv" if p_sig else "odluka", "ref_min": ref_min, "supply": sup,
            "poziv": (float(p_sig), mc(float(p_sig))) if p_sig else None,
            "odluka": (entry, mc(entry), ch(entry)), "steps": steps, "hi": hi}


def verdict(row, ts, now, tp=TP, sl=SL):
    """{"kind", "word", "detail"} of one skip. kind: "miss" (propušteno: +tp % before -sl % within the hour),
    "ok" (dobro preskočen: the stop first, or no +tp % within the hour), "wait" (mjeri se: younger than WAIT_S,
    not measured yet, or a network error to be retried), "none" (nema podataka: no pool, no candle)."""
    if row == UNDER_FLOOR:
        return {"kind": "floor", "word": "ispod 30k", "detail": "po pravilu se ne kupuje ni ne mjeri"}
    if now - ts < WAIT_S:
        return {"kind": "wait", "word": "mjeri se", "detail": f"rezultat oko {hm(ts + WAIT_S, now)}"}
    if not row or row.get("bad") == "greska":
        return {"kind": "wait", "word": "mjeri se", "detail": "čeka mjerenje"}
    if row.get("bad") or row.get("entry") is None:
        return {"kind": "none", "word": "nema podataka",
                "detail": "pool nije pronađen" if row.get("bad") == "pool" else "nema svijeća za taj sat"}
    t, _ = _first(row, "u", tp, TP, "t15")
    s, _ = _first(row, "d", sl, SL, "sl_min")
    hi, lo, r60 = row.get("hi60"), row.get("lo60"), row.get("r60")
    if t is not None and (s is None or t < s):
        return {"kind": "miss", "word": "propušteno",
                "detail": f"+{tp}\u00a0% za {t} min" + (f" · najviše {pct(hi)}" if hi is not None else "")}
    if hi is None and lo is None:
        return {"kind": "ok", "word": "dobro preskočen", "detail": "sat vremena bez trgovanja"}
    bits = [f"−{sl}\u00a0% za {s} min"] if s is not None else ([f"najviše {pct(hi)}"] if hi is not None else [])
    if r60 is not None:
        bits.append(f"nakon 1\u00a0h {pct(r60)}")   # 10.11. (pregled): "1 h" never breaks
    if lo is not None:
        bits.append(f"najniže {pct(lo)}")
    return {"kind": "ok", "word": "dobro preskočen", "detail": " · ".join(bits)}


def _one(n):
    return n % 10 == 1 and n % 100 != 11


def _few(n):
    return n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14)


def counts(verdicts):
    out = {"miss": 0, "ok": 0, "wait": 0, "none": 0, "floor": 0}
    for v in verdicts:
        out[v["kind"]] = out.get(v["kind"], 0) + 1
    return out


def _parts(c, tp, sl):
    parts = []
    if c["miss"]:
        parts.append(f"{c['miss']} bi {'dosegao' if _one(c['miss']) else 'dosegla'} +{tp} % prije −{sl} %")
        if c["ok"]:
            parts.append(f"{c['ok']} {'nije' if _one(c['ok']) else 'nisu'}")
    elif c["ok"]:
        parts.append(f"nijedan nije dosegao +{tp} % prije −{sl} % (izmjereno {c['ok']})")
    if c["wait"]:
        parts.append(f"{c['wait']} se još {'mjeri' if _one(c['wait']) else 'mjere'}")
    if c["none"]:
        parts.append(f"{c['none']} bez podataka")
    if c.get("floor"):
        parts.append(f"{c['floor']} ispod 30k (ne mjeri se)")
    return ", ".join(parts)


def sentence(skips, tech, tp=TP, sl=SL):
    """The one-line answer above the rows. skips / tech: verdicts of the rule skips and of the technical failures.
    'Od 12 preskočenih: 3 bi dosegla +15 % prije −20 %, 7 nisu, 2 se još mjere.'"""
    out = []
    n = len(skips)
    if n:
        word = "preskočenog" if _one(n) else "preskočena" if _few(n) else "preskočenih"
        out.append(f"Od {n} {word}: {_parts(counts(skips), tp, sl)}.")
    m = len(tech)
    if m:
        lead = f"{'Još ' if n else ''}{m} {'nije prošao' if _one(m) else 'nisu prošla'} tehnički"
        out.append(f"{lead}: {_parts(counts(tech), tp, sl)}.")
    return " ".join(out)
