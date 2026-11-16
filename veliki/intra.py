"""The intraday range rule of the midcaps (15.11. ~12:35 UTC, vlasnik: "Puno tokena 2M-200M je trending, ulazi
volumen; puno 10 % rangeova; do 100 tradeova dnevno s ~10 %, više tradeova po tokenu. Kreni pratiti DANAS").
Pure (no database, no clock): veliki/live.py trades it next to the 7-day rule (rule.py), the same functions decide in
an offline replay (simulate) and live.

Bars: 1h candles of the last LOOK_H (48 h) completed by the decision time t (GeckoTerminal 1h, and every hour that has
15m bars rebuilt from them: rule.h1_from_15m; the 15m bars are GeckoTerminal's, the midcap collector's 90-s DexScreener
snapshots and veliki/live's own quotes), at least MIN_H (12) of them; the trigger reads the last completed 15m bars.

Zone: lo = q10 of the lows, hi = q90 of the highs; valid when wide enough (hi / lo - 1 >= width_min 10 %), not a trend
(efficiency ratio of the closes <= er_max 0.5) and not sliding (last / first close - 1 >= drift_min -25 %).
Entry at a tick price px after a 15m bar completed (all of):
    px in the bottom `bottom` (25 %) of the zone: px <= lo + 0.25 x (hi - lo), and not under lo x (1 - below 3 %)
    the bars stopped falling: the last `calm` (2) completed 15m bars made no lower low than the bar before them, and
    the last close >= the close before it
    BTC not in a free fall (rule.Crash.regime "slobodan_pad")
    the round's caps: one position a token, cooldown COOLDOWN_S (30 min) after an exit, at most MAX_ROUNDS (3) rounds a
    token a Zagreb day
Exit (rule.on_price, the same as the 7-day rule): half at +tp (10 %) NET of the real round trip, the rest's stop to
break-even and a 5 % trailing from its peak; the stop under the zone's low (lo x 0.98), at most -12 % (stop_cap) and
at least 3 % under the entry; the time stop 24 h.
"""
import bisect

from veliki import rule

H, M15 = 3600, 900
LOOK_H = 48
MIN_H = 12
COOLDOWN_S = 30 * 60
MAX_ROUNDS = 3
CFG = {"tp": 10.0, "trail": 0.05, "half": 0.5, "time_h": 24, "bottom": 0.25, "below": 0.03, "calm": 2,
       "width_min": 0.10, "width_max": 0.80, "er_max": 0.50, "drift_min": -0.25, "q_lo": 0.10, "q_hi": 0.90,
       "stop_under": 0.02, "stop_cap": 0.12, "stop_min": 0.03, "look_h": LOOK_H, "min_h": MIN_H,
       "entry_slip": 0.002, "exit_slip": 0.002, "stop_slip": 0.005, "stop_fill": "level", "bar_s": M15}
KEY = "intra/tp10+pola/tr5/stop-zona/24h"


def cfg_of(over=None):
    return {**rule.RULE, **CFG, **(over or {})}


def zone(h1, t, cfg=None):
    """The intraday zone at t from the 1h candles completed by t within look_h: {ok, why, lo, hi, width, er, drift, n}."""
    c = cfg_of(cfg)
    w = [b for b in h1 if t - c["look_h"] * H <= b[0] and b[0] + H <= t]
    if len(w) < c["min_h"]:
        return {"ok": False, "why": f"premalo satnih svijeća u zadnjih {c['look_h']} h ({len(w)} od {c['min_h']})",
                "n": len(w)}
    lows, highs, closes = [b[3] for b in w], [b[2] for b in w], [b[4] for b in w]
    lo, hi = rule.quantile(lows, c["q_lo"]), rule.quantile(highs, c["q_hi"])
    if not lo or lo <= 0 or not hi:
        return {"ok": False, "why": "nema cijene", "n": len(w)}
    path = sum(abs(closes[i] - closes[i - 1]) for i in range(1, len(closes)))
    er = abs(closes[-1] - closes[0]) / path if path > 0 else 1.0
    z = {"lo": lo, "hi": hi, "width": hi / lo - 1, "er": er, "drift": closes[-1] / closes[0] - 1, "n": len(w),
         "s_lo": lo, "s_hi": lo + c["bottom"] * (hi - lo), "r_lo": hi, "r_hi": hi, "mid": (lo + hi) / 2}
    why = None
    if z["width"] < c["width_min"]:
        why = f"raspon preuzak ({z['width']:.1%})"
    elif z["width"] > c["width_max"]:
        why = f"raspon preširok ({z['width']:.0%})"
    elif er > c["er_max"]:
        why = f"trend, ne raspon (ER {er:.2f})"
    elif z["drift"] < c["drift_min"]:
        why = f"klizi dolje ({z['drift']:.0%})"
    z["ok"], z["why"] = why is None, why
    return z


def calm(b15, cfg=None):
    """(ok, why): the last `calm` completed 15m bars made no lower low than the bar before them and the last close is
    not under the one before it (the bars stopped falling)."""
    c = cfg_of(cfg)
    k = int(c["calm"])
    if len(b15) < k + 1:
        return False, "premalo 15m svijeća"
    last = b15[-k:]
    ref = b15[-k - 1]
    if min(b[3] for b in last) < ref[3]:
        return False, "još pada (novo niže dno u zadnjim svijećama)"
    if b15[-1][4] < b15[-2][4]:
        return False, "zadnje zatvaranje niže od prethodnog"
    return True, None


def signal(px, z, b15, cfg=None, btc_state=None):
    """None when the price px is an intraday entry under zone z and the completed 15m bars b15, else why (Croatian)."""
    c = cfg_of(cfg)
    if btc_state == "slobodan_pad":
        return "BTC slobodan pad: bez novih ulaza"
    if not z or not z.get("ok"):
        return (z or {}).get("why") or "nema zone"
    if px < z["lo"] * (1 - c["below"]):
        return "ispod dna zone (probija dolje)"
    if px > z["lo"] + c["bottom"] * (z["hi"] - z["lo"]):
        return f"nije u donjih {c['bottom']:.0%} zone"
    ok, why = calm(b15, c)
    return None if ok else why


def stop_px(entry, z, cfg=None):
    """Under the zone's low (lo x (1 - stop_under)), at most stop_cap (12 %) and at least stop_min (3 %) under the entry."""
    c = cfg_of(cfg)
    s = max(z["lo"] * (1 - c["stop_under"]), entry * (1 - c["stop_cap"]))
    return min(s, entry * (1 - c["stop_min"]))


def position(entry, ts, z, rt, cfg=None):
    """The open position dict rule.on_price / rule.exit_on_bar trade: target +tp net at the real round trip rt, the
    stop under the zone, the break-even after the half."""
    c = cfg_of(cfg)
    return {"entry": entry, "first": entry, "ts": ts, "tp_px": rule.tp_price(entry, c["tp"], rt, z, c),
            "stop_px": stop_px(entry, z, c), "be_px": rule.be_price(entry, rt, c)}


def owner_stop_bar(pos, bar, crash):
    """rule.OWNER_STOP on one bar of a replay (veliki/live.btc_stop on ticks): from what is known at the bar's open.
    BTC down: once an episode the stop goes `tight` under the bar's open (break-even when the open is above it) and
    the stop it replaces is remembered; BTC calm: that stop is back unless the +5 % rule armed break-even meanwhile."""
    down = rule.btc_down(crash, bar[0])[0]
    if down and not pos.get("tight"):
        pos["tight"] = True
        new = rule.tight_stop(bar[1], pos.get("be_px"))
        if new > pos["stop_px"]:
            pos["wide_prev"], pos["stop_px"] = pos["stop_px"], new
    elif not down and pos.get("tight"):
        pos["tight"] = False
        prev = pos.pop("wide_prev", None)
        if prev is not None and prev < pos["stop_px"] and not pos.get("be_armed"):
            pos["stop_px"] = prev


def simulate(b15, h1, rt, size_usd, cfg=None, crash=None, pit=None, zcache=None, ctx=None):
    """Offline replay on one token's 15m bars (and its 1h candles; None: rebuilt from the 15m): decide at each
    completed 15m bar's close, fill at the next bar's open; one position at a time, the cooldown and MAX_ROUNDS a UTC
    day. [{ts, out_ts, entry, exit, reason, ret, pnl, half, ret_demo, rt, fx, hours, mae, mfe, px0, z_lo, z_hi}]
    (walk.stats reads them; px0 = the signal's close, z_lo / z_hi = the zone of the entry).
    The hooks of veliki/replay.py (all off by default: today's behaviour): pit(t, px) False = no entry at that close
    (the point-in-time universe); zcache {t: zone} shared between calls whose cfg differs only in keys the zone's
    geometry does not read (bottom moves only its informational s_hi); cfg "reasoned" with ctx {"macro": fn(t) or
    None} = the reasoned exits veliki/live.manage makes on the bars' closes (rule.reasoned_exit: BTC free fall, the
    macro regime risk_off); the owner's exits are cfg keys (time_h None, be_at, full_tp; same_bar: rule.exit_on_bar)."""
    c = cfg_of(cfg)
    hh = rule.h1_from_15m(b15, h1)
    hts = [x[0] for x in hh]
    k = int(c["calm"])
    out, free_at, day_n = [], 0, {}
    i = k + 1
    while i < len(b15) - 1:
        t = b15[i][0] + M15
        d = t // 86400
        if t < free_at or day_n.get(d, 0) >= MAX_ROUNDS:
            i += 1
            continue
        if pit is not None and not pit(t, b15[i][4]):
            i += 1
            continue
        z = zcache.get(t) if zcache is not None else None
        if z is None:   # only the candles the zone reads (the same set zone() would pick out of all of them)
            z = zone(hh[bisect.bisect_left(hts, t - c["look_h"] * H):bisect.bisect_right(hts, t - H)], t, c)
            if zcache is not None:
                zcache[t] = z
        st = crash.regime(t)[0] if crash is not None else None
        if signal(b15[i][4], z, b15[i - k - 1:i + 1], c, st) is not None:   # calm() reads the last calm + 1 bars
            i += 1
            continue
        b = b15[i + 1]
        e = b[1] * (1 + c["entry_slip"])
        pos = position(e, b[0], z, rt, c)
        if c.get("owner_stop"):   # 16.11. popodne (rule.OWNER_STOP): the wide stop; tight from the start when BTC falls
            pos["stop_px"] = rule.wide_stop(e)
            if crash is not None and rule.btc_down(crash, b[0])[0]:
                pos["wide_prev"], pos["stop_px"], pos["tight"] = pos["stop_px"], rule.tight_stop(e, None), True
        day_n[d] = day_n.get(d, 0) + 1
        j, hit = i + 1, None
        lo = hi = e
        while j < len(b15):
            if c.get("owner_stop") and crash is not None and j > i + 1 and not pos.get("half_px"):
                owner_stop_bar(pos, b15[j], crash)
            hit = rule.exit_on_bar(pos, b15[j], c)
            lo, hi = min(lo, b15[j][3]), max(hi, b15[j][2])
            if hit:
                break
            if c.get("reasoned") and ctx is not None:
                rs, tight = rule.reasoned_exit(pos, b15[j][4], rt, rule._bt_ctx(ctx, b15[j][0] + M15, crash, j, [e]), c)
                if rs:
                    hit = (rs, b15[j][4] * (1 - c["exit_slip"]))
                    break
                if tight:
                    pos["stop_px"] = tight
            j += 1
        if not hit:
            j = len(b15) - 1
            hit = ("kraj", b15[-1][4] * (1 - c["exit_slip"]))
        r = rule.blend_ret(pos, hit[1], rt, c)
        out_ts = b15[j][0] + M15
        out.append({"ts": b[0], "out_ts": out_ts, "entry": e, "exit": hit[1], "reason": hit[0], "ret": r,
                    "pnl": r * size_usd, "half": bool(pos.get("half_px")), "ret_demo": r, "rt": rt,
                    "fx": hit[1] / e, "hours": round((out_ts - b[0]) / H, 2), "mae": round(lo / e - 1, 4),
                    "mfe": round(hi / e - 1, 4), "px0": b15[i][4], "z_lo": z["lo"], "z_hi": z["hi"]})
        free_at = out_ts + COOLDOWN_S
        i = j + 1
    return out
