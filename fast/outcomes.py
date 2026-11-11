"""What the price did after every fast_check decision, bought or not (Jure, point 6).

From the decision's own price (check d, price0) the move at +1, +5, +15 and +60 min and the max (and min) within
60 min; hit = +15 % came before -10 % within 45 min (the fast path's own exits; neither = not a hit, the cautious
reading); "propušteno" = SKIP and max >= +MISS_PCT (20 %). The base rate of every source kind (decide.base_for) is the
hit share of its measured signals.

Price points (fast.db px): the price every fast_check read anyway (free), and one DexScreener batch request (free,
<= 30 tokens) per SAMPLE_EVERY_S (60 s) for tokens whose 60-min window is open, at most FAST_DEX_DAY requests a
Zagreb day (default 2000, counted in fast.db costs as dexscreener_ishodi). No GeckoTerminal, no paid source. A point
counts for +k min when it is within [-30 s, +150 s] of that minute.
"""
import json
import os

from . import store

OFFSETS = (("1m", 60), ("5m", 300), ("15m", 900), ("60m", 3600))
HORIZON_S = 3600
GRACE_S = 300
SAMPLE_EVERY_S = 60
DEX_TOKENS = 30
DEX_DAY = int(os.environ.get("FAST_DEX_DAY", "2000"))
MISS_PCT = 20.0
TP_PCT, SL_PCT, TP_WIN_S = 15.0, 10.0, 45 * 60
BASE_DAYS = 30


def put_px(con, token, price, mcap, now):
    if token and price:
        con.execute("INSERT OR IGNORE INTO px VALUES (?,?,?,?)", (token, int(now), float(price), mcap))


def open_tokens(con, now):
    """Tokens with a decided signal whose window is open and no point in the last SAMPLE_EVERY_S."""
    toks = [t for (t,) in con.execute("SELECT DISTINCT token FROM signals WHERE decided_ts IS NOT NULL AND out_done=0 "
                                      "AND decided_ts >= ?", (now - HORIZON_S - GRACE_S,))]
    out = []
    for t in toks:
        r = con.execute("SELECT MAX(ts) FROM px WHERE token=?", (t,)).fetchone()
        if not r or r[0] is None or now - r[0] >= SAMPLE_EVERY_S - 5:
            out.append(t)
    return out


def sample(con, now, fetch=None, meter=None):
    """One price point for the open tokens (DexScreener batches, capped). Returns how many tokens were priced."""
    toks = open_tokens(con, now)
    if not toks:
        return 0
    day = store.day_of(now)
    used = store.kv_get(con, "dex_out_day", {}) or {}
    n_used = (used.get("n") or 0) if used.get("day") == day else 0
    priced = 0
    for i in range(0, len(toks), DEX_TOKENS):
        if n_used >= DEX_DAY:
            break
        part = toks[i:i + DEX_TOKENS]
        try:
            if fetch is None:
                from dexscreener import client
                from .checks import parse_pairs
                got = parse_pairs(client.tokens("solana", part, ttl=30))
            else:
                got = fetch(part) or {}
        except Exception:  # noqa: BLE001 - DexScreener down: the next pass tries again
            got = {}
        n_used += 1
        if meter is not None:
            meter.add("dexscreener_ishodi")
        for t in part:
            m = got.get(t)
            if m and m.get("price"):
                put_px(con, t, m["price"], m.get("mcap"), now)
                priced += 1
    store.kv_put(con, "dex_out_day", {"day": day, "n": n_used})
    return priced


def path_of(con, token, t0, p0):
    """[(ts, change)] of the points in (t0, t0 + HORIZON_S], change = price / p0 - 1."""
    return [(ts, px / p0 - 1) for ts, px in con.execute(
        "SELECT ts, price FROM px WHERE token=? AND ts > ? AND ts <= ? AND price > 0 ORDER BY ts",
        (token, int(t0), int(t0) + HORIZON_S))]


def outcome(path, t0, done):
    """{"1m", "5m", "15m", "60m", "max60", "min60", "hit", "n_points"} in percent from a path (path_of)."""
    out = {"n_points": len(path)}
    for k, off in OFFSETS:
        near = [(abs(ts - t0 - off), ch) for ts, ch in path if -30 <= ts - t0 - off <= 150]
        out[k] = round(min(near)[1] * 100, 1) if near else None
    chs = [ch for _ts, ch in path]
    out["max60"] = round(max(chs) * 100, 1) if chs else None
    out["min60"] = round(min(chs) * 100, 1) if chs else None
    hit = None
    for ts, ch in path:
        if ts - t0 > TP_WIN_S:
            break
        if ch * 100 >= TP_PCT:
            hit = 1
            break
        if ch * 100 <= -SL_PCT:
            hit = 0
            break
    if hit is None and done and path:
        hit = 0
    out["hit"] = hit
    return out


def measure(con, now):
    """Update the outcome of every decided signal whose window is open; close the ones past HORIZON_S + GRACE_S.
    Returns how many were closed."""
    # every signal, bought or not (a CHECK_FAILED that still retries waits for its final decision)
    rows = con.execute("SELECT id, token, decided_ts, price0, decision FROM signals WHERE decided_ts IS NOT NULL AND "
                       "out_done=0 AND status IN ('done', 'failed') ORDER BY decided_ts LIMIT 2000").fetchall()
    closed = 0
    for sid, tok, t0, p0, dec in rows:
        done = now >= t0 + HORIZON_S + GRACE_S
        if not p0:
            r = con.execute("SELECT price FROM px WHERE token=? AND ts >= ? ORDER BY ts LIMIT 1", (tok, int(t0))).fetchone()
            p0 = r[0] if r else None
        if not p0:
            if done:
                con.execute("UPDATE signals SET out_done=1, out=? WHERE id=?",
                            (json.dumps({"note": "bez cijene u trenutku odluke"}), sid))
                closed += 1
            continue
        o = outcome(path_of(con, tok, t0, p0), t0, done)
        missed = None if o["max60"] is None else int(dec == "SKIP" and o["max60"] >= MISS_PCT)
        con.execute("UPDATE signals SET out=?, max60=?, missed=?, hit=?, out_done=? WHERE id=?",
                    (json.dumps(o), o["max60"], missed, o["hit"], int(done), sid))
        closed += int(done)
    return closed


def base_rates(con, now, days=BASE_DAYS):
    """{kind: (hits, n)} of the measured signals of the last `days` (every decision: what the source's signal did)."""
    out = {}
    for kind, h, n in con.execute("SELECT kind, COALESCE(SUM(hit), 0), COUNT(*) FROM signals WHERE out_done=1 AND hit "
                                  "IS NOT NULL AND decided_ts >= ? GROUP BY kind", (now - days * 86400,)):
        out[kind] = (int(h), int(n))
    return out
