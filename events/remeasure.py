"""Night: calls that were never measured, or whose minute check found no trade (bad:svijeca), measured from minute
candles, so every caller's score rests on as many measured calls as we can afford (11.11., Jure, point 3).

Which calls (the measure_status of get_caller_history): real calls (kind 'call', no wallet pseudo-calls, no alert
bots) 25 h to 30 days old with
  never_measured   kol.db: no 24 h result, not given up (bad), never measured (measured_ts, p0 empty)
  bad:svijeca      minute.db call_path: no trade within 5 min of the call
and no final row in events.db call_outcomes yet. Order: callers with few measured calls first (fewer than 5, then
fewer than 20, then the rest), the newest first inside each group; one token = one or two requests for all its calls
within 16 h.

How: the pool from events.db pools, else kol.db tokens.pair, else DexScreener (free, 30 tokens a request), else
GeckoTerminal's token pools (one request); then GeckoTerminal 1-minute candles from 10 min before the first call to
16 h after it (1000 candles, one request) and, for calls older than 24 h, 5-minute candles 16-24 h after it (one
more). Entry = the close of the call's minute, else the open of the first candle within ENTRY_LATE_MIN (the minute
check allows 5; here a later entry is taken and the reason says by how much). The outcome (events/outcomes.metrics)
goes to call_outcomes with src gt_minute and status ok, or unavailable with the reason: nema poola, nema svijeća,
ispod 30k, ulaz nakon N min.

Spend (CLAUDE.md: izmjeri prije troška): GeckoTerminal is shared with the whole bot (event_calendar/http.py; with the
CoinGecko key every request counts against the paid day of CG_DAILY_CALLS, 3000). At most NIGHT_CAP requests a night
(kv remeasure_night), and with the key never past half of the day's calls (the day starts at 00 UTC: the night must
not eat the day's budget). Birdeye only when BIRDEYE_API_KEY is set (BIRDEYE_NIGHT_CAP), as the fallback for tokens
GeckoTerminal has no candles for. No Helius here.
"""
import datetime as dt
import json
import os
import sqlite3
import time
import urllib.request

from events import outcomes, sources, store

NIGHT_CAP = int(store._env_num("REMEASURE_NIGHT_CAP", 600))
BIRDEYE_NIGHT_CAP = int(store._env_num("BIRDEYE_NIGHT_CAP", 100))
MIN_AGE_S = 25 * 3600
MAX_AGE_D = 30
SPAN_S = 16 * 3600
ENTRY_LATE_MIN = 30
BUDGET_S = 1800
TZ = "Europe/Zagreb"


def night_key(now):
    from zoneinfo import ZoneInfo
    return dt.datetime.fromtimestamp(now, ZoneInfo(TZ)).date().isoformat()


def used(econ, now, key="remeasure_night"):
    d = store.kv_get(econ, key) or {}
    return int(d.get("n") or 0) if d.get("day") == night_key(now) else 0


def _spend(econ, now, n, key="remeasure_night"):
    store.kv_put(econ, key, {"day": night_key(now), "n": used(econ, now, key) + n})
    econ.commit()


def cap_left(econ, now, cap=NIGHT_CAP):
    """Requests this night may still make: the night cap minus what was used, and with the CoinGecko key never past
    half of the paid day."""
    left = cap - used(econ, now)
    try:
        from event_calendar import http
        if http.cg_key():
            day_cap = int(float(os.environ.get("CG_DAILY_CALLS", "3000")))
            left = min(left, day_cap // 2 - http.cg_used())
    except Exception:  # noqa: BLE001
        pass
    return max(0, left)


def queue(kcon, mcon, econ, now, limit=2000):
    """[(token, [(tweet_id, handle, ts, why)])] in the order of the module text."""
    lo, hi = now - MAX_AGE_D * 86400, now - MIN_AGE_S
    try:
        bots = {h for (h,) in kcon.execute("SELECT handle FROM kols WHERE COALESCE(bot, 0) = 1")}
    except sqlite3.Error:
        bots = set()
    calls = {}
    try:
        for tid, tok, h, ts in kcon.execute(
                "SELECT tweet_id, token, handle, ts FROM calls WHERE kind = 'call' AND handle NOT LIKE 'w:%' "
                "AND COALESCE(source, '') != 'chain' AND r24h IS NULL AND COALESCE(bad, '') = '' "
                "AND measured_ts IS NULL AND p0 IS NULL AND ts BETWEEN ? AND ?", (lo, hi)):
            if h not in bots:
                calls[(tid, tok)] = (h, ts, "never_measured")
    except sqlite3.Error:
        pass
    if mcon is not None:
        try:
            for tid, tok, h, ts in mcon.execute("SELECT tweet_id, token, handle, ts FROM call_path WHERE bad = 'svijeca' "
                                                "AND ts BETWEEN ? AND ?", (lo, hi)):
                if h not in bots:
                    calls.setdefault((tid, tok), (h, ts, "bad:svijeca"))
        except sqlite3.Error:
            pass
    if not calls:
        return []
    done = set()
    tids = sorted({t for t, _ in calls})
    for i in range(0, len(tids), 400):
        part = tids[i:i + 400]
        done |= {(t, m) for t, m in econ.execute(
            f"SELECT tweet_id, mint FROM call_outcomes WHERE tweet_id IN ({','.join('?' * len(part))}) "
            f"AND {outcomes.FINAL}", part)}
    measured = {}
    try:
        measured = dict(kcon.execute("SELECT handle, COUNT(*) FROM calls WHERE kind = 'call' AND r24h IS NOT NULL "
                                     "AND ts >= ? GROUP BY handle", (lo,)).fetchall())
    except sqlite3.Error:
        pass
    by = {}
    for (tid, tok), (h, ts, why) in calls.items():
        if (tid, tok) in done:
            continue
        n = measured.get(h, 0)
        prio = 0 if n < 5 else 1 if n < 20 else 2
        g = by.setdefault(tok, {"prio": prio, "ts": ts, "calls": []})
        g["prio"], g["ts"] = min(g["prio"], prio), max(g["ts"], ts)
        g["calls"].append((tid, h, ts, why))
    order = sorted(by.items(), key=lambda kv: (kv[1]["prio"], -kv[1]["ts"]))[:limit]
    out = []
    for tok, g in order:
        cs = sorted(g["calls"], key=lambda c: c[2])
        t0 = cs[0][2]
        out.append((tok, [c for c in cs if c[2] <= t0 + SPAN_S]))
    return out


# ---------- fetching (each one counted) -----------------------------------------------------------------------------

class Budget:
    def __init__(self, n):
        self.left, self.used = n, 0

    def take(self):
        if self.left <= 0:
            return False
        self.left -= 1
        self.used += 1
        return True


def gt_candles(pool, end, limit, aggregate=1):
    """[(ts, o, h, l, c, v)] from GeckoTerminal (the bot's shared limiter), None when another job holds it."""
    from event_calendar import http
    from kol import measure
    measure._GT.wait()
    d = http.get_json(f"{measure.GECKO}/pools/{pool}/ohlcv/minute",
                      {"aggregate": aggregate, "before_timestamp": int(end), "limit": int(limit), "currency": "usd"},
                      ttl=3600, headers={"Accept": "application/json"}, retries=0)
    if d is None:
        return None
    rows = (d.get("data") or {}).get("attributes", {}).get("ohlcv_list") or []
    return sorted((int(r[0]), *map(float, r[1:6])) for r in rows)


def birdeye_candles(token, start, end):
    """Birdeye 1-minute OHLCV (only with BIRDEYE_API_KEY); [] on any error."""
    key = os.environ.get("BIRDEYE_API_KEY")
    if not key:
        return []
    url = (f"https://public-api.birdeye.so/defi/ohlcv?address={token}&type=1m&time_from={int(start)}"
           f"&time_to={int(end)}")
    req = urllib.request.Request(url, headers={"X-API-KEY": key, "x-chain": "solana", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            items = (json.loads(r.read().decode()).get("data") or {}).get("items") or []
    except Exception:  # noqa: BLE001
        return []
    return sorted((int(i["unixTime"]), float(i["o"]), float(i["h"]), float(i["l"]), float(i["c"]),
                   float(i.get("v") or 0)) for i in items if i.get("unixTime"))


def dex_pools(tokens):
    """{token: (pair address, supply)} from DexScreener (free), the most liquid pair of each token."""
    from dexscreener import client
    want, best = set(tokens), {}
    for p in client.tokens("solana", list(tokens)):
        t = (p.get("baseToken") or {}).get("address")
        if t not in want:
            continue
        liq = (p.get("liquidity") or {}).get("usd") or 0
        if t not in best or liq >= ((best[t].get("liquidity") or {}).get("usd") or 0):
            best[t] = p
    out = {}
    for t, p in best.items():
        price = float(p.get("priceUsd") or 0)
        mc = p.get("marketCap") or p.get("fdv") or 0
        out[t] = (p.get("pairAddress"), mc / price if price and mc else None)
    return out


def gt_pool(token):
    from kol import measure
    p = measure.gecko_pool(token)
    return (p["address"], None) if p else None


# ---------- the pass ------------------------------------------------------------------------------------------------

def _pools(econ, kcon, toks, fetch_dex, fetch_gt_pool, budget, now):
    out = {t: (p, s) for t, p, s in econ.execute(
        f"SELECT token, pool, supply FROM pools WHERE token IN ({','.join('?' * len(toks))})", toks)} if toks else {}
    need = [t for t in toks if t not in out]
    if need and kcon is not None:
        for i in range(0, len(need), 400):
            part = need[i:i + 400]
            try:
                for t, pair, sup in kcon.execute(f"SELECT token, pair, supply FROM tokens WHERE pair IS NOT NULL AND "
                                                 f"token IN ({','.join('?' * len(part))})", part):
                    out[t] = (pair, sup)
            except sqlite3.Error:
                break
    need = [t for t in toks if t not in out]
    if need:
        try:
            out.update({t: v for t, v in fetch_dex(need).items() if v and v[0]})
        except Exception:  # noqa: BLE001 - DexScreener down: GeckoTerminal below
            pass
    tried = set(out)
    for t in [t for t in toks if t not in out]:
        if not budget.take():
            break
        tried.add(t)
        try:
            v = fetch_gt_pool(t)
        except Exception:  # noqa: BLE001
            v = None
        if v and v[0]:
            out[t] = v
    rows = [(t, p, s, now) for t, (p, s) in out.items() if p]
    econ.executemany("INSERT OR REPLACE INTO pools VALUES (?,?,?,?)", rows)
    return out, tried


def measure_token(tok, calls, pool, supply, now, fetch, budget, fetch_bird=None, bird=None):
    """[call_outcomes rows] of one token's calls; None when the requests ran out or GeckoTerminal is held by another
    job (the calls stay in the queue). A minute without a candle had no trade, so a request covers its whole window
    (the horizon is the window's end, not the last candle)."""
    t0 = min(c[2] for c in calls)
    t_last = max(c[2] for c in calls)
    c1, c5, horizon, src = [], [], None, "gt_minute"
    if pool:
        if not budget.take():
            return None
        end1 = min(now, t0 + SPAN_S)
        try:
            got = fetch(pool, end1, 1000, 1)
        except Exception:  # noqa: BLE001 - 429 / network: stop the pass, the calls stay queued
            return None
        if got is None:
            return None
        c1, horizon = [c for c in got if c[0] >= t0 - 600], end1
        if c1 and now >= t_last + 24 * 3600 + 300 and budget.take():
            end5 = min(now, t_last + 24 * 3600 + 600)
            n5 = int((end5 - (t0 + SPAN_S - 300)) // 300) + 2
            try:
                got5 = fetch(pool, end5, max(2, min(1000, n5)), 5)
            except Exception:  # noqa: BLE001 - the 24 h part stays unknown
                got5 = None
            if got5 is not None:
                c5, horizon = [c for c in got5 if c[0] >= t0 + SPAN_S - 300], end5
    if not c1 and fetch_bird and bird is not None and bird.take():
        end = min(now, t_last + 24 * 3600 + 600)
        c1 = fetch_bird(tok, t0 - 600, end) or []
        horizon, src = (end, "birdeye_minute") if c1 else (horizon, src)
    pts = outcomes.points_from_candles(c1) + [(c[0] + 300, min(c[2], max(c[1], c[4]) * outcomes.WICK_X), c[3], c[4])
                                              for c in c5]
    pts.sort()
    rows = []
    for tid, h, ts, why in calls:
        base = (store.uid(f"call|{tid}|{tok}"), "call", tok, h, "telegram" if h.startswith("tg:") else "x", ts, tid)
        empty = (None, None) + (None,) * 7
        if not pool and not c1:
            rows.append(base + empty + ("unavailable", "nema poola", src, now))
            continue
        e = outcomes.entry_from_candles([c for c in c1 if ts - 600 <= c[0] <= ts + 3600], ts,
                                        within_s=ENTRY_LATE_MIN * 60)
        if not e:
            rows.append(base + empty + ("unavailable", f"nema trgovanja do {ENTRY_LATE_MIN} min nakon poziva", src,
                                        now))
            continue
        late = max(0, (e[1] - (ts - ts % 60 + 60)) // 60)
        mcap0 = e[0] * supply if supply else None
        m = outcomes.metrics([p for p in pts if p[0] <= ts + 25 * 3600], e[1], e[0], horizon or e[1])
        if mcap0 is not None and mcap0 < store.MIN_MCAP:
            st, reason = "unavailable", "ispod 30k"
        elif m["max_4h"] is None:
            st, reason = "unavailable", "svijeće ne pokrivaju 4 h"
        else:
            st, reason = "ok", (f"ulaz nakon {late} min" if late > 5 else None)
        rows.append(base + (mcap0, e[0], m["max_1h"], m["max_4h"], m["max_24h"], m["min_before_max"], m["change_4h"],
                            m["change_24h"], m["ev"], st, reason, src, now))
    return rows


def run(econ=None, now=None, cap=None, log=print, fetch=None, fetch_dex=None, fetch_gt_pool=None, fetch_bird=None,
        force=False, deadline_s=BUDGET_S):
    """One capped night pass. Returns {"tokens", "calls", "ok", "unavailable", "requests", "left_in_queue", "why"}."""
    from ops import heavy
    now = int(now or time.time())
    if not force and not heavy.night_now(dt.datetime.fromtimestamp(now, dt.timezone.utc)):
        return {"why": "izvan noćnog prozora", "requests": 0}
    own = econ is None
    econ = econ or store.connect()
    kcon, mcon = sources._ro(sources.db_paths()["kol"]), outcomes._minute_ro()
    try:
        if kcon is None:
            return {"why": "nema kol.db", "requests": 0}
        left = cap_left(econ, now, NIGHT_CAP if cap is None else cap)
        if left <= 0:
            return {"why": "noćni strop zahtjeva potrošen", "requests": 0}
        q = queue(kcon, mcon, econ, now)
        if not q:
            return {"why": "nema neizmjerenih poziva", "requests": 0}
        live = fetch is None
        fetch = fetch or gt_candles
        if live:
            from event_calendar import http
            from kol import measure
            if http.cooling(measure.GECKO) > 30:
                return {"why": "GeckoTerminal je zauzet (drugi posao ili 429)", "requests": 0}
            http.reserve(measure.GECKO, deadline_s)
        budget = Budget(left)
        bird = Budget(BIRDEYE_NIGHT_CAP if os.environ.get("BIRDEYE_API_KEY") or fetch_bird else 0)
        stop_at = time.monotonic() + deadline_s
        rows, n_tok, why = [], 0, ""
        try:
            toks = [t for t, _ in q]
            pools = {}
            for i in range(0, len(toks), 30):   # pools in chunks as the queue is worked through
                if budget.left <= 0 or time.monotonic() > stop_at:
                    break
                chunk = toks[i:i + 30]
                found, tried = _pools(econ, kcon, chunk, fetch_dex or dex_pools, fetch_gt_pool or gt_pool, budget, now)
                pools.update(found)
                for tok, calls in q[i:i + 30]:
                    if time.monotonic() > stop_at:
                        why = "vremenski strop"
                        break
                    if tok not in tried:   # its pool was never looked for (the requests ran out): stays queued
                        why = why or "strop zahtjeva"
                        continue
                    pool, sup = pools.get(tok, (None, None))
                    r = measure_token(tok, calls, pool, sup, now, fetch, budget, fetch_bird or birdeye_candles, bird)
                    if r is None:
                        why = why or ("strop zahtjeva" if budget.left <= 0 else "GeckoTerminal zauzet")
                        break
                    rows += r
                    n_tok += 1
                if why:
                    break
        finally:
            if live:
                from event_calendar import http
                from kol import measure
                http.release(measure.GECKO)
        econ.executemany("INSERT OR REPLACE INTO call_outcomes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        econ.commit()
        _spend(econ, now, budget.used)
        if bird.used:
            _spend(econ, now, bird.used, "birdeye_night")
        ok = sum(1 for r in rows if r[16] == "ok")
        out = {"tokens": n_tok, "calls": len(rows), "ok": ok, "unavailable": len(rows) - ok, "requests": budget.used,
               "birdeye": bird.used, "left_in_queue": max(0, len(q) - n_tok), "why": why}
        log(f"događaji: mjerenje neizmjerenih poziva: {n_tok} tokena, {len(rows)} poziva (ok {ok}, nedostupno "
            f"{len(rows) - ok}); GeckoTerminal {budget.used} zahtjeva, noćas {used(econ, now)}/{NIGHT_CAP}"
            + (f", Birdeye {bird.used}" if bird.used else "") + f"; u redu još {out['left_in_queue']} tokena"
            + (f" ({why})" if why else ""))
        return out
    finally:
        for c in (kcon, mcon):
            if c is not None:
                c.close()
        if own:
            econ.close()
