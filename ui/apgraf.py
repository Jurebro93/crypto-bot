"""The Autopilot chart's history on demand (14.11. 17:01, owner: "Graf ne prikazuje dobro": YoungBull on 1h showed one
candle and a cut fragment of another; the rest of the chart was empty).

The chart (ui/apterm.candles_data) reads only what the bot already stores. A token the bot has just started to watch,
or one the owner opens or buys by hand, has minutes of our snapshots, so 1h / 15m showed one or two candles. When the
stored series of the asked window is thin (need()), ONE GeckoTerminal request fills it, in a background thread: the
page never waits; the first answer says "dohvaćam povijest…" (fill.state "dohvacam") and the browser asks again a few
seconds later.
  m1  1-minute OHLCV, the last 998 minutes (~16.6 h), the same request as the range job's seed (rangedca/data.seed),
      stored in range.db gt_candles (store_gt): later views and the range detector reuse it, and the range job does
      not seed that token again for 24 h (as after its own seed)
  h1  1-hour OHLCV, the last 7 days (one request), for the 1h view of a token older than one m1 request reaches;
      stored in range.db gt_hours (the range detector works on minutes; only the chart reads these)

Budget (CLAUDE.md: "prije svakog troška izmjeri"; cost per source in the daily line):
  - its own day cap GRAF_DAY (AP_GRAF_DAY, default 60 requests a UTC day), counted in range.db kv graf_day; the range
    list's caps (gt_day, mkt_gt_day, mkt_seed_day) are never read or touched here
  - one request per token and kind per TOKEN_GAP_S (30 min); after an answer that filled what GeckoTerminal has (or an
    empty one, or no pool) DONE_GAP_S (6 h), unless the series has gone stale at its end (a token no job snapshots)
  - at most GRAF_PER_MIN (2) a minute from this process, each paced by kol/measure's GeckoTerminal throttle and the
    shared gate of event_calendar/http (the free API's pace across processes); nothing is sent while GeckoTerminal is
    paused after a 429 / 403 or held by another job (http.cooling)
  - with the CoinGecko key the calls count for the job "graf" (http.cg_job_as): per job in the day file and in the
    daily cost line (usage/daily); "graf" is not a live job, so it stops before the live jobs' share of the hour
  - every token the owner opens is filled, under 30k too (CLAUDE.md 11.11.: such tokens may be analysed and measured,
    and bought by hand); the cost is bounded by the caps above, not by the token
The pool: range.db pools, else the pair of the shared DexScreener row (ui/prijedlog.live_market), else kol.db tokens,
else one free DexScreener request in the worker.
"""
import math
import os
import sqlite3
import threading
import time

M1_SPAN_S = 998 * 60          # one minute request (GeckoTerminal: 1000 candles), as rangedca/data.seed
H1_SPAN_S = 168 * 3600        # one hour request: 7 days (the 1h view's window)
SPAN_S = {"m1": M1_SPAN_S, "h1": H1_SPAN_S}
GRAF_DAY = int(os.environ.get("AP_GRAF_DAY", "60"))
GRAF_PER_MIN = max(1, int(os.environ.get("AP_GRAF_PER_MIN", "2")))
TOKEN_GAP_S = 1800
DONE_GAP_S = 6 * 3600
WAIT_GAP_S = 60               # GeckoTerminal was held by another job when the request was due: asked again after this
WANT_S = 120                  # a queued token nobody asked about for this long is dropped (the owner moved on)
QUEUE_MAX = 6
DAY_KEY = "graf_day"
JOB = "graf"
ENABLED = os.environ.get("AP_GRAF_FILL", "1") == "1"
MANUAL = False                # tests: the jobs wait in the queue for drain() instead of the worker thread

_LOCK = threading.Condition()
_QUEUE = {}                   # (mint, kind) -> {"asked": ts, "hint": pool or None, "why": reason}
_RUN = set()                  # (mint, kind) being fetched right now
_DONE = {}                    # (mint, kind) -> {"ts", "n", "err", "why"}
_SENT = []                    # time.monotonic() of the requests sent in the last minute
_WORKER = {"thread": None, "gen": 0}   # gen: reset() ends the running worker (tests)
_HOOKS = []                   # fn(mint) once new candles are stored (ui/apterm drops its cached series)

NOTES = {
    "dohvacam": "Dohvaćam povijest (GeckoTerminal)…",
    "ceka": "GeckoTerminal je trenutno zauzet: povijest dohvaćam čim se oslobodi.",
    "strop": "Današnji strop povijesti grafa ({cap} dohvata) je potrošen: prikazane su samo naše snimke.",
    "greska": "Povijest se nije dohvatila (GeckoTerminal); novi pokušaj za 30 min.",
    "nema_poola": "GeckoTerminal ne poznaje pool tokena: prikazane su samo naše snimke.",
}


def note(state):
    """The line under the chart for a fill state ("" when there is nothing to say)."""
    return NOTES.get(state, "").replace("{cap}", str(GRAF_DAY))


def need(step, hours, now, minutes, bars, born=None):
    """(kind, why) of the fill a chart view needs, else None. step / hours: the view's candle and window; minutes: the
    stored minute series of the window [(ts, ...)]; bars: what the chart would show [{time, ...}]; born: the pair's
    creation (unix s) or None. kind "h1" for the 1h view of a token older than one minute request reaches (or of unknown
    age), else "m1". why: "prazno" (nothing stored), "pocetak" (the series starts later than the window, the token's
    birth and what one request reaches allow, by more than a few candles), "kraj" (the newest stored data is older
    than max(30 min, 2 candles): nobody snapshots the token, the chart would jump from then to the live candle)."""
    kind = "h1" if step >= 3600 and (born is None or now - born > M1_SPAN_S) else "m1"
    if not minutes and not bars:
        return kind, "prazno"
    want_from = max(now - hours * 3600, born or 0, now - SPAN_S[kind])
    if kind == "m1":
        first = minutes[0][0] if minutes else bars[0]["time"]
        slack = max(600, 3 * min(step, 900))
    else:
        first = bars[0]["time"] if bars else minutes[0][0]
        slack = 3 * step
    if first - want_from > slack:
        return kind, "pocetak"
    last = max(minutes[-1][0] if minutes else 0, bars[-1]["time"] if bars and kind == "h1" else 0)
    if now - last > max(1800, 2 * step):
        return kind, "kraj"
    return None


# ---------- the day cap (range.db kv graf_day) ----------------------------------------------------------------------

def day_used(now=None):
    """Requests sent today (UTC day) for the chart, read-only; 0 when range.db does not exist yet."""
    from rangedca import data as rdata
    con = rdata.ro()
    if con is None:
        return 0
    try:
        return rdata.day_used(con, DAY_KEY, now or time.time())
    except sqlite3.Error:
        return 0
    finally:
        con.close()


def _charge(con, now):
    """One request from today's cap, atomically (another process may count too): True, or False when it is spent."""
    from rangedca import data as rdata
    con.execute("BEGIN IMMEDIATE")
    try:
        if rdata.day_used(con, DAY_KEY, now) >= GRAF_DAY:
            con.rollback()
            return False
        rdata.day_add(con, DAY_KEY, 1, now)
        con.commit()
        return True
    except Exception:
        con.rollback()
        raise


# ---------- asking (the request thread: bookkeeping only) ----------------------------------------------------------

def _cooling():
    try:
        from event_calendar import http
        from kol import measure
        return http.cooling(measure.GECKO)
    except Exception:  # noqa: BLE001
        return 0.0


def request(mint, kind, why, now=None, hint=None, bg=True):
    """Ask for a fill of (mint, kind); never fetches here. Returns the state for the chart's JSON: "dohvacam" (queued
    or running), "nedavno" (filled lately: what GeckoTerminal had is shown), "greska" / "nema_poola" (the last try
    failed: asked again after its gap), "strop" (today's cap is spent), "ceka" (GeckoTerminal is paused or held by
    another job: the next poll asks again), "iskljuceno" (off: AP_GRAF_FILL=0, or no background thread, as in tests)."""
    now = now or time.time()
    if not ENABLED or not (bg or MANUAL):
        return "iskljuceno"
    key = (mint, kind)
    with _LOCK:
        if key in _QUEUE:
            _QUEUE[key]["asked"] = now
            return "dohvacam"
        if key in _RUN:
            return "dohvacam"
        d = _DONE.get(key)
    if d:
        err = d.get("err")
        gap = {"greska": TOKEN_GAP_S, "ceka": WAIT_GAP_S, "nema_poola": DONE_GAP_S, "strop": WAIT_GAP_S}.get(err)
        if gap is None:   # a stale end is topped up every 30 min; a start GeckoTerminal has no more of waits 6 h, as
            gap = TOKEN_GAP_S if why == "kraj" and d.get("fresh") else DONE_GAP_S   # does a token that stopped trading
        if now - d["ts"] < gap:
            return err if err in ("greska", "nema_poola", "ceka") else "nedavno"
    if day_used(now) >= GRAF_DAY:
        return "strop"
    if _cooling() > 0:
        return "ceka"
    with _LOCK:
        if len(_QUEUE) >= QUEUE_MAX:   # the newest ask is what the owner looks at: the oldest one makes room
            _QUEUE.pop(min(_QUEUE, key=lambda k: _QUEUE[k]["asked"]), None)
        _QUEUE[key] = {"asked": now, "hint": hint, "why": why}
        _LOCK.notify_all()
    if bg and not MANUAL:
        _start()
    return "dohvacam"


def on_store(fn):
    if fn not in _HOOKS:
        _HOOKS.append(fn)


# ---------- the worker ----------------------------------------------------------------------------------------------

def _start():
    with _LOCK:
        t = _WORKER["thread"]
        if t is not None and t.is_alive():
            return
        t = threading.Thread(target=_loop, daemon=True, name="autopilot-graf")
        _WORKER["thread"] = t
    t.start()


def _loop():
    gen = _WORKER["gen"]
    while _WORKER["gen"] == gen:
        try:
            r = step()
            if r is False:
                with _LOCK:
                    if not _QUEUE and _WORKER["gen"] == gen:
                        _LOCK.wait(30)
            elif r is not True:
                time.sleep(r)
        except Exception as e:  # noqa: BLE001 - one bad token never stops the chart's history
            print(f"graf: {type(e).__name__}: {e}"[:200], flush=True)
            time.sleep(5)


def _take(now):
    with _LOCK:
        for k in [k for k, j in _QUEUE.items() if now - j["asked"] > WANT_S]:
            _QUEUE.pop(k, None)
        if not _QUEUE:
            return None
        key = max(_QUEUE, key=lambda k: _QUEUE[k]["asked"])
        job = _QUEUE.pop(key)
        _RUN.add(key)
        return key, job


def _pace_wait():
    """Seconds until this process may send another request (at most GRAF_PER_MIN in any 60 s); 0 = now."""
    mono = time.monotonic()
    with _LOCK:
        _SENT[:] = [t for t in _SENT if mono - t < 60]
        return 0.0 if len(_SENT) < GRAF_PER_MIN else max(0.5, 60 - (mono - _SENT[0]))


def _sent():
    with _LOCK:
        _SENT.append(time.monotonic())


def step(now=None):
    """One queued fill, the most recently asked token first. True when one ran, False when the queue is empty, or the
    seconds to wait when this minute's requests are spent (the jobs stay queued)."""
    wait = _pace_wait()
    if wait:
        with _LOCK:
            return wait if _QUEUE else False
    now = now or time.time()
    got = _take(now)
    if got is None:
        return False
    key, job = got
    try:
        res = _fill(key[0], key[1], job, now)
    except Exception as e:  # noqa: BLE001
        print(f"graf: {key[0][:6]} {key[1]}: {type(e).__name__}: {e}"[:200], flush=True)
        res = {"n": 0, "err": "greska"}
    with _LOCK:
        _RUN.discard(key)
        _DONE[key] = {"ts": now, "n": res.get("n", 0), "err": res.get("err"), "why": job.get("why"),
                      "fresh": bool(res.get("newest") and now - res["newest"] <= TOKEN_GAP_S)}
        if len(_DONE) > 200:
            for k in sorted(_DONE, key=lambda k: _DONE[k]["ts"])[:100]:
                _DONE.pop(k, None)
    return True


def drain(now=None):
    """Run the queued fills now, as far as this minute's pace allows (tests; MANUAL). Returns how many ran."""
    n = 0
    while step(now) is True:
        n += 1
    return n


def _fill(mint, kind, job, now):
    from rangedca import data as rdata
    pool = _pool(mint, job.get("hint"))
    if not pool:
        return {"n": 0, "err": "nema_poola"}
    if _cooling() > 0:
        return {"n": 0, "err": "ceka"}
    con = rdata.connect()
    try:
        if not _charge(con, now):
            return {"n": 0, "err": "strop"}
        start, end = int(now - SPAN_S[kind]), int(now)
        _sent()
        from event_calendar import http
        try:
            with http.cg_job_as(JOB):
                rows = FETCH[kind](pool, start, end)
        except Exception as e:  # noqa: BLE001 - 429 / 403 / timeout: http already paused GeckoTerminal for everyone
            print(f"graf: GeckoTerminal za {mint[:6]} ({kind}): {type(e).__name__} {getattr(e, 'code', '')}", flush=True)
            # 404: GeckoTerminal does not know the pool (asked again in 6 h, not every 30 min)
            return {"n": 0, "err": "nema_poola" if getattr(e, "code", None) == 404 else "greska"}
        if rows is None:   # another job holds GeckoTerminal right now (http.reserve)
            return {"n": 0, "err": "ceka"}
        n = 0
        if rows:
            con.execute("BEGIN IMMEDIATE")   # the range job may store the same token's seed: one read-modify-write
            try:
                n = (rdata.store_gt if kind == "m1" else rdata.store_hours)(con, mint, pool, rows, now)
                con.commit()
            except Exception:
                con.rollback()
                raise
        used = rdata.day_used(con, DAY_KEY, now)
    finally:
        con.close()
    print(f"graf: {mint[:6]} {'minutne' if kind == 'm1' else 'satne'} svijeće s GeckoTerminala: {len(rows)} "
          f"({job.get('why')}), danas {used}/{GRAF_DAY}", flush=True)
    if rows:
        for fn in list(_HOOKS):
            try:
                fn(mint)
            except Exception:  # noqa: BLE001
                pass
    return {"n": len(rows), "err": None, "stored": n, "newest": int(rows[-1][0]) if rows else None}


# ---------- the pool and the requests -------------------------------------------------------------------------------

def _pool(mint, hint=None):
    """range.db pools (the range job's pool, so gt_candles keeps one pool), else the shared DexScreener row's pair,
    else kol.db tokens, else one DexScreener request (free)."""
    from rangedca import data as rdata
    con = rdata.ro()
    if con is not None:
        try:
            r = con.execute("SELECT pool FROM pools WHERE token=?", (mint,)).fetchone()
            if r and r[0]:
                return r[0]
        except sqlite3.Error:
            pass
        finally:
            con.close()
    if hint:
        return hint
    try:
        from kol import store as kstore
        kc = rdata._ro_file(kstore.DB)
        if kc is not None:
            try:
                r = kc.execute("SELECT pair FROM tokens WHERE token=?", (mint,)).fetchone()
                if r and r[0]:
                    return r[0]
            finally:
                kc.close()
    except Exception:  # noqa: BLE001
        pass
    return POOL_LOOKUP(mint)


def dex_pool(mint):
    """The deepest DexScreener pair of the token (its address is GeckoTerminal's pool), else None."""
    try:
        from dexscreener import client
        pairs = [p for p in client.tokens("solana", [mint]) or [] if (p.get("baseToken") or {}).get("address") == mint]
    except Exception:  # noqa: BLE001
        return None
    if not pairs:
        return None
    return max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0).get("pairAddress")


def fetch_minutes(pool, start, end):
    """[(ts, o, h, l, c, v)] 1-minute candles (kol/minute.minutes: its pacing and the shared GeckoTerminal gate)."""
    from kol import minute
    return minute.minutes(pool, start, end)


def fetch_hours(pool, start, end):
    """[(ts, o, h, l, c, v)] 1-hour candles covering start..end, oldest first; None when another job holds
    GeckoTerminal (as kol/minute.minutes)."""
    from event_calendar import http
    from kol import measure
    limit = max(2, min(1000, math.ceil((end - start) / 3600) + 2))
    measure._GT.wait()
    d = http.get_json(f"{measure.GECKO}/pools/{pool}/ohlcv/hour",
                      {"aggregate": 1, "before_timestamp": int(end) + 3600, "limit": limit, "currency": "usd"},
                      ttl=600, headers={"Accept": "application/json"}, retries=0)
    if d is None:
        return None
    rows = (d.get("data") or {}).get("attributes", {}).get("ohlcv_list") or []
    return sorted((int(r[0]), *map(float, r[1:6])) for r in rows)


FETCH = {"m1": fetch_minutes, "h1": fetch_hours}   # tests replace them (no network)
POOL_LOOKUP = dex_pool


def reset():
    """Forget the queue and the history of fills (tests; a deploy starts empty anyway). The day cap stays in range.db."""
    with _LOCK:
        _QUEUE.clear()
        _RUN.clear()
        _DONE.clear()
        _SENT.clear()
        _WORKER["gen"] += 1
        _WORKER["thread"] = None
        _LOCK.notify_all()
