"""The oscillation scanner: per token and Zagreb day, from that day's bars only (pure, day_metrics), and the minute
data the server already holds (load_server, read-only: no API call, no cost).

Per token-day:
  bars, coverage    bars in the day / 1440 and the median gap between them (s): a sparse series is only the minutes
                    with a trade (GeckoTerminal), a 5- / 15-minute one is the market watchlist's snapshots
  liq               the median liquidity of the token's snapshots (None = unknown: the cost assumes DEFAULT_LIQ)
  vol_usd           the day's volume (the candles' USD volume)
  range_pct         the day's high / low - 1
  drift_pct         the last close / the first open - 1 (the net trend)
  er                Kaufman's efficiency ratio |net change| / sum |minute changes|: ~0 = back and forth, 1 = one way
  swings[size]      ZIGZAG on the closes: the completed up-legs of at least need(size) = the move the rule needs at
                    that size (the round-trip cost at the token's liquidity + 1 $ net, entry / exit slippage), each
                    leg confirmed by a fall of the same size: how many buy-low / sell-high cycles there were
  breakdown         the token broke: the day's low under half its open (rug / dump) or the close under 60 % of the
                    day's high
  score             swings at the reference size (REF_SOL 0.5) x (1 - er): many cycles, little net trend
Eligible (rank): MC at the close >= 30k, liquidity >= 15k (or unknown), bars >= MIN_DAY_BARS (360: a quarter of the
day's minutes), median gap <= MAX_GAP_S (180 s), drift > -30 %, no breakdown, not in the rug archive, bonded (a known
pool that is not the pump.fun curve, or a GeckoTerminal series: an AMM pool).
"""
import statistics

from . import rule

REF_SOL = 0.5
MIN_DAY_BARS = 360
MAX_GAP_S = 180
MIN_MCAP = 30_000
MIN_LIQ = 15_000
DRIFT_MIN = -0.30
TZ_S = 3600   # Zagreb in November (CET), as rangedca/backtest's day counter


def day_of(ts):
    return int((int(ts) + TZ_S) // 86400)


def day_start(day):
    return int(day) * 86400 - TZ_S


def zigzag_legs(closes, th):
    """The completed up-legs of at least th (fraction) in a zigzag of the closes with reversal threshold th."""
    if len(closes) < 2 or th <= 0:
        return 0
    lo = hi = closes[0]
    up, n = False, 0
    for p in closes[1:]:
        if not p or p <= 0:
            continue
        if not up:
            lo = min(lo, p)
            if p >= lo * (1 + th):
                up, hi = True, p
        else:
            hi = max(hi, p)
            if p <= hi * (1 - th):
                n += 1
                up, lo = False, p
    if up and hi >= lo * (1 + th):   # the last leg up counts once it reached th (the sale is possible at its top)
        n += 1
    return n


def efficiency(closes):
    if len(closes) < 2:
        return None
    path = sum(abs(b - a) for a, b in zip(closes, closes[1:]))
    return abs(closes[-1] - closes[0]) / path if path > 0 else 0.0


def need_at(size_sol, liq, sol_usd=rule.SOL_USD, tp_usd=1.0, fee_side=None, tx=None):
    """The move the rule needs at this size (rule.need_move: cost + tp_usd net + slippage)."""
    c = rule.cost_at(size_sol, liq, sol_usd, fee_side, tx)
    return rule.need_move(rule.target_frac(c["size_usd"], tp_usd), c["rt"])


def day_metrics(bars, liq=None, supply=None, sol_usd=rule.SOL_USD, sizes=rule.SIZES_SOL, fee_side=None, tx=None):
    """The metrics of one token-day (bars of that day only, oldest first)."""
    n = len(bars)
    out = {"bars": n, "coverage": round(n / 1440, 3), "liq": liq, "liq_known": liq is not None}
    if n < 2:
        return dict(out, eligible=False, why="premalo barova", swings={}, score=0.0)
    gaps = [b[0] - a[0] for a, b in zip(bars, bars[1:])]
    closes = [b[4] for b in bars if b[4] and b[4] > 0]
    o, c = bars[0][1], bars[-1][4]
    hi, lo = max(b[2] for b in bars), min(b[3] for b in bars if b[3] > 0)
    out.update(med_gap_s=int(statistics.median(gaps)), open=o, close=c, high=hi, low=lo,
               range_pct=round((hi / lo - 1) * 100, 2) if lo > 0 else None,
               drift_pct=round((c / o - 1) * 100, 2) if o else None,
               er=round(efficiency(closes) or 0.0, 3), vol_usd=round(sum(b[5] or 0 for b in bars), 0),
               mcap=round(c * supply) if supply and c else None)
    out["breakdown"] = bool(lo <= o * 0.5 or c < hi * 0.6)
    out["swings"] = {f"{s:g}": zigzag_legs(closes, need_at(s, liq, sol_usd, 1.0, fee_side, tx)) for s in sizes}
    out["swings_3pct"] = zigzag_legs(closes, 0.03)
    out["score"] = round(out["swings"].get(f"{REF_SOL:g}", 0) * (1 - out["er"]), 3)
    why = None
    if n < MIN_DAY_BARS:
        why = f"premalo minutnih barova ({n} < {MIN_DAY_BARS})"
    elif out["med_gap_s"] > MAX_GAP_S:
        why = f"rijetki podaci (medijan razmaka {out['med_gap_s']} s)"
    elif out["mcap"] is not None and out["mcap"] < MIN_MCAP:
        why = "MC ispod 30k"
    elif liq is not None and liq < MIN_LIQ:
        why = "likvidnost ispod 15k"
    elif out["drift_pct"] is not None and out["drift_pct"] < DRIFT_MIN * 100:
        why = f"pada {out['drift_pct']:+.0f} % u danu"
    elif out["breakdown"]:
        why = "slom (dno ispod pola otvaranja ili zatvaranje ispod 60 % vrha)"
    out["eligible"], out["why"] = why is None, why
    return out


def split_days(candles):
    """{day: [bars]} by Zagreb day."""
    out = {}
    for b in candles:
        out.setdefault(day_of(b[0]), []).append(b)
    return out


# ---------- the server's minute data (read-only) -------------------------------------------------------------------

def _q(con, sql, args=()):
    try:
        return con.execute(sql, args).fetchall()
    except Exception:  # noqa: BLE001 - a missing table is no data
        return []


def server_tokens(rcon, now, days):
    """{token: {"src": set of sources}} with at least ~5 h of minute data in the last `days` (prefiltered in SQL so
    the market watchlist's hundreds of 5- / 15-minute series are not loaded)."""
    from rangedca import data
    t0 = int(now - days * 86400)
    toks = {}

    def add(rows, src):
        for r in rows:
            toks.setdefault(r[0], set()).add(src)
    add(_q(rcon, "SELECT token FROM gt_candles WHERE last_ts >= ? AND n >= 300", (t0,)), "gt")
    add(_q(rcon, "SELECT token FROM snaps WHERE ts >= ? GROUP BY token HAVING COUNT(*) >= 300", (t0,)), "snaps")
    for path, sql, src in ((data.minute_path(), "SELECT token FROM call_candles WHERE last_ts >= ? AND n >= 300",
                            "call_candles"),
                           (data.hype_path(), "SELECT token FROM token_pulse WHERE ts >= ? GROUP BY token "
                                              "HAVING COUNT(*) >= 300", "pulse")):
        con = data._ro_file(path)
        if con is None:
            continue
        try:
            add(_q(con, sql, (t0,)), src)
        finally:
            con.close()
    return toks


def bonded(rcon, tok, srcs):
    """False only when the token's known pool is the pump.fun curve; a GeckoTerminal series is an AMM pool."""
    r = _q(rcon, "SELECT dex FROM pools WHERE token=?", (tok,))
    dex = ((r[0][0] if r else None) or "").lower()
    if dex in ("pumpfun", "pump.fun", "pump-fun", "pump"):
        return False
    return True


def archived(tok):
    try:
        from rangedca import trade as rtrade
        return rtrade.archived_why(tok)
    except Exception:  # noqa: BLE001
        return None


def load_server(rcon, tok, now, days):
    """(candles, supply, liq, symbol) of one token: rangedca/backtest.load (range.db gt_candles + snaps, minute.db
    call_candles, hype.db token_pulse)."""
    from rangedca import backtest
    return backtest.load(rcon, tok, now, days)
