"""Entry, lot 2 (DCA) and exit rules of range_dca (spec 3 and 4). Pure: the trader (rangedca/trade.py) and the
backtest (rangedca/backtest.py) call the same functions, so a backtest number is the rule that would trade.

Entry, lot 1: the price in the bottom 15 % of the range (range_low_low .. range_high_top) OR inside the bottom zone,
and not under range_low_low * 0.92; 5-minute change > -3 %; buys >= 50 % of the last 5 minutes' transactions; the
last 15 minutes' volume * 4 >= 50 % of the average hourly volume of the last 6 h; range_score >= 0.7 (0.6 / 0.8 in
the backtest's comparison); the range's own minimums (MC >= 30k, liquidity >= 20k, volume_1h >= 10k).
Lot 2: -10 % to -15 % from lot 1's price, still above range_low_low * 0.92, the volume ratio not under 0.5 (volume
not down more than half from the hourly average), buys >= 50 %. At most 2 lots; their SOL together at most the
dca cap (trade settings dca_token_cap).

Exit: half of the position when the price enters the top zone (range_high_low); the rest at range_high_top (sold
the moment the price is back under it after touching it), or when the price goes on above the top, on a 10 %
trailing stop from the peak. The trailing stop is armed from the first take profit on: the spec does not say what
happens when the price turns inside the top zone without reaching range_high_top, and without it the rest would
ride back down to the hard stop; 10 % under the peak keeps most of the move. Hard stop range_low_low * 0.85 (it only
ever tightens when the zones move); time stop: 6 h after lot 1 without touching the top zone, out as soon as the
price is at break-even (fees included) or better, else the hard stop decides. After a round, 20 minutes' cooldown;
the token stays a candidate.

11.11. (flag range_flip G26, detect.flip_step): new_range() is the range the NEW rules trade, from a computed range and
its "flip" block: state normal -> today's range with the volatility stop (range_low_low - 1.5 x ATR, 5-20 % under it);
flipped / resumed -> the range that formed after the break (its zones, score, status), with today's fresh 5-minute
numbers and the volatility stop on its range_low_low; flip_candidate / paused -> no range (no lot 1, no lot 2). A
range without a "flip" block (the flag was off when it was computed) is today's range unchanged. levels_of() takes a
range's own stop_px when it has one (only new_range sets it) and then never lets an entry or lot 2 under it (floor =
max(range_low_low x 0.92, stop)); without it the levels are today's.

11.11. (the owner's decision 1, "range stopovi", after HAOBIBI and the stop variants of rangedca/stops.py): the hard
stop of EVERY account is the ATR stop, variant (b), whatever range_flip's mode: atr_range() puts detect.vol_stop
(range_low_low - 1.5 x ATR, 5-20 % under it) on today's range, with the ATR run_range.py computes at every full
detection (ranges.data "atr", 14 x 15-minute bars). ATR unknown (fewer than 4 bars): x 0.85 as before ("fixed").
  real account (LEAGUE_USER)  the ATR stop, never a reclaim until gate.reclaim_refusal() is None (>= 7 nights of the
                              nightly stop comparison AND >= 20 closed demo reclaim rounds with EV > 0 after cost)
  demo account (PAPER_USER)   the ATR stop + reclaim: after a stop-out (or the "range broken downward" give-up) of a
                              round that was no reclaim itself, within RECLAIM["window_s"] (30 min) a lot 1 of a new
                              round (levels "reclaim": true, the stopped round's take-profit levels) when the 20-s pass's
                              price is back above range_low (the bottom zone's average) and buys >= 60 % of 5 minutes;
                              its stop = reclaim_stop(): under the NEW low (the lowest price the loops saw since the
                              stop-out) by the same ATR rule. Not after 30 min, not with buys under 60 %.
  event / market / paper_only tokens: only the demo account trades them (rangedca/trade.allowed), so b + reclaim.
stop_line() is the one log line per active range ("range stop SYM: pravi račun ATR MC ...").
"""
# 13.11. (owner, točka 3: "Na get_range_candidates i zonewatch spusti prag buy_share za entry_ready s 0.50 na 0.45 kako
# bi se poklapao s pravilima analitičara i zona-alarma"): the entry (entry_ready, zonewatch's range zones, the entry
# itself) 0.45; lot 2 keeps its 0.50 (lot2_buy_share_min: the owner's order is about the entry only)
RULES = {"score_min": 0.7, "entry_bottom": 0.15, "ch5_min": -0.03, "buy_share_min": 0.45, "vol_ratio_min": 0.5,
         "lot2_lo": 0.10, "lot2_hi": 0.15, "floor_x": 0.92, "stop_x": 0.85, "tp1_share": 0.5, "trail": 0.10,
         "time_stop_s": 6 * 3600, "cooldown_s": 20 * 60, "lot2_min_share": 0.5, "lot2_buy_share_min": 0.5,
         "exclude_s": 24 * 3600, "breakdowns_max": 2, "vol_exclude_s": 3600}

# 14.11. (owner: "otvaraj pozicije ... koji su u donjem dijelu range-a. Testiraj sa stop loss, nemoj stavljati preblizu
# stop loss zbog straha ... readjust parametre tako da se ulazi u trade I da se uzima barem 10-15% profita"; flag
# range_demo G32, the DEMO account only, never real money: trade/settings.NEVER_LIVE). The profile the demo account
# PAPER_USER trades on top of RULES (rangedca/trade.profile); the real account keeps RULES exactly. Every number was
# chosen on the backtest (rangedca/backtest.DemoCompare; 14.11.: the 6 range fixtures, 12.5 token-days, and 17 bonded
# tokens alive on 14.11. with GeckoTerminal minutes of the last ~50 h incl. the crash night, 74.5 token-days; ticks
# wick, the ATR stop, the owner's round-trip cost): RULES 14 rounds, hit 71 %, EV +7.8 % a round, PnL +17.2 $, DD 3.4 $;
# DEMO 37 rounds, hit 60 %, EV +3.2 %, PnL +17.8 $, DD 7.9 $ (2.6x the trades, EV still > 0):
#   entry   score_min 0.6, the bottom 25 % of the range (or inside the bottom zone), 5-minute change > -5 %, the 15-minute
#           volume x 4 >= 35 % of the hourly average, buys >= 45 % of 5 minutes (unchanged). survivor "loss": a token
#           whose MC is more than 45 % under the level 24 h ago (it did not survive the crash) is never entered; the
#           full survivor (rangedca/survivor: also >= 24 h old) is tried first and shown, not required: required
#           ("survivor": True) it cut the rounds 37 -> 18 and EV +3.2 -> +0.7 % (the age rule threw out good young ranges)
#   exits   half at +10 % NET of the round-trip cost (tp1_net); the rest at +15 % net or the range's top zone when
#           that is higher (tp2_range: "barem", at least; a fixed +15 % gave EV +1.6 %), else a 15 % trailing stop from
#           the peak (10 % cut the rest early: EV +2.5 %), else break-even (the rest's own cost, fees included) once TP1
#           sold (be_after_tp1)
#   stop    the ATR stop (decision 1) held between -12 % and -25 % from the entry price (stop_min_pct / stop_max_pct):
#           closer, a memecoin's 15-minute noise (ATR 5-10 % of the price) stops good entries out (-8..-20 %: twice the
#           stop-outs on the 17 tokens, EV +0.5 %); wider than -25 % one loss eats ~2 wins
#   lot 2   none (lot2 False): a second lot 10-15 % under lot 1 lands at or under a -12 % stop (with it: DD 4.1 -> 6.6 $)
#   time    6 h without TP1: out at break-even or better (RULES' time stop; 3 h / 12 h changed nothing)
DEMO = {**RULES, "profile": "demo", "score_min": 0.6, "entry_bottom": 0.25, "ch5_min": -0.05, "vol_ratio_min": 0.35,
        "buy_share_min": 0.45, "tp1_net": 0.10, "tp2_net": 0.15, "tp2_range": True, "tp1_share": 0.5, "trail": 0.15,
        "be_after_tp1": True, "stop_min_pct": 0.12, "stop_max_pct": 0.25, "lot2": False, "survivor": "loss"}
DEMO_GOAL = 5   # 14.11. (owner: "želim da danas otvoriš barem 5 tradeova"): the daily counter's goal


def exclusions(prev, res, now, holder_why=None, cfg=None):
    """Spec 5, give up / exclude a token. prev: the token's state from the last detection ({} the first time); res:
    detect.analyze of now; holder_why: the transfer holders' net selling when that rule acts (rangedca/holders.py).
    Returns the new state: breakdowns (timestamps of the last 24 h), was_broken, excluded_until, excluded_why and
    give_up {why, ts} (the trader closes a round opened before give_up.ts). Rules:
      two local lows in a row each < the previous * 0.97          -> excluded 24 h, open rounds out
      volume of the last hour < half of the 6 h hourly average   -> no entry for 1 h (renewed while it lasts), out
      transfer holders net-selling > 2 % of supply in 15 min     -> excluded 24 h, out (only RANGE_HOLDER_RULE=act)
      the range broken downward (price < range_low_low * 0.92) twice within 24 h -> excluded 24 h, out
    """
    c = _r(cfg)
    now = int(now)
    st = {"breakdowns": [t for t in (prev or {}).get("breakdowns") or [] if now - t < 86400],
          "was_broken": bool((prev or {}).get("was_broken")),
          "excluded_until": int((prev or {}).get("excluded_until") or 0),
          "excluded_why": (prev or {}).get("excluded_why") or "",
          "give_up": (prev or {}).get("give_up")}
    sig = (res or {}).get("signals") or {}
    broken = bool(sig.get("broken_down"))
    pz = (prev or {}).get("zones")
    price = ((res or {}).get("metrics") or {}).get("price")
    if not broken and pz and price:   # against the range as it was before this pass (the zones move after a break)
        broken = price < pz["range_low_low"] * c["floor_x"]
    if broken and not st["was_broken"]:
        st["breakdowns"].append(now)
    st["was_broken"] = broken
    why, until = None, 0
    if len(st["breakdowns"]) >= c["breakdowns_max"]:
        why, until = f"raspon probijen dolje {len(st['breakdowns'])} puta u 24 h", now + c["exclude_s"]
    elif sig.get("lower_lows"):
        why, until = "dva niža dna zaredom (svako ispod prethodnog × 0,97)", now + c["exclude_s"]
    elif holder_why:
        why, until = holder_why, now + c["exclude_s"]
    elif sig.get("vol_decline"):
        why, until = "volumen zadnjeg sata pao ispod pola prosjeka 6 h", now + c["vol_exclude_s"]
    if why and st["excluded_until"] <= now:
        st.update(excluded_until=until, excluded_why=why, give_up={"why": why, "ts": now})
    elif why and why == st["excluded_why"] and until > st["excluded_until"] and "volumen" in why:
        st["excluded_until"] = until   # the volume rule lasts while the volume stays low
    st["zones"] = (res or {}).get("zones") or pz
    return st


def apply_exclusion(res, st, now):
    """res with active False and the status "isključen" while the token is excluded."""
    if st.get("excluded_until", 0) > now and res.get("active"):
        res = dict(res, active=False, status="isključen", why=st.get("excluded_why") or "isključen")
    return res


def _r(cfg):
    return {**RULES, **(cfg or {})}


def levels_of(rng):
    """The exit / entry levels (prices) of a computed range: rll, rlt, rhl, rht, stop_px, floor_px. A range with its
    own stop_px (new_range, flag range_flip) keeps that stop, stop_kind with it, and its floor is never under it."""
    z = rng["zones"]
    out = {"rll": z["range_low_low"], "rlt": z["range_low_top"], "rhl": z["range_high_low"], "rht": z["range_high_top"],
           "stop_px": z["range_low_low"] * RULES["stop_x"], "floor_px": z["range_low_low"] * RULES["floor_x"]}
    if rng.get("stop_px"):
        out.update(stop_px=rng["stop_px"], floor_px=max(out["floor_px"], rng["stop_px"]),
                   stop_kind=rng.get("stop_kind") or "atr")
    return out


def demo_levels(lv, entry_px, rt_cost, cfg=None):
    """14.11. (DEMO): the levels of a demo round from the range's levels (levels_of, the ATR stop on them) and its
    entry price: tp1_px / tp2_px = entry x (1 + tp_net) / (1 - round-trip cost) (+10 % / +15 % NET: what the sale
    returns over what the lot cost, fees and AMM impact included), the stop held between -stop_max_pct (25 %) and
    -stop_min_pct (12 %) from the entry (stop_clamp, kept for the whole round), the floor never under the stop,
    profile "demo" and be_after_tp1. rt_cost: trade/cost.round_trip(lot USD, liquidity) as a fraction."""
    c = {**DEMO, **(cfg or {})}
    out = dict(lv)
    rt = min(max(float(rt_cost or 0.0), 0.0), 0.5)
    lo, hi = entry_px * (1 - c["stop_max_pct"]), entry_px * (1 - c["stop_min_pct"])
    out["tp1_px"] = entry_px * (1 + c["tp1_net"]) / (1 - rt)
    out["tp2_px"] = entry_px * (1 + c["tp2_net"]) / (1 - rt)
    raw = lv.get("stop_px") or lo
    out["stop_px"] = min(hi, max(lo, raw))
    if out["stop_px"] != raw:
        out["stop_kind"] = f"{lv.get('stop_kind') or 'fixed'}_clamp"
    out["stop_clamp"] = [lo, hi]
    out["floor_px"] = max(lv.get("floor_px") or 0.0, out["stop_px"])
    out.update(profile="demo", be_after_tp1=bool(c["be_after_tp1"]), entry_px=entry_px, rt_cost=round(rt, 5),
               tp2_range=bool(c.get("tp2_range")))
    return out


def tp2_of(lv):
    """The price the rest of a demo round sells at: tp2_px (+15 % net), or with tp2_range the range's top zone when
    that is higher (range_high_low of the range in force: "barem 10-15 %", at least, never less)."""
    if lv.get("tp2_range") and lv.get("rhl"):
        return max(lv["tp2_px"], lv["rhl"])
    return lv["tp2_px"]


def levels_in_force(frozen, fresh):
    """merge_levels for any round. 14.11. (DEMO): a demo round keeps its own take-profit prices (fresh ranges never
    move them: they are the entry's +10 / +15 % net) and its stop stays inside its clamp: it tightens with the newer
    range, but never closer than -stop_min_pct (12 %) to the entry."""
    out = merge_levels(frozen, fresh)
    if (frozen or {}).get("profile") == "demo":
        for k in ("tp1_px", "tp2_px", "tp2_range", "be_after_tp1", "profile", "stop_clamp", "entry_px", "rt_cost"):
            if k in frozen:
                out[k] = frozen[k]
        clamp = frozen.get("stop_clamp")
        if clamp and out.get("stop_px") and out["stop_px"] > clamp[1]:
            out["stop_px"] = clamp[1]
            out["stop_kind"] = frozen.get("stop_kind") or out.get("stop_kind")
        out["floor_px"] = max(out.get("floor_px") or 0.0, out.get("stop_px") or 0.0)
    return out


def profile_cfg(levels):
    """The rule set of an open round: DEMO for a demo-profile round (levels "profile": "demo"), else None (RULES)."""
    return DEMO if (levels or {}).get("profile") == "demo" else None


FLIP_PARTS = ("flip", "atr")


def new_range(rng, parts=FLIP_PARTS):
    """The range the new rules (flag range_flip) trade, from a computed range with its "flip" block (see the module
    text); parts: "flip" (the flip / pause states) and / or "atr" (the volatility stop), both by default (the
    backtest measures each alone). Returns a range dict (with stop_px / stop_kind when "atr" and ATR is known; a
    blocked one has active False, zones None and flip_block = why) or the range itself without a "flip" block."""
    if not rng:
        return rng
    fl = rng.get("flip")
    if not fl:
        return rng
    from . import detect
    s = fl.get("state")
    if "flip" in parts and s in detect.FLIP_BLOCKED:
        why = fl.get("block") or s
        return {**{k: rng.get(k) for k in ("ts", "mts", "metrics", "symbol", "state", "source", "sources", "flip")},
                "active": False, "status": s, "why": why, "flip_block": why, "zones": None, "score": None,
                "pos_pct": None, "ratio": None, "signals": {}}
    out = dict(rng)
    alt = fl.get("alt") if "flip" in parts and s in ("flipped", "resumed") else None
    if "flip" in parts and s in ("flipped", "resumed"):
        excluded = rng.get("status") == "isključen"
        z = (alt or {}).get("zones")
        out.update(zones=z, score=(alt or {}).get("score"), ratio=(alt or {}).get("ratio"),
                   status="isključen" if excluded else (alt or {}).get("status") or s,
                   active=bool(z and (alt or {}).get("active") and not excluded),
                   why=rng.get("why") if excluded else (alt or {}).get("why") or ("" if z else
                                                                                 "novi raspon nakon proboja još nije oblikovan"),
                   touches=None, components=None, recoveries=[], flip_range=s)
        px = (rng.get("metrics") or {}).get("price")
        out["pos_pct"] = (round((px - z["range_low_low"]) / (z["range_high_top"] - z["range_low_low"]) * 100, 1)
                          if z and px and z["range_high_top"] > z["range_low_low"] else None)
    if "atr" in parts and out.get("zones") and fl.get("atr"):
        out["stop_px"], out["stop_kind"] = detect.vol_stop(out["zones"]["range_low_low"], fl["atr"])
    return out


def flip_block(rng):
    """Why the new rules take no entry in this range's token now (flip_candidate / paused), None otherwise."""
    fl = (rng or {}).get("flip") or {}
    from . import detect
    return (fl.get("block") or fl.get("state")) if fl.get("state") in detect.FLIP_BLOCKED else None


def merge_levels(frozen, fresh):
    """The levels in force for an open round: the newest range's take-profit levels when it is still known, the stop
    never looser than the one at the entry (it only tightens); stop_kind follows the stop that won."""
    if not fresh:
        return dict(frozen)
    out = dict(fresh)
    out["stop_px"] = max(frozen.get("stop_px") or 0, fresh.get("stop_px") or 0)
    if (frozen.get("stop_px") or 0) >= (fresh.get("stop_px") or 0):
        if frozen.get("stop_kind"):
            out["stop_kind"] = frozen["stop_kind"]
        else:
            out.pop("stop_kind", None)
    return out


# ---------- 11.11. the owner's decision 1: the ATR stop for every account, reclaim on the demo account -----------------
RECLAIM = {"window_s": 30 * 60, "buy_share_min": 0.6}


def atr_of(rng):
    """The range's ATR in price (ranges.data "atr", run_range.py), None when unknown."""
    try:
        a = float((rng or {}).get("atr") or 0)
    except (TypeError, ValueError):
        return None
    return a if a > 0 else None


def atr_range(rng):
    """Variant (b) on a range: the range with stop_px / stop_kind of detect.vol_stop(range_low_low, ATR). A range that
    already carries its own stop (rules.new_range), has no zones or no known ATR is returned as it is (x 0.85)."""
    if not rng or not rng.get("zones") or rng.get("stop_px"):
        return rng
    a = atr_of(rng)
    if not a:
        return rng
    from . import detect
    out = dict(rng)
    out["stop_px"], out["stop_kind"] = detect.vol_stop(rng["zones"]["range_low_low"], a)
    return out


def reclaim_stop(low, atr_px):
    """(stop price, kind) of a reclaim round: under the new low by the ATR rule (detect.vol_stop on the low: low - 1.5 x
    ATR, 5-20 % under it; ATR unknown: low x 0.85)."""
    from . import detect
    s, kind = detect.vol_stop(low, atr_px)
    return s, ("reclaim" if kind == "atr" else "reclaim_fixed")


def reclaim_check(arm, price, m, now, cfg=None):
    """None when a reclaim lot 1 may be bought now, else why. arm: the stopped round's state "reclaim" ({until, rl,
    low, done}); m: the range's FRESH 5-minute numbers (None when stale or unknown)."""
    c = {**RECLAIM, **(cfg or {})}
    if not arm or arm.get("done"):
        return "nema reclaima"
    if now > (arm.get("until") or 0):
        return f"više od {c['window_s'] // 60} min od stopa"
    if not price or price <= (arm.get("rl") or 0):
        return "cijena nije iznad range_low"
    bs = (m or {}).get("buy_share_5m")
    if bs is None:
        return "udio kupnji u 5 min nepoznat (ili star)"
    if bs < c["buy_share_min"] - 1e-9:
        return f"kupnje {bs:.0%} transakcija u 5 min (reclaim traži {c['buy_share_min']:.0%})"
    return None


def stop_parts(rng):
    """{"atr_px", "stop_px", "kind", "old_px", "rll_px"} of a computed range under the owner's decision 1 (None without
    zones): the ATR stop of every account and today's old x 0.85 next to it."""
    z = (rng or {}).get("zones") or {}
    rll = z.get("range_low_low")
    if not rll:
        return None
    lv = levels_of(atr_range(rng) if rng.get("zones") else rng)
    return {"atr_px": atr_of(rng), "stop_px": lv["stop_px"], "kind": lv.get("stop_kind") or "fixed",
            "old_px": rll * RULES["stop_x"], "rll_px": rll}


def _mc3(px, supply):
    """A price as a market cap rounded to 3 significant digits ("$88,600"); "?" unknown."""
    if not px or not supply:
        return "?"
    return f"${float(f'{px * supply:.3g}'):,.0f}"


def stop_line(sym, rng):
    """The one log line of a range's stops (decision 1): "range stop SYM: pravi račun ATR MC $X (range_low_low $Y, ATR
    $Z) · demo ATR+reclaim · staro 0,85 $W" (3 significant digits, so it changes only when a level really moves);
    None without zones or supply."""
    sp = stop_parts(rng)
    sup = ((rng or {}).get("metrics") or {}).get("supply")
    if not sp or not sup:
        return None
    if sp["kind"] == "atr":
        real = (f"pravi račun ATR MC {_mc3(sp['stop_px'], sup)} (range_low_low {_mc3(sp['rll_px'], sup)}, ATR "
                f"{_mc3(sp['atr_px'], sup)})")
    else:
        real = (f"pravi račun ATR nepoznat, × 0,85 MC {_mc3(sp['stop_px'], sup)} (range_low_low "
                f"{_mc3(sp['rll_px'], sup)})")
    return f"range stop {sym}: {real} · demo ATR+reclaim · staro 0,85 {_mc3(sp['old_px'], sup)}"


def entry_check(rng, price, cfg=None, min_score=None):
    """None when lot 1 may be bought at `price`, else the reason in Croatian."""
    c = _r(cfg)
    if not rng or not rng.get("active"):
        return (rng or {}).get("why") or (rng or {}).get("status") or "nema aktivnog raspona"
    smin = c["score_min"] if min_score is None else min_score
    sc = rng.get("score") or 0
    if sc < smin - 1e-9:
        return f"ocjena raspona {sc:.2f} ispod {smin:.2f}"
    if c.get("survivor"):   # 14.11. (DEMO): only a token that survived the crash and is back in its range
        sv = rng.get("survivor")
        if not sv:
            return "preživljavanje pada nepoznato (raspon izračunat prije 14.11.)"
        if c["survivor"] == "loss":   # only the crash itself blocks (MC > 45 % under the level 24 h ago)
            if sv.get("crashed"):
                return sv.get("why") or "nije preživio pad"
        elif not sv.get("ok"):
            return sv.get("why") or "nije preživio pad"
    if not price or price <= 0:
        return "nema cijene"
    lv = levels_of(rng)
    if price < lv["floor_px"]:
        return "cijena ispod range_low_low × 0,92"
    span = lv["rht"] - lv["rll"]
    pos = (price - lv["rll"]) / span if span > 0 else 1.0
    if not (pos <= c["entry_bottom"] or lv["rll"] <= price <= lv["rlt"]):
        return f"cijena na {pos:.0%} raspona (ulaz u donjih {c['entry_bottom']:.0%} ili u donjoj zoni)"
    m = rng.get("metrics") or {}
    if m.get("ch_5m") is None:
        return "promjena 5 min nepoznata"
    if m["ch_5m"] <= c["ch5_min"]:
        return f"pada {m['ch_5m']:+.1%} u 5 min (granica {c['ch5_min']:+.0%})"
    if m.get("buy_share_5m") is None:
        return "udio kupnji u 5 min nepoznat"
    if m["buy_share_5m"] < c["buy_share_min"]:
        return f"kupnje {m['buy_share_5m']:.0%} transakcija u 5 min (treba {c['buy_share_min']:.0%})"
    if m.get("vol_ratio") is None or m["vol_ratio"] < c["vol_ratio_min"]:
        vr = m.get("vol_ratio")
        return (f"volumen 15 min je {vr:.0%} prosjeka sata" if vr is not None else "volumen nepoznat") + \
            f" (treba {c['vol_ratio_min']:.0%})"
    return None


def lot2_check(lot1_px, price, lv, m, cfg=None):
    """None when lot 2 may be bought, else the reason. lv: levels in force, m: the fresh metrics."""
    c = _r(cfg)
    if not price or not lot1_px:
        return "nema cijene"
    drop = 1 - price / lot1_px
    if drop < c["lot2_lo"] - 1e-9:
        return f"tek {drop:.1%} ispod prvog ulaza (lot 2 na -{c['lot2_lo']:.0%} do -{c['lot2_hi']:.0%})"
    if drop > c["lot2_hi"] + 1e-9:
        return f"već {drop:.1%} ispod prvog ulaza, dublje od -{c['lot2_hi']:.0%}: bez lota 2"
    if price <= lv["floor_px"]:
        return "cijena ispod range_low_low × 0,92"
    m = m or {}
    if m.get("vol_ratio") is None or m["vol_ratio"] < c["vol_ratio_min"]:
        return "volumen pao više od pola od prosjeka sata"
    if m.get("buy_share_5m") is None or m["buy_share_5m"] < c["lot2_buy_share_min"]:
        return f"kupnje ispod {c['lot2_buy_share_min']:.0%} transakcija u 5 min"
    return None


def lot_sizes(size_sol, cap_sol, held_sol=0.0, cfg=None):
    """SOL of the next lot under the dca cap (lot 1 + lot 2 <= cap): size_sol, less when the cap leaves less; 0 when
    what is left is under lot2_min_share of a lot (not worth a swap)."""
    c = _r(cfg)
    left = max(0.0, (cap_sol or size_sol * 2) - held_sol)
    lot = min(size_sol, left)
    return lot if lot >= size_sol * c["lot2_min_share"] - 1e-12 else 0.0


def exit_step(lv, st, price, now, opened_ts, be_px, stale=False, cfg=None):
    """One price tick of an open round. lv: levels in force (stop_px, rhl, rht); st: the round's state, changed in
    place (tp1, top_ts, top_active, peak); be_px: the price at which selling everything returns the cost (fees
    included). Returns (reason, fraction of what is left to sell) or None. A stale price fires only the stop."""
    c = _r(cfg)
    if price is None or price <= 0:
        return None
    if price <= lv["stop_px"]:
        return "stop", 1.0
    if stale:
        return None
    # 14.11. (DEMO): a round with its own take-profit prices (demo_levels: +10 % / +15 % net of cost from the entry)
    # takes them instead of the range's top zone / top
    tp1_px = lv.get("tp1_px") or lv["rhl"]
    if price >= tp1_px and not st.get("top_ts"):
        st["top_ts"] = int(now)
    if not st.get("tp1"):
        if price >= tp1_px:
            st["tp1"], st["peak"], st["top_active"] = True, price, price >= lv["rht"]
            return "tp1", c["tp1_share"]
        if not st.get("top_ts") and now - opened_ts >= c["time_stop_s"] and be_px and price >= be_px:
            return "time", 1.0
        return None
    if lv.get("tp2_px"):   # 14.11. (DEMO): the rest at +15 % net / the top zone, else trailing (15 %), else break-even
        st["peak"] = max(st.get("peak") or 0, price)
        if price >= tp2_of(lv):
            return "tp2", 1.0
        trail_px = st["peak"] * (1 - c["trail"])
        be = be_px if lv.get("be_after_tp1") and be_px else 0.0
        if price <= max(trail_px, be):   # the higher of the two levels is the one a falling price meets first
            return ("breakeven" if be > trail_px else "trailing"), 1.0
        return None
    st["peak"] = max(st.get("peak") or 0, price)
    if price >= lv["rht"]:
        st["top_active"] = True
    trail_px = st["peak"] * (1 - c["trail"])
    if st.get("top_active") and price < lv["rht"]:   # back under the top after touching it: the rest goes now
        return ("trailing" if trail_px > lv["rht"] else "top"), 1.0
    if price <= trail_px:
        return "trailing", 1.0
    return None
