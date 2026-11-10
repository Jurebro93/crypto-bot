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
"""
RULES = {"score_min": 0.7, "entry_bottom": 0.15, "ch5_min": -0.03, "buy_share_min": 0.5, "vol_ratio_min": 0.5,
         "lot2_lo": 0.10, "lot2_hi": 0.15, "floor_x": 0.92, "stop_x": 0.85, "tp1_share": 0.5, "trail": 0.10,
         "time_stop_s": 6 * 3600, "cooldown_s": 20 * 60, "lot2_min_share": 0.5,
         "exclude_s": 24 * 3600, "breakdowns_max": 2, "vol_exclude_s": 3600}


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
    """The exit / entry levels (prices) of a computed range: rll, rlt, rhl, rht, stop_px, floor_px."""
    z = rng["zones"]
    return {"rll": z["range_low_low"], "rlt": z["range_low_top"], "rhl": z["range_high_low"], "rht": z["range_high_top"],
            "stop_px": z["range_low_low"] * RULES["stop_x"], "floor_px": z["range_low_low"] * RULES["floor_x"]}


def merge_levels(frozen, fresh):
    """The levels in force for an open round: the newest range's take-profit levels when it is still known, the stop
    never looser than the one at the entry (it only tightens)."""
    if not fresh:
        return dict(frozen)
    out = dict(fresh)
    out["stop_px"] = max(frozen.get("stop_px") or 0, fresh.get("stop_px") or 0)
    return out


def entry_check(rng, price, cfg=None, min_score=None):
    """None when lot 1 may be bought at `price`, else the reason in Croatian."""
    c = _r(cfg)
    if not rng or not rng.get("active"):
        return (rng or {}).get("why") or (rng or {}).get("status") or "nema aktivnog raspona"
    smin = c["score_min"] if min_score is None else min_score
    sc = rng.get("score") or 0
    if sc < smin - 1e-9:
        return f"ocjena raspona {sc:.2f} ispod {smin:.2f}"
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
    if m.get("buy_share_5m") is None or m["buy_share_5m"] < c["buy_share_min"]:
        return "kupnje ispod 50 % transakcija u 5 min"
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
    if price >= lv["rhl"] and not st.get("top_ts"):
        st["top_ts"] = int(now)
    if not st.get("tp1"):
        if price >= lv["rhl"]:
            st["tp1"], st["peak"], st["top_active"] = True, price, price >= lv["rht"]
            return "tp1", c["tp1_share"]
        if not st.get("top_ts") and now - opened_ts >= c["time_stop_s"] and be_px and price >= be_px:
            return "time", 1.0
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
