"""Paper-trade mechanics, no I/O: fill prices with fee + AMM price impact, and the exit rules.

The same `step` drives live paper trading (run_paper.py tick) and the replays in the daily review, so a
parameter the review suggests behaves exactly like the one that will trade tomorrow.
"""
import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

# Bumped whenever the exit mechanics change meaning, so the exit learner re-fits its rules under the new mechanics
# right away (exits.json keeps the version it was fitted with) instead of waiting for the next daily run.
# 2: the stop after a take profit only arms once the peak has cleared it (lock_gap), see after_tp_stop().
SIM_VERSION = 2


def load_config(path=None, learned=True):
    """paper/config.json plus the entry rules the daily review applied itself (paper/auto.py), unless a
    specific file is asked for or learned=False."""
    with open(path or CONFIG_PATH) as f:
        cfg = json.load(f)
    if path is None and learned:
        try:
            from . import auto
            cfg = auto.overlay(cfg)
        except Exception:
            pass
    return cfg


def impact(usd, liq):
    """Constant-product price impact: half the pool's liquidity sits on each side."""
    side = (liq or 0) / 2
    return usd / (side + usd) if side > 0 else 1.0


def open_position(price, liq, ts, size_usd, cfg):
    """Buy size_usd at market price; effective price is worse by fee + impact."""
    eff = price * (1 + cfg["fee"]) / (1 - impact(size_usd, liq))
    return {"entry_px": price, "entry_eff": eff, "entry_liq": liq, "opened_ts": ts, "size_usd": size_usd,
            "qty": size_usd / eff, "left": 1.0, "realized": 0.0, "peak": 0.0, "low": 0.0,
            "tp_done": 0, "open": True, "fills": []}


def sell(pos, frac, price, liq, ts, reason, cfg):
    """Sell `frac` of the original quantity (capped at what is left)."""
    frac = min(frac, pos["left"])
    if frac <= 0:
        return
    gross = pos["qty"] * frac * price
    net = gross * (1 - cfg["fee"]) * (1 - impact(gross, liq)) if price > 0 else 0.0
    pos["left"] = round(pos["left"] - frac, 9)
    pos["realized"] += net
    pos["fills"].append({"ts": ts, "price": price, "frac": frac, "usd": round(net, 4), "reason": reason})
    if pos["left"] <= 1e-9:
        pos["open"] = False
        pos["exit_reason"] = reason
        pos["closed_ts"] = ts


def trail_for(peak, cfg):
    """Trailing distance for the current peak. `trail_tiers` [[peak, trail], ...] widens it as the token grows, so a
    moonshot gets room to breathe; without tiers the single `trail` applies once the peak passes `trail_after`."""
    tiers = cfg.get("trail_tiers")
    if not tiers:
        return cfg["trail"] if peak >= cfg["trail_after"] else None
    use = None
    for level, tr in sorted(tiers):
        if peak >= level:
            use = tr
    return use


def after_tp_stop(pos, cfg):
    """Stop level (return vs. entry) for what is left after the first take profit, or None.

    A learned lock above the price where the take profit fired (e.g. TP at +10%, lock at +30%) used to sell the
    whole rest on the same tick, so every winner closed at ~+10% (31.10.: 11 of 12 demo winners; ANSEM kept 20%
    only because one candle jumped over every TP level). The lock now arms only once the peak is lock_gap above
    it; until then the rest is protected at breakeven (or at the lock, if that is below breakeven)."""
    lock = cfg.get("sl_after_tp")
    if lock is None and cfg.get("breakeven_after_tp"):
        lock = 0.0
    if lock is None or not pos.get("tp_done"):
        return None
    if (1 + pos.get("peak", 0.0)) >= (1 + lock) * (1 + cfg.get("lock_gap", 0.1)):
        return lock
    return min(lock, 0.0)


def _tp_frac(pos, frac, price, liq, cfg):
    """"cost" = sell just enough to get the stake back (the rest rides for free); a number = share of the buy."""
    if frac != "cost":
        return frac
    gross_all = pos["qty"] * price
    if gross_all <= 0:
        return 0
    need = (pos["size_usd"] - pos["realized"]) / ((1 - cfg["fee"]) * (1 - impact(pos["size_usd"], liq)))
    return max(0.0, min(pos["left"], need / gross_all))


def step(pos, price, liq, ts, cfg):
    """Apply one price observation. Fills at the observed price, so a gap through the stop costs extra,
    as it would for real.

    Moonbag (cfg moonbag > 0): once a take profit has locked in a gain, the last `moonbag` share of the buy is
    never sold by the normal exits; it rides with its own wide trailing stop (moon_trail) until rug or
    moon_hold_h, so a trade that already paid for itself keeps a ticket to a moonshot."""
    if not pos["open"]:
        return pos
    # rug: liquidity pulled, or the price dumped so far (rug_drop, default 70% below entry) that it is a rug, not a dip
    if price <= 0 or liq < cfg["rug_liq"] * pos["entry_liq"] or price <= pos["entry_px"] * (1 - cfg.get("rug_drop", 0.7)):
        sell(pos, 1.0, price, liq, ts, "rug", cfg)
        return pos
    ret = price / pos["entry_px"] - 1
    pos["peak"], pos["low"] = max(pos["peak"], ret), min(pos["low"], ret)
    age = ts - pos["opened_ts"]
    if pos.get("bag"):
        if (1 + ret) <= (1 + pos["peak"]) * (1 - cfg.get("moon_trail", 0.6)):
            sell(pos, 1.0, price, liq, ts, "moonbag_trailing", cfg)
        elif age >= cfg.get("moon_hold_h", cfg["max_hold_h"]) * 3600:
            sell(pos, 1.0, price, liq, ts, "moonbag_time", cfg)
        return pos
    if pos["tp_done"] == 0 and ret <= cfg["sl"]:
        sell(pos, 1.0, price, liq, ts, "stop_loss", cfg)
        return pos
    bag = cfg.get("moonbag") or 0
    for i, (level, frac) in enumerate(cfg["tp"]):
        if i >= pos["tp_done"] and ret >= level:
            f = _tp_frac(pos, frac, price, liq, cfg)
            if bag:
                f = min(f, max(0.0, pos["left"] - bag))
            sell(pos, f, price, liq, ts, f"take_profit_{level:g}x", cfg)
            pos["tp_done"] = i + 1
    if not pos["open"]:
        return pos
    # after a take profit with a moonbag, the normal exits sell down to the bag and the bag rides on
    rest = max(0.0, pos["left"] - bag) if (bag and pos["tp_done"]) else 1.0
    tr = trail_for(pos["peak"], cfg)
    # KOL wave: influencers called it in the last kol_hold_min minutes (caller sets pos["kol_until"]). After a call
    # a token often pumps, pauses and finds its rhythm: no "nothing happens" exit then, and a looser trail.
    kol = cfg.get("kol_hold_min") and pos.get("kol_until", 0) >= ts
    if kol and tr is not None:
        tr = min(0.9, tr + cfg.get("kol_trail_add", 0.0))
    after_tp = after_tp_stop(pos, cfg)  # stop for the rest after the first take profit (0 = breakeven)
    why = None
    if after_tp is not None and ret <= after_tp:
        why = "breakeven"
    elif tr is not None and (1 + ret) <= (1 + pos["peak"]) * (1 - tr):
        why = "trailing"
    elif (cfg.get("stale_min") and not kol and age >= cfg["stale_min"] * 60 and pos["tp_done"] == 0
          and pos["peak"] < cfg.get("stale_ret", 0.1)):
        why = "stale"  # nothing happened in the first minutes: the pump is not coming
    elif age >= cfg["max_hold_h"] * 3600:
        why = "time"
    if why:
        sell(pos, rest, price, liq, ts, why, cfg)
    if pos["open"] and bag and pos["tp_done"] and pos["left"] <= bag + 1e-9:
        pos["bag"] = True
    return pos


def result(pos, mark_price=None, mark_liq=None, cfg=None):
    """PnL in USD and as a return on size; an open position is marked at mark_price (as if sold now)."""
    value = pos["realized"]
    if pos["open"] and mark_price and cfg:
        gross = pos["qty"] * pos["left"] * mark_price
        value += gross * (1 - cfg["fee"]) * (1 - impact(gross, mark_liq))
    pnl = value - pos["size_usd"]
    return {"pnl_usd": round(pnl, 2), "ret": round(pnl / pos["size_usd"], 4), "max_ret": round(pos["peak"], 4),
            "min_ret": round(pos["low"], 4), "exit_reason": pos.get("exit_reason") or ("open" if pos["open"] else "")}


def kol_until(calls, ts, cfg):
    """Until when the newest influencer call at or before ts keeps the KOL hold on (0 = none)."""
    hold = cfg.get("kol_hold_min") or 0
    last = max((c for c in calls or () if c <= ts), default=None)
    return last + hold * 60 if (hold and last is not None) else 0


def replay(entry_price, entry_liq, entry_ts, path, cfg, size_usd=None, calls=None):
    """Simulate a whole trade over [(ts, price, liq), ...]; unfinished trades are marked at the last tick.
    calls: timestamps of influencer calls on the token (KOL hold)."""
    pos = open_position(entry_price, entry_liq, entry_ts, size_usd or cfg["size_usd"], cfg)
    last = (entry_ts, entry_price, entry_liq)
    for ts, price, liq in path:
        if ts <= entry_ts:
            continue
        if calls:
            pos["kol_until"] = kol_until(calls, ts, cfg)
        step(pos, price or 0, liq or 0, ts, cfg)
        last = (ts, price, liq)
        if not pos["open"]:
            break
    return result(pos, last[1], last[2], cfg)
