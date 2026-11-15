"""The LOCKED measurement rules (the critic, 15.11.: "pravila mjerenja zaključati UNAPRIJED"). Version RULES_VERSION;
LOCKED holds every number; RULES_HASH is pinned in tests/test_makroinf_offline.py, so changing a rule after looking at
results needs a new version (and a new pinned hash), never a quiet edit. Outcomes are stored with rules_v.

Horizons (pre-registered): 7 d and 30 d. A call that STATES its horizon is tested on one bucket (<= 14 d -> 7 d,
<= 60 d -> 30 d, longer = "dugo", not scored in v1). A call WITHOUT a horizon is tested on BOTH, each with weight 0.5
(both are always reported; the better one is never picked).

Start: the first price point at or after the call (hourly when we have it, else the daily close). A CONDITIONAL call
("if BTC loses 60k -> 50k") starts only when the condition hits (the first point beyond trigger_level, in
trigger_dir) within cond_expiry_d days; never hit = "neaktiviran" (not scored), not yet = "ceka".

Threshold: thr_sigma x sigma_H, sigma_H = the std of the daily log returns of the 30 daily closes KNOWN at the call
time (points with ts <= t_call) x sqrt(H). Tests:
  up / down     hit: the H-day return >= +thr (down: <= -thr); miss: the opposite; else flat (not decided)
  range         hit: |return| < range_sigma sigma_H AND no excursion beyond range_excursion_sigma sigma_H; else miss
  bottom_in     miss: any point below p0 (1 - turn_breach_sigma sigma_H) in the window (a lower low = the bottom was not
                in, whatever came first); hit: else a point >= p0 (1 + turn_move_sigma sigma_H); else flat
  top_in        mirrored
  levels        (separate statistic) target touched before invalidation within H; both inside ONE bar = miss
                (conservative); neither = not reached
Episodes: repeated calls of one account on one asset with the same thesis (direction, condition), each within
episode_gap_d of the previous, are ONE prediction (the first call's time, horizon and levels). Thesis register:
aktivacija, ponavljanje, promjena (another thesis on the asset), povlacenje (the author withdraws), istek (no repeat
within episode_gap_d). Not scored: unclear / sarcasm, confidence joke, promo (counted under integrity), conditional
without a level.
Baselines on the SAME asset, start, horizon and threshold: always-bull (up; bottom_in for the turn calls), defined
random (0.5 x the bull test + 0.5 x the bear test: an expected value, no seed), 7-day trend-follow (the bull test when
the 7-day return KNOWN at the start is >= 0, else the bear test). Range calls have no baseline.
Follow return (economic value): +return for up / bottom_in, -return for down / top_in, minus the round-trip cost of
the asset (LOCKED cost); always-bull = +return - cost.
"""
import hashlib
import json
import math

RULES_VERSION = "pravila-v1 (15.11.2026.)"
D = 86400
LOCKED = {
    "horizons_d": [7, 30], "hz_short_max_d": 14, "hz_long_max_d": 60, "no_horizon": "oba (7 i 30, tezina 0,5)",
    "thr_sigma": 0.5, "vol_days": 30, "vol_min_pts": 20,
    "range_sigma": 0.5, "range_excursion_sigma": 1.0, "turn_breach_sigma": 0.5, "turn_move_sigma": 1.0,
    "cond_expiry_d": 30, "episode_gap_d": 14, "p0_hourly_within_h": 3, "p0_daily_within_h": 26, "end_gap_d": 2,
    "trend_days": 7,
    "cost": {"BTC": 0.002, "ETH": 0.002, "SOL": 0.003, "total": 0.002, "alts": 0.004, "memes": 0.01},
    "min_episodes": 10, "shrink_k": 10, "z": 1.96,
    "stance_h_d": {"7": 7, "30": 30, "oba": 30, "dugo": 60},
}
RULES_HASH = hashlib.sha256(json.dumps(LOCKED, sort_keys=True).encode()).hexdigest()[:12]
BULL = {"up": "up", "down": "up", "bottom_in": "bottom_in", "top_in": "bottom_in"}
BEAR = {"up": "down", "down": "down", "bottom_in": "top_in", "top_in": "top_in"}
SIGN = {"up": 1, "bottom_in": 1, "down": -1, "top_in": -1, "range": 0}


def bucket(horizon_days, L=LOCKED):
    if horizon_days is None:
        return "oba"
    if horizon_days <= L["hz_short_max_d"]:
        return "7"
    if horizon_days <= L["hz_long_max_d"]:
        return "30"
    return "dugo"


def horizons(hz):
    return {"7": [(7, 1.0)], "30": [(30, 1.0)], "oba": [(7, 0.5), (30, 0.5)], "dugo": []}[hz]


def _sig2(x):
    if not x:
        return None
    return float(f"{x:.2g}")


def thesis(c):
    if c.get("conditional"):
        if not c.get("trigger_level") or c.get("trigger_dir") not in ("below", "above"):
            return None
        return (c["direction"], c["trigger_dir"], _sig2(c["trigger_level"]))
    return (c["direction"],)


def skip_reason(c):
    if c.get("unclear"):
        return "nejasno"
    if c.get("confidence") == "joke":
        return "sala"
    if c.get("promo"):
        return "promocija"
    if c.get("conditional") and thesis(c) is None:
        return "uvjet_bez_razine"
    return None


def episodes(calls, now, L=LOCKED):
    """(episodes, register events, skipped {reason: n}) from call dicts (id, handle, asset, ts, avail_ts, direction,
    horizon_days, conditional, trigger_level, trigger_dir, target, invalidation, confidence, prob, promo, unclear,
    withdraws). Deterministic: the same calls give the same episodes."""
    gap = L["episode_gap_d"] * D
    eps, reg, skipped = [], [], {}
    by = {}
    for c in sorted(calls, key=lambda x: (x["handle"], x["asset"], x["ts"], str(x["id"]))):
        by.setdefault((c["handle"], c["asset"]), []).append(c)
    for (h, a), cs in by.items():
        cur = None

        def close(ep, ts, why):
            ep["closed_ts"], ep["closed_why"] = ts, why
            reg.append({"handle": h, "asset": a, "ts": ts, "event": why, "eid": ep["eid"]})

        for c in cs:
            if c.get("withdraws"):
                if cur is not None:
                    close(cur, c["ts"], "povlacenje")
                    cur = None
                continue
            why = skip_reason(c)
            if why:
                skipped[why] = skipped.get(why, 0) + 1
                continue
            key = thesis(c)
            if cur is not None and cur["key"] == key and c["ts"] - cur["last_ts"] <= gap:
                cur["n_calls"] += 1
                cur["last_ts"] = c["ts"]
                cur["ids"].append(str(c["id"]))
                reg.append({"handle": h, "asset": a, "ts": c["ts"], "event": "ponavljanje", "eid": cur["eid"]})
                continue
            if cur is not None:
                if cur["key"] != key and c["ts"] - cur["last_ts"] <= gap:
                    close(cur, c["ts"], "promjena")
                else:
                    close(cur, cur["last_ts"] + gap, "istek")
            cur = {"eid": f"{h}:{a}:{c['id']}", "handle": h, "asset": a, "direction": c["direction"], "key": key,
                   "t_call": int(c["ts"]), "avail": int(c.get("avail_ts") or c["ts"]), "first_id": str(c["id"]),
                   "ids": [str(c["id"])], "n_calls": 1, "last_ts": int(c["ts"]), "hz": bucket(c.get("horizon_days"), L),
                   "horizon_days": c.get("horizon_days"), "conditional": bool(c.get("conditional")),
                   "trigger_level": c.get("trigger_level"), "trigger_dir": c.get("trigger_dir"),
                   "target": c.get("target"), "invalidation": c.get("invalidation"), "prob": c.get("prob"),
                   "closed_ts": None, "closed_why": None}
            eps.append(cur)
            reg.append({"handle": h, "asset": a, "ts": c["ts"], "event": "aktivacija", "eid": cur["eid"]})
        if cur is not None and cur["last_ts"] + gap <= now:
            close(cur, cur["last_ts"] + gap, "istek")
    return eps, reg, skipped


def direction_test(direction, p0, p_end, path, s_h, L=LOCKED):
    """'hit' | 'miss' | 'flat' (see the module text). path: [price] inside the window (end included)."""
    r = p_end / p0 - 1
    thr = L["thr_sigma"] * s_h
    if direction == "up":
        return "hit" if r >= thr else "miss" if r <= -thr else "flat"
    if direction == "down":
        return "hit" if r <= -thr else "miss" if r >= thr else "flat"
    lo = min(path + [p_end]) / p0 - 1
    hi = max(path + [p_end]) / p0 - 1
    if direction == "range":
        exc = max(abs(lo), abs(hi))
        return "hit" if abs(r) < L["range_sigma"] * s_h and exc < L["range_excursion_sigma"] * s_h else "miss"
    if direction == "bottom_in":
        if lo < -L["turn_breach_sigma"] * s_h:
            return "miss"
        return "hit" if hi >= L["turn_move_sigma"] * s_h else "flat"
    if direction == "top_in":
        if hi > L["turn_breach_sigma"] * s_h:
            return "miss"
        return "hit" if lo <= -L["turn_move_sigma"] * s_h else "flat"
    return None


def level_test(bars, p0, target, invalidation):
    """'cilj' (target first) | 'invalidacija' (invalidation first, or both inside one bar: conservative) | 'nije'
    (neither) | None (no usable target). bars: [(ts, low, high)] in time order."""
    if not target or not p0 or target == p0:
        return None
    up = target > p0
    inv = invalidation if invalidation and ((invalidation < p0) if up else (invalidation > p0)) else None
    for _ts, lo, hi in bars:
        t_hit = hi >= target if up else lo <= target
        i_hit = inv is not None and (lo <= inv if up else hi >= inv)
        if t_hit and i_hit:
            return "invalidacija"
        if i_hit:
            return "invalidacija"
        if t_hit:
            return "cilj"
    return "nije"


def _start(ep, truth, now, L):
    """(t_start, p0, state) - state None when started, else ceka / neaktiviran / bez_podataka."""
    a = ep["asset"]
    s_d = truth.daily(a)
    if not s_d:
        return None, None, "bez_podataka"
    t = ep["t_call"]
    if ep["conditional"]:
        exp = t + L["cond_expiry_d"] * D
        s = truth.fine(a, t, exp)
        trig, dr = ep["trigger_level"], ep["trigger_dir"]
        for ts, p in s.window(t, exp):
            if (dr == "below" and p <= trig) or (dr == "above" and p >= trig):
                return ts, p, None
        return None, None, ("neaktiviran" if exp <= min(now, s.end()) else "ceka")
    h = truth.h.get(a)
    pt = h.first_at(t, L["p0_hourly_within_h"] * 3600) if h else None
    if pt is None:
        pt = s_d.first_at(t, L["p0_daily_within_h"] * 3600)
    if pt is None:
        return None, None, ("ceka" if t >= s_d.end() - D else "bez_podataka")
    return pt[0], pt[1], None


def evaluate(ep, truth, now, L=LOCKED):
    """[outcome dict] of one episode: one per tested horizon (none for "dugo": one row with res dugo, weight 0)."""
    base = {"eid": ep["eid"], "handle": ep["handle"], "asset": ep["asset"], "direction": ep["direction"],
            "t_call": ep["t_call"], "first_id": ep["first_id"], "n_calls": ep["n_calls"], "hz": ep["hz"],
            "prob": ep.get("prob"), "avail": ep.get("avail")}
    hs = horizons(ep["hz"])
    if not hs:
        return [{**base, "horizon": "dugo", "w": 0.0, "res": "dugo"}]
    t0, p0, state = _start(ep, truth, now, L)
    sigma = truth.vol(ep["asset"], ep["t_call"], L["vol_days"], L["vol_min_pts"])
    out = []
    for H, w in hs:
        o = {**base, "horizon": str(H), "w": w, "t_start": t0, "p0": p0}
        if state:
            out.append({**o, "res": state})
            continue
        if sigma is None:
            out.append({**o, "res": "bez_podataka"})
            continue
        t_end = t0 + H * D
        s = truth.fine(ep["asset"], t0, t_end)
        if t_end > now or t_end > s.end():
            out.append({**o, "res": "ceka"})
            continue
        end = s.known(t_end)
        if end is None or t_end - end[0] > L["end_gap_d"] * D:
            out.append({**o, "res": "bez_podataka"})
            continue
        s_h = sigma * math.sqrt(H)
        path = [p for _t, p in s.window(t0, t_end)]
        r = end[1] / p0 - 1
        d = ep["direction"]
        res = direction_test(d, p0, end[1], path, s_h, L)
        cost = L["cost"].get(ep["asset"], 0.005)
        sg = SIGN.get(d, 0)
        o.update(res=res, thr=round(L["thr_sigma"] * s_h, 6), ret=round(r, 6), done_ts=t_end,
                 follow=(round(sg * r - cost, 6) if sg else None),
                 level=level_test([(t, p, p) for t, p in s.window(t0, t_end)], p0, ep.get("target"),
                                  ep.get("invalidation")))
        if d in BULL:
            bull = direction_test(BULL[d], p0, end[1], path, s_h, L)
            bear = direction_test(BEAR[d], p0, end[1], path, s_h, L)
            tr = truth.trend(ep["asset"], t0, L["trend_days"])
            tr_test = None if tr is None else (bull if tr >= 0 else bear)
            o.update(b_bull=bull, b_rand_hit=0.5 * (bull == "hit") + 0.5 * (bear == "hit"),
                     b_rand_dec=0.5 * (bull in ("hit", "miss")) + 0.5 * (bear in ("hit", "miss")),
                     b_trend=tr_test, b_bull_follow=round(r - cost, 6),
                     b_trend_follow=(None if tr is None else round((1 if tr >= 0 else -1) * r - cost, 6)))
        out.append(o)
    return out


def stance_until(c, L=LOCKED):
    """Until when one call is the account's stance on the asset (the index): its horizon bucket's stance days."""
    return int(c["ts"]) + L["stance_h_d"][bucket(c.get("horizon_days"), L)] * D
