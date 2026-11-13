"""Price and volume snapshots from DexScreener for every token called in the last day, and call outcomes from them.

The free GeckoTerminal candle API (kol/measure.py) is shared with other jobs on the same IP and is often busy: on
1.11. one 8-minute round measured 3 tokens, so most new calls showed "–" for 1 h / 6 h / 24 h. DexScreener answers
30 tokens per request (300 requests/min, free), so every round (20 min) the bot stores price, last-hour volume,
liquidity and market cap of each token with a call younger than 25 h. From those snapshots a call gets:

  p0, mcap0   first snapshot within SNAP_GAP after the post (or just before it, if the token was already tracked)
  r1h/6h/24h  snapshot closest to 1/6/24 h after the post (within SNAP_GAP)
  max24       highest snapshot price within 24 h (sampled every ~20 min, so a short wick can be missed)
  vol_before  DexScreener "volume last hour" at the post; vol_after the same one hour later; vol_lift their ratio

Gecko candles stay the better source: a call they measured is never overwritten from snapshots (msrc 'gecko').
"""
import time

H = 3600
SNAP_GAP = 25 * 60   # a snapshot this far from the moment it stands for still counts
KEEP_S = 3 * 86400


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def tokens_to_watch(con, now):
    """Tokens with a real call (X/Telegram post or a known KOL wallet's buy) in the last 25 h. 9.11.: 17,161 of the
    20,411 tokens snapshotted in a week had only scanner-bot posts or anonymous swaps behind them; nothing scores
    those, so their snapshots (190k rows a week, 60-80 s of DexScreener reads a round) bought nothing."""
    return [t for (t,) in con.execute("""SELECT DISTINCT token FROM calls WHERE ts >= ? AND kind IN ('call', 'buy')
        AND handle NOT LIKE 'w:%' AND handle NOT IN (SELECT handle FROM kols WHERE COALESCE(bot, 0) = 1)""",
                                      (now - 25 * H,))]


def take(con, now=None, fetch=None):
    """One snapshot of every token called in the last 25 h. Returns tokens stored."""
    from dexscreener import client
    now = now or int(time.time())
    fetch = fetch or (lambda toks: client.tokens("solana", toks))
    toks = tokens_to_watch(con, now)
    if not toks:
        return 0
    best = {}
    for p in fetch(toks):
        t = (p.get("baseToken") or {}).get("address")
        liq = (p.get("liquidity") or {}).get("usd") or 0
        if t and (t not in best or liq >= ((best[t].get("liquidity") or {}).get("usd") or 0)):
            best[t] = p
    rows = []
    for t, p in best.items():
        price = _num(p.get("priceUsd"))
        if not price:
            continue
        rows.append((t, now, price, _num((p.get("volume") or {}).get("h1")), _num((p.get("liquidity") or {}).get("usd")),
                     _num(p.get("marketCap") or p.get("fdv"))))
        # the token's symbol and pair for the tables, without a separate lookup
        mcap = _num(p.get("marketCap") or p.get("fdv"))
        con.execute("""INSERT INTO tokens (token, symbol, name, pair, supply, created_ts, liquidity, tries, updated)
            VALUES (?,?,?,?,?,?,?,0,?)
            ON CONFLICT (token) DO UPDATE SET symbol = COALESCE(symbol, excluded.symbol),
              name = COALESCE(name, excluded.name), pair = COALESCE(pair, excluded.pair),
              supply = COALESCE(supply, excluded.supply), created_ts = COALESCE(created_ts, excluded.created_ts)""",
                    (t, (p.get("baseToken") or {}).get("symbol"), (p.get("baseToken") or {}).get("name"),
                     p.get("pairAddress"), mcap / price if mcap else None, (p.get("pairCreatedAt") or 0) // 1000 or None,
                     _num((p.get("liquidity") or {}).get("usd")), now))
    con.executemany("INSERT OR REPLACE INTO snaps VALUES (?,?,?,?,?,?)", rows)
    try:   # 11.11. dual write into events.db (events/hooks.py), type price_tick (one per token per minute, 30k+)
        from events import hooks as _ev
        _ev.prices(rows)
    except Exception:  # noqa: BLE001
        pass
    con.execute("DELETE FROM snaps WHERE ts < ?", (now - KEEP_S,))
    con.commit()
    return len(rows)


def _near(snaps, t, after_only=False):
    """Snapshot closest to t (within SNAP_GAP); after_only: only snapshots at or after t."""
    best = None
    for s in snaps:
        if after_only and s[0] < t:
            continue
        d = abs(s[0] - t)
        if d <= SNAP_GAP and (best is None or d < abs(best[0] - t)):
            best = s
    return best


def outcome(snaps, ts, now, cfg):
    """Measured columns of one call from (ts, price, vol_h1, liq, mcap) snapshots, oldest first; None if the first
    snapshot is too far from the post."""
    first = _near(snaps, ts, after_only=True)
    before = [s for s in snaps if ts - 10 * 60 <= s[0] < ts]
    start = before[-1] if before else first
    if not start:
        return None
    p0 = start[1]
    o = {"p0": p0, "mcap0": start[4], "pre2h": None}
    old = _near(snaps, ts - 2 * H)
    if old:
        o["pre2h"] = p0 / old[1] - 1
    for k, h in (("r1h", 1), ("r6h", 6), ("r24h", 24)):
        s = _near(snaps, ts + h * H) if now >= ts + h * H else None
        o[k] = (s[1] / p0 - 1) if s else None
    after = [s[1] for s in snaps if ts <= s[0] <= ts + 24 * H]
    o["max24"] = (max(after) / p0 - 1) if after else None
    o["vol_before"] = start[2]
    one = _near(snaps, ts + H) if now >= ts + H else None
    o["vol_after"] = one[2] if one else None
    o["vol_lift"] = (min(50.0, o["vol_after"] / max(o["vol_before"] or 0, 50.0))
                     if o["vol_after"] is not None else None)
    last = o["r24h"] if o["r24h"] is not None else o["r6h"]
    o["rug"] = int(last is not None and last <= cfg["rug_x"])
    o["complete"] = int(now >= ts + 24 * H + SNAP_GAP)
    return o


def measure(con, cfg, now=None):
    """Fill the outcome of every call Gecko has not measured from the snapshots. No network. Returns calls updated."""
    from kol.measure import why_bad
    now = now or int(time.time())
    rows = con.execute("""SELECT tweet_id, token, ts FROM calls WHERE complete = 0 AND COALESCE(msrc, '') != 'gecko'
        AND ts >= ?""", (now - 25 * H - SNAP_GAP,)).fetchall()
    by = {}
    for tid, tok, ts in rows:
        by.setdefault(tok, []).append((tid, ts))
    n = 0
    for tok, calls in by.items():
        snaps = con.execute("SELECT ts, price, vol_h1, liq, mcap FROM snaps WHERE token = ? ORDER BY ts",
                            (tok,)).fetchall()
        if not snaps:
            continue
        for tid, ts in calls:
            o = outcome(snaps, ts, now, cfg)
            if not o:
                continue
            bad = why_bad(o["mcap0"], o["max24"], cfg)
            if bad:
                for k in ("pre2h", "r1h", "r6h", "r24h", "max24", "vol_lift", "rug"):
                    o[k] = None
            con.execute("""UPDATE calls SET p0=?, mcap0=?, pre2h=?, r1h=?, r6h=?, r24h=?, max24=?, vol_before=?,
                vol_after=?, vol_lift=?, rug=?, complete=?, bad=?, msrc='dex' WHERE tweet_id=? AND token=?""",
                        (o["p0"], o["mcap0"], o["pre2h"], o["r1h"], o["r6h"], o["r24h"], o["max24"], o["vol_before"],
                         o["vol_after"], o["vol_lift"], o["rug"], o["complete"], bad, tid, tok))
            n += 1
    con.commit()
    return n
