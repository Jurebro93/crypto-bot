"""What the price and volume did around each call, from GeckoTerminal 5-minute candles (free, no key).

One OHLCV request per token covers all its calls: from 2 h before the first call to 24 h after the last one.
A call is complete once 24 h have passed and been measured; until then it is re-measured at most hourly.
"""
import math
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


_GT = _Throttle(3.0)  # free API: 30 requests per minute


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
    for t in tokens:
        p = best.get(t)
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
                      ttl=600, headers={"Accept": "application/json"}, retries=4)
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
    o["max24"] = (max(c[2] for c in after) / p0 - 1) if after else None
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


def due(con, now, limit):
    """Tokens with calls that still need a (re)measure, newest calls first."""
    return [r[0] for r in con.execute("""
        SELECT token FROM calls WHERE complete = 0 AND (measured_ts IS NULL OR measured_ts < ?)
        GROUP BY token ORDER BY MAX(ts) DESC LIMIT ?""", (now - H, limit))]


def run(con, cfg, now=None, fetch=ohlcv, verbose=False):
    """Measure due calls. Returns (tokens measured, calls updated)."""
    now = now or int(time.time())
    toks = due(con, now, cfg["measure_tokens_per_run"])
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
                con.execute("UPDATE calls SET measured_ts = ? WHERE token = ? AND complete = 0", (now, t))
            continue
        start = min(ts for _, ts in rows) - 2 * H - CANDLE
        end = min(now, max(ts for _, ts in rows) + 24 * H + CANDLE)
        try:
            candles = fetch(pair, start, end)
        except Exception as e:
            if verbose:
                print(f"  gecko {t}: {type(e).__name__}: {e}")
            con.execute("UPDATE calls SET measured_ts = ? WHERE token = ? AND complete = 0", (now, t))
            continue
        n_tok += 1
        for tid, ts in rows:
            o = outcome(candles, ts, now, cfg)
            if not o:
                con.execute("UPDATE calls SET measured_ts = ?, complete = ? WHERE tweet_id = ? AND token = ?",
                            (now, int(now >= ts + 24 * H + CANDLE), tid, t))
                continue
            con.execute("""UPDATE calls SET p0=?, mcap0=?, pre2h=?, r1h=?, r6h=?, r24h=?, max24=?, vol_before=?,
                vol_after=?, vol_lift=?, rug=?, complete=?, measured_ts=? WHERE tweet_id=? AND token=?""",
                        (o["p0"], o["p0"] * supply if supply else None, o["pre2h"], o["r1h"], o["r6h"], o["r24h"],
                         o["max24"], o["vol_before"], o["vol_after"], o["vol_lift"], o["rug"], o["complete"], now,
                         tid, t))
            n_calls += 1
        con.commit()
    return n_tok, n_calls
