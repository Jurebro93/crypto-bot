"""What the price and volume did around each call, from GeckoTerminal 5-minute candles (free, no key).

One OHLCV request per token covers all its calls: from 2 h before the first call to 24 h after the last one.
A call is complete once 24 h have passed and been measured; until then it is re-measured at most hourly.
"""
import math
import os
import threading
import time

from event_calendar import http

GECKO = "https://api.geckoterminal.com/api/v2/networks/solana"
CANDLE = 300  # 5-min candles; 1000 per request = 3.5 days of calls per token
H = 3600


class _Throttle:
    def __init__(self, gap):
        self.gap, self.last, self.lock = gap, 0.0, threading.Lock()

    def wait(self):
        with self.lock:
            d = self.last + self.gap - time.monotonic()
            if d > 0:
                time.sleep(d)
            self.last = time.monotonic()


_GT = _Throttle(float(os.environ.get("KOL_GECKO_GAP", "3.0")))  # free API: ~30 requests per minute, shared per IP


GECKO_POOL_LOOKUPS = int(os.environ.get("KOL_GECKO_POOL_LOOKUPS", "10"))  # per resolve round, free API


def gecko_pool(token):
    """Most liquid pool of a token on GeckoTerminal ({address, symbol, name, created, liquidity}) or None."""
    import datetime as dt
    _GT.wait()
    try:
        d = http.get_json(f"{GECKO}/tokens/{token}/pools", {}, ttl=3600, headers={"Accept": "application/json"},
                          retries=0)
    except Exception:  # noqa: BLE001  (404 = unknown token, 429 = busy: the normal retry count handles both)
        return None
    pools = (d or {}).get("data") or []
    if not pools:
        return None
    a = max(pools, key=lambda x: float((x.get("attributes") or {}).get("reserve_in_usd") or 0)).get("attributes") or {}
    name = a.get("name") or ""
    created = None
    try:
        created = int(dt.datetime.fromisoformat(a["pool_created_at"].replace("Z", "+00:00")).timestamp())
    except (KeyError, TypeError, ValueError, AttributeError):
        pass
    return {"address": a.get("address"), "symbol": name.split(" / ")[0][:20] or None, "name": name[:80],
            "created": created, "liquidity": float(a.get("reserve_in_usd") or 0)} if a.get("address") else None


def resolve(con, tokens, now=None):
    """Most liquid Solana pair and supply per token, from DexScreener (30 tokens per request)."""
    from dexscreener import client
    now = now or int(time.time())
    if not tokens:
        return 0
    best = {}
    for p in client.tokens("solana", list(tokens)):
        t = (p.get("baseToken") or {}).get("address")
        if t in tokens and ((p.get("liquidity") or {}).get("usd") or 0) >= ((best.get(t, {}).get("liquidity") or {}).get("usd") or 0):
            best[t] = p
    gecko_left = GECKO_POOL_LOOKUPS
    for t in tokens:
        p = best.get(t)
        if not p and gecko_left > 0 and http.cooling(GECKO) <= 30:
            # DexScreener drops dead tokens; GeckoTerminal often still has the pool and its old candles (a token
            # that pumped and died months ago is exactly the history we want to measure)
            gecko_left -= 1
            pool = gecko_pool(t)
            if pool:
                con.execute("INSERT OR REPLACE INTO tokens VALUES (?,?,?,?,?,?,?,0,?)",
                            (t, pool.get("symbol"), pool.get("name"), pool["address"], None, pool.get("created"),
                             pool.get("liquidity"), now))
                continue
        if not p:
            con.execute("INSERT INTO tokens (token, tries, updated) VALUES (?,1,?) ON CONFLICT (token) DO UPDATE SET "
                        "tries=tries+1, updated=excluded.updated", (t, now))
            continue
        price = float(p.get("priceUsd") or 0)
        mcap = p.get("marketCap") or p.get("fdv") or 0
        con.execute("INSERT OR REPLACE INTO tokens VALUES (?,?,?,?,?,?,?,0,?)",
                    (t, p["baseToken"].get("symbol"), p["baseToken"].get("name"), p.get("pairAddress"),
                     mcap / price if price else None, (p.get("pairCreatedAt") or 0) // 1000 or None,
                     (p.get("liquidity") or {}).get("usd"), now))
    return len(best)


def ohlcv(pool, start, end):
    """[(ts, open, high, low, close, volume_usd)] oldest first, 5-min candles covering start..end (newest 1000)."""
    limit = max(2, min(1000, math.ceil((end - start) / CANDLE) + 2))
    _GT.wait()
    d = http.get_json(f"{GECKO}/pools/{pool}/ohlcv/minute",
                      {"aggregate": CANDLE // 60, "before_timestamp": int(end) + CANDLE, "limit": limit, "currency": "usd"},
                      ttl=600, headers={"Accept": "application/json"}, retries=1)
    rows = ((d or {}).get("data") or {}).get("attributes", {}).get("ohlcv_list") or []
    return sorted((int(r[0]), *map(float, r[1:6])) for r in rows)


def price_at(candles, t):
    """Close of the last candle that started at or before t (no candle = no trade = price unchanged)."""
    last = None
    for c in candles:
        if c[0] > t:
            break
        last = c[4]
    return last


def outcome(candles, ts, now, cfg):
    """Price path of one call. Returns a dict of the measured columns (missing ones are None)."""
    if not candles:
        return None
    # price just before the tweet: close of the previous candle, or the open of the first one for a new token
    p0 = price_at(candles, ts - CANDLE) or (candles[0][1] if candles[0][0] <= ts + CANDLE else None)
    if not p0:
        return None
    first = candles[0][0]
    before = price_at(candles, ts - 2 * H)
    if before is None and first < ts:  # token younger than 2 h at the call: compare with its first trade
        before = candles[0][1]
    o = {"p0": p0, "pre2h": (p0 / before - 1) if before else None}
    for k, h in (("r1h", 1), ("r6h", 6), ("r24h", 24)):
        o[k] = (price_at(candles, ts + h * H) / p0 - 1) if now >= ts + h * H and price_at(candles, ts + h * H) else None
    after = [c for c in candles if ts < c[0] + CANDLE and c[0] <= ts + 24 * H]
    # one dust print can put a candle's high far above where it opened and closed (1.11.: a "65x" call on a $143
    # pool); a wick counts only up to wick_x times the candle body
    wick = (cfg.get("valid") or {}).get("wick_x", 3.0)
    o["max24"] = (max(min(c[2], max(c[1], c[4]) * wick) for c in after) / p0 - 1) if after else None
    o["vol_before"] = sum(c[5] for c in candles if ts - H <= c[0] < ts - CANDLE + 1)
    o["vol_after"] = sum(c[5] for c in candles if ts - CANDLE < c[0] <= ts + H - CANDLE) if now >= ts + H else None
    if o["vol_after"] is not None:
        o["vol_lift"] = min(50.0, o["vol_after"] / max(o["vol_before"], 50.0))
    else:
        o["vol_lift"] = None
    last = o["r24h"] if o["r24h"] is not None else o["r6h"]
    o["rug"] = int(last is not None and last <= cfg["rug_x"])
    o["complete"] = int(now >= ts + 24 * H + CANDLE)
    return o


MVER = 2  # 2 = wick cap + market-cap check (1.11.); older rows with a huge max24 are measured again once


def why_bad(mcap0, max24, cfg):
    """Why a measured call cannot be trusted, or None. A market cap of a few hundred dollars at the call is a dust
    pool (rugged, or not trading yet): any multiple from there is noise, not the KOL's doing."""
    v = cfg.get("valid") or {}
    if mcap0 is not None and mcap0 < v.get("min_mcap0", 3000):
        return "mcap"
    if max24 is not None and max24 >= v.get("max_x", 200):
        return "skok"
    return None


def revalidate(con, cfg):
    """Apply why_bad to rows measured before it existed; queue old huge moves for one more (wick-capped) measure."""
    v = cfg.get("valid") or {}
    n = con.execute("""UPDATE calls SET bad = 'mcap', pre2h = NULL, r1h = NULL, r6h = NULL, r24h = NULL, max24 = NULL,
        vol_lift = NULL, rug = NULL WHERE bad IS NULL AND mcap0 IS NOT NULL AND mcap0 < ?""",
                    (v.get("min_mcap0", 3000),)).rowcount
    n += con.execute("""UPDATE calls SET complete = 0, measured_ts = NULL WHERE bad IS NULL AND COALESCE(mver, 1) < ?
        AND max24 >= ?""", (MVER, v.get("remeasure_x", 9))).rowcount
    return n


LAG = 600  # GeckoTerminal candles show up a few minutes late: a checkpoint is measured 10 min after it passes
RETRY = 1200  # after a failed or empty fetch (API busy, no pair yet) the token waits 20 min


def due(con, now, limit):
    """Tokens with calls that need a measure now: never measured, or a checkpoint (1 h, 6 h, 24 h after the post)
    passed since the last measure. Real KOL calls first, then newest. Re-measuring every token every hour (before
    1.11.) asked GeckoTerminal for ~24 fetches per token a day; the free API (shared with other jobs) could not keep
    up, the newest calls took every slot and older ones never got their 1 h / 6 h / 24 h numbers."""
    marks = " OR ".join(f"(measured_ts < ts + {h * H} AND ts + {h * H + LAG} <= :now)" for h in (1, 6, 24))
    # 8.11.: wallet swaps ('w:' pseudo-calls, kind buy/sell) and alert-bot posts (kind 'bot') are never scored, yet
    # 487,235 of them waited in this queue while 39,743 of 40,772 Telegram calls had never been measured
    return [r[0] for r in con.execute(f"""
        SELECT token FROM calls WHERE complete = 0 AND COALESCE(mtry, 0) <= :now
          AND handle NOT LIKE 'w:%' AND kind NOT IN ('bot', 'buy', 'sell')
          AND (measured_ts IS NULL OR {marks} OR measured_ts < :now - 6 * {H})
        GROUP BY token ORDER BY MAX(kind = 'call') DESC, MAX(ts) DESC LIMIT :lim""", {"now": now, "lim": limit})]


def run(con, cfg, now=None, fetch=ohlcv, verbose=False):
    """Measure due calls. Returns (tokens measured, calls updated)."""
    now = now or int(time.time())
    stop_at = time.monotonic() + cfg.get("measure_budget_s", 480)
    toks = due(con, now, cfg["measure_tokens_per_run"])
    if fetch is ohlcv and toks:   # 9.11.: the free GeckoTerminal limit is ours for this budget (event_calendar/http.reserve)
        http.reserve(GECKO, cfg.get("measure_budget_s", 480))
    try:
        return _run(con, cfg, now, fetch, verbose, stop_at, toks)
    finally:
        if fetch is ohlcv:
            http.release(GECKO)


def _run(con, cfg, now, fetch, verbose, stop_at, toks):
    known = {r[0]: r[1:] for r in con.execute("SELECT token, pair, supply, tries FROM tokens")}
    unresolved = [t for t in toks if t not in known or (not known[t][0] and known[t][2] < 3)]
    if unresolved:
        try:
            resolve(con, unresolved, now)
        except Exception as e:
            print(f"  dexscreener: {type(e).__name__}: {e}")
        known = {r[0]: r[1:] for r in con.execute("SELECT token, pair, supply, tries FROM tokens")}
    n_tok = n_calls = 0
    for t in toks:
        pair, supply, tries = known.get(t, (None, None, 0))
        rows = con.execute("SELECT tweet_id, ts FROM calls WHERE token = ? AND complete = 0", (t,)).fetchall()
        if not pair:
            if tries >= 3:  # not a tradable Solana token (or a pair address in a link): stop trying
                con.execute("UPDATE calls SET complete = 1, measured_ts = ? WHERE token = ?", (now, t))
            else:
                con.execute("UPDATE calls SET mtry = ? WHERE token = ? AND complete = 0", (now + RETRY, t))
            continue
        if time.monotonic() > stop_at:  # leave the rest for the next round, so scoring and the rest of the cycle run
            break
        if fetch is ohlcv and http.cooling(GECKO) > 30:  # free limit used up (shared IP): snapshots cover it
            break
        start = min(ts for _, ts in rows) - 2 * H - CANDLE
        end = min(now, max(ts for _, ts in rows) + 24 * H + CANDLE)
        try:
            candles = fetch(pair, start, end)
        except Exception as e:
            if verbose:
                print(f"  gecko {t}: {type(e).__name__}: {e}")
            con.execute("UPDATE calls SET mtry = ? WHERE token = ? AND complete = 0", (now + RETRY, t))
            continue
        if not candles:  # busy API or no trades yet: try again soon instead of waiting for the next checkpoint
            con.execute("UPDATE calls SET mtry = ?, complete = (ts + 24 * ? + ? <= ?) WHERE token = ? AND complete = 0",
                        (now + RETRY, H, CANDLE, now, t))
            continue
        n_tok += 1
        from kol import sessions
        sessions.save_hours(con, t, candles, now)
        for tid, ts in rows:
            o = outcome(candles, ts, now, cfg)
            if not o:
                con.execute("UPDATE calls SET measured_ts = ?, complete = ? WHERE tweet_id = ? AND token = ?",
                            (now, int(now >= ts + 24 * H + CANDLE), tid, t))
                continue
            mcap0 = o["p0"] * supply if supply else None
            bad = why_bad(mcap0, o.get("max24"), cfg)
            if bad:  # keep the price at the call for the record, but no outcome that could count anywhere
                for k in ("pre2h", "r1h", "r6h", "r24h", "max24", "vol_lift", "rug"):
                    o[k] = None
            con.execute("""UPDATE calls SET p0=?, mcap0=?, pre2h=?, r1h=?, r6h=?, r24h=?, max24=?, vol_before=?,
                vol_after=?, vol_lift=?, rug=?, complete=?, measured_ts=?, bad=?, mver=?, msrc='gecko' WHERE tweet_id=? AND token=?""",
                        (o["p0"], mcap0, o["pre2h"], o["r1h"], o["r6h"], o["r24h"],
                         o["max24"], o["vol_before"], o["vol_after"], o["vol_lift"], o["rug"], o["complete"], now,
                         bad, MVER, tid, t))
            n_calls += 1
        con.commit()
    return n_tok, n_calls
