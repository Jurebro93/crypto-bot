"""Range detection and range quality from minute candles (flag range_dca). Pure functions, no I/O.

A candle is (ts, o, h, l, c, v, buys, sells): ts the minute's start (unix s), prices in USD, v the minute's volume in
USD, buys / sells the number of buy / sell transactions in that minute (None when the source does not know them:
GeckoTerminal candles). Snapshot-based minutes (DexScreener) carry the price as o=h=l=c and an estimate of the
minute's volume and transactions (rangedca/data.py).

Swing points (pivots): a zigzag over the candle BODIES (max/min of open and close; a one-print wick is not a touch,
and the live feed is a sampled price without wicks anyway). A local high is confirmed when the price then falls at
least HIGH_TURN (10 %) under it, a local low when the price then rises at least LOW_TURN (15 %) over it; highs and
lows alternate. Only swings confirmed by `now` and not older than the window (24 h) count.

Zones (spec 1): a top zone is >= 2 local highs within +-8 % of one of them, a bottom zone >= 2 local lows within
+-10 %. Minute swings of a memecoin give many such groups, so the range is the PAIR (top group, bottom group) with
the top above the bottom and range_high / range_low (the zones' averages) >= 1.3 that the price sits in (between
range_low_low * 0.85 and range_high_top * 1.15), with the most touches on its weaker side, touches weighted by age
(half-life 8 h: a level touched today outweighs yesterday's). A zone's edges come from its last 3 touches:
range_high_low = their lowest, range_high_top = their highest (at least +-1 % around their average), so every new
touch moves the zone. A range also needs data for >= 6 h, liquidity >= $20k, volume in the last hour >= $10k and
MC >= $30k (CLAUDE.md); the rug check is the entry's (league/copy guards).

range_score 0-1 (spec 2), each component 0-1 times its weight:
  recoveries             0.25  bottom touches followed by >= +25 %: 0-1 -> 0, 2 -> 0.6, >= 3 -> 1
  recovery_speed         0.15  median minutes from a bottom touch to half way to the top: <= 20 -> 1, >= 90 -> 0
  higher_lows            0.15  the range's last low >= its previous one * 0.97: 1, else 0 (the range's lows are
                               the swing lows in or under the bottom zone, range_lows(); a swing low half way up
                               is noise on the way down; spec 5's "two lower lows in a row" reads the same lows)
  volume_hold            0.20  volume_15m * 4 / average hourly volume of the last 6 h: >= 0.5 -> 1, <= 0.25 -> 0
  buy_share_at_low       0.15  buys / (buys + sells) in the minutes whose body touched the bottom zone: >= 0.55 -> 1,
                               <= 0.45 -> 0 (without transaction counts: the share of volume in rising minutes,
                               marked "proxy")
  sell_pressure_on_drop  0.10  volume per minute of the last fall into the bottom vs the window's average: <= 1x -> 1,
                               >= 2x (panic) -> 0
Unknown inputs score 0, never a guess in our favour.

range_flip (11.11., Jure: "rangedca flip / pauza / stop", flag range_flip G26; flip_step() and its helpers, pure):
a state per token next to the range above, computed every detection pass from the previous pass's state.
  break        a 5-minute bar (epoch-aligned bucket of the series) that CLOSES beyond the range in force by a margin of
               max(2 %, 1 x ATR) (up: range_high_top + margin, down: range_low_low - margin), the bar before the
               excursion closing inside; CONFIRMED when the bar's volume >= 1.5 x the median 5-minute volume of the
               window (24 h) and the excursion is at most 3 bars (15 min) old. An unconfirmed break changes nothing
               (it is shown as "seen").
  normal       today's range (the 24 h window) is in force; its breaks are watched.
  flip_candidate  after a confirmed break UP: the old top zone (range_high_low .. range_high_top) is the candidate
               for the new bottom; no range entries. It becomes the bottom (state flipped) after >= 2 retest touches
               (swing lows, the same pivots as the zones, within the zone +-3 %) without a 5-minute close under its
               low x 0.97; such a close is a failed flip (state normal again).
  paused       after a confirmed break DOWN: no new entries (lot 1 or lot 2); the old bottom zone (range_low_low ..
               range_low_top) is stored as the resistance. Resumes (state resumed) when the range computed from the
               candles after the break only has a valid pair (its bottom then has >= 2 touches after the break) whose
               range_high_top <= the resistance's top x 1.03 (the new range lies under the old floor).
  flipped / resumed  the range in force is the one computed from the candles after the break only (post_range;
               the window's first candle is no swing point); its own breaks are watched like a normal range's.
  Every non-normal state ends 24 h after its break (the 24 h window then holds only candles after it): normal. A
  pass more than 1 h after the previous one reads no break (the zones it would read against are stale).
  stop         ATR = mean true range (candle BODIES, like the pivots) of the last 14 complete 15-minute bars (3.5 h)
               of the same series; the stop is range_low_low - 1.5 x ATR, held between 5 % and 20 % under
               range_low_low (old: range_low_low x 0.85, kept under off / shadow and whenever ATR is unknown: fewer
               than 4 bars).
Only rules.new_range() reads the state (the new rules); today's range, its status and `active` never change for it.
"""
import statistics

CFG = {
    "window_h": 24, "min_hist_h": 6,
    "high_turn": 0.10, "low_turn": 0.15, "high_tol": 0.08, "low_tol": 0.10,
    "keep_touches": 3, "zone_min_half": 0.01,
    "min_ratio": 1.3, "min_liq": 20_000, "min_vol_h1": 10_000, "min_mcap": 30_000,
    "rec_up": 0.25, "speed_fast_min": 20, "speed_slow_min": 90, "higher_low_x": 0.97,
    "vol_hold_hi": 0.5, "vol_hold_lo": 0.25, "buy_hi": 0.55, "buy_lo": 0.45, "panic_x": 2.0,
    "lower_low_x": 0.97, "vol_decline": 0.5,
    "break_down_x": 0.92,   # under range_low_low * this the range is broken downward (also lot 2's floor)
    "break_up_x": 1.15,     # over range_high_top * this the range is broken upward: no entries
    "snap_fresh_s": 300,    # a snapshot older than this is not "now"
    "unknown_liq_ok": False,  # backtest only: history without a liquidity reading is not refused for it
    "skip_edge_pivot": False,  # range_flip's range after a break: the window's first candle is no swing point
}
WEIGHTS = {"recoveries": 0.25, "recovery_speed": 0.15, "higher_lows": 0.15, "volume_hold": 0.20,
           "buy_share_at_low": 0.15, "sell_pressure_on_drop": 0.10}
ACTIVE = "aktivan"


def _cfg(cfg):
    return {**CFG, **(cfg or {})}


def body(c):
    """(high, low) of a candle's body."""
    return max(c[1], c[4]), min(c[1], c[4])


def lin(x, lo, hi):
    """0 at or under lo, 1 at or over hi, linear between (hi > lo); None -> 0."""
    if x is None:
        return 0.0
    if x >= hi:
        return 1.0
    if x <= lo:
        return 0.0
    return (x - lo) / (hi - lo)


def pivots(candles, high_turn=CFG["high_turn"], low_turn=CFG["low_turn"]):
    """Alternating swing points [{"kind": "H"|"L", "ts", "px", "confirm_ts"}], oldest first."""
    out, mode, hi, lo = [], None, None, None
    for c in candles:
        ts = c[0]
        bh, bl = body(c)
        if bh <= 0:
            continue
        if hi is None:
            hi, lo = (bh, ts), (bl, ts)
            continue
        if mode != "down" and bh > hi[0]:
            hi = (bh, ts)
        if mode != "up" and bl < lo[0]:
            lo = (bl, ts)
        if mode != "down" and bl <= hi[0] * (1 - high_turn):
            out.append({"kind": "H", "ts": hi[1], "px": hi[0], "confirm_ts": ts})
            mode, lo = "down", (bl, ts)
            continue
        if mode != "up" and bh >= lo[0] * (1 + low_turn):
            out.append({"kind": "L", "ts": lo[1], "px": lo[0], "confirm_ts": ts})
            mode, hi = "up", (bh, ts)
    return out


def _zone_of(mem, keep, min_half, now, half_life_h):
    mem = sorted(mem, key=lambda p: p["ts"])
    last = mem[-keep:]
    pxs = [p["px"] for p in last]
    mid = sum(pxs) / len(pxs)
    return {"low": min(min(pxs), mid * (1 - min_half)), "top": max(max(pxs), mid * (1 + min_half)), "mid": mid,
            "touches": [{"ts": p["ts"], "px": p["px"]} for p in mem], "last": [p["ts"] for p in last],
            "w": round(sum(0.5 ** (max(0, now - p["ts"]) / 3600 / half_life_h) for p in mem), 4)}


def clusters(points, tol, now, keep=CFG["keep_touches"], min_half=CFG["zone_min_half"], half_life_h=8.0):
    """Every distinct group of >= 2 swing points within +-tol of one of them, as zones (see _zone_of); "w" is the
    number of touches weighted by age (half-life 8 h), so a level touched today outweighs one touched yesterday."""
    out, seen = [], set()
    for p in points:
        mem = [q for q in points if abs(q["px"] / p["px"] - 1) <= tol]
        key = tuple(sorted(q["ts"] for q in mem))
        if len(mem) < 2 or key in seen:
            continue
        seen.add(key)
        out.append(_zone_of(mem, keep, min_half, now, half_life_h))
    return out


def pick(highs, lows, price, now, cfg=None):
    """(top zone, bottom zone, valid): the pair of a high cluster and a low cluster with the top zone above the
    bottom zone and range_high / range_low >= min_ratio, preferring a pair the price sits in (between the hard stop
    and the upward break), then the most touches on the weaker side, then the most touches. Without a valid pair the
    strongest cluster of each side (for the reason), valid False."""
    cfg = _cfg(cfg)
    tops = clusters(highs, cfg["high_tol"], now, cfg["keep_touches"], cfg["zone_min_half"])
    bots = clusters(lows, cfg["low_tol"], now, cfg["keep_touches"], cfg["zone_min_half"])
    best = None
    for t in tops:
        for b in bots:
            if t["low"] <= b["top"] or t["mid"] / b["mid"] < cfg["min_ratio"]:
                continue
            inside = price is None or b["low"] * 0.85 <= price <= t["top"] * cfg["break_up_x"]
            key = (inside, round(min(t["w"], b["w"]), 6), round(t["w"] + b["w"], 6), t["touches"][-1]["ts"])
            if best is None or key > best[0]:
                best = (key, t, b)
    if best:
        return best[1], best[2], True
    return (max(tops, key=lambda z: z["w"]) if tops else None), (max(bots, key=lambda z: z["w"]) if bots else None), False


def zone(points, tol, now=None, keep=CFG["keep_touches"], min_half=CFG["zone_min_half"]):
    """The strongest single zone of these swing points (most age-weighted touches), None without one."""
    now = now or max((p["ts"] for p in points), default=0)
    cs = clusters(points, tol, now, keep, min_half)
    return max(cs, key=lambda z: (z["w"], z["touches"][-1]["ts"])) if cs else None


def vol_sum(candles, t0, t1):
    """Volume of the minutes t0 < ts <= t1 (the last 15 minutes at `now` = 15 minute candles)."""
    return sum(c[5] or 0 for c in candles if t0 < c[0] <= t1)


def _close_at(candles, ts):
    """Close of the last candle that started at or before ts, None when none."""
    best = None
    for c in candles:
        if c[0] <= ts:
            best = c
        else:
            break
    return best[4] if best else None


def _buy_share(candles, pred):
    """(share, how): buys / (buys + sells) over the candles pred() keeps; without counts the share of the volume of
    rising minutes ("proxy"); (None, None) when there is nothing."""
    b = s = 0.0
    up = tot = 0.0
    known = False
    for c in candles:
        if not pred(c):
            continue
        if c[6] is not None and c[7] is not None:
            b += c[6]
            s += c[7]
            known = True
        v = c[5] or 0
        tot += v
        if c[4] >= c[1]:
            up += v
    if known and b + s > 0:
        return b / (b + s), "transakcije"
    if tot > 0:
        return up / tot, "proxy"
    return None, None


def metrics(candles, now, snap=None, cfg=None):
    """The entry-time numbers from the candles (and the fresh snapshot, which wins where it knows better):
    price, ch_5m, vol_15m, vol_h1, vol_1h_avg6, vol_ratio (vol_15m * 4 / vol_1h_avg6), buy_share_5m (+ how), liq,
    mcap, supply."""
    cfg = _cfg(cfg)
    now = int(now)
    fresh = bool(snap and snap.get("ts") and now - snap["ts"] <= cfg["snap_fresh_s"])
    price = (snap or {}).get("price") if fresh else None
    if not price and candles:
        last = [c for c in candles if c[0] <= now]
        price = last[-1][4] if last else None
    p5 = _close_at(candles, now - 300)
    ch5 = (price / p5 - 1) if price and p5 else None
    if fresh and snap.get("ch_m5") is not None:
        ch5 = snap["ch_m5"] / 100.0
    v15 = vol_sum(candles, now - 900, now)
    v1 = vol_sum(candles, now - 3600, now)
    first = candles[0][0] if candles else now
    hours = max(1.0, min(6.0, (now - first) / 3600))
    avg6 = vol_sum(candles, now - 6 * 3600, now) / hours
    if fresh and snap.get("vol_h1") is not None:
        v1 = snap["vol_h1"]
    if snap and snap.get("vol_h1_avg6"):
        avg6 = snap["vol_h1_avg6"]
    if fresh and snap.get("vol_15m") is not None:
        v15 = snap["vol_15m"]
    bs, how = None, None
    if fresh and (snap.get("buys_m5") or 0) + (snap.get("sells_m5") or 0) > 0:
        bs, how = snap["buys_m5"] / (snap["buys_m5"] + snap["sells_m5"]), "transakcije"
    else:
        bs, how = _buy_share(candles, lambda c: now - 300 < c[0] <= now)
    supply = (snap or {}).get("supply") or cfg.get("supply")
    mcap = (snap or {}).get("mcap") if fresh and snap.get("mcap") else (price * supply if price and supply else None)
    return {"price": price, "ch_5m": ch5, "vol_15m": v15, "vol_h1": v1, "vol_1h_avg6": avg6,
            "vol_ratio": (v15 * 4 / avg6) if avg6 else None, "buy_share_5m": bs, "buy_share_how": how,
            "liq": (snap or {}).get("liq"), "mcap": mcap, "supply": supply, "snap_fresh": fresh}


def _recoveries(candles, lows_all, bot, top_mid, cfg, now):
    """[{ts, px, up (best rise before the next local low), minutes_to_half}] for every bottom touch."""
    out = []
    lows_sorted = sorted(lows_all, key=lambda p: p["ts"])
    for t in bot["touches"]:
        nxt = next((p["ts"] for p in lows_sorted if p["ts"] > t["ts"]), now + 60)
        seg = [c for c in candles if t["ts"] < c[0] <= nxt]
        best = max((body(c)[0] for c in seg), default=None)
        half = t["px"] + 0.5 * (top_mid - t["px"])
        hit = next((c[0] for c in seg if body(c)[0] >= half), None)
        out.append({"ts": t["ts"], "px": t["px"], "up": (best / t["px"] - 1) if best else None,
                    "minutes_to_half": round((hit - t["ts"]) / 60, 1) if hit else None})
    return out


def range_lows(lows, bot, cfg=None):
    """The range's own lows: swing lows in or under the bottom zone (at most range_low_top). A swing low half way up
    the range is a step on the way down, not a low of the range; "higher lows" and "two lower lows in a row" (spec 2
    and 5) are read on these, so the rule sees the floor giving way, not the noise above it."""
    return [p for p in lows if p["px"] <= bot["top"]]


def components(candles, pv, top, bot, m, now, cfg=None):
    """{name: {"value", "score", "weight"}} and the recoveries list (spec 2)."""
    cfg = _cfg(cfg)
    lows = [p for p in pv if p["kind"] == "L"]
    highs = [p for p in pv if p["kind"] == "H"]
    rec = _recoveries(candles, lows, bot, top["mid"], cfg, now)
    n_rec = sum(1 for r in rec if r["up"] is not None and r["up"] >= cfg["rec_up"])
    speeds = [r["minutes_to_half"] for r in rec if r["minutes_to_half"] is not None]
    med = statistics.median(speeds) if speeds else None
    hl = None
    rl = range_lows(lows, bot, cfg)
    if len(rl) >= 2:
        hl = rl[-1]["px"] >= rl[-2]["px"] * cfg["higher_low_x"]
    lo_z, top_z = bot["low"], bot["top"]
    # minutes whose body touched the bottom zone (the bounce minute closes above it, so "closed inside" misses it)
    bs_low, bs_how = _buy_share(candles, lambda c: body(c)[1] <= top_z and body(c)[0] >= lo_z)
    # the last fall into the bottom: from the local high before the newest bottom touch down to that touch
    last_t = bot["touches"][-1]["ts"]
    h0 = max((h["ts"] for h in highs if h["ts"] < last_t), default=None)
    press = None
    if h0 is not None and candles:
        leg_min = max(1.0, (last_t - h0) / 60)
        span_min = max(1.0, (min(now, candles[-1][0]) - candles[0][0]) / 60 + 1)
        avg = vol_sum(candles, candles[0][0] - 1, now) / span_min
        leg = vol_sum(candles, h0, last_t) / leg_min
        press = (leg / avg) if avg else None
    c = {
        "recoveries": {"value": n_rec, "score": 1.0 if n_rec >= 3 else 0.6 if n_rec == 2 else 0.0},
        "recovery_speed": {"value": med, "score": 0.0 if med is None else
                           1 - lin(med, cfg["speed_fast_min"], cfg["speed_slow_min"])},
        "higher_lows": {"value": hl, "score": 1.0 if hl else 0.0},
        "volume_hold": {"value": m.get("vol_ratio"), "score": lin(m.get("vol_ratio"), cfg["vol_hold_lo"], cfg["vol_hold_hi"])},
        "buy_share_at_low": {"value": bs_low, "how": bs_how, "score": lin(bs_low, cfg["buy_lo"], cfg["buy_hi"])},
        "sell_pressure_on_drop": {"value": press, "score": 0.0 if press is None else
                                  1 - lin(press, 1.0, cfg["panic_x"])},
    }
    for k, v in c.items():
        v["weight"] = WEIGHTS[k]
        v["score"] = round(v["score"], 4)
        if isinstance(v["value"], float):
            v["value"] = round(v["value"], 4)
    return c, rec


def score_of(comps):
    return round(sum(v["score"] * v["weight"] for v in comps.values()), 4)


def analyze(candles, now, snap=None, cfg=None):
    """The range of one token at `now` from its candles (oldest first) and its latest snapshot (dict with price,
    mcap, liq, vol_h1, buys_m5, sells_m5, ch_m5, supply, ts; may be None). Returns a dict: status ("aktivan" or the
    reason in Croatian), active, why, zones (price and MC), touches, recoveries, components, score, ratio, pos_pct
    (where the price sits in the range, 0 = range_low_low, 100 = range_high_top), metrics and the exclusion signals
    (lower_lows, vol_decline, broken_down, broken_up)."""
    cfg = _cfg(cfg)
    now = int(now)
    w0 = now - int(cfg["window_h"] * 3600)
    cs = [c for c in candles if w0 <= c[0] <= now and c[4] and c[4] > 0]
    m = metrics(cs, now, snap, cfg)
    out = {"ts": now, "status": None, "active": False, "why": "", "zones": None, "touches": None, "recoveries": [],
           "components": None, "score": None, "ratio": None, "pos_pct": None, "metrics": m,
           "signals": {"lower_lows": False, "vol_decline": False, "broken_down": False, "broken_up": False},
           "span_h": round((cs[-1][0] - cs[0][0]) / 3600, 2) if cs else 0.0}
    if not cs or out["span_h"] < cfg["min_hist_h"]:
        out.update(status="premalo podataka", why=f"minutni podaci za {out['span_h']:.1f} h, treba {cfg['min_hist_h']} h")
        return out
    pv = [p for p in pivots(cs, cfg["high_turn"], cfg["low_turn"]) if p["confirm_ts"] <= now
          and not (cfg["skip_edge_pivot"] and p["ts"] == cs[0][0])]
    highs = [p for p in pv if p["kind"] == "H"]
    lows = [p for p in pv if p["kind"] == "L"]
    if m["vol_h1"] is not None and m["vol_1h_avg6"]:
        out["signals"]["vol_decline"] = m["vol_h1"] < cfg["vol_decline"] * m["vol_1h_avg6"]
    top, bot, valid = pick(highs, lows, m["price"], now, cfg)
    if not top or not bot:
        out.update(status="nema raspona", why=("manje od 2 vrha unutar ±8 %" if not top else "manje od 2 dna unutar ±10 %"))
        return out
    rl = range_lows(lows, bot, cfg)
    if len(rl) >= 3:
        l1, l2, l3 = (p["px"] for p in rl[-3:])
        out["signals"]["lower_lows"] = l2 < l1 * cfg["lower_low_x"] and l3 < l2 * cfg["lower_low_x"]
    supply = m.get("supply")

    def mc(px):
        return round(px * supply) if supply and px else None
    out["zones"] = {"range_high_low": top["low"], "range_high_top": top["top"], "range_low_low": bot["low"],
                    "range_low_top": bot["top"], "range_high": top["mid"], "range_low": bot["mid"],
                    "mc": {k: mc(v) for k, v in (("range_high_low", top["low"]), ("range_high_top", top["top"]),
                                                 ("range_low_low", bot["low"]), ("range_low_top", bot["top"]))}}
    out["touches"] = {"top": top["touches"], "bottom": bot["touches"], "top_last3": top["last"], "bottom_last3": bot["last"]}
    out["ratio"] = round(top["mid"] / bot["mid"], 4)
    comps, rec = components(cs, pv, top, bot, m, now, cfg)
    out.update(components=comps, recoveries=rec, score=score_of(comps))
    price = m["price"]
    if price and top["top"] > bot["low"]:
        out["pos_pct"] = round((price - bot["low"]) / (top["top"] - bot["low"]) * 100, 1)
        out["signals"]["broken_down"] = price < bot["low"] * cfg["break_down_x"]
        out["signals"]["broken_up"] = price > top["top"] * cfg["break_up_x"]
    liq, v1 = m.get("liq"), m.get("vol_h1")
    if not valid or top["low"] <= bot["top"] or out["ratio"] < cfg["min_ratio"]:
        out.update(status="raspon preuzak", why=f"vrh/dno {out['ratio']:.2f}, treba barem {cfg['min_ratio']}")
    elif not m.get("mcap") or m["mcap"] < cfg["min_mcap"]:
        out.update(status="ispod 30k", why="MC ispod 30k ili nepoznat (ispod 30k se ne analizira)")
    elif liq is None and not cfg["unknown_liq_ok"]:
        out.update(status="mala likvidnost", why="likvidnost nepoznata")
    elif liq is not None and liq < cfg["min_liq"]:
        out.update(status="mala likvidnost", why=f"likvidnost ${liq:,.0f}, treba ${cfg['min_liq']:,.0f}")
    elif v1 is None or v1 < cfg["min_vol_h1"]:
        out.update(status="slab volumen", why=f"volumen 1 h ${v1 or 0:,.0f}, treba ${cfg['min_vol_h1']:,.0f}")
    elif out["signals"]["broken_down"]:
        out.update(status="probijen dolje", why="cijena ispod range_low_low × 0,92")
    elif out["signals"]["broken_up"]:
        out.update(status="probijen gore", why="cijena iznad range_high_top × 1,15")
    else:
        out.update(status=ACTIVE, active=True, why="")
    return out


# ---------- range_flip (11.11., flag range_flip G26): flip, pause, volatility stop ---------------------------------
# At the merge with noc/katalizator this replaces its zone_reset (analyze_reset / excursion): an excursion 2x above the
# top or under half the bottom is a confirmed break here too (a close beyond the margin, with volume); instead of
# trading zones of the last 6 h at once, the range after the break (post_range: the candles since the break only) is
# traded once flipped / resumed, for 24 h, behind the flag. reset_zones(c, now, window_h=h) == post_range(c, now,
# now - h x 3600) but for the minimum history; keep it as that one-line wrapper if another branch still calls it.
FLIP = {
    "v": 1,               # the state's format version (range.db range_flip.v; a state of another version is ignored)
    "bar_s": 300,         # break bars: 5-minute buckets of the series
    "atr_bar_s": 900,     # ATR bars: 15 minutes
    "atr_n": 14,          # ATR periods (3.5 h)
    "atr_min_bars": 4,    # fewer complete bars: ATR unknown, the stop stays range_low_low x 0.85
    "brk_pct": 0.02,      # a break closes beyond the edge by >= max(brk_pct x edge, brk_atr x ATR)
    "brk_atr": 1.0,
    "brk_vol_x": 1.5,     # ... with its bar's volume >= 1.5 x the median 5-minute volume of the window
    "brk_fresh_bars": 3,  # ... at most 3 bars after the excursion began (a slow grind is no break)
    "touch_tol": 0.03,    # a retest touch: a swing low within the flip zone +-3 %; a close under its low x 0.97 fails
    "touches": 2,
    "hold_s": 24 * 3600,  # a flip / pause state ends 24 h after its break
    "max_gap_s": 3600,    # a previous pass older than this: its zones are stale, no break is read against them
    "alt_min_h": 1.0,     # the range after a break needs >= 1 h of candles after it
    "res_tol": 0.03,      # resume: the new range's range_high_top <= the resistance's top x 1.03
    "stop_k": 1.5, "stop_min": 0.05, "stop_max": 0.20,
}
FLIP_STATES = ("normal", "flip_candidate", "flipped", "paused", "resumed")
FLIP_BLOCKED = ("flip_candidate", "paused")
ZONE4 = ("range_low_low", "range_low_top", "range_high_low", "range_high_top")
_NO_PAIR = ("nema raspona", "raspon preuzak", "premalo podataka")


def _fcfg(cfg):
    return {**FLIP, **((cfg or {}).get("flip") or {})}


def bars(candles, bar_s, now):
    """[[start, o, h, l, c, v]] epoch-aligned buckets of bar_s seconds of the candles, oldest first, only the complete
    ones (start + bar_s <= now). h / l are the highs and lows of the candles' BODIES (like the pivots: a one-print wick
    is not the bar's range, and a snapshot series has no wicks at all, so both sources give the same ATR)."""
    out, cur = [], None
    for c in candles:
        b = int(c[0]) - int(c[0]) % bar_s
        if b + bar_s > now:
            break
        bh, bl = max(c[1], c[4]), min(c[1], c[4])
        if cur is None or cur[0] != b:
            cur = [b, c[1], bh, bl, c[4], c[5] or 0.0]
            out.append(cur)
        else:
            cur[2], cur[3], cur[4] = max(cur[2], bh), min(cur[3], bl), c[4]
            cur[5] += c[5] or 0.0
    return out


def atr(candles, now, cfg=None):
    """Mean true range (price) of the last atr_n complete atr_bar_s bars, against the previous bar's close; None
    with fewer than atr_min_bars bars."""
    c = _fcfg(cfg)
    bs = bars(candles, c["atr_bar_s"], now)
    trs = [max(b[2], p[4]) - min(b[3], p[4]) for p, b in zip(bs, bs[1:])][-c["atr_n"]:]
    if len(trs) < c["atr_min_bars"]:
        return None
    return sum(trs) / len(trs)


def vol_stop(rll, atr_px, cfg=None):
    """(stop price, kind): range_low_low - stop_k x ATR, held between stop_max (20 %) and stop_min (5 %) under
    range_low_low ("atr"); without ATR today's range_low_low x 0.85 ("fixed")."""
    c = _fcfg(cfg)
    if not rll or rll <= 0:
        return None, None
    if not atr_px or atr_px <= 0:
        return rll * 0.85, "fixed"
    return min(rll * (1 - c["stop_min"]), max(rll * (1 - c["stop_max"]), rll - c["stop_k"] * atr_px)), "atr"


def breakout(zones, candles, t0, now, atr_px=None, cfg=None):
    """The break of these zones among the 5-minute bars that closed in (t0, now] (see the module text): {"dir" up |
    down, "ts" (bar start), "end", "close", "level", "margin", "vol_x", "confirmed"}; the first confirmed bar wins,
    else the first unconfirmed one; None when nothing broke (or the excursion began before the window's first bar)."""
    c = _fcfg(cfg)
    if not zones or not zones.get("range_high_top") or not zones.get("range_low_low"):
        return None
    rht, rll = zones["range_high_top"], zones["range_low_low"]
    m_up = max(c["brk_pct"] * rht, c["brk_atr"] * (atr_px or 0))
    m_dn = max(c["brk_pct"] * rll, c["brk_atr"] * (atr_px or 0))
    up, dn = rht + m_up, rll - m_dn
    bs = bars(candles, c["bar_s"], now)
    if not bs:
        return None
    vols = [b[5] for b in bs if b[5] > 0]
    med = statistics.median(vols) if vols else 0.0

    def side(b):
        return "up" if b[4] > up else "down" if b[4] < dn else None
    seen = None
    for i, b in enumerate(bs):
        if b[0] + c["bar_s"] <= t0:
            continue
        d = side(b)
        if not d:
            continue
        j = i
        while j > 0 and side(bs[j - 1]) == d:
            j -= 1
        if j == 0:   # no bar inside the range before this excursion in the window: no crossing seen
            continue
        vx = (b[5] / med) if med > 0 else None
        out = {"dir": d, "ts": int(b[0]), "end": int(b[0] + c["bar_s"]), "close": b[4], "level": up if d == "up" else dn,
               "margin": m_up if d == "up" else m_dn, "vol_x": round(vx, 2) if vx is not None else None,
               "confirmed": bool(vx is not None and vx >= c["brk_vol_x"] and i - j < c["brk_fresh_bars"])}
        if out["confirmed"]:
            return out
        seen = seen or out
    return seen


def retest_touches(zone, candles, t_from, now, cfg=None):
    """The retests of a flip zone: swing lows (pivots of the candles from t_from, confirmed by now) within the zone
    +-touch_tol, [{"ts", "px"}]."""
    c = _fcfg(cfg)
    lo, hi = zone["low"] * (1 - c["touch_tol"]), zone["top"] * (1 + c["touch_tol"])
    cs = [x for x in candles if t_from <= x[0] <= now]
    return [{"ts": p["ts"], "px": p["px"]} for p in pivots(cs) if p["kind"] == "L" and p["confirm_ts"] <= now
            and lo <= p["px"] <= hi and p["ts"] != cs[0][0]]   # the first candle is where the window starts, no swing


def post_range(candles, now, t_from, snap=None, cfg=None):
    """The range computed from the candles since t_from (the break) only: analyze() over that window, with a minimum
    history of alt_min_h (1 h), the window's first candle not taken for a swing point (it is where the window starts,
    not a turn of the price). The old zones are not kept."""
    c = _fcfg(cfg)
    hours = max(0.0, (int(now) - int(t_from)) / 3600)
    return analyze(candles, now, snap, {**(cfg or {}), "window_h": hours, "min_hist_h": c["alt_min_h"],
                                        "skip_edge_pivot": True})


def has_pair(r):
    """True when a computed range has a real pair of zones (valid top / bottom, ratio >= min_ratio)."""
    return bool(r and r.get("zones") and r.get("status") not in _NO_PAIR)


def _z4(z):
    return {k: z[k] for k in ZONE4} if z else None


def _alt_view(r, supply):
    """What the state keeps of the range after a break (compact: no touches, recoveries or components)."""
    if not r:
        return None
    z = r.get("zones")
    zz = None
    if z:
        zz = {**_z4(z), "range_high": z.get("range_high"), "range_low": z.get("range_low"),
              "mc": {k: round(z[k] * supply) if supply else None for k in ZONE4}}
    return {"status": r.get("status"), "active": bool(r.get("active")), "why": r.get("why") or "", "score": r.get("score"),
            "ratio": r.get("ratio"), "pos_pct": r.get("pos_pct"), "span_h": r.get("span_h"), "zones": zz,
            "bottom_touches": len((r.get("touches") or {}).get("bottom") or [])}


def flip_step(prev, res, candles, now, snap=None, cfg=None):
    """range_flip's state of one token after this pass (see the module text). prev: the state of the previous pass
    (None the first time; another version counts as none); res: analyze() of now (today's range, 24 h); candles:
    the series up to now. Returns the new state: v, state, ts, since, ver, brk, zone (flip zone or resistance),
    touches, alt (the range after the break), ref (the zones whose breaks the next pass watches), atr, stop_px,
    stop_kind, stop_rll, block (why no entry, None when entries may happen), seen (the last unconfirmed break), why
    (the last change, Croatian)."""
    c = _fcfg(cfg)
    now = int(now)
    prev = prev if prev and prev.get("v") == c["v"] and prev.get("state") in FLIP_STATES else None
    cs = [x for x in candles if x[0] <= now]
    supply = ((res or {}).get("metrics") or {}).get("supply") or (cfg or {}).get("supply")
    st = dict(prev) if prev else {"v": c["v"], "state": "normal", "since": now, "ver": 0, "brk": None, "zone": None,
                                  "touches": [], "alt": None, "ref": None, "seen": None, "why": ""}
    t0 = int(prev["ts"]) if prev else now - c["bar_s"]
    a = atr(cs, now, c)

    def go(state, why, **kw):
        st.update(state=state, why=why, ver=int(st.get("ver") or 0) + 1, **kw)
    if st["state"] != "normal" and st.get("brk") and now - int(st["brk"]["end"]) > c["hold_s"]:
        go("normal", "24 h od proboja: opet raspon zadnja 24 h", since=now, brk=None, zone=None, touches=[], alt=None)
    if st["state"] in ("normal", "flipped", "resumed") and prev and prev.get("ref") and now - t0 <= c["max_gap_s"]:
        b = breakout(prev["ref"], cs, t0, now, a, c)
        if b and b["confirmed"]:
            z = prev["ref"]
            if b["dir"] == "up":
                go("flip_candidate", f"potvrđen proboj gore (zatvaranje {b['close']:.6g}, volumen {b['vol_x']}x): stari "
                   "vrh je kandidat za novo dno", since=b["end"], brk=b, touches=[], alt=None,
                   zone={"low": z["range_high_low"], "top": z["range_high_top"]})
            else:
                go("paused", f"potvrđen proboj dolje (zatvaranje {b['close']:.6g}, volumen {b['vol_x']}x): pauza, staro "
                   "dno je otpor", since=b["end"], brk=b, touches=[], alt=None,
                   zone={"low": z["range_low_low"], "top": z["range_low_top"]})
        elif b:
            st["seen"] = b
    alt = None
    if st["state"] == "flip_candidate":
        z, b = st["zone"], st["brk"]
        fail = next((x for x in bars(cs, c["bar_s"], now) if x[0] >= b["end"] and x[4] < z["low"] * (1 - c["touch_tol"])),
                    None)
        if fail:
            go("normal", f"flip nije uspio: zatvaranje {fail[4]:.6g} ispod starog vrha", since=now, brk=None, zone=None,
               touches=[], alt=None)
        else:
            st["touches"] = [p["ts"] for p in retest_touches(z, cs, b["ts"], now, c)]
            if len(st["touches"]) >= c["touches"]:
                go("flipped", f"stari vrh je novo dno ({len(st['touches'])} retesta bez zatvaranja ispod)", since=now)
    if st["state"] in ("paused", "flipped", "resumed"):
        alt = post_range(cs, now, st["brk"]["ts"], snap, cfg)
    if st["state"] == "paused" and has_pair(alt) and \
            alt["zones"]["range_high_top"] <= st["zone"]["top"] * (1 + c["res_tol"]):
        go("resumed", f"novi raspon ispod otpora (vrh {alt['zones']['range_high_top']:.6g}, "
           f"{len(alt['touches']['bottom'])} dodira dna nakon proboja)", since=now)
    s = st["state"]
    force = res if s == "normal" else alt if s in ("flipped", "resumed") else None
    st["alt"] = _alt_view(alt, supply) if s in ("paused", "flipped", "resumed") else None
    st["ref"] = _z4(force["zones"]) if has_pair(force) else None
    st["atr"] = a
    px = ((res or {}).get("metrics") or {}).get("price")
    st["atr_pct"] = round(a / px, 4) if a and px else None
    st["stop_rll"] = st["ref"]["range_low_low"] if st["ref"] else None
    st["stop_px"], st["stop_kind"] = vol_stop(st["stop_rll"], a, c) if st["ref"] else (None, None)
    st["block"] = ("pauza nakon proboja dolje: nema novih ulaza dok se ispod otpora ne oblikuje novi raspon"
                   if s == "paused" else "proboj gore: čeka se retest starog vrha (2 dodira) prije ulaza"
                   if s == "flip_candidate" else None)
    st["ts"] = now
    return st


def flip_public(st, supply=None):
    """The state as the range JSON (range.db ranges.data "flip") and the MCP API show it: without ref, with market
    caps of the zone, the stop and the ATR."""
    if not st:
        return None

    def mc(px):
        return round(px * supply) if supply and px else None
    out = {k: v for k, v in st.items() if k != "ref"}
    if st.get("zone"):
        out["zone"] = dict(st["zone"], mc_low=mc(st["zone"]["low"]), mc_top=mc(st["zone"]["top"]))
    out["stop_mc"] = mc(st.get("stop_px"))
    out["atr_mc"] = mc(st.get("atr"))
    return out
