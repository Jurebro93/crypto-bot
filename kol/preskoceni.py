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
under $30k market cap are measured too: the reason text already says why they were skipped, and the owner asked
whether skipping them was right.

Pool: kol.db tokens.pair when the token was called, else the deepest DexScreener pair (the scanner's 60-s cache,
30 tokens a request), else a 'pool' failure. Failures retry: no candle / unknown pool once a day, a network error
after an hour, a busy host on the next pass. Decisions older than 48 h are not measured any more.

For the page (ui/pravitrade.py, the box under the log's one-line summary): lookup() reads rows by key, verdict()
turns one into "propušteno" / "dobro preskočen" / "mjeri se" / "nema podataka" with its numbers, sentence() the
one-line answer. All pure: no network, no write.
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
KINDS = ("preskocio", "nije_proslo")
DEFAULT = {"budget_s": 60, "per_run": 20, "per_run_busy": 5, "every_s": 120}

SCHEMA = """CREATE TABLE IF NOT EXISTS skip_path (
    token TEXT, ts INTEGER, pool TEXT, entry REAL, lag_s INTEGER, t15 INTEGER, sl_min INTEGER, hi60 REAL, lo60 REAL,
    r60 REAL, max_min INTEGER, lv TEXT, bad TEXT, retry_ts INTEGER, done_ts INTEGER, PRIMARY KEY (token, ts));
CREATE INDEX IF NOT EXISTS skip_path_ts ON skip_path (ts)"""
COLS = ("token", "ts", "pool", "entry", "lag_s", "t15", "sl_min", "hi60", "lo60", "r60", "max_min", "lv", "bad",
        "retry_ts", "done_ts")
TZ = "Europe/Zagreb"
_LAST = {"ts": 0.0}


def ensure(con):
    con.executescript(SCHEMA)


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
    return skipped(rows)


def due(mcon, entries, now, cap):
    """{token: [minute ts, ...]} of skips older than WAIT_S without a row (or whose retry time came), newest first,
    one per (token, minute): two follows skipping the same call in the same minute are one measurement. At most `cap`
    of them; per token only those within SPAN_S of its newest (the rest next pass)."""
    keys = []
    for e in entries:
        k = (e["token"], minute_of(e["ts"]))
        if now - e["ts"] < WAIT_S or now - e["ts"] > WINDOW_S or k in keys:
            continue
        keys.append(k)
    have = {}
    for i in range(0, len(keys), 400):
        ch = keys[i:i + 400]
        toks = sorted({t for t, _ in ch})
        q = ",".join("?" * len(toks))
        for tok, ts, retry in mcon.execute(f"SELECT token, ts, retry_ts FROM skip_path WHERE token IN ({q}) AND ts >= ?",
                                           (*toks, int(now) - WINDOW_S - MIN)):
            have[(tok, ts)] = retry
    out, n = {}, 0
    for tok, ts in keys:
        if (tok, ts) in have and (have[(tok, ts)] is None or have[(tok, ts)] > now):
            continue
        if n >= cap:
            break
        lst = out.setdefault(tok, [])
        if lst and lst[0] - ts > SPAN_S:
            continue
        lst.append(ts)
        n += 1
    return out


# ---------- pools ----------------------------------------------------------------------------------------------

def _dex_pairs(tokens):
    from dexscreener import client
    return client.tokens("solana", list(tokens))


def pools(kcon, mcon, tokens, pairs_fn=None, log=print):
    """({token: pool address}, dex_failed). Order: kol.db tokens.pair (a called token), the pool an earlier try found,
    the deepest DexScreener pair (the scanner's 60-s cache, one request per 30 tokens). dex_failed: DexScreener did
    not answer, so a token without a pool is a network failure, not an unknown token."""
    tokens = list(tokens)
    out = {}
    if kcon is not None and tokens:
        try:
            q = ",".join("?" * len(tokens))
            out.update({t: p for t, p in kcon.execute(f"SELECT token, pair FROM tokens WHERE token IN ({q})", tokens) if p})
        except sqlite3.Error:
            pass
    left = [t for t in tokens if t not in out]
    if left:
        q = ",".join("?" * len(left))
        for t, p in mcon.execute(f"SELECT token, pool FROM skip_path WHERE token IN ({q}) AND pool IS NOT NULL", left):
            out.setdefault(t, p)
    left = [t for t in tokens if t not in out]
    if not left:
        return out, False
    try:
        pairs = (pairs_fn or _dex_pairs)(left) or []
    except Exception as e:  # noqa: BLE001 - DexScreener down: these tokens wait an hour, the rest goes on
        log(f"  preskočeni: DexScreener {type(e).__name__}: {str(e)[:80]}")
        return out, True
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
            best[t] = (liq, p["pairAddress"])
    out.update({t: v[1] for t, v in best.items()})
    return out, False


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


def _put_bad(mcon, tok, ts, pool, bad, retry, now):
    mcon.execute("INSERT OR REPLACE INTO skip_path (token, ts, pool, bad, retry_ts, done_ts) VALUES (?,?,?,?,?,?)",
                 (tok, ts, pool, bad, retry, now))


def _put(mcon, tok, ts, pool, o, peak, now):
    mcon.execute("INSERT OR REPLACE INTO skip_path VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (tok, ts, pool, o["entry"], o["lag_s"], o["t15"], o["sl_min"], o["hi60"], o["lo60"], o["r60"], peak,
                  json.dumps(o["lv"], separators=(",", ":")), None, None, now))


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
    if real and http.cooling(measure.GECKO) > 0:   # after a 429, or another job holds the host: not our turn
        return 0, 0, None
    if entries is None:
        entries = decisions(now)
    cap = c["per_run_busy"] if busy else c["per_run"]
    todo = due(mcon, entries, now, cap)
    if not todo:
        _prune(mcon, now)
        return 0, 0, 0
    found, dex_failed = pools(kcon, mcon, todo, pairs_fn, log)
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
                _put_bad(mcon, tok, ts, None, bad, retry, now)
            mcon.commit()
            left -= len(keys)
            continue
        if real and http.cooling(measure.GECKO) > 0:
            break   # never wait on the host: the call measurements and the KOL round come first
        start = min(keys) - 10 * MIN
        end = min(now, max(keys) + WAIT_S)
        try:
            candles = fetch(pool, start, end)
        except Exception as e:  # noqa: BLE001
            log(f"  preskočeni {tok[:8]}: {type(e).__name__}: {str(e)[:80]}")
            gone = getattr(e, "code", None) == 404   # GeckoTerminal does not know the pool
            for ts in keys:
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
                _put_bad(mcon, tok, ts, pool, "svijeca", now + RETRY_EMPTY_S, now)
                continue
            _put(mcon, tok, ts, pool, o, peak_minute(candles, ts, mc["wick_x"]), now)
            n_rows += 1
        mcon.commit()
        left -= len(keys)
    _prune(mcon, now)
    return n_req, n_rows, left


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
    """{(token, minute ts): row dict} for the given (token, minute ts) keys, read by the primary key."""
    out = {}
    sql = f"SELECT {', '.join(COLS)} FROM skip_path WHERE token = ? AND ts = ?"
    for k in dict.fromkeys(keys):
        r = con.execute(sql, k).fetchone()
        if r:
            out[k] = dict(zip(COLS, r))
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
        return (json.loads(row.get("lv") or "{}").get(key) or {}).get(str(int(level))), True
    except (ValueError, AttributeError):
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
    """+42 % / −8 % (a real minus sign, a space before %, as the page writes percentages)."""
    v = round(100 * float(x))
    return f"{'+' if v >= 0 else '−'}{abs(v)} %"


def hm(ts, now=None):
    """14:05, or 'jučer 23:10', in Zagreb time."""
    try:
        from zoneinfo import ZoneInfo
        z = ZoneInfo(TZ)
    except Exception:  # noqa: BLE001 - no tz database: UTC, said so
        z = datetime.timezone.utc
    d = datetime.datetime.fromtimestamp(int(ts), z)
    n = datetime.datetime.fromtimestamp(int(now or time.time()), z)
    s = f"{d:%H:%M}" + ("" if z is not datetime.timezone.utc else " UTC")
    if d.date() == n.date():
        return s
    if (n.date() - d.date()).days == 1:
        return f"jučer {s}"
    return f"{d.day}.{d.month}. {s}"


def verdict(row, ts, now, tp=TP, sl=SL):
    """{"kind", "word", "detail"} of one skip. kind: "miss" (propušteno: +tp % before -sl % within the hour),
    "ok" (dobro preskočen: the stop first, or no +tp % within the hour), "wait" (mjeri se: younger than WAIT_S,
    not measured yet, or a network error to be retried), "none" (nema podataka: no pool, no candle)."""
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
                "detail": f"+{tp} % za {t} min" + (f" · najviše {pct(hi)}" if hi is not None else "")}
    if hi is None and lo is None:
        return {"kind": "ok", "word": "dobro preskočen", "detail": "sat vremena bez trgovanja"}
    bits = [f"−{sl} % za {s} min"] if s is not None else ([f"najviše {pct(hi)}"] if hi is not None else [])
    if r60 is not None:
        bits.append(f"nakon 1 h {pct(r60)}")
    if lo is not None:
        bits.append(f"najniže {pct(lo)}")
    return {"kind": "ok", "word": "dobro preskočen", "detail": " · ".join(bits)}


def _one(n):
    return n % 10 == 1 and n % 100 != 11


def _few(n):
    return n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14)


def counts(verdicts):
    out = {"miss": 0, "ok": 0, "wait": 0, "none": 0}
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
